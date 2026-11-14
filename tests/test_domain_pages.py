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
<section id="brief" hidden><p id="edition-note" class="edition-note"></p><aside id="field-reading-guidance" class="field-reading-guidance" hidden></aside><span id="selected-field-label"></span><h2 id="brief-title"></h2>
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

    def test_server_rendered_images_include_bounded_candidates_and_retry_without_cropping(self):
        item = self.item(image_url="https://research.example/image.png", image_candidates=["https://research.example/image.png", "https://cdn.example/backup.png", "javascript:alert(1)"])
        with tempfile.TemporaryDirectory() as folder:
            result = self.render([item], Path(folder))
        self.assertIn('data-image-candidates=', result)
        self.assertIn('https://cdn.example/backup.png', result)
        self.assertIn('data-image-retry hidden', result)
        self.assertIn('media-contain', result)
        self.assertNotIn('javascript:alert(1)', result)
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

    def test_reading_order_unique_h1_and_old_feed_screening_floor(self):
        items = [self.item("normal", image_url="https://research.example/image.png"), self.item("weak", importance=64), self.item("academic-low", category="academia", importance=69, scores={"confidence": 90}),
                 *[self.item(f"academic-{n}", category="academia", importance=90-n, scores={"confidence": 80}, image_url="https://research.example/image.png") for n in range(4)]]
        with tempfile.TemporaryDirectory() as folder:
            result = self.render(items, Path(folder))
        self.assertEqual(len(re.findall(r'<h1\b', result)), 1)
        self.assertIn('<body class="is-field-page">', result)
        self.assertNotIn('Current biology weak', result)
        self.assertNotIn('Current biology academic-low', result)
        self.assertNotIn('Current biology academic-2', result)
        self.assertIn('data-story-id="academic-0"', result)
        card = re.search(r'<article class="story-card\b[^"]*".*?</article>', result, re.S)[0]
        self.assertLess(card.index('<h3>'), card.index('story-meta'))
        self.assertLess(card.index('card-copy'), card.index('card-visual'))
        self.assertLess(card.index('story-heading'), card.index('card-visual'))
        self.assertLess(card.index('card-visual'), card.index('story-body'))
        self.assertLess(card.index('story-body'), card.index('story-summary'))
        self.assertIn('story-evidence', card)
        self.assertNotIn('story-context', card)
        self.assertEqual(result.count('id="field-reading-guidance"'), 1)
        self.assertEqual(result.count('General field guidance, not verification of this story.'), 1)
        self.assertIn('details class="screening-details"', card)
        self.assertIn('<h2 id="brief-title">Today’s selection</h2>', result)
        lead = re.search(r'<div id="lead-story"[^>]*>(.*?)<div id="story-grid"', result, re.S)[1]
        self.assertLess(lead.index('story-heading'), lead.index('story-visual'))
        self.assertLess(lead.index('story-visual'), lead.index('story-body'))

    def test_edition_has_one_lead_three_features_and_text_only_remaining_briefs(self):
        items = [self.item(str(n), importance=90-n, image_url=None if n == 2 else "https://research.example/image.png") for n in range(8)]
        with tempfile.TemporaryDirectory() as folder:
            for locale in ("en", "zh"):
                result = self.render(items, Path(folder), locale=locale)
                self.assertEqual(result.count('class="feature-section"'), 1)
                self.assertEqual(result.count('class="brief-section"'), 1)
                self.assertEqual(len(re.findall(r'<article class="story-card is-feature', result)), 3)
                self.assertEqual(len(re.findall(r'<article class="story-card is-brief', result)), 4)
                self.assertIn('class="story-card is-feature" data-story-id="2"', result)
                self.assertIn('is-editorial-visual', result)
                self.assertIn("非原文图片" if locale == "zh" else "Not a source image", result)
                brief_section = re.search(r'<section class="brief-section">(.*?)</section>', result, re.S)[1]
                self.assertNotIn('<figure', brief_section)
                self.assertNotIn('<img', brief_section)
                self.assertNotIn('text-edition-note', brief_section)
                self.assertIn("更多简讯" if locale == "zh" else "More briefs", brief_section)
                self.assertIn("2026-11-12 20:00 SGT", result)
                self.assertIn("原文发布 48 小时窗口" if locale == "zh" else "48-hour source publication window", result)
                self.assertEqual(len(re.findall(r'<h1\b', result)), 1)
        for count in (0, 1, 3):
            with self.subTest(count=count), tempfile.TemporaryDirectory() as folder:
                result = self.render(items[:count], Path(folder))
                self.assertNotIn('class="brief-section"', result)
                self.assertEqual(result.count('class="feature-section"'), 1 if count > 1 else 0)

    def test_source_figures_have_conservative_caption_and_small_failure_note(self):
        item = self.item(image_url="https://research.example/image.png", source='Lab <script>alert(1)</script>')
        with tempfile.TemporaryDirectory() as folder:
            for lead in (False, True):
                rendered = pages.story_markup(item, "en", {}, Path(folder), lead=lead)
                visual_class = "story-visual" if lead else "card-visual"
                self.assertIn(f'<figure class="{visual_class}" data-media-source=', rendered)
                self.assertIn('<div class="visual-media"><img', rendered)
                self.assertIn('data-fallback-image', rendered)
                self.assertIn('data-image-unavailable-note hidden', rendered)
                self.assertIn('<figcaption class="media-caption" data-source-caption><a href="https://research.example/current"', rendered)
                self.assertIn('data-editorial-artwork hidden', rendered)
                self.assertIn('data-editorial-caption hidden', rendered)
                self.assertIn('Source image · Lab &lt;script&gt;', rendered)
                self.assertNotIn('<script>alert(1)</script>', rendered)
                self.assertNotIn('Photo by', rendered)
                self.assertNotIn('<svg', rendered)
                self.assertLess(rendered.index('story-heading'), rendered.index('<figure'))
                self.assertLess(rendered.index('<figure'), rendered.index('story-body'))
            video = self.item(url="https://www.youtube.com/watch?v=9J1iZuOUbx8")
            rendered = pages.story_markup(video, "zh", {}, Path(folder))
            self.assertIn('https://i.ytimg.com/vi/9J1iZuOUbx8/hqdefault.jpg', rendered)
            self.assertIn('视频缩略图 · Research Lab', rendered)
            invalid_video = self.item(url="https://www.youtube.com/watch?v=not-an-id", image_url="https://research.example/image.png")
            rendered = pages.story_markup(invalid_video, "en", {}, Path(folder))
            self.assertIn('Source image · Research Lab', rendered)
            self.assertNotIn('Video thumbnail', rendered)
            self.assertNotIn('i.ytimg.com', rendered)
            text_only = pages.story_markup(self.item(), "en", {}, Path(folder), lead=True)
            self.assertIn('Not a source image', text_only)
            self.assertIn('<figure class="story-visual is-editorial-visual"', text_only)
            self.assertIn('/assets/editorial/programmable_life.svg', text_only)
            self.assertNotIn('data-fallback-image', text_only)
            self.assertNotIn('<svg', text_only)

    def test_clean_text_preserves_technical_double_underscore_identifiers(self):
        text = "`__init__` keeps __checkpoint_key__ unchanged"
        self.assertEqual(pages.clean_text(text), "__init__ keeps __checkpoint_key__ unchanged")

    def test_details_keep_tags_and_unknown_stage_out_of_heading_without_generic_article_context(self):
        item = self.item(en={"title": "A complete title", "summary": "Short readable preview.", "full_summary": "A longer summary with full detail."},
                         tags=['<script>alert(1)</script>', "biology"])
        with tempfile.TemporaryDirectory() as folder:
            for lead in (False, True):
                rendered = pages.story_markup(pages.enrich_item(item), "en", {}, Path(folder), lead=lead, domains=self.domains)
                heading, body = rendered.split('class="story-body"', 1)
                self.assertNotIn("Stage not specified", heading)
                self.assertNotIn("story-context", heading)
                self.assertNotIn('class="tags"', heading)
                self.assertIn('<span class="story-source">Research Lab</span>', heading)
                self.assertIn('class="story-published"><time', heading)
                self.assertIn('<details class="summary-details" data-summary-details>', body)
                self.assertIn('<div class="summary-full" data-summary-full><p>A longer summary with full detail.</p></div>', body)
                screening = re.search(r'<details class="screening-details">(.*?)</details>', body, re.S)[1]
                self.assertIn("Stage not specified", screening)
                self.assertNotIn("story-context", screening)
                self.assertIn('class="tags"', screening)
                self.assertIn("not independent verification", screening)
                self.assertNotIn('<script>alert(1)</script>', rendered)
                self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', rendered)
                self.assertNotIn('class="screening-details" open', rendered)

    def test_native_summary_expansion_keeps_full_text_when_only_short_summary_exists(self):
        summary = "A full original summary that must remain readable. " * 12
        item = self.item(en={"title": "Long summary", "summary": summary})
        with tempfile.TemporaryDirectory() as folder:
            rendered = pages.story_markup(item, "en", {}, Path(folder))
        full = re.search(r'<div class="summary-full" data-summary-full>(.*?)</div>', rendered, re.S)[1]
        self.assertEqual(full, "<p>" + pages.esc(summary.strip()) + "</p>")
        self.assertIn('<p class="summary-preview" data-summary-short>', rendered)
        self.assertIn('<summary>Expand summary</summary>', rendered)
        self.assertNotIn('class="summary-details" open', rendered)

    def test_expanded_summary_has_only_explicit_headings_safe_paragraphs_and_inline_markup(self):
        summary = ('## 背景\n\n正文 **重点** 与 `__init__`。\n保留本段第二行。\n\n'
                   '自然语言标题不会被猜成 heading\n\n'
                   '### Evidence\n\n<script>alert(1)</script> 与 `<img src=x onerror="bad()">`\n\n'
                   'Inline ## marker stays text, and __checkpoint_key__ stays intact.')
        rendered = pages.summary_blocks(summary)
        self.assertTrue(rendered.startswith('<h4>背景</h4><p>'))
        self.assertIn('<strong>重点</strong>', rendered)
        self.assertIn('<code>__init__</code>', rendered)
        self.assertIn('保留本段第二行。', rendered)
        self.assertIn('<p>自然语言标题不会被猜成 heading</p>', rendered)
        self.assertIn('<h4>Evidence</h4>', rendered)
        self.assertIn('Inline ## marker stays text, and __checkpoint_key__ stays intact.', rendered)
        self.assertNotIn('<script>', rendered)
        self.assertNotIn('<img', rendered)
        self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', rendered)
        self.assertIn('<code>&lt;img src=x onerror=&quot;bad()&quot;&gt;</code>', rendered)
        self.assertEqual(pages.summary_blocks('`**literal**`'), '<p><code>**literal**</code></p>')
        self.assertEqual(pages.summary_blocks('##背景与定位\n\n#include <stdio.h>'), '<h4>背景与定位</h4><p>#include &lt;stdio.h&gt;</p>')

    def test_github_rankings_cannot_become_daily_news_but_releases_can(self):
        ranked = self.item("ranked", source="GitHub Trending", source_published_at=self.now.isoformat())
        release = self.item("release", source="NVIDIA Official Releases", url="https://github.com/NVIDIA/project/releases/tag/v2")
        with tempfile.TemporaryDirectory() as folder:
            result = self.render([ranked, release], Path(folder))
        self.assertNotIn("Current biology ranked", result)
        self.assertIn("Current biology release", result)

    def test_observations_are_separate_escaped_and_link_original_even_with_archive(self):
        evidence = {"title": {"en": '<script>alert(1)</script>', "zh": "原文"}, "source": '<img onerror="evil()">',
                    "date": self.now.isoformat(), "url": "https://research.example/evidence", "canonical_urls": {"en": "https://polyemergence.com/en/archive/2026/11/12/evidence/"}}
        card = {"title": {"en": "A reading question"}, "change": {"en": "A hypothesis, not a forecast"}, "uncertainty": {"en": "No independent confirmation"}, "next_check": {"en": "Check repeated performance"}, "status": "unverified_signal", "evidence": [evidence]}
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            html = pages.render_field_page(SHELL, self.domains[1], "en", self.domains, {"items": []}, self.sources, {}, public, self.now, {"generated_at": self.now.isoformat(), "fields": {"programmable_life": [card]}})
            self.assertIn('id="field-observations" class="field-observations" data-field="programmable_life"', html)
            self.assertIn('30-day evidence snapshot as of', html)
            self.assertIn('class="observation-snapshot-time"', html)
            self.assertIn('2026-11-12 20:00 SGT', html)
            self.assertIn('data-generated-at="2026-11-12T12:00:00Z"', html)
            self.assertIn('data-window-start="2026-10-13T12:00:00Z"', html)
            self.assertIn('href="/en/fields/programmable_life/#field-observations"', html)
            self.assertEqual(len(re.findall(r'<h1\b', html)), 1)
            self.assertIn('Signal to examine', html)
            self.assertIn('No qualifying stories from the past 48 hours', html)
            self.assertIn('href="https://research.example/evidence"', html)
            self.assertNotIn('href="https://polyemergence.com/en/archive/2026/11/12/evidence/"', html)
            self.assertNotIn('<script>alert(1)</script>', html)
            self.assertIn('&lt;script&gt;alert(1)&lt;/script&gt;', html)
            archive = public / "en/archive/2026/11/12/evidence/index.html"
            archive.parent.mkdir(parents=True)
            archive.write_text("Real archive")
            html = pages.observation_markup([card], "en", public, self.now)
            self.assertIn('href="https://research.example/evidence"', html)
            self.assertIn('href="https://polyemergence.com/en/archive/2026/11/12/evidence/"', html)
            evidence["date"] = (self.now - timedelta(days=31)).isoformat()
            self.assertEqual(pages.observation_markup([card], "en", public, self.now), "")

    def test_export_expands_registry_to_both_languages_and_sitemap(self):
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            registry, feed, sources = self.export_fixture(public, self.domains)
            self.assertEqual(pages.export(public, registry, feed, sources, now=self.now), 6)
            sitemap = (public / "field-sitemap.xml").read_text(encoding="utf-8")
            self.assertIn("/en/fields/programmable_life/", sitemap)
            self.assertIn("/zh/fields/ai/", sitemap)
            self.assertIn("/en/tech-news/", sitemap)
            self.assertIn("/zh/tech-news/", sitemap)
            self.assertEqual(len(list(public.glob("*/fields/*/index.html"))), 4)
            self.assertEqual(len(list(public.glob("*/tech-news/index.html"))), 2)

    def test_new_registered_field_syncs_escaped_home_and_field_page_navigation(self):
        new_domain = {"id": "new_field", "order": 1, "label": {"en": 'New <field> & "science"', "zh": '新<领域>与"科技"'}, "short_label": {"en": "New <&>", "zh": "新<&>"}, "description": {"en": 'A <scope> & "evidence"', "zh": '有<范围>与"证据"'}}
        domains = [*self.domains, new_domain]
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            registry, feed, sources = self.export_fixture(public, domains)
            self.assertEqual(pages.export(public, registry, feed, sources, now=self.now), 8)
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

    def test_all_registered_fields_have_distinct_useful_bilingual_seo_and_one_guidance(self):
        domains = json.loads((ROOT / "web/public/data/editorial-domains.json").read_text())["domains"]
        self.assertEqual(len(domains), 11)
        source_catalog = pages.load_sources(ROOT / "scripts/bootstrap_sources.py")
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            for locale in ("en", "zh"):
                titles, descriptions = set(), set()
                for domain in domains:
                    with self.subTest(locale=locale, domain=domain["id"]):
                        result = pages.render_field_page(SHELL, domain, locale, domains, {"items": []}, source_catalog, {}, public, self.now)
                        copy = pages.seo_copy(domain, locale)
                        titles.add(copy["title"])
                        descriptions.add(copy["description"])
                        self.assertLess(len(copy["title"]), 75)
                        self.assertIn(f'<title>{pages.esc(copy["title"])}</title>', result)
                        self.assertIn(f'content="{pages.esc(copy["description"])}"', result)
                        self.assertIn(pages.esc(copy["intro"]), result)
                        self.assertIn(pages.esc(copy["scope"]), result)
                        self.assertEqual(len(re.findall(r'<h1\b', result)), 1)
                        self.assertEqual(result.count('id="field-reading-guidance"'), 1)
                        self.assertEqual(result.count('General field guidance, not verification of this story.' if locale == "en" else '领域通用指引，不是对单篇报道的核验结论。'), 1)
                        self.assertIn(f'href="/{locale}/tech-news/"', result)
                        self.assertIn('class="field-related-links"', result)
                        self.assertIn('id="field-sources"', result)
                        self.assertNotIn('"@type":"FAQPage"', result)
                        graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', result, re.S)[1])["@graph"]
                        self.assertEqual(graph[-1]["numberOfItems"], 0)
                        for node in graph:
                            self.assertNotIn("datePublished", node)
                            self.assertNotIn("dateModified", node)
                        self.assertIn('No qualifying stories from the past 48 hours' if locale == "en" else '最近 48 小时内暂无符合筛选标准的新闻', result)
                self.assertEqual(len(titles), len(domains))
                self.assertEqual(len(descriptions), len(domains))

    def test_tech_news_hub_is_a_bilingual_field_directory_with_true_counts_not_news_stream(self):
        feed = {"generated_at": self.now.isoformat(), "items": [self.item(), self.item("ai-story", domain="ai"),
                self.item("old", source_published_at=(self.now - timedelta(hours=49)).isoformat()),
                self.item("future", source_published_at=(self.now + timedelta(hours=1)).isoformat()),
                self.item("ranked", source="GitHub Trending"), self.item("weak", importance=64)]}
        for locale in ("en", "zh"):
            with self.subTest(locale=locale):
                result = pages.render_hub_page(SHELL, locale, self.domains, feed, self.sources, self.now)
                self.assertIn('data-page="tech-news"', result)
                self.assertIn('class="is-tech-news-page"', result)
                self.assertIn('id="tech-news-hub"', result)
                self.assertIn('id="fields" hidden', result)
                self.assertIn('id="brief" hidden', result)
                self.assertEqual(result.count('class="tech-news-card"'), 2)
                self.assertEqual(len(re.findall(r'<h1\b', result)), 1)
                self.assertIn('data-field-count="ai">1 selected story · 48h' if locale == "en" else 'data-field-count="ai">已精选 1 条 · 48 小时', result)
                self.assertIn('data-field-count="programmable_life">1 selected story · 48h' if locale == "en" else 'data-field-count="programmable_life">已精选 1 条 · 48 小时', result)
                self.assertNotIn('Current biology', result)
                self.assertNotIn('生命研究进展', result)
                for path in (f'/{locale}/standards/', f'/{locale}/archive/', f'/{locale}/fields/ai/#brief', f'/{locale}/fields/programmable_life/#field-sources'):
                    self.assertIn(f'href="{path}"', result)
                self.assertIn('Lab &lt;R&amp;D&gt; &quot;Official&quot;', result)
                self.assertIn(f'rel="canonical" href="https://polyemergence.com/{locale}/tech-news/"', result)
                self.assertIn('hreflang="en" href="https://polyemergence.com/en/tech-news/"', result)
                self.assertIn('hreflang="zh-Hans" href="https://polyemergence.com/zh/tech-news/"', result)
                graph = json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', result, re.S)[1])["@graph"]
                self.assertEqual(graph[-1]["numberOfItems"], 2)
                self.assertEqual([item["url"] for item in graph[-1]["itemListElement"]], [pages.SITE + pages.field_path(locale, domain["id"]) for domain in self.domains])
                self.assertNotIn('NewsArticle', result)

    def test_hub_empty_future_registry_and_untrusted_copy_remain_useful_and_escaped(self):
        domain = {"id": "new_field", "label": {"en": '<img src=x onerror="bad()"> & future'},
                  "description": {"en": 'A <scope> & "evidence"'}, "reading_guidance": {"en": "Check <script>bad()</script> safely"}}
        domains = [*self.domains, domain]
        result = pages.render_hub_page(SHELL, "en", domains, {"items": []}, self.sources, self.now)
        self.assertEqual(result.count('class="tech-news-card"'), 3)
        self.assertEqual(result.count('0 selected stories · 48h'), 3)
        self.assertIn('No qualifying stories in the current 48-hour window', result)
        self.assertIn('href="/en/fields/new_field/"', result)
        self.assertIn('&lt;img src=x onerror=&quot;bad()&quot;&gt;', result)
        self.assertNotIn('<img src=x', result)
        with tempfile.TemporaryDirectory() as folder:
            field = pages.render_field_page(SHELL, domain, "en", domains, {"items": []}, self.sources, {}, Path(folder), self.now)
        self.assertIn('Check &lt;script&gt;bad()&lt;/script&gt; safely', field)
        self.assertNotIn('<script>bad()</script>', field)
        self.assertIn('Source coverage for this field is still being configured', field)
        self.assertIn('class="field-related-links"', field)

    def test_direct_story_renderer_rejects_unbound_context_but_keeps_true_specific_context(self):
        item = self.item(reading_context={"en": "Check how the reported gain changes with larger sample sizes."})
        with tempfile.TemporaryDirectory() as folder:
            public = Path(folder)
            self.assertNotIn('story-context', pages.story_markup(item, "en", {}, public))
            item["reading_context_meta"] = {"scope": "article_specific", "validation": "source_grounded", "version": 1,
                                            "article_id": item["id"], "source_url": item["url"]}
            self.assertIn('story-context', pages.story_markup(item, "en", {}, public))


if __name__ == "__main__":
    unittest.main()
