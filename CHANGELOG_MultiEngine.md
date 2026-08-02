# BetterGI／PyAutoGUI輸出引擎更新

## 問題判斷

先前`pydirectinput-rgx`版本使用掃描碼模式。檢查BetterGI原始碼後，發現BetterGI的`InputBuilder`會同時填入`wVk`與`wScan`，但不加入`KEYEVENTF_SCANCODE`；最後透過Windows`SendInput`送出。

## 本次修正

- 新增`keyboard_backends.py`。
- 預設改成BetterGI相容Virtual-Key SendInput。
- 新增PyAutoGUI輸出引擎。
- 保留DirectInput掃描碼引擎。
- Qt客戶端新增輸出引擎下拉選單。
- 新增3秒後輸出F鍵的快速測試。
- 顯示目前是否使用系統管理員權限。
- `run_client.bat`會自動要求管理員權限。
- 客戶端EXE使用`--uac-admin`建立。
