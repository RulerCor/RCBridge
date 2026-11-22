"""
入口与生命周期管理模块。

负责桥接的启动、停止、主循环重连逻辑，以及命令行入口。
"""

import logging
import threading

import state
import config
from senders import create_sender
from ob_client import _run_ob_client
from bridge_core import WeFlowBridge
from message_source import create_message_source

log = logging.getLogger("ob11-bridge")


# ============ 启动 / 停止 ============


def _start_bridge(*, auto_start=False):
    with state.run_lock:
        if state.running:
            return
        if state.ob_thread is not None and state.ob_thread.is_alive():
            raise ValueError("OneBot 客户端仍在停止，请稍后重试。")

        sender = create_sender()
        bridge = WeFlowBridge(sender)
        state.sender_instance = sender
        with state.bridge_lock:
            state.bridge_instance = bridge
        state.stop_event.clear()
        state.paused.clear()
        state.running = True
        state.bridge_thread = threading.Thread(target=_bridge_loop, args=(bridge,),
                                               kwargs={'wait_for_werc': auto_start},
                                               daemon=True, name="bridge")
        state.bridge_thread.start()
        log.info("[Web] 正在启动")


def _stop_bridge():
    with state.run_lock:
        state.running = False
        state.stop_event.set()

        # 切断 SSE 长连接，让 listen_sse() 从阻塞中退出。
        with state.bridge_lock:
            bridge = state.bridge_instance
            if bridge:
                bridge.stop_requested.set()
                if bridge._sse_session:
                    try:
                        bridge._sse_session.close()
                        log.info("[Web] SSE 连接已断开")
                    except Exception as e:
                        log.warning(f"[Web] 断开 SSE 异常: {e}")

        ws = state._ob_ws
        loop = state._ob_ws_loop
        if ws and loop and loop.is_running():
            try:
                import asyncio
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
                log.info("[Web] WebSocket 连接已关闭")
            except Exception as e:
                log.warning(f"[Web] 关闭 WebSocket 异常: {e}")

        state._ob_ws_ready.clear()
        thread = state.ob_thread
        if thread is not None:
            thread.join(timeout=5)
            if thread.is_alive():
                log.warning("[Web] OB 客户端线程未能及时退出，将在后台自行结束")
            else:
                state.ob_thread = None

        log.info("[Web] 已停止")


def _check_source(bridge, *, wait_for_werc):
    if config.MESSAGE_SOURCE == "weflow" and not config.ACCESS_TOKEN:
        log.error("❌ 未配置 access_token")
        return False
    if config.MESSAGE_SOURCE == "alpha" and not (config.ALPHA_BASE_URL and config.ALPHA_ACCESS_TOKEN):
        log.error("❌ 未配置 alpha_base_url / alpha_access_token")
        return False

    source = create_message_source()
    while not bridge.stop_requested.is_set():
        ok, status, msg = source.check()
        if ok:
            log.info(f"✅ {msg}")
            return True
        if not (wait_for_werc and source.name == 'werc' and (status in (0, 429) or 500 <= status < 600)):
            log.error(f"❌ {msg}")
            return False
        log.warning('自动启动：等待 WeRC 就绪（%s）', msg)
        if bridge.stop_requested.wait(5):
            break
    return False


def _bridge_loop(bridge, *, wait_for_werc=False):
    import ctypes
    ctypes.windll.ole32.CoInitialize(None)
    try:
        log.info(f"Bridge | 消息源: {config.MESSAGE_SOURCE.upper()} | "
                 f"OB11: {config.ASTRBOT_OB_URL} | 发送: {config.SEND_METHOD}")
        if not _check_source(bridge, wait_for_werc=wait_for_werc):
            return

        with state.run_lock:
            if bridge.stop_requested.is_set():
                return

            # 只有探测成功才启动 OneBot。失败的尝试不会创建客户端或留下启动标记。
            # 管理员名单同步失败不影响启动。
            try:
                import people
                if config.ASTRBOT_CONFIG_FILE and people.load_admins():
                    people.sync_admins_to_astrbot()
            except Exception as e:
                log.warning(f"管理员同步跳过: {e}")
            thread = threading.Thread(target=_run_ob_client, daemon=True, name="ob11-client")
            thread.start()
            state.ob_thread = thread
            log.info("[Web] 已启动")

        while not bridge.stop_requested.is_set():
            try:
                bridge.listen_sse()
            except Exception as e:
                log.error(f"SSE: {e}")
            if bridge.stop_requested.is_set():
                break
            log.warning("⚠️ SSE 断开，10s 后重连")
            if bridge.stop_requested.wait(10):
                break
    finally:
        with state.run_lock, state.bridge_lock:
            # 停止后若已再次启动，旧探测不能清除新实例的状态。
            if state.bridge_instance is bridge:
                state.bridge_instance = None
                state.stop_event.set()
                state.running = False
        ctypes.windll.ole32.CoUninitialize()
