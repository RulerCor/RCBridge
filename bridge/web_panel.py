"""
Web 控制面板模块。

提供可视化控制页面（http://127.0.0.1:WEB_PORT），
支持启停/暂停/恢复桥接，显示运行状态和日志，
以及在线编辑 config.json 配置。
"""

import json
import logging
import os
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler

import state
import config

log = logging.getLogger("ob11-bridge")


def _read_config() -> dict:
    """读 config.json；万一文件已损坏，自动回退到最近的可用备份。

    为什么要有回退：这个文件被面板与启动流程两边读写，历史上损坏过
    （现场留下 config.json.bak_broken_201419）。损坏后若直接抛异常，
    面板所有"保存"都会失败，用户只能手动修 JSON —— 所以这里尽量自愈。
    """
    try:
        with open(config.CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.error(f"[Web] config.json 读取失败（{e}），尝试从备份恢复")
        d = os.path.dirname(config.CONFIG_FILE) or "."
        base = os.path.basename(config.CONFIG_FILE)
        try:
            cands = sorted(
                (os.path.join(d, n) for n in os.listdir(d)
                 if n.startswith(base + ".") and "broken" not in n
                 and not n.endswith(".tmp")),
                key=lambda p: os.path.getmtime(p), reverse=True)
        except OSError:
            raise
        for p in cands:
            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                log.warning(f"[Web] 已从备份恢复配置: {os.path.basename(p)}")
                return data
            except Exception:
                continue
        raise


def _atomic_write_json(path: str, data: dict) -> None:
    """原子写 JSON：先写临时文件、再 os.replace 顶替。

    为什么必须原子：以前是 `open(path,'w')` 就地改写。面板被连点两下
    （或开了两个标签页）时两次保存会并发，后一次的写入落在已写一半的文件上，
    产生 `Extra data: line 35 column 2` 这种"拼接了两份 JSON"的损坏文件。
    os.replace 在同一分区上是原子的 —— 读到的永远是完整的旧版或完整的新版。
    """
    tmp = f"{path}.tmp{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        f.write("\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, path)


class WebHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/status":
            ob_connected = state._ob_ws is not None and state._ob_ws_ready.is_set()
            weflow_connected = state.bridge_instance is not None and (state.bridge_instance._sse_session is not None or getattr(state.bridge_instance, "werc_connected", False))
            log_lines = []
            try:
                with open("bridge.log", encoding="utf-8", errors="replace") as f:
                    log_lines = f.read().splitlines()[-200:]
            except Exception:
                pass
            self.send_json({
                "running": state.running,
                "paused": state.paused.is_set(),
                "send_method": config.SEND_METHOD,
                "message_source": config.MESSAGE_SOURCE,
                "ob_url": config.ASTRBOT_OB_URL,
                "ob_connected": ob_connected,
                "weflow_connected": weflow_connected,
                "group_reply_mode": state.group_reply_mode,
                # 项目标识：面板标题上的 _RC 标记与版本号从后端下发，
                # 这样以后改 VERSION 文件就够了，不用再回来改 HTML。
                "project_name": getattr(config, "PROJECT_NAME", "Mon3trBot_Remake"),
                "project_version": getattr(config, "PROJECT_VERSION", ""),
                "log": "\n".join(log_lines),
            })
        elif self.path == "/api/config":
            try:
                with open(config.CONFIG_FILE, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                self.send_json(cfg)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)
        elif self.path == "/api/detect-bot":
            self.send_json(self._detect_bot())
        elif self.path == "/api/people":
            import people
            try:
                self.send_json(people.read_overview())
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/exit-reason":
            # 退出归因：面板上直接看「上次是怎么退的、这次是否正常」
            import exit_reason as _er
            try:
                self.send_json(_er.summary())
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/sync-umo-names":
            # 手动触发：给 AstrBot 里"没名字/名字是 wxid"的会话补可读名
            # （面板「自定义规则」里那一列显示的就是它）
            import people
            try:
                n, msg = people.sync_umo_aliases()
                self.send_json({"ok": True, "fixed": n, "message": msg})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/astrbot-status":
            # 供前端轮询重启进度（GET）
            import astrbot_ctl
            try:
                self.send_json(astrbot_ctl.status())
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(b"RCBridge desktop service")

    def do_POST(self):
        if self.path == "/start":
            from main import _start_bridge
            _start_bridge()
            self.send_json({"ok": True})
        elif self.path == "/stop":
            from main import _stop_bridge
            _stop_bridge()
            self.send_json({"ok": True})
        elif self.path == "/pause":
            state.paused.set()
            log.info("[Web] 已暂停")
            self.send_json({"ok": True})
        elif self.path == "/resume":
            state.paused.clear()
            log.info("[Web] 已恢复")
            self.send_json({"ok": True})
        elif self.path == "/mode":
            mode_order = ["all", "batch"]
            idx = mode_order.index(state.group_reply_mode) if state.group_reply_mode in mode_order else -1
            new_mode = mode_order[(idx + 1) % len(mode_order)]
            state.group_reply_mode = new_mode
            try:
                # ⚠️ 以前是「读 → 就地改写 → 直接 dump 到原文件」。面板被连点
                # （或两个标签页同时切）时两次保存并发，后一次写入落在已写一半的
                # 文件上，就产生 `Extra data: line 35 column 2`。
                # 实测发生过，现场留下 config.json.bak_broken_201419。
                # 现在统一走原子写。
                cfg = _read_config()
                cfg["group_reply_mode"] = new_mode
                _atomic_write_json(config.CONFIG_FILE, cfg)
                log.info(f"[Web] 群聊模式已切换为: {new_mode}")
            except Exception as e:
                log.error(f"[Web] 保存配置失败: {e}")
            self.send_json({"ok": True, "group_reply_mode": new_mode})
        elif self.path == "/api/config":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                new_cfg = json.loads(body)

                # 读取当前配置，仅覆盖前端传来的字段
                current = _read_config()
                current.update(new_cfg)
                # 保留 _comment 字段
                if "_comment" not in current:
                    current["_comment"] = "微信 ↔ AstrBot 桥接 - OneBot v11 版配置"

                _atomic_write_json(config.CONFIG_FILE, current)

                log.info(f"[Web] 配置已保存")
                # 运行时同步 group_reply_mode（旧值 mention 归一化为 all）
                if "group_reply_mode" in new_cfg:
                    state.group_reply_mode = ("all" if new_cfg["group_reply_mode"] == "mention"
                                              else new_cfg["group_reply_mode"])

                self.send_json({"ok": True})
            except Exception as e:
                log.error(f"[Web] 保存配置异常: {e}")
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/admins":
            import people
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                wxids = [str(w).strip() for w in (body.get("wxids") or []) if str(w).strip()]
                synced, msg = people.sync_admins_to_astrbot(wxids)
                self.send_json({"ok": True, "synced": synced, "message": msg,
                                "admins": people.load_admins()})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/astrbot":
            import people
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                ok, msg = people.update_astrbot_settings(body)
                self.send_json({"ok": ok, "error": "" if ok else msg})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/session-toggle":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                session = str(body.get("session", "")).strip()
                muted = bool(body.get("muted"))
                if not session:
                    self.send_json({"ok": False, "error": "缺少 session"}, 400)
                    return
                state.set_session_muted(session, muted)
                log.info(f"[Web] 会话 {session} 回复已{'关闭' if muted else '开启'}")
                self.send_json({"ok": True, "session": session, "muted": muted})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/refresh-people":
            # 立即从 WeFlow 补拉联系人/群缓存。
            # 场景：把 bot 拉进新群后，面板「群里管什么」表要马上能看到它，
            # 而不是等桥接重启或 10 分钟定时刷新（2026-10-07 用户报障）。
            try:
                import bridge_core
                n, total, err = bridge_core.refresh_contact_names()
                # 群成员名册慢（每群一个请求），放后台线程补，不阻塞面板响应
                inst = getattr(state, "bridge_instance", None)
                if inst is not None:
                    threading.Thread(target=inst._prefetch_group_rosters,
                                     daemon=True).start()
                self.send_json({
                    "ok": not err,
                    "new": n,
                    "total_chats": total,
                    "groups": len(state.known_groups()),
                    "persons": len(state.all_persons()),
                    "error": err,
                })
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        elif self.path == "/api/astrbot-restart":
            # 重启 AstrBot（白名单/人设等只在启动时读一次，改完必须重启）。
            # 耗时约 10-25 秒 → 放后台线程跑，立刻返回，前端轮询 /api/astrbot-status。
            import astrbot_ctl
            try:
                length = int(self.headers.get("Content-Length", 0) or 0)
                body = {}
                if length:
                    try:
                        body = json.loads(self.rfile.read(length).decode("utf-8"))
                    except Exception:
                        body = {}
                if body.get("action") == "stop":
                    ok, msg = astrbot_ctl.stop()
                    self.send_json({"ok": ok, "message": msg})
                    return
                if astrbot_ctl.is_restarting():
                    self.send_json({"ok": False, "error": "已有一个重启在进行中"})
                    return
                astrbot_ctl.restart_async()
                log.info("[Web] 面板触发 AstrBot 重启")
                self.send_json({"ok": True, "message": "已开始重启，约 10-25 秒"})
            except Exception as e:
                self.send_json({"ok": False, "error": str(e)}, 500)
        else:
            self.send_json({"ok": False}, 404)

    # ===== 自动探测机器人自己的 wxid / 昵称 =====
    def _detect_bot(self):
        """从 WeFlow 反查「我自己」是谁。

        两条路：
        ① 已在 /api/v1/messages 里出现 isSend=1 的消息 → senderUsername 就是本机微信的 wxid
           （这是最权威的来源，因为那条消息就是这台机器发出去的）
        ② 拿到 wxid 后去各群的 /api/v1/group-members 里找同名条目 → 拿到昵称
        """
        out = {"ok": False, "wxid": "", "nicknames": [], "source": "", "error": ""}
        try:
            import requests
        except Exception as e:
            out["error"] = f"缺少 requests: {e}"
            return out

        # WeFlow/Alpha 的鉴权、分页、参数名差异统一走 message_source。
        # 这里不直接用 fetch_contacts()：面板只需要群列表，逐页拉全量太重。
        from message_source import create_message_source
        source = create_message_source()
        if source.name == "werc":
            return source.detect_identity()
        if not source.base_url:
            out["error"] = "未配置消息源地址"
            return out

        def _get(path, **params):
            try:
                if source.name == "alpha":
                    # Alpha 需要 account_id + chatroomId（不是 WeFlow 的 talker）
                    params.setdefault("account_id", source.ensure_account())
                    if path == "/api/v1/group-members" and "talker" in params:
                        params["chatroomId"] = params.pop("talker")
                    r = requests.get(
                        f"{source.base_url}{path}", params=params,
                        headers={"Authorization": f"Bearer {config.ALPHA_ACCESS_TOKEN}"},
                        timeout=15)
                else:
                    params.setdefault("access_token", config.ACCESS_TOKEN)
                    r = requests.get(f"{source.base_url}{path}", params=params, timeout=15)
                if r.status_code != 200:
                    return None
                return r.json()
            except Exception:
                return None

        # 1) 群（会话）列表
        rooms = []
        try:
            d = _get("/api/v1/contacts") or {}
            rooms = [c.get("username", "") for c in (d.get("contacts") or d.get("items") or [])
                     if "@chatroom" in (c.get("username") or "")]
        except Exception:
            rooms = []
        if not rooms:
            # 退而求其次：用桥接自己已知的名册
            try:
                import state
                rooms = [v for v in getattr(state, "_ob_id_to_session", {}).values()
                         if "@chatroom" in str(v)]
            except Exception:
                rooms = []

        # 2) 先拿现有配置当种子去群成员里对（快：通常 1~2 次请求）
        cur = (config.BOT_WXID or "").strip()
        seeds = []
        if cur:
            seeds.append(cur)
            if "_" in cur:
                seeds.append(cur.rsplit("_", 1)[0])  # 去掉微信 4.x 可能带的 _xxxx 后缀

        wxid = ""
        names = []
        for room in rooms[:6]:
            try:
                d = _get("/api/v1/group-members", talker=room) or {}
            except Exception:
                continue
            members = d.get("members") or d.get("data") or []
            if not isinstance(members, list):
                members = []
            for m in members:
                mw = str(m.get("wxid") or m.get("username") or "")
                if not mw:
                    continue
                if not seeds:
                    continue
                hit = any(mw == s for s in seeds) or any(mw.startswith(s) for s in seeds)
                if hit:
                    wxid = mw
                    for k in ("displayName", "nickname", "groupNickname", "remark"):
                        v = str(m.get(k) or "").strip()
                        if v and v not in names:
                            names.append(v)
                    out["source"] = "group-members"
                    break
            if wxid:
                break

        # 3) 没找到（通常是因为还没填 wxid）→ 从「我发出的消息」里认领
        if not wxid:
            for room in rooms[:4]:
                try:
                    d = _get("/api/v1/messages", talker=room, limit=100)
                except Exception:
                    continue
                msgs = d if isinstance(d, list) else (
                    (d or {}).get("messages") or (d or {}).get("data") or [])
                for m in msgs:
                    if not isinstance(m, dict):
                        continue
                    # WeFlow: isSend/senderUsername；Alpha: direction/sender_id
                    is_own = (str(m.get("isSend")) in ("1", "true", "True")
                              or m.get("direction") in (2, "2"))
                    if is_own:
                        su = str(m.get("senderUsername")
                                 or m.get("sender_id") or "").strip()
                        if su.startswith("wxid_"):
                            wxid = su
                            out["source"] = "own-message"
                            break
                if wxid:
                    break

        if not wxid:
            out["error"] = "没识别到机器人自己（需要它在至少一个群里发过消息，或先手填 wxid）"
            return out

        # 4) 用确认过的 wxid 再扫一遍群成员，把各群昵称收集全
        if out["source"] != "group-members":
            for room in rooms[:6]:
                try:
                    d = _get("/api/v1/group-members", talker=room) or {}
                except Exception:
                    continue
                members = d.get("members") or d.get("data") or []
                for m in members or []:
                    if str(m.get("wxid") or "") == wxid:
                        for k in ("displayName", "nickname", "groupNickname", "remark"):
                            v = str(m.get(k) or "").strip()
                            if v and v not in names:
                                names.append(v)
                        break

        out.update(ok=True, wxid=wxid, nicknames=names)
        return out

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def log_message(self, fmt, *args):
        pass
