from __future__ import annotations

import sys
from typing import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger


class TaskScheduler:
    """APScheduler 封装：定时查票、定时任务。"""

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        self._started = False

    def start(self) -> None:
        if not self._started:
            self.scheduler.start()
            self._started = True

    def shutdown(self) -> None:
        if self._started:
            self.scheduler.shutdown(wait=False)
            self._started = False

    def add_poll_job(
        self,
        job_id: str,
        func: Callable,
        interval_seconds: float,
        **kwargs,
    ) -> None:
        self.start()
        trigger = IntervalTrigger(seconds=interval_seconds)
        self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs=kwargs,
        )

    def remove_job(self, job_id: str) -> None:
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

    def list_jobs(self) -> list[str]:
        return [job.id for job in self.scheduler.get_jobs()]
