# Changelog

## Unreleased

### Changed

- **A description leaves out what no reader sees.** A comment, a `<script>` or `<style>`
  block, what a `<noscript>` or `<template>` holds, and an element that is hidden, with
  everything in it, are dropped before the HTML is flattened to text, so an instruction
  planted where a page does not show it no longer reaches `Job.description`. An element is
  hidden by the `hidden` attribute, `aria-hidden="true"`, or an inline `display:none` or
  `visibility:hidden`, in any case and spacing, with `!important`, or with a comment or an
  escape in the style. A word in another attribute (`class="hidden"`) hides nothing, a `>` in
  a quoted value does not end a tag, and the text after a hidden element stays. A hidden
  element ends where a browser ends it, with the end tags a page leaves out (`</p>`, `</li>`)
  and without the ones a browser ignores (`</span>` across an open `<div>`). Whatever a
  browser leaves open to the end of the text hides the rest of it: a comment, a script, a
  hidden element, a tag whose quote never closes, and a hidden `<b>` or `<a>` that it would
  open again. The text is read again after each round of decoding, so what a board encodes
  twice is dropped too, and a text with no sign of any of it reads exactly as before. Text
  hidden by a style sheet, a class, a colour, a size or a position is still there.
- **Lever and Ashby descriptions are built from the boards' HTML, so the same applies to them.**
  They read the board's plain-text field first (Lever's `descriptionPlain` and
  `additionalPlain`, Ashby's `descriptionPlain`), which is the HTML with its tags taken off
  and nothing else: a comment or a hidden element's text was in it. They now read the HTML
  (Lever's `description` and `additional`, Ashby's `descriptionHtml`), and the plain-text field
  only for a part the board sent no HTML for; an HTML field that shows no text gives no
  description. The text comes out as it does for the other systems, so an inline tag leaves a
  space (`<b>warehouse</b>, and` reads "warehouse , and").

### Fixed

- **A kept page that is not all UTF-8 is asked about again under a limit it fits.** Each
  byte that is not UTF-8 is read as one three-byte replacement character, so a page was
  measured by its text at up to three times the bytes it came in, and one near a caller's
  size limit was read afresh every time instead of being asked about. Each kept answer now
  keeps the number of bytes it was read from, in memory and on disk, and is measured by
  that. A copy kept by 0.3.0, without it, is measured by its text as before, which never
  says a page fits that does not.

## 0.3.0 (2026-10-21)

Pay as numbers, a cache that spares a board that has not changed, one id for a posting
found in two places, and careers sites read however they write their JSON-LD.

### New

- **A board that has not changed since the last run sends nothing.** With
  `openroles.configure(cache_dir=...)` (CLI `--cache DIR`), each board's last answer is
  kept with the `ETag` or `Last-Modified` date it came with, and the next run asks with
  them; a board that honours them and has not changed answers `304 Not Modified`. Every
  read still asks the board. Off by default, and `configure` refuses a folder that is not
  text or a path with a `ValueError`. An answer is kept only when it is a GET, is not
  marked `no-store`, and shows that all of it arrived (all of its `Content-Length`, every
  chunk of a chunked answer, or a gzip stream to its end); a JSON reader keeps it only
  once it has parsed, and a kept copy a 304 sends back that does not parse is dropped and
  read afresh. It is kept by address and `Accept`, and one longer than a caller's size
  limit is read afresh for that caller. Kept answers are owner-only files named for a hash
  of the request, each with a format version so a later release can ignore them, for 30
  days unused, and about 500 MB of them: each process keeps the folder to that, so two
  writing to one folder at once can take it past until one of them next looks at the whole
  folder (when it starts using it, hourly while it does, and when its own writes pass the
  cap).
- **`openroles.job_id(url)` gives a posting's id from its address alone.** The same
  `Job.id` a board read gives it, so a posting found on a job site whose link goes to the
  employer's board can be matched to the copy read from that board, with nothing fetched.
  Greenhouse (its boards, its application form and any page with `gh_jid`), Lever, Ashby,
  Rippling, Workable, Personio and Workday. An address that does not carry the system's
  own id, or carries two that disagree, gives "", never a guess. On those seven systems
  `job_id(job.url)` gives back `job.id` wherever the board gives the posting's address on
  its own system; an employer can point Greenhouse postings at a page of its own without
  `gh_jid`, and that address gives "". One Workday case is ambiguous: a listing that
  sends its path already percent-encoded ("M%C3%BCnchen") gives the same address as one
  that sends it plain ("München"), and `job_id` reads it as the plain one. Workday's
  `Job.id` stays exactly as 0.2.0 gave it.
- **The posted pay band as numbers: `salary_min`, `salary_max`, `salary_currency` and
  `salary_period`.** Filled only where the board publishes its pay as numbers (Lever,
  Ashby, Recruitee, Rippling, ClearCompany and careers sites' schema.org `baseSalary`),
  never read out of a description; `compensation` keeps the band as the board words it. A
  range written high to low comes out lowest first, the two figures swapped and never
  changed. A figure that could be misread ("48.000"), zero or below, or not a finite
  number is left out. The period is "hour", "day", "week", "month" or "year", and "" for
  one counted in anything but one of its unit (Ashby's "2 WEEK", "0.5 MONTH") or that no
  field can hold (bi-weekly, semi-annual, twice monthly). Ashby's equity and bonus are not
  salary, and Ashby tiers in different currencies or paid over different intervals give no
  figures rather than one band that mixes them. An odd value anywhere in a board's pay
  gives no figure, never an exception.
- **A careers site's job page is read however the page writes its JSON-LD.** 0.2.0 read
  each script as strict JSON, so a description pasted with its line breaks, which leaves a
  raw newline inside a JSON string, made the page read as having no `JobPosting`. Also
  read now: a `type` written without quotes, a script wrapped in comment or CDATA lines,
  one entity-encoded as a whole, a stray semicolon after it, and a script holding more
  than one value. However many framing lines a script has, it is read in linear time.
  Nothing is guessed beyond that: a JavaScript comment with words in it, a trailing comma,
  or a broken escape or quote is not mended.

### Changed

- **A host that sends `Last-Modified` and no `ETag` is asked with `If-Modified-Since`.**
  Read twice in a process, it answers 304 and sends nothing, as one with an `ETag` did. It
  is asked that way for at most 24 hours (`MODIFIED_MAX_AGE` in `openroles._http`) after
  its answer was last read in full, a 304 not counting, and then read in full once: a
  host whose date does not move when its data does holds a board back a day at most,
  in memory and in a `cache_dir` alike. An answer with an `ETag` is asked about however
  old it is.

### Fixed

- **A body cut short is no longer sent back on a 304.** 0.2.0 kept the last answer of any
  GET that came with an `ETag` in memory, whether the network or the size limit had cut it
  short or not, and sent it back on every 304 for the life of the process. Now only an
  answer that shows all of it arrived is kept, as above, so one that gives no length and
  is neither chunked nor gzipped is read in full every time.
- **`posted` and `deadline` are always a real `YYYY-MM-DD`, or empty.** Every reader cut
  the board's value to ten characters, so a date written another way ("1/9/2026") came out
  as text that `since_days` compared as older than any real date, and the role was dropped
  for a date nobody gave it. A placeholder written as a date did the same: a year before
  1990 (.NET's `0001-01-01`, `1900-01-01`, the Unix epoch, Lever's `createdAt` of 0) or
  more than two years ahead (`9999-12-31`). Each now reads as no date, and a role with no
  date is kept, as it always was. Greenhouse falls back to `updated_at` and ClearCompany
  to `openDate` when the first date cannot be read.
- **One posting's odd pay no longer loses every board in the call.** A pay figure too
  large for a float raised `OverflowError` (Recruitee, Rippling, ClearCompany and careers
  sites), and Rippling's list of pay ranges sent as a number or `true` raised `TypeError`.
  Neither is a `BoardError`, so `fetch()` lost every board it was reading.
- **One posting's odd field no longer stops a whole board being read.** A field in a
  shape its reader did not expect (a number where a list of locations or departments
  belongs, text where an object does, an object where a description does) raised
  `TypeError` or `AttributeError` out of `fetch()` on Greenhouse, Lever, Ashby, Recruitee,
  Workable, Rippling, Workday, Gem and ClearCompany, and lost every board in the call.
  Every reader now reads a field only in the shape it expects and gives the empty value
  otherwise, so no field holds text the board never wrote ("{'name': 'Leeds'}", "True"),
  and a posting whose id or title cannot be read is left out rather than given one such as
  "gh-None".
- **An answer nested too deep, or a Workday path no address can hold, no longer loses
  every board in the call.** JSON nested deeper than Python can follow (from a few hundred
  levels, depending on the Python version), from a board or in a careers page's script,
  raised `RecursionError`; a board's answer now reads as not JSON, and the script gives no
  posting while the page's others are still read. A Workday path holding a lone surrogate,
  which JSON can carry and which has no UTF-8, raised `UnicodeEncodeError`; its posting is
  left out. The MCP server stopped on a line nested that deep, and now answers it with a
  parse error.
- **A page built to stall the reader, or a long run, no longer slows to a crawl.** Finding
  a page's JSON-LD scripts looked to the end of the page again for every opening tag left
  unclosed (280 kB of them took 15 seconds, and a 5 MB page could take hours), and so did
  dropping a description's markup for every "<" with no ">" after it (180 kB took 15
  seconds). Both now take time in step with the page's length, under a second at 5 MB.
  Keeping answers in memory added up every kept answer again on each new one, so a long
  run's cost grew with the square of the answers it read; it now keeps a running total.

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
