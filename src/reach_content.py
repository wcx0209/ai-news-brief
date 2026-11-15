"""Provenance and publication safeguards between public reads and editing."""

from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def publication_time(value):
    try:
        result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc)
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def same_article_url(left, right):
    """Allow scheme/tracking changes, never another article or query ID."""
    def key(value):
        parsed = urlsplit(value)
        if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
            return None
        host = parsed.hostname.lower().removeprefix('www.')
        if parsed.port and parsed.port not in {80, 443}:
            return None
        query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                 if not k.lower().startswith('utm_') and k.lower() not in {'fbclid', 'gclid'}]
        query.sort(key=lambda pair: pair[0]) # Stable: duplicate IDs keep their order.
        # Keep duplicate parameter order: some publishers use the last ID.
        # Ordinary #section anchors are harmless, but SPA routes identify a story.
        fragment = parsed.fragment if parsed.fragment.startswith(('/', '!/')) else ''
        path = parsed.path.rstrip('/') or '/'
        if host == 'github.com':
            path = path.casefold()
        return urlunsplit(('', host, path, urlencode(query), fragment))
    try:
        a, b = key(left), key(right)
        return bool(a and a == b)
    except (TypeError, ValueError):
        return False


def read_entry_content(collector, entry, *, first_party=False):
    """Return (text, backend, error); never use the old article extractor.

    Official adapters already validate the publisher's body and date together.
    Reuse that captured text rather than submitting it to another provider.
    Social channels needing account/engagement adapters remain disabled.
    """
    if any(entry.get(flag) for flag in ('is_reddit', 'is_twitter', 'is_hackernews')):
        return None, None, 'reach_social_not_configured'
    official = (entry.get('official_content') or '').strip()
    if first_party and entry.get('discovery_backend') == 'publisher_adapter' and len(official) >= 120:
        return official, 'publisher_adapter', None
    result = collector.read_entry(entry)
    if not isinstance(result, dict) or not result.get('ok'):
        code = ((result or {}).get('error') or {}).get('code', 'READ_FAILED') if isinstance(result, dict) else 'READ_FAILED'
        return None, None, 'reach_' + str(code).lower()
    url = entry.get('link') or entry.get('url')
    matches = [item for item in result.get('items', [])
               if isinstance(item, dict) and same_article_url(url, item.get('url'))]
    if not matches:
        return None, None, 'reach_provenance_mismatch'
    item = matches[0]
    text = (item.get('text') or '').strip()
    kind = result.get('meta', {}).get('content_type')
    minimum = 300 if kind == 'video_description' else 120
    if len(text) < minimum:
        return None, None, 'reach_insufficient_content'
    if kind == 'video_description':
        text = ('Publisher-supplied video description (not a verbatim transcript). '
                'Treat claims as the publisher\'s description, not as verified interview quotations.\n\n' + text)
    # A repository creation date is not a news publication date. Never replace
    # an original feed date with Reach metadata, nor use a GitHub repo date.
    if not entry.get('published_at') and result.get('channel') in {'web', 'youtube'}:
        published = publication_time(item.get('published_at'))
        if published:
            entry['published_at'] = published.isoformat()
            entry['date_basis'] = 'source_reader_published'
    return text, 'agent_reach:' + str(result.get('backend') or 'unknown'), None
