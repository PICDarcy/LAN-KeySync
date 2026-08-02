@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo 安裝必要套件...
py -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto error

echo.
echo 建立Qt主控端EXE...
py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --noconsole ^
  --name LAN_KeySync_Qt_Server ^
  --uac-admin ^
  --collect-all PySide6 ^
  server_qt.py
if errorlevel 1 goto error

echo.
echo 建立Qt客戶端EXE...
py -m PyInstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --noconsole ^
  --name LAN_KeySync_Qt_Client ^
  --uac-admin ^
  --collect-all PySide6 ^
  --collect-all pydirectinput ^
  client_qt.py
if errorlevel 1 goto error

echo.
echo 建立完成。
echo EXE位於：%~dp0dist
pause
exit /b 0

:error
echo.
echo 建立失敗，請查看上方錯誤訊息。
pause
exit /b 1
