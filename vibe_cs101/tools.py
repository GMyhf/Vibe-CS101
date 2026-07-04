"""Agent tools: search / read the indexed course materials and solutions."""

from __future__ import annotations

import json

from . import store
from .config import LOCAL_SOURCES, REMOTE_SOURCES

MAX_SECTION_CHARS = 6000

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
    {
        "type": "function",
        "function": {
            "name": "record_mistake",
            "description": (
                "把一道做错的题记入错题本（自动安排 1/3/7/14/30 天间隔复习）。"
                "当用户说做错了某题、某题不会做、希望记下来复习时使用。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string", "description": "题目标识，如“OpenJudge 26977 接雨水”"},
                    "course": {"type": "string", "enum": ["cs101", "cs201"], "description": "所属课程"},
                    "tags": {"type": "string", "description": "知识点标签，逗号分隔，如“dp,单调栈”"},
                    "reason": {"type": "string", "description": "错误原因（思路错/边界条件/超时/语法等）"},
                    "note": {"type": "string", "description": "正确思路要点"},
                    "section_id": {"type": "integer", "description": "关联题解章节 id（可选，来自 search_materials）"},
                },
                "required": ["problem"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "review_mistakes",
            "description": "查询错题本：今日待复习列表、全部错题、或学习进度统计（薄弱知识点排行）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "view": {
                        "type": "string",
                        "enum": ["due", "all", "stats"],
                        "description": "due=今日待复习，all=全部错题，stats=进度统计",
                    },
                    "course": {"type": "string", "enum": ["cs101", "cs201"]},
                    "tag": {"type": "string", "description": "按标签过滤"},
                },
                "required": ["view"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "mark_reviewed",
            "description": "记录一次错题复习结果：good（记住了，间隔前进）或 again（还是不会，重新开始）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "mistake_id": {"type": "integer"},
                    "result": {"type": "string", "enum": ["good", "again"]},
                },
                "required": ["mistake_id", "result"],
            },
        },
    },
]


def _tool_search(args: dict, context: dict) -> str:
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


def _tool_read(args: dict, context: dict) -> str:
    section = store.get_section(int(args["section_id"]))
    if not section:
        return json.dumps({"error": f"section_id {args['section_id']} 不存在"}, ensure_ascii=False)
    content = section.get("content", "")
    if len(content) > MAX_SECTION_CHARS:
        section = dict(section)
        section["content"] = content[:MAX_SECTION_CHARS] + "\n\n[内容已截断：只返回前 6000 字。需要更具体内容请重新检索更精确章节。]"
        section["truncated"] = True
    return json.dumps(section, ensure_ascii=False)


def _tool_list_sources(_args: dict, context: dict) -> str:
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


def _tool_record_mistake(args: dict, context: dict) -> str:
    from . import journal

    m = journal.add_mistake(
        problem=str(args.get("problem", "")),
        course=args.get("course") or "",
        tags=args.get("tags") or "",
        reason=args.get("reason") or "",
        note=args.get("note") or "",
        section_id=args.get("section_id"),
        db_path=context.get("journal_db"),
    )
    return json.dumps({"recorded": m.to_dict(), "hint": f"已记入错题本，{m.next_review} 复习"}, ensure_ascii=False)


def _tool_review_mistakes(args: dict, context: dict) -> str:
    from . import journal

    view = args.get("view", "due")
    if view == "stats":
        return json.dumps(journal.stats(db_path=context.get("journal_db")), ensure_ascii=False)
    mistakes = journal.list_mistakes(
        due_only=(view == "due"),
        course=args.get("course") or None,
        tag=args.get("tag") or None,
        db_path=context.get("journal_db"),
    )
    return json.dumps({"mistakes": [m.to_dict() for m in mistakes]}, ensure_ascii=False)


def _tool_mark_reviewed(args: dict, context: dict) -> str:
    from . import journal

    m = journal.review_mistake(
        int(args["mistake_id"]), str(args.get("result", "good")), db_path=context.get("journal_db")
    )
    return json.dumps({"updated": m.to_dict()}, ensure_ascii=False)


_HANDLERS = {
    "search_materials": _tool_search,
    "read_section": _tool_read,
    "list_sources": _tool_list_sources,
    "record_mistake": _tool_record_mistake,
    "review_mistakes": _tool_review_mistakes,
    "mark_reviewed": _tool_mark_reviewed,
}


def run_tool(name: str, arguments: str, context: dict | None = None) -> str:
    """context 可携带调用方信息，目前支持 journal_db（按用户隔离的错题本路径）。"""
    handler = _HANDLERS.get(name)
    if not handler:
        return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
    try:
        args = json.loads(arguments) if arguments else {}
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"bad tool arguments: {exc}"}, ensure_ascii=False)
    try:
        return handler(args, context or {})
    except Exception as exc:  # noqa: BLE001 - tool errors go back to the model
        return json.dumps({"error": str(exc)}, ensure_ascii=False)
