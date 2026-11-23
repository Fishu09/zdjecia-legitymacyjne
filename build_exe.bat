@echo off
REM Buduje ZdjeciaLegitymacyjne.exe (jeden plik, bez okna konsoli) do folderu dist\
cd /d "%~dp0"

if not exist .venv (
    python -m venv .venv || goto :error
)
call .venv\Scripts\activate.bat || goto :error
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || goto :error

pyinstaller --noconfirm --clean --onefile --windowed ^
    --name "ZdjeciaLegitymacyjne" ^
    --collect-data customtkinter ^
    main.py || goto :error

echo.
echo Gotowe: dist\ZdjeciaLegitymacyjne.exe
pause
exit /b 0

:error
echo.
echo BLAD podczas budowania.
pause
exit /b 1
