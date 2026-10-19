"""openroles on the command line.

    openroles <company, careers URL, board URL or ats:token> [filters]
    openroles detect <company or URL>
    openroles hosts <company, URL or ats:token>   # the hosts to allow in a network policy
    openroles mcp                      # serve the tools to an MCP client over stdio
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from typing import List, Optional

from . import BoardError, Job, __version__, detect, fetch, hosts
from .models import systems


def _table(jobs: List[Job]) -> str:
    if not jobs:
        return "no open roles matched"
    rows = [(j.posted or "-", j.title, j.location or "-", j.url) for j in jobs]
    w0 = max(len(r[0]) for r in rows)
    w1 = min(60, max(len(r[1]) for r in rows))
    w2 = min(40, max(len(r[2]) for r in rows))
    out = [f"{r[0]:<{w0}}  {r[1][:w1]:<{w1}}  {r[2][:w2]:<{w2}}  {r[3]}" for r in rows]
    return "\n".join(out) + f"\n\n{len(jobs)} open role(s)"


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "mcp":
        from .mcp import serve
        return serve()
    if argv and argv[0] == "detect":
        ap = argparse.ArgumentParser(prog="openroles detect",
                                     description="Find the job boards behind a company or URL.")
        ap.add_argument("target")
        a = ap.parse_args(argv[1:])
        boards = detect(a.target)
        for b in boards:
            print(b)
        if not boards:
            print(f"no {systems()} board found for {a.target!r}",
                  file=sys.stderr)
        return 0 if boards else 1

    if argv and argv[0] == "hosts":
        ap = argparse.ArgumentParser(prog="openroles hosts",
                                     description="The hosts reading a board calls, one a line, "
                                                 "for a network allowlist.")
        ap.add_argument("target", nargs="+")
        a = ap.parse_args(argv[1:])
        seen: List[str] = []
        try:
            for target in a.target:
                seen.extend(h for h in hosts(target) if h not in seen)
        except BoardError as e:
            print(f"openroles: {e}", file=sys.stderr)
            return 1
        print("\n".join(seen))
        return 0

    ap = argparse.ArgumentParser(
        prog="openroles",
        description="Every open role, straight from the employer's own ATS "
                    f"({systems('and')}).",
        epilog="Also: `openroles detect <target>`, `openroles hosts <target>` and `openroles mcp`.")
    ap.add_argument("target", help="a company name, a careers or board URL, or ats:token")
    ap.add_argument("-q", "--query", help="words that must all appear in the title")
    ap.add_argument("-l", "--location", help="text that must appear in a location")
    ap.add_argument("--remote", action="store_true", help="remote roles only")
    ap.add_argument("--since", type=int, metavar="DAYS", help="posted within DAYS days")
    ap.add_argument("-n", "--limit", type=int, help="at most N roles, newest first")
    ap.add_argument("--country", default="", help="Workday: narrow to one country by name")
    ap.add_argument("--details", action="store_true",
                    help="Workday, Rippling and Polymer: fetch every posting's description "
                         "(one request each)")
    ap.add_argument("--json", action="store_true", help="JSON array (the default when piped)")
    ap.add_argument("--jsonl", action="store_true", help="one JSON object per line")
    ap.add_argument("-v", "--verbose", action="store_true")
    ap.add_argument("--version", action="version", version=f"openroles {__version__}")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO if a.verbose else logging.WARNING,
                        format="%(name)s: %(message)s")
    try:
        jobs = fetch(a.target, query=a.query, location=a.location,
                     remote=True if a.remote else None, since_days=a.since, limit=a.limit,
                     details=True if a.details else None, country=a.country)
    except BoardError as e:
        print(f"openroles: {e}", file=sys.stderr)
        return 1
    if a.jsonl:
        for j in jobs:
            print(json.dumps(j.to_dict(), ensure_ascii=False))
    elif a.json or not sys.stdout.isatty():
        print(json.dumps([j.to_dict() for j in jobs], ensure_ascii=False, indent=2))
    else:
        print(_table(jobs))
    return 0


if __name__ == "__main__":
    sys.exit(main())
