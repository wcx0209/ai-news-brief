"""Publication gates use only synthetic records; no services or production DB."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from weekly_publication import latest_completed_week, prepare_publication


NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)
PUBLISHED = "2026-11-16T10:00:00Z"


def fixture():
    issue = {"week_start": "2026-11-09", "week_end": "2026-11-15", "timezone": "Asia/Singapore",
             "start": "2026-11-08T16:00:00Z", "end": "2026-11-15T16:00:00Z", "end_exclusive": True,
             "generated_at": "2026-11-16T02:00:00Z", "status": "DRAFT"}
    packet = {"issue": deepcopy(issue), "main_events": [], "early_signals": []}
    catalog = []
    for index in range(3):
        identifier = f"source-{index}"
        row = {"id": identifier, "url": f"https://source.example/story/{index}", "source": "Source Lab",
               "source_published_at": "2026-11-12T08:00:00Z", "published_at": "2026-11-12T08:00:00Z",
               "date_basis": "source_published", "domain": "ai", "domain_labels": {"en": "AI", "zh": "人工智能"},
               "archive_url_en": f"https://polyemergence.com/en/archive/2026/11/12/{index}/",
               "archive_url_zh": None,
               "en": {"title": f"Original title {index}", "summary": "PRIVATE SOURCE SUMMARY", "full": "PRIVATE FULL TEXT"},
               "zh": {"title": f"原标题{index}", "summary": "私密原始摘要", "full": "私密完整文本"}}
        catalog.append(row)
        packet["main_events"].append({"event_id": f"event-{index}", "evidence_ids": [identifier], "evidence": [deepcopy(row)]})
    report = {"issue": issue, "editorial_review": {"human_approved": False, "independently_verified": False,
                                                   "revision_made": False, "audit": {"issues": []}},
              "coverage": {"scope": "loaded_archive_only", "fields": [{"domain": "ai", "domain_labels": {"en": "AI", "zh": "人工智能"},
                                                                         "selected_count": 3, "qualified_count": 5}]}}
    for locale in ("zh", "en"):
        synthesis = {"intro": "A reading of this selection.", "limits": "This selection does not establish a global trend.",
                     "evidence_ids": ["source-0", "source-1"]}
        for dimension in ("signal", "structure", "consequence"):
            synthesis[dimension] = {"title": "What these examples suggest", "text": "The reported examples suggest a conditional interpretation.",
                                    "support": "selection_based", "evidence_ids": ["source-0", "source-1"]}
        report[locale] = {"title": "Weekly publication fixture", "dek": "A source-attributed selection.", "synthesis": synthesis,
                          "lead": {"text": "Two distinct selected events raise a question.", "evidence_ids": ["source-0", "source-1"]},
                          "main_events": [{"event_id": f"event-{index}", "title": f"Selected event {index}",
                                           "what_changed": "The source reports a change.", "why_it_matters": "This may matter if the claim holds.",
                                           "uncertainty": "The supplied material does not establish the strongest baseline.",
                                           "evidence_ids": [f"source-{index}"]} for index in range(3)],
                          "early_signals": [], "next_watch": [{"text": "Will the source publish a comparison?", "evidence_ids": ["source-0"]}],
                          "follow_up": {"available": False, "note": "No earlier issue was supplied.", "items": []}}
    return report, packet, catalog


def publish(report=None, packet=None, catalog=None, **kwargs):
    if report is None:
        report, packet, catalog = fixture()
    options = {"published_at": PUBLISHED, "user_authorized": True, "now": NOW, **kwargs}
    return prepare_publication(report, packet, catalog, **options)


class WeeklyPeriodPublicationTests(unittest.TestCase):
    def test_latest_complete_week_uses_sgt_not_utc_or_current_week(self):
        self.assertEqual(latest_completed_week("2026-11-15T15:59:59Z"), "2026-11-02")
        self.assertEqual(latest_completed_week("2026-11-15T16:00:00Z"), "2026-11-09")
        self.assertEqual(latest_completed_week("2026-11-16T18:00:00Z"), "2026-11-09")
        self.assertEqual(latest_completed_week("2026-11-23T00:00:00+08:00"), "2026-11-16")

    def test_period_is_exact_complete_monday_sgt_week_and_right_open(self):
        for changes in ({"week_start": "../../private"}, {"week_start": "2026-11-10"}, {"week_end": "2026-11-16"},
                        {"start": "2026-11-09T00:00:00Z"}, {"end": "2026-11-15T15:59:59Z"},
                        {"end_exclusive": False}, {"timezone": "UTC"}):
            report, packet, catalog = fixture()
            report["issue"].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                publish(report, packet, catalog)
        with self.assertRaises(ValueError):
            publish(now="2026-11-15T15:00:00Z")

    def test_packet_week_cannot_differ_from_the_report(self):
        report, packet, catalog = fixture()
        packet["issue"]["end"] = "2026-11-15T17:00:00Z"
        with self.assertRaises(ValueError):
            publish(report, packet, catalog)

    def test_publication_and_generated_times_require_timezone_and_sane_order(self):
        for stamp in ("2026-11-16", "2026-11-16T10:00:00", "2026-11-15T15:00:00Z", "2026-11-17T00:00:00Z"):
            with self.subTest(stamp=stamp), self.assertRaises(ValueError):
                publish(published_at=stamp)
        report, packet, catalog = fixture()
        report["issue"]["generated_at"] = "2026-11-16T11:00:00Z"
        with self.assertRaises(ValueError):
            publish(report, packet, catalog)


class WeeklySourceAndReferenceTests(unittest.TestCase):
    def test_three_distinct_main_events_and_present_synthesis_are_required(self):
        report, packet, catalog = fixture()
        packet["main_events"] = packet["main_events"][:2]
        with self.assertRaisesRegex(ValueError, "event_count"):
            publish(report, packet, catalog)
        report, packet, catalog = fixture()
        catalog[2]["url"] = catalog[1]["url"] + "?utm_source=repost"
        with self.assertRaisesRegex(ValueError, "distinct_main_events"):
            publish(report, packet, catalog)
        report, packet, catalog = fixture()
        report["en"].pop("synthesis")
        with self.assertRaisesRegex(ValueError, "synthesis_required"):
            publish(report, packet, catalog)

    def test_two_source_ids_for_one_event_do_not_support_a_dimension(self):
        report, packet, catalog = fixture()
        duplicate = deepcopy(catalog[0])
        duplicate["id"], duplicate["url"] = "official-0", "https://official.example/notice"
        catalog.append(duplicate)
        packet["main_events"][0]["evidence_ids"].append("official-0")
        for locale in ("zh", "en"):
            report[locale]["synthesis"]["signal"]["evidence_ids"] = ["source-0", "official-0"]
        with self.assertRaisesRegex(ValueError, "distinct_events"):
            publish(report, packet, catalog)

    def test_unknown_citations_translation_mismatch_and_unsafe_ids_fail(self):
        mutations = (
            lambda r, p, c: r["en"]["main_events"][0].update(evidence_ids=["unknown"]),
            lambda r, p, c: r["en"]["synthesis"]["structure"].update(evidence_ids=["source-0", "source-2"]),
            lambda r, p, c: p["main_events"][0].update(event_id="../event"),
            lambda r, p, c: c[0].update(id="source/../../private"),
            lambda r, p, c: r["en"]["follow_up"].update(available=True),
        )
        for mutation in mutations:
            report, packet, catalog = fixture()
            mutation(report, packet, catalog)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                publish(report, packet, catalog)

    def test_source_dates_are_original_with_no_created_or_first_seen_fallback(self):
        for change in ({"source_published_at": None, "published_at": None, "created_at": "2026-11-12T08:00:00Z"},
                       {"date_basis": "first_seen"}, {"source": "Unknown source"},
                       {"source_published_at": "2026-11-15T16:00:00Z"}, {"source_published_at": "2026-11-08T15:59:59Z"}):
            report, packet, catalog = fixture()
            catalog[0].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                publish(report, packet, catalog)

    def test_calendar_only_official_supplement_retains_honest_precision(self):
        report, packet, catalog = fixture()
        catalog[0].update(source_published_at="2026-11-12", published_at="2026-11-12",
                          date_precision="publisher_calendar_date_only", archive_url_en=None)
        source = next(row for row in publish(report, packet, catalog)["sources"] if row["id"] == "source-0")
        self.assertEqual(source["published_at"], "2026-11-12")
        self.assertEqual(source["date_precision"], "publisher_calendar_date_only")
        catalog[0]["date_precision"] = "timestamp"
        with self.assertRaises(ValueError):
            publish(report, packet, catalog)

    def test_unsafe_source_urls_signed_keys_and_archive_paths_are_rejected(self):
        for key, value in (("url", "http://169.254.169.254/latest/meta-data/"), ("url", "javascript:alert(1)"),
                           ("url", "https://source.example/story?api_key=private"),
                           ("archive_url_en", "https://evil.example/en/archive/a/"),
                           ("archive_url_en", "https://polyemergence.com/en/archive/%2e%2e/private/")):
            report, packet, catalog = fixture()
            catalog[0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                publish(report, packet, catalog)


class WeeklyProcessAndPrivacyTests(unittest.TestCase):
    def test_explicit_authorization_is_not_a_claim_of_human_or_fact_review(self):
        payload = publish(generation_metadata={"status": "failed"})
        self.assertEqual(payload["process"], {"ai_assisted": True, "human_reviewed": False, "independently_verified": False})
        self.assertEqual(payload["id"], "2026-11-09")
        self.assertNotIn("status", payload)

    def test_auto_requires_successful_generation_and_no_unresolved_high_or_medium(self):
        report, packet, catalog = fixture()
        with self.assertRaisesRegex(ValueError, "generation_not_successful"):
            publish(report, packet, catalog, user_authorized=False)
        for severity in ("high", "medium"):
            report["editorial_review"]["audit"]["issues"] = [{"severity": severity}]
            with self.subTest(severity=severity), self.assertRaisesRegex(ValueError, "unresolved"):
                publish(report, packet, catalog, user_authorized=False, generation_metadata={"status": "success"})
        report["editorial_review"]["audit"]["issues"] = []
        self.assertEqual(publish(report, packet, catalog, user_authorized=False, generation_metadata={"status": "success"})["id"], "2026-11-09")

    def test_auto_revision_requires_a_clean_post_revision_audit(self):
        report, packet, catalog = fixture()
        report["editorial_review"]["revision_made"] = True
        report["editorial_review"]["audit"] = {"issues": [{"severity": "high"}]}
        with self.assertRaisesRegex(ValueError, "audit"):
            publish(report, packet, catalog, user_authorized=False, generation_metadata={"status": "completed"})
        report["editorial_review"]["post_revision_audit"] = {"issues": []}
        self.assertEqual(publish(report, packet, catalog, user_authorized=False, generation_metadata={"status": "completed"})["process"]["independently_verified"], False)
        report["editorial_review"]["post_revision_audit"] = {"issues": [{"severity": "medium", "resolved": True}]}
        with self.assertRaisesRegex(ValueError, 'unresolved'):
            publish(report, packet, catalog, user_authorized=False, generation_metadata={"status": "completed"})

    def test_unsupported_verified_flags_are_not_laundered_by_authorization(self):
        report, packet, catalog = fixture()
        report["editorial_review"]["independently_verified"] = True
        with self.assertRaisesRegex(ValueError, "verification"):
            publish(report, packet, catalog)

    def test_allowlist_drops_raw_sources_audits_prompts_and_arbitrary_private_fields(self):
        report, packet, catalog = fixture()
        private = "DO NOT PUBLISH PRIVATE VALUE"
        report.update(email=private, api_key=private, raw_evidence=private, prompt=private, arbitrary=private)
        report["editorial_review"]["secret"] = private
        report["coverage"]["prompt"] = private
        for locale in ("en", "zh"):
            report[locale]["private_prompt"] = private
            report[locale]["main_events"][0]["raw"] = private
            report[locale]["lead"]["api_key"] = private
        catalog[0]["secret"] = private
        unused = deepcopy(catalog[0])
        unused.update(id="unused-source", source="Unused source", url="https://unused.example/story")
        catalog.append(unused)
        before = deepcopy((report, packet, catalog))
        payload = publish(report, packet, catalog)
        encoded = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn(private, encoded)
        self.assertNotIn("PRIVATE FULL TEXT", encoded)
        self.assertNotIn("PRIVATE SOURCE SUMMARY", encoded)
        self.assertNotIn("Unused source", encoded)
        self.assertEqual((report, packet, catalog), before)
        self.assertEqual(set(payload), {"schema_version", "id", "week_start", "week_end", "timezone", "period_start", "period_end",
                                        "published_at", "modified_at", "generated_at", "en", "zh", "sources", "coverage", "process"})

    def test_private_email_and_key_echo_in_allowed_text_fail_closed(self):
        for private in ("Contact wcx0209@hotmail.com", "Key AIza" + "x" * 35):
            report, packet, catalog = fixture()
            report["en"]["title"] = private
            with self.assertRaisesRegex(ValueError, "private_data"):
                publish(report, packet, catalog)


class WeeklyImmutabilityTests(unittest.TestCase):
    def test_republication_keeps_first_publication_and_does_not_fake_modification(self):
        prior = publish()
        current = publish(prior=prior, published_at="2026-11-16T11:00:00Z")
        self.assertEqual(current, prior)

    def test_only_explicit_manual_correction_can_change_published_body(self):
        prior = publish()
        report, packet, catalog = fixture()
        report["en"]["dek"] = "A manually corrected attribution."
        with self.assertRaisesRegex(ValueError, "immutable"):
            publish(report, packet, catalog, prior=prior, published_at="2026-11-16T11:00:00Z")
        revised = publish(report, packet, catalog, prior=prior, published_at="2026-11-16T11:00:00Z", manual_correction=True)
        self.assertEqual(revised["published_at"], prior["published_at"])
        self.assertEqual(revised["modified_at"], "2026-11-16T11:00:00Z")
        self.assertEqual(revised["en"]["dek"], "A manually corrected attribution.")

    def test_prior_cannot_belong_to_another_week_or_have_a_future_date(self):
        prior = publish()
        prior["id"] = "2026-11-02"
        with self.assertRaisesRegex(ValueError, "prior_issue"):
            publish(prior=prior)
        prior = publish()
        prior["published_at"] = "2026-11-17T00:00:00Z"
        with self.assertRaisesRegex(ValueError, "prior_publication"):
            publish(prior=prior)


if __name__ == "__main__":
    unittest.main()
