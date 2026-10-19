# Contributing to openroles

Thanks for helping. openroles is small on purpose: one reader per system, one shape, no
dependencies. Contributions that keep it that way are very welcome.

## Set up

```bash
git clone https://github.com/aranculleton/openroles && cd openroles
python -m venv .venv && . .venv/bin/activate
pip install -e . pytest ruff
pytest && ruff check .
```

The tests never touch the network. Every answer comes from `tests/fixtures/`, through
the `web` fixture in `tests/conftest.py`.

## What makes a good change

- **Standard library only.** No runtime dependencies, ever. It is the reason people can
  drop this into anything.
- **Python 3.9 and up.** CI runs 3.9 to 3.13.
- **One shape.** Every reader returns `openroles.Job` with the same fields. A field only
  one ATS has goes into an existing field or not at all; open an issue first if you think
  the shape needs to change.
- **Polite, always.** robots.txt is read and obeyed, never worked around. Two requests per
  host at a time. A board that answers 429 or 503 is left alone. These are not up for
  trade-offs.
- **A test for every fix.** The smallest input that showed the bug, as an invented
  fixture. Never paste a real company's board or a real person's details into a fixture.

## Adding an ATS

The most useful contribution. A new reader is welcome when the system publishes an
employer's open roles at an endpoint that is either documented as public or allowed by
its robots.txt, and its terms do not forbid it. The README's "Not supported" table says
why each system there was left out; a check that changes one of those answers is as
welcome as a reader.

1. Add `src/openroles/providers/<ats>.py` with `fetch(token) -> list[Job]` and
   `exists(token) -> bool`. Quote the vendor's own words for the endpoint in its
   docstring. Check robots.txt first: `_http.robots_refuses` (an explicit Disallow stops
   it) where the endpoint is documented as public, `_http.robots_allows` (it must be
   readable and allow) everywhere else.
2. Register it in `providers/__init__.py`, `models.ATS` and `models.NAMES`, and
   `discover.py` (its board URL pattern, so `detect` finds it, and `GUESSED` if a board
   can be found from a company name).
3. Add an invented fixture and tests: the fields, an unknown board, robots.txt saying no.
4. Add a row to the README's "Supported systems" table and a line to `CHANGELOG.md`.

## Pull requests

Small and focused is easiest to review. CI must be green (ruff and the tests on every
supported Python). Say in the description what you changed and how you checked it
against a real board, without pasting that board's data.

## Releases

Maintainers bump `__version__` in `src/openroles/__init__.py` and both versions in
`server.json`, turn the CHANGELOG's `Unreleased` heading into `## X.Y.Z (date)`, merge,
and push the tag: `git tag vX.Y.Z && git push origin vX.Y.Z`. The publish workflow checks
the tag against all three, builds the package, publishes it to PyPI, creates the GitHub
release from the CHANGELOG entry and lists the server in the MCP Registry. A tag that
disagrees with the package publishes nothing.

## Conduct

Everyone taking part is expected to follow the [Code of Conduct](CODE_OF_CONDUCT.md).
