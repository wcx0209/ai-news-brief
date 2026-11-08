(() => {
  let savedLocale = null;
  try {
    savedLocale = localStorage.getItem("polyemergence-locale");
  } catch {
    // Language detection still works when browser storage is unavailable.
  }

  const systemLocale = (navigator.languages?.[0] || navigator.language || "en").toLowerCase();
  const locale = savedLocale === "zh" || savedLocale === "en"
    ? savedLocale
    : systemLocale.startsWith("zh") ? "zh" : "en";

  location.replace(`/${locale}/${location.search}${location.hash}`);
})();
