# 工控机自动填入数值工具（ipc-auto-fill）

笔记本读 Excel/CSV 表格，把数值一条条自动「点进」工控机的小屏幕软件里。
每次填完一条，等你人工确认无误后才填下一条（也支持校准模式自动试点）。

> 硬件已从树莓派 **Pico 升级为 ESP32-S3**，并新增 **WiFi 无线控制**通道。详见下方「本次更新说明」。

---

## 0. 本次更新说明（2026-09）

- **整合为单文件夹**：固件与 host 工具合并到统一目录（`firmware/` + `host/`），结构更清晰，便于接手与发布。
- **硬件升级为 ESP32-S3**：固件改为 `firmware/ipc_auto_fill_esp32s3.ino`（Arduino + TinyUSB 复合 HID，相对鼠标定位 + 键鼠注入），取代原 Pico/CircuitPython 方案。
- **新增 WiFi 无线控制通道**：笔记本 ↔ ESP32 的「控制通道」可从串口改为 **WiFi（TCP，默认端口 8080）**。ESP32 接入现有 WiFi 后，笔记本经 WiFi 下发指令；**ESP32 → 工控机的 USB-HID 注入线保持不变**（注入通道仍是物理 USB）。
- **SSID/密码走 NVS + GUI**：在图形界面「保存并连接」里输入 WiFi 名/密码，固件写入 ESP32 的 **NVS**，断电不丢、下次自动联网、自动回填 IP。
- 保留 MIT LICENSE；旧版 `pico/`、`zero/`、`docs/` 方案已移除。
- 发布地址：https://github.com/laona-ux/ipc-auto-fill

> 想完整接手代码（编译/运行/协议/踩坑），先看 `host/AI接手文档.md`。

---

## 1. 方案原理

```
┌─────────────┐   控制通道(串口COM 或 WiFi TCP)   ┌──────────────────┐   USB-HID   ┌──────────────────┐
│ Windows 笔记本 │ ───────────────────────────────▶ │   ESP32-S3 开发板  │ ─────────▶ │ 工控机（USB-A口） │
│  run.py 读表格  │  (UART串口指令 / TCP:8080 WiFi)  │  模拟USB键鼠(HID)  │  (标准HID)  │  小屏幕上的软件     │
└─────────────┘                                    └──────────────────┘            └──────────────────┘
```

- **笔记本**：读表格、算坐标、发指令、等人工确认。
- **ESP32-S3**：插在工控机 USB-A 口，被识别为「USB 键盘 + 鼠标」；用 TinyUSB 复合 HID 做相对移动 / 点击 / 输入。
- **控制通道（笔记本 ↔ ESP32）二选一**：
  - 串口：ESP32 的 UART（GPIO）经 USB-TTL 接笔记本 COM 口（兜底 / 调试用）。
  - WiFi：ESP32 连上现有 WiFi 后，笔记本经 TCP(:8080) 直连，笔记本不再需要插线。
- **注入通道（ESP32 → 工控机）固定为物理 USB**（ESP32 原生 USB 口），无论控制通道用串口还是 WiFi 都不变。

### 「手动定位数值」怎么落地的
工控机屏幕小，软件窗口位置固定，输入框的坐标（x, y 像素）基本固定。
- 你把每个输入框的坐标填进 `host/config.json`（第一次要用校准模式试出来，见第 8 节）。
- 脚本让 ESP32 用**相对移动**把光标精确移动到坐标再点击（ESP32 自己记着光标上一次的位置，从上次位置算差值，所以不需要知道屏幕分辨率）。
- 每次运行前：人工把工控机上的鼠标光标移到**屏幕左上角**按回车，脚本就发 `home` 命令让 ESP32 把坐标原点对准左上角，之后全部自动。**注意：开始后不要再手动动工控机的鼠标/触摸屏**，否则坐标会偏移（撞墙式归零 `slamHome()` 会在每步前把光标甩回原点，降低漂移）。

> 换更省事的思路：如果工控机软件能用 Tab 键在输入框之间跳转，可以把目标模式设成 `keyboard`，脚本只用键盘导航和输入，完全不用鼠标定位。两种模式都支持，见第 6 节。

---

## 2. 需要准备的设备

| 设备 | 作用 | 建议 | 参考价 |
|---|---|---|---|
| ESP32-S3 开发板（如 YD-ESP32-S3-WROOM-1-N16R8） | 模拟 USB 键鼠 + WiFi 控制 | 带**原生 USB**（需支持 TinyUSB）、有 PSRAM 更佳 | ¥30～50 |
| （可选）USB 转 TTL 串口模块（CH340 / CP2102） | 笔记本 ↔ ESP32 的**串口**控制通道（WiFi 模式不需要） | 带 3.3V 电平跳线 | ¥3～8 |
| USB 数据线 1～2 根 | ESP32 原生 USB 连工控机（注入）；烧录 / 串口用 | 要**能传数据**的线 | ¥5～10 |
| 无线路由器 / 现有 WiFi | 无线控制模式需要 ESP32 能连上（2.4G） | 你已有的 | — |

不需要再买别的。笔记本、Excel、WiFi 你都有。

> 无线模式**不需要**串口线和 CH340；只有纯串口模式才需要那根线。

### 早期方案（已弃用，仓库内已移除）
- **树莓派 Pico（RP2040）+ CircuitPython**：最早方案，已被 ESP32-S3 取代。
- **树莓派 Zero 2W（USB OTG 模拟 HID）**：配置复杂、偏贵，已弃用。

---

## 3. 接线

按你选的控制通道二选一：

### A. 无线（WiFi）模式（推荐，免连线）
- ESP32 原生 USB-C → 工控机 USB-A（HID 注入）。
- 笔记本**不接** ESP32；ESP32 连上你的 WiFi 即可（WiFi 名/密码在 GUI「保存并连接」里填，存 NVS）。

### B. 串口模式（兜底 / 调试）
- ESP32 的 UART（GPIO）经 USB-TTL（CH340）接笔记本 COM 口：

  | ESP32 引脚 | CH340 模块 |
  |---|---|
  | `GPIO43`（UART0 TX） | `RXD` |
  | `GPIO44`（UART0 RX） | `TXD` |
  | `GND` | `GND` |

  注意：TX/RX 交叉接；CH340 电平拨到 **3.3V**，别接 5V。
- ESP32 原生 USB-C → 工控机 USB-A（HID 注入）。

---

## 4. 安装步骤

### 4.1 给 ESP32-S3 烧录固件（一次性）
1. 安装 [Arduino CLI](https://arduino.github.io/arduino-cli/)，加入 `esp32` 平台（core 3.3.x）。
2. 选板：`esp32:esp32:esp32s3`（参数 `USBMode=default, FlashSize=16M, PSRAM=opi, UploadSpeed=921600`）。
3. 编译 `firmware/ipc_auto_fill_esp32s3.ino`，用 `esptool` 直写偏移 `0x0 bootloader / 0x8000 partitions / 0xe000 boot_app0 / 0x10000 app`，或用 `arduino-cli upload`。
4. 细节（含编译缓存坑、启动崩溃排查）见 `host/AI接手文档.md` §6 与 `host/工控机部署与测试说明.md`。

### 4.2 笔记本装环境（一次性）
1. 装 Python 3.10+：https://www.python.org/downloads/ （勾选 **Add Python to PATH**）。
2. 打开 PowerShell / CMD，进入项目目录：
   ```powershell
   cd 手机自动化填写数值软件\host
   pip install -r requirements.txt
   ```
   主要依赖：`pyserial`、`openpyxl`、`tk`（GUI 用，Python 自带）。
3. 串口模式：设备管理器确认 CH340 的 COM 口号。

### 4.3 工控机侧
**工控机上不用装任何东西、不用改任何设置。** 把 ESP32 插进它的 USB-A 口，它看到的就是一个「USB 输入设备」（键盘+鼠标）。

---

## 5. 表格格式（Excel 或 CSV）

支持几乎任意结构：`.xlsx / .xlsm / .xls / .csv`，自动按扩展名区分。列名随意，例如：`序号, 温度, 压力, 转速`。

- 默认**第一行是表头**；若表头不在第一行，把 `header_row` 设为表头所在行号（0-based）。
- 若表格**没有表头**，把 `has_header` 设为 `false`，脚本自动按 `col1/col2…` 生成列名，
  此时 `header_row` 表示第一条数据所在行号（可用来跳过前面的标题行），并用 `col` 填列名或 0-based 列序号。
- 每一行是一条记录，脚本把这一行的数值逐项填到工控机上。
- 数值支持数字、小数、正负号（如 `123.45`、`-12.5`、`0.8`）和普通英文/数字/符号。**不支持中文**（USB 键盘协议只能发英文键码）。

示例 `values.xlsx`：

| 序号 | 温度 | 压力 | 转速 |
|---|---|---|---|
| 1 | 25.5 | 101.3 | 1500 |
| 2 | 26.0 | 102.1 | 1600 |

> 读取 `.xls` 需要 `pip install xlrd`；`.xlsx/.xlsm` 需要 `openpyxl`；`.csv` 无需额外库。

---

## 6. 配置文件 `host/config.json`

> 这是一个「步骤流程」配置。核心是 `steps`：**对表格的每一行数据，按顺序把这些步骤执行一遍**（点击进入界面 → 填入数值 → 返回 → 再进另一界面 → …）。
> 旧版「targets」配置仍完全兼容：没有 `steps` 时会自动按老方式展开。

```jsonc
{
  "device_type": "esp32",        // 固定为 esp32（本固件）
  "transport": "wifi",           // 控制通道： "wifi"(无线) 或 "serial"(串口)
  "com_port": "COM12",           // 串口模式下的串口号（WiFi 模式可留空，作兜底）
  "baudrate": 115200,
  "wifi_ip": "192.168.11.10",    // ESP32 连上 WiFi 后的 IP（GUI 自动回填；SSID/密码在 NVS，不在此文件）
  "wifi_port": 8080,             // ESP32 TCP Server 端口
  "data_file": "values.xlsx",    // Excel/CSV 路径（相对 host/ 或绝对路径）
  "sheet": "Sheet1",             // 工作表名，留空取第一个
  "header_row": 0,               // 表头所在行号（0-based）；缺省 0
  "has_header": true,            // false=没有表头
  "row_start": 1,                // 只填从第几条（数据行，1-based）开始
  "row_end": 0,                  // 填到第几条为止；0=到末尾
  "confirm": "enter",            // "enter"=每行人工确认；"none"=不停
  "start_home": true,            // true=每次运行前要求把工控机鼠标移到屏幕左上角，自动校准原点
  "step_delay_ms": 300,          // 默认动作间停顿（毫秒）
  "steps": [                     // ───────── 步骤流程 ─────────
    { "type": "click", "name": "返回主界面", "x": 210, "y": 120 },
    { "type": "click", "name": "参数", "x": 100, "y": 60 },
    { "type": "input", "name": "填入压力", "col": "稳定压力(MPa)" },
    { "type": "confirm", "name": "人工确认" }
  ],
  "buttons": {}                  // 自定义按钮（可复用/快捷执行）
}
```

### 步骤类型（steps 里的每一项）

| `type` | 作用 | 主要字段 |
|---|---|---|
| `click` | 移动到 (x,y) 并单击 | `x`,`y` |
| `dblclick` | 移动到 (x,y) 并双击 | `x`,`y` |
| `press_at` | 移动到 (x,y) 按住左键 `ms` 毫秒（长按） | `x`,`y`,`ms` |
| `move` | 只移动光标到 (x,y)，不点击 | `x`,`y` |
| `scroll` | 滚动滚轮 | `delta`（>0 上滚，<0 下滚） |
| `key` | 按一个键 | `key`（enter/tab/esc/f5/ctrl+a …） |
| `input` | 填入一个数值 | `col`/`value`、`prefix`/`suffix`、`default`、`pre_keys`、`round`、`enter` |
| `sleep` | 等待 `ms` 毫秒 | `ms` |
| `home` | 让光标回屏幕左上角并重设原点 | — |
| `confirm` | 暂停，等人点『已确认』 | `name` |
| `button` | 引用自定义按钮，执行时展开 | `name` |

- 每个步骤可选 `name` 和 `delay_ms`。
- `input`：填了 `col` 就从表格该列取值；没填 `col` 用 `value` 固定值。
- 新坐标用第 8 节的校准模式试出来。

---

## 7. 使用流程

### 7.1 图形界面操作（推荐）

可视化界面（Tkinter，Python 自带）。日常使用推荐用它：

```powershell
cd 手机自动化填写数值软件\host
python gui.py
```

界面操作概览：

1. **连接 / 传输方式**：顶部「传输」下拉选 **无线(WiFi)** 或 **串口**。
   - **无线(WiFi)**：填 ESP32 的 `IP` 与 `端口(8080)`；首次配网在「WiFi名(SSID) / 密码」里输入，点 **保存并连接**——固件写入 NVS 并立即联网，连上后 IP 自动回填，之后切到无线即可（串口作兜底保留）。
   - **串口**：选 COM 口、波特率，点「测试 Pico」确认在线。
2. **选数据文件**：选 Excel/CSV，自动列出工作表下拉，点「载入表格」校验并把表头填进「表格列」下拉。
3. **行列与步骤（三步走）**：选填范围 → 多选要填的列 → 点「将选中列生成填入步骤」自动生成 `输入数值` 步骤。
4. **步骤流程（核心）**：列表每行一个步骤，对范围内每行数据顺序执行。右侧表单编辑字段；类型含 `单击/双击/长按/移动/滚轮/按键/输入数值/延时/归零/人工确认/自定义按钮`。
5. **坐标定位**：
   - **方式一（推荐，F8 定位）**：先把工控机鼠标移到左上角点 ●归零；用方向键挪到目标；选中鼠标类步骤按 **F8** 记录坐标。
   - **方式二（旧校准）**：点「校准坐标」逐个核对微调。
6. **开始填数**：点「开始填数」，弹窗提示把工控机鼠标移到左上角；之后每步/每行亮起「✔ 已确认」按钮，核对无误再继续。
7. **其他**：底部日志实时显示；「Dry Run 预览」只打印指令不动工控机；「停止」最长 12 秒看门狗强制恢复，不卡死。

> 命令行版 `python run.py` 功能相同，两者共用同一个 config.json，可混用。

### 7.2 命令行使用流程

```powershell
cd 手机自动化填写数值软件\host
copy config.example.json config.json   # 第一次
notepad config.json                    # 按第 6 节改传输方式、IP/COM、表格路径
python run.py
```

脚本启动 → 按 `transport` 连 WiFi 或串口 → 测在线 → 读表格 →（若 `start_home`）提示归零 → 逐条填入 → 每行等你确认 → 写 `host/.progress` 断点。中途中断下次可续传。

#### 命令行选项
```powershell
python run.py --config config.json     # 指定配置（默认 config.json）
python run.py --calibrate              # 校准模式：只移动不输入，人工回报是否对准
python run.py --dry-run                # 只打印指令序列，不连设备
python run.py --resume                 # 直接从断点继续
```

---

## 8. 坐标校准（第一次必做）

1. 工控机软件打开、窗口放固定位置（**以后别动**）。
2. 运行 `python run.py --calibrate`（或 GUI 的校准模式）。
3. 提示把鼠标移到屏幕左上角，回车（原点校准）。
4. 脚本逐个把光标移到每个鼠标类步骤（click/dblclick/move/press_at）的坐标，停在目标位置。
5. 你看工控机屏幕：对准按 `y`；偏了按 `n` 输入微调像素（如 `+20,0`、`0,-10`）。
6. 校准完配置即真实坐标，之后正常跑。

> 一次调 ±20 像素较稳妥。小屏常见 800×600 / 1024×768，1 厘米约 40～60 像素。

---

## 9. 笔记本 ↔ ESP32 协议（简洁版）

每行一条 JSON（UTF-8，以 `\n` 结尾）。ESP32 执行完回 `{"ack":"ok"}`（或对应结果）。串口与 WiFi(TCP) **共用同一套行协议**。

| 笔记本 → ESP32 | 含义 |
|---|---|
| `{"op":"ping"}` | 在线检测，回 `{"pong":true}` |
| `{"op":"home"}` | 光标甩到屏幕左上角并设原点 (0,0)（撞墙式归零） |
| `{"op":"move_to","x":120,"y":96}` | 光标移到绝对坐标（相对上次位置移动） |
| `{"op":"click_at","x":120,"y":96}` | 移动到坐标并左键单击 |
| `{"op":"dblclick_at", ...}` / `{"op":"press_at","ms":800}` | 双击 / 长按 |
| `{"op":"wheel","delta":-120}` | 滚动滚轮 |
| `{"op":"get_pos"}` | 查询当前光标坐标，回 `{"ack":"ok","x":..,"y":..}` |
| `{"op":"type","text":"25.5"}` | 键盘输入文本（ASCII） |
| `{"op":"key","key":"enter"}` | 按一个键 |
| `{"op":"sleep","ms":500}` | 停 500ms |
| `{"op":"net_info"}` | 查 WiFi 状态，回 `{"wifi":..,"ip":..,"rssi":..,"port":..}` |
| `{"op":"set_wifi","ssid":"..","pass":".."}` | 写 NVS 并联网（GUI「保存并连接」用） |

> 完整指令与字段以 `firmware/ipc_auto_fill_esp32s3.ino` 与 `host/AI接手文档.md` §4 为准。

---

## 10. 故障排查

| 现象 | 原因 / 解决 |
|---|---|
| 串口模式「找不到 COM 口」 | 设备管理器确认 CH340 的 COM 号，改 config.json |
| 「ESP32 无响应 (ping 超时)」 | 串口模式下 TX/RX 接反（对调）；波特率不一致；WiFi 模式下 IP/端口填错或未连上 |
| 工控机没有任何反应 | ESP32 的 USB-C 线是**充电线**（不能传数据），换一条；或固件没烧好（重烧） |
| **WiFi 连不上 / `set_wifi` 报错** | SSID/密码错；ESP32 只支持 **2.4G** WiFi（别连 5G）；用「保存并连接」重填；串口作兜底仍可控制 |
| **改了 WiFi 后 IP 没回填** | 联网成功才会回填；先看 GUI 弹窗的 net_info；串口重连查 `net_info` 确认 IP |
| 光标点不到正确位置 | 校准模式重新校准；运行中有人动过工控机鼠标导致偏移（重新归零左上角） |
| 点「停止」卡住不恢复 | 串口被占用/设备拔出卡住。已加保护：打开 3 秒上限、延时可被打断、12 秒看门狗强制恢复；再不行重插/换 COM |
| 输进去的数值不对/多字 | 输入框有旧值 → 输入步骤加 `"pre_keys": ["ctrl+a"]` 先清空 |
| 想输入中文 | 不支持（USB 键盘协议限制） |

---

## 文件说明

```text
手机自动化填写数值软件/
├── README.md                         # 本文件
├── LICENSE                           # MIT（Copyright laona-ux）
├── 启动界面.bat                       # 一键进入 host 目录的快捷脚本
├── firmware/
│   └── ipc_auto_fill_esp32s3.ino     # ESP32-S3 固件：TinyUSB 复合 HID + WiFi TCP 控制通道
└── host/
    ├── gui.py                        # 图形界面（推荐）：步骤流程编辑 + 无线/串口连接 + 校准 + 日志
    ├── run.py                        # 命令行主程序：步骤引擎、读表、发指令、确认、断点
    ├── config.json                   # 你的实际配置（传输方式 + 步骤 + 坐标）
    ├── config.example.json           # 模板
    ├── requirements.txt              # Python 依赖
    ├── 启动工控机填数助手.bat         # Windows 一键启动 GUI
    ├── AI接手文档.md                  # 面向接手 AI：代码地图、协议、编译/运行命令、已知坑
    ├── 工控机部署与测试说明.md         # 部署与端到端测试步骤
    ├── 测试报告-完善后.md             # 测试结论
    ├── values.xlsx / 测试数据.xlsx    # 示例数据
    ├── tests/                        # 单元/接口测试
    └── audit/                        # 填数操作审计日志（.jsonl，本地用，默认不入库）
```

> 仓库地址：https://github.com/laona-ux/ipc-auto-fill ｜ 内部详细协议与踩坑看 `host/AI接手文档.md`。
