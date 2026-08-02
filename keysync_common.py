from __future__ import annotations

import base64
import hashlib
import hmac
import json
import socket
from typing import Any

from cryptography.fernet import Fernet
from pynput import keyboard

APP_ID = "LAN_KEY_SYNC_QT_V1"
DISCOVERY_REQUEST = b"LAN_KEY_SYNC_DISCOVER_QT_V1"
DEFAULT_DISCOVERY_PORT = 50100
DEFAULT_TCP_PORT = 50101
MAX_LINE_BYTES = 1024 * 1024


def make_fernet(secret: str) -> Fernet:
    """由共用密碼建立對稱加密金鑰。"""
    material = f"{APP_ID}:{secret}".encode("utf-8")
    digest = hashlib.sha256(material).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def make_auth_proof(secret: str, nonce: bytes) -> str:
    return hmac.new(secret.encode("utf-8"), nonce, hashlib.sha256).hexdigest()


def verify_auth_proof(secret: str, nonce: bytes, proof: str) -> bool:
    expected = make_auth_proof(secret, nonce)
    return hmac.compare_digest(expected, proof)


def send_json_line(sock: socket.socket, payload: dict[str, Any]) -> None:
    data = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    sock.sendall(data + b"\n")


def recv_line(sock: socket.socket, max_bytes: int = MAX_LINE_BYTES) -> bytes:
    data = bytearray()

    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("連線已中斷")

        if chunk == b"\n":
            return bytes(data)

        data.extend(chunk)

        if len(data) > max_bytes:
            raise ValueError("收到的資料超過允許大小")


def recv_json_line(sock: socket.socket) -> dict[str, Any]:
    raw = recv_line(sock)
    value = json.loads(raw.decode("utf-8"))

    if not isinstance(value, dict):
        raise ValueError("JSON資料格式錯誤")

    return value


def key_to_payload(
    key: keyboard.Key | keyboard.KeyCode,
) -> dict[str, Any] | None:
    """將按鍵轉成網路格式，Windows上優先傳送實體VK碼。"""
    if isinstance(key, keyboard.Key):
        key_value = getattr(key, "value", None)
        vk = getattr(key_value, "vk", None)

        if vk is not None:
            return {
                "kind": "vk",
                "value": int(vk),
                "name": key.name,
            }

        return {
            "kind": "special",
            "value": key.name,
        }

    if isinstance(key, keyboard.KeyCode):
        if key.vk is not None:
            payload: dict[str, Any] = {
                "kind": "vk",
                "value": int(key.vk),
            }

            if key.char is not None:
                payload["char"] = key.char

            return payload

        if key.char is not None:
            return {
                "kind": "char",
                "value": key.char,
            }

    return None


def payload_to_key(
    payload: dict[str, Any],
) -> keyboard.Key | keyboard.KeyCode | str:
    kind = payload.get("kind")
    value = payload.get("value")

    if kind == "special":
        if not isinstance(value, str):
            raise ValueError("特殊鍵資料錯誤")

        result = getattr(keyboard.Key, value, None)

        if result is None:
            raise ValueError(f"不支援的特殊鍵：{value}")

        return result

    if kind == "char":
        if not isinstance(value, str) or not value:
            raise ValueError("字元按鍵資料錯誤")

        return value

    if kind == "vk":
        return keyboard.KeyCode.from_vk(int(value))

    raise ValueError(f"未知按鍵類型：{kind}")


def key_token(payload: dict[str, Any]) -> str:
    """建立按鍵識別碼；忽略char/name等顯示用中繼資料。"""
    identity = {
        "kind": payload.get("kind"),
        "value": payload.get("value"),
    }
    return json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
