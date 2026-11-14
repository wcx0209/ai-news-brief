# Free deployment: Polyemergence

This setup keeps the public site static and places all credentials in GitHub Actions.

## Architecture

```text
Public RSS + Hacker News + YouTube + GitHub Trending
                   ↓
    GitHub Actions (06:00 / 18:00 UTC)
                   ↓
       Gemini OpenAI-compatible endpoint
                   ↓
       Supabase Postgres + pgvector
                   ↓
        web/public/data/latest.json
                   ↓
        Cloudflare Pages static frontend
```

The browser never connects to Postgres and never receives a database URL or API key. Postgres permanently retains the complete article and vector history; the Daily Brief contains only stories whose original source publication time is within the latest 48-hour reading window.

After archive export, `export_observations.py` builds a separate 30-day,
evidence-linked observation set from the public corpus. Field-page export then
renders that set alongside, but not inside, the 48-hour news list. This uses no
additional LLM calls or paid service. The workflow commits all outputs and the
public site remains independent of a local computer.

For a presentation or methodology change, a manual workflow run can set
`refresh_only=true`. It validates the suite and regenerates public exports from
stored Postgres articles without new collection or LLM calls. Scheduled runs
continue normal collection at 06:00 and 18:00 UTC.

Historical archive discovery is field-first at `/en/archive/` and `/zh/archive/`.
Each field has one bilingual static collection with keyword, tag and month
filters (18 visible results per batch); all titles remain readable without JS.
Tag query URLs reuse the same canonical field page rather than generating thin
pages. Related reads are calculated from existing tags, dates and titles, never
by new LLM calls. Matching is conservative, same-field and deduplicated; labels
mean earlier/newer coverage or another source, not verified follow-ups.

The exporter rejects future source/site dates from the corpus, feeds and indexes.
Previously published URLs remain addressable. Retained unlisted articles receive
the current reading template without returning to the curated feed. Future-dated
URLs receive a noindex date-review notice with the complete original public HTML
stored inertly in the page for safe recovery; no database history is deleted.

Source images are discovered and repaired in GitHub Actions, not on a local
computer. The exporter tries source metadata and actual article image candidates,
then verifies complete decoding and the existing 480×270 minimum. Verified URLs
are reused for seven days, and older archives preserve media even after leaving
the 48-hour brief. Each cloud run repairs up to 50 more archived articles, with a
seven-day retry cooldown. No image binaries, public image proxy or extra LLM calls
are introduced. Public-address DNS pinning, per-hop redirect checks, timeouts and
response-size limits protect outbound discovery. Publisher query signatures are
preserved. Browser loading uses at most three candidates and one automatic retry;
successful retries restore the image and source caption. An unavailable external
source may still require a later manual retry. An old image confirmed to be
undersized is not retained as a temporary network failure: the article becomes
text-led when the original has no qualifying image. QbitAI's non-semantic article
container has a host-scoped adapter that excludes the author information area.

Reader likes and comments are handled separately by a Cloudflare Pages Function and a free D1 database. The service stores a salted visitor hash for like deduplication and rate limiting. It never stores the full visitor IP; public comments show only `poly`, the approximate Cloudflare region, and the final three IP characters.

## 1. Gemini

Create a Gemini API key in Google AI Studio, then add:

```text
GEMINI_API_KEY=...
```

The project uses Google's OpenAI-compatible endpoint and `gemini-3.5-flash-lite`, selected for its higher-throughput free tier. Change `INBRIEF_LLM_MODEL_NAME` in the workflow if the available free model changes.

Only public news content is sent for summarization. Do not send private or licensed full-text material that your terms do not permit.

## 2. GitHub Actions

Keep the repository public if you want standard GitHub-hosted Actions to remain free without consuming private-repository minutes.

Run **Polyemergence daily brief** manually once. A successful run will:

1. connect to Supabase Postgres and create or update the schema;
2. connect to the persistent Supabase database and seed the free source catalog;
3. collect and summarize new items;
4. export `web/public/data/latest.json`;
5. commit the refreshed feed.

The source catalog includes six core feeds for each of the nine additional
emerging fields (54 feeds in those fields, 175 configured feeds overall).
`SOURCE_COVERAGE.md` records their scope and verification notes. Seeding uses a
single bulk upsert and retains existing source IDs and historical articles.

After exporting the permanent archive, the workflow also runs
`scripts/export_domain_pages.py`. This refreshes all bilingual field landing
pages, their static news summaries and `field-sitemap.xml` from the cloud feed.
The homepage links to these pages after readers choose a field. Adding a field
to the shared registry automatically adds its landing pages on the next run.

The scheduled runs are 06:00 and 18:00 UTC every day (14:00 and 02:00 Singapore time).

## 3. Cloudflare Pages

Create a Pages project using Git integration and choose this repository.

```text
Framework preset: None
Build command:     (leave blank)
Output directory:  web/public
Production branch: main
```

Connect `polyemergence.com` after the first successful deployment.

For reader interactions, create a D1 database named `polyemergence-interactions` and bind it to the Pages project with the variable name:

```text
INTERACTIONS
```

Add a production secret containing a long random value:

```text
INTERACTIONS_HASH_SALT=...
```

The Pages Function creates its tables and indexes on its first request. Redeploy the latest production build after adding the binding and secret.

## Free-tier fit

- Two daily commits use roughly 60 of Cloudflare Pages' 500 Free-plan monthly builds.
- The site is far below the Free-plan 20,000-file limit.
- Public repositories can use standard GitHub-hosted Actions without metered minutes.
- Supabase's Free plan can host the persistent pgvector database while it remains within the current free limits.
- Gemini offers a limited free developer tier; model and rate limits can change.

## Optional sources

The free profile intentionally excludes X, Reddit, and YouTube because they require persistent browser sessions and are unreliable in unattended free CI. Enable them later on a persistent runner after reviewing their platform terms.
