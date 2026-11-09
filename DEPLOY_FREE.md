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

The scheduled runs are 06:00 and 18:00 UTC every day (14:00 and 02:00 Singapore time).

## 3. Cloudflare Pages

Create a Pages project using Git integration and choose this repository.

```text
Framework preset: None
Build command:     (leave blank)
Output directory:  web/public
Production branch: main
```

Connect `polyemergence.com` after the first successful deployment. The static frontend does not require Cloudflare environment variables.

## Free-tier fit

- Two daily commits use roughly 60 of Cloudflare Pages' 500 Free-plan monthly builds.
- The site is far below the Free-plan 20,000-file limit.
- Public repositories can use standard GitHub-hosted Actions without metered minutes.
- Supabase's Free plan can host the persistent pgvector database while it remains within the current free limits.
- Gemini offers a limited free developer tier; model and rate limits can change.

## Optional sources

The free profile intentionally excludes X, Reddit, and YouTube because they require persistent browser sessions and are unreliable in unattended free CI. Enable them later on a persistent runner after reviewing their platform terms.
