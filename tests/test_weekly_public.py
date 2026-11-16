import copy
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from weekly_public import render_weekly_index, render_weekly_issue


def fixture(identifier="2026-11-09"):
    event = {"event_id": "one", "title": "A reported capability", "what_changed": "A result was reported.",
             "why_it_matters": "A workflow may change.", "uncertainty": "Independent replication is not supplied.", "evidence_ids": ["source-one"]}
    zh_event = {"event_id": "one", "title": "一项已报告能力", "what_changed": "来源报告了一项成果。",
                "why_it_matters": "一种工作流可能变化。", "uncertainty": "未提供独立复现。", "evidence_ids": ["source-one"]}
    synthesis = {"intro": "This selection suggests a question worth examining.", "signal": {"title": "A supplied signal", "text": "One reported result deserves attention.", "support": "selection_based", "evidence_ids": ["source-one"]},
                 "structure": {"text": "A possible change in one workflow.", "support": "insufficient", "evidence_ids": ["source-one"]}, "consequence": {"text": "Readers may want to check the limits.", "evidence_ids": ["source-one"]}, "limits": "No industry-wide conclusion follows."}
    zh_synthesis = {"intro": "本期选材提出了一个值得观察的问题。", "signal": {"title": "一个已提供的信号", "text": "一项已报告成果值得留意。", "evidence_ids": ["source-one"]},
                    "structure": {"text": "一种工作流可能发生变化。", "support": "insufficient", "evidence_ids": ["source-one"]}, "consequence": {"text": "读者仍应核实适用条件。", "evidence_ids": ["source-one"]}, "limits": "不能据此推断全行业。"}
    return {"schema_version": 1, "id": identifier, "week_start": identifier, "week_end": "2026-11-15", "timezone": "Asia/Singapore", "period_start": "2026-11-08T16:00:00Z", "period_end": "2026-11-15T16:00:00Z",
            "published_at": "2026-11-16T02:00:00Z", "modified_at": "2026-11-16T02:30:00Z", "generated_at": "2026-11-16T01:00:00Z",
            "en": {"title": "The English weekly title", "dek": "The supplied English description.", "synthesis": synthesis, "lead": {"text": "A supplied selection focus.", "evidence_ids": ["source-one"]}, "main_events": [event], "early_signals": [dict(event, title="A supplied early signal")], "next_watch": [{"text": "Look for replication.", "evidence_ids": ["source-one"]}], "follow_up": {"available": False, "note": "No previous weekly comparison was supplied.", "items": []}},
            "zh": {"title": "中文周报测试标题", "dek": "提供的中文描述。", "synthesis": zh_synthesis, "lead": {"text": "已提供的本周选材主线。", "evidence_ids": ["source-one"]}, "main_events": [zh_event], "early_signals": [dict(zh_event, title="已提供的早期信号")], "next_watch": [{"text": "关注复现结果。", "evidence_ids": ["source-one"]}], "follow_up": {"available": False, "note": "未提供上一期周报对照。", "items": []}},
            "sources": [{"id": "source-one", "url": "https://publisher.example.org/source?a=1&b=2", "archive_url_en": "https://polyemergence.com/en/archive/source/", "archive_url_zh": "https://polyemergence.com/zh/archive/source/", "source": "Example Research", "published_at": "2026-11-12T05:00:00Z", "date_precision": "second", "domain": "ai", "domain_labels": {"en": "Artificial Intelligence", "zh": "人工智能"}, "en": {"title": "English source title"}, "zh": {"title": "中文来源标题"}}],
            "coverage": {"fields": [{"domain": "ai", "domain_labels": {"en": "Artificial Intelligence", "zh": "人工智能"}, "qualified_count": 12, "selected_count": 2}]},
            "process": {"ai_assisted": True, "human_reviewed": False, "independently_verified": False}}


def schema(page):
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    return json.loads(match[1])


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class WeeklyPublicTests(unittest.TestCase):
    def test_public_issue_has_canonical_hreflang_same_issue_language_switch_and_description(self):
        payload = fixture()
        for locale, alternate in (("en", "zh"), ("zh", "en")):
            page = render_weekly_issue(payload, locale)
            self.assertIn(f'<link rel="canonical" href="https://polyemergence.com/{locale}/weekly/2026-11-09/">', page)
            self.assertIn(f'class="weekly-language" href="https://polyemergence.com/{alternate}/weekly/2026-11-09/"', page)
            self.assertIn('hreflang="en"', page)
            self.assertIn('hreflang="zh-Hans"', page)
            self.assertIn('hreflang="x-default"', page)
            self.assertIn(f'<meta name="description" content="{payload[locale]["dek"]}">', page)
            self.assertIn('<link rel="stylesheet" href="/weekly.css?v=1">', page)

    def test_locales_are_independent_and_reuse_existing_branding_and_navigation(self):
        payload = fixture()
        en, zh = render_weekly_issue(payload, "en"), render_weekly_issue(payload, "zh")
        self.assertNotIn("中文周报测试标题", en)
        self.assertNotIn("中文来源标题", en)
        self.assertNotIn("The English weekly title", zh)
        self.assertNotIn("English source title", zh)
        for locale, page in (("en", en), ("zh", zh)):
            self.assertIn(f'src="/assets/logo-{locale}-reverse.svg"', page)
            for path in ("#fields", "#about", "#feedback", "weekly/", "archive/"):
                self.assertIn(f'href="/{locale}/{path}"', page)
            self.assertIn("PolyEmergence Pte Ltd.", page)

    def test_synthesis_comes_before_lead_and_events_without_scores_or_draft_status(self):
        page = render_weekly_issue(fixture(), "en")
        self.assertLess(page.index('id="weekly-insights"'), page.index("<h2>This week's selection</h2>"))
        self.assertLess(page.index('id="weekly-insights"'), page.index("<h2>Main events</h2>"))
        self.assertIn("Signals worth noticing", page)
        self.assertIn("How the landscape may change", page)
        self.assertIn("What it could mean for readers", page)
        self.assertIn("Insufficient evidence in this selection", page)
        self.assertNotIn("DRAFT", page)
        self.assertNotIn("Importance", page)
        self.assertIn("AI-assisted weekly", page)
        self.assertIn("does not claim human editorial review or independent fact-checking", page)

    def test_all_sources_are_native_collapsed_details_and_retain_source_and_archive_links(self):
        page = render_weekly_issue(fixture(), "zh")
        reader = Elements()
        reader.feed(page)
        details = [attrs for tag, attrs in reader.elements if tag == "details"]
        self.assertTrue(details)
        self.assertTrue(all("open" not in attrs for attrs in details))
        self.assertIn("<summary>本段依据</summary>", page)
        self.assertIn("<summary>出处与归档摘要</summary>", page)
        self.assertIn('href="https://publisher.example.org/source?a=1&amp;b=2"', page)
        self.assertIn('href="https://polyemergence.com/zh/archive/source/"', page)
        self.assertIn("原文发布时间: 2026-11-12 13:00 SGT", page)
        self.assertIn("领域: 人工智能", page)

    def test_weekly_publication_times_are_never_replaced_with_source_or_generation_dates(self):
        payload = fixture()
        page = render_weekly_issue(payload, "en")
        data = schema(page)
        self.assertEqual(data["datePublished"], "2026-11-16T02:00:00+00:00")
        self.assertEqual(data["dateModified"], "2026-11-16T02:30:00+00:00")
        self.assertIn("Weekly edition published</strong> 2026-11-16 10:00 SGT", page)
        payload["published_at"] = None
        payload["modified_at"] = None
        data = schema(render_weekly_issue(payload, "en"))
        self.assertNotIn("datePublished", data)
        self.assertNotIn("dateModified", data)

    def test_day_precision_sources_do_not_invent_a_midnight_or_shift_the_date(self):
        payload = fixture()
        payload["sources"][0]["date_precision"] = "day"
        payload["sources"][0]["published_at"] = "2026-11-12T23:00:00Z"
        page = render_weekly_issue(payload, "en")
        self.assertIn("Original publication: 2026-11-12 ·", page)
        self.assertNotIn("Original publication: 2026-11-13", page)
        self.assertNotIn("Original publication: 2026-11-12 00:00", page)

    def test_every_external_text_field_is_escaped_and_json_ld_cannot_close_its_script(self):
        payload = fixture()
        hostile = '</script><script>alert("x")</script><img src=x onerror=x>'
        payload["en"]["title"] = hostile
        payload["en"]["dek"] = hostile
        payload["en"]["synthesis"]["intro"] = hostile
        payload["en"]["synthesis"]["signal"]["title"] = hostile
        payload["en"]["main_events"][0]["what_changed"] = hostile
        payload["sources"][0]["source"] = hostile
        page = render_weekly_issue(payload, "en")
        self.assertNotIn("<script>alert", page)
        self.assertNotIn("<img src=x", page)
        self.assertIn("&lt;/script&gt;", page)
        self.assertIn("\\u003c/script\\u003e", page)
        self.assertEqual(schema(page)["headline"], hostile)
        self.assertEqual(schema(page)["description"], hostile)
        reader = Elements()
        reader.feed(page)
        self.assertFalse(any(any(key.startswith("on") for key in attrs) for _, attrs in reader.elements))
        self.assertTrue(all(attrs.get("type") == "application/ld+json" or attrs.get("src") == "/analytics.js?v=2" for tag, attrs in reader.elements if tag == "script"))

    def test_private_credentialed_or_non_http_links_are_not_rendered_or_cited(self):
        for unsafe in ("javascript:alert(1)", "data:text/html,x", "file:///tmp/private", "https://user:secret@example.org/x", "http://127.0.0.1/x", "https://[::1]/x", "http://169.254.169.254/x", "http://10.0.0.1/x", "http://localhost/x"):
            with self.subTest(unsafe=unsafe):
                payload = fixture()
                payload["sources"][0]["url"] = unsafe
                payload["sources"][0]["archive_url_en"] = unsafe
                page = render_weekly_issue(payload, "en")
                reader = Elements()
                reader.feed(page)
                self.assertFalse(any(attrs.get("href") == unsafe for _, attrs in reader.elements))
                self.assertNotIn("citation", schema(page))
                self.assertIn("Original link unavailable or unsafe", page)
                self.assertIn("Archive link unavailable or unsafe", page)

    def test_supplementary_source_without_archive_has_a_neutral_note_but_unsafe_links_stay_flagged(self):
        for locale, note, warning in (("en", "Supplementary source; no site archive", "Archive link unavailable or unsafe"),
                                       ("zh", "补充来源，尚无本站归档", "归档链接不可用或不安全")):
            for absent in (None, "", "   "):
                with self.subTest(locale=locale, absent=absent):
                    payload = fixture()
                    payload["sources"][0]["archive_url_" + locale] = absent
                    page = render_weekly_issue(payload, locale)
                    self.assertIn(note, page)
                    self.assertNotIn(warning, page)
                    self.assertIn('href="https://publisher.example.org/source?a=1&amp;b=2"', page)
            payload = fixture()
            payload["sources"][0]["archive_url_" + locale] = "http://127.0.0.1/private"
            page = render_weekly_issue(payload, locale)
            self.assertIn(warning, page)
            self.assertNotIn(note, page)

    def test_issue_is_readable_without_app_javascript_or_remote_images_fonts_and_css(self):
        page = render_weekly_issue(fixture(), "en")
        reader = Elements()
        reader.feed(page)
        self.assertEqual(sum(tag == "h1" for tag, _ in reader.elements), 1)
        self.assertEqual([attrs.get("src") for tag, attrs in reader.elements if tag == "img"], ["/assets/logo-en-reverse.svg"])
        self.assertEqual([attrs.get("href") for tag, attrs in reader.elements if tag == "link" and attrs.get("rel") == "stylesheet"], ["/weekly.css?v=1"])
        self.assertFalse(any(tag in {"iframe", "form", "video", "audio", "style"} for tag, _ in reader.elements))
        scripts = [attrs for tag, attrs in reader.elements if tag == "script"]
        local_analytics = [attrs for attrs in scripts if attrs.get("src") == "/analytics.js?v=2"]
        self.assertEqual(len(local_analytics), 1)
        self.assertIn("defer", local_analytics[0])
        self.assertFalse(any(attrs.get("src", "").startswith("http") for attrs in scripts))
        self.assertNotIn("app.js", page)
        self.assertIn("weekly-skip", page)

    def test_no_missing_field_is_filled_with_another_language_or_a_verification_claim(self):
        payload = fixture()
        payload["zh"] = {}
        payload["process"] = {"human_reviewed": True, "independently_verified": True}
        page = render_weekly_issue(payload, "zh")
        self.assertNotIn("The English weekly title", page)
        self.assertNotIn("English source title", page)
        self.assertIn("未提供", page)
        self.assertNotIn("审核通过", page)
        self.assertNotIn("已独立核验", page)

    def test_missing_evidence_and_unavailable_follow_up_remain_honest(self):
        payload = fixture()
        payload["en"]["main_events"][0]["evidence_ids"] = ["missing <id>"]
        payload["en"]["follow_up"]["items"] = [{"title": "Must not become a tracked event"}]
        page = render_weekly_issue(payload, "en")
        self.assertIn("This reference was not found", page)
        self.assertIn("missing &lt;id&gt;", page)
        self.assertNotIn("Must not become a tracked event", page)

    def test_publication_follow_up_note_is_escaped_without_renderer_copyediting(self):
        payload = fixture()
        payload["en"]["follow_up"]["note"] = "This published first edition has no previous edition to compare."
        self.assertIn(payload["en"]["follow_up"]["note"], render_weekly_issue(payload, "en"))
        payload["en"]["follow_up"]["note"] = "A review draft <note> must be copyedited before publication."
        self.assertIn("A review draft &lt;note&gt; must be copyedited before publication.", render_weekly_issue(payload, "en"))

    def test_local_analytics_is_present_on_both_public_issue_and_index_without_inline_execution(self):
        for page in (render_weekly_issue(fixture(), "zh"), render_weekly_index([fixture()], "en")):
            reader = Elements()
            reader.feed(page)
            scripts = [attrs for tag, attrs in reader.elements if tag == "script"]
            self.assertEqual(sum(attrs.get("src") == "/analytics.js?v=2" and "defer" in attrs for attrs in scripts), 1)
            self.assertEqual(sum(attrs.get("type") == "application/ld+json" for attrs in scripts), 1)
            self.assertEqual(len(scripts), 2)

    def test_empty_index_has_no_fabricated_issue_and_collection_schema_is_zero(self):
        page = render_weekly_index([], "en")
        self.assertIn("No weekly editions have been published here yet.", page)
        self.assertNotIn("weekly-edition-card", page)
        self.assertEqual(schema(page)["mainEntity"]["numberOfItems"], 0)
        self.assertEqual(schema(page)["@type"], "CollectionPage")
        self.assertIn('rel="canonical" href="https://polyemergence.com/en/weekly/"', page)

    def test_index_sorts_by_week_deduplicates_and_links_latest_and_history_clearly(self):
        old = fixture("2026-11-02")
        old["en"]["title"] = "Earlier weekly title"
        latest = fixture()
        page = render_weekly_index([old, latest, copy.deepcopy(latest), {"id": "../../unsafe"}], "en")
        self.assertEqual(schema(page)["mainEntity"]["numberOfItems"], 2)
        self.assertLess(page.index("The English weekly title"), page.index("Earlier weekly title"))
        self.assertIn("Latest edition", page)
        self.assertIn("Earlier editions", page)
        self.assertIn('href="/en/weekly/2026-11-09/"', page)
        self.assertIn('href="/en/weekly/2026-11-02/"', page)
        self.assertNotIn("../../unsafe", page)
        self.assertIn('class="weekly-language" href="https://polyemergence.com/zh/weekly/"', page)

    def test_invalid_issue_ids_and_locales_fail_explicitly(self):
        for value in (None, "2026-02-30", "2026-1-1", "../../x", '2026-11-09" onload=x'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                render_weekly_issue(fixture(value), "en")
        with self.assertRaises(ValueError):
            render_weekly_issue(fixture(), "fr")
        with self.assertRaises(ValueError):
            render_weekly_index([], "fr")

    def test_rendering_is_pure_offline_deterministic_and_does_not_modify_publication_metadata(self):
        payload = fixture()
        before = copy.deepcopy(payload)
        with patch("builtins.open", side_effect=AssertionError("no file access")), patch("socket.getaddrinfo", side_effect=AssertionError("no network")):
            first = render_weekly_issue(payload, "en")
            second = render_weekly_issue(payload, "en")
            index = render_weekly_index([payload], "zh")
        self.assertEqual(first, second)
        self.assertEqual(payload, before)
        self.assertIn("中文周报测试标题", index)

    def test_styles_are_scoped_responsive_and_have_no_remote_asset_dependencies(self):
        css = (ROOT / "web/public/weekly.css").read_text()
        self.assertIn("body.weekly-public", css)
        self.assertIn("@media(max-width:760px)", css)
        self.assertIn("@media print", css)
        self.assertIn("focus-visible", css)
        self.assertNotIn("@import", css)
        self.assertNotIn("url(", css)


if __name__ == "__main__":
    unittest.main()
