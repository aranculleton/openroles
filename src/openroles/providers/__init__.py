"""One reader per applicant tracking system."""
from . import ashby, greenhouse, lever, workday

READERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}

__all__ = ["READERS", "ashby", "greenhouse", "lever", "workday"]
