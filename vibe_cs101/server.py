"""Web UI 后端：标准库 ThreadingHTTPServer 上的 REST API + 静态页面.

架构参照 Vibe-Trading（后端 API + 单页前端），但保持零依赖：
不用 FastAPI/uvicorn，路由风格保持一致，前端是无构建的单页应用（web/）。
默认只监听 127.0.0.1，仅供本机使用。

API:
    GET  /api/info                     配置与索引状态
    GET  /api/search?q=&course=&limit= 全文检索
    GET  /api/section/{id}             读取章节全文
    POST /api/chat                     {message, session_id?} → {answer, events, session_id}
    GET  /api/mistakes?view=all|due    错题列表
    POST /api/mistakes                 记错题 {problem, course?, tags?, reason?, note?, section_id?}
    POST /api/mistakes/{id}/review     {result: good|again}
    DELETE /api/mistakes/{id}          删除
    GET  /api/mistakes/stats           进度统计
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import re
import ssl
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import journal, store
from .config import DB_PATH, load_auth_keys, load_llm_config

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 1 << 20  # 1MB
MAX_SESSIONS = 50

AUTH_KEYS: dict[str, str] = {}  # {username: key}; 空 = 未启用鉴权（仅本机模式）

_sessions: dict[tuple[str, str], dict] = {}  # (user, session_id) -> {"agent", "lock"}
_sessions_lock = threading.Lock()


def _get_session(user: str, session_id: str | None) -> tuple[str, dict]:
    with _sessions_lock:
        if session_id and (user, session_id) in _sessions:
            return session_id, _sessions[(user, session_id)]
        from .agent import Agent

        new_id = session_id or uuid.uuid4().hex[:12]
        if len(_sessions) >= MAX_SESSIONS:
            _sessions.pop(next(iter(_sessions)))
        _sessions[(user, new_id)] = {
            "agent": Agent(tool_context={"journal_db": journal.user_db(user)}),
            "lock": threading.Lock(),
        }
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

    # ---- auth ----------------------------------------------------------
    def _authenticate(self) -> str | None:
        """Return the username, or None if auth is required and failed."""
        if not AUTH_KEYS:
            return "owner"  # 未启用鉴权：仅本机模式（serve() 保证非本机必须配 key）
        header = self.headers.get("Authorization", "")
        presented = header[7:].strip() if header.lower().startswith("bearer ") else ""
        presented = presented or self.headers.get("X-API-Key", "").strip()
        if presented:
            for user, key in AUTH_KEYS.items():
                if hmac.compare_digest(presented, key):
                    return user
        return None

    def _require_auth(self) -> str | None:
        user = self._authenticate()
        if user is None:
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Bearer realm="vibe-cs101"')
            body = json.dumps({"error": "需要 API key（Authorization: Bearer <key>）"}).encode()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
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

    # ---- routes --------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        q = parse_qs(url.query)
        if not url.path.startswith("/api/"):
            self._serve_static(url.path)
            return
        user = self._require_auth()
        if user is None:
            return
        try:
            if url.path == "/api/me":
                self._json({"user": user, "auth_enabled": bool(AUTH_KEYS)})
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
                hits = store.search(
                    q.get("q", [""])[0],
                    limit=min(int(q.get("limit", ["10"])[0]), 50),
                    course=q.get("course", [None])[0] or None,
                    source=q.get("source", [None])[0] or None,
                )
                self._json({"results": [h.__dict__ for h in hits]})
            elif m := re.fullmatch(r"/api/section/(\d+)", url.path):
                section = store.get_section(int(m.group(1)))
                self._json(section) if section else self._error(404, "section not found")
            elif url.path == "/api/mistakes/stats":
                self._json(journal.stats(db_path=journal.user_db(user)))
            elif url.path == "/api/mistakes":
                view = q.get("view", ["all"])[0]
                mistakes = journal.list_mistakes(
                    due_only=(view == "due"),
                    course=q.get("course", [None])[0] or None,
                    tag=q.get("tag", [None])[0] or None,
                    db_path=journal.user_db(user),
                )
                self._json({"mistakes": [m.to_dict() for m in mistakes]})
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
                self._json({"answer": answer, "events": events, "session_id": session_id})
            elif url.path == "/api/mistakes":
                data = self._body()
                m = journal.add_mistake(
                    problem=str(data.get("problem", "")),
                    course=str(data.get("course", "") or ""),
                    tags=str(data.get("tags", "") or ""),
                    reason=str(data.get("reason", "") or ""),
                    note=str(data.get("note", "") or ""),
                    section_id=data.get("section_id"),
                    db_path=journal.user_db(user),
                )
                self._json({"mistake": m.to_dict()}, 201)
            elif m := re.fullmatch(r"/api/mistakes/(\d+)/review", url.path):
                data = self._body()
                updated = journal.review_mistake(
                    int(m.group(1)), str(data.get("result", "good")), db_path=journal.user_db(user)
                )
                self._json({"mistake": updated.to_dict()})
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
            self._json({"deleted": deleted}) if deleted else self._error(404, "not found")
        else:
            self._error(404, "unknown endpoint")


def serve(
    host: str = "127.0.0.1",
    port: int = 8101,
    tls_cert: str | None = None,
    tls_key: str | None = None,
) -> None:
    global AUTH_KEYS
    AUTH_KEYS = load_auth_keys()

    if not _is_loopback(host) and not AUTH_KEYS:
        raise SystemExit(
            f"拒绝在 {host} 上无鉴权启动。远程访问必须设置 VIBE_CS101_AUTH_KEY=<key>"
            "（或多用户 VIBE_CS101_AUTH_KEYS=name:key,name:key），"
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

    who = f"{len(AUTH_KEYS)} 个用户（鉴权已启用）" if AUTH_KEYS else "仅本机、未启用鉴权"
    print(f"Vibe-cs101 Web UI: {scheme}://{host}:{port}  [{who}]  (Ctrl-C 退出)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
    finally:
        httpd.server_close()
