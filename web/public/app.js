const COPY = {
  en: {
    brand: "POLYEMERGENCE", navNews: "News", navSignals: "Signals", navInsight: "Insight",
    eyebrow: "AI NEWS · SIGNALS · INSIGHT", tagline: "What’s next,<br>made visible.",
    promise: "Important AI changes, connected across technology, business, policy, and society.",
    loading: "Loading today’s brief…", updated: "Updated", stories: "stories", dailyBrief: "Daily Brief",
    filters: { all: "All", news: "News", discussion: "Discussion", video: "Video", opensource: "Open source" },
    read: "Read original", noStories: "No stories in this section yet.", error: "The live feed is unavailable. Showing the last bundled briefing.",
    demo: "Demo feed — connect Supabase and run the collector to publish live reporting.",
    methodTitle: "From signal to consequence.", methodSignal: "Signal", methodSignalText: "What changed?",
    methodStructure: "Structure", methodStructureText: "What larger system is taking shape?",
    methodConsequence: "Consequence", methodConsequenceText: "Who is affected, and what comes next?",
    footer: "Independent AI intelligence for a changing world."
  },
  zh: {
    brand: "多重涌现", navNews: "新闻", navSignals: "信号", navInsight: "洞察",
    eyebrow: "AI 新闻 · 信号 · 洞察", tagline: "看见<br>下一步。",
    promise: "连接技术、商业、政策与社会，理解真正重要的 AI 变化。",
    loading: "正在载入今日简报…", updated: "更新于", stories: "条内容", dailyBrief: "每日简报",
    filters: { all: "全部", news: "新闻", discussion: "讨论", video: "视频", opensource: "开源" },
    read: "阅读原文", noStories: "这个栏目暂时没有内容。", error: "实时数据暂时不可用，正在显示最近一次简报。",
    demo: "当前为演示数据——连接 Supabase 并运行采集任务后将自动发布实时内容。",
    methodTitle: "从信号到影响。", methodSignal: "信号", methodSignalText: "发生了什么变化？",
    methodStructure: "结构", methodStructureText: "什么更大的系统正在形成？",
    methodConsequence: "影响", methodConsequenceText: "谁会受到影响，下一步是什么？",
    footer: "面向变化世界的独立 AI 情报媒体。"
  }
};

const state = { locale: localStorage.getItem("polyemergence-locale") || (navigator.language.startsWith("zh") ? "zh" : "en"), category: "all", feed: null };
const categories = ["all", "news", "discussion", "video", "opensource"];
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function safeUrl(value) {
  try { const url = new URL(value); return ["http:", "https:"].includes(url.protocol) ? url.href : "#"; }
  catch { return "#"; }
}

function formatDate(value) {
  if (!value) return "";
  const locale = state.locale === "zh" ? "zh-CN" : "en-SG";
  return new Intl.DateTimeFormat(locale, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function textFor(item) {
  const localized = item[state.locale] || item.en || item.zh || {};
  return { title: localized.title || "Untitled", summary: localized.summary || localized.long_summary || "" };
}

function imageMarkup(item) {
  const image = safeUrl(item.image_url);
  return image !== "#" ? `<img src="${escapeHtml(image)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : "";
}

function renderLead(item) {
  if (!item) { $("#lead-story").innerHTML = ""; return; }
  const text = textFor(item);
  $("#lead-story").innerHTML = `
    <div class="lead-copy">
      <div class="story-kicker"><span>${escapeHtml(item.source)} · ${escapeHtml(formatDate(item.published_at))}</span><span class="score">${Number(item.importance || 0)}</span></div>
      <div><h3>${escapeHtml(text.title)}</h3><p>${escapeHtml(text.summary)}</p><a class="read-link" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${COPY[state.locale].read} ↗</a></div>
    </div>
    <div class="story-visual">${imageMarkup(item)}</div>`;
}

function renderCard(item) {
  const text = textFor(item);
  const tags = (item.tags || []).slice(0, 4).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  return `<article class="story-card">
    <div class="story-kicker"><span>${escapeHtml(item.source)}</span><span>${Number(item.importance || 0)}</span></div>
    <h3>${escapeHtml(text.title)}</h3><p>${escapeHtml(text.summary)}</p>
    <a class="read-link" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${COPY[state.locale].read} ↗</a>
    <div class="tags">${tags}</div>
  </article>`;
}

function renderFeed() {
  if (!state.feed) return;
  const items = state.feed.items || [];
  const filtered = state.category === "all" ? items : items.filter(item => item.category === state.category);
  renderLead(filtered[0]);
  $("#story-grid").innerHTML = filtered.slice(1).map(renderCard).join("");
  $("#story-grid").hidden = filtered.length < 2;
  $("#empty-state").hidden = filtered.length > 0;
  $("#empty-state").textContent = COPY[state.locale].noStories;
  $("#demo-notice").hidden = !state.feed.demo;
  $("#demo-notice").textContent = COPY[state.locale].demo;
  const updated = formatDate(state.feed.generated_at);
  $("#update-status").textContent = `${COPY[state.locale].updated} ${updated} · ${items.length} ${COPY[state.locale].stories}`;
}

function renderFilters() {
  $("#filters").innerHTML = categories.map(category => `<button type="button" data-category="${category}" aria-pressed="${category === state.category}">${COPY[state.locale].filters[category]}</button>`).join("");
  $$('[data-category]').forEach(button => button.addEventListener("click", () => { state.category = button.dataset.category; renderFilters(); renderFeed(); }));
}

function setLocale(locale) {
  state.locale = locale === "zh" ? "zh" : "en";
  localStorage.setItem("polyemergence-locale", state.locale);
  document.documentElement.lang = state.locale === "zh" ? "zh-Hans" : "en";
  document.documentElement.dataset.locale = state.locale;
  document.title = state.locale === "zh" ? "多重涌现 — AI 新闻、信号与洞察" : "Polyemergence — AI News, Signals, Insight";
  $$('[data-locale-button]').forEach(button => button.setAttribute("aria-pressed", String(button.dataset.localeButton === state.locale)));
  $$('[data-copy]').forEach(node => node.innerHTML = COPY[state.locale][node.dataset.copy]);
  renderFilters(); renderFeed();
}

$$('[data-locale-button]').forEach(button => button.addEventListener("click", () => setLocale(button.dataset.localeButton)));
$$('[data-filter-link]').forEach(link => link.addEventListener("click", () => { state.category = link.dataset.filterLink; renderFilters(); renderFeed(); }));

async function loadFeed() {
  try {
    const response = await fetch("./data/latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.feed = await response.json();
  } catch (error) {
    $("#update-status").textContent = COPY[state.locale].error;
    state.feed = { generated_at: new Date().toISOString(), items: [], demo: true };
  }
  setLocale(state.locale);
}

setLocale(state.locale);
loadFeed();
