"""Observation cards are bounded reading hypotheses tied to real evidence."""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("export_observations", ROOT / "scripts/export_observations.py")
observations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observations)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 12, tzinfo=timezone.utc)

    def item(self, title="AI agent deployed in customer workflow", identifier="a", **kwargs):
        result = {"id": identifier, "domain": "ai", "url": f"https://lab.example/{identifier}", "source": "Lab",
                  "source_published_at": (self.now - timedelta(days=2)).isoformat(),
                  "en": {"title": title, "summary": title}, "zh": {"title": "", "summary": ""}}
        result.update(kwargs)
        return result

    def cards(self, items, field="ai"):
        return observations.observation_cards({"items": items}, now=self.now)["fields"][field]

    def test_no_padding_and_strict_original_date_window(self):
        self.assertEqual(self.cards([]), [])
        excluded = [self.item(identifier="future", source_published_at=(self.now + timedelta(seconds=1)).isoformat()),
                    self.item(identifier="old", source_published_at=(self.now - timedelta(days=30, seconds=1)).isoformat()),
                    self.item(identifier="missing", source_published_at=None),
                    self.item(identifier="bad", url="javascript:alert(1)")]
        self.assertEqual(self.cards(excluded), [])
        boundary = self.cards([self.item(source_published_at=(self.now - timedelta(days=30)).isoformat())])
        self.assertEqual(len(boundary), 1)
        self.assertEqual(boundary[0]["status"], "unverified_signal")
        self.assertEqual(boundary[0]["evidence"][0]["url"], "https://lab.example/a")

    def test_tracking_urls_and_reprints_count_as_one_event(self):
        a = self.item("OpenAI launches AI agents for deployed customer workflow", url="https://news.example/item/?utm_source=test#top")
        same = self.item("A different AI agent workflow headline", identifier="b", url="http://www.news.example/item?ref=reader")
        copy = self.item("OpenAI releases AI agents in customer production workflow", identifier="c", url="https://other.example/openai")
        card = self.cards([a, same, copy])[0]
        self.assertEqual(card["report_group_count"], 1)
        self.assertEqual(card["status"], "unverified_signal")
        self.assertEqual(observations.canonical_url(a["url"]), observations.canonical_url(same["url"]))

    def test_subdomains_do_not_create_publisher_diversity(self):
        items = [self.item("AI agent workflow at a hospital", "a", url="https://research.company.co.uk/a"),
                 self.item("Insurance production deploys an AI agent", "b", url="https://blog.company.co.uk/b"),
                 self.item("Warehouse AI agent workflow starts operating", "c", url="https://company.co.uk/c")]
        card = self.cards(items)[0]
        self.assertEqual(card["report_group_count"], 3)
        self.assertEqual(card["publisher_count"], 1)
        self.assertEqual(card["status"], "unverified_signal")
        items[-1]["url"] = "https://independent.example/c"
        card = self.cards(items)[0]
        self.assertEqual(card["status"], "unverified_signal")
        self.assertTrue(card["event_identity_uncertain"])
        self.assertEqual(card["publisher_count"], 2)
        self.assertIn("Reports may describe the same event.", card["uncertainty"]["en"])
        self.assertIn("have not been independently verified", card["uncertainty"]["en"])
        self.assertIn("不能据此认定趋势已经形成", card["uncertainty"]["zh"])

    def test_topic_matching_rejects_substring_and_semantic_false_positives(self):
        cases = [("ai", "Thai agent deploys new tourist workflow"),
                 ("robotics_autonomy", "聊天机器人部署到工厂服务系统"),
                 ("advanced_materials", "Training materials for production workers"),
                 ("quantum_technology", "Quantum company builds a fault-tolerant classical database")]
        for field, title in cases:
            with self.subTest(title=title):
                self.assertEqual(self.cards([self.item(title, domain=field)], field), [])
        self.assertTrue(self.cards([self.item("Humanoid robots deployed in a factory", domain="robotics_autonomy")], "robotics_autonomy"))
        self.assertTrue(self.cards([self.item("Logical qubits improve after quantum error correction", domain="quantum_technology")], "quantum_technology"))

    def test_bilingual_reprints_and_unknown_entities_never_upgrade_status(self):
        items = [self.item("NovaWorks introduces AI agent production workflow", "a", url="https://one.example/a", zh={"title": "新星公司发布用于工厂工作流的 AI 智能体", "summary": ""}),
                 self.item("A new agentic workplace release comes from a startup", "b", url="https://two.example/b", zh={"title": "新星公司发布用于工厂工作流的 AI 智能体", "summary": ""}),
                 self.item("Enterprise workflow gains autonomous AI agent software", "c", url="https://three.example/c", zh={"title": "新星公司发布用于工厂工作流的 AI 智能体", "summary": ""})]
        card = self.cards(items)[0]
        self.assertEqual(card["report_group_count"], 1)
        self.assertEqual(card["status"], "unverified_signal")
        self.assertTrue(card["event_identity_uncertain"])

    def test_related_domain_is_explicit_and_topic_matching_is_specific(self):
        item = self.item("Data center grid power demand grows", domain="energy_storage", related_domains=["ai"])
        self.assertEqual(self.cards([item])[0]["id"], "compute-power")
        self.assertEqual(self.cards([self.item("A software company raises funding")]), [])
        item.pop("related_domains")
        self.assertEqual(self.cards([item]), [])
        unknown = observations.observation_cards({"items": [self.item(domain="future_field")]}, now=self.now)
        self.assertNotIn("future_field", unknown["fields"])

    def test_safe_urls_and_xss_data_are_not_executable(self):
        for value in ("javascript:alert(1)", "https://example.org/\nattack", "https://user:pass@example.org/a", "https://example.org\\@evil.example/x", "https://example.org:bad/a"):
            with self.subTest(value=value):
                self.assertIsNone(observations.safe_url(value))
        item = self.item('AI agent workflow <img src=x onerror="alert(1)">', canonical_urls={"en": "javascript:alert(2)", "zh": "https://polyemergence.com/zh/archive/2026/11/11/a/"})
        evidence = self.cards([item])[0]["evidence"][0]
        self.assertNotIn("en", evidence["canonical_urls"])
        # JSON preserves text; HTML escaping is tested at the rendering boundary.
        self.assertIn("<img", evidence["title"]["en"])

    def test_every_registered_field_has_a_small_cautious_catalogue(self):
        self.assertEqual(len(observations.TOPICS), 11)
        for configs in observations.TOPICS.values():
            self.assertLessEqual(len(configs), 3)
            for config in configs:
                self.assertTrue(config["groups"])
                self.assertEqual(set(config["title"]), {"en", "zh"})

    def test_github_trending_is_not_publication_evidence(self):
        ranked = self.item(source="GitHub Trending", url="https://github.com/vendor/agent")
        self.assertEqual(self.cards([ranked]), [])
        ranked["source"] = "Vendor Official Releases"
        ranked["url"] = "https://github.com/vendor/agent/releases/tag/v2"
        self.assertTrue(self.cards([ranked]))


if __name__ == "__main__":
    unittest.main()
