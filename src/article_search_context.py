"""Evidence-bounded reader questions for explicitly reviewed archive articles.

This presentation helper does not fetch sources, call a model, or change article
facts. The first profile is intentionally bound to one article and source URL.
New profiles require a separate editorial review rather than broad keyword
matching that would create generic questions across the archive.
"""

from collections.abc import Mapping
import re


_HYDROGEN_ID = "ef947a5d-9a1d-4aaf-a3a3-fad2dc5bef6a"
_HYDROGEN_SOURCE = "https://deepmind.google/blog/introducing-gemini-4-hydrogen/"

# These are reviewed excerpts of the existing bilingual record, not additional
# reporting. At runtime both the definition and complete usage sentence must
# still occur in the requested locale's summary/full before a profile is shown.
# The usage answer extracts one independent clause and omits model comparisons.
_HYDROGEN = {
    "en": {
        "seo_title": "What Is Google Gemini 4 Hydrogen? Overview and Uses",
        "heading": "Gemini 4 Hydrogen: reading guide",
        "definition": (
            "According to Google DeepMind: Google is introducing Gemini 4 Hydrogen, "
            "a new model designed for rapid execution and everyday agentic workflows."
        ),
        "usage_evidence": (
            "While frontier models like Carbon and Argon handle deep, long-horizon "
            "reasoning on complex problems, Hydrogen is built as an efficient "
            "execution engine for rapid tasks and multi-model collaboration."
        ),
        "usage_excerpt": (
            "Hydrogen is built as an efficient execution engine for rapid tasks "
            "and multi-model collaboration."
        ),
        "questions": (
            "What is Gemini 4 Hydrogen?",
            "Which workflows does the brief describe?",
            "What should you verify before using it?",
        ),
        "verification": (
            "In the original release, check: Which entry points and regions can you "
            "use? What pricing and limits apply? Which workloads, thinking settings "
            "and comparison conditions support the performance claims?"
        ),
    },
    "zh": {
        "seo_title": "谷歌 Gemini 4 Hydrogen：定位与用途",
        "heading": "Gemini 4 Hydrogen：阅读指引",
        "definition": (
            "据Google DeepMind发布的信息：谷歌推出了全新模型 Gemini 4 Hydrogen，"
            "旨在提供快速执行能力和日常的智能体工作流。"
        ),
        "usage_evidence": (
            "虽然谷歌的旗舰模型 Carbon 和 Argon 专注于处理复杂的长周期推理任务，"
            "但 Hydrogen 的核心定位则是作为一个高效的执行引擎，胜任各类高频和多步骤的日常任务。"
        ),
        "usage_excerpt": (
            "Hydrogen 的核心定位则是作为一个高效的执行引擎，胜任各类高频和多步骤的日常任务。"
        ),
        "questions": (
            "Gemini 4 Hydrogen 是什么？",
            "这篇简报描述了哪些适用场景？",
            "使用前还应核查什么？",
        ),
        "verification": (
            "在原始发布中核查：你能使用哪些入口，所在地区是否可用？适用哪些定价与额度限制？"
            "性能说法对应哪些任务、思考层级与对比条件？"
        ),
    },
}


def _text(value):
    return re.sub(r"\s+", " ", value).strip() if isinstance(value, str) else ""


def _contains_sentence(text, sentence):
    """Require a reviewed sentence, rather than a clause in changed context."""
    start = text.find(sentence)
    if start < 0:
        return False
    # Whitespace is normalized first. In the current record the definition is
    # the first sentence and the usage evidence follows a complete sentence.
    preceding = text[:start].rstrip()
    return not preceding or preceding[-1] in ".!?。！？"


def article_search_context(record, locale):
    """Return three concise reader questions, or None without reviewed evidence.

    ``record`` follows export_archive's normalized schema with ``summary`` and
    ``full`` inside each locale. Answers with factual content are excerpts from
    that same locale; the last answer asks verification questions and does not
    infer that an unmentioned capability or restriction exists or is absent.

    All returned values are plain text. The renderer must escape the strings
    and use its normal URL validation/escaping before creating an HTML link.
    Inputs, article dates, canonical URLs and underlying facts are untouched.
    """
    if not isinstance(record, Mapping) or not isinstance(locale, str) or locale not in _HYDROGEN:
        return None
    if record.get("id") != _HYDROGEN_ID or record.get("url") != _HYDROGEN_SOURCE:
        return None
    text = record.get(locale)
    if not isinstance(text, Mapping):
        return None
    profile = _HYDROGEN[locale]
    sources = [_text(text.get(key)) for key in ("summary", "full")]
    if not all(
        any(_contains_sentence(source, profile[key]) for source in sources)
        for key in ("definition", "usage_evidence")
    ):
        return None
    answers = (profile["definition"], profile["usage_excerpt"], profile["verification"])
    return {
        "seo_title": profile["seo_title"],
        "description": profile["definition"],
        "heading": profile["heading"],
        "points": [
            {"question": question, "answer": answer}
            for question, answer in zip(profile["questions"], answers)
        ],
        "source_url": record["url"],
    }
