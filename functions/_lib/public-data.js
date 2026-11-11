const SITE = "https://polyemergence.com";

export const API_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, MCP-Protocol-Version",
  "Cache-Control": "public, max-age=60, s-maxage=300, stale-while-revalidate=600",
  "Content-Type": "application/json; charset=utf-8",
  "X-Content-Type-Options": "nosniff",
};

export function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status,
    headers: { ...API_HEADERS, ...headers },
  });
}

export function options() {
  return new Response(null, { status: 204, headers: API_HEADERS });
}

export function error(message, status = 400, details) {
  return json({ error: { message, ...(details ? { details } : {}) } }, status);
}

export function clampInt(value, fallback, minimum, maximum) {
  const parsed = Number.parseInt(value ?? "", 10);
  return Number.isFinite(parsed) ? Math.min(maximum, Math.max(minimum, parsed)) : fallback;
}

export function language(value) {
  return value === "zh" || value === "zh-Hans" ? "zh" : "en";
}

export function category(value) {
  const normalized = String(value || "").trim().toLowerCase().replaceAll("-", "_");
  return /^[a-z][a-z0-9_]{1,31}$/.test(normalized) ? normalized : "";
}

export const domain = category;

export async function loadArticles(env, request) {
  if (!env?.ASSETS?.fetch) {
    throw new Error("Static asset binding is unavailable");
  }
  const dataUrl = new URL("/data/articles.json", request.url);
  const response = await env.ASSETS.fetch(new Request(dataUrl, { method: "GET" }));
  if (!response.ok) {
    throw new Error(`Article data unavailable (${response.status})`);
  }
  return response.json();
}

export function publicArticle(article, locale = "en", includeFull = false) {
  const lang = language(locale);
  const copy = article[lang] || article.en || article.zh || {};
  const output = {
    id: String(article.id),
    title: copy.title || "",
    summary: copy.summary || copy.full_summary || "",
    source: article.source || "Unknown source",
    source_url: article.url,
    canonical_url: article.canonical_urls?.[lang] || `${SITE}/${lang}/`,
    language: lang === "zh" ? "zh-Hans" : "en",
    category: article.category,
    domain: article.domain || "ai",
    importance: article.importance,
    scores: article.scores,
    published_at: article.published_at,
    source_published_at: article.source_published_at,
    tags: article.tags || [],
  };
  if (includeFull) output.full_summary = copy.full_summary || copy.summary || "";
  return output;
}

export function filterArticles(payload, params, { defaultHours = 48 } = {}) {
  const lang = language(params.get("lang"));
  const selectedCategory = category(params.get("category"));
  const selectedDomain = domain(params.get("domain"));
  const limit = clampInt(params.get("limit"), 20, 1, 100);
  const hours = clampInt(params.get("hours"), defaultHours, 1, 8760);
  const generatedAt = Date.parse(payload.generated_at) || Date.now();
  const cutoff = generatedAt - hours * 60 * 60 * 1000;
  const items = (payload.items || [])
    .filter((item) => !selectedDomain || (item.domain || "ai") === selectedDomain)
    .filter((item) => !selectedCategory || item.category === selectedCategory)
    .filter((item) => Date.parse(item.source_published_at || item.published_at) >= cutoff)
    .sort((a, b) => (b.importance - a.importance) || Date.parse(b.published_at) - Date.parse(a.published_at))
    .slice(0, limit)
    .map((item) => publicArticle(item, lang, false));
  return { lang, selectedCategory, selectedDomain, limit, hours, items };
}

function searchableText(article, lang) {
  const primary = article[lang] || {};
  const secondary = article[lang === "en" ? "zh" : "en"] || {};
  return [
    primary.title, primary.summary, primary.full_summary,
    secondary.title, article.source, article.domain, article.category, ...(article.tags || []),
  ].join(" ").toLocaleLowerCase();
}

export function searchArticles(payload, query, locale = "en", limit = 10) {
  const lang = language(locale);
  const terms = String(query || "").trim().toLocaleLowerCase().split(/\s+/u).filter(Boolean).slice(0, 12);
  if (!terms.length) return [];
  return (payload.items || [])
    .map((article) => {
      const haystack = searchableText(article, lang);
      if (!terms.every((term) => haystack.includes(term))) return null;
      const title = (article[lang]?.title || "").toLocaleLowerCase();
      const matches = terms.reduce((sum, term) => sum + (title.includes(term) ? 4 : 1), 0);
      return { article, rank: matches * 1000 + Number(article.importance || 0) };
    })
    .filter(Boolean)
    .sort((a, b) => b.rank - a.rank || Date.parse(b.article.published_at) - Date.parse(a.article.published_at))
    .slice(0, limit)
    .map(({ article }) => publicArticle(article, lang, false));
}

export function findArticle(payload, id) {
  const wanted = String(id || "");
  return (payload.items || []).find((item) => String(item.id) === wanted);
}

export const METHODOLOGY = {
  name: "Polyemergence Method",
  version: "1.0",
  importance_formula: {
    signal: 0.35,
    structure: 0.35,
    consequence: 0.30,
  },
  separate_scores: ["confidence", "momentum"],
  academia_rules: { minimum_importance: 70, minimum_confidence: 65, maximum_per_daily_brief: 2 },
  disclosure: "AI-assisted collection, translation, summarisation, classification and scoring. Original links and publication metadata are retained. Summaries are not independently fact-checked unless explicitly stated.",
  publisher: "PolyEmergence Pte Ltd., Singapore",
  conflict_disclosure: "No current financial or commercial conflict declared.",
  standards_url: `${SITE}/en/standards/`,
};
