"""Workable: an account's published jobs, from Workable's documented public endpoint.

Workable documents GET https://www.workable.com/api/accounts/<subdomain>?details=true as
"a collection of the public jobs for an account" with no authentication
(workable.readme.io, "jobs"; help.workable.com article 115012771647). It may answer with
a redirect to apply.workable.com, which is followed only where that host's robots.txt
does not refuse it (openroles checks every redirect). Only an explicit Disallow stops a
read. The listing has no pay.

Built from Workable's documentation: when this reader was written, Workable's hosts were
rate-limiting the checks, so it has not yet been run against a live board.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text, workplace_of

HOST = "www.workable.com"
URL = "https://www.workable.com/api/accounts/{token}?details=true"


def _account(token: str) -> dict:
    slug = quote(token.strip().lower(), safe="")
    why = _http.robots_refuses(HOST, [f"/api/accounts/{slug}"])
    if why:
        raise RobotsDisallowed(f"workable:{token}: {why}")
    data, err = _http.request(URL.format(token=slug))
    if err or not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise BoardError(f"workable:{token}: {failed(err, 'account name')}")
    return data


def exists(token: str) -> bool:
    try:
        _account(token)
        return True
    except BoardError:
        return False


def fetch(token: str) -> List[Job]:
    out = []
    for j in _account(token)["jobs"]:
        if not isinstance(j, dict):
            continue
        title = clean(j.get("title"))
        url = j.get("application_url") or j.get("shortlink") or j.get("url") or ""
        if not title or not url:
            continue
        place = ", ".join(x for x in (clean(j.get("city")), clean(j.get("state")),
                                      clean(j.get("country"))) if x)
        workplace = workplace_of(j.get("workplace_type")) or ("remote" if j.get("telecommuting") else "")
        out.append(Job(
            id=f"wk-{j.get('shortcode') or j.get('code') or url.rstrip('/').rsplit('/', 1)[-1]}",
            ats="workable",
            board=token,
            title=title,
            url=url,
            location=place,
            locations=[place] if place else [],
            remote=True if workplace == "remote" else (False if workplace == "onsite" else None),
            posted=str(j.get("published_on") or j.get("created_at") or "")[:10],
            department=clean(j.get("department")),
            employment_type=clean(j.get("employment_type")),
            description=html_to_text(j.get("description") or "") or None,
            workplace=workplace,
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST, "apply.workable.com"]          # it may redirect there
