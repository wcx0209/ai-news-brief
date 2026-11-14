from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from repair_archive_images import repair_payload

NOW = datetime(2026, 11, 14, tzinfo=timezone.utc)


def item(identifier, **extra):
    return {"id": identifier, "url": "https://example.com/" + identifier,
            "published_at": "2026-11-10T00:00:00Z", "importance": 80,
            "canonical_urls": {"en": "https://polyemergence.com/en/archive/old/"},
            "en": {"title": "Unchanged news", "summary": "Unchanged summary"}, **extra}


class ImageRepairTests(unittest.TestCase):
    def test_only_media_changes_no_republication_and_input_is_untouched(self):
        payload = {"count": 1, "generated_at": "2026-11-10T00:00:00Z", "items": [item("one")]}
        original = deepcopy(payload)
        repaired, stats = repair_payload(payload, now=NOW, discover=lambda url: ["https://cdn.example.com/picture.png"])
        self.assertEqual(payload, original)
        self.assertEqual(stats, {"checked": 1, "verified": 1})
        self.assertEqual(repaired["generated_at"], payload["generated_at"])
        for key in ("published_at", "importance", "canonical_urls", "en"):
            self.assertEqual(repaired["items"][0][key], payload["items"][0][key])
        self.assertEqual(repaired["items"][0]["image_status"], "verified")

    def test_failure_keeps_historical_image_and_cooldown_avoids_repeated_scrapes(self):
        record = item("one", image_url="https://cdn.example.com/old.png")
        payload = {"items": [record]}
        repaired, stats = repair_payload(payload, now=NOW, discover=lambda url: [])
        self.assertEqual(repaired["items"][0]["image_url"], record["image_url"])
        self.assertEqual(repaired["items"][0]["image_status"], "unavailable")
        again, stats = repair_payload(repaired, now=NOW, discover=lambda url: self.fail("must respect cooldown"))
        self.assertEqual(stats["checked"], 0)

    def test_limit_future_and_changed_source_url_are_handled(self):
        records = [item("future", source_published_at="2026-12-01T00:00:00Z"),
                   item("changed", image_checked_at=NOW.isoformat(), image_source_url="https://example.com/old"),
                   item("later")]
        visited = []
        _, stats = repair_payload({"items": records}, limit=1, now=NOW, discover=lambda url: visited.append(url) or [])
        self.assertEqual(stats["checked"], 1)
        self.assertEqual(visited, ["https://example.com/changed"])

    def test_fresh_latest_media_is_reused_without_rescraping_or_restoring_news(self):
        current = item("one", image_url="https://cdn.example.com/new.png", image_candidates=["https://cdn.example.com/new.png"],
                       image_status="verified", image_source_url="https://example.com/one", image_checked_at=NOW.isoformat())
        current["en"]["title"] = "Do not copy title from live feed"
        payload = {"items": [item("one")]}
        repaired, stats = repair_payload(payload, now=NOW, current_items=[current, item("not-in-corpus")], discover=lambda url: self.fail("already checked by feed exporter"))
        self.assertEqual(stats["checked"], 0)
        self.assertEqual(len(repaired["items"]), 1)
        self.assertEqual(repaired["items"][0]["image_url"], current["image_url"])
        self.assertEqual(repaired["items"][0]["en"]["title"], "Unchanged news")


if __name__ == "__main__":
    unittest.main()
