"""Bounded original-source excerpts for a cloud-only weekly review draft.

Reads are anonymous public web reads of already selected article URLs. They
check what a publisher says, not whether its claims are independently true.
An injected reader is an offline test seam; it must never perform live I/O.
"""

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import os
import re

from agent_reach_client import AgentReachClient, _validate_url
from reach_content import same_article_url


MAX_MAIN = 8
MAX_SIGNALS = 2
MAX_URLS = 10
MAX_WORKERS = 4
TIMEOUT_SECONDS = 20
MAX_EXCERPT_CHARS = 6000
MIN_BODY_CHARS = 300
_SAFE_ERRORS = frozenset({
    'BAD_INPUT', 'PLATFORM_BLOCKED', 'NEED_LOGIN', 'RATE_LIMITED', 'BUSY',
    'UPSTREAM_BROKEN', 'TIMEOUT', 'NEED_SETUP', 'NOT_FOUND',
    'LOCAL_EXECUTION_DISABLED', 'UNSAFE_RUNTIME_CONFIG',
})
_INTERSTITIAL = re.compile(
    r'title:\s*(?:just a moment|access denied|attention required)|'
    r'(?:performing|complete|requires?) security verification|'
    r'(?:verify|confirm) (?:that )?you are (?:a )?human|'
    r'verify (?:your humanity|you are not a bot)|'
    r'(?:requiring|required) captcha|sign in to (?:continue|confirm)|'
    r'人机验证|反爬验证|/cdn-cgi/challenge-platform/', re.IGNORECASE,
)


def _safe_url(value):
    """Reuse the read adapter's syntax/credential guard without local DNS."""
    try:
        return _validate_url(value)
    except ValueError:
        return None


def _unavailable(url, code):
    return {'status': 'unavailable', 'source_url': url, 'error_code': code}


def _selected_row(event):
    """Choose only among the exact first three sources supplied to the model."""
    evidence = event.get('support') or [event.get('representative')]
    support = [row for row in evidence[:3] if isinstance(row, dict)]
    for row in support:
        if row.get('source_type') == 'official_release' and _safe_url(row.get('url')):
            return row
    representative = event.get('representative')
    if isinstance(representative, dict):
        for row in support:
            if row.get('id') == representative.get('id') and row.get('url') == representative.get('url'):
                return row
    return support[0] if support else None


def _read_one(reader, url):
    try:
        result = reader(url)
    except TimeoutError:
        return _unavailable(url, 'TIMEOUT')
    except Exception:
        # Never copy exceptions, arbitrary provider messages, or payloads.
        return _unavailable(url, 'READ_FAILED')
    if not isinstance(result, dict) or result.get('ok') is not True:
        error = result.get('error') if isinstance(result, dict) else None
        code = error.get('code') if isinstance(error, dict) else None
        return _unavailable(url, code if isinstance(code, str) and code in _SAFE_ERRORS else 'READ_FAILED')
    items = result.get('items')
    if not isinstance(items, list):
        return _unavailable(url, 'INVALID_RESPONSE')
    matches = [item for item in items if isinstance(item, dict)
               and same_article_url(url, item.get('url'))]
    if not matches:
        return _unavailable(url, 'PROVENANCE_MISMATCH')
    text = matches[0].get('text')
    if not isinstance(text, str) or len(re.sub(r'\s+', ' ', text).strip()) < MIN_BODY_CHARS:
        return _unavailable(url, 'INSUFFICIENT_CONTENT')
    text = text.strip()
    if _INTERSTITIAL.search(text[:MAX_EXCERPT_CHARS]):
        return _unavailable(url, 'PLATFORM_BLOCKED')
    return {'status': 'retrieved', 'source_url': url,
            'excerpt': text[:MAX_EXCERPT_CHARS]}


def _attach(event, selected, read):
    """Attach only to the actual selected record, preserving all publisher metadata."""
    if selected is None:
        return
    rows = [event.get('representative'), *event.get('support', [])]
    for row in rows:
        if (isinstance(row, dict) and row.get('id') == selected.get('id')
                and row.get('url') == selected.get('url')):
            row['original_read'] = deepcopy(read)


def enrich_selected_sources(plan, reader=None):
    """Return ``(copied_plan, private_audit)`` with at most 10 selected URL reads.

    Each of the selected eight main/two signal events contributes at most one
    URL. Shared URLs are read once. Read failures remain evidence gaps; they
    never replace summaries, source dates, publisher names, or source URLs.
    """
    if reader is None:
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise RuntimeError('weekly_source_reads_are_cloud_only')
        reader = AgentReachClient(timeout=TIMEOUT_SECONDS,
                                  max_chars=MAX_EXCERPT_CHARS).read_web
    elif not callable(reader):
        reader = reader.read_web
    enriched = deepcopy(plan)
    shortlist = enriched.get('shortlist', {})
    targets, urls = [], []
    for section, limit in (('main', MAX_MAIN), ('signals', MAX_SIGNALS)):
        for index, event in enumerate(shortlist.get(section, [])):
            row = _selected_row(event)
            url = _safe_url(row.get('url')) if row else None
            code = 'SOURCE_READ_BUDGET_EXCEEDED' if index >= limit else 'UNSAFE_URL' if not url else None
            if code:
                read = _unavailable(url or '', code)
                _attach(event, row, read)
            else:
                read = None
                if url not in urls:
                    urls.append(url)
            targets.append((event, row, url, read))
    # Section caps above imply this bound, independently of caller plan sizes.
    if len(urls) > MAX_URLS:
        raise ValueError('weekly_source_url_bound_exceeded')
    reads = {}
    if urls:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(urls))) as pool:
            reads = dict(zip(urls, pool.map(lambda url: _read_one(reader, url), urls)))
    entries = []
    for event, row, url, failure in targets:
        read = failure if failure is not None else reads[url]
        _attach(event, row, read)
        entries.append({'event_id': event.get('event_id'),
                        'source_id': row.get('id') if row else None,
                        **{key: value for key, value in read.items() if key != 'excerpt'}})
    retrieved = sum(read['status'] == 'retrieved' for read in reads.values())
    audit = {'schema_version': 1, 'scope': 'selected_existing_urls_only',
             'independently_verified': False, 'new_collection': False,
             'max_urls': MAX_URLS, 'max_workers': MAX_WORKERS,
             'timeout_seconds': TIMEOUT_SECONDS, 'max_excerpt_chars': MAX_EXCERPT_CHARS,
             'selected_events': len(targets), 'requested_unique_urls': len(urls),
             'retrieved_unique_urls': retrieved,
             'unavailable_unique_urls': len(urls) - retrieved,
             'reads': entries}
    return enriched, audit
