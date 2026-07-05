#!/usr/bin/env python3
"""Prepare FuYnAloft/sol101 inputs from Vibe-CS101's local solution cache."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import shutil
import sys
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parent.parent
SOL101_DIR = ROOT / "data" / "sol101"
VIBE_ORIGINAL = ROOT / "data" / "original"
WORKSPACE_DIR = ROOT.parent
FETCH_TIMEOUT_S = float(os.environ.get("SOL101_FETCH_TIMEOUT_S", "45"))
FETCH_RETRIES = int(os.environ.get("SOL101_FETCH_RETRIES", "2"))
REFRESH_ALL = os.environ.get("SOL101_REFRESH_ALL", "0") == "1"

LOCAL_CACHE_SOURCES = {
    "oj-dsa": VIBE_ORIGINAL / "2024spring-cs201" / "2024spring_dsa_problems.md",
    "oj": VIBE_ORIGINAL / "2020fall-cs101" / "2020fall_cs101.openjudge.cn_problems.md",
    "cf": VIBE_ORIGINAL / "2020fall-cs101" / "2020fall_Codeforces_problems.md",
    "leetcode-em": VIBE_ORIGINAL / "2024fall-cs101" / "2024fall_LeetCode_problems.md",
    "leetcode-tough": VIBE_ORIGINAL / "2024fall-cs101" / "2024fall_LeetCode_tough_problems.md",
    "sunnywhy": VIBE_ORIGINAL / "2024spring-cs201" / "sunnywhy_problems.md",
    "cpp": VIBE_ORIGINAL / "2025fall-cs201" / "2025fall_problems_in_cpp.md",
}
LOCAL_REPO_FALLBACKS = {
    "cpp": WORKSPACE_DIR / "2025fall-cs201" / "2025fall_problems_in_cpp.md",
}


def _load_sol101_answers() -> list[object]:
    old_cwd = Path.cwd()
    sys.path.insert(0, str(SOL101_DIR))
    try:
        os.chdir(SOL101_DIR)
        config = importlib.import_module("config")
        return list(config.ANSWERS)
    finally:
        os.chdir(old_cwd)
        try:
            sys.path.remove(str(SOL101_DIR))
        except ValueError:
            pass


def _fetch_answer(answer: object, target_dir: Path) -> None:
    name = getattr(answer, "name")
    url = getattr(answer, "url")
    target = target_dir / f"{name}.md"
    etag_dir = SOL101_DIR / "etag"
    etag_dir.mkdir(parents=True, exist_ok=True)
    etag_path = etag_dir / f"{name}.etag"

    headers = {"User-Agent": "Vibe-CS101 sol101 updater"}
    if target.is_file() and etag_path.is_file():
        etag = etag_path.read_text(encoding="utf-8").strip()
        if etag:
            headers["If-None-Match"] = etag

    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=FETCH_TIMEOUT_S) as response:
        status = getattr(response, "status", response.getcode())
        if status != 200:
            raise RuntimeError(f"unexpected HTTP status {status}")
        tmp = target.with_suffix(target.suffix + ".tmp")
        with open(tmp, "wb") as out:
            while chunk := response.read(1 << 20):
                out.write(chunk)
        tmp.replace(target)
        new_etag = response.headers.get("ETag")
        if new_etag:
            etag_path.write_text(new_etag, encoding="utf-8")
    print(f"{name}: fetched {url} -> {target.relative_to(ROOT)}")


def _update_answer(answer: object, target_dir: Path) -> bool:
    name = getattr(answer, "name")
    target = target_dir / f"{name}.md"
    for attempt in range(1, FETCH_RETRIES + 2):
        try:
            _fetch_answer(answer, target_dir)
            return True
        except urllib.error.HTTPError as exc:
            if exc.code == 304:
                print(f"{name}: not modified")
                return True
            error: Exception = exc
        except Exception as exc:  # noqa: BLE001 - continue with local cache when possible
            error = exc

        if attempt <= FETCH_RETRIES:
            print(f"WARN: {name} fetch attempt {attempt} failed: {error}; retrying")
            time.sleep(min(attempt * 2, 5))
            continue
        if target.is_file():
            print(f"WARN: {name} fetch failed: {error}; keeping existing {target.relative_to(ROOT)}")
            return True
        print(f"ERROR: {name} fetch failed and no local file exists: {error}")
        return False


def main() -> int:
    if not SOL101_DIR.is_dir():
        raise SystemExit(f"sol101 repository not found: {SOL101_DIR}")

    target_dir = SOL101_DIR / "original"
    target_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name, src in LOCAL_CACHE_SOURCES.items():
        if not src.is_file():
            fallback = LOCAL_REPO_FALLBACKS.get(name)
            if fallback and fallback.is_file():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(fallback, src)
                print(f"{name}: restored local cache from {fallback} -> {src.relative_to(ROOT)}")
            else:
                print(f"{name}: local cache missing, sol101 updater will fetch it")
                continue
        dst = target_dir / f"{name}.md"
        shutil.copyfile(src, dst)
        copied += 1
        try:
            src_label = src.relative_to(ROOT)
        except ValueError:
            src_label = src
        print(f"{name}: {src_label} -> {dst.relative_to(ROOT)}")
    print(f"copied {copied} local source(s)")

    answers = _load_sol101_answers()
    print(f"updating {len(answers)} sol101-supported answer source(s)")
    ok = True
    for answer in answers:
        name = getattr(answer, "name")
        target = target_dir / f"{name}.md"
        if target.is_file() and not REFRESH_ALL:
            print(f"{name}: using existing {target.relative_to(ROOT)}")
            continue
        ok = _update_answer(answer, target_dir) and ok
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
