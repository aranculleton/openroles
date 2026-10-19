"""Recruitee: a company's published offers, from its Careers Site API.

Documented for showing "a list of job offers ... on your custom website"
(docs.recruitee.com, "Careers Site API"): GET https://<company>.recruitee.com/api/offers/.
It needs no key today, but Recruitee's docs say each employer's own token
(X-Careers-Sites-Token) is required from 10 February 2027, after which a call without
one answers 401. A board that answers 401 is reported as needing that token, not as
missing. Only an explicit Disallow in the host's robots.txt stops a read.
"""
from __future__ import annotations

from typing import List

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text

URL = "https://{host}/api/offers/"
NEEDS_TOKEN = ("Recruitee asks for the employer's own Careers Site API token from 10 February "
               "2027, and openroles has none, so this board cannot be read")


def _host(token: str) -> str:
    """"acme" is acme.recruitee.com; a careers site on the employer's own domain, which
    serves the same feed, is itself."""
    t = (token or "").strip().lower()
    if "//" in t:
        t = t.split("//", 1)[1]
    t = t.split("/", 1)[0]
    return t if "." in t else f"{t}.recruitee.com"


def _offers(token: str):
    host = _host(token)
    why = _http.robots_refuses(host, ["/api/offers/"])
    if why:
        raise RobotsDisallowed(f"recruitee:{token}: {why}")
    data, err = _http.request(URL.format(host=host))
    if err == "HTTP 401":
        raise BoardError(f"recruitee:{token}: {NEEDS_TOKEN}")
    if err:
        raise BoardError(f"recruitee:{token}: {failed(err, 'company name')}")
    if not isinstance(data, dict) or not isinstance(data.get("offers"), list):
        raise BoardError(f"recruitee:{token}: no offers list in the response")
    return data["offers"]


def exists(token: str) -> bool:
    try:
        _offers(token)
        return True
    except BoardError:
        return False


def _place(loc: dict) -> str:
    city, country = clean(loc.get("city")), clean(loc.get("country"))
    if city:
        return ", ".join(x for x in (city, clean(loc.get("state")), country) if x)
    return clean(loc.get("name")) or country


def _pay(offer: dict) -> str:
    s = offer.get("salary")
    if not isinstance(s, dict):
        return ""
    lo, hi = s.get("min"), s.get("max")
    if lo in (None, "") and hi in (None, ""):
        return ""

    def num(v):
        try:
            return f"{int(float(v)):,}"
        except (TypeError, ValueError):
            return clean(v)
    span = "-".join(num(v) for v in (lo, hi) if v not in (None, ""))
    return clean(f"{s.get('currency') or ''} {span} {clean(s.get('period')).replace('_', ' ')}")


def fetch(token: str) -> List[Job]:
    out = []
    for o in _offers(token):
        if not isinstance(o, dict) or (o.get("status") and o.get("status") != "published"):
            continue
        title, url = clean(o.get("title")), o.get("careers_url") or ""
        if not title or not url:
            continue
        places = [p for p in (_place(loc) for loc in o.get("locations") or [] if isinstance(loc, dict)) if p]
        places = list(dict.fromkeys(places))
        workplace = ("remote" if o.get("remote") else "hybrid" if o.get("hybrid")
                     else "onsite" if o.get("on_site") else "")
        body = "\n\n".join(x for x in (html_to_text(o.get("description") or ""),
                                       html_to_text(o.get("requirements") or "")) if x)
        out.append(Job(
            id=f"rc-{o.get('id')}",
            ats="recruitee",
            board=token,
            title=title,
            url=url,
            location="; ".join(places),
            locations=places,
            remote=True if workplace == "remote" else (False if workplace == "onsite" else None),
            posted=str(o.get("published_at") or o.get("created_at") or "")[:10],
            department=clean(o.get("department")),
            employment_type=clean(o.get("employment_type_code")).replace("_", " "),
            compensation=_pay(o),
            deadline=str(o.get("close_at") or "")[:10],
            description=body or None,
            workplace=workplace,
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [_host(token)]
