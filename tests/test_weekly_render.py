import copy
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from weekly_render import render_review, to_markdown


def fixture():
    event = {"event_id": "event-one", "title": "A measured result", "what_changed": "A source reported a 4K result.",
             "why_it_matters": "It may change one deployment decision.", "uncertainty": "Independent replication is not supplied.",
             "evidence_ids": ["evidence-one"]}
    chinese_event = {"event_id": "event-one", "title": "一项有条件的成果", "what_changed": "来源报告了4K结果。",
                     "why_it_matters": "这可能影响一项部署选择。", "uncertainty": "尚未提供独立复现结果。", "evidence_ids": ["evidence-one"]}
    report = {
        "issue": {"week_start": "2026-11-09", "week_end": "2026-11-15", "start": "2026-11-08T16:00:00Z", "end": "2026-11-15T16:00:00Z", "timezone": "Asia/Singapore", "generated_at": "2026-11-16T02:00:00Z", "status": "DRAFT"},
        "en": {"title": "English weekly fixture", "dek": "An evidence-bound selection.", "lead": {"text": "This draft selects one supplied event.", "evidence_ids": ["evidence-one"]},
               "main_events": [event], "early_signals": [], "follow_up": {"available": False, "note": "No historical comparison was supplied.", "items": []},
               "next_watch": [{"text": "Look for a published replication.", "evidence_ids": ["evidence-one"]}]},
        "zh": {"title": "中文周报测试标题", "dek": "依据证据选材。", "lead": {"text": "本草稿围绕一项已提供事件选材。", "evidence_ids": ["evidence-one"]},
               "main_events": [chinese_event], "early_signals": [], "follow_up": {"available": False, "note": "未提供历史对照。", "items": []},
               "next_watch": [{"text": "关注是否公布复现结果。", "evidence_ids": ["evidence-one"]}]},
    }
    catalog = [{"id": "evidence-one", "url": "https://publisher.example.org/article?x=1&y=2", "archive_url_en": "https://polyemergence.com/en/archive/one/", "archive_url_zh": "https://polyemergence.com/zh/archive/one/",
                "source": "Example Research", "published_at": "2026-11-12T05:00:00Z", "domain": "ai", "domain_labels": {"en": "Artificial Intelligence", "zh": "人工智能"},
                "en": {"title": "English original title", "summary": "Existing summary."}, "zh": {"title": "中文原文标题", "summary": "已有摘要。"}, "importance": 80, "scores": {"confidence": 75}}]
    return report, catalog


class Elements(HTMLParser):
    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))


class WeeklyRenderTests(unittest.TestCase):
    def test_documents_are_separate_locales_with_reciprocal_fixed_file_links(self):
        report, catalog = fixture()
        pages = render_review(report, catalog)
        self.assertEqual(set(pages), {"en", "zh"})
        self.assertIn('<html lang="en">', pages["en"])
        self.assertIn('<html lang="zh-Hans">', pages["zh"])
        self.assertIn('href="zh.html"', pages["en"])
        self.assertIn('href="en.html"', pages["zh"])
        self.assertNotIn("中文周报测试标题", pages["en"])
        self.assertNotIn("English weekly fixture", pages["zh"])
        self.assertNotIn("English original title", pages["zh"])
        self.assertNotIn("中文原文标题", pages["en"])

    def test_self_contained_text_first_html_has_no_executable_or_remote_assets(self):
        pages = render_review(*fixture())
        for page in pages.values():
            reader = Elements()
            reader.feed(page)
            self.assertEqual(sum(tag == "h1" for tag, _ in reader.elements), 1)
            self.assertFalse(any(tag in {"script", "img", "iframe", "form", "link", "video", "audio"} for tag, _ in reader.elements))
            self.assertFalse(any("src" in attrs or any(key.startswith("on") for key in attrs) for _, attrs in reader.elements))
            self.assertIn("<style>", page)
            self.assertIn("--orange:#ff5a24", page)
            self.assertIn('content="noindex,nofollow"', page)
            self.assertNotIn("@import", page)
            self.assertNotIn("analytics", page)

    def test_each_passage_exposes_original_archive_publication_and_domain(self):
        report, catalog = fixture()
        page = render_review(report, catalog)["en"]
        self.assertEqual(page.count('class="source-index"'), 3)
        self.assertEqual(page.count('href="https://publisher.example.org/article?x=1&amp;y=2"'), 3)
        self.assertEqual(page.count('href="https://polyemergence.com/en/archive/one/"'), 3)
        self.assertIn("Source published: 2026-11-12T05:00:00+00:00", page)
        self.assertIn("Field: Artificial Intelligence", page)
        self.assertIn("Reported facts · based on existing summaries", page)
        self.assertIn("Why it matters · editorial judgment", page)
        self.assertIn("Unverified points and uncertainty", page)

    def test_all_external_text_and_attributes_are_escaped(self):
        report, catalog = fixture()
        hostile = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        report["en"]["title"] = hostile
        report["en"]["dek"] = hostile
        report["en"]["lead"]["text"] = hostile
        for key in ("title", "what_changed", "why_it_matters", "uncertainty", "event_id"):
            report["en"]["main_events"][0][key] = hostile
        catalog[0]["source"] = hostile
        catalog[0]["en"]["title"] = hostile
        catalog[0]["domain_labels"]["en"] = hostile
        catalog[0]["url"] = 'https://publisher.example.org/article?q="onmouseover=x"'
        page = render_review(report, catalog)["en"]
        reader = Elements()
        reader.feed(page)
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img ", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertFalse(any(any(key.startswith("on") for key in attrs) for _, attrs in reader.elements))
        self.assertTrue(any(tag == "a" and attrs.get("href") == catalog[0]["url"] for tag, attrs in reader.elements))

    def test_unsafe_original_and_archive_links_are_never_clickable(self):
        report, catalog = fixture()
        for unsafe in ("javascript:alert(1)", "data:text/html,test", "file:///tmp/private", "https://user:password@publisher.example.org/article", "http://127.0.0.1/private", "https://[::1]/private", "http://10.0.0.1/private", "http://169.254.169.254/latest", "http://localhost/private"):
            with self.subTest(unsafe=unsafe):
                catalog[0]["url"] = unsafe
                catalog[0]["archive_url_en"] = unsafe
                page = render_review(report, catalog)["en"]
                reader = Elements()
                reader.feed(page)
                links = [attrs.get("href") for tag, attrs in reader.elements if tag == "a"]
                self.assertEqual(links, ["zh.html"])
                self.assertIn("Original-source link not provided or unsafe", page)
                self.assertIn("Archive link not provided or unsafe", page)
                markdown = to_markdown(report, "en", catalog)
                self.assertNotIn(unsafe, markdown)

    def test_missing_evidence_is_honest_and_unreferenced_catalog_rows_are_not_invented(self):
        report, catalog = fixture()
        report["en"]["main_events"][0]["evidence_ids"] = ["missing <id>", "missing <id>"]
        report["en"]["lead"]["evidence_ids"] = []
        catalog.append({"id": "unused", "en": {"title": "Unreferenced catalog title"}})
        page = render_review(report, catalog)["en"]
        self.assertIn("No traceable evidence references were provided", page)
        self.assertIn("missing &lt;id&gt;", page)
        self.assertEqual(page.count("missing &lt;id&gt;"), 1)
        self.assertNotIn("Unreferenced catalog title", page)

    def test_missing_fields_or_locales_do_not_copy_the_other_language_or_infer_certainty(self):
        report, catalog = fixture()
        report["en"]["main_events"][0].pop("uncertainty")
        page = render_review(report, catalog)["en"]
        self.assertIn("No uncertainty statement was provided. This does not establish certainty.", page)
        report.pop("zh")
        chinese = render_review(report, catalog)["zh"]
        self.assertNotIn("English weekly fixture", chinese)
        self.assertIn("本节未提供可审阅条目", chinese)
        self.assertIn("未提供", chinese)

    def test_input_status_cannot_turn_the_artifact_into_an_approved_report(self):
        report, catalog = fixture()
        report["issue"]["status"] = "APPROVED BY EDITOR"
        page = render_review(report, catalog)["en"]
        self.assertNotIn("APPROVED BY EDITOR", page)
        self.assertIn("DRAFT · Not reviewed by a human", page)
        self.assertIn("Review draft based on existing news summaries", page)
        self.assertIn("not independently fact-checked", page)
        self.assertIn("Published by PolyEmergence, a sole proprietorship in Singapore.", page)

    def test_follow_up_unavailable_does_not_render_unsupplied_or_inconsistent_items(self):
        report, catalog = fixture()
        report["en"]["follow_up"]["items"] = [{"title": "Must not invent a tracked event"}]
        page = render_review(report, catalog)["en"]
        self.assertIn("No historical follow-up available for this draft", page)
        self.assertNotIn("Must not invent a tracked event", page)
        report["en"]["follow_up"] = {"available": True, "items": []}
        self.assertIn("Follow-up was marked available, but no entries were provided.", render_review(report, catalog)["en"])
        report["en"]["follow_up"] = {"available": "true", "items": []}
        self.assertIn("Follow-up availability was not specified", render_review(report, catalog)["en"])

    def test_coverage_displays_only_supplied_counts_not_heat_or_guessed_totals(self):
        report, catalog = fixture()
        report["coverage"] = {"fields": [{"domain": "ai", "domain_labels": {"en": "Artificial Intelligence", "zh": "人工智能"}, "qualified_count": 12, "selected_count": 2},
                                          {"domain": "quantum", "qualified_count": 0, "selected_count": 0},
                                          {"domain": "future", "qualified_count": -1, "selected_count": True}]}
        page = render_review(report, catalog)["en"]
        self.assertIn("not industry activity or momentum", page)
        self.assertIn("<td>12</td><td>2</td>", page)
        self.assertIn("<td>0</td><td>0</td>", page)
        self.assertIn("<td>future</td><td>Not provided</td><td>Not provided</td>", page)
        self.assertIn("| quantum | 0 | 0 |", to_markdown(report, "en", catalog))

    def test_markdown_coverage_table_is_one_contiguous_block(self):
        report, catalog = fixture()
        report["coverage"] = [{"domain": "ai", "selected_count": 2, "qualified_count": 12},
                              {"domain": "quantum", "selected_count": 0, "qualified_count": 0},
                              {"domain": "future", "domain_labels": {"en": "A field\n| not another row"}}]
        markdown = to_markdown(report, "en", catalog)
        expected = ("| Field | Qualified items | Selected items |\n"
                    "| --- | ---: | ---: |\n"
                    "| ai | 12 | 2 |\n"
                    "| quantum | 0 | 0 |\n"
                    r"| A field \| not another row | Not provided | Not provided |")
        self.assertIn(expected, markdown)
        self.assertNotIn("|\n\n|", markdown)

    def test_markdown_watch_evidence_is_nested_under_its_watch_item(self):
        report, catalog = fixture()
        report["en"]["next_watch"].append({"text": "A second follow-up question.", "evidence_ids": []})
        markdown = to_markdown(report, "en", catalog)
        watch = markdown.split("## What to watch next\n\n", 1)[1].split("\n\n---", 1)[0]
        self.assertIn("- Look for a published replication\\.\n\n  **Evidence and sources**\n  - English original title", watch)
        self.assertIn("- A second follow\\-up question\\.\n\n  No traceable evidence references", watch)
        self.assertEqual(sum(line.startswith("- ") for line in watch.splitlines()), 2)

    def test_synthesis_precedes_events_in_both_formats_and_keeps_each_dimension_traceable(self):
        report, catalog = fixture()
        report["en"]["synthesis"] = {
            "intro": "A supplied plain-language overview.",
            "signal": {"title": "A reported capability", "text": "One supplied result deserves attention.", "evidence_ids": ["evidence-one"]},
            "structure": {"title": "A possible change in tools", "text": "This could change one workflow, not the whole industry.", "evidence_ids": ["evidence-one"]},
            "consequence": {"title": "A practical question", "text": "A reader may want to check the cost before using it.", "evidence_ids": ["evidence-one"]},
            "limits": "A broader effect is not established by this selection.", "evidence_ids": ["evidence-one"],
        }
        before = copy.deepcopy((report, catalog))
        page = render_review(report, catalog)["en"]
        start = page.index('<section class="synthesis"')
        end = page.index('<h2>Editorial selection focus</h2>')
        synthesis = page[start:end]
        self.assertLess(page.index('class="issue-meta"'), start)
        self.assertIn("What this selection suggests", synthesis)
        for key, label in (("signal", "Signals worth noticing"), ("structure", "How the landscape may change"), ("consequence", "What it could mean for readers")):
            self.assertIn(f'data-synthesis-dimension="{key}"', synthesis)
            self.assertIn(label, synthesis)
            self.assertIn(report["en"]["synthesis"][key]["text"], synthesis)
        self.assertEqual(synthesis.count('class="source-index"'), 4)
        self.assertEqual(synthesis.count('<details class="synthesis-sources">'), 4)
        self.assertEqual(synthesis.count('<summary>Sources for this interpretation</summary>'), 4)
        self.assertNotIn('<details class="synthesis-sources" open', synthesis)
        self.assertEqual(synthesis.count('href="https://polyemergence.com/en/archive/one/"'), 4)
        self.assertIn("Source published:", synthesis)
        self.assertIn("Field: Artificial Intelligence", synthesis)
        self.assertIn("not an industry-wide measurement or a certain forecast", synthesis)
        self.assertNotIn("Importance", synthesis)
        self.assertNotIn("<article", synthesis)
        markdown = to_markdown(report, "en", catalog)
        self.assertLess(markdown.index("## What this selection suggests"), markdown.index("## Editorial selection focus"))
        self.assertIn("### What we cannot conclude yet", markdown)
        self.assertIn("A broader effect is not established by this selection", markdown)
        self.assertEqual((report, catalog), before)

    def test_synthesis_sources_are_native_collapsed_details_without_changing_event_sources(self):
        report, catalog = fixture()
        report["zh"]["synthesis"] = {"intro": "一段已提供的讲解。", "signal": {"text": "一个信号。", "evidence_ids": ["evidence-one"]}, "limits": "不能推断全行业。"}
        page = render_review(report, catalog)["zh"]
        synthesis = page.split('<section class="synthesis"', 1)[1].split('<h2>本周选材主线</h2>', 1)[0]
        reader = Elements()
        reader.feed(synthesis)
        details = [attrs for tag, attrs in reader.elements if tag == "details"]
        self.assertEqual(len(details), 3)
        self.assertTrue(all(attrs.get("class") == "synthesis-sources" and "open" not in attrs for attrs in details))
        self.assertEqual(synthesis.count("<summary>本段依据</summary>"), 3)
        remainder = page.split('<h2>本周选材主线</h2>', 1)[1]
        self.assertNotIn("synthesis-sources", remainder)
        self.assertIn('class="source-index"', remainder)
        self.assertNotIn("<details", remainder)

    def test_insufficient_synthesis_support_is_explicit_in_html_and_markdown_without_forcing_missing_metadata(self):
        report, catalog = fixture()
        for locale, label in (("en", "Insufficient evidence in this selection"), ("zh", "现有选材不足以支持这一判断")):
            report[locale]["synthesis"] = {"intro": "Supplied overview.",
                                            "signal": {"text": "A conditional interpretation.", "support": "insufficient", "evidence_ids": []},
                                            "structure": {"text": "A supplied structural interpretation.", "support": "selection_based", "evidence_ids": ["evidence-one"]},
                                            "consequence": {"text": "Another supplied interpretation.", "evidence_ids": ["evidence-one"]}}
            page = render_review(report, catalog)[locale]
            self.assertEqual(page.count(f'<p class="synthesis-support" role="note">{label}</p>'), 1)
            self.assertEqual(to_markdown(report, locale, catalog).count("**" + label + "**"), 1)
            self.assertIn("DRAFT", page)

    def test_synthesis_is_language_specific_and_old_drafts_do_not_gain_invented_interpretation(self):
        report, catalog = fixture()
        for missing in (None, {}, "not an object", {"signal": {}}, {"evidence_ids": ["evidence-one"]}):
            report["en"]["synthesis"] = missing
            self.assertNotIn('<section class="synthesis"', render_review(report, catalog)["en"])
            self.assertNotIn("## What this selection suggests", to_markdown(report, "en", catalog))
        report["en"]["synthesis"] = {"intro": "English interpretation only."}
        report["zh"]["synthesis"] = {
            "intro": "这是本期选材中的中文讲解。",
            "signal": {"title": "一个待核实的信号", "text": "仅据提供的报道观察。", "evidence_ids": ["evidence-one"]},
            "structure": {"text": "一种可能的分工变化。", "evidence_ids": ["evidence-one"]},
            "consequence": {"text": "读者应先核实适用条件。", "evidence_ids": ["evidence-one"]},
            "limits": "不能凭这些条目推断整个行业。",
        }
        pages = render_review(report, catalog)
        self.assertIn("这周看出了什么", pages["zh"])
        self.assertIn("值得留意的信号", pages["zh"])
        self.assertIn("可能改变的格局", pages["zh"])
        self.assertIn("对读者意味着什么", pages["zh"])
        self.assertIn("还不能确定什么", pages["zh"])
        self.assertNotIn("English interpretation only", pages["zh"])
        self.assertNotIn("这是本期选材中的中文讲解", pages["en"])
        self.assertNotIn("What this selection suggests", to_markdown(report, "zh", catalog))
        self.assertIn("DRAFT · 未经人工审阅", pages["zh"])

    def test_synthesis_escapes_text_and_missing_evidence_without_inventing_links(self):
        report, catalog = fixture()
        hostile = '<script>alert("synthesis")</script><img src=x onerror=x>'
        report["en"]["synthesis"] = {"intro": hostile, "limits": hostile,
                                        "signal": {"title": hostile, "text": hostile, "evidence_ids": ["unknown <id>"]}}
        page = render_review(report, catalog)["en"]
        self.assertNotIn("<script>", page)
        self.assertNotIn("<img ", page)
        self.assertIn("&lt;script&gt;", page)
        self.assertIn("unknown &lt;id&gt;", page)
        self.assertIn("Evidence reference is missing from the supplied catalog", page)
        self.assertIn("No uncertainty statement was provided", render_review({"en": {"synthesis": {"intro": "A supplied partial overview."}}}, [])["en"])
        markdown = to_markdown(report, "en", catalog)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("<img ", markdown)
        self.assertIn("unknown &lt;id&gt;", markdown)

    def test_malformed_fields_dates_and_collections_have_safe_honest_fallbacks(self):
        report = {"issue": {"start": "not-a-date", "end": "2026-02-30", "generated_at": "bad-date"},
                  "en": {"title": ["not text"], "lead": "not an object", "main_events": {"bad": "shape"}, "early_signals": [None, "bad"], "next_watch": None}}
        page = render_review(report, [None, "bad"])["en"]
        self.assertIn("Weekly technology review (draft)", page)
        self.assertIn("Not provided", page)
        self.assertNotIn("not-a-date", page)
        self.assertNotIn("2026-02-30", page)
        self.assertTrue(to_markdown(report, "en", []).endswith("\n"))

    def test_markdown_has_single_language_safe_links_and_claim_boundaries(self):
        report, catalog = fixture()
        report["en"]["main_events"][0]["what_changed"] = '<script>x</script> [new link](javascript:alert(1)) **untrusted format**'
        markdown = to_markdown(report, "en", catalog)
        self.assertIn("# English weekly fixture", markdown)
        self.assertIn("**Why it matters · editorial judgment**", markdown)
        self.assertIn("**Unverified points and uncertainty**", markdown)
        self.assertIn("[Original source](<https://publisher.example.org/article?x=1&y=2>)", markdown)
        self.assertIn("[Archived brief](<https://polyemergence.com/en/archive/one/>)", markdown)
        self.assertNotIn("<script>", markdown)
        self.assertIn(r"\[new link\]\(javascript:alert\(1\)\)", markdown)
        self.assertNotIn("中文周报测试标题", markdown)
        self.assertNotIn("中文原文标题", markdown)

    def test_rendering_is_deterministic_nonmutating_and_offline(self):
        report, catalog = fixture()
        before = copy.deepcopy((report, catalog))
        with patch("socket.getaddrinfo", side_effect=AssertionError("no network")), patch("builtins.open", side_effect=AssertionError("no file access")):
            first = render_review(report, catalog)
            second = render_review(report, catalog)
            markdown = to_markdown(report, "zh", catalog)
        self.assertEqual(first, second)
        self.assertEqual((report, catalog), before)
        self.assertIn("基于已有新闻摘要形成的审阅草稿", markdown)

    def test_invalid_markdown_locale_is_explicitly_rejected(self):
        with self.assertRaises(ValueError):
            to_markdown({}, "fr", [])


if __name__ == "__main__":
    unittest.main()
