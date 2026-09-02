@echo off
chcp 65001 >nul
setlocal
rem 工控机自动填数助手（host 目录版）—— 双击启动 GUI

cd /d "%~dp0"
if errorlevel 1 (
    echo [错误] 进入本目录失败，请确认本 bat 在 host 文件夹内。
    pause
    exit /b 1
)

set "PY="
if exist "C:\Users\20527\AppData\Local\Programs\Python\Python313\python.exe" (
    set "PY=C:\Users\20527\AppData\Local\Programs\Python\Python313\python.exe"
) else (
    where py >nul 2>nul && set "PY=py"
    if not defined PY (
        where python >nul 2>nul && set "PY=python"
    )
)
if not defined PY (
    echo [错误] 未找到 Python，请安装 Python 3.10+ 并勾选 "Add python.exe to PATH"。
    pause
    exit /b 1
)

"%PY%" -c "import serial, openpyxl, xlrd, tkinter" >nul 2>&1
if errorlevel 1 (
    echo [提示] 缺少依赖，正在尝试安装(pyserial/openpyxl/xlrd)...
    "%PY%" -m pip install -r requirements.txt
)

echo [信息] 正在启动 工控机自动填数助手 ...
"%PY%" gui.py
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请查看上方报错。
    echo.
)
pause
