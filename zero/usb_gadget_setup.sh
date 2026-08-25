#!/bin/bash
# usb_gadget_setup.sh
# 在树莓派 Zero 2W 上，用 configfs(libcomposite) 把它变成「USB 键盘 + USB 鼠标」复合设备。
# 运行后，把 Zero 的 OTG 口（标 "USB" 的 Micro-USB）用数据线插到工控机 USB-A 口，
# 工控机就会识别出一个输入设备（键盘+鼠标）。
#
# 用法：
#   sudo bash usb_gadget_setup.sh        # 手动启用（重启后需重跑，或装成开机服务）
# 持久化（开机自启）：见下方 systemd 单元示例。
#
# 依赖的设备树覆盖与内核模块（写在 /boot/firmware/config.txt 和 cmdline.txt）：
#   config.txt 加： dtoverlay=dwc2
#   cmdline.txt 追加（同一行末尾）： modules-load=dwc2,libcomposite

set -e
if [ "$(id -u)" -ne 0 ]; then
  echo "请用 sudo 运行。" >&2
  exit 1
fi

modprobe libcomposite

CDIR=/sys/kernel/config
GADGET=$CDIR/usb_gadget/g0
[ -d "$GADGET" ] && { echo "gadget 已存在，已跳过（如需重建请先清理 $GADGET）。"; exit 0; }

mkdir -p "$GADGET"
cd "$GADGET"

echo 0x1d6b > idVendor       # Linux Foundation
echo 0x0104 > idProduct      # Multifunction Composite Gadget
echo 0x0100 > bcdDevice
echo 0x0200 > bcdUSB

mkdir -p strings/0x409
echo "ipc-hid" > strings/0x409/manufacturer
echo "IPC USB Keyboard+Mouse" > strings/0x409/product
echo "0000000001" > strings/0x409/serialnumber

# ---- 键盘 HID 函数 (hid.usb0) ----
mkdir -p functions/hid.usb0
echo 1 > functions/hid.usb0/protocol      # boot protocol
echo 1 > functions/hid.usb0/subclass      # boot subclass
echo 8 > functions/hid.usb0/report_length # [modifier, reserved, k1..k6]
# 标准 USB 键盘 report descriptor
printf '%s' '05010906a101050719e029e71500250175019508810295017508810195057501050819012905910295017503910195067508150026ff000507190029658100c0' \
  | xxd -r -p > functions/hid.usb0/report_desc

# ---- 鼠标 HID 函数 (hid.usb1) ----
mkdir -p functions/hid.usb1
echo 0 > functions/hid.usb1/protocol
echo 0 > functions/hid.usb1/subclass
echo 4 > functions/hid.usb1/report_length # [buttons, relX, relY, wheel]
printf '%s' '05010902a1010901a1000509190129031500250195037501810295017505810105010930093109381581257f750895038106c0c0' \
  | xxd -r -p > functions/hid.usb1/report_desc

# ---- 绑定到配置 ----
mkdir -p configs/c.1/strings/0x409
echo "gadget config" > configs/c.1/strings/0x409/configuration
echo 500 > configs/c.1/MaxPower   # 500mA；工控机 USB 需能供此电流
ln -s functions/hid.usb0 configs/c.1/
ln -s functions/hid.usb1 configs/c.1/

# ---- 激活 ----
UDC=$(ls /sys/class/udc 2>/dev/null | head -n1)
if [ -z "$UDC" ]; then
  echo "找不到 UDC（确认已加 dtoverlay=dwc2 且已 modprobe dwc2）。" >&2
  exit 1
fi
echo "$UDC" > UDC
echo "已启用：/dev/hidg0=键盘, /dev/hidg1=鼠标"
echo "现在把 Zero 的『USB』口插到工控机即可。"
