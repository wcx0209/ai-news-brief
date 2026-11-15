import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
SPEC = importlib.util.spec_from_file_location("reach_probe", ROOT / "scripts" / "check_agent_reach.py")
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def envelope(channel, backend, url, text="public content " * 30):
    return {"schema_version": 1, "ok": True, "channel": channel,
            "action": "read", "backend": backend,
            "items": [{"url": url, "text": text, "published_at": "2026-11-14T12:00:00Z"}],
            "meta": {"attempts": [{"backend": backend, "result": "ok"}]}, "error": None}


class ReachProbeTests(unittest.TestCase):
    def test_manifest_is_offline_and_honest_about_rss(self):
        with patch("socket.getaddrinfo", side_effect=AssertionError("network")):
            manifest = probe.source_manifest()
            report = probe.build_report(manifest=manifest)
        self.assertEqual(manifest["source_count"], 205)
        self.assertEqual(sum(manifest["route_counts"].values()), 205)
        sources = {source["name"]: source for source in manifest["sources"]}
        self.assertEqual(sources["OpenAI News"]["discovery_backend"], "public_rss")
        self.assertEqual(sources["Anthropic News"]["publisher_adapter"], "official_html")
        self.assertEqual(sources["ByteDance Seed"]["publisher_adapter"], "bytedance_seed")
        self.assertEqual(sources["Tencent Newsroom"]["publisher_adapter"], "tencent_newsroom")
        self.assertEqual(sources["Hugging Face Daily Papers"]["publisher_adapter"], "huggingface_json")
        self.assertEqual(sources["Meta Llama Releases"]["article_channel"], "web")
        self.assertEqual(sources["Ollama Releases"]["publisher_adapter"], "github_releases_json")
        self.assertEqual(sources["Ollama Releases"]["discovery_backend"], "publisher_adapter")
        self.assertFalse(sources["Tencent Newsroom"]["publisher_content_reuse"])
        self.assertEqual(sources["Dwarkesh Patel"]["article_channel"], "youtube")
        self.assertFalse(manifest["native_agent_reach_rss"])
        self.assertFalse(report["live_migration_verified"])

    def test_live_guard_precedes_constructor_and_runtime(self):
        with patch.dict(os.environ, {}, clear=True), patch("agent_reach_client.AgentReachClient") as client:
            with self.assertRaisesRegex(RuntimeError, "GitHub Actions"):
                probe.probe_readers(probe.source_manifest())
            with self.assertRaisesRegex(RuntimeError, "GitHub Actions"):
                probe.build_report(probe=True, runtime=MagicMock())
        client.assert_not_called()

    def test_exact_official_revision_is_required_not_only_version(self):
        distribution = MagicMock()
        distribution.version = probe.AGENT_REACH_VERSION
        distribution.read_text.return_value = json.dumps({"url": f"https://github.com/Panniantong/Agent-Reach/archive/{probe.AGENT_REACH_COMMIT}.zip"})
        with patch.object(probe.metadata, "distribution", return_value=distribution):
            self.assertTrue(probe.installed_runtime()["pinned_revision_verified"])
            distribution.read_text.return_value = json.dumps({"url": "https://pypi.org/agent-reach"})
            self.assertFalse(probe.installed_runtime()["pinned_revision_verified"])

    def test_vcs_pin_is_supported_but_other_repo_is_not(self):
        distribution = MagicMock()
        distribution.version = probe.AGENT_REACH_VERSION
        provenance = {"url": "https://github.com/Panniantong/Agent-Reach.git",
                      "vcs_info": {"commit_id": probe.AGENT_REACH_COMMIT}}
        distribution.read_text.return_value = json.dumps(provenance)
        with patch.object(probe.metadata, "distribution", return_value=distribution):
            self.assertTrue(probe.installed_runtime()["pinned_revision_verified"])
            provenance["url"] = "https://github.com/someone/Agent-Reach"
            distribution.read_text.return_value = json.dumps(provenance)
            self.assertFalse(probe.installed_runtime()["pinned_revision_verified"])

    def test_unrelated_reader_url_cannot_pass(self):
        result = envelope("web", "jina", "https://other.example/article")
        summary = probe.summarize_read("web", "https://www.anthropic.com/news", result,
                                       expected_channel="web", allowed_backends={"jina", "exa"})
        self.assertEqual(summary["status"], "failed")
        self.assertFalse(summary["samples"][0]["matches_original_url"])

    def test_errors_and_attempt_messages_cannot_leak_secrets(self):
        result = {"ok": False, "channel": "web", "items": [],
                  "meta": {"attempts": [{"backend": "jina", "result": "RATE_LIMITED", "message": "token=SECRET"}]},
                  "error": {"code": "RATE_LIMITED", "message": "token=SECRET", "hint": "SECRET"}}
        summary = probe.summarize_read("web", "https://public.example/page", result,
                                       expected_channel="web", allowed_backends={"jina"})
        self.assertNotIn("SECRET", json.dumps(summary))
        self.assertEqual(summary["error_code"], "RATE_LIMITED")
        self.assertIsNone(probe._report_url("https://public.example/page?access_token=SECRET"))

    def test_probe_uses_only_new_paths_and_preserves_original_date(self):
        client = MagicMock()
        client.read_web.side_effect = lambda url: envelope("web", "jina", url,
            "public content " * 30 + "\n## [poly / example](https://github.com/poly/example)")
        client.read_github.side_effect = lambda url: envelope("github", "github-api", url)
        client.read_youtube.return_value = {"schema_version": 1, "ok": False, "channel": "youtube", "action": "subtitle",
                                           "backend": None, "items": [], "meta": {"attempts": [{"backend": "yt-dlp", "result": "PLATFORM_BLOCKED"}]},
                                           "error": {"code": "PLATFORM_BLOCKED", "message": "verification required"}}
        entry = {"link": "https://www.youtube.com/watch?v=abcdefghijk", "published_at": "2026-11-14T12:00:00+00:00",
                 "date_basis": "source_published", "discovery_backend": "public_rss"}
        collector = MagicMock()
        release_entry = {"link": "https://github.com/ollama/ollama/releases/tag/v0.1.0",
                         "published_at": "2026-11-14T12:00:00+00:00", "date_basis": "source_published",
                         "discovery_backend": "publisher_adapter", "discovery_subtype": "github_releases_json"}
        collector.parse_feed.side_effect = lambda source: {"entries": [release_entry if source["name"] == "Ollama Releases" else entry], "error": None}
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}), patch("rss_fetcher.RSSFetcher.parse_feed", side_effect=AssertionError("legacy")):
            checks = probe.probe_readers(probe.source_manifest(), collector=collector, client=client)
        self.assertEqual([item["status"] for item in checks if item.get("required")], ["ok", "ok", "ok"])
        self.assertEqual(next(item for item in checks if item["name"] == "github_trending")["parsed_repositories"], 1)
        video = next(item for item in checks if item["name"] == "youtube_interview")
        self.assertTrue(video["original_date_unchanged"])
        self.assertEqual(video["error_code"], "PLATFORM_BLOCKED")
        client.read_youtube.assert_called_once_with(entry["link"])
        collector.close.assert_called_once()

    def test_missing_runtime_does_not_attempt_live_reader(self):
        reader = MagicMock()
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            report = probe.build_report(probe=True, runtime=lambda: {"pinned_revision_verified": False}, reader=reader)
        self.assertEqual(report["status"], "failed")
        reader.assert_not_called()

    def test_broken_channel_feed_still_tests_a_previously_public_video_without_new_discovery(self):
        client, collector = MagicMock(), MagicMock()
        collector.parse_feed.return_value = {'entries': [], 'error': 'rss_http_404'}
        client.read_web.side_effect = lambda url: envelope('web', 'jina', url)
        client.read_github.side_effect = lambda url: envelope('github', 'github-api', url)
        client.read_youtube.side_effect = lambda url: envelope('youtube', 'yt-dlp', url)
        existing = {'link': 'https://www.youtube.com/watch?v=abcdefghijk', 'published_at': '2026-11-12T11:00:00Z',
                    'source': 'Existing public channel', 'canary_basis': 'existing_public_archive'}
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(probe, '_archived_youtube_canary', return_value=existing):
            checks = probe.probe_readers(probe.source_manifest(), collector=collector, client=client)
        video = next(item for item in checks if item['name'] == 'youtube_interview')
        self.assertEqual(video['status'], 'ok')
        self.assertEqual(video['canary_basis'], 'existing_public_archive')
        self.assertTrue(video['original_date_unchanged'])
        self.assertEqual(next(item for item in checks if item['name'] == 'youtube_rss')['status'], 'failed')

    def test_only_real_core_readers_gate_success_and_advisory_is_visible(self):
        checks = [{"name": "official_web", "required": True, "status": "ok"},
                  {"name": "github_repository", "required": True, "status": "ok"},
                  {"name": "official_github_release", "required": True, "status": "ok"},
                  {"name": "youtube_interview", "required": False, "status": "failed"}]
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            report = probe.build_report(probe=True, runtime=lambda: {"pinned_revision_verified": True}, reader=lambda manifest: checks)
        self.assertTrue(report["live_migration_verified"])
        self.assertEqual(report["advisories"], ["youtube_interview"])

    def test_release_without_original_publication_date_fails_gate(self):
        client = MagicMock()
        client.read_web.side_effect = lambda url: envelope("web", "jina", url)
        client.read_github.side_effect = lambda url: envelope("github", "github-api", url)
        collector = MagicMock()
        collector.parse_feed.return_value = {"entries": [{"link": "https://github.com/ollama/ollama/releases/tag/v0.1.0",
                                                         "updated_at": "2026-11-14T12:00:00Z"}], "error": None}
        with patch.dict(os.environ, {"GITHUB_ACTIONS": "true"}):
            checks = probe.probe_readers(probe.source_manifest(), collector=collector, client=client)
        release = next(item for item in checks if item["name"] == "official_github_release")
        self.assertEqual(release["status"], "failed")
        self.assertEqual(release["published_release_entries"], 0)

    def test_release_discovery_failure_keeps_the_actual_reason(self):
        client, collector = MagicMock(), MagicMock()
        client.read_web.side_effect = lambda url: envelope('web', 'jina', url)
        client.read_github.side_effect = lambda url: envelope('github', 'github-api', url)
        collector.parse_feed.return_value = {'entries': [], 'error': 'rss_rate_limited'}
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(probe, '_archived_youtube_canary', return_value=None):
            checks = probe.probe_readers(probe.source_manifest(), collector=collector, client=client)
        release = next(item for item in checks if item['name'] == 'official_github_release')
        self.assertEqual(release['error_code'], 'rss_rate_limited')

    def test_cli_manifest_output_is_not_live_verification(self):
        with tempfile.TemporaryDirectory() as tmp, patch("socket.getaddrinfo", side_effect=AssertionError("network")):
            output = Path(tmp) / "manifest.json"
            self.assertEqual(probe.main(["--manifest-only", "--output", str(output)]), 0)
            report = json.loads(output.read_text())
        self.assertEqual(report["mode"], "offline_manifest")
        self.assertFalse(report["live_migration_verified"])
        self.assertFalse(any(report["effects"].values()))


if __name__ == "__main__":
    unittest.main()
