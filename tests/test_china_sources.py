import os
import sys
import unittest
from collections import Counter
from unittest.mock import MagicMock, patch

from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

from editorial_domains import domains, source_category_domain
from relevance_filter import passes_source_ai_filter
from rss_fetcher import RSSFetcher, OFFICIAL_HTML_INDEX_RULES
from source_catalog import china_sources, china_source_tuples, load_seed_catalog


class ChinaSourceCatalogTests(unittest.TestCase):
    def test_every_non_ai_field_has_at_least_three_chinese_specialist_sources(self):
        counts = Counter(source_category_domain(source["category"]) for source in china_sources())
        for domain in domains():
            if domain["id"] != "ai":
                self.assertGreaterEqual(counts[domain["id"]], 3, domain["id"])

    def test_sources_have_unique_urls_and_explicit_provenance(self):
        sources = china_sources()
        self.assertEqual(len({source["url"] for source in sources}), len(sources))
        self.assertEqual(len({source["name"] for source in sources}), len(sources))
        for source in sources:
            with self.subTest(source=source["name"]):
                self.assertEqual(source["region"], "CN")
                self.assertIn(source["kind"], ("company", "research", "government", "media"))
                self.assertTrue(source["url"].startswith("https://"))
                self.assertRegex(source["verified_on"], r"^20\d{2}-\d{2}-\d{2}$")
                self.assertIn("[REGION:CN]", next(row[2] for row in china_source_tuples() if row[0] == source["url"]))
                self.assertFalse(passes_source_ai_filter(source["name"], "新春慰问暨职工文体活动圆满结束"))
                if source.get("html"):
                    rule = OFFICIAL_HTML_INDEX_RULES[source["url"].rstrip("/")]
                    self.assertEqual(rule["timezone"], "Asia/Shanghai")
                    self.assertFalse(rule["browser_fallback"])
                    self.assertLessEqual(rule["max_index_links"], 8)

    def test_catalog_is_included_in_idempotent_cloud_seed(self):
        from bootstrap_sources import SOURCES
        self.assertTrue(set(china_source_tuples()).issubset(set(SOURCES)))
        self.assertEqual(len(SOURCES), len({source[0] for source in SOURCES}))
        self.assertEqual(load_seed_catalog(os.path.join(ROOT, "scripts/bootstrap_sources.py")), SOURCES)

    def test_new_official_sources_are_labelled_first_party_in_public_exports(self):
        from editorial_insights import evidence_type
        for source in china_sources():
            if source["kind"] != "media":
                with self.subTest(source=source["name"]):
                    self.assertEqual(evidence_type({"source": source["name"], "url": source["url"]}), "official_release")


class ChineseHtmlAdapterTests(unittest.TestCase):
    def test_chinese_metadata_date_uses_beijing_time(self):
        soup = BeautifulSoup('<meta name="PubDate" content="2026-11-14 18:30:00">', "html.parser")
        self.assertEqual(RSSFetcher._official_page_date(soup, "Asia/Shanghai"), "2026-11-14T10:30:00+00:00")

    def test_explicit_offset_is_preserved(self):
        soup = BeautifulSoup('<meta name="PubDate" content="2026-11-14 18:30:00+08:00">', "html.parser")
        self.assertEqual(RSSFetcher._official_page_date(soup, "Asia/Shanghai"), "2026-11-14T10:30:00+00:00")

    def test_chinese_and_dotted_dates_and_single_digit_months(self):
        for raw in ("2026年1月4日", "2026.01.04", "2026/1/4"):
            with self.subTest(raw=raw):
                soup = BeautifulSoup(f'<div class="pubdate">发布时间：{raw}</div>', "html.parser")
                self.assertEqual(RSSFetcher._official_page_date(soup, "Asia/Shanghai", ".pubdate"), "2026-01-03T16:00:00+00:00")

    def test_missing_date_never_becomes_fetch_time(self):
        self.assertIsNone(RSSFetcher._official_page_date(BeautifulSoup("<h1>量子计算进展</h1>", "html.parser"), "Asia/Shanghai"))

    def test_broken_publisher_date_selector_never_uses_body_event_date(self):
        soup = BeautifulSoup('<h1>研究进展</h1><p>本研究曾于2026-11-14举办研讨会。</p>', "html.parser")
        self.assertIsNone(RSSFetcher._official_page_date(soup, "Asia/Shanghai", ".publisher-date"))

    def test_broken_date_selector_never_uses_sidebar_time_or_other_article_jsonld(self):
        soup = BeautifulSoup('''<h1>无日期稿件</h1><aside><time datetime="2026-11-14T09:00:00+08:00">推荐稿</time>
            <script type="application/ld+json">{"@type":"NewsArticle","datePublished":"2026-11-14T10:00:00+08:00"}</script></aside>''', "html.parser")
        self.assertIsNone(RSSFetcher._official_page_date(soup, "Asia/Shanghai", ".publisher-date"))

    def test_scoped_abbreviated_english_date(self):
        soup = BeautifulSoup('<p class="publisher-date">Nov. 05, 2026</p>', "html.parser")
        self.assertEqual(RSSFetcher._official_page_date(soup, "Asia/Shanghai", ".publisher-date"), "2026-11-04T16:00:00+00:00")

    def test_scoped_split_publication_date_does_not_use_image_upload_date(self):
        soup = BeautifulSoup('''<div class="post-date"><div>2026</div><div>11/14</div><div>18:30</div></div>
            <div>图片上传日期：2026-11-15</div>''', "html.parser")
        self.assertEqual(RSSFetcher._official_page_date(soup, "Asia/Shanghai", ".post-date"), "2026-11-14T10:30:00+00:00")

    def test_article_pattern_and_list_scope_exclude_cms_navigation(self):
        soup = BeautifulSoup('''<div class="list">
            <a href="/research/index_1.shtml">下一页</a>
            <a href="/research/202611/t20261114_123.shtml">研究进展</a>
            <a href="https://elsewhere.example/research/202611/t20261114_124.shtml">外站</a>
            </div><footer><a href="/research/202601/t20260101_999.shtml">旧稿</a></footer>''', "html.parser")
        urls = RSSFetcher._discover_official_article_urls(soup, "https://lab.example/research/", ("/research/",),
            article_url_pattern=r"/t\d{8}_\d+\.shtml$", article_selector=".list a[href]")
        self.assertEqual(urls, ["https://lab.example/research/202611/t20261114_123.shtml"])

    def test_preserves_query_identifiers_for_chinese_company_pages(self):
        soup = BeautifulSoup('<a href="/news-detail.html?itemid=78&utm_source=home">火箭新闻</a>', "html.parser")
        urls = RSSFetcher._discover_official_article_urls(soup, "https://space.example/news.html", ("/news-detail.html",), keep_query_keys=("itemid",))
        self.assertEqual(urls, ["https://space.example/news-detail.html?itemid=78"])

    def test_legacy_same_host_http_links_use_the_verified_https_origin(self):
        soup = BeautifulSoup('<a href="http://lab.example/news/one.html">技术新闻</a>', "html.parser")
        self.assertEqual(RSSFetcher._discover_official_article_urls(soup, "https://lab.example/news/", ("/news/",)),
                         ["https://lab.example/news/one.html"])

    def test_list_date_is_bound_to_its_own_article_not_an_adjacent_card(self):
        soup = BeautifulSoup('''<div class="card"><a href="/news/one.html">One</a><time>2026-11-14</time></div>
            <div class="card"><a href="/news/two.html">Two</a><time>2026-11-12</time></div>
            <footer>2026-11-15</footer>''', "html.parser")
        dates = RSSFetcher._official_index_dates(soup, "https://lab.example/news", {
            "path_prefixes": ("/news/",), "index_item_selector": ".card", "index_date_selector": "time", "timezone": "Asia/Shanghai"})
        self.assertEqual(dates, {"https://lab.example/news/one.html": "2026-11-13T16:00:00+00:00",
                                 "https://lab.example/news/two.html": "2026-11-11T16:00:00+00:00"})

    def test_browserless_adapter_reads_trs_title_body_and_date(self):
        index = MagicMock(text='<a href="/research/t20261114_123.shtml">研究</a>', url="https://lab.example/research/")
        article = MagicMock(text='''<meta name="ArticleTitle" content="研究团队突破脑机接口技术">
            <meta name="PubDate" content="2026-11-14 12:00:00">
            <div class="TRS_Editor"><p>这是研究机构发布的真实研究正文。</p></div>''')
        fetcher = RSSFetcher([])
        rule = {"path_prefixes": ("/research/",), "timezone": "Asia/Shanghai", "browser_fallback": False, "max_articles": 1}
        with patch("curl_cffi.requests.get", side_effect=[index, article]), patch.object(fetcher, "_get_browser_unlocked") as browser:
            result = fetcher._fetch_official_html_index({"url": "https://lab.example/research/", "name": "Research"}, rule)
        self.assertIsNone(result["error"])
        self.assertEqual(len(result["entries"]), 1)
        self.assertEqual(result["entries"][0]["published_at"], "2026-11-14T04:00:00+00:00")
        self.assertEqual(result["entries"][0]["title"], "研究团队突破脑机接口技术")
        self.assertIn("真实研究正文", result["entries"][0]["official_content"])
        browser.assert_not_called()

    def test_new_chinese_technical_headlines_pass_relevance_gate(self):
        names = [source["name"] for source in china_sources()]
        for title in ("钙钛矿太阳能电池取得进展", "团队完成火箭回收验证", "碳捕集与污水处理技术突破", "智慧农业与生物育种平台发布", "智能制造与工业自动化应用", "三维打印复合材料新工艺"):
            with self.subTest(title=title):
                self.assertTrue(passes_source_ai_filter(names[0], title))

    def test_verified_materials_headlines_are_not_lost_after_healthy_html_parsing(self):
        examples = (
            ("CAS Institute of Metal Research", "固体晶格动力学研究取得重要进展"),
            ("CAS Shanghai Institute of Ceramics", "提出超导临界温度新模型"),
            ("CAS Ningbo Institute of Materials Technology and Engineering", "生物基呋喃二甲酸中试生产取得阶段性进展"),
            ("CAAS Institute of Plant Protection 中国农科院植保所", "植保所破解植保无人飞机飘移预测黑箱密码"),
        )
        for source, title in examples:
            with self.subTest(title=title):
                self.assertTrue(passes_source_ai_filter(source, title))

    def test_cloud_verified_technical_vocabulary_is_kept_without_admitting_generic_pr(self):
        examples = (
            ("CAS Institute of Urban Environment 城市环境研究所", "城市环境研究所在重金属修复重塑土壤碳循环取得进展"),
            ("Beijing Academy of Quantum Information Sciences", "我院与合作单位量子编译成果在国际顶会MICRO 2026上获奖"),
            ("CNQT 量科网", "香港科技大学与金管局推出后量子密码学工具包"),
            ("Farsoon Technologies 华曙高科", "Farsoon introduces FS4X built around the demands of series production"),
            ("Nanjixiong 南极熊3D打印", "罗切斯特大学用450美元DIY生物打印机，打印超100层复杂活体结构"),
        )
        for source, title in examples:
            with self.subTest(title=title):
                self.assertTrue(passes_source_ai_filter(source, title))
        self.assertFalse(passes_source_ai_filter("Gotion High-Tech 国轩高科", "连获两项一等奖，企业创新奖揭晓"))
        self.assertFalse(passes_source_ai_filter("SIASUN 新松机器人", "预告：我司即将参加亚洲国际物流展"))


if __name__ == "__main__":
    unittest.main()
