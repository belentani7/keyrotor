"""Real loopback HTTP tests; zero provider credentials and no outbound requests."""
from __future__ import annotations

import http.client
import json
from http.server import ThreadingHTTPServer
from threading import Thread
from types import SimpleNamespace
from contextlib import contextmanager

from keyrotor.server import _make_handler


class StubRedactor:
    def clean(self, text):
        return text


class StubRouter:
    def __init__(self):
        self.requests = []
        self.redactor = StubRedactor()
        self.events = []

    def status(self):
        return {"providers": []}

    def chat(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return SimpleNamespace(
            ok=True, model="unit-test", content="response",
            provider="stub", cache_hit=False, attempts=1,
        )


@contextmanager
def serve_local():
    fake = StubRouter()
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(fake))
    runner = Thread(target=httpd.serve_forever, daemon=True)
    runner.start()
    try:
        yield fake, httpd.server_port
    finally:
        httpd.shutdown()
        runner.join(timeout=3)
        httpd.server_close()


def post(port, body):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    try:
        conn.request("POST", "/v1/chat/completions",
                     json.dumps(body).encode("utf-8"),
                     {"Content-Type": "application/json"})
        response = conn.getresponse()
        return response.status, json.loads(response.read())
    finally:
        conn.close()


def test_stream_true_returns_http_400_without_using_any_provider():
    with serve_local() as (router, port):
        status, response = post(port, {
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": True,
        })
        assert status == 400
        assert "streaming is not supported" in response["error"]["message"]
        assert router.requests == []


def test_invalid_input_never_reaches_provider():
    with serve_local() as (router, port):
        for request in [
            {"messages": [{"role": "admin", "content": "hi"}]},
            {"messages": [{"role": [], "content": "hi"}]},
            {"messages": [{"role": {}, "content": "hi"}]},
            {"messages": [{"role": "user", "content": []}]},
            {"messages": [{"role": "user", "content": "hi"}], "max_tokens": 100000},
            {"messages": [{"role": "user", "content": "hi"}], "temperature": 25},
            {"messages": [{"role": "user", "content": "hi"}], "temperature": 10 ** 400},
            {"messages": [{"role": "user", "content": "hi"}], "top_p": 10 ** 400},
        ]:
            status, response = post(port, request)
            assert status == 400, response
        assert router.requests == []


def test_normal_json_response_without_streaming():
    with serve_local() as (router, port):
        status, response = post(port, {
            "messages": [{"role": "user", "content": "Hola"}],
            "stream": False,
            "max_tokens": 64,
        })
        assert status == 200, response
        assert response["choices"][0]["message"]["content"] == "response"
        assert response["provider"] == "stub"
        assert len(router.requests) == 1
        assert router.requests[0][1]["max_tokens"] == 64
        assert "stream" not in router.requests[0][1]
