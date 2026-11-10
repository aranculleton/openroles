"""Which ATS an employer's jobs live on, from a URL, a careers page or a company name."""
from __future__ import annotations

import dataclasses
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional
from urllib.parse import parse_qs, urlsplit

from . import _http
from .models import ATS, Board
from .providers import READERS, workday

_SLUG = r"([A-Za-z0-9][A-Za-z0-9_.-]*)"
PATTERNS = [
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/embed/job_board(?:/js)?\?for=" + _SLUG, re.I)),
    ("greenhouse", re.compile(r"boards-api\.greenhouse\.io/v1/boards/" + _SLUG, re.I)),
    ("greenhouse", re.compile(r"(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io/(?!embed\b)" + _SLUG, re.I)),
    ("lever", re.compile(r"jobs(?:\.eu)?\.lever\.co/" + _SLUG, re.I)),
    ("lever", re.compile(r"api(?:\.eu)?\.lever\.co/v0/postings/" + _SLUG, re.I)),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/" + _SLUG, re.I)),
    ("ashby", re.compile(r"api\.ashbyhq\.com/posting-api/job-board/" + _SLUG, re.I)),
    ("personio", re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*)\.jobs\.personio\.(?:de|com)\b", re.I)),
    ("teamtailor", re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*)\.teamtailor\.com\b", re.I)),
    ("recruitee", re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*)\.recruitee\.com\b", re.I)),
    ("workable", re.compile(r"apply\.workable\.com/(?:api/v\d/(?:widget/)?accounts/)?" + _SLUG, re.I)),
    ("workable", re.compile(r"workable\.com/api/accounts/" + _SLUG, re.I)),
    ("workable", re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*)\.workable\.com\b", re.I)),
    ("rippling", re.compile(r"ats\.rippling\.com/" + _SLUG, re.I)),
    ("rippling", re.compile(r"api\.rippling\.com/platform/api/ats/v\d/board/" + _SLUG, re.I)),
    ("jazzhr", re.compile(r"app\.jazz\.co/feeds/export/jobs/" + _SLUG, re.I)),
    ("jazzhr", re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*)\.applytojob\.com\b", re.I)),
    ("gem", re.compile(r"jobs\.gem\.com/" + _SLUG, re.I)),
    ("gem", re.compile(r"api\.gem\.com/job_board/v0/" + _SLUG, re.I)),
    ("polymer", re.compile(r"jobs\.polymer\.co/" + _SLUG, re.I)),
    ("polymer", re.compile(r"api\.polymer\.co/v1/hire/organizations/" + _SLUG, re.I)),
    ("manatal", re.compile(r"api\.manatal\.com/open/v\d/career-page/" + _SLUG, re.I)),
    ("manatal", re.compile(r"careers-page\.com/" + _SLUG, re.I)),
    ("homerun", re.compile(r"feed\.homerun\.co/" + _SLUG, re.I)),
    ("homerun", re.compile(r"(?<![\w.-])([a-z0-9][a-z0-9-]*)\.homerun\.co\b", re.I)),
    ("clearcompany", re.compile(r"career-site\.js\?siteId=([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
    ("clearcompany", re.compile(r"careers-api\.clearcompany\.com/v1/([0-9a-f]{8}-[0-9a-f-]{27})", re.I)),
]
# Lever's embedded job list names its board in a script, not a link:
# window.leverJobsOptions = {accountName: 'acme', ...}.
_LEVER_EMBED = re.compile(r"leverJobsOptions[^}]{0,400}?accountName['\"]?\s*:\s*['\"]" + _SLUG + "['\"]", re.I)
# Systems a careers page may use that openroles cannot read, and why, so "nothing found"
# says what was there: every system in the README's "Not supported" table.
_NO_ROBOTS = "its robots.txt disallows the job pages, or the board needs a sign-in"
_TERMS = "its terms forbid automated reading of the careers pages"
_SESSION = "its board is read through a session token issued to the browser"
_UNCHECKED = "openroles has no reader for it yet: it has not been checked well enough to build one on"
_JSON_LD = ("it publishes no open job API; if the careers site publishes its jobs for search engines, "
            "read it as careersite:<the site's address>")
UNSUPPORTED = [
    ("SuccessFactors", re.compile(r"\b(?:career\d*\.)?successfactors\.(?:com|eu)\b|\bjobs\.sap\.com\b", re.I),
     "its robots.txt disallows reading"),
    ("iCIMS", re.compile(r"\.icims\.com\b", re.I), _JSON_LD),
    ("Eightfold", re.compile(r"\.eightfold\.ai\b", re.I), _JSON_LD),
    ("Taleo", re.compile(r"\.taleo\.net\b", re.I), "it publishes no open job board"),
    ("Oracle Recruiting", re.compile(r"\.oraclecloud\.com/hcmUI/CandidateExperience", re.I),
     "its job API is marked for internal use"),
    ("SmartRecruiters", re.compile(r"\b(?:jobs|careers)\.smartrecruiters\.com\b", re.I),
     "its robots.txt closes it to every crawler but LinkedIn's"),
    ("Dayforce", re.compile(r"\bdayforcehcm\.com\b", re.I), _NO_ROBOTS),
    ("UKG", re.compile(r"\brecruiting\d*\.ultipro\.com\b", re.I), _NO_ROBOTS),
    ("Paycom", re.compile(r"\bpaycomonline\.(?:net|com)\b", re.I), _NO_ROBOTS),
    ("Pinpoint", re.compile(r"\.pinpointhq\.com\b", re.I), _NO_ROBOTS),
    ("BambooHR", re.compile(r"\.bamboohr\.com/(?:careers|jobs)\b", re.I), _TERMS),
    ("Breezy", re.compile(r"\.breezy\.hr\b", re.I), _TERMS),
    ("Cornerstone", re.compile(r"\.csod\.com\b", re.I), _SESSION),
    ("BrassRing", re.compile(r"\bbrassring\.com\b", re.I), _SESSION),
    ("Hireology", re.compile(r"\bhireology\.com\b", re.I), _SESSION),
    ("Comeet", re.compile(r"\bcomeet\.(?:com|co)/(?:jobs|careers-api)\b", re.I), _SESSION),
    ("Phenom", re.compile(r"\bphenompeople\.com\b", re.I),
     "the sites checked ask, through robots.txt's Content-Signal, that their content not be used as "
     "AI input; one that does not can be read as careersite:<the site's address>"),
    ("Freshteam", re.compile(r"\.freshteam\.com\b", re.I), "it is being shut down by its vendor"),
    ("ADP", re.compile(r"\b(?:workforcenow|recruiting|myjobs)\.adp\.com\b", re.I), _UNCHECKED),
    ("Paylocity", re.compile(r"\brecruiting\.paylocity\.com\b", re.I), _UNCHECKED),
    ("JOIN", re.compile(r"\bjoin\.com/companies/", re.I), _UNCHECKED),
    ("TalentLyft", re.compile(r"\.talentlyft\.com\b", re.I), _UNCHECKED),
    ("ApplicantPro", re.compile(r"\.applicantpro\.com\b", re.I), _UNCHECKED),
    ("Jobvite", re.compile(r"\bjobs\.jobvite\.com\b", re.I), _UNCHECKED),
]
_NOT_A_BOARD = {"embed", "js", "v1", "api", "static", "assets", "favicon.ico", "robots.txt",
                # the vendors' own sites, not an employer's board
                "www", "app", "docs", "support", "help", "status", "blog", "careers-api",
                "apply", "resources", "internal", "j", "open", "feed", "404", "jobs",
                "developers", "feeds"}


def parse(text: str) -> Optional[Board]:
    """A Board from "ats:token" or from any board URL, found "named". None when it names no
    board."""
    text = (text or "").strip()
    head, sep, tail = text.partition(":")
    if sep and head.lower() in ATS and not tail.startswith("//"):
        token = tail.strip()
        if head.lower() == "workday":
            token = workday.token_from(token) or token
        return Board(head.lower(), token, "named") if token else None
    wd = workday.token_from(text)
    if wd:
        return Board("workday", wd, "named")
    if "greenhouse.io" in text and "for=" in text:
        q = parse_qs(urlsplit(text if "//" in text else "https://" + text).query)
        if q.get("for"):
            return Board("greenhouse", q["for"][0], "named")
    for ats, rx in PATTERNS:
        m = rx.search(text)
        if m and m.group(1).lower() not in _NOT_A_BOARD:
            return Board(ats, m.group(1).rstrip("."), "named")
    return None


def in_page(url: str) -> List[Board]:
    """Every board a careers page links to or embeds, found "linked", if its robots.txt allows
    reading it."""
    parts = urlsplit(url if "//" in url else "https://" + url)
    path = parts.path or "/"
    ok, _why = _http.robots_allows(parts.netloc, [path])
    if not ok:
        return []
    body, err = _http.request_raw(parts.geturl(), accept="text/html,*/*", limit=3_000_000)
    if err:
        return []
    # Links written inside JSON or a script ("https:\/\/jobs.lever.co\/acme"), and links
    # written without a scheme ("//boards.greenhouse.io/embed/job_board?for=acme").
    body = body.replace("\\/", "/")
    found = []
    for m in re.finditer(r"(?:https?:)?//[^\s\"'<>)\\]+", body):
        link = m.group(0)
        board = parse("https:" + link if link.startswith("//") else link)
        if board and board not in found:
            found.append(dataclasses.replace(board, found="linked"))
    for m in _LEVER_EMBED.finditer(body):
        board = Board("lever", m.group(1), "linked")
        if board not in found:
            found.append(board)
    if not found:
        for name, rx, why in UNSUPPORTED:
            if rx.search(body):
                logging.getLogger("openroles").warning(
                    "%s uses %s, which openroles cannot read: %s", parts.netloc, name, why)
                break
    return found


# Small words that do not make a name distinctive.
_SMALL = {"and", "of", "the", "for", "de", "la", "le", "du", "des", "und", "y", "et"}
# Words that open many employers' names, so one alone is somebody else's board as often as
# this employer's: "Bank of Brackenhollow" is not the board "bank".
_GENERIC = {"bank", "first", "national", "royal", "united", "american", "canadian", "british",
            "global", "international", "general", "city", "state", "new", "north", "south",
            "east", "west", "central", "my", "open", "data", "digital", "health", "capital",
            "financial", "insurance", "group", "home", "best", "smart", "big", "great"}


def slugs(company: str) -> List[str]:
    """The board names an employer is likely to use: "Acme Data Ltd" -> acmedata, acme-data, acme.

    The first word alone is tried only for a name of at most two distinctive words whose first
    is not a word that opens many names: otherwise it is too often another employer's whole
    name. A web address's ending goes ("Monday.com" is monday).
    """
    name = re.sub(r"\.(?:com|io|ai|co|net|org|app|dev)\b", " ", company.lower())
    words = re.findall(r"[a-z0-9]+", name.replace("&", " and "))
    suffixes = {"inc", "ltd", "llc", "plc", "limited", "corp", "corporation", "co", "group",
                "gmbh", "ag", "sa", "bv", "the"}
    core = [w for w in words if w not in suffixes] or words
    distinctive = [w for w in core if w not in _SMALL]
    alone = core[0] if core and len(distinctive) <= 2 and core[0] not in _GENERIC else ""
    out = ["".join(core), "-".join(core), alone]
    return [s for s in dict.fromkeys(out) if s]


# Tried by name, most common first. Workday cannot be guessed from a name (its address
# needs a tenant, a data centre and a site name): give its careers URL instead.
GUESSED = ("greenhouse", "lever", "ashby", "workable", "teamtailor", "recruitee", "personio",
           "rippling", "jazzhr", "gem", "polymer", "manatal", "homerun")


def guess(company: str) -> List[Board]:
    """Boards found by trying the employer's likely board names on every system a name can
    find, found "guessed": a board under the name exists, and nothing yet shows it is this
    employer's. Each name is tried on every system at once, since each system is its own
    host (and each host still has its two requests at most): one after another, a name took
    as long as thirteen systems' answers and robots.txt files added up."""
    found: List[Board] = []
    with ThreadPoolExecutor(max_workers=len(GUESSED)) as pool:
        for slug in slugs(company):
            def tried(ats: str, slug: str = slug) -> bool:
                try:
                    return bool(READERS[ats].exists(slug))
                except Exception as e:  # noqa: BLE001  one system failing is no reason to lose the rest
                    logging.getLogger("openroles").debug("%s:%s could not be tried: %r", ats, slug, e)
                    return False
            for ats, exists in zip(GUESSED, pool.map(tried, GUESSED)):
                board = Board(ats, slug, "guessed")
                if exists and board not in found:
                    found.append(board)
            if found:
                break
    return found


def detect(target: str) -> List[Board]:
    """The boards behind a board URL, an "ats:token", a careers page or a company name, each
    with how it was found (`Board.found`): "named", "linked" or "guessed"."""
    board = parse(target)
    if board:
        return [board]
    target = target.strip()
    if re.match(r"^(https?://|www\.)|^[a-z0-9-]+(\.[a-z0-9-]+)+(/|$)", target, re.I):
        found = in_page(target)
        # A bare domain that is also a company's name ("Monday.com") is tried as a name
        # when its home page links to no board.
        if found or not re.match(r"^[a-z0-9-]+\.[a-z]{2,4}$", target, re.I):
            return found
    return guess(target)
