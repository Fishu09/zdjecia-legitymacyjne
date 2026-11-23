"""Ustawienia aplikacji zapisywane w %APPDATA%\\ZdjeciaLegitymacyjne\\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, fields

from naming import DEFAULT_SCHEME

APP_NAME = "ZdjeciaLegitymacyjne"


def data_dir() -> str:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


@dataclass
class Settings:
    source_dir: str = ""
    dest_dir: str = ""
    scheme: str = DEFAULT_SCHEME
    ascii_only: bool = True
    include_raw: bool = True
    ignore_existing: bool = True
    keep_class: bool = True
    stable_seconds: float = 1.5
    appearance: str = "System"
    last_class: str = ""

    @classmethod
    def path(cls) -> str:
        return os.path.join(data_dir(), "settings.json")

    @classmethod
    def load(cls) -> "Settings":
        try:
            with open(cls.path(), encoding="utf-8") as f:
                raw = json.load(f)
            known = {f.name for f in fields(cls)}
            return cls(**{k: v for k, v in raw.items() if k in known})
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        try:
            tmp = self.path() + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path())
        except OSError:
            pass
