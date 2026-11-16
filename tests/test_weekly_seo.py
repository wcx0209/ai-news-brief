import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from weekly_seo import weekly_cover_path, weekly_heading, weekly_meta_title, weekly_period, weekly_topic


class WeeklySeoTests(unittest.TestCase):
    def test_legacy_brand_and_review_labels_are_removed_without_rewriting_the_subject(self):
        examples = (
            ("en", "Polyemergence Industry Review: Multiagent Systems, IBM Quantum Reports & AI Security/Genetics Tools", "Multiagent Systems, IBM Quantum Reports & AI Security/Genetics Tools"),
            ("zh", "Polyemergence 行业观察：多智能体协作、IBM报告量子优势进展及AI安全与基因工具升级", "多智能体协作、IBM报告量子优势进展及AI安全与基因工具升级"),
            ("zh", "多重涌现科技周报：量子系统的验证边界", "量子系统的验证边界"),
            ("en", "The Polyemergence Weekly: AI verification tools | Polyemergence", "AI verification tools"),
            ("en", "Industry Review: Industry review tools for engineers", "Industry review tools for engineers"),
        )
        for locale, title, expected in examples:
            with self.subTest(title=title):
                self.assertEqual(weekly_topic({locale: {"title": title}}, locale), expected)

    def test_new_topic_titles_keep_their_meaning_and_h1_does_not_cut_long_topics(self):
        topic = "Quantum verification reports, multiagent research tools, and the conditions for reliable deployment"
        payload = {"en": {"title": topic}, "week_start": "2026-11-09", "week_end": "2026-11-15"}
        self.assertEqual(weekly_topic(payload, "en"), topic)
        self.assertEqual(weekly_heading(payload, "en"), f"Weekly Tech News & Analysis: {topic} (Nov 9–15, 2026)")
        self.assertTrue(weekly_meta_title(payload, "en").startswith("Weekly Tech News: Quantum verification reports"))
        self.assertTrue(weekly_meta_title(payload, "en").endswith(" | Nov 9–15, 2026"))
        self.assertEqual(weekly_period(payload, "en"), "2026-11-09 — 2026-11-15")
        for subject in ("-5 degrees in a quantum experiment", "Industry review tools for engineers", "Trials (2025-01-01 — 2025-01-02)"):
            payload["en"]["title"] = subject
            self.assertEqual(weekly_topic(payload, "en"), subject)

    def test_an_existing_formatted_title_does_not_duplicate_the_same_coverage_period(self):
        payload = {"en": {"title": "Weekly Tech News & Analysis: Verification tools (2026-11-09 — 2026-11-15) | Polyemergence"}, "week_start": "2026-11-09", "week_end": "2026-11-15"}
        self.assertEqual(weekly_topic(payload, "en"), "Verification tools")
        self.assertEqual(weekly_heading(payload, "en").count("Nov 9–15, 2026"), 1)
        self.assertNotIn("2026-11-09", weekly_heading(payload, "en"))

    def test_real_legacy_115_character_title_has_a_shorter_meta_summary_and_complete_h1(self):
        original = "Polyemergence Industry Review: Multiagent Systems, IBM Quantum Reports & AI Security/Genetics Tools"
        payload = {"en": {"title": original}, "zh": {"title": "Polyemergence 行业观察：多智能体协作、IBM报告量子优势进展及AI安全与基因工具升级"}, "week_start": "2026-11-09", "week_end": "2026-11-15"}
        meta = weekly_meta_title(payload, "en")
        self.assertEqual(len(original + " | Polyemergence"), 115)
        self.assertEqual(meta, "Weekly Tech News: Multiagent Systems, IBM Quantum Reports | Nov 9–15, 2026")
        self.assertLess(len(meta + " | Polyemergence"), 100)
        self.assertLess(len(meta + " | Polyemergence"), len(original + " | Polyemergence"))
        self.assertNotIn("Polyemergence", meta)
        self.assertNotIn("Industry Review", meta)
        self.assertIn("IBM Quantum Reports", meta)
        self.assertIn("AI Security/Genetics Tools", weekly_heading(payload, "en"))
        self.assertIn("科技周报：", weekly_meta_title(payload, "zh"))
        self.assertTrue(weekly_meta_title(payload, "zh").endswith("｜11月9–15日"))
        self.assertIn("2026年11月9–15日", weekly_heading(payload, "zh"))

    def test_long_english_meta_topics_stop_at_whole_words_and_preserve_claim_qualifiers(self):
        payload = {"en": {"title": "Reported experimental quantum verification methods for more reliable multiagent systems and deployment constraints"}, "week_start": "2026-11-09", "week_end": "2026-11-15"}
        meta = weekly_meta_title(payload, "en")
        self.assertIn("Reported experimental", meta)
        self.assertLessEqual(len(meta + " | Polyemergence"), 100)
        self.assertRegex(meta, r"\bverification… \| Nov 9–15, 2026$")
        payload["en"]["title"] = "A highly specific quantum advantage experiment with unusually important trailing claims and limitations"
        self.assertIn("claims", weekly_meta_title(payload, "en"))
        self.assertLessEqual(len(weekly_meta_title(payload, "en") + " | Polyemergence"), 100)
        self.assertIn("limitations", weekly_heading(payload, "en"))

    def test_compact_dates_keep_cross_month_and_year_periods_clear(self):
        payload = {"en": {"title": "Verification tools"}, "zh": {"title": "验证工具"}, "week_start": "2026-11-30", "week_end": "2026-12-06"}
        self.assertIn("Nov 30–Dec 6, 2026", weekly_meta_title(payload, "en"))
        self.assertIn("11月30日–12月6日", weekly_meta_title(payload, "zh"))
        payload.update(week_start="2026-12-28", week_end="2027-01-03")
        self.assertIn("Dec 28, 2026–Jan 3, 2027", weekly_meta_title(payload, "en"))
        self.assertIn("2026年12月28日–2027年1月3日", weekly_meta_title(payload, "zh"))

    def test_topic_does_not_fall_back_to_other_language_or_infer_a_new_subject(self):
        payload = {"en": {"title": "AI tools"}, "zh": {}}
        self.assertEqual(weekly_topic(payload, "zh"), "本周选材")
        self.assertEqual(weekly_period({}, "zh"), "未提供 — 未提供")
        self.assertNotIn("AI tools", weekly_heading(payload, "zh"))

    def test_cover_paths_are_deterministic_locale_specific_and_validate_ids(self):
        for locale in ("en", "zh"):
            self.assertEqual(weekly_cover_path("2026-11-09", locale), f"/assets/weekly/2026-11-09-{locale}.png")
            self.assertEqual(weekly_cover_path(None, locale), f"/assets/weekly/index-{locale}.png")
        for identifier in ("../private", "2026-02-30", "2026-1-1", "2026-11-09\" onload=x", {}):
            with self.subTest(identifier=identifier), self.assertRaises(ValueError):
                weekly_cover_path(identifier, "en")
        for function, argument in ((weekly_topic, {}), (weekly_heading, {}), (weekly_period, {}), (weekly_cover_path, None)):
            with self.subTest(function=function.__name__), self.assertRaises(ValueError):
                function(argument, "fr")

    def test_helpers_are_pure_offline_and_preserve_published_json_and_timestamps(self):
        payload = {"en": {"title": "Polyemergence Industry Review: Verification tools"}, "week_start": "2026-11-09", "week_end": "2026-11-15", "published_at": "2026-11-16T02:00:00Z"}
        before = copy.deepcopy(payload)
        with patch("builtins.open", side_effect=AssertionError("no file I/O")), patch("socket.getaddrinfo", side_effect=AssertionError("no network")):
            weekly_topic(payload, "en")
            weekly_heading(payload, "en")
            weekly_meta_title(payload, "en")
            weekly_cover_path("2026-11-09", "en")
        self.assertEqual(payload, before)


if __name__ == "__main__":
    unittest.main()
