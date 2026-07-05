"""Append-only behavior audit log for course administrators."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

AUDIT_DB = DATA_DIR / "audit.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    user TEXT NOT NULL,
    role TEXT NOT NULL,
    action TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_user_ts ON audit_events(user, ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_action_ts ON audit_events(action, ts DESC);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or AUDIT_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def log(
    user: str,
    role: str,
    action: str,
    detail: dict | None = None,
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    with conn:
        conn.execute(
            "INSERT INTO audit_events (ts, user, role, action, detail_json) VALUES (?,?,?,?,?)",
            (
                datetime.now().isoformat(timespec="seconds"),
                user,
                role,
                action,
                json.dumps(detail or {}, ensure_ascii=False, sort_keys=True),
            ),
        )
    conn.close()


def list_events(
    user: str | None = None,
    action: str | None = None,
    limit: int = 200,
    db_path: Path | None = None,
) -> list[dict]:
    if not (db_path or AUDIT_DB).is_file():
        return []
    limit = max(1, min(int(limit), 500))
    sql = "SELECT id, ts, user, role, action, detail_json FROM audit_events WHERE 1=1"
    args: list[object] = []
    if user:
        sql += " AND user = ?"
        args.append(user)
    if action:
        sql += " AND action = ?"
        args.append(action)
    sql += " ORDER BY id DESC LIMIT ?"
    args.append(limit)
    conn = _connect(db_path)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [
        {
            "id": row[0],
            "ts": row[1],
            "user": row[2],
            "role": row[3],
            "action": row[4],
            "detail": json.loads(row[5] or "{}"),
        }
        for row in rows
    ]
