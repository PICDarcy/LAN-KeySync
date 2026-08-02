# 主控端遊戲輸入偵測修正

## 問題

原版主控端使用`pynput.Listener`。部分遊戲取得焦點後，pynput可能無法收到按鍵事件，導致客戶端完全沒有同步輸入。

## 參考BetterGI後的修正

BetterGI的`MouseKeyMonitor`使用`Gma.System.MouseKeyHook.Hook.GlobalEvents()`訂閱全域`KeyDown`與`KeyUp`事件。本版本直接以Python ctypes實作Windows`WH_KEYBOARD_LL`低階全域鍵盤鉤子，避免pynput封裝層。

## 額外備用模式

新增`GetAsyncKeyState`每2ms輪詢。當遊戲或其他程式攔截低階鍵盤鉤子時，可以改用此模式讀取Virtual-Key目前狀態。

## 其他改善

- 主控端Qt介面增加鍵盤偵測引擎選單。
- 顯示最後偵測按鍵及事件總數。
- 鍵盤鉤子回呼只將事件加入佇列，網路傳送改由獨立執行緒處理，避免鉤子逾時。
- 過濾同一按鍵的系統自動重複KeyDown。
- 忽略注入型鍵盤事件，避免模擬輸入被再次廣播。
- `run_server.bat`與主控端EXE自動要求系統管理員權限。
