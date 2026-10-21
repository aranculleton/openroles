"""`posted` and `deadline` are a real YYYY-MM-DD or nothing, whatever a board sends.

Invented boards and values only."""
import datetime as dt

import pytest

import openroles
from openroles.providers import greenhouse, recruitee, workday

from .conftest import fixture

TODAY = dt.date(2026, 10, 15)


@pytest.mark.parametrize("value,want", [
    ("2026-10-05", "2026-10-05"),
    ("2026-10-05T09:00:00-04:00", "2026-10-05"),       # the employer's own day, as before
    ("2026-10-05 08:00:00 UTC", "2026-10-05"),
    ("  2026-10-05", "2026-10-05"),
    ("1/9/2026", ""),
    ("Invalid date", ""),
    ("2026-02-30", ""),                                # not a day, never the next one along
    ("2026-10-055", ""),
    (None, ""),
    (1760000000000, ""),                               # an epoch is a reader's to convert
])
def test_one_reading_of_a_date(value, want):
    from openroles.models import iso_day
    assert iso_day(value) == want


def test_the_first_readable_value_wins():
    from openroles.models import iso_day
    assert iso_day("soon", "2026-10-01T00:00:00Z") == "2026-10-01"
    assert iso_day("", None) == ""


@pytest.mark.parametrize("value", [
    "0001-01-01T00:00:00",                             # .NET's DateTime.MinValue
    "1900-01-01", "1970-01-01T00:00:00Z", "1989-12-31", "9999-12-31",
])
def test_a_placeholder_written_as_a_date_is_no_date(value):
    """Read as real, it dropped the role from since_days, sorted it last and blocked the
    fallback a missing date gets."""
    from openroles.models import iso_day
    assert iso_day(value) == ""
    assert iso_day(value, "2026-10-01T00:00:00") == "2026-10-01"


def test_a_real_date_near_either_edge_is_kept():
    from openroles.models import iso_day
    assert iso_day("1990-01-01") == "1990-01-01"
    ahead = dt.date.today() + dt.timedelta(days=365)
    assert iso_day(ahead.isoformat()) == ahead.isoformat()        # a closing date next year
    assert iso_day((dt.date.today() + dt.timedelta(days=3 * 366)).isoformat()) == ""


def test_a_placeholder_date_falls_back_to_the_next_one_a_board_gives(web):
    from openroles.providers import clearcompany, lever
    site = "0b9c1f7e-2222-4c2b-9f00-000000000301"
    web.routes[f"careers-api.clearcompany.com/v1/{site}"] = {"results": [{
        "id": 55, "positionTitle": "Recruiter", "applyLink": "https://jobs.clearcompany.com/careers/jobs/55",
        "postedDate": "0001-01-01T00:00:00", "openDate": "2026-10-01T00:00:00"}]}
    assert clearcompany.fetch(site)[0].posted == "2026-10-01"
    data = fixture("lever.json")
    data[0]["createdAt"] = 0                           # the epoch: Lever's blank
    web.routes["api.lever.co/v0/postings/acme"] = data
    assert lever.fetch("acme")[0].posted == ""


def test_a_date_a_board_wrote_its_own_way_is_no_date_and_the_role_is_kept(web):
    data = fixture("greenhouse.json")
    data["jobs"][0]["first_published"] = "1/9/2026"
    data["jobs"][0].pop("updated_at", None)
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = data
    assert greenhouse.fetch("acme")[0].posted == ""
    # A role with no date is kept by since_days. Read as text, "1/9/2026" compared as
    # older than every real date, and the role was dropped for a date nobody gave it.
    jobs = openroles.fetch("greenhouse:acme", since_days=14, today=TODAY)
    assert [j.id for j in jobs] == ["gh-102", "gh-101"]


def test_an_unreadable_first_published_date_falls_back_as_a_missing_one_does(web):
    data = fixture("greenhouse.json")
    data["jobs"][0]["first_published"] = "pending"
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = data
    assert greenhouse.fetch("acme")[0].posted == data["jobs"][0]["updated_at"][:10]


def test_an_impossible_closing_date_is_left_out(web):
    data = fixture("recruitee.json")
    for o in data["offers"]:
        o["close_at"] = "2026-02-30 23:59:00 UTC"
    web.routes["acme.recruitee.com/api/offers"] = data
    assert {j.deadline for j in recruitee.fetch("acme")} == {""}


def test_a_workday_posting_page_with_no_readable_start_keeps_the_listing_date(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    page = fixture("workday_job.json")
    page["jobPostingInfo"]["startDate"] = "pending"
    page["jobPostingInfo"]["endDate"] = "2026-13-01"
    web.routes["/wday/cxs/acme/External/job/"] = page
    listed = {j.id: j.posted for j in workday.fetch("acme.wd3/External", today=TODAY)}
    detailed = workday.fetch("acme.wd3/External", details=True, today=TODAY)
    assert all(j.posted == listed[j.id] for j in detailed)
    assert all(j.deadline == "" for j in detailed)
