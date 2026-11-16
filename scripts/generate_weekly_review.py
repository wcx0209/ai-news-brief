#!/usr/bin/env python3
"""Cloud-only weekly REVIEW artifact. No collection, DB writes or publication."""

import argparse
from datetime import date, datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
SGT = ZoneInfo('Asia/Singapore')


def week_window(value, now=None):
    start_date = date.fromisoformat(value)
    if start_date.weekday() != 0:
        raise ValueError('week_start_must_be_a_monday')
    start = datetime.combine(start_date, time.min, SGT)
    end = start + timedelta(days=7)
    if end > (now or datetime.now(timezone.utc)):
        raise ValueError('weekly_review_requires_a_completed_week')
    return {'week_start': start_date.isoformat(), 'week_end': (start_date + timedelta(days=6)).isoformat(),
            'start': start.astimezone(timezone.utc).isoformat(), 'end': end.astimezone(timezone.utc).isoformat(),
            'end_exclusive': True, 'timezone': 'Asia/Singapore', 'status': 'DRAFT'}


def known_archive_urls():
    """Reuse actual published canonical URLs; never invent an archive address."""
    from source_images import normalize_source_url
    payload = json.loads((ROOT / 'web/public/data/articles.json').read_text(encoding='utf-8'))
    result = {}
    for item in payload.get('items', []):
        for locale, url in (item.get('canonical_urls') or {}).items():
            if locale not in {'en', 'zh'} or not normalize_source_url(url):
                continue
            parsed = urlsplit(url)
            if parsed.scheme == 'https' and parsed.netloc == 'polyemergence.com' and parsed.path.startswith(f'/{locale}/archive/'):
                result.setdefault(str(item['id']), {})[locale] = url
    return result


def load_cloud_archive(issue):
    """Select only source-dated articles, in a read-only PostgreSQL session."""
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        raise RuntimeError('weekly_database_is_cloud_only')
    db_url = os.environ.get('INBRIEF_SUPABASE_DB_URL')
    if not db_url:
        raise RuntimeError('weekly_missing_cloud_database_url')
    import psycopg2
    import psycopg2.extras
    with psycopg2.connect(db_url, options='-c default_transaction_read_only=on',
                          application_name='polyemergence-weekly-review', connect_timeout=20) as connection:
        connection.set_session(readonly=True, autocommit=False)
        with connection.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
            cursor.execute('''
                SELECT a.id, a.url, a.title, a.title_en, a.title_zh,
                       a.summary_en, a.summary_zh, a.long_summary_en, a.long_summary_zh,
                       a.importance_score, a.signal_score, a.structure_score,
                       a.consequence_score, a.confidence_score, a.momentum_score,
                       a.tags, a.category, a.source_published_at,
                       rs.name AS source_name, rs.category AS source_category
                FROM articles a LEFT JOIN rss_sources rs ON rs.id = a.rss_source_id
                WHERE a.source_published_at >= %s AND a.source_published_at < %s
                ORDER BY a.source_published_at DESC, a.id
                LIMIT 1001
            ''', (issue['start'], issue['end']))
            rows = [dict(row) for row in cursor.fetchall()]
    if len(rows) > 1000:
        raise ValueError('weekly_source_row_bound_exceeded')
    return rows


def prepare_records(rows, archives=None):
    from editorial_domains import domains, infer_domain
    from editorial_insights import evidence_type
    from relevance_filter import passes_source_ai_filter
    from source_images import normalize_source_url
    registry = {field['id']: field['label'] for field in domains()}
    records, rejected = [], []
    archives = archives or {}
    for row in rows:
        article_id = str(row['id'])
        title = row.get('title_en') or row.get('title') or row.get('title_zh') or ''
        source = row.get('source_name') or 'Unknown source'
        url = row.get('url') or ''
        if not normalize_source_url(url) or not passes_source_ai_filter(source, title):
            rejected.append({'id': article_id, 'reason': 'unsafe_url_or_source_relevance_gate'})
            continue
        tags = row.get('tags') or []
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except ValueError:
                tags = []
        tags = tags if isinstance(tags, list) else []
        published = row.get('source_published_at')
        published = published.isoformat() if isinstance(published, datetime) else published
        domain = infer_domain(row.get('category'), row.get('source_category'), ' '.join([title, source, *map(str, tags)]))
        record = {'id': article_id, 'url': url, 'source': source, 'source_published_at': published,
                  'published_at': published, 'date_basis': 'source_published',
                  'source_dates': {'source_published_at': published, 'verified': True},
                  'category': row.get('category'), 'source_category': row.get('source_category'),
                  'domain': domain, 'domain_labels': registry.get(domain, {'en': domain, 'zh': domain}),
                  'importance': int(row.get('importance_score') or 0),
                  'scores': {name: int(row.get(name + '_score') or 0)
                             for name in ('signal', 'structure', 'consequence', 'confidence', 'momentum')},
                  'tags': tags, 'archive_url_en': archives.get(article_id, {}).get('en'),
                  'archive_url_zh': archives.get(article_id, {}).get('zh')}
        for locale in ('en', 'zh'):
            record[locale] = {'title': row.get('title_' + locale) or row.get('title') or '',
                              'summary': row.get('summary_' + locale) or '',
                              'full': row.get('long_summary_' + locale) or ''}
        record['source_type'] = evidence_type(record)
        records.append(record)
    return records, rejected


def render_coverage(plan):
    from editorial_domains import domains
    counts = plan.get('domain_counts', {})
    return {'scope': 'loaded_archive_only', 'fields': [
        {'domain': field['id'], 'domain_labels': field['label'],
         'selected_count': counts.get(field['id'], {}).get('main', 0) + counts.get(field['id'], {}).get('signals', 0),
         'qualified_count': counts.get(field['id'], {}).get('event_groups', 0)} for field in domains()]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='output/weekly-review')
    args = parser.parse_args(argv)
    # Before database, model import, config secrets or any live operation.
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('All database reads and LLM calls must run in GitHub Actions, not on this computer')
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT / 'output'):
        parser.error('Drafts must stay outside web/public and inside output/')
    output.mkdir(parents=True, exist_ok=True)

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    generation = {'status': 'failed', 'runtime': 'GitHub Actions', 'llm_runtime': 'cloud Gemini API',
                  'database_read_only': True, 'new_collection': False, 'article_writes': False,
                  'website_publication': False, 'emails_sent': False, 'calls': []}
    try:
        issue = week_window(os.environ.get('WEEK_START', '2026-11-09'))
        from weekly_editorial import build_weekly_plan
        from weekly_generation import CloudGemini, generate_review
        from weekly_render import render_review, to_markdown
        rows = load_cloud_archive(issue)
        records, rejected = prepare_records(rows, known_archive_urls())
        plan = build_weekly_plan(records, start_utc=issue['start'], end_utc=issue['end'])
        save('selection-audit.json', plan)
        generation.update(week=issue, loaded_source_dated_articles=len(rows),
                          relevance_rejected=len(rejected), qualified_event_candidates=len(plan['candidates']),
                          selected_main=len(plan['shortlist']['main']), selected_signals=len(plan['shortlist']['signals']))
        if len(plan['shortlist']['main']) < 3:
            raise ValueError('not_enough_qualified_independent_events_for_weekly_review')
        model = CloudGemini()
        generation['model'] = model.model
        generation['calls'] = model.calls
        report, packet = generate_review(plan, issue, model)
        report['coverage'] = render_coverage(plan)
        selected_ids = {item for section in ('main_events', 'early_signals') for event in packet[section] for item in event['evidence_ids']}
        catalog = [record for record in records if record['id'] in selected_ids]
        save('source-catalog.json', catalog)
        save('evidence-packet.json', packet)
        save('weekly-review.json', report)
        save('automated-editorial-review.json', report['editorial_review'])
        html = render_review(report, catalog)
        for locale in ('zh', 'en'):
            (output / (locale + '.html')).write_text(html[locale], encoding='utf-8')
            (output / (locale + '.md')).write_text(to_markdown(report, locale, catalog), encoding='utf-8')
        generation['status'] = 'draft_ready_for_human_review'
        generation['actual_usage'] = {name: sum(call.get('usage', {}).get(name) or 0 for call in model.calls)
                                      for name in ('input_tokens', 'output_tokens', 'total_tokens')}
        print(json.dumps({key: generation[key] for key in ('status', 'loaded_source_dated_articles',
                                                          'selected_main', 'selected_signals', 'actual_usage')}))
        return 0
    except Exception as exc:
        # No provider exception strings: these may contain credentials or URLs.
        generation['error_type'] = type(exc).__name__
        generation['provider_status'] = getattr(exc, 'status_code', None)
        if isinstance(exc, ValueError) and str(exc).startswith(('weekly_', 'not_enough_')):
            generation['validation_error'] = str(exc)
        print(json.dumps({'status': 'failed', 'error_type': generation['error_type'],
                          'provider_status': generation['provider_status'],
                          'validation_error': generation.get('validation_error')}))
        return 1
    finally:
        save('generation-metadata.json', generation)
        summary = os.environ.get('GITHUB_STEP_SUMMARY')
        if summary:
            with open(summary, 'a', encoding='utf-8') as handle:
                handle.write('## Weekly review artifact\n\n'
                             f"Status: `{generation['status']}`. Cloud database read-only; "
                             'cloud Gemini only. No collection, article writes, website publishing, email or schedule changes. '
                             'The report text is kept in the review artifact, not this public job summary.\n')


if __name__ == '__main__':
    raise SystemExit(main())
