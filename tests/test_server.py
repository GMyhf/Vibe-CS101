import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from vibe_cs101 import journal, server, sessions, users
from vibe_cs101.ratelimit import RateLimiter


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.TemporaryDirectory()
        # 把错题本/会话/用户库指到临时目录，避免测试写入真实 data/
        cls._orig_journal_db = journal.JOURNAL_DB
        cls._orig_data_dir = journal.DATA_DIR
        cls._orig_sessions_db = sessions.SESSIONS_DB
        cls._orig_users_db = users.USERS_DB
        journal.JOURNAL_DB = Path(cls._tmp.name) / "journal.db"
        journal.DATA_DIR = Path(cls._tmp.name)
        sessions.SESSIONS_DB = Path(cls._tmp.name) / "sessions.db"
        users.USERS_DB = Path(cls._tmp.name) / "users.db"
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        cls.port = cls.httpd.server_address[1]
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        journal.JOURNAL_DB = cls._orig_journal_db
        journal.DATA_DIR = cls._orig_data_dir
        sessions.SESSIONS_DB = cls._orig_sessions_db
        users.USERS_DB = cls._orig_users_db
        cls._tmp.cleanup()

    def setUp(self):
        server.AUTH_KEYS = {}
        server.API_LIMITER = RateLimiter(0)  # 0 = 不限流
        server.CHAT_LIMITER = RateLimiter(0)
        server.AUTH_FAIL_LIMITER = RateLimiter(0)
        sessions.SESSIONS_DB.unlink(missing_ok=True)
        users.USERS_DB.unlink(missing_ok=True)
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

    def _stub_agent(self, sess):
        sess["agent"].chat_fn = lambda cfg, messages, tools=None, temperature=0.3: {
            "content": f"echo: {messages[-1]['content']}", "tool_calls": None,
        }

    def test_chat_session_persists_and_survives_memory_eviction(self):
        session_id, sess = server._get_session("owner", None)
        self._stub_agent(sess)
        status, _ = self.request("/api/chat", "POST", {"message": "第一问", "session_id": session_id})
        self.assertEqual(status, 200)

        # 会话列表 / 历史消息端点
        status, data = self.request("/api/sessions")
        self.assertEqual(status, 200)
        self.assertEqual([s["id"] for s in data["sessions"]], [session_id])
        self.assertTrue(data["sessions"][0]["title"].startswith("第一问"))
        status, data = self.request(f"/api/sessions/{session_id}")
        self.assertEqual(status, 200)
        self.assertEqual(
            data["messages"], [{"role": "user", "content": "第一问"}, {"role": "assistant", "content": "echo: 第一问"}]
        )

        # 模拟服务重启/内存淘汰：内存清空后按 session_id 仍能恢复完整上下文
        with server._sessions_lock:
            server._sessions.clear()
        new_id, restored = server._get_session("owner", session_id)
        self.assertEqual(new_id, session_id)
        contents = [m.get("content") for m in restored["agent"].messages]
        self.assertIn("第一问", contents)
        self.assertIn("echo: 第一问", contents)

    def test_session_delete_endpoint(self):
        session_id, sess = server._get_session("owner", None)
        self._stub_agent(sess)
        self.request("/api/chat", "POST", {"message": "hi", "session_id": session_id})
        status, data = self.request(f"/api/sessions/{session_id}", "DELETE")
        self.assertEqual(status, 200)
        self.assertTrue(data["deleted"])
        status, _ = self.request(f"/api/sessions/{session_id}")
        self.assertEqual(status, 404)
        status, _ = self.request(f"/api/sessions/{session_id}", "DELETE")
        self.assertEqual(status, 404)

    def test_sessions_endpoint_isolated_per_user(self):
        server.AUTH_KEYS = {"alice": "alice-key", "bob": "bob-key"}
        session_id, sess = server._get_session("alice", None)
        self._stub_agent(sess)
        self.request("/api/chat", "POST", {"message": "alice 的会话", "session_id": session_id}, key="alice-key")
        status, data = self.request("/api/sessions", key="bob-key")
        self.assertEqual(data["sessions"], [])
        status, data = self.request(f"/api/sessions/{session_id}", key="bob-key")
        self.assertEqual(status, 404)

    def test_chat_rate_limit_returns_429(self):
        server.CHAT_LIMITER = RateLimiter(1, window_s=60)
        session_id, sess = server._get_session("owner", None)
        self._stub_agent(sess)
        status, _ = self.request("/api/chat", "POST", {"message": "1", "session_id": session_id})
        self.assertEqual(status, 200)
        status, data = self.request("/api/chat", "POST", {"message": "2", "session_id": session_id})
        self.assertEqual(status, 429)
        self.assertIn("频繁", data["error"])

    def test_api_rate_limit_returns_429(self):
        server.API_LIMITER = RateLimiter(2, window_s=60)
        self.assertEqual(self.request("/api/me")[0], 200)
        self.assertEqual(self.request("/api/me")[0], 200)
        self.assertEqual(self.request("/api/me")[0], 429)

    def test_db_users_can_authenticate(self):
        key = users.add_user("carol")
        status, data = self.request("/api/me")  # 有 DB 用户 → 鉴权已启用
        self.assertEqual(status, 401)
        status, data = self.request("/api/me", key=key)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"], "carol")
        self.assertTrue(data["auth_enabled"])

    def test_auth_failures_are_rate_limited(self):
        server.AUTH_KEYS = {"alice": "alice-key"}
        server.AUTH_FAIL_LIMITER = RateLimiter(2, window_s=60)
        self.assertEqual(self.request("/api/me", key="bad-1")[0], 401)
        self.assertEqual(self.request("/api/me", key="bad-2")[0], 401)
        self.assertEqual(self.request("/api/me", key="bad-3")[0], 429)
        # 正确的 key 也被同 IP 的失败限流挡住，直到窗口过期——这是防暴力破解的预期行为
        self.assertEqual(self.request("/api/me", key="alice-key")[0], 429)

    def test_stream_response_terminates(self):
        # SSE 流结束后必须关闭连接，否则前端 fetch 永远等不到 EOF（发送按钮卡死）
        session_id, sess = server._get_session("owner", None)
        sess["agent"].chat_fn = lambda cfg, messages, tools=None, temperature=0.3: {
            "content": "答案", "tool_calls": None,
        }
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/chat/stream",
            method="POST",
            data=json.dumps({"message": "q", "session_id": session_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # 未关连接会超时
            body = resp.read().decode()
        self.assertIn('"type": "done"', body.replace('"type":"done"', '"type": "done"'))

    def _lib_root(self):
        root = Path(self._tmp.name) / "lib"
        (root / "sub").mkdir(parents=True, exist_ok=True)
        (root / "a.md").write_text("# hello", encoding="utf-8")
        (root / "sub" / "b.py").write_text("print(1)", encoding="utf-8")
        (root / "secret.env").write_text("KEY=1", encoding="utf-8")  # 扩展名不在白名单
        (root / ".hidden").mkdir(exist_ok=True)
        (root / ".hidden" / "c.md").write_text("x", encoding="utf-8")
        return root

    def test_library_list_and_fetch(self):
        root = self._lib_root()
        with patch("vibe_cs101.server._library_roots", return_value={"course": ("课件", root)}):
            status, data = self.request("/api/library")
            self.assertEqual(status, 200)
            self.assertEqual(
                [f["path"] for f in data["sources"][0]["files"]], ["a.md", "sub/b.py"]
            )

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/library/file?source=course&path=a.md&download=1"
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.read().decode(), "# hello")
                self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_library_blocks_traversal_and_unknown(self):
        root = self._lib_root()
        with patch("vibe_cs101.server._library_roots", return_value={"course": ("课件", root)}):
            for path in ("../outside.md", "..%2F..%2Fetc%2Fpasswd", "secret.env", ".hidden/c.md"):
                status, _ = self.request(f"/api/library/file?source=course&path={path}")
                self.assertEqual(status, 404, path)
            status, _ = self.request("/api/library/file?source=nope&path=a.md")
            self.assertEqual(status, 404)

    def test_remote_serve_requires_auth_key(self):
        with patch("vibe_cs101.server.load_auth_keys", return_value={}):
            with self.assertRaises(SystemExit):
                server.serve(host="0.0.0.0", port=0)


if __name__ == "__main__":
    unittest.main()
