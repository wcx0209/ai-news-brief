"""Offline recovery of an exact failed-run packet, without service calls."""
from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from test_weekly_publication import fixture
import recover_weekly_draft as repair


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.input = Path(self.tmp.name) / 'input'
        self.attempt = self.input / 'attempt-1'
        self.attempt.mkdir(parents=True)
        report, _, catalog = fixture()
        self.issue = repair.week_window('2026-11-09')
        self.complete = {loc: report[loc] for loc in ('zh', 'en')}
        incomplete = deepcopy(self.complete)
        for loc in incomplete:
            incomplete[loc]['main_events'].pop()
        events = [{'event_id': f'event-{i}', 'support': [s], 'representative': s} for i, s in enumerate(catalog)]
        self.plan = {'shortlist': {'main': events, 'signals': []}, 'domain_counts': {'ai': {'main': 3, 'event_groups': 3}}}
        self.packet = repair.build_packet(self.plan, self.issue)
        self.prior = {'status': 'failed', 'validation_error': 'weekly_event_plan_mismatch', 'week': self.issue,
                      'calls': [{'purpose': 'draft', 'finish_reason': 'stop'}]}
        self.out = Path(self.tmp.name) / 'review'
        write(self.attempt / 'selection-audit.json', self.plan)
        write(self.attempt / 'evidence-packet.json', self.packet)
        write(self.attempt / 'source-catalog.json', catalog)
        write(self.attempt / 'generation-metadata.json', self.prior)
        write(self.attempt / 'model-response-texts.json',
              [{'purpose': 'draft', 'finish_reason': 'stop', 'text': json.dumps(incomplete)}])

    def test_only_manually_dispatched_main_cloud_before_any_live_operation(self):
        with patch.dict('os.environ', {}, clear=True), patch.object(repair, 'retrieve') as retrieve:
            with self.assertRaisesRegex(ValueError, 'cloud_main_dispatch_only'):
                repair.main()
            retrieve.assert_not_called()

    def test_exact_failed_source_workflow_and_first_attempt(self):
        run = {'id': 12, 'head_branch': 'main', 'head_repository': {'full_name': repair.REPO}, 'event': 'schedule',
               'path': '.github/workflows/weekly-publish.yml', 'status': 'completed', 'conclusion': 'failure',
               'run_attempt': 1}
        repair.check_run(run, '12')
        for change in ({'id': 13}, {'head_branch': 'other'}, {'head_repository': {}},
                       {'path': 'review.yml'}, {'event': 'push'}, {'conclusion': 'success'}, {'run_attempt': 2}):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, 'invalid_source_run'):
                repair.check_run({**run, **change}, '12')

    def test_restore_accepts_only_original_plan_and_selected_ids_for_matching_week(self):
        restored, _, draft, _ = repair.restore(self.input, self.issue)
        self.assertEqual(restored, self.plan)
        self.assertEqual(len(draft['zh']['main_events']), 2)
        with self.assertRaisesRegex(ValueError, 'not_a_single_incomplete_draft'):
            repair.restore(self.input, repair.week_window('2026-11-16'))
        self.packet['main_events'].reverse()
        write(self.attempt / 'evidence-packet.json', self.packet)
        with self.assertRaisesRegex(ValueError, 'saved_selection_mismatch'):
            repair.restore(self.input, self.issue)

    def test_refuses_other_completed_requests_or_prior_attempts(self):
        self.prior['calls'].append({'purpose': 'review', 'finish_reason': 'stop'})
        write(self.attempt / 'generation-metadata.json', self.prior)
        with self.assertRaisesRegex(ValueError, 'not_a_single_incomplete_draft'):
            repair.restore(self.input, self.issue)
        (self.input / 'attempt-2').mkdir()
        with self.assertRaisesRegex(ValueError, 'single_failed_attempt'):
            repair.restore(self.input, self.issue)

    def test_refreshes_only_missing_sources_with_the_original_adapter(self):
        plan, catalog, _, _ = repair.restore(self.input, self.issue)
        old = {'status': 'retrieved', 'source_url': catalog[0]['url'], 'excerpt': 'original retained '}
        catalog[0]['original_read'] = old
        repair.apply_reads(plan, {s['id']: s for s in catalog})
        requested = []
        def reader(url):
            requested.append(url)
            return {'ok': False, 'error': {'code': 'PLATFORM_BLOCKED'}}
        audit = repair.refresh_missing(plan, catalog, lambda sub: repair.enrich_selected_sources(sub, reader))
        self.assertCountEqual(requested, [s['url'] for s in catalog[1:]])
        self.assertEqual(audit['requested_unique_urls'], 2)
        self.assertEqual(catalog[0]['original_read'], old)
        self.assertEqual(catalog[1]['original_read']['error_code'], 'PLATFORM_BLOCKED')

    def test_recovers_original_through_fresh_revision_and_audit_before_usable_review_artifact(self):
        corrected = self.complete
        class Model:
            model = 'fixture'
            def __init__(self):
                self.calls = []
                self.raw_responses = []
            def __call__(self, system, payload, purpose):
                self.calls.append({'purpose': purpose})
                self.guidance = payload['editorial_guidance']
                if purpose == 'bounded_revision':
                    return deepcopy(corrected)
                self.audit_lengths = len(payload['draft']['zh']['main_events'])
                return {'issues': []}
        model = Model()
        with patch.object(repair, 'editorial_guidance', return_value=['Check scope']):
            repair.recover(self.input, self.out, self.issue, '12', model_factory=lambda: model,
                           enrich=lambda part: (part, {'requested_unique_urls': 0}))
        self.assertEqual([r['purpose'] for r in model.calls],
                         ['automated_editorial_check', 'bounded_revision', 'post_revision_editorial_check'])
        self.assertEqual(model.guidance, ['Check scope'])
        self.assertEqual(model.audit_lengths, 3)
        meta = repair.load_json(self.out / 'generation-metadata.json')
        self.assertEqual(meta['total_cloud_llm_calls_including_initial'], 4)
        self.assertEqual(meta['recovered_from_publication_run_id'], '12')
        self.assertEqual(meta['status'], 'revised_draft_ready_for_human_review')
        report = repair.load_json(self.out / 'weekly-review.json')
        self.assertEqual(len(report['zh']['main_events']), 3)
        self.assertTrue(report['editorial_review']['revision_made'])
        self.assertIn('post_revision_audit', report['editorial_review'])

    def test_failed_automatic_release_gate_yields_diagnostics_only(self):
        report, _, _ = fixture()
        report['issue']['generated_at'] = self.issue['end']
        finding = {'event_id': 'lead', 'severity': 'medium', 'evidence_ids': ['source-0'],
                   'detail_en': 'Unsupported wording', 'detail_zh': '措辞超出依据'}
        report['editorial_review'].update(revision_made=True, post_revision_audit={'issues': [finding]})
        class Model:
            model = 'fixture'
            calls = []
            raw_responses = []
        with patch.object(repair, 'generate_review', return_value=(report, self.packet)):
            with self.assertRaisesRegex(ValueError, 'unresolved_editorial_issue'):
                repair.recover(self.input, self.out, self.issue, '12', model_factory=Model,
                               enrich=lambda part: (part, {}))
        self.assertFalse((self.out / 'weekly-review.json').exists())
        self.assertEqual(repair.load_json(self.out / 'generation-metadata.json')['status'], 'failed')

    def final_fixture(self):
        config = Path(self.tmp.name) / 'edited.json'
        edited = deepcopy(self.complete)
        for locale in ('zh', 'en'):
            edited[locale].pop('follow_up')
        write(config, edited)
        prior_calls = [{'purpose': 'draft', 'finish_reason': 'stop'}]
        calls = [{'purpose': p, 'finish_reason': 'stop'} for p in ('automated_editorial_check', 'bounded_revision')]
        write(self.attempt / 'generation-metadata.json', {'week': self.issue, 'status': 'failed',
              'recovered_from_publication_run_id': '11',
              'validation_error': 'model_json_invalid_json', 'total_cloud_llm_calls_including_initial': 3,
              'prior_run_calls': prior_calls, 'calls': calls})
        write(self.attempt / 'model-response-texts.json', [{**calls[0], 'text': '{"issues":[]}'},
                                                          {**calls[1], 'text': '{"zh" : {'}])
        write(self.attempt / 'source-read-audit.json', {'requested_unique_urls': 3})
        folder = Path(self.tmp.name) / 'corrections'
        folder.mkdir()
        write(folder / (self.issue['week_start'] + '.json'), {'week_start': self.issue['week_start'], 'source_run_id': '11',
              'final_audit_source_run_id': '12', 'instructions': ['Check supporting material']})
        location = patch.object(repair, 'CORRECTIONS', folder)
        location.start()
        self.addCleanup(location.stop)
        return config

    def test_final_only_uses_one_new_call_auditing_exact_editorial_copy(self):
        config = self.final_fixture()
        class AuditOnly:
            calls = []
            raw_responses = []
            model = 'fixture'
            def __call__(self, system, payload, purpose):
                self.calls.append({'purpose': purpose})
                self.reviewed = deepcopy(payload['draft'])
                return {'issues': []}
        fake = AuditOnly()
        with patch.object(repair, 'refresh_missing', side_effect=AssertionError('no new collection')):
            repair.recover(self.attempt, self.out, self.issue, '12', model_factory=lambda: fake,
                           final_copy=config)
        report = repair.load_json(self.out / 'weekly-review.json')
        self.assertEqual(fake.reviewed, {k: report[k] for k in ('zh','en')})
        self.assertEqual(fake.calls, [{'purpose': 'post_revision_editorial_check'}])
        meta = repair.load_json(self.out / 'generation-metadata.json')
        self.assertEqual([c['purpose'] for c in meta['prior_run_calls']], ['draft','automated_editorial_check','bounded_revision'])
        self.assertEqual(meta['total_cloud_llm_calls_including_initial'], 4)
        self.assertEqual(meta['recovered_from_repair_run_id'], '12')
        self.assertEqual(meta['recovered_from_publication_run_id'], '11')
        self.assertEqual(meta['revision_source'], 'repository_editorial_copy')

    def test_final_only_rejects_wrong_lineage_and_sensitive_claims_before_model(self):
        config = self.final_fixture()
        with self.assertRaisesRegex(ValueError, 'unrecognized_week_or_run'):
            repair.final_inputs(self.attempt, self.issue, '123', config)
        data = repair.load_json(config)
        data['en']['main_events'][0]['what_changed'] = 'The source reports a clinical benefit.'
        write(config, data)
        with self.assertRaisesRegex(ValueError, 'high_impact_original_source_unavailable'):
            repair.recover(self.attempt, self.out, self.issue, '12', final_copy=config,
                           model_factory=lambda: self.fail('no cloud call for invalid copy'))
        prior = repair.load_json(self.attempt / 'generation-metadata.json')
        prior['calls'].append({'purpose':'post_revision_editorial_check','finish_reason':'stop'})
        write(self.attempt / 'generation-metadata.json', prior)
        with self.assertRaisesRegex(ValueError,'prior_attempt_mismatch'):
            repair.final_inputs(self.attempt,self.issue,'12',config)
