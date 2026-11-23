/* pfas-browser-check.js -- a plain notice for a browser older than the lab
   supports (early 2023: Chromium 111, Firefox 113, Safari 16.2). The pages
   rely on color-mix(), which those versions introduced, so a browser that
   cannot parse it is the older one. Written in ES5 on purpose: it must run
   in the browsers it warns. Nothing else changes for them. */
(function () {
  var supported = true;
  try {
    supported = !!(window.CSS && CSS.supports &&
      CSS.supports('color', 'color-mix(in srgb, red, blue)'));
  } catch (e) { supported = true; }
  if (supported) return;
  function show() {
    if (document.getElementById('pfas-old-browser')) return;
    var box = document.createElement('div');
    box.id = 'pfas-old-browser';
    box.className = 'pfas-banner is-warn';
    box.setAttribute('role', 'alert');
    box.appendChild(document.createTextNode(
      'This browser is older than this system supports, so some pages may look wrong. ' +
      'Update the browser, or open the system in another one.'));
    document.body.insertBefore(box, document.body.firstChild);
  }
  if (document.body) show();
  else document.addEventListener('DOMContentLoaded', show);
})();
