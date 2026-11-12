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

    def test_broad_emerging_field_feeds_filter_before_the_source_cap(self):
        self.assertFalse(passes_source_ai_filter("EIA Today in Energy", "US crude oil imports rise"))
        self.assertFalse(passes_source_ai_filter("AgFunderNews", "Iran denies cyberattacks on French supermarkets"))
        self.assertFalse(passes_source_ai_filter("Green Queen", "The best restaurants to visit this summer"))
        self.assertFalse(passes_source_ai_filter("Yale Environment 360", "A rare fish is making a comeback"))

    def test_new_technical_vocabulary_survives_the_broad_feed_gate(self):
        examples = (
            ("UK Atomic Energy Authority", "Giant box lowered into place for fusion upgrade"),
            ("Utility Dive", "Utilities test virtual power plants and new batteries"),
            ("FoodNavigator", "Precision fermentation platform reaches commercial scale"),
            ("Environmental Protection", "New PFAS remediation technology enters water treatment trials"),
            ("The Transmitter", "BCI startup advances clinical trials"),
            ("Siemens Blog", "Factory automation and digital twins cut production time"),
        )
        for source, title in examples:
            with self.subTest(source=source):
                self.assertTrue(passes_source_ai_filter(source, title))


if __name__ == "__main__":
    unittest.main()
