"""Shared, UI-independent model and server settings for Strata Desktop (standard library only)."""
from __future__ import annotations

import json
import os
import socket
import ipaddress
import tempfile
from pathlib import Path

FAMILIES = {
    "qwen": ("Q2_0", "IQ2_XS", "IQ3_XXS", "IQ3_S"),
    "swift": ("Q2_0", "IQ2_XS", "IQ3_XXS"),
    "coder": ("IQ1_M",),
}
CONTEXTS = (8192, 32768, 65536, 131072, 262144)
DATA_ITEMS = ("models", "packs", "mtp")


def user_dir() -> Path:
    return Path(os.environ.get("APPDATA") or (Path.home() / "AppData" / "Roaming")) / "Strata"


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=path.name + ".", suffix=".tmp", delete=False) as f:
            name = f.name
            json.dump(value, f, indent=1)
            f.write("\n")
        os.replace(name, path)
    finally:
        if name and os.path.exists(name):
            os.unlink(name)


def valid_config(value: dict) -> bool:
    return (isinstance(value.get("exe"), str)
            and isinstance(value.get("args"), list)
            and all(isinstance(x, str) for x in value["args"])
            and isinstance(value.get("model_name"), str))


def installed_models(root: Path) -> list[tuple[Path, dict]]:
    result = []
    for path in root.glob("strata-*.json"):
        config = read_json(path)
        if valid_config(config):
            result.append((path, config))
    return sorted(result, key=lambda pair: pair[0].stat().st_mtime, reverse=True)


def model_config_path(root: Path, family: str, model: str) -> Path:
    if family not in FAMILIES or model not in FAMILIES[family]:
        raise ValueError("Unsupported model family or quantization.")
    prefix = "" if family == "qwen" else family + "-"
    return root / f"strata-{prefix}{model.lower()}.json"


def flag_value(args: list[str], name: str, default: str) -> str:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else default


def set_flag(args: list[str], name: str, value: str | None) -> list[str]:
    result = list(args)
    while name in result:
        i = result.index(name)
        if i + 1 >= len(result):
            raise ValueError(f"Malformed engine option: {name}")
        del result[i:i + 2]
    if value is not None:
        result.extend((name, str(value)))
    return result


def current_data_root(root: Path) -> Path:
    settings = read_json(user_dir() / "settings.json")
    return Path(settings.get("data_dir") or root.parent / "Strata-data").expanduser()


def validate_data_root(root: Path, proposed: Path) -> Path:
    """Guard GUI setup even when an older setup.py without the storage fix is installed."""
    destination = proposed.expanduser().resolve()
    settings = read_json(user_dir() / "settings.json")
    previous = [settings.get("data_dir"), *settings.get("previous_data_dirs", [])]
    sources = [root, *(Path(p).expanduser() for p in previous if p)]
    for source in dict.fromkeys(p.resolve() for p in sources):
        for item in DATA_ITEMS:
            subdir = (source / item).resolve()
            if source != destination and (destination == subdir or subdir in destination.parents):
                raise ValueError(
                    f"{destination} is inside {subdir}. Select a data ROOT instead, e.g. "
                    f"{root.parent / 'Strata-data'}; Strata creates models/, packs/, mtp/ under it."
                )
            if (subdir / item).is_dir():
                raise ValueError(
                    f"Nested directory found: {subdir / item}. A previous migration may have been "
                    "interrupted. Inspect the files before attempting another installation."
                )
    return destination


def validate_runtime(host: str, port: str | int, api_key: str, gpu: str,
                     cpu_workers: str | int, vision_threads: str | int,
                     expert_cache: str, prefill: str) -> tuple[int, int, int, int | None]:
    if host not in ("127.0.0.1", "0.0.0.0"):
        raise ValueError("Bind address must be 127.0.0.1 or 0.0.0.0.")
    if host == "0.0.0.0" and not api_key.strip():
        raise ValueError("An API key is required when binding to 0.0.0.0.")
    try:
        parsed_port = int(port)
        workers = int(cpu_workers)
        vision = int(vision_threads)
        device = None if gpu == "Auto" else int(gpu)
    except (TypeError, ValueError) as exc:
        raise ValueError("Port, GPU and worker values must be integers or Auto.") from exc
    if not 1 <= parsed_port <= 65535:
        raise ValueError("Port must be between 1 and 65535.")
    if not 0 <= workers <= 256 or not 0 <= vision <= 256:
        raise ValueError("Worker counts must be between 0 (automatic) and 256.")
    if device is not None and device < 0:
        raise ValueError("GPU index cannot be negative.")
    if expert_cache != "auto":
        try:
            if not 1 <= int(expert_cache) <= 1000000:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Expert cache must be auto or a positive slot count (the default speculative engine needs cache).") from exc
    if prefill not in ("auto", "512", "1024", "2048", "4096", "8192"):
        raise ValueError("Invalid prefill chunk size.")
    return parsed_port, workers, vision, device


def apply_runtime(path: Path, *, host: str, port: str | int, api_key: str, gpu: str,
                  cpu_workers: str | int, vision_threads: str | int,
                  expert_cache: str, prefill: str, fit_max_tokens: bool) -> dict:
    config = read_json(path)
    if not valid_config(config):
        raise ValueError(f"Not a model configuration: {path}")
    p, workers, vision, device = validate_runtime(
        host, port, api_key, gpu, cpu_workers, vision_threads, expert_cache, prefill)
    args = config["args"]
    args = set_flag(args, "--pool-workers", None if workers == 0 else str(workers))
    args = set_flag(args, "--expert-cache", expert_cache)
    args = set_flag(args, "--prefill", prefill)
    config["args"] = args
    config["host"] = host
    config["port"] = p
    config["api_key"] = api_key.strip()
    config["fit_max_tokens"] = bool(fit_max_tokens)
    if device is None:
        config.pop("gpu", None)
    else:
        config["gpu"] = device
    if isinstance(config.get("vision"), dict):
        if vision:
            config["vision"]["threads"] = vision
        else:
            config["vision"].pop("threads", None)
    atomic_json(path, config)
    return config


def setup_command(python: Path, root: Path, *, family: str, model: str, context: int,
                  kv: str, vision: str, projection: str, data_dir: Path,
                  gpu: str, gguf_dir: str) -> list[str]:
    model_config_path(root, family, model)
    if context not in CONTEXTS or kv not in ("int8", "q4_0"):
        raise ValueError("Unsupported context or KV cache setting.")
    if vision not in ("none", "gpu", "cpu") or projection not in ("on", "off"):
        raise ValueError("Unsupported image/projection setting.")
    if family == "swift" and projection == "on":
        raise ValueError("The speed projection is not supported by Swift.")
    path = validate_data_root(root, data_dir)
    cmd = [str(python), "-u", str(root / "setup.py"), "--setup", "--yes", "--no-start",
           "--family", family, "--model", model, "--context", str(context),
           "--kv", kv, "--vision", vision, "--experimental-speed-projection", projection,
           "--data-dir", str(path)]
    if gpu != "Auto":
        if not gpu.isdigit():
            raise ValueError("GPU index must be Auto or a non-negative integer.")
        cmd += ["--gpu", gpu]
    if gguf_dir.strip():
        folder = Path(gguf_dir.strip()).expanduser().resolve()
        if not folder.is_dir():
            raise ValueError("Existing GGUF folder does not exist.")
        cmd += ["--gguf-dir", str(folder)]
    return cmd


def server_command(python: Path, root: Path, config_path: Path, config: dict,
                   mcp_path: str = "") -> list[str]:
    if not valid_config(config):
        raise ValueError("Invalid model configuration.")
    host = config.get("host", "127.0.0.1")
    port = config.get("port", 8080)
    validate_runtime(host, port, config.get("api_key", ""), str(config.get("gpu", "Auto")),
                     flag_value(config["args"], "--pool-workers", "0"),
                     config.get("vision", {}).get("threads", 0) if isinstance(config.get("vision"), dict) else 0,
                     flag_value(config["args"], "--expert-cache", "auto"),
                     flag_value(config["args"], "--prefill", "auto"))
    cmd = [str(python), "-u", str(root / "serve" / "server.py"),
           "--engine", "strata", "--config", str(config_path), "--port", str(port)]
    if mcp_path.strip():
        file = Path(mcp_path.strip()).expanduser().resolve()
        if not file.is_file() or not isinstance(read_json(file).get("mcpServers"), dict):
            raise ValueError("MCP config must be an existing JSON file with an mcpServers object.")
        cmd += ["--mcp-config", str(file)]
    return cmd


def local_url(config: dict) -> str:
    return f"http://127.0.0.1:{int(config.get('port', 8080))}"


def lan_addresses() -> list[str]:
    """Candidate LAN IPv4 addresses; does not transmit user data."""
    preferred = None
    addresses = set()
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("10.255.255.255", 1))
            preferred = sock.getsockname()[0]
    except OSError:
        pass
    try:
        addresses.update(item[4][0] for item in
                         socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET))
    except OSError:
        pass
    def allowed(ip):
        try:
            address = ipaddress.ip_address(ip)
            return (address.version == 4 and not address.is_loopback
                    and not address.is_link_local and not address.is_unspecified
                    and not address.is_multicast)
        except ValueError:
            return False
    result = [preferred] if preferred and allowed(preferred) else []
    return result + sorted(ip for ip in addresses if allowed(ip) and ip != preferred)


def lan_urls(config: dict, addresses: list[str] | None = None) -> list[str]:
    if config.get("host", "127.0.0.1") != "0.0.0.0":
        return []
    port = int(config.get("port", 8080))
    ips = lan_addresses() if addresses is None else addresses
    return [f"http://{ip}:{port}/v1" for ip in ips]
