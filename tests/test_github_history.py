"""Trending popularity must never manufacture another publication event.

AST-loaded collector/database functions keep these regressions independent of
local database, browser, scraping or LLM dependencies. Requests are mocked.
"""

import ast
from datetime import datetime, timedelta, timezone
import importlib.util
import json
import logging
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from editorial_insights import enrich_item, is_github_trending

spec = importlib.util.spec_from_file_location("history_public_feed", ROOT / "scripts/export_public_feed.py")
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)


def load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    body = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    module = ast.fix_missing_locations(ast.Module(body=body, type_ignores=[]))
    exec(compile(module, str(path), "exec"), namespace)
    return namespace


class TrendingCollectorHistoryTests(unittest.TestCase):
    def setUp(self):
        self.namespace = load_functions(ROOT / "src/github_fetcher.py", {"_trending_fetched_today", "is_github_trending_source", "fetch_github_trending"}, {
            "datetime": datetime, "timezone": timezone, "logging": logging,
            "urlparse": urlparse, "ConfigLoader": SimpleNamespace(get_instance=lambda: {"fetching": {"github_trending": {"enabled": True}}}),
        })
        self.database = MagicMock()
        self.database.get_or_create_rss_source.return_value = 7
        self.database.get_rss_source_by_id.return_value = {"last_fetch_at": None}
        self.database.get_article_by_url.return_value = {
            "id": "permanent-id", "category": "open_source", "importance_score": 88,
            "published_at": "2026-11-08T12:47:26Z", "source_published_at": None,
            "created_at": "2026-11-08T12:47:27Z",
            "summary_en": "⭐ 10,000 | Original summary.", "summary_zh": "⭐ 10,000 | 原摘要。",
        }
        self.namespace["_parse_github_trending_page"] = lambda html: [{
            "owner": "NVIDIA", "repo": "auto-ontology", "url": "https://github.com/NVIDIA/auto-ontology",
            "description": "An existing repository", "stars": 11830,
        }]
        self.requests = MagicMock()
        self.requests.get.return_value.text = "A mocked trending page, never a real request"

    def test_repeat_listing_updates_popularity_without_any_timestamp_or_score(self):
        engine, vectors, stats = MagicMock(), MagicMock(), MagicMock()
        with patch.dict(sys.modules, {"requests": self.requests}):
            self.assertEqual(self.namespace["fetch_github_trending"](self.database, engine, vectors, stats), 1)
        kwargs = self.database.update_article_refresh.call_args.kwargs
        self.assertEqual(kwargs, {"article_id": "permanent-id", "summary_en": "⭐ 11,830 | Original summary.", "summary_zh": "⭐ 11,830 | 原摘要。", "momentum_score": 100})
        self.database.get_articles_count_by_category_published_today.assert_not_called()
        self.database.add_article.assert_not_called()
        self.database.delete_articles_by_category_excluding_urls.assert_not_called()
        vectors.delete_articles.assert_not_called()
        engine.summarize_content.assert_not_called()
        self.database.update_rss_source_fetch_time.assert_called_once_with(7)

    def test_daily_guard_uses_source_marker_before_requesting_the_page(self):
        self.database.get_rss_source_by_id.return_value = {"last_fetch_at": datetime.now(timezone.utc)}
        with patch.dict(sys.modules, {"requests": self.requests}):
            self.assertEqual(self.namespace["fetch_github_trending"](self.database, MagicMock(), MagicMock(), MagicMock()), 0)
        self.requests.get.assert_not_called()
        self.database.update_article_refresh.assert_not_called()

    def test_existing_non_trending_article_is_not_resummarized(self):
        self.database.get_article_by_url.return_value["category"] = "research"
        engine = MagicMock()
        with patch.dict(sys.modules, {"requests": self.requests}):
            self.namespace["fetch_github_trending"](self.database, engine, MagicMock(), MagicMock())
        engine.summarize_content.assert_not_called()
        self.database.add_article.assert_not_called()
        self.database.update_article_refresh.assert_not_called()

    def test_source_marker_is_utc_and_tolerates_invalid_legacy_values(self):
        now = datetime(2026, 11, 12, 1, tzinfo=timezone.utc)
        check = self.namespace["_trending_fetched_today"]
        self.assertTrue(check("2026-11-12T08:01:00+08:00", now))
        self.assertFalse(check("2026-11-12T00:30:00+08:00", now))
        self.assertFalse(check(None, now))
        self.assertFalse(check("not-a-date", now))

    def test_only_virtual_trending_source_is_excluded_from_generic_rss(self):
        check = self.namespace["is_github_trending_source"]
        self.assertTrue(check({"name": "GitHub Trending", "url": "https://github.com/trending?since=weekly"}))
        for url in ("https://github.com/NVIDIA/auto-ontology/releases.atom", "https://github.com/trending/releases.atom", "https://github.com.evil.example/trending", "https://github.com@evil.example/trending"):
            self.assertFalse(check({"name": "GitHub Trending", "url": url}))
        tree = ast.parse((ROOT / "src/pipeline_runner.py").read_text(encoding="utf-8"))
        guarded = [node for node in ast.walk(tree) if isinstance(node, ast.If) and isinstance(node.test, ast.Call) and isinstance(node.test.func, ast.Name) and node.test.func.id == "is_github_trending_source"]
        self.assertTrue(any(any(isinstance(child, ast.Continue) for child in guard.body) for guard in guarded))

    def test_collector_has_no_dropoff_delete_path(self):
        tree = ast.parse((ROOT / "src/github_fetcher.py").read_text(encoding="utf-8"))
        collector = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "fetch_github_trending")
        methods = {node.func.attr for node in ast.walk(collector) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertNotIn("delete_articles_by_category_excluding_urls", methods)
        self.assertNotIn("delete_articles", methods)

    def test_database_refresh_sql_never_mutates_dates_or_editorial_importance(self):
        tree = ast.parse((ROOT / "src/user_db.py").read_text(encoding="utf-8"))
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "UserDatabase")
        method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == "update_article_refresh")
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])), "database_refresh", "exec"), namespace)
        database = MagicMock()
        cursor = database._get_connection.return_value.__enter__.return_value.cursor.return_value
        cursor.rowcount = 1
        self.assertTrue(namespace["update_article_refresh"](database, "id", "English", "中文", 90))
        sql, params = cursor.execute.call_args.args
        for name in ("published_at", "source_published_at", "created_at", "importance_score"):
            self.assertNotIn(name, sql)
        self.assertEqual(params, (90, "English", "中文", "id"))


class TrendingPublicationTests(unittest.TestCase):
    def item(self, source="GitHub Trending"):
        return {"id": "id", "url": "https://github.com/NVIDIA/auto-ontology", "source": source,
                "importance": 100, "category": "open_source", "domain": "ai",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "source_published_at": datetime.now(timezone.utc).isoformat(),
                "site_published_at": "2026-11-08T12:47:27Z", "en": {"title": "NVIDIA prototype repository", "summary": "A project"}, "zh": {}}

    def test_trending_is_excluded_even_above_threshold_but_real_releases_remain(self):
        trending, release = self.item(), self.item("NVIDIA Releases")
        release["id"] = "release"
        release["url"] += "/releases/tag/v2"
        selected = feed.merge_recent_items([trending, release], [], 60, 2, 2, 70, 65)
        self.assertEqual([item["id"] for item in selected], ["release"])
        rows = [{"id": "trending", "source_name": "GitHub Trending", "title": "AI project", "category": "open_source", "importance_score": 100},
                {"id": "release", "source_name": "NVIDIA Releases", "title": "AI model release", "category": "open_source", "importance_score": 90}]
        self.assertEqual([row["id"] for row in feed.select_balanced_rows(rows, 60, 2, 2, 70, 65)], ["release"])

    def test_first_seen_date_does_not_use_refreshed_or_source_publication_dates(self):
        record = enrich_item(self.item())
        self.assertEqual(record["date_basis"], "first_seen")
        self.assertEqual(record["first_seen_at"], "2026-11-08T12:47:27Z")
        self.assertEqual(record["evidence"]["stage"], "unspecified")
        record.pop("site_published_at")
        record.pop("first_seen_at")
        self.assertIsNone(enrich_item(record)["first_seen_at"])
        record["created_at"] = datetime(2026, 11, 8, 12, 47, 27, tzinfo=timezone.utc)
        self.assertEqual(enrich_item(record)["first_seen_at"], "2026-11-08T12:47:27Z")
        self.assertNotIn("date_basis", enrich_item(self.item("NVIDIA Releases")))

    def test_carry_forward_and_offline_export_both_remove_trending(self):
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / "source.json", Path(folder) / "output.json"
            release = self.item("NVIDIA Releases")
            release["id"] = "release"
            source.write_text(json.dumps({"generated_at": "unchanged-collection-time", "items": [self.item(), release]}))
            self.assertEqual([item["id"] for item in feed.load_previous_items(source)], ["release"])
            subprocess.run([sys.executable, "-S", str(ROOT / "scripts/export_public_feed.py"), "--input-json", str(source), "--output", str(output)], capture_output=True, check=True)
            result = json.loads(output.read_text())
            self.assertEqual([item["id"] for item in result["items"]], ["release"])
            self.assertEqual(result["generated_at"], "unchanged-collection-time")


if __name__ == "__main__":
    unittest.main()
