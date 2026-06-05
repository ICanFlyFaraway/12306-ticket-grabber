from __future__ import annotations

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.core.auth import AuthService, LoginResult
from app.core.captcha import CaptchaSolver
from app.database.db import get_session
from app.database.models import Account
from app.utils.crypto import decrypt_password, encrypt_password


class LoginWorker(QThread):
    finished = pyqtSignal(object)

    def __init__(self, auth: AuthService, username: str, password: str) -> None:
        super().__init__()
        self.auth = auth
        self.username = username
        self.password = password

    def run(self) -> None:
        result = self.auth.login_with_password(self.username, self.password)
        self.finished.emit(result)


class QRLoginWorker(QThread):
    qr_ready = pyqtSignal(str, str)
    status_update = pyqtSignal(str)
    finished = pyqtSignal(object)

    def __init__(self, auth: AuthService) -> None:
        super().__init__()
        self.auth = auth

    def run(self) -> None:
        result = self.auth.login_with_qr(
            on_qr=lambda uid, img: self.qr_ready.emit(uid, img),
            on_status=lambda s: self.status_update.emit(s),
        )
        self.finished.emit(result)


class LoginPanel(QWidget):
    login_success = pyqtSignal(str)
    login_failed = pyqtSignal(str)

    def __init__(self, auth: AuthService, parent=None) -> None:
        super().__init__(parent)
        self.auth = auth
        self._worker: LoginWorker | None = None
        self._qr_worker: QRLoginWorker | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)
        tabs = QTabWidget()

        pwd_widget = QWidget()
        pwd_form = QFormLayout(pwd_widget)
        self.username_edit = QLineEdit()
        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        pwd_form.addRow("用户名", self.username_edit)
        pwd_form.addRow("密码", self.password_edit)

        remember_row = QHBoxLayout()
        self.remember_cb = QPushButton("记住账号")
        self.remember_cb.setCheckable(True)
        self.remember_cb.setChecked(True)
        remember_row.addWidget(self.remember_cb)
        remember_row.addStretch()
        pwd_form.addRow(remember_row)

        login_btn = QPushButton("密码登录")
        login_btn.clicked.connect(self._do_password_login)
        pwd_form.addRow(login_btn)
        tabs.addTab(pwd_widget, "密码登录")

        qr_widget = QWidget()
        qr_layout = QVBoxLayout(qr_widget)
        self.qr_label = QLabel("点击获取二维码")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumHeight(200)
        self.qr_status = QLabel("")
        self.qr_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_btn = QPushButton("获取扫码登录二维码")
        qr_btn.clicked.connect(self._do_qr_login)
        qr_layout.addWidget(self.qr_label)
        qr_layout.addWidget(self.qr_status)
        qr_layout.addWidget(qr_btn)
        tabs.addTab(qr_widget, "扫码登录")

        layout.addWidget(tabs)

        status_group = QGroupBox("登录状态")
        status_layout = QVBoxLayout(status_group)
        self.status_label = QLabel("未登录")
        self.status_label.setStyleSheet("color: #c0392b; font-weight: bold;")
        status_layout.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        check_btn = QPushButton("检查登录")
        check_btn.clicked.connect(self._check_login)
        logout_btn = QPushButton("退出登录")
        logout_btn.clicked.connect(self._logout)
        btn_row.addWidget(check_btn)
        btn_row.addWidget(logout_btn)
        status_layout.addLayout(btn_row)
        layout.addWidget(status_group)

        captcha_info = QLabel(
            f"验证码识别: {'可用 (ddddocr)' if CaptchaSolver.is_available() else '未安装 ddddocr'}"
        )
        captcha_info.setStyleSheet("color: gray; font-size: 12px;")
        layout.addWidget(captcha_info)
        layout.addStretch()
        self._load_saved_account()

    def _load_saved_account(self) -> None:
        with get_session() as session:
            acc = session.query(Account).filter_by(is_active=True).first()
            if acc:
                self.username_edit.setText(acc.username)
                try:
                    self.password_edit.setText(decrypt_password(acc.password_enc))
                except Exception:
                    pass

    def _save_account(self, username: str, password: str) -> None:
        with get_session() as session:
            acc = session.query(Account).filter_by(username=username).first()
            enc = encrypt_password(password)
            if acc:
                acc.password_enc = enc
            else:
                session.add(Account(username=username, password_enc=enc))

    def _do_password_login(self) -> None:
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            QMessageBox.warning(self, "提示", "请输入用户名和密码")
            return
        self.status_label.setText("登录中...")
        self._worker = LoginWorker(self.auth, username, password)
        self._worker.finished.connect(lambda r: self._on_login_result(r, username, password))
        self._worker.start()

    def _do_qr_login(self) -> None:
        self.qr_status.setText("等待扫码...")
        self._qr_worker = QRLoginWorker(self.auth)
        self._qr_worker.qr_ready.connect(self._on_qr_ready)
        self._qr_worker.status_update.connect(lambda s: self.qr_status.setText(f"状态: {s}"))
        self._qr_worker.finished.connect(self._on_qr_login_result)
        self._qr_worker.start()

    def _on_qr_ready(self, uid: str, image_b64: str) -> None:
        if image_b64:
            import base64
            from PyQt6.QtCore import QByteArray

            data = QByteArray(base64.b64decode(image_b64))
            pixmap = QPixmap()
            pixmap.loadFromData(data)
            self.qr_label.setPixmap(pixmap.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio))
        else:
            self.qr_label.setText(f"模拟二维码\nUUID: {uid[:8]}...")

    def _on_login_result(self, result: LoginResult, username: str, password: str) -> None:
        if result.success:
            if self.remember_cb.isChecked():
                self._save_account(username, password)
            self._set_logged_in(result.username or username, result.message)
        else:
            self.status_label.setText(f"登录失败: {result.message}")
            self.status_label.setStyleSheet("color: #c0392b; font-weight: bold;")
            self.login_failed.emit(result.message)

    def _on_qr_login_result(self, result: LoginResult) -> None:
        if result.success:
            self._set_logged_in(result.username or "扫码用户", result.message)
        else:
            self.qr_status.setText(result.message)
            self.login_failed.emit(result.message)

    def _set_logged_in(self, username: str, message: str) -> None:
        self.status_label.setText(f"已登录: {username} ({message})")
        self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        self.login_success.emit(username)

    def _check_login(self) -> None:
        if self.auth.check_login():
            self.status_label.setText(f"已登录: {self.auth.client.username}")
            self.status_label.setStyleSheet("color: #27ae60; font-weight: bold;")
        else:
            self.status_label.setText("登录已失效，请重新登录")
            self.status_label.setStyleSheet("color: #c0392b; font-weight: bold;")

    def _logout(self) -> None:
        self.auth.logout()
        self.status_label.setText("未登录")
        self.status_label.setStyleSheet("color: #c0392b; font-weight: bold;")
