#!/usr/bin/env python3
"""Audit collector routes offline, or probe public readers in GitHub Actions.

This check does not import the application pipeline, access its database, call
an LLM, install software, authenticate, or write any source/article records.
RSS discovery is Polyemergence's transport, not an Agent Reach capability.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from importlib import metadata
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qsl, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from agent_reach_client import AGENT_REACH_COMMIT, AGENT_REACH_VERSION
from rss_fetcher import OFFICIAL_HTML_INDEX_RULES
from source_catalog import load_seed_catalog


_TOKEN = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_PRIVATE_QUERY = re.compile(r"token|secret|password|cookie|auth|signature|credential|api.?key|session", re.I)
_TRACKING_QUERY = {"fbclid", "gclid", "ref", "source"}


def _label(value, default="UNKNOWN"):
    return value if isinstance(value, str) and _TOKEN.fullmatch(value) else default


def _report_url(value):
    """Do not copy credentials, signed links, or arbitrary provider messages."""
    if not isinstance(value, str) or len(value) > 8192:
        return None
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.username is not None or parsed.password is not None
                or any(_PRIVATE_QUERY.search(key) or key.lower().startswith(("x-amz-", "x-goog-"))
                       for key, _ in parse_qsl(parsed.query, keep_blank_values=True))):
            return None
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return None


def _same_url(original, read):
    def normalized(value):
        value = _report_url(value)
        if not value:
            return None
        parsed = urlsplit(value)
        host = parsed.hostname.lower().removeprefix("www.")
        path = parsed.path.rstrip("/")
        if host == "github.com":
            path = path.lower()
        query = sorted((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                       if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_QUERY)
        return host, path, tuple(query)
    return normalized(original) is not None and normalized(original) == normalized(read)


def _source_date(value):
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


def source_manifest(catalog_path=None):
    rows = load_seed_catalog(catalog_path or ROOT / "scripts" / "bootstrap_sources.py")
    sources = []
    for url, name, description, category, importance in rows:
        parsed = urlsplit(url)
        host, path = (parsed.hostname or "").lower(), parsed.path.rstrip("/")
        adapter = None
        if url.rstrip("/") in OFFICIAL_HTML_INDEX_RULES:
            adapter = "official_html"
        elif host == "huggingface.co" and path == "/api/daily_papers":
            adapter = "huggingface_json"
        elif host == "seed.bytedance.com":
            adapter = "bytedance_seed"
        elif host in ("tencent.com", "www.tencent.com") and path == "/zh-cn/newsroom":
            adapter = "tencent_newsroom"
        elif host in ("github.com", "www.github.com") and re.fullmatch(r"/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/releases\.atom", path):
            adapter = "github_releases_json"
        discovery = "publisher_adapter" if adapter else "public_rss"
        if host.endswith("youtube.com") or host == "youtu.be":
            channel = "youtube"
        else:
            # Release Atom entries are article URLs, not GitHub repo reads.
            channel = "web"
        sources.append({
            "name": name, "url": _report_url(url), "category": category,
            "discovery_backend": discovery, "publisher_adapter": adapter,
            "article_reader": "agent_reach", "article_channel": channel,
            "publisher_content_reuse": adapter == "official_html",
            "route_verified_live": False,
        })
    return {
        "source_count": len(sources),
        "route_counts": dict(Counter(source["discovery_backend"] for source in sources)),
        "native_agent_reach_rss": False,
        "social_channels": {"reddit": "not_configured", "x": "not_configured"},
        "sources": sources,
        "note": "Routing coverage is not proof that every source is currently reachable or fresh.",
    }


def installed_runtime():
    """Verify the installed archive/VCS provenance without importing its code."""
    expected = {"version": AGENT_REACH_VERSION, "commit": AGENT_REACH_COMMIT,
                "repository": "https://github.com/Panniantong/Agent-Reach"}
    try:
        distribution = metadata.distribution("agent-reach")
        actual_version = distribution.version
        provenance = json.loads(distribution.read_text("direct_url.json") or "{}")
        url = provenance.get("url", "")
        vcs_commit = (provenance.get("vcs_info") or {}).get("commit_id")
        archive_url = f"{expected['repository']}/archive/{AGENT_REACH_COMMIT}.zip"
        archive_matches = url == archive_url
        vcs_matches = (url.rstrip("/").removesuffix(".git") == expected["repository"]
                       and vcs_commit == AGENT_REACH_COMMIT)
        verified = actual_version == AGENT_REACH_VERSION and (archive_matches or vcs_matches)
        return {"expected": expected, "installed_version": _label(actual_version),
                "pinned_revision_verified": verified,
                "provenance": "pinned_archive" if archive_matches else "pinned_vcs" if vcs_matches else "unverified",
                "status": "ok" if verified else "failed"}
    except (metadata.PackageNotFoundError, ValueError, TypeError, AttributeError):
        return {"expected": expected, "installed_version": None,
                "pinned_revision_verified": False, "provenance": "unavailable", "status": "failed"}


def summarize_read(name, original_url, result, *, expected_channel, allowed_backends):
    """Store evidence of actual actions, never full article/provider payloads."""
    if not isinstance(result, dict):
        result = {}
    meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
    attempts = []
    for attempt in (meta.get("attempts") or [])[:10]:
        if isinstance(attempt, dict):
            attempts.append({"backend": _label(attempt.get("backend")),
                             "result": _label(attempt.get("result")),
                             "skipped": bool(attempt.get("skipped"))})
    samples = []
    for item in (result.get("items") or [])[:3]:
        if not isinstance(item, dict):
            continue
        item_url = _report_url(item.get("url"))
        samples.append({"read_url": item_url, "matches_original_url": _same_url(original_url, item_url),
                        "reader_published_at": _source_date(item.get("published_at")),
                        "text_chars": len(item.get("text") or "") if isinstance(item.get("text"), str) else 0})
    backend = _label(result.get("backend"), None)
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    ok = (result.get("ok") is True and result.get("channel") == expected_channel
          and backend in allowed_backends and any(item["matches_original_url"] and item["text_chars"] >= 80 for item in samples))
    return {"name": name, "original_url": _report_url(original_url),
            "status": "ok" if ok else "failed", "channel": _label(result.get("channel"), expected_channel),
            "action": _label(result.get("action"), None), "backend": backend,
            "content_type": _label(meta.get("content_type"), None), "attempts": attempts,
            "error_code": None if ok else _label(error.get("code"), "UNUSABLE_RESULT"),
            "samples": samples, "legacy_fallback_used": False,
            "date_policy": "Reader metadata is evidence only; never replace an existing source publication date."}


def _discovery_probe(name, source, collector):
    try:
        result = collector.parse_feed(source)
    except Exception:
        result = {"entries": [], "error": "SOURCE_DISCOVERY_FAILED"}
    entries = [entry for entry in result.get("entries", []) if isinstance(entry, dict)]
    sample = [{"original_url": _report_url(entry.get("link")),
               "original_published_at": _source_date(entry.get("published_at")),
               "date_basis": _label(entry.get("date_basis"), "unknown"),
               "discovery_backend": _label(entry.get("discovery_backend"), "UNKNOWN"),
               "discovery_subtype": _label(entry.get("discovery_subtype"), None)}
              for entry in entries[:3]]
    ok = not result.get("error") and any(item["original_url"] and item["original_published_at"] for item in sample)
    return {"name": name, "source_url": _report_url(source["url"]),
            "status": "ok" if ok else "failed", "entry_count": len(entries),
            "error_code": None if ok else _label(result.get("error"), "NO_DATED_ENTRY"),
            "samples": sample, "native_agent_reach_rss": False,
            "legacy_fallback_used": False}, entries


def _archived_youtube_canary():
    """Already-public URL only; no database/history mutation or fresh scraping."""
    try:
        corpus = json.loads((ROOT / 'web/public/data/articles.json').read_text(encoding='utf-8'))
        for item in corpus.get('items', []):
            url = _report_url(item.get('url'))
            parsed = urlsplit(url or '')
            if parsed.hostname == 'www.youtube.com' and parsed.path == '/watch' and parsed.query.startswith('v='):
                return {'link': url, 'published_at': item.get('published_at'),
                        'source': item.get('source'), 'canary_basis': 'existing_public_archive'}
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return None


def probe_readers(manifest, *, collector=None, client=None):
    """Explicit GHA guard also protects programmatic callers and test seams."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Live collector checks must run in GitHub Actions")
    if client is None:
        from agent_reach_client import AgentReachClient
        client = AgentReachClient(timeout=40, max_chars=12000)
    if collector is None:
        from news_collector import AgentReachCollector
        collector = AgentReachCollector([], client=client, config={"network_timeout": 25})
    probes = []
    try:
        source = next(source for source in manifest["sources"] if source["name"] == "OpenAI News")
        rss, _ = _discovery_probe("official_rss", source, collector)
        rss["required"] = False
        probes.append(rss)
        release_source = next(source for source in manifest["sources"] if source["name"] == "Ollama Releases")
        release_probe, release_entries = _discovery_probe("official_github_release", release_source, collector)
        release_probe["required"] = True
        release_probe["source_name"] = release_source["name"]
        release_probe["published_release_entries"] = sum(
            bool(_source_date(entry.get("published_at")))
            and entry.get("date_basis") == "source_published"
            and entry.get("discovery_subtype") == "github_releases_json"
            and bool(re.fullmatch(r"https://github\.com/ollama/ollama/releases/tag/[^\s]+", entry.get("link") or ""))
            for entry in release_entries
        )
        if not release_probe["published_release_entries"]:
            release_probe.update(status="failed", error_code="NO_DATED_OFFICIAL_RELEASE")
        probes.append(release_probe)
        for name, url, channel, backends, method in (
            ("official_web", "https://www.anthropic.com/news", "web", {"jina", "exa"}, client.read_web),
            ("github_repository", "https://github.com/Panniantong/Agent-Reach", "github", {"github-api"}, client.read_github),
        ):
            try:
                result = method(url)
            except Exception:
                result = {"error": {"code": "PROBE_ACTION_FAILED"}}
            probe = summarize_read(name, url, result, expected_channel=channel, allowed_backends=backends)
            probe["required"] = True
            if channel == "github":
                probe["date_policy"] = "Repository created_at is not a news publication date and is not used for freshness."
            probes.append(probe)
        trending_url = "https://github.com/trending?since=weekly"
        try:
            from reach_github import parse_trending_markdown
            trending_result = client.read_web(trending_url)
            trending = summarize_read("github_trending", trending_url, trending_result,
                                      expected_channel="web", allowed_backends={"jina", "exa"})
            matching = [item for item in trending_result.get("items", [])
                        if _same_url(trending_url, item.get("url"))]
            candidates = parse_trending_markdown(matching[0].get("text")) if matching else []
            trending["parsed_repositories"] = len(candidates)
            trending["sample_repository_urls"] = [_report_url(item["url"]) for item in candidates[:3]]
            if trending["status"] == "ok" and not candidates:
                trending.update(status="failed", error_code="NO_TRENDING_REPOSITORIES_PARSED")
        except Exception:
            trending = {"name": "github_trending", "status": "failed", "error_code": "TRENDING_PROBE_FAILED",
                        "legacy_fallback_used": False, "parsed_repositories": 0}
        trending["required"] = False
        probes.append(trending)
        youtube_source = next(source for source in manifest["sources"] if source["name"] == "Dwarkesh Patel")
        youtube_discovery, entries = _discovery_probe("youtube_rss", youtube_source, collector)
        youtube_discovery["required"] = False
        probes.append(youtube_discovery)
        entry = next((entry for entry in entries if (urlsplit(entry.get("link") or "").hostname or "").lower()
                      in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}), None)
        # A broken channel feed is a separate finding, not a reason to leave the
        # runtime action untested. Use one URL already in our public archive.
        entry = entry or _archived_youtube_canary()
        if entry:
            original_date = entry.get("published_at")
            try:
                result = client.read_youtube(entry["link"])
            except Exception:
                result = {"error": {"code": "PROBE_ACTION_FAILED"}}
            youtube = summarize_read("youtube_interview", entry["link"], result,
                                     expected_channel="youtube", allowed_backends={"yt-dlp"})
            youtube["original_published_at"] = _source_date(original_date)
            youtube["original_date_unchanged"] = entry.get("published_at") == original_date
            youtube["source_channel"] = entry.get('source') or youtube_source["name"]
            youtube["canary_basis"] = entry.get('canary_basis', 'current_channel_rss')
        else:
            youtube = {"name": "youtube_interview", "status": "not_tested", "error_code": "NO_PUBLIC_VIDEO_DISCOVERED",
                       "source_channel": youtube_source["name"], "legacy_fallback_used": False}
        youtube["required"] = False
        youtube["blocked_access_policy"] = "Stop on challenge, login, or rate-limit; no cookies, browser, provider hopping, or transcription."
        probes.append(youtube)
    finally:
        collector.close()
    return probes


def build_report(*, probe=False, manifest=None, runtime=None, reader=None):
    if probe and os.environ.get("GITHUB_ACTIONS") != "true":
        raise RuntimeError("Live collector checks must run in GitHub Actions")
    manifest = source_manifest() if manifest is None else manifest
    report = {"schema_version": 1, "checked_at": datetime.now(timezone.utc).isoformat(),
              "mode": "live_probe" if probe else "offline_manifest", "collector_backend": "agent_reach",
              "upstream": {"repository": "https://github.com/Panniantong/Agent-Reach",
                           "expected_version": AGENT_REACH_VERSION, "expected_commit": AGENT_REACH_COMMIT},
              "manifest": manifest, "probes": [], "legacy_fallback_enabled": False,
              "effects": {"database_writes": False, "llm_calls": False, "login_or_cookies": False,
                          "software_installation": False, "article_ingestion": False}}
    if not probe:
        report["status"] = "manifest_only"
        report["live_migration_verified"] = False
        return report
    report["runner"] = "GitHub Actions"
    report["runtime"] = (runtime or installed_runtime)()
    if report["runtime"].get("pinned_revision_verified"):
        report["probes"] = (reader or probe_readers)(manifest)
    required = [item for item in report["probes"] if item.get("required")]
    verified = (report["runtime"].get("pinned_revision_verified") is True
                and {item["name"] for item in required} == {"official_web", "github_repository", "official_github_release"}
                and all(item["status"] == "ok" for item in required))
    report["live_migration_verified"] = verified
    report["status"] = "ok" if verified else "failed"
    report["advisories"] = [item["name"] for item in report["probes"]
                            if not item.get("required") and item["status"] != "ok"]
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--manifest-only", action="store_true", help="No live requests; audit declared source routing")
    mode.add_argument("--probe", action="store_true", help="Public live readers; GitHub Actions only")
    parser.add_argument("--output", default="output/agent-reach-check.json")
    args = parser.parse_args(argv)
    if args.probe and os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("Run --probe in GitHub Actions, not on a local computer")
    report = build_report(probe=args.probe)
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Collector check: {report['status']}; {report['manifest']['source_count']} configured source routes; "
          f"live verification: {report['live_migration_verified']}")
    for item in report["probes"]:
        print(f"{item['name']}: {item['status']} ({item.get('backend') or item.get('error_code') or 'RSS discovery'})")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(f"## Agent Reach collector check\n\nStatus: {report['status']}. "
                          f"{report['manifest']['source_count']} declared routes; RSS is Polyemergence discovery. "
                          "No DB writes, LLM calls, logins, or ingestion.\n\n")
            for item in report["probes"]:
                summary.write(f"- {item['name']}: {item['status']} "
                              f"({item.get('backend') or item.get('error_code') or 'RSS discovery'})\n")
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
