#!/usr/bin/env python3
"""Recover a single structurally incomplete bilingual draft on GitHub Actions."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))

from generate_weekly_review import render_coverage, week_window
from model_json import parse_json_response
from publish_weekly import load_json
from weekly_generation import CloudGemini, build_packet, generate_review, validate_draft
from weekly_publication import prepare_publication
from weekly_source_reads import enrich_selected_sources

REPO = 'wcx0209/ai-news-brief'
ARTIFACT = 'polyemergence-weekly-publication'
WORK = ROOT / 'output/weekly-draft-repair'
OUTPUT = WORK / 'review'


def check_run(run, source_id):
    if (str(run.get('id')) != source_id or run.get('head_branch') != 'main'
            or run.get('path') != '.github/workflows/weekly-publish.yml'
            or run.get('event') not in ('schedule', 'workflow_dispatch')
            or run.get('head_repository', {}).get('full_name') != REPO
            or run.get('status') != 'completed' or run.get('conclusion') != 'failure'
            or run.get('run_attempt') != 1):
        raise ValueError('weekly_repair_invalid_source_run')


def retrieve(source_id, target):
    run = subprocess.run(['gh', 'api', f'repos/{REPO}/actions/runs/{source_id}'],
                         check=True, capture_output=True, timeout=30)
    check_run(json.loads(run.stdout), source_id)
    subprocess.run(['gh', 'run', 'download', source_id, '--repo', REPO, '--name', ARTIFACT,
                    '--dir', str(target)], check=True, timeout=90)


def restore(source, issue):
    if {p.name for p in source.iterdir()} != {'attempt-1'}:
        raise ValueError('weekly_repair_requires_single_failed_attempt')
    attempt = source / 'attempt-1'
    if attempt.is_symlink() or not attempt.is_dir() or (attempt / 'weekly-review.json').is_file():
        raise ValueError('weekly_repair_invalid_source_artifact')
    prior = load_json(attempt / 'generation-metadata.json')
    replies = load_json(attempt / 'model-response-texts.json')
    calls = prior.get('calls')
    if (prior.get('week') != issue or prior.get('status') != 'failed'
            or prior.get('validation_error') != 'weekly_event_plan_mismatch'
            or not isinstance(calls, list) or len(calls) != 1 or calls[0].get('purpose') != 'draft'
            or calls[0].get('finish_reason') != 'stop'
            or not isinstance(replies, list) or len(replies) != 1 or replies[0].get('purpose') != 'draft'
            or replies[0].get('finish_reason') != 'stop'):
        raise ValueError('weekly_repair_not_a_single_incomplete_draft')
    draft = parse_json_response(replies[0]['text'])
    plan = load_json(attempt / 'selection-audit.json')
    packet = load_json(attempt / 'evidence-packet.json')
    catalog = load_json(attempt / 'source-catalog.json')
    by_id = {source['id']: source for source in catalog}
    if len(by_id) != len(catalog) or sorted(by_id) != packet.get('allowed_evidence_ids'):
        raise ValueError('weekly_repair_catalog_mismatch')
    apply_reads(plan, by_id)
    if (build_packet(plan, issue) != packet or not 3 <= len(plan['shortlist']['main']) <= 8
            or len(plan['shortlist']['signals']) > 2):
        raise ValueError('weekly_repair_saved_selection_mismatch')
    try:
        validate_draft(draft, packet)
    except ValueError as exc:
        if str(exc) != 'weekly_event_plan_mismatch':
            raise
    else:
        raise ValueError('weekly_repair_prior_draft_already_complete')
    return plan, catalog, draft, prior


def event_rows(event):
    return [event['representative'], *event.get('support', [])]


def apply_reads(plan, by_id):
    for events in plan['shortlist'].values():
        for event in events:
            for row in event_rows(event):
                source = by_id.get(row['id'])
                if source:
                    if source['url'] != row['url']:
                        raise ValueError('weekly_repair_source_url_mismatch')
                    if 'original_read' in source:
                        row['original_read'] = source['original_read']


def refresh_missing(plan, catalog, enrich=enrich_selected_sources):
    missing = {key: [event for event in events if not any(
        row.get('original_read', {}).get('status') == 'retrieved'
        for row in (event.get('support') or [event['representative']])[:3])]
               for key, events in plan['shortlist'].items()}
    # Existing successful reads are immutable. Only the original adapter may
    # attempt missing material, using the same URL budget and stop conditions.
    refreshed, audit = enrich({'shortlist': missing})
    selected = {row['id']: row for row in catalog}
    for events in refreshed['shortlist'].values():
        for event in events:
            for row in event_rows(event):
                source = selected.get(row['id'])
                if (source and 'original_read' in row
                        and source.get('original_read', {}).get('status') != 'retrieved'):
                    if row['url'] != source['url']:
                        raise ValueError('weekly_repair_source_url_mismatch')
                    source['original_read'] = row['original_read']
    apply_reads(plan, selected)
    return audit


def editorial_guidance(week, source_id):
    path = ROOT / 'config/weekly-review-corrections' / (week + '.json')
    if not path.exists():
        return None
    config = load_json(path)
    if config.get('week_start') != week or config.get('source_run_id') != source_id:
        return None
    instructions = config.get('instructions')
    if (not isinstance(instructions, list) or not 1 <= len(instructions) <= 30
            or any(not isinstance(line, str) or not line.strip() or len(line) > 2000 for line in instructions)):
        raise ValueError('weekly_repair_invalid_editorial_guidance')
    return instructions


def recover(source, output, issue, source_id, model_factory=CloudGemini, enrich=enrich_selected_sources):
    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    plan, catalog, previous_draft, prior = restore(source, issue)
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'status': 'failed', 'recovered_from_publication_run_id': source_id, 'week': issue, 'database_reads': False,
                'website_publication': False, 'calls': [], 'prior_run_calls': prior['calls']}
    model = None
    try:
        audit = refresh_missing(plan, catalog, enrich)
        packet = build_packet(plan, issue)
        save('source-read-audit.json', audit)
        save('evidence-packet.json', packet)
        save('source-catalog.json', catalog)
        save('selection-audit.json', plan)
        guidance = editorial_guidance(issue['week_start'], source_id)
        model = model_factory()
        metadata.update(model=model.model, calls=model.calls)
        used_saved_draft = False

        def resume(system, payload, purpose):
            nonlocal used_saved_draft
            if not used_saved_draft and purpose == 'draft':
                used_saved_draft = True
                return previous_draft
            if not used_saved_draft or purpose == 'draft' or len(model.calls) + len(prior['calls']) >= 4:
                raise ValueError('weekly_repair_lifetime_call_bound')
            if guidance:
                payload = {**payload, 'editorial_guidance': guidance}
                system += '\nCheck the supplied editorial guidance against the evidence and correct supported concerns. Never treat guidance as source evidence.\n'
            return model(system, payload, purpose)

        report, _ = generate_review(plan, issue, resume)
        report['coverage'] = render_coverage(plan)
        review = report['editorial_review']
        if not review.get('revision_made') or not review.get('post_revision_audit'):
            raise ValueError('weekly_repair_new_revision_and_audit_required')
        now = datetime.now(timezone.utc)
        # Validate exactly as for an automatic release before making the
        # standard reviewed artifact available to the publication workflow.
        status = 'revised_draft_ready_for_human_review'
        prepare_publication(report, packet, catalog, published_at=now, now=now, user_authorized=False,
                            generation_metadata={**metadata, 'status': status})
        from weekly_render import render_review, to_markdown
        pages = render_review(report, catalog)
        for locale in ('zh', 'en'):
            (output / (locale + '.html')).write_text(pages[locale], encoding='utf-8')
            (output / (locale + '.md')).write_text(to_markdown(report, locale, catalog), encoding='utf-8')
        save('weekly-review.json', report)
        save('automated-editorial-review.json', review)
        metadata['status'] = status
    except Exception as exc:
        metadata['error_type'] = type(exc).__name__
        metadata['provider_status'] = getattr(exc, 'status_code', None)
        if isinstance(exc, ValueError) and re.fullmatch(r'(?:weekly_|model_json_)[a-z0-9_]+', str(exc)):
            metadata['validation_error'] = str(exc)
        raise
    finally:
        metadata['total_cloud_llm_calls_including_initial'] = len(metadata['calls']) + len(prior['calls'])
        if model and model.raw_responses:
            save('model-response-texts.json', model.raw_responses)
        save('generation-metadata.json', metadata)


def main():
    env = os.environ
    if (env.get('GITHUB_ACTIONS') != 'true' or env.get('GITHUB_REPOSITORY') != REPO
            or env.get('GITHUB_REF') != 'refs/heads/main' or env.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('weekly_repair_cloud_main_dispatch_only')
    source_id = env.get('SOURCE_RUN_ID', '')
    if not re.fullmatch(r'[1-9]\d{0,19}', source_id):
        raise ValueError('weekly_repair_invalid_source_id')
    issue = week_window(env['WEEK_START'])
    existing = ROOT / 'web/public/data/weekly' / (issue['week_start'] + '.json')
    if existing.exists() or existing.is_symlink():
        print('This edition has already been published.')
        return
    source = WORK / 'input'
    source.mkdir(parents=True, exist_ok=False)
    retrieve(source_id, source)
    recover(source, OUTPUT, issue, source_id)
    print('Recovered draft passed the automatic publication checks.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never print an upstream body, exception, or model text to Actions.
        print(str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'(weekly_|model_json_)[a-z0-9_]+', str(exc))
              else 'Weekly draft recovery failed: ' + type(exc).__name__)
        sys.exit(1)
