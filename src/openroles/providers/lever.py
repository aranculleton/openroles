"""Lever: one request a board, every posting's description included.

Lever hosts boards in two regions. A board the global API does not know is tried on
the EU one before it is called missing.
"""
from __future__ import annotations

import datetime as dt
from typing import List, Optional, Tuple
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, clean

HOSTS = ("https://api.lever.co", "https://api.eu.lever.co")
PATH = "/v0/postings/{token}?mode=json"


def _epoch_ms_date(ms) -> str:
    """Lever's createdAt (milliseconds since 1970) as YYYY-MM-DD, or ""."""
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def _postings(token: str) -> Tuple[Optional[list], str]:
    why = ""
    for host in HOSTS:
        data, err = _http.request(host + PATH.format(token=quote(token, safe="")))
        # Lever answers an unknown board with {"ok": false, ...}, not a 404.
        if isinstance(data, list):
            return data, ""
        # The global region's answer explains more than the EU's 404 does.
        why = why or err or "not a posting list"
    return None, why


def exists(token: str) -> bool:
    return _postings(token)[0] is not None


def _description(j: dict) -> Optional[str]:
    """The intro, then every list (requirements, responsibilities), then the closing text.

    `descriptionPlain` alone is only the intro: the requirements live in `lists`.
    """
    parts = [str(j.get("descriptionPlain") or "").strip()]
    for block in j.get("lists") or []:
        if not isinstance(block, dict):
            continue
        from ..models import html_to_text
        body = html_to_text(str(block.get("content") or ""))
        head = clean(block.get("text"))
        if head or body:
            parts.append(f"{head}\n{body}".strip())
    parts.append(str(j.get("additionalPlain") or "").strip())
    text = "\n\n".join(p for p in parts if p)
    return text or None


def _pay(j: dict) -> str:
    r = j.get("salaryRange")
    if not isinstance(r, dict) or (r.get("min") is None and r.get("max") is None):
        return ""
    lo, hi = r.get("min"), r.get("max")
    span = f"{lo:,}-{hi:,}" if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) \
        else str(lo if lo is not None else hi)
    unit = clean(r.get("interval")).replace("-", " ")
    return clean(f"{r.get('currency') or ''} {span} {unit}")


def fetch(token: str) -> List[Job]:
    data, why = _postings(token)
    if data is None:
        raise BoardError(f"lever:{token}: not a posting list ({why}); probably a wrong board name")
    out = []
    for j in data:
        if not isinstance(j, dict):
            continue
        cats = j.get("categories") or {}
        location = clean(cats.get("location"))
        every = [clean(x) for x in cats.get("allLocations") or [] if clean(x)]
        workplace = clean(j.get("workplaceType")).lower()
        out.append(Job(
            id=f"lv-{j.get('id')}",
            ats="lever",
            board=token,
            title=clean(j.get("text")),
            url=j.get("hostedUrl") or "",
            location=location,
            locations=every or ([location] if location else []),
            remote=True if workplace == "remote" else (False if workplace in ("on-site", "onsite") else None),
            posted=_epoch_ms_date(j.get("createdAt")),
            department=clean(cats.get("department") or cats.get("team")),
            employment_type=clean(cats.get("commitment")),
            compensation=_pay(j),
            description=_description(j),
        ))
    return out
