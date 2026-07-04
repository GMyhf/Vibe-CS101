import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from vibe_cs101 import journal, server


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        # 把错题本指到临时目录，避免测试写入真实 data/
        cls._orig_journal_db = journal.JOURNAL_DB
        cls._orig_data_dir = journal.DATA_DIR
        journal.JOURNAL_DB = Path(cls._tmp.name) / "journal.db"
        journal.DATA_DIR = Path(cls._tmp.name)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        journal.JOURNAL_DB = cls._orig_journal_db
        journal.DATA_DIR = cls._orig_data_dir
        cls._tmp.cleanup()

    def setUp(self):
        server.AUTH_KEYS = {}
        with server._sessions_lock:
            server._sessions.clear()

    def request(self, path, method="GET", body=None, key=None):
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            method=method,
            data=json.dumps(body).encode() if body is not None else None,
            headers=headers,
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
        session_id, sess = server._get_session("owner", None)
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

    def test_auth_rejects_missing_and_accepts_bearer_key(self):
        server.AUTH_KEYS = {"alice": "alice-key"}

        status, data = self.request("/api/me")
        self.assertEqual(status, 401)
        self.assertIn("API key", data["error"])

        status, data = self.request("/api/me", key="alice-key")
        self.assertEqual(status, 200)
        self.assertEqual(data["user"], "alice")
        self.assertTrue(data["auth_enabled"])

    def test_auth_accepts_x_api_key_fallback(self):
        server.AUTH_KEYS = {"alice": "alice-key"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/me",
            headers={"X-API-Key": "alice-key"},
        )
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode())
        self.assertEqual(resp.status, 200)
        self.assertEqual(data["user"], "alice")

    def test_mistakes_are_isolated_per_authenticated_user(self):
        server.AUTH_KEYS = {"alice": "alice-key", "bob": "bob-key"}

        status, data = self.request("/api/mistakes", "POST", {"problem": "Alice only"}, key="alice-key")
        self.assertEqual(status, 201)

        status, data = self.request("/api/mistakes?view=all", key="bob-key")
        self.assertEqual(status, 200)
        self.assertEqual(data["mistakes"], [])

        status, data = self.request("/api/mistakes?view=all", key="alice-key")
        self.assertEqual(status, 200)
        self.assertEqual([m["problem"] for m in data["mistakes"]], ["Alice only"])

    def test_chat_sessions_are_isolated_per_authenticated_user(self):
        alice_id, alice_sess = server._get_session("alice", "shared")
        bob_id, bob_sess = server._get_session("bob", "shared")

        self.assertEqual(alice_id, bob_id)
        self.assertIsNot(alice_sess, bob_sess)
        self.assertEqual(alice_sess["agent"].tool_context["journal_db"], journal.user_db("alice"))
        self.assertEqual(bob_sess["agent"].tool_context["journal_db"], journal.user_db("bob"))

    def test_remote_serve_requires_auth_key(self):
        with patch("vibe_cs101.server.load_auth_keys", return_value={}):
            with self.assertRaises(SystemExit):
                server.serve(host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
