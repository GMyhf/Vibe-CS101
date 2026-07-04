import tempfile
import unittest
from pathlib import Path

from vibe_cs101 import users


class UsersTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "users.db"

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_and_verify(self):
        key = users.add_user("alice", db_path=self.db)
        self.assertGreaterEqual(len(key), 24)
        self.assertEqual(users.verify_key(key, db_path=self.db), "alice")
        self.assertIsNone(users.verify_key("wrong-key", db_path=self.db))

    def test_key_is_not_stored_in_plaintext(self):
        key = users.add_user("alice", key="my-secret-key", db_path=self.db)
        blob = self.db.read_bytes()
        self.assertNotIn(key.encode(), blob)

    def test_duplicate_add_raises(self):
        users.add_user("alice", db_path=self.db)
        with self.assertRaises(ValueError):
            users.add_user("alice", db_path=self.db)

    def test_invalid_name_raises(self):
        for bad in ("", "a b", "汉字", "x" * 33, "a/b"):
            with self.assertRaises(ValueError):
                users.add_user(bad, db_path=self.db)

    def test_reset_invalidates_old_key(self):
        old = users.add_user("alice", db_path=self.db)
        new = users.reset_key("alice", db_path=self.db)
        self.assertNotEqual(old, new)
        self.assertIsNone(users.verify_key(old, db_path=self.db))
        self.assertEqual(users.verify_key(new, db_path=self.db), "alice")
        with self.assertRaises(ValueError):
            users.reset_key("nobody", db_path=self.db)

    def test_remove_and_list(self):
        users.add_user("alice", db_path=self.db)
        users.add_user("bob", db_path=self.db)
        self.assertEqual([u["name"] for u in users.list_users(db_path=self.db)], ["alice", "bob"])
        self.assertTrue(users.remove_user("alice", db_path=self.db))
        self.assertFalse(users.remove_user("alice", db_path=self.db))
        self.assertEqual([u["name"] for u in users.list_users(db_path=self.db)], ["bob"])

    def test_has_users_does_not_create_db_file(self):
        self.assertFalse(users.has_users(db_path=self.db))
        self.assertFalse(self.db.exists())
        self.assertIsNone(users.verify_key("k", db_path=self.db))
        self.assertFalse(self.db.exists())
        users.add_user("alice", db_path=self.db)
        self.assertTrue(users.has_users(db_path=self.db))

    def test_verify_updates_last_seen(self):
        key = users.add_user("alice", db_path=self.db)
        self.assertIsNone(users.list_users(db_path=self.db)[0]["last_seen"])
        users.verify_key(key, db_path=self.db)
        self.assertIsNotNone(users.list_users(db_path=self.db)[0]["last_seen"])


if __name__ == "__main__":
    unittest.main()
