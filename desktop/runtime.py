"""Runtime helpers for the Windows manager, kept separate from Tk for testability."""
from __future__ import annotations

import json
import re
import threading
import urllib.error
import urllib.request
from collections.abc import Iterable, Iterator


class APIError(Exception):
    """An API, protocol or transport error safe to show in the GUI."""


def redact(text: str, secrets: Iterable[str] = ()) -> str:
    """Do not accidentally show the configured API token in Activity or dialogs."""
    value = str(text)
    for secret in secrets:
        if secret:
            value = value.replace(secret, "[redacted]")
    value = re.sub(r"(?i)(authorization:\s*bearer\s+)\S+", r"\1[redacted]", value)
    return value


def api_error(error: Exception) -> APIError:
    if isinstance(error, urllib.error.HTTPError):
        detail = ""
        try:
            body = error.read(4096).decode("utf-8", "replace")
            payload = json.loads(body)
            if isinstance(payload, dict):
                obj = payload.get("error") or payload
                if isinstance(obj, dict):
                    detail = str(obj.get("message") or "")
        except (ValueError, OSError, UnicodeError):
            pass
        return APIError(f"HTTP {error.code}: {detail or error.reason}")
    if isinstance(error, urllib.error.URLError):
        return APIError(f"Connection failed: {error.reason}")
    return APIError(str(error))


def openai_sse(lines: Iterable[bytes | str]) -> Iterator[tuple[str, str]]:
    """Parse OpenAI streaming events, including UTF-8, comments and server-side errors.

    Emits content/reasoning/finish tuples. Completion is signalled only by [DONE],
    so abruptly disconnected streams are reported as failures.
    """
    fields: list[str] = []
    completed = False

    def decode_frame(data: list[str]) -> Iterator[tuple[str, str]]:
        nonlocal completed
        if not data:
            return
        payload = "\n".join(data)
        if payload == "[DONE]":
            completed = True
            return
        try:
            event = json.loads(payload)
        except (ValueError, TypeError) as exc:
            raise APIError("The server returned malformed stream data.") from exc
        if not isinstance(event, dict):
            raise APIError("The server returned an unexpected stream event.")
        if "error" in event:
            error = event["error"]
            message = error.get("message", str(error)) if isinstance(error, dict) else str(error)
            raise APIError(message)
        try:
            choice = event["choices"][0]
            delta = choice.get("delta") or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise APIError("The server returned an unexpected response shape.") from exc
        for name, key in (("reasoning", "reasoning_content"), ("content", "content")):
            value = delta.get(key)
            if value:
                if not isinstance(value, str):
                    raise APIError("The server returned a non-text chat delta.")
                yield name, value
        if choice.get("finish_reason"):
            yield "finish", str(choice["finish_reason"])

    for raw in lines:
        if isinstance(raw, bytes):
            try:
                line = raw.decode("utf-8")
            except UnicodeError as exc:
                raise APIError("The server returned invalid UTF-8.") from exc
        else:
            line = raw
        line = line.rstrip("\r\n")
        if not line:
            yield from decode_frame(fields)
            fields.clear()
            if completed:
                return
            continue
        if line.startswith(":"):
            continue
        if line.startswith("data:"):
            fields.append(line[5:].lstrip(" "))
    if fields:
        yield from decode_frame(fields)
    if not completed:
        raise APIError("The server disconnected before finishing its response.")


def chat_request(url: str, api_key: str, model: str, messages: list[dict],
                 max_tokens: int = 2048) -> urllib.request.Request:
    if not url.startswith("http://127.0.0.1:"):
        raise ValueError("Desktop requests must target Strata's local loopback server.")
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True}
    headers = {"Accept": "text/event-stream", "Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key
    return urllib.request.Request(url + "/v1/chat/completions",
                                  data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                  headers=headers, method="POST")


def metrics_summary(result: dict) -> dict:
    """Keep the monitor stable across older/newer server field sets."""
    live = result.get("live") or {}
    totals = result.get("totals") or {}
    engine = result.get("engine") or {}
    hardware = result.get("hardware") or {}
    return {
        "model": str(engine.get("model") or "Unknown"),
        "state": str(live.get("state") or "unknown"),
        "queue": int(live.get("queued") or 0),
        "tok_s": float(live.get("tok_s") or 0.0),
        "prompt": int(live.get("prompt_tokens") or 0),
        "generated": int(live.get("generated") or 0),
        "requests": int(totals.get("requests") or 0),
        "output_tokens": int(totals.get("output_tokens") or 0),
        "max_context": engine.get("max_context"),
        "hardware": hardware,
    }


class RunState:
    """Small tested state machine for process lifecycle; Tk callbacks remain on its main thread."""
    IDLE, SETUP, CALIBRATION, STARTING, RUNNING, STOPPING = (
        "idle", "setup", "calibration", "starting", "running", "stopping")

    def __init__(self):
        self.state = self.IDLE
        self.generation = 0

    @property
    def busy(self) -> bool:
        return self.state != self.IDLE

    @property
    def server(self) -> bool:
        return self.state in (self.STARTING, self.RUNNING, self.STOPPING)

    def begin(self, kind: str) -> int:
        if self.busy or kind not in ("setup", "calibration", "server"):
            raise ValueError("Finish or stop the current operation first.")
        self.generation += 1
        self.state = self.STARTING if kind == "server" else kind
        return self.generation

    def ready(self, generation: int) -> bool:
        if generation == self.generation and self.state == self.STARTING:
            self.state = self.RUNNING
            return True
        return False

    def stopping(self) -> bool:
        if self.busy and self.state != self.STOPPING:
            self.state = self.STOPPING
            return True
        return False

    def finished(self, generation: int) -> bool:
        if generation != self.generation:
            return False
        self.state = self.IDLE
        return True


def can_send_chat(state: RunState, active_path, chat_busy: bool) -> bool:
    return state.state == RunState.RUNNING and active_path is not None and not chat_busy
