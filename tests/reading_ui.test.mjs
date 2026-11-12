import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../web/public/app.js", import.meta.url), "utf8");
const executable = source.slice(0, source.lastIndexOf("\nsetLocale(state.locale);"));

function fixture(savedState = null) {
  const nodes = new Map();
  const handlers = new Map();
  let roots = [];
  let nativeSummaries = [];
  const storage = new Map(savedState ? [["polyemergence-reading-v2", JSON.stringify(savedState)]] : []);
  const context = vm.createContext({
    URL, Date, Intl, Set, CSS: { escape: String }, innerHeight: 844, scrollX: 0, scrollY: 300,
    location: { pathname: "/en/fields/ai/", href: "https://polyemergence.com/en/fields/ai/", origin: "https://polyemergence.com", hash: "", reload() { context.reloadCount = (context.reloadCount || 0) + 1; } },
    navigator: { language: "en", userAgent: "test", platform: "test" },
    localStorage: { setItem() {} },
    sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
    document: {
      querySelector(selector) { if (!nodes.has(selector)) nodes.set(selector, { hidden: true, textContent: "", dataset: {}, addEventListener() {} }); return nodes.get(selector); },
      querySelectorAll(selector) { return selector === "[data-story-id]" ? roots : selector === "[data-summary-details][open]" ? nativeSummaries : []; },
      addEventListener(name, callback) { handlers.set(name, [...(handlers.get(name) || []), callback]); }, visibilityState: "visible", activeElement: null,
      documentElement: { style: {} }, body: { classList: { toggle() {} } }
    },
    requestAnimationFrame: callback => callback(),
    fetch: async () => { throw Error("unconfigured request"); }
  });
  context.window = { navigator: context.navigator, addEventListener() {}, setInterval() {}, matchMedia: () => ({ matches: false }), scrollTo() {}, scrollBy() {} };
  vm.runInContext(`${executable}\nglobalThis.ui = { state, applyBriefWindow, feedFingerprint, renderCard, renderLead, evidenceMarkup, coverArtwork, captureReadingState, saveReadingState, summaryMarkup, interactionMarkup, loadFeed, applyFeed, publishedTimeMarkup, observationFreshness, updateObservationFreshness }; globalThis.renderCount = 0; setLocale = () => { renderCount += 1; };`, context);
  return { context, ui: context.ui, nodes, storage, handlers, setRoots(value) { roots = value; }, setNativeSummaries(value) { nativeSummaries = value; } };
}

function article(id = "one", overrides = {}) {
  return { id, source: "Example", url: "https://example.com/story", domain: "ai", category: "company", importance: 80, source_published_at: new Date().toISOString(), scores: { confidence: 80 }, en: { title: "A complete readable headline", summary: "Short", full_summary: "Longer summary" }, ...overrides };
}

test("brief rejects weak, future, expired and GitHub Trending while retaining actual releases and only two eligible papers", () => {
  const { ui } = fixture();
  const age = hours => new Date(Date.now() - hours * 3_600_000).toISOString();
  const items = [article("good"), article("trending", { source: "GitHub Trending", importance: 88 }), article("release", { source: "Official GitHub Releases", category: "open_source" }), article("weak", { importance: 64 }), article("future", { source_published_at: age(-1) }), article("old", { source_published_at: age(49) }), article("paper", { category: "academia", importance: 69 }), article("uncertain", { category: "academia", importance: 90, scores: { confidence: 64 } }), article("paper1", { category: "academia", importance: 88 }), article("paper2", { category: "academia", importance: 82 }), article("paper3", { category: "academia", importance: 75 })];
  assert.deepEqual(Array.from(ui.applyBriefWindow({ items }).items, item => item.id), ["good", "release", "paper1", "paper2"]);
});

test("first-seen dates never masquerade as source publication dates or fall back to a refreshed publication time", () => {
  const { ui } = fixture();
  const firstSeen = "2026-11-01T06:00:00Z";
  const markup = ui.publishedTimeMarkup(article("trending", { source: "GitHub Trending", first_seen_at: firstSeen, site_published_at: "2026-11-02T06:00:00Z" }));
  assert.match(markup, /First seen/);
  assert.match(markup, new RegExp(firstSeen));
  assert.doesNotMatch(markup, /Published/);
  assert.equal(ui.publishedTimeMarkup(article("missing", { source: "GitHub Trending" })), "");
  assert.equal(ui.publishedTimeMarkup(article("missing", { date_basis: "first_seen" })), "");
  assert.match(ui.publishedTimeMarkup(article("seen", { date_basis: "first_seen", site_published_at: firstSeen })), /First seen/);
});

test("a newer feed flags the fixed observation snapshot and snapshots over 30 days hide old cards", () => {
  const { ui, nodes } = fixture();
  const now = Date.now();
  const grid = { hidden: false };
  const link = { textContent: "" };
  const notice = { hidden: true, querySelector: () => link };
  const section = { dataset: { generatedAt: new Date(now - 3_600_000).toISOString() }, querySelector: selector => selector === ".observation-grid" ? grid : selector === "[data-observation-update-status]" ? notice : null };
  nodes.set("#field-observations", section);
  ui.state.feed = { generated_at: new Date(now).toISOString(), items: [] };
  ui.updateObservationFreshness();
  assert.equal(notice.hidden, false);
  assert.equal(grid.hidden, false);
  assert.match(link.textContent, /newer update/);
  section.dataset.generatedAt = new Date(now - 31 * 86_400_000).toISOString();
  ui.updateObservationFreshness();
  assert.equal(grid.hidden, true);
  assert.match(link.textContent, /over 30 days old/);
  section.dataset.generatedAt = new Date(now + 1_000).toISOString();
  ui.updateObservationFreshness();
  assert.equal(grid.hidden, false);
  assert.equal(notice.hidden, true);
});

test("the observation refresh link reloads a same-page hash after saving the reading draft", () => {
  const { ui, context, handlers, storage } = fixture();
  ui.state.reading.one = { draft: "Keep this draft" };
  let prevented = false;
  const link = { href: "https://polyemergence.com/en/fields/ai/#field-observations" };
  const event = { target: { closest: selector => selector === "[data-observation-refresh]" ? link : null }, preventDefault() { prevented = true; } };
  handlers.get("click").forEach(handler => handler(event));
  assert.equal(prevented, true);
  assert.equal(context.reloadCount, 1);
  assert.equal(JSON.parse(storage.get("polyemergence-reading-v2")).articles.one.draft, "Keep this draft");
  link.href = "https://polyemergence.com/zh/fields/ai/#field-observations";
  prevented = false;
  handlers.get("click").forEach(handler => handler(event));
  assert.equal(prevented, false);
  assert.equal(context.reloadCount, 1);
});

test("cards put linked title and metadata before the image, then summary; context and tags stay folded", () => {
  const { ui } = fixture();
  const markup = ui.renderCard(article("safe", { evidence: { type: "official_release", stage: "unspecified" }, reading_context: { en: "Check independent deployment evidence." }, tags: ["proof <not promise>"], related_domains: ["energy_storage", "energy_storage", "space_economy", "neurotechnology"] }));
  assert.ok(markup.indexOf("<h3><a") < markup.indexOf('class="story-meta"'));
  assert.ok(markup.indexOf('class="story-meta"') < markup.indexOf('class="card-visual"'));
  assert.ok(markup.indexOf('class="card-visual"') < markup.indexOf('class="story-body"'));
  assert.ok(markup.indexOf('class="story-body"') < markup.indexOf('class="story-summary"'));
  assert.match(markup, /Official release/);
  assert.match(markup, /Stage not specified/);
  assert.match(markup, /What to watch · editorial perspective/);
  assert.match(markup, /not independent verification/);
  assert.equal((markup.match(/class="story-related"/g) || []).length, 1);
  assert.equal((markup.match(/ × /g) || []).length, 2);
  assert.doesNotMatch(markup, /trust-strip|card-plane|Expand full summary|independently verified/);
  assert.ok(markup.indexOf("Importance 80") > markup.indexOf("<summary>Selection rationale</summary>"));
  const screening = markup.slice(markup.indexOf('<details class="screening-details"'), markup.indexOf("</details>"));
  const heading = markup.slice(markup.indexOf('class="story-heading"'), markup.indexOf('class="card-visual"'));
  assert.match(screening, /class="story-context"/);
  assert.match(screening, /class="tags"/);
  assert.match(screening, /proof &lt;not promise&gt;/);
  assert.match(screening, /Stage not specified/);
  assert.doesNotMatch(heading, /story-context|class="tags"|Stage not specified/);
});

test("lead uses the same heading, image, body order inside lead-copy", () => {
  const { ui, nodes } = fixture();
  ui.renderLead(article());
  const markup = nodes.get("#lead-story").innerHTML;
  assert.match(markup, /^\s*<div class="lead-copy">/);
  assert.ok(markup.indexOf('class="story-heading"') < markup.indexOf('class="story-visual"'));
  assert.ok(markup.indexOf('class="story-visual"') < markup.indexOf('class="story-body"'));
  assert.ok(markup.indexOf('class="story-body"') < markup.indexOf('class="story-summary"'));
  assert.equal(nodes.get("#lead-story").dataset.storyId, "one");
  assert.match(markup, /data-share-button/);
  assert.match(markup, /data-comment-form/);
  const toolbar = markup.slice(markup.indexOf('<div class="story-toolbar">'));
  assert.ok(toolbar.indexOf('class="story-actions"') < toolbar.indexOf('class="story-social"'));
  assert.match(toolbar, /data-comment-panel/);
  assert.match(toolbar, /data-comment-form/);
  assert.match(toolbar, /data-comments-toggle aria-expanded="false" aria-label="Comments"/);
  assert.match(toolbar, /data-like aria-pressed="false" aria-label="Like"/);
});

test("a four-line preview can expand every character even with missing or identical full summary", () => {
  const { ui, handlers } = fixture();
  const long = "Long summary with details <not markup>. ".repeat(30);
  for (const fullSummary of ["", long]) {
    const markup = ui.summaryMarkup({ summary: long, fullSummary }, article());
    assert.match(markup, /data-summary-toggle aria-expanded="false"/);
    assert.match(markup, /class="summary-full" data-summary-full hidden/);
    assert.equal((markup.match(/Long summary with details &lt;not markup&gt;\./g) || []).length, 60);
  }
  const short = { hidden: false };
  const full = { hidden: true };
  let expanded = "false";
  const summary = { querySelector: selector => selector === "[data-summary-short]" ? short : full };
  const toggle = { closest: () => summary, getAttribute: () => expanded, setAttribute(name, value) { expanded = value; }, textContent: "" };
  const event = { target: { closest: selector => selector === "[data-summary-toggle]" ? toggle : null } };
  handlers.get("click").forEach(handler => handler(event));
  assert.equal(expanded, "true");
  assert.equal(short.hidden, true);
  assert.equal(full.hidden, false);
  assert.match(toggle.textContent, /Collapse summary/);
});

test("an SSR native summary opened before hydration stays expanded in the live card", () => {
  const { ui, setNativeSummaries } = fixture();
  setNativeSummaries([{ closest: () => ({ dataset: { storyId: "one" } }) }]);
  ui.applyFeed({ generated_at: new Date().toISOString(), items: [article()] });
  assert.equal(ui.state.reading.one.summaryOpen, true);
  assert.match(ui.summaryMarkup({ summary: "Preview", fullSummary: "Complete content" }, article()), /data-summary-toggle aria-expanded="true"/);
});

test("missing evidence stays unknown and artwork never uses a slicing transform", () => {
  const { ui } = fixture();
  assert.match(ui.evidenceMarkup(article()), /Source type not yet identified/);
  assert.doesNotMatch(ui.evidenceMarkup(article()), /Stage not specified/);
  assert.match(ui.evidenceMarkup(article(), true), /Stage not specified/);
  assert.match(ui.coverArtwork("company", "Company", "Source"), /preserveAspectRatio="xMidYMid meet"/);
  assert.doesNotMatch(ui.coverArtwork("company", "Company", "Source"), /slice/);
});

test("same news updates timestamps without rebuilding, and background news waits for consent", async () => {
  const { context, ui, nodes } = fixture();
  const one = article();
  let payload = { generated_at: new Date().toISOString(), items: [one] };
  context.fetch = async () => ({ ok: true, json: async () => payload });
  await ui.loadFeed();
  assert.equal(context.renderCount, 1);
  payload = { ...payload, generated_at: new Date(Date.now() + 1_000).toISOString() };
  await ui.loadFeed({ background: true });
  assert.equal(context.renderCount, 1, "generation time alone must not redraw cards");
  payload = { ...payload, items: [one, article("two")] };
  await ui.loadFeed({ background: true });
  assert.equal(context.renderCount, 1);
  assert.equal(ui.state.feed.items.length, 1);
  assert.equal(ui.state.pendingFeed.items.length, 2);
  assert.equal(nodes.get("#feed-update-notice").hidden, false);
  ui.applyFeed(ui.state.pendingFeed);
  assert.equal(context.renderCount, 2);
  assert.equal(ui.state.feed.items.length, 2);
  assert.equal(ui.state.pendingFeed, null);
});

test("expiration also produces a pending update even when the raw feed is unchanged", async () => {
  const { context, ui } = fixture();
  const old = article("expired", { source_published_at: new Date(Date.now() - 49 * 3_600_000).toISOString() });
  ui.state.feed = { generated_at: new Date().toISOString(), items: [old] };
  context.fetch = async () => ({ ok: true, json: async () => ({ ...ui.state.feed }) });
  await ui.loadFeed({ background: true });
  assert.equal(ui.state.feed.items.length, 1);
  assert.equal(ui.state.pendingFeed.items.length, 0);
  assert.equal(context.renderCount, 0);
});

test("draft, summary, rationale, comments and reading position survive card rebuilds and locale navigation", () => {
  const { ui, storage, setRoots } = fixture();
  ui.state.openComments.add("one");
  const selectors = {
    '[data-comment-form] textarea': { value: "Draft <never execute>" },
    '[data-summary-toggle]': { getAttribute: () => "true" },
    '.screening-details': { open: true }
  };
  setRoots([{ dataset: { storyId: "one" }, querySelector: selector => selectors[selector], getBoundingClientRect: () => ({ top: 160, bottom: 600 }) }]);
  ui.saveReadingState();
  assert.equal(ui.state.reading.one.draft, "Draft <never execute>");
  assert.equal(ui.state.reading.one.summaryOpen, true);
  assert.equal(ui.state.reading.one.screeningOpen, true);
  assert.equal(ui.state.reading.one.commentsOpen, true);
  const saved = JSON.parse(storage.get("polyemergence-reading-v2"));
  assert.equal(saved.position.anchorId, "one");
  assert.equal(saved.position.anchorTop, 160);
  const restored = fixture(saved).ui;
  assert.equal(restored.state.reading.one.draft, "Draft <never execute>");
  assert.match(restored.interactionMarkup(article()), /Draft &lt;never execute&gt;/);
  assert.match(restored.summaryMarkup({ summary: "Short", fullSummary: "Longer" }, article()), /aria-expanded="true"/);
});
