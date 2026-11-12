import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const code = await readFile(new URL("../functions/_lib/public-data.js", import.meta.url), "utf8");
const api = await import(`data:text/javascript;base64,${Buffer.from(code).toString("base64")}`);

test("public article keeps evidence, related fields and localized reading context", () => {
  const item = { id: "1", domain: "ai", related_domains: ["energy_storage"], evidence: { type: "official_release", stage: "unspecified" }, reading_context: { en: "Check deployment evidence", zh: "核查部署证据" }, en: { title: "News" }, zh: { title: "新闻" } };
  const result = api.publicArticle(item, "zh");
  assert.equal(result.reading_context, "核查部署证据");
  assert.deepEqual(result.related_domains, ["energy_storage"]);
  assert.equal(result.evidence.stage, "unspecified");
});

test("brief applies real time, threshold, future exclusion and academic cap", () => {
  const now = Date.now();
  const item = (id, importance, age, category = "company", confidence = 90) => ({ id, importance, category, scores: { confidence }, source_published_at: new Date(now - age * 3_600_000).toISOString(), en: { title: id } });
  const payload = { generated_at: new Date(now - 100 * 3_600_000).toISOString(), items: [item("low", 18, 1), item("expired", 99, 49), item("future", 99, -1), item("ok", 65, 2), { ...item("old_trending", 88, 1, "open_source"), source: "GitHub Trending" }, { ...item("release", 77, 1, "open_source"), source: "Qwen Releases" }, item("paper1", 90, 1, "academia"), item("paper2", 85, 2, "academia"), item("paper3", 80, 3, "academia"), item("uncertain", 95, 1, "academia", 64)] };
  const result = api.filterArticles(payload, new URLSearchParams("limit=100"));
  assert.deepEqual(result.items.map(value => value.id), ["paper1", "paper2", "release", "ok"]);
});

test("permanent archive search retains below-threshold historical items", () => {
  const result = api.searchArticles({ items: [{ id: "historic", importance: 18, en: { title: "Lunar greenhouse experiment" } }] }, "greenhouse");
  assert.equal(result.length, 1);
  assert.equal(result[0].id, "historic");
});
