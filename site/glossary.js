(function () {
  "use strict";

  var terms = window.COURSE_DATA.glossary;
  var ui = window.AnalystToolsSite;

  function render(query) {
    var normalized = query.trim().toLowerCase();
    var filtered = terms.filter(function (item) {
      return (item.term + " " + item.definition).toLowerCase().indexOf(normalized) !== -1;
    });
    document.getElementById("glossaryCount").textContent =
      "Показано " + filtered.length + " из " + terms.length;
    document.getElementById("glossaryList").innerHTML = filtered.length
      ? filtered.map(function (item) {
          return (
            '<article class="term-card">' +
              "<h2>" + ui.escapeHtml(item.term) + "</h2>" +
              "<p>" + ui.escapeHtml(item.definition) + "</p>" +
            "</article>"
          );
        }).join("")
      : '<p class="empty-state">Термин не найден.</p>';
  }

  document.addEventListener("DOMContentLoaded", function () {
    var input = document.getElementById("glossarySearch");
    input.addEventListener("input", function () { render(input.value); });
    render("");
  });
})();
