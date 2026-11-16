import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('publish_weekly', ROOT / 'scripts/publish_weekly.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class WeeklyReleaseTests(unittest.TestCase):
    def test_complete_week_defaults_to_singapore_calendar(self):
        now = datetime(2026, 11, 15, 16, tzinfo=timezone.utc)
        self.assertEqual(release.week_id('', now), '2026-11-09')
        for value in ('2026-11-16', '2026-11-10', '../2026-11-09', '2026-11-09\n'):
            with self.assertRaises(ValueError):
                release.week_id(value, now)

    def test_local_entrypoint_refuses_before_files_sdk_or_database(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), patch.object(release, 'load_json') as load:
            with self.assertRaises(SystemExit):
                release.main(['--generate'])
            load.assert_not_called()

    def test_existing_issue_skips_cloud_generation_even_when_requested(self):
        exporter = MagicMock()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dated = root / 'web/public/data/weekly/2026-11-09.json'
            dated.parent.mkdir(parents=True)
            dated.write_text('{}')
            with patch.object(release, 'ROOT', root), patch.object(release, 'generate_cloud') as generate, \
                    patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'WEEK_START': '2026-11-09',
                                            'SOURCE_RUN_ID': '', 'GITHUB_EVENT_NAME': 'schedule'}), \
                    patch.dict(sys.modules, {'export_weekly': exporter}):
                self.assertEqual(release.main(['--generate']), 0)
                generate.assert_not_called()
                exporter.export_weeklies.assert_called_once()

    def test_artifact_authorization_cannot_be_inferred_from_schedule(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'WEEK_START': '2026-11-09',
                                     'SOURCE_RUN_ID': '43792710068', 'GITHUB_EVENT_NAME': 'schedule'}):
            with self.assertRaisesRegex(ValueError, 'manual_dispatch'):
                release.main(['--preflight'])

    def test_retry_only_known_transient_before_any_successful_response(self):
        value = {'status': 'failed', 'provider_status': 503, 'calls': [{'purpose': 'draft'}]}
        self.assertTrue(release.transient_before_response(value))
        for mutation in ({'provider_status': 429}, {'provider_status': None},
                         {'calls': [{'usage': {'total_tokens': 100}}, {'purpose': 'audit'}]},
                         {'calls': [{'finish_reason': 'stop'}, {'purpose': 'audit'}]},
                         {'calls': []}, {'status': 'draft_ready_for_human_review'}):
            self.assertFalse(release.transient_before_response({**value, **mutation}))

    def test_invalid_artifact_symlink_and_large_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            file = Path(directory) / 'json'
            file.write_text('{}')
            link = Path(directory) / 'link'
            link.symlink_to(file)
            with self.assertRaises(ValueError):
                release.load_json(link)
            file.write_text(' ' * 2_000_001)
            with self.assertRaises(ValueError):
                release.load_json(file)

    def test_release_copy_is_explicit_scoped_and_keeps_original_unchanged(self):
        report = {'issue': {'week_start': '2026-11-09'}, 'en': {'lead': {'text':
            'IBM reported reaching quantum advantage with the Nighthawk r2 processor. '
            'This digest is a human-review draft, not a verified industry verdict.'}, 'main_events': [
                {'event_id': 'weekly-0b1ecfbfdf707b37', 'why_it_matters': 'significantly reducing manual audit time'},
                {'event_id': 'weekly-5d8ca9d00f0f44dd', 'what_changed': 'A Nature Brain-Machine Interfaces study'}]},
            'zh': {'main_events': [
                {'event_id': 'weekly-0b1ecfbfdf707b37', 'why_it_matters': '大幅缩短了形式化验证所需的人工时间',
                 'what_changed': '', 'uncertainty': '该供料未提供'},
                {'event_id': 'weekly-5d8ca9d00f0f44dd', 'what_changed': '', 'why_it_matters': '', 'uncertainty': ''}]}}
        before = json.dumps(report)
        copy, changes = release.release_copy(report, '43792710068')
        self.assertEqual(json.dumps(report), before)
        self.assertNotIn('human-review draft', copy['en']['lead']['text'])
        self.assertIn('separately introduced', copy['en']['lead']['text'])
        self.assertIn('18 次', copy['zh']['main_events'][1]['what_changed'])
        self.assertGreater(len(changes), 3)

    def test_workflow_is_cloud_only_scheduled_serial_and_fail_closed(self):
        import yaml
        workflow = yaml.load((ROOT / '.github/workflows/weekly-publish.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertEqual(workflow['on']['schedule'][0]['cron'], '0 10 * * 1')
        self.assertEqual(workflow['concurrency']['group'], 'polyemergence-daily-brief')
        steps = workflow['jobs']['publish']['steps']
        self.assertFalse(any('continue-on-error' in step for step in steps))
        model_steps = [step for step in steps if 'INBRIEF_LLM_API_KEY' in step.get('env', {})]
        self.assertEqual(len(model_steps), 1)
        self.assertIn("inputs.source_run_id == ''", model_steps[0]['if'])
        self.assertNotIn('INBRIEF_LLM_API_KEY', workflow['jobs']['publish'].get('env', {}))
        self.assertTrue(any('--input-json web/public/data/articles.json' in step.get('run', '') for step in steps))


if __name__ == '__main__':
    unittest.main()
