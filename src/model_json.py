"""Strict, bounded JSON-object parsing for model responses, with no repair.

The only tolerated presentation wrapper is one complete ``json`` code fence.
Parsing never extracts a substring, fills fields, changes prose or punctuation,
or treats a syntactically valid object as a validated report.
"""

import json
import math
import re


MAX_RESPONSE_CHARS = 200_000
_JSON_FENCE = re.compile(
    r"\A```json[ \t]*\r?\n(?P<body>[\s\S]*)\r?\n```[ \t]*\Z",
    re.IGNORECASE,
)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("model_json_duplicate_key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("model_json_non_finite_number")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("model_json_non_finite_number")
    return result


def parse_json_response(text):
    """Return exactly one JSON object, or raise a fixed-code ``ValueError``.

    Leading/trailing whitespace and one whole, paired JSON code fence are
    allowed. Root arrays/scalars, non-finite values and duplicate keys anywhere
    in the object are rejected. Required fields and content checks remain the
    responsibility of the downstream schema/evidence validators.
    """
    if not isinstance(text, str):
        raise ValueError("model_json_response_must_be_text")
    if len(text) > MAX_RESPONSE_CHARS:
        raise ValueError("model_json_response_too_large")
    content = text.strip()
    if content.startswith("```"):
        fence = _JSON_FENCE.fullmatch(content)
        if fence is None:
            raise ValueError("model_json_invalid_fence")
        content = fence.group("body")
    try:
        result = json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
            parse_float=_finite_float,
        )
    except json.JSONDecodeError:
        # Do not propagate the input, a nearby prose excerpt, or provider data.
        raise ValueError("model_json_invalid_json") from None
    if not isinstance(result, dict):
        raise ValueError("model_json_response_must_be_object")
    return result
