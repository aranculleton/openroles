"""A posting's id from its address alone, the same id the board's reader gives it.

Invented boards, ids and addresses only."""
import datetime as dt

import pytest

import openroles
from openroles.providers import greenhouse, lever, personio, rippling, workable, workday

from .conftest import FIXTURES, fixture

U1 = "6f1c2d3e-4a5b-4c6d-8e9f-0a1b2c3d4e5f"
U2 = "0b9c1f7e-0000-4c2b-9f00-000000000201"
WD = "wd-acme-Demand-Planner_R1"


@pytest.mark.parametrize("url,want", [
    ("https://boards.greenhouse.io/acme/jobs/4012345", "gh-4012345"),
    ("https://job-boards.greenhouse.io/acme/jobs/4012345?gh_src=x1", "gh-4012345"),
    ("https://job-boards.eu.greenhouse.io/acme/jobs/4012345", "gh-4012345"),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&token=4012345", "gh-4012345"),
    ("https://www.acme.example/careers/open-roles?gh_jid=4012345&utm_source=x", "gh-4012345"),
    ("www.acme.example/careers?gh_jid=4012345", "gh-4012345"),
    (f"https://jobs.lever.co/acme/{U1}", f"lv-{U1}"),
    (f"https://jobs.lever.co/acme/{U1}/apply?lever-source=board", f"lv-{U1}"),
    (f"https://jobs.eu.lever.co/acme/{U1}", f"lv-{U1}"),
    (f"https://jobs.ashbyhq.com/acme/{U1}", f"ab-{U1}"),
    (f"https://jobs.ashbyhq.com/acme/{U1}/application", f"ab-{U1}"),
    (f"https://ats.rippling.com/acme/jobs/{U2}", f"rp-{U2}"),
    ("https://apply.workable.com/acme/j/ABC123DEF4/", "wk-ABC123DEF4"),
    ("https://apply.workable.com/j/ABC123DEF4", "wk-ABC123DEF4"),
    ("https://acme.jobs.personio.de/job/4101?language=en", "ps-4101"),
    ("https://acme.jobs.personio.com/job/4101", "ps-4101"),
    ("https://acme.wd3.myworkdayjobs.com/External/job/Manchester/Demand-Planner_R1", WD),
    ("https://acme.wd3.myworkdayjobs.com/en-US/External/job/Manchester/Demand-Planner_R1/apply", WD),
    ("https://acme.wd3.myworkdayjobs.com/en-US/External/details/Demand-Planner_R1", WD),
    ("https://wd3.myworkdaysite.com/en-US/recruiting/acme/External/job/Manchester/Demand-Planner_R1", WD),
])
def test_a_posting_address_gives_its_id(url, want):
    assert openroles.job_id(url) == want


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/acme",                       # a board, not a posting
    "https://boards.greenhouse.io/acme/jobs/",
    "https://www.acme.example/careers?gh_jid=",
    "https://www.acme.example/careers?gh_jid=abc",
    "https://www.acme.example/careers/4012345",                # digits on a page that is not Greenhouse's
    "https://jobs.lever.co/acme",
    "https://jobs.lever.co/acme/embed",                         # a board page, never a posting
    "https://jobs.ashbyhq.com/acme/embed",
    "https://jobs.ashbyhq.com/acme/not-a-posting-id",
    "https://apply.workable.com/acme/",
    "https://acme.jobs.personio.de/",
    "https://acme.wd3.myworkdayjobs.com/External",
    "https://acme.wd3.myworkdayjobs.com/External/job/Manchester",   # a place, not a posting
    "https://elsewhere.example/job/Manchester/Demand-Planner_R1",
    "ftp://boards.greenhouse.io/acme/jobs/4012345",
    "",
    None,
])
def test_an_address_that_does_not_carry_an_id_gives_none(url):
    assert openroles.job_id(url) == ""


def test_every_reader_s_own_address_gives_back_its_own_id(web):
    """The point of it: the copy on the board and a link to it agree."""
    jobs = []
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    jobs += greenhouse.fetch("acme")
    data = fixture("lever.json")
    data[0]["id"], data[0]["hostedUrl"] = U1, f"https://jobs.lever.co/acme/{U1}"
    web.routes["api.lever.co/v0/postings/acme"] = data
    jobs += lever.fetch("acme")
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    jobs += rippling.fetch("acme")
    web.routes["www.workable.com/api/accounts/acme?details=true"] = fixture("workable.json")
    jobs += workable.fetch("acme")
    web.routes["acme.jobs.personio.de/xml"] = ((FIXTURES / "personio.xml").read_text(encoding="utf-8"), None)
    jobs += personio.fetch("acme")
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    jobs += workday.fetch("acme.wd3/External", today=dt.date(2026, 10, 15))
    assert {j.ats for j in jobs} == {"greenhouse", "lever", "rippling", "workable", "personio", "workday"}
    assert [openroles.job_id(j.url) for j in jobs] == [j.id for j in jobs]


@pytest.mark.parametrize("url,want", [
    # The boards give their UUIDs in lower case; an address written in upper case is the
    # same posting.
    (f"https://jobs.lever.co/acme/{U1.upper()}", f"lv-{U1}"),
    (f"https://jobs.ashbyhq.com/acme/{U1.upper()}/application", f"ab-{U1}"),
    (f"https://ats.rippling.com/en-GB/acme/jobs/{U2.upper()}", f"rp-{U2}"),
    (f"https://ats.rippling.com/en-gb/acme/jobs/{U2}", f"rp-{U2}"),
    # As scraped HTML writes its links.
    ("//boards.greenhouse.io/acme/jobs/4012345", "gh-4012345"),
    # gh_jid saying what the address already says is no conflict.
    ("https://boards.greenhouse.io/acme/jobs/4012345?gh_jid=4012345", "gh-4012345"),
    ("https://www.acme.example/careers?gh_jid=4012345&gh_jid=4012345", "gh-4012345"),
])
def test_an_address_written_another_way_gives_the_same_id(url, want):
    assert openroles.job_id(url) == want


@pytest.mark.parametrize("url", [
    "https://boards.greenhouse.io/acme/jobs/4012345?gh_jid=999",
    "https://boards.greenhouse.io/embed/job_app?for=acme&token=4012345&gh_jid=999",
    f"https://jobs.lever.co/acme/{U1}?gh_jid=99",
    "https://www.acme.example/careers?gh_jid=4012345&gh_jid=999",
])
def test_an_address_with_two_ids_that_disagree_gives_none(url):
    """Either could be the wrong one, and a wrong id loses a role."""
    assert openroles.job_id(url) == ""


def test_a_workday_posting_whose_path_needs_encoding_gives_back_its_own_id(web):
    """The address percent-encodes the path ("&" is %26, "ü" %C3%BC); the id keeps the path
    as the listing sends it, as 0.2.0 did."""
    listing = {"total": 3, "facets": [], "jobPostings": [
        {"title": "Pricing", "externalPath": "/job/London/Pricing-&-Revenue-Analyst_R5",
         "locationsText": "London"},
        {"title": "Analista", "externalPath": "/job/São-Paulo/Analista-de-Precificação_R4",
         "locationsText": "São Paulo"},
        {"title": "Planner", "externalPath": "/job/Leeds/Planner-(Fixed-Term)_R6",
         "locationsText": "Leeds"},
    ]}
    web.routes["/wday/cxs/acme/External/jobs"] = listing
    jobs = workday.fetch("acme.wd3/External", today=dt.date(2026, 10, 15))
    assert len(jobs) == 3
    assert [openroles.job_id(j.url) for j in jobs] == [j.id for j in jobs]
    assert jobs[0].id == "wd-acme-Pricing-&-Revenue-Analyst_R5"
    # A link written with the characters themselves is the same address.
    assert openroles.job_id("https://acme.wd3.myworkdayjobs.com/External/job/S%C3%A3o-Paulo/"
                            "Analista-de-Precificação_R4") == jobs[1].id


# The id 0.2.0 gave each of these, which a caller may have stored.
WORKDAY_0_2_0 = [
    ("/job/M%C3%BCnchen/Datenanalyst-M%C3%BCnchen_R3", "wd-acme-Datenanalyst-M%C3%BCnchen_R3"),
    ("/job/London/Pricing-&-Revenue-Analyst_R5", "wd-acme-Pricing-&-Revenue-Analyst_R5"),
    ("/job/X/Save-10%AB_R7", "wd-acme-Save-10%AB_R7"),
    ("/job/X/Data%2FAnalytics_R8", "wd-acme-Data%2FAnalytics_R8"),
    ("/job/X/a%25b_R9", "wd-acme-a%25b_R9"),
    ("/job/Toronto-ON/Senior-Data-Analyst_R-123456", "wd-acme-Senior-Data-Analyst_R-123456"),
]


def test_a_workday_id_is_what_0_2_0_gave_whatever_the_path_holds(web):
    """A path that arrived percent-encoded was decoded into the id for a while, so a stored
    id changed, a broken escape became U+FFFD and %2F put a "/" inside the id."""
    web.routes["/wday/cxs/acme/External/jobs"] = {"total": len(WORKDAY_0_2_0), "facets": [], "jobPostings": [
        {"title": f"Role {n}", "externalPath": path, "locationsText": "X"}
        for n, (path, _) in enumerate(WORKDAY_0_2_0)]}
    jobs = workday.fetch("acme.wd3/External", today=dt.date(2026, 10, 15))
    assert [j.id for j in jobs] == [want for _, want in WORKDAY_0_2_0]
    # Escapes an address never writes for a character show the listing sent them, so
    # these read back too.
    assert [openroles.job_id(j.url) for j in jobs[2:]] == [j.id for j in jobs[2:]]
    # The one address that cannot be told apart: a listing that sends "München" gives the
    # same one, and that is how it reads.
    assert openroles.job_id(jobs[0].url) == "wd-acme-Datenanalyst-München_R3"


def test_a_workday_path_no_address_can_hold_is_left_out_not_an_exception(web):
    """JSON can carry a lone surrogate, which has no UTF-8: writing its address raised
    UnicodeEncodeError out of fetch()."""
    import json
    web.routes["/wday/cxs/acme/External/jobs"] = json.loads(
        '{"total": 2, "facets": [], "jobPostings": ['
        '{"title": "Odd", "externalPath": "/job/X/Odd-\\ud800_R1", "locationsText": "X"},'
        '{"title": "Planner", "externalPath": "/job/X/Planner_R2", "locationsText": "X"}]}')
    jobs = workday.fetch("acme.wd3/External", today=dt.date(2026, 10, 15))
    assert [j.id for j in jobs] == ["wd-acme-Planner_R2"]
    assert openroles.job_id("https://acme.wd3.myworkdayjobs.com/External/job/X/Odd-\ud800_R1") == ""
