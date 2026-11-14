"""Shared, auditable regional sources for cloud seeding and HTML adapters."""

import ast
import json
from functools import lru_cache
from pathlib import Path


CATALOG_PATH = Path(__file__).resolve().parent.parent / "config" / "sources"


@lru_cache(maxsize=1)
def china_sources():
    sources = []
    for path in sorted(CATALOG_PATH.glob("china-*.json")):
        sources.extend(json.loads(path.read_text(encoding="utf-8"))["sources"])
    return sources


def china_source_tuples():
    return [
        (
            source["url"], source["name"],
            ("[FIRST_PARTY] " if source["kind"] != "media" else "")
            + "[REGION:CN] " + source["description"].removeprefix("[FIRST_PARTY] "),
            source["category"], source["importance_score"],
        )
        for source in china_sources()
    ]


def china_html_rules():
    return {
        source["url"].rstrip("/"): {
            "timezone": "Asia/Shanghai",
            "browser_fallback": False,
            "max_index_links": 8,
            "max_articles": 3,
            "min_content_chars": 120,
            **source["html"],
        }
        for source in china_sources() if source.get("html")
    }


def china_title_gated_names():
    return {source["name"] for source in china_sources() if source.get("title_gate", True)}


def load_seed_catalog(path):
    """Read only the declared literal and known regional extension; never exec."""
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    sources = []
    regional_extension = False
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "SOURCES" for target in node.targets
        ):
            sources = ast.literal_eval(node.value)
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute)
                and isinstance(node.value.func.value, ast.Name)
                and node.value.func.value.id == "SOURCES" and node.value.func.attr == "extend"
                and len(node.value.args) == 1 and isinstance(node.value.args[0], ast.Call)
                and isinstance(node.value.args[0].func, ast.Name)
                and node.value.args[0].func.id == "china_source_tuples"):
            regional_extension = True
    return sources + china_source_tuples() if regional_extension else sources
