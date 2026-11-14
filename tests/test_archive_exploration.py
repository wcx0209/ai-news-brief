import copy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from archive_exploration import normalize_tag, related_articles, topic_labels


NOW = datetime(2026, 11, 14, 12, tzinfo=timezone.utc)


def article(identifier, title, days=0, tags=None, source="Publisher A", **changes):
    published = NOW - timedelta(days=days)
    record = {
        "id": identifier, "url": f"https://example.org/{identifier}", "source": source,
        "domain": "ai", "tags": tags if tags is not None else ["gemini", "tool use", "ai"],
        "published": published, "source_published": published, "site_published": published,
        "en": {"title": title}, "zh": {"title": ""}, "importance": 80,
    }
    record.update(changes)
    return record


class ArchiveExplorationTests(unittest.TestCase):
    def setUp(self):
        self.current = article("current", "Gemini 3 improves tool-use evaluations", days=3)
        self.background = article("background", "Gemini 2 introduces tool use in a published benchmark", days=8)
        self.recent = article("recent", "Gemini expands the tool-use suite with browser tasks", days=1)
        self.perspective = article("perspective", "An outside Gemini tool-use test reports uneven task results", days=3, source="Publisher B")

    def test_normalization_is_unicode_aware_and_does_not_guess_synonyms(self):
        self.assertEqual(normalize_tag("  #ＡＩ–Agents  "), "ai agents")
        self.assertEqual(normalize_tag("GPT_5.1"), "gpt 5 1")
        self.assertEqual(normalize_tag(" 脑机接口 "), "脑机接口")
        self.assertEqual(normalize_tag("C++"), "c++")
        self.assertEqual(normalize_tag(None), "")
        self.assertNotEqual(normalize_tag("brain computer interface"), normalize_tag("脑机接口"))

    def test_roles_are_chronological_and_other_source_is_not_claimed_independent(self):
        values = related_articles(self.current, [self.current, self.background, self.recent, self.perspective], now=NOW)
        self.assertEqual([(x["record"]["id"], x["kind"]) for x in values], [
            ("background", "background"), ("recent", "recent"), ("perspective", "perspective")])
        self.assertEqual(values[0]["shared_tags"], ["gemini", "tool use"])
        self.assertLess(values[0]["record"]["published"], self.current["published"])
        self.assertGreater(values[1]["record"]["published"], self.current["published"])
        self.assertNotEqual(values[2]["record"]["source"], self.current["source"])

    def test_all_future_timestamp_variants_are_excluded(self):
        for key in ("published", "source_published", "site_published", "published_at", "source_published_at", "site_published_at", "created_at", "first_seen_at"):
            with self.subTest(key=key):
                candidate = dict(self.background, **{key: (NOW + timedelta(hours=1)).isoformat()})
                self.assertEqual(related_articles(self.current, [candidate], now=NOW), [])
        future_current = dict(self.current, site_published=NOW + timedelta(seconds=1))
        self.assertEqual(related_articles(future_current, [self.background], now=NOW), [])

    def test_self_tracking_urls_internal_canonical_urls_and_near_duplicates_are_excluded(self):
        canonical = dict(self.background, url=self.current["url"] + "/?utm_source=test&fbclid=x#fragment")
        same_id = dict(self.background, id="current")
        internal = dict(self.background, canonical_urls={"en": "https://polyemergence.com/en/archive/item/"})
        current = dict(self.current, canonical_urls={"en": "https://polyemergence.com/en/archive/item/?utm_medium=social"})
        duplicate = article("duplicate", "GEMINI 3 improves tool use evaluations!")
        self.assertEqual(related_articles(current, [canonical, same_id, internal, duplicate], now=NOW), [])

    def test_generic_tags_and_cross_domain_overlap_do_not_create_related_items(self):
        generic_current = dict(self.current, tags=["AI", "news", "company", "research", "models"])
        generic = dict(self.background, tags=["ai", "news", "company", "research", "models"])
        self.assertEqual(related_articles(generic_current, [generic], now=NOW), [])
        self.assertEqual(related_articles(self.current, [dict(self.background, domain="quantum_technology")], now=NOW), [])

    def test_single_product_tag_requires_exact_title_token_evidence(self):
        current = dict(self.current, tags=["gemini"])
        candidate = dict(self.background, tags=["Gemini"])
        self.assertEqual(len(related_articles(current, [candidate], now=NOW)), 1)
        unrelated = dict(candidate, en={"title": "GeminiCraft expands its unrelated enterprise service"})
        self.assertEqual(related_articles(current, [unrelated], now=NOW), [])
        unknown = dict(candidate, tags=["batteries"], en={"title": "Batteries in a new business report"})
        self.assertEqual(related_articles(dict(current, tags=["batteries"], en={"title": "Batteries and broader financial demand"}), [unknown], now=NOW), [])

    def test_company_alone_does_not_link_unrelated_stories(self):
        current = article("a", "NVIDIA announces a CUDA compiler capability", tags=["nvidia"])
        unrelated = article("b", "NVIDIA quarterly earnings exceed expectations", days=1, tags=["nvidia"])
        related = article("c", "NVIDIA documents CUDA debugging constraints", days=2, tags=["nvidia"])
        self.assertEqual(related_articles(current, [unrelated], now=NOW), [])
        self.assertEqual(related_articles(current, [related], now=NOW)[0]["record"]["id"], "c")
        generic_current = dict(current, en={"title": "NVIDIA artificial intelligence financial forecast"})
        generic_other = dict(unrelated, en={"title": "NVIDIA brings artificial intelligence to consumer headphones"})
        self.assertEqual(related_articles(generic_current, [generic_other], now=NOW), [])

    def test_same_source_url_candidates_and_similar_recommendations_do_not_repeat(self):
        duplicate_url = dict(self.recent, id="recent2", url=self.background["url"] + "?utm_campaign=x")
        values = related_articles(self.current, [self.background, duplicate_url], now=NOW)
        self.assertEqual(len(values), 1)
        duplicate_title = dict(self.perspective, en={"title": self.background["en"]["title"] + "!"})
        values = related_articles(self.current, [self.background, duplicate_title], now=NOW)
        self.assertEqual(len(values), 1)

    def test_result_is_deterministic_sparse_and_does_not_mutate_records(self):
        records = [self.background, self.recent, self.perspective]
        before = copy.deepcopy(records)
        expected = related_articles(self.current, records, now=NOW)
        for _ in range(5):
            random.Random(27 + _).shuffle(records)
            self.assertEqual(related_articles(self.current, records, now=NOW), expected)
        self.assertEqual(sorted(records, key=lambda x: x["id"]), sorted(before, key=lambda x: x["id"]))
        self.assertEqual(len(related_articles(self.current, [self.background], now=NOW)), 1)
        self.assertEqual(related_articles(self.current, [], now=NOW), [])
        self.assertEqual(related_articles(self.current, records, now=NOW, limit=0), [])
        self.assertEqual(len(related_articles(self.current, records, now=NOW, limit=1)), 1)

    def test_public_feed_dates_are_supported(self):
        def public(record):
            value = dict(record)
            for key in ("published", "source_published", "site_published"):
                value[key + "_at"] = value.pop(key).isoformat().replace("+00:00", "Z")
            return value
        values = related_articles(public(self.current), [public(self.background)], now=NOW.isoformat())
        self.assertEqual(values[0]["kind"], "background")

    def test_topic_labels_require_two_distinct_articles_exclude_future_and_are_stable(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        first = article("a", "One subject", tags=["AI", "AI Agents", "single"], published=old, source_published=old, site_published=old)
        second = article("b", "Another subject", tags=["news", "ai-agents"], published=old, source_published=old, site_published=old)
        same = dict(first, id="c", url=first["url"] + "?utm_source=copy")
        future = article("future", "Future subject", tags=["single"], published_at="2099-01-01T00:00:00Z")
        values = topic_labels([first, second, same, future])
        self.assertEqual(values, [{"tag": "ai agents", "label": "AI Agents", "count": 2}])
        self.assertEqual(topic_labels([future, same, second, first]), values)
        self.assertEqual(topic_labels([first]), [])
        self.assertEqual(topic_labels([first, second], limit=0), [])

    def test_topic_labels_duplicate_rows_and_cap_are_input_order_independent(self):
        old = datetime(2020, 1, 1, tzinfo=timezone.utc)
        tags = [f"topic {number}" for number in range(10)]
        first = article("a", "One subject", tags=tags, published=old, source_published=old, site_published=old)
        second = article("b", "Another subject", tags=tags, published=old, source_published=old, site_published=old)
        alternate = dict(first, tags=["unshared subject"])
        values = topic_labels([first, second, alternate], limit=20)
        self.assertEqual(len(values), 8)
        self.assertEqual(topic_labels([alternate, second, first], limit=20), values)


if __name__ == "__main__":
    unittest.main()
