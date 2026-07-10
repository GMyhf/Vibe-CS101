import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibe_cs101 import journal, store
from vibe_cs101.tools import MAX_SECTION_CHARS, TOOL_SCHEMAS, run_tool


class ToolContextTests(unittest.TestCase):
    def test_search_limit_is_declared_and_enforced(self):
        search_schema = next(
            item["function"] for item in TOOL_SCHEMAS
            if item["function"]["name"] == "search_materials"
        )
        limit_schema = search_schema["parameters"]["properties"]["limit"]
        self.assertEqual(limit_schema["minimum"], 1)
        self.assertEqual(limit_schema["maximum"], store.MAX_SEARCH_RESULTS)

        with patch("vibe_cs101.tools.store.search") as search:
            for limit in (-1, 0, store.MAX_SEARCH_RESULTS + 1, 1.9, True, "2", None):
                result = json.loads(
                    run_tool("search_materials", json.dumps({"query": "dp", "limit": limit}))
                )
                self.assertIn("limit 必须", result["error"])
            search.assert_not_called()

    def test_record_mistake_uses_context_journal_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "alice.db"
            result = json.loads(
                run_tool(
                    "record_mistake",
                    json.dumps(
                        {
                            "problem": "OpenJudge 26977",
                            "course": "cs101",
                            "tags": "单调栈",
                            "link": "http://cs101.openjudge.cn/practice/26977/",
                        }
                    ),
                    {"journal_db": db},
                )
            )

            self.assertEqual(result["recorded"]["problem"], "OpenJudge 26977")
            self.assertEqual(result["recorded"]["link"], "http://cs101.openjudge.cn/practice/26977/")
            self.assertEqual(len(journal.list_mistakes(db_path=db)), 1)

    def test_review_mistakes_uses_context_journal_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bob.db"
            journal.add_mistake("Bob problem", db_path=db)

            result = json.loads(run_tool("review_mistakes", '{"view":"all"}', {"journal_db": db}))

            self.assertEqual([m["problem"] for m in result["mistakes"]], ["Bob problem"])

    def test_read_section_truncates_long_content(self):
        section = {
            "section_id": 1,
            "source": "test",
            "course": "cs101",
            "kind": "courseware",
            "file": "x.md",
            "title": "Long",
            "content": "a" * (MAX_SECTION_CHARS + 10),
        }
        with patch("vibe_cs101.tools.store.get_section", return_value=section):
            result = json.loads(run_tool("read_section", '{"section_id":1}'))

        self.assertTrue(result["truncated"])
        self.assertLess(len(result["content"]), MAX_SECTION_CHARS + 120)
        self.assertIn("内容已截断", result["content"])

    def test_read_section_limit_configurable_via_env(self):
        section = {
            "section_id": 1,
            "source": "test",
            "course": "cs101",
            "kind": "courseware",
            "file": "x.md",
            "title": "Long",
            "content": "a" * 300,
        }
        with patch("vibe_cs101.tools.store.get_section", return_value=section), \
             patch.dict("os.environ", {"VIBE_CS101_MAX_SECTION_CHARS": "100"}):
            result = json.loads(run_tool("read_section", '{"section_id":1}'))
        self.assertTrue(result["truncated"])
        self.assertIn("只返回前 100 字", result["content"])
        # 放宽后不截断
        with patch("vibe_cs101.tools.store.get_section", return_value=section), \
             patch.dict("os.environ", {"VIBE_CS101_MAX_SECTION_CHARS": "1000"}):
            result = json.loads(run_tool("read_section", '{"section_id":1}'))
        self.assertNotIn("truncated", result)


if __name__ == "__main__":
    unittest.main()
