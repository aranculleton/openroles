"""Any careers site that publishes its jobs for search engines: a sitemap listing the job
pages, and on each page a schema.org JobPosting in JSON-LD, the markup Google for Jobs
asks every careers site for.

This is how openroles reaches systems that publish no open job API, among them iCIMS,
Phenom and Eightfold sites: the employer has already published every role this way, for
anyone, to be found. It is read only as far as the site allows:

  - its robots.txt must be readable and must allow the sitemap and each job page;
  - its Crawl-delay is kept between requests, so reading is slow where it asks it to be;
  - a site whose robots.txt asks that its content not be AI input is not read;
  - at most `limit` pages a call, newest first where the sitemap's dates are real, so one
    large site cannot take a run over.

A page whose JobPosting is added by script in the browser (Oracle's sites do this) carries
none in its HTML, and is skipped. The token is the careers site's address, its host and
any path the job pages sit under: "careers.acme.com" or "careers.acme.com/us/en".
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html as _html
import json
import re
from typing import Callable, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

from .. import _http
from ..models import BoardError, Job, RobotsDisallowed, clean, html_to_text, iso_day, pay, workplace_of
from ._xml import parse

LIMIT = 40              # job pages read in one call
MAX_SITEMAPS = 20       # sitemap files followed from an index
# What a job page's address looks like on the systems this has been checked against:
# /job/..., /jobs/123, /careers/job/..., /JobDetail/...
JOB_PATH = re.compile(r"/(?:jobs?|jobdetail|vacanc(?:y|ies)|positions?|openings?)(?:/|-|$)", re.I)
# A JSON-LD script: its opening tag, the type in that tag, and the tag that closes it. The
# type may be quoted or not: HTML allows type=application/ld+json, and minified pages write
# it that way.
_SCRIPT = re.compile(r"<script\b", re.I)
_LD_TYPE = re.compile(r"\btype\s*=\s*[\"']?application/ld\+json\b", re.I)
_SCRIPT_END = re.compile(r"</script>", re.I)
# Lines some pages wrap a script in to hide it from older parsers: comment and CDATA markers.
_FRAMING = re.compile(r"//|/\*|\*/|<!--|--!?>|<!\[CDATA\[|\]\]>|\s+")


def site_of(token: str) -> Tuple[str, str]:
    """(host, path prefix) of a careers site: "careers.acme.com/us/en" is
    ("careers.acme.com", "/us/en")."""
    t = (token or "").strip()
    parts = urlsplit(t if "//" in t else "https://" + t)
    return parts.netloc.lower(), parts.path.rstrip("/")


def _date(value) -> str:
    v = clean(value)
    for fmt, n in (("%Y-%m-%d", 10), ("%d-%b-%Y", 11)):
        try:
            return iso_day(dt.datetime.strptime(v[:n], fmt).date().isoformat())
        except ValueError:
            continue
    return ""


def _sitemap(url: str):
    """([(page url, lastmod)], [child sitemap urls]) from one sitemap file."""
    if url.lower().endswith(".gz"):
        return [], []
    body, err = _http.request_raw(url, accept="application/xml,text/xml;q=0.9,*/*;q=0.1",
                                  limit=20_000_000)
    root = parse(body) if not err else None
    if root is None:
        return [], []
    tag = root.tag.rsplit("}", 1)[-1].lower()
    pages, children = [], []
    for entry in root:
        loc = lastmod = ""
        for field in entry:
            name = field.tag.rsplit("}", 1)[-1].lower()
            if name == "loc":
                loc = clean(field.text)
            elif name == "lastmod":
                lastmod = _date(field.text)
        if not loc:
            continue
        (children if tag == "sitemapindex" else pages).append(loc if tag == "sitemapindex" else (loc, lastmod))
    return pages, children


def _sitemap_urls(host: str, prefix: str = "") -> List[str]:
    """The sitemaps a site's robots.txt names, else the one under the careers path, else
    the site's /sitemap.xml."""
    status, body = _http.robots_txt(host)
    named = re.findall(r"(?im)^\s*sitemap\s*:\s*(\S+)", body) if status == 200 else []
    guesses = [f"https://{host}{prefix}/sitemap.xml"] if prefix else []
    return list(dict.fromkeys(named)) or guesses + [f"https://{host}/sitemap.xml"]


def _words(url: str) -> set:
    path = urlsplit(url).path.lower()
    return set(re.findall(r"[a-z]{3,}", path))


def job_pages(token: str, queries: Optional[Iterable[str]] = None) -> List[Tuple[str, str]]:
    """[(job page url, lastmod)] the site's sitemaps list under the token's path, newest first
    when the sitemap dates them. With `queries`, a page whose address carries words keeps
    only when every word of one query (its first five letters) is among them; a page whose
    address is only a number is kept, since nothing in it can be judged."""
    host, prefix = site_of(token)
    todo, seen_maps, pages = _sitemap_urls(host, prefix), set(), {}
    while todo and len(seen_maps) < MAX_SITEMAPS:
        url = todo.pop(0)
        if url in seen_maps:
            continue
        seen_maps.add(url)
        if urlsplit(url).netloc.lower() not in ("", host):
            continue
        found, children = _sitemap(url)
        todo.extend(c for c in children if c not in seen_maps)
        for loc, lastmod in found:
            p = urlsplit(loc)
            if p.netloc.lower() == host and p.path.startswith(prefix or "/") and JOB_PATH.search(p.path):
                pages.setdefault(loc, lastmod)
    stems = [[w[:5] for w in q.lower().split()] for q in queries or () if q.strip()]
    out = []
    for loc, lastmod in pages.items():
        words = _words(loc) - {"job", "jobs", "career", "careers", "jobdetail", "lang", "en", "us"}
        if stems and words and not any(all(any(w.startswith(s) for w in words) for s in q) for q in stems):
            continue
        out.append((loc, lastmod))
    if len({m for _, m in out if m}) > 1:
        out.sort(key=lambda x: x[1], reverse=True)
    return out


def _lower(obj):
    if isinstance(obj, dict):
        return {str(k).lower(): _lower(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_lower(v) for v in obj]
    return obj


def _unframed(text: str) -> str:
    """The script without the comment or CDATA lines at either end.

    In one pass from each end and one slice: dropping lines one at a time from the front
    of a list moved every line after them each time, and a script that opened with a few
    hundred thousand comment lines held a read for minutes."""
    lines = text.split("\n")
    first, last = 0, len(lines)
    while first < last and not _FRAMING.sub("", lines[first]):
        first += 1
    while last > first and not _FRAMING.sub("", lines[last - 1]):
        last -= 1
    return "\n".join(lines[first:last])


def _leading(text: str) -> list:
    """Every complete JSON value `text` starts with, in order; what follows the last is
    left (a stray semicolon or brace)."""
    decoder = json.JSONDecoder(strict=False)
    out, i = [], 0
    while True:
        while i < len(text) and text[i] in " \t\r\n;":
            i += 1
        if i >= len(text):
            return out
        try:
            value, i = decoder.raw_decode(text, i)
        except (ValueError, RecursionError):        # nested deeper than Python can follow
            return out
        out.append(value)


def json_values(block: str) -> list:
    """The JSON in one JSON-LD script, read the way careers sites actually write it.

    A strict reader lost whole sites: a description pasted with its line breaks puts a
    raw newline inside a JSON string, which strict JSON refuses, so the page read as
    having no JobPosting. Also read: a script wrapped in comment or CDATA lines, one
    HTML-entity-encoded as a whole, and junk after a complete value. Nothing is guessed
    beyond that: a JavaScript comment with words in it, a trailing comma, or a broken
    escape or quote is not mended, and a script still unreadable gives nothing.
    """
    text = block.strip()
    found = _leading(text)
    if found:
        return found
    unframed = _unframed(text)
    found = _leading(unframed)
    if found:
        return found
    unescaped = _html.unescape(unframed)
    return _leading(unescaped) if unescaped != unframed else []


def _ld_scripts(html: str) -> List[str]:
    """The text inside every JSON-LD script on a page, in order.

    In one pass. A single regular expression for the whole script looked to the end of
    the page for a closing tag after every opening one that had none, and for a ">" after
    every "<script" that had none, so a hostile page of 5 MB could hold one read for hours.
    Here each is looked for once: when none follows, no later script can be complete
    either. What it finds is what that expression found."""
    out, i = [], 0
    while True:
        opening = _SCRIPT.search(html, i)
        if not opening:
            return out
        end = html.find(">", opening.end())
        if end < 0:
            return out
        if not _LD_TYPE.search(html, opening.end(), end):
            # Every "<script" before this ">" ends its tag here too, and none of them can
            # hold a type this whole stretch does not.
            i = end + 1
            continue
        closing = _SCRIPT_END.search(html, end + 1)
        if not closing:
            return out
        out.append(html[end + 1:closing.start()])
        i = closing.end()


def postings(html: str) -> List[dict]:
    """Every schema.org JobPosting in a page's JSON-LD, keys lower-cased (some sites write
    "DatePosted")."""
    out = []
    for block in _ld_scripts(html or ""):
        try:
            stack = [_lower(data) for data in json_values(block)]
        except RecursionError:      # JSON nested deeper than this can follow: as unreadable
            continue
        while stack:
            node = stack.pop()
            if isinstance(node, list):
                stack.extend(node)
            elif isinstance(node, dict):
                kind = node.get("@type")
                kinds = kind if isinstance(kind, list) else [kind]
                if any(str(k).lower() == "jobposting" for k in kinds):
                    out.append(node)
                stack.extend(v for k, v in node.items() if k == "@graph")
    return out


def _name(value) -> str:
    return clean(value.get("name")) if isinstance(value, dict) else clean(value)


def _places(p: dict) -> List[str]:
    locs = p.get("joblocation")
    out = []
    for loc in locs if isinstance(locs, list) else [locs]:
        if not isinstance(loc, dict):
            continue
        addr = loc.get("address")
        if isinstance(addr, dict):
            parts = [clean(addr.get("addresslocality")), clean(addr.get("addressregion")),
                     _name(addr.get("addresscountry"))]
            out.append(", ".join(x for x in parts if x))
        else:
            out.append(clean(addr) or _name(loc))
    if str(p.get("joblocationtype") or "").upper() == "TELECOMMUTE":
        req = p.get("applicantlocationrequirements")
        where = [_name(r) for r in (req if isinstance(req, list) else [req]) if r]
        out += [f"Remote, {w}" if w else "Remote" for w in (where or [""])]
    return list(dict.fromkeys(x for x in out if x))


def _pay(p: dict) -> str:
    s = p.get("basesalary")
    if not isinstance(s, dict):
        return ""
    v = s.get("value") if isinstance(s.get("value"), dict) else {"value": s.get("value")}
    lo, hi = v.get("minvalue"), v.get("maxvalue")
    if lo is None and hi is None:
        lo = v.get("value")
    if lo is None and hi is None:
        return ""

    def num(x):
        try:
            return f"{float(x):,.0f}"
        except (TypeError, ValueError, OverflowError):
            return clean(x)
    span = "-".join(num(x) for x in (lo, hi) if x is not None)
    return clean(f"{clean(s.get('currency')) or clean(p.get('salarycurrency'))} {span} "
                 f"{clean(v.get('unittext')).lower()}")


def _salary(p: dict) -> dict:
    """schema.org baseSalary as numbers: a MonetaryAmount whose value is a range
    (minValue, maxValue) or one figure, which is then both ends."""
    s = p.get("basesalary")
    if not isinstance(s, dict):
        return pay()
    v = s.get("value") if isinstance(s.get("value"), dict) else {"value": s.get("value")}
    lo, hi = v.get("minvalue"), v.get("maxvalue")
    if lo is None and hi is None:
        lo = hi = v.get("value")
    return pay(lo, hi, clean(s.get("currency")) or p.get("salarycurrency"), v.get("unittext"))


def _job(token: str, page: str, p: dict) -> Optional[Job]:
    title = clean(p.get("title"))
    if not title:
        return None
    places = _places(p)
    remote = str(p.get("joblocationtype") or "").upper() == "TELECOMMUTE"
    ident = p.get("identifier")
    ident = clean(ident.get("value") if isinstance(ident, dict) else ident)
    kinds = p.get("employmenttype")
    return Job(
        id="cs-" + (ident or hashlib.sha1(page.encode("utf-8")).hexdigest()[:12]),
        ats="careersite",
        board=token,
        title=title,
        url=clean(p.get("url")) if str(p.get("url") or "").startswith("http") else page,
        location="; ".join(places),
        locations=places,
        remote=True if remote else None,
        posted=_date(p.get("dateposted")),
        employment_type=", ".join(clean(k) for k in kinds) if isinstance(kinds, list) else clean(kinds),
        compensation=_pay(p),
        **_salary(p),
        deadline=_date(p.get("validthrough")),
        description=html_to_text(p.get("description")) or None,
        workplace="remote" if remote else workplace_of(*places),
    )


def exists(token: str) -> bool:
    try:
        host, prefix = site_of(token)
        return bool(host) and _http.robots_allows(host, [prefix or "/"])[0] and bool(job_pages(token))
    except BoardError:
        return False


def fetch(token: str, queries: Optional[Iterable[str]] = None, limit: int = LIMIT,
          skip: Optional[Callable[[str], bool]] = None, report: Optional[dict] = None) -> List[Job]:
    """The roles on up to `limit` of the site's job pages, newest first. `skip` is given each
    page address and says yes to one the caller already has, so successive calls move on
    through a large site. `report`, when given, is filled with "pages_listed",
    "pages_read" and "page_errors" ({url: why})."""
    host, prefix = site_of(token)
    if not host:
        raise BoardError(f"careersite:{token}: not a careers site address")
    ok, why = _http.robots_allows(host, [prefix or "/"])
    if not ok:
        raise RobotsDisallowed(f"careersite:{token}: {why}")
    listed = job_pages(token, queries)
    if not listed:
        raise BoardError(f"careersite:{token}: its sitemap lists no job pages under {prefix or '/'}")
    todo = [u for u, _ in listed if not (skip and skip(u))][:limit]
    jobs, errors = [], {}
    for page in todo:
        ok, why = _http.robots_allows(host, [urlsplit(page).path or "/"])
        if not ok:
            errors[page] = why
            continue
        html, err = _http.request_raw(page, accept="text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
                                      limit=5_000_000)
        found = postings(html) if not err else []
        if not found:
            errors[page] = err or "no JobPosting on the page"
            continue
        job = _job(token, page, found[0])
        if job:
            jobs.append(job)
    if report is not None:
        report.update(pages_listed=len(listed), pages_read=len(todo), page_errors=errors)
    return jobs


def hosts(token: str) -> List[str]:
    """The hosts reading this board calls, for a network allowlist. Nothing is fetched."""
    host, _prefix = site_of(token)
    return [host] if host else []
