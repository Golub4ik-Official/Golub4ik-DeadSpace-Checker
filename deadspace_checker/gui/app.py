import asyncio
import logging
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import random

from deadspace_checker.config import load_file, config as cfg
from deadspace_checker.services.database_service import DatabaseService
from deadspace_checker.utils.path_utils import app_dir, bundle_dir
from deadspace_checker.utils.logging_utils import setup_logging

from .config_helper import (
    CONFIG_FILE, _CONFIG_DEFAULTS, CONFIG_OVERRIDE_MAP,
    CFG_MESSAGE_LIMIT, CFG_BAN_BYPASS_PAGES,
    CFG_TARGET_CHANNEL_ID, CFG_COMPLAINT_CHANNEL_IDS, CFG_MESSAGE_HISTORY_LIMIT,
    CFG_BASE_ADMIN_URL, CFG_ACCOUNT_URL, CFG_OPERATION_TIMEOUT, CFG_REQUEST_TIMEOUT,
    CFG_SEARCH_TIMEOUT, CFG_BATCH_TIMEOUT, CFG_TERM_TIMEOUT, CFG_MAX_CONCURRENT_REQUESTS,
    CFG_SEARCH_MAX_DEPTH, CFG_SEARCH_LIMIT_ROOT, CFG_SEARCH_LIMIT_LEVEL1, CFG_SEARCH_LIMIT_LEVEL2,
    CFG_SEARCH_LIMIT_DEFAULT, CFG_BYPASS_SEARCH_MAX_DEPTH, CFG_SEARCH_CACHE_MAX_SIZE, CFG_SEARCH_CACHE_TTL,
    CFG_CLOSE_TIME_THRESHOLD_MINUTES, CFG_TIME_THRESHOLD_MINUTES,
    CFG_SUSPICIOUS_TIME_THRESHOLD_MINUTES, CFG_IP_MATCH_TIMEDELTA_MINUTES,
)
from .widgets.log_handler import QueueLogHandler
from .widgets.queue_stream import QueueStream
from deadspace_checker.services.reporting.html_renderer import write_report_html
from deadspace_checker.services.vpn_detector import enrich_report_data

LOGO_PATH = os.path.join(bundle_dir(), "DeadSpaceLogo.png")

SPACE_COLORS = {
    "bg_deep": "#070714",
    "bg_panel": "#0f0f24",
    "bg_card": "#151530",
    "border": "#2a2a50",
    "cyan": "#22d3ee",
    "purple": "#7c3aed",
    "gold": "#fbbf24",
    "red": "#ef4444",
    "green": "#22c55e",
    "text": "#e2e8f0",
    "text_dim": "#6b7280",
    "star_white": "#ffffff",
    "star_blue": "#a5d8ff",
    "star_yellow": "#ffddaa",
    "glass": "#0a0a1e",
    "glass_border": "#2a2a5a",
}


def _force_close_loop(loop):
    if loop.is_closed():
        return
    try:
        pending = asyncio.all_tasks(loop)
        for t in pending:
            t.cancel()
    except Exception:
        pass
    try:
        if not loop.is_closed():
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                loop.run_until_complete(loop.shutdown_asyncgens())
    except Exception:
        pass
    try:
        if not loop.is_closed():
            loop.close()
    except Exception:
        pass


class BanCheckerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Golub4ik (WikiHampter) DeadSpace Checker")
        self.root.geometry("860x780")
        self.root.minsize(700, 600)
        self.root.configure(bg=SPACE_COLORS["bg_deep"])

        self.db = DatabaseService()
        self._set_icon()
        self.settings = self._load_settings()
        self.bot = None
        self.bot_loop = None
        self.running = False
        self.output_queue = queue.Queue()
        self._admin_panel_loop = None
        self._admin_panel = None
        self._twinkle_job = None
        self._stars = []
        self._twinkle_stars = []

        self._setup_styles()
        self._build_ui()
        self._fix_shortcuts()
        self._apply_settings()
        self._poll_output()
        self._animate_twinkle()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", font=("Segoe UI", 10), background=SPACE_COLORS["glass"], foreground=SPACE_COLORS["text"])
        style.configure("TFrame", background=SPACE_COLORS["glass"])
        style.configure("TLabel", background=SPACE_COLORS["glass"], foreground=SPACE_COLORS["text"])
        style.configure("TLabelFrame", background=SPACE_COLORS["glass"], foreground=SPACE_COLORS["cyan"], bordercolor=SPACE_COLORS["glass_border"], lightcolor=SPACE_COLORS["glass_border"], darkcolor=SPACE_COLORS["glass_border"])
        style.configure("TLabelframe.Label", background=SPACE_COLORS["glass"], foreground=SPACE_COLORS["cyan"], font=("Segoe UI", 10, "bold"))
        style.configure("TNotebook", background=SPACE_COLORS["bg_deep"], bordercolor=SPACE_COLORS["border"])
        style.configure("TNotebook.Tab", background=SPACE_COLORS["bg_card"], foreground=SPACE_COLORS["text_dim"], padding=[14, 6], font=("Segoe UI", 10))
        style.map("TNotebook.Tab", background=[("selected", SPACE_COLORS["bg_panel"]), ("active", SPACE_COLORS["bg_card"])], foreground=[("selected", SPACE_COLORS["cyan"])])
        style.configure("TPanedwindow", background=SPACE_COLORS["bg_deep"])
        style.configure("TSeparator", background=SPACE_COLORS["border"])
        style.configure("Vertical.TScrollbar", background=SPACE_COLORS["bg_card"], bordercolor=SPACE_COLORS["border"], arrowcolor=SPACE_COLORS["text_dim"])
        style.configure("Horizontal.TScrollbar", background=SPACE_COLORS["bg_card"], bordercolor=SPACE_COLORS["border"], arrowcolor=SPACE_COLORS["text_dim"])
        style.configure("TEntry", fieldbackground=SPACE_COLORS["bg_deep"], foreground=SPACE_COLORS["text"], bordercolor=SPACE_COLORS["border"], lightcolor=SPACE_COLORS["border"], darkcolor=SPACE_COLORS["border"])
        style.map("TEntry", fieldbackground=[("focus", "#0a0a1e")], bordercolor=[("focus", SPACE_COLORS["cyan"])])

        style.configure("Cyan.TButton", font=("Segoe UI", 10, "bold"), padding=[16, 8], background=SPACE_COLORS["cyan"], foreground=SPACE_COLORS["bg_deep"], bordercolor=SPACE_COLORS["cyan"], focuscolor="none")
        style.map("Cyan.TButton", background=[("disabled", "#1a2a3a"), ("active", "#5eead4"), ("pressed", "#0e7490")], foreground=[("disabled", "#3a5a6a"), ("active", SPACE_COLORS["bg_deep"])])
        style.configure("Red.TButton", font=("Segoe UI", 10, "bold"), padding=[16, 8], background=SPACE_COLORS["red"], foreground="#ffffff", bordercolor=SPACE_COLORS["red"], focuscolor="none")
        style.map("Red.TButton", background=[("disabled", "#2a1a1a"), ("active", "#f87171"), ("pressed", "#b91c1c")], foreground=[("disabled", "#5a3a3a"), ("active", "#ffffff")])
        style.configure("Dim.TButton", font=("Segoe UI", 10), padding=[10, 6], background=SPACE_COLORS["bg_card"], foreground=SPACE_COLORS["text_dim"], bordercolor=SPACE_COLORS["border"], focuscolor="none")
        style.map("Dim.TButton", background=[("active", SPACE_COLORS["border"]), ("pressed", "#1a1a3a")], foreground=[("active", SPACE_COLORS["text"])])
        style.configure("Gold.TButton", font=("Segoe UI", 10, "bold"), padding=[12, 6], background=SPACE_COLORS["gold"], foreground=SPACE_COLORS["bg_deep"], bordercolor=SPACE_COLORS["gold"], focuscolor="none")
        style.map("Gold.TButton", background=[("active", "#fcd34d"), ("pressed", "#b45309")])
        style.configure("Small.TButton", font=("Segoe UI", 9), padding=[6, 4], background=SPACE_COLORS["bg_card"], foreground=SPACE_COLORS["text_dim"], bordercolor=SPACE_COLORS["border"], focuscolor="none")
        style.map("Small.TButton", background=[("active", SPACE_COLORS["border"])], foreground=[("active", SPACE_COLORS["text"])])
        style.configure("TRadiobutton", background=SPACE_COLORS["bg_panel"], foreground=SPACE_COLORS["text"], font=("Segoe UI", 10))
        style.map("TRadiobutton", foreground=[("active", SPACE_COLORS["cyan"])])
        style.configure("TCheckbutton", background=SPACE_COLORS["bg_panel"], foreground=SPACE_COLORS["text"], font=("Segoe UI", 10))
        style.map("TCheckbutton", foreground=[("active", SPACE_COLORS["cyan"])])
        style.configure("TProgressbar", background=SPACE_COLORS["cyan"], troughcolor=SPACE_COLORS["bg_deep"], bordercolor=SPACE_COLORS["glass_border"], lightcolor=SPACE_COLORS["cyan"], darkcolor=SPACE_COLORS["glass"])

    def _set_icon(self):
        try:
            logo = tk.PhotoImage(file=LOGO_PATH)
            self.root.iconphoto(True, logo)
            self._logo_img = logo
        except Exception:
            pass

    def _load_settings(self):
        try:
            return self.db.gui_get_all()
        except Exception:
            return {}

    def _save_settings(self):
        try:
            self.db.gui_set_all(self.settings)
        except Exception as e:
            logging.warning(f"Failed to save GUI settings: {e}")

    def _apply_settings(self):
        self.username_var.set(self.settings.get("admin_username", ""))
        self.password_var.set(self.settings.get("admin_password", ""))
        self.token_var.set(self.settings.get("discord_token", ""))
        self.msg_count_var.set(str(self.settings.get("message_count", CFG_MESSAGE_LIMIT)))
        self.bypass_pages_var.set(str(self.settings.get("bypass_pages", CFG_BAN_BYPASS_PAGES)))
        self.auto_ban_var.set(bool(self.settings.get("auto_ban", False)))
        self.auth_cookie_var.set(self.settings.get("auth_cookie", ""))
        self.nickname_var.set(self.settings.get("last_nickname", ""))

    def _create_starfield(self, canvas):
        w = self.root.winfo_width() or 860
        h = self.root.winfo_height() or 780
        for _ in range(250):
            x = random.randint(0, w)
            y = random.randint(0, h)
            size = random.choice([1, 1, 1, 2, 2, 3])
            shade = random.random()
            if shade > 0.9:
                color = SPACE_COLORS["star_blue"]
            elif shade > 0.8:
                color = SPACE_COLORS["star_yellow"]
            else:
                gray = random.randint(160, 255)
                color = f"#{gray:02x}{gray:02x}{gray:02x}"
            star = canvas.create_oval(x, y, x + size, y + size, fill=color, outline="")
            self._stars.append(star)
            if size >= 2 and random.random() > 0.7:
                self._twinkle_stars.append(star)

    def _animate_twinkle(self):
        if not hasattr(self, '_bg_canvas') or not self._bg_canvas.winfo_exists():
            return
        if self._twinkle_stars:
            for _ in range(min(15, len(self._twinkle_stars))):
                s = random.choice(self._twinkle_stars)
                try:
                    cur = self._bg_canvas.itemcget(s, "fill")
                    if cur and cur.startswith("#"):
                        r, gb = cur[1:3], cur[3:]
                        if int(r, 16) > 200:
                            dim = random.randint(80, 140)
                            self._bg_canvas.itemconfig(s, fill=f"#{dim:02x}{dim:02x}{dim:02x}")
                        else:
                            bright = random.randint(200, 255)
                            self._bg_canvas.itemconfig(s, fill=f"#{bright:02x}{bright:02x}{bright:02x}")
                except Exception:
                    pass
        self._twinkle_job = self.root.after(800, self._animate_twinkle)

    def _build_ui(self):
        self._bg_canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg=SPACE_COLORS["bg_deep"])
        self._bg_canvas.place(x=0, y=0, relwidth=1, relheight=1)
        self.root.tk.call("lower", self._bg_canvas._w)
        self.root.update_idletasks()
        self._create_starfield(self._bg_canvas)
        self.root.bind("<Configure>", self._on_resize)

        container = tk.Frame(self.root, bg=SPACE_COLORS["bg_deep"], bd=0, highlightthickness=0)
        container.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.95, relheight=0.95)
        self.root.tk.call("raise", container._w)

        main = ttk.Frame(container, padding="6")
        main.pack(fill="both", expand=True)
        main.columnconfigure(0, weight=1)
        main.rowconfigure(2, weight=1)

        header_frame = tk.Frame(main, bg=SPACE_COLORS["bg_deep"])
        header_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        header_frame.columnconfigure(0, weight=1)
        header_frame.columnconfigure(2, weight=0)

        logo_img = None
        try:
            logo_full = tk.PhotoImage(file=LOGO_PATH)
            logo_img = logo_full.subsample(20, 20)
        except Exception:
            pass
        if logo_img:
            logo_label = tk.Label(header_frame, image=logo_img, bg=SPACE_COLORS["bg_deep"])
            logo_label.grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 8))
            self._header_logo = logo_img
        title_frame = tk.Frame(header_frame, bg=SPACE_COLORS["bg_deep"])
        title_frame.grid(row=0, column=1, sticky="w")
        tk.Label(title_frame, text="Golub4ik DeadSpace Checker", font=("Segoe UI", 15, "bold"),
                 fg=SPACE_COLORS["cyan"], bg=SPACE_COLORS["bg_deep"]).pack(anchor="w")
        tk.Label(title_frame, text="☆ Dead Space 14 ☆  Космическая Станция 14", font=("Segoe UI", 8),
                 fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_deep"]).pack(anchor="w")

        support_frame = tk.Frame(header_frame, bg=SPACE_COLORS["bg_deep"])
        support_frame.grid(row=0, column=2, rowspan=2, sticky="ne", padx=(8, 0))
        ttk.Button(support_frame, text="❤️ Поддержать", style="Gold.TButton",
                   command=self._show_support_dialog).pack()

        self._build_credentials(main)
        self._build_notebook(main)
        self.root.after(100, self._draw_glass_cards)

    def _draw_glass_cards(self):
        if not hasattr(self, '_bg_canvas') or not self._bg_canvas.winfo_exists():
            return
        try:
            self._bg_canvas.update_idletasks()
            cv_x = self._bg_canvas.winfo_rootx()
            cv_y = self._bg_canvas.winfo_rooty()
            for name, widget in [("access", getattr(self, '_cred_frame', None)),
                                 ("notebook", getattr(self, '_notebook_frame', None))]:
                if not widget or not widget.winfo_exists():
                    continue
                wx = widget.winfo_rootx() - cv_x - 4
                wy = widget.winfo_rooty() - cv_y - 4
                ww = widget.winfo_width() + 8
                wh = widget.winfo_height() + 8
                self._bg_canvas.create_rectangle(
                    wx, wy, wx + ww, wy + wh,
                    fill="#0b0b20", outline="#1e1e4a", width=1,
                )
        except Exception:
            pass

    def _on_resize(self, event):
        if hasattr(self, '_bg_canvas') and self._bg_canvas.winfo_exists():
            self._bg_canvas.delete("all")
            self._stars.clear()
            self._twinkle_stars.clear()
            self._create_starfield(self._bg_canvas)
            self.root.after(200, self._draw_glass_cards)

    def _build_credentials(self, parent):
        cred = ttk.LabelFrame(parent, text="🔐 Доступ", padding="10")
        cred.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        cred.columnconfigure(1, weight=1)
        self._cred_frame = cred

        self.username_var = tk.StringVar()
        self.password_var = tk.StringVar()
        self.token_var = tk.StringVar()
        self.show_secrets = tk.BooleanVar(value=False)

        row = 0
        tk.Label(cred, text="Администратор:", font=("Segoe UI", 10),
                 fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["glass"]).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        ttk.Entry(cred, textvariable=self.username_var).grid(row=row, column=1, sticky="ew", pady=2)
        row += 1

        tk.Label(cred, text="Пароль:", font=("Segoe UI", 10),
                 fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["glass"]).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        self.pw_entry = ttk.Entry(cred, textvariable=self.password_var, show="*")
        self.pw_entry.grid(row=row, column=1, sticky="ew", pady=2)
        row += 1

        tk.Label(cred, text="Discord токен:", font=("Segoe UI", 10),
                 fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["glass"]).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        token_frame = ttk.Frame(cred)
        token_frame.grid(row=row, column=1, sticky="ew", pady=2)
        token_frame.columnconfigure(0, weight=1)
        self.tk_entry = ttk.Entry(token_frame, textvariable=self.token_var, show="*")
        self.tk_entry.grid(row=0, column=0, sticky="ew", padx=(0, 4))
        ttk.Button(token_frame, text="?", width=2, style="Small.TButton", command=self._show_token_help).grid(row=0, column=1)
        row += 1

        tk.Label(cred, text="Auth cookie (опц.):", font=("Segoe UI", 10),
                 fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["glass"]).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)
        auth_cookie_frame = ttk.Frame(cred)
        auth_cookie_frame.grid(row=row, column=1, sticky="ew", pady=2)
        auth_cookie_frame.columnconfigure(0, weight=1)
        self.auth_cookie_var = tk.StringVar()
        ttk.Entry(auth_cookie_frame, textvariable=self.auth_cookie_var, show="*").grid(row=0, column=0, sticky="ew")
        row += 1

        btn_row = ttk.Frame(cred)
        btn_row.grid(row=row, column=1, sticky="e", pady=(6, 0))
        ttk.Checkbutton(btn_row, text="👁 Показать", variable=self.show_secrets,
                        command=self._toggle_secrets).pack(side="left", padx=(0, 8))
        ttk.Button(btn_row, text="💾 Сохранить настройки",
                   style="Dim.TButton", command=self._on_save).pack(side="left")

    def _build_notebook(self, parent):
        notebook = ttk.Notebook(parent)
        notebook.grid(row=2, column=0, sticky="nsew", pady=(0, 0))
        parent.rowconfigure(2, weight=1)
        self._notebook_frame = notebook

        self._build_scan_tab(notebook)
        self._build_ban_tab(notebook)
        self._on_mode_change()

    def _build_scan_tab(self, notebook):
        scan_tab = ttk.Frame(notebook, padding="8")
        notebook.add(scan_tab, text="🔍 Поиск")
        scan_tab.columnconfigure(0, weight=1)
        scan_tab.rowconfigure(3, weight=1)

        self._build_scan_mode(scan_tab)
        self._build_scan_actions(scan_tab)
        self._build_progress(scan_tab)
        self._build_status_log(scan_tab)

    def _build_scan_mode(self, parent):
        mode = ttk.LabelFrame(parent, text="🎯 Режим сканирования", padding="10")
        mode.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        mode.columnconfigure(1, weight=1)

        self.scan_mode = tk.StringVar(value="username")
        ttk.Radiobutton(mode, text="🔎 Пробив игрока по нику",
                        variable=self.scan_mode, value="username",
                        command=self._on_mode_change).grid(row=0, column=0, columnspan=2, sticky="w", pady=1)
        ttk.Radiobutton(mode, text="🛡 Проверка обхода банов",
                        variable=self.scan_mode, value="banbypass",
                        command=self._on_mode_change).grid(row=1, column=0, columnspan=2, sticky="w", pady=1)

        ttk.Label(mode, text="Имя игрока:").grid(row=2, column=0, sticky="w", padx=(24, 4), pady=(10, 2))
        self.nickname_var = tk.StringVar()
        self.nickname_entry = ttk.Entry(mode, textvariable=self.nickname_var)
        self.nickname_entry.grid(row=2, column=1, sticky="ew", pady=(10, 2))

        params = ttk.Frame(mode)
        params.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        params.columnconfigure(1, weight=1)
        params.columnconfigure(3, weight=1)

        ttk.Label(params, text="Кол-во сообщений:").grid(row=0, column=0, sticky="w", padx=(24, 2))
        self.msg_count_var = tk.StringVar(value="10")
        ttk.Entry(params, textvariable=self.msg_count_var, width=8).grid(row=0, column=1, sticky="w")

        ttk.Label(params, text="Страниц обхода:").grid(row=0, column=2, sticky="w", padx=(12, 2))
        self.bypass_pages_var = tk.StringVar(value="3")
        ttk.Entry(params, textvariable=self.bypass_pages_var, width=8).grid(row=0, column=3, sticky="w")

        self.auto_ban_var = tk.BooleanVar(value=False)
        self.auto_ban_cb = ttk.Checkbutton(params, text="⚡ Авто-бан IP/HWID",
                                           variable=self.auto_ban_var)
        self.auto_ban_cb.grid(row=1, column=0, columnspan=4, sticky="w", padx=(24, 2), pady=(4, 0))

    def _build_scan_actions(self, parent):
        actions = ttk.Frame(parent)
        actions.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        self.start_btn = ttk.Button(actions, text="▶ Запуск", style="Cyan.TButton", command=self._on_start)
        self.start_btn.pack(side="left", padx=(0, 8))
        self.stop_btn = ttk.Button(actions, text="■ Остановить", style="Red.TButton", command=self._on_stop, state="disabled")
        self.stop_btn.pack(side="left")
        self.config_btn = ttk.Button(actions, text="⚙️", width=3, style="Small.TButton", command=self._open_config_dialog)
        self.config_btn.pack(side="left", padx=(8, 0))

    def _build_progress(self, parent):
        progress_frame = ttk.LabelFrame(parent, text="⏳ Прогресс", padding="8")
        progress_frame.grid(row=2, column=0, sticky="ew", pady=(0, 6))
        progress_frame.columnconfigure(1, weight=1)

        self.progress_var = tk.IntVar(value=0)
        self.progress_bar = ttk.Progressbar(
            progress_frame, mode="determinate",
            variable=self.progress_var, length=200
        )
        self.progress_bar.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.progress_label = tk.Label(progress_frame, text="",
                                        font=("Segoe UI", 10), fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["glass"])
        self.progress_label.grid(row=0, column=1, sticky="w")

    def _build_status_log(self, parent):
        out = ttk.LabelFrame(parent, text="📋 Статус", padding="4")
        out.grid(row=3, column=0, sticky="nsew", pady=(4, 0))
        out.columnconfigure(0, weight=1)
        out.rowconfigure(0, weight=1)

        self.output_text = scrolledtext.ScrolledText(
            out, wrap="word", font=("Consolas", 9),
            bg="#0a0a1a", fg="#94a3b8", insertbackground=SPACE_COLORS["cyan"],
            highlightbackground=SPACE_COLORS["border"], highlightcolor=SPACE_COLORS["cyan"],
            highlightthickness=1, bd=0,
        )
        self.output_text.grid(row=0, column=0, sticky="nsew")
        self.output_text.tag_configure("error", foreground=SPACE_COLORS["red"])
        self.output_text.tag_configure("success", foreground=SPACE_COLORS["green"])
        self.output_text.tag_configure("info", foreground=SPACE_COLORS["cyan"])
        self.output_text.tag_configure("warning", foreground=SPACE_COLORS["gold"])
        self.output_text.tag_configure("dim", foreground=SPACE_COLORS["text_dim"])

    def _build_ban_tab(self, notebook):
        ban_tab = ttk.Frame(notebook, padding="8")
        notebook.add(ban_tab, text="🔨 Блокировка")
        ban_tab.columnconfigure(0, weight=1)
        ban_tab.rowconfigure(2, weight=1)

        input_frame = ttk.LabelFrame(ban_tab, text="🎯 Цели (HWID / IP / Username — по одному на строку)", padding="6")
        input_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        input_frame.columnconfigure(0, weight=1)
        input_frame.rowconfigure(0, weight=1)

        self.ban_targets_text = scrolledtext.ScrolledText(
            input_frame, wrap="none", font=("Consolas", 9),
            bg="#0a0a1a", fg="#94a3b8", insertbackground=SPACE_COLORS["cyan"],
            highlightbackground=SPACE_COLORS["border"], highlightcolor=SPACE_COLORS["cyan"],
            highlightthickness=1, bd=0, height=5,
        )
        self.ban_targets_text.grid(row=0, column=0, sticky="nsew")

        opts_frame = ttk.LabelFrame(ban_tab, text="⚙ Параметры блокировки", padding="8")
        opts_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        opts_frame.columnconfigure(1, weight=1)

        ttk.Label(opts_frame, text="Причина:").grid(row=0, column=0, sticky="w", padx=(0, 6), pady=2)
        self.ban_reason_var = tk.StringVar(value="Перманентная блокировка, Правило 0: Набегатор или твинк набегатора, обход блокировки путём создания нового аккаунта. Бан в реестр. Обжалование в Discord")
        reason_entry = ttk.Entry(opts_frame, textvariable=self.ban_reason_var)
        reason_entry.grid(row=0, column=1, sticky="ew", pady=2)

        preset_frame = ttk.Frame(opts_frame)
        preset_frame.grid(row=0, column=2, padx=(4, 0), pady=2)
        ttk.Button(preset_frame, text="📋 Пресеты", style="Small.TButton", command=self._show_ban_reason_presets).pack(side="left")
        ttk.Button(preset_frame, text="🔄 Сброс", style="Small.TButton", command=self._reset_ban_reason).pack(side="left", padx=(2, 0))

        chk_frame = ttk.LabelFrame(opts_frame, text="Дополнительно", padding="4")
        chk_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(6, 0))

        self.use_latest_ip_var = tk.BooleanVar(value=False)
        self.use_latest_hwid_var = tk.BooleanVar(value=True)

        ttk.Checkbutton(chk_frame, text="📍 Забанить последний IP (если бан по нику)",
                        variable=self.use_latest_ip_var).grid(row=0, column=0, sticky="w", pady=2, padx=4)
        ttk.Checkbutton(chk_frame, text="🔑 Забанить последний HWID (если бан по нику)",
                        variable=self.use_latest_hwid_var).grid(row=0, column=1, sticky="w", pady=2, padx=4)

        ttk.Label(opts_frame, text="Длительность (мин, 0 = навсегда):").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=2)
        self.ban_minutes_var = tk.StringVar(value="0")
        ttk.Entry(opts_frame, textvariable=self.ban_minutes_var, width=10).grid(row=2, column=1, sticky="w", pady=2)

        btn_frame = ttk.Frame(opts_frame)
        btn_frame.grid(row=3, column=0, columnspan=3, sticky="e", pady=(6, 0))
        self.ban_execute_btn = ttk.Button(btn_frame, text="🔨 Выдать блокировку", style="Red.TButton", command=self._on_ban_execute)
        self.ban_execute_btn.pack(side="right")

        results_frame = ttk.LabelFrame(ban_tab, text="📋 Результат", padding="4")
        results_frame.grid(row=2, column=0, sticky="nsew")
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(0, weight=1)

        self.ban_result_text = scrolledtext.ScrolledText(
            results_frame, wrap="word", font=("Consolas", 9),
            bg="#0a0a1a", fg="#94a3b8", insertbackground=SPACE_COLORS["cyan"],
            highlightbackground=SPACE_COLORS["border"], highlightcolor=SPACE_COLORS["cyan"],
            highlightthickness=1, bd=0, state="disabled",
        )
        self.ban_result_text.grid(row=0, column=0, sticky="nsew")

    def _fix_shortcuts(self):
        self.root.bind_all("<KeyPress>", self._on_global_keypress, add=True)

    def _on_global_keypress(self, event):
        if not (event.state & 0x0004):
            return None
        if re.match(r'^[a-z]$', event.keysym):
            return None
        action = {67: "<<Copy>>", 86: "<<Paste>>", 88: "<<Cut>>", 65: "<<SelectAll>>"}.get(event.keycode)
        if action and isinstance(event.widget, (tk.Text, tk.Entry)):
            try:
                event.widget.event_generate(action)
                return "break"
            except Exception:
                pass
        return None

    def _toggle_secrets(self):
        show = "" if self.show_secrets.get() else "*"
        self.pw_entry.config(show=show)
        self.tk_entry.config(show=show)

    @staticmethod
    def _show_token_help():
        msg = (
            "Как получить Discord токен:\n\n"
            "1. Откройте Discord (десктоп или браузер)\n"
            "2. Нажмите F12 (или Ctrl+Shift+I)\n"
            "3. Перейдите на вкладку Network\n"
            "4. Отправьте любое сообщение в чат\n"
            "5. В списке запросов нажмите на любой\n"
            "   запрос к discord.com/api/\n"
            "6. В правой панели найдите заголовок\n"
            "   authorization: и скопируйте его значение\n"
        )
        messagebox.showinfo("Как получить токен Discord", msg)

    def _show_support_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("❤️ Поддержать автора")
        dialog.geometry("480x340")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=SPACE_COLORS["bg_panel"])

        frame = tk.Frame(dialog, bg=SPACE_COLORS["bg_panel"], padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="❤️ Спасибо, что используете DeadSpace Checker!",
                 font=("Segoe UI", 14, "bold"), fg=SPACE_COLORS["cyan"],
                 bg=SPACE_COLORS["bg_panel"]).pack(anchor="w")
        tk.Label(frame, text="Если проект оказался полезным, вы можете поддержать автора:",
                 font=("Segoe UI", 10), fg=SPACE_COLORS["text"],
                 bg=SPACE_COLORS["bg_panel"], wraplength=440).pack(anchor="w", pady=(8, 12))

        sep = tk.Frame(frame, bg=SPACE_COLORS["border"], height=1)
        sep.pack(fill="x", pady=(0, 12))

        def make_row(label, value, copy_val=None):
            row = tk.Frame(frame, bg=SPACE_COLORS["bg_panel"])
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=("Segoe UI", 10, "bold"),
                     fg=SPACE_COLORS["gold"], bg=SPACE_COLORS["bg_panel"],
                     width=14, anchor="w").pack(side="left")
            tk.Label(row, text=value, font=("Consolas", 10),
                     fg=SPACE_COLORS["text"], bg=SPACE_COLORS["bg_panel"]).pack(side="left", padx=(4, 0))
            if copy_val:
                btn = ttk.Button(row, text="📋", width=2, style="Small.TButton",
                                 command=lambda v=copy_val: self.root.clipboard_append(v))
                btn.pack(side="left", padx=(4, 0))

        make_row("Карта Сбербанк:", "2202 2068 9547 6567", "2202206895476567")
        make_row("Boosty:", "boosty.to/golub4ik")
        make_row("Steam:", "osnova_golubia")

        tk.Frame(frame, bg=SPACE_COLORS["border"], height=1).pack(fill="x", pady=(12, 4))
        tk.Label(frame, text="💡 Boosty пока не работает, но скоро будет доступен",
                 font=("Segoe UI", 9), fg=SPACE_COLORS["text_dim"],
                 bg=SPACE_COLORS["bg_panel"], wraplength=440).pack(anchor="w")

        btn_row = tk.Frame(frame, bg=SPACE_COLORS["bg_panel"])
        btn_row.pack(fill="x", pady=(12, 0))
        ttk.Button(btn_row, text="Закрыть", style="Dim.TButton",
                   command=dialog.destroy).pack(side="right")

    def _on_mode_change(self):
        mode = self.scan_mode.get()
        self.nickname_entry.config(state="normal" if mode == "username" else "disabled")
        self.auto_ban_cb.config(state="normal" if mode == "banbypass" else "disabled")

    def _on_save(self):
        self.settings["admin_username"] = self.username_var.get()
        self.settings["admin_password"] = self.password_var.get()
        self.settings["discord_token"] = self.token_var.get()
        self.settings["auth_cookie"] = self.auth_cookie_var.get()
        self.settings["last_nickname"] = self.nickname_var.get()
        try:
            self.settings["message_count"] = int(self.msg_count_var.get())
        except ValueError:
            pass
        try:
            self.settings["bypass_pages"] = int(self.bypass_pages_var.get())
        except ValueError:
            pass
        self.settings["auto_ban"] = bool(self.auto_ban_var.get())
        self._save_settings()
        messagebox.showinfo("", "Настройки сохранены")

    def _show_first_run_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Первый запуск — предупреждение")
        dialog.geometry("520x350")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=SPACE_COLORS["bg_panel"])

        frame = tk.Frame(dialog, bg=SPACE_COLORS["bg_panel"], padx=20, pady=20)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="⚠ ПЕРВЫЙ ЗАПУСК", font=("Segoe UI", 14, "bold"),
                 fg=SPACE_COLORS["gold"], bg=SPACE_COLORS["bg_panel"]).pack(anchor="w")
        tk.Label(frame, text="Данные о наказаниях ещё не загружены.",
                 font=("Segoe UI", 10), fg=SPACE_COLORS["text"], bg=SPACE_COLORS["bg_panel"],
                 wraplength=460).pack(anchor="w", pady=(10, 4))
        tk.Label(frame, text=(
            "Скачиваются все сообщения из каналов жалоб Discord.\n"
            "В среднем это занимает 10–15 минут."
        ), font=("Segoe UI", 10), fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"],
                 wraplength=460).pack(anchor="w", pady=(0, 4))
        tk.Label(frame, text=(
            "Это нормально. После завершения данные сохранятся локально, "
            "и следующие запуски будут быстрыми."
        ), font=("Segoe UI", 10), fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"],
                 wraplength=460).pack(anchor="w")

        link_frame = tk.Frame(frame, bg=SPACE_COLORS["bg_panel"])
        link_frame.pack(fill="x", pady=(10, 4))
        tk.Label(link_frame, text="💡 Совет: ", font=("Segoe UI", 10, "bold"),
                 fg=SPACE_COLORS["cyan"], bg=SPACE_COLORS["bg_panel"]).pack(side="left")
        tk.Label(link_frame, text=(
            "можно скачать уже готовую базу в разделе Releases — "
            "положить deadspace_checker.db рядом с программой и запустить сразу"
        ), font=("Segoe UI", 10), fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"],
                 wraplength=400).pack(side="left")

        sep = tk.Frame(frame, bg=SPACE_COLORS["border"], height=1)
        sep.pack(fill="x", pady=(10, 10))

        btn_frame = tk.Frame(frame, bg=SPACE_COLORS["bg_panel"])
        btn_frame.pack(fill="x")

        def make_start_btn():
            start_btn = ttk.Button(btn_frame, text=f"Начать сканирование (через 10с)",
                                   style="Cyan.TButton", state="disabled",
                                   command=lambda: self._on_first_run_confirm(dialog))
            start_btn.pack(side="right", padx=(6, 0))

            def tick(countdown=[10]):
                countdown[0] -= 1
                if countdown[0] > 0:
                    start_btn.config(text=f"Начать сканирование (через {countdown[0]}с)")
                    dialog.after(1000, tick)
                else:
                    start_btn.config(text="Начать сканирование", state="normal")
            dialog.after(1000, tick)
            return start_btn

        make_start_btn()
        ttk.Button(btn_frame, text="Отмена", style="Dim.TButton", command=dialog.destroy).pack(side="right")

        self.root.wait_window(dialog)
        return getattr(self, "_first_run_confirmed", False)

    def _on_first_run_confirm(self, dialog):
        self._first_run_confirmed = True
        dialog.destroy()

    def _show_banbypass_info_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("🛡 Проверка обхода банов")
        dialog.configure(bg=SPACE_COLORS["bg_panel"])
        dialog.resizable(False, False)
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() - 500) // 2
        y = (dialog.winfo_screenheight() - 280) // 2
        dialog.geometry(f"500x280+{x}+{y}")

        frame = tk.Frame(dialog, bg=SPACE_COLORS["bg_panel"], padx=20, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="🛡 Проверка обхода банов",
                 font=("Segoe UI", 14, "bold"), fg=SPACE_COLORS["cyan"],
                 bg=SPACE_COLORS["bg_panel"]).pack(anchor="w")

        sep = tk.Frame(frame, bg=SPACE_COLORS["border"], height=1)
        sep.pack(fill="x", pady=(10, 10))

        tk.Label(frame, text="Количество страниц влияет на глубину сканирования:",
                 font=("Segoe UI", 10), fg=SPACE_COLORS["text"],
                 bg=SPACE_COLORS["bg_panel"], wraplength=460).pack(anchor="w", pady=(0, 6))
        tk.Label(frame, text=(
            "• 1 страница ≈ 2000 записей — быстро, только свежие баны\n"
            "• 3-5 страниц — рекомендуемый баланс\n"
            "• 10+ страниц — может сканироваться 10-30 минут"
        ), font=("Segoe UI", 10), fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"],
                 wraplength=460, justify="left").pack(anchor="w", pady=(0, 4))

        sep2 = tk.Frame(frame, bg=SPACE_COLORS["border"], height=1)
        sep2.pack(fill="x", pady=(10, 10))

        btn_frame = tk.Frame(frame, bg=SPACE_COLORS["bg_panel"])
        btn_frame.pack(fill="x")

        confirmed = [False]

        def confirm():
            confirmed[0] = True
            dialog.destroy()

        start_btn = ttk.Button(btn_frame, text="Начать сканирование (через 5с)",
                               style="Cyan.TButton", state="disabled",
                               command=confirm)
        start_btn.pack(side="right", padx=(6, 0))

        def tick(countdown=[5]):
            countdown[0] -= 1
            if countdown[0] > 0:
                start_btn.config(text=f"Начать сканирование (через {countdown[0]}с)")
                dialog.after(1000, tick)
            else:
                start_btn.config(text="Начать сканирование", state="normal")
        dialog.after(1000, tick)

        ttk.Button(btn_frame, text="Отмена", style="Dim.TButton",
                   command=dialog.destroy).pack(side="right")

        self.root.wait_window(dialog)
        return confirmed[0]

    def _on_start(self):
        if not self.username_var.get() or not self.password_var.get():
            messagebox.showerror("Ошибка", "Укажите ADMIN_USERNAME и ADMIN_PASSWORD")
            return
        if not self.token_var.get() and self.scan_mode.get() not in ("banbypass",):
            messagebox.showerror("Ошибка", "Укажите DISCORD_TOKEN")
            return

        mode = self.scan_mode.get()
        nickname = self.nickname_var.get()
        if mode == "username" and not nickname:
            messagebox.showerror("Ошибка", "Укажите имя игрока для пробива")
            return

        if mode == "banbypass":
            if not self._show_banbypass_info_dialog():
                return

        complaint_count = self.db.complaint_channel_count()
        if complaint_count == 0:
            if not self._show_first_run_dialog():
                return

        self.output_text.delete("1.0", tk.END)
        self.progress_var.set(0)
        self.progress_label.config(text="")
        self._scan_start = time.time()
        self._last_progress_msg = ""
        self._log("▶ Запуск сканирования...\n", "info")

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.running = True

        thread_args = (
            self.username_var.get(),
            self.password_var.get(),
            self.token_var.get(),
            mode,
            nickname,
            int(self.msg_count_var.get()),
            int(self.bypass_pages_var.get()),
        )
        threading.Thread(target=self._run_bot, args=thread_args, daemon=True).start()

    def _run_bot(self, admin_username, admin_password, discord_token,
                 scan_mode, scan_nickname, msg_limit, bypass_pages):
        original_stdout = sys.stdout

        self._cleanup_previous_bot()

        try:
            log_format = logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s")

            setup_logging(log_file=None, level=logging.INFO, use_colors=False)
            for h in logging.getLogger().handlers:
                logging.getLogger().removeHandler(h)

            queue_handler = QueueLogHandler(self.output_queue, log_format)
            logging.getLogger().addHandler(queue_handler)
            logging.getLogger().setLevel(logging.INFO)

            discord_logger = logging.getLogger("discord")
            discord_logger.setLevel(logging.WARNING)
            discord_logger.addHandler(queue_handler)

            sys.stdout = QueueStream(self.output_queue)

            load_file(CONFIG_FILE, cfg)
            self._apply_config_overrides()

            cfg.auth.admin_username = admin_username
            cfg.auth.admin_password = admin_password
            cfg.discord.discord_user_token = discord_token

            cfg.scan.username = scan_nickname if scan_mode == "username" else None
            cfg.scan.check_ban_bypass = scan_mode == "banbypass"
            cfg.scan.message_limit = msg_limit
            cfg.scan.ban_bypass_pages = bypass_pages
            cfg.scan.auto_ban_enabled = bool(self.settings.get("auto_ban", False)) and scan_mode == "banbypass"
            cfg.scan.html_report_mode = scan_mode == "banbypass"
            cfg.logging.log_level = "INFO"

            logging.info("Starting Ban Checker Bot")
            mode_desc = (
                f"Username: {cfg.scan.username}" if cfg.scan.username else
                "Ban Bypass Check" if cfg.scan.check_ban_bypass else
                f"Messages: {cfg.scan.message_limit}"
            )
            logging.info(f"Scan mode: {mode_desc}")

            from deadspace_checker.admin import AdminPanel
            admin_panel = AdminPanel(cfg.auth.admin_username, cfg.auth.admin_password)
            self._admin_panel = admin_panel

            from deadspace_checker.discord_bot import BanCheckerBot
            bot_config = {
                "TARGET_CHANNEL_ID": cfg.discord.target_channel_id,
                "COMPLAINT_CHANNEL_IDS": cfg.discord.complaint_channel_ids,
                "COMPLAINT_MESSAGE_HISTORY_LIMIT": cfg.discord.message_history_limit,
                "message_limit": cfg.scan.message_limit,
                "username": cfg.scan.username,
                "check_ban_bypass": cfg.scan.check_ban_bypass,
                "ban_bypass_pages": cfg.scan.ban_bypass_pages,
                "html_report_filename": cfg.report.html_report_filename,
                "graph_format": cfg.report.graph_format,
                "graph_output": cfg.report.graph_output,
                "message_interval_start": None,
                "message_interval_end": None,
                "html_report_mode": cfg.scan.html_report_mode,
                "auth_cookie": self.settings.get("auth_cookie", ""),
            }

            logging.info(f"Discord token length: {len(discord_token)}, starts with: {discord_token[:10]}...")

            bot = BanCheckerBot(discord_token, admin_panel, bot_config, progress_queue=self.output_queue)
            self.bot = bot

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self.bot_loop = loop
            self._admin_panel_loop = loop
            try:
                if cfg.scan.html_report_mode:
                    loop.run_until_complete(bot.run_offline())
                else:
                    loop.run_until_complete(bot.client.start(discord_token))
            except asyncio.CancelledError:
                self.output_queue.put("\n⏹ Сканирование остановлено\n")
            except Exception as e:
                if type(e).__name__ == 'LoginFailure' or 'Improper token' in str(e):
                    self.output_queue.put("__DISCORD_TOKEN_ERROR__")
                self.output_queue.put(f"\nОшибка: {e}\n")
                import traceback
                self.output_queue.put(traceback.format_exc() + "\n")
        finally:
            self._cleanup_loop()
            sys.stdout = original_stdout
            if self.bot and hasattr(self.bot, 'admin_service') and self.bot.admin_service:
                panel = self.bot.admin_service.admin_panel
                if getattr(panel, '_sso_unreachable', False):
                    self.output_queue.put("__AUTH_ERROR__")
                elif getattr(panel, '_login_error_reason', '') in ("invalid_credentials", "2fa_required", "captcha"):
                    self.output_queue.put("__SS14_CREDENTIALS_ERROR__")
            self.bot = None
            self.bot_loop = None
            self.output_queue.put(f"\n{'─'*50}\nПроцесс завершён\n")
            self.output_queue.put("__DONE__")

    def _cleanup_previous_bot(self):
        loop = getattr(self, 'bot_loop', None)
        if loop and not loop.is_closed():
            try:
                if loop.is_running():
                    async def _do_close():
                        if self.bot:
                            try:
                                await self.bot.close()
                            except Exception:
                                pass
                        _force_close_loop(loop)
                    future = asyncio.run_coroutine_threadsafe(_do_close(), loop)
                    future.result(timeout=10)
                else:
                    try:
                        if self.bot:
                            loop.run_until_complete(self.bot.close())
                    except Exception:
                        pass
                    _force_close_loop(loop)
            except Exception:
                pass
        self.bot_loop = None
        self.bot = None

    def _cleanup_loop(self):
        loop = getattr(self, 'bot_loop', None)
        if loop and not loop.is_closed():
            try:
                if loop.is_running():
                    async def _full_cleanup():
                        try:
                            if self.bot:
                                await self.bot.close()
                        except Exception:
                            pass
                        _force_close_loop(loop)
                    asyncio.run_coroutine_threadsafe(_full_cleanup(), loop).result(timeout=10)
                else:
                    try:
                        if self.bot:
                            loop.run_until_complete(self.bot.close())
                    except Exception:
                        pass
                    _force_close_loop(loop)
            except Exception:
                pass

    def _log(self, text, tag=None):
        if tag:
            self.output_text.insert(tk.END, text, tag)
        else:
            self.output_text.insert(tk.END, text)
        self.output_text.see(tk.END)

    def _poll_output(self):
        try:
            processed = 0
            while processed < 200:
                item = self.output_queue.get_nowait()
                processed += 1

                if isinstance(item, dict):
                    msg_type = item.get("type", "")
                    if msg_type == "progress":
                        cur = item.get("current", 0)
                        total = item.get("total", 1)
                        pct = int(cur / max(total, 1) * 100)
                        self.progress_var.set(pct)
                        msg = item.get("msg", "")
                        if msg:
                            self._last_progress_msg = msg
                    elif msg_type == "progress_done":
                        self.progress_var.set(100)
                        self.progress_label.config(text="✅ Завершено")
                    elif msg_type == "log":
                        text = item.get("text", "")
                        if not text:
                            continue
                        self._log(text, "dim")
                elif isinstance(item, str):
                    if item == "__DONE__":
                        self.running = False
                        self.start_btn.config(state="normal")
                        self.stop_btn.config(state="disabled")
                        self.progress_var.set(100)
                        self.progress_label.config(text="✅ Завершено")
                        self._scan_start = None
                        self._last_progress_msg = ""
                        self.root.after(500, self._auto_generate_report)
                    elif item == "__AUTH_ERROR__":
                        messagebox.showerror(
                            "Ошибка подключения",
                            "Не удалось подключиться к серверу авторизации account.spacestation14.com.\n\n"
                            "Попробуйте:\n"
                            "• Перезапустить ПК\n"
                            "• Перезапустить VPN/Zapret\n"
                            "• Проверить подключение к интернету\n"
                            "• Запустить от имени администратора"
                        )
                    elif item == "__DISCORD_TOKEN_ERROR__":
                        messagebox.showerror(
                            "Ошибка Discord Token",
                            "Указан неверный Discord токен.\n\n"
                            "Как получить токен:\n"
                            "1. Откройте Discord в браузере\n"
                            "2. Нажмите F12 (Инструменты разработчика)\n"
                            "3. Перейдите на вкладку Console\n"
                            "4. Вставьте: (localStorage.getItem('token') || '').replace(/[\"']/g, '')\n"
                            "5. Скопируйте полученный токен\n\n"
                            "Либо:\n"
                            "1. F12 → Application → Local Storage\n"
                            "2. Найдите ключ 'token' и скопируйте его значение\n"
                            "3. Убедитесь, что копируете без кавычек"
                        )
                    elif item == "__SS14_CREDENTIALS_ERROR__":
                        messagebox.showerror(
                            "Ошибка авторизации SS14",
                            "Не удалось войти в админ-панель Space Station 14.\n\n"
                            "Убедитесь, что:\n"
                            "• Логин и пароль от аккаунта Space Station 14 (не от Discord)\n"
                            "• Двухэтапная аутентификация (2FA) отключена\n"
                            "• Аккаунт имеет доступ к админ-панели\n"
                            "• Логин и пароль введены без ошибок"
                        )
                    elif item == "__BAN_DONE__":
                        self.ban_execute_btn.config(state="normal")
                    elif re.match(r'^\d{4}-\d{2}-\d{2}', item) or 'API Calls=' in item or 'Depth Dist=' in item:
                        continue
                    else:
                        self._log(item, "dim")
                        self._ban_log(item)

            self.output_text.see(tk.END)
        except queue.Empty:
            pass

        if getattr(self, '_scan_start', None) and getattr(self, '_last_progress_msg', None):
            dt = time.time() - self._scan_start
            if dt >= 3600:
                elapsed = f"{int(dt//3600)}ч {int((dt%3600)//60)}м {int(dt%60)}с"
            elif dt >= 60:
                elapsed = f"{int(dt//60)}м {int(dt%60)}с"
            else:
                elapsed = f"{int(dt)}с"
            self.progress_label.config(text=f"{self._last_progress_msg}  ⏱ {elapsed}")

        self.root.after(50, self._poll_output)

    def _on_stop(self):
        self.running = False
        self._cleanup_previous_bot()
        self._log("\n⏹ Остановлено\n", "warning")
        self.start_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.progress_label.config(text="⏹ Остановлено")
        self._scan_start = None
        self._last_progress_msg = ""

    def _auto_generate_report(self):
        if self.scan_mode.get() == "banbypass":
            return
        report_dir = os.path.join(app_dir(), "reports")
        json_path = os.path.join(report_dir, "scan_report.json")
        if not os.path.exists(json_path):
            self._log(f"\n⚠ Файл отчёта не найден: {json_path}\n", "warning")
            return
        try:
            import json
            with open(json_path, encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self._log(f"\n❌ Ошибка чтения отчёта: {e}\n", "error")
            return

        self._log("\n🔍 Проверка IP на VPN...\n", "info")
        try:
            enrich_report_data(data)
        except Exception:
            pass

        out_path = os.path.join(report_dir, "scan_report.html")
        write_report_html(data, out_path, LOGO_PATH)
        self._log(f"\n✅ HTML-отчёт открыт в браузере: {out_path}\n", "success")

        primary = data[0].get("primary_nickname", data[0].get("nickname", "report")) if data else "report"
        save_to = filedialog.asksaveasfilename(
            parent=self.root,
            title="Сохранить HTML-отчёт как",
            defaultextension=".html",
            initialfile=f"{primary}.html",
            filetypes=[("HTML files", "*.html"), ("All files", "*.*")]
        )
        if save_to:
            try:
                with open(save_to, 'w', encoding='utf-8') as f:
                    f.write(write_report_html(data, out_path, LOGO_PATH))
                self._log(f"💾 Отчёт сохранён: {save_to}\n", "success")
            except Exception as e:
                self._log(f"❌ Ошибка сохранения: {e}\n", "error")

    def _apply_config_overrides(self):
        overrides = self.settings.get("config", {})
        if not overrides:
            return
        for name, value in overrides.items():
            path = CONFIG_OVERRIDE_MAP.get(name)
            if path is None:
                continue
            parent = getattr(cfg, path[0])
            setattr(parent, path[1], value)

    def _open_config_dialog(self):
        import ast
        dialog = tk.Toplevel(self.root)
        dialog.title("Настройки конфигурации")
        dialog.geometry("640x520")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=SPACE_COLORS["bg_panel"])

        overrides = dict(self.settings.get("config", {}))

        def _val(name, default):
            return overrides.get(name, default)

        notebook = ttk.Notebook(dialog)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        def make_entry(parent, label, default, row):
            tk.Label(parent, text=label, font=("Segoe UI", 10),
                     fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"]).grid(row=row, column=0, sticky="w", padx=(4, 8), pady=3)
            var = tk.StringVar(value=str(default))
            entry = ttk.Entry(parent, textvariable=var, width=40)
            entry.grid(row=row, column=1, sticky="ew", pady=3)
            parent.columnconfigure(1, weight=1)
            return var

        def make_text(parent, label, default, row):
            tk.Label(parent, text=label, font=("Segoe UI", 10),
                     fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"]).grid(row=row, column=0, sticky="nw", padx=(4, 8), pady=3)
            frame = ttk.Frame(parent)
            frame.grid(row=row, column=1, sticky="ew", pady=3)
            frame.columnconfigure(0, weight=1)
            text = tk.Text(frame, height=6, width=40,
                           bg="#0a0a1a", fg=SPACE_COLORS["text"],
                           insertbackground=SPACE_COLORS["cyan"],
                           highlightbackground=SPACE_COLORS["border"],
                           highlightcolor=SPACE_COLORS["cyan"],
                           highlightthickness=1, bd=0)
            text.grid(row=0, column=0, sticky="ew")
            scroll = ttk.Scrollbar(frame, orient="vertical", command=text.yview)
            scroll.grid(row=0, column=1, sticky="ns")
            text.config(yscrollcommand=scroll.set)
            if isinstance(default, list):
                text.insert("1.0", "\n".join(str(x) for x in default))
            return text

        tab1 = ttk.Frame(notebook)
        notebook.add(tab1, text="Discord")
        r = 0
        v_target_id = make_entry(tab1, "TARGET_CHANNEL_ID:", _val("TARGET_CHANNEL_ID", CFG_TARGET_CHANNEL_ID), r); r += 1
        t_complaint_ids = make_text(tab1, "COMPLAINT_CHANNEL_IDS:", _val("COMPLAINT_CHANNEL_IDS", CFG_COMPLAINT_CHANNEL_IDS), r); r += 1
        v_msg_hist = make_entry(tab1, "MESSAGE_HISTORY_LIMIT:", _val("MESSAGE_HISTORY_LIMIT", CFG_MESSAGE_HISTORY_LIMIT), r); r += 1

        tab2 = ttk.Frame(notebook)
        notebook.add(tab2, text="API")
        r = 0
        v_base_url = make_entry(tab2, "BASE_ADMIN_URL:", _val("BASE_ADMIN_URL", CFG_BASE_ADMIN_URL), r); r += 1
        v_acc_url = make_entry(tab2, "ACCOUNT_URL:", _val("ACCOUNT_URL", CFG_ACCOUNT_URL), r); r += 1
        v_op_timeout = make_entry(tab2, "OPERATION_TIMEOUT:", _val("OPERATION_TIMEOUT", CFG_OPERATION_TIMEOUT), r); r += 1
        v_req_timeout = make_entry(tab2, "REQUEST_TIMEOUT:", _val("REQUEST_TIMEOUT", CFG_REQUEST_TIMEOUT), r); r += 1
        v_search_timeout = make_entry(tab2, "SEARCH_TIMEOUT:", _val("SEARCH_TIMEOUT", CFG_SEARCH_TIMEOUT), r); r += 1
        v_batch_timeout = make_entry(tab2, "BATCH_TIMEOUT:", _val("BATCH_TIMEOUT", CFG_BATCH_TIMEOUT), r); r += 1
        v_term_timeout = make_entry(tab2, "TERM_TIMEOUT:", _val("TERM_TIMEOUT", CFG_TERM_TIMEOUT), r); r += 1
        v_max_conc = make_entry(tab2, "MAX_CONCURRENT_REQUESTS:", _val("MAX_CONCURRENT_REQUESTS", CFG_MAX_CONCURRENT_REQUESTS), r); r += 1

        tab3 = ttk.Frame(notebook)
        notebook.add(tab3, text="Сканирование")
        r = 0
        v_search_max_depth = make_entry(tab3, "SEARCH_MAX_DEPTH:", _val("SEARCH_MAX_DEPTH", CFG_SEARCH_MAX_DEPTH), r); r += 1
        v_search_limit_root = make_entry(tab3, "SEARCH_LIMIT_ROOT:", _val("SEARCH_LIMIT_ROOT", CFG_SEARCH_LIMIT_ROOT), r); r += 1
        v_search_limit_l1 = make_entry(tab3, "SEARCH_LIMIT_LEVEL1:", _val("SEARCH_LIMIT_LEVEL1", CFG_SEARCH_LIMIT_LEVEL1), r); r += 1
        v_search_limit_l2 = make_entry(tab3, "SEARCH_LIMIT_LEVEL2:", _val("SEARCH_LIMIT_LEVEL2", CFG_SEARCH_LIMIT_LEVEL2), r); r += 1
        v_search_limit_def = make_entry(tab3, "SEARCH_LIMIT_DEFAULT:", _val("SEARCH_LIMIT_DEFAULT", CFG_SEARCH_LIMIT_DEFAULT), r); r += 1
        v_bypass_depth = make_entry(tab3, "BYPASS_SEARCH_MAX_DEPTH:", _val("BYPASS_SEARCH_MAX_DEPTH", CFG_BYPASS_SEARCH_MAX_DEPTH), r); r += 1
        v_cache_size = make_entry(tab3, "SEARCH_CACHE_MAX_SIZE:", _val("SEARCH_CACHE_MAX_SIZE", CFG_SEARCH_CACHE_MAX_SIZE), r); r += 1
        v_cache_ttl = make_entry(tab3, "SEARCH_CACHE_TTL:", _val("SEARCH_CACHE_TTL", CFG_SEARCH_CACHE_TTL), r); r += 1

        tab4 = ttk.Frame(notebook)
        notebook.add(tab4, text="Тайминги")
        r = 0
        v_close_time = make_entry(tab4, "CLOSE_TIME_THRESHOLD_MINUTES:", _val("CLOSE_TIME_THRESHOLD_MINUTES", CFG_CLOSE_TIME_THRESHOLD_MINUTES), r); r += 1
        v_time_thresh = make_entry(tab4, "TIME_THRESHOLD_MINUTES:", _val("TIME_THRESHOLD_MINUTES", CFG_TIME_THRESHOLD_MINUTES), r); r += 1
        v_susp_time = make_entry(tab4, "SUSPICIOUS_TIME_THRESHOLD_MINUTES:", _val("SUSPICIOUS_TIME_THRESHOLD_MINUTES", CFG_SUSPICIOUS_TIME_THRESHOLD_MINUTES), r); r += 1
        v_ip_time = make_entry(tab4, "IP_MATCH_TIMEDELTA_MINUTES:", _val("IP_MATCH_TIMEDELTA_MINUTES", CFG_IP_MATCH_TIMEDELTA_MINUTES), r); r += 1

        def _save_config():
            overrides.clear()

            def _add(name, var):
                raw = var.get().strip()
                try:
                    val = ast.literal_eval(raw)
                except Exception:
                    val = raw
                if val != _CONFIG_DEFAULTS.get(name):
                    overrides[name] = val

            def _add_text(name, text_widget):
                raw = text_widget.get("1.0", tk.END).strip()
                if not raw:
                    vals = []
                else:
                    vals = [ast.literal_eval(line.strip()) for line in raw.split("\n") if line.strip()]
                if vals != _CONFIG_DEFAULTS.get(name):
                    overrides[name] = vals

            _add("TARGET_CHANNEL_ID", v_target_id)
            _add_text("COMPLAINT_CHANNEL_IDS", t_complaint_ids)
            _add("MESSAGE_HISTORY_LIMIT", v_msg_hist)
            _add("BASE_ADMIN_URL", v_base_url)
            _add("ACCOUNT_URL", v_acc_url)
            _add("OPERATION_TIMEOUT", v_op_timeout)
            _add("REQUEST_TIMEOUT", v_req_timeout)
            _add("SEARCH_TIMEOUT", v_search_timeout)
            _add("BATCH_TIMEOUT", v_batch_timeout)
            _add("TERM_TIMEOUT", v_term_timeout)
            _add("MAX_CONCURRENT_REQUESTS", v_max_conc)
            _add("SEARCH_MAX_DEPTH", v_search_max_depth)
            _add("SEARCH_LIMIT_ROOT", v_search_limit_root)
            _add("SEARCH_LIMIT_LEVEL1", v_search_limit_l1)
            _add("SEARCH_LIMIT_LEVEL2", v_search_limit_l2)
            _add("SEARCH_LIMIT_DEFAULT", v_search_limit_def)
            _add("BYPASS_SEARCH_MAX_DEPTH", v_bypass_depth)
            _add("SEARCH_CACHE_MAX_SIZE", v_cache_size)
            _add("SEARCH_CACHE_TTL", v_cache_ttl)
            _add("CLOSE_TIME_THRESHOLD_MINUTES", v_close_time)
            _add("TIME_THRESHOLD_MINUTES", v_time_thresh)
            _add("SUSPICIOUS_TIME_THRESHOLD_MINUTES", v_susp_time)
            _add("IP_MATCH_TIMEDELTA_MINUTES", v_ip_time)

            self.settings["config"] = dict(overrides)
            self._save_settings()
            dialog.destroy()

        btn_frame = ttk.Frame(dialog)
        btn_frame.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btn_frame, text="💾 Сохранить", style="Cyan.TButton", command=_save_config).pack(side="right", padx=(4, 0))
        ttk.Button(btn_frame, text="Отмена", style="Dim.TButton", command=dialog.destroy).pack(side="right")

    def _ban_log(self, text, color=None):
        self.ban_result_text.config(state="normal")
        if color:
            self.ban_result_text.insert(tk.END, text, color)
        else:
            self.ban_result_text.insert(tk.END, text)
        self.ban_result_text.see(tk.END)
        self.ban_result_text.config(state="disabled")

    @staticmethod
    def _detect_target_type(value):
        value = value.strip()
        if not value:
            return None
        if re.match(r'^\d{1,3}(\.\d{1,3}){3}$', value):
            return "ip"
        if re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', value, re.I):
            return "user_id"
        if len(value) > 30 and re.match(r'^[A-Za-z0-9+/=,\-{}: ]+$', value):
            return "hwid"
        return "username"

    def _reset_ban_reason(self):
        self.ban_reason_var.set("Перманентная блокировка, Правило 0: Набегатор или твинк набегатора, обход блокировки путём создания нового аккаунта. Бан в реестр. Обжалование в Discord")

    def _show_ban_reason_presets(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Пресеты причин бана")
        dialog.geometry("600x500")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.configure(bg=SPACE_COLORS["bg_panel"])

        frame = tk.Frame(dialog, bg=SPACE_COLORS["bg_panel"], padx=15, pady=15)
        frame.pack(fill="both", expand=True)

        presets = [
            ("Обход блокировки",
             "Перма ДК. Правило 9.2. Попытка обхода блокировки путем создания нового аккаунта. Просим откликнуться на нашем Discord сервере в канале с обжалованиями."),
            ("ПДК по жалобе",
             "Перма ДК. На вас поступила жалоба, просим откликнуться в канале жалоб на игроков. [Ссылка на жалобу]."),
            ("Набег на сервер партнёров",
             "Перманентная блокировка. Правило 0. Набег на сервер партнёров. Обжалование в Discord."),
            ("Набегаторский твинк HWID/IP",
             "Перманентная блокировка, Правило 0: Набегатор или твинк набегатора, обход блокировки путём создания нового аккаунта. Бан в реестр. Обжалование в Discord"),
            ("Перманентная блокировка",
             "Перманентная блокировка, Правило X, рецидив(если имеется): [краткое, понятное описание ситуации]. Обжалование в Discord."),
            ("Набегатор",
             "Перманентная блокировка, Правило 0: Набегатор. [краткое, понятное описание ситуации]. Бан в реестр. Обжалование в Discord."),
            ("БВО",
             "Перманентная блокировка БВО: Правило X, [Краткое, понятное описания ситуации]. Без возможности обжалования."),
        ]

        canvas = tk.Canvas(frame, highlightthickness=0, bg=SPACE_COLORS["bg_panel"])
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=canvas.yview)
        scrollable = tk.Frame(canvas, bg=SPACE_COLORS["bg_panel"])
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        tk.Label(scrollable, text="Локальные пресеты:", font=("Segoe UI", 11, "bold"),
                 fg=SPACE_COLORS["cyan"], bg=SPACE_COLORS["bg_panel"]).pack(anchor="w", pady=(0, 5))

        for title, reason in presets:
            btn = ttk.Button(scrollable, text=title, style="Dim.TButton", command=lambda r=reason: self._apply_preset_reason(r, dialog))
            btn.pack(fill="x", pady=2)

        tk.Frame(scrollable, bg=SPACE_COLORS["border"], height=1).pack(fill="x", pady=(10, 5))
        tk.Label(scrollable, text="Пресеты с админ-сайта:", font=("Segoe UI", 11, "bold"),
                 fg=SPACE_COLORS["cyan"], bg=SPACE_COLORS["bg_panel"]).pack(anchor="w", pady=(0, 5))

        load_btn = ttk.Button(scrollable, text="📥 Загрузить с админки", style="Dim.TButton")
        load_btn.pack(fill="x", pady=2)
        loading_label = tk.Label(scrollable, text="", font=("Segoe UI", 10),
                                 fg=SPACE_COLORS["text_dim"], bg=SPACE_COLORS["bg_panel"])
        loading_label.pack()

        def load_templates():
            load_btn.config(state="disabled")
            loading_label.config(text="Загрузка...")
            threading.Thread(target=self._load_admin_templates_thread, args=(scrollable, loading_label, dialog), daemon=True).start()

        load_btn.config(command=load_templates)

        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        ttk.Button(frame, text="Отмена", style="Dim.TButton", command=dialog.destroy).pack(fill="x", pady=(10, 0))

    def _load_admin_templates_thread(self, parent, loading_label, dialog):
        try:
            if self._admin_panel and self._admin_panel_loop and not self._admin_panel_loop.is_closed():
                try:
                    future = asyncio.run_coroutine_threadsafe(
                        self._fetch_templates_shared(parent, loading_label, dialog),
                        self._admin_panel_loop
                    )
                    future.result(timeout=15)
                    return
                except asyncio.TimeoutError:
                    parent.after(0, lambda: loading_label.config(text="❌ Таймаут загрузки шаблонов"))
                    return
                except Exception as e:
                    parent.after(0, lambda m=str(e): loading_label.config(text=f"❌ Ошибка: {m[:80]}"))
                    return
            parent.after(0, lambda: loading_label.config(text="❌ Запустите сканирование игрока для авторизации на админ-сайте"))
        except Exception as exc:
            parent.after(0, lambda m=str(exc): loading_label.config(text=f"❌ Ошибка: {m[:80]}"))

    async def _fetch_templates_shared(self, parent, loading_label, dialog):
        try:
            templates = await self._admin_panel.fetch_ban_templates(require_auth=False)
            if not templates and not self._admin_panel._is_authenticated:
                parent.after(0, lambda: loading_label.config(text="❌ Нет активной сессии. Сканируйте игрока для авторизации"))
                return
            parent.after(0, lambda t=templates: self._display_admin_templates(parent, t, dialog, loading_label))
        except Exception as e:
            parent.after(0, lambda m=str(e): loading_label.config(text=f"❌ Ошибка: {m[:80]}"))

    def _display_admin_templates(self, parent, templates, dialog, loading_label):
        loading_label.config(text="")
        if not templates:
            loading_label.config(text="Не удалось загрузить шаблоны с админки")
            return
        loading_label.config(text=f"✅ Загружено {len(templates)} шаблонов с админки")
        for t in templates:
            btn = ttk.Button(parent, text=f"📌 {t['title']}", style="Dim.TButton",
                             command=lambda r=t["reason"]: self._apply_preset_reason(r, dialog))
            btn.pack(fill="x", pady=2, before=loading_label)

    def _apply_preset_reason(self, reason, dialog):
        self.ban_reason_var.set(reason)
        dialog.destroy()

    def _on_ban_execute(self):
        admin_username = self.username_var.get()
        admin_password = self.password_var.get()
        if not admin_username or not admin_password:
            messagebox.showerror("Ошибка", "Укажите имя и пароль администратора")
            return

        raw = self.ban_targets_text.get("1.0", tk.END).strip()
        if not raw:
            messagebox.showerror("Ошибка", "Введите цели для блокировки")
            return

        reason = self.ban_reason_var.get().strip()
        if not reason:
            messagebox.showerror("Ошибка", "Укажите причину блокировки")
            return

        try:
            minutes = int(self.ban_minutes_var.get())
        except ValueError:
            minutes = 0

        targets = [line.strip() for line in raw.split("\n") if line.strip()]
        if not targets:
            messagebox.showerror("Ошибка", "Нет целей для блокировки")
            return

        self.ban_result_text.config(state="normal")
        self.ban_result_text.delete("1.0", tk.END)
        self.ban_result_text.config(state="disabled")
        self.ban_execute_btn.config(state="disabled")

        threading.Thread(
            target=self._run_ban_worker,
            args=(admin_username, admin_password, targets, reason, minutes),
            daemon=True,
        ).start()

    def _run_ban_worker(self, admin_username, admin_password, targets, reason, minutes):
        import traceback as _tb
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(
                self._ban_worker_async(admin_username, admin_password, targets, reason, minutes)
            )
            loop.close()
            self.output_queue.put(f"\n{'─'*50}\nБлокировка завершена: {result.get('ok', 0)} успешно, {result.get('fail', 0)} ошибок\n")
        except Exception as e:
            self.output_queue.put(f"\nОшибка выполнения блокировки: {e}\n{_tb.format_exc()}\n")
        finally:
            self.output_queue.put("__BAN_DONE__")

    async def _ban_worker_async(self, admin_username, admin_password, targets, reason, minutes):
        from deadspace_checker.admin import AdminPanel
        panel = AdminPanel(admin_username, admin_password)
        panel._set_debug_callback(lambda msg: self.output_queue.put(msg + "\n"))
        ok_count = 0
        fail_count = 0

        self.output_queue.put("🔑 Выполняю вход в админ-панель...\n")
        logged_in = await panel.login()
        if not logged_in:
            self.output_queue.put("❌ Ошибка входа в админ-панель\n")
            return {"ok": 0, "fail": len(targets)}

        use_latest_ip = self.use_latest_ip_var.get()
        use_latest_hwid = self.use_latest_hwid_var.get()

        self.output_queue.put(f"📋 Начинаю блокировку {len(targets)} целей...\n")
        self.output_queue.put(f"   Использовать последний IP: {'Да' if use_latest_ip else 'Нет'}\n")
        self.output_queue.put(f"   Использовать последний HWID: {'Да' if use_latest_hwid else 'Нет'}\n\n")

        for idx, target in enumerate(targets):
            detected_type = self._detect_target_type(target)
            log_line = f"[{idx + 1}/{len(targets)}] {target}  →  тип: {detected_type}  ...  "
            self.output_queue.put(log_line)

            try:
                kwargs = dict(reason=reason, minutes=minutes)
                if detected_type == "ip":
                    kwargs["ip_address"] = target
                elif detected_type == "hwid":
                    kwargs["hwid"] = target
                elif detected_type == "user_id":
                    kwargs["user_id"] = target
                else:
                    kwargs["user_id"] = target
                    if use_latest_ip:
                        kwargs["use_latest_ip"] = True
                    if use_latest_hwid:
                        kwargs["use_latest_hwid"] = True

                success = await panel.create_ban(**kwargs)
                if success:
                    ok_count += 1
                    self.output_queue.put("✅ УСПЕХ\n")
                else:
                    fail_count += 1
                    self.output_queue.put("❌ ОШИБКА\n")
            except Exception as e:
                fail_count += 1
                self.output_queue.put(f"❌ ИСКЛЮЧЕНИЕ: {e}\n")

        self.output_queue.put(f"\n{'─'*50}\n")
        self.output_queue.put(f"✅ Успешно: {ok_count}\n")
        self.output_queue.put(f"❌ Ошибок: {fail_count}\n")

        await panel.close()
        return {"ok": ok_count, "fail": fail_count}

    def _on_close(self):
        self.running = False
        if self._twinkle_job:
            try:
                self.root.after_cancel(self._twinkle_job)
            except Exception:
                pass
        self._cleanup_previous_bot()
        self.root.destroy()
