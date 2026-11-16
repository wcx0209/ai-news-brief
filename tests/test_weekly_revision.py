from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('weekly_revision', ROOT / 'scripts/revise_weekly_review.py')
revision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(revision)


class WeeklyRevisionTests(unittest.TestCase):
    def test_no_local_llm_revision_or_file_generation(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'false'}), self.assertRaises(SystemExit):
            revision.main(['--input', 'output/fixture'])

    def test_supplement_requires_exact_event_and_does_not_mutate_input(self):
        packet = {'issue': {'week_start': '2026-11-09'}, 'source_scope': 'Existing summary.',
                  'main_events': [{'event_id': 'event-a', 'evidence_ids': ['source-a'], 'evidence': []}],
                  'early_signals': []}
        original = deepcopy(packet)
        corrections = {'week_start': '2026-11-09', 'supplemental_sources': [
            {'id': 'official-a', 'target_evidence_id': 'source-a', 'source': 'Official lab',
             'published_at': '2026-11-12', 'url': 'https://example.com/notice',
             'en': {'summary': 'A notice.'}, 'zh': {'summary': '一份公告。'}}]}
        revised, catalog = revision.prepare_revision(packet, [], corrections)
        self.assertEqual(packet, original)
        self.assertEqual(revised['main_events'][0]['evidence_ids'], ['source-a', 'official-a'])
        self.assertEqual(catalog[0]['id'], 'official-a')
        corrections['supplemental_sources'][0]['target_evidence_id'] = 'not-in-packet'
        with self.assertRaises(ValueError):
            revision.prepare_revision(packet, [], corrections)

    def test_cannot_apply_another_weeks_review_notes(self):
        with self.assertRaises(ValueError):
            revision.prepare_revision({'issue': {'week_start': '2026-11-09'}}, [], {'week_start': '2026-11-02'})


if __name__ == '__main__':
    unittest.main()
