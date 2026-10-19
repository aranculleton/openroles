# Changelog

## Unreleased

- Workday: a search reads on while its titles keep matching. Workday reports a search's
  total on its first page only, so every term stopped after its second page: 40 roles at
  most, however many the board held.
- Workday: `country` is found under whatever facet the board files countries in (some use
  a location hierarchy) and under any of its names ("United States of America" for
  "United States"). A board with no place filter at all is read whole, with a warning,
  instead of returning nothing.
- Workday: a posting listed as "3 Locations" reads as its primary location "and 2 more",
  and a `location` filter on another place reads its page to check. Past the 2,000 roles
  Workday pages, a warning says so.
- Fewer requests: a Workday posting's page is fetched only when its title passes `query`,
  and none past `limit`. Responses come gzipped.
- One board failing no longer loses the others a company name found.
- Greenhouse: every office a posting lists counts as one of its locations, so a posting
  located "Hybrid" with its city under its offices is found by a place filter.
- Politeness: a host's `Crawl-delay` is kept between requests (Lever asks for one second);
  Greenhouse and Lever stop at an explicit Disallow in their robots.txt; robots.txt is
  read again after 24 hours, which matters to a long-running `openroles mcp`.
- `detect` finds a board written without a scheme (`//boards.greenhouse.io/...`), inside
  JSON or a script with its slashes escaped, or named in Lever's embedded job list
  (`accountName`), and reads a Workday board linked at `wdN.myworkdaysite.com/recruiting/`
  at the tenant's own address.
- `detect` never guesses a long name's first word alone, nor a generic one ("Bank of
  Northfield" is not the board "bank"), and tries a bare domain such as "Acme.com" as a name
  when its home page links to no board. A careers page on a system openroles cannot read
  (SuccessFactors, iCIMS, Taleo, Oracle, SmartRecruiters) is named in a warning.

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
