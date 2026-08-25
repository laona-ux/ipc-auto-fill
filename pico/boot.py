# boot.py —— 在 CircuitPython 枚举 USB 之前运行
# 目标：让 Pico 在工控机上显示为「USB 键盘 + USB 鼠标」，
#       不显示串口控制台（避免工控机上多出 COM 设备）。
# CIRCUITPY 磁盘保留：方便以后直接复制文件更新 code.py。
# 如需也隐藏磁盘，取消下面注释：
# import storage
# storage.disable_usb_drive()
import usb_cdc
import usb_hid

usb_cdc.disable()
usb_hid.enable((usb_hid.Device.KEYBOARD, usb_hid.Device.MOUSE))