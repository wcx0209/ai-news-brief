#!/usr/bin/env python3
"""Export a privacy-safe static feed for the Polyemergence frontend."""

import argparse
import json
import os
from datetime import datetime, timezone
from urllib.parse import urlparse

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup


def safe_http_url(value):
    if not value:
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def discover_image(url, timeout=8):
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "Polyemergence/1.0 (+https://polyemergence.com)"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.text[:500000], "html.parser")
        for attrs in (
            {"property": "og:image"},
            {"name": "twitter:image"},
            {"property": "twitter:image"},
        ):
            node = soup.find("meta", attrs=attrs)
            image = safe_http_url(node.get("content") if node else None)
            if image:
                return image
    except Exception:
        return None
    return None


def parse_tags(value):
    if isinstance(value, list):
        return value[:5]
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return parsed[:5] if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return [tag.strip() for tag in str(value).split(",") if tag.strip()][:5]


def iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z") if value else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="web/public/data/latest.json")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--discover-images", type=int, default=12)
    args = parser.parse_args()

    db_url = os.environ.get("INBRIEF_SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("INBRIEF_SUPABASE_DB_URL is required")

    with psycopg2.connect(db_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT a.id, a.url, a.title, a.title_en, a.title_zh,
                       a.summary_en, a.summary_zh, a.long_summary_en, a.long_summary_zh,
                       a.importance_score, a.tags, a.category, a.published_at,
                       a.created_at, rs.name AS source_name
                FROM articles a
                LEFT JOIN rss_sources rs ON rs.id = a.rss_source_id
                WHERE COALESCE(a.published_at, a.created_at) >= NOW() - INTERVAL '14 days'
                ORDER BY a.importance_score DESC, COALESCE(a.published_at, a.created_at) DESC
                LIMIT %s
                """,
                (args.limit,),
            )
            rows = cursor.fetchall()

    items = []
    for index, row in enumerate(rows):
        source_url = safe_http_url(row["url"])
        image_url = discover_image(source_url) if source_url and index < args.discover_images else None
        items.append({
            "id": row["id"],
            "url": source_url,
            "source": row["source_name"] or "Unknown source",
            "category": row["category"] or "news",
            "importance": int(row["importance_score"] or 0),
            "published_at": iso(row["published_at"] or row["created_at"]),
            "image_url": image_url,
            "tags": parse_tags(row["tags"]),
            "en": {
                "title": row["title_en"] or row["title"],
                "summary": row["summary_en"] or "",
                "long_summary": row["long_summary_en"] or "",
            },
            "zh": {
                "title": row["title_zh"] or row["title"],
                "summary": row["summary_zh"] or "",
                "long_summary": row["long_summary_zh"] or "",
            },
        })

    payload = {
        "brand": "Polyemergence",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(items),
        "items": items,
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    print(f"Exported {len(items)} articles to {args.output}")


if __name__ == "__main__":
    main()
