"""The one place openroles talks to the network.

Polite by construction: at most PER_HOST requests in flight to any one host, a timeout
on every call, an honest User-Agent, and robots.txt read once per host per process.
"""
from __future__ import annotations

import http.client
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional, Tuple

from . import __version__
from .robots import allowed, is_robots_body

USER_AGENT = f"openroles/{__version__} (+https://github.com/aranculleton/openroles)"
TIMEOUT = 20
PER_HOST = 2
RETRY_PAUSE = 2.0

_SLOTS: dict = {}
_SLOTS_LOCK = threading.Lock()


def _slot(host: str) -> threading.BoundedSemaphore:
    with _SLOTS_LOCK:
        return _SLOTS.setdefault(host.lower(), threading.BoundedSemaphore(PER_HOST))


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
    headers = {"User-Agent": USER_AGENT, "Accept": accept}
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
                with urllib.request.urlopen(req, timeout=TIMEOUT) as fh:
                    return fh.read(limit).decode("utf-8", "replace"), None
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


def robots_txt(host: str) -> Tuple[int, str]:
    """(HTTP status, body) for https://<host>/robots.txt, fetched once per process.

    Status 0 means no answer at all.
    """
    key = host.lower()
    with _ROBOTS_LOCK:
        if key in _ROBOTS:
            return _ROBOTS[key]
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
        _ROBOTS[key] = got
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
