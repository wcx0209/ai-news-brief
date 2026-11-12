import copy
from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from editorial_insights import enrich_item, evidence_type, related_domains, technology_stage

spec = importlib.util.spec_from_file_location("public_feed_under_test", ROOT / "scripts/export_public_feed.py")
feed = importlib.util.module_from_spec(spec)
spec.loader.exec_module(feed)


def fixture(identifier="one", **changes):
    record = {
        "id": identifier, "domain": "ai", "category": "company",
        "source": "OpenAI News", "url": "https://openai.com/index/research-result/",
        "importance": 80, "scores": {"confidence": 80},
        "source_published_at": datetime.now(timezone.utc).isoformat(),
        "en": {"title": "A new model result", "summary": "The company reports a result.", "full_summary": "## Results\nReported results and caveats."},
        "zh": {"title": "一项模型成果", "summary": "公司报告一项结果。", "full_summary": "## 结果\n已报告的结果与限制。"},
    }
    record.update(changes)
    return record


class EvidenceMetadataTests(unittest.TestCase):
    def test_first_party_url_and_spoofed_hosts(self):
        self.assertEqual(evidence_type(fixture()), "official_release")
        for url in ("https://openai.com.evil.example/index/result", "https://notopenai.com/index/result", "https://openai.com@evil.example/result", "javascript:alert(1)"):
            self.assertEqual(evidence_type(fixture(url=url)), "unknown")

    def test_research_news_is_not_a_peer_reviewed_paper(self):
        self.assertEqual(evidence_type(fixture(source="MIT CSAIL", url="https://www.csail.mit.edu/news/model", category="academia")), "official_release")
        self.assertEqual(evidence_type(fixture(source="Nature Materials", url="https://www.nature.com/articles/s41563-026-01234-5")), "research_paper")
        self.assertEqual(evidence_type(fixture(source="Nature Materials", url="https://www.nature.com/articles/d41586-026-01234-5")), "media_report")

    def test_preprint_interview_open_source_and_media_are_distinct(self):
        cases = [
            ({"url": "https://arxiv.org/abs/2611.12345", "category": "academia"}, "preprint"),
            ({"url": "https://www.biorxiv.org/content/10.1101/2026.11.10.12345v1"}, "preprint"),
            ({"url": "https://youtube.com/watch?v=abcdefghijk", "category": "interviews"}, "interview"),
            ({"url": "https://github.com/openai/example/releases/tag/v1"}, "open_source"),
            ({"url": "https://techcrunch.com/2026/11/11/model", "source": "TechCrunch AI"}, "media_report"),
            ({"url": "https://arxiv.org.evil.example/abs/2611.12345"}, "unknown"),
        ]
        for changes, expected in cases:
            with self.subTest(changes=changes):
                self.assertEqual(evidence_type(fixture(**changes)), expected)

    def test_publisher_name_cannot_verify_shared_youtube_host(self):
        record = fixture(source="IMDA Singapore", url="https://youtube.com/watch?v=abcdefghijk")
        self.assertEqual(evidence_type(record), "unknown")

    def test_stages_require_explicit_achieved_headline_evidence(self):
        titles = [
            ("Company announces a new robot", "unspecified"),
            ("Company plans commercial deployment of robot", "unspecified"),
            ("Robot has not yet been deployed at a factory", "unspecified"),
            ("No evidence that robot is deployed in a factory", "unspecified"),
            ("Robot deployment could start if pilot program succeeds", "unspecified"),
            ("机器人尚未商业化部署", "unspecified"),
            ("原型演示不等于商业化部署", "unspecified"),
            ("Company unveils roadmap for quantum computing", "unspecified"),
            ("AI model released for research", "unspecified"),
            ("New battery prototype demonstrates a working system", "demonstration"),
            ("Company starts pilot program for battery storage", "pilot"),
            ("Battery deployed at a working factory", "deployment"),
            ("Battery laboratory test measures a result", "laboratory"),
        ]
        for title, stage in titles:
            with self.subTest(title=title):
                record = fixture(en={"title": title}, zh={})
                self.assertEqual(technology_stage(record), stage)

    def test_related_domains_ignore_source_tags_generic_words_and_ai_marketing(self):
        record = fixture(domain="quantum_technology", source="AI Robotics Materials", tags=["biotech", "battery"],
                         en={"title": "A new computational model", "summary": "A neural network model studies materials. AI could help in the future."}, zh={})
        self.assertEqual(related_domains(record), [])
        record["en"] = {"title": "A battery of tests checks a model", "summary": "A group of evaluation tasks."}
        self.assertEqual(related_domains(record), [])
        record["zh"] = {"title": "Adobe 发布聊天机器人", "summary": "聊天机器人用于设计软件，而非实体自动化。"}
        record["en"] = {"title": "Adobe adds creative software features", "summary": "Enterprise software uses a digital twin to test software workflows."}
        self.assertEqual(related_domains(record), [])

    def test_specific_related_fields_are_bounded_and_exclude_primary(self):
        record = fixture(domain="programmable_life", en={"title": "AI protein design for cultivated meat", "summary": "Uses machine learning and precision fermentation."}, zh={})
        self.assertEqual(related_domains(record), ["ai", "agrifood_technology"])
        record["en"]["title"] += " with satellite robotics and quantum computing"
        self.assertLessEqual(len(related_domains(record)), 2)
        self.assertNotIn("programmable_life", related_domains(record))
        record = fixture(domain="programmable_life", en={"title": "A biology result", "summary": "Training uses a million samples and a neural network."}, zh={})
        self.assertEqual(related_domains(record), [])

    def test_enrichment_is_detached_idempotent_and_supports_archive_full(self):
        original = fixture(domain="energy_storage", source="NVIDIA Robotics", url="https://blogs.nvidia.com/blog/result/",
                           en={"title": "A storage study", "summary": "Measured results.", "full": "## Conditions\nReported conditions."})
        before = copy.deepcopy(original)
        enriched = enrich_item(original)
        self.assertEqual(original, before)
        self.assertEqual(enriched, enrich_item(enriched))
        self.assertTrue(enriched["en"]["summary"].startswith("According to NVIDIA Robotics:"))
        self.assertTrue(enriched["en"]["full"].startswith("According to NVIDIA Robotics:\n\n##"))
        self.assertEqual(enriched["related_domains"], [])
        self.assertIn("measured performance", enriched["reading_context"]["en"])
        self.assertIn("实测", enriched["reading_context"]["zh"])
        renamed = copy.deepcopy(enriched)
        renamed["source"] = "NVIDIA News"
        renamed = enrich_item(renamed)
        self.assertEqual(renamed["en"]["summary"].count("According to"), 1)
        self.assertTrue(renamed["en"]["summary"].startswith("According to NVIDIA News:"))
        self.assertEqual(renamed["related_domains"], [])

    def test_preprint_attribution_preserves_uncertainty(self):
        record = enrich_item(fixture(url="https://arxiv.org/abs/2611.12345"))
        self.assertTrue(record["en"]["summary"].startswith("The authors report in this preprint:"))
        self.assertTrue(record["zh"]["summary"].startswith("据这篇预印本作者报告："))
        self.assertNotIn("independently verified", record["en"]["summary"])

    def test_future_registered_domain_has_non_fabricated_context(self):
        record = enrich_item(fixture(domain="a_future_domain", url="https://unknown.example/result"))
        self.assertIn("original evidence", record["reading_context"]["en"])
        self.assertEqual(record["evidence"], {"type": "unknown", "stage": "unspecified"})


class DailyPublicationGateTests(unittest.TestCase):
    def test_carry_forward_cannot_bypass_minimum_by_domain_reservation(self):
        weak = fixture("weak", domain="space_economy", importance=18)
        passing = fixture("passing", importance=65)
        self.assertEqual([item["id"] for item in feed.merge_recent_items([], [weak, passing], 60, 2, 2, 70, 65)], ["passing"])

    def test_rows_share_the_same_minimum_before_domain_balance(self):
        rows = [{"id": "weak", "category": "company", "source_category": "space_economy", "source_name": "Example", "title": "Satellite result", "importance_score": 18},
                {"id": "passing", "category": "company", "source_name": "Example", "title": "AI model result", "importance_score": 65}]
        selected = feed.select_balanced_rows(rows, 60, 2, 2, 70, 65)
        self.assertEqual([row["id"] for row in selected], ["passing"])

    def test_academia_keeps_stricter_scores_confidence_and_daily_cap(self):
        values = [fixture("lowimportance", category="academia", importance=69), fixture("lowconfidence", category="academia", importance=90, scores={"confidence": 64})]
        values += [fixture(str(index), category="academia", importance=90-index, scores={"confidence": 65}) for index in range(3)]
        selected = feed.merge_recent_items(values, [], 60, 2, 2, 70, 65)
        self.assertEqual([item["id"] for item in selected], ["0", "1"])

    def test_offline_export_requires_no_db_or_scraping_and_preserves_collection_time(self):
        now = datetime.now(timezone.utc)
        with tempfile.TemporaryDirectory() as folder:
            input_path = Path(folder) / "input.json"
            output_path = Path(folder) / "output.json"
            input_path.write_text(json.dumps({"generated_at": "original-collection-time", "items": [fixture(), fixture("weak", importance=18), fixture("old", source_published_at=(now-timedelta(hours=49)).isoformat()), fixture("future", source_published_at=(now+timedelta(hours=1)).isoformat())]}))
            result = subprocess.run([sys.executable, "-S", str(ROOT / "scripts/export_public_feed.py"), "--input-json", str(input_path), "--output", str(output_path)], capture_output=True, text=True, check=True, cwd=folder)
            payload = json.loads(output_path.read_text())
            self.assertEqual(payload["generated_at"], "original-collection-time")
            self.assertEqual(payload["count"], 1)
            self.assertEqual(payload["items"][0]["evidence"]["type"], "official_release")
            self.assertIn("no database, collection or LLM calls", result.stdout)


class FutureSummarizationContractTests(unittest.TestCase):
    def test_prompt_requires_attribution_and_does_not_invent_historical_validation(self):
        from ai_engine import AIEngine

        engine = AIEngine.__new__(AIEngine)
        engine.max_input_chars = 8000
        engine.model = "test-no-network"
        engine.ai_timeout = 1
        engine._get_prompt_for_category = lambda category: "JSON contract"
        captured = []

        def fake_completion(**kwargs):
            captured.append(kwargs["messages"][0]["content"])
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps({
                "summary_en": "The company reports a result.", "summary_zh": "据公司称有一项结果。",
                "importance_score": 80, "category": "company",
            })))])

        engine._create_chat_completion = fake_completion
        engine.summarize_content("A company announcement.", title="A reported result", category="company")
        prompt = captured[0]
        for boundary in ("Attribute first-party", "not independent validation", "separate reported facts", "not proof of a historical trend", "最强", "硬刚"):
            self.assertIn(boundary, prompt)


if __name__ == "__main__":
    unittest.main()
