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
watchlist events, reads at most one original URL per selected event through the
existing anonymous Agent Reach adapter (10 URLs, four workers, 20-second request
budget, 6,000 characters per source), and generates the bilingual report and plain-language
signal/structure/consequence opening. It checks citations, week boundaries,
translation alignment, evidence diversity, safe URLs, privacy and the final
automated editorial audit before exporting public files. A revised draft must
pass a subsequent automated audit. Automatic release of clinical/patient,
quantum-advantage or executive-change claims additionally requires a cited
original-source excerpt with matching article provenance. Failed reads remain
evidence gaps and block those releases; a successful read establishes what the
publisher says, not independent factual verification. No article database writes occur.

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

Generated titles contain only short, evidence-backed issue themes; the renderer
adds the weekly label, coverage dates and a single brand suffix. Descriptions
state the issue's specific value without keyword stuffing. Original-source
titles and contextual archive links are descriptive, with a visible organization
byline and matching `Article.author` metadata. AI assistance remains disclosed.
Each locale gets a deterministic 1200×630 issue cover generated from its actual
themes and coverage period using local typography in Actions; no image model or
third-party image service is used. It replaces the old generic brand mockup in
the page, sharing metadata and Article image. Chinese typography requires Noto
CJK on Linux and fails closed rather than publishing missing-glyph boxes.

The separate manual `Polyemergence weekly presentation refresh` workflow only
re-renders existing public editions and cover assets. It has no database/model
secrets and explicitly verifies that `/data/weekly/` is byte-for-byte unchanged.
Use it for template/SEO improvements without bypassing the publication duplicate
check, re-generating content or changing original publication dates.

The website remains on Cloudflare Pages and uses the existing Git deployment
chain. Archive and field navigation regenerate from public static JSON; they
never run a local collector or model. Local work is limited to code editing and
offline fixture tests. The cloud entrypoint rejects execution outside Actions.
