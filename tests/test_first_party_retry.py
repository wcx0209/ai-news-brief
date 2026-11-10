import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from pipeline_runner import _article_url_already_processed


class FakeDatabase:
    def __init__(self, stored_article=None, fetched_url=True):
        self.stored_article = stored_article
        self.fetched_url = fetched_url

    def get_article_by_url(self, url):
        return self.stored_article

    def article_url_exists(self, url):
        return self.fetched_url


class FirstPartyRetryTests(unittest.TestCase):
    def test_first_party_retries_when_only_fetched_url_exists(self):
        database = FakeDatabase(stored_article=None, fetched_url=True)
        self.assertFalse(
            _article_url_already_processed(database, "https://official.example/post", True)
        )

    def test_first_party_stops_after_article_is_stored(self):
        database = FakeDatabase(stored_article={"id": "article-1"}, fetched_url=True)
        self.assertTrue(
            _article_url_already_processed(database, "https://official.example/post", True)
        )

    def test_secondary_source_keeps_fetched_url_deduplication(self):
        database = FakeDatabase(stored_article=None, fetched_url=True)
        self.assertTrue(
            _article_url_already_processed(database, "https://media.example/post", False)
        )


if __name__ == "__main__":
    unittest.main()
