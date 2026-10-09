# pdfme bundle (document template designer)

`src/senaite/pfas/browser/static/vendor/pdfme/` is built here. It is pdfme 6.2.2
(MIT, github.com/pdfme/pdfme): the drag-and-drop template Designer, the Viewer
and Form, and the PDF generator, as one browser script exposing
`window.PFASPdfme` (see `entry.js`).

## Rebuild

```sh
git clone --depth 1 --branch 6.2.2 https://github.com/pdfme/pdfme.git /tmp/pdfme-src
cd tools/pdfme
npm ci --legacy-peer-deps
PDFME_UI_SRC=/tmp/pdfme-src/packages/ui/src node build.mjs
```

The build is deterministic from `package-lock.json`. It writes:

| File | What |
|---|---|
| `pdfme.min.js` | the bundle |
| `pdfme.min.css` | styles the Designer's property panel needs |
| `pdfme.LICENSES.txt` | every bundled package's own licence text (MIT, ISC, BSD and the others need their notice shipped) |
| `pdfme.packages.json` | name, version and licence of every bundled package |

## Why it is built, not downloaded

This project is GPL-2.0, and Apache-2.0 code cannot be combined with GPL-2.0.
pdfme itself is MIT, but some code that comes with it is Apache-2.0. The build
replaces each piece with our own code (`shim/`) and **fails** if any comes back:

| Apache-2.0 code | Used for | Replaced by |
|---|---|---|
| `@swc/helpers` (via fontkit) | class-field helpers | `shim/define_property.js`, `shim/ts_decorate.js` (tslib, 0BSD) |
| `brotli` (via fontkit) | WOFF2 fonts | `shim/no_brotli.js`: TTF only |
| `jpeg-js` decoder (from pdf.js) | straightening EXIF-rotated JPEGs | `shim/no_jpeg_decode.js`: pdfme falls back to the image as stored |
| `clawpdf` / PDFium | drawing an uploaded PDF as page background | `shim/no_pdfium.js`: templates use a blank page or an image |
| tslib 1.x helpers inlined by `@egjs/children-differ` | class inheritance | our own `__extends` in `build.mjs` |

`@pdfme/ui` is compiled from its source (the pdfme repository at the same tag)
because its npm build already contains ~140 packages, `@swc/helpers` and `brotli`
among them, where no substitution can reach.

After bundling, every input file is scanned for Apache-2.0 licence text, and
every package must declare a licence in `ALLOWED`. DOMPurify is taken under
MPL-2.0 (it is offered as MPL-2.0 OR Apache-2.0). `licences/` holds the upstream
LICENSE of the few packages that do not ship one.
