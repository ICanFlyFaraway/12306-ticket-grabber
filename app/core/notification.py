from __future__ import annotations

import sys


def notify(title: str, message: str, timeout: int = 8) -> None:
    """系统桌面通知。"""
    try:
        if sys.platform == "win32":
            from win10toast import ToastNotifier

            toaster = ToastNotifier()
            toaster.show_toast(title, message, duration=timeout, threaded=True)
            return
    except Exception:
        pass

    try:
        from plyer import notification

        notification.notify(title=title, message=message, timeout=timeout)
    except Exception:
        pass
