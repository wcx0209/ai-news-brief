import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from scripts import track_search_indexing as tracker


NOW = tracker.timestamp("2026-11-28T07:00:00Z")
URL = "https://polyemergence.com/en/archive/2026/11/27/article/"
ZH_URL = URL.replace("/en/", "/zh/")


class SearchIndexingTests(unittest.TestCase):
    def test_actual_edition_and_visible_field_are_the_same_canonical_sample(self):
        with tempfile.TemporaryDirectory() as directory:
            public = Path(directory)
            def put(path, data):
                target = public / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(data, encoding="utf8")
            put("data/articles.json", json.dumps({"items": [{
                "id": "article", "canonical_urls": {"en": URL, "zh": ZH_URL},
                "published_at": "2026-11-24T16:35:00Z", "site_published_at": "2026-11-27T15:15:00Z",
                "en": {"title": "Example"}, "zh": {"title": "新闻"}
            }]}))
            for locale, suffix, url in (("en", "daily-ai-news", URL), ("zh", "ai-news-daily", ZH_URL)):
                ld = json.dumps({"@type": "CollectionPage", "mainEntity": {"itemListElement": [
                    {"position": 2, "url": "never-selected"}, {"position": 1, "url": url}]}})
                put(f"{locale}/{suffix}/2026-11-27/index.html", f'<script type="application/ld+json">{ld}</script>')
                put(f"{locale}/fields/ai/index.html", '<div id="lead-story" data-story-id="article"></div>')
                put(f"{locale}/fields/empty/index.html", '<div id="lead-story" hidden data-story-id="old"></div>')
            found = tracker.discover(public, NOW)
            self.assertEqual(set(found), {URL, ZH_URL})
            for row in found.values():
                self.assertEqual(row["published_at"], tracker.timestamp("2026-11-27T15:15:00Z"))
                self.assertEqual(row["cohorts"], ["daily-ai:2026-11-27", "field:ai"])

    def test_missed_windows_never_backfill_using_a_later_inspection(self):
        published = NOW - timedelta(hours=50)
        self.assertEqual(tracker.checkpoint_state(published, {}, 24, NOW), "missed")
        self.assertEqual(tracker.checkpoint_state(published, {}, 48, NOW), "due")
        self.assertEqual(tracker.checkpoint_state(published, {}, 72, NOW), "upcoming")
        row = {"url": URL, "published_at": published, "checkpoints": {}}
        conn = Mock()
        with patch.object(tracker, "utcnow", return_value=NOW), patch.object(
            tracker, "inspect_url", return_value={"status": "indexed", "observed_at": NOW.isoformat()}
        ) as inspect:
            for _ in range(2):
                tracker.update_checks(conn, Mock(), [row], None)
            inspect.assert_called_once_with(None, URL)
        self.assertEqual(set(row["checkpoints"]), {"48"})
        conn.commit.assert_called_once()

    def test_permission_probe_calls_both_readonly_endpoints_without_writing(self):
        with patch.object(tracker, "inspect_url") as inspect, patch.object(tracker, "search_buckets") as analytics:
            tracker.verify_access(None, URL, NOW)
        inspect.assert_called_once_with(None, URL)
        analytics.assert_called_once_with(None, {URL}, date(2026, 11, 23), date(2026, 11, 23), hourly=False)

    def test_inspection_errors_and_missing_data_do_not_become_negative_observations(self):
        session = Mock()
        session.post.return_value.ok = False
        session.post.return_value.status_code = 403
        with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
            tracker.inspect_url(session, URL)
        session.post.return_value.ok = True
        session.post.return_value.json.return_value = {"inspectionResult": {"indexStatusResult": {"verdict": "VERDICT_UNSPECIFIED"}}}
        self.assertEqual(tracker.inspect_url(session, URL)["status"], "unknown")

    def test_rate_limit_retries_before_recording_observation(self):
        limited = Mock(ok=False, status_code=429)
        ok = Mock(ok=True)
        ok.json.return_value = {"rows": []}
        session = Mock()
        session.post.side_effect = [limited, limited, ok]
        with patch.object(tracker.time, "sleep") as delay:
            result = tracker.gsc_post(session, tracker.ANALYTICS, {})
        self.assertEqual(result, {"rows": []})
        self.assertEqual(delay.call_count, 2)

    def test_transient_url_error_preserves_siblings_and_remains_due(self):
        rows = [{"url": u, "published_at": NOW - timedelta(hours=25), "checkpoints": {}} for u in (URL, ZH_URL)]
        result = {"status": "not_indexed", "observed_at": NOW.isoformat()}
        conn = Mock()
        with patch.object(tracker, "utcnow", return_value=NOW), patch.object(
            tracker, "inspect_url", side_effect=[tracker.GSCError(503), result, result]
        ) as inspect:
            self.assertEqual(tracker.update_checks(conn, Mock(), rows, None), 1)
            self.assertEqual(rows[0]["checkpoints"], {})
            self.assertEqual(rows[1]["checkpoints"], {"24": result})
            self.assertEqual(tracker.update_checks(conn, Mock(), rows, None), 0)
        self.assertEqual(inspect.call_count, 3)
        self.assertEqual(conn.commit.call_count, 2)

    def test_rate_denominator_only_includes_measured_urls(self):
        make = lambda url, status: dict(url=url, locale="en", cohorts=["field:ai"], published_at=NOW-timedelta(hours=36),
                                        checkpoints={"24": {"status": status}} if status else {})
        rates = tracker.report([make("a", "indexed"), make("b", ""), make("c", "unknown"), make("d", "not_indexed")],
                               NOW, "google_measured")["rates_by_locale"]["en"]["24"]
        self.assertEqual(rates, {"indexed": 1, "missed": 1, "unknown": 1, "not_indexed": 1,
                                 "measured": 2, "index_rate": .5})

    def test_hour_buckets_and_reporting_lag(self):
        session = Mock()
        session.post.return_value.ok = True
        session.post.return_value.json.return_value = {"rows": [
            {"keys": [URL, "2026-11-18T17:00:00-08:00"], "impressions": 3},
            {"keys": [URL, "2026-11-18T09:00:00-08:00"], "impressions": 1},
            {"keys": [ZH_URL, "2026-11-18T08:00:00-08:00"], "impressions": 0},
        ]}
        result = tracker.search_buckets(session, {URL, ZH_URL}, date(2026, 11, 18), date(2026, 11, 20), hourly=True)
        self.assertEqual(result, {URL: "2026-11-18T17:00:00+00:00"})
        self.assertEqual(session.post.call_args.kwargs["json"]["dataState"], "hourly_all")
        row = {"url": URL, "published_at": NOW - timedelta(days=4), "analytics": {}}
        with patch.object(tracker, "search_buckets", side_effect=[{}, {}, {URL: "2026-11-25"}, {}]) as api:
            tracker.update_analytics(Mock(), Mock(), [row], None, NOW)
            self.assertNotIn("first_final_date_pt", row["analytics"])
            tracker.update_analytics(Mock(), Mock(), [row], None, NOW + timedelta(hours=3))
            self.assertEqual(api.call_count, 2)
            tracker.update_analytics(Mock(), Mock(), [row], None, NOW + timedelta(hours=12))
            self.assertEqual(api.call_count, 4)
        self.assertEqual(row["analytics"]["first_final_date_pt"], "2026-11-25")
        self.assertEqual(row["analytics"]["first_seen_in_api_at"], (NOW + timedelta(hours=12)).isoformat())


if __name__ == "__main__":
    unittest.main()
