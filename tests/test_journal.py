import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from vibe_cs101 import journal


class JournalTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "journal.db"

    def tearDown(self):
        self._tmp.cleanup()

    def add(self, **kw):
        kw.setdefault("problem", "OpenJudge 26977 接雨水")
        kw.setdefault("tags", "单调栈,dp")
        kw.setdefault("course", "cs101")
        return journal.add_mistake(db_path=self.db, **kw)

    def test_add_schedules_first_review_tomorrow(self):
        m = self.add()
        self.assertEqual(m.next_review, (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(m.status, "active")

    def test_add_stores_link(self):
        m = self.add(link="http://cs101.openjudge.cn/practice/02733/")
        self.assertEqual(m.link, "http://cs101.openjudge.cn/practice/02733/")
        loaded = journal.get_mistake(m.id, db_path=self.db)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.link, m.link)

    def test_add_infers_openjudge_link_and_normalizes_tags(self):
        m = self.add(problem="OpenJudge E02733 判断闰年", tags="条件判断、取模，闰年规则 OpenJudge Easy")

        self.assertEqual(m.link, "http://cs101.openjudge.cn/practice/02733/")
        self.assertEqual(m.tags, "条件判断,取模,闰年规则,OpenJudge,Easy")

    def test_existing_db_migrates_link_column(self):
        conn = journal._connect(self.db)
        conn.execute("ALTER TABLE mistakes RENAME TO mistakes_old")
        conn.execute(
            """
            CREATE TABLE mistakes (
                id INTEGER PRIMARY KEY,
                created TEXT NOT NULL,
                problem TEXT NOT NULL,
                course TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '',
                reason TEXT NOT NULL DEFAULT '',
                note TEXT NOT NULL DEFAULT '',
                section_id INTEGER,
                status TEXT NOT NULL DEFAULT 'active',
                interval_idx INTEGER NOT NULL DEFAULT 0,
                next_review TEXT NOT NULL,
                review_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.close()

        m = self.add()

        self.assertEqual(m.link, "http://cs101.openjudge.cn/practice/26977/")

    def test_add_rejects_empty_problem(self):
        with self.assertRaises(ValueError):
            journal.add_mistake("   ", db_path=self.db)

    def test_review_good_advances_interval(self):
        m = self.add()
        m2 = journal.review_mistake(m.id, "good", db_path=self.db)
        self.assertEqual(m2.interval_idx, 1)
        self.assertEqual(m2.next_review, (date.today() + timedelta(days=3)).isoformat())
        self.assertEqual(m2.review_count, 1)

    def test_review_again_resets(self):
        m = self.add()
        journal.review_mistake(m.id, "good", db_path=self.db)
        m3 = journal.review_mistake(m.id, "again", db_path=self.db)
        self.assertEqual(m3.interval_idx, 0)
        self.assertEqual(m3.status, "active")

    def test_mastered_after_all_intervals(self):
        m = self.add()
        for _ in range(len(journal.INTERVALS)):
            m = journal.review_mistake(m.id, "good", db_path=self.db)
        self.assertEqual(m.status, "mastered")

    def test_due_filter_and_tag_filter(self):
        self.add()
        # 新错题明天到期 → 今天不在 due 列表
        self.assertEqual(journal.list_mistakes(due_only=True, db_path=self.db), [])
        self.assertEqual(len(journal.list_mistakes(tag="单调栈", db_path=self.db)), 1)
        self.assertEqual(journal.list_mistakes(tag="图", db_path=self.db), [])

    def test_stats(self):
        m = self.add()
        self.add(problem="LeetCode 42", tags="单调栈")
        for _ in range(len(journal.INTERVALS)):
            journal.review_mistake(m.id, "good", db_path=self.db)
        s = journal.stats(db_path=self.db)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["mastered"], 1)
        self.assertEqual(s["by_tag"]["单调栈"]["total"], 2)
        self.assertEqual(s["by_tag"]["单调栈"]["mastered"], 1)
        self.assertEqual(s["by_course"]["cs101"]["total"], 2)

    def test_delete(self):
        m = self.add()
        self.assertTrue(journal.delete_mistake(m.id, db_path=self.db))
        self.assertFalse(journal.delete_mistake(m.id, db_path=self.db))
        self.assertIsNone(journal.get_mistake(m.id, db_path=self.db))

    def test_user_db_owner_uses_default_journal(self):
        self.assertEqual(journal.user_db(None), journal.JOURNAL_DB)
        self.assertEqual(journal.user_db("owner"), journal.JOURNAL_DB)

    def test_user_db_named_user_gets_separate_file(self):
        self.assertEqual(journal.user_db("alice"), journal.DATA_DIR / "journal-alice.db")


if __name__ == "__main__":
    unittest.main()
