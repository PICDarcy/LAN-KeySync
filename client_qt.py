from __future__ import annotations

import sys
import ctypes
import threading
import time
from typing import Any

from PySide6.QtCore import QObject, QSettings, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from keysync_client_core import (
    KeyboardSyncClient,
    discover_servers,
)
from keysync_common import (
    DEFAULT_DISCOVERY_PORT,
    DEFAULT_TCP_PORT,
)
from keyboard_backends import (
    ENGINE_BETTERGI,
    ENGINE_LABELS,
    create_keyboard_backend,
    is_running_as_admin,
)
from qt_style import APP_STYLE


class ClientSignals(QObject):
    log = Signal(str)
    state = Signal(str)
    search_finished = Signal(object)
    search_failed = Signal(str)


class ClientWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("LAN鍵盤同步－Qt客戶端")
        self.resize(760, 560)
        self.setMinimumSize(680, 500)

        self.settings = QSettings(
            "PICDarcy",
            "LANKeyboardSyncQtClient",
        )

        self.client: KeyboardSyncClient | None = None
        self.signals = ClientSignals()

        self.signals.log.connect(self.append_log)
        self.signals.state.connect(
            self.update_connection_state
        )
        self.signals.search_finished.connect(
            self.on_search_finished
        )
        self.signals.search_failed.connect(
            self.on_search_failed
        )

        self._build_ui()
        self._load_settings()
        self.update_connection_state("尚未連線")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        outer = QVBoxLayout(central)
        outer.setContentsMargins(20, 18, 20, 18)
        outer.setSpacing(12)

        title = QLabel("LAN鍵盤同步")
        title.setObjectName("titleLabel")
        outer.addWidget(title)

        subtitle = QLabel(
            "客戶端可切換BetterGI相容SendInput、PyAutoGUI或DirectInput掃描碼，"
            "並執行主控端傳來的按鍵事件。"
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        settings_group = QGroupBox("主控端設定")
        settings_layout = QGridLayout(
            settings_group
        )
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(10)

        host_label = QLabel("主控端IP")
        self.host_edit = QLineEdit()
        self.host_edit.setPlaceholderText(
            "例如：192.168.1.100"
        )

        self.search_button = QPushButton(
            "自動搜尋"
        )
        self.search_button.clicked.connect(
            self.search_server
        )

        tcp_label = QLabel("TCP連接埠")
        self.tcp_spin = QSpinBox()
        self.tcp_spin.setRange(1, 65535)
        self.tcp_spin.setValue(DEFAULT_TCP_PORT)

        password_label = QLabel("共用密碼")
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(
            QLineEdit.EchoMode.Password
        )
        self.password_edit.setPlaceholderText(
            "必須與主控端相同"
        )

        discovery_label = QLabel("UDP搜尋埠")
        self.discovery_spin = QSpinBox()
        self.discovery_spin.setRange(1, 65535)
        self.discovery_spin.setValue(
            DEFAULT_DISCOVERY_PORT
        )

        settings_layout.addWidget(
            host_label,
            0,
            0,
        )
        settings_layout.addWidget(
            self.host_edit,
            0,
            1,
            1,
            2,
        )
        settings_layout.addWidget(
            self.search_button,
            0,
            3,
        )
        settings_layout.addWidget(
            tcp_label,
            0,
            4,
        )
        settings_layout.addWidget(
            self.tcp_spin,
            0,
            5,
        )

        settings_layout.addWidget(
            password_label,
            1,
            0,
        )
        settings_layout.addWidget(
            self.password_edit,
            1,
            1,
            1,
            3,
        )
        settings_layout.addWidget(
            discovery_label,
            1,
            4,
        )
        settings_layout.addWidget(
            self.discovery_spin,
            1,
            5,
        )

        settings_layout.setColumnStretch(1, 1)
        settings_layout.setColumnStretch(2, 1)
        settings_layout.setColumnStretch(3, 1)

        outer.addWidget(settings_group)

        options_group = QGroupBox("客戶端選項")
        options_layout = QGridLayout(options_group)

        engine_label = QLabel("按鍵輸出引擎")
        self.engine_combo = QComboBox()
        for engine_id, label in ENGINE_LABELS.items():
            self.engine_combo.addItem(label, engine_id)
        self.engine_combo.currentIndexChanged.connect(self.on_engine_changed)

        self.input_checkbox = QCheckBox(
            "允許主控端輸入"
        )
        self.input_checkbox.setChecked(True)
        self.input_checkbox.toggled.connect(
            self.on_input_enabled_changed
        )

        self.reconnect_checkbox = QCheckBox(
            "斷線後自動重新連線"
        )
        self.reconnect_checkbox.setChecked(True)

        self.admin_label = QLabel()
        self._update_admin_label()

        options_layout.addWidget(engine_label, 0, 0)
        options_layout.addWidget(self.engine_combo, 0, 1, 1, 3)
        options_layout.addWidget(self.input_checkbox, 1, 0)
        options_layout.addWidget(self.reconnect_checkbox, 1, 1)
        options_layout.addWidget(self.admin_label, 1, 2, 1, 2)
        options_layout.setColumnStretch(3, 1)

        outer.addWidget(options_group)

        controls = QHBoxLayout()

        self.connect_button = QPushButton("連線")
        self.connect_button.setObjectName(
            "primaryButton"
        )
        self.connect_button.clicked.connect(
            self.connect_client
        )

        self.disconnect_button = QPushButton(
            "中斷"
        )
        self.disconnect_button.setObjectName(
            "dangerButton"
        )
        self.disconnect_button.clicked.connect(
            self.disconnect_client
        )

        self.release_button = QPushButton(
            "緊急釋放所有按鍵"
        )
        self.release_button.setObjectName(
            "warningButton"
        )
        self.release_button.clicked.connect(
            self.release_all
        )

        self.test_button = QPushButton("3秒後測試F鍵")
        self.test_button.clicked.connect(self.test_output_engine)

        self.status_label = QLabel("尚未連線")
        self.status_label.setAlignment(
            Qt.AlignmentFlag.AlignCenter
        )

        controls.addWidget(self.connect_button)
        controls.addWidget(
            self.disconnect_button
        )
        controls.addWidget(self.release_button)
        controls.addWidget(self.test_button)
        controls.addStretch(1)
        controls.addWidget(self.status_label)

        outer.addLayout(controls)

        self.engine_hint = QLabel()
        self.engine_hint.setObjectName("subtitleLabel")
        self.engine_hint.setWordWrap(True)
        self.on_engine_changed()
        warning = self.engine_hint
        warning.setObjectName("subtitleLabel")
        warning.setWordWrap(True)
        outer.addWidget(warning)

        log_group = QGroupBox("執行紀錄")
        log_layout = QVBoxLayout(log_group)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
        )

        log_layout.addWidget(self.log_edit)
        outer.addWidget(log_group, 1)

    def _load_settings(self) -> None:
        self.host_edit.setText(
            str(
                self.settings.value(
                    "host",
                    "",
                )
            )
        )
        self.tcp_spin.setValue(
            int(
                self.settings.value(
                    "tcp_port",
                    DEFAULT_TCP_PORT,
                )
            )
        )
        self.discovery_spin.setValue(
            int(
                self.settings.value(
                    "discovery_port",
                    DEFAULT_DISCOVERY_PORT,
                )
            )
        )
        self.input_checkbox.setChecked(
            str(
                self.settings.value(
                    "input_enabled",
                    "true",
                )
            ).lower() == "true"
        )
        self.reconnect_checkbox.setChecked(
            str(
                self.settings.value(
                    "auto_reconnect",
                    "true",
                )
            ).lower() == "true"
        )
        saved_engine = str(
            self.settings.value(
                "output_engine",
                ENGINE_BETTERGI,
            )
        )
        engine_index = self.engine_combo.findData(saved_engine)
        if engine_index < 0:
            engine_index = self.engine_combo.findData(ENGINE_BETTERGI)
        self.engine_combo.setCurrentIndex(engine_index)
        self.on_engine_changed()

    def _save_settings(self) -> None:
        self.settings.setValue(
            "host",
            self.host_edit.text().strip(),
        )
        self.settings.setValue(
            "tcp_port",
            self.tcp_spin.value(),
        )
        self.settings.setValue(
            "discovery_port",
            self.discovery_spin.value(),
        )
        self.settings.setValue(
            "input_enabled",
            self.input_checkbox.isChecked(),
        )
        self.settings.setValue(
            "auto_reconnect",
            self.reconnect_checkbox.isChecked(),
        )
        self.settings.setValue(
            "output_engine",
            self.engine_combo.currentData(),
        )

    @Slot()
    def search_server(self) -> None:
        self.search_button.setEnabled(False)
        self.update_connection_state(
            "正在搜尋主控端…"
        )

        discovery_port = self.discovery_spin.value()

        def worker() -> None:
            try:
                servers = discover_servers(
                    discovery_port=discovery_port,
                    timeout=2.5,
                )
                self.signals.search_finished.emit(
                    servers
                )
            except OSError as exc:
                self.signals.search_failed.emit(
                    str(exc)
                )

        threading.Thread(
            target=worker,
            daemon=True,
            name="keysync-search",
        ).start()

    @Slot(object)
    def on_search_finished(
        self,
        servers: Any,
    ) -> None:
        self.search_button.setEnabled(True)
        server_list = list(servers)

        if not server_list:
            self.update_connection_state(
                "搜尋不到主控端"
            )
            QMessageBox.information(
                self,
                "搜尋結果",
                "找不到主控端。\n\n"
                "請確認：\n"
                "1. 主控端已啟動。\n"
                "2. 兩台電腦位於同一區域網路。\n"
                "3. Windows防火牆已允許私人網路。\n\n"
                "也可以直接手動輸入主控端IP。",
            )
            return

        choices = [
            (
                f'{item["server_name"]} — '
                f'{item["host"]}:{item["tcp_port"]}'
            )
            for item in server_list
        ]

        selected_index = 0

        if len(choices) > 1:
            selected, accepted = (
                QInputDialog.getItem(
                    self,
                    "選擇主控端",
                    "搜尋到多個主控端：",
                    choices,
                    0,
                    False,
                )
            )

            if not accepted:
                self.update_connection_state(
                    "搜尋完成"
                )
                return

            selected_index = choices.index(
                selected
            )

        server = server_list[selected_index]

        self.host_edit.setText(
            str(server["host"])
        )
        self.tcp_spin.setValue(
            int(server["tcp_port"])
        )

        self.append_log(
            "已找到主控端："
            f'{server["server_name"]} '
            f'（{server["host"]}:'
            f'{server["tcp_port"]}）'
        )
        self.update_connection_state(
            "已找到主控端"
        )

    @Slot(str)
    def on_search_failed(
        self,
        error: str,
    ) -> None:
        self.search_button.setEnabled(True)
        self.update_connection_state(
            "搜尋失敗"
        )
        QMessageBox.critical(
            self,
            "搜尋失敗",
            f"搜尋主控端時發生錯誤：\n{error}",
        )

    @Slot()
    def connect_client(self) -> None:
        host = self.host_edit.text().strip()
        password = self.password_edit.text()

        if not host:
            QMessageBox.warning(
                self,
                "設定錯誤",
                "請輸入主控端IP，或按「自動搜尋」。",
            )
            return

        if len(password) < 8:
            QMessageBox.warning(
                self,
                "設定錯誤",
                "共用密碼至少需要8個字元。",
            )
            return

        self.client = KeyboardSyncClient(
            server_host=host,
            tcp_port=self.tcp_spin.value(),
            password=password,
            log_callback=self.signals.log.emit,
            state_callback=self.signals.state.emit,
            input_enabled_callback=(
                self.input_checkbox.isChecked
            ),
            output_engine=str(self.engine_combo.currentData()),
            auto_reconnect=(
                self.reconnect_checkbox.isChecked()
            ),
        )
        self.client.start()
        self._save_settings()
        self._set_connection_controls(True)

    @Slot()
    def disconnect_client(self) -> None:
        if self.client is not None:
            self.client.stop()
            self.client = None

        self._set_connection_controls(False)
        self.update_connection_state(
            "已中斷"
        )

    @Slot()
    def release_all(self) -> None:
        if self.client is not None:
            self.client.release_all()

        self.append_log(
            "已執行緊急釋放所有按鍵"
        )

    @Slot(bool)
    def on_input_enabled_changed(
        self,
        enabled: bool,
    ) -> None:
        if (
            not enabled
            and self.client is not None
        ):
            self.client.release_all()
            self.append_log(
                "已停用主控端輸入並釋放所有按鍵"
            )

    @Slot(str)
    def append_log(
        self,
        message: str,
    ) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_edit.append(
            f"[{timestamp}] {message}"
        )

    @Slot(str)
    def update_connection_state(
        self,
        state: str,
    ) -> None:
        self.status_label.setText(state)

        if state.startswith("已連線"):
            object_name = "statusRunning"
        elif (
            "搜尋" in state
            or "重新連線" in state
            or "連線中" in state
        ):
            object_name = "statusWarning"
        else:
            object_name = "statusStopped"

        self.status_label.setObjectName(
            object_name
        )
        self.status_label.style().unpolish(
            self.status_label
        )
        self.status_label.style().polish(
            self.status_label
        )

        active = (
            self.client is not None
            and self.client.desired_connection.is_set()
        )
        self._set_connection_controls(active)

    def _set_connection_controls(
        self,
        active: bool,
    ) -> None:
        self.connect_button.setEnabled(
            not active
        )
        self.disconnect_button.setEnabled(
            active
        )

        self.host_edit.setEnabled(not active)
        self.password_edit.setEnabled(
            not active
        )
        self.tcp_spin.setEnabled(not active)
        self.discovery_spin.setEnabled(
            not active
        )
        self.search_button.setEnabled(
            not active
        )
        self.reconnect_checkbox.setEnabled(
            not active
        )
        self.engine_combo.setEnabled(not active)


    @Slot()
    def on_engine_changed(self) -> None:
        engine_id = str(self.engine_combo.currentData())
        hints = {
            "bettergi_sendinput": (
                "建議優先使用：模仿BetterGI的Fischless.WindowsInput，使用Win32 SendInput，"
                "保留Virtual-Key且不設定SCANCODE旗標。"
            ),
            "pyautogui": (
                "使用PyAutoGUI公開的keyDown/keyUp輸出；適合你已確認PyAutoGUI可控制的遊戲。"
            ),
            "directinput_scancode": (
                "舊版pydirectinput-rgx掃描碼模式；部分DirectX遊戲可用，但你的遊戲目前未接收。"
            ),
        }
        self.engine_hint.setText(
            hints.get(engine_id, "選擇客戶端的按鍵輸出方式。")
            + " 停用輸入時會立即釋放Ctrl、Alt、Shift等按鍵。"
        )

    def _update_admin_label(self) -> None:
        if is_running_as_admin():
            self.admin_label.setText("權限：系統管理員")
            self.admin_label.setObjectName("statusRunning")
        else:
            self.admin_label.setText("權限：一般（遊戲若為管理員將無法控制）")
            self.admin_label.setObjectName("statusWarning")
        self.admin_label.style().unpolish(self.admin_label)
        self.admin_label.style().polish(self.admin_label)

    @Slot()
    def test_output_engine(self) -> None:
        engine_id = str(self.engine_combo.currentData())
        self.test_button.setEnabled(False)
        self.append_log("3秒後輸出F鍵；請立即切換到遊戲視窗。")

        def worker() -> None:
            try:
                time.sleep(3.0)
                backend = create_keyboard_backend(engine_id)
                test_key = backend.resolve_key(
                    {"kind": "vk", "value": 0x46, "char": "f"}
                )
                backend.key_down(test_key)
                time.sleep(0.08)
                backend.key_up(test_key)
                self.signals.log.emit(
                    f"測試完成：{backend.engine_name}已輸出F鍵"
                )
            except (ValueError, OSError, RuntimeError, ImportError, ctypes.ArgumentError) as exc:
                self.signals.log.emit(f"輸出引擎測試失敗：{exc}")
            finally:
                self.signals.state.emit(self.status_label.text())

        threading.Thread(
            target=worker,
            daemon=True,
            name="keysync-output-test",
        ).start()
        # 避免跨執行緒直接操作Qt元件；4秒後由GUI執行緒恢復按鈕。
        from PySide6.QtCore import QTimer
        QTimer.singleShot(4000, lambda: self.test_button.setEnabled(True))

    def closeEvent(
        self,
        event: QCloseEvent,
    ) -> None:
        self.disconnect_client()
        self._save_settings()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(
        "LAN鍵盤同步Qt客戶端"
    )
    app.setStyleSheet(APP_STYLE)

    window = ClientWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
