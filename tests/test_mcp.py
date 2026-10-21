import io
import json
import subprocess
import sys

from openroles import mcp


def test_handshake_and_tool_list():
    lines = [{"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2025-06-18", "capabilities": {}}},
             {"jsonrpc": "2.0", "method": "notifications/initialized"},
             {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
             {"jsonrpc": "2.0", "id": 3, "method": "nope"}]
    out = io.StringIO()
    mcp.serve(io.StringIO("\n".join(json.dumps(x) for x in lines) + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r["id"] for r in replies] == [1, 2, 3]
    assert replies[0]["result"]["protocolVersion"] == "2025-06-18"
    assert {t["name"] for t in replies[1]["result"]["tools"]} == {"find_job_board", "list_open_roles"}
    assert replies[2]["error"]["code"] == -32601


def test_a_line_nested_too_deep_is_a_parse_error_not_a_dead_server():
    out = io.StringIO()
    mcp.serve(io.StringIO("[" * 100_000 + "\n" + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                          + "\n"), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert replies[0]["error"]["code"] == -32700 and replies[1]["id"] == 2


def test_a_tool_error_is_a_result_not_a_crash(web):
    res = mcp.call_tool("list_open_roles", {"target": "lever:nobody"})
    assert res["isError"] is True


def test_descriptions_are_left_out_unless_asked(web):
    from .conftest import fixture
    web.routes["boards-api.greenhouse.io/v1/boards/acme/jobs"] = fixture("greenhouse.json")
    rows = mcp.call_tool("list_open_roles", {"target": "greenhouse:acme"})["structuredContent"]["result"]
    assert rows and "description" not in rows[0]


def test_the_server_runs_as_a_command():
    msg = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "ping"}) + "\n"
    out = subprocess.run([sys.executable, "-m", "openroles", "mcp"], input=msg,
                         capture_output=True, text=True, timeout=30)
    assert json.loads(out.stdout) == {"jsonrpc": "2.0", "id": 1, "result": {}}
