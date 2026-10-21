"""One posting's odd field never stops a board being read.

Every part of one posting, and of each record read for a posting's details, is replaced by
each odd value a board could send: the board still reads, the other postings are still
there, and no field holds Python's rendering of the odd value ("{'a': 1}", "True", "gh-None").
A posting whose id or title cannot be read is left out. Invented boards only."""
import copy
import datetime as dt
import json
import re
import xml.etree.ElementTree as ET

import pytest

from openroles import Job
from openroles.providers import (
    ashby,
    careersite,
    clearcompany,
    gem,
    greenhouse,
    homerun,
    jazzhr,
    lever,
    manatal,
    personio,
    polymer,
    recruitee,
    rippling,
    teamtailor,
    workable,
    workday,
)

from .conftest import FIXTURES, fixture

TODAY = dt.date(2026, 10, 15)
ODD = [None, 0, -1, True, False, 5, 1.5, "", "x", [], [1], ["a"], {}, {"a": 1}, [None], [{}], [[1]],
       {"name": {"a": 1}}]
# What str() makes of the odd values above that are not text or a number.
JUNK = ["None", "True", "False", "[]", "{}", "[1]", "['a']", "{'a': 1}", "[None]", "[{}]", "[[1]]", "{'name'"]
SITE = "0b9c1f7e-1111-4c2b-9f00-000000000001"

GEM = [{"id": "p1", "title": "Data Analyst", "absolute_url": "https://jobs.gem.com/acme/p1",
        "location": {"name": "Leeds"}, "location_type": "hybrid",
        "offices": [{"name": "North", "location": "Leeds, United Kingdom"}],
        "departments": [{"id": 1, "name": "Analytics"}], "employment_type": "full_time",
        "first_published_at": "2026-09-01T00:00:00Z", "content_plain": "Model demand.",
        "content": "<p>Model.</p>"},
       {"id": "p2", "title": "Planner", "absolute_url": "https://jobs.gem.com/acme/p2"}]
POLYMER = {"items": [{"id": 7, "title": "Planner", "job_post_url": "https://jobs.polymer.co/acme/7",
                      "city": "Leeds", "state_region": "WY", "country": "United Kingdom",
                      "display_location": "Leeds", "remoteness_pretty": "Remote", "kind_pretty": "Full-time",
                      "published_at": "2026-10-02T00:00:00Z", "job_category_name": "Ops",
                      "salary_pretty": "£40k - £45k"},
                     {"id": 8, "title": "Analyst", "job_post_url": "https://jobs.polymer.co/acme/8"}],
           "meta": {"is_last": True}}
POLYMER_RECORD = {"id": 7, "description": "<p>Plan.</p>", "department": "Operations"}
MANATAL = {"results": [{"id": 1, "hash": "h1", "position_name": "Analyst", "city": "Leeds", "state": "WY",
                        "country": "United Kingdom", "location_display": "Leeds", "is_remote": False,
                        "description": "<p>A.</p>", "contract_details": "full_time"},
                       {"id": 2, "hash": "h2", "position_name": "Engineer", "is_remote": True}], "next": None}
CLEARCOMPANY = {"results": [{"id": 55, "positionTitle": "Recruiter", "description": "<p>Hire.</p>",
                             "postedDate": "2026-10-01T00:00:00", "openDate": "2026-09-01",
                             "departmentName": "People", "location": "Leeds",
                             "locations": [{"city": "Leeds", "subdivision": "WY", "country": "United Kingdom",
                                            "isRemote": False}],
                             "applyLink": "https://jobs.clearcompany.com/careers/jobs/55/apply",
                             "salaryRangeLow": 30000, "salaryRangeHigh": 35000, "salaryType": "Annual"},
                            {"id": 56, "positionTitle": "Analyst",
                             "applyLink": "https://jobs.clearcompany.com/careers/jobs/56"}],
                "totalCount": 2}
JOB_POSTING = {"@type": "JobPosting", "title": "Planner", "url": "https://careers.acme.example/job/1",
               "identifier": {"@type": "PropertyValue", "value": "P-1"}, "datePosted": "2026-10-01",
               "validThrough": "2026-12-01", "employmentType": ["FULL_TIME"], "description": "<p>Plan.</p>",
               "jobLocationType": "TELECOMMUTE",
               "applicantLocationRequirements": [{"@type": "Country", "name": "United Kingdom"}],
               "jobLocation": [{"@type": "Place", "address": {"addressLocality": "Leeds", "addressRegion": "WY",
                                                             "addressCountry": {"name": "UK"}}}],
               "baseSalary": {"currency": "GBP", "value": {"minValue": 1, "maxValue": 2, "unitText": "YEAR"}}}


def _careersite(web, posting):
    page = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
    found = [careersite._job("careers.acme.example", "https://careers.acme.example/job/1", p)
             for p in careersite.postings(page)]
    return [j for j in found if j]


# Each reader: its board, where the posting sits in it, the answers to serve (None for the
# board itself), and the read.
READERS = {
    "greenhouse": (lambda: fixture("greenhouse.json"), ("jobs", 0),
                   {"boards-api.greenhouse.io/v1/boards/acme/jobs": None}, lambda web: greenhouse.fetch("acme")),
    "lever": (lambda: fixture("lever.json"), (0,), {"api.lever.co/v0/postings/acme": None},
              lambda web: lever.fetch("acme")),
    "ashby": (lambda: fixture("ashby.json"), ("jobs", 0), {"api.ashbyhq.com/posting-api/job-board/acme": None},
              lambda web: ashby.fetch("acme")),
    "recruitee": (lambda: fixture("recruitee.json"), ("offers", 0), {"acme.recruitee.com/api/offers/": None},
                  lambda web: recruitee.fetch("acme")),
    "workable": (lambda: fixture("workable.json"), ("jobs", 0),
                 {"www.workable.com/api/accounts/acme?details=true": None}, lambda web: workable.fetch("acme")),
    "rippling listing": (lambda: fixture("rippling_list.json"), ("items", 0), {"/v2/board/acme/jobs?": None},
                         lambda web: rippling.fetch("acme")),
    "rippling record": (lambda: fixture("rippling_job.json"), (),
                        {"/v2/board/acme/jobs/0b9c1f7e": None, "/v2/board/acme/jobs?": "rippling_list.json"},
                        lambda web: rippling.fetch("acme", details=True)),
    "workday listing": (lambda: fixture("workday_list.json"), ("jobPostings", 0),
                        {"/wday/cxs/acme/External/jobs": None},
                        lambda web: workday.fetch("acme.wd3/External", today=TODAY)),
    "workday record": (lambda: fixture("workday_job.json"), ("jobPostingInfo",),
                       {"/wday/cxs/acme/External/job/": None, "/wday/cxs/acme/External/jobs": "workday_list.json"},
                       lambda web: workday.fetch("acme.wd3/External", today=TODAY, details=True)),
    "gem": (lambda: copy.deepcopy(GEM), (0,), {"api.gem.com/job_board/v0/acme/job_posts/": None},
            lambda web: gem.fetch("acme")),
    "polymer listing": (lambda: copy.deepcopy(POLYMER), ("items", 0),
                        {"organizations/acme/jobs?page=1": None, "organizations/acme/jobs/7": POLYMER_RECORD},
                        lambda web: polymer.fetch("acme", details=True)),
    "polymer record": (lambda: copy.deepcopy(POLYMER_RECORD), (),
                       {"organizations/acme/jobs/7": None, "organizations/acme/jobs?page=1": POLYMER},
                       lambda web: polymer.fetch("acme", details=True)),
    "manatal": (lambda: copy.deepcopy(MANATAL), ("results", 0), {"career-page/acme/jobs/?page_size=100": None},
                lambda web: manatal.fetch("acme")),
    "clearcompany": (lambda: copy.deepcopy(CLEARCOMPANY), ("results", 0),
                     {f"careers-api.clearcompany.com/v1/{SITE}": None}, lambda web: clearcompany.fetch(SITE)),
    "careers site": (lambda: copy.deepcopy(JOB_POSTING), (), {}, None),
}
TEXT = ("id", "ats", "board", "title", "url", "location", "posted", "department", "employment_type",
        "compensation", "deadline", "workplace", "salary_currency", "salary_period")


def _nodes(node, here=()):
    yield here
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _nodes(v, here + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _nodes(v, here + (i,))


def _at(root, path):
    for step in path:
        root = root[step]
    return root


def _read(web, reader, data):
    _load, _where, routes, read = READERS[reader]
    if read is None:
        return _careersite(web, data)
    for route, source in routes.items():
        web.routes[route] = (data if source is None else fixture(source) if isinstance(source, str)
                             else copy.deepcopy(source))
    return read(web)


def _faults(job: Job, base: str) -> list:
    """What is wrong with one Job: a field of the wrong type, an id or title that is not
    there, or text the board never wrote. `base` is everything the unchanged board gave."""
    out = [f for f in TEXT if not isinstance(getattr(job, f), str)]
    if not (isinstance(job.locations, list) and all(isinstance(x, str) for x in job.locations)):
        out.append("locations")
    if job.remote not in (None, True, False) or not (job.description is None or isinstance(job.description, str)):
        out.append("remote or description")
    if out:
        return out
    if not re.fullmatch(r"[a-z]{2}-\S.*", job.id, re.S) or not job.title:
        out.append(f"id {job.id!r} or title {job.title!r}")
    for value in [getattr(job, f) for f in TEXT] + job.locations + [job.description or ""]:
        out += [f"{value[:40]!r} holds {t!r}" for t in JUNK if t in value and t not in base]
    out += [f"date {v!r}" for v in (job.posted, job.deadline) if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)]
    return out


@pytest.mark.parametrize("reader", list(READERS))
def test_one_posting_s_odd_field_never_stops_its_board_being_read(web, reader):
    load, where, _routes, _read_board = READERS[reader]
    base = _read(web, reader, load())
    assert base, reader
    text = json.dumps([j.to_dict() for j in base])
    problems = []
    for path in list(_nodes(_at(load(), where))):
        for odd in ODD:
            data = load()
            if where + path:
                _at(data, (where + path)[:-1])[(where + path)[-1]] = copy.deepcopy(odd)
            else:
                data = copy.deepcopy(odd)
            jobs = _read(web, reader, data)
            if len(jobs) < len(base) - 1:
                problems.append((path, odd, "lost the board's other postings"))
            problems += [(path, odd, f) for j in jobs for f in _faults(j, text)]
    assert problems == []


FEED = """<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><title>Office Manager</title><link rel="alternate" href="https://acme.homerun.co/office-manager"/>
    <id>job_1</id><updated>2026-10-04T09:00:00Z</updated><content type="html">&lt;p&gt;Run.&lt;/p&gt;</content>
    <department><name>People</name></department><location><name>Leeds</name></location>
    <type><name>Full-time</name></type><salary_indication>£30k</salary_indication></entry>
  <entry><title>Planner</title><link rel="alternate" href="https://acme.homerun.co/planner"/><id>job_2</id></entry>
</feed>"""
FEEDS = {
    "teamtailor": (lambda: (FIXTURES / "teamtailor.xml").read_text(encoding="utf-8"), "acme.teamtailor.com/jobs.rss",
                   ".//item", lambda: teamtailor.fetch("acme")),
    "personio": (lambda: (FIXTURES / "personio.xml").read_text(encoding="utf-8"), "acme.jobs.personio.de/xml",
                 ".//position", lambda: personio.fetch("acme")),
    "jazzhr": (lambda: (FIXTURES / "jazzhr.xml").read_text(encoding="utf-8"), "app.jazz.co/feeds/export/jobs/acme",
               ".//job", lambda: jazzhr.fetch("acme")),
    "homerun": (lambda: FEED, "feed.homerun.co/acme", "{http://www.w3.org/2005/Atom}entry",
                lambda: homerun.fetch("acme")),
}
ODD_TEXT = [None, "", "   ", "x", "0", "1/9/2026", "<b>", "\u00a0", "&amp;"]


@pytest.mark.parametrize("reader", list(FEEDS))
def test_one_posting_s_odd_element_never_stops_its_feed_being_read(web, reader):
    """Each element of one posting removed, emptied, given odd text, or given elements
    where its text belongs."""
    load, route, item, read = FEEDS[reader]
    web.routes[route] = (load(), None)
    base = read()
    text = json.dumps([j.to_dict() for j in base])
    size = len(list(ET.fromstring(load().encode("utf-8")).find(item).iter()))
    problems = []
    for n in range(1, size):
        for change in ["remove", "elements", "attribute"] + [("text", t) for t in ODD_TEXT]:
            root = ET.fromstring(load().encode("utf-8"))
            posting = root.find(item)
            element = list(posting.iter())[n]
            parent = next(p for p in posting.iter() if element in list(p))
            if change == "remove":
                parent.remove(element)
            elif change == "elements":
                element.text = None
                ET.SubElement(element, "odd").text = "inside"
            elif change == "attribute":
                element.set("href", "")
            else:
                element.text = change[1]
            web.routes[route] = (ET.tostring(root, encoding="unicode"), None)
            jobs = read()
            if len(jobs) < len(base) - 1:
                problems.append((element.tag, change, "lost the feed's other postings"))
            problems += [(element.tag, change, f) for j in jobs for f in _faults(j, text)]
    assert problems == []


def test_a_posting_whose_id_or_title_cannot_be_read_is_left_out(web):
    """Each came out as a posting called "gh-None" or titled "{'a': 1}", one the same as
    every other such posting."""
    data = fixture("greenhouse.json")
    data["jobs"] = data["jobs"][:2]
    data["jobs"][0]["id"] = None
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = data
    assert [j.id for j in greenhouse.fetch("acme")] == [f"gh-{data['jobs'][1]['id']}"]
    data["jobs"][0]["id"], data["jobs"][0]["title"] = 7, {"text": "Analyst"}
    assert len(greenhouse.fetch("acme")) == 1
    feed = (FIXTURES / "jazzhr.xml").read_text(encoding="utf-8")
    root = ET.fromstring(feed.encode("utf-8"))
    first = root.find(".//job")
    first.remove(first.find("id"))
    web.routes["app.jazz.co/feeds/export/jobs/acme"] = (ET.tostring(root, encoding="unicode"), None)
    assert "jz-" not in [j.id for j in jazzhr.fetch("acme")]
