from openroles.robots import allowed, is_robots_body

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
