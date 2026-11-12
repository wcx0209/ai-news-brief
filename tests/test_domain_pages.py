"""Field pages must be useful without JS and retain truthful publication gates."""

import importlib.util
import json
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("export_domain_pages", ROOT / "scripts/export_domain_pages.py")
pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pages)


SHELL = '''<!doctype html><html lang="en"><head><title>Home</title>
<meta name="description" content="Home"><meta property="og:title" content="Home">
<meta property="og:description" content="Home"><meta property="og:url" content="https://polyemergence.com/en/">
<meta name="twitter:title" content="Home"><meta name="twitter:description" content="Home">
<link rel="canonical" href="https://polyemergence.com/en/">
<link rel="alternate" hreflang="en" href="https://polyemergence.com/en/">
<link rel="alternate" hreflang="zh-Hans" href="https://polyemergence.com/zh/">
<link rel="alternate" hreflang="x-default" href="https://polyemergence.com/en/">
<script type="application/ld+json">{"@type":"CollectionPage","name":"Home"}</script></head><body>
<a href="/en/" data-locale-button="en">EN</a><a href="/zh/" data-locale-button="zh">中</a>
<a class="choose-field-link" href="#fields" data-fields-link>Choose field</a>
<h1 id="intro-title" data-copy="tagline">Home</h1><p data-copy="promise">Home</p><p data-copy="eyebrow">Home</p>
<span id="update-status">Loading</span><section id="fields"><div class="field-grid" id="field-grid" aria-label="News fields"><a href="/stale-card/">Stale card</a></div></section>
<section id="brief" hidden><span id="selected-field-label"></span><h2 id="brief-title"></h2>
<p id="field-description"></p><div id="lead-story"></div><div id="story-grid"></div><div id="empty-state" hidden></div></section>
<section id="field-seo-content" class="field-seo-content" hidden></section>
<footer>PolyEmergence Pte Ltd. Singapore <nav class="footer-topics" aria-label="Fields"><a href="/stale-footer/">Stale footer</a></nav><a href="/en/standards/">Editorial standards</a></footer>
</body></html>'''


class DomainPagesTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 11, 12, 12, tzinfo=timezone.utc)
        self.domains = [
            {"id": "ai", "label": {"en": "Artificial Intelligence", "zh": "人工智能"}, "description": {"en": "AI coverage", "zh": "人工智能报道"}},
            {"id": "programmable_life", "label": {"en": "Programmable Life", "zh": "可编程生命"}, "description": {"en": "Engineering life", "zh": "工程化生命"}, "source_categories": ["biotech"]},
        ]
        self.sources = [
            ("https://research.example/feed/", 'Lab <R&D> "Official"', "[FIRST_PARTY] Research", "biotech", 90),
            ("https://ai.example/rss.xml", "AI lab", "Official AI", "news", 95),
        ]

    def item(self, item_id="current", **changes):
        value = {"id": item_id, "domain": "programmable_life", "source": "Research Lab", "url": f"https://research.example/{item_id}", "source_published_at": (self.now - timedelta(hours=1)).isoformat(), "importance": 80, "en": {"title": f"Current biology {item_id}", "summary": "Evidence and the result."}, "zh": {"title": "生命研究进展", "summary": "实验结果及证据。"}}
        value.update(changes)
        return value

    def render(self, items, public, locale="en", corpus=None, domain=None):
        return pages.render_field_page(SHELL, domain or self.domains[1], locale, self.domains, {"generated_at": self.now.isoformat(), "items": items}, self.sources, corpus or {}, public, self.now)

    def export_fixture(self, public, domains):
        for locale in ("en", "zh"):
            (public / locale).mkdir()
            (public / locale / "index.html").write_text(SHELL, encoding="utf-8")
        registry = public / "registry.json"
        registry.write_text(json.dumps({"domains": domains}), encoding="utf-8")
        feed = public / "feed.json"
        feed.write_text(json.dumps({"items": [self.item()]}), encoding="utf-8")
        sources = public / "sources.py"
        sources.write_text("SOURCES = " + repr(self.sources), encoding="utf-8")
        return registry, feed, sources

    def test_publication_window_and_domain_are_enforced_in_visible_html_and_jsonld(self):
        items = [self.item(), self.item("boundary", source_published_at=(self.now - timedelta(hours=48)).isoformat()), self.item("old", source_published_at=(self.now - timedelta(hours=48, seconds=1)).isoformat()), self.item("future", source_published_at=(self.now + timedelta(seconds=1)).isoformat()), self.item("missing", source_published_at=None), self.item("other", domain="ai"), self.item("unsafe", url="javascript:alert(1)"), self.item()]
        with tempfile.TemporaryDirectory() as folder:
            result = self.render(items, Path(folder))
        self.assertIn("Current biology current", result)
        self.assertIn("Current biology boundary", result)
        for marker in ("old", "future", "missing", "other", "unsafe"):
            self.assertNotIn(f"Current biology {marker}", result)
        graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', result, re.S)[1])["@graph"]
        self.assertEqual(graph[-1]["numberOfItems"], 2)
        self.assertNotIn("NewsArticle", [node["@type"] for node in graph])
        self.assertIn('<section id="brief">', result)
        self.assertIn('datetime="2026-11-12T11:00:00Z"', result)

    def test_markup_and_script_data_escape_untrusted_titles_and_source_names(self):
        title = '</script><img src=x onerror="alert(1)"> & "quoted"'
        item = self.item(en={"title": title, "summary": "<script>alert(2)</script>"})
        with tempfile.TemporaryDirectory() as folder:
            result = self.render([item], Path(folder))
        self.assertNotIn('<img src=x', result)
        self.assertNotIn('<script>alert(2)', result)
        self.assertIn('&lt;img src=x', result)
        self.assertIn('Lab &lt;R&amp;D&gt; &quot;Official&quot;', result)
        graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', result, re.S)[1])["@graph"]
        self.assertEqual(graph[-1]["itemListElement"][0]["name"], title)

    def test_canonical_language_links_and_archive_target_exist(self):
        item = self.item()
        canonical = "https://polyemergence.com/en/archive/2026/11/12/current/"
        corpus = {"current": {"canonical_urls": {"en": canonical}}}
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            missing = self.render([item], public, corpus=corpus)
            self.assertNotIn(canonical, missing)
            archive = public / "en/archive/2026/11/12/current/index.html"
            archive.parent.mkdir(parents=True)
            archive.write_text("A real archived summary", encoding="utf-8")
            result = self.render([item], public, corpus=corpus)
            self.assertIn(canonical, result)
            zh = self.render([item], public, locale="zh", corpus=corpus)
        for page in (result, zh):
            self.assertIn('hreflang="en" href="https://polyemergence.com/en/fields/programmable_life/"', page)
            self.assertIn('hreflang="zh-Hans" href="https://polyemergence.com/zh/fields/programmable_life/"', page)
            self.assertIn('hreflang="x-default" href="https://polyemergence.com/en/fields/programmable_life/"', page)
            self.assertIn('data-field="programmable_life"', page)
        self.assertIn('rel="canonical" href="https://polyemergence.com/zh/fields/programmable_life/"', zh)
        self.assertIn('href="/zh/fields/programmable_life/" data-locale-button="zh"', result)

    def test_empty_and_future_registered_fields_have_honest_useful_pages(self):
        domain = {"id": "new_field", "label": {"en": "New field", "zh": "新领域"}, "description": {"en": "A real scope", "zh": "具体报道范围"}, "seo": {"en": {"heading": "Custom field news", "intro": "Custom editorial scope"}}}
        with tempfile.TemporaryDirectory() as folder:
            result = self.render([], Path(folder), domain=domain)
        self.assertIn("Custom field news", result)
        self.assertIn("Custom editorial scope", result)
        self.assertIn("No qualifying stories from the past 48 hours", result)
        self.assertIn('<div id="lead-story" hidden>', result)
        self.assertIn('<section id="field-seo-content" class="field-seo-content" data-field="new_field">', result)
        self.assertNotIn('"@type":"NewsArticle"', result)
        self.assertEqual(pages.item_domain({"category": "biotech"}, self.domains), "programmable_life")
        self.assertEqual(pages.field_sources("programmable_life", self.sources, self.domains)[0][1], 'Lab <R&D> "Official"')

    def test_export_expands_registry_to_both_languages_and_sitemap(self):
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            registry, feed, sources = self.export_fixture(public, self.domains)
            self.assertEqual(pages.export(public, registry, feed, sources, now=self.now), 4)
            sitemap = (public / "field-sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("/en/fields/programmable_life/", sitemap)
            self.assertIn("/zh/fields/ai/", sitemap)
            self.assertEqual(len(list(public.glob("*/fields/*/index.html"))), 4)

    def test_new_registered_field_syncs_escaped_home_and_field_page_navigation(self):
        new_domain = {"id": "new_field", "order": 1, "label": {"en": 'New <field> & "science"', "zh": '新<领域>与"科技"'}, "short_label": {"en": "New <&>", "zh": "新<&>"}, "description": {"en": 'A <scope> & "evidence"', "zh": '有<范围>与"证据"'}}
        domains = [*self.domains, new_domain]
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            registry, feed, sources = self.export_fixture(public, domains)
            self.assertEqual(pages.export(public, registry, feed, sources, now=self.now), 6)
            for locale in ("en", "zh"):
                home = (public / locale / "index.html").read_text(encoding="utf-8")
                field = (public / locale / "fields/new_field/index.html").read_text(encoding="utf-8")
                for result in (home, field):
                    grid = re.search(r'<div class="field-grid" id="field-grid"[^>]*>(.*?)</div>', result, re.S)[1]
                    footer = re.search(r'<nav class="footer-topics"[^>]*>(.*?)</nav>', result, re.S)[1]
                    self.assertEqual(grid.count('class="field-card"'), 3)
                    self.assertEqual(footer.count("<a "), 3)
                    self.assertTrue(grid.startswith(f'<a class="field-card" href="/{locale}/fields/new_field/#brief">'))
                    self.assertIn('<span class="field-number">01</span>', grid)
                    self.assertIn(pages.esc(new_domain["label"][locale]), grid)
                    self.assertIn(pages.esc(new_domain["description"][locale]), grid)
                    self.assertIn(f'<a href="/{locale}/fields/new_field/">{pages.esc(new_domain["short_label"][locale])}</a>', footer)
                    self.assertIn(f'<a href="/{locale}/fields/ai/">{pages.esc(self.domains[0]["label"][locale])}</a>', footer)
                    self.assertNotIn("/stale-card/", result)
                    self.assertNotIn("/stale-footer/", result)
                    self.assertNotIn("<field>", result)
                    self.assertIn('aria-label="News fields"', result)
                    self.assertIn('aria-label="Fields"', result)
                self.assertIn(f'rel="canonical" href="https://polyemergence.com/{locale}/fields/new_field/"', field)
                self.assertIn('data-field="new_field"', field)
            sitemap = (public / "field-sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("/en/fields/new_field/", sitemap)
            self.assertIn("/zh/fields/new_field/", sitemap)

    def test_export_rejects_unsafe_registry_id_before_changing_outputs(self):
        for unsafe_id in ("../escape", 'field" onclick="alert(1)', "", None, 12):
            with self.subTest(field_id=unsafe_id), tempfile.TemporaryDirectory() as folder:
                public = Path(folder)
                invalid = {"id": unsafe_id, "label": {"en": "Unsafe", "zh": "非法领域"}}
                registry, feed, sources = self.export_fixture(public, [*self.domains, invalid])
                with self.assertRaisesRegex(ValueError, "Invalid field id"):
                    pages.export(public, registry, feed, sources, now=self.now)
                for locale in ("en", "zh"):
                    self.assertEqual((public / locale / "index.html").read_text(encoding="utf-8"), SHELL)
                    self.assertFalse((public / locale / "fields").exists())
                self.assertFalse((public / "field-sitemap.xml").exists())


if __name__ == "__main__":
    unittest.main()
