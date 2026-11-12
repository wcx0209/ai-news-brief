(function () {
  "use strict";

  function bindMedia(figure) {
    if (figure.dataset.archiveMediaBound === "true") return;
    const image = figure.querySelector("img");
    const caption = figure.querySelector("figcaption");
    const fallback = figure.querySelector("[data-archive-media-fallback]");
    if (!image || !fallback) return;
    figure.dataset.archiveMediaBound = "true";

    function showUnavailable() {
      image.hidden = true;
      if (caption) caption.hidden = true;
      fallback.hidden = false;
      figure.classList.add("is-unavailable");
    }

    function checkImage() {
      // Match the brief's resolution-only threshold. Do not reject colors,
      // composition or aspect ratio, and never crop an accepted source image.
      if (image.naturalWidth < 480 || image.naturalHeight < 270) {
        showUnavailable();
        return;
      }
      image.hidden = false;
      if (caption) caption.hidden = false;
      fallback.hidden = true;
      figure.classList.remove("is-unavailable");
    }

    image.addEventListener("error", showUnavailable);
    image.addEventListener("load", checkImage);
    // A cache hit or an error may have completed before this deferred script.
    if (image.complete) checkImage();
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
