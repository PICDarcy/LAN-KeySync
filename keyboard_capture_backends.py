from __future__ import annotations

import ctypes
import json
import queue
import sys
import threading
import time
from ctypes import wintypes
from typing import Any, Callable, Protocol

from pynput import keyboard

from keysync_common import key_to_payload

CAPTURE_BETTERGI_HOOK = "bettergi_global_hook"
CAPTURE_ASYNC_POLL = "win32_async_poll"
CAPTURE_PYNPUT = "pynput_legacy"

CAPTURE_LABELS: dict[str, str] = {
    CAPTURE_BETTERGI_HOOK: "BetterGI相容全域鉤子（建議）",
    CAPTURE_ASYNC_POLL: "Win32按鍵狀態輪詢（遊戲備用）",
    CAPTURE_PYNPUT: "pynput（舊版）",
}

InputCallback = Callable[[str, dict[str, Any]], None]
LogCallback = Callable[[str], None]


class KeyboardCaptureBackend(Protocol):
    engine_id: str
    engine_name: str

    def start(self) -> None:
        ...

    def stop(self) -> None:
        ...


VK_NAMES: dict[int, str] = {
    0x08: "Backspace",
    0x09: "Tab",
    0x0D: "Enter",
    0x10: "Shift",
    0x11: "Ctrl",
    0x12: "Alt",
    0x13: "Pause",
    0x14: "CapsLock",
    0x1B: "Esc",
    0x20: "Space",
    0x21: "PageUp",
    0x22: "PageDown",
    0x23: "End",
    0x24: "Home",
    0x25: "Left",
    0x26: "Up",
    0x27: "Right",
    0x28: "Down",
    0x2C: "PrintScreen",
    0x2D: "Insert",
    0x2E: "Delete",
    0x5B: "LWin",
    0x5C: "RWin",
    0x5D: "Menu",
    0x90: "NumLock",
    0x91: "ScrollLock",
    0xA0: "LShift",
    0xA1: "RShift",
    0xA2: "LCtrl",
    0xA3: "RCtrl",
    0xA4: "LAlt",
    0xA5: "RAlt",
}
for number in range(10):
    VK_NAMES[0x30 + number] = str(number)
    VK_NAMES[0x60 + number] = f"Num{number}"
for number in range(26):
    VK_NAMES[0x41 + number] = chr(ord("A") + number)
for number in range(1, 25):
    VK_NAMES[0x70 + number - 1] = f"F{number}"


def require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("遊戲鍵盤偵測引擎只支援Windows。")


def is_running_as_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def describe_payload(payload: dict[str, Any]) -> str:
    if payload.get("kind") == "vk":
        vk = int(payload.get("value", 0))
        return VK_NAMES.get(vk, f"VK_{vk:02X}")
    if payload.get("kind") == "special":
        return str(payload.get("value", "特殊鍵"))
    if payload.get("kind") == "char":
        return str(payload.get("value", "字元"))
    return json.dumps(payload, ensure_ascii=False)


class BetterGIGlobalHookCapture:
    """
    BetterGI相容的全域鍵盤鉤子。

    BetterGI的MouseKeyMonitor使用Gma.System.MouseKeyHook.Hook.GlobalEvents()。
    該套件在Windows底層使用WH_KEYBOARD_LL；此處直接以ctypes實作相同類型的
    低階全域鍵盤鉤子，避免pynput封裝層在遊戲焦點下失效。
    """

    engine_id = CAPTURE_BETTERGI_HOOK
    engine_name = "Win32 WH_KEYBOARD_LL／BetterGI相容全域鉤子"

    WH_KEYBOARD_LL = 13
    WM_KEYDOWN = 0x0100
    WM_KEYUP = 0x0101
    WM_SYSKEYDOWN = 0x0104
    WM_SYSKEYUP = 0x0105
    WM_QUIT = 0x0012

    LLKHF_EXTENDED = 0x01
    LLKHF_LOWER_IL_INJECTED = 0x02
    LLKHF_INJECTED = 0x10

    def __init__(
        self,
        event_callback: InputCallback,
        log_callback: LogCallback,
        ignore_injected: bool = True,
    ) -> None:
        require_windows()
        self.event_callback = event_callback
        self.log_callback = log_callback
        self.ignore_injected = ignore_injected

        self._running = threading.Event()
        self._startup_event = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self._hook_handle: int | None = None
        self._hook_proc: Any = None

        # 使用獨立DLL函式物件，避免其他輸入套件改寫argtypes。
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

        ulong_ptr = wintypes.WPARAM

        class KBDLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [
                ("vkCode", wintypes.DWORD),
                ("scanCode", wintypes.DWORD),
                ("flags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        self._KBDLLHOOKSTRUCT = KBDLLHOOKSTRUCT
        self._LRESULT = ctypes.c_ssize_t
        self._HOOKPROC = ctypes.WINFUNCTYPE(
            self._LRESULT,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        self._user32.SetWindowsHookExW.argtypes = (
            ctypes.c_int,
            self._HOOKPROC,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        )
        self._user32.SetWindowsHookExW.restype = ctypes.c_void_p

        self._user32.CallNextHookEx.argtypes = (
            ctypes.c_void_p,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self._user32.CallNextHookEx.restype = self._LRESULT

        self._user32.UnhookWindowsHookEx.argtypes = (ctypes.c_void_p,)
        self._user32.UnhookWindowsHookEx.restype = wintypes.BOOL

        self._user32.GetMessageW.argtypes = (
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
        )
        self._user32.GetMessageW.restype = wintypes.BOOL

        self._user32.TranslateMessage.argtypes = (ctypes.POINTER(wintypes.MSG),)
        self._user32.TranslateMessage.restype = wintypes.BOOL

        self._user32.DispatchMessageW.argtypes = (ctypes.POINTER(wintypes.MSG),)
        self._user32.DispatchMessageW.restype = self._LRESULT

        self._user32.PostThreadMessageW.argtypes = (
            wintypes.DWORD,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )
        self._user32.PostThreadMessageW.restype = wintypes.BOOL

        self._kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE
        self._kernel32.GetCurrentThreadId.argtypes = ()
        self._kernel32.GetCurrentThreadId.restype = wintypes.DWORD

    def start(self) -> None:
        if self._running.is_set():
            return

        self._startup_error = None
        self._startup_event.clear()
        self._running.set()
        self._thread = threading.Thread(
            target=self._message_loop,
            daemon=True,
            name="keysync-bettergi-hook",
        )
        self._thread.start()

        if not self._startup_event.wait(timeout=5.0):
            self.stop()
            raise RuntimeError("全域鍵盤鉤子啟動逾時。")

        if self._startup_error is not None:
            error = self._startup_error
            self.stop()
            raise RuntimeError(f"全域鍵盤鉤子啟動失敗：{error}") from error

    def stop(self) -> None:
        self._running.clear()
        if self._thread_id:
            try:
                self._user32.PostThreadMessageW(
                    self._thread_id,
                    self.WM_QUIT,
                    0,
                    0,
                )
            except OSError:
                pass

        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

        self._thread = None
        self._thread_id = 0

    def _message_loop(self) -> None:
        try:
            self._thread_id = int(self._kernel32.GetCurrentThreadId())
            self._hook_proc = self._HOOKPROC(self._hook_callback)
            module_handle = self._kernel32.GetModuleHandleW(None)

            ctypes.set_last_error(0)
            hook_handle = self._user32.SetWindowsHookExW(
                self.WH_KEYBOARD_LL,
                self._hook_proc,
                module_handle,
                0,
            )
            if not hook_handle:
                error = ctypes.get_last_error()
                raise OSError(error, "SetWindowsHookExW失敗")

            self._hook_handle = int(hook_handle)
            self._startup_event.set()
            self.log_callback(f"輸入偵測已啟動：{self.engine_name}")

            message = wintypes.MSG()
            while self._running.is_set():
                result = int(
                    self._user32.GetMessageW(
                        ctypes.byref(message),
                        None,
                        0,
                        0,
                    )
                )
                if result <= 0:
                    break
                self._user32.TranslateMessage(ctypes.byref(message))
                self._user32.DispatchMessageW(ctypes.byref(message))

        except BaseException as exc:
            self._startup_error = exc
            self._startup_event.set()
            self.log_callback(f"全域鍵盤鉤子錯誤：{exc}")
        finally:
            if self._hook_handle:
                try:
                    self._user32.UnhookWindowsHookEx(
                        ctypes.c_void_p(self._hook_handle)
                    )
                except OSError:
                    pass
            self._hook_handle = None
            self._hook_proc = None
            self._running.clear()
            self._startup_event.set()

    def _hook_callback(
        self,
        code: int,
        w_param: int,
        l_param: int,
    ) -> int:
        try:
            if code >= 0:
                data = ctypes.cast(
                    l_param,
                    ctypes.POINTER(self._KBDLLHOOKSTRUCT),
                ).contents

                injected_flags = (
                    self.LLKHF_INJECTED
                    | self.LLKHF_LOWER_IL_INJECTED
                )
                if not (
                    self.ignore_injected
                    and (int(data.flags) & injected_flags)
                ):
                    message = int(w_param)
                    if message in (self.WM_KEYDOWN, self.WM_SYSKEYDOWN):
                        action = "press"
                    elif message in (self.WM_KEYUP, self.WM_SYSKEYUP):
                        action = "release"
                    else:
                        action = ""

                    if action:
                        payload = {
                            "kind": "vk",
                            "value": int(data.vkCode),
                            "scan_code": int(data.scanCode),
                            "extended": bool(
                                int(data.flags) & self.LLKHF_EXTENDED
                            ),
                            "source": self.engine_id,
                        }
                        self.event_callback(action, payload)
        except BaseException as exc:
            # 鉤子回呼不能把例外傳回Windows。
            self.log_callback(f"鍵盤鉤子事件處理失敗：{exc}")

        return int(
            self._user32.CallNextHookEx(
                ctypes.c_void_p(self._hook_handle or 0),
                code,
                w_param,
                l_param,
            )
        )


class AsyncKeyStateCapture:
    """
    使用GetAsyncKeyState高速輪詢實體鍵狀態。

    這不是鉤子，所以即使遊戲或其他程式攔截低階鍵盤訊息，通常仍能讀到目前的
    Virtual-Key按下狀態。此模式只送出狀態切換，不送出作業系統自動重複事件。
    """

    engine_id = CAPTURE_ASYNC_POLL
    engine_name = "Win32 GetAsyncKeyState高速輪詢"

    # 排除滑鼠按鍵、未定義鍵及會與左右修飾鍵重複的通用修飾鍵。
    EXCLUDED_VKS = {
        0x01, 0x02, 0x03, 0x04, 0x05, 0x06,
        0x07,
        0x10, 0x11, 0x12,
        0xFF,
    }

    def __init__(
        self,
        event_callback: InputCallback,
        log_callback: LogCallback,
        interval_ms: float = 2.0,
    ) -> None:
        require_windows()
        self.event_callback = event_callback
        self.log_callback = log_callback
        self.interval_seconds = max(0.001, interval_ms / 1000.0)
        self._running = threading.Event()
        self._thread: threading.Thread | None = None
        self._pressed: set[int] = set()

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
        self._user32.MapVirtualKeyW.restype = wintypes.UINT

        self._virtual_keys = [
            vk
            for vk in range(0x08, 0xFF)
            if vk not in self.EXCLUDED_VKS
        ]

    def start(self) -> None:
        if self._running.is_set():
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True,
            name="keysync-async-key-state",
        )
        self._thread.start()
        self.log_callback(f"輸入偵測已啟動：{self.engine_name}")

    def stop(self) -> None:
        self._running.clear()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._thread = None
        self._pressed.clear()

    def _is_pressed(self, vk: int) -> bool:
        return bool(int(self._user32.GetAsyncKeyState(vk)) & 0x8000)

    def _payload(self, vk: int) -> dict[str, Any]:
        # MAPVK_VK_TO_VSC_EX = 4，可在回傳值高位保留E0/E1資訊。
        mapped = int(self._user32.MapVirtualKeyW(vk, 4))
        return {
            "kind": "vk",
            "value": vk,
            "scan_code": mapped & 0xFF,
            "extended": bool(mapped & 0xFF00),
            "source": self.engine_id,
        }

    def _poll_loop(self) -> None:
        try:
            # 啟動時只建立基準，不把已經按住的鍵誤判為新按下。
            self._pressed = {
                vk for vk in self._virtual_keys if self._is_pressed(vk)
            }

            while self._running.is_set():
                current = {
                    vk for vk in self._virtual_keys if self._is_pressed(vk)
                }

                for vk in sorted(current - self._pressed):
                    self.event_callback("press", self._payload(vk))

                for vk in sorted(self._pressed - current):
                    self.event_callback("release", self._payload(vk))

                self._pressed = current
                time.sleep(self.interval_seconds)

        except BaseException as exc:
            self.log_callback(f"按鍵狀態輪詢錯誤：{exc}")
            self._running.clear()


class PynputLegacyCapture:
    engine_id = CAPTURE_PYNPUT
    engine_name = "pynput全域Listener（舊版）"

    def __init__(
        self,
        event_callback: InputCallback,
        log_callback: LogCallback,
    ) -> None:
        self.event_callback = event_callback
        self.log_callback = log_callback
        self._listener: keyboard.Listener | None = None

    def start(self) -> None:
        if self._listener is not None:
            return

        def on_press(key: keyboard.Key | keyboard.KeyCode) -> None:
            payload = key_to_payload(key)
            if payload is not None:
                payload["source"] = self.engine_id
                self.event_callback("press", payload)

        def on_release(key: keyboard.Key | keyboard.KeyCode) -> None:
            payload = key_to_payload(key)
            if payload is not None:
                payload["source"] = self.engine_id
                self.event_callback("release", payload)

        self._listener = keyboard.Listener(
            on_press=on_press,
            on_release=on_release,
        )
        self._listener.start()
        self.log_callback(f"輸入偵測已啟動：{self.engine_name}")

    def stop(self) -> None:
        listener = self._listener
        self._listener = None
        if listener is not None:
            listener.stop()


def create_keyboard_capture(
    engine_id: str,
    event_callback: InputCallback,
    log_callback: LogCallback,
) -> KeyboardCaptureBackend:
    if engine_id == CAPTURE_BETTERGI_HOOK:
        return BetterGIGlobalHookCapture(event_callback, log_callback)
    if engine_id == CAPTURE_ASYNC_POLL:
        return AsyncKeyStateCapture(event_callback, log_callback)
    if engine_id == CAPTURE_PYNPUT:
        return PynputLegacyCapture(event_callback, log_callback)
    raise ValueError(f"未知鍵盤偵測引擎：{engine_id}")
