"""Conservative, deterministic presentation metadata for public news records.

This module does not call a database, the network, or an LLM. Labels describe
the linked document, not a guarantee that its claims have been independently
verified. Enrichment is safe to repeat and never mutates the input record.
"""

import ast
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import re
from urllib.parse import urlparse

from editorial_domains import domains, infer_domain


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_TYPES = {
    "official_release", "preprint", "research_paper", "media_report",
    "interview", "open_source", "unknown",
}
STAGES = {"laboratory", "demonstration", "pilot", "deployment", "unspecified"}


def is_github_trending(item):
    """The repository popularity list is not a dated release announcement."""
    source = item.get("source") or item.get("source_name") or item.get("name") or ""
    return str(source).strip().casefold() == "github trending"


def _public_date(value):
    try:
        date = value if isinstance(value, datetime) else datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if date.tzinfo is None:
            date = date.replace(tzinfo=timezone.utc)
        return date.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    except (TypeError, ValueError):
        return None


def _host(value):
    try:
        parsed = urlparse(str(value or ""))
        if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
            return ""
        return (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
    except ValueError:
        return ""


def _on_host(host, expected):
    return bool(host and (host == expected or host.endswith("." + expected)))


@lru_cache(maxsize=1)
def _source_catalog():
    """Read the existing literal catalog without executing its seeding script."""
    tree = ast.parse((ROOT / "scripts/bootstrap_sources.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SOURCES" for target in node.targets
        ):
            return ast.literal_eval(node.value)
    return []


def _matches_source_url(url, feed_url):
    host, expected = _host(url), _host(feed_url)
    if not _on_host(host, expected):
        return False
    # A GitHub repository's official release feed cannot vouch for another
    # user's repository, nor can a shared raw-file mirror identify a publisher.
    if expected in {"github.com", "raw.githubusercontent.com"}:
        path = urlparse(url).path.strip("/").split("/")
        feed_path = urlparse(feed_url).path.strip("/").split("/")
        return len(path) >= 2 and path[:2] == feed_path[:2]
    # YouTube's watch URL does not expose its channel; don't infer first-party
    # provenance solely from a shared youtube.com host and a source name.
    if expected in {"youtube.com", "youtu.be", "feeds.simplecast.com"}:
        return False
    return True


def evidence_type(item):
    """Classify only what the linked URL and configured publisher support."""
    url = str(item.get("url") or "")
    host = _host(url)
    if not host:
        return "unknown"
    path = urlparse(url).path
    if (
        (_on_host(host, "arxiv.org") and re.match(r"/(?:abs|pdf|html)/", path))
        or (_on_host(host, "biorxiv.org") and path.startswith("/content/"))
        or (_on_host(host, "medrxiv.org") and path.startswith("/content/"))
        or (_on_host(host, "chemrxiv.org") and path.startswith("/engage/"))
    ):
        return "preprint"
    if item.get("category") == "interviews":
        return "interview"
    if host == "github.com" and len(path.strip("/").split("/")) >= 2:
        return "open_source"
    # Nature's d-prefixed article identifiers are journalism/editorials, not
    # primary research. University newsrooms are deliberately excluded here.
    if host == "nature.com" and re.match(r"/articles/s\d{5}-\d{3,}", path):
        return "research_paper"
    matches = [source for source in _source_catalog() if _matches_source_url(url, source[0])]
    for _, name, description, _, _ in matches:
        if name == item.get("source") and (
            "[FIRST_PARTY]" in description
            or re.search(r"\bofficial\b|\bfirst-party\b", description, re.I)
        ):
            return "official_release"
    # A known first-party host still supports the label when a saved source
    # name changed. Do not trust the phrase "official" in an arbitrary name.
    if any("[FIRST_PARTY]" in source[2] or re.search(r"\bofficial\b|\bfirst-party\b", source[2], re.I)
           for source in matches):
        return "official_release"
    if matches or (host == "nature.com" and path.startswith("/articles/")):
        return "media_report"
    return "unknown"


def technology_stage(item):
    """Require explicit headline evidence; announcements are not deployment."""
    title = " ".join(str((item.get(locale) or {}).get("title") or "") for locale in ("en", "zh"))
    title = title or str(item.get("title") or "")
    # A roadmap or planned test must not become an already-achieved stage.
    if re.search(r"\b(?:plans?|planned|aims?|targets?|roadmap|will|could|would|might|may|if|unless|proposes?|to deploy|to test|to pilot|not|never|no evidence)\b|计划|拟于|拟将|有望|将于|路线图|目标是|尚未|仍未|不等于|没有|若能|如果|未(?:曾|能|有|完成|部署|开展|进行|启动|投入|验证|通过|实现|上市|商业)", title, re.I):
        return "unspecified"
    patterns = (
        ("laboratory", r"\bin (?:the )?lab(?:oratory)?\b|\bin vitro\b|\bin mice\b|\blaboratory (?:test|result|validation|experiment)\b|实验室(?:验证|实验|结果)|体外实验|小鼠实验"),
        ("pilot", r"\b(?:begins?|starts?|completes?|completed|launches?|launched|opens?)\b.{0,45}\b(?:pilot|clinical trial|field trial)\b|\bpilot (?:project|programme|program|plant|trial)\b|启动.{0,16}(?:试点|临床试验)|试点(?:启动|运行|完成)|完成.{0,12}(?:试点|临床试验)"),
        ("deployment", r"\b(?:deployed at|deployed in|enters? service|begins? operations|operational deployment|commercial deployment)\b|已(?:部署|投入运营|投产)|正式(?:投产|投入运营)|商业化部署"),
        ("demonstration", r"\b(?:demonstrates?|demonstrated|prototype|proof[- ]of[- ]concept|working demo)\b|原型(?:机|系统|演示)|概念验证|展示.{0,12}(?:机器人|原型|系统)"),
    )
    for stage, pattern in patterns:
        if re.search(pattern, title, re.I):
            return stage
    return "unspecified"


def _keyword_matches(text, keyword):
    if re.search(r"[\u3400-\u9fff]", keyword):
        return len(re.findall(re.escape(keyword), text, re.I))
    return len(re.findall(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", text, re.I))


def _strip_attribution(text):
    """Recognise our own display prefix even after a publisher is renamed."""
    return re.sub(
        r"^(?:According to [^\n:]{1,100}:|据[^\n：]{1,100}发布的信息：|The authors report in this preprint:|据这篇预印本作者报告：)\s*",
        "", str(text or ""), count=1,
    )


def related_domains(item):
    """Find concrete secondary subjects, never tags or publisher-name hints."""
    titles = " ".join(str((item.get(locale) or {}).get("title") or "") for locale in ("en", "zh"))
    summary_parts = [_strip_attribution((item.get(locale) or {}).get("summary")) for locale in ("en", "zh")]
    summaries = " ".join(summary_parts)
    # "A battery of tests" is not energy technology; "neural network" is not
    # neurotechnology, and generic "model", "data", "materials" are not tags.
    summaries = re.sub(r"\bbattery of\b", "group of", summaries, flags=re.I)
    titles = re.sub(r"\bbattery of\b", "group of", titles, flags=re.I)
    summaries = re.sub(r"聊天机器人|软件机器人|机器人客服|客服机器人", "软件助手", summaries)
    titles = re.sub(r"聊天机器人|软件机器人|机器人客服|客服机器人", "软件助手", titles)
    candidates = []
    for domain in domains():
        if domain["id"] == item.get("domain"):
            continue
        keywords = list(domain.get("keywords", []))
        if domain["id"] == "advanced_manufacturing" and not re.search(
            r"\b(?:industrial|manufacturing|factory|production line|physical|assembly|machinery)\b|工业|制造|工厂|生产线|物理设备|机械设备", titles + " " + summaries, re.I,
        ):
            # Enterprise-software simulations also use "digital twin"; that
            # phrase alone is not evidence of manufacturing technology.
            keywords = [term for term in keywords if term not in {"digital twin", "数字孪生"}]
        if domain["id"] == "ai":
            keywords += ["AI", "AI-powered", "LLM", "deep learning", "深度学习"]
        title_score = sum(_keyword_matches(titles, keyword) for keyword in keywords)
        summary_score = sum(_keyword_matches(summaries, keyword) for keyword in keywords)
        # AI must be a headline subject or a specific method, not an incidental
        # AI mention in every company's marketing paragraph.
        if domain["id"] == "ai" and not title_score:
            specific = [term for term in keywords if term not in {"AI", "人工智能", "智能体"}]
            summary_score = sum(_keyword_matches(summaries, term) for term in specific)
        if title_score or summary_score:
            candidates.append((title_score * 3 + summary_score, domain.get("order", 999), domain["id"]))
    candidates.sort(key=lambda row: (-row[0], row[1]))
    return [row[2] for row in candidates[:2]]


READING_CONTEXT = {
    "ai": ("Check whether reported capability gains hold up in independent evaluations and real use, and what remains untested.", "关注所称能力提升能否在独立评测与真实使用中成立，以及还有哪些未验证之处。"),
    "programmable_life": ("Check the experimental setting, reproducibility and safety evidence before inferring effects in humans or production at scale.", "先核查实验条件、可重复性与安全证据，再判断能否推广到人体或规模化生产。"),
    "energy_storage": ("Check measured performance, costs, operating duration and scale; a technical milestone alone does not establish commercial viability.", "关注实测性能、成本、运行时长与规模；单次技术进展不等于商业可行性已经成立。"),
    "robotics_autonomy": ("Check whether results come from a controlled demonstration or sustained operation, including failure rates, human assistance and costs.", "关注成果来自受控演示还是持续运行，并核查失败率、人工介入与成本。"),
    "quantum_technology": ("Check the task, verification method and classical baseline before treating a claimed quantum advantage as a general capability.", "关注任务范围、核验方法和经典计算基线，不把特定任务的量子优势直接等同于普遍能力。"),
    "space_economy": ("Distinguish announced plans from completed missions, and check reliability, costs and the evidence for repeatable operations.", "区分计划宣布与任务完成，关注可靠性、成本以及能否重复运行的证据。"),
    "advanced_materials": ("Check measurement conditions, reproducibility, durability and manufacturing scale before extrapolating a material's performance.", "关注测量条件、可重复性、耐久性与制造规模，不把特定条件下的性能直接外推。"),
    "neurotechnology": ("Check participant numbers, study duration, safety and independent replication; a demonstration does not establish broad clinical benefit.", "关注参与人数、研究时长、安全性和独立复现；一次演示不代表已证实广泛临床获益。"),
    "climate_water_environment": ("Check system boundaries, lifecycle impacts, measured resource use and local conditions before extrapolating environmental benefits.", "关注系统边界、全生命周期影响、实测资源消耗与当地条件，再判断环境收益能否推广。"),
    "agrifood_technology": ("Check field or production conditions, safety, resource use and unit costs; laboratory results need not translate to commercial scale.", "关注田间或生产条件、安全性、资源消耗与单位成本；实验室结果未必能直接扩大到商业规模。"),
    "advanced_manufacturing": ("Check production yield, throughput, integration costs and sustained operation, rather than treating a prototype as a factory-wide result.", "关注生产良率、吞吐量、集成成本与持续运行表现，不把原型效果当作整座工厂的成果。"),
}


def _attribute(text, source, locale, kind):
    text = str(text or "").strip()
    if not text or kind not in {"official_release", "preprint"}:
        return text
    prefix = (
        (f"According to {source}:" if locale == "en" else f"据{source}发布的信息：")
        if kind == "official_release" else
        ("The authors report in this preprint:" if locale == "en" else "据这篇预印本作者报告：")
    )
    text = _strip_attribution(text)
    return prefix + ("\n\n" if text.startswith("#") or "\n" in text else " " if locale == "en" else "") + text


def enrich_item(item):
    """Return a detached, enriched public/archive record; never modify history.

    Locales can use ``full_summary`` (feed) or ``full`` (archive). The original
    shape is retained, so existing renderers can adopt this function directly.
    """
    result = deepcopy(item)
    if is_github_trending(result):
        # A bare repository has no source publication date. Its historical
        # published_at can contain a legacy popularity-refresh timestamp; do
        # not reuse that timestamp as either first-seen or a new news event.
        result["date_basis"] = "first_seen"
        result["first_seen_at"] = next((date for value in (
            result.get("site_published_at"), result.get("created_at"),
            result.get("first_seen_at"), result.get("site_published"),
        ) if (date := _public_date(value))), None)
    result["domain"] = result.get("domain") or infer_domain(
        result.get("category"), result.get("source_category"),
        " ".join(str((result.get(locale) or {}).get("title") or "") for locale in ("en", "zh")),
    )
    result["evidence"] = {"type": evidence_type(result), "stage": technology_stage(result)}
    if is_github_trending(result):
        result["evidence"]["stage"] = "unspecified"
    result["related_domains"] = related_domains(result)
    context = READING_CONTEXT.get(result["domain"], (
        "Check the original evidence, uncertainty and conditions before generalising the reported result.",
        "关注原始证据、不确定性与适用条件，不把单篇报道直接外推为普遍结论。",
    ))
    result["reading_context"] = {"en": context[0], "zh": context[1]}
    source = re.sub(r"[\r\n]+", " ", str(result.get("source") or "the publisher")).strip()[:100]
    for locale in ("en", "zh"):
        localized = result.get(locale)
        if isinstance(localized, dict):
            for field in ("summary", "full_summary", "full", "long_summary"):
                if field in localized:
                    localized[field] = _attribute(localized[field], source, locale, result["evidence"]["type"])
    return result
