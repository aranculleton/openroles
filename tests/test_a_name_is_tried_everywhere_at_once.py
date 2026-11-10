"""A company name is tried on every system at once, and the boards come back in the same
order as before, whichever answered first."""
import threading

import openroles
from openroles import Board
from openroles.discover import GUESSED, guess
from openroles.providers import READERS


def test_every_system_is_asked_at_once(monkeypatch):
    together = threading.Barrier(len(GUESSED), timeout=10)
    for ats in GUESSED:
        def exists(token, ats=ats):
            together.wait()             # passes only when every system is being asked at once
            return ats in ("lever", "greenhouse")
        monkeypatch.setattr(READERS[ats], "exists", exists)
    assert guess("Acme") == [Board("greenhouse", "acme"), Board("lever", "acme")]


def test_one_system_failing_loses_none_of_the_others(monkeypatch, web):
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)

    def broken(token):
        raise RuntimeError("a reader's bug")
    monkeypatch.setattr(READERS["ashby"], "exists", broken)
    assert openroles.detect("Acme") == [Board("lever", "acme")]


def test_the_next_name_is_tried_only_when_the_first_finds_nothing(web):
    web.routes["api.lever.co/v0/postings/acme-data?"] = ([], None)
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)
    assert openroles.detect("Acme Data") == [Board("lever", "acme-data")]
    asked = [u for u, _ in web.calls if "postings/acme?" in u]
    assert asked == []
