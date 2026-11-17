import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("language_public_feed", ROOT / "scripts/export_public_feed.py")
feed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(feed)


class PublicLanguageGuardTests(unittest.TestCase):
    def fixture(self):
        now = datetime.now(timezone.utc).isoformat()
        return {
            "id": "language-fixture", "url": "https://example.org/release",
            "source": "Example", "category": "models", "domain": "ai",
            "importance": 85, "scores": {"confidence": 85}, "tags": [],
            "published_at": now, "source_published_at": now, "site_published_at": now,
            "en": {"title": "New model", "summary": "The company reports a new model.",
                   "full_summary": "这段正文被错误地放进了英文摘要字段，不能直接展示给英文读者。" * 5},
            "zh": {"title": "新模型", "summary": "据该公司发布的信息，公司发布新模型。",
                   "full_summary": "公司表示已经发布了一个新模型，具体能力还需要独立评测。"},
        }

    def test_guard_uses_same_locale_short_summary_without_mutating_input(self):
        item = self.fixture()
        original = copy.deepcopy(item)
        result = feed.safe_public_item(item)
        self.assertNotIn("这段正文", result["en"]["full_summary"])
        self.assertIn("The company reports a new model", result["en"]["full_summary"])
        self.assertEqual(result["zh"]["full_summary"], item["zh"]["full_summary"])
        for key in ("id", "source_published_at", "published_at", "site_published_at"):
            self.assertEqual(result[key], original[key])
        self.assertEqual(item, original)

    def test_english_in_chinese_is_not_rescued_by_chinese_source_prefix(self):
        item = self.fixture()
        item["source"] = "中国科学院科技动态"
        item["zh"]["full_summary"] = "The company reports that its new model is being tested by several teams. " * 5
        result = feed.safe_public_item(item)
        self.assertNotIn("several teams", result["zh"]["full_summary"])
        self.assertIn("公司发布新模型", result["zh"]["full_summary"])

    def test_offline_command_guards_carried_feed_and_keeps_collection_time(self):
        item = self.fixture()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "input.json"
            output = Path(directory) / "latest.json"
            source.write_text(json.dumps({"generated_at": item["published_at"], "items": [item]}))
            subprocess.run([sys.executable, "-S", str(ROOT / "scripts/export_public_feed.py"),
                            "--input-json", str(source), "--output", str(output)],
                           check=True, capture_output=True, text=True)
            payload = json.loads(output.read_text())
            self.assertEqual(payload["generated_at"], item["published_at"])
            self.assertEqual(len(payload["items"]), 1)
            self.assertNotIn("这段正文", payload["items"][0]["en"]["full_summary"])
            self.assertEqual(payload["items"][0]["source_published_at"], item["source_published_at"])


if __name__ == "__main__":
    unittest.main()
