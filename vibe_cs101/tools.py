"""Agent tools: search / read the indexed course materials and solutions."""

from __future__ import annotations

import json

from . import store
from .config import LOCAL_SOURCES, REMOTE_SOURCES

TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "search_materials",
            "description": (
                "在老师的课程课件（cs101 计算概论B / cs201 数据结构与算法B）和题解"
                "（LeetCode、OpenJudge、Codeforces、晴问）中全文检索。"
                "支持中英文关键词，返回匹配的章节列表（含 section_id）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "检索关键词，如“动态规划”“monotonic stack”“接雨水”"},
                    "course": {
                        "type": "string",
                        "enum": ["cs101", "cs201"],
                        "description": "可选，限定课程",
                    },
                    "source": {"type": "string", "description": "可选，限定来源名（见 list_sources）"},
                    "limit": {"type": "integer", "description": "返回条数，默认 8"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_section",
            "description": "按 search_materials 返回的 section_id 读取该章节的完整内容。",
            "parameters": {
                "type": "object",
                "properties": {
                    "section_id": {"type": "integer", "description": "章节 id"},
                },
                "required": ["section_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_sources",
            "description": "列出全部资料来源及索引统计（来源名、课程、章节数）。",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]


def _tool_search(args: dict) -> str:
    hits = store.search(
        query=str(args.get("query", "")),
        limit=int(args.get("limit", 8) or 8),
        course=args.get("course") or None,
        source=args.get("source") or None,
    )
    if not hits:
        return json.dumps({"results": [], "hint": "无匹配，试试更短或不同的关键词"}, ensure_ascii=False)
    return json.dumps(
        {
            "results": [
                {
                    "section_id": h.section_id,
                    "source": h.source,
                    "course": h.course,
                    "file": h.file,
                    "title": h.title,
                    "snippet": h.snippet,
                }
                for h in hits
            ]
        },
        ensure_ascii=False,
    )


def _tool_read(args: dict) -> str:
    section = store.get_section(int(args["section_id"]))
    if not section:
        return json.dumps({"error": f"section_id {args['section_id']} 不存在"}, ensure_ascii=False)
    return json.dumps(section, ensure_ascii=False)


def _tool_list_sources(_args: dict) -> str:
    known = {s.name: s.title for s in REMOTE_SOURCES}
    known.update({s.name: s.title for s in LOCAL_SOURCES})
    rows = store.stats()
    return json.dumps(
        {
            "sources": [
                {"name": name, "course": course, "sections": count, "title": known.get(name, "")}
                for name, course, count in rows
            ],
            "indexed": bool(rows),
            "hint": "" if rows else "索引为空：先运行 `vibe-cs101 update && vibe-cs101 index`",
        },
        ensure_ascii=False,
    )


_HANDLERS = {
    "search_materials": _tool_search,
    "read_section": _tool_read,
    "list_sources": _tool_list_sources,
}


def run_tool(name: str, arguments: str) -> str:
    handler = _HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"bad tool arguments: {exc}"}, ensure_ascii=False)
    try:
        return handler(args)
    except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
