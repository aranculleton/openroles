"""What a caller that runs searches on a schedule needs from the reader: what failed,
the day a run is dated from, large Workday boards searched, and a hybrid called hybrid."""
import datetime as dt
import io
import urllib.error

import openroles
from openroles import _http
from openroles.models import workplace_of
from openroles.providers import workday

from .conftest import fixture

TODAY = dt.date(2026, 10, 15)


def test_a_report_says_which_workday_pages_failed(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    web.routes["/wday/cxs/acme/External/job/"] = (None, "HTTP 500")
    report: dict = {}
    jobs = workday.fetch("acme.wd3/External", details=True, today=TODAY, report=report)
    assert len(jobs) == 2 and report["details_asked"] == 2
    assert set(report["detail_errors"]) == {j.id for j in jobs}
    assert report["listing_errors"] == []
    # The top-level fetch files each board's report under the board.
    whole: dict = {}
    openroles.fetch("workday:acme.wd3/External", details=True, report=whole, today=TODAY)
    assert whole["workday:acme.wd3/External"]["details_asked"] == 2


def test_a_board_that_cannot_be_read_is_in_the_report(web, monkeypatch):
    from openroles import Board, discover
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    monkeypatch.setattr(discover, "detect", lambda target: [Board("lever", "acme"),
                                                             Board("greenhouse", "acme")])
    report: dict = {}
    openroles.fetch("Acme", report=report)
    assert "error" in report["lever:acme"] and report["greenhouse:acme"] == {}


def test_the_day_a_run_is_dated_from_is_the_callers(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    jobs = openroles.fetch("workday:acme.wd3/External", details=False, today=dt.date(2026, 1, 10))
    assert {j.posted for j in jobs} >= {"2026-01-07"}        # "Posted 3 Days Ago"


def test_workdays_own_country_id_narrows_the_board(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    workday.fetch("acme.wd3/External", country_id="uk-id", today=TODAY)
    assert any(p and p["appliedFacets"] == {"locationCountry": ["uk-id"]} for _, p in web.calls)


def test_a_large_board_is_searched_with_the_callers_terms(web):
    def listing(url, payload):
        data = fixture("workday_list.json")
        data["total"] = 1500
        return data, None
    web.routes["/wday/cxs/acme/External/jobs"] = listing
    workday.fetch("acme.wd3/External", large_queries=["demand planner"], today=TODAY)
    assert [p["searchText"] for _, p in web.calls if p and p["searchText"]] == ["demand planner"]
    web.calls.clear()
    workday.fetch("acme.wd3/External", today=TODAY)                  # no terms: paged
    assert not [p for _, p in web.calls if p and p["searchText"]]


def test_a_multi_location_posting_can_be_told_apart():
    board = workday.WorkdayBoard("acme.wd3/External")
    many = board.job({"title": "Analyst", "locationsText": "3 Locations",
                      "externalPath": "/job/Leeds/Analyst_R1"}, TODAY)
    one = board.job({"title": "Analyst", "locationsText": "Leeds",
                     "externalPath": "/job/Leeds/Analyst_R2"}, TODAY)
    assert workday.more_places(many) and not workday.more_places(one)


def test_hybrid_is_called_hybrid_whatever_the_board_writes(web):
    assert [workplace_of(x) for x in ("on-site", "OnSite", "Hybrid", "Flexible", "Remote",
                                      "unspecified", "")] == [
        "onsite", "onsite", "hybrid", "hybrid", "remote", "", ""]
    web.routes["api.lever.co/v0/postings/acme"] = fixture("lever.json")
    from openroles.providers import lever
    assert lever.fetch("acme")[0].workplace == "remote"


def test_a_board_read_twice_costs_the_host_a_304(monkeypatch):
    sent = []

    class Answer(io.BytesIO):
        def __init__(self, body, etag):
            super().__init__(body)
            self.headers = {"ETag": etag}

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout=0):
        sent.append(req.get_header("If-none-match"))
        if req.get_header("If-none-match") == '"v1"':
            raise urllib.error.HTTPError(req.full_url, 304, "Not Modified", {}, None)
        return Answer(b'{"jobs": [1]}', '"v1"')
    monkeypatch.setattr(_http, "_urlopen", urlopen)
    monkeypatch.setattr(_http, "_ETAGS", type(_http._ETAGS)())
    monkeypatch.setattr(_http, "_DELAYS", {})
    url = "https://boards.example/v1/acme"
    assert _http.request(url) == ({"jobs": [1]}, None)
    assert _http.request(url) == ({"jobs": [1]}, None)
    assert sent == [None, '"v1"']
    # A POST is never answered from the cache.
    assert _http.request(url, payload={"q": 1}) == ({"jobs": [1]}, None)


def test_a_country_the_board_does_not_list_can_still_read_the_whole_board(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    assert workday.fetch("acme.wd3/External", country="Canada", today=TODAY) == []
    loose = workday.fetch("acme.wd3/External", country="Canada", today=TODAY, strict_country=False)
    assert len(loose) == 2
