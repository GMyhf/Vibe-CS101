"""Query layer over the FTS5 index, shared by the CLI and agent tools."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import DB_PATH
from .indexer import build_any_match_query, build_match_query, connect

_UNSPACE_CJK = re.compile(r"(?<=[㐀-䶿一-鿿豈-﫿\[\]…]) +(?=[㐀-䶿一-鿿豈-﫿\[\]…])")
MAX_SEARCH_RESULTS = 50


@dataclass(frozen=True)
class Hit:
    section_id: int
    source: str
    course: str
    kind: str
    file: str
    title: str
    snippet: str


def _clean_snippet(text: str) -> str:
    """Undo CJK spacing in snippets taken from the preprocessed FTS column."""
    return _UNSPACE_CJK.sub("", text).replace("\n", " ").strip()


def search(
    query: str,
    limit: int = 8,
    course: str | None = None,
    source: str | None = None,
    sources: list[str] | tuple[str, ...] | set[str] | None = None,
    db_path: Path = DB_PATH,
) -> list[Hit]:
    limit = int(limit)
    if limit <= 0:
        return []
    limit = min(limit, MAX_SEARCH_RESULTS)
    match = build_match_query(query)
    if not match:
        return []
    fallback_match = build_any_match_query(query)
    conn = connect(db_path)
    sql = """
        SELECT s.id, s.source, s.course, s.kind, s.file, s.title,
               snippet(sections_fts, 1, '', '', ' … ', 32)
        FROM sections_fts
        JOIN sections s ON s.id = sections_fts.rowid
        WHERE sections_fts MATCH ?
    """
    args: list[object] = [match]
    if course:
        sql += " AND s.course = ?"
        args.append(course)
    if source:
        sql += " AND s.source = ?"
        args.append(source)
    elif sources is not None:
        clean_sources = [str(s).strip() for s in sources if str(s).strip()]
        if not clean_sources:
            conn.close()
            return []
        placeholders = ",".join("?" for _ in clean_sources)
        sql += f" AND s.source IN ({placeholders})"
        args.extend(clean_sources)
    sql += " ORDER BY bm25(sections_fts, 3.0, 1.0) LIMIT ?"
    args.append(limit)
    try:
        rows = conn.execute(sql, args).fetchall()
        if not rows and fallback_match and fallback_match != match:
            fallback_args = [fallback_match, *args[1:]]
            rows = conn.execute(sql, fallback_args).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return [Hit(r[0], r[1], r[2], r[3], r[4], r[5], _clean_snippet(r[6])) for r in rows]


def get_section(section_id: int, db_path: Path = DB_PATH) -> dict | None:
    conn = connect(db_path)
    row = conn.execute(
        "SELECT id, source, course, kind, file, title, content FROM sections WHERE id = ?",
        (section_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {
        "section_id": row[0],
        "source": row[1],
        "course": row[2],
        "kind": row[3],
        "file": row[4],
        "title": row[5],
        "content": row[6],
    }


def get_document_for_section(section_id: int, db_path: Path = DB_PATH) -> dict | None:
    """Return all indexed sections from the same source/course/file as one document."""
    section = get_section(section_id, db_path)
    if not section:
        return None
    conn = connect(db_path)
    rows = conn.execute(
        """
        SELECT id, title, content
        FROM sections
        WHERE source = ? AND course = ? AND file = ?
        ORDER BY id
        """,
        (section["source"], section["course"], section["file"]),
    ).fetchall()
    conn.close()
    sections = [{"id": row[0], "title": row[1], "content": row[2]} for row in rows]
    content = "\n\n".join(section["content"] for section in sections if section["content"])
    return {
        "section_id": section["section_id"],
        "source": section["source"],
        "course": section["course"],
        "kind": section["kind"],
        "file": section["file"],
        "title": section["file"],
        "matched_title": section["title"],
        "matched_section_id": section["section_id"],
        "section_count": len(rows),
        "sections": sections,
        "content": content,
    }


def stats(db_path: Path = DB_PATH) -> list[tuple[str, str, int]]:
    """(source, course, section-count) rows, or [] if the index is empty."""
    conn = connect(db_path)
    rows = conn.execute(
        "SELECT source, course, COUNT(*) FROM sections GROUP BY source, course ORDER BY source"
    ).fetchall()
    conn.close()
    return rows
