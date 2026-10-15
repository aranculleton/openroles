"""What openroles returns: one shape for every applicant tracking system."""
from __future__ import annotations

import html
import re
from dataclasses import asdict, dataclass, field
from typing import List, Optional

ATS = ("greenhouse", "lever", "ashby", "workday")
BODY_CAP = 50_000


class BoardError(Exception):
    """A board could not be read: a wrong token, no answer, or robots.txt says no."""


class RobotsDisallowed(BoardError):
    """The host's robots.txt does not allow this board to be read."""


@dataclass(frozen=True)
class Board:
    """One employer's job board on one ATS.

    `token` is the board's name on its ATS: `acme` for Greenhouse, Lever and Ashby,
    and `tenant.wdN/Site` for Workday (from https://tenant.wdN.myworkdayjobs.com/Site).
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


def clean(value) -> str:
    """One line of text, whitespace collapsed."""
    return " ".join(str(value or "").split())
