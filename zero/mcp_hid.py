#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_hid.py —— 树莓派 Zero 2W 端的「USB 键鼠」执行器（参考实现，需实体 Zero 验证）。
复用 host/run.py 的命令协议：一行一条 JSON（UTF-8，\\n 结尾），执行后回 {"ack":"ok"}。

需要先运行 usb_gadget_setup.sh 启用 HID 设备。本机约定：
    /dev/hidg0 = 键盘（8 字节 report）
    /dev/hidg1 = 鼠标（4 字节 report，相对移动）

两种用法：
  1) 直接管道喂指令（适合 SSH 调试）：
        python3 mcp_hid.py            # 从 stdin 读，回 ack 到 stdout
  2) 作为 run.py 的后端（在 Zero 上跑本项目的命令行版，见 run_on_zero.py）：
        from mcp_hid import HidLink   # 具备 link.send()/ping()/close() 接口

注意：本文件需要实体 Zero 2W 才能实测；未在本机验证。
"""
import json
import os
import struct
import sys
import time

KEYBOARD_DEV = os.environ.get("HID_KEYBOARD", "/dev/hidg0")
MOUSE_DEV = os.environ.get("HID_MOUSE", "/dev/hidg1")

# ---- HID 修饰键位 ----
MOD_CTRL = 0x01
MOD_SHIFT = 0x02
MOD_ALT = 0x04
MOD_GUI = 0x08

# ---- USB 键码（与 Pico 的 adafruit_hid 一致）----
KEYCODES = {
    "enter": 40, "tab": 43, "space": 44, "backspace": 42, "delete": 76,
    "esc": 41, "escape": 41, "up": 82, "down": 81, "left": 80, "right": 79,
    "home": 74, "end": 77, "pageup": 75, "pagedown": 78, "insert": 73,
    "f1": 58, "f2": 59, "f3": 60, "f4": 61, "f5": 62, "f6": 63,
    "f7": 64, "f8": 65, "f9": 66, "f10": 67, "f11": 68, "f12": 69,
    "printscreen": 70, "menu": 101, "capslock": 57,
}
MODIFIERS = {
    "ctrl": MOD_CTRL, "control": MOD_CTRL, "shift": MOD_SHIFT,
    "alt": MOD_ALT, "win": MOD_GUI,
}
# ASCII 字符 -> (USB 键码, 是否需要 shift)
CHAR_KEYS = {}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    CHAR_KEYS[_c] = (4 + _i, False)
for _i, _c in enumerate("1234567890"):
    CHAR_KEYS[_c] = (30 + _i, False)   # 1..0
CHAR_KEYS.update({
    "-": (45, False), "=": (46, False), "[": (47, False), "]": (48, False),
    "\\": (49, False), ";": (51, False), "'": (52, False), "`": (53, False),
    ",": (54, False), ".": (55, False), "/": (56, False),
    "!": (30, True), "@": (31, True), "#": (32, True), "$": (33, True),
    "%": (34, True), "^": (35, True), "&": (36, True), "*": (37, True),
    "(": (38, True), ")": (39, True), "_": (45, True), "+": (46, True),
    "{": (47, True), "}": (48, True), "|": (49, True), ":": (51, True),
    "\"": (52, True), "~": (53, True), "<": (54, True), ">": (55, True),
    "?": (56, True), " ": (44, False), "\n": (40, False), "\t": (43, False),
})

HOME_SLAM = 60
STEP_DELAY = 0.005
MOVED_MAX = 120


def _parse_key(spec):
    """把一个键名令牌转成 (键码列表, 修饰位)。如 'ctrl+a' / 'shift+tab' / 'enter' / 'A'。"""
    raw = [p.strip() for p in spec.split("+") if p.strip()]
    if not raw:
        return None, 0
    modifiers = 0
    codes = []
    for p in raw:
        low = p.lower()
        if low in MODIFIERS:
            modifiers |= MODIFIERS[low]
        elif low in KEYCODES:
            codes.append(KEYCODES[low])
        elif len(p) == 1 and (p.isalnum() or p in CHAR_KEYS):
            if p.isalpha() and p.isupper():
                code = CHAR_KEYS.get(p.lower(), (None, False))[0]
                modifiers |= MOD_SHIFT
            else:
                code, sh = CHAR_KEYS.get(p, (None, False))
                if sh:
                    modifiers |= MOD_SHIFT
            if code is None:
                return None, 0
            codes.append(code)
        else:
            return None, 0
    if not codes:
        return None, 0
    return codes, modifiers


class HidKeyboard:
    def __init__(self, path=KEYBOARD_DEV):
        self.f = open(path, "wb", buffering=0)

    def _report(self, modifier, keys):
        # report: [modifier, 0, k1..k6]
        buf = [modifier, 0] + list(keys[:6]) + [0] * max(0, 6 - len(keys))
        self.f.write(bytes(buf[:8]))

    def _clear(self):
        self.f.write(bytes([0, 0, 0, 0, 0, 0, 0, 0]))

    def press_combo(self, spec):
        codes, mods = _parse_key(spec)
        if codes is None:
            return False
        self._report(mods, codes)
        time.sleep(0.03)
        self._clear()
        return True

    def type_ascii(self, text):
        for ch in text:
            if ord(ch) > 126 and ch not in "\t\n":
                raise ValueError("不支持的非 ASCII 字符: %r" % ch)
            if ch == "\n":
                self.press_combo("enter")
                continue
            if ch == "\t":
                self.press_combo("tab")
                continue
            if ch.isalpha() and ch.isupper():
                # 大写字母：用小写键码 + Shift
                code = CHAR_KEYS.get(ch.lower(), (None, False))[0]
                shift = True
            else:
                code, shift = CHAR_KEYS.get(ch, (None, False))
            if code is None:
                raise ValueError("无键码字符: %r" % ch)
            self._report(MOD_SHIFT if shift else 0, [code])
            time.sleep(0.01)
            self._clear()
            time.sleep(0.01)


class HidMouse:
    BUTTON_LEFT = 1

    def __init__(self, path=MOUSE_DEV):
        self.f = open(path, "wb", buffering=0)
        self.cursor = (0, 0)

    def _move(self, dx, dy, wheel=0):
        self.f.write(struct.pack("Bbbb", 0, dx, dy, wheel))

    def _buttons(self, buttons):
        self.f.write(struct.pack("Bbbb", buttons, 0, 0, 0))

    def slam_home(self):
        for _ in range(HOME_SLAM):
            self._move(-127, -127)
            time.sleep(STEP_DELAY)
        self.cursor = (0, 0)

    def move_to(self, x, y):
        dx = int(x) - self.cursor[0]
        dy = int(y) - self.cursor[1]
        import math
        steps = max(math.ceil(abs(dx) / 127.0), math.ceil(abs(dy) / 127.0), 1)
        if steps > MOVED_MAX:
            raise ValueError("move_to 分步超限: %s,%s" % (x, y))
        sx, rx = divmod(dx, steps)
        sy, ry = divmod(dy, steps)
        for i in range(steps):
            self._move(sx + (1 if i < rx else 0), sy + (1 if i < ry else 0))
            time.sleep(STEP_DELAY)
        self.cursor = (int(x), int(y))

    def click_at(self, x, y):
        self.move_to(x, y)
        time.sleep(0.05)
        self._buttons(self.BUTTON_LEFT)
        time.sleep(0.03)
        self._buttons(0)

    def dblclick_at(self, x, y):
        self.move_to(x, y)
        time.sleep(0.05)
        self._buttons(self.BUTTON_LEFT); time.sleep(0.03); self._buttons(0)
        time.sleep(0.05)
        self._buttons(self.BUTTON_LEFT); time.sleep(0.03); self._buttons(0)

    def press_at(self, x, y, ms):
        self.move_to(x, y)
        time.sleep(0.05)
        self._buttons(self.BUTTON_LEFT)
        time.sleep(max(0, ms) / 1000.0)
        self._buttons(0)

    def wheel(self, delta):
        self._move(0, 0, wheel=int(delta))


class HidLink:
    """drop-in：和 run.Link 一样有 send()/ping()/close()。可直接替换。"""
    def __init__(self, port="hid", baud=None):
        self.kb = HidKeyboard()
        self.mouse = HidMouse()

    def close(self):
        for o in (self.kb, self.mouse):
            try:
                o.f.close()
            except Exception:
                pass

    def ping(self):
        return True

    def send(self, cmd, timeout=5.0):
        handle(cmd, self.kb, self.mouse)
        return {"ack": "ok"}


def handle(cmd, kb, mouse):
    if not isinstance(cmd, dict):
        raise ValueError("not_object")
    op = cmd.get("op")
    if op == "ping":
        return
    if op == "home":
        mouse.slam_home()
    elif op == "move_to":
        if mouse.cursor is None:
            raise ValueError("未归零，请先 home")
        mouse.move_to(int(cmd["x"]), int(cmd["y"]))
    elif op == "click_at":
        mouse.click_at(int(cmd["x"]), int(cmd["y"]))
    elif op == "dblclick_at":
        mouse.dblclick_at(int(cmd["x"]), int(cmd["y"]))
    elif op == "press_at":
        mouse.press_at(int(cmd["x"]), int(cmd["y"]), int(cmd.get("ms", 500)))
    elif op == "wheel":
        mouse.wheel(cmd.get("delta", -120))
    elif op == "type":
        kb.type_ascii(cmd["text"])
    elif op == "key":
        if not kb.press_combo(cmd["key"]):
            raise ValueError("未知按键: %s" % cmd["key"])
    elif op == "sleep":
        time.sleep(max(0, int(cmd["ms"])) / 1000.0)
    else:
        raise ValueError("未知指令: %s" % op)
    return {"ack": "ok"}


def main():
    kb = HidKeyboard()
    mouse = HidMouse()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
            handle(cmd, kb, mouse)
            print(json.dumps({"ack": "ok", "op": cmd.get("op")}, ensure_ascii=False))
        except Exception as e:
            print(json.dumps({"ack": "error", "msg": str(e)}, ensure_ascii=False))
    kb.f.close()
    mouse.f.close()


if __name__ == "__main__":
    main()
