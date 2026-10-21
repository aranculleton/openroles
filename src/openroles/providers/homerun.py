"""Homerun: a company's jobs, from the Atom feed its careers page links to.

Every Homerun careers page names its feed in its head, as
<link rel="alternate" type="application/atom+xml" href="https://feed.homerun.co/...">,
so the feed is published for anyone to read: https://feed.homerun.co/<subdomain>. Homerun
documents no public API (its API needs a key), so the feed's host must have a robots.txt
that allows it or none at all, and the reader obeys it.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text, iso_day, workplace_of
from ._xml import parse

HOST = "feed.homerun.co"


def _local(el) -> str:
    return el.tag.rsplit("}", 1)[-1].lower()


def _child(el, name):
    return next((c for c in el if _local(c) == name), None)


def _text(el, *path) -> str:
    for name in path:
        el = _child(el, name) if el is not None else None
    return clean(el.text) if el is not None and el.text else ""


def _entries(token: str) -> list:
    sub = quote(token.strip().lower(), safe="")
    ok, why = _http.robots_allows(HOST, [f"/{sub}"])
    if not ok:
        raise RobotsDisallowed(f"homerun:{token}: {why}")
    body, err = _http.request_raw(f"https://{HOST}/{sub}",
                                  accept="application/atom+xml,application/xml;q=0.9,*/*;q=0.1",
                                  limit=20_000_000)
    root = parse(body) if not err else None
    if root is None or _local(root) != "feed":
        raise BoardError(f"homerun:{token}: {failed(err, 'subdomain')}")
    return [e for e in root if _local(e) == "entry"]


def exists(token: str) -> bool:
    try:
        _entries(token)
        return True
    except BoardError:
        return False


def fetch(token: str) -> List[Job]:
    out = []
    for e in _entries(token):
        title = _text(e, "title")
        link = next((c.get("href") for c in e if _local(c) == "link"
                     and c.get("rel", "alternate") == "alternate" and c.get("href")), "")
        if not title or not link:
            continue
        place = _text(e, "location", "name")
        body = next((c.text for c in e if _local(c) in ("content", "description", "summary") and c.text), "")
        out.append(Job(
            id=f"hr-{_text(e, 'id') or link.rstrip('/').rsplit('/', 1)[-1]}",
            ats="homerun",
            board=token,
            title=title,
            url=link,
            location=place,
            locations=[place] if place else [],
            remote=True if workplace_of(place) == "remote" else None,
            posted=iso_day(_text(e, "updated")),
            department=_text(e, "department", "name"),
            employment_type=_text(e, "type", "name"),
            compensation=_text(e, "salary_indication"),
            description=html_to_text(body) or None,
            workplace=workplace_of(place),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
