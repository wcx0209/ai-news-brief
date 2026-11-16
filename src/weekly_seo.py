"""Pure presentation helpers for weekly titles and local share-cover paths.

Published JSON stays unchanged. Legacy publication labels are removed only at
render time; the remaining title is the edition's supplied topic, not a newly
inferred editorial claim.
"""

from collections.abc import Mapping
from datetime import date
import re


WEEKLY_TYPES = {"en": "Weekly Tech News & Analysis", "zh": "科技周报"}
_BRANDS = {"en": "Polyemergence", "zh": "多重涌现"}
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_MISSING_TOPIC = {"en": "This week's selection", "zh": "本周选材"}
_QUALIFIERS = re.compile(r"\b(?:reports?|reported|claims?|claimed|propos(?:es?|ed|als?)|preliminary|experimental|unverified|alleged)\b", re.IGNORECASE)
_BRAND_PREFIX = re.compile(
    r"^(?:(?:the\s+)?polyemergence(?:\s+pte\s+ltd\.?)?(?=$|\s|[:：|｜—–\-])|多重涌现)"
    r"(?:\s*[:：|｜—–\-]\s*|\s+)?",
    re.IGNORECASE,
)
_LABEL_PREFIX = re.compile(
    r"^(?:industry\s+review|行业观察|weekly\s+tech\s+news\s*&\s*analysis|"
    r"(?:the\s+)?weekly(?:\s+(?:technology|tech))?(?:\s+review)?|科技周报)"
    r"(?:\s*[:：|｜—–\-]\s*|\s*$)",
    re.IGNORECASE,
)
_BRAND_SUFFIX = re.compile(r"\s*[|｜]\s*(?:polyemergence|多重涌现)\s*$", re.IGNORECASE)
_PERIOD_SUFFIX = re.compile(
    r"\s*[（(]\s*(\d{4}-\d{2}-\d{2})\s*[—–]\s*(\d{4}-\d{2}-\d{2})\s*[）)]\s*$"
)


def _locale(locale):
    if locale not in WEEKLY_TYPES:
        raise ValueError("locale must be en or zh")
    return locale


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def weekly_topic(payload, locale):
    """Return the supplied topic without legacy publication branding/labels."""
    _locale(locale)
    payload = payload if isinstance(payload, Mapping) else {}
    content = payload.get(locale)
    content = content if isinstance(content, Mapping) else {}
    topic = _BRAND_SUFFIX.sub("", _text(content.get("title")))
    period = _PERIOD_SUFFIX.search(topic)
    if period and (period[1], period[2]) == (payload.get("week_start"), payload.get("week_end")):
        topic = topic[:period.start()]
    topic = _BRAND_PREFIX.sub("", topic, count=1)
    while topic and (match := _LABEL_PREFIX.match(topic)):
        topic = topic[match.end():].strip()
    return topic.strip() or _MISSING_TOPIC[locale]


def weekly_period(payload, locale):
    """Use the supplied coverage dates without changing publication dates."""
    _locale(locale)
    payload = payload if isinstance(payload, Mapping) else {}
    dates = []
    for name in ("week_start", "week_end"):
        try:
            dates.append(date.fromisoformat(_text(payload.get(name))[:10]).isoformat())
        except (ValueError, TypeError):
            dates.append("Not provided" if locale == "en" else "未提供")
    return " — ".join(dates)


def weekly_heading(payload, locale):
    """Full readable title: publication type, actual supplied topic, period."""
    topic = weekly_topic(payload, locale)
    period = weekly_period(payload, locale)
    return (f"{WEEKLY_TYPES[locale]}: {topic} ({period})" if locale == "en"
            else f"{WEEKLY_TYPES[locale]}：{topic}（{period}）")


def weekly_meta_title(payload, locale):
    """Compact display summary; full H1/headline retain the complete subject.

    Prefer two complete supplied subject phrases, then one. If a single English
    phrase still needs shortening, cut only at a word boundary. Keep trailing
    claim qualifiers after an ellipsis so the summary cannot overstate a result.
    """
    _locale(locale)
    topic = weekly_topic(payload, locale)
    period = _compact_period(payload, locale)
    prefix = "Weekly Tech News: " if locale == "en" else "科技周报："
    suffix = f" | {period}" if locale == "en" else f"｜{period}"
    budget = max(20, 100 - len(prefix + suffix + " | " + _BRANDS[locale]))
    if locale == "en":
        phrases = [part.strip() for part in re.split(r"\s*[,;]\s*|\s+(?:&|and)\s+", topic) if part.strip()]
        short = ", ".join(phrases[:2])
        if len(short) > budget and len(phrases) > 1:
            short = phrases[0]
        if len(short) > budget:
            words = list(re.finditer(r"\S+", short))
            ends = [word.end() for word in words if word.end() <= budget - 1]
            end = ends[-1] if ends else words[0].end()
            # Reserve space for qualifiers beyond the normal cut. Moving the
            # cut earlier can uncover another qualifier, so settle that before
            # rendering the omitted middle as an explicit ellipsis.
            qualifiers = list(_QUALIFIERS.finditer(short))
            tail = "…"
            while True:
                omitted = [match.group() for match in qualifiers if match.end() > end]
                tail = "… " + " ".join(omitted) if omitted else "…"
                fitting = [word.end() for word in words if word.end() <= budget - len(tail)]
                revised = fitting[-1] if fitting else 0
                if revised >= end:
                    break
                end = revised
            short = short[:end].rstrip(" ,;:&") + tail
    else:
        short = topic
        if len(short) > budget:
            phrases = [part.strip() for part in re.split(r"[，、；]", topic) if part.strip()]
            short = "、".join(phrases[:2])
            if len(short) > budget:
                short = short[:budget - 1].rstrip("，、；：") + "…"
    return prefix + short + suffix


def _compact_period(payload, locale):
    payload = payload if isinstance(payload, Mapping) else {}
    try:
        start = date.fromisoformat(_text(payload.get("week_start"))[:10])
        end = date.fromisoformat(_text(payload.get("week_end"))[:10])
    except (ValueError, TypeError):
        return weekly_period(payload, locale)
    if locale == "zh":
        if start.year != end.year:
            return f"{start.year}年{start.month}月{start.day}日–{end.year}年{end.month}月{end.day}日"
        if start.month != end.month:
            return f"{start.month}月{start.day}日–{end.month}月{end.day}日"
        return f"{start.month}月{start.day}–{end.day}日"
    start_month, end_month = _MONTHS[start.month - 1], _MONTHS[end.month - 1]
    if start.year != end.year:
        return f"{start_month} {start.day}, {start.year}–{end_month} {end.day}, {end.year}"
    if start.month != end.month:
        return f"{start_month} {start.day}–{end_month} {end.day}, {end.year}"
    return f"{start_month} {start.day}–{end.day}, {end.year}"


def weekly_cover_path(identifier, locale):
    """1200×630 local PNG contract shared by rendering and offline export."""
    _locale(locale)
    if identifier is None:
        return f"/assets/weekly/index-{locale}.png"
    if not isinstance(identifier, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", identifier):
        raise ValueError("weekly edition id must be YYYY-MM-DD")
    date.fromisoformat(identifier)
    return f"/assets/weekly/{identifier}-{locale}.png"
