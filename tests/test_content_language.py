import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from content_language import safe_localized_fields, validate_localized_fields, wrong_language


ENGLISH = (
    "The research team reports that its new model improves the measured result "
    "on a limited benchmark. The announcement describes the test conditions, "
    "but provides no independent replication or evidence of commercial deployment."
)
CHINESE = (
    "研究团队表示，新模型在限定的测试条件下改善了测量结果。公告提供了基准测试的具体设置，"
    "但尚未披露独立复现的结果，也没有提供已经投入商业部署的证据，后续效果仍有待验证。"
)


class ContentLanguageTests(unittest.TestCase):
    def test_rejects_substantial_prose_in_the_opposite_locale(self):
        self.assertTrue(wrong_language(CHINESE, "en"))
        self.assertTrue(wrong_language(ENGLISH, "zh"))
        self.assertTrue(wrong_language(CHINESE, "en-US"))
        self.assertTrue(wrong_language(ENGLISH, "zh_CN"))
        self.assertFalse(wrong_language(ENGLISH, "en"))
        self.assertFalse(wrong_language(CHINESE, "zh"))

    def test_ignores_punctuation_and_numbers_as_evidence(self):
        self.assertTrue(wrong_language(CHINESE + " 2026 12345 67.89 " * 40, "en"))
        self.assertTrue(wrong_language(ENGLISH + " 2026 12345 67.89 " * 40, "zh"))
        self.assertFalse(wrong_language("1234567890, $67.89 2026-11-17 " * 30, "zh"))

    def test_allows_short_titles_names_and_mixed_technical_text(self):
        for title in ("OpenAI 发布 GPT-5 API", "New model from 李飞飞", "研究团队公布测试结果", "2026 AI GPU benchmark"):
            self.assertFalse(wrong_language(title, "en"))
            self.assertFalse(wrong_language(title, "zh"))
        technical_chinese = (
            "据 OpenAI、Google DeepMind 和 NVIDIA 称，新的 GPU benchmark 使用 PyTorch、"
            "CUDA、TensorRT、FlashAttention 和 Python 进行测试。测试结果仅代表特定设置，"
            "团队尚未披露独立复现结果，也未公布其实际部署情况。"
        )
        self.assertFalse(wrong_language(technical_chinese, "zh"))
        english_with_names = ENGLISH + " The authors include 李飞飞 and 张伟."
        self.assertFalse(wrong_language(english_with_names, "en"))
        self.assertTrue(wrong_language(english_with_names, "zh"))

    def test_ignores_code_and_url_destinations(self):
        code = "```python\n" + ENGLISH * 5 + "\n```"
        self.assertFalse(wrong_language("模型发布。\n" + code, "zh"))
        self.assertFalse(wrong_language("New release. `" + CHINESE * 3 + "`", "en"))
        self.assertFalse(wrong_language("模型发布。 https://example.com/" + "new-model/" * 80, "zh"))
        self.assertFalse(wrong_language("Release [details](https://example.com/" + CHINESE * 3 + ")", "en"))
        self.assertTrue(wrong_language("[" + CHINESE + "](https://example.com)", "en"))

    def test_markup_does_not_hide_wrong_language(self):
        self.assertTrue(wrong_language("<p>" + CHINESE + "</p>", "en"))
        self.assertTrue(wrong_language("<p>" + ENGLISH.replace(" ", "&nbsp;") + "</p>", "zh"))

    def test_traditional_and_supplementary_han_are_recognized(self):
        traditional = "研究團隊表示模型在限定條件下改善測試結果但沒有獨立複現證據後續效果仍需驗證" * 2
        self.assertTrue(wrong_language(traditional, "en"))
        self.assertTrue(wrong_language("\U00020000" * 50, "en"))

    def test_insufficient_or_unknown_inputs_are_preserved(self):
        for value in (None, "", "a few words", 123, [], {}):
            self.assertFalse(wrong_language(value, "en"))
            self.assertFalse(wrong_language(value, "zh"))
        self.assertFalse(wrong_language(CHINESE, "fr"))
        self.assertFalse(wrong_language(CHINESE, None))

    def test_validates_all_six_db_fields_and_ignores_unrelated_keys(self):
        fields = {
            "title_en": "模型发布", "title_zh": "Model released",
            "summary_en": CHINESE, "summary_zh": CHINESE,
            "long_summary_en": ENGLISH, "long_summary_zh": ENGLISH,
            "source_text": CHINESE,
        }
        original = fields.copy()
        self.assertEqual(validate_localized_fields(fields), ["summary_en", "long_summary_zh"])
        self.assertEqual(fields, original)
        self.assertEqual(validate_localized_fields(None), [])
        self.assertEqual(validate_localized_fields({"title_en": CHINESE}), ["title_en"])

    def test_safe_public_fields_clear_wrong_summary_and_full_without_mutation(self):
        fields = {"id": "fixed-id", "date": "2026-11-17", "title": "Keep title", "summary": CHINESE, "full_summary": CHINESE, "extra": 17}
        original = fields.copy()
        safe = safe_localized_fields(fields, "en")
        self.assertEqual(safe, {**fields, "summary": "", "full_summary": ""})
        self.assertEqual(fields, original)
        self.assertIsNot(safe, fields)

    def test_safe_full_falls_back_only_to_own_valid_short_summary(self):
        fields = {"summary": ENGLISH, "full_summary": CHINESE, "zh": {"summary": CHINESE}}
        self.assertEqual(safe_localized_fields(fields, "en")["full_summary"], ENGLISH)
        archive = {"summary": CHINESE, "full": ENGLISH, "title": "Keep title"}
        self.assertEqual(safe_localized_fields(archive, "zh", full_key="full")["full"], CHINESE)
        self.assertEqual(archive["full"], ENGLISH)
        self.assertEqual(safe_localized_fields({"full": CHINESE}, "en", full_key="full")["full"], "")

    def test_safe_public_fields_keep_valid_full_and_short_or_unknown_text(self):
        self.assertEqual(safe_localized_fields({"summary": CHINESE, "full_summary": ENGLISH}, "en"), {"summary": "", "full_summary": ENGLISH})
        for locale in ("en", "zh", "other"):
            fields = {"summary": "AI 模型", "full_summary": "Short title", "date": "unchanged"}
            self.assertEqual(safe_localized_fields(fields, locale), fields)


if __name__ == "__main__":
    unittest.main()
