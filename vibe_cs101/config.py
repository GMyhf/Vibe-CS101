"""Source registry and runtime configuration for Vibe-cs101."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# Workspace root = parent of the vibe-cs101 project directory.
PROJECT_DIR = Path(__file__).resolve().parent.parent
WORKSPACE_DIR = PROJECT_DIR.parent
DATA_DIR = Path(os.environ.get("VIBE_CS101_DATA_DIR", PROJECT_DIR / "data"))
ORIGINAL_DIR = DATA_DIR / "original"
ETAG_DIR = DATA_DIR / "etag"
DB_PATH = DATA_DIR / "index.db"


@dataclass(frozen=True)
class RemoteSource:
    """A long-Markdown solutions file hosted on GitHub."""

    name: str
    url: str
    title: str
    course: str  # "cs101" or "cs201"
    kind: str = "solutions"


@dataclass(frozen=True)
class LocalSource:
    """A local directory of course materials (cloned upstream repo)."""

    name: str
    path: Path
    title: str
    course: str
    kind: str = "courseware"


# 题解来源（task.md 列出的 6 个上游长 Markdown 文件）
REMOTE_SOURCES: list[RemoteSource] = [
    RemoteSource(
        name="leetcode",
        url="https://raw.githubusercontent.com/GMyhf/2024fall-cs101/main/2024fall_LeetCode_problems.md",
        title="力扣简单和中等题目题解",
        course="cs101",
    ),
    RemoteSource(
        name="leetcode-tough",
        url="https://raw.githubusercontent.com/GMyhf/2024fall-cs101/main/2024fall_LeetCode_tough_problems.md",
        title="力扣挑战题目题解",
        course="cs101",
    ),
    RemoteSource(
        name="cs201-dsa",
        url="https://raw.githubusercontent.com/GMyhf/2024spring-cs201/main/2024spring_dsa_problems.md",
        title="cs201 数算题解",
        course="cs201",
    ),
    RemoteSource(
        name="openjudge",
        url="https://raw.githubusercontent.com/GMyhf/2020fall-cs101/main/2020fall_cs101.openjudge.cn_problems.md",
        title="cs101.openjudge.cn 题解",
        course="cs101",
    ),
    RemoteSource(
        name="codeforces",
        url="https://raw.githubusercontent.com/GMyhf/2020fall-cs101/main/2020fall_Codeforces_problems.md",
        title="Codeforces 题解",
        course="cs101",
    ),
    RemoteSource(
        name="sunnywhy",
        url="https://raw.githubusercontent.com/GMyhf/2024spring-cs201/main/sunnywhy_problems.md",
        title="晴问算法笔记题解",
        course="cs201",
    ),
]

# 课程课件（本地克隆的上游仓库）
LOCAL_SOURCES: list[LocalSource] = [
    LocalSource(
        name="2025fall-cs101",
        path=WORKSPACE_DIR / "2025fall-cs101",
        title="2025 秋季 cs101 计算概论B 课件",
        course="cs101",
    ),
    LocalSource(
        name="2026spring-cs201",
        path=WORKSPACE_DIR / "2026spring-cs201",
        title="2026 春季 cs201 数据结构与算法B 课件",
        course="cs201",
    ),
]


def _load_dotenv() -> None:
    """Load KEY=VALUE lines from vibe-cs101/.env without overriding real env."""
    env_file = PROJECT_DIR / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key)


def load_llm_config() -> LLMConfig:
    """Resolve LLM settings from env / .env.

    Any OpenAI-compatible endpoint works (DeepSeek, OpenAI, Moonshot, ...).
    Explicit VIBE_CS101_* vars win; otherwise well-known provider keys are
    picked up with their default endpoints.
    """
    _load_dotenv()
    base_url = os.environ.get("VIBE_CS101_BASE_URL", "")
    api_key = os.environ.get("VIBE_CS101_API_KEY", "")
    model = os.environ.get("VIBE_CS101_MODEL", "")

    if not api_key:
        if os.environ.get("DEEPSEEK_API_KEY"):
            api_key = os.environ["DEEPSEEK_API_KEY"]
            base_url = base_url or "https://api.deepseek.com/v1"
            model = model or "deepseek-chat"
        elif os.environ.get("OPENAI_API_KEY"):
            api_key = os.environ["OPENAI_API_KEY"]
            base_url = base_url or "https://api.openai.com/v1"
            model = model or "gpt-4o-mini"

    return LLMConfig(
        base_url=base_url or "https://api.deepseek.com/v1",
        api_key=api_key,
        model=model or "deepseek-chat",
    )
