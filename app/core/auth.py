from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Callable

from app.config import PASSPORT_BASE, USE_MOCK
from app.core.api_client import ApiClient
from app.core.captcha import CaptchaSolver
from app.utils.crypto import md5_hex


@dataclass
class LoginResult:
    success: bool
    message: str
    username: str = ""


class AuthService:
    def __init__(self, client: ApiClient, captcha: CaptchaSolver | None = None) -> None:
        self.client = client
        self.captcha = captcha or CaptchaSolver()
        self.max_retries = 3

    def login_with_password(
        self, username: str, password: str, on_captcha: Callable[[bytes], str] | None = None
    ) -> LoginResult:
        if USE_MOCK:
            if username and password:
                self.client.logged_in = True
                self.client.username = username
                return LoginResult(True, "模拟登录成功", username)
            return LoginResult(False, "用户名或密码不能为空")

        self.client.init_session()
        for attempt in range(1, self.max_retries + 1):
            try:
                captcha_code = self._resolve_captcha(on_captcha)
                ok, msg = self._do_login(username, password, captcha_code)
                if ok:
                    return LoginResult(True, msg, self.client.username or username)
                if "验证码" not in msg:
                    return LoginResult(False, msg)
            except Exception as exc:
                if attempt == self.max_retries:
                    return LoginResult(False, f"登录失败: {exc}")
                time.sleep(1)
        return LoginResult(False, "验证码多次错误，请重试")

    def login_with_qr(
        self,
        poll_interval: float = 2.0,
        timeout: float = 120.0,
        on_qr: Callable[[str, str], None] | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> LoginResult:
        if not USE_MOCK:
            self.client.init_session()
        uuid, image_b64 = self.client.get_qr_code()
        if on_qr:
            on_qr(uuid, image_b64)

        deadline = time.time() + timeout
        while time.time() < deadline:
            if USE_MOCK:
                time.sleep(poll_interval)
                self.client.logged_in = True
                self.client.username = "qr_user"
                return LoginResult(True, "模拟扫码登录成功", "qr_user")

            data = self.client.check_qr_status(uuid)
            code = data.get("result_code", "")
            if on_status:
                on_status(str(code))
            if str(code) == "2":
                uamtk = data.get("uamtk") or ""
                self.client.logged_in = True
                ok, err = self.client.complete_login(uamtk=uamtk or None, qr_login=True)
                if ok:
                    return LoginResult(True, "扫码登录成功", self.client.username or "扫码用户")
                self.client.logged_in = False
                return LoginResult(False, err or "登录令牌换取失败，请重试")
            if str(code) in ("3", "4"):
                return LoginResult(False, "二维码已过期或取消")
            time.sleep(poll_interval)
        return LoginResult(False, "扫码超时")

    def check_login(self) -> bool:
        if not self.client.logged_in:
            return False
        if USE_MOCK:
            return True
        if self.client.check_user():
            return True
        if self.client.refresh_login_status():
            return True
        self.client.logged_in = False
        return False

    def logout(self) -> None:
        self.client.logged_in = False
        self.client.username = ""
        self.client.session.cookies.clear()

    def _resolve_captcha(self, on_captcha: Callable[[bytes], str] | None) -> str:
        if USE_MOCK:
            return "ABCD"
        url = f"{PASSPORT_BASE}/passport/captcha/captcha-image64"
        resp = self.client.post(
            url,
            data={"login_site": "E", "module": "login", "rand": "sjrand", "_": int(time.time() * 1000)},
        )
        data = resp.json()
        img_b64 = data.get("image", "")
        img_bytes = base64.b64decode(img_b64.split(",")[-1])
        if on_captcha:
            return on_captcha(img_bytes)
        return self.captcha.solve_image(img_bytes)

    def _do_login(self, username: str, password: str, captcha: str) -> tuple[bool, str]:
        url = f"{PASSPORT_BASE}/passport/web/login"
        pwd = md5_hex(password)
        data = {
            "username": username,
            "password": pwd,
            "appid": "otn",
            "answer": captcha,
        }
        resp = self.client.post(url, data=data)
        try:
            result = resp.json()
            if str(result.get("result_code", "")) == "0":
                uamtk = result.get("uamtk") or ""
                self.client.logged_in = True
                ok, err = self.client.complete_login(uamtk=uamtk or None, qr_login=False)
                if ok:
                    return True, "登录成功"
                self.client.logged_in = False
                return False, err or "登录令牌换取失败，请重试"
            return False, result.get("result_message", "登录失败")
        except Exception as exc:
            return False, str(exc)
