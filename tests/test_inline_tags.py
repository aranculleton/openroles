"""A tag of an inline element leaves nothing between the words around it, as on a page.

"<b>warehouse</b>, and" is shown as "warehouse, and", and was read as "warehouse , and": every
tag, inline or not, left a space. The elements below are the ones that sit inside a line of
text; the end of a block ends the line, <br> breaks it, and any other tag still leaves a space."""
import pytest

from openroles.models import html_to_text
from openroles.providers import ashby

INLINE = ("a abbr b bdi bdo cite code data dfn em font i kbd mark q s samp small span strong sub sup "
          "time u var wbr").split()


def test_a_tag_around_a_word_leaves_the_punctuation_beside_it():
    assert html_to_text("<p>Model the <b>warehouse</b>, and more.</p>") == "Model the warehouse, and more."
    assert html_to_text("Python (<code>pandas</code>), SQL; <em>dbt</em>.") == "Python (pandas), SQL; dbt."
    assert html_to_text("10<sup>6</sup> rows, H<sub>2</sub>O") == "106 rows, H2O"
    assert html_to_text("Hel<span>lo</span> <a href='https://x.example'>there</a>!") == "Hello there!"


@pytest.mark.parametrize("name", INLINE)
def test_each_inline_element_joins_the_words_around_it(name):
    assert html_to_text(f"x<{name}>y</{name}>z") == "xyz"
    assert html_to_text(f"x<{name.upper()} class='k' data-n=1>y</{name.upper()}>z") == "xyz"
    assert html_to_text(f"x<{name}\n>y</{name} >z") == "xyz"


def test_the_empty_tag_form_of_an_inline_element_joins_too():
    assert html_to_text("one<wbr/>two<span />three") == "onetwothree"


def test_the_end_of_a_block_or_a_br_still_ends_the_line():
    assert html_to_text("one<br>two<br/>three") == "one\ntwo\nthree"
    assert html_to_text("<p>one</p><p>two</p>") == "one\ntwo"
    assert html_to_text("<ul><li>one</li><li>two</li></ul>") == "one\ntwo"
    assert html_to_text("<h2>One</h2>Two<div>Three</div>Four") == "One\nTwo Three\nFour"      # the end of a block


@pytest.mark.parametrize("tag", ["td", "th", "tr", "ul", "section", "label", "button", "img", "input", "o:p", "custom-tag",
                                 "abbrx", "span2", "b-x", "bold", "strongest", "iframe", "svg"])
def test_any_other_tag_still_leaves_a_space(tag):
    assert html_to_text(f"x<{tag}>y</{tag}>z") == "x y z"


def test_what_is_a_tag_has_not_changed():
    """A "<" and the first ">" after it, as before: an inline tag is only one that reads
    "<", an inline name, then a space, "/" or ">"."""
    assert html_to_text("<p>Plan</p><br><<a href=x>the week</a> <> 2 < 3") == "Plan\n\nthe week <> 2 < 3"
    assert html_to_text("a <b and c> d") == "a d"                  # "<b and c>" is a tag: b, then two attributes
    assert html_to_text("a<b") == "a<b" and html_to_text("a<b>") == "a"


def test_a_reader_gives_the_text_as_a_page_shows_it(web):
    job = {"id": "u-3", "title": "Analytics Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/u-3",
           "isListed": True, "location": "Leeds",
           "descriptionHtml": "<p>Model the <strong>data</strong> <em>warehouse</em>, then <a href='x'>ship</a> it.</p>"}
    web.routes["api.ashbyhq.com/posting-api/job-board/acme"] = {"jobs": [job]}
    assert ashby.fetch("acme")[0].description == "Model the data warehouse, then ship it."
