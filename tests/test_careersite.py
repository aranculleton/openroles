"""Any careers site that publishes its jobs for search engines, read from its sitemap and
each page's JobPosting. An invented site, careers.acme.example."""
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
