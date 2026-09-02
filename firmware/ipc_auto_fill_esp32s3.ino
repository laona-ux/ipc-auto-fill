/*
 * ipc_auto_fill_esp32s3.ino
 * ----------------------------------------------------------------
 * 把 reasonix/ipc-auto-fill 项目中「树莓派 Pico」的 USB 键鼠注入角色
 * 移植到 YD-ESP32-S3 开发板（顶替 Pico）。
 *
 * 拓扑（与 Pico 方案完全一致）：
 *   笔记本(host/run.py) ──UART@115200──▶ ESP32-S3(UART0 = 本机 COM12)
 *                                      └─原生 USB(右 USB-C 口)──▶ 工控机(表现为 USB 键鼠)
 *
 * 协议：每行一条 JSON（UTF-8，\n 结尾），板子回一行 {"ack":...} 或 {"pong":true}
 *   {"op":"ping"}                          -> {"pong":true}
 *   {"op":"home"}                          把光标甩到左上角并设原点 (0,0)
 *   {"op":"move_to","x":120,"y":96}        移到绝对坐标（内部记录上次位置）
 *   {"op":"click_at","x":120,"y":96}       移到该坐标并左键单击
 *   {"op":"dblclick_at","x":120,"y":96}    移到该坐标并双击
 *   {"op":"press_at","x":120,"y":96,"ms":800} 移到该坐标，按住左键 ms 毫秒后松开
 *   {"op":"wheel","delta":-120}            滚轮，>0 上滚，<0 下滚
 *   {"op":"type","text":"25.5"}            键盘输入文本（ASCII；\t=Tab \n=Enter）
 *   {"op":"key","key":"enter"}             按一个键；支持 ctrl+a / shift+tab
 *   {"op":"sleep","ms":500}                等待 ms 毫秒
 *   {"op":"get_pos"}                       回当前内部光标坐标
 *
 * 编译/烧录（arduino-cli）：
 *   arduino-cli compile -b esp32:esp32:esp32s3 <本目录>
 *   arduino-cli upload  -b esp32:esp32:esp32s3 -p COM12 <本目录>
 */

#include "USB.h"
#include "USBHIDKeyboard.h"
#include "USBHIDMouse.h"
#include <WiFi.h>
#include <Preferences.h>

// ---------------- 配置 ----------------
#define BAUD        115200
#define HOME_STEPS  60          // home 时向 (0,0) 甩的步数（每步 -127，覆盖 7620px）
#define STEP_DELAY  1           // 每步相对移动之间的停顿(ms)
#define MOVE_MAX    120          // 单次 move_to 允许的最大分步数，防死循环

// ---------------- 无线（WiFi 控制通道） ----------------
// 推荐：通过 GUI 的「保存并连接」把 SSID/密码写入 ESP32 的 NVS（断电保存，无需改代码重烧）。
// 下面仅作为『NVS 为空时的兜底默认值』——一般留空，首次用 GUI 配置后即可连 WiFi。
// ESP32 连上后，会在 TCP_PORT 上监听——本协议（每行一条 JSON）与串口完全一致。
// 串口(UART/COM12)始终保留作兜底通道：两条通道并行可用、互不冲突。
#define WIFI_SSID       ""      // 兜底默认 SSID（一般留空，用 GUI 写入 NVS）
#define WIFI_PASSWORD   ""      // 兜底默认密码
#define TCP_PORT        8080

// 主机链路（双通道）：UART0（开发板左侧 FTDI 口 = 本机 COM12） + WiFi TCP Server
HardwareSerial Host(0);
// 注意：WiFiServer / WiFiClient 不能做全局对象——其构造或 begin() 在 Arduino 核心与
// 网络事件循环就绪前会触碰 WiFi 栈，触发 xQueueSemaphoreTake(NULL) 断言导致反复重启。
// 故均改为指针，延迟到 setup() / WiFi 真正连上后再 new 与 begin()。
WiFiServer *server = nullptr;
WiFiClient *tcpClient = nullptr;
Preferences prefs;          // NVS 句柄：持久化 WiFi 凭据（断电保存）
String g_ssid = "";         // 当前生效 SSID（NVS 优先，其次 #define 兜底）
String g_pass = "";         // 当前生效密码
bool serverStarted = false; // TCP 监听是否已在 WiFi 就绪后启动

USBHIDKeyboard Keyboard;
USBHIDMouse    Mouse;

// 内部记录的光标绝对坐标（像素），None 表示尚未 home 校准
long cursorX = -1, cursorY = -1;
bool homed = false;

// ---------------- HID 用法 ID（USB HID Usage Page 0x07，与 adafruit_hid 一致）----
// 普通字符：a-z=0x04..0x1d, 1-9=0x1e..0x26, 0=0x27
#define HID_A 0x04
#define KEY_ENTER   0x28
#define KEY_TAB     0x2B
#define KEY_ESC     0x29
#define KEY_BACKSP  0x2A
#define KEY_DELETE  0x4C
#define KEY_SPACE   0x2C
#define KEY_UP      0x52
#define KEY_DOWN    0x51
#define KEY_LEFT    0x50
#define KEY_RIGHT   0x4F
#define KEY_HOME    0x4A
#define KEY_END     0x4D
#define KEY_PGUP    0x4B
#define KEY_PGDOWN  0x4E
#define KEY_INSERT  0x49
#define KEY_F1 0x3A
#define KEY_F2 0x3B
#define KEY_F3 0x3C
#define KEY_F4 0x3D
#define KEY_F5 0x3E
#define KEY_F6 0x3F
#define KEY_F7 0x40
#define KEY_F8 0x41
#define KEY_F9 0x42
#define KEY_F10 0x43
#define KEY_F11 0x44
#define KEY_F12 0x45

#define MOD_CTRL 0xE0
#define MOD_SHIFT 0xE1
#define MOD_ALT 0xE2
#define MOD_GUI 0xE3

// 把键名映射到 HID 用法 ID（单字符键按 ASCII 计算）
long aliasToKey(const String& t) {
  String k = t;
  k.toLowerCase();
  if (k == "enter")    return KEY_ENTER;
  if (k == "tab")      return KEY_TAB;
  if (k == "esc" || k == "escape") return KEY_ESC;
  if (k.startsWith("f") && k.length() <= 3) {
    int n = k.substring(1).toInt();
    if (n >= 1 && n <= 12) return KEY_F1 + (n - 1);
  }
  if (k == "backspace") return KEY_BACKSP;
  if (k == "delete")    return KEY_DELETE;
  if (k == "space")     return KEY_SPACE;
  if (k == "up")    return KEY_UP;
  if (k == "down")  return KEY_DOWN;
  if (k == "left")  return KEY_LEFT;
  if (k == "right") return KEY_RIGHT;
  if (k == "home")  return KEY_HOME;
  if (k == "end")   return KEY_END;
  if (k == "pageup")   return KEY_PGUP;
  if (k == "pagedown") return KEY_PGDOWN;
  if (k == "insert")   return KEY_INSERT;
  if (k == "menu")     return 0x76;  // KEY_MENU
  if (k == "capslock") return 0x39;
  if (k == "numlock")  return 0x53;
  if (k.length() == 1) {
    char c = k[0];
    if (c >= 'a' && c <= 'z') return HID_A + (c - 'a');
    if (c >= '1' && c <= '9') return 0x1E + (c - '1');
    if (c == '0') return 0x27;
    if (c == '-' || c == '_') return 0x2D;
    if (c == '.' || c == '>') return 0x37;
    if (c == ',' || c == '<') return 0x36;
    if (c == ';' || c == ':') return 0x33;
    if (c == '/') return 0x38;
    if (c == '=' || c == '+') return 0x2E;
  }
  return -1;
}

// 按一个键或组合键，如 "enter" / "ctrl+a" / "shift+tab"
bool pressKey(const String& spec) {
  int firstPlus = spec.indexOf('+');
  // 拆分修饰键与普通键
  String modPart = "", keyPart = "";
  if (firstPlus >= 0) {
    String left = spec.substring(0, firstPlus);
    keyPart = spec.substring(firstPlus + 1);
    // 允许 ctrl+shift+a 这种多修饰（简单起见只认一个修饰 + 一个键）
    int sp2 = left.indexOf('+');
    if (sp2 >= 0) { modPart = left.substring(0, sp2) + "," + left.substring(sp2 + 1); }
    else modPart = left;
  } else {
    keyPart = spec;
  }
  uint8_t toPress[6];
  int n = 0;
  // 修饰键
  if (modPart.length()) {
    int idx = 0;
    while (idx < modPart.length()) {
      int comma = modPart.indexOf(',', idx);
      String m = (comma < 0) ? modPart.substring(idx) : modPart.substring(idx, comma);
      m.toLowerCase();
      if (m == "ctrl" || m == "control") toPress[n++] = MOD_CTRL;
      else if (m == "shift") toPress[n++] = MOD_SHIFT;
      else if (m == "alt")   toPress[n++] = MOD_ALT;
      else if (m == "win" || m == "gui") toPress[n++] = MOD_GUI;
      if (comma < 0) break;
      idx = comma + 1;
    }
  }
  // 普通键
  long kid = aliasToKey(keyPart);
  if (kid < 0) return false;
  toPress[n++] = (uint8_t)kid;
  if (n == 0) return false;
  // 注意：esp32 的 Keyboard.press() 把参数当 ASCII/Arduino keycode，
  // 而本草图内部统一用「原生 HID usage 码」(0x28=Enter, 0xE0=Ctrl...)，
  // 必须用 pressRaw() 才能正确发送。
  Keyboard.pressRaw(toPress[0]);
  for (int i = 1; i < n; i++) Keyboard.pressRaw(toPress[i]);
  delay(50);
  Keyboard.releaseAll();
  return true;
}

// ---------------- 鼠标动作 ----------------
void slamHome() {
  for (int i = 0; i < HOME_STEPS; i++) {
    Mouse.move(-127, -127, 0);
    delay(STEP_DELAY);
  }
  cursorX = 0; cursorY = 0; homed = true;
}

void moveTo(long x, long y) {
  // 不在每个动作前重新归零：动作完成后坐标保持连续（停在上一动作结束点），
  // 仅当从未建立过原点时（首次移动）补一次 home，避免内部坐标偏移。
  if (!homed) slamHome();
  long dx = x - cursorX;
  long dy = y - cursorY;
  // 用「向上取整」保证单步不超过 ±127，避免被 move() 截断造成累计偏移
  long dist = max(abs(dx), abs(dy));
  long steps = max((dist + 126L) / 127L, 1L);
  if (steps > MOVE_MAX) steps = MOVE_MAX;
  long stepX = dx / steps, stepY = dy / steps;
  long remX = dx - stepX * steps, remY = dy - stepY * steps;
  for (long i = 0; i < steps; i++) {
    int mx = (int)(stepX + (i < remX ? 1 : 0));
    int my = (int)(stepY + (i < remY ? 1 : 0));
    if (mx < -127) mx = -127; if (mx > 127) mx = 127;
    if (my < -127) my = -127; if (my > 127) my = 127;
    Mouse.move(mx, my, 0);
    delay(STEP_DELAY);
  }
  cursorX = x; cursorY = y;
}

void clickAt(long x, long y) {
  moveTo(x, y);
  delay(50);
  Mouse.click(MOUSE_LEFT);
}
void dblClickAt(long x, long y) {
  moveTo(x, y);
  delay(50);
  Mouse.click(MOUSE_LEFT);
  delay(50);
  Mouse.click(MOUSE_LEFT);
}
void pressAt(long x, long y, long ms) {
  moveTo(x, y);
  delay(50);
  Mouse.press(MOUSE_LEFT);
  delay(max(0L, ms));
  Mouse.release(MOUSE_LEFT);
}
void wheel(int delta) {
  Mouse.move(0, 0, delta);
}

// ---------------- 极简 JSON 取值 ----------------
String getStr(const String& j, const char* key) {
  String k = String("\"") + key + "\":";
  int i = j.indexOf(k);
  if (i < 0) return "";
  int c = j.indexOf('"', i + k.length());
  if (c < 0) return "";
  int e = j.indexOf('"', c + 1);
  if (e < 0) return "";
  return j.substring(c + 1, e);
}
long getInt(const String& j, const char* key, long def) {
  String k = String("\"") + key + "\":";
  int i = j.indexOf(k);
  if (i < 0) return def;
  int s = i + k.length();
  while (s < j.length() && (j[s] == ' ' || j[s] == '\t')) s++;
  int e = s;
  while (e < j.length() && j[e] != ',' && j[e] != '}' && j[e] != ' ' && j[e] != '\n' && j[e] != '\r') e++;
  String num = j.substring(s, e);
  num.trim();
  return num.length() ? num.toInt() : def;
}

// ---------------- 应答（out 可为 Host(UART) 或 WiFi 客户端，协议一致） ----------------
void sendRaw(Print& out, const String& s) {
  out.print(s);
  out.print('\n');
}
void ackOk(Print& out, const String& op) {
  sendRaw(out, "{\"ack\":\"ok\",\"op\":\"" + op + "\"}");
}
void ackErr(Print& out, const String& op, const String& msg) {
  sendRaw(out, "{\"ack\":\"error\",\"op\":\"" + op + "\",\"msg\":\"" + msg + "\"}");
}

// ---------------- 指令分发（out = 应答写回的通道：UART 或 WiFi） ----------------
void handle(const String& line, Print& out) {
  String op = getStr(line, "op");
  if (op.length() == 0) { sendRaw(out, "{\"ack\":\"error\",\"msg\":\"no_op\"}"); return; }

  if (op == "ping") { sendRaw(out, "{\"pong\":true}"); return; }

  // 网络/无线诊断：回报 WiFi 连接状态、本地 IP、信号强度、TCP 监听端口。
  // host 端「测试连接 / HID 检测」可借此拿到 ESP32 在 WiFi 下的 IP，填进 GUI 即可无线控制。
  if (op == "net_info") {
    bool up = (WiFi.status() == WL_CONNECTED);
    String ip = up ? WiFi.localIP().toString() : String("0.0.0.0");
    sendRaw(out, "{\"ack\":\"ok\",\"op\":\"net_info\",\"wifi\":" + String(up ? "true" : "false") +
                  ",\"ip\":\"" + ip + "\",\"rssi\":" + String(up ? WiFi.RSSI() : 0) +
                  ",\"port\":" + String(TCP_PORT) + "}");
    return;
  }

  // 运行时配置 WiFi 凭据并立即重连：GUI「保存并连接」调用。凭据存入 NVS（断电保存）。
  if (op == "set_wifi") {
    String ssid = getStr(line, "ssid");
    String pass = getStr(line, "pass");
    if (ssid.length() == 0) { ackErr(out, op, "empty_ssid"); return; }
    prefs.begin("wificfg", false);
    prefs.putString("ssid", ssid);
    prefs.putString("pass", pass);
    prefs.end();
    g_ssid = ssid; g_pass = pass;
    WiFi.mode(WIFI_STA);
    WiFi.begin(ssid.c_str(), pass.c_str());
    ackOk(out, op); return;
  }

  // 诊断：汇报原生 USB(HID) 是否被对端（工控机）枚举成功。
  // mounted=true 表示对端已挂载本 HID 复合设备（键盘+鼠标）；false 表示枚举未建立
  // （线材无数据线 / 端口损坏 / 对端未识别 / USB 模式不对）。
  // 注：USB 全局对象 operator bool() 返回 _started && tinyusb_device_mounted。
  if (op == "usb_state") {
    bool mounted = (bool)USB;
    sendRaw(out, "{\"ack\":\"ok\",\"op\":\"usb_state\",\"mounted\":" + String(mounted ? "true" : "false") + "}");
    return;
  }

  if (op == "home") { slamHome(); ackOk(out, op); return; }

  if (op == "move_to") {
    long x = getInt(line, "x", 0), y = getInt(line, "y", 0);
    moveTo(x, y); ackOk(out, op); return;
  }
  if (op == "click_at") {
    long x = getInt(line, "x", 0), y = getInt(line, "y", 0);
    clickAt(x, y); ackOk(out, op); return;
  }
  if (op == "dblclick_at") {
    long x = getInt(line, "x", 0), y = getInt(line, "y", 0);
    dblClickAt(x, y); ackOk(out, op); return;
  }
  if (op == "press_at") {
    long x = getInt(line, "x", 0), y = getInt(line, "y", 0);
    long ms = getInt(line, "ms", 500);
    pressAt(x, y, ms); ackOk(out, op); return;
  }
  if (op == "wheel") {
    int d = (int)getInt(line, "delta", -120);
    wheel(d); ackOk(out, op); return;
  }
  if (op == "get_pos") {
    // 与 Pico 固件保持一致：未归零校准前返回 error，由 host 决定自动 home 或提示用户。
    if (!homed) { ackErr(out, op, "not_homed"); return; }
    sendRaw(out, "{\"ack\":\"ok\",\"op\":\"get_pos\",\"x\":" + String(cursorX) + ",\"y\":" + String(cursorY) + "}");
    return;
  }
  if (op == "type") {
    String text = getStr(line, "text");
    for (unsigned int i = 0; i < text.length(); i++) {
      char ch = text.charAt(i);
      if (ch == '\t') { Keyboard.pressRaw(KEY_TAB); Keyboard.releaseAll(); }
      else if (ch == '\n') { Keyboard.pressRaw(KEY_ENTER); Keyboard.releaseAll(); }
      else { Keyboard.print(String(ch)); }
      delay(10);
    }
    ackOk(out, op); return;
  }
  if (op == "key") {
    String key = getStr(line, "key");
    if (!pressKey(key)) { ackErr(out, op, "unknown_key:" + key); return; }
    ackOk(out, op); return;
  }
  if (op == "sleep") {
    long ms = getInt(line, "ms", 0);
    delay(max(0L, ms));
    ackOk(out, op); return;
  }
  ackErr(out, op, "unknown_op");
}

// ---------------- WiFi 凭据（NVS 持久化 + 运行时可改） ----------------
// 优先从 NVS 读取（GUI「保存并连接」写入），为空则回退到代码里的 #define 兜底。
void loadWiFiCreds() {
  prefs.begin("wificfg", false);
  String s = prefs.getString("ssid", "");
  String p = prefs.getString("pass", "");
  prefs.end();
  g_ssid = (s.length() ? s : String(WIFI_SSID));
  g_pass = (p.length() ? p : String(WIFI_PASSWORD));
}
// 用当前 g_ssid/g_pass 发起连接（set_wifi 改完凭据后、或启动时使用）。
void connectWiFi() {
  if (g_ssid.length() == 0) return;   // 没有任何凭据则不瞎连
  WiFi.mode(WIFI_STA);
  WiFi.begin(g_ssid.c_str(), g_pass.c_str());
}

// ---------------- setup / loop ----------------
void setup() {
  // 主机链路 UART0（COM12，兜底通道）
  Host.begin(BAUD);
  // 原生 USB：键盘 + 鼠标复合设备（接工控机的右 USB-C 口，HID 注入通道保持有线）
  USB.begin();
  Keyboard.begin();
  Mouse.begin();
  // 无线控制通道：载入凭据（NVS→兜底）。注意：TCP 监听 server->begin() 必须在
  // WiFi 栈就绪（WiFi 已连上）之后才能调用，否则会触碰 NULL 信号量断言。
  // 因此这里只 new 出对象、载入凭据；server->begin() 放到 loop() 里连上 WiFi 后再执行。
  loadWiFiCreds();
  connectWiFi();                       // 仅在有凭据时才会 WiFi.begin()（启动栈并连接）
  server = new WiFiServer(TCP_PORT);   // 仅创建对象，暂不 begin
  delay(500);
  sendRaw(Host, "{\"ready\":true,\"role\":\"esp32s3-hid\",\"transport\":\"uart+wifi\"}");
}

void loop() {
  // --- 无线通道维护：断线周期性重试重连（仅当有凭据时才重试） ---
  if (g_ssid.length() && WiFi.status() != WL_CONNECTED) {
    static unsigned long lastTry = 0;
    if (millis() - lastTry > 5000) { WiFi.reconnect(); lastTry = millis(); }
  }

  // --- WiFi 已连上且 TCP 服务尚未启动：此刻网络栈已就绪，安全调用 server->begin() ---
  if (WiFi.status() == WL_CONNECTED && server && !serverStarted) {
    server->begin();
    serverStarted = true;
  }

  // --- 接受新的 TCP 客户端（单客户端模型：新连接顶掉旧连接） ---
  if (server && server->hasClient()) {
    WiFiClient c = server->available();
    if (c) {
      if (tcpClient && tcpClient->connected()) tcpClient->stop();
      tcpClient = new WiFiClient(c);
      sendRaw(*tcpClient, "{\"ready\":true,\"role\":\"esp32s3-hid\",\"transport\":\"wifi\"}");
    }
  }

  // --- UART 通道（兜底，与 WiFi 并行） ---
  static String ubuf = "";
  while (Host.available()) {
    char c = Host.read();
    if (c == '\n') {
      ubuf.trim();
      if (ubuf.length()) handle(ubuf, Host);
      ubuf = "";
    } else if (c != '\r') {
      ubuf += c;
    }
  }

  // --- WiFi 通道 ---
  static String wbuf = "";
  if (tcpClient && tcpClient->connected()) {
    while (tcpClient->available()) {
      char c = tcpClient->read();
      if (c == '\n') {
        wbuf.trim();
        if (wbuf.length()) handle(wbuf, *tcpClient);
        wbuf = "";
      } else if (c != '\r') {
        wbuf += c;
      }
    }
  } else {
    wbuf = "";
  }

  delay(5);
}
