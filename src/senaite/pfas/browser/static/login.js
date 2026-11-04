/* The sign-in page: the clock, and the account tiles.
 * A tile fills in the user name only; the password is always asked for.
 * Without this script the page is Plone's plain form. */
(function () {
  "use strict";
  var time = document.getElementById("login-time");
  var date = document.getElementById("login-date");
  /* the laboratory's clock when the page gives it (while a zone is set), run
     on from when the page opened; the device's own clock otherwise */
  var clock = document.querySelector(".login-clock");
  var lab = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)$/.exec((clock && clock.getAttribute("data-lab-now")) || "");
  var opened = Date.now();
  /* ISO 8601 like every date in the LIMS: 24-hour HH:MM, YYYY-MM-DD */
  function two(n) { return (n < 10 ? "0" : "") + n; }
  function tick() {
    var now, parts;
    if (lab) {
      now = new Date(Date.UTC(+lab[1], lab[2] - 1, +lab[3], +lab[4], +lab[5], +lab[6]) + (Date.now() - opened));
      parts = [now.getUTCHours(), now.getUTCMinutes(), now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate()];
    } else {
      now = new Date();
      parts = [now.getHours(), now.getMinutes(), now.getFullYear(), now.getMonth(), now.getDate()];
    }
    if (time) time.textContent = two(parts[0]) + ":" + two(parts[1]);
    if (date) date.textContent = parts[2] + "-" + two(parts[3] + 1) + "-" + two(parts[4]);
  }
  tick();
  setInterval(tick, 15000);

  var card = document.querySelector(".login-card");
  var user = document.getElementById("__ac_name");
  var pass = document.getElementById("__ac_password");
  var chosen = document.getElementById("login-chosen");
  if (!card || !user || !pass) return;
  var tiles = document.querySelectorAll(".login-tile");
  tiles.forEach(function (tile) {
    tile.addEventListener("click", function () {
      tiles.forEach(function (t) { t.classList.remove("is-chosen"); });
      tile.classList.add("is-chosen");
      var login = tile.getAttribute("data-login") || "";
      user.value = login;
      if (login) {
        document.getElementById("login-chosen-img").src = tile.querySelector("img").src;
        document.getElementById("login-chosen-name").textContent = tile.getAttribute("data-name");
        chosen.hidden = false;
        card.classList.add("has-chosen");
        pass.value = "";
        pass.focus();
      } else {
        chosen.hidden = true;
        card.classList.remove("has-chosen");
        user.focus();
      }
    });
  });
  if (!tiles.length && !user.value) user.focus();
  else if (user.value) pass.focus();
})();
