"""One reader per applicant tracking system, and one for any careers site that publishes
its jobs for search engines."""
from . import (
    ashby,
    careersite,
    clearcompany,
    gem,
    greenhouse,
    homerun,
    jazzhr,
    lever,
    manatal,
    personio,
    polymer,
    recruitee,
    rippling,
    teamtailor,
    workable,
    workday,
)

READERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday,
           "workable": workable, "teamtailor": teamtailor, "personio": personio,
           "recruitee": recruitee, "rippling": rippling, "jazzhr": jazzhr, "gem": gem,
           "polymer": polymer, "manatal": manatal, "homerun": homerun,
           "clearcompany": clearcompany, "careersite": careersite}

__all__ = ["READERS", "ashby", "careersite", "clearcompany", "gem", "greenhouse", "homerun",
           "jazzhr", "lever", "manatal", "personio", "polymer", "recruitee", "rippling",
           "teamtailor", "workable", "workday"]
