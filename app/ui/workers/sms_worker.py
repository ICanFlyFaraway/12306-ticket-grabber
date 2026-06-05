from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal

from app.core.api_client import TrainTicket
from app.core.sms import SmsService


class SmsSendWorker(QThread):
    finished = pyqtSignal(list)

    def __init__(
        self,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str,
        travel_date: str,
    ) -> None:
        super().__init__()
        self.order_id = order_id
        self.ticket = ticket
        self.seat_type = seat_type
        self.travel_date = travel_date

    def run(self) -> None:
        results = SmsService().send_ticket_success(
            self.order_id,
            self.ticket,
            self.seat_type,
            self.travel_date,
        )
        self.finished.emit(results)
