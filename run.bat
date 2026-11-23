@echo off
REM Uruchamia aplikacje ze zrodel (tworzy srodowisko przy pierwszym uruchomieniu)
cd /d "%~dp0"
if not exist .venv (
    python -m venv .venv
    call .venv\Scripts\activate.bat
    python -m pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)
start "" pythonw main.py
