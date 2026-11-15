#!/usr/bin/env python3
"""Mark exact failed URLs retryable in cloud; never delete or alter articles."""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))


def validate_urls(value):
    from source_images import normalize_source_url
    urls = json.loads(value)
    if not isinstance(urls, list) or not 1 <= len(urls) <= 10:
        raise ValueError('Provide a JSON array containing 1–10 exact public URLs')
    if any(not isinstance(url, str) or normalize_source_url(url) != url for url in urls):
        raise ValueError('Every target must be an exact public article URL')
    return list(dict.fromkeys(urls))


def mark_retryable(database, urls):
    """Only existing failed markers; no inserts, source-ID or history changes."""
    with database._get_connection() as connection:
        cursor = connection.cursor()
        cursor.execute('''
            UPDATE fetched_urls AS failed SET next_fetch_at = NOW()
            WHERE failed.url = ANY(%s)
              AND NOT EXISTS (SELECT 1 FROM articles WHERE articles.url = failed.url)
            RETURNING failed.url
        ''', (urls,))
        return [row[0] for row in cursor.fetchall()]


def main():
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise SystemExit('Run this exact-target repair in GitHub Actions only')
    urls = validate_urls(os.environ.get('RETRY_URLS_JSON', ''))
    from user_db import UserDatabase
    updated = mark_retryable(UserDatabase(), urls)
    print(json.dumps({'requested': len(urls), 'retryable_markers': len(updated),
                      'article_writes': 0, 'deletions': 0, 'llm_calls': 0}))


if __name__ == '__main__':
    main()
