"""The one place openroles talks to the network.

Polite by construction: at most PER_HOST requests in flight to any one host, a timeout
on every call, an honest User-Agent, robots.txt read once per host a day, and a host's
Crawl-delay kept between requests once its robots.txt has been read.
"""
from __future__ import annotations

import gzip
import http.client
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zlib
from typing import Optional, Tuple

from . import __version__
from .robots import allowed, crawl_delay, is_robots_body

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


def _body(fh, limit: int) -> str:
    """The response body as text, unzipped when it came gzipped, at most `limit` bytes."""
    raw = fh.read(limit)
    if (fh.headers.get("Content-Encoding") or "").lower() == "gzip":
        try:
            raw = zlib.decompressobj(16 + zlib.MAX_WBITS).decompress(raw, limit)
        except zlib.error:
            raw = gzip.decompress(raw)[:limit]
    return raw.decode("utf-8", "replace")


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


def request_raw(url: str, payload: Optional[dict] = None,
                accept: str = "*/*", limit: int = 100_000_000) -> Tuple[str, Optional[str]]:
    """(body as text, None) or ("", why)."""
    # gzip: a large board's JSON is a third of the size on the wire.
    headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "gzip"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    host = urllib.parse.urlsplit(url).netloc
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
                with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
                    return _body(fh, limit), None
        except urllib.error.HTTPError as e:
            err = f"HTTP {e.code}"
            if e.code not in (502, 504):
                break
        # HTTPException covers a body cut off mid-read, which is not an OSError.
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            err = type(e).__name__
    return "", err


# ------------------------------------------------------------------ robots.txt

# Statuses that mean no policy is published. RFC 9309 section 2.3.1.3 reads an
# unavailable robots.txt as no restriction. A 403 is left out on purpose: on
# robots.txt it is usually a firewall refusing an unknown client. A 429, a 5xx or
# no answer means the policy could not be read, which the RFC treats as disallow.
NO_POLICY = {401, 404, 410}
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


def robots_allows(host: str, paths) -> Tuple[bool, str]:
    """(may these paths be read, why), from the host's robots.txt."""
    status, body = robots_txt(host)
    if status == 200:
        if not is_robots_body(body):
            return False, ("robots.txt answered 200 with something that is not a robots "
                           "file, so permission is unconfirmed")
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
    for path in paths:
        for agent in AGENTS:
            if not allowed(body, agent, path):
                return f"robots.txt on {host} disallows {path}"
    return ""
