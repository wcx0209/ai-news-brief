"""Public GitHub discovery/content through reviewed Agent Reach actions."""

import re
from urllib.parse import urljoin, urlsplit

from reach_content import same_article_url


def parse_trending_markdown(text):
    """Accept repository heading links, not login/nav/stargazer links."""
    result, seen = [], set()
    for label, href in re.findall(r'\[([^\]\n]+)\]\(([^\s)]+)\)', text or ''):
        target = urljoin('https://github.com/', href)
        parsed = urlsplit(target)
        if parsed.scheme != 'https' or parsed.netloc not in {'github.com', 'www.github.com'} or parsed.query or parsed.fragment:
            continue
        match = re.fullmatch(r'/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?', parsed.path)
        if not match:
            continue
        owner, repo = match.groups()
        if re.sub(r'\s+', '', label).casefold() != f'{owner}/{repo}'.casefold():
            continue
        key = (owner.casefold(), repo.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append({'owner': owner, 'repo': repo, 'url': f'https://github.com/{owner}/{repo}',
                       'rank': len(result) + 1})
    return result


def read_trending(client, url, max_repos):
    """Fail closed; a transient metadata failure must not overwrite stars with 0."""
    page = client.read_web(url)
    if not page.get('ok'):
        return [], ((page.get('error') or {}).get('code') or 'READ_FAILED')
    matches = [item for item in page.get('items', []) if same_article_url(url, item.get('url'))]
    if not matches:
        return [], 'PROVENANCE_MISMATCH'
    candidates = parse_trending_markdown(matches[0].get('text'))[:max(0, int(max_repos))]
    repos = []
    for candidate in candidates:
        response = client.read_github(candidate['url'])
        if not response.get('ok'):
            continue
        items = [item for item in response.get('items', []) if same_article_url(candidate['url'], item.get('url'))]
        if not items:
            continue
        item = items[0]
        raw = item.get('raw') or {}
        stars = raw.get('stargazers_count')
        if isinstance(stars, bool) or not isinstance(stars, int) or stars < 0:
            continue
        repos.append({**candidate, 'description': str(raw.get('description') or ''),
                      'stars': stars, 'forks': raw.get('forks_count') or 0,
                      'language': raw.get('language') or '', 'readme_text': item.get('text') or ''})
    return repos, None if repos else 'NO_USABLE_REPOSITORIES'
