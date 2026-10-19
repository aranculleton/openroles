"""Manatal: a company's career page, from Manatal's documented Career Page Public API.

developers.manatal.com: "Release of the Career Page Public API"; its OpenAPI declares no
security. GET https://api.manatal.com/open/v3/career-page/<slug>/jobs/, paged, each job
with its description. The listing has no date, department or link, so the link is the
career page's own address for the job. Only an explicit Disallow stops a read.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text, workplace_of

HOST = "api.manatal.com"
BASE = "https://api.manatal.com/open/v3/career-page/{slug}/jobs/"
PAGE = "https://www.careers-page.com/{slug}/job/{hash}"
MAX_PAGES = 20


def _results(token: str) -> list:
    slug = quote(token.strip(), safe="")
    why = _http.robots_refuses(HOST, [f"/open/v3/career-page/{slug}/jobs/"])
    if why:
        raise RobotsDisallowed(f"manatal:{token}: {why}")
    out: list = []
    url = f"{BASE.format(slug=slug)}?page_size=100"
    for n in range(MAX_PAGES):
        data, err = _http.request(url)
        if err or not isinstance(data, dict) or not isinstance(data.get("results"), list):
            if n == 0:
                raise BoardError(f"manatal:{token}: {failed(err, 'career page name')}")
            break
        out.extend(r for r in data["results"] if isinstance(r, dict))
        nxt = data.get("next")
        if not nxt or not str(nxt).startswith("https://api.manatal.com/"):
            break
        url = nxt
    return out


def exists(token: str) -> bool:
    try:
        _results(token)
        return True
    except BoardError:
        return False


def fetch(token: str) -> List[Job]:
    out = []
    for r in _results(token):
        title, ident = clean(r.get("position_name")), r.get("hash") or r.get("id")
        if not title or not ident:
            continue
        place = ", ".join(x for x in (clean(r.get("city")), clean(r.get("state")),
                                      clean(r.get("country"))) if x) or clean(r.get("location_display"))
        remote = r.get("is_remote") is True
        out.append(Job(
            id=f"mn-{r.get('id') or ident}",
            ats="manatal",
            board=token,
            title=title,
            url=PAGE.format(slug=quote(token.strip(), safe=""), hash=quote(str(ident), safe="")),
            location=place,
            locations=[place] if place else [],
            remote=True if remote else None,
            employment_type=clean(r.get("contract_details")).replace("_", " "),
            description=html_to_text(str(r.get("description") or "")) or None,
            workplace="remote" if remote else workplace_of(place),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
