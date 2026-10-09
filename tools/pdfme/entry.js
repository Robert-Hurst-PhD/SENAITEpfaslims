// senaite.pfas: the pdfme template designer and generator for the browser
// . Exposed as window.PFASPdfme. Plugin keys are the names the
// Designer's palette shows; a template stores each field's `type`, which is
// what senaite.pfas.document_templates validates (PLUGIN_TYPES there).
import { Designer, Form, Viewer } from "@pdfme/ui";
import { generate } from "@pdfme/generator";
import * as s from "@pdfme/schemas";
import { BLANK_PDF, checkTemplate } from "@pdfme/common";

const plugins = {
  "Text": s.text,
  "Text with fields": s.multiVariableText,
  "Image": s.image,
  "SVG": s.svg,
  "Table": s.table,
  "Line": s.line,
  "Rectangle": s.rectangle,
  "Ellipse": s.ellipse,
  "Date": s.date,
  "Checkbox": s.checkbox,
  "QR code": s.barcodes.qrcode,
  "Code 128": s.barcodes.code128,
  "Code 39": s.barcodes.code39,
  "GS1 DataMatrix": s.barcodes.gs1datamatrix,
  "PDF417": s.barcodes.pdf417,
};
for (const [label, p] of Object.entries(plugins)) {
  if (!p || !p.propPanel) throw new Error("pdfme plugin missing: " + label);
}
// type stored in a template -> the palette name
const typeOf = Object.fromEntries(Object.entries(plugins).map(([k, p]) => [p.propPanel.defaultSchema.type, k]));

// eslint-disable-next-line no-undef
const version = __PDFME_VERSION__;   // set by build.mjs; the renderer reports the same
window.PFASPdfme = { Designer, Form, Viewer, generate, plugins, typeOf, BLANK_PDF, checkTemplate, version };
