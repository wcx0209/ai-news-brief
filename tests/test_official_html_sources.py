import json
import os
import sys
import unittest

from bs4 import BeautifulSoup


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from rss_fetcher import RSSFetcher


class OfficialHtmlSourceTests(unittest.TestCase):
    def test_discovers_same_domain_articles_and_rejects_navigation(self):
        soup = BeautifulSoup(
            """
            <a href="/news/model-one">Model one</a>
            <a href="/news/model-one?utm_source=home">Duplicate</a>
            <a href="/news/page/2/">Pagination</a>
            <a href="https://example.org/news/copied">External</a>
            <a href="/company">Company</a>
            """,
            "html.parser",
        )

        urls = RSSFetcher._discover_official_article_urls(
            soup, "https://vendor.example/news", ("/news/",)
        )

        self.assertEqual(urls, ["https://vendor.example/news/model-one"])

    def test_preserves_qwen_article_identifier(self):
        soup = BeautifulSoup(
            """
            <a href="/blog?id=qwen-one&utm_source=home">One</a>
            <a href="/blog?id=qwen-two">Two</a>
            """,
            "html.parser",
        )

        urls = RSSFetcher._discover_official_article_urls(
            soup,
            "https://qwen.ai/blog",
            ("/blog",),
            keep_query_keys=("id",),
        )

        self.assertEqual(
            urls,
            [
                "https://qwen.ai/blog?id=qwen-one",
                "https://qwen.ai/blog?id=qwen-two",
            ],
        )

    def test_excludes_category_path_prefixes(self):
        soup = BeautifulSoup(
            '<a href="/blog/tag/research">Research tag</a>'
            '<a href="/blog/model-release">Model release</a>',
            "html.parser",
        )

        urls = RSSFetcher._discover_official_article_urls(
            soup,
            "https://vendor.example/blog",
            ("/blog/",),
            exclude_path_prefixes=("/blog/tag/",),
        )

        self.assertEqual(urls, ["https://vendor.example/blog/model-release"])

    def test_extracts_date_from_nested_json_ld(self):
        payload = {
            "@context": "https://schema.org",
            "@graph": [{"@type": "NewsArticle", "datePublished": "2026-11-09T08:30:00Z"}],
        }
        soup = BeautifulSoup(
            '<script type="application/ld+json">'
            + json.dumps(payload)
            + "</script>",
            "html.parser",
        )

        self.assertEqual(
            RSSFetcher._official_page_date(soup),
            "2026-11-09T08:30:00+00:00",
        )

    def test_extracts_numeric_visible_date(self):
        soup = BeautifulSoup("<main>Published 2026/09/20</main>", "html.parser")
        self.assertEqual(
            RSSFetcher._official_page_date(soup),
            "2026-09-20T00:00:00+00:00",
        )

    def test_extracts_short_visible_date_without_comma(self):
        soup = BeautifulSoup("<main>Aug 18 2026</main>", "html.parser")
        self.assertEqual(
            RSSFetcher._official_page_date(soup),
            "2026-08-18T00:00:00+00:00",
        )

    def test_extracts_official_article_text_without_navigation(self):
        soup = BeautifulSoup(
            """
            <main>
              <nav>Products Company Careers</nav>
              <h1>Introducing Model One</h1>
              <p>Model One is the publisher's newest model.</p>
              <script>window.__DATA__ = 'ignore';</script>
            </main>
            """,
            "html.parser",
        )

        text = RSSFetcher._official_page_text(soup)

        self.assertIn("Introducing Model One", text)
        self.assertIn("newest model", text)
        self.assertNotIn("Products Company Careers", text)
        self.assertNotIn("window.__DATA__", text)


if __name__ == "__main__":
    unittest.main()
