# Changelog

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
