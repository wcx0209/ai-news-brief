"""Restricted, cloud-only reader for a reviewed Agent Reach revision.

This is not the upstream installer or CLI. Only public read operations are
exposed, and no login, browser, transcription, search, or setup action is used.
Web targets are disclosed to Jina Reader and, after an ordinary read failure,
Exa; never pass private, authenticated, or signed links to this adapter.

An injected dispatcher makes tests entirely offline. Its contract is
``dispatcher(channel_name, action, params, timeout=..., only_backend=...)`` and
its return value is the upstream schema-version-1 result envelope.
"""

from __future__ import annotations

from copy import deepcopy
import ipaddress
import math
import os
import re
import socket
import time
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urlsplit


AGENT_REACH_VERSION = "1.6.1"
AGENT_REACH_COMMIT = "c70ae6da5d39bc90e09ad2ae0575ccc89f31e284"
AGENT_REACH_REQUIREMENT = (
    "agent-reach @ https://github.com/Panniantong/Agent-Reach/archive/"
    + AGENT_REACH_COMMIT + ".zip"
)
AGENT_REACH_REQUESTS_REQUIREMENT = "requests==2.32.5"
AGENT_REACH_YTDLP_REQUIREMENT = "yt-dlp[default]==2026.8.19"

_STOP_CODES = frozenset({"PLATFORM_BLOCKED", "NEED_LOGIN", "RATE_LIMITED", "BUSY"})
_WEB_FALLBACK_CODES = frozenset({"UPSTREAM_BROKEN", "TIMEOUT", "NEED_SETUP"})
_SENSITIVE_KEYS = frozenset({
    "access_token", "accesstoken", "api_key", "apikey", "auth", "authorization",
    "auth_token", "bearer", "code", "cookie", "credential", "credentials",
    "jwt", "key", "key-pair-id", "password", "passwd", "policy", "secret",
    "session", "sessionid", "session_id", "sig", "signature", "token",
    "refresh_token", "client_secret", "csrf", "csrf_token", "xsrf_token",
})
_BLOCKED_HOSTS = frozenset({
    "localhost", "localhost.localdomain", "metadata.google.internal",
    "metadata.goog", "instance-data", "instance-data.ec2.internal",
})
_PRIVATE_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".localdomain", ".home.arpa")
_BLOCKED_IPS = frozenset({"168.63.129.16", "100.100.100.200"})
_CHALLENGE = re.compile(
    r"captcha|反爬验证|人机验证|验证码|verify (?:you are|that you are|your humanity)|"
    r"security verification|cloudflare (?:challenge|verification)|"
    r"sign in to confirm|not a bot|access denied|http[ :]+(?:401|403|429)\b",
    re.IGNORECASE,
)


def _error(channel: str, action: str, code: str, message: str) -> dict:
    return {
        "schema_version": 1, "ok": False, "channel": channel, "action": action,
        "backend": None, "items": [], "meta": {"elapsed_ms": 0, "attempts": []},
        "error": {"code": code, "message": message, "hint": (
            "Stop automation; do not switch providers or attempt a login."
            if code in _STOP_CODES else ""
        )},
    }


def _public_ip(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return (ip.is_global and not ip.is_multicast and not ip.is_reserved
            and not ip.is_unspecified and str(ip) not in _BLOCKED_IPS)


def _sensitive_query(query: str) -> bool:
    for key, _ in parse_qsl(query, keep_blank_values=True):
        # Reject double-encoded credential keys as well as ordinary query keys.
        key = unquote(unquote(key)).lower().replace("[]", "")
        if key in _SENSITIVE_KEYS or key.startswith(("x-amz-", "x-goog-", "oauth_")):
            return True
    return False


def _validate_url(target: Any, resolver: Callable | None = None) -> str:
    """Validate without normalizing the source/canonical URL or its parameters."""
    if not isinstance(target, str) or not target or len(target) > 8192:
        raise ValueError("A public HTTP(S) URL is required")
    if target != target.strip() or re.search(r"[\s\\\x00-\x1f\x7f]", target):
        raise ValueError("Whitespace, controls, and backslashes are not allowed in URLs")
    try:
        parsed = urlsplit(target)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        raise ValueError("The URL is malformed") from None
    if parsed.scheme not in {"http", "https"} or not host:
        raise ValueError("Only public HTTP(S) URLs are permitted")
    if parsed.username is not None or parsed.password is not None or "@" in parsed.netloc:
        raise ValueError("Authenticated URLs are not permitted")
    if port is not None and port not in {80, 443}:
        raise ValueError("Only standard public web ports are permitted")
    host = host.rstrip(".").lower()
    if not host or "%" in host or host in _BLOCKED_HOSTS or host.endswith(_PRIVATE_SUFFIXES):
        raise ValueError("Local, metadata, and private network targets are not permitted")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        raise ValueError("The URL hostname is invalid") from None
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        if not _public_ip(str(ip)):
            raise ValueError("Local, metadata, and private IP addresses are not permitted")
    else:
        # inet_aton recognizes abbreviated, octal and integer IPv4 forms that
        # ipaddress (correctly) refuses; browsers/network stacks may still use them.
        try:
            legacy_ip = socket.inet_ntoa(socket.inet_aton(host))
        except OSError:
            legacy_ip = None
        if legacy_ip is not None:
            if not _public_ip(legacy_ip):
                raise ValueError("Non-public numeric IP addresses are not permitted")
        elif "." not in host or not re.fullmatch(r"[a-z0-9.-]+", host):
            raise ValueError("A valid public hostname is required")
    if _sensitive_query(parsed.query) or ("=" in parsed.fragment and _sensitive_query(parsed.fragment)):
        raise ValueError("Signed URLs and sensitive credential query parameters are not permitted")
    if resolver is not None:
        try:
            addresses = resolver(host, port or (443 if parsed.scheme == "https" else 80),
                                 type=socket.SOCK_STREAM)
        except (OSError, ValueError):
            raise ValueError("The public hostname could not be safely resolved") from None
        if not addresses or any(not _public_ip(info[4][0]) for info in addresses):
            raise ValueError("The hostname resolves to a non-public address")
    return target


class AgentReachClient:
    """Read public source content without modifying its URL or publication date.

    Real operations run only when GITHUB_ACTIONS is exactly ``true``. Injecting
    a dispatcher is a trusted offline-test seam and disables live DNS by
    default; a resolver can also be injected for deterministic DNS tests.
    The real path checks DNS before dispatch, but cannot control a hosted
    provider's subsequent DNS or redirects: publish only vetted public sources.
    """

    def __init__(self, timeout: float = 45, max_chars: int = 30000, *,
                 dispatcher: Callable | None = None, resolver: Callable | None = None):
        if isinstance(timeout, bool) or not isinstance(timeout, (float, int)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be finite and positive")
        if isinstance(max_chars, bool) or not isinstance(max_chars, int) or max_chars < 1:
            raise ValueError("max_chars must be a positive integer")
        self.timeout = float(timeout)
        self.max_chars = max_chars
        self._dispatcher = dispatcher
        self._resolver = resolver
        self._injected = dispatcher is not None

    def _prepare(self, channel: str, action: str, target: str) -> tuple[str | None, dict | None]:
        if (channel, action) not in {("web", "read"), ("youtube", "read"),
                                     ("youtube", "subtitle"), ("github", "read")}:
            return None, _error(channel, action, "BAD_INPUT", "Only reviewed public read/subtitle actions are allowed")
        if not self._injected and os.environ.get("GITHUB_ACTIONS") != "true":
            return None, _error(channel, action, "LOCAL_EXECUTION_DISABLED", "Real collection is restricted to GitHub Actions")
        try:
            resolver = self._resolver if self._injected else (self._resolver or socket.getaddrinfo)
            clean = _validate_url(target, resolver)
            host = urlsplit(clean).hostname.lower().rstrip(".")
            if channel == "github" and host not in {"github.com", "www.github.com"}:
                raise ValueError("The GitHub reader requires a github.com URL")
            if channel == "youtube" and host not in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
                raise ValueError("The YouTube reader requires a public YouTube URL")
        except ValueError as exc:
            return None, _error(channel, action, "BAD_INPUT", str(exc))
        return clean, None

    @staticmethod
    def _upstream_dispatch(channel: str, action: str, params: dict, *,
                           timeout: float, only_backend: str) -> dict:
        # Importing these modules does not install anything or open a browser.
        # Refuse existing config rather than reading a user's saved sessions.
        from agent_reach.config import Config
        if os.path.lexists(Config.CONFIG_FILE):
            return _error(channel, action, "UNSAFE_RUNTIME_CONFIG", "A clean CI runtime without saved Agent Reach configuration is required")
        from agent_reach.channels.web import WebChannel
        from agent_reach.channels.youtube import YouTubeChannel
        from agent_reach.channels.github import GitHubChannel
        from agent_reach.runtime.dispatch import run_action
        channels = {"web": WebChannel, "youtube": YouTubeChannel, "github": GitHubChannel}
        return run_action(channels[channel](), action, params, timeout=timeout, only_backend=only_backend)

    def _invoke(self, channel: str, action: str, target: str, backend: str, timeout: float) -> dict:
        try:
            result = (self._dispatcher or self._upstream_dispatch)(
                channel, action, {"target": target}, timeout=max(0.001, timeout), only_backend=backend)
        except ImportError:
            return _error(channel, action, "NEED_SETUP", "The pinned Agent Reach runtime is not installed")
        except (TimeoutError, socket.timeout):
            return _error(channel, action, "TIMEOUT", "The public reader timed out")
        except Exception as exc:
            if _CHALLENGE.search(str(exc)):
                return _error(channel, action, "PLATFORM_BLOCKED", "The platform requires verification or denied automated access")
            # Never echo exceptions containing tokens, URLs or provider payloads.
            return _error(channel, action, "UPSTREAM_BROKEN", "The public reader failed")
        if (not isinstance(result, dict) or result.get("schema_version") != 1
                or not isinstance(result.get("ok"), bool) or not isinstance(result.get("items"), list)
                or not isinstance(result.get("meta"), dict)
                or not isinstance(result.get("meta", {}).get("attempts", []), list)
                or result.get("channel") != channel or result.get("action") != action
                or (result["ok"] and result.get("backend") != backend)
                or (not result["ok"] and (not isinstance(result.get("error"), dict)
                                          or not isinstance(result.get("error", {}).get("code"), str)))):
            return _error(channel, action, "UPSTREAM_BROKEN", "The public reader returned an invalid result envelope")
        result = deepcopy(result)
        if not result["ok"]:
            error = result.get("error") or {}
            if error.get("code") not in _STOP_CODES and _CHALLENGE.search(str(error.get("message") or "")):
                return _error(channel, action, "PLATFORM_BLOCKED", "The platform requires verification or denied automated access")
            return result
        if result.get("error") is not None or not result["items"]:
            return _error(channel, action, "UPSTREAM_BROKEN", "The public reader returned no usable content")
        budget = self.max_chars
        truncated = False
        for item in result["items"]:
            if not isinstance(item, dict):
                return _error(channel, action, "UPSTREAM_BROKEN", "The public reader returned an invalid item")
            # Preserve source/canonical URL and missing publication dates verbatim.
            if item.get("url"):
                try:
                    _validate_url(item["url"])
                except ValueError:
                    return _error(channel, action, "BAD_INPUT", "The public reader returned an unsafe content URL")
            text = item.get("text")
            if text is not None and not isinstance(text, str):
                return _error(channel, action, "UPSTREAM_BROKEN", "The public reader returned non-text content")
            if text:
                item["text"] = text[:budget]
                truncated = truncated or len(text) > budget
                budget = max(0, budget - len(item["text"]))
        if truncated:
            result["meta"]["text_truncated"] = True
        return result

    def action(self, channel: str, action: str, target: str) -> dict:
        """Run an allowlisted action and return the upstream result envelope."""
        if (channel, action) == ("web", "read"):
            return self.read_web(target)
        if (channel, action) == ("github", "read"):
            return self.read_github(target)
        target, failure = self._prepare(channel, action, target)
        if failure is not None:
            return failure
        result = self._invoke(channel, action, target, "yt-dlp", self.timeout)
        if result["ok"]:
            result["meta"]["content_type"] = "video_subtitles" if action == "subtitle" else "video_description"
        return result

    def read_web(self, url: str) -> dict:
        target, failure = self._prepare("web", "read", url)
        if failure is not None:
            return failure
        started = time.monotonic()
        # Explicit backends prevent upstream's automatic fallback from switching
        # providers before this adapter can recognize a challenge/denial result.
        result = self._invoke("web", "read", target, "jina", self.timeout / 2)
        attempts = list(result["meta"].get("attempts") or [])
        code = (result.get("error") or {}).get("code")
        remaining = self.timeout - (time.monotonic() - started)
        if not result["ok"] and code in _WEB_FALLBACK_CODES and remaining > 0:
            result = self._invoke("web", "read", target, "exa", remaining)
            result["meta"]["attempts"] = attempts + list(result["meta"].get("attempts") or [])
        if result["ok"]:
            result["meta"]["content_type"] = "web_article"
        return result

    def read_youtube(self, url: str) -> dict:
        target, failure = self._prepare("youtube", "subtitle", url)
        if failure is not None:
            return failure
        started = time.monotonic()
        result = self._invoke("youtube", "subtitle", target, "yt-dlp", self.timeout * 0.75)
        if result["ok"]:
            result["meta"]["content_type"] = "video_subtitles"
            return result
        code = (result.get("error") or {}).get("code")
        # A missing subtitle is not permission to use a different provider.
        # The same public yt-dlp backend may read the video's own description.
        remaining = self.timeout - (time.monotonic() - started)
        if code != "NOT_FOUND" or remaining <= 0:
            return result
        attempts = list(result["meta"].get("attempts") or [])
        result = self._invoke("youtube", "read", target, "yt-dlp", remaining)
        result["meta"]["attempts"] = attempts + list(result["meta"].get("attempts") or [])
        if result["ok"]:
            result["meta"]["content_type"] = "video_description"
            result["meta"]["subtitle_status"] = "NOT_FOUND"
        return result

    def read_github(self, url: str) -> dict:
        target, failure = self._prepare("github", "read", url)
        if failure is not None:
            return failure
        result = self._invoke("github", "read", target, "github-api", self.timeout)
        if result["ok"]:
            result["meta"]["content_type"] = "repository_or_issue"
        return result
