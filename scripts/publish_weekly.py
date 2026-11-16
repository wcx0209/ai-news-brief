#!/usr/bin/env python3
"""Cloud-only weekly release: validate a finished draft, then export public files.

This does not collect news or write the article database. Existing editions are
immutable. All live database/model work is delegated to the cloud-only drafter.
"""

import argparse
from copy import deepcopy
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'scripts'))
from weekly_publication import latest_completed_week, prepare_publication


def week_id(value, now=None):
    value = value or latest_completed_week(now)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValueError('weekly_invalid_release_week')
    day = date.fromisoformat(value)
    if day.weekday() != 0 or value > latest_completed_week(now):
        raise ValueError('weekly_release_requires_completed_monday_week')
    return value


def load_json(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2_000_000:
        raise ValueError('weekly_invalid_artifact_file')
    return json.loads(path.read_text(encoding='utf-8'))


def release_copy(report, source_run_id):
    """Explicit scope/attribution edits to the reviewed first issue, not new facts."""
    result = deepcopy(report)
    changes = []
    # Remove review-workflow boilerplate from the authorized publication copy.
    for locale, sentence, replacement in (
        ('en', 'This digest is a human-review draft, not a verified industry verdict.',
         'This selection is not an independently verified industry verdict.'),
    ):
        lead = result[locale]['lead']['text']
        if sentence in lead:
            result[locale]['lead']['text'] = lead.replace(sentence, replacement)
            changes.append('release_label_' + locale)
    if source_run_id != '43792710068' or result['issue']['week_start'] != '2026-11-09':
        return result, changes

    def replace(mapping, key, old, new):
        if old not in mapping[key]:
            raise ValueError('weekly_reviewed_copy_mismatch')
        mapping[key] = mapping[key].replace(old, new)

    replace(result['en']['lead'], 'text',
            'IBM reported reaching quantum advantage with the Nighthawk r2 processor',
            'IBM reported quantum-advantage progress and separately introduced the Nighthawk r2 processor')
    events = {locale: {event['event_id']: event for event in result[locale]['main_events']}
              for locale in ('en', 'zh')}
    signal = 'weekly-0b1ecfbfdf707b37'
    replace(events['en'][signal], 'why_it_matters',
            'significantly reducing manual audit time',
            'with DeepMind reporting a shorter verification process')
    replace(events['zh'][signal], 'why_it_matters',
            '大幅缩短了形式化验证所需的人工时间', '据 DeepMind 介绍，缩短了验证流程所需时间')
    bci = 'weekly-5d8ca9d00f0f44dd'
    replace(events['en'][bci], 'what_changed', 'A Nature Brain-Machine Interfaces study',
            "A study hosted on Nature's website")
    events['zh'][bci]['what_changed'] = (
        'Nature 网站刊载的一项研究显示，一名渐冻症患者通过植入式皮层电图脑机接口，'
        '在 18 次实验中，以 97.1% 的中位解码准确率用默念语音控制智能家居。')
    for event in events['zh'].values():
        for key in ('what_changed', 'why_it_matters', 'uncertainty'):
            event[key] = event[key].replace('该供料', '现有材料')
    for locale, note in (
        ('en', 'This is the first published weekly edition; no earlier issue is available for comparison.'),
        ('zh', '这是首期正式周报，尚无上期周报可供回看。'),
    ):
        result[locale]['follow_up'] = {'available': False, 'note': note, 'items': []}
    changes.extend(['separate_ibm_processor_from_advantage_claim', 'attribute_verification_time',
                    'bci_one_participant_18_sessions_not_journal_title', 'first_published_issue_copy'])
    return result, changes


def transient_before_response(metadata):
    # Never repeat a completed response or quality failure to hunt for a pass.
    calls = metadata.get('calls') or []
    return (metadata.get('status') == 'failed' and bool(calls)
            and metadata.get('provider_status') in {500, 502, 503, 504}
            and all('usage' not in call and 'finish_reason' not in call for call in calls))


def generate_cloud(week, work):
    env = {**os.environ, 'WEEK_START': week}
    for attempt in (1, 2):
        target = work / ('attempt-' + str(attempt))
        run = subprocess.run([sys.executable, str(ROOT / 'scripts/generate_weekly_review.py'),
                              '--output', str(target.relative_to(ROOT))], cwd=ROOT, env=env, check=False)
        if run.returncode == 0:
            return target
        metadata = load_json(target / 'generation-metadata.json')
        if attempt == 2 or not transient_before_response(metadata):
            raise RuntimeError('weekly_cloud_generation_failed_preserving_previous_issue')
        time.sleep(25)
    raise RuntimeError('weekly_generation_attempt_bound')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--input')
    parser.add_argument('--generate', action='store_true')
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Weekly publication, database reads and LLM calls run in GitHub Actions only')
    week = week_id(os.environ.get('WEEK_START', ''))
    public = ROOT / 'web/public'
    existing = public / 'data/weekly' / (week + '.json')
    source_run = os.environ.get('SOURCE_RUN_ID', '')
    if source_run and (not re.fullmatch(r'[0-9]{1,20}', source_run)
                       or os.environ.get('GITHUB_EVENT_NAME') != 'workflow_dispatch'):
        raise ValueError('weekly_source_artifact_requires_manual_dispatch')
    if args.preflight:
        output = os.environ.get('GITHUB_OUTPUT')
        if output:
            with open(output, 'a', encoding='utf-8') as handle:
                handle.write(f'week_start={week}\nexists={str(existing.is_file()).lower()}\n')
        print(json.dumps({'week_start': week, 'already_published': existing.is_file()}))
        return 0
    if existing.is_file():
        # An existing issue ends the release before draft retrieval, DB/model
        # work, rendering or writing any public file.
        print('Weekly edition already published; skipped generation and publication.')
        return 0
    from export_weekly import export_weeklies, load_editions
    work = ROOT / 'output/weekly-publication'
    work.mkdir(parents=True, exist_ok=True)
    if args.input:
        source = (ROOT / args.input).resolve()
        if not source.is_relative_to(ROOT / 'output') or not source_run:
            raise ValueError('weekly_manual_artifact_must_be_inside_output')
    elif args.generate and not source_run:
        source = generate_cloud(week, work)
    else:
        parser.error('Choose cloud generation or a manually dispatched review artifact')
    report = load_json(source / 'weekly-review.json')
    if report.get('issue', {}).get('week_start') != week:
        raise ValueError('weekly_requested_week_mismatch')
    packet = load_json(source / 'evidence-packet.json')
    catalog = load_json(source / 'source-catalog.json')
    metadata = load_json(source / 'generation-metadata.json')
    report, copyedits = release_copy(report, source_run)
    now = datetime.now(timezone.utc)
    payload = prepare_publication(report, packet, catalog, published_at=now,
                                  user_authorized=bool(source_run), generation_metadata=metadata, now=now)
    # Exporter renders and checks every page before replacing any public file.
    export_weeklies(public, [*load_editions(public), payload])
    audit = {'status': 'publication_ready', 'week_start': week,
             'published_at': payload['published_at'], 'source_run_id': source_run or None,
             'copyedits': copyedits, 'database_writes': False,
             'human_reviewed': False, 'independently_verified': False}
    (work / 'release-metadata.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'publication_ready', 'week_start': week}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
