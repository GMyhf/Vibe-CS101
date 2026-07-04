"""错题本 + 学习进度跟踪（参照 Vibe-Trading Shadow Account 思路）.

Shadow Account 从交易日志里找出"你在哪里丢钱"；错题本从做题记录里找出
"你在哪里丢分"：记录错题（题目、原因、标签），按间隔复习（1/3/7/14/30 天），
统计各知识点的薄弱程度。存储在 data/journal.db，独立于可随时重建的 index.db。
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from .config import DATA_DIR

JOURNAL_DB = DATA_DIR / "journal.db"

# 复习间隔（天）：每次“记住了”前进一档，全部通过后 status → mastered
INTERVALS = [1, 3, 7, 14, 30]

SCHEMA = """
CREATE TABLE IF NOT EXISTS mistakes (
    id INTEGER PRIMARY KEY,
    created TEXT NOT NULL,
    problem TEXT NOT NULL,          -- 题目名/编号，如 "OpenJudge 26977 接雨水"
    course TEXT NOT NULL DEFAULT '',
    tags TEXT NOT NULL DEFAULT '',  -- 逗号分隔：dp,单调栈
    reason TEXT NOT NULL DEFAULT '',-- 错误原因
    note TEXT NOT NULL DEFAULT '',  -- 笔记/正确思路
    section_id INTEGER,             -- 关联的题解章节（可选）
    status TEXT NOT NULL DEFAULT 'active',  -- active | mastered
    interval_idx INTEGER NOT NULL DEFAULT 0,
    next_review TEXT NOT NULL,
    review_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY,
    mistake_id INTEGER NOT NULL REFERENCES mistakes(id),
    reviewed_at TEXT NOT NULL,
    result TEXT NOT NULL            -- good | again
);
"""


@dataclass(frozen=True)
class Mistake:
    id: int
    created: str
    problem: str
    course: str
    tags: str
    reason: str
    note: str
    section_id: int | None
    status: str
    interval_idx: int
    next_review: str
    review_count: int

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or JOURNAL_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def _row_to_mistake(row: tuple) -> Mistake:
    return Mistake(*row)


_COLS = "id, created, problem, course, tags, reason, note, section_id, status, interval_idx, next_review, review_count"


def add_mistake(
    problem: str,
    course: str = "",
    tags: str = "",
    reason: str = "",
    note: str = "",
    section_id: int | None = None,
    db_path: Path | None = None,
) -> Mistake:
    db_path = db_path or JOURNAL_DB
    if not problem.strip():
        raise ValueError("problem 不能为空")
    now = datetime.now().isoformat(timespec="seconds")
    next_review = (date.today() + timedelta(days=INTERVALS[0])).isoformat()
    conn = _connect(db_path)
    with conn:
        cur = conn.execute(
            "INSERT INTO mistakes (created, problem, course, tags, reason, note, section_id, next_review)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (now, problem.strip(), course, tags, reason, note, section_id, next_review),
        )
        row = conn.execute(f"SELECT {_COLS} FROM mistakes WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return _row_to_mistake(row)


def list_mistakes(
    due_only: bool = False,
    course: str | None = None,
    tag: str | None = None,
    status: str | None = None,
    limit: int = 100,
    db_path: Path | None = None,
) -> list[Mistake]:
    db_path = db_path or JOURNAL_DB
    sql = f"SELECT {_COLS} FROM mistakes WHERE 1=1"
    args: list[object] = []
    if due_only:
        sql += " AND status='active' AND next_review <= ?"
        args.append(date.today().isoformat())
    if course:
        sql += " AND course = ?"
        args.append(course)
    if tag:
        sql += " AND (',' || tags || ',') LIKE ?"
        args.append(f"%,{tag},%")
    if status:
        sql += " AND status = ?"
        args.append(status)
    sql += " ORDER BY next_review ASC, id DESC LIMIT ?"
    args.append(limit)
    conn = _connect(db_path)
    rows = conn.execute(sql, args).fetchall()
    conn.close()
    return [_row_to_mistake(r) for r in rows]


def get_mistake(mistake_id: int, db_path: Path | None = None) -> Mistake | None:
    db_path = db_path or JOURNAL_DB
    conn = _connect(db_path)
    row = conn.execute(f"SELECT {_COLS} FROM mistakes WHERE id=?", (mistake_id,)).fetchone()
    conn.close()
    return _row_to_mistake(row) if row else None


def review_mistake(mistake_id: int, result: str, db_path: Path | None = None) -> Mistake:
    """记录一次复习。result: 'good'（记住了，间隔前进）或 'again'（忘了，重来）。"""
    db_path = db_path or JOURNAL_DB
    if result not in ("good", "again"):
        raise ValueError("result 必须是 'good' 或 'again'")
    m = get_mistake(mistake_id, db_path)
    if m is None:
        raise ValueError(f"错题 {mistake_id} 不存在")

    if result == "again":
        idx, status = 0, "active"
    elif m.interval_idx + 1 >= len(INTERVALS):
        idx, status = m.interval_idx, "mastered"
    else:
        idx, status = m.interval_idx + 1, "active"
    next_review = (date.today() + timedelta(days=INTERVALS[idx])).isoformat()

    conn = _connect(db_path)
    with conn:
        conn.execute(
            "UPDATE mistakes SET interval_idx=?, next_review=?, status=?, review_count=review_count+1 WHERE id=?",
            (idx, next_review, status, mistake_id),
        )
        conn.execute(
            "INSERT INTO reviews (mistake_id, reviewed_at, result) VALUES (?,?,?)",
            (mistake_id, datetime.now().isoformat(timespec="seconds"), result),
        )
    conn.close()
    updated = get_mistake(mistake_id, db_path)
    assert updated is not None
    return updated


def delete_mistake(mistake_id: int, db_path: Path | None = None) -> bool:
    db_path = db_path or JOURNAL_DB
    conn = _connect(db_path)
    with conn:
        conn.execute("DELETE FROM reviews WHERE mistake_id=?", (mistake_id,))
        cur = conn.execute("DELETE FROM mistakes WHERE id=?", (mistake_id,))
    conn.close()
    return cur.rowcount > 0


def stats(db_path: Path | None = None) -> dict:
    """学习进度总览：总量、待复习、已掌握、按标签/课程的薄弱点排行。"""
    db_path = db_path or JOURNAL_DB
    conn = _connect(db_path)
    today = date.today().isoformat()
    total = conn.execute("SELECT COUNT(*) FROM mistakes").fetchone()[0]
    mastered = conn.execute("SELECT COUNT(*) FROM mistakes WHERE status='mastered'").fetchone()[0]
    due = conn.execute(
        "SELECT COUNT(*) FROM mistakes WHERE status='active' AND next_review <= ?", (today,)
    ).fetchone()[0]
    reviews_total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    again_total = conn.execute("SELECT COUNT(*) FROM reviews WHERE result='again'").fetchone()[0]

    by_tag: dict[str, dict[str, int]] = {}
    for tags, status in conn.execute("SELECT tags, status FROM mistakes"):
        for tag in [t.strip() for t in tags.split(",") if t.strip()]:
            entry = by_tag.setdefault(tag, {"total": 0, "mastered": 0})
            entry["total"] += 1
            entry["mastered"] += status == "mastered"
    by_course: dict[str, dict[str, int]] = {}
    for course, status in conn.execute("SELECT course, status FROM mistakes WHERE course != ''"):
        entry = by_course.setdefault(course, {"total": 0, "mastered": 0})
        entry["total"] += 1
        entry["mastered"] += status == "mastered"
    conn.close()

    weak_tags = sorted(by_tag.items(), key=lambda kv: kv[1]["total"] - kv[1]["mastered"], reverse=True)
    return {
        "total": total,
        "active": total - mastered,
        "mastered": mastered,
        "due_today": due,
        "reviews_total": reviews_total,
        "again_rate": round(again_total / reviews_total, 2) if reviews_total else 0.0,
        "by_tag": {k: v for k, v in weak_tags},
        "by_course": by_course,
    }
