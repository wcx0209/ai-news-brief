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

## Explicit rollback

An operator may change `collector.backend` to `legacy` and publish that config.
This is a visible whole-backend rollback, **not automatic fallback per article**.
Unknown backend names fail immediately. Existing database schema, source IDs,
source history and API contract are unchanged, so rollback needs no deletion or
data migration. The supported production workflow remains cloud-hosted.

AI News Brief-derived editing/storage code and its MIT notice remain. Agent
Reach is separately acknowledged at `/en/open-source/` and `/zh/open-source/`.
