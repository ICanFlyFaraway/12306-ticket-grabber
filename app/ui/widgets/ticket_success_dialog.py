from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from app.core.api_client import TrainTicket


class TicketSuccessDialog(QDialog):
    """抢票成功模态弹窗，必须手动点击确认才会关闭。"""

    def __init__(
        self,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str,
        travel_date: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("抢票成功")
        self.setModal(True)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.setMinimumWidth(420)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)

        layout = QVBoxLayout(self)
        title = QLabel("抢票成功，请尽快完成支付")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #27ae60;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        if ticket:
            lines = [
                f"订单号：{order_id}",
                f"出发日期：{travel_date or ticket.travel_date}",
                f"车次：{ticket.train_code}",
                f"行程：{ticket.from_station_name} → {ticket.to_station_name}",
                f"时间：{ticket.start_time} 开 → {ticket.arrive_time} 到",
                f"席别：{seat_type or '—'}",
                "",
                "请在 30 分钟内登录 12306 客户端或官网完成支付。",
                "超时未支付，订单将自动取消。",
            ]
        else:
            lines = [
                f"订单号：{order_id}",
                "",
                "请在 30 分钟内登录 12306 完成支付。",
                "超时未支付，订单将自动取消。",
            ]

        body = QLabel("\n".join(lines))
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(body)

        hint = QLabel("请点击下方「我知道了」关闭此窗口。")
        hint.setStyleSheet("color: #666; font-size: 12px;")
        layout.addWidget(hint)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        if ok_btn:
            ok_btn.setText("我知道了")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)

    @staticmethod
    def show_blocking(
        parent,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str,
        travel_date: str,
    ) -> None:
        dialog = TicketSuccessDialog(order_id, ticket, seat_type, travel_date, parent)
        dialog.exec()
