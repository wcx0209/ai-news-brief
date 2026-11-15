"""Cloud collector with explicit RSS discovery and Agent Reach article reads.

RSS/XML and maintained publisher adapters are discovery transports, not a claim
that Agent Reach itself implements every source. Article reads use its real
channel client; this module never falls back to the legacy article reader.
"""

from calendar import timegm
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import os
import re
import time
from urllib.parse import unquote, urljoin, urlparse

import feedparser

from config_loader import ConfigLoader
from rss_fetcher import OFFICIAL_HTML_INDEX_RULES
from source_images import normalize_source_url


def _public_url(value):
    """Validate configured public HTTP targets without altering query IDs."""
    return bool(normalize_source_url(value))


def _date(value=None, parsed=None):
    """UTC publication metadata only; a missing date never becomes now()."""
    try:
        if parsed:
            return datetime.fromtimestamp(timegm(parsed), timezone.utc).isoformat()
        if not value:
            return None
        if isinstance(value, datetime):
            result = value
        else:
            try:
                result = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
            except ValueError:
                result = parsedate_to_datetime(str(value))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _host_matches(host, domain):
    return host == domain or host.endswith("." + domain)


def github_release_repository(url):
    """Identify only configured, canonical GitHub release Atom endpoints."""
    if not _public_url(url):
        return None
    parsed = urlparse(url)
    if (parsed.scheme != "https" or parsed.netloc != "github.com"
            or parsed.query or parsed.fragment):
        return None
    match = re.fullmatch(r"/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/releases\.atom", parsed.path)
    if not match or any(part in (".", "..") for part in match.groups()):
        return None
    return match.groups()


class AgentReachCollector:
    """Drop-in discovery interface; ``client`` exposes the real Reach actions.

    The optional injected transport/adapters/client are trusted test seams, not
    automatic legacy fallbacks. Default network execution requires Actions.
    """

    backend = "agent_reach"

    def __init__(self, feeds_config=None, *, client=None, publisher_adapters=None,
                 rss_transport=None, config=None):
        self.feeds = feeds_config or []
        fetching = (config if config is not None else ConfigLoader.get_instance().get("fetching", {}))
        self.timeout = max(1, min(float(fetching.get("network_timeout", 60)), 120))
        self.max_chars = max(1000, min(int(fetching.get("max_input_chars", 30000)), 100000))
        self.max_feed_bytes = max(1024, min(int(fetching.get("max_feed_bytes", 5 * 1024 * 1024)), 10 * 1024 * 1024))
        self.max_feed_entries = max(1, min(int(fetching.get("max_feed_entries", 200)), 500))
        self._client = client
        self._publisher_adapters = publisher_adapters
        self._publisher_adapters_injected = publisher_adapters is not None
        self._rss_transport = rss_transport

    @property
    def client(self):
        if self._client is None:
            from agent_reach_client import AgentReachClient
            self._client = AgentReachClient(timeout=self.timeout, max_chars=self.max_chars)
        return self._client

    @staticmethod
    def _require_cloud():
        if os.environ.get("GITHUB_ACTIONS") != "true":
            raise RuntimeError("collector_cloud_only")

    def _adapters(self):
        if not self._publisher_adapters_injected:
            self._require_cloud()
        if self._publisher_adapters is None:
            from rss_fetcher import PublisherSourceAdapters
            self._publisher_adapters = PublisherSourceAdapters(self.feeds)
        return self._publisher_adapters

    def _fetch_rss(self, url, *, json_endpoint=False):
        if json_endpoint:
            endpoint = urlparse(url)
            if (endpoint.scheme != "https" or endpoint.netloc != "api.github.com"
                    or endpoint.query != "per_page=20" or endpoint.fragment
                    or not re.fullmatch(r"/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases", endpoint.path)):
                raise ValueError("github_releases_invalid_endpoint")
        if self._rss_transport is not None:
            return self._rss_transport(url)
        self._require_cloud()
        import requests
        from source_images import _pinned_adapter, _resolve_public

        # Manual redirects keep every target public. Stream decoded bytes so a
        # huge feed or compressed response cannot bypass the input-size bound.
        headers = {"User-Agent": "Polyemergence/1.0 (+https://polyemergence.com/)",
                   "Accept": "application/vnd.github+json" if json_endpoint else "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9"}
        if json_endpoint:
            headers["X-GitHub-Api-Version"] = "2022-11-28"
        with requests.Session() as session:
            session.trust_env = False
            target = normalize_source_url(url)
            deadline = time.monotonic() + self.timeout
            for _ in range(4):
                target = normalize_source_url(target)
                if not target:
                    raise ValueError("rss_invalid_redirect")
                if json_endpoint and target != url:
                    raise ValueError("github_releases_invalid_redirect")
                addresses = _resolve_public(target)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("rss_timeout")
                parsed = urlparse(target)
                session.mount(parsed.scheme + "://", _pinned_adapter(
                    parsed.hostname, addresses[0], parsed.port or (443 if parsed.scheme == "https" else 80)))
                session.cookies.clear()
                request_headers = {**headers, "Host": parsed.netloc}
                with session.get(target, headers=request_headers, timeout=(min(5, remaining), remaining),
                                 stream=True, allow_redirects=False, verify=True) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("Location") or response.headers.get("location")
                        if not location:
                            raise ValueError("rss_invalid_redirect")
                        target = urljoin(target, location)
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
                    allowed_types = ("application/json", "application/vnd.github+json") if json_endpoint else (
                        "application/rss+xml", "application/atom+xml", "application/rdf+xml",
                        "application/xml", "text/xml", "text/plain", "application/octet-stream",
                    )
                    if content_type and content_type not in allowed_types:
                        raise ValueError("rss_response_not_xml")
                    declared_size = response.headers.get("Content-Length", "")
                    if str(declared_size).isdigit() and int(declared_size) > self.max_feed_bytes:
                        raise ValueError("rss_too_large")
                    chunks, total = [], 0
                    for chunk in response.iter_content(chunk_size=16384):
                        total += len(chunk)
                        if total > self.max_feed_bytes:
                            raise ValueError("rss_too_large")
                        if time.monotonic() > deadline:
                            raise TimeoutError("rss_timeout")
                        chunks.append(chunk)
                    return b"".join(chunks)
        raise ValueError("rss_redirect_limit")

    def _github_releases(self, source, repository):
        """Read real release publication dates, never Atom updated/repo created."""
        owner, repo = repository
        endpoint = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=20"
        content = self._fetch_rss(endpoint, json_endpoint=True)
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, bytes) or len(content) > self.max_feed_bytes:
            raise ValueError("rss_too_large")
        payload = json.loads(content)
        if not isinstance(payload, list):
            raise ValueError("github_releases_invalid_response")
        entries, seen = [], set()
        prefix = f"/{owner}/{repo}/releases/tag/".casefold()
        for release in payload[:20]:
            if not isinstance(release, dict) or release.get("draft") is not False:
                continue
            published = _date(release.get("published_at"))
            link = release.get("html_url") or ""
            if not published or not _public_url(link):
                continue
            parsed = urlparse(link)
            if (parsed.scheme != "https" or parsed.netloc != "github.com" or parsed.query or parsed.fragment
                    or not parsed.path.casefold().startswith(prefix)
                    or len(parsed.path) <= len(prefix) or link in seen
                    or any(part in (".", "..") for part in unquote(parsed.path).split("/"))):
                continue
            title = release.get("name") or release.get("tag_name")
            if not isinstance(title, str) or not title.strip():
                continue
            seen.add(link)
            item = self._decorate({"title": title.strip(), "link": link,
                                   "summary": release.get("body") or "", "published_at": published,
                                   "updated_at": _date(release.get("updated_at")),
                                   "is_github_release": True, "orig_entry": release}, source, "publisher_adapter")
            item["discovery_subtype"] = "github_releases_json"
            entries.append(item)
        entries.sort(key=lambda item: item["published_at"], reverse=True)
        return {"entries": entries, "error": None if entries else "github_releases_no_dated_entries",
                "feed_config": source}

    def _decorate(self, entry, source, discovery_backend):
        result = dict(entry)
        result.update({"source": source.get("name", ""), "source_id": source.get("id"),
                       "source_url": source["url"], "source_description": source.get("description", ""),
                       "collector_backend": self.backend, "discovery_backend": discovery_backend})
        result["published_at"] = _date(result.get("published_at"))
        result["date_basis"] = "source_published" if result["published_at"] else "unknown"
        if result.get("updated_at"):
            result["updated_at"] = _date(result["updated_at"])
        return result

    def parse_rss(self, source, content):
        """Normalize supplied RSS/Atom bytes offline; never fetch this input."""
        if isinstance(content, str):
            content = content.encode("utf-8")
        if not isinstance(content, bytes) or len(content) > self.max_feed_bytes:
            return {"entries": [], "error": "rss_too_large" if isinstance(content, bytes) else "rss_invalid_content", "feed_config": source}
        if not _public_url(source.get("url")):
            return {"entries": [], "error": "rss_invalid_url", "feed_config": source}
        parsed = feedparser.parse(content)
        source_host = (urlparse(source["url"]).hostname or "").lower()
        entries = []
        for raw in parsed.entries[:self.max_feed_entries]:
            fields = dict(raw)  # Avoid FeedParserDict compatibility date aliases.
            title = (raw.get("title") or "").strip()
            link = urljoin(source["url"], (raw.get("link") or "").strip())
            if not title or not raw.get("link") or not _public_url(link):
                continue
            if _host_matches(source_host, "theverge.com") and not any(
                (tag.get("term") or "").strip().upper() == "AI" for tag in raw.get("tags", [])
            ):
                continue
            content_parts = raw.get("content") or []
            summary = ((content_parts[0].get("value") or "") if content_parts else "")
            summary = summary or raw.get("summary") or raw.get("description") or ""
            item = {"title": title, "link": link, "summary": summary,
                    "published_at": _date(fields.get("published"), fields.get("published_parsed")),
                    "updated_at": _date(fields.get("updated"), fields.get("updated_parsed")),
                    "orig_entry": raw}
            link_host = (urlparse(link).hostname or "").lower()
            if source_host == "news.ycombinator.com" or source_host == "hnrss.org":
                item["is_hackernews"] = True
                item["comments_url"] = raw.get("comments") or ""
            if _host_matches(source_host, "reddit.com") or _host_matches(link_host, "reddit.com"):
                item["is_reddit"] = True
            if (_host_matches(source_host, "youtube.com") or source_host == "youtu.be"
                    or _host_matches(link_host, "youtube.com") or link_host == "youtu.be"):
                item["is_youtube"] = True
            if any(_host_matches(link_host, domain) for domain in ("twitter.com", "x.com")):
                item["is_twitter"] = True
            entries.append(self._decorate(item, source, "public_rss"))
        return {"entries": entries, "error": "rss_parse_error" if parsed.bozo and not entries else None,
                "feed_config": source}

    def parse_feed(self, source):
        """Discover a source without invoking ``RSSFetcher.parse_feed``."""
        url = source.get("url", "")
        if not _public_url(url):
            return {"entries": [], "error": "rss_invalid_url", "feed_config": source}
        host = (urlparse(url).hostname or "").lower()
        path = urlparse(url).path.rstrip("/")
        rule = OFFICIAL_HTML_INDEX_RULES.get(url.rstrip("/"))
        method = None
        repository = github_release_repository(url)
        if host == "huggingface.co" and path == "/api/daily_papers":
            method = "_fetch_hf_daily_papers"
        elif host == "seed.bytedance.com":
            method = "_fetch_bytedance_seed"
        elif host in ("tencent.com", "www.tencent.com") and path == "/zh-cn/newsroom":
            method = "_fetch_tencent_newsroom"
        try:
            if repository:
                return self._github_releases(source, repository)
            if rule or method:
                adapters = self._adapters()
                result = (adapters._fetch_official_html_index(source, {**rule, "browser_fallback": False}) if rule
                          else getattr(adapters, method)(source))
                return {**result, "entries": [self._decorate(entry, source, "publisher_adapter")
                                              for entry in result.get("entries", [])], "feed_config": source}
            return self.parse_rss(source, self._fetch_rss(url))
        except Exception as exc:
            code = str(exc) if str(exc) in ("collector_cloud_only", "rss_too_large", "rss_invalid_redirect", "rss_redirect_limit", "rss_timeout", "rss_response_not_xml", "github_releases_invalid_endpoint", "github_releases_invalid_redirect", "github_releases_invalid_response") else "source_discovery_failed"
            status = getattr(getattr(exc, "response", None), "status_code", None)
            if isinstance(status, int):
                code = {401: "rss_unauthorized", 403: "rss_forbidden", 429: "rss_rate_limited"}.get(status, f"rss_http_{status}")
            return {"entries": [], "error": code, "error_type": type(exc).__name__, "feed_config": source}

    def read_entry(self, entry):
        """Return the Reach envelope without overwriting the source date."""
        url = entry.get("link") or entry.get("url") or ""
        if not _public_url(url):
            return {"schema_version": 1, "ok": False, "channel": "web", "action": "read",
                    "backend": self.backend, "items": [], "meta": {},
                    "error": {"code": "INVALID_URL", "message": "A public HTTP article URL is required"}}
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if _host_matches(host, "youtube.com") or host == "youtu.be":
            return self.client.read_youtube(url)
        parts = [part for part in parsed.path.split("/") if part]
        if host in ("github.com", "www.github.com") and len(parts) == 2 and all(
            re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in parts
        ):
            return self.client.read_github(url)
        return self.client.read_web(url)

    def close(self):
        for component in (self._publisher_adapters, self._client):
            close = getattr(component, "close", None)
            if callable(close):
                close()


def get_news_collector(feeds_config=None, *, backend=None, config=None, **kwargs):
    """Default to Reach; legacy is an explicit rollback, never a fallback."""
    settings = config if config is not None else ConfigLoader.get_instance().get("collector", {})
    selected = backend if backend is not None else settings.get("backend", "agent_reach")
    if selected == "agent_reach":
        return AgentReachCollector(feeds_config, **kwargs)
    if selected == "legacy":
        from rss_fetcher import RSSFetcher
        result = RSSFetcher(feeds_config or [])
        result.backend = "legacy"
        return result
    raise ValueError(f"Unsupported collector backend: {selected!r}")
