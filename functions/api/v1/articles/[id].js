import { error, findArticle, json, language, loadArticles, options, publicArticle } from "../../../_lib/public-data.js";

export async function onRequestOptions() { return options(); }

export async function onRequestGet({ env, request, params }) {
  try {
    const payload = await loadArticles(env, request);
    const article = findArticle(payload, params.id);
    if (!article) return error("Article not found", 404);
    const lang = language(new URL(request.url).searchParams.get("lang"));
    return json({ object: "article", ...publicArticle(article, lang, true) });
  } catch {
    return error("Article is temporarily unavailable", 503);
  }
}
