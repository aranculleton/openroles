"""Teamtailor, Personio and Recruitee, read into the same shape as the rest."""
import pathlib

import pytest

import openroles
from openroles import Board, BoardError, RobotsDisallowed
from openroles.discover import parse
from openroles.providers import personio, recruitee, teamtailor
from openroles.providers._xml import parse as parse_xml

from .conftest import fixture

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def text(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_teamtailor_reads_its_feed_in_one_shape(web):
    web.routes["acme.teamtailor.com/jobs.rss"] = (text("teamtailor.xml"), None)
    analyst, support = teamtailor.fetch("acme")
    assert analyst.id == "tt-0b9c1f7e-1111-4c2b-9f00-000000000101" and analyst.ats == "teamtailor"
    assert analyst.url == "https://acme.teamtailor.com/jobs/101-data-analyst"
    assert analyst.locations == ["Leeds, United Kingdom"] and analyst.workplace == "hybrid"
    assert analyst.remote is None and analyst.posted == "2026-10-06"
    assert analyst.department == "Analytics" and analyst.description == "Forecast demand & build dashboards."
    assert support.workplace == "remote" and support.remote is True and support.locations == ["Remote"]


def test_teamtailor_pages_on_and_reads_a_custom_domain(web):
    asked = []

    def feed(url, payload):
        asked.append(url)
        return text("teamtailor.xml"), None
    web.routes["careers.acme.example/jobs.rss"] = feed
    assert len(teamtailor.fetch("https://careers.acme.example/jobs")) == 2
    assert asked == ["https://careers.acme.example/jobs.rss?per_page=100&offset=0"]
    assert teamtailor.host_of("acme") == "acme.teamtailor.com"


def test_teamtailor_missing_board_and_robots(web):
    web.routes["nobody.teamtailor.com/jobs.rss"] = (None, "HTTP 404")
    with pytest.raises(BoardError):
        teamtailor.fetch("nobody")
    web.robots["acme.teamtailor.com"] = (200, "User-agent: *\nDisallow: /jobs.rss\n")
    with pytest.raises(RobotsDisallowed):
        teamtailor.fetch("acme")


def test_personio_reads_the_xml_and_tries_both_domains(web):
    web.routes["acme.jobs.personio.de/xml"] = (None, "HTTP 404")
    web.routes["acme.jobs.personio.com/xml"] = (text("personio.xml"), None)
    planner, engineer = personio.fetch("acme")
    assert planner.id == "ps-4101" and planner.url == "https://acme.jobs.personio.com/job/4101"
    assert planner.location == "Leeds" and planner.posted == "2026-09-28"
    assert planner.employment_type == "permanent full-time" and planner.department == "Analytics"
    assert planner.description.startswith("The role\nPlan weekly demand.") and "About you" in planner.description
    assert engineer.workplace == "remote" and engineer.remote is True
    assert any("language=en" in url for url, _ in web.calls)


def test_personio_reads_a_name_that_is_no_account_as_no_board(web):
    for host in ("nobody.jobs.personio.de", "nobody.jobs.personio.com"):
        web.robots[host] = (200, "User-agent: *\nDisallow: /\n")
    with pytest.raises(RobotsDisallowed):
        personio.fetch("nobody")
    assert personio.exists("nobody") is False


def test_recruitee_reads_published_offers_with_pay(web):
    web.routes["acme.recruitee.com/api/offers/"] = fixture("recruitee.json")
    [job] = recruitee.fetch("acme")
    assert job.id == "rc-501" and job.url == "https://acme.recruitee.com/o/logistics-analyst"
    assert job.locations == ["Leeds, England, United Kingdom", "Remote UK"]
    assert job.workplace == "hybrid" and job.remote is None
    assert job.posted == "2026-10-05" and job.deadline == "2026-11-30"
    assert job.compensation == "GBP 40,000-48,000 year"
    assert job.description == "Route planning in SQL.\n\nPython"


def test_recruitee_says_when_it_needs_the_employers_token(web):
    web.routes["acme.recruitee.com/api/offers/"] = (None, "HTTP 401")
    with pytest.raises(BoardError, match="token"):
        recruitee.fetch("acme")
    web.routes["acme.recruitee.com/api/offers/"] = (None, "HTTP 404")
    assert recruitee.exists("acme") is False


def test_a_feed_that_declares_entities_is_never_parsed():
    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><rss><channel/></rss>'
    assert parse_xml(bomb) is None
    assert parse_xml("not xml at all") is None
    assert parse_xml("<rss><channel/></rss>").tag == "rss"


@pytest.mark.parametrize("url,board", [
    ("https://acme.teamtailor.com/jobs", Board("teamtailor", "acme")),
    ("https://acme.jobs.personio.de/job/4101", Board("personio", "acme")),
    ("https://acme.jobs.personio.com/", Board("personio", "acme")),
    ("https://acme.recruitee.com/o/logistics-analyst", Board("recruitee", "acme")),
    ("teamtailor:careers.acme.example", Board("teamtailor", "careers.acme.example")),
])
def test_their_boards_are_found_from_a_link(url, board):
    assert parse(url) == board


def test_the_vendors_own_sites_are_not_boards():
    assert parse("https://www.teamtailor.com/en/") is None
    assert parse("https://app.recruitee.com/") is None


def test_fetch_reads_them_like_any_other(web):
    web.routes["acme.recruitee.com/api/offers/"] = fixture("recruitee.json")
    jobs = openroles.fetch("recruitee:acme", location="leeds")
    assert [j.id for j in jobs] == ["rc-501"]


def test_recruitee_reads_a_careers_site_on_the_employers_own_domain(web):
    web.routes["careers.acme.example/api/offers/"] = fixture("recruitee.json")
    assert [j.id for j in recruitee.fetch("careers.acme.example")] == ["rc-501"]
