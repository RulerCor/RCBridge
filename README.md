# RCBridge

[中文](#中文) · [English](#english) · [Releases](../../releases)

## 中文

RCBridge 是一个 Windows 桌面桥接工具：通过 WeRC 接收微信消息，将其转发给 OneBot v11 应用，并把机器人的回复发回微信。它不自带机器人、模型或微信客户端。

### 功能与兼容性

| 项目 | 支持范围 |
| --- | --- |
| 桌面端 | Windows x64，需 Microsoft Edge WebView2 Runtime。便携包自带 Python 和桥接依赖，不包含微信、WeRC 或 AstrBot。 |
| 微信接入 | 推荐用 WeRC：接收原生入站消息，支持发送文本、图片、文件、视频和语音（取决于 WeRC 接受的格式和授权范围）。也可配置 Alpha 或 WeFlow 为接收源，或选择 Windows UIA 发送；这些是独立的接入路径，能力不完全相同。 |
| 机器人接入 | OneBot v11 **反向 WebSocket**：RCBridge 主动连接下游应用提供的地址。通用模式不依赖 AstrBot；配置 AstrBot 后可使用其成员权限同步和重启功能。 |

新版 WeRC 的「Bot 收发」令牌默认包含群名同步、好友列表和分类通讯录，无需分别勾选。「成员与权限」可查看名称和 OneBot ID，并按类别浏览通讯录。数据来自 WeRC 本地缓存，不代表微信服务器的实时全量名单。

WeRC 发送模式下，OneBot `image` 段中的 GIF 会按内容识别并作为原生表情发送，需 WeRC 支持原生表情发送。JPG/PNG 仍作为普通图片发送。

OneBot `reply` 支持微信原生文字引用，需要 WeRC 的引用接口支持按接收位置（`position`）定位原消息。合并事件引用最后一条可引用的原始文字。

主动发送按当前账号的 WeRC 原生会话记录恢复目标，不按昵称匹配，也不重放旧消息。没有原生记录的会话无法确认；目前 WeRC 群事件不提供成员 ID，OneBot 以 `user_id: 0` 表示未知发送者。发送结果未知时不会自动重发。

### 快速开始

1. 从 [Releases](../../releases) 下载 Windows x64 便携包。完整解压，运行顶层的 `RCBridge.exe`。
2. 在已连接微信的 WeRC 中复制「Bot 接入」配置，在 RCBridge 的「设置」中导入，然后填写 OneBot v11 反向 WebSocket 地址及所需令牌。
3. 保存后关闭并重新打开 RCBridge，点击「启动桥接」。在总览确认两端已连接，再用测试联系人验证实际收发。

「设置 → 启动」可分别开启 **Windows 登录后启动 RCBridge** 和 **启动 RCBridge 后自动开启桥接**。两项默认关闭；第一项仅适用于当前 Windows 用户。

点击窗口右上角的 × 可选择退出或最小化到系统托盘。最小化到托盘不会停止桥接；双击托盘图标可恢复窗口。

[详细使用与排错](docs/使用指南.md) · [变更记录](CHANGELOG.md) · [许可证](LICENSE)

## English

RCBridge is a Windows desktop bridge. It receives WeChat messages through WeRC, forwards them to a OneBot v11 app, and sends the bot's replies back to WeChat. It does not provide a bot, model, or WeChat client.

### Features and compatibility

| Area | Support |
| --- | --- |
| Desktop | Windows x64 with Microsoft Edge WebView2 Runtime. The portable package includes Python and bridge dependencies, but not WeChat, WeRC, or AstrBot. |
| WeChat | WeRC is recommended for native inbound messages and sending text, images, files, video, and audio, subject to WeRC permissions and accepted formats. Alpha and WeFlow are alternative receive sources, and Windows UI Automation is an alternative send method. These paths have different capabilities. |
| Bots | OneBot v11 over **reverse WebSocket**: RCBridge connects to the endpoint exposed by the downstream app. AstrBot is optional and enables additional member-permission sync and restart controls when configured. |

The newer WeRC Bot preset includes group-name sync, the friend list, and the categorized directory in one token. People shows names alongside OneBot IDs and lets you browse the directory by category. The directory reflects WeRC’s local cache, not live server relationships.

When sending via WeRC, RCBridge detects GIF bytes in OneBot `image` segments and sends them as native emoticons on supported WeRC builds. JPG/PNG still go through the regular image route.

OneBot `reply` supports native WeChat text quotes with a WeRC build that can resolve the original message by receive `position`. A merged event quotes its last eligible original text message.

Proactive sends resolve targets from the current account’s WeRC native observations, without matching display names or replaying old messages. Conversations without a matching native record cannot be resolved. WeRC group events currently lack member IDs; OneBot reports an unknown sender as `user_id: 0`. Unconfirmed sends are not retried automatically.

### Quick start

1. Download the Windows x64 portable ZIP from [Releases](../../releases). Extract the entire ZIP and run `RCBridge.exe` at the top level.
2. In WeRC, connect WeChat and copy the bot connection settings. Import them in RCBridge's Settings, then enter the OneBot v11 reverse WebSocket URL and any required token.
3. Save, close and reopen RCBridge, then start the bridge. Check that both connections are up and verify message delivery with a test contact.

**Settings → Startup** has separate options for opening RCBridge at Windows sign-in and starting the bridge when RCBridge opens. Both are off by default; sign-in startup applies to the current Windows user only.

The window’s × button offers a choice between exiting and minimizing to the system tray. The bridge keeps running in the tray; double-click its icon to restore the window.

[Usage and troubleshooting (Chinese)](docs/使用指南.md) · [Changelog (Chinese)](CHANGELOG.md) · [License](LICENSE)

## 从源码构建 / Build from source

在 Windows x64 上使用 64 位 CPython 3.13 和 .NET Framework 4.x 的 x64 C# 编译器。在项目根目录用 PowerShell 执行；输出目录须不存在。

On Windows x64, use 64-bit CPython 3.13 and the x64 .NET Framework 4.x C# compiler. Run in PowerShell from the repository root; the output directory must not already exist.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-lock.txt
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
.\.venv\Scripts\python.exe -X utf8 build_desktop.py build/RCBridge-win-x64
.\.venv\Scripts\python.exe -X utf8 tests/offline_roundtrip.py build/RCBridge-win-x64
```

[版号与存档 / Versioning and archives (Chinese)](docs/版号与存档.md)
