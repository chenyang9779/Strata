"""Native Windows manager for Strata. Uses the existing installer and inference server."""
from __future__ import annotations

import json
import os
import queue
import secrets
import subprocess
import sys
import threading
import webbrowser
import urllib.error
import urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import strata_desktop_core as core
import runtime


BG = "#0b1220"
NAV = "#0f1b2c"
PANEL = "#15243a"
FIELD = "#1e314c"
BORDER = "#304660"
TEXT = "#eef6fc"
MUTED = "#a8bdd0"
ACCENT = "#66dec9"
PURPLE = "#a1aeff"
SUCCESS = "#7fe2a6"
WARNING = "#ffcc85"
LOG_BG = "#0a1524"


def locate_root(saved: str) -> Path | None:
    candidates = [os.environ.get("STRATA_HOME"), saved, Path(__file__).resolve().parent.parent,
                  Path(sys.executable).resolve().parent, Path.cwd()]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser()
        for parent in (path, *path.parents):
            if (parent / "setup.py").is_file() and (parent / "serve" / "server.py").is_file():
                return parent.resolve()
    return None


class Desktop(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Strata  |  Control Center")
        self.geometry("1240x850")
        self.minsize(990, 685)
        self.configure(background=BG)
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.events = queue.Queue()
        self.proc = None
        self.operation = ""
        self._closing = False
        self.machine = runtime.RunState()
        self.stop_requested = threading.Event()
        self.pending_config = None
        self.pending_runtime = None
        self.model_files = {}
        self.selected_path = None
        self.active_config_path = None
        self.chat_history = []
        self.chat_busy = False
        self.metrics_busy = False
        self.chat_request_id = 0
        self.chat_cancel = threading.Event()
        self.chat_response = None
        self.chat_response_lock = threading.Lock()
        self.partial_answer = ""
        self.active_config = None
        self._loading_form = False
        self.dirty = False
        self.prefs_path = core.user_dir() / "desktop.json"
        self.prefs = core.read_json(self.prefs_path)
        self.root_dir = locate_root(str(self.prefs.get("root", "")))
        if self.root_dir is None:
            messagebox.showinfo("Locate Strata", "Select the folder containing setup.py and START-HERE.bat.")
            chosen = filedialog.askdirectory(title="Strata installation folder")
            candidate = Path(chosen) if chosen else None
            if candidate is None or not (candidate / "setup.py").is_file() or not (candidate / "serve" / "server.py").is_file():
                messagebox.showerror("Strata not found", "A valid Strata source folder is required.")
                self.destroy()
                return
            self.root_dir = candidate.resolve()
        self.prefs["root"] = str(self.root_dir)
        self._save_prefs()

        self.family = tk.StringVar(value="qwen")
        self.model = tk.StringVar(value="IQ2_XS")
        self.context = tk.StringVar(value="32768")
        self.kv = tk.StringVar(value="int8")
        self.vision = tk.StringVar(value="none")
        self.projection = tk.StringVar(value="off")
        self.data_root = tk.StringVar(value=str(core.current_data_root(self.root_dir)))
        self.gguf_folder = tk.StringVar()
        self.gpu = tk.StringVar(value="Auto")
        self.host = tk.StringVar(value="127.0.0.1")
        self.port = tk.StringVar(value="8080")
        self.api_key = tk.StringVar()
        self.cpu_workers = tk.StringVar(value="0")
        self.vision_threads = tk.StringVar(value="0")
        self.expert_cache = tk.StringVar(value="auto")
        self.prefill = tk.StringVar(value="auto")
        self.fit_max_tokens = tk.BooleanVar(value=False)
        self.mcp_file = tk.StringVar(value=str(self.prefs.get("mcp_file", "")))
        self.status = tk.StringVar(value="OFFLINE")
        self.current_activity = tk.StringVar(value="Ready to launch a model")
        self.active_model_text = tk.StringVar(value="No active model")
        self.monitor_state = tk.StringVar(value="OFFLINE")
        self.monitor_queue = tk.StringVar(value="0")
        self.monitor_toks = tk.StringVar(value="0.0")
        self.monitor_requests = tk.StringVar(value="0")
        self.endpoint = tk.StringVar(value="http://127.0.0.1:8080/v1")
        self.lan_endpoint = tk.StringVar(value="Enable LAN serving to show network addresses")
        self.local_ips = core.lan_addresses()
        self._theme()
        self._layout()
        self.family.trace_add("write", self._family_changed)
        self.refresh_models()
        self._track_dirty()
        self.after(120, self._poll)
        self.after(5000, self._metrics_timer)

    def _save_prefs(self):
        self.prefs["root"] = str(self.root_dir)
        if self.selected_path is not None:
            self.prefs["last_selected"] = str(self.selected_path)
        self.prefs["mcp_file"] = self.mcp_file.get() if hasattr(self, "mcp_file") else self.prefs.get("mcp_file", "")
        core.atomic_json(self.prefs_path, self.prefs)

    def _theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG, foreground=TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Hint.TLabel", background=PANEL, foreground=MUTED, font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 21))
        style.configure("TButton", background=FIELD, foreground=TEXT,
                        padding=(13, 9), borderwidth=0, relief="flat")
        style.map("TButton", background=[("active", "#355273"), ("disabled", PANEL)],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground=BG,
                        padding=(16, 9), font=("Segoe UI Semibold", 10), borderwidth=0)
        style.map("Accent.TButton", background=[("active", "#a4f5df"), ("disabled", FIELD)],
                  foreground=[("disabled", MUTED)])
        style.configure("Danger.TButton", background="#453148", foreground="#ffe5e9")
        style.map("Danger.TButton", background=[("active", "#704255")])
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT,
                        insertcolor=TEXT, padding=7, borderwidth=0)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        selectbackground=FIELD, selectforeground=TEXT, arrowcolor=TEXT, padding=6)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.map("TCheckbutton", background=[("active", PANEL)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=35, borderwidth=0)
        style.configure("Treeview.Heading", background=FIELD, foreground=MUTED,
                        font=("Segoe UI Semibold", 9), relief="flat", padding=6)
        style.map("Treeview", background=[("selected", "#275d69")],
                  foreground=[("selected", TEXT)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)

    def _layout(self):
        shell = tk.Frame(self, background=BG)
        shell.pack(fill="both", expand=True)
        sidebar = tk.Frame(shell, bg=NAV, width=218, padx=17, pady=23)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)

        tk.Label(sidebar, text="◈  STRATA", bg=NAV, fg=ACCENT,
                 font=("Segoe UI Semibold", 20), anchor="w").pack(fill="x")
        tk.Label(sidebar, text="LOCAL AI  /  CONTROL CENTER", bg=NAV, fg=MUTED,
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(2, 35))
        self.nav_buttons = []
        names = ["Models", "Engine", "API & Tools", "Chat", "Monitor", "Activity"]
        tags = ["01", "02", "03", "04", "05", "06"]
        for index, name in enumerate(names):
            btn = tk.Button(sidebar, text=f"{tags[index]}    {name}", bg=NAV, fg=MUTED,
                            activebackground=FIELD, activeforeground=TEXT, relief="flat",
                            bd=0, cursor="hand2", anchor="w", padx=15, pady=13,
                            font=("Segoe UI Semibold", 10),
                            command=lambda number=index: self._show_page(number))
            btn.pack(fill="x", pady=2)
            self.nav_buttons.append(btn)
        tk.Frame(sidebar, bg=NAV).pack(fill="both", expand=True)
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill="x", pady=(5, 17))
        tk.Label(sidebar, text="SERVER STATUS", bg=NAV, fg=MUTED,
                 font=("Segoe UI Semibold", 9), anchor="w").pack(fill="x")
        self.side_status = tk.Label(sidebar, textvariable=self.status, bg=NAV, fg=WARNING,
                                    font=("Segoe UI Semibold", 12), anchor="w")
        self.side_status.pack(fill="x", pady=(5, 2))
        tk.Label(sidebar, textvariable=self.active_model_text, bg=NAV, fg=MUTED,
                 wraplength=183, justify="left", font=("Segoe UI", 9), anchor="w").pack(fill="x")

        work = tk.Frame(shell, bg=BG, padx=23, pady=21)
        work.pack(side="left", fill="both", expand=True)
        mast = tk.Frame(work, bg=BG)
        mast.pack(fill="x")
        title_col = tk.Frame(mast, bg=BG)
        title_col.pack(side="left", fill="both", expand=True)
        self.page_title = tk.Label(title_col, text="Models", bg=BG, fg=TEXT,
                                   font=("Segoe UI Semibold", 23), anchor="w")
        self.page_title.pack(anchor="w")
        self.page_desc = tk.Label(title_col, text="Manage your local intelligence", bg=BG, fg=MUTED,
                                  font=("Segoe UI", 10), anchor="w")
        self.page_desc.pack(anchor="w", pady=(2, 0))
        actions = tk.Frame(mast, bg=BG)
        actions.pack(side="right")
        self.start_button = ttk.Button(actions, text="▶  Start model", style="Accent.TButton",
                                       command=self.start_server)
        self.start_button.pack(side="left", padx=(0, 7))
        self.stop_button = ttk.Button(actions, text="■  Stop", style="Danger.TButton",
                                      command=self.stop_server)
        self.stop_button.pack(side="left", padx=(0, 7))
        ttk.Button(actions, text="Open web UI ↗", command=self.open_chat).pack(side="left")

        ribbon = tk.Frame(work, bg=PANEL, highlightbackground=BORDER, highlightthickness=1,
                          padx=14, pady=9)
        ribbon.pack(fill="x", pady=(18, 15))
        tk.Label(ribbon, text="PROJECT", bg=PANEL, fg=ACCENT,
                 font=("Segoe UI Semibold", 9)).pack(side="left", padx=(0, 12))
        tk.Label(ribbon, text=str(self.root_dir), bg=PANEL, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(side="left", fill="x", expand=True)
        self.dirty_label = tk.Label(ribbon, text="", bg=PANEL, fg=WARNING,
                                    font=("Segoe UI Semibold", 9))
        self.dirty_label.pack(side="right")

        self.page_host = tk.Frame(work, bg=BG)
        self.page_host.pack(fill="both", expand=True)
        self.pages = []
        self.scroll_canvases = {}
        for i in range(6):
            page = tk.Frame(self.page_host, bg=BG)
            self.pages.append(page)
            inner = page if i in (3, 4, 5) else self._scroll_page(page)
            if i == 0:
                self._models_tab(inner)
            elif i == 1:
                self._engine_tab(inner)
            elif i == 2:
                self._api_tab(inner)
            elif i == 3:
                self._chat_tab(inner)
            elif i == 4:
                self._monitor_tab(inner)
            else:
                self._logs_tab(inner)

        footer = tk.Frame(work, bg=BG, pady=9)
        footer.pack(fill="x")
        tk.Label(footer, text="●", bg=BG, fg=ACCENT, font=("Segoe UI", 9)).pack(side="left")
        tk.Label(footer, textvariable=self.current_activity, bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(side="left", fill="x", expand=True, padx=7)
        tk.Label(footer, text="1 GENERATION  •  QUEUED REQUESTS", bg=BG, fg=MUTED,
                 font=("Segoe UI Semibold", 8)).pack(side="right")
        self._page_index = 0
        self.bind_all("<MouseWheel>", self._wheel_page, add="+")
        self._show_page(0)
        self._set_busy(False)

    def _scroll_page(self, page):
        canvas = tk.Canvas(page, bg=BG, highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        inner = ttk.Frame(canvas, padding=(1, 1, 10, 12))
        item = canvas.create_window((0, 0), anchor="nw", window=inner)
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(item, width=e.width))
        self.scroll_canvases[page] = canvas
        return inner

    def _wheel_page(self, event):
        if self._page_index >= 3:
            return
        page = self.pages[self._page_index]
        target = self.winfo_containing(event.x_root, event.y_root)
        if not target:
            return
        path = str(target)
        parent_path = str(page)
        if path != parent_path and not path.startswith(parent_path + "."):
            return
        if isinstance(target, (tk.Text, ttk.Treeview, ttk.Combobox)):
            return
        step = max(1, int(abs(event.delta) / 120))
        self.scroll_canvases[page].yview_scroll(-step if event.delta > 0 else step, "units")
        return "break"

    def _show_page(self, index):
        headings = [
            ("Models", "Your installed checkpoints and model storage"),
            ("Engine", "Tune hardware resources and inference behaviour"),
            ("API & Tools", "Local serving, LAN access and integrations"),
            ("Quick Chat", "Chat directly with the running local model"),
            ("Monitor", "Runtime, throughput and hardware telemetry"),
            ("Activity", "Download, engine and server activity logs"),
        ]
        for frame in self.pages:
            frame.pack_forget()
        self.pages[index].pack(fill="both", expand=True)
        self._page_index = index
        self.page_title.configure(text=headings[index][0])
        self.page_desc.configure(text=headings[index][1])
        for i, button in enumerate(self.nav_buttons):
            button.configure(bg=FIELD if i == index else NAV,
                             fg=ACCENT if i == index else MUTED)
        if index == 4:
            self.fetch_metrics()

    def _section(self, parent, title, description=""):
        outline = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        outline.pack(fill="x", pady=(0, 14))
        wrapper = ttk.Frame(outline, style="Panel.TFrame", padding=18)
        wrapper.pack(fill="both", expand=True)
        ttk.Label(wrapper, text=title, style="Panel.TLabel",
                  font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 4))
        if description:
            ttk.Label(wrapper, text=description, style="Hint.TLabel",
                      wraplength=760, justify="left").pack(anchor="w", pady=(0, 12))
        grid = ttk.Frame(wrapper, style="Panel.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        return grid

    def _field(self, parent, line, title, variable, values=None, browse=None, secret=False):
        ttk.Label(parent, text=title, style="Panel.TLabel").grid(
            row=line, column=0, sticky="w", pady=6, padx=(0, 20))
        if values is not None:
            widget = ttk.Combobox(parent, textvariable=variable, values=values,
                                  state="readonly", width=26)
        else:
            widget = ttk.Entry(parent, textvariable=variable, show="*" if secret else "",
                               width=46)
        widget.grid(row=line, column=1, sticky="ew", pady=6)
        if browse:
            ttk.Button(parent, text="Browse…", command=browse).grid(
                row=line, column=2, padx=(10, 0), pady=6)
        return widget

    def _models_tab(self, parent):
        top = self._section(parent, "Installed models",
                            "Select an installed configuration to load its settings. Only one model can generate at a time.")
        self.tree = ttk.Treeview(top, columns=("model", "context", "images", "files"),
                                 show="headings", height=5)
        for key, title, width in (("model", "Model", 290), ("context", "Context", 110),
                                  ("images", "Images", 85), ("files", "Engine", 110)):
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.grid(row=0, column=0, columnspan=3, sticky="ew")
        self.tree.bind("<<TreeviewSelect>>", self._select_model)
        ttk.Button(top, text="Refresh models", command=self.refresh_models).grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.selected_label = ttk.Label(top, text="No model selected", style="Hint.TLabel")
        self.selected_label.grid(row=1, column=1, columnspan=2, sticky="w", pady=(12, 0))
        install = self._section(parent, "Install / prepare another model",
                                "Uses setup.py, retains existing model files, and does not start a server automatically.")
        self._field(install, 0, "Family", self.family, list(core.FAMILIES))
        self.size_field = self._field(install, 1, "Quantization", self.model, list(core.FAMILIES["qwen"]))
        self._field(install, 2, "Context tokens", self.context, [str(x) for x in core.CONTEXTS])
        self._field(install, 3, "KV cache", self.kv, ["int8", "q4_0"])
        self._field(install, 4, "Image encoder", self.vision, ["none", "gpu", "cpu"])
        self._field(install, 5, "Experimental projection", self.projection, ["off", "on"])
        self._field(install, 6, "Data ROOT (not models/)", self.data_root, browse=self.browse_data)
        self._field(install, 7, "Existing GGUF folder (optional)", self.gguf_folder, browse=self.browse_gguf)
        self.install_button = ttk.Button(install, text="Install / prepare model", style="Accent.TButton",
                                         command=self.install_model)
        self.install_button.grid(row=8, column=1, sticky="e", pady=(15, 0))
        ttk.Label(install, text="Data root contains models/, packs/ and mtp/. Do not select a models/ subfolder.",
                  style="Hint.TLabel", wraplength=800).grid(row=9, column=0, columnspan=3, sticky="w", pady=6)

    def _engine_tab(self, parent):
        engine = self._section(parent, "Execution tuning",
                               "CPU workers set the engine's --pool-workers option (0 = automatic). Changes take effect on restart.")
        self._field(engine, 0, "GPU index", self.gpu, self._gpu_options())
        self._field(engine, 1, "CPU expert workers (0 = auto)", self.cpu_workers)
        self._field(engine, 2, "Vision encoder threads (0 = auto)", self.vision_threads)
        self._field(engine, 3, "Expert cache slots", self.expert_cache,
                    ["auto", "1024", "2048", "4096", "8192"])
        self._field(engine, 4, "Prefill chunk", self.prefill,
                    ["auto", "512", "1024", "2048", "4096", "8192"])
        ttk.Label(engine, text="Concurrent generations: 1 (engine limit). Additional API requests queue; CPU workers are separate.",
                  style="Hint.TLabel", wraplength=850).grid(row=5, column=0, columnspan=3, sticky="w", pady=10)
        options = self._section(parent, "Context handling")
        ttk.Checkbutton(options, text="Fit max_tokens to available context instead of returning HTTP 400",
                        variable=self.fit_max_tokens).grid(row=0, column=0, columnspan=3, sticky="w", pady=5)
        self.save_engine_button = ttk.Button(options, text="Save settings to selected model",
                                              command=self.save_selected)
        self.save_engine_button.grid(row=1, column=1, sticky="e", pady=(10, 0))
        self.calibrate_button = ttk.Button(options, text="Calibrate selected model (5-10 min)",
                                            command=self.calibrate)
        self.calibrate_button.grid(row=2, column=1, sticky="e", pady=(8, 0))

    def _api_tab(self, parent):
        config = self._section(parent, "Serving & access",
                               "0.0.0.0 listens on all network interfaces. A nonempty API key is mandatory in this manager.")
        self._field(config, 0, "Bind address", self.host, ["127.0.0.1", "0.0.0.0"])
        self._field(config, 1, "HTTP port", self.port)
        self._field(config, 2, "API key", self.api_key, secret=True)
        ttk.Button(config, text="Generate key", command=lambda: self.api_key.set(secrets.token_urlsafe(32))).grid(
            row=3, column=1, sticky="w", pady=6)
        ttk.Button(config, text="Copy key", command=self.copy_key).grid(row=3, column=1, padx=135, sticky="w")
        ttk.Label(config, text="The key is stored in the selected model's existing JSON config, not the desktop preferences.",
                  style="Hint.TLabel", wraplength=830).grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
        tools = self._section(parent, "Integration",
                              "Local OpenAI-compatible and Anthropic-compatible endpoints; optional MCP servers for Chat.")
        self._field(tools, 0, "MCP config JSON (optional)", self.mcp_file, browse=self.browse_mcp)
        ttk.Label(tools, text="Local OpenAI API:", style="Panel.TLabel").grid(row=1, column=0, sticky="w", pady=8)
        ttk.Label(tools, textvariable=self.endpoint, style="Panel.TLabel").grid(row=1, column=1, sticky="w")
        ttk.Button(tools, text="Copy URL", command=self.copy_url).grid(row=1, column=2, padx=(8, 0))
        ttk.Label(tools, text="LAN URL uses your actual machine IP, not 0.0.0.0; Windows Firewall may need a Private-network rule.",
                  style="Hint.TLabel", wraplength=830).grid(row=2, column=0, columnspan=3, sticky="w", pady=5)
        self.save_api_button = ttk.Button(tools, text="Save API settings to selected model",
                                           command=self.save_selected)
        self.save_api_button.grid(row=3, column=1, sticky="e", pady=10)
        ttk.Label(tools, text="LAN OpenAI API:", style="Panel.TLabel").grid(
            row=4, column=0, sticky="w", pady=9)
        ttk.Label(tools, textvariable=self.lan_endpoint, style="Hint.TLabel",
                  wraplength=530).grid(row=4, column=1, sticky="w")
        ttk.Button(tools, text="Copy LAN URL", command=self.copy_lan_url).grid(
            row=4, column=2, padx=(8, 0))
        ttk.Button(tools, text="Refresh network addresses", command=self.refresh_lan_addresses).grid(
            row=5, column=1, sticky="w", pady=(5, 0))

    def _chat_tab(self, parent):
        header = tk.Frame(parent, bg=BG)
        header.pack(fill="x", pady=(0, 13))
        tk.Label(header, text="LOCAL CONVERSATION", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(side="left")
        ttk.Button(header, text="Open full Chat ↗", command=self.open_chat).pack(side="right")
        ttk.Button(header, text="New conversation", command=self.new_chat).pack(side="right", padx=8)

        outer = tk.Frame(parent, bg=LOG_BG, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(outer)
        scrollbar.pack(side="right", fill="y")
        self.chat_view = tk.Text(outer, background=LOG_BG, foreground=TEXT, state="disabled",
                                 wrap="word", font=("Segoe UI", 10), padx=17, pady=16,
                                 highlightthickness=0, relief="flat", spacing2=5,
                                 yscrollcommand=scrollbar.set)
        self.chat_view.pack(fill="both", expand=True)
        self.chat_view.tag_configure("role", foreground=ACCENT,
                                     font=("Segoe UI Semibold", 10), spacing1=8)
        self.chat_view.tag_configure("thought", foreground=MUTED,
                                     font=("Segoe UI", 9, "italic"))
        self.chat_view.tag_configure("error", foreground=WARNING)
        scrollbar.configure(command=self.chat_view.yview)
        self.chat_status = tk.StringVar(value="Start a model to begin chatting")
        tk.Label(parent, textvariable=self.chat_status, bg=BG, fg=MUTED,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(11, 6))
        entry = tk.Frame(parent, bg=BG)
        entry.pack(fill="x")
        self.chat_input = tk.Text(entry, height=3, wrap="word", background=FIELD,
                                  foreground=TEXT, insertbackground=TEXT, font=("Segoe UI", 10),
                                  relief="flat", highlightbackground=BORDER, highlightthickness=1,
                                  padx=12, pady=10)
        self.chat_input.pack(side="left", fill="both", expand=True)
        self.chat_input.bind("<Control-Return>", self._shortcut_send)
        actions = tk.Frame(entry, bg=BG)
        actions.pack(side="right", fill="y", padx=(10, 0))
        self.chat_send = ttk.Button(actions, text="Send ↗", style="Accent.TButton",
                                    command=self.send_chat)
        self.chat_send.pack(fill="x", pady=(0, 5))
        self.chat_stop = ttk.Button(actions, text="Cancel reply", command=self.cancel_chat)
        self.chat_stop.pack(fill="x")
        self.chat_stop.configure(state="disabled")
        tk.Label(parent, text="Ctrl+Enter to send • Streaming replies • For images and advanced tools, use the full web app.",
                 bg=BG, fg=MUTED, font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(9, 0))

    def _shortcut_send(self, _event):
        self.send_chat()
        return "break"

    def _metric(self, frame, name, value, col):
        card = tk.Frame(frame, bg=PANEL, highlightbackground=BORDER,
                        highlightthickness=1, padx=15, pady=12)
        card.grid(row=0, column=col, sticky="nsew", padx=(0, 10) if col < 3 else 0)
        tk.Label(card, text=name.upper(), bg=PANEL, fg=MUTED,
                 font=("Segoe UI Semibold", 8)).pack(anchor="w")
        tk.Label(card, textvariable=value, bg=PANEL, fg=ACCENT,
                 font=("Segoe UI Semibold", 21)).pack(anchor="w", pady=(4, 0))
        frame.columnconfigure(col, weight=1, uniform="metrics")

    def _monitor_tab(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, 14))
        tk.Label(bar, text="MODEL TELEMETRY", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(side="left")
        ttk.Button(bar, text="Open web Monitor ↗", command=self.open_monitor).pack(side="right")
        ttk.Button(bar, text="Refresh", command=self.fetch_metrics).pack(side="right", padx=8)
        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x", pady=(0, 14))
        self._metric(cards, "State", self.monitor_state, 0)
        self._metric(cards, "Tokens / sec", self.monitor_toks, 1)
        self._metric(cards, "Queue", self.monitor_queue, 2)
        self._metric(cards, "Requests served", self.monitor_requests, 3)
        outer = tk.Frame(parent, bg=LOG_BG, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(outer)
        scrollbar.pack(side="right", fill="y")
        self.metrics_view = tk.Text(outer, background=LOG_BG, foreground="#d1e8f4",
                                    font=("Consolas", 10), wrap="word", relief="flat",
                                    highlightthickness=0, padx=16, pady=14,
                                    yscrollcommand=scrollbar.set)
        self.metrics_view.pack(fill="both", expand=True)
        self.metrics_view.insert("end", "Start a model to view live engine and hardware data.\n")
        scrollbar.config(command=self.metrics_view.yview)

    def _logs_tab(self, parent):
        bar = tk.Frame(parent, bg=BG)
        bar.pack(fill="x", pady=(0, 12))
        tk.Label(bar, text="ACTIVITY STREAM", bg=BG, fg=ACCENT,
                 font=("Segoe UI Semibold", 10)).pack(side="left")
        ttk.Button(bar, text="Export log…", command=self.export_log).pack(side="right")
        ttk.Button(bar, text="Clear view", command=lambda: self.log_text.delete("1.0", "end")).pack(
            side="right", padx=7)
        outer = tk.Frame(parent, bg=LOG_BG, highlightbackground=BORDER, highlightthickness=1)
        outer.pack(fill="both", expand=True)
        scrollbar = ttk.Scrollbar(outer)
        scrollbar.pack(side="right", fill="y")
        self.log_text = tk.Text(outer, background=LOG_BG, foreground="#d1e8f4",
                                insertbackground=TEXT, font=("Consolas", 9), wrap="word",
                                relief="flat", highlightthickness=0, padx=14, pady=12,
                                yscrollcommand=scrollbar.set)
        self.log_text.pack(fill="both", expand=True)
        scrollbar.config(command=self.log_text.yview)
        self.log_text.tag_configure("log_error", foreground=WARNING)
        self.log_text.tag_configure("log_ready", foreground=SUCCESS)
        self._log("Strata Desktop is ready. Select or prepare a model.")

    def _gpu_options(self):
        options = ["Auto"]
        try:
            cmd = ["nvidia-smi", "--query-gpu=index", "--format=csv,noheader,nounits"]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=4, check=False,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            options.extend(x.strip() for x in r.stdout.splitlines() if x.strip().isdigit())
        except (OSError, subprocess.TimeoutExpired):
            pass
        return list(dict.fromkeys(options))

    def _family_changed(self, *_):
        valid = core.FAMILIES[self.family.get()]
        self.size_field.configure(values=valid)
        if self.model.get() not in valid:
            self.model.set(valid[0])
        if self.family.get() == "swift":
            self.projection.set("off")

    def _browse(self, variable, files=False):
        selected = (filedialog.askopenfilename(title="Choose MCP JSON", filetypes=[("JSON files", "*.json")])
                    if files else filedialog.askdirectory(title="Choose directory"))
        if selected:
            variable.set(selected)

    def browse_data(self):
        self._browse(self.data_root)

    def browse_gguf(self):
        self._browse(self.gguf_folder)

    def browse_mcp(self):
        self._browse(self.mcp_file, files=True)

    def _track_dirty(self):
        for variable in (self.host, self.port, self.api_key, self.gpu,
                         self.cpu_workers, self.vision_threads, self.expert_cache,
                         self.prefill, self.fit_max_tokens):
            variable.trace_add("write", self._mark_dirty)
        for variable in (self.host, self.port, self.api_key):
            variable.trace_add("write", self._refresh_api_urls)
        self._refresh_api_urls()

    def _mark_dirty(self, *_):
        if not self._loading_form and self.selected_path is not None:
            self.dirty = True
            self.dirty_label.configure(text="● UNSAVED SETTINGS")
            self.current_activity.set("Settings changed · save before the next start")

    def _restore_tree_selection(self):
        for item, (path, _) in self.model_files.items():
            if path == self.selected_path:
                self.tree.selection_set(item)
                self.tree.focus(item)
                return

    def refresh_models(self, select_path=None):
        preferred = select_path or self.selected_path or self.prefs.get("last_selected")
        if preferred:
            preferred = Path(preferred)
        self._loading_form = True
        try:
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.model_files.clear()
            wanted = None
            for path, cfg in core.installed_models(self.root_dir):
                ready = "Ready" if Path(cfg["exe"]).is_file() else "Missing"
                item = self.tree.insert("", "end", values=(
                    cfg["model_name"],
                    core.flag_value(cfg["args"], "--max-context", "?"),
                    "Yes" if cfg.get("vision") else "No", ready))
                self.model_files[item] = (path, cfg)
                if preferred and path == preferred:
                    wanted = item
            items = self.tree.get_children()
            if items:
                self.tree.selection_set(wanted or items[0])
                self.tree.focus(wanted or items[0])
            else:
                self.selected_path = None
                self.selected_label.configure(text="No installed models · prepare one below.")
        finally:
            self._loading_form = False
        if self.tree.selection():
            self._select_model()
        self._set_busy(self.machine.busy)

    def _select_model(self, _event=None):
        if self._loading_form:
            return
        selection = self.tree.selection()
        if not selection or selection[0] not in self.model_files:
            return
        path, cfg = self.model_files[selection[0]]
        if self.dirty and self.selected_path and path != self.selected_path:
            if self.machine.busy:
                discard = messagebox.askyesno(
                    "Discard changes?", "An operation is running, so settings cannot be saved now. "
                    "Discard the unsaved changes and choose another model?")
                if not discard:
                    self._restore_tree_selection()
                    return
            else:
                choice = messagebox.askyesnocancel(
                    "Unsaved settings", "Save settings for the previous model before switching?\n"
                    "Yes: save   ·   No: discard   ·   Cancel: stay on this model.")
                if choice is None or (choice and not self.save_selected()):
                    self._restore_tree_selection()
                    return
        self._loading_form = True
        try:
            self.selected_path = path
            self.selected_label.configure(text=path.name +
                                          ("  ·  currently running" if self.active_config_path == path else ""))
            args = cfg["args"]
            self.host.set(cfg.get("host") or "127.0.0.1")
            self.port.set(str(cfg.get("port") or 8080))
            self.api_key.set(cfg.get("api_key") or "")
            self.gpu.set(str(cfg.get("gpu")) if cfg.get("gpu") is not None else "Auto")
            self.cpu_workers.set(core.flag_value(args, "--pool-workers", "0"))
            self.vision_threads.set(str(cfg.get("vision", {}).get("threads", 0))
                                    if isinstance(cfg.get("vision"), dict) else "0")
            self.expert_cache.set(core.flag_value(args, "--expert-cache", "auto"))
            self.prefill.set(core.flag_value(args, "--prefill", "auto"))
            self.fit_max_tokens.set(bool(cfg.get("fit_max_tokens", False)))
            self.endpoint.set(core.local_url(cfg) + "/v1")
            self._refresh_api_urls()
            self.dirty = False
            self.dirty_label.configure(text="")
        finally:
            self._loading_form = False
        self._save_prefs()
        self.current_activity.set("Selected " + str(cfg["model_name"]))

    def _refresh_api_urls(self, *_):
        if self.host.get() != "0.0.0.0":
            self.lan_endpoint.set("LAN access off · bind to 0.0.0.0 to enable")
            self.available_lan_urls = []
            return
        if not self.api_key.get().strip():
            self.lan_endpoint.set("Generate an API key before enabling LAN access")
            self.available_lan_urls = []
            return
        try:
            port = int(self.port.get())
            if not 1 <= port <= 65535:
                raise ValueError
            self.available_lan_urls = core.lan_urls(
                {"host": "0.0.0.0", "port": port}, self.local_ips)
            self.lan_endpoint.set(", ".join(self.available_lan_urls) if self.available_lan_urls else
                                  "No LAN IPv4 address found · check Windows network settings")
        except (TypeError, ValueError):
            self.available_lan_urls = []
            self.lan_endpoint.set("Enter a valid port to show LAN addresses")

    def refresh_lan_addresses(self):
        self.local_ips = core.lan_addresses()
        self._refresh_api_urls()

    def copy_lan_url(self):
        if not getattr(self, "available_lan_urls", []):
            messagebox.showinfo("No LAN URL", "Configure a LAN bind address, port and API key first.")
            return
        self.clipboard_clear()
        self.clipboard_append(self.available_lan_urls[0])
        self.current_activity.set("LAN API URL copied")

    def _runtime_values(self):
        return dict(host=self.host.get(), port=self.port.get(), api_key=self.api_key.get(),
                    gpu=self.gpu.get(), cpu_workers=self.cpu_workers.get(),
                    vision_threads=self.vision_threads.get(), expert_cache=self.expert_cache.get(),
                    prefill=self.prefill.get(), fit_max_tokens=self.fit_max_tokens.get())

    def _validate_runtime(self, values):
        return core.validate_runtime(*(values[name] for name in (
            "host", "port", "api_key", "gpu", "cpu_workers", "vision_threads",
            "expert_cache", "prefill")))

    def save_selected(self):
        if self.machine.busy:
            messagebox.showwarning("Operation in progress",
                                   "Stop the running operation before editing its saved configuration.")
            return False
        if not self.selected_path:
            messagebox.showinfo("Select a model", "Select an installed model first.")
            return False
        try:
            config = core.apply_runtime(self.selected_path, **self._runtime_values())
            self._save_prefs()
            self.endpoint.set(core.local_url(config) + "/v1")
            self.dirty = False
            self.dirty_label.configure(text="")
            self.current_activity.set("Configuration saved · changes apply on the next launch")
            self._log("Saved model configuration: " + self.selected_path.name)
            return True
        except (OSError, ValueError) as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return False

    def install_model(self):
        if self.machine.busy:
            return
        try:
            if not self.data_root.get().strip():
                raise ValueError("Choose a data root folder, not an existing models/ directory.")
            values = self._runtime_values()
            self._validate_runtime(values)
            config_path = core.model_config_path(self.root_dir, self.family.get(), self.model.get())
            py = self.root_dir / ".venv" / "Scripts" / "python.exe"
            command = core.setup_command(
                py, self.root_dir, family=self.family.get(), model=self.model.get(),
                context=int(self.context.get()), kv=self.kv.get(), vision=self.vision.get(),
                projection=self.projection.get(), data_dir=Path(self.data_root.get()),
                gpu=self.gpu.get(), gguf_dir=self.gguf_folder.get())
        except (ValueError, OSError) as exc:
            messagebox.showerror("Invalid model setup", str(exc))
            return
        if not messagebox.askyesno(
                "Prepare model",
                "Prepare this configuration with Strata's existing installer?\n\n"
                "It may download large model files. Existing completed downloads are reused, and "
                "previous model configurations are retained."):
            return
        self.pending_config = config_path
        self.pending_runtime = values
        self._start_operation("setup", command, bootstrap=True)

    def calibrate(self):
        if self.machine.busy or not self.selected_path:
            return
        if not self.save_selected():
            return
        if not messagebox.askyesno("Calibrate model",
                                   "Run hardware calibration for this selected model? "
                                   "The configured model and engine will be used during tuning."):
            return
        py = self.root_dir / ".venv" / "Scripts" / "python.exe"
        if not py.exists():
            messagebox.showerror("Python environment missing", "Prepare a model first.")
            return
        self._start_operation("calibration", [
            str(py), "-u", str(self.root_dir / "desktop" / "calibrate_selected.py"),
            str(self.selected_path)])

    def start_server(self):
        if self.machine.busy or not self.selected_path:
            return
        if not self.save_selected():
            return
        py = self.root_dir / ".venv" / "Scripts" / "python.exe"
        if not py.exists():
            messagebox.showerror("Python environment missing", "Prepare a model first.")
            return
        try:
            config = core.read_json(self.selected_path)
            engine = Path(config["exe"])
            if not engine.is_file():
                raise ValueError("The configured engine is missing: " + str(engine) +
                                 "\nPrepare this model again before starting.")
            command = core.server_command(py, self.root_dir, self.selected_path,
                                          config, self.mcp_file.get())
        except (KeyError, ValueError, OSError) as exc:
            messagebox.showerror("Cannot start model", str(exc))
            return
        if self.active_config_path != self.selected_path:
            self.new_chat()
        self.active_config_path = self.selected_path
        self.active_config = config
        self.active_model_text.set(config["model_name"])
        self._start_operation("server", command)

    def _start_operation(self, kind, command, bootstrap=False):
        token = self.machine.begin(kind)
        self.operation = kind
        self.stop_requested.clear()
        self.status.set({"setup": "INSTALLING", "calibration": "CALIBRATING",
                         "server": "STARTING"}[kind])
        self.side_status.configure(fg=WARNING)
        self.current_activity.set({"setup": "Preparing selected model",
                                   "calibration": "Calibrating the selected configuration",
                                   "server": "Loading model into memory"}[kind])
        self._set_busy(True)
        self._show_page(5)
        threading.Thread(target=self._worker, args=(token, kind, command, bootstrap),
                         daemon=True, name="strata-process").start()

    def _worker(self, token, kind, command, bootstrap):
        try:
            if bootstrap and not (self.root_dir / ".venv" / "Scripts" / "python.exe").exists():
                bootstrap_cmd = [str(self.root_dir / "START-HERE.bat"), "--check"]
                self.events.put(("line", token, "Creating the Strata Python environment..."))
                code = self._pipe(token, "bootstrap", bootstrap_cmd)
                if code:
                    self.events.put(("finished", token, kind, code))
                    return
            if self.stop_requested.is_set():
                self.events.put(("finished", token, kind, 130))
                return
            code = self._pipe(token, kind, command)
            self.events.put(("finished", token, kind, code))
        except Exception as exc:
            self.events.put(("line", token, "Process launch failed: " + str(exc)))
            self.events.put(("finished", token, kind, 1))

    def _pipe(self, token, kind, command):
        if self.stop_requested.is_set():
            return 130
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        proc = subprocess.Popen(command, cwd=str(self.root_dir), stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, encoding="utf-8", errors="replace", bufsize=1,
                                creationflags=flags)
        self.proc = proc
        if self.stop_requested.is_set():
            self._terminate_tree(proc)
        try:
            for line in proc.stdout:
                self.events.put(("line", token, line.rstrip("\r\n")))
                if kind == "server" and line.startswith("ready: "):
                    self.events.put(("ready", token))
            return proc.wait()
        finally:
            if proc.stdout:
                proc.stdout.close()
            if self.proc is proc:
                self.proc = None

    def _log(self, line):
        safe = runtime.redact(str(line), (self.api_key.get(),))
        tag = ("log_error" if "error" in safe.lower() or "[X]" in safe or "traceback" in safe.lower()
               else "log_ready" if "ready:" in safe or "[ok]" in safe else "")
        self.log_text.insert("end", safe + "\n", tag)
        if int(self.log_text.index("end-1c").split(".")[0]) > 2500:
            self.log_text.delete("1.0", "400.0")
        self.log_text.see("end")

    def _poll(self):
        try:
            for _ in range(250):
                event = self.events.get_nowait()
                kind = event[0]
                if kind == "line":
                    if event[1] == self.machine.generation:
                        self._log(event[2])
                elif kind == "ready":
                    if self.machine.ready(event[1]):
                        self.status.set("ONLINE")
                        self.side_status.configure(fg=SUCCESS)
                        self.current_activity.set("Model online · " + core.local_url(self.active_config or {}))
                        self.chat_status.set("Connected · replies stream as they are generated")
                        self._set_busy(True)
                        self.fetch_metrics()
                elif kind == "finished":
                    token, operation, code = event[1:]
                    was_stopping = self.machine.state == runtime.RunState.STOPPING
                    if not self.machine.finished(token):
                        continue
                    self.operation = ""
                    self._log(f"{operation} finished (exit code {code}).")
                    self.status.set("OFFLINE" if code == 0 or was_stopping else "ERROR")
                    self.side_status.configure(fg=MUTED if code == 0 or was_stopping else WARNING)
                    self.current_activity.set(
                        "Stopped" if was_stopping else
                        "Model preparation complete" if operation == "setup" and code == 0 else
                        "Operation complete" if code == 0 else
                        "Operation failed · review Activity")
                    if operation == "server":
                        self.cancel_chat(silent=True)
                        self.active_config_path = None
                        self.active_config = None
                        self.active_model_text.set("No active model")
                        self.monitor_state.set("OFFLINE")
                        self.monitor_toks.set("0.0")
                        self.monitor_queue.set("0")
                        self.metrics_busy = False
                        self.chat_status.set("Start a model to send messages")
                    if operation == "setup" and code == 0 and self.pending_config:
                        try:
                            core.apply_runtime(self.pending_config, **self.pending_runtime)
                            self.dirty = False
                            self.dirty_label.configure(text="")
                            self.data_root.set(str(core.current_data_root(self.root_dir)))
                            self.refresh_models(self.pending_config)
                            self._save_prefs()
                            self._log("Model prepared and selected. Use Start model to serve it.")
                        except (ValueError, OSError) as exc:
                            self._log("Model prepared; could not apply desktop settings: " + str(exc))
                    elif operation == "calibration" and code == 0:
                        self.dirty = False
                        self.dirty_label.configure(text="")
                        self.refresh_models(self.selected_path)
                    self.pending_config = None
                    self.pending_runtime = None
                    self._set_busy(False)
                elif kind == "chat_chunk":
                    token, request_id, name, value = event[1:]
                    if token != self.machine.generation or request_id != self.chat_request_id:
                        continue
                    if name == "content":
                        self.partial_answer += value
                        self._chat_text(value)
                    elif name == "reasoning":
                        self._chat_text(value, "thought")
                    elif name == "finish":
                        self.chat_status.set("Finish reason: " + value)
                elif kind == "chat_done":
                    token, request_id, success, detail = event[1:]
                    if token != self.machine.generation or request_id != self.chat_request_id:
                        continue
                    self.chat_busy = False
                    self.chat_stop.configure(state="disabled")
                    if success:
                        if self.partial_answer:
                            self.chat_history.append({"role": "assistant", "content": self.partial_answer})
                        else:
                            if self.chat_history and self.chat_history[-1]["role"] == "user":
                                self.chat_history.pop()
                            self._chat_text("\n(No assistant text was returned.)")
                        self._chat_text("\n\n")
                        self.chat_status.set("Reply complete")
                    else:
                        if self.chat_history and self.chat_history[-1]["role"] == "user":
                            self.chat_history.pop()
                        self._chat_text("\n\n" + runtime.redact(detail, (self.api_key.get(),)) + "\n\n",
                                        "error")
                        self.chat_status.set("Request failed · see the error above")
                    self._set_busy(self.machine.busy)
                elif kind == "metrics":
                    token, result, error = event[1:]
                    if token != self.machine.generation:
                        continue
                    self.metrics_busy = False
                    if error:
                        self.metrics_view.delete("1.0", "end")
                        self.metrics_view.insert("end", "Monitor unavailable: " +
                                                 runtime.redact(error, (self.api_key.get(),)))
                        continue
                    summary = runtime.metrics_summary(result)
                    self.monitor_state.set(summary["state"].upper())
                    self.monitor_queue.set(str(summary["queue"]))
                    self.monitor_toks.set(f'{summary["tok_s"]:.1f}')
                    self.monitor_requests.set(str(summary["requests"]))
                    sections = [
                        ("ENGINE", result.get("engine") or {}),
                        ("LIVE REQUEST", result.get("live") or {}),
                        ("TOTALS", result.get("totals") or {}),
                        ("HARDWARE", result.get("hardware") or {})]
                    self.metrics_view.delete("1.0", "end")
                    self.metrics_view.insert("end", "\n\n".join(
                        title + "\n" + json.dumps(value, indent=2, ensure_ascii=False)
                        for title, value in sections))
        except queue.Empty:
            pass
        if not getattr(self, "_closing", False):
            self.after(90, self._poll)

    def _chat_append(self, role, content=""):
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", role.upper() + "\n", "role")
        if content:
            self.chat_view.insert("end", str(content))
        self.chat_view.insert("end", "\n\n")
        self.chat_view.configure(state="disabled")
        self.chat_view.see("end")

    def _chat_text(self, content, tag=""):
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", str(content), tag)
        self.chat_view.configure(state="disabled")
        self.chat_view.see("end")

    def new_chat(self):
        if self.chat_busy:
            messagebox.showinfo("Reply in progress", "Cancel the current reply before clearing the conversation.")
            return
        self.chat_history.clear()
        self.chat_view.configure(state="normal")
        self.chat_view.delete("1.0", "end")
        self.chat_view.configure(state="disabled")
        self.chat_status.set("New conversation")

    def _api_request(self, url, timeout=8, api_key=""):
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        request = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def send_chat(self):
        if not runtime.can_send_chat(self.machine, self.active_config_path, self.chat_busy):
            messagebox.showinfo("Start a model", "Start the server and finish the previous reply first.")
            return
        prompt = self.chat_input.get("1.0", "end-1c").strip()
        if not prompt:
            return
        config = dict(self.active_config)
        self.chat_history.append({"role": "user", "content": prompt})
        history = [dict(message) for message in self.chat_history]
        self.chat_input.delete("1.0", "end")
        self._chat_append("You", prompt)
        self._chat_text("STRATA\n", "role")
        self.chat_busy = True
        self.partial_answer = ""
        self.chat_cancel = threading.Event()
        self.chat_request_id += 1
        request_id = self.chat_request_id
        self.chat_status.set("Generating · tokens stream as they arrive")
        self._set_busy(True)
        threading.Thread(target=self._chat_worker, args=(
            self.machine.generation, request_id, config, history, self.chat_cancel),
            daemon=True, name="strata-chat").start()

    def _chat_worker(self, token, request_id, config, history, cancel):
        finish = ""
        try:
            request = runtime.chat_request(core.local_url(config), config.get("api_key", ""),
                                           config["model_name"], history)
            with urllib.request.urlopen(request, timeout=900) as response:
                with self.chat_response_lock:
                    self.chat_response = response
                if cancel.is_set():
                    return
                for kind, value in runtime.openai_sse(response):
                    if cancel.is_set():
                        return
                    if kind == "finish":
                        finish = value
                    self.events.put(("chat_chunk", token, request_id, kind, value))
            self.events.put(("chat_done", token, request_id, True, finish))
        except Exception as exc:
            if not cancel.is_set():
                self.events.put(("chat_done", token, request_id, False,
                                 str(runtime.api_error(exc))))
        finally:
            with self.chat_response_lock:
                self.chat_response = None

    def cancel_chat(self, silent=False):
        if not self.chat_busy:
            return
        self.chat_cancel.set()
        self.chat_request_id += 1
        with self.chat_response_lock:
            response = self.chat_response
        if response is not None:
            threading.Thread(target=self._close_response, args=(response,),
                             daemon=True, name="cancel-chat").start()
        self.chat_busy = False
        if self.chat_history and self.chat_history[-1]["role"] == "user":
            self.chat_history.pop()
        self._chat_text("\n\n[Response cancelled; partial output is not included in the conversation.]\n\n",
                        "thought")
        self.chat_status.set("Reply cancelled" if not silent else "Model stopped")
        self.chat_stop.configure(state="disabled")
        self._set_busy(self.machine.busy)

    @staticmethod
    def _close_response(response):
        try:
            response.close()
        except OSError:
            pass

    def fetch_metrics(self):
        if self.metrics_busy or self.machine.state != runtime.RunState.RUNNING or not self.active_config:
            return
        self.metrics_busy = True
        config = dict(self.active_config)
        token = self.machine.generation
        threading.Thread(target=self._metrics_worker, args=(token, config),
                         daemon=True, name="strata-metrics").start()

    def _metrics_worker(self, token, config):
        try:
            result = self._api_request(core.local_url(config) + "/metrics",
                                       api_key=config.get("api_key", ""))
            self.events.put(("metrics", token, result, None))
        except Exception as exc:
            self.events.put(("metrics", token, None, str(runtime.api_error(exc))))

    def _metrics_timer(self):
        if getattr(self, "_closing", False):
            return
        self.fetch_metrics()
        self.after(5000, self._metrics_timer)

    def export_log(self):
        file = filedialog.asksaveasfilename(title="Export Strata activity",
                                            defaultextension=".txt",
                                            filetypes=[("Text log", "*.txt")])
        if not file:
            return
        try:
            Path(file).write_text(self.log_text.get("1.0", "end-1c"), encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Cannot export log", str(exc))
        else:
            self.current_activity.set("Activity exported")


    def _set_busy(self, _busy):
        busy = self.machine.busy
        selected = self.selected_path is not None
        self.start_button.configure(state="disabled" if busy or not selected else "normal")
        self.install_button.configure(state="disabled" if busy else "normal")
        self.save_engine_button.configure(state="disabled" if busy or not selected else "normal")
        self.save_api_button.configure(state="disabled" if busy or not selected else "normal")
        self.calibrate_button.configure(state="disabled" if busy or not selected else "normal")
        self.stop_button.configure(state="normal" if busy and
                                   self.machine.state != runtime.RunState.STOPPING else "disabled")
        self.chat_send.configure(state="normal" if
                                 runtime.can_send_chat(self.machine, self.active_config_path,
                                                       self.chat_busy) else "disabled")
        self.chat_stop.configure(state="normal" if self.chat_busy else "disabled")

    def stop_server(self):
        if not self.machine.busy or self.machine.state == runtime.RunState.STOPPING:
            return
        questions = {
            "setup": ("Cancel installation?", "Stop preparing this model? Completed downloads are retained."),
            "calibration": ("Stop calibration?", "Interrupt tuning the selected model?"),
            "server": ("Stop model?", "Stop the server and interrupt its active API requests?"),
        }
        title, question = questions.get(self.operation, ("Stop operation?", "Stop the active operation?"))
        if not messagebox.askyesno(title, question):
            return
        self.machine.stopping()
        self.stop_requested.set()
        self.status.set("STOPPING")
        self.side_status.configure(fg=WARNING)
        self.current_activity.set("Stopping supervised process...")
        self.cancel_chat(silent=True)
        self._set_busy(True)
        if self.proc is not None:
            threading.Thread(target=self._terminate_tree, args=(self.proc,),
                             daemon=True, name="strata-stop").start()

    @staticmethod
    def _terminate_tree(proc):
        if proc.poll() is not None:
            return
        if os.name == "nt":
            try:
                result = subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                        capture_output=True, timeout=15, check=False,
                                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                if result.returncode == 0:
                    return
            except (OSError, subprocess.TimeoutExpired):
                pass
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    def open_chat(self):
        self._open_web("")

    def open_monitor(self):
        self._open_web("#monitor")

    def _open_web(self, suffix):
        config = self.active_config if self.machine.server and self.active_config else (
            core.read_json(self.selected_path) if self.selected_path else {})
        try:
            webbrowser.open(core.local_url(config) + "/" + suffix)
        except (TypeError, ValueError, OSError) as exc:
            messagebox.showerror("Invalid model port", str(exc))

    def copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.endpoint.get())
        self.current_activity.set("API URL copied to clipboard")

    def copy_key(self):
        if not self.api_key.get().strip():
            messagebox.showinfo("No API key", "Generate or enter a key first.")
            return
        self.clipboard_clear()
        self.clipboard_append(self.api_key.get())
        self.current_activity.set("API key copied to clipboard")

    def close_app(self):
        if self.machine.busy:
            if not messagebox.askyesno("Exit Strata Desktop",
                                       "An operation is active. Stop the supervised process and close the app?"):
                return
            self.stop_requested.set()
            self.chat_cancel.set()
            if self.proc is not None:
                self._terminate_tree(self.proc)
        try:
            self._save_prefs()
        except OSError as exc:
            if not messagebox.askyesno("Cannot save preferences",
                                       f"{exc}\nExit without saving desktop preferences?"):
                return
        self._closing = True
        self.destroy()

if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Strata Desktop is a Windows app. Use ./setup.sh on Linux.")
    Desktop().mainloop()
