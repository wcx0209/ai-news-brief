import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from relevance_filter import passes_source_ai_filter


class RelevanceFilterTests(unittest.TestCase):
    def test_rejects_cross_promoted_itmedia_business_story(self):
        self.assertFalse(
            passes_source_ai_filter(
                "ITmedia AI+",
                "Why Agoda Teams Up with ANA and Hoshino Resorts in Japan",
            )
        )

    def test_keeps_itmedia_story_with_explicit_ai_signal(self):
        self.assertTrue(
            passes_source_ai_filter(
                "ITmedia AI+",
                "Sakana AI is developing its first mobile app",
            )
        )

    def test_does_not_gate_first_party_model_feed(self):
        self.assertTrue(
            passes_source_ai_filter("Anthropic News", "Introducing Fable 5.2")
        )

    def test_keeps_registered_non_ai_fields(self):
        self.assertTrue(passes_source_ai_filter("US NIST", "New quantum sensing network reaches field trial"))
        self.assertTrue(passes_source_ai_filter("US NIST", "Advanced manufacturing method cuts alloy waste"))


if __name__ == "__main__":
    unittest.main()
