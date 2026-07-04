import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibe_cs101 import sessions


MSGS = [
    {"role": "system", "content": "prompt"},
    {"role": "user", "content": "单调栈是什么？这是一个比较长的问题描述用来测试标题截断" * 3},
    {"role": "assistant", "content": "", "tool_calls": [{"id": "x"}]},
    {"role": "tool", "tool_call_id": "x", "content": "{}"},
    {"role": "assistant", "content": "单调栈是……"},
]


class SessionsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "sessions.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_load_roundtrip(self):
        sessions.save("alice", "s1", MSGS, db_path=self.db)
        self.assertEqual(sessions.load("alice", "s1", db_path=self.db), MSGS)

    def test_load_missing_returns_none(self):
        self.assertIsNone(sessions.load("alice", "nope", db_path=self.db))
        sessions.save("alice", "s1", MSGS, db_path=self.db)
        self.assertIsNone(sessions.load("bob", "s1", db_path=self.db))  # 用户隔离

    def test_list_title_and_order(self):
        sessions.save("alice", "s1", MSGS, db_path=self.db)
        sessions.save("alice", "s2", [{"role": "user", "content": "第二个会话"}], db_path=self.db)
        rows = sessions.list_sessions("alice", db_path=self.db)
        self.assertEqual([r["id"] for r in rows][:1], ["s2"])  # 最近更新在前
        self.assertEqual(len(rows), 2)
        self.assertTrue(rows[1]["title"].startswith("单调栈是什么？"))
        self.assertLessEqual(len(rows[1]["title"]), 60)

    def test_update_existing_session(self):
        sessions.save("alice", "s1", MSGS, db_path=self.db)
        more = MSGS + [{"role": "user", "content": "追问"}]
        sessions.save("alice", "s1", more, db_path=self.db)
        self.assertEqual(len(sessions.list_sessions("alice", db_path=self.db)), 1)
        self.assertEqual(sessions.load("alice", "s1", db_path=self.db), more)

    def test_delete(self):
        sessions.save("alice", "s1", MSGS, db_path=self.db)
        self.assertTrue(sessions.delete("alice", "s1", db_path=self.db))
        self.assertFalse(sessions.delete("alice", "s1", db_path=self.db))
        self.assertIsNone(sessions.load("alice", "s1", db_path=self.db))

    def test_prune_keeps_most_recent(self):
        with patch.object(sessions, "MAX_SAVED_PER_USER", 3):
            for i in range(5):
                sessions.save("alice", f"s{i}", [{"role": "user", "content": f"q{i}"}], db_path=self.db)
        rows = sessions.list_sessions("alice", db_path=self.db)
        self.assertEqual(len(rows), 3)
        self.assertIn("s4", [r["id"] for r in rows])

    def test_display_messages_filters_internals(self):
        shown = sessions.display_messages(MSGS)
        self.assertEqual([m["role"] for m in shown], ["user", "assistant"])
        self.assertEqual(shown[-1]["content"], "单调栈是……")


if __name__ == "__main__":
    unittest.main()
