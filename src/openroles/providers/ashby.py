"""Ashby: one request a board, descriptions and any posted pay included.

Read only where api.ashbyhq.com's robots.txt allows it, checked once per process.
"""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import (
    BoardError,
    Job,
    RobotsDisallowed,
    amount,
    as_str,
    clean,
    html_to_text,
    ident,
    iso_day,
    pay,
    period_of,
    span,
    workplace_of,
)

HOST = "api.ashbyhq.com"
URL = "https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true"


def _address(entry: dict) -> dict:
    addr = entry.get("address")
    post = addr.get("postalAddress") if isinstance(addr, dict) else None
    return post if isinstance(post, dict) else {}


def with_country(label: str, country: str) -> str:
    """A bare "Remote" borrows the country the ATS recorded beside it."""
    from .workday import with_country as same
    return same(label, country)


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


def _list(value) -> list:
    """A field Ashby documents as a list, or nothing: one odd posting is not a reason to
    lose the board."""
    return value if isinstance(value, list) else []


def _salaries(components) -> list:
    """The salary components with a figure: equity and bonus are not salary."""
    return [c for c in components if isinstance(c, dict)
            and clean(c.get("compensationType")).lower() == "salary"
            and (amount(c.get("minValue")) is not None or amount(c.get("maxValue")) is not None)]


def _salary(job: dict) -> dict:
    """The salary band from Ashby's structured compensation: its summary where that has
    one, else every tier's. Tiers in different currencies or periods are not one band, so
    they give none, and `compensation` still words them. Two intervals no period field can
    hold ("2 WEEK", "0.5 MONTH") are still two periods."""
    comp = job.get("compensation") if isinstance(job.get("compensation"), dict) else {}
    tiers = [t for t in _list(comp.get("compensationTiers")) if isinstance(t, dict)]
    parts = (_salaries(_list(comp.get("summaryComponents")))
             or _salaries(c for t in tiers for c in _list(t.get("components"))))
    kinds = {(clean(c.get("currencyCode")).upper(),
              period_of(c.get("interval")) or clean(c.get("interval")).lower()) for c in parts}
    if len(kinds) != 1:
        return pay()
    spans = [span(c.get("minValue"), c.get("maxValue")) for c in parts]     # each in order first
    lows = [lo for lo, _ in spans if lo is not None]
    highs = [hi for _, hi in spans if hi is not None]
    return pay(min(lows) if lows else None, max(highs) if highs else None,
               parts[0].get("currencyCode"), parts[0].get("interval"))


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
        number, title = ident(j.get("id")), clean(j.get("title"))
        if not number or not title:
            continue
        home = clean(_address(j).get("addressCountry"))
        labels = [label(j)] + [label(s, home) for s in _list(j.get("secondaryLocations"))
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
            id=f"ab-{number}",
            ats="ashby",
            board=token,
            title=title,
            url=as_str(j.get("jobUrl")),
            location="; ".join(labels),
            locations=labels,
            remote=remote,
            # Ashby's publishedAt is when the job was last published, and the board gives
            # no first-published date: a re-published role reads as new.
            posted=iso_day(j.get("publishedAt")),
            department=clean(j.get("department") or j.get("team")),
            employment_type=clean(j.get("employmentType")),
            compensation=_pay(j),
            **_salary(j),
            description=(clean_block(j.get("descriptionPlain"))
                         or html_to_text(j.get("descriptionHtml")) or None),
            workplace=workplace_of(workplace) or ("remote" if remote else ""),
        ))
    return out


def clean_block(text) -> str:
    return as_str(text).strip()


def fetch(token: str) -> List[Job]:
    data, err = _request(token)
    if err:
        raise BoardError(f"ashby:{token}: the board did not answer ({err})")
    return rows(token, data)


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
