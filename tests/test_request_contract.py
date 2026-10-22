"""No real API tokens or provider networking in the request-contract suite."""
import copy

import pytest

from keyrotor.request_contract import validate_chat_request

VALID = {
    "messages": [{"role": "user", "content": "Hola, responde en español."}],
    "model": "auto",
    "max_tokens": 256,
    "temperature": 0.7,
    "top_p": 0.9,
    "stream": False,
}


def test_valid_plain_json_chat_request():
    assert validate_chat_request(VALID) is None


@pytest.mark.parametrize("bad", [
    {"messages": []},
    {"messages": "hi"},
    {"messages": [{}]},
    {"messages": [None]},
    {"messages": [{"role": "tool", "content": "secret"}]},
    {"messages": [{"role": "user", "content": ["image-data"]}]},
    {"messages": [{"role": "user", "content": ""}]},
    {"messages": [{"role": "user", "content": "x" * 8001}]},
    {"messages": [{"role": "user", "content": "x"}] * 65},
    {"model": {"not": "a-string"}},
    {"model": "x" * 151},
    {"stream": True},
    {"stream": "false"},
    {"max_tokens": 0},
    {"max_tokens": True},
    {"max_tokens": 100000000},
    {"temperature": float("nan")},
    {"top_p": float("inf")},
    {"top_p": -0.5},
    {"stop": ["x"] * 5},
    {"stop": 55},
])
def test_rejects_unsupported_modes_and_unbounded_inputs(bad):
    item = copy.deepcopy(VALID)
    item.update(bad)
    assert validate_chat_request(item) is not None


def test_never_mutates_user_payload():
    value = copy.deepcopy(VALID)
    assert validate_chat_request(value) is None
    assert value == VALID
