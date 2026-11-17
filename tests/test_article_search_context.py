"""Offline excerpts copied from the existing Gemini archive record."""

import copy
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from article_search_context import article_search_context


def fixture():
    # Keep fixtures independent of the changing public feed and production DB.
    return {
        "id": "ef947a5d-9a1d-4aaf-a3a3-fad2dc5bef6a",
        "url": "https://deepmind.google/blog/introducing-gemini-4-hydrogen/",
        "published_at": "2026-11-12T18:00:50Z",
        "canonical_urls": {"en": "/existing-en-url/", "zh": "/existing-zh-url/"},
        "en": {
            "title": "Google Introduces Gemini 4 Hydrogen Model for Fast Execution and Agentic Workflows",
            "summary": (
                "According to Google DeepMind: Google is introducing Gemini 4 Hydrogen, "
                "a new model designed for rapid execution and everyday agentic workflows. "
                "Available across Google AI Studio, the Gemini API, and the Gemini app, "
                "Hydrogen offers flat pricing at $1.50 per million input tokens and $7.50 "
                "per million output tokens while delivering significant speed and "
                "efficiency upgrades over its predecessor."
            ),
            "full": (
                "According to Google DeepMind:\n\nBackground and Positioning\n"
                "Google is rolling out Gemini 4 Hydrogen to bring cutting-edge intelligence "
                "and speed to everyday coding and agentic workflows. While frontier models "
                "like Carbon and Argon handle deep, long-horizon reasoning on complex problems, "
                "Hydrogen is built as an efficient execution engine for rapid tasks and "
                "multi-model collaboration."
            ),
        },
        "zh": {
            "title": "谷歌发布 Gemini 4 Hydrogen 模型，主打快速执行与智能体工作流",
            "summary": (
                "据Google DeepMind发布的信息：谷歌推出了全新模型 Gemini 4 Hydrogen，"
                "旨在提供快速执行能力和日常的智能体工作流。该模型已全面上线谷歌各大开发和消费端产品，"
                "在保持极高性价比的同时，带来了显著的速度与效率提升。"
            ),
            "full": (
                "据Google DeepMind发布的信息：\n\n背景与定位\n"
                "谷歌正式发布了 Gemini 4 Hydrogen 模型，旨在将前沿的AI智能以高速度和高效率带入日常编程与"
                "智能体工作流中。虽然谷歌的旗舰模型 Carbon 和 Argon 专注于处理复杂的长周期推理任务，"
                "但 Hydrogen 的核心定位则是作为一个高效的执行引擎，胜任各类高频和多步骤的日常任务。"
            ),
        },
    }


class ArticleSearchContextTests(unittest.TestCase):
    def test_bilingual_answers_are_short_excerpts_of_the_requested_locale(self):
        record = fixture()
        for locale in ("en", "zh"):
            with self.subTest(locale=locale):
                context = article_search_context(record, locale)
                self.assertEqual(set(context), {
                    "seo_title", "description", "heading", "points", "source_url",
                })
                self.assertEqual(len(context["points"]), 3)
                self.assertEqual(context["source_url"], record["url"])
                source_text = " ".join(record[locale]["summary"].split()) + " " + " ".join(record[locale]["full"].split())
                for point in context["points"][:2]:
                    self.assertEqual(set(point), {"question", "answer"})
                    self.assertIn(point["answer"], source_text)
                    self.assertLess(len(point["answer"]), len(source_text) / 2)
                self.assertEqual(context["description"], context["points"][0]["answer"])
                self.assertIn("Gemini 4 Hydrogen", context["seo_title"])
                self.assertIn("Google" if locale == "en" else "谷歌", context["seo_title"])
                self.assertLessEqual(len(context["seo_title"]), 60)
                self.assertNotIn("latest", context["seo_title"].lower())
                self.assertNotIn("最新", context["seo_title"])

    def test_verification_is_a_question_list_without_new_pricing_or_benchmarks(self):
        for locale in ("en", "zh"):
            context = article_search_context(fixture(), locale)
            rendered_text = " ".join(point["answer"] for point in context["points"])
            for claim in ("$1.50", "$7.50", "Argon", "Carbon", "Terminal-Bench", "100 万"):
                self.assertNotIn(claim, rendered_text)
            verification = context["points"][2]["answer"]
            self.assertGreaterEqual(verification.count("?" if locale == "en" else "？"), 3)
            self.assertNotIn("not available", verification)
            self.assertNotIn("不可用", verification)

    def test_identity_and_source_allowlist_prevent_bulk_or_spoofed_context(self):
        for field, value in (
            ("id", "another-article"),
            ("url", "https://deepmind.google.evil.example/blog/introducing-gemini-4-hydrogen/"),
            ("url", "https://deepmind.google@evil.example/blog/introducing-gemini-4-hydrogen/"),
            ("url", "https://deepmind.google/blog/another-announcement/"),
            ("url", "javascript:alert(1)"),
        ):
            with self.subTest(field=field, value=value):
                record = fixture()
                record[field] = value
                self.assertIsNone(article_search_context(record, "en"))

    def test_missing_or_revised_evidence_disables_context_in_that_locale(self):
        for locale in ("en", "zh"):
            for key in ("summary", "full"):
                with self.subTest(locale=locale, missing=key):
                    record = fixture()
                    record[locale][key] = ""
                    self.assertIsNone(article_search_context(record, locale))
                    other_locale = "zh" if locale == "en" else "en"
                    self.assertIsNotNone(article_search_context(record, other_locale))
        record = fixture()
        record["en"]["full"] = record["en"]["full"].replace("efficient execution engine", "research prototype")
        self.assertIsNone(article_search_context(record, "en"))

    def test_changed_sentence_context_cannot_reuse_an_old_claim(self):
        record = fixture()
        record["en"]["summary"] = "It is false that " + record["en"]["summary"]
        self.assertIsNone(article_search_context(record, "en"))

    def test_whitespace_changes_preserve_excerpts_without_copying_the_full_body(self):
        record = fixture()
        expected = article_search_context(record, "en")
        record["en"]["summary"] = record["en"]["summary"].replace(" ", "\n  ")
        record["en"]["full"] = record["en"]["full"].replace(" ", "\n  ")
        self.assertEqual(article_search_context(record, "en"), expected)

    def test_inputs_unchanged_and_returned_values_are_detached(self):
        record = fixture()
        before = copy.deepcopy(record)
        context = article_search_context(record, "en")
        context["points"][0]["answer"] = "Caller modification"
        context["seo_title"] = "Caller title"
        self.assertEqual(record, before)
        fresh = article_search_context(record, "en")
        self.assertNotEqual(fresh["points"][0]["answer"], "Caller modification")
        self.assertNotEqual(fresh["seo_title"], "Caller title")

    def test_unsupported_or_malformed_input_does_not_guess_or_translate(self):
        for record, locale in ((None, "en"), ({}, "en"), (fixture(), "fr"), (fixture(), ""), (fixture(), [])):
            self.assertIsNone(article_search_context(record, locale))
        for value in (None, "", [], {"summary": [], "full": {}}):
            record = fixture()
            record["en"] = value
            self.assertIsNone(article_search_context(record, "en"))


if __name__ == "__main__":
    unittest.main()
