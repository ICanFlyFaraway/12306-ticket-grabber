from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "12306抢票助手"
APP_VERSION = "1.0.0"

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

DB_PATH = DATA_DIR / "ticket_grabber.db"
STATIONS_PATH = DATA_DIR / "stations.json"

# 12306 官方接口
KYFW_BASE = "https://kyfw.12306.cn"
PASSPORT_BASE = "https://passport.12306.cn"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Origin": KYFW_BASE,
    "Referer": f"{KYFW_BASE}/otn/leftTicket/init",
}

# 席别代码映射
SEAT_TYPES = {
    "商务座": "9",
    "一等座": "M",
    "二等座": "O",
    "高级软卧": "6",
    "软卧": "4",
    "硬卧": "3",
    "软座": "2",
    "硬座": "1",
    "无座": "1",
}

SEAT_TYPE_LABELS = list(SEAT_TYPES.keys())

# 车次查询表格展示的席别列
QUERY_SEAT_COLUMNS = ["商务座", "一等座", "二等座", "软卧", "硬卧", "硬座", "无座"]

# 默认轮询间隔（秒）
DEFAULT_POLL_INTERVAL = 3
MIN_POLL_INTERVAL = 1
MAX_POLL_INTERVAL = 60

# 支付等待超时（秒）
PAYMENT_TIMEOUT = 30 * 60

# 是否使用模拟模式（不请求真实 12306，用于本地演示）
USE_MOCK = os.environ.get("TICKET_MOCK", "0") == "1"
