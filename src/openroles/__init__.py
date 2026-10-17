"""openroles: every open role, straight from the employer's own applicant tracking system.

    >>> import openroles
    >>> openroles.detect("https://jobs.lever.co/acme")
    [Board(ats='lever', token='acme')]
    >>> jobs = openroles.fetch("greenhouse:acme", query="data analyst", location="London")

Greenhouse, Lever, Ashby and Workday, read from the same public JSON their own
careers pages use: no key, no account, no scraping service, and nothing but the
Python standard library.
"""
from __future__ import annotations

__version__ = "0.1.2"

import datetime as _dt
from typing import Callable, Iterable, List, Optional, Union

from .models import ATS, Board, BoardError, Job, RobotsDisallowed

__all__ = ["ATS", "Board", "BoardError", "Job", "RobotsDisallowed", "__version__",
           "detect", "fetch"]


def detect(target: str) -> List[Board]:
    """The job boards behind a board URL, "ats:token", a careers page or a company name."""
    from .discover import detect as _detect
    return _detect(target)


def _boards(target: Union[str, Board]) -> List[Board]:
    if isinstance(target, Board):
        return [target]
    found = detect(target)
    if not found:
        raise BoardError(f"no Greenhouse, Lever, Ashby or Workday board found for {target!r}")
    return found


def _matches(job: Job, query: Optional[str], location: Optional[str],
             remote: Optional[bool], since: Optional[_dt.date]) -> bool:
    if query and not all(w in job.title.lower() for w in query.lower().split()):
        return False
    if location:
        where = " ".join([job.location] + job.locations).lower()
        if location.lower() not in where:
            return False
    if remote is not None and bool(job.remote) != remote:
        return False
    if since and job.posted and job.posted < since.isoformat():
        return False
    return True


def fetch(target: Union[str, Board], query: Optional[str] = None,
          location: Optional[str] = None, remote: Optional[bool] = None,
          since_days: Optional[int] = None, limit: Optional[int] = None,
          details: Union[None, bool, Callable[[Job], bool]] = None,
          country: str = "", workday_queries: Optional[Iterable[str]] = None) -> List[Job]:
    """Open roles from one employer's board (or every board `detect` finds for a name).

    query       words that must all appear in the title (Workday also searches with it)
    location    text that must appear in a location ("London", "Remote")
    remote      True for remote roles only, False for on-site and hybrid only
    since_days  posted within this many days (roles with no date are kept)
    limit       at most this many roles, newest first
    details     Workday only: fetch each posting's page for its description (one
                request each). Defaults to True when `query` narrows the board.
    country     Workday only: narrow the board to one country by name ("Canada")
    """
    from .providers import READERS
    since = (_dt.date.today() - _dt.timedelta(days=since_days)) if since_days else None
    jobs: List[Job] = []
    for board in _boards(target):
        reader = READERS[board.ats]
        if board.ats == "workday":
            queries = list(workday_queries) if workday_queries else (query or None)
            got = reader.fetch(board.token, query=queries, country=country,
                               details=bool(query) if details is None else details)
        else:
            got = reader.fetch(board.token)
        jobs.extend(j for j in got if _matches(j, query, location, remote, since))
    jobs.sort(key=lambda j: j.posted or "", reverse=True)
    return jobs[:limit] if limit else jobs
