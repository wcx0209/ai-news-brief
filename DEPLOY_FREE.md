# Free deployment: Polyemergence

This setup keeps the public site static and places all credentials in GitHub Actions.

## Architecture

```text
Public RSS + Hacker News + GitHub Trending
                   ↓
        GitHub Actions (daily, UTC 00:15)
                   ↓
       Gemini OpenAI-compatible endpoint
                   ↓
     Ephemeral Postgres + pgvector service
                   ↓
        web/public/data/latest.json
                   ↓
        Cloudflare Pages static frontend
```

The browser never connects to Postgres and never receives an API key. The database exists only for the duration of each workflow run; the published JSON is the durable output.

## 1. Gemini

Create a Gemini API key in Google AI Studio, then add:

```text
GEMINI_API_KEY=...
```

The project uses Google's OpenAI-compatible endpoint and `gemini-3.8-flash`. Change `INBRIEF_LLM_MODEL_NAME` in the workflow if the available free model changes.

Only public news content is sent for summarization. Do not send private or licensed full-text material that your terms do not permit.

## 2. GitHub Actions

Keep the repository public if you want standard GitHub-hosted Actions to remain free without consuming private-repository minutes.

Run **Polyemergence daily brief** manually once. A successful run will:

1. start an isolated pgvector database and create the schema;
2. seed the free RSS catalog;
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

- One daily commit uses roughly 30 of Cloudflare Pages' 500 Free-plan monthly builds.
- The site is far below the Free-plan 20,000-file limit.
- Public repositories can use standard GitHub-hosted Actions without metered minutes.
- The workflow uses a temporary pgvector service, so there is no hosted database bill or database account to maintain.
- Gemini offers a limited free developer tier; model and rate limits can change.

## Optional sources

The free profile intentionally excludes X, Reddit, and YouTube because they require persistent browser sessions and are unreliable in unattended free CI. Enable them later on a persistent runner after reviewing their platform terms.
