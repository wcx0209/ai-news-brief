(function () {
  "use strict";

  var measurementId = "G-ZNVK1S0DY0";
  var path = window.location.pathname;
  var locale = document.documentElement.dataset.locale || document.documentElement.lang || "unknown";
  var articleMatch = path.match(/^\/(?:en|zh)\/archive\/\d{4}\/\d{2}\/\d{2}\/([^/]+)\/?$/);
  var articleId = articleMatch ? articleMatch[1] : "";
  var pageKind = articleMatch
    ? "article"
    : /^\/(?:en|zh)\/?$/.test(path)
      ? "homepage"
      : /^\/(?:en|zh)\/topics\//.test(path)
        ? "topic"
        : /^\/(?:en|zh)\/archive\//.test(path)
          ? "archive"
          : "other";
  var meaningfulEngagementSent = false;

  window.dataLayer = window.dataLayer || [];
  window.gtag = window.gtag || function () {
    window.dataLayer.push(arguments);
  };

  window.gtag("js", new Date());
  window.gtag("config", measurementId, {
    allow_google_signals: false,
    allow_ad_personalization_signals: false
  });

  var script = document.createElement("script");
  script.async = true;
  script.src = "https://www.googletagmanager.com/gtag/js?id=" + encodeURIComponent(measurementId);
  document.head.appendChild(script);

  function eventParams(extra) {
    return Object.assign({
      page_kind: pageKind,
      page_locale: locale,
      article_id: articleId || undefined
    }, extra || {});
  }

  function track(name, extra) {
    window.gtag("event", name, eventParams(extra));
  }

  function markMeaningful(method, id) {
    if (meaningfulEngagementSent) return;
    meaningfulEngagementSent = true;
    track("meaningful_engagement", {
      engagement_method: method,
      article_id: id || articleId || undefined
    });
  }

  function articleIdFor(element) {
    var root = element && element.closest(".lead-story, .story-card, [data-interaction]");
    var interaction = root && (root.matches("[data-interaction]") ? root : root.querySelector("[data-interaction]"));
    return interaction && interaction.dataset.articleId || articleId || "";
  }

  if (articleId) track("article_view");

  var visibleSeconds = 0;
  var timeCheckpoints = { 20: false, 60: false, 180: false };
  window.setInterval(function () {
    if (document.visibilityState !== "visible" || !document.hasFocus()) return;
    visibleSeconds += 1;
    Object.keys(timeCheckpoints).forEach(function (value) {
      var seconds = Number(value);
      if (!timeCheckpoints[value] && visibleSeconds >= seconds) {
        timeCheckpoints[value] = true;
        track("read_time", { seconds: seconds });
        if (seconds === 20) markMeaningful("visible_20_seconds");
      }
    });
  }, 1000);

  var scrollCheckpoints = { 50: false, 90: false };
  var scrollFramePending = false;
  function measureScroll() {
    scrollFramePending = false;
    var root = document.documentElement;
    var available = root.scrollHeight - window.innerHeight;
    if (available < 200 || window.scrollY < 80) return;
    var percent = Math.min(100, Math.round(window.scrollY / available * 100));
    Object.keys(scrollCheckpoints).forEach(function (value) {
      var checkpoint = Number(value);
      if (!scrollCheckpoints[value] && percent >= checkpoint) {
        scrollCheckpoints[value] = true;
        track("scroll_depth", { percent_scrolled: checkpoint });
        if (checkpoint === 50) markMeaningful("scroll_50_percent");
      }
    });
  }
  window.addEventListener("scroll", function () {
    if (scrollFramePending) return;
    scrollFramePending = true;
    window.requestAnimationFrame(measureScroll);
  }, { passive: true });

  document.addEventListener("click", function (event) {
    var target = event.target.closest("a, button");
    if (!target) return;
    var id = articleIdFor(target);

    if (target.matches("[data-summary-toggle]")) {
      window.setTimeout(function () {
        if (target.getAttribute("aria-expanded") === "true") {
          track("summary_expand", { article_id: id || undefined });
          markMeaningful("summary_expand", id);
        }
      }, 0);
      return;
    }

    if (target.matches(".read-link, .archive-original")) {
      var destinationHost = "";
      try { destinationHost = new URL(target.href, window.location.href).hostname; } catch (_) {}
      track("original_click", {
        article_id: id || undefined,
        destination_host: destinationHost || undefined
      });
      markMeaningful("original_click", id);
      return;
    }

    if (target.matches("[data-like]")) {
      track("like_intent", { article_id: id || undefined });
      markMeaningful("like", id);
      return;
    }

    if (target.matches("[data-comments-toggle]")) {
      window.setTimeout(function () {
        if (target.getAttribute("aria-expanded") === "true") {
          track("comments_open", { article_id: id || undefined });
          markMeaningful("comments_open", id);
        }
      }, 0);
    }
  });

  document.addEventListener("submit", function (event) {
    if (!event.target.matches(".comment-form")) return;
    var root = event.target.closest("[data-interaction]");
    track("comment_submit", { article_id: root && root.dataset.articleId || articleId || undefined });
    markMeaningful("comment_submit", root && root.dataset.articleId);
  });
})();
