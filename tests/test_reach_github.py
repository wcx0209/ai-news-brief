import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from reach_github import parse_trending_markdown, read_trending


def response(url, text, raw=None):
    return {'ok': True, 'items': [{'url': url, 'text': text, 'raw': raw or {},
                                 'published_at': '2010-01-01T00:00:00Z'}]}


class ReachGitHubTests(unittest.TestCase):
    def test_heading_links_only_unique_and_ranked(self):
        text = ('[Explore](https://github.com/explore)\n[Topics](https://github.com/topics/ai)\n'
                '## [NVIDIA / auto-ontology](https://github.com/NVIDIA/auto-ontology)\n'
                '[NVIDIA/auto-ontology](https://github.com/NVIDIA/auto-ontology)\n'
                '[A / B](/A/B)\n[A/B](https://evil.example/A/B)')
        repos = parse_trending_markdown(text)
        self.assertEqual([(r['owner'], r['repo'], r['rank']) for r in repos], [('NVIDIA', 'auto-ontology', 1), ('A', 'B', 2)])

    def test_real_client_seam_reads_both_page_and_repo_without_creation_date(self):
        client = MagicMock()
        url = 'https://github.com/trending?since=weekly'
        client.read_web.return_value = response(url, '## [A / B](https://github.com/A/B)')
        client.read_github.return_value = response('https://github.com/A/B', 'README', {'stargazers_count': 123})
        repos, error = read_trending(client, url, 2)
        self.assertIsNone(error)
        self.assertEqual(repos[0]['stars'], 123)
        self.assertNotIn('published_at', repos[0])
        self.assertEqual(repos[0]['readme_text'], 'README')
        client.read_github.assert_called_once_with('https://github.com/A/B')

    def test_failed_or_wrong_metadata_does_not_reset_star_count(self):
        for result in ({'ok': False}, response('https://github.com/A/C', 'bad', {'stargazers_count': 99}),
                       response('https://github.com/A/B', 'README')):
            client = MagicMock()
            url = 'https://github.com/trending?since=weekly'
            client.read_web.return_value = response(url, '[A/B](https://github.com/A/B)')
            client.read_github.return_value = result
            repos, error = read_trending(client, url, 2)
            self.assertFalse(repos)
            self.assertIsNotNone(error)

    def test_blocked_trending_does_not_fallback_or_read_repos(self):
        client = MagicMock()
        client.read_web.return_value = {'ok': False, 'error': {'code': 'PLATFORM_BLOCKED'}}
        self.assertEqual(read_trending(client, 'https://github.com/trending', 2), ([], 'PLATFORM_BLOCKED'))
        client.read_github.assert_not_called()


if __name__ == '__main__':
    unittest.main()
