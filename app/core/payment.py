from __future__ import annotations

import threading
import time
from typing import Callable

from app.config import PAYMENT_TIMEOUT
from app.core.order import OrderService
from app.core.notification import notify


class PaymentWatcher:
    """支付倒计时监控：提醒用户支付，超时自动标记取消。"""

    def __init__(
        self,
        order_service: OrderService,
        on_tick: Callable[[str, int], None] | None = None,
        on_timeout: Callable[[str], None] | None = None,
        on_paid: Callable[[str], None] | None = None,
    ) -> None:
        self.order_service = order_service
        self.on_tick = on_tick or (lambda oid, sec: None)
        self.on_timeout = on_timeout or (lambda oid: None)
        self.on_paid = on_paid or (lambda oid: None)
        self._threads: dict[str, threading.Thread] = {}

    def watch(self, order_id: str, auto_pay: bool = False, show_notify: bool = True) -> None:
        if order_id in self._threads:
            return
        t = threading.Thread(
            target=self._run,
            args=(order_id, auto_pay),
            daemon=True,
        )
        self._threads[order_id] = t
        t.start()
        if show_notify:
            notify("待支付", f"订单 {order_id} 已生成，请在30分钟内完成支付")

    def confirm_paid(self, order_id: str) -> None:
        self.order_service.mark_paid(order_id)
        notify("支付成功", f"订单 {order_id} 已支付，出票成功！")
        self.on_paid(order_id)

    def _run(self, order_id: str, auto_pay: bool) -> None:
        remaining = PAYMENT_TIMEOUT
        while remaining > 0:
            self.on_tick(order_id, remaining)
            if auto_pay and remaining < PAYMENT_TIMEOUT - 5:
                self.confirm_paid(order_id)
                return
            time.sleep(10)
            remaining -= 10
        self.order_service.mark_cancelled(order_id, "支付超时")
        notify("订单取消", f"订单 {order_id} 支付超时，已自动取消")
        self.on_timeout(order_id)
        self._threads.pop(order_id, None)
