"""What openroles asks of a host: its robots.txt, its Crawl-delay, and fewer bytes."""
import gzip
import io

import pytest

from openroles import RobotsDisallowed, _http
from openroles.providers import greenhouse, lever
from openroles.robots import crawl_delay

from .conftest import fixture


def test_crawl_delay_is_read_for_our_group_or_everyone():
    assert crawl_delay("User-agent: *\nAllow: /\nCrawl-delay: 1\n", "openroles") == 1.0
    text = "User-agent: *\nCrawl-delay: 5\n\nUser-agent: openroles\nCrawl-delay: 2\n"
    assert crawl_delay(text, "openroles") == 2.0 and crawl_delay(text, "other") == 5.0
    assert crawl_delay("User-agent: *\nDisallow:\n", "openroles") == 0.0
    assert crawl_delay("User-agent: *\nCrawl-delay: soon\n", "openroles") == 0.0


def test_requests_to_a_host_with_a_crawl_delay_are_spaced(monkeypatch):
    clock = {"now": 100.0}
    slept = []
    monkeypatch.setattr(_http.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(_http.time, "sleep", lambda s: slept.append(round(s, 3)))
    monkeypatch.setitem(_http._DELAYS, "slow.example", 1.0)
    monkeypatch.setattr(_http, "_NEXT", {})
    for _ in range(3):
        _http._wait_turn("slow.example")
    assert slept == [1.0, 2.0]
    _http._wait_turn("fast.example")
    assert slept == [1.0, 2.0]


def test_robots_is_read_again_after_a_day(monkeypatch):
    clock = {"now": 0.0}
    fetched = []

    class Answer(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        fetched.append(req.full_url)
        return Answer(b"User-agent: *\nCrawl-delay: 1\n")
    monkeypatch.setattr(_http.time, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(_http.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(_http, "_ROBOTS", {})
    monkeypatch.setattr(_http, "_DELAYS", {})
    _http.robots_txt("daily.example")
    clock["now"] = 3600.0
    _http.robots_txt("daily.example")
    assert len(fetched) == 1 and _http._DELAYS["daily.example"] == 1.0
    clock["now"] = _http.ROBOTS_TTL + 1
    _http.robots_txt("daily.example")
    assert len(fetched) == 2


def test_a_gzipped_body_is_unzipped():
    class Response(io.BytesIO):
        headers = {"Content-Encoding": "gzip"}
    body = '{"jobs": []}'
    assert _http._body(Response(gzip.compress(body.encode())), 1_000_000) == body


def test_a_documented_api_stops_only_at_an_explicit_disallow(web):
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    web.robots["boards-api.greenhouse.io"] = (403, "")          # unreadable: not a refusal
    assert len(greenhouse.fetch("acme")) == 2
    web.robots["boards-api.greenhouse.io"] = (200, "User-agent: *\nDisallow: /v1/boards/\n")
    with pytest.raises(RobotsDisallowed):
        greenhouse.fetch("acme")
    assert greenhouse.exists("acme") is False


def test_lever_skips_a_region_whose_robots_refuses_it(web):
    web.routes["api.lever.co/v0/postings/acme"] = fixture("lever.json")
    web.robots["api.eu.lever.co"] = (200, "User-agent: *\nDisallow: /\n")
    assert len(lever.fetch("acme")) == 1
    web.robots["api.lever.co"] = (200, "User-agent: *\nDisallow: /\n")
    with pytest.raises(RobotsDisallowed):
        lever.fetch("acme")
    assert lever.exists("acme") is False


def test_greenhouse_reads_every_office_a_posting_lists(web):
    data = fixture("greenhouse.json")
    data["jobs"][1]["location"] = {"name": "Hybrid"}
    data["jobs"][1]["offices"] = [{"id": 1, "name": "North", "location": "Leeds, United Kingdom"},
                                  {"id": 2, "name": "Head office"}]
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = data
    job = greenhouse.fetch("acme")[1]
    assert job.location == "Hybrid"
    assert job.locations == ["Hybrid", "Leeds, United Kingdom", "Head office"]
    import openroles
    assert [j.id for j in openroles.fetch("greenhouse:acme", location="leeds")] == ["gh-102"]
