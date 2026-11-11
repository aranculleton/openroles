"""detect says how it found each board: named by the caller, linked from the careers page
given, or guessed from a name, which may be another organisation's board."""
import io
import json
from contextlib import redirect_stderr

import pytest

import openroles
from openroles import Board, cli, mcp
from openroles.discover import parse


def test_a_board_url_or_ats_token_is_named():
    assert parse("https://jobs.lever.co/acme").found == "named"
    assert parse("lever:acme").found == "named"
    assert openroles.detect("https://acme.wd3.myworkdayjobs.com/External")[0].found == "named"


@pytest.mark.parametrize("page", [
    '<a href="https://jobs.lever.co/acme">Jobs</a>',
    "<script>window.leverJobsOptions = {accountName: 'acme'};</script>",
])
def test_a_board_the_careers_page_links_to_is_linked(web, page):
    web.routes["example.com/careers"] = (page, None)
    [board] = openroles.detect("https://example.com/careers")
    assert board == Board("lever", "acme") and board.found == "linked"


def test_a_board_tried_by_name_is_guessed(web):
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)
    [board] = openroles.detect("Acme")
    assert board.found == "guessed"


def test_how_is_not_part_of_a_boards_identity():
    assert Board("lever", "acme", "guessed") == Board("lever", "acme") == Board("lever", "acme", "named")
    assert len({Board("lever", "acme", "guessed"), Board("lever", "acme")}) == 1
    assert repr(Board("lever", "acme", "linked")) == "Board(ats='lever', token='acme')"
    assert str(Board("lever", "acme", "linked")) == "lever:acme"
    with pytest.raises(ValueError):
        Board("lever", "acme", "rumoured")


def test_the_mcp_tool_says_how_each_board_was_found(web):
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)
    res = mcp.call_tool("find_job_board", {"target": "Acme"})
    assert res["structuredContent"]["result"] == [{"board": "lever:acme", "found": "guessed"}]
    assert json.loads(res["content"][0]["text"]) == res["structuredContent"]["result"]


def test_the_command_line_warns_of_a_guess_and_prints_the_board_as_before(web, capsys):
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)
    err = io.StringIO()
    with redirect_stderr(err):
        assert cli.main(["detect", "Acme"]) == 0
    assert capsys.readouterr().out == "lever:acme\n"
    assert "lever:acme was guessed from the name 'Acme'" in err.getvalue()
    assert cli.main(["detect", "lever:acme"]) == 0
    assert "guessed" not in capsys.readouterr().err
