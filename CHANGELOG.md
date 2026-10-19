# Changelog

## Unreleased

## 0.2.0 (2026-10-19)

Eleven more hiring systems, careers sites with no job API, and a library any application
can embed.

### New

- **Eleven more hiring systems: Workable, Teamtailor, Personio, Recruitee, Rippling, JazzHR,
  Gem, Polymer, Manatal, Homerun and ClearCompany.** In the same `Job` shape, each from the
  vendor's own documented endpoint where there is one. Workable was built from its
  documentation and has not yet been run against a live board.
- **Careers sites with no job API are read from the job pages they publish for search
  engines.** `careersite:<address>` reads each page's schema.org `JobPosting` (iCIMS and
  Eightfold sites, among others), where robots.txt allows it, at most 40 pages a call,
  newest first.
- **An application that embeds openroles names itself with `openroles.configure()`.** Its
  own User-Agent, and the robots.txt agents it answers to (never fewer than `*` and
  `openroles`). `openroles.robots_allows()` asks robots.txt the way openroles does.
- **`openroles hosts` lists the addresses a board needs, for a firewall or a sandbox.** No
  request is made for a board given as `ats:token`.
- **Every role says whether it is remote, hybrid or on-site.** `Job.workplace`, from the
  board's own field; `remote` stays, and is `None` for a hybrid role.

### Changed

- **`detect` tries every system a company name can find.** A careers page on iCIMS or
  Eightfold is pointed at `careersite:`, and one on a system openroles cannot read is named
  in a warning.
- **Politer: a site that asks not to be AI input is left alone, and redirects and crawl
  delays are respected.** `Content-Signal: ai-input=no` in robots.txt is honoured; a
  redirect is followed only where its new host allows it, at most five times; a host's
  `Crawl-delay` is kept; Greenhouse and Lever stop at an explicit Disallow; robots.txt is
  read again after 24 hours.
- **Fewer requests: a Workday posting's page is fetched only when its title matches.**
  None past `limit` either; responses come gzipped; a GET read twice in a process sends
  its `ETag`.
- **Releases publish themselves when a new version reaches main.** PyPI, the tag, this
  release page and the MCP Registry, with nobody pushing a tag.

### Fixed

- **Workday searches read past their second page.** Workday reports a search's total on
  its first page only, so every term stopped at 40 roles however many the board held.
- **Workday's `country` filter works on any board.** It is found under whatever facet the
  board files countries in, by any of the country's names; a board with no place filter is
  read whole, with a warning, instead of returning nothing.
- **A Workday posting listed in several locations is found by any of them.** A `location`
  filter on a place other than its primary reads its page to check.
- **A Greenhouse posting is found by every office it lists.**
- **One board failing no longer loses the others a company name found.**
- **`detect` finds a board however a careers page writes the link.** Without a scheme,
  inside JSON or a script, in Lever's embedded list, or at Workday's `myworkdaysite.com`;
  it tries a bare domain such as `acme.com` as a name, and never guesses a long or generic
  name's first word alone.
- **XML that declares a DTD or entities is never parsed.**

## 0.1.2 (2026-10-17)

- Workday: a posting's location is read from its path when the listing leaves
  `locationsText` out. On one large board, 154 of 154 postings came back with no
  location, so any filter by place dropped the whole board.

## 0.1.1 (2026-10-15)

- Listed in the official MCP Registry as `io.github.aranculleton/openroles`: `server.json`, the
  ownership line in the README, and a release step that publishes it after PyPI.
- Package metadata: supported Python versions, and a clearer one-line summary.

## 0.1.0 (2026-10-15)

First release.

- Greenhouse, Lever (global and EU), Ashby and Workday boards, in one `Job` shape.
- `detect`: a board from a company name, a board URL or a careers page.
- CLI (`openroles`), Python API (`openroles.fetch`, `openroles.detect`) and an MCP server
  (`openroles mcp`) with no dependencies.
- robots.txt honoured; two requests per host at a time; Workday stops on 429 or 503.
