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
ROLES = {"teacher", "assistant", "student"}
DEFAULT_ROLE = "teacher"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    name TEXT PRIMARY KEY,
    salt TEXT NOT NULL,
    key_hash TEXT NOT NULL,       -- sha256(salt + key) 十六进制
    role TEXT NOT NULL DEFAULT 'teacher',
    student_id TEXT,
    display_name TEXT,
    department TEXT,
    created TEXT NOT NULL,
    last_seen TEXT
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or USERS_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "role" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN role TEXT NOT NULL DEFAULT 'teacher'")
    if "student_id" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN student_id TEXT")
    if "display_name" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN display_name TEXT")
    if "department" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN department TEXT")
    return conn


def _hash(salt: str, key: str) -> str:
    return hashlib.sha256((salt + key).encode("utf-8")).hexdigest()


def _check_name(name: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise ValueError(f"用户名只能含字母/数字/_/-（≤32 字符）: {name!r}")
    return name


def _check_role(role: str) -> str:
    if role not in ROLES:
        raise ValueError(f"角色只能是 teacher / assistant / student: {role!r}")
    return role


def add_user(
    name: str,
    key: str | None = None,
    role: str = DEFAULT_ROLE,
    student_id: str = "",
    display_name: str = "",
    department: str = "",
    db_path: Path | None = None,
) -> str:
    """创建用户，返回明文 key（仅此一次机会获取）。已存在则报错。"""
    _check_name(name)
    _check_role(role)
    key = key or secrets.token_urlsafe(24)
    salt = secrets.token_hex(16)
    conn = _connect(db_path)
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO users
                    (name, salt, key_hash, role, student_id, display_name, department, created)
                VALUES (?,?,?,?,?,?,?,?)
                """,
                (
                    name,
                    salt,
                    _hash(salt, key),
                    role,
                    student_id or None,
                    display_name or None,
                    department or None,
                    datetime.now().isoformat(timespec="seconds"),
                ),
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


def set_role(name: str, role: str, db_path: Path | None = None) -> None:
    _check_role(role)
    conn = _connect(db_path)
    with conn:
        cur = conn.execute("UPDATE users SET role=? WHERE name=?", (role, name))
    conn.close()
    if cur.rowcount == 0:
        raise ValueError(f"用户 {name!r} 不存在")


def update_profile(
    name: str,
    student_id: str = "",
    display_name: str = "",
    department: str = "",
    db_path: Path | None = None,
) -> None:
    conn = _connect(db_path)
    with conn:
        cur = conn.execute(
            "UPDATE users SET student_id=?, display_name=?, department=? WHERE name=?",
            (student_id or None, display_name or None, department or None, name),
        )
    conn.close()
    if cur.rowcount == 0:
        raise ValueError(f"用户 {name!r} 不存在")


def parse_student_rows(text: str) -> list[dict]:
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = [p for p in re.split(r"[\t,，;； ]+", line) if p]
        if len(parts) < 3:
            raise ValueError(f"每行至少需要 学号 姓名 院系: {line!r}")
        student_id, display_name = parts[0], parts[1]
        department = "".join(parts[2:]) if len(parts) > 3 else parts[2]
        if not re.fullmatch(r"\d{6,32}", student_id):
            raise ValueError(f"学号格式错误: {student_id!r}")
        rows.append(
            {
                "name": student_id,
                "student_id": student_id,
                "display_name": display_name,
                "department": department,
                "role": "student",
            }
        )
    if not rows:
        raise ValueError("没有可导入的学生")
    return rows


def import_students(
    text: str,
    db_path: Path | None = None,
) -> list[dict]:
    rows = parse_student_rows(text)
    conn = _connect(db_path)
    imported = []
    try:
        with conn:
            for row in rows:
                key = secrets.token_urlsafe(24)
                salt = secrets.token_hex(16)
                try:
                    conn.execute(
                        """
                        INSERT INTO users
                            (name, salt, key_hash, role, student_id, display_name, department, created)
                        VALUES (?,?,?,?,?,?,?,?)
                        """,
                        (
                            row["name"],
                            salt,
                            _hash(salt, key),
                            "student",
                            row["student_id"],
                            row["display_name"],
                            row["department"],
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )
                except sqlite3.IntegrityError:
                    raise ValueError(f"用户 {row['name']!r} 已存在") from None
                imported.append({**row, "key": key})
    finally:
        conn.close()
    return imported


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
    rows = conn.execute(
        """
        SELECT name, role, student_id, display_name, department, created, last_seen
        FROM users ORDER BY role, student_id, name
        """
    ).fetchall()
    conn.close()
    return [
        {
            "name": n,
            "role": r,
            "student_id": sid or "",
            "display_name": display or "",
            "department": dept or "",
            "created": c,
            "last_seen": s,
        }
        for n, r, sid, display, dept, c, s in rows
    ]


def get_user(name: str, db_path: Path | None = None) -> dict | None:
    if not (db_path or USERS_DB).is_file():
        return None
    conn = _connect(db_path)
    row = conn.execute(
        """
        SELECT name, role, student_id, display_name, department, created, last_seen
        FROM users WHERE name=?
        """,
        (name,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    n, role, student_id, display_name, department, created, last_seen = row
    return {
        "name": n,
        "role": role,
        "student_id": student_id or "",
        "display_name": display_name or "",
        "department": department or "",
        "created": created,
        "last_seen": last_seen,
    }


def role_of(name: str, db_path: Path | None = None) -> str:
    row = get_user(name, db_path=db_path)
    return row["role"] if row else DEFAULT_ROLE


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
