"""The notes a GitHub release shows: one line per change, short enough to read at a glance.

    python scripts/release_notes.py 0.2.0          # the notes for one version

From that version's CHANGELOG entry: its one-line summary, then each `### Section` with the
bold headline of every item (the detail stays in the CHANGELOG), at most MAX a section and
the rest counted with a link, then how to upgrade. An entry written without headlines is
printed as it stands.
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
CHANGELOG = ROOT / "CHANGELOG.md"
# The package's own Changelog URL (pyproject.toml), so the link is written in one place.
_URL = re.search(r'^Changelog\s*=\s*"([^"]+)"', (ROOT / "pyproject.toml").read_text(encoding="utf-8"), re.M)
LINK = _URL.group(1) if _URL else "CHANGELOG.md"
MAX = 8
UPGRADE = "Upgrade: `pip install -U openroles`, or `uvx openroles@latest`."


def entry(version: str, text: str) -> str:
    """The body of `## <version> (<date>)`, up to the next `## ` heading, or ""."""
    m = re.search(r"^## " + re.escape(version) + r" \(.*?\)\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else ""


def notes(version: str, text: str) -> str:
    body = entry(version, text)
    if not body:
        return f"openroles {version}\n\n{UPGRADE}\n"
    parts = re.split(r"^### +(.+?)\s*$", body, flags=re.M)
    intro, sections = parts[0].strip(), list(zip(parts[1::2], parts[2::2]))
    if not sections or not re.search(r"^- \*\*", body, re.M):
        return f"{body}\n\n{UPGRADE}\n"
    out = [" ".join(intro.split())] if intro else []
    for name, block in sections:
        heads = [" ".join(h.split()) for h in re.findall(r"^- \*\*(.+?)\*\*", block, re.M | re.S)]
        if not heads:
            continue
        lines = [f"- {h}" for h in heads[:MAX]]
        if len(heads) > MAX:
            lines.append(f"- And {len(heads) - MAX} more ({LINK}).")
        out.append(f"**{name.strip()}**\n" + "\n".join(lines))
    out.append(f"Everything in detail: [CHANGELOG]({LINK}). {UPGRADE}")
    return "\n\n".join(out) + "\n"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__.strip().splitlines()[2].strip(), file=sys.stderr)
        return 2
    with open(CHANGELOG, encoding="utf-8") as fh:
        print(notes(argv[0], fh.read()), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
