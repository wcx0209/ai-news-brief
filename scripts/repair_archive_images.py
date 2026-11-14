#!/usr/bin/env python3
"""Repair a bounded batch of already-public source images in cloud CI only.

No database, new news collection, LLM, image proxy or binary media storage.
Article text, selection, publication times and canonical links are untouched.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from source_images import discover_images, normalize_source_url
from export_public_feed import merge_image_fields


def parsed_date(value):
    try:
        value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def repair_payload(payload, limit=50, workers=4, now=None, discover=None, current_items=None):
    discover = discover or discover_images
    now = now or datetime.now(timezone.utc)
    output = deepcopy(payload)
    latest = {str(item.get("id")): item for item in (current_items or []) if isinstance(item, dict)}
    queued = []
    for index, item in enumerate(output.get("items", [])):
        url = item.get("url")
        source = normalize_source_url(url)
        if not source:
            continue
        current = latest.get(str(item.get("id")))
        if current and source == normalize_source_url(current.get("url")):
            item.update(merge_image_fields(current, item))
        dates = [parsed_date(item.get(key)) for key in ("published_at", "source_published_at", "site_published_at")]
        if any(value and value > now for value in dates):
            continue
        checked = parsed_date(item.get("image_checked_at"))
        # Recheck failures weekly; don't hit the same source twice every day.
        if (checked and now - timedelta(days=7) <= checked <= now
                and item.get("image_status") in {"verified", "unavailable"}
                and normalize_source_url(item.get("image_source_url")) == source):
            continue
        queued.append((index, item))
    # First fix existing broken/low-res selections, then backfill missing art.
    queued.sort(key=lambda entry: (not bool(entry[1].get("image_url")), entry[0]))
    queued = queued[:max(0, min(100, int(limit)))]
    successes = 0
    if queued:
        with ThreadPoolExecutor(max_workers=max(1, min(6, int(workers)))) as executor:
            futures = {executor.submit(discover, item["url"]): index for index, item in queued}
            for future in as_completed(futures):
                index = futures[future]
                item = output["items"][index]
                try:
                    urls = list(dict.fromkeys(future.result() or []))[:3]
                except Exception:
                    urls = []
                item["image_checked_at"] = now.isoformat().replace("+00:00", "Z")
                item["image_source_url"] = normalize_source_url(item["url"])
                item["image_status"] = "verified" if urls else "unavailable"
                if urls:
                    item["image_url"] = urls[0]
                    item["image_candidates"] = urls
                    successes += 1
                # A transient source error must not erase previously published
                # image URLs. Browser-side bounded recovery still applies.
    return output, {"checked": len(queued), "verified": successes}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="web/public/data/articles.json")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--latest", default="web/public/data/latest.json")
    args = parser.parse_args()
    path = Path(args.input)
    if not path.is_file():
        print("No previous public archive; image repair skipped")
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    latest_path = Path(args.latest)
    current_items = json.loads(latest_path.read_text(encoding="utf-8")).get("items", []) if latest_path.is_file() else []
    repaired, stats = repair_payload(payload, args.limit, args.workers, current_items=current_items)
    if repaired != payload:
        path.write_text(json.dumps(repaired, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Source image repair: {stats['checked']} checked, {stats['verified']} verified; no LLM or database calls")


if __name__ == "__main__":
    main()
