import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

test("offline data caches cannot substitute taxonomy or observations for news", async () => {
  const entries = new Map();
  const listeners = {};
  let online = true;
  const context = vm.createContext({
    Request, Response, URL,
    self: { location: { origin: "https://polyemergence.com" }, addEventListener: (name, fn) => { listeners[name] = fn; } },
    caches: { open: async () => ({ put: async (key, value) => entries.set(key, value), match: async key => entries.get(key)?.clone() }) },
    fetch: async request => {
      if (!online) throw new Error("offline");
      return new Response(new URL(request.url).pathname);
    },
  });
  vm.runInContext(await readFile(new URL("../web/public/sw.js", import.meta.url), "utf8"), context);
  async function fetchData(path) {
    let pending;
    listeners.fetch({ request: new Request("https://polyemergence.com" + path), respondWith: response => { pending = response; } });
    return (await pending).text();
  }
  for (const path of ["/data/latest.json", "/data/editorial-domains.json", "/data/observations.json"]) assert.equal(await fetchData(path), path);
  online = false;
  assert.equal(await fetchData("/data/latest.json?refresh=123"), "/data/latest.json");
  assert.equal(await fetchData("/data/editorial-domains.json"), "/data/editorial-domains.json");
  assert.equal(await fetchData("/data/observations.json"), "/data/observations.json");
});
