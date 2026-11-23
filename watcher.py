"""Nasłuchiwanie folderu źródłowego (tethering) i bezpieczne kopiowanie zdjęć.

Wykorzystujemy cykliczne skanowanie folderu (polling) zamiast powiadomień systemowych –
działa niezawodnie z każdym programem do tetheringu, dyskami sieciowymi i OneDrive.
"""
from __future__ import annotations

import io
import os
import queue
import shutil
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageOps

from history import History, HistoryRecord
from naming import Student, build_stem, no_data_stem, unique_path

IMAGE_EXTS = {".jpg", ".jpeg", ".png"}
RAW_EXTS = {".cr2", ".cr3", ".nef", ".arw", ".dng", ".raf", ".orf", ".rw2"}
IGNORED_PREFIXES = ("~", ".", "_tmp")
IGNORED_SUFFIXES = (".part", ".tmp", ".crdownload")

THUMB_SIZE = (400, 400)


# --------------------------------------------------------------------- blokady
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _CreateFileW = ctypes.windll.kernel32.CreateFileW
    _CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                             wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _CreateFileW.restype = wintypes.HANDLE
    _CloseHandle = ctypes.windll.kernel32.CloseHandle
    _GENERIC_READ = 0x80000000
    _OPEN_EXISTING = 3
    _INVALID_HANDLE = wintypes.HANDLE(-1).value

    def is_file_locked(path: str) -> bool:
        """Próbuje otworzyć plik na wyłączność (share mode = 0).

        Jeśli inny proces (np. program do tetheringu) wciąż ma otwarty uchwyt,
        Windows zwróci błąd naruszenia udostępniania -> plik jest zajęty.
        """
        handle = _CreateFileW(path, _GENERIC_READ, 0, None, _OPEN_EXISTING, 0x80, None)
        if handle == _INVALID_HANDLE or handle is None:
            return True
        _CloseHandle(handle)
        return False
else:  # pragma: no cover - na innych systemach wystarczy próba odczytu
    def is_file_locked(path: str) -> bool:
        try:
            with open(path, "rb"):
                return False
        except OSError:
            return True


# ------------------------------------------------------------------ miniatury
def _embedded_jpeg_from_raw(path: str) -> Image.Image | None:
    """Wyciąga największy osadzony podgląd JPEG z pliku RAW (CR2/NEF/ARW/...)."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError:
        return None
    best: Image.Image | None = None
    start = 0
    tried = 0
    while tried < 12:
        idx = data.find(b"\xff\xd8\xff", start)
        if idx < 0:
            break
        start = idx + 3
        tried += 1
        try:
            img = Image.open(io.BytesIO(data[idx:]))
            img.load()
            if best is None or img.width * img.height > best.width * best.height:
                best = img
        except Exception:
            continue
    return best


def make_thumbnail(path: str, size=THUMB_SIZE) -> Image.Image | None:
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in RAW_EXTS:
            img = _embedded_jpeg_from_raw(path)
            if img is None:
                return None
        else:
            img = Image.open(path)
            if img.format == "JPEG":
                img.draft("RGB", (size[0] * 2, size[1] * 2))  # szybkie dekodowanie
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail(size, Image.LANCZOS)
        return img
    except Exception:
        return None


# ----------------------------------------------------------------- kopiowanie
def copy_photo(src: str, dest_dir: str, student: Student, scheme: str, ascii_only: bool) -> str:
    """Kopiuje plik pod nową nazwą (przez plik .part) i zwraca ścieżkę docelową."""
    ext = os.path.splitext(src)[1].lower() or ".jpg"
    stem = no_data_stem(src) if student.is_empty else build_stem(student, scheme, ascii_only)
    os.makedirs(dest_dir, exist_ok=True)
    last_err: Exception | None = None
    for attempt in range(5):
        final = unique_path(dest_dir, stem, ext)
        tmp = final + ".part"
        try:
            shutil.copy2(src, tmp)
            if os.path.getsize(tmp) != os.path.getsize(src):
                raise OSError("Rozmiar kopii nie zgadza się z oryginałem.")
            if os.path.exists(final):  # ktoś zajął nazwę w międzyczasie
                os.remove(tmp)
                continue
            os.replace(tmp, final)
            return final
        except OSError as e:
            last_err = e
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except OSError:
                pass
            time.sleep(0.5 * (attempt + 1))
    raise OSError(f"Nie udało się skopiować pliku: {last_err}")


def rename_to_student(rec: HistoryRecord, student: Student, scheme: str, ascii_only: bool) -> str:
    """Zmienia nazwę już skopiowanego pliku docelowego (ponowne przypisanie ucznia)."""
    old = rec.dest_path
    if not os.path.isfile(old):
        raise FileNotFoundError(f"Plik docelowy nie istnieje: {old}")
    folder = os.path.dirname(old)
    ext = os.path.splitext(old)[1].lower()
    stem = build_stem(student, scheme, ascii_only)
    new = unique_path(folder, stem, ext)
    os.rename(old, new)
    return new


# ------------------------------------------------------------------- watcher
@dataclass
class _Pending:
    path: str
    first_seen: float
    student: Student
    size: int = -1
    mtime: int = -1
    stable_since: float = 0.0
    warned: bool = False


class FolderWatcher(threading.Thread):
    """Wątek monitorujący folder źródłowy i przetwarzający nowe zdjęcia.

    Komunikacja z GUI odbywa się wyłącznie przez kolejkę `events`:
        ("log", poziom, tekst)
        ("detected", nazwa_pliku, Student)
        ("processed", HistoryRecord, PIL.Image | None)
        ("stopped", None)
    """

    def __init__(
        self,
        source: str,
        dest: str,
        history: History,
        events: "queue.Queue",
        get_student: Callable[[], Student],
        get_naming: Callable[[], tuple[str, bool]],
        include_raw: bool = True,
        ignore_existing: bool = True,
        stable_seconds: float = 1.5,
        poll_interval: float = 0.5,
    ):
        super().__init__(daemon=True, name="FolderWatcher")
        self.source = os.path.abspath(source)
        self.dest = os.path.abspath(dest)
        self.history = history
        self.events = events
        self.get_student = get_student
        self.get_naming = get_naming
        self.exts = IMAGE_EXTS | (RAW_EXTS if include_raw else set())
        self.ignore_existing = ignore_existing
        self.stable_seconds = stable_seconds
        self.poll_interval = poll_interval
        self._stop_event = threading.Event()
        self._seen: dict[str, tuple[int, int]] = {}
        self._pending: dict[str, _Pending] = {}
        self._source_error = False

    # -------------------------------------------------------------- pomocnicze
    def _emit(self, *event):
        self.events.put(event)

    def _log(self, level: str, msg: str):
        self._emit("log", level, msg)

    def stop(self):
        self._stop_event.set()

    def _is_candidate(self, name: str) -> bool:
        low = name.lower()
        if low.startswith(IGNORED_PREFIXES) or low.endswith(IGNORED_SUFFIXES):
            return False
        return os.path.splitext(low)[1] in self.exts

    def _scan(self) -> dict[str, os.stat_result]:
        found: dict[str, os.stat_result] = {}
        with os.scandir(self.source) as it:
            for entry in it:
                try:
                    if entry.is_file() and self._is_candidate(entry.name):
                        found[entry.path] = entry.stat()
                except OSError:
                    continue
        return found

    # ------------------------------------------------------------------ pętla
    def run(self):
        try:
            if self.ignore_existing:
                for path, st in self._scan().items():
                    self._seen[os.path.normcase(path)] = (st.st_size, st.st_mtime_ns)
                self._log("info", f"Pominięto {len(self._seen)} istniejących plików w folderze źródłowym.")
        except OSError as e:
            self._log("error", f"Nie można odczytać folderu źródłowego: {e}")

        self._log("ok", f"Nasłuchiwanie: {self.source}")
        while not self._stop_event.is_set():
            try:
                self._tick()
                if self._source_error:
                    self._source_error = False
                    self._log("ok", "Folder źródłowy znów dostępny.")
            except OSError as e:
                if not self._source_error:
                    self._source_error = True
                    self._log("error", f"Folder źródłowy niedostępny: {e}")
            except Exception as e:  # nie pozwalamy, by wątek padł
                self._log("error", f"Nieoczekiwany błąd watchera: {e!r}")
            self._stop_event.wait(self.poll_interval)
        self._emit("stopped", None)

    def _tick(self):
        now = time.monotonic()
        found = self._scan()
        found_keys = {os.path.normcase(p) for p in found}

        # wyczyść wpisy o plikach, które zniknęły
        for key in list(self._seen):
            if key not in found_keys:
                del self._seen[key]
        for key in list(self._pending):
            if key not in found_keys:
                self._log("warn", f"Plik zniknął przed skopiowaniem: {os.path.basename(self._pending[key].path)}")
                del self._pending[key]

        # nowe pliki -> kolejka oczekujących (dane ucznia zapamiętane w chwili wykrycia!)
        for path in sorted(found, key=lambda p: found[p].st_mtime_ns):
            key = os.path.normcase(path)
            st = found[path]
            sig = (st.st_size, st.st_mtime_ns)
            if key in self._pending:
                continue
            if self._seen.get(key) == sig:
                continue
            student = self.get_student()
            self._pending[key] = _Pending(path=path, first_seen=now, student=student)
            self._emit("detected", os.path.basename(path), student)

        # sprawdź stabilność oczekujących
        for key, p in list(self._pending.items()):
            st = found.get(p.path)
            if st is None:
                continue
            if st.st_size != p.size or st.st_mtime_ns != p.mtime:
                p.size, p.mtime, p.stable_since = st.st_size, st.st_mtime_ns, now
                continue
            if p.size <= 0 or now - p.stable_since < self.stable_seconds:
                continue
            if is_file_locked(p.path):
                if not p.warned and now - p.first_seen > 30:
                    p.warned = True
                    self._log("warn", f"Plik wciąż zablokowany przez inny proces: {os.path.basename(p.path)}")
                continue
            self._process(p)
            self._seen[key] = (p.size, p.mtime)
            del self._pending[key]

    def _process(self, p: _Pending):
        original = os.path.basename(p.path)
        scheme, ascii_only = self.get_naming()
        try:
            dest_path = copy_photo(p.path, self.dest, p.student, scheme, ascii_only)
        except Exception as e:
            self._log("error", f"Błąd kopiowania {original}: {e}")
            return
        rec = HistoryRecord(
            original_name=original,
            new_name=os.path.basename(dest_path),
            first_name=p.student.first.strip(),
            last_name=p.student.last.strip(),
            klass=p.student.klass.strip(),
            dest_path=dest_path,
            source_path=p.path,
            has_data=not p.student.is_empty,
        )
        try:
            self.history.add(rec)
        except Exception as e:
            self._log("error", f"Nie zapisano historii dla {original}: {e}")
        thumb = make_thumbnail(dest_path)
        self._emit("processed", rec, thumb)
