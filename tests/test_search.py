import tempfile
import unittest
from pathlib import Path

from vibe_cs101 import store
from vibe_cs101.indexer import cjk_space, connect


class SearchTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "index.db"
        conn = connect(self.db)
        rows = [
            ("2025fall-cs101", "cs101", "courseware", "dp.md", "dp > 动态规划入门",
             "动态规划是一种精妙的算法思想，先接触经典模型。"),
            ("2025fall-cs101", "cs101", "courseware", "dp.md", "dp > 状态转移",
             "状态设计和转移方程是动态规划的核心。"),
            ("openjudge", "cs101", "solutions", "openjudge.md", "OJ > 02533 Fibonacci",
             "递推求斐波那契数列，注意 dp 数组初始化。"),
            ("2026spring-cs201", "cs201", "courseware", "graph.md", "graph > Dijkstra",
             "Dijkstra shortest path with a priority queue."),
        ]
        with conn:
            for src, course, kind, file, title, content in rows:
                cur = conn.execute(
                    "INSERT INTO sections (source, course, kind, file, title, content) VALUES (?,?,?,?,?,?)",
                    (src, course, kind, file, title, content),
                )
                conn.execute(
                    "INSERT INTO sections_fts (rowid, title_t, content_t) VALUES (?,?,?)",
                    (cur.lastrowid, cjk_space(title), cjk_space(content)),
                )
        conn.close()

    def tearDown(self):
        self._tmp.cleanup()

    def test_chinese_search(self):
        hits = store.search("动态规划", db_path=self.db)
        self.assertEqual(len(hits), 2)
        self.assertIn("dp > 动态规划入门", [h.title for h in hits])
        self.assertTrue(any("动态规划" in h.snippet.replace(" ", "") for h in hits))
        self.assertNotIn("[", hits[0].snippet)
        self.assertNotIn("]", hits[0].snippet)

    def test_english_search(self):
        hits = store.search("dijkstra priority queue", db_path=self.db)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].course, "cs201")

    def test_course_filter(self):
        self.assertEqual(store.search("dp", course="cs201", db_path=self.db), [])
        # all cs101 rows either mention "dp" in title/content or source metadata
        self.assertEqual(len(store.search("dp", course="cs101", db_path=self.db)), 3)

    def test_source_allowlist_filter(self):
        hits = store.search("dp", course="cs101", sources=["openjudge"], db_path=self.db)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].source, "openjudge")
        self.assertEqual(store.search("dp", course="cs101", sources=[], db_path=self.db), [])

    def test_broad_query_falls_back_to_any_term(self):
        hits = store.search("动态规划 不存在的学习路线词", course="cs101", db_path=self.db)
        self.assertEqual(len(hits), 2)
        self.assertIn("dp > 动态规划入门", [h.title for h in hits])

    def test_fts_syntax_injection_is_safe(self):
        self.assertEqual(store.search('") OR (1', db_path=self.db), [])
        store.search("NEAR/3 AND", db_path=self.db)  # must not raise

    def test_get_section_roundtrip(self):
        hit = store.search("动态规划", db_path=self.db)[0]
        section = store.get_section(hit.section_id, db_path=self.db)
        self.assertIsNotNone(section)
        self.assertIn("精妙", section["content"])

    def test_get_document_for_section_combines_same_file(self):
        hit = store.search("状态转移", db_path=self.db)[0]
        doc = store.get_document_for_section(hit.section_id, db_path=self.db)

        self.assertIsNotNone(doc)
        self.assertEqual(doc["file"], "dp.md")
        self.assertEqual(doc["section_count"], 2)
        self.assertEqual([s["id"] for s in doc["sections"]], [1, 2])
        self.assertIn("动态规划是一种精妙", doc["content"])
        self.assertIn("状态设计和转移方程", doc["content"])

    def test_empty_query(self):
        self.assertEqual(store.search("", db_path=self.db), [])
        self.assertEqual(store.search("   ", db_path=self.db), [])

    def test_result_limit_has_a_hard_bound(self):
        conn = connect(self.db)
        with conn:
            for i in range(store.MAX_SEARCH_RESULTS + 10):
                title = f"bounded result {i}"
                cur = conn.execute(
                    "INSERT INTO sections (source, course, kind, file, title, content) VALUES (?,?,?,?,?,?)",
                    ("test", "cs101", "courseware", f"{i}.md", title, title),
                )
                conn.execute(
                    "INSERT INTO sections_fts (rowid, title_t, content_t) VALUES (?,?,?)",
                    (cur.lastrowid, title, title),
                )
        conn.close()

        self.assertEqual(store.search("bounded", limit=0, db_path=self.db), [])
        self.assertEqual(store.search("bounded", limit=-1, db_path=self.db), [])
        self.assertEqual(
            len(store.search("bounded", limit=10_000, db_path=self.db)),
            store.MAX_SEARCH_RESULTS,
        )


if __name__ == "__main__":
    unittest.main()
