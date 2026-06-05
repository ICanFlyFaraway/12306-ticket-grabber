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

        for attempt in range(1, self.max_retries + 1):
            try:
                captcha_code = self._resolve_captcha(on_captcha)
                ok, msg = self._do_login(username, password, captcha_code)
                if ok:
                    self.client.logged_in = True
                    self.client.username = username
                    return LoginResult(True, msg, username)
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
            if code == "2":
                self.client.logged_in = True
                return LoginResult(True, "扫码登录成功")
            if code in ("3", "4"):
                return LoginResult(False, "二维码已过期或取消")
            time.sleep(poll_interval)
        return LoginResult(False, "扫码超时")

    def check_login(self) -> bool:
        return self.client.check_user() if self.client.logged_in else False

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
            if result.get("result_code") == 0:
                self.client.get("https://kyfw.12306.cn/otn/login/loginAysnSuggest")
                return True, "登录成功"
            return False, result.get("result_message", "登录失败")
        except Exception as exc:
            return False, str(exc)
