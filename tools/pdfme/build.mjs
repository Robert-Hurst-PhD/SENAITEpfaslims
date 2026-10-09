// senaite.pfas: builds static/vendor/pdfme/pdfme.min.js.

// pdfme is MIT, but some code that comes with it is Apache-2.0, which cannot be
// shipped in a GPL-2.0 project. This build keeps every piece of it out, and FAILS
// (rather than shipping) when anything changes under it:
//   @swc/helpers      (fontkit)            -> shim/define_property.js, ts_decorate.js
//   brotli            (fontkit, WOFF2)     -> shim/no_brotli.js
//   jpeg-js decoder   (pdfme EXIF rotate)  -> shim/no_jpeg_decode.js
//   clawpdf / PDFium  (PDF page background)-> shim/no_pdfium.js
//   tslib 1.x helpers inlined by @egjs/children-differ -> our own, below
// @pdfme/ui is built from its source (PDFME_UI_SRC, the pdfme repo at the same
// tag), because its npm dist pre-bundles ~140 packages beyond reach of the
// substitutions above.
// Every bundled file is then scanned for Apache-2.0 text, and every package
// must declare an allowed licence in its package.json (ALLOWED).
import * as esbuild from "esbuild";
import fs from "fs";
import path from "path";

const UI_SRC = process.env.PDFME_UI_SRC || "../pdfme-src/packages/ui/src";
// PDFME_TARGET=node: the server renderer's library (generator, schemas,
// common; no designer), built through the same gate from the same lockfile
// so the stored PDF and the designer's preview come from one pdfme.
const NODE = process.env.PDFME_TARGET === "node";
const OUT = process.env.PDFME_OUT || (NODE
  ? path.resolve(path.dirname(new URL(import.meta.url).pathname), "dist/pdfme-node.min.js")
  : path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src/senaite/pfas/browser/static/vendor/pdfme/pdfme.min.js"));
const ALLOWED = new Set(["MIT", "ISC", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Zlib",
  "(MIT AND Zlib)", "(MPL-2.0 OR Apache-2.0)", "MIT OR Apache-2.0"]);
// Packages whose package.json has no licence field, checked by hand.
const KNOWN = { "component-indexof": "MIT (readme)", "rc-trigger": "MIT (LICENSE file)" };

const HERE = path.dirname(new URL(import.meta.url).pathname);
const VERSION = JSON.stringify(JSON.parse(fs.readFileSync(
  path.resolve("node_modules/@pdfme/generator/package.json"), "utf8")).version);
const SHIM = (f) => path.resolve(HERE, "shim", f);

const EGJS_APACHE = /\/\*! \*+\r?\nCopyright \(c\) Microsoft Corporation\. All rights reserved\.\r?\nLicensed under the Apache License[\s\S]*?\nfunction __extends\(d, b\) \{[\s\S]*?\n\}\n/;
const OURS_EXTENDS = `// senaite.pfas (GPL-2.0): class inheritance helper, our own code.
var extendStatics = function(child, parent) {
  if (Object.setPrototypeOf) Object.setPrototypeOf(child, parent);
  else for (var k in parent) if (Object.prototype.hasOwnProperty.call(parent, k)) child[k] = parent[k];
  return child;
};
function __extends(child, parent) {
  extendStatics(child, parent);
  child.prototype = Object.create(parent === null ? null : parent.prototype, {
    constructor: { value: child, writable: true, configurable: true }
  });
}
`;

const noApache = {
  name: "no-apache",
  setup(b) {
    b.onResolve({ filter: /^@swc\/helpers/ }, (a) => ({
      path: SHIM(a.path.includes("ts_decorate") ? "ts_decorate.js" : "define_property.js") }));
    b.onResolve({ filter: /^clawpdf(\/|$)/ }, () => ({ path: SHIM("no_pdfium.js") }));
    b.onResolve({ filter: /^brotli(\/|$)/ }, () => ({ path: SHIM("no_brotli.js") }));
    b.onResolve({ filter: /^jpeg-js$/ }, () => ({ path: SHIM("no_jpeg_decode.js") }));
    b.onResolve({ filter: /^@pdfme\/ui$/ }, () => ({ path: path.resolve(UI_SRC, "index.ts") }));
    b.onLoad({ filter: /@egjs[\\/]children-differ[\\/]dist[\\/]children-differ\.esm\.js$/ }, (a) => {
      const src = fs.readFileSync(a.path, "utf8");
      if (!EGJS_APACHE.test(src)) throw new Error("children-differ: Apache tslib block not found");
      return { contents: src.replace(EGJS_APACHE, OURS_EXTENDS), loader: "js" };
    });
  },
};

const r = await esbuild.build(NODE ? {
  entryPoints: [path.resolve(HERE, "entry-node.js")], bundle: true, minify: true, format: "esm",
  platform: "node", target: ["node20"], outfile: OUT, plugins: [noApache], metafile: true,
  legalComments: "none", logLevel: "error",
  define: { "process.env.NODE_ENV": '"production"', __PDFME_VERSION__: VERSION },
  banner: { js: "import{createRequire as __pfasCR}from'module';const require=__pfasCR(import.meta.url);" },
} : {
  entryPoints: [path.resolve(HERE, "entry.js")], bundle: true, minify: true, format: "iife", target: ["es2019"],
  outfile: OUT, plugins: [noApache], external: ["node:*"], jsx: "automatic",
  // the pdfme repo's tsconfig maps @pdfme/* to its sources; use the published packages
  nodePaths: [path.resolve("node_modules")],  // the ui sources live outside this folder
  tsconfigRaw: { compilerOptions: { jsx: "react-jsx" } },
  define: { "process.env.NODE_ENV": '"production"', "import.meta.url": "__pfasPdfmeBase",
            __PDFME_VERSION__: VERSION },
  // import.meta does not exist in a classic script: resolve relative assets
  // against this file. No worker is shipped (see no_pdfium.js).
  banner: { js: "var __pfasPdfmeBase=(document.currentScript&&document.currentScript.src)||location.href;" },
  metafile: true, legalComments: "none", logLevel: "error",
});

// ── licence gate ────────────────────────────────────────────────────────────
const APACHE = /Apache License|SPDX-License-Identifier:\s*Apache|Licensed under the Apache/;
const ins = Object.keys(r.metafile.inputs);
const hits = [], pkgs = new Map(), bad = [];
for (const i of ins) {
  if (/(^|[\\/])(@swc|clawpdf|brotli)[\\/]|jpeg-js[\\/]lib[\\/]decoder/.test(i)) throw new Error("excluded code bundled: " + i);
  if (/children-differ\.esm\.js$/.test(i)) continue;            // replaced in onLoad
  if (APACHE.test(fs.readFileSync(i, "utf8"))) hits.push(i);
  const m = i.match(/^(.*node_modules[\\/](?:@[^\\/]+[\\/])?[^\\/]+)/);
  if (m && !pkgs.has(m[1])) pkgs.set(m[1], JSON.parse(fs.readFileSync(path.join(m[1], "package.json"), "utf8")));
}
if (hits.length) throw new Error("Apache-2.0 text in:\n  " + hits.join("\n  "));
for (const [dir, pj] of pkgs) {
  const lic = typeof pj.license === "string" ? pj.license : (pj.license && pj.license.type) || KNOWN[pj.name];
  if (!lic || (!ALLOWED.has(lic) && !KNOWN[pj.name])) bad.push(pj.name + ": " + lic);
}
if (bad.length) throw new Error("licence not allowed:\n  " + bad.join("\n  "));
const out = fs.readFileSync(OUT, "utf8");
fs.writeFileSync(OUT.replace(/\.min\.js$/, ".packages.json"), JSON.stringify(
  [...pkgs].map(([dir, pj]) => ({ dir, name: pj.name, version: pj.version,
    license: typeof pj.license === "string" ? pj.license : (pj.license && pj.license.type) || KNOWN[pj.name] }))
    .sort((a, b) => a.name.localeCompare(b.name)), null, 1));
console.log("ok", ins.length, "files,", pkgs.size, "packages,", (out.length / 1048576).toFixed(1), "MB");

// ── attribution: every bundled package's own licence text travels with it ──
const notice = [
  "Third-party software in pdfme.min.js (senaite.pfas, GPL-2.0).",
  "Built by tools/pdfme/build.mjs. Each package below keeps its own licence.",
  "DOMPurify is used under MPL-2.0 (it is offered as MPL-2.0 OR Apache-2.0).",
  "Not included (Apache-2.0, replaced by senaite.pfas code): @swc/helpers,",
  "brotli, the jpeg-js decoder, clawpdf/PDFium, tslib 1.x helpers.", ""];
// pdfme's own LICENSE (the repository's; its npm packages ship none), kept here
const uiLicence = path.resolve(HERE, "licences", "@pdfme.txt");
const missing = [];
const entries = NODE ? [] : [["@pdfme/ui (built from source)", fs.readFileSync(uiLicence, "utf8")]];
for (const [dir, pj] of [...pkgs].sort((a, b) => a[1].name.localeCompare(b[1].name))) {
  const f = fs.readdirSync(dir).find((n) => /^(licen[cs]e|copying)(\.|$)/i.test(n));
  let text = f ? fs.readFileSync(path.join(dir, f), "utf8") : null;
  const kept = path.join(HERE, "licences", pj.name.replace("/", "__") + ".txt");
  if (!text && fs.existsSync(kept)) text = fs.readFileSync(kept, "utf8");   // upstream LICENSE, fetched once
  if (!text && /^@pdfme\//.test(pj.name) && fs.existsSync(uiLicence)) text = fs.readFileSync(uiLicence, "utf8");
  if (!text) {                                   // some packages state it in the readme only
    const rd = fs.readdirSync(dir).find((n) => /^readme/i.test(n));
    const m = rd && fs.readFileSync(path.join(dir, rd), "utf8").match(/#+\s*licen[cs]e[\s\S]{0,1500}/i);
    text = m ? m[0] : null;
  }
  if (!text) missing.push(pj.name);
  entries.push([pj.name + "@" + pj.version + " (" + (typeof pj.license === "string" ? pj.license : KNOWN[pj.name]) + ")", text]);
}
if (missing.length) throw new Error("no licence text for:\n  " + missing.join("\n  "));
fs.writeFileSync(OUT.replace(/\.min\.js$/, ".LICENSES.txt"),
  notice.join("\n") + entries.map(([h, t]) => "\n" + "=".repeat(78) + "\n" + h + "\n" + "=".repeat(78) + "\n" + t.trim() + "\n").join(""));
console.log("licences written:", entries.length);
