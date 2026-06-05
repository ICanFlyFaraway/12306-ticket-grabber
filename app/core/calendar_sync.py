from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from app.config import DATA_DIR


class CalendarSync:
    """将出票行程写入本地 ICS 日历文件。"""

    def __init__(self, ics_path: Path | None = None) -> None:
        self.ics_path = ics_path or (DATA_DIR / "trips.ics")

    def add_trip(
        self,
        train_code: str,
        from_station: str,
        to_station: str,
        travel_date: str,
        start_time: str,
        arrive_time: str,
    ) -> Path:
        start_dt = datetime.strptime(f"{travel_date} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{travel_date} {arrive_time}", "%Y-%m-%d %H:%M")
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        uid = f"{train_code}-{travel_date}@12306-grabber"
        summary = f"火车 {train_code} {from_station}→{to_station}"
        dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        dtstart = start_dt.strftime("%Y%m%dT%H%M%S")
        dtend = end_dt.strftime("%Y%m%dT%H%M%S")

        event = f"""BEGIN:VEVENT
UID:{uid}
DTSTAMP:{dtstamp}
DTSTART:{dtstart}
DTEND:{dtend}
SUMMARY:{summary}
DESCRIPTION:12306 抢票助手自动同步
END:VEVENT
"""
        if self.ics_path.exists():
            content = self.ics_path.read_text(encoding="utf-8")
            if "END:VCALENDAR" in content:
                content = content.replace("END:VCALENDAR", event + "END:VCALENDAR")
            else:
                content += event
        else:
            content = f"BEGIN:VCALENDAR\nVERSION:2.0\nPRODID:-//12306 Grabber//CN\n{event}END:VCALENDAR\n"

        self.ics_path.write_text(content, encoding="utf-8")
        return self.ics_path
