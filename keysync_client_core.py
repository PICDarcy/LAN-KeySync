from __future__ import annotations

import base64
import ctypes
import json
import socket
import threading
import time
from typing import Callable

from cryptography.fernet import InvalidToken

from keyboard_backends import (
    KeyboardBackend,
    create_keyboard_backend,
)
from keysync_common import (
    APP_ID,
    DEFAULT_TCP_PORT,
    DISCOVERY_REQUEST,
    key_token,
    make_auth_proof,
    make_fernet,
    recv_json_line,
    recv_line,
    send_json_line,
)


class KeyboardSyncClient:
    """區域網路鍵盤同步客戶端，支援多種Windows按鍵輸出引擎。"""

    def __init__(
        self,
        server_host: str,
        tcp_port: int,
        password: str,
        log_callback: Callable[[str], None],
        state_callback: Callable[[str], None],
        input_enabled_callback: Callable[[], bool],
        output_engine: str,
        auto_reconnect: bool = True,
    ) -> None:
        self.server_host = server_host
        self.tcp_port = tcp_port
        self.password = password
        self.log_callback = log_callback
        self.state_callback = state_callback
        self.input_enabled_callback = input_enabled_callback
        self.output_engine = output_engine
        self.auto_reconnect = auto_reconnect

        self.fernet = make_fernet(password)
        self.keyboard_output: KeyboardBackend = create_keyboard_backend(output_engine)

        self.sock: socket.socket | None = None
        self.sock_lock = threading.Lock()

        self.desired_connection = threading.Event()
        self.connected = threading.Event()

        self.held_keys: dict[str, object] = {}
        self.held_lock = threading.Lock()

        self.worker: threading.Thread | None = None

    def log(self, message: str) -> None:
        self.log_callback(message)

    def start(self) -> None:
        if self.desired_connection.is_set():
            return

        self.desired_connection.set()
        self.log(
            f"按鍵輸出引擎：{self.keyboard_output.engine_name}"
        )

        self.worker = threading.Thread(
            target=self._connection_loop,
            daemon=True,
            name="keysync-client-connection",
        )
        self.worker.start()

    def stop(self) -> None:
        self.desired_connection.clear()
        self.connected.clear()

        with self.sock_lock:
            sock_obj = self.sock
            self.sock = None

        if sock_obj is not None:
            try:
                sock_obj.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

            try:
                sock_obj.close()
            except OSError:
                pass

        self.release_all()
        self.state_callback("已中斷")

    def _connection_loop(self) -> None:
        while self.desired_connection.is_set():
            try:
                self.state_callback("連線中…")
                self._connect_once()
                self._receive_loop()

            except PermissionError as exc:
                self.log(f"驗證失敗：{exc}")
                self.state_callback("密碼錯誤")
                self.desired_connection.clear()
                break

            except (
                ConnectionError,
                OSError,
                ValueError,
                json.JSONDecodeError,
                InvalidToken,
            ) as exc:
                if self.desired_connection.is_set():
                    self.log(f"連線中斷：{exc}")
                    self.state_callback("連線中斷")

            finally:
                self.connected.clear()
                self.release_all()

                with self.sock_lock:
                    sock_obj = self.sock
                    self.sock = None

                if sock_obj is not None:
                    try:
                        sock_obj.close()
                    except OSError:
                        pass

            if (
                not self.desired_connection.is_set()
                or not self.auto_reconnect
            ):
                break

            self.state_callback("3秒後重新連線…")

            for _ in range(30):
                if not self.desired_connection.is_set():
                    break
                time.sleep(0.1)

        if not self.desired_connection.is_set():
            self.state_callback("已中斷")

    def _connect_once(self) -> None:
        sock_obj = socket.create_connection(
            (self.server_host, self.tcp_port),
            timeout=8.0,
        )
        sock_obj.settimeout(8.0)

        challenge = recv_json_line(sock_obj)

        if (
            challenge.get("type") != "challenge"
            or challenge.get("app") != APP_ID
        ):
            sock_obj.close()
            raise ConnectionError(
                "對方不是LAN鍵盤同步Qt主控端"
            )

        nonce = base64.b64decode(
            str(challenge.get("nonce", "")),
            validate=True,
        )

        send_json_line(
            sock_obj,
            {
                "type": "auth",
                "proof": make_auth_proof(
                    self.password,
                    nonce,
                ),
                "client_name": socket.gethostname(),
            },
        )

        auth_result = recv_json_line(sock_obj)

        if auth_result.get("type") == "auth_failed":
            sock_obj.close()
            raise PermissionError("共用密碼不正確")

        if auth_result.get("type") != "auth_ok":
            sock_obj.close()
            raise ConnectionError("主控端驗證回應異常")

        sock_obj.settimeout(None)

        with self.sock_lock:
            self.sock = sock_obj

        self.connected.set()

        server_name = str(
            auth_result.get(
                "server_name",
                self.server_host,
            )
        )

        self.state_callback(f"已連線：{server_name}")
        self.log(
            f"已連線到 {server_name}"
            f"（{self.server_host}:{self.tcp_port}）"
        )

    def _receive_loop(self) -> None:
        with self.sock_lock:
            sock_obj = self.sock

        if sock_obj is None:
            raise ConnectionError("通訊端不存在")

        while self.desired_connection.is_set():
            encrypted_line = recv_line(sock_obj)
            plain = self.fernet.decrypt(encrypted_line)
            event = json.loads(plain.decode("utf-8"))

            if not isinstance(event, dict):
                continue

            self._handle_event(event)

    def _handle_event(self, event: dict) -> None:
        event_type = event.get("type")

        if event_type == "release_all":
            self.release_all()
            return

        if (
            event_type != "key"
            or not self.input_enabled_callback()
        ):
            return

        action = event.get("action")
        payload = event.get("key")

        if not isinstance(payload, dict):
            return

        try:
            output_key = self.keyboard_output.resolve_key(payload)
            token = key_token(payload)

            if action == "press":
                self.keyboard_output.key_down(output_key)

                with self.held_lock:
                    self.held_keys[token] = output_key

            elif action == "release":
                with self.held_lock:
                    held_key = self.held_keys.pop(
                        token,
                        output_key,
                    )

                self.keyboard_output.key_up(held_key)

        except (ValueError, OSError, RuntimeError, ctypes.ArgumentError) as exc:
            self.log(f"按鍵執行失敗：{exc}")

    def release_all(self) -> None:
        with self.held_lock:
            keys = list(self.held_keys.values())
            self.held_keys.clear()

        released: set[object] = set()
        for output_key in reversed(keys):
            if output_key in released:
                continue

            released.add(output_key)

            try:
                self.keyboard_output.key_up(output_key)
            except (ValueError, OSError, RuntimeError, ctypes.ArgumentError):
                pass


def discover_servers(
    discovery_port: int,
    timeout: float = 2.0,
) -> list[dict[str, str | int]]:
    """利用UDP廣播搜尋同一區域網路內的主控端。"""
    found: dict[
        tuple[str, int],
        dict[str, str | int],
    ] = {}

    sock_obj = socket.socket(
        socket.AF_INET,
        socket.SOCK_DGRAM,
    )
    sock_obj.setsockopt(
        socket.SOL_SOCKET,
        socket.SO_BROADCAST,
        1,
    )
    sock_obj.settimeout(0.25)
    sock_obj.bind(("0.0.0.0", 0))

    try:
        sock_obj.sendto(
            DISCOVERY_REQUEST,
            ("255.255.255.255", discovery_port),
        )

        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                data, address = sock_obj.recvfrom(4096)
            except socket.timeout:
                continue

            try:
                payload = json.loads(
                    data.decode("utf-8")
                )
            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                continue

            if (
                not isinstance(payload, dict)
                or payload.get("app") != APP_ID
            ):
                continue

            tcp_port = int(
                payload.get(
                    "tcp_port",
                    DEFAULT_TCP_PORT,
                )
            )

            item: dict[str, str | int] = {
                "host": address[0],
                "tcp_port": tcp_port,
                "server_name": str(
                    payload.get(
                        "server_name",
                        address[0],
                    )
                ),
            }

            found[(address[0], tcp_port)] = item

    finally:
        sock_obj.close()

    return list(found.values())
