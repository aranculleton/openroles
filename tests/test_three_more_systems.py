"""Workable, Rippling and JazzHR, read into the same shape as the rest."""
import pathlib

import pytest

import openroles
from openroles import Board, BoardError, RobotsDisallowed
from openroles.discover import parse
from openroles.providers import jazzhr, rippling, workable

from .conftest import fixture

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def test_workable_reads_an_accounts_public_jobs(web):
    web.routes["www.workable.com/api/accounts/acme?details=true"] = fixture("workable.json")
    planner, engineer = workable.fetch("acme")
    assert planner.id == "wk-ABC123" and planner.url == "https://apply.workable.com/acme/j/ABC123/"
    assert planner.location == "Leeds, England, United Kingdom" and planner.workplace == "hybrid"
    assert planner.posted == "2026-10-03" and planner.description == "Plan routes."
    assert engineer.workplace == "remote" and engineer.remote is True


def test_workable_missing_account_is_an_error(web):
    web.routes["www.workable.com/api/accounts/nobody"] = (None, "HTTP 404")
    with pytest.raises(BoardError):
        workable.fetch("nobody")
    assert workable.exists("nobody") is False


def test_rippling_lists_then_reads_only_the_postings_asked_for(web):
    web.routes["/v2/board/acme/jobs/0b9c1f7e"] = fixture("rippling_job.json")
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    report: dict = {}
    analyst, lead = rippling.fetch("acme", details=lambda j: "Analyst" in j.title, report=report)
    assert analyst.id == "rp-0b9c1f7e-0000-4c2b-9f00-000000000201"
    assert analyst.locations == ["Leeds, England, United Kingdom"] and analyst.workplace == "hybrid"
    assert analyst.posted == "2026-09-30" and analyst.employment_type == "Full time"
    assert analyst.compensation == "GBP 45,000-52,000 annual"
    assert analyst.description == "Price lanes in SQL.\n\nAcme moves freight."
    assert lead.description is None and lead.workplace == "remote" and lead.remote is True
    assert report["details_asked"] == 1
    assert len([u for u, _ in web.calls if "/jobs/0b9c" in u]) == 1


def test_rippling_never_reads_more_records_than_its_rate_limit_allows(web, monkeypatch):
    monkeypatch.setattr(rippling, "DETAIL_CAP", 1)
    web.routes["/v2/board/acme/jobs/0b9c1f7e"] = fixture("rippling_job.json")
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    rippling.fetch("acme", details=True)
    assert len([u for u, _ in web.calls if "/jobs/0b9c" in u]) == 1


def test_rippling_missing_board_is_an_error(web):
    web.routes["/v2/board/nobody/jobs"] = (None, "HTTP 404")
    with pytest.raises(BoardError):
        rippling.fetch("nobody")


def test_jazzhr_reads_open_jobs_from_its_feed(web):
    web.routes["app.jazz.co/feeds/export/jobs/acme"] = ((FIXTURES / "jazzhr.xml").read_text(), None)
    [job] = jazzhr.fetch("acme")
    assert job.id == "jz-job_20261001000000_ABCDEFGHIJKLMNOP" and job.title == "Inventory Analyst"
    assert job.location == "Leeds, United Kingdom" and job.department == "Operations"
    assert job.employment_type == "Full Time" and job.description == "Keep stock right."
    assert job.posted == ""                       # the feed dates no job


def test_jazzhr_refused_or_missing(web):
    web.routes["app.jazz.co/feeds/export/jobs/nobody"] = ("", "HTTP 404")
    with pytest.raises(BoardError):
        jazzhr.fetch("nobody")
    web.robots["app.jazz.co"] = (200, "User-agent: *\nDisallow: /feeds/\n")
    with pytest.raises(RobotsDisallowed):
        jazzhr.fetch("acme")


@pytest.mark.parametrize("url,board", [
    ("https://apply.workable.com/acme/", Board("workable", "acme")),
    ("https://apply.workable.com/acme/j/ABC123/", Board("workable", "acme")),
    ("https://acme.workable.com/", Board("workable", "acme")),
    ("https://ats.rippling.com/acme/jobs", Board("rippling", "acme")),
    ("https://acme.applytojob.com/apply/ABCDEFGHIJ/Inventory-Analyst", Board("jazzhr", "acme")),
    ("https://app.jazz.co/feeds/export/jobs/acme", Board("jazzhr", "acme")),
])
def test_their_boards_are_found_from_a_link(url, board):
    assert parse(url) == board


def test_the_vendors_own_sites_are_not_boards():
    assert parse("https://www.workable.com/pricing") is None
    assert parse("https://apply.workable.com/j/ABC123") is None


def test_fetch_asks_rippling_for_descriptions_only_where_the_title_passes(web):
    web.routes["/v2/board/acme/jobs/0b9c1f7e"] = fixture("rippling_job.json")
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    [job] = openroles.fetch("rippling:acme", query="pricing")
    assert job.description and len([u for u, _ in web.calls if "/jobs/0b9c" in u]) == 1
