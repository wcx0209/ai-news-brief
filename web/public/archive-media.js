(function () {
  "use strict";

  function safeImageUrl(value) {
    if (typeof value !== "string" || /[\x00-\x20\\]/.test(value)) return "";
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : "";
    } catch (_) { return ""; }
  }

  function bindMedia(figure) {
    if (figure.dataset.archiveMediaBound === "true") return;
    const image = figure.querySelector("img[data-source-image]") || figure.querySelector("img:not([data-editorial-image])");
    const caption = figure.querySelector("[data-source-caption]") || figure.querySelector("figcaption:not([data-editorial-caption])");
    const fallback = figure.querySelector("[data-archive-media-fallback]");
    const editorial = figure.querySelector("[data-editorial-artwork]");
    const editorialCaption = figure.querySelector("[data-editorial-caption]");
    if (!image || (!fallback && !editorial)) return;
    figure.dataset.archiveMediaBound = "true";
    const original = safeImageUrl(image.getAttribute?.("src") || image.src || image.currentSrc);
    let provided = [];
    try { const parsed = JSON.parse(image.dataset?.imageCandidates || "[]"); if (Array.isArray(parsed)) provided = parsed; } catch (_) {}
    const candidates = [...new Set([original, ...provided].map(safeImageUrl).filter(Boolean))].slice(0, 3);
    let index = 0, originalRetried = false, exhausted = false, awaiting = false, timer = null, watchdog = null;
    let retry = figure.querySelector("[data-image-retry]");
    // Recommendation thumbnails can be inside an article link: never put an
    // interactive button inside that link, even when enhancing older markup.
    if (!retry && !figure.closest?.("a") && document.createElement && figure.appendChild) {
      retry = document.createElement("button");
      retry.type = "button";
      retry.setAttribute("data-image-retry", "");
      retry.textContent = (document.documentElement?.lang || "").startsWith("zh") ? "重试原图" : "Retry source image";
      retry.hidden = true;
      figure.appendChild(retry);
    }

    function clearWatchdog() {
      if (watchdog !== null) clearTimeout(watchdog);
      watchdog = null;
    }

    function armWatchdog() {
      clearWatchdog();
      if (!editorial || !candidates.length || exhausted) return;
      watchdog = setTimeout(() => {
        watchdog = null;
        if (exhausted || (image.complete && !awaiting)) return;
        // Do not hide the lazy source or change loading/src: keep its geometry
        // and let it finish normally under the local editorial cover.
        editorial.hidden = false;
        if (editorialCaption) editorialCaption.hidden = false;
        if (caption) caption.hidden = true;
        if (fallback) fallback.hidden = true;
        figure.classList.add("is-editorial-visual");
      }, 3000);
    }

    function showUnavailable() {
      clearWatchdog();
      image.hidden = true;
      if (caption) caption.hidden = true;
      if (fallback) fallback.hidden = Boolean(editorial);
      if (editorial) {
        editorial.hidden = false;
        if (editorialCaption) editorialCaption.hidden = false;
        figure.classList.add("is-editorial-visual");
        figure.classList.remove("is-unavailable");
      } else figure.classList.add("is-unavailable");
      exhausted = true;
      awaiting = false;
      if (retry) retry.hidden = false;
    }

    function requestImage(url) {
      awaiting = true;
      image.loading = "eager";
      const artworkVisible = editorial && !editorial.hidden;
      image.hidden = Boolean(artworkVisible);
      if (caption) caption.hidden = true;
      if (fallback) fallback.hidden = true;
      if (retry) retry.hidden = true;
      figure.classList.remove("is-unavailable");
      image.src = url; // No cache-busting, signed-query edits or image cropping.
      armWatchdog();
    }

    function tryNext() {
      if (timer !== null || exhausted) return;
      clearWatchdog();
      awaiting = false;
      if (index + 1 < candidates.length) requestImage(candidates[++index]);
      else if (!originalRetried && candidates.length) {
        originalRetried = true;
        image.hidden = true;
        if (caption) caption.hidden = true;
        if (fallback) fallback.hidden = true;
        timer = setTimeout(() => { timer = null; requestImage(candidates[0]); }, 150);
      } else showUnavailable();
    }

    function checkImage() {
      clearWatchdog();
      // Match the brief's resolution-only threshold. Do not reject colors,
      // composition or aspect ratio, and never crop an accepted source image.
      if (image.naturalWidth < 480 || image.naturalHeight < 270) {
        tryNext();
        return;
      }
      if (timer !== null) clearTimeout(timer);
      timer = null;
      awaiting = false;
      exhausted = false;
      image.hidden = false;
      if (caption) caption.hidden = false;
      if (fallback) fallback.hidden = true;
      if (editorial) editorial.hidden = true;
      if (editorialCaption) editorialCaption.hidden = true;
      figure.classList.remove("is-unavailable");
      figure.classList.remove("is-editorial-visual");
      if (retry) retry.hidden = true;
    }

    image.addEventListener("error", tryNext);
    image.addEventListener("load", checkImage);
    retry?.addEventListener("click", event => {
      if (!exhausted || !candidates.length) return;
      event.preventDefault();
      index = 0;
      originalRetried = false;
      exhausted = false;
      requestImage(candidates[0]);
    });
    // A cache hit or an error may have completed before this deferred script.
    if (image.complete && !awaiting) checkImage();
    else if (!image.complete) armWatchdog();
  }

  function initialise() {
    document.querySelectorAll("[data-archive-media]").forEach(bindMedia);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialise, { once: true });
  } else {
    initialise();
  }
}());
