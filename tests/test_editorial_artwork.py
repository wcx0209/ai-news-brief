import importlib.util
import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
import editorial_artwork as artwork

spec = importlib.util.spec_from_file_location("generate_editorial_artwork", ROOT / "scripts/generate_editorial_artwork.py")
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
SVG = "{http://www.w3.org/2000/svg}"


def path_points(value):
    """Conservative bounds include Bézier control points, not just endpoints."""
    tokens = re.findall(r"[A-Za-z]|[-+]?(?:\d*\.\d+|\d+\.?\d*)", value)
    arity = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2}
    points, position, command, x, y, start = [], 0, None, 0, 0, (0, 0)
    while position < len(tokens):
        if tokens[position].isalpha():
            command = tokens[position]
            position += 1
            if command.upper() == "Z":
                x, y = start
                command = None
                continue
        if command is None or command.upper() not in arity:
            raise AssertionError(f"Unsupported SVG path command: {command}")
        count = arity[command.upper()]
        numbers = list(map(float, tokens[position:position + count]))
        position += count
        if len(numbers) != count:
            raise AssertionError("Incomplete SVG path")
        relative = command.islower()
        kind = command.upper()
        if kind == "H":
            x = numbers[0] + (x if relative else 0)
            points.append((x, y))
        elif kind == "V":
            y = numbers[0] + (y if relative else 0)
            points.append((x, y))
        else:
            pairs = [(numbers[i] + (x if relative else 0), numbers[i + 1] + (y if relative else 0))
                     for i in range(0, count, 2)]
            points.extend(pairs)
            x, y = pairs[-1]
            if kind == "M":
                start = x, y
                command = "l" if relative else "L"
    return points


def geometric_bounds(node, transform=(0, 0, 1, 1)):
    tx, ty, sx, sy = transform
    for kind, raw in re.findall(r"(translate|scale)\(([^)]*)\)", node.get("transform", "")):
        values = [float(value) for value in re.split(r"[ ,]+", raw.strip())]
        if kind == "translate":
            tx += sx * values[0]
            ty += sy * (values[1] if len(values) > 1 else 0)
        else:
            sx *= values[0]
            sy *= values[1] if len(values) > 1 else values[0]
    name = node.tag.removeprefix(SVG)
    points = []
    if name == "path":
        points = path_points(node.get("d", ""))
    elif name in {"circle", "ellipse"}:
        x, y = float(node.get("cx", 0)), float(node.get("cy", 0))
        rx = float(node.get("r", node.get("rx", 0)))
        ry = float(node.get("r", node.get("ry", 0)))
        points = [(x - rx, y - ry), (x + rx, y + ry)]
    elif name == "rect":
        x, y = float(node.get("x", 0)), float(node.get("y", 0))
        points = [(x, y), (x + float(node.get("width", 0)), y + float(node.get("height", 0)))]
    elif name == "line":
        points = [(float(node.get("x1", 0)), float(node.get("y1", 0))),
                  (float(node.get("x2", 0)), float(node.get("y2", 0)))]
    elif name == "polygon":
        values = [float(value) for value in re.split(r"[ ,]+", node.get("points", "").strip())]
        points = list(zip(values[::2], values[1::2]))
    weight = float(node.get("stroke-width", 0)) / 2 if node.get("stroke", "none") != "none" else 0
    for x, y in points:
        yield tx + (x - weight) * sx, ty + (y - weight) * sy
        yield tx + (x + weight) * sx, ty + (y + weight) * sy
    for child in node:
        yield from geometric_bounds(child, (tx, ty, sx, sy))


class EditorialArtworkTests(unittest.TestCase):
    def setUp(self):
        self.catalog = json.loads((ROOT / "web/public/data/editorial-domains.json").read_text())

    def test_all_eleven_domains_and_general_have_local_assets(self):
        self.assertEqual(len(self.catalog["domains"]), 11)
        self.assertEqual(self.catalog["artwork_default"], artwork.GENERAL_ARTWORK)
        for field in self.catalog["domains"]:
            with self.subTest(domain=field["id"]):
                expected = f'/assets/editorial/{field["id"]}.svg'
                self.assertEqual(field["artwork"], expected)
                self.assertEqual(artwork.editorial_artwork_path({"domain": field["id"]}), expected)
                self.assertTrue((artwork.PUBLIC_ROOT / expected.lstrip("/")).is_file())
        self.assertTrue((artwork.PUBLIC_ROOT / artwork.GENERAL_ARTWORK.lstrip("/")).is_file())

    def test_unknown_or_malformed_item_uses_general_not_story_url(self):
        for item in (None, {}, [], {"domain": []}, {"domain": "unknown"}, {"domain": "../../secret"},
                     {"domain": "https://evil.example/a.svg"}, {"artwork": "https://evil.example/a.svg"}):
            with self.subTest(item=item):
                self.assertEqual(artwork.editorial_artwork_path(item), artwork.GENERAL_ARTWORK)

    def test_registry_paths_cannot_escape_asset_directory_or_use_external_url(self):
        for value in ("https://evil.example/a.svg", "//evil.example/a.svg", "/assets/editorial/../mark.svg",
                      "/assets/editorial/%2e%2e/mark.svg", "/assets/editorial/a.svg?x=1", "/assets/editorial/missing.svg"):
            with self.subTest(value=value), patch.object(artwork, "registry", return_value={
                "artwork_default": value, "domains": [{"id": "test", "artwork": value}]
            }):
                self.assertEqual(artwork.editorial_artwork_path({"domain": "test"}), artwork.GENERAL_ARTWORK)

    def test_explicit_bilingual_disclosure(self):
        self.assertEqual(artwork.editorial_caption("en"), "Polyemergence editorial artwork · Not a source image")
        self.assertEqual(artwork.editorial_caption("zh-Hans"), "Polyemergence 编辑配图 · 非原文图片")

    def test_assets_are_safe_self_contained_lightweight_and_complete(self):
        assets = sorted((ROOT / "web/public/assets/editorial").glob("*.svg"))
        self.assertEqual(len(assets), 12)
        mark = ET.parse(ROOT / "web/public/assets/mark.svg").getroot()
        original_paths = [node.get("d") for node in mark.findall(SVG + "path")]
        for asset in assets:
            with self.subTest(asset=asset.name):
                raw = asset.read_text()
                self.assertLess(len(raw.encode()), 12_000)
                self.assertNotRegex(raw.lower(), r"<!doctype|<!entity|javascript:|data:|url\(|@import|https?://(?!www\.w3\.org/2000/svg)")
                root = ET.fromstring(raw)
                self.assertEqual(root.get("viewBox"), "0 0 1200 675")
                self.assertEqual(root.get("width"), "1200")
                self.assertEqual(root.get("height"), "675")
                for node in root.iter():
                    self.assertNotIn(node.tag.removeprefix(SVG), {"script", "image", "foreignObject", "iframe", "animate", "set", "use", "style"})
                    self.assertFalse(any(key.lower().startswith("on") or key.endswith("href") for key in node.attrib))
                brand = root.find(f"{SVG}g[@transform='translate(78 92) scale(1.32)']")
                self.assertEqual([node.get("d") for node in brand], original_paths)
                self.assertEqual(list(brand)[-1].get("fill"), "#FF5A24")
                self.assertIsNone(list(brand)[-1].get("fill-opacity"))
                self.assertEqual([node.text for node in root.iter(SVG + "text")], ["Polyemergence"])
                for x, y in geometric_bounds(root):
                    self.assertGreaterEqual(x, 0)
                    self.assertLessEqual(x, 1200)
                    self.assertGreaterEqual(y, 0)
                    self.assertLessEqual(y, 675)

    def test_generator_reproduces_every_committed_svg(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(generator.generate(directory), 12)
            for asset in Path(directory).glob("*.svg"):
                self.assertEqual(asset.read_bytes(), (ROOT / "web/public/assets/editorial" / asset.name).read_bytes())


if __name__ == "__main__":
    unittest.main()
