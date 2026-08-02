from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

ENGINE_BETTERGI = "bettergi_sendinput"
ENGINE_PYAUTOGUI = "pyautogui"
ENGINE_DIRECTINPUT = "directinput_scancode"

ENGINE_LABELS: dict[str, str] = {
    ENGINE_BETTERGI: "BetterGI相容SendInput（建議）",
    ENGINE_PYAUTOGUI: "PyAutoGUI",
    ENGINE_DIRECTINPUT: "DirectInput掃描碼（舊版）",
}


@runtime_checkable
class KeyboardBackend(Protocol):
    engine_id: str
    engine_name: str

    def resolve_key(self, payload: dict[str, Any]) -> Any:
        ...

    def key_down(self, key: Any) -> None:
        ...

    def key_up(self, key: Any) -> None:
        ...


# Windows Virtual-Key constants used by both BetterGI-compatible and PyAutoGUI backends.
VK_BACK = 0x08
VK_TAB = 0x09
VK_CLEAR = 0x0C
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_PAUSE = 0x13
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_SELECT = 0x29
VK_PRINT = 0x2A
VK_EXECUTE = 0x2B
VK_SNAPSHOT = 0x2C
VK_INSERT = 0x2D
VK_DELETE = 0x2E
VK_HELP = 0x2F
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_APPS = 0x5D
VK_NUMPAD0 = 0x60
VK_MULTIPLY = 0x6A
VK_ADD = 0x6B
VK_SEPARATOR = 0x6C
VK_SUBTRACT = 0x6D
VK_DECIMAL = 0x6E
VK_DIVIDE = 0x6F
VK_F1 = 0x70
VK_NUMLOCK = 0x90
VK_SCROLL = 0x91
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF
VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_STOP = 0xB2
VK_MEDIA_PLAY_PAUSE = 0xB3

_SPECIAL_TO_VK: dict[str, int] = {
    "alt": VK_MENU,
    "alt_l": VK_LMENU,
    "alt_r": VK_RMENU,
    "backspace": VK_BACK,
    "caps_lock": VK_CAPITAL,
    "cmd": VK_LWIN,
    "cmd_l": VK_LWIN,
    "cmd_r": VK_RWIN,
    "ctrl": VK_CONTROL,
    "ctrl_l": VK_LCONTROL,
    "ctrl_r": VK_RCONTROL,
    "delete": VK_DELETE,
    "down": VK_DOWN,
    "end": VK_END,
    "enter": VK_RETURN,
    "esc": VK_ESCAPE,
    "home": VK_HOME,
    "insert": VK_INSERT,
    "left": VK_LEFT,
    "media_next": VK_MEDIA_NEXT_TRACK,
    "media_play_pause": VK_MEDIA_PLAY_PAUSE,
    "media_previous": VK_MEDIA_PREV_TRACK,
    "media_stop": VK_MEDIA_STOP,
    "media_volume_down": VK_VOLUME_DOWN,
    "media_volume_mute": VK_VOLUME_MUTE,
    "media_volume_up": VK_VOLUME_UP,
    "menu": VK_APPS,
    "num_lock": VK_NUMLOCK,
    "page_down": VK_NEXT,
    "page_up": VK_PRIOR,
    "pause": VK_PAUSE,
    "print_screen": VK_SNAPSHOT,
    "right": VK_RIGHT,
    "scroll_lock": VK_SCROLL,
    "shift": VK_SHIFT,
    "shift_l": VK_LSHIFT,
    "shift_r": VK_RSHIFT,
    "space": VK_SPACE,
    "tab": VK_TAB,
    "up": VK_UP,
}
for number in range(1, 25):
    _SPECIAL_TO_VK[f"f{number}"] = VK_F1 + number - 1


@dataclass(frozen=True)
class VirtualKey:
    vk: int


def _require_windows() -> None:
    if sys.platform != "win32":
        raise RuntimeError("鍵盤輸出引擎只支援Windows。")


def is_running_as_admin() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def _payload_to_vk(payload: dict[str, Any]) -> int:
    kind = payload.get("kind")
    value = payload.get("value")

    if kind == "vk":
        vk = int(value)
        if not 0 <= vk <= 0xFF:
            raise ValueError(f"Virtual-Key超出範圍：{vk}")
        return vk

    if kind == "special":
        if not isinstance(value, str):
            raise ValueError("特殊鍵資料錯誤")
        vk = _SPECIAL_TO_VK.get(value)
        if vk is None:
            raise ValueError(f"不支援的特殊鍵：{value}")
        return vk

    if kind == "char":
        if not isinstance(value, str) or not value:
            raise ValueError("字元按鍵資料錯誤")
        _require_windows()
        result = int(ctypes.windll.user32.VkKeyScanW(value[0]))
        if result == -1:
            raise ValueError(f"字元無法轉成Virtual-Key：{value[0]!r}")
        return result & 0xFF

    raise ValueError(f"未知按鍵類型：{kind}")


class BetterGISendInputKeyboard:
    """
    依照BetterGI的Fischless.WindowsInput做法輸出按鍵：
    - INPUT_KEYBOARD
    - wVk保留Virtual-Key
    - wScan填入MapVirtualKey結果
    - 不設定KEYEVENTF_SCANCODE
    - 僅設定EXTENDEDKEY與KEYUP
    """

    engine_id = ENGINE_BETTERGI
    engine_name = "BetterGI相容／Win32 SendInput Virtual-Key"

    INPUT_KEYBOARD = 1
    KEYEVENTF_EXTENDEDKEY = 0x0001
    KEYEVENTF_KEYUP = 0x0002
    MAPVK_VK_TO_VSC = 0

    # 與BetterGI InputBuilder.IsExtendedKey的判定保持一致。
    EXTENDED_KEYS = {
        VK_MENU,
        VK_LMENU,
        VK_RMENU,
        VK_CONTROL,
        VK_RCONTROL,
        VK_INSERT,
        VK_DELETE,
        VK_HOME,
        VK_END,
        VK_PRIOR,
        VK_NEXT,
        VK_RIGHT,
        VK_UP,
        VK_LEFT,
        VK_DOWN,
        VK_NUMLOCK,
        0x03,  # VK_CANCEL
        VK_SNAPSHOT,
        VK_DIVIDE,
    }

    def __init__(self) -> None:
        _require_windows()
        from ctypes import wintypes

        ulong_ptr = wintypes.WPARAM

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [
                ("dx", wintypes.LONG),
                ("dy", wintypes.LONG),
                ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [
                ("wVk", wintypes.WORD),
                ("wScan", wintypes.WORD),
                ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD),
                ("dwExtraInfo", ulong_ptr),
            ]

        class HARDWAREINPUT(ctypes.Structure):
            _fields_ = [
                ("uMsg", wintypes.DWORD),
                ("wParamL", wintypes.WORD),
                ("wParamH", wintypes.WORD),
            ]

        class INPUTUNION(ctypes.Union):
            _fields_ = [
                ("mi", MOUSEINPUT),
                ("ki", KEYBDINPUT),
                ("hi", HARDWAREINPUT),
            ]

        class INPUT(ctypes.Structure):
            _anonymous_ = ("union",)
            _fields_ = [
                ("type", wintypes.DWORD),
                ("union", INPUTUNION),
            ]

        self._KEYBDINPUT = KEYBDINPUT
        self._INPUT = INPUT

        # 不使用ctypes.windll.user32的共用函式物件。
        # PyAutoGUI、pydirectinput或其他套件可能重新設定同一個
        # SendInput函式物件的argtypes，導致Python 3.14嚴格檢查時，
        # 出現「expected LP_INPUT instance instead of pointer to INPUT」。
        #
        # 使用獨立WinDLL實例可避免不同套件的INPUT結構互相污染。
        self._user32 = ctypes.WinDLL(
            "user32",
            use_last_error=True,
        )

        self._send_input = self._user32.SendInput
        self._send_input.argtypes = (
            wintypes.UINT,
            ctypes.POINTER(self._INPUT),
            ctypes.c_int,
        )
        self._send_input.restype = wintypes.UINT

        self._map_virtual_key = self._user32.MapVirtualKeyW
        self._map_virtual_key.argtypes = (
            wintypes.UINT,
            wintypes.UINT,
        )
        self._map_virtual_key.restype = wintypes.UINT

    def resolve_key(self, payload: dict[str, Any]) -> VirtualKey:
        return VirtualKey(_payload_to_vk(payload))

    def key_down(self, key: VirtualKey) -> None:
        self._send(key.vk, key_up=False)

    def key_up(self, key: VirtualKey) -> None:
        self._send(key.vk, key_up=True)

    def _send(self, vk: int, key_up: bool) -> None:
        flags = 0
        if vk in self.EXTENDED_KEYS:
            flags |= self.KEYEVENTF_EXTENDEDKEY
        if key_up:
            flags |= self.KEYEVENTF_KEYUP

        scan = int(self._map_virtual_key(vk, self.MAPVK_VK_TO_VSC)) & 0xFF
        keyboard_input = self._KEYBDINPUT(
            wVk=vk,
            wScan=scan,
            dwFlags=flags,
            time=0,
            dwExtraInfo=0,
        )
        input_event = self._INPUT(
            type=self.INPUT_KEYBOARD,
            ki=keyboard_input,
        )

        # 建立與argtypes完全相同的INPUT陣列。
        # 傳入陣列時ctypes會自動轉成POINTER(self._INPUT)，
        # 避免Python 3.14對byref產生的臨時指標型別判定錯誤。
        input_array = (self._INPUT * 1)(input_event)

        ctypes.set_last_error(0)
        sent = int(
            self._send_input(
                1,
                input_array,
                ctypes.sizeof(self._INPUT),
            )
        )
        if sent != 1:
            error = ctypes.get_last_error()
            raise OSError(
                error,
                "SendInput失敗；請以系統管理員身分執行客戶端，"
                "並確認安全軟體未阻擋模擬輸入。",
            )


_PYAUTOGUI_VK_NAMES: dict[int, str] = {
    VK_BACK: "backspace",
    VK_TAB: "tab",
    VK_CLEAR: "clear",
    VK_RETURN: "enter",
    VK_SHIFT: "shift",
    VK_CONTROL: "ctrl",
    VK_MENU: "alt",
    VK_PAUSE: "pause",
    VK_CAPITAL: "capslock",
    VK_ESCAPE: "esc",
    VK_SPACE: "space",
    VK_PRIOR: "pgup",
    VK_NEXT: "pgdn",
    VK_END: "end",
    VK_HOME: "home",
    VK_LEFT: "left",
    VK_UP: "up",
    VK_RIGHT: "right",
    VK_DOWN: "down",
    VK_SELECT: "select",
    VK_PRINT: "print",
    VK_EXECUTE: "execute",
    VK_SNAPSHOT: "printscreen",
    VK_INSERT: "insert",
    VK_DELETE: "delete",
    VK_HELP: "help",
    VK_LWIN: "winleft",
    VK_RWIN: "winright",
    VK_APPS: "apps",
    VK_MULTIPLY: "multiply",
    VK_ADD: "add",
    VK_SEPARATOR: "separator",
    VK_SUBTRACT: "subtract",
    VK_DECIMAL: "decimal",
    VK_DIVIDE: "divide",
    VK_NUMLOCK: "numlock",
    VK_SCROLL: "scrolllock",
    VK_LSHIFT: "shiftleft",
    VK_RSHIFT: "shiftright",
    VK_LCONTROL: "ctrlleft",
    VK_RCONTROL: "ctrlright",
    VK_LMENU: "altleft",
    VK_RMENU: "altright",
    VK_VOLUME_MUTE: "volumemute",
    VK_VOLUME_DOWN: "volumedown",
    VK_VOLUME_UP: "volumeup",
    VK_MEDIA_NEXT_TRACK: "nexttrack",
    VK_MEDIA_PREV_TRACK: "prevtrack",
    VK_MEDIA_STOP: "stop",
    VK_MEDIA_PLAY_PAUSE: "playpause",
    0xBA: ";",
    0xBB: "=",
    0xBC: ",",
    0xBD: "-",
    0xBE: ".",
    0xBF: "/",
    0xC0: "`",
    0xDB: "[",
    0xDC: "\\",
    0xDD: "]",
    0xDE: "'",
}
for number in range(10):
    _PYAUTOGUI_VK_NAMES[0x30 + number] = str(number)
    _PYAUTOGUI_VK_NAMES[VK_NUMPAD0 + number] = f"num{number}"
for letter in range(26):
    _PYAUTOGUI_VK_NAMES[0x41 + letter] = chr(ord("a") + letter)
for number in range(1, 25):
    _PYAUTOGUI_VK_NAMES[VK_F1 + number - 1] = f"f{number}"


@dataclass(frozen=True)
class PyAutoGUIKey:
    name: str


class PyAutoGUIKeyboard:
    engine_id = ENGINE_PYAUTOGUI
    engine_name = "PyAutoGUI／Windows Virtual-Key"

    def __init__(self) -> None:
        _require_windows()
        import pyautogui

        pyautogui.PAUSE = 0
        pyautogui.FAILSAFE = False
        self._pyautogui = pyautogui

    def resolve_key(self, payload: dict[str, Any]) -> PyAutoGUIKey:
        vk = _payload_to_vk(payload)
        name = _PYAUTOGUI_VK_NAMES.get(vk)
        if name is None:
            char_value = payload.get("char")
            if isinstance(char_value, str) and char_value:
                name = char_value.lower()
        if not name:
            raise ValueError(f"PyAutoGUI沒有對應按鍵：VK {vk}")
        return PyAutoGUIKey(name)

    def key_down(self, key: PyAutoGUIKey) -> None:
        self._pyautogui.keyDown(key.name, _pause=False)

    def key_up(self, key: PyAutoGUIKey) -> None:
        self._pyautogui.keyUp(key.name, _pause=False)


class DirectInputKeyboardAdapter:
    engine_id = ENGINE_DIRECTINPUT
    engine_name = "pydirectinput-rgx／SendInput掃描碼"

    def __init__(self) -> None:
        _require_windows()
        from directinput_backend import DirectInputKeyboard

        self._backend = DirectInputKeyboard()

    def resolve_key(self, payload: dict[str, Any]) -> Any:
        from directinput_backend import payload_to_direct_key

        return payload_to_direct_key(payload)

    def key_down(self, key: Any) -> None:
        self._backend.key_down(key)

    def key_up(self, key: Any) -> None:
        self._backend.key_up(key)


def create_keyboard_backend(engine_id: str) -> KeyboardBackend:
    if engine_id == ENGINE_BETTERGI:
        return BetterGISendInputKeyboard()
    if engine_id == ENGINE_PYAUTOGUI:
        return PyAutoGUIKeyboard()
    if engine_id == ENGINE_DIRECTINPUT:
        return DirectInputKeyboardAdapter()
    raise ValueError(f"未知輸出引擎：{engine_id}")
