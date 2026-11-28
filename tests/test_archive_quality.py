"""Offline regression coverage for language-safe archives and reader context."""

import copy
import html
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
from content_language import wrong_language


GOOD_EN = "The research team describes a model release and the conditions used to evaluate its workflow."
GOOD_ZH = "研究团队介绍了模型发布及其工作流的评估条件，读者可以查阅原始资料了解具体适用范围。"
WRONG_EN = "这是被错误写入英文栏位的中文长摘要，内容主要介绍模型能力、研究过程、技术背景以及实际使用时应当核查的边界。" * 3
WRONG_ZH = (
    "This English paragraph was accidentally stored as the Chinese long summary. "
    "It contains enough ordinary prose to establish that the full article is in "
    "the wrong language, rather than a short product name, an API identifier, "
    "a code example, or a collection of mixed technical terms."
)


def fixture(identifier="quality-test"):
    published = archive.parse_datetime("2026-11-12T18:00:50Z")
    return {
        "id": identifier, "url": "https://example.org/research/" + identifier,
        "source": "Research Desk", "category": "models", "domain": "ai",
        "published": published, "source_published": published,
        "site_published": archive.parse_datetime("2026-11-12T23:24:35.533918Z"),
        "importance": 80,
        "scores": {key: 80 for key in ("signal", "structure", "consequence", "confidence", "momentum")},
        "tags": ["models"], "image_url": "#",
        "en": {"title": "A model release", "summary": GOOD_EN, "full": WRONG_EN},
        "zh": {"title": "一项模型发布", "summary": GOOD_ZH, "full": WRONG_ZH},
    }


def public_fixture(identifier="quality-test"):
    record = fixture(identifier)
    item = {
        **record,
        "published_at": "2026-11-12T18:00:50Z",
        "source_published_at": "2026-11-12T18:00:50Z",
        "site_published_at": "2026-11-12T23:24:35.533918Z",
    }
    for key in ("published", "source_published", "site_published"):
        item.pop(key)
    for locale in ("en", "zh"):
        fields = dict(item[locale])
        fields["full_summary"] = fields.pop("full")
        item[locale] = fields
    return item


def hydrogen_fixture():
    record = fixture("ef947a5d-9a1d-4aaf-a3a3-fad2dc5bef6a")
    record.update(url="https://deepmind.google/blog/introducing-gemini-4-hydrogen/", source="Google DeepMind")
    record["en"] = {
        "title": "Google Introduces Gemini 4 Hydrogen Model for Fast Execution and Agentic Workflows",
        "summary": "According to Google DeepMind: Google is introducing Gemini 4 Hydrogen, a new model designed for rapid execution and everyday agentic workflows.",
        "full": "Google is rolling out Gemini 4 Hydrogen to bring cutting-edge intelligence and speed to everyday coding and agentic workflows. While frontier models like Carbon and Argon handle deep, long-horizon reasoning on complex problems, Hydrogen is built as an efficient execution engine for rapid tasks and multi-model collaboration.\nEcosystem Integration\nHydrogen is rolling out globally across the Gemini API, Google AI Studio, the Gemini app, Google Search, and enterprise tools.",
    }
    record["zh"] = {
        "title": "谷歌发布 Gemini 4 Hydrogen 模型，主打快速执行与智能体工作流",
        "summary": "据Google DeepMind发布的信息：谷歌推出了全新模型 Gemini 4 Hydrogen，旨在提供快速执行能力和日常的智能体工作流。",
        "full": "谷歌正式发布了 Gemini 4 Hydrogen 模型，旨在将前沿的AI智能以高速度和高效率带入日常编程与智能体工作流中。虽然谷歌的旗舰模型 Carbon 和 Argon 专注于处理复杂的长周期推理任务，但 Hydrogen 的核心定位则是作为一个高效的执行引擎，胜任各类高频和多步骤的日常任务。\n生态整合与应用\nHydrogen 目前正在向全球的开发者、企业和普通消费者全面推送，覆盖 Gemini API、AI Studio、Gemini App 以及谷歌搜索。",
    }
    return record


def article_page(output, record, locale):
    day = record["published"].astimezone(archive.LOCAL_TZ).date()
    return output / archive.article_path(locale, day, record).lstrip("/") / "index.html"


def schema(page):
    return json.loads(re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)[1])


class ArchiveLanguageQualityTests(unittest.TestCase):
    def assert_safe_locales(self, record):
        for locale, summary in (("en", GOOD_EN), ("zh", GOOD_ZH)):
            self.assertEqual(record[locale]["summary"], summary)
            self.assertEqual(record[locale]["full"], summary)
            self.assertFalse(wrong_language(record[locale]["full"], locale))

    def test_feed_and_json_load_keep_articles_and_use_same_language_short_summary(self):
        item = public_fixture()
        before = copy.deepcopy(item)
        self.assert_safe_locales(archive.record_from_feed(item))
        self.assertEqual(item, before)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "feed.json"
            path.write_text(json.dumps({"items": [item, public_fixture("second")]}))
            records = archive.load_json(path)
        self.assertEqual([record["id"] for record in records], ["quality-test", "second"])
        for record in records:
            self.assert_safe_locales(record)

    def test_database_enrichment_guards_input_and_rejects_reintroduced_wrong_prose(self):
        record = fixture()
        before = copy.deepcopy(record)

        def changed_enrichment(item):
            self.assert_safe_locales(item)
            for locale, summary in (("en", GOOD_EN), ("zh", GOOD_ZH)):
                self.assertEqual(item[locale]["full_summary"], summary)
            item = copy.deepcopy(item)
            item["en"]["full_summary"] = WRONG_EN
            item["zh"]["full_summary"] = WRONG_ZH
            return item

        with patch.object(archive, "enrich_item", side_effect=changed_enrichment):
            enriched = archive.enrich_record(record)
        self.assert_safe_locales(enriched)
        self.assertEqual(record, before)
        for key in ("id", "url", "published", "source_published", "site_published"):
            self.assertEqual(enriched[key], before[key])

    def test_empty_enrichment_results_do_not_restore_rejected_original_fields(self):
        def cleared_enrichment(item):
            item = copy.deepcopy(item)
            for locale in ("en", "zh"):
                item[locale]["summary"] = ""
                item[locale]["full_summary"] = ""
            return item

        with patch.object(archive, "enrich_item", side_effect=cleared_enrichment):
            result = archive.enrich_record(fixture())
        for locale in ("en", "zh"):
            self.assertEqual(result[locale]["summary"], "")
            self.assertEqual(result[locale]["full"], "")

    def test_both_wrong_fields_stay_empty_without_other_locale_fallback(self):
        record = fixture()
        record["en"]["summary"] = WRONG_EN
        record["zh"]["summary"] = WRONG_ZH
        result = archive.enrich_record(record)
        for locale in ("en", "zh"):
            self.assertEqual(result[locale]["summary"], "")
            self.assertEqual(result[locale]["full"], "")
        self.assertEqual(result["id"], record["id"])

    def test_direct_story_detail_and_rss_have_render_boundary_protection(self):
        record = fixture()
        before = copy.deepcopy(record)
        day = record["published"].astimezone(archive.LOCAL_TZ).date()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for locale, bad, good in (("en", WRONG_EN, GOOD_EN), ("zh", WRONG_ZH, GOOD_ZH)):
                for detail in (False, True):
                    rendered = archive.story_html(record, locale, detail=detail)
                    self.assertNotIn(bad, rendered)
                    self.assertIn(good, rendered)
                archive.render_article(output, locale, record)
                page = article_page(output, record, locale).read_text()
                self.assertNotIn(bad, page)
                self.assertEqual(schema(page)["description"], good)
                archive.render_rss(output, locale, {day: [record]})
                rss = (output / f"feed-{locale}.xml").read_text()
                self.assertNotIn(bad, rss)
                self.assertIn(good, rss)
        self.assertEqual(record, before)

    def test_public_corpus_rechecks_enrichment_and_keeps_identity_dates_and_count(self):
        original_enrich = archive.enrich_item

        def changed_enrichment(item):
            item = original_enrich(item)
            item["en"]["full_summary"] = WRONG_EN
            item["zh"]["full_summary"] = WRONG_ZH
            return item

        record = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(archive, "enrich_item", side_effect=changed_enrichment):
                archive.render_public_data(output, [record])
            corpus = json.loads((output / "data/articles.json").read_text())
        self.assertEqual(corpus["count"], 1)
        item = corpus["items"][0]
        for locale, good in (("en", GOOD_EN), ("zh", GOOD_ZH)):
            self.assertEqual(item[locale], {"title": record[locale]["title"], "summary": good, "full_summary": good})
            self.assertEqual(item["canonical_urls"][locale], archive.SITE + archive.article_path(locale, record["published"].astimezone(archive.LOCAL_TZ).date(), record))
        self.assertEqual(item["id"], record["id"])
        self.assertEqual(item["published_at"], "2026-11-12T18:00:50Z")
        self.assertEqual(item["site_published_at"], "2026-11-12T23:24:35.533918Z")


class ArchiveSearchContextTests(unittest.TestCase):
    def test_gemini_detail_metadata_h1_schema_align_without_changing_public_headline_or_dates(self):
        record = hydrogen_fixture()
        before = copy.deepcopy(record)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for locale in ("en", "zh"):
                context = archive.article_search_context(record, locale)
                archive.render_article(output, locale, record)
                page = article_page(output, record, locale).read_text()
                data = schema(page)
                self.assertIn(f'<title>{html.escape(context["seo_title"])} | ', page)
                self.assertIn(f'<h1>{html.escape(context["seo_title"])}</h1>', page)
                self.assertEqual(data["headline"], context["seo_title"])
                self.assertEqual(data["description"], context["description"])
                self.assertIn(f'<p class="archive-dek">{html.escape(context["description"])}</p>', page)
                self.assertIn(f'<meta name="description" content="{html.escape(context["description"], quote=True)}">', page)
                self.assertIn('class="archive-prose archive-search-context"', page)
                reader_section = re.search(r'<section class="archive-prose archive-search-context".*?</section>', page, re.S)[0]
                self.assertEqual(reader_section.count('<strong>'), 3)
                self.assertNotIn('archive-search-context', archive.story_html(record, locale))
                expected_date = record["site_published"].astimezone(archive.LOCAL_TZ).isoformat()
                self.assertEqual(data["datePublished"], expected_date)
                self.assertEqual(data["dateModified"], expected_date)
                self.assertEqual(data["mainEntityOfPage"], archive.SITE + "/" + str(article_page(output, record, locale).relative_to(output)).removesuffix("index.html"))
            archive.render_public_data(output, [record])
            public = json.loads((output / "data/articles.json").read_text())["items"][0]
        for locale in ("en", "zh"):
            self.assertEqual(public[locale]["title"], before[locale]["title"])
        self.assertEqual(record, before)

    def test_reader_context_html_and_metadata_escape_untrusted_plain_text(self):
        attack = '</script><img src=x onerror="alert(1)"> & unsafe'
        context = {
            "seo_title": attack, "description": attack, "heading": attack,
            "points": [{"question": attack, "answer": attack}] * 3,
            "source_url": "javascript:alert(1)",
        }
        record = hydrogen_fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(archive, "article_search_context", return_value=context):
                archive.render_article(output, "en", record)
            page = article_page(output, record, "en").read_text()
        visible_html = re.sub(r'<script\b[^>]*>.*?</script>', "", page, flags=re.S)
        self.assertNotIn('<img src=x onerror=', visible_html)
        self.assertNotIn('href="javascript:', page)
        self.assertIn(html.escape(attack, quote=True), page)
        self.assertEqual(schema(page)["headline"], attack)
        self.assertNotIn('</script><img', page)

    def test_other_articles_and_incomplete_target_evidence_keep_original_metadata(self):
        for record in (fixture(), hydrogen_fixture()):
            if "Gemini" in record["en"]["title"]:
                record["en"]["full"] = "The article is being revised."
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                archive.render_article(output, "en", record)
                page = article_page(output, record, "en").read_text()
            self.assertEqual(schema(page)["headline"], record["en"]["title"])
            self.assertNotIn('archive-search-context', page)


if __name__ == "__main__":
    unittest.main()
