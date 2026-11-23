"""Budowanie bezpiecznych nazw plików dla zdjęć legitymacyjnych."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass

# Schematy nazw: klucz -> (etykieta w GUI, kolejność pól)
NAME_SCHEMES: dict[str, tuple[str, tuple[str, ...]]] = {
    "imie_nazwisko_klasa": ("Imie_Nazwisko_Klasa", ("first", "last", "klass")),
    "nazwisko_imie_klasa": ("Nazwisko_Imie_Klasa", ("last", "first", "klass")),
    "klasa_nazwisko_imie": ("Klasa_Nazwisko_Imie", ("klass", "last", "first")),
    "nazwisko_imie": ("Nazwisko_Imie", ("last", "first")),
}
DEFAULT_SCHEME = "imie_nazwisko_klasa"

_POLISH_MAP = str.maketrans({
    "ą": "a", "ć": "c", "ę": "e", "ł": "l", "ń": "n", "ó": "o", "ś": "s", "ź": "z", "ż": "z",
    "Ą": "A", "Ć": "C", "Ę": "E", "Ł": "L", "Ń": "N", "Ó": "O", "Ś": "S", "Ź": "Z", "Ż": "Z",
})

# Znaki niedozwolone w nazwach plików Windows + znaki sterujące
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
MAX_STEM_LEN = 150


@dataclass(frozen=True)
class Student:
    first: str = ""
    last: str = ""
    klass: str = ""

    @property
    def is_empty(self) -> bool:
        return not (self.first.strip() or self.last.strip())

    @property
    def display(self) -> str:
        name = f"{self.first.strip()} {self.last.strip()}".strip()
        return name or "— brak danych —"


def transliterate(text: str) -> str:
    """Zamienia polskie (i inne) znaki diakrytyczne na odpowiedniki ASCII."""
    text = text.translate(_POLISH_MAP)
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(c for c in normalized if not unicodedata.combining(c)).encode(
        "ascii", "ignore"
    ).decode("ascii")


def clean_part(text: str, ascii_only: bool) -> str:
    """Czyści pojedynczy fragment nazwy (imię, nazwisko, klasa)."""
    text = (text or "").strip()
    if ascii_only:
        text = transliterate(text)
    text = _INVALID_CHARS.sub("", text)
    # spacje i myślniki w środku -> łącznik '-', np. "Anna Maria" -> "Anna-Maria"
    text = re.sub(r"\s+", "-", text)
    text = re.sub(r"[_]+", "-", text)          # '_' rezerwujemy jako separator pól
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-. ")


def build_stem(student: Student, scheme: str, ascii_only: bool) -> str:
    """Zwraca rdzeń nazwy pliku (bez rozszerzenia i sufiksu)."""
    _, fields = NAME_SCHEMES.get(scheme, NAME_SCHEMES[DEFAULT_SCHEME])
    values = {
        "first": clean_part(student.first, ascii_only),
        "last": clean_part(student.last, ascii_only),
        "klass": clean_part(student.klass, ascii_only),
    }
    parts = [values[f] for f in fields if values[f]]
    stem = "_".join(parts)
    return sanitize_stem(stem)


def sanitize_stem(stem: str) -> str:
    stem = _INVALID_CHARS.sub("", stem).strip(" .")
    if not stem:
        stem = "zdjecie"
    if stem.split(".")[0].upper() in _RESERVED_NAMES:
        stem = f"_{stem}"
    return stem[:MAX_STEM_LEN]


def no_data_stem(original_name: str) -> str:
    """Nazwa dla zdjęcia, które wpadło bez danych ucznia."""
    base = os.path.splitext(os.path.basename(original_name))[0]
    return sanitize_stem(f"BEZ_DANYCH_{clean_part(base, True)}")


def unique_path(folder: str, stem: str, ext: str) -> str:
    """Pierwsza wolna ścieżka: stem.ext, stem_2.ext, stem_3.ext, ...

    Sprawdzane są też pliki tymczasowe .part, aby nie kolidować z kopiowaniem w toku.
    """
    ext = ext.lower()
    candidate = os.path.join(folder, f"{stem}{ext}")
    n = 2
    while os.path.exists(candidate) or os.path.exists(candidate + ".part"):
        candidate = os.path.join(folder, f"{stem}_{n}{ext}")
        n += 1
        if n > 100000:
            raise RuntimeError("Nie udało się znaleźć wolnej nazwy pliku.")
    return candidate
