# Zdjęcia legitymacyjne

Aplikacja desktopowa (Windows) dla operatora sesji zdjęć legitymacyjnych.
Nasłuchuje folderu, do którego program do tetheringu zapisuje zdjęcia z aparatu,
i od razu kopiuje każde nowe ujęcie do folderu docelowego pod nazwą aktywnego ucznia,
np. `Jan_Kowalski_3A.jpg`, `Jan_Kowalski_3A_2.jpg`, …

## Struktura

| Plik | Zawartość |
|---|---|
| `main.py` | punkt startowy, zapis błędów do `crash.log` |
| `app.py` | interfejs (customtkinter): sesja, kafelek podglądu, historia, pasek stanu, dziennik |
| `watcher.py` | nasłuch folderu, kontrola stabilności/blokady pliku, kopiowanie, miniatury (także z RAW) |
| `naming.py` | schematy nazw, usuwanie polskich znaków, bezpieczne nazwy, sufiksy `_2`, `_3` |
| `history.py` | trwała historia: SQLite + dopisywany na bieżąco `history.csv`, eksport CSV/JSON |
| `settings.py` | zapamiętywanie ustawień |

Dane aplikacji (ustawienia, `history.sqlite3`, `history.csv`, `crash.log`) są w
`%APPDATA%\ZdjeciaLegitymacyjne` (przycisk **Folder historii** w zakładce Historia).

## Uruchomienie ze źródeł

Wymagany Python 3.10+ (z zaznaczonym „tcl/tk”, domyślnie w instalatorze z python.org).

```bat
cd Zdjecia_app
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

albo po prostu dwuklik na `run.bat`.

## Budowanie pliku .exe

Dwuklik na `build_exe.bat` albo ręcznie (w aktywnym `.venv`):

```bat
pyinstaller --noconfirm --clean --onefile --windowed --name "ZdjeciaLegitymacyjne" --collect-data customtkinter main.py
```

Wynik: `dist\ZdjeciaLegitymacyjne.exe` – można go skopiować na dowolny komputer z Windows 10/11
(Python nie jest wtedy potrzebny). Wersja `--onedir` zamiast `--onefile` startuje szybciej.

## Jak pracować

1. Wybierz **folder źródłowy** (tam, gdzie zapisuje program do tetheringu, np. EOS Utility,
   Capture One, Lightroom, digiCamControl) oraz **folder docelowy** (musi być inny).
2. Kliknij **Start nasłuchiwania**.
3. Wpisz **Imię → Enter → Nazwisko → Enter → Klasa**. Rób zdjęcia – każde trafia do folderu docelowego
   z nazwą ucznia. Kolejne ujęcia tego samego ucznia dostają sufiks `_2`, `_3`, …
4. **Nowy uczeń** (przycisk, `Ctrl+N` lub `F2`) czyści imię i nazwisko, ustawia kursor w polu Imię.
   Przełącznik **Zachowaj klasę przy nowym uczniu** pozwala focić całą klasę bez przepisywania klasy.
5. Kafelek podglądu pokazuje miniaturę, ucznia, oryginalną i nową nazwę oraz godzinę zapisu.
   Zdjęcie złapane **bez danych ucznia** jest zapisywane jako `BEZ_DANYCH_DSC0001.jpg`, kafelek robi się
   czerwony, a program wydaje dźwięk. Wpisz dane i kliknij **Przypisz to zdjęcie do aktywnego ucznia**.
6. Zakładka **Historia** (`Ctrl+F`) – wyszukiwanie na żywo po nazwie z aparatu (`DSC0001`, `0001`),
   klasie, nazwisku, imieniu lub dacie (kilka słów = wszystkie muszą pasować, np. `3A Kowal`).
   Dwuklik otwiera zdjęcie; można też przypisać dowolny wpis do aktywnego ucznia oraz wyeksportować
   historię do CSV (Excel) lub JSON.

## Zabezpieczenia

- Dane ucznia są zapamiętywane **w chwili wykrycia pliku**, więc kliknięcie „Nowy uczeń” w trakcie
  zapisu zdjęcia z aparatu nie przypisze go do następnej osoby.
- Plik jest kopiowany dopiero, gdy jego rozmiar i data modyfikacji nie zmieniają się przez 1,5 s
  **i** da się go otworzyć na wyłączność (żaden inny proces go nie trzyma).
- Kopia powstaje najpierw jako `*.part`, jest weryfikowana (rozmiar) i dopiero wtedy dostaje docelową
  nazwę. Oryginał w folderze źródłowym **nigdy nie jest usuwany ani zmieniany**.
- Konflikt nazw → bezpieczny sufiks `_2`, `_3`, … – nic nie zostanie nadpisane.
- Nazwy są oczyszczane ze znaków niedozwolonych w Windows; domyślnie usuwane są polskie znaki
  (`Łukasz Żółć` → `Lukasz_Zolc`), można to wyłączyć.
- Obsługiwane: `.jpg .jpeg .png` oraz opcjonalnie RAW `.cr2 .cr3 .nef .arw .dng .raf .orf .rw2`
  (podgląd RAW z osadzonej miniatury JPEG, jeśli istnieje).
