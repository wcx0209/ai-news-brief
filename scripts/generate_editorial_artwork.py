#!/usr/bin/env python3
"""Reproduce self-contained, code-native editorial SVGs; no image generation/API."""

import argparse
from html import escape
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from editorial_domains import domains


PAPER = "#F3F1EB"
INK = "#202124"
GRAY = "#85878A"
ORANGE = "#FF5A24"
LIGHT = "#D8D7D2"
WHITE = "#FFFFFF"


def line(x1, y1, x2, y2, color=GRAY, width=3, extra=""):
    return f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="{width}" {extra}/>'


def path(value, color=INK, width=4, fill="none", extra=""):
    return f'<path d="{value}" fill="{fill}" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round" {extra}/>'


def circle(x, y, radius, fill=WHITE, stroke=INK, width=3):
    return f'<circle cx="{x}" cy="{y}" r="{radius}" fill="{fill}" stroke="{stroke}" stroke-width="{width}"/>'


def rect(x, y, width, height, fill=WHITE, stroke=INK, weight=3, rx=0):
    return f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{weight}"/>'


def polygon(points, fill=WHITE, stroke=INK, width=3):
    return f'<polygon points="{points}" fill="{fill}" stroke="{stroke}" stroke-width="{width}" stroke-linejoin="round"/>'


def motif(domain):
    """Abstract field symbols, not illustrations of a real event or evidence."""
    if domain == "ai":
        nodes = [(100, 100), (100, 235), (100, 370), (300, 65), (300, 205), (300, 345), (510, 135), (510, 300)]
        links = [(0, 3), (0, 4), (1, 3), (1, 4), (1, 5), (2, 4), (2, 5), (3, 6), (4, 6), (4, 7), (5, 7)]
        return "".join(line(*nodes[a], *nodes[b], LIGHT, 3) for a, b in links) + "".join(
            circle(x, y, 25, ORANGE if i in (3, 6) else WHITE, INK if i not in (3, 6) else ORANGE, 4)
            for i, (x, y) in enumerate(nodes))
    if domain == "programmable_life":
        rungs = [(110, 80, 460, 80), (170, 140, 400, 140), (245, 200, 325, 200),
                 (245, 260, 325, 260), (170, 320, 400, 320), (110, 380, 460, 380)]
        return ("".join(line(*rung, LIGHT, 6) for rung in rungs) +
                path("M110 60 C110 170 460 280 460 400", INK, 12) +
                path("M460 60 C460 170 110 280 110 400", ORANGE, 12) +
                "".join(circle(x, y, 10, ORANGE if x > 280 else INK, "none", 0) for rung in rungs for x, y in (rung[:2], rung[2:])))
    if domain == "energy_storage":
        return (rect(110, 95, 365, 270, WHITE, INK, 5, 15) + rect(475, 175, 30, 110, INK, INK, 0, 5) +
                "".join(rect(x, 125, 78, 210, ORANGE if i == 2 else LIGHT, "none", 0, 4) for i, x in enumerate((140, 243, 346))) +
                path("M265 155 L225 240 H285 L252 307 L350 210 H292 L324 155 Z", INK, 3, WHITE))
    if domain == "robotics_autonomy":
        return (path("M110 388 H460", INK, 7) + polygon("165,388 190,323 255,323 280,388", LIGHT) +
                path("M220 325 L245 210 L395 125 L470 185", INK, 32) +
                path("M220 325 L245 210 L395 125 L470 185", WHITE, 21) +
                circle(245, 210, 30, WHITE, INK, 5) + circle(395, 125, 27, ORANGE, ORANGE, 5) +
                path("M470 185 L495 218 L475 253 M470 185 L443 218 L460 253", ORANGE, 9) + circle(220, 325, 22, WHITE, INK, 5))
    if domain == "quantum_technology":
        return ('<ellipse cx="300" cy="235" rx="228" ry="76" fill="none" stroke="#85878A" stroke-width="4"/>' +
                '<ellipse cx="300" cy="235" rx="118" ry="210" fill="none" stroke="#202124" stroke-width="4"/>' +
                path("M110 105 C390 15 555 300 475 365 C350 460 110 245 110 105 Z", GRAY, 4) +
                circle(300, 235, 36, ORANGE, ORANGE, 0) + circle(72, 235, 13, INK, INK, 0) +
                circle(400, 126, 13, ORANGE, ORANGE, 0) + circle(300, 445, 13, INK, INK, 0))
    if domain == "space_economy":
        return ('<ellipse cx="300" cy="240" rx="245" ry="130" fill="none" stroke="#85878A" stroke-width="3"/>' +
                circle(300, 240, 118, WHITE, INK, 5) +
                path("M215 160 C325 185 370 265 335 350 M190 230 C275 265 355 255 410 220", LIGHT, 5) +
                polygon("445,95 483,115 460,153 423,132", ORANGE, ORANGE, 3) +
                polygon("414,108 389,93 370,122 395,138", WHITE) + polygon("490,134 514,150 496,180 471,164", WHITE) +
                line(446, 118, 430, 92, INK, 4) + circle(430, 92, 6, INK, INK, 0))
    if domain == "advanced_materials":
        return (polygon("95,287 300,190 505,287 300,390", LIGHT, GRAY, 3) +
                polygon("95,224 300,127 505,224 300,327", WHITE, INK, 4) +
                polygon("95,161 300,64 505,161 300,264", ORANGE, ORANGE, 3) +
                "".join(line(x1, y1, x2, y2, PAPER, 2) for x1, y1, x2, y2 in
                        [(164, 129, 369, 232), (232, 96, 438, 198), (164, 198, 369, 96), (232, 232, 438, 129)]))
    if domain == "neurotechnology":
        points = [(90, 235), (205, 145), (205, 325), (335, 80), (335, 210), (335, 375), (490, 125), (510, 300)]
        edges = [(0, 1), (0, 2), (1, 3), (1, 4), (2, 4), (2, 5), (4, 6), (4, 7), (5, 7)]
        return ("".join(line(*points[a], *points[b], GRAY, 5) for a, b in edges) +
                "".join(circle(x, y, 21 if i == 4 else 13, ORANGE if i in (4, 6, 7) else WHITE,
                               ORANGE if i in (4, 6, 7) else INK, 4) for i, (x, y) in enumerate(points)) +
                path("M52 245 H100 L122 215 L142 260 L166 235 H202", INK, 4))
    if domain == "climate_water_environment":
        return (path("M300 45 C270 100 160 205 160 285 C160 365 220 410 300 410 C380 410 440 365 440 285 C440 205 330 100 300 45 Z", INK, 5, WHITE) +
                path("M165 290 C215 260 245 320 300 290 C350 260 390 320 435 290 L420 350 Q385 406 300 407 Q215 406 180 350 Z", ORANGE, 0, ORANGE) +
                path("M205 220 C205 190 240 145 260 123", GRAY, 5) +
                path("M80 440 C150 420 190 457 255 440 C325 420 370 457 440 440 C470 432 495 432 520 439", GRAY, 3))
    if domain == "agrifood_technology":
        return (path("M300 410 V95 M300 225 L220 165 M300 305 L390 245", INK, 7) +
                path("M300 245 C185 243 130 180 130 105 C220 105 300 150 300 245 Z", GRAY, 4, WHITE) +
                path("M300 324 C410 324 475 270 475 185 C365 185 300 240 300 324 Z", INK, 4, WHITE) +
                path("M300 155 C300 80 365 45 435 45 C435 125 370 166 300 155 Z", ORANGE, 4, ORANGE) +
                path("M300 240 L172 145 M300 323 L430 220", LIGHT, 3) + line(185, 410, 420, 410, INK, 4))
    if domain == "advanced_manufacturing":
        return (path("M90 390 V80 H510 V390 M140 390 V130 H460 V390", INK, 5) +
                rect(245, 115, 110, 55, LIGHT, INK, 3, 4) + path("M300 170 V210", INK, 8) +
                polygon("180,315 300,255 420,315 300,375", LIGHT, INK, 3) +
                polygon("180,280 300,220 420,280 300,340", WHITE, INK, 3) +
                polygon("180,245 300,185 420,245 300,305", ORANGE, ORANGE, 3) + line(60, 410, 540, 410, INK, 5))
    return (circle(300, 235, 190, "none", LIGHT, 3) + circle(300, 235, 137, "none", GRAY, 3) +
            polygon("125,295 300,215 475,295 300,380", LIGHT, GRAY, 3) +
            polygon("125,235 300,155 475,235 300,320", WHITE, INK, 4) +
            polygon("125,175 300,95 475,175 300,260", ORANGE, ORANGE, 3))


def render_artwork(domain, label="Emerging technology"):
    grid = "".join(line(x, 40, x, 635, LIGHT, 1) for x in range(60, 1200, 90))
    grid += "".join(line(40, y, 1160, y, LIGHT, 1) for y in range(65, 675, 90))
    mark = (ROOT / "web/public/assets/mark.svg").read_text(encoding="utf-8")
    paths = mark[mark.index("  <path"):mark.rindex("</svg>")].strip()
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 675" width="1200" height="675" role="img" aria-labelledby="title desc">
  <title id="title">Polyemergence editorial artwork — {escape(label)}</title>
  <desc id="desc">Abstract brand illustration, not a source image or a depiction of a reported event.</desc>
  <rect width="1200" height="675" fill="{PAPER}"/>
  <g opacity=".38">{grid}</g>
  <rect x="40" y="40" width="1120" height="595" fill="none" stroke="{LIGHT}" stroke-width="1"/>
  <g transform="translate(78 92) scale(1.32)">{paths}</g>
  <path d="M84 370 H326 M84 387 H244" fill="none" stroke="{GRAY}" stroke-width="2"/>
  <rect x="84" y="420" width="96" height="8" fill="{ORANGE}"/>
  <g transform="translate(470 70)">{motif(domain)}</g>
  <text x="84" y="581" fill="{INK}" font-family="Arial, Helvetica, sans-serif" font-size="29" font-weight="700" letter-spacing="-.7">Polyemergence</text>
  <path d="M470 581 H1080" fill="none" stroke="{GRAY}" stroke-width="1"/>
</svg>
'''


def generate(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    fields = [(field["id"], field["label"]["en"]) for field in domains()]
    for domain, label in [*fields, ("general", "Emerging technology")]:
        (output / f"{domain}.svg").write_text(render_artwork(domain, label), encoding="utf-8")
    return len(fields) + 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=str(ROOT / "web/public/assets/editorial"))
    args = parser.parse_args()
    print(f"Generated {generate(args.output)} local editorial SVGs")


if __name__ == "__main__":
    main()
