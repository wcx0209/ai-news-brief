"""Offline contract tests: every database/model/artifact boundary is injected."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).absolute().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
repair = importlib.import_module('repair_archive_languages')

CLOUD = {'GITHUB_ACTIONS': 'true'}
SOURCE = '存档摘要称公司投入1,000美元，GPT-4预计2026年推出，但这一时间仍不确定。'
TRANSLATION = ('The stored summary says the company invested 1,000 dollars. '
               'GPT-4 is expected in 2026, but that timing remains uncertain.')


def wrong_language(text, locale):
    assert locale == 'en'
    return bool(re.search(r'[\u3400-\u9fff]', text))


def records(english=False):
    return [dict(id=identifier, title='Stored title', title_en='English title',
                 title_zh='原有标题', summary_en='Original short summary',
                 summary_zh='原有短摘要', long_summary_en=TRANSLATION if english else SOURCE,
                 long_summary_zh='原有中文长摘要', source_published_at='2026-11-01T09:00:00Z',
                 published_at='2026-11-02T00:00:00Z', created_at='2026-11-02T01:00:00Z',
                 category='news', importance_score=80) for identifier in repair.TARGET_IDS]


def clean_audit(identifiers=repair.TARGET_IDS):
    return {'audit_type': 'automated_model_check', 'checked_ids': list(identifiers), 'issues': []}


class FakeConnection:
    """Small transaction fake that models compare-and-update plus rollback."""

    def __init__(self, rows=None, conflict_id=None):
        self.rows = deepcopy(records() if rows is None else rows)
        self.pending = {}
        self.executed = []
        self.commits = self.rollbacks = self.closes = 0
        self.conflict_id = conflict_id

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        for row in self.rows:
            if row['id'] in self.pending:
                row['long_summary_en'] = self.pending[row['id']]
        self.pending.clear()
        self.commits += 1

    def rollback(self):
        self.pending.clear()
        self.rollbacks += 1

    def close(self):
        self.closes += 1


class FakeCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rowcount = -1

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query, parameters):
        self.connection.executed.append((query, parameters))
        if query == repair.SELECT_SQL:
            assert parameters == repair.TARGET_IDS
            return
        assert query == repair.UPDATE_SQL
        translated, identifier, old = parameters
        assert identifier in repair.TARGET_IDS
        row = next(row for row in self.connection.rows if row['id'] == identifier)
        if identifier == self.connection.conflict_id:
            row['long_summary_en'] = 'Concurrent editor changed this summary.'
        self.rowcount = int(row['long_summary_en'] == old)
        if self.rowcount:
            self.connection.pending[identifier] = translated

    def fetchall(self):
        return deepcopy(self.connection.rows)


class FakeCaller:
    def __init__(self, translations=None, audit=None):
        self.translations = translations
        self.audit = audit
        self.calls = []
        self.payloads = []

    def __call__(self, system, payload, purpose):
        assert len(self.calls) < 2
        self.calls.append({'purpose': purpose, 'usage': {'total_tokens': 42}})
        self.payloads.append(deepcopy(payload))
        if purpose == 'batch_translation':
            return {'translations': self.translations if self.translations is not None
                    else {identifier: TRANSLATION for identifier in payload['sources']}}
        return self.audit if self.audit is not None else clean_audit(payload['sources'])


class ArchiveLanguageRepairTests(unittest.TestCase):
    def run_offline(self, connection=None, caller=None, **kwargs):
        connection = connection or FakeConnection()
        caller = caller or FakeCaller()
        self.artifacts = {}

        def writer(artifacts, environment):
            self.assertEqual(environment, CLOUD)
            self.artifacts.update(deepcopy(artifacts))

        report = repair.run_repair(
            environ=CLOUD, connection_factory=lambda env: connection,
            caller_factory=lambda env: caller, wrong_language=wrong_language,
            artifact_writer=writer, **kwargs)
        return report, connection, caller

    def test_local_guard_precedes_secrets_sdk_database_language_and_file_io(self):
        class GuardedEnvironment(dict):
            def get(self, key, default=None):
                if key != 'GITHUB_ACTIONS':
                    raise AssertionError('Read a secret before the cloud guard')
                return super().get(key, default)

        environment = GuardedEnvironment(GITHUB_ACTIONS='false')
        forbidden = Mock(side_effect=AssertionError('Local side effect'))
        with patch('builtins.open', forbidden), patch.object(Path, 'mkdir', forbidden):
            with self.assertRaisesRegex(repair.RepairError, 'is_cloud_only'):
                repair.run_repair(environ=environment, connection_factory=forbidden,
                                  caller_factory=forbidden, wrong_language=forbidden,
                                  artifact_writer=forbidden)
            with self.assertRaisesRegex(repair.RepairError, 'is_cloud_only'):
                repair.CloudGemini(environment, sdk_factory=forbidden)
            with self.assertRaisesRegex(repair.RepairError, 'is_cloud_only'):
                repair.open_cloud_database(environment)
            with self.assertRaisesRegex(repair.RepairError, 'is_cloud_only'):
                repair.write_private_artifacts({}, environment)
        forbidden.assert_not_called()

    def test_only_literal_github_actions_true_is_accepted(self):
        for value in (None, '', 'TRUE', '1', True):
            with self.subTest(value=value), self.assertRaises(repair.RepairError):
                repair.require_cloud({'GITHUB_ACTIONS': value})

    def test_preview_is_audited_but_has_no_database_updates(self):
        original = records()
        report, connection, caller = self.run_offline()
        self.assertEqual(report['status'], 'preview')
        self.assertEqual((report['checked'], report['translated'], report['updated']), (4, 4, 0))
        self.assertEqual(connection.rows, original)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertEqual(len(connection.executed), 1)
        self.assertEqual([call['purpose'] for call in caller.calls],
                         ['batch_translation', 'automated_fidelity_audit'])
        self.assertEqual(caller.payloads[0], {'sources': {key: SOURCE for key in repair.TARGET_IDS}})
        self.assertEqual(set(caller.payloads[1]), {'sources', 'translations'})
        self.assertEqual(self.artifacts['translation-preview.json']['status'],
                         'automated_model_audited_preview')
        self.assertEqual(self.artifacts['report.json']['model_calls'], caller.calls)
        self.assertNotIn('repaired-summaries.json', self.artifacts)

    def test_apply_updates_only_target_column_after_both_model_calls(self):
        original = records()
        connection = FakeConnection()
        caller = FakeCaller()
        original_execute = FakeCursor.execute

        def execute(cursor, query, parameters):
            if query == repair.UPDATE_SQL:
                self.assertEqual(len(caller.calls), 2)
            return original_execute(cursor, query, parameters)

        with patch.object(FakeCursor, 'execute', execute):
            report, connection, _ = self.run_offline(connection, caller, apply=True)
        self.assertEqual((report['status'], report['updated']), ('applied', 4))
        self.assertEqual(connection.commits, 1)
        self.assertEqual(connection.closes, 1)
        for before, after in zip(original, connection.rows):
            self.assertEqual(after['long_summary_en'], TRANSLATION)
            self.assertEqual({key: value for key, value in before.items() if key != 'long_summary_en'},
                             {key: value for key, value in after.items() if key != 'long_summary_en'})
        self.assertIn('IS NOT DISTINCT FROM %s', repair.UPDATE_SQL)
        self.assertEqual(repair.UPDATE_SQL.split('SET', 1)[1].split('WHERE', 1)[0].strip(),
                         'long_summary_en = %s')

    def test_second_run_is_idempotent_and_never_initializes_a_model(self):
        _, connection, _ = self.run_offline(apply=True)
        forbidden = Mock(side_effect=AssertionError('No model needed'))
        artifacts = {}
        report = repair.run_repair(
            apply=True, environ=CLOUD, connection_factory=lambda env: connection,
            caller_factory=forbidden, wrong_language=wrong_language,
            artifact_writer=lambda data, env: artifacts.update(data))
        self.assertEqual((report['status'], report['already_english'], report['updated']), ('skipped', 4, 0))
        self.assertEqual(report['model_calls'], [])
        self.assertEqual(artifacts['repaired-summaries.json'], {
            'summaries': {identifier: TRANSLATION for identifier in repair.TARGET_IDS}})
        forbidden.assert_not_called()

    def test_apply_artifact_exports_exactly_four_confirmed_summaries(self):
        report, _, _ = self.run_offline(apply=True)
        self.assertEqual(report['status'], 'applied')
        self.assertEqual(self.artifacts['repaired-summaries.json'], {
            'summaries': {identifier: TRANSLATION for identifier in repair.TARGET_IDS}})

    def test_partial_apply_artifact_preserves_already_english_database_text(self):
        rows = records(english=True)
        for index, row in enumerate(rows):
            row['long_summary_en'] = f'Stored English account {index}; its qualification remains unchanged.'
        rows[2]['long_summary_en'] = SOURCE
        expected = {row['id']: row['long_summary_en'] for row in rows}
        expected[repair.TARGET_IDS[2]] = TRANSLATION
        report, _, caller = self.run_offline(FakeConnection(rows), apply=True)
        self.assertEqual(report['updated'], 1)
        self.assertEqual(len(caller.calls), 2)
        self.assertEqual(self.artifacts['repaired-summaries.json'], {'summaries': expected})

    def test_only_remaining_wrong_language_ids_are_sent_and_updated(self):
        rows = records(english=True)
        rows[2]['long_summary_en'] = SOURCE
        report, connection, caller = self.run_offline(FakeConnection(rows), apply=True)
        self.assertEqual((report['already_english'], report['updated']), (3, 1))
        self.assertEqual(set(caller.payloads[0]['sources']), {repair.TARGET_IDS[2]})

    def test_numbers_allow_grouping_fullwidth_and_chinese_sentence_punctuation(self):
        identifier = repair.TARGET_IDS[0]
        source = '版本3.5在2026年增长12%，投入１２，０００美元；地址https://example.com/v2。'
        translated = 'Version 3.5 grew 12% in 2026, with 12000 dollars; https://example.com/v2.'
        result = {'translations': {identifier: translated}}
        self.assertEqual(repair.validate_translations(result, {identifier: source}, wrong_language),
                         result['translations'])
        self.assertEqual(repair.numeric_tokens('版本3，2026年推出。'),
                         repair.numeric_tokens('Version 3 will ship in 2026.'))
        self.assertEqual(repair.numeric_tokens('投入1,000, 尚未确认。'),
                         repair.numeric_tokens('An investment of 1000, unconfirmed.'))

    def test_changed_numbers_urls_or_non_english_block_every_update(self):
        cases = [(TRANSLATION.replace('2026', '2027'), 'numeric_tokens'),
                 (TRANSLATION + ' https://new.example.org/', 'changed_urls'),
                 (SOURCE, 'non_english')]
        for bad_text, code in cases:
            with self.subTest(code=code):
                connection = FakeConnection()
                proposed = {key: TRANSLATION for key in repair.TARGET_IDS}
                proposed[repair.TARGET_IDS[-1]] = bad_text
                with self.assertRaisesRegex(repair.RepairError, code):
                    self.run_offline(connection, FakeCaller(proposed), apply=True)
                self.assertEqual(len(connection.executed), 1)
                self.assertEqual(connection.commits, 0)
                self.assertEqual(connection.rows, records())
                self.assertNotIn('repaired-summaries.json', self.artifacts)

    def test_added_removed_duplicate_and_out_of_scope_ids_are_refused(self):
        translations = {key: TRANSLATION for key in repair.TARGET_IDS}
        cases = [dict(translations, unknown=TRANSLATION),
                 {key: value for key, value in translations.items() if key != repair.TARGET_IDS[0]}]
        for proposed in cases:
            connection = FakeConnection()
            with self.assertRaisesRegex(repair.RepairError, 'translation_scope'):
                self.run_offline(connection, FakeCaller(proposed), apply=True)
            self.assertEqual(len(connection.executed), 1)
        invalid_rows = records()
        invalid_rows[-1]['id'] = 'not-in-the-approved-four'
        for rows in (invalid_rows, records()[:-1], [records()[0]] * 4):
            with self.assertRaises(repair.RepairError):
                self.run_offline(FakeConnection(rows), apply=True)

    def test_audit_requires_all_ids_automated_label_and_no_material_issues(self):
        cases = []
        for severity in ('high', 'medium'):
            audit = clean_audit()
            audit['issues'] = [{'id': repair.TARGET_IDS[0], 'severity': severity,
                                'detail': 'A claim lost its attribution.'}]
            cases.append(audit)
        cases += [dict(clean_audit(), checked_ids=list(repair.TARGET_IDS[:-1])),
                  dict(clean_audit(), audit_type='human_review'),
                  dict(clean_audit(), independent_verification=True)]
        for audit in cases:
            connection = FakeConnection()
            with self.subTest(audit=audit), self.assertRaises(repair.RepairError):
                self.run_offline(connection, FakeCaller(audit=audit), apply=True)
            self.assertEqual(connection.rows, records())
            self.assertEqual(len(connection.executed), 1)
            self.assertEqual(connection.commits, 0)

    def test_one_concurrent_change_rolls_back_the_entire_batch(self):
        conflict_id = repair.TARGET_IDS[1]
        connection = FakeConnection(conflict_id=conflict_id)
        with self.assertRaisesRegex(repair.RepairError, 'concurrent_change'):
            self.run_offline(connection, apply=True)
        self.assertEqual(connection.commits, 0)
        self.assertEqual(connection.rollbacks, 1)
        self.assertFalse(connection.pending)
        self.assertEqual(connection.rows[0]['long_summary_en'], SOURCE)
        self.assertEqual(connection.rows[1]['long_summary_en'], 'Concurrent editor changed this summary.')
        self.assertEqual(self.artifacts['report.json']['updated'], 0)
        self.assertEqual(len(self.artifacts['report.json']['model_calls']), 2)
        self.assertNotIn('repaired-summaries.json', self.artifacts)

    def test_provider_exception_text_is_never_in_reports(self):
        secret = 'a-secret-token-and-story-text'
        connection = FakeConnection()
        with self.assertRaisesRegex(repair.RepairError, '^archive_language_repair_failed$'):
            repair.run_repair(environ=CLOUD,
                              connection_factory=lambda env: connection,
                              caller_factory=Mock(side_effect=RuntimeError(secret)),
                              wrong_language=wrong_language,
                              artifact_writer=lambda value, env: setattr(self, 'artifacts', value))
        self.assertNotIn(secret, json.dumps(self.artifacts))
        self.assertEqual(connection.rollbacks, 1)

    def test_gemini_is_pinned_bounded_and_keeps_usage_with_no_retries(self):
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{"ok":true}'))])
        create = Mock(return_value=response)
        sdk = Mock(return_value=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
        client = repair.CloudGemini(dict(CLOUD, INBRIEF_LLM_API_KEY='never-log-this'), sdk_factory=sdk)
        sdk.assert_called_once_with(api_key='never-log-this', base_url=repair.BASE_URL,
                                    max_retries=0, timeout=180)
        self.assertEqual(client('Instructions', {'sources': {}}, 'batch_translation'), {'ok': True})
        client('Instructions', {}, 'automated_fidelity_audit')
        with self.assertRaisesRegex(repair.RepairError, 'call_limit'):
            client('Instructions', {}, 'batch_translation')
        self.assertEqual(create.call_count, 2)
        self.assertEqual(client.calls[0]['usage']['total_tokens'], 30)
        for call in create.call_args_list:
            self.assertEqual(call.kwargs['model'], 'gemini-3.5-flash-lite')
            self.assertEqual(call.kwargs['max_tokens'], 15000)
            self.assertEqual(call.kwargs['timeout'], 180)
        self.assertNotIn('never-log-this', json.dumps(client.calls))

    def test_failed_model_request_consumes_budget_and_sanitizes_error(self):
        create = Mock(side_effect=RuntimeError('provider leaked SECRET and story'))
        sdk = lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        client = repair.CloudGemini(dict(CLOUD, INBRIEF_LLM_API_KEY='SECRET'), sdk_factory=sdk)
        for _ in range(2):
            with self.assertRaisesRegex(repair.RepairError, '^archive_language_repair_model_request_failed$'):
                client('instructions', {}, 'batch_translation')
        with self.assertRaisesRegex(repair.RepairError, 'call_limit'):
            client('instructions', {}, 'automated_fidelity_audit')
        self.assertEqual(create.call_count, 2)
        self.assertNotIn('SECRET', json.dumps(client.calls))

    def test_model_input_output_json_and_finish_reason_bounds(self):
        response = SimpleNamespace(usage=None, choices=[SimpleNamespace(
            finish_reason='stop', message=SimpleNamespace(content='{"translations":{},"translations":{}}'))])
        create = Mock(return_value=response)
        sdk = lambda **kwargs: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

        def client():
            return repair.CloudGemini(dict(CLOUD, INBRIEF_LLM_API_KEY='fake'), sdk_factory=sdk)

        bounded = client()
        with self.assertRaisesRegex(repair.RepairError, 'input_bound'):
            bounded('x' * repair.MAX_INPUT_CHARS, {}, 'batch_translation')
        self.assertFalse(bounded.calls)
        create.assert_not_called()
        with self.assertRaisesRegex(repair.RepairError, 'duplicate_json_key'):
            client()('instructions', {}, 'batch_translation')
        response.choices[0].message.content = 'x' * (repair.MAX_OUTPUT_CHARS + 1)
        with self.assertRaisesRegex(repair.RepairError, 'output_bound'):
            client()('instructions', {}, 'batch_translation')
        response.choices[0].finish_reason = 'length'
        with self.assertRaisesRegex(repair.RepairError, 'incomplete'):
            client()('instructions', {}, 'batch_translation')


if __name__ == '__main__':
    unittest.main()
