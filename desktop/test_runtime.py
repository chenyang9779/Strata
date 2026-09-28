"""Fast runtime tests independent of tkinter, GPUs or external API servers."""
import json
import sys
import threading
import urllib.request
import unittest
from pathlib import Path
from urllib.error import HTTPError
from io import BytesIO
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runtime


def frame(payload):
    return ("data: " + json.dumps(payload, ensure_ascii=False) + "\n\n").encode("utf-8")


class SSETests(unittest.TestCase):
    def test_streamed_utf8_and_keepalive(self):
        payloads = [
            frame({"choices": [{"delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}),
            b": keep-alive\n\n",
            frame({"choices": [{"delta": {"reasoning_content": "Thinking"}, "finish_reason": None}]}),
            frame({"choices": [{"delta": {"content": "Hello 🌍"}, "finish_reason": None}]}),
            frame({"choices": [{"delta": {"content": "!"}, "finish_reason": "stop"}]}),
            b"data: [DONE]\n\n"]
        events = list(runtime.openai_sse(b"".join(payloads).splitlines(keepends=True)))
        self.assertEqual(events, [("reasoning", "Thinking"), ("content", "Hello 🌍"),
                                  ("content", "!"), ("finish", "stop")])

    def test_error_frame(self):
        with self.assertRaisesRegex(runtime.APIError, "engine died"):
            list(runtime.openai_sse([frame({"error": {"message": "engine died"}})]))

    def test_disconnection_does_not_claim_success(self):
        with self.assertRaisesRegex(runtime.APIError, "disconnected"):
            list(runtime.openai_sse([frame({"choices": [{"delta": {"content": "partial"},
                                                         "finish_reason": None}]})]))

    def test_malformed_event(self):
        with self.assertRaisesRegex(runtime.APIError, "malformed"):
            list(runtime.openai_sse([b"data: {broken}\n\n"]))

    def test_request_header_and_payload(self):
        request = runtime.chat_request("http://127.0.0.1:8080", "private-secret",
                                       "model", [{"role": "user", "content": "test"}])
        self.assertEqual(request.full_url, "http://127.0.0.1:8080/v1/chat/completions")
        self.assertTrue(json.loads(request.data)["stream"])
        self.assertEqual(request.get_header("Authorization"), "Bearer private-secret")
        with self.assertRaises(ValueError):
            runtime.chat_request("http://192.0.2.1:8080", "", "model", [])

    def test_loopback_http_stream_contract(self):
        class FakeStrata(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                assert self.path == "/v1/chat/completions"
                assert self.headers.get("Authorization") == "Bearer local-key"
                assert payload["stream"] is True
                assert payload["messages"][0]["content"] == "ping"
                data = b"".join([
                    frame({"choices": [{"delta": {"role": "assistant"}, "finish_reason": None}]}),
                    frame({"choices": [{"delta": {"content": "pong"}, "finish_reason": None}]}),
                    frame({"choices": [{"delta": {}, "finish_reason": "stop"}]}),
                    b"data: [DONE]\n\n",
                ])
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeStrata)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{server.server_address[1]}"
            request = runtime.chat_request(url, "local-key", "test-model",
                                           [{"role": "user", "content": "ping"}])
            with urllib.request.urlopen(request, timeout=5) as response:
                events = list(runtime.openai_sse(response))
            self.assertEqual(events, [("content", "pong"), ("finish", "stop")])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_error_message(self):
        e = HTTPError("http://127.0.0.1:8080", 400, "Bad Request", None,
                      BytesIO(b'{"error":{"message":"context too large"}}'))
        self.assertEqual(str(runtime.api_error(e)), "HTTP 400: context too large")

    def test_log_secrets_redacted(self):
        msg = "Authorization: Bearer testsecret and testsecret again"
        clean = runtime.redact(msg, ("testsecret",))
        self.assertNotIn("testsecret", clean)


class StateTests(unittest.TestCase):
    def test_process_transition_and_stale_event(self):
        s = runtime.RunState()
        generation = s.begin("server")
        self.assertEqual(s.state, "starting")
        with self.assertRaises(ValueError):
            s.begin("setup")
        self.assertFalse(s.ready(generation - 1))
        self.assertTrue(s.ready(generation))
        self.assertTrue(runtime.can_send_chat(s, Path("model.json"), False))
        self.assertFalse(runtime.can_send_chat(s, Path("model.json"), True))
        self.assertTrue(s.stopping())
        self.assertFalse(s.stopping())
        self.assertFalse(runtime.can_send_chat(s, Path("model.json"), False))
        self.assertTrue(s.finished(generation))
        generation2 = s.begin("setup")
        self.assertNotEqual(generation2, generation)
        self.assertFalse(s.finished(generation))
        self.assertEqual(s.state, "setup")
        self.assertTrue(s.finished(generation2))

    def test_summary_defaults(self):
        self.assertEqual(runtime.metrics_summary({})["state"], "unknown")
        self.assertEqual(runtime.metrics_summary({"live": {"queued": "N/A", "tok_s": "invalid"}})["queue"], 0)
        with self.assertRaises(runtime.APIError):
            runtime.metrics_summary([])
        result = runtime.metrics_summary({"engine": {"model": "test"}, "live":
                                          {"queued": 2, "tok_s": 32.5},
                                          "totals": {"requests": 4}})
        self.assertEqual((result["model"], result["queue"], result["tok_s"], result["requests"]),
                         ("test", 2, 32.5, 4))


if __name__ == "__main__":
    unittest.main()
