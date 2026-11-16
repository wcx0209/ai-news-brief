"""Local font/layout fixtures: no model, database, download or old-image editing."""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import weekly_covers as covers


def fixture():
    return {"id": "2026-11-09", "week_start": "2026-11-09", "week_end": "2026-11-15",
            "en": {"title": "Polyemergence Industry Review: Model evaluations and chip deployment"},
            "zh": {"title": "Polyemergence 行业观察：模型评测与芯片部署"}}


class WeeklyCoverTests(unittest.TestCase):
    def require_cjk(self):
        try:
            covers._font_path("zh", "科技周报")
        except RuntimeError as error:
            self.skipTest(f"Chinese cover requires Noto CJK or macOS STHeiti: {error}")

    def test_png_is_1200_by_630_deterministic_nonmutating_and_offline(self):
        payload = fixture()
        original = deepcopy(payload)
        with patch("socket.create_connection", side_effect=AssertionError("No network is allowed")):
            first = covers.render_weekly_cover(payload, "en")
            self.assertEqual(first, covers.render_weekly_cover(deepcopy(payload), "en"))
        with Image.open(BytesIO(first)) as picture:
            self.assertEqual(picture.format, "PNG")
            self.assertEqual(picture.size, (1200, 630))
            self.assertEqual(picture.mode, "RGB")
            self.assertEqual(picture.getpixel((0, 0)), (255, 90, 36))
        self.assertEqual(payload, original)

    def test_bilingual_topics_keep_facts_and_wrap_inside_measured_boxes(self):
        self.require_cjk()
        payload = fixture()
        payload["en"]["title"] = "Model evaluations and chip deployment: reported costs, test conditions and operating limits"
        payload["zh"]["title"] = "模型评测、芯片部署与临床试验：报告中披露的测试条件、部署成本和研究边界仍需分别理解"
        for locale in ("en", "zh"):
            with self.subTest(locale=locale):
                lines = covers._cover_layout(payload, locale)
                topic = [line for line in lines if line.role == "topic"]
                self.assertGreater(len(topic), 1)
                expected = covers.weekly_topic(payload, locale)
                self.assertEqual("".join("".join(line.text.split()) for line in topic), "".join(expected.split()))
                for line in lines:
                    left, top, right, bottom = line.bbox
                    self.assertGreaterEqual(left, 0)
                    self.assertGreaterEqual(top, 0)
                    self.assertLessEqual(right, 1140)
                    self.assertLessEqual(bottom, 610)
                    if line.role == "topic":
                        self.assertGreaterEqual(top, 207)
                        self.assertLessEqual(bottom, 489)
                png = covers.render_weekly_cover(payload, locale)
                self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))

    def test_legacy_branding_is_removed_only_from_the_topic(self):
        self.require_cjk()
        for locale in ("en", "zh"):
            with self.subTest(locale=locale):
                lines = covers._cover_layout(fixture(), locale)
                self.assertEqual([line.text for line in lines if line.role == "brand"], ["POLYEMERGENCE"])
                topic = " ".join(line.text for line in lines if line.role == "topic")
                self.assertNotIn("Polyemergence", topic)
                self.assertNotIn("Industry Review", topic)
                self.assertNotIn("行业观察", topic)
                self.assertIn("2026-11-09", next(line.text for line in lines if line.role == "period"))
                self.assertIn("2026-11-15", next(line.text for line in lines if line.role == "period"))

    def test_long_topic_shrinks_without_losing_any_supplied_characters(self):
        self.require_cjk()
        payload = fixture()
        payload["zh"]["title"] = "部署条件、试验范围与证据边界" * 12
        topic = [line for line in covers._cover_layout(payload, "zh") if line.role == "topic"]
        self.assertLess(topic[0].size, 72)
        self.assertEqual("".join(line.text for line in topic), payload["zh"]["title"])
        self.assertLessEqual(max(line.bbox[3] for line in topic), 489)

    def test_directory_cover_has_no_invented_coverage_dates(self):
        self.require_cjk()
        for locale in ("en", "zh"):
            lines = covers._cover_layout(None, locale)
            self.assertEqual(next(line.text for line in lines if line.role == "period"), covers._COPY[locale]["index_period"])
            self.assertNotIn("2026", " ".join(line.text for line in lines))
            self.assertEqual(covers.render_weekly_cover(None, locale), covers.render_weekly_cover(None, locale))

    def test_extreme_topic_is_explicitly_omitted_rather_than_a_cut_claim(self):
        payload = fixture()
        payload["en"]["title"] = "A reported result with conditions " * 80
        topic = [line for line in covers._cover_layout(payload, "en") if line.role == "topic"]
        self.assertEqual(" ".join(line.text for line in topic), covers._COPY["en"]["omitted"])
        self.assertNotIn("A reported result", " ".join(line.text for line in topic))

    def test_missing_chinese_font_fails_closed_instead_of_rendering_tofu(self):
        with patch.object(covers, "_CJK_FONTS", ()):
            with self.assertRaisesRegex(RuntimeError, "cjk_font_required"):
                covers.render_weekly_cover(fixture(), "zh")

    def test_unsupported_locale_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "locale"):
            covers.render_weekly_cover(fixture(), "fr")


if __name__ == "__main__":
    unittest.main()
