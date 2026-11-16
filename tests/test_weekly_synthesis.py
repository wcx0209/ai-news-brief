from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from weekly_synthesis import attach_synthesis, evidence_components, generate_synthesis, validate_synthesis

spec = importlib.util.spec_from_file_location('synthesis_script', ROOT / 'scripts/add_weekly_synthesis.py')
script = importlib.util.module_from_spec(spec)
spec.loader.exec_module(script)


def fixtures():
    packet = {'main_events': [{'event_id': 'event-a', 'evidence_ids': ['media-a', 'official-a']},
                              {'event_id': 'event-b', 'evidence_ids': ['official-b']}], 'early_signals': []}
    catalog = [{'id': 'media-a', 'url': 'https://media.example/story-a'},
               {'id': 'official-a', 'url': 'https://lab.example/notice-a'},
               {'id': 'official-b', 'url': 'https://other.example/notice-b'}]
    def synthesis():
        value = {'intro': 'This selection raises a useful question.', 'limits': 'A selection does not establish an industry trend.',
                 'evidence_ids': ['official-a', 'official-b']}
        for name in ('signal', 'structure', 'consequence'):
            value[name] = {'title': 'Explain what changes', 'text': 'Specific examples suggest a conditional interpretation.',
                           'support': 'selection_based', 'evidence_ids': ['official-a', 'official-b']}
        return value
    result = {locale: {'synthesis': synthesis()} for locale in ('zh', 'en')}
    previous = {'issue': {'status': 'DRAFT', 'generated_at': '2026-11-16T01:35:51Z'}, 'coverage': {'fields': []},
                'editorial_review': {'human_approved': False},
                **{locale: {'title': 'Existing title', 'lead': {'text': 'Existing lead'},
                             'main_events': [{'event_id': 'event-a', 'what_changed': 'An existing attributed claim.'}],
                             'early_signals': [], 'follow_up': {'available': False}} for locale in ('zh', 'en')}}
    return packet, catalog, result, previous


class WeeklySynthesisTests(unittest.TestCase):
    def setUp(self):
        self.packet, self.catalog, self.result, self.previous = fixtures()

    def test_real_two_event_reading_is_accepted_without_claiming_verification(self):
        self.assertEqual(validate_synthesis(self.result, self.packet, self.catalog), self.result)

    def test_two_sources_for_one_event_do_not_count_as_two_events(self):
        for locale in ('zh', 'en'):
            self.result[locale]['synthesis']['signal']['evidence_ids'] = ['media-a', 'official-a']
        with self.assertRaisesRegex(ValueError, 'distinct_events'):
            validate_synthesis(self.result, self.packet, self.catalog)

    def test_same_url_mis_split_into_two_events_does_not_count_twice(self):
        self.catalog[2]['url'] = 'https://lab.example/notice-a?utm_source=copy'
        with self.assertRaisesRegex(ValueError, 'distinct_events'):
            validate_synthesis(self.result, self.packet, self.catalog)

    def test_duplicate_id_across_events_is_rejected_instead_of_overwritten(self):
        self.packet['main_events'][1]['evidence_ids'] = ['official-a']
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            evidence_components(self.packet, self.catalog)

    def test_unknown_ids_cannot_become_evidence(self):
        self.result['zh']['synthesis']['consequence']['evidence_ids'] = ['not-supplied']
        with self.assertRaises(ValueError):
            validate_synthesis(self.result, self.packet, self.catalog)

    def test_bilingual_citations_and_support_must_match(self):
        self.result['zh']['synthesis']['structure']['evidence_ids'] = ['media-a', 'official-b']
        with self.assertRaisesRegex(ValueError, 'translation_citation'):
            validate_synthesis(self.result, self.packet, self.catalog)
        self.result = fixtures()[2]
        self.result['en']['synthesis']['consequence']['support'] = 'insufficient'
        with self.assertRaisesRegex(ValueError, 'translation_support'):
            validate_synthesis(self.result, self.packet, self.catalog)

    def test_insufficient_evidence_is_explicit_and_cannot_pass_as_supported(self):
        for locale in ('zh', 'en'):
            item = self.result[locale]['synthesis']['structure']
            item.update(support='insufficient', evidence_ids=['official-a'], text='This selection does not establish a common mechanism.')
        validate_synthesis(self.result, self.packet, self.catalog)

    def test_only_new_section_can_be_returned_and_existing_report_is_frozen(self):
        old = deepcopy(self.previous)
        report = attach_synthesis(self.previous, self.result, self.packet, self.catalog)
        self.assertEqual(self.previous, old)
        for locale in ('zh', 'en'):
            del report[locale]['synthesis']
        self.assertEqual(report, old)
        self.result['zh']['main_events'] = [{'event_id': 'made-up'}]
        with self.assertRaisesRegex(ValueError, 'must_not_rewrite'):
            attach_synthesis(old, self.result, self.packet, self.catalog)

    def test_one_injected_offline_call_only_and_no_input_mutation(self):
        call = MagicMock(return_value=self.result)
        report, result = generate_synthesis(self.previous, self.packet, self.catalog, call)
        self.assertEqual(call.call_count, 1)
        self.assertEqual(result, self.result)
        self.assertIn('synthesis', report['zh'])

    def test_model_cannot_supply_unindexed_urls_or_extra_fields(self):
        self.result['en']['synthesis']['signal']['text'] = 'See https://invented.example/claim'
        with self.assertRaises(ValueError):
            validate_synthesis(self.result, self.packet, self.catalog)
        self.result = fixtures()[2]
        self.result['en']['synthesis']['signal']['is_verified'] = True
        with self.assertRaises(ValueError):
            validate_synthesis(self.result, self.packet, self.catalog)

    def test_main_refuses_local_execution_before_clients_files_or_keys(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), patch.object(Path, 'mkdir') as mkdir:
            with self.assertRaises(SystemExit):
                script.main(['--input', 'output/fixture'])
            mkdir.assert_not_called()

    def test_editorial_copy_cloud_render_never_instantiates_a_gemini_client(self):
        packet, catalog, result, previous = fixtures()
        previous['issue'].update(week_start='2026-11-09')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / 'output/source'
            source.mkdir(parents=True)
            edits = root / 'config/weekly-synthesis-guidance'
            edits.mkdir(parents=True)
            files = {'weekly-review.json': previous, 'source-catalog.json': catalog, 'evidence-packet.json': packet,
                     'generation-metadata.json': {'calls': [], 'actual_usage': {}},
                     'selection-audit.json': {}, 'automated-editorial-review.json': {}}
            for name, value in files.items():
                (source / name).write_text(json.dumps(value), encoding='utf-8')
            editorial_payload = json.dumps({
                'week_start': '2026-11-09', 'source_run_id': '123', 'copy': result,
                'authoring_method': 'Cloud assistant editorial copy', 'superseded_cloud_attempts': []})
            with patch.object(script, 'ROOT', root), \
                    patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'SOURCE_RUN_ID': '123', 'APPLY_EDITORIAL_COPY': 'true', 'INBRIEF_LLM_API_KEY': '', 'WEEKLY_REVIEW_EDITORIAL_COPY': editorial_payload}), \
                    patch('weekly_generation.CloudGemini', side_effect=AssertionError('No API client')) as client:
                self.assertEqual(script.main(['--input', 'output/source', '--output', 'output/review']), 0)
            client.assert_not_called()
            output = root / 'output/review'
            report = json.loads((output / 'weekly-review.json').read_text())
            metadata = json.loads((output / 'generation-metadata.json').read_text())
            self.assertEqual(metadata['gemini_requests_in_this_render'], 0)
            self.assertEqual(report['zh']['main_events'], previous['zh']['main_events'])
            self.assertEqual(report['issue'], previous['issue'])
            self.assertTrue((output / 'zh.html').exists())


if __name__ == '__main__':
    unittest.main()
