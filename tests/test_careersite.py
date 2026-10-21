"""Any careers site that publishes its jobs for search engines, read from its sitemap and
each page's JobPosting. An invented site, careers.acme.example."""
import html
import json

import pytest

import openroles
from openroles import BoardError, RobotsDisallowed
from openroles.providers import careersite

HOST = "careers.acme.example"
ROBOTS = (200, "User-agent: *\nAllow: /\nCrawl-delay: 5\n"
               f"Sitemap: https://{HOST}/sitemap_index.xml\n")
INDEX = f"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://{HOST}/sitemap-jobs.xml</loc></sitemap>
  <sitemap><loc>https://elsewhere.example/sitemap.xml</loc></sitemap>
</sitemapindex>"""
JOBS = f"""<?xml version="1.0"?>
<urlset xmlns="http://www.google.com/schemas/sitemap/0.9">
  <url><loc>https://{HOST}/us/en/job/P-101/demand-planner</loc><lastmod>2026-10-01</lastmod></url>
  <url><loc>https://{HOST}/us/en/job/P-102/pricing-analyst</loc><lastmod>2026-10-09</lastmod></url>
  <url><loc>https://{HOST}/us/en/job/P-103/warehouse-operative</loc><lastmod>2026-10-05</lastmod></url>
  <url><loc>https://{HOST}/jobs/104</loc><lastmod>2026-09-20</lastmod></url>
  <url><loc>https://{HOST}/about-us</loc></url>
</urlset>"""


def page(posting):
    return (f"<html><head><script type='application/ld+json'>{json.dumps(posting)}</script>"
            "</head><body>job</body></html>")


ANALYST = {"@context": "https://schema.org", "@type": "JobPosting", "title": "Pricing Analyst",
           "datePosted": "2026-10-09", "validThrough": "2026-11-30T00:00:00",
           "employmentType": ["FULL_TIME"], "description": "<p>Price lanes &amp; quotes.</p>",
           "identifier": {"@type": "PropertyValue", "value": "P-102"},
           "jobLocation": {"@type": "Place", "address": {"addressLocality": "Leeds",
                                                         "addressRegion": "England",
                                                         "addressCountry": {"name": "United Kingdom"}}},
           "baseSalary": {"currency": "GBP", "value": {"minValue": 40000, "maxValue": 48000,
                                                       "unitText": "YEAR"}}}
REMOTE = {"@graph": [{"@type": "Organization", "name": "Acme"},
                     {"@type": "JobPosting", "Title": "Demand Planner", "DatePosted": "2026-10-01",
                      "jobLocationType": "TELECOMMUTE",
                      "applicantLocationRequirements": {"@type": "Country", "name": "United Kingdom"}}]}


def site(web):
    web.robots[HOST] = ROBOTS
    web.routes[f"{HOST}/sitemap_index.xml"] = (INDEX, None)
    web.routes[f"{HOST}/sitemap-jobs.xml"] = (JOBS, None)
    web.routes["P-102"] = (page(ANALYST), None)
    web.routes["P-101"] = (page(REMOTE), None)
    web.routes["P-103"] = ("<html>no structured data</html>", None)
    web.routes["/jobs/104"] = (page({**ANALYST, "title": "Route Planner", "identifier": "104"}), None)


def test_job_pages_come_from_the_sitemaps_newest_first(web):
    site(web)
    pages = careersite.job_pages(HOST)
    assert [u.rsplit("/", 2)[-2] if "P-" in u else u.rsplit("/", 1)[-1] for u, _ in pages] == [
        "P-102", "P-103", "P-101", "104"]
    assert not any("elsewhere" in u for u, _ in web.calls)          # another host's sitemap is not read


def test_each_page_is_read_for_its_jobposting(web):
    site(web)
    report: dict = {}
    analyst, planner, route = careersite.fetch(HOST, report=report)
    assert analyst.title == "Pricing Analyst" and analyst.id == "cs-P-102"
    assert analyst.locations == ["Leeds, England, United Kingdom"] and analyst.posted == "2026-10-09"
    assert analyst.deadline == "2026-11-30" and analyst.compensation == "GBP 40,000-48,000 year"
    assert analyst.description == "Price lanes & quotes." and analyst.employment_type == "FULL_TIME"
    assert planner.title == "Demand Planner" and planner.workplace == "remote"
    assert planner.locations == ["Remote, United Kingdom"] and planner.remote is True
    assert route.id == "cs-104"
    assert report["pages_read"] == 4 and list(report["page_errors"]) == [
        f"https://{HOST}/us/en/job/P-103/warehouse-operative"]


def test_a_query_skips_pages_whose_address_names_another_job(web):
    site(web)
    pages = [u for u, _ in careersite.job_pages(HOST, queries=["pricing analyst"])]
    assert pages == [f"https://{HOST}/us/en/job/P-102/pricing-analyst", f"https://{HOST}/jobs/104"]


def test_a_limit_and_a_skip_keep_a_large_site_to_a_few_pages(web):
    site(web)
    jobs = careersite.fetch(HOST, limit=1, skip=lambda url: "P-102" in url)
    assert [j.title for j in jobs] == []                        # P-103 is next, and has none
    assert len([u for u, _ in web.calls if "/job" in u]) == 1


def test_the_sites_robots_must_allow_it_and_its_wishes_are_kept(web):
    site(web)
    web.robots[HOST] = (200, "User-agent: *\nDisallow: /\n")
    with pytest.raises(RobotsDisallowed):
        careersite.fetch(HOST)
    web.robots[HOST] = (200, "User-agent: *\nAllow: /\nContent-Signal: ai-input=no\n")
    with pytest.raises(RobotsDisallowed, match="AI input"):
        careersite.fetch(HOST)
    web.robots[HOST] = (503, "")                                 # unreadable: not read
    with pytest.raises(RobotsDisallowed):
        careersite.fetch(HOST)


def test_a_site_with_no_job_pages_is_an_error(web):
    web.robots[HOST] = (200, "User-agent: *\nAllow: /\n")
    web.routes[f"{HOST}/sitemap.xml"] = (f"<urlset><url><loc>https://{HOST}/about</loc></url></urlset>", None)
    with pytest.raises(BoardError):
        careersite.fetch(HOST)


def test_fetch_reads_a_careers_site_named_as_one(web):
    site(web)
    jobs = openroles.fetch(f"careersite:{HOST}", query="pricing analyst")
    assert [j.title for j in jobs] == ["Pricing Analyst"]


PLANNER = '{"@type": "JobPosting", "title": "Demand Planner", "description": "Plan the week.\nForecast the month."}'
# The same posting as strictly valid JSON, so each case below fails on its own fault alone.
FLAT = PLANNER.replace("\n", " ")


@pytest.mark.parametrize("why,script", [
    ("a line break inside a string", f'<script type="application/ld+json">{PLANNER}</script>'),
    ("a type written without quotes", f"<script type=application/ld+json>{FLAT}</script>"),
    ("other attributes around the type", f"<script id=jp type='application/ld+json' nonce=x>{FLAT}</script>"),
    ("comment lines around it", f'<script type="application/ld+json">\n<!--\n{FLAT}\n-->\n</script>'),
    ("CDATA lines around it", f'<script type="application/ld+json">\n//<![CDATA[\n{FLAT}\n//]]>\n</script>'),
    ("the whole script entity-encoded", f'<script type="application/ld+json">{html.escape(FLAT)}</script>'),
    ("a semicolon after it", f'<script type="application/ld+json">{FLAT};</script>'),
])
def test_a_jobposting_is_read_however_the_page_writes_its_script(why, script):
    """A strict JSON reader found no posting on any of these pages, so the site read as
    having none."""
    found = careersite.postings(f"<html><head>{script}</head></html>")
    assert [p["title"] for p in found] == ["Demand Planner"], why
    assert found[0]["description"].startswith("Plan the week."), why


def test_a_script_that_is_not_a_jobposting_still_gives_nothing():
    for script in ('<script type="application/ld+json">{"@type": "JobPosting", "title": </script>',
                   '<script type="application/ld+jsonp">' + PLANNER + "</script>",
                   '<script type="text/javascript">var j = ' + PLANNER + "</script>",
                   '<script type="application/ld+json">not json</script>'):
        assert careersite.postings(script) == [], script


def test_a_script_wrapped_in_a_great_many_comment_lines_is_read_in_linear_time():
    """Dropping framing lines one at a time from the front took 20 seconds here, and a
    5 MB page could hold one read for many minutes. The bound is generous; the fixed
    reader takes a small fraction of it."""
    import time
    framing = "//\n" * 200_000
    for body, want in ((FLAT, ["Demand Planner"]), ("{oops", [])):
        page = f'<script type="application/ld+json"><!--\n{framing}{body}\n{framing}--></script>'
        start = time.perf_counter()
        found = careersite.postings(page)
        assert time.perf_counter() - start < 2.0
        assert [p["title"] for p in found] == want


def test_a_page_of_script_tags_that_never_close_is_read_in_linear_time():
    """An opening tag with no closing one after it, or a "<script" with no ">" after it,
    sent the scan to the end of the page again for each one: 280 kB of the first took 30
    seconds, and a page of 5 MB, the most a careers page is read to, could hold one read for
    hours. The first two pages here took seconds each; every one now takes a fraction of
    the bound."""
    import time
    opener = '<script type="application/ld+json">'
    for page in (opener * 3_000, "<script a" * 6_000,
                 opener * 140_000, "<script a" * 550_000, "<script a" * 550_000 + ">",
                 "<script a" * 550_000 + f">{opener}{FLAT}</script>"):
        start = time.perf_counter()
        found = careersite.postings(page)
        assert time.perf_counter() - start < 1.0, page[:40]
    assert [p["title"] for p in found] == ["Demand Planner"]


def test_the_scripts_found_are_the_ones_one_regular_expression_found():
    """The scan replaced a single regular expression that was quadratic on hostile pages.
    On pages built from the pieces that decide what it matched, it finds the same scripts:
    case, a type written several ways, "<scripts", a type in another attribute, a closing
    tag with a space in it, and characters whose lower case is longer than they are."""
    import random
    import re
    whole = re.compile(r"<script\b[^>]*?\btype\s*=\s*[\"']?application/ld\+json\b[\"']?[^>]*>(.*?)</script>",
                       re.I | re.S)
    pieces = ["<script", "<SCRIPT", "<scripts", " type=", "type", "=", " ", "\n", "'", '"', ">", "<",
              "application/ld+json", "application/ld+jsonx", "APPLICATION/LD+JSON", "</script>",
              "</SCRIPT>", "</script >", "x", "data-", "İ", "ſ", FLAT,
              "<script type=application/ld+json>"]
    rnd = random.Random(7)
    for _ in range(5_000):
        page = "".join(rnd.choice(pieces) for _ in range(rnd.randint(0, 14)))
        assert careersite._ld_scripts(page) == whole.findall(page), page


def test_a_script_nested_deeper_than_python_can_follow_gives_no_posting():
    """It raised RecursionError out of fetch(), from the JSON reader or from lower-casing
    the keys, and lost the whole board. The page's other scripts are still read."""
    import sys
    deep = sys.getrecursionlimit() + 100
    for text in ("[" * 100_000, "[" * deep + FLAT + "]" * deep, '{"a": ' * deep + FLAT + "}" * deep):
        page = (f'<script type="application/ld+json">{text}</script>'
                f'<script type="application/ld+json">{FLAT}</script>')
        assert [p["title"] for p in careersite.postings(page)] == ["Demand Planner"]


def test_a_page_whose_description_keeps_its_line_breaks_is_a_role(web):
    site(web)
    lead = PLANNER.replace("Demand Planner", "Planning Lead")
    web.routes["P-103"] = (f'<script type="application/ld+json">{lead}</script>', None)
    report: dict = {}
    jobs = {j.title: j for j in careersite.fetch(HOST, report=report)}
    assert jobs["Planning Lead"].description == "Plan the week.\nForecast the month."
    assert report["page_errors"] == {}
