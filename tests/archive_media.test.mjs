import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../web/public/archive-media.js", import.meta.url), "utf8");

function fixture({ width = 1200, height = 675, complete = false, loading = false } = {}) {
  const handlers = new Map();
  const classes = new Set();
  const image = {
    naturalWidth: width, naturalHeight: height, complete, hidden: false,
    addEventListener(event, callback) {
      handlers.set(event, [...(handlers.get(event) || []), callback]);
    }
  };
  const caption = { hidden: false };
  const fallback = { hidden: true };
  const figure = {
    dataset: {},
    classList: { add: value => classes.add(value), remove: value => classes.delete(value) },
    querySelector: selector => ({ img: image, figcaption: caption, "[data-archive-media-fallback]": fallback }[selector])
  };
  let onReady;
  const document = {
    readyState: loading ? "loading" : "complete",
    querySelectorAll: () => [figure],
    addEventListener(event, callback) { if (event === "DOMContentLoaded") onReady = callback; }
  };
  vm.runInContext(source, vm.createContext({ document }));
  return { image, caption, fallback, figure, classes, handlers,
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
