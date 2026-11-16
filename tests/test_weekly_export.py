"""Static weekly publication fixtures never use a model, database or network."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weekly_export_fixture", ROOT / "scripts/export_weekly.py")
exporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(exporter)


def fixture(identifier="2026-11-09"):
    monday = date.fromisoformat(identifier)
    start = datetime.combine(monday, datetime.min.time(), timezone(timedelta(hours=8))).astimezone(timezone.utc)
    end = start + timedelta(days=7)
    iso = lambda value: value.isoformat().replace("+00:00", "Z")
    payload = {"schema_version": 1, "id": identifier, "week_start": identifier,
               "week_end": (monday + timedelta(days=6)).isoformat(), "timezone": "Asia/Singapore",
               "period_start": iso(start), "period_end": iso(end), "generated_at": iso(end + timedelta(hours=9)),
               "published_at": iso(end + timedelta(hours=10)), "modified_at": iso(end + timedelta(hours=11)),
               "process": {"ai_assisted": True, "human_reviewed": False, "independently_verified": False},
               "coverage": {"scope": "loaded_archive_only", "fields": []},
               "sources": [{"id": "source-one", "url": "https://source.example/research?a=1&b=2", "source": "Research Desk",
                            "published_at": iso(start + timedelta(days=2)), "date_precision": "timestamp", "domain": "ai",
                            "domain_labels": {"en": "AI", "zh": "人工智能"}, "archive_url_en": None, "archive_url_zh": None,
                            "en": {"title": "A source title"}, "zh": {"title": "原文标题"}}]}
    for locale, title, dek in (("en", 'A weekly <signal> & "context"', "An attributed weekly selection."),
                               ("zh", "本周科技观察", "保留来源与不确定性的选材。")):
        event = {"event_id": "one", "title": title, "what_changed": "A source reports a result.",
                 "why_it_matters": "The result may affect a workflow.", "uncertainty": "Independent replication is not supplied.",
                 "evidence_ids": ["source-one"]}
        point = {"title": title, "text": "A conditional interpretation.", "support": "selection_based", "evidence_ids": ["source-one"]}
        payload[locale] = {"title": title, "dek": dek, "synthesis": {"intro": dek, "limits": "Not an industry-wide measurement.",
                             "evidence_ids": ["source-one"], **{key: deepcopy(point) for key in ("signal", "structure", "consequence")}},
                           "lead": {"text": dek, "evidence_ids": ["source-one"]}, "main_events": [event], "early_signals": [],
                           "next_watch": [], "follow_up": {"available": False, "note": "No comparison supplied.", "items": []}}
    return payload


def snapshots(output):
    return {str(path.relative_to(output)): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in output.rglob("*") if path.is_file()}


class WeeklyExportTests(unittest.TestCase):
    def test_static_outputs_have_canonical_routes_stored_dates_and_escaped_xml(self):
        payload = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = exporter.export_weeklies(output, [payload])
            self.assertEqual(len(paths), 9)
            self.assertTrue(all(path.is_file() for path in paths))
            manifest = json.loads((output / "data/weekly/index.json").read_text())
            self.assertEqual(manifest["latest"], payload["id"])
            self.assertEqual(manifest["modified_at"], payload["modified_at"])
            self.assertEqual(manifest["editions"][0]["canonical_urls"]["en"], "https://polyemergence.com/en/weekly/2026-11-09/")
            self.assertNotIn("sources", manifest["editions"][0])
            self.assertNotIn("synthesis", manifest["editions"][0]["en"])
            for locale in ("en", "zh"):
                html = (output / locale / "weekly/2026-11-09/index.html").read_text()
                self.assertIn(f'rel="canonical" href="https://polyemergence.com/{locale}/weekly/2026-11-09/"', html)
                self.assertIn('hreflang="zh-Hans" href="https://polyemergence.com/zh/weekly/2026-11-09/"', html)
                self.assertNotIn("<signal>", html)
                channel = ET.parse(output / f"weekly-{locale}.xml").getroot().find("channel")
                self.assertEqual(channel.findtext("item/title"), payload[locale]["title"])
                self.assertEqual(channel.findtext("item/description"), payload[locale]["dek"])
                self.assertEqual(parsedate_to_datetime(channel.findtext("item/pubDate")), exporter._timestamp(payload["published_at"]))
                self.assertEqual(parsedate_to_datetime(channel.findtext("lastBuildDate")), exporter._timestamp(payload["modified_at"]))
                self.assertEqual(channel.find("item/guid").get("isPermaLink"), "true")
            sitemap = ET.parse(output / "weekly-sitemap.xml").getroot()
            self.assertEqual(sitemap.tag, f"{{{exporter.SITEMAP_NS}}}urlset")
            self.assertEqual(len(sitemap), 4)
            for node in sitemap:
                self.assertEqual(node.findtext(f"{{{exporter.SITEMAP_NS}}}lastmod"), payload["modified_at"])
                self.assertEqual(len(node.findall(f"{{{exporter.XHTML_NS}}}link")), 3)

    def test_public_projection_omits_private_fields_at_every_level_without_mutating_input(self):
        payload = fixture()
        secret = "/private/reports/private-debug.json"
        payload["private_report_path"] = secret
        payload["editorial_review"] = {"private_audit": secret}
        payload["en"]["private_draft"] = secret
        payload["en"]["main_events"][0]["private_notes"] = secret
        payload["sources"][0]["en"]["full"] = secret
        payload["sources"][0]["private_report_path"] = secret
        payload["process"]["model_trace"] = secret
        original = deepcopy(payload)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            paths = exporter.export_weeklies(output, [payload])
            self.assertTrue(all(secret not in path.read_text() for path in paths))
            self.assertEqual(json.loads((output / "data/weekly/2026-11-09.json").read_text()), fixture())
        self.assertEqual(payload, original)

    def test_repeat_export_is_byte_and_timestamp_stable_and_atomic(self):
        payload = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            with patch.object(exporter.os, "replace", wraps=os.replace) as replace:
                paths = exporter.export_weeklies(output, [payload])
                self.assertEqual(replace.call_count, len(paths))
                for call in replace.call_args_list:
                    self.assertEqual(Path(call.args[0]).parent, Path(call.args[1]).parent)
            before = snapshots(output)
            with patch.object(exporter.os, "replace", wraps=os.replace) as replace:
                self.assertEqual(exporter.export_weeklies(output, [deepcopy(payload)]), paths)
                replace.assert_not_called()
            self.assertEqual(snapshots(output), before)
            self.assertFalse(list(output.rglob("*.tmp")))

    def test_new_issue_keeps_earlier_edition_and_corrections_keep_rss_publication_time(self):
        older, latest = fixture("2026-11-02"), fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            exporter.export_weeklies(output, [older])
            exporter.export_weeklies(output, [latest])
            correction = deepcopy(older)
            correction["en"]["dek"] = "A corrected description."
            correction["modified_at"] = "2026-11-17T03:00:00Z"
            exporter.export_weeklies(output, [correction], allow_corrections=True)
            manifest = json.loads((output / "data/weekly/index.json").read_text())
            self.assertEqual([row["id"] for row in manifest["editions"]], ["2026-11-09", "2026-11-02"])
            self.assertEqual(manifest["modified_at"], latest["modified_at"])
            self.assertTrue((output / "en/weekly/2026-11-02/index.html").is_file())
            rows = ET.parse(output / "weekly-en.xml").getroot().findall("channel/item")
            self.assertEqual(parsedate_to_datetime(rows[1].findtext("pubDate")), exporter._timestamp(older["published_at"]))
            nodes = ET.parse(output / "weekly-sitemap.xml").getroot()
            for node in nodes:
                if node.findtext(f"{{{exporter.SITEMAP_NS}}}loc").endswith("/2026-11-02/"):
                    self.assertEqual(node.findtext(f"{{{exporter.SITEMAP_NS}}}lastmod"), correction["modified_at"])

    def test_existing_editions_are_immutable_unless_explicitly_corrected_without_republishing(self):
        payload = fixture()
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            exporter.export_weeklies(output, [payload])
            before = snapshots(output)
            correction = deepcopy(payload)
            correction["en"]["title"] = "An explicitly corrected title"
            correction["modified_at"] = "2026-11-17T03:00:00Z"
            with self.assertRaisesRegex(ValueError, "immutable"):
                exporter.export_weeklies(output, [correction])
            self.assertEqual(snapshots(output), before)
            republished = deepcopy(correction)
            republished["published_at"] = "2026-11-17T02:00:00Z"
            with self.assertRaisesRegex(ValueError, "preserve original published_at"):
                exporter.export_weeklies(output, [republished], allow_corrections=True)
            self.assertEqual(snapshots(output), before)
            backwards = deepcopy(correction)
            backwards["modified_at"] = payload["published_at"]
            with self.assertRaisesRegex(ValueError, "backwards"):
                exporter.export_weeklies(output, [backwards], allow_corrections=True)
            self.assertEqual(snapshots(output), before)
            exporter.export_weeklies(output, [correction], allow_corrections=True)
            stored = json.loads((output / "data/weekly/2026-11-09.json").read_text())
            self.assertEqual(stored["published_at"], payload["published_at"])
            self.assertEqual(stored["en"]["title"], correction["en"]["title"])

    def test_load_and_cli_only_use_dated_public_json_and_leave_other_sitemaps_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            exporter.export_weeklies(output, [fixture()])
            (output / "data/weekly/index.json").write_text("not an edition")
            (output / "data/weekly/private-draft.json").write_text("also not an edition")
            (output / "sitemap.xml").write_text("Keep the existing main URLSET")
            self.assertEqual([row["id"] for row in exporter.load_editions(output)], ["2026-11-09"])
            with patch("socket.create_connection", side_effect=AssertionError("No network is allowed")):
                self.assertEqual(exporter.main(["--output", str(output)]), 0)
            self.assertEqual((output / "sitemap.xml").read_text(), "Keep the existing main URLSET")
            self.assertEqual(json.loads((output / "data/weekly/index.json").read_text())["latest"], "2026-11-09")

    def test_invalid_routes_dates_or_duplicates_fail_before_changing_any_file(self):
        changes = [
            {"id": "../../private"}, {"id": "2026-02-30"}, {"id": "2026-11-10"},
            {"week_start": "2026-11-02"}, {"week_end": "2026-11-16"}, {"timezone": "UTC"},
            {"period_end": "2026-11-16T16:00:00Z"}, {"published_at": "2026-11-16T02:00:00"},
            {"modified_at": "2026-11-15T18:00:00Z"},
            {"canonical_urls": {"en": "https://elsewhere.example/en/weekly/2026-11-09/", "zh": "https://polyemergence.com/zh/weekly/2026-11-09/"}},
        ]
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            exporter.export_weeklies(output, [fixture()])
            before = snapshots(output)
            for change in changes:
                invalid = fixture()
                invalid.update(change)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    exporter.export_weeklies(output, [invalid])
                self.assertEqual(snapshots(output), before)
            with self.assertRaisesRegex(ValueError, "Duplicate"):
                exporter.export_weeklies(output, [fixture(), fixture()])
            self.assertEqual(snapshots(output), before)

    def test_all_html_is_rendered_and_checked_before_the_first_write(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for failure in (RuntimeError("Renderer failed"), '<link rel="canonical" href="https://wrong.example/">'):
                with self.subTest(failure=failure):
                    kwargs = {"side_effect": failure} if isinstance(failure, Exception) else {"return_value": failure}
                    with patch.object(exporter, "render_weekly_index", **kwargs), patch.object(exporter, "_atomic_write") as writer:
                        with self.assertRaises((RuntimeError, ValueError)):
                            exporter.export_weeklies(output, [fixture()])
                        writer.assert_not_called()
                    self.assertEqual(list(output.iterdir()), [])

    def test_filename_mismatch_and_symlink_escape_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory, tempfile.TemporaryDirectory() as elsewhere:
            output = Path(directory)
            dated = output / "data/weekly/2026-11-02.json"
            dated.parent.mkdir(parents=True)
            dated.write_text(json.dumps(fixture()))
            with self.assertRaisesRegex(ValueError, "filename"):
                exporter.load_editions(output)
            dated.unlink()
            (output / "en").mkdir()
            (output / "en/weekly").symlink_to(Path(elsewhere), target_is_directory=True)
            before = snapshots(output)
            with self.assertRaisesRegex(ValueError, "escapes"):
                exporter.export_weeklies(output, [fixture()])
            self.assertEqual(list(Path(elsewhere).iterdir()), [])
            self.assertEqual(snapshots(output), before)

    def test_empty_export_is_honest_and_has_no_invented_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertEqual(len(exporter.export_weeklies(output, [])), 6)
            manifest = json.loads((output / "data/weekly/index.json").read_text())
            self.assertIsNone(manifest["latest"])
            self.assertIsNone(manifest["modified_at"])
            self.assertEqual(manifest["editions"], [])
            self.assertIsNone(ET.parse(output / "weekly-en.xml").getroot().find("channel/lastBuildDate"))
            self.assertEqual(len(ET.parse(output / "weekly-sitemap.xml").getroot()), 2)


if __name__ == "__main__":
    unittest.main()
