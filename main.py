#!/usr/bin/env python3
"""12306 抢票助手入口"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PyQt6.QtWidgets import QApplication

from app.config import APP_NAME, USE_MOCK
from app.core.station_registry import seed_stations_if_empty
from app.database.db import init_db
from app.ui.main_window import MainWindow


def main() -> int:
    init_db()
    seed_stations_if_empty()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    if USE_MOCK:
        app.setApplicationDisplayName(f"{APP_NAME} [模拟模式]")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
