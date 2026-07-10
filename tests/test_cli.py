import argparse
import unittest
from io import StringIO
from unittest.mock import patch

from vibe_cs101 import store
from vibe_cs101.cli import _search_limit, main


class SearchLimitTests(unittest.TestCase):
    def test_accepts_bounds(self):
        self.assertEqual(_search_limit("1"), 1)
        self.assertEqual(
            _search_limit(str(store.MAX_SEARCH_RESULTS)),
            store.MAX_SEARCH_RESULTS,
        )

    def test_rejects_invalid_values(self):
        for value in ("-1", "0", str(store.MAX_SEARCH_RESULTS + 1), "many"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    _search_limit(value)

    def test_main_passes_default_and_upper_bound(self):
        with patch("vibe_cs101.cli.store.search", return_value=[]) as search, \
             patch("sys.stdout", new_callable=StringIO):
            self.assertEqual(main(["search", "dp"]), 1)
            self.assertEqual(search.call_args.kwargs["limit"], 8)

            self.assertEqual(
                main(["search", "dp", "--limit", str(store.MAX_SEARCH_RESULTS)]),
                1,
            )
            self.assertEqual(search.call_args.kwargs["limit"], store.MAX_SEARCH_RESULTS)


if __name__ == "__main__":
    unittest.main()
