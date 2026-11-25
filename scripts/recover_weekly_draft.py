#!/usr/bin/env python3
"""Recover a single structurally incomplete bilingual draft on GitHub Actions."""
from datetime import datetime, timezone
import hashlib
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
from weekly_generation import (AUDIT_PROMPT, CloudGemini, _validate_new_draft, build_packet, generate_review,
                               validate_draft, validate_editorial_audit)
from weekly_publication import _require_original_for_high_impact, prepare_publication
from weekly_source_reads import enrich_selected_sources

REPO = 'wcx0209/ai-news-brief'
ARTIFACT = 'polyemergence-weekly-publication'
REPAIR_DIAGNOSTICS = 'polyemergence-weekly-repair-diagnostics'
CORRECTIONS = ROOT / 'config/weekly-review-corrections'
WORK = ROOT / 'output/weekly-draft-repair'
OUTPUT = WORK / 'review'


def check_run(run, source_id, final_only=False):
    workflow = 'weekly-draft-repair.yml' if final_only else 'weekly-publish.yml'
    if (str(run.get('id')) != source_id or run.get('head_branch') != 'main'
            or run.get('path') != '.github/workflows/' + workflow
            or run.get('event') not in (('workflow_dispatch',) if final_only else ('schedule', 'workflow_dispatch'))
            or run.get('head_repository', {}).get('full_name') != REPO
            or run.get('status') != 'completed' or run.get('conclusion') != 'failure'
            or run.get('run_attempt') != 1):
        raise ValueError('weekly_repair_invalid_source_run')


def retrieve(source_id, target, final_only=False):
    run = subprocess.run(['gh', 'api', f'repos/{REPO}/actions/runs/{source_id}'],
                         check=True, capture_output=True, timeout=30)
    check_run(json.loads(run.stdout), source_id, final_only)
    name = REPAIR_DIAGNOSTICS if final_only else ARTIFACT
    subprocess.run(['gh', 'run', 'download', source_id, '--repo', REPO, '--name', name,
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
    path = CORRECTIONS / (week + '.json')
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


def pinned_original(week, source_id):
    config = load_json(CORRECTIONS / (week + '.json'))
    original_id = config.get('source_run_id')
    if (config.get('week_start') != week or config.get('final_audit_source_run_id') != source_id
            or not isinstance(original_id, str) or not re.fullmatch(r'[1-9]\d{0,19}', original_id)):
        raise ValueError('weekly_final_audit_unrecognized_week_or_run')
    return original_id


def final_inputs(source, issue, source_id, copy_path):
    original_id = pinned_original(issue['week_start'], source_id)
    prior = load_json(source / 'generation-metadata.json')
    replies = load_json(source / 'model-response-texts.json')
    purposes = ['automated_editorial_check', 'bounded_revision']
    calls = prior.get('prior_run_calls', []) + prior.get('calls', [])
    if (prior.get('status') != 'failed' or prior.get('validation_error') != 'model_json_invalid_json'
            or prior.get('recovered_from_publication_run_id') != original_id or prior.get('week') != issue
            or prior.get('total_cloud_llm_calls_including_initial') != 3
            or [c.get('purpose') for c in calls] != ['draft', *purposes]
            or [r.get('purpose') for r in replies] != purposes
            or any(v.get('finish_reason') != 'stop' for v in [*calls, *replies])
            or (source / 'weekly-review.json').exists()):
        raise ValueError('weekly_final_audit_prior_attempt_mismatch')
    plan = load_json(source / 'selection-audit.json')
    catalog = load_json(source / 'source-catalog.json')
    packet = load_json(source / 'evidence-packet.json')
    if build_packet(plan, issue) != packet or sorted(row['id'] for row in catalog) != packet['allowed_evidence_ids']:
        raise ValueError('weekly_repair_saved_selection_mismatch')
    prior_audit = validate_editorial_audit(parse_json_response(replies[0]['text']), packet)
    draft = parse_json_response(copy_path.read_text(encoding='utf-8'))
    if set(draft) != {'zh', 'en'}:
        raise ValueError('weekly_final_audit_requires_locale_copy_only')
    _validate_new_draft(draft, packet)
    validate_draft(draft, packet, catalog)
    _require_original_for_high_impact(draft, catalog)
    for locale, note in (('zh', '本期未作与上期的逐项对照。'),
                         ('en', 'This edition does not include an item-by-item comparison with an earlier issue.')):
        if 'follow_up' in draft[locale]:
            raise ValueError('weekly_final_audit_requires_locale_copy_only')
        draft[locale]['follow_up'] = {'available': False, 'note': note, 'items': []}
    return plan, catalog, draft, {'calls': calls}, prior_audit, original_id


def final_audit(model, draft, packet, prior_audit, guidance):
    # One new provider call. The checked-in copy is attributed to an editorial
    # correction; neither the malformed response nor the old audit is reused
    # as the wording or review of the final copy.
    prompt = AUDIT_PROMPT + ('\nReview the entire current edited copy afresh. Treat prior findings as history, '
                           'and editorial guidance as questions to check against the packet, never as evidence. '
                           'For each issue distinguish a source contradiction from an explicitly stated limitation.')
    result = model(prompt, {'evidence_packet': packet, 'draft': draft, 'previous_review': prior_audit,
                            'editorial_guidance': guidance or []}, 'post_revision_editorial_check')
    validate_editorial_audit(result, packet)
    return {**draft, 'issue': {**packet['issue'], 'status': 'DRAFT', 'generated_at': datetime.now(timezone.utc).isoformat()},
            'editorial_review': {'automated_only': True, 'independently_verified': False, 'revision_made': True,
                                 'audit': prior_audit, 'post_revision_audit': result}}


def recover(source, output, issue, source_id, model_factory=CloudGemini, enrich=enrich_selected_sources,
            final_copy=None):
    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    final_only = final_copy is not None
    if final_only:
        plan, catalog, corrected, prior, prior_audit, original_run = final_inputs(source, issue, source_id, final_copy)
    else:
        plan, catalog, previous_draft, prior = restore(source, issue)
        original_run = source_id
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'status': 'failed', 'recovered_from_publication_run_id': original_run, 'week': issue, 'database_reads': False,
                'website_publication': False, 'calls': [], 'prior_run_calls': prior['calls']}
    model = None
    try:
        if final_only:
            metadata.update(recovered_from_repair_run_id=source_id, revision_source='repository_editorial_copy',
                            audited_copy_sha256=hashlib.sha256(json.dumps(corrected, ensure_ascii=False, sort_keys=True,
                                                                         separators=(',', ':')).encode()).hexdigest())
            audit = load_json(source / 'source-read-audit.json')
        else:
            audit = refresh_missing(plan, catalog, enrich)
        packet = build_packet(plan, issue)
        save('source-read-audit.json', audit)
        save('evidence-packet.json', packet)
        save('source-catalog.json', catalog)
        save('selection-audit.json', plan)
        guidance = editorial_guidance(issue['week_start'], original_run)
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

        if final_only:
            report = final_audit(model, corrected, packet, prior_audit, guidance)
        else:
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
    final_only = env.get('FINAL_AUDIT_ONLY') == 'true'
    copy_path = None
    if final_only:
        if env.get('GITHUB_RUN_ATTEMPT') != '1':
            raise ValueError('weekly_final_audit_rerun_requires_review')
        pinned_original(issue['week_start'], source_id)
        copy_path = CORRECTIONS / (issue['week_start'] + '-draft.json')
    retrieve(source_id, source, final_only)
    recover(source, OUTPUT, issue, source_id, final_copy=copy_path)
    print('Recovered draft passed the automatic publication checks.')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        # Never print an upstream body, exception, or model text to Actions.
        print(str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'(weekly_|model_json_)[a-z0-9_]+', str(exc))
              else 'Weekly draft recovery failed: ' + type(exc).__name__)
        sys.exit(1)
