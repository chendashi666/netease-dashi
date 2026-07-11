@echo off
title 网易云音乐工具箱
chcp 65001 >nul 2>&1
cd /d "%~dp0"

:: 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    echo 下载地址: https://www.python.org/downloads/
    pause
    exit /b 1
)

:: 检查依赖
python -c "import requests, Crypto" >nul 2>&1
if errorlevel 1 (
    echo [提示] 正在安装依赖...
    pip install -r requirements.txt
    if errorlevel 1 (
        echo [错误] 依赖安装失败，请手动运行: pip install -r requirements.txt
        pause
        exit /b 1
    )
)

:: 启动 GUI（用 pythonw.exe 无控制台窗口）
start "" pythonw gui.py 2>error_launcher.log
if errorlevel 1 (
    echo [错误] GUI 启动失败，请查看 error_launcher.log
    type error_launcher.log
    pause
)