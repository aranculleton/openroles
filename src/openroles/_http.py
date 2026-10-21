"""The one place openroles talks to the network.

Polite by construction: at most PER_HOST requests in flight to any one host, a timeout
on every call, an honest User-Agent, robots.txt read once per host a day, and a host's
Crawl-delay kept between requests once its robots.txt has been read. A GET read before
sends the validators its last answer came with, so an unchanged board answers 304 and
sends nothing: in memory for the life of the process, and on disk across runs where the
caller names a cache directory (`openroles.configure(cache_dir=...)`, off by default).
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from collections import OrderedDict
from typing import Optional, Tuple

from . import __version__
from .robots import allowed, content_signals, crawl_delay, is_robots_body

USER_AGENT = f"openroles/{__version__} (+https://github.com/aranculleton/openroles)"
TIMEOUT = 20
PER_HOST = 2
RETRY_PAUSE = 2.0

_SLOTS: dict = {}
_SLOTS_LOCK = threading.Lock()
# Seconds between requests a host's robots.txt asks for, and when it may next be sent to.
_DELAYS: dict = {}
_NEXT: dict = {}
_PACE_LOCK = threading.Lock()


def _slot(host: str) -> threading.BoundedSemaphore:
    with _SLOTS_LOCK:
        return _SLOTS.setdefault(host.lower(), threading.BoundedSemaphore(PER_HOST))


# A GET's last answer, by URL, for hosts that send an ETag or a Last-Modified date: read
# again, the request carries them and an unchanged answer is a 304 with no body.
ETAG_BYTES = 32_000_000
_ETAGS: OrderedDict = OrderedDict()   # url -> (etag, last modified, body), oldest first
_ETAG_LOCK = threading.Lock()


def _remember(url: str, etag: str, body: str, modified: str = "") -> None:
    with _ETAG_LOCK:
        _ETAGS.pop(url, None)
        _ETAGS[url] = (etag, modified, body)
        size = sum(len(entry[-1]) for entry in _ETAGS.values())
        while _ETAGS and size > ETAG_BYTES:
            _, gone = _ETAGS.popitem(last=False)
            size -= len(gone[-1])


def _forget(url: str) -> None:
    with _ETAG_LOCK:
        _ETAGS.pop(url, None)
    if CACHE_DIR:
        try:
            os.remove(_cache_file(url))
        except OSError:
            pass


def _validators(headers) -> Optional[Tuple[str, str]]:
    """(ETag, Last-Modified) an answer can be asked about again with, or None: an answer
    with neither, or one its host marks no-store, is not kept."""
    if "no-store" in (headers.get("Cache-Control") or "").lower():
        return None
    etag = (headers.get("ETag") or "").strip()
    modified = (headers.get("Last-Modified") or "").strip()
    return (etag, modified) if etag or modified else None


# ------------------------------------------------------------------ on disk

# Where answers are kept between runs: "" keeps nothing on disk (the default). Set with
# openroles.configure(cache_dir=...). Each answer is one gzipped file named for a hash of
# its address, readable by its owner alone; the folder holds at most CACHE_BYTES, and an
# answer not asked for in CACHE_DAYS goes. It only ever spares a download: every read
# still asks the host, and a 304 is the host saying nothing changed.
CACHE_DIR = ""
CACHE_BYTES = 500_000_000
CACHE_DAYS = 30
PRUNE_EVERY = 500          # writes between tidies of the folder, after the first
_WRITES: dict = {}
_PRUNE_LOCK = threading.Lock()


def _cache_file(url: str) -> str:
    name = hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json.gz"
    return os.path.join(CACHE_DIR, "http", name)


def _disk_get(url: str) -> Optional[Tuple[str, str, str]]:
    """(etag, last modified, body) kept on disk for `url`, or None. An unreadable or
    foreign file is a miss, never an error."""
    if not CACHE_DIR:
        return None
    try:
        with gzip.open(_cache_file(url), "rt", encoding="utf-8") as fh:
            entry = json.load(fh)
    except (OSError, EOFError, ValueError, zlib.error):
        return None
    if not isinstance(entry, dict) or entry.get("url") != url:
        return None
    etag, modified, body = (entry.get(k) for k in ("etag", "last_modified", "body"))
    if not all(isinstance(x, str) for x in (etag, modified, body)) or not (etag or modified):
        return None
    return etag, modified, body


def _disk_put(url: str, etag: str, modified: str, body: str) -> None:
    if not CACHE_DIR:
        return
    folder = os.path.join(CACHE_DIR, "http")
    tmp = ""
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")      # owner-only
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as fh:
            fh.write(json.dumps({"url": url, "etag": etag, "last_modified": modified,
                                 "body": body}, ensure_ascii=False).encode("utf-8"))
        os.replace(tmp, _cache_file(url))
        tmp = ""
    except OSError:
        return                      # a cache that cannot be written is only a slower run
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    with _PRUNE_LOCK:
        n = _WRITES.get(folder, 0)
        _WRITES[folder] = n + 1
    if n % PRUNE_EVERY == 0:
        prune(folder)


def _touch(url: str) -> None:
    """An answer asked for again counts as recent, so pruning keeps what is in use."""
    if CACHE_DIR:
        try:
            os.utime(_cache_file(url))
        except OSError:
            pass


def prune(folder: str, now: Optional[float] = None) -> None:
    """Answers older than CACHE_DAYS go, then the oldest until the folder is under
    CACHE_BYTES; a write cut off more than an hour ago goes too."""
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return
    kept = []
    for e in entries:
        try:
            st = e.stat()
        except OSError:
            continue
        stale = (e.name.endswith(".tmp") and now - st.st_mtime > 3600) or (
            e.name.endswith(".json.gz") and now - st.st_mtime > CACHE_DAYS * 86400)
        if stale:
            try:
                os.remove(e.path)
            except OSError:
                pass
        elif e.name.endswith(".json.gz"):
            kept.append((st.st_mtime, st.st_size, e.path))
    total = sum(size for _, size, _ in kept)
    for _, size, path in sorted(kept):
        if total <= CACHE_BYTES:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def _wait_turn(host: str) -> None:
    """Hold a request back until the host's Crawl-delay since the last one has passed."""
    key = host.lower()
    delay = _DELAYS.get(key, 0.0)
    if not delay:
        return
    with _PACE_LOCK:
        now = time.monotonic()
        start = max(now, _NEXT.get(key, 0.0))
        _NEXT[key] = start + delay
    if start > now:
        time.sleep(start - now)


def _read(fh, limit: int) -> Tuple[str, bool]:
    """(the response body as text, unzipped when it came gzipped, at most `limit` bytes;
    whether that is all of it). A body cut at the limit is never kept for next time."""
    raw = fh.read(limit)
    whole = len(raw) < limit
    if (fh.headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, limit)
        except zlib.error:
            raw = gzip.decompress(raw)
        whole = whole and len(raw) < limit
        raw = raw[:limit]
    return raw.decode("utf-8", "replace"), whole


def _body(fh, limit: int) -> str:
    """The response body as text, unzipped when it came gzipped, at most `limit` bytes."""
    return _read(fh, limit)[0]


def request(url: str, payload: Optional[dict] = None,
            accept: str = "application/json") -> Tuple[Optional[object], Optional[str]]:
    """(parsed JSON, None) or (None, why). A GET, or a JSON POST when `payload` is given."""
    raw, err = request_raw(url, payload, accept)
    if err:
        return None, err
    try:
        return json.loads(raw), None
    except ValueError:
        return None, "the response was not JSON"


class _HandBack(urllib.request.HTTPRedirectHandler):
    """Hands a redirect back to request_raw, which looks at where it leads first."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_HandBack)
REDIRECTS = (301, 302, 303, 307, 308)
MAX_REDIRECTS = 5


def _urlopen(req, timeout):
    return _OPENER.open(req, timeout=timeout)


def request_raw(url: str, payload: Optional[dict] = None,
                accept: str = "*/*", limit: int = 100_000_000) -> Tuple[str, Optional[str]]:
    """(body as text, None) or ("", why).

    A redirect is followed only after looking at where it leads: to another host, only
    when that host's robots.txt does not refuse the path. A board's own robots.txt says
    nothing about the host it hands a reader on to.
    """
    # gzip: a large board's JSON is a third of the size on the wire.
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    for _hop in range(MAX_REDIRECTS + 1):
        body, err, onward = _one(url, data, headers, limit)
        if onward is None:
            return body, err
        nxt, code = onward
        old, new = urllib.parse.urlsplit(url), urllib.parse.urlsplit(nxt)
        if new.scheme not in ("http", "https") or not new.netloc:
            return "", f"HTTP {code} to an address that is not a web page"
        if new.netloc.lower() != old.netloc.lower():
            why = robots_refuses(new.netloc, [new.path or "/"])
            if why:
                return "", f"redirected to {new.netloc}, and {why}"
        if code == 303 or (code in (301, 302) and data is not None):
            data = None
            headers.pop("Content-Type", None)
        url = nxt
    return "", f"more than {MAX_REDIRECTS} redirects"


def _one(url: str, data, headers: dict, limit: int):
    """(body, None, None), ("", why, None), or ("", None, (next url, status)) for a redirect."""
    headers = dict(headers)
    host = urllib.parse.urlsplit(url).netloc
    cached = None
    if data is None:                 # a POST is never answered from what was kept
        with _ETAG_LOCK:
            cached = _ETAGS.get(url)
        cached = cached or _disk_get(url)
    if cached:
        if cached[0]:
            headers["If-None-Match"] = cached[0]
        if cached[1]:
            headers["If-Modified-Since"] = cached[1]
    err = None
    # One retry, after a pause, for a dropped connection or a gateway error. Never for
    # 429 or 503: those mean slow down, and the caller decides what that means.
    for attempt in range(2):
        if attempt:
            time.sleep(RETRY_PAUSE)
        try:
            req = urllib.request.Request(url, data=data, headers=headers,
                                         method="POST" if data is not None else "GET")
            with _slot(host):
                _wait_turn(host)
                with _urlopen(req, timeout=TIMEOUT) as fh:
                    body, whole = _read(fh, limit)
                    keep = _validators(fh.headers) if data is None and whole else None
            if keep:
                _remember(url, keep[0], body, keep[1])
                _disk_put(url, keep[0], keep[1], body)
            elif cached:
                _forget(url)         # what was kept no longer describes this answer
            return body, None, None
        except urllib.error.HTTPError as e:
            if e.code == 304 and cached:
                _remember(url, cached[0], cached[2], cached[1])
                _touch(url)
                return cached[2], None, None
            if e.code in REDIRECTS and e.headers and e.headers.get("Location"):
                return "", None, (urllib.parse.urljoin(url, e.headers["Location"]), e.code)
            err = f"HTTP {e.code}"
            if e.code not in (502, 504):
                break
        # HTTPException covers a body cut off mid-read, which is not an OSError.
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            err = type(e).__name__
    return "", err, None


# ------------------------------------------------------------------ robots.txt

# Statuses that mean no policy is published. RFC 9309 section 2.3.1.3 reads an
# unavailable robots.txt as no restriction. A 403 is left out on purpose: on
# robots.txt it is usually a firewall refusing an unknown client. A 429, a 5xx or
# no answer means the policy could not be read, which the RFC treats as disallow.
NO_POLICY = {401, 404, 410}
# A site whose robots.txt says "Content-Signal: ai-input=no" asks that its content not be
# fed to an AI model. openroles is read by AI agents (its MCP server) and by searches that
# have a model read each posting, so it honours that by default. A caller that never
# passes what it reads to a model may set this to False.
RESPECT_AI_INPUT = True
AGENTS = ("*", "openroles")

_ROBOTS: dict = {}
_ROBOTS_LOCK = threading.Lock()
# RFC 9309 section 2.4: a cached robots.txt should not be used for more than 24 hours,
# which matters to a long-running `openroles mcp` server.
ROBOTS_TTL = 24 * 3600


def robots_txt(host: str) -> Tuple[int, str]:
    """(HTTP status, body) for https://<host>/robots.txt, fetched once a day per process.

    Status 0 means no answer at all. A Crawl-delay it declares for openroles is kept
    between requests to that host from then on.
    """
    key = host.lower()
    with _ROBOTS_LOCK:
        if key in _ROBOTS and time.monotonic() - _ROBOTS[key][0] < ROBOTS_TTL:
            return _ROBOTS[key][1]
    req = urllib.request.Request(f"https://{key}/robots.txt",
                                 headers={"User-Agent": USER_AGENT,
                                          "Accept": "text/plain,*/*"})
    try:
        with _slot(key):
            with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
                got = (fh.status, fh.read(512_000).decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        got = (e.code, "")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError):
        got = (0, "")
    with _ROBOTS_LOCK:
        _ROBOTS[key] = (time.monotonic(), got)
    if got[0] == 200 and is_robots_body(got[1]):
        _DELAYS[key] = max(crawl_delay(got[1], a) for a in AGENTS)
    return got


def _no_ai(host: str, body: str) -> str:
    if RESPECT_AI_INPUT and any(content_signals(body, a).get("ai-input") == "no" for a in AGENTS):
        return (f"robots.txt on {host} asks that its content not be used as AI input "
                "(Content-Signal: ai-input=no)")
    return ""


def robots_allows(host: str, paths) -> Tuple[bool, str]:
    """(may these paths be read, why), from the host's robots.txt."""
    status, body = robots_txt(host)
    if status == 200:
        if not is_robots_body(body):
            return False, ("robots.txt answered 200 with something that is not a robots "
                           "file, so permission is unconfirmed")
        no = _no_ai(host, body)
        if no:
            return False, no
        for path in paths:
            for agent in AGENTS:
                if not allowed(body, agent, path):
                    return False, f"robots.txt on {host} disallows {path}"
        return True, "robots.txt allows it"
    if status in NO_POLICY:
        return True, f"no robots.txt (HTTP {status}), which RFC 9309 reads as no restriction"
    seen = f"HTTP {status}" if status else "no answer"
    return False, f"robots.txt on {host} could not be read ({seen}), so permission is unconfirmed"


def robots_refuses(host: str, paths) -> str:
    """Why robots.txt refuses these paths, or "" when it does not, for an endpoint its
    vendor documents as a public API: there only an explicit Disallow refuses, and a
    robots.txt that cannot be read is not taken for one. Reading it also learns the
    host's Crawl-delay."""
    status, body = robots_txt(host)
    if status != 200 or not is_robots_body(body):
        return ""
    no = _no_ai(host, body)
    if no:
        return no
    for path in paths:
        for agent in AGENTS:
            if not allowed(body, agent, path):
                return f"robots.txt on {host} disallows {path}"
    return ""
