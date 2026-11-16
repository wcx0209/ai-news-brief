# Weekly publication

Public editions live at `/en/weekly/` and `/zh/weekly/`, with permanent dated
URLs such as `/en/weekly/2026-11-09/`. The publication is AI-assisted; it does
not claim that an automated audit is human review or independent fact-checking.

The `Polyemergence weekly publication` GitHub Actions workflow runs Mondays at
10:00 UTC (18:00 Singapore). It covers the previous complete Monday–Sunday
Singapore week, using original source publication timestamps rather than crawl
or database insertion dates. Daily collection remains at 06:00/18:00 UTC.

For an unpublished week, Actions reads PostgreSQL in a read-only transaction,
uses the existing cloud Gemini API, selects up to eight main events and two
watchlist events, and generates the bilingual report and plain-language
signal/structure/consequence opening. It checks citations, week boundaries,
translation alignment, evidence diversity, safe URLs, privacy and the final
automated editorial audit before exporting public files. A revised draft must
pass a subsequent automated audit. No article database writes occur.

Only one transient provider retry is allowed, before any successful response.
Quality failures do not trigger repeated generation to hunt for a passing draft.
Failure stops before commit and leaves the previous public issue available;
diagnostics remain in an Actions artifact for 30 days. A published week is
checked before draft retrieval/generation and skipped on repeat runs without
database/model calls, rendering, public-file changes or another publication commit.
The job checks out the latest target branch rather than the original event SHA,
so a queued or re-run job sees editions already published by earlier jobs.
The check applies to scheduled generation and manual artifact publication alike.
Existing editions are not
silently rewritten. Corrections require a separate explicit change preserving
the original publication date.

Manual dispatch can publish an existing `polyemergence-weekly-review` artifact
by entering its numeric `source_run_id` and matching Monday `week_start`. This
records authorization to publish, not a claim of independent verification.
The initial reviewed edition uses run `43792710068`; explicit publication
copyedits preserve attribution and experimental scope without a new model call.

Public JSON under `/data/weekly/` contains an allowlist of edition prose, source
titles/links/dates, coverage and process labels. Raw evidence summaries, prompts,
audit instructions, usage logs and credentials are never exported. Weekly RSS:
`/weekly-en.xml`, `/weekly-zh.xml`; discovery: `/weekly-sitemap.xml` in robots.txt.
Stored publication/modification timestamps remain stable on static re-export.

The website remains on Cloudflare Pages and uses the existing Git deployment
chain. Archive and field navigation regenerate from public static JSON; they
never run a local collector or model. Local work is limited to code editing and
offline fixture tests. The cloud entrypoint rejects execution outside Actions.
