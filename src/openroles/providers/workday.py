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
from ..models import BoardError, Job, RobotsDisallowed, as_list, clean, html_to_text, iso_day, workplace_of

PAGE = 20            # Workday serves at most 20 postings a page
MAX_OFFSET = 2000    # and stops paging at an offset of 2,000
PAGE_ALL_MAX = 1000  # past this many, a board is searched with `large_queries` when given
SEARCH_PAGES = 5     # a search term's pages read at most
SATURATED = 15       # a term's next page is read only while this many titles still match

TOKEN = re.compile(r"^(?P<tenant>[a-z0-9][a-z0-9-]*)\.(?P<dc>wd\d{1,3})/"
                   r"(?P<site>[A-Za-z0-9][A-Za-z0-9_-]*)$")
SITE_URL = re.compile(r"https?://(?P<tenant>[a-z0-9][a-z0-9-]*)\.(?P<dc>wd\d{1,3})"
                      r"\.myworkdayjobs\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?"
                      r"(?P<site>[A-Za-z0-9][A-Za-z0-9_-]*)", re.I)
# The same board on Workday's other host: https://wdN.myworkdaysite.com/recruiting/<tenant>/<Site>.
# Its API answers there too, but its robots.txt does not (it answered 422), so the board is
# read at the tenant's own myworkdayjobs.com address, whose robots.txt can be read.
MY_SITE = re.compile(r"https?://(?P<dc>wd\d{1,3})\.myworkdaysite\.com/(?:[a-z]{2}-[A-Za-z]{2}/)?"
                     r"recruiting/(?P<tenant>[a-z0-9][a-z0-9-]*)/(?P<site>[A-Za-z0-9][A-Za-z0-9_-]*)", re.I)
MULTI = re.compile(r"^\s*(\d+)\s+locations?\s*$", re.I)
_MORE = re.compile(r" and \d+ more$")
# A posting's path inside its board, and nothing else. It comes from the listing's
# structured `externalPath`, and anything that could point elsewhere is refused.
_PATH = re.compile(r"^/job/[^\s?#\\]+$")
# What a posting's address leaves as it is when it writes the listing's path: everything
# else is percent-encoded, and a "%" stays, so a path the listing sends already encoded
# keeps its escapes.
PATH_SAFE = "/-_.~%"
_POSTED = re.compile(r"posted\s+(today|yesterday|(\d+)(\+)?\s+days?\s+ago)", re.I)

Details = Union[bool, Callable[[Job], bool]]


def token_from(text: str) -> Optional[str]:
    """"tenant.wdN/Site" from a token or from a careers-site URL pasted as seen."""
    text = (text or "").strip()
    if TOKEN.match(text):
        return text
    m = SITE_URL.search(text) or MY_SITE.search(text)
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


# The names one country goes by on Workday boards. A board's facet says "United States
# of America" where a caller says "United States", and an exact match found nothing.
_COUNTRY_ALIASES = (
    ("united states", "united states of america", "usa", "us", "u.s.", "u.s.a."),
    ("united kingdom", "uk", "u.k.", "great britain", "gb",
     "united kingdom of great britain and northern ireland"),
    ("south korea", "korea, republic of", "republic of korea", "korea"),
    ("czechia", "czech republic"),
    ("netherlands", "the netherlands", "holland"),
    ("united arab emirates", "uae"),
    ("turkey", "türkiye", "turkiye"),
)


def country_names(country) -> frozenset:
    """Every spelling of a country a board may use, lower case; empty for none."""
    want = clean(country).lower()
    if not want:
        return frozenset()
    for group in _COUNTRY_ALIASES:
        if want in group:
            return frozenset(group)
    return frozenset({want})


def _workplace(remote_type, labels) -> str:
    """The board's own remoteType first. Without one, a location decides only when every
    location says the same: one remote site among on-site ones does not make the job remote."""
    own = workplace_of(remote_type)
    if own:
        return own
    found = {workplace_of(x) for x in labels if x}
    return found.pop() if len(found) == 1 and "" not in found and not _MORE.search(labels[0] or "") else ""


def more_places(job: Job) -> bool:
    """True for a listing-level Job whose posting names more places than it shows: the
    listing said "N Locations", and only the posting's page names the rest."""
    return bool(_MORE.search(job.location or ""))


BARE_REMOTE = re.compile(r"^\W*(fully |100% )?remote\W*$", re.I)


def with_country(label, country) -> str:
    """A bare "Remote" borrows the country the board recorded beside it."""
    label, country = clean(label), clean(country)
    if country and BARE_REMOTE.match(label):
        return f"{label}, {country}"
    return label


def path_place(path) -> str:
    """The primary location from a posting's path, `/job/<place>/<title>_<id>`.

    Some tenants leave `locationsText` out of the listing, and a blank location
    reads as "nowhere" to anything that filters by place. Workday writes the
    primary location into every posting's path, so that is the fallback:
    "Leeds-1-Example-Street-Office" reads "Leeds 1 Example Street Office".
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
        self.errors: List[str] = []          # listing pages that failed

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
        return f"https://{self.host}/{self.site}{quote(path, safe=PATH_SAFE)}"

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

        The facet's own name differs between tenants (locationCountry, Country, and on
        some boards a location hierarchy such as locationHierarchy1), so it is found by
        its value: a country name in any of the spellings Workday uses ("United States
        of America" for "United States"), or Workday's id for it. A facet named for
        countries wins over one that only holds them.
        """
        names = country_names(country)
        if not names and not country_id:
            return {}, None
        best = None
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
                if v.get("id") and param and (v.get("id") == country_id or name in names):
                    rank = 0 if "country" in param.lower() else 1
                    if best is None or rank < best[0]:
                        best = (rank, {param: [v["id"]]}, v.get("count"))
        return (best[1], best[2]) if best else ({}, None)

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
            found, errs, total = [], [], 0
            for n in range(SEARCH_PAGES):
                data, err = self.page(facets, term, n * PAGE)
                if err or not isinstance(data, dict):
                    errs.append(err or "a page that was not a listing")
                    break
                posts = [p for p in data.get("jobPostings") or [] if isinstance(p, dict)]
                found.extend(posts)
                hits = sum(1 for p in posts
                           if all(s in str(p.get("title") or "").lower() for s in stems))
                # Workday reports the total on the first page only, and 0 on every later
                # one: read afresh, it ended every term after its second page.
                total = total or int(data.get("total") or 0)
                if not posts or hits < SATURATED or (n + 1) * PAGE >= total:
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
        where = clean(posting.get("locationsText"))
        primary = path_place(path)
        many = MULTI.match(where)
        # "3 Locations" names none of them, and read as nowhere to a filter by place. The
        # primary is in the path; the rest are on the posting's page (`detailed`).
        if many and primary:
            where = f"{primary} and {int(many[1]) - 1} more" if int(many[1]) > 1 else primary
        where = where or primary
        remote = clean(posting.get("remoteType")).lower()
        return Job(
            # The path's last segment as the listing sends it, exactly as 0.2.0 gave it: an
            # id a caller has stored must not change under them. job_id() reads it back
            # from the posting's address (see ids._workday_segment).
            id=f"wd-{self.tenant}-{path.rsplit('/', 1)[-1]}",
            ats="workday",
            board=self.token,
            title=title,
            url=self.public_url(path),
            location=where,
            locations=[primary] if many and primary else ([where] if where else []),
            remote=True if (remote == "remote" or "remote" in where.lower()) else None,
            posted=posted_on(posting.get("postedOn"), today),
            workplace=_workplace(posting.get("remoteType"), [where]),
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
        labels += [with_country(a, country) for a in as_list(info.get("additionalLocations"))
                   if isinstance(a, str)]
        labels = list(dict.fromkeys(x for x in labels if x))
        remote = clean(info.get("remoteType") or posting.get("remoteType")).lower()
        job.title = clean(info.get("title")) or job.title
        job.locations = labels
        job.location = "; ".join(labels)
        job.remote = True if (remote == "remote" or any("remote" in x.lower() for x in labels)) \
            else job.remote
        job.workplace = _workplace(info.get("remoteType") or posting.get("remoteType"), labels)
        job.posted = iso_day(info.get("startDate")) or job.posted
        job.employment_type = clean(info.get("timeType"))
        job.deadline = iso_day(info.get("endDate"))
        job.description = html_to_text(info.get("jobDescription")) or None
        return job


def _valid(path) -> bool:
    return (isinstance(path, str) and bool(_PATH.match(path))
            and ".." not in path and "//" not in path and _writable(path))


def _writable(path: str) -> bool:
    """Whether the path can be written into an address at all: JSON can carry a lone
    surrogate ("\\ud800"), which has no UTF-8, and its posting raised UnicodeEncodeError
    out of fetch()."""
    try:
        path.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _log():
    import logging
    return logging.getLogger("openroles")


def fetch(token: str, query: Union[None, str, Iterable[str]] = None, country: str = "",
          details: Details = False, limit: Optional[int] = None,
          today: Optional[dt.date] = None, where: str = "", country_id: str = "",
          large_queries: Optional[Iterable[str]] = None, page_all_max: int = PAGE_ALL_MAX,
          report: Optional[dict] = None, strict_country: bool = True) -> List[Job]:
    """Every posting on a Workday board, or the ones `query` finds.

    `details` decides which postings get their page fetched (one request each) for
    the description, every location and the dates: False for none, True for all, or a
    function that is given the listing-level Job and answers yes or no. Postings whose
    page could not be read keep their listing-level fields.

    `where` is a place the caller will filter on. A posting listed as "N Locations"
    whose primary location is not that place has its page read too, because only the
    page says whether it is one of the others.

    `country_id` is Workday's own id for the country, the same on every tenant seen,
    tried beside the name. `large_queries`: a board holding more than `page_all_max`
    postings (after the country) is searched with these terms instead of paged, so a
    caller does not page through a thousand roles to find its own, and a board past
    Workday's 2,000 is read at all.

    A board whose facets do not list the country has no roles filed there, and returns
    none; with `strict_country=False` it is read whole instead, for a caller that filters
    by place itself and wants a remote role filed under another country.

    `report`, when given, is filled in: "listing_errors" (pages that failed),
    "detail_errors" ({job id: why} for postings whose page could not be read) and
    "details_asked" (how many pages were asked for).
    """
    today = today or dt.date.today()
    board = WorkdayBoard(token)
    board.check_robots()
    first = board.first()
    facets, in_country = board.country_facet(first.get("facets"), country, country_id)
    if (country or country_id) and not facets:
        if first.get("facets"):
            # The board lists its places and this country is not among them.
            if strict_country:
                return []
        else:
            _log().warning("workday:%s: the board offers no place filter, so %r could not be "
                           "applied: every posting is returned", token, country or country_id)
    total = int((in_country if in_country is not None else first.get("total")) or 0)
    if query:
        listing = board.search(facets, [query] if isinstance(query, str) else query)
    elif large_queries is not None and total > page_all_max:
        listing = board.search(facets, large_queries)
    else:
        if total > MAX_OFFSET and not limit:
            _log().warning("workday:%s: the board holds %d postings and Workday pages only the "
                           "first %d; pass a query to search the rest", token, total, MAX_OFFSET)
        listing = board.all_postings(facets, total,
                                     None if facets else first["jobPostings"], limit)
    jobs, postings, seen = [], [], set()
    for p in listing:
        job = board.job(p, today)
        if job and p["externalPath"] not in seen:
            seen.add(p["externalPath"])
            jobs.append(job)
            postings.append(p)
    if limit:
        # The same postings come back either way; a page past the limit was a wasted request.
        jobs, postings = jobs[:limit], postings[:limit]
    place = clean(where).lower()

    def located(i: int) -> bool:
        return bool(place and MULTI.match(clean(postings[i].get("locationsText")))
                    and place not in " ".join(jobs[i].locations).lower())
    want = [i for i, j in enumerate(jobs)
            if details is True or (callable(details) and details(j)) or located(i)]
    pages = _parallel(lambda i: board.detail(postings[i]["externalPath"]), want)
    failed: dict = {}
    for i, (detail, err) in zip(want, pages):
        if err or board.detailed(jobs[i], postings[i], detail, today) is None:
            failed[jobs[i].id] = err or "a posting page that was not a posting"
    if report is not None:
        report.update(listing_errors=list(board.errors), detail_errors=dict(failed),
                      details_asked=len(want))
    if board.errors or failed:
        _log().warning(
            "workday:%s: %d request(s) failed (%s)%s", token, len(board.errors) + len(failed),
            _summarise(board.errors + list(failed.values())),
            f"; {len(failed)} posting(s) kept without a description" if failed else "")
    return jobs


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    m = TOKEN.match(token or "")
    return [f"{m['tenant']}.{m['dc']}.myworkdayjobs.com"] if m else []
