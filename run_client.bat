@echo off
chcp 65001 >nul
cd /d "%~dp0"

net session >nul 2>&1
if %errorlevel% neq 0 (
    echo 正在要求系統管理員權限...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)

py client_qt.py
if errorlevel 1 pause
