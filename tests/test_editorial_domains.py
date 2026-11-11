import unittest

from editorial_domains import category_ids, category_labels, infer_domain, match_category, taxonomy_prompt


class EditorialDomainsTests(unittest.TestCase):
    def test_registry_contains_programmable_life_category(self):
        self.assertIn("biotech", category_ids())
        self.assertEqual(category_labels("zh")["biotech"], "可编程生命")

    def test_keyword_routing(self):
        self.assertEqual(match_category("CRISPR gene editing platform"), "biotech")
        self.assertEqual(match_category("new LLM benchmark"), "models")

    def test_domain_is_independent_from_story_angle(self):
        self.assertEqual(infer_domain("policy", "biotech", "export controls"), "programmable_life")
        self.assertEqual(infer_domain("policy", "news", "AI Act"), "ai")

    def test_taxonomy_is_prompt_ready(self):
        prompt = taxonomy_prompt()
        self.assertIn("biotech", prompt)
        self.assertIn("programmable life", prompt.lower())


if __name__ == "__main__":
    unittest.main()
