from __future__ import annotations

from PyQt6.QtCore import Qt, QObject, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from app.core.ticket_monitor import MonitorConfig, MonitorEvent, MonitorState, TicketMonitor


class MonitorBridge(QObject):
    event_received = pyqtSignal(object)


class MonitorPanel(QWidget):
    order_created = pyqtSignal(str, object, dict)
    start_requested = pyqtSignal()

    def __init__(self, monitor: TicketMonitor, parent=None) -> None:
        super().__init__(parent)
        self.monitor = monitor
        self._bridge = MonitorBridge()
        self._bridge.event_received.connect(self._handle_event)
        self.monitor.on_event = self._bridge.event_received.emit
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        ctrl_group = QGroupBox("监控控制")
        ctrl_layout = QHBoxLayout(ctrl_group)
        self.start_btn = QPushButton("开始抢票")
        self.pause_btn = QPushButton("暂停")
        self.stop_btn = QPushButton("停止")
        self.start_btn.clicked.connect(lambda: self.start_requested.emit())
        self.pause_btn.clicked.connect(self._pause)
        self.stop_btn.clicked.connect(self._stop)
        ctrl_layout.addWidget(self.start_btn)
        ctrl_layout.addWidget(self.pause_btn)
        ctrl_layout.addWidget(self.stop_btn)
        ctrl_layout.addStretch()
        self.state_label = QLabel("状态: 空闲")
        ctrl_layout.addWidget(self.state_label)
        layout.addWidget(ctrl_group)

        self.ticket_table = QTableWidget(0, 7)
        self.ticket_table.setHorizontalHeaderLabels(
            ["车次", "出发", "到达", "历时", "二等座", "一等座", "硬卧"]
        )
        self.ticket_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.ticket_table.setMinimumHeight(200)
        self.ticket_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.ticket_table, 2)

        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout(log_group)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(120)
        self.log_view.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        log_layout.addWidget(self.log_view)
        layout.addWidget(log_group, 1)

    def start_with_config(self, config_dict: dict) -> None:
        cfg = MonitorConfig(
            from_code=config_dict["from_code"],
            to_code=config_dict["to_code"],
            from_name=config_dict["from_name"],
            to_name=config_dict["to_name"],
            travel_dates=config_dict.get("travel_dates") or [config_dict.get("travel_date", "")],
            train_codes=config_dict.get("train_codes", []),
            seat_types=config_dict.get("seat_types", ["二等座"]),
            poll_interval=config_dict.get("poll_interval", 3),
            enable_waitlist=config_dict.get("enable_waitlist", False),
            auto_submit=config_dict.get("auto_submit", True),
            passenger_ids=config_dict.get("passenger_ids", []),
        )
        self.monitor.start(cfg)
        self._append_log("开始监控...")

    def _pause(self) -> None:
        if self.monitor.state == MonitorState.RUNNING:
            self.monitor.pause()
        elif self.monitor.state == MonitorState.PAUSED:
            self.monitor.resume()

    def _stop(self) -> None:
        self.monitor.stop()

    def _handle_event(self, event: MonitorEvent) -> None:
        self.log_view.append(f"[{event.type}] {event.message}")
        self.state_label.setText(f"状态: {self.monitor.state.value}")

        if event.ticket:
            self._update_ticket_row(event.ticket)

        if event.type == "order_success" and event.data:
            self.order_created.emit(
                event.data.get("order_id", ""),
                event.ticket,
                event.data,
            )

        if event.type in ("found", "order_success"):
            self.log_view.verticalScrollBar().setValue(
                self.log_view.verticalScrollBar().maximum()
            )

    def _update_ticket_row(self, ticket) -> None:
        for row in range(self.ticket_table.rowCount()):
            if self.ticket_table.item(row, 0).text() == ticket.train_code:
                return
        row = self.ticket_table.rowCount()
        self.ticket_table.insertRow(row)
        values = [
            ticket.train_code,
            ticket.start_time,
            ticket.arrive_time,
            ticket.duration,
            ticket.seats.get("二等座", "--"),
            ticket.seats.get("一等座", "--"),
            ticket.seats.get("硬卧", "--"),
        ]
        for col, val in enumerate(values):
            item = QTableWidgetItem(val)
            if val not in ("--", "无", "*") and (val == "有" or val.isdigit()):
                item.setBackground(QColor("#d5f5e3"))
            self.ticket_table.setItem(row, col, item)

    def _append_log(self, msg: str) -> None:
        self.log_view.append(msg)
