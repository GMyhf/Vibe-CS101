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


def cmd_quickstart(_args: argparse.Namespace) -> int:
    """一条命令完成初始化：下载每周预构建的全文索引（含课件+题解）。"""
    from .fetch import INDEX_RELEASE_URL, download_prebuilt_index

    print("正在下载预构建索引（每周一自动更新，含课件与全部题解）…")

    def progress(done: int, total: int) -> None:
        if total:
            print(f"\r  {done // (1 << 20)}MB / {total // (1 << 20)}MB", end="", flush=True)

    try:
        size = download_prebuilt_index(on_progress=progress)
    except Exception as exc:  # noqa: BLE001
        print(f"\n❌ 下载失败：{exc}", file=sys.stderr)
        print(f"   可稍后重试，或手动下载 {INDEX_RELEASE_URL} 放到 {DB_PATH}", file=sys.stderr)
        print("   也可以自行构建：vibe-cs101 update && vibe-cs101 index（题解部分）", file=sys.stderr)
        return 1
    print(f"\n✅ 索引就绪（{size / (1 << 20):.1f}MB → {DB_PATH}）")
    print("试试：python3 -m vibe_cs101 search \"动态规划\"")
    print("配置 LLM key 后可对话：python3 -m vibe_cs101 chat（见 README）")
    return 0


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


def _print_mistakes(mistakes) -> None:
    if not mistakes:
        print("（无记录）")
        return
    for m in mistakes:
        badge = "🎓" if m.status == "mastered" else "📌"
        tags = f" [{m.tags}]" if m.tags else ""
        course = f" ({m.course})" if m.course else ""
        print(f"{badge} #{m.id} {m.problem}{course}{tags}")
        if m.reason:
            print(f"     原因: {m.reason}")
        print(f"     复习: {m.next_review}（已复习 {m.review_count} 次）")


def cmd_mistake(args: argparse.Namespace) -> int:
    from . import journal

    action = args.action
    if action == "add":
        m = journal.add_mistake(
            problem=args.problem, course=args.course or "", tags=args.tags or "",
            reason=args.reason or "", note=args.note or "", section_id=args.section,
        )
        print(f"已记入错题本 #{m.id}，{m.next_review} 复习")
    elif action == "list":
        _print_mistakes(journal.list_mistakes(course=args.course, tag=args.tags))
    elif action == "due":
        due = journal.list_mistakes(due_only=True)
        if due:
            print(f"今日待复习 {len(due)} 题：")
        _print_mistakes(due)
    elif action == "review":
        m = journal.review_mistake(args.id, args.result)
        verdict = "已掌握 🎓" if m.status == "mastered" else f"下次复习 {m.next_review}"
        print(f"#{m.id} {m.problem}: {verdict}")
    elif action == "rm":
        print("已删除" if journal.delete_mistake(args.id) else "不存在")
    elif action == "stats":
        s = journal.stats()
        print(f"错题总数 {s['total']}（活跃 {s['active']}，已掌握 {s['mastered']}），今日待复习 {s['due_today']}")
        print(f"累计复习 {s['reviews_total']} 次，遗忘率 {s['again_rate']:.0%}")
        if s["by_tag"]:
            print("\n薄弱知识点（未掌握数排序）:")
            for tag, v in list(s["by_tag"].items())[:10]:
                print(f"  {tag}: {v['total'] - v['mastered']} 未掌握 / {v['total']} 总计")
        if s["by_course"]:
            print("\n按课程:")
            for course, v in s["by_course"].items():
                print(f"  {course}: {v['mastered']}/{v['total']} 已掌握")
    return 0


def cmd_user(args: argparse.Namespace) -> int:
    from . import users

    action = args.action
    try:
        if action == "add":
            key = users.add_user(args.name, key=args.key, role=args.role)
            print(f"✅ 用户 {args.name} 已创建。API key（仅显示这一次，请妥善保存）：")
            print(f"   {key}")
            print("无需重启 serve，立即生效。")
        elif action == "reset":
            key = users.reset_key(args.name)
            print(f"✅ 用户 {args.name} 的 key 已重置（旧 key 立即失效）。新 key：")
            print(f"   {key}")
        elif action == "rm":
            print("已删除" if users.remove_user(args.name) else "不存在")
        elif action == "list":
            rows = users.list_users()
            if not rows:
                print("（无持久化用户；环境变量 VIBE_CS101_AUTH_KEY(S) 配置的用户不在此列）")
            for u in rows:
                seen = f"，最近使用 {u['last_seen']}" if u["last_seen"] else ""
                print(f"  {u['name']} [{u['role']}]（创建于 {u['created']}{seen}）")
    except ValueError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from .server import serve

    serve(host=args.host, port=args.port, tls_cert=args.tls_cert, tls_key=args.tls_key)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="vibe-cs101",
        description="个人计算机基础学习智能体：检索并讲解 cs101/cs201 课件与题解。",
    )
    parser.add_argument("--version", action="version", version=f"vibe-cs101 {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("quickstart", help="一键初始化：下载预构建索引（推荐新同学）").set_defaults(fn=cmd_quickstart)
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

    p = sub.add_parser("mistake", help="错题本：add/list/due/review/rm/stats")
    msub = p.add_subparsers(dest="action", required=True)
    pa = msub.add_parser("add", help="记一道错题")
    pa.add_argument("problem", help='题目标识，如 "OpenJudge 26977 接雨水"')
    pa.add_argument("--course", choices=["cs101", "cs201"])
    pa.add_argument("--tags", help="知识点标签，逗号分隔")
    pa.add_argument("--reason", help="错误原因")
    pa.add_argument("--note", help="正确思路要点")
    pa.add_argument("--section", type=int, help="关联题解章节 id")
    pl = msub.add_parser("list", help="列出错题")
    pl.add_argument("--course", choices=["cs101", "cs201"])
    pl.add_argument("--tags", help="按标签过滤")
    msub.add_parser("due", help="今日待复习")
    pr = msub.add_parser("review", help="记录复习结果")
    pr.add_argument("id", type=int)
    pr.add_argument("result", choices=["good", "again"])
    pd = msub.add_parser("rm", help="删除错题")
    pd.add_argument("id", type=int)
    msub.add_parser("stats", help="学习进度统计")
    p.set_defaults(fn=cmd_mistake)

    p = sub.add_parser("user", help="Web UI 用户管理：add/list/rm/reset（key 加盐哈希存储）")
    usub = p.add_subparsers(dest="action", required=True)
    ua = usub.add_parser("add", help="创建用户并生成 API key")
    ua.add_argument("name", help="用户名（字母/数字/_/-，≤32 字符）")
    ua.add_argument("--role", choices=["teacher", "assistant", "student"], default="student")
    ua.add_argument("--key", help="指定 key（默认自动生成随机 key）")
    usub.add_parser("list", help="列出持久化用户")
    ur = usub.add_parser("reset", help="重置某用户的 key")
    ur.add_argument("name")
    ud = usub.add_parser("rm", help="删除用户")
    ud.add_argument("name")
    p.set_defaults(fn=cmd_user)

    p = sub.add_parser("serve", help="启动 Web UI（对话/检索/错题本）")
    p.add_argument("--host", default="127.0.0.1", help="非本机地址需设置 VIBE_CS101_AUTH_KEY(S)")
    p.add_argument("--port", type=int, default=8101)
    p.add_argument("--tls-cert", help="TLS 证书（PEM，含证书链）→ 启用 HTTPS")
    p.add_argument("--tls-key", help="TLS 私钥（PEM；证书文件已含私钥则可省略）")
    p.set_defaults(fn=cmd_serve)

    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
