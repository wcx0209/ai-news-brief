import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import MagicMock, patch

spec = importlib.util.spec_from_file_location('collector_retry', Path(__file__).resolve().parents[1] / 'scripts/retry_collector_failures.py')
retry = importlib.util.module_from_spec(spec)
spec.loader.exec_module(retry)


class CollectorRetryTests(unittest.TestCase):
    def test_targets_are_bounded_exact_public_urls(self):
        for value in ('[]', '{}', '["http://127.0.0.1/x"]', '["file:///private/x"]', '[null]', '["https://x.example/ x"]'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                retry.validate_urls(value)
        self.assertEqual(retry.validate_urls('["https://example.com/article/","https://example.com/article/"]'), ['https://example.com/article/'])

    def test_local_repair_fails_before_database_or_target_processing(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), patch.object(retry, 'validate_urls') as validate:
            with self.assertRaises(SystemExit):
                retry.main()
            validate.assert_not_called()

    def test_update_is_parameterized_and_excludes_stored_articles(self):
        database = MagicMock()
        cursor = database._get_connection.return_value.__enter__.return_value.cursor.return_value
        cursor.fetchall.return_value = [('https://example.com/failed/',)]
        urls = ['https://example.com/failed/']
        self.assertEqual(retry.mark_retryable(database, urls), urls)
        sql, params = cursor.execute.call_args.args
        self.assertEqual(params, (urls,))
        self.assertIn('NOT EXISTS (SELECT 1 FROM articles', sql)
        self.assertEqual(sql.split('SET ')[1].split('WHERE')[0].strip(), 'next_fetch_at = NOW()')
        self.assertNotIn('DELETE', sql)
        self.assertNotIn('INSERT', sql)


if __name__ == '__main__':
    unittest.main()
