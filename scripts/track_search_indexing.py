"""Measure the Google visibility of published PolyEmergence headlines, from cloud jobs."""
import argparse
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo


SITE = "https://polyemergence.com/"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
PACIFIC = ZoneInfo("America/Los_Angeles")
SINGAPORE = ZoneInfo("Asia/Singapore")
CHECKS = (24, 48, 72)
GRACE = timedelta(hours=6)


def utcnow():
    return datetime.now(timezone.utc)


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Publication or observation timestamp must include a timezone")
    return parsed


class LeadReader(HTMLParser):
    def __init__(self):
        super().__init__()
        self.lead_id = None
        self.structured = []
        self.script = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "div" and attrs.get("id") == "lead-story" and "hidden" not in attrs:
            self.lead_id = attrs.get("data-story-id")
        if tag == "script" and attrs.get("type") == "application/ld+json":
            self.script = []

    def handle_data(self, data):
        if self.script is not None:
            self.script.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.script is not None:
            self.structured.append("".join(self.script))
            self.script = None

    @classmethod
    def read(cls, path):
        reader = cls()
        reader.feed(path.read_text(encoding="utf-8"))
        return reader

    def edition_lead(self):
        for raw in self.structured:
            data = json.loads(raw)
            if data.get("@type") == "CollectionPage":
                items = data["mainEntity"]["itemListElement"]
                return next((e["url"] for e in items if e["position"] == 1), None)
        raise ValueError("Daily edition has no CollectionPage metadata")


def discover(public, now):
    articles = json.loads((public / "data/articles.json").read_text())["items"]
    by_id = {item["id"]: item for item in articles}
    by_url = {url: item for item in articles for url in item["canonical_urls"].values()}
    found = []
    today = now.astimezone(SINGAPORE).date()
    for locale, edition_dir in (("en", "daily-ai-news"), ("zh", "ai-news-daily")):
        for offset in range(8):
            day = (today - timedelta(days=offset)).isoformat()
            path = public / locale / edition_dir / day / "index.html"
            if path.exists():
                url = LeadReader.read(path).edition_lead()
                if url:
                    found.append((locale, by_url[url], f"daily-ai:{day}"))
        fields = public / locale / "fields"
        for page in sorted(fields.glob("*/index.html")):
            lead_id = LeadReader.read(page).lead_id
            if lead_id:
                found.append((locale, by_id[lead_id], f"field:{page.parent.name}"))
    result = {}
    for locale, article, cohort in found:
        url = article["canonical_urls"][locale]
        published = timestamp(article["site_published_at"])
        if not url.startswith(f"{SITE}{locale}/archive/") or published > now:
            continue
        row = result.setdefault(url, dict(url=url, locale=locale, published_at=published,
                                          title=article[locale]["title"], cohorts=[]))
        if cohort not in row["cohorts"]:
            row["cohorts"].append(cohort)
    return result


def checkpoint_state(published, checked, hour, now):
    result = checked.get(str(hour))
    if result:
        return result["status"]
    elapsed = now - (published + timedelta(hours=hour))
    if elapsed < timedelta(0):
        return "upcoming"
    return "due" if elapsed < GRACE else "missed"


def make_session():
    import google.auth
    from google.auth.transport.requests import AuthorizedSession
    credentials, _ = google.auth.default(scopes=[SCOPE])
    return AuthorizedSession(credentials)


class GSCError(RuntimeError):
    def __init__(self, status):
        super().__init__(f"Search Console API returned HTTP {status}")
        self.status = status


def gsc_post(session, url, body):
    from requests.exceptions import ConnectionError, Timeout
    for attempt in range(3):
        try:
            response = session.post(url, json=body, timeout=20)
        except (ConnectionError, Timeout):
            if attempt == 2:
                raise GSCError(503) from None
        else:
            if response.ok:
                return response.json()
            if response.status_code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise GSCError(response.status_code)
        time.sleep(2 ** attempt)


def inspect_url(session, url):
    data = gsc_post(session, "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
                    {"siteUrl": SITE, "inspectionUrl": url, "languageCode": "en-US"})
    index = data["inspectionResult"]["indexStatusResult"]
    status = {"PASS": "indexed", "FAIL": "not_indexed", "NEUTRAL": "not_indexed"}.get(index.get("verdict"), "unknown")
    return {"status": status, "coverage": index.get("coverageState"), "canonical": index.get("googleCanonical"),
            "last_crawl_at": index.get("lastCrawlTime"), "observed_at": utcnow().isoformat()}


ANALYTICS = f"https://www.googleapis.com/webmasters/v3/sites/{quote(SITE, safe='')}/searchAnalytics/query"


def search_buckets(session, urls, start, end, hourly):
    # 16 exact, property-owned URLs stay under Google's filter size and row limits.
    expression = "^(" + "|".join(re.escape(url) for url in urls) + ")$"
    dimension = "hour" if hourly else "date"
    data = gsc_post(session, ANALYTICS, {
        "startDate": start.isoformat(), "endDate": end.isoformat(), "type": "web",
        "dataState": "hourly_all" if hourly else "final", "dimensions": ["page", dimension],
        "rowLimit": 25000,
        "dimensionFilterGroups": [{"filters": [{"dimension": "page", "operator": "includingRegex",
                                                "expression": expression}]}],
    })
    first = {}
    for row in data.get("rows", []):
        url, bucket = row["keys"]
        if url in urls and row["impressions"] > 0:
            if hourly:
                bucket = timestamp(bucket).astimezone(timezone.utc).isoformat()
            first[url] = min(first.get(url, bucket), bucket)
    return first


def verify_access(session, url, now):
    # An access probe is not an aged checkpoint and does not enter any rate.
    inspect_url(session, url)
    day = (now.astimezone(PACIFIC) - timedelta(days=4)).date()
    search_buckets(session, {url}, day, day, hourly=False)
    print("Read-only URL Inspection and Search Analytics access verified.", flush=True)


SCHEMA = """
CREATE SCHEMA IF NOT EXISTS search_monitor_private;
REVOKE ALL ON SCHEMA search_monitor_private FROM PUBLIC;
CREATE TABLE IF NOT EXISTS search_monitor_private.leads (
    url text PRIMARY KEY, locale text NOT NULL, title text NOT NULL, published_at timestamptz NOT NULL,
    enrolled_at timestamptz NOT NULL, checkpoints jsonb NOT NULL DEFAULT '{}', analytics jsonb NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS search_monitor_private.cohorts (
    url text NOT NULL REFERENCES search_monitor_private.leads, cohort text NOT NULL,
    observed_at timestamptz NOT NULL, PRIMARY KEY(url, cohort)
);
CREATE TABLE IF NOT EXISTS search_monitor_private.latest_report (
    id integer PRIMARY KEY, generated_at timestamptz NOT NULL, report jsonb NOT NULL
);
ALTER TABLE search_monitor_private.leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_monitor_private.cohorts ENABLE ROW LEVEL SECURITY;
ALTER TABLE search_monitor_private.latest_report ENABLE ROW LEVEL SECURITY;
"""


def enroll(cursor, found, now):
    for url, record in found.items():
        cursor.execute("""INSERT INTO search_monitor_private.leads (url, locale, title, published_at, enrolled_at)
                          VALUES (%s,%s,%s,%s,%s) ON CONFLICT (url) DO NOTHING""",
                       (url, record["locale"], record["title"], record["published_at"], now))
        for cohort in record["cohorts"]:
            cursor.execute("""INSERT INTO search_monitor_private.cohorts (url, cohort, observed_at)
                              VALUES (%s,%s,%s) ON CONFLICT DO NOTHING""", (url, cohort, now))


def recent_records(cursor, now):
    cursor.execute("""SELECT l.*, ARRAY(SELECT c.cohort FROM search_monitor_private.cohorts c
                       WHERE c.url=l.url ORDER BY c.cohort) AS cohorts
                       FROM search_monitor_private.leads l WHERE published_at >= %s ORDER BY published_at DESC, url""",
                   (now - timedelta(days=35),))
    return list(cursor.fetchall())


def update_checks(conn, cursor, rows, session):
    failed = 0
    for row in rows:
        for hour in CHECKS:
            if checkpoint_state(row["published_at"], row["checkpoints"], hour, utcnow()) != "due":
                continue
            try:
                result = inspect_url(session, row["url"])
            except GSCError as error:
                if error.status in (401, 403):
                    raise
                failed += 1
                continue
            if timestamp(result["observed_at"]) >= row["published_at"] + timedelta(hours=hour) + GRACE:
                continue
            row["checkpoints"][str(hour)] = result
            cursor.execute("UPDATE search_monitor_private.leads SET checkpoints=%s WHERE url=%s",
                           (json.dumps(row["checkpoints"]), row["url"]))
            conn.commit()
    return failed


def update_analytics(conn, cursor, rows, session, now):
    # Revisit both new and delayed Search Analytics data throughout 35 days.
    failed = 0
    # Fetching only hourly buckets would lose delayed reporting and outage recovery.
    today = now.astimezone(PACIFIC).date()
    due = [row for row in rows if not row["analytics"].get("checked_at") or
           now - timestamp(row["analytics"]["checked_at"]) >= timedelta(hours=12)]
    for offset in range(0, len(due), 16):
        chunk = due[offset:offset + 16]
        urls = {row["url"] for row in chunk}
        earliest = min(row["published_at"].astimezone(PACIFIC).date() for row in chunk)
        try:
            dates = search_buckets(session, urls, earliest, today, hourly=False)
            hours = search_buckets(session, urls, max(earliest, today - timedelta(days=7)), today, hourly=True)
        except GSCError as error:
            if error.status in (401, 403):
                raise
            failed += 1
            continue
        for row in chunk:
            url, metrics = row["url"], row["analytics"]
            # Event time and observation time are different. Hourly buckets may still be revised.
            if url in dates:
                metrics["first_final_date_pt"] = dates[url]
            if url in hours:
                metrics["first_observed_hour_utc"] = min(hours[url], metrics.get("first_observed_hour_utc", hours[url]))
            if url in dates or url in hours:
                metrics.setdefault("first_seen_in_api_at", now.isoformat())
            metrics["checked_at"] = now.isoformat()
            cursor.execute("UPDATE search_monitor_private.leads SET analytics=%s WHERE url=%s",
                           (json.dumps(metrics), url))
        conn.commit()
    return failed


def report(rows, now, mode):
    rates = {}
    details = []
    for row in rows:
        states = {}
        for hour in CHECKS:
            state = checkpoint_state(row["published_at"], row["checkpoints"], hour, now)
            states[str(hour)] = state
            for locale in ("all", row["locale"]):
                counts = rates.setdefault(locale, {}).setdefault(str(hour), {})
                counts[state] = counts.get(state, 0) + 1
        details.append({**row, "checkpoint_states": states})
    for by_hour in rates.values():
        for counts in by_hour.values():
            denominator = counts.get("indexed", 0) + counts.get("not_indexed", 0)
            counts["measured"] = denominator
            counts["index_rate"] = counts.get("indexed", 0) / denominator if denominator else None
    return {"as_of_utc": now.isoformat(), "mode": mode, "scope": "Previous 35 days by site publication time",
            "url_count": len(rows), "cohort_memberships": sum(len(r["cohorts"]) for r in rows),
            "rates_by_locale": rates, "urls": details}


def store_report(conn, cursor, rows, output, mode):
    now = utcnow()
    data = report(rows, now, mode)
    encoded = json.dumps(data, ensure_ascii=False, default=lambda d: d.isoformat(), indent=2)
    cursor.execute("""INSERT INTO search_monitor_private.latest_report VALUES (1,%s,%s)
                      ON CONFLICT(id) DO UPDATE SET generated_at=excluded.generated_at,report=excluded.report""",
                   (now, encoded))
    conn.commit()
    output.mkdir(parents=True, exist_ok=True)
    (output / "report.json").write_text(encoded, encoding="utf-8")
    lines = ["# Search visibility", "", f"{data['as_of_utc']} · {data['mode']} · {len(rows)} canonical URLs",
             "", "|Locale|Checkpoint|Indexed|Measured|Missed|Rate|", "|---|---:|---:|---:|---:|---:|"]
    for locale, by_hour in data["rates_by_locale"].items():
        for hour, counts in by_hour.items():
            rate = counts["index_rate"]
            percent = f"{rate:.0%}" if rate is not None else "—"
            lines.append(f"|{locale}|{hour}h|{counts.get('indexed', 0)}|{counts['measured']}|{counts.get('missed', 0)}|{percent}|")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    import psycopg2
    from psycopg2.extras import RealDictCursor
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, default=Path("web/public"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/search-indexing"))
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--verify-access", action="store_true", help="Probe both read-only APIs once without recording a checkpoint")
    args = parser.parse_args()
    if args.discover_only and args.verify_access:
        parser.error("--verify-access requires Google measurement mode")
    now = utcnow()
    found = discover(args.public, now)
    conn = psycopg2.connect(os.environ["INBRIEF_SUPABASE_DB_URL"], connect_timeout=20)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            # Serialize even manual retries from a second runner, including schema initialization.
            cursor.execute("SELECT pg_advisory_lock(815746313)")
            cursor.execute(SCHEMA)
            enroll(cursor, found, now)
            conn.commit()
            rows = recent_records(cursor, now)
            mode = "discovery_only" if args.discover_only else "google_measured"
            try:
                if not args.discover_only:
                    session = make_session()
                    if args.verify_access:
                        if not rows:
                            raise ValueError("No published lead to inspect")
                        verify_access(session, rows[0]["url"], now)
                    failed = update_checks(conn, cursor, rows, session)
                    failed += update_analytics(conn, cursor, rows, session, now)
                    if failed:
                        raise RuntimeError("Retryable measurement errors")
            except Exception:
                conn.rollback()
                store_report(conn, cursor, recent_records(cursor, now), args.output_dir, "google_measurement_incomplete")
                raise
            store_report(conn, cursor, rows, args.output_dir, mode)
            print("Search visibility cohort and private report saved.", flush=True)
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # DB/auth exception messages may contain private connection or response details.
        message = str(error) if isinstance(error, GSCError) else type(error).__name__
        raise SystemExit(f"Search visibility monitor failed: {message}") from None
