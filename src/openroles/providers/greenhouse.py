"""Greenhouse: one request a board, every posting's description included."""
from __future__ import annotations

from typing import List
from urllib.parse import quote

from .. import _http
from ..models import BoardError, Job, clean, html_to_text

# `content=true` returns every posting's body in the same request.
URL = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
META = "https://boards-api.greenhouse.io/v1/boards/{token}"


def exists(token: str) -> bool:
    data, err = _http.request(META.format(token=quote(token, safe="")))
    return not err and isinstance(data, dict) and "name" in data


def fetch(token: str) -> List[Job]:
    data, err = _http.request(URL.format(token=quote(token, safe="")))
    if err:
        raise BoardError(f"greenhouse:{token}: the board did not answer ({err})")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise BoardError(f"greenhouse:{token}: no jobs list in the response")
    out = []
    for j in data["jobs"]:
        if not isinstance(j, dict):
            continue
        location = clean((j.get("location") or {}).get("name"))
        depts = [clean(d.get("name")) for d in j.get("departments") or [] if isinstance(d, dict)]
        out.append(Job(
            id=f"gh-{j.get('id')}",
            ats="greenhouse",
            board=token,
            title=clean(j.get("title")),
            url=j.get("absolute_url") or "",
            location=location,
            locations=[location] if location else [],
            remote=True if "remote" in location.lower() else None,
            # First published, not updated: Greenhouse bumps updated_at on every edit,
            # so a role first posted months ago would read as new.
            posted=str(j.get("first_published") or j.get("updated_at") or "")[:10],
            department=next((d for d in depts if d), ""),
            deadline=str(j.get("application_deadline") or "")[:10],
            description=html_to_text(j.get("content") or "") or None,
        ))
    return out
