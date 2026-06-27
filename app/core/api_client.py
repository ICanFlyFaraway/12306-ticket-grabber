from __future__ import annotations

import json
import random
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

import requests

from app.config import DEFAULT_HEADERS, KYFW_BASE, PASSPORT_BASE, SEAT_TYPES, USE_MOCK
from app.core.proxy_pool import ProxyPool
from app.core.station_registry import resolve_station_code as lookup_station_code


@dataclass
class TrainTicket:
    train_code: str
    from_station: str
    to_station: str
    from_station_name: str
    to_station_name: str
    start_time: str
    arrive_time: str
    duration: str
    can_web_buy: str
    secret_str: str
    travel_date: str = ""
    seats: dict[str, str] = field(default_factory=dict)


class ApiClient:
    """12306 HTTP 客户端，支持代理与 Mock 模式。"""

    def __init__(self, proxy_pool: ProxyPool | None = None) -> None:
        self.proxy_pool = proxy_pool or ProxyPool()
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self._cookies: dict[str, str] = {}
        self.logged_in = False
        self.username = ""
        self._query_path: str | None = None
        self._station_cache: dict[str, str] = {}

    def _proxies(self) -> dict[str, str] | None:
        proxy = self.proxy_pool.get_proxy()
        if not proxy:
            return None
        return {"http": proxy, "https": proxy}

    def get(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 15)
        kwargs.setdefault("proxies", self._proxies())
        return self.session.get(url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 15)
        kwargs.setdefault("proxies", self._proxies())
        return self.session.post(url, **kwargs)

    def init_session(self, force_real: bool = False) -> None:
        if USE_MOCK and not force_real:
            self._cookies["mock_session"] = "1"
            return
        resp = self.get(f"{KYFW_BASE}/otn/leftTicket/init")
        self._query_path = self._parse_query_path(resp.text)
        self.get(f"{KYFW_BASE}/otn/login/init")
        self.get(f"{KYFW_BASE}/otn/resources/login.html")
        self.post(f"{KYFW_BASE}/passport/web/auth/uamtk-static", data={"appid": "otn"})

    def resolve_station_code(self, name: str, local_map: dict[str, str] | None = None) -> str:
        """将站名解析为电报码，使用本地 + 12306 全量站名表。"""
        name = name.strip()
        if not name:
            raise ValueError("站名不能为空")
        if name in self._station_cache:
            return self._station_cache[name]
        code = lookup_station_code(name, local_map)
        self._station_cache[name] = code
        return code

    def _parse_query_path(self, html: str) -> str:
        patterns = [
            r"['\"](/otn/leftTicket/query[A-Z]?)['\"]",
            r"CLeftTicketUrl\s*=\s*['\"]([^'\"]+)['\"]",
        ]
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                path = match.group(1)
                if not path.startswith("/"):
                    path = f"/otn/{path.lstrip('/')}"
                if "leftTicket" in path:
                    return path.split("?")[0]
        return "/otn/leftTicket/queryG"

    def _ensure_query_path(self) -> str:
        if self._query_path:
            return self._query_path
        if USE_MOCK:
            self.init_session(force_real=True)
        else:
            resp = self.get(f"{KYFW_BASE}/otn/leftTicket/init")
            self._query_path = self._parse_query_path(resp.text)
        return self._query_path or "/otn/leftTicket/queryG"

    def _validate_travel_date(self, travel_date: str) -> None:
        try:
            target = datetime.strptime(travel_date, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValueError(f"日期格式无效: {travel_date}") from exc
        today = date.today()
        if target < today:
            raise ValueError(f"日期 {travel_date} 已过期，请选择今天及之后的日期")
        if target > today + timedelta(days=15):
            raise ValueError(
                f"日期 {travel_date} 超出预售期（12306 通常仅预售 15 天内车票）"
            )

    def _parse_query_json(self, resp: requests.Response, travel_date: str) -> dict[str, Any]:
        content_type = (resp.headers.get("content-type") or "").lower()
        text = resp.text.strip()
        if not text:
            raise RuntimeError(f"日期 {travel_date} 查询无响应，请稍后重试")
        if "json" not in content_type:
            raise RuntimeError(
                f"日期 {travel_date} 无法查询（可能已过期或超出预售期），请检查日期"
            )
        try:
            return resp.json()
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"日期 {travel_date} 响应异常，请确认日期在预售期内并重试"
            ) from exc

    def query_tickets(
        self,
        from_code: str,
        to_code: str,
        travel_date: str,
        force_real: bool = False,
    ) -> list[TrainTicket]:
        if USE_MOCK and not force_real:
            return self._mock_tickets(from_code, to_code, travel_date)

        self._validate_travel_date(travel_date)

        paths = [self._ensure_query_path(), "/otn/leftTicket/queryG", "/otn/leftTicket/queryZ"]
        seen: set[str] = set()
        paths = [p for p in paths if not (p in seen or seen.add(p))]

        params = {
            "leftTicketDTO.train_date": travel_date,
            "leftTicketDTO.from_station": from_code,
            "leftTicketDTO.to_station": to_code,
            "purpose_codes": "ADULT",
        }
        last_error: Exception | None = None
        for path in paths:
            try:
                resp = self.get(f"{KYFW_BASE}{path}", params=params)
                resp.raise_for_status()
                data = self._parse_query_json(resp, travel_date)
                if data.get("status") is not True:
                    msgs = data.get("messages") or data.get("message") or ["查票失败"]
                    raise RuntimeError(msgs[0] if isinstance(msgs, list) else str(msgs))
                self._query_path = path
                result: list[TrainTicket] = []
                station_map = data.get("data", {}).get("map", {})
                for row in data.get("data", {}).get("result", []):
                    ticket = self._parse_ticket_row(row, station_map, travel_date)
                    if ticket:
                        result.append(ticket)
                return result
            except Exception as exc:
                last_error = exc
                continue
        raise RuntimeError(f"查票失败: {last_error}")

    def query_tickets_multi_dates(
        self,
        from_code: str,
        to_code: str,
        travel_dates: list[str],
        force_real: bool = True,
    ) -> tuple[list[TrainTicket], list[str]]:
        all_tickets: list[TrainTicket] = []
        warnings: list[str] = []
        for travel_date in travel_dates:
            try:
                tickets = self.query_tickets(
                    from_code, to_code, travel_date, force_real=force_real
                )
                all_tickets.extend(tickets)
            except Exception as exc:
                warnings.append(str(exc))
        if not all_tickets and warnings:
            raise RuntimeError("\n".join(warnings))
        return all_tickets, warnings

    def _parse_ticket_row(
        self, row: str, station_map: dict, travel_date: str = ""
    ) -> TrainTicket | None:
        parts = row.split("|")
        if len(parts) < 35:
            return None
        from_code = parts[6]
        to_code = parts[7]
        start_time = parts[8]
        arrive_time = parts[9]
        duration = parts[10]
        if not is_valid_train_schedule(start_time, arrive_time, duration):
            return None
        return TrainTicket(
            train_code=parts[3],
            from_station=from_code,
            to_station=to_code,
            from_station_name=station_map.get(from_code, from_code),
            to_station_name=station_map.get(to_code, to_code),
            start_time=start_time,
            arrive_time=arrive_time,
            duration=duration,
            can_web_buy=parts[11],
            secret_str=parts[0] if parts[0] else parts[2],
            travel_date=travel_date,
            seats={
                "商务座": parts[32] or "--",
                "一等座": parts[31] or "--",
                "二等座": parts[30] or "--",
                "高级软卧": parts[21] or "--",
                "软卧": parts[23] or "--",
                "硬卧": parts[28] or "--",
                "软座": parts[24] or "--",
                "硬座": parts[29] or "--",
                "无座": parts[26] or "--",
            },
        )

    def _mock_tickets(
        self, from_code: str, to_code: str, travel_date: str
    ) -> list[TrainTicket]:
        trains = [
            ("G101", "06:30", "11:45", "5:15"),
            ("G103", "07:00", "12:10", "5:10"),
            ("D321", "08:15", "14:20", "6:05"),
            ("K571", "20:30", "08:15", "11:45"),
        ]
        result = []
        for code, start, arrive, duration in trains:
            seats = {
                "商务座": random.choice(["无", "3", "8"]),
                "一等座": random.choice(["无", "5", "12"]),
                "二等座": random.choice(["无", "有", "15", "0"]),
                "硬卧": random.choice(["无", "4", "有"]),
                "硬座": random.choice(["无", "有", "20"]),
                "无座": random.choice(["无", "有"]),
            }
            result.append(
                TrainTicket(
                    train_code=code,
                    from_station=from_code,
                    to_station=to_code,
                    from_station_name="出发",
                    to_station_name="到达",
                    start_time=start,
                    arrive_time=arrive,
                    duration=duration,
                    can_web_buy="Y",
                    secret_str=f"mock_secret_{code}_{travel_date}",
                    travel_date=travel_date,
                    seats=seats,
                )
            )
        return result

    def _set_uamtk_cookie(self, uamtk: str) -> None:
        if not uamtk:
            return
        self.session.cookies.update({"uamtk": uamtk})

    def complete_login(self, uamtk: str | None = None, qr_login: bool = False) -> tuple[bool, str]:
        """登录成功后换取 kyfw 侧 apptk，建立可校验的会话。"""
        if USE_MOCK:
            return self.logged_in, ""

        login_headers = {
            **DEFAULT_HEADERS,
            "Referer": f"{KYFW_BASE}/otn/resources/login.html",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        client_headers = {
            **login_headers,
            "Referer": f"{KYFW_BASE}/otn/passport?redirect=/otn/login/userLogin",
        }

        if uamtk:
            self._set_uamtk_cookie(uamtk)

        # 密码登录才需要 userLogin 桥接；扫码登录 checkqr 成功后直接换票
        if not qr_login:
            self.post(
                f"{KYFW_BASE}/otn/login/userLogin",
                data={"_json_att": ""},
                headers=login_headers,
            )

        resp = self.post(
            f"{KYFW_BASE}/passport/web/auth/uamtk",
            data={"appid": "otn"},
            headers=login_headers,
        )
        try:
            data = resp.json()
        except Exception:
            return False, "uamtk 响应解析失败"
        if str(data.get("result_code", "")) != "0":
            msg = data.get("result_message") or "uamtk 验证失败"
            return False, str(msg)
        apptk = data.get("newapptk") or data.get("apptk")
        if not apptk:
            return False, "未获取到 newapptk"

        resp2 = self.post(
            f"{KYFW_BASE}/otn/uamauthclient",
            data={"tk": apptk},
            headers=client_headers,
        )
        try:
            result = resp2.json()
        except Exception:
            return False, "uamauthclient 响应解析失败"
        if str(result.get("result_code", "")) != "0":
            msg = result.get("result_message") or "客户端验证失败"
            return False, str(msg)

        username = result.get("username")
        if username:
            self.username = str(username)

        self.post(f"{KYFW_BASE}/otn/login/conf", headers=login_headers)
        return True, ""

    def refresh_login_status(self) -> bool:
        """尝试刷新登录态，用于检查登录前恢复会话。"""
        if USE_MOCK:
            return self.logged_in
        if not self.logged_in:
            return False
        ok, _ = self.complete_login(qr_login=True)
        if ok and self.check_user():
            return True
        ok, _ = self.complete_login(qr_login=False)
        return ok and self.check_user()

    def check_user(self) -> bool:
        if USE_MOCK:
            return self.logged_in
        url = f"{KYFW_BASE}/otn/login/checkUser"
        resp = self.post(url, data={"_json_att": ""})
        try:
            payload = resp.json()
        except Exception:
            return False
        data = payload.get("data")
        if isinstance(data, dict):
            flag = data.get("flag")
            if flag is True or flag in (1, "1", "Y", "y", "true"):
                return True
        if data is True or data == "1":
            return True
        return False

    @staticmethod
    def normalize_station_name(name: str) -> str:
        name = (name or "").strip()
        if name.endswith("站") and len(name) > 1:
            return name[:-1]
        return name

    @staticmethod
    def decode_secret_str(secret_str: str) -> str:
        decoded = (secret_str or "").strip()
        if not decoded:
            return ""
        for _ in range(3):
            next_value = urllib.parse.unquote(decoded)
            if next_value == decoded:
                break
            decoded = next_value
        return decoded

    def back_train_date(self) -> str:
        cookie_date = self.session.cookies.get("_jc_save_toDate")
        return cookie_date or travel_date_fallback()

    def prepare_order_session(self) -> bool:
        if USE_MOCK:
            return self.logged_in
        self.get(f"{KYFW_BASE}/otn/leftTicket/init")
        if self.check_user():
            return True
        return self.refresh_login_status()

    @staticmethod
    def _is_true(value: Any) -> bool:
        if value is True:
            return True
        if value is False or value is None:
            return False
        if isinstance(value, (int, float)):
            return value == 1
        return str(value).lower() in ("true", "1", "y", "yes")

    def parse_submit_order_response(self, resp: dict[str, Any]) -> tuple[bool, str]:
        if not self._is_true(resp.get("status")):
            return False, self._api_error(resp, "预提交失败")

        data = resp.get("data")
        if data == "N":
            return True, ""
        if isinstance(data, dict):
            if self._is_true(data.get("submitStatus")):
                return True, ""
            err = data.get("errMsg") or data.get("msg") or data.get("message")
            if err:
                return False, str(err)
        return False, self._api_error(resp, "预提交失败")

    def find_fresh_ticket(
        self,
        from_code: str,
        to_code: str,
        travel_date: str,
        train_code: str,
    ) -> TrainTicket | None:
        tickets = self.query_tickets(from_code, to_code, travel_date, force_real=True)
        for ticket in tickets:
            if ticket.train_code == train_code:
                return ticket
        return None

    def submit_order_request(
        self,
        secret_str: str,
        train_date: str,
        from_name: str,
        to_name: str,
    ) -> dict[str, Any]:
        if USE_MOCK:
            time.sleep(0.3)
            if random.random() < 0.85:
                return {"status": True, "data": "N", "order_id": f"MOCK{int(time.time())}"}
            return {"status": False, "messages": ["模拟下单失败，余票已被抢"]}

        if not self.check_user() and not self.refresh_login_status():
            return {"status": False, "messages": ["登录已失效，请重新登录"]}

        decoded_secret = self.decode_secret_str(secret_str)
        if not decoded_secret:
            return {"status": False, "messages": ["车票信息无效，请重新查票"]}

        from_name = self.normalize_station_name(from_name)
        to_name = self.normalize_station_name(to_name)
        if not from_name or not to_name:
            return {"status": False, "messages": ["出发站或到达站无效"]}

        headers = {
            **DEFAULT_HEADERS,
            "Referer": f"{KYFW_BASE}/otn/leftTicket/init",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }
        data = {
            "secretStr": decoded_secret,
            "train_date": train_date,
            "back_train_date": self.back_train_date(),
            "tour_flag": "dc",
            "purpose_codes": "ADULT",
            "query_from_station_name": from_name,
            "query_to_station_name": to_name,
            "undefined": "",
        }
        resp = self.post(url=f"{KYFW_BASE}/otn/leftTicket/submitOrderRequest", data=data, headers=headers)
        try:
            payload = resp.json()
        except Exception:
            snippet = resp.text[:120].strip()
            if snippet.startswith("<"):
                return {"status": False, "messages": ["预提交返回异常页面，请重新登录"]}
            return {"status": False, "messages": ["预提交响应解析失败"]}
        if not isinstance(payload, dict):
            return {"status": False, "messages": ["预提交响应格式异常"]}
        return payload

    def _confirm_headers(self, referer: str | None = None) -> dict[str, str]:
        return {
            **DEFAULT_HEADERS,
            "Referer": referer or f"{KYFW_BASE}/otn/confirmPassenger/initDc",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

    def _parse_init_dc(self, html: str) -> tuple[str, dict[str, Any]]:
        token_match = re.search(r"globalRepeatSubmitToken\s*=\s*'([^']*)'", html)
        if not token_match:
            raise ValueError("无法获取订单提交令牌，请重新登录")
        idx = html.find("ticketInfoForPassengerForm")
        if idx < 0:
            raise ValueError("无法解析订单页面，请重新查票")
        start = html.find("{", idx)
        depth = 0
        end = start
        for pos, ch in enumerate(html[start:], start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = pos + 1
                    break
        form_text = html[start:end].replace("'", '"')
        form = json.loads(form_text)
        return token_match.group(1), form

    @staticmethod
    def _build_passenger_strings(passengers: list[dict], seat_code: str) -> tuple[str, str]:
        ticket_parts: list[str] = []
        old_parts: list[str] = []
        for index, passenger in enumerate(passengers, 1):
            name = passenger["name"]
            id_no = passenger["id_no"]
            id_type = passenger.get("id_type", "1")
            phone = passenger.get("phone", "")
            ticket_parts.append(f"{seat_code},0,{index},{name},1,{id_type},{id_no},{phone},N")
            old_parts.append(f"{name},1,{id_no},1")
        return "_".join(ticket_parts), "_".join(old_parts) + "_"

    @staticmethod
    def _api_error(payload: dict[str, Any], default: str) -> str:
        messages = payload.get("messages")
        if isinstance(messages, list) and messages:
            return str(messages[0])
        if isinstance(messages, str) and messages:
            return messages
        validate = payload.get("validateMessages") or {}
        if isinstance(validate, dict):
            for value in validate.values():
                if value:
                    return str(value)
        data = payload.get("data")
        if isinstance(data, dict) and data.get("errMsg"):
            return str(data["errMsg"])
        return default

    def complete_booking(
        self,
        passengers: list[dict],
        seat_type: str,
        train_code: str,
    ) -> tuple[bool, str, str]:
        if USE_MOCK:
            return True, "下单成功", f"MOCK{int(time.time())}"

        seat_code = SEAT_TYPES.get(seat_type, "O")
        passenger_ticket, old_passenger = self._build_passenger_strings(passengers, seat_code)

        init_url = f"{KYFW_BASE}/otn/confirmPassenger/initDc"
        init_resp = self.get(
            init_url,
            params={"_json_att": "", "type": "1", "random": str(int(time.time() * 1000))},
            headers=self._confirm_headers(f"{KYFW_BASE}/otn/leftTicket/init"),
        )
        token, form = self._parse_init_dc(init_resp.text)
        query = form.get("queryLeftTicketRequestDTO") or {}
        key_check = form.get("key_check_isChange", "")
        left_ticket = form.get("leftTicketStr", "")
        train_location = form.get("train_location", "")
        confirm_headers = self._confirm_headers()

        check_data = {
            "cancel_flag": "3",
            "bed_level_order_num": "0",
            "passengerTicketStr": passenger_ticket,
            "oldPassengerStr": old_passenger,
            "tour_flag": "dc",
            "whatsSelect": "1",
            "seatDetailType": "000",
            "roomType": "00",
            "dwAll": "N",
            "_json_att": "",
            "REPEAT_SUBMIT_TOKEN": token,
        }
        check_resp = self.post(
            f"{KYFW_BASE}/otn/confirmPassenger/checkOrderInfo",
            data=check_data,
            headers=confirm_headers,
        ).json()
        if not check_resp.get("status"):
            return False, self._api_error(check_resp, "订单核验失败"), ""

        self.post(
            f"{KYFW_BASE}/otn/confirmPassenger/getPassengerDTOs",
            data={"_json_att": "", "REPEAT_SUBMIT_TOKEN": token},
            headers=confirm_headers,
        )

        confirm_data = {
            "passengerTicketStr": passenger_ticket,
            "oldPassengerStr": old_passenger,
            "randCode": "",
            "purpose_codes": "00",
            "key_check_isChange": key_check,
            "leftTicketStr": left_ticket,
            "train_location": train_location,
            "choose_seats": "",
            "seatDetailType": "000",
            "whatsSelect": "1",
            "roomType": "00",
            "dwAll": "N",
            "_json_att": "",
            "REPEAT_SUBMIT_TOKEN": token,
        }
        confirm_resp = self.post(
            f"{KYFW_BASE}/otn/confirmPassenger/confirmPassengerInfoSingle",
            data=confirm_data,
            headers=confirm_headers,
        ).json()
        if not confirm_resp.get("status"):
            return False, self._api_error(confirm_resp, "确认乘客信息失败"), ""

        queue_data = {
            "train_date": query.get("train_date", ""),
            "train_no": query.get("station_train_code", train_code),
            "stationTrainCode": query.get("station_train_code", train_code),
            "seatType": seat_code,
            "fromStationTelecode": query.get("from_station", ""),
            "toStationTelecode": query.get("to_station", ""),
            "leftTicket": left_ticket,
            "purpose_codes": "00",
            "train_location": train_location,
            "_json_att": "",
            "REPEAT_SUBMIT_TOKEN": token,
        }
        queue_resp = self.post(
            f"{KYFW_BASE}/otn/confirmPassenger/getQueueCount",
            data=queue_data,
            headers=confirm_headers,
        ).json()
        if not queue_resp.get("status"):
            return False, self._api_error(queue_resp, "排队查询失败"), ""

        queue_confirm_data = {
            **queue_data,
            "passengerTicketStr": passenger_ticket,
            "oldPassengerStr": old_passenger,
            "key_check_isChange": key_check,
        }
        queue_confirm_resp = self.post(
            f"{KYFW_BASE}/otn/confirmPassenger/confirmSingleForQueue",
            data=queue_confirm_data,
            headers=confirm_headers,
        ).json()
        if not queue_confirm_resp.get("status"):
            return False, self._api_error(queue_confirm_resp, "进入排队失败"), ""

        for _ in range(30):
            wait_resp = self.get(
                f"{KYFW_BASE}/otn/confirmPassenger/queryOrderWaitTime",
                params={
                    "random": str(int(time.time() * 1000)),
                    "tourFlag": "dc",
                    "_json_att": "",
                },
                headers=confirm_headers,
            ).json()
            data = wait_resp.get("data") or {}
            order_id = data.get("orderId") or ""
            if wait_resp.get("status") and order_id:
                return True, "下单成功", str(order_id)
            msg = str(data.get("msg") or "")
            if msg and any(word in msg for word in ("失败", "错误", "取消")):
                return False, msg, ""
            time.sleep(1)

        return False, "排队确认超时，请到 12306 我的订单查看是否生单", ""

    def confirm_passenger_info(
        self, passengers: list[dict], seat_type: str, train_code: str
    ) -> dict[str, Any]:
        if USE_MOCK:
            return {"status": True, "ticket_price": "553.5"}
        ok, _, _ = self.complete_booking(passengers, seat_type, train_code)
        return {"status": ok, "ticket_price": ""}

    def query_order_status(self, order_id: str) -> str:
        if USE_MOCK:
            return "wait_pay" if order_id.startswith("MOCK") else "unknown"
        return "unknown"

    def get_qr_code(self) -> tuple[str, str]:
        """返回 (uuid, qr_image_base64)。"""
        if USE_MOCK:
            return "mock-uuid", ""
        url = f"{PASSPORT_BASE}/passport/web/create-qr64"
        resp = self.post(url, data={"appid": "otn"})
        data = resp.json()
        return data.get("uuid", ""), data.get("image", "")

    def check_qr_status(self, uuid: str) -> dict[str, Any]:
        if USE_MOCK:
            return {"status": False}
        url = f"{PASSPORT_BASE}/passport/web/checkqr"
        resp = self.post(url, data={"uuid": uuid, "appid": "otn"})
        return resp.json()


def travel_date_fallback() -> str:
    return time.strftime("%Y-%m-%d")


def is_valid_train_schedule(start_time: str, arrive_time: str, duration: str) -> bool:
    """12306 对停运/不可售车次会用 24:00 与 99:59 作为占位。"""
    if not start_time or not arrive_time:
        return False
    if start_time == "24:00" or arrive_time == "24:00":
        return False
    if duration == "99:59" or duration.startswith("99:"):
        return False
    time_pattern = re.compile(r"^([01]?\d|2[0-3]):[0-5]\d$")
    if not time_pattern.match(start_time) or not time_pattern.match(arrive_time):
        return False
    return True


def has_ticket(seat_status: str) -> bool:
    if not seat_status or seat_status in ("--", "无", "*"):
        return False
    if seat_status == "有":
        return True
    return seat_status.isdigit() and int(seat_status) > 0


def format_seat_display(seat_status: str) -> str:
    """将 12306 席别余票字段转为可读文本。"""
    if not seat_status or seat_status in ("--", "*"):
        return "无"
    if seat_status == "无":
        return "无"
    if seat_status == "有":
        return "有票"
    if seat_status.isdigit():
        count = int(seat_status)
        return "无" if count == 0 else f"{count}张"
    return seat_status


def seat_has_stock_display(seat_status: str) -> bool:
    return has_ticket(seat_status)
