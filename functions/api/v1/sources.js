import { error, json, loadArticles, options } from "../../_lib/public-data.js";

export async function onRequestOptions() { return options(); }

export async function onRequestGet({ env, request }) {
  try {
    const payload = await loadArticles(env, request);
    const sources = new Map();
    for (const article of payload.items || []) {
      const name = article.source || "Unknown source";
      const entry = sources.get(name) || { name, article_count: 0, domains: new Set(), categories: new Set() };
      entry.article_count += 1;
      if (article.domain) entry.domains.add(article.domain);
      if (article.category) entry.categories.add(article.category);
      sources.set(name, entry);
    }
    const items = [...sources.values()]
      .map((entry) => ({ ...entry, domains: [...entry.domains].sort(), categories: [...entry.categories].sort() }))
      .sort((a, b) => b.article_count - a.article_count || a.name.localeCompare(b.name));
    return json({ object: "list", generated_at: payload.generated_at, count: items.length, items });
  } catch {
    return error("Source directory is temporarily unavailable", 503);
  }
}
