"""Web 对话会话持久化：Agent 消息历史存 SQLite，服务重启后可恢复继续.

存储在 data/sessions.db（独立于可随时重建的 index.db）。messages 列保存
Agent.messages 的完整 JSON（含 system/tool 消息），恢复会话时上下文不丢；
前端展示用 display_messages() 过滤出 user/assistant 可读消息。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

SESSIONS_DB = DATA_DIR / "sessions.db"
MAX_SAVED_PER_USER = 200  # 每用户最多保留的会话数，超出删最旧

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    user TEXT NOT NULL,
    id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    messages TEXT NOT NULL,
    PRIMARY KEY (user, id)
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or SESSIONS_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def save(user: str, session_id: str, messages: list[dict], db_path: Path | None = None) -> None:
    """保存/更新一个会话（每轮对话成功结束后调用）。"""
    title = next(
        (str(m.get("content", ""))[:60] for m in messages if m.get("role") == "user" and m.get("content")),
        "",
    )
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO sessions (user, id, title, created, updated, messages) VALUES (?,?,?,?,?,?)"
            " ON CONFLICT(user, id) DO UPDATE SET"
            " title=excluded.title, updated=excluded.updated, messages=excluded.messages",
            (user, session_id, title, now, now, json.dumps(messages, ensure_ascii=False)),
        )
        conn.execute(
            "DELETE FROM sessions WHERE user=? AND id NOT IN ("
            " SELECT id FROM sessions WHERE user=? ORDER BY updated DESC, rowid DESC LIMIT ?)",
            (user, user, MAX_SAVED_PER_USER),
        )
    conn.close()


def load(user: str, session_id: str, db_path: Path | None = None) -> list[dict] | None:
    if not (db_path or SESSIONS_DB).is_file():
        return None
    conn = _connect(db_path)
    row = conn.execute(
        "SELECT messages FROM sessions WHERE user=? AND id=?", (user, session_id)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    messages = json.loads(row[0])
    return messages if isinstance(messages, list) else None


def list_sessions(user: str, limit: int = 50, db_path: Path | None = None) -> list[dict]:
    if not (db_path or SESSIONS_DB).is_file():
        return []
    conn = _connect(db_path)
    rows = conn.execute(
        "SELECT id, title, created, updated FROM sessions WHERE user=?"
        " ORDER BY updated DESC, rowid DESC LIMIT ?",
        (user, limit),
    ).fetchall()
    conn.close()
    return [{"id": i, "title": t, "created": c, "updated": u} for i, t, c, u in rows]


def delete(user: str, session_id: str, db_path: Path | None = None) -> bool:
    if not (db_path or SESSIONS_DB).is_file():
        return False
    conn = _connect(db_path)
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE user=? AND id=?", (user, session_id))
    conn.close()
    return cur.rowcount > 0


def display_messages(messages: list[dict]) -> list[dict]:
    """过滤出前端可展示的消息：user 全部、assistant 仅保留有正文的（跳过纯工具调用）。"""
    shown = []
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "user" and content:
            shown.append({"role": "user", "content": content})
        elif role == "assistant" and content:
            shown.append({"role": "assistant", "content": content})
    return shown
