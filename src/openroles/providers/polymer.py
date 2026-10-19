"""Polymer: an organisation's jobs, from Polymer's documented public API.

developer.polymer.co: "Public API - Unauthenticated access to job listings for job board
integrations", rate-limited. GET https://api.polymer.co/v1/hire/organizations/<slug>/jobs,
paged; a job's own record (/jobs/<id>) adds its description and department, so it is
fetched only when asked for, and never more than DETAIL_CAP a board. Only an explicit
Disallow in the host's robots.txt stops a read.
"""
from __future__ import annotations

from typing import Callable, List, Optional, Union
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text, workplace_of

HOST = "api.polymer.co"
BASE = "https://api.polymer.co/v1/hire/organizations/{slug}/jobs"
MAX_PAGES = 20
DETAIL_CAP = 60

Details = Union[bool, Callable[[Job], bool]]


def _items(token: str) -> list:
    slug = quote(token.strip(), safe="")
    why = _http.robots_refuses(HOST, [f"/v1/hire/organizations/{slug}/jobs"])
    if why:
        raise RobotsDisallowed(f"polymer:{token}: {why}")
    items: list = []
    for page in range(1, MAX_PAGES + 1):
        data, err = _http.request(f"{BASE.format(slug=slug)}?page={page}")
        if err or not isinstance(data, dict) or not isinstance(data.get("items"), list):
            if page == 1:
                raise BoardError(f"polymer:{token}: {failed(err, 'organisation name')}")
            break
        items.extend(i for i in data["items"] if isinstance(i, dict))
        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        if meta.get("is_last") or not meta.get("next_page"):
            break
    return items


def exists(token: str) -> bool:
    try:
        _items(token)
        return True
    except BoardError:
        return False


def fetch(token: str, details: Details = False, report: Optional[dict] = None) -> List[Job]:
    out = []
    for i in _items(token):
        title, url = clean(i.get("title")), i.get("job_post_url") or ""
        if not title or not url:
            continue
        place = ", ".join(x for x in (clean(i.get("city")), clean(i.get("state_region")),
                                      clean(i.get("country"))) if x) or clean(i.get("display_location"))
        workplace = workplace_of(i.get("remoteness_pretty"))
        out.append(Job(
            id=f"pm-{i.get('id')}",
            ats="polymer",
            board=token,
            title=title,
            url=url,
            location=place,
            locations=[place] if place else [],
            remote=True if workplace == "remote" else (False if workplace == "onsite" else None),
            posted=str(i.get("published_at") or i.get("created_at") or "")[:10],
            department=clean(i.get("job_category_name")),
            employment_type=clean(i.get("kind_pretty")),
            compensation=clean(i.get("salary_pretty")),
            workplace=workplace,
        ))
    want = [j for j in out if details is True or (callable(details) and details(j))][:DETAIL_CAP]
    errors: dict = {}
    for job in want:
        detail, err = _http.request(f"{BASE.format(slug=quote(token.strip(), safe=''))}/{job.id[3:]}")
        if err or not isinstance(detail, dict):
            errors[job.id] = err or "a job record that was not a job"
            continue
        rec = detail.get("item") if isinstance(detail.get("item"), dict) else detail
        job.description = html_to_text(str(rec.get("description") or "")) or None
        job.department = clean(rec.get("department")) or job.department
    if report is not None:
        report.update(listing_errors=[], detail_errors=errors, details_asked=len(want))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return [HOST]
