"""Web UI 后端：标准库 ThreadingHTTPServer 上的 REST API + 静态页面.

架构参照 Vibe-Trading（后端 API + 单页前端），但保持零依赖：
不用 FastAPI/uvicorn，路由风格保持一致，前端是无构建的单页应用（web/）。
默认只监听 127.0.0.1，仅供本机使用。

API:
    GET  /api/info                     配置与索引状态
    GET  /api/search?q=&course=&limit= 全文检索
    GET  /api/section/{id}             读取章节全文
    GET  /api/document/{section_id}    读取命中 section 所在整篇文档
    POST /api/chat                     {message, session_id?} → {answer, events, session_id}
    GET  /api/sessions                 会话列表（持久化于 data/sessions.db）
    GET  /api/sessions/{id}            会话历史消息（前端可展示部分）
    DELETE /api/sessions/{id}          删除会话
    GET  /api/library                  知识库：原始课件/题解文件列表
    GET  /api/library/file?source=&path=[&download=1]   查看/下载原始文件
    GET  /api/sol101                   题解查询工具入口配置
    GET  /api/solutions                原生题解查询：题解集列表
    GET  /api/solutions/list?set=      原生题解查询：列出题集题目
    GET  /api/solutions/search?q=&set=&limit=  原生题解查询：搜索题目
    GET  /api/solutions/file?set=&path=        原生题解查询：读取 Markdown
    GET  /api/mistakes?view=all|due    错题列表
    POST /api/mistakes                 记错题 {problem, course?, tags?, reason?, note?, link?, section_id?}
    GET  /api/mistakes/{id}            读取错题详情
    POST /api/mistakes/{id}/review     {result: good|again}
    DELETE /api/mistakes/{id}          删除
    GET  /api/mistakes/stats           进度统计
    GET  /api/admin/users              教师查看用户
    GET  /api/admin/users/export       教师导出成员 CSV
    POST /api/admin/users              教师添加用户 {name, role, key?}
    POST /api/admin/users/import       教师批量导入学生 {text}
    PATCH /api/admin/users/{name}      教师修改用户角色 {role}
    POST /api/admin/users/{name}/reset 教师重置用户 key
    DELETE /api/admin/users/{name}     教师删除用户
    GET  /api/admin/courses            教师/助教查看课程资源配置
    POST /api/admin/courses/{course}   教师/助教指定课件和题解 {resources}
    GET  /api/admin/logs               教师/助教查看学生行为日志
    GET  /api/admin/logs/export        教师/助教导出学生行为日志 CSV

鉴权：VIBE_CS101_AUTH_KEY(S) 环境变量 + `vibe-cs101 user add` 管理的持久化用户（二者并存）。
限流：VIBE_CS101_RATE_API / _RATE_CHAT（按用户）、_RATE_AUTHFAIL（按 IP），超限返回 429。
会话：每轮对话后持久化，服务重启后带 session_id 请求可无缝恢复上下文。
"""

from __future__ import annotations

import csv
import hmac
import io
import ipaddress
import json
import re
import ssl
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from . import audit, courses, journal, ratelimit, sessions, store, users
from .config import (
    DATA_DIR,
    DB_PATH,
    LOCAL_SOURCES,
    ORIGINAL_DIR,
    REMOTE_SOURCES,
    load_auth_keys,
    load_llm_config,
)

WEB_DIR = Path(__file__).resolve().parent / "web"
SOL101_DOCS_DIR = DATA_DIR / "sol101" / "docs"
SOL101_DIST_DIR = DATA_DIR / "sol101" / "docs" / ".vitepress" / "dist"
MAX_BODY = 1 << 20  # 1MB
MAX_SESSIONS = 50  # 内存中的活跃会话上限；被挤出的会话可随时从 sessions.db 恢复

# 知识库：可浏览/下载的原始资料文件类型与单来源文件数上限
LIB_EXTS = {".md", ".pdf", ".py", ".cpp", ".c", ".h", ".txt", ".ipynb",
            ".zip", ".csv", ".png", ".jpg", ".jpeg", ".gif", ".pptx", ".docx", ".xlsx"}
LIB_TEXT_EXTS = {".md", ".py", ".cpp", ".c", ".h", ".txt", ".csv"}
LIB_MAX_FILES = 800

SOL101_SET_META = {
    "oj-dsa": {"title": "OpenJudge 数算", "course": "cs201", "badge": "OJ"},
    "oj": {"title": "OpenJudge 计概", "course": "cs101", "badge": "OJ"},
    "cf": {"title": "Codeforces", "course": "cs101", "badge": "CF"},
    "leetcode-em": {"title": "LeetCode 易+中", "course": "cs101", "badge": "LC"},
    "leetcode-tough": {"title": "LeetCode 难", "course": "cs101", "badge": "LC+"},
    "sunnywhy": {"title": "Sunnywhy", "course": "cs201", "badge": "SY"},
    "cpp": {"title": "C++ 题解", "course": "cs201", "badge": "C++"},
}
SOL101_SKIP_DIRS = {".vitepress", "public", "__pycache__"}
SOL101_MAX_FILE = 2_000_000


def _sol101_set_order() -> list[str]:
    known = [name for name in SOL101_SET_META if (SOL101_DOCS_DIR / name).is_dir()]
    extra = []
    if SOL101_DOCS_DIR.is_dir():
        for p in sorted(SOL101_DOCS_DIR.iterdir()):
            if p.is_dir() and p.name not in SOL101_SET_META and p.name not in SOL101_SKIP_DIRS:
                extra.append(p.name)
    return known + extra


def _sol101_set_info(name: str) -> dict:
    meta = SOL101_SET_META.get(name, {})
    root = SOL101_DOCS_DIR / name
    count = 0
    if root.is_dir():
        count = sum(1 for p in root.glob("*.md") if p.name != "index.md")
    return {
        "name": name,
        "title": meta.get("title", name),
        "course": meta.get("course", ""),
        "badge": meta.get("badge", name[:3].upper()),
        "count": count,
    }


def _sol101_sets() -> list[dict]:
    return [_sol101_set_info(name) for name in _sol101_set_order()]


def _resolve_solution_file(set_name: str, rel_path: str) -> Path | None:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", set_name):
        return None
    if set_name not in _sol101_set_order():
        return None
    root = (SOL101_DOCS_DIR / set_name).resolve()
    try:
        file = (root / rel_path).resolve()
        file.relative_to(root)
    except (ValueError, OSError):
        return None
    if not file.is_file() or file.suffix.lower() != ".md":
        return None
    if file.name == "index.md" or any(part.startswith(".") for part in file.relative_to(root).parts):
        return None
    if file.stat().st_size > SOL101_MAX_FILE:
        return None
    return file


def _solution_title_and_meta(text: str, fallback: str) -> tuple[str, str]:
    title = fallback
    meta = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            title = stripped[2:].strip() or title
            continue
        if title != fallback and not stripped.startswith("#"):
            meta = stripped
            break
    return title, meta


def _query_terms(query: str) -> list[str]:
    terms = re.findall(r"[0-9A-Za-z_.+#-]+|[\u3400-\u9fff]+", query.lower())
    return [t for t in terms if len(t) >= 1]


def _solution_sidebar_order(set_name: str) -> dict[str, int]:
    config = SOL101_DOCS_DIR / ".vitepress" / "config.mjs"
    if not config.is_file():
        return {}
    text = config.read_text(encoding="utf-8", errors="replace")
    links = re.findall(rf"link:\s*'/{re.escape(set_name)}/([^']+)'", text)
    order: dict[str, int] = {}
    for i, link in enumerate(links):
        path = link.lstrip("/")
        if not path.endswith(".md"):
            path += ".md"
        order.setdefault(path, i)
    return order


def _solution_snippet(text: str, terms: list[str], max_len: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    lower = compact.lower()
    pos = -1
    for term in terms:
        pos = lower.find(term)
        if pos >= 0:
            break
    if pos < 0:
        return compact[:max_len]
    start = max(0, pos - max_len // 3)
    end = min(len(compact), start + max_len)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return prefix + compact[start:end] + suffix


def _solution_entry(set_name: str, file: Path, terms: list[str] | None = None) -> dict:
    root = SOL101_DOCS_DIR / set_name
    rel = file.relative_to(root).as_posix()
    text = file.read_text(encoding="utf-8", errors="replace")
    title, meta = _solution_title_and_meta(text, file.stem)
    set_info = _sol101_set_info(set_name)
    return {
        "set": set_name,
        "set_title": set_info["title"],
        "badge": set_info["badge"],
        "course": set_info["course"],
        "path": rel,
        "title": title,
        "meta": meta,
        "snippet": _solution_snippet(text, terms or []),
    }


def _list_solutions(set_name: str) -> list[dict]:
    if set_name not in _sol101_set_order():
        return []
    root = SOL101_DOCS_DIR / set_name
    if not root.is_dir():
        return []
    entries = [
        _solution_entry(set_name, file, [])
        for file in sorted(root.glob("*.md"))
        if file.name != "index.md" and file.stat().st_size <= SOL101_MAX_FILE
    ]
    order = _solution_sidebar_order(set_name)
    entries.sort(key=lambda e: (order.get(e["path"], len(order) + 1), e["path"]))
    nav = [_solution_nav_item(entry) for entry in entries]
    for i, entry in enumerate(entries):
        entry["prev"] = nav[i - 1] if i > 0 else None
        entry["next"] = nav[i + 1] if i + 1 < len(entries) else None
    return entries


def _solution_nav_item(entry: dict) -> dict:
    return {
        "set": entry["set"],
        "set_title": entry["set_title"],
        "path": entry["path"],
        "title": entry["title"],
    }


def _solution_neighbors(set_name: str, rel_path: str) -> tuple[dict | None, dict | None]:
    entries = _list_solutions(set_name)
    for i, entry in enumerate(entries):
        if entry["path"] == rel_path:
            prev_item = _solution_nav_item(entries[i - 1]) if i > 0 else None
            next_item = _solution_nav_item(entries[i + 1]) if i + 1 < len(entries) else None
            return prev_item, next_item
    return None, None


def _search_solutions(query: str, set_name: str | None, limit: int) -> list[dict]:
    terms = _query_terms(query)
    sets = [set_name] if set_name else _sol101_set_order()
    ranked: list[tuple[int, str, dict]] = []
    for name in sets:
        if name not in _sol101_set_order():
            continue
        root = SOL101_DOCS_DIR / name
        if not root.is_dir():
            continue
        for file in sorted(root.glob("*.md")):
            if file.name == "index.md" or file.stat().st_size > SOL101_MAX_FILE:
                continue
            entry = _solution_entry(name, file, terms)
            hay_title = entry["title"].lower()
            hay_path = entry["path"].lower()
            hay_meta = entry["meta"].lower()
            if terms:
                text = file.read_text(encoding="utf-8", errors="replace").lower()
                if not all(t in text or t in hay_title or t in hay_path or t in hay_meta for t in terms):
                    continue
                score = 0
                for term in terms:
                    score += 30 if term in hay_title else 0
                    score += 12 if term in hay_path else 0
                    score += 8 if term in hay_meta else 0
                    score += min(text.count(term), 8)
            else:
                score = 1
            ranked.append((score, f"{name}/{entry['path']}", entry))
    ranked.sort(key=lambda x: (-x[0], x[1]))
    return [entry for _score, _key, entry in ranked[:limit]]


def _library_roots() -> dict[str, tuple[str, Path]]:
    """知识库根目录：本地课件仓库 + 已下载的上游题解原文。"""
    roots: dict[str, tuple[str, Path]] = {}
    for src in LOCAL_SOURCES:
        if src.path.is_dir():
            roots[src.name] = (src.title, src.path)
    if ORIGINAL_DIR.is_dir():
        roots["solutions"] = ("题解原文（上游长 Markdown）", ORIGINAL_DIR)
    return roots


def _library_display_prefix(source_name: str, root: Path) -> str:
    """Directory name shown in the left knowledge-base tree."""
    if root.resolve() == ORIGINAL_DIR.resolve():
        return ""
    return source_name


def _hidden_library_files(root: Path) -> set[str]:
    if root.resolve() != ORIGINAL_DIR.resolve():
        return set()
    hidden = set()
    for src in REMOTE_SOURCES:
        if src.original_path.is_file() and src.legacy_original_path.is_file():
            hidden.add(src.legacy_original_path.relative_to(ORIGINAL_DIR).as_posix())
    return hidden


def _library_files(
    root: Path,
    hidden: set[str] | None = None,
    display_prefix: str = "",
) -> list[dict]:
    root = root.resolve()
    hidden = hidden or set()
    files = []
    for p in sorted(root.rglob("*")):
        if len(files) >= LIB_MAX_FILES:
            break
        if not p.is_file() or p.suffix.lower() not in LIB_EXTS:
            continue
        try:
            p.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        rel = p.relative_to(root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        rel_path = rel.as_posix()
        if rel_path in hidden:
            continue
        display_path = f"{display_prefix}/{rel_path}" if display_prefix else rel_path
        files.append({"path": rel_path, "display_path": display_path, "size": p.stat().st_size})
    return files


def _resolve_library_file(source: str, rel_path: str) -> Path | None:
    roots = _library_roots()
    if source not in roots:
        return None
    root = roots[source][1].resolve()
    try:
        file = (root / rel_path).resolve()
        file.relative_to(root)
    except (ValueError, OSError):
        return None
    if not file.is_file() or file.suffix.lower() not in LIB_EXTS:
        return None
    if any(part.startswith(".") for part in file.relative_to(root).parts):
        return None
    return file

AUTH_KEYS: dict[str, str] = {}  # {username: key}; 来自环境变量；DB 用户见 users.py

API_LIMITER = ratelimit.from_env("VIBE_CS101_RATE_API", "120/60")
CHAT_LIMITER = ratelimit.from_env("VIBE_CS101_RATE_CHAT", "10/60")
AUTH_FAIL_LIMITER = ratelimit.from_env("VIBE_CS101_RATE_AUTHFAIL", "10/300")

_sessions: dict[tuple[str, str], dict] = {}  # (user, session_id) -> {"agent", "lock"}
_sessions_lock = threading.Lock()


def _auth_enabled() -> bool:
    return bool(AUTH_KEYS) or users.has_users()


def _role_of(user: str) -> str:
    return users.role_of(user)


def _can_manage_users(user: str) -> bool:
    return _role_of(user) == "teacher"


def _can_manage_courses(user: str) -> bool:
    return _role_of(user) in {"teacher", "assistant"}


def _can_view_student_logs(user: str) -> bool:
    return _role_of(user) in {"teacher", "assistant"}


def _public_user(user: str) -> dict:
    info = users.get_user(user) or {"name": user, "role": users.DEFAULT_ROLE}
    return {"name": info["name"], "role": info["role"]}


def _log_action(user: str, action: str, detail: dict | None = None) -> None:
    try:
        audit.log(user, _role_of(user), action, detail)
    except Exception:  # noqa: BLE001 - audit must not break user-facing flows
        pass


def _get_session(user: str, session_id: str | None) -> tuple[str, dict]:
    with _sessions_lock:
        if session_id and (user, session_id) in _sessions:
            return session_id, _sessions[(user, session_id)]
        from .agent import Agent

        new_id = session_id or uuid.uuid4().hex[:12]
        agent = Agent(tool_context={"journal_db": journal.user_db(user)})
        if session_id:  # 内存中没有：尝试从持久化存储恢复上下文
            saved = sessions.load(user, session_id)
            if saved:
                agent.messages = saved
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        _sessions[(user, new_id)] = {"agent": agent, "lock": threading.Lock()}
        return new_id, _sessions[(user, new_id)]


def _is_loopback(host: str) -> bool:
    if host in ("localhost",):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class Handler(BaseHTTPRequestHandler):
    server_version = "vibe-cs101"

    # ---- helpers -------------------------------------------------------
    def _json(self, obj: object, status: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _sse_start(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        # SSE 没有 Content-Length，必须以关闭连接标记流结束，
        # 否则浏览器端 fetch 永远等不到 EOF，发送按钮一直禁用
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True

    def _sse(self, obj: object) -> None:
        body = json.dumps(obj, ensure_ascii=False)
        self.wfile.write(f"data: {body}\n\n".encode("utf-8"))
        self.wfile.flush()

    def _error(self, status: int, message: str) -> None:
        self._json({"error": message}, status)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError("request body too large")
        raw = self.rfile.read(length) if length else b"{}"
        data = json.loads(raw.decode("utf-8") or "{}")
        if not isinstance(data, dict):
            raise ValueError("JSON body must be an object")
        return data

    def log_message(self, fmt: str, *args: object) -> None:  # quieter logs
        pass

    # ---- auth / rate limit ---------------------------------------------
    def _rate_limited(self, retry_after: float, what: str = "请求") -> None:
        wait = max(1, int(retry_after + 0.999))
        body = json.dumps(
            {"error": f"{what}过于频繁，请 {wait} 秒后重试"}, ensure_ascii=False
        ).encode("utf-8")
        self.send_response(429)
        self.send_header("Retry-After", str(wait))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authenticate(self) -> str | None:
        """Return the username, or None if auth is required and failed."""
        if not _auth_enabled():
            return "owner"  # 未启用鉴权：仅本机模式（serve() 保证非本机必须配 key）
        header = self.headers.get("Authorization", "")
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        presented = presented or self.headers.get("X-API-Key", "").strip()
        if presented:
            for user, key in AUTH_KEYS.items():
                if hmac.compare_digest(presented, key):
                    return user
            return users.verify_key(presented)
        return None

    def _require_auth(self) -> str | None:
        """鉴权 + 通用限流。返回用户名；失败时已发送响应，调用方直接 return。"""
        ip = self.client_address[0]
        if _auth_enabled():
            wait = AUTH_FAIL_LIMITER.retry_after(ip)
            if wait > 0:
                self._rate_limited(wait, "鉴权失败")
                return None
        user = self._authenticate()
        if user is None:
            AUTH_FAIL_LIMITER.hit(ip)
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="vibe-cs101"')
            body = json.dumps({"error": "需要 API key（Authorization: Bearer <key>）"}).encode()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return None
        wait = API_LIMITER.hit(user)
        if wait > 0:
            self._rate_limited(wait)
            return None
        return user

    # ---- static --------------------------------------------------------
    def _serve_static(self, path: str) -> None:
        name = "index.html" if path in ("/", "") else path.lstrip("/")
        file = (WEB_DIR / name).resolve()
        try:
            file.relative_to(WEB_DIR)
        except ValueError:
            self._error(404, "not found")
            return
        if not file.is_file():
            self._error(404, "not found")
            return
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(file.suffix, "application/octet-stream")
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sol101_static(self, path: str) -> None:
        if path == "/sol101":
            self.send_response(302)
            self.send_header("Location", "/sol101/")
            self.end_headers()
            return
        rel = path[len("/sol101/") :]
        name = "index.html" if rel in ("", "/") else rel
        file = (SOL101_DIST_DIR / name).resolve()
        try:
            file.relative_to(SOL101_DIST_DIR)
        except ValueError:
            self._error(404, "not found")
            return
        if not file.is_file():
            fallback = (SOL101_DIST_DIR / "index.html").resolve()
            if not fallback.is_file():
                self._error(404, "sol101 site has not been built")
                return
            file = fallback
        ctype = {
            ".html": "text/html; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".svg": "image/svg+xml",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".ico": "image/x-icon",
            ".json": "application/json; charset=utf-8",
        }.get(file.suffix, "application/octet-stream")
        body = file.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if url.path == "/sol101" or url.path.startswith("/sol101/"):
            self._serve_sol101_static(url.path)
            return
        if not url.path.startswith("/api/"):
            self._serve_static(url.path)
            return
        user = self._require_auth()
        if user is None:
            return
        try:
            if url.path == "/api/me":
                me = _public_user(user)
                self._json(
                    {
                        "user": me["name"],
                        "role": me["role"],
                        "auth_enabled": _auth_enabled(),
                        "can_manage_users": _can_manage_users(user),
                        "can_manage_courses": _can_manage_courses(user),
                        "can_view_student_logs": _can_view_student_logs(user),
                    }
                )
            elif url.path == "/api/info":
                cfg = load_llm_config()
                self._json(
                    {
                        "llm_configured": cfg.configured,
                        "model": cfg.model if cfg.configured else None,
                        "index": [
                            {"source": s, "course": c, "sections": n} for s, c, n in store.stats()
                        ],
                        "db_path": str(DB_PATH),
                    }
                )
            elif url.path == "/api/search":
                query = q.get("q", [""])[0]
                course = q.get("course", [None])[0] or None
                source = q.get("source", [None])[0] or None
                enabled_sources = None if source else courses.enabled_resources(course)
                hits = store.search(
                    query,
                    limit=min(int(q.get("limit", ["10"])[0]), 50),
                    course=course,
                    source=source,
                    sources=enabled_sources,
                )
                _log_action(
                    user,
                    "search",
                    {"query": query, "course": course, "source": source, "results": len(hits)},
                )
                self._json({"results": [h.__dict__ for h in hits]})
            elif m := re.fullmatch(r"/api/section/(\d+)", url.path):
                section = store.get_section(int(m.group(1)))
                if section:
                    _log_action(
                        user,
                        "section_read",
                        {
                            "section_id": section["section_id"],
                            "source": section["source"],
                            "course": section["course"],
                            "file": section["file"],
                        },
                    )
                    self._json(section)
                else:
                    self._error(404, "section not found")
            elif m := re.fullmatch(r"/api/document/(\d+)", url.path):
                doc = store.get_document_for_section(int(m.group(1)))
                if doc:
                    _log_action(
                        user,
                        "document_read",
                        {
                            "section_id": doc["matched_section_id"],
                            "source": doc["source"],
                            "course": doc["course"],
                            "file": doc["file"],
                            "sections": doc["section_count"],
                        },
                    )
                    self._json(doc)
                else:
                    self._error(404, "document not found")
            elif url.path == "/api/library":
                _log_action(user, "library_list", {})
                self._json(
                    {
                        "sources": [
                            {
                                "name": name,
                                "title": title,
                                "files": _library_files(
                                    root,
                                    _hidden_library_files(root),
                                    _library_display_prefix(name, root),
                                ),
                            }
                            for name, (title, root) in _library_roots().items()
                        ]
                    }
                )
            elif url.path == "/api/library/file":
                source = q.get("source", [""])[0]
                rel_path = q.get("path", [""])[0]
                file = _resolve_library_file(source, rel_path)
                if file is None:
                    self._error(404, "file not found")
                    return
                download = bool(q.get("download", [""])[0])
                _log_action(
                    user,
                    "library_download" if download else "library_view",
                    {"source": source, "path": rel_path},
                )
                import mimetypes

                ctype = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                if file.suffix.lower() in LIB_TEXT_EXTS:
                    ctype = "text/plain; charset=utf-8"
                body = file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                if download:
                    self.send_header(
                        "Content-Disposition",
                        f"attachment; filename*=UTF-8''{quote(file.name)}",
                    )
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/sol101":
                _log_action(user, "sol101_view", {})
                self._json(
                    {
                        "title": "题解查询",
                        "mode": "native",
                        "site_url": "/sol101/",
                        "repo_url": "https://github.com/FuYnAloft/sol101",
                        "sets": _sol101_sets(),
                    }
                )
            elif url.path == "/api/solutions":
                _log_action(user, "solutions_list", {})
                self._json({"sets": _sol101_sets(), "site_url": "/sol101/"})
            elif url.path == "/api/solutions/list":
                set_name = q.get("set", [""])[0]
                if set_name not in _sol101_set_order():
                    self._error(404, "solution set not found")
                    return
                items = _list_solutions(set_name)
                _log_action(user, "solutions_list", {"set": set_name, "count": len(items)})
                self._json({"set": _sol101_set_info(set_name), "items": items})
            elif url.path == "/api/solutions/search":
                query = q.get("q", [""])[0]
                set_name = q.get("set", [None])[0] or None
                limit = min(int(q.get("limit", ["30"])[0]), 80)
                results = _search_solutions(query, set_name, limit)
                _log_action(
                    user,
                    "solutions_search",
                    {"query": query, "set": set_name, "results": len(results)},
                )
                self._json({"results": results})
            elif url.path == "/api/solutions/file":
                set_name = q.get("set", [""])[0]
                rel_path = q.get("path", [""])[0]
                file = _resolve_solution_file(set_name, rel_path)
                if file is None:
                    self._error(404, "solution not found")
                    return
                text = file.read_text(encoding="utf-8", errors="replace")
                title, meta = _solution_title_and_meta(text, file.stem)
                set_info = _sol101_set_info(set_name)
                prev_item, next_item = _solution_neighbors(set_name, rel_path)
                _log_action(
                    user,
                    "solution_read",
                    {"set": set_name, "path": rel_path, "title": title},
                )
                self._json(
                    {
                        "set": set_name,
                        "set_title": set_info["title"],
                        "badge": set_info["badge"],
                        "course": set_info["course"],
                        "path": rel_path,
                        "title": title,
                        "meta": meta,
                        "prev": prev_item,
                        "next": next_item,
                        "content": text,
                    }
                )
            elif url.path == "/api/sessions":
                self._json({"sessions": sessions.list_sessions(user)})
            elif m := re.fullmatch(r"/api/sessions/([A-Za-z0-9-]{1,64})", url.path):
                msgs = sessions.load(user, m.group(1))
                if msgs is None:
                    self._error(404, "session not found")
                else:
                    self._json(
                        {"session_id": m.group(1), "messages": sessions.display_messages(msgs)}
                    )
            elif url.path == "/api/mistakes/stats":
                _log_action(user, "stats_view", {})
                self._json(journal.stats(db_path=journal.user_db(user)))
            elif url.path == "/api/mistakes":
                view = q.get("view", ["all"])[0]
                mistakes = journal.list_mistakes(
                    due_only=(view == "due"),
                    course=q.get("course", [None])[0] or None,
                    tag=q.get("tag", [None])[0] or None,
                    db_path=journal.user_db(user),
                )
                _log_action(user, "mistakes_view", {"view": view, "count": len(mistakes)})
                self._json({"mistakes": [m.to_dict() for m in mistakes]})
            elif m := re.fullmatch(r"/api/mistakes/(\d+)", url.path):
                mistake = journal.get_mistake(int(m.group(1)), db_path=journal.user_db(user))
                if not mistake:
                    self._error(404, "mistake not found")
                    return
                _log_action(user, "mistake_view", {"id": mistake.id})
                self._json({"mistake": mistake.to_dict()})
            elif url.path == "/api/admin/users":
                if not _can_manage_users(user):
                    self._error(403, "需要教师权限")
                    return
                self._json({"users": users.list_users()})
            elif url.path == "/api/admin/users/export":
                if not _can_manage_users(user):
                    self._error(403, "需要教师权限")
                    return

                out = io.StringIO()
                writer = csv.writer(out)
                writer.writerow(["学号", "姓名", "院系", "权限", "加入时间", "最近使用", "用户名"])
                for u in users.list_users():
                    writer.writerow(
                        [
                            u["student_id"] or u["name"],
                            u["display_name"] or u["name"],
                            u["department"],
                            u["role"],
                            u["created"],
                            u["last_seen"] or "",
                            u["name"],
                        ]
                    )
                body = out.getvalue().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{quote('members.csv')}",
                )
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/admin/logs/export":
                if not _can_view_student_logs(user):
                    self._error(403, "需要教师或助教权限")
                    return
                target = q.get("user", [None])[0] or None
                action = q.get("action", [None])[0] or None
                events = audit.list_events(user=target, action=action, limit=10000, max_limit=10000)

                out = io.StringIO()
                writer = csv.writer(out)
                writer.writerow(["时间", "用户", "角色", "行为", "详情"])
                for event in events:
                    writer.writerow(
                        [
                            event["ts"],
                            event["user"],
                            event["role"],
                            event["action"],
                            json.dumps(event["detail"], ensure_ascii=False, sort_keys=True),
                        ]
                    )
                body = out.getvalue().encode("utf-8-sig")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header(
                    "Content-Disposition",
                    f"attachment; filename*=UTF-8''{quote('behavior-logs.csv')}",
                )
                self.end_headers()
                self.wfile.write(body)
            elif url.path == "/api/admin/courses":
                if not _can_manage_courses(user):
                    self._error(403, "需要教师或助教权限")
                    return
                self._json({"courses": courses.list_courses(), "resources": courses.known_resources()})
            elif url.path == "/api/admin/logs":
                if not _can_view_student_logs(user):
                    self._error(403, "需要教师或助教权限")
                    return
                target = q.get("user", [None])[0] or None
                action = q.get("action", [None])[0] or None
                limit = int(q.get("limit", ["200"])[0])
                offset = int(q.get("offset", ["0"])[0])
                events = audit.list_events(user=target, action=action, limit=limit, offset=offset)
                total = audit.count_events(user=target, action=action)
                self._json(
                    {
                        "events": events,
                        "total": total,
                        "limit": max(1, min(limit, 500)),
                        "offset": max(0, offset),
                    }
                )
            else:
                self._error(404, "unknown endpoint")
        except Exception as exc:  # noqa: BLE001
            self._error(500, str(exc))

    def do_POST(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        user = self._require_auth()
        if user is None:
            return
        try:
            if url.path == "/api/chat":
                data = self._body()
                message = str(data.get("message", "")).strip()
                if not message:
                    self._error(400, "message 不能为空")
                    return
                wait = CHAT_LIMITER.hit(user)
                if wait > 0:
                    self._rate_limited(wait, "对话")
                    return
                session_id, sess = _get_session(user, data.get("session_id"))
                events: list[str] = []
                with sess["lock"]:
                    agent = sess["agent"]
                    agent.on_event = events.append
                    try:
                        answer = agent.ask(message)
                    except Exception as exc:  # noqa: BLE001 - surface LLM errors as JSON
                        self._json({"error": str(exc), "session_id": session_id}, 502)
                        return
                    sessions.save(user, session_id, agent.messages)
                _log_action(
                    user,
                    "chat",
                    {"session_id": session_id, "message": message[:500], "answer_chars": len(answer)},
                )
                self._json({"answer": answer, "events": events, "session_id": session_id})
            elif url.path == "/api/chat/stream":
                data = self._body()
                message = str(data.get("message", "")).strip()
                if not message:
                    self._error(400, "message 不能为空")
                    return
                wait = CHAT_LIMITER.hit(user)
                if wait > 0:
                    self._rate_limited(wait, "对话")
                    return
                session_id, sess = _get_session(user, data.get("session_id"))
                self._sse_start()
                self._sse({"type": "session", "session_id": session_id})
                with sess["lock"]:
                    agent = sess["agent"]
                    saved = False
                    try:
                        for event in agent.stream(message):
                            if isinstance(event, dict) and event.get("type") == "done":
                                sessions.save(user, session_id, agent.messages)
                                saved = True
                            self._sse(event)
                    except Exception as exc:  # noqa: BLE001 - stream errors as events
                        self._sse({"type": "error", "error": str(exc)})
                    else:
                        # 出错的轮次不落盘：消息尾部可能残留未完成的 tool_calls
                        if not saved:
                            sessions.save(user, session_id, agent.messages)
                        _log_action(
                            user,
                            "chat",
                            {
                                "session_id": session_id,
                                "message": message[:500],
                                "stream": True,
                            },
                        )
            elif url.path == "/api/mistakes":
                data = self._body()
                m = journal.add_mistake(
                    problem=str(data.get("problem", "")),
                    course=str(data.get("course", "") or ""),
                    tags=str(data.get("tags", "") or ""),
                    reason=str(data.get("reason", "") or ""),
                    note=str(data.get("note", "") or ""),
                    link=str(data.get("link", "") or ""),
                    section_id=data.get("section_id"),
                    db_path=journal.user_db(user),
                )
                _log_action(
                    user,
                    "mistake_add",
                    {"id": m.id, "problem": m.problem, "course": m.course, "tags": m.tags},
                )
                self._json({"mistake": m.to_dict()}, 201)
            elif m := re.fullmatch(r"/api/mistakes/(\d+)/review", url.path):
                data = self._body()
                updated = journal.review_mistake(
                    int(m.group(1)), str(data.get("result", "good")), db_path=journal.user_db(user)
                )
                _log_action(
                    user,
                    "mistake_review",
                    {"id": updated.id, "result": str(data.get("result", "good"))},
                )
                self._json({"mistake": updated.to_dict()})
            elif url.path == "/api/admin/users":
                if not _can_manage_users(user):
                    self._error(403, "需要教师权限")
                    return
                data = self._body()
                name = str(data.get("name", "")).strip()
                role = str(data.get("role", "student")).strip() or "student"
                key = data.get("key")
                key = str(key).strip() if key else None
                student_id = str(data.get("student_id", "") or "").strip()
                display_name = str(data.get("display_name", "") or "").strip()
                department = str(data.get("department", "") or "").strip()
                new_key = users.add_user(
                    name,
                    key=key,
                    role=role,
                    student_id=student_id,
                    display_name=display_name,
                    department=department,
                )
                _log_action(
                    user,
                    "admin_user_add",
                    {"name": name, "role": role, "student_id": student_id},
                )
                self._json({"user": users.get_user(name), "key": new_key}, 201)
            elif url.path == "/api/admin/users/import":
                if not _can_manage_users(user):
                    self._error(403, "需要教师权限")
                    return
                data = self._body()
                imported = users.import_students(str(data.get("text", "")))
                _log_action(
                    user,
                    "admin_users_import",
                    {"count": len(imported), "student_ids": [r["student_id"] for r in imported]},
                )
                self._json({"imported": imported}, 201)
            elif m := re.fullmatch(r"/api/admin/users/([A-Za-z0-9_-]{1,32})", url.path):
                self._error(405, "use PATCH")
            elif m := re.fullmatch(r"/api/admin/users/([A-Za-z0-9_-]{1,32})/reset", url.path):
                if not _can_manage_users(user):
                    self._error(403, "需要教师权限")
                    return
                key = users.reset_key(m.group(1))
                _log_action(user, "admin_user_reset", {"name": m.group(1)})
                self._json({"user": users.get_user(m.group(1)), "key": key})
            elif m := re.fullmatch(r"/api/admin/courses/([A-Za-z0-9_-]{1,32})", url.path):
                if not _can_manage_courses(user):
                    self._error(403, "需要教师或助教权限")
                    return
                data = self._body()
                resources = data.get("resources", [])
                if not isinstance(resources, list):
                    raise ValueError("resources must be a list")
                course = courses.set_course_resources(m.group(1), resources, user)
                _log_action(
                    user,
                    "admin_course_update",
                    {"course": course["course"], "resources": course["resources"]},
                )
                self._json({"course": course})
            else:
                self._error(404, "unknown endpoint")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(500, str(exc))

    def do_DELETE(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        user = self._require_auth()
        if user is None:
            return
        if m := re.fullmatch(r"/api/mistakes/(\d+)", url.path):
            deleted = journal.delete_mistake(int(m.group(1)), db_path=journal.user_db(user))
            if deleted:
                _log_action(user, "mistake_delete", {"id": int(m.group(1))})
            self._json({"deleted": deleted}) if deleted else self._error(404, "not found")
        elif m := re.fullmatch(r"/api/sessions/([A-Za-z0-9-]{1,64})", url.path):
            deleted = sessions.delete(user, m.group(1))
            with _sessions_lock:
                _sessions.pop((user, m.group(1)), None)
            if deleted:
                _log_action(user, "session_delete", {"session_id": m.group(1)})
            self._json({"deleted": deleted}) if deleted else self._error(404, "not found")
        elif m := re.fullmatch(r"/api/admin/users/([A-Za-z0-9_-]{1,32})", url.path):
            if not _can_manage_users(user):
                self._error(403, "需要教师权限")
                return
            deleted = users.remove_user(m.group(1))
            if deleted:
                _log_action(user, "admin_user_delete", {"name": m.group(1)})
            self._json({"deleted": deleted}) if deleted else self._error(404, "not found")
        else:
            self._error(404, "unknown endpoint")

    def do_PATCH(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        user = self._require_auth()
        if user is None:
            return
        try:
            if m := re.fullmatch(r"/api/admin/users/([A-Za-z0-9_-]{1,32})", url.path):
                if not _can_manage_users(user):
                    self._error(403, "需要教师权限")
                    return
                data = self._body()
                role = str(data.get("role", "")).strip()
                users.set_role(m.group(1), role)
                _log_action(user, "admin_user_role", {"name": m.group(1), "role": role})
                self._json({"user": users.get_user(m.group(1))})
            else:
                self._error(404, "unknown endpoint")
        except ValueError as exc:
            self._error(400, str(exc))
        except Exception as exc:  # noqa: BLE001
            self._error(500, str(exc))


def serve(
    host: str = "127.0.0.1",
    port: int = 8101,
    tls_cert: str | None = None,
    tls_key: str | None = None,
) -> None:
    global AUTH_KEYS, API_LIMITER, CHAT_LIMITER, AUTH_FAIL_LIMITER
    AUTH_KEYS = load_auth_keys()  # 同时加载 .env，之后再读限流环境变量
    API_LIMITER = ratelimit.from_env("VIBE_CS101_RATE_API", "120/60")
    CHAT_LIMITER = ratelimit.from_env("VIBE_CS101_RATE_CHAT", "10/60")
    AUTH_FAIL_LIMITER = ratelimit.from_env("VIBE_CS101_RATE_AUTHFAIL", "10/300")

    if not _is_loopback(host) and not _auth_enabled():
        raise SystemExit(
            f"拒绝在 {host} 上无鉴权启动。远程访问必须设置 VIBE_CS101_AUTH_KEY=<key>"
            "（或多用户 VIBE_CS101_AUTH_KEYS=name:key,name:key，"
            "或用 `vibe-cs101 user add <name>` 创建用户），"
            "否则请使用默认的 127.0.0.1 仅本机访问。"
        )
    if not _is_loopback(host) and not tls_cert:
        print("⚠️  远程访问未启用 HTTPS：建议加 --tls-cert/--tls-key，或置于反向代理（Caddy/Nginx）之后。")

    httpd = ThreadingHTTPServer((host, port), Handler)
    scheme = "http"
    if tls_cert:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=tls_cert, keyfile=tls_key or None)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    n_users = len(AUTH_KEYS) + len(users.list_users())
    who = f"{n_users} 个用户（鉴权已启用）" if _auth_enabled() else "仅本机、未启用鉴权"
    print(f"Vibe-cs101 Web UI: {scheme}://{host}:{port}  [{who}]  (Ctrl-C 退出)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
