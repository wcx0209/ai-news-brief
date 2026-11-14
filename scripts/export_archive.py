#!/usr/bin/env python3
"""Generate bilingual static daily archives, indexes, RSS, and an archive sitemap."""

import argparse
import html
import json
import os
import re
import sys
from collections import Counter, defaultdict
from html.parser import HTMLParser
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from urllib.parse import urlencode, urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from relevance_filter import passes_source_ai_filter
from editorial_domains import categories, category_ids, category_labels, domains, infer_domain, match_category
from editorial_insights import enrich_item, article_reading_context
from archive_exploration import normalize_tag, topic_labels, related_articles
from source_images import normalize_source_url
from export_public_feed import image_fields, merge_image_fields
from editorial_artwork import editorial_artwork_path, editorial_caption


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
    # Underscores can be part of names such as __init__; keep those intact.
    text = re.sub(r"(\*\*|`)", "", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


PROSE_HEADINGS = {
    "overview", "introduction", "background", "keyfeatures", "detailedfeatures",
    "features", "howitworks", "technicaldetails", "technologyoverview",
    "systemarchitecture", "technicalarchitecture", "architecture", "installation",
    "installationandusage", "installationanduse", "usage", "gettingstarted",
    "applications", "practicalapplications", "results", "findings", "keyfindings",
    "researchmethod", "methodology", "limitations", "availability", "pricing",
    "datasetdetails", "industryimpact",
    "whatchanged", "whatitmeans", "nextsteps", "futureimpact", "futureoutlook",
    "概述", "简介", "背景", "核心特点", "核心功能", "主要功能", "详细功能",
    "工作原理", "实现原理", "技术细节", "技术概述", "系统架构", "技术架构",
    "安装", "使用方法", "安装与使用", "快速开始", "应用场景", "实际应用",
    "研究方法", "研究结果", "主要发现", "局限", "限制", "局限性",
    "可用性", "定价", "未来影响", "行业实际影响", "未来展望", "下一步",
    "背景与定位", "核心能力与表现", "效率与行业影响", "性能与关键细节", "生态整合与应用",
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


def detail_dek(text, locale):
    """Use the existing short summary as a lead, never invent a new takeaway.

    When a short full text is identical, it is shown once as the lead. A long
    text without a distinct short summary stays in the body rather than being
    repeated, flattened or cut mid-claim merely to fill the lead slot.
    """
    summary = re.sub(r"\s+", " ", prose_text(text.get("summary"))).strip()
    full = str(text.get("full") or text.get("summary") or "")
    full_plain = re.sub(r"\s+", " ", prose_text(full)).strip()
    maximum = 390 if locale == "en" else 190
    if not summary:
        return "", full
    if summary == full_plain:
        if len(summary) <= maximum and not any(prose_heading(line) for line in full.splitlines()):
            return summary, ""
        return "", full
    dek = summary
    if len(dek) > maximum:
        # Sentence punctuation must be followed by whitespace for English,
        # whereas Chinese sentence boundaries need no intervening space.
        boundaries = [match.end() for match in re.finditer(r"[。！？]|[.!?](?=\s|$)", dek[:maximum])]
        if not boundaries:
            return "", full
        dek = dek[:boundaries[-1]].strip()
    # Some generated long summaries repeat the short summary verbatim as the
    # first paragraph. Remove only an exact duplicate, not related analysis.
    paragraphs = re.split(r"\n\s*\n", full, maxsplit=1)
    first = re.sub(r"\s+", " ", prose_text(paragraphs[0])).strip()
    if first == dek and len(paragraphs) == 2:
        full = paragraphs[1]
    return dek, full


def editorial_media(record, locale, hidden=False, thumbnail=False):
    visibility = " hidden" if hidden else ""
    caption = ("Editorial artwork · Not a source image" if locale == "en" else "编辑配图 · 非原图") if thumbnail else editorial_caption(locale)
    artwork = (f'<div class="editorial-artwork" data-editorial-artwork{visibility}>'
               f'<img data-editorial-image src="{esc(editorial_artwork_path(record))}" alt="" width="1200" height="675" loading="lazy" decoding="async"></div>')
    return artwork + f'<figcaption class="editorial-caption" data-editorial-caption{visibility}>{esc(caption)}</figcaption>'


def archive_figure(record, locale):
    """Caption only source provenance, not guessed photographers or rights."""
    media = image_fields(record)
    image = safe_url(media["image_url"])
    parts = urlparse(image)
    if parts.hostname == "polyemergence.com" and parts.path.startswith("/assets/"):
        image = "#"  # Our own branding must never claim original provenance.
    if image == "#":
        return '<figure class="archive-figure is-editorial-visual">' + editorial_media(record, locale) + '</figure>'
    source_host = (urlparse(record.get("url") or "").hostname or "").lower()
    image_host = (parts.hostname or "").lower()
    video = (source_host in {"youtube.com", "www.youtube.com", "youtu.be"}
             or image_host == "ytimg.com" or image_host.endswith(".ytimg.com"))
    label = ("Video thumbnail" if locale == "en" else "视频缩略图") if video else ("Source image" if locale == "en" else "原文配图")
    unavailable = "Original image temporarily unavailable" if locale == "en" else "原文配图暂不可用"
    retry = "Retry source image" if locale == "en" else "重试原图"
    candidates = esc(json.dumps(media["image_candidates"], ensure_ascii=False, separators=(",", ":")))
    return f'<figure class="archive-figure" data-archive-media><img data-source-image src="{esc(image)}" data-image-candidates="{candidates}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer"><figcaption data-source-caption>{label} · <a href="{esc(safe_url(record.get("url")))}" target="_blank" rel="noopener noreferrer">{esc(record.get("source"))}</a></figcaption>{editorial_media(record, locale, hidden=True)}<p class="archive-media-unavailable" data-archive-media-fallback role="status" hidden>{unavailable}</p><button type="button" data-image-retry hidden>{retry}</button></figure>'


def safe_url(value):
    value = str(value or "")
    return value if normalize_source_url(value) else "#"


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


def archive_field_path(locale, domain, tag=None):
    path = f"/{locale}/archive/fields/{domain}/"
    return path + ("?" + urlencode({"tag": normalize_tag(tag)}) if tag else "")


def eligible_archive_record(record, now=None):
    """Invalid/future source dates must never create public discovery entries."""
    now = now or datetime.now(timezone.utc)
    for key in ("published", "source_published", "site_published", "first_seen_at"):
        value = record.get(key)
        if value is not None:
            try:
                if parse_datetime(value) > now:
                    return False
            except (TypeError, ValueError):
                return False
    return bool(record.get("published"))


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
    if record.get("date_basis") == "archive_date":
        date_label = "Archive date" if locale == "en" else "归档日期"
        date_markup = f'<time datetime="{published_local:%Y-%m-%d}">{published_local:%Y-%m-%d}</time>'
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
        "site_published": site_published, **image_fields(item),
        "importance": int(item.get("importance") or 0),
        "scores": {key: int(scores.get(key) or 0) for key in ("signal", "structure", "consequence", "confidence", "momentum")},
        "tags": tags,
        "evidence": item.get("evidence") or {}, "related_domains": item.get("related_domains") or [],
        "reading_context": item.get("reading_context") or {},
        "reading_context_meta": item.get("reading_context_meta") or {},
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
    for key in ("evidence", "related_domains", "reading_context", "reading_context_meta"):
        record[key] = enriched.get(key) or ([] if key == "related_domains" else {})
    record["date_basis"] = enriched.get("date_basis") or ("first_seen" if is_trending(record) else "source_published")
    record["first_seen_at"] = enriched.get("first_seen_at") if is_trending(record) else enriched.get("first_seen_at") or item["first_seen_at"]
    for locale in ("en", "zh"):
        record[locale]["summary"] = enriched[locale].get("summary") or record[locale]["summary"]
        record[locale]["full"] = enriched[locale].get("full_summary") or record[locale]["full"]
    record.update(image_fields(record))
    return record


def select_daily(records, now=None):
    grouped = defaultdict(list)
    for record in records:
        if not eligible_archive_record(record, now):
            continue
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


def preserve_archive_images(records, corpus_path):
    """Restore media only for existing ids bound to the same source article.

    Never restore removed articles, prose, scores or publication dates. This
    runs before the live feed merge, so newly verified candidates can replace
    prior media without requiring old stories to remain in the 48-hour brief.
    """
    if not corpus_path.is_file():
        return records
    try:
        payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return records
    previous = {str(item.get("id")): item for item in payload.get("items", [])
                if isinstance(item, dict) and item.get("id") is not None}
    for record in records:
        prior = previous.get(str(record.get("id")))
        if prior is not None:
            record.update(merge_image_fields(record, prior))
    return records


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
            if normalize_source_url(existing.get("url")) == normalize_source_url(record.get("url")):
                existing.update(merge_image_fields(record, existing))
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
    field_links = f'<a href="/{locale}/tech-news/">{"Tech News overview" if locale == "en" else "科技新闻总览"}</a>' + "".join(
        f'<a href="{field_path(locale, domain)}">{esc(item["label"][locale])}</a>'
        for domain, item in DOMAIN_REGISTRY.items()
    )
    current_path = urlparse(canonical).path
    fields_current = ' aria-current="page"' if f"/{locale}/fields/" in current_path else ""
    archive_current = ' aria-current="page"' if f"/{locale}/archive/" in current_path else ""
    body_class = ' class="archive-detail"' if og_type == "article" else ""
    media_script = '<script defer src="/archive-media.js?v=4"></script><script defer src="/archive-explore.js?v=1"></script>'
    return f'''<!doctype html>
<html lang="{c['lang']}" data-locale="{locale}"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<script defer src="/analytics.js?v=3"></script><script defer src="/share.js?v=20261109-1"></script><title>{esc(title)}</title>
<meta name="description" content="{esc(description)}"><meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large">
<link rel="canonical" href="{esc(canonical)}"><link rel="alternate" hreflang="{c['lang']}" href="{esc(canonical)}">
<link rel="alternate" hreflang="{COPY[other]['lang']}" href="{esc(alternate)}"><link rel="alternate" hreflang="x-default" href="{esc(canonical if locale == 'en' else alternate)}">
<link rel="alternate" type="application/rss+xml" title="{esc(c['brand'])} RSS" href="/feed-{locale}.xml">
<meta property="og:type" content="{esc(og_type)}"><meta property="og:site_name" content="{esc(c['brand'])}"><meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(description)}"><meta property="og:url" content="{esc(canonical)}"><meta property="og:image" content="{SITE}/assets/social-preview.png">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(title)}"><meta name="twitter:description" content="{esc(description)}"><meta name="twitter:image" content="{SITE}/assets/social-preview.png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/styles.css?v=20261114-2"><link rel="stylesheet" href="/archive.css?v=11">{media_script}{structured_html}</head>
<body{body_class}><header class="site-header"><a class="brand" href="/{locale}/" aria-label="{esc(c['brand'])}"><img src="/assets/{logo}" alt="{esc(c['brand'])}" width="420" height="70"></a>
<nav class="desktop-nav" aria-label="{'Primary' if locale == 'en' else '主导航'}"><a href="/{locale}/#fields"{fields_current}>{esc(c['fields'])}</a><a href="/{locale}/archive/"{archive_current}>{esc(c['archive'])}</a><a href="/{locale}/#about">{esc(c['method'])}</a></nav>
<div class="header-tools"><span class="edition">{esc(c['edition'])}</span><div class="language-switch"><a data-archive-locale href="{esc(alternate)}" hreflang="{COPY[other]['lang']}">{'中' if other == 'zh' else 'EN'}</a><span>|</span><a href="{esc(canonical)}" aria-current="page">{'中' if locale == 'zh' else 'EN'}</a></div></div></header>
<main class="archive-main">{body}</main><footer><div class="footer-brand"><img src="/assets/{logo}" alt="{esc(c['brand'])}" width="360"></div><div class="footer-copy"><p>{esc(c['footer'])}</p><p class="company-note">{esc(c['company'])}</p><p class="footer-meta">{esc(c['fields'])}</p><nav class="footer-topics" aria-label="{esc(c['fields'])}">{field_links}</nav><p class="footer-meta">{esc(c['angles'])}</p><nav class="footer-topics" aria-label="{esc(c['angles'])}">{topic_links}</nav><p class="footer-meta"><a href="/{locale}/standards/">{esc(c['standards'])}</a> · <a href="/{locale}/corrections/">{esc(c['corrections'])}</a> · <a href="/feed-{locale}.xml">{esc(c['feed'])}</a> · <a href="/developers/">API / MCP</a></p></div></footer></body></html>'''


def editorial_analysis(record, locale):
    """Describe stored scores, with no invented explanation or watch point."""
    # Do not present field-wide advice as an individual editorial assessment.
    why = ""
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
    watch = article_reading_context(record).get(locale, "")
    return why, signal, watch


def editorial_analysis_html(record, locale):
    if record["importance"] < 75:
        return ""
    _, signal, _ = editorial_analysis(record, locale)
    label = "About this score" if locale == "en" else "评分说明"
    return f'<aside class="editorial-analysis" aria-label="{label}"><div><h3>{label}</h3><p>{esc(signal)}</p></div></aside>'


def story_html(record, locale, detail=False):
    c = COPY[locale]
    text = record[locale]
    scores = record["scores"]
    source_published, first_seen = display_date(record)
    date_label = ("First seen" if locale == "en" else "首次发现") if first_seen else c["published"]
    published_local = source_published.astimezone(LOCAL_TZ) if source_published else None
    date_markup = f'<time datetime="{source_published.isoformat()}">{published_local:%Y-%m-%d %H:%M} SGT</time>' if source_published else ("Unknown" if locale == "en" else "时间未知")
    if record.get("date_basis") == "archive_date":
        date_label = "Archive date" if locale == "en" else "归档日期"
        date_markup = f'<time datetime="{published_local:%Y-%m-%d}">{published_local:%Y-%m-%d}</time>'
    tags = "".join(f'<a data-archive-tag href="{esc(archive_field_path(locale, record_domain(record), tag))}">{esc(tag)}</a>' for tag in record["tags"] if normalize_tag(tag))
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
    document_type = (record.get("evidence") or {}).get("type")
    type_label = evidence_labels[document_type][0 if locale == "en" else 1] if document_type in evidence_labels and document_type != "unknown" else content_type(record, locale)
    provenance = f'<div class="archive-story-meta archive-provenance"><a class="archive-source" href="{esc(safe_url(record["url"]))}" target="_blank" rel="noopener noreferrer">{esc(record["source"])} ↗</a><span class="archive-date"><span>{esc(date_label)}</span> {date_markup}</span><span class="archive-document-type">{esc(type_label)}</span><a class="archive-field" href="{field_path(locale, domain)}">{esc(field_label)}</a></div>'
    related = " × ".join(f'<a href="{field_path(locale, domain_id)}">{esc(DOMAIN_REGISTRY[domain_id]["label"][locale])}</a>' for domain_id in (record.get("related_domains") or [])[:2] if domain_id in DOMAIN_REGISTRY)
    context = article_reading_context(record).get(locale)
    context_html = f'<p class="story-context"><strong>{"Observation focus (editorial lens)" if locale == "en" else "观察重点（编辑视角）"}</strong> {esc(context)}</p>' if context else ""
    dek_html = ""
    if detail:
        dek, body = detail_dek(text, locale)
        dek_html = f'<p class="archive-dek">{esc(dek)}</p>' if dek else ""
        summary_html = archive_figure(record, locale) + archive_prose(body)
    else:
        summary_label = "Read full summary" if locale == "en" else "阅读完整摘要"
        summary_html = f'<p class="archive-summary">{esc(archive_excerpt(text, locale))}</p><a class="archive-summary-link" href="{article_path(locale, day, record)}">{summary_label} →</a>'
    screening = "View selection rationale" if locale == "en" else "查看筛选依据"
    share_button = f'''<button class="share-button" type="button" data-share-button data-share-id="{esc(record['id'])}" data-share-locale="{locale}" data-share-title="{esc(clean_text(text['title']))}" data-share-summary="{esc(share_summary)}" data-share-url="{share_url}" aria-label="{esc(c['share'])}: {esc(clean_text(text['title']))}"><svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="18" cy="5" r="2.5"/><circle cx="6" cy="12" r="2.5"/><circle cx="18" cy="19" r="2.5"/><path d="m8.2 10.8 7.6-4.5M8.2 13.2l7.6 4.5"/></svg><span>{esc(c['share'])}</span></button>'''
    screening_html = f'<details class="screening-details"><summary>{screening}</summary><div class="story-evidence">{evidence}</div>{context_html}<p>{esc(c["importance"])} {record["importance"]}/100</p><div class="archive-scores" aria-label="Polyemergence Method scores">{score_html}</div>{editorial_analysis_html(record, locale)}</details>' if record.get("scores_available", True) else ""
    return f'''<article class="archive-story" id="{anchor_for(record)}" data-story-id="{esc(record['id'])}">
<{heading}>{title_html}</{heading}>
{dek_html}{provenance}
<div class="story-related">{related}</div>{summary_html}
{screening_html}{trust_box(record, locale)}<div class="archive-story-footer"><div class="archive-tags">{tags}</div><div class="archive-actions">{share_button}<a class="archive-original" href="{esc(record['url'])}" target="_blank" rel="noopener noreferrer">{esc(c['original'])} ↗</a></div></div></article>'''


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


def archive_thumbnail(record, css_class, locale="en"):
    media = image_fields(record)
    image = safe_url(media["image_url"])
    if image == "#" or image == SITE + "/assets/social-preview.png":
        return f'<figure class="{css_class} is-editorial-visual">{editorial_media(record, locale, thumbnail=True)}</figure>'
    candidates = esc(json.dumps(media["image_candidates"], ensure_ascii=False, separators=(",", ":")))
    # Recommendation figures can be inside a link; no nested retry button.
    return f'<figure class="{css_class}" data-archive-media><img data-source-image src="{esc(image)}" data-image-candidates="{candidates}" alt="" loading="lazy" decoding="async" referrerpolicy="no-referrer">{editorial_media(record, locale, hidden=True, thumbnail=True)}<p data-archive-media-fallback hidden></p></figure>'


def continue_reading_html(record, records, locale):
    recommendations = related_articles(record, records)
    domain = record_domain(record)
    label = DOMAIN_REGISTRY[domain]["label"][locale]
    kinds = {
        "en": {"background": "Earlier coverage", "recent": "More recent coverage", "perspective": "Another source"},
        "zh": {"background": "了解背景", "recent": "较新相关报道", "perspective": "换个来源看"},
    }
    cards = []
    for pos, match in enumerate(recommendations):
        item = match["record"]
        day = item["published"].astimezone(LOCAL_TZ).date()
        date, first_seen = display_date(item)
        date_text = date.astimezone(LOCAL_TZ).strftime("%Y-%m-%d") if date else ("Date unknown" if locale == "en" else "时间未知")
        shared = " · ".join(match["shared_tags"][:2])
        reason = ("Shared topic: " if locale == "en" else "共同主题：") + shared
        cards.append(f'''<a class="archive-recommendation{' is-featured' if pos == 0 else ''}" href="{article_path(locale, day, item)}" data-related-kind="{esc(match['kind'])}" data-related-id="{esc(item['id'])}">{archive_thumbnail(item, 'archive-recommendation-image', locale)}<div class="archive-recommendation-copy"><p class="archive-card-meta">{esc(kinds[locale][match['kind']])} · {esc(date_text)}</p><h3>{esc(clean_text(item[locale]['title']))}</h3><p class="archive-card-reason">{esc(reason)}</p><span class="archive-card-source">{esc(item['source'])} →</span></div></a>''')
    title = "Keep exploring" if locale == "en" else "继续探索"
    intro = "Follow the topic, not just the headline." if locale == "en" else "顺着这条线索，看看它从哪里来，又走到了哪里。"
    browse = f"Explore the {label} archive" if locale == "en" else f"探索{label}历史报道"
    grid = f'<div class="archive-recommendations">{"".join(cards)}</div>' if cards else ""
    # Sparse archives still offer a useful domain-scoped route, without padding
    # the recommendation set with unrelated or cross-field headlines.
    return f'<section class="archive-continue" aria-labelledby="continue-reading"><div class="archive-continue-heading"><p class="section-index">POLYEMERGENCE / EXPLORE</p><h2 id="continue-reading">{title}</h2><p>{intro}</p></div>{grid}<a class="archive-summary-link" href="{archive_field_path(locale, domain)}">{esc(browse)} →</a></section>'


def render_article(output, locale, record, records=None):
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
    archive_label = "Historical brief" if locale == "en" else "历史简报"
    legacy_note = ('This page is retained as a historical record and is not part of the current curated selection.' if locale == 'en' else '此页作为历史记录保留，不属于当前精选内容。') if record.get("legacy_only") else ""
    note = f'<p class="archive-history-note">{archive_label} · {day.isoformat()}{" · " + esc(legacy_note) if legacy_note else ""}</p>'
    back = archive_field_path(locale, domain) if record.get("legacy_only") else archive_path(locale, day)
    body = f'''<nav class="archive-period-nav" aria-label="{'Article navigation' if locale == 'en' else '文章导航'}"><a href="{back}">← {day.isoformat() if not record.get("legacy_only") else esc(field_label)}</a><a href="{archive_field_path(locale, domain)}">{esc(field_label)}</a>{daily_link if not record.get("legacy_only") else ""}<a href="/{locale}/archive/">{esc(c['all'])}</a></nav>{note}<section class="archive-list archive-article-page">{story_html(record, locale, detail=True)}</section>{continue_reading_html(record, records or [], locale)}'''
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
    records = [record for day in ordered_days for record in grouped[day]]
    counts = Counter(record_domain(record) for record in records)
    field_cards = []
    for index, (domain, field) in enumerate(DOMAIN_REGISTRY.items(), 1):
        count = counts[domain]
        count_text = f"{count} stories" if locale == "en" else f"{count} 条历史报道"
        if not count:
            count_text = "Coverage coming soon" if locale == "en" else "等待首条报道"
        field_cards.append(f'<a class="archive-field-card" data-archive-field="{esc(domain)}" href="{archive_field_path(locale, domain)}"><span class="archive-field-index">{index:02d} /</span><h2>{esc(field["label"][locale])}</h2><p>{esc(field["description"][locale])}</p><span class="archive-field-count">{esc(count_text)} →</span></a>')
        render_archive_field(output, locale, domain, [record for record in records if record_domain(record) == domain])
    headline = "How we got here." if locale == "en" else "科技如何走到今天。"
    intro = "Choose a field. Follow a topic. Discover the stories behind the change." if locale == "en" else "先选一个领域，再顺着主题，找到变化的来路。"
    choose = "Choose your field" if locale == "en" else "从你关心的领域开始"
    by_date = "Browse by publication date" if locale == "en" else "按发布日期查找"
    body = f'<section class="archive-hero archive-hero-root archive-explore-hero"><p class="section-index">{esc(c["title"])}</p><h1>{headline}</h1><p>{intro}</p></section><section aria-labelledby="choose-field"><div class="archive-explore-intro"><h2 id="choose-field">{choose}</h2><p>{len(records)} {esc(c["stories"])} · {len(DOMAIN_REGISTRY)} {"fields" if locale == "en" else "个领域"}</p></div><div class="archive-field-grid">{"".join(field_cards)}</div></section><details class="archive-date-browser"><summary>{by_date}</summary><section class="archive-months"><h2>{esc(c["months"])}</h2><div>{"".join(month_cards)}</div></section></details>'
    path = output / locale / "archive" / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{c['title']} | {c['brand']}", c["intro"], canonical, alternate, body), encoding="utf-8")


def render_archive_field(output, locale, domain, records):
    """Small static field collections: no public-corpus download or tag pages."""
    other = "zh" if locale == "en" else "en"
    field = DOMAIN_REGISTRY[domain]
    label = field["label"][locale]
    ordered = sorted(records, key=lambda item: (display_date(item)[0] or item["published"], item["importance"], str(item["id"])), reverse=True)
    canonical = SITE + archive_field_path(locale, domain)
    alternate = SITE + archive_field_path(other, domain)
    title = f"{label} Archive" if locale == "en" else f"{label}历史报道"
    description = f"Explore {label} coverage by topic, keyword and publication date." if locale == "en" else f"按主题、关键词和发布时间探索{label}历史报道。"
    chips = "".join(f'<a data-archive-tag href="{esc(archive_field_path(locale, domain, topic["tag"]))}">{esc(topic["label"])} <span>{topic["count"]}</span></a>' for topic in topic_labels(ordered))
    months = sorted({(display_date(record)[0] or record["published"]).astimezone(LOCAL_TZ).strftime("%Y-%m") for record in ordered}, reverse=True)
    options = "".join(f'<option value="{month}">{month}</option>' for month in months)
    cards = []
    for pos, record in enumerate(ordered):
        day = record["published"].astimezone(LOCAL_TZ).date()
        published, first_seen = display_date(record)
        date = published.astimezone(LOCAL_TZ) if published else None
        month = date.strftime("%Y-%m") if date else ""
        excerpt = archive_excerpt(record[locale], locale)
        excerpt = excerpt[:180 if locale == "en" else 95].rstrip() + ("…" if len(excerpt) > (180 if locale == "en" else 95) else "")
        tags = [normalize_tag(tag) for tag in record["tags"] if normalize_tag(tag)]
        search = " ".join([record[locale]["title"], record[locale]["summary"], record["source"], *record["tags"]])
        date_text = date.strftime("%Y-%m-%d") if date else ("Date unknown" if locale == "en" else "时间未知")
        date_text = (("First seen " if locale == "en" else "首次发现 ") if first_seen else "") + date_text
        cards.append(f'''<article class="archive-explore-card{' is-featured' if pos == 0 else ''}" data-archive-entry data-search="{esc(search)}" data-tags="{esc(json.dumps(tags, ensure_ascii=False))}" data-month="{month}">{archive_thumbnail(record, 'archive-explore-image', locale)}<div class="archive-explore-copy"><p class="archive-card-meta">{esc(date_text)} · {esc(record['source'])}</p><h2><a href="{article_path(locale, day, record)}">{esc(clean_text(record[locale]['title']))}</a></h2><p class="archive-card-excerpt">{esc(excerpt)}</p><a class="archive-summary-link" href="{article_path(locale, day, record)}">{'Read the brief' if locale == 'en' else '阅读简报'} →</a></div></article>''')
    search_label = "Search this field" if locale == "en" else "在此领域内搜索"
    month_label = "Publication month" if locale == "en" else "发布月份"
    all_months = "All months" if locale == "en" else "全部月份"
    reset = "Clear filters" if locale == "en" else "清除筛选"
    all_fields = "Choose another field" if locale == "en" else "选择其他领域"
    body = f'''<section class="archive-hero archive-explore-hero"><p class="section-index">{COPY[locale]['archive']}</p><h1>{esc(label)}</h1><p>{esc(description)}</p></section><nav class="archive-period-nav"><a href="/{locale}/archive/">← {all_fields}</a><a href="{field_path(locale, domain)}">{'Latest coverage' if locale == 'en' else '最新简报'} →</a></nav><section class="archive-browser" data-archive-browser><form class="archive-controls" data-archive-filters action="{archive_field_path(locale, domain)}" method="get"><label>{search_label}<input type="search" name="q" placeholder="{search_label}" maxlength="160" autocomplete="off"></label><label>{month_label}<select name="month"><option value="">{all_months}</option>{options}</select></label><input type="hidden" name="tag" value=""><button type="submit">{'Search' if locale == 'en' else '搜索'}</button><button type="button" data-archive-reset>{reset}</button></form><nav class="archive-topic-links" aria-label="{'Explore recurring topics' if locale == 'en' else '探索已有主题'}">{chips}</nav><p class="archive-results-count" data-archive-count aria-live="polite" aria-atomic="true">{len(ordered)} {'stories' if locale == 'en' else '条历史报道'}</p><p class="archive-filter-note">{'Topics link related coverage, not verified causal connections.' if locale == 'en' else '主题关联用于发现相关报道，不代表已证实的因果关系。'}</p><div class="archive-explore-list">{"".join(cards)}</div><p data-archive-empty {'hidden' if ordered else ''}>{'No matching stories yet. Clear filters or choose another field.' if locale == 'en' else '暂无符合条件的报道，可清除筛选或选择其他领域。'}</p><button type="button" class="archive-load-more" data-archive-more hidden>{'Show more stories' if locale == 'en' else '查看更多报道'}</button></section>'''
    structured = {"@context": "https://schema.org", "@type": "CollectionPage", "name": title, "description": description, "url": canonical, "inLanguage": COPY[locale]["lang"], "mainEntity": {"@type": "ItemList", "numberOfItems": len(ordered), "itemListElement": [{"@type": "ListItem", "position": index, "url": SITE + article_path(locale, item["published"].astimezone(LOCAL_TZ).date(), item), "name": clean_text(item[locale]["title"])} for index, item in enumerate(ordered, 1)]}}
    path = output / archive_field_path(locale, domain).lstrip("/") / "index.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page_shell(locale, f"{title} | {COPY[locale]['brand']}", description, canonical, alternate, body, structured), encoding="utf-8")


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
    for domain in DOMAIN_REGISTRY:
        field_records = [record for items in grouped.values() for record in items if record_domain(record) == domain]
        if not field_records:
            continue  # Empty fields remain accessible, not indexed as thin pages.
        lastmod = max(record["site_published"] for record in field_records).date().isoformat()
        for current_locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = SITE + archive_field_path(current_locale, domain)
            ET.SubElement(node, f"{{{namespace}}}lastmod").text = lastmod
            for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": SITE + archive_field_path(locale, domain)})
    for page in ("standards", "corrections"):
        for current_locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{namespace}}}url")
            ET.SubElement(node, f"{{{namespace}}}loc").text = f"{SITE}/{current_locale}/{page}/"
            ET.SubElement(node, f"{{{namespace}}}lastmod").text = latest_day.isoformat()
            for lang, locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{xhtml}}}link", {"rel": "alternate", "hreflang": lang, "href": f"{SITE}/{locale}/{page}/"})
    ET.ElementTree(root).write(output / "archive-sitemap.xml", encoding="utf-8", xml_declaration=True)


def render_news_sitemap(output, grouped, now=None):
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    news = "http://www.google.com/schemas/sitemap-news/0.9"
    ET.register_namespace("", namespace)
    ET.register_namespace("news", news)
    root = ET.Element(f"{{{namespace}}}urlset")
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=2)
    recent = sorted(
        (record for items in grouped.values() for record in items if cutoff <= record["site_published"] <= now and not is_trending(record) and eligible_archive_record(record, now)),
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
            **image_fields(record),
            "tags": record["tags"],
            "evidence": record.get("evidence") or {}, "related_domains": record.get("related_domains") or [],
            "reading_context": record.get("reading_context") or {},
            "reading_context_meta": record.get("reading_context_meta") or {},
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


class LegacyArticleReader(HTMLParser):
    """Read only published prose/metadata; never execute or reuse old HTML."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.prose, self.paragraphs, self.dek, self.source = [], [], [], []
        self.provenance_times, self.date_labels = [], []
        self.image_candidates = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set(attrs.get("class", "").split())
        in_article = any("archive-story" in node[1] for node in self.stack)
        if in_article and tag == "img" and "data-editorial-image" not in attrs:
            values = [attrs.get("src")]
            try:
                stored = json.loads(attrs.get("data-image-candidates", "[]"))
                if isinstance(stored, list):
                    values.extend(stored)
            except (ValueError, TypeError):
                pass
            for value in values:
                if normalize_source_url(value) and value not in self.image_candidates:
                    self.image_candidates.append(value)
                    if len(self.image_candidates) >= 3:
                        break
        if in_article and tag == "time" and attrs.get("datetime") and any("archive-provenance" in node[1] for node in self.stack):
            self.provenance_times.append(attrs["datetime"])
        mode = None
        if in_article:
            if "archive-dek" in classes or any(node[2] == "dek" for node in self.stack):
                mode = "dek"
            elif "archive-prose" in classes or any(node[2] == "prose" for node in self.stack):
                mode = "prose"
            elif tag == "p" and self.stack[-1][0] == "article" and "archive-dek" not in classes:
                mode = "paragraph"
            elif any(node[2] == "paragraph" for node in self.stack):
                mode = "paragraph"
            elif "archive-source" in classes:
                mode = "source"
        if tag not in {"br", "img", "hr", "input", "meta", "link", "source", "wbr"}:
            self.stack.append((tag, classes, mode))
        if tag in {"p", "h2", "h3", "li", "br"}:
            self._append("\n\n" if tag != "li" else "\n• ")

    def handle_endtag(self, tag):
        if tag in {"p", "h2", "h3", "li", "pre"}:
            self._append("\n\n")
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                self.stack = self.stack[:index]
                break

    def _append(self, data):
        modes = {node[2] for node in self.stack}
        if "prose" in modes:
            self.prose.append(data)
        elif "dek" in modes:
            self.dek.append(data)
        elif "paragraph" in modes:
            self.paragraphs.append(data)
        elif "source" in modes:
            self.source.append(data)

    def handle_data(self, data):
        if any("archive-date" in node[1] for node in self.stack):
            self.date_labels.append(data)
        self._append(data)


def retained_snapshot(page):
    snapshot = re.search(r'<script type="application/json" id="archive-retained-snapshot">(.*?)</script>', page, re.S)
    if snapshot:
        try:
            value = json.loads(snapshot[1]).get("html")
            if isinstance(value, str):
                return value
        except (ValueError, TypeError, AttributeError):
            pass
    return page


def legacy_record(path, locale):
    """Migrate retained URLs without resurrecting them into curated exports."""
    page = retained_snapshot(path.read_text(encoding="utf-8"))
    match = re.search(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    if not match:
        return None
    try:
        schema = json.loads(match[1])
        if schema.get("@type") != "NewsArticle":
            return None
        reader = LegacyArticleReader()
        reader.feed(page)
        # Resolve date from the already-public URL, not a fresh export date.
        year, month, day, identifier = path.parts[-5:-1]
        published = datetime(int(year), int(month), int(day), tzinfo=LOCAL_TZ).astimezone(timezone.utc)
        site_published = parse_datetime(schema.get("datePublished") or published)
        source_published = None
        basis = "archive_date"
        date_label = " ".join(reader.date_labels).casefold()
        if reader.provenance_times and ("source published" in date_label or "原文发布时间" in date_label):
            source_published = parse_datetime(reader.provenance_times[0])
            basis = "source_published"
        domain_url = (schema.get("about") or {}).get("url", "") if isinstance(schema.get("about"), dict) else ""
        domain = domain_url.rstrip("/").rsplit("/", 1)[-1]
        tags = parse_tags(schema.get("keywords"))
        title = schema.get("headline") or ""
        category = normalize_category(schema.get("articleSection"), title, "", tags)
        if domain not in DOMAIN_REGISTRY:
            domain = infer_domain(category, None, " ".join([title, *tags]))
        lead = "".join(reader.dek).strip()
        full = "".join(reader.prose or reader.paragraphs).strip()
        # The displayed lede can contain the only copy of a short brief, or
        # facts absent from the body. Never replace it with truncated SEO text.
        if lead and not re.sub(r"\s+", " ", full).startswith(re.sub(r"\s+", " ", lead)):
            full = lead + ("\n\n" + full if full else "")
        full = full or schema.get("description", "")
        source_url = safe_url(schema.get("isBasedOn"))
        source = "".join(reader.source).replace("↗", "").strip() or (urlparse(source_url).hostname or "Original source")
        image = schema.get("image", [])
        image = image[0] if isinstance(image, list) and image else image if isinstance(image, str) else "#"
        if image == SITE + "/assets/social-preview.png":
            image = "#"
        media = image_fields({"url": source_url, "image_url": image, "image_candidates": reader.image_candidates})
        text = {"title": title, "summary": lead or schema.get("description") or full, "full": full}
        return {"id": identifier, "url": source_url, "source": source, "category": category, "domain": domain,
                "published": published, "source_published": source_published, "site_published": site_published, "date_basis": basis,
                **media, "importance": 0,
                "scores": {key: 0 for key in ("signal", "structure", "consequence", "confidence", "momentum")},
                "scores_available": False, "tags": tags, "en": dict(text), "zh": dict(text), "legacy_only": True}
    except (ValueError, KeyError, TypeError, AttributeError):
        return None


def render_date_notice(output, locale, relative_path, now=None):
    """Keep a suspect old URL accessible, but out of indexes and search results."""
    canonical = SITE + "/" + relative_path.as_posix().removesuffix("index.html")
    other = "zh" if locale == "en" else "en"
    alternate = canonical.replace(f"/{locale}/", f"/{other}/", 1)
    title = "Publication date under review" if locale == "en" else "发布时间待核对"
    explanation = "This archived URL contained a future publication date. It has been removed from discovery while the date is checked; it is not a new report." if locale == "en" else "此归档链接的发布时间晚于当前时间，已暂时从归档列表与推荐中隐藏，等待日期核对；这不是一条新发布的报道。"
    original = retained_snapshot((output / relative_path).read_text(encoding="utf-8"))
    # Preserve the complete prior document inertly, including prose and source
    # metadata. It can be migrated when the date is valid; never erase history.
    snapshot = f'<script type="application/json" id="archive-retained-snapshot">{json_ld({"html": original})}</script>'
    body = f'<section class="archive-hero archive-explore-hero"><p class="section-index">{COPY[locale]["archive"]}</p><h1>{title}</h1><p>{explanation}</p></section><a class="archive-summary-link" href="/{locale}/archive/">{COPY[locale]["all"]} →</a>{snapshot}'
    page = page_shell(locale, title + " | Polyemergence", explanation, canonical, alternate, body)
    page = page.replace('content="index,follow,max-snippet:-1,max-image-preview:large"', 'content="noindex,follow"')
    (output / relative_path).write_text(page, encoding="utf-8")


def refresh_retained_pages(output, records, now=None):
    """Upgrade old retained prose without adding removed stories to any feed."""
    now = now or datetime.now(timezone.utc)
    current_paths = {article_path(locale, record["published"].astimezone(LOCAL_TZ).date(), record)
                     for record in records for locale in ("en", "zh")}
    upgraded = withheld = 0
    for locale in ("en", "zh"):
        for path in sorted((output / locale / "archive").glob("[0-9][0-9][0-9][0-9]/[0-9][0-9]/**/index.html")):
            relative = path.relative_to(output)
            parts = relative.parts
            if len(parts) < 5:
                continue
            year, month = int(parts[2]), int(parts[3])
            day = int(parts[4]) if len(parts) >= 6 else 1
            try:
                future_path = datetime(year, month, day, tzinfo=LOCAL_TZ) > now
            except ValueError:
                future_path = True
            if future_path:
                render_date_notice(output, locale, relative, now)
                withheld += 1
                continue
            if len(parts) != 7 or "/" + relative.as_posix().removesuffix("index.html") in current_paths:
                continue
            record = legacy_record(path, locale)
            if not record:
                continue
            if not eligible_archive_record(record, now):
                render_date_notice(output, locale, relative, now)
                withheld += 1
                continue
            render_article(output, locale, record, records)
            upgraded += 1
        daily_slug = "daily-ai-news" if locale == "en" else "ai-news-daily"
        for path in sorted((output / locale / daily_slug).glob("*/index.html")):
            try:
                day = datetime.strptime(path.parent.name, "%Y-%m-%d").replace(tzinfo=LOCAL_TZ)
            except ValueError:
                continue
            if day > now:
                render_date_notice(output, locale, path.relative_to(output), now)
                withheld += 1
    return upgraded, withheld


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="web/public")
    parser.add_argument("--input-json", help="Use a public feed fixture instead of PostgreSQL")
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    records = merge_current_feed(
        preserve_archive_images(load_json(args.input_json) if args.input_json else load_database(),
                                output / "data" / "articles.json"),
        output / "data" / "latest.json",
    )
    records = preserve_trending_history(records, output / "data" / "articles.json")
    grouped = select_daily(records)
    if not grouped:
        raise SystemExit("No eligible archive records")
    ordered_days = sorted(grouped, reverse=True)
    all_records = [record for day in ordered_days for record in grouped[day]]
    for locale in ("en", "zh"):
        render_indexes(output, locale, grouped)
        for day in ordered_days:
            render_daily(output, locale, day, grouped[day], ordered_days)
            render_daily_brief(output, locale, day, grouped[day])
            for record in grouped[day]:
                render_article(output, locale, record, all_records)
        for category in CATEGORY_ORDER:
            render_topic(output, locale, category, [
                record for record in all_records
                if (record.get("domain") == "programmable_life" if category == "biotech" else record["category"] == category)
            ])
        render_rss(output, locale, grouped)
    render_public_data(output, [record for day in ordered_days for record in grouped[day]])
    render_sitemap(output, grouped)
    render_news_sitemap(output, grouped)
    upgraded, withheld = refresh_retained_pages(output, all_records)
    print(f"Generated {len(grouped)} daily archives containing {sum(map(len, grouped.values()))} stories")
    print(f"Updated {upgraded} retained article pages; withheld {withheld} future-dated URLs (no deletions)")


if __name__ == "__main__":
    main()
