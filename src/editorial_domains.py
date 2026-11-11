"""Shared, data-driven editorial taxonomy for collectors, exports and prompts."""

import json
import re
from functools import lru_cache
from pathlib import Path


REGISTRY_PATH = Path(__file__).resolve().parent.parent / "web" / "public" / "data" / "editorial-domains.json"


@lru_cache(maxsize=1)
def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def categories():
    return sorted(registry()["categories"], key=lambda item: item.get("order", 999))


def domains():
    return sorted(registry()["domains"], key=lambda item: item.get("order", 999))


def domain_ids():
    return [item["id"] for item in domains()]


def source_category_domain(value):
    normalized = str(value or "").strip().lower().replace("-", "_")
    for item in domains():
        aliases = {item["id"], *item.get("source_categories", [])}
        if normalized in aliases:
            return item["id"]
    return None


def category_ids():
    return [item["id"] for item in categories()]


def category_labels(locale="en"):
    return {item["id"]: item["label"][locale] for item in categories()}


def category_titles(locale="en"):
    return {item["id"]: item["title"][locale] for item in categories()}


def category_domain(category):
    for item in categories():
        if item["id"] == category:
            return item.get("domain", "ai")
    return "ai"


def infer_domain(category=None, source_category=None, text=""):
    """Resolve the broad editorial domain independently of the story angle."""
    for value in (source_category, category):
        explicit = source_category_domain(value)
        if explicit:
            return explicit
        mapped = category_domain(str(value or "").strip().lower().replace("-", "_"))
        if mapped != "ai":
            return mapped
    matched = match_domain(text)
    if matched:
        return matched
    matched_category = match_category(text)
    return category_domain(matched_category) if matched_category else "ai"


def _contains_keyword(value, keyword):
    term = keyword.lower()
    # Unicode \w treats adjacent Han characters as one word, so ASCII-style
    # boundaries incorrectly reject phrases such as "脑机接口恢复交流能力".
    if re.search(r"[\u3400-\u9fff]", term):
        return term in value
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", value))


def match_domain(text):
    value = str(text or "").lower()
    # AI is the platform default and has intentionally broad vocabulary, so
    # test every specialist field first to preserve cross-domain signals.
    for item in [domain for domain in domains() if domain["id"] != "ai"]:
        for keyword in item.get("keywords", []):
            if _contains_keyword(value, keyword):
                return item["id"]
    return None


def match_category(text):
    value = str(text or "").lower()
    for item in categories():
        for keyword in item.get("keywords", []):
            if _contains_keyword(value, keyword):
                return item["id"]
    return None


def taxonomy_prompt():
    domain_lines = []
    for item in domains():
        terms = ", ".join(item.get("keywords", [])[:6])
        domain_lines.append(f'- {item["id"]}: {item["label"]["en"]} ({terms})')
    category_lines = []
    for item in categories():
        if item.get("is_angle") is False:
            continue
        terms = ", ".join(item.get("keywords", [])[:6])
        category_lines.append(f'- {item["id"]}: {item["label"]["en"]} ({terms})')
    return (
        "\n# Current editorial domains\n" + "\n".join(domain_lines)
        + "\n# Story angles (category must be one of these)\n" + "\n".join(category_lines)
    )
