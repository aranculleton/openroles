# openroles

**Every open role, straight from the employer's own careers system.** Fifteen applicant
tracking systems (Greenhouse, Lever, Ashby, Workday, Workable, Teamtailor, Personio,
Recruitee, Rippling, JazzHR, Gem, Polymer, Manatal, Homerun and ClearCompany), plus any
careers site that publishes its jobs for search engines, in one shape. Read from the
feeds and APIs the employers' own careers pages use: no API key, no account, no scraping
service, and nothing but the Python standard library.

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
the source: it is complete, current, and carries the real apply link. Most applicant
tracking systems publish that board as JSON, RSS or XML for the employer's own careers
page. `openroles` reads it the same way, politely, and puts every system that allows it
behind one function.

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
openroles hosts greenhouse:figma lever:zoox         # the hosts to allow in a network policy
openroles personio:acme                            # any system, as ats:token
openroles careersite:careers.acme.example          # a careers site with no job API
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

openroles.hosts("personio:acme")
# ['acme.jobs.personio.de', 'acme.jobs.personio.com']: what a firewall must allow
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
| `id` | stable across runs: a prefix for the system (`gh-`, `lv-`, `ab-`, `wd-`, ...) plus its own id |
| `ats`, `board` | where it came from, e.g. `greenhouse`, `figma` |
| `title`, `url` | the role and its apply page |
| `location`, `locations` | every location the posting lists, joined and as a list |
| `workplace` | `remote`, `hybrid`, `onsite`, or `""` when the board does not say |
| `remote` | `True`, `False`, or `None` when the board does not say (hybrid is `None`) |
| `posted` | `YYYY-MM-DD`, first published (not last edited) where the system says; see below |
| `department`, `employment_type` | where the board provides them |
| `compensation` | the posted pay band, where the employer publishes one |
| `deadline` | where the board provides one |
| `description` | plain text, HTML removed |

## Supported systems

| System | Requests | Notes |
|---|---|---|
| Greenhouse | 1 per board | descriptions; every office a posting lists counts as one of its locations |
| Lever | 1 per board | descriptions with their requirement lists; EU boards found automatically |
| Ashby | 1 per board | descriptions and posted pay. Ashby publishes no first-posted date, so `posted` is when the posting was last published |
| Workday | 1 per 20 roles, plus 1 per description | `--query` searches the board, reading on while titles keep matching; `--country` narrows it by whatever facet the board files countries under; `--details` fetches descriptions, only for roles whose title passes `--query` |
| Workable | 1 per board | descriptions; no pay. Built from Workable's documentation and not yet run against a live board (its hosts were rate-limiting when it was written) |
| Teamtailor | 1 per 100 roles | descriptions; hybrid and remote; a careers site on the employer's own domain works too |
| Personio | 1 per board | descriptions in English where the employer wrote them; `.de` and `.com` accounts |
| Recruitee | 1 per board | descriptions, pay and closing dates. From 10 February 2027 Recruitee asks for each employer's own token, after which a board reads as needing it |
| Rippling | 1 per board, plus 1 per description | descriptions and dates come from each posting's own record, fetched only with `--details` or a `--query`, at most 80 a board (Rippling allows 100 requests in 10 minutes) |
| JazzHR | 1 per board | descriptions; no date or pay. The feed is regenerated once a day |
| Gem | 1 per board | descriptions; hybrid and remote |
| Polymer | 1 per 20 roles, plus 1 per description | pay; descriptions as for Rippling, at most 60 a board |
| Manatal | 1 per 100 roles | descriptions; no date |
| Homerun | 1 per board | descriptions and pay, from the feed every Homerun careers page links to |
| ClearCompany | 1 per board | descriptions and pay; the token is the site id the careers page prints. Only its first page is read, with a warning when there is more |
| Any careers site (`careersite`) | 1 per sitemap, plus 1 per job page | reads the schema.org `JobPosting` each job page carries for search engines (iCIMS and Eightfold sites, among others), at most 40 pages a call, newest first |

A Workday posting listed as "3 Locations" reads as its primary location "and 2 more"; with
`--location` on a place that is not its primary, its page is read to see whether the place
is one of the others. Workday pages a board only to its first 2,000 roles: past that, a
warning says to search with `--query`.

`detect` finds a board from a company name (every system but Workday and ClearCompany,
by trying the names an employer is likely to use), from any board URL, and from a careers
page that links to or embeds one, however the page writes it. A Workday board cannot be
guessed from a name: give its URL (either `tenant.wdN.myworkdayjobs.com` or
`wdN.myworkdaysite.com/recruiting/tenant`). A careers site is never guessed: name it as
`careersite:<address>`. When a careers page uses a system openroles cannot read, a
warning names it.

### Not supported, and why

Each was checked before it was left out. A system moves onto the list above when it
publishes an open board its own terms and robots.txt allow.

| System | Why not |
|---|---|
| SmartRecruiters | its robots.txt closes its public API to every crawler except LinkedIn's |
| SuccessFactors, Dayforce, UKG, Paycom, Pinpoint | robots.txt disallows the job pages, or the board needs a sign-in |
| BambooHR, Breezy | their terms forbid automated reading of the careers pages |
| Cornerstone, BrassRing, Hireology, Comeet | the board is read through a session token issued to the browser |
| Phenom | the sites checked ask, through robots.txt's Content-Signal, that their content not be used as AI input |
| Oracle Recruiting | its job API is marked for internal use, and the job pages build their `JobPosting` in the browser |
| Freshteam | being shut down by its vendor |
| iCIMS, Eightfold | no open job API, but their careers sites usually publish `JobPosting` pages: read them as `careersite:` |
| Taleo, ADP, Paylocity, JOIN, TalentLyft, ApplicantPro | not yet checked well enough to build a reader on |

## Polite by design

- **robots.txt is read first**, and a refusal is honoured, never worked around. Where the
  vendor documents its endpoint as a public API (Greenhouse, Lever, Workable, Teamtailor,
  Personio, Recruitee, Rippling, JazzHR, Gem, Polymer, Manatal), an explicit Disallow stops
  a read and a robots.txt that cannot be read does not. Everywhere else (Ashby, Workday,
  Homerun, ClearCompany, any careers site) robots.txt must be readable and must allow
  the read. For Workday the careers site's own rules count too.
- **A site that asks not to be AI input is not read.** robots.txt's `Content-Signal:
  ai-input=no` is honoured, because openroles is often run by an AI agent.
- **A redirect is followed only where its new host's robots.txt allows it**, and never
  more than five times.
- **A host's `Crawl-delay` is kept** between requests once its robots.txt is read (Lever
  asks for one second), and a robots.txt is read again after a day, as RFC 9309 asks.
- **At most two requests in flight per host**, a timeout on every call, gzip on the wire,
  conditional requests (`ETag`) for anything read twice in a run, and an honest
  `User-Agent` naming this project.
- **XML that declares a DTD or entities is never parsed**, so a hostile feed cannot expand.
- **A board that answers 429 or 503 is left alone** for the rest of the run, and a
  documented rate limit (Rippling's 100 requests in 10 minutes) is kept below.

## Is this allowed?

Most of these systems document their endpoints as public, for exactly this purpose:
showing an employer's open roles somewhere else. Each reader's source file quotes the
vendor's own words and says where they are. Workday's, Ashby's, Homerun's and
ClearCompany's are the endpoints their own careers pages call; they are not documented,
they can change without notice, and `openroles` reads them only where robots.txt allows.
A careers site is read only from the job pages it publishes for search engines, at the
pace its robots.txt asks. Use it the way the boards are
meant to be used: to find roles and apply to them, at a human pace. It is not a tool for
hammering a site or republishing someone's board wholesale.

## Where it came from

`openroles` is the employer-board reader from
[last-job-search](https://github.com/aranculleton/last-job-search), a job search that Claude
runs end to end, extracted so anyone can use it.

## Contributing

Contributions are welcome, and the most useful one is a reader for another system,
or a check that moves one off the "Not supported" list. [CONTRIBUTING.md](CONTRIBUTING.md)
has the set-up, the few rules that keep the library small and polite, and a checklist
for adding a system. Bugs and requests go in [Issues](https://github.com/aranculleton/openroles/issues).

```bash
pip install -e . pytest ruff
pytest && ruff check .        # offline: every answer comes from tests/fixtures/
```

## Licence

MIT. See [LICENSE](LICENSE).
