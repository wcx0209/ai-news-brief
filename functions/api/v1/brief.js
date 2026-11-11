import { error, filterArticles, json, loadArticles, options } from "../../_lib/public-data.js";

export async function onRequestOptions() { return options(); }

export async function onRequestGet({ env, request }) {
  try {
    const payload = await loadArticles(env, request);
    const url = new URL(request.url);
    const result = filterArticles(payload, url.searchParams);
    return json({
      object: "list",
      generated_at: payload.generated_at,
      window_hours: result.hours,
      domain: result.selectedDomain || null,
      category: result.selectedCategory || null,
      count: result.items.length,
      items: result.items,
      methodology_url: "https://polyemergence.com/api/v1/methodology",
    });
  } catch {
    return error("Public brief is temporarily unavailable", 503);
  }
}
