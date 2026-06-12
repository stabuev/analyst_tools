(function () {
  "use strict";

  var data = window.COURSE_DATA;
  var ui = window.AnalystToolsSite;

  function renderRoute(route) {
    var phases = route.phases.map(function (phase, index) {
      var connector = index < route.phases.length - 1 ? '<span class="route-arrow">→</span>' : "";
      return (
        '<a class="route-phase status-' + phase.status + '" href="index.html#phase-' +
          ui.phaseNumber(phase.number) + '">' +
          '<span>' + ui.phaseNumber(phase.number) + "</span>" +
          "<strong>" + ui.escapeHtml(phase.title) + "</strong>" +
        "</a>" + connector
      );
    }).join("");
    return (
      '<article class="route-detail">' +
        '<div class="route-detail-head">' +
          "<div><p class=\"eyebrow\">Профессиональный маршрут</p><h2>" +
            ui.escapeHtml(route.name) + "</h2></div>" +
          '<div class="route-detail-hours">' + route.hours.min + "–" +
            route.hours.max + "<small>часов</small></div>" +
        "</div>" +
        '<p class="route-path">' + ui.escapeHtml(route.path) + "</p>" +
        '<div class="route-sequence">' + phases + "</div>" +
      "</article>"
    );
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.getElementById("routesList").innerHTML =
      data.routes.map(renderRoute).join("");
  });
})();
