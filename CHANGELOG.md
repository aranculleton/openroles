# Changelog

## Unreleased

### New

- **A board that has not changed since the last run sends nothing.** With
  `openroles.configure(cache_dir=...)` (CLI `--cache DIR`), each board's last answer is
  kept with the `ETag` or `Last-Modified` date it came with, and the next run asks with
  them; Greenhouse and Lever, among others, answer `304 Not Modified`. Every read still
  asks the board. Off by default. Only GET answers are kept, never one marked `no-store`
  or cut at the size limit, in owner-only files named for a hash of the address, at most
  500 MB and for 30 days unused.
- **`openroles.job_id(url)` gives a posting's id from its address alone.** The same `Job.id`
  a board read gives it, so a posting found on a job site whose link goes to the employer's
  board can be matched to the copy read from that board, with nothing fetched. Greenhouse
  (its boards, its application form and any page with `gh_jid`), Lever, Ashby, Rippling,
  Workable, Personio and Workday. An address that does not carry the system's own id gives
  "", never a guess.
- **The posted pay band as numbers: `salary_min`, `salary_max`, `salary_currency` and
  `salary_period`.** Filled only where the board publishes its pay as numbers (Lever,
  Ashby, Recruitee, Rippling, ClearCompany and careers sites' schema.org `baseSalary`),
  never read out of a description. `compensation` keeps the band as the board words it.
  Ashby's equity and bonus are not salary, and Ashby tiers in different currencies give
  no figures rather than a band that mixes them. A figure that could be misread, such as
  "48.000", is left out.

### Changed

- **A host that sends `Last-Modified` and no `ETag` is asked with `If-Modified-Since`.**
  Read twice in a process, it answers 304 and sends nothing, as one with an `ETag` did.

### Fixed

- **A body cut short by the network is never kept for a 304 to send back.** Only one that
  arrived whole (all of its `Content-Length`, a gzip stream to its end) is kept; a kept
  copy that a 304 sends back and that is not JSON is dropped and read afresh; and each
  cache file carries a format version, so files an earlier build wrote are ignored.
  0.2.0 had the same flaw in memory, for the life of a process.
- **The cache folder keeps to its 500 MB after every write, not only after every 500th,**
  and a run that gets only 304s still drops what has gone unused for 30 days.
- **A kept answer goes only to a request like the one it answered.** It is kept by
  address and `Accept`, and one longer than a caller's size limit is read afresh for that
  caller, as an uncached read would be, instead of being handed back whole on a 304.
- **`configure(cache_dir=...)` refuses anything but text or a path with a `ValueError`**,
  where a folder named as bytes was taken and then broke every read.
- **A JSON-LD script wrapped in a great many comment lines is read in linear time.** The
  framing lines were dropped one at a time from the front, so one page could hold a read
  for minutes.
- **`salary_period` keeps the count a board gives.** Ashby's "2 WEEK", "0.5 MONTH" and
  "6 MONTH", and a "semi-annual" anywhere, are no period a field can hold, so they give
  "" instead of "week", "month" or "year", and Ashby tiers paid over different intervals
  are no longer merged into one band.
- **`posted` and `deadline` are always a real `YYYY-MM-DD`, or empty.** Every reader cut
  the board's value to ten characters, so a date written another way ("1/9/2026") came out
  as text that `since_days` compared as older than any real date, and the role was dropped
  for a date nobody gave it. Now a value that is not a calendar date reads as no date, and
  a role with no date is kept, as it always was. Greenhouse falls back to `updated_at`
  when `first_published` cannot be read, as it did when it was missing.
- **A careers site's job page is read even when its JSON-LD is not strictly valid JSON.**
  A description pasted with its line breaks left a raw newline inside a JSON string, which
  a strict reader refused, so the page read as having no `JobPosting`. Also read now: a
  `type` written without quotes, a script wrapped in comment or CDATA lines, one
  entity-encoded as a whole, and a stray semicolon after it. The cases are the ones
  extruct's JSON-LD reader handles (BSD-3-Clause), written afresh.

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
