"""Offline provenance/date gates and real-pipeline routing regression tests.

All source readers, database objects, model calls and legacy extractors are
mocked. No test starts a browser, sends a request, or opens a database.
"""

from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from editorial_domains import domain_ids
from reach_content import publication_time, read_entry_content, same_article_url
import pipeline_runner as pipeline


BODY = "A public research announcement with documented methods and results. " * 5
URL = "https://publisher.example.org/news/model?id=7"


def result(*, url=URL, channel="web", kind="web_article", text=BODY,
           published_at=None, code=None):
    return {
        "schema_version": 1, "ok": code is None, "channel": channel, "action": "read",
        "backend": "jina" if code is None else None,
        "items": [] if code else [{"title": "A model announcement", "url": url,
                                    "text": text, "author": None,
                                    "published_at": published_at, "raw": None}],
        "meta": {"content_type": kind, "attempts": []},
        "error": {"code": code, "message": "Public platform stopped this read"} if code else None,
    }


class FakeCollector:
    backend = "agent_reach"

    def __init__(self, response=None):
        self.response = response if response is not None else result()
        self.read_calls = []
        self.feed_calls = []
        self.closed = False

    def read_entry(self, entry):
        self.read_calls.append(deepcopy(entry))
        return deepcopy(self.response)

    def parse_feed(self, source):
        self.feed_calls.append(dict(source))
        return {"entries": [], "error": None, "feed_config": source}

    def close(self):
        self.closed = True


class ReachContentTests(unittest.TestCase):
    def test_publication_time_converts_offsets_without_using_current_time(self):
        self.assertEqual(publication_time("2026-11-14T08:00:00+08:00"),
                         datetime(2026, 11, 14, tzinfo=timezone.utc))
        self.assertEqual(publication_time(datetime(2026, 11, 14)),
                         datetime(2026, 11, 14, tzinfo=timezone.utc))
        for value in (None, "", "unknown", "not-a-date", "2026-99-99", object()):
            with self.subTest(value=repr(value)):
                self.assertIsNone(publication_time(value))

    def test_url_matching_allows_tracking_but_preserves_query_article_identity(self):
        self.assertTrue(same_article_url("http://www.example.org/news?id=7&utm_source=rss#summary",
                                         "https://example.org/news/?id=7&gclid=tracking"))
        # Be conservative about non-tracking query order; duplicate IDs can
        # identify a different article when a publisher accepts the last value.
        self.assertFalse(same_article_url("https://example.org/news?id=1&id=2",
                                          "https://example.org/news?id=2&id=1"))
        self.assertFalse(same_article_url("https://example.org/#/news/1", "https://example.org/#/news/2"))
        self.assertFalse(same_article_url("https://example.org/#!/news/1", "https://example.org/#!/news/2"))
        self.assertTrue(same_article_url("https://github.com/Owner/Repository", "https://github.com/owner/repository/"))
        for other in ("https://example.org/news?id=8", "https://example.org/other?id=7",
                      "https://other.example.org/news?id=7", "file:///news?id=7",
                      "https://user:password@example.org/news?id=7", "https://example.org:9021/news?id=7", None):
            self.assertFalse(same_article_url("https://example.org/news?id=7", other))

    def test_source_date_and_original_link_are_not_overwritten_by_reader(self):
        entry = {"link": URL, "published_at": "2026-11-14T01:00:00Z", "date_basis": "source_published"}
        collector = FakeCollector(result(published_at="2026-11-15T02:00:00Z"))
        text, backend, error = read_entry_content(collector, entry)
        self.assertEqual((text, backend, error), (BODY.strip(), "agent_reach:jina", None))
        self.assertEqual(entry["published_at"], "2026-11-14T01:00:00Z")
        self.assertEqual(entry["date_basis"], "source_published")
        self.assertEqual(entry["link"], URL)

    def test_missing_source_date_can_use_matching_web_publication_metadata(self):
        entry = {"link": URL, "published_at": None}
        collector = FakeCollector(result(published_at="2026-11-14T08:00:00+08:00"))
        _, _, error = read_entry_content(collector, entry)
        self.assertIsNone(error)
        self.assertEqual(entry["published_at"], "2026-11-14T00:00:00+00:00")
        self.assertEqual(entry["date_basis"], "source_reader_published")

    def test_missing_reader_metadata_never_becomes_a_new_publication(self):
        for metadata in (None, "bad date"):
            entry = {"link": URL, "published_at": None}
            read_entry_content(FakeCollector(result(published_at=metadata)), entry)
            self.assertIsNone(entry["published_at"])
            self.assertNotIn("date_basis", entry)

    def test_repository_creation_metadata_is_not_used_as_news_publication(self):
        entry = {"link": URL, "published_at": None}
        read_entry_content(FakeCollector(result(channel="github", kind="repository_or_issue",
                                               published_at="2020-01-01T00:00:00Z")), entry)
        self.assertIsNone(entry["published_at"])

    def test_wrong_article_or_query_id_cannot_supply_content_or_a_date(self):
        for wrong_url in (URL.replace("id=7", "id=8"), "https://publisher.example.org/other"):
            entry = {"link": URL, "published_at": None}
            collector = FakeCollector(result(url=wrong_url, published_at="2026-11-14T00:00:00Z"))
            self.assertEqual(read_entry_content(collector, entry), (None, None, "reach_provenance_mismatch"))
            self.assertIsNone(entry["published_at"])

    def test_matching_item_is_selected_instead_of_an_unrelated_first_result(self):
        response = result()
        response["items"].insert(0, {"url": "https://publisher.example.org/wrong", "text": "Wrong story " * 100})
        text, _, error = read_entry_content(FakeCollector(response), {"link": URL})
        self.assertEqual(text, BODY.strip())
        self.assertIsNone(error)

    def test_official_validated_adapter_text_is_reused_without_third_party_read(self):
        entry = {"link": URL, "published_at": "2026-11-14T01:00:00Z",
                 "discovery_backend": "publisher_adapter", "official_content": BODY}
        collector = FakeCollector(result(code="PLATFORM_BLOCKED"))
        self.assertEqual(read_entry_content(collector, entry, first_party=True),
                         (BODY.strip(), "publisher_adapter", None))
        self.assertEqual(collector.read_calls, [])

    def test_media_or_unverified_captured_text_does_not_bypass_the_reader(self):
        for first_party, discovery in ((False, "publisher_adapter"), (True, "public_rss")):
            entry = {"link": URL, "official_content": BODY, "discovery_backend": discovery}
            collector = FakeCollector(result(code="PLATFORM_BLOCKED"))
            self.assertEqual(read_entry_content(collector, entry, first_party=first_party),
                             (None, None, "reach_platform_blocked"))
            self.assertEqual(len(collector.read_calls), 1)

    def test_description_has_an_explicit_non_transcript_label(self):
        collector = FakeCollector(result(channel="youtube", kind="video_description", text=BODY))
        text, _, error = read_entry_content(collector, {"link": URL})
        self.assertIsNone(error)
        self.assertTrue(text.startswith("Publisher-supplied video description (not a verbatim transcript)."))
        self.assertIn("not as verified interview quotations", text)

    def test_short_description_is_not_treated_as_an_interview(self):
        collector = FakeCollector(result(channel="youtube", kind="video_description", text="Short promotional description. " * 5))
        self.assertEqual(read_entry_content(collector, {"link": URL}),
                         (None, None, "reach_insufficient_content"))

    def test_blocked_login_and_rate_limit_fail_without_content(self):
        for code in ("PLATFORM_BLOCKED", "NEED_LOGIN", "RATE_LIMITED"):
            collector = FakeCollector(result(code=code))
            self.assertEqual(read_entry_content(collector, {"link": URL}),
                             (None, None, "reach_" + code.lower()))
            self.assertEqual(len(collector.read_calls), 1)

    def test_unsupported_social_entries_do_not_use_captured_text_or_call_reader(self):
        for flag in ("is_reddit", "is_twitter", "is_hackernews"):
            collector = FakeCollector()
            entry = {"link": URL, flag: True, "official_content": BODY, "discovery_backend": "publisher_adapter"}
            self.assertEqual(read_entry_content(collector, entry, first_party=True),
                             (None, None, "reach_social_not_configured"))
            self.assertEqual(collector.read_calls, [])


class ReachPipelineIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.now(timezone.utc)
        self.source = {"id": 7, "name": "Fixture Laboratory", "url": "https://publisher.example.org/feed.xml",
                       "description": "[first_party] Official public research announcements", "category": "research",
                       "importance_score": 90}
        self.database = MagicMock()
        self.database.get_article_by_url.return_value = None
        self.database.article_url_exists.return_value = False
        self.database.get_similar_article.return_value = None
        self.database.add_article.return_value = "offline-article-id"
        self.engine = MagicMock()
        self.engine.summarize_content.return_value = (
            "A documented result.", "已公布研究成果。", "A detailed summary.", "详细摘要。", 85,
            ["research"], "Model research", "模型研究", "research", False,
            {"signal": 85, "structure": 80, "consequence": 75, "confidence": 90, "momentum": 30},
        )
        self.vectors = MagicMock()
        self.vectors.find_similar_articles.return_value = []
        self.stats = MagicMock()
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(pipeline, "_passes_broad_source_ai_filter", return_value=True))
        self.stack.enter_context(patch("compliance_filter.check_summary", return_value=(True, None)))
        self.stack.enter_context(patch("lsh_dedup.compute_simhash", return_value=1234))
        self.legacy = self.stack.enter_context(patch.object(pipeline.ContentProcessor, "fetch_and_extract", side_effect=AssertionError("No legacy read")))
        for name in ("_fetch_article_via_playwright", "_fetch_youtube_content", "_fetch_reddit_content", "_fetch_hackernews_content"):
            self.stack.enter_context(patch.object(pipeline, name, side_effect=AssertionError("No legacy/browser read")))
        self.stack.enter_context(patch("socket.create_connection", side_effect=AssertionError("No network")))
        self.stack.enter_context(patch("requests.sessions.Session.request", side_effect=AssertionError("No HTTP")))

    def entry(self, **overrides):
        return {"title": "A new model research result", "link": URL, "source_id": 7,
                "source": self.source["name"], "published_at": (self.now - timedelta(hours=1)).isoformat(),
                "discovery_backend": "public_rss", **overrides}

    def process(self, entry, collector):
        return pipeline._process_single_entry(
            entry, [self.source], {7: self.source}, self.database, self.engine, self.vectors,
            self.stats, 0, 0, self.now - timedelta(hours=48), {"youtube": {"delay_min": 0, "delay_max": 0}},
            collector=collector, counter_lock=threading.Lock(), youtube_fetched_counter=[0],
        )

    def test_successful_real_pipeline_keeps_feed_date_source_and_original_url(self):
        entry = self.entry()
        collector = FakeCollector(result(published_at=(self.now + timedelta(days=1)).isoformat()))
        self.assertEqual(self.process(entry, collector), 1)
        saved = self.database.add_article.call_args.args[0]
        self.assertEqual(saved["rss_source_id"], 7)
        self.assertEqual(saved["url"], URL)
        self.assertEqual(saved["published_at"], entry["published_at"])
        self.assertEqual(saved["source_published_at"], entry["published_at"])
        self.engine.summarize_content.assert_called_once()
        self.legacy.assert_not_called()

    def test_pipeline_blocks_missing_invalid_and_future_source_dates_before_llm(self):
        for date in (None, "not-a-date", (self.now + timedelta(days=1)).isoformat()):
            with self.subTest(date=date):
                self.engine.reset_mock()
                self.database.reset_mock()
                self.stats.reset_mock()
                self.assertEqual(self.process(self.entry(published_at=date), FakeCollector(result())), 0)
                self.engine.summarize_content.assert_not_called()
                self.database.add_article.assert_not_called()
                self.database.record_fetched_url.assert_not_called()
                self.stats.record_skip.assert_called_with(self.source["url"], unittest.mock.ANY, "missing_or_invalid_source_date")

    def test_valid_reader_metadata_can_fill_a_missing_source_date_in_pipeline(self):
        entry = self.entry(published_at=None)
        published = (self.now - timedelta(hours=2)).isoformat()
        self.assertEqual(self.process(entry, FakeCollector(result(published_at=published))), 1)
        self.assertEqual(self.database.add_article.call_args.args[0]["published_at"], published)
        self.assertEqual(entry["date_basis"], "source_reader_published")

    def test_old_reader_metadata_does_not_make_an_undated_item_current(self):
        old = (self.now - timedelta(days=10)).isoformat()
        self.assertEqual(self.process(self.entry(published_at=None), FakeCollector(result(published_at=old))), 0)
        self.engine.summarize_content.assert_not_called()
        self.stats.record_skip.assert_called_with(self.source["url"], unittest.mock.ANY, "old_article")

    def test_blocked_or_wrong_article_never_runs_an_old_extractor_or_llm(self):
        for response, reason in ((result(code="PLATFORM_BLOCKED"), "reach_platform_blocked"),
                                 (result(code="NEED_LOGIN"), "reach_need_login"),
                                 (result(code="RATE_LIMITED"), "reach_rate_limited"),
                                 (result(url=URL.replace("id=7", "id=8")), "reach_provenance_mismatch")):
            with self.subTest(reason=reason):
                self.stats.reset_mock()
                self.assertEqual(self.process(self.entry(), FakeCollector(response)), 0)
                self.stats.record_failure.assert_called_with(self.source["url"], unittest.mock.ANY, reason)
        self.engine.summarize_content.assert_not_called()
        self.database.add_article.assert_not_called()
        self.legacy.assert_not_called()

    def test_official_text_reuse_still_requires_a_valid_source_date(self):
        collector = FakeCollector(result(code="PLATFORM_BLOCKED"))
        entry = self.entry(published_at=None, official_content=BODY, discovery_backend="publisher_adapter")
        self.assertEqual(self.process(entry, collector), 0)
        self.assertEqual(collector.read_calls, [])
        self.engine.summarize_content.assert_not_called()

    def test_video_description_warning_reaches_the_editorial_prompt(self):
        collector = FakeCollector(result(channel="youtube", kind="video_description"))
        self.assertEqual(self.process(self.entry(is_youtube=True), collector), 1)
        prompt_text = self.engine.summarize_content.call_args.args[0]
        self.assertIn("not a verbatim transcript", prompt_text)
        self.assertIn("not as verified interview quotations", prompt_text)

    def test_cloud_guard_precedes_database_model_and_vector_construction(self):
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}), \
                patch.object(pipeline.ConfigLoader, "get_instance", return_value={}), \
                patch.object(pipeline, "get_news_collector", return_value=FakeCollector()), \
                patch.object(pipeline, "UserDatabase") as database, \
                patch.object(pipeline, "AIEngine") as engine, \
                patch.object(pipeline, "VectorStore") as vectors:
            with self.assertRaisesRegex(RuntimeError, "cloud-only"):
                pipeline.run_pipeline()
        database.assert_not_called()
        engine.assert_not_called()
        vectors.assert_not_called()

    def test_all_registered_fields_still_reach_discovery_without_browser_groups(self):
        sources = [{"id": i, "name": "Fixture " + domain, "url": "https://publisher.example.org/" + domain,
                    "description": "Public specialist source", "category": domain}
                   for i, domain in enumerate(domain_ids(), 1)]
        collector = FakeCollector()
        with patch.object(pipeline.ConfigLoader, "get_instance", return_value={"fetching": {"concurrency": 1}}), \
                patch.object(pipeline, "get_news_collector", return_value=collector), \
                patch.object(pipeline, "_process_browser_group", side_effect=AssertionError("No browser groups")):
            self.assertEqual(pipeline.fetch_articles_for_sources(sources, self.database, self.engine, self.vectors,
                                                                 fetch_stats=self.stats), 0)
        self.assertEqual({source["id"] for source in collector.feed_calls}, {source["id"] for source in sources})
        self.assertTrue(collector.closed)
        self.assertEqual(collector.read_calls, [])


if __name__ == "__main__":
    unittest.main()
