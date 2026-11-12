#!/usr/bin/env python3
"""Build indexable bilingual field briefings from the public feed and home shell.

The same lead/grid containers are hydrated by app.js, so readers and crawlers
receive useful HTML without a duplicate, crawler-only list of news stories.
"""

import argparse
import ast
import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
SITE = "https://polyemergence.com"
SGT = ZoneInfo("Asia/Singapore")
WINDOW = timedelta(hours=48)

# Editorial copy supplements the registry. A newly registered field still gets
# a complete page; optional domain["seo"][locale] values can override this copy.
SEO = {
    "ai": {
        "en": ("AI News", "AI news on foundation models, AI agents, companies, research and regulation. Read sourced summaries and the developments that matter for business and society.", "Follow changes in model capabilities, the companies building AI, and the infrastructure behind them. Coverage connects new research and product releases with adoption, governance and economic consequences.", "Foundation models · AI agents · AI infrastructure · Research · Regulation"),
        "zh": ("AI 新闻与人工智能动态", "精选 AI 新闻与人工智能动态，追踪大模型、智能体、公司、研究与监管，提供原始来源、发布时间与影响摘要。", "关注模型能力如何变化、哪些公司正在推动应用，以及支撑 AI 的算力与基础设施。将研究与产品发布同实际采用、治理和产业影响联系起来。", "大模型 · AI 智能体 · 算力基础设施 · 研究 · 监管"),
    },
    "programmable_life": {
        "en": ("Biotech News & Programmable Life", "Biotech news covering synthetic biology, gene editing, protein design, cell engineering and biomanufacturing, with original sources and concise context.", "Track technologies that read, design and engineer living systems. Coverage follows the path from a reproducible biological result to tools, clinical development and scalable manufacturing, with attention to evidence and deployment constraints.", "Synthetic biology · Gene editing · Protein design · Cell engineering · Biomanufacturing"),
        "zh": ("生物技术新闻与可编程生命", "追踪生物技术新闻、合成生物学、基因编辑、蛋白质设计与生物制造，以原始来源和简明摘要解释研究及商业进展。", "关注读取、设计和工程化生命系统的技术。从可重复的实验结果，到研发工具、临床开发和规模化制造，持续观察证据、成本与实际落地条件。", "合成生物学 · 基因编辑 · 蛋白质设计 · 细胞工程 · 生物制造"),
    },
    "energy_storage": {
        "en": ("Renewable Energy News & Energy Storage", "Renewable energy news, batteries, energy storage, geothermal, advanced nuclear and fusion. Follow research, grid deployment and the companies scaling new energy systems.", "Follow how energy is generated, stored and delivered. Coverage looks at battery performance, long-duration storage, firm low-carbon power and grid integration, including the engineering and economics that determine deployment.", "Batteries · Long-duration storage · Solar and grids · Geothermal · Nuclear fusion"),
        "zh": ("新能源新闻与能源储存", "追踪新能源新闻、储能技术、电池、地热、先进核能与核聚变，连接研究突破、电网部署与产业商业化。", "关注能源如何生产、储存和输送。观察电池性能、长时储能、稳定低碳电力与电网接入，也关注决定规模化部署的工程条件和经济性。", "电池 · 长时储能 · 光伏与电网 · 地热 · 核聚变"),
    },
    "robotics_autonomy": {
        "en": ("Robotics News & Autonomous Systems", "Robotics news on humanoids, industrial robots, autonomous vehicles, drones and embodied AI. Read original-source summaries of research, products and real-world deployments.", "Track machines that sense, decide and act in the physical world. Coverage distinguishes demonstrations from practical deployments and follows manipulation, navigation, safety, reliability and the cost of useful work.", "Humanoid robots · Industrial automation · Autonomous vehicles · Drones · Embodied AI"),
        "zh": ("机器人新闻与自主系统", "精选机器人新闻，涵盖人形机器人、工业机器人、自动驾驶、无人机与具身智能，追踪研究、产品与真实部署。", "关注能够感知、决策并作用于物理世界的机器。区分演示与实际部署，观察操作、导航、安全、可靠性，以及完成有效工作的成本。", "人形机器人 · 工业自动化 · 自动驾驶 · 无人机 · 具身智能"),
    },
    "quantum_technology": {
        "en": ("Quantum Computing News & Quantum Technology", "Quantum computing news, qubits, error correction, quantum sensing and communications. Follow laboratory results, hardware roadmaps and commercial deployments with source links.", "Follow the engineering of useful quantum systems, from qubits and error correction to sensing and secure communications. Coverage considers what was measured, how results were verified and what remains before practical use.", "Quantum processors · Error correction · Quantum sensing · Quantum networks · Hybrid computing"),
        "zh": ("量子计算新闻与量子技术", "追踪量子计算新闻、量子比特、纠错、量子传感与通信，连接实验结果、硬件路线图和商业应用，保留原始来源。", "关注有用量子系统的工程进展，从量子比特和纠错到精密传感与安全通信。观察测量结果、验证方法，以及距离实际使用尚存的条件。", "量子处理器 · 量子纠错 · 量子传感 · 量子网络 · 混合计算"),
    },
    "space_economy": {
        "en": ("Space News & the Space Economy", "Space news covering launch systems, satellites, Earth observation, spacecraft and in-orbit services. Follow mission technology, space companies and commercial infrastructure.", "Track the technologies making access to space and services in orbit more capable and affordable. Coverage follows launch reliability, satellite systems, Earth observation, mission milestones and the infrastructure supporting commercial activity.", "Launch systems · Satellites · Earth observation · Spacecraft · In-orbit services"),
        "zh": ("太空新闻与商业航天", "追踪太空新闻与商业航天，涵盖发射系统、卫星、地球观测、航天器及在轨服务，关注任务技术、企业与空间基础设施。", "关注让进入太空和在轨服务更加可靠、可负担的技术。追踪发射可靠性、卫星系统、地球观测与任务里程碑，以及支撑商业活动的基础设施。", "发射系统 · 卫星 · 地球观测 · 航天器 · 在轨服务"),
    },
    "advanced_materials": {
        "en": ("Advanced Materials News & Nanotechnology", "Advanced materials news covering nanotechnology, metamaterials, semiconductor materials, composites and low-carbon materials, with research context and original sources.", "Follow materials whose structure or composition enables new performance. Coverage connects laboratory properties with reproducibility, processing, manufacturing scale and the applications that could benefit.", "Nanomaterials · Metamaterials · Semiconductor materials · Composites · Low-carbon materials"),
        "zh": ("新材料新闻与纳米技术", "追踪新材料新闻、纳米技术、超材料、半导体材料、复合材料与低碳材料，连接研究性能、制造条件及应用前景。", "关注通过结构或成分设计实现新性能的材料。将实验室指标同可重复性、加工方法、制造规模与可能受益的应用联系起来。", "纳米材料 · 超材料 · 半导体材料 · 复合材料 · 低碳材料"),
    },
    "neurotechnology": {
        "en": ("Neurotechnology News & Brain-Computer Interfaces", "Neurotechnology news on brain-computer interfaces, neural implants, neurostimulation and sensory restoration. Follow evidence, device development and clinical progress.", "Track technologies that measure or interact with the nervous system. Coverage focuses on communication, movement and sensory restoration, considering clinical evidence, usability, durability and the limits of each reported result.", "Brain-computer interfaces · Neural implants · Neurostimulation · Sensory restoration · Neural signals"),
        "zh": ("神经科技新闻与脑机接口", "追踪神经科技新闻、脑机接口、神经植入物、神经刺激与感觉恢复，关注临床证据、设备开发及真实使用进展。", "关注测量或作用于神经系统的技术。围绕交流、运动和感觉恢复，观察临床证据、易用性、长期可靠性，以及每项结果的适用边界。", "脑机接口 · 神经植入物 · 神经刺激 · 感觉恢复 · 神经信号"),
    },
    "climate_water_environment": {
        "en": ("Climate Technology News, Water & Environment", "Climate technology news on carbon removal, water treatment, desalination, industrial decarbonisation and environmental engineering, with source-linked research and deployment updates.", "Follow technologies that reduce emissions, secure water supplies and address environmental damage. Coverage examines measured impact, resource use, infrastructure requirements and whether solutions can work at useful scale.", "Carbon removal · Water treatment · Desalination · Industrial decarbonisation · Environmental monitoring"),
        "zh": ("气候科技新闻、水与环境工程", "追踪气候科技新闻、碳移除、水处理、海水淡化、工业脱碳与环境工程，提供研究和部署进展及原始来源。", "关注减少排放、保障供水与修复环境的技术。观察可测量的影响、资源消耗、基础设施条件，以及解决方案能否实现有效规模。", "碳移除 · 水处理 · 海水淡化 · 工业脱碳 · 环境监测"),
    },
    "agrifood_technology": {
        "en": ("Agritech News & Food Technology", "Agritech news covering precision farming, agricultural robotics, resilient crops, fermentation and alternative proteins. Follow food-system research, startups and commercial deployment.", "Track technologies changing how food is grown, produced and processed. Coverage connects field performance and food science with resource efficiency, production costs, regulation and adoption by farmers and manufacturers.", "Precision agriculture · Farm robotics · Resilient crops · Fermentation · Alternative proteins"),
        "zh": ("农业科技新闻与食品技术", "精选农业科技新闻，涵盖精准农业、农业机器人、韧性作物、发酵与替代蛋白，追踪研究、创业公司及商业化部署。", "关注改变食物种植、生产和加工方式的技术。将田间表现与食品科学同资源效率、生产成本、监管以及农户和制造商的实际采用联系起来。", "精准农业 · 农业机器人 · 韧性作物 · 发酵 · 替代蛋白"),
    },
    "advanced_manufacturing": {
        "en": ("Advanced Manufacturing News & Industrial Technology", "Advanced manufacturing news on additive manufacturing, digital twins, industrial automation, advanced packaging and factory infrastructure, with research and deployment context.", "Follow technologies changing the design, production and verification of physical goods. Coverage examines throughput, precision, reliability, digital integration and the economics of moving from prototypes to repeatable production.", "Additive manufacturing · Digital twins · Factory automation · Advanced packaging · Industrial infrastructure"),
        "zh": ("先进制造新闻与产业基础设施", "追踪先进制造新闻、增材制造、数字孪生、工业自动化、先进封装及工厂基础设施，连接研究突破与生产部署。", "关注改变实体产品设计、生产和验证方式的技术。观察产能、精度、可靠性、数字化集成，以及从原型走向可重复生产的经济条件。", "增材制造 · 数字孪生 · 工厂自动化 · 先进封装 · 产业基础设施"),
    },
}


def esc(value):
    return html.escape(str(value or ""), quote=True)


def safe_url(value):
    value = str(value or "")
    if re.search(r"[\x00-\x20\\]", value):
        return None
    try:
        parsed = urlparse(value)
        return value if parsed.scheme in {"http", "https"} and parsed.netloc else None
    except ValueError:
        return None


def parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def field_path(locale, domain_id):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", domain_id):
        raise ValueError(f"Invalid field id: {domain_id!r}")
    return f"/{locale}/fields/{domain_id}/"


def localized(value, locale, fallback=""):
    return value.get(locale, value.get("en", fallback)) if isinstance(value, dict) else value or fallback


def seo_copy(domain, locale):
    label = localized(domain.get("label"), locale, domain["id"].replace("_", " ").title())
    description = localized(domain.get("description"), locale)
    default_heading = f"{label} News" if locale == "en" else f"{label}新闻"
    defaults = SEO.get(domain["id"], {}).get(locale, (
        default_heading,
        f"{default_heading}. {description}" if locale == "en" else f"{default_heading}。{description}",
        description,
        "",
    ))
    custom = localized(domain.get("seo", {}), locale, {})
    custom = custom if isinstance(custom, dict) else {}
    values = dict(zip(("heading", "description", "intro", "scope"), defaults))
    values.update({key: str(custom[key]) for key in values if custom.get(key)})
    values["title"] = str(custom.get("title") or f'{values["heading"]} | {"Polyemergence" if locale == "en" else "多重涌现 Polyemergence"}')
    return values


def item_domain(item, domains):
    aliases = {alias: d["id"] for d in domains for alias in [d["id"], *d.get("source_categories", [])]}
    if item.get("domain"):
        return aliases.get(item["domain"])
    for value in (item.get("source_category"), item.get("category")):
        if value in aliases:
            return aliases[value]
    return "ai" if "ai" in aliases else None


def current_items(feed, domain_id, domains, now):
    """Apply the exact original-publication 48-hour window, including future gate."""
    selected, seen = [], set()
    for item in feed.get("items", []):
        published = parse_datetime(item.get("source_published_at") or item.get("published_at"))
        url = safe_url(item.get("url"))
        key = item.get("id") or url
        if (not published or not now - WINDOW <= published <= now or not url
                or item_domain(item, domains) != domain_id or key in seen):
            continue
        seen.add(key)
        selected.append(item)
    return sorted(selected, key=lambda i: (float(i.get("importance") or 0), parse_datetime(i.get("source_published_at") or i.get("published_at"))), reverse=True)


def load_sources(path):
    """Read the committed source catalog without importing database code."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "SOURCES" for t in node.targets):
            return ast.literal_eval(node.value)
    return []


def source_home(url):
    parsed = urlparse(url)
    if parsed.netloc == "www.nature.com" and parsed.path.endswith(".rss"):
        return f"https://www.nature.com{parsed.path[:-4]}/"
    if parsed.path.endswith(".atom"):
        return url.split("?", 1)[0][:-5]
    if "news.mit.edu" == parsed.netloc and "/rss/topic/" in parsed.path:
        return url.replace("/rss/topic/", "/topic/")
    if "/feed" in parsed.path or parsed.path.endswith((".xml", ".rss")) or "/rss" in parsed.path:
        return f"{parsed.scheme}://{parsed.netloc}/"
    return url


def field_sources(domain_id, sources, domains):
    aliases = {alias: d["id"] for d in domains for alias in [d["id"], *d.get("source_categories", [])]}
    selected = [s for s in sources if len(s) >= 5 and safe_url(s[0]) and aliases.get(s[3], "ai") == domain_id]
    # The AI catalog is much larger; show a useful representative source list.
    return sorted(selected, key=lambda s: (-int(s[4]), s[1]))[:12]


def archive_url(item, locale, corpus, public):
    """Only emit own summary links whose static archive page actually exists."""
    known = corpus.get(str(item.get("id")), {})
    candidate = (known.get("canonical_urls") or {}).get(locale)
    if not safe_url(candidate):
        return None
    parsed = urlparse(candidate)
    if parsed.netloc != "polyemergence.com" or not re.fullmatch(rf"/{locale}/archive/\d{{4}}/\d{{2}}/\d{{2}}/[A-Za-z0-9_-]+/", parsed.path):
        return None
    if (public / parsed.path.lstrip("/") / "index.html").is_file():
        return SITE + parsed.path
    return None


def clean_text(value):
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", str(value or ""))
    text = re.sub(r"(?m)^\s*#{1,6}\s*", "", text)
    return re.sub(r"\s+", " ", re.sub(r"\*\*|__|`", "", text)).strip()


def news_text(item, locale):
    text = item.get(locale) or item.get("en") or item.get("zh") or {}
    return clean_text(text.get("title") or item.get("title")), clean_text(text.get("summary") or text.get("full_summary"))


def story_markup(item, locale, corpus, public, lead=False):
    title, summary = news_text(item, locale)
    original = safe_url(item.get("url"))
    summary_url = archive_url(item, locale, corpus, public)
    published = parse_datetime(item.get("source_published_at") or item.get("published_at"))
    date_label = published.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")
    published_label = "Source published" if locale == "en" else "原文发布"
    original_label = "Read original" if locale == "en" else "阅读原文"
    summary_label = "Read summary" if locale == "en" else "阅读摘要"
    actions = f'<a class="read-link" href="{esc(original)}" target="_blank" rel="noopener noreferrer">{original_label} ↗</a>'
    if summary_url:
        actions += f'<a class="read-link" href="{esc(summary_url)}">{summary_label} →</a>'
    copy = (f'<div class="story-kicker"><span>{esc(item.get("source"))}</span></div>'
            f'<div class="story-published"><time datetime="{published.isoformat().replace("+00:00", "Z")}">{published_label} {date_label}</time></div>'
            f'<h3><a href="{esc(summary_url or original)}">{esc(title)}</a></h3>'
            f'<p>{esc(summary)}</p><div class="story-actions">{actions}</div>')
    image_url = safe_url(item.get("image_url"))
    if image_url:
        visual = f'<img class="media-contain" src="{esc(image_url)}" alt="{esc(title)}" loading="lazy" decoding="async" referrerpolicy="no-referrer">'
    else:
        visual = ('<div class="brand-cover" role="img" aria-label="Polyemergence">'
                  '<svg class="cover-art cover-art-landscape" viewBox="0 0 1200 675" aria-hidden="true">'
                  '<rect class="cover-bg" width="1200" height="675"/>'
                  '<path class="cover-grid" d="M0 225h1200M0 450h1200M400 0v675M800 0v675"/>'
                  '<path class="cover-orange" d="M250 450l350-175 350 175-350 175z"/>'
                  '<path class="cover-stroke" d="M250 340l350-175 350 175-350 175zM250 230L600 55l350 175-350 175z"/>'
                  '</svg></div>')
    if lead:
        return f'<div class="lead-copy">{copy}</div><div class="story-visual">{visual}</div>'
    return f'<article class="story-card"><div class="card-visual">{visual}</div><div class="card-copy">{copy}</div></article>'


def replace_content(page, tag, element_id, content):
    pattern = rf'(<{tag}\b[^>]*\bid="{re.escape(element_id)}"[^>]*>).*?(</{tag}>)'
    result, count = re.subn(pattern, lambda m: m[1] + content + m[2], page, count=1, flags=re.S)
    if not count:
        raise ValueError(f"Home shell is missing #{element_id}")
    return result


def set_hidden(page, tag, element_id, hidden):
    pattern = rf'<{tag}\b[^>]*\bid="{re.escape(element_id)}"[^>]*>'
    def update(match):
        opening = re.sub(r'\s+hidden(?:="[^"]*")?', "", match[0])
        return opening[:-1] + (" hidden>" if hidden else ">")
    return re.sub(pattern, update, page, count=1)


def json_script(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_domain_links(locale, domains):
    return "".join(f'<a href="{field_path(locale, d["id"])}">{esc(localized(d.get("label"), locale, d["id"]))}</a>' for d in domains)


def render_field_page(shell, domain, locale, domains, feed, sources, corpus, public, now):
    copy = seo_copy(domain, locale)
    url = SITE + field_path(locale, domain["id"])
    items = current_items(feed, domain["id"], domains, now)
    page = re.sub(r"<html\b([^>]*)>", lambda m: f'<html{m[1]} data-field="{esc(domain["id"])}">', shell, count=1)
    page = re.sub(r"<title>.*?</title>", lambda _: f'<title>{esc(copy["title"])}</title>', page, count=1, flags=re.S)
    for key, attribute, value in [
        ("description", "name", copy["description"]),
        ("og:title", "property", copy["title"]), ("og:description", "property", copy["description"]),
        ("og:url", "property", url), ("twitter:title", "name", copy["title"]),
        ("twitter:description", "name", copy["description"]),
    ]:
        page = re.sub(rf'<meta\b[^>]*\b{attribute}="{re.escape(key)}"[^>]*>', lambda _, k=key, a=attribute, v=value: f'<meta {a}="{k}" content="{esc(v)}">', page, count=1)
    page = re.sub(r'<link\b[^>]*\brel="canonical"[^>]*>', f'<link rel="canonical" href="{url}">', page, count=1)
    for language, target_locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
        target = SITE + field_path(target_locale, domain["id"])
        page = re.sub(rf'<link\b[^>]*\bhreflang="{language}"[^>]*>', f'<link rel="alternate" hreflang="{language}" href="{target}">', page, count=1)
    for target_locale in ("en", "zh"):
        page = re.sub(rf'(<a\b[^>]*\bdata-locale-button="{target_locale}"[^>]*>)', lambda m: re.sub(r'href="[^"]*"', f'href="{field_path(target_locale, domain["id"])}"', m[0]), page)
    page = re.sub(r'<a\b[^>]*\bdata-fields-link\b[^>]*>', lambda m: re.sub(r'href="[^"]*"', f'href="/{locale}/#fields"', m[0]), page)
    page = replace_content(page, "h1", "intro-title", esc(copy["heading"]))
    page = re.sub(r'(<p\b[^>]*\bdata-copy="promise"[^>]*>).*?</p>', lambda m: m[1] + esc(copy["description"]) + "</p>", page, count=1, flags=re.S)
    page = re.sub(r'(<p\b[^>]*\bdata-copy="eyebrow"[^>]*>).*?</p>', lambda m: m[1] + ("FIELD BRIEFING · PAST 48 HOURS" if locale == "en" else "领域简报 · 最近 48 小时") + "</p>", page, count=1, flags=re.S)
    page = set_hidden(page, "section", "fields", True)
    page = set_hidden(page, "section", "brief", False)
    page = replace_content(page, "span", "selected-field-label", esc(localized(domain.get("label"), locale)))
    page = replace_content(page, "h2", "brief-title", esc(copy["heading"]) + (" · Past 48 hours" if locale == "en" else " · 最近 48 小时"))
    page = replace_content(page, "p", "field-description", esc(localized(domain.get("description"), locale)))
    page = replace_content(page, "div", "lead-story", story_markup(items[0], locale, corpus, public, True) if items else "")
    page = replace_content(page, "div", "story-grid", "".join(story_markup(item, locale, corpus, public) for item in items[1:]))
    page = set_hidden(page, "div", "lead-story", not items)
    page = set_hidden(page, "div", "story-grid", len(items) <= 1)
    empty = ("No qualifying stories from the past 48 hours. Explore the field coverage and sources below, or browse the archive." if locale == "en" else "最近 48 小时内暂无符合筛选标准的新闻。可以阅读下方领域介绍与信息源，或浏览历史归档。")
    page = replace_content(page, "div", "empty-state", esc(empty))
    page = set_hidden(page, "div", "empty-state", bool(items))
    generated = parse_datetime(feed.get("generated_at"))
    if generated and generated <= now:
        status = ("Updated " if locale == "en" else "更新于 ") + generated.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")
        page = replace_content(page, "span", "update-status", esc(status))
    source_list = field_sources(domain["id"], sources, domains)
    heading = "Field coverage" if locale == "en" else "领域覆盖"
    source_heading = "Sources we follow" if locale == "en" else "关注的信息源"
    source_note = ("A selection of configured official, research and specialist sources. A source is not a guarantee that every item will be selected." if locale == "en" else "以下为已配置的官方、研究机构与专业媒体来源。来源中的内容仍需经过筛选，并非每篇都会入选。")
    source_links = "".join(f'<li><a href="{esc(source_home(s[0]))}" target="_blank" rel="noopener noreferrer">{esc(s[1])}</a></li>' for s in source_list)
    evergreen = (f'<div><p class="section-index">{heading}</p><h2>{esc(copy["heading"])}</h2><p>{esc(copy["intro"])}</p>'
                 + (f'<p class="field-scope">{esc(copy["scope"])}</p>' if copy["scope"] else "")
                 + f'<p><a href="/{locale}/archive/">{"Browse historical editions" if locale == "en" else "浏览历史归档"} →</a> · <a href="/{locale}/standards/">{"Editorial standards" if locale == "en" else "编辑标准"}</a></p></div>'
                 + (f'<div><h3>{source_heading}</h3><p>{source_note}</p><ul>{source_links}</ul></div>' if source_links else ""))
    page = replace_content(page, "section", "field-seo-content", evergreen)
    page = set_hidden(page, "section", "field-seo-content", False)
    page = re.sub(r'(<section\b[^>]*\bid="field-seo-content"[^>]*)(>)', lambda m: m[1] + f' data-field="{domain["id"]}"' + m[2], page, count=1)
    # Replace the generic homepage graph with truthful collection/list data.
    graph = {
        "@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": SITE + "/#organization", "name": "Polyemergence", "legalName": "PolyEmergence Pte Ltd.", "url": SITE + "/"},
            {"@type": "WebSite", "@id": SITE + "/#website", "name": "Polyemergence", "url": SITE + "/"},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Fields" if locale == "en" else "领域", "item": SITE + f"/{locale}/#fields"},
                {"@type": "ListItem", "position": 2, "name": localized(domain.get("label"), locale), "item": url},
            ]},
            {"@type": "CollectionPage", "@id": url + "#page", "url": url, "name": copy["heading"], "description": copy["description"], "inLanguage": "en" if locale == "en" else "zh-Hans", "about": localized(domain.get("label"), locale), "isPartOf": {"@id": SITE + "/#website"}, "publisher": {"@id": SITE + "/#organization"}, "mainEntity": {"@id": url + "#brief-list"}},
            {"@type": "ItemList", "@id": url + "#brief-list", "name": ("Past 48 hours" if locale == "en" else "最近 48 小时"), "numberOfItems": len(items), "itemListElement": [{"@type": "ListItem", "position": n, "name": news_text(item, locale)[0], "url": archive_url(item, locale, corpus, public) or safe_url(item.get("url"))} for n, item in enumerate(items, 1)]},
        ],
    }
    page = re.sub(r'<script\b[^>]*type="application/ld\+json"[^>]*>.*?</script>', lambda _: '<script type="application/ld+json">' + json_script(graph) + '</script>', page, count=1, flags=re.S)
    return page


def export(public, registry_path, feed_path, sources_path, articles_path=None, now=None):
    now = now or datetime.now(timezone.utc)
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    domains = sorted(registry["domains"], key=lambda d: d.get("order", 999))
    feed = json.loads(Path(feed_path).read_text(encoding="utf-8"))
    sources = load_sources(sources_path)
    corpus = {}
    if articles_path and Path(articles_path).is_file():
        corpus = {str(item.get("id")): item for item in json.loads(Path(articles_path).read_text(encoding="utf-8")).get("items", [])}
    urls = []
    for locale in ("en", "zh"):
        shell = (public / locale / "index.html").read_text(encoding="utf-8")
        for domain in domains:
            path = field_path(locale, domain["id"])
            destination = public / path.lstrip("/") / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render_field_page(shell, domain, locale, domains, feed, sources, corpus, public, now), encoding="utf-8")
            urls.append(SITE + path)
    namespace = "http://www.sitemaps.org/schemas/sitemap/0.9"
    ET.register_namespace("", namespace)
    sitemap = ET.Element(f"{{{namespace}}}urlset")
    for url in urls:
        entry = ET.SubElement(sitemap, f"{{{namespace}}}url")
        ET.SubElement(entry, f"{{{namespace}}}loc").text = url
    (public / "field-sitemap.xml").write_bytes(ET.tostring(sitemap, encoding="utf-8", xml_declaration=True))
    return len(urls)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "web/public")
    parser.add_argument("--registry", type=Path, default=ROOT / "web/public/data/editorial-domains.json")
    parser.add_argument("--feed", type=Path, default=ROOT / "web/public/data/latest.json")
    parser.add_argument("--sources", type=Path, default=ROOT / "scripts/bootstrap_sources.py")
    parser.add_argument("--articles", type=Path, default=ROOT / "web/public/data/articles.json")
    args = parser.parse_args()
    count = export(args.output, args.registry, args.feed, args.sources, args.articles)
    print(f"Exported {count} bilingual field pages and field-sitemap.xml")


if __name__ == "__main__":
    main()
