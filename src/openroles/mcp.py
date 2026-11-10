"""A Model Context Protocol server over stdio, with no dependencies.

    openroles mcp

Add it to an MCP client (Claude Code, Claude Desktop, Cursor and others) as a stdio
server whose command is `openroles` with the argument `mcp`, or `uvx openroles mcp`.
It offers two tools: find_job_board and list_open_roles.

The protocol is JSON-RPC 2.0, one message per line on stdin and stdout. Only what a
tools server needs is implemented: initialize, ping, tools/list and tools/call.
"""
from __future__ import annotations

import json
import sys
from typing import Optional

from . import BoardError, __version__, detect, fetch
from .models import systems

PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
DESCRIPTION_CHARS = 4000
MAX_LIMIT = 200

TOOLS = [
    {
        "name": "find_job_board",
        "description": (f"Find which applicant tracking system ({systems()}) an employer "
                        "posts its jobs on. Give a company name, its "
                        "careers page URL or a job board URL. Returns each board as "
                        "{board: ats:token, which list_open_roles accepts, found: how}. found "
                        "is 'named' (the URL or ats:token given), 'linked' (the careers page "
                        "given links to it) or 'guessed' (a board exists under a name the "
                        "company might use; it may be another organisation's, so confirm it "
                        "by giving the employer's careers page URL)."),
        "inputSchema": {
            "type": "object",
            "properties": {"target": {"type": "string",
                                      "description": "company name, careers page URL or board URL"}},
            "required": ["target"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "list_open_roles",
        "description": ("List an employer's open roles straight from its own job board, newest "
                        "first: title, location, remote, posted date, department, pay where "
                        "posted, and the URL to apply. Filter by title words, location and "
                        "remote. Descriptions are left out unless asked for, to keep the "
                        "answer short; with them, a role whose posting hid text from its "
                        "readers says what was left out under 'hidden'."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "ats:token, a board or careers URL, or a company name"},
                "query": {"type": "string", "description": "words that must all appear in the title"},
                "location": {"type": "string", "description": "text that must appear in a location, e.g. London or Remote"},
                "remote_only": {"type": "boolean", "default": False},
                "since_days": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1, "maximum": MAX_LIMIT, "default": 25},
                "include_descriptions": {"type": "boolean", "default": False},
                "country": {"type": "string", "description": "Workday only: narrow to one country by name"},
            },
            "required": ["target"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
]


class _BadArgument(ValueError):
    """An argument a tool cannot use, said as a tool error."""


def _whole(value, name: str) -> Optional[int]:
    """A whole number of at least one from a tool argument (an agent may send "7" or 7.0),
    None when it is missing, and a tool error for anything else."""
    if value is None or value == "":
        return None
    try:
        n = int(str(value).strip()) if isinstance(value, str) else value
    except ValueError:
        n = None
    if isinstance(n, float) and n.is_integer():
        n = int(n)
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise _BadArgument(f"{name} must be a whole number of at least 1, not {value!r}")
    return n


def _yes(value) -> bool:
    """A yes from a tool argument: true, or "true" as some agents send it."""
    return value is True or (isinstance(value, str) and value.strip().lower() in ("true", "yes", "1"))


def _text(value) -> str:
    return value.strip() if isinstance(value, str) else ""


def _result(payload, is_error: bool = False) -> dict:
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    out = {"content": [{"type": "text", "text": text}], "isError": is_error}
    if not is_error and not isinstance(payload, str):
        out["structuredContent"] = {"result": payload}
    return out


def call_tool(name: str, args: dict) -> dict:
    try:
        if name == "find_job_board":
            boards = detect(str(args.get("target") or ""))
            return _result([{"board": str(b), "found": b.found} for b in boards] if boards else
                           f"no {systems()} board found")
        if name == "list_open_roles":
            since = _whole(args.get("since_days"), "since_days")
            described = _yes(args.get("include_descriptions"))
            limit = min(_whole(args.get("limit"), "limit") or 25, MAX_LIMIT)
            jobs = fetch(str(args.get("target") or ""), query=_text(args.get("query")) or None,
                         location=_text(args.get("location")) or None,
                         remote=True if _yes(args.get("remote_only")) else None,
                         since_days=since, limit=limit,
                         details=True if described else None,
                         country=_text(args.get("country")))
            rows = []
            for j in jobs:
                d = j.to_dict()
                if described:
                    d["description"] = (d.get("description") or "")[:DESCRIPTION_CHARS] or None
                    if j.hidden:
                        d["hidden"] = j.hidden
                else:
                    d.pop("description", None)
                rows.append(d)
            return _result(rows)
        return _result(f"unknown tool {name!r}", is_error=True)
    except (BoardError, _BadArgument) as e:
        return _result(str(e), is_error=True)
    except Exception as e:  # noqa: BLE001  a tool error, never a dead server
        return _result(f"{type(e).__name__}: {e}", is_error=True)


def handle(msg: dict) -> Optional[dict]:
    """The response to one JSON-RPC message, or None for a notification."""
    method, mid = msg.get("method"), msg.get("id")
    if mid is None:
        return None
    if method == "initialize":
        asked = (msg.get("params") or {}).get("protocolVersion")
        result = {
            "protocolVersion": asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "openroles", "version": __version__},
            "instructions": ("Use find_job_board to locate an employer's board, then "
                             "list_open_roles to read its open roles."),
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = msg.get("params") or {}
        result = call_tool(str(params.get("name")), params.get("arguments") or {})
    else:
        return {"jsonrpc": "2.0", "id": mid,
                "error": {"code": -32601, "message": f"method not found: {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def serve(stdin=None, stdout=None) -> int:
    stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except (ValueError, RecursionError):        # nested too deep to read is unreadable too
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "parse error"}}
        else:
            reply = handle(msg) if isinstance(msg, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
            stdout.flush()
    return 0
