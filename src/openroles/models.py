"""What openroles returns: one shape for every applicant tracking system."""
from __future__ import annotations

import datetime as _dt
import html
import math
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional, Tuple

from ._hidden import dropped

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
# How `detect` found a board (Board.found), most certain first; "" for one made by hand.
FOUND = ("named", "linked", "guessed", "")


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

    `found` is how `detect` found it: "named" (the target was the board's own URL or
    ats:token), "linked" (the careers page given links to it or embeds it) or "guessed" (a
    board exists under a name the company might use, and nothing yet shows it is theirs: a
    small organisation may have taken the name first). "" for a Board made by hand. It is
    not part of the board's identity: two Boards with one ats and token are equal.
    """
    ats: str
    token: str
    found: str = field(default="", compare=False, repr=False)

    def __post_init__(self):
        if self.ats not in ATS:
            raise ValueError(f"unknown ATS {self.ats!r}; expected one of {', '.join(ATS)}")
        if self.found not in FOUND:
            raise ValueError(f"unknown way of finding a board {self.found!r}; expected one of "
                             f"{', '.join(repr(f) for f in FOUND)}")

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

    def __post_init__(self):
        _take_hidden(self)

    @property
    def hidden(self) -> dict:
        """What openroles left out of `description` because no reader of the posting sees
        it, by kind: {"comments": 1, "scripts and styles": 1, "hidden elements": 2,
        "tag characters": 40}, only the kinds there were, and {} when there was nothing.

        A hidden element is one with the `hidden` attribute, aria-hidden="true", or an
        inline style that hides it (display:none, visibility:hidden, opacity:0, font-size:0,
        color:transparent, a clip that leaves nothing, a place far off the page, a height of
        0 with its overflow hidden), with everything in it; tag characters
        (U+E0000 to U+E007F) show nothing and a model reads them as the ASCII they shadow.
        Comments and style blocks are common and usually harmless. A hidden element or tag
        characters are words written for a program and not for a person, which is worth
        knowing before a model reads the posting. Not part of `to_dict()`."""
        return dict(self.__dict__.get("_hidden") or {})

    def to_dict(self) -> dict:
        return asdict(self)


def _take_hidden(job: Job) -> None:
    """Keep what was left out of a description that says so (`Shown`), and the description
    as plain text."""
    found = job.description.hidden if isinstance(job.description, Shown) else None
    if found is not None:
        job.description = str.__str__(job.description)
    if found:
        job.__dict__["_hidden"] = dict(found)
    else:
        job.__dict__.pop("_hidden", None)


def describe(job: Job, text: Optional[str]) -> None:
    """Give a Job its description after it was made, from a posting's own record read
    later, with what was left out of it (`Job.hidden`)."""
    job.description = text or None
    _take_hidden(job)


class Shown(str):
    """Text a reader of the page sees, with what was left out of it to get there (`hidden`,
    as `Job.hidden` says it). `html_to_text` gives one only where something was left out;
    a Job keeps the count and plain text."""

    def __new__(cls, text: str = "", hidden: Optional[dict] = None):
        self = super().__new__(cls, text)
        self.hidden = dict(hidden or {})
        return self


def _add(into: dict, found) -> dict:
    for kind, n in (found or {}).items():
        into[kind] = into.get(kind, 0) + n
    return into


def joined(parts, sep: str = "\n\n") -> str:
    """The non-empty `parts` joined with `sep`, keeping what was left out of each."""
    parts = [p for p in parts if p]
    found: dict = {}
    for part in parts:
        _add(found, getattr(part, "hidden", None))
    text = sep.join(parts)
    return Shown(text, found) if found else text


def each_once(jobs) -> List[Job]:
    """Each posting once, the first time it comes, by its id. A board read page by page while
    it changes lists a posting on two pages when one is added or removed ahead of it."""
    seen: set = set()
    out = []
    for job in jobs:
        if job.id not in seen:
            seen.add(job.id)
            out.append(job)
    return out


# A tag is anything between "<" and ">". The tag of an inline element (group 1) leaves nothing
# in its place, as it leaves nothing between the words on either side of it on a page; any other
# tag leaves a space. (Block elements and <br> end a line: _BREAK, which is read first.)
_INLINE = ("a abbr b bdi bdo cite code data dfn em font i kbd mark q s samp small span strong sub sup "
           "time u var wbr").split()
_TAG = re.compile(r"<(?:(/?(?:" + "|".join(_INLINE) + r")(?=[\s/>])[^>]*)|[^>]+)>", re.I | re.A)
# The tags that end a line: <br>, and the end of a paragraph, list item, block or heading.
_BREAK = re.compile(r"<(br|/p|/li|/div|/h\d)[^>]*>", re.I)


def _swap_tags(pattern, repl, s: str) -> str:
    """pattern.sub(repl, s) for a tag pattern, which ends at a ">": run only up to the last
    ">" in `s`, since no tag can start after it. Before it, every "<" has a ">" to stop at,
    so the pattern never looks far ahead; over the whole text, it looked to the end of the
    text for every "<" with no ">" after it, and a description of "<a " repeated took
    seconds."""
    cut = s.rfind(">") + 1
    return pattern.sub(repl, s[:cut]) + s[cut:]


# Unicode tag characters (U+E0000 to U+E007F) show nothing, and a model reads a run of them as
# the ASCII text each one shadows: a sentence written in them is on no page anyone sees. Their
# one use in text is a subdivision flag (a black flag, two to seven tag letters or digits, and
# U+E007F, as England's is), which is kept whole.
_TAG_CHARS = re.compile("[\U000E0000-\U000E007F]")
_TAG_FLAG = re.compile("\U0001F3F4[\U000E0030-\U000E0039\U000E0061-\U000E007A]{2,7}\U000E007F")


def _untagged(text: str) -> Tuple[str, int]:
    """(`text` without its tag characters, a subdivision flag apart, how many went)."""
    if not _TAG_CHARS.search(text):
        return text, 0
    pieces, last = [], 0
    for m in _TAG_FLAG.finditer(text):
        pieces += (_TAG_CHARS.sub("", text[last:m.start()]), m.group(0))
        last = m.end()
    pieces.append(_TAG_CHARS.sub("", text[last:]))
    out = "".join(pieces)
    return out, len(text) - len(out)


def html_to_text(content: str) -> str:
    """Plain text from an ATS's HTML, which some boards entity-encode twice. What no reader
    sees (comments, scripts, styles, hidden elements) is dropped first, and again after each
    round of decoding, so what a board encoded twice is dropped too: see `_hidden`. Tag
    characters go too. Where anything was left out, the text is a `Shown` that says what
    (`.hidden`). Anything a board sends there that is not text (a number, an object, a list)
    gives "", never an exception."""
    found: dict = {}
    s, counts = dropped(content if isinstance(content, str) else "")
    _add(found, counts)
    for _ in range(3):
        un = html.unescape(s)
        if un == s:
            break
        s, counts = dropped(un)
        _add(found, counts)
    s = _swap_tags(_BREAK, "\n", s)
    s = _swap_tags(_TAG, lambda m: " " if m.group(1) is None else "", s)
    s = re.sub(r"[ \t]{2,}", " ", re.sub(r"\n{3,}", "\n\n", s))
    text, tags = _untagged("\n".join(line.strip() for line in s.splitlines()).strip())
    if tags:
        found["tag characters"] = tags
    text = text[:BODY_CAP]
    return Shown(text, found) if found else text


def html_or_plain(markup, plain) -> str:
    """A posting's text from a board's HTML field, and from its plain-text field only where the
    board sent no HTML. A board's plain-text field is its HTML with the tags taken off and
    nothing else, so a comment or a hidden element's text is in it: `html_to_text` leaves it
    out of the HTML's. An HTML field that is there but shows no text gives "", and is not a
    reason to read the plain one. Tag characters are left out of either."""
    if isinstance(markup, str) and markup.strip():
        return html_to_text(markup)
    if not isinstance(plain, str):
        return ""
    text, tags = _untagged(plain.strip())
    return Shown(text, {"tag characters": tags}) if tags else text


def failed(err: str, what: str) -> str:
    """Why a board did not come back, said honestly: a wrong name only on a 404 or an answer
    that is not a board, slowing down on a 429 or 503, a request not sent because its host
    asked for a pause or its rate limit is spent, and anything else as it was."""
    if err in ("HTTP 429", "HTTP 503"):
        return f"the board asked to slow down ({err}); try again later"
    if err and err.startswith("not sent: "):
        return f"{err}; try again later"
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


# A posting's own location that names no place: a way of working ("Hybrid", "Remote",
# "On-site"), "Anywhere", "Multiple locations", or a time zone. Where a board also files the
# posting under offices, those say where the job is.
_NO_PLACE = re.compile(
    r"^\W*(?:(?:fully |100% )?remote|hybrid|on[- ]?site|in[- ]office|office[- ]based|flexible|distributed"
    r"|anywhere|multiple locations|various(?: locations)?|(?:[a-z]+\s+)*time\s*zones?"
    r"|(?:utc|gmt)\s*[+-]?\s*[0-9:]*)\W*$", re.I)


def names_a_place(label) -> bool:
    """Whether a posting's location label names somewhere, rather than a way of working
    ("Hybrid", "Remote", "On-site"), "Anywhere", "Multiple locations" or a time zone."""
    text = clean(label)
    return bool(text) and not _NO_PLACE.match(text)


def own_place_first(own: str, offices) -> List[str]:
    """A posting's locations on a board that also files it under offices (Greenhouse, Gem).

    An office is the employer's own tag, not a place the job is open at: a role a board shows
    as "Berlin, Germany" was filed under six European offices, one shown as "San Francisco,
    CA • New York, NY • United States" under "Canada" and "US", and one in Dublin under
    "Ireland Locations". So a posting that names its own place is where it says, and its
    offices count only where it names none ("Hybrid", a time zone, nothing), which is where
    such a board records where the job is."""
    own = clean(own)
    if names_a_place(own):
        return [own]
    return list(dict.fromkeys(x for x in [own, *(clean(o) for o in offices)] if x))


def clean(value) -> str:
    """One line of text, whitespace collapsed, from a field a board writes as text or a
    number, without tag characters. Anything else (an object, a list, true) is "": written
    out as Python shows it, it came out as text nobody wrote ("{'name': 'Leeds'}", "True")."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join((_untagged(value)[0] if isinstance(value, str) else str(value)).split())


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
