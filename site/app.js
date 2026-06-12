(function () {
  "use strict";

  var data = window.COURSE_DATA;
  var ui = window.AnalystToolsSite;
  var progress = window.AnalystToolsProgress;

  function renderStats() {
    var stats = data.stats;
    var values = {
      phases: stats.phases,
      lessons: stats.lessons,
      ready: stats.complete_lessons,
      hours: stats.hours.min + "–" + stats.hours.max,
    };
    Object.keys(values).forEach(function (key) {
      var element = document.querySelector('[data-stat="' + key + '"]');
      if (element) element.textContent = values[key];
    });
  }

  function routeCard(route) {
    var phaseTokens = route.phases.map(function (phase) {
      return '<span class="phase-token status-' + phase.status + '" title="' +
        ui.escapeHtml(phase.title) + '">' + ui.phaseNumber(phase.number) + "</span>";
    }).join("");
    return (
      '<article class="route-card">' +
        '<p class="eyebrow">Маршрут</p>' +
        "<h3>" + ui.escapeHtml(route.name) + "</h3>" +
        '<p class="route-path">' + ui.escapeHtml(route.path) + "</p>" +
        '<p class="route-hours">' + route.hours.min + "–" + route.hours.max + " часов</p>" +
        '<div class="phase-token-list">' + phaseTokens + "</div>" +
      "</article>"
    );
  }

  function renderRoutes() {
    var container = document.getElementById("routeGrid");
    if (!container) return;
    container.innerHTML = data.routes.map(routeCard).join("");
  }

  function lessonRow(lesson) {
    var title = ui.escapeHtml(lesson.title);
    var primary = lesson.docs_url || lesson.url;
    var titleHtml = primary
      ? '<a href="' + primary + '" target="_blank" rel="noopener">' + title + "</a>"
      : "<span>" + title + "</span>";
    var actions = "";
    if (lesson.available) {
      var done = progress.isComplete(lesson.path);
      actions =
        '<a class="text-link" href="' + lesson.url + '" target="_blank" rel="noopener">GitHub</a>' +
        '<button class="progress-toggle' + (done ? " is-done" : "") +
        '" type="button" data-progress-path="' + lesson.path + '">' +
        (done ? "Пройдено" : "Отметить") + "</button>";
    }
    return (
      '<li class="lesson-row">' +
        '<span class="lesson-number">' + ui.phaseNumber(lesson.number) + "</span>" +
        '<div class="lesson-copy">' + titleHtml +
          '<span class="lesson-outcome">' + ui.escapeHtml(lesson.outcome) + "</span>" +
        "</div>" +
        '<span class="status-badge status-' + lesson.status + '">' +
          ui.statusLabel(lesson.status) +
        "</span>" +
        '<div class="lesson-actions">' + actions + "</div>" +
      "</li>"
    );
  }

  function phaseCard(phase) {
    var availablePaths = phase.lessons.filter(function (lesson) {
      return lesson.available;
    }).map(function (lesson) {
      return lesson.path;
    });
    var complete = progress.count(availablePaths);
    var prerequisites = phase.prerequisites.length
      ? phase.prerequisites.map(ui.phaseNumber).join(", ")
      : "нет";
    return (
      '<article class="phase-card" id="phase-' + ui.phaseNumber(phase.number) + '">' +
        '<div class="phase-card-head">' +
          '<div class="phase-index">' + ui.phaseNumber(phase.number) + "</div>" +
          '<div class="phase-heading">' +
            '<p class="eyebrow">' + ui.escapeHtml(phase.tracks.join(" · ")) + "</p>" +
            "<h3>" + ui.escapeHtml(phase.title) + "</h3>" +
            "<p>" + ui.escapeHtml(phase.summary) + "</p>" +
          "</div>" +
          '<span class="status-badge status-' + phase.status + '">' +
            ui.statusLabel(phase.status) +
          "</span>" +
        "</div>" +
        '<div class="phase-meta">' +
          "<span>~" + phase.hours.min + "–" + phase.hours.max + " ч</span>" +
          "<span>Пререквизиты: " + prerequisites + "</span>" +
          "<span>Личный прогресс: " + complete + "/" + availablePaths.length + "</span>" +
        "</div>" +
        '<details class="phase-lessons"' + (phase.number === 0 ? " open" : "") + ">" +
          "<summary>Уроки фазы <span>" + phase.lessons.length + "</span></summary>" +
          '<ol class="lesson-list">' + phase.lessons.map(lessonRow).join("") + "</ol>" +
          '<a class="phase-source" href="' + phase.url +
          '" target="_blank" rel="noopener">Открыть фазу на GitHub</a>' +
        "</details>" +
      "</article>"
    );
  }

  function renderPhases() {
    var container = document.getElementById("phaseGrid");
    if (!container) return;
    container.innerHTML = data.phases.map(phaseCard).join("");
    container.querySelectorAll("[data-progress-path]").forEach(function (button) {
      button.addEventListener("click", function () {
        progress.toggle(button.getAttribute("data-progress-path"));
      });
    });
  }

  function renderProgress() {
    var paths = [];
    data.phases.forEach(function (phase) {
      phase.lessons.forEach(function (lesson) {
        if (lesson.available) paths.push(lesson.path);
      });
    });
    var done = progress.count(paths);
    var percent = paths.length ? Math.round(done / paths.length * 100) : 0;
    var label = document.getElementById("personalProgress");
    var bar = document.getElementById("personalProgressBar");
    if (label) label.textContent = done + " из " + paths.length + " доступных уроков";
    if (bar) bar.style.width = percent + "%";
  }

  document.addEventListener("DOMContentLoaded", function () {
    renderStats();
    renderRoutes();
    renderPhases();
    renderProgress();
  });

  progress.onChange(function () {
    renderPhases();
    renderProgress();
  });
})();
