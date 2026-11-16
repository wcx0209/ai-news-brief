#!/usr/bin/env python3
"""One cloud-only editorial revision of an existing draft artifact. No DB use."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))


def prepare_revision(packet, catalog, corrections):
    packet, catalog = deepcopy(packet), deepcopy(catalog)
    if packet['issue']['week_start'] != corrections['week_start']:
        raise ValueError('weekly_revision_period_mismatch')
    for row in corrections.get('supplemental_sources', []):
        targets = [event for section in ('main_events', 'early_signals') for event in packet[section]
                   if row['target_evidence_id'] in event['evidence_ids']]
        if len(targets) != 1:
            raise ValueError('weekly_revision_supplement_target_mismatch')
        target = targets[0]
        target['evidence_ids'].append(row['id'])
        target['evidence'].append({key: value for key, value in row.items()
                                   if key in ('id', 'source', 'source_type', 'published_at', 'domain', 'en', 'zh')})
        catalog.append(row)
    packet['source_scope'] += ' One linked official announcement was checked separately and added as a supplemental citation.'
    return packet, catalog


def require_supplemental_citations(draft, packet, corrections):
    for source in corrections.get('supplemental_sources', []):
        event = next(event for section in ('main_events', 'early_signals') for event in packet[section]
                     if source['target_evidence_id'] in event['evidence_ids'])
        for locale in ('zh', 'en'):
            revised = next(item for section in ('main_events', 'early_signals') for item in draft[locale][section]
                           if item['event_id'] == event['event_id'])
            if source['id'] not in revised['evidence_ids']:
                raise ValueError('weekly_revision_missing_required_official_citation')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', default='output/weekly-review')
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('All LLM revision calls must run in GitHub Actions')
    source, output = (ROOT / args.input).resolve(), (ROOT / args.output).resolve()
    if any(not value.is_relative_to(ROOT / 'output') for value in (source, output)):
        parser.error('Input/output must remain in output/, never web/public')
    output.mkdir(parents=True, exist_ok=True)

    def load(directory, name):
        return json.loads((directory / name).read_text(encoding='utf-8'))

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    metadata = {'status': 'failed', 'runtime': 'GitHub Actions', 'llm_runtime': 'cloud Gemini API',
                'database_reads': False, 'article_writes': False, 'website_publication': False,
                'emails_sent': False, 'calls': []}
    try:
        from weekly_generation import CloudGemini, SYSTEM_PROMPT, validate_draft
        from weekly_render import render_review, to_markdown
        previous = load(source, 'weekly-review.json')
        week = previous['issue']['week_start']
        # A real date, not an arbitrary path supplied by a model or user.
        if datetime.strptime(week, '%Y-%m-%d').date().isoformat() != week:
            raise ValueError('weekly_invalid_revision_week')
        corrections = load(ROOT / 'config/weekly-review-corrections', week + '.json')
        if os.environ.get('SOURCE_RUN_ID') != corrections['source_run_id']:
            raise ValueError('weekly_revision_source_run_mismatch')
        prior = load(source, 'generation-metadata.json')
        prior_count = prior.get('total_cloud_llm_calls_including_initial', len(prior.get('calls', [])))
        if prior_count >= 3 or previous.get('editorial_review', {}).get('revision_made'):
            raise ValueError('weekly_total_cloud_call_budget_exhausted')
        packet, catalog = prepare_revision(load(source, 'evidence-packet.json'), load(source, 'source-catalog.json'), corrections)
        model = CloudGemini()
        metadata.update(source_run_id=corrections['source_run_id'], model=model.model, calls=model.calls)
        draft = model(SYSTEM_PROMPT + '\nResolve the following preflight observations conservatively.\n',
                      {'evidence_packet': packet,
                       'previous_draft': {locale: previous[locale] for locale in ('zh', 'en')},
                       'preflight_corrections': corrections['instructions']}, 'preflight_editorial_revision')
        validate_draft(draft, packet, catalog=catalog)
        require_supplemental_citations(draft, packet, corrections)
        report = deepcopy(previous)
        report.update(draft)
        report['issue'].update(status='DRAFT', generated_at=datetime.now(timezone.utc).isoformat())
        for locale in ('zh', 'en'):
            report[locale]['follow_up'] = previous[locale]['follow_up']
        report['editorial_review'].update(revision_made=True, human_approved=False,
                                          independent_fact_check_complete=False,
                                          preflight_corrections=corrections,
                                          note='The earlier automated audit missed attribution/scope issues; this is a corrected draft, not human approval.')
        for name in ('selection-audit.json',):
            save(name, load(source, name))
        save('source-catalog.json', catalog)
        save('evidence-packet.json', packet)
        save('weekly-review.json', report)
        save('automated-editorial-review.json', report['editorial_review'])
        html = render_review(report, catalog)
        for locale in ('zh', 'en'):
            (output / (locale + '.html')).write_text(html[locale], encoding='utf-8')
            (output / (locale + '.md')).write_text(to_markdown(report, locale, catalog), encoding='utf-8')
        metadata['status'] = 'revised_draft_ready_for_human_review'
        metadata['current_usage'] = {name: sum(call.get('usage', {}).get(name) or 0 for call in model.calls)
                                     for name in ('input_tokens', 'output_tokens', 'total_tokens')}
        prior_usage = prior.get('cumulative_usage', prior.get('actual_usage', {}))
        metadata['cumulative_usage'] = {name: metadata['current_usage'][name] + prior_usage.get(name, 0)
                                        for name in metadata['current_usage']}
        metadata['total_cloud_llm_calls_including_initial'] = len(model.calls) + prior_count
        metadata['prior_failed_revision_requests'] = corrections.get('prior_failed_revision_requests', [])
        metadata['cloud_request_attempts_including_initial'] = metadata['total_cloud_llm_calls_including_initial'] + len(metadata['prior_failed_revision_requests'])
        metadata['usage_scope'] = 'Provider-returned usage only. The earlier 503 request returned no token usage.'
        print(json.dumps({key: metadata[key] for key in ('status', 'total_cloud_llm_calls_including_initial', 'cumulative_usage')}))
        return 0
    except Exception as exc:
        metadata['error_type'] = type(exc).__name__
        metadata['provider_status'] = getattr(exc, 'status_code', None)
        if isinstance(exc, ValueError) and str(exc).startswith('weekly_'):
            metadata['validation_error'] = str(exc)
        print(json.dumps({key: metadata.get(key) for key in ('status', 'error_type', 'provider_status', 'validation_error')}))
        return 1
    finally:
        save('generation-metadata.json', metadata)


if __name__ == '__main__':
    raise SystemExit(main())
