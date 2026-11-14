import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../web/public/archive-media.js", import.meta.url), "utf8");

function fixture({ width = 1200, height = 675, complete = false, loading = false, src = "", candidates = [], linked = false, hasRetry = true } = {}) {
  const handlers = new Map();
  const classes = new Set();
  const requests = [], timers = new Map();
  let timerId = 0;
  const image = {
    naturalWidth: width, naturalHeight: height, complete, hidden: false, dataset: { imageCandidates: JSON.stringify(candidates) }, _src: src,
    getAttribute: name => name === "src" ? image._src : null,
    get src() { return this._src; },
    set src(value) { this._src = value; requests.push(value); this.complete = false; this.naturalWidth = 0; this.naturalHeight = 0; },
    addEventListener(event, callback) {
      handlers.set(event, [...(handlers.get(event) || []), callback]);
    }
  };
  const caption = { hidden: false };
  const fallback = { hidden: true };
  const retryHandlers = new Map();
  let retry = hasRetry ? { hidden: true, addEventListener: (type, callback) => retryHandlers.set(type, callback) } : null;
  let createdButtons = 0;
  const figure = {
    dataset: {},
    closest: () => linked ? {} : null,
    appendChild(value) { retry = value; createdButtons += 1; },
    classList: { add: value => classes.add(value), remove: value => classes.delete(value) },
    querySelector: selector => ({ img: image, figcaption: caption, "[data-archive-media-fallback]": fallback, "[data-image-retry]": retry }[selector])
  };
  let onReady;
  const document = {
    readyState: loading ? "loading" : "complete",
    documentElement: { lang: "en" },
    createElement: () => ({ hidden: false, setAttribute() {}, addEventListener: (type, callback) => retryHandlers.set(type, callback) }),
    querySelectorAll: () => [figure],
    addEventListener(event, callback) { if (event === "DOMContentLoaded") onReady = callback; }
  };
  vm.runInContext(source, vm.createContext({ document, URL, setTimeout(callback) { timers.set(++timerId, callback); return timerId; }, clearTimeout(id) { timers.delete(id); } }));
  return { image, caption, fallback, figure, classes, handlers,
    requests, timers, get retry() { return retry; }, get createdButtons() { return createdButtons; },
    flushTimers() { const pending = [...timers.values()]; timers.clear(); pending.forEach(callback => callback()); },
    retryClick: () => retryHandlers.get("click")?.({ preventDefault() {} }),
    emit: event => (handlers.get(event) || []).forEach(callback => callback()),
    ready: () => onReady?.() };
}

test("network errors hide both the broken image and its caption, leaving only the small notice", () => {
  const page = fixture();
  page.emit("error");
  assert.equal(page.image.hidden, true);
  assert.equal(page.caption.hidden, true);
  assert.equal(page.fallback.hidden, false);
  assert.equal(page.classes.has("is-unavailable"), true);
});

test("resolution gates reject either undersized dimension but accept the exact brief threshold", () => {
  for (const [width, height] of [[479, 675], [1200, 269], [0, 0]]) {
    const page = fixture({ width, height, complete: true });
    assert.equal(page.image.hidden, true);
    assert.equal(page.caption.hidden, true);
    assert.equal(page.fallback.hidden, false);
  }
  const accepted = fixture({ width: 480, height: 270, complete: true });
  assert.equal(accepted.image.hidden, false);
  assert.equal(accepted.caption.hidden, false);
  assert.equal(accepted.fallback.hidden, true);
});

test("already completed cache hits are checked, including previously broken responses", () => {
  const good = fixture({ complete: true });
  assert.equal(good.figure.dataset.archiveMediaBound, "true");
  assert.equal(good.fallback.hidden, true);
  const broken = fixture({ complete: true, width: 0, height: 0 });
  assert.equal(broken.classes.has("is-unavailable"), true);
});

test("a later successful load restores valid media without duplicate caption or warning", () => {
  const page = fixture({ width: 0, height: 0, complete: true });
  page.image.naturalWidth = 800;
  page.image.naturalHeight = 600;
  page.emit("load");
  assert.equal(page.image.hidden, false);
  assert.equal(page.caption.hidden, false);
  assert.equal(page.fallback.hidden, true);
  assert.equal(page.classes.has("is-unavailable"), false);
});

test("early script execution waits for markup and binds each figure only once", () => {
  const page = fixture({ loading: true });
  assert.equal(page.handlers.size, 0);
  page.ready();
  page.ready();
  assert.equal(page.handlers.get("error").length, 1);
  assert.equal(page.handlers.get("load").length, 1);
});

test("a failed original tries safe distinct candidates, then retries the unchanged original once before showing the notice", () => {
  const original = "https://images.example.com/original.jpg?VersionId=signed-value";
  const page = fixture({ src: original, candidates: [original, "javascript:alert(1)", "https://u:p@example.com/private", "https://images.example.com/two.png", "https://images.example.com/three.png", "https://images.example.com/ignored.png"] });
  page.emit("error");
  assert.deepEqual(page.requests, ["https://images.example.com/two.png"]);
  assert.equal(page.image.loading, "eager");
  assert.equal(page.image.hidden, false);
  assert.equal(page.caption.hidden, true);
  assert.equal(page.fallback.hidden, true);
  page.image.naturalWidth = 1200; page.image.naturalHeight = 269;
  page.emit("load");
  assert.equal(page.requests.at(-1), "https://images.example.com/three.png");
  page.emit("error");
  page.emit("error");
  assert.equal(page.timers.size, 1);
  page.flushTimers();
  assert.equal(page.requests.at(-1), original);
  page.emit("error");
  assert.equal(page.image.hidden, true);
  assert.equal(page.fallback.hidden, false);
  assert.equal(page.retry.hidden, false);
  for (let i = 0; i < 5; i += 1) page.emit("error");
  assert.equal(page.requests.length, 3);
  assert.equal(page.timers.size, 0);
});

test("cached failures get one bounded retry and the manual button can restore truthful media and caption", () => {
  const page = fixture({ src: "https://images.example.com/one.jpg", width: 0, height: 0, complete: true });
  assert.equal(page.timers.size, 1);
  page.flushTimers();
  page.emit("error");
  assert.equal(page.retry.hidden, false);
  page.retryClick();
  assert.equal(page.requests.length, 2);
  assert.equal(page.image.hidden, false);
  assert.equal(page.image.loading, "eager");
  page.image.naturalWidth = 480; page.image.naturalHeight = 270;
  page.emit("load");
  assert.equal(page.caption.hidden, false);
  assert.equal(page.fallback.hidden, true);
  assert.equal(page.retry.hidden, true);
  assert.equal(page.classes.has("is-unavailable"), false);
});

test("pending lazy images are not rejected and recommendation links never gain nested retry buttons", () => {
  const page = fixture({ src: "https://images.example.com/one.jpg", width: 0, height: 0, complete: false, linked: true, hasRetry: false });
  assert.equal(page.requests.length, 0);
  assert.equal(page.timers.size, 0);
  assert.equal(page.image.hidden, false);
  assert.equal(page.createdButtons, 0);
  const standalone = fixture({ src: "https://images.example.com/one.jpg", hasRetry: false });
  assert.equal(standalone.createdButtons, 1);
  assert.equal(standalone.retry.textContent, "Retry image");
});
