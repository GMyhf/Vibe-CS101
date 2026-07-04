import unittest

from vibe_cs101.indexer import build_match_query, cjk_space, split_markdown


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


if __name__ == "__main__":
    unittest.main()
