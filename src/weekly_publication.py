"""Fail-closed weekly publication checks and a strict public-field allowlist.

No database, network, model, filesystem writes or independent fact-checking is
performed. Passing this gate establishes process/traceability, not claim truth.
"""

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import re
from urllib.parse import parse_qsl, unquote, urlsplit
from zoneinfo import ZoneInfo

from source_images import normalize_source_url
from weekly_generation import validate_draft
from weekly_synthesis import DIMENSIONS, evidence_components, validate_synthesis


SGT = ZoneInfo("Asia/Singapore")
SUCCESS_STATUSES = {
    "success", "completed", "publication_ready", "draft_ready_for_human_review",
    "revised_draft_ready_for_human_review", "synthesis_draft_ready_for_human_review",
}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}\Z")
_EMAIL = re.compile(r"[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_TOKEN = re.compile(r"\b(?:AIza[A-Za-z0-9_-]{25,}|sk-(?:proj-)?[A-Za-z0-9_-]{20,})\b")
_CREDENTIAL_KEYS = {"token", "access_token", "api_key", "apikey", "key", "password", "secret",
                    "authorization", "auth", "sig", "signature", "email"}


def _fail(reason):
    raise ValueError("weekly_publication_" + reason)


def _identifier(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        _fail("unsafe_identifier")
    return value


def _datetime(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            _fail("timezone_required")
        return result.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError):
        _fail("invalid_timestamp")


def _iso(value):
    return value.isoformat().replace("+00:00", "Z")


def _calendar_date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        _fail("invalid_calendar_date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail("invalid_calendar_date")


def latest_completed_week(now=None):
    """SGT Monday of the previous complete Monday-to-Sunday week."""
    local = _datetime(now if now is not None else datetime.now(timezone.utc)).astimezone(SGT)
    current_monday = local.date() - timedelta(days=local.weekday())
    return (current_monday - timedelta(days=7)).isoformat()


def _period(issue):
    if not isinstance(issue, dict) or issue.get("timezone") != "Asia/Singapore":
        _fail("invalid_issue_timezone")
    monday = _calendar_date(issue.get("week_start"))
    if monday.weekday() != 0 or issue.get("week_end") != (monday + timedelta(days=6)).isoformat():
        _fail("invalid_week_dates")
    start = datetime.combine(monday, time.min, SGT).astimezone(timezone.utc)
    end = start + timedelta(days=7)
    if issue.get("end_exclusive") is not True:
        _fail("period_must_be_right_open")
    for names, expected in ((("start", "period_start"), start), (("end", "period_end"), end)):
        supplied = [issue[name] for name in names if name in issue]
        if not supplied or any(_datetime(value) != expected for value in supplied):
            _fail("period_does_not_match_sgt_week")
    return monday, start, end


def _text(value, limit=3000, *, required=True):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        _fail("invalid_public_text")
    if _EMAIL.search(value) or _TOKEN.search(value) or any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        _fail("private_data_in_public_text")
    return value


def _url(value, *, archive_locale=None):
    if not isinstance(value, str) or not normalize_source_url(value) or _EMAIL.search(value) or _TOKEN.search(value):
        _fail("unsafe_source_url")
    parsed = urlsplit(value)
    if any(key.casefold() in _CREDENTIAL_KEYS or key.casefold().startswith(("x-amz-", "x-goog-"))
           for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
        _fail("credential_source_url")
    if any(part in {".", ".."} for part in unquote(parsed.path).split("/")):
        _fail("source_url_path_traversal")
    if archive_locale and (parsed.scheme != "https" or parsed.netloc != "polyemergence.com"
                           or not parsed.path.startswith(f"/{archive_locale}/archive/")
                           or parsed.query or parsed.fragment):
        _fail("invalid_archive_url")
    return value


def _refs(value, allowed):
    if (not isinstance(value, list) or not value or len(value) > 12
            or any(not isinstance(item, str) or item not in allowed for item in value)
            or len(set(value)) != len(value)):
        _fail("invalid_public_references")
    return [_identifier(item) for item in value]


def _event(value, allowed):
    if not isinstance(value, dict):
        _fail("invalid_public_event")
    return {"event_id": _identifier(value.get("event_id")),
            **{name: _text(value.get(name), limit) for name, limit in (
                ("title", 220), ("what_changed", 1800), ("why_it_matters", 1400), ("uncertainty", 1000))},
            "evidence_ids": _refs(value.get("evidence_ids"), allowed)}


def _locale(value, allowed):
    synthesis = value["synthesis"]
    clean_synthesis = {"intro": _text(synthesis["intro"], 800), "limits": _text(synthesis["limits"], 1000),
                       "evidence_ids": _refs(synthesis["evidence_ids"], allowed)}
    for dimension in DIMENSIONS:
        part = synthesis[dimension]
        clean_synthesis[dimension] = {"title": _text(part["title"], 160), "text": _text(part["text"], 1500),
                                      "support": part["support"], "evidence_ids": _refs(part["evidence_ids"], allowed)}
    follow = value.get("follow_up") or {"available": False, "note": "", "items": []}
    if not isinstance(follow, dict) or not isinstance(follow.get("available"), bool) or not isinstance(follow.get("items", []), list):
        _fail("invalid_follow_up")
    if not follow["available"] and follow.get("items"):
        _fail("unavailable_follow_up_has_items")
    return {
        "title": _text(value["title"], 180), "dek": _text(value["dek"], 800), "synthesis": clean_synthesis,
        "lead": {"text": _text(value["lead"]["text"], 2400), "evidence_ids": _refs(value["lead"]["evidence_ids"], allowed)},
        "main_events": [_event(event, allowed) for event in value["main_events"]],
        "early_signals": [_event(event, allowed) for event in value["early_signals"]],
        "next_watch": [{"text": _text(item["text"], 1000), "evidence_ids": _refs(item["evidence_ids"], allowed)}
                       for item in value["next_watch"]],
        "follow_up": {"available": follow["available"], "note": _text(follow.get("note", ""), 1000, required=False),
                      "items": [_event(item, allowed) for item in follow.get("items", [])]},
    }


def _audit_clean(audit, *, historical=False):
    if not isinstance(audit, dict) or not isinstance(audit.get("issues"), list):
        _fail("missing_automated_audit")
    for issue in audit["issues"]:
        if not isinstance(issue, dict) or issue.get("severity") not in {"high", "medium", "low"}:
            _fail("invalid_automated_audit")
        if not historical and issue["severity"] in {"high", "medium"}:
            _fail("unresolved_editorial_issue")


def _automatic_gate(report, metadata):
    if not isinstance(metadata, dict) or metadata.get("status") not in SUCCESS_STATUSES:
        _fail("generation_not_successful")
    review = report.get("editorial_review")
    if not isinstance(review, dict):
        _fail("missing_automated_audit")
    if "revision_made" in review and not isinstance(review["revision_made"], bool):
        _fail("invalid_revision_state")
    if review.get("revision_made") is True:
        _audit_clean(review.get("audit"), historical=True)
        post = review.get("post_revision_audit") or metadata.get("post_revision_audit")
        _audit_clean(post)
    else:
        _audit_clean(review.get("audit"))


def _no_false_verification(report):
    for mapping in (report, report.get("issue"), report.get("editorial_review"), report.get("process")):
        if not isinstance(mapping, dict):
            continue
        for name in ("verified", "fact_verified", "fact_checked", "human_approved", "human_reviewed",
                     "independently_verified", "independent_fact_check_complete"):
            if mapping.get(name) is True:
                _fail("unsupported_verification_attestation")


def _source(row, monday, start, end):
    label = _text(row.get("source"), 240)
    if label.casefold() in {"unknown", "unknown source", "unspecified", "未知", "未知来源"}:
        _fail("unknown_source")
    raw_date = row.get("source_published_at") or row.get("published_at")
    if row.get("date_basis") in {"first_seen", "unknown", "site_published", "updated"}:
        _fail("unknown_source_date")
    precision = row.get("date_precision") or "timestamp"
    if precision == "publisher_calendar_date_only":
        source_day = _calendar_date(raw_date)
        if not monday <= source_day <= monday + timedelta(days=6):
            _fail("source_outside_week")
        stamp = source_day.isoformat()
    elif precision == "timestamp":
        source_time = _datetime(raw_date)
        if not start <= source_time < end:
            _fail("source_outside_week")
        stamp = _iso(source_time)
    else:
        _fail("unknown_source_date_precision")
    domain = _identifier(row.get("domain"))
    labels = row.get("domain_labels") if isinstance(row.get("domain_labels"), dict) else {}
    result = {"id": _identifier(row.get("id")), "url": _url(row.get("url")), "source": label,
              "published_at": stamp, "date_precision": precision, "domain": domain,
              "domain_labels": {locale: _text(labels.get(locale, domain), 160) for locale in ("en", "zh")}}
    for locale in ("en", "zh"):
        localized = row.get(locale) if isinstance(row.get(locale), dict) else {}
        result[locale] = {"title": _text(localized.get("title"), 240)}
        archive = row.get("archive_url_" + locale)
        result["archive_url_" + locale] = _url(archive, archive_locale=locale) if archive else None
    return result


def _coverage(value):
    fields = value.get("fields", []) if isinstance(value, dict) else []
    if not isinstance(fields, list) or len(fields) > 100:
        _fail("invalid_coverage")
    clean, seen = [], set()
    for field in fields:
        if not isinstance(field, dict):
            _fail("invalid_coverage")
        domain = _identifier(field.get("domain"))
        if domain in seen:
            _fail("duplicate_coverage_domain")
        seen.add(domain)
        labels = field.get("domain_labels") if isinstance(field.get("domain_labels"), dict) else {}
        counts = {}
        for name in ("selected_count", "qualified_count"):
            count = field.get(name, 0)
            if isinstance(count, bool) or not isinstance(count, int) or not 0 <= count <= 10000:
                _fail("invalid_coverage_count")
            counts[name] = count
        clean.append({"domain": domain, "domain_labels": {locale: _text(labels.get(locale, domain), 160)
                                                           for locale in ("en", "zh")}, **counts})
    return {"scope": "loaded_archive_only", "fields": clean}


def prepare_publication(report, packet, catalog, *, published_at, prior=None,
                        user_authorized=False, generation_metadata=None, manual_correction=False, now=None):
    """Validate a finished weekly and return only safe public content fields.

    Explicit user authorization bypasses automated review-state gating, not
    chronology, citation, bilingual, source-safety or privacy checks. It never
    becomes a claim of human review or independent factual verification.
    """
    if not isinstance(report, dict) or not isinstance(packet, dict) or not isinstance(catalog, list):
        _fail("invalid_input")
    if not isinstance(user_authorized, bool) or not isinstance(manual_correction, bool):
        _fail("invalid_authorization")
    monday, start, end = _period(report.get("issue"))
    if _period(packet.get("issue")) != (monday, start, end):
        _fail("packet_period_mismatch")
    current = _datetime(now if now is not None else datetime.now(timezone.utc))
    publication = _datetime(published_at)
    generated = _datetime(report["issue"].get("generated_at"))
    if end > current or publication < end or publication > current + timedelta(minutes=5):
        _fail("invalid_publication_time")
    if generated < end or generated > publication:
        _fail("invalid_generation_time")
    _no_false_verification(report)
    if not user_authorized:
        _automatic_gate(report, generation_metadata)
    for section in ("main_events", "early_signals"):
        events = packet.get(section)
        if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
            _fail("invalid_event_plan")
        for event in events:
            _identifier(event.get("event_id"))
            if not isinstance(event.get("evidence_ids"), list):
                _fail("invalid_event_sources")
            for source_id in event["evidence_ids"]:
                _identifier(source_id)
    if len(packet["main_events"]) < 3 or len(packet["main_events"]) + len(packet["early_signals"]) > 12:
        _fail("invalid_event_count")
    if len(catalog) > 100:
        _fail("source_count_bound")
    rows = {}
    for row in catalog:
        if not isinstance(row, dict):
            _fail("invalid_source_catalog")
        key = _identifier(row.get("id"))
        if key in rows:
            _fail("duplicate_source_id")
        rows[key] = row
    components = evidence_components(packet, catalog)
    main_components = {components[source_id] for event in packet["main_events"] for source_id in event["evidence_ids"]}
    if len(main_components) < 3:
        _fail("requires_three_distinct_main_events")
    if any(not isinstance(report.get(locale), dict) or "synthesis" not in report[locale] for locale in ("en", "zh")):
        _fail("synthesis_required")
    validate_draft(report, packet, catalog)
    validate_synthesis({locale: {"synthesis": report[locale]["synthesis"]} for locale in ("en", "zh")}, packet, catalog)
    allowed = set(components)
    locales = {locale: _locale(report[locale], allowed) for locale in ("en", "zh")}
    left, right = locales["zh"]["follow_up"], locales["en"]["follow_up"]
    if (left["available"] != right["available"] or len(left["items"]) != len(right["items"])
            or any(a["event_id"] != b["event_id"] or set(a["evidence_ids"]) != set(b["evidence_ids"])
                   for a, b in zip(left["items"], right["items"]))):
        _fail("bilingual_follow_up_mismatch")
    references = set()
    for locale in locales.values():
        references.update(locale["lead"]["evidence_ids"])
        synthesis = locale["synthesis"]
        references.update(synthesis["evidence_ids"])
        for name in DIMENSIONS:
            references.update(synthesis[name]["evidence_ids"])
        for name in ("main_events", "early_signals", "next_watch"):
            for item in locale[name]:
                references.update(item["evidence_ids"])
        for item in locale["follow_up"]["items"]:
            references.update(item["evidence_ids"])
    payload = {
        "schema_version": 1, "id": monday.isoformat(), "week_start": monday.isoformat(),
        "week_end": (monday + timedelta(days=6)).isoformat(), "timezone": "Asia/Singapore",
        "period_start": _iso(start), "period_end": _iso(end), "published_at": _iso(publication),
        "modified_at": _iso(publication), "generated_at": _iso(generated), **locales,
        "sources": [_source(rows[key], monday, start, end) for key in sorted(references)],
        "coverage": _coverage(report.get("coverage")),
        "process": {"ai_assisted": True, "human_reviewed": False, "independently_verified": False},
    }
    if prior is not None:
        if not isinstance(prior, dict) or any(prior.get(name) != payload[name] for name in (
            "id", "week_start", "week_end", "timezone", "period_start", "period_end")):
            _fail("prior_issue_mismatch")
        first = _datetime(prior.get("published_at"))
        modified = _datetime(prior.get("modified_at") or prior.get("published_at"))
        if not end <= first <= modified <= publication:
            _fail("invalid_prior_publication_time")
        changed = any(prior.get(key) != payload[key] for key in payload if key not in {
            "published_at", "modified_at", "generated_at"})
        if changed and not manual_correction:
            _fail("immutable_existing_issue")
        payload["published_at"] = _iso(first)
        payload["modified_at"] = _iso(publication if changed else modified)
        if not changed:
            payload["generated_at"] = _iso(_datetime(prior.get("generated_at")))
    return deepcopy(payload)
