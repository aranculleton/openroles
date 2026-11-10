"""A careers page on a system openroles cannot read says which, for every system the
README's "Not supported" table names."""
import logging
import pathlib
import re

import pytest

import openroles
from openroles.discover import UNSUPPORTED

README = (pathlib.Path(__file__).resolve().parent.parent / "README.md").read_text(encoding="utf-8")

PAGES = {
    "SuccessFactors": "https://career5.successfactors.eu/career?company=acme",
    "iCIMS": "https://careers-acme.icims.com/jobs",
    "Eightfold": "https://acme.eightfold.ai/careers",
    "Taleo": "https://acme.taleo.net/careersection/2/jobsearch.ftl",
    "Oracle Recruiting": "https://acme.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX",
    "SmartRecruiters": "https://jobs.smartrecruiters.com/Acme",
    "Dayforce": "https://jobs.dayforcehcm.com/en-US/acme/CANDIDATEPORTAL",
    "UKG": "https://recruiting2.ultipro.com/ACM1000/JobBoard/0000",
    "Paycom": "https://www.paycomonline.net/v4/ats/web.php/jobs?clientkey=X",
    "Pinpoint": "https://acme.pinpointhq.com/",
    "BambooHR": "https://acme.bamboohr.com/careers",
    "Breezy": "https://acme.breezy.hr/",
    "Cornerstone": "https://acme.csod.com/ux/ats/careersite/1/home",
    "BrassRing": "https://sjobs.brassring.com/TGnewUI/Search/Home/Home?partnerid=1",
    "Hireology": "https://careers.hireology.com/acme",
    "Comeet": "https://www.comeet.com/jobs/acme/00.000",
    "Phenom": "https://cdn.phenompeople.com/CareerConnectResources/x.js",
    "Freshteam": "https://acme.freshteam.com/jobs",
    "ADP": "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?cid=x",
    "Paylocity": "https://recruiting.paylocity.com/recruiting/jobs/All/x",
    "JOIN": "https://join.com/companies/acme",
    "TalentLyft": "https://acme.talentlyft.com/",
    "ApplicantPro": "https://acme.applicantpro.com/jobs/",
    "Jobvite": "https://jobs.jobvite.com/acme/jobs",
}


def _not_supported() -> list:
    table = README.split("### Not supported, and why", 1)[1].split("\n## ", 1)[0]
    names = []
    for row in re.findall(r"^\| ([^|]+?) \|", table, re.M)[1:]:      # past the header
        names += [n.strip() for n in row.split(",")]
    return names


def test_every_system_the_readme_does_not_support_is_recognised():
    named = [name for name, _rx, _why in UNSUPPORTED]
    assert sorted(_not_supported()) == sorted(named) == sorted(PAGES)


@pytest.mark.parametrize("name", sorted(PAGES))
def test_a_careers_page_on_it_says_which_system_and_why(web, caplog, name):
    web.routes["example.com/careers"] = (f'<a href="{PAGES[name]}">Open roles</a>', None)
    with caplog.at_level(logging.WARNING, logger="openroles"):
        assert openroles.detect("https://example.com/careers") == []
    why = next(w for n, _rx, w in UNSUPPORTED if n == name)
    assert f"uses {name}, which openroles cannot read: {why}" in caplog.text


def test_a_page_that_only_mentions_a_vendor_is_not_taken_for_its_board(web, caplog):
    web.routes["example.com/careers"] = ("<p>We moved off BambooHR (bamboohr.com) last year.</p>", None)
    with caplog.at_level(logging.WARNING, logger="openroles"):
        assert openroles.detect("https://example.com/careers") == []
    assert "BambooHR" not in caplog.text
