"""The posted pay band as numbers, where the board publishes it as numbers.

Never read out of a description: a board that only words its pay gives `compensation`
and nothing here. Invented boards and figures only."""
import json
import math

import pytest

from openroles import Job
from openroles.providers import ashby, careersite, clearcompany, greenhouse, lever, recruitee, rippling

from .conftest import fixture

NONE = (None, None, "", "")


def band(job: Job):
    return job.salary_min, job.salary_max, job.salary_currency, job.salary_period


def test_lever_salary_range(web):
    web.routes["api.lever.co/v0/postings/acme"] = fixture("lever.json")
    job = lever.fetch("acme")[0]
    assert band(job) == (50000, 65000, "GBP", "year")
    assert job.compensation == "GBP 50,000-65,000 per year salary"     # unchanged


def test_ashby_salary_from_its_summary_and_never_from_equity(web):
    data = fixture("ashby.json")
    data["jobs"][0]["compensation"] = {
        "compensationTierSummary": "$81K - $87K • 0.5% - 1.75%",
        "summaryComponents": [
            {"compensationType": "EquityPercentage", "interval": "NONE", "currencyCode": None,
             "minValue": 0.5, "maxValue": 1.75},
            {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "USD",
             "minValue": 81000, "maxValue": 87000}]}
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = data
    assert band(ashby.fetch("acme")[0]) == (81000, 87000, "USD", "year")


def test_ashby_tiers_in_one_currency_are_one_band_and_in_two_are_none(web):
    def tier(cur, lo, hi):
        return {"title": "Zone", "components": [{"compensationType": "Salary", "interval": "1 YEAR",
                                                 "currencyCode": cur, "minValue": lo, "maxValue": hi}]}
    data = fixture("ashby.json")
    data["jobs"][0]["compensation"] = {"compensationTiers": [tier("GBP", 50000, 60000),
                                                             tier("GBP", 55000, 70000)]}
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = data
    assert band(ashby.fetch("acme")[0]) == (50000, 70000, "GBP", "year")
    data["jobs"][0]["compensation"] = {"compensationTiers": [tier("GBP", 50000, 60000),
                                                             tier("EUR", 58000, 70000)]}
    assert band(ashby.fetch("acme")[0]) == NONE


def test_ashby_tiers_paid_over_different_intervals_are_not_one_band(web):
    def tier(interval, lo, hi):
        return {"title": "Zone", "components": [{"compensationType": "Salary", "interval": interval,
                                                 "currencyCode": "GBP", "minValue": lo, "maxValue": hi}]}
    data = fixture("ashby.json")
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = data
    for pair in (("1 WEEK", "2 WEEK"), ("2 WEEK", "0.5 MONTH"), ("1 MONTH", "6 MONTH")):
        data["jobs"][0]["compensation"] = {"compensationTiers": [tier(pair[0], 1000, 1200),
                                                                 tier(pair[1], 2000, 2400)]}
        assert band(ashby.fetch("acme")[0]) == NONE, pair
    data["jobs"][0]["compensation"] = {"summaryComponents": [
        {"compensationType": "Salary", "interval": "2 WEEK", "currencyCode": "GBP",
         "minValue": 2000, "maxValue": 2400}]}
    assert band(ashby.fetch("acme")[0]) == (2000, 2400, "GBP", "")       # not "week"


def test_ashby_pay_worded_only_gives_no_figures(web):
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = fixture("ashby.json")
    job = ashby.fetch("acme")[0]
    assert job.compensation == "£60K - £75K" and band(job) == NONE


def test_recruitee_salary_written_as_strings(web):
    web.routes["acme.recruitee.com/api/offers/"] = fixture("recruitee.json")
    assert band(recruitee.fetch("acme")[0]) == (40000, 48000, "GBP", "year")


def test_rippling_salary_comes_with_the_posting_record_only(web):
    web.routes["/v2/board/acme/jobs/0b9c1f7e"] = fixture("rippling_job.json")
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    analyst, lead = rippling.fetch("acme", details=lambda j: "Analyst" in j.title)
    assert band(analyst) == (45000, 52000, "GBP", "year")
    assert band(lead) == NONE                                # its record was not read


def test_clearcompany_salary_has_no_currency_to_give(web):
    site = "0b9c1f7e-2222-4c2b-9f00-000000000301"
    web.routes[f"careers-api.clearcompany.com/v1/{site}"] = {"results": [{
        "id": 55, "positionTitle": "Recruiter", "applyLink": "https://jobs.clearcompany.com/careers/jobs/55",
        "salaryRangeLow": 30000, "salaryRangeHigh": 35000, "salaryType": "Hourly"}]}
    assert band(clearcompany.fetch(site)[0]) == (30000, 35000, "", "hour")


@pytest.mark.parametrize("salary,want", [
    ({"currency": "CAD", "value": {"minValue": 90000, "maxValue": 110000, "unitText": "YEAR"}},
     (90000, 110000, "CAD", "year")),
    ({"currency": "EUR", "value": {"value": 28.5, "unitText": "HOUR"}}, (28.5, 28.5, "EUR", "hour")),
    ({"currency": "GBP", "value": 52000}, (52000, 52000, "GBP", "")),
    ({"currency": "GBP", "value": {"unitText": "YEAR"}}, NONE),
])
def test_a_careers_site_salary_from_schema_org(salary, want):
    posting = {"@type": "JobPosting", "title": "Demand Planner", "baseSalary": salary}
    page = f'<script type="application/ld+json">{json.dumps(posting)}</script>'
    job = careersite._job("careers.acme.example", "https://careers.acme.example/job/1",
                          careersite.postings(page)[0])
    assert band(job) == want


def test_a_board_that_publishes_no_pay_gives_none(web):
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    assert {band(j) for j in greenhouse.fetch("acme")} == {NONE}


def test_the_figures_are_in_the_dict_every_caller_reads(web):
    web.routes["api.lever.co/v0/postings/acme"] = fixture("lever.json")
    d = lever.fetch("acme")[0].to_dict()
    assert (d["salary_min"], d["salary_max"], d["salary_currency"], d["salary_period"]) == \
        (50000, 65000, "GBP", "year")


@pytest.mark.parametrize("value,want", [
    (48000, 48000), (48000.0, 48000), (28.5, 28.5), ("48000", 48000), ("48,000", 48000),
    (" 48000.50 ", 48000.5),
    ("48.000", None),          # forty-eight thousand in much of Europe, forty-eight elsewhere
    ("48k", None), ("", None), (None, None), (True, None), (0, None), (-5, None),
    (math.nan, None), (math.inf, None), ("competitive", None),
])
def test_a_figure_is_read_only_when_it_cannot_be_misread(value, want):
    from openroles.models import amount
    assert amount(value) == want


@pytest.mark.parametrize("value,want", [
    ("per-year-salary", "year"), ("1 YEAR", "year"), ("ANNUAL", "year"), ("Annually", "year"),
    ("per-hour-wage", "hour"), ("HOURLY", "hour"), ("MONTHLY", "month"), ("per-month-salary", "month"),
    ("weekly", "week"), ("DAY", "day"), ("daily", "day"),
    ("bi-weekly", ""), ("semi-monthly", ""), ("one-time", ""), ("NONE", ""), ("", ""), (None, ""),
    # Ashby's intervals carry a count, and only a count of one is the period it names.
    ("1 HOUR", "hour"), ("1 MONTH", "month"), ("1.0 WEEK", "week"), ("1 TIME", ""),
    ("2 WEEK", ""), ("0.5 MONTH", ""), ("2 MONTH", ""), ("3 MONTH", ""), ("6 MONTH", ""),
    ("semi-annual", ""), ("Semiannually", ""), ("biannual", ""), ("twice monthly", ""),
])
def test_one_word_for_each_pay_period(value, want):
    from openroles.models import period_of
    assert period_of(value) == want


def test_a_currency_or_period_with_no_figure_says_nothing():
    from openroles.models import pay
    assert pay(None, None, "GBP", "year") == {"salary_min": None, "salary_max": None,
                                              "salary_currency": "", "salary_period": ""}
    assert pay(40000, None, "gbp ", "year")["salary_currency"] == "GBP"
    assert pay(40000, None, "pounds", "year")["salary_currency"] == ""
