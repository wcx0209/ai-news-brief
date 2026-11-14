"""Local, explicitly labelled brand artwork for stories without source images."""

from collections.abc import Mapping
from pathlib import Path
import re

from editorial_domains import registry


GENERAL_ARTWORK = "/assets/editorial/general.svg"
PUBLIC_ROOT = Path(__file__).resolve().parent.parent / "web" / "public"


def _safe_artwork_path(value):
    return (isinstance(value, str) and
            re.fullmatch(r"/assets/editorial/[a-z][a-z0-9_]*\.svg", value) is not None and
            (PUBLIC_ROOT / value.lstrip("/")).is_file())


def editorial_artwork_path(item):
    """Resolve registry artwork, never accept an arbitrary URL/path from a story."""
    catalog = registry()
    fallback = catalog.get("artwork_default", GENERAL_ARTWORK)
    if not _safe_artwork_path(fallback):
        fallback = GENERAL_ARTWORK
    domain = item.get("domain") if isinstance(item, Mapping) else item if isinstance(item, str) else None
    if not isinstance(domain, str):
        return fallback
    for field in catalog.get("domains", []):
        if field.get("id") == domain:
            candidate = field.get("artwork")
            return candidate if _safe_artwork_path(candidate) else fallback
    return fallback


def editorial_caption(locale="en"):
    if str(locale).lower().startswith("zh"):
        return "Polyemergence 编辑配图 · 非原文图片"
    return "Polyemergence editorial artwork · Not a source image"
