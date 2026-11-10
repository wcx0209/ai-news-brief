import { clampInt, error, json, loadArticles, options, searchArticles } from "../../_lib/public-data.js";

export async function onRequestOptions() { return options(); }

export async function onRequestGet({ env, request }) {
  const url = new URL(request.url);
  const query = (url.searchParams.get("q") || "").trim();
  if (!query) return error("The q query parameter is required");
  if (query.length > 200) return error("The q query parameter must be 200 characters or fewer");
  try {
    const payload = await loadArticles(env, request);
    const limit = clampInt(url.searchParams.get("limit"), 10, 1, 50);
    const items = searchArticles(payload, query, url.searchParams.get("lang"), limit);
    return json({ object: "search_results", query, count: items.length, items });
  } catch {
    return error("Search is temporarily unavailable", 503);
  }
}
