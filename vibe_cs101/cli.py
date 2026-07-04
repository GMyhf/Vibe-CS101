"""Vibe-cs101 command-line interface."""

from __future__ import annotations

import argparse
import sys

from . import __version__, store
from .config import DB_PATH, LOCAL_SOURCES, REMOTE_SOURCES, load_llm_config

BANNER = f"""\
┌─────────────────────────────────────────────┐
│  Vibe-cs101 v{__version__} — 个人计算机基础学习智能体  │
│  cs101 计算概论B · cs201 数据结构与算法B      │
└─────────────────────────────────────────────┘"""


def cmd_update(_args: argparse.Namespace) -> int:
    from .fetch import fetch_all

    ok = True
    for r in fetch_all():
        mark = {"updated": "⬇️ ", "unchanged": "✅", "cached": "📦", "error": "❌"}[r.status]
        print(f"{mark} {r.name}: {r.status}" + (f" ({r.detail})" if r.detail else ""))
        ok = ok and r.status != "error"
    if not ok:
        print("\n部分来源下载失败（可稍后重试）；已有本地副本的来源不受影响。", file=sys.stderr)
    return 0 if ok else 1


def cmd_index(_args: argparse.Namespace) -> int:
    from .indexer import rebuild_index

    counts = rebuild_index()
    if not counts:
        print("没有可索引的资料。先运行 `vibe-cs101 update`，并确认课件目录存在。", file=sys.stderr)
        return 1
    total = sum(counts.values())
    for name, n in sorted(counts.items()):
        print(f"  {name}: {n} sections")
    print(f"索引完成：{total} sections → {DB_PATH}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    hits = store.search(args.query, limit=args.limit, course=args.course, source=args.source)
    if not hits:
        print("无匹配结果。若索引为空，先运行 `vibe-cs101 update && vibe-cs101 index`。")
        return 1
    for h in hits:
        print(f"[{h.section_id}] ({h.source}/{h.course}) {h.title}")
        print(f"      {h.snippet}\n")
    print("用 `vibe-cs101 show <id>` 查看完整章节。")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    section = store.get_section(args.section_id)
    if not section:
        print(f"section {args.section_id} 不存在", file=sys.stderr)
        return 1
    print(f"# {section['title']}")
    print(f"(来源: {section['source']} / {section['course']} / {section['file']})\n")
    print(section["content"])
    return 0


def cmd_info(_args: argparse.Namespace) -> int:
    print(BANNER)
    cfg = load_llm_config()
    print(f"\nLLM: {'已配置 ' + cfg.model + ' @ ' + cfg.base_url if cfg.configured else '未配置（chat/ask 不可用，search/show 可用）'}")
    rows = store.stats()
    if rows:
        print(f"索引: {DB_PATH}")
        for name, course, count in rows:
            print(f"  {name} ({course}): {count} sections")
    else:
        print("索引为空：运行 `vibe-cs101 update && vibe-cs101 index`")
    print("\n资料来源:")
    for local in LOCAL_SOURCES:
        exists = "✓" if local.path.is_dir() else "✗ 缺失"
        print(f"  [本地 {exists}] {local.name}: {local.title}")
    for remote in REMOTE_SOURCES:
        print(f"  [远程] {remote.name}: {remote.title}")
    return 0


def _make_agent():
    from .agent import Agent

    return Agent(on_event=lambda msg: print(f"  {msg}", file=sys.stderr))


def cmd_ask(args: argparse.Namespace) -> int:
    from .llm import LLMError

    agent = _make_agent()
    try:
        print(agent.ask(args.question))
    except LLMError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_chat(_args: argparse.Namespace) -> int:
    from .llm import LLMError

    print(BANNER)
    print("输入问题开始对话；exit / quit / Ctrl-D 退出。\n")
    agent = _make_agent()
    while True:
        try:
            question = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            break
        try:
            answer = agent.ask(question)
        except LLMError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            continue
        print(f"\n助教> {answer}\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vibe-cs101",
        description="个人计算机基础学习智能体：检索并讲解 cs101/cs201 课件与题解。",
    )
    parser.add_argument("--version", action="version", version=f"vibe-cs101 {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("update", help="下载/更新上游题解").set_defaults(fn=cmd_update)
    sub.add_parser("index", help="重建全文索引").set_defaults(fn=cmd_index)

    p = sub.add_parser("search", help="全文检索课件与题解")
    p.add_argument("query")
    p.add_argument("--course", choices=["cs101", "cs201"])
    p.add_argument("--source")
    p.add_argument("--limit", type=int, default=8)
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("show", help="查看完整章节")
    p.add_argument("section_id", type=int)
    p.set_defaults(fn=cmd_show)

    p = sub.add_parser("ask", help="向智能体提问（单轮）")
    p.add_argument("question")
    p.set_defaults(fn=cmd_ask)

    sub.add_parser("chat", help="交互式对话").set_defaults(fn=cmd_chat)
    sub.add_parser("info", help="显示配置与索引状态").set_defaults(fn=cmd_info)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
