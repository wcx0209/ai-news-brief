import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from ai_engine import AIEngine


class AiEnginePromptRoutingTests(unittest.TestCase):
    def setUp(self):
        self.engine = AIEngine.__new__(AIEngine)
        self.engine.prompts_dir = os.path.join(ROOT, "src", "prompts")

    def test_public_news_categories_use_news_contract(self):
        news_prompt = self.engine._get_prompt_for_category("news")
        for category in (
            "models", "company", "startups", "research",
            "policy", "business", "society",
        ):
            self.assertEqual(
                self.engine._get_prompt_for_category(category),
                news_prompt,
            )

    def test_open_source_uses_open_source_contract(self):
        self.assertEqual(
            self.engine._get_prompt_for_category("open_source"),
            self.engine._get_prompt_for_category("opensource"),
        )

    def test_unknown_category_falls_back_to_news_contract(self):
        self.assertEqual(
            self.engine._get_prompt_for_category("future_category"),
            self.engine._get_prompt_for_category("news"),
        )


if __name__ == "__main__":
    unittest.main()
