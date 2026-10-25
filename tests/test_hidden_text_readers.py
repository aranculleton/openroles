"""The readers that had a plain-text field to use build a description from the HTML instead.

A board's plain-text field is its HTML with the tags taken off, so a comment or a hidden
element's text is in it. Every posting here is invented; `test_hidden_text.py` has the rest."""
from openroles.providers import ashby, gem, lever

from .conftest import fixture

SECRETS = ("SECRET-COMMENT", "SECRET-DISPLAY", "SECRET-ARIA", "SECRET-SCRIPT", "SECRET-HIDDEN")


def _with(secrets, intro="Intro text."):
    return (f"<p>{intro}</p><!-- {secrets[0]} --><div style='display:none'>{secrets[1]}</div>"
            f"<p>Then <span aria-hidden='true'>{secrets[2]}</span>this.</p>"
            f"<script>var x = '{secrets[3]}';</script><ul><li hidden>{secrets[4]}</li><li>Last point.</li></ul>")


def _plain(secrets, intro="Intro text."):
    """What a board makes of that: the same text with the tags taken off."""
    return f"{intro}\n{' '.join(secrets[:3])}\nThen this.\n{secrets[3]}\n{secrets[4]}\nLast point."


def test_lever_reads_the_html_so_that_what_no_reader_sees_is_left_out(web):
    posting = {
        "id": "bbb-2", "text": "Data Engineer", "hostedUrl": "https://jobs.lever.co/acme/bbb-2",
        "createdAt": 1760000000000, "categories": {"location": "Leeds"},
        "description": _with(SECRETS), "descriptionPlain": _plain(SECRETS),
        "lists": [{"text": "What you need", "content": "<li>Python</li><li style='display:none'>SECRET-LIST</li>"}],
        "additional": "<div>Equal opportunity employer.<!-- SECRET-ADDITIONAL --></div>",
        "additionalPlain": "Equal opportunity employer. SECRET-ADDITIONAL",
    }
    web.routes["api.lever.co/v0/postings/acme"] = [posting]
    text = lever.fetch("acme")[0].description
    assert text == "Intro text.\nThen this.\nLast point.\n\nWhat you need\nPython\n\nEqual opportunity employer."
    assert "SECRET" not in text


def test_lever_reads_the_plain_text_only_where_a_part_has_no_html(web):
    posting = fixture("lever.json")[0]
    assert "description" not in posting and "additional" not in posting
    web.routes["api.lever.co/v0/postings/acme"] = [posting]
    text = lever.fetch("acme")[0].description
    assert text == "We are Acme.\n\nWhat you need\nPython\nStatistics\n\nEqual opportunity employer."
    posting = dict(posting, description="   ", additional=7)
    web.routes["api.lever.co/v0/postings/acme"] = [posting]
    assert lever.fetch("acme")[0].description == text


def test_lever_does_not_fall_back_to_the_plain_text_when_the_html_shows_nothing(web):
    posting = {"id": "bbb-2", "text": "Data Engineer", "categories": {},
               "description": "<!-- SECRET-COMMENT --><div hidden>SECRET-HIDDEN</div>",
               "descriptionPlain": "SECRET-COMMENT SECRET-HIDDEN",
               "additional": "<script>SECRET-SCRIPT</script>", "additionalPlain": "SECRET-SCRIPT"}
    web.routes["api.lever.co/v0/postings/acme"] = [posting]
    assert lever.fetch("acme")[0].description is None


def test_ashby_reads_the_html_so_that_what_no_reader_sees_is_left_out(web):
    job = {"id": "u-3", "title": "Analytics Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/u-3",
           "isListed": True, "location": "Leeds", "descriptionHtml": _with(SECRETS),
           "descriptionPlain": _plain(SECRETS)}
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = {"jobs": [job]}
    assert ashby.fetch("acme")[0].description == "Intro text.\nThen this.\nLast point."


def test_ashby_reads_the_plain_text_only_where_there_is_no_html(web):
    job = dict(fixture("ashby.json")["jobs"][0])
    assert "descriptionHtml" not in job
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = {"jobs": [job]}
    assert ashby.fetch("acme")[0].description == "Model the warehouse."
    job["descriptionHtml"] = "  "
    assert ashby.fetch("acme")[0].description == "Model the warehouse."
    job["descriptionHtml"] = "<p>Model the data warehouse.</p><p>Then ship it.</p>"
    assert ashby.fetch("acme")[0].description == "Model the data warehouse.\nThen ship it."


def test_ashby_does_not_fall_back_to_the_plain_text_when_the_html_shows_nothing(web):
    job = {"id": "u-3", "title": "Analytics Engineer", "descriptionPlain": "SECRET-COMMENT",
           "descriptionHtml": "<!-- SECRET-COMMENT -->"}
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = {"jobs": [job]}
    assert ashby.fetch("acme")[0].description is None


def test_gem_reads_the_html_so_that_what_no_reader_sees_is_left_out(web):
    post = {"id": 7, "title": "Analyst", "absolute_url": "https://jobs.gem.com/acme/7",
            "content": _with(SECRETS), "content_plain": _plain(SECRETS)}
    web.routes["api.gem.com/job_board/v0/acme/job_posts/"] = [post]
    assert gem.fetch("acme")[0].description == "Intro text.\nThen this.\nLast point."
    del post["content"]
    assert gem.fetch("acme")[0].description == _plain(SECRETS)
