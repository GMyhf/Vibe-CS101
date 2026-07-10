import json
import os
import tempfile
import threading
import unittest
import urllib.request
from io import StringIO
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote
from unittest.mock import patch

from vibe_cs101 import audit, courses, journal, server, sessions, store, users
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
        cls._orig_courses_db = courses.COURSES_DB
        cls._orig_audit_db = audit.AUDIT_DB
        journal.JOURNAL_DB = Path(cls._tmp.name) / "journal.db"
        journal.DATA_DIR = Path(cls._tmp.name)
        sessions.SESSIONS_DB = Path(cls._tmp.name) / "sessions.db"
        users.USERS_DB = Path(cls._tmp.name) / "users.db"
        courses.COURSES_DB = Path(cls._tmp.name) / "courses.db"
        audit.AUDIT_DB = Path(cls._tmp.name) / "audit.db"
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
        courses.COURSES_DB = cls._orig_courses_db
        audit.AUDIT_DB = cls._orig_audit_db
        cls._tmp.cleanup()

    def setUp(self):
        server.AUTH_KEYS = {}
        server.API_LIMITER = RateLimiter(0)  # 0 = 不限流
        server.CHAT_LIMITER = RateLimiter(0)
        server.AUTH_FAIL_LIMITER = RateLimiter(0)
        sessions.SESSIONS_DB.unlink(missing_ok=True)
        users.USERS_DB.unlink(missing_ok=True)
        courses.COURSES_DB.unlink(missing_ok=True)
        audit.AUDIT_DB.unlink(missing_ok=True)
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

    def test_document_endpoint_returns_whole_file_for_section(self):
        doc = {
            "section_id": 1,
            "matched_section_id": 1,
            "source": "2025fall-cs101",
            "course": "cs101",
            "kind": "courseware",
            "file": "dp.md",
            "title": "dp.md",
            "matched_title": "dp > 动态规划",
            "section_count": 2,
            "sections": [{"id": 1, "title": "dp > 动态规划", "content": "# DP\n\n动态规划正文"}],
            "content": "# DP\n\n动态规划正文",
        }
        with patch("vibe_cs101.server.store.get_document_for_section", return_value=doc):
            status, data = self.request("/api/document/1")

        self.assertEqual(status, 200)
        self.assertEqual(data["matched_section_id"], 1)
        self.assertEqual(data["sections"][0]["id"], 1)
        self.assertEqual(data["content"], "# DP\n\n动态规划正文")
        self.assertEqual(data["section_count"], 2)

    def test_search_limit_validation(self):
        with patch("vibe_cs101.server.store.search", return_value=[]) as search:
            invalid = ("-1", "0", str(store.MAX_SEARCH_RESULTS + 1), "not-a-number")
            for value in invalid:
                status, data = self.request(f"/api/search?q=dp&limit={value}")
                self.assertEqual(status, 400)
                self.assertIn("limit 必须", data["error"])
            search.assert_not_called()

            status, _ = self.request("/api/search?q=dp")
            self.assertEqual(status, 200)
            self.assertEqual(search.call_args.kwargs["limit"], 10)

            status, _ = self.request("/api/search?q=dp&limit=1")
            self.assertEqual(status, 200)
            self.assertEqual(search.call_args.kwargs["limit"], 1)

            status, _ = self.request(
                f"/api/search?q=dp&limit={store.MAX_SEARCH_RESULTS}"
            )
            self.assertEqual(status, 200)
            self.assertEqual(search.call_args.kwargs["limit"], store.MAX_SEARCH_RESULTS)

    def test_solution_search_limit_validation(self):
        with patch("vibe_cs101.server._search_solutions", return_value=[]) as search:
            invalid = ("-1", "0", str(server.SOL101_SEARCH_MAX_RESULTS + 1), "not-a-number")
            for value in invalid:
                status, data = self.request(f"/api/solutions/search?q=dp&limit={value}")
                self.assertEqual(status, 400)
                self.assertIn("limit 必须", data["error"])
            search.assert_not_called()

            for path, expected in (
                ("/api/solutions/search?q=dp", 30),
                ("/api/solutions/search?q=dp&limit=1", 1),
                (
                    f"/api/solutions/search?q=dp&limit={server.SOL101_SEARCH_MAX_RESULTS}",
                    server.SOL101_SEARCH_MAX_RESULTS,
                ),
            ):
                status, _ = self.request(path)
                self.assertEqual(status, 200)
                self.assertEqual(search.call_args.args[2], expected)

    def test_mistake_crud_and_review_flow(self):
        status, data = self.request(
            "/api/mistakes", "POST",
            {
                "problem": "LeetCode 42 接雨水",
                "course": "cs101",
                "tags": "单调栈",
                "reason": "边界写错",
                "link": "https://leetcode.cn/problems/trapping-rain-water/",
            },
        )
        self.assertEqual(status, 201)
        mid = data["mistake"]["id"]
        self.assertEqual(data["mistake"]["link"], "https://leetcode.cn/problems/trapping-rain-water/")

        status, data = self.request("/api/mistakes?view=all")
        self.assertEqual(status, 200)
        self.assertTrue(any(m["id"] == mid for m in data["mistakes"]))

        status, data = self.request(f"/api/mistakes/{mid}")
        self.assertEqual(status, 200)
        self.assertEqual(data["mistake"]["link"], "https://leetcode.cn/problems/trapping-rain-water/")

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
        key = users.add_user("carol", role="student")
        status, data = self.request("/api/me")  # 有 DB 用户 → 鉴权已启用
        self.assertEqual(status, 401)
        status, data = self.request("/api/me", key=key)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"], "carol")
        self.assertEqual(data["role"], "student")
        self.assertTrue(data["auth_enabled"])

    def test_teacher_can_add_users_and_change_roles(self):
        teacher_key = users.add_user("teacher", role="teacher")
        status, data = self.request(
            "/api/admin/users", "POST",
            {"name": "student1", "role": "student", "display_name": "学生一", "department": "信息学院"},
            key=teacher_key,
        )
        self.assertEqual(status, 201)
        self.assertEqual(data["user"]["role"], "student")
        self.assertEqual(data["user"]["display_name"], "学生一")
        self.assertIn("key", data)

        status, data = self.request(
            "/api/admin/users/student1", "PATCH", {"role": "assistant"}, key=teacher_key
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["role"], "assistant")

        status, data = self.request("/api/admin/users/student1/reset", "POST", {}, key=teacher_key)
        self.assertEqual(status, 200)
        self.assertIn("key", data)

        status, data = self.request("/api/admin/users/student1", "DELETE", key=teacher_key)
        self.assertEqual(status, 200)
        self.assertTrue(data["deleted"])

    def test_teacher_can_batch_import_students(self):
        teacher_key = users.add_user("teacher", role="teacher")
        status, data = self.request(
            "/api/admin/users/import", "POST",
            {"text": "2100012865 郭彦君 信息科学技术学院\n2200011313,李昱麒,物理学院"},
            key=teacher_key,
        )
        self.assertEqual(status, 201)
        self.assertEqual(len(data["imported"]), 2)
        status, data = self.request("/api/admin/users", key=teacher_key)
        self.assertEqual(data["users"][0]["student_id"], "2100012865")
        self.assertEqual(data["users"][0]["display_name"], "郭彦君")

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/admin/users/export",
            headers={"Authorization": f"Bearer {teacher_key}"},
        )
        with urllib.request.urlopen(req) as resp:
            csv_text = resp.read().decode("utf-8-sig")
        self.assertIn("学号,姓名,院系", csv_text)
        self.assertIn("2100012865,郭彦君,信息科学技术学院", csv_text)

    def test_student_cannot_use_admin_endpoints(self):
        student_key = users.add_user("student", role="student")
        status, data = self.request("/api/admin/users", key=student_key)
        self.assertEqual(status, 403)
        status, data = self.request("/api/admin/courses", key=student_key)
        self.assertEqual(status, 403)
        status, data = self.request("/api/admin/logs", key=student_key)
        self.assertEqual(status, 403)
        status, data = self.request("/api/admin/logs/export", key=student_key)
        self.assertEqual(status, 403)

    def test_assistant_can_manage_courses_and_view_logs_not_users(self):
        assistant_key = users.add_user("ta", role="assistant")
        status, data = self.request("/api/admin/users", key=assistant_key)
        self.assertEqual(status, 403)

        status, data = self.request("/api/admin/courses", key=assistant_key)
        self.assertEqual(status, 200)
        first = data["resources"][0]["name"]
        course = data["resources"][0]["course"]
        status, data = self.request(
            f"/api/admin/courses/{course}", "POST", {"resources": [first]}, key=assistant_key
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["course"]["resources"], [first])

        status, data = self.request("/api/admin/logs", key=assistant_key)
        self.assertEqual(status, 200)
        self.assertIn("events", data)

    def test_search_uses_enabled_course_resources(self):
        teacher_key = users.add_user("teacher", role="teacher")
        courses.set_course_resources("cs101", ["openjudge"], "teacher")
        hit = store.Hit(1, "openjudge", "cs101", "solutions", "x.md", "title", "snippet")
        with patch("vibe_cs101.server.store.search", return_value=[hit]) as search:
            status, data = self.request("/api/search?q=dp&course=cs101", key=teacher_key)

        self.assertEqual(status, 200)
        self.assertEqual(data["results"][0]["source"], "openjudge")
        self.assertEqual(search.call_args.kwargs["sources"], ["openjudge"])

    def test_explicit_search_source_bypasses_enabled_course_resources(self):
        teacher_key = users.add_user("teacher", role="teacher")
        courses.set_course_resources("cs101", ["openjudge"], "teacher")
        with patch("vibe_cs101.server.store.search", return_value=[]) as search:
            status, _ = self.request("/api/search?q=dp&course=cs101&source=leetcode", key=teacher_key)

        self.assertEqual(status, 200)
        self.assertIsNone(search.call_args.kwargs["sources"])

    def test_audit_logs_student_activity_for_staff(self):
        teacher_key = users.add_user("teacher", role="teacher")
        student_key = users.add_user("student", role="student")
        self.request("/api/search?q=dp", key=student_key)
        self.request("/api/mistakes?view=all", key=student_key)

        status, data = self.request("/api/admin/logs?user=student", key=teacher_key)
        self.assertEqual(status, 200)
        actions = [e["action"] for e in data["events"]]
        self.assertIn("search", actions)
        self.assertIn("mistakes_view", actions)

    def test_admin_logs_support_pagination_and_export(self):
        teacher_key = users.add_user("teacher", role="teacher")
        for i in range(5):
            audit.log("student", "student", "search", {"i": i})

        status, data = self.request("/api/admin/logs?user=student&limit=2&offset=1", key=teacher_key)
        self.assertEqual(status, 200)
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["limit"], 2)
        self.assertEqual(data["offset"], 1)
        self.assertEqual(len(data["events"]), 2)
        self.assertEqual(data["events"][0]["detail"]["i"], 3)

        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/admin/logs/export?user=student",
            headers={"Authorization": f"Bearer {teacher_key}"},
        )
        with urllib.request.urlopen(req) as resp:
            csv_text = resp.read().decode("utf-8-sig")
        self.assertIn("时间,用户,角色,行为,详情", csv_text)
        self.assertIn("student,student,search", csv_text)
        self.assertIn('"{""i"": 4}"', csv_text)

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
            "content": "READY", "tool_calls": None,
        }
        sess["agent"].stream_chat_fn = lambda cfg, messages, temperature=0.3: iter(["答", "案"])
        req = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/api/chat/stream",
            method="POST",
            data=json.dumps({"message": "q", "session_id": session_id}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # 未关连接会超时
            body = resp.read().decode()
        self.assertIn('"type": "done"', body.replace('"type":"done"', '"type": "done"'))
        self.assertIn('"text": "答"', body.replace('"text":"答"', '"text": "答"'))

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
            self.assertEqual(
                [f["display_path"] for f in data["sources"][0]["files"]],
                ["course/a.md", "course/sub/b.py"],
            )

            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/library/file?source=course&path=a.md&download=1"
            )
            with urllib.request.urlopen(req) as resp:
                self.assertEqual(resp.read().decode(), "# hello")
                self.assertIn("attachment", resp.headers.get("Content-Disposition", ""))

    def test_library_hides_legacy_remote_duplicate(self):
        root = Path(self._tmp.name) / "original"
        structured = root / "2024fall-cs101" / "2024fall_LeetCode_problems.md"
        legacy = root / "leetcode.md"
        structured.parent.mkdir(parents=True, exist_ok=True)
        structured.write_text("# structured", encoding="utf-8")
        legacy.write_text("# legacy", encoding="utf-8")
        with patch("vibe_cs101.config.ORIGINAL_DIR", root), patch("vibe_cs101.server.ORIGINAL_DIR", root):
            files = server._library_files(root, server._hidden_library_files(root))
        self.assertEqual([f["path"] for f in files], ["2024fall-cs101/2024fall_LeetCode_problems.md"])

    def test_library_blocks_traversal_and_unknown(self):
        root = self._lib_root()
        with patch("vibe_cs101.server._library_roots", return_value={"course": ("课件", root)}):
            for path in ("../outside.md", "..%2F..%2Fetc%2Fpasswd", "secret.env", ".hidden/c.md"):
                status, _ = self.request(f"/api/library/file?source=course&path={path}")
                self.assertEqual(status, 404, path)
            status, _ = self.request("/api/library/file?source=nope&path=a.md")
            self.assertEqual(status, 404)

    def test_sol101_endpoint_returns_links_and_logs(self):
        teacher_key = users.add_user("teacher", role="teacher")
        student_key = users.add_user("student", role="student")

        status, data = self.request("/api/sol101", key=student_key)
        self.assertEqual(status, 200)
        self.assertEqual(data["mode"], "native")
        self.assertEqual(data["site_url"], "/sol101/")
        self.assertEqual(data["repo_url"], "https://github.com/FuYnAloft/sol101")

        status, logs = self.request("/api/admin/logs?action=sol101_view", key=teacher_key)
        self.assertEqual(status, 200)
        self.assertTrue(any(e["action"] == "sol101_view" for e in logs["events"]))

    def test_native_solutions_api_lists_searches_and_reads_markdown(self):
        student_key = users.add_user("student", role="student")
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "cf").mkdir()
            (docs / ".vitepress").mkdir()
            (docs / ".vitepress" / "config.mjs").write_text(
                "sidebar: {'/cf': {items: [{ text: '2A. Winner', link: '/cf/2a' },"
                "{ text: '1A. Theatre Square', link: '/cf/1a' }]}}",
                encoding="utf-8",
            )
            (docs / "cf" / "1a.md").write_text(
                "# 1A. Theatre Square\n\nmath, http://codeforces.com/problemset/problem/1/A\n\n"
                "Use ceiling division.",
                encoding="utf-8",
            )
            (docs / "cf" / "2a.md").write_text(
                "# 2A. Winner\n\ngreedy, http://codeforces.com/problemset/problem/2/A\n\nTrack scores.",
                encoding="utf-8",
            )
            with patch("vibe_cs101.server.SOL101_DOCS_DIR", docs):
                status, data = self.request("/api/solutions", key=student_key)
                self.assertEqual(status, 200)
                self.assertEqual(data["sets"][0]["name"], "cf")
                self.assertEqual(data["sets"][0]["count"], 2)

                status, data = self.request("/api/solutions/list?set=cf", key=student_key)
                self.assertEqual(status, 200)
                self.assertEqual(data["set"]["name"], "cf")
                self.assertEqual([x["path"] for x in data["items"]], ["2a.md", "1a.md"])
                self.assertEqual(data["items"][0]["title"], "2A. Winner")
                self.assertEqual(data["items"][0]["next"]["path"], "1a.md")

                status, data = self.request("/api/solutions/search?q=Theatre&set=cf", key=student_key)
                self.assertEqual(status, 200)
                self.assertEqual(data["results"][0]["title"], "1A. Theatre Square")
                self.assertEqual(data["results"][0]["path"], "1a.md")

                status, data = self.request("/api/solutions/file?set=cf&path=1a.md", key=student_key)
                self.assertEqual(status, 200)
                self.assertEqual(data["title"], "1A. Theatre Square")
                self.assertIn("ceiling division", data["content"])
                self.assertEqual(data["prev"]["path"], "2a.md")
                self.assertIsNone(data["next"])

                status, _ = self.request("/api/solutions/file?set=cf&path=../secret.md", key=student_key)
                self.assertEqual(status, 404)
                status, _ = self.request("/api/solutions/list?set=missing", key=student_key)
                self.assertEqual(status, 404)

    def test_solution_search_cache_reuses_reads_and_invalidates_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            docs = Path(tmp)
            (docs / "cf").mkdir()
            first = docs / "cf" / "1a.md"
            second = docs / "cf" / "2a.md"
            first.write_text("# First\n\nceiling division", encoding="utf-8")
            second.write_text("# Second\n\ntrack scores", encoding="utf-8")

            server._cached_solution_record.cache_clear()
            try:
                with patch("vibe_cs101.server.SOL101_DOCS_DIR", docs), \
                     patch(
                         "vibe_cs101.server._read_solution_record",
                         wraps=server._read_solution_record,
                     ) as read_record, \
                     patch(
                         "vibe_cs101.server._sol101_set_info",
                         wraps=server._sol101_set_info,
                     ) as set_info:
                    self.assertEqual(server._search_solutions("", "cf", -1), [])
                    read_record.assert_not_called()

                    self.assertEqual(
                        [item["title"] for item in server._search_solutions("ceiling", "cf", 30)],
                        ["First"],
                    )
                    self.assertEqual(read_record.call_count, 2)
                    self.assertEqual(set_info.call_count, 1)

                    self.assertEqual(
                        [item["title"] for item in server._search_solutions("scores", "cf", 30)],
                        ["Second"],
                    )
                    self.assertEqual(read_record.call_count, 2)

                    original_stat = second.stat()
                    replacement = docs / "replacement.tmp"
                    replacement.write_text("# Second\n\nunique token", encoding="utf-8")
                    os.utime(
                        replacement,
                        ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns),
                    )
                    replacement.replace(second)
                    replaced_stat = second.stat()
                    self.assertEqual(replaced_stat.st_size, original_stat.st_size)
                    self.assertEqual(replaced_stat.st_mtime_ns, original_stat.st_mtime_ns)
                    self.assertNotEqual(replaced_stat.st_ino, original_stat.st_ino)
                    self.assertEqual(
                        [item["title"] for item in server._search_solutions("unique token", "cf", 30)],
                        ["Second"],
                    )
                    self.assertEqual(read_record.call_count, 3)
            finally:
                server._cached_solution_record.cache_clear()

    def test_image_proxy_serves_without_auth_and_rejects_private_hosts(self):
        server.AUTH_KEYS = {"teacher": "secret"}
        self.assertIsNone(server._image_proxy_allowed("http://127.0.0.1/private.png"))
        image_url = "https://raw.githubusercontent.com/GMyhf/img/main/img/1779708912.png"
        with patch("vibe_cs101.server._cached_image", return_value=(b"image-body", "image/png")) as cached:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/api/image?url={quote(image_url, safe='')}"
            ) as resp:
                self.assertEqual(resp.status, 200)
                self.assertEqual(resp.headers.get_content_type(), "image/png")
                self.assertEqual(resp.read(), b"image-body")
        cached.assert_called_once_with(image_url)

    def test_image_proxy_falls_back_to_jsdelivr_for_github_raw(self):
        image_url = "https://raw.githubusercontent.com/GMyhf/img/main/img/1779708912.png"

        def fake_fetch(url):
            if url == image_url:
                raise urllib.error.URLError("dns")
            self.assertEqual(url, "https://cdn.jsdelivr.net/gh/GMyhf/img@main/img/1779708912.png")
            return b"image-body", "image/png"

        with tempfile.TemporaryDirectory() as tmp, \
                patch("vibe_cs101.server.IMAGE_CACHE_DIR", Path(tmp)), \
                patch("vibe_cs101.server._fetch_image_url", side_effect=fake_fetch):
            body, ctype = server._cached_image(image_url)
        self.assertEqual(body, b"image-body")
        self.assertEqual(ctype, "image/png")

    def test_sol101_static_route_serves_built_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            dist = Path(tmp)
            (dist / "index.html").write_text("sol101 home", encoding="utf-8")
            (dist / "assets").mkdir()
            (dist / "assets" / "app.js").write_text("console.log('ok')", encoding="utf-8")
            with patch("vibe_cs101.server.SOL101_DIST_DIR", dist):
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/sol101/") as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("sol101 home", resp.read().decode())
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/sol101/assets/app.js") as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("text/javascript", resp.headers.get("Content-Type", ""))

    def test_remote_serve_requires_auth_key(self):
        with patch("vibe_cs101.server.load_auth_keys", return_value={}):
            with self.assertRaises(SystemExit):
                server.serve(host="0.0.0.0", port=0)

    def test_remote_serve_warns_to_enable_https(self):
        class FakeHTTPServer:
            def __init__(self, server_address, handler_class):
                self.server_address = server_address
                self.handler_class = handler_class
                self.socket = object()

            def serve_forever(self):
                return None

            def server_close(self):
                return None

        out = StringIO()
        with patch("vibe_cs101.server.load_auth_keys", return_value={"alice": "secret"}), \
             patch("vibe_cs101.server.ThreadingHTTPServer", FakeHTTPServer), \
             patch("sys.stdout", out):
            server.serve(host="0.0.0.0", port=8101)

        self.assertIn("通过 --tls-cert/--tls-key 或反向代理", out.getvalue())
        self.assertIn("启用 HTTPS", out.getvalue())


if __name__ == "__main__":
    unittest.main()
