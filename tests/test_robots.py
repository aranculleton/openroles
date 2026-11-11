import random
import re
import time

import pytest

from openroles.robots import _canon, _match, allowed, is_robots_body

RULES = """User-agent: *
Disallow: /private/
Allow: /private/ok$

User-agent: openroles
Disallow: /no-bots/
"""


def test_longest_match_wins_and_ties_go_to_disallow():
    assert not allowed(RULES, "*", "/private/x")
    assert allowed(RULES, "*", "/private/ok")
    assert allowed("User-agent: *\nAllow: /a\nDisallow: /a\n", "*", "/b")
    assert not allowed("User-agent: *\nAllow: /a\nDisallow: /a\n", "*", "/a")


def test_a_named_agent_uses_its_own_group():
    assert not allowed(RULES, "openroles", "/no-bots/x")
    assert allowed(RULES, "openroles", "/private/x")


def test_an_html_page_is_not_a_robots_file():
    assert not is_robots_body("<html><body>Not found</body></html>")
    assert is_robots_body("")


def _regex_match(pattern, path):
    """_match as one regular expression, after both are put in the one form RFC 9309 compares
    them in, with "$" the end only as the pattern's last character. Slow on a pattern with
    many wildcards, and so used here only on short ones."""
    if pattern == "":
        return -1
    pattern, path = _canon(pattern), _canon(path)
    body, end = (pattern[:-1], r"\Z") if pattern.endswith("$") else (pattern, "")
    rx = "^" + "".join(".*" if c == "*" else re.escape(c) for c in body) + end
    return len(pattern) if re.match(rx, path, re.S) else -1


@pytest.mark.parametrize("pattern, path, length", [
    ("/", "/anything", 1),
    ("/a", "/b", -1),
    ("/a*b", "/axxb", 4),
    ("/a*b", "/axxbxx", 4),                 # a pattern matches the paths it begins
    ("/a*b$", "/axxbxx", -1),
    ("/a*b$", "/axxb", 5),
    ("/*", "/", 2),
    ("*", "", 1),
    ("/a$", "/a", 3),
    ("/a$", "/ab", -1),
    ("/a$b", "/a", -1),                     # a "$" before the end is itself
    ("/a$b", "/a$b", 4),
    ("/a$*", "/a", -1),
    ("/a$*", "/a$x", 4),
    ("/**a", "/xa", 4),
    ("/*a*a*a", "/baabab", 7),
    ("/*a*a*a", "/bab", -1),
    ("/*abc", "/ababab", -1),
    ("/*aab", "/aaab", 5),                  # the first "aa" is not the one that leads to "b"
    ("/a%2Ab", "/axxb", -1),                # an escaped "*" is a "*", not a wildcard
    ("/a%2Ab", "/a%2ab", 6),
    ("/a%24", "/a", -1),                    # an escaped "$" is a "$", not the end
    ("/a%24", "/a%24", 5),
    ("/%7Euser", "/~user", 6),              # "~" is unreserved: its escape is "~"
    ("/~user", "/%7euser", 6),
    ("", "/a", -1),
])
def test_wildcards_match_as_they_always_did(pattern, path, length):
    assert _match(pattern, path) == length
    assert _regex_match(pattern, path) == length


def test_the_new_match_gives_the_verdict_the_regular_expression_gave():
    """Random patterns of the kinds a robots.txt has, short enough for the regular
    expression, against random paths: every verdict the same."""
    rnd = random.Random(1)
    pieces = ["/", "a", "b", "ab", "a", "*", "*", "$", "?", "=", "%2A", "%24", "%2F", ".", "(", ")"]
    chars = "/ab?=*$.()%"
    for _ in range(30_000):
        pattern = "".join(rnd.choice(pieces) for _ in range(rnd.randint(0, 7)))
        path = "".join(rnd.choice(chars) for _ in range(rnd.randint(0, 12)))
        assert _match(pattern, path) == _regex_match(pattern, path), (pattern, path)


def test_the_same_rules_give_the_same_verdicts_on_a_robots_txt():
    rnd = random.Random(2)
    rules = ["Disallow: /a/*b", "Disallow: /*.pdf$", "Allow: /a/b$", "Disallow: /*?*q=", "Allow: /a/*/ok",
             "Disallow: /x", "Disallow: /", "Allow: /x/y", "Disallow: /*/*/*z"]
    for _ in range(300):
        text = "User-agent: *\n" + "\n".join(rnd.sample(rules, rnd.randint(1, 6)))
        for _ in range(20):
            path = "/" + "".join(rnd.choice("ab/xyz.pdf?q=") for _ in range(rnd.randint(0, 14)))
            old = best = -1
            allow = True
            for line in text.splitlines()[1:]:
                is_allow, _, pattern = line.partition(": ")
                n = _regex_match(pattern, path)
                if n > best or (n == best and n >= 0 and is_allow == "Disallow"):
                    best, allow = n, is_allow == "Allow"
            old = True if best < 0 else allow
            assert allowed(text, "*", path) is old, (text, path)


def _trade_me_names():
    rnd = random.Random(4)
    return [f"{rnd.choice(['saint', 'mount', 'port', 'new', 'old'])}-{rnd.choice('abcdefghij')}{i}" for i in range(2_500)]


def _trade_me_shaped():
    """A robots.txt of the shape of a large marketplace's, about 300 kB: thousands of rules that
    end in a name and have three wildcards before it, a few hundred plain ones, and fifty with a
    hundred and ten "*" each."""
    rnd = random.Random(3)
    names = _trade_me_names()
    lines = ["User-agent: *", "Allow: /", "Sitemap: https://shop.example/sitemap.xml"]
    for name in names:
        lines.append(f"Disallow: /a/property/residential/*/*/*/{name}$")
        lines.append(f"Disallow: /a/property/commercial/*/*/*/{name}$")
        lines.append(f"Disallow: /a/property/*/*/{name}$")
    for i in range(500):
        lines.append(f"Disallow: /a/jobs/{rnd.choice(['trades', 'it', 'sales', 'health'])}/other{i}$")
        lines.append(f"Disallow: /a/*refine{i}")
    for i in range(50):
        lines.append(f"Disallow: /a/{'*' * 110}k{i}.cc")
        lines.append(f"Disallow: /a/{'*/' * 55}x{i}$")
    return "\n".join(lines) + "\n"


def test_a_robots_txt_with_many_wildcards_is_matched_in_well_under_a_second():
    """As one regular expression each, patterns like these took minutes against a path that
    did not match them: a hundred "*" is a hundred places to try again. Now the work is at most
    the product of the pattern's length and the path's."""
    text = _trade_me_shaped()
    assert len(text) > 250_000 and text.count("*") > 20_000
    paths = ["/a/jobs/it/search?page=2", "/a/marketplace/computers/laptops/search?sort_order=price_asc&page=3",
             "/a/property/residential/sale/auckland/ponsonby/listing/1234567", "/a/property/" + "x/" * 60,
             "/a/" + "x" * 200, "/careers"]
    start = time.perf_counter()
    verdicts = [allowed(text, "openroles", path) for path in paths]
    assert time.perf_counter() - start < 1.0
    assert verdicts == [True] * len(paths)
    assert not allowed(text, "openroles", "/a/property/residential/sale/auckland/ponsonby/" + _trade_me_names()[0])
    assert not allowed(text, "openroles", "/a/" + "x" * 100 + "k5.cc")
    assert not allowed(text, "openroles", "/a/" + "x/" * 60 + "x7")
    assert allowed(text, "openroles", "/a/" + "x" * 100 + "k5.ccc") is False         # "k5.cc" is a prefix: no "$"
    assert allowed(text, "openroles", "/a/jobs/it/other3x")                          # "other3$" needs the end of the path


# RFC 9309, section 2.2.2: a rule's path and a path asked about are compared encoded alike.
@pytest.mark.parametrize("rule, path", [
    ("/search?q=café", "/search?q=caf%C3%A9"),          # the rule written in UTF-8
    ("/search?q=caf%C3%A9", "/search?q=caf%C3%A9"),     # the rule escaped as the address is
    ("/search?q=caf%c3%a9", "/search?q=café"),          # hex in either case, a path not escaped
    ("/foo/bar/ツ", "/foo/bar/%E3%83%84"),
    ("/foo/bar/%62%61%7A", "/foo/bar/baz"),             # an unreserved character escaped
    ("/foo%20bar", "/foo bar"),
])
def test_a_rule_matches_its_path_however_either_is_escaped(rule, path):
    text = f"User-agent: *\nDisallow: {rule}\n"
    assert not allowed(text, "openroles", path)
    assert not allowed(text, "openroles", path + "/more")


def test_an_escaped_reserved_character_is_not_the_character():
    text = "User-agent: *\nDisallow: /a%2Fb\n"
    assert allowed(text, "openroles", "/a/b")
    assert not allowed(text, "openroles", "/a%2fb")


def test_a_byte_order_mark_does_not_hide_the_first_group():
    text = "﻿User-agent: *\nDisallow: /\n"
    assert is_robots_body(text)
    assert not allowed(text, "openroles", "/jobs")
    from openroles.robots import content_signals, crawl_delay
    assert crawl_delay("﻿User-agent: *\nCrawl-delay: 4\n", "openroles") == 4.0
    assert content_signals("﻿User-agent: *\nContent-Signal: ai-input=no\n", "x") == {"ai-input": "no"}


def test_a_rule_that_is_not_utf8_leaves_permission_unconfirmed(monkeypatch):
    from openroles import _http
    from openroles.robots import has_undecodable_rule
    garbled = "User-agent: *\nDisallow: /caf�\n"
    assert has_undecodable_rule(garbled)
    assert not has_undecodable_rule("# caf�\nUser-agent: *\nSitemap: /caf�.xml\nDisallow: /x\n")
    # An Allow line that cannot be read only makes the file stricter: the host is not refused.
    assert not has_undecodable_rule("User-agent: *\nDisallow: /\nAllow: /caf�/\n")
    monkeypatch.setattr(_http, "robots_txt", lambda host: (200, garbled))
    ok, why = _http.robots_allows("acme.example", ["/jobs"])
    assert ok is False and "not UTF-8" in why
