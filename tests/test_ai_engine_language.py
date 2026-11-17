import json
import os
import sys
import unittest
from types import SimpleNamespace


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_engine import AIEngine
from test_content_language import CHINESE, ENGLISH


class AiEngineLanguageTests(unittest.TestCase):
    def engine_with_responses(self, *responses):
        engine = AIEngine.__new__(AIEngine)
        engine.max_input_chars = 8000
        engine.model = "offline-fixture"
        engine.ai_timeout = 1
        engine._get_prompt_for_category = lambda category: "JSON contract"
        calls = []
        results = iter(responses)

        def complete(**kwargs):
            calls.append(kwargs)
            result = next(results)
            if isinstance(result, Exception):
                raise result
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(result)))])

        engine._create_chat_completion = complete
        return engine, calls

    def valid(self, **changes):
        return {
            "title_en": "New research result", "title_zh": "研究公布新结果",
            "summary_en": ENGLISH, "summary_zh": CHINESE,
            "long_summary_en": ENGLISH * 2, "long_summary_zh": CHINESE * 2,
            "importance_score": 70, "tags": ["AI"], **changes,
        }

    def test_correct_output_uses_one_request(self):
        engine, calls = self.engine_with_responses(self.valid())
        result = engine.summarize_content("source " * 200)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result[0:4], (ENGLISH, CHINESE, ENGLISH * 2, CHINESE * 2))
        self.assertEqual(result[4], 70)

    def test_wrong_english_field_retries_with_the_reason_then_accepts_fixed_output(self):
        engine, calls = self.engine_with_responses(self.valid(summary_en=CHINESE), self.valid())
        result = engine.summarize_content("source " * 200)
        self.assertEqual(len(calls), 2)
        self.assertIn("wrong_language_fields=['summary_en']", calls[1]["messages"][1]["content"])
        self.assertIn("Use English prose", calls[1]["messages"][1]["content"])
        self.assertEqual(result[0], ENGLISH)

    def test_persistent_wrong_chinese_body_fails_closed_after_two_requests(self):
        invalid = self.valid(long_summary_zh=ENGLISH)
        engine, calls = self.engine_with_responses(invalid, invalid)
        result = engine.summarize_content("source " * 200)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result[0:4], ("", "", "", ""))
        self.assertEqual(result[4], 0)
        self.assertEqual(result[6:8], ("", ""))

    def test_optional_wrong_language_full_summary_cannot_bypass_validation(self):
        invalid = self.valid(long_summary_en=CHINESE)
        engine, calls = self.engine_with_responses(invalid, invalid)
        result = engine.summarize_content("short source")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result[0:5], ("", "", "", "", 0))

    def test_failed_retry_does_not_return_first_wrong_language_attempt(self):
        engine, calls = self.engine_with_responses(self.valid(summary_zh=ENGLISH), RuntimeError("offline simulated failure"))
        result = engine.summarize_content("short source")
        self.assertEqual(len(calls), 2)
        self.assertEqual(result[0:5], ("", "", "", "", 0))

    def test_dropped_invalid_item_does_not_retry_or_expose_wrong_text(self):
        for dropped in ({"importance_score": 0}, {"china_blocked": True}):
            engine, calls = self.engine_with_responses(self.valid(summary_en=CHINESE, **dropped))
            result = engine.summarize_content("short source")
            self.assertEqual(len(calls), 1)
            self.assertEqual(result[0:5], ("", "", "", "", 0))

    def test_short_mixed_titles_and_missing_optional_body_remain_allowed(self):
        valid = self.valid(title_en="OpenAI 发布 GPT API", title_zh="New API", long_summary_en="", long_summary_zh="")
        engine, calls = self.engine_with_responses(valid)
        result = engine.summarize_content("short source")
        self.assertEqual(len(calls), 1)
        self.assertEqual(result[4], 70)


if __name__ == "__main__":
    unittest.main()
