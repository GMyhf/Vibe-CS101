"""Split materials into sections and build the SQLite FTS5 index.

FTS5's unicode61 tokenizer treats a run of CJK characters as a single token,
which breaks Chinese search. We index a preprocessed copy of the text with a
space inserted between CJK characters, and preprocess queries the same way
(each CJK run becomes a phrase query), so 中文检索 works without external
segmentation libraries.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import DB_PATH, LOCAL_SOURCES, REMOTE_SOURCES

MAX_SECTION_CHARS = 8000
_CJK = re.compile(r"([㐀-䶿一-鿿豈-﫿])")
_HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*\s*$")
_FTS_TOKEN = re.compile(r"[0-9A-Za-z_.+#-]+|[㐀-䶿一-鿿豈-﫿]+")

SKIP_DIRS = {".git", ".github", "node_modules", "img", "imgs", "image", "images", "assets", ".vitepress"}
INDEXED_SUFFIXES = {".md", ".py", ".cpp", ".c", ".h"}


_MULTISPACE = re.compile(r" {2,}")


def cjk_space(text: str) -> str:
    """Insert spaces around every CJK character so FTS5 sees them as tokens."""
    return _MULTISPACE.sub(" ", _CJK.sub(r" \1 ", text))


def build_match_query(query: str) -> str:
    """Turn a user query into a safe FTS5 MATCH expression.

    English words become quoted terms; each CJK run becomes a quoted phrase of
    space-separated characters. Terms are ANDed (FTS5 implicit AND).
    """
    parts = []
    for token in _FTS_TOKEN.findall(query):
        spaced = cjk_space(token).strip()
        spaced = spaced.replace('"', "")
        if spaced:
            parts.append(f'"{spaced}"')
    return " ".join(parts)


def build_any_match_query(query: str) -> str:
    """Build a safe OR query for broad fallback searches."""
    parts = []
    for token in _FTS_TOKEN.findall(query):
        spaced = cjk_space(token).strip()
        spaced = spaced.replace('"', "")
        if spaced:
            parts.append(f'"{spaced}"')
    return " OR ".join(parts)


@dataclass(frozen=True)
class Section:
    source: str
    course: str
    kind: str
    file: str
    title: str
    content: str


def split_markdown(text: str, doc_title: str) -> list[tuple[str, str]]:
    """Split a markdown document into (heading-path, body) sections.

    Fenced code blocks are respected (a `# comment` inside ``` is not a
    heading). Oversized sections are chunked with a part suffix.
    """
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    path: list[str] = []  # heading text per level, index = level-1
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        body = "\n".join(buf).strip()
        buf.clear()
        if not body:
            return
        title = " > ".join([doc_title] + [p for p in path if p]) or doc_title
        for i in range(0, len(body), MAX_SECTION_CHARS):
            chunk = body[i : i + MAX_SECTION_CHARS]
            suffix = f" (part {i // MAX_SECTION_CHARS + 1})" if i else ""
            sections.append((title + suffix, chunk))

    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            buf.append(line)
            continue
        m = None if in_fence else _HEADING.match(line)
        if m:
            flush()
            level = len(m.group(1))
            del path[level - 1 :]
            path.extend([""] * (level - 1 - len(path)))
            path.append(m.group(2).strip())
        else:
            buf.append(line)
    flush()
    return sections


def iter_sections() -> list[Section]:
    out: list[Section] = []

    for src in REMOTE_SOURCES:
        f = src.original_path
        if not f.is_file():
            f = src.legacy_original_path
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        rel = f"{src.github_repo}/{src.upstream_filename}" if f == src.original_path else f.name
        for title, body in split_markdown(text, src.title):
            out.append(Section(src.name, src.course, src.kind, rel, title, body))

    for src in LOCAL_SOURCES:
        if not src.path.is_dir():
            continue
        for f in sorted(src.path.rglob("*")):
            if not f.is_file() or f.suffix.lower() not in INDEXED_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in f.relative_to(src.path).parts):
                continue
            rel = str(f.relative_to(src.path))
            text = f.read_text(encoding="utf-8", errors="replace")
            if f.suffix.lower() == ".md":
                for title, body in split_markdown(text, f.stem):
                    out.append(Section(src.name, src.course, src.kind, rel, title, body))
            else:
                body = text[:MAX_SECTION_CHARS]
                out.append(Section(src.name, src.course, "code", rel, rel, body))

    return out


SCHEMA = """
CREATE TABLE IF NOT EXISTS sections (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    course TEXT NOT NULL,
    kind TEXT NOT NULL,
    file TEXT NOT NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS sections_fts USING fts5(
    title_t, content_t, tokenize = 'unicode61'
);
"""


def connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    return conn


def rebuild_index(db_path: Path = DB_PATH) -> dict[str, int]:
    """Drop and rebuild the whole index. Returns per-source section counts."""
    sections = iter_sections()
    conn = connect(db_path)
    with conn:
        conn.execute("DELETE FROM sections")
        conn.execute("DELETE FROM sections_fts")
        for s in sections:
            cur = conn.execute(
                "INSERT INTO sections (source, course, kind, file, title, content) VALUES (?,?,?,?,?,?)",
                (s.source, s.course, s.kind, s.file, s.title, s.content),
            )
            conn.execute(
                "INSERT INTO sections_fts (rowid, title_t, content_t) VALUES (?,?,?)",
                (cur.lastrowid, cjk_space(s.title), cjk_space(s.content)),
            )
    counts: dict[str, int] = {}
    for s in sections:
        counts[s.source] = counts.get(s.source, 0) + 1
    conn.close()
    return counts
