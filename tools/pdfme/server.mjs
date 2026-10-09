// senaite.pfas document renderer: pdfme's generator behind one
// endpoint, for documents that must be rendered on the server from an issued
// template (certificates, logbook PDFs, reports). Reachable only from SENAITE
// on the internal `render` network; no port is published.

//   GET  /health   -> {"ok": true, "pdfme": "<version>"}
//   POST /render   {"template": {...}, "inputs": [{...}, ...]} -> application/pdf
//                  or {"documents": [{"template", "inputs"}, ...]}: each document
//                  rendered from its own (compiled) template, merged in order
//   POST /pages    <pdf bytes> -> {"pages": n}
//   POST /stamp    <one line of JSON>\n<pdf bytes> -> application/pdf
//                  {"stamps": [{"page": 1-based, "blocks": [{"title", "lines": [..],
//                  "signatures": [{"label", "png": data URI}]}]}]}: each stamped
//                  page is made taller and its content moved up, and the blocks
//                  are drawn in the new strip -- never over the original content
//                  (manual integration). Binary in, binary out: an
//                  instrument report is too large for base64 JSON.

// Limits: a 25 MB request, 500 inputs, 60 s per render. Errors answer JSON
// {"error": "..."} with 400 (the request) or 500 (the render).
import http from "http";
import { generate, checkTemplate, plugins, version, PDFDocument, StandardFonts, rgb } from "./dist/pdfme-node.min.js";

const PORT = Number(process.env.PORT || 3000);
const MAX_BYTES = 25 * 1024 * 1024;
const MAX_REPORT_BYTES = 150 * 1024 * 1024;   // /pages and /stamp: whole instrument reports
const MAX_INPUTS = 500;
const TIMEOUT_MS = 60000;

function answer(res, status, body, type) {
  const data = type ? body : Buffer.from(JSON.stringify(body));
  res.writeHead(status, { "Content-Type": type || "application/json", "Content-Length": data.length });
  res.end(data);
}

function readBody(req, limit = MAX_BYTES) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    let size = 0;
    req.on("data", (c) => {
      size += c.length;
      if (size > limit) { reject(Object.assign(new Error("request larger than " + Math.round(limit / 1048576) + " MB"), { status: 400 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function withTimeout(promise) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => {
    timer = setTimeout(() => reject(new Error("render took longer than 60 s")), TIMEOUT_MS);
  })]).finally(() => clearTimeout(timer));
}

const STRIP_PAD = 6, LINE_H = 10, SIG_H = 28, SIG_AREA = SIG_H + 18;   // image + its label
const TITLE_SIZE = 8.5, TEXT_SIZE = 7.5, MARGIN = 10;

// Helvetica (a standard PDF font, nothing embedded) encodes WinAnsi only.
// These have a faithful plain spelling; any other character is REFUSED with
// where it is, never dropped or swapped for "?": a stamp is a record.
const SPELL = {
  "\u2264": "<=", "\u2265": ">=", "\u2260": "!=", "\u2248": "~", "\u2192": "->", "\u2190": "<-",
  "\u2212": "-", "\u2010": "-", "\u2011": "-", "\u2009": " ", "\u202f": " ", "\u200b": "",
  "\u03b1": "alpha", "\u03b2": "beta", "\u03b3": "gamma", "\u03b4": "delta", "\u0394": "delta",
  "\u03c3": "sigma", "\u03bc": "\u00b5",
  "\n": " ", "\r": " ", "\t": " ",
};

function plain(text, font, where) {
  let out = "";
  for (const ch of String(text == null ? "" : text)) {
    const c = Object.prototype.hasOwnProperty.call(SPELL, ch) ? SPELL[ch] : ch;
    try { font.widthOfTextAtSize(c, TEXT_SIZE); }
    catch (e) {
      const code = "U+" + ch.codePointAt(0).toString(16).toUpperCase().padStart(4, "0");
      throw Object.assign(new Error("the stamp cannot print \"" + ch + "\" (" + code + ") in " + where + ": rewrite it"), { status: 400 });
    }
    out += c;
  }
  return out;
}

// whole words to the line; a word longer than a line is cut
function wrap(text, font, size, maxW) {
  const lines = [];
  let cur = "";
  for (let w of text.split(/ +/)) {
    while (w && font.widthOfTextAtSize(w, size) > maxW) {
      let n = w.length - 1;
      while (n > 1 && font.widthOfTextAtSize(w.slice(0, n), size) > maxW) n--;
      if (cur) { lines.push(cur); cur = ""; }
      lines.push(w.slice(0, n));
      w = w.slice(n);
    }
    if (!w) continue;
    const t = cur ? cur + " " + w : w;
    if (font.widthOfTextAtSize(t, size) <= maxW) cur = t;
    else { lines.push(cur); cur = w; }
  }
  if (cur || !lines.length) lines.push(cur);
  return lines;
}

// a block made printable for a page `width` wide: every line wrapped
function layout(b, width, font, bold, where) {
  const maxW = width - 2 * MARGIN;
  const title = b.title ? wrap(plain(b.title, bold, where + ", title"), bold, TITLE_SIZE, maxW) : [];
  const lines = [];
  (b.lines || []).forEach((l, i) => lines.push(...wrap(plain(l, font, where + ", line " + (i + 1)), font, TEXT_SIZE, maxW)));
  const signatures = (b.signatures || []).map((sig, i) => ({ png: sig.png, label: plain(sig.label || "", font, where + ", signature " + (i + 1)) }));
  const h = STRIP_PAD * 2 + (title.length + lines.length) * LINE_H + (signatures.length ? SIG_AREA : 0);
  return { title, lines, signatures, h };
}

async function stamp(pdfBytes, spec) {
  const doc = await PDFDocument.load(pdfBytes, { updateMetadata: false });
  const font = await doc.embedFont(StandardFonts.Helvetica);
  const bold = await doc.embedFont(StandardFonts.HelveticaBold);
  const pages = doc.getPages();
  for (const s of spec.stamps || []) {
    const idx = Number(s.page) - 1;
    if (!(idx >= 0 && idx < pages.length)) throw Object.assign(new Error("page " + s.page + " is not in the report (" + pages.length + " pages)"), { status: 400 });
    const page = pages[idx];
    const { width, height } = page.getSize();
    const blocks = (s.blocks || []).map((b, i) => layout(b, width, font, bold, "page " + s.page + " block " + (i + 1)));
    const strip = blocks.reduce((h, b) => h + b.h, 0);
    // taller page, original content moved up: the stamp never covers it
    page.setSize(width, height + strip);
    page.translateContent(0, strip);
    // translateContent wraps the page's content streams -- including the one
    // pdf-lib draws into next -- so everything drawn below is shifted up by
    // `strip` too. Start at -strip: the blocks land in the new bottom strip,
    // never on the original content (checked on a full page).
    let y = strip;
    for (const b of blocks) {
      const h = b.h;
      y -= h;
      const yb = y - strip;
      page.drawRectangle({ x: 4, y: yb + 2, width: width - 8, height: h - 4,
                           borderColor: rgb(0.1, 0.1, 0.1), borderWidth: 0.8, color: rgb(1, 1, 1) });
      let ty = yb + h - STRIP_PAD - 8;
      for (const line of b.title) { page.drawText(line, { x: MARGIN, y: ty, size: TITLE_SIZE, font: bold }); ty -= LINE_H; }
      for (const line of b.lines) { page.drawText(line, { x: MARGIN, y: ty, size: TEXT_SIZE, font }); ty -= LINE_H; }
      let sx = 10;
      for (const sig of b.signatures || []) {
        page.drawText(sig.label, { x: sx, y: yb + STRIP_PAD + 2, size: 7, font });
        if (sig.png && /^data:image\/(png|jpeg);base64,/.test(sig.png)) {
          // a copy: a small Buffer lives inside a shared pool at an offset,
          // and pdf-lib reads the underlying memory from 0
          const raw = new Uint8Array(Buffer.from(sig.png.split(",")[1], "base64"));
          const img = sig.png.startsWith("data:image/png") ? await doc.embedPng(raw) : await doc.embedJpg(raw);
          const scale = Math.min(SIG_H / img.height, 110 / img.width);
          page.drawImage(img, { x: sx + 4, y: yb + STRIP_PAD + 12, width: img.width * scale, height: img.height * scale });
        }
        sx += Math.max(140, (width - 20) / Math.max(1, b.signatures.length));
      }
    }
  }
  return doc.save();
}

const server = http.createServer(async (req, res) => {
  try {
    if (req.method === "GET" && req.url === "/health") return answer(res, 200, { ok: true, pdfme: version });
    if (req.method === "POST" && req.url === "/pages") {
      const body = await readBody(req, MAX_REPORT_BYTES);
      const doc = await PDFDocument.load(body, { updateMetadata: false });
      return answer(res, 200, { pages: doc.getPageCount() });
    }
    if (req.method === "POST" && req.url === "/stamp") {
      const body = await readBody(req, MAX_REPORT_BYTES);
      const nl = body.indexOf(10);
      if (nl < 0) return answer(res, 400, { error: "expected a line of JSON, then the PDF" });
      let spec;
      try { spec = JSON.parse(body.slice(0, nl).toString("utf8")); }
      catch (e) { return answer(res, 400, { error: "the stamp specification is not JSON" }); }
      try {
        const out = await withTimeout(stamp(new Uint8Array(body.subarray(nl + 1)), spec));
        return answer(res, 200, Buffer.from(out), "application/pdf");
      } catch (e) {
        return answer(res, e.status || 500, { error: String(e && e.message || e) });
      }
    }
    if (req.method !== "POST" || req.url !== "/render") return answer(res, 404, { error: "not found" });
    let payload;
    try {
      payload = JSON.parse((await readBody(req)).toString("utf8"));
    } catch (e) {
      return answer(res, 400, { error: e.status ? e.message : "the request is not JSON" });
    }
    const docs = Array.isArray(payload && payload.documents) ? payload.documents
      : [{ template: payload && payload.template, inputs: payload && payload.inputs }];
    const total = docs.reduce((n, d) => n + (Array.isArray(d && d.inputs) ? d.inputs.length : 0), 0);
    if (!docs.length || total > MAX_INPUTS || docs.some((d) => !Array.isArray(d && d.inputs) || !d.inputs.length)) {
      return answer(res, 400, { error: "each document needs inputs; at most 500 in all" });
    }
    for (const d of docs) {
      try {
        checkTemplate(d.template);
      } catch (e) {
        return answer(res, 400, { error: "invalid template: " + e.message });
      }
    }
    const pdf = await withTimeout((async () => {
      if (docs.length === 1) return generate({ template: docs[0].template, inputs: docs[0].inputs, plugins });
      const merged = await PDFDocument.create();
      for (const d of docs) {
        const part = await PDFDocument.load(await generate({ template: d.template, inputs: d.inputs, plugins }));
        for (const page of await merged.copyPages(part, part.getPageIndices())) merged.addPage(page);
      }
      return merged.save();
    })());
    return answer(res, 200, Buffer.from(pdf), "application/pdf");
  } catch (e) {
    console.error("render failed:", e && e.stack || e);
    if (!res.headersSent) answer(res, 500, { error: String(e && e.message || e) });
  }
});
server.requestTimeout = TIMEOUT_MS + 10000;
server.listen(PORT, () => console.log("pdfme " + version + " renderer on :" + PORT));
