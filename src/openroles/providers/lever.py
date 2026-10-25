"""Lever: one request a board, every posting's description included.

Lever hosts boards in two regions. A board the global API does not know is tried on
the EU one before it is called missing. The postings API is documented as public, so
only an explicit Disallow in a host's robots.txt stops a read there, and the
Crawl-delay both hosts declare is kept.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Tuple
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
    html_or_plain,
    html_to_text,
    ident,
    iso_day,
    pay,
    workplace_of,
)

HOSTS = ("https://api.lever.co", "https://api.eu.lever.co")
PATH = "/v0/postings/{token}?mode=json"


def _epoch_ms_date(ms) -> str:
    """Lever's createdAt (milliseconds since 1970) as YYYY-MM-DD, or "" (0 among them)."""
    try:
        return iso_day(dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).date().isoformat())
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _postings(token: str) -> Tuple[Optional[list], str]:
    why, refused = "", []
    for host in HOSTS:
        no = _http.robots_refuses(host.split("//", 1)[1], [f"/v0/postings/{quote(token, safe='')}"])
        if no:
            refused.append(no)
            continue
        data, err = _http.request(host + PATH.format(token=quote(token, safe="")))
        # Lever answers an unknown board with {"ok": false, ...}, not a 404.
        if isinstance(data, list):
            return data, ""
        # The global region's answer explains more than the EU's 404 does.
        why = why or err or "not a posting list"
    if len(refused) == len(HOSTS):
        raise RobotsDisallowed(f"lever:{token}: {refused[0]}")
    return None, why


def exists(token: str) -> bool:
    try:
        return _postings(token)[0] is not None
    except RobotsDisallowed:
        return False


def _description(j: dict) -> Optional[str]:
    """The intro and body, then every list (requirements, responsibilities), then the closing
    text.

    Each part is read from its HTML field (`description`, `lists`, `additional`), so that
    what no reader sees is left out as it is for every other system, and from its plain-text
    field (`descriptionPlain`, `additionalPlain`) only where Lever sent no HTML: the plain
    fields keep a comment or a hidden element's text. `description` holds the intro and the
    body together, and the requirements live in `lists`.
    """
    parts = [html_or_plain(j.get("description"), j.get("descriptionPlain"))]
    for block in as_list(j.get("lists")):
        if not isinstance(block, dict):
            continue
        body = html_to_text(block.get("content"))
        head = clean(block.get("text"))
        if head or body:
            parts.append(f"{head}\n{body}".strip())
    parts.append(html_or_plain(j.get("additional"), j.get("additionalPlain")))
    text = "\n\n".join(p for p in parts if p)
    return text or None


def _pay(j: dict) -> str:
    r = j.get("salaryRange")
    if not isinstance(r, dict) or (r.get("min") is None and r.get("max") is None):
        return ""
    lo, hi = r.get("min"), r.get("max")
    one = lo if lo is not None else hi
    span = f"{lo:,}-{hi:,}" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) \
        else str(one) if isinstance(one, (int, float)) and not isinstance(one, bool) else clean(one)
    unit = clean(r.get("interval")).replace("-", " ")
    return clean(f"{clean(r.get('currency'))} {span} {unit}")


def _salary(j: dict) -> dict:
    r = j.get("salaryRange") if isinstance(j.get("salaryRange"), dict) else {}
    return pay(r.get("min"), r.get("max"), r.get("currency"), r.get("interval"))


def fetch(token: str) -> List[Job]:
    data, why = _postings(token)
    if data is None:
        raise BoardError(f"lever:{token}: not a posting list ({why}); probably a wrong board name")
    out = []
    for j in data:
        if not isinstance(j, dict):
            continue
        number, title = ident(j.get("id")), clean(j.get("text"))
        if not number or not title:
            continue
        cats = as_dict(j.get("categories"))
        location = clean(cats.get("location"))
        # Lever's docs do not say what an allLocations entry is: a name, or an object.
        every = [clean(x.get("location") or x.get("name")) if isinstance(x, dict) else clean(x)
                 for x in as_list(cats.get("allLocations"))]
        every = list(dict.fromkeys(x for x in every if x))
        workplace = clean(j.get("workplaceType")).lower()
        out.append(Job(
            id=f"lv-{number}",
            ats="lever",
            board=token,
            title=title,
            url=as_str(j.get("hostedUrl")),
            location=location,
            locations=every or ([location] if location else []),
            remote=True if workplace == "remote" else (False if workplace in ("on-site", "onsite") else None),
            posted=_epoch_ms_date(j.get("createdAt")),
            department=clean(cats.get("department") or cats.get("team")),
            employment_type=clean(cats.get("commitment")),
            compensation=_pay(j),
            description=_description(j),
            **_salary(j),
            workplace=workplace_of(workplace),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [h.split("//", 1)[1] for h in HOSTS]
