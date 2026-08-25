# 树莓派 Zero 2W 使用说明（本项目的进阶方案）

> 若你只想「能用就好」，**请继续用 Pico 方案**（已验证、便宜、免配置）。下面这套 Zero 2W 方案是
> 「一体机 / 免笔记本 / 能联网」的进阶选择，**更贵、配置更复杂、需实体板子验证**。

## 它在方案里的角色

```
笔记本(可选) ──WiFi/SSH──▶ [树莓派 Zero 2W] ◀── USB OTG 数据线 ──▶ [工控机 USB-A]
                              │  (gadget: USB 键盘+鼠标)
                              └─ 板上跑整套 host 逻辑(读表格→发 HID)
```

Zero 2W 通过它的 **OTG 口（标 `USB` 那个）** 把自己伪装成「USB 键盘 + USB 鼠标」插进工控机，
作用同 Pico；但它本身是一台完整 Linux（有 WiFi），所以：

- 可以不依赖笔记本：把项目拷到 Zero，零板上直接跑命令行版；
- 或保留笔记本的 GUI，把 Zero 当「可远程控制的键鼠」用 WiFi 通信。

## 硬件 / 接线

| Zero 2W 端口 | 用途 |
|---|---|
| 标 `USB` 的 Micro-USB（靠边缘） | **OTG/数据口**：插工控机 USB-A，做成键鼠 |
| 标 `PWR` 的 Micro-USB | 供电 |
| mini-HDMI | 可临时接显示器（跑 GUI 用） |
| microSD | 系统盘 |
| 板载 WiFi/BT | 笔记本 ↔ Zero 无线控制 |

> ⚠️ **只有一个 USB 数据口**。一旦插工控机当键鼠，这个口就无法再同时给笔记本传数据，
> 所以笔记本和 Zero 之间一律走 **WiFi/SSH**，而不是串口（这也是和 Pico+CH340 最大的不同）。

**供电**：工控机 USB-A 通常能供电（500mA 档）；但 Zero 2W 比 Pico 耗电，若工控机 USB 口较弱可能
导致降频/掉线。稳妥做法是另用一个 5V 电源插 `PWR` 口；若靠工控机供电，建议在 `usb_gadget_setup.sh`
里把 `MaxPower` 设为 500 甚至更低，先试稳定性。

## 一、系统准备（一次性）

1. 用 **Raspberry Pi Imager** 给 microSD 烧 **Raspberry Pi OS Lite（64 位）**。
   Imager 的「高级选项」里：开 SSH、设主机名/账号密码、填 WiFi 名称和密码（联网配置用）。
2. 插卡开机，从笔记本 SSH：`ssh 用户名@zero的主机名`（或走 IP）。
3. 更新并安装依赖：
   ```bash
   sudo apt update && sudo apt install -y python3-pip
   pip3 install openpyxl xlrd     # 读 xlsx / xls；只读 csv 可省 xlrd
   ```

## 二、开启 USB 键鼠 gadget

1. 编辑 `/boot/firmware/config.txt`（旧系统是 `/boot/config.txt`），末尾加一行：
   ```
   dtoverlay=dwc2
   ```
2. 编辑 `/boot/firmware/cmdline.txt`（旧系统是 `/boot/cmdline.txt`），在**同一行**末尾追加：
   ```
   modules-load=dwc2,libcomposite
   ```
3. 重启：`sudo reboot`。
4. 运行本项目提供的脚本（一次性，重启后需重跑，见下方“开机自启”）：
   ```bash
   cd zero
   sudo bash usb_gadget_setup.sh
   ```
5. 确认出现设备节点：
   ```bash
   ls -l /dev/hidg0 /dev/hidg1     # hidg0=键盘, hidg1=鼠标
   ```
6. 用一条**能传数据的** Micro-USB 线，把 Zero 的 `USB` 口插到工控机 USB-A。
   工控机应识别出一个「USB 输入设备」（键盘+鼠标）。

> **开机自启**：把 `usb_gadget_setup.sh` 做成服务，例如 `/etc/systemd/system/usb-gadget.service`：
> ```ini
> [Unit]
> Description=Enable USB HID gadget
> [Service]
> Type=oneshot
> ExecStart=/bin/bash /home/<用户>/ipc-auto-fill/zero/usb_gadget_setup.sh
> [Install]
> WantedBy=multi-user.target
> ```
> 然后 `sudo systemctl enable --now usb-gadget`。

## 三、用法 A：全在 Zero 上跑（推荐，运行时不依赖笔记本）

1. 把整个项目拷到 Zero（如 `~/ipc-auto-fill`），把表格 `values.xlsx` 也放进 `host/`。
2. 编辑 `host/config.json`（串口那两项可忽略，HID 后端不用串口）。
3. 用 Zero 上的**命令行版**跑（不改 `run.py`，只换成 HID 后端）：
   ```bash
   cd ipc-auto-fill/zero
   python3 run_on_zero.py --config ../host/config.json --calibrate   # 先校准坐标
   python3 run_on_zero.py --config ../host/config.json               # 开始填数
   ```
   - `--dry-run` 也一样能预览指令。
   - 运行时你在笔记本上 `ssh` 进 Zero 看打印，并到工控机小屏核对，确认后按回车。
4. 想要可视化界面：临时给 Zero 接显示器（mini-HDMI），装带桌面的系统后 `python3 host/gui.py`；
   不建议用 SSH X 转发（太慢）。

## 四、用法 B：保留笔记本 GUI（Zero 走 WiFi）

Zero 仍当键鼠插工控机；在 Zero 上跑 `mcp_hid.py` 作为服务，从 stdin 读指令并执行：
```bash
# Zero 端：把 mcp_hid 常驻，接收一行 JSON 执行一行
python3 mcp_hid.py
```
笔记本端再开一个进程，把命令**通过 WiFi（SSH/网络）喂给它**即可（例如 SSH 管道）。
若要在 GUI 里直接选 Zero，需要给 `run.py/gui.py` 的 `Link` 加一个 **TCP 后端**：
把 `run.Link` 换成连接 Zero 一个端口、发送同样 JSON 指令的 socket 版（要的话我再加）。

## 五、把零板消息对接到本项目

`zero/mcp_hid.py` 实现了和 `host/run.py` **完全相同的命令协议**：
`ping / home / move_to / click_at / dblclick_at / press_at / wheel / type / key / sleep`。
- `HidLink` 具备 `link.send()/ping()/close()`，与 `run.Link` 同接口，可直接替换（见 `run_on_zero.py`）。
- 所有坐标、按键映射逻辑与 Pico 固件一致，因此**表格、步骤流程、config 结构完全复用**。

## 六、常见坑与排查

| 现象 | 原因 / 处理 |
|---|---|
| `ls /dev/hidg*` 空 | 没加 `dtoverlay=dwc2` / `modules-load=dwc2,libcomposite`；或没重启用 gadget |
| `usb_gadget_setup.sh` 报“找不到 UDC” | 同上，先确认 `ls /sys/class/udc` 有输出 |
| 工控机没反应 | 线是**充电线**不能传数据，换一条；或没插 `USB`（OTG）口而插了 `PWR` 口 |
| 光标乱跳/点不准 | 运行中有人动过工控机鼠标导致相对坐标失准，重新归零（home）；先校准坐标 |
| 掉线/重启 | Zero 供电不足，改用 `PWR` 口独立 5V 供电 |
| 输入的中文/符号 | 只支持 ASCII（USB 键盘协议限制）；本项目数值一般是英数 |

## 结论

- **预算 & 省事 → Pico 方案**（本项目默认路径，已验证）。
- **要一体机、免笔记本、可联网、以后想再扩展功能 → 买 Zero 2W**，按本文用法 A 走；
  其中 `zero/usb_gadget_setup.sh` + `zero/mcp_hid.py` + `zero/run_on_zero.py` 已备好，
  **需要有实体 Zero 才能实测**（未在本机验证）。
