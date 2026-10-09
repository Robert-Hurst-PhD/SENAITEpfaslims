/* Manual integration review: the report's pages.
 *
 * PDF.js (Apache-2.0) is loaded from cdnjs, never vendored (GPLv2 add-on). The
 * report comes from @@pfas-mi-report (permission-checked), never a file path.
 *
 * A page whose text carries the lab's heading ("Manual Integration") and a
 * row's injection and analyte is SUGGESTED as that row's before page (the
 * first match) and after page (the second); a suggestion fills only an empty
 * field and is saved only when the analyst presses Save. Click a page field,
 * then a page, to set it by hand. A heading page matching no row is marked:
 * the export may have missed that manual integration. The heading pages found
 * fill "Pages headed ..." (recorded on Save, for this report only).
 */
(function () {
  "use strict";
  var viewer = document.getElementById("mi-viewer");
  if (!viewer || !window.pdfjsLib) return;
  var lib = window.pdfjsLib;
  lib.GlobalWorkerOptions.workerSrc =
    "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
  var status = document.getElementById("mi-viewer-status");
  var thumbs = document.getElementById("mi-thumbs");
  var heading = norm(viewer.getAttribute("data-heading") || "Manual Integration");
  var active = null;

  document.querySelectorAll("input.mi-page").forEach(function (inp) {
    inp.addEventListener("focus", function () {
      document.querySelectorAll("input.mi-page.mi-active").forEach(function (x) { x.classList.remove("mi-active"); });
      inp.classList.add("mi-active");
      active = inp;
    });
  });

  // the same rule as manual_integration.page_has_heading: case and ALL white
  // space ignored (text extraction drops or doubles spaces)
  function norm(s) { return (s || "").toLowerCase().replace(/\s+/g, ""); }

  function rows() {
    return Array.prototype.map.call(document.querySelectorAll("tr[data-mi]"), function (tr) {
      return { tr: tr, injection: norm(tr.querySelector("td:nth-child(2) strong").textContent),
               analyte: norm(tr.querySelector(".mi-analyte").textContent),
               before: tr.querySelector('input.mi-page[data-which="before"]'),
               after: tr.querySelector('input.mi-page[data-which="after"]') };
    });
  }

  function tag(box, text, cls) {
    var t = document.createElement("span");
    t.className = "badge " + (cls || "badge-info");
    t.textContent = text;
    box.querySelector(".mi-thumb-tags").appendChild(t);
  }

  lib.getDocument(viewer.getAttribute("data-url")).promise.then(function (pdf) {
    status.textContent = pdf.numPages + " pages";
    var texts = [], boxes = [];
    var chain = Promise.resolve();
    for (var n = 1; n <= pdf.numPages; n++) {
      (function (n) {
        chain = chain.then(function () { return pdf.getPage(n); }).then(function (page) {
          var vp = page.getViewport({ scale: 0.22 });
          var box = document.createElement("button");
          box.type = "button";
          box.className = "mi-thumb";
          var canvas = document.createElement("canvas");
          canvas.width = vp.width; canvas.height = vp.height;
          box.appendChild(canvas);
          var label = document.createElement("span");
          label.className = "mi-thumb-no";
          label.textContent = "Page " + n;
          box.appendChild(label);
          var tags = document.createElement("span");
          tags.className = "mi-thumb-tags";
          box.appendChild(tags);
          box.addEventListener("click", function () {
            if (!active) { status.textContent = "Click a Before or After page field first."; return; }
            active.value = n;
            active.classList.add("mi-set");
          });
          thumbs.appendChild(box);
          boxes[n] = box;
          return page.render({ canvasContext: canvas.getContext("2d"), viewport: vp }).promise
            .then(function () { return page.getTextContent(); })
            .then(function (tc) { texts[n] = norm(tc.items.map(function (i) { return i.str; }).join(" ")); });
        });
      })(n);
    }
    return chain.then(function () {
      var used = {};
      rows().forEach(function (r) {
        var hits = [];
        for (var n = 1; n < texts.length; n++) {
          var t = texts[n] || "";
          if (t.indexOf(heading) >= 0 && t.indexOf(r.injection) >= 0 && t.indexOf(r.analyte) >= 0) hits.push(n);
        }
        hits.forEach(function (n) { used[n] = true; });
        if (hits[0]) { tag(boxes[hits[0]], r.tr.getAttribute("data-mi") + " before?");
                       if (!r.before.value) { r.before.value = hits[0]; r.before.classList.add("mi-suggested"); } }
        // one matching page: before and after may be drawn side by side on it
        var after = hits[1] || hits[0];
        if (after) { tag(boxes[after], r.tr.getAttribute("data-mi") + " after?");
                     if (!r.after.value) { r.after.value = after; r.after.classList.add("mi-suggested"); } }
      });
      var unlisted = 0, found = [];
      for (var n = 1; n < texts.length; n++) {
        if ((texts[n] || "").indexOf(heading) < 0) continue;
        found.push(n);
        if (!used[n]) { tag(boxes[n], "not listed", "badge-warning"); unlisted++; }
      }
      // the heading pages are recorded on Save; the gate refuses any page
      // that no row lists and no one has dismissed. Like the page fields, the
      // scan fills only an empty field: a recorded list (perhaps corrected by
      // hand, for a page whose text the scan cannot read) is never replaced.
      var hp = document.getElementById("mi-heading-pages");
      var want = found.length ? found.join(", ") : "none";
      var differs = "";
      // what the scan found goes with Save too: a found page cannot be typed
      // away, only dismissed with a reason
      var sf = document.getElementById("mi-scan-found");
      if (sf) sf.value = want;
      if (hp && !hp.readOnly && !hp.value.trim()) {
        hp.value = want;
        hp.classList.add("mi-suggested");
      } else if (hp && hp.value.replace(/\s/g, "") !== want.replace(/\s/g, "")) {
        differs = "; the scan found heading pages " + want + ", not as recorded";
      }
      status.textContent = pdf.numPages + " pages" + (unlisted ? "; " + unlisted + " manual-integration page(s) match no row: add them" : "") +
        differs + ". Suggestions fill empty fields only; press Save to keep them.";
    });
  }).catch(function (e) {
    status.textContent = "The report could not be shown (" + e.message + "). Type the page numbers instead.";
  });
})();
