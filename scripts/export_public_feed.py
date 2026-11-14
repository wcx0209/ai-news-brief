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

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from relevance_filter import passes_source_ai_filter
from editorial_domains import category_ids, infer_domain, match_category
from editorial_insights import enrich_item, is_github_trending
from source_images import discover_images, normalize_source_url


TOPIC_CATEGORIES = set(category_ids())


def safe_http_url(value):
    # Keep publication/provenance URLs byte-for-byte while applying the same
    # public HTTP(S) URL guard used by cloud image discovery.
    return value if isinstance(value, str) and normalize_source_url(value) else None


def youtube_thumbnail(url):
    """Return YouTube's reliable static thumbnail without using the Data API."""
    if not url:
        return None
    parsed = urlparse(url)
    video_id = None
    host = (parsed.hostname or "").lower()
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host == "youtube.com" or host.endswith(".youtube.com"):
        if parsed.path == "/watch":
            video_id = parse_qs(parsed.query).get("v", [None])[0]
        elif parsed.path.startswith(("/shorts/", "/embed/")):
            video_id = parsed.path.strip("/").split("/")[1]
    if video_id and re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"
    return None


def discover_image(url, timeout=8):
    """Backward-compatible single-image wrapper around validated candidates."""
    candidates = discover_images(url, timeout=timeout, limit=3)
    return candidates[0] if candidates else None


def _image_date(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def image_fields(item):
    """Sanitize only media metadata, bound to this exact source article.

    This is deliberately offline. A syntactically safe legacy image URL is
    retained, but never promoted to ``verified`` without actual discovery.
    """
    source = normalize_source_url(item.get("url"))
    bound = normalize_source_url(item.get("image_source_url") or item.get("url"))
    result = {"image_url": None, "image_candidates": [], "image_source_url": source,
              "image_rejected_urls": []}
    if not source or source != bound:
        return result
    rejected = set()
    if isinstance(item.get("image_rejected_urls"), list):
        for value in item["image_rejected_urls"]:
            normalized = normalize_source_url(value)
            if normalized and normalized not in rejected:
                rejected.add(normalized)
                result["image_rejected_urls"].append(value)
                if len(result["image_rejected_urls"]) >= 12:
                    break
    values = [item.get("image_url")]
    if isinstance(item.get("image_candidates"), list):
        values.extend(item["image_candidates"])
    seen = set()
    for value in values:
        normalized = normalize_source_url(value)
        if normalized and normalized not in seen and normalized not in rejected:
            seen.add(normalized)
            result["image_candidates"].append(value)
            if len(result["image_candidates"]) >= 3:
                break
    if result["image_candidates"]:
        result["image_url"] = result["image_candidates"][0]
    checked = _image_date(item.get("image_checked_at"))
    status = item.get("image_status")
    if checked is not None and status in {"verified", "unavailable"}:
        result["image_checked_at"] = checked.isoformat().replace("+00:00", "Z")
        result["image_status"] = status if result["image_candidates"] else "unavailable"
    return result


def merge_image_fields(current, previous, now=None):
    """Prefer new candidates; a transient miss must not erase earlier media."""
    result = image_fields(current)
    same_id = str(current.get("id") or "") == str(previous.get("id") or "")
    same_source = (normalize_source_url(current.get("url"))
                   == normalize_source_url(previous.get("url")))
    if not same_id or not same_source:
        return result
    prior = image_fields(previous)
    checked = _image_date(result.get("image_checked_at"))
    prior_checked = _image_date(prior.get("image_checked_at"))
    # The archive repair runs after the live-feed export. Do not let that
    # earlier snapshot overwrite a newer successful check during their merge.
    if (prior_checked and prior_checked <= (now or datetime.now(timezone.utc))
            and (checked is None or checked < prior_checked)):
        return prior
    if result["image_candidates"] and result.get("image_status") == "verified":
        # A real newer successful check may rehabilitate a previously rejected
        # URL. Only this attempt's explicit failures remain on the denylist.
        return result
    use_current = bool(result["image_candidates"]) and (
        not prior["image_candidates"] or (
            result.get("image_status") != "unavailable" and prior.get("image_status") != "verified"))
    preferred = result if use_current else prior
    # A failed new attempt is still recorded as unavailable, rather than
    # falsely claiming the preserved older URL passed a fresh check. Explicit
    # low-resolution rejections, unlike timeouts, must remove an old candidate.
    merged = {**preferred, "url": current.get("url"),
              "image_rejected_urls": result["image_rejected_urls"] + prior["image_rejected_urls"],
              **{key: result[key] for key in ("image_checked_at", "image_status") if key in result}}
    return image_fields(merged)


def collect_image_fields(rows, previous, discover_limit=60, now=None):
    """Cloud-only, bounded discovery with a seven-day verified-media cache."""
    now = now or datetime.now(timezone.utc)
    known = {str(item.get("id")): item for item in previous}
    output = []
    pending = {}
    for index, row in enumerate(rows):
        current = {"id": row.get("id"), "url": safe_http_url(row.get("url"))}
        prior = known.get(str(row.get("id"))) or {}
        media = merge_image_fields(current, prior, now=now)
        output.append(media)
        checked = _image_date(media.get("image_checked_at"))
        cached = (media.get("image_status") == "verified" and checked is not None
                  and now - timedelta(days=7) <= checked <= now)
        if not cached and index < max(0, discover_limit) and current["url"]:
            pending[index] = (current, prior)
    if pending:
        with ThreadPoolExecutor(max_workers=min(6, len(pending))) as executor:
            futures = {}
            for index, item in pending.items():
                rejected = []
                future = executor.submit(discover_images, item[0]["url"], timeout=8, limit=3, rejected=rejected)
                futures[future] = (index, rejected)
            for future in as_completed(futures):
                index, rejected = futures[future]
                current, prior = pending[index]
                try:
                    candidates = future.result()
                except Exception:
                    candidates = []
                discovered = {
                    **current, "image_candidates": candidates,
                    "image_url": candidates[0] if candidates else None,
                    "image_source_url": normalize_source_url(current["url"]),
                    "image_checked_at": now.isoformat().replace("+00:00", "Z"),
                    "image_status": "verified" if candidates else "unavailable",
                    "image_rejected_urls": rejected,
                }
                output[index] = merge_image_fields(discovered, prior, now=now)
    return output


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
                         min_academia_importance, min_academia_confidence,
                         min_importance=65):
    """Apply source/category caps while keeping the strongest eligible rows."""
    selected = []
    github_count = 0
    academia_count = 0
    for row in rows:
        if is_github_trending(row):
            continue
        if int(row.get("importance_score") or 0) < min_importance:
            continue
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
        if is_github_trending(item):
            continue
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
                       min_academia_importance, min_academia_confidence,
                       min_importance=65):
    """Merge, rank, and reapply publication gates to carried-forward items."""
    deduped = {}
    for item in previous + current:
        # Article ids are permanent even when an official source replaces an
        # earlier media URL. Deduplicating by URL first would temporarily show
        # both provenance versions of the same story.
        key = item.get("id") or item.get("url")
        if key:
            # Current editorial fields win; media alone survives a transient
            # discovery failure when id and source article still match.
            prior = deduped.get(key) or {}
            deduped[key] = {**item, **merge_image_fields(item, prior)}

    def rank(item):
        published = str(item.get("source_published_at") or item.get("published_at") or "")
        return int(item.get("importance") or 0), published

    eligible = []
    github_count = 0
    academia_count = 0
    for item in sorted(deduped.values(), key=rank, reverse=True):
        if is_github_trending(item):
            continue
        if int(item.get("importance") or 0) < min_importance:
            continue
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
    parser.add_argument("--input-json", help="Re-export already-public JSON offline; never connect to a database or discover images")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--discover-images", type=int, default=60)
    parser.add_argument("--max-open-source", type=int, default=2)
    parser.add_argument("--max-academia", type=int, default=2)
    parser.add_argument("--min-academia-importance", type=int, default=70)
    parser.add_argument("--min-academia-confidence", type=int, default=65)
    parser.add_argument("--min-importance", type=int, default=65)
    parser.add_argument("--carry-forward-hours", type=int, default=48)
    parser.add_argument("--max-age-hours", type=int, default=48)
    args = parser.parse_args()

    if args.input_json:
        # This path is intentionally dependency-free and read-only except for
        # its requested public output. It does not scrape or re-summarize news.
        with open(args.input_json, encoding="utf-8") as handle:
            original_payload = json.load(handle)
        current = load_previous_items(args.input_json, args.max_age_hours)
        items = merge_recent_items(
            current, [], args.limit, args.max_open_source, args.max_academia,
            args.min_academia_importance, args.min_academia_confidence,
            args.min_importance,
        )
        payload = {
            "brand": "Polyemergence",
            # Preserve the actual collection time, not the re-render time.
            "generated_at": original_payload.get("generated_at"),
            "count": len(items),
            "items": [enrich_item({**item, **image_fields(item)}) for item in items],
        }
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
            handle.write("\n")
        print(f"Re-exported {len(items)} already-public articles to {args.output}; no database, collection or LLM calls")
        return

    previous_items = load_previous_items(args.output, args.carry_forward_hours)

    db_url = os.environ.get("INBRIEF_SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("INBRIEF_SUPABASE_DB_URL is required")

    import psycopg2
    import psycopg2.extras

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
                  AND LOWER(BTRIM(COALESCE(rs.name, ''))) <> 'github trending'
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
                args.min_academia_confidence, args.min_importance,
            )

    media = collect_image_fields(rows, previous_items, args.discover_images)

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
            **media[index],
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
        args.min_academia_confidence, args.min_importance,
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

    items = [enrich_item(item) for item in items]

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
