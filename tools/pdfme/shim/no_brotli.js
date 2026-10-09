// senaite.pfas (GPL-2.0): the brotli decoder is Apache-2.0 and is not shipped.
// fontkit only needs it for WOFF2 fonts; senaite.pfas fonts are TTF.
module.exports = function decompress() {
  throw new Error("WOFF2 fonts are not supported: use a TTF font.");
};
