#!/usr/bin/env python3
"""Add a cloud-generated plain-language opening to an existing review artifact."""

import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'src'))
COPIED = ('selection-audit.json', 'source-catalog.json', 'evidence-packet.json', 'automated-editorial-review.json')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', default='output/weekly-review')
    args = parser.parse_args(argv)
    if os.environ.get('GITHUB_ACTIONS') != 'true':
        parser.error('Weekly synthesis and LLM calls run in GitHub Actions only')
    if not os.environ.get('SOURCE_RUN_ID', '').isdigit():
        parser.error('An existing numeric cloud draft run ID is required')
    source, output = (ROOT / args.input).resolve(), (ROOT / args.output).resolve()
    if any(not path.is_relative_to(ROOT / 'output') for path in (source, output)) or source == output:
        parser.error('Use different input/output directories inside output/, never web/public')
    output.mkdir(parents=True, exist_ok=True)

    def load(directory, name):
        return json.loads((directory / name).read_text(encoding='utf-8'))

    def save(name, value):
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

    metadata = {'status': 'failed', 'runtime': 'GitHub Actions', 'llm_runtime': 'cloud Gemini API',
                'operation': 'add_plain_language_synthesis', 'database_reads': False, 'article_writes': False,
                'new_collection': False, 'website_publication': False, 'emails_sent': False, 'calls': []}
    try:
        from weekly_generation import CloudGemini
        from weekly_synthesis import generate_synthesis
        from weekly_render import render_review, to_markdown
        previous = load(source, 'weekly-review.json')
        packet = load(source, 'evidence-packet.json')
        catalog = load(source, 'source-catalog.json')
        prior = load(source, 'generation-metadata.json')
        week = previous['issue']['week_start']
        if date.fromisoformat(week).isoformat() != week or previous['issue'].get('status') != 'DRAFT':
            raise ValueError('weekly_synthesis_invalid_draft_period')
        path = ROOT / 'config/weekly-synthesis-guidance' / (week + '.json')
        guidance = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        model = CloudGemini()
        metadata.update(source_run_id=os.environ.get('SOURCE_RUN_ID'), model=model.model, calls=model.calls)
        # One request only for this new user-authorized addition. No redrafting
        # or automatic repair calls, and no live database/source access.
        def recorded_call(system, payload, purpose):
            result = model(system, payload, purpose)
            save('synthesis-raw-response.json', result)
            return result
        report, synthesis = generate_synthesis(previous, packet, catalog, recorded_call, guidance)
        if report['issue'] != previous['issue'] or report.get('coverage') != previous.get('coverage'):
            raise ValueError('weekly_synthesis_mutated_frozen_report')
        for locale in ('zh', 'en'):
            if {key: value for key, value in report[locale].items() if key != 'synthesis'} != {key: value for key, value in previous[locale].items() if key != 'synthesis'}:
                raise ValueError('weekly_synthesis_mutated_existing_sections')
        for name in COPIED:
            save(name, load(source, name))
        save('weekly-review.json', report)
        save('plain-language-synthesis.json', synthesis)
        html = render_review(report, catalog)
        for locale in ('zh', 'en'):
            (output / (locale + '.html')).write_text(html[locale], encoding='utf-8')
            (output / (locale + '.md')).write_text(to_markdown(report, locale, catalog), encoding='utf-8')
        metadata['status'] = 'synthesis_draft_ready_for_human_review'
        metadata['generated_at'] = datetime.now(timezone.utc).isoformat()
        metadata['base_report_generated_at'] = previous['issue'].get('generated_at')
        metadata['existing_report_unchanged'] = True
        metadata['current_usage'] = {name: sum(call.get('usage', {}).get(name) or 0 for call in model.calls)
                                     for name in ('input_tokens', 'output_tokens', 'total_tokens')}
        old_usage = prior.get('cumulative_usage', prior.get('actual_usage', {}))
        metadata['cumulative_usage'] = {name: metadata['current_usage'][name] + old_usage.get(name, 0)
                                        for name in metadata['current_usage']}
        old_calls = prior.get('total_cloud_llm_calls_including_initial', len(prior.get('calls', [])))
        metadata['total_cloud_llm_calls_including_initial'] = old_calls + len(model.calls)
        metadata['prior_failed_revision_requests'] = prior.get('prior_failed_revision_requests', [])
        old_attempts = prior.get('cloud_request_attempts_including_initial', old_calls)
        metadata['cloud_request_attempts_including_initial'] = old_attempts + len(model.calls)
        metadata['usage_scope'] = 'Provider-returned usage; previous failed requests may not return token usage.'
        print(json.dumps({key: metadata[key] for key in ('status', 'existing_report_unchanged', 'current_usage')}))
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
