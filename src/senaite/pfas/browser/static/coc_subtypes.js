/* The CoC sample rows' Sub-type: a row offers only the
 * sub-types of its matrix that its method analyses, and none when there are
 * none (the select hides). The server checks the same (coc_entry.
 * subtype_problems). Each option carries its sample type (data-type) and the
 * method profiles turned off for it (data-off). */
(function () {
  "use strict";
  function field(row, key) {
    return row.querySelector('select[name$="__' + key + '"]');
  }
  function sync(row) {
    var sub = field(row, "subtype");
    if (!sub) { return; }
    var type = (field(row, "sampletype") || {}).value || "";
    var method = (field(row, "method") || {}).value || "";
    var any = false;
    Array.prototype.forEach.call(sub.options, function (o) {
      if (!o.value) { return; }
      var off = (o.getAttribute("data-off") || "").split(" ");
      var fits = o.getAttribute("data-type") === type && off.indexOf(method) === -1;
      o.hidden = !fits;
      o.disabled = !fits;
      if (fits) { any = true; } else if (o.selected) { sub.value = ""; }
    });
    sub.hidden = !any;
  }
  document.addEventListener("change", function (e) {
    var name = (e.target && e.target.name) || "";
    if (/__(sampletype|method)$/.test(name)) { sync(e.target.closest("tr")); }
  });
  function all() {
    Array.prototype.forEach.call(document.querySelectorAll("tr"), function (r) {
      if (field(r, "subtype")) { sync(r); }
    });
  }
  if (document.readyState === "loading") { document.addEventListener("DOMContentLoaded", all); } else { all(); }
})();
