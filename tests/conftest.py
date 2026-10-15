"""Every test runs offline: the network layer is replaced with canned answers."""
from __future__ import annotations

import json
import pathlib

import pytest

from openroles import _http

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def web(monkeypatch):
    """Map URL substrings to answers: {substring: json or (None, "HTTP 404")}."""
    routes: dict = {}
    robots: dict = {}
    calls: list = []

    def request(url, payload=None, accept="application/json"):
        calls.append((url, payload))
        for key, answer in routes.items():
            if key in url:
                if callable(answer):
                    answer = answer(url, payload)
                return answer if isinstance(answer, tuple) else (answer, None)
        return None, "HTTP 404"

    def request_raw(url, payload=None, accept="*/*", limit=0):
        data, err = request(url, payload)
        return (data if isinstance(data, str) else json.dumps(data)), err

    monkeypatch.setattr(_http, "RETRY_PAUSE", 0)
    monkeypatch.setattr(_http, "request", request)
    monkeypatch.setattr(_http, "request_raw", request_raw)
    monkeypatch.setattr(_http, "robots_txt", lambda host: robots.get(host, (404, "")))
    return type("Web", (), {"routes": routes, "robots": robots, "calls": calls})
