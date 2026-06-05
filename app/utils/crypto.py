from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

from cryptography.fernet import Fernet

_KEY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / ".key"


def _get_fernet() -> Fernet:
    _KEY_PATH.parent.mkdir(exist_ok=True)
    if not _KEY_PATH.exists():
        _KEY_PATH.write_bytes(Fernet.generate_key())
    return Fernet(_KEY_PATH.read_bytes())


def encrypt_password(password: str) -> str:
    return _get_fernet().encrypt(password.encode()).decode()


def decrypt_password(token: str) -> str:
    return _get_fernet().decrypt(token.encode()).decode()


def md5_hex(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


def load_stations(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {item["name"]: item["code"] for item in data}


def save_stations(path: Path, stations: list[dict]) -> None:
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(stations, ensure_ascii=False, indent=2), encoding="utf-8")


def image_to_base64(data: bytes) -> str:
    return base64.b64encode(data).decode()
