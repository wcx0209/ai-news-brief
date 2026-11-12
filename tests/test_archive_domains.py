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

    def test_permanent_archive_has_no_trending_quota_and_rss_does_not_republish_rankings(self):
        ranked = [fixture(f"repo-{n}", "ai", f"Ranked repository {n}", 85-n) for n in range(3)]
        for record in ranked:
            record.update(source="GitHub Trending", category="open_source", url="https://github.com/vendor/" + record["id"])
        release = fixture("release", "ai", "Real release")
        grouped = archive.select_daily([*ranked, release])
        day = release["published"].astimezone(archive.LOCAL_TZ).date()
        self.assertEqual({record["id"] for record in grouped[day]}, {"repo-0", "repo-1", "repo-2", "release"})
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_rss(output, "en", grouped)
            rss = (output / "feed-en.xml").read_text()
            self.assertIn(release["en"]["title"], rss)
            for record in ranked:
                self.assertNotIn(record["en"]["title"], rss)

    def test_prior_public_trending_is_preserved_without_restoring_other_removed_content(self):
        def ranked(identifier, date):
            record = fixture(identifier, "ai", "Ranked " + identifier)
            record.update(source="GitHub Trending", category="open_source", url="https://github.com/vendor/" + identifier,
                          published=archive.parse_datetime(date), site_published=archive.parse_datetime("2026-11-08T02:00:00Z"))
            return archive.enrich_record(record)
        prior_match = ranked("matching", "2026-11-09T01:00:00Z")
        prior_missing = ranked("missing", "2026-11-10T01:00:00Z")
        removed_other = fixture("removed-other", "ai", "Intentionally removed news")
        current = ranked("matching", "2026-11-12T01:00:00Z")
        current["importance"] = 91
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_public_data(output, [prior_match, prior_missing, removed_other])
            corpus_path = output / "data/articles.json"
            old = {item["id"]: item for item in json.loads(corpus_path.read_text())["items"]}
            records = archive.preserve_trending_history([current], corpus_path)
            by_id = {record["id"]: record for record in records}
            self.assertEqual(set(by_id), {"matching", "missing"})
            self.assertEqual(by_id["matching"]["importance"], 91, "current editorial data is retained")
            self.assertEqual(by_id["matching"]["published"], prior_match["published"])
            self.assertEqual(by_id["matching"]["first_seen_at"], "2026-11-08T02:00:00Z")
            for record in records:
                for locale in ("en", "zh"):
                    day = record["published"].astimezone(archive.LOCAL_TZ).date()
                    self.assertEqual(archive.SITE + archive.article_path(locale, day, record), old[record["id"]]["canonical_urls"][locale])
                    archive.render_article(output, locale, record)
                    path = archive.article_path(locale, day, record)
                    self.assertTrue((output / path.lstrip("/") / "index.html").is_file())
            archive.render_public_data(output, records)
            new = {item["id"]: item for item in json.loads(corpus_path.read_text())["items"]}
        for identifier in ("matching", "missing"):
            self.assertEqual(new[identifier]["canonical_urls"], old[identifier]["canonical_urls"])
            self.assertEqual(new[identifier]["date_basis"], "first_seen")
            self.assertIsNone(new[identifier]["source_published_at"])

    def test_preserved_canonical_is_narrow_and_cannot_overwrite_another_article(self):
        record = fixture("own-id", "ai", "Ranked own repository")
        record["source"] = "GitHub Trending"
        record["canonical_urls"] = {
            "en": "https://polyemergence.com/en/archive/2026/11/08/own-id/",
            "zh": "https://polyemergence.com/zh/archive/2026/11/08/another-id/",
        }
        day = record["published"].astimezone(archive.LOCAL_TZ).date()
        self.assertEqual(archive.article_path("en", day, record), "/en/archive/2026/11/08/own-id/")
        self.assertEqual(archive.article_path("zh", day, record), "/zh/archive/2026/11/12/own-id/")
        record["source"] = "Official Releases"
        self.assertEqual(archive.article_path("en", day, record), "/en/archive/2026/11/12/own-id/")

    def test_article_prose_has_real_headings_paragraphs_and_lists_in_original_order(self):
        text = """Overview
First paragraph preserves the reported result.

How It Works
The method runs in two stages.

### Technical limits
- First limitation.
- Second limitation.

Installation and Usage
1. Clone the project.
2. Run the supplied tools.

Final paragraph preserves the uncertainty."""
        prose = archive.archive_prose(text)
        self.assertIn('<div class="archive-prose">', prose)
        self.assertIn('<h2>Overview</h2><p>First paragraph', prose)
        self.assertIn('<h2>How It Works</h2>', prose)
        self.assertIn('<h3>Technical limits</h3>', prose)
        self.assertIn('<ul><li>First limitation.</li><li>Second limitation.</li></ul>', prose)
        self.assertIn('<ol><li value="1">Clone the project.</li><li value="2">Run the supplied tools.</li></ol>', prose)
        self.assertLess(prose.index("First paragraph"), prose.index("How It Works"))
        self.assertLess(prose.index("Second limitation"), prose.index("Clone the project"))
        self.assertTrue(prose.endswith('<p>Final paragraph preserves the uncertainty.</p></div>'))

    def test_chinese_plain_headings_are_recognised_without_guessing_sentences(self):
        prose = archive.archive_prose("系统架构\n系统由三个组件构成。\n\n安装与使用\n• 下载工具。\n• 阅读文档。\n\n这是一句普通的短句。\n下一句保留原有内容。")
        self.assertIn('<h2>系统架构</h2>', prose)
        self.assertIn('<h2>安装与使用</h2>', prose)
        self.assertIn('<ul><li>下载工具。</li><li>阅读文档。</li></ul>', prose)
        self.assertNotIn('<h2>这是一句', prose)
        self.assertIn('下一句保留原有内容。', prose)

    def test_prose_xss_and_markdown_links_are_inert_and_code_survives(self):
        text = '''## <img src=x onerror="alert(1)">
[Safe label](https://example.org/read) and [Unsafe label](javascript:alert(2))

<script>alert(3)</script>

```html
<img src=x onerror="alert(4)">
```

The last sentence is still here.'''
        prose = archive.archive_prose(text)
        self.assertNotIn('<img', prose)
        self.assertNotIn('<script', prose)
        self.assertNotIn('<a ', prose)
        self.assertNotIn('href=', prose)
        self.assertIn('&lt;img src=x onerror=&quot;alert(1)&quot;&gt;', prose)
        self.assertIn('Safe label', prose)
        self.assertIn('Unsafe label', prose)
        self.assertIn('<pre><code>&lt;img src=x onerror=&quot;alert(4)&quot;&gt;</code></pre>', prose)
        self.assertIn('The last sentence is still here.', prose)

    def test_detail_retains_entire_long_summary_but_archive_list_uses_short_preview(self):
        record = fixture("long-detail", "ai", "A detailed reported result")
        paragraphs = [f"Paragraph {index}: measured result {index}, with uncertainty retained." for index in range(100)]
        record["en"]["full"] = "## Overview\n\n" + "\n\n".join(paragraphs)
        record["en"]["summary"] = "A concise overview of the reported result."
        record["reading_context"] = {"en": "Generic editorial reading guidance."}
        detailed = archive.story_html(record, "en", detail=True)
        preview = archive.story_html(record, "en")
        self.assertIn('<h1>A detailed reported result</h1>', detailed)
        self.assertIn('<div class="archive-prose"><h2>Overview</h2>', detailed)
        for paragraph in paragraphs:
            self.assertIn(paragraph, detailed)
        self.assertNotIn("Paragraph 99:", preview)
        self.assertIn('<p class="archive-summary">A concise overview', preview)
        self.assertIn('Read full summary', preview)
        self.assertLess(detailed.index('<details class="screening-details">'), detailed.index('Generic editorial reading guidance.'))
        self.assertLess(preview.index('<details class="screening-details">'), preview.index('Generic editorial reading guidance.'))

    def test_missing_short_summary_is_bounded_in_list_not_detail(self):
        record = fixture("missing-short", "ai", "A long report")
        record["en"]["summary"] = ""
        record["en"]["full"] = "An original result with disclosed limitations. " * 100 + "Unique final caveat."
        self.assertLessEqual(len(archive.archive_excerpt(record["en"], "en")), 521)
        self.assertNotIn("Unique final caveat.", archive.story_html(record, "en"))
        self.assertIn("Unique final caveat.", archive.story_html(record, "en", detail=True))

    def test_article_shell_uses_scoped_reading_layout_and_versioned_archive_styles(self):
        page = archive.page_shell("en", "Title", "Description", "https://polyemergence.com/en/archive/2026/11/12/id/", "https://polyemergence.com/zh/archive/2026/11/12/id/", "Body", og_type="article")
        self.assertIn('<body class="archive-detail">', page)
        self.assertIn('/archive.css?v=6', page)
        styles = (ROOT / "web/public/archive.css").read_text()
        self.assertRegex(styles, r'\.archive-prose\s*\{[^}]*max-width:\s*760px')
        self.assertRegex(styles, r'\.archive-prose\s*\{[^}]*font-size:\s*16px;\s*line-height:\s*1\.78')


if __name__ == "__main__":
    unittest.main()
