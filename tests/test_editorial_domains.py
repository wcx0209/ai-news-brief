import unittest

from editorial_domains import (
    category_ids, category_labels, domain_ids, infer_domain, match_category,
    match_domain, taxonomy_prompt,
)


class EditorialDomainsTests(unittest.TestCase):
    def test_registry_contains_programmable_life_category(self):
        self.assertIn("biotech", category_ids())
        self.assertEqual(category_labels("zh")["biotech"], "可编程生命")

    def test_keyword_routing(self):
        self.assertEqual(match_category("CRISPR gene editing platform"), "biotech")
        self.assertEqual(match_category("new LLM benchmark"), "models")

    def test_domain_is_independent_from_story_angle(self):
        self.assertEqual(infer_domain("policy", "biotech", "export controls"), "programmable_life")
        self.assertEqual(infer_domain("business", "quantum_technology", "funding round"), "quantum_technology")
        self.assertEqual(infer_domain("policy", "news", "AI Act"), "ai")

    def test_registry_contains_all_long_horizon_fields(self):
        self.assertEqual(len(domain_ids()), 11)
        self.assertIn("energy_storage", domain_ids())
        self.assertIn("advanced_manufacturing", domain_ids())
        self.assertEqual(match_domain("a long-duration energy storage system"), "energy_storage")
        self.assertEqual(match_domain("脑机接口恢复交流能力"), "neurotechnology")

    def test_taxonomy_is_prompt_ready(self):
        prompt = taxonomy_prompt()
        self.assertIn("quantum_technology", prompt)
        self.assertIn("story angles", prompt.lower())
        self.assertIn("programmable life", prompt.lower())


if __name__ == "__main__":
    unittest.main()
