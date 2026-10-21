"""What openroles returns: one shape for every applicant tracking system."""
from __future__ import annotations

import datetime as _dt
import html
import math
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

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
    # "hour", "day", "week", "month", "year", or "" when the board does not say.
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: str = ""
    salary_period: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


_TAG = re.compile(r"<[^>]+>")


def html_to_text(content: str) -> str:
    """Plain text from an ATS's HTML, which some boards entity-encode twice."""
    s = content or ""
    for _ in range(3):
        un = html.unescape(s)
        if un == s:
            break
        s = un
    s = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = _TAG.sub(" ", s)
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
    """One line of text, whitespace collapsed."""
    return " ".join(str(value or "").split())


_DAY = re.compile(r"\s*([0-9]{4})-([0-9]{2})-([0-9]{2})(?![0-9])")


def iso_day(*values) -> str:
    """The first of `values` that starts with a real calendar date, as YYYY-MM-DD, or "".

    Every reader's `posted` and `deadline` comes through here. Cut to ten characters
    instead, a board's odd value ("1/9/2026", "Invalid date", "2026-02-30") came out as
    text that `since_days` compared and the newest-first sort ordered as if it were a
    date, so a role could be dropped as old for a date nobody gave it."""
    for value in values:
        m = _DAY.match(str(value or ""))
        if not m:
            continue
        try:
            return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            continue
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
        x = float(value)
    elif isinstance(value, str) and _AMOUNT.fullmatch(value) and not _DOT_THOUSANDS.fullmatch(value):
        x = float(value.replace(",", ""))
    else:
        return None
    if not math.isfinite(x) or x <= 0:
        return None
    return int(x) if x.is_integer() else x


_NOT_A_PERIOD = ("biweek", "fortnight", "semimonth", "bimonth", "onetime")
_PERIODS = (("hour", "hour"), ("daily", "day"), ("day", "day"), ("week", "week"),
            ("month", "month"), ("annual", "year"), ("annum", "year"), ("year", "year"))


def period_of(value) -> str:
    """"hour", "day", "week", "month", "year" or "" from what boards write: Lever's
    "per-year-salary", Ashby's "1 YEAR", Rippling's "ANNUAL", schema.org's "HOUR". A period
    no field here can hold ("bi-weekly", "one-time") is ""."""
    v = re.sub(r"[^a-z]", "", str(value or "").lower())
    if not v or any(w in v for w in _NOT_A_PERIOD):
        return ""
    return next((period for word, period in _PERIODS if word in v), "")


def pay(low=None, high=None, currency="", period="") -> dict:
    """A Job's salary fields from a board's structured pay, all empty when it gives no
    amount: a currency or a period with no figure says nothing."""
    lo, hi = amount(low), amount(high)
    if lo is None and hi is None:
        return {"salary_min": None, "salary_max": None, "salary_currency": "", "salary_period": ""}
    code = clean(currency).upper()
    return {"salary_min": lo, "salary_max": hi,
            "salary_currency": code if re.fullmatch(r"[A-Z]{3}", code) else "",
            "salary_period": period_of(period)}
