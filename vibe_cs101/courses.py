"""Course resource configuration for the Web UI."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import DATA_DIR, LOCAL_SOURCES, REMOTE_SOURCES

COURSES_DB = DATA_DIR / "courses.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS courses (
    course TEXT PRIMARY KEY,
    resources_json TEXT NOT NULL,
    updated_by TEXT NOT NULL,
    updated TEXT NOT NULL
);
"""


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    db_path = db_path or COURSES_DB
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def known_resources() -> list[dict]:
    out = []
    for src in LOCAL_SOURCES:
        out.append(
            {
                "name": src.name,
                "title": src.title,
                "course": src.course,
                "kind": "courseware",
            }
        )
    for src in REMOTE_SOURCES:
        out.append(
            {
                "name": src.name,
                "title": src.title,
                "course": src.course,
                "kind": "solutions",
            }
        )
    return out


def _default_map() -> dict[str, list[str]]:
    resources: dict[str, list[str]] = {}
    for res in known_resources():
        resources.setdefault(res["course"], []).append(res["name"])
    return resources


def list_courses(db_path: Path | None = None) -> list[dict]:
    defaults = _default_map()
    conn = _connect(db_path)
    rows = conn.execute("SELECT course, resources_json, updated_by, updated FROM courses").fetchall()
    conn.close()
    saved = {c: (json.loads(raw), by, updated) for c, raw, by, updated in rows}
    out = []
    for course in sorted(set(defaults) | set(saved)):
        resources, by, updated = saved.get(course, (defaults.get(course, []), "", ""))
        out.append({"course": course, "resources": resources, "updated_by": by, "updated": updated})
    return out


def get_course(course: str, db_path: Path | None = None) -> dict | None:
    for row in list_courses(db_path=db_path):
        if row["course"] == course:
            return row
    return None


def enabled_resources(course: str | None, db_path: Path | None = None) -> list[str] | None:
    """Return the enabled source names for a course, or None if course is unset/unknown."""
    if not course:
        return None
    row = get_course(course, db_path=db_path)
    if not row:
        return None
    return list(row["resources"])


def set_course_resources(
    course: str,
    resources: list[str],
    updated_by: str,
    db_path: Path | None = None,
) -> dict:
    known = {r["name"] for r in known_resources()}
    clean = []
    for name in resources:
        name = str(name).strip()
        if name and name not in clean:
            if name not in known:
                raise ValueError(f"未知资源: {name}")
            clean.append(name)
    updated = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path)
    with conn:
        conn.execute(
            """
            INSERT INTO courses (course, resources_json, updated_by, updated)
            VALUES (?,?,?,?)
            ON CONFLICT(course) DO UPDATE SET
                resources_json=excluded.resources_json,
                updated_by=excluded.updated_by,
                updated=excluded.updated
            """,
            (course, json.dumps(clean, ensure_ascii=False), updated_by, updated),
        )
    conn.close()
    return {"course": course, "resources": clean, "updated_by": updated_by, "updated": updated}
