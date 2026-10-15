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
