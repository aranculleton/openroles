"""Ashby: one request a board, descriptions and any posted pay included.

Read only where api.ashbyhq.com's robots.txt allows it, checked once per process.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, html_to_text

HOST = "api.ashbyhq.com"
URL = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"


def _address(entry: dict) -> dict:
    addr = entry.get("address")
    post = addr.get("postalAddress") if isinstance(addr, dict) else None
    return post if isinstance(post, dict) else {}


def with_country(label: str, country: str) -> str:
    """A bare "Remote" borrows the country the ATS recorded beside it."""
    label, country = clean(label), clean(country)
    if country and label.lower().strip(" -") in ("remote", "fully remote", "100% remote"):
        return f"{label}, {country}"
    return label


def label(entry: dict, fallback_country: str = "") -> str:
    """One location as text, from the structured address where there is one.

    The display name is whatever the employer typed, and some carry no geography at
    all; the postal address beside it says where the job is.
    """
    name = clean(entry.get("location"))
    post = _address(entry)
    city, region, country = (clean(post.get(k)) for k in
                             ("addressLocality", "addressRegion", "addressCountry"))
    if city:
        text = ", ".join(x for x in (city, region, country) if x)
        return f"Remote - {text}" if "remote" in name.lower() else text
    if country and country.lower() not in name.lower():
        return f"{name}, {country}" if name else country
    return with_country(name, fallback_country)


def _pay(job: dict) -> str:
    comp = job.get("compensation") if isinstance(job.get("compensation"), dict) else {}
    for key in ("scrapeableCompensationSalarySummary", "compensationTierSummary"):
        if clean(comp.get(key)):
            return clean(comp.get(key))
    return ""


def _request(token: str):
    ok, why = _http.robots_allows(HOST, [f"/posting-api/job-board/{token}"])
    if not ok:
        raise RobotsDisallowed(f"ashby:{token}: {why}")
    return _http.request(URL.format(token=quote(token, safe="")))


def exists(token: str) -> bool:
    try:
        data, err = _request(token)
    except RobotsDisallowed:
        return False
    return not err and isinstance(data, dict) and isinstance(data.get("jobs"), list)


def rows(token: str, data: object) -> List[Job]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise BoardError(f"ashby:{token}: no jobs list in the response; probably a wrong board name")
    out = []
    for j in data["jobs"]:
        if not isinstance(j, dict) or j.get("isListed") is False:
            continue
        home = clean(_address(j).get("addressCountry"))
        labels = [label(j)] + [label(s, home) for s in j.get("secondaryLocations") or []
                               if isinstance(s, dict)]
        labels = list(dict.fromkeys(x for x in labels if x))
        # workplaceType is Ashby's current field; isRemote is the older flag, and only
        # counts when the newer one is missing (a "Hybrid" role can carry isRemote).
        workplace = clean(j.get("workplaceType")).lower()
        if workplace:
            remote = True if workplace == "remote" else (False if workplace in ("onsite", "on-site") else None)
        else:
            remote = True if j.get("isRemote") is True else None
        out.append(Job(
            id=f"ab-{j.get('id')}",
            ats="ashby",
            board=token,
            title=clean(j.get("title")),
            url=j.get("jobUrl") or "",
            location="; ".join(labels),
            locations=labels,
            remote=remote,
            posted=str(j.get("publishedAt") or "")[:10],
            department=clean(j.get("department") or j.get("team")),
            employment_type=clean(j.get("employmentType")),
            compensation=_pay(j),
            description=(clean_block(j.get("descriptionPlain"))
                         or html_to_text(str(j.get("descriptionHtml") or "")) or None),
        ))
    return out


def clean_block(text) -> str:
    return str(text or "").strip()


def fetch(token: str) -> List[Job]:
    data, err = _request(token)
    if err:
        raise BoardError(f"ashby:{token}: the board did not answer ({err})")
    return rows(token, data)
