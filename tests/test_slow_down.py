"""A host that asks to be sent less is sent nothing for the pause it asked for, from every
board read from it, and a host's documented rate limit holds across boards. Every answer
comes from a fake `_urlopen`; nothing touches the network."""
import email.utils
import io
import json
import urllib.error

import pytest

from openroles import _http
from openroles.models import failed
from openroles.providers import rippling, workday

ROBOTS_TXT = _http.robots_txt


class Answer(io.BytesIO):
    def __init__(self, body: bytes):
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Host:
    """Answers by URL piece: a dict or list is sent as JSON, an int is that status with
    `retry_after` as its Retry-After. Every URL asked for is in `sent`."""

    def __init__(self, monkeypatch, routes, retry_after=None):
        self.routes, self.retry_after, self.sent = routes, retry_after, []
        monkeypatch.setattr(_http, "_urlopen", self.urlopen)

    def urlopen(self, req, timeout=0):
        self.sent.append(req.full_url)
        for key, answer in self.routes.items():
            if key in req.full_url:
                if isinstance(answer, int):
                    headers = {"Retry-After": self.retry_after} if self.retry_after else {}
                    raise urllib.error.HTTPError(req.full_url, answer, "slow down", headers, None)
                return Answer(json.dumps(answer).encode())
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    now = {"t": 1000.0}
    monkeypatch.setattr(_http.time, "monotonic", lambda: now["t"])
    monkeypatch.setattr(_http.time, "sleep", lambda s: None)
    monkeypatch.setattr(_http, "_QUIET", {})
    monkeypatch.setattr(_http, "_SENT", {})
    monkeypatch.setattr(_http, "_DELAYS", {})
    monkeypatch.setattr(_http, "_ETAGS", _http.OrderedDict())
    monkeypatch.setattr(_http, "CACHE_DIR", "")
    monkeypatch.setattr(_http, "RETRY_PAUSE", 0)
    monkeypatch.setattr(_http, "robots_txt", lambda host: (404, ""))
    return now


def test_a_429_holds_the_host_for_the_pause_its_retry_after_names(monkeypatch, clock):
    host = Host(monkeypatch, {"/busy": 429}, retry_after="120")
    assert _http.request("https://api.example/busy") == (None, "HTTP 429")
    host.routes["/busy"] = {"ok": True}
    data, err = _http.request("https://api.example/other")
    assert data is None and err == "not sent: api.example answered HTTP 429 and asked to slow down"
    assert len(host.sent) == 1                      # the second was never sent
    clock["t"] += 121
    assert _http.request("https://api.example/busy") == ({"ok": True}, None)
    assert len(host.sent) == 2


def test_a_503_with_no_retry_after_holds_the_host_for_the_default_pause(monkeypatch, clock):
    host = Host(monkeypatch, {"/down": 503})
    assert _http.request("https://api.example/down") == (None, "HTTP 503")
    clock["t"] += _http.BACKOFF - 1
    assert _http.request("https://api.example/down")[1].startswith("not sent: ")
    clock["t"] += 2
    assert _http.request("https://api.example/down") == (None, "HTTP 503")
    assert len(host.sent) == 2
    assert _http.request("https://other.example/down") == (None, "HTTP 503")   # another host is asked


def test_a_retry_after_date_is_read_and_a_long_one_is_capped(monkeypatch, clock):
    monkeypatch.setattr(_http, "_now", lambda: 1_800_000_000.0)
    when = email.utils.formatdate(1_800_000_000.0 + 300, usegmt=True)
    Host(monkeypatch, {"/busy": 429}, retry_after=when)
    _http.request("https://api.example/busy")
    assert _http._QUIET["api.example"][0] == pytest.approx(clock["t"] + 300)
    assert _http._retry_after("soon") is None and _http._retry_after("") is None
    Host(monkeypatch, {"/busy": 429}, retry_after="999999")
    _http.request("https://far.example/busy")
    assert _http._QUIET["far.example"][0] == clock["t"] + _http.BACKOFF_MAX


def test_a_rippling_board_stops_asking_for_postings_once_told_to_slow_down(monkeypatch):
    items = [{"id": f"0000000{i}-0000-0000-0000-000000000000", "name": f"Analyst {i}",
              "url": f"https://ats.rippling.com/acme/jobs/{i}", "locations": []} for i in range(5)]
    host = Host(monkeypatch, {"/jobs?page=0": {"items": items, "totalPages": 1},
                              "/jobs/00000000": {"description": {"role": "<p>Role</p>"}},
                              "/jobs/0000000": 429})
    report: dict = {}
    jobs = rippling.fetch("acme", details=True, report=report)
    assert len(jobs) == 5
    asked = [u for u in host.sent if "/jobs/" in u]
    assert len(asked) == 2                          # the first answered, the second said 429
    assert jobs[0].description == "Role"
    errors = report["detail_errors"]
    assert list(errors.values()).count("HTTP 429") == 1
    assert all(e.startswith("not sent: api.rippling.com") for e in list(errors.values())[1:])


def test_a_documented_rate_limit_holds_across_boards(monkeypatch, clock):
    monkeypatch.setitem(_http.LIMITS, "limited.example", (3, 60))
    host = Host(monkeypatch, {"/board": {"jobs": []}})
    for name in ("a", "b"):
        assert _http.request(f"https://limited.example/board/{name}") == ({"jobs": []}, None)
    data, err = _http.request("https://limited.example/board/c")       # 90% of 3 is 2
    assert err == "not sent: limited.example takes 3 requests in 1 minutes, and that many were sent"
    assert len(host.sent) == 2
    clock["t"] += 60
    assert _http.request("https://limited.example/board/c") == ({"jobs": []}, None)
    assert rippling.HOST in _http.LIMITS


def test_robots_txt_that_says_slow_down_holds_the_host_and_is_not_kept(monkeypatch, clock):
    monkeypatch.setattr(_http, "robots_txt", ROBOTS_TXT)
    monkeypatch.setattr(_http, "_ROBOTS", {})
    asked = []

    def urlopen(req, timeout=0):
        asked.append(req.full_url)
        raise urllib.error.HTTPError(req.full_url, 429, "slow down", {"Retry-After": "30"}, None)
    monkeypatch.setattr(_http.urllib.request, "urlopen", urlopen)
    assert _http.robots_txt("busy.example") == (429, "")
    assert _http.robots_allows("busy.example", ["/jobs"])[0] is False     # held off: not asked
    assert len(asked) == 1
    clock["t"] += 31
    assert _http.robots_txt("busy.example") == (429, "")                  # asked again
    assert len(asked) == 2


def test_a_workday_board_stops_once_its_host_is_held_off(monkeypatch):
    monkeypatch.setattr(_http, "_QUIET", {"acme.wd3.myworkdayjobs.com": (10 ** 9, 429)})
    board = workday.WorkdayBoard("acme.wd3/External")
    data, err = board.call(f"{board.api}/jobs", {})
    assert data is None and err.startswith("not sent: ") and board.halt.is_set()


def test_the_reason_a_board_failed_says_it_was_not_sent():
    why = failed("not sent: api.example answered HTTP 429 and asked to slow down", "board name")
    assert why == "not sent: api.example answered HTTP 429 and asked to slow down; try again later"
    assert "probably a wrong" not in why
    assert failed("HTTP 429", "board name").startswith("the board asked to slow down")
