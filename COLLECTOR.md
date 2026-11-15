# Polyemergence collection: Agent Reach

## What is replaced

`config.free.yaml` and `config.yaml` select `collector.backend: agent_reach`.
`pipeline_runner` constructs `AgentReachCollector`, not `RSSFetcher`.
Public content reads execute the real upstream Python `run_action` dispatcher:

- Web: explicit Jina Reader backend, then Exa only after an ordinary technical
  failure. Login, verification, denial and rate-limit results stop the read.
- YouTube: yt-dlp subtitles first; only missing subtitles may use an explicitly
  labelled publisher description. No paid transcription, browser or cookies.
- GitHub: explicit public REST backend, not a saved `gh` session. Trending uses
  a Reach web read and Markdown repository headings, then Reach README/metadata
  reads. Repeat listings change popularity only, never publication dates.

The approved upstream is `Panniantong/Agent-Reach`, revision
`c70ae6da5d39bc90e09ad2ae0575ccc89f31e284` (package version 1.6.1).
Install the official pinned archive, **not an unverified PyPI namesake**.
Do not run upstream setup, login, browser-cookie extraction or auto-update.

## What remains (intentionally)

Agent Reach is a public content reader, not a newspaper production system.
Polyemergence still owns the 205-source catalog, bounded RSS/XML discovery,
official HTML/JSON index adapters, relevance gates, first-party ordering,
Gemini bilingual editing/Method scoring, deduplication, permanent PostgreSQL
history, image checks, static archives/API and Cloudflare publishing.
Discovery is labelled `public_rss` or `publisher_adapter`, never misrepresented
as native Agent Reach RSS. Validated first-party HTML text is reused without
another external read. The old generic `RSSFetcher.parse_feed` and
`ContentProcessor.fetch_and_extract` are not called in the new mode.

GitHub release Atom feeds are discovered through official public release JSON
to obtain the actual `published_at`, not mutable `updated_at` or repository
creation time. Missing/invalid dates are never replaced with the current time.
The Daily Brief still exposes only original publication dates within 48 hours;
archived records and existing URLs are preserved.

Public URLs may be sent to **Jina/Exa** for web reading and article text to
Gemini for editing. Never submit private, authenticated or signed URLs.
Requests have public-address checks, TLS, size/time bounds and explicit errors.
Hosted readers control their own subsequent DNS/redirects; only vetted public
sources belong in the catalog. Their free availability/rate limits are not a
service guarantee. Reddit/X/Hacker News engagement adapters are not configured
in this free migration; no personal account/session is reused to enable them.

## Cloud operation and evidence

Normal collection runs only in GitHub Actions, at **06:00 and 18:00 UTC**.
Both pipeline and default transports refuse local live execution. Unit tests
use injected offline fixtures. Do not set `GITHUB_ACTIONS` locally to bypass it.
No `GH_TOKEN`/`GITHUB_TOKEN` is exposed to content reads (anonymous public API
limits apply). Existing upstream saved configuration also fails closed.

Run **Agent Reach collector verification** for a no-DB/no-LLM canary:

1. Verify installed package version and exact archive/VCS revision.
2. Audit routing for all catalog entries (not a claim of all-source uptime).
3. Read a real official page and GitHub repository with reported backend,
   canonical URL, body size and actual attempts.
4. Check real RSS, release dates, YouTube and Trending capability, recording
   optional blocks without cookies or hidden legacy fallbacks.
5. Check all 30 Chinese specialist sources through the new factory.

Reports are retained as the `agent-reach-verification` Actions artifact.
`refresh_only=true` on the daily workflow still only re-exports existing data.
The health check does not consume Gemini tokens or change articles/source rows.

### Verified 2026-11-15

[Cloud canary 43668950017](https://github.com/wcx0209/ai-news-brief/actions/runs/43668950017)
verified the pinned archive, actual Jina web read, GitHub API repository read,
OpenAI RSS and official release publication dates. All **30/30 Chinese
specialist sources** also returned dated, readable entries through the new
collector. The catalog route audit is **123 RSS + 82 publisher adapters**
(55 HTML indexes, 24 release JSON endpoints, HF, ByteDance and Tencent).
This does not claim every one of the 205 sources was live-tested or published
a fresh story; freshness and editorial relevance are separately enforced.

Known live limitations: GitHub Trending returned `PLATFORM_BLOCKED`; the
Dwarkesh channel RSS returned HTTP 404. A separate test of an already-public
Silicon Valley 101 video also returned `PLATFORM_BLOCKED` from the YouTube
reader. These results are explicit advisories, not successful reads. No cookie,
browser, paid service or legacy fallback was used. Existing archive records
remain accessible; new interviews from blocked reads are skipped.

[First full production cycle 43668648396](https://github.com/wcx0209/ai-news-brief/actions/runs/43668648396)
stored **22 new articles**, exported **40 current briefs** and generated the
archive containing **274 stories**. Cloudflare deployment succeeded. Production
logs show real `agent_reach:jina` reads; already-captured official page content
is separately labelled `publisher_adapter`. The run also recorded 155 skips and
32 failed attempts; a successful job is not a claim that all sources succeeded.

The first run exposed three long-text SimHash/NumPy 2 overflow errors. The fix
uses the library's equivalent batched algorithm, retaining existing 64-bit
fingerprints, and hashing now precedes the permanent fetched-URL marker.
**Retry exact failed collector URLs** can set only existing failed URL markers
due now (1–10 explicit public URLs), excluding URLs already stored as articles.
It changes no article, source ID, publication date, or history and makes no LLM
calls. The next regular cycle applies the usual date, relevance and Method
gates; being retryable is not a promise of publication.

## Explicit rollback

An operator may change `collector.backend` to `legacy` and publish that config.
This is a visible whole-backend rollback, **not automatic fallback per article**.
Unknown backend names fail immediately. Existing database schema, source IDs,
source history and API contract are unchanged, so rollback needs no deletion or
data migration. The supported production workflow remains cloud-hosted.

AI News Brief-derived editing/storage code and its MIT notice remain. Agent
Reach is separately acknowledged at `/en/open-source/` and `/zh/open-source/`.
