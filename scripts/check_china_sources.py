#!/usr/bin/env python3
"""Cloud-only source health check. No article ingestion, database or LLM calls."""

import argparse
import concurrent.futures
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from rss_fetcher import OFFICIAL_HTML_INDEX_RULES, RSSFetcher
from source_catalog import china_sources
from relevance_filter import passes_source_ai_filter


def check_source(source):
    fetcher = RSSFetcher([])
    # Match the deployed collector's timeout; a stricter probe would falsely
    # reject slower institutional publishers that the real collector can read.
    try:
        rule = OFFICIAL_HTML_INDEX_RULES.get(source["url"].rstrip("/"))
        result = fetcher._fetch_official_html_index(source, {
            **rule, "max_index_links": 4, "max_articles": 3,
        }) if rule else fetcher.parse_feed(source)
        entries = result.get("entries", [])
        dated = [entry for entry in entries if entry.get("title") and entry.get("published_at")]
        readable = [entry for entry in dated if not source.get("html") or len(entry.get("official_content", "")) >= 120]
        return {
            "name": source["name"], "url": source["url"],
            "domain": source["category"], "kind": source["kind"], "region": source["region"],
            "status": "ok" if readable and not result.get("error") else "failed",
            "dated_entries": len(dated), "readable_entries": len(readable),
            "relevance_passed_entries": sum(passes_source_ai_filter(source["name"], entry["title"]) for entry in readable),
            "error": result.get("error") or ("No readable article body" if dated and not readable else None),
            "latest_published_at": max((entry["published_at"] for entry in dated), default=None),
            "sample": [{"title": entry["title"], "url": entry["link"], "published_at": entry["published_at"],
                        "passes_relevance": passes_source_ai_filter(source["name"], entry["title"])} for entry in dated[:3]],
        }
    except Exception as exc:
        return {"name": source["name"], "url": source["url"], "domain": source["category"],
                "kind": source["kind"], "region": source["region"], "status": "failed", "error": str(exc)}
    finally:
        fetcher.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    # Keep the reader's computer out of collection and live source probing.
    if os.environ.get("GITHUB_ACTIONS") != "true":
        parser.error("Run this live check in GitHub Actions, not on a local computer")
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        for result in executor.map(check_source, china_sources()):
            results.append(result)
            print(f'{result["status"]}: {result["name"]} ({result.get("dated_entries", 0)} dated entries)', flush=True)
    payload = {"checked_at": datetime.now(timezone.utc).isoformat(), "runner": "GitHub Actions",
               "counts": dict(Counter(item["status"] for item in results)), "sources": results}
    target = Path(args.output)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write("## China specialist source health\n\nNo news ingestion or LLM calls. A dated historical item proves parsing, not daily freshness.\n\n")
            summary.write("| Source | Field | Status | Dated entries | Relevant titles | Latest source date |\n| --- | --- | --- | ---: | ---: | --- |\n")
            for item in results:
                summary.write(f'| {item["name"]} | {item["domain"]} | {item["status"]} | {item.get("dated_entries", 0)} | {item.get("relevance_passed_entries", 0)} | {item.get("latest_published_at") or "—"} |\n')
    return 1 if any(item["status"] != "ok" for item in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
