// senaite.pfas: the server renderer's pdfme. Plugin keys are the
// field TYPES a template stores (document_templates.PLUGIN_TYPES); the
// browser bundle (entry.js) offers the same plugins under palette names.
import { generate } from "@pdfme/generator";
import * as s from "@pdfme/schemas";
import { checkTemplate } from "@pdfme/common";
import { PDFDocument, StandardFonts, rgb } from "@pdfme/pdf-lib";

export const plugins = {
  text: s.text, multiVariableText: s.multiVariableText, image: s.image, svg: s.svg,
  table: s.table, line: s.line, rectangle: s.rectangle, ellipse: s.ellipse,
  date: s.date, checkbox: s.checkbox, qrcode: s.barcodes.qrcode,
  code128: s.barcodes.code128, code39: s.barcodes.code39,
  gs1datamatrix: s.barcodes.gs1datamatrix, pdf417: s.barcodes.pdf417,
};
// eslint-disable-next-line no-undef
export const version = __PDFME_VERSION__;   // set by build.mjs
export { generate, checkTemplate, PDFDocument, StandardFonts, rgb };
