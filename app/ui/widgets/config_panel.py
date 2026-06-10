from __future__ import annotations

from PyQt6.QtCore import Qt, QDate, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.config import QUERY_SEAT_COLUMNS, SEAT_TYPE_LABELS
from app.core.api_client import ApiClient, TrainTicket, format_seat_display, seat_has_stock_display
from app.core.station_registry import (
    get_last_refreshed,
    get_station_count,
    get_station_registry,
    refresh_stations_from_remote,
)
from app.database.db import get_session
from app.database.models import Passenger, TaskConfig

TRAIN_TABLE_ROW_HEIGHT = 30
TRAIN_TABLE_VISIBLE_ROWS = 10


class StationRefreshWorker(QThread):
    finished = pyqtSignal(int, str)
    failed = pyqtSignal(str)

    def run(self) -> None:
        try:
            count, refreshed_at = refresh_stations_from_remote()
            self.finished.emit(count, refreshed_at.strftime("%Y-%m-%d %H:%M"))
        except Exception as exc:
            self.failed.emit(str(exc))


class TrainQueryWorker(QThread):
    finished = pyqtSignal(list, list)
    failed = pyqtSignal(str)

    def __init__(
        self,
        client: ApiClient,
        from_name: str,
        to_name: str,
        travel_dates: list[str],
        local_stations: dict[str, str],
    ) -> None:
        super().__init__()
        self.client = client
        self.from_name = from_name
        self.to_name = to_name
        self.travel_dates = travel_dates
        self.local_stations = local_stations

    def run(self) -> None:
        try:
            self.client.init_session(force_real=True)
            from_code = self.client.resolve_station_code(self.from_name, self.local_stations)
            to_code = self.client.resolve_station_code(self.to_name, self.local_stations)
            tickets, warnings = self.client.query_tickets_multi_dates(
                from_code, to_code, self.travel_dates, force_real=True
            )
            self.finished.emit(tickets, warnings)
        except Exception as exc:
            self.failed.emit(str(exc))


class ConfigPanel(QWidget):
    saved = pyqtSignal(dict)

    def __init__(self, client: ApiClient, parent=None) -> None:
        super().__init__(parent)
        self.client = client
        self._stations = get_station_registry()
        self._query_worker: TrainQueryWorker | None = None
        self._station_refresh_worker: StationRefreshWorker | None = None
        self._saved_train_codes: list[str] = []
        self._build_ui()
        self._load_passengers()
        self._load_last_config()
        if not self.get_travel_dates():
            self._add_default_date()

    def _load_stations(self) -> dict[str, str]:
        return get_station_registry()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        route_group = QGroupBox("行程配置")
        form = QFormLayout(route_group)

        self.from_combo = QComboBox()
        self.from_combo.setEditable(True)
        self.from_combo.addItems(sorted(self._stations.keys()))
        form.addRow("出发站", self.from_combo)

        self.to_combo = QComboBox()
        self.to_combo.setEditable(True)
        self.to_combo.addItems(sorted(self._stations.keys()))
        form.addRow("到达站", self.to_combo)

        station_row = QHBoxLayout()
        self.refresh_station_btn = QPushButton("刷新站名")
        self.refresh_station_btn.clicked.connect(self._refresh_stations)
        self.station_info_label = QLabel()
        self.station_info_label.setStyleSheet("color: gray;")
        station_row.addWidget(self.refresh_station_btn)
        station_row.addWidget(self.station_info_label)
        station_row.addStretch()
        form.addRow("车站数据", station_row)
        self._update_station_info_label()

        date_row = QHBoxLayout()
        self.date_edit = QDateEdit()
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDate(QDate.currentDate().addDays(1))
        self.date_edit.setDisplayFormat("yyyy-MM-dd")
        add_date_btn = QPushButton("添加日期")
        add_date_btn.clicked.connect(self._add_date)
        remove_date_btn = QPushButton("删除选中")
        remove_date_btn.clicked.connect(self._remove_selected_dates)
        date_row.addWidget(self.date_edit)
        date_row.addWidget(add_date_btn)
        date_row.addWidget(remove_date_btn)
        form.addRow("出发日期", date_row)

        self.date_list = QListWidget()
        self.date_list.setMaximumHeight(80)
        self.date_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        form.addRow("已选日期", self.date_list)

        layout.addWidget(route_group)

        train_group = QGroupBox("车次查询（12306 实时接口）")
        train_layout = QVBoxLayout(train_group)

        query_row = QHBoxLayout()
        self.query_btn = QPushButton("查询车次")
        self.query_btn.clicked.connect(self._query_trains)
        self.query_status = QLabel("请先选择站点和日期，再点击查询")
        self.query_status.setStyleSheet("color: gray;")
        select_all_btn = QPushButton("全选")
        select_all_btn.clicked.connect(lambda: self._set_all_trains(True))
        deselect_all_btn = QPushButton("取消全选")
        deselect_all_btn.clicked.connect(lambda: self._set_all_trains(False))
        query_row.addWidget(self.query_btn)
        query_row.addWidget(select_all_btn)
        query_row.addWidget(deselect_all_btn)
        query_row.addStretch()
        query_row.addWidget(self.query_status)
        train_layout.addLayout(query_row)

        self.train_table = QTableWidget(0, 8 + len(QUERY_SEAT_COLUMNS))
        headers = (
            ["选", "日期", "车次", "出发站", "到达站", "出发", "到达", "历时"]
            + QUERY_SEAT_COLUMNS
        )
        self.train_table.setHorizontalHeaderLabels(headers)
        self.train_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.train_table.horizontalHeader().setStretchLastSection(True)
        self.train_table.setHorizontalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.train_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.train_table.verticalHeader().setDefaultSectionSize(TRAIN_TABLE_ROW_HEIGHT)
        self.train_table.verticalHeader().setVisible(False)
        table_min_height = (
            self.train_table.horizontalHeader().height()
            + TRAIN_TABLE_ROW_HEIGHT * TRAIN_TABLE_VISIBLE_ROWS
            + 8
        )
        self.train_table.setMinimumHeight(table_min_height)
        self.train_table.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        train_layout.addWidget(self.train_table, 1)
        layout.addWidget(train_group, 1)

        seat_group = QGroupBox("席别与策略")
        seat_layout = QVBoxLayout(seat_group)
        self.seat_checks: dict[str, QCheckBox] = {}
        row = QHBoxLayout()
        for i, seat in enumerate(SEAT_TYPE_LABELS[:6]):
            cb = QCheckBox(seat)
            if seat == "二等座":
                cb.setChecked(True)
            self.seat_checks[seat] = cb
            row.addWidget(cb)
            if i == 2:
                seat_layout.addLayout(row)
                row = QHBoxLayout()
        seat_layout.addLayout(row)

        opts = QHBoxLayout()
        self.waitlist_cb = QCheckBox("启用候补")
        self.auto_submit_cb = QCheckBox("发现余票自动下单")
        self.auto_submit_cb.setChecked(True)
        opts.addWidget(self.waitlist_cb)
        opts.addWidget(self.auto_submit_cb)
        seat_layout.addLayout(opts)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("轮询间隔(秒)"))
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(1, 60)
        self.interval_spin.setValue(3)
        self.interval_spin.setSingleStep(0.5)
        interval_row.addWidget(self.interval_spin)
        interval_row.addStretch()
        seat_layout.addLayout(interval_row)
        layout.addWidget(seat_group)

        passenger_group = QGroupBox("乘车人")
        pg_layout = QVBoxLayout(passenger_group)
        self.passenger_list = QListWidget()
        self.passenger_list.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        pg_layout.addWidget(self.passenger_list)

        p_btn_row = QHBoxLayout()
        add_btn = QPushButton("添加乘车人")
        add_btn.clicked.connect(self._add_passenger_dialog)
        p_btn_row.addWidget(add_btn)
        p_btn_row.addStretch()
        pg_layout.addLayout(p_btn_row)
        layout.addWidget(passenger_group)

        save_btn = QPushButton("保存配置")
        save_btn.clicked.connect(self._save_config)
        layout.addWidget(save_btn)

    def _update_station_info_label(self) -> None:
        count = get_station_count()
        refreshed = get_last_refreshed()
        if refreshed:
            text = f"本地共 {count} 个站，更新于 {refreshed.strftime('%Y-%m-%d %H:%M')}"
        else:
            text = f"本地共 {count} 个站"
        self.station_info_label.setText(text)

    def _reload_station_combos(self) -> None:
        from_text = self.from_combo.currentText()
        to_text = self.to_combo.currentText()
        self._stations = get_station_registry(refresh=True)
        names = sorted(self._stations.keys())
        for combo, text in ((self.from_combo, from_text), (self.to_combo, to_text)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if text:
                combo.setCurrentText(text)
            combo.blockSignals(False)

    def _refresh_stations(self) -> None:
        if self._station_refresh_worker and self._station_refresh_worker.isRunning():
            return
        self.refresh_station_btn.setEnabled(False)
        self.station_info_label.setText("正在从 12306 更新站名...")
        self._station_refresh_worker = StationRefreshWorker()
        self._station_refresh_worker.finished.connect(self._on_station_refresh_finished)
        self._station_refresh_worker.failed.connect(self._on_station_refresh_failed)
        self._station_refresh_worker.start()

    def _on_station_refresh_finished(self, count: int, refreshed_text: str) -> None:
        self.refresh_station_btn.setEnabled(True)
        self._reload_station_combos()
        self._update_station_info_label()
        QMessageBox.information(
            self,
            "站名更新成功",
            f"已从 12306 同步 {count} 个车站到本地数据库\n更新时间：{refreshed_text}",
        )

    def _on_station_refresh_failed(self, message: str) -> None:
        self.refresh_station_btn.setEnabled(True)
        self._update_station_info_label()
        QMessageBox.critical(self, "站名更新失败", message)

    def _add_default_date(self) -> None:
        self.date_edit.setMinimumDate(QDate.currentDate())
        self.date_edit.setMaximumDate(QDate.currentDate().addDays(15))
        default = self.date_edit.date().toString("yyyy-MM-dd")
        self.date_list.clear()
        self.date_list.addItem(default)

    def _add_date(self) -> None:
        date_str = self.date_edit.date().toString("yyyy-MM-dd")
        err = self._date_error(date_str)
        if err:
            QMessageBox.warning(self, "日期无效", err)
            return
        for i in range(self.date_list.count()):
            if self.date_list.item(i).text() == date_str:
                QMessageBox.information(self, "提示", f"日期 {date_str} 已存在")
                return
        self.date_list.addItem(date_str)

    def _remove_selected_dates(self) -> None:
        for item in self.date_list.selectedItems():
            self.date_list.takeItem(self.date_list.row(item))

    def get_travel_dates(self) -> list[str]:
        return [self.date_list.item(i).text() for i in range(self.date_list.count())]

    def _query_trains(self) -> None:
        from_name = self.from_combo.currentText().strip()
        to_name = self.to_combo.currentText().strip()
        dates = self.get_travel_dates()
        if not from_name or not to_name:
            QMessageBox.warning(self, "提示", "请填写出发站和到达站")
            return
        if not dates:
            QMessageBox.warning(self, "提示", "请至少添加一个出发日期")
            return
        invalid = [d for d in dates if self._date_error(d)]
        if invalid:
            QMessageBox.warning(
                self,
                "日期无效",
                "\n".join(self._date_error(d) for d in invalid),
            )
            return
        if self._query_worker and self._query_worker.isRunning():
            return

        self.query_btn.setEnabled(False)
        self.query_status.setText("正在查询 12306 实时余票...")
        self._query_worker = TrainQueryWorker(
            self.client, from_name, to_name, dates, self._stations
        )
        self._query_worker.finished.connect(self._on_query_finished)
        self._query_worker.failed.connect(self._on_query_failed)
        self._query_worker.start()

    def _date_error(self, date_str: str) -> str | None:
        from datetime import date as date_cls, datetime, timedelta

        try:
            target = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return f"日期格式无效: {date_str}"
        today = date_cls.today()
        if target < today:
            return f"日期 {date_str} 已过期，请删除后重新添加"
        if target > today + timedelta(days=15):
            return f"日期 {date_str} 超出预售期（12306 通常仅预售 15 天内）"
        return None

    def _on_query_finished(self, tickets: list, warnings: list) -> None:
        self.query_btn.setEnabled(True)
        self.train_table.setRowCount(0)
        for ticket in tickets:
            self._append_train_row(ticket)
        self.query_status.setText(f"共查询到 {len(tickets)} 个车次，请勾选目标车次")
        if warnings:
            QMessageBox.warning(
                self,
                "部分日期查询失败",
                "\n".join(warnings) + f"\n\n已成功查询 {len(tickets)} 个车次。",
            )
        elif tickets and len(tickets) <= 30:
            self._set_all_trains(True)

    def _on_query_failed(self, message: str) -> None:
        self.query_btn.setEnabled(True)
        self.query_status.setText("查询失败")
        QMessageBox.critical(self, "查票失败", message)

    def _append_train_row(self, ticket: TrainTicket) -> None:
        row = self.train_table.rowCount()
        self.train_table.insertRow(row)

        check_item = QTableWidgetItem()
        check_item.setFlags(
            Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
        )
        check_item.setCheckState(Qt.CheckState.Unchecked)
        check_item.setData(Qt.ItemDataRole.UserRole, ticket)

        seat_values = [format_seat_display(ticket.seats.get(seat, "--")) for seat in QUERY_SEAT_COLUMNS]
        values = [
            ticket.travel_date,
            ticket.train_code,
            ticket.from_station_name,
            ticket.to_station_name,
            ticket.start_time,
            ticket.arrive_time,
            ticket.duration,
            *seat_values,
        ]
        self.train_table.setItem(row, 0, check_item)
        for col, val in enumerate(values, start=1):
            item = QTableWidgetItem(val)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            raw_seat = ticket.seats.get(QUERY_SEAT_COLUMNS[col - 8], "--") if col >= 8 else ""
            if col >= 8 and seat_has_stock_display(raw_seat):
                item.setBackground(QColor("#d5f5e3"))
            elif col < 8 and col in (3, 4):
                item.setToolTip(f"站码: {ticket.from_station if col == 3 else ticket.to_station}")
            self.train_table.setItem(row, col, item)

    def _set_all_trains(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.train_table.rowCount()):
            item = self.train_table.item(row, 0)
            if item:
                item.setCheckState(state)

    def get_selected_train_codes(self) -> list[str]:
        codes: list[str] = []
        for row in range(self.train_table.rowCount()):
            item = self.train_table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                ticket = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(ticket, TrainTicket):
                    codes.append(ticket.train_code)
                else:
                    code_item = self.train_table.item(row, 2)
                    if code_item:
                        codes.append(code_item.text())
        return codes

    def _load_passengers(self) -> None:
        self.passenger_list.clear()
        with get_session() as session:
            for p in session.query(Passenger).all():
                item = QListWidgetItem(f"{p.name} ({p.id_no[-4:]})")
                item.setData(Qt.ItemDataRole.UserRole, p.id)
                self.passenger_list.addItem(item)
                if p.is_default:
                    item.setSelected(True)

    def _load_last_config(self) -> None:
        with get_session() as session:
            tc = (
                session.query(TaskConfig)
                .filter_by(name="当前任务", is_active=True)
                .order_by(TaskConfig.created_at.desc())
                .first()
            )
            if not tc:
                return

            if tc.from_station_name:
                self.from_combo.setCurrentText(tc.from_station_name)
            if tc.to_station_name:
                self.to_combo.setCurrentText(tc.to_station_name)

            self.date_list.clear()
            for date_text in tc.travel_date.split(","):
                date_text = date_text.strip()
                if date_text:
                    self.date_list.addItem(date_text)

            for seat, cb in self.seat_checks.items():
                cb.setChecked(seat in (tc.seat_types or ""))

            self.interval_spin.setValue(float(tc.poll_interval or 3))
            self.waitlist_cb.setChecked(bool(tc.enable_waitlist))
            self.auto_submit_cb.setChecked(bool(tc.auto_submit))

            if tc.train_codes:
                self._saved_train_codes = [
                    code.strip() for code in tc.train_codes.split(",") if code.strip()
                ]

            if tc.passenger_ids:
                selected_ids = {
                    int(pid)
                    for pid in tc.passenger_ids.split(",")
                    if pid.strip().isdigit()
                }
                for i in range(self.passenger_list.count()):
                    item = self.passenger_list.item(i)
                    item.setSelected(item.data(Qt.ItemDataRole.UserRole) in selected_ids)

    def _add_passenger_dialog(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("添加乘车人")
        form = QFormLayout(dlg)
        name_edit = QLineEdit()
        id_edit = QLineEdit()
        phone_edit = QLineEdit()
        form.addRow("姓名", name_edit)
        form.addRow("身份证号", id_edit)
        form.addRow("手机号", phone_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec():
            with get_session() as session:
                p = Passenger(
                    account_id=1,
                    name=name_edit.text().strip(),
                    id_no=id_edit.text().strip(),
                    phone=phone_edit.text().strip(),
                )
                session.add(p)
            self._load_passengers()

    def _resolve_codes(self, from_name: str, to_name: str) -> tuple[str, str]:
        try:
            from_code = self.client.resolve_station_code(from_name, self._stations)
            to_code = self.client.resolve_station_code(to_name, self._stations)
        except Exception:
            from_code = self._stations.get(from_name, from_name)
            to_code = self._stations.get(to_name, to_name)
        return from_code, to_code

    def _save_config(self) -> None:
        from_name = self.from_combo.currentText().strip()
        to_name = self.to_combo.currentText().strip()
        from_code, to_code = self._resolve_codes(from_name, to_name)
        dates = self.get_travel_dates()
        seats = [s for s, cb in self.seat_checks.items() if cb.isChecked()]
        trains = self.get_selected_train_codes()
        selected = [
            self.passenger_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.passenger_list.count())
            if self.passenger_list.item(i).isSelected()
        ]
        config = {
            "from_station": from_code,
            "from_station_name": from_name,
            "to_station": to_code,
            "to_station_name": to_name,
            "travel_date": ",".join(dates),
            "train_codes": ",".join(trains),
            "seat_types": ",".join(seats),
            "passenger_ids": ",".join(str(x) for x in selected),
            "poll_interval": self.interval_spin.value(),
            "enable_waitlist": self.waitlist_cb.isChecked(),
            "auto_submit": self.auto_submit_cb.isChecked(),
        }
        self._saved_train_codes = list(trains)
        with get_session() as session:
            tc = session.query(TaskConfig).filter_by(name="当前任务").first()
            if tc:
                for key, value in config.items():
                    setattr(tc, key, value)
                tc.is_active = True
            else:
                session.add(TaskConfig(**config, name="当前任务"))
        self.saved.emit(config)

    def get_monitor_config(self) -> dict | None:
        from_name = self.from_combo.currentText().strip()
        to_name = self.to_combo.currentText().strip()
        dates = self.get_travel_dates()
        if not from_name or not to_name or not dates:
            return None
        from_code, to_code = self._resolve_codes(from_name, to_name)
        seats = [s for s, cb in self.seat_checks.items() if cb.isChecked()]
        trains = self.get_selected_train_codes()
        if not trains and self._saved_train_codes:
            trains = list(self._saved_train_codes)
        selected = [
            self.passenger_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.passenger_list.count())
            if self.passenger_list.item(i).isSelected()
        ]
        return {
            "from_code": from_code,
            "to_code": to_code,
            "from_name": from_name,
            "to_name": to_name,
            "travel_dates": dates,
            "train_codes": trains,
            "seat_types": seats or ["二等座"],
            "poll_interval": self.interval_spin.value(),
            "enable_waitlist": self.waitlist_cb.isChecked(),
            "auto_submit": self.auto_submit_cb.isChecked(),
            "passenger_ids": selected,
        }

    def get_primary_travel_date(self) -> str:
        dates = self.get_travel_dates()
        return dates[0] if dates else self.date_edit.date().toString("yyyy-MM-dd")
