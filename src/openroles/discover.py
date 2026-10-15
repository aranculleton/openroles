"""Which ATS an employer's jobs live on, from a URL, a careers page or a company name."""
from __future__ import annotations

import re
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

from . import _http
from .models import ATS, Board
from .providers import ashby, greenhouse, lever, workday

_SLUG = r"([A-Za-z0-9][A-Za-z0-9_.-]*)"
PATTERNS = [
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/embed/job_board(?:/js)?\?for=" + _SLUG, re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/" + _SLUG, re.I)),
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?!embed\b)" + _SLUG, re.I)),
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/" + _SLUG, re.I)),
    ("lever", re.compile(r"api(?:\.eu)?\.lever\.co/v0/postings/" + _SLUG, re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/" + _SLUG, re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/" + _SLUG, re.I)),
]
_NOT_A_BOARD = {"embed", "js", "v1", "api", "static", "assets", "favicon.ico", "robots.txt"}


def parse(text: str) -> Optional[Board]:
    """A Board from "ats:token" or from any board URL. None when it names no board."""
    text = (text or "").strip()
    head, sep, tail = text.partition(":")
    if sep and head.lower() in ATS and not tail.startswith("//"):
        token = tail.strip()
        if head.lower() == "workday":
            token = workday.token_from(token) or token
        return Board(head.lower(), token) if token else None
    wd = workday.token_from(text)
    if wd:
        return Board("workday", wd)
    if "greenhouse.io" in text and "for=" in text:
        q = parse_qs(urlsplit(text if "//" in text else "https://" + text).query)
        if q.get("for"):
            return Board("greenhouse", q["for"][0])
    for ats, rx in PATTERNS:
        m = rx.search(text)
        if m and m.group(1).lower() not in _NOT_A_BOARD:
            return Board(ats, m.group(1).rstrip("."))
    return None


def in_page(url: str) -> List[Board]:
    """Every board a careers page links to or embeds, if its robots.txt allows reading it."""
    parts = urlsplit(url if "//" in url else "https://" + url)
    path = parts.path or "/"
    ok, _why = _http.robots_allows(parts.netloc, [path])
    if not ok:
        return []
    body, err = _http.request_raw(parts.geturl(), accept="text/html,*/*", limit=3_000_000)
    if err:
        return []
    found = []
    for m in re.finditer(r"https?://[^\s\"'<>)]+", body):
        board = parse(m.group(0))
        if board and board not in found:
            found.append(board)
    return found


def slugs(company: str) -> List[str]:
    """The board names an employer is likely to use: "Acme Data Ltd" -> acmedata, acme-data, acme."""
    words = re.findall(r"[a-z0-9]+", company.lower().replace("&", " and "))
    suffixes = {"inc", "ltd", "llc", "plc", "limited", "corp", "corporation", "co", "group",
                "gmbh", "ag", "sa", "bv", "the"}
    core = [w for w in words if w not in suffixes] or words
    out = ["".join(core), "-".join(core), core[0] if core else ""]
    return [s for s in dict.fromkeys(out) if s]


def guess(company: str) -> List[Board]:
    """Boards found by trying the employer's likely board names on Greenhouse, Lever and Ashby.

    Workday cannot be guessed from a name (its address needs a tenant, a data centre
    and a site name): give its careers URL instead.
    """
    found = []
    for slug in slugs(company):
        for ats, reader in (("greenhouse", greenhouse), ("lever", lever), ("ashby", ashby)):
            if reader.exists(slug):
                board = Board(ats, slug)
                if board not in found:
                    found.append(board)
        if found:
            break
    return found


def detect(target: str) -> List[Board]:
    """The boards behind a board URL, an "ats:token", a careers page or a company name."""
    board = parse(target)
    if board:
        return [board]
    if re.match(r"^(https?://|www\.)|^[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", target.strip(), re.I):
        return in_page(target.strip())
    return guess(target)
