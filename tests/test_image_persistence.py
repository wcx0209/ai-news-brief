import copy
from datetime import datetime, timedelta, timezone
import html
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_archive as archive
import export_public_feed as feed


NOW = datetime(2026, 11, 14, 3, tzinfo=timezone.utc)
FIRST = "https://cdn.example.org/image.png?signature=a%2Bb&width=1200"
SECOND = "https://cdn.example.org/alternative.jpg"


def item(identifier="one", url="https://publisher.example.org/story", **changes):
    published = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
    value = {
        "id": identifier, "url": url, "source": "Example Research", "domain": "ai", "category": "research",
        "importance": 85, "scores": {"confidence": 80}, "tags": ["Gemini", "evaluation"],
        "published_at": published, "source_published_at": published, "site_published_at": published,
        "image_url": FIRST, "image_candidates": [FIRST, SECOND], "image_source_url": url,
        "image_rejected_urls": [],
        "image_status": "verified", "image_checked_at": NOW.isoformat().replace("+00:00", "Z"),
        "en": {"title": "Gemini evaluation protocol", "summary": "A reported research result.", "full_summary": "Complete reported result."},
        "zh": {"title": "Gemini 评测方法", "summary": "研究成果摘要。", "full_summary": "完整研究成果摘要。"},
    }
    value.update(changes)
    return value


def write_feed(path, items):
    path.write_text(json.dumps({"generated_at": "2026-11-14T00:00:00Z", "items": items}), encoding="utf-8")


class ImagePersistenceTests(unittest.TestCase):
    def test_media_guard_preserves_signed_urls_deduplicates_and_caps_candidates(self):
        value = item(image_candidates=[FIRST, "https://cdn.example.org/alternative.jpg", "https://cdn.example.org/three.jpg", "https://cdn.example.org/four.jpg"])
        media = feed.image_fields(value)
        self.assertEqual(media["image_url"], FIRST)
        self.assertEqual(len(media["image_candidates"]), 3)
        self.assertEqual(media["image_status"], "verified")
        for unsafe in ("http://127.0.0.1/image.png", "https://user:secret@cdn.example.org/image.png", "javascript:alert(1)", "http://10.0.0.1/image.png"):
            guarded = feed.image_fields(item(image_url=unsafe, image_candidates=[unsafe]))
            self.assertEqual(guarded["image_candidates"], [])
            self.assertIsNone(guarded["image_url"])

    def test_explicit_source_binding_mismatch_discards_media(self):
        media = feed.image_fields(item(image_source_url="https://publisher.example.org/another-story"))
        self.assertEqual(media["image_candidates"], [])
        self.assertNotIn("image_status", media)

    def test_discovery_supplies_validated_candidates_and_actual_attempt_metadata(self):
        rows = [{"id": "one", "url": "https://publisher.example.org/story"}]
        with patch.object(feed, "discover_images", return_value=[FIRST, SECOND]) as discover:
            values = feed.collect_image_fields(rows, [], now=NOW)
        discover.assert_called_once_with(rows[0]["url"], timeout=8, limit=3, rejected=[])
        self.assertEqual(values[0]["image_candidates"], [FIRST, SECOND])
        self.assertEqual(values[0]["image_status"], "verified")
        self.assertEqual(values[0]["image_checked_at"], "2026-11-14T03:00:00Z")

    def test_only_recent_verified_same_source_media_skips_rediscovery(self):
        previous = item(url="https://PUBLISHER.example.org:443/story#section")
        rows = [{"id": previous["id"], "url": "https://publisher.example.org/story"}]
        with patch.object(feed, "discover_images") as discover:
            values = feed.collect_image_fields(rows, [previous], now=NOW + timedelta(days=6))
        discover.assert_not_called()
        self.assertEqual(values[0]["image_candidates"], [FIRST, SECOND])
        self.assertEqual(values[0]["image_source_url"], "https://publisher.example.org/story")

    def test_legacy_unverified_stale_and_future_checked_media_is_checked_again(self):
        previous = item()
        rows = [{"id": previous["id"], "url": previous["url"]}]
        variants = [dict(previous, image_status=None),
                    dict(previous, image_checked_at=(NOW - timedelta(days=8)).isoformat()),
                    dict(previous, image_checked_at=(NOW + timedelta(minutes=1)).isoformat())]
        for prior in variants:
            with self.subTest(prior=prior.get("image_status")), patch.object(feed, "discover_images", return_value=[SECOND]) as discover:
                values = feed.collect_image_fields(rows, [prior], now=NOW)
                self.assertEqual(values[0]["image_url"], SECOND)
                discover.assert_called_once()

    def test_empty_discovery_preserves_prior_media_without_claiming_verification(self):
        previous = item()
        with patch.object(feed, "discover_images", return_value=[]):
            media = feed.collect_image_fields([{"id": "one", "url": previous["url"]}], [previous], now=NOW + timedelta(days=8))[0]
        current = item(image_url=None, image_candidates=[], image_status="unavailable", **{"image_checked_at": media["image_checked_at"]})
        current["en"]["title"] = "Updated editorial title"
        current["importance"] = 90
        merged = feed.merge_recent_items([current], [previous], 60, 2, 2, 70, 65)[0]
        self.assertEqual(media["image_url"], FIRST)
        self.assertEqual(merged["image_candidates"], [FIRST, SECOND])
        self.assertEqual(merged["image_status"], "unavailable")
        self.assertEqual(merged["en"]["title"], "Updated editorial title")
        self.assertEqual(merged["importance"], 90)
        self.assertEqual(merged["source_published_at"], current["source_published_at"])

    def test_changed_source_url_never_reuses_the_previous_image(self):
        previous = item()
        changed = item(url="https://publisher.example.org/corrected-story", image_url=None,
                       image_candidates=[], image_source_url="https://publisher.example.org/corrected-story")
        self.assertEqual(feed.merge_image_fields(changed, previous)["image_candidates"], [])
        with patch.object(feed, "discover_images") as discover:
            media = feed.collect_image_fields([changed], [previous], discover_limit=0, now=NOW)[0]
        discover.assert_not_called()
        self.assertEqual(media["image_candidates"], [])
        self.assertNotIn("image_checked_at", media)

    def test_archive_keeps_media_after_article_leaves_latest_without_restoring_rows(self):
        previous = item()
        record = archive.record_from_feed(item(image_url=None, image_candidates=[], image_status=None))
        before = copy.deepcopy(record)
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "articles.json"
            latest = Path(directory) / "latest.json"
            write_feed(corpus, [previous, item("removed")])
            write_feed(latest, [])
            records = archive.preserve_archive_images([record], corpus)
            records = archive.merge_current_feed(records, latest)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["image_candidates"], [FIRST, SECOND])
        self.assertEqual(records[0]["image_source_url"], previous["url"])
        for key in ("id", "published", "source_published", "site_published", "importance", "scores", "en", "zh"):
            self.assertEqual(records[0][key], before[key])

    def test_archive_does_not_reuse_media_after_source_url_changes(self):
        previous = item()
        record = archive.record_from_feed(item(url="https://publisher.example.org/official-story", image_url=None,
                                              image_candidates=[], image_source_url="https://publisher.example.org/official-story"))
        with tempfile.TemporaryDirectory() as directory:
            corpus = Path(directory) / "articles.json"
            write_feed(corpus, [previous])
            archive.preserve_archive_images([record], corpus)
        self.assertEqual(record["image_candidates"], [])

    def test_latest_verified_media_overrides_preserved_archive_and_empty_does_not_erase(self):
        record = archive.record_from_feed(item())
        with tempfile.TemporaryDirectory() as directory:
            latest = Path(directory) / "latest.json"
            write_feed(latest, [item(image_url=SECOND, image_candidates=[SECOND])])
            archive.merge_current_feed([record], latest)
            self.assertEqual(record["image_candidates"], [SECOND])
            write_feed(latest, [item(image_url=None, image_candidates=[], image_status="unavailable")])
            archive.merge_current_feed([record], latest)
        self.assertEqual(record["image_url"], SECOND)
        self.assertEqual(record["image_status"], "unavailable")

    def test_newer_archive_repair_is_not_overwritten_by_an_older_feed_snapshot(self):
        repaired = item(image_url=SECOND, image_candidates=[SECOND], image_checked_at=NOW.isoformat())
        earlier = item(image_status="unavailable", image_checked_at=(NOW - timedelta(minutes=5)).isoformat())
        media = feed.merge_image_fields(earlier, repaired, now=NOW)
        self.assertEqual(media["image_candidates"], [SECOND])
        self.assertEqual(media["image_status"], "verified")
        unchecked = item(image_status=None, image_checked_at=None)
        self.assertEqual(feed.merge_image_fields(unchecked, repaired, now=NOW)["image_url"], SECOND)

    def test_explicit_low_resolution_rejection_removes_only_the_rejected_old_candidate(self):
        previous = item()
        unavailable = item(image_url=None, image_candidates=[], image_status="unavailable",
                           image_rejected_urls=[FIRST], image_checked_at=NOW.isoformat())
        media = feed.merge_image_fields(unavailable, previous, now=NOW)
        self.assertEqual(media["image_candidates"], [SECOND])
        self.assertEqual(media["image_url"], SECOND)
        self.assertEqual(media["image_rejected_urls"], [FIRST])
        self.assertEqual(media["image_status"], "unavailable")
        unavailable["image_rejected_urls"].append(SECOND)
        media = feed.merge_image_fields(unavailable, previous, now=NOW)
        self.assertEqual(media["image_candidates"], [])
        self.assertIsNone(media["image_url"])

    def test_newer_no_image_rejection_cannot_be_resurrected_by_an_older_feed(self):
        rejected = item(image_url=None, image_candidates=[], image_status="unavailable",
                        image_rejected_urls=[FIRST, SECOND], image_checked_at=NOW.isoformat())
        older = item(image_checked_at=(NOW - timedelta(minutes=5)).isoformat())
        media = feed.merge_image_fields(older, rejected, now=NOW)
        self.assertEqual(media["image_candidates"], [])
        self.assertEqual(media["image_rejected_urls"], [FIRST, SECOND])
        self.assertEqual(media["image_status"], "unavailable")
        unchecked = item(image_status=None, image_checked_at=None)
        self.assertIsNone(feed.merge_image_fields(unchecked, rejected, now=NOW)["image_url"])

    def test_new_real_verification_can_clear_older_rejections(self):
        previous = item(image_url=None, image_candidates=[], image_status="unavailable",
                        image_rejected_urls=[FIRST], image_checked_at=(NOW - timedelta(minutes=5)).isoformat())
        media = feed.merge_image_fields(item(image_candidates=[FIRST]), previous, now=NOW)
        self.assertEqual(media["image_candidates"], [FIRST])
        self.assertEqual(media["image_rejected_urls"], [])
        self.assertEqual(media["image_status"], "verified")

    def test_rejection_guard_caps_safe_urls_and_does_not_reuse_another_source_denylist(self):
        rejected = ["http://127.0.0.1/image.png", "https://user:secret@cdn.example.org/image.png"]
        rejected.extend(f"https://cdn.example.org/small-{number}.png" for number in range(20))
        media = feed.image_fields(item(image_rejected_urls=rejected))
        self.assertEqual(len(media["image_rejected_urls"]), 12)
        self.assertTrue(all(value.startswith("https://cdn.example.org/small-") for value in media["image_rejected_urls"]))
        changed = item(url="https://publisher.example.org/other", image_source_url="https://publisher.example.org/other",
                       image_url=None, image_candidates=[], image_status=None, image_checked_at=None)
        previous = item(image_rejected_urls=[FIRST])
        self.assertEqual(feed.merge_image_fields(changed, previous, now=NOW)["image_rejected_urls"], [])

    def test_each_discovery_thread_owns_its_rejection_list(self):
        rows = [{"id": str(number), "url": f"https://publisher.example.org/{number}"} for number in range(2)]
        lists = []
        def discover(url, timeout, limit, rejected):
            lists.append(rejected)
            rejected.append(FIRST if url.endswith("0") else SECOND)
            return []
        with patch.object(feed, "discover_images", side_effect=discover):
            media = feed.collect_image_fields(rows, [], now=NOW)
        self.assertEqual(len({id(value) for value in lists}), 2)
        self.assertEqual(media[0]["image_rejected_urls"], [FIRST])
        self.assertEqual(media[1]["image_rejected_urls"], [SECOND])
        self.assertTrue(all(value["image_status"] == "unavailable" for value in media))

    def test_public_archive_export_round_trip_keeps_media_and_source_dates(self):
        original = item()
        record = archive.enrich_record(archive.record_from_feed(original))
        with tempfile.TemporaryDirectory() as directory:
            archive.render_public_data(Path(directory), [record])
            exported = json.loads((Path(directory) / "data/articles.json").read_text())["items"][0]
        for key in ("image_url", "image_candidates", "image_source_url", "image_checked_at", "image_status", "image_rejected_urls"):
            self.assertEqual(exported[key], original[key])
        for key in ("published_at", "source_published_at", "site_published_at"):
            self.assertEqual(exported[key], original[key])

    def test_offline_feed_reexport_never_discovers_and_keeps_media(self):
        original = item()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.json"
            output = Path(directory) / "latest.json"
            write_feed(path, [original])
            with patch.object(sys, "argv", ["export_public_feed.py", "--input-json", str(path), "--output", str(output)]), patch.object(feed, "discover_images") as discover:
                feed.main()
            exported = json.loads(output.read_text())
        discover.assert_not_called()
        self.assertEqual(exported["generated_at"], "2026-11-14T00:00:00Z")
        for key in ("image_url", "image_candidates", "image_source_url", "image_checked_at", "image_status", "image_rejected_urls", "source_published_at"):
            self.assertEqual(exported["items"][0][key], original[key])

    def test_candidate_json_is_escaped_and_only_detail_figure_has_retry_button(self):
        record = archive.record_from_feed(item(image_candidates=[FIRST, 'https://cdn.example.org/second.jpg?label="quoted"']))
        detail = archive.archive_figure(record, "zh")
        match = re.search(r'data-image-candidates="([^"]+)"', detail)
        self.assertEqual(json.loads(html.unescape(match[1])), record["image_candidates"])
        self.assertIn("&quot;", detail)
        self.assertIn("data-image-retry hidden>重试原图", detail)
        thumbnail = archive.archive_thumbnail(record, "archive-recommendation-image")
        self.assertIn("data-image-candidates", thumbnail)
        self.assertNotIn("<button", thumbnail)

    def test_legacy_parser_keeps_stored_candidates_without_changing_prose(self):
        reader = archive.LegacyArticleReader()
        stored = html.escape(json.dumps([FIRST, SECOND]), quote=True)
        reader.feed(f'<article class="archive-story"><p class="archive-dek">Original prose.</p><figure><img src="{html.escape(FIRST, quote=True)}" data-image-candidates="{stored}"></figure></article>')
        self.assertEqual(reader.image_candidates, [FIRST, SECOND])
        self.assertIn("Original prose.", "".join(reader.dek))


if __name__ == "__main__":
    unittest.main()
