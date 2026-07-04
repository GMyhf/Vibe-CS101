"""进程内限流：滑动窗口计数（stdlib only，线程安全）.

用于 Web UI 三处防护：
- 按用户限普通 API 频率（VIBE_CS101_RATE_API，默认 120/60 即每 60 秒 120 次）
- 按用户限 chat 频率（VIBE_CS101_RATE_CHAT，默认 10/60；LLM 调用最贵）
- 按 IP 限鉴权失败次数（VIBE_CS101_RATE_AUTHFAIL，默认 10/300，防暴力试 key）

格式 "N/秒数" 或 "N"（窗口默认 60 秒）；N 为 0 表示不限流。
"""

from __future__ import annotations

import os
import threading
import time
from collections import deque


class RateLimiter:
    """滑动窗口限流器：每个 key 在 window_s 秒内最多 limit 次；limit<=0 不限流。"""

    def __init__(self, limit: int, window_s: float = 60.0):
        self.limit = int(limit)
        self.window_s = float(window_s)
        self._events: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, q: deque[float], now: float) -> None:
        while q and now - q[0] >= self.window_s:
            q.popleft()

    def hit(self, key: str) -> float:
        """记一次调用。返回 0 表示放行；>0 表示拒绝，值为建议等待秒数。"""
        if self.limit <= 0:
            return 0.0
        now = time.monotonic()
        with self._lock:
            q = self._events.setdefault(key, deque())
            self._prune(q, now)
            if len(q) >= self.limit:
                return max(self.window_s - (now - q[0]), 0.001)
            q.append(now)
            return 0.0

    def retry_after(self, key: str) -> float:
        """非消耗性检查：>0 表示该 key 当前已被限流（不记入次数）。"""
        if self.limit <= 0:
            return 0.0
        now = time.monotonic()
        with self._lock:
            q = self._events.get(key)
            if not q:
                return 0.0
            self._prune(q, now)
            if len(q) >= self.limit:
                return max(self.window_s - (now - q[0]), 0.001)
            return 0.0


def from_env(var: str, default: str) -> RateLimiter:
    """从环境变量解析限流配置，如 '10/60'、'120'、'0'（不限流）。"""
    raw = os.environ.get(var, "").strip() or default
    num, _, win = raw.partition("/")
    try:
        limit = int(num)
        window = float(win) if win else 60.0
    except ValueError as exc:
        raise ValueError(f"{var} 格式错误（应为 N 或 N/秒数）: {raw!r}") from exc
    return RateLimiter(limit, window)
