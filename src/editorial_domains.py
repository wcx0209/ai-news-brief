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


def category_ids():
    return [item["id"] for item in categories()]


def category_labels(locale="en"):
    return {item["id"]: item["label"][locale] for item in categories()}


def category_titles(locale="en"):
    return {item["id"]: item["title"][locale] for item in categories()}


def match_category(text):
    value = str(text or "").lower()
    for item in categories():
        for keyword in item.get("keywords", []):
            if re.search(r"(?<!\w)" + re.escape(keyword.lower()) + r"(?!\w)", value):
                return item["id"]
    return None


def taxonomy_prompt():
    lines = []
    for item in categories():
        terms = ", ".join(item.get("keywords", [])[:6])
        lines.append(f'- {item["id"]}: {item["label"]["en"]} ({terms})')
    return "\n# Current editorial taxonomy\n" + "\n".join(lines)
