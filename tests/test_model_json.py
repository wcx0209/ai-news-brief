"""Offline parser and mocked cloud-client response preservation contracts."""

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from model_json import MAX_RESPONSE_CHARS, parse_json_response
import weekly_generation


class ModelJSONTests(unittest.TestCase):
    def test_plain_object_and_whitespace_keep_actual_values(self):
        self.assertEqual(parse_json_response(' \n{"zh":{"text":"原始文字"},"value":2.5,"ok":true}\t'),
                         {'zh': {'text': '原始文字'}, 'value': 2.5, 'ok': True})

    def test_complete_json_fence_is_the_only_wrapper_removed(self):
        for source in ('```json\n{"text":"An unchanged claim."}\n```',
                       '\r\n```JSON \r\n{"text":"An unchanged claim."}\r\n``` \r\n'):
            with self.subTest(source=source):
                self.assertEqual(parse_json_response(source), {'text': 'An unchanged claim.'})

    def test_does_not_extract_objects_or_repair_prose_and_punctuation(self):
        for source in ('Here is the JSON:\n{}', '{}\nThanks', '{} {}',
                       '```json\n{}\n```\nThanks', '```json\n{}',
                       '```\n{}\n```', '```python\n{}\n```',
                       '````json\n{}\n```', '```json\n{}\n````',
                       '{"text":"claim",}', '{"first":1 "second":2}',
                       '{"text": "raw\nnewline"}', '{"text": “smart quotes”}'):
            with self.subTest(source=source), self.assertRaises(ValueError):
                parse_json_response(source)

    def test_rejects_root_arrays_scalars_and_nontext(self):
        for value in ('[]', '[{}]', 'null', 'true', '17', '"text"', None, {}, b'{}', 7):
            with self.subTest(value=value), self.assertRaises(ValueError):
                parse_json_response(value)

    def test_rejects_duplicate_keys_including_nested_and_escaped_spellings(self):
        for source in ('{"a":1,"a":2}', '{"a":{"b":1,"b":2}}',
                       '{"a":1,"\\u0061":2}'):
            with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'duplicate_key'):
                parse_json_response(source)

    def test_rejects_nonfinite_constants_and_overflow(self):
        for value in ('NaN', 'Infinity', '-Infinity', '1e10000', '-1e10000'):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'non_finite_number'):
                parse_json_response('{"value":' + value + '}')

    def test_retains_missing_fields_for_downstream_validation(self):
        self.assertEqual(parse_json_response('{}'), {})
        with self.assertRaisesRegex(ValueError, 'weekly_missing_locale'):
            weekly_generation.validate_draft(parse_json_response('{}'),
                                             {'main_events': [], 'early_signals': []})

    def test_response_size_is_bounded_and_error_does_not_expose_text(self):
        boundary = '{"a":"' + 'x' * (MAX_RESPONSE_CHARS - 8) + '"}'
        self.assertEqual(len(boundary), MAX_RESPONSE_CHARS)
        self.assertEqual(len(parse_json_response(boundary)['a']), MAX_RESPONSE_CHARS - 8)
        secret = 'private-provider-response'
        with self.assertRaises(ValueError) as caught:
            parse_json_response(secret + ' ' * MAX_RESPONSE_CHARS)
        self.assertEqual(str(caught.exception), 'model_json_response_too_large')
        self.assertNotIn(secret, str(caught.exception))
        with self.assertRaises(ValueError) as invalid:
            parse_json_response('invalid ' + secret)
        self.assertEqual(str(invalid.exception), 'model_json_invalid_json')


class WeeklyCloudResponseTests(unittest.TestCase):
    def setUp(self):
        self.sdk = MagicMock()
        self.response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=11, completion_tokens=22, total_tokens=33),
            choices=[SimpleNamespace(finish_reason='stop', message=SimpleNamespace(content='{}'))],
        )
        self.sdk.OpenAI.return_value.chat.completions.create.return_value = self.response
        self.environ = patch.dict(os.environ, {'GITHUB_ACTIONS': 'true',
                                              'INBRIEF_LLM_API_KEY': 'offline-only-fixture'})
        self.sdk_patch = patch.dict(sys.modules, {'openai': self.sdk})
        self.sleep_patch = patch.object(weekly_generation.time, 'sleep')
        self.clock_patch = patch.object(weekly_generation.time, 'monotonic', return_value=1000)
        for context in (self.environ, self.sdk_patch, self.sleep_patch, self.clock_patch):
            context.start()
            self.addCleanup(context.stop)
        self.client = weekly_generation.CloudGemini()

    def assert_response_metadata_preserved(self):
        self.assertEqual(self.client.calls[0]['usage'],
                         {'input_tokens': 11, 'output_tokens': 22, 'total_tokens': 33})
        self.assertIn('finish_reason', self.client.calls[0])
        self.assertEqual(self.sdk.OpenAI.return_value.chat.completions.create.call_count, 1)

    def test_successful_fence_is_retained_verbatim_before_parse(self):
        text = '```json\n{"actual":"claim"}\n```'
        self.response.choices[0].message.content = text
        self.assertEqual(self.client('fixture', {}, 'draft'), {'actual': 'claim'})
        self.assertEqual(self.client.raw_responses,
                         [{'purpose': 'draft', 'text': text, 'finish_reason': 'stop'}])
        self.assert_response_metadata_preserved()

    def test_invalid_json_retains_exact_paid_output_without_new_request(self):
        text = '{"actual":"claim",}'
        self.response.choices[0].message.content = text
        with self.assertRaisesRegex(ValueError, 'model_json_invalid_json'):
            self.client('fixture', {}, 'draft')
        self.assertEqual(self.client.raw_responses,
                         [{'purpose': 'draft', 'text': text, 'finish_reason': 'stop'}])
        self.assert_response_metadata_preserved()

    def test_nonstring_and_oversize_are_not_forwarded_to_private_artifact(self):
        for value in (None, {'not': 'text'}, 'a' * (MAX_RESPONSE_CHARS + 1)):
            with self.subTest(value_type=type(value).__name__):
                self.client.calls.clear()
                self.client.raw_responses.clear()
                self.sdk.OpenAI.return_value.chat.completions.create.reset_mock()
                self.response.choices[0].message.content = value
                with self.assertRaisesRegex(ValueError, 'weekly_cloud_(response_must_be_text|raw_response_too_large)'):
                    self.client('fixture', {}, 'draft')
                self.assertEqual(self.client.raw_responses, [])
                self.assert_response_metadata_preserved()

    def test_incomplete_output_is_retained_but_never_parsed_as_finished(self):
        for reason in ('length', 'content_filter', None):
            with self.subTest(reason=reason):
                self.client.calls.clear()
                self.client.raw_responses.clear()
                self.response.choices[0].finish_reason = reason
                self.response.choices[0].message.content = '{"partial":"text"}'
                with self.assertRaisesRegex(ValueError, 'weekly_cloud_output_(truncated|incomplete)'):
                    self.client('fixture', {}, 'draft')
                self.assertEqual(self.client.raw_responses[0]['finish_reason'], reason)

    def test_four_calls_and_four_raw_responses_remain_the_absolute_bound(self):
        self.response.choices[0].message.content = 'not json'
        for index in range(4):
            with self.assertRaises(ValueError):
                self.client('fixture', {}, 'attempt-' + str(index))
        with self.assertRaisesRegex(RuntimeError, 'weekly_llm_call_budget_exhausted'):
            self.client('fixture', {}, 'forbidden-fifth')
        self.assertEqual(len(self.client.raw_responses), 4)
        self.assertEqual(len(self.client.calls), 4)
        self.assertEqual(self.sdk.OpenAI.return_value.chat.completions.create.call_count, 4)
        self.assertEqual(self.sdk.OpenAI.call_args.kwargs['max_retries'], 0)
        request = self.sdk.OpenAI.return_value.chat.completions.create.call_args.kwargs
        self.assertEqual(request['timeout'], 180)
        self.assertEqual(request['max_tokens'], 10000)


if __name__ == '__main__':
    unittest.main()
