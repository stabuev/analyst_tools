(function () {
  "use strict";

  var STATUS_LABELS = {
    complete: "Готов",
    "in-progress": "В работе",
    designed: "Спроектирован",
    draft: "Черновик",
    planned: "Запланирован",
  };

  function escapeHtml(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || status;
  }

  function phaseNumber(number) {
    return String(number).padStart(2, "0");
  }

  function initTheme() {
    var root = document.documentElement;
    var stored = null;
    try {
      stored = localStorage.getItem("analyst-tools-theme");
    } catch (_) {}
    var preferred = window.matchMedia &&
      window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
    root.setAttribute("data-theme", stored || preferred);

    var button = document.getElementById("themeToggle");
    if (!button) return;

    function paint() {
      var dark = root.getAttribute("data-theme") === "dark";
      button.textContent = dark ? "Свет" : "Тьма";
      button.setAttribute("aria-pressed", String(dark));
    }

    button.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try {
        localStorage.setItem("analyst-tools-theme", next);
      } catch (_) {}
      paint();
    });
    paint();
  }

  function initMenu() {
    var button = document.getElementById("menuToggle");
    var nav = document.getElementById("siteNav");
    if (!button || !nav) return;
    button.addEventListener("click", function () {
      var open = nav.classList.toggle("is-open");
      button.setAttribute("aria-expanded", String(open));
    });
  }

  function currentPage() {
    var page = location.pathname.split("/").pop() || "index.html";
    document.querySelectorAll("[data-nav]").forEach(function (link) {
      if (link.getAttribute("href") === page) {
        link.setAttribute("aria-current", "page");
      }
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initTheme();
    initMenu();
    currentPage();
  });

  window.AnalystToolsSite = {
    escapeHtml: escapeHtml,
    phaseNumber: phaseNumber,
    statusLabel: statusLabel,
  };
})();
