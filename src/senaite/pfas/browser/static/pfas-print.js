/* A page that does not say what document it is prints under its own title:
   the browser tab's text names it in the control block and the footer. The
   server wrote everything else (revision, who printed it and when). */
(function () {
  function name() {
    var h = document.getElementById('pfas-printhead');
    if (!h || h.getAttribute('data-auto') !== '1') { return; }
    var t = (document.title || '').replace(/^\s+|\s+$/g, '');
    if (!t) { return; }
    var id = h.querySelector('.pd-docid');
    if (id) { id.textContent = t; }
    var s = document.getElementById('pfas-pagefoot');
    if (s) {
      s.textContent = '@page { @bottom-left { content: "' + t.replace(/["\\]/g, '\\$&') +
        (h.getAttribute('data-foot') || '') + '"; } }';
    }
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', name);
  } else {
    name();
  }
  window.addEventListener('beforeprint', name);
})();
