"""Conservative, offline guards against obviously swapped EN/ZH prose.

This is a script-distribution check, not a language classifier. Short titles,
names, and mixed technical text intentionally need more evidence before they
can be rejected. No network calls or optional language packages are used.
"""

import html
import re
import unicodedata
from collections.abc import Mapping


LOCALIZED_FIELDS = (
    "title_en", "title_zh",
    "summary_en", "summary_zh",
    "long_summary_en", "long_summary_zh",
)

_FENCED_CODE = re.compile(r"```[^\n]*\n.*?(?:```|\Z)|~~~[^\n]*\n.*?(?:~~~|\Z)", re.DOTALL)
_INLINE_CODE = re.compile(r"`+[^`\n]*`+")
_MARKDOWN_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
_URL = re.compile(r"(?:https?://|www\.)[^\s<>]+", re.IGNORECASE)
_HTML_TAG = re.compile(r"<[^>]+>")
_LATIN_WORD = re.compile(r"[A-Za-z]+(?:['\u2019-][A-Za-z]+)*")


def _prose(text):
    """Exclude code, links' destinations and markup from script evidence."""
    text = _FENCED_CODE.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    text = _MARKDOWN_LINK.sub(r"\1", text)
    text = _URL.sub(" ", text)
    return html.unescape(_HTML_TAG.sub(" ", text))


def wrong_language(text, locale):
    """Return True only for substantial prose clearly in the other script.

    English fields require at least 40 Han characters with Han making up a
    majority of letters before rejection. Chinese fields require at least 120
    Latin letters and 24 words, with only a few Han characters (such as names)
    present. Numbers, punctuation, code and URL targets provide no evidence.
    Insufficient evidence and unsupported locales conservatively return False.
    """
    if not isinstance(text, str) or not isinstance(locale, str):
        return False
    locale = locale.lower().replace("_", "-").split("-", 1)[0]
    if locale not in {"en", "zh"}:
        return False

    prose = _prose(text)
    han = latin = letters = 0
    for char in prose:
        if not char.isalpha():
            continue
        letters += 1
        name = unicodedata.name(char, "")
        if name.startswith(("CJK UNIFIED IDEOGRAPH", "CJK COMPATIBILITY IDEOGRAPH")):
            han += 1
        elif "LATIN" in name:
            latin += 1

    if locale == "en":
        return han >= 40 and han * 2 >= letters
    return (
        latin >= 120
        and len(_LATIN_WORD.findall(prose)) >= 24
        and han <= max(8, latin * 0.03)
        and latin >= letters * 0.90
    )


def validate_localized_fields(mapping):
    """Return wrong-language DB field names in stable schema order.

    The accepted keys are title_en/title_zh, summary_en/summary_zh, and
    long_summary_en/long_summary_zh. Missing, empty and non-string values provide
    no language evidence; required-field/type checks belong to the caller.
    """
    if not isinstance(mapping, Mapping):
        return []
    return [
        field for field in LOCALIZED_FIELDS
        if wrong_language(mapping.get(field), field.rsplit("_", 1)[1])
    ]


def safe_localized_fields(fields, locale, *, full_key="full_summary"):
    """Copy one locale's public fields, suppressing clearly swapped prose.

    A rejected full summary can use the same locale's remaining short summary.
    Other fields are preserved verbatim; this never translates text or reads
    another locale. Empty or short values retain their existing behavior.
    """
    safe = dict(fields)
    if wrong_language(safe.get("summary"), locale):
        safe["summary"] = ""
    if wrong_language(safe.get(full_key), locale):
        safe[full_key] = safe.get("summary") or ""
    return safe
