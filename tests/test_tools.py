import json
import tempfile
import unittest
from pathlib import Path

from vibe_cs101 import journal
from vibe_cs101.tools import run_tool


class ToolContextTests(unittest.TestCase):
    def test_record_mistake_uses_context_journal_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "alice.db"
            result = json.loads(
                run_tool(
                    "record_mistake",
                    json.dumps({"problem": "OpenJudge 26977", "course": "cs101", "tags": "单调栈"}),
                    {"journal_db": db},
                )
            )

            self.assertEqual(result["recorded"]["problem"], "OpenJudge 26977")
            self.assertEqual(len(journal.list_mistakes(db_path=db)), 1)

    def test_review_mistakes_uses_context_journal_db(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "bob.db"
            journal.add_mistake("Bob problem", db_path=db)

            result = json.loads(run_tool("review_mistakes", '{"view":"all"}', {"journal_db": db}))

            self.assertEqual([m["problem"] for m in result["mistakes"]], ["Bob problem"])


if __name__ == "__main__":
    unittest.main()
