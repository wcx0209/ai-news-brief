"""Offline SimHash compatibility, including NumPy 2's uint8 weight boundary."""

from collections import Counter
import hashlib
from pathlib import Path
import re
import sys
import unittest

from simhash import Simhash

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

from lsh_dedup import compute_simhash


def signed64(value):
    return value - (1 << 64) if value >= (1 << 63) else value


def reference_simhash(text):
    """Integer-only reference to the existing library's exact 64-bit vote."""
    if not text or not text.strip():
        return 0
    normalized = ''.join(re.findall(r'[\w\u4e00-\u9fcc]+', text.lower()))
    features = Counter(normalized[index:index + 4]
                       for index in range(max(len(normalized) - 3, 1)))
    votes = [0] * 64
    total = sum(features.values())
    for feature, weight in features.items():
        digest = int.from_bytes(hashlib.md5(feature.encode('utf-8')).digest()[-8:], 'big')
        for bit in range(64):
            if digest & (1 << bit):
                votes[bit] += weight
    return signed64(sum(1 << bit for bit, vote in enumerate(votes) if 2 * vote > total))


class SimHashCompatibilityTests(unittest.TestCase):
    def test_fixed_existing_english_and_chinese_fingerprints_are_unchanged(self):
        fixtures = (
            ('Polyemergence tracks emerging technology.', -3241462291254705799),
            ('OpenAI releases a new model for scientific discovery.', 3142041647829769260),
            ('中国科研团队发布新型脑机接口研究成果。', -2250385221839927834),
            ('Models, companies, startups, research, open source, policy, business and society.', -309284096813212551),
        )
        for text, expected in fixtures:
            with self.subTest(text=text):
                self.assertEqual(signed64(Simhash(text).value), expected)
                self.assertEqual(compute_simhash(text), expected)
                self.assertEqual(reference_simhash(text), expected)

    def test_frequency_475_does_not_overflow_numpy_uint8(self):
        # 478 characters yield the single 'aaaa' feature with frequency 475.
        text = 'a' * 478
        self.assertEqual(compute_simhash(text), -3224717227156716059)
        self.assertEqual(compute_simhash(text), reference_simhash(text))

    def test_large_mixed_weights_and_multiple_library_batches_match_exact_votes(self):
        fixtures = (
            ('the model ' * 1200) + ('robot ' * 700) + ('quantum ' * 500),
            ' '.join(f'item{index}' for index in range(500)),
            ('人工智能模型研究' * 600) + ('脑机接口' * 300),
        )
        for text in fixtures:
            with self.subTest(length=len(text)):
                actual = compute_simhash(text)
                self.assertEqual(actual, reference_simhash(text))
                self.assertGreaterEqual(actual, -(1 << 63))
                self.assertLess(actual, 1 << 63)

    def test_prior_working_weight_boundaries_still_match_the_original_library(self):
        for frequency in (1, 49, 50, 51, 200, 254, 255):
            text = 'a' * (frequency + 3)
            with self.subTest(frequency=frequency):
                self.assertEqual(compute_simhash(text), signed64(Simhash(text).value))

    def test_normalization_short_text_and_tied_votes_remain_compatible(self):
        for text in ('A', 'ab', 'abc', 'abcd', 'abcde', 'aBc D! e', '!!!', 'ＡＩ 模型', 'İstanbul research'):
            with self.subTest(text=text):
                self.assertEqual(compute_simhash(text), signed64(Simhash(text).value))
                self.assertEqual(compute_simhash(text), reference_simhash(text))

    def test_empty_input_and_global_library_configuration_are_unchanged(self):
        cutoff = Simhash.large_weight_cutoff
        for text in (None, '', '  \n\t '):
            self.assertEqual(compute_simhash(text), 0)
        compute_simhash('a' * 478)
        self.assertEqual(Simhash.large_weight_cutoff, cutoff)
        self.assertEqual(Simhash(0).large_weight_cutoff, cutoff)


if __name__ == '__main__':
    unittest.main()
