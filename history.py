"""Trwała historia przetworzonych zdjęć: SQLite + dopisywany na bieżąco history.csv."""
from __future__ import annotations

import csv
import json
import os
import sqlite3
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime

CSV_FIELDS = [
    "id", "timestamp", "original_name", "new_name", "first_name", "last_name",
    "klass", "dest_path", "source_path", "has_data",
]


@dataclass
class HistoryRecord:
    original_name: str
    new_name: str
    first_name: str
    last_name: str
    klass: str
    dest_path: str
    source_path: str
    has_data: bool
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    id: int | None = None


class History:
    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.db_path = os.path.join(data_dir, "history.sqlite3")
        self.csv_path = os.path.join(data_dir, "history.csv")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    original_name TEXT NOT NULL,
                    new_name TEXT NOT NULL,
                    first_name TEXT,
                    last_name TEXT,
                    klass TEXT,
                    dest_path TEXT,
                    source_path TEXT,
                    has_data INTEGER NOT NULL DEFAULT 1
                )"""
            )
            self._conn.execute("CREATE INDEX IF NOT EXISTS ix_orig ON history(original_name)")
            self._conn.commit()

    # ------------------------------------------------------------------ zapis
    def add(self, rec: HistoryRecord) -> HistoryRecord:
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO history (timestamp, original_name, new_name, first_name,
                   last_name, klass, dest_path, source_path, has_data)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (rec.timestamp, rec.original_name, rec.new_name, rec.first_name,
                 rec.last_name, rec.klass, rec.dest_path, rec.source_path, int(rec.has_data)),
            )
            self._conn.commit()
            rec.id = cur.lastrowid
        self._append_csv(rec, note="")
        return rec

    def update_assignment(self, rec: HistoryRecord) -> None:
        """Aktualizuje rekord po ponownym przypisaniu zdjęcia do ucznia."""
        if rec.id is None:
            return
        with self._lock:
            self._conn.execute(
                """UPDATE history SET new_name=?, first_name=?, last_name=?, klass=?,
                   dest_path=?, has_data=? WHERE id=?""",
                (rec.new_name, rec.first_name, rec.last_name, rec.klass,
                 rec.dest_path, int(rec.has_data), rec.id),
            )
            self._conn.commit()
        # CSV jest dziennikiem "append-only" – dopisujemy wiersz z korektą
        self._append_csv(rec, note="")

    def _append_csv(self, rec: HistoryRecord, note: str) -> None:
        try:
            new_file = not os.path.exists(self.csv_path) or os.path.getsize(self.csv_path) == 0
            with open(self.csv_path, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
                if new_file:
                    w.writeheader()
                row = asdict(rec)
                row["has_data"] = "tak" if rec.has_data else "NIE"
                w.writerow({k: row.get(k, "") for k in CSV_FIELDS})
        except OSError:
            # CSV może być otwarty w Excelu – SQLite i tak zawiera pełne dane
            pass

    # ---------------------------------------------------------------- odczyt
    def search(self, query: str = "", limit: int = 1000) -> list[sqlite3.Row]:
        query = (query or "").strip()
        sql = "SELECT * FROM history"
        params: list = []
        if query:
            terms = query.split()
            conds = []
            for t in terms:
                like = f"%{t}%"
                conds.append(
                    "(original_name LIKE ? OR new_name LIKE ? OR first_name LIKE ? "
                    "OR last_name LIKE ? OR klass LIKE ? OR timestamp LIKE ?)"
                )
                params += [like] * 6
            sql += " WHERE " + " AND ".join(conds)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            return list(self._conn.execute(sql, params))

    def count(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM history").fetchone()[0]

    # --------------------------------------------------------------- eksport
    def export_csv(self, path: str) -> int:
        rows = self.search(limit=10_000_000)
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CSV_FIELDS, delimiter=";")
            w.writeheader()
            for r in reversed(rows):
                d = dict(r)
                d["has_data"] = "tak" if d["has_data"] else "NIE"
                w.writerow({k: d.get(k, "") for k in CSV_FIELDS})
        return len(rows)

    def export_json(self, path: str) -> int:
        rows = [dict(r) for r in reversed(self.search(limit=10_000_000))]
        for r in rows:
            r["has_data"] = bool(r["has_data"])
        with open(path, "w", encoding="utf-8") as f:
            json.dump(rows, f, ensure_ascii=False, indent=2)
        return len(rows)

    def close(self) -> None:
        with self._lock:
            self._conn.close()
