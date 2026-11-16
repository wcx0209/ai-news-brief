"""Deterministic local typography for weekly share cards; no external services."""

from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import re

from PIL import Image, ImageDraw, ImageFont

from weekly_seo import WEEKLY_TYPES, weekly_period, weekly_topic


SIZE = (1200, 630)
ORANGE = "#ff5a24"
INK = "#161616"
GRAY = "#696969"
PAPER = "#f5f5f2"
_CJK_FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/System/Library/Fonts/STHeiti Medium.ttc",
    "/System/Library/Fonts/STHeiti Light.ttc",
)
_LATIN_FONTS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)
_COPY = {
    "en": {"index_topic": "Evidence, context and what comes next",
           "index_period": "Weekly editions · Singapore time",
           "footer": "SOURCE-LINKED TECH ANALYSIS",
           "omitted": "Topic omitted for length. Open the issue for the complete headline."},
    "zh": {"index_topic": "读懂每周科技变化与证据边界",
           "index_period": "历期周报 · 新加坡时间",
           "footer": "来源 · 结构 · 可能影响",
           "omitted": "本期主题较长，封面省略；请打开周报阅读完整标题。"},
}


@dataclass(frozen=True)
class _Line:
    role: str
    text: str
    size: int
    font_path: str
    xy: tuple[int, int]
    bbox: tuple[int, int, int, int]
    color: str


@lru_cache(maxsize=128)
def _font(path, size):
    return ImageFont.truetype(path, size)


def _glyph_key(font, character):
    mask = font.getmask(character)
    return mask.size, bytes(mask)


def _check_glyphs(font, text):
    missing = _glyph_key(font, "\uffff")
    if any(_glyph_key(font, character) == missing for character in set(text) if not character.isspace()):
        raise RuntimeError("weekly_cover_font_missing_glyph; install fonts-noto-cjk")


def _font_path(locale, text):
    needs_cjk = locale == "zh" or any("\u2e80" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"
                                     or 0x20000 <= ord(char) <= 0x313ff for char in text)
    candidates = _CJK_FONTS if needs_cjk else (*_LATIN_FONTS, *_CJK_FONTS)
    for candidate in candidates:
        if not Path(candidate).is_file():
            continue
        try:
            font = _font(candidate, 32)
            _check_glyphs(font, text + ("科技周报" if needs_cjk else ""))
        except (OSError, RuntimeError):
            continue
        return candidate
    kind = "cjk" if needs_cjk else "latin"
    raise RuntimeError(f"weekly_cover_{kind}_font_required; install fonts-noto-cjk")


def _width(font, text):
    box = font.getbbox(text, anchor="lt")
    return box[2] - box[0]


def _wrap(text, font, width):
    """Wrap CJK at characters and Latin at words, splitting only oversized words."""
    normalized = " ".join(text.split())
    tokens = re.findall(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*|\s+|.", normalized)
    lines, line = [], ""
    for token in tokens:
        if not line and token.isspace():
            continue
        if _width(font, line + token) <= width:
            line += token
            continue
        if line.strip():
            lines.append(line.rstrip())
            line = ""
        token = token.lstrip()
        for character in token:
            if line and _width(font, line + character) > width:
                lines.append(line)
                line = ""
            line += character
    if line.strip():
        lines.append(line.rstrip())
    return lines


def _text_line(role, text, path, size, left, top, color):
    font = _font(path, size)
    box = font.getbbox(text, anchor="lt")
    width, height = box[2] - box[0], box[3] - box[1]
    return _Line(role, text, size, path, (left - box[0], top - box[1]),
                 (left, top, left + width, top + height), color)


def _fit_topic(text, path, locale):
    width, height = 1048, 282
    # Published headlines are bounded; defend direct callers against huge input too.
    sizes = range(76 if locale == "en" else 72, 27, -2) if len(text) <= 2000 else ()
    for size in sizes:
        font = _font(path, size)
        lines = _wrap(text, font, width)
        line_height = round(size * 1.22)
        if lines and (len(lines) - 1) * line_height + max(font.getbbox(line, anchor="lt")[3] for line in lines) <= height:
            return lines, size, line_height
    # Omit the whole oversized topic explicitly rather than cutting a factual claim.
    size = 38
    return _wrap(_COPY[locale]["omitted"], _font(path, size), width), size, round(size * 1.22)


def _cover_layout(payload, locale):
    """Return the measured lines used by the renderer, with inspectable true ink bounds."""
    if locale not in _COPY:
        raise ValueError("locale must be en or zh")
    topic = weekly_topic(payload, locale) if payload is not None else _COPY[locale]["index_topic"]
    period = (weekly_period(payload, locale) + " · SGT") if payload is not None else _COPY[locale]["index_period"]
    label = WEEKLY_TYPES[locale]
    path = _font_path(locale, topic + period + label + _COPY[locale]["footer"] + _COPY[locale]["omitted"])
    lines = [_text_line("brand", "POLYEMERGENCE", path, 25, 76, 64, ORANGE),
             _text_line("type", label.upper() if locale == "en" else label, path, 29, 76, 136, INK)]
    wrapped, size, line_height = _fit_topic(topic, path, locale)
    lines.extend(_text_line("topic", text, path, size, 76, 207 + index * line_height, INK)
                 for index, text in enumerate(wrapped))
    lines.extend((_text_line("period", period, path, 26, 76, 533, GRAY),
                  _text_line("footer", _COPY[locale]["footer"], path, 18, 76, 585, GRAY)))
    for line in lines:
        if not (0 <= line.bbox[0] < line.bbox[2] <= SIZE[0] - 60
                and 0 <= line.bbox[1] < line.bbox[3] <= SIZE[1] - 20):
            raise ValueError("weekly_cover_text_outside_canvas")
    return lines


def render_weekly_cover(payload, locale):
    """Render a 1200×630 PNG in memory, using only supplied publication text."""
    lines = _cover_layout(payload, locale)
    canvas = Image.new("RGB", SIZE, PAPER)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 14, SIZE[1]), fill=ORANGE)
    draw.line((76, 111, 1124, 111), fill="#d1d1ce", width=2)
    draw.line((76, 509, 1124, 509), fill="#d1d1ce", width=2)
    draw.rectangle((1056, 54, 1124, 72), fill=ORANGE)
    for line in lines:
        draw.text(line.xy, line.text, font=_font(line.font_path, line.size), fill=line.color, anchor="lt")
    output = BytesIO()
    canvas.save(output, format="PNG", compress_level=9, optimize=False)
    return output.getvalue()
