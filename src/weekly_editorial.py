"""Deterministic weekly review selection; no database, network, or LLM calls.

Groups are conservative editorial deduplication suggestions, not verified
events or evidence of a trend. Coverage describes only the supplied archive.
"""

from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
import hashlib
import ipaddress
import math
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


DEFAULT_START_UTC = "2026-11-08T16:00:00Z"
DEFAULT_END_UTC = "2026-11-15T16:00:00Z"
REGISTERED_DOMAINS = (
    "ai", "programmable_life", "robotics_autonomy", "energy_storage",
    "space_economy", "advanced_materials", "quantum_technology", "neurotechnology",
    "climate_water_environment", "agrifood_technology", "advanced_manufacturing",
)
METHOD_FIELDS = ("signal", "structure", "consequence", "confidence", "momentum")
SOURCE_DATE_BASES = {"source_published", "source_reader_published", "source_metadata"}
GENERIC_TAGS = {
    "ai", "artificial intelligence", "人工智能", "news", "新闻", "technology", "科技",
    "model", "models", "模型", "research", "研究", "open source", "开源", "business",
    "company", "startups", "startup", "policy", "society", "machine learning", "deep learning",
    "robotics", "quantum", "space", "biotech", "energy", "robotics autonomy",
}
STOP_WORDS = {
    "a", "an", "the", "and", "or", "of", "for", "to", "in", "on", "at", "by", "with",
    "new", "latest", "its", "their", "is", "are", "as", "from", "that", "this", "it",
    "announces", "announced", "announcement", "launches", "launch", "releases", "release",
    "introduces", "introduce", "unveils", "unveil", "update", "updates", "news", "weekly",
    "ai", "model", "models", "research", "technology", "company",
}
ACTION_PATTERNS = {
    "release": r"\b(?:launch(?:es|ed)?|releas(?:e|es|ed)|unveil(?:s|ed)?|introduc(?:e|es|ed))\b|发布|推出",
    "funding": r"\b(?:funding|financing|rais(?:e|es|ed)|investment|invests?)\b|融资|注资|投资",
    "acquisition": r"\b(?:acquir(?:e|es|ed)|acquisition|merger)\b|收购|并购",
    "policy": r"\b(?:regulation|regulator|legislation|ban|law)\b|监管|法规|禁令|立法",
    "partnership": r"\b(?:partnership|collaborat(?:e|es|ion))\b|合作|联合",
    "deployment": r"\b(?:deploy(?:s|ed|ment)?|pilot|clinical trial|rollout)\b|部署|落地|试点|临床",
}


def _date(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if result.tzinfo is None:
            return None
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _normalize(value):
    return re.sub(r"[^\w]+", " ", unicodedata.normalize("NFKC", _text(value)).casefold()).strip()


def _score(value):
    if isinstance(value, bool):
        return 0
    try:
        number = float(value)
        if not math.isfinite(number):
            return 0
        number = max(0.0, min(100.0, number))
        return int(number) if number.is_integer() else number
    except (TypeError, ValueError, OverflowError):
        return 0


def _domain(item):
    value = item.get("domain")
    if isinstance(value, dict):
        value = value.get("id")
    return _text(value) or "unclassified"


def canonical_report_url(value):
    """Syntax-only report identity; preserve article/release query identifiers."""
    if not isinstance(value, str) or not value or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        return None
    try:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower().rstrip(".").removeprefix("www.")
        if (parsed.scheme not in {"https", "http"} or not host or parsed.username is not None
                or parsed.password is not None or parsed.port not in {None, 80, 443}
                or host == "localhost" or host.endswith((".local", ".internal", ".localhost"))):
            return None
        try:
            if not ipaddress.ip_address(host).is_global:
                return None
        except ValueError:
            if "." not in host:
                return None
        query = sorted((key, val) for key, val in parse_qsl(parsed.query, keep_blank_values=True)
                       if not key.casefold().startswith("utm_")
                       and key.casefold() not in {"fbclid", "gclid", "msclkid"})
        return urlunsplit(("", host, parsed.path.rstrip("/") or "/", urlencode(query), ""))
    except (ValueError, TypeError):
        return None


def _original_date(item):
    dates = item.get("source_dates") if isinstance(item.get("source_dates"), dict) else {}
    basis = item.get("date_basis") or dates.get("date_basis")
    if basis in {"first_seen", "unknown", "site_published", "updated"} or dates.get("verified") is False:
        return None, "unknown_original_date"
    direct = item.get("source_published_at")
    nested = dates.get("source_published_at")
    if direct and nested and _date(direct) != _date(nested):
        return None, "conflicting_original_dates"
    if direct or nested:
        return _date(direct or nested), "invalid_original_date"
    # Bare published_at may be a site's first-seen time. Require explicit
    # source-date provenance before using that compatibility field.
    if basis in SOURCE_DATE_BASES or dates.get("verified") is True or item.get("published_verified") is True:
        return _date(dates.get("published_at") or item.get("published_at")), "invalid_original_date"
    return None, "unknown_original_date"


def _trending(item):
    name = _normalize(item.get("source") or item.get("source_name"))
    if name == "github trending":
        return True
    for value in (item.get("source_url"), item.get("url")):
        try:
            parsed = urlsplit(value or "")
            if parsed.hostname in {"github.com", "www.github.com"} and parsed.path.rstrip("/") == "/trending":
                return True
        except (TypeError, ValueError):
            pass
    return False


def _titles(item):
    return [_text((item.get(locale) or {}).get("title")) for locale in ("en", "zh")
            if isinstance(item.get(locale), dict) and _text(item[locale].get("title"))]


def _tags(item):
    values = item.get("tags") or []
    if not isinstance(values, (list, tuple, set)):
        return set()
    return {tag for value in values if (tag := _normalize(value)) and tag not in GENERIC_TAGS}


def _actions(title):
    return {name for name, pattern in ACTION_PATTERNS.items() if re.search(pattern, title, re.I)}


def _title_pair_matches(left, right, shared_tags):
    a, b = _normalize(left), _normalize(right)
    if not a or not b or min(len(a), len(b)) < 12:
        return False, None
    # Product revisions, amounts and trial stages are not interchangeable.
    nums_a, nums_b = set(re.findall(r"\d+(?:\.\d+)*", left)), set(re.findall(r"\d+(?:\.\d+)*", right))
    if nums_a and nums_b and nums_a != nums_b:
        return False, None
    actions_a, actions_b = _actions(left), _actions(right)
    if actions_a and actions_b and not actions_a.intersection(actions_b):
        return False, None
    han = bool(re.search(r"[\u3400-\u9fff]", a + b))
    if han:
        if min(len(a.replace(" ", "")), len(b.replace(" ", ""))) < 16:
            return False, None
        if a == b and len(a.replace(" ", "")) >= 16 and (shared_tags or nums_a):
            return True, "exact_localized_title"
        compact_a, compact_b = a.replace(" ", ""), b.replace(" ", "")
        tokens_a = {compact_a[index:index + 2] for index in range(len(compact_a) - 1)}
        tokens_b = {compact_b[index:index + 2] for index in range(len(compact_b) - 1)}
    else:
        tokens_a = set(a.split()) - STOP_WORDS
        tokens_b = set(b.split()) - STOP_WORDS
        if a == b and len(tokens_a) >= 4 and (shared_tags or nums_a):
            return True, "exact_localized_title"
    shared = tokens_a & tokens_b
    overlap = len(shared) / max(1, len(tokens_a | tokens_b))
    if (len(shared_tags) >= 2 and len(shared) >= (8 if han else 5)
            and overlap >= .8 and SequenceMatcher(None, a, b, autojunk=False).ratio() >= .9):
        return True, "near_title_and_specific_tags"
    return False, None


def _same_event(left, right):
    if left.get("id") == right.get("id") or canonical_report_url(left.get("url")) == canonical_report_url(right.get("url")):
        return True, "same_record_or_report_url"
    if _domain(left) != _domain(right):
        return False, None
    if abs((_date(left["source_published_at"]) - _date(right["source_published_at"])).total_seconds()) > 48 * 3600:
        return False, None
    # A vague translated headline must not override a different explicit
    # model version or event action in the other shared language.
    for locale in ("en", "zh"):
        a, b = _text((left.get(locale) or {}).get("title")), _text((right.get(locale) or {}).get("title"))
        nums_a, nums_b = set(re.findall(r"\d+(?:\.\d+)*", a)), set(re.findall(r"\d+(?:\.\d+)*", b))
        actions_a, actions_b = _actions(a), _actions(b)
        if nums_a and nums_b and nums_a != nums_b:
            return False, None
        if actions_a and actions_b and not actions_a.intersection(actions_b):
            return False, None
    shared_tags = _tags(left) & _tags(right)
    for a in _titles(left):
        for b in _titles(right):
            same, reason = _title_pair_matches(a, b, shared_tags)
            if same:
                return True, reason
    return False, None


def _priority(item):
    evidence = item.get("evidence") or {}
    kind = item.get("source_type") or (evidence.get("type") if isinstance(evidence, dict) else None)
    return {"official_release": 0, "preprint": 1, "research_paper": 1, "open_source": 1}.get(kind, 2)


def _record_rank(item):
    scores = item["scores"]
    return (-item["importance"], -scores["signal"], -scores["structure"], -scores["consequence"],
            -scores["confidence"], item.get("id", ""), item.get("url", ""))


def _group_rank(group):
    return _record_rank(group["representative"]) + (group["event_id"],)


def _event_groups(items):
    groups = []
    for item in sorted(items, key=lambda value: (value["source_published_at"], str(value["id"]), value["url"])):
        for group in groups:
            matches = [_same_event(item, member) for member in group["support"]]
            # Complete-link, not transitive chaining: A~B and B~C do not prove A~C.
            if all(same for same, _ in matches):
                group["support"].append(item)
                group["grouping_basis"].update(reason for _, reason in matches)
                break
        else:
            groups.append({"support": [item], "grouping_basis": {"single_report"}})
    for group in groups:
        support = sorted(group["support"], key=lambda item: (_priority(item), _record_rank(item)))
        ids = sorted({str(item["id"]) for item in support})
        group.update({
            "event_id": "weekly-" + hashlib.sha256("\n".join(ids).encode("utf-8")).hexdigest()[:16],
            "representative": support[0], "support": support, "evidence_ids": ids,
            "source_count": len({_normalize(item["source"]) for item in support}),
            "report_count": len({canonical_report_url(item["url"]) for item in support}),
            "independent_source_count": None, "claims_verified": False,
            "event_identity": "heuristic_editorial_group" if len(support) > 1 else "single_report",
            "grouping_basis": sorted(group["grouping_basis"] - ({"single_report"} if len(support) > 1 else set())),
            "selection_reason": {},
        })
    return sorted(groups, key=_group_rank)


def _balanced_pick(groups, count, already=(), *, main=False, score_gap=8):
    chosen = []
    prior = list(already)
    while len(chosen) < count:
        counts = Counter(_domain(item["representative"]) for item in prior + chosen)
        candidates = [group for group in groups if group not in chosen and group not in prior
                      and counts[_domain(group["representative"])] < (3 if _domain(group["representative"]) == "ai" and main else 4 if _domain(group["representative"]) == "ai" else 3)]
        if not candidates:
            break
        candidates.sort(key=_group_rank)
        best = candidates[0]["representative"]["importance"]
        comparable_new_fields = [group for group in candidates
                                 if counts[_domain(group["representative"])] == 0
                                 and group["representative"]["importance"] >= best - score_gap]
        chosen.append(comparable_new_fields[0] if comparable_new_fields else candidates[0])
    return chosen


def build_weekly_plan(records, *, start_utc=DEFAULT_START_UTC, end_utc=DEFAULT_END_UTC,
                      max_candidates=24, max_main=8, max_signals=2, min_importance=65,
                      min_confidence=65, main_min_importance=70, registered_domains=REGISTERED_DOMAINS):
    """Return a bilingual, traceable selection plan for a review-only draft.

    Source dates and Method scores are supplied metadata, not independently
    checked facts. ``published_at`` alone is never assumed to mean publication.
    Low coverage never causes a score/date/translation gate to be relaxed.
    """
    start, end = _date(start_utc), _date(end_utc)
    if not start or not end or start >= end:
        raise ValueError("An explicit timezone-aware, increasing weekly interval is required")
    max_candidates = max(0, min(24, int(max_candidates)))
    max_main = max(0, min(12, int(max_main), max_candidates))
    max_signals = max(0, min(12 - max_main, int(max_signals), max_candidates - max_main))
    min_importance, min_confidence = max(65, _score(min_importance)), max(65, _score(min_confidence))
    main_min_importance = max(min_importance, _score(main_min_importance))
    registered = list(dict.fromkeys(_text(value.get("id") if isinstance(value, dict) else value)
                                    for value in registered_domains))
    registered = [value for value in registered if value]
    eligible, exclusions = [], []
    input_counts = Counter()
    input_count = 0
    for raw in records:
        input_count += 1
        if not isinstance(raw, dict):
            exclusions.append({"id": None, "url": None, "reason": "invalid_record"})
            continue
        input_counts[_domain(raw)] += 1
        reason = None
        published, date_error = _original_date(raw)
        if not _text(str(raw.get("id") or "")):
            reason = "missing_record_id"
        elif _trending(raw):
            reason = "github_trending_not_publication"
        elif not canonical_report_url(raw.get("url")):
            reason = "invalid_source_url"
        elif not _text(raw.get("source")):
            reason = "missing_source_attribution"
        elif not published:
            reason = date_error
        elif published < start:
            reason = "before_week"
        elif published >= end:
            reason = "after_week_or_future"
        elif any(not isinstance(raw.get(locale), dict) or not _text(raw[locale].get("summary"))
                 or not _text(raw[locale].get("title")) for locale in ("en", "zh")):
            reason = "missing_bilingual_title_or_summary"
        scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
        importance = _score(raw.get("importance", raw.get("importance_score")))
        normalized_scores = {name: _score(scores.get(name, raw.get(name + "_score"))) for name in METHOD_FIELDS}
        if not reason and importance < min_importance:
            reason = "below_importance_threshold"
        if not reason and normalized_scores["confidence"] < min_confidence:
            reason = "below_confidence_threshold"
        if reason:
            exclusions.append({"id": raw.get("id"), "url": raw.get("url"), "reason": reason})
            continue
        item = deepcopy(raw)
        item.update({"id": str(raw["id"]), "source_published_at": _iso(published), "domain": _domain(raw),
                     "importance": importance, "scores": normalized_scores, "claims_verified": False})
        eligible.append(item)
    groups = _event_groups(eligible)
    main = _balanced_pick([group for group in groups if group["representative"]["importance"] >= main_min_importance], max_main, main=True)
    signals = _balanced_pick(groups, max_signals, already=main)
    for section, chosen in (("main", main), ("signals", signals)):
        for group in chosen:
            group["selection_reason"] = {
                "en": f"Meets supplied Method importance/confidence gates; selected for {section} with bounded field diversity. This is not a factual verification.",
                "zh": "达到已有 Method 重要性与置信度门槛，并按有限跨领域规则入选" + ("重点" if section == "main" else "观察信号") + "；不代表事实已获核验。",
            }
    selected_ids = {group["event_id"] for group in main + signals}
    candidates = (main + signals + [group for group in groups if group["event_id"] not in selected_ids])[:max_candidates]
    for group in candidates:
        if not group["selection_reason"]:
            group["selection_reason"] = {
                "en": "Eligible reserve candidate from the supplied archive; not shortlisted, independently verified, or evidence of a trend.",
                "zh": "库内达到筛选门槛的备选报道，未进入短名单；不代表独立核验或趋势已经成立。",
            }
    domain_counts = {}
    for domain in registered + sorted(set(input_counts) - set(registered)):
        report_count = sum(_domain(item) == domain for item in eligible)
        counts = {"input": input_counts[domain], "eligible_reports": report_count,
                  "event_groups": sum(_domain(group["representative"]) == domain for group in groups),
                  "candidates": sum(_domain(group["representative"]) == domain for group in candidates),
                  "main": sum(_domain(group["representative"]) == domain for group in main),
                  "signals": sum(_domain(group["representative"]) == domain for group in signals)}
        counts["status"] = "selected" if counts["main"] + counts["signals"] else "eligible_not_selected" if report_count else "no_qualifying_record_in_loaded_archive"
        counts["notice"] = {"en": "Selection describes the loaded archive only, not the absence or presence of worldwide progress.",
                            "zh": "仅说明本次库内选材情况；未选入不等于全球没有进展。"}
        domain_counts[domain] = counts
    warnings = [
        {"code": "claims_not_verified", "en": "Source claims and supplied scores have not been independently verified; report groups do not establish trends or independent corroboration.",
         "zh": "来源主张与原有评分未经独立核验；报道归并不等于趋势成立或获得独立交叉验证。"},
        {"code": "archive_coverage_only", "en": "Coverage is limited to supplied archive records; sparse fields are not padded.",
         "zh": "覆盖范围仅限本次提供的历史记录，稀疏领域不凑数。"},
    ]
    if len(main) < max_main:
        warnings.append({"code": "main_shortfall", "en": "Fewer main items met the quality/diversity limits; no lower-quality filler was added.",
                         "zh": "达到重点质量与分布约束的条目不足，未降低门槛补位。"})
    exclusions.sort(key=lambda item: (str(item["id"] or ""), str(item["url"] or ""), item["reason"]))
    return {
        "schema_version": 1, "period": {"start_utc": _iso(start), "end_utc": _iso(end), "end_exclusive": True},
        "claims_verified": False, "candidates": candidates, "shortlist": {"main": main, "signals": signals},
        "domain_counts": domain_counts, "exclusions": exclusions,
        "exclusion_counts": dict(sorted(Counter(item["reason"] for item in exclusions).items())),
        "coverage": {"scope": "loaded_archive_only", "registered_domains": registered, "input_records": input_count,
                     "eligible_reports": len(eligible), "heuristic_event_groups": len(groups), "candidate_count": len(candidates),
                     "main_count": len(main), "signals_count": len(signals),
                     "selected_domains": sorted({_domain(group["representative"]) for group in main + signals}),
                     "domain_counts": domain_counts},
        "selection_rules": {"min_importance": min_importance, "main_min_importance": main_min_importance,
                            "min_confidence": min_confidence, "max_main_ai": 3, "max_total_ai": 4,
                            "max_total_per_other_domain": 3, "diversity_score_gap": 8, "max_total": 12},
        "warnings": warnings,
    }
