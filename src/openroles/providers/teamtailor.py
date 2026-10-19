"""Teamtailor: a careers site's public RSS feed, a hundred roles a page.

Teamtailor documents the feed as public: "Go to the main jobs page of your careers site
and add .rss ... Note that all of the data is publicly available"
(support.teamtailor.com, article 11171756). A careers site lives at
<name>.teamtailor.com or on the employer's own domain, so a token is either the name
or the site's host. Only an explicit Disallow in the site's robots.txt stops a read.
"""
from __future__ import annotations

import email.utils
from typing import List, Optional
from urllib.parse import urlsplit

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, failed, html_to_text, workplace_of
from ._xml import parse, text_of

NS = "{https://teamtailor.com/locations}"
PER_PAGE = 100
MAX_PAGES = 20          # 2,000 roles: past that a careers site is not one employer's board
# remoteStatus as the feed writes it.
_WORKPLACE = {"fully": "remote", "hybrid": "hybrid", "none": "onsite"}


def host_of(token: str) -> str:
    """The careers site's host: "acme" is acme.teamtailor.com; a host or URL is itself."""
    t = (token or "").strip()
    if "//" in t:
        t = urlsplit(t).netloc
    t = t.split("/", 1)[0].lower()
    return t if "." in t else f"{t}.teamtailor.com"


def _date(value: str) -> str:
    try:
        return email.utils.parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, IndexError):
        return ""


def _page(host: str, offset: int):
    body, err = _http.request_raw(f"https://{host}/jobs.rss?per_page={PER_PAGE}&offset={offset}",
                                  accept="application/rss+xml,application/xml;q=0.9,*/*;q=0.1",
                                  limit=20_000_000)
    if err:
        return None, err
    root = parse(body)
    channel = root.find("channel") if root is not None and root.tag == "rss" else None
    if channel is None:
        return None, "not a Teamtailor jobs feed"
    return channel.findall("item"), ""


def _items(token: str) -> List:
    host = host_of(token)
    why = _http.robots_refuses(host, ["/jobs.rss"])
    if why:
        raise RobotsDisallowed(f"teamtailor:{token}: {why}")
    items: list = []
    for n in range(MAX_PAGES):
        got, err = _page(host, n * PER_PAGE)
        if got is None:
            if n == 0:
                raise BoardError(f"teamtailor:{token}: {host}: {failed(err, 'careers site')}")
            break
        items.extend(got)
        if len(got) < PER_PAGE:
            break
    return items


def exists(token: str) -> bool:
    try:
        host = host_of(token)
        if _http.robots_refuses(host, ["/jobs.rss"]):
            return False
        return _page(host, 0)[0] is not None
    except BoardError:
        return False


def _place(loc) -> str:
    city, country = text_of(loc, f"{NS}city"), text_of(loc, f"{NS}country")
    if city:
        return ", ".join(x for x in (city, country) if x)
    return text_of(loc, f"{NS}name") or country


def fetch(token: str) -> List[Job]:
    out = []
    for item in _items(token):
        title, url = text_of(item, "title"), text_of(item, "link")
        if not title or not url:
            continue
        places = [p for p in (_place(loc) for loc in item.findall(f"{NS}locations/{NS}location")) if p]
        places = list(dict.fromkeys(places))
        status = text_of(item, "remoteStatus").lower()
        workplace = _WORKPLACE.get(status, "")
        ident: Optional[str] = text_of(item, "guid") or url.rstrip("/").rsplit("/", 1)[-1]
        out.append(Job(
            id=f"tt-{ident}",
            ats="teamtailor",
            board=token,
            title=title,
            url=url,
            location="; ".join(places),
            locations=places,
            remote=True if workplace == "remote" else (False if workplace == "onsite" else None),
            posted=_date(text_of(item, "pubDate")),
            department=text_of(item, f"{NS}department"),
            description=html_to_text(item.findtext("description") or "") or None,
            workplace=workplace or workplace_of(*places),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [host_of(token)]
