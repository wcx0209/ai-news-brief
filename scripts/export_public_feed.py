#!/usr/bin/env python3
"""Export a privacy-safe static feed for the Polyemergence frontend."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import re
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import psycopg2
import psycopg2.extras
import requests
from bs4 import BeautifulSoup


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from relevance_filter import passes_source_ai_filter
from editorial_domains import category_ids, infer_domain, match_category


TOPIC_CATEGORIES = set(category_ids())


def safe_http_url(value):
    if not value:
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def youtube_thumbnail(url):
    """Return YouTube's reliable static thumbnail without using the Data API."""
    if not url:
        return None
    parsed = urlparse(url)
    video_id = None
    if parsed.netloc.lower().endswith("youtu.be"):
        video_id = parsed.path.strip("/").split("/")[0]
    elif "youtube.com" in parsed.netloc.lower():
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/")):
            video_id = parsed.path.strip("/").split("/")[1]
    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
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


def normalize_category(value, tags=None, title="", source=""):
    category = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if category in TOPIC_CATEGORIES:
        return category
    if category == "opensource":
        return "open_source"

    haystack = " ".join([title or "", source or "", " ".join(parse_tags(tags))]).lower()
    matched = match_category(haystack)
    if matched:
        return matched
    if re.search(r"interview|podcast|conversation|访谈|对谈|播客", haystack):
        return "interviews"
    if re.search(r"policy|regulat|law|government|election|治理|监管|政策|法规", haystack):
        return "policy"
    if re.search(r"arxiv|academic|university|bair|csail|论文预印本|学术", haystack):
        return "academia"
    if re.search(r"research|paper|study|benchmark|simulation|论文|研究|评测|基准", haystack):
        return "research"
    if re.search(r"open.source|github|开源|开放权重", haystack):
        return "open_source"
    if re.search(r"startup|venture|seed round|series [a-f]|初创|创业|融资轮", haystack):
        return "startups"
    if re.search(r"model|llm|gpt|claude|gemini|qwen|deepseek|模型|推理", haystack):
        return "models"
    if re.search(r"funding|revenue|earnings|acqui|data center|chip|enterprise|融资|营收|收购|数据中心|芯片|企业", haystack):
        return "business"
    if re.search(r"jobs|labor|education|culture|public|environment|社会|就业|教育|文化|环境|公众", haystack):
        return "society"
    return "company"


def _row_domain(row):
    return infer_domain(
        row.get("category"), row.get("source_category"),
        " ".join([
            row.get("title") or row.get("title_en") or row.get("title_zh") or "",
            row.get("source_name") or "", " ".join(parse_tags(row.get("tags"))),
        ]),
    )


def _balanced_domain_limit(items, limit, domain_getter, key_getter):
    """Reserve one highest-ranked story per represented specialist field."""
    if len(items) <= limit:
        return items
    reserved = {}
    for item in items:  # Input is already importance-ranked.
        domain = domain_getter(item)
        if domain and domain != "ai" and domain not in reserved:
            reserved[domain] = item
    reserved_keys = {key_getter(item) for item in reserved.values()}
    ordinary_slots = max(0, limit - len(reserved_keys))
    selected = []
    for item in items:
        key = key_getter(item)
        if key in reserved_keys or ordinary_slots > 0:
            selected.append(item)
            if key not in reserved_keys:
                ordinary_slots -= 1
    return selected[:limit]


def select_balanced_rows(rows, limit, max_open_source, max_academia,
                         min_academia_importance, min_academia_confidence):
    """Apply source/category caps while keeping the strongest eligible rows."""
    selected = []
    github_count = 0
    academia_count = 0
    for row in rows:
        source_name = row.get("source_name") or ""
        title = row.get("title") or row.get("title_en") or row.get("title_zh") or ""
        if not passes_source_ai_filter(source_name, title):
            continue
        category = normalize_category(
            row["category"], row.get("tags"), row.get("title") or "", row.get("source_name") or ""
        )
        if category == "open_source" and row.get("source_name") == "GitHub Trending":
            if github_count >= max_open_source:
                continue
            github_count += 1
        if category == "academia":
            if int(row.get("importance_score") or 0) < min_academia_importance:
                continue
            if int(row.get("confidence_score") or 0) < min_academia_confidence:
                continue
            if academia_count >= max_academia:
                continue
            academia_count += 1
        selected.append(row)
    return _balanced_domain_limit(
        selected, limit, _row_domain,
        lambda row: row.get("id") or row.get("url"),
    )


def load_previous_items(path, max_age_hours=48):
    """Load items whose original source publication is still in the brief window."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            items = json.load(handle).get("items", [])
    except (OSError, TypeError, json.JSONDecodeError):
        return []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=max_age_hours)
    recent = []
    for item in items:
        try:
            source_published = item.get("source_published_at") or item.get("published_at")
            published = datetime.fromisoformat(str(source_published or "").replace("Z", "+00:00"))
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if cutoff <= published <= now:
            recent.append(item)
    return recent


def merge_recent_items(current, previous, limit, max_github, max_academia,
                       min_academia_importance, min_academia_confidence):
    """Merge, rank, and reapply publication gates to carried-forward items."""
    deduped = {}
    for item in previous + current:
        # Article ids are permanent even when an official source replaces an
        # earlier media URL. Deduplicating by URL first would temporarily show
        # both provenance versions of the same story.
        key = item.get("id") or item.get("url")
        if key:
            deduped[key] = item  # Current items arrive last and win.

    def rank(item):
        published = str(item.get("source_published_at") or item.get("published_at") or "")
        return int(item.get("importance") or 0), published

    eligible = []
    github_count = 0
    academia_count = 0
    for item in sorted(deduped.values(), key=rank, reverse=True):
        title = (item.get("en") or {}).get("title") or (item.get("zh") or {}).get("title") or ""
        if not passes_source_ai_filter(item.get("source") or "", title):
            continue
        if item.get("source") == "GitHub Trending":
            if github_count >= max_github:
                continue
            github_count += 1
        if item.get("category") == "academia":
            confidence = int((item.get("scores") or {}).get("confidence") or 0)
            if int(item.get("importance") or 0) < min_academia_importance:
                continue
            if confidence < min_academia_confidence:
                continue
            if academia_count >= max_academia:
                continue
            academia_count += 1
        eligible.append(item)
    return _balanced_domain_limit(
        eligible, limit,
        lambda item: item.get("domain") or infer_domain(
            item.get("category"), None,
            " ".join([
                (item.get("en") or {}).get("title") or "",
                (item.get("zh") or {}).get("title") or "",
                item.get("source") or "", " ".join(item.get("tags") or []),
            ]),
        ),
        lambda item: item.get("id") or item.get("url"),
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="web/public/data/latest.json")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--discover-images", type=int, default=60)
    parser.add_argument("--max-open-source", type=int, default=2)
    parser.add_argument("--max-academia", type=int, default=2)
    parser.add_argument("--min-academia-importance", type=int, default=70)
    parser.add_argument("--min-academia-confidence", type=int, default=65)
    parser.add_argument("--carry-forward-hours", type=int, default=48)
    parser.add_argument("--max-age-hours", type=int, default=48)
    args = parser.parse_args()

    previous_items = load_previous_items(args.output, args.carry_forward_hours)

    db_url = os.environ.get("INBRIEF_SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("INBRIEF_SUPABASE_DB_URL is required")

    with psycopg2.connect(db_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute(
                """
                SELECT a.id, a.url, a.title, a.title_en, a.title_zh,
                       a.summary_en, a.summary_zh, a.long_summary_en, a.long_summary_zh,
                       a.importance_score, a.signal_score, a.structure_score,
                       a.consequence_score, a.confidence_score, a.momentum_score,
                       a.tags, a.category, a.published_at,
                       COALESCE(a.source_published_at, a.published_at) AS source_published_at,
                       a.created_at, rs.name AS source_name,
                       rs.category AS source_category
                FROM articles a
                LEFT JOIN rss_sources rs ON rs.id = a.rss_source_id
                WHERE COALESCE(a.source_published_at, a.published_at, a.created_at)
                      >= NOW() - (%s * INTERVAL '1 hour')
                  AND COALESCE(a.source_published_at, a.published_at, a.created_at) <= NOW()
                ORDER BY (a.importance_score - CASE WHEN a.category IN ('opensource', 'open_source') AND rs.name = 'GitHub Trending' THEN 25 ELSE 0 END) DESC,
                         COALESCE(rs.importance_score, 0) DESC,
                         COALESCE(a.source_published_at, a.published_at, a.created_at) DESC
                LIMIT %s
                """,
                (max(1, args.max_age_hours), max(args.limit * 3, args.limit)),
            )
            rows = select_balanced_rows(
                cursor.fetchall(), args.limit, args.max_open_source,
                args.max_academia, args.min_academia_importance,
                args.min_academia_confidence,
            )

    image_urls = [youtube_thumbnail(safe_http_url(row["url"])) for row in rows]
    discoverable = {
        index: safe_http_url(row["url"])
        for index, row in enumerate(rows[:args.discover_images])
        if not image_urls[index] and safe_http_url(row["url"])
    }
    if discoverable:
        with ThreadPoolExecutor(max_workers=min(6, len(discoverable))) as executor:
            futures = {
                executor.submit(discover_image, url): index
                for index, url in discoverable.items()
            }
            for future in as_completed(futures):
                image_urls[futures[future]] = future.result()

    items = []
    for index, row in enumerate(rows):
        source_url = safe_http_url(row["url"])
        items.append({
            "id": row["id"],
            "url": source_url,
            "source": row["source_name"] or "Unknown source",
            "category": normalize_category(
                row["category"], row["tags"], row["title"] or "", row["source_name"] or ""
            ),
            "domain": infer_domain(
                row["category"], row.get("source_category"),
                " ".join([row["title"] or "", row["source_name"] or "", " ".join(parse_tags(row["tags"]))]),
            ),
            "importance": int(row["importance_score"] or 0),
            "scores": {
                "signal": int(row["signal_score"] or 0),
                "structure": int(row["structure_score"] or 0),
                "consequence": int(row["consequence_score"] or 0),
                "confidence": int(row["confidence_score"] or 0),
                "momentum": int(row["momentum_score"] or 0),
            },
            "published_at": iso(row["published_at"] or row["created_at"]),
            "site_published_at": iso(row["created_at"]),
            "source_published_at": iso(
                row["source_published_at"] or row["published_at"] or row["created_at"]
            ),
            "image_url": image_urls[index],
            "tags": parse_tags(row["tags"]),
            "en": {
                "title": row["title_en"] or row["title"],
                "summary": row["summary_en"] or row["long_summary_en"] or "",
                "full_summary": row["long_summary_en"] or row["summary_en"] or "",
            },
            "zh": {
                "title": row["title_zh"] or row["title"],
                "summary": row["summary_zh"] or row["long_summary_zh"] or "",
                "full_summary": row["long_summary_zh"] or row["summary_zh"] or "",
            },
        })

    items = merge_recent_items(
        items, previous_items, args.limit, args.max_open_source,
        args.max_academia, args.min_academia_importance,
        args.min_academia_confidence,
    )
    for item in items:
        item["domain"] = item.get("domain") or infer_domain(
            item.get("category"), None,
            " ".join([
                (item.get("en") or {}).get("title") or "",
                (item.get("zh") or {}).get("title") or "",
                item.get("source") or "",
                " ".join(item.get("tags") or []),
            ]),
        )
        scores = item.get("scores") or {}
        item["scores"] = {
            key: max(0, min(100, int(scores.get(key) or 0)))
            for key in ("signal", "structure", "consequence", "confidence", "momentum")
        }
        for locale in ("en", "zh"):
            localized = item.get(locale) or {}
            item[locale] = {
                "title": localized.get("title") or "",
                "summary": localized.get("summary") or localized.get("long_summary") or "",
                "full_summary": localized.get("full_summary") or localized.get("long_summary") or localized.get("summary") or "",
            }

    payload = {
        "brand": "Polyemergence",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(items),
        "items": items,
    }
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
        handle.write("\n")

    sitemap_path = os.path.join(os.path.dirname(os.path.dirname(args.output)), "sitemap.xml")
    if os.path.exists(sitemap_path):
        today = datetime.now(timezone.utc).date().isoformat()
        with open(sitemap_path, "r", encoding="utf-8") as handle:
            sitemap = handle.read()
        sitemap = re.sub(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", f"<lastmod>{today}</lastmod>", sitemap)
        with open(sitemap_path, "w", encoding="utf-8") as handle:
            handle.write(sitemap)
    print(f"Exported {len(items)} articles to {args.output}")


if __name__ == "__main__":
    main()
