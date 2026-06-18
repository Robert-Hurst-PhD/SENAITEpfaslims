"""
Report Generator — replaces RunFullPDFPipeline / MergePDFsStable (Adobe COM).

Key change per your requirement: the PDF is no longer assembled from loose
files on S:\\PFAS — it is GENERATED FROM the extraction log + barcode scans
+ QC results captured during analysis.  Sections:

  1. Cover / batch summary
  2. Summary results table (Sheet 5 equivalent, with qualifiers)
  3. QC Log (Sheet 6 equivalent)
  4. Calibration & CCV table
  5. IS / Surrogate response table
  6. LFSM / LFSMD recovery table
  7. Digital extraction log (steps + reagent lots from barcode scans)
  8. Signature block (Analyst / Reviewer / Supervisor)

Bookmarks per section; signature rows match the VBA printWs layout.
Pure-Python: reportlab + pypdf — runs in the SENAITE Docker container.
"""

from __future__ import annotations
from datetime import datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

from .models import Batch
from .barcode import ExtractionLog


_styles = getSampleStyleSheet()
_H1 = ParagraphStyle("H1", parent=_styles["Heading1"], fontSize=16)
_H2 = ParagraphStyle("H2", parent=_styles["Heading2"], fontSize=12)
_BODY = _styles["BodyText"]

_GRID = TableStyle([
    ("FONTSIZE",   (0, 0), (-1, -1), 7),
    ("GRID",       (0, 0), (-1, -1), 0.4, colors.grey),
    ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.9, 0.9, 0.9)),
    ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
    ("VALIGN",     (0, 0), (-1, -1), "TOP"),
])


def _tbl(headers: list[str], rows: list[list], col_widths=None) -> Table:
    data = [headers] + [[str(c) for c in r] for r in rows]
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(_GRID)
    return t


def generate_batch_report(
    batch: Batch,
    extraction_log: ExtractionLog | None,
    output_path: str | Path,
) -> Path:
    """Build the complete batch report PDF."""
    output_path = Path(output_path)
    doc = SimpleDocTemplate(
        str(output_path), pagesize=letter,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title=f"PFAS Batch Report — {batch.batch_id}",
    )
    story = []

    # ── 1. Cover ──────────────────────────────────────────────────────────────
    story.append(Paragraph(f"PFAS Batch Report — {batch.batch_id}", _H1))
    story.append(Paragraph(
        f"Method: {batch.method_id or '—'} &nbsp;|&nbsp; Matrix: {batch.matrix} "
        f"&nbsp;|&nbsp; Analyst: {batch.analyst} "
        f"&nbsp;|&nbsp; Date: {batch.date:%Y-%m-%d} "
        f"&nbsp;|&nbsp; Instrument file: {batch.instrument_file}", _BODY))
    story.append(Spacer(1, 12))

    n_flags = len(batch.qc_flags)
    story.append(Paragraph(
        f"QC flags raised: <b>{n_flags}</b> &nbsp;|&nbsp; "
        f"Injections: <b>{len({r.concat_id for r in batch.injections})}</b>",
        _BODY))
    story.append(Spacer(1, 18))

    # ── 2. Summary results ────────────────────────────────────────────────────
    if batch.summary:
        story.append(Paragraph("Summary results", _H2))
        samples = sorted({s.sample_injection for s in batch.summary})
        analytes = sorted({s.analyte for s in batch.summary})
        lookup = {(s.analyte, s.sample_injection): s.display()
                  for s in batch.summary}
        rows = [[a] + [lookup.get((a, smp), "") for smp in samples]
                for a in analytes]
        story.append(_tbl(["Analyte"] + [s[:28] for s in samples], rows))
        story.append(PageBreak())

    # ── 3. QC Log ────────────────────────────────────────────────────────────
    story.append(Paragraph("QC log", _H2))
    if batch.qc_flags:
        story.append(_tbl(
            ["Source", "Analyte", "Injection", "Value", "Issue"],
            [[f.source, f.analyte, f.injection_name[:36], f.value, f.issue]
             for f in batch.qc_flags],
        ))
    else:
        story.append(Paragraph("No QC flags raised.", _BODY))
    story.append(Spacer(1, 14))

    # ── 4. Calibration ───────────────────────────────────────────────────────
    cal = [c for c in batch.cal_results if c.flag]
    story.append(Paragraph("Calibration exceptions", _H2))
    if cal:
        story.append(_tbl(
            ["Analyte", "Injection", "R²", "% Dev"],
            [[c.analyte, c.injection_name[:36],
              f"{c.r2:.4f}" if c.r2 else "—",
              f"{c.pct_deviation*100:+.1f}%" if c.pct_deviation is not None else "—"]
             for c in cal],
        ))
    else:
        story.append(Paragraph("All calibration points within criteria.", _BODY))
    story.append(Spacer(1, 14))

    # ── 5. IS / Surrogate exceptions ─────────────────────────────────────────
    is_ex = [r for r in batch.is_results if r.flag]
    story.append(Paragraph("Internal standard / surrogate exceptions", _H2))
    if is_ex:
        story.append(_tbl(
            ["IS Compound", "Injection", "Response ratio", "Batch avg"],
            [[r.is_compound, r.injection_name[:36],
              f"{(r.pct_from_cal or 0)*100:.0f}%",
              f"{r.average_response:.4g}" if r.average_response else "—"]
             for r in is_ex],
        ))
    else:
        story.append(Paragraph("All IS responses within ±50% of batch average.", _BODY))
    story.append(Spacer(1, 14))

    # ── 6. LFSM / LFSMD ──────────────────────────────────────────────────────
    story.append(Paragraph("LFSM / LFSMD recoveries", _H2))
    if batch.lfsm_results:
        story.append(_tbl(
            ["Analyte", "Recovery %", "Spike (ppt)", "Pass"],
            [[r.analyte, f"{r.recovery_pct:.1f}", r.spike_value_ppt,
              "✓" if r.passes else "✗ REC"]
             for r in batch.lfsm_results],
        ))
    if batch.lfsmd_results:
        story.append(Spacer(1, 8))
        story.append(_tbl(
            ["Analyte", "LFSM %", "LFSMD %", "RPD %", "Pass"],
            [[r.analyte, f"{r.recovery_lfsm:.1f}", f"{r.recovery_lfsmd:.1f}",
              f"{r.rpd_pct:.1f}", "✓" if r.passes else "✗ RPD"]
             for r in batch.lfsmd_results],
        ))
    story.append(PageBreak())

    # ── 7. Digital extraction log (from barcode scans) ───────────────────────
    story.append(Paragraph("Extraction log", _H2))
    if extraction_log:
        el = extraction_log.to_dict()
        story.append(Paragraph(
            f"Started {el['started']} — "
            f"Completed {el['completed'] or 'in progress'}", _BODY))
        if el["steps"]:
            story.append(Spacer(1, 6))
            story.append(_tbl(
                ["Time", "Step", "Detail", "Value", "By"],
                [[s["at"][11:19], s["step"], s["detail"], s["value"], s["by"]]
                 for s in el["steps"]],
            ))
        if el["reagent_scans"]:
            story.append(Spacer(1, 10))
            story.append(Paragraph("Reagents & standards used (barcode-scanned)", _H2))
            story.append(_tbl(
                ["Time", "Step", "Cat #", "Lot #", "Expiry", "New lot?"],
                [[s["at"][11:19], s.get("step", ""), s["catalog_number"],
                  s["lot_number"], s["expiry_date"][:10],
                  "NEW" if s["is_new_lot"] else ""]
                 for s in el["reagent_scans"]],
            ))
    else:
        story.append(Paragraph("No extraction log attached.", _BODY))
    story.append(Spacer(1, 30))

    # ── 8. Signature block (matches VBA printWs layout) ──────────────────────
    sig_rows = [
        ["Analyst Initials:", "____________", "Date:", "____________"],
        ["", "", "", ""],
        ["Reviewer Initials:", "____________", "Date:", "____________"],
        ["", "", "", ""],
        ["Supervisor Initials:", "____________", "Date:", "____________"],
    ]
    if extraction_log:
        for s in extraction_log.signoffs:
            for row in sig_rows:
                if row and row[0].lower().startswith(s["role"].lower()):
                    row[1] = s["initials"]
                    row[3] = s["at"][:10]
    sig = Table(sig_rows, colWidths=[1.6*inch, 1.6*inch, 0.8*inch, 1.6*inch])
    sig.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 11),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(sig)

    doc.build(story)
    return output_path


def merge_external_pdfs(main_report: Path, attachments: list[dict],
                        output_path: Path) -> Path:
    """
    MergePDFsStable replacement.  attachments = [{"path":…, "label":…}, …]
    (CoC, instrument raw report, checklist).  Adds bookmarks per document.
    """
    from pypdf import PdfWriter, PdfReader

    writer = PdfWriter()
    offset = 0

    docs = [{"path": main_report, "label": "Batch Report"}] + attachments
    for d in docs:
        reader = PdfReader(str(d["path"]))
        for page in reader.pages:
            writer.add_page(page)
        writer.add_outline_item(d["label"], offset)
        offset += len(reader.pages)

    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path
