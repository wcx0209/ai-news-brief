import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../web/public/app.js", import.meta.url), "utf8");
const executable = source.slice(0, source.lastIndexOf("\nsetLocale(state.locale);"));

function fixture(savedState = null, completedImages = [], { pathname = "/en/fields/ai/", page = "" } = {}) {
  const nodes = new Map();
  const allNodes = new Map();
  const handlers = new Map();
  const timers = new Map();
  let timerId = 0;
  let roots = [];
  let nativeSummaries = [];
  const storage = new Map(savedState ? [["polyemergence-reading-v2", JSON.stringify(savedState)]] : []);
  const context = vm.createContext({
    URL, Date, Intl, Set, CSS: { escape: String }, innerHeight: 844, scrollX: 0, scrollY: 300,
    setTimeout(callback) { timers.set(++timerId, callback); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    location: { pathname, href: `https://polyemergence.com${pathname}`, origin: "https://polyemergence.com", hash: "", reload() { context.reloadCount = (context.reloadCount || 0) + 1; } },
    navigator: { language: "en", userAgent: "test", platform: "test" },
    localStorage: { setItem() {} },
    sessionStorage: { getItem: key => storage.get(key) || null, setItem: (key, value) => storage.set(key, value) },
    document: {
      querySelector(selector) {
        if (!nodes.has(selector)) {
          const classes = new Set();
          nodes.set(selector, { hidden: true, textContent: "", dataset: {}, addEventListener() {}, setAttribute() {}, removeAttribute() {}, classList: { add: name => classes.add(name), contains: name => classes.has(name), toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); } } });
        }
        return nodes.get(selector);
      },
      querySelectorAll(selector) { return allNodes.get(selector) || (selector === "[data-story-id]" ? roots : selector === "[data-summary-details][open]" ? nativeSummaries : selector === "img[data-fallback-image]" ? completedImages : []); },
      addEventListener(name, callback) { handlers.set(name, [...(handlers.get(name) || []), callback]); }, visibilityState: "visible", activeElement: null,
      documentElement: { style: {}, dataset: { page } }, body: { classList: { toggle() {} } }
    },
    requestAnimationFrame: callback => callback(),
    fetch: async () => { throw Error("unconfigured request"); }
  });
  context.window = { navigator: context.navigator, addEventListener() {}, setInterval() {}, matchMedia: () => ({ matches: false }), scrollTo() {}, scrollBy() {} };
  vm.runInContext(`${executable}\nglobalThis.ui = { state, applyBriefWindow, feedFingerprint, renderCard, renderLead, renderEditionSections, visualMarkup, activateImageFallback, inspectLoadedImages, editionNote, evidenceMarkup, plainText, inlineMarkup, fullSummaryMarkup, readingContextMarkup, renderFieldReadingGuidance, legacyTemplates: LEGACY_READING_CONTEXT, setRegistry: value => { domainRegistry = value; }, setLocale, renderFeed, renderFilters, updateFieldLinks, fieldFromUrl, captureReadingState, saveReadingState, summaryMarkup, interactionMarkup, loadFeed, applyFeed, publishedTimeMarkup, observationFreshness, updateObservationFreshness }; globalThis.renderCount = 0; setLocale = () => { renderCount += 1; };`, context);
  return { context, ui: context.ui, nodes, storage, handlers, timers,
    flushTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); },
    setAll: (selector, values) => allNodes.set(selector, values), setRoots(value) { roots = value; }, setNativeSummaries(value) { nativeSummaries = value; } };
}

function article(id = "one", overrides = {}) {
  return { id, source: "Example", url: "https://example.com/story", domain: "ai", category: "company", importance: 80, source_published_at: new Date().toISOString(), scores: { confidence: 80 }, en: { title: "A complete readable headline", summary: "Short", full_summary: "Longer summary" }, ...overrides };
}

function mediaImage({ src = "https://images.example.com/original.jpg?signature=keep", candidates = [], width = 1_200, height = 675, complete = false } = {}) {
  const classes = new Set(), articleClasses = new Set(), requests = [];
  const note = { hidden: true }, caption = { textContent: "Source image · Example" }, captionBox = { hidden: false };
  const retry = { hidden: true, closest: () => visual };
  const visual = { dataset: { mediaSource: "Example" },
    classList: { add: value => classes.add(value), remove: value => classes.delete(value) },
    querySelector: selector => ({ "[data-image-unavailable-note]": note, ".media-caption a": caption, ".media-caption": captionBox, "[data-image-retry]": retry, "img[data-fallback-image]": image }[selector]),
    closest: () => ({ classList: { add: value => articleClasses.add(value), remove: value => articleClasses.delete(value) } }) };
  const image = { _src: src, hidden: false, naturalWidth: width, naturalHeight: height, complete, dataset: { imageCandidates: JSON.stringify(candidates) },
    closest: () => visual, matches: selector => selector === "img[data-fallback-image]", getAttribute: name => name === "src" ? image._src : null,
    get src() { return this._src; }, set src(value) { this._src = value; requests.push(value); this.complete = false; this.naturalWidth = 0; this.naturalHeight = 0; } };
  return { image, visual, caption, captionBox, note, retry, classes, articleClasses, requests };
}

function contextMeta(id = "one") {
  return { scope: "article_specific", validation: "source_grounded", version: 1, article_id: id, source_url: "https://example.com/story" };
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
  const markup = ui.renderCard(article("safe", { image_url: "https://example.com/image.jpg", evidence: { type: "official_release", stage: "unspecified" }, reading_context: { en: "Check independent deployment evidence." }, reading_context_meta: contextMeta("safe"), tags: ["proof <not promise>"], related_domains: ["energy_storage", "energy_storage", "space_economy", "neurotechnology"] }));
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

test("article reading context requires exact article/source binding and rejects every old generic checklist", () => {
  const { ui } = fixture();
  const value = "The reported 24-hour run still lacks an independently measured failure rate.";
  const valid = article("one", { reading_context: { en: value }, reading_context_meta: contextMeta() });
  assert.match(ui.readingContextMarkup(valid), /reported 24-hour run/);
  assert.equal(ui.readingContextMarkup({ ...valid, reading_context_meta: undefined }), "");
  for (const change of [{ scope: "domain" }, { validation: "inferred" }, { version: "1" }, { article_id: "other" }, { source_url: "https://other.example/story" }]) {
    assert.equal(ui.readingContextMarkup({ ...valid, reading_context_meta: { ...contextMeta(), ...change } }), "");
  }
  assert.equal(ui.legacyTemplates.size, 24);
  for (const generic of ui.legacyTemplates) {
    assert.equal(ui.readingContextMarkup({ ...valid, reading_context: { en: generic } }), "");
    assert.doesNotMatch(ui.renderCard({ ...valid, reading_context: { en: generic } }), /class="story-context"/);
  }
  assert.equal(ui.readingContextMarkup({ ...valid, reading_context: { en: "  CHECK THE TASK, VERIFICATION METHOD AND CLASSICAL BASELINE BEFORE TREATING A CLAIMED QUANTUM ADVANTAGE AS A GENERAL CAPABILITY!!!\n" } }), "");
  for (const invalid of ["short", "x".repeat(801), "A <script>alert(1)</script> claim", "An <em>unverified</em> claim"]) {
    assert.equal(ui.readingContextMarkup({ ...valid, reading_context: { en: invalid } }), "");
  }
  assert.equal(ui.readingContextMarkup({ ...valid, reading_context: { zh: "这里只提供中文，英文页面不显示。" } }), "");
});

test("current and future registry reading guides cannot pass as article-specific context even with valid metadata", () => {
  const { ui } = fixture();
  const guidance = "Review test conditions and durability before generalising this future technology.";
  ui.setRegistry([{ id: "future_field", label: { en: "Future field", zh: "未来领域" }, reading_guidance: { en: guidance, zh: "先关注测试条件与耐久性，再判断这项未来技术能否普遍适用。" } }]);
  const item = article("one", { reading_context_meta: contextMeta(), reading_context: { en: guidance.toUpperCase().replace(/\.$/, "!!!") } });
  assert.equal(ui.readingContextMarkup(item), "");
  assert.equal(ui.readingContextMarkup({ ...item, reading_context: { en: "先关注测试条件与耐久性，再判断这项未来技术能否普遍适用！" } }), "");
  assert.match(ui.readingContextMarkup({ ...item, reading_context: { en: "This reported 24-hour test has no published long-duration durability result." } }), /24-hour test/);
});

test("field guidance appears only once in a collapsed domain-level guide, never as repeated article context", () => {
  const { ui, nodes } = fixture();
  const value = "Check the trial setting, duration and replication before generalising.";
  ui.setRegistry([{ id: "ai", label: { en: "AI", zh: "人工智能" }, reading_guidance: { en: value, zh: "关注试验条件、时长和复现，再判断能否推广。" } }]);
  ui.state.domain = "ai";
  ui.renderFieldReadingGuidance();
  const section = nodes.get("#field-reading-guidance");
  assert.equal(section.hidden, false);
  assert.equal(section.dataset.field, "ai");
  assert.match(section.innerHTML, /^<details><summary>Reading guide<\/summary>/);
  assert.match(section.innerHTML, /General field guidance, not verification of this story\./);
  assert.equal(section.innerHTML.split(value).length - 1, 1);
  assert.doesNotMatch(ui.renderEditionSections([article("a"), article("b")]), /class="story-context"|Check the trial setting/);
  ui.state.domain = null;
  ui.renderFieldReadingGuidance();
  assert.equal(section.hidden, true);
  ui.state.domain = "ai";
  ui.state.locale = "zh";
  ui.renderFieldReadingGuidance();
  assert.match(section.innerHTML, /<summary>阅读提示<\/summary>/);
  assert.match(section.innerHTML, /领域通用指引，不是对单篇报道的核验结论/);
});

test("Tech News hub keeps its SEO and static field overview through hydration, without exposing a mixed feed", () => {
  const { ui, nodes, context, setAll } = fixture(null, [], { pathname: "/en/tech-news/", page: "tech-news" });
  context.document.title = "Tech News | Original SEO";
  const description = context.document.querySelector('meta[name="description"]');
  description.content = "Original tech news overview description";
  const h1 = { dataset: { copy: "tagline" }, innerHTML: "Tech News" };
  const promise = { dataset: { copy: "promise" }, innerHTML: "Original overview introduction" };
  setAll('[data-copy]', [h1, promise]);
  const languages = ["en", "zh"].map(locale => ({ dataset: { localeButton: locale }, setAttribute() {}, removeAttribute() {} }));
  const fieldsLink = {};
  setAll('[data-locale-button]', languages);
  setAll('[data-fields-link]', [fieldsLink]);
  const hub = context.document.querySelector("#tech-news-hub");
  hub.innerHTML = "Independent static field overview";
  const fields = context.document.querySelector("#field-grid");
  fields.innerHTML = "Do not hydrate the hub into homepage cards";
  ui.state.feed = { generated_at: new Date().toISOString(), items: [article()] };
  ui.state.domain = "ai";
  ui.setLocale("en");
  assert.equal(context.document.title, "Tech News | Original SEO");
  assert.equal(description.content, "Original tech news overview description");
  assert.equal(h1.innerHTML, "Tech News");
  assert.equal(promise.innerHTML, "Original overview introduction");
  assert.equal(hub.innerHTML, "Independent static field overview");
  assert.equal(fields.innerHTML, "Do not hydrate the hub into homepage cards");
  assert.equal(ui.state.domain, null);
  for (const selector of ["#fields", "#brief", "#field-observations", "#field-seo-content", "#field-reading-guidance"]) assert.equal(nodes.get(selector).hidden, true);
  assert.equal(languages[1].href, "/zh/tech-news/");
  assert.equal(fieldsLink.href, "/en/#fields");
  context.location.href += "?field=ai";
  assert.equal(ui.fieldFromUrl(), null);
});

test("lead uses the same heading, image, body order inside lead-copy", () => {
  const { ui, nodes } = fixture();
  ui.renderLead(article("one", { image_url: "https://example.com/image.jpg" }));
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

test("technical double-underscore identifiers survive titles and summaries after hydration", () => {
  const { ui } = fixture();
  const text = "**Checkpoint** uses `__init__` and __checkpoint_key__, not C* truncation";
  assert.equal(ui.plainText(text), "Checkpoint uses __init__ and __checkpoint_key__, not C* truncation");
  assert.match(ui.inlineMarkup(text), /<strong>Checkpoint<\/strong> uses <code>__init__<\/code> and __checkpoint_key__/);
  const markup = ui.renderCard(article("technical", { en: { title: text, summary: "Preserve __init__", full_summary: "Inspect `__checkpoint_key__`" } }));
  assert.match(markup, /Checkpoint uses __init__ and __checkpoint_key__/);
  assert.match(markup, /Preserve __init__/);
  assert.match(markup, /<code>__checkpoint_key__<\/code>/);
});

test("expanded summaries safely render explicit Markdown headings and paragraphs without rewriting content", () => {
  const { ui } = fixture();
  const raw = "##背景与定位\nFirst **bold** paragraph with `__init__`.\n\n### Technical detail\n#include <header>\nLiteral <img src=x onerror=alert(1)> and `**not bold**`.";
  const markup = ui.fullSummaryMarkup(raw);
  assert.match(markup, /^<h4>背景与定位<\/h4><p>First <strong>bold<\/strong> paragraph with <code>__init__<\/code>\.<\/p>/);
  assert.match(markup, /<h4>Technical detail<\/h4><p>#include &lt;header&gt;/);
  assert.match(markup, /Literal &lt;img src=x onerror=alert\(1\)&gt;/);
  assert.match(markup, /<code>\*\*not bold\*\*<\/code>/);
  assert.doesNotMatch(markup, /<img|<script|<h4>#?include|##背景/);
});

test("an SSR native summary opened before hydration stays expanded in the live card", () => {
  const { ui, setNativeSummaries } = fixture();
  setNativeSummaries([{ closest: () => ({ dataset: { storyId: "one" } }) }]);
  ui.applyFeed({ generated_at: new Date().toISOString(), items: [article()] });
  assert.equal(ui.state.reading.one.summaryOpen, true);
  assert.match(ui.summaryMarkup({ summary: "Preview", fullSummary: "Complete content" }, article()), /data-summary-toggle aria-expanded="true"/);
});

test("missing evidence stays unknown and absent images are text-led without SVG placeholders", () => {
  const { ui, nodes } = fixture();
  assert.match(ui.evidenceMarkup(article()), /Source type not yet identified/);
  assert.doesNotMatch(ui.evidenceMarkup(article()), /Stage not specified/);
  assert.match(ui.evidenceMarkup(article(), true), /Stage not specified/);
  assert.match(ui.renderCard(article()), /story-card is-feature is-text-led/);
  assert.match(ui.visualMarkup(article()), /Text report · No source image available/);
  assert.doesNotMatch(ui.visualMarkup(article()), /<svg|<figure|<img|brand-cover/);
  ui.renderLead(article());
  assert.equal(nodes.get("#lead-story").classList.contains("is-text-led"), true);
  assert.doesNotMatch(nodes.get("#lead-story").innerHTML, /<figure|brand-cover/);
});

test("lead and feature images have conservative linked captions; video thumbnails are identified separately", () => {
  const { ui } = fixture();
  const source = "Example <source>";
  const markup = ui.visualMarkup(article("image", { source, image_url: "https://example.com/image.jpg?a=1&b=2" }));
  assert.match(markup, /^<figure class="card-visual"/);
  assert.match(markup, /<div class="visual-media"><img/);
  assert.match(markup, /<figcaption class="media-caption"><a href="https:\/\/example\.com\/story"/);
  assert.match(markup, /Source image · Example &lt;source&gt;/);
  assert.match(markup, /data-media-source="Example &lt;source&gt;"/);
  assert.match(markup, /a=1&amp;b=2/);
  assert.doesNotMatch(markup, /photograph|copyright|official image|<svg/i);
  const video = ui.visualMarkup(article("video", { url: "https://www.youtube.com/watch?v=abcdefghijk" }));
  assert.match(video, /Video thumbnail · Example/);
  assert.match(video, /https:\/\/i\.ytimg\.com\/vi\/abcdefghijk\/hqdefault.jpg/);
});

test("only the first three remaining stories become features; extra stories are image-free briefs with unchanged order", () => {
  const { ui } = fixture();
  const items = Array.from({ length: 6 }, (_, index) => article(`id${index}`, { image_url: "https://example.com/pic.jpg", importance: 90 - index }));
  const original = JSON.stringify(items);
  const markup = ui.renderEditionSections(items);
  assert.equal((markup.match(/class="story-card is-feature/g) || []).length, 3);
  assert.equal((markup.match(/class="story-card is-brief/g) || []).length, 3);
  assert.match(markup, /feature-section.*edition-subheading">Highlights/s);
  assert.match(markup, /brief-section.*edition-subheading">More briefs/s);
  const brief = markup.slice(markup.indexOf('<section class="brief-section">'));
  assert.doesNotMatch(brief, /<figure|<img|card-visual|No source image available/);
  const ids = [...markup.matchAll(/data-story-id="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(ids, items.map(item => item.id));
  assert.equal(JSON.stringify(items), original);
  assert.equal(ui.renderEditionSections([]), "");
  assert.doesNotMatch(ui.renderEditionSections(items.slice(0, 2)), /brief-section/);
});

test("image errors and low-resolution images become text notes and never retain a caption claiming the image is visible", () => {
  const { ui, handlers } = fixture();
  const classNames = new Set();
  const articleClasses = new Set();
  const note = { hidden: true };
  const caption = { textContent: "Source image · Example" };
  const visual = { dataset: { mediaSource: "Example" }, classList: { add: name => classNames.add(name) }, querySelector: selector => selector === "[data-image-unavailable-note]" ? note : caption, closest: () => ({ classList: { add: name => articleClasses.add(name) } }) };
  const image = { hidden: false, naturalWidth: 120, naturalHeight: 90, closest: () => visual, matches: selector => selector === "img[data-fallback-image]" };
  handlers.get("load").forEach(handler => handler({ target: image }));
  assert.equal(image.hidden, true);
  assert.equal(note.hidden, false);
  assert.ok(classNames.has("is-text-visual"));
  assert.ok(articleClasses.has("is-text-led"));
  assert.equal(caption.textContent, "Original image temporarily unavailable · Example");
  caption.textContent = "Source image · Example";
  image.hidden = false;
  handlers.get("error").forEach(handler => handler({ target: image }));
  assert.equal(image.hidden, true);
  assert.match(caption.textContent, /temporarily unavailable/);
});

test("SSR images completed before the deferred app loads are checked once, while healthy and pending images are preserved", () => {
  function image(width, height, complete) {
    const note = { hidden: true };
    const caption = { textContent: "Source image · Example" };
    const visual = { dataset: { mediaSource: "Example" }, classList: { add() {} }, querySelector: selector => selector === "[data-image-unavailable-note]" ? note : caption, closest: () => ({ classList: { add() {} } }) };
    return { hidden: false, naturalWidth: width, naturalHeight: height, complete, closest: () => visual, note, caption };
  }
  const failed = image(0, 0, true);
  const small = image(240, 135, true);
  const healthy = image(1_200, 675, true);
  const pending = image(0, 0, false);
  fixture(null, [failed, small, healthy, pending]);
  assert.equal(failed.hidden, true);
  assert.equal(small.hidden, true);
  assert.equal(failed.note.hidden, false);
  assert.match(failed.caption.textContent, /temporarily unavailable/);
  assert.equal(healthy.hidden, false);
  assert.equal(pending.hidden, false);
});

test("source images try at most three safe distinct candidates, then the unchanged original once, and restore after success", () => {
  const page = fixture();
  const original = "https://images.example.com/original.jpg?signature=keep";
  const media = mediaImage({ candidates: [original, "javascript:alert(1)", "https://user:secret@example.com/a.jpg", "https://images.example.com/two.png", "https://images.example.com/three.png", "https://images.example.com/ignored.png"] });
  const emit = type => page.handlers.get(type).forEach(handler => handler({ target: media.image }));
  emit("error");
  assert.deepEqual(media.requests, ["https://images.example.com/two.png"]);
  assert.equal(media.image.loading, "eager");
  assert.equal(media.image.hidden, false);
  assert.equal(media.note.hidden, true);
  assert.equal(media.captionBox.hidden, true, "do not claim a source picture is visible while replacement loads");
  media.image.naturalWidth = 479; media.image.naturalHeight = 675;
  emit("load");
  assert.equal(media.requests.at(-1), "https://images.example.com/three.png");
  emit("error");
  emit("error");
  assert.equal(page.timers.size, 1, "duplicate errors do not schedule extra retries");
  page.flushTimers();
  assert.equal(media.requests.at(-1), original, "signed parameters remain unchanged");
  emit("error");
  assert.equal(media.requests.length, 3, "two alternates and one original retry, no unbounded requests");
  assert.equal(media.image.hidden, true);
  assert.equal(media.note.hidden, false);
  assert.equal(media.retry.hidden, false);
  assert.ok(media.classes.has("is-text-visual"));
  assert.ok(media.articleClasses.has("is-text-led"));
  for (let i = 0; i < 5; i += 1) emit("error");
  assert.equal(media.requests.length, 3);
  media.image.naturalWidth = 480; media.image.naturalHeight = 270;
  emit("load");
  assert.equal(media.image.hidden, false);
  assert.equal(media.note.hidden, true);
  assert.equal(media.retry.hidden, true);
  assert.equal(media.caption.textContent, "Source image · Example");
  assert.equal(media.captionBox.hidden, false);
  assert.equal(media.classes.has("is-text-visual"), false);
  assert.equal(media.articleClasses.has("is-text-led"), false);
});

test("cached failed images retry once, pending lazy images do not, and a manual retry can recover", () => {
  const failed = mediaImage({ width: 0, height: 0, complete: true });
  const pending = mediaImage({ width: 0, height: 0, complete: false });
  const page = fixture(null, [failed.image, pending.image]);
  assert.equal(page.timers.size, 1);
  assert.equal(pending.requests.length, 0);
  page.ui.inspectLoadedImages();
  assert.equal(page.timers.size, 1);
  page.flushTimers();
  page.handlers.get("error").forEach(handler => handler({ target: failed.image }));
  assert.equal(failed.retry.hidden, false);
  let prevented = false;
  const target = { closest: selector => selector === "[data-image-retry]" ? failed.retry : null };
  page.handlers.get("click").forEach(handler => handler({ target, preventDefault() { prevented = true; } }));
  assert.equal(prevented, true);
  assert.equal(failed.requests.length, 2);
  assert.equal(failed.image.loading, "eager");
  assert.equal(failed.image.hidden, false);
  assert.equal(failed.retry.hidden, true);
  failed.image.naturalWidth = 800; failed.image.naturalHeight = 600;
  page.handlers.get("load").forEach(handler => handler({ target: failed.image }));
  assert.equal(failed.caption.textContent, "Source image · Example");
  assert.equal(failed.note.hidden, true);
});

test("hydrated image markup exports bounded safe candidates and a hidden accessible manual retry", () => {
  const { ui } = fixture();
  const markup = ui.visualMarkup(article("safe-image", { image_url: "https://images.example.com/one.jpg", image_candidates: ["https://images.example.com/one.jpg", "javascript:alert(1)", "https://u:p@images.example.com/private", "https://images.example.com/two.jpg", "https://images.example.com/three.jpg", "https://images.example.com/four.jpg"] }));
  assert.match(markup, /data-image-candidates=/);
  assert.match(markup, /two\.jpg/);
  assert.match(markup, /three\.jpg/);
  assert.doesNotMatch(markup, /javascript|private|four\.jpg/);
  assert.match(markup, /<button type="button" data-image-retry hidden>Retry image<\/button>/);
});

test("edition note uses the actual feed timestamp in SGT and the 48-hour window, not an invented issue number", () => {
  const { ui } = fixture();
  const note = ui.editionNote({ generated_at: "2026-11-12T00:30:00Z" });
  assert.match(note, /12 Nov 2026/);
  assert.match(note, /08:30 SGT · Past 48 hours/);
  assert.doesNotMatch(note, /issue|edition [0-9]/i);
  assert.equal(ui.editionNote({ generated_at: "invalid" }), "");
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
