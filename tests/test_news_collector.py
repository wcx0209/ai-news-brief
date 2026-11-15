"""No local collection, database or LLM: all network/client calls are mocked."""

from pathlib import Path
import json
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import news_collector as news


SOURCE = {"id": 42, "url": "https://example.com/feed.xml", "name": "Official Example",
          "description": "[FIRST_PARTY] Original company announcements"}


def collector(**kwargs):
    return news.AgentReachCollector([SOURCE], config={}, **kwargs)


class DiscoveryContractTests(unittest.TestCase):
    def parse(self, fields, source=SOURCE, **kwargs):
        instance = collector(**kwargs)
        with patch.object(news.feedparser, "parse", return_value=SimpleNamespace(entries=fields, bozo=False)):
            return instance.parse_rss(source, b"<rss/>")

    def test_original_publication_query_id_and_provenance_survive(self):
        result = self.parse([{"title": "Release", "link": "https://example.com/blog?id=12&lang=zh",
                             "published": "2026-11-15T16:00:00+08:00", "updated": "2026-11-16T08:00:00Z"}])
        item = result["entries"][0]
        self.assertEqual(item["published_at"], "2026-11-15T08:00:00+00:00")
        self.assertEqual(item["updated_at"], "2026-11-16T08:00:00+00:00")
        self.assertEqual(item["link"], "https://example.com/blog?id=12&lang=zh")
        self.assertEqual(item["source_id"], 42)
        self.assertEqual(item["source_description"], SOURCE["description"])
        self.assertEqual(item["collector_backend"], "agent_reach")
        self.assertEqual(item["discovery_backend"], "public_rss")
        self.assertEqual(item["date_basis"], "source_published")

    def test_updated_and_missing_dates_never_become_publication_or_now(self):
        items = self.parse([
            {"title": "Updated only", "link": "https://example.com/a", "updated": "2026-11-15T08:00:00Z"},
            {"title": "Undated", "link": "https://example.com/b"},
            {"title": "Invalid", "link": "https://example.com/c", "published": "unparseable"},
        ])["entries"]
        self.assertEqual([item["published_at"] for item in items], [None, None, None])
        self.assertTrue(all(item["date_basis"] == "unknown" for item in items))
        self.assertEqual(items[0]["updated_at"], "2026-11-15T08:00:00+00:00")

    def test_feedparser_compatibility_alias_cannot_promote_updated(self):
        class Aliased(dict):
            def get(self, key, default=None):
                if key == "published":
                    return "2026-11-15T08:00:00Z"
                return super().get(key, default)
        item = self.parse([Aliased(title="Old post updated", link="https://example.com/a", updated="2026-11-15T08:00:00Z")])["entries"][0]
        self.assertIsNone(item["published_at"])

    def test_verge_keeps_ai_category_only(self):
        source = {**SOURCE, "url": "https://www.theverge.com/rss/index.xml"}
        result = self.parse([
            {"title": "AI model", "link": "https://www.theverge.com/ai", "tags": [{"term": "AI"}]},
            {"title": "Phone", "link": "https://www.theverge.com/phone", "tags": [{"term": "Tech"}]},
        ], source)
        self.assertEqual([item["title"] for item in result["entries"]], ["AI model"])

    def test_youtube_reddit_hn_flags_and_yc_blog_are_not_conflated(self):
        cases = [
            ("https://www.youtube.com/feeds/videos.xml?channel_id=UC12", "https://www.youtube.com/watch?v=12", "is_youtube"),
            ("https://www.reddit.com/r/MachineLearning/.rss", "https://www.reddit.com/r/MachineLearning/comments/12", "is_reddit"),
            ("https://news.ycombinator.com/rss", "https://example.com/post", "is_hackernews"),
        ]
        for source_url, link, flag in cases:
            with self.subTest(flag=flag):
                item = self.parse([{"title": "Story", "link": link, "comments": "https://news.ycombinator.com/item?id=3"}], {**SOURCE, "url": source_url})["entries"][0]
                self.assertTrue(item[flag])
                if flag == "is_hackernews":
                    self.assertEqual(item["comments_url"], "https://news.ycombinator.com/item?id=3")
        yc = self.parse([{"title": "Startup", "link": "https://www.ycombinator.com/blog/a"}], {**SOURCE, "url": "https://www.ycombinator.com/blog/rss.xml"})["entries"][0]
        self.assertNotIn("is_hackernews", yc)

    def test_official_adapter_preserves_existing_body_and_never_calls_legacy_parse(self):
        adapters = MagicMock()
        adapters._fetch_official_html_index.return_value = {
            "entries": [{"title": "Model", "link": "https://www.anthropic.com/news/model", "published_at": "2026-11-15T08:00:00Z", "official_content": "Verified publisher page body"}], "error": None}
        instance = collector(publisher_adapters=adapters)
        source = {**SOURCE, "url": "https://www.anthropic.com/news"}
        result = instance.parse_feed(source)
        adapters.parse_feed.assert_not_called()
        adapters._fetch_official_html_index.assert_called_once()
        self.assertFalse(adapters._fetch_official_html_index.call_args.args[1]["browser_fallback"])
        self.assertEqual(result["entries"][0]["official_content"], "Verified publisher page body")
        self.assertEqual(result["entries"][0]["discovery_backend"], "publisher_adapter")

    def test_special_sources_call_only_maintained_adapter_methods(self):
        adapters = MagicMock()
        cases = [
            ("https://huggingface.co/api/daily_papers", "_fetch_hf_daily_papers"),
            ("https://seed.bytedance.com/en/", "_fetch_bytedance_seed"),
            ("https://www.tencent.com/zh-cn/newsroom/", "_fetch_tencent_newsroom"),
        ]
        for url, method in cases:
            with self.subTest(method=method):
                getattr(adapters, method).return_value = {"entries": [], "error": None}
                result = collector(publisher_adapters=adapters).parse_feed({**SOURCE, "url": url})
                self.assertIsNone(result["error"])
                getattr(adapters, method).assert_called_once()
        adapters.parse_feed.assert_not_called()

    def test_feed_payload_and_entry_limits_apply_offline_too(self):
        instance = news.AgentReachCollector(config={"max_feed_bytes": 1024, "max_feed_entries": 1})
        self.assertEqual(instance.parse_rss(SOURCE, b"x" * 1025)["error"], "rss_too_large")
        raw = [{"title": "One", "link": "https://example.com/a"}, {"title": "Two", "link": "https://example.com/b"}]
        with patch.object(news.feedparser, "parse", return_value=SimpleNamespace(entries=raw, bozo=False)):
            self.assertEqual(len(instance.parse_rss(SOURCE, b"<rss/>")["entries"]), 1)

    def test_default_live_discovery_is_cloud_only(self):
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}):
            instance = collector()
            self.assertEqual(instance.parse_feed(SOURCE)["error"], "collector_cloud_only")
            self.assertEqual(instance.parse_feed({**SOURCE, "url": "https://www.anthropic.com/news"})["error"], "collector_cloud_only")

    def test_reused_default_adapter_still_checks_cloud_on_every_call(self):
        instance = collector()
        instance._publisher_adapters = MagicMock()
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}):
            result = instance.parse_feed({**SOURCE, "url": "https://www.anthropic.com/news"})
        self.assertEqual(result["error"], "collector_cloud_only")
        instance._publisher_adapters._fetch_official_html_index.assert_not_called()

    def test_unsafe_urls_are_rejected_without_transport_or_client_calls(self):
        transport, client = MagicMock(), MagicMock()
        instance = collector(rss_transport=transport, client=client)
        for url in ("http://127.0.0.1/rss", "http://169.254.169.254/latest/meta-data/", "http://[::1]/rss", "https://user:password@example.com/rss", "https://example.com\\@localhost/rss", "https://example.com:1234/rss"):
            with self.subTest(url=url):
                self.assertEqual(instance.parse_feed({**SOURCE, "url": url})["error"], "rss_invalid_url")
                self.assertFalse(instance.read_entry({"link": url})["ok"])
        transport.assert_not_called()
        client.read_web.assert_not_called()


class ReachReaderTests(unittest.TestCase):
    def test_real_channel_calls_return_envelope_without_changing_original_dates(self):
        client = MagicMock()
        envelope = {"schema_version": 1, "ok": True, "items": [{"text": "Reach result", "published_at": "2020-01-01T00:00:00Z"}]}
        for method in (client.read_web, client.read_youtube, client.read_github):
            method.return_value = envelope
        instance = collector(client=client)
        for url, method in (
            ("https://example.com/article?id=1", client.read_web),
            ("https://www.youtube.com/watch?v=12", client.read_youtube),
            ("https://youtu.be/12", client.read_youtube),
            ("https://github.com/NVIDIA/auto-ontology", client.read_github),
            ("https://github.com/QwenLM/Qwen3/releases/tag/v3", client.read_web),
            ("https://github.com/QwenLM/Qwen3/releases.atom", client.read_web),
            ("https://github.com/QwenLM/Qwen3/blob/main/README.md", client.read_web),
        ):
            with self.subTest(url=url):
                item = {"link": url, "published_at": "2026-11-15T08:00:00Z", "official_content": "Not the default reader result"}
                self.assertIs(instance.read_entry(item), envelope)
                method.assert_called_with(url)
                self.assertEqual(item["published_at"], "2026-11-15T08:00:00Z")

    def test_failed_reach_read_is_not_silently_replaced_with_old_content(self):
        client = MagicMock()
        failure = {"schema_version": 1, "ok": False, "items": [], "error": {"code": "RATE_LIMITED"}}
        client.read_web.return_value = failure
        self.assertIs(collector(client=client).read_entry({"link": "https://example.com/post", "official_content": "Old captured text"}), failure)

    def test_close_does_not_construct_unused_components(self):
        instance = collector()
        instance.close()
        self.assertIsNone(instance._client)
        client, adapters = MagicMock(), MagicMock()
        collector(client=client, publisher_adapters=adapters).close()
        client.close.assert_called_once()
        adapters.close.assert_called_once()

    def test_default_factory_and_unknown_backend_fail_closed(self):
        with patch.object(news.ConfigLoader, "get_instance", return_value=SimpleNamespace(get=lambda key, default=None: {})):
            instance = news.get_news_collector()
        self.assertIsInstance(instance, news.AgentReachCollector)
        self.assertEqual(instance.backend, "agent_reach")
        with self.assertRaisesRegex(ValueError, "Unsupported collector backend"):
            news.get_news_collector(config={"backend": "misspelled"})

    def test_legacy_is_available_only_as_an_explicit_rollback(self):
        import rss_fetcher
        with patch.object(rss_fetcher, "RSSFetcher") as old_fetcher:
            result = news.get_news_collector([SOURCE], config={"backend": "legacy"})
        old_fetcher.assert_called_once_with([SOURCE])
        self.assertIs(result, old_fetcher.return_value)
        self.assertEqual(result.backend, "legacy")


class GitHubReleaseDiscoveryTests(unittest.TestCase):
    source = {**SOURCE, "url": "https://github.com/QwenLM/Qwen3/releases.atom", "name": "Qwen Releases"}

    @staticmethod
    def release(**updates):
        return {"draft": False, "name": "Qwen release", "tag_name": "v3.1",
                "html_url": "https://github.com/QwenLM/Qwen3/releases/tag/v3.1",
                "published_at": "2026-11-15T08:00:00Z", "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2026-11-16T08:00:00Z", "body": "Publisher's release notes", **updates}

    def parse(self, payload):
        transport = MagicMock(return_value=json.dumps(payload).encode("utf-8"))
        instance = collector(rss_transport=transport)
        return instance.parse_feed(self.source), transport, instance

    def test_official_json_endpoint_preserves_release_date_canonical_and_source(self):
        import rss_fetcher
        with patch.object(rss_fetcher.RSSFetcher, "parse_feed", side_effect=AssertionError("Legacy is forbidden")) as old:
            result, transport, _ = self.parse([self.release()])
        old.assert_not_called()
        transport.assert_called_once_with("https://api.github.com/repos/QwenLM/Qwen3/releases?per_page=20")
        self.assertIsNone(result["error"])
        item = result["entries"][0]
        self.assertEqual(item["link"], "https://github.com/QwenLM/Qwen3/releases/tag/v3.1")
        self.assertEqual(item["published_at"], "2026-11-15T08:00:00+00:00")
        self.assertEqual(item["updated_at"], "2026-11-16T08:00:00+00:00")
        self.assertEqual(item["source_id"], SOURCE["id"])
        self.assertEqual(item["source_url"], self.source["url"])
        self.assertEqual(item["discovery_backend"], "publisher_adapter")
        self.assertEqual(item["discovery_subtype"], "github_releases_json")
        self.assertEqual(item["date_basis"], "source_published")
        self.assertNotIn("official_content", item)

    def test_missing_publication_never_uses_updated_created_or_now(self):
        absent = self.release()
        absent.pop("published_at")
        result, _, _ = self.parse([absent, self.release(published_at=None), self.release(published_at="bad date")])
        self.assertEqual(result["entries"], [])
        self.assertEqual(result["error"], "github_releases_no_dated_entries")

    def test_drafts_or_noncanonical_other_repository_release_urls_are_rejected(self):
        for release in (
            self.release(draft=True), self.release(draft=None),
            self.release(html_url="https://github.com/Other/Qwen3/releases/tag/v3.1"),
            self.release(html_url="https://github.com/QwenLM/Other/releases/tag/v3.1"),
            self.release(html_url="http://github.com/QwenLM/Qwen3/releases/tag/v3.1"),
            self.release(html_url="https://github.com.evil.example/QwenLM/Qwen3/releases/tag/v3.1"),
            self.release(html_url="https://github.com/QwenLM/Qwen3/releases/tag/../other"),
        ):
            with self.subTest(release=release):
                result, _, _ = self.parse([release])
            self.assertEqual(result["entries"], [])

    def test_only_exact_atom_source_gets_github_json_routing(self):
        self.assertEqual(news.github_release_repository(self.source["url"]), ("QwenLM", "Qwen3"))
        for url in (
            "https://github.com/QwenLM/Qwen3", "https://github.com/QwenLM/Qwen3/releases/tag/v3.1",
            "https://github.com/QwenLM/Qwen3/releases.atom?token=secret", "https://github.com.evil.example/QwenLM/Qwen3/releases.atom",
            "http://github.com/QwenLM/Qwen3/releases.atom", "https://github.com/../Qwen3/releases.atom",
        ):
            with self.subTest(url=url):
                self.assertIsNone(news.github_release_repository(url))

    def test_release_body_read_uses_reach_web_not_repository_creation_date(self):
        result, _, instance = self.parse([self.release()])
        instance._client = MagicMock()
        instance.read_entry(result["entries"][0])
        instance.client.read_web.assert_called_once_with("https://github.com/QwenLM/Qwen3/releases/tag/v3.1")
        instance.client.read_github.assert_not_called()
        self.assertEqual(result["entries"][0]["published_at"], "2026-11-15T08:00:00+00:00")

    def test_invalid_json_payload_does_not_fall_back_to_feed_updated_dates(self):
        result, transport, _ = self.parse({"message": "Not Found"})
        self.assertEqual(result["error"], "github_releases_invalid_response")
        self.assertEqual(result["entries"], [])
        self.assertEqual(transport.call_count, 1)


class PinnedTransportTests(unittest.TestCase):
    def run_transport(self, responses, *, addresses=None, settings=None):
        import source_images
        requests = MagicMock()
        session = requests.Session.return_value.__enter__.return_value
        session.get.side_effect = responses
        instance = news.AgentReachCollector(config=settings or {})
        with patch.dict(sys.modules, {"requests": requests}), patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), \
                patch.object(source_images, "_resolve_public", side_effect=addresses or [["93.184.216.34"]] * 4) as resolve, \
                patch.object(source_images, "_pinned_adapter", return_value="pinned") as pin:
            result = instance.parse_feed(SOURCE)
        return result, session, resolve, pin

    @staticmethod
    def response(status=200, headers=None, chunks=None):
        response = MagicMock()
        response.__enter__.return_value = response
        response.status_code = status
        response.headers = headers or {"Content-Type": "application/rss+xml"}
        response.iter_content.return_value = chunks or [b"<rss/>"]
        return response

    def test_tls_dns_pinning_no_proxy_and_stream_limits(self):
        with patch.object(news.feedparser, "parse", return_value=SimpleNamespace(entries=[], bozo=False)):
            result, session, resolve, pin = self.run_transport([self.response()])
        self.assertIsNone(result["error"])
        self.assertFalse(session.trust_env)
        pin.assert_called_once_with("example.com", "93.184.216.34", 443)
        resolve.assert_called_once_with(SOURCE["url"])
        self.assertTrue(session.get.call_args.kwargs["verify"])
        self.assertFalse(session.get.call_args.kwargs["allow_redirects"])
        self.assertTrue(session.get.call_args.kwargs["stream"])

    def test_redirect_private_dns_target_is_rejected_before_second_request(self):
        response = self.response(302, {"Location": "https://second.example.com/feed"})
        result, session, resolve, _ = self.run_transport([response], addresses=[["93.184.216.34"], ValueError("private DNS")])
        self.assertEqual(result["error"], "source_discovery_failed")
        self.assertEqual(resolve.call_count, 2)
        self.assertEqual(session.get.call_count, 1)

    def test_redirect_to_metadata_address_is_rejected_before_dns_or_request(self):
        response = self.response(302, {"Location": "http://169.254.169.254/latest/meta-data/"})
        result, session, resolve, _ = self.run_transport([response])
        self.assertEqual(result["error"], "rss_invalid_redirect")
        self.assertEqual(resolve.call_count, 1)
        self.assertEqual(session.get.call_count, 1)

    def test_content_size_and_challenge_html_are_not_parsed(self):
        for response, expected in (
            (self.response(headers={"Content-Type": "application/xml", "Content-Length": "1025"}), "rss_too_large"),
            (self.response(chunks=[b"x" * 600, b"x" * 600]), "rss_too_large"),
            (self.response(headers={"Content-Type": "text/html"}), "rss_response_not_xml"),
        ):
            with self.subTest(expected=expected), patch.object(news.feedparser, "parse") as parse:
                result, _, _, _ = self.run_transport([response], settings={"max_feed_bytes": 1024})
            self.assertEqual(result["error"], expected)
            parse.assert_not_called()

    def test_forbidden_or_rate_limit_does_not_retry_a_different_reader(self):
        for status, expected in ((403, "rss_forbidden"), (429, "rss_rate_limited")):
            response = self.response(status)
            error = RuntimeError("No body or credentials are logged")
            error.response = SimpleNamespace(status_code=status)
            response.raise_for_status.side_effect = error
            with self.subTest(status=status):
                result, session, _, _ = self.run_transport([response])
            self.assertEqual(result["error"], expected)
            self.assertEqual(session.get.call_count, 1)

    def test_github_style_403_with_zero_remaining_is_a_rate_limit_not_a_parse_error(self):
        result, session, _, _ = self.run_transport([self.response(403, {'X-RateLimit-Remaining': '0'})])
        self.assertEqual(result['error'], 'rss_rate_limited')
        self.assertEqual(session.get.call_count, 1)

    def test_mixed_public_and_private_ipv6_dns_fails_before_any_connection(self):
        import source_images
        import socket
        requests = MagicMock()
        session = requests.Session.return_value.__enter__.return_value
        addresses = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                     (socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd00::1", 443, 0, 0))]
        with patch.dict(sys.modules, {"requests": requests}), patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), \
                patch.object(source_images.socket, "getaddrinfo", return_value=addresses), \
                patch.object(source_images, "_pinned_adapter") as pin:
            result = collector().parse_feed(SOURCE)
        self.assertEqual(result["error"], "source_discovery_failed")
        pin.assert_not_called()
        session.get.assert_not_called()

    def test_json_mime_is_allowed_only_for_the_specific_github_api_route(self):
        import source_images
        requests = MagicMock()
        session = requests.Session.return_value.__enter__.return_value
        response = self.response(headers={"Content-Type": "application/json"}, chunks=[b"[]"])
        session.get.return_value = response
        endpoint = "https://api.github.com/repos/QwenLM/Qwen3/releases?per_page=20"
        with patch.dict(sys.modules, {"requests": requests}), patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), \
                patch.object(source_images, "_resolve_public", return_value=["93.184.216.34"]), \
                patch.object(source_images, "_pinned_adapter", return_value="pinned"):
            self.assertEqual(collector()._fetch_rss(endpoint, json_endpoint=True), b"[]")
            with self.assertRaisesRegex(ValueError, "rss_response_not_xml"):
                collector()._fetch_rss(SOURCE["url"])
            with self.assertRaisesRegex(ValueError, "github_releases_invalid_endpoint"):
                collector()._fetch_rss("https://example.com/releases?per_page=20", json_endpoint=True)
        self.assertEqual(session.get.call_args_list[0].kwargs["headers"]["Accept"], "application/vnd.github+json")


class RealRssFixtureTests(unittest.TestCase):
    def test_rss_pubdate_and_atom_updated_only_fixture(self):
        rss = b'''<rss version="2.0"><channel><title>News</title><link>https://example.com</link><description>News</description>
          <item><title>Original release</title><link>https://example.com/news?id=1</link><pubDate>Sun, 15 Nov 2026 08:00:00 GMT</pubDate></item></channel></rss>'''
        item = collector(rss_transport=lambda url: rss).parse_feed(SOURCE)["entries"][0]
        self.assertEqual(item["published_at"], "2026-11-15T08:00:00+00:00")
        atom = b'''<feed xmlns="http://www.w3.org/2005/Atom"><title>News</title><id>https://example.com</id>
          <entry><title>Updated old entry</title><id>urn:1</id><link href="https://example.com/old"/><updated>2026-11-15T08:00:00Z</updated></entry></feed>'''
        item = collector(rss_transport=lambda url: atom).parse_feed(SOURCE)["entries"][0]
        self.assertIsNone(item["published_at"])
        self.assertEqual(item["updated_at"], "2026-11-15T08:00:00+00:00")

    def test_rss_discovery_succeeds_when_legacy_fetcher_is_forbidden(self):
        import rss_fetcher
        rss = b'''<rss version="2.0"><channel><title>News</title><link>https://example.com</link><description>News</description>
          <item><title>Release</title><link>https://example.com/new</link><pubDate>Sun, 15 Nov 2026 08:00:00 GMT</pubDate></item></channel></rss>'''
        with patch.object(rss_fetcher.RSSFetcher, "parse_feed", side_effect=AssertionError("Legacy discovery is forbidden")) as old:
            result = collector(rss_transport=lambda url: rss).parse_feed(SOURCE)
        self.assertIsNone(result["error"])
        self.assertEqual(result["entries"][0]["title"], "Release")
        old.assert_not_called()


if __name__ == "__main__":
    unittest.main()
