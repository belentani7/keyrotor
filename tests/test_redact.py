"""Redactor / redact / find_secrets / mask_key unit tests.

All secret-shaped strings are assembled by concatenation so that the
repo secret scanner (scripts/secret_scan.py) never flags this file.
"""

from keyrotor.redact import Redactor, find_secrets, mask_key, redact


def test_redact_openai_style_key():
    key = "sk-" + "abcdefgh1234"
    out = redact("my key is " + key)
    assert "****" in out
    assert "abcdefgh1234" not in out


def test_redact_nvidia_key():
    key = "nvapi-" + "abcdefghijklmnopqrstuvwx"
    out = redact(key)
    assert "****" in out
    assert "abcdefghijklmnopqrstuvwx" not in out


def test_redact_openrouter_key():
    key = "sk-or-v1-" + "abcdef0123456789abcdef"
    out = redact(key)
    assert "****" in out
    assert "abcdef0123456789abcdef" not in out


def test_redact_google_oauth_token():
    token = "AQ." + "abcdefghijklmnopqrstuvwx"
    out = redact("creds " + token)
    assert "****" in out
    assert "abcdefghijklmnopqrstuvwx" not in out


def test_redact_jwt():
    jwt = (
        "eyJ" + "hbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" + "."
        + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "abcDEFghij1234"
    )
    out = redact("token: " + jwt)
    assert "****" in out
    assert "abcDEFghij1234" not in out


def test_redact_github_pat():
    pat = "github_pat_" + "ABCDEFGHIJKLMNOPQRST"
    out = redact("pat=" + pat)
    assert "****" in out
    assert "ABCDEFGHIJKLMNOPQRST" not in out


def test_find_secrets_returns_entries():
    text = "k1: sk-" + "abcdefgh1234" + " k2: nvapi-" + "abcdefghijklmnopqrstuvwx"
    found = find_secrets(text)
    kinds = [kind for kind, _masked in found]
    assert "openai-like" in kinds
    assert "nvidia" in kinds
    for _kind, masked in found:
        assert "****" in masked


def test_find_secrets_empty_on_clean_text():
    assert find_secrets("hola mundo, nada que ver") == []


def test_mask_key():
    assert mask_key("sk-" + "abcdefgh1234") == "sk-a...1234"


def test_mask_key_short_and_empty():
    assert mask_key("abc") == "****"
    assert mask_key("") == ""


def test_redactor_class():
    redactor = Redactor()
    assert redactor.mask("sk-" + "abcdefgh1234") == "sk-a...1234"
    cleaned = redactor.clean("secret nvapi-" + "abcdefghijklmnopqrstuvwx")
    assert "abcdefghijklmnopqrstuvwx" not in cleaned
