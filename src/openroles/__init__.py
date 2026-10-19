"""openroles: every open role, straight from the employer's own applicant tracking system.

    >>> import openroles
    >>> openroles.detect("https://jobs.lever.co/acme")
    [Board(ats='lever', token='acme')]
    >>> jobs = openroles.fetch("greenhouse:acme", query="data analyst", location="London")

Fifteen applicant tracking systems and any careers site that publishes its jobs for
search engines, read from the same public feeds their own careers pages use: no key,
no account, no scraping service, and nothing but the Python standard library.
"""
from __future__ import annotations

__version__ = "0.2.0"

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
        from .models import systems
        raise BoardError(f"no {systems()} board found for {target!r}")
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
          country: str = "", workday_queries: Optional[Iterable[str]] = None,
          today: Optional[_dt.date] = None, report: Optional[dict] = None) -> List[Job]:
    """Open roles from one employer's board (or every board `detect` finds for a name).

    query       words that must all appear in the title (Workday also searches with it)
    location    text that must appear in a location ("London", "Remote")
    remote      True for remote roles only, False for on-site and hybrid only
    since_days  posted within this many days (roles with no date are kept)
    limit       at most this many roles, newest first
    details     Workday, Rippling and Polymer: fetch each posting's own record for its
                description (one request each). Defaults to True when `query` narrows the board.
    country     Workday only: narrow the board to one country by name ("Canada")
    today       the day "posted 3 days ago" and `since_days` count from (default: today),
                so a run replayed later dates its roles from its own day
    report      filled with {board: what failed} for every board read: "error" for a
                board that could not be read at all, and for Workday the pages that failed
    """
    from .providers import READERS
    today = today or _dt.date.today()
    since = (today - _dt.timedelta(days=since_days)) if since_days else None
    jobs: List[Job] = []
    boards = _boards(target)
    failed: List[BoardError] = []
    for board in boards:
        reader = READERS[board.ats]
        seen: dict = {}
        if report is not None:
            report[str(board)] = seen
        try:
            pages = _titled(query, bool(query) if details is None else details)
            if board.ats == "workday":
                queries = list(workday_queries) if workday_queries else (query or None)
                got = reader.fetch(board.token, query=queries, country=country, details=pages,
                                   where=location or "", today=today, report=seen)
            elif board.ats in ("rippling", "polymer"):
                got = reader.fetch(board.token, details=pages, report=seen)
            elif board.ats == "careersite":
                got = reader.fetch(board.token, queries=[query] if query else None, report=seen)
            else:
                got = reader.fetch(board.token)
        except BoardError as e:
            seen["error"] = str(e)
            # One of several boards a name found failing is not a reason to lose the rest.
            if len(boards) == 1:
                raise
            failed.append(e)
            continue
        jobs.extend(j for j in got if _matches(j, query, location, remote, since))
    if failed:
        if len(failed) == len(boards):
            raise failed[0]
        import logging
        logging.getLogger("openroles").warning(
            "%d of %d boards could not be read: %s", len(failed), len(boards),
            "; ".join(str(e) for e in failed))
    jobs.sort(key=lambda j: j.posted or "", reverse=True)
    return jobs[:limit] if limit else jobs


def _titled(query: Optional[str], details: Union[bool, Callable[[Job], bool]]):
    """`details`, asked only of postings whose title passes `query`: a page fetched for a
    posting the title filter then drops was a wasted request."""
    if not query or details is False:
        return details
    words = query.lower().split()

    def wanted(job: Job) -> bool:
        if not all(w in job.title.lower() for w in words):
            return False
        return details(job) if callable(details) else True
    return wanted
