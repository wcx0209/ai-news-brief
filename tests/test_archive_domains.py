import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import export_archive as archive


def fixture(identifier, domain, title, importance=85):
    published = archive.parse_datetime("2026-11-12T01:00:00Z")
    return {
        "id": identifier, "domain": domain, "category": "research",
        "url": "https://example.org/research", "source": "Example Research",
        "published": published, "source_published": published,
        "site_published": published, "image_url": "#", "importance": importance,
        "scores": {"signal": 80, "structure": 70, "consequence": 75,
                   "confidence": 80, "momentum": 50},
        "tags": [],
        "en": {"title": title, "summary": "Reported research result.", "full": "Reported research result."},
        "zh": {"title": title + "中文", "summary": "研究成果摘要。", "full": "研究成果摘要。"},
    }


def structured_data(page):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page)
    return json.loads(match.group(1))


class ArchiveDomainTests(unittest.TestCase):
    def test_new_registered_domain_uses_safe_reading_guidance_fallback(self):
        record = fixture("new-field", "new_field", "New field research")
        with patch.dict(archive.DOMAIN_REGISTRY, {"new_field": {"label": {"en": "New Field", "zh": "新领域"}}}):
            context, _, evidence = archive.editorial_analysis(record, "en")
        self.assertIn("New Field", context)
        self.assertIn("original evidence", evidence)

    def test_daily_ai_page_excludes_other_fields_but_archive_keeps_them(self):
        ai = fixture("ai-result", "ai", "AI fixture title")
        quantum = fixture("quantum-result", "quantum_technology", "Quantum fixture title", 95)
        day = ai["published"].astimezone(archive.LOCAL_TZ).date()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for locale in ("en", "zh"):
                archive.render_daily_brief(output, locale, day, [quantum, ai])
                path = output / archive.daily_brief_path(locale, day).lstrip("/") / "index.html"
                page = path.read_text()
                self.assertIn(ai[locale]["title"], page)
                self.assertNotIn(quantum[locale]["title"], page)
                self.assertEqual(structured_data(page)["mainEntity"]["numberOfItems"], 1)
                archive.render_daily(output, locale, day, [quantum, ai], [day])
                page = (output / archive.archive_path(locale, day).lstrip("/") / "index.html").read_text()
                self.assertIn(quantum[locale]["title"], page)
                self.assertIn(ai[locale]["title"], page)

    def test_daily_ai_page_handles_a_date_with_no_ai_records(self):
        quantum = fixture("quantum-only", "quantum_technology", "Quantum fixture title")
        day = quantum["published"].astimezone(archive.LOCAL_TZ).date()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for locale, message in (("en", "No AI stories"), ("zh", "没有收录人工智能新闻")):
                archive.render_daily_brief(output, locale, day, [quantum])
                page = (output / archive.daily_brief_path(locale, day).lstrip("/") / "index.html").read_text()
                self.assertIn(message, page)
                self.assertIn(f'href="/{locale}/fields/ai/"', page)
                self.assertEqual(structured_data(page)["mainEntity"]["numberOfItems"], 0)

    def test_non_ai_article_has_field_metadata_and_honest_reading_guidance(self):
        record = fixture("quantum-result", "quantum_technology", "Quantum fixture title")
        day = record["published"].astimezone(archive.LOCAL_TZ).date()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for locale in ("en", "zh"):
                archive.render_article(output, locale, record)
                page = (output / archive.article_path(locale, day, record).lstrip("/") / "index.html").read_text()
                data = structured_data(page)
                self.assertEqual(data["about"]["url"], archive.SITE + f"/{locale}/fields/quantum_technology/")
                self.assertNotIn(archive.daily_brief_path(locale, day), page)
                self.assertNotIn("what AI systems can do", page)
                self.assertNotIn("改变 AI 系统", page)
                self.assertIn("classical methods" if locale == "en" else "经典方法", page)
                for domain in archive.DOMAIN_REGISTRY:
                    self.assertIn(f'href="/{locale}/fields/{domain}/"', page)
                nav = re.search(r'<nav class="desktop-nav".*?</nav>', page).group(0)
                self.assertIn(f'href="/{locale}/#fields"', nav)
                self.assertNotIn("#brief", nav)

    def test_cross_field_topic_does_not_claim_to_be_ai_only(self):
        record = fixture("quantum-result", "quantum_technology", "Quantum fixture title")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_topic(output, "en", "research", [record])
            page = (output / "en/topics/research/index.html").read_text()
            self.assertIn("Technology Research News", page)
            self.assertNotIn("AI Research News", page)

    def test_official_field_source_labels_match_domain_boundaries(self):
        record = fixture("source", "quantum_technology", "Quantum fixture title")
        for url in ("https://www.gov.uk/government/news/fusion", "https://aws.amazon.com/blogs/quantum-computing/research", "https://ir.dwavequantum.com/news/result"):
            record["url"] = url
            self.assertEqual(archive.source_type(record, "en"), "First-party / official source")
        record["url"] = "https://openai.com.example.org/research"
        self.assertEqual(archive.source_type(record, "en"), "Publisher report")


if __name__ == "__main__":
    unittest.main()
