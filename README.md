# openroles

**Every open role, straight from the employer's own careers system.** Greenhouse, Lever,
Ashby and Workday, in one shape, from the same public JSON their own careers pages read.
No API key, no account, no scraping service, and nothing but the Python standard library.

[![CI](https://github.com/aranculleton/openroles/actions/workflows/ci.yml/badge.svg)](https://github.com/aranculleton/openroles/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/openroles)](https://pypi.org/project/openroles/)
[![Python](https://img.shields.io/pypi/pyversions/openroles)](https://pypi.org/project/openroles/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

```console
$ pip install openroles
$ openroles figma --query data --limit 3
2026-09-23  Data Engineer Intern (2027)      San Francisco, CA • New York, NY          https://boards.greenhouse.io/figma/jobs/6178851004?gh_jid=6178851004
2026-09-21  Data Platform Engineer           San Francisco, CA • New York, NY • Unite  https://boards.greenhouse.io/figma/jobs/6201407004?gh_jid=6201407004
2026-09-21  PhD Intern, Data Science (2027)  San Francisco, CA • New York, NY          https://boards.greenhouse.io/figma/jobs/6200626004?gh_jid=6200626004

3 open role(s)
```

Give it a company name, a careers page, a board URL or `ats:token`. It finds the board,
reads every open role, and gives you the same fields whichever system the employer uses.

## Why

Job sites miss roles, show them late, and repost them stale. The employer's own board is
the source: it is complete, current, and carries the real apply link. Every major
applicant tracking system publishes that board as JSON for its own careers page.
`openroles` reads it the same way, politely, and puts the four biggest systems behind
one function.

## Install

```bash
pip install openroles          # or: uvx openroles <company>
```

Python 3.9 or newer. No dependencies.

## Command line

```bash
openroles linear                                   # every open role at Linear
openroles https://jobs.ashbyhq.com/linear          # the same, from the board URL
openroles lever:zoox --query "data" --since 14     # title words, posted in the last 14 days
openroles figma --location "New York"              # filter by place (--remote for remote only)
openroles https://adobe.wd5.myworkdayjobs.com/external_experienced \
          --query "data scientist" --details       # Workday, with each posting's description
openroles detect "Figma"                           # which ATS, and the board's token
openroles linear --json > roles.json               # JSON (the default when piped), or --jsonl
```

## Python

```python
import openroles

openroles.detect("Figma")
# [Board(ats='greenhouse', token='figma'), Board(ats='ashby', token='figma')]

jobs = openroles.fetch("greenhouse:figma", query="data", location="New York")
for job in jobs:
    print(job.posted, job.title, job.location, job.url)

job.to_dict()   # plain JSON-ready dict
```

`fetch()` raises `openroles.BoardError` when a board cannot be read (a wrong token, no
answer), and `openroles.RobotsDisallowed` when the host's robots.txt says no.

## For AI agents (MCP)

<!-- mcp-name: io.github.aranculleton/openroles -->

`openroles mcp` is a [Model Context Protocol](https://modelcontextprotocol.io) server over
stdio, so Claude, Cursor and other agents can look up any employer's open roles
themselves. Two tools: `find_job_board` and `list_open_roles` (descriptions left out
unless asked for, to keep answers short).

Claude Code:

```bash
claude mcp add openroles -- uvx openroles mcp
```

Claude Desktop, Cursor and other clients (`mcpServers` in their config):

```json
{
  "mcpServers": {
    "openroles": { "command": "uvx", "args": ["openroles", "mcp"] }
  }
}
```

There is also [`llms.txt`](llms.txt), a short brief for a model that has to use the
library or the CLI.

## What you get

Every role, from every system, has the same fields:

| Field | |
|---|---|
| `id` | stable across runs: `gh-`, `lv-`, `ab-` or `wd-` plus the ATS's own id |
| `ats`, `board` | where it came from, e.g. `greenhouse`, `figma` |
| `title`, `url` | the role and its apply page |
| `location`, `locations` | every location the posting lists, joined and as a list |
| `remote` | `True`, `False`, or `None` when the board does not say |
| `posted` | `YYYY-MM-DD`, first published (not last edited) where the ATS says |
| `department`, `employment_type` | where the board provides them |
| `compensation` | the posted pay band, where the employer publishes one |
| `deadline` | where the board provides one |
| `description` | plain text, HTML removed |

## Supported systems

| ATS | Requests | Notes |
|---|---|---|
| Greenhouse | 1 per board | descriptions included; every office a posting lists counts as one of its locations |
| Lever | 1 per board | descriptions with their requirement lists; EU boards found automatically |
| Ashby | 1 per board | descriptions and posted pay included |
| Workday | 1 per 20 roles, plus 1 per description | `--query` searches the board, reading on while titles keep matching; `--country` narrows it by whatever facet the board files countries under; `--details` fetches descriptions, only for roles whose title passes `--query` |

A Workday posting listed as "3 Locations" reads as its primary location "and 2 more"; with
`--location` on a place that is not its primary, its page is read to see whether the place
is one of the others. Workday pages a board only to its first 2,000 roles: past that, a
warning says to search with `--query`.

`detect` finds a board from a company name (Greenhouse, Lever and Ashby, by trying the
names an employer is likely to use), from any board URL, and from a careers page that
links to or embeds one, however the page writes it. A Workday board cannot be guessed
from a name: give its URL (either `tenant.wdN.myworkdayjobs.com` or
`wdN.myworkdaysite.com/recruiting/tenant`). When a careers page uses a system openroles
cannot read, a warning names it.

Not supported, because none publishes an open board this way: SuccessFactors, Oracle,
iCIMS and custom careers sites. SmartRecruiters publishes one, but its robots.txt closes it
to every crawler except LinkedIn's, so `openroles` does not read it.

## Polite by design

- **robots.txt is read first** for Ashby, Workday and any careers page, and a refusal is
  honoured, never worked around. For Workday the careers site's own rules count too.
  Greenhouse and Lever document their endpoints as public APIs, so there an explicit
  Disallow stops a read and a robots.txt that cannot be read does not.
- **A host's `Crawl-delay` is kept** between requests once its robots.txt is read (Lever
  asks for one second), and a robots.txt is read again after a day, as RFC 9309 asks.
- **At most two requests in flight per host**, a timeout on every call, gzip on the wire,
  and an honest `User-Agent` naming this project.
- **A Workday board that answers 429 or 503 is left alone** for the rest of the run.

## Is this allowed?

Greenhouse, Lever and Ashby document these endpoints as public job board APIs, for
exactly this purpose: showing an employer's open roles somewhere else. Workday's is the
endpoint its own careers pages call; it is not documented, it can change without notice,
and `openroles` only reads it where robots.txt allows. Use it the way the boards are
meant to be used: to find roles and apply to them, at a human pace. It is not a tool for
hammering a site or republishing someone's board wholesale.

## Where it came from

`openroles` is the employer-board reader from
[last-job-search](https://github.com/aranculleton/last-job-search), a job search that Claude
runs end to end, extracted so anyone can use it.

## Contributing

Contributions are welcome, and the most useful one is a reader for another ATS
(Workable, Recruitee, Personio, Teamtailor and more are wanted). [CONTRIBUTING.md](CONTRIBUTING.md)
has the set-up, the few rules that keep the library small and polite, and a checklist
for adding a system. Bugs and requests go in [Issues](https://github.com/aranculleton/openroles/issues).

```bash
pip install -e . pytest ruff
pytest && ruff check .        # offline: every answer comes from tests/fixtures/
```

## Licence

MIT. See [LICENSE](LICENSE).
