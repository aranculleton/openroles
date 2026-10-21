"""Gem: a company's job board, from Gem's documented Job Board API.

Gem's OpenAPI (api.gem.com/job_board/v0/openapi.json): "Most endpoints in the Job Board API
are public and do not require authentication: job board information can be read by anyone
using your job board's vanity URL path." GET .../job_board/v0/<vanity path>/job_posts/
returns every post with its body, unpaged. api.gem.com's robots.txt answers 403 (it cannot
be read), which for a documented public API is not taken for a refusal; an explicit
Disallow would be.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, as_list, as_str, clean, failed, html_to_text, ident, iso_day, workplace_of

HOST = "api.gem.com"
URL = "https://api.gem.com/job_board/v0/{path}/job_posts/"


def _posts(token: str) -> list:
    path = quote(token.strip(), safe="")
    why = _http.robots_refuses(HOST, [f"/job_board/v0/{path}/job_posts/"])
    if why:
        raise RobotsDisallowed(f"gem:{token}: {why}")
    data, err = _http.request(URL.format(path=path))
    if err or not isinstance(data, list):
        raise BoardError(f"gem:{token}: {failed(err, 'job board path')}")
    return [p for p in data if isinstance(p, dict)]


def exists(token: str) -> bool:
    try:
        _posts(token)
        return True
    except BoardError:
        return False


def fetch(token: str) -> List[Job]:
    out = []
    for p in _posts(token):
        number, title, url = ident(p.get("id")), clean(p.get("title")), as_str(p.get("absolute_url"))
        if not number or not title or not url:
            continue
        loc = p.get("location")
        primary = clean(loc.get("name")) if isinstance(loc, dict) else clean(loc)
        offices = [clean(o.get("location") or o.get("name")) for o in as_list(p.get("offices"))
                   if isinstance(o, dict)]
        places = list(dict.fromkeys(x for x in [primary, *offices] if x))
        workplace = workplace_of(p.get("location_type"))
        depts = [clean(d.get("name")) for d in as_list(p.get("departments")) if isinstance(d, dict)]
        out.append(Job(
            id=f"gm-{number}",
            ats="gem",
            board=token,
            title=title,
            url=url,
            location="; ".join(places),
            locations=places,
            remote=True if workplace == "remote" else (False if workplace == "onsite" else None),
            posted=iso_day(p.get("first_published_at"), p.get("created_at")),
            department=next((d for d in depts if d), ""),
            employment_type=clean(p.get("employment_type")).replace("_", " "),
            description=(as_str(p.get("content_plain")).strip()
                         or html_to_text(p.get("content"))) or None,
            workplace=workplace,
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
