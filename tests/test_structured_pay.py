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


HUGE = 10 ** 400          # a plain JSON integer, which json.loads keeps as an int


def test_an_odd_pay_shape_gives_no_figure_and_never_sinks_the_board(web):
    """One posting's odd pay raised OverflowError or TypeError, which is not a BoardError,
    so fetch() lost every board in the call."""
    data = fixture("lever.json")
    data[0]["salaryRange"] = {"min": HUGE, "max": 65000, "currency": "GBP", "interval": "per-year-salary"}
    web.routes["api.lever.co/v0/postings/acme"] = data
    assert band(lever.fetch("acme")[0]) == (None, 65000, "GBP", "year")

    data = fixture("ashby.json")
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = data
    for compensation in ({"compensationTiers": 5}, {"compensationTiers": True},
                         {"summaryComponents": 1.5}, {"compensationTiers": [{"components": 7}]},
                         {"summaryComponents": [{"compensationType": "Salary", "interval": "1 YEAR",
                                                 "currencyCode": "GBP", "minValue": HUGE, "maxValue": HUGE}]}):
        data["jobs"][0]["compensation"] = compensation
        assert band(ashby.fetch("acme")[0]) == NONE, compensation

    data = fixture("recruitee.json")
    data["offers"][0]["salary"] = {"min": HUGE, "max": math.inf, "currency": "GBP", "period": "year"}
    web.routes["acme.recruitee.com/api/offers/"] = data
    assert band(recruitee.fetch("acme")[0]) == NONE

    job = fixture("rippling_job.json")
    job["payRangeDetails"] = [{"rangeStart": HUGE, "rangeEnd": HUGE, "currency": "GBP", "frequency": "ANNUAL"}]
    web.routes["/v2/board/acme/jobs/0b9c1f7e"] = job
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    assert band(rippling.fetch("acme", details=True)[0]) == NONE

    site = "0b9c1f7e-2222-4c2b-9f00-000000000301"
    web.routes[f"careers-api.clearcompany.com/v1/{site}"] = {"results": [{
        "id": 55, "positionTitle": "Recruiter", "applyLink": "https://jobs.clearcompany.com/careers/jobs/55",
        "salaryRangeLow": HUGE, "salaryRangeHigh": HUGE, "salaryType": "Hourly"}]}
    assert band(clearcompany.fetch(site)[0]) == NONE

    posting = {"@type": "JobPosting", "title": "T", "basesalary": {"currency": "GBP", "value": HUGE}}
    assert careersite._salary(posting) == careersite._salary({}) and careersite._pay(posting)


@pytest.mark.parametrize("odd", [5, 1.5, True, -1, math.nan, "x", {"rangeStart": 1}])
def test_rippling_pay_ranges_that_are_not_a_list_give_no_figure(web, odd):
    """A number or true where the list of ranges belongs raised TypeError out of fetch()."""
    job = fixture("rippling_job.json")
    job["payRangeDetails"] = odd
    web.routes["/v2/board/acme/jobs/0b9c1f7e"] = job
    web.routes["/v2/board/acme/jobs?"] = fixture("rippling_list.json")
    found = rippling.fetch("acme", details=True)[0]
    assert band(found) == NONE and found.compensation == "" and found.description


ODD = [None, 0, -1, True, False, 5, 1.5, "", "x", "1e999", "-5", [], [1], ["a"], {}, {"a": 1},
       math.nan, math.inf, -math.inf, HUGE, [[1]], [None], [{"min": 5}], {"min": {"x": 1}}, "48.000"]


def _nodes(node, here=()):
    yield here
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _nodes(v, here + (k,))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _nodes(v, here + (i,))


def _with(root, path, value):
    if not path:
        return value
    node = root
    for p in path[:-1]:
        node = node[p]
    node[path[-1]] = value
    return root


def _sound(job: Job) -> bool:
    def figure(x):
        return x is None or (type(x) in (int, float) and math.isfinite(x) and x > 0)
    lo, hi = job.salary_min, job.salary_max
    return (figure(lo) and figure(hi) and (lo is None or hi is None or lo <= hi)
            and isinstance(job.salary_currency, str) and isinstance(job.salary_period, str)
            and isinstance(job.compensation, str))


def _ashby():
    data = fixture("ashby.json")
    data["jobs"][0]["compensation"] = {"compensationTierSummary": "GBP 1-2", "summaryComponents": [
        {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "GBP", "minValue": 1, "maxValue": 2}],
        "compensationTiers": [{"components": [
            {"compensationType": "Salary", "interval": "1 YEAR", "currencyCode": "GBP", "minValue": 1, "maxValue": 2}]}]}
    return data


SITE = "0b9c1f7e-2222-4c2b-9f00-000000000301"
# Each reader: its board, where its pay sits in it (and which fields there are pay), the
# answers to serve, and the read.
READERS = {
    "lever": (lambda: fixture("lever.json"), (0, "salaryRange"), None,
              {"api.lever.co/v0/postings/acme": None}, lambda: lever.fetch("acme")),
    "ashby": (_ashby, ("jobs", 0, "compensation"), None,
              {"api.ashbyhq.com/posting-api/job-board/acme": None}, lambda: ashby.fetch("acme")),
    "recruitee": (lambda: fixture("recruitee.json"), ("offers", 0, "salary"), None,
                  {"acme.recruitee.com/api/offers/": None}, lambda: recruitee.fetch("acme")),
    "rippling": (lambda: fixture("rippling_job.json"), ("payRangeDetails",), None,
                 {"/v2/board/acme/jobs/0b9c1f7e": None, "/v2/board/acme/jobs?": "rippling_list.json"},
                 lambda: rippling.fetch("acme", details=True)),
    "clearcompany": (lambda: {"results": [{"id": 55, "positionTitle": "Recruiter",
                                           "applyLink": "https://jobs.clearcompany.com/careers/jobs/55",
                                           "salaryRangeLow": 40000, "salaryRangeHigh": 50000,
                                           "salaryType": "Annual"}]},
                     ("results", 0), {"salaryRangeLow", "salaryRangeHigh", "salaryType"},
                     {f"careers-api.clearcompany.com/v1/{SITE}": None}, lambda: clearcompany.fetch(SITE)),
}


@pytest.mark.parametrize("reader", sorted(READERS))
def test_every_odd_value_anywhere_in_a_reader_s_pay_gives_no_figure_and_no_exception(web, reader):
    """Each part of each reader's structured pay, the whole field included, replaced by
    each odd value a board could send: the board still reads, and every figure is a
    positive number or none, lowest first."""
    load, where, only, routes, fetch = READERS[reader]
    pay = load()
    for step in where:
        pay = pay[step]
    for path in list(_nodes(pay)):
        if only and (not path or path[0] not in only):
            continue
        for odd in ODD:
            data = load()
            _with(data, where + path, odd)
            for route, source in routes.items():
                web.routes[route] = data if source is None else fixture(source)
            jobs = fetch()
            assert jobs and all(_sound(j) for j in jobs), (path, odd)


def test_every_odd_value_anywhere_in_a_careers_site_s_pay_gives_no_figure_and_no_exception():
    posting = {"@type": "JobPosting", "title": "T", "salaryCurrency": "GBP",
               "baseSalary": {"@type": "MonetaryAmount", "currency": "GBP", "value": {
                   "@type": "QuantitativeValue", "minValue": 1, "maxValue": 2, "unitText": "YEAR", "value": 3}}}
    for path in list(_nodes(posting)):
        if not path or path[0] not in ("baseSalary", "salaryCurrency"):
            continue
        for odd in ODD:
            page = careersite._lower(_with(json.loads(json.dumps(posting)), path, odd))
            job = careersite._job("careers.acme.example", "https://careers.acme.example/job/1", page)
            assert job and _sound(job), (path, odd)


def test_a_range_written_high_to_low_comes_out_lowest_first(web):
    """A caller filtering on salary_max >= x was given the minimum."""
    from openroles.models import pay
    assert pay(65000, 50000, "GBP", "year")["salary_min"] == 50000
    assert (pay(65000, None)["salary_min"], pay(None, 50000)["salary_max"]) == (65000, 50000)

    data = fixture("lever.json")
    data[0]["salaryRange"] = {"min": 65000, "max": 50000, "currency": "GBP", "interval": "per-year-salary"}
    web.routes["api.lever.co/v0/postings/acme"] = data
    assert band(lever.fetch("acme")[0]) == (50000, 65000, "GBP", "year")

    def tier(lo, hi):
        return {"components": [{"compensationType": "Salary", "interval": "1 YEAR",
                                "currencyCode": "GBP", "minValue": lo, "maxValue": hi}]}
    data = fixture("ashby.json")
    data["jobs"][0]["compensation"] = {"compensationTiers": [tier(50000, 60000), tier(70000, 55000)]}
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = data
    assert band(ashby.fetch("acme")[0]) == (50000, 70000, "GBP", "year")


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
    # plain JSON integers past any float
    pytest.param(10 ** 400, None, id="huge-int"), pytest.param("9" * 400, None, id="huge-digits"),
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
