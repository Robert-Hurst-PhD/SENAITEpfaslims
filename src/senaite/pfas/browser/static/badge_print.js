/* A badge: a credit-card PDF made in the browser with the vendored
 * pdfme -- name, title, the code as a QR and as Code 128 for any badge
 * scanner. The code reaches this page in the POST that issued it (never a
 * URL) and is gone when the page is left. */
(function () {
  'use strict';
  var data = JSON.parse(document.getElementById('badge-data').textContent);
  var P = window.PFASPdfme;
  function plugin(type) {
    var names = Object.keys(P.plugins);
    for (var i = 0; i < names.length; i++) {
      if (P.plugins[names[i]].propPanel.defaultSchema.type === type) return P.plugins[names[i]];
    }
  }
  function field(type, name, x, y, w, h, extra) {
    var s = JSON.parse(JSON.stringify(plugin(type).propPanel.defaultSchema));
    s.name = name; s.position = { x: x, y: y }; s.width = w; s.height = h;
    Object.keys(extra || {}).forEach(function (k) { s[k] = extra[k]; });
    return s;
  }
  var template = {
    basePdf: { width: 85.6, height: 54, padding: [0, 0, 0, 0] },
    schemas: [[
      field('text', 'lab', 4, 4, 77, 5, { fontSize: 8 }),
      field('text', 'name', 4, 11, 48, 7, { fontSize: 12 }),
      field('text', 'title', 4, 19, 48, 5, { fontSize: 8 }),
      field('qrcode', 'qr', 57, 9, 24, 24, {}),
      field('code128', 'bar', 4, 37, 77.6, 13, { includetext: false })
    ]]
  };
  var inputs = [{ lab: data.lab, name: data.name, title: data.title, qr: data.code, bar: data.code }];
  document.getElementById('badge-print').addEventListener('click', function () {
    P.generate({ template: template, inputs: inputs, plugins: P.plugins }).then(function (pdf) {
      var url = URL.createObjectURL(new Blob([pdf.buffer], { type: 'application/pdf' }));
      var frame = document.getElementById('badge-pdf');
      frame.src = url; frame.hidden = false;
      var open = document.getElementById('badge-open');
      open.href = url; open.hidden = false;
      frame.onload = function () { try { frame.contentWindow.print(); } catch (e) {} };
    });
  });
}());
