"""JazzHR: a company's open jobs as the XML feed its careers-page integration offers.

JazzHR's help ("Integrate JazzHR with Your Career Page/Website - Advanced Methods")
describes https://app.jazz.co/feeds/export/jobs/<subdomain>, listing jobs with status
Open that are exposed on the careers website, "generated once per day and is subject to
rate limiting". So a board is one request, answered from the ETag cache when it is read
again in a process and the host sends one. Only an explicit Disallow in app.jazz.co's
robots.txt stops a read. The feed carries no date per job and no pay.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, failed, html_to_text, workplace_of
from ._xml import parse, text_of

HOST = "app.jazz.co"
URL = "https://app.jazz.co/feeds/export/jobs/{token}"


def _jobs(token: str):
    path = f"/feeds/export/jobs/{quote(token.strip(), safe='')}"
    why = _http.robots_refuses(HOST, [path])
    if why:
        raise RobotsDisallowed(f"jazzhr:{token}: {why}")
    body, err = _http.request_raw(URL.format(token=quote(token.strip(), safe="")),
                                  accept="application/xml,text/xml;q=0.9,*/*;q=0.1",
                                  limit=30_000_000)
    root = parse(body) if not err else None
    if root is None or root.tag != "jobs":
        raise BoardError(f"jazzhr:{token}: {failed(err, 'subdomain')}")
    return root.findall("job")


def exists(token: str) -> bool:
    try:
        _jobs(token)
        return True
    except BoardError:
        return False


def fetch(token: str) -> List[Job]:
    out = []
    for j in _jobs(token):
        title, url = text_of(j, "title"), text_of(j, "url")
        status = text_of(j, "status").lower()
        if not title or not url or (status and status != "open"):
            continue
        place = ", ".join(x for x in (text_of(j, "city"), text_of(j, "state"), text_of(j, "country")) if x)
        out.append(Job(
            id=f"jz-{text_of(j, 'id')}",
            ats="jazzhr",
            board=token,
            title=title,
            url=url,
            location=place,
            locations=[place] if place else [],
            remote=True if workplace_of(place) == "remote" else None,
            department=text_of(j, "department"),
            employment_type=text_of(j, "type"),
            description=html_to_text(j.findtext("description") or "") or None,
            workplace=workplace_of(place),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
