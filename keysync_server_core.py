from __future__ import annotations

import base64
import json
import os
import queue
import socket
import threading
from dataclasses import dataclass
from typing import Any, Callable

from keyboard_capture_backends import (
    KeyboardCaptureBackend,
    create_keyboard_capture,
    describe_payload,
)
from keysync_common import (
    APP_ID,
    DISCOVERY_REQUEST,
    key_token,
    make_fernet,
    recv_json_line,
    send_json_line,
    verify_auth_proof,
)


@dataclass
class ConnectedClient:
    sock: socket.socket
    address: tuple[str, int]
    name: str
    send_lock: threading.Lock


class KeyboardSyncServer:
    """區域網路鍵盤同步主控核心，支援可切換的遊戲鍵盤偵測引擎。"""

    PAUSE_VK = 0x13

    def __init__(
        self,
        password: str,
        tcp_port: int,
        discovery_port: int,
        capture_engine: str,
        log_callback: Callable[[str], None],
        running_callback: Callable[[bool], None],
        clients_callback: Callable[[list[dict[str, str]]], None],
        sync_callback: Callable[[bool], None],
        input_event_callback: Callable[[str], None],
    ) -> None:
        self.password = password
        self.tcp_port = tcp_port
        self.discovery_port = discovery_port
        self.capture_engine = capture_engine

        self.log_callback = log_callback
        self.running_callback = running_callback
        self.clients_callback = clients_callback
        self.sync_callback = sync_callback
        self.input_event_callback = input_event_callback

        self.fernet = make_fernet(password)

        self.running = threading.Event()
        self.broadcast_enabled = threading.Event()
        self.broadcast_enabled.set()

        self.tcp_socket: socket.socket | None = None
        self.udp_socket: socket.socket | None = None
        self.input_capture: KeyboardCaptureBackend | None = None
        self.input_worker: threading.Thread | None = None
        self.input_queue: queue.Queue[
            tuple[str, dict[str, Any]] | None
        ] = queue.Queue(maxsize=4096)

        self._pressed_tokens: set[str] = set()
        self._pause_held = False

        self.clients: list[ConnectedClient] = []
        self.clients_lock = threading.Lock()

    def log(self, message: str) -> None:
        self.log_callback(message)

    def start(self) -> None:
        if self.running.is_set():
            return

        tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tcp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tcp_socket.bind(("0.0.0.0", self.tcp_port))
        tcp_socket.listen(32)
        tcp_socket.settimeout(1.0)

        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        udp_socket.bind(("0.0.0.0", self.discovery_port))
        udp_socket.settimeout(1.0)

        self.tcp_socket = tcp_socket
        self.udp_socket = udp_socket
        self.running.set()

        try:
            self.input_worker = threading.Thread(
                target=self._input_worker_loop,
                daemon=True,
                name="keysync-input-worker",
            )
            self.input_worker.start()

            self.input_capture = create_keyboard_capture(
                self.capture_engine,
                self._enqueue_input_event,
                self.log,
            )
            self.input_capture.start()

            threading.Thread(
                target=self._accept_loop,
                daemon=True,
                name="keysync-accept",
            ).start()

            threading.Thread(
                target=self._discovery_loop,
                daemon=True,
                name="keysync-discovery",
            ).start()

        except BaseException:
            self._cleanup_after_failed_start()
            raise

        self.log(
            f"主控端已啟動：TCP {self.tcp_port}／UDP搜尋 {self.discovery_port}"
        )
        self.log("按Pause鍵可暫停或恢復同步；Pause鍵本身不會傳送。")
        self.running_callback(True)
        self.sync_callback(self.broadcast_enabled.is_set())

    def _cleanup_after_failed_start(self) -> None:
        capture = self.input_capture
        self.input_capture = None
        if capture is not None:
            try:
                capture.stop()
            except BaseException:
                pass

        self.running.clear()
        try:
            self.input_queue.put_nowait(None)
        except queue.Full:
            pass

        for sock_obj in (self.tcp_socket, self.udp_socket):
            if sock_obj is not None:
                try:
                    sock_obj.close()
                except OSError:
                    pass
        self.tcp_socket = None
        self.udp_socket = None

    def stop(self) -> None:
        if not self.running.is_set():
            return

        self.set_broadcast_enabled(False)

        capture = self.input_capture
        self.input_capture = None
        if capture is not None:
            try:
                capture.stop()
            except BaseException as exc:
                self.log(f"停止鍵盤偵測時發生錯誤：{exc}")

        self.running.clear()
        try:
            self.input_queue.put_nowait(None)
        except queue.Full:
            pass

        worker = self.input_worker
        if worker is not None and worker is not threading.current_thread():
            worker.join(timeout=2.0)
        self.input_worker = None

        for sock_obj in (self.tcp_socket, self.udp_socket):
            if sock_obj is not None:
                try:
                    sock_obj.close()
                except OSError:
                    pass

        self.tcp_socket = None
        self.udp_socket = None

        with self.clients_lock:
            clients = list(self.clients)
            self.clients.clear()

        for client in clients:
            try:
                client.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.sock.close()
            except OSError:
                pass

        self._pressed_tokens.clear()
        self._pause_held = False
        self._notify_clients_changed()
        self.log("主控端已停止")
        self.running_callback(False)
        self.sync_callback(False)

    def set_broadcast_enabled(self, enabled: bool) -> None:
        if enabled:
            self.broadcast_enabled.set()
            self.log("鍵盤同步已開啟")
        else:
            if self.broadcast_enabled.is_set():
                self._broadcast({"type": "release_all"})
            self.broadcast_enabled.clear()
            self._pressed_tokens.clear()
            self.log("鍵盤同步已暫停")

        self.sync_callback(self.broadcast_enabled.is_set())

    def _enqueue_input_event(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        if not self.running.is_set():
            return
        try:
            self.input_queue.put_nowait((action, payload))
        except queue.Full:
            self.log("鍵盤事件佇列已滿，已略過一筆事件。")

    def _input_worker_loop(self) -> None:
        while self.running.is_set() or not self.input_queue.empty():
            try:
                item = self.input_queue.get(timeout=0.25)
            except queue.Empty:
                continue

            if item is None:
                break

            action, payload = item
            try:
                self._handle_input_event(action, payload)
            except BaseException as exc:
                self.log(f"處理鍵盤事件失敗：{exc}")

    def _handle_input_event(
        self,
        action: str,
        payload: dict[str, Any],
    ) -> None:
        key_name = describe_payload(payload)
        self.input_event_callback(
            f"{key_name} {'按下' if action == 'press' else '放開'}"
        )

        is_pause = (
            payload.get("kind") == "vk"
            and int(payload.get("value", -1)) == self.PAUSE_VK
        ) or (
            payload.get("kind") == "special"
            and payload.get("value") == "pause"
        )

        if is_pause:
            if action == "press" and not self._pause_held:
                self._pause_held = True
                self.set_broadcast_enabled(
                    not self.broadcast_enabled.is_set()
                )
            elif action == "release":
                self._pause_held = False
            return

        if not self.broadcast_enabled.is_set():
            return

        token = key_token(payload)
        if action == "press":
            # 避免低階鉤子的系統自動重複事件造成多次keyDown。
            if token in self._pressed_tokens:
                return
            self._pressed_tokens.add(token)
        elif action == "release":
            self._pressed_tokens.discard(token)
        else:
            return

        self._broadcast(
            {
                "type": "key",
                "action": action,
                "key": payload,
            }
        )

    def _accept_loop(self) -> None:
        while self.running.is_set():
            tcp_socket = self.tcp_socket
            if tcp_socket is None:
                break
            try:
                client_sock, address = tcp_socket.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            client_sock.settimeout(8.0)
            threading.Thread(
                target=self._authenticate_client,
                args=(client_sock, address),
                daemon=True,
                name=f"keysync-client-{address[0]}",
            ).start()

    def _authenticate_client(
        self,
        client_sock: socket.socket,
        address: tuple[str, int],
    ) -> None:
        try:
            nonce = os.urandom(32)
            send_json_line(
                client_sock,
                {
                    "type": "challenge",
                    "app": APP_ID,
                    "nonce": base64.b64encode(nonce).decode("ascii"),
                },
            )

            reply = recv_json_line(client_sock)
            if reply.get("type") != "auth":
                raise PermissionError("驗證格式不正確")

            proof = str(reply.get("proof", ""))
            if not verify_auth_proof(self.password, nonce, proof):
                send_json_line(client_sock, {"type": "auth_failed"})
                raise PermissionError("共用密碼錯誤")

            client_name = str(reply.get("client_name", address[0]))[:80]
            send_json_line(
                client_sock,
                {
                    "type": "auth_ok",
                    "server_name": socket.gethostname(),
                },
            )
            client_sock.settimeout(None)

            client = ConnectedClient(
                sock=client_sock,
                address=address,
                name=client_name,
                send_lock=threading.Lock(),
            )
            with self.clients_lock:
                self.clients.append(client)

            self.log(f"客戶端已連線：{client_name}（{address[0]}）")
            self._notify_clients_changed()

            while self.running.is_set():
                data = client_sock.recv(1)
                if not data:
                    break

        except PermissionError as exc:
            self.log(f"拒絕連線 {address[0]}：{exc}")
        except (
            ConnectionError,
            OSError,
            ValueError,
            json.JSONDecodeError,
        ) as exc:
            self.log(f"客戶端 {address[0]} 連線失敗：{exc}")
        finally:
            self._remove_client_socket(client_sock)

    def _remove_client_socket(self, target: socket.socket) -> None:
        removed: ConnectedClient | None = None
        with self.clients_lock:
            for client in list(self.clients):
                if client.sock is target:
                    self.clients.remove(client)
                    removed = client
                    break

        try:
            target.close()
        except OSError:
            pass

        if removed is not None:
            self.log(f"客戶端已離線：{removed.name}（{removed.address[0]}）")
            self._notify_clients_changed()

    def _notify_clients_changed(self) -> None:
        with self.clients_lock:
            rows = [
                {"name": client.name, "ip": client.address[0]}
                for client in self.clients
            ]
        self.clients_callback(rows)

    def _discovery_loop(self) -> None:
        while self.running.is_set():
            udp_socket = self.udp_socket
            if udp_socket is None:
                break
            try:
                data, address = udp_socket.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break

            if data != DISCOVERY_REQUEST:
                continue

            response = {
                "app": APP_ID,
                "server_name": socket.gethostname(),
                "tcp_port": self.tcp_port,
            }
            try:
                udp_socket.sendto(
                    json.dumps(response, ensure_ascii=False).encode("utf-8"),
                    address,
                )
            except OSError:
                pass

    def _broadcast(self, event: dict[str, Any]) -> None:
        if not self.running.is_set():
            return

        encrypted = self.fernet.encrypt(
            json.dumps(
                event,
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        ) + b"\n"

        with self.clients_lock:
            clients = list(self.clients)

        dead_sockets: list[socket.socket] = []
        for client in clients:
            try:
                with client.send_lock:
                    client.sock.sendall(encrypted)
            except OSError:
                dead_sockets.append(client.sock)

        for sock_obj in dead_sockets:
            self._remove_client_socket(sock_obj)
