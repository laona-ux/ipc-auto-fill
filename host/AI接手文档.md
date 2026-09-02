# IPC 自动填数 — AI 接手文档（含「无线控制」更新）

> 适用对象：接手本项目的另一位 AI / 维护者。
> 目标：读完这一份，就能理解现状、知道代码在哪儿、改哪里、怎么编译/运行/验证，不必再翻历史对话。
> 最近一次重大更新：**无线控制（WiFi TCP 控制通道）已上线并实测通过**（2026-09-01）。
> 配套文档：`README.md`（原 Pico 方案总览）、`工控机部署与测试说明.md`（操作员部署 + 无线配网流程，面向人）。本文件面向 AI，侧重"代码地图 + 改动细节 + 踩坑"。

---

## 0. 当前状态速览（TL;DR）

| 项 | 状态 |
|---|---|
| 固件（ESP32-S3）USB-HID 键鼠注入 | ✅ 完成并验证 |
| 串口控制通道（COM12 / UART@115200） | ✅ 完成，作为兜底通道长期保留 |
| **无线控制通道（WiFi TCP :8080）** | ✅ **本次新增，已端到端实测通过** |
| WiFi 凭据持久化（NVS，断电不丢） | ✅ 完成（由 GUI「保存并连接」写入） |
| host 控制台（gui.py）无线控件 | ✅ 完成 |
| 工控机实物"撞墙归零"表现核验 | ⚠️ **待用户在真机上肉眼确认**（本机已代验注入生效） |

设备当前 Wireless 参数（已烧进 ESP32 NVS，不在 config.json 里）：SSID `Kwrt_2.4G`、密码 `12345678`、分得 IP `192.168.11.10`、监听 `:8080`。

---

## 1. 项目是什么

把 `ipc-auto-fill` 项目里"树莓派 Pico 做 USB 键鼠注入"的角色，移植到 **YD-ESP32-S3 开发板**。最终用途：按一张 Excel 表格（如注浆记录），让 ESP32 以"USB 键盘+鼠标"身份自动操作工控机上的目标软件，逐行填入数据。

**两条物理链路（关键，务必理解）：**
- **注入链路（有线，保留）**：ESP32 原生 USB-C（右口 / OTG）→ 插**工控机**，被识别为 USB 输入设备，键鼠落到工控机软件。这条线**始终是 USB 有线**，最稳，本次未动。
- **控制链路（本次改造点）**：笔记本上 `gui.py` 下发 JSON 指令给 ESP32。原来只能走 **FTDI 串口（左口 / COM12）**；本次新增 **WiFi TCP** 通道，操作员可拔掉串口线、在同一 WiFi 下远程控制。串口通道**保留作兜底**，两条并行不冲突。

---

## 2. 文件地图（⚠️ 原项目分散两目录；2026-09-01 已复制合并为「手机自动化填写数值软件」）

> 整合副本位置：`C:\Users\20527\AppData\Roaming\reasonix\global-workspace\手机自动化填写数值软件\`
> 结构：`firmware/ipc_auto_fill_esp32s3.ino` + `host/`（gui.py/run.py/config…）+ README。原 `ipc-auto-fill/` 与 WorkBuddy 工作区源码**保留不动**，故下方旧绝对路径仍有效。改代码优先用整合副本。

```
C:\Users\20527\AppData\Roaming\reasonix\global-workspace\ipc-auto-fill\
├── README.md                      原 Pico 方案总览（背景，非必读）
├── host\                          ← host 端 Python 源码真身（改这里）
│   ├── gui.py                     tkinter 操作台（111KB，本次加无线控件）
│   ├── run.py                     指令/步骤引擎 + Link(串口)/TcpLink(WiFi) + open_link 工厂
│   ├── config.json                ⭐ 运行配置（transport=wifi, wifi_ip, wifi_port, com_port…）
│   ├── config.example.json        配置模板
│   ├── config.json.bak            改动前的备份
│   ├── 启动工控机填数助手.bat     一键建 venv + 装依赖 + 启动 gui.py
│   ├── requirements.txt           pyserial openpyxl xlrd
│   ├── 工控机部署与测试说明.md     面向人的部署+无线配网文档
│   ├── 测试报告-完善后.md / 测试数据.xlsx / values.xlsx
│   └── audit\ tests\              单元/审计用例
├── _backup_20260901_xxxx\         ⭐ 多个时间戳快照（改前备份，回滚用）
├── pico\ zero\                    原 Pico / Zero 方案（历史，本次未涉及）
└── backup_v1_20260824_155913.zip  更早的整体备份

C:\Users\20527\WorkBuddy\2026-08-31-21-55-57\
└── ipc_auto_fill_esp32s3\
    └── ipc_auto_fill_esp32s3.ino  ← ESP32 固件源码真身（改这里烧录）
    （该 WorkBuddy 目录还散落大量 gui_run*.log / compile*.log / probe_*.py 临时文件，可清理，非源码）
```

**铁律**：固件只改 `firmware/ipc_auto_fill_esp32s3.ino`；host 只改 `host/` 下文件。整合副本即可独立编译/运行/交付；原 `ipc-auto-fill/`（`_backup_20260901_*` 与 `config.json.bak`）作为回滚保留。

---

## 3. 本次更新内容（无线控制）—— 重点

**决策**：只把"笔记本→ESP32 的控制通道"从串口换 WiFi（ESP32 接入现场 WiFi）；ESP32→工控机的 USB-HID 注入线**保留有线**。协议不变，风险最低。用户明确不想改代码重烧来换网络，所以凭据走 **NVS + GUI 配置**。

### 3.1 固件改动（`ipc_auto_fill_esp32s3.ino`）
- 新增 `#include <WiFi.h>`、`<Preferences.h>`；`#define TCP_PORT 8080`。
- **关键坑修复**：`WiFiServer`/`WiFiClient` 由全局对象改为**指针**（`WiFiServer *server = nullptr; WiFiClient *tcpClient = nullptr;`），`server->begin()` **延迟到 WiFi 真正连上后**才在 `loop()` 里调用。原因见 §9.2。
- NVS 持久化：`Preferences prefs`；`loadWiFiCreds()` 从 NVS 读 `ssid/pass`，空则回退到代码 `#define WIFI_SSID/WIFI_PASSWORD`（当前留空）。
- 双通道抽象：所有应答走 `void sendRaw(Print& out, ...)` 与 `void handle(const String& line, Print& out)`，`out` 既可是 `Host`(UART) 也可是 `*tcpClient`(WiFi)，**协议完全一致**。
- 新增两个 op：`net_info`（回报 wifi/ip/rssi/port）、`set_wifi`（把 ssid/pass 写 NVS 并立即 `WiFi.begin()` 重连）。
- `setup()`：仅 `loadWiFiCreds()` + `connectWiFi()`（有凭据才连），`server = new WiFiServer(TCP_PORT)` 只建对象不 begin。
- `loop()`：WiFi 断线每 5s `reconnect()`；连上且 `!serverStarted` 时 `server->begin()`；`hasClient()` 时接受新连接（**单客户端，新连接顶掉旧**）；UART 与 WiFi 两路各自按行解析 `handle()`。
- `connectWiFi()` 内：`if(!g_wifiStarted){ server=new WiFiServer(...); server->begin(); g_wifiStarted=true; }` 保证 begin 只在就绪后一次。

### 3.2 host 改动（`run.py`）
- `import socket`（顶部）。
- 新增 `class TcpLink`（约 run.py:242）：与 `Link`（串口）**接口对齐**——`send/ping/get_pos/close`；`__init__(host, port, connect_timeout=5.0, timeout=0.05)`；`send()` 先 `_drain()` 丢弃残留再发 JSON 行等应答；`ping()` 发 `{"op":"ping"}` 期待 `{"pong":true}`；`get_pos()` 解析 `get_pos` 返回 `(x,y)` 或 `None`。
- 新增 `def open_link(cfg)`（run.py:318）：`transport=="wifi"` → `TcpLink(wifi_ip, wifi_port)`；否则 `Link(com_port, baudrate)`。这是**统一的链路工厂**，全项目所有 `_open_link_bounded(cfg)` 都经它。

### 3.3 host 改动（`gui.py`）
- `_open_link_bounded(cfg)`（gui.py:207）内部改用 `run.open_link(cfg)`，按 `transport` 选串口或 WiFi。
- 无线控件放进独立 `ttk.Frame wf`（原 row0 挤 16 列超窗口、row2 同格重叠导致"WiFi 框不显示"，已修）：
  - `transport` Combobox，values=`["串口","无线(WiFi)"]`（gui.py:487）。
  - `wifi_ip` / `wifi_port` / `wifi_ssid` / `wifi_pass`(show=*) 输入框。
  - `btn_wifi`「保存并连接」→ `self._save_wifi`（gui.py:505）。
- `_save_wifi` / `_save_wifi_worker`（gui.py:1467 / 1487）：
  - 必须先经**串口**连上板子（`com_port` 必填）才能下发 WiFi 凭据（板子没联网时只能走 UART/COM）。
  - 子线程里：`open_link(serial_cfg)` → `ping()` → `send({"op":"set_wifi","ssid","pass"})` 写 NVS → 轮询 `net_info` 最多 ~20s 拿 IP → 拿到后回填 `wifi_ip`、把 `transport` 切到 `无线(WiFi)`、弹 `messagebox.showinfo` 成功提示。
- `collect_config`（约 gui.py:1085-1152）：`transport` = `"wifi" if combobox.get().startswith("无线") else "serial"`；并写入 `wifi_ip/wifi_port/wifi_ssid/wifi_pass`；界面初始化时按 `cfg.transport` 回填 combobox（gui.py:1152）。
- **放宽三处 `com_port` 必填校验**（`_locate_get_cfg`/`_validate_start`/`_test_step`）：无线模式下串口可空。
- 窗口 `geometry("1400x1000")` 两处（gui.py:262 App.__init__、gui.py:2259 main）—— 因为无线控件多，旧窗口太窄会挤掉。
- **反馈改弹窗**：因"步骤流程"区恒定高度会裁切底部日志，测试连接/HID检测/配网结果统一用 `messagebox` 弹窗（而非仅靠日志）。

### 3.4 配置与文档
- `config.json` 新增字段：`transport` / `wifi_ip` / `wifi_port`（**不含 ssid/pass**——凭据在 NVS，这是正确的，别往 config 里找）。当前值见 §0。
- `工控机部署与测试说明.md` §6 改写为"NVS + GUI 保存并连接"流程（含首次配网 + 日常使用 + 协议可靠性说明）。

---

## 4. 通信协议（JSON 行协议，串口与 WiFi **通用**）

每行一条 JSON（UTF-8，`\n` 结尾），板子回一行 `{"ack":...}` 或 `{"pong":true}`。

| host→ESP32 | 说明 |
|---|---|
| `{"op":"ping"}` | 心跳，回 `{"pong":true}` |
| `{"op":"home"}` | 把光标甩到左上角并设原点 (0,0)（撞墙式归零） |
| `{"op":"move_to","x":120,"y":96}` | 移到绝对坐标（内部记录上次位置，连续移动不重归零） |
| `{"op":"click_at","x":120,"y":96}` | 移到该坐标并左键单击 |
| `{"op":"dblclick_at",...}` / `{"op":"press_at","x":,"y":,"ms":800}` | 双击 / 按住 ms 毫秒 |
| `{"op":"wheel","delta":-120}` | 滚轮，>0 上滚 <0 下滚 |
| `{"op":"type","text":"25.5"}` | 键盘输文本（ASCII；`\t`=Tab `\n`=Enter） |
| `{"op":"key","key":"enter"}` | 按键，支持 `ctrl+a` / `shift+tab` |
| `{"op":"sleep","ms":500}` | 等待 |
| `{"op":"get_pos"}` | 回当前内部光标坐标；未归零回 `{"ack":"error","msg":"not_homed"}` |
| `{"op":"net_info"}` | 回 `{"wifi":bool,"ip":str,"rssi":int,"port":int}`（**无线诊断**） |
| `{"op":"set_wifi","ssid":..,"pass":..}` | 写 NVS 并立即重连（**GUI 配网用**） |
| `{"op":"usb_state"}` | 回 `{"mounted":bool}`——原生 USB 是否被工控机枚举为 HID |

> 鼠标相对移动：`moveTo()` 按 ±127 分步（ESP32 `Mouse.move` 上限），用向上取整 + 余数分摊避免累计偏移；`HOME_STEPS=60` 步 × -127 覆盖约 7620px。`MOVE_MAX=120` 防死循环。

---

## 5. 关键代码索引（要改 X，去 Y）

| 想改什么 | 文件:位置 | 备注 |
|---|---|---|
| 换 WiFi 网络/改端口 | 固件 `#define TCP_PORT`；凭据走 GUI 写 NVS | **不要**在代码里硬写 SSID/密码 |
| WiFi 栈崩溃/重启 | 固件 `server`/`tcpClient` 必须是指针 + 延迟 begin | 见 §9.2 |
| 新增 JSON 指令 | 固件 `handle()`（约 ino:285）加分支；host `run.py` 加对应 step 类型 | 两边都要加 |
| 链路层（串口/WiFi） | `run.py` `Link` / `TcpLink` / `open_link` | 新调用一律走 `run.open_link(cfg)` |
| 控制台 UI | `gui.py` 控件在独立 Frame，搜索 `self.ui["..."]` | 加控件记得窗口 1400x1000 够不够 |
| 配网流程 | `gui.py` `_save_wifi` / `_save_wifi_worker`（1467/1487） | 必须串口先连 |
| 启动/停止/填数主流程 | `gui.py` 内 `link = _open_link_bounded(cfg)` 各调用点 | 已全量切换为 open_link |
| 配置字段 | `host/config.json` + `gui.py collect_config` | transport 映射逻辑在 collect_config |

---

## 6. 构建 / 烧录固件

环境：`arduino-cli`（ESP32 core 3.3.11），板型 **ESP32-S3（N16R8，16MB Flash + PSRAM）**。

```bash
# 编译
arduino-cli compile -b esp32:esp32:esp32s3:USBMode=default,FlashSize=16M,PSRAM=opi,UploadSpeed=921600 \
  "C:/Users/20527/AppData/Roaming/reasonix/global-workspace/手机自动化填写数值软件/firmware"

# 上传（FTDI 左口 = COM12）
arduino-cli upload -b esp32:esp32:esp32s3:USBMode=default,FlashSize=16M,PSRAM=opi,UploadSpeed=921600 \
  -p COM12 "C:/Users/20527/AppData/Roaming/reasonix/global-workspace/手机自动化填写数值软件/firmware"
```

⚠️ **冷编译会卡死**（见 §9.1）。若卡住：杀 arduino-cli 进程 → 删 `build/` 缓存 → 再编译（热缓存 1–2 分钟过）。
⚠️ 若手头只有 `.bin`：esptool 直写偏移 `0x0 bootloader / 0x8000 partitions / 0xe000 boot_app0 / 0x10000 app`，构建缓存在 `C:\Users\20527\AppData\Local\arduino\sketches\DAAAB9DEC96345B0E6376B75BAEFDB35\`。

---

## 7. 运行 host（操作台）

```bash
cd "C:/Users/20527/AppData/Roaming/reasonix/global-workspace/手机自动化填写数值软件/host"
# 方式A：一键（建 venv + 装依赖 + 启动）
启动工控机填数助手.bat
# 方式B：手动
python -m pip install pyserial openpyxl xlrd
python gui.py
```

`config.json` 关键字段（当前无线模式）：
```json
{ "com_port":"COM12", "baudrate":115200,
  "transport":"wifi", "wifi_ip":"192.168.11.10", "wifi_port":8080,
  "data_file":"C:/Users/20527/Documents/注浆脚本.xlsx", "sheet":"Sheet1",
  "start_home":true, "step_delay_ms":300,
  "steps":[ ... ] }
```
- `transport`：`"wifi"` 或 `"serial"`（GUI 显示"无线(WiFi)"/"串口"）。
- `wifi_ip/wifi_port`：ESP32 在 WiFi 下的地址（用「保存并连接」自动填，或 `net_info` 查）。
- **`com_port` 在无线模式下可空**（已放宽校验）；串口模式必填。
- `ssid/pass` **不在** config.json（在 NVS）。

---

## 8. 测试 / 验证方法（接手后想确认没坏，照做）

1. **单元逻辑**：`host/tests/` 下 FakeLink 测试（纯逻辑，无需硬件）。
2. **Dry Run**：`python run.py --dry-run`（解析表格 + 展开步骤 + 生成指令序列）。
3. **串口直连实测**：`run.Link` 直连 COM12，跑 `home/move_to/click_at/wheel/type/key/get_pos`。
4. **无线端到端**（已实测 PASS）：ESP32 连 WiFi 得 IP → 本机 `TcpLink(wifi_ip,8080).ping()` → `net_info` 拿到 IP → 走 WiFi 下发 `home`→(0,0)、`move_to(50,50)`→工控机光标真移到 (50,50)。
5. **控制台启动**：`python gui.py` 窗口能起来、端口检测含 COM12、能载入表格列、能连真实 ESP32。
6. **物理 HID 核验**（工控机 PowerShell）：
   ```powershell
   Get-PnpDevice -PresentOnly -Class HIDClass | Where-Object { $_.FriendlyName -match 'USB' }
   ```
   应看到新增的 USB 输入设备（ESP32 复合键鼠）；没有则说明原生 USB-C 没插好/线材仅供电。

---

## 9. 已知坑（都踩过、都修好了，别再栽）

### 9.1 arduino-cli 冷编译卡死
现象：冷启动编译 27 分钟零产出。处理：杀 PID → `rm -rf build` → 热缓存重编（1–2 分钟过）。**首次编译前先确保有热缓存**，否则会以为死机。

### 9.2 固件启动崩溃 `assert failed: xQueueSemaphoreTake`
**根因**：全局 `WiFiServer`/`WiFiClient` 对象在构造/begin 时触碰尚未就绪的 WiFi 栈（FreeRTOS 信号量 NULL）。
**修法**：二者改指针；`server->begin()` 延迟到 `loop()` 里 `WiFi.status()==WL_CONNECTED` 之后。看到这个断言就代表 WiFi 对象初始化时机不对，重新干净编译烧录。

### 9.3 GUI "WiFi名/密码框没显示"
根因：原 row0 挤 16 列超窗口、row2 同格重叠被盖。
**修法**：无线控件挪进独立 `ttk.Frame wf`，窗口加宽到 `1400x1000`。

### 9.4 `not all arguments converted during string formatting`
根因：gui.py:1521 原日志 `"...保留。" % ip` 没有占位符（旧代码）。现 1523 `_toast` 已用 `%s` 正确占位。此错只在"连上 WiFi 的成功分支"触发，能复现即说明凭据已连上。

### 9.5 日志区被布局裁切，看不到结果
根因："步骤流程"区恒定高度把底部日志挤掉。
**修法**：测试连接 / HID 检测 / 配网结果一律改 `messagebox` 弹窗。改 UI 高度前先想清楚会不会再丢日志。

---

## 10. 待办 / 接手后可继续

1. **⚠️ 工控机实物核验"撞墙归零"**：在真机上确认每点一步前光标是否先跳回左上角 (0,0)。本机已代验 WiFi HID 注入生效（光标真的移动），但"归零视觉表现"需人眼在工控机确认。
2. 可选增强：路由器给 ESP32 做 DHCP 保留（避免 IP 变）；多客户端仲裁（当前单客户端，新连顶旧）；GUI 配网失败时直接显示具体错误而不仅是"20s 未连上"。
3. 临时文件清理：WorkBuddy 目录里 `gui_run*.log` / `compile*.log` / `probe_*.py` 是调试遗留，可删（非源码）。

---

## 11. 接手第一件事（Checklist）

- [ ] 读 `host/工控机部署与测试说明.md` §0 拓扑 + §6 无线配网（面向人的版本，配套本文件）。
- [ ] 确认固件 `.ino` 在 `WorkBuddy/.../ipc_auto_fill_esp32s3/`，host 在 `reasonix/.../ipc-auto-fill/host/`（别改错目录）。
- [ ] 要改网络：用 GUI「保存并连接」（写 NVS），**别**在代码硬写 SSID。
- [ ] 要加指令：固件 `handle()` + host `run.py` step 类型两边同步。
- [ ] 要换链路：只动 `run.open_link()` / `TcpLink` / `Link`，调用方全走 `run.open_link(cfg)`。
- [ ] 编译卡死 → 杀进程删 build 热编；板子重启断言 → 查 WiFi 对象是否又变全局了。
- [ ] 验证：先 `--dry-run`，再串口直连，再 WiFi 端到端（§8）。

---
*本文件由 AI 在 2026-09-01 无线控制上线后整理，供后续接手 AI 使用。发现文档与代码不符时，以代码为准并顺手更新本文件。*
