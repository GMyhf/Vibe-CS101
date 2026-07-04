"""Tool-calling agent loop grounded in the local material index."""

from __future__ import annotations

from typing import Callable

from .config import LLMConfig, load_llm_config
from .llm import chat
from .tools import TOOL_SCHEMAS, run_tool

MAX_ITERATIONS = 12

SYSTEM_PROMPT = """\
你是 Vibe-cs101，一位个人计算机基础学习助教，服务于北大《计算概论B（cs101）》和\
《数据结构与算法B（cs201）》课程的学习者。

你可以检索的资料（都来自任课老师）：
- 课程课件：2025 秋季 cs101、2026 春季 cs201 的每周讲义、作业、cheatsheet、往年考题
- 题解：LeetCode（简单/中等/挑战）、cs101.openjudge.cn、Codeforces、晴问算法笔记、cs201 数算题解

工作方式：
1. 回答课程或算法问题前，先用 search_materials 检索相关资料，必要时用 read_section 读取全文。
2. 回答要以检索到的老师资料为根据，并注明出处（来源与章节标题）。资料没有覆盖时明确说明，再给出你自己的讲解。
3. 讲解算法时给出思路、复杂度，代码优先用 Python（cs101/cs201 的主要语言）。
4. 用中文回答（除非提问是英文）。

错题本（学习进度跟踪）：
- 用户说做错了某题、某题不会时，主动提议用 record_mistake 记入错题本（标注知识点标签和错误原因，
  并先检索题解、把对应 section_id 关联上）。
- 用户想复习时，用 review_mistakes 查今日到期错题，逐题考查后用 mark_reviewed 记录结果。
- 用户问学习情况时，用 review_mistakes(view="stats") 给出薄弱知识点分析和复习建议。
"""


class Agent:
    def __init__(
        self,
        cfg: LLMConfig | None = None,
        on_event: Callable[[str], None] | None = None,
        tool_context: dict | None = None,
    ):
        self.cfg = cfg or load_llm_config()
        self.messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.on_event = on_event or (lambda _msg: None)
        # 传给工具的调用方上下文（如按用户隔离的 journal_db）
        self.tool_context = tool_context or {}
        # Injectable for tests: same signature as llm.chat.
        self.chat_fn = chat

    def ask(self, user_message: str) -> str:
        """Run one user turn through the tool loop; returns the final answer."""
        self.messages.append({"role": "user", "content": user_message})

        for _ in range(MAX_ITERATIONS):
            tools = TOOL_SCHEMAS if _ < MAX_ITERATIONS - 1 else None
            msg = self.chat_fn(self.cfg, self.messages, tools=tools)
            tool_calls = msg.get("tool_calls") or []

            assistant_msg: dict = {"role": "assistant", "content": msg.get("content") or ""}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            self.messages.append(assistant_msg)

            if not tool_calls:
                return msg.get("content") or "(模型返回了空回答)"

            for call in tool_calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                args = fn.get("arguments", "") or "{}"
                self.on_event(f"🔧 {name}({args[:120]})")
                result = run_tool(name, args, self.tool_context)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": result,
                    }
                )

        return "(达到最大工具调用轮数，未能完成回答)"
