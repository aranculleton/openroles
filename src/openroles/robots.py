"""A small RFC 9309 robots.txt reader: longest match wins, and a tie goes to Disallow."""
from __future__ import annotations

import re
from urllib.parse import unquote

_DIRECTIVES = ("user-agent", "allow", "disallow", "sitemap", "crawl-delay", "host")


def is_robots_body(text: str) -> bool:
    """Does this look like a robots.txt at all?

    A misconfigured host can answer /robots.txt with 200 and an HTML page. That
    parses to zero rules, which would read as "allowed", so a soft 200 would grant a
    permission nobody gave. An empty body is a valid allow-all and stays allowed.
    """
    if not text.strip():
        return True
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().lower()
        if ":" in line and line.split(":", 1)[0].strip() in _DIRECTIVES:
            return True
    return False


def _groups(text: str) -> dict:
    """user-agent -> [(is_allow, pattern)], tolerating blank lines inside a group."""
    out: dict = {}
    agents: list = []
    expect = True
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        field, _, value = line.partition(":")
        field, value = field.strip().lower(), value.strip()
        if field == "user-agent":
            if not expect:
                agents, expect = [], True
            agents.append(value.lower())
            out.setdefault(value.lower(), [])
        elif field in ("allow", "disallow") and agents:
            expect = False
            for a in agents:
                out[a].append((field == "allow", value))
    return out


def _match(pattern: str, path: str) -> int:
    """Length of the match under RFC 9309 wildcards, or -1. Patterns are percent-decoded."""
    if pattern == "":
        return -1
    pattern = unquote(pattern)
    rx = "^" + "".join(".*" if c == "*" else ("$" if c == "$" else re.escape(c))
                       for c in pattern)
    return len(pattern) if re.match(rx, path) else -1


def allowed(text: str, agent: str, path: str) -> bool:
    """May `agent` fetch `path` under this robots.txt?"""
    groups = _groups(text)
    rules = groups.get(agent.lower()) or groups.get("*") or []
    best_len, best_allow = -1, True
    for is_allow, pattern in rules:
        n = _match(pattern, path)
        if n > best_len or (n == best_len and n >= 0 and not is_allow):
            best_len, best_allow = n, is_allow
    return True if best_len < 0 else best_allow
