(function () {
  "use strict";

  const PAGE_SIZE = 18;
  const normalise = value => String(value || "").normalize("NFKC").trim().toLowerCase().replace(/\s+/g, " ");
  // Keep tag matching in step with src/archive_exploration.py:normalize_tag.
  // In particular, separators are spaces but the + in C++ remains meaningful.
  const normaliseTag = value => normalise(value).replace(/ß/g, "ss").replace(/ς/g, "σ")
    .replace(/[\u2010-\u2015\u2212_.\-/]+/g, " ").replace(/[^\p{L}\p{N}+\s]/gu, " ").replace(/\s+/g, " ").trim();
  const bounded = (value, maximum) => Array.from(String(value || "").normalize("NFKC").trim()).slice(0, maximum).join("");

  function refreshExistingWorker() {
    try {
      const serviceWorker = typeof navigator !== "undefined" && navigator.serviceWorker;
      if (serviceWorker && typeof serviceWorker.getRegistration === "function") {
        Promise.resolve(serviceWorker.getRegistration()).then(registration => {
          if (registration && typeof registration.update === "function") return registration.update();
        }).catch(() => {});
      }
    } catch (_) {}
  }

  function initialise() {
    const form = document.querySelector("[data-archive-filters]");
    if (!form || form.dataset.archiveExploreBound === "true") return;
    const query = form.querySelector('[name="q"]');
    const month = form.querySelector('[name="month"]');
    const tag = form.querySelector('[name="tag"]');
    const count = document.querySelector("[data-archive-count]");
    const empty = document.querySelector("[data-archive-empty]");
    const more = document.querySelector("[data-archive-more]");
    if (!query || !month || !tag || !count || !empty || !more) return;
    form.dataset.archiveExploreBound = "true";
    refreshExistingWorker();

    const entries = Array.from(document.querySelectorAll("[data-archive-entry]")).map(node => {
      let tags = [];
      try { const value = JSON.parse(node.dataset.tags || "[]"); if (Array.isArray(value)) tags = value.filter(value => typeof value === "string").map(normaliseTag).filter(Boolean); } catch (_) {}
      return { node, search: normalise(node.dataset.search), tags, month: node.dataset.month || "" };
    });
    const months = new Set(entries.map(entry => entry.month).filter(value => /^\d{4}-(0[1-9]|1[0-2])$/.test(value)));
    const chinese = (document.documentElement.dataset.locale || document.documentElement.lang || "").startsWith("zh");
    const domain = (location.pathname.match(/\/archive\/fields\/([a-z][a-z0-9_]*)\/?$/) || [])[1] || "";
    let state = { q: "", tag: "", month: "" };
    let limit = PAGE_SIZE;
    let timer;
    let composing = false;

    function read(params) {
      const selectedMonth = params.get("month") || "";
      return { q: bounded(params.get("q"), 200), tag: bounded(params.get("tag"), 120), month: months.has(selectedMonth) ? selectedMonth : "" };
    }

    function stateUrl(value, href = location.href) {
      const url = new URL(href, location.href);
      ["q", "tag", "month"].forEach(key => { url.searchParams.delete(key); if (value[key]) url.searchParams.set(key, value[key]); });
      return url;
    }

    function updateLocaleLinks() {
      document.querySelectorAll("[data-archive-locale]").forEach(link => {
        try {
          const destination = stateUrl(state, link.href);
          if (destination.origin === location.origin && destination.protocol === location.protocol) link.href = destination.href;
        } catch (_) {}
      });
    }

    function render() {
      const terms = normalise(state.q).split(" ").filter(Boolean);
      const selectedTag = normaliseTag(state.tag);
      const matches = entries.filter(entry => (!state.month || entry.month === state.month)
        && (!selectedTag || entry.tags.includes(selectedTag)) && terms.every(term => entry.search.includes(term)));
      const visible = new Set(matches.slice(0, limit));
      entries.forEach(entry => { entry.node.hidden = !visible.has(entry); });
      const shown = Math.min(limit, matches.length);
      count.textContent = chinese ? `共 ${matches.length} 条，已显示 ${shown} 条` : `${matches.length} ${matches.length === 1 ? "result" : "results"} · ${shown} shown`;
      if (state.tag) count.textContent += ` · #${state.tag}`;
      count.setAttribute("aria-live", "polite");
      empty.hidden = matches.length !== 0;
      more.hidden = shown >= matches.length;
      updateLocaleLinks();
      return matches.length;
    }

    function apply(next, { historyMode = "replace", reason = "", syncControls = true } = {}) {
      const changed = ["q", "tag", "month"].some(key => state[key] !== next[key]);
      state = next;
      limit = PAGE_SIZE;
      if (syncControls) { query.value = state.q; month.value = state.month; tag.value = state.tag; }
      if (historyMode) {
        const url = stateUrl(state);
        if (url.href !== location.href) history[historyMode === "push" ? "pushState" : "replaceState"](null, "", url.href);
      }
      const results = render();
      if (changed && reason) document.dispatchEvent(new CustomEvent("polyemergence:archive-filter", { detail: {
        filter_type: reason, search_active: Boolean(state.q), tag_active: Boolean(state.tag),
        month: state.month, result_count: results, archive_domain: domain,
      } }));
    }

    function controls() {
      return read(new URLSearchParams({ q: query.value, month: month.value, tag: tag.value }));
    }

    function scheduleSearch() {
      clearTimeout(timer);
      timer = setTimeout(() => { apply(controls(), { reason: "search", syncControls: false }); }, 150);
    }

    query.addEventListener("input", event => { if (!composing && !event.isComposing) scheduleSearch(); });
    query.addEventListener("compositionstart", () => { composing = true; clearTimeout(timer); });
    query.addEventListener("compositionend", () => { composing = false; scheduleSearch(); });
    month.addEventListener("change", () => { clearTimeout(timer); apply(controls(), { historyMode: "push", reason: "month" }); });
    form.addEventListener("submit", event => { event.preventDefault(); clearTimeout(timer); apply(controls(), { historyMode: "push", reason: "submit" }); });
    form.querySelector("[data-archive-reset]")?.addEventListener("click", event => { event.preventDefault(); clearTimeout(timer); apply({ q: "", tag: "", month: "" }, { historyMode: "push", reason: "reset" }); });
    more.addEventListener("click", event => { event.preventDefault(); limit += PAGE_SIZE; render(); });

    document.addEventListener("click", event => {
      if (event.defaultPrevented || event.button > 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const link = event.target.closest?.("[data-archive-tag]");
      if (!link || link.target === "_blank" || link.hasAttribute("download")) return;
      try {
        const destination = new URL(link.href, location.href);
        if (destination.origin !== location.origin || destination.pathname !== location.pathname) return;
        const selectedTag = bounded(destination.searchParams.get("tag"), 120);
        event.preventDefault();
        clearTimeout(timer);
        apply({ ...controls(), tag: selectedTag }, { historyMode: "push", reason: "tag" });
      } catch (_) {}
    });
    window.addEventListener("popstate", () => { clearTimeout(timer); apply(read(new URL(location.href).searchParams), { historyMode: null }); });
    apply(read(new URL(location.href).searchParams));
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", initialise, { once: true });
  else initialise();
}());
