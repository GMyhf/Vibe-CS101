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
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].title, "dp > 动态规划入门")
        self.assertIn("动态规划", hits[0].snippet.replace(" ", ""))

    def test_english_search(self):
        hits = store.search("dijkstra priority queue", db_path=self.db)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].course, "cs201")

    def test_course_filter(self):
        self.assertEqual(store.search("dp", course="cs201", db_path=self.db), [])
        # both cs101 rows mention "dp" (title of one, content of the other)
        self.assertEqual(len(store.search("dp", course="cs101", db_path=self.db)), 2)

    def test_fts_syntax_injection_is_safe(self):
        self.assertEqual(store.search('") OR (1', db_path=self.db), [])
        store.search("NEAR/3 AND", db_path=self.db)  # must not raise

    def test_get_section_roundtrip(self):
        hit = store.search("动态规划", db_path=self.db)[0]
        section = store.get_section(hit.section_id, db_path=self.db)
        self.assertIsNotNone(section)
        self.assertIn("精妙", section["content"])

    def test_empty_query(self):
        self.assertEqual(store.search("", db_path=self.db), [])
        self.assertEqual(store.search("   ", db_path=self.db), [])


if __name__ == "__main__":
    unittest.main()
