const COPY = {
  en: {
    brand: "POLYEMERGENCE", navNews: "Brief", navSignals: "Signals", navInsight: "Method",
    edition: "GLOBAL EDITION", latest: "LATEST INTELLIGENCE",
    seoTitle: "AI News & Industry Intelligence | Polyemergence",
    seoDescription: "Daily AI news and analysis covering models, companies, startups, research, open source, policy, business, and society.",
    eyebrow: "DAILY AI NEWS · INDUSTRY SIGNALS · ANALYSIS", tagline: "What’s next,<br>made visible.",
    promise: "Daily AI intelligence across models, companies, startups, research, open source, policy, business, and society.",
    loading: "Loading today’s brief…", updated: "Updated", stories: "stories", dailyBrief: "Daily Brief",
    filters: { all: "All", models: "Models", company: "Company", startups: "Startups", research: "Research", open_source: "Open Source", policy: "Policy", business: "Business", society: "Society" }, importance: "Importance",
    read: "Read original", noStories: "No stories in this section yet.", error: "The live feed is unavailable. Showing the last bundled briefing.",
    demo: "Demo feed — run the scheduled collector to publish the live briefing.",
    methodTitle: "From signal to consequence.", methodSignal: "Signal", methodSignalText: "What changed?",
    methodStructure: "Structure", methodStructureText: "What larger system is taking shape?",
    methodConsequence: "Consequence", methodConsequenceText: "Who is affected, and what comes next?",
    footer: "Independent AI intelligence for a changing world."
  },
  zh: {
    brand: "多重涌现", navNews: "简报", navSignals: "信号", navInsight: "方法",
    edition: "全球版", latest: "最新情报",
    seoTitle: "AI 新闻与人工智能行业情报 | 多重涌现",
    seoDescription: "每日聚合 AI 模型、公司、创业、研究、开源、政策、商业与社会领域的重要新闻。",
    eyebrow: "AI 新闻 · 人工智能行业动态 · 趋势洞察", tagline: "看见<br>下一步。",
    promise: "每日追踪模型、公司、创业、研究、开源、政策、商业与社会领域的重要 AI 新闻。",
    loading: "正在载入今日简报…", updated: "更新于", stories: "条内容", dailyBrief: "每日简报",
    filters: { all: "全部", models: "模型", company: "公司", startups: "创业", research: "研究", open_source: "开源", policy: "政策", business: "商业", society: "社会" }, importance: "重要性",
    read: "阅读原文", noStories: "这个栏目暂时没有内容。", error: "实时数据暂时不可用，正在显示最近一次简报。",
    demo: "当前为演示数据——运行定时采集任务后将自动发布实时内容。",
    methodTitle: "从信号到影响。", methodSignal: "信号", methodSignalText: "发生了什么变化？",
    methodStructure: "结构", methodStructureText: "什么更大的系统正在形成？",
    methodConsequence: "影响", methodConsequenceText: "谁会受到影响，下一步是什么？",
    footer: "面向变化世界的独立 AI 情报媒体。"
  }
};

const routeLocale = location.pathname.split("/").filter(Boolean)[0];
const state = { locale: routeLocale === "zh" ? "zh" : routeLocale === "en" ? "en" : (navigator.language.startsWith("zh") ? "zh" : "en"), category: "all", feed: null };
const categories = ["all", "models", "company", "startups", "research", "open_source", "policy", "business", "society"];
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value = "") {
  return String(value).replace(/[&<>'"]/g, char => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" }[char]));
}

function plainText(value = "") {
  return String(value)
    .replace(/\*\*([^*]+)\*\*/g, "$1")
    .replace(/__([^_]+)__/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\*+/g, "")
    .replace(/_{2,}/g, "");
}

function inlineMarkup(value = "") {
  return escapeHtml(value)
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*+/g, "")
    .replace(/_{2,}/g, "");
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
  return { title: plainText(localized.title || "Untitled"), summary: localized.summary || localized.long_summary || "" };
}

function categoryFor(item) {
  const category = String(item.category || "").toLowerCase().replace(/[ -]/g, "_");
  if (categories.includes(category)) return category;
  if (category === "opensource") return "open_source";
  const text = `${textFor(item).title} ${item.source || ""} ${(item.tags || []).join(" ")}`.toLowerCase();
  if (/policy|regulat|law|government|election|治理|监管|政策|法规/.test(text)) return "policy";
  if (/research|paper|study|benchmark|simulation|论文|研究|评测|基准/.test(text)) return "research";
  if (/open.source|github|开源|开放权重/.test(text)) return "open_source";
  if (/startup|venture|seed round|series [a-f]|初创|创业|融资轮/.test(text)) return "startups";
  if (/model|llm|gpt|claude|gemini|qwen|deepseek|sagemaker|模型|推理/.test(text)) return "models";
  if (/funding|revenue|earnings|acqui|data center|chip|enterprise|融资|营收|收购|数据中心|芯片|企业/.test(text)) return "business";
  if (/jobs|labor|education|culture|public|environment|社会|就业|教育|文化|环境|公众/.test(text)) return "society";
  return "company";
}

function imageFit(item) {
  if (["cover", "contain"].includes(item.image_fit)) return item.image_fit;
  const source = String(item.source || "");
  const image = String(item.image_url || "");
  const editorialPhoto = /techcrunch|reuters|ap news|associated press|the verge|wired|bloomberg|venturebeat|cnbc|bbc|fortune|forbes/i;
  const photoUrl = /gettyimages|unsplash|techcrunch\.com\/wp-content/i;
  return editorialPhoto.test(source) || photoUrl.test(image) ? "cover" : "contain";
}

function imageMarkup(item, priority = false) {
  const image = safeUrl(item.image_url);
  const alt = textFor(item).title;
  const loading = priority ? 'fetchpriority="high"' : 'loading="lazy"';
  return image !== "#" ? `<img class="media-${imageFit(item)}" src="${escapeHtml(image)}" alt="${escapeHtml(alt)}" ${loading} referrerpolicy="no-referrer">` : "";
}

function renderHero(items) {
  const lead = items[0];
  if (lead && safeUrl(lead.image_url) !== "#") $("#hero-photo").src = safeUrl(lead.image_url);
  $("#hero-ticker").innerHTML = items.slice(0, 3).map((item, index) => {
    const text = textFor(item);
    return `<a href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer"><span>${String(index + 1).padStart(2, "0")}</span><strong>${escapeHtml(text.title)}</strong><small>${escapeHtml(formatDate(item.published_at))}</small></a>`;
  }).join("");
}

function renderLead(item) {
  if (!item) { $("#lead-story").innerHTML = ""; return; }
  const text = textFor(item);
  const importance = Number(item.importance || 0);
  $("#lead-story").innerHTML = `
    <div class="lead-copy">
      <div class="story-kicker"><span>${escapeHtml(item.source)} · ${COPY[state.locale].filters[categoryFor(item)]} · ${escapeHtml(formatDate(item.published_at))}</span><span class="score" title="${COPY[state.locale].importance} ${importance}"><small>${COPY[state.locale].importance}</small>${importance}</span></div>
      <div><h3>${escapeHtml(text.title)}</h3><p>${inlineMarkup(text.summary)}</p><a class="read-link" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${COPY[state.locale].read} ↗</a></div>
    </div>
    <div class="story-visual">${imageMarkup(item, true)}</div>`;
}

function renderCard(item) {
  const text = textFor(item);
  const tags = (item.tags || []).slice(0, 4).map(tag => `<span class="tag">${escapeHtml(tag)}</span>`).join("");
  const importance = Number(item.importance || 0);
  return `<article class="story-card">
    <div class="card-visual">${imageMarkup(item)}<span class="card-plane" aria-hidden="true"></span></div>
    <div class="card-copy">
    <div class="story-kicker"><span>${escapeHtml(item.source)} · ${COPY[state.locale].filters[categoryFor(item)]}</span><span>${COPY[state.locale].importance} ${importance}</span></div>
    <h3>${escapeHtml(text.title)}</h3><p>${inlineMarkup(text.summary)}</p>
    <a class="read-link" href="${escapeHtml(safeUrl(item.url))}" target="_blank" rel="noopener noreferrer">${COPY[state.locale].read} ↗</a>
    <div class="tags">${tags}</div>
    </div>
  </article>`;
}

function renderFeed() {
  if (!state.feed) return;
  const items = state.feed.items || [];
  renderHero(items);
  const filtered = state.category === "all" ? items : items.filter(item => categoryFor(item) === state.category);
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
  const items = state.feed?.items || [];
  const available = categories.filter(category => category === "all" || items.some(item => categoryFor(item) === category));
  if (!available.includes(state.category)) state.category = "all";
  $("#filters").innerHTML = available.map(category => {
    const count = category === "all" ? items.length : items.filter(item => categoryFor(item) === category).length;
    return `<button type="button" data-category="${category}" aria-pressed="${category === state.category}">${COPY[state.locale].filters[category]} <span>${count}</span></button>`;
  }).join("");
  $$('[data-category]').forEach(button => button.addEventListener("click", () => { state.category = button.dataset.category; renderFilters(); renderFeed(); }));
}

function setLocale(locale) {
  state.locale = locale === "zh" ? "zh" : "en";
  localStorage.setItem("polyemergence-locale", state.locale);
  document.documentElement.lang = state.locale === "zh" ? "zh-Hans" : "en";
  document.documentElement.dataset.locale = state.locale;
  document.title = COPY[state.locale].seoTitle;
  const description = document.querySelector('meta[name="description"]');
  if (description) description.content = COPY[state.locale].seoDescription;
  const logoName = state.locale === "zh" ? "logo-zh-reverse.svg" : "logo-en-reverse.svg";
  $("#brand-logo").src = `/assets/${logoName}`;
  $("#brand-logo").alt = COPY[state.locale].brand;
  $("#footer-logo").src = `/assets/${logoName}`;
  $("#footer-logo").alt = COPY[state.locale].brand;
  $$('[data-locale-button]').forEach(link => {
    if (link.dataset.localeButton === state.locale) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  $$('[data-copy]').forEach(node => node.innerHTML = COPY[state.locale][node.dataset.copy]);
  renderFilters(); renderFeed();
}

$$('[data-filter-link]').forEach(link => link.addEventListener("click", () => { state.category = link.dataset.filterLink; renderFilters(); renderFeed(); }));

async function loadFeed() {
  try {
    const response = await fetch("/data/latest.json", { cache: "no-store" });
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
