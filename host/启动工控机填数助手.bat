@echo off
setlocal
cd /d "%~dp0"

REM ---- 检查 Python ----
where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未找到 python。请安装 Python 3.10+ 并勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

REM ---- 优先用本地 .venv，不存在则创建（避免污染系统 Python）----
if not exist ".venv\Scripts\python.exe" (
    echo [INFO] 创建本地虚拟环境 .venv ...
    python -m venv .venv
)
call .venv\Scripts\activate.bat

REM ---- 安装依赖（离线工控机请提前在有网机器装好，或自备 wheels）----
python -m pip install -q -r requirements.txt
if errorlevel 1 (
    echo [WARN] 依赖安装失败（可能离线）。若已手动装好 pyserial/openpyxl/xlrd 可忽略。
)

REM ---- 启动 GUI 操作台（独立窗口）----
echo [INFO] 启动 工控机自动填数助手 ...
start "" python gui.py
endlocal
