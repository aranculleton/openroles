"""What a release publishes has to agree with itself, or the MCP Registry refuses it."""
import json
import pathlib
import re

import openroles

ROOT = pathlib.Path(__file__).resolve().parent.parent
SERVER = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))


def test_one_version_everywhere():
    assert SERVER["version"] == openroles.__version__
    assert [p["version"] for p in SERVER["packages"]] == [openroles.__version__]


def test_the_readme_proves_ownership_of_the_registry_name():
    # The registry reads the README on PyPI for this exact line.
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    names = re.findall(r"mcp-name: (\S+) -->", readme)
    assert names == [SERVER["name"]]
    assert SERVER["name"].startswith("io.github.aranculleton/")


def test_the_registry_entry_runs_the_mcp_server():
    (pkg,) = SERVER["packages"]
    assert (pkg["registryType"], pkg["identifier"]) == ("pypi", "openroles")
    assert pkg["transport"] == {"type": "stdio"}
    assert [a["value"] for a in pkg["packageArguments"]] == ["mcp"]
    assert len(SERVER["description"]) <= 100
