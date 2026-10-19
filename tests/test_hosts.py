"""Every reader says which hosts it calls, so a network allowlist can be written without
reading a board."""
import pytest

import openroles
from openroles.cli import main
from openroles.providers import READERS

SITE = "0b9c1f7e-1111-4c2b-9f00-000000000001"
EXPECTED = {
    "greenhouse:acme": ["boards-api.greenhouse.io"],
    "lever:acme": ["api.lever.co", "api.eu.lever.co"],
    "ashby:acme": ["api.ashbyhq.com"],
    "workday:acme.wd3/External": ["acme.wd3.myworkdayjobs.com"],
    "workable:acme": ["www.workable.com", "apply.workable.com"],
    "teamtailor:acme": ["acme.teamtailor.com"],
    "teamtailor:careers.acme.example": ["careers.acme.example"],
    "personio:acme": ["acme.jobs.personio.de", "acme.jobs.personio.com"],
    "recruitee:acme": ["acme.recruitee.com"],
    "rippling:acme": ["api.rippling.com"],
    "jazzhr:acme": ["app.jazz.co"],
    "gem:acme": ["api.gem.com"],
    "polymer:acme": ["api.polymer.co"],
    "manatal:acme": ["api.manatal.com"],
    "homerun:acme": ["feed.homerun.co"],
    f"clearcompany:{SITE}": ["careers-api.clearcompany.com"],
    "careersite:careers.acme.example/us/en": ["careers.acme.example"],
}


def test_every_reader_names_its_hosts():
    assert {t.split(":", 1)[0] for t in EXPECTED} == set(READERS)


@pytest.mark.parametrize("target,want", sorted(EXPECTED.items()))
def test_hosts_without_a_request(web, target, want):
    assert openroles.hosts(target) == want
    assert web.calls == []


def test_the_cli_prints_them_one_a_line(capsys):
    assert main(["hosts", "greenhouse:acme", "lever:acme", "greenhouse:other"]) == 0
    assert capsys.readouterr().out.split() == ["boards-api.greenhouse.io", "api.lever.co", "api.eu.lever.co"]


def test_an_application_names_itself_and_its_agents(web):
    from openroles import _http
    saved = (_http.USER_AGENT, _http.AGENTS, _http.RESPECT_AI_INPUT)
    try:
        openroles.configure(user_agent="acme-search/2.0 (+https://acme.example)",
                            robots_agents=["acme-search", "*"])
        assert _http.USER_AGENT.startswith("acme-search/2.0")
        assert _http.AGENTS == ("*", "openroles", "acme-search")      # never fewer than the defaults
        openroles.configure(user_agent="x/1")                          # agents are kept
        assert _http.AGENTS == ("*", "openroles", "acme-search")
        web.robots["boards.acme.example"] = (200, "User-agent: acme-search\nDisallow: /jobs\n")
        ok, why = openroles.robots_allows("boards.acme.example", ["/jobs"])
        assert not ok and "disallows /jobs" in why
        with pytest.raises(ValueError):
            openroles.configure(user_agent=" ")
    finally:
        _http.USER_AGENT, _http.AGENTS, _http.RESPECT_AI_INPUT = saved
