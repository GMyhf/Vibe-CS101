"""Download upstream solution files with ETag caching (stdlib only)."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass

from .config import ETAG_DIR, ORIGINAL_DIR, REMOTE_SOURCES, RemoteSource

USER_AGENT = "vibe-cs101/0.1 (+https://github.com/GMyhf)"
TIMEOUT_S = 30


@dataclass(frozen=True)
class FetchResult:
    name: str
    status: str  # "updated" | "unchanged" | "cached" | "error"
    detail: str = ""


def _mirror_url(raw_url: str) -> str | None:
    """raw.githubusercontent.com/<owner>/<repo>/<ref>/<path> → jsDelivr CDN."""
    prefix = "https://raw.githubusercontent.com/"
    if not raw_url.startswith(prefix):
        return None
    owner, repo, ref, *path = raw_url[len(prefix):].split("/")
    return f"https://cdn.jsdelivr.net/gh/{owner}/{repo}@{ref}/{'/'.join(path)}"


def _fetch(url: str, etag: str | None) -> tuple[int, bytes, str]:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return resp.status, resp.read(), resp.headers.get("ETag", "")
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, b"", etag or ""
        raise


def fetch_source(source: RemoteSource) -> FetchResult:
    """Fetch one source; keep the previously downloaded copy on failure."""
    ORIGINAL_DIR.mkdir(parents=True, exist_ok=True)
    ETAG_DIR.mkdir(parents=True, exist_ok=True)
    target = ORIGINAL_DIR / f"{source.name}.md"
    etag_file = ETAG_DIR / f"{source.name}.etag"
    old_etag = etag_file.read_text().strip() if etag_file.is_file() else None

    try:
        status, body, etag = _fetch(source.url, old_etag if target.is_file() else None)
    except Exception as exc:  # noqa: BLE001 - network errors of any shape
        # raw.githubusercontent.com is unreachable from some networks; try the
        # jsDelivr mirror (no conditional request — its ETags differ per host).
        mirror = _mirror_url(source.url)
        try:
            if mirror is None:
                raise exc
            status, body, etag = _fetch(mirror, None)
        except Exception:  # noqa: BLE001
            if target.is_file():
                return FetchResult(source.name, "cached", f"fetch failed, keeping local copy: {exc}")
            return FetchResult(source.name, "error", str(exc))

    if status == 304:
        return FetchResult(source.name, "unchanged")
    if status != 200:
        detail = f"HTTP {status}"
        if target.is_file():
            return FetchResult(source.name, "cached", f"{detail}, keeping local copy")
        return FetchResult(source.name, "error", detail)

    target.write_bytes(body)
    if etag:
        etag_file.write_text(etag)
    return FetchResult(source.name, "updated", f"{len(body):,} bytes")


INDEX_RELEASE_URL = "https://github.com/GMyhf/Vibe-CS101/releases/download/data-latest/index.db"


def download_prebuilt_index(url: str = INDEX_RELEASE_URL, on_progress=None) -> int:
    """下载每周自动构建的 index.db（含课件 + 全部题解），返回字节数。

    下载到临时文件、校验 SQLite 文件头后原子替换，避免中断留下坏索引。
    """
    from .config import DB_PATH

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".db.part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    done = 0
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp, open(tmp, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        while chunk := resp.read(1 << 20):
            out.write(chunk)
            done += len(chunk)
            if on_progress:
                on_progress(done, total)
    with open(tmp, "rb") as f:
        if f.read(16) != b"SQLite format 3\x00":
            tmp.unlink(missing_ok=True)
            raise ValueError("下载内容不是有效的 SQLite 索引文件")
    tmp.replace(DB_PATH)
    return done


def fetch_all(retries: int = 2) -> list[FetchResult]:
    """Fetch all sources in parallel, retrying transient failures."""
    from concurrent.futures import ThreadPoolExecutor

    results: dict[str, FetchResult] = {}
    pending = list(REMOTE_SOURCES)
    for _attempt in range(retries + 1):
        with ThreadPoolExecutor(max_workers=6) as pool:
            for res in pool.map(fetch_source, pending):
                results[res.name] = res
        pending = [s for s in REMOTE_SOURCES if results[s.name].status == "error"]
        if not pending:
            break
    return [results[s.name] for s in REMOTE_SOURCES]
