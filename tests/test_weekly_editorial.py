"""Pure weekly selection fixtures: no production data, DB, network, or LLM."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weekly_editorial import REGISTERED_DOMAINS, build_weekly_plan, canonical_report_url


def article(identifier="a", *, domain="ai", importance=85, confidence=80, **overrides):
    stamp = "2026-11-12T08:00:00Z"
    item = {
        "id": identifier, "url": f"https://publisher.example/news/{identifier}", "source": f"Publisher {identifier}",
        "source_published_at": stamp, "published_at": "2026-11-16T08:00:00Z", "date_basis": "source_published",
        "source_dates": {"source_published_at": stamp, "verified": True},
        "source_category": domain, "category": "company", "domain": domain,
        "domain_labels": {"en": domain, "zh": "测试领域"}, "importance": importance,
        "scores": {"signal": 80, "structure": 80, "consequence": 80, "confidence": confidence, "momentum": 10},
        "en": {"title": f"Company {identifier} launches a distinct technology platform", "summary": "A source-attributed summary.", "full": "Existing full summary."},
        "zh": {"title": f"公司{identifier}发布面向独特用途的技术平台", "summary": "原有中文摘要。", "full": "已有完整摘要。"},
        "tags": [f"product {identifier}", f"company {identifier}"], "source_type": "media_report",
        "archive_url_en": "https://polyemergence.com/en/archive/2026/11/12/a/",
        "archive_url_zh": "https://polyemergence.com/zh/archive/2026/11/12/a/",
    }
    item.update(deepcopy(overrides))
    return item


class WeeklyDateAndGateTests(unittest.TestCase):
    def test_sgt_complete_week_boundaries_and_original_not_site_date(self):
        items = []
        for identifier, stamp in (
            ("before", "2026-11-08T15:59:59Z"), ("start", "2026-11-08T16:00:00Z"),
            ("last", "2026-11-15T15:59:59Z"), ("end", "2026-11-15T16:00:00Z"),
            ("future", "2027-01-01T00:00:00Z"),
        ):
            items.append(article(identifier, source_published_at=stamp, source_dates={"source_published_at": stamp, "verified": True}))
        plan = build_weekly_plan(items)
        ids = {identifier for group in plan["candidates"] for identifier in group["evidence_ids"]}
        self.assertEqual(ids, {"start", "last"})
        self.assertEqual(plan["exclusion_counts"], {"after_week_or_future": 2, "before_week": 1})
        self.assertTrue(plan["period"]["end_exclusive"])

    def test_unknown_first_seen_trending_and_unverified_published_are_not_allowed(self):
        records = [article("seen", date_basis="first_seen"), article("unknown", date_basis="unknown"),
                   article("trending", source="GitHub Trending"),
                   article("trending-url", source_url="https://github.com/trending?since=weekly"),
                   article("unverified", source_published_at=None, source_dates={}, date_basis=None),
                   article("no-date", source_published_at=None, source_dates={}, published_at=None),
                   article("bad", source_published_at="not a date", source_dates={}),
                   article("naive", source_published_at="2026-11-12T08:00:00", source_dates={})]
        plan = build_weekly_plan(records)
        self.assertEqual(plan["candidates"], [])
        self.assertEqual(len(plan["exclusions"]), len(records))

    def test_verified_published_fallback_and_offset_normalization(self):
        record = article("verified", source_published_at=None, source_dates={"verified": True},
                         published_at="2026-11-09T00:00:00+08:00")
        item = build_weekly_plan([record])["candidates"][0]["representative"]
        self.assertEqual(item["source_published_at"], "2026-11-08T16:00:00Z")

    def test_date_metadata_conflicts_and_explicit_unverified_are_rejected(self):
        records = [article("conflict", source_dates={"source_published_at": "2026-11-13T00:00:00Z", "verified": True}),
                   article("negative", source_dates={"verified": False})]
        self.assertEqual(build_weekly_plan(records)["exclusion_counts"], {"conflicting_original_dates": 1, "unknown_original_date": 1})

    def test_bilingual_quality_confidence_and_bad_url_gates_never_relax_for_sparse_fields(self):
        records = [article("low", domain="neurotechnology", importance=64),
                   article("confidence", domain="space_economy", confidence=64),
                   article("translation", zh={"title": "新闻", "summary": ""}),
                   article("url", url="javascript:alert(1)"), article("source", source=""),
                   article("id", id=None)]
        plan = build_weekly_plan(records, min_importance=0, min_confidence=0)
        self.assertEqual(plan["candidates"], [])
        self.assertEqual(plan["selection_rules"]["min_importance"], 65)
        self.assertEqual(plan["selection_rules"]["min_confidence"], 65)
        self.assertIn("库内", plan["domain_counts"]["neurotechnology"]["notice"]["zh"])


class ConservativeEventGroupingTests(unittest.TestCase):
    def test_exact_report_url_merges_tracking_but_preserves_original_links_and_ids(self):
        a = article("one", url="https://publisher.example/story?id=12&utm_source=mail#top")
        b = article("two", url="http://www.publisher.example/story/?id=12")
        plan = build_weekly_plan([a, b])
        group = plan["candidates"][0]
        self.assertEqual(len(plan["candidates"]), 1)
        self.assertEqual(group["evidence_ids"], ["one", "two"])
        self.assertEqual(group["report_count"], 1)
        self.assertEqual({item["url"] for item in group["support"]}, {a["url"], b["url"]})
        self.assertNotEqual(canonical_report_url("https://publisher.example/story?id=12"), canonical_report_url("https://publisher.example/story?id=13"))

    def test_bilingual_reprints_group_and_original_source_is_representative(self):
        official = article("official", source="Original Lab", importance=80, source_type="official_release",
                           en={"title": "OpenAI introduces GPT-5.1 for reliable tool use", "summary": "Official summary."},
                           zh={"title": "OpenAI发布GPT-5.1并改善可靠工具使用能力", "summary": "官方摘要。"}, tags=["OpenAI", "GPT-5.1"])
        media = article("reprint", source="Media", importance=95, en=deepcopy(official["en"]), zh=deepcopy(official["zh"]), tags=official["tags"])
        group = build_weekly_plan([media, official])["candidates"][0]
        self.assertEqual(group["representative"]["id"], "official")
        self.assertEqual(group["evidence_ids"], ["official", "reprint"])
        self.assertEqual(group["source_count"], 2)
        self.assertIsNone(group["independent_source_count"])
        self.assertFalse(group["claims_verified"])

    def test_different_versions_actions_or_events_do_not_merge_on_company_tags(self):
        common = {"tags": ["OpenAI", "GPT"], "zh": {"title": "", "summary": "中文摘要"}}
        records = [
            article("release-1", **common, en={"title": "OpenAI releases GPT-5.1 for enterprise tool use", "summary": "Summary."}),
            article("release-2", **common, en={"title": "OpenAI releases GPT-5.2 for enterprise tool use", "summary": "Summary."}),
            article("funding", **common, en={"title": "OpenAI raises funding for enterprise tool use", "summary": "Summary."}),
        ]
        # Titles are required in both languages; use distinct truthful fixture titles.
        for record in records:
            record["zh"]["title"] = "测试记录 " + record["id"]
        self.assertEqual(len(build_weekly_plan(records)["candidates"]), 3)

    def test_related_generic_tags_and_generic_titles_are_not_event_evidence(self):
        a = article("generic-a", tags=["AI", "Research", "Models"],
                    en={"title": "Scientists discover unexpected behavior in large models", "summary": "Summary."},
                    zh={"title": "我国科研团队在人工智能领域取得重要研究进展", "summary": "摘要。"})
        b = article("generic-b", tags=a["tags"], en=deepcopy(a["en"]), zh=deepcopy(a["zh"]))
        self.assertEqual(len(build_weekly_plan([a, b])["candidates"]), 2)

    def test_same_title_more_than_48_hours_apart_is_not_forced_into_one_event(self):
        a = article("first", tags=["Specific platform", "Specific lab"])
        b = article("later", en=a["en"], zh=a["zh"], tags=a["tags"], source_published_at="2026-11-15T12:00:00Z", source_dates={})
        self.assertEqual(len(build_weekly_plan([a, b])["candidates"]), 2)


class WeeklyBalanceAndAuditTests(unittest.TestCase):
    def test_main_eight_signals_two_with_bounded_diversity_and_full_audit(self):
        records = [article(f"ai-{index}", importance=95-index) for index in range(8)]
        records += [article(f"field-{index}", domain=domain, importance=92-index)
                    for index, domain in enumerate(REGISTERED_DOMAINS[1:])]
        plan = build_weekly_plan(records)
        self.assertEqual(len(plan["shortlist"]["main"]), 8)
        self.assertEqual(len(plan["shortlist"]["signals"]), 2)
        self.assertLessEqual(sum(group["representative"]["domain"] == "ai" for group in plan["shortlist"]["main"]), 3)
        self.assertEqual(len(plan["domain_counts"]), 11)
        self.assertFalse(plan["claims_verified"])
        self.assertEqual(plan["coverage"]["scope"], "loaded_archive_only")
        self.assertTrue(all(group["selection_reason"].get("zh") for group in plan["candidates"]))

    def test_low_scoring_sparse_field_is_not_promoted_over_quality_floor(self):
        records = [article(f"ai-{index}", importance=99-index) for index in range(5)]
        records += [article("weak", domain="space_economy", importance=69)]
        plan = build_weekly_plan(records)
        self.assertNotIn("weak", [group["representative"]["id"] for group in plan["shortlist"]["main"]])
        self.assertTrue(any(item["code"] == "main_shortfall" for item in plan["warnings"]))
        self.assertEqual(plan["domain_counts"]["neurotechnology"]["status"], "no_qualifying_record_in_loaded_archive")

    def test_limits_are_bounded_and_source_records_are_not_mutated(self):
        records = [article(f"item-{index}", domain=REGISTERED_DOMAINS[index % 11], importance=80)
                   for index in range(50)]
        original = deepcopy(records)
        plan = build_weekly_plan(records, max_candidates=100, max_main=100, max_signals=100)
        self.assertLessEqual(len(plan["candidates"]), 24)
        self.assertLessEqual(sum(len(value) for value in plan["shortlist"].values()), 12)
        self.assertEqual(records, original)
        self.assertEqual(plan["candidates"][0]["representative"]["archive_url_en"], original[0]["archive_url_en"])
        json.dumps(plan, ensure_ascii=False)

    def test_input_order_does_not_change_plan(self):
        records = [article(str(index), domain=REGISTERED_DOMAINS[index % 11], importance=80 + index % 10)
                   for index in range(30)]
        before = build_weekly_plan(records)
        random.Random(20261116).shuffle(records)
        self.assertEqual(build_weekly_plan(records), before)

    def test_unknown_future_domain_is_not_silently_treated_as_ai(self):
        plan = build_weekly_plan([article("future", domain="future_field")])
        self.assertEqual(plan["candidates"][0]["representative"]["domain"], "future_field")
        self.assertIn("future_field", plan["domain_counts"])

    def test_invalid_week_and_empty_archive(self):
        for start, end in (("bad", "2026-11-15T16:00:00Z"), ("2026-11-15", "2026-11-16"),
                           ("2026-11-15T16:00:00Z", "2026-11-08T16:00:00Z")):
            with self.assertRaises(ValueError):
                build_weekly_plan([], start_utc=start, end_utc=end)
        empty = build_weekly_plan([])
        self.assertEqual(empty["shortlist"], {"main": [], "signals": []})
        self.assertEqual(len(empty["domain_counts"]), 11)


if __name__ == "__main__":
    unittest.main()
