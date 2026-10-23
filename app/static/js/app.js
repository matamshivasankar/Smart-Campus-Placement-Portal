/* Client side helpers.
 *
 * These only improve usability. Every action on the portal is still validated
 * and committed on the server - nothing here replaces a backend operation.
 * Submit buttons are deliberately left enabled so that WTForms submit fields
 * are always part of the POST data.
 */
(function () {
  "use strict";

  // Ask for confirmation before irreversible submissions.
  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form.matches("form[data-confirm]")) {
      return;
    }
    var message = form.getAttribute("data-confirm") || "Are you sure?";
    if (!window.confirm(message)) {
      event.preventDefault();
    }
  });

  // Keep the chosen file name visible next to a file input.
  document.querySelectorAll("input[type=file]").forEach(function (input) {
    var selector = input.getAttribute("data-filename-target");
    if (!selector) {
      return;
    }
    input.addEventListener("change", function () {
      var target = document.querySelector(selector);
      if (target && input.files.length) {
        target.textContent = input.files[0].name;
      }
    });
  });

  // Collapse helper: auto dismiss alerts after a while.
  window.setTimeout(function () {
    document.querySelectorAll(".alert-auto-dismiss").forEach(function (alert) {
      alert.classList.remove("show");
      window.setTimeout(function () { alert.remove(); }, 300);
    });
  }, 6000);
})();
