"""A small RFC 9309 robots.txt reader: longest match wins, and a tie goes to Disallow.

A rule's path and the path asked about are compared in one form (RFC 9309, section 2.2.2):
what a URL cannot carry as it is (anything outside ASCII, a space) percent-encoded as UTF-8,
an escape of an unreserved character ("%62" for "b") decoded, and every other escape kept
with its hex in capitals, so "/caf%c3%a9", "/café" and "/caf%C3%A9" are one path and "%2F"
stays apart from "/". A "$" ends a pattern only as its last character.
"""
from __future__ import annotations

import re
from functools import lru_cache

_DIRECTIVES = ("user-agent", "allow", "disallow", "sitemap", "crawl-delay", "host",
               "content-signal")
_BOM = "\ufeff"


def _unmarked(text: str) -> str:
    """The text without one leading byte-order mark. Left in, it is part of the first
    field's name, and a robots.txt saved with one hides its first "User-agent" line and
    with it every rule of that group, which then reads as allowing everything."""
    return text[1:] if text.startswith(_BOM) else text


def is_robots_body(text: str) -> bool:
    """Does this look like a robots.txt at all?

    A misconfigured host can answer /robots.txt with 200 and an HTML page. That
    parses to zero rules, which would read as "allowed", so a soft 200 would grant a
    permission nobody gave. An empty body is a valid allow-all and stays allowed.
    """
    text = _unmarked(text)
    if not text.strip():
        return True
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip().lower()
        if ":" in line and line.split(":", 1)[0].strip() in _DIRECTIVES:
            return True
    return False


def has_undecodable_rule(text: str) -> bool:
    """Whether a User-agent or Disallow line holds U+FFFD, which stands where a byte that is
    not UTF-8 was read. A robots.txt saved in another encoding with such a byte in a rule gives
    a pattern no path can match, and the rule read as if it were not there: the file would read
    as more open than it is. An Allow line that cannot be read only makes the file read
    stricter, so it never refuses the whole host."""
    for raw in _unmarked(text).splitlines():
        line = raw.split("#", 1)[0]
        if "\ufffd" in line and line.partition(":")[0].replace("\ufffd", "").strip().lower() in (
                "user-agent", "disallow"):
            return True
    return False


def _groups(text: str) -> dict:
    """user-agent -> [(is_allow, pattern)], tolerating blank lines inside a group."""
    text = _unmarked(text)
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
    text = _unmarked(text)
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
    text = _unmarked(text)
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


# RFC 3986: characters a URL carries as they are. An escape of an unreserved one means the
# character itself; a reserved one means something else written as it is, and stays escaped.
_UNRESERVED = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_RESERVED = frozenset(":/?#[]@!$&'()*+,;=")
# Text already in the one form: nothing but those, and no escape to read.
_PLAIN = re.compile(r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=]*")
_HEX = frozenset("0123456789abcdefABCDEF")


def _canon(text: str) -> str:
    """A rule's path or a path asked about in the one form they are compared in: see the
    module's docstring. Nothing is lost: a "%" that starts no escape is written "%25"."""
    if _PLAIN.fullmatch(text):
        return text
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == "%" and i + 2 < n and text[i + 1] in _HEX and text[i + 2] in _HEX:
            ch = chr(int(text[i + 1:i + 3], 16))
            out.append(ch if ch in _UNRESERVED else "%" + text[i + 1:i + 3].upper())
            i += 3
            continue
        if c in _UNRESERVED or c in _RESERVED:
            out.append(c)
        else:
            out.append("".join(f"%{b:02X}" for b in c.encode("utf-8", "surrogatepass")))
        i += 1
    return "".join(out)


def _match(pattern: str, path: str) -> int:
    """Length of the match under RFC 9309 wildcards, or -1. Both are read in the one form
    (`_canon`) first.

    A pattern matches the paths it begins: "*" stands for any run of characters (none too),
    a "$" at its very end for the end of the path, and every other character, a "$" anywhere
    else among them, for itself. The pattern is read from left to right against the path,
    going back only to the last "*", to let it take one more character. That is enough,
    since an earlier "*" can only do worse than the last one when the rest has to be found
    further on, and it keeps the work to the product of the two lengths, however many
    wildcards there are: as one regular expression, a pattern of a hundred "*" took minutes
    on a path that did not match it."""
    if pattern == "":
        return -1
    return _matched(_canon(pattern), _canon(path))


def _matched(pattern: str, path: str) -> int:
    """`_match` for a pattern and a path already in the one form."""
    if pattern == "":
        return -1
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    n, m = len(path), len(body)
    i = j = 0                           # how far the path and the pattern are read
    star, taken = -1, 0                 # the last "*", and how far the path was when it began
    while True:
        if j == m:
            if not anchored or i == n:
                return len(pattern)
        elif body[j] == "*":
            star, taken = j, i
            j += 1
            continue
        elif i < n and path[i] == body[j]:
            i += 1
            j += 1
            continue
        if star >= 0 and taken < n:     # let the "*" take one more character, and go on after it
            taken += 1
            i, j = taken, star + 1
        else:
            return -1


@lru_cache(maxsize=16)
def _rules(text: str) -> dict:
    """`_groups`, with every pattern in the one form, read once for each robots.txt: one
    question about several paths for several agents read the whole file each time."""
    return {agent: tuple((is_allow, _canon(pattern)) for is_allow, pattern in rules)
            for agent, rules in _groups(text).items()}


def allowed(text: str, agent: str, path: str) -> bool:
    """May `agent` fetch `path` under this robots.txt?"""
    groups = _rules(text)
    rules = groups.get(agent.lower()) or groups.get("*") or ()
    path = _canon(path)
    best_len, best_allow = -1, True
    for is_allow, pattern in rules:
        n = _matched(pattern, path)
        if n > best_len or (n == best_len and n >= 0 and not is_allow):
            best_len, best_allow = n, is_allow
    return True if best_len < 0 else best_allow
