/* The sign-in page: the clock, and the account tiles.
 * A tile fills in the user name only; the password is always asked for.
 * Without this script the page is Plone's plain form. */
(function () {
  "use strict";
  var time = document.getElementById("login-time");
  var date = document.getElementById("login-date");
  function tick() {
    var now = new Date();
    if (time) time.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (date) date.textContent = now.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
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
