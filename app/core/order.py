from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.config import SEAT_TYPES, USE_MOCK
from app.core.api_client import ApiClient, TrainTicket
from app.database.db import get_session
from app.database.models import OrderRecord, Passenger


@dataclass
class OrderSubmitResult:
    success: bool
    message: str
    order_id: str = ""
    price: str = ""


class OrderService:
    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def submit(
        self,
        ticket: TrainTicket,
        seat_type: str,
        travel_date: str,
        passenger_ids: list[int],
    ) -> OrderSubmitResult:
        if not self.client.logged_in:
            return OrderSubmitResult(False, "请先登录")

        passengers = self._load_passengers(passenger_ids)
        if not passengers:
            return OrderSubmitResult(False, "请配置乘车人")

        try:
            resp = self.client.submit_order_request(
                secret_str=ticket.secret_str,
                train_date=travel_date,
                from_code=ticket.from_station_name or ticket.from_station,
                to_code=ticket.to_station_name or ticket.to_station,
            )
            if USE_MOCK:
                if resp.get("status"):
                    order_id = resp["order_id"]
                    self._save_order(ticket, seat_type, travel_date, passengers, order_id)
                    return OrderSubmitResult(
                        True, "下单成功，请在30分钟内完成支付", order_id, "553.5"
                    )
                return OrderSubmitResult(False, resp.get("message", "下单失败"))

            if resp.get("status") is True or resp.get("data") == "N":
                order_id = resp.get("data", {}).get("orderId", "")
                self._save_order(ticket, seat_type, travel_date, passengers, order_id)
                confirm = self.client.confirm_passenger_info(
                    passengers, SEAT_TYPES.get(seat_type, "O"), ticket.train_code
                )
                price = confirm.get("ticket_price", "")
                return OrderSubmitResult(True, "订单提交成功", order_id, price)
            msg = resp.get("messages", ["下单失败"])
            return OrderSubmitResult(False, msg[0] if msg else "下单失败")
        except Exception as exc:
            return OrderSubmitResult(False, f"下单异常: {exc}")

    def _load_passengers(self, passenger_ids: list[int]) -> list[dict]:
        if not passenger_ids:
            return [{"name": "测试乘客", "id_no": "110101199001011234", "id_type": "1"}]
        with get_session() as session:
            rows = (
                session.query(Passenger)
                .filter(Passenger.id.in_(passenger_ids))
                .all()
            )
            return [
                {
                    "name": p.name,
                    "id_no": p.id_no,
                    "id_type": p.id_type,
                    "passenger_type": p.passenger_type,
                }
                for p in rows
            ]

    def _save_order(
        self,
        ticket: TrainTicket,
        seat_type: str,
        travel_date: str,
        passengers: list[dict],
        order_id: str,
    ) -> None:
        names = ",".join(p["name"] for p in passengers)
        with get_session() as session:
            record = OrderRecord(
                order_id=order_id,
                train_code=ticket.train_code,
                from_station=ticket.from_station_name,
                to_station=ticket.to_station_name,
                travel_date=travel_date,
                seat_type=seat_type,
                passengers=names,
                status="wait_pay",
                created_at=datetime.now(),
            )
            session.add(record)

    def mark_paid(self, order_id: str) -> None:
        with get_session() as session:
            record = session.query(OrderRecord).filter_by(order_id=order_id).first()
            if record:
                record.status = "paid"
                record.paid_at = datetime.now()

    def mark_cancelled(self, order_id: str, reason: str = "") -> None:
        with get_session() as session:
            record = session.query(OrderRecord).filter_by(order_id=order_id).first()
            if record:
                record.status = "cancelled"
                record.remark = reason
