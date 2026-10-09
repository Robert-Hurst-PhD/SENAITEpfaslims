// senaite.pfas (GPL-2.0): PDFium (via clawpdf) carries Apache-2.0 components and
// is not shipped. It is only used to draw an uploaded PDF as a template's page
// background; senaite.pfas templates use a blank page or an image instead.
export async function createEngine() {
  throw new Error("PDF page backgrounds are not available: use a blank page or an image.");
}
