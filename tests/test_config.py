import unittest
from unittest.mock import patch

from vibe_cs101 import config


class AuthConfigTests(unittest.TestCase):
    def test_no_auth_keys_by_default(self):
        with patch("vibe_cs101.config.os.environ", {}), patch("vibe_cs101.config._load_dotenv"):
            self.assertEqual(config.load_auth_keys(), {})

    def test_single_auth_key_uses_owner(self):
        env = {"VIBE_CS101_AUTH_KEY": "secret"}
        with patch("vibe_cs101.config.os.environ", env), patch("vibe_cs101.config._load_dotenv"):
            self.assertEqual(config.load_auth_keys(), {"owner": "secret"})

    def test_multi_auth_keys_parse_named_users(self):
        env = {"VIBE_CS101_AUTH_KEYS": "alice:k1,bob:k2"}
        with patch("vibe_cs101.config.os.environ", env), patch("vibe_cs101.config._load_dotenv"):
            self.assertEqual(config.load_auth_keys(), {"alice": "k1", "bob": "k2"})

    def test_multi_auth_keys_override_single_owner(self):
        env = {"VIBE_CS101_AUTH_KEY": "single", "VIBE_CS101_AUTH_KEYS": "owner:multi,alice:k1"}
        with patch("vibe_cs101.config.os.environ", env), patch("vibe_cs101.config._load_dotenv"):
            self.assertEqual(config.load_auth_keys(), {"owner": "multi", "alice": "k1"})

    def test_multi_auth_keys_reject_bad_pairs(self):
        env = {"VIBE_CS101_AUTH_KEYS": "alice"}
        with patch("vibe_cs101.config.os.environ", env), patch("vibe_cs101.config._load_dotenv"):
            with self.assertRaises(ValueError):
                config.load_auth_keys()

    def test_multi_auth_keys_reject_unsafe_usernames(self):
        env = {"VIBE_CS101_AUTH_KEYS": "../alice:key"}
        with patch("vibe_cs101.config.os.environ", env), patch("vibe_cs101.config._load_dotenv"):
            with self.assertRaises(ValueError):
                config.load_auth_keys()


class RemoteSourcePathTests(unittest.TestCase):
    def test_github_repo_and_filename_come_from_raw_url(self):
        src = config.REMOTE_SOURCES[0]
        self.assertEqual(src.github_repo, "2024fall-cs101")
        self.assertEqual(src.upstream_filename, "2024fall_LeetCode_problems.md")
        self.assertEqual(
            src.original_path.relative_to(config.ORIGINAL_DIR).as_posix(),
            "2024fall-cs101/2024fall_LeetCode_problems.md",
        )


if __name__ == "__main__":
    unittest.main()
