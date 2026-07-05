import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vibe_cs101 import config, indexer
from vibe_cs101.indexer import build_any_match_query, build_match_query, cjk_space, split_markdown


class CjkSpaceTests(unittest.TestCase):
    def test_inserts_token_boundaries(self):
        self.assertEqual(cjk_space("动态规划dp").split(), ["动", "态", "规", "划", "dp"])


class MatchQueryTests(unittest.TestCase):
    def test_mixed_language(self):
        q = build_match_query("动态规划 monotonic stack")
        self.assertIn('"动 态 规 划"', q)
        self.assertIn('"monotonic"', q)
        self.assertIn('"stack"', q)

    def test_strips_fts_syntax(self):
        q = build_match_query('") OR (1 -- NEAR/3')
        self.assertNotIn("(", q)
        self.assertNotIn(")", q)

    def test_any_match_query_ors_terms(self):
        q = build_any_match_query("课程内容 学习路线")
        self.assertIn(" OR ", q)
        self.assertIn('"课 程 内 容"', q)
        self.assertIn('"学 习 路 线"', q)


class SplitMarkdownTests(unittest.TestCase):
    def test_heading_paths(self):
        text = "intro\n## A\nbody a\n### A.1\nbody a1\n## B\nbody b\n"
        titles = [t for t, _ in split_markdown(text, "doc")]
        self.assertEqual(titles, ["doc", "doc > A", "doc > A > A.1", "doc > B"])

    def test_ignores_headings_in_code_fence(self):
        text = "## Real\n```python\n# not a heading\nx = 1\n```\ntail\n"
        sections = split_markdown(text, "doc")
        self.assertEqual(len(sections), 1)
        self.assertIn("# not a heading", sections[0][1])

    def test_chunks_oversized_sections(self):
        text = "## Big\n" + "x" * 20000
        sections = split_markdown(text, "doc")
        self.assertEqual(len(sections), 3)
        self.assertTrue(sections[1][0].endswith("(part 2)"))


class RemoteSourceIndexTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.original_dir = Path(self._tmp.name) / "original"
        self.src = config.REMOTE_SOURCES[0]

    def tearDown(self):
        self._tmp.cleanup()

    def _with_tmp_original(self):
        return patch.multiple(
            "vibe_cs101.config",
            ORIGINAL_DIR=self.original_dir,
        )

    def test_iter_sections_prefers_structured_remote_path(self):
        structured = self.original_dir / self.src.github_repo / self.src.upstream_filename
        legacy = self.original_dir / f"{self.src.name}.md"
        structured.parent.mkdir(parents=True)
        structured.write_text("## New\nstructured body", encoding="utf-8")
        legacy.write_text("## Old\nlegacy body", encoding="utf-8")
        with self._with_tmp_original(), patch.object(indexer, "LOCAL_SOURCES", []):
            sections = indexer.iter_sections()
        self.assertEqual(sections[0].file, "2024fall-cs101/2024fall_LeetCode_problems.md")
        self.assertIn("structured body", sections[0].content)

    def test_iter_sections_reads_legacy_remote_path(self):
        legacy = self.original_dir / f"{self.src.name}.md"
        legacy.parent.mkdir(parents=True)
        legacy.write_text("## Legacy\nlegacy body", encoding="utf-8")
        with self._with_tmp_original(), patch.object(indexer, "LOCAL_SOURCES", []):
            sections = indexer.iter_sections()
        self.assertEqual(sections[0].file, "leetcode.md")
        self.assertIn("legacy body", sections[0].content)


if __name__ == "__main__":
    unittest.main()
