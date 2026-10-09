// senaite.pfas (GPL-2.0): jpeg-js's decoder is Apache-2.0 (from pdf.js) and is
// not shipped. pdfme uses it only to straighten a JPEG whose EXIF says it is
// rotated, and falls back to the image as stored when this throws.
function unavailable() {
  throw new Error("JPEG re-orientation is not available.");
}
module.exports = { decode: unavailable, encode: unavailable };
