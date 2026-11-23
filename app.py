"""Zdjęcia legitymacyjne – główne okno aplikacji (customtkinter)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk
from PIL import Image

from history import History, HistoryRecord
from naming import NAME_SCHEMES, Student, build_stem, no_data_stem
from settings import Settings, data_dir
from watcher import FolderWatcher, make_thumbnail, rename_to_student

APP_TITLE = "Zdjęcia legitymacyjne"
FONT = "Segoe UI"

COLOR_OK = "#2e9e5b"
COLOR_OK_HOVER = "#25834b"
COLOR_STOP = "#c0392b"
COLOR_STOP_HOVER = "#9e2f23"
COLOR_WARN = "#e67e22"
COLOR_ERR = "#d64541"
COLOR_MUTED = ("#6b6b6b", "#a0a0a0")

LOG_COLORS = {"info": None, "ok": COLOR_OK, "warn": COLOR_WARN, "error": COLOR_ERR}


def open_path(path: str) -> None:
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as e:
        messagebox.showerror(APP_TITLE, f"Nie można otworzyć:\n{path}\n\n{e}")


def show_in_folder(path: str) -> None:
    if sys.platform == "win32" and os.path.exists(path):
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    else:
        open_path(os.path.dirname(path))


class App(ctk.CTk):
    def __init__(self):
        self.settings = Settings.load()
        ctk.set_appearance_mode(self.settings.appearance)
        ctk.set_default_color_theme("blue")
        super().__init__()

        self.title(APP_TITLE)
        self.geometry("1280x840")
        self.minsize(1080, 720)
        try:
            self.state("zoomed")
        except tk.TclError:
            pass

        self.history = History(data_dir())
        self.events: queue.Queue = queue.Queue()
        self.watcher: FolderWatcher | None = None

        # Stan współdzielony z wątkiem watchera (odczyty atomowe niezmiennych obiektów)
        self._student = Student()
        self._naming = (self.settings.scheme, self.settings.ascii_only)

        self.session_count = 0
        self.student_count = 0
        self.last_record: HistoryRecord | None = None
        self._preview_image: ctk.CTkImage | None = None
        self._search_job: str | None = None

        self._build_ui()
        self._bind_keys()
        self._update_student_state()
        self._refresh_history()
        self._update_statusbar()
        self.log("info", f"Dane aplikacji i historia: {data_dir()}")

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._poll_events)
        self.after(200, lambda: self.e_first.focus_set())

    # ================================================================== UI
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_top()

        self.tabs = ctk.CTkTabview(self, anchor="nw")
        self.tabs.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 6))
        self.tab_session = self.tabs.add("  Sesja  ")
        self.tab_history = self.tabs.add("  Historia  ")
        self.tabs.configure(command=self._on_tab_change)
        self._build_session_tab(self.tab_session)
        self._build_history_tab(self.tab_history)

        self._build_statusbar()

    # ------------------------------------------------------------- górny pas
    def _build_top(self):
        top = ctk.CTkFrame(self)
        top.grid(row=0, column=0, sticky="ew", padx=12, pady=12)
        top.grid_columnconfigure(1, weight=1)

        self.var_source = tk.StringVar(value=self.settings.source_dir)
        self.var_dest = tk.StringVar(value=self.settings.dest_dir)

        ctk.CTkLabel(top, text="Folder źródłowy (tethering):", font=(FONT, 13)).grid(
            row=0, column=0, sticky="w", padx=(12, 8), pady=(10, 4))
        self.e_source = ctk.CTkEntry(top, textvariable=self.var_source, font=(FONT, 13))
        self.e_source.grid(row=0, column=1, sticky="ew", pady=(10, 4))
        ctk.CTkButton(top, text="Wybierz…", width=90,
                      command=lambda: self._choose_dir(self.var_source)).grid(
            row=0, column=2, padx=6, pady=(10, 4))
        ctk.CTkButton(top, text="Otwórz", width=70, fg_color="gray40", hover_color="gray30",
                      command=lambda: self._open_dir(self.var_source.get())).grid(
            row=0, column=3, padx=(0, 12), pady=(10, 4))

        ctk.CTkLabel(top, text="Folder docelowy:", font=(FONT, 13)).grid(
            row=1, column=0, sticky="w", padx=(12, 8), pady=4)
        self.e_dest = ctk.CTkEntry(top, textvariable=self.var_dest, font=(FONT, 13))
        self.e_dest.grid(row=1, column=1, sticky="ew", pady=4)
        ctk.CTkButton(top, text="Wybierz…", width=90,
                      command=lambda: self._choose_dir(self.var_dest)).grid(row=1, column=2, padx=6, pady=4)
        ctk.CTkButton(top, text="Otwórz", width=70, fg_color="gray40", hover_color="gray30",
                      command=lambda: self._open_dir(self.var_dest.get())).grid(
            row=1, column=3, padx=(0, 12), pady=4)

        opts = ctk.CTkFrame(top, fg_color="transparent")
        opts.grid(row=2, column=0, columnspan=4, sticky="ew", padx=12, pady=(6, 10))
        opts.grid_columnconfigure(6, weight=1)

        ctk.CTkLabel(opts, text="Schemat nazwy:", font=(FONT, 13)).grid(row=0, column=0, padx=(0, 6))
        self._scheme_labels = {label: key for key, (label, _) in NAME_SCHEMES.items()}
        current_label = NAME_SCHEMES.get(self.settings.scheme, next(iter(NAME_SCHEMES.values())))[0]
        self.var_scheme = tk.StringVar(value=current_label)
        ctk.CTkOptionMenu(opts, variable=self.var_scheme, values=list(self._scheme_labels),
                          width=190, command=lambda _: self._on_naming_change()).grid(row=0, column=1, padx=(0, 16))

        self.var_ascii = tk.BooleanVar(value=self.settings.ascii_only)
        ctk.CTkSwitch(opts, text="Usuwaj polskie znaki (bezpieczne nazwy)", variable=self.var_ascii,
                      command=self._on_naming_change).grid(row=0, column=2, padx=(0, 16))
        self.var_raw = tk.BooleanVar(value=self.settings.include_raw)
        self.sw_raw = ctk.CTkSwitch(opts, text="Pliki RAW (CR2/NEF/ARW…)", variable=self.var_raw)
        self.sw_raw.grid(row=0, column=3, padx=(0, 16))
        self.var_ignore = tk.BooleanVar(value=self.settings.ignore_existing)
        self.sw_ignore = ctk.CTkSwitch(opts, text="Pomiń pliki już obecne w źródle", variable=self.var_ignore)
        self.sw_ignore.grid(row=0, column=4, padx=(0, 16))

        self.var_theme = tk.StringVar(value=self.settings.appearance)
        ctk.CTkOptionMenu(opts, variable=self.var_theme, values=["System", "Light", "Dark"], width=100,
                          command=self._on_theme_change).grid(row=0, column=5, padx=(0, 16))

        self.btn_watch = ctk.CTkButton(opts, text="▶  Start nasłuchiwania", width=230, height=40,
                                       font=(FONT, 15, "bold"), fg_color=COLOR_OK,
                                       hover_color=COLOR_OK_HOVER, command=self._toggle_watch)
        self.btn_watch.grid(row=0, column=7, sticky="e")

    # ---------------------------------------------------------------- sesja
    def _build_session_tab(self, tab):
        tab.grid_columnconfigure(0, weight=0, minsize=400)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=0)

        # --- panel ucznia
        # przewijany – na małych ekranach (np. 1366x768) nic nie zostanie ucięte
        left = ctk.CTkScrollableFrame(tab, width=370)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10), pady=(0, 8))
        left.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(left, text="Aktywny uczeń", font=(FONT, 20, "bold")).grid(
            row=0, column=0, sticky="w", padx=10, pady=(6, 6))

        self.lbl_nodata = ctk.CTkLabel(
            left, text="⚠  BRAK DANYCH UCZNIA\nZdjęcia zostaną zapisane jako BEZ_DANYCH_…",
            font=(FONT, 14, "bold"), text_color="white", fg_color=COLOR_ERR, corner_radius=8, height=50)
        self.lbl_nodata.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 8))

        self.var_first = tk.StringVar()
        self.var_last = tk.StringVar()
        self.var_class = tk.StringVar(value=self.settings.last_class)

        def field(row, label, var, hint):
            label = f"{label}   ({hint})"
            ctk.CTkLabel(left, text=label, font=(FONT, 13), text_color=COLOR_MUTED).grid(
                row=row, column=0, sticky="w", padx=10)
            e = ctk.CTkEntry(left, textvariable=var, font=(FONT, 20), height=40)
            e.grid(row=row + 1, column=0, sticky="ew", padx=10, pady=(0, 6))
            return e

        self.e_first = field(2, "Imię", self.var_first, "np. Jan")
        self.e_last = field(4, "Nazwisko", self.var_last, "np. Kowalski")
        self.e_class = field(6, "Klasa", self.var_class, "np. 3A, 1Ti")

        for v in (self.var_first, self.var_last, self.var_class):
            v.trace_add("write", lambda *_: self._update_student_state())

        self.var_keep_class = tk.BooleanVar(value=self.settings.keep_class)
        ctk.CTkSwitch(left, text="Zachowaj klasę przy nowym uczniu", variable=self.var_keep_class,
                      font=(FONT, 13)).grid(row=8, column=0, sticky="w", padx=10, pady=(4, 10))

        self.btn_new = ctk.CTkButton(left, text="➕  Nowy uczeń   (Ctrl+N)", height=48,
                                     font=(FONT, 17, "bold"), command=self.new_student)
        self.btn_new.grid(row=9, column=0, sticky="ew", padx=10, pady=(0, 10))

        info = ctk.CTkFrame(left, fg_color=("gray90", "gray17"))
        info.grid(row=10, column=0, sticky="ew", padx=10, pady=(0, 8))
        info.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(info, text="Następne zdjęcie zostanie zapisane jako:", font=(FONT, 12),
                     text_color=COLOR_MUTED).grid(row=0, column=0, sticky="w", padx=12, pady=(8, 0))
        self.lbl_next_name = ctk.CTkLabel(info, text="", font=(FONT, 15, "bold"), wraplength=330,
                                          justify="left", anchor="w")
        self.lbl_next_name.grid(row=1, column=0, sticky="ew", padx=12, pady=(0, 2))
        self.lbl_student_count = ctk.CTkLabel(info, text="", font=(FONT, 13), anchor="w")
        self.lbl_student_count.grid(row=2, column=0, sticky="ew", padx=12, pady=(0, 8))

        ctk.CTkLabel(left, text="Enter – następne pole  •  Ctrl+N / F2 – nowy uczeń",
                     font=(FONT, 11), text_color=COLOR_MUTED).grid(row=11, column=0, sticky="w",
                                                                   padx=10, pady=(0, 6))

        # --- kafelek podglądu
        self.tile = ctk.CTkFrame(tab, border_width=3, border_color=("gray75", "gray30"))
        self.tile.grid(row=0, column=1, sticky="nsew", pady=(0, 8))
        self.tile.grid_columnconfigure(1, weight=1)
        self.tile.grid_rowconfigure(1, weight=1)

        self.lbl_tile_header = ctk.CTkLabel(self.tile, text="Ostatnie zdjęcie", font=(FONT, 16, "bold"),
                                            anchor="w", corner_radius=6)
        self.lbl_tile_header.grid(row=0, column=0, columnspan=2, sticky="ew", padx=14, pady=(12, 6))

        self.lbl_image = ctk.CTkLabel(self.tile, text="Czekam na pierwsze zdjęcie…", width=410, height=410,
                                      fg_color=("gray85", "gray20"), corner_radius=8, font=(FONT, 14),
                                      text_color=COLOR_MUTED)
        self.lbl_image.grid(row=1, column=0, sticky="n", padx=(14, 10), pady=(0, 14))

        details = ctk.CTkFrame(self.tile, fg_color="transparent")
        details.grid(row=1, column=1, sticky="nsew", padx=(4, 14), pady=(0, 14))
        details.grid_columnconfigure(0, weight=1)

        self.lbl_t_name = ctk.CTkLabel(details, text="—", font=(FONT, 28, "bold"), anchor="w",
                                       justify="left", wraplength=420)
        self.lbl_t_name.grid(row=0, column=0, sticky="ew", pady=(4, 0))
        self.lbl_t_class = ctk.CTkLabel(details, text="", font=(FONT, 20), anchor="w")
        self.lbl_t_class.grid(row=1, column=0, sticky="ew", pady=(0, 6))

        def kv(row, key):
            ctk.CTkLabel(details, text=key, font=(FONT, 12), text_color=COLOR_MUTED, anchor="w").grid(
                row=row, column=0, sticky="ew")
            val = ctk.CTkLabel(details, text="—", font=(FONT, 15), anchor="w", justify="left",
                               wraplength=420)
            val.grid(row=row + 1, column=0, sticky="ew", pady=(0, 6))
            return val

        self.lbl_t_orig = kv(4, "Plik z aparatu")
        self.lbl_t_new = kv(6, "Nowa nazwa")
        self.lbl_t_time = kv(8, "Zapisano")
        self.lbl_t_folder = kv(10, "Folder docelowy")

        # przyciski tuż pod nazwiskiem – zawsze widoczne
        btns = ctk.CTkFrame(details, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="ew")
        self.btn_t_open = ctk.CTkButton(btns, text="Otwórz zdjęcie", width=130, state="disabled",
                                        command=lambda: self.last_record and open_path(self.last_record.dest_path))
        self.btn_t_open.pack(side="left", padx=(0, 6), pady=4)
        self.btn_t_folder = ctk.CTkButton(btns, text="Pokaż w folderze", width=130, state="disabled",
                                          fg_color="gray40", hover_color="gray30",
                                          command=lambda: self.last_record and show_in_folder(self.last_record.dest_path))
        self.btn_t_folder.pack(side="left", padx=(0, 6), pady=4)
        self.btn_t_assign = ctk.CTkButton(details, text="Przypisz to zdjęcie do aktywnego ucznia",
                                          state="disabled", fg_color=COLOR_WARN, hover_color="#c96a12",
                                          command=self._assign_last)
        self.btn_t_assign.grid(row=3, column=0, sticky="w", pady=(2, 14))

        # --- dziennik
        logf = ctk.CTkFrame(tab)
        logf.grid(row=1, column=0, columnspan=2, sticky="nsew")
        logf.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(logf, text="Dziennik zdarzeń", font=(FONT, 13, "bold")).grid(
            row=0, column=0, sticky="w", padx=12, pady=(6, 0))
        self.txt_log = ctk.CTkTextbox(logf, height=95, font=("Consolas", 12), wrap="none")
        self.txt_log.grid(row=1, column=0, sticky="nsew", padx=10, pady=(2, 10))
        self.txt_log.configure(state="disabled")
        for level, color in LOG_COLORS.items():
            if color:
                self.txt_log.tag_config(level, foreground=color)

    # -------------------------------------------------------------- historia
    def _build_history_tab(self, tab):
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        bar.grid_columnconfigure(0, weight=1)

        # bez textvariable – inaczej CTkEntry nie pokazuje tekstu podpowiedzi
        self.e_search = ctk.CTkEntry(bar, height=40, font=(FONT, 16),
                                     placeholder_text="🔍  Szukaj: DSC0001, 0001, 3A, nazwisko, imię, data…")
        self.e_search.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.e_search.bind("<KeyRelease>", lambda _: self._schedule_search())
        ctk.CTkButton(bar, text="Wyczyść", width=80, height=40, fg_color="gray40", hover_color="gray30",
                      command=self._clear_search).grid(row=0, column=1, padx=(0, 8))
        self.lbl_hist_count = ctk.CTkLabel(bar, text="", font=(FONT, 13), width=150)
        self.lbl_hist_count.grid(row=0, column=2)
        ctk.CTkLabel(bar, text="Szuka w: plik z aparatu (np. DSC0001 lub 0001), nowa nazwa, imię, nazwisko, "
                               "klasa, data. Kilka słów = wszystkie muszą pasować (np. „3A Kowal”).",
                     font=(FONT, 12), text_color=COLOR_MUTED).grid(row=1, column=0, columnspan=3,
                                                                   sticky="w", padx=4, pady=(4, 0))

        table = ctk.CTkFrame(tab)
        table.grid(row=1, column=0, sticky="nsew")
        table.grid_columnconfigure(0, weight=1)
        table.grid_rowconfigure(0, weight=1)

        self.tree_style = ttk.Style(self)
        self._style_tree()
        cols = ("time", "orig", "new", "first", "last", "klass", "folder")
        heads = ("Czas zapisu", "Plik z aparatu", "Nowa nazwa", "Imię", "Nazwisko", "Klasa", "Folder docelowy")
        widths = (170, 150, 260, 120, 160, 70, 300)
        self.tree = ttk.Treeview(table, columns=cols, show="headings", style="Hist.Treeview",
                                 selectmode="browse")
        for c, h, w in zip(cols, heads, widths):
            self.tree.heading(c, text=h, anchor="w")
            self.tree.column(c, width=w, minwidth=50, anchor="w", stretch=c in ("new", "folder"))
        self.tree.tag_configure("nodata", foreground=COLOR_ERR)
        ysb = ctk.CTkScrollbar(table, command=self.tree.yview)
        self.tree.configure(yscrollcommand=ysb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        ysb.grid(row=0, column=1, sticky="ns", pady=6)
        self.tree.bind("<Double-1>", lambda _: self._hist_open())
        self.tree.bind("<Return>", lambda _: self._hist_open())
        self._hist_rows: dict[str, dict] = {}

        actions = ctk.CTkFrame(tab, fg_color="transparent")
        actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ctk.CTkButton(actions, text="Otwórz zdjęcie", command=self._hist_open).pack(side="left", padx=(0, 6))
        ctk.CTkButton(actions, text="Pokaż w folderze", fg_color="gray40", hover_color="gray30",
                      command=self._hist_show).pack(side="left", padx=(0, 6))
        ctk.CTkButton(actions, text="Przypisz zaznaczone do aktywnego ucznia", fg_color=COLOR_WARN,
                      hover_color="#c96a12", command=self._hist_assign).pack(side="left", padx=(0, 6))
        ctk.CTkButton(actions, text="Folder historii", fg_color="gray40", hover_color="gray30",
                      command=lambda: open_path(data_dir())).pack(side="right")
        ctk.CTkButton(actions, text="Eksport JSON…", fg_color="gray40", hover_color="gray30",
                      command=lambda: self._export("json")).pack(side="right", padx=6)
        ctk.CTkButton(actions, text="Eksport CSV…", fg_color="gray40", hover_color="gray30",
                      command=lambda: self._export("csv")).pack(side="right")

    def _style_tree(self):
        dark = ctk.get_appearance_mode() == "Dark"
        bg, fg, head_bg, sel = (("#2b2b2b", "#e6e6e6", "#3a3a3a", "#1f6aa5") if dark
                                else ("#ffffff", "#1a1a1a", "#e4e4e4", "#3b8ed0"))
        s = self.tree_style
        s.theme_use("clam")
        s.configure("Hist.Treeview", background=bg, fieldbackground=bg, foreground=fg,
                    rowheight=28, font=(FONT, 11), borderwidth=0)
        s.configure("Hist.Treeview.Heading", background=head_bg, foreground=fg,
                    font=(FONT, 11, "bold"), relief="flat", padding=(6, 4))
        s.map("Hist.Treeview", background=[("selected", sel)], foreground=[("selected", "white")])
        s.map("Hist.Treeview.Heading", background=[("active", head_bg)])

    # ----------------------------------------------------------- pasek stanu
    def _build_statusbar(self):
        bar = ctk.CTkFrame(self, height=30, corner_radius=0)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_columnconfigure(1, weight=1)
        self.lbl_state = ctk.CTkLabel(bar, text="", font=(FONT, 12, "bold"), width=220, anchor="w")
        self.lbl_state.grid(row=0, column=0, padx=12, pady=3)
        self.lbl_status = ctk.CTkLabel(bar, text="Gotowy.", font=(FONT, 12), anchor="w")
        self.lbl_status.grid(row=0, column=1, sticky="ew", padx=6)
        self.lbl_counts = ctk.CTkLabel(bar, text="", font=(FONT, 12), anchor="e")
        self.lbl_counts.grid(row=0, column=2, padx=12)

    def _bind_keys(self):
        self.bind_all("<Control-n>", lambda _: self.new_student())
        self.bind_all("<Control-N>", lambda _: self.new_student())
        self.bind_all("<F2>", lambda _: self.new_student())
        self.bind_all("<Control-f>", lambda _: self._focus_search())
        self.e_first.bind("<Return>", lambda _: self.e_last.focus_set())
        self.e_last.bind("<Return>", lambda _: self.e_class.focus_set())
        self.e_class.bind("<Return>", lambda _: self.focus_set())

    # ============================================================ logika
    def _current_student(self) -> Student:
        return Student(self.var_first.get(), self.var_last.get(), self.var_class.get())

    def _update_student_state(self):
        student = self._current_student()
        if student != self._student:
            self._student = student  # atomowa podmiana – czytana przez wątek watchera
        scheme, ascii_only = self._naming
        if student.is_empty:
            name = no_data_stem("DSC0001.JPG") + ".jpg"
            self.lbl_nodata.grid()
        else:
            name = build_stem(student, scheme, ascii_only) + ".jpg"
            self.lbl_nodata.grid_remove()
        self.lbl_next_name.configure(text=name)
        self.lbl_student_count.configure(text=f"Zdjęć tego ucznia w tej sesji: {self.student_count}")

    def new_student(self):
        keep = self.var_keep_class.get()
        self.var_first.set("")
        self.var_last.set("")
        if not keep:
            self.var_class.set("")
        self.student_count = 0
        self._update_student_state()
        self.tabs.set("  Sesja  ")
        self.e_first.focus_set()
        self.set_status("Nowy uczeń – wpisz imię i nazwisko.")
        return "break"

    def _on_naming_change(self):
        key = self._scheme_labels.get(self.var_scheme.get(), self.settings.scheme)
        self._naming = (key, bool(self.var_ascii.get()))
        self._update_student_state()

    def _on_theme_change(self, value):
        ctk.set_appearance_mode(value)
        self.after(50, self._style_tree)

    def _on_tab_change(self):
        if self.tabs.get().strip() == "Historia":
            self._refresh_history()
            self.after(50, self.e_search.focus_set)

    def _focus_search(self):
        self.tabs.set("  Historia  ")
        self._on_tab_change()
        return "break"

    def _choose_dir(self, var: tk.StringVar):
        path = filedialog.askdirectory(initialdir=var.get() or os.path.expanduser("~"), parent=self)
        if path:
            var.set(os.path.normpath(path))

    def _open_dir(self, path: str):
        if path and os.path.isdir(path):
            open_path(path)
        else:
            messagebox.showwarning(APP_TITLE, "Folder nie istnieje lub nie został wybrany.")

    # ------------------------------------------------------------ watcher
    def _toggle_watch(self):
        if self.watcher and self.watcher.is_alive():
            self._stop_watch()
        else:
            self._start_watch()

    def _start_watch(self):
        src = self.var_source.get().strip()
        dst = self.var_dest.get().strip()
        if not src or not os.path.isdir(src):
            messagebox.showerror(APP_TITLE, "Wybierz istniejący folder źródłowy (tethering).")
            return
        if not dst:
            messagebox.showerror(APP_TITLE, "Wybierz folder docelowy.")
            return
        if os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst)):
            messagebox.showerror(APP_TITLE, "Folder docelowy musi być inny niż folder źródłowy.")
            return
        if not os.path.isdir(dst):
            if not messagebox.askyesno(APP_TITLE, f"Folder docelowy nie istnieje:\n{dst}\n\nUtworzyć go?"):
                return
            try:
                os.makedirs(dst, exist_ok=True)
            except OSError as e:
                messagebox.showerror(APP_TITLE, f"Nie można utworzyć folderu:\n{e}")
                return
        if not os.access(dst, os.W_OK):
            messagebox.showerror(APP_TITLE, "Brak uprawnień do zapisu w folderze docelowym.")
            return

        self._save_settings()
        self.watcher = FolderWatcher(
            source=src, dest=dst, history=self.history, events=self.events,
            get_student=lambda: self._student,
            get_naming=lambda: self._naming,
            include_raw=bool(self.var_raw.get()),
            ignore_existing=bool(self.var_ignore.get()),
            stable_seconds=float(self.settings.stable_seconds),
        )
        self.watcher.start()
        for w in (self.e_source, self.e_dest, self.sw_raw, self.sw_ignore):
            w.configure(state="disabled")
        self.btn_watch.configure(text="■  Zatrzymaj nasłuchiwanie", fg_color=COLOR_STOP,
                                 hover_color=COLOR_STOP_HOVER)
        self._update_statusbar()

    def _stop_watch(self):
        if self.watcher:
            self.watcher.stop()
            self.watcher.join(timeout=3)
            self.watcher = None
        for w in (self.e_source, self.e_dest, self.sw_raw, self.sw_ignore):
            w.configure(state="normal")
        self.btn_watch.configure(text="▶  Start nasłuchiwania", fg_color=COLOR_OK, hover_color=COLOR_OK_HOVER)
        self.log("info", "Nasłuchiwanie zatrzymane.")
        self._update_statusbar()

    def _poll_events(self):
        try:
            for _ in range(50):
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self.log(ev[1], ev[2])
                elif kind == "detected":
                    name, student = ev[1], ev[2]
                    who = student.display if not student.is_empty else "BEZ DANYCH"
                    self.log("info", f"Wykryto {name} → {who}. Czekam na zakończenie zapisu…")
                    self.set_status(f"Odbieram {name}…")
                elif kind == "processed":
                    self._on_processed(ev[1], ev[2])
                elif kind == "stopped":
                    pass
        except queue.Empty:
            pass
        self.after(150, self._poll_events)

    def _on_processed(self, rec: HistoryRecord, thumb: Image.Image | None):
        self.session_count += 1
        current = self._student
        if (rec.has_data and rec.first_name == current.first.strip()
                and rec.last_name == current.last.strip() and rec.klass == current.klass.strip()):
            self.student_count += 1
        self._show_tile(rec, thumb)
        if rec.has_data:
            self.log("ok", f"{rec.original_name} → {rec.new_name}")
            self.set_status(f"Zapisano {rec.new_name}")
        else:
            self.log("error", f"{rec.original_name} → {rec.new_name}  (BRAK DANYCH UCZNIA!)")
            self.set_status(f"UWAGA: {rec.original_name} zapisano bez danych ucznia!", COLOR_ERR)
            self.bell()
        self._update_student_state()
        self._update_statusbar()
        if self.tabs.get().strip() == "Historia":
            self._refresh_history()

    def _show_tile(self, rec: HistoryRecord, thumb: Image.Image | None):
        self.last_record = rec
        if thumb is not None:
            self._preview_image = ctk.CTkImage(light_image=thumb, dark_image=thumb, size=thumb.size)
            self.lbl_image.configure(image=self._preview_image, text="")
        else:
            self._preview_image = None
            self.lbl_image.configure(image="", text="Brak podglądu\n(format RAW lub uszkodzony plik)")

        if rec.has_data:
            self.tile.configure(border_color=COLOR_OK)
            self.lbl_tile_header.configure(text="  ✔  Ostatnie zdjęcie", fg_color=COLOR_OK, text_color="white")
            self.lbl_t_name.configure(text=f"{rec.first_name} {rec.last_name}".strip(), text_color=("gray10", "gray95"))
            self.lbl_t_class.configure(text=f"Klasa: {rec.klass}" if rec.klass else "Klasa: —")
        else:
            self.tile.configure(border_color=COLOR_ERR)
            self.lbl_tile_header.configure(text="  ⚠  ZDJĘCIE BEZ DANYCH UCZNIA – uzupełnij dane i kliknij „Przypisz”",
                                           fg_color=COLOR_ERR, text_color="white")
            self.lbl_t_name.configure(text="BRAK DANYCH", text_color=COLOR_ERR)
            self.lbl_t_class.configure(text="")
        try:
            ts = datetime.fromisoformat(rec.timestamp).strftime("%H:%M:%S   (%d.%m.%Y)")
        except ValueError:
            ts = rec.timestamp
        self.lbl_t_orig.configure(text=rec.original_name)
        self.lbl_t_new.configure(text=rec.new_name)
        self.lbl_t_time.configure(text=ts)
        self.lbl_t_folder.configure(text=os.path.dirname(rec.dest_path))
        for b in (self.btn_t_open, self.btn_t_folder, self.btn_t_assign):
            b.configure(state="normal")

    # ------------------------------------------------- ponowne przypisanie
    def _reassign(self, rec: HistoryRecord) -> bool:
        student = self._current_student()
        if student.is_empty:
            messagebox.showwarning(APP_TITLE, "Najpierw wpisz imię i nazwisko aktywnego ucznia.")
            return False
        scheme, ascii_only = self._naming
        preview = build_stem(student, scheme, ascii_only)
        if not messagebox.askyesno(
                APP_TITLE,
                f"Przypisać zdjęcie {rec.original_name}\n(obecnie: {rec.new_name})\n\n"
                f"do ucznia: {student.display} {student.klass}\n"
                f"Nowa nazwa: {preview}{os.path.splitext(rec.new_name)[1].lower()}?"):
            return False
        try:
            new_path = rename_to_student(rec, student, scheme, ascii_only)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Nie udało się zmienić nazwy:\n{e}")
            return False
        old_name = rec.new_name
        rec.dest_path = new_path
        rec.new_name = os.path.basename(new_path)
        rec.first_name = student.first.strip()
        rec.last_name = student.last.strip()
        rec.klass = student.klass.strip()
        rec.has_data = True
        self.history.update_assignment(rec)
        self.log("ok", f"Przypisano ponownie: {old_name} → {rec.new_name}")
        self.set_status(f"Przypisano {rec.original_name} do {student.display}")
        return True

    def _assign_last(self):
        if self.last_record and self._reassign(self.last_record):
            self.student_count += 1
            self._show_tile(self.last_record, make_thumbnail(self.last_record.dest_path))
            self._update_student_state()
            self._refresh_history()

    # -------------------------------------------------------------- historia
    def _schedule_search(self):
        if self._search_job:
            self.after_cancel(self._search_job)
        self._search_job = self.after(150, self._refresh_history)

    def _search_text(self) -> str:
        # gdy pole pokazuje podpowiedź, CTkEntry.get() zwraca pusty tekst
        return self.e_search.get() if hasattr(self, "e_search") else ""

    def _clear_search(self):
        self.e_search.delete(0, "end")
        self._refresh_history()
        self.e_search.focus_set()

    def _refresh_history(self):
        self._search_job = None
        try:
            rows = self.history.search(self._search_text())
        except Exception as e:
            self.log("error", f"Błąd odczytu historii: {e}")
            return
        self.tree.delete(*self.tree.get_children())
        self._hist_rows.clear()
        for r in rows:
            d = dict(r)
            try:
                t = datetime.fromisoformat(d["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            except (ValueError, TypeError):
                t = d["timestamp"]
            iid = self.tree.insert("", "end", values=(
                t, d["original_name"], d["new_name"], d["first_name"] or "", d["last_name"] or "",
                d["klass"] or "", os.path.dirname(d["dest_path"] or "")),
                tags=() if d["has_data"] else ("nodata",))
            self._hist_rows[iid] = d
        total = self.history.count()
        q = self._search_text().strip()
        self.lbl_hist_count.configure(text=f"{len(rows)} z {total}" if q else f"{total} zdjęć")

    def _hist_selected(self) -> dict | None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo(APP_TITLE, "Zaznacz pozycję w historii.")
            return None
        return self._hist_rows.get(sel[0])

    def _hist_open(self):
        d = self._hist_selected()
        if d:
            if os.path.exists(d["dest_path"]):
                open_path(d["dest_path"])
            else:
                messagebox.showwarning(APP_TITLE, f"Plik nie istnieje:\n{d['dest_path']}")

    def _hist_show(self):
        d = self._hist_selected()
        if d:
            show_in_folder(d["dest_path"])

    def _hist_assign(self):
        d = self._hist_selected()
        if not d:
            return
        rec = HistoryRecord(
            id=d["id"], timestamp=d["timestamp"], original_name=d["original_name"], new_name=d["new_name"],
            first_name=d["first_name"] or "", last_name=d["last_name"] or "", klass=d["klass"] or "",
            dest_path=d["dest_path"], source_path=d["source_path"] or "", has_data=bool(d["has_data"]))
        if self._reassign(rec):
            if self.last_record and self.last_record.id == rec.id:
                self.last_record = rec
                self._show_tile(rec, make_thumbnail(rec.dest_path))
            self._refresh_history()

    def _export(self, kind: str):
        stamp = datetime.now().strftime("%Y%m%d_%H%M")
        path = filedialog.asksaveasfilename(
            parent=self, defaultextension=f".{kind}", initialfile=f"historia_zdjec_{stamp}.{kind}",
            filetypes=[("CSV (Excel)", "*.csv")] if kind == "csv" else [("JSON", "*.json")])
        if not path:
            return
        try:
            n = self.history.export_csv(path) if kind == "csv" else self.history.export_json(path)
        except OSError as e:
            messagebox.showerror(APP_TITLE, f"Eksport nie powiódł się:\n{e}")
            return
        self.log("ok", f"Wyeksportowano {n} pozycji do {path}")
        self.set_status(f"Wyeksportowano historię ({n} pozycji).")

    # ---------------------------------------------------------------- pomocnicze
    def log(self, level: str, msg: str):
        line = f"{datetime.now():%H:%M:%S}  {msg}\n"
        self.txt_log.configure(state="normal")
        self.txt_log.insert("end", line, level if LOG_COLORS.get(level) else None)
        # ogranicz dziennik do 500 linii
        lines = int(self.txt_log.index("end-1c").split(".")[0])
        if lines > 500:
            self.txt_log.delete("1.0", f"{lines - 500}.0")
        self.txt_log.see("end")
        self.txt_log.configure(state="disabled")
        if level in ("warn", "error"):
            self.set_status(msg, LOG_COLORS[level])

    def set_status(self, msg: str, color=None):
        self.lbl_status.configure(text=msg, text_color=color or ("gray10", "gray90"))

    def _update_statusbar(self):
        active = bool(self.watcher and self.watcher.is_alive())
        if active:
            self.lbl_state.configure(text="●  Nasłuchiwanie aktywne", text_color=COLOR_OK)
        else:
            self.lbl_state.configure(text="○  Nasłuchiwanie zatrzymane", text_color=COLOR_MUTED)
        try:
            total = self.history.count()
        except Exception:
            total = "?"
        self.lbl_counts.configure(text=f"Sesja: {self.session_count} zdj.   |   Historia: {total} zdj.")

    def _save_settings(self):
        s = self.settings
        s.source_dir = self.var_source.get().strip()
        s.dest_dir = self.var_dest.get().strip()
        s.scheme = self._naming[0]
        s.ascii_only = bool(self.var_ascii.get())
        s.include_raw = bool(self.var_raw.get())
        s.ignore_existing = bool(self.var_ignore.get())
        s.keep_class = bool(self.var_keep_class.get())
        s.appearance = self.var_theme.get()
        s.last_class = self.var_class.get().strip()
        s.save()

    def _on_close(self):
        if self.watcher and self.watcher.is_alive():
            if not messagebox.askyesno(APP_TITLE, "Nasłuchiwanie jest aktywne. Zamknąć program?"):
                return
            self.watcher.stop()
            self.watcher.join(timeout=3)
        # dokończ przetwarzanie zdarzeń, które już przyszły (zapis do historii jest w wątku)
        self._save_settings()
        try:
            self.history.close()
        except Exception:
            pass
        self.destroy()
