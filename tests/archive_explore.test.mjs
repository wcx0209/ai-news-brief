import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../web/public/archive-explore.js", import.meta.url), "utf8");
const analytics = await readFile(new URL("../web/public/analytics.js", import.meta.url), "utf8");

function element(extra = {}) {
  const listeners = new Map();
  return { value: "", hidden: false, dataset: {}, attributes: {}, textContent: "", ...extra,
    addEventListener(name, callback) { listeners.set(name, [...(listeners.get(name) || []), callback]); },
    emit(name, event = {}) { (listeners.get(name) || []).forEach(callback => callback({ preventDefault() {}, ...event })); },
    setAttribute(name, value) { this.attributes[name] = value; },
    hasAttribute(name) { return Object.hasOwn(this.attributes, name); },
  };
}

function fixture({ url = "https://polyemergence.com/en/archive/fields/ai/", locale = "en", size = 40, data, loading = false, navigator } = {}) {
  const query = element(), month = element(), tag = element(), reset = element();
  const form = element({ querySelector: selector => ({ '[name="q"]': query, '[name="month"]': month, '[name="tag"]': tag, "[data-archive-reset]": reset }[selector]) });
  const count = element(), empty = element({ hidden: true }), more = element({ hidden: true });
  const entries = (data || Array.from({ length: size }, (_, index) => ({ search: `Story ${index} AI 中文`, tags: JSON.stringify(index % 2 ? ["Models"] : ["Research"]), month: index % 2 ? "2026-10" : "2026-11" })))
    .map(dataset => element({ dataset }));
  const localeLink = element({ href: "https://polyemergence.com/zh/archive/fields/ai/" });
  const handlers = new Map(), windowHandlers = new Map(), events = [], historyCalls = [], timers = new Map();
  const document = {
    readyState: loading ? "loading" : "complete", documentElement: { dataset: { locale }, lang: locale },
    querySelector: selector => ({ "[data-archive-filters]": form, "[data-archive-count]": count, "[data-archive-empty]": empty, "[data-archive-more]": more }[selector]),
    querySelectorAll: selector => selector === "[data-archive-entry]" ? entries : selector === "[data-archive-locale]" ? [localeLink] : [],
    addEventListener(name, callback) { handlers.set(name, [...(handlers.get(name) || []), callback]); },
    dispatchEvent(event) { events.push(event); (handlers.get(event.type) || []).forEach(callback => callback(event)); }
  };
  let timerId = 0;
  const context = vm.createContext({ URL, URLSearchParams, document, location: new URL(url), navigator,
    CustomEvent: class { constructor(type, options) { this.type = type; this.detail = options.detail; } },
    setTimeout(callback, delay) { timers.set(++timerId, { callback, delay }); return timerId; },
    clearTimeout(id) { timers.delete(id); },
    window: { addEventListener(name, callback) { windowHandlers.set(name, callback); } }
  });
  context.history = {
    pushState(_, __, next) { historyCalls.push(["push", next]); context.location = new URL(next); },
    replaceState(_, __, next) { historyCalls.push(["replace", next]); context.location = new URL(next); }
  };
  vm.runInContext(source, context);
  return { context, document, query, month, tag, reset, form, count, empty, more, entries, localeLink, events, timers, historyCalls,
    visible: () => entries.filter(entry => !entry.hidden),
    flush() { const pending = [...timers.values()]; timers.clear(); pending.forEach(value => value.callback()); },
    click(link, extra = {}) { const event = { button: 0, target: { closest: () => link }, preventDefault() { this.defaultPrevented = true; }, ...extra }; document.dispatchEvent({ type: "click", ...event }); return event; },
    pop(next) { context.location = new URL(next); windowHandlers.get("popstate")?.(); },
    ready() { (handlers.get("DOMContentLoaded") || []).forEach(callback => callback()); }
  };
}

test("enhancement paginates existing server HTML at 18 without fetching, then loads the next batch", () => {
  const page = fixture();
  assert.equal(page.visible().length, 18);
  assert.match(page.count.textContent, /40 results · 18 shown/);
  assert.equal(page.count.attributes["aria-live"], "polite");
  page.more.emit("click");
  assert.equal(page.visible().length, 36);
  page.more.emit("click");
  assert.equal(page.visible().length, 40);
  assert.equal(page.more.hidden, true);
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /\.focus\s*\(/);
});

test("Unicode search is debounced, respects composition, ANDs terms and uses textContent for counts", () => {
  const page = fixture({ data: [
    { search: "AI 模型 <script> text", tags: '["Ｒｅｓｅａｒｃｈ"]', month: "2026-11" },
    { search: "ai unrelated", tags: "malformed", month: "2026-11" }
  ] });
  page.query.value = "ＡＩ 模型";
  page.query.emit("compositionstart");
  page.query.emit("input", { isComposing: true });
  assert.equal(page.timers.size, 0);
  page.query.emit("compositionend");
  assert.equal([...page.timers.values()][0].delay, 150);
  page.flush();
  assert.equal(page.visible().length, 1);
  assert.equal(new URL(page.context.location).searchParams.get("q"), "AI 模型");
  assert.equal(page.query.value, "ＡＩ 模型", "typing does not reset caret or replace the active input");
  assert.equal(page.events.filter(event => event.type === "polyemergence:archive-filter").length, 1);
  const detail = page.events.find(event => event.type === "polyemergence:archive-filter").detail;
  assert.equal(detail.search_active, true);
  assert.equal(Object.hasOwn(detail, "q"), false);
});

test("URL filters combine exact tags and month; locale links preserve only the filter state", () => {
  const page = fixture({ url: "https://polyemergence.com/en/archive/fields/ai/?q=ai&tag=Research&month=2026-11&utm_source=test" });
  assert.equal(page.visible().length, 18);
  assert.match(page.count.textContent, /20 results/);
  const target = new URL(page.localeLink.href);
  assert.equal(target.pathname, "/zh/archive/fields/ai/");
  assert.equal(target.searchParams.get("q"), "ai");
  assert.equal(target.searchParams.get("tag"), "Research");
  assert.equal(target.searchParams.get("month"), "2026-11");
  page.reset.emit("click");
  assert.equal(page.query.value, "");
  assert.equal(page.tag.value, "");
  assert.equal(page.month.value, "");
  assert.equal(page.context.location.searchParams.has("q"), false);
  assert.equal(page.context.location.searchParams.get("utm_source"), "test");
  assert.equal(new URL(page.localeLink.href).search, "");
});

test("tag punctuation and Unicode forms match the Python-normalized server tag while C++ stays distinct", () => {
  const data = [
    { search: "Compound subject", tags: '["a b 中文"]', month: "2026-11" },
    { search: "Programming", tags: '["c++", "crispr cas9", "strasse", "οσ"]', month: "2026-11" },
    { search: "The letter c", tags: '["c"]', month: "2026-11" }
  ];
  const page = fixture({ data, url: "https://polyemergence.com/en/archive/fields/ai/?tag=" + encodeURIComponent("Ａ＆Ｂ / 中文") });
  assert.equal(page.visible().length, 1);
  assert.equal(page.visible()[0].dataset.search, "Compound subject");
  for (const selected of ["Ｃ＋＋", "CRISPR_Cas9", "Straße", "ΟΣ"]) {
    page.pop("https://polyemergence.com/en/archive/fields/ai/?tag=" + encodeURIComponent(selected));
    assert.equal(page.visible().length, 1, selected);
    assert.equal(page.visible()[0].dataset.search, "Programming");
  }
});

test("submit and month changes do not reload; empty results and back navigation are coherent", () => {
  const page = fixture();
  page.query.value = "No such article";
  let prevented = false;
  page.form.emit("submit", { preventDefault() { prevented = true; } });
  assert.equal(prevented, true);
  assert.equal(page.visible().length, 0);
  assert.equal(page.empty.hidden, false);
  assert.equal(page.more.hidden, true);
  page.pop("https://polyemergence.com/en/archive/fields/ai/?month=2026-10");
  assert.equal(page.query.value, "");
  assert.equal(page.month.value, "2026-10");
  assert.equal(page.visible().length, 18);
  assert.equal(page.empty.hidden, true);
  page.month.value = "2026-11";
  page.month.emit("change");
  assert.equal(page.context.location.searchParams.get("month"), "2026-11");
});

test("tag links filter only current-domain unmodified clicks; hostile params stay inert", () => {
  const page = fixture();
  const link = element({ href: "https://polyemergence.com/en/archive/fields/ai/?tag=Research", target: "" });
  page.click(link);
  assert.equal(page.tag.value, "Research");
  assert.match(page.count.textContent, /20 results/);
  const before = page.historyCalls.length;
  page.click(element({ href: "https://other.example/route?tag=Models" }));
  page.click(element({ href: "https://polyemergence.com/en/archive/fields/energy/?tag=Models" }));
  page.click(link, { ctrlKey: true });
  assert.equal(page.historyCalls.length, before);
  const hostile = fixture({ url: "https://polyemergence.com/en/archive/fields/ai/?tag=%3Cimg%20src%3Dx%3E&month=javascript%3Aalert(1)" });
  assert.equal(hostile.month.value, "");
  assert.match(hostile.count.textContent, /#<img src=x>/);
  assert.equal(Object.hasOwn(hostile.count, "innerHTML"), false);
});

test("Chinese count and no-JS markup are progressively enhanced only when controls exist", () => {
  const page = fixture({ locale: "zh", size: 2, loading: true });
  assert.equal(page.visible().length, 2, "all server records start visible");
  page.ready();
  assert.match(page.count.textContent, /共 2 条，已显示 2 条/);
});

test("startup only refreshes an existing service worker; missing or failed APIs never block the archive", async () => {
  let gets = 0, updates = 0;
  const page = fixture({ navigator: { serviceWorker: { getRegistration() { gets += 1; return Promise.resolve({ update() { updates += 1; return Promise.resolve(); } }); } } } });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(gets, 1);
  assert.equal(updates, 1);
  assert.equal(page.visible().length, 18);
  page.ready();
  assert.equal(gets, 1, "repeated initialization does not trigger duplicate update checks");
  for (const getRegistration of [() => { throw new Error("disabled"); }, () => Promise.reject(new Error("offline")), () => Promise.resolve({ update() { return Promise.reject(new Error("offline")); } }), () => Promise.resolve(undefined)]) {
    assert.equal(fixture({ navigator: { serviceWorker: { getRegistration } } }).visible().length, 18);
  }
  await new Promise(resolve => setImmediate(resolve));
  assert.doesNotMatch(source, /\.(?:register|unregister)\s*\(/);
});

test("analytics never sends raw archive query or tag in custom events or page-location/referrer overrides", () => {
  const listeners = new Map();
  const calls = [];
  const location = new URL("https://polyemergence.com/en/archive/fields/ai/?q=private-search&tag=private-tag&month=2026-11");
  const document = {
    documentElement: { dataset: { locale: "en" }, lang: "en" },
    referrer: "https://polyemergence.com/en/archive/fields/ai/?q=private-referrer",
    createElement: () => ({}), head: { appendChild() {} },
    addEventListener(name, callback) { listeners.set(name, callback); }
  };
  const window = { location, gtag: (...args) => calls.push(args), setInterval() {}, addEventListener() {} };
  vm.runInContext(analytics, vm.createContext({ document, window, URL, Date }));
  listeners.get("polyemergence:archive-filter")({ detail: { filter_type: "search", q: "private-search", tag: "private-tag", search_active: true, tag_active: true, month: "2026-11", result_count: 3 } });
  const target = { dataset: { relatedKind: "same_field", relatedId: "article-one" }, closest: () => null, matches: selector => selector === "[data-related-kind]" };
  listeners.get("click")({ target: { closest: () => target } });
  assert.doesNotMatch(JSON.stringify(calls), /private-search|private-tag|private-referrer/);
  assert.ok(calls.some(call => call[0] === "event" && call[1] === "archive_filter" && call[2].result_count === 3));
  assert.ok(calls.some(call => call[0] === "event" && call[1] === "related_article_click" && call[2].related_article_id === "article-one"));
});
