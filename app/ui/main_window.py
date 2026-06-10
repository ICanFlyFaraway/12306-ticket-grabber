from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QSystemTrayIcon,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.config import APP_NAME, USE_MOCK
from app.core.api_client import ApiClient
from app.core.auth import AuthService
from app.core.calendar_sync import CalendarSync
from app.core.notification import notify
from app.core.order import OrderService
from app.core.payment import PaymentWatcher
from app.core.proxy_pool import ProxyPool
from app.core.scheduler import TaskScheduler
from app.core.ticket_monitor import TicketMonitor
from app.ui.scroll import wrap_scroll_area
from app.ui.workers.sms_worker import SmsSendWorker
from app.ui.widgets.config_panel import ConfigPanel
from app.ui.widgets.history_panel import HistoryPanel
from app.ui.widgets.login_panel import LoginPanel
from app.ui.widgets.monitor_panel import MonitorPanel
from app.ui.widgets.settings_panel import SettingsPanel
from app.ui.widgets.ticket_success_dialog import TicketSuccessDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(720, 480)
        self.resize(960, 820)

        self.proxy_pool = ProxyPool()
        self.client = ApiClient(self.proxy_pool)
        self.client.init_session()
        self.auth = AuthService(self.client)
        self.order_service = OrderService(self.client)
        self.monitor = TicketMonitor(self.client, self.order_service)
        self.payment_watcher = PaymentWatcher(self.order_service, on_tick=self._on_payment_tick)
        self.scheduler = TaskScheduler()
        self.calendar = CalendarSync()
        self._sms_worker: SmsSendWorker | None = None

        self._build_ui()
        self._setup_tray()
        self._setup_status()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QHBoxLayout()
        title = QLabel(f"🚄 {APP_NAME}")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        header.addWidget(title)
        if USE_MOCK:
            mock_label = QLabel("【模拟模式】")
            mock_label.setStyleSheet("color: #e67e22; font-weight: bold;")
            header.addWidget(mock_label)
        header.addStretch()
        layout.addLayout(header)

        tabs = QTabWidget()
        self.config_panel = ConfigPanel(self.client)
        self.login_panel = LoginPanel(self.auth)
        self.monitor_panel = MonitorPanel(self.monitor)
        self.history_panel = HistoryPanel()
        self.settings_panel = SettingsPanel(self.proxy_pool)
        self._tabs = tabs

        tabs.addTab(wrap_scroll_area(self.config_panel), "行程配置")
        tabs.addTab(wrap_scroll_area(self.login_panel), "登录")
        tabs.addTab(wrap_scroll_area(self.monitor_panel), "抢票监控")
        tabs.addTab(wrap_scroll_area(self.history_panel), "历史订单")
        tabs.addTab(wrap_scroll_area(self.settings_panel), "设置")
        layout.addWidget(tabs, 1)

        self.config_panel.saved.connect(lambda _: self.statusBar().showMessage("配置已保存", 3000))
        self.login_panel.login_success.connect(self._on_login_success)
        self.monitor_panel.start_requested.connect(self._start_grabbing)
        self.monitor_panel.order_created.connect(
            self._on_order_created,
            Qt.ConnectionType.QueuedConnection,
        )

    def _setup_status(self) -> None:
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage("就绪")

    def _setup_tray(self) -> None:
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(self)
        self.tray.setToolTip(APP_NAME)
        self.tray.show()

    def _on_login_success(self, username: str) -> None:
        self.statusBar().showMessage(f"登录成功: {username}", 5000)
        notify("登录成功", f"账号 {username} 已登录")

    def _start_grabbing(self) -> None:
        if not self.auth.client.logged_in:
            QMessageBox.warning(self, "提示", "请先登录 12306 账号")
            return
        cfg = self.config_panel.get_monitor_config()
        if not cfg:
            QMessageBox.warning(self, "提示", "请完善行程配置")
            return
        self.monitor_panel.start_with_config(cfg)
        self.statusBar().showMessage("抢票监控已启动")
        dates = cfg.get("travel_dates") or [cfg.get("travel_date", "")]
        notify("开始抢票", f"{cfg['from_name']} → {cfg['to_name']} {'、'.join(dates)}")

    def _on_order_created(self, order_id: str, ticket, meta: dict | None = None) -> None:
        auto_pay = self.settings_panel.is_auto_pay()
        self.history_panel.refresh()
        meta = meta or {}
        travel_date = (
            meta.get("travel_date", "")
            or getattr(ticket, "travel_date", "")
            or self.config_panel.get_primary_travel_date()
        )
        seat_type = meta.get("seat_type", "")

        self.show()
        self.raise_()
        self.activateWindow()
        if QApplication.instance():
            QApplication.alert(self, 0)

        tabs = self._tabs
        if tabs:
            tabs.setCurrentIndex(2)

        TicketSuccessDialog.show_blocking(
            self, order_id, ticket, seat_type, travel_date
        )

        self.payment_watcher.watch(order_id, auto_pay=auto_pay, show_notify=False)
        self.statusBar().showMessage(f"抢票成功，订单 {order_id} 待支付", 15000)

        if ticket:
            self.calendar.add_trip(
                ticket.train_code,
                ticket.from_station_name,
                ticket.to_station_name,
                travel_date,
                ticket.start_time,
                ticket.arrive_time,
            )

        if self.settings_panel.is_sms_enabled():
            self._sms_worker = SmsSendWorker(order_id, ticket, seat_type, travel_date)
            self._sms_worker.finished.connect(self._on_sms_sent)
            self._sms_worker.start()

    def _on_sms_sent(self, results: list) -> None:
        summary = "；".join(results)
        self.statusBar().showMessage(f"短信通知: {summary}", 10000)
        notify("短信通知", summary)

    def _on_payment_tick(self, order_id: str, remaining: int) -> None:
        mins = remaining // 60
        self.statusBar().showMessage(f"订单 {order_id} 待支付，剩余 {mins} 分钟")

    def closeEvent(self, event) -> None:
        self.monitor.stop()
        self.scheduler.shutdown()
        event.accept()
