from __future__ import annotations

import random
import threading
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class ProxyEntry:
    url: str
    fail_count: int = 0
    last_used: datetime | None = None
    is_active: bool = True


class ProxyPool:
    """代理 IP 池：轮询、失败剔除、限速规避。"""

    def __init__(self) -> None:
        self._proxies: list[ProxyEntry] = []
        self._lock = threading.Lock()
        self._index = 0
        self.max_fail = 3

    def add_proxy(self, url: str) -> None:
        with self._lock:
            if not any(p.url == url for p in self._proxies):
                self._proxies.append(ProxyEntry(url=url))

    def remove_proxy(self, url: str) -> None:
        with self._lock:
            self._proxies = [p for p in self._proxies if p.url != url]

    def load_from_text(self, text: str) -> int:
        count = 0
        for line in text.strip().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                self.add_proxy(line)
                count += 1
        return count

    def get_proxy(self) -> str | None:
        with self._lock:
            active = [p for p in self._proxies if p.is_active]
            if not active:
                return None
            if len(active) == 1:
                entry = active[0]
            else:
                self._index = (self._index + 1) % len(active)
                entry = active[self._index]
            entry.last_used = datetime.now()
            return entry.url

    def report_fail(self, url: str) -> None:
        with self._lock:
            for entry in self._proxies:
                if entry.url == url:
                    entry.fail_count += 1
                    if entry.fail_count >= self.max_fail:
                        entry.is_active = False

    def report_success(self, url: str) -> None:
        with self._lock:
            for entry in self._proxies:
                if entry.url == url:
                    entry.fail_count = 0
                    entry.is_active = True

    def reset_all(self) -> None:
        with self._lock:
            for entry in self._proxies:
                entry.fail_count = 0
                entry.is_active = True

    def list_proxies(self) -> list[str]:
        with self._lock:
            return [p.url for p in self._proxies if p.is_active]

    @property
    def count(self) -> int:
        return len(self.list_proxies())
