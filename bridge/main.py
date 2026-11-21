"""
入口与生命周期管理模块。

负责桥接的启动、停止、主循环重连逻辑，以及命令行入口。
"""

import json
import logging
import os
import sys
import threading
import time

import requests

import state
import config
import exit_reason
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
        state.sender_instance = create_sender()
        state.running = True
    state.paused.clear()

    # 启动即把管理员名单（wxid → UID）重放一遍到 AstrBot 配置：
    # 桥接重启/换机后无需人工再同步。失败不影响启动。
    try:
        import people
        if config.ASTRBOT_CONFIG_FILE and people.load_admins():
            people.sync_admins_to_astrbot()
    except Exception as e:
        log.warning(f"管理员同步跳过: {e}")

    if not state.ob_client_started:
        t = threading.Thread(target=_run_ob_client, daemon=True, name="ob11-client")
        t.start()
        state.ob_thread = t
        state.ob_client_started = True

    state.stop_event.clear()
    state.bridge_thread = threading.Thread(target=_bridge_loop, kwargs={'wait_for_werc': auto_start},
                                           daemon=True, name="bridge")
    state.bridge_thread.start()
    log.info("[Web] 已启动")


def _stop_bridge():
    with state.run_lock:
        state.running = False
        state.stop_event.set()

    # 切断 SSE 长连接，让 _bridge_loop 的 listen_sse() 从阻塞中退出
    with state.bridge_lock:
        if state.bridge_instance:
            state.bridge_instance.stop_requested.set()
        if state.bridge_instance and state.bridge_instance._sse_session:
            try:
                state.bridge_instance._sse_session.close()
                log.info("[Web] SSE 连接已断开")
            except Exception as e:
                log.warning(f"[Web] 断开 SSE 异常: {e}")

    # 关闭 WebSocket 连接，让 _ob_client_main 从 async for 中退出
    _ws = state._ob_ws
    _loop = state._ob_ws_loop
    if _ws:
        try:
            if _loop and _loop.is_running():
                import asyncio
                asyncio.run_coroutine_threadsafe(
                    _ws.close(), _loop
                )
                log.info("[Web] WebSocket 连接已关闭")
        except Exception as e:
            log.warning(f"[Web] 关闭 WebSocket 异常: {e}")

    state._ob_ws_ready.clear()

    # 等旧的客户端线程真正退出再允许重启 —— 否则 stop→start 会留下两个客户端线程
    _t = getattr(state, "ob_thread", None)
    if _t is not None and _t.is_alive():
        _t.join(timeout=5)
        if _t.is_alive():
            log.warning("[Web] OB 客户端线程未能及时退出，将在后台自行结束")
    state.ob_thread = None

    # 重置启动标记，让下次 start 能重新拉起 WebSocket 客户端线程
    state.ob_client_started = False
    state._ob_ws_loop = None

    log.info("[Web] 已停止")


def _bridge_loop(*, wait_for_werc=False):
    import ctypes
    ctypes.windll.ole32.CoInitialize(None)

    if config.MESSAGE_SOURCE == "weflow" and not config.ACCESS_TOKEN:
        log.error("❌ 未配置 access_token")
        state.running = False
        return

    log.info(f"Bridge | 消息源: {config.MESSAGE_SOURCE.upper()} | "
             f"OB11: {config.ASTRBOT_OB_URL} | 发送: {config.SEND_METHOD}")
    # Alpha 专属前置检查（地址/令牌/账号），错误信息里不含 token。
    if config.MESSAGE_SOURCE == "alpha":
        if not config.ALPHA_BASE_URL or not config.ALPHA_ACCESS_TOKEN:
            log.error("❌ 未配置 alpha_base_url / alpha_access_token")
            state.running = False
            return

    bridge = WeFlowBridge(state.sender_instance)
    with state.bridge_lock:
        state.bridge_instance = bridge

    # WeFlow/Alpha 的自检差异（WeFlow 旧接口不带 talker 也能探活；
    # Alpha /api/v1/messages 必须带 talker，所以这里探 accounts 而不是 messages）
    # 统一封在 message_source.check() 里。
    source = create_message_source()
    while state.running and not bridge.stop_requested.is_set():
        ok, status, msg = source.check()
        if ok:
            log.info(f"✅ {msg}")
            break
        if not (wait_for_werc and source.name == 'werc' and (status in (0, 429) or 500 <= status < 600)):
            log.error(f"❌ {msg}")
            state.running = False
            break
        log.warning('自动启动：等待 WeRC 就绪（%s）', msg)
        if state.stop_event.wait(5):
            break

    while state.running and not bridge.stop_requested.is_set():
        try:
            bridge.listen_sse()
        except Exception as e:
            log.error(f"SSE: {e}")
        if not state.running:
            break
        log.warning("⚠️ SSE 断开，10s 后重连")
        for _ in range(10):
            if not state.running:
                break
            time.sleep(1)

    with state.bridge_lock:
        if state.bridge_instance is bridge:
            state.bridge_instance = None


