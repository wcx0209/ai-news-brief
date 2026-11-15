"""Offline safety and routing tests; no upstream install, network or database."""

from copy import deepcopy
from pathlib import Path
import socket
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from agent_reach_client import AGENT_REACH_COMMIT, AGENT_REACH_REQUIREMENT, AgentReachClient


def envelope(channel="web", action="read", backend="jina", *, text="Public article.",
             url="https://example.org/canonical", published_at=None, code=None, message="Reader failed"):
    return {
        "schema_version": 1, "ok": code is None, "channel": channel, "action": action,
        "backend": backend if code is None else None,
        "items": [] if code else [{"title": "An article", "url": url, "author": None,
                                     "published_at": published_at, "text": text, "raw": None}],
        "meta": {"elapsed_ms": 10, "attempts": [{"backend": backend}]},
        "error": {"code": code, "message": message, "hint": ""} if code else None,
    }


class Dispatcher:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, channel, action, params, *, timeout, only_backend):
        self.calls.append((channel, action, params, timeout, only_backend))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class AgentReachClientTests(unittest.TestCase):
    def test_dependency_is_pinned_to_the_reviewed_commit_not_pypi(self):
        self.assertEqual(AGENT_REACH_COMMIT, "c70ae6da5d39bc90e09ad2ae0575ccc89f31e284")
        self.assertIn(AGENT_REACH_COMMIT + ".zip", AGENT_REACH_REQUIREMENT)

    def test_real_local_execution_is_disabled_before_import_or_dns(self):
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "false"}), \
                patch("agent_reach_client.socket.getaddrinfo") as dns, \
                patch.object(AgentReachClient, "_upstream_dispatch") as dispatch:
            result = AgentReachClient().read_web("https://example.org/news")
        self.assertEqual(result["error"]["code"], "LOCAL_EXECUTION_DISABLED")
        dns.assert_not_called()
        dispatch.assert_not_called()

    def test_mock_dispatcher_is_offline_and_preserves_url_and_missing_date(self):
        source = envelope()
        dispatcher = Dispatcher(source)
        with patch("agent_reach_client.socket.getaddrinfo", side_effect=AssertionError("No network")):
            result = AgentReachClient(dispatcher=dispatcher).read_web("https://example.org/story?id=7#news")
        self.assertTrue(result["ok"])
        self.assertEqual(result["items"][0]["url"], "https://example.org/canonical")
        self.assertIsNone(result["items"][0]["published_at"])
        self.assertEqual(dispatcher.calls[0][2], {"target": "https://example.org/story?id=7#news"})
        self.assertEqual(dispatcher.calls[0][-1], "jina")
        self.assertNotIn("content_type", source["meta"])

    def test_web_ordinary_failure_uses_jina_then_exa(self):
        dispatcher = Dispatcher(envelope(code="UPSTREAM_BROKEN"), envelope(backend="exa"))
        result = AgentReachClient(dispatcher=dispatcher).action("web", "read", "https://example.org/news")
        self.assertTrue(result["ok"])
        self.assertEqual([call[-1] for call in dispatcher.calls], ["jina", "exa"])
        self.assertEqual(len(result["meta"]["attempts"]), 2)
        self.assertLessEqual(sum(call[3] for call in dispatcher.calls), 67.5)

    def test_terminal_errors_never_switch_web_provider(self):
        for code in ("PLATFORM_BLOCKED", "NEED_LOGIN", "RATE_LIMITED", "NOT_FOUND", "BAD_INPUT", "BUSY"):
            with self.subTest(code=code):
                dispatcher = Dispatcher(envelope(code=code))
                result = AgentReachClient(dispatcher=dispatcher).read_web("https://example.org/news")
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"]["code"], code)
                self.assertEqual(len(dispatcher.calls), 1)

    def test_misclassified_challenges_stop_before_exa(self):
        for message in ("Jina Reader 返回了反爬验证页", "CAPTCHA required", "HTTP 403: denied", "Sign in to confirm you're not a bot"):
            with self.subTest(message=message):
                dispatcher = Dispatcher(envelope(code="UPSTREAM_BROKEN", message=message))
                result = AgentReachClient(dispatcher=dispatcher).read_web("https://example.org/news")
                self.assertEqual(result["error"]["code"], "PLATFORM_BLOCKED")
                self.assertEqual(len(dispatcher.calls), 1)

    def test_exception_revealing_a_challenge_does_not_switch_or_leak_payload(self):
        dispatcher = Dispatcher(RuntimeError("CAPTCHA at https://example.org/?token=secret"))
        result = AgentReachClient(dispatcher=dispatcher).read_web("https://example.org/news")
        self.assertEqual(result["error"]["code"], "PLATFORM_BLOCKED")
        self.assertNotIn("secret", result["error"]["message"])
        self.assertEqual(len(dispatcher.calls), 1)

    def test_youtube_prefers_subtitles_and_does_not_invent_a_date(self):
        dispatcher = Dispatcher(envelope("youtube", "subtitle", "yt-dlp", url="https://www.youtube.com/watch?v=abc"))
        result = AgentReachClient(dispatcher=dispatcher).read_youtube("https://youtu.be/abc")
        self.assertTrue(result["ok"])
        self.assertEqual(dispatcher.calls[0][0:2], ("youtube", "subtitle"))
        self.assertEqual(dispatcher.calls[0][-1], "yt-dlp")
        self.assertEqual(result["meta"]["content_type"], "video_subtitles")
        self.assertIsNone(result["items"][0]["published_at"])

    def test_youtube_missing_subtitles_may_use_labeled_description(self):
        dispatcher = Dispatcher(envelope("youtube", "subtitle", "yt-dlp", code="NOT_FOUND"),
                                envelope("youtube", "read", "yt-dlp", text="Video description", published_at="2026-11-14"))
        result = AgentReachClient(dispatcher=dispatcher).read_youtube("https://www.youtube.com/watch?v=abc")
        self.assertTrue(result["ok"])
        self.assertEqual([call[1] for call in dispatcher.calls], ["subtitle", "read"])
        self.assertEqual([call[-1] for call in dispatcher.calls], ["yt-dlp", "yt-dlp"])
        self.assertEqual(result["meta"]["content_type"], "video_description")
        self.assertEqual(result["items"][0]["published_at"], "2026-11-14")

    def test_youtube_block_login_rate_and_generic_failure_do_not_fallback(self):
        for code in ("PLATFORM_BLOCKED", "NEED_LOGIN", "RATE_LIMITED", "UPSTREAM_BROKEN", "TIMEOUT"):
            dispatcher = Dispatcher(envelope("youtube", "subtitle", "yt-dlp", code=code))
            result = AgentReachClient(dispatcher=dispatcher).read_youtube("https://youtu.be/abc")
            self.assertEqual(result["error"]["code"], code)
            self.assertEqual(len(dispatcher.calls), 1)

    def test_github_uses_only_public_api_not_gh_or_browser(self):
        dispatcher = Dispatcher(envelope("github", "read", "github-api", url="https://github.com/example/project", published_at="2020-01-01T00:00:00Z"))
        result = AgentReachClient(dispatcher=dispatcher).read_github("https://github.com/example/project")
        self.assertEqual(dispatcher.calls[0][-1], "github-api")
        self.assertEqual(result["items"][0]["published_at"], "2020-01-01T00:00:00Z")

    def test_forbidden_actions_and_channel_host_confusion_never_dispatch(self):
        dispatcher = Dispatcher()
        client = AgentReachClient(dispatcher=dispatcher)
        for channel, action, url in (("web", "setup", "https://example.org"),
                                     ("youtube", "transcribe", "https://youtu.be/abc"),
                                     ("web", "search", "https://example.org"),
                                     ("github", "read", "https://github.com.example.org/repo"),
                                     ("youtube", "read", "https://example.org/video")):
            result = client.action(channel, action, url)
            self.assertEqual(result["error"]["code"], "BAD_INPUT")
        self.assertEqual(dispatcher.calls, [])

    def test_private_credential_signed_and_malformed_urls_are_rejected(self):
        urls = ["file:///etc/passwd", "ftp://example.org/a", "javascript:alert(1)",
                "https://user:password@example.org/a", "http://localhost/a", "http://localhost./a",
                "http://service.internal/a", "http://metadata.google.internal/computeMetadata/v1/",
                "http://127.0.0.1/a", "http://127.1/a", "http://2130706433/a", "http://0177.0.0.1/a",
                "http://10.0.0.1/a", "http://192.168.1.1/a", "http://169.254.169.254/a",
                "http://224.0.0.1/a", "http://[ff02::1]/a",
                "http://168.63.129.16/a", "http://100.100.100.200/a", "http://[::1]/a",
                "http://[::ffff:127.0.0.1]/a", "https://example.org:9021/a", "https://example.org\\@localhost/a",
                " https://example.org/a", "https://example.org/a\n", "https://example.org/a?token=secret",
                "https://example.org/a?%61pi_key=secret", "https://example.org/a?%2574oken=secret",
                "https://example.org/a?X-Amz-Signature=secret", "https://example.org/a#access_token=secret"]
        dispatcher = Dispatcher()
        client = AgentReachClient(dispatcher=dispatcher)
        for url in urls:
            with self.subTest(url=url):
                result = client.read_web(url)
                self.assertEqual(result["error"]["code"], "BAD_INPUT")
                self.assertNotIn("secret", result["error"]["message"])
        self.assertEqual(dispatcher.calls, [])

    def test_hostname_resolving_to_any_private_address_is_rejected(self):
        def resolver(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443)),
                    (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.1", 443))]
        dispatcher = Dispatcher()
        result = AgentReachClient(dispatcher=dispatcher, resolver=resolver).read_web("https://example.org")
        self.assertEqual(result["error"]["code"], "BAD_INPUT")
        self.assertEqual(dispatcher.calls, [])

    def test_total_text_cap_and_upstream_object_are_preserved(self):
        response = envelope(text="1234567890")
        response["items"].append(deepcopy(response["items"][0]))
        result = AgentReachClient(max_chars=12, dispatcher=Dispatcher(response)).read_web("https://example.org")
        self.assertEqual([item["text"] for item in result["items"]], ["1234567890", "12"])
        self.assertTrue(result["meta"]["text_truncated"])
        self.assertEqual(response["items"][1]["text"], "1234567890")

    def test_invalid_envelope_or_unsafe_canonical_url_fails_closed(self):
        unsafe = envelope(url="http://127.0.0.1/private")
        wrong_provider = envelope(backend="browser")
        invalid_attempts = envelope()
        invalid_attempts["meta"]["attempts"] = 5
        for response in (None, {}, {"schema_version": 2, "ok": True}, unsafe, wrong_provider, invalid_attempts):
            dispatcher = Dispatcher(response, response)
            result = AgentReachClient(dispatcher=dispatcher).read_web("https://example.org")
            self.assertFalse(result["ok"])
            self.assertEqual(result["items"], [])

    def test_real_cloud_path_validates_dns_and_only_uses_the_reviewed_backend(self):
        def resolver(*args, **kwargs):
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))]
        with patch.dict("os.environ", {"GITHUB_ACTIONS": "true"}), \
                patch.object(AgentReachClient, "_upstream_dispatch", return_value=envelope()) as dispatch:
            result = AgentReachClient(resolver=resolver).read_web("https://example.org/news")
        self.assertTrue(result["ok"])
        self.assertEqual(dispatch.call_args.kwargs["only_backend"], "jina")

    def test_upstream_saved_configuration_is_not_read_or_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.yaml"
            config_path.touch()
            fake_config = types.ModuleType("agent_reach.config")
            fake_config.Config = type("Config", (), {"CONFIG_FILE": config_path})
            with patch.dict(sys.modules, {"agent_reach.config": fake_config}):
                result = AgentReachClient._upstream_dispatch("web", "read", {"target": "https://example.org"},
                                                           timeout=45, only_backend="jina")
        self.assertEqual(result["error"]["code"], "UNSAFE_RUNTIME_CONFIG")

    def test_invalid_constructor_settings_are_rejected(self):
        for kwargs in ({"timeout": 0}, {"timeout": float("inf")}, {"timeout": True},
                       {"max_chars": 0}, {"max_chars": 1.5}, {"max_chars": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                AgentReachClient(**kwargs)


if __name__ == "__main__":
    unittest.main()
