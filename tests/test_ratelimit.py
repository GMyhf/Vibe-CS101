import time
import unittest
from unittest.mock import patch

from vibe_cs101.ratelimit import RateLimiter, from_env


class RateLimiterTests(unittest.TestCase):
    def test_allows_up_to_limit_then_blocks(self):
        rl = RateLimiter(3, window_s=60)
        self.assertEqual(rl.hit("u"), 0.0)
        self.assertEqual(rl.hit("u"), 0.0)
        self.assertEqual(rl.hit("u"), 0.0)
        self.assertGreater(rl.hit("u"), 0.0)

    def test_keys_are_independent(self):
        rl = RateLimiter(1, window_s=60)
        self.assertEqual(rl.hit("a"), 0.0)
        self.assertEqual(rl.hit("b"), 0.0)
        self.assertGreater(rl.hit("a"), 0.0)

    def test_window_expiry_frees_slots(self):
        rl = RateLimiter(1, window_s=0.05)
        self.assertEqual(rl.hit("u"), 0.0)
        self.assertGreater(rl.hit("u"), 0.0)
        time.sleep(0.06)
        self.assertEqual(rl.hit("u"), 0.0)

    def test_retry_after_is_non_consuming(self):
        rl = RateLimiter(2, window_s=60)
        rl.hit("u")
        self.assertEqual(rl.retry_after("u"), 0.0)  # 未超限
        rl.hit("u")
        self.assertGreater(rl.retry_after("u"), 0.0)  # 已满
        # retry_after 不应记入次数：清空后仍只有 2 条记录
        self.assertGreater(rl.retry_after("u"), 0.0)

    def test_zero_limit_means_unlimited(self):
        rl = RateLimiter(0)
        for _ in range(100):
            self.assertEqual(rl.hit("u"), 0.0)
        self.assertEqual(rl.retry_after("u"), 0.0)

    def test_from_env_parsing(self):
        with patch.dict("os.environ", {"X_RATE": "5/30"}):
            rl = from_env("X_RATE", "10/60")
            self.assertEqual((rl.limit, rl.window_s), (5, 30.0))
        with patch.dict("os.environ", {}, clear=False):
            rl = from_env("X_RATE_MISSING", "10/60")
            self.assertEqual((rl.limit, rl.window_s), (10, 60.0))
        with patch.dict("os.environ", {"X_RATE": "7"}):
            rl = from_env("X_RATE", "10/60")
            self.assertEqual((rl.limit, rl.window_s), (7, 60.0))
        with patch.dict("os.environ", {"X_RATE": "abc"}):
            with self.assertRaises(ValueError):
                from_env("X_RATE", "10/60")


if __name__ == "__main__":
    unittest.main()
