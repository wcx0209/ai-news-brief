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

    def test_insights_survive_feed_archive_corpus_and_scores_stay_folded(self):
        item = {"id": "bci", "domain": "neurotechnology", "category": "research", "source": "BrainGate",
                "url": "https://www.braingate.org/research/", "published_at": "2026-11-12T01:00:00Z", "importance": 85,
                "en": {"title": "Brain-computer interface uses AI in a clinical trial", "summary": "Reported research result."},
                "zh": {"title": "脑机接口临床试验使用人工智能", "summary": "研究成果摘要。"}}
        record = archive.record_from_feed(item)
        self.assertTrue(record["evidence"])
        self.assertIn("ai", record["related_domains"])
        self.assertTrue(record["reading_context"]["en"])
        record = archive.enrich_record(record)
        page = archive.story_html(record, "en")
        self.assertLess(page.index('<h2>'), page.index('archive-story-meta'))
        self.assertLess(page.index('<details class="screening-details">'), page.index('Importance 85'))
        self.assertIn('story-evidence', page)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_public_data(output, [record])
            exported = json.loads((output / "data/articles.json").read_text())["items"][0]
        self.assertEqual(exported["evidence"], record["evidence"])
        self.assertEqual(exported["related_domains"], record["related_domains"])
        self.assertEqual(exported["reading_context"], record["reading_context"])
        self.assertIn("source_published_at", exported)

    def test_ranked_repository_keeps_legacy_archive_path_but_uses_first_seen(self):
        record = fixture("repo", "ai", "NVIDIA repository")
        record["source"] = "GitHub Trending"
        record["url"] = "https://github.com/NVIDIA/project"
        record["site_published"] = archive.parse_datetime("2026-11-08T02:00:00Z")
        record = archive.enrich_record(record)
        original_day = record["published"].astimezone(archive.LOCAL_TZ).date()
        path = archive.article_path("en", original_day, record)
        self.assertEqual(record["date_basis"], "first_seen")
        self.assertEqual(record["first_seen_at"], "2026-11-08T02:00:00Z")
        self.assertIn("/2026/11/12/", path)
        for locale, label in (("en", "First seen"), ("zh", "首次发现")):
            page = archive.story_html(record, locale)
            self.assertIn(label, page)
            self.assertIn("2026-11-08 10:00 SGT", page)
            self.assertNotIn("2026-11-12 09:00 SGT", page)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_article(output, "en", record)
            self.assertTrue((output / path.lstrip("/") / "index.html").exists())
            archive.render_public_data(output, [record])
            exported = json.loads((output / "data/articles.json").read_text())["items"][0]
        self.assertEqual(exported["first_seen_at"], "2026-11-08T02:00:00Z")
        self.assertIsNone(exported["source_published_at"])
        self.assertEqual(exported["published_at"], "2026-11-12T01:00:00Z")

    def test_ranked_repository_stays_in_permanent_archive_not_daily_news_or_news_sitemap(self):
        ranked = fixture("ranked-repo", "ai", "Ranked NVIDIA repository", 95)
        ranked["source"] = "GitHub Trending"
        release = fixture("release", "ai", "Official repository release", 80)
        release["source"] = "Vendor Releases"
        day = ranked["published"].astimezone(archive.LOCAL_TZ).date()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_daily_brief(output, "en", day, [ranked, release])
            news = (output / archive.daily_brief_path("en", day).lstrip("/") / "index.html").read_text()
            self.assertNotIn(ranked["en"]["title"], news)
            self.assertIn(release["en"]["title"], news)
            archive.render_daily(output, "en", day, [ranked, release], [day])
            permanent = (output / archive.archive_path("en", day).lstrip("/") / "index.html").read_text()
            self.assertIn(ranked["en"]["title"], permanent)
            archive.render_news_sitemap(output, {day: [ranked, release]})
            sitemap = (output / "news-sitemap.xml").read_text()
            self.assertNotIn(ranked["en"]["title"], sitemap)
            self.assertIn(release["en"]["title"], sitemap)


if __name__ == "__main__":
    unittest.main()
