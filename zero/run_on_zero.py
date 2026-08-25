#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_on_zero.py —— 在树莓派 Zero 2W 上直接运行本项目的命令行版 run.py。
把 run.Link 换成 mcp_hid.HidLink（直接驱动 /dev/hidg0/1），其余逻辑不变。

前提：
  1) 已运行 usb_gadget_setup.sh 启用 HID 设备（/dev/hidg0=键盘 /dev/hidg1=鼠标）。
  2) 本项目已拷到 Zero，且把表格文件（如 values.xlsx）路径写进 host/config.json。
  3) 用 py/python3 执行（先 pip install openpyxl；.xls 再 pip install xlrd）。

用法（在 Zero 上，host 目录）：
    python3 run_on_zero.py --config config.json
    python3 run_on_zero.py --config config.json --calibrate
注意：--dry-run 也要能跑，但它不需要 Link。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "host"))   # 让 run.py 可导入
sys.path.insert(0, HERE)                               # 让 mcp_hid 可导入

import run
import mcp_hid

# 把 run 的串口 Link 替换成 HID 后端（其余宿主逻辑完全复用）
run.Link = mcp_hid.HidLink

if __name__ == "__main__":
    run.main()
