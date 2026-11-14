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
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from editorial_insights import enrich_item, reading_guidance, article_reading_context
SITE = "https://polyemergence.com"
SGT = ZoneInfo("Asia/Singapore")
WINDOW = timedelta(hours=48)
HUB_COPY = {
    "en": {
        "title": "Tech News by Field — AI, Biotech & Emerging Tech | Polyemergence",
        "heading": "Tech News by Field",
        "description": "Explore technology news by field: AI, biotech, energy, robotics and other emerging technologies. Choose a briefing for sourced summaries from the past 48 hours.",
        "intro": "Start with a field, not a mixed news feed. Each briefing links to original reporting and separates recent developments from longer-term coverage and research questions.",
    },
    "zh": {
        "title": "科技新闻总览：AI、生物技术与前沿科技｜多重涌现",
        "heading": "科技新闻总览",
        "description": "按领域浏览人工智能、生物技术、能源、机器人等前沿科技新闻。先选择关注领域，再阅读最近 48 小时的精选摘要、原始来源与研究背景。",
        "intro": "先选择领域，再看具体新闻，而不是浏览混杂的信息流。各领域简报保留原始来源，并将近期进展、长期覆盖范围与待核查的问题分开呈现。",
    },
}
RELATED_FIELDS = {
    "ai": [("robotics_autonomy", "Intelligence acting in physical systems", "智能如何作用于物理系统"), ("programmable_life", "Computational tools for biological design", "用于生命设计的计算工具"), ("energy_storage", "Power and infrastructure constraints", "电力与基础设施约束")],
    "programmable_life": [("ai", "Models and tools for biological research", "用于生命研究的模型与工具"), ("agrifood_technology", "Biological engineering in food production", "食品生产中的生物工程"), ("advanced_manufacturing", "Repeatable production and process engineering", "可重复生产与工艺工程")],
    "energy_storage": [("advanced_materials", "Materials that determine performance and lifetime", "决定性能与寿命的材料"), ("climate_water_environment", "Deployment, resource use and environmental impact", "部署、资源使用与环境影响"), ("ai", "Electricity demand and computing infrastructure", "用电需求与计算基础设施")],
    "robotics_autonomy": [("ai", "Perception, planning and learning systems", "感知、规划与学习系统"), ("advanced_manufacturing", "Factory integration and repeatable work", "工厂集成与可重复工作"), ("agrifood_technology", "Automation in farms and food production", "农场与食品生产中的自动化")],
    "quantum_technology": [("advanced_materials", "Device materials and fabrication", "器件材料与制备"), ("advanced_manufacturing", "Fabrication, packaging and control systems", "制造、封装与控制系统"), ("ai", "Hybrid methods and computing infrastructure", "混合方法与计算基础设施")],
    "space_economy": [("advanced_materials", "Mass, structure and durability", "质量、结构与耐久性"), ("robotics_autonomy", "Autonomous operation beyond Earth", "地外环境中的自主运行"), ("climate_water_environment", "Earth observation and measurement", "地球观测与测量")],
    "advanced_materials": [("advanced_manufacturing", "From measured properties to repeatable production", "从实测性能到可重复制造"), ("energy_storage", "Materials for energy conversion and storage", "能源转换与储存材料"), ("space_economy", "Materials under demanding operating conditions", "严苛运行条件下的材料")],
    "neurotechnology": [("programmable_life", "Biological interfaces and experimental evidence", "生物接口与实验证据"), ("ai", "Signal processing and adaptive interfaces", "信号处理与自适应接口"), ("advanced_materials", "Implant materials and device durability", "植入材料与器件耐久性")],
    "climate_water_environment": [("energy_storage", "Energy inputs, grids and decarbonisation", "能源投入、电网与脱碳"), ("agrifood_technology", "Water, land and food-system resource use", "水、土地与食品系统资源使用"), ("advanced_materials", "Materials for treatment and environmental systems", "处理工艺与环境系统材料")],
    "agrifood_technology": [("programmable_life", "Biological design and fermentation", "生物设计与发酵"), ("robotics_autonomy", "Machines working in agricultural settings", "农业环境中工作的机器"), ("climate_water_environment", "Water, emissions and resource efficiency", "水、排放与资源效率")],
    "advanced_manufacturing": [("robotics_autonomy", "Automation and production-line integration", "自动化与产线集成"), ("advanced_materials", "Material processing and production yield", "材料加工与生产良率"), ("energy_storage", "Industrial energy use and infrastructure", "工业能源使用与基础设施")],
}
SEO_TITLES = {
    "ai": ("AI News", "AI 新闻与人工智能动态"),
    "programmable_life": ("Biotech News", "生物技术新闻"),
    "energy_storage": ("Energy Storage News", "储能与新能源新闻"),
    "robotics_autonomy": ("Robotics News", "机器人新闻"),
    "quantum_technology": ("Quantum Computing News", "量子计算新闻"),
    "space_economy": ("Space News", "商业航天新闻"),
    "advanced_materials": ("Materials Science News", "材料科学与新材料新闻"),
    "neurotechnology": ("Neurotechnology News", "神经科技与脑机接口新闻"),
    "climate_water_environment": ("Climate & Water Tech News", "气候科技与水技术新闻"),
    "agrifood_technology": ("AgriTech & FoodTech News", "农业科技与食品技术新闻"),
    "advanced_manufacturing": ("Advanced Manufacturing News", "先进制造新闻"),
}

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
        _ = parsed.port
        return value if parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password else None
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
    if not isinstance(domain_id, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", domain_id):
        raise ValueError(f"Invalid field id: {domain_id!r}")
    return f"/{locale}/fields/{domain_id}/"


def hub_path(locale):
    return f"/{locale}/tech-news/"


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
    title_heading = SEO_TITLES.get(domain["id"], (values["heading"], values["heading"]))[0 if locale == "en" else 1]
    values["title"] = str(custom.get("title") or f'{title_heading} | {"Polyemergence" if locale == "en" else "多重涌现 Polyemergence"}')
    return values


def related_fields(domain_id, domains):
    registry = {domain["id"]: domain for domain in domains}
    return [entry for entry in RELATED_FIELDS.get(domain_id, []) if entry[0] in registry and entry[0] != domain_id]


def render_related_fields(domain_id, locale, domains):
    registry = {domain["id"]: domain for domain in domains}
    entries = related_fields(domain_id, domains)
    if not entries:
        entries = [(domain["id"], localized(domain.get("description"), "en"), localized(domain.get("description"), "zh"))
                   for domain in domains if domain["id"] != domain_id][:3]
    if not entries:
        return ""
    links = "".join(f'<li><a href="{field_path(locale, identifier)}">{esc(localized(registry[identifier].get("label"), locale, identifier))}</a>'
                    f'<p>{esc(en if locale == "en" else zh)}</p></li>' for identifier, en, zh in entries[:3])
    return f'<nav class="field-related-links" aria-label="{"Related fields" if locale == "en" else "关联领域"}"><h3>{"Related fields" if locale == "en" else "关联领域"}</h3><ul>{links}</ul></nav>'


def apply_metadata(page, locale, title, description, canonical, language_paths):
    page = re.sub(r"<title>.*?</title>", lambda _: f'<title>{esc(title)}</title>', page, count=1, flags=re.S)
    for key, attribute, value in [
        ("description", "name", description), ("og:title", "property", title),
        ("og:description", "property", description), ("og:url", "property", canonical),
        ("twitter:title", "name", title), ("twitter:description", "name", description),
    ]:
        page = re.sub(rf'<meta\b[^>]*\b{attribute}="{re.escape(key)}"[^>]*>', lambda _, k=key, a=attribute, v=value: f'<meta {a}="{k}" content="{esc(v)}">', page, count=1)
    page = re.sub(r'<link\b[^>]*\brel="canonical"[^>]*>', f'<link rel="canonical" href="{canonical}">', page, count=1)
    for language, target_locale in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
        page = re.sub(rf'<link\b[^>]*\bhreflang="{language}"[^>]*>', f'<link rel="alternate" hreflang="{language}" href="{SITE + language_paths[target_locale]}">', page, count=1)
    return page


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
        # A repeated ranking is a discovery signal, not a newly published story.
        # Real repository releases from other configured sources remain eligible.
        if str(item.get("source") or "").strip().casefold() == "github trending":
            continue
        published = parse_datetime(item.get("source_published_at") or item.get("published_at"))
        url = safe_url(item.get("url"))
        key = item.get("id") or url
        if (not published or not now - WINDOW <= published <= now or not url
                or float(item.get("importance") or 0) < 65 or key in seen):
            continue
        seen.add(key)
        selected.append(item)
    ordered = sorted(selected, key=lambda i: (float(i.get("importance") or 0), parse_datetime(i.get("source_published_at") or i.get("published_at"))), reverse=True)
    eligible, academic_count = [], 0
    for item in ordered:
        if item.get("category") == "academia":
            if (float(item.get("importance") or 0) < 70
                    or float((item.get("scores") or {}).get("confidence") or 0) < 65
                    or academic_count >= 2):
                continue
            academic_count += 1
        if item_domain(item, domains) == domain_id:
            eligible.append(item)
    return eligible


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
    # Double underscores can be actual technical identifiers (__init__,
    # checkpoint keys), so never erase them as generic Markdown decoration.
    return re.sub(r"\s+", " ", re.sub(r"\*\*|`", "", text)).strip()


def news_text(item, locale):
    text = item.get(locale) or item.get("en") or item.get("zh") or {}
    return clean_text(text.get("title") or item.get("title")), clean_text(text.get("summary") or text.get("full_summary"))


def localized_insight(value, locale):
    """Accept bilingual insight dictionaries and never turn them into repr text."""
    return clean_text(localized(value, locale)) if isinstance(value, (dict, str)) else ""


def evidence_labels(item, locale):
    labels = {
        "official_release": ("Official release", "官方发布"), "preprint": ("Preprint", "预印本"),
        "research_paper": ("Research paper", "研究论文"), "media_report": ("Media report", "媒体报道"),
        "interview": ("Interview", "访谈"), "open_source": ("Open source", "开源项目"), "unknown": ("Source type unconfirmed", "信源类型待确认"),
        "laboratory": ("Laboratory result", "实验室结果"), "demonstration": ("Demonstration", "演示"),
        "pilot": ("Pilot / trial", "试点／试验"), "deployment": ("Reported deployment", "报道已部署"),
        "unspecified": ("Stage not specified", "阶段未说明"),
    }
    return [labels.get((item.get("evidence") or {}).get(key), ("", ""))[0 if locale == "en" else 1] for key in ("type", "stage")]


def summary_inline(value):
    """Escape first; support only explicit bold and inline-code delimiters."""
    chunks = []
    for part in re.split(r"(`[^`\n]+`)", str(value or "")):
        if len(part) > 1 and part.startswith("`") and part.endswith("`"):
            chunks.append("<code>" + esc(part[1:-1]) + "</code>")
        else:
            chunks.append(re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", esc(part)))
    return "".join(chunks)


def summary_blocks(value):
    """Preserve full text with explicit line-start headings and paragraphs.

    Bare prose is never promoted to a heading. Arbitrary HTML and underscore
    identifiers remain escaped text; this is deliberately not a Markdown engine.
    """
    blocks, paragraph = [], []
    def flush():
        if paragraph:
            blocks.append("<p>" + summary_inline("\n".join(paragraph)) + "</p>")
            paragraph.clear()
    for line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        heading = re.match(r"^ {0,3}#{1,6}(?:[ \t]+|(?=[\u3400-\u9fff]))(.+?)\s*$", line)
        if not line.strip():
            flush()
        elif heading and heading[1].strip():
            flush()
            blocks.append("<h4>" + summary_inline(heading[1].strip()) + "</h4>")
        else:
            paragraph.append(line)
    flush()
    return "".join(blocks)


def story_image(item):
    """Use a supplied image, or the standard thumbnail of a linked video."""
    original = safe_url(item.get("url"))
    parsed = urlparse(original or "")
    video = (parsed.hostname or "").lower() in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
    video_id = None
    if video:
        if parsed.hostname == "youtu.be":
            match = re.fullmatch(r"/([\w-]{11})/?", parsed.path)
        elif parsed.path == "/watch":
            match = re.search(r"(?:^|&)v=([\w-]{11})(?:&|$)", parsed.query)
        else:
            match = re.fullmatch(r"/shorts/([\w-]{11})/?", parsed.path)
        if match:
            video_id = match[1]
    return (f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg" if video_id else safe_url(item.get("image_url"))), bool(video_id)


def story_markup(item, locale, corpus, public, lead=False, domains=None, tier="feature"):
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
    evidence_parts = evidence_labels(item, locale)
    heading_evidence = [part for key, part in zip(("type", "stage"), evidence_parts)
                        if part and (key != "stage" or (item.get("evidence") or {}).get(key) not in {None, "unknown", "unspecified"})]
    evidence_markup = '<div class="story-evidence">' + "".join(f'<span>{esc(part)}</span>' for part in heading_evidence) + '</div>' if heading_evidence else ""
    related = []
    labels = {domain["id"]: localized(domain.get("short_label") or domain.get("label"), locale, domain["id"]) for domain in (domains or [])}
    for domain in (item.get("related_domains") or [])[:2]:
        if domain in labels:
            related.append(f'<a href="{field_path(locale, domain)}">{esc(labels[domain])}</a>')
    related_markup = '<div class="story-related">' + " × ".join(related) + '</div>' if related else ""
    context = localized_insight(article_reading_context(item), locale)
    context_markup = f'<aside class="story-context"><strong>{"Observation focus (editorial lens)" if locale == "en" else "观察重点（编辑视角）"}</strong><p>{esc(context)}</p></aside>' if context else ""
    tags = "".join(f'<span class="tag">{esc(tag)}</span>' for tag in (item.get("tags") or [])[:4])
    tags_markup = f'<div class="tags">{tags}</div>' if tags else ""
    evidence_details = '<div class="screening-metadata">' + "".join(f'<span>{esc(part)}</span>' for part in evidence_parts if part) + '</div>'
    score_labels = {"signal": ("Signal", "信号"), "structure": ("Structure", "结构"), "consequence": ("Consequence", "影响"), "confidence": ("Confidence", "可信度"), "momentum": ("Momentum", "热度")}
    score_values = "".join(f'<span><small>{labels[0 if locale == "en" else 1]}</small><strong>{esc(str((item.get("scores") or {}).get(key) or 0))}</strong></span>' for key, labels in score_labels.items())
    screening = (f'<details class="screening-details"><summary>{"View selection rationale" if locale == "en" else "查看筛选依据"}</summary><p class="screening-importance">{"Importance" if locale == "en" else "重要性"} {esc(item.get("importance"))}/100</p><div class="score-breakdown">{score_values}</div>'
                 f'{evidence_details}{context_markup}{tags_markup}<p class="screening-note">{"Editorial assessments, not independent verification." if locale == "en" else "评分属于编辑评估，不代表独立核验。"} <a href="/{locale}/standards/">{"Editorial standards" if locale == "en" else "编辑标准"} →</a></p></details>')
    heading = (f'<div class="story-heading"><h3><a href="{esc(original)}" target="_blank" rel="noopener noreferrer">{esc(title)}</a></h3>'
               f'<div class="story-meta"><span class="story-source">{esc(item.get("source"))}</span>'
               f'<div class="story-published"><time datetime="{published.isoformat().replace("+00:00", "Z")}">{published_label} {date_label}</time></div></div>'
               f'{evidence_markup}{related_markup}</div>')
    text = item.get(locale) or item.get("en") or item.get("zh") or {}
    # A CSS preview clamp must never be the only copy of the summary. Native
    # disclosure remains usable before hydration and when JavaScript is absent.
    full_summary = str(text.get("full_summary") or text.get("long_summary") or summary).strip()
    full_markup = (f'<details class="summary-details" data-summary-details><summary>{"Expand summary" if locale == "en" else "展开摘要"}</summary>'
                   f'<div class="summary-full" data-summary-full>{summary_blocks(full_summary)}</div></details>') if full_summary else ""
    body = (f'<div class="story-body"><div class="story-summary"><p class="summary-preview" data-summary-short>{esc(summary)}</p>{full_markup}</div>'
            f'{screening}<div class="story-actions">{actions}</div></div>')
    image_url, video = story_image(item)
    is_brief = not lead and tier == "brief"
    if image_url and not is_brief:
        loading = 'fetchpriority="high"' if lead else 'loading="lazy"'
        candidates = list(dict.fromkeys([image_url, *(safe_url(url) for url in (item.get("image_candidates") or []) if isinstance(url, str))]))[:3]
        candidates = [url for url in candidates if url and url != "#"]
        image = f'<img class="media-contain" data-fallback-image data-image-candidates="{esc(json.dumps(candidates, ensure_ascii=False))}" src="{esc(image_url)}" alt="{esc(title)}" {loading} decoding="async" referrerpolicy="no-referrer">'
        caption_label = ("Video thumbnail" if video else "Source image") if locale == "en" else ("视频缩略图" if video else "原文配图")
        caption = f'{caption_label} · {item.get("source") or ""}'
        unavailable = "Original image temporarily unavailable" if locale == "en" else "原文配图暂不可用"
        retry = "Retry image" if locale == "en" else "重试图片"
        visual = (f'<figure class="{"story-visual" if lead else "card-visual"}" data-media-source="{esc(item.get("source"))}">'
                  f'<div class="visual-media">{image}<div class="text-edition-note" data-image-unavailable-note hidden>{unavailable}</div><button type="button" data-image-retry hidden>{retry}</button></div>'
                  f'<figcaption class="media-caption"><a href="{esc(original)}" target="_blank" rel="noopener noreferrer">{esc(caption)}</a></figcaption></figure>')
    else:
        visual = "" if is_brief else '<div class="text-edition-note">' + ("Text report · No source image available" if locale == "en" else "文字报道 · 暂无原文配图") + '</div>'
    if lead:
        return f'<div class="lead-copy">{heading}{visual}{body}</div>'
    classes = "story-card is-brief" if is_brief else "story-card is-feature"
    if not image_url or is_brief:
        classes += " is-text-led"
    return f'<article class="{classes}" data-story-id="{esc(item.get("id"))}"><div class="card-copy">{heading}{visual}{body}</div></article>'


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


def set_class_flag(page, tag, element_id, class_name, enabled):
    pattern = rf'<{tag}\b[^>]*\bid="{re.escape(element_id)}"[^>]*>'
    def update(match):
        opening = match[0]
        current = re.search(r'\bclass="([^"]*)"', opening)
        classes = current[1].split() if current else []
        classes = [value for value in classes if value != class_name]
        if enabled:
            classes.append(class_name)
        if current:
            return opening[:current.start()] + f'class="{" ".join(classes)}"' + opening[current.end():]
        return opening[:-1] + (f' class="{" ".join(classes)}">' if classes else ">")
    return re.sub(pattern, update, page, count=1)


def json_script(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_domain_links(locale, domains):
    return "".join(
        f'<a href="{field_path(locale, d["id"])}">'
        f'{esc(localized(d.get("short_label"), locale) or localized(d.get("label"), locale, d["id"]))}</a>'
        for d in domains
    )


def sync_home_navigation(shell, locale, domains):
    """Keep crawlable homepage links in step with the data-driven field registry."""
    cards = "".join(
        f'<a class="field-card" href="{field_path(locale, d["id"])}#brief">'
        f'<span class="field-card-top"><span class="field-number">{index:02d}</span>'
        '<span class="field-arrow" aria-hidden="true">↗</span></span>'
        f'<strong><span class="field-label-full">{esc(localized(d.get("label"), locale, d["id"]))}</span>'
        f'<span class="field-label-short">{esc(localized(d.get("short_label") or d.get("label"), locale, d["id"]))}</span></strong>'
        f'<span class="field-card-description">{esc(localized(d.get("description"), locale))}</span></a>'
        for index, d in enumerate(domains, 1)
    )
    shell = replace_content(shell, "div", "field-grid", cards)
    pattern = r'(<nav\b(?=[^>]*\bclass="[^"]*\bfooter-topics\b)[^>]*>).*?(</nav>)'
    shell, count = re.subn(pattern, lambda m: m[1] + render_domain_links(locale, domains) + m[2], shell, count=1, flags=re.S)
    if not count:
        raise ValueError("Home shell is missing .footer-topics")
    return shell


def observation_markup(cards, locale, public, now, generated_at=None, refresh_path=None):
    """Render public evidence, never claims of independent trend validation."""
    rendered = []
    for card in cards[:3]:
        evidence = []
        for item in card.get("evidence", []):
            url = safe_url(item.get("url"))
            published = parse_datetime(item.get("date"))
            if not url or not published or not now - timedelta(days=30) <= published <= now:
                continue
            title = localized_insight(item.get("title"), locale)
            canonical = (item.get("canonical_urls") or {}).get(locale)
            summary_link = ""
            if safe_url(canonical):
                parts = urlparse(canonical)
                if parts.netloc == "polyemergence.com" and re.fullmatch(rf"/{locale}/archive/\d{{4}}/\d{{2}}/\d{{2}}/[A-Za-z0-9_-]+/", parts.path) and (public / parts.path.lstrip("/") / "index.html").is_file():
                    summary_link = f' · <a href="{esc(SITE + parts.path)}">{"Our summary" if locale == "en" else "本站摘要"}</a>'
            evidence.append(f'<li><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(title)} ↗</a><span>{esc(item.get("source"))} · <time datetime="{esc(item.get("date"))}">{published:%Y-%m-%d}</time>{summary_link}</span></li>')
        if not evidence:
            continue
        # Public lexical groupings are not editor-confirmed independent events.
        status = "Signal to examine" if locale == "en" else "待验证信号"
        rendered.append(f'<article class="observation-card"><span class="observation-status">{status}</span><h3>{esc(localized_insight(card.get("title"), locale))}</h3>'
                        f'<p>{esc(localized_insight(card.get("change"), locale))}</p><p class="observation-uncertainty">{esc(localized_insight(card.get("uncertainty"), locale))}</p>'
                        f'<p class="observation-next"><strong>{"Next check" if locale == "en" else "下一步看什么"}</strong> {esc(localized_insight(card.get("next_check"), locale))}</p>'
                        f'<details class="observation-evidence"><summary>{"Reported evidence" if locale == "en" else "查看报道证据"} ({len(evidence)})</summary><ul>{"".join(evidence)}</ul></details></article>')
    if not rendered:
        return ""
    heading = "Signals worth following" if locale == "en" else "持续观察"
    generated = parse_datetime(generated_at)
    if generated:
        label = generated.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")
        snapshot = f'<time datetime="{esc(generated_at)}">{label}</time>'
        snapshot = (f"30-day evidence snapshot as of {snapshot}." if locale == "en" else f"截至 {snapshot} 的 30 天证据快照。")
    else:
        snapshot = "Evidence snapshot · capture time unavailable." if locale == "en" else "证据快照 · 快照时间未知。"
    note = ("Separate from the 48-hour brief: changes worth checking next, with links to the underlying reports. These are tentative leads, not predictions or established trends. Topics appear only when relevant evidence is available." if locale == "en" else "与 48 小时日报分开，追踪值得继续核查的变化，并附上相关报道。它们是待验证的线索，不是预测或已经证实的趋势；没有合适证据的主题不补位。")
    refresh_path = refresh_path or f"/{locale}/#fields"
    refresh = f'<a class="observation-refresh" data-observation-refresh href="{esc(refresh_path)}">{"Refresh evidence snapshot" if locale == "en" else "刷新证据快照"} ↻</a>'
    return f'<div class="section-heading"><p class="section-index">30 DAYS</p><h2>{heading}</h2><p class="observation-snapshot-time">{snapshot} {refresh}</p><p>{note}</p></div><div class="observation-grid">{"".join(rendered)}</div>'


def render_field_page(shell, domain, locale, domains, feed, sources, corpus, public, now, observations=None):
    copy = seo_copy(domain, locale)
    url = SITE + field_path(locale, domain["id"])
    items = [enrich_item(item) for item in current_items(feed, domain["id"], domains, now)]
    page = re.sub(r"<html\b([^>]*)>", lambda m: f'<html{m[1]} data-field="{esc(domain["id"])}">', shell, count=1)
    page = re.sub(r'<body\b([^>]*)>', lambda m: ('<body' + re.sub(r'\bclass="([^"]*)"', lambda c: f'class="{c[1]} is-field-page"', m[1]) + '>') if 'class="' in m[1] else f'<body{m[1]} class="is-field-page">', page, count=1)
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
    page = replace_content(page, "h2", "brief-title", "Today’s selection" if locale == "en" else "今日精选")
    if not re.search(r'\bid="field-reading-guidance"', page):
        page = re.sub(r'(<section\b[^>]*\bid="brief"[^>]*>)', r'\1<aside id="field-reading-guidance" class="field-reading-guidance" hidden></aside>', page, count=1)
    guidance = localized(domain.get("reading_guidance") or reading_guidance(domain["id"]), locale)
    guidance_note = "General field guidance, not verification of this story." if locale == "en" else "领域通用指引，不是对单篇报道的核验结论。"
    guidance_html = f'<details><summary>{"Reading guide" if locale == "en" else "阅读提示"}</summary><p>{esc(guidance)}</p><small>{guidance_note}</small></details>'
    page = replace_content(page, "aside", "field-reading-guidance", guidance_html)
    page = set_hidden(page, "aside", "field-reading-guidance", not bool(guidance))
    page = re.sub(r'(<aside\b[^>]*\bid="field-reading-guidance"[^>]*)(>)', lambda m: m[1] + f' data-field="{esc(domain["id"])}"' + m[2], page, count=1)
    page = replace_content(page, "p", "field-description", esc(localized(domain.get("description"), locale)))
    page = replace_content(page, "div", "lead-story", story_markup(items[0], locale, corpus, public, True, domains) if items else "")
    page = set_class_flag(page, "div", "lead-story", "is-text-led", bool(items and not story_image(items[0])[0]))
    if items:
        page = re.sub(r'(<div\b[^>]*\bid="lead-story"[^>]*)(>)', lambda m: m[1] + f' data-story-id="{esc(items[0].get("id"))}"' + m[2], page, count=1)
    features, briefs = items[1:4], items[4:]
    sections = []
    if features:
        sections.append('<section class="feature-section"><h3 class="edition-subheading">'
                        + ("Highlights" if locale == "en" else "重点报道") + '</h3><div class="feature-grid">'
                        + "".join(story_markup(item, locale, corpus, public, domains=domains, tier="feature") for item in features)
                        + '</div></section>')
    if briefs:
        sections.append('<section class="brief-section"><h3 class="edition-subheading">'
                        + ("More briefs" if locale == "en" else "更多简讯") + '</h3><div class="brief-grid">'
                        + "".join(story_markup(item, locale, corpus, public, domains=domains, tier="brief") for item in briefs)
                        + '</div></section>')
    page = replace_content(page, "div", "story-grid", "".join(sections))
    page = set_hidden(page, "div", "lead-story", not items)
    page = set_hidden(page, "div", "story-grid", len(items) <= 1)
    empty = ("No qualifying stories from the past 48 hours. Explore the field coverage and sources below, or browse the archive." if locale == "en" else "最近 48 小时内暂无符合筛选标准的新闻。可以阅读下方领域介绍与信息源，或浏览历史归档。")
    page = replace_content(page, "div", "empty-state", esc(empty))
    page = set_hidden(page, "div", "empty-state", bool(items))
    generated = parse_datetime(feed.get("generated_at"))
    if generated and generated <= now:
        edition_time = generated.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")
        status = ("Updated " if locale == "en" else "更新于 ") + edition_time
        page = replace_content(page, "span", "update-status", esc(status))
        edition = edition_time + (" · 48-hour source publication window" if locale == "en" else " · 原文发布 48 小时窗口")
    else:
        edition = "48-hour source publication window · Edition time unavailable" if locale == "en" else "原文发布 48 小时窗口 · 版本时间未知"
    edition_note = re.search(r'<([a-z][a-z0-9]*)\b[^>]*\bid="edition-note"', page)
    if edition_note:
        page = replace_content(page, edition_note[1], "edition-note", esc(edition))
    source_list = field_sources(domain["id"], sources, domains)
    heading = "Field coverage" if locale == "en" else "领域覆盖"
    source_heading = "Sources we follow" if locale == "en" else "关注的信息源"
    source_note = ("A selection of configured official, research and specialist sources. A source is not a guarantee that every item will be selected." if locale == "en" else "以下为已配置的官方、研究机构与专业媒体来源。来源中的内容仍需经过筛选，并非每篇都会入选。")
    source_links = "".join(f'<li><a href="{esc(source_home(s[0]))}" target="_blank" rel="noopener noreferrer">{esc(s[1])}</a></li>' for s in source_list)
    evergreen = (f'<div><p class="section-index">{heading}</p><h2>{esc(copy["heading"])}</h2><p>{esc(copy["intro"])}</p>'
                 + (f'<p class="field-scope">{esc(copy["scope"])}</p>' if copy["scope"] else "")
                 + f'<p><a class="tech-news-hub-link" href="{hub_path(locale)}">{"Tech News: all fields" if locale == "en" else "科技新闻总览：所有领域"}</a> · <a href="/{locale}/archive/">{"Browse historical editions" if locale == "en" else "浏览历史归档"} →</a> · <a href="/{locale}/standards/">{"Editorial standards" if locale == "en" else "编辑标准"}</a></p></div>'
                 + (f'<div id="field-sources"><h3>{source_heading}</h3><p>{source_note}</p><ul>{source_links}</ul></div>' if source_links else f'<div id="field-sources"><h3>{source_heading}</h3><p>{"Source coverage for this field is still being configured. Stories are not added merely to fill the briefing." if locale == "en" else "本领域的信息源仍在配置中，不会为填充简报而补入新闻。"}</p></div>')
                 + render_related_fields(domain["id"], locale, domains))
    page = replace_content(page, "section", "field-seo-content", evergreen)
    page = set_hidden(page, "section", "field-seo-content", False)
    page = re.sub(r'(<section\b[^>]*\bid="field-seo-content"[^>]*)(>)', lambda m: m[1] + f' data-field="{domain["id"]}"' + m[2], page, count=1)
    observation_payload = observations or {}
    snapshot_date = parse_datetime(observation_payload.get("generated_at"))
    window_start = parse_datetime(observation_payload.get("window_start"))
    if snapshot_date and not window_start:
        window_start = snapshot_date - timedelta(days=30)
    observations_html = observation_markup(observation_payload.get("fields", {}).get(domain["id"], []), locale, public, now,
                                           generated_at=observation_payload.get("generated_at"), refresh_path=field_path(locale, domain["id"]) + "#field-observations")
    if not re.search(r'<section\b[^>]*\bid="field-observations"', page):
        page = page.replace('<section id="field-seo-content"', '<section id="field-observations" class="field-observations" hidden></section>\n<section id="field-seo-content"', 1)
    page = replace_content(page, "section", "field-observations", observations_html)
    page = set_hidden(page, "section", "field-observations", not bool(observations_html))
    snapshot_attrs = f' data-field="{domain["id"]}"'
    if snapshot_date:
        snapshot_attrs += f' data-generated-at="{snapshot_date.isoformat().replace("+00:00", "Z")}"'
    if window_start:
        snapshot_attrs += f' data-window-start="{window_start.isoformat().replace("+00:00", "Z")}"'
    page = re.sub(r'(<section\b[^>]*\bid="field-observations"[^>]*)(>)', lambda m: m[1] + snapshot_attrs + m[2], page, count=1)
    observation_section = re.search(r'<section\b[^>]*\bid="field-observations"[^>]*>.*?</section>', page, re.S)
    if observation_section:
        page = page[:observation_section.start()] + page[observation_section.end():]
        page = page.replace('<section id="field-seo-content"', observation_section[0] + '\n<section id="field-seo-content"', 1)
    # Replace the generic homepage graph with truthful collection/list data.
    graph = {
        "@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": SITE + "/#organization", "name": "Polyemergence", "legalName": "PolyEmergence Pte Ltd.", "url": SITE + "/"},
            {"@type": "WebSite", "@id": SITE + "/#website", "name": "Polyemergence", "url": SITE + "/"},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Fields" if locale == "en" else "领域", "item": SITE + f"/{locale}/#fields"},
                {"@type": "ListItem", "position": 2, "name": localized(domain.get("label"), locale), "item": url},
            ]},
            {"@type": "CollectionPage", "@id": url + "#page", "url": url, "name": copy["heading"], "description": copy["description"], "inLanguage": "en" if locale == "en" else "zh-Hans", "about": {"@type": "Thing", "name": localized(domain.get("label"), locale), "description": copy["intro"]}, "isPartOf": {"@id": SITE + "/#website"}, "publisher": {"@id": SITE + "/#organization"}, "mainEntity": {"@id": url + "#brief-list"}},
            {"@type": "ItemList", "@id": url + "#brief-list", "name": ("Past 48 hours" if locale == "en" else "最近 48 小时"), "numberOfItems": len(items), "itemListElement": [{"@type": "ListItem", "position": n, "name": news_text(item, locale)[0], "url": archive_url(item, locale, corpus, public) or safe_url(item.get("url"))} for n, item in enumerate(items, 1)]},
        ],
    }
    page = re.sub(r'<script\b[^>]*type="application/ld\+json"[^>]*>.*?</script>', lambda _: '<script type="application/ld+json">' + json_script(graph) + '</script>', page, count=1, flags=re.S)
    return "\n".join(line.rstrip() for line in page.split("\n"))


def render_hub_page(shell, locale, domains, feed, sources, now):
    """A genuine field directory, not an unchosen mixed-domain news feed."""
    copy = HUB_COPY[locale]
    path = hub_path(locale)
    canonical = SITE + path
    page = re.sub(r'<html\b([^>]*)>', lambda m: f'<html{m[1]} data-page="tech-news">', shell, count=1)
    page = re.sub(r'<body\b([^>]*)>', lambda m: ('<body' + re.sub(r'\bclass="([^"]*)"', lambda c: f'class="{c[1]} is-tech-news-page"', m[1]) + '>') if 'class="' in m[1] else f'<body{m[1]} class="is-tech-news-page">', page, count=1)
    page = apply_metadata(page, locale, copy["title"], copy["description"], canonical, {language: hub_path(language) for language in ("en", "zh")})
    page = replace_content(page, "h1", "intro-title", esc(copy["heading"]))
    page = re.sub(r'(<p\b[^>]*\bdata-copy="promise"[^>]*>).*?</p>', lambda m: m[1] + esc(copy["description"]) + '</p>', page, count=1, flags=re.S)
    page = re.sub(r'(<p\b[^>]*\bdata-copy="eyebrow"[^>]*>).*?</p>', lambda m: m[1] + ("TECH NEWS · CHOOSE A FIELD" if locale == "en" else "科技新闻 · 按领域阅读") + '</p>', page, count=1, flags=re.S)
    for language in ("en", "zh"):
        page = re.sub(rf'(<a\b[^>]*\bdata-locale-button="{language}"[^>]*>)', lambda m, lang=language: re.sub(r'href="[^"]*"', f'href="{hub_path(lang)}"', m[0]), page)
    for tag, identifier in (("section", "fields"), ("section", "brief"), ("section", "field-observations"), ("section", "field-seo-content"), ("aside", "field-reading-guidance")):
        page = set_hidden(page, tag, identifier, True)
    # The shell's data-managed sections remain empty; only field selection is
    # visible in this independently addressable, indexable hub section.
    page = replace_content(page, "div", "lead-story", "")
    page = replace_content(page, "div", "story-grid", "")
    generated = parse_datetime(feed.get("generated_at"))
    if generated and generated <= now:
        page = replace_content(page, "span", "update-status", esc(("Feed updated " if locale == "en" else "数据更新于 ") + generated.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")))
    counted_at = now.astimezone(SGT).strftime("%Y-%m-%d %H:%M SGT")
    count_note = (f"Selection counts as of {counted_at}, using original publication times within the preceding 48 hours. These are published snapshot counts, not measures of a field’s overall activity. Empty briefings are not padded."
                  if locale == "en" else f"精选数量统计于 {counted_at}，仅计算此前 48 小时内原始发布且符合标准的内容。这是页面发布时的数量快照，不代表领域整体活跃度；没有达标内容时不补位。")
    cards = []
    for domain in domains:
        field_copy = seo_copy(domain, locale)
        field_url = field_path(locale, domain["id"])
        count = len(current_items(feed, domain["id"], domains, now))
        count_text = f'{count} selected {"story" if count == 1 else "stories"} · 48h' if locale == "en" else f'已精选 {count} 条 · 48 小时'
        selected_sources = field_sources(domain["id"], sources, domains)[:3]
        source_links = "".join(f'<li><a href="{esc(source_home(source[0]))}" target="_blank" rel="noopener noreferrer">{esc(source[1])}</a></li>' for source in selected_sources)
        source_markup = ('<p class="hub-source-label">' + ("Configured source examples" if locale == "en" else "已配置的信息源示例") + '</p><ul class="hub-source-list">' + source_links + '</ul>') if source_links else '<p class="hub-source-label">' + ("Source coverage is still being configured." if locale == "en" else "信息源仍在配置中。") + '</p>'
        empty_note = ('<p class="hub-field-empty">' + ("No qualifying stories in the current 48-hour window. Field coverage and source notes remain available." if locale == "en" else "当前 48 小时内暂无达标新闻，仍可查看领域覆盖范围与信息源。") + '</p>') if not count else ""
        cards.append(f'<article class="tech-news-card" data-domain="{esc(domain["id"])}"><div class="hub-field-heading"><h3><a href="{field_url}">{esc(field_copy["heading"])}</a></h3><span class="tech-news-count" data-field-count="{esc(domain["id"])}">{count_text}</span></div>'
                     f'<p>{esc(field_copy["intro"])}</p>' + (f'<p class="field-scope">{esc(field_copy["scope"])}</p>' if field_copy["scope"] else "")
                     + empty_note + source_markup + f'<p class="hub-field-actions"><a href="{field_url}#brief">{"Read this field briefing" if locale == "en" else "进入领域简报"} →</a> · <a href="{field_url}#field-sources">{"Coverage and sources" if locale == "en" else "覆盖范围与信息源"}</a></p></article>')
    resources = f'<nav class="tech-news-method" aria-label="{"Reading resources" if locale == "en" else "阅读资源"}"><a href="/{locale}/standards/">{"Editorial standards and verification limits" if locale == "en" else "编辑标准与核验边界"}</a><a href="/{locale}/archive/">{"Permanent archive" if locale == "en" else "永久历史归档"}</a><a href="/{locale}/#about">{"Selection method" if locale == "en" else "筛选方法"}</a></nav>'
    hub = f'<section id="tech-news-hub" class="tech-news-hub" aria-label="{esc(copy["heading"])}" data-counted-at="{now.isoformat().replace("+00:00", "Z")}"><p class="tech-news-intro">{esc(copy["intro"])}</p><p class="hub-count-note">{esc(count_note)}</p>{resources}<h2>{"Choose a technology field" if locale == "en" else "选择科技领域"}</h2><div id="tech-news-field-directory" class="tech-news-grid">{"".join(cards)}</div></section>'
    page, inserted = re.subn(r'(<section\b[^>]*\bid="fields"[^>]*>)', lambda m: hub + '\n' + m[0], page, count=1)
    if not inserted:
        raise ValueError("Home shell is missing #fields for the tech news hub")
    graph = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "@id": SITE + "/#organization", "name": "Polyemergence", "legalName": "PolyEmergence Pte Ltd.", "url": SITE + "/"},
        {"@type": "WebSite", "@id": SITE + "/#website", "name": "Polyemergence", "url": SITE + "/"},
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Polyemergence", "item": SITE + f"/{locale}/"},
            {"@type": "ListItem", "position": 2, "name": copy["heading"], "item": canonical}]},
        {"@type": "CollectionPage", "@id": canonical + "#page", "url": canonical, "name": copy["heading"], "description": copy["description"], "inLanguage": "en" if locale == "en" else "zh-Hans", "isPartOf": {"@id": SITE + "/#website"}, "publisher": {"@id": SITE + "/#organization"}, "mainEntity": {"@id": canonical + "#tech-news-field-directory"}},
        {"@type": "ItemList", "@id": canonical + "#tech-news-field-directory", "name": "Technology news fields" if locale == "en" else "科技新闻领域", "numberOfItems": len(domains), "itemListElement": [{"@type": "ListItem", "position": index, "name": seo_copy(domain, locale)["heading"], "url": SITE + field_path(locale, domain["id"])} for index, domain in enumerate(domains, 1)]},
    ]}
    page = re.sub(r'<script\b[^>]*type="application/ld\+json"[^>]*>.*?</script>', lambda _: '<script type="application/ld+json">' + json_script(graph) + '</script>', page, count=1, flags=re.S)
    return "\n".join(line.rstrip() for line in page.split("\n"))


def export(public, registry_path, feed_path, sources_path, articles_path=None, now=None, observations_path=None):
    now = now or datetime.now(timezone.utc)
    registry = json.loads(Path(registry_path).read_text(encoding="utf-8"))
    domains = sorted(registry["domains"], key=lambda d: d.get("order", 999))
    # Reject unsafe paths before changing either homepage or any generated page.
    for domain in domains:
        field_path("en", domain["id"])
    feed = json.loads(Path(feed_path).read_text(encoding="utf-8"))
    sources = load_sources(sources_path)
    corpus = {}
    if articles_path and Path(articles_path).is_file():
        corpus = {str(item.get("id")): item for item in json.loads(Path(articles_path).read_text(encoding="utf-8")).get("items", [])}
    observations_path = Path(observations_path) if observations_path else public / "data/observations.json"
    observations = json.loads(observations_path.read_text(encoding="utf-8")) if observations_path.is_file() else {}
    urls = []
    for locale in ("en", "zh"):
        home = public / locale / "index.html"
        shell = sync_home_navigation(home.read_text(encoding="utf-8"), locale, domains)
        home.write_text(shell, encoding="utf-8")
        destination = public / hub_path(locale).lstrip("/") / "index.html"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_hub_page(shell, locale, domains, feed, sources, now), encoding="utf-8")
        urls.append(SITE + hub_path(locale))
        for domain in domains:
            path = field_path(locale, domain["id"])
            destination = public / path.lstrip("/") / "index.html"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render_field_page(shell, domain, locale, domains, feed, sources, corpus, public, now, observations), encoding="utf-8")
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
    parser.add_argument("--observations", type=Path, default=ROOT / "web/public/data/observations.json")
    args = parser.parse_args()
    count = export(args.output, args.registry, args.feed, args.sources, args.articles, observations_path=args.observations)
    print(f"Exported {count} bilingual field and tech news hub pages, plus field-sitemap.xml")


if __name__ == "__main__":
    main()
