"""Every reader offers fetch, exists and hosts, as CONTRIBUTING.md says, so code that walks
openroles.providers.READERS can ask any of them the same things."""
import pytest

from openroles.providers import READERS, workday

from .conftest import fixture


@pytest.mark.parametrize("ats", sorted(READERS))
def test_every_reader_can_fetch_say_whether_a_board_exists_and_name_its_hosts(ats):
    for call in ("fetch", "exists", "hosts"):
        assert callable(getattr(READERS[ats], call, None)), f"{ats} has no {call}"


def test_a_workday_board_exists_where_its_listing_answers_and_robots_allows(web):
    web.routes["/wday/cxs/acme/External/jobs"] = fixture("workday_list.json")
    assert workday.exists("acme.wd3/External") is True
    assert workday.exists("acme.wd3/Elsewhere") is False                 # 404
    assert workday.exists("https://acme.wd3.myworkdayjobs.com/External") is False   # a URL, not a token
    web.robots["acme.wd3.myworkdayjobs.com"] = (200, "User-agent: *\nDisallow: /External/\n")
    assert workday.exists("acme.wd3/External") is False
    assert [u for u, _ in web.calls].count("https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/External/jobs") == 1
