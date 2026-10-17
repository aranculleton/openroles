"""Workday: a paged listing, then one request per posting for its description.

A careers site at https://<tenant>.<wdN>.myworkdayjobs.com/<Site> is backed by the
endpoint its own front end calls: POST /wday/cxs/<tenant>/<Site>/jobs lists postings
and GET /wday/cxs/<tenant>/<Site>/job/<path> returns one. It is not a documented API,
so it can change without notice. The board is read only where the tenant's robots.txt
allows the listing, the postings and the careers site itself, and the reader stops
sending the moment the board answers 429 or 503.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable, List, Optional, Tuple, Union
from urllib.parse import quote, unquote

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, html_to_text

PAGE = 20            # Workday serves at most 20 postings a page
MAX_OFFSET = 2000    # and stops paging at an offset of 2,000
SEARCH_PAGES = 5     # a search term's pages read at most
SATURATED = 15       # a term's next page is read only while this many titles still match

TOKEN = re.compile(r"^(?P<tenant>[a-z0-9][a-z0-9-]*)\.(?P<dc>wd\d{1,3})/"
                   r"(?P<site>[A-Za-z0-9][A-Za-z0-9_-]*)$")
SITE_URL = re.compile(r"https?://(?P<tenant>[a-z0-9][a-z0-9-]*)\.(?P<dc>wd\d{1,3})"
                      r"\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?"
                      r"(?P<site>[A-Za-z0-9][A-Za-z0-9_-]*)", re.I)
MULTI = re.compile(r"^\s*\d+\s+locations?\s*$", re.I)
# A posting's path inside its board, and nothing else. It comes from the listing's
# structured `externalPath`, and anything that could point elsewhere is refused.
_PATH = re.compile(r"^/job/[^\s?#\\]+$")
_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)(\+)?\s+days?\s+ago)", re.I)

Details = Union[bool, Callable[[Job], bool]]


def token_from(text: str) -> Optional[str]:
    """"tenant.wdN/Site" from a token or from a careers-site URL pasted as seen."""
    text = (text or "").strip()
    if TOKEN.match(text):
        return text
    m = SITE_URL.search(text)
    if not m or m["site"].lower() in ("wday", "en-us"):
        return None
    return f"{m['tenant'].lower()}.{m['dc'].lower()}/{m['site']}"


def posted_on(text, today: dt.date) -> str:
    """ISO date from "Posted 3 Days Ago", or "" when it is only a floor ("30+ Days")."""
    m = _POSTED.search(str(text or ""))
    if not m:
        return ""
    word = m.group(1).lower()
    if word == "today":
        days = 0
    elif word == "yesterday":
        days = 1
    elif m.group(3):
        return ""
    else:
        days = int(m.group(2))
    return (today - dt.timedelta(days=days)).isoformat()


def with_country(label, country) -> str:
    label, country = clean(label), clean(country)
    if country and label.lower().strip(" -") in ("remote", "fully remote", "100% remote"):
        return f"{label}, {country}"
    return label


def path_place(path) -> str:
    """The primary location from a posting's path, `/job/<place>/<title>_<id>`.

    Some tenants leave `locationsText` out of the listing, and a blank location
    reads as "nowhere" to anything that filters by place. Workday writes the
    primary location into every posting's path, so that is the fallback:
    "Toronto-40-King-St-W-Corp" reads "Toronto 40 King St W Corp".
    """
    parts = str(path or "").split("/")
    return clean(" ".join(unquote(parts[2]).split("-"))) if len(parts) > 3 else ""


def distinct_terms(queries: Iterable[str]) -> List[str]:
    """Search terms, less any that only add words to a shorter one.

    Workday matches every word of a search, so "senior data analyst" can only find
    what "data analyst" already found.
    """
    terms = list(dict.fromkeys(" ".join(q.lower().split()) for q in queries if q.strip()))
    words = {t: frozenset(t.split()) for t in terms}
    return [t for t in terms if not any(words[o] < words[t] for o in terms)]


def _parallel(fn, items) -> list:
    """fn over items, two at a time, results in input order, never raising."""
    def safe(item):
        try:
            return fn(item)
        except Exception as exc:  # noqa: BLE001
            return None, f"{type(exc).__name__}: {exc}"
    with ThreadPoolExecutor(max_workers=_http.PER_HOST) as ex:
        return list(ex.map(safe, items))


def _summarise(errors: List[str]) -> str:
    counts: dict = {}
    for e in errors:
        counts[e] = counts.get(e, 0) + 1
    return ", ".join(f"{n}x {e}" for e, n in sorted(counts.items(), key=lambda x: -x[1])[:3])


class WorkdayBoard:
    """One Workday board's calls. Stops sending the moment it is told to slow down."""

    def __init__(self, token: str):
        m = TOKEN.match(token or "")
        if not m:
            raise BoardError(f"not a Workday board (want tenant.wdN/Site): {token!r}")
        self.token = token
        self.tenant, self.site = m["tenant"], m["site"]
        self.host = f"{m['tenant']}.{m['dc']}.myworkdayjobs.com"
        self.api = f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}"
        self.halt = threading.Event()
        self.errors: List[str] = []

    # -------------------------------------------------------------- calls

    def robots_paths(self) -> List[str]:
        """The listing, the postings and the careers site, which robots.txt must all allow.

        A robots.txt path is case-sensitive and a Workday site name is not, so a rule
        written as /external/ still covers a board spelt /External/.
        """
        site = self.site
        paths = [f"/wday/cxs/{self.tenant}/{site}/jobs", f"/wday/cxs/{self.tenant}/{site}/job/",
                 f"/{site}/"]
        return paths + ([f"/{site.lower()}/"] if site != site.lower() else [])

    def check_robots(self) -> None:
        ok, why = _http.robots_allows(self.host, self.robots_paths())
        if not ok:
            raise RobotsDisallowed(f"workday:{self.token}: {why}")

    def call(self, url: str, payload: Optional[dict] = None):
        if self.halt.is_set():
            return None, "not sent: the board asked to slow down"
        data, err = _http.request(url, payload)
        if err in ("HTTP 429", "HTTP 503"):
            self.halt.set()
        return data, err

    def page(self, facets: dict, search: str, offset: int):
        return self.call(f"{self.api}/jobs", {"appliedFacets": facets, "limit": PAGE,
                                              "offset": offset, "searchText": search})

    def detail(self, path: str):
        return self.call(f"{self.api}{quote(path, safe='/-_.~%')}")

    def public_url(self, path: str) -> str:
        return f"https://{self.host}/{self.site}{quote(path, safe='/-_.~%')}"

    # -------------------------------------------------------------- listing

    def first(self) -> dict:
        data, err = self.page({}, "", 0)
        if err:
            raise BoardError(f"workday:{self.token}: the board did not answer ({err})")
        if not isinstance(data, dict) or not isinstance(data.get("jobPostings"), list):
            raise BoardError(f"workday:{self.token}: not a Workday listing; "
                             f"probably a wrong tenant or site")
        return data

    @staticmethod
    def country_facet(facets, country: str = "", country_id: str = "") -> Tuple[dict, Optional[int]]:
        """({facetParameter: [id]}, count) for the board's facet value for one country.

        The facet's own name differs between tenants (locationCountry, Country, ...),
        so it is found by its value: a country name, or Workday's id for it.
        """
        want = clean(country).lower()
        stack = [f for f in facets or [] if isinstance(f, dict)]
        while stack:
            facet = stack.pop()
            param = str(facet.get("facetParameter") or "")
            for v in facet.get("values") or []:
                if not isinstance(v, dict):
                    continue
                if isinstance(v.get("values"), list):
                    stack.append(v)
                    continue
                name = clean(v.get("descriptor")).lower()
                if "country" in param.lower() and v.get("id") and (want or country_id) and (
                        v.get("id") == country_id or (want and name == want)):
                    return {param: [v["id"]]}, v.get("count")
        return {}, None

    def all_postings(self, facets: dict, total: int, first=None, limit: Optional[int] = None):
        """Every posting on the board (or on its slice for one country)."""
        got = [p for p in first or [] if isinstance(p, dict)]
        stop = min(total, MAX_OFFSET, limit if limit else MAX_OFFSET)
        offsets = list(range(PAGE if first is not None else 0, stop, PAGE))
        for data, err in _parallel(lambda off: self.page(facets, "", off), offsets):
            if err or not isinstance(data, dict):
                self.errors.append(err or "a page that was not a listing")
                continue
            got.extend(p for p in data.get("jobPostings") or [] if isinstance(p, dict))
        return got

    def search(self, facets: dict, queries: Iterable[str]):
        """The postings each search term finds.

        Workday ranks by relevance over the whole description, so page three of
        "pricing" is postings that mention pricing once: a term's next page is read
        only while most of its titles still contain the term.
        """
        def one(term):
            stems = [w[:5] for w in term.split()]
            found, errs = [], []
            for n in range(SEARCH_PAGES):
                data, err = self.page(facets, term, n * PAGE)
                if err or not isinstance(data, dict):
                    errs.append(err or "a page that was not a listing")
                    break
                posts = [p for p in data.get("jobPostings") or [] if isinstance(p, dict)]
                found.extend(posts)
                hits = sum(1 for p in posts
                           if all(s in str(p.get("title") or "").lower() for s in stems))
                if hits < SATURATED or (n + 1) * PAGE >= int(data.get("total") or 0):
                    break
            return found, errs

        listing = []
        for found, errs in _parallel(one, distinct_terms(queries)):
            listing.extend(found or [])
            self.errors.extend([errs] if isinstance(errs, str) else errs or [])
        return listing

    # -------------------------------------------------------------- jobs

    def job(self, posting: dict, today: dt.date) -> Optional[Job]:
        """A Job from one listing entry, with no description."""
        path = posting.get("externalPath")
        title = clean(posting.get("title"))
        if not title or not _valid(path):
            return None
        where = clean(posting.get("locationsText")) or path_place(path)
        remote = clean(posting.get("remoteType")).lower()
        return Job(
            id=f"wd-{self.tenant}-{path.rsplit('/', 1)[-1]}",
            ats="workday",
            board=self.token,
            title=title,
            url=self.public_url(path),
            location=where,
            locations=[where] if where else [],
            remote=True if (remote == "remote" or "remote" in where.lower()) else None,
            posted=posted_on(posting.get("postedOn"), today),
        )

    def detailed(self, job: Job, posting: dict, detail, today: dt.date) -> Optional[Job]:
        """The same Job, completed from its posting page."""
        info = detail.get("jobPostingInfo") if isinstance(detail, dict) else None
        if not isinstance(info, dict):
            return None
        place = info.get("country")
        country = clean(place.get("descriptor")) if isinstance(place, dict) else ""
        labels = [with_country(info.get("location") or posting.get("locationsText")
                               or path_place(posting.get("externalPath")), country)]
        labels += [with_country(a, country) for a in info.get("additionalLocations") or []
                   if isinstance(a, str)]
        labels = list(dict.fromkeys(x for x in labels if x))
        remote = clean(info.get("remoteType") or posting.get("remoteType")).lower()
        job.title = clean(info.get("title")) or job.title
        job.locations = labels
        job.location = "; ".join(labels)
        job.remote = True if (remote == "remote" or any("remote" in x.lower() for x in labels)) \
            else job.remote
        job.posted = str(info.get("startDate") or "")[:10] or job.posted
        job.employment_type = clean(info.get("timeType"))
        job.deadline = str(info.get("endDate") or "")[:10]
        job.description = html_to_text(str(info.get("jobDescription") or "")) or None
        return job


def _valid(path) -> bool:
    return (isinstance(path, str) and bool(_PATH.match(path))
            and ".." not in path and "//" not in path)


def fetch(token: str, query: Union[None, str, Iterable[str]] = None, country: str = "",
          details: Details = False, limit: Optional[int] = None,
          today: Optional[dt.date] = None) -> List[Job]:
    """Every posting on a Workday board, or the ones `query` finds.

    `details` decides which postings get their page fetched (one request each) for
    the description, every location and the dates: False for none, True for all, or a
    function that is given the listing-level Job and answers yes or no. Postings whose
    page could not be read keep their listing-level fields.
    """
    today = today or dt.date.today()
    board = WorkdayBoard(token)
    board.check_robots()
    first = board.first()
    facets, in_country = board.country_facet(first.get("facets"), country)
    if country and not facets:
        return []
    total = int((in_country if in_country is not None else first.get("total")) or 0)
    if query:
        listing = board.search(facets, [query] if isinstance(query, str) else query)
    else:
        listing = board.all_postings(facets, total,
                                     None if facets else first["jobPostings"], limit)
    jobs, postings, seen = [], [], set()
    for p in listing:
        job = board.job(p, today)
        if job and p["externalPath"] not in seen:
            seen.add(p["externalPath"])
            jobs.append(job)
            postings.append(p)
    want = [i for i, j in enumerate(jobs)
            if details is True or (callable(details) and details(j))]
    pages = _parallel(lambda i: board.detail(postings[i]["externalPath"]), want)
    failed = 0
    for i, (detail, err) in zip(want, pages):
        if err or board.detailed(jobs[i], postings[i], detail, today) is None:
            failed += 1
            board.errors.append(err or "a posting page that was not a posting")
    if board.errors:
        import logging
        logging.getLogger("openroles").warning(
            "workday:%s: %d request(s) failed (%s)%s", token, len(board.errors),
            _summarise(board.errors),
            f"; {failed} posting(s) kept without a description" if failed else "")
    return jobs[:limit] if limit else jobs
