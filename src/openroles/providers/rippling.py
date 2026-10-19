"""Rippling: a company's job board, from Rippling's documented Job Board API.

Rippling publishes the API for rendering a board on a company's own careers site
(developer.rippling.com, "Job Board API", OpenAPI job-board-api-v2.yaml): GET
https://api.rippling.com/platform/api/ats/v2/board/<slug>/jobs, with no authentication
and "Rate Limit: 100 requests every 10 minutes". The listing carries no description or
date; each posting's own record (the same host, /<slug>/jobs/<id>) does, so it is
fetched only when asked for, and never more than DETAIL_CAP a board, which keeps a read
inside that limit. Only an explicit Disallow in the host's robots.txt stops a read.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Union
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text, workplace_of

HOST = "api.rippling.com"
BASE = "https://api.rippling.com/platform/api/ats/v2/board/{slug}"
PAGE_SIZE = 1000            # the documented maximum
MAX_PAGES = 5
DETAIL_CAP = 80             # under the documented 100 requests every 10 minutes

Details = Union[bool, Callable[[Job], bool]]


def _base(token: str) -> str:
    return BASE.format(slug=quote(token.strip(), safe=""))


def _items(token: str) -> list:
    why = _http.robots_refuses(HOST, [f"/platform/api/ats/v2/board/{quote(token.strip(), safe='')}/jobs"])
    if why:
        raise RobotsDisallowed(f"rippling:{token}: {why}")
    items: list = []
    for page in range(MAX_PAGES):
        data, err = _http.request(f"{_base(token)}/jobs?page={page}&pageSize={PAGE_SIZE}")
        if err or not isinstance(data, dict) or not isinstance(data.get("items"), list):
            if page == 0:
                raise BoardError(f"rippling:{token}: {failed(err, 'board name')}")
            break
        items.extend(i for i in data["items"] if isinstance(i, dict))
        if page + 1 >= int(data.get("totalPages") or 1):
            break
    return items


def exists(token: str) -> bool:
    try:
        _items(token)
        return True
    except BoardError:
        return False


def _place(loc: dict) -> str:
    city = clean(loc.get("city"))
    parts = [city, clean(loc.get("state")), clean(loc.get("country"))] if city else []
    return ", ".join(x for x in parts if x) or clean(loc.get("name"))


def _pay(detail: dict) -> str:
    for r in detail.get("payRangeDetails") or []:
        if isinstance(r, dict) and (r.get("rangeStart") is not None or r.get("rangeEnd") is not None):
            def num(v):
                return f"{v:,.0f}" if isinstance(v, (int, float)) else clean(v)
            span = "-".join(num(v) for v in (r.get("rangeStart"), r.get("rangeEnd")) if v is not None)
            return clean(f"{r.get('currency') or ''} {span} {clean(r.get('frequency')).lower().replace('_', ' ')}")
    return ""


def fetch(token: str, details: Details = False, report: Optional[dict] = None) -> List[Job]:
    """Every role on the board. `details` (False, True, or a function given the listing-level
    Job) decides whose own record is fetched for its description, date and pay."""
    out = []
    for i in _items(token):
        title, url = clean(i.get("name")), i.get("url") or ""
        if not title or not url:
            continue
        locs = [loc for loc in i.get("locations") or [] if isinstance(loc, dict)]
        places = list(dict.fromkeys(p for p in (_place(loc) for loc in locs) if p))
        kinds = {workplace_of(loc.get("workplaceType")) for loc in locs}
        workplace = kinds.pop() if len(kinds) == 1 else ""
        dept = i.get("department")
        out.append(Job(
            id=f"rp-{i.get('id')}",
            ats="rippling",
            board=token,
            title=title,
            url=url,
            location="; ".join(places),
            locations=places,
            remote=True if workplace == "remote" else (False if workplace == "onsite" else None),
            department=clean(dept.get("name")) if isinstance(dept, dict) else clean(dept),
            workplace=workplace,
        ))
    want = [j for j in out if details is True or (callable(details) and details(j))][:DETAIL_CAP]
    failed: dict = {}
    for job in want:
        detail, err = _http.request(f"{_base(token)}/jobs/{quote(job.id[3:], safe='')}")
        if err or not isinstance(detail, dict):
            failed[job.id] = err or "a posting record that was not a posting"
            continue
        desc = detail.get("description") if isinstance(detail.get("description"), dict) else {}
        body = "\n\n".join(x for x in (html_to_text(desc.get("role") or ""),
                                       html_to_text(desc.get("company") or "")) if x)
        kind = detail.get("employmentType")
        job.posted = str(detail.get("createdOn") or "")[:10]
        job.employment_type = clean(kind.get("label")) if isinstance(kind, dict) else clean(kind)
        job.compensation = _pay(detail)
        job.description = body or None
    if report is not None:
        report.update(listing_errors=[], detail_errors=failed, details_asked=len(want))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
