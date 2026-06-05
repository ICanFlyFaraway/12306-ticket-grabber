from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from app.config import SEAT_TYPES
from app.core.api_client import ApiClient, TrainTicket, has_ticket
from app.core.order import OrderService, OrderSubmitResult


class MonitorState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class MonitorConfig:
    from_code: str
    to_code: str
    from_name: str
    to_name: str
    travel_dates: list[str] = field(default_factory=list)
    train_codes: list[str] = field(default_factory=list)
    seat_types: list[str] = field(default_factory=lambda: ["二等座"])
    poll_interval: float = 3.0
    enable_waitlist: bool = False
    auto_submit: bool = True
    passenger_ids: list[int] = field(default_factory=list)

    @property
    def travel_date(self) -> str:
        return self.travel_dates[0] if self.travel_dates else ""


@dataclass
class MonitorEvent:
    type: str
    message: str
    ticket: TrainTicket | None = None
    data: dict | None = None


class TicketMonitor:
    """余票监控：轮询查票，发现余票后触发下单。"""

    def __init__(
        self,
        client: ApiClient,
        order_service: OrderService,
        on_event: Callable[[MonitorEvent], None] | None = None,
    ) -> None:
        self.client = client
        self.order_service = order_service
        self.on_event = on_event or (lambda e: None)
        self.config: MonitorConfig | None = None
        self.state = MonitorState.IDLE
        self._thread: threading.Thread | None = None
        self._stop_flag = threading.Event()
        self._poll_count = 0

    def start(self, config: MonitorConfig) -> None:
        if self.state == MonitorState.RUNNING:
            return
        self.config = config
        self._stop_flag.clear()
        self.state = MonitorState.RUNNING
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._emit("start", "开始监控余票")

    def stop(self) -> None:
        self._stop_flag.set()
        self.state = MonitorState.STOPPED
        self._emit("stop", "监控已停止")

    def pause(self) -> None:
        if self.state == MonitorState.RUNNING:
            self.state = MonitorState.PAUSED
            self._emit("pause", "监控已暂停")

    def resume(self) -> None:
        if self.state == MonitorState.PAUSED:
            self.state = MonitorState.RUNNING
            self._emit("resume", "监控已恢复")

    def _run_loop(self) -> None:
        assert self.config is not None
        cfg = self.config
        while not self._stop_flag.is_set():
            if self.state == MonitorState.PAUSED:
                time.sleep(0.5)
                continue

            try:
                self._poll_count += 1
                all_matched: list[tuple[TrainTicket, str]] = []
                for travel_date in cfg.travel_dates:
                    tickets = self.client.query_tickets(
                        cfg.from_code, cfg.to_code, travel_date, force_real=True
                    )
                    matched = self._filter_tickets(tickets, cfg)
                    all_matched.extend(matched)

                if all_matched:
                    for ticket, seat_type in all_matched:
                        date_hint = ticket.travel_date or cfg.travel_date
                        self._emit(
                            "found",
                            f"发现余票 {date_hint} {ticket.train_code} {seat_type}",
                            ticket=ticket,
                            data={"seat_type": seat_type, "travel_date": date_hint},
                        )
                        if cfg.auto_submit:
                            result = self._submit(ticket, seat_type, cfg)
                            if result.success:
                                self.state = MonitorState.SUCCESS
                                self._emit(
                                    "order_success",
                                    f"下单成功，订单号 {result.order_id}",
                                    ticket=ticket,
                                    data={"order_id": result.order_id},
                                )
                                return
                            self._emit(
                                "order_fail",
                                result.message,
                                ticket=ticket,
                            )
                else:
                    dates_text = "、".join(cfg.travel_dates)
                    self._emit(
                        "polling",
                        f"第 {self._poll_count} 次查票（{dates_text}），暂无符合条件余票",
                    )
            except Exception as exc:
                self._emit("error", f"查票异常: {exc}")

            time.sleep(cfg.poll_interval + random.uniform(0, 0.5))

        self.state = MonitorState.STOPPED

    def _filter_tickets(
        self, tickets: list[TrainTicket], cfg: MonitorConfig
    ) -> list[tuple[TrainTicket, str]]:
        result: list[tuple[TrainTicket, str]] = []
        for ticket in tickets:
            if cfg.train_codes and ticket.train_code not in cfg.train_codes:
                continue
            if ticket.can_web_buy != "Y":
                continue
            for seat in cfg.seat_types:
                status = ticket.seats.get(seat, "--")
                if has_ticket(status):
                    result.append((ticket, seat))
                    break
        return result

    def _submit(
        self, ticket: TrainTicket, seat_type: str, cfg: MonitorConfig
    ) -> OrderSubmitResult:
        travel_date = ticket.travel_date or cfg.travel_date
        return self.order_service.submit(
            ticket=ticket,
            seat_type=seat_type,
            travel_date=travel_date,
            passenger_ids=cfg.passenger_ids,
        )

    def _emit(
        self,
        event_type: str,
        message: str,
        ticket: TrainTicket | None = None,
        data: dict | None = None,
    ) -> None:
        self.on_event(MonitorEvent(event_type, message, ticket, data))
