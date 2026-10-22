"""CLI, environment-only secrets and HTTP origin security regressions."""
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from keyrotor.__main__ import build_parser, build_router
from keyrotor.router import RotatingRouter
from keyrotor.secrets import load_keys, provider_order_from_env
from keyrotor.server import RotorServer, _make_handler


def test_keys_are_loaded_from_process_values_without_side_effects():
    env = {
        "OPENROUTER_API_KEYS": "alpha, beta,alpha, ",
        "OPENROUTER_API_KEY": "gamma",
        "GEMINI_API_KEY": "google-test",
        "NVIDIA_API_KEYS": "nvapi-EXAMPLE_VALUE",
    }
    before = dict(env)
    keys = load_keys(env)
    assert keys["openrouter"] == ["alpha", "beta", "gamma"]
    assert keys["google"] == ["google-test"]
    assert keys["nvidia"] == []
    assert env == before
    assert keys["mistral"] == []


def test_provider_order_rejects_unknown_names_and_duplicates():
    baseline = ["nvidia", "openrouter", "google"]
    assert provider_order_from_env(baseline, {}) == baseline
    env = {"KEYROTOR_PROVIDER_ORDER": "google, nonsense,google,nvidia"}
    assert provider_order_from_env(baseline, env) == ["google", "nvidia"]
    assert provider_order_from_env(baseline, {"KEYROTOR_PROVIDER_ORDER": "invalid"}) == baseline


def test_cli_and_server_modules_import_and_cli_parses(monkeypatch):
    for key in ("OPENROUTER_API_KEYS", "NVIDIA_API_KEYS", "GOOGLE_API_KEYS"):
        monkeypatch.delenv(key, raising=False)
    assert build_parser().parse_args(["status"]).command == "status"
    assert isinstance(build_router(), RotatingRouter)


@pytest.fixture()
def local_server():
    router = RotatingRouter(providers={}, keys={}, provider_order=[])
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(router))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)


def test_health_without_browser_origin(local_server):
    with urlopen(f"http://127.0.0.1:{local_server.server_port}/health", timeout=3) as res:
        assert json.load(res)["ok"] is True
        assert res.headers.get("Access-Control-Allow-Origin") is None


def test_same_origin_only_and_preflight_rejection(local_server):
    url = f"http://127.0.0.1:{local_server.server_port}/health"
    origin = f"http://127.0.0.1:{local_server.server_port}"
    with urlopen(Request(url, headers={"Origin": origin}), timeout=3) as res:
        assert res.status == 200
        assert res.headers["Access-Control-Allow-Origin"] == origin

    for method in ("GET", "OPTIONS"):
        req = Request(url, method=method, headers={
            "Origin": "https://attacker.example",
            "Access-Control-Request-Method": "POST",
        })
        with pytest.raises(HTTPError) as exc:
            urlopen(req, timeout=3)
        assert exc.value.code == 403
        assert exc.value.headers.get("Access-Control-Allow-Origin") is None


def test_remote_bind_requires_a_real_authenticated_gateway():
    router = RotatingRouter(providers={}, keys={}, provider_order=[])
    with pytest.raises(ValueError, match="Remote HTTP bind"):
        RotorServer(router).serve(host="0.0.0.0", port=0)


def test_rebinding_host_is_rejected_even_without_origin(local_server):
    url = f"http://127.0.0.1:{local_server.server_port}/api/status"
    request = Request(url, headers={
        "Host": f"attacker.example:{local_server.server_port}",
    })
    with pytest.raises(HTTPError) as exc:
        urlopen(request, timeout=3)
    assert exc.value.code == 403
    assert exc.value.headers.get("Access-Control-Allow-Origin") is None


def test_completion_output_does_not_echo_provider_secrets():
    from keyrotor.router import RouterResult

    secret = "sk-or-v1-" + "a" * 24
    router = RotatingRouter(providers={}, keys={}, provider_order=[])

    def fake_chat(messages, **kwargs):
        return RouterResult(ok=True, provider="test", model="test-model",
                            content="secret marker: " + secret)

    router.chat = fake_chat
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(router))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/v1/chat/completions"
        request = Request(
            url,
            data=json.dumps({"messages": [{"role": "user", "content": "hi"}]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            result = json.load(response)
        content = result["choices"][0]["message"]["content"]
        assert secret not in content
        assert "****" in content
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=3)
