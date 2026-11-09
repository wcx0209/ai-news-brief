#!/usr/bin/env python3
"""Generate bilingual static daily archives, indexes, RSS, and an archive sitemap."""

import argparse
import html
import json
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


SITE = "https://polyemergence.com"
LOCAL_TZ = ZoneInfo("Asia/Singapore")
CATEGORIES = {
    "models", "company", "startups", "research", "academia",
    "open_source", "interviews", "policy", "business", "society",
}
CATEGORY_LABELS = {
    "en": {"models": "Models", "company": "Company", "startups": "Startups", "research": "Research", "academia": "Academia", "open_source": "Open Source", "interviews": "Interviews", "policy": "Policy", "business": "Business", "society": "Society"},
    "zh": {"models": "模型", "company": "公司", "startups": "创业", "research": "研究", "academia": "学术", "open_source": "开源", "interviews": "访谈", "policy": "政策", "business": "商业", "society": "社会"},
}
COPY = {
    "en": {"lang": "en", "brand": "Polyemergence", "brief": "Brief", "archive": "Archive", "method": "Method", "edition": "GLOBAL EDITION", "title": "AI News Archive", "intro": "A permanent record of Polyemergence AI intelligence, organized by Singapore publication date.", "stories": "stories", "months": "Months", "days": "Daily editions", "day_count": "days", "original": "Read original", "share": "Share", "importance": "Importance", "signal": "Signal", "structure": "Structure", "consequence": "Consequence", "confidence": "Confidence", "momentum": "Momentum", "older": "Older edition", "newer": "Newer edition", "month": "Month overview", "all": "All archives", "feed": "RSS feed", "footer": "Independent AI intelligence for a changing world.", "company": "Published by a Singapore-based technology startup focused on data and investment."},
    "zh": {"lang": "zh-Hans", "brand": "多重涌现", "brief": "简报", "archive": "历史归档", "method": "方法", "edition": "全球版", "title": "AI 新闻历史归档", "intro": "按新加坡发布日期整理的多重涌现 AI 情报永久记录。", "stories": "条内容", "months": "月份", "days": "每日归档", "day_count": "天", "original": "阅读原文", "share": "分享", "importance": "重要性", "signal": "信号", "structure": "结构", "consequence": "影响", "confidence": "可信度", "momentum": "热度", "older": "较早一期", "newer": "较新一期", "month": "本月总览", "all": "全部归档", "feed": "RSS 订阅", "footer": "面向变化世界的独立 AI 情报媒体。", "company": "由一家位于新加坡、以数据与投资为主要业务的科技初创公司创办。"},
}


def esc(value):
    return html.escape(str(value or ""), quote=True)


def clean_text(value):
    """Turn lightweight Markdown summaries into readable archive/RSS text."""
    text = str(value or "").replace("\r\n", "\n")
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "• ", text)
    text = re.sub(r"\[([^\]]+)\]\((?:https?://[^)]+)\)", r"\1", text)
    text = re.sub(r"(\*\*|__|`)", "", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def safe_url(value):
    try:
        parsed = urlparse(str(value or ""))
        return str(value) if parsed.scheme in {"http", "https"} and parsed.netloc else "#"
    except ValueError:
        return "#"


def parse_datetime(value):
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_tags(value):
    if isinstance(value, list):
        return [str(tag) for tag in value[:5]]
    if not value:
        return []
    try:
        parsed = json.loads(value)
        return [str(tag) for tag in parsed[:5]] if isinstance(parsed, list) else []
    except (TypeError, json.JSONDecodeError):
        return [tag.strip() for tag in str(value).split(",") if tag.strip()][:5]


def normalize_category(value, title="", source="", tags=None):
    category = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if category in CATEGORIES:
        return category
    if category == "opensource":
        return "open_source"
    text = " ".join([title or "", source or "", " ".join(tags or [])]).lower()
    checks = [
        ("interviews", r"interview|podcast|conversation|访谈|对谈|播客"),
        ("policy", r"policy|regulat|law|government|治理|监管|政策|法规"),
        ("academia", r"arxiv|academic|university|bair|csail|预印本|学术"),
        ("research", r"research|paper|study|benchmark|论文|研究|评测|基准"),
        ("open_source", r"open.source|github|开源|开放权重"),
        ("startups", r"startup|venture|seed round|series [a-f]|初创|创业|融资轮"),
        ("models", r"model|llm|gpt|claude|gemini|qwen|deepseek|模型|推理"),
        ("business", r"funding|revenue|earnings|acqui|chip|enterprise|融资|营收|收购|芯片|企业"),
        ("society", r"jobs|labor|education|culture|public|environment|社会|就业|教育|文化|环境"),
    ]
    for result, pattern in checks:
        if re.search(pattern, text):
            return result
    return "company"


def anchor_for(record):
    return "news-" + re.sub(r"[^A-Za-z0-9_-]+", "-", str(record["id"])).strip("-")


def archive_path(locale, day, anchor=None):
    base = f"/{locale}/archive/{day:%Y/%m/%d}/"
    return base + (f"#{anchor}" if anchor else "")


def record_from_feed(item):
    published = parse_datetime(item.get("published_at"))
    tags = parse_tags(item.get("tags"))
    source = item.get("source") or "Unknown source"
    title = (item.get("en") or {}).get("title") or (item.get("zh") or {}).get("title") or ""
    scores = item.get("scores") or {}
    return {
        "id": item.get("id"), "url": safe_url(item.get("url")), "source": source,
        "category": normalize_category(item.get("category"), title, source, tags),
        "published": published, "importance": int(item.get("importance") or 0),
        "scores": {key: int(scores.get(key) or 0) for key in ("signal", "structure", "consequence", "confidence", "momentum")},
        "tags": tags,
        "en": {"title": (item.get("en") or {}).get("title") or title, "summary": (item.get("en") or {}).get("summary") or "", "full": (item.get("en") or {}).get("full_summary") or (item.get("en") or {}).get("summary") or ""},
        "zh": {"title": (item.get("zh") or {}).get("title") or title, "summary": (item.get("zh") or {}).get("summary") or "", "full": (item.get("zh") or {}).get("full_summary") or (item.get("zh") or {}).get("summary") or ""},
    }


def load_json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return [record_from_feed(item) for item in payload.get("items", []) if item.get("published_at")]


def load_database():
    import psycopg2
    import psycopg2.extras

    db_url = os.environ.get("INBRIEF_SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("INBRIEF_SUPABASE_DB_URL is required unless --input-json is used")
    with psycopg2.connect(db_url) as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute("""
                SELECT a.id, a.url, a.title, a.title_en, a.title_zh,
                       a.summary_en, a.summary_zh, a.long_summary_en, a.long_summary_zh,
                       a.importance_score, a.signal_score, a.structure_score,
                       a.consequence_score, a.confidence_score, a.momentum_score,
                       a.tags, a.category, COALESCE(a.published_at, a.created_at) AS published_at,
                       rs.name AS source_name
                FROM articles a
                LEFT JOIN rss_sources rs ON rs.id = a.rss_source_id
                WHERE a.importance_score > 0
                ORDER BY COALESCE(a.published_at, a.created_at) DESC
            """)
            rows = cursor.fetchall()

    records = []
    for row in rows:
        tags = parse_tags(row["tags"])
        source = row["source_name"] or "Unknown source"
        title = row["title_en"] or row["title"] or row["title_zh"] or ""
        records.append({
            "id": row["id"], "url": safe_url(row["url"]), "source": source,
            "category": normalize_category(row["category"], title, source, tags),
            "published": parse_datetime(row["published_at"]), "importance": int(row["importance_score"] or 0),
            "scores": {"signal": int(row["signal_score"] or 0), "structure": int(row["structure_score"] or 0), "consequence": int(row["consequence_score"] or 0), "confidence": int(row["confidence_score"] or 0), "momentum": int(row["momentum_score"] or 0)},
            "tags": tags,
            "en": {"title": row["title_en"] or row["title"] or "", "summary": row["summary_en"] or row["long_summary_en"] or "", "full": row["long_summary_en"] or row["summary_en"] or ""},
            "zh": {"title": row["title_zh"] or row["title"] or "", "summary": row["summary_zh"] or row["long_summary_zh"] or "", "full": row["long_summary_zh"] or row["summary_zh"] or ""},
        })
    return records


def select_daily(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["published"].astimezone(LOCAL_TZ).date()].append(record)
    selected = {}
    for day, items in grouped.items():
        github = academia = 0
        output = []
        for item in sorted(items, key=lambda row: (row["importance"], row["published"]), reverse=True):
            if item["source"] == "GitHub Trending":
                if github >= 2:
                    continue
                github += 1
            if item["category"] == "academia":
                if item["importance"] < 70 or item["scores"]["confidence"] < 65 or academia >= 2:
                    continue
                academia += 1
            output.append(item)
        if output:
            selected[day] = output
    return selected


def json_ld(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def page_shell(locale, title, description, canonical, alternate, body, structured=None):
    c = COPY[locale]
    logo = f"logo-{locale}-reverse.svg"
    other = "zh" if locale == "en" else "en"
    structured_html = f'<script type="application/ld+json">{json_ld(structured)}</script>' if structured else ""
    return f'''<!doctype html>
<html lang="{c['lang']}" data-locale="{locale}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<script defer src="/analytics.js?v=1"></script><script defer src="/share.js?v=20261109-1"></script><title>{esc(title)}</title>
<meta name="description" content="{esc(description)}"><meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large">
<link rel="canonical" href="{esc(canonical)}"><link rel="alternate" hreflang="{c['lang']}" href="{esc(canonical)}">
<link rel="alternate" hreflang="{COPY[other]['lang']}" href="{esc(alternate)}"><link rel="alternate" hreflang="x-default" href="{esc(canonical if locale == 'en' else alternate)}">
<link rel="alternate" type="application/rss+xml" title="{esc(c['brand'])} RSS" href="/feed-{locale}.xml">
<meta property="og:type" content="website"><meta property="og:site_name" content="{esc(c['brand'])}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}"><meta property="og:image" content="{SITE}/assets/social-preview.png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/styles.css?v=20261109-19"><link rel="stylesheet" href="/archive.css?v=3">{structured_html}</head>
<body><header class="site-header"><a class="brand" href="/{locale}/" aria-label="{esc(c['brand'])}"><img src="/assets/{logo}" alt="{esc(c['brand'])}" width="420" height="70"></a>
<nav class="desktop-nav" aria-label="Primary"><a href="/{locale}/#brief">{esc(c['brief'])}</a><a href="/{locale}/archive/" aria-current="page">{esc(c['archive'])}</a><a href="/{locale}/#about">{esc(c['method'])}</a></nav>
<div class="header-tools"><span class="edition">{esc(c['edition'])}</span><div class="language-switch"><a href="{esc(alternate)}" hreflang="{COPY[other]['lang']}">{'中' if other == 'zh' else 'EN'}</a><span>|</span><a href="{esc(canonical)}" aria-current="page">{'中' if locale == 'zh' else 'EN'}</a></div></div></header>
<main class="archive-main">{body}</main><footer><div class="footer-brand"><img src="/assets/{logo}" alt="{esc(c['brand'])}" width="360"></div><div class="footer-copy"><p>{esc(c['footer'])}</p><p class="company-note">{esc(c['company'])}</p><p class="footer-meta"><a href="/feed-{locale}.xml">{esc(c['feed'])}</a></p></div></footer></body></html>'''


def story_html(record, locale):
    c = COPY[locale]
    text = record[locale]
    scores = record["scores"]
    published_local = record["published"].astimezone(LOCAL_TZ)
    tags = "".join(f'<span>{esc(tag)}</span>' for tag in record["tags"])
    score_html = "".join(f'<span><small>{esc(c[key])}</small><strong>{scores[key]}</strong></span>' for key in ("signal", "structure", "consequence", "confidence", "momentum"))
    anchor = anchor_for(record)
    day = record["published"].astimezone(LOCAL_TZ).date()
    share_url = f"{SITE}{archive_path(locale, day)}?utm_source=share&amp;utm_medium=organic&amp;utm_campaign=article#{anchor}"
    share_summary = re.sub(r"\s+", " ", clean_text(text["summary"] or text["full"])).strip()[:180]
    share_button = f'''<button class="share-button" type="button" data-share-button data-share-id="{esc(record['id'])}" data-share-locale="{locale}" data-share-title="{esc(clean_text(text['title']))}" data-share-summary="{esc(share_summary)}" data-share-url="{share_url}" aria-label="{esc(c['share'])}: {esc(clean_text(text['title']))}"><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5"/></svg><span>{esc(c['share'])}</span></button>'''
    return f'''<article class="archive-story" id="{anchor_for(record)}">
<div class="archive-story-meta"><span>{esc(record['source'])}</span><span>{esc(CATEGORY_LABELS[locale][record['category']])}</span><time datetime="{record['published'].isoformat()}">{published_local:%H:%M} SGT</time><strong>{esc(c['importance'])} {record['importance']}</strong></div>
<h2><a href="#{anchor_for(record)}">{esc(clean_text(text['title']))}</a></h2><p>{esc(clean_text(text['full'] or text['summary']))}</p>
<div class="archive-scores" aria-label="Polyemergence Method scores">{score_html}</div><div class="archive-story-footer"><div class="archive-tags">{tags}</div><div class="archive-actions">{share_button}<a class="archive-original" href="{esc(record['url'])}" target="_blank" rel="noopener noreferrer">{esc(c['original'])} ↗</a></div></div></article>'''


def render_daily(output, locale, day, items, ordered_days):
    c = COPY[locale]
    index = ordered_days.index(day)
    newer = ordered_days[index - 1] if index > 0 else None
    older = ordered_days[index + 1] if index + 1 < len(ordered_days) else None
    canonical = SITE + archive_path(locale, day)
    alternate = SITE + archive_path("zh" if locale == "en" else "en", day)
    nav = []
    if older:
        nav.append(f'<a href="{archive_path(locale, older)}">← {esc(c["older"])}</a>')
    nav.append(f'<a href="/{locale}/archive/{day:%Y/%m}/">{esc(c["month"])}</a>')
    if newer:
        nav.append(f'<a href="{archive_path(locale, newer)}">{esc(c["newer"])} →</a>')
    body = f'''<section class="archive-hero"><p class="section-index">{esc(c['archive']).upper()}</p><h1>{day:%Y · %m · %d}</h1><p>{len(items)} {esc(c['stories'])}</p></section><nav class="archive-period-nav">{"".join(nav)}</nav><section class="archive-list">{"".join(story_html(item, locale) for item in items)}</section>'''
    structured = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{c['title']} {day.isoformat()}", "url": canonical, "datePublished": day.isoformat(), "inLanguage": c["lang"], "mainEntity": {"@type": "ItemList", "numberOfItems": len(items), "itemListElement": [{"@type": "ListItem", "position": pos, "url": canonical + "#" + anchor_for(item), "name": clean_text(item[locale]["title"])} for pos, item in enumerate(items, 1)]}}
    path = output / locale / "archive" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{day.isoformat()} | {c['title']}", c["intro"], canonical, alternate, body, structured), encoding="utf-8")


def render_indexes(output, locale, grouped):
    c = COPY[locale]
    ordered_days = sorted(grouped, reverse=True)
    months = defaultdict(list)
    for day in ordered_days:
        months[(day.year, day.month)].append(day)

    for (year, month), days in months.items():
        cards = []
        for day in days:
            titles = "".join(f'<li><a href="{archive_path(locale, day, anchor_for(item))}">{esc(clean_text(item[locale]["title"]))}</a></li>' for item in grouped[day][:5])
            cards.append(f'<article class="archive-day-card"><div><time datetime="{day.isoformat()}">{day:%d}</time><span>{len(grouped[day])} {esc(c["stories"])}</span></div><ol>{titles}</ol><a class="archive-day-link" href="{archive_path(locale, day)}">{day:%Y-%m-%d} →</a></article>')
        canonical = f"{SITE}/{locale}/archive/{year:04d}/{month:02d}/"
        other = "zh" if locale == "en" else "en"
        alternate = f"{SITE}/{other}/archive/{year:04d}/{month:02d}/"
        body = f'<section class="archive-hero"><p class="section-index">{esc(c["days"]).upper()}</p><h1>{year:04d} · {month:02d}</h1><p>{sum(len(grouped[day]) for day in days)} {esc(c["stories"])}</p></section><nav class="archive-period-nav"><a href="/{locale}/archive/">← {esc(c["all"])}</a></nav><section class="archive-day-grid">{"".join(cards)}</section>'
        path = output / locale / "archive" / f"{year:04d}" / f"{month:02d}" / "index.html"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(page_shell(locale, f"{year:04d}-{month:02d} | {c['title']}", c["intro"], canonical, alternate, body), encoding="utf-8")

    month_cards = []
    for (year, month), days in sorted(months.items(), reverse=True):
        count = sum(len(grouped[day]) for day in days)
        month_cards.append(f'<a class="archive-month-card" href="/{locale}/archive/{year:04d}/{month:02d}/"><strong>{year:04d} · {month:02d}</strong><span>{len(days)} {esc(c["day_count"])} · {count} {esc(c["stories"])}</span></a>')
    canonical = f"{SITE}/{locale}/archive/"
    other = "zh" if locale == "en" else "en"
    alternate = f"{SITE}/{other}/archive/"
    body = f'<section class="archive-hero archive-hero-root"><p class="section-index">POLYEMERGENCE</p><h1>{esc(c["title"])}</h1><p>{esc(c["intro"])}</p></section><section class="archive-months"><h2>{esc(c["months"])}</h2><div>{"".join(month_cards)}</div></section>'
    path = output / locale / "archive" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{c['title']} | {c['brand']}", c["intro"], canonical, alternate, body), encoding="utf-8")


def render_rss(output, locale, grouped, limit=100):
    c = COPY[locale]
    records = sorted((item for items in grouped.values() for item in items), key=lambda item: item["published"], reverse=True)[:limit]
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    root = ET.Element("rss", {"version": "2.0", "xmlns:atom": "http://www.w3.org/2005/Atom"})
    channel = ET.SubElement(root, "channel")
    ET.SubElement(channel, "title").text = c["brand"]
    ET.SubElement(channel, "link").text = f"{SITE}/{locale}/archive/"
    ET.SubElement(channel, "description").text = c["intro"]
    ET.SubElement(channel, "language").text = c["lang"]
    ET.SubElement(channel, "lastBuildDate").text = format_datetime(datetime.now(timezone.utc))
    ET.SubElement(channel, "atom:link", {"href": f"{SITE}/feed-{locale}.xml", "rel": "self", "type": "application/rss+xml"})
    for record in records:
        day = record["published"].astimezone(LOCAL_TZ).date()
        link = SITE + archive_path(locale, day, anchor_for(record))
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = clean_text(record[locale]["title"])
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = link
        ET.SubElement(item, "pubDate").text = format_datetime(record["published"])
        ET.SubElement(item, "category").text = CATEGORY_LABELS[locale][record["category"]]
        ET.SubElement(item, "description").text = clean_text(record[locale]["full"] or record[locale]["summary"])
        ET.SubElement(item, "source", {"url": record["url"]}).text = record["source"]
    ET.ElementTree(root).write(output / f"feed-{locale}.xml", encoding="utf-8", xml_declaration=True)


def render_sitemap(output, grouped):
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    xhtml = "http://www.w3.org/1999/xhtml"
    ET.register_namespace("", namespace)
    ET.register_namespace("xhtml", xhtml)
    root = ET.Element(f"{{{namespace}}}urlset")
    pages = [("archive", None)]
    months = sorted({(day.year, day.month) for day in grouped}, reverse=True)
    pages.extend(("month", value) for value in months)
    pages.extend(("day", day) for day in sorted(grouped, reverse=True))
    latest_day = max(grouped) if grouped else datetime.now(LOCAL_TZ).date()
    for kind, value in pages:
        suffix = "archive/" if kind == "archive" else (f"archive/{value[0]:04d}/{value[1]:02d}/" if kind == "month" else f"archive/{value:%Y/%m/%d}/")
        lastmod = latest_day if kind == "archive" else (max(day for day in grouped if (day.year, day.month) == value) if kind == "month" else value)
        for current_locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = f"{SITE}/{current_locale}/{suffix}"
            ET.SubElement(node, f"{{{namespace}}}lastmod").text = lastmod.isoformat()
            for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": f"{SITE}/{locale}/{suffix}"})
    ET.ElementTree(root).write(output / "archive-sitemap.xml", encoding="utf-8", xml_declaration=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="web/public")
    parser.add_argument("--input-json", help="Use a public feed fixture instead of PostgreSQL")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = load_json(args.input_json) if args.input_json else load_database()
    grouped = select_daily(records)
    if not grouped:
        raise SystemExit("No eligible archive records")
    ordered_days = sorted(grouped, reverse=True)
    for locale in ("en", "zh"):
        render_indexes(output, locale, grouped)
        for day in ordered_days:
            render_daily(output, locale, day, grouped[day], ordered_days)
        render_rss(output, locale, grouped)
    render_sitemap(output, grouped)
    print(f"Generated {len(grouped)} daily archives containing {sum(map(len, grouped.values()))} stories")


if __name__ == "__main__":
    main()
