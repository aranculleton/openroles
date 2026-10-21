"""Greenhouse: one request a board, every posting's description included.

The Job Board API is documented as public, so only an explicit Disallow in
boards-api.greenhouse.io's robots.txt stops a read.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import (
    BoardError,
    Job,
    RobotsDisallowed,
    as_dict,
    as_list,
    as_str,
    clean,
    html_to_text,
    ident,
    iso_day,
    workplace_of,
)

HOST = "boards-api.greenhouse.io"
# `content=true` returns every posting's body, departments and offices in the same request.
URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
META = "https://boards-api.greenhouse.io/v1/boards/{token}"


def _refused(token: str) -> str:
    return _http.robots_refuses(HOST, [f"/v1/boards/{quote(token, safe='')}"])


def exists(token: str) -> bool:
    if _refused(token):
        return False
    data, err = _http.request(META.format(token=quote(token, safe="")))
    return not err and isinstance(data, dict) and "name" in data


def fetch(token: str) -> List[Job]:
    why = _refused(token)
    if why:
        raise RobotsDisallowed(f"greenhouse:{token}: {why}")
    data, err = _http.request(URL.format(token=quote(token, safe="")))
    if err:
        raise BoardError(f"greenhouse:{token}: the board did not answer ({err})")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise BoardError(f"greenhouse:{token}: no jobs list in the response")
    out = []
    for j in data["jobs"]:
        if not isinstance(j, dict):
            continue
        number, title = ident(j.get("id")), clean(j.get("title"))
        if not number or not title:
            continue
        location = clean(as_dict(j.get("location")).get("name"))
        depts = [clean(d.get("name")) for d in as_list(j.get("departments")) if isinstance(d, dict)]
        # A posting's location can be "Hybrid" or a time zone, with where the job is
        # recorded only under its offices; a filter by place read the first alone.
        offices = [clean(o.get("location") or o.get("name")) for o in as_list(j.get("offices"))
                   if isinstance(o, dict)]
        every = list(dict.fromkeys(x for x in [location, *offices] if x))
        out.append(Job(
            id=f"gh-{number}",
            ats="greenhouse",
            board=token,
            title=title,
            url=as_str(j.get("absolute_url")),
            location=location,
            locations=every,
            remote=True if "remote" in location.lower() else None,
            # First published, not updated: Greenhouse bumps updated_at on every edit,
            # so a role first posted months ago would read as new.
            posted=iso_day(j.get("first_published"), j.get("updated_at")),
            department=next((d for d in depts if d), ""),
            deadline=iso_day(j.get("application_deadline")),
            description=html_to_text(j.get("content")) or None,
            workplace=workplace_of(location),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
