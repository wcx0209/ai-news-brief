#!/usr/bin/env python3
"""Export already-public weekly payloads without a database, model or network."""

import argparse
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from weekly_public import COPY, SITE, render_weekly_index, render_weekly_issue


SGT = timezone(timedelta(hours=8))
SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
XHTML_NS = "http://www.w3.org/1999/xhtml"
ATOM_NS = "http://www.w3.org/2005/Atom"
EVENT = {key: str for key in ("event_id", "title", "what_changed", "why_it_matters", "uncertainty")}
EVENT["evidence_ids"] = [str]
POINT = {"title": str, "text": str, "support": str, "evidence_ids": [str]}
LOCALE = {"title": str, "dek": str,
          "synthesis": {"intro": str, "limits": str, "evidence_ids": [str],
                        **{key: POINT for key in ("signal", "structure", "consequence")}},
          "lead": {"text": str, "evidence_ids": [str]}, "main_events": [EVENT], "early_signals": [EVENT],
          "next_watch": [{"text": str, "evidence_ids": [str]}],
          "follow_up": {"available": bool, "note": str, "items": [EVENT]}}
PUBLIC_SCHEMA = {
    "schema_version": int, **{key: str for key in (
        "id", "week_start", "week_end", "timezone", "period_start", "period_end",
        "published_at", "modified_at", "generated_at")}, "en": LOCALE, "zh": LOCALE,
    "sources": [{**{key: str for key in ("id", "url", "source", "published_at", "date_precision", "domain")},
                 "archive_url_en": (str, type(None)), "archive_url_zh": (str, type(None)),
                 "domain_labels": {"en": str, "zh": str}, "en": {"title": str}, "zh": {"title": str}}],
    "coverage": {"scope": str, "fields": [{"domain": str, "domain_labels": {"en": str, "zh": str},
                                           "qualified_count": int, "selected_count": int}]},
    "process": {"ai_assisted": bool, "human_reviewed": bool, "independently_verified": bool},
}


def _project(value, schema):
    """Defense in depth: never copy private report/debug fields into public JSON."""
    if isinstance(schema, dict):
        if not isinstance(value, dict):
            raise ValueError("Invalid weekly public object")
        return {key: _project(value[key], child) for key, child in schema.items() if key in value}
    if isinstance(schema, list):
        if not isinstance(value, list):
            raise ValueError("Invalid weekly public list")
        return [_project(item, schema[0]) for item in value]
    if type(value) not in (schema if isinstance(schema, tuple) else (schema,)):
        raise ValueError("Invalid weekly public value")
    return value


def _timestamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Weekly timestamps require a timezone")
        return parsed.astimezone(timezone.utc)
    except (TypeError, AttributeError, ValueError, OverflowError) as error:
        raise ValueError("Invalid weekly timestamp") from error


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Weekly id must be YYYY-MM-DD")
    monday = date.fromisoformat(value)
    if monday.weekday() != 0:
        raise ValueError("Weekly id must identify a Monday")
    return monday


def _canonical(locale, identifier=None):
    return f"{SITE}/{locale}/weekly/" + (f"{identifier}/" if identifier else "")


def _source_url(value, locale=None):
    if value is None and locale:
        return
    if not isinstance(value, str) or re.search(r"[\x00-\x20\\]", value):
        raise ValueError("Unsafe weekly source URL")
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Unsafe weekly source URL")
    if locale and (parsed.scheme != "https" or parsed.netloc != "polyemergence.com"
                   or not parsed.path.startswith(f"/{locale}/archive/") or parsed.query or parsed.fragment):
        raise ValueError("Invalid weekly archive URL")


def validate_payload(payload):
    """Check public route/chronology safety; the publication gate owns editorial QA."""
    clean = _project(payload, PUBLIC_SCHEMA)
    required = {"schema_version", "id", "week_start", "week_end", "timezone", "period_start", "period_end",
                "published_at", "modified_at", "generated_at", "en", "zh", "sources", "process"}
    if required - clean.keys() or clean["schema_version"] != 1:
        raise ValueError("Incomplete public weekly payload")
    monday = _identifier(clean["id"])
    if (clean["week_start"] != clean["id"] or clean["week_end"] != (monday + timedelta(days=6)).isoformat()
            or clean["timezone"] != "Asia/Singapore"):
        raise ValueError("Weekly id and period dates do not match")
    start = datetime.combine(monday, datetime.min.time(), SGT).astimezone(timezone.utc)
    end = start + timedelta(days=7)
    published, modified, generated = (_timestamp(clean[key]) for key in ("published_at", "modified_at", "generated_at"))
    if (_timestamp(clean["period_start"]) != start or _timestamp(clean["period_end"]) != end
            or not end <= published <= modified or not end <= generated <= modified):
        raise ValueError("Invalid weekly publication chronology")
    if clean["process"] != {"ai_assisted": True, "human_reviewed": False, "independently_verified": False}:
        raise ValueError("Unsupported weekly verification attestation")
    for locale in ("en", "zh"):
        if any(not clean[locale].get(key, "").strip() for key in ("title", "dek")):
            raise ValueError("Weekly title and description are required in both languages")
    if "canonical_urls" in payload and payload["canonical_urls"] != {locale: _canonical(locale, clean["id"]) for locale in ("en", "zh")}:
        raise ValueError("Unexpected weekly canonical routes")
    for source in clean["sources"]:
        _source_url(source.get("url"))
        for locale in ("en", "zh"):
            _source_url(source.get("archive_url_" + locale), locale)
    return clean


def _target(output, relative):
    target = output / relative
    if not target.resolve().is_relative_to(output.resolve()):
        raise ValueError("Weekly output path escapes the public directory")
    return target


def load_editions(output):
    """Read dated public JSON only; the lightweight manifest is never an issue."""
    output = Path(output)
    directory = _target(output, "data/weekly")
    editions = []
    for path in sorted(directory.glob("*.json"), reverse=True):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", path.name):
            continue
        _target(output, path.relative_to(output))
        payload = validate_payload(json.loads(path.read_text(encoding="utf-8")))
        if payload["id"] != path.stem:
            raise ValueError("Weekly filename and edition id do not match")
        editions.append(payload)
    return editions


def _json(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def _manifest(editions):
    rows = [{**{key: payload[key] for key in ("id", "week_start", "week_end", "published_at", "modified_at")},
             "json_url": f'{SITE}/data/weekly/{payload["id"]}.json',
             "canonical_urls": {locale: _canonical(locale, payload["id"]) for locale in ("en", "zh")},
             **{locale: {key: payload[locale][key] for key in ("title", "dek")} for locale in ("en", "zh")}}
            for payload in editions]
    return {"schema_version": 1, "latest": editions[0]["id"] if editions else None,
            "modified_at": editions[0]["modified_at"] if editions else None, "editions": rows}


def _rss(editions, locale):
    ET.register_namespace("atom", ATOM_NS)
    root = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(root, "channel")
    for key, value in (("title", COPY[locale]["index_title"]), ("link", _canonical(locale)),
                       ("description", COPY[locale]["index_dek"]), ("language", COPY[locale]["lang"])):
        ET.SubElement(channel, key).text = value
    ET.SubElement(channel, f"{{{ATOM_NS}}}link", {"href": f"{SITE}/weekly-{locale}.xml", "rel": "self", "type": "application/rss+xml"})
    if editions:
        ET.SubElement(channel, "lastBuildDate").text = format_datetime(_timestamp(editions[0]["modified_at"]), usegmt=True)
    for payload in editions:
        item = ET.SubElement(channel, "item")
        for key, value in (("title", payload[locale]["title"]), ("link", _canonical(locale, payload["id"])),
                           ("description", payload[locale]["dek"]),
                           ("pubDate", format_datetime(_timestamp(payload["published_at"]), usegmt=True))):
            ET.SubElement(item, key).text = value
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = _canonical(locale, payload["id"])
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _sitemap(editions):
    ET.register_namespace("", SITEMAP_NS)
    ET.register_namespace("xhtml", XHTML_NS)
    root = ET.Element(f"{{{SITEMAP_NS}}}urlset")
    for payload in [None, *editions]:
        identifier = payload["id"] if payload else None
        modified = payload["modified_at"] if payload else editions[0]["modified_at"] if editions else None
        for locale in ("en", "zh"):
            node = ET.SubElement(root, f"{{{SITEMAP_NS}}}url")
            ET.SubElement(node, f"{{{SITEMAP_NS}}}loc").text = _canonical(locale, identifier)
            if modified:
                ET.SubElement(node, f"{{{SITEMAP_NS}}}lastmod").text = modified
            for language, alternate in (("en", "en"), ("zh-Hans", "zh"), ("x-default", "en")):
                ET.SubElement(node, f"{{{XHTML_NS}}}link", {"rel": "alternate", "hreflang": language, "href": _canonical(alternate, identifier)})
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _check_page(page, locale, identifier=None):
    canonical = re.findall(r'<link\b[^>]*rel="canonical"[^>]*href="([^"]+)"', page)
    if canonical != [_canonical(locale, identifier)]:
        raise ValueError("Rendered weekly page has an unexpected canonical route")


def _atomic_write(path, content):
    if path.is_file() and path.read_bytes() == content:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def export_weeklies(output: Path, payloads: list[dict], *, allow_corrections=False) -> list[Path]:
    """Render everything before writing; retain previously published dated issues."""
    output = Path(output)
    if not isinstance(payloads, list):
        raise ValueError("Weekly payloads must be a list")
    if not isinstance(allow_corrections, bool):
        raise ValueError("Weekly correction authority must be explicit")
    known = {payload["id"]: payload for payload in load_editions(output)}
    supplied = set()
    for payload in payloads:
        clean = validate_payload(payload)
        if clean["id"] in supplied:
            raise ValueError("Duplicate incoming weekly edition id")
        supplied.add(clean["id"])
        previous = known.get(clean["id"])
        if previous is not None and clean != previous:
            if not allow_corrections:
                raise ValueError("Existing weekly editions are immutable without explicit correction authority")
            if clean["published_at"] != previous["published_at"]:
                raise ValueError("Weekly corrections must preserve original published_at")
            if _timestamp(clean["modified_at"]) < _timestamp(previous["modified_at"]):
                raise ValueError("Weekly corrections cannot move modified_at backwards")
        known[clean["id"]] = clean
    editions = [known[key] for key in sorted(known, reverse=True)]
    artifacts = {"data/weekly/index.json": _json(_manifest(editions)), "weekly-sitemap.xml": _sitemap(editions)}
    for payload in editions:
        artifacts[f'data/weekly/{payload["id"]}.json'] = _json(payload)
        for locale in ("en", "zh"):
            page = render_weekly_issue(payload, locale)
            _check_page(page, locale, payload["id"])
            artifacts[f'{locale}/weekly/{payload["id"]}/index.html'] = page.encode("utf-8")
    for locale in ("en", "zh"):
        page = render_weekly_index(editions, locale)
        _check_page(page, locale)
        artifacts[f"{locale}/weekly/index.html"] = page.encode("utf-8")
        artifacts[f"weekly-{locale}.xml"] = _rss(editions, locale)
    # Validate every destination before the first file or directory is changed.
    destinations = [(_target(output, name), content) for name, content in sorted(artifacts.items())]
    for path, content in destinations:
        _atomic_write(path, content)
    return [path for path, _ in destinations]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "web/public")
    args = parser.parse_args(argv)
    paths = export_weeklies(args.output, load_editions(args.output))
    print(f"Exported {len(paths)} public weekly files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
