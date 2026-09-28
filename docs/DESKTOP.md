# Strata Desktop (Windows)

Strata Desktop is a native Windows controller for the existing Strata installer and server. The layout is inspired by the model management/tuning workflow of FreeToken, but it uses its own code and Strata's existing backend. It does not ship model weights or replace the existing browser Chat/Monitor.

## Launch

Double-click `DESKTOP.bat` in the Strata project directory. If a packaged executable is present, it opens that; otherwise, it uses the Python installation in `.venv` or the Windows Python launcher. On the first launch, select the Strata folder if prompted. Use the **Models** tab to prepare a model. The desktop manager calls `START-HERE.bat --check` to bootstrap Strata's Python environment when `.venv` does not exist, then invokes the normal `setup.py --setup --yes --no-start` installer. Python/engine/model dependencies still require the same NVIDIA hardware and network access as the ordinary installer.

To build the standalone GUI on Windows, double-click `BUILD-DESKTOP.bat` (run the regular Strata setup once first). The output is `dist\StrataDesktop\StrataDesktop.exe`. Keep its entire sibling `_internal` folder. This EXE packages the **GUI only**; it locates a Strata source checkout containing `setup.py` and `serve/server.py` and runs its original environment. No NVIDIA engine or model weights are bundled in the desktop executable.

The Windows GitHub Actions workflow also builds a ZIP artifact of the GUI. The artifact is generated on a Windows runner, not on Linux.

## Controls

- **Models:** choose an installed model, configure Qwen/Swift/Coder quantization, context, KV precision, vision, optional existing GGUF folder and data root; prepare or switch models without deleting existing configurations.
- **Engine:** GPU index, CPU expert worker count (`--pool-workers`; 0 = automatic), vision encoder threads, VRAM expert cache and prefill chunk; optionally calibrate the selected configuration using the existing tuning code.
- **API & Tools:** bind address, port, API key generation, fit-max-tokens, optional MCP configuration JSON and local API URL. Network binding requires an API key in the desktop app. It listens on all interfaces when set to `0.0.0.0`; clients should use the PC's LAN address rather than `0.0.0.0`.
- **Chat:** native Quick Chat through the running Strata API; the full browser Chat remains available for image uploads, tool usage and advanced controls.
- **Monitor:** live engine, request and hardware metrics read from the existing authenticated `/metrics` endpoint.
- **Activity:** live installer/engine/server output and start/stop controls. Stop terminates the supervised process tree on Windows (including in-flight requests).

**Concurrency:** the current engine supports **one active model-generation request**; additional requests are queued by the HTTP server. CPU workers are parallel expert-computation threads, not concurrent model-request slots. The desktop intentionally does not offer a misleading "concurrent generations" switch. Changing advanced options requires stopping and restarting the server.

**Storage:** select the parent data directory, e.g. `E:\Strata-data`, not an existing `E:\Strata-main\models` folder. The manager rejects a model/packs/mtp descendant and detects an already nested `models\models` hierarchy left by an interrupted migration. It does not automatically delete, flatten, or repair old files. The separate pending storage-safety PR provides equivalent protections for CLI-only setup.

**Authentication:** the API key is stored in the selected model's Strata JSON configuration, following Strata's existing server behaviour. Do not share the configuration file. Desktop preferences (Strata path and optional MCP config path) do not contain the key. If you expose the server on the LAN, use a strong key, private-network firewall rules and an appropriately trusted network; the API is HTTP, not TLS.

The local API base is `http://127.0.0.1:<port>/v1`; the Anthropic-compatible path is `http://127.0.0.1:<port>/v1/messages`. The browser Chat and Monitor are provided by the same server.

## Developer validation

From the project directory, run:

```powershell
python -m unittest discover -s desktop -p "test_*.py" -v
python -m py_compile desktop/app.py desktop/strata_desktop_core.py desktop/calibrate_selected.py
```

Unit tests do not download models or start the GPU engine. Windows GUI packaging and end-to-end model downloads/serving require a Windows machine with compatible NVIDIA hardware.
