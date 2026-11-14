import json
from pathlib import Path
import re
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import export_archive as archive


def fixture(identifier="test", date="2026-11-12T01:00:00Z", domain="ai"):
    published = archive.parse_datetime(date)
    return {"id": identifier, "domain": domain, "category": "models", "source": "Research Desk",
            "url": "https://example.org/" + identifier, "published": published,
            "source_published": published, "site_published": published, "importance": 80,
            "scores": {key: 80 for key in ("signal", "structure", "consequence", "confidence", "momentum")},
            "image_url": "#", "tags": ["Gemini", "evaluation"],
            "en": {"title": "Gemini evaluation " + identifier, "summary": "An attributed research summary.", "full": "Background\n\nAn attributed research summary."},
            "zh": {"title": "Gemini 评测 " + identifier, "summary": "研究摘要。", "full": "背景\n\n研究摘要。"}}


class ArchiveNavigationTests(unittest.TestCase):
    def test_future_source_site_or_group_date_is_not_discoverable(self):
        now = archive.parse_datetime("2026-11-14T00:00:00Z")
        valid = fixture()
        for key in ("published", "source_published", "site_published"):
            record = fixture("future")
            record[key] = archive.parse_datetime("2026-12-08T01:00:00Z")
            grouped = archive.select_daily([valid, record], now=now)
            self.assertEqual([item["id"] for items in grouped.values() for item in items], ["test"])

    def test_root_is_field_first_and_has_no_article_headlines(self):
        record = fixture()
        grouped = archive.select_daily([record], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for locale in ("en", "zh"):
                archive.render_indexes(output, locale, grouped)
                page = (output / locale / "archive/index.html").read_text()
                self.assertIn('class="archive-field-grid"', page)
                self.assertNotIn(record[locale]["title"], page)
                for domain in archive.DOMAIN_REGISTRY:
                    self.assertIn(archive.archive_field_path(locale, domain), page)
                self.assertLess(page.index('class="archive-field-grid"'), page.index('class="archive-date-browser"'))

    def test_domain_collection_is_static_and_tags_use_scoped_query_links(self):
        record = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_archive_field(output, "en", "ai", [record])
            page = (output / "en/archive/fields/ai/index.html").read_text()
            self.assertIn('data-archive-entry', page)
            self.assertIn('aria-live="polite"', page)
            self.assertIn(record["en"]["title"], page)
            self.assertIn('data-archive-more hidden', page)
            self.assertIn('data-archive-locale', page)
            html = archive.story_html(record, "en", detail=True)
            self.assertIn('/en/archive/fields/ai/?tag=gemini', html)
            record["tags"] = ['<script>alert(1)</script>', 'a&b / 中文']
            html = archive.story_html(record, "en")
            self.assertNotIn('<script>alert(1)</script>', html)
            self.assertIn('tag=a+b+%E4%B8%AD%E6%96%87', html)

    def test_related_reads_are_bilingual_and_do_not_assert_followup(self):
        older = fixture("older", "2026-11-10T01:00:00Z")
        current = fixture("current")
        newer = fixture("newer", "2026-11-13T01:00:00Z")
        # Distinct titles, not repetitions of the same headline.
        older["en"]["title"] = "Gemini verification test suite opens"
        newer["en"]["title"] = "Gemini scientific workflow evaluated by researchers"
        for locale, heading in (("en", "Keep exploring"), ("zh", "继续探索")):
            html = archive.continue_reading_html(current, [current, older, newer], locale)
            self.assertIn(heading, html)
            self.assertIn('data-related-id=', html)
            self.assertNotIn('Follow-up confirmed', html)

    def test_legacy_url_keeps_prose_original_date_and_canonical_without_resurfacing(self):
        record = fixture("old")
        record["en"]["full"] = "Background\n\nKeep this exact historical sentence.\n\nResults\n\nSecond paragraph."
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_article(output, "en", record)
            path = output / "en/archive/2026/11/12/old/index.html"
            original = path.read_text()
            upgraded, _ = archive.refresh_retained_pages(output, [], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
            self.assertEqual(upgraded, 1)
            page = path.read_text()
            self.assertIn("Keep this exact historical sentence.", page)
            self.assertIn("Second paragraph.", page)
            self.assertIn('Historical brief', page)
            self.assertIn('Source published', page)
            self.assertIn('2026-11-12 09:00 SGT', page)
            self.assertIn('Keep exploring', page)
            self.assertIn('href="https://polyemergence.com/en/archive/2026/11/12/old/"', page)
            def schema(html):
                return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', html).group(1))
            self.assertEqual(schema(original)["datePublished"], schema(page)["datePublished"])
            self.assertNotIn('Importance 0', page)
            self.assertFalse((output / 'data/articles.json').exists())

    def test_future_old_urls_stay_accessible_but_noindex(self):
        record = fixture("future", "2026-12-08T01:00:00Z")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_article(output, "en", record)
            upgraded, withheld = archive.refresh_retained_pages(output, [], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
            self.assertEqual(upgraded, 0)
            self.assertEqual(withheld, 1)
            page = (output / "en/archive/2026/12/08/future/index.html").read_text()
            self.assertIn('content="noindex,follow"', page)
            self.assertIn('Publication date under review', page)
            visible = page.split('<script type="application/json" id="archive-retained-snapshot">')[0]
            self.assertNotIn('Keep exploring', visible)
            self.assertEqual(archive.legacy_record(output / "en/archive/2026/12/08/future/index.html", "en")["en"]["title"], record["en"]["title"])
            archive.refresh_retained_pages(output, [], now=archive.parse_datetime("2026-12-09T00:00:00Z"))
            restored = (output / "en/archive/2026/12/08/future/index.html").read_text()
            self.assertIn(record["en"]["title"], restored)
            self.assertIn('Historical brief', restored)

    def test_retained_short_dek_and_unique_lead_facts_are_never_truncated(self):
        record = fixture("short")
        text = "An original short brief with complete evidence. " * 6 + "TAIL_FACT_MUST_SURVIVE."
        record["en"].update(summary=text, full=text)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_article(output, "en", record)
            archive.refresh_retained_pages(output, [], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
            path = output / "en/archive/2026/11/12/short/index.html"
            self.assertIn('TAIL_FACT_MUST_SURVIVE', path.read_text())
            record["en"].update(summary="UNIQUE_LEAD_FACT remains important.", full="Background\n\nDifferent body facts.")
            archive.render_article(output, "en", record)
            archive.refresh_retained_pages(output, [], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
            page = path.read_text()
            self.assertIn('UNIQUE_LEAD_FACT', page)
            self.assertIn('Different body facts', page)

    def test_future_source_date_cannot_bypass_guard_through_legacy_migration(self):
        record = fixture("future-source")
        record["source_published"] = archive.parse_datetime("2026-12-08T01:00:00Z")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_article(output, "en", record)
            upgraded, withheld = archive.refresh_retained_pages(output, [], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
            self.assertEqual((upgraded, withheld), (0, 1))
            path = output / "en/archive/2026/11/12/future-source/index.html"
            self.assertIn('content="noindex,follow"', path.read_text())
            self.assertEqual(archive.legacy_record(path, "en")["source_published"], record["source_published"])

    def test_sitemap_includes_populated_field_archives_without_query_pages(self):
        record = fixture()
        grouped = archive.select_daily([record], now=archive.parse_datetime("2026-11-14T00:00:00Z"))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            archive.render_sitemap(output, grouped)
            page = (output / "archive-sitemap.xml").read_text()
            self.assertIn('/en/archive/fields/ai/', page)
            self.assertNotIn('/archive/fields/quantum_technology/', page)
            self.assertNotIn('?tag=', page)


if __name__ == "__main__":
    unittest.main()
