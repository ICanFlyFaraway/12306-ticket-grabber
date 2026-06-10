from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.database.db import get_session
from app.database.models import AppSetting
from app.utils.crypto import decrypt_password, encrypt_password


@dataclass
class SmsConfig:
    enabled: bool = False
    phones: str = ""
    provider: str = "mock"
    api_url: str = ""
    access_key_id: str = ""
    access_key_secret: str = ""
    sign_name: str = ""
    template_code: str = ""


def get_setting(key: str, default: str = "") -> str:
    with get_session() as session:
        row = session.get(AppSetting, key)
        return row.value if row else default


def set_setting(key: str, value: str) -> None:
    with get_session() as session:
        row = session.get(AppSetting, key)
        if row:
            row.value = value
            row.updated_at = datetime.now()
        else:
            session.add(AppSetting(key=key, value=value))


def get_sms_config() -> SmsConfig:
    secret_enc = get_setting("sms_access_key_secret", "")
    secret = ""
    if secret_enc:
        try:
            secret = decrypt_password(secret_enc)
        except Exception:
            secret = secret_enc
    return SmsConfig(
        enabled=get_setting("sms_enabled", "0") == "1",
        phones=get_setting("sms_phones", ""),
        provider=get_setting("sms_provider", "mock"),
        api_url=get_setting("sms_api_url", ""),
        access_key_id=get_setting("sms_access_key_id", ""),
        access_key_secret=secret,
        sign_name=get_setting("sms_sign_name", ""),
        template_code=get_setting("sms_template_code", ""),
    )


def save_sms_config(cfg: SmsConfig) -> None:
    set_setting("sms_enabled", "1" if cfg.enabled else "0")
    set_setting("sms_phones", cfg.phones.strip())
    set_setting("sms_provider", cfg.provider)
    set_setting("sms_api_url", cfg.api_url.strip())
    set_setting("sms_access_key_id", cfg.access_key_id.strip())
    if cfg.access_key_secret:
        set_setting("sms_access_key_secret", encrypt_password(cfg.access_key_secret))
    set_setting("sms_sign_name", cfg.sign_name.strip())
    set_setting("sms_template_code", cfg.template_code.strip())


def get_proxy_text() -> str:
    return get_setting("proxy_list", "")


def save_proxy_text(text: str) -> None:
    set_setting("proxy_list", text)


def get_auto_pay() -> bool:
    return get_setting("auto_pay", "0") == "1"


def save_auto_pay(enabled: bool) -> None:
    set_setting("auto_pay", "1" if enabled else "0")
