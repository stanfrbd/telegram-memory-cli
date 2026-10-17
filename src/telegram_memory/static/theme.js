"use strict";

// Apply before the stylesheet loads to avoid a flash of the wrong theme.
(() => {
  const storageKey = "tgmem-theme";
  const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
  let preference = null;
  try {
    const saved = localStorage.getItem(storageKey);
    if (saved === "dark" || saved === "light") preference = saved;
  } catch {
    // Theme switching also works when browser storage is unavailable.
  }

  function applyTheme() {
    const theme = preference || (systemTheme.matches ? "dark" : "light");
    document.documentElement.dataset.theme = theme;
    const button = document.getElementById("theme-toggle");
    if (button) {
      const label =
        theme === "dark" ? "Switch to light mode" : "Switch to dark mode";
      button.textContent = theme === "dark" ? "☀ Light" : "☾ Dark";
      button.setAttribute("aria-label", label);
      button.setAttribute("title", label);
      button.setAttribute("aria-pressed", String(theme === "dark"));
    }
  }

  applyTheme();
  systemTheme.addEventListener("change", applyTheme);
  document.addEventListener("DOMContentLoaded", () => {
    applyTheme();
    document.getElementById("theme-toggle").addEventListener("click", () => {
      preference =
        document.documentElement.dataset.theme === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(storageKey, preference);
      } catch {
        // Keep the choice for this page even if it cannot be persisted.
      }
      applyTheme();
    });
  });
})();
