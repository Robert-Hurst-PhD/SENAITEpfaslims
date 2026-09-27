# -*- coding: utf-8 -*-
"""Attach SPECIMEN manufacturer Certificates of Analysis to reagent lots.

Run inside the SENAITE container:

  docker exec <container> bin/instance -O senaite run \
    /addon/scripts/seed_example_coas.py

WHY THIS EXISTS. The reagent CoA is level 1 of the ISO 17025 §6.6 chain -- the
document that establishes what is in a lot and that its value is traceable. The
upload machinery has always worked and had never been used: GAPS.md §33 found 0 of
14 lots carrying one, including the Wellington CRMs every calibration standard on
this instance descends from, and §36 now prints "no CoA on file" on every
manufacturer node of every Certificate of Preparation because of it.

These are EXAMPLES, for exercising and reviewing that machinery. Every page says
so, in the title, in a banner, in a watermark and in the footer, and every
document carries SPECIMEN-* identifiers and a "not valid for compliance purposes"
statement.

THAT MARKING IS NOT DECORATION. A fabricated manufacturer CoA is precisely the
record that does damage if it is later mistaken for genuine -- it would assert
traceability to a reference value that nobody ever measured, which is the one
thing this subsystem exists to prevent. CLAUDE.md §8 says to flag placeholders,
never to fabricate a regulatory value. So the layout and the field coverage are
real (that is what makes them useful for review) and the CONTENT is unmistakably
not.

Replace each one with the supplier's actual PDF as it arrives; `_save_coa`
overwrites by reagent uid, so re-uploading a real CoA simply displaces the
specimen.

Idempotent: re-running replaces the specimens it wrote. Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
import sys
from datetime import date

SPECIMEN_BANNER = u"SPECIMEN — NOT A GENUINE CERTIFICATE OF ANALYSIS"

# Per-category test panels. A CoA's substance is its RESULTS table: what was
# measured, against what specification, by what method. These mirror the shape a
# supplier issues for each class of material so the review has something real to
# look at -- the numbers are illustrative and the documents say so.
PANELS = {
    u"Standard / Reference Material": [
        (u"Identity (LC-MS/MS, m/z confirmation)", u"Conforms", u"Conforms"),
        (u"Purity / assay (HPLC area %)", u"≥ 98.0 %", u"99.2 %"),
        (u"Gravimetric concentration", u"± 2.0 % of nominal", u"+0.6 %"),
        (u"Solvent (headspace GC)", u"Methanol, ≥ 99.9 %", u"99.96 %"),
        (u"Isotopic enrichment", u"≥ 99 atom % ¹³C", u"99.4 %"),
        (u"Homogeneity (n=10 ampoules)", u"RSD ≤ 2.0 %", u"0.8 %"),
    ],
    u"Internal Standard": [
        (u"Identity (LC-MS/MS, m/z confirmation)", u"Conforms", u"Conforms"),
        (u"Isotopic purity", u"≥ 99 atom %", u"99.5 %"),
        (u"Chemical purity (HPLC)", u"≥ 98.0 %", u"98.9 %"),
        (u"Unlabelled analogue", u"≤ 1.0 %", u"0.2 %"),
        (u"Gravimetric concentration", u"± 2.0 % of nominal", u"-0.4 %"),
    ],
    u"Mobile Phase / Solvent": [
        (u"Assay (GC)", u"≥ 99.9 %", u"99.95 %"),
        (u"Water content (Karl Fischer)", u"≤ 0.02 %", u"0.008 %"),
        (u"PFAS background (LC-MS/MS)", u"< 0.5 ng/L each analyte", u"Not detected"),
        (u"Non-volatile residue", u"≤ 1 mg/L", u"0.3 mg/L"),
        (u"UV absorbance @ 254 nm", u"≤ 0.01 AU", u"0.004 AU"),
    ],
    u"Buffer": [
        (u"Assay (titration)", u"98.0 – 102.0 %", u"99.7 %"),
        (u"pH (1 % solution, 25 °C)", u"6.8 – 7.2", u"7.02"),
        (u"PFAS background (LC-MS/MS)", u"< 0.5 ng/L each analyte", u"Not detected"),
        (u"Insoluble matter", u"≤ 0.005 %", u"0.001 %"),
    ],
    u"Acid / Base": [
        (u"Assay (titration)", u"≥ 99.0 %", u"99.4 %"),
        (u"PFAS background (LC-MS/MS)", u"< 0.5 ng/L each analyte", u"Not detected"),
        (u"Trace metals", u"≤ 10 ppb total", u"3 ppb"),
    ],
    u"Salt": [
        (u"Assay (titration, dried basis)", u"≥ 99.0 %", u"99.6 %"),
        (u"Loss on drying", u"≤ 0.5 %", u"0.11 %"),
        (u"PFAS background (LC-MS/MS)", u"< 0.5 ng/L each analyte", u"Not detected"),
        (u"Insoluble matter", u"≤ 0.005 %", u"0.002 %"),
    ],
    u"Extraction Reagent": [
        (u"Identity / conformance", u"Conforms to specification", u"Conforms"),
        (u"PFAS background (LC-MS/MS)", u"< 0.5 ng/L each analyte", u"Not detected"),
        (u"Recovery check (spiked matrix)", u"85 – 115 %", u"97 %"),
    ],
}
DEFAULT_PANEL = [
    (u"Identity / conformance", u"Conforms to specification", u"Conforms"),
    (u"PFAS background (LC-MS/MS)", u"< 0.5 ng/L each analyte", u"Not detected"),
]

# Illustrative accreditation lines per supplier. Real CoAs name the supplier's own
# accreditation; these are labelled illustrative for the same reason as everything
# else on the page.
ACCREDITATION = {
    u"Wellington Laboratories": u"ISO/IEC 17034 reference material producer "
                                u"(illustrative)",
    u"Fisher Scientific":       u"ISO 9001 manufacturing (illustrative)",
    u"Sigma-Aldrich":           u"ISO 9001 / ISO 17034 (illustrative)",
}


def _rows(panel):
    out = u""
    for name, spec, result in panel:
        out += (u"<tr><td>{0}</td><td>{1}</td><td><strong>{2}</strong></td>"
                u"<td>Pass</td></tr>").format(name, spec, result)
    return out


def _coa_html(rec, issue_date):
    """A specimen CoA for one reagent lot.

    Field coverage follows what a supplier's certificate carries and what
    ISO 17025 §6.6 needs from it to be usable as level-1 provenance: unambiguous
    identification of the material and the LOT, the specification tested against,
    the measured result, the method, storage and expiry, traceability of the
    assigned value, and an identified authorising signatory with an issue date.
    All dates ISO 8601.
    """
    supplier = rec.get("supplier") or u"—"
    category = rec.get("category") or u""
    panel = PANELS.get(category, DEFAULT_PANEL)
    lot = rec.get("lot_number") or u"—"
    expiry = (rec.get("expiry_date") or rec.get("manufacturer_expiry") or u"—")
    return u"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>{banner} — {name} lot {lot}</title>
<style>
  body {{ font-family: Arial, Helvetica, sans-serif; font-size: 12px; color:#222;
          margin: 28px 36px; position: relative; }}
  .wm {{ position: fixed; top: 42%; left: 50%;
         transform: translate(-50%,-50%) rotate(-28deg);
         font-size: 58px; font-weight: bold; color: rgba(190,30,30,0.13);
         letter-spacing: 3px; z-index: 0; pointer-events: none; }}
  .content {{ position: relative; z-index: 1; }}
  .alert {{ border: 2px solid #b91c1c; background:#fef2f2; color:#7f1d1d;
            padding: 8px 12px; font-weight: bold; margin-bottom: 14px;
            text-align:center; }}
  h1 {{ font-size: 17px; margin: 0 0 2px 0; }}
  .sub {{ color:#555; margin-bottom: 14px; }}
  dl {{ display:grid; grid-template-columns: 1fr 1fr; gap: 4px 20px;
        background:#f4f6f8; padding:12px 16px; border-radius:6px; margin:0 0 16px 0; }}
  dl div {{ display:flex; justify-content:space-between; border-bottom:1px solid #e3e7ea;
            padding:3px 0; }}
  dt {{ color:#555; }} dd {{ margin:0; font-weight:bold; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:16px; }}
  th,td {{ border:1px solid #ccd2d8; padding:5px 7px; text-align:left; }}
  th {{ background:#eef1f4; }}
  .sig {{ margin-top: 22px; border-top:1px solid #ccd2d8; padding-top:10px; }}
  .ln {{ display:inline-block; min-width:210px; border-bottom:1px solid #444; }}
  .foot {{ margin-top:18px; color:#7f1d1d; font-size:10px; border-top:1px solid #e3e7ea;
           padding-top:8px; }}
</style></head>
<body>
<div class="wm">SPECIMEN</div>
<div class="content">
<div class="alert">{banner}<br>
Illustrative content for system review. NOT valid for compliance purposes.
Replace with the supplier's issued certificate.</div>

<h1>Certificate of Analysis <span style="font-weight:normal">(specimen)</span></h1>
<p class="sub">{supplier} &mdash; {accreditation}</p>

<dl>
  <div><dt>Product</dt><dd>{name}</dd></div>
  <div><dt>Catalogue number</dt><dd>{cat}</dd></div>
  <div><dt>Lot / batch number</dt><dd>{lot}</dd></div>
  <div><dt>Certificate number</dt><dd>SPECIMEN-{lot}</dd></div>
  <div><dt>Material category</dt><dd>{category}</dd></div>
  <div><dt>Quantity per unit</dt><dd>{qty} {unit}</dd></div>
  <div><dt>Date of issue</dt><dd>{issue_date}</dd></div>
  <div><dt>Expiry / retest date</dt><dd>{expiry}</dd></div>
  <div><dt>Storage condition</dt><dd>{storage}</dd></div>
  <div><dt>Date format</dt><dd>ISO 8601 (YYYY-MM-DD)</dd></div>
</dl>

<h2 style="font-size:13px;margin-bottom:6px">Test results</h2>
<table>
  <thead><tr><th>Test</th><th>Specification</th><th>Result</th><th>Verdict</th></tr></thead>
  <tbody>{rows}</tbody>
</table>

<h2 style="font-size:13px;margin-bottom:6px">Traceability of the assigned value</h2>
<p style="margin-top:0">The assigned value is stated as gravimetrically prepared and
verified against a reference standard of stated traceability. On a genuine
certificate this section names the reference used, its certificate number and the
national metrology institute the value is traceable to (for example NIST SRM), with
the associated measurement uncertainty and coverage factor. <strong>This specimen
asserts no such traceability.</strong></p>

<h2 style="font-size:13px;margin-bottom:6px">Measurement uncertainty</h2>
<p style="margin-top:0">Stated on a genuine certificate as an expanded uncertainty
with its coverage factor (typically k=2, ~95 % confidence). Not asserted here.</p>

<div class="sig">
  <strong>Authorised by</strong> (specimen &mdash; not a real signatory)<br>
  <table style="border:none;margin-top:8px">
    <tr style="border:none">
      <td style="border:none;padding-left:0">Name / title</td>
      <td style="border:none">Quality Manager, {supplier}</td>
      <td style="border:none">Signature <span class="ln">&nbsp;</span></td>
      <td style="border:none">Date {issue_date}</td>
    </tr>
  </table>
</div>

<div class="foot">
  SPECIMEN DOCUMENT generated by senaite.pfas scripts/seed_example_coas.py on
  {issue_date}. Contains illustrative values only and establishes no traceability.
  It exists so the certificate and traceability machinery can be reviewed against
  a realistic layout. Do not rely on it, cite it, or present it as a
  manufacturer's certificate. Replace it with the supplier's issued CoA.
</div>
</div></body></html>""".format(
        banner=SPECIMEN_BANNER,
        supplier=supplier,
        accreditation=ACCREDITATION.get(supplier, u"accreditation not stated "
                                                  u"(illustrative)"),
        name=rec.get("name") or u"—",
        cat=rec.get("cat_number") or u"(not recorded)",
        lot=lot,
        category=category or u"(not recorded)",
        qty=rec.get("quantity") or u"—",
        unit=rec.get("unit") or u"",
        issue_date=issue_date,
        expiry=expiry,
        storage=rec.get("storage_location") or u"(not recorded)",
        rows=_rows(panel),
    )


def run():
    app_obj = globals().get("app")
    if app_obj is None:
        import Zope2
        from Testing.makerequest import makerequest
        app_obj = makerequest(Zope2.app())
    portals = [o for o in app_obj.objectValues("Plone Site")]
    if not portals:
        print("ERROR: no Plone site found.")
        sys.exit(1)
    portal = portals[0]

    from zope.component.hooks import setSite
    setSite(portal)
    from senaite.pfas.browser.reagents import _list_reagents, _save_coa

    issue_date = date.today().strftime("%Y-%m-%d")
    written = skipped = 0
    for rec in _list_reagents(portal):
        uid = rec.get("uid")
        lot = rec.get("lot_number") or u"?"
        if not uid:
            print("  SKIP %s — no uid" % lot)
            skipped += 1
            continue
        html = _coa_html(rec, issue_date)
        ok = _save_coa(portal, uid,
                       html.encode("utf-8") if isinstance(html, bytes) is False
                       else html,
                       "SPECIMEN-CoA-%s.html" % lot, "text/html",
                       "seed_example_coas (SPECIMEN)")
        print("  %-7s %-22s %s" % ("WROTE" if ok else "FAILED", lot,
                                   rec.get("name") or u""))
        written += 1 if ok else 0

    try:
        import transaction
        transaction.commit()
        print("Committed. %d specimen CoA(s) attached, %d skipped." % (written,
                                                                      skipped))
    except Exception as exc:
        print("ERROR committing: %s" % exc)
        sys.exit(1)


if __name__ == "__main__" or "app" in globals():
    run()
