"""Evidence-bounded reader questions for explicitly reviewed archive articles.

This presentation helper does not fetch sources, call a model, or change article
facts. The first profile is intentionally bound to one article and source URL.
New profiles require a separate editorial review rather than broad keyword
matching that would create generic questions across the archive.
"""

from collections.abc import Mapping
import re
from unicodedata import normalize


_HYDROGEN_ID = "ef947a5d-9a1d-4aaf-a3a3-fad2dc5bef6a"
_HYDROGEN_SOURCE = "https://deepmind.google/blog/introducing-gemini-4-hydrogen/"

# The archive links to Google's Nov 12 release. The Search details below are
# sourced from the section “Fast, everyday help in the Gemini app and Search”
# in the Nov 16 update to that same release (now hosted at blog.google).
# Require both the model identity and Search rollout in the stored locale.
_HYDROGEN = {
    "en": {
        "seo_title": "What Can Gemini 4 Hydrogen Do in Google Search?",
        "description": (
            "Google says Gemini 4 Hydrogen helps Search understand questions with several parts, "
            "give visual answers and find links by exploring related queries."
        ),
        "heading": "How a search changes",
        "identity_evidence": (
            "According to Google DeepMind: Google is introducing Gemini 4 Hydrogen, "
            "a new model designed for rapid execution and everyday agentic workflows."
        ),
        "search_evidence": (
            "Ecosystem Integration Hydrogen is rolling out globally across the Gemini API, "
            "Google AI Studio, the Gemini app, Google Search, and enterprise tools."
        ),
        "points": (
            ("Can I ask about several things at once?",
             "For example, you could ask which Boston neighborhoods have parks nearby and a short trip "
             "downtown. Google says Search can pick up several conditions in one question, even with typos."),
            ("Where do the extra links come from?",
             "Google says Search also looks up related questions. This can turn up useful pages that "
             "use different words from the ones you typed."),
            ("What might the answer look like?",
             "Google’s announcement shows visual answers for searches about neighborhoods and sneakers. "
             "The layout and links can vary with the question."),
        ),
    },
    "zh": {
        "seo_title": "Gemini 4 Hydrogen 能在谷歌搜索里做什么？",
        "description": (
            "据谷歌介绍，Gemini 4 Hydrogen 能帮助谷歌搜索读懂包含多个条件的问题，用图文呈现答案，"
            "并通过检索相关问题找到更多有用的链接。"
        ),
        "heading": "一次搜索会有什么变化",
        "identity_evidence": (
            "据Google DeepMind发布的信息：谷歌推出了全新模型 Gemini 4 Hydrogen，"
            "旨在提供快速执行能力和日常的智能体工作流。"
        ),
        "search_evidence": (
            "生态整合与应用 Hydrogen 目前正在向全球的开发者、企业和普通消费者全面推送，"
            "覆盖 Gemini API、AI Studio、Gemini App 以及谷歌搜索。"
        ),
        "points": (
            ("能把几个条件放进同一个问题吗？",
             "例如，你可以问“波士顿哪些街区附近有公园，去市中心也方便？”据谷歌介绍，即使有拼写错误，"
             "搜索也能识别同一个问题里的多个条件。"),
            ("更多相关链接从哪里来？",
             "据谷歌介绍，搜索还会检索与你的问题相关的其他问题。这样，即使某个网页使用了不同的说法，"
             "也有机会出现在结果里。"),
            ("答案会怎样呈现？",
             "谷歌在公告中展示了查询街区和运动鞋时得到的图文答案。具体版式和链接会随问题而变化。"),
        ),
    },
}


def _text(value):
    # The cloud archive keeps Markdown in its stored text. Public JSON strips
    # heading/emphasis marks, so compare the same visible words on both paths.
    if not isinstance(value, str):
        return ""
    visible = re.sub(r"(?m)^ {0,3}#{1,6} +", "", value).replace("**", "")
    return re.sub(r"\s+", " ", normalize("NFKC", visible)).strip()


def _contains_sentence(text, sentence):
    """Require a reviewed sentence, rather than a clause in changed context."""
    start = text.find(_text(sentence))
    if start < 0:
        return False
    # A qualifier or negation immediately before the matched text changes its meaning.
    preceding = text[:start].rstrip()
    return not preceding or preceding[-1] in ".!?。！？"


def article_search_context(record, locale):
    """Return three concise reader questions, or None without reviewed evidence.

    ``record`` follows export_archive's normalized schema. The reviewed answers
    paraphrase the linked release and label a hypothetical search as an example.

    All returned values are plain text. The renderer must escape the strings
    and use its normal URL validation/escaping before creating an HTML link.
    Inputs, article dates, canonical URLs and underlying facts are untouched.
    """
    if not isinstance(record, Mapping) or not isinstance(locale, str) or locale not in _HYDROGEN:
        return None
    if str(record.get("id")) != _HYDROGEN_ID or record.get("url") != _HYDROGEN_SOURCE:
        return None
    text = record.get(locale)
    if not isinstance(text, Mapping):
        return None
    profile = _HYDROGEN[locale]
    sources = [_text(text.get(key)) for key in ("summary", "full")]
    if not all(
        any(_contains_sentence(source, profile[key]) for source in sources)
        for key in ("identity_evidence", "search_evidence")
    ):
        return None
    return {
        "seo_title": profile["seo_title"],
        "description": profile["description"],
        "heading": profile["heading"],
        "points": [
            {"question": question, "answer": answer}
            for question, answer in profile["points"]
        ],
        "source_url": record["url"],
    }
