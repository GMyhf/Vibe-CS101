"""Minimal MCP server (stdio, JSON-RPC 2.0, newline-delimited) — stdlib only.

Exposes the material-index tools to MCP clients such as Claude Code:

    claude mcp add vibe-cs101 -- python3 -m vibe_cs101.mcp_server

Only the tools capability is implemented; requests are handled sequentially.
"""

from __future__ import annotations

import json
import sys

from . import __version__
from .tools import TOOL_SCHEMAS, run_tool

PROTOCOL_VERSION = "2024-11-05"


def _mcp_tools() -> list[dict]:
    return [
        {
            "name": t["function"]["name"],
            "description": t["function"]["description"],
            "inputSchema": t["function"]["parameters"],
        }
        for t in TOOL_SCHEMAS
    ]


def _handle(request: dict) -> dict | None:
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion", PROTOCOL_VERSION),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "vibe-cs101", "version": __version__},
        }
    elif method == "tools/list":
        result = {"tools": _mcp_tools()}
    elif method == "tools/call":
        text = run_tool(params.get("name", ""), json.dumps(params.get("arguments") or {}))
        result = {"content": [{"type": "text", "text": text}]}
    elif method == "ping":
        result = {}
    elif method.startswith("notifications/"):
        return None  # notifications get no response
    else:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def serve() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = _handle(request)
        if response is not None and request.get("id") is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve()
