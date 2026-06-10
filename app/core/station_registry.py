from __future__ import annotations

import json
from datetime import datetime

import requests
from sqlalchemy.orm import Session

from app.config import DATA_DIR, KYFW_BASE, STATIONS_PATH
from app.database.db import get_session
from app.database.models import Station

STATION_JS_URL = f"{KYFW_BASE}/otn/resources/js/framework/station_name.js"
CACHE_PATH = DATA_DIR / "stations_full.json"

_registry: dict[str, str] | None = None
_last_refreshed: datetime | None = None


def _parse_station_js(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    body = text
    if "=" in text:
        body = text.split("=", 1)[1].strip().strip("'\"")
    for chunk in body.split("@"):
        if not chunk or "|" not in chunk:
            continue
        parts = chunk.split("|")
        if len(parts) < 3:
            continue
        name, code = parts[1].strip(), parts[2].strip()
        pinyin = parts[3].strip() if len(parts) > 3 else ""
        if name and code:
            rows.append({"name": name, "code": code, "pinyin": pinyin})
    return rows


def _load_json_stations(path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        {"name": item["name"], "code": item["code"], "pinyin": item.get("pinyin", "")}
        for item in data
    ]


def _save_rows_to_db(session: Session, rows: list[dict[str, str]]) -> int:
    session.query(Station).delete()
    now = datetime.now()
    for row in rows:
        session.add(
            Station(
                name=row["name"],
                code=row["code"],
                pinyin=row.get("pinyin", ""),
                updated_at=now,
            )
        )
    session.flush()
    return len(rows)


def load_stations_from_db() -> dict[str, str]:
    with get_session() as session:
        rows = session.query(Station).all()
        return {row.name: row.code for row in rows}


def get_station_count() -> int:
    with get_session() as session:
        return session.query(Station).count()


def get_last_refreshed() -> datetime | None:
    global _last_refreshed
    if _last_refreshed:
        return _last_refreshed
    with get_session() as session:
        row = session.query(Station.updated_at).order_by(Station.updated_at.desc()).first()
        if row:
            _last_refreshed = row[0]
    return _last_refreshed


def invalidate_cache() -> None:
    global _registry, _last_refreshed
    _registry = None
    _last_refreshed = None


def seed_stations_if_empty() -> int:
    """首次启动：从 JSON 缓存或内置站名表导入数据库。"""
    if get_station_count() > 0:
        return get_station_count()
    rows = _load_json_stations(CACHE_PATH)
    if not rows:
        rows = _load_json_stations(STATIONS_PATH)
    if rows:
        with get_session() as session:
            return _save_rows_to_db(session, rows)
    try:
        count, _ = refresh_stations_from_remote()
        return count
    except Exception:
        return 0


def fetch_remote_station_rows() -> list[dict[str, str]]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Referer": f"{KYFW_BASE}/otn/leftTicket/init",
    }
    resp = requests.get(STATION_JS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    rows = _parse_station_js(resp.text)
    if not rows:
        raise RuntimeError("无法解析 12306 车站数据")
    CACHE_PATH.parent.mkdir(exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(
            [{"name": r["name"], "code": r["code"]} for r in rows],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return rows


def refresh_stations_from_remote() -> tuple[int, datetime]:
    """从 12306 拉取最新站名并写入本地数据库。"""
    global _registry, _last_refreshed
    rows = fetch_remote_station_rows()
    refreshed_at = datetime.now()
    with get_session() as session:
        count = _save_rows_to_db(session, rows)
    _registry = load_stations_from_db()
    _last_refreshed = refreshed_at
    return count, refreshed_at


def get_station_registry(refresh: bool = False) -> dict[str, str]:
    global _registry
    if _registry is not None and not refresh:
        return _registry

    db_map = load_stations_from_db()
    if db_map:
        _registry = db_map
        return _registry

    seed_stations_if_empty()
    _registry = load_stations_from_db()
    return _registry or {}


def resolve_station_code(name: str, local_map: dict[str, str] | None = None) -> str:
    name = name.strip()
    if not name:
        raise ValueError("站名不能为空")
    if len(name) <= 3 and name.isalpha() and name.isupper():
        return name

    registry = get_station_registry()
    if local_map:
        registry = {**registry, **local_map}

    if name in registry:
        return registry[name]

    short = name.removesuffix("站")
    if short in registry:
        return registry[short]

    matches = [code for n, code in registry.items() if n.startswith(name)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        candidates = sorted(
            ((n, c) for n, c in registry.items() if name in n),
            key=lambda x: (len(x[0]), x[0]),
        )
        if candidates:
            return candidates[0][1]

    raise ValueError(f"未找到车站「{name}」，请点击「刷新站名」更新车站数据")
