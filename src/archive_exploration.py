"""Small, deterministic archive navigation helpers; no network, DB or LLM.

Related means lexical subject overlap, not a verified follow-up, causal link,
independent confirmation, or evidence of a different editorial opinion.
"""

from collections import defaultdict
from datetime import date, datetime, timezone
from difflib import SequenceMatcher
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


GENERIC_TAGS = frozenset({
    "ai", "artificial intelligence", "machine learning", "deep learning", "llm", "llms",
    "ai model", "ai models", "large language model", "large language models", "foundation model", "foundation models",
    "news", "company", "companies", "research", "paper", "papers", "study", "studies",
    "technology", "tech", "innovation", "startup", "startups", "business", "policy",
    "society", "model", "models", "open source", "science", "scientific research",
    "quantum", "quantum computing", "robotics", "biotech", "biotechnology", "energy",
    "space", "materials", "climate", "agriculture", "manufacturing",
    "人工智能", "机器学习", "深度学习", "大模型", "新闻", "公司", "研究", "论文", "科技",
    "技术", "创新", "创业", "初创企业", "商业", "政策", "社会", "模型", "开源", "科学",
    "量子", "量子计算", "机器人", "生物技术", "能源", "太空", "新材料", "气候", "农业", "制造",
})

# Product names can support a one-tag match only when present in both titles.
PRODUCT_TAGS = frozenset({
    "gemini", "claude", "qwen", "deepseek", "chatgpt", "gpt", "llama", "grok",
    "alphafold", "alphagenome", "alphafold 2", "alphafold 3", "alphagenome 2",
    "blackwell", "rubin", "cuda", "qiskit", "starship", "falcon 9", "cas9", "crispr cas9",
    "豆包", "混元", "通义千问", "文心一言", "阿尔法折叠",
})
COMPANY_TAGS = frozenset({
    "nvidia", "openai", "anthropic", "google", "deepmind", "google deepmind", "meta",
    "microsoft", "amazon", "aws", "ibm", "amd", "intel", "apple", "tesla", "spacex",
    "neuralink", "synchron", "waymo", "腾讯", "阿里巴巴", "百度", "英伟达", "谷歌", "微软",
})
HEADLINE_STOP = GENERIC_TAGS | frozenset({
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "from", "by",
    "its", "is", "at", "as", "new", "announces", "announced", "announce", "launch",
    "launches", "launched", "release", "releases", "released", "introduces", "introduce",
    "update", "updates", "says", "reports", "first", "发布", "宣布", "推出", "新", "升级",
})
TRACKING_KEYS = frozenset({
    "fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid", "igshid", "mkt_tok",
    "ref", "ref_src", "ref_url", "spm",
})
DATE_KEYS = (
    "source_published", "source_published_at", "published", "published_at",
    "site_published", "site_published_at", "created_at", "first_seen_at",
)


def normalize_tag(value):
    """Normalize presentation variants, without stemming or guessing synonyms."""
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = re.sub(r"[\u2010-\u2015\u2212_.\-/]+", " ", text)
    return re.sub(r"\s+", " ", re.sub(r"[^\w+\s]", " ", text)).strip()


def _meaningful_tags(record):
    tags = record.get("tags") or []
    if not isinstance(tags, (list, tuple, set)):
        return set()
    return {
        tag for value in tags if isinstance(value, str)
        if (tag := normalize_tag(value)) and tag not in GENERIC_TAGS
        and len(tag) >= 2 and not tag.isdecimal()
    }


def _parse_date(value):
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, date):
            parsed = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        elif isinstance(value, str) and value.strip():
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            return None
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def _now(value=None):
    if value is None:
        return datetime.now(timezone.utc)
    parsed = _parse_date(value)
    if parsed is None:
        raise ValueError("now must be a datetime or an ISO date")
    return parsed


def _published(record):
    return next((parsed for key in DATE_KEYS if (parsed := _parse_date(record.get(key))) is not None), None)


def _not_future(record, now):
    dates = [_parse_date(record.get(key)) for key in DATE_KEYS]
    valid = [value for value in dates if value is not None]
    return bool(valid) and all(value <= now for value in valid)


def _canonical_url(value):
    try:
        if not isinstance(value, str) or re.search(r"[\x00-\x20\\]", value):
            return ""
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return ""
        host = parsed.hostname.casefold().rstrip(".").removeprefix("www.")
        port = parsed.port
        if port and port not in {80, 443}:
            host += f":{port}"
        query = sorted((key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                       if not key.casefold().startswith("utm_") and key.casefold() not in TRACKING_KEYS)
        return urlunsplit(("https", host, parsed.path.rstrip("/") or "/", urlencode(query), ""))
    except (ValueError, TypeError):
        return ""


def _identities(record):
    result = set()
    if record.get("id") is not None and str(record["id"]):
        result.add("id:" + str(record["id"]))
    urls = [record.get("url"), record.get("source_url"), record.get("canonical_url")]
    if isinstance(record.get("canonical_urls"), dict):
        urls.extend(record["canonical_urls"].values())
    result.update("url:" + normalized for value in urls if (normalized := _canonical_url(value)))
    return result


def _titles(record):
    values = [record.get("title")]
    values.extend((record.get(locale) or {}).get("title") for locale in ("en", "zh")
                  if isinstance(record.get(locale), dict))
    return sorted({normalize_tag(value) for value in values if isinstance(value, str) and value.strip()})


def _tag_in_titles(tag, titles):
    if re.search(r"[\u3400-\u9fff]", tag):
        return any(tag in title for title in titles)
    return any(re.search(r"(?<![a-z0-9_])" + re.escape(tag) + r"(?![a-z0-9_])", title) for title in titles)


def _near_duplicate(left, right):
    for first in _titles(left):
        for second in _titles(right):
            if first == second or SequenceMatcher(None, first, second, autojunk=False).ratio() >= .92:
                return True
            a, b = set(first.split()), set(second.split())
            if min(len(a), len(b)) >= 5 and len(a & b) / len(a | b) >= .9:
                return True
    return False


def _single_specific_tag(tag, first, second):
    a, b = _titles(first), _titles(second)
    if not _tag_in_titles(tag, a) or not _tag_in_titles(tag, b):
        return False
    if tag in COMPANY_TAGS:
        # A company's unrelated earnings and product releases are not a thread.
        excluded = {token for term in HEADLINE_STOP for token in term.split()} | set(tag.split())
        extra_a = {token for title in a for token in title.split()} - excluded
        extra_b = {token for title in b for token in title.split()} - excluded
        return any(len(token) >= 3 and not token.isdecimal() for token in extra_a & extra_b)
    return tag in PRODUCT_TAGS or bool(re.search(r"[a-z]", tag) and re.search(r"\d", tag))


def _stable_key(record):
    # Duplicate corpus rows may differ in tags or timestamps. Break those ties
    # explicitly so input order cannot change which version supplies labels.
    dates = tuple(parsed.isoformat() if (parsed := _parse_date(record.get(key))) else ""
                  for key in DATE_KEYS)
    return (str(record.get("id") or ""), _canonical_url(record.get("url") or record.get("source_url")),
            "|".join(_titles(record)), tuple(sorted(_meaningful_tags(record))),
            str(record.get("domain") or ""), str(record.get("source") or ""), dates)


def _source(record):
    return re.sub(r"\s+", " ", str(record.get("source") or "")).strip().casefold()


def topic_labels(records, limit=8):
    """Return {tag, label, count} for tags in >=2 distinct non-future articles.

    Counts represent archived articles, not independent events or sources.
    Sorting is count descending, then normalized tag; input order is irrelevant.
    """
    limit = min(8, max(0, int(limit)))
    if not limit:
        return []
    counts = defaultdict(set)
    labels = defaultdict(set)
    seen = set()
    now = _now()
    for record in sorted(records, key=_stable_key):
        identities = _identities(record)
        if not identities or identities & seen or not _not_future(record, now):
            continue
        seen.update(identities)
        meaningful = _meaningful_tags(record)
        for value in record.get("tags") or []:
            if not isinstance(value, str) or (tag := normalize_tag(value)) not in meaningful:
                continue
            counts[tag].add(_stable_key(record))
            labels[tag].add(re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip())
    ordered = sorted((tag for tag, articles in counts.items() if len(articles) >= 2),
                     key=lambda tag: (-len(counts[tag]), tag))[:limit]
    return [{"tag": tag, "label": min(labels[tag], key=lambda label: (len(label), label.casefold(), label)),
             "count": len(counts[tag])} for tag in ordered]


def related_articles(record, records, now=None, limit=3):
    """Return up to one background, newer related item, and other-source item.

    Results have ``record``, ``kind`` and sorted ``shared_tags`` fields. Sparse
    matches remain sparse; role labels never assert an actual follow-up or an
    independent/different perspective. Neither scores nor dates are mutated.
    """
    now = _now(now)
    limit = min(3, max(0, int(limit)))
    current_date = _published(record)
    domain = str(record.get("domain") or "").strip().casefold()
    current_ids = _identities(record)
    if not limit or not domain or not current_ids or not current_date or not _not_future(record, now):
        return []
    current_tags = _meaningful_tags(record)
    candidates = []
    for candidate in records:
        if str(candidate.get("domain") or "").strip().casefold() != domain:
            continue
        shared = sorted(current_tags & _meaningful_tags(candidate))
        if len(shared) < 2 and not (len(shared) == 1 and _single_specific_tag(shared[0], record, candidate)):
            continue
        identities = _identities(candidate)
        if (not identities or identities & current_ids
                or not _not_future(candidate, now) or _near_duplicate(record, candidate)):
            continue
        published = _published(candidate)
        candidates.append({"record": candidate, "shared_tags": shared, "published": published,
                           "identities": identities})
    output = []
    used = set(current_ids)
    for kind in ("background", "recent", "perspective"):
        eligible = [value for value in candidates if not value["identities"] & used
                    and all(not _near_duplicate(value["record"], previous["record"]) for previous in output) and (
            value["published"] < current_date if kind == "background" else
            value["published"] > current_date if kind == "recent" else
            bool(_source(record)) and bool(_source(value["record"]))
            and _source(record) != _source(value["record"]))]
        if not eligible:
            continue
        def rank(value):
            time_rank = abs((value["published"] - current_date).total_seconds()) if kind == "perspective" else -value["published"].timestamp()
            return (-len(value["shared_tags"]), time_rank, _stable_key(value["record"]))
        selected = min(eligible, key=rank)
        output.append({"record": selected["record"], "kind": kind, "shared_tags": selected["shared_tags"]})
        used.update(selected["identities"])
        if len(output) >= limit:
            break
    return output
