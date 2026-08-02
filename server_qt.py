from __future__ import annotations

import sys
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
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from keyboard_capture_backends import (
    CAPTURE_BETTERGI_HOOK,
    CAPTURE_LABELS,
    is_running_as_admin,
)
from keysync_common import DEFAULT_DISCOVERY_PORT, DEFAULT_TCP_PORT
from keysync_server_core import KeyboardSyncServer
from qt_style import APP_STYLE


class ServerSignals(QObject):
    log = Signal(str)
    running = Signal(bool)
    clients = Signal(object)
    sync = Signal(bool)
    input_event = Signal(str)


class ServerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()

        self.setWindowTitle("LAN鍵盤同步－Qt主控端／遊戲輸入版")
        self.resize(860, 700)
        self.setMinimumSize(740, 610)

        self.settings = QSettings("PICDarcy", "LANKeyboardSyncQtServer")
        self.server: KeyboardSyncServer | None = None
        self.input_event_count = 0

        self.signals = ServerSignals()
        self.signals.log.connect(self.append_log)
        self.signals.running.connect(self.update_running_state)
        self.signals.clients.connect(self.update_clients)
        self.signals.sync.connect(self.update_sync_state)
        self.signals.input_event.connect(self.update_input_event)

        self._build_ui()
        self._load_settings()
        self.update_running_state(False)

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
            "主控端使用Windows原生遊戲鍵盤偵測，將按下與放開事件同步到所有客戶端。"
        )
        subtitle.setObjectName("subtitleLabel")
        subtitle.setWordWrap(True)
        outer.addWidget(subtitle)

        settings_group = QGroupBox("連線與輸入設定")
        settings_layout = QGridLayout(settings_group)
        settings_layout.setHorizontalSpacing(12)
        settings_layout.setVerticalSpacing(10)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("至少8個字元，兩端必須相同")

        self.tcp_spin = QSpinBox()
        self.tcp_spin.setRange(1, 65535)
        self.tcp_spin.setValue(DEFAULT_TCP_PORT)

        self.discovery_spin = QSpinBox()
        self.discovery_spin.setRange(1, 65535)
        self.discovery_spin.setValue(DEFAULT_DISCOVERY_PORT)

        self.capture_combo = QComboBox()
        for engine_id, label in CAPTURE_LABELS.items():
            self.capture_combo.addItem(label, engine_id)
        self.capture_combo.currentIndexChanged.connect(self.update_capture_hint)

        self.admin_label = QLabel()
        self.admin_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_admin_label()

        settings_layout.addWidget(QLabel("共用密碼"), 0, 0)
        settings_layout.addWidget(self.password_edit, 0, 1, 1, 3)
        settings_layout.addWidget(QLabel("TCP連接埠"), 1, 0)
        settings_layout.addWidget(self.tcp_spin, 1, 1)
        settings_layout.addWidget(QLabel("UDP搜尋埠"), 1, 2)
        settings_layout.addWidget(self.discovery_spin, 1, 3)
        settings_layout.addWidget(QLabel("鍵盤偵測引擎"), 2, 0)
        settings_layout.addWidget(self.capture_combo, 2, 1, 1, 2)
        settings_layout.addWidget(self.admin_label, 2, 3)
        settings_layout.setColumnStretch(1, 1)
        settings_layout.setColumnStretch(2, 1)
        settings_layout.setColumnStretch(3, 1)
        outer.addWidget(settings_group)

        self.capture_hint = QLabel()
        self.capture_hint.setObjectName("subtitleLabel")
        self.capture_hint.setWordWrap(True)
        outer.addWidget(self.capture_hint)

        controls = QHBoxLayout()
        self.start_button = QPushButton("啟動主控端")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self.start_server)

        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.clicked.connect(self.stop_server)

        self.sync_checkbox = QCheckBox("啟用鍵盤同步")
        self.sync_checkbox.setChecked(True)
        self.sync_checkbox.toggled.connect(self.on_sync_toggled)

        self.status_label = QLabel("尚未啟動")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        controls.addWidget(self.start_button)
        controls.addWidget(self.stop_button)
        controls.addSpacing(8)
        controls.addWidget(self.sync_checkbox)
        controls.addStretch(1)
        controls.addWidget(self.status_label)
        outer.addLayout(controls)

        input_status_group = QGroupBox("主控端按鍵偵測測試")
        input_status_layout = QHBoxLayout(input_status_group)
        self.last_input_label = QLabel("最後偵測：尚無按鍵事件")
        self.last_input_label.setWordWrap(True)
        self.input_count_label = QLabel("事件數：0")
        input_status_layout.addWidget(self.last_input_label, 1)
        input_status_layout.addWidget(self.input_count_label)
        outer.addWidget(input_status_group)

        hint = QLabel(
            "請啟動後切換到遊戲並按W、A、S、D測試。Pause鍵可暫停或恢復同步，且不會傳給客戶端。"
        )
        hint.setObjectName("subtitleLabel")
        hint.setWordWrap(True)
        outer.addWidget(hint)

        clients_group = QGroupBox("已連線客戶端")
        clients_layout = QVBoxLayout(clients_group)
        self.clients_table = QTableWidget(0, 2)
        self.clients_table.setHorizontalHeaderLabels(["電腦名稱", "IP位址"])
        self.clients_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.clients_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.clients_table.setAlternatingRowColors(True)
        self.clients_table.verticalHeader().setVisible(False)
        self.clients_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self.clients_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents
        )
        clients_layout.addWidget(self.clients_table)
        outer.addWidget(clients_group, 2)

        log_group = QGroupBox("執行紀錄")
        log_layout = QVBoxLayout(log_group)
        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        log_layout.addWidget(self.log_edit)
        outer.addWidget(log_group, 3)

        self.update_capture_hint()

    def _update_admin_label(self) -> None:
        if is_running_as_admin():
            self.admin_label.setText("系統管理員")
            self.admin_label.setObjectName("statusRunning")
        else:
            self.admin_label.setText("一般權限")
            self.admin_label.setObjectName("statusWarning")
        self.admin_label.style().unpolish(self.admin_label)
        self.admin_label.style().polish(self.admin_label)

    @Slot()
    def update_capture_hint(self) -> None:
        engine = str(self.capture_combo.currentData())
        hints = {
            "bettergi_global_hook": (
                "BetterGI相容模式：直接使用Win32 WH_KEYBOARD_LL全域低階鍵盤鉤子，"
                "對應BetterGI的Hook.GlobalEvents()做法。"
            ),
            "win32_async_poll": (
                "遊戲備用模式：每2ms讀取GetAsyncKeyState；不依賴鍵盤訊息是否被遊戲攔截，"
                "只傳送按下／放開狀態變化。"
            ),
            "pynput_legacy": "舊版pynput Listener，保留供比較。",
        }
        self.capture_hint.setText(
            hints.get(engine, "選擇主控端的鍵盤偵測方式。")
            + " 主控端與遊戲建議使用相同權限，最好都以系統管理員身分執行。"
        )

    def _load_settings(self) -> None:
        self.tcp_spin.setValue(int(self.settings.value("tcp_port", DEFAULT_TCP_PORT)))
        self.discovery_spin.setValue(
            int(self.settings.value("discovery_port", DEFAULT_DISCOVERY_PORT))
        )
        saved_engine = str(
            self.settings.value("capture_engine", CAPTURE_BETTERGI_HOOK)
        )
        index = self.capture_combo.findData(saved_engine)
        if index < 0:
            index = self.capture_combo.findData(CAPTURE_BETTERGI_HOOK)
        self.capture_combo.setCurrentIndex(index)
        self.update_capture_hint()

    def _save_settings(self) -> None:
        self.settings.setValue("tcp_port", self.tcp_spin.value())
        self.settings.setValue("discovery_port", self.discovery_spin.value())
        self.settings.setValue("capture_engine", self.capture_combo.currentData())

    @Slot()
    def start_server(self) -> None:
        password = self.password_edit.text()
        if len(password) < 8:
            QMessageBox.warning(self, "設定錯誤", "共用密碼至少需要8個字元。")
            return

        self.input_event_count = 0
        self.input_count_label.setText("事件數：0")
        self.last_input_label.setText("最後偵測：等待按鍵…")

        try:
            self.server = KeyboardSyncServer(
                password=password,
                tcp_port=self.tcp_spin.value(),
                discovery_port=self.discovery_spin.value(),
                capture_engine=str(self.capture_combo.currentData()),
                log_callback=self.signals.log.emit,
                running_callback=self.signals.running.emit,
                clients_callback=self.signals.clients.emit,
                sync_callback=self.signals.sync.emit,
                input_event_callback=self.signals.input_event.emit,
            )
            self.server.start()
            self.server.set_broadcast_enabled(self.sync_checkbox.isChecked())
            self._save_settings()

        except (OSError, RuntimeError, ValueError) as exc:
            self.server = None
            QMessageBox.critical(
                self,
                "無法啟動",
                f"主控端或鍵盤偵測引擎啟動失敗：\n\n{exc}\n\n"
                "請改用系統管理員身分執行，或切換到另一個鍵盤偵測引擎。",
            )

    @Slot()
    def stop_server(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None

    @Slot(bool)
    def on_sync_toggled(self, checked: bool) -> None:
        if self.server is not None:
            self.server.set_broadcast_enabled(checked)

    @Slot(str)
    def append_log(self, message: str) -> None:
        self.log_edit.append(f"[{time.strftime('%H:%M:%S')}] {message}")

    @Slot(str)
    def update_input_event(self, event_text: str) -> None:
        self.input_event_count += 1
        self.last_input_label.setText(f"最後偵測：{event_text}")
        self.input_count_label.setText(f"事件數：{self.input_event_count}")

    @Slot(bool)
    def update_running_state(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.sync_checkbox.setEnabled(running)
        self.password_edit.setEnabled(not running)
        self.tcp_spin.setEnabled(not running)
        self.discovery_spin.setEnabled(not running)
        self.capture_combo.setEnabled(not running)

        if running:
            self.status_label.setText("主控端執行中")
            self.status_label.setObjectName("statusRunning")
        else:
            self.status_label.setText("尚未啟動")
            self.status_label.setObjectName("statusStopped")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    @Slot(object)
    def update_clients(self, rows: Any) -> None:
        client_rows = list(rows)
        self.clients_table.setRowCount(len(client_rows))
        for row_index, client in enumerate(client_rows):
            self.clients_table.setItem(
                row_index, 0, QTableWidgetItem(str(client.get("name", "")))
            )
            self.clients_table.setItem(
                row_index, 1, QTableWidgetItem(str(client.get("ip", "")))
            )

    @Slot(bool)
    def update_sync_state(self, enabled: bool) -> None:
        self.sync_checkbox.blockSignals(True)
        self.sync_checkbox.setChecked(enabled)
        self.sync_checkbox.blockSignals(False)

        if self.server is not None:
            if enabled:
                self.status_label.setText("同步已開啟")
                self.status_label.setObjectName("statusRunning")
            else:
                self.status_label.setText("同步已暫停")
                self.status_label.setObjectName("statusWarning")
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.stop_server()
        self._save_settings()
        event.accept()


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("LAN鍵盤同步Qt主控端")
    app.setStyleSheet(APP_STYLE)
    window = ServerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
