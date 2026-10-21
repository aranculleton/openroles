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
