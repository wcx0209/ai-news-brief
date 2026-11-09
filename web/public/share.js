(function () {
  "use strict";

  var toastTimer;

  function isMobileShareDevice() {
    return window.matchMedia("(pointer: coarse)").matches || navigator.maxTouchPoints > 0;
  }

  function shareText(button) {
    var brand = button.dataset.shareLocale === "zh" ? "多重涌现 · AI 情报" : "Polyemergence · AI Intelligence";
    return [button.dataset.shareTitle, button.dataset.shareSummary, brand].filter(Boolean).join("\n\n");
  }

  function showToast(locale) {
    var toast = document.getElementById("share-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "share-toast";
      toast.className = "share-toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      document.body.appendChild(toast);
    }
    toast.textContent = locale === "zh" ? "分享文案和链接已复制" : "Share text and link copied";
    toast.classList.add("is-visible");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toast.classList.remove("is-visible"); }, 2600);
  }

  async function copyText(value) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(value);
      return;
    }
    var field = document.createElement("textarea");
    field.value = value;
    field.setAttribute("readonly", "");
    field.style.position = "fixed";
    field.style.opacity = "0";
    document.body.appendChild(field);
    field.select();
    document.execCommand("copy");
    field.remove();
  }

  function trackShare(button, method) {
    window.dataLayer = window.dataLayer || [];
    window.gtag = window.gtag || function () { window.dataLayer.push(arguments); };
    window.gtag("event", "share", {
      method: method,
      content_type: "article",
      item_id: button.dataset.shareId || "",
      language: button.dataset.shareLocale || "",
      link_url: button.dataset.shareUrl || ""
    });
  }

  document.addEventListener("click", async function (event) {
    var button = event.target.closest && event.target.closest("[data-share-button]");
    if (!button) return;
    var text = shareText(button);
    var url = button.dataset.shareUrl;

    if (navigator.share && isMobileShareDevice()) {
      try {
        await navigator.share({ title: button.dataset.shareTitle, text: text, url: url });
        trackShare(button, "native");
        return;
      } catch (error) {
        if (error && error.name === "AbortError") return;
      }
    }

    try {
      await copyText(text + "\n\n" + url);
      trackShare(button, "copy");
      showToast(button.dataset.shareLocale);
    } catch (_) {
      window.prompt(button.dataset.shareLocale === "zh" ? "复制以下内容" : "Copy this", text + "\n\n" + url);
    }
  });
})();
