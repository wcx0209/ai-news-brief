import feedparser
import logging
import httpx
import concurrent.futures
import threading
import os
import re
import json
from datetime import datetime, timezone
from calendar import timegm
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from config_loader import ConfigLoader


# Founder-led frontier labs often publish only an HTML news index, not RSS.
# Keep this allowlist narrow and first-party: the adapter follows article links
# on the same official domain and reads their own publication metadata.
OFFICIAL_HTML_INDEX_RULES = {
    'https://thinkingmachines.ai/news': {'path_prefixes': ('/news/',)},
    'https://www.worldlabs.ai/blog': {'path_prefixes': ('/blog/',)},
    'https://www.pi.website/blog': {'path_prefixes': ('/blog/', '/research/')},
    'https://reflection.ai/blog': {'path_prefixes': ('/blog/',)},
    'https://www.lila.ai/news': {'path_prefixes': ('/news/',)},
    'https://news.mit.edu/topic/biological-engineering': {'path_prefixes': ('/20',)},

    # Official company, model, research, and product indexes. Many vendors do
    # not expose a stable RSS feed, so these narrow same-domain rules keep the
    # primary announcement in the pipeline instead of relying on media recaps
    # or third-party RSS mirrors.
    'https://research.meta.ai': {'path_prefixes': ('/blog/',)},
    'https://about.fb.com/news/tag/ai': {
        'path_prefixes': ('/news/',),
        'exclude_path_prefixes': ('/news/topics/', '/news/category/'),
    },
    'https://www.anthropic.com/news': {
        # Anthropic places some flagship model announcements at root-level
        # /claude-* URLs even though they are featured on the News index.
        'path_prefixes': ('/news/', '/claude-'),
        'exclude_titles': ('Announcements',),
    },
    'https://www.anthropic.com/research': {
        'path_prefixes': ('/research/',),
        'exclude_titles': (
            'Alignment', 'Economics', 'Engineering', 'Frontier Red Team',
            'Interpretability', 'Science', 'Societal Impacts',
        ),
    },
    'https://x.ai/news': {'path_prefixes': ('/news/',)},
    'https://mistral.ai/news': {'path_prefixes': ('/news/',)},
    'https://cohere.com/blog': {
        'path_prefixes': ('/blog/',),
        'exclude_path_prefixes': ('/blog/tag/',),
    },
    # Qwen's current blog identifies articles with ?id=... on one route.
    'https://qwen.ai/blog': {
        'path_prefixes': ('/blog',),
        'keep_query_keys': ('id',),
    },
    'https://ernie.baidu.com': {'path_prefixes': ('/blog/',)},
    'https://www.minimax.io/news': {'path_prefixes': ('/news/',)},
    'https://www.amd.com/en/blogs.html': {'path_prefixes': ('/en/blogs/',)},
    'https://www.qualcomm.com/news/onq': {'path_prefixes': ('/news/onq/',)},
    'https://www.cerebras.ai/blog': {'path_prefixes': ('/blog/',)},
    'https://groq.com/blog': {'path_prefixes': ('/blog/',)},
    'https://www.langchain.com/blog': {'path_prefixes': ('/blog/',)},
    'https://www.llamaindex.ai/blog': {'path_prefixes': ('/blog/',)},
    'https://crewai.com/blog': {'path_prefixes': ('/blog/',)},
    'https://ollama.com/blog': {'path_prefixes': ('/blog/',)},
    'https://www.ibm.com/quantum/blog': {'path_prefixes': ('/quantum/blog/',)},
}


class RSSFetcher:
    def __init__(self, feeds_config):
        self.feeds = feeds_config
        # Load timeout from config
        config = ConfigLoader.get_instance().get('fetching', {})
        self.timeout = config.get('network_timeout', 60)
        # Lazy-initialized browser instance for YouTube
        self._browser = None
        self._browser_lock = threading.Lock()
    
    def _get_browser_unlocked(self):
        """Get or create the shared browser instance (must be called with lock held)"""
        if self._browser is None:
            from DrissionPage import ChromiumPage, ChromiumOptions
            co = ChromiumOptions()
            co.headless()
            co.set_argument('--disable-gpu')
            self._browser = ChromiumPage(co)
        return self._browser

    
    def close(self):
        """Close the browser instance if it exists"""
        if self._browser is not None:
            try:
                self._browser.quit()
            except:
                pass
            self._browser = None

    def _fetch_url(self, url, headers):
        """Fetch URL with httpx client"""
        with httpx.Client(timeout=self.timeout, trust_env=True, verify=False) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            return response.content

    def _get_youtube_channel_id(self, url):
        """Extract channel ID from YouTube RSS URL"""
        # Pattern: https://www.youtube.com/feeds/videos.xml?channel_id=UC...
        match = re.search(r'channel_id=([A-Za-z0-9_-]+)', url)
        return match.group(1) if match else None

    def _fetch_youtube_via_api(self, feed_config):
        """
        Fetch YouTube videos using YouTube Data API (PlaylistItems).
        More reliable than RSS and uses less quota than search.
        
        Returns:
            dict with 'entries' (list) and 'error' (str or None)
        """
        url = feed_config['url']
        name = feed_config['name']
        source_id = feed_config.get('id')
        
        api_key = os.environ.get('YOUTUBE_API_KEY') or os.environ.get('INBRIEF_YOUTUBE_API_KEY')
        if not api_key:
            return None  # Fall back to RSS
        
        channel_id = self._get_youtube_channel_id(url)
        if not channel_id:
            logging.warning(f"Cannot extract channel ID from {url}")
            return None
        
        # Convert channel ID (UC...) to uploads playlist ID (UU...)
        # YouTube stores all uploads in a playlist with ID starting with UU
        if channel_id.startswith('UC'):
            playlist_id = 'UU' + channel_id[2:]
        else:
            playlist_id = channel_id
        
        try:
            api_url = 'https://www.googleapis.com/youtube/v3/playlistItems'
            params = {
                'part': 'snippet',
                'playlistId': playlist_id,
                'maxResults': 10,  # Fetch latest 10 videos
                'key': api_key
            }
            
            with httpx.Client(timeout=self.timeout, trust_env=True) as client:
                response = client.get(api_url, params=params)
                response.raise_for_status()
                data = response.json()
            
            entries = []
            for item in data.get('items', []):
                snippet = item.get('snippet', {})
                video_id = snippet.get('resourceId', {}).get('videoId', '')
                
                # Parse published date
                published_at_str = snippet.get('publishedAt', '')
                if published_at_str:
                    # ISO 8601 format: 2026-02-09T12:00:00Z
                    try:
                        dt = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                        published_at = dt.isoformat()
                    except:
                        published_at = datetime.now(timezone.utc).isoformat()
                else:
                    published_at = datetime.now(timezone.utc).isoformat()
                
                entry_data = {
                    'title': snippet.get('title', ''),
                    'link': f'https://www.youtube.com/watch?v={video_id}' if video_id else '',
                    'summary': snippet.get('description', '')[:500],  # Truncate long descriptions
                    'source': name,
                    'source_id': source_id,
                    'published_at': published_at,
                    'is_youtube': True,
                    'orig_entry': item
                }
                entries.append(entry_data)
            
            logging.info(f"Fetched {len(entries)} entries from {name} via YouTube API")
            return {'entries': entries, 'error': None, 'feed_config': feed_config}
            
        except Exception as e:
            logging.warning(f"YouTube API failed for {name}: {e}")
            return None  # Fall back to RSS

    def _fetch_hf_daily_papers(self, feed_config):
        """Fetch Hugging Face curated Papers (JSON API), the *weekly* trending
        batch rather than the daily one. The base source URL points at the daily
        endpoint; we append ?week=YYYY-Www (current ISO week) so the API returns
        the whole week's trending list. Using the weekly list instead of the daily
        one keeps the collected set stable within a week (each run returns roughly
        the same papers, so dedup absorbs them) instead of piling on a fresh daily
        batch every run. Entries are flagged is_hf_papers so the pipeline skips the
        age cutoff.

        To resist HF upvote gaming, papers are re-ranked by combining their rank
        position in the upvotes list with their rank position in the GitHub-stars
        list (ranks, not raw values, so a large star count can't drown out votes) —
        both fields are supplied by the API — and only the top N are kept. Papers
        without an associated GitHub repo are dropped. Endpoint sits behind
        Cloudflare, so use curl_cffi TLS impersonation."""
        url = feed_config['url']
        name = feed_config['name']
        source_id = feed_config.get('id')
        top_n = ConfigLoader.get_instance().get('fetching', {}).get('hf_daily_top_n', 5)
        # Request the current ISO week's trending list (HF uses ISO week tags,
        # e.g. 2026-W24). The daily endpoint accepts ?week=... and returns the
        # weekly batch.
        iso = datetime.now(timezone.utc).isocalendar()
        week_tag = f"{iso[0]}-W{iso[1]:02d}"
        sep = '&' if '?' in url else '?'
        fetch_url = f"{url}{sep}week={week_tag}"
        try:
            from curl_cffi import requests as cffi_requests
            resp = cffi_requests.get(fetch_url, impersonate="chrome", timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logging.warning(f"HF Daily Papers fetch failed for {name}: {e}")
            return {'entries': [], 'error': str(e), 'feed_config': feed_config}

        candidates = []
        for item in data:
            paper = item.get('paper', {}) or {}
            arxiv_id = paper.get('id', '')
            github_repo = paper.get('githubRepo')
            # Ignore papers without an arxiv id or a backing GitHub project.
            if not arxiv_id or not github_repo:
                continue
            candidates.append({
                'item': item,
                'paper': paper,
                'arxiv_id': arxiv_id,
                'upvotes': paper.get('upvotes') or 0,
                'stars': paper.get('githubStars') or 0,
            })

        # Rank by position, not raw value: each paper's rank in the upvotes list
        # plus its rank in the stars list (rank = number of papers strictly above,
        # so ties share a rank). Smaller combined rank = better.
        for c in candidates:
            c['rank'] = (sum(1 for o in candidates if o['upvotes'] > c['upvotes'])
                         + sum(1 for o in candidates if o['stars'] > c['stars']))
        candidates.sort(key=lambda c: c['rank'])
        candidates = candidates[:top_n]

        entries = []
        for c in candidates:
            item, paper, arxiv_id = c['item'], c['paper'], c['arxiv_id']
            published_at_str = (item.get('publishedAt')
                                or paper.get('submittedOnDailyAt')
                                or paper.get('publishedAt') or '')
            try:
                dt = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                published_at = dt.isoformat()
            except Exception:
                published_at = datetime.now(timezone.utc).isoformat()

            entries.append({
                'title': paper.get('title') or item.get('title') or '',
                'link': f'https://huggingface.co/papers/{arxiv_id}',
                'summary': paper.get('summary') or item.get('summary') or '',
                'source': name,
                'source_id': source_id,
                'published_at': published_at,
                'is_hf_papers': True,
                'orig_entry': item,
            })

        logging.info(f"Fetched {len(entries)} entries from {name} via HF Papers API "
                     f"(week {week_tag}, top {top_n} by upvotes+stars, github-backed only)")
        return {'entries': entries, 'error': None, 'feed_config': feed_config}

    def _fetch_bytedance_seed(self, feed_config):
        """Build feed entries from ByteDance Seed's embedded article-list JSON."""
        routes = ("foundation", "audio", "visual")
        articles = {}
        try:
            from curl_cffi import requests as cffi_requests
            for route in routes:
                page_url = f"https://seed.bytedance.com/en/blog_list/{route}"
                response = cffi_requests.get(page_url, impersonate="chrome", timeout=self.timeout)
                response.raise_for_status()
                page = response.text
                marker = '"article_list":'
                marker_index = page.find(marker)
                if marker_index < 0:
                    continue
                payload, _ = json.JSONDecoder().raw_decode(page[marker_index + len(marker):])
                for item in payload:
                    content = item.get('ArticleSubContentEn') or item.get('ArticleSubContentZh') or {}
                    meta = item.get('ArticleMeta') or {}
                    title_key = content.get('TitleKey')
                    title = content.get('Title') or content.get('ShortTitle')
                    if not title_key or not title:
                        continue
                    link = f"https://seed.bytedance.com/en/blog/{title_key}"
                    published_ms = meta.get('PublishDate') or meta.get('UpdateTime')
                    try:
                        published_at = datetime.fromtimestamp(
                            float(published_ms) / 1000, tz=timezone.utc
                        ).isoformat()
                    except (TypeError, ValueError, OSError):
                        published_at = datetime.now(timezone.utc).isoformat()
                    articles[link] = {
                        'title': title,
                        'link': link,
                        'summary': content.get('Abstract') or '',
                        'source': feed_config['name'],
                        'source_id': feed_config.get('id'),
                        'published_at': published_at,
                        'orig_entry': item,
                    }
        except Exception as exc:
            logging.warning(f"ByteDance Seed fetch failed: {exc}")
            return {'entries': [], 'error': str(exc), 'feed_config': feed_config}

        entries = sorted(articles.values(), key=lambda entry: entry['published_at'], reverse=True)
        logging.info(f"Fetched {len(entries)} entries from {feed_config['name']}")
        return {'entries': entries, 'error': None, 'feed_config': feed_config}

    def _fetch_tencent_newsroom(self, feed_config):
        """Build feed entries from Tencent's official Chinese newsroom.

        Tencent exposes a structured newsroom but no stable RSS/Atom endpoint.
        Keeping this adapter here lets first-party Hunyuan announcements enter
        the same pipeline as RSS sources without relying on a media rewrite.
        """
        try:
            from bs4 import BeautifulSoup
            from curl_cffi import requests as cffi_requests

            response = cffi_requests.get(
                feed_config['url'], impersonate="chrome", timeout=self.timeout
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            entries = []
            seen = set()
            for article in soup.select('article'):
                anchor = article.select_one('h2.blog-title a[href]')
                if not anchor:
                    continue
                link = urljoin(
                    feed_config['url'], (anchor.get('href') or '').strip()
                )
                title = anchor.get_text(' ', strip=True)
                if not link or not title or link in seen:
                    continue
                seen.add(link)

                published_at = datetime.now(timezone.utc).isoformat()
                date_node = article.select_one('.tc-blogpost-date')
                if date_node:
                    raw_date = date_node.get_text(' ', strip=True)
                    try:
                        published_at = datetime.strptime(
                            raw_date, '%Y年%m月%d日'
                        ).replace(tzinfo=timezone.utc).isoformat()
                    except ValueError:
                        logging.debug(
                            "Tencent Newsroom date could not be parsed: %s", raw_date
                        )

                entries.append({
                    'title': title,
                    'link': link,
                    'summary': '',
                    'source': feed_config['name'],
                    'source_id': feed_config.get('id'),
                    'published_at': published_at,
                    'orig_entry': {'title': title, 'link': link},
                })

            entries.sort(key=lambda entry: entry['published_at'], reverse=True)
            logging.info(
                "Fetched %d entries from %s official newsroom",
                len(entries), feed_config['name']
            )
            return {'entries': entries, 'error': None, 'feed_config': feed_config}
        except Exception as exc:
            logging.warning("Tencent Newsroom fetch failed: %s", exc)
            return {'entries': [], 'error': str(exc), 'feed_config': feed_config}

    @staticmethod
    def _official_page_date(soup):
        """Extract an official article's publication date without inventing one."""
        selectors = (
            'meta[property="article:published_time"]',
            'meta[itemprop="datePublished"]',
            'meta[name="datePublished"]',
            'meta[name="date"]',
            'time[datetime]',
        )
        raw_values = []
        for selector in selectors:
            node = soup.select_one(selector)
            if node:
                raw_values.append((node.get('content') or node.get('datetime') or '').strip())

        # JSON-LD is the most reliable publication metadata on many modern
        # company sites. Walk nested graphs instead of assuming one schema.
        def collect_json_dates(value):
            if isinstance(value, dict):
                published = value.get('datePublished')
                if published:
                    raw_values.append(str(published).strip())
                for child in value.values():
                    collect_json_dates(child)
            elif isinstance(value, list):
                for child in value:
                    collect_json_dates(child)

        for node in soup.select('script[type="application/ld+json"]'):
            try:
                collect_json_dates(json.loads(node.string or node.get_text() or '{}'))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        # Some modern sites expose the date only in visible page text.
        page_text = soup.get_text(' ', strip=True)
        match = re.search(
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+20\d{2}\b',
            page_text,
        )
        if match:
            raw_values.append(match.group(0))
        short_match = re.search(
            r'\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+\d{1,2},?\s+20\d{2}\b',
            page_text,
        )
        if short_match:
            raw_values.append(short_match.group(0).replace('Sept ', 'Sep ').replace('.', ''))
        numeric_match = re.search(r'\b20\d{2}[/-]\d{1,2}[/-]\d{1,2}\b', page_text)
        if numeric_match:
            raw_values.append(numeric_match.group(0).replace('/', '-'))

        for raw in raw_values:
            if not raw:
                continue
            try:
                parsed = datetime.fromisoformat(raw.replace('Z', '+00:00'))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=timezone.utc)
                return parsed.astimezone(timezone.utc).isoformat()
            except ValueError:
                pass
            for fmt in ('%B %d, %Y', '%b %d, %Y', '%b %d %Y', '%Y-%m-%d'):
                try:
                    return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).isoformat()
                except ValueError:
                    continue
        return None

    @staticmethod
    def _official_page_text(soup):
        """Extract readable first-party text already present in an article page."""
        node = soup.select_one('article') or soup.select_one('main')
        if not node:
            return ''
        for unwanted in node.select('script, style, noscript, svg, nav, footer'):
            unwanted.decompose()
        return node.get_text('\n', strip=True)

    @staticmethod
    def _discover_official_article_urls(soup, index_url, path_prefixes,
                                        keep_query_keys=(),
                                        exclude_path_prefixes=(), limit=40):
        """Return canonical, same-domain article URLs from an official index."""
        parsed_index = urlparse(index_url)
        source_host = parsed_index.netloc.lower()

        def normalize(link):
            parsed = urlparse(link)
            kept_query = urlencode([
                (key, value) for key, value in parse_qsl(parsed.query)
                if key in keep_query_keys
            ])
            path = parsed.path.rstrip('/') or '/'
            return urlunparse((parsed.scheme, parsed.netloc, path, '', kept_query, ''))

        index_normalized = normalize(index_url)
        article_urls = []
        seen = set()
        for anchor in soup.select('a[href]'):
            link = urljoin(index_url, (anchor.get('href') or '').strip())
            parsed = urlparse(link)
            normalized = normalize(link)
            if (
                parsed.netloc.lower() != source_host
                or normalized == index_normalized
                or not any(parsed.path.startswith(prefix) for prefix in path_prefixes)
                or any(parsed.path.startswith(prefix) for prefix in exclude_path_prefixes)
                or parsed.path.lower().endswith(('.xml', '.rss', '.atom'))
                or re.search(r'/page/\d+/?$', parsed.path)
                or normalized in seen
            ):
                continue
            seen.add(normalized)
            article_urls.append(normalized)
            if len(article_urls) >= limit:
                break
        return article_urls

    def _fetch_official_html_index(self, feed_config, rule):
        """Build feed entries from a first-party HTML news or research index."""
        try:
            from bs4 import BeautifulSoup
            from curl_cffi import requests as cffi_requests

            index_url = feed_config['url']
            response = cffi_requests.get(
                index_url, impersonate='chrome', timeout=self.timeout
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')
            resolved_index_url = str(getattr(response, 'url', '') or index_url)
            article_urls = self._discover_official_article_urls(
                soup,
                resolved_index_url,
                rule['path_prefixes'],
                rule.get('keep_query_keys', ()),
                rule.get('exclude_path_prefixes', ()),
            )

            # A few official sites render the article grid client-side. Keep
            # the cloud collector browserless by default, but reuse its shared
            # headless browser when static HTML contains no article links.
            if not article_urls:
                try:
                    with self._browser_lock:
                        browser = self._get_browser_unlocked()
                        browser.get(resolved_index_url)
                        rendered_html = browser.run_js(
                            'return document.documentElement.outerHTML || ""'
                        )
                    if rendered_html:
                        rendered_soup = BeautifulSoup(rendered_html, 'html.parser')
                        article_urls = self._discover_official_article_urls(
                            rendered_soup,
                            resolved_index_url,
                            rule['path_prefixes'],
                            rule.get('keep_query_keys', ()),
                            rule.get('exclude_path_prefixes', ()),
                        )
                except Exception as exc:
                    logging.debug(
                        'Rendered official index fallback failed for %s: %s',
                        feed_config['name'], exc
                    )

            entries = []
            for link in article_urls:
                try:
                    article_response = cffi_requests.get(
                        link, impersonate='chrome', timeout=self.timeout
                    )
                    article_response.raise_for_status()
                    article_soup = BeautifulSoup(article_response.text, 'html.parser')
                    title_node = (
                        article_soup.select_one('meta[property="og:title"]')
                        or article_soup.select_one('h1')
                    )
                    title = (
                        title_node.get('content')
                        if title_node and title_node.name == 'meta'
                        else title_node.get_text(' ', strip=True) if title_node else ''
                    )
                    if title.strip() in rule.get('exclude_titles', ()):
                        continue
                    published_at = self._official_page_date(article_soup)
                    if not title or not published_at:
                        logging.debug(
                            'Skipping official page without title/date: %s', link
                        )
                        continue
                    description_node = article_soup.select_one(
                        'meta[property="og:description"]'
                    ) or article_soup.select_one(
                        'meta[name="description"]'
                    )
                    official_content = self._official_page_text(article_soup)
                    entries.append({
                        'title': title.strip(),
                        'link': link,
                        'summary': (description_node.get('content') or '').strip()
                        if description_node else '',
                        'official_content': official_content,
                        'source': feed_config['name'],
                        'source_id': feed_config.get('id'),
                        'published_at': published_at,
                        'orig_entry': {'title': title.strip(), 'link': link},
                    })
                    if len(entries) >= 8:
                        break
                except Exception as exc:
                    logging.debug('Official article fetch failed for %s: %s', link, exc)

            entries.sort(key=lambda entry: entry['published_at'], reverse=True)
            logging.info(
                'Fetched %d entries from %s official HTML index',
                len(entries), feed_config['name']
            )
            return {'entries': entries, 'error': None, 'feed_config': feed_config}
        except Exception as exc:
            logging.warning('Official HTML index failed for %s: %s', feed_config['name'], exc)
            return {'entries': [], 'error': str(exc), 'feed_config': feed_config}

    # Domains that require TLS fingerprint impersonation to bypass WAF
    DIFFICULT_RSS_DOMAINS = [
        'marktechpost.com',
        'artificialintelligence-news.com',
        'awesomeagents.ai',
    ]

    def parse_feed(self, feed_config):
        """
        Parse a single RSS feed.
        
        Returns:
            dict with 'entries' (list) and 'error' (str or None)
        """
        url = feed_config['url']
        name = feed_config['name']
        source_id = feed_config.get('id')  # Optional source ID from database
        description = feed_config.get('description', name)
        
        # Check if this is a Hacker News feed
        is_hackernews = 'ycombinator.com' in url
        # Check if this is a Reddit feed
        is_reddit = 'reddit.com' in url
        # Check if this is the Hugging Face Daily Papers JSON API
        is_hf_papers = 'huggingface.co/api/daily_papers' in url
        is_bytedance_seed = 'seed.bytedance.com' in url
        is_tencent_newsroom = 'tencent.com/zh-cn/newsroom' in url
        official_html_rule = OFFICIAL_HTML_INDEX_RULES.get(url.rstrip('/'))
        # Check if this is a YouTube feed
        is_youtube = 'youtube.com' in url or 'youtu.be' in url
        # Check if this is a The Verge feed
        is_theverge = 'theverge.com' in url
        # Check if this is a Twitter/X feed
        is_twitter = 'twitter.com' in url or 'x.com' in url or 'nitter' in url or '/twitter/' in url
        # Check if this is a difficult RSS domain
        is_difficult_rss = any(domain in url for domain in self.DIFFICULT_RSS_DOMAINS)
        
        # Hugging Face Daily Papers come from a JSON API, not RSS
        if is_hf_papers:
            return self._fetch_hf_daily_papers(feed_config)

        if is_bytedance_seed:
            return self._fetch_bytedance_seed(feed_config)

        if is_tencent_newsroom:
            return self._fetch_tencent_newsroom(feed_config)

        if official_html_rule:
            return self._fetch_official_html_index(feed_config, official_html_rule)

        # For YouTube, try API first (more stable than RSS)
        if is_youtube:
            api_result = self._fetch_youtube_via_api(feed_config)
            if api_result is not None:
                return api_result
            logging.info(f"Falling back to RSS for YouTube: {name}")
        
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'application/rss+xml, application/xml, text/xml, */*',
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
                'Referer': url,
            }
            
            content = None
            
            # For specific difficult domains, prioritize curl_cffi
            if is_difficult_rss:
                try:
                    from curl_cffi import requests as cffi_requests
                    logging.info(f"Using curl_cffi for difficult domain: {name}")
                    resp = cffi_requests.get(url, impersonate="chrome", timeout=self.timeout)
                    resp.raise_for_status()
                    # Relaxed XML check for these domains
                    # Check first 1000 bytes
                    prefix = resp.content[:1000]
                    if b'<?' in prefix or b'<rss' in prefix or b'<feed' in prefix or b'<html' not in prefix:
                        content = resp.content
                        logging.info(f"curl_cffi succeeded for {name}")
                    else:
                        logging.warning(f"curl_cffi returned likely non-XML for {name}: {prefix[:100]}")
                except Exception as e:
                    logging.warning(f"curl_cffi failed for difficult domain {name}: {e}")
            
            # Fallback to httpx/autodetect logic if content is still None
            if content is None:
                # Strategy: curl_cffi (TLS impersonation) → DrissionPage (real browser) → httpx
                # NOTE: Do NOT pass custom headers to curl_cffi - impersonate mode auto-sets
                # browser-matching headers, and custom headers would break fingerprint consistency
                try:
                    from curl_cffi import requests as cffi_requests
                    resp = cffi_requests.get(url, impersonate="chrome", timeout=self.timeout)
                    resp.raise_for_status()
                    # Verify we got actual XML, not a WAF challenge page (e.g. SiteGround captcha)
                    if b'<?' in resp.content[:100] or b'<rss' in resp.content[:500] or b'<feed' in resp.content[:500]:
                        content = resp.content
                    else:
                        logging.info(f"curl_cffi got non-XML response for {name}, trying browser engine...")
                        raise ValueError("Non-XML response from curl_cffi")
                except Exception as ce:
                    # curl_cffi failed or got non-XML, try DrissionPage browser engine
                    logging.debug(f"curl_cffi not sufficient for {name}: {ce}")
                    try:
                        with self._browser_lock:
                            browser = self._get_browser_unlocked()
                            browser.get(url)
                            # Browser renders XML in a <pre> tag; extract raw text via JS
                            raw_xml = browser.run_js(
                                'return document.querySelector("pre")?.textContent || ""'
                            )
                            if raw_xml and ('<rss' in raw_xml or '<?xml' in raw_xml or '<feed' in raw_xml):
                                content = raw_xml.encode('utf-8')
                                logging.info(f"Browser engine succeeded for {name}")
                            else:
                                raise ValueError("Browser did not return valid RSS XML")
                    except Exception as be:
                        logging.debug(f"Browser engine failed for {name}: {be}")
                        # Final fallback: plain httpx
                        content = self._fetch_url(url, headers)
            
            parsed = feedparser.parse(content)
            entries = []
            for entry in parsed.entries:
                # The Verge: only keep entries with "AI" category
                if is_theverge:
                    tags = entry.get('tags', [])
                    has_ai = any(
                        (tag.get('term', '') or '').strip().upper() == 'AI'
                        for tag in tags
                    )
                    if not has_ai:
                        continue
                # Harmonize date
                published_parsed = entry.get('published_parsed') or entry.get('updated_parsed')
                if published_parsed:
                    dt = datetime.fromtimestamp(timegm(published_parsed), tz=timezone.utc)
                    published_at = dt.isoformat()
                else:
                    published_at = datetime.now(timezone.utc).isoformat()

                # Try to get the most detailed content from RSS
                content_val = ''
                if 'content' in entry and len(entry.content) > 0:
                    content_val = entry.content[0].value
                
                summary = content_val or entry.get('summary', '') or entry.get('description', '')

                entry_data = {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'summary': summary,
                    'source': name,
                    'source_id': source_id,  # Include source ID
                    'published_at': published_at,
                    'orig_entry': entry # Keep raw just in case
                }
                
                # For Hacker News, extract comments URL from the comments tag
                if is_hackernews:
                    entry_data['is_hackernews'] = True
                    # feedparser stores <comments> tag in entry.comments
                    comments_url = entry.get('comments', '')
                    entry_data['comments_url'] = comments_url
                
                # For Reddit, mark as Reddit source and extract updated time
                if is_reddit:
                    entry_data['is_reddit'] = True
                    updated_parsed = entry.get('updated_parsed')
                    if updated_parsed:
                        entry_data['updated_at'] = datetime.fromtimestamp(timegm(updated_parsed), tz=timezone.utc).isoformat()
                
                # For Twitter, mark as Twitter source if feed matches or link matches
                is_twitter_entry = is_twitter or 'twitter.com' in entry_data['link'] or 'x.com' in entry_data['link']
                if is_twitter_entry:
                    entry_data['is_twitter'] = True
                
                # For YouTube, mark as YouTube source
                if is_youtube:
                    entry_data['is_youtube'] = True
                
                entries.append(entry_data)
            logging.info(f"Fetched {len(entries)} entries from {name}")
            return {'entries': entries, 'error': None, 'feed_config': feed_config}
        except Exception as e:
            # Extract error type for clearer reporting
            error_str = str(e)
            if '404' in error_str:
                error_type = 'rss_404_not_found'
            elif '403' in error_str:
                error_type = 'rss_403_forbidden'
            elif '401' in error_str:
                error_type = 'rss_401_unauthorized'
            elif 'timeout' in error_str.lower():
                error_type = 'rss_timeout'
            elif 'ssl' in error_str.lower() or 'certificate' in error_str.lower():
                error_type = 'rss_ssl_error'
            else:
                error_type = 'rss_fetch_error'
            
            logging.error(f"Error fetching feed {name} ({url}): {e}")
            return {
                'entries': [], 
                'error': error_type, 
                'error_detail': error_str,
                'feed_config': feed_config
            }

    def fetch_all(self):
        """
        Fetch all configured feeds.
        
        Returns:
            tuple: (all_entries, failed_feeds)
            - all_entries: list of entry dicts
            - failed_feeds: list of dicts with 'url', 'name', 'description', 'error', 'error_detail'
        """
        all_entries = []
        failed_feeds = []
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                future_to_feed = {executor.submit(self.parse_feed, feed): feed for feed in self.feeds}
                for future in concurrent.futures.as_completed(future_to_feed):
                    feed = future_to_feed[future]
                    try:
                        result = future.result()
                        if result.get('error'):
                            # Feed fetch failed, record for statistics
                            failed_feeds.append({
                                'url': feed['url'],
                                'name': feed['name'],
                                'description': feed.get('description', feed['name']),
                                'error': result['error'],
                                'error_detail': result.get('error_detail', '')
                            })
                        else:
                            all_entries.extend(result['entries'])
                    except Exception as exc:
                        logging.error(f"Feed fetch generated an exception: {exc}")
                        failed_feeds.append({
                            'url': feed['url'],
                            'name': feed['name'],
                            'description': feed.get('description', feed['name']),
                            'error': 'rss_exception',
                            'error_detail': str(exc)
                        })
        finally:
            self.close()  # Clean up browser after all fetches
        return all_entries, failed_feeds
