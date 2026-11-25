#!/usr/bin/env python3
"""Cloud-only, bounded recovery of weekly model failures before any response.

This controller never reads the news database, calls a model, edits public
files, or retries a content-quality failure. It only dispatches the existing
publication workflow after inspecting its own fixed diagnostic artifact.
"""

from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from zoneinfo import ZoneInfo


ROOT = Path(__file__).absolute().parents[1]
REPOSITORY = 'wcx0209/ai-news-brief'
BRANCH = 'main'
WORKFLOW = 'weekly-publish.yml'
WORKFLOW_PATH = '.github/workflows/' + WORKFLOW
ARTIFACT = 'polyemergence-weekly-publication'
MAX_RUNS = 20
MAX_GENERATION_RUNS = 3  # One original run and at most two later recoveries.
MAX_AGE = timedelta(hours=72)
MAX_JSON_BYTES = 2_000_000
SGT = ZoneInfo('Asia/Singapore')
WORKFLOW_URL = f'https://github.com/{REPOSITORY}/actions/workflows/{WORKFLOW}'


class RecoveryError(RuntimeError):
    """Only fixed, secret-free codes are allowed in logs."""


def require_cloud(environ=None):
    environment = os.environ if environ is None else environ
    if environment.get('GITHUB_ACTIONS') != 'true':
        raise RecoveryError('weekly_recovery_is_cloud_only')
    if (environment.get('GITHUB_REPOSITORY') != REPOSITORY
            or environment.get('GITHUB_REF_NAME') != BRANCH
            or environment.get('GITHUB_EVENT_NAME') not in {'schedule', 'workflow_dispatch'}):
        raise RecoveryError('weekly_recovery_invalid_context')
    return environment


def current_issue(now):
    if not isinstance(now, datetime) or now.tzinfo is None:
        raise RecoveryError('weekly_recovery_aware_clock_required')
    today = now.astimezone(SGT).date()
    current_monday = today - timedelta(days=today.weekday())
    week = current_monday - timedelta(days=7)
    release_start = datetime.combine(current_monday, time.min, SGT).astimezone(timezone.utc)
    return week.isoformat(), release_start


def _timestamp(value):
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError):
        raise RecoveryError('weekly_recovery_invalid_run_metadata') from None


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def validate_runs(payload, release_start, now):
    """Accept only the fixed workflow's bounded run inventory for this cycle."""
    if (not isinstance(payload, dict) or not isinstance(payload.get('workflow_runs'), list)
            or len(payload['workflow_runs']) > MAX_RUNS):
        raise RecoveryError('weekly_recovery_invalid_run_inventory')
    selected = []
    seen = set()
    for run in payload['workflow_runs']:
        if not isinstance(run, dict) or not _integer(run.get('id')) or run['id'] in seen:
            raise RecoveryError('weekly_recovery_invalid_run_metadata')
        seen.add(run['id'])
        created = _timestamp(run.get('created_at'))
        if created > now:
            raise RecoveryError('weekly_recovery_future_run')
        if not release_start <= created < release_start + timedelta(days=7):
            continue
        if (run.get('path') != WORKFLOW_PATH or run.get('head_branch') != BRANCH
                or run.get('event') not in {'schedule', 'workflow_dispatch'}
                or not _integer(run.get('run_attempt'))):
            raise RecoveryError('weekly_recovery_invalid_run_metadata')
        selected.append({**run, '_created': created})
    return sorted(selected, key=lambda run: (run['_created'], run['id']), reverse=True)


def transient_metadata(metadata, week):
    """Accept only a failed initial draft request, never completed model text."""
    if not isinstance(metadata, dict) or not isinstance(metadata.get('week'), dict):
        return False
    calls = metadata.get('calls')
    issue = metadata['week']
    expected_end = (datetime.fromisoformat(week).date() + timedelta(days=6)).isoformat()
    return (
        metadata.get('status') == 'failed'
        and type(metadata.get('provider_status')) is int
        and metadata['provider_status'] in {500, 502, 503, 504}
        and not metadata.get('validation_error')
        and issue.get('week_start') == week
        and issue.get('week_end') == expected_end
        and issue.get('timezone') == 'Asia/Singapore'
        and isinstance(calls, list) and 1 <= len(calls) <= 4
        and all(isinstance(call, dict) and call.get('purpose') == 'draft'
                and 'usage' not in call and 'finish_reason' not in call
                for call in calls)
    )


class GitHubClient:
    """Use the official gh CLI; no shell, model keys, or database credentials."""

    def __init__(self, environment, root=ROOT, runner=None):
        self.environment = require_cloud(environment)
        self.root = root
        self.runner = runner or subprocess.run

    def _run(self, arguments):
        require_cloud(self.environment)
        try:
            result = self.runner(['gh', *arguments], cwd=self.root, env=self.environment,
                                 check=False, capture_output=True, text=True, timeout=60)
        except Exception:
            raise RecoveryError('weekly_recovery_github_command_failed') from None
        if result.returncode or len(result.stdout.encode('utf-8')) > MAX_JSON_BYTES:
            raise RecoveryError('weekly_recovery_github_command_failed')
        return result.stdout

    def list_runs(self):
        value = self._run(['api', '--method', 'GET',
                          f'repos/{REPOSITORY}/actions/workflows/{WORKFLOW}/runs?per_page={MAX_RUNS}&branch={BRANCH}'])
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            raise RecoveryError('weekly_recovery_invalid_run_inventory') from None

    def diagnostics(self, run):
        directory = self.root / 'output/weekly-recovery' / f"run-{run['id']}-attempt-{run['run_attempt']}"
        if directory.exists() or directory.is_symlink():
            raise RecoveryError('weekly_recovery_diagnostics_already_exist')
        directory.mkdir(parents=True)
        self._run(['run', 'download', str(run['id']), '--repo', REPOSITORY,
                   '--name', ARTIFACT, '--dir', str(directory)])
        # A release-ready artifact means publication/push failed after model
        # success. Do not generate another report to repair delivery.
        if (directory / 'release-metadata.json').exists():
            raise RecoveryError('weekly_recovery_has_completed_report')
        attempts = {path.name for path in directory.iterdir() if path.name.startswith('attempt-')}
        if attempts not in ({'attempt-1'}, {'attempt-1', 'attempt-2'}):
            raise RecoveryError('weekly_recovery_missing_diagnostics')
        metadata = []
        for number in (1, 2):
            attempt = directory / f'attempt-{number}'
            path = attempt / 'generation-metadata.json'
            if not attempt.exists():
                continue
            response_paths = (attempt / 'weekly-review.json', attempt / 'model-response-texts.json')
            if attempt.is_symlink() or any(path.exists() or path.is_symlink() for path in response_paths):
                raise RecoveryError('weekly_recovery_has_completed_report')
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
                raise RecoveryError('weekly_recovery_missing_diagnostics')
            try:
                metadata.append(json.loads(path.read_text(encoding='utf-8')))
            except (OSError, ValueError):
                raise RecoveryError('weekly_recovery_missing_diagnostics') from None
        if not metadata or len(metadata) > 2:
            raise RecoveryError('weekly_recovery_missing_diagnostics')
        return metadata

    def dispatch(self, week):
        # week is generated by current_issue, not supplied by an artifact.
        value = self._run(['workflow', 'run', WORKFLOW, '--repo', REPOSITORY,
                          '--ref', BRANCH, '--field', 'week_start=' + week])
        match = re.search(r'https://github\.com/wcx0209/ai-news-brief/actions/runs/[0-9]+\b', value)
        return match.group(0) if match else WORKFLOW_URL


def run_recovery(*, environ=None, now=None, root=ROOT, client_factory=GitHubClient):
    environment = require_cloud(environ)  # Before clients, reads or output I/O.
    now = now or datetime.now(timezone.utc)
    week, release_start = current_issue(now)
    result = {'status': 'skipped', 'week_start': week, 'reason': 'already_published'}
    existing = root / 'web/public/data/weekly' / (week + '.json')
    if existing.exists() or existing.is_symlink():
        return result
    client = client_factory(environment, root)
    runs = validate_runs(client.list_runs(), release_start, now)
    if not runs:
        return {**result, 'reason': 'no_current_week_attempt'}
    if any(run.get('status') != 'completed' for run in runs):
        return {**result, 'reason': 'publication_in_progress'}
    if any(run.get('conclusion') == 'success' for run in runs):
        return {**result, 'reason': 'publication_already_succeeded'}
    if any(run.get('conclusion') != 'failure' for run in runs):
        return {**result, 'reason': 'prior_run_not_retryable'}
    # A GitHub rerun may expose only its newest artifact. Earlier attempts could
    # have completed model text, so the current diagnostic cannot authorize a
    # fresh generation automatically even if it records only a later 503.
    if any(run['run_attempt'] != 1 for run in runs):
        return {**result, 'reason': 'prior_github_rerun_requires_manual_review'}
    generation_runs = sum(run['run_attempt'] for run in runs)
    if generation_runs >= MAX_GENERATION_RUNS:
        return {**result, 'reason': 'weekly_recovery_budget_exhausted', 'generation_runs': generation_runs}
    if now - runs[0]['_created'] > MAX_AGE:
        return {**result, 'reason': 'latest_attempt_expired'}
    # All current-cycle failures are inspected, not merely the newest one:
    # a later transport outage cannot hide an earlier quality failure.
    for run in runs:
        try:
            metadata = client.diagnostics(run)
        except RecoveryError as error:
            return {**result, 'reason': str(error)}
        if (not isinstance(metadata, list) or not metadata
                or any(not transient_metadata(item, week) for item in metadata)):
            return {**result, 'reason': 'prior_failure_has_response_or_invalid_diagnostics'}
    # Recheck before dispatch in case another publisher completed during reads.
    if existing.exists() or existing.is_symlink():
        return result
    run_url = client.dispatch(week)
    return {**result, 'status': 'dispatched', 'reason': 'transient_before_any_model_response',
            'generation_runs_before_dispatch': generation_runs,
            'source_run_url': f"https://github.com/{REPOSITORY}/actions/runs/{runs[0]['id']}",
            'run_url': run_url}


def main():
    try:
        result = run_recovery()
    except RecoveryError as error:
        print(json.dumps({'status': 'failed', 'error': str(error)}))
        return 1
    print(json.dumps(result))
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a', encoding='utf-8') as stream:
            stream.write(f"Weekly {result['week_start']}: **{result['status']}** — {result['reason']}.\n\n")
            if result.get('run_url'):
                stream.write(f"[Publication run / workflow]({result['run_url']})\n")
            if result.get('source_run_url'):
                stream.write(f"[Prior transient failure]({result['source_run_url']})\n")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
