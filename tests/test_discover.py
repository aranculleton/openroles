import pytest

import openroles
from openroles import Board
from openroles.discover import parse, slugs


@pytest.mark.parametrize("text,board", [
    ("https://boards.greenhouse.io/acme", Board("greenhouse", "acme")),
    ("https://job-boards.greenhouse.io/acme/jobs/123", Board("greenhouse", "acme")),
    ("https://boards.greenhouse.io/embed/job_board?for=acme&b=x", Board("greenhouse", "acme")),
    ("https://jobs.lever.co/acme/abc-123", Board("lever", "acme")),
    ("https://jobs.eu.lever.co/acme", Board("lever", "acme")),
    ("https://jobs.ashbyhq.com/acme/9f1", Board("ashby", "acme")),
    ("https://acme.wd3.myworkdayjobs.com/en-US/External/job/Leeds/x_R1", Board("workday", "acme.wd3/External")),
    ("lever:acme", Board("lever", "acme")),
    ("workday:https://acme.wd5.myworkdayjobs.com/Careers", Board("workday", "acme.wd5/Careers")),
])
def test_parse(text, board):
    assert parse(text) == board


def test_not_a_board():
    assert parse("https://example.com/careers") is None
    assert parse("Acme") is None


def test_slugs():
    assert slugs("Acme Data Ltd") == ["acmedata", "acme-data", "acme"]
    assert slugs("Brindle & Hart") == ["brindleandhart", "brindle-and-hart", "brindle"]


def test_a_careers_page_is_read_for_the_board_it_embeds(web):
    web.routes["example.com/careers"] = ('<script src="https://boards.greenhouse.io/embed/job_board/js?for=acme"></script>', None)
    assert openroles.detect("https://example.com/careers") == [Board("greenhouse", "acme")]


def test_a_name_is_tried_on_each_ats(web):
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)
    assert openroles.detect("Acme") == [Board("lever", "acme")]


@pytest.mark.parametrize("page,board", [
    # No scheme, as embed snippets often write it.
    ('<script src="//boards.greenhouse.io/embed/job_board/js?for=acme"></script>', Board("greenhouse", "acme")),
    # Inside JSON or a script, slashes escaped.
    ('{"careers":"https:\\/\\/jobs.lever.co\\/acme"}', Board("lever", "acme")),
    # Lever's embedded list names its board in a script, not a link.
    ("<script>window.leverJobsOptions = {accountName: 'acme', includeCss: true};</script>",
     Board("lever", "acme")),
])
def test_a_careers_page_is_read_however_it_writes_the_board(web, page, board):
    web.routes["example.com/careers"] = (page, None)
    assert openroles.detect("https://example.com/careers") == [board]


def test_workdays_other_host_is_read_at_the_tenants_own_address():
    assert parse("https://wd3.myworkdaysite.com/recruiting/acme/External") == Board(
        "workday", "acme.wd3/External")
    assert parse("https://wd5.myworkdaysite.com/en-US/recruiting/acme/Careers/job/x") == Board(
        "workday", "acme.wd5/Careers")


def test_a_long_name_is_never_shortened_to_its_first_word():
    assert slugs("Bank of Brackenhollow") == ["bankofbrackenhollow", "bank-of-brackenhollow"]
    assert slugs("Kestrel Mutual") == ["kestrelmutual", "kestrel-mutual", "kestrel"]
    assert slugs("brackenhollow lantern savings trust") == [
        "brackenhollowlanternsavingstrust", "brackenhollow-lantern-savings-trust"]
    assert slugs("Acme.com") == ["acme"]


def test_a_bare_domain_with_no_board_on_its_home_page_is_tried_as_a_name(web):
    web.routes["acme.com"] = ("<html>no jobs here</html>", None)
    web.routes["api.lever.co/v0/postings/acme?"] = ([], None)
    assert openroles.detect("Acme.com") == [Board("lever", "acme")]


def test_a_careers_page_on_a_system_openroles_cannot_read_says_so(web, caplog):
    import logging
    web.routes["example.com/careers"] = ('<a href="https://acme.icims.com/jobs">Jobs</a>', None)
    with caplog.at_level(logging.WARNING, logger="openroles"):
        assert openroles.detect("https://example.com/careers") == []
    assert "iCIMS" in caplog.text
