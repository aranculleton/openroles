"""What openroles returns: one shape for every applicant tracking system."""
from __future__ import annotations

import datetime as _dt
import html
import math
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

ATS = ("greenhouse", "lever", "ashby", "workday", "workable", "teamtailor", "personio",
       "recruitee", "rippling", "jazzhr", "gem", "polymer", "manatal", "homerun", "clearcompany",
       "careersite")
# How each is written in a sentence.
NAMES = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby", "workday": "Workday",
         "workable": "Workable", "teamtailor": "Teamtailor", "personio": "Personio",
         "recruitee": "Recruitee", "rippling": "Rippling", "jazzhr": "JazzHR", "gem": "Gem",
         "polymer": "Polymer", "manatal": "Manatal", "homerun": "Homerun",
         "clearcompany": "ClearCompany",
         "careersite": "any careers site that publishes its jobs for search engines"}


def systems(last: str = "or") -> str:
    """Every system openroles reads, as a sentence: "Greenhouse, Lever, ... or Recruitee"."""
    names = [NAMES[a] for a in ATS if a != "careersite"]
    return ", ".join(names[:-1]) + f" {last} " + names[-1]
BODY_CAP = 50_000


class BoardError(Exception):
    """A board could not be read: a wrong token, no answer, or robots.txt says no."""


class RobotsDisallowed(BoardError):
    """The host's robots.txt does not allow this board to be read."""


@dataclass(frozen=True)
class Board:
    """One employer's job board on one ATS.

    `token` is the board's name on its ATS: `acme` for most; `tenant.wdN/Site` for Workday
    (from https://tenant.wdN.myworkdayjobs.com/Site); for Teamtailor and Recruitee the
    careers site's name or, on the employer's own domain, its host; for ClearCompany the
    site id its careers page prints; for a careers site, its address.
    """
    ats: str
    token: str

    def __post_init__(self):
        if self.ats not in ATS:
            raise ValueError(f"unknown ATS {self.ats!r}; expected one of {', '.join(ATS)}")

    def __str__(self) -> str:
        return f"{self.ats}:{self.token}"


@dataclass
class Job:
    """One open role, in the same shape whichever ATS it came from."""
    id: str
    ats: str
    board: str
    title: str
    url: str
    location: str = ""
    locations: List[str] = field(default_factory=list)
    remote: Optional[bool] = None
    posted: str = ""
    department: str = ""
    employment_type: str = ""
    compensation: str = ""
    deadline: str = ""
    description: Optional[str] = None
    # "remote", "hybrid", "onsite", or "" when the board does not say. `remote` stays
    # for callers that only ask yes or no; this is the one that can say hybrid.
    workplace: str = ""
    # The posted pay band as numbers, only where the board publishes it as numbers: never
    # read out of the description. `compensation` is the same band as the board words it.
    # The currency is the ISO 4217 code the board gives ("GBP"), and the period one of
    # "hour", "day", "week", "month", "year", or "" when the board does not say or says
    # one these cannot hold (every two weeks, twice a month).
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    salary_period: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_TAG = re.compile(r"<[^>]+>")
# The tags that end a line: <br>, and the end of a paragraph, list item, block or heading.
_BREAK = re.compile(r"<(br|/p|/li|/div|/h\d)[^>]*>", re.I)


def _swap_tags(pattern, repl: str, s: str) -> str:
    """pattern.sub(repl, s) for a tag pattern, which ends at a ">": run only up to the last
    ">" in `s`, since no tag can start after it. Before it, every "<" has a ">" to stop at,
    so the pattern never looks far ahead; over the whole text, it looked to the end of the
    text for every "<" with no ">" after it, and a description of "<a " repeated took
    seconds."""
    cut = s.rfind(">") + 1
    return pattern.sub(repl, s[:cut]) + s[cut:]


def html_to_text(content: str) -> str:
    """Plain text from an ATS's HTML, which some boards entity-encode twice. Anything a
    board sends there that is not text (a number, an object, a list) gives "", never an
    exception."""
    s = content if isinstance(content, str) else ""
    for _ in range(3):
        un = html.unescape(s)
        if un == s:
            break
        s = un
    s = _swap_tags(_BREAK, "\n", s)
    s = _swap_tags(_TAG, " ", s)
    s = re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", s))
    return "\n".join(line.strip() for line in s.splitlines()).strip()[:BODY_CAP]


def failed(err: str, what: str) -> str:
    """Why a board did not come back, said honestly: a wrong name only on a 404 or an answer
    that is not a board, slowing down on a 429 or 503, and anything else as it was."""
    if err in ("HTTP 429", "HTTP 503"):
        return f"the board asked to slow down ({err}); try again later"
    if not err or err == "HTTP 404" or not err.startswith(("HTTP", "URLError", "Timeout", "OSError")):
        return f"{err or 'not a board'}; probably a wrong {what}"
    return f"the board did not answer ({err})"


def workplace_of(*values) -> str:
    """"remote", "hybrid", "onsite" or "" from what boards write: Lever's "on-site",
    Ashby's "OnSite", Workday's "Flexible", a location that says "Hybrid"."""
    for value in values:
        v = re.sub(r"[^a-z]", "", str(value or "").lower())
        if not v or v == "unspecified":
            continue
        if "hybrid" in v or "flexible" in v:
            return "hybrid"
        if "remote" in v:
            return "remote"
        if v in ("onsite", "inoffice", "office", "none"):
            return "onsite"
    return ""


def clean(value) -> str:
    """One line of text, whitespace collapsed, from a field a board writes as text or a
    number. Anything else (an object, a list, true) is "": written out as Python shows it,
    it came out as text nobody wrote ("{'name': 'Leeds'}", "True")."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join(str(value or "").split())


# A posting is one record from a board, and one odd field in it is no reason to lose the
# board: each reader reads a field only in the shape it expects, and the empty value
# otherwise.

def as_list(value) -> list:
    """A field a board writes as a list, or []."""
    return value if isinstance(value, list) else []


def as_dict(value) -> dict:
    """A field a board writes as an object, or {}."""
    return value if isinstance(value, dict) else {}


def as_str(value) -> str:
    """A field a board writes as text, as it stands (an address, a block of text), or ""."""
    return value if isinstance(value, str) else ""


def ident(value) -> str:
    """A posting's own id as text: a whole number or text the board gives, or "" for
    anything else (an object, a list, true, a fraction), which leaves the posting out. An
    id written as None or an object came out as "None" or Python's view of the object,
    the same for every such posting."""
    if isinstance(value, bool):
        return ""
    if isinstance(value, int):
        return str(value)
    return value if isinstance(value, str) and value.strip() else ""


_DAY = re.compile(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})(?![0-9])")
# A date before any of these systems existed, or further ahead than any posting runs, is a
# board's blank written as a date: .NET's DateTime.MinValue (0001-01-01), 1900-01-01, the
# Unix epoch (1970-01-01), 9999-12-31 for "no closing date".
FIRST_YEAR = 1990
YEARS_AHEAD = 2


def iso_day(*values) -> str:
    """The first of `values` that starts with a real calendar date, as YYYY-MM-DD, or "".

    Every reader's `posted` and `deadline` comes through here. Cut to ten characters
    instead, a board's odd value ("1/9/2026", "Invalid date", "2026-02-30") came out as
    text that `since_days` compared and the newest-first sort ordered as if it were a
    date, so a role could be dropped as old for a date nobody gave it. A placeholder
    (a year before FIRST_YEAR, or more than YEARS_AHEAD years from today) is no date
    either, so the next value is tried."""
    latest = _dt.date.today() + _dt.timedelta(days=366 * YEARS_AHEAD)
    for value in values:
        m = _DAY.match(str(value or ""))
        if not m:
            continue
        try:
            day = _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if FIRST_YEAR <= day.year and day <= latest:
            return day.isoformat()
    return ""


# A plain number, or one with comma thousands ("48,000"). "48.000" is left alone: it is
# forty-eight thousand in much of Europe and forty-eight elsewhere, and a wrong salary is
# worse than none.
_AMOUNT = re.compile(r"\s*(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?\s*")
_DOT_THOUSANDS = re.compile(r"\s*[0-9]{1,3}(?:\.[0-9]{3})+\s*")


def amount(value) -> Optional[float]:
    """A pay figure a board wrote as a number or as plain digits, or None. Zero and below are
    a board's way of leaving the field blank."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            x = float(value)
        except OverflowError:       # an integer past any float: no salary is that
            return None
    elif isinstance(value, str) and _AMOUNT.fullmatch(value) and not _DOT_THOUSANDS.fullmatch(value):
        x = float(value.replace(",", ""))
    else:
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return int(x) if x.is_integer() else x


_NOT_A_PERIOD = ("biweek", "fortnight", "semi", "bimonth", "biannual", "twice", "onetime")
_PERIODS = (("hour", "hour"), ("daily", "day"), ("day", "day"), ("week", "week"),
            ("month", "month"), ("annual", "year"), ("annum", "year"), ("year", "year"))
_COUNT = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def period_of(value) -> str:
    """"hour", "day", "week", "month", "year" or "" from what boards write: Lever's
    "per-year-salary", Ashby's "1 YEAR", Rippling's "ANNUAL", schema.org's "HOUR". A period
    no field here can hold ("bi-weekly", "one-time", "semi-annual") is "", and so is one
    counted in anything but one of its unit: Ashby's "2 WEEK", "0.5 MONTH" and "6 MONTH"
    are not a week or a month."""
    text = str(value or "").lower()
    if any(float(n) != 1 for n in _COUNT.findall(text)):
        return ""
    v = re.sub(r"[^a-z]", "", text)
    if not v or any(w in v for w in _NOT_A_PERIOD):
        return ""
    return next((period for word, period in _PERIODS if word in v), "")


def span(low=None, high=None) -> Tuple[Optional[float], Optional[float]]:
    """(low, high) as figures (see `amount`), lowest first. A board that puts the higher
    figure in its minimum field has written the same range the wrong way round: the two
    are swapped, never changed, and with only one of them there is nothing to order."""
    lo, hi = amount(low), amount(high)
    if lo is not None and hi is not None and lo > hi:
        lo, hi = hi, lo
    return lo, hi


def pay(low=None, high=None, currency="", period="") -> dict:
    """A Job's salary fields from a board's structured pay, all empty when it gives no
    amount: a currency or a period with no figure says nothing."""
    lo, hi = span(low, high)
    if lo is None and hi is None:
        return {"salary_min": None, "salary_max": None, "salary_currency": "", "salary_period": ""}
    code = clean(currency).upper()
    return {"salary_min": lo, "salary_max": hi,
            "salary_currency": code if re.fullmatch(r"[A-Z]{3}", code) else "",
            "salary_period": period_of(period)}
