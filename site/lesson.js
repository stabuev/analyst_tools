(function () {
  "use strict";

  var progress = window.AnalystToolsProgress;

  function initProgress() {
    var button = document.getElementById("lessonProgress");
    if (!button || !progress) return;
    var path = button.getAttribute("data-progress-path");

    function paint() {
      var done = progress.isComplete(path);
      button.classList.toggle("is-done", done);
      button.textContent = done ? "Пройдено" : "Отметить пройденным";
    }

    button.addEventListener("click", function () {
      progress.toggle(path);
    });
    progress.onChange(paint);
    paint();
  }

  function initQuizzes() {
    document.querySelectorAll(".quiz-question").forEach(function (question) {
      var correct = Number(question.getAttribute("data-correct"));
      var feedback = question.querySelector(".quiz-feedback");
      question.querySelectorAll(".quiz-option").forEach(function (button) {
        button.addEventListener("click", function () {
          var choice = Number(button.getAttribute("data-choice"));
          question.querySelectorAll(".quiz-option").forEach(function (option) {
            var optionChoice = Number(option.getAttribute("data-choice"));
            option.disabled = true;
            option.classList.toggle("is-correct", optionChoice === correct);
            option.classList.toggle("is-wrong", optionChoice === choice && choice !== correct);
          });
          if (feedback) {
            feedback.hidden = false;
            feedback.classList.toggle("is-correct", choice === correct);
            feedback.insertAdjacentText("afterbegin", choice === correct ? "Верно. " : "Пока нет. ");
          }
        }, { once: true });
      });
    });
  }

  function initCopyButtons() {
    document.querySelectorAll(".copy-button").forEach(function (button) {
      button.addEventListener("click", function () {
        var code = button.parentElement.querySelector("code");
        if (!code || !navigator.clipboard) return;
        navigator.clipboard.writeText(code.textContent).then(function () {
          var previous = button.textContent;
          button.textContent = "Скопировано";
          window.setTimeout(function () { button.textContent = previous; }, 1200);
        });
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    initProgress();
    initQuizzes();
    initCopyButtons();
  });
})();
