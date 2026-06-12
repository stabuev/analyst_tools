(function () {
  "use strict";

  var STORAGE_KEY = "analyst-tools-progress-v1";
  var listeners = [];

  function read() {
    try {
      var parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (_) {
      return {};
    }
  }

  function write(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (_) {}
    listeners.forEach(function (listener) {
      listener(state);
    });
  }

  function isComplete(path) {
    return Boolean(read()[path]);
  }

  function toggle(path) {
    var state = read();
    if (state[path]) {
      delete state[path];
    } else {
      state[path] = Date.now();
    }
    write(state);
  }

  function count(paths) {
    var state = read();
    return paths.filter(function (path) { return Boolean(state[path]); }).length;
  }

  function reset() {
    write({});
  }

  function onChange(listener) {
    listeners.push(listener);
  }

  window.addEventListener("storage", function (event) {
    if (event.key !== STORAGE_KEY) return;
    var state = read();
    listeners.forEach(function (listener) {
      listener(state);
    });
  });

  window.AnalystToolsProgress = {
    count: count,
    isComplete: isComplete,
    onChange: onChange,
    reset: reset,
    toggle: toggle,
  };
})();
