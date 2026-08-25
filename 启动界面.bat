@echo off
chcp 65001 >nul
rem 工控机自动填数助手 —— 双击本文件即可打开界面
cd /d "%~dp0host"
where py >nul 2>nul
if %errorlevel%==0 (
    py gui.py
) else (
    python gui.py
)
if errorlevel 1 (
    echo.
    echo 启动失败：请确认已安装 Python 并执行过：
    echo   pip install pyserial openpyxl xlrd
    echo.
)
pause