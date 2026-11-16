"""Pure public weekly-edition SSR, with no collection or publishing effects."""

from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from html import escape
import json
import re

from source_images import normalize_source_url


SITE = "https://polyemergence.com"
SGT = timezone(timedelta(hours=8))
COPY = {
    "en": {
        "lang": "en", "brand": "Polyemergence", "home": "Fields", "weekly": "Weekly", "archive": "Archive", "method": "Method", "feedback": "Feedback",
        "skip": "Skip to content", "navigation": "Primary navigation", "language": "Change language",
        "index_title": "The Polyemergence Weekly", "index_dek": "Explore our weekly editions on emerging technologies, with editorial interpretation, original sources and uncertainty kept in view.",
        "issue_title": "Polyemergence Weekly", "ai": "AI-assisted weekly", "period": "Coverage period",
        "published": "Weekly edition published", "modified": "Updated", "timezone": "Time zone",
        "latest": "Latest edition", "history": "Earlier editions", "read": "Read this edition", "all": "All weekly editions",
        "no_editions": "No weekly editions have been published here yet.", "no_history": "This is the first available edition.",
        "missing": "Not provided", "untitled": "Title not provided", "empty": "No entries were supplied for this section.",
        "synthesis": "What this selection suggests", "signal": "Signals worth noticing", "structure": "How the landscape may change",
        "consequence": "What it could mean for readers", "limits": "What we cannot conclude yet",
        "scope": "Editorial interpretation of this selection, not an industry-wide measurement or a certain forecast.",
        "insufficient": "Insufficient evidence in this selection", "interpretation_sources": "Sources for this interpretation",
        "lead": "This week's selection", "main": "Main events", "signals": "Signals to watch",
        "signals_note": "These are leads to examine, not established trends or a maturity classification.",
        "what": "What changed · reported facts", "why": "Why it matters · editorial judgment", "uncertainty": "Uncertainty and unverified points",
        "uncertainty_missing": "No uncertainty statement was supplied. This does not establish certainty.",
        "sources": "Sources and archived briefs", "source_missing": "This reference was not found in the supplied source catalog",
        "no_sources": "No traceable source references were supplied for this passage.", "source": "Source", "source_published": "Original publication",
        "domain": "Field", "original": "Read original", "archived": "Archived brief", "unsafe_original": "Original link unavailable or unsafe", "unsafe_archive": "Archive link unavailable or unsafe", "supplement_no_archive": "Supplementary source; no site archive",
        "follow": "Historical follow-up", "follow_available": "Historical comparisons supplied", "follow_unavailable": "No historical comparison available for this edition",
        "follow_unknown": "Historical-comparison availability was not specified", "watch": "What to watch next",
        "coverage": "Selection coverage", "qualified": "Qualified items", "selected": "Selected items",
        "coverage_note": "These counts describe the supplied selection, not industry activity or momentum.",
        "process": "How this was produced", "process_note": "AI-assisted synthesis based on existing news summaries. This page does not claim human editorial review or independent fact-checking. Reported facts remain attributed to the linked sources; interpretations and uncertainty are identified separately.",
        "publisher": "Published by PolyEmergence Pte Ltd., Singapore.", "standards": "Editorial standards", "corrections": "Corrections",
    },
    "zh": {
        "lang": "zh-Hans", "brand": "多重涌现", "home": "领域", "weekly": "周报", "archive": "归档", "method": "方法", "feedback": "反馈",
        "skip": "跳到正文", "navigation": "主导航", "language": "切换语言",
        "index_title": "多重涌现科技周报", "index_dek": "按周梳理新兴科技进展，保留编辑解读、原始出处与尚未确定的边界。",
        "issue_title": "多重涌现科技周报", "ai": "AI 辅助周报", "period": "选材周期",
        "published": "周报发布时间", "modified": "更新于", "timezone": "时区",
        "latest": "最新一期", "history": "往期周报", "read": "阅读本期", "all": "全部周报",
        "no_editions": "这里暂未发布周报。", "no_history": "这是目前可阅读的第一期。",
        "missing": "未提供", "untitled": "标题未提供", "empty": "本节未提供具体条目。",
        "synthesis": "这周看出了什么", "signal": "值得留意的信号", "structure": "可能改变的格局",
        "consequence": "对读者意味着什么", "limits": "还不能确定什么",
        "scope": "基于本期选材的编辑解读，不代表全行业统计或确定预测。",
        "insufficient": "现有选材不足以支持这一判断", "interpretation_sources": "本段依据",
        "lead": "本周选材主线", "main": "主要事件", "signals": "值得跟踪的信号",
        "signals_note": "这些条目是待观察线索，不代表已经形成行业趋势，也不据此判定技术成熟度。",
        "what": "发生了什么 · 事实摘要", "why": "为何重要 · 编辑判断", "uncertainty": "未验证事项与不确定性",
        "uncertainty_missing": "未提供不确定性说明；这不代表不存在不确定性。",
        "sources": "出处与归档摘要", "source_missing": "提供的来源目录中未找到此引用",
        "no_sources": "此段未提供可追溯的来源引用。", "source": "来源", "source_published": "原文发布时间",
        "domain": "领域", "original": "阅读原文", "archived": "本站归档摘要", "unsafe_original": "原文链接不可用或不安全", "unsafe_archive": "归档链接不可用或不安全", "supplement_no_archive": "补充来源，尚无本站归档",
        "follow": "历史跟踪", "follow_available": "已提供历史对照", "follow_unavailable": "本期暂无可用历史对照",
        "follow_unknown": "是否具备历史对照尚未说明", "watch": "接下来关注什么",
        "coverage": "本期选材覆盖", "qualified": "合格候选数", "selected": "入选数",
        "coverage_note": "这些计数仅描述本期选材，不代表行业热度或发展速度。",
        "process": "制作与核验说明", "process_note": "本周报使用 AI 辅助综合已有新闻摘要，不声称已经过人工编辑审阅或独立事实核查。事实摘要保留来源归属，编辑判断与不确定性分别列明；请通过所列原文核实。",
        "publisher": "发布主体：PolyEmergence Pte Ltd.，新加坡。", "standards": "编辑标准", "corrections": "纠错记录",
    },
}


def _obj(value):
    return value if isinstance(value, Mapping) else {}


def _text(value, default=""):
    return value.strip() if isinstance(value, str) and value.strip() else default


def _esc(value):
    return escape(str(value), quote=True)


def _rows(value):
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, (list, tuple)) else []


def _locale(locale):
    if locale not in COPY:
        raise ValueError("locale must be en or zh")
    return locale


def _edition_id(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("weekly edition id must be YYYY-MM-DD")
    date.fromisoformat(value)
    return value


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(_text(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo is not None else None
    except (TypeError, ValueError, OverflowError):
        return None


def _date(value, locale):
    try:
        return date.fromisoformat(_text(value)[:10]).isoformat()
    except (ValueError, TypeError):
        return COPY[locale]["missing"]


def _time(value, locale):
    parsed = _timestamp(value)
    return parsed.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT") if parsed else COPY[locale]["missing"]


def _period(payload, locale):
    return _date(payload.get("week_start"), locale) + " — " + _date(payload.get("week_end"), locale)


def _path(locale, identifier=None):
    return f"/{locale}/weekly/" + (identifier + "/" if identifier else "")


def _json_ld(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _sources_index(payload):
    result = {}
    for row in _rows(payload.get("sources")):
        identifier = _text(row.get("id"))
        if identifier and identifier not in result:
            result[identifier] = row
    return result


def _source_time(row, locale):
    value = row.get("published_at")
    precision = _text(row.get("date_precision")).lower()
    if precision in {"day", "date", "day_only"} or re.fullmatch(r"\d{4}-\d{2}-\d{2}", _text(value)):
        return _date(value, locale)
    return _time(value, locale)


def _evidence(value):
    return list(dict.fromkeys(identifier for raw in value if (identifier := _text(raw)))) if isinstance(value, (list, tuple)) else []


def _source_notes(ids, sources, locale, interpretation=False):
    c = COPY[locale]
    rows = []
    for identifier in _evidence(ids):
        row = sources.get(identifier)
        if row is None:
            rows.append(f'<li class="weekly-missing">{c["source_missing"]}: <code>{_esc(identifier)}</code></li>')
            continue
        title = _text(_obj(row.get(locale)).get("title"), c["untitled"])
        domain = _text(_obj(row.get("domain_labels")).get(locale), _text(row.get("domain"), c["missing"]))
        links = []
        for key, label, missing in (("url", "original", "unsafe_original"), ("archive_url_" + locale, "archived", "unsafe_archive")):
            raw_url = row.get(key)
            url = normalize_source_url(raw_url)
            absent_archive = key.startswith("archive_url_") and (raw_url is None or isinstance(raw_url, str) and not raw_url.strip())
            note = c["supplement_no_archive"] if absent_archive else c[missing]
            links.append(f'<a href="{_esc(url)}" target="_blank" rel="noopener noreferrer">{c[label]}</a>' if url else f'<span class="weekly-missing">{note}</span>')
        rows.append(f'<li><span class="weekly-source-title">{_esc(title)}</span><span class="weekly-source-meta">{c["source"]}: {_esc(_text(row.get("source"), c["missing"]))} · {c["source_published"]}: {_esc(_source_time(row, locale))} · {c["domain"]}: {_esc(domain)}</span><div class="weekly-source-links">{"".join(links)}</div></li>')
    body = '<ol>' + "".join(rows) + '</ol>' if rows else f'<p class="weekly-missing">{c["no_sources"]}</p>'
    summary = c["interpretation_sources"] if interpretation else c["sources"]
    return f'<details class="weekly-sources"><summary>{summary}</summary>{body}</details>'


def _synthesis(content, sources, locale):
    c = COPY[locale]
    synthesis = _obj(content.get("synthesis"))
    points = []
    for dimension in ("signal", "structure", "consequence"):
        point = _obj(synthesis.get(dimension))
        title = _text(point.get("title"))
        title_html = f'<h4>{_esc(title)}</h4>' if title else ""
        support = f'<p class="weekly-insufficient" role="note">{c["insufficient"]}</p>' if point.get("support") == "insufficient" else ""
        points.append(f'<div class="weekly-synthesis-point"><h3>{c[dimension]}</h3>{title_html}{support}<p>{_esc(_text(point.get("text"), c["missing"]))}</p>{_source_notes(point.get("evidence_ids"), sources, locale, True)}</div>')
    overall_sources = _source_notes(synthesis.get("evidence_ids"), sources, locale, True) if _evidence(synthesis.get("evidence_ids")) else ""
    return f'<section class="weekly-synthesis" id="weekly-insights" aria-labelledby="weekly-insights-title"><h2 id="weekly-insights-title">{c["synthesis"]}</h2><p class="weekly-section-note">{c["scope"]}</p><p class="weekly-synthesis-intro">{_esc(_text(synthesis.get("intro"), c["missing"]))}</p>{"".join(points)}<div class="weekly-limits"><strong>{c["limits"]}</strong><p>{_esc(_text(synthesis.get("limits"), c["uncertainty_missing"]))}</p></div>{overall_sources}</section>'


def _event(event, sources, locale):
    c = COPY[locale]
    parts = []
    for key, label in (("what_changed", "what"), ("why_it_matters", "why"), ("uncertainty", "uncertainty")):
        fallback = c["uncertainty_missing"] if key == "uncertainty" else c["missing"]
        parts.append(f'<div class="weekly-event-{key}"><strong class="weekly-reading-label">{c[label]}</strong><p>{_esc(_text(event.get(key), fallback))}</p></div>')
    return f'<article class="weekly-event"><h3>{_esc(_text(event.get("title"), c["untitled"]))}</h3>{"".join(parts)}{_source_notes(event.get("evidence_ids"), sources, locale)}</article>'


def _coverage(payload, locale):
    c = COPY[locale]
    coverage = payload.get("coverage")
    fields = _rows(_obj(coverage).get("fields")) if isinstance(coverage, Mapping) else _rows(coverage)
    if not fields:
        return ""
    rows = []
    for field in fields:
        label = _text(_obj(field.get("domain_labels")).get(locale), _text(field.get("domain"), c["missing"]))
        counts = [str(value) if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else c["missing"]
                  for value in (field.get("qualified_count"), field.get("selected_count"))]
        rows.append(f'<tr><th scope="row">{_esc(label)}</th><td>{counts[0]}</td><td>{counts[1]}</td></tr>')
    return f'<details class="weekly-coverage"><summary>{c["coverage"]}</summary><p class="weekly-section-note">{c["coverage_note"]}</p><div class="weekly-table-wrap"><table><thead><tr><th scope="col">{c["domain"]}</th><th scope="col">{c["qualified"]}</th><th scope="col">{c["selected"]}</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></details>'


def _shell(locale, title, description, body, schema, identifier=None):
    c = COPY[locale]
    other = "zh" if locale == "en" else "en"
    canonical = SITE + _path(locale, identifier)
    alternate = SITE + _path(other, identifier)
    logo = f"/assets/logo-{locale}-reverse.svg"
    nav = f'<nav class="weekly-nav" aria-label="{c["navigation"]}"><a href="/{locale}/#fields">{c["home"]}</a><a href="/{locale}/weekly/" aria-current="page">{c["weekly"]}</a><a href="/{locale}/archive/">{c["archive"]}</a><a href="/{locale}/#about">{c["method"]}</a><a href="/{locale}/#feedback">{c["feedback"]}</a></nav>'
    return f'''<!doctype html>
<html lang="{c['lang']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{_esc(title)} | {_esc(c['brand'])}</title><meta name="description" content="{_esc(description)}"><meta name="robots" content="index,follow,max-snippet:-1,max-image-preview:large"><link rel="canonical" href="{canonical}"><link rel="alternate" hreflang="en" href="{SITE + _path('en', identifier)}"><link rel="alternate" hreflang="zh-Hans" href="{SITE + _path('zh', identifier)}"><link rel="alternate" hreflang="x-default" href="{SITE + _path('en', identifier)}"><meta property="og:type" content="{'article' if identifier else 'website'}"><meta property="og:site_name" content="Polyemergence"><meta property="og:title" content="{_esc(title)}"><meta property="og:description" content="{_esc(description)}"><meta property="og:url" content="{canonical}"><meta property="og:locale" content="{'zh_CN' if locale == 'zh' else 'en_US'}"><meta property="og:image" content="{SITE}/assets/social-preview.png"><meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{_esc(title)}"><meta name="twitter:description" content="{_esc(description)}"><meta name="twitter:image" content="{SITE}/assets/social-preview.png"><link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="stylesheet" href="/weekly.css?v=1"><script defer src="/analytics.js?v=2"></script><script type="application/ld+json">{_json_ld(schema)}</script></head>
<body class="weekly-public"><a class="weekly-skip" href="#main">{c['skip']}</a><header class="weekly-header"><a class="weekly-brand" href="/{locale}/" aria-label="{_esc(c['brand'])}"><img src="{logo}" alt="{_esc(c['brand'])}" width="420" height="70"></a>{nav}<a class="weekly-language" href="{alternate}" hreflang="{COPY[other]['lang']}" aria-label="{c['language']}">{'中' if other == 'zh' else 'EN'}</a></header>
<main id="main" class="weekly-main">{body}</main><footer class="weekly-footer"><p>{c['publisher']}</p><p><a href="/{locale}/standards/">{c['standards']}</a> · <a href="/{locale}/corrections/">{c['corrections']}</a> · <a href="/{locale}/weekly/">{c['all']}</a></p></footer></body></html>'''


def render_weekly_issue(payload, locale):
    """Render a public issue without changing payload or performing any I/O."""
    locale = _locale(locale)
    payload = _obj(payload)
    identifier = _edition_id(payload.get("id"))
    c, content = COPY[locale], _obj(payload.get(locale))
    sources = _sources_index(payload)
    title = _text(content.get("title"), c["issue_title"])
    description = _text(content.get("dek"))
    published = _timestamp(payload.get("published_at"))
    modified = _timestamp(payload.get("modified_at"))
    metadata = f'<p><strong>{c["period"]}</strong> {_esc(_period(payload, locale))} · {_esc(_text(payload.get("timezone"), c["missing"]))}</p><p><strong>{c["published"]}</strong> {_esc(_time(payload.get("published_at"), locale))}</p>'
    if modified and published and modified > published:
        metadata += f'<p><strong>{c["modified"]}</strong> {_esc(_time(payload.get("modified_at"), locale))}</p>'
    intro = f'<nav class="weekly-breadcrumb"><a href="/{locale}/weekly/">← {c["all"]}</a></nav><header class="weekly-issue-header"><p class="weekly-eyebrow">{c["ai"]}</p><h1>{_esc(title)}</h1><p class="weekly-dek">{_esc(description)}</p><div class="weekly-issue-meta">{metadata}</div></header>'
    body = [intro, _synthesis(content, sources, locale)]
    lead = _obj(content.get("lead"))
    if _text(lead.get("text")):
        body.append(f'<section class="weekly-section"><h2>{c["lead"]}</h2><p class="weekly-lead">{_esc(lead["text"])}</p>{_source_notes(lead.get("evidence_ids"), sources, locale)}</section>')
    for key, label in (("main_events", "main"), ("early_signals", "signals")):
        rows = _rows(content.get(key))
        note = f'<p class="weekly-section-note">{c["signals_note"]}</p>' if key == "early_signals" else ""
        items = "".join(_event(row, sources, locale) for row in rows) if rows else f'<p class="weekly-missing">{c["empty"]}</p>'
        body.append(f'<section class="weekly-section"><h2>{c[label]}</h2>{note}{items}</section>')
    watch = _rows(content.get("next_watch"))
    if watch:
        items = "".join(f'<li><p>{_esc(_text(row.get("text"), c["missing"]))}</p>{_source_notes(row.get("evidence_ids"), sources, locale)}</li>' for row in watch)
        body.append(f'<section class="weekly-section"><h2>{c["watch"]}</h2><ol class="weekly-watch">{items}</ol></section>')
    follow = _obj(content.get("follow_up"))
    available = follow.get("available")
    label = c["follow_available"] if available is True else c["follow_unavailable"] if available is False else c["follow_unknown"]
    follow_items = "".join(_event(row, sources, locale) for row in _rows(follow.get("items"))) if available is True else ""
    body.append(f'<section class="weekly-section weekly-follow"><h2>{c["follow"]}</h2><p class="weekly-section-note">{label}</p><p>{_esc(_text(follow.get("note"), c["missing"]))}</p>{follow_items}</section>')
    body.extend([_coverage(payload, locale), f'<details class="weekly-process"><summary>{c["process"]}</summary><p>{c["process_note"]}</p></details>'])
    schema = {"@context": "https://schema.org", "@type": "Article", "@id": SITE + _path(locale, identifier) + "#article", "url": SITE + _path(locale, identifier), "mainEntityOfPage": SITE + _path(locale, identifier), "headline": title, "description": description, "inLanguage": c["lang"], "articleSection": c["weekly"], "publisher": {"@type": "Organization", "name": "PolyEmergence Pte Ltd.", "url": SITE, "logo": {"@type": "ImageObject", "url": SITE + "/assets/logo-en.svg"}}, "image": [SITE + "/assets/social-preview.png"]}
    if published:
        schema["datePublished"] = published.isoformat()
    if modified and (not published or modified >= published):
        schema["dateModified"] = modified.isoformat()
    citations = list(dict.fromkeys(url for row in sources.values() if (url := normalize_source_url(row.get("url")))))
    if citations:
        schema["citation"] = citations
    return _shell(locale, title, description, "".join(body), schema, identifier)


def render_weekly_index(editions, locale):
    """Render latest and historical public editions; never invent an issue."""
    locale = _locale(locale)
    c, known = COPY[locale], {}
    for payload in _rows(editions):
        try:
            identifier = _edition_id(payload.get("id"))
        except (ValueError, TypeError):
            continue
        if identifier not in known:
            known[identifier] = payload
    ordered = [known[identifier] for identifier in sorted(known, reverse=True)]
    body = [f'<header class="weekly-index-header"><p class="weekly-eyebrow">{c["ai"]}</p><h1>{c["index_title"]}</h1><p class="weekly-dek">{c["index_dek"]}</p></header>']
    cards = []
    for index, payload in enumerate(ordered):
        content = _obj(payload.get(locale))
        identifier = _edition_id(payload["id"])
        heading = "h2" if index == 0 else "h3"
        latest = f'<p class="weekly-eyebrow">{c["latest"]}</p>' if index == 0 else ""
        cards.append(f'<article class="weekly-edition-card{" is-latest" if index == 0 else ""}">{latest}<p class="weekly-edition-period">{_esc(_period(payload, locale))}</p><{heading}><a href="{_path(locale, identifier)}">{_esc(_text(content.get("title"), c["issue_title"]))}</a></{heading}><p>{_esc(_text(content.get("dek"), c["missing"]))}</p><p class="weekly-index-published">{c["published"]}: {_esc(_time(payload.get("published_at"), locale))}</p><a class="weekly-read-link" href="{_path(locale, identifier)}">{c["read"]} →</a></article>')
    if cards:
        body.append(cards[0])
        history = "".join(cards[1:]) if len(cards) > 1 else f'<p class="weekly-section-note">{c["no_history"]}</p>'
        body.append(f'<section class="weekly-section"><h2>{c["history"]}</h2><div class="weekly-history">{history}</div></section>')
    else:
        body.append(f'<p class="weekly-empty">{c["no_editions"]}</p>')
    schema = {"@context": "https://schema.org", "@type": "CollectionPage", "name": c["index_title"], "description": c["index_dek"], "url": SITE + _path(locale), "inLanguage": c["lang"], "mainEntity": {"@type": "ItemList", "numberOfItems": len(ordered), "itemListElement": [{"@type": "ListItem", "position": index + 1, "url": SITE + _path(locale, payload["id"]), "name": _text(_obj(payload.get(locale)).get("title"), c["issue_title"])} for index, payload in enumerate(ordered)]}}
    return _shell(locale, c["index_title"], c["index_dek"], "".join(body), schema)
