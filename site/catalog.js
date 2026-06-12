(function () {
  "use strict";

  var data = window.COURSE_DATA;
  var ui = window.AnalystToolsSite;
  var state = { query: "", phase: "", status: "", track: "" };
  var lessons = [];

  data.phases.forEach(function (phase) {
    phase.lessons.forEach(function (lesson) {
      lessons.push(Object.assign({ phase: phase.number, phaseTitle: phase.title }, lesson));
    });
  });

  function fillSelects() {
    var phase = document.getElementById("phaseFilter");
    var track = document.getElementById("trackFilter");
    data.phases.forEach(function (item) {
      phase.insertAdjacentHTML(
        "beforeend",
        '<option value="' + item.number + '">' +
        ui.phaseNumber(item.number) + " · " + ui.escapeHtml(item.title) + "</option>"
      );
    });
    Object.keys(data.tracks).forEach(function (key) {
      track.insertAdjacentHTML(
        "beforeend",
        '<option value="' + key + '">' + ui.escapeHtml(data.tracks[key]) + "</option>"
      );
    });
  }

  function matches(lesson) {
    var haystack = [
      lesson.title,
      lesson.outcome,
      lesson.artifact,
      lesson.phaseTitle,
    ].join(" ").toLowerCase();
    return (!state.query || haystack.indexOf(state.query) !== -1) &&
      (!state.phase || String(lesson.phase) === state.phase) &&
      (!state.status || lesson.status === state.status) &&
      (!state.track || lesson.tracks.indexOf(state.track) !== -1);
  }

  function render() {
    var filtered = lessons.filter(matches);
    var count = document.getElementById("catalogCount");
    var body = document.getElementById("catalogBody");
    count.textContent = "Показано " + filtered.length + " из " + lessons.length;
    if (!filtered.length) {
      body.innerHTML = '<tr><td colspan="6" class="empty-state">Ничего не найдено.</td></tr>';
      return;
    }
    body.innerHTML = filtered.map(function (lesson) {
      var link = lesson.docs_url || lesson.url;
      var title = link
        ? '<a href="' + link + '" target="_blank" rel="noopener">' +
          ui.escapeHtml(lesson.title) + "</a>"
        : ui.escapeHtml(lesson.title);
      return (
        "<tr>" +
          '<td><span class="phase-chip">' + ui.phaseNumber(lesson.phase) + "</span></td>" +
          '<td class="catalog-title">' + title +
            "<small>" + ui.escapeHtml(lesson.outcome) + "</small></td>" +
          "<td>" + (lesson.time_minutes || "—") + "</td>" +
          "<td>" + ui.escapeHtml(lesson.tracks.join(", ")) + "</td>" +
          '<td><span class="status-badge status-' + lesson.status + '">' +
            ui.statusLabel(lesson.status) + "</span></td>" +
          "<td>" + (lesson.url
            ? '<a class="text-link" href="' + lesson.url +
              '" target="_blank" rel="noopener">Исходники</a>'
            : "—") + "</td>" +
        "</tr>"
      );
    }).join("");
  }

  function bind(id, key, transform) {
    document.getElementById(id).addEventListener("input", function (event) {
      state[key] = transform ? transform(event.target.value) : event.target.value;
      render();
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("catalogSummary").textContent =
      data.stats.lessons + " уроков · " + data.stats.phases + " фаз";
    fillSelects();
    bind("catalogSearch", "query", function (value) {
      return value.trim().toLowerCase();
    });
    bind("phaseFilter", "phase");
    bind("statusFilter", "status");
    bind("trackFilter", "track");
    render();
  });
})();
