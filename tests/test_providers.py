import datetime as dt

import pytest

import openroles
from openroles import Board, BoardError, RobotsDisallowed
from openroles.providers import ashby, greenhouse, lever, workday

from .conftest import fixture

TODAY = dt.date(2026, 10, 15)


def test_greenhouse_one_shape_and_unescaped_text(web):
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    jobs = greenhouse.fetch("acme")
    first = jobs[0]
    assert first.id == "gh-101" and first.ats == "greenhouse" and first.board == "acme"
    assert first.posted == "2026-09-01"          # first published, not last edited
    assert first.department == "Analytics"
    assert first.description.startswith("Build & ship models.") and "<" not in first.description
    assert jobs[1].remote is True and jobs[1].posted == "2026-10-10"


def test_lever_reads_the_requirements_not_just_the_intro(web):
    web.routes["api.lever.co/v0/postings/acme"] = fixture("lever.json")
    job = lever.fetch("acme")[0]
    assert "Python" in job.description and "Equal opportunity" in job.description
    assert job.locations == ["Manchester", "Leeds"] and job.remote is True
    assert job.compensation == "GBP 50,000-65,000 per year salary"
    assert job.posted == "2025-10-09"


def test_lever_tries_the_eu_region_before_giving_up(web):
    web.routes["api.lever.co/"] = ({"ok": False}, None)
    web.routes["api.eu.lever.co/v0/postings/acme"] = fixture("lever.json")
    assert len(lever.fetch("acme")) == 1


def test_lever_unknown_board_is_an_error_not_an_empty_board(web):
    web.routes["lever.co"] = ({"ok": False, "error": "Document not found"}, None)
    with pytest.raises(BoardError):
        lever.fetch("nobody")


def test_ashby_uses_the_address_and_skips_unlisted_roles(web):
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = fixture("ashby.json")
    jobs = ashby.fetch("acme")
    assert len(jobs) == 1
    job = jobs[0]
    assert job.locations == ["Remote, United Kingdom", "Leeds, United Kingdom"]
    assert job.remote is True and job.compensation == "£60K - £75K"


def test_ashby_respects_robots(web):
    web.robots["api.ashbyhq.com"] = (200, "User-agent: *\nDisallow: /posting-api/\n")
    with pytest.raises(RobotsDisallowed):
        ashby.fetch("acme")


def test_workday_listing_details_and_safety(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    web.routes["/wday/cxs/acme/External/job/"] = fixture("workday_job.json")
    jobs = workday.fetch("acme.wd3/External", details=lambda j: "more" in j.location,
                         today=TODAY)
    assert [j.title for j in jobs] == ["Demand Planner", "Logistics Analyst"]  # the bad path is refused
    planner, analyst = jobs
    assert planner.posted == "2026-10-12" and planner.description is None
    assert analyst.locations == ["Leeds", "Remote, United Kingdom"] and analyst.remote is True
    assert analyst.description == "Route planning in SQL." and analyst.posted == "2026-09-20"
    assert planner.url == "https://acme.wd3.myworkdayjobs.com/External/job/Manchester/Demand-Planner_R1"
    assert all("elsewhere" not in url for url, _ in web.calls)


def test_workday_reads_the_place_from_the_path_when_the_listing_has_none():
    # Some tenants send no locationsText; a blank location reads as "nowhere"
    # to a place filter, which emptied a whole board.
    board = workday.WorkdayBoard("acme.wd3/External")
    job = board.job({"title": "Demand Planner", "bulletFields": ["R7", "Location Negotiable"],
                     "externalPath": "/job/Manchester-1-Piccadilly-Corp/Demand-Planner_R7"}, TODAY)
    assert job.location == "Manchester 1 Piccadilly Corp" and job.locations == [job.location]
    remote = board.job({"title": "Analyst", "externalPath": "/job/Remote-United-Kingdom/Analyst_R8"},
                       TODAY)
    assert remote.location == "Remote United Kingdom" and remote.remote is True
    assert workday.path_place("/job/S%C3%A3o-Paulo/Analyst_R9") == "São Paulo"
    assert workday.path_place("not-a-path") == ""


def test_workday_narrows_to_a_country_with_the_boards_own_facet(web):
    def listing(url, payload):
        assert payload["appliedFacets"] in ({}, {"locationCountry": ["uk-id"]})
        return fixture("workday_list.json"), None
    web.routes["/wday/cxs/acme/External/jobs"] = listing
    workday.fetch("acme.wd3/External", country="United Kingdom", today=TODAY)
    assert any(p and p["appliedFacets"] for _, p in web.calls)
    assert workday.fetch("acme.wd3/External", country="Narnia", today=TODAY) == []


def test_workday_stops_when_told_to_slow_down(web):
    web.routes["/wday/cxs/acme/External/jobs"] = (None, "HTTP 429")
    with pytest.raises(BoardError):
        workday.fetch("acme.wd3/External", today=TODAY)


def test_workday_respects_robots_on_the_careers_site_too(web):
    web.robots["acme.wd3.myworkdayjobs.com"] = (200, "User-agent: *\nDisallow: /external/\n")
    with pytest.raises(RobotsDisallowed):
        workday.fetch("acme.wd3/External", today=TODAY)


def test_fetch_filters_and_sorts(web):
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    jobs = openroles.fetch(Board("greenhouse", "acme"), query="data analyst")
    assert [j.id for j in jobs] == ["gh-101"]
    assert [j.id for j in openroles.fetch("greenhouse:acme", remote=True)] == ["gh-102"]
    assert [j.id for j in openroles.fetch("greenhouse:acme", location="london")] == ["gh-101"]
    assert [j.id for j in openroles.fetch("greenhouse:acme")] == ["gh-102", "gh-101"]


def test_lever_reads_a_location_entry_whether_name_or_object(web):
    data = fixture("lever.json")
    data[0]["categories"]["allLocations"] = ["Manchester", {"location": "Leeds"}, {"name": "York"}, {}]
    web.routes["api.lever.co/v0/postings/acme"] = data
    assert lever.fetch("acme")[0].locations == ["Manchester", "Leeds", "York"]
