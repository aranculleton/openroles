"""Greenhouse and Gem file a posting under the employer's offices as well as its own
location. An office is a tag, not a place the job is open at: a posting that names its own
place is where it says, and its offices count only where it names none."""
import pytest

import openroles
from openroles.models import names_a_place, own_place_first
from openroles.providers import gem, greenhouse

from .conftest import fixture


def _greenhouse(web, *postings):
    data = fixture("greenhouse.json")
    base = data["jobs"][0]
    data["jobs"] = [dict(base, id=100 + i, location={"name": own},
                         offices=[{"id": n, "name": o, "location": o} for n, o in enumerate(offices)])
                    for i, (own, offices) in enumerate(postings)]
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = data


def test_a_posting_that_names_its_place_is_not_where_its_office_tags_are(web):
    europe = ["Barcelona, Spain", "Berlin, Germany", "Paris, France"]
    _greenhouse(web, ("Berlin, Germany", europe), ("Paris, France", europe),
                ("San Francisco, CA • New York, NY • United States", ["Canada", "US"]))
    jobs = greenhouse.fetch("acme")
    assert [j.locations for j in jobs] == [["Berlin, Germany"], ["Paris, France"],
                                           ["San Francisco, CA • New York, NY • United States"]]
    assert [j.id for j in openroles.fetch("greenhouse:acme", location="Paris")] == ["gh-101"]
    assert openroles.fetch("greenhouse:acme", location="Canada") == []


@pytest.mark.parametrize("own", ["", "Hybrid", "Remote", "Fully remote", "On-site", "In office",
                                 "Flexible", "Anywhere", "Multiple Locations", "Eastern Time Zone",
                                 "UTC+1", "GMT-05:00"])
def test_a_posting_that_names_no_place_is_where_its_offices_are(web, own):
    _greenhouse(web, (own, ["Leeds, United Kingdom", "York, United Kingdom"]))
    [job] = greenhouse.fetch("acme")
    assert job.locations == [x for x in [own, "Leeds, United Kingdom", "York, United Kingdom"] if x]
    assert len(openroles.fetch("greenhouse:acme", location="York")) == 1


@pytest.mark.parametrize("label", ["London, UK", "Remote - US", "Remote, Canada", "Toronto",
                                   "Hybrid - Berlin", "US"])
def test_a_label_with_a_place_in_it_names_a_place(label):
    assert names_a_place(label)
    assert own_place_first(label, ["Somewhere else"]) == [label]


def test_gem_judges_its_offices_the_same_way(web):
    post = {"id": "p1", "title": "Analyst", "absolute_url": "https://jobs.gem.com/acme/p1",
            "offices": [{"name": "North", "location": "Leeds, United Kingdom"},
                        {"name": "Europe", "location": "Ireland Locations"}]}
    web.routes["api.gem.com/job_board/v0/acme/job_posts/"] = [
        dict(post, location={"name": "Dublin"}), dict(post, id="p2", location={"name": "Hybrid"})]
    named, hybrid = gem.fetch("acme")
    assert named.locations == ["Dublin"] and named.location == "Dublin"
    assert hybrid.locations == ["Hybrid", "Leeds, United Kingdom", "Ireland Locations"]
