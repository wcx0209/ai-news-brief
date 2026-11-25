"""Recovery tests use injected gh clients/runners; no live CLI or model calls."""

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).absolute().parents[1]
SPEC = importlib.util.spec_from_file_location('recover_weekly_fixture', ROOT / 'scripts/recover_weekly.py')
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)

CLOUD = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': recovery.REPOSITORY,
         'GITHUB_REF_NAME': 'main', 'GITHUB_EVENT_NAME': 'schedule'}
NOW = datetime(2026, 11, 25, 12, tzinfo=timezone.utc)


def run(identifier=100, created='2026-11-23T21:45:49Z', **changes):
    return {'id': identifier, 'created_at': created, 'path': recovery.WORKFLOW_PATH,
            'head_branch': 'main', 'event': 'schedule', 'run_attempt': 1,
            'status': 'completed', 'conclusion': 'failure', **changes}


def diagnostic(**changes):
    return {'status': 'failed', 'provider_status': 503,
            'week': {'week_start': '2026-11-16', 'week_end': '2026-11-22', 'timezone': 'Asia/Singapore'},
            'calls': [{'purpose': 'draft'}], **changes}


class FakeClient:
    def __init__(self, runs=None, diagnostics=None):
        self.runs = [run()] if runs is None else runs
        self.values = {100: [diagnostic(), diagnostic()]} if diagnostics is None else diagnostics
        self.calls = []

    def list_runs(self):
        self.calls.append(('list',))
        return {'workflow_runs': deepcopy(self.runs)}

    def diagnostics(self, value):
        self.calls.append(('diagnostics', value['id']))
        result = self.values[value['id']]
        if isinstance(result, Exception):
            raise result
        return deepcopy(result)

    def dispatch(self, week):
        self.calls.append(('dispatch', week))
        return 'https://github.com/wcx0209/ai-news-brief/actions/runs/200'


class RecoveryTests(unittest.TestCase):
    def recover(self, client=None, *, root=None, now=NOW, environ=None):
        client = client or FakeClient()
        factory = Mock(return_value=client)
        value = recovery.run_recovery(environ=CLOUD if environ is None else environ,
                                      now=now, root=root or self.root, client_factory=factory)
        return value, client, factory

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_refuses_local_or_unexpected_repo_branch_event_before_clients_and_files(self):
        for change in ({'GITHUB_ACTIONS': 'false'}, {'GITHUB_REPOSITORY': 'attacker/fork'},
                       {'GITHUB_REF_NAME': 'main; echo secret'}, {'GITHUB_EVENT_NAME': 'pull_request'}):
            factory = Mock()
            with self.subTest(change=change), patch.object(Path, 'exists') as exists:
                with self.assertRaises(recovery.RecoveryError):
                    recovery.run_recovery(environ={**CLOUD, **change}, now=NOW,
                                          root=self.root, client_factory=factory)
                factory.assert_not_called()
                exists.assert_not_called()

    def test_already_published_skips_before_client_download_or_output_directory(self):
        path = self.root / 'web/public/data/weekly/2026-11-16.json'
        path.parent.mkdir(parents=True)
        path.write_text('{}')
        result, client, factory = self.recover()
        self.assertEqual(result['reason'], 'already_published')
        factory.assert_not_called()
        self.assertFalse(client.calls)
        self.assertFalse((self.root / 'output').exists())

    def test_completed_week_uses_singapore_calendar(self):
        sunday_utc = datetime(2026, 11, 22, 16, tzinfo=timezone.utc)
        week, start = recovery.current_issue(sunday_utc)
        self.assertEqual(week, '2026-11-16')
        self.assertEqual(start.isoformat(), '2026-11-22T16:00:00+00:00')
        with self.assertRaises(recovery.RecoveryError):
            recovery.current_issue(datetime(2026, 11, 25))

    def test_two_failed_503_draft_attempts_allow_one_dispatch(self):
        result, client, _ = self.recover()
        self.assertEqual(result['status'], 'dispatched')
        self.assertEqual(result['week_start'], '2026-11-16')
        self.assertEqual(result['generation_runs_before_dispatch'], 1)
        self.assertEqual(client.calls, [('list',), ('diagnostics', 100), ('dispatch', '2026-11-16')])

    def test_second_recovery_allowed_but_third_generation_run_exhausts_budget(self):
        values = {100: [diagnostic()], 101: [diagnostic()]}
        client = FakeClient([run(101, '2026-11-24T21:00:00Z'), run()], values)
        result, _, _ = self.recover(client)
        self.assertEqual(result['status'], 'dispatched')
        self.assertEqual(result['generation_runs_before_dispatch'], 2)
        blocked = FakeClient([run(102, '2026-11-25T10:00:00Z'), *client.runs], values)
        result, _, _ = self.recover(blocked)
        self.assertEqual(result['reason'], 'weekly_recovery_budget_exhausted')
        self.assertEqual(blocked.calls, [('list',)])

    def test_github_rerun_cannot_hide_prior_attempt_behind_latest_503_artifact(self):
        for attempt in (2, 3):
            client = FakeClient([run(run_attempt=attempt)], {100: [diagnostic()]})
            result, _, _ = self.recover(client)
            self.assertEqual(result['reason'], 'prior_github_rerun_requires_manual_review')
            self.assertEqual(client.calls, [('list',)])

    def test_any_usage_or_finished_response_blocks_even_when_later_attempt_is_503(self):
        for call in ({'purpose': 'draft', 'usage': {}}, {'purpose': 'draft', 'finish_reason': None},
                     {'purpose': 'audit'}, {'purpose': 'revision'}):
            client = FakeClient(diagnostics={100: [diagnostic(calls=[call]), diagnostic()]})
            result, _, _ = self.recover(client)
            self.assertEqual(result['status'], 'skipped')
            self.assertFalse(any(call[0] == 'dispatch' for call in client.calls))

    def test_prior_quality_failure_cannot_be_hidden_by_newer_transport_failure(self):
        client = FakeClient([run(101, '2026-11-24T21:00:00Z'), run()],
                            {100: [diagnostic(status='quality_failed')], 101: [diagnostic()]})
        result, _, _ = self.recover(client)
        self.assertEqual(result['status'], 'skipped')
        self.assertEqual(client.calls, [('list',), ('diagnostics', 101), ('diagnostics', 100)])

    def test_wrong_week_missing_invalid_calls_and_other_provider_errors_block(self):
        for change in (
                {'week': {'week_start': '2026-11-09', 'week_end': '2026-11-15', 'timezone': 'Asia/Singapore'}},
                {'provider_status': 429}, {'provider_status': 401}, {'provider_status': '503'},
                {'calls': []}, {'calls': [None]}, {'validation_error': 'unsupported_claim'},
                {'status': 'draft_ready_for_human_review'}):
            with self.subTest(change=change):
                result, client, _ = self.recover(FakeClient(diagnostics={100: [diagnostic(**change)]}))
                self.assertEqual(result['status'], 'skipped')
                self.assertFalse(any(call[0] == 'dispatch' for call in client.calls))

    def test_missing_or_release_ready_diagnostics_block(self):
        for data in ([], None, recovery.RecoveryError('weekly_recovery_has_completed_report')):
            result, client, _ = self.recover(FakeClient(diagnostics={100: data}))
            self.assertEqual(result['status'], 'skipped')
            self.assertFalse(any(call[0] == 'dispatch' for call in client.calls))

    def test_queued_in_progress_success_cancelled_and_timed_out_runs_block(self):
        for changes, reason in (
                ({'status': 'queued', 'conclusion': None}, 'publication_in_progress'),
                ({'status': 'in_progress', 'conclusion': None}, 'publication_in_progress'),
                ({'conclusion': 'success'}, 'publication_already_succeeded'),
                ({'conclusion': 'cancelled'}, 'prior_run_not_retryable'),
                ({'conclusion': 'timed_out'}, 'prior_run_not_retryable')):
            result, client, _ = self.recover(FakeClient([run(**changes)]))
            self.assertEqual(result['reason'], reason)
            self.assertEqual(client.calls, [('list',)])

    def test_old_cycle_no_attempt_and_expired_attempt_never_start_new_generation(self):
        result, client, _ = self.recover(FakeClient([run(created='2026-11-16T10:00:00Z')]))
        self.assertEqual(result['reason'], 'no_current_week_attempt')
        result, client, _ = self.recover(FakeClient(), now=datetime(2026, 11, 28, 12, tzinfo=timezone.utc))
        self.assertEqual(result['reason'], 'latest_attempt_expired')
        self.assertEqual(client.calls, [('list',)])

    def test_run_inventory_and_untrusted_ids_paths_cannot_inject_commands(self):
        bad = [run(identifier='100; echo secret'), run(path='some-other-workflow.yml'),
               run(head_branch='attacker'), run(event='pull_request'), run(run_attempt=0),
               run(created='2026-12-01T00:00:00Z')]
        for value in bad:
            client = FakeClient([value])
            with self.subTest(value=value), self.assertRaises(recovery.RecoveryError):
                self.recover(client)
            self.assertEqual(client.calls, [('list',)])
        with self.assertRaises(recovery.RecoveryError):
            recovery.validate_runs({'workflow_runs': [run(i) for i in range(1, 22)]},
                                   datetime(2026, 11, 22, 16, tzinfo=timezone.utc), NOW)

    def test_dispatch_rechecks_published_issue_after_reading_diagnostics(self):
        client = FakeClient()
        original = client.diagnostics

        def publish_during_check(value):
            path = self.root / 'web/public/data/weekly/2026-11-16.json'
            path.parent.mkdir(parents=True)
            path.write_text('{}')
            return original(value)

        client.diagnostics = publish_during_check
        result, _, _ = self.recover(client)
        self.assertEqual(result['reason'], 'already_published')
        self.assertEqual(client.calls, [('list',), ('diagnostics', 100)])


class GitHubBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_gh_arguments_are_fixed_separate_tokens_and_api_is_bounded(self):
        runner = Mock(side_effect=[SimpleNamespace(returncode=0, stdout='{"workflow_runs": []}'),
                                   SimpleNamespace(returncode=0, stdout='https://github.com/wcx0209/ai-news-brief/actions/runs/456')])
        client = recovery.GitHubClient(CLOUD, self.root, runner)
        self.assertEqual(client.list_runs(), {'workflow_runs': []})
        self.assertTrue(client.dispatch('2026-11-16').endswith('/456'))
        first, second = [call.args[0] for call in runner.call_args_list]
        self.assertEqual(first, ['gh', 'api', '--method', 'GET',
                                'repos/wcx0209/ai-news-brief/actions/workflows/weekly-publish.yml/runs?per_page=20&branch=main'])
        self.assertEqual(second, ['gh', 'workflow', 'run', 'weekly-publish.yml', '--repo', recovery.REPOSITORY,
                                 '--ref', 'main', '--field', 'week_start=2026-11-16'])
        for call in runner.call_args_list:
            self.assertNotIn('shell', call.kwargs)
            self.assertEqual(call.kwargs['timeout'], 60)

    def test_provider_exception_text_is_not_exposed(self):
        client = recovery.GitHubClient(CLOUD, self.root, Mock(side_effect=RuntimeError('secret-token')))
        with self.assertRaisesRegex(recovery.RecoveryError, '^weekly_recovery_github_command_failed$'):
            client.list_runs()

    def test_fixed_artifact_only_and_response_files_or_symlinks_are_rejected(self):
        def runner(arguments, **kwargs):
            destination = Path(arguments[arguments.index('--dir') + 1])
            attempt = destination / 'attempt-1'
            attempt.mkdir()
            (attempt / 'generation-metadata.json').write_text(json.dumps(diagnostic()))
            return SimpleNamespace(returncode=0, stdout='')

        callback = Mock(side_effect=runner)
        client = recovery.GitHubClient(CLOUD, self.root, callback)
        self.assertEqual(client.diagnostics(run()), [diagnostic()])
        arguments = callback.call_args.args[0]
        self.assertEqual(arguments[:7], ['gh', 'run', 'download', '100', '--repo', recovery.REPOSITORY, '--name'])
        self.assertEqual(arguments[7], recovery.ARTIFACT)
        with self.assertRaisesRegex(recovery.RecoveryError, 'already_exist'):
            client.diagnostics(run())

        for name in ('weekly-review.json', 'model-response-texts.json', 'response-symlink',
                     'generation-symlink', 'attempt-2-only', 'attempt-3'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)

                def invalid_runner(arguments, **kwargs):
                    destination = Path(arguments[arguments.index('--dir') + 1])
                    number = 2 if name == 'attempt-2-only' else 3 if name == 'attempt-3' else 1
                    attempt = destination / f'attempt-{number}'
                    attempt.mkdir()
                    data = attempt / 'generation-metadata.json'
                    if name == 'generation-symlink':
                        target = destination / 'outside.json'
                        target.write_text(json.dumps(diagnostic()))
                        data.symlink_to(target)
                    else:
                        data.write_text(json.dumps(diagnostic()))
                    if name == 'weekly-review.json':
                        (attempt / name).write_text('{}')
                    if name == 'model-response-texts.json':
                        (attempt / name).write_text('{"draft": "A completed response"}')
                    if name == 'response-symlink':
                        (attempt / 'model-response-texts.json').symlink_to(destination / 'missing-response.json')
                    return SimpleNamespace(returncode=0, stdout='')

                with self.assertRaises(recovery.RecoveryError):
                    recovery.GitHubClient(CLOUD, root, invalid_runner).diagnostics(run())

    def test_workflow_has_no_news_or_model_secrets_and_uses_only_two_backup_days(self):
        source = (ROOT / '.github/workflows/weekly-recovery.yml').read_text()
        # Keep this recovery workflow/test suite stdlib-only on a clean runner.
        self.assertIn('cron: "23 10 * * 2,3"', source)
        self.assertIn('permissions:\n  contents: read\n  actions: write', source)
        self.assertIn('group: polyemergence-weekly-recovery', source)
        self.assertIn('cancel-in-progress: false', source)
        self.assertNotIn('secrets.', source)
        self.assertNotIn('pip install', source)
        self.assertIn('ref: main', source)
        self.assertIn('GH_TOKEN: ${{ github.token }}', source)
        self.assertNotIn('INBRIEF_', source)
        self.assertNotIn('continue-on-error', source)


if __name__ == '__main__':
    unittest.main()
