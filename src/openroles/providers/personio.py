"""Personio: an account's open positions as XML, the feed its own careers page offers.

Personio documents it: "Current open job postings can be retrieved in XML format under
myaccount.jobs.personio.de/xml" (developer.personio.de, "Retrieving open positions"), with
no credentials. Accounts live on .de or .com and the XML is not redirected between them,
so both are tried. Descriptions come in German unless `language=en` asks otherwise.

A host's robots.txt is read first and an explicit Disallow is obeyed. Personio answers a
name that is not an account with "Disallow: /", so that also reads as no board.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, failed, html_to_text, iso_day, workplace_of
from ._xml import parse, text_of

DOMAINS = ("jobs.personio.de", "jobs.personio.com")


def hosts_of(token: str) -> List[str]:
    """The hosts an account may answer on: "acme" is acme.jobs.personio.de, then .com."""
    t = (token or "").strip().lower()
    if t.startswith("http"):
        t = t.split("//", 1)[1]
    t = t.split("/", 1)[0]
    if any(t.endswith(d) for d in DOMAINS):
        return [t]
    return [f"{t}.{d}" for d in DOMAINS]


def _feed(token: str, language: str = "en") -> Tuple[Optional[object], str, str]:
    """(root element, host, why not) for the first host that serves the feed."""
    why, refused = "", 0
    hosts = hosts_of(token)
    for host in hosts:
        no = _http.robots_refuses(host, ["/xml"])
        if no:
            refused += 1
            why = why or no
            continue
        body, err = _http.request_raw(f"https://{host}/xml?language={language}",
                                      accept="application/xml,text/xml;q=0.9,*/*;q=0.1",
                                      limit=30_000_000)
        root = parse(body) if not err else None
        if root is not None and root.tag == "workzag-jobs":
            return root, host, ""
        why = why or err or "not a Personio positions feed"
    if refused == len(hosts):
        raise RobotsDisallowed(f"personio:{token}: {why} (Personio answers a name that is not "
                               "an account this way too)")
    return None, "", why


def exists(token: str) -> bool:
    try:
        return _feed(token)[0] is not None
    except BoardError:
        return False


def _description(position) -> Optional[str]:
    parts = []
    for block in position.findall("jobDescriptions/jobDescription"):
        head, body = text_of(block, "name"), html_to_text(block.findtext("value") or "")
        if head or body:
            parts.append(f"{head}\n{body}".strip())
    return "\n\n".join(parts) or None


def fetch(token: str, language: str = "en") -> List[Job]:
    root, host, why = _feed(token, language)
    if root is None:
        raise BoardError(f"personio:{token}: {failed(why, 'account name, or its XML feed is off')}")
    out = []
    for p in root.findall("position"):
        ident, title = text_of(p, "id"), text_of(p, "name")
        if not ident or not title:
            continue
        offices = [x for x in [text_of(p, "office")] if x]
        kind = " ".join(x for x in (text_of(p, "employmentType"), text_of(p, "schedule")) if x)
        workplace = workplace_of(*offices)
        out.append(Job(
            id=f"ps-{ident}",
            ats="personio",
            board=token,
            title=title,
            url=f"https://{host}/job/{ident}",
            location="; ".join(offices),
            locations=offices,
            remote=True if workplace == "remote" else None,
            posted=iso_day(text_of(p, "createdAt")),
            department=text_of(p, "department") or text_of(p, "subcompany"),
            employment_type=clean(kind),
            description=_description(p),
            workplace=workplace,
        ))
    return out


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    return hosts_of(token)
