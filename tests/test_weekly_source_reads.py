"""Offline fixtures for bounded weekly original-source reads and script wiring."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
import weekly_source_reads as sources

BODY = 'The publisher describes a result, its methods, and its stated limits. ' * 20


def record(number, *, source_type='media_report', url=None):
    return {'id': str(number), 'url': url or f'https://publisher.example.org/news/{number}',
            'source': 'Original publisher', 'source_type': source_type,
            'source_published_at': '2026-11-10T12:00:00Z',
            'en': {'summary': 'A stored summary.'}, 'zh': {'summary': '保存的摘要。'}}


def event(number):
    row = record(number)
    return {'event_id': f'event-{number}', 'representative': row, 'support': [row]}


def plan(main=3, signals=0):
    return {'shortlist': {'main': [event(n) for n in range(main)],
                          'signals': [event(n + main) for n in range(signals)]},
            'candidates': [event(100)], 'coverage': {}}


def response(url, text=BODY, **overrides):
    return {'schema_version': 1, 'ok': True, 'channel': 'web', 'action': 'read',
            'backend': 'jina', 'items': [{'url': url, 'text': text,
                                        'published_at': '2099-01-01T00:00:00Z'}],
            'meta': {}, **overrides}


class WeeklySourceReadTests(unittest.TestCase):
    def setUp(self):
        self.no_dns = patch('socket.getaddrinfo', side_effect=AssertionError('No DNS'))
        self.no_dns.start()
        self.addCleanup(self.no_dns.stop)

    def test_live_local_entrypoint_refuses_before_client_or_dns(self):
        for value in ('false', '', 'TRUE'):
            with patch.dict(os.environ, {'GITHUB_ACTIONS': value}), \
                    patch.object(sources, 'AgentReachClient') as client:
                with self.assertRaisesRegex(RuntimeError, 'cloud_only'):
                    sources.enrich_selected_sources(plan())
                client.assert_not_called()

    def test_live_cloud_client_uses_only_bounded_web_reader(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true'}), \
                patch.object(sources, 'AgentReachClient') as client:
            client.return_value.read_web.side_effect = response
            enriched, audit = sources.enrich_selected_sources(plan())
        client.assert_called_once_with(timeout=20, max_chars=6000)
        self.assertEqual(client.return_value.read_web.call_count, 3)
        client.return_value.read_github.assert_not_called()
        client.return_value.read_youtube.assert_not_called()
        self.assertEqual(audit['retrieved_unique_urls'], 3)
        self.assertEqual(enriched['shortlist']['main'][0]['support'][0]['original_read']['status'], 'retrieved')

    def test_copy_preserves_attribution_dates_summaries_and_unselected_candidates(self):
        original = plan()
        before = deepcopy(original)
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}):
            enriched, audit = sources.enrich_selected_sources(original, reader=response)
        self.assertEqual(original, before)
        row = enriched['shortlist']['main'][0]['support'][0]
        self.assertEqual({key: value for key, value in row.items() if key != 'original_read'},
                         original['shortlist']['main'][0]['support'][0])
        self.assertFalse(audit['independently_verified'])
        self.assertFalse(audit['new_collection'])
        self.assertEqual(enriched['candidates'], before['candidates'])
        self.assertNotIn(BODY, json.dumps(audit))

    def test_safe_official_support_is_preferred_without_reading_other_sources(self):
        value = plan(main=1)
        selected = value['shortlist']['main'][0]
        selected['support'].extend([
            record('unsafe', source_type='official_release', url='https://example.org/?token=secret'),
            record('official', source_type='official_release'),
        ])
        reader = MagicMock(side_effect=response)
        enriched, _ = sources.enrich_selected_sources(value, reader=reader)
        reader.assert_called_once_with('https://publisher.example.org/news/official')
        rows = enriched['shortlist']['main'][0]['support']
        self.assertNotIn('original_read', rows[0])
        self.assertNotIn('original_read', rows[1])
        self.assertEqual(rows[2]['original_read']['status'], 'retrieved')

    def test_unsafe_representative_does_not_dispatch_or_echo_credential_url(self):
        for url in ('http://127.0.0.1/internal', 'https://example.org/?token=secret',
                    'https://user:password@example.org/story', 'file:///etc/passwd'):
            value = plan(main=1)
            value['shortlist']['main'][0]['representative']['url'] = url
            reader = MagicMock(side_effect=AssertionError('No read'))
            enriched, audit = sources.enrich_selected_sources(value, reader=reader)
            reader.assert_not_called()
            read = enriched['shortlist']['main'][0]['support'][0]['original_read']
            self.assertEqual(read, {'status': 'unavailable', 'source_url': '', 'error_code': 'UNSAFE_URL'})
            self.assertEqual(audit['requested_unique_urls'], 0)
            self.assertNotIn('secret', json.dumps(audit))

    def test_official_source_outside_packet_first_three_is_never_read(self):
        value = plan(main=1)
        selected = value['shortlist']['main'][0]
        selected['support'].extend([record('media-2'), record('media-3'),
                                    record('omitted-official', source_type='official_release')])
        reader = MagicMock(side_effect=response)
        enriched, _ = sources.enrich_selected_sources(value, reader=reader)
        reader.assert_called_once_with(selected['representative']['url'])
        rows = enriched['shortlist']['main'][0]['support']
        self.assertEqual(rows[0]['original_read']['status'], 'retrieved')
        self.assertNotIn('original_read', rows[3])

    def test_nonempty_support_omits_representative_that_is_outside_the_packet(self):
        value = plan(main=1)
        value['shortlist']['main'][0]['support'] = [record('actual-packet-source')]
        reader = MagicMock(side_effect=response)
        enriched, _ = sources.enrich_selected_sources(value, reader=reader)
        reader.assert_called_once_with('https://publisher.example.org/news/actual-packet-source')
        selected = enriched['shortlist']['main'][0]
        self.assertNotIn('original_read', selected['representative'])
        self.assertEqual(selected['support'][0]['original_read']['status'], 'retrieved')

    def test_empty_support_falls_back_to_representative(self):
        value = plan(main=1)
        value['shortlist']['main'][0]['support'] = []
        reader = MagicMock(side_effect=response)
        enriched, _ = sources.enrich_selected_sources(value, reader=reader)
        reader.assert_called_once_with(value['shortlist']['main'][0]['representative']['url'])
        self.assertEqual(enriched['shortlist']['main'][0]['representative']['original_read']['status'], 'retrieved')

    def test_one_url_per_event_ten_unique_urls_max_and_no_reserve_reads(self):
        value = plan(main=9, signals=3)
        for selected in value['shortlist']['main'] + value['shortlist']['signals']:
            selected['support'].append(record('unselected-' + selected['event_id']))
        reader = MagicMock(side_effect=response)
        enriched, audit = sources.enrich_selected_sources(value, reader=reader)
        self.assertEqual(reader.call_count, 10)
        self.assertEqual(audit['requested_unique_urls'], 10)
        self.assertEqual(audit['max_workers'], 4)
        for selected in (enriched['shortlist']['main'][8], enriched['shortlist']['signals'][2]):
            self.assertEqual(selected['representative']['original_read']['error_code'], 'SOURCE_READ_BUDGET_EXCEEDED')
        self.assertTrue(all('unselected-' not in call.args[0] for call in reader.call_args_list))
        self.assertNotIn('original_read', enriched['candidates'][0]['representative'])

    def test_duplicate_urls_share_one_read_and_failure_is_not_retried(self):
        value = plan(main=2)
        value['shortlist']['main'][1]['representative']['url'] = value['shortlist']['main'][0]['representative']['url']
        reader = MagicMock(return_value={'ok': False, 'error': {'code': 'RATE_LIMITED', 'message': 'secret provider payload'}})
        enriched, audit = sources.enrich_selected_sources(value, reader=reader)
        self.assertEqual(reader.call_count, 1)
        self.assertEqual(audit['unavailable_unique_urls'], 1)
        for selected in enriched['shortlist']['main']:
            self.assertEqual(selected['representative']['original_read']['error_code'], 'RATE_LIMITED')
        self.assertNotIn('secret', json.dumps(audit))

    def test_concurrency_is_bounded_to_four_readers(self):
        lock, first_four = threading.Lock(), threading.Event()
        active = peak = 0

        def reader(url):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(active, peak)
                if active == 4:
                    first_four.set()
            first_four.wait(2)
            try:
                return response(url)
            finally:
                with lock:
                    active -= 1

        _, audit = sources.enrich_selected_sources(plan(main=8, signals=2), reader=reader)
        self.assertEqual(peak, 4)
        self.assertEqual(audit['retrieved_unique_urls'], 10)

    def test_url_provenance_and_body_limits(self):
        url = record(0)['url']
        cases = [
            (response(url + '-other'), 'PROVENANCE_MISMATCH'),
            (response(url + '?id=7'), 'PROVENANCE_MISMATCH'),
            (response(url, 'short text'), 'INSUFFICIENT_CONTENT'),
            (response(url, 'menu' + (' \n ' * 300) + 'footer'), 'INSUFFICIENT_CONTENT'),
            (response(url, 'Title: Just a moment...\nRequiring CAPTCHA. ' * 30), 'PLATFORM_BLOCKED'),
            (response(url, 'Sign in to continue. ' * 30), 'PLATFORM_BLOCKED'),
        ]
        for result, code in cases:
            enriched, _ = sources.enrich_selected_sources(plan(main=1), reader=lambda _: result)
            read = enriched['shortlist']['main'][0]['representative']['original_read']
            self.assertEqual(read['error_code'], code)
            self.assertNotIn('excerpt', read)
        enriched, _ = sources.enrich_selected_sources(
            plan(main=1), reader=lambda _: response(url + '?utm_source=fixture', BODY * 20))
        read = enriched['shortlist']['main'][0]['representative']['original_read']
        self.assertEqual(len(read['excerpt']), 6000)
        self.assertEqual(read['source_url'], url)

    def test_terminal_errors_and_exceptions_are_safe_evidence_gaps(self):
        for code in ('PLATFORM_BLOCKED', 'NEED_LOGIN', 'RATE_LIMITED', 'TIMEOUT',
                     'a secret credential', ['invalid-code']):
            reader = MagicMock(return_value={'ok': False, 'error': {'code': code, 'message': BODY}})
            enriched, audit = sources.enrich_selected_sources(plan(main=1), reader=reader)
            read = enriched['shortlist']['main'][0]['representative']['original_read']
            self.assertEqual(reader.call_count, 1)
            self.assertEqual(read['status'], 'unavailable')
            self.assertNotIn('excerpt', read)
            self.assertNotIn('secret', json.dumps(audit))
        reader = MagicMock(side_effect=RuntimeError('provider token=secret'))
        enriched, audit = sources.enrich_selected_sources(plan(main=1), reader=reader)
        self.assertEqual(enriched['shortlist']['main'][0]['representative']['original_read']['error_code'], 'READ_FAILED')
        self.assertNotIn('secret', json.dumps(audit))


class WeeklySourceScriptTests(unittest.TestCase):
    def test_script_retains_private_audit_and_uses_enriched_plan_without_extra_model_calls(self):
        spec = importlib.util.spec_from_file_location('weekly_source_script', ROOT / 'scripts/generate_weekly_review.py')
        script = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script)
        original = plan()
        enriched, audit = sources.enrich_selected_sources(original, reader=response)
        records = [deepcopy(selected['representative']) for selected in original['shortlist']['main']]
        packet = {'main_events': [{'evidence_ids': [row['id']]} for row in records], 'early_signals': []}
        model = MagicMock(model='offline-model', calls=[])
        with tempfile.TemporaryDirectory(dir=ROOT / 'output') as directory, \
                patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'WEEK_START': '2026-11-09', 'GITHUB_STEP_SUMMARY': ''}), \
                patch.object(script, 'load_cloud_archive', return_value=[]), \
                patch.object(script, 'prepare_records', return_value=(records, [])), \
                patch.object(script, 'known_archive_urls', return_value={}), \
                patch.object(script, 'render_coverage', return_value={}), \
                patch('weekly_editorial.build_weekly_plan', return_value={**original, 'candidates': []}), \
                patch('weekly_source_reads.enrich_selected_sources', return_value=(enriched, audit)) as reads, \
                patch('weekly_generation.CloudGemini', return_value=model), \
                patch('weekly_generation.generate_review', return_value=({'editorial_review': {}}, packet)) as generate, \
                patch('weekly_render.render_review', return_value={'en': '<p>Review</p>', 'zh': '<p>周报</p>'}), \
                patch('weekly_render.to_markdown', return_value='Review'):
            self.assertEqual(script.main(['--output', directory]), 0)
            reads.assert_called_once()
            self.assertIs(generate.call_args.args[0], enriched)
            self.assertEqual(generate.call_count, 1)
            self.assertEqual(json.loads((Path(directory) / 'source-read-audit.json').read_text()), audit)
            catalog = json.loads((Path(directory) / 'source-catalog.json').read_text())
            self.assertTrue(all(row['original_read']['status'] == 'retrieved' for row in catalog))
            metadata = json.loads((Path(directory) / 'generation-metadata.json').read_text())
            self.assertEqual(metadata['original_source_reads']['retrieved_unique_urls'], 3)
            self.assertFalse(metadata['article_writes'])
        self.assertTrue(all('original_read' not in row for row in records))


if __name__ == '__main__':
    unittest.main()
