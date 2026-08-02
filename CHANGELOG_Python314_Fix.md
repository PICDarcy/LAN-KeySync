# Python 3.14 SendInput修正

## 發生原因

錯誤：

```text
ctypes.ArgumentError:
expected LP_INPUT instance instead of pointer to INPUT
```

`ctypes.windll.user32.SendInput`可能與PyAutoGUI、pydirectinput或其他套件共用同一個函式物件。
其他套件重新設定`SendInput.argtypes`後，即使兩個結構都命名為`INPUT`，Python 3.14仍會將它們視為不同的ctypes型別。

## 修正內容

- 改用獨立的`ctypes.WinDLL("user32", use_last_error=True)`實例。
- `SendInput.argtypes`綁定目前後端自己的`INPUT`結構。
- 使用`(INPUT * 1)`陣列傳入，不再使用`ctypes.byref(input_event)`。
- 使用`ctypes.get_last_error()`取得正確Win32錯誤碼。
- 客戶端增加`ctypes.ArgumentError`例外保護，單一按鍵錯誤不再讓連線執行緒崩潰。

## 需要替換的檔案

最低限度替換：

- `keyboard_backends.py`
- `keysync_client_core.py`

若需要使用介面內的「3秒後測試F鍵」，也建議替換：

- `client_qt.py`
