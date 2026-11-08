# Polyemergence frontend

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
