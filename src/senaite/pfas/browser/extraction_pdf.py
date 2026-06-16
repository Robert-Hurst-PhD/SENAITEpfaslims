# -*- coding: utf-8 -*-
"""
PFAS Extraction Logbook PDF Generator (@@pfas-extraction-pdf).

Uses ReportLab to produce a multi-page ISO 17025-grade PDF logbook from
the extraction session stored in ZODB annotations on the Batch.

Python 2.7 compatible.  Requires: reportlab>=3.0,<3.4 (last Py2.7-supporting series).
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import StringIO
from datetime import datetime

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView

from senaite.pfas.browser.extraction_guide import _load_session
from senaite.pfas.method_profile_store import get_profile

logger = logging.getLogger("senaite.pfas.browser.extraction_pdf")

# ── Colours (RGB 0-1 for ReportLab) ──────────────────────────────────────────
_DARK  = (0.07, 0.07, 0.14)
_BLUE  = (0.10, 0.38, 0.64)
_GREEN = (0.16, 0.65, 0.27)
_RED   = (0.78, 0.16, 0.22)
_GREY  = (0.50, 0.50, 0.50)
_LGREY = (0.93, 0.93, 0.93)
_WHITE = (1.00, 1.00, 1.00)


def _rgb(t):
    try:
        from reportlab.lib.colors import Color
        return Color(*t)
    except ImportError:
        return None


def _build_pdf(batch, session, profile):
    """Return a StringIO buffer containing the PDF bytes."""
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.units import inch
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph,
        Spacer, HRFlowable, PageBreak,
    )
    from reportlab.lib.colors import HexColor, Color

    buf = StringIO.StringIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=LETTER,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "pfas_title",
        parent=styles["Title"],
        fontSize=18,
        textColor=Color(*_DARK),
        spaceAfter=4,
    )
    h1_style = ParagraphStyle(
        "pfas_h1",
        parent=styles["Heading1"],
        fontSize=13,
        textColor=Color(*_BLUE),
        spaceBefore=14,
        spaceAfter=6,
    )
    h2_style = ParagraphStyle(
        "pfas_h2",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=Color(*_DARK),
        spaceBefore=10,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "pfas_body",
        parent=styles["Normal"],
        fontSize=9,
        leading=13,
        textColor=Color(*_DARK),
    )
    small_style = ParagraphStyle(
        "pfas_small",
        parent=styles["Normal"],
        fontSize=8,
        textColor=Color(*_GREY),
    )
    red_style = ParagraphStyle(
        "pfas_red",
        parent=styles["Normal"],
        fontSize=9,
        textColor=Color(*_RED),
    )

    tbl_hdr = TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), Color(*_BLUE)),
        ("TEXTCOLOR",   (0, 0), (-1, 0), Color(*_WHITE)),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, 0), 9),
        ("ALIGN",       (0, 0), (-1, -1), "LEFT"),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [Color(*_WHITE), Color(*_LGREY)]),
        ("FONTSIZE",    (0, 1), (-1, -1), 8),
        ("FONTNAME",    (0, 1), (-1, -1), "Helvetica"),
        ("GRID",        (0, 0), (-1, -1), 0.3, Color(*_GREY)),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
    ])

    # ── Helper to make a 2-col info table ────────────────────────────────────
    def info_table(rows):
        data = [[Paragraph("<b>"+k+"</b>", body_style), Paragraph(unicode(v), body_style)]
                for k, v in rows]
        t = Table(data, colWidths=[1.6*inch, 5.6*inch])
        t.setStyle(TableStyle([
            ("ALIGN",       (0, 0), (-1, -1), "LEFT"),
            ("VALIGN",      (0, 0), (-1, -1), "TOP"),
            ("FONTSIZE",    (0, 0), (-1, -1), 9),
            ("GRID",        (0, 0), (-1, -1), 0.2, Color(*_LGREY)),
            ("ROWBACKGROUNDS", (0, 0), (-1, -1), [Color(*_WHITE), Color(0.96, 0.96, 0.99)]),
            ("TOPPADDING",  (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ]))
        return t

    # ── Helpers ───────────────────────────────────────────────────────────────
    def para(text, style=None):
        return Paragraph(unicode(text) if text else u"—", style or body_style)

    def sp(h=0.1):
        return Spacer(1, h * inch)

    def hr():
        return HRFlowable(width="100%", thickness=0.5, color=Color(*_GREY), spaceAfter=6)

    def _fmt(val):
        if val is None:
            return u"—"
        return unicode(val) if val else u"—"

    # ── Story ─────────────────────────────────────────────────────────────────
    story = []
    method_name = profile.get("display_name", session.get("method_id", ""))
    batch_id = batch.getId() if hasattr(batch, "getId") else "N/A"
    batch_title = batch.Title() if hasattr(batch, "Title") else "N/A"
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # ── Cover header ─────────────────────────────────────────────────────────
    story.append(para("PFAS Extraction Logbook", title_style))
    story.append(para(method_name, h1_style))
    story.append(hr())
    story.append(info_table([
        ("Batch ID",         batch_id),
        ("Batch Title",      batch_title),
        ("Method",           method_name),
        ("Lead Analyst",     _fmt(session.get("analyst"))),
        ("Started",          _fmt(session.get("started_at"))),
        ("Finalized",        _fmt(session.get("finalized_at"))),
        ("Reviewing Analyst", _fmt(session.get("finalized_by"))),
        ("PDF Generated",    now),
    ]))
    story.append(sp(0.3))

    # ── Stage completion summary ──────────────────────────────────────────────
    story.append(para("Extraction Stages", h1_style))
    stages_config = sorted(
        profile.get("extraction_stages", []),
        key=lambda s: s.get("order", 0)
    )
    completed = session.get("stages", {})
    tbl_data = [[
        Paragraph("<b>Stage</b>", body_style),
        Paragraph("<b>Name</b>", body_style),
        Paragraph("<b>Completed</b>", body_style),
        Paragraph("<b>Analyst</b>", body_style),
        Paragraph("<b>Deviations</b>", body_style),
    ]]
    for sc in stages_config:
        order = str(sc.get("order", ""))
        sd = completed.get(order, {})
        done = "YES" if sd else "pending"
        dev = sd.get("deviations", "") or u"—"
        tbl_data.append([
            Paragraph(order, body_style),
            Paragraph(sc.get("name", ""), body_style),
            Paragraph(sd.get("completed_at", u"—"), small_style),
            Paragraph(sd.get("analyst", u"—"), body_style),
            Paragraph(dev[:80], body_style),
        ])
    t = Table(tbl_data, colWidths=[0.4*inch, 2.0*inch, 1.5*inch, 1.2*inch, 2.15*inch])
    t.setStyle(tbl_hdr)
    story.append(t)
    story.append(sp(0.2))

    # ── Per-stage detail ──────────────────────────────────────────────────────
    for sc in stages_config:
        order = str(sc.get("order", ""))
        sd = completed.get(order)
        if not sd:
            continue
        story.append(para(
            "Stage {0}: {1}".format(sc.get("order", ""), sc.get("name", "")),
            h2_style
        ))

        # Equipment S/Ns
        eq_sns = sd.get("equipment_sns") or {}
        if eq_sns:
            eq_rows = [["Equipment", "Serial / Verification Number"]]
            for eq, sn in eq_sns.items():
                eq_rows.append([eq, sn or u"—"])
            t = Table(eq_rows, colWidths=[3*inch, 4.25*inch])
            t.setStyle(tbl_hdr)
            story.append(t)
            story.append(sp(0.1))

        # Reagents
        reagents = sd.get("reagents") or []
        if reagents:
            story.append(para("Reagents Used:", body_style))
            rg_rows = [["Role / Name", "Lot #", "Expiry", "Qty Used", "Status"]]
            for r in reagents:
                exp_str = r.get("expiry", "") or u"—"
                status_str = r.get("new_status", "") or "OK"
                rg_rows.append([
                    r.get("role") or r.get("name") or u"—",
                    r.get("lot", "") or u"—",
                    exp_str,
                    r.get("qty_used", "") or u"—",
                    status_str,
                ])
            t = Table(rg_rows, colWidths=[2.3*inch, 1.4*inch, 0.9*inch, 0.8*inch, 1.85*inch])
            t.setStyle(tbl_hdr)
            story.append(t)
            story.append(sp(0.1))

        # Solutions prepared
        solutions = sd.get("solutions_prepared") or []
        if solutions:
            story.append(para("Solutions Prepared:", body_style))
            sol_rows = [["Name", "Lot #", "Concentration", "Volume (mL)", "Expiry"]]
            for s in solutions:
                sol_rows.append([
                    s.get("name", "") or u"—",
                    s.get("lot", "") or u"—",
                    s.get("conc", "") or u"—",
                    str(s.get("volume_ml", "") or u"—"),
                    s.get("expiry", "") or u"—",
                ])
            t = Table(sol_rows, colWidths=[2.0*inch, 1.5*inch, 1.5*inch, 1.0*inch, 1.25*inch])
            t.setStyle(tbl_hdr)
            story.append(t)
            story.append(sp(0.1))

        # Deviations
        dev = sd.get("deviations", "")
        if dev:
            story.append(para("<b>Deviations / Observations:</b>", body_style))
            story.append(para(dev, red_style))
            story.append(sp(0.05))

        story.append(hr())

    # ── Pedigree ──────────────────────────────────────────────────────────────
    pedigree = session.get("pedigree") or {}
    if pedigree:
        story.append(PageBreak())
        story.append(para("Standard Pedigree / Traceability", title_style))
        story.append(hr())
        for std_name, levels in sorted(pedigree.items()):
            story.append(para(std_name, h2_style))
            ped_rows = [["Level", "Lot #", "Conc (ng/mL)", "Supplier / Prep By", "Date", "CoA / Notes"]]
            for lvl in levels:
                is_crm = "CRM" in (lvl.get("level") or "")
                ped_rows.append([
                    lvl.get("level", "") or u"—",
                    lvl.get("lot", "") or u"—",
                    str(lvl.get("cert_conc") or lvl.get("conc") or u"—"),
                    lvl.get("supplier") or lvl.get("prepared_by") or u"—",
                    lvl.get("cert_date") or lvl.get("prepared_date") or u"—",
                    lvl.get("coa", "") or u"—",
                ])
            t = Table(ped_rows, colWidths=[1.4*inch, 1.2*inch, 1.0*inch, 1.5*inch, 0.9*inch, 1.25*inch])
            t.setStyle(tbl_hdr)
            story.append(t)
            story.append(sp(0.15))

    # ── Sign-off ──────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(para("Sign-Off and Authorisation", title_style))
    story.append(hr())
    story.append(info_table([
        ("Extraction Analyst", session.get("analyst", "") or u"—"),
        ("Reviewing Analyst",  session.get("finalized_by", "") or u"—"),
        ("Date Finalized",     session.get("finalized_at", "") or u"—"),
    ]))
    story.append(sp(0.5))
    sign_tbl = Table([
        [Paragraph("<b>Analyst Signature</b>", body_style), Paragraph("", body_style),
         Paragraph("<b>Reviewer Signature</b>", body_style), Paragraph("", body_style)],
        ["", "__________________________", "", "__________________________"],
        [Paragraph("<b>Date</b>", body_style), Paragraph("", body_style),
         Paragraph("<b>Date</b>", body_style), Paragraph("", body_style)],
        ["", "__________________________", "", "__________________________"],
    ], colWidths=[1.0*inch, 2.5*inch, 1.0*inch, 2.5*inch])
    sign_tbl.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "BOTTOM"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(sign_tbl)
    story.append(sp(0.3))
    story.append(para(
        "This document is generated by the PFAS LIMS. Retain with batch records "
        "in accordance with ISO 17025 and laboratory SOP.",
        small_style
    ))

    doc.build(story)
    buf.seek(0)
    return buf


# ── View ──────────────────────────────────────────────────────────────────────

class PFASExtractionPDFView(BrowserView):
    """Generate and serve the extraction logbook PDF via ReportLab."""

    def __call__(self):
        uid = self.request.form.get("batch_uid", "")
        if not uid:
            self.request.response.setStatus(400)
            return "batch_uid parameter required"

        catalog = getToolByName(self.context, "uid_catalog")
        brains = catalog(UID=uid)
        if not brains:
            self.request.response.setStatus(404)
            return "Batch not found"

        try:
            batch = brains[0].getObject()
        except Exception as exc:
            self.request.response.setStatus(500)
            return "Error loading batch: {0}".format(str(exc))

        session = _load_session(batch)
        if not session:
            self.request.response.setStatus(404)
            return "No extraction session found for this batch"

        method_id = session.get("method_id", "FDA_32PFAS")
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        profile = get_profile(portal, method_id)

        try:
            buf = _build_pdf(batch, session, profile)
        except ImportError:
            self.request.response.setStatus(500)
            return (
                "ReportLab is not installed in this environment. "
                "Add 'reportlab>=3.0,<3.4' to the SENAITE Docker image "
                "(pip install reportlab) and restart."
            )
        except Exception as exc:
            logger.exception("PDF generation failed")
            self.request.response.setStatus(500)
            return "PDF generation error: {0}".format(str(exc))

        batch_id = batch.getId() if hasattr(batch, "getId") else "extraction"
        filename = "pfas_extraction_{0}.pdf".format(batch_id)

        self.request.response.setHeader("Content-Type", "application/pdf")
        self.request.response.setHeader(
            "Content-Disposition",
            'attachment; filename="{0}"'.format(filename)
        )
        return buf.read()
