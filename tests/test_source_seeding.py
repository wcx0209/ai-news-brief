import os
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from user_db import UserDatabase


class SourceSeedingTests(unittest.TestCase):
    def test_bulk_upsert_preserves_source_ids_and_fetch_metadata(self):
        database = UserDatabase.__new__(UserDatabase)
        database._get_connection = MagicMock()
        sources = [("https://example.org/feed", "Example", "Research", "research", 90)]
        with patch("user_db.psycopg2.extras.execute_values", return_value=[(42, "Example")]) as upsert:
            self.assertEqual(database.seed_rss_sources(sources), [(42, "Example")])
        query = upsert.call_args.args[1]
        self.assertIn("ON CONFLICT (url) DO UPDATE", query)
        self.assertNotIn("last_fetch_at =", query)
        self.assertEqual(upsert.call_args.args[2], sources)

    def test_feed_url_migration_updates_in_place_before_upsert(self):
        database = UserDatabase.__new__(UserDatabase)
        database._get_connection = MagicMock()
        cursor = database._get_connection.return_value.__enter__.return_value.cursor.return_value
        with patch("user_db.psycopg2.extras.execute_values", return_value=[]):
            database.seed_rss_sources(
                [("https://example.org/new", "Example", "Research", "research", 90)],
                {"https://example.org/old": "https://example.org/new"},
            )
        query, params = cursor.execute.call_args.args
        self.assertIn("UPDATE rss_sources SET url", query)
        self.assertIn("NOT EXISTS", query)
        self.assertEqual(params, ("https://example.org/new", "https://example.org/old", "https://example.org/new"))


if __name__ == "__main__":
    unittest.main()
