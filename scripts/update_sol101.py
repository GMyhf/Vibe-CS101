#!/usr/bin/env python3
"""Prepare FuYnAloft/sol101 inputs from Vibe-CS101's local solution cache."""

from __future__ import annotations

from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parent.parent
SOL101_DIR = ROOT / "data" / "sol101"
VIBE_ORIGINAL = ROOT / "data" / "original"

SOURCES = {
    "oj-dsa": VIBE_ORIGINAL / "2024spring-cs201" / "2024spring_dsa_problems.md",
    "oj": VIBE_ORIGINAL / "2020fall-cs101" / "2020fall_cs101.openjudge.cn_problems.md",
    "cf": VIBE_ORIGINAL / "2020fall-cs101" / "2020fall_Codeforces_problems.md",
}


def main() -> int:
    if not SOL101_DIR.is_dir():
        raise SystemExit(f"sol101 repository not found: {SOL101_DIR}")
    missing = [str(path) for path in SOURCES.values() if not path.is_file()]
    if missing:
        raise SystemExit("missing local solution source(s): " + ", ".join(missing))

    target_dir = SOL101_DIR / "original"
    target_dir.mkdir(parents=True, exist_ok=True)
    for name, src in SOURCES.items():
        dst = target_dir / f"{name}.md"
        shutil.copyfile(src, dst)
        print(f"{name}: {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
