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
import math
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


# A GET's last answer, for hosts that send an ETag or a Last-Modified date: read again, the
# request carries them and an unchanged answer is a 304 with no body. Kept by address and
# the Accept it was asked with, since one address can answer JSON to one and HTML to
# another, and a host that only sends Last-Modified would answer 304 to both.
ETAG_BYTES = 32_000_000
# (url, accept) -> (etag, last modified, body, when it was last read in full), oldest first
_ETAGS: OrderedDict = OrderedDict()
_ETAG_LOCK = threading.Lock()
Key = Tuple[str, str]
# An answer kept with a Last-Modified date and no ETag is asked about with If-Modified-Since
# for this long after it was last read in full (a 304 does not count), then read in full
# once. A host whose Last-Modified stays put while its data changes answers 304 to every
# such question, and each 304 counts as recent use, so without a bound its kept copy would
# be the answer for good. An ETag names the body itself and has no such bound.
MODIFIED_MAX_AGE = 24 * 3600
# The wall clock MODIFIED_MAX_AGE is measured on, in seconds since 1970. A name of its own,
# so a test can move it on a day without waiting one.
_now = time.time
# The characters the kept bodies hold, and the store that total is for. A running total:
# adding every body up again on each insert made a run of n answers cost n squared. A store
# put in _ETAGS's place (a fresh process in a test) is counted once, the first time.
_HELD: list = [None, 0]


def _held() -> int:
    if _HELD[0] is not _ETAGS:
        _HELD[:] = [_ETAGS, sum(len(entry[2]) for entry in _ETAGS.values())]
    return _HELD[1]


def _remember(key: Key, etag: str, body: str, modified: str = "",
              fetched: Optional[float] = None) -> None:
    """Keep an answer in memory. `fetched` is when it was last read in full: now, unless
    a 304 is sending back one read earlier."""
    with _ETAG_LOCK:
        size = _held()
        old = _ETAGS.pop(key, None)
        if old is not None:
            size -= len(old[2])
        _ETAGS[key] = (etag, modified, body, _now() if fetched is None else fetched)
        size += len(body)
        while _ETAGS and size > ETAG_BYTES:
            _, gone = _ETAGS.popitem(last=False)
            size -= len(gone[2])
        _HELD[1] = size


def _forget(key: Key) -> None:
    with _ETAG_LOCK:
        size = _held()
        old = _ETAGS.pop(key, None)
        if old is not None:
            _HELD[1] = size - len(old[2])
    if CACHE_DIR:
        try:
            os.remove(_cache_file(key))
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
# its address, readable by its owner alone; the folder holds about CACHE_BYTES (see
# PRUNE_SECONDS), and an answer not asked for in CACHE_DAYS goes. It only ever spares a
# download: every read still asks the host, and a 304 is the host saying nothing changed.
CACHE_DIR = ""
CACHE_BYTES = 500_000_000
CACHE_DAYS = 30
# The folder is looked at whole on its first use in a process, read or write, so a run of
# only 304s still drops what is past CACHE_DAYS; then every PRUNE_SECONDS, for a long-running
# server; and whenever a running total of what this process wrote takes it past CACHE_BYTES.
# The total starts from the look, so another process writing to the same folder at the same
# time is counted at this one's next look: the cap holds for each process, and two writing
# to one folder at once can take it past the cap until one of them looks again.
PRUNE_SECONDS = 3600
# A look that finds the folder over CACHE_BYTES takes it down to this share of it. Taken
# down only to the cap, the next write passed it again, and every write after that looked
# at the whole folder (a scan, a stat of every file and a sort) while holding the lock
# every read waits on.
PRUNE_TO = 0.9
# Written into every file. A file without it, or with another, is a miss and is replaced on
# the next full answer: so a release that changes what a file means, or one that must not
# trust what an earlier build wrote (before 0.3.0 a body cut short by the network could be
# kept), says so by raising it.
CACHE_FORMAT = 1
_TIDY: dict = {}           # folder -> [bytes it holds as far as this process knows, last look]
_PRUNE_LOCK = threading.Lock()


def _this_format(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and v == CACHE_FORMAT


def _cache_file(key: Key) -> str:
    name = hashlib.sha256(json.dumps(list(key)).encode("utf-8")).hexdigest() + ".json.gz"
    return os.path.join(CACHE_DIR, "http", name)


def _disk_get(key: Key) -> Optional[Tuple[str, str, str, float]]:
    """(etag, last modified, body, when it was last read in full) kept on disk for (url,
    accept), or None. An unreadable or foreign file is a miss, never an error; one that
    does not say when it was read reads as read long ago."""
    if not CACHE_DIR:
        return None
    _tidy(os.path.join(CACHE_DIR, "http"))
    try:
        with gzip.open(_cache_file(key), "rt", encoding="utf-8") as fh:
            entry = json.load(fh)
    except (OSError, EOFError, ValueError, zlib.error, RecursionError):
        return None
    if not isinstance(entry, dict) or not _this_format(entry.get("v")) or \
            (entry.get("url"), entry.get("accept")) != key:
        return None
    etag, modified, body = (entry.get(k) for k in ("etag", "last_modified", "body"))
    if not all(isinstance(x, str) for x in (etag, modified, body)) or not (etag or modified):
        return None
    fetched = entry.get("fetched")
    real = isinstance(fetched, (int, float)) and not isinstance(fetched, bool) and math.isfinite(fetched)
    return etag, modified, body, float(fetched) if real else 0.0


def _disk_put(key: Key, etag: str, modified: str, body: str,
              fetched: Optional[float] = None) -> None:
    if not CACHE_DIR:
        return
    fetched = _now() if fetched is None else fetched
    folder = os.path.join(CACHE_DIR, "http")
    path = _cache_file(key)
    tmp = ""
    try:
        os.makedirs(folder, mode=0o700, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")      # owner-only
        with os.fdopen(fd, "wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as fh:
            fh.write(json.dumps({"v": CACHE_FORMAT, "url": key[0], "accept": key[1],
                                 "etag": etag, "last_modified": modified, "body": body,
                                 "fetched": fetched},
                                ensure_ascii=False).encode("utf-8"))
        grown = os.path.getsize(tmp)
        try:
            grown -= os.path.getsize(path)          # the copy this one replaces
        except OSError:
            pass
        os.replace(tmp, path)
        tmp = ""
    except OSError:
        return                      # a cache that cannot be written is only a slower run
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass
    _tidy(folder, grown)


def _tidy(folder: str, grown: int = 0) -> None:
    """Keep the folder to CACHE_BYTES and CACHE_DAYS: see PRUNE_SECONDS for when it is
    looked at whole. `grown` is what a write just added."""
    with _PRUNE_LOCK:
        now = time.monotonic()
        known = _TIDY.get(folder)
        if known is not None:
            known[0] += grown
            if known[0] <= CACHE_BYTES and now - known[1] < PRUNE_SECONDS:
                return
        _TIDY[folder] = [prune(folder), now]


def _touch(key: Key, etag: str, modified: str, body: str, fetched: float) -> None:
    """An answer asked for again counts as recent, so pruning keeps what is in use; one
    known only in memory (the folder was named after it was read) is written down."""
    if not CACHE_DIR:
        return
    _tidy(os.path.join(CACHE_DIR, "http"))
    try:
        os.utime(_cache_file(key))
    except OSError:
        _disk_put(key, etag, modified, body, fetched)


def prune(folder: str, now: Optional[float] = None) -> int:
    """Answers older than CACHE_DAYS go, and when the folder holds more than CACHE_BYTES,
    the oldest until it holds PRUNE_TO of it; a write cut off more than an hour ago goes
    too. The bytes kept."""
    now = time.time() if now is None else now
    try:
        entries = list(os.scandir(folder))
    except OSError:
        return 0
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
    goal = CACHE_BYTES * PRUNE_TO if total > CACHE_BYTES else total
    for _, size, path in sorted(kept):
        if total <= goal:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass
    return total


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


def _all_arrived(fh, got: int) -> Optional[bool]:
    """Whether the answer's own framing shows every byte arrived: True for a chunked
    answer or one that got all of its Content-Length, False for one short of it, and None
    for one that says neither. With a size to read, http.client hands back a short read
    with no error when the connection drops (its own comment says it does not raise
    IncompleteRead, for compatibility), so the declared Content-Length is the only sign a
    body was cut short. A chunked answer that drops raises instead. An answer with neither
    ends when the connection closes, and one dropped halfway ends the same way."""
    left = getattr(fh, "length", None)          # what http.client still expected
    if isinstance(left, int) and left > 0:
        return False
    headers = fh.headers
    if "chunked" in (headers.get("Transfer-Encoding") or "").lower():
        return True
    declared = (headers.get("Content-Length") or "").strip()
    if declared.isascii() and declared.isdigit():
        return got == int(declared)
    return None


def _read(fh, limit: int) -> Tuple[str, bool]:
    """(the response body as text, unzipped when it came gzipped, at most `limit` bytes;
    whether that is provably all of it). Only a body shown to be whole is ever kept for
    next time: not one cut at the limit, not one short of its Content-Length, not a gzip
    stream that stops before its end, and not a plain body that gives no length and is
    not chunked, since nothing shows whether all of it came."""
    raw = fh.read(limit)
    arrived = _all_arrived(fh, len(raw))
    whole = len(raw) < limit and arrived is not False
    if (fh.headers.get("Content-Encoding") or "").lower() == "gzip":
        unzip = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            raw = unzip.decompress(raw, limit)
        except zlib.error as e:
            raise gzip.BadGzipFile(f"the gzipped body could not be unzipped ({e})") from e
        # A stream cut off by the network unzips to a prefix with no error at all; only
        # reaching the stream's end shows it was all there, with or without a length.
        whole = (whole and unzip.eof and not unzip.unconsumed_tail
                 and not unzip.unused_data.strip(b"\0") and len(raw) < limit)
        raw = raw[:limit]
    else:
        whole = whole and arrived is True
    return raw.decode("utf-8", "replace"), whole


def _body(fh, limit: int) -> str:
    """The response body as text, unzipped when it came gzipped, at most `limit` bytes."""
    return _read(fh, limit)[0]


def request(url: str, payload: Optional[dict] = None,
            accept: str = "application/json") -> Tuple[Optional[object], Optional[str]]:
    """(parsed JSON, None) or (None, why). A GET, or a JSON POST when `payload` is given.

    A kept answer that a 304 sends back and that is not JSON was damaged before it was
    kept. Asked again with its validators, the board would answer 304 for as long as it
    does not change, so the kept copy is dropped and the board asked once more without
    them. A kept copy counts as recently used only once it has parsed, and a new answer is
    kept only once it has: one that is not JSON (a maintenance page) was kept, sent back
    on the next 304, found not to be JSON and read again, two requests every run."""
    for attempt in range(2):
        raw, err, served, fresh = _get(url, payload, accept)
        if err:
            return None, err
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):        # nested deeper than Python can follow
            if served and not attempt:
                _forget(served[0])
                continue
            if fresh:
                _forget(fresh[0])   # nor is an older answer this one replaces worth asking about
            return None, "the response was not JSON"
        if served:
            _kept_again(*served)
        if fresh:
            _keep(*fresh)
        return data, None
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
    body, err, served, fresh = _get(url, payload, accept, limit)
    if served:
        _kept_again(*served)
    if fresh:
        _keep(*fresh)
    return body, err


def _kept_again(key: Key, cached: tuple) -> None:
    """A kept answer a 304 sent back and that was read: recent again, in memory and on disk,
    and still dated from when it was last read in full."""
    _remember(key, cached[0], cached[2], cached[1], cached[3])
    _touch(key, *cached)


def _keep(key: Key, etag: str, modified: str, body: str) -> None:
    """A new answer, kept to be asked about next time, in memory and on disk."""
    fetched = _now()
    _remember(key, etag, body, modified, fetched)
    _disk_put(key, etag, modified, body, fetched)


def _get(url: str, payload: Optional[dict] = None, accept: str = "*/*",
         limit: int = 100_000_000):
    """(body, why, served, fresh): request_raw's two, then ((url, accept), the kept
    answer) when a 304 sent the body back from what was kept, and ((url, accept), etag,
    last modified, body) for a new answer that can be kept. Each is None otherwise, and
    the caller decides whether the body is worth keeping."""
    # gzip: a large board's JSON is a third of the size on the wire.
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    for _hop in range(MAX_REDIRECTS + 1):
        body, err, onward, served, fresh = _one(url, data, headers, limit)
        if onward is None:
            return body, err, served, fresh
        nxt, code = onward
        old, new = urllib.parse.urlsplit(url), urllib.parse.urlsplit(nxt)
        if new.scheme not in ("http", "https") or not new.netloc:
            return "", f"HTTP {code} to an address that is not a web page", None, None
        if new.netloc.lower() != old.netloc.lower():
            why = robots_refuses(new.netloc, [new.path or "/"])
            if why:
                return "", f"redirected to {new.netloc}, and {why}", None, None
        if code == 303 or (code in (301, 302) and data is not None):
            data = None
            headers.pop("Content-Type", None)
        url = nxt
    return "", f"more than {MAX_REDIRECTS} redirects", None, None


def _fits(body: str, limit: int) -> bool:
    """Whether `body` is within `limit` bytes, as a fresh read would count it."""
    return len(body) * 4 <= limit or len(body.encode("utf-8")) <= limit


def _one(url: str, data, headers: dict, limit: int):
    """(body, None, None, served, fresh), ("", why, None, None, None), or ("", None,
    (next url, status), None, None) for a redirect. `served` is ((url, accept), the kept
    answer) when a 304 sent the body back from what was kept: the caller marks it used
    once it has read it. `fresh` is ((url, accept), etag, last modified, body) for a new
    GET answer that came whole and can be asked about again: the caller keeps it
    (`_keep`) once it is what the caller wanted."""
    headers = dict(headers)
    host = urllib.parse.urlsplit(url).netloc
    key = (url, headers.get("Accept", ""))
    cached, expired = None, False
    if data is None:                 # a POST is never answered from what was kept
        with _ETAG_LOCK:
            cached = _ETAGS.get(key)
        cached = cached or _disk_get(key)
        # A kept answer longer than this caller's `limit` is not what it would be given:
        # read afresh, the body is cut at the limit. So it is not asked about, and the copy
        # stays for the caller that can take it. (The limit is not part of the key: the
        # same page under two limits is one answer whenever it fits both.)
        if cached and not _fits(cached[2], limit):
            cached = None
        elif cached and not cached[0] and not 0 <= _now() - cached[3] < MODIFIED_MAX_AGE:
            cached, expired = None, True     # read in full; see MODIFIED_MAX_AGE
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
                return body, None, None, None, (key, keep[0], keep[1], body)
            if cached or expired:
                _forget(key)         # what was kept no longer describes this answer
            return body, None, None, None, None
        except urllib.error.HTTPError as e:
            if e.code == 304 and cached:
                return cached[2], None, None, (key, cached), None
            if e.code in REDIRECTS and e.headers and e.headers.get("Location"):
                return "", None, (urllib.parse.urljoin(url, e.headers["Location"]), e.code), None, None
            err = f"HTTP {e.code}"
            if e.code not in (502, 504):
                break
        # HTTPException covers a body cut off mid-read, which is not an OSError.
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            err = type(e).__name__
    return "", err, None, None, None


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
