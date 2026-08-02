@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 正在安裝PySide6與必要套件...
py -m pip install -r requirements.txt
echo.
echo 安裝完成。
pause
