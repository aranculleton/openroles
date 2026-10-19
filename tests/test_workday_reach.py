"""Workday: how much of a board a read reaches, and how few requests it spends."""
import datetime as dt
import logging

import pytest

import openroles
from openroles import BoardError
from openroles.providers import workday

from .conftest import fixture

TODAY = dt.date(2026, 10, 15)


def _pages(total=2000, last=None, title="Pricing Analyst"):
    """A listing that reports its total on the first page only, as Workday does."""
    def answer(url, payload):
        offset = payload["offset"]
        if last is not None and offset > last:
            return {"total": 0, "jobPostings": []}, None
        posts = [{"title": f"{title} {offset + i}", "locationsText": "Leeds",
                  "externalPath": f"/job/Leeds/{title.replace(' ', '-')}_R{offset + i}"}
                 for i in range(workday.PAGE)]
        return {"total": total if offset == 0 else 0, "jobPostings": posts,
                "facets": []}, None
    return answer


def _searches(web):
    return [p["offset"] for _, p in web.calls if p and p.get("searchText")]


def test_a_search_reads_on_while_its_titles_keep_matching(web):
    web.routes["/wday/cxs/acme/External/jobs"] = _pages()
    jobs = workday.fetch("acme.wd3/External", query="pricing analyst", today=TODAY)
    assert _searches(web) == [0, 20, 40, 60, 80]
    assert len(jobs) == workday.SEARCH_PAGES * workday.PAGE


def test_a_search_stops_at_an_empty_page_and_at_the_total(web):
    web.routes["/wday/cxs/acme/External/jobs"] = _pages(last=40)
    workday.fetch("acme.wd3/External", query="pricing analyst", today=TODAY)
    assert _searches(web) == [0, 20, 40, 60]
    web.calls.clear()
    web.routes["/wday/cxs/acme/External/jobs"] = _pages(total=30)
    workday.fetch("acme.wd3/External", query="pricing analyst", today=TODAY)
    assert _searches(web) == [0, 20]


def _facets(*facets):
    data = fixture("workday_list.json")
    data["facets"] = list(facets)
    return data


def test_a_country_is_found_under_any_facet_and_any_of_its_names():
    hierarchy = {"facetParameter": "locationMainGroup", "values": [
        {"facetParameter": "locationHierarchy1", "descriptor": "Locations", "values": [
            {"descriptor": "United States of America", "id": "us-id", "count": 9},
            {"descriptor": "Canada", "id": "ca-id", "count": 4}]}]}
    find = workday.WorkdayBoard.country_facet
    assert find([hierarchy], "Canada") == ({"locationHierarchy1": ["ca-id"]}, 4)
    assert find([hierarchy], "United States") == ({"locationHierarchy1": ["us-id"]}, 9)
    assert find([hierarchy], "USA")[0] == {"locationHierarchy1": ["us-id"]}
    # A facet named for countries wins over a hierarchy that also holds them.
    named = {"facetParameter": "Country", "values": [{"descriptor": "Canada", "id": "c2", "count": 3}]}
    assert find([hierarchy, named], "canada")[0] == {"Country": ["c2"]}
    assert find([hierarchy], "Narnia") == ({}, None)
    assert find([hierarchy], "") == ({}, None)


def test_a_country_the_board_does_not_list_is_empty_but_a_board_with_no_facets_is_read(web, caplog):
    web.routes["/wday/cxs/acme/External/jobs"] = _facets(
        {"facetParameter": "locationCountry", "values": [{"descriptor": "France", "id": "f", "count": 1}]})
    assert workday.fetch("acme.wd3/External", country="Canada", today=TODAY) == []
    web.routes["/wday/cxs/acme/External/jobs"] = _facets()
    with caplog.at_level(logging.WARNING, logger="openroles"):
        jobs = workday.fetch("acme.wd3/External", country="Canada", today=TODAY)
    assert len(jobs) == 2 and "could not be applied" in caplog.text


def test_a_posting_in_several_places_reads_as_its_primary_and_the_rest_are_fetched_when_asked(web):
    listing = fixture("workday_list.json")
    listing["jobPostings"][1]["locationsText"] = "3 Locations"
    web.routes["/wday/cxs/acme/External/jobs"] = listing
    web.routes["/wday/cxs/acme/External/job/"] = fixture("workday_job.json")
    jobs = workday.fetch("acme.wd3/External", today=TODAY)
    analyst = jobs[1]
    assert analyst.location == "Leeds and 2 more" and analyst.locations == ["Leeds"]
    assert not [u for u, p in web.calls if "/job/" in u]
    # Filtering on a place that is not its primary reads its page, and only its page.
    web.calls.clear()
    jobs = workday.fetch("acme.wd3/External", today=TODAY, where="Remote")
    assert [u for u, p in web.calls if "/job/" in u] == [
        "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/External/job/Leeds/Logistics-Analyst_R2"]
    assert jobs[1].locations == ["Leeds", "Remote, United Kingdom"]
    web.calls.clear()
    workday.fetch("acme.wd3/External", today=TODAY, where="Leeds")
    assert not [u for u, p in web.calls if "/job/" in u]


def test_a_board_past_what_workday_pages_says_so(web, caplog):
    web.routes["/wday/cxs/acme/External/jobs"] = _pages(total=5000, last=0)
    with caplog.at_level(logging.WARNING, logger="openroles"):
        workday.fetch("acme.wd3/External", today=TODAY)
    assert "5000 postings" in caplog.text and "pass a query" in caplog.text


def test_pages_are_read_only_for_postings_the_title_filter_keeps(web):
    listing = fixture("workday_list.json")
    web.routes["/wday/cxs/acme/External/jobs"] = listing
    web.routes["/wday/cxs/acme/External/job/"] = fixture("workday_job.json")
    jobs = openroles.fetch("workday:acme.wd3/External", query="logistics")
    assert [j.title for j in jobs] == ["Logistics Analyst"]
    assert [u.rsplit("/", 1)[-1] for u, _ in web.calls if "/job/" in u] == ["Logistics-Analyst_R2"]


def test_a_limit_spends_no_request_past_it(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    web.routes["/wday/cxs/acme/External/job/"] = fixture("workday_job.json")
    jobs = workday.fetch("acme.wd3/External", details=True, limit=1, today=TODAY)
    assert len(jobs) == 1 and len([u for u, _ in web.calls if "/job/" in u]) == 1


def test_one_failing_board_of_several_does_not_lose_the_others(web, monkeypatch, caplog):
    from openroles import Board, discover
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    monkeypatch.setattr(discover, "detect", lambda target: [Board("lever", "acme"),
                                                             Board("greenhouse", "acme")])
    with caplog.at_level(logging.WARNING, logger="openroles"):
        jobs = openroles.fetch("Acme")
    assert {j.ats for j in jobs} == {"greenhouse"} and "1 of 2 boards" in caplog.text
    monkeypatch.setattr(discover, "detect", lambda target: [Board("lever", "acme"),
                                                             Board("lever", "acme2")])
    with pytest.raises(BoardError):
        openroles.fetch("Acme")
