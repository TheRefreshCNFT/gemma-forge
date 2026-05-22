(function () {
  "use strict";

  var expectedPhrase = "Hello World";

  function ensureStatusElement() {
    var existing = document.getElementById("validation-status");

    if (existing) {
      return existing;
    }

    var status = document.createElement("p");
    status.id = "validation-status";
    status.setAttribute("role", "status");
    document.body.appendChild(status);
    return status;
  }

  function validate() {
    var chars = Array.prototype.slice.call(document.querySelectorAll(".char"));
    var phrase = chars.map(function (char) {
      return char.textContent || "";
    }).join("");
    var colors = chars.map(function (char) {
      return window.getComputedStyle(char).color;
    });
    var uniqueColorCount = new Set(colors).size;
    var failures = [];

    if (chars.length !== expectedPhrase.length) {
      failures.push("expected " + expectedPhrase.length + " .char spans, found " + chars.length);
    }

    if (phrase !== expectedPhrase) {
      failures.push("expected phrase \"" + expectedPhrase + "\", found \"" + phrase + "\"");
    }

    if (uniqueColorCount !== colors.length) {
      failures.push("expected unique computed text colors for every .char span");
    }

    var passed = failures.length === 0;
    var status = ensureStatusElement();

    document.body.dataset.validation = passed ? "passed" : "failed";
    status.textContent = passed
      ? "Validation passed: Hello World uses " + chars.length + " uniquely colored character spans."
      : "Validation failed: " + failures.join("; ") + ".";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", validate, { once: true });
  } else {
    validate();
  }
}());
