"""Stdlib-only HTTP server exposing the router as an OpenAI-compatible API.

Rule #2 of the project: BACKEND PROXY - the frontend never sees a key.
Everything the server echoes back to a client that did not originate in
this process (error text, model names, request bodies) is passed through
``router.redactor.clean`` before it can leave the machine.

No FastAPI: http.server.ThreadingHTTPServer only, so the server runs
anywhere Python >= 3.9 runs, with zero extra dependencies.

Endpoints
---------
GET  /                     -> dashboard (frontend/index.html)
GET  /health               -> {"ok": true, "version": ...}
GET  /api/status           -> router.status() (masked + redacted)
GET  /api/events           -> router.events (redacted)
POST /v1/chat/completions  -> OpenAI-compatible chat
"""

from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional, Tuple, Type

from keyrotor.providers import BUILTIN_PROVIDERS
from keyrotor.router import RotatingRouter
from keyrotor.secrets import load_keys, provider_order_from_env

VERSION = "1.0.0"

# Request fields forwarded from the OpenAI-shaped body to the providers.
_FORWARDABLE = ("temperature", "top_p", "max_tokens", "stream", "stop")

_INDEX_HTML_CANDIDATES = [
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 "frontend", "index.html"),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "frontend",
                 "index.html"),
]


def _find_index_html() -> Optional[str]:
    for candidate in _INDEX_HTML_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


def _make_handler(router: RotatingRouter) -> Type[BaseHTTPRequestHandler]:
    """Build a request handler bound to one router instance."""

    class Handler(BaseHTTPRequestHandler):
        server_version = "Keyrotor/" + VERSION

        # ------------------------------------------------- CORS / plumbing
        def _send_cors(self) -> None:
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, Authorization")

        def _send_json(self, payload: Any, status: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self._send_cors()
            self.end_headers()
            self.wfile.write(body)

        def _send_bytes(self, data: bytes, content_type: str,
                        status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self._send_cors()
            self.end_headers()
            self.wfile.write(data)

        def _read_json_body(self) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return None, "invalid Content-Length"
            if length <= 0 or length > 10 * 1024 * 1024:
                return None, "empty or oversized body"
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                return None, router.redactor.clean(f"invalid json: {exc}")
            if not isinstance(payload, dict):
                return None, "body must be a json object"
            return payload, None

        def log_message(self, fmt: str, *args: Any) -> None:
            # default handler prints to stderr; keep it silent except errors
            pass

        # ------------------------------------------------- OPTIONS
        def do_OPTIONS(self) -> None:  # noqa: N802
            self.send_response(204)
            self._send_cors()
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ------------------------------------------------- GET
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"

            if path == "/":
                index_path = _find_index_html()
                if index_path is None:
                    self._send_json(
                        {"error": "frontend/index.html not found"}, 404)
                    return
                with open(index_path, "rb") as fh:
                    self._send_bytes(fh.read(), "text/html; charset=utf-8")
                return

            if path == "/health":
                self._send_json({"ok": True, "version": VERSION})
                return

            if path == "/api/status":
                self._send_json(router.status())
                return

            if path == "/api/events":
                self._send_json({"events": router.events})
                return

            self._send_json({"error": "not found"}, 404)

        # ------------------------------------------------- POST
        def do_POST(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0].rstrip("/") or "/"

            if path != "/v1/chat/completions":
                self._send_json({"error": "not found"}, 404)
                return

            body, err = self._read_json_body()
            if body is None:
                self._send_json({"error": {"message": err or "bad request",
                                           "type": "invalid_request_error"}},
                                400)
                return

            messages = body.get("messages")
            if not isinstance(messages, list) or not messages:
                self._send_json({"error": {"message": "messages required",
                                           "type": "invalid_request_error"}},
                                400)
                return

            model = body.get("model")
            # "auto"/empty: let each provider use its own default model, so
            # cross-provider failover works with a single client model id.
            if not model or str(model).lower() in ("auto", "router", "keyrotor"):
                model = None
            request_kwargs = {k: body[k] for k in _FORWARDABLE if k in body}

            result = router.chat(messages, model=model, **request_kwargs)

            if not result.ok:
                # Anything echoed to the client is redacted first.
                self._send_json(
                    {"error": {
                        "message": router.redactor.clean(result.error),
                        "type": "router_error",
                    }},
                    502,
                )
                return

            safe_model = router.redactor.clean(result.model or "")
            self._send_json({
                "id": "chatcmpl-" + uuid.uuid4().hex,
                "object": "chat.completion",
                "created": int(__import__("time").time()),
                "model": safe_model,
                "provider": result.provider,
                "cache_hit": result.cache_hit,
                "attempts": result.attempts,
                "choices": [{
                    "index": 0,
                    "message": {"role": "assistant",
                                "content": result.content},
                    "finish_reason": "stop",
                }],
            })

    return Handler


class RotorServer:
    """Threading HTTP server with the router injected."""

    def __init__(self, router: RotatingRouter) -> None:
        self.router = router
        self.handler = _make_handler(router)

    def serve(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        httpd = ThreadingHTTPServer((host, port), self.handler)
        print(f"keyrotor v{VERSION} -> http://{host}:{port} "
              f"(dashboard: http://{host}:{port}/)")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nshutdown")
        finally:
            httpd.server_close()


def build_app(router: RotatingRouter) -> RotorServer:
    """Build the server around an existing router instance."""
    return RotorServer(router)


def run(host: str = "127.0.0.1", port: int = 8000,
        router: Optional[RotatingRouter] = None) -> None:
    """Create a router from env-only secrets and serve forever."""
    if router is None:
        default_order = list(BUILTIN_PROVIDERS.keys())
        router = RotatingRouter(
            providers=BUILTIN_PROVIDERS,
            keys=load_keys(),
            provider_order=provider_order_from_env(default_order),
        )
    RotorServer(router).serve(host, port)
