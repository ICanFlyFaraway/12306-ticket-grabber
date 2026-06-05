from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from app.config import USE_MOCK
from app.core.api_client import TrainTicket
from app.core.settings_store import SmsConfig, get_sms_config

logger = logging.getLogger(__name__)


class SmsService:
    def __init__(self, config: SmsConfig | None = None) -> None:
        self.config = config or get_sms_config()

    def reload_config(self) -> None:
        self.config = get_sms_config()

    def send_ticket_success(
        self,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str = "",
        travel_date: str = "",
    ) -> list[str]:
        self.reload_config()
        if not self.config.enabled:
            return ["短信通知未启用"]
        phones = self._parse_phones(self.config.phones)
        if not phones:
            return ["未配置通知手机号"]

        message = self._build_message(order_id, ticket, seat_type, travel_date)
        results: list[str] = []
        for phone in phones:
            try:
                ok, detail = self._send_one(phone, message, order_id, ticket, seat_type, travel_date)
                results.append(f"{phone}: {'成功' if ok else detail}")
            except Exception as exc:
                results.append(f"{phone}: 失败 - {exc}")
        return results

    def _parse_phones(self, raw: str) -> list[str]:
        phones = []
        for part in raw.replace("，", ",").split(","):
            p = part.strip()
            if p and p.isdigit() and len(p) == 11:
                phones.append(p)
        return phones

    def _build_message(
        self,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str,
        travel_date: str,
    ) -> str:
        if not ticket:
            return f"【12306抢票】下单成功，订单号{order_id}，请30分钟内登录12306完成支付。"
        date = travel_date or ticket.travel_date
        seat = seat_type or "车票"
        return (
            f"【12306抢票】抢票成功！{date} {ticket.train_code} "
            f"{ticket.from_station_name}→{ticket.to_station_name} {seat}，"
            f"订单号{order_id}，请30分钟内完成支付。"
        )

    def _send_one(
        self,
        phone: str,
        message: str,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str,
        travel_date: str,
    ) -> tuple[bool, str]:
        provider = self.config.provider
        if provider == "mock" or (USE_MOCK and provider != "http" and provider != "aliyun"):
            logger.info("SMS mock -> %s: %s", phone, message)
            return True, "模拟发送成功"

        if provider == "http":
            return self._send_http(phone, message)

        if provider == "aliyun":
            return self._send_aliyun(phone, order_id, ticket, seat_type, travel_date, message)

        return False, f"未知短信通道: {provider}"

    def _send_http(self, phone: str, message: str) -> tuple[bool, str]:
        url = self.config.api_url.strip()
        if not url:
            return False, "未配置 HTTP 接口地址"
        payload = {"phone": phone, "phones": [phone], "message": message, "content": message}
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
        return True, resp.text[:120]

    def _send_aliyun(
        self,
        phone: str,
        order_id: str,
        ticket: TrainTicket | None,
        seat_type: str,
        travel_date: str,
        message: str,
    ) -> tuple[bool, str]:
        if not all(
            [
                self.config.access_key_id,
                self.config.access_key_secret,
                self.config.sign_name,
                self.config.template_code,
            ]
        ):
            return False, "阿里云短信参数不完整"

        template_param = {
            "train": ticket.train_code if ticket else "",
            "from": ticket.from_station_name if ticket else "",
            "to": ticket.to_station_name if ticket else "",
            "date": travel_date or (ticket.travel_date if ticket else ""),
            "seat": seat_type,
            "order": order_id,
            "msg": message,
        }
        params: dict[str, str] = {
            "Action": "SendSms",
            "Format": "JSON",
            "Version": "2017-05-25",
            "AccessKeyId": self.config.access_key_id,
            "SignatureMethod": "HMAC-SHA1",
            "Timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "SignatureVersion": "1.0",
            "SignatureNonce": str(uuid.uuid4()),
            "PhoneNumbers": phone,
            "SignName": self.config.sign_name,
            "TemplateCode": self.config.template_code,
            "TemplateParam": json.dumps(template_param, ensure_ascii=False),
        }
        params["Signature"] = self._aliyun_sign(params, self.config.access_key_secret)
        resp = requests.get("https://dysmsapi.aliyuncs.com/", params=params, timeout=15)
        data = resp.json()
        if data.get("Code") == "OK":
            return True, "OK"
        return False, data.get("Message", str(data))

    @staticmethod
    def _aliyun_sign(params: dict[str, str], secret: str) -> str:
        sorted_params = sorted(params.items())
        query = "&".join(f"{quote(k, safe='')}={quote(str(v), safe='')}" for k, v in sorted_params)
        string_to_sign = f"GET&{quote('/', safe='')}&{quote(query, safe='')}"
        digest = hmac.new(
            (secret + "&").encode(),
            string_to_sign.encode(),
            hashlib.sha1,
        ).digest()
        return base64.b64encode(digest).decode()
