#!/usr/bin/env python3
"""Generate bilingual static daily archives, indexes, RSS, and an archive sitemap."""

import argparse
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from relevance_filter import passes_source_ai_filter
from editorial_domains import categories, category_ids, category_labels, domains, infer_domain, match_category
from editorial_insights import enrich_item


SITE = "https://polyemergence.com"
LOCAL_TZ = ZoneInfo("Asia/Singapore")
CATEGORY_ORDER = category_ids()
CATEGORIES = set(CATEGORY_ORDER)
CATEGORY_LABELS = {locale: category_labels(locale) for locale in ("en", "zh")}
STORY_ANGLE_ORDER = [item["id"] for item in categories() if item.get("is_angle") is not False]
DOMAIN_REGISTRY = {item["id"]: item for item in domains()}
TOPIC_TITLES = {
    "en": {
        "models": "Model News: Releases, Benchmarks & Updates",
        "company": "Technology Company News: Products, Strategy & Partnerships",
        "startups": "Technology Startup News: Funding, Products & Venture Capital",
        "research": "Technology Research News: Papers, Experiments & Results",
        "academia": "Academic News: University Research & Papers",
        "biotech": "Biotech & Programmable Life: Synthetic Biology, Gene Editing & More",
        "open_source": "Open Source Technology: Models, Tools & Projects",
        "interviews": "Technology Interviews: Founders, Researchers & Industry Leaders",
        "policy": "Technology Policy News: Regulation, Safety & Government",
        "business": "Technology Business News: Markets, Investment & Strategy",
        "society": "Technology and Society: Work, Culture & Public Impact",
    },
    "zh": {
        "models": "模型资讯：发布、评测与更新",
        "company": "科技公司资讯：产品、战略与合作",
        "startups": "科技创业资讯：融资、产品与风险投资",
        "research": "科技研究资讯：论文、实验与成果",
        "academia": "学术资讯：高校研究与前沿论文",
        "biotech": "生物技术与可编程生命：合成生物、基因编辑与前沿进展",
        "open_source": "开源科技资讯：模型、工具与项目",
        "interviews": "科技深度访谈：创始人、研究者与行业领袖",
        "policy": "科技政策与监管：安全、法规与政府动态",
        "business": "科技商业资讯：市场、投资与企业战略",
        "society": "科技与社会：工作、文化与公共影响",
    },
}
COPY = {
    "en": {"lang": "en", "brand": "Polyemergence", "brief": "Brief", "fields": "Fields", "angles": "Story angles", "archive": "Archive", "method": "Method", "edition": "GLOBAL EDITION", "title": "Emerging Intelligence Archive", "intro": "A permanent record of Polyemergence coverage across AI and emerging technology, organized by Singapore publication date.", "stories": "stories", "months": "Months", "days": "Daily editions", "day_count": "days", "original": "Read original", "share": "Share", "importance": "Importance", "signal": "Signal", "structure": "Structure", "consequence": "Consequence", "confidence": "Confidence", "momentum": "Momentum", "older": "Older edition", "newer": "Newer edition", "month": "Month overview", "all": "All archives", "feed": "RSS feed", "footer": "Independent intelligence across AI and emerging technology.", "company": "Published by PolyEmergence Pte Ltd., Singapore. No current financial or commercial conflict declared.", "standards": "Editorial standards", "corrections": "Corrections", "about_brief": "About this brief", "content_type": "Content type", "source_type": "Source type", "source": "Original source", "published": "Source published", "process": "Process", "verification": "Verification", "byline": "Published by", "conflict": "Conflict disclosure"},
    "zh": {"lang": "zh-Hans", "brand": "多重涌现", "brief": "简报", "fields": "领域", "angles": "报道分类", "archive": "历史归档", "method": "方法", "edition": "全球版", "title": "前沿科技情报归档", "intro": "按新加坡发布日期整理的多重涌现人工智能与新兴科技情报永久记录。", "stories": "条内容", "months": "月份", "days": "每日归档", "day_count": "天", "original": "阅读原文", "share": "分享", "importance": "重要性", "signal": "信号", "structure": "结构", "consequence": "影响", "confidence": "可信度", "momentum": "热度", "older": "较早一期", "newer": "较新一期", "month": "本月总览", "all": "全部归档", "feed": "RSS 订阅", "footer": "面向变化世界的人工智能与新兴科技独立情报。", "company": "由新加坡 PolyEmergence Pte Ltd. 发布。目前无已声明的财务或商业利益冲突。", "standards": "编辑标准", "corrections": "纠错记录", "about_brief": "关于这篇简报", "content_type": "内容类型", "source_type": "信源类型", "source": "原始来源", "published": "原文发布时间", "process": "处理方式", "verification": "核验边界", "byline": "发布方", "conflict": "利益冲突"},
}

SEO_COPY = {
    "en": {
        "site_published": "Polyemergence published",
        "why": "Reading context",
        "signal": "Importance assessment",
        "watch": "Evidence to check",
        "daily": "Daily AI News",
        "full_archive": "View the complete daily archive",
    },
    "zh": {
        "site_published": "本站发布时间",
        "why": "阅读提示",
        "signal": "重要性评估",
        "watch": "可核查的证据",
        "daily": "每日 AI 新闻",
        "full_archive": "查看完整当日归档",
    },
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
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


PROSE_HEADINGS = {
    "overview", "introduction", "background", "keyfeatures", "detailedfeatures",
    "features", "howitworks", "technicaldetails", "technologyoverview",
    "systemarchitecture", "technicalarchitecture", "architecture", "installation",
    "installationandusage", "installationanduse", "usage", "gettingstarted",
    "applications", "practicalapplications", "results", "findings", "keyfindings",
    "researchmethod", "methodology", "limitations", "availability", "pricing",
    "whatchanged", "whatitmeans", "nextsteps", "futureimpact", "futureoutlook",
    "概述", "简介", "背景", "核心特点", "核心功能", "主要功能", "详细功能",
    "工作原理", "实现原理", "技术细节", "技术概述", "系统架构", "技术架构",
    "安装", "使用方法", "安装与使用", "快速开始", "应用场景", "实际应用",
    "研究方法", "研究结果", "主要发现", "局限", "限制", "局限性",
    "可用性", "定价", "未来影响", "行业实际影响", "未来展望", "下一步",
}


def prose_text(value):
    """Keep lightweight inline Markdown as inert text; never trust raw HTML."""
    text = str(value or "")
    # Plain link labels are sufficient for this summary; the authoritative
    # source URL stays in the separately validated Read original control.
    text = re.sub(r"!?\[([^\]]*)\]\([^\n)]*\)", r"\1", text)
    # Double underscores can be real technical identifiers (__init__, etc.).
    # Retaining an occasional Markdown marker is safer than changing a name.
    return re.sub(r"\*\*|`", "", text).strip()


def prose_heading(line):
    """Recognise explicit Markdown and a narrow set of legacy plain headings."""
    explicit = re.match(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$", line)
    if explicit:
        # The page already has an article h1; summary sections begin at h2.
        return (2 if len(explicit[1]) <= 2 else 3), prose_text(explicit[2])
    text = prose_text(line).rstrip(":：").strip()
    normalized = re.sub(r"\s+", "", text).casefold()
    if len(text) <= 80 and normalized in PROSE_HEADINGS:
        return 2, text
    return None


def archive_prose(value):
    """Render paragraphs/headings/lists safely, retaining order and all prose.

    This is deliberately not a general Markdown/HTML interpreter. Unknown
    syntax remains escaped text; fenced snippets remain escaped code blocks.
    """
    lines = str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output, paragraph, entries, code = [], [], [], []
    list_kind, fence = None, None

    def flush_paragraph():
        if paragraph:
            output.append("<p>" + esc(prose_text(" ".join(paragraph))) + "</p>")
            paragraph.clear()

    def flush_list():
        nonlocal list_kind
        if entries:
            tag = list_kind
            output.append(f"<{tag}>" + "".join(
                (f'<li value="{number}">' if tag == "ol" else "<li>") + esc(prose_text(text)) + "</li>"
                for number, text in entries
            ) + f"</{tag}>")
            entries.clear()
        list_kind = None

    def flush_code():
        output.append("<pre><code>" + esc("\n".join(code)) + "</code></pre>")
        code.clear()

    for line in lines:
        stripped = line.strip()
        marker = re.match(r"^\s*(`{3,}|~{3,})([^`]*)$", line)
        if fence:
            if stripped.startswith(fence):
                flush_code()
                fence = None
            else:
                code.append(line)
            continue
        if marker:
            flush_paragraph()
            flush_list()
            fence = marker[1]
            continue
        if not stripped:
            flush_paragraph()
            # Blank lines between bullet items do not create separate lists.
            continue
        heading = prose_heading(line)
        if heading:
            flush_paragraph()
            flush_list()
            level, text = heading
            output.append(f"<h{level}>" + esc(text) + f"</h{level}>")
            continue
        unordered = re.match(r"^\s*[-*+•]\s+(.+)$", line)
        ordered = re.match(r"^\s*(\d{1,3})[.)]\s+(.+)$", line)
        if unordered or ordered:
            flush_paragraph()
            kind = "ol" if ordered else "ul"
            if list_kind and list_kind != kind:
                flush_list()
            list_kind = kind
            entries.append((int(ordered[1]) if ordered else None, ordered[2] if ordered else unordered[1]))
            continue
        if entries and re.match(r"^\s{2,}\S", line):
            number, text = entries[-1]
            entries[-1] = number, text + " " + stripped
            continue
        flush_list()
        paragraph.append(stripped)
    flush_paragraph()
    flush_list()
    if fence:
        flush_code()
    return '<div class="archive-prose">' + "".join(output) + "</div>"


def archive_excerpt(text, locale):
    """List pages preview the summary, never duplicate an entire long brief."""
    value = re.sub(r"\s+", " ", clean_text(text.get("summary") or text.get("full"))).strip()
    maximum = 520 if locale == "en" else 260
    if len(value) <= maximum:
        return value
    excerpt = value[:maximum]
    stops = [match.end() for match in re.finditer(r"[.!?。！？](?:\s|$)", excerpt)]
    if stops and stops[-1] >= maximum * .55:
        excerpt = excerpt[:stops[-1]].rstrip()
    elif locale == "en" and " " in excerpt:
        excerpt = excerpt.rsplit(" ", 1)[0]
    return excerpt.rstrip() + "…"


def safe_url(value):
    value = str(value or "")
    if re.search(r"[\x00-\x20\\]", value):
        return "#"
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password else "#"
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
    matched = match_category(text)
    if matched:
        return matched
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


def article_path(locale, day, record):
    preserved = prior_trending_paths(record).get(locale)
    if preserved:
        return preserved
    return f"/{locale}/archive/{day:%Y/%m/%d}/{anchor_for(record)[5:]}/"


def prior_trending_paths(record):
    """Only accept this ranked record's own already-published canonical paths."""
    if not is_trending(record):
        return {}
    paths = {}
    values = record.get("canonical_urls") or {}
    if not isinstance(values, dict):
        return paths
    for locale in ("en", "zh"):
        value = values.get(locale)
        if safe_url(value) == "#":
            continue
        parsed = urlparse(value)
        match = re.fullmatch(rf"/{locale}/archive/(\d{{4}}/\d{{2}}/\d{{2}})/{re.escape(anchor_for(record)[5:])}/", parsed.path)
        if parsed.scheme != "https" or parsed.netloc != "polyemergence.com" or parsed.query or parsed.fragment or not match:
            continue
        try:
            datetime.strptime(match[1], "%Y/%m/%d")
        except ValueError:
            continue
        paths[locale] = parsed.path
    return paths


def topic_path(locale, category):
    return f"/{locale}/topics/{category.replace('_', '-')}/"


def field_path(locale, domain):
    return f"/{locale}/fields/{domain}/"


def record_domain(record):
    domain = record.get("domain")
    if domain in DOMAIN_REGISTRY:
        return domain
    text = " ".join([
        record.get("en", {}).get("title", ""),
        record.get("zh", {}).get("title", ""),
        " ".join(record.get("tags", [])),
    ])
    return infer_domain(record.get("category"), None, text)


def daily_brief_path(locale, day):
    slug = "daily-ai-news" if locale == "en" else "ai-news-daily"
    return f"/{locale}/{slug}/{day.isoformat()}/"


def content_type(record, locale):
    labels = {
        "en": {"interviews": "Interview summary", "academia": "Research summary", "research": "Research summary", "biotech": "Research summary", "default": "News summary"},
        "zh": {"interviews": "访谈摘要", "academia": "研究摘要", "research": "研究摘要", "biotech": "研究摘要", "default": "新闻摘要"},
    }
    return labels[locale].get(record["category"], labels[locale]["default"])


def source_type(record, locale):
    host = (urlparse(record["url"]).hostname or "").lower()
    def within(domain):
        return host == domain or host.endswith("." + domain)

    first_party = (
        "github.com", "github.blog", "arxiv.org", "huggingface.co", "openai.com",
        "anthropic.com", "deepmind.google", "blogs.nvidia.com", "tencent.com",
        "graphcore.ai", "sambanova.ai", "skhynix.com", "cloudflare.com",
        "databricks.com", "pinecone.io", "wandb.ai", "vercel.com",
        "broadinstitute.org", "news.mit.edu", "gov.uk", "aws.amazon.com",
        "ibm.com", "dwavequantum.com", "clearpathrobotics.com", "jaxa.jp",
        "nims.go.jp", "braingate.org", "iwmi.org", "gfi-apac.org",
        "siemens.com", "fraunhofer.de",
    )
    if host.endswith((".gov", ".gov.sg")) or within("europa.eu") or any(within(domain) for domain in first_party):
        return "First-party / official source" if locale == "en" else "第一方／官方来源"
    if within("youtube.com") or within("youtu.be"):
        return "Interview / video source" if locale == "en" else "访谈／视频来源"
    return "Publisher report" if locale == "en" else "媒体报道"


def is_trending(record):
    return str(record.get("source") or "").strip().casefold() == "github trending"


def display_date(record):
    """Keep legacy archive paths, but never call a ranking refresh publication."""
    if is_trending(record) or record.get("date_basis") == "first_seen":
        first_seen = record.get("first_seen_at") if "first_seen_at" in record else record.get("site_published") or record.get("created_at")
        return parse_datetime(first_seen) if first_seen else None, True
    return record.get("source_published") or record["published"], False


def trust_box(record, locale):
    c = COPY[locale]
    source_published, first_seen = display_date(record)
    date_label = ("First seen" if locale == "en" else "首次发现") if first_seen else c["published"]
    published_local = source_published.astimezone(LOCAL_TZ) if source_published else None
    date_markup = f'<time datetime="{source_published.isoformat()}">{published_local:%Y-%m-%d %H:%M} SGT</time>' if source_published else ("Unknown" if locale == "en" else "时间未知")
    process = (
        "AI-assisted discovery, translation, summarisation, classification and scoring; standards and corrections are maintained by the editorial desk."
        if locale == "en" else
        "AI 辅助发现、翻译、摘要、分类与评分；编辑标准和纠错由编辑部维护。"
    )
    verification = (
        "The original URL and publication metadata are retained. This brief is not independently fact-checked unless explicitly stated."
        if locale == "en" else
        "保留原始链接与发布信息；除非特别说明，本简报不构成独立事实核查。"
    )
    conflict = "No financial or commercial conflict declared." if locale == "en" else "无已声明的财务或商业利益冲突。"
    return f'''<details class="source-note"><summary>{esc(c['about_brief'])}</summary><dl>
<div><dt>{esc(c['content_type'])}</dt><dd>{esc(content_type(record, locale))}</dd></div>
<div><dt>{esc(c['source_type'])}</dt><dd>{esc(source_type(record, locale))}</dd></div>
<div><dt>{esc(c['source'])}</dt><dd><a href="{esc(record['url'])}" target="_blank" rel="noopener noreferrer">{esc(record['source'])} ↗</a></dd></div>
<div><dt>{esc(date_label)}</dt><dd>{date_markup}</dd></div>
<div><dt>{esc(c['process'])}</dt><dd>{esc(process)}</dd></div>
<div><dt>{esc(c['verification'])}</dt><dd>{esc(verification)}</dd></div>
<div><dt>{esc(c['byline'])}</dt><dd>Polyemergence Editorial Desk · PolyEmergence Pte Ltd.</dd></div>
<div><dt>{esc(c['conflict'])}</dt><dd>{esc(conflict)}</dd></div>
</dl><p><a href="/{locale}/standards/">{esc(c['standards'])} →</a> · <a href="/{locale}/corrections/">{esc(c['corrections'])} →</a></p></details>'''


def record_from_feed(item):
    item = enrich_item(item)
    published = parse_datetime(item.get("published_at"))
    source_published = parse_datetime(item.get("source_published_at") or item.get("published_at"))
    site_published = parse_datetime(item.get("site_published_at") or item.get("published_at"))
    tags = parse_tags(item.get("tags"))
    source = item.get("source") or "Unknown source"
    title = (item.get("en") or {}).get("title") or (item.get("zh") or {}).get("title") or ""
    if not passes_source_ai_filter(source, title):
        return None
    scores = item.get("scores") or {}
    return {
        "id": item.get("id"), "url": safe_url(item.get("url")), "source": source,
        "category": normalize_category(item.get("category"), title, source, tags),
        "domain": item.get("domain") or infer_domain(item.get("category"), None, " ".join([title, source, " ".join(tags)])),
        "published": published, "source_published": source_published,
        "site_published": site_published, "image_url": safe_url(item.get("image_url")),
        "importance": int(item.get("importance") or 0),
        "scores": {key: int(scores.get(key) or 0) for key in ("signal", "structure", "consequence", "confidence", "momentum")},
        "tags": tags,
        "evidence": item.get("evidence") or {}, "related_domains": item.get("related_domains") or [],
        "reading_context": item.get("reading_context") or {},
        "date_basis": item.get("date_basis") or ("first_seen" if is_trending(item) else "source_published"),
        "first_seen_at": item.get("first_seen_at") if is_trending(item) else item.get("first_seen_at") or site_published.isoformat().replace("+00:00", "Z"),
        "canonical_urls": {locale: SITE + path for locale, path in prior_trending_paths(item).items()},
        "en": {"title": (item.get("en") or {}).get("title") or title, "summary": (item.get("en") or {}).get("summary") or "", "full": (item.get("en") or {}).get("full_summary") or (item.get("en") or {}).get("summary") or ""},
        "zh": {"title": (item.get("zh") or {}).get("title") or title, "summary": (item.get("zh") or {}).get("summary") or "", "full": (item.get("zh") or {}).get("full_summary") or (item.get("zh") or {}).get("summary") or ""},
    }


def load_json(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    records = [record_from_feed(item) for item in payload.get("items", []) if item.get("published_at")]
    return [record for record in records if record]


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
                       CASE WHEN rs.name = 'GitHub Trending' THEN a.created_at
                            ELSE COALESCE(a.source_published_at, a.published_at, a.created_at) END AS source_published_at,
                       a.created_at AS site_published_at,
                       rs.name AS source_name,
                       rs.category AS source_category
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
        if not passes_source_ai_filter(source, title):
            continue
        records.append({
            "id": row["id"], "url": safe_url(row["url"]), "source": source,
            "category": normalize_category(row["category"], title, source, tags),
            "domain": infer_domain(row["category"], row.get("source_category"), " ".join([title, source, " ".join(tags)])),
            "published": parse_datetime(row["published_at"]),
            "source_published": parse_datetime(row["source_published_at"]),
            "site_published": parse_datetime(row["site_published_at"]), "image_url": "#",
            "importance": int(row["importance_score"] or 0),
            "scores": {"signal": int(row["signal_score"] or 0), "structure": int(row["structure_score"] or 0), "consequence": int(row["consequence_score"] or 0), "confidence": int(row["confidence_score"] or 0), "momentum": int(row["momentum_score"] or 0)},
            "tags": tags,
            "en": {"title": row["title_en"] or row["title"] or "", "summary": row["summary_en"] or row["long_summary_en"] or "", "full": row["long_summary_en"] or row["summary_en"] or ""},
            "zh": {"title": row["title_zh"] or row["title"] or "", "summary": row["summary_zh"] or row["long_summary_zh"] or "", "full": row["long_summary_zh"] or row["summary_zh"] or ""},
        })
    return [enrich_record(record) for record in records]


def enrich_record(record):
    """Use the same evidence rules for PostgreSQL and public-feed archives."""
    first_seen = record.get("first_seen_at") if "first_seen_at" in record else record["site_published"].isoformat().replace("+00:00", "Z")
    item = {**record, "first_seen_at": first_seen,
            "site_published_at": first_seen if is_trending(record) else record["site_published"].isoformat().replace("+00:00", "Z"),
            **{locale: {**record[locale], "full_summary": record[locale].get("full")} for locale in ("en", "zh")}}
    enriched = enrich_item(item)
    for key in ("evidence", "related_domains", "reading_context"):
        record[key] = enriched.get(key) or ([] if key == "related_domains" else {})
    record["date_basis"] = enriched.get("date_basis") or ("first_seen" if is_trending(record) else "source_published")
    record["first_seen_at"] = enriched.get("first_seen_at") if is_trending(record) else enriched.get("first_seen_at") or item["first_seen_at"]
    for locale in ("en", "zh"):
        record[locale]["summary"] = enriched[locale].get("summary") or record[locale]["summary"]
        record[locale]["full"] = enriched[locale].get("full_summary") or record[locale]["full"]
    return record


def select_daily(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["published"].astimezone(LOCAL_TZ).date()].append(record)
    selected = {}
    for day, items in grouped.items():
        academia = 0
        output = []
        for item in sorted(items, key=lambda row: (row["importance"], row["published"]), reverse=True):
            # Ranking quotas belong to the live selection, not the permanent
            # archive. Never drop an already-published repository from history.
            if item["category"] == "academia" and not is_trending(item):
                if item["importance"] < 70 or item["scores"]["confidence"] < 65 or academia >= 2:
                    continue
                academia += 1
            output.append(item)
        if output:
            selected[day] = output
    return selected


def merge_current_feed(records, feed_path):
    """Keep every currently published card addressable from its share link.

    The public feed can contain newly curated rows that are not returned by the
    archive query yet.  Merge those rows by id so the archive export and the
    homepage are always published atomically with matching anchors.
    """
    if not feed_path.exists():
        return records
    current = load_json(feed_path)
    known = {str(record["id"]): record for record in records}
    for record in current:
        existing = known.get(str(record["id"]))
        if existing:
            if record.get("image_url") not in (None, "", "#"):
                existing["image_url"] = record["image_url"]
            continue
        records.append(record)
    return records


def preserve_trending_history(records, corpus_path):
    """Retain only previously published rankings, and freeze their old links.

    Current news can intentionally be removed or reclassified; do not restore
    arbitrary prior corpus items. Trending is the narrow exception because its
    old mutable ranking timestamps and daily quota could erase public history.
    No database state is changed and rankings remain excluded from live news.
    """
    if not corpus_path.is_file():
        return records
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    known = {str(record["id"]): record for record in records}
    for item in payload.get("items", []):
        if not is_trending(item) or not item.get("published_at"):
            continue
        previous = record_from_feed(item)
        if not previous:
            continue
        key = str(previous["id"])
        current = known.get(key)
        if current:
            if not is_trending(current):
                continue
            # This is the prior public archive date, not a newly claimed source
            # publication. first_seen/source_published semantics stay untouched.
            current["published"] = previous["published"]
            current["canonical_urls"] = previous["canonical_urls"]
        else:
            records.append(previous)
            known[key] = previous
    return records


def json_ld(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def page_shell(locale, title, description, canonical, alternate, body, structured=None, og_type="website"):
    c = COPY[locale]
    logo = f"logo-{locale}-reverse.svg"
    other = "zh" if locale == "en" else "en"
    structured_html = f'<script type="application/ld+json">{json_ld(structured)}</script>' if structured else ""
    topic_links = "".join(
        f'<a href="{topic_path(locale, category)}">{esc(CATEGORY_LABELS[locale][category])}</a>'
        for category in STORY_ANGLE_ORDER
    )
    field_links = "".join(
        f'<a href="{field_path(locale, domain)}">{esc(item["label"][locale])}</a>'
        for domain, item in DOMAIN_REGISTRY.items()
    )
    current_path = urlparse(canonical).path
    fields_current = ' aria-current="page"' if f"/{locale}/fields/" in current_path else ""
    archive_current = ' aria-current="page"' if f"/{locale}/archive/" in current_path else ""
    body_class = ' class="archive-detail"' if og_type == "article" else ""
    return f'''<!doctype html>
<html lang="{c['lang']}" data-locale="{locale}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<script defer src="/analytics.js?v=2"></script><script defer src="/share.js?v=20261109-1"></script><title>{esc(title)}</title>
<meta name="description" content="{esc(description)}"><meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large">
<link rel="canonical" href="{esc(canonical)}"><link rel="alternate" hreflang="{c['lang']}" href="{esc(canonical)}">
<link rel="alternate" hreflang="{COPY[other]['lang']}" href="{esc(alternate)}"><link rel="alternate" hreflang="x-default" href="{esc(canonical if locale == 'en' else alternate)}">
<link rel="alternate" type="application/rss+xml" title="{esc(c['brand'])} RSS" href="/feed-{locale}.xml">
<meta property="og:type" content="{esc(og_type)}"><meta property="og:site_name" content="{esc(c['brand'])}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}"><meta property="og:image" content="{SITE}/assets/social-preview.png">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(title)}"><meta name="twitter:description" content="{esc(description)}"><meta name="twitter:image" content="{SITE}/assets/social-preview.png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/styles.css?v=20261112-28"><link rel="stylesheet" href="/archive.css?v=6">{structured_html}</head>
<body{body_class}><header class="site-header"><a class="brand" href="/{locale}/" aria-label="{esc(c['brand'])}"><img src="/assets/{logo}" alt="{esc(c['brand'])}" width="420" height="70"></a>
<nav class="desktop-nav" aria-label="{'Primary' if locale == 'en' else '主导航'}"><a href="/{locale}/#fields"{fields_current}>{esc(c['fields'])}</a><a href="/{locale}/archive/"{archive_current}>{esc(c['archive'])}</a><a href="/{locale}/#about">{esc(c['method'])}</a></nav>
<div class="header-tools"><span class="edition">{esc(c['edition'])}</span><div class="language-switch"><a href="{esc(alternate)}" hreflang="{COPY[other]['lang']}">{'中' if other == 'zh' else 'EN'}</a><span>|</span><a href="{esc(canonical)}" aria-current="page">{'中' if locale == 'zh' else 'EN'}</a></div></div></header>
<main class="archive-main">{body}</main><footer><div class="footer-brand"><img src="/assets/{logo}" alt="{esc(c['brand'])}" width="360"></div><div class="footer-copy"><p>{esc(c['footer'])}</p><p class="company-note">{esc(c['company'])}</p><p class="footer-meta">{esc(c['fields'])}</p><nav class="footer-topics" aria-label="{esc(c['fields'])}">{field_links}</nav><p class="footer-meta">{esc(c['angles'])}</p><nav class="footer-topics" aria-label="{esc(c['angles'])}">{topic_links}</nav><p class="footer-meta"><a href="/{locale}/standards/">{esc(c['standards'])}</a> · <a href="/{locale}/corrections/">{esc(c['corrections'])}</a> · <a href="/feed-{locale}.xml">{esc(c['feed'])}</a> · <a href="/developers/">API / MCP</a></p></div></footer></body></html>'''


def editorial_analysis(record, locale):
    """Offer field-specific reading guidance, not fabricated article analysis."""
    domain = record_domain(record)
    label = DOMAIN_REGISTRY[domain]["label"][locale]
    why = (
        f"Read this {label} brief alongside the original source. Distinguish what was demonstrated from what is proposed or planned."
        if locale == "en" else
        f"阅读这篇{label}简报时，可结合原文区分已展示的成果、提出的设想与未来计划。"
    )
    scores = record["scores"]
    dimensions = [("signal", scores["signal"]), ("structure", scores["structure"]), ("consequence", scores["consequence"])]
    strongest, score = max(dimensions, key=lambda item: item[1])
    dimension_names = {
        "en": {"signal": "signal", "structure": "structure", "consequence": "consequence"},
        "zh": {"signal": "信号", "structure": "结构", "consequence": "影响"},
    }
    if locale == "en":
        signal = f"The recorded importance score is {record['importance']}/100; the highest of its signal, structure and consequence scores is {dimension_names[locale][strongest]} ({score}/100). These are editorial assessments, not independent verification."
    else:
        signal = f"本条新闻记录的重要性评分为 {record['importance']}/100；信号、结构、影响三个维度中，{dimension_names[locale][strongest]}得分最高（{score}/100）。这些评分属于编辑评估，不代表独立核验。"
    watch = {
        "ai": ("Check the stated evaluation setup, independent tests, access terms and evidence of real use.", "核查所述评测条件、独立测试、使用条款与实际应用证据。"),
        "programmable_life": ("Check the experimental stage, reproducibility, safety evidence, regulatory status and manufacturing scale.", "核查实验阶段、可重复性、安全证据、监管状态与制造规模。"),
        "energy_storage": ("Check operating conditions, measured performance, lifetime, cost assumptions and deployment scale.", "核查运行条件、实测表现、使用寿命、成本假设与部署规模。"),
        "robotics_autonomy": ("Check the test environment, human intervention, safety limits and repeated performance in real deployments.", "核查测试环境、人工干预、安全边界与实际部署中的重复表现。"),
        "quantum_technology": ("Check the measured task, error rates, physical versus logical qubits where relevant, and comparisons with classical methods.", "核查测量任务、错误率、适用时的物理与逻辑量子比特区别，以及与经典方法的比较。"),
        "space_economy": ("Check completed flight or orbital tests, mission status, reliability and disclosed cost assumptions.", "核查已完成的飞行或在轨测试、任务状态、可靠性与披露的成本假设。"),
        "advanced_materials": ("Check test conditions, independent reproduction, durability, feedstock requirements and production scale.", "核查测试条件、独立复现、耐久性、原料要求与生产规模。"),
        "neurotechnology": ("Check whether evidence comes from lab, animal or human studies, along with safety, consent and follow-up duration.", "核查证据来自实验室、动物还是人体研究，以及安全性、知情同意与随访时长。"),
        "climate_water_environment": ("Check system boundaries, lifecycle measurements, energy and water inputs, and performance at the reported scale.", "核查系统边界、全生命周期测量、能源与水投入，以及所述规模下的表现。"),
        "agrifood_technology": ("Check the trial or production setting, yields, input requirements, safety evidence and regulatory status.", "核查试验或生产条件、产量、投入要求、安全证据与监管状态。"),
        "advanced_manufacturing": ("Check throughput, defect rates, integration requirements, unit costs and evidence beyond a demonstration line.", "核查产能、缺陷率、集成要求、单位成本与示范线之外的应用证据。"),
    }.get(domain, (
        "Check the original evidence, test conditions, stated limitations and independent confirmation.",
        "核查原始证据、测试条件、所述限制与独立验证情况。",
    ))[0 if locale == "en" else 1]
    return why, signal, watch


def editorial_analysis_html(record, locale):
    if record["importance"] < 75:
        return ""
    why, signal, watch = editorial_analysis(record, locale)
    labels = SEO_COPY[locale]
    return f'''<aside class="editorial-analysis" aria-label="{esc(labels['signal'])}">
<div><h3>{esc(labels['why'])}</h3><p>{esc(why)}</p></div>
<div><h3>{esc(labels['signal'])}</h3><p>{esc(signal)}</p></div>
<div><h3>{esc(labels['watch'])}</h3><p>{esc(watch)}</p></div>
</aside>'''


def story_html(record, locale, detail=False):
    c = COPY[locale]
    text = record[locale]
    scores = record["scores"]
    source_published, first_seen = display_date(record)
    date_label = ("First seen" if locale == "en" else "首次发现") if first_seen else c["published"]
    published_local = source_published.astimezone(LOCAL_TZ) if source_published else None
    date_markup = f'<time datetime="{source_published.isoformat()}">{published_local:%Y-%m-%d %H:%M} SGT</time>' if source_published else ("Unknown" if locale == "en" else "时间未知")
    tags = "".join(f'<span>{esc(tag)}</span>' for tag in record["tags"])
    score_html = "".join(f'<span><small>{esc(c[key])}</small><strong>{scores[key]}</strong></span>' for key in ("signal", "structure", "consequence", "confidence", "momentum"))
    anchor = anchor_for(record)
    day = record["published"].astimezone(LOCAL_TZ).date()
    domain = record_domain(record)
    field_label = DOMAIN_REGISTRY[domain]["label"][locale]
    share_url = f"{SITE}{article_path(locale, day, record)}?utm_source=share&amp;utm_medium=organic&amp;utm_campaign=article"
    share_summary = re.sub(r"\s+", " ", clean_text(text["summary"] or text["full"])).strip()[:180]
    heading = "h1" if detail else "h2"
    title_html = esc(clean_text(text["title"])) if detail else f'<a href="{article_path(locale, day, record)}">{esc(clean_text(text["title"]))}</a>'
    evidence_labels = {
        "official_release": ("Official release", "官方发布"), "preprint": ("Preprint", "预印本"),
        "research_paper": ("Research paper", "研究论文"), "media_report": ("Media report", "媒体报道"),
        "interview": ("Interview", "访谈"), "open_source": ("Open source", "开源项目"), "unknown": ("Source type unconfirmed", "信源类型待确认"),
        "laboratory": ("Laboratory result", "实验室结果"), "demonstration": ("Demonstration", "演示"),
        "pilot": ("Pilot / trial", "试点／试验"), "deployment": ("Reported deployment", "报道已部署"),
        "unspecified": ("Stage not established", "阶段未明确"),
    }
    evidence = "".join(f'<span>{esc(evidence_labels[value][0 if locale == "en" else 1])}</span>' for value in (record.get("evidence") or {}).values() if value in evidence_labels)
    related = " × ".join(f'<a href="{field_path(locale, domain_id)}">{esc(DOMAIN_REGISTRY[domain_id]["label"][locale])}</a>' for domain_id in (record.get("related_domains") or [])[:2] if domain_id in DOMAIN_REGISTRY)
    context = (record.get("reading_context") or {}).get(locale)
    context_html = f'<p class="story-context"><strong>{"Observation focus (editorial lens)" if locale == "en" else "观察重点（编辑视角）"}</strong> {esc(context)}</p>' if context else ""
    if detail:
        summary_html = archive_prose(text["full"] or text["summary"])
    else:
        summary_label = "Read full summary" if locale == "en" else "阅读完整摘要"
        summary_html = f'<p class="archive-summary">{esc(archive_excerpt(text, locale))}</p><a class="archive-summary-link" href="{article_path(locale, day, record)}">{summary_label} →</a>'
    screening = "View selection rationale" if locale == "en" else "查看筛选依据"
    share_button = f'''<button class="share-button" type="button" data-share-button data-share-id="{esc(record['id'])}" data-share-locale="{locale}" data-share-title="{esc(clean_text(text['title']))}" data-share-summary="{esc(share_summary)}" data-share-url="{share_url}" aria-label="{esc(c['share'])}: {esc(clean_text(text['title']))}"><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5"/></svg><span>{esc(c['share'])}</span></button>'''
    return f'''<article class="archive-story" id="{anchor_for(record)}" data-story-id="{esc(record['id'])}">
<{heading}>{title_html}</{heading}>
<div class="archive-story-meta"><span>{esc(record['source'])}</span><a href="{field_path(locale, domain)}">{esc(field_label)}</a><span>{esc(CATEGORY_LABELS[locale][record['category']])}</span><span>{esc(date_label)}</span>{date_markup}</div>
<div class="story-evidence">{evidence}</div><div class="story-related">{related}</div>{summary_html}
<details class="screening-details"><summary>{screening}</summary>{context_html}<p>{esc(c['importance'])} {record['importance']}/100</p><div class="archive-scores" aria-label="Polyemergence Method scores">{score_html}</div>{editorial_analysis_html(record, locale)}</details>{trust_box(record, locale)}<div class="archive-story-footer"><div class="archive-tags">{tags}</div><div class="archive-actions">{share_button}<a class="archive-original" href="{esc(record['url'])}" target="_blank" rel="noopener noreferrer">{esc(c['original'])} ↗</a></div></div></article>'''


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
    nav.append(f'<a href="{daily_brief_path(locale, day)}">{esc(SEO_COPY[locale]["daily"])}</a>')
    if newer:
        nav.append(f'<a href="{archive_path(locale, newer)}">{esc(c["newer"])} →</a>')
    body = f'''<section class="archive-hero"><p class="section-index">{esc(c['archive']).upper()}</p><h1>{day:%Y · %m · %d}</h1><p>{len(items)} {esc(c['stories'])}</p></section><nav class="archive-period-nav">{"".join(nav)}</nav><section class="archive-list">{"".join(story_html(item, locale) for item in items)}</section>'''
    structured = {"@context": "https://schema.org", "@type": "CollectionPage", "name": f"{c['title']} {day.isoformat()}", "url": canonical, "datePublished": day.isoformat(), "inLanguage": c["lang"], "mainEntity": {"@type": "ItemList", "numberOfItems": len(items), "itemListElement": [{"@type": "ListItem", "position": pos, "url": SITE + article_path(locale, day, item), "name": clean_text(item[locale]["title"])} for pos, item in enumerate(items, 1)]}}
    path = output / locale / "archive" / f"{day:%Y}" / f"{day:%m}" / f"{day:%d}" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{day.isoformat()} | {c['title']}", c["intro"], canonical, alternate, body, structured), encoding="utf-8")


def render_daily_brief(output, locale, day, items):
    c = COPY[locale]
    items = [item for item in items if record_domain(item) == "ai" and not is_trending(item)]
    top = sorted(items, key=lambda item: (item["importance"], item["published"]), reverse=True)[:5]
    category_counts = Counter(item["category"] for item in items)
    leading_categories = [CATEGORY_LABELS[locale][key] for key, _ in category_counts.most_common(3)]
    lead_title = clean_text(top[0][locale]["title"]) if top else ""
    if locale == "en":
        title = f"Daily AI News — {day:%B %-d, %Y} | Polyemergence"
        description = f"AI news for {day:%B %-d, %Y}, ranked by the Polyemergence importance method and linked to original sources."
        lede = (
            f"This edition contains {len(items)} AI stories. Its highest-ranked story is “{lead_title}”. The most represented story angles are {', '.join(leading_categories)}."
            if items else "No AI stories are included in this date’s archive. Explore the AI field page for available coverage."
        )
        heading = f"DAILY AI NEWS · {day:%B %-d, %Y}"
    else:
        title = f"每日 AI 新闻 — {day:%Y年%m月%d日} | 多重涌现"
        description = f"{day:%Y年%m月%d日} AI 新闻，按多重涌现重要性方法排序，并保留原始来源链接。"
        lede = (
            f"本期收录 {len(items)} 条人工智能新闻，排名最高的是“{lead_title}”。报道数量最多的分类为{'、'.join(leading_categories)}。"
            if items else "这一天的归档没有收录人工智能新闻。可前往人工智能领域页查看已有报道。"
        )
        heading = f"每日 AI 新闻 · {day:%Y年%m月%d日}"
    if not items:
        description = lede
    canonical = SITE + daily_brief_path(locale, day)
    other = "zh" if locale == "en" else "en"
    alternate = SITE + daily_brief_path(other, day)
    # The same title-first, evidence-aware layout is used in historical editions.
    # Scores remain available inside disclosure rather than competing with titles.
    cards = [story_html(record, locale) for record in top]
    body = f'''<section class="archive-hero"><p class="section-index">{esc(SEO_COPY[locale]['daily']).upper()}</p><h1>{esc(heading)}</h1><p class="daily-brief-lede">{esc(lede)}</p></section>
<nav class="archive-period-nav"><a href="{field_path(locale, 'ai')}">{esc(DOMAIN_REGISTRY['ai']['label'][locale])}</a><a href="{archive_path(locale, day)}">{esc(SEO_COPY[locale]['full_archive'])} →</a></nav>
<section class="daily-brief-list">{"".join(cards)}</section>'''
    structured = {
        "@context": "https://schema.org", "@type": "CollectionPage", "name": title,
        "url": canonical, "datePublished": max(item["site_published"] for item in items).astimezone(LOCAL_TZ).isoformat() if items else day.isoformat(),
        "inLanguage": c["lang"], "isPartOf": {"@type": "WebSite", "@id": SITE + "/#website"},
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(top), "itemListElement": [
            {"@type": "ListItem", "position": position, "url": SITE + article_path(locale, day, record), "name": clean_text(record[locale]["title"])}
            for position, record in enumerate(top, 1)
        ]},
    }
    slug = "daily-ai-news" if locale == "en" else "ai-news-daily"
    path = output / locale / slug / day.isoformat() / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, title, description, canonical, alternate, body, structured), encoding="utf-8")


def render_article(output, locale, record):
    c = COPY[locale]
    other = "zh" if locale == "en" else "en"
    day = record["published"].astimezone(LOCAL_TZ).date()
    text = record[locale]
    title = clean_text(text["title"])
    description = re.sub(r"\s+", " ", clean_text(text["summary"] or text["full"])).strip()[:240]
    canonical = SITE + article_path(locale, day, record)
    alternate = SITE + article_path(other, day, record)
    domain = record_domain(record)
    field_label = DOMAIN_REGISTRY[domain]["label"][locale]
    daily_link = f'<a href="{daily_brief_path(locale, day)}">{esc(SEO_COPY[locale]["daily"])}</a>' if domain == "ai" else ""
    body = f'''<nav class="archive-period-nav" aria-label="{'Article navigation' if locale == 'en' else '文章导航'}"><a href="{archive_path(locale, day)}">← {day.isoformat()}</a><a href="{field_path(locale, domain)}">{esc(field_label)}</a>{daily_link}<a href="/{locale}/archive/">{esc(c['all'])}</a></nav><section class="archive-list archive-article-page">{story_html(record, locale, detail=True)}</section>'''
    schema_image = record.get("image_url")
    if not schema_image or schema_image == "#":
        schema_image = SITE + "/assets/social-preview.png"
    structured = {
        "@context": "https://schema.org", "@type": "NewsArticle", "headline": title,
        "description": description,
        "image": [schema_image],
        "datePublished": record["site_published"].astimezone(LOCAL_TZ).isoformat(),
        "dateModified": record["site_published"].astimezone(LOCAL_TZ).isoformat(), "inLanguage": c["lang"],
        "articleSection": CATEGORY_LABELS[locale][record["category"]],
        "about": {"@type": "Thing", "name": field_label, "url": SITE + field_path(locale, domain)},
        "keywords": record["tags"],
        "mainEntityOfPage": canonical, "url": canonical,
        "author": {"@type": "Organization", "name": "Polyemergence Editorial Desk", "url": SITE + f"/{locale}/standards/"},
        "publisher": {"@type": "NewsMediaOrganization", "name": c["brand"], "legalName": "PolyEmergence Pte Ltd.", "url": SITE, "logo": {"@type": "ImageObject", "url": SITE + "/assets/mark.svg"}, "publishingPrinciples": SITE + f"/{locale}/standards/", "correctionsPolicy": SITE + f"/{locale}/corrections/"},
        "isAccessibleForFree": True,
        "isBasedOn": record["url"],
    }
    path = output / article_path(locale, day, record).lstrip("/") / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{title} | {c['brand']}", description, canonical, alternate, body, structured, "article"), encoding="utf-8")


def render_topic(output, locale, category, records):
    c = COPY[locale]
    other = "zh" if locale == "en" else "en"
    title = TOPIC_TITLES[locale][category]
    description = (
        f"{title}. Follow coverage across AI and emerging technology, ranked by the Polyemergence importance method."
        if locale == "en"
        else f"{title}。多重涌现按重要性筛选并持续更新全球人工智能与新兴科技动态。"
    )
    canonical = SITE + topic_path(locale, category)
    alternate = SITE + topic_path(other, category)
    ordered = sorted(records, key=lambda item: (item["published"], item["importance"]), reverse=True)
    content = "".join(story_html(record, locale) for record in ordered)
    if not content:
        content = f'<p class="archive-empty">{"New coverage will appear here as it is published." if locale == "en" else "新内容发布后将在这里持续归档。"}</p>'
    body = f'''<section class="archive-hero archive-topic-hero"><p class="section-index">{esc(CATEGORY_LABELS[locale][category]).upper()}</p><h1>{esc(title)}</h1><p>{esc(description)}</p></section><nav class="archive-period-nav"><a href="/{locale}/">← {esc(c['brief'])}</a><a href="/{locale}/archive/">{esc(c['archive'])}</a></nav><section class="archive-list">{content}</section>'''
    structured = {
        "@context": "https://schema.org", "@type": "CollectionPage", "name": title,
        "description": description, "url": canonical, "inLanguage": c["lang"],
        "mainEntity": {"@type": "ItemList", "numberOfItems": len(ordered), "itemListElement": [
            {"@type": "ListItem", "position": position, "url": SITE + article_path(locale, record["published"].astimezone(LOCAL_TZ).date(), record), "name": clean_text(record[locale]["title"])}
            for position, record in enumerate(ordered, 1)
        ]},
    }
    path = output / locale / "topics" / category.replace("_", "-") / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{title} | {c['brand']}", description, canonical, alternate, body, structured), encoding="utf-8")


def render_indexes(output, locale, grouped):
    c = COPY[locale]
    ordered_days = sorted(grouped, reverse=True)
    months = defaultdict(list)
    for day in ordered_days:
        months[(day.year, day.month)].append(day)

    for (year, month), days in months.items():
        cards = []
        for day in days:
            titles = "".join(f'<li><a href="{article_path(locale, day, item)}">{esc(clean_text(item[locale]["title"]))}</a></li>' for item in grouped[day][:5])
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
    records = sorted((item for items in grouped.values() for item in items if not is_trending(item)), key=lambda item: item["published"], reverse=True)[:limit]
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
        link = SITE + article_path(locale, day, record)
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = clean_text(record[locale]["title"])
        ET.SubElement(item, "link").text = link
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = link
        ET.SubElement(item, "pubDate").text = format_datetime(record["published"])
        ET.SubElement(item, "category").text = CATEGORY_LABELS[locale][record["category"]]
        ET.SubElement(item, "category").text = DOMAIN_REGISTRY[record_domain(record)]["label"][locale]
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
    for day in sorted(grouped, reverse=True):
        for current_locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = SITE + daily_brief_path(current_locale, day)
            ET.SubElement(node, f"{{{namespace}}}lastmod").text = max(record["site_published"] for record in grouped[day]).date().isoformat()
            for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": SITE + daily_brief_path(locale, day)})
        for record in grouped[day]:
            for current_locale in ("en", "zh"):
                node = ET.SubElement(root, f"{{{namespace}}}url")
                ET.SubElement(node, f"{{{namespace}}}loc").text = SITE + article_path(current_locale, day, record)
                ET.SubElement(node, f"{{{namespace}}}lastmod").text = day.isoformat()
                for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                    ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": SITE + article_path(locale, day, record)})
    for category in CATEGORY_ORDER:
        for current_locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = SITE + topic_path(current_locale, category)
            ET.SubElement(node, f"{{{namespace}}}lastmod").text = latest_day.isoformat()
            for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": SITE + topic_path(locale, category)})
    for page in ("standards", "corrections"):
        for current_locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = f"{SITE}/{current_locale}/{page}/"
            ET.SubElement(node, f"{{{namespace}}}lastmod").text = latest_day.isoformat()
            for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": f"{SITE}/{locale}/{page}/"})
    ET.ElementTree(root).write(output / "archive-sitemap.xml", encoding="utf-8", xml_declaration=True)


def render_news_sitemap(output, grouped):
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    news = "http://www.google.com/schemas/sitemap-news/0.9"
    ET.register_namespace("", namespace)
    ET.register_namespace("news", news)
    root = ET.Element(f"{{{namespace}}}urlset")
    cutoff = datetime.now(timezone.utc) - timedelta(days=2)
    recent = sorted(
        (record for items in grouped.values() for record in items if record["site_published"] >= cutoff and not is_trending(record)),
        key=lambda record: record["site_published"], reverse=True,
    )[:500]
    for record in recent:
        day = record["published"].astimezone(LOCAL_TZ).date()
        for locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = SITE + article_path(locale, day, record)
            news_node = ET.SubElement(node, f"{{{news}}}news")
            publication = ET.SubElement(news_node, f"{{{news}}}publication")
            ET.SubElement(publication, f"{{{news}}}name").text = COPY[locale]["brand"]
            ET.SubElement(publication, f"{{{news}}}language").text = "en" if locale == "en" else "zh"
            ET.SubElement(news_node, f"{{{news}}}publication_date").text = record["site_published"].isoformat().replace("+00:00", "Z")
            ET.SubElement(news_node, f"{{{news}}}title").text = clean_text(record[locale]["title"])
    ET.ElementTree(root).write(output / "news-sitemap.xml", encoding="utf-8", xml_declaration=True)


def render_public_data(output, records):
    """Export the permanent public corpus consumed by the REST API and MCP server."""
    items = []
    for record in sorted(records, key=lambda item: (item["published"], item["importance"]), reverse=True):
        day = record["published"].astimezone(LOCAL_TZ).date()
        items.append(enrich_item({
            "id": str(record["id"]), "url": record["url"], "source": record["source"],
            "category": record["category"], "domain": record.get("domain", "ai"), "importance": record["importance"],
            "scores": record["scores"],
            "published_at": record["published"].isoformat().replace("+00:00", "Z"),
            "site_published_at": record.get("first_seen_at") if is_trending(record) and "first_seen_at" in record else record["site_published"].isoformat().replace("+00:00", "Z"),
            "source_published_at": None if is_trending(record) else record["source_published"].isoformat().replace("+00:00", "Z"),
            "first_seen_at": record.get("first_seen_at") if is_trending(record) and "first_seen_at" in record else record.get("first_seen_at") or record["site_published"].isoformat().replace("+00:00", "Z"),
            "date_basis": record.get("date_basis") or ("first_seen" if is_trending(record) else "source_published"),
            "image_url": None if record.get("image_url") == "#" else record.get("image_url"),
            "tags": record["tags"],
            "evidence": record.get("evidence") or {}, "related_domains": record.get("related_domains") or [],
            "reading_context": record.get("reading_context") or {},
            "canonical_urls": {locale: SITE + article_path(locale, day, record) for locale in ("en", "zh")},
            "en": {"title": clean_text(record["en"]["title"]), "summary": clean_text(record["en"]["summary"]), "full_summary": clean_text(record["en"]["full"])},
            "zh": {"title": clean_text(record["zh"]["title"]), "summary": clean_text(record["zh"]["summary"]), "full_summary": clean_text(record["zh"]["full"])},
        }))
    target = output / "data" / "articles.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({
        "schema_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(items),
        "methodology_url": SITE + "/api/v1/methodology",
        "license": "Public API access subject to Polyemergence terms and source rights; preserve attribution and canonical URLs.",
        "items": items,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="web/public")
    parser.add_argument("--input-json", help="Use a public feed fixture instead of PostgreSQL")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = merge_current_feed(
        load_json(args.input_json) if args.input_json else load_database(),
        output / "data" / "latest.json",
    )
    records = preserve_trending_history(records, output / "data" / "articles.json")
    grouped = select_daily(records)
    if not grouped:
        raise SystemExit("No eligible archive records")
    ordered_days = sorted(grouped, reverse=True)
    for locale in ("en", "zh"):
        render_indexes(output, locale, grouped)
        for day in ordered_days:
            render_daily(output, locale, day, grouped[day], ordered_days)
            render_daily_brief(output, locale, day, grouped[day])
            for record in grouped[day]:
                render_article(output, locale, record)
        all_records = [record for day in ordered_days for record in grouped[day]]
        for category in CATEGORY_ORDER:
            render_topic(output, locale, category, [
                record for record in all_records
                if (record.get("domain") == "programmable_life" if category == "biotech" else record["category"] == category)
            ])
        render_rss(output, locale, grouped)
    render_public_data(output, [record for day in ordered_days for record in grouped[day]])
    render_sitemap(output, grouped)
    render_news_sitemap(output, grouped)
    print(f"Generated {len(grouped)} daily archives containing {sum(map(len, grouped.values()))} stories")


if __name__ == "__main__":
    main()
