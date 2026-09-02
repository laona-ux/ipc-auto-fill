@echo off
chcp 65001 >nul
setlocal
rem 工控机自动填数助手（离线便携版）—— 双击即可打开界面，无需安装、无需联网

rem 1) 优先使用本目录自带的便携 Python（python\ 文件夹），完全离线
set "PY="
if exist "%~dp0python\python.exe" (
    set "PY=%~dp0python\python.exe"
) else (
    where py >nul 2>nul && set "PY=py"
    if not defined PY (
        where python >nul 2>nul && set "PY=python"
    )
)
if not defined PY (
    echo [错误] 未找到 Python。本程序已自带离线 Python（python\ 文件夹），请确认 python\ 文件夹与本文件在同一目录；或在系统安装 Python 3.10+ 并勾选加入 PATH。
    pause
    exit /b 1
)

rem 2) 进入 host 目录
cd /d "%~dp0host"
if errorlevel 1 (
    echo [错误] 无法进入 host 目录，请确认本文件与 host 文件夹在同一目录。
    pause
    exit /b 1
)

rem 3) 依赖自检：缺失则从本地 依赖\ 文件夹离线安装（不联网）
"%PY%" -c "import serial, openpyxl, xlrd, tkinter" >nul 2>&1
if errorlevel 1 (
    echo [提示] 本地依赖缺失，正在从 依赖\ 文件夹离线安装（不联网）...
    "%PY%" -m pip install --no-index --find-links "%~dp0依赖" pyserial==3.5 openpyxl==3.1.5 xlrd==2.0.2
    if errorlevel 1 (
        echo [错误] 离线依赖安装失败，请确认 依赖\ 文件夹与本文件在同一目录且包含所需 .whl 文件。
        pause
        exit /b 1
    )
)

rem 4) 启动 GUI
echo [信息] 正在启动 工控机自动填数助手 ...
"%PY%" gui.py
if errorlevel 1 (
    echo.
    echo [错误] 启动失败，请查看上方报错；或手动在 host 目录运行: "%PY%" gui.py
    echo.
)
pause
