"""Gem, Polymer, Manatal, Homerun and ClearCompany, in the same shape as the rest."""
import pytest

from openroles import Board, BoardError, RobotsDisallowed
from openroles.discover import parse
from openroles.providers import clearcompany, gem, homerun, manatal, polymer

SITE = "0b9c1f7e-1111-4c2b-9f00-000000000001"


def test_gem_reads_its_job_posts(web):
    web.routes["api.gem.com/job_board/v0/acme/job_posts/"] = [
        {"id": "p1", "title": "Data Analyst", "absolute_url": "https://jobs.gem.com/acme/p1",
         "location": {"name": "Leeds"}, "location_type": "hybrid",
         "offices": [{"name": "North", "location": "Leeds, United Kingdom"}],
         "departments": [{"id": 1, "name": "Analytics"}], "employment_type": "full_time",
         "first_published_at": "2026-09-01T00:00:00Z", "content_plain": "Model demand."}]
    [job] = gem.fetch("acme")
    assert job.id == "gm-p1" and job.locations == ["Leeds", "Leeds, United Kingdom"]
    assert job.workplace == "hybrid" and job.posted == "2026-09-01" and job.department == "Analytics"
    assert job.employment_type == "full time" and job.description == "Model demand."


def test_gem_unreadable_robots_is_no_refusal_but_a_disallow_is(web):
    web.routes["api.gem.com/job_board/v0/acme/job_posts/"] = []
    web.robots["api.gem.com"] = (403, "")
    assert gem.fetch("acme") == []
    web.robots["api.gem.com"] = (200, "User-agent: *\nDisallow: /job_board/\n")
    with pytest.raises(RobotsDisallowed):
        gem.fetch("acme")


def test_polymer_pages_and_reads_records_only_when_asked(web):
    web.routes["organizations/acme/jobs?page=1"] = {
        "items": [{"id": 7, "title": "Planner", "job_post_url": "https://jobs.polymer.co/acme/7",
                   "city": "Leeds", "country": "United Kingdom", "remoteness_pretty": "Remote",
                   "kind_pretty": "Full-time", "published_at": "2026-10-02T00:00:00Z",
                   "job_category_name": "Ops", "salary_pretty": "£40k - £45k"}],
        "meta": {"is_last": True}}
    web.routes["organizations/acme/jobs/7"] = {"id": 7, "description": "<p>Plan.</p>",
                                               "department": "Operations"}
    [job] = polymer.fetch("acme")
    assert job.description is None and job.workplace == "remote" and job.compensation == "£40k - £45k"
    [job] = polymer.fetch("acme", details=True)
    assert job.description == "Plan." and job.department == "Operations"
    web.routes["organizations/nobody/jobs"] = ({"errors": {"organization": ["could not be found"]}}, "HTTP 422")
    with pytest.raises(BoardError):
        polymer.fetch("nobody")


def test_manatal_follows_its_pages_on_its_own_host_only(web):
    web.routes["career-page/acme/jobs/?page_size=100"] = {
        "results": [{"id": 1, "hash": "h1", "position_name": "Analyst", "city": "Leeds",
                     "country": "United Kingdom", "is_remote": False, "description": "<p>A.</p>",
                     "contract_details": "full_time"}],
        "next": "https://api.manatal.com/open/v3/career-page/acme/jobs/?page=2"}
    web.routes["career-page/acme/jobs/?page=2"] = {
        "results": [{"id": 2, "hash": "h2", "position_name": "Engineer", "is_remote": True}],
        "next": "https://evil.example/next"}
    one, two = manatal.fetch("acme")
    assert one.url == "https://www.careers-page.com/acme/job/h1" and one.employment_type == "full time"
    assert two.workplace == "remote" and not any("evil" in u for u, _ in web.calls)


def test_homerun_reads_its_atom_feed(web):
    web.routes["feed.homerun.co/acme"] = ("""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Office Manager</title>
    <link rel="alternate" href="https://acme.homerun.co/office-manager"/>
    <id>job_1</id>
    <updated>2026-10-04T09:00:00Z</updated>
    <content type="html">&lt;p&gt;Run the office.&lt;/p&gt;</content>
    <department><name>People</name></department>
    <location><name>Leeds</name></location>
    <type><name>Full-time</name></type>
    <salary_indication>£30k</salary_indication>
  </entry>
</feed>""", None)
    [job] = homerun.fetch("acme")
    assert job.id == "hr-job_1" and job.url == "https://acme.homerun.co/office-manager"
    assert job.location == "Leeds" and job.department == "People" and job.compensation == "£30k"
    assert job.posted == "2026-10-04" and job.description == "Run the office."


def test_homerun_needs_its_robots_to_allow_it(web):
    web.robots["feed.homerun.co"] = (503, "")
    with pytest.raises(RobotsDisallowed):
        homerun.fetch("acme")


def test_clearcompany_reads_a_site_by_its_id(web):
    web.routes[f"careers-api.clearcompany.com/v1/{SITE}"] = {
        "results": [{"id": 55, "positionTitle": "Recruiter", "description": "<p>Hire.</p>",
                     "postedDate": "2026-10-01T00:00:00", "departmentName": "People",
                     "locations": [{"city": "Leeds", "country": "United Kingdom", "isRemote": False}],
                     "applyLink": "https://jobs.clearcompany.com/careers/jobs/55/apply",
                     "salaryRangeLow": 30000, "salaryRangeHigh": 35000, "salaryType": "Annual"}],
        "totalCount": 1}
    [job] = clearcompany.fetch(SITE)
    assert job.id == "cc-55" and job.url == "https://jobs.clearcompany.com/careers/jobs/55"
    assert job.compensation == "30,000-35,000 annual" and job.locations == ["Leeds, United Kingdom"]
    with pytest.raises(BoardError, match="site id"):
        clearcompany.fetch("acme")


@pytest.mark.parametrize("url,board", [
    ("https://jobs.gem.com/acme/p1", Board("gem", "acme")),
    ("https://jobs.polymer.co/acme/7", Board("polymer", "acme")),
    ("https://www.careers-page.com/acme/job/h1", Board("manatal", "acme")),
    ("https://acme.homerun.co/office-manager", Board("homerun", "acme")),
    (f"https://careers-content.clearcompany.com/js/v1/career-site.js?siteId={SITE}", Board("clearcompany", SITE)),
])
def test_their_boards_are_found_from_a_link(url, board):
    assert parse(url) == board
