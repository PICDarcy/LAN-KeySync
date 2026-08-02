from __future__ import annotations

import ctypes
import sys
from dataclasses import dataclass
from typing import Any, Literal

if sys.platform != "win32":
    raise RuntimeError("DirectInput按鍵輸出只支援Windows。")

import pydirectinput

# 網路同步需要低延遲，也不能因滑鼠位於螢幕角落而中止鍵盤輸出。
pydirectinput.PAUSE = None
pydirectinput.FAILSAFE = False

_MAPVK_VK_TO_VSC_EX = 4


@dataclass(frozen=True)
class DirectKey:
    mode: Literal["scancode", "name", "unicode"]
    value: int | str


_SPECIAL_NAME_MAP: dict[str, str] = {
    "alt": "alt",
    "alt_l": "altleft",
    "alt_r": "altright",
    "backspace": "backspace",
    "caps_lock": "capslock",
    "cmd": "win",
    "cmd_l": "winleft",
    "cmd_r": "winright",
    "ctrl": "ctrl",
    "ctrl_l": "ctrlleft",
    "ctrl_r": "ctrlright",
    "delete": "delete",
    "down": "down",
    "end": "end",
    "enter": "enter",
    "esc": "esc",
    "home": "home",
    "insert": "insert",
    "left": "left",
    "media_next": "nexttrack",
    "media_play_pause": "playpause",
    "media_previous": "prevtrack",
    "media_volume_down": "volumedown",
    "media_volume_mute": "volumemute",
    "media_volume_up": "volumeup",
    "menu": "apps",
    "num_lock": "numlock",
    "page_down": "pagedown",
    "page_up": "pageup",
    "pause": "pause",
    "print_screen": "printscreen",
    "right": "right",
    "scroll_lock": "scrolllock",
    "shift": "shift",
    "shift_l": "shiftleft",
    "shift_r": "shiftright",
    "space": "space",
    "tab": "tab",
    "up": "up",
}

for number in range(1, 25):
    _SPECIAL_NAME_MAP[f"f{number}"] = f"f{number}"


def _vk_to_scancode(vk: int) -> int:
    """把Windows Virtual-Key轉成包含E0/E1資訊的掃描碼。"""
    scancode = int(
        ctypes.windll.user32.MapVirtualKeyW(
            int(vk),
            _MAPVK_VK_TO_VSC_EX,
        )
    )

    if scancode == 0:
        raise ValueError(f"VK {vk}無法轉換成掃描碼")

    return scancode


def _normalise_character(value: str) -> str:
    if value == " ":
        return "space"
    if value == "\r" or value == "\n":
        return "enter"
    if value == "\t":
        return "tab"
    return value


def payload_to_direct_key(payload: dict[str, Any]) -> DirectKey:
    kind = payload.get("kind")
    value = payload.get("value")

    if kind == "vk":
        return DirectKey(
            mode="scancode",
            value=_vk_to_scancode(int(value)),
        )

    if kind == "special":
        if not isinstance(value, str):
            raise ValueError("特殊鍵資料錯誤")

        direct_name = _SPECIAL_NAME_MAP.get(value)
        if direct_name is None:
            raise ValueError(f"DirectInput不支援特殊鍵：{value}")

        return DirectKey(mode="name", value=direct_name)

    if kind == "char":
        if not isinstance(value, str) or not value:
            raise ValueError("字元按鍵資料錯誤")

        direct_name = _normalise_character(value)
        if pydirectinput.is_valid_key(direct_name):
            return DirectKey(mode="name", value=direct_name)

        # Unicode輸入不是所有遊戲都接受，但可作為一般桌面程式的後備方案。
        return DirectKey(mode="unicode", value=value[0])

    raise ValueError(f"未知按鍵類型：{kind}")


class DirectInputKeyboard:
    """使用pydirectinput-rgx的SendInput掃描碼後端。"""

    engine_name = "pydirectinput-rgx／SendInput掃描碼"

    @staticmethod
    def key_down(key: DirectKey) -> None:
        if key.mode == "scancode":
            success = pydirectinput.scancode_keyDown(
                int(key.value),
                _pause=False,
            )
        elif key.mode == "name":
            success = pydirectinput.keyDown(
                str(key.value),
                _pause=False,
                auto_shift=False,
            )
        else:
            success = pydirectinput.unicode_charDown(
                str(key.value),
                _pause=False,
            )

        if success is False:
            raise OSError(f"按鍵按下失敗：{key}")

    @staticmethod
    def key_up(key: DirectKey) -> None:
        if key.mode == "scancode":
            success = pydirectinput.scancode_keyUp(
                int(key.value),
                _pause=False,
            )
        elif key.mode == "name":
            success = pydirectinput.keyUp(
                str(key.value),
                _pause=False,
                auto_shift=False,
            )
        else:
            success = pydirectinput.unicode_charUp(
                str(key.value),
                _pause=False,
            )

        if success is False:
            raise OSError(f"按鍵放開失敗：{key}")
