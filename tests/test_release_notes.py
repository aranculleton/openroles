"""The release page shows one line per change, from the CHANGELOG's bold headlines."""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("release_notes", ROOT / "scripts" / "release_notes.py")
release_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_notes)

LOG = """# Changelog

## Unreleased

## 1.1.0 (2026-11-01)

Two new things.

### New

- **Acme boards are read.** A long detail that stays
  in the changelog.
- **Roles say where.** More detail.

### Fixed
""" + "".join(f"- **Fix number {n}.** Detail.\n" for n in range(10)) + """
## 1.0.0 (2026-10-01)

- First release, written without headlines.
"""


def test_headlines_only_and_the_rest_counted():
    notes = release_notes.notes("1.1.0", LOG)
    assert notes.startswith("Two new things.\n\n**New**\n- Acme boards are read.\n- Roles say where.")
    assert "long detail" not in notes
    assert "- Fix number 7." in notes and "Fix number 8" not in notes
    assert "- And 2 more (" in notes and "pip install -U openroles" in notes


def test_an_entry_without_headlines_is_shown_as_written():
    assert "First release, written without headlines." in release_notes.notes("1.0.0", LOG)


def test_this_repos_newest_entry_has_headlines():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    import openroles
    notes = release_notes.notes(openroles.__version__, text)
    assert "**New**" in notes or "**Fixed**" in notes or "**Changed**" in notes
    assert len(notes.splitlines()) < 40
