# Polyemergence frontend

## Current homepage promise

The homepage introduces the publication, then asks readers to choose a field
before it displays news. The selected field is explicit in the URL and retained
when switching language; there is no default mixed-field feed.

- English headline: **Tech moves fast. Know what matters.**
- Chinese headline: **科技在变。看清重点。**
- English support: Essential developments across AI, biotech, energy and
  more—selected, sourced and explained.
- Chinese support: 每天精选 AI、生命科技、能源等前沿领域的重要进展，附上原始来源与影响摘要。

The headline expresses the reader benefit. Domain navigation provides the scope;
the Method section explains how importance is assessed. Keep the two locale
versions separate on screen.

## Reading and evidence conventions

The homepage is a compact field chooser, not a mixed news feed. Field pages use
a compact heading and put readable, linked news titles before scoring. Preserve
the approved layered mark and black/grey/orange palette; source images remain
in natural colour, with diagrams and brand covers kept complete.

Daily Brief is strictly the last 48 hours by original publication time. Ordinary
items must reach importance 65; academic items retain importance 70, confidence
65 and a maximum of two. These are revisable editorial gates, not scientific
probabilities. Do not fill an empty field with a below-threshold story. Undated
GitHub Trending repositories are not news publications and are excluded from
Daily Brief; a real tagged release with an original date remains eligible.
Recurring chart appearances may update momentum but never publication dates.

Evidence labels describe provenance, not independent verification. Official
releases and preprints keep attribution. Technical maturity is only displayed
when the supplied material explicitly supports it; otherwise it is unspecified.
One primary field is retained, with at most two cautiously matched related
fields. Reading context is identified as an editorial lens, not a new fact.

Field observations cover a separate 30-day evidence window. They are generated
from public archived items, never from fabricated evidence or new predictions.
This first release keeps every card a tentative signal: heuristic report groups
cannot establish distinct events, even across publishers or languages. There is
no automatic promotion to a trend. Each observation links actual sources and
explains uncertainty and what to check next; an eventual stronger label requires
explicit event-identity review as well as multiple events and publishers.

Background checks must not interrupt reading or replace comment drafts. Apply
changed news only after the reader chooses to update; unchanged data does not
rebuild cards. Preserve draft, disclosure and reading-position state.

The original AI News Brief collector is retained under the MIT license. This fork adds:

- a Polyemergence-branded static frontend in `web/public/`;
- exclusive English/Chinese display with an `EN | 中` switch;
- natural-color editorial images when source pages expose a valid Open Graph image;
- a browserless free collection profile in `config.free.yaml`;
- idempotent source seeding and static JSON export scripts;
- a daily GitHub Actions workflow;
- Cloudflare Pages deployment instructions.

## Local frontend preview

Serve `web/public` with any static server. The bundled JSON is visibly marked as demo data until the first successful collector run.

## Data contract

The frontend reads `web/public/data/latest.json`. Each item includes localized `en` and `zh` fields, but the interface renders only the selected locale. Source URLs are preserved so every brief remains traceable.

## Brand source

The approved direction is documented in the parent workspace at:

```text
brand/polyemergence/BRAND_GUIDE.md
brand/polyemergence/concepts/direction-bc-original-logo-orange-top-v8.png
```
