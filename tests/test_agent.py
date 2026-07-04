import json
import unittest

from vibe_cs101.agent import Agent
from vibe_cs101.config import LLMConfig


def make_agent(script):
    """Agent whose chat_fn pops canned assistant messages from `script`."""
    agent = Agent(cfg=LLMConfig(base_url="http://test", api_key="test-key", model="test"))
    calls = []

    def fake_chat(cfg, messages, tools=None, temperature=0.3):
        calls.append({"messages": [dict(m) for m in messages], "tools": tools})
        return script.pop(0)

    agent.chat_fn = fake_chat
    return agent, calls


class AgentLoopTests(unittest.TestCase):
    def test_plain_answer(self):
        agent, calls = make_agent([{"content": "答案", "tool_calls": None}])
        self.assertEqual(agent.ask("你好"), "答案")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["messages"][0]["role"], "system")

    def test_tool_call_roundtrip(self):
        tool_call = {"id": "call_1", "function": {"name": "list_sources", "arguments": "{}"}}
        agent, calls = make_agent(
            [
                {"content": "", "tool_calls": [tool_call]},
                {"content": "最终回答", "tool_calls": None},
            ]
        )
        self.assertEqual(agent.ask("有哪些资料？"), "最终回答")
        tool_msgs = [m for m in calls[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(len(tool_msgs), 1)
        self.assertEqual(tool_msgs[0]["tool_call_id"], "call_1")
        self.assertIn("sources", json.loads(tool_msgs[0]["content"]))

    def test_unknown_tool_reports_error_to_model(self):
        tool_call = {"id": "c1", "function": {"name": "nope", "arguments": "{}"}}
        agent, calls = make_agent(
            [
                {"content": "", "tool_calls": [tool_call]},
                {"content": "ok", "tool_calls": None},
            ]
        )
        agent.ask("x")
        tool_msg = [m for m in calls[1]["messages"] if m["role"] == "tool"][0]
        self.assertIn("unknown tool", tool_msg["content"])

    def test_conversation_history_persists(self):
        agent, calls = make_agent(
            [
                {"content": "第一轮", "tool_calls": None},
                {"content": "第二轮", "tool_calls": None},
            ]
        )
        agent.ask("q1")
        agent.ask("q2")
        roles = [m["role"] for m in calls[1]["messages"]]
        self.assertEqual(roles, ["system", "user", "assistant", "user"])


if __name__ == "__main__":
    unittest.main()
