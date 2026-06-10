from __future__ import annotations

from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.proxy_pool import ProxyPool
from app.core.settings_store import (
    SmsConfig,
    get_auto_pay,
    get_proxy_text,
    get_sms_config,
    save_auto_pay,
    save_proxy_text,
    save_sms_config,
)


class SettingsPanel(QWidget):
    def __init__(self, proxy_pool: ProxyPool, parent=None) -> None:
        super().__init__(parent)
        self.proxy_pool = proxy_pool
        self._build_ui()
        self._load_settings()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        proxy_group = QGroupBox("代理 IP 池")
        proxy_layout = QVBoxLayout(proxy_group)
        proxy_layout.addWidget(QLabel("每行一个代理地址，格式: http://ip:port"))
        self.proxy_edit = QPlainTextEdit()
        self.proxy_edit.setPlaceholderText("# 示例\n# http://127.0.0.1:7890")
        self.proxy_edit.setMaximumHeight(120)
        proxy_layout.addWidget(self.proxy_edit)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("保存代理")
        save_btn.clicked.connect(self._save_proxies)
        reset_btn = QPushButton("重置状态")
        reset_btn.clicked.connect(self.proxy_pool.reset_all)
        btn_row.addWidget(save_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addStretch()
        proxy_layout.addLayout(btn_row)

        self.proxy_count_label = QLabel("当前可用代理: 0")
        proxy_layout.addWidget(self.proxy_count_label)
        layout.addWidget(proxy_group)

        sms_group = QGroupBox("抢票成功短信通知")
        sms_layout = QVBoxLayout(sms_group)

        self.sms_enabled_cb = QCheckBox("启用短信通知")
        sms_layout.addWidget(self.sms_enabled_cb)

        form = QFormLayout()
        self.sms_phones_edit = QLineEdit()
        self.sms_phones_edit.setPlaceholderText("多个手机号用英文逗号分隔，如 13800138000,13900139000")
        form.addRow("通知手机号", self.sms_phones_edit)

        self.sms_provider_combo = QComboBox()
        self.sms_provider_combo.addItem("模拟发送（测试）", "mock")
        self.sms_provider_combo.addItem("HTTP 接口", "http")
        self.sms_provider_combo.addItem("阿里云短信", "aliyun")
        self.sms_provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form.addRow("发送方式", self.sms_provider_combo)
        sms_layout.addLayout(form)

        self.provider_stack = QStackedWidget()
        self.provider_stack.addWidget(self._build_mock_page())
        self.provider_stack.addWidget(self._build_http_page())
        self.provider_stack.addWidget(self._build_aliyun_page())
        sms_layout.addWidget(self.provider_stack)

        sms_btn_row = QHBoxLayout()
        save_sms_btn = QPushButton("保存短信配置")
        save_sms_btn.clicked.connect(self._save_sms)
        sms_btn_row.addWidget(save_sms_btn)
        sms_btn_row.addStretch()
        sms_layout.addLayout(sms_btn_row)
        self.sms_status_label = QLabel("")
        self.sms_status_label.setStyleSheet("color: gray;")
        sms_layout.addWidget(self.sms_status_label)
        layout.addWidget(sms_group)

        pay_group = QGroupBox("支付设置")
        pay_form = QFormLayout(pay_group)
        self.auto_pay_cb = QPushButton("自动支付（实验性）")
        self.auto_pay_cb.setCheckable(True)
        self.auto_pay_cb.toggled.connect(lambda _: self._save_auto_pay())
        pay_form.addRow("自动支付", self.auto_pay_cb)
        layout.addWidget(pay_group)

        about_group = QGroupBox("关于")
        about_layout = QVBoxLayout(about_group)
        about_layout.addWidget(
            QLabel(
                "12306抢票助手 v1.0\n"
                "短信支持：模拟 / HTTP 自定义接口 / 阿里云短信\n"
                "设置环境变量 TICKET_MOCK=1 可启用模拟模式"
            )
        )
        layout.addWidget(about_group)
        layout.addStretch()

    def _build_mock_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addWidget(QLabel("模拟模式仅记录日志，不实际发送短信，用于测试流程。"))
        return page

    def _build_http_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.sms_api_url_edit = QLineEdit()
        self.sms_api_url_edit.setPlaceholderText("https://your-server.com/api/sms")
        form.addRow("接口地址", self.sms_api_url_edit)
        hint = QLabel(
            "POST JSON: {\"phone\":\"手机号\",\"message\":\"短信内容\"}\n"
            "可使用自建服务对接任意短信网关。"
        )
        hint.setStyleSheet("color: gray; font-size: 12px;")
        form.addRow(hint)
        return page

    def _build_aliyun_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.sms_access_key_edit = QLineEdit()
        self.sms_secret_edit = QLineEdit()
        self.sms_secret_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.sms_sign_edit = QLineEdit()
        self.sms_template_edit = QLineEdit()
        form.addRow("AccessKey ID", self.sms_access_key_edit)
        form.addRow("AccessKey Secret", self.sms_secret_edit)
        form.addRow("短信签名", self.sms_sign_edit)
        form.addRow("模板 Code", self.sms_template_edit)
        hint = QLabel(
            "模板变量: train, from, to, date, seat, order, msg\n"
            "请在阿里云控制台创建对应短信模板。"
        )
        hint.setStyleSheet("color: gray; font-size: 12px;")
        form.addRow(hint)
        return page

    def _on_provider_changed(self) -> None:
        self.provider_stack.setCurrentIndex(self.sms_provider_combo.currentIndex())

    def _load_settings(self) -> None:
        self._load_sms_config()
        self.proxy_edit.setPlainText(get_proxy_text())
        if self.proxy_edit.toPlainText().strip():
            count = self.proxy_pool.load_from_text(self.proxy_edit.toPlainText())
            self.proxy_count_label.setText(f"当前可用代理: {self.proxy_pool.count} (已加载 {count})")
        else:
            self.proxy_count_label.setText(f"当前可用代理: {self.proxy_pool.count}")
        self.auto_pay_cb.setChecked(get_auto_pay())

    def _load_sms_config(self) -> None:
        cfg = get_sms_config()
        self.sms_enabled_cb.setChecked(cfg.enabled)
        self.sms_phones_edit.setText(cfg.phones)
        idx = max(0, self.sms_provider_combo.findData(cfg.provider))
        self.sms_provider_combo.setCurrentIndex(idx)
        self.sms_api_url_edit.setText(cfg.api_url)
        self.sms_access_key_edit.setText(cfg.access_key_id)
        self.sms_secret_edit.setText(cfg.access_key_secret)
        self.sms_sign_edit.setText(cfg.sign_name)
        self.sms_template_edit.setText(cfg.template_code)
        self._on_provider_changed()

    def _save_sms(self) -> None:
        cfg = SmsConfig(
            enabled=self.sms_enabled_cb.isChecked(),
            phones=self.sms_phones_edit.text(),
            provider=self.sms_provider_combo.currentData(),
            api_url=self.sms_api_url_edit.text(),
            access_key_id=self.sms_access_key_edit.text(),
            access_key_secret=self.sms_secret_edit.text(),
            sign_name=self.sms_sign_edit.text(),
            template_code=self.sms_template_edit.text(),
        )
        save_sms_config(cfg)
        self.sms_status_label.setText("短信配置已保存")

    def _save_proxies(self) -> None:
        text = self.proxy_edit.toPlainText()
        save_proxy_text(text)
        count = self.proxy_pool.load_from_text(text)
        self.proxy_count_label.setText(f"当前可用代理: {self.proxy_pool.count} (新增 {count})")

    def _save_auto_pay(self) -> None:
        save_auto_pay(self.auto_pay_cb.isChecked())

    def is_auto_pay(self) -> bool:
        return self.auto_pay_cb.isChecked()

    def is_sms_enabled(self) -> bool:
        return self.sms_enabled_cb.isChecked()
