@echo off
chcp 65001 >nul
setlocal
rem 工控机自动填数助手（host 目录版 · 离线便携）—— 双击启动 GUI

cd /d "%~dp0"
if errorlevel 1 (
    echo [错误] 进入本目录失败，请确认本文件在 host 文件夹内。
    pause
    exit /b 1
)

set "PY="
if exist "%~dp0..\python\python.exe" (
    set "PY=%~dp0..\python\python.exe"
) else (
    where py >nul 2>nul && set "PY=py"
    if not defined PY (
        where python >nul 2>nul && set "PY=python"
    )
)
if not defined PY (
    echo [错误] 未找到 Python。本程序已自带离线 Python（python\ 文件夹，位于 host 的上级目录），请确认目录结构完整；或在系统安装 Python 3.10+。
    pause
    exit /b 1
)

"%PY%" -c "import serial, openpyxl, xlrd, tkinter" >nul 2>&1
if errorlevel 1 (
    echo [提示] 本地依赖缺失，正在从 依赖\ 文件夹离线安装（不联网）...
    "%PY%" -m pip install --no-index --find-links "%~dp0..\依赖" pyserial==3.5 openpyxl==3.1.5 xlrd==2.0.2
    if errorlevel 1 (
        echo [错误] 离线依赖安装失败，请确认 依赖\ 文件夹位于 host 的上级目录且包含所需 .whl 文件。
        pause
        exit /b 1
    )
)

echo [信息] 正在启动 工控机自动填数助手 ...
"%PY%" gui.py
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请查看上方报错。
    echo.
)
pause
