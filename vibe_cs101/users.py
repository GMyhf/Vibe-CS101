"""Web UI 持久化用户管理：key 加盐哈希后存 SQLite，CLI 增删查.

与环境变量方式并存、互补：
- VIBE_CS101_AUTH_KEY(S)：明文写在 .env，适合临时/单人场景（匹配优先）。
- `vibe-cs101 user add <name>`：key 只在创建时显示一次，库里只存
  sha256(salt+key)，适合长期多用户。增删即时生效，无需重启 serve。

存储在 data/users.db，独立于可随时重建的 index.db。
"""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR

USERS_DB = DATA_DIR / "users.db"
NAME_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    key_hash TEXT NOT NULL,       -- sha256(salt + key) 十六进制
    created TEXT NOT NULL,
    last_seen TEXT
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or USERS_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def _hash(salt: str, key: str) -> str:
    return hashlib.sha256((salt + key).encode("utf-8")).hexdigest()


def _check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"用户名只能含字母/数字/_/-（≤32 字符）: {name!r}")
    return name


def add_user(name: str, key: str | None = None, db_path: Path | None = None) -> str:
    """创建用户，返回明文 key（仅此一次机会获取）。已存在则报错。"""
    _check_name(name)
    key = key or secrets.token_urlsafe(24)
    salt = secrets.token_hex(16)
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(
                "INSERT INTO users (name, salt, key_hash, created) VALUES (?,?,?,?)",
                (name, salt, _hash(salt, key), datetime.now().isoformat(timespec="seconds")),
            )
    except sqlite3.IntegrityError:
        raise ValueError(f"用户 {name!r} 已存在（可用 `user reset {name}` 换 key）") from None
    finally:
        conn.close()
    return key


def reset_key(name: str, key: str | None = None, db_path: Path | None = None) -> str:
    """重新生成某用户的 key（旧 key 立即失效），返回新明文 key。"""
    key = key or secrets.token_urlsafe(24)
    salt = secrets.token_hex(16)
    conn = _connect(db_path)
    with conn:
        cur = conn.execute(
            "UPDATE users SET salt=?, key_hash=? WHERE name=?", (salt, _hash(salt, key), name)
        )
    conn.close()
    if cur.rowcount == 0:
        raise ValueError(f"用户 {name!r} 不存在")
    return key


def remove_user(name: str, db_path: Path | None = None) -> bool:
    conn = _connect(db_path)
    with conn:
        cur = conn.execute("DELETE FROM users WHERE name=?", (name,))
    conn.close()
    return cur.rowcount > 0


def list_users(db_path: Path | None = None) -> list[dict]:
    if not (db_path or USERS_DB).is_file():
        return []
    conn = _connect(db_path)
    rows = conn.execute("SELECT name, created, last_seen FROM users ORDER BY name").fetchall()
    conn.close()
    return [{"name": n, "created": c, "last_seen": s} for n, c, s in rows]


def has_users(db_path: Path | None = None) -> bool:
    if not (db_path or USERS_DB).is_file():
        return False
    conn = _connect(db_path)
    n = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return n > 0


def verify_key(presented: str, db_path: Path | None = None) -> str | None:
    """校验 key，命中返回用户名并刷新 last_seen；否则 None。"""
    if not presented or not (db_path or USERS_DB).is_file():
        return None
    conn = _connect(db_path)
    rows = conn.execute("SELECT name, salt, key_hash FROM users").fetchall()
    matched = None
    for name, salt, key_hash in rows:
        if hmac.compare_digest(_hash(salt, presented), key_hash):
            matched = name  # 不提前 break，保持近似恒定耗时
    if matched:
        with conn:
            conn.execute(
                "UPDATE users SET last_seen=? WHERE name=?",
                (datetime.now().isoformat(timespec="seconds"), matched),
            )
    conn.close()
    return matched
