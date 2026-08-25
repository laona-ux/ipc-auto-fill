# code.py —— 树莓派 Pico 主程序
# Pico 插在工控机的 USB-A 口上，对工控机表现为「USB 键盘 + USB 鼠标」。
# 笔记本通过 CH340 串口（接到 GP0/GP1）向 Pico 发 JSON 行指令，
# Pico 执行完每条指令回一行 {"ack": ...}。
#
# 协议（每行一条 JSON，UTF-8，\n 结尾）：
#   {"op":"ping"}                             -> {"pong":true}
#   {"op":"home"}                             把光标甩到屏幕左上角，并把内部原点设为 (0,0)
#   {"op":"move_to","x":120,"y":96}           把光标移到绝对坐标（相对上一次位置移动）
#   {"op":"click_at","x":120,"y":96}          移到该坐标并左键单击
#   {"op":"dblclick_at","x":120,"y":96}       移到该坐标并双击
#   {"op":"press_at","x":120,"y":96,"ms":800} 移到该坐标，按住左键 ms 毫秒后松开（长按）
#   {"op":"wheel","delta":-120}               滚动滚轮，delta>0 向上滚，<0 向下滚
#   {"op":"type","text":"25.5"}               键盘输入文本（ASCII；\t=Tab \n=Enter）
#   {"op":"key","key":"enter"}                按一个键；支持 ctrl+a / shift+tab 这类组合
#   {"op":"sleep","ms":500}                   等待 ms 毫秒
#
# 坐标采用「相对移动 + 内部记录上次位置」实现绝对定位：
# 先执行一次 home 校准原点，之后 move_to 根据 dx/dy 分步发送 HID 相对移动。
# 注意：使用期间不要人工移动工控机的鼠标/触摸屏，否则内部记录的坐标会失准。

import board
import busio
import json
import math
import time

import usb_hid

try:
    from adafruit_hid.keycode import Keycode
except ImportError:  # 新版 bundle 里 Keycode 移到了 keyboard_usb 模块
    from adafruit_hid.keyboard_usb import Keycode
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keyboard_layout_us import KeyboardLayoutUS
from adafruit_hid.mouse import Mouse

# ---------------- 配置 ----------------
BAUD = 115200              # 串口波特率，与 host/run.py 保持一致
HOME_SLAM_STEPS = 60       # home 时向 (0,0) 方向甩的步数（每步上限 127，共可覆盖 7620 像素）
STEP_DELAY_MS = 0.005      # 每步相对移动之间的停顿（秒）
MOVED_MAX = 120            # 单次 move_to 允许的最大分步数，防死循环

# ---------------- 初始化 ----------------
# 串口：GP0=TX -> CH340 RXD，GP1=RX <- CH340 TXD，GND 共地
uart = busio.UART(board.GP0, board.GP1, baudrate=BAUD, timeout=0.02,
                  receiver_buffer_size=1024)

keyboard = Keyboard(usb_hid.devices)
layout = KeyboardLayoutUS(keyboard)
mouse = Mouse(usb_hid.devices)

# 内部记录的光标位置（绝对坐标，像素）。None 表示还没归零校准。
cursor = None

# ---------------- 按键映射 ----------------
KEY_ALIASES = {
    "enter": Keycode.ENTER,
    "tab": Keycode.TAB,
    "esc": Keycode.ESCAPE,
    "escape": Keycode.ESCAPE,
    "f5": Keycode.F5,
    "f1": Keycode.F1,
    "f2": Keycode.F2,
    "f3": Keycode.F3,
    "f4": Keycode.F4,
    "f6": Keycode.F6,
    "f7": Keycode.F7,
    "f8": Keycode.F8,
    "f9": Keycode.F9,
    "f10": Keycode.F10,
    "f11": Keycode.F11,
    "f12": Keycode.F12,
    "backspace": Keycode.BACKSPACE,
    "delete": Keycode.DELETE,
    "space": Keycode.SPACE,
    "up": Keycode.UP_ARROW,
    "down": Keycode.DOWN_ARROW,
    "left": Keycode.LEFT_ARROW,
    "right": Keycode.RIGHT_ARROW,
    "home": Keycode.HOME,
    "end": Keycode.END,
    "pageup": Keycode.PAGE_UP,
    "pagedown": Keycode.PAGE_DOWN,
    "insert": getattr(Keycode, "INSERT", None),
    "printscreen": getattr(Keycode, "PRINT_SCREEN", None),
    "menu": getattr(Keycode, "MENU", None),
    "capslock": getattr(Keycode, "CAPS_LOCK", None),
    "numlock": getattr(Keycode, "KEYPAD_NUMLOCK", None),
}
# 去掉缺失的按键（某些 bundle 版本可能没有对应 Keycode）
KEY_ALIASES = {k: v for k, v in KEY_ALIASES.items() if v is not None}

MODIFIER_ALIASES = {
    "ctrl": Keycode.LEFT_CONTROL,
    "control": Keycode.LEFT_CONTROL,
    "shift": Keycode.LEFT_SHIFT,
    "alt": Keycode.LEFT_ALT,
    "win": Keycode.LEFT_GUI,
}

def _token_to_keys(token):
    """把一个键名令牌转成 Keycode 列表。字母/数字返回单键，别名返回映射键。"""
    t = token.strip().lower()
    if t in KEY_ALIASES:
        return [KEY_ALIASES[t]]
    if len(t) == 1 and (t.isalnum() or t in "-_.,;:"):
        try:
            return [Keycode.ord_to_keycode(ord(t.upper()))]
        except (ValueError, TypeError):
            return None
    return None

def press_key(spec):
    """按一个键或组合键，如 enter / ctrl+a / shift+tab。"""
    parts = [p.strip() for p in spec.split("+") if p.strip()]
    if not parts:
        return False
    modifiers = []
    plain = []
    for p in parts:
        if p.lower() in MODIFIER_ALIASES:
            modifiers.append(MODIFIER_ALIASES[p.lower()])
        else:
            keys = _token_to_keys(p)
            if not keys:
                return False
            plain.extend(keys)
    if not plain and not modifiers:
        return False
    if modifiers and not plain:  # 纯修饰键不允许
        return False
    to_press = modifiers + plain
    keyboard.press(*to_press)
    time.sleep(0.05)
    keyboard.release_all()
    return True

# ---------------- 鼠标动作 ----------------
def slam_home():
    """把光标甩到屏幕左上角并设原点 (0,0)。大步相对移动会被显示驱动钳制在屏幕边界。"""
    global cursor
    for _ in range(HOME_SLAM_STEPS):
        mouse.move(-127, -127)
        time.sleep(STEP_DELAY_MS)
    cursor = (0, 0)

def move_to(x, y):
    """把光标移到绝对坐标 (x, y)，基于内部记录的上一次位置做相对移动。"""
    global cursor
    dx = int(x) - cursor[0]
    dy = int(y) - cursor[1]
    # HID 相对移动单步上限 ±127，按最大差值分步（向上取整，保证每步不超限）
    steps = max(math.ceil(abs(dx) / 127.0), math.ceil(abs(dy) / 127.0), 1)
    if steps > MOVED_MAX:
        raise ValueError("move_to 分步数超过上限，疑似坐标异常: x=%s y=%s" % (x, y))
    # 整数分配：每步基准 step_X，前 rem_X 步各多加 1，保证每步整数且总和精确
    step_x, rem_x = divmod(dx, steps)
    step_y, rem_y = divmod(dy, steps)
    for i in range(steps):
        mouse.move(step_x + (1 if i < rem_x else 0),
                   step_y + (1 if i < rem_y else 0))
        time.sleep(STEP_DELAY_MS)
    cursor = (int(x), int(y))

def click_at(x, y):
    move_to(x, y)
    time.sleep(0.05)          # 给目标软件一点处理时间
    mouse.click(Mouse.LEFT_BUTTON)

def dblclick_at(x, y):
    move_to(x, y)
    time.sleep(0.05)
    mouse.click(Mouse.LEFT_BUTTON)
    time.sleep(0.05)
    mouse.click(Mouse.LEFT_BUTTON)

def press_at(x, y, ms):
    """移动到坐标并按住左键 ms 毫秒后松开（模拟长按）。"""
    move_to(x, y)
    time.sleep(0.05)
    mouse.press(Mouse.LEFT_BUTTON)
    time.sleep(max(0, ms) / 1000.0)
    mouse.release(Mouse.LEFT_BUTTON)

def wheel(delta):
    """滚动滚轮；delta>0 向上滚，<0 向下滚。"""
    mouse.move(0, 0, wheel=int(delta))

# ---------------- 指令处理 ----------------
def send(obj):
    uart.write((json.dumps(obj) + "\n").encode("utf-8"))

def handle(msg):
    try:
        cmd = json.loads(msg)
    except ValueError:
        send({"ack": "error", "msg": "bad_json"})
        return
    if not isinstance(cmd, dict):
        send({"ack": "error", "msg": "not_object"})
        return
    op = cmd.get("op")
    global cursor
    try:
        if op == "ping":
            send({"pong": True})
            return
        elif op == "home":
            slam_home()
        elif op == "move_to":
            if cursor is None:
                raise ValueError("未归零校准，请先发送 home（或在配置里打开 start_home）")
            move_to(int(cmd["x"]), int(cmd["y"]))
        elif op == "click_at":
            if cursor is None:
                raise ValueError("未归零校准，请先发送 home（或在配置里打开 start_home）")
            click_at(int(cmd["x"]), int(cmd["y"]))
        elif op == "dblclick_at":
            if cursor is None:
                raise ValueError("未归零校准，请先发送 home")
            dblclick_at(int(cmd["x"]), int(cmd["y"]))
        elif op == "press_at":
            if cursor is None:
                raise ValueError("未归零校准，请先发送 home")
            press_at(int(cmd["x"]), int(cmd["y"]), int(cmd.get("ms", 500)))
        elif op == "wheel":
            wheel(cmd.get("delta", -120))
        elif op == "get_pos":
            if cursor is None:
                raise ValueError("未归零校准，请先发送 home")
            send({"ack": "ok", "op": op, "x": cursor[0], "y": cursor[1]})
            return
        elif op == "type":
            text = cmd["text"]
            for ch in text:
                if ord(ch) > 126 and ch not in "\t\n":
                    raise ValueError("不支持的非 ASCII 字符: %r" % ch)
            layout.write(text)
        elif op == "key":
            if not press_key(cmd["key"]):
                raise ValueError("未知按键: %s" % cmd["key"])
        elif op == "sleep":
            ms = max(0, int(cmd["ms"]))
            time.sleep(ms / 1000.0)
        else:
            raise ValueError("未知指令: %s" % op)
    except Exception as e:  # 单条指令失败不影响后面
        send({"ack": "error", "op": op, "msg": str(e)})
        return
    send({"ack": "ok", "op": op})

# ---------------- 主循环 ----------------
buf = b""
while True:
    data = uart.read(64)
    if data:
        buf += data
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            line = line.strip()
            if line:
                handle(line.decode("utf-8", errors="replace"))
    time.sleep(0.01)