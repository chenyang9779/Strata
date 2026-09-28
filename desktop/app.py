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


BG = "#101827"
PANEL = "#192536"
FIELD = "#223149"
TEXT = "#eef3fa"
MUTED = "#a9bbd1"
ACCENT = "#51b9d6"
LOG_BG = "#0c1420"


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
        self.title("Strata Desktop")
        self.geometry("1100x820")
        self.minsize(875, 680)
        self.configure(background=BG)
        self.protocol("WM_DELETE_WINDOW", self.close_app)
        self.events = queue.Queue()
        self.proc = None
        self.operation = ""
        self.pending_config = None
        self.pending_runtime = None
        self.model_files = {}
        self.selected_path = None
        self.chat_history = []
        self.chat_busy = False
        self.metrics_busy = False
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
        self.status = tk.StringVar(value="Stopped")
        self.endpoint = tk.StringVar(value="http://127.0.0.1:8080/v1")
        self._theme()
        self._layout()
        self.family.trace_add("write", self._family_changed)
        self.refresh_models()
        self.after(120, self._poll)
        self.after(5000, self._metrics_timer)

    def _save_prefs(self):
        self.prefs["root"] = str(self.root_dir)
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
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI Semibold", 19))
        style.configure("TButton", background=FIELD, foreground=TEXT, padding=(12, 8), borderwidth=0)
        style.map("TButton", background=[("active", "#314965"), ("disabled", PANEL)],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=ACCENT, foreground="#061520",
                        font=("Segoe UI Semibold", 10))
        style.map("Accent.TButton", background=[("active", "#79d9ed"), ("disabled", FIELD)])
        style.configure("TEntry", fieldbackground=FIELD, foreground=TEXT, insertcolor=TEXT, padding=5)
        style.configure("TCombobox", fieldbackground=FIELD, background=FIELD, foreground=TEXT,
                        selectbackground=FIELD, selectforeground=TEXT, arrowcolor=TEXT, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", FIELD)], foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", FIELD)], selectforeground=[("readonly", TEXT)])
        style.configure("TCheckbutton", background=PANEL, foreground=TEXT)
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=PANEL, foreground=MUTED, padding=(18, 11))
        style.map("TNotebook.Tab", background=[("selected", FIELD)], foreground=[("selected", TEXT)])
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=28, borderwidth=0)
        style.configure("Treeview.Heading", background=FIELD, foreground=TEXT, relief="flat")
        style.map("Treeview", background=[("selected", "#226581")], foreground=[("selected", TEXT)])
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", TEXT)

    def _layout(self):
        header = ttk.Frame(self, padding=(20, 14))
        header.pack(fill="x")
        ttk.Label(header, text="STRATA  /  DESKTOP", style="Title.TLabel").pack(side="left")
        ttk.Label(header, textvariable=self.status, foreground=ACCENT).pack(side="right", padx=12)
        bar = ttk.Frame(self, padding=(20, 0, 20, 12))
        bar.pack(fill="x")
        ttk.Label(bar, text=str(self.root_dir), foreground=MUTED).pack(side="left")
        self.stop_button = ttk.Button(bar, text="Stop", command=self.stop_server)
        self.stop_button.pack(side="right", padx=(8, 0))
        self.start_button = ttk.Button(bar, text="Start selected model", style="Accent.TButton",
                                       command=self.start_server)
        self.start_button.pack(side="right", padx=(8, 0))
        ttk.Button(bar, text="Open Chat", command=self.open_chat).pack(side="right")

        self.tabs = ttk.Notebook(self)
        self.tabs.pack(expand=True, fill="both", padx=20, pady=(0, 14))
        models = ttk.Frame(self.tabs, padding=16)
        engine = ttk.Frame(self.tabs, padding=16)
        api = ttk.Frame(self.tabs, padding=16)
        chat = ttk.Frame(self.tabs, padding=16)
        monitor = ttk.Frame(self.tabs, padding=16)
        logs = ttk.Frame(self.tabs, padding=16)
        self.tabs.add(models, text="Models")
        self.tabs.add(engine, text="Engine")
        self.tabs.add(api, text="API & Tools")
        self.tabs.add(chat, text="Chat")
        self.tabs.add(monitor, text="Monitor")
        self.tabs.add(logs, text="Activity")
        self._models_tab(models)
        self._engine_tab(engine)
        self._api_tab(api)
        self._chat_tab(chat)
        self._monitor_tab(monitor)
        self._logs_tab(logs)
        self._set_busy(False)

    def _section(self, parent, title, description=""):
        wrapper = ttk.Frame(parent, style="Panel.TFrame", padding=15)
        wrapper.pack(fill="x", pady=(0, 12))
        ttk.Label(wrapper, text=title, style="Panel.TLabel",
                  font=("Segoe UI Semibold", 12)).pack(anchor="w", pady=(0, 3))
        if description:
            ttk.Label(wrapper, text=description, style="Hint.TLabel", wraplength=950).pack(anchor="w", pady=(0, 10))
        grid = ttk.Frame(wrapper, style="Panel.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        return grid

    def _field(self, parent, line, title, variable, values=None, browse=None, secret=False):
        ttk.Label(parent, text=title, style="Panel.TLabel").grid(row=line, column=0, sticky="w", pady=5, padx=(0, 16))
        if values is not None:
            w = ttk.Combobox(parent, textvariable=variable, values=values, state="readonly", width=25)
        else:
            w = ttk.Entry(parent, textvariable=variable, show="*" if secret else "", width=48)
        w.grid(row=line, column=1, sticky="ew", pady=5)
        if browse:
            ttk.Button(parent, text="Browse", command=browse).grid(row=line, column=2, padx=(10, 0), pady=5)
        return w

    def _models_tab(self, parent):
        top = self._section(parent, "Installed models",
                            "Select an installed configuration to load its settings. Only one model can generate at a time.")
        self.tree = ttk.Treeview(top, columns=("model", "context", "images"), show="headings", height=5)
        for key, title, width in (("model", "Model", 330), ("context", "Context", 120),
                                  ("images", "Images", 100)):
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
                    ["auto", "0", "1024", "2048", "4096", "8192"])
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

    def _chat_tab(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Quick Chat  /  OpenAI-compatible API",
                  font=("Segoe UI Semibold", 12)).pack(side="left")
        ttk.Button(bar, text="Open full browser Chat", command=self.open_chat).pack(side="right")
        ttk.Button(bar, text="New conversation", command=self.new_chat).pack(side="right", padx=8)
        viewer = ttk.Frame(parent)
        viewer.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(viewer)
        scroll.pack(side="right", fill="y")
        self.chat_view = tk.Text(viewer, background=LOG_BG, foreground=TEXT, state="disabled",
                                 wrap="word", font=("Segoe UI", 10), padx=14, pady=14,
                                 highlightthickness=0, relief="flat", yscrollcommand=scroll.set)
        self.chat_view.pack(fill="both", expand=True)
        self.chat_view.tag_configure("role", foreground=ACCENT, font=("Segoe UI Semibold", 10))
        scroll.configure(command=self.chat_view.yview)
        entry = ttk.Frame(parent)
        entry.pack(fill="x", pady=(12, 0))
        self.chat_input = tk.Text(entry, height=3, wrap="word", background=FIELD,
                                  foreground=TEXT, insertbackground=TEXT, font=("Segoe UI", 10),
                                  relief="flat", padx=10, pady=8)
        self.chat_input.pack(side="left", fill="both", expand=True)
        self.chat_input.bind("<Control-Return>", lambda _event: self.send_chat())
        self.chat_send = ttk.Button(entry, text="Send", style="Accent.TButton", command=self.send_chat)
        self.chat_send.pack(side="right", padx=(10, 0))
        ttk.Label(parent, text="Ctrl+Enter sends. For image uploads, tools and advanced chat controls, use the browser Chat.",
                  foreground=MUTED).pack(anchor="w", pady=(8, 0))

    def _monitor_tab(self, parent):
        bar = ttk.Frame(parent)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Live engine and hardware metrics",
                  font=("Segoe UI Semibold", 12)).pack(side="left")
        ttk.Button(bar, text="Open full Monitor", command=self.open_chat).pack(side="right")
        ttk.Button(bar, text="Refresh", command=self.fetch_metrics).pack(side="right", padx=8)
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(outer)
        scroll.pack(side="right", fill="y")
        self.metrics_view = tk.Text(outer, background=LOG_BG, foreground="#cce7f2",
                                    font=("Consolas", 10), wrap="word", relief="flat",
                                    highlightthickness=0, padx=14, pady=14, yscrollcommand=scroll.set)
        self.metrics_view.pack(fill="both", expand=True)
        self.metrics_view.insert("end", "Start a model to view live metrics.\n")
        scroll.config(command=self.metrics_view.yview)

    def _logs_tab(self, parent):
        row = ttk.Frame(parent)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Installer, server and engine output").pack(side="left")
        ttk.Button(row, text="Clear view", command=lambda: self.log_text.delete("1.0", "end")).pack(side="right")
        outer = ttk.Frame(parent)
        outer.pack(fill="both", expand=True)
        scroll = ttk.Scrollbar(outer)
        scroll.pack(side="right", fill="y")
        self.log_text = tk.Text(outer, background=LOG_BG, foreground="#cce7f2",
                                insertbackground=TEXT, font=("Consolas", 9), wrap="word",
                                relief="flat", highlightthickness=0, padx=12, pady=10,
                                state="normal", yscrollcommand=scroll.set)
        self.log_text.pack(fill="both", expand=True)
        scroll.config(command=self.log_text.yview)
        self._log("Strata Desktop is ready. Select a model or install a new one.")

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

    def refresh_models(self, select_path=None):
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.model_files.clear()
        for path, cfg in core.installed_models(self.root_dir):
            iid = self.tree.insert("", "end", values=(
                cfg["model_name"],
                core.flag_value(cfg["args"], "--max-context", "?"),
                "Yes" if cfg.get("vision") else "No"))
            self.model_files[iid] = (path, cfg)
            if select_path and path == select_path:
                self.tree.selection_set(iid)
        if not self.tree.selection() and self.tree.get_children():
            self.tree.selection_set(self.tree.get_children()[0])
        if self.tree.selection():
            self._select_model()
        else:
            self.selected_path = None
            self.selected_label.configure(text="No installed model. Use the installer below.")

    def _select_model(self, _event=None):
        selection = self.tree.selection()
        if not selection or selection[0] not in self.model_files:
            return
        path, cfg = self.model_files[selection[0]]
        self.selected_path = path
        self.selected_label.configure(text=path.name)
        args = cfg["args"]
        self.host.set(cfg.get("host") or "127.0.0.1")
        self.port.set(str(cfg.get("port") or 8080))
        self.api_key.set(cfg.get("api_key") or "")
        self.gpu.set(str(cfg.get("gpu")) if cfg.get("gpu") is not None else "Auto")
        self.cpu_workers.set(core.flag_value(args, "--pool-workers", "0"))
        self.vision_threads.set(str(cfg.get("vision", {}).get("threads", 0)) if isinstance(cfg.get("vision"), dict) else "0")
        self.expert_cache.set(core.flag_value(args, "--expert-cache", "auto"))
        self.prefill.set(core.flag_value(args, "--prefill", "auto"))
        self.fit_max_tokens.set(bool(cfg.get("fit_max_tokens", False)))
        self.endpoint.set(core.local_url(cfg) + "/v1")

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
        if self.operation:
            messagebox.showwarning("Server busy", "Stop the server or wait for setup to finish before changing configuration.")
            return False
        if not self.selected_path:
            messagebox.showinfo("Select a model", "Choose an installed model first.")
            return False
        try:
            values = self._runtime_values()
            cfg = core.apply_runtime(self.selected_path, **values)
            self._save_prefs()
            self.endpoint.set(core.local_url(cfg) + "/v1")
            self._log(f"Saved settings: {self.selected_path.name}")
            return True
        except (OSError, ValueError) as e:
            messagebox.showerror("Invalid settings", str(e))
            return False

    def install_model(self):
        if self.operation:
            return
        try:
            values = self._runtime_values()
            self._validate_runtime(values)
            cfg_path = core.model_config_path(self.root_dir, self.family.get(), self.model.get())
            py = self.root_dir / ".venv" / "Scripts" / "python.exe"
            command = core.setup_command(py, self.root_dir, family=self.family.get(),
                model=self.model.get(), context=int(self.context.get()), kv=self.kv.get(),
                vision=self.vision.get(), projection=self.projection.get(),
                data_dir=Path(self.data_root.get()), gpu=self.gpu.get(),
                gguf_dir=self.gguf_folder.get())
        except (ValueError, OSError) as e:
            messagebox.showerror("Invalid setup", str(e))
            return
        if not messagebox.askyesno("Prepare model", "Install or reconfigure this model? Setup may download tens of GB. "
                                  "Already completed downloads are reused."):
            return
        self.pending_config, self.pending_runtime = cfg_path, values
        self._start_operation("setup", command, bootstrap=True)

    def calibrate(self):
        if self.operation or not self.selected_path:
            return
        if not self.save_selected():
            return
        if not messagebox.askyesno("Calibrate model", "Calibration may keep the PC busy for 5-10 minutes. Continue?"):
            return
        py = self.root_dir / ".venv" / "Scripts" / "python.exe"
        if not py.exists():
            messagebox.showerror("Python environment missing", "Install a model first.")
            return
        self._start_operation("calibration", [str(py), "-u", str(self.root_dir / "desktop" / "calibrate_selected.py"),
                                               str(self.selected_path)])

    def start_server(self):
        if self.operation or not self.selected_path:
            return
        if not self.save_selected():
            return
        py = self.root_dir / ".venv" / "Scripts" / "python.exe"
        if not py.exists():
            messagebox.showerror("Python environment missing", "Install or prepare a model first.")
            return
        try:
            cfg = core.read_json(self.selected_path)
            command = core.server_command(py, self.root_dir, self.selected_path, cfg, self.mcp_file.get())
        except (ValueError, OSError) as e:
            messagebox.showerror("Cannot start", str(e))
            return
        self._start_operation("server", command)

    def _start_operation(self, kind, command, bootstrap=False):
        self.operation = kind
        self.status.set({"setup": "Preparing model", "calibration": "Calibrating", "server": "Starting"}[kind])
        self._set_busy(True)
        self.tabs.select(5)
        threading.Thread(target=self._worker, args=(kind, command, bootstrap), daemon=True).start()

    def _worker(self, kind, command, bootstrap):
        try:
            if bootstrap and not (self.root_dir / ".venv" / "Scripts" / "python.exe").exists():
                bootstrap_cmd = [str(self.root_dir / "START-HERE.bat"), "--check"]
                self.events.put(("line", "Bootstrapping Strata's Python environment ..."))
                code = self._pipe(bootstrap_cmd)
                if code != 0:
                    self.events.put(("finished", kind, code))
                    return
            code = self._pipe(command)
            self.events.put(("finished", kind, code))
        except Exception as exc:
            self.events.put(("line", f"Process error: {exc}"))
            self.events.put(("finished", kind, 1))

    def _pipe(self, command):
        # Always pass an argument array: paths and user fields must not be interpreted by a shell.
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        p = subprocess.Popen(command, cwd=str(self.root_dir), stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                             encoding="utf-8", errors="replace", bufsize=1,
                             creationflags=flags)
        self.proc = p
        try:
            for line in p.stdout:
                line = line.rstrip("\r\n")
                self.events.put(("line", line))
                if line.startswith("ready: "):
                    self.events.put(("ready",))
            return p.wait()
        finally:
            p.stdout.close()
            if self.proc is p:
                self.proc = None

    def _log(self, line):
        self.log_text.insert("end", line + "\n")
        if int(self.log_text.index("end-1c").split(".")[0]) > 2200:
            self.log_text.delete("1.0", "400.0")
        self.log_text.see("end")

    def _poll(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "line":
                    self._log(event[1])
                elif event[0] == "ready":
                    self.status.set("Running")
                    self.fetch_metrics()
                elif event[0] == "chat":
                    self.chat_busy = False
                    self.chat_send.configure(state="normal")
                    answer = event[1]
                    if event[2]:
                        self.chat_history.append({"role": "assistant", "content": answer})
                        self._chat_append("Strata", answer)
                    else:
                        if self.chat_history and self.chat_history[-1]["role"] == "user":
                            self.chat_history.pop()
                        self._chat_append("Error", answer)
                elif event[0] == "metrics":
                    self.metrics_busy = False
                    self.metrics_view.delete("1.0", "end")
                    self.metrics_view.insert("end", event[1])
                elif event[0] == "finished":
                    kind, code = event[1:]
                    self.operation = ""
                    self._set_busy(False)
                    self.status.set("Stopped" if code == 0 else f"{kind} exited ({code})")
                    self._log(f"{kind} exited with status {code}.")
                    if kind == "setup" and code == 0 and self.pending_config:
                        try:
                            core.apply_runtime(self.pending_config, **self.pending_runtime)
                            self._save_prefs()
                            self.refresh_models(self.pending_config)
                            self._log("Installed model selected. Start it from the top bar.")
                        except (ValueError, OSError) as e:
                            self._log(f"Model prepared, but desktop settings could not be saved: {e}")
                    elif kind == "calibration" and code == 0:
                        self.refresh_models(self.selected_path)
                    self.pending_config = None
                    self.pending_runtime = None
        except queue.Empty:
            pass
        if self.winfo_exists():
            self.after(120, self._poll)

    def _chat_append(self, role, content):
        self.chat_view.configure(state="normal")
        self.chat_view.insert("end", role + "\n", "role")
        self.chat_view.insert("end", str(content) + "\n\n")
        self.chat_view.configure(state="disabled")
        self.chat_view.see("end")

    def new_chat(self):
        if self.chat_busy:
            messagebox.showinfo("Chat in progress", "Wait for the current response before clearing the conversation.")
            return
        self.chat_history.clear()
        self.chat_view.configure(state="normal")
        self.chat_view.delete("1.0", "end")
        self.chat_view.configure(state="disabled")

    def _api_request(self, url, payload=None, timeout=30):
        cfg = core.read_json(self.selected_path) if self.selected_path else {}
        headers = {"Accept": "application/json"}
        if cfg.get("api_key"):
            headers["Authorization"] = "Bearer " + cfg["api_key"]
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(url, data=data, headers=headers)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def send_chat(self):
        if self.chat_busy:
            return
        if self.operation != "server" or self.status.get() != "Running" or not self.selected_path:
            messagebox.showinfo("Start a model", "Start the selected model before using Quick Chat.")
            return
        prompt = self.chat_input.get("1.0", "end-1c").strip()
        if not prompt:
            return
        cfg = core.read_json(self.selected_path)
        self.chat_history.append({"role": "user", "content": prompt})
        history = [dict(msg) for msg in self.chat_history]
        self.chat_input.delete("1.0", "end")
        self._chat_append("You", prompt)
        self.chat_busy = True
        self.chat_send.configure(state="disabled")
        threading.Thread(target=self._chat_worker, args=(cfg, history), daemon=True).start()

    def _chat_worker(self, cfg, history):
        try:
            result = self._api_request(core.local_url(cfg) + "/v1/chat/completions",
                                       {"model": cfg["model_name"], "messages": history,
                                        "max_tokens": 2048, "stream": False}, timeout=900)
            content = result["choices"][0]["message"].get("content") or ""
            self.events.put(("chat", str(content), True))
        except (OSError, ValueError, KeyError, IndexError) as exc:
            self.events.put(("chat", str(exc), False))

    def fetch_metrics(self):
        if self.metrics_busy or self.operation != "server" or self.status.get() != "Running" or not self.selected_path:
            return
        self.metrics_busy = True
        cfg = core.read_json(self.selected_path)
        threading.Thread(target=self._metrics_worker, args=(cfg,), daemon=True).start()

    def _metrics_worker(self, cfg):
        try:
            data = self._api_request(core.local_url(cfg) + "/metrics", timeout=8)
            live = data.get("live") or {}
            engine = data.get("engine") or {}
            totals = data.get("totals") or {}
            lines = ["MODEL", json.dumps(engine, indent=2), "", "LIVE",
                     json.dumps(live, indent=2), "", "TOTALS",
                     json.dumps(totals, indent=2), "", "HARDWARE",
                     json.dumps(data.get("hardware") or {}, indent=2)]
            self.events.put(("metrics", "\n".join(lines)))
        except (OSError, ValueError) as exc:
            self.events.put(("metrics", "Metrics unavailable: " + str(exc)))

    def _metrics_timer(self):
        if self.winfo_exists():
            if self.tabs.index(self.tabs.select()) == 4:
                self.fetch_metrics()
            self.after(5000, self._metrics_timer)

    def _set_busy(self, busy):
        state = "disabled" if busy else "normal"
        self.start_button.configure(state=state)
        self.install_button.configure(state=state)
        self.save_engine_button.configure(state=state)
        self.save_api_button.configure(state=state)
        self.calibrate_button.configure(state=state)
        self.stop_button.configure(state="normal" if busy else "disabled")

    def stop_server(self):
        if not self.proc:
            return
        if self.operation == "setup" and not messagebox.askyesno(
                "Cancel setup", "Stop the installer? Any completed downloads are kept."):
            return
        if self.operation == "calibration" and not messagebox.askyesno(
                "Stop calibration", "Interrupt calibration now?"):
            return
        if self.operation == "server" and not messagebox.askyesno(
                "Stop server", "Stop the model and interrupt current API requests?"):
            return
        proc = self.proc
        self._log("Stopping process tree ...")
        if os.name == "nt":
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=15,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            except (OSError, subprocess.TimeoutExpired):
                proc.terminate()
        else:
            proc.terminate()

    def open_chat(self):
        port = self.port.get().strip()
        if port.isdigit() and 1 <= int(port) <= 65535:
            webbrowser.open(f"http://127.0.0.1:{port}/")
        else:
            messagebox.showerror("Invalid port", "Choose a port between 1 and 65535.")

    def copy_url(self):
        self.clipboard_clear()
        self.clipboard_append(self.endpoint.get())

    def copy_key(self):
        self.clipboard_clear()
        self.clipboard_append(self.api_key.get())

    def close_app(self):
        if self.operation and self.proc:
            if not messagebox.askyesno("Quit Strata Desktop", "A process is running. Stop it and quit?"):
                return
            self.stop_server_on_exit()
        self._save_prefs()
        self.destroy()

    def stop_server_on_exit(self):
        proc = self.proc
        if proc and proc.poll() is None:
            if os.name == "nt":
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                   capture_output=True, timeout=15,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                except (OSError, subprocess.TimeoutExpired):
                    proc.terminate()
            else:
                proc.terminate()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Strata Desktop is a Windows app. Use ./setup.sh on Linux.")
    Desktop().mainloop()
