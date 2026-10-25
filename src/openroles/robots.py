"""A small RFC 9309 robots.txt reader: longest match wins, and a tie goes to Disallow."""
from __future__ import annotations

from urllib.parse import unquote

_DIRECTIVES = ("user-agent", "allow", "disallow", "sitemap", "crawl-delay", "host",
               "content-signal")


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


def _group_values(text: str, field_name: str) -> dict:
    """agent -> [values] of one directive, read within user-agent groups."""
    found: dict = {}
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
        elif agents:
            expect = False
            if field == field_name:
                for a in agents:
                    found.setdefault(a, []).append(value)
    return found


def content_signals(text: str, agent: str) -> dict:
    """The Content-Signal preferences a robots.txt states for `agent` (its own group, else
    "*"): {"search": "yes", "ai-train": "no", "ai-input": "no"}, or {} for none.

    Content signals (contentsignals.org) say what a site's content may be used for once
    fetched. "ai-input=no" asks that it not be fed to an AI model as input, which is what
    a job search that has an AI read the postings would do with it."""
    found = _group_values(text, "content-signal")
    values = found.get(agent.lower()) or found.get("*") or []
    out: dict = {}
    for value in values:
        for pair in value.split(","):
            k, _, v = pair.partition("=")
            if k.strip() and v.strip():
                out[k.strip().lower()] = v.strip().lower()
    return out


def crawl_delay(text: str, agent: str) -> float:
    """Seconds between requests the robots.txt asks of `agent` (its own group, else "*"),
    or 0 for none. Crawl-delay is not in RFC 9309, but a host that writes one means it."""
    delays: dict = {}
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
        elif agents:
            expect = False
            if field == "crawl-delay":
                try:
                    seconds = float(value)
                except ValueError:
                    continue
                for a in agents:
                    delays[a] = max(0.0, seconds)
    own = delays.get(agent.lower())
    return own if own is not None else delays.get("*", 0.0)


def _match(pattern: str, path: str) -> int:
    """Length of the match under RFC 9309 wildcards, or -1. Patterns are percent-decoded.

    A pattern matches the paths it begins: "*" stands for any run of characters (none too),
    "$" for the end of the path, and every other character for itself. The pattern is read
    from left to right against the path, going back only to the last "*", to let it take one
    more character. That is enough, since an earlier "*" can only do worse than the last one
    when the rest has to be found further on, and it keeps the work to the product of the two
    lengths, however many wildcards there are: as one regular expression, a pattern of a
    hundred "*" took minutes on a path that did not match it."""
    if pattern == "":
        return -1
    pattern = unquote(pattern)
    n, m = len(path), len(pattern)
    i = j = 0                           # how far the path and the pattern are read
    star, taken = -1, 0                 # the last "*", and how far the path was when it began
    while j < m:
        c = pattern[j]
        if c == "*":
            star, taken = j, i
            j += 1
        elif c == "$" and i == n:
            j += 1
        elif c != "$" and i < n and path[i] == c:
            i += 1
            j += 1
        elif star >= 0 and taken < n:   # let the "*" take one more character, and go on after it
            taken += 1
            i, j = taken, star + 1
        else:
            return -1
    return m


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
