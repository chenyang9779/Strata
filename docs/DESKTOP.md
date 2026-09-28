# Strata Desktop (Windows)

Strata Desktop is a native Windows controller for the existing Strata installer and server. The layout is inspired by the model management/tuning workflow of FreeToken, but it uses its own code and Strata's existing backend. It does not ship model weights or replace the existing browser Chat/Monitor.

## Launch

Double-click `DESKTOP.bat` in the Strata project directory. If a packaged executable is present, it opens that; otherwise, it uses the Python installation in `.venv` or the Windows Python launcher. On the first launch, select the Strata folder if prompted. Use **Models** to prepare a model. The desktop manager calls `START-HERE.bat --check` to bootstrap Strata's Python environment when `.venv` does not exist, then invokes the normal `setup.py --setup --yes --no-start` installer. Python/engine/model dependencies still require the same NVIDIA hardware and network access as the ordinary installer.

To build the standalone GUI on Windows, double-click `BUILD-DESKTOP.bat` (run the regular Strata setup once first). The output is `dist\StrataDesktop\StrataDesktop.exe`. Keep its entire sibling `_internal` folder. This EXE packages the **GUI only**; it locates a Strata source checkout containing `setup.py` and `serve/server.py` and runs its original environment. No NVIDIA engine or model weights are bundled in the desktop executable.

The Windows GitHub Actions workflow also runs the desktop unit tests, a native Tk window/navigation smoke test,
a local mock HTTP/SSE streaming integration test, Python syntax checks, a packaged EXE self-test and a ZIP artifact. The ZIP is
available from that workflow run's Artifacts section; extract the entire folder before launching the EXE.

## Controls

The interface has six views in a persistent navigation rail. Press **Ctrl+1** through **Ctrl+6** to switch views.

- **Models:** installed configurations show model/context/image/engine readiness; selection is remembered. The installer supports Qwen/Swift/Coder, quantization, context, KV, vision, existing GGUF files and a separate data root. Switching away from unsaved changes prompts you to save, discard or cancel.
- **Engine:** set GPU index, CPU expert workers (`--pool-workers`; 0 = automatic), vision encoder threads, expert cache and prefill; optionally calibrate a selected model. Changes to a running engine are not applied silently: stop, save, then start it again.
- **API & Tools:** bind address, port, generated API key, fit-max-tokens and MCP JSON. The app displays local and actual detected LAN URLs, and lets you copy either. Binding to `0.0.0.0` requires an API key.
- **Quick Chat:** response tokens stream from the existing OpenAI-compatible API as they arrive; cancel an in-flight reply without blocking the interface. Ctrl+Enter sends. Cancelled/incomplete replies are excluded from subsequent context. Image uploads, tools and advanced chat controls remain available in the browser.
- **Monitor:** separate state, throughput, queue and request cards plus engine/hardware details, refreshed while the server runs.
- **Activity:** colour-coded errors/ready lines, a bounded rolling log, text selection/copy, export and supervised start/stop/cancel. Logs redact the active model key.

The header distinguishes **selected configuration** from **currently running model**, and a clear unsaved-settings indicator appears after editing. Windows DPI scaling, keyboard navigation and a custom window icon are supported.

**Concurrency:** the current engine supports **one active model-generation request**; additional requests are queued by the HTTP server. CPU workers are parallel expert-computation threads, not concurrent model-request slots. The desktop intentionally does not offer a misleading "concurrent generations" switch. Changing advanced options requires stopping and restarting the server.

**Storage:** select the parent data directory, e.g. `E:\Strata-data`, not an existing `E:\Strata-main\models` folder. The manager rejects a model/packs/mtp descendant and detects an already nested `models\models` hierarchy left by an interrupted migration. It does not automatically delete, flatten, or repair old files. The separate pending storage-safety PR provides equivalent protections for CLI-only setup.

**Authentication:** the API key is stored in the selected model's Strata JSON configuration, following Strata's existing server behaviour. Do not share the configuration file. Desktop preferences (Strata path and optional MCP config path) do not contain the key. If you expose the server on the LAN, use a strong key, private-network firewall rules and an appropriately trusted network; the API is HTTP, not TLS. The server's public health/status endpoints and static UI are separate from its authenticated API routes.

The local API base is `http://127.0.0.1:<port>/v1`; the Anthropic-compatible path is `http://127.0.0.1:<port>/v1/messages`. The browser Chat and Monitor are provided by the same server.

## Developer validation

From the project directory, run:

```powershell
python -m unittest discover -s desktop -p "test_*.py" -v
python -m py_compile desktop/app.py desktop/strata_desktop_core.py desktop/runtime.py desktop/calibrate_selected.py desktop/smoke_gui.py
python desktop/smoke_gui.py
```

Tests do not download models or start the GPU engine. The SSE integration test serves controlled responses over
127.0.0.1. The GUI smoke test creates a real Tk window and navigates all six views when an interactive desktop
is available. Successful CI packaging is not a substitute for hardware-specific model-loading, inference and
Firewall testing on a compatible Windows NVIDIA machine.
