APP_STYLE = """
QWidget {
    font-family: "Microsoft JhengHei UI", "Microsoft JhengHei";
    font-size: 10pt;
    color: #172033;
}

QMainWindow {
    background: #f4f7fb;
}

QGroupBox {
    background: #ffffff;
    border: 1px solid #d9e2ef;
    border-radius: 10px;
    margin-top: 12px;
    padding-top: 10px;
    font-weight: 600;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: #334155;
}

QLineEdit,
QSpinBox,
QComboBox {
    min-height: 34px;
    padding: 0 9px;
    background: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 7px;
    selection-background-color: #2563eb;
}

QLineEdit:focus,
QSpinBox:focus,
QComboBox:focus {
    border: 1px solid #2563eb;
}

QPushButton {
    min-height: 36px;
    padding: 0 16px;
    border: 1px solid #cbd5e1;
    border-radius: 8px;
    background: #ffffff;
    font-weight: 600;
}

QPushButton:hover {
    background: #f8fafc;
    border-color: #94a3b8;
}

QPushButton:pressed {
    background: #e2e8f0;
}

QPushButton:disabled {
    color: #94a3b8;
    background: #f1f5f9;
    border-color: #e2e8f0;
}

QPushButton#primaryButton {
    color: #ffffff;
    background: #2563eb;
    border-color: #2563eb;
}

QPushButton#primaryButton:hover {
    background: #1d4ed8;
}

QPushButton#dangerButton {
    color: #ffffff;
    background: #dc2626;
    border-color: #dc2626;
}

QPushButton#dangerButton:hover {
    background: #b91c1c;
}

QPushButton#warningButton {
    color: #ffffff;
    background: #d97706;
    border-color: #d97706;
}

QPushButton#warningButton:hover {
    background: #b45309;
}

QTextEdit,
QTableWidget,
QListWidget {
    background: #ffffff;
    border: 1px solid #d9e2ef;
    border-radius: 8px;
    alternate-background-color: #f8fafc;
}

QHeaderView::section {
    background: #eef2f7;
    color: #334155;
    border: none;
    border-bottom: 1px solid #d9e2ef;
    padding: 8px;
    font-weight: 600;
}

QCheckBox {
    spacing: 8px;
}

QCheckBox::indicator {
    width: 18px;
    height: 18px;
}

QLabel#titleLabel {
    font-size: 20pt;
    font-weight: 700;
    color: #0f172a;
}

QLabel#subtitleLabel {
    color: #64748b;
}

QLabel#statusRunning {
    color: #166534;
    background: #dcfce7;
    border: 1px solid #86efac;
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 600;
}

QLabel#statusStopped {
    color: #475569;
    background: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 600;
}

QLabel#statusWarning {
    color: #92400e;
    background: #fef3c7;
    border: 1px solid #fcd34d;
    border-radius: 12px;
    padding: 4px 10px;
    font-weight: 600;
}
"""
