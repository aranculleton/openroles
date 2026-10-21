"""A posting's openroles id from its web address alone.

The same posting reaches a search more than once: read from the employer's board, and
found again on a job site whose link goes to the same apply page. `job_id(url)` gives the
`Job.id` openroles gives that posting when it reads the board, so the two copies can be
matched exactly, with nothing fetched. It answers only where the address carries the
system's own posting id in a shape that cannot be mistaken for anything else, and is ""
everywhere else: two different postings given one id would lose a role, while a copy left
unmatched only shows twice.
"""
from __future__ import annotations

import re
from urllib.parse import parse_qs, quote, unquote, urlsplit

from .providers import workday

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_GREENHOUSE = re.compile(r"^(?:job-boards|boards)(?:\.eu)?\.greenhouse\.io$")
_GREENHOUSE_PATH = re.compile(r"^/[^/]+/jobs/([0-9]+)/?$")
_DIGITS = re.compile(r"^[0-9]+$")
# Lever, Ashby and Rippling ids are UUIDs: /<board>/<id>, then perhaps /apply or
# /application. A board's other pages never have a UUID there.
_BOARD_UUID = re.compile(r"^/[^/]+/(" + _UUID + r")(?:/[A-Za-z]+)?/?$")
_RIPPLING_PATH = re.compile(r"^/(?:[A-Za-z]{2}-[A-Za-z]{2}/)?[^/]+/jobs/(" + _UUID + r")(?:/[A-Za-z]+)?/?$")
# apply.workable.com/<account>/j/<shortcode>/ and the short link apply.workable.com/j/<shortcode>.
_WORKABLE_PATH = re.compile(r"^(?:/[^/]+)?/j/([A-Za-z0-9]{6,})(?:/[A-Za-z]+)?/?$")
_PERSONIO = re.compile(r"^[a-z0-9][a-z0-9-]*\.jobs\.personio\.(?:de|com)$")
_PERSONIO_PATH = re.compile(r"^/job/([0-9]+)/?$")
_WORKDAY_HOST = re.compile(r"\.myworkday(?:jobs|site)\.com$")


def _gh_jid(query: dict) -> str:
    """The Greenhouse id any page with gh_jid carries: an employer's own careers page shows
    Greenhouse postings at its own address with the job id in the query. "" when there is
    none, and None when the address gives two that disagree."""
    jids = [j for j in query.get("gh_jid") or [] if _DIGITS.match(j)]
    if len(set(jids)) > 1:
        return None
    return f"gh-{jids[0]}" if jids else ""


def _greenhouse(host: str, path: str, query: dict) -> str:
    """The id in a Greenhouse board's own address: a posting page or its application form."""
    if not _GREENHOUSE.match(host):
        return ""
    m = _GREENHOUSE_PATH.match(path)
    if m:
        return f"gh-{m.group(1)}"
    token = (query.get("token") or [""])[0]
    if path.rstrip("/") == "/embed/job_app" and _DIGITS.match(token):
        return f"gh-{token}"
    return ""


def _workday(url: str, host: str, path: str) -> str:
    """wd-<tenant>-<the posting's last path segment>, from either Workday host.

    A posting's path is /job/<place>/<title>_<requisition>, or /details/<title>_<requisition>
    on a shared link; what follows it (/apply...) is not part of it. The segment must carry
    the "_" before its requisition, as every posting's does."""
    if not _WORKDAY_HOST.search(host):
        return ""
    m = workday.SITE_URL.search(url) or workday.MY_SITE.search(url)
    if not m:
        return ""
    parts = [p for p in path.split("/") if p]
    lowered = [p.lower() for p in parts]
    at = next((i for i, p in enumerate(lowered) if p in ("job", "details")), None)
    if at is None:
        return ""
    rest = parts[at + 1:]
    if "apply" in (p.lower() for p in rest):
        rest = rest[:[p.lower() for p in rest].index("apply")]
    if not rest or "_" not in rest[-1]:
        return ""
    segment = _workday_segment(rest[-1])
    return f"wd-{m['tenant'].lower()}-{segment}" if segment else ""


def _workday_segment(segment: str) -> str:
    """The id part of a Workday posting from the last segment of its address.

    The reader's id is the segment as the board's listing sends it, and the posting's
    address is that path with what workday.PATH_SAFE does not list percent-encoded and
    any "%" left as it is ("&" is %26, "ü" %C3%BC). So the segment is first written that
    way, which makes a link copied with a raw "ü" or "&" the reader's own address, and
    then decoded wherever the reader would have written exactly this from the decoded
    text. Where it would not (an escape it never writes, such as %2F or %25, or bytes that
    are not UTF-8), the listing sent the path with its escapes, and they are the id.

    One case cannot be told from the address: a listing that sends "M%C3%BCnchen" and
    one that sends "München" give the same address, and it is read as the second. A "/"
    never comes out of decoding, and bytes that are not UTF-8 never become U+FFFD."""
    try:
        written = quote(segment, safe=workday.PATH_SAFE)
    except UnicodeEncodeError:              # a lone surrogate: no address has one
        return ""
    try:
        text = unquote(written, errors="strict")
    except UnicodeDecodeError:
        return written
    return text if quote(text, safe=workday.PATH_SAFE) == written else written


def job_id(url: str) -> str:
    """The `Job.id` openroles gives the posting at `url`, read from the address alone, or ""
    when the address does not carry it.

        >>> job_id("https://boards.greenhouse.io/acme/jobs/4012345")
        'gh-4012345'
        >>> job_id("https://www.acme.example/careers/open-roles?gh_jid=4012345")
        'gh-4012345'
        >>> job_id("https://www.acme.example/careers")
        ''

    Greenhouse (its boards, its application form and any page with gh_jid), Lever,
    Ashby, Rippling, Workable, Personio and Workday. Nothing is fetched.
    """
    text = str(url or "").strip()
    if text.startswith("//"):                   # protocol-relative, as scraped HTML links are
        text = "https:" + text
    parts = urlsplit(text if "//" in text else "https://" + text)
    if parts.scheme not in ("http", "https"):
        return ""
    query = parse_qs(parts.query)
    from_query = _gh_jid(query)
    from_path = _from_path(parts, query)
    if from_query is None or (from_query and from_path and from_query != from_path):
        return ""                               # two ids for one address: neither is safe
    return from_path or from_query


def _from_path(parts, query: dict) -> str:
    """The id the address itself carries, gh_jid aside."""
    host = (parts.hostname or "").lower()
    path = parts.path or "/"
    found = _greenhouse(host, path, query)
    if found:
        return found
    # Lever, Ashby and Rippling give their UUIDs in lower case, and so does the id.
    if host in ("jobs.lever.co", "jobs.eu.lever.co"):
        m = _BOARD_UUID.match(path)
        return f"lv-{m.group(1).lower()}" if m else ""
    if host == "jobs.ashbyhq.com":
        m = _BOARD_UUID.match(path)
        return f"ab-{m.group(1).lower()}" if m else ""
    if host == "ats.rippling.com":
        m = _RIPPLING_PATH.match(path)
        return f"rp-{m.group(1).lower()}" if m else ""
    if host == "apply.workable.com":
        m = _WORKABLE_PATH.match(path)
        return f"wk-{m.group(1)}" if m else ""
    if _PERSONIO.match(host):
        m = _PERSONIO_PATH.match(path)
        return f"ps-{m.group(1)}" if m else ""
    return _workday(parts.geturl(), host, path)
