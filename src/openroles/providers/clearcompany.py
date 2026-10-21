"""ClearCompany: a careers site's jobs, from the API its own careers widget reads.

A ClearCompany careers page loads career-site.js?siteId=<id>, which reads
https://careers-api.clearcompany.com/v1/<id>. The site id is printed in the page for every
visitor; no key is needed. ClearCompany documents no public API, so the host's robots.txt
must allow the path (it disallows only /internal/), and the reader obeys it.
"""
from __future__ import annotations

import re
from typing import List
from urllib.parse import quote

from .. import _http
from ..models import (
    BoardError,
    Job,
    RobotsDisallowed,
    as_list,
    as_str,
    clean,
    failed,
    html_to_text,
    ident,
    iso_day,
    pay,
    workplace_of,
)

HOST = "careers-api.clearcompany.com"
SITE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def _results(token: str) -> list:
    site = token.strip().lower()
    if not SITE_ID.match(site):
        raise BoardError(f"clearcompany:{token}: not a ClearCompany site id (a GUID from "
                         "career-site.js?siteId=... on the careers page)")
    ok, why = _http.robots_allows(HOST, [f"/v1/{site}"])
    if not ok:
        raise RobotsDisallowed(f"clearcompany:{token}: {why}")
    data, err = _http.request(f"https://{HOST}/v1/{quote(site, safe='')}")
    if err or not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise BoardError(f"clearcompany:{token}: {failed(err, 'site id')}")
    results = [r for r in data["results"] if isinstance(r, dict)]
    total = data.get("totalCount")
    if isinstance(total, int) and total > len(results):
        import logging
        logging.getLogger("openroles").warning(
            "clearcompany:%s: the site lists %d jobs and its first page gave %d", token, total, len(results))
    return results


def exists(token: str) -> bool:
    try:
        _results(token)
        return True
    except BoardError:
        return False


def _pay(r: dict) -> str:
    lo, hi = r.get("salaryRangeLow"), r.get("salaryRangeHigh")
    if not lo and not hi:
        return ""

    def num(v):
        try:
            return f"{float(v):,.0f}"
        except (TypeError, ValueError, OverflowError):
            return clean(v)
    span = "-".join(num(v) for v in (lo, hi) if v)
    return clean(f"{span} {clean(r.get('salaryType')).lower()}")


def fetch(token: str) -> List[Job]:
    out = []
    for r in _results(token):
        number, title, url = ident(r.get("id")), clean(r.get("positionTitle")), as_str(r.get("applyLink"))
        if not number or not title or not url:
            continue
        places, remote = [], False
        for loc in as_list(r.get("locations")):
            if not isinstance(loc, dict):
                continue
            remote = remote or loc.get("isRemote") is True
            place = ", ".join(x for x in (clean(loc.get("city")), clean(loc.get("subdivision")),
                                          clean(loc.get("country"))) if x)
            if place:
                places.append(f"Remote, {place}" if loc.get("isRemote") is True and "remote" not in place.lower()
                              else place)
        places = list(dict.fromkeys(places)) or ([clean(r.get("location"))] if clean(r.get("location")) else [])
        out.append(Job(
            id=f"cc-{number}",
            ats="clearcompany",
            board=token,
            title=title,
            url=re.sub(r"/apply/?$", "", url),
            location="; ".join(places),
            locations=places,
            remote=True if remote and all("remote" in p.lower() for p in places) else None,
            posted=iso_day(r.get("postedDate"), r.get("openDate")),
            department=clean(r.get("departmentName")),
            compensation=_pay(r),
            **pay(r.get("salaryRangeLow"), r.get("salaryRangeHigh"), "", r.get("salaryType")),
            description=html_to_text(r.get("description")) or None,
            workplace="remote" if remote and all("remote" in p.lower() for p in places) else workplace_of(*places),
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
