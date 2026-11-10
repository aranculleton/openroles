"""A board read page by page while it changes lists a posting on two pages; it comes back
once."""
import openroles
from openroles.models import Job, each_once
from openroles.providers import manatal, rippling, teamtailor


def _item(n: int) -> str:
    return (f"<item><title>Role {n}</title><link>https://acme.teamtailor.com/jobs/{n}</link>"
            f"<guid>guid-{n}</guid><description>&lt;p&gt;Role {n}.&lt;/p&gt;</description></item>")


def test_a_teamtailor_posting_pushed_onto_the_next_page_comes_back_once(web, monkeypatch):
    monkeypatch.setattr(teamtailor, "PER_PAGE", 3)
    feed = '<rss version="2.0"><channel>{}</channel></rss>'
    web.routes["offset=0"] = (feed.format("".join(_item(n) for n in (1, 2, 3))), None)
    # A posting was added at the top between the two requests: 3 is listed again.
    web.routes["offset=3"] = (feed.format("".join(_item(n) for n in (3, 4))), None)
    jobs = teamtailor.fetch("acme")
    assert [j.id for j in jobs] == ["tt-guid-1", "tt-guid-2", "tt-guid-3", "tt-guid-4"]


def test_a_manatal_posting_on_two_pages_comes_back_once(web):
    row = {"id": 2, "hash": "h2", "position_name": "Analyst"}
    web.routes["career-page/acme/jobs/?page_size=100"] = {
        "results": [{"id": 1, "hash": "h1", "position_name": "Planner"}, row],
        "next": "https://api.manatal.com/open/v3/career-page/acme/jobs/?page=2"}
    web.routes["jobs/?page=2"] = {"results": [row, {"id": 3, "hash": "h3", "position_name": "Lead"}],
                                  "next": None}
    assert [j.id for j in manatal.fetch("acme")] == ["mn-1", "mn-2", "mn-3"]


def test_a_rippling_posting_on_two_pages_is_read_and_asked_about_once(web):
    def item(n):
        return {"id": f"{n}", "name": f"Role {n}", "url": f"https://ats.rippling.com/acme/jobs/{n}"}
    web.routes["/jobs?page=0"] = {"items": [item(1), item(2)], "totalPages": 2}
    web.routes["/jobs?page=1"] = {"items": [item(2), item(3)], "totalPages": 2}
    web.routes["/acme/jobs/"] = {"description": {"role": "<p>Role.</p>"}}
    jobs = rippling.fetch("acme", details=True)
    assert [j.id for j in jobs] == ["rp-1", "rp-2", "rp-3"]
    assert len([u for u, _ in web.calls if "/acme/jobs/" in u]) == 3


def test_fetch_never_gives_one_id_twice(web, monkeypatch):
    one = Job(id="gh-1", ats="greenhouse", board="acme", title="Analyst", url="https://x/1")
    monkeypatch.setattr("openroles.providers.greenhouse.fetch", lambda token: [one, one])
    assert openroles.fetch("greenhouse:acme") == [one]
    assert each_once([one, Job(id="gh-2", ats="greenhouse", board="acme", title="B", url="u"), one])[1].id == "gh-2"
