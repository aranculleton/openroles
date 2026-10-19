"""What openroles returns: one shape for every applicant tracking system."""
from __future__ import annotations

import html
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
