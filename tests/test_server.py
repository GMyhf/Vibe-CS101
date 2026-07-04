import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from vibe_cs101 import journal, server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        # 把错题本指到临时目录，避免测试写入真实 data/
        cls._orig_journal_db = journal.JOURNAL_DB
        journal.JOURNAL_DB = Path(cls._tmp.name) / "journal.db"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        journal.JOURNAL_DB = cls._orig_journal_db
        cls._tmp.cleanup()

    def request(self, path, method="GET", body=None):
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read().decode())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode())

    def test_info(self):
        status, data = self.request("/api/info")
        self.assertEqual(status, 200)
        self.assertIn("llm_configured", data)
        self.assertIn("index", data)

    def test_index_page_served(self):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/") as resp:
            html = resp.read().decode()
        self.assertEqual(resp.status, 200)
        self.assertIn("Vibe-cs101", html)

    def test_static_path_traversal_blocked(self):
        status, data = self.request("/../pyproject.toml")
        self.assertEqual(status, 404)

    def test_mistake_crud_and_review_flow(self):
        status, data = self.request(
            "/api/mistakes", "POST",
            {"problem": "LeetCode 42 接雨水", "course": "cs101", "tags": "单调栈", "reason": "边界写错"},
        )
        self.assertEqual(status, 201)
        mid = data["mistake"]["id"]

        status, data = self.request("/api/mistakes?view=all")
        self.assertEqual(status, 200)
        self.assertTrue(any(m["id"] == mid for m in data["mistakes"]))

        status, data = self.request(f"/api/mistakes/{mid}/review", "POST", {"result": "good"})
        self.assertEqual(status, 200)
        self.assertEqual(data["mistake"]["review_count"], 1)

        status, data = self.request("/api/mistakes/stats")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(data["total"], 1)

        status, data = self.request(f"/api/mistakes/{mid}", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(data["deleted"])

    def test_mistake_validation(self):
        status, data = self.request("/api/mistakes", "POST", {"problem": "  "})
        self.assertEqual(status, 400)
        status, data = self.request("/api/mistakes/99999/review", "POST", {"result": "good"})
        self.assertEqual(status, 400)

    def test_chat_requires_message(self):
        status, data = self.request("/api/chat", "POST", {"message": ""})
        self.assertEqual(status, 400)

    def test_chat_roundtrip_with_stubbed_llm(self):
        # 打桩 LLM：绕过网络，验证 chat 会话与 events 通路
        session_id, sess = server._get_session(None)
        sess["agent"].chat_fn = lambda cfg, messages, tools=None, temperature=0.3: {
            "content": f"echo: {messages[-1]['content']}", "tool_calls": None,
        }
        status, data = self.request("/api/chat", "POST", {"message": "你好", "session_id": session_id})
        self.assertEqual(status, 200)
        self.assertEqual(data["answer"], "echo: 你好")
        self.assertEqual(data["session_id"], session_id)

    def test_unknown_api_404(self):
        status, data = self.request("/api/nope")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
