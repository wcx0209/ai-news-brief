#!/usr/bin/env python3
"""Build cautious, evidence-linked 30-day observation cards without an LLM.

This is a curated question catalogue, not a trend detector. Matching articles
support a question worth following; neither article counts nor source diversity
establish that the proposed change is true.
"""

import argparse
import json
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent
WINDOW_DAYS = 30
MAX_CARDS = 3


def topic(identifier, groups, en, zh, question_en, question_zh, check_en, check_zh):
    return {"id": identifier, "groups": groups, "title": {"en": en, "zh": zh},
            "change": {"en": question_en, "zh": question_zh},
            "next_check": {"en": check_en, "zh": check_zh}}


# Each group must match; alternatives within a group are ORed. Specific terms
# keep generic funding, company and climate stories out of technical themes.
TOPICS = {
    "ai": [topic("agents-in-use", [["ai agent", "agentic", "智能体"], ["deploy", "production", "workflow", "adoption", "部署", "工作流", "应用"]], "AI agents beyond the demo", "AI 智能体能否走出演示", "Are AI agents moving into repeatable everyday work? These reports are leads to examine, not proof of reliable autonomy.", "AI 智能体是否正在进入可重复的日常工作？这些报道提供观察线索，不证明其已具备可靠自主性。", "Look for repeated task success, human intervention, failure rates and actual customer use.", "关注重复任务成功率、人工干预、失败情况及真实客户使用。"),
           topic("compute-power", [["data center", "data centre", "ai compute", "数据中心", "AI 算力"], ["power", "electric", "energy", "grid", "电力", "能源", "电网"]], "The power behind AI compute", "AI 算力背后的供电条件", "Are power and grid constraints changing the pace or location of AI infrastructure?", "电力与电网约束是否正在改变 AI 基础设施建设的速度或选址？", "Check connected capacity, operating dates, energy demand and disclosed supply contracts.", "核查已接入容量、投运日期、耗电量与披露的供电合同。")],
    "programmable_life": [topic("engineered-biology-scale", [["synthetic biology", "biomanufactur", "fermentation", "合成生物", "生物制造", "发酵"], ["scale", "manufactur", "production", "commercial", "规模", "生产", "商业"]], "Engineered biology at production scale", "工程化生命能否走向规模生产", "Can engineered biology move from promising experiments to repeatable production?", "工程化生命能否从实验结果走向可重复的规模生产？", "Check yields, batch consistency, manufacturing cost and regulatory status.", "核查产率、批次一致性、制造成本及监管状态。")],
    "energy_storage": [topic("long-storage", [["long-duration", "long duration", "flow battery", "iron-air", "长时储能", "液流电池", "铁空气电池"], ["storage", "battery", "grid", "储能", "电池", "电网"]], "Long-duration storage in real systems", "长时储能的真实系统表现", "Which long-duration storage approaches are progressing beyond laboratory performance?", "哪些长时储能路线正在走出实验室指标？", "Check delivered capacity, duration, cycling life, cost and sustained operation.", "核查实际交付容量、时长、循环寿命、成本及持续运行表现。")],
    "robotics_autonomy": [topic("robots-at-work", [["humanoid", "industrial robot", "warehouse robot", "robotic arm", "robot arm", "mobile robot", "quadruped", "biped", "embodied robot", "人形机器人", "工业机器人", "仓储机器人", "机械臂", "移动机器人", "四足机器人", "具身机器人"], ["factory", "warehouse", "deploy", "production", "工厂", "仓库", "部署", "生产"]], "Robots doing repeatable work", "机器人能否完成可重复工作", "Are robots progressing from staged demonstrations to useful repeated work?", "机器人是否正在从演示走向有用且可重复的工作？", "Check operating hours, task success, human intervention, safety and customer deployments.", "核查运行时长、任务成功率、人工干预、安全及客户部署。")],
    "quantum_technology": [topic("logical-qubits", [["logical qubit", "quantum error correction", "fault-tolerant quantum", "逻辑量子比特", "量子纠错", "容错量子"]], "The engineering of logical qubits", "逻辑量子比特的工程进展", "Are error-corrected quantum systems improving on measured, comparable tasks?", "纠错量子系统是否在可测量、可比较的任务中持续改善？", "Check logical error rates, physical resources, repeated tests and classical baselines.", "核查逻辑错误率、物理资源、重复测试及经典计算基线。")],
    "space_economy": [topic("reusable-launch", [["reusab", "reflight", "重复使用", "复飞"], ["launch", "rocket", "booster", "发射", "火箭", "助推器"]], "Reusable launch in operation", "可重复使用发射的实际运行", "Is reuse translating into reliable launch operations rather than isolated milestones?", "重复使用是否正在转化为可靠发射运营，而非孤立里程碑？", "Check completed flights, turnaround time, reliability and disclosed operating costs.", "核查已完成飞行、周转时间、可靠性及披露的运营成本。")],
    "advanced_materials": [topic("materials-scale", [["advanced material", "nanomaterial", "metamaterial", "semiconductor material", "composite material", "graphene", "新材料", "纳米材料", "超材料", "复合材料", "半导体材料", "石墨烯"], ["scale", "manufactur", "pilot", "production", "规模", "制造", "中试", "生产"]], "New materials beyond the laboratory", "新材料能否走出实验室", "Which new material properties survive the move toward repeatable manufacturing?", "哪些新材料性能能够在可重复制造中得到保留？", "Check independent measurements, durability, feedstock and production yield.", "核查独立测量、耐久性、原料及生产良率。")],
    "neurotechnology": [topic("bci-human-use", [["brain-computer", "brain computer", "neural implant", "脑机接口", "神经植入"], ["human", "patient", "clinical", "trial", "人体", "患者", "临床", "试验"]], "Brain-computer interfaces in human use", "脑机接口的人体使用进展", "Are brain-computer interfaces improving sustained function for people?", "脑机接口能否为使用者带来持续的功能改善？", "Check participant numbers, follow-up duration, safety and performance outside supervised sessions.", "核查参与人数、随访时间、安全及监督实验之外的表现。")],
    "climate_water_environment": [topic("carbon-removal", [["carbon remov", "direct air capture", "碳移除", "直接空气捕集"], ["plant", "scale", "capacity", "cost", "工厂", "规模", "产能", "成本"]], "Carbon removal at useful scale", "碳移除的有效规模", "Can carbon-removal projects demonstrate durable net removal at practical scale?", "碳移除项目能否在实际规模上证明持久的净移除效果？", "Check lifecycle net removal, energy use, storage permanence and independently audited delivery.", "核查全生命周期净移除量、能耗、储存持久性及独立审计交付。")],
    "agrifood_technology": [topic("fermentation-food", [["precision fermentation", "cultivated", "alternative protein", "精准发酵", "细胞培养", "替代蛋白"], ["food", "protein", "production", "approval", "食品", "蛋白", "生产", "批准"]], "New food production becoming practical", "新型食品生产的落地条件", "Are new protein and fermentation methods becoming viable food-production systems?", "新蛋白与发酵方法是否正在成为可行的食品生产系统？", "Check production cost, yields, regulatory clearance, nutrition and actual sales.", "核查生产成本、产率、监管许可、营养及真实销售。")],
    "advanced_manufacturing": [topic("additive-production", [["additive manufactur", "3d print", "3-d print", "增材制造", "3D 打印", "3d打印"], ["production", "industrial", "factory", "scale", "生产", "工业", "工厂", "规模"]], "Additive manufacturing in production", "增材制造走向生产", "Where is additive manufacturing becoming repeatable production rather than prototyping?", "增材制造在哪些场景正从原型制作走向可重复生产？", "Check throughput, defect rates, unit cost, certification and customer use.", "核查产能、缺陷率、单位成本、认证及客户使用。")],
}


def parse_datetime(value):
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def safe_url(value):
    value = str(value or "")
    if re.search(r"[\x00-\x20\\]", value):
        return None
    try:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
            return None
        _ = parts.port
        return value
    except ValueError:
        return None


def canonical_url(value):
    value = safe_url(value)
    if not value:
        return None
    parts = urlsplit(value)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
             if not k.lower().startswith("utm_") and k.lower() not in {"fbclid", "gclid", "ref", "source"}]
    return urlunsplit(("https", parts.netloc.lower().removeprefix("www."), parts.path.rstrip("/") or "/", urlencode(sorted(query)), ""))


def publisher(value):
    host = (urlsplit(value).hostname or "").lower().removeprefix("www.")
    labels = host.split(".")
    # Standard-library-only conservative registrable-domain approximation.
    compound = {"co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "org.au", "com.cn", "org.cn", "com.sg", "gov.sg", "co.jp", "ac.jp", "go.jp", "co.in", "co.nz", "com.br", "co.kr", "or.kr"}
    count = 3 if ".".join(labels[-2:]) in compound else 2
    return ".".join(labels[-count:])


def article_text(item):
    values = []
    for locale in ("en", "zh"):
        copy = item.get(locale) or {}
        values.extend(str(copy.get(key) or "") for key in ("title", "summary", "full_summary"))
    return " ".join(values).casefold()


def matches(item, config):
    text = article_text(item)
    def term_matches(term):
        term = term.casefold()
        if re.search(r"[\u3400-\u9fff]", term):
            return term in text
        # Prefix matching is explicit, never an arbitrary substring (Thai is
        # not AI). The final token may inflect, while preceding words stay exact.
        stems = {"manufactur", "reusab", "carbon remov", "deploy", "commercial"}
        suffix = r"\w*" if term in stems else r"s?" if term.endswith(("qubit", "robot", "material", "plant", "battery", "neural implant", "ai agent")) else ""
        return bool(re.search(r"(?<!\w)" + re.escape(term) + suffix + r"(?!\w)", text))
    return all(any(term_matches(term) for term in alternatives) for alternatives in config["groups"])


STOPWORDS = set("the a an of and or to for in on with from by at new how what why is are as its it this that an announces announce announced launches launch launched releases release released introducing unveils unveiled says said company research researchers study report reports ai system systems".split())
ENTITIES = ("openai", "anthropic", "google", "deepmind", "meta", "nvidia", "microsoft", "ibm", "spacex", "rocket lab", "blue origin", "neuralink", "synchron", "braingate", "tesla", "figure", "boston dynamics", "dwave", "d-wave", "ionq", "quantinuum", "rigetti")


def fingerprint(item, locale="en"):
    title = str((item.get(locale) or {}).get("title") or "")
    normalized = re.sub(r"[^\w\s]", " ", title.casefold())
    tokens = {token for token in normalized.split() if len(token) > 2 and token not in STOPWORDS}
    # Product-version tokens and known entities provide conservative cross-source
    # event keys. Broad same-company launches within three days are merged rather
    # than inflated; this intentionally undercounts when evidence is ambiguous.
    entities = {name for name in ENTITIES if name in title.casefold()}
    entities.update(re.findall(r"\b[a-z]+[- ]?\d+(?:[.\-][a-z0-9]+)*\b", title.casefold()))
    event = next((key for key, pattern in (("launch", r"launch|releas|introduc|unveil|发布|推出"), ("funding", r"funding|raises|investment|融资|投资"), ("trial", r"trial|patient|clinical|试验|临床|患者"), ("result", r"demonstrat|achiev|error|qubit|breakthrough|结果|突破|量子比特")) if re.search(pattern, title.casefold())), None)
    return normalized, tokens, entities, event


def same_event(left, right):
    if canonical_url(left.get("url")) == canonical_url(right.get("url")):
        return True
    days = abs((parse_datetime(left.get("source_published_at") or left.get("published_at")) - parse_datetime(right.get("source_published_at") or right.get("published_at"))).total_seconds()) / 86400
    for locale in ("en", "zh"):
        a, at, ae, av = fingerprint(left, locale)
        b, bt, be, bv = fingerprint(right, locale)
        if not a or not b:
            continue
        if a == b or SequenceMatcher(None, a, b).ratio() >= .78:
            return True
        shared = at & bt
        if len(shared) >= 3 and len(shared) / max(1, min(len(at), len(bt))) >= .65:
            return True
        if days <= 3 and ae & be and av and av == bv:
            return True
    return False


def observation_cards(payload, now=None, topics=None):
    now = now or datetime.now(timezone.utc)
    topics = TOPICS if topics is None else topics
    eligible = []
    for item in payload.get("items", []):
        if str(item.get("source") or "").strip().casefold() == "github trending":
            continue
        date = parse_datetime(item.get("source_published_at") or item.get("published_at"))
        if date and now - timedelta(days=WINDOW_DAYS) <= date <= now and safe_url(item.get("url")):
            eligible.append(item)
    fields = {}
    for field, configs in topics.items():
        cards = []
        for config in configs:
            selected = [item for item in eligible if field in [item.get("domain"), *(item.get("related_domains") or [])] and matches(item, config)]
            selected.sort(key=lambda item: str(item.get("source_published_at") or item.get("published_at")), reverse=True)
            clusters = []
            for item in selected:
                group = next((group for group in clusters if any(same_event(item, old) for old in group)), None)
                if group is None:
                    clusters.append([item])
                else:
                    group.append(item)
            if not clusters:
                continue
            publishers = {publisher(item["url"]) for item in selected}
            evidence = []
            for event_index, group in enumerate(clusters):
                for item in group:
                    date = parse_datetime(item.get("source_published_at") or item.get("published_at"))
                    evidence.append({"id": str(item.get("id") or canonical_url(item["url"])), "report_group": event_index + 1,
                        "title": {locale: str((item.get(locale) or item.get("en") or item.get("zh") or {}).get("title") or "") for locale in ("en", "zh")},
                        "source": str(item.get("source") or publisher(item["url"])), "publisher": publisher(item["url"]),
                        "date": date.isoformat().replace("+00:00", "Z"), "url": safe_url(item["url"]),
                        "canonical_urls": {locale: value for locale, value in (item.get("canonical_urls") or {}).items() if locale in {"en", "zh"} and safe_url(value)}})
            count_en = f"{len(clusters)} related reporting group(s) from {len(publishers)} source website(s). Reports may describe the same event."
            count_zh = f"目前整理了 {len(clusters)} 组相关报道，来自 {len(publishers)} 个来源网站；不同报道仍可能讨论同一事件。"
            # Current public records do not carry editor-confirmed event IDs.
            # Therefore no amount of lexical grouping or source counting may
            # upgrade a card to an established multi-event observation.
            cards.append({"id": config["id"], "domain": field, "status": "unverified_signal", "event_identity_uncertain": True,
                "title": config["title"], "change": config["change"], "next_check": config["next_check"],
                "uncertainty": {"en": count_en + " These leads have not been independently verified and do not establish a lasting trend or a causal link. Contrary evidence may be missing.", "zh": count_zh + "这些线索尚未独立核验，不能据此认定趋势已经形成或存在因果关系，也可能遗漏相反证据。"},
                "report_group_count": len(clusters), "publisher_count": len(publishers), "evidence": evidence})
        fields[field] = sorted(cards, key=lambda card: (-card["report_group_count"], -card["publisher_count"], card["id"]))[:MAX_CARDS]
    return {"schema_version": "1.0", "generated_at": now.isoformat().replace("+00:00", "Z"), "window_days": WINDOW_DAYS,
            "window_start": (now - timedelta(days=WINDOW_DAYS)).isoformat().replace("+00:00", "Z"), "fields": fields}


def export(input_path, output_path, now=None):
    result = observation_cards(json.loads(Path(input_path).read_text(encoding="utf-8")), now=now)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return sum(len(cards) for cards in result["fields"].values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "web/public/data/articles.json")
    parser.add_argument("--output", type=Path, default=ROOT / "web/public/data/observations.json")
    args = parser.parse_args()
    print(f"Exported {export(args.input, args.output)} evidence-linked observation cards")


if __name__ == "__main__":
    main()
