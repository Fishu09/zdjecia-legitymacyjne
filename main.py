"""Punkt startowy aplikacji „Zdjęcia legitymacyjne”."""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime


def _crash_log(exc_type, exc, tb):
    """Zapisuje nieobsłużone wyjątki do pliku crash.log i pokazuje komunikat."""
    text = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        from settings import data_dir
        with open(os.path.join(data_dir(), "crash.log"), "a", encoding="utf-8") as f:
            f.write(f"\n===== {datetime.now():%Y-%m-%d %H:%M:%S} =====\n{text}")
    except Exception:
        pass
    try:
        from tkinter import messagebox
        messagebox.showerror("Zdjęcia legitymacyjne – błąd", f"Wystąpił nieoczekiwany błąd:\n\n{exc}")
    except Exception:
        print(text, file=sys.stderr)


def main():
    if sys.platform == "win32":
        try:  # własny identyfikator -> poprawna ikona/grupowanie na pasku zadań
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("ZdjeciaLegitymacyjne.App")
        except Exception:
            pass
    sys.excepthook = _crash_log

    from app import App
    app = App()
    app.report_callback_exception = _crash_log  # błędy w callbackach Tk
    app.mainloop()


if __name__ == "__main__":
    main()
