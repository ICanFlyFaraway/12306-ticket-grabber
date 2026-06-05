from __future__ import annotations

from PyQt6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.database.db import get_session
from app.database.models import OrderRecord


class HistoryPanel(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.refresh()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        toolbar = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self.refresh)
        toolbar.addWidget(refresh_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["订单号", "车次", "出发", "到达", "日期", "席别", "乘客", "状态"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setMinimumHeight(240)
        self.table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        layout.addWidget(self.table, 1)

        stats_group = QGroupBox("统计")
        stats_layout = QHBoxLayout(stats_group)
        self.stats_label = QLabel("总计 0 单")
        stats_layout.addWidget(self.stats_label)
        layout.addWidget(stats_group)

    def refresh(self) -> None:
        self.table.setRowCount(0)
        with get_session() as session:
            records = session.query(OrderRecord).order_by(OrderRecord.created_at.desc()).all()
            for rec in records:
                row = self.table.rowCount()
                self.table.insertRow(row)
                values = [
                    rec.order_id,
                    rec.train_code,
                    rec.from_station,
                    rec.to_station,
                    rec.travel_date,
                    rec.seat_type,
                    rec.passengers,
                    rec.status,
                ]
                for col, val in enumerate(values):
                    self.table.setItem(row, col, QTableWidgetItem(str(val)))
            paid = sum(1 for r in records if r.status == "paid")
            wait = sum(1 for r in records if r.status == "wait_pay")
            self.stats_label.setText(
                f"总计 {len(records)} 单 | 待支付 {wait} | 已支付 {paid}"
            )
