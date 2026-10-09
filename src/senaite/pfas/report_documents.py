# -*- coding: utf-8 -*-
"""Designed reports: the extraction log, the QC Review report and the
settings report.

Each report keeps its own assembly -- extraction_logbook.logbook_data(), the
QC Review view's sections (which delegate to Data Review), the settings
report's report() -- and this module only FLATTENS that into the fields and
tables of a document kind (document_templates.KINDS). A report's nested or
pivoted parts become long tables, since a designed table has fixed columns:
the extraction's per-stage materials one "materials" table with a stage
column, the QC summary one row per analyte x QC type, a method's settings
sections one row per setting.

Every table is required in a design: these are records an assessor reads,
and a layout must not quietly drop a part of one (the settings report's
"judged by the pipeline" claims are pinned to the pipeline code by
tests/test_settings_report.py; a design cannot leave them out).

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import doc_fields as _df
except ImportError:                                         # loaded by path (tests)
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import doc_fields as _df


def _s(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return "%s" % v


def _cols(*specs):
    return [(k, t, e) for k, t, e in specs]


# ── extraction log (FM-ENV-003, @@pfas-extraction-pdf) ─────────────────────

EXTRACTION_FIELDS = [
    ("batch_id", "Batch ID", "B-DEMO"),
    ("batch_title", "Batch title", "DEMO batch"),
    ("method", "Method", "EPA 537.1"),
    ("lead_analyst", "Lead analyst", "AN1"),
    ("started", "Started", "2026-10-01 09:00"),
    ("finalized", "Finalized", "2026-10-01 15:00"),
    ("reviewer", "Reviewing analyst", "AN2"),
    ("generated", "PDF generated", "2026-10-05 10:00 UTC"),
    ("warnings", "What needed a note", "DEMO: balance not registered"),
    ("deviations", "Deviations", "DEMO deviation note"),
    ("pedigree", "Spike pedigree (older records)", ""),
]
# the laboratory and its signatories: the extraction analyst
# prepares, the reviewing analyst reviews, the Director of Site Settings
_SIGNED = _df.LAB_FIELDS + [f for _c, fs in _df.people() for f in fs]
SIGNED_IMAGES = _df.LAB_IMAGES + _df.people_images()


def _plus_signed(fields):
    have = set(k for k, _t, _e in fields)
    return fields + [f for f in _SIGNED if f[0] not in have]


# the starting layout keeps the record's own fields; the laboratory and
# signatory fields are offered in the designer (not required)
EXTRACTION_OWN = EXTRACTION_FIELDS
EXTRACTION_FIELDS = _plus_signed(EXTRACTION_FIELDS)


def _assign(base, extra=None):
    out = dict((k, c) for c, fs in [(_df.LAB, _df.LAB_FIELDS)] + _df.people() for k, _t, _e in fs)
    out.update(base)
    out.update(extra or {})
    return out


EXTRACTION_GROUPS = _df.grouped(EXTRACTION_FIELDS, _assign({
    "batch_id": _df.BATCH, "batch_title": _df.BATCH, "method": _df.ANALYSIS,
    "lead_analyst": _df.PREPARER, "started": _df.PREPARER,
    "reviewer": _df.REVIEWER, "finalized": _df.REVIEWER,
    "generated": _df.DOCUMENT, "warnings": _df.DEVIATIONS, "deviations": _df.DEVIATIONS,
    "pedigree": _df.TRACE}))

EXTRACTION_TABLES = {
    "extracted": _cols(("name", "Name", "DEMO-0001"), ("role", "Role", "Sample"),
                       ("made_from", "Made from", ""), ("matrix", "Matrix", "Drinking Water"),
                       ("amount", "Amount", "250 mL"), ("final_volume", "Final volume", "1 mL"),
                       ("spe_port", "SPE port", "A1")),
    "stages": _cols(("order", "Stage", "1"), ("name", "Name", "Sample prep"),
                    ("completed", "Completed", "2026-10-01 10:00"), ("analyst", "Analyst", "AN1"),
                    ("deviations", "Deviations", "—")),
    "materials": _cols(("stage", "Stage", "1"), ("kind", "Kind", "Reagent"),
                       ("name", "Name", "Methanol"), ("lot", "Lot", "DEMO-LOT-1"),
                       ("supplier", "Supplier", "DEMO"), ("qty", "Quantity", "10 mL"),
                       ("conc", "Conc.", ""), ("expiry", "Expiry", "2027-01-01")),
    "equipment": _cols(("stage", "Stage", "1"), ("item", "Equipment", "Balance"),
                       ("serial", "Serial", "SN-DEMO")),
    "spikes": _cols(("sample", "Sample", "LFSM-1"), ("parent", "Parent sample", "DEMO-0001"),
                    ("lot", "Spike lot", "DEMO-PS-1"), ("volume_ul", "Volume (µL)", "50"),
                    ("ppt", "Level (ppt)", "10"), ("by", "Entered by", "AN1"),
                    ("at", "Entered at", "2026-10-01"), ("source", "Source", "review")),
}
EXTRACTION_ORDER = ("extracted", "stages", "materials", "equipment", "spikes")
EXTRACTION_REQUIRED = ("batch_id", "method", "lead_analyst", "finalized", "reviewer",
                       "warnings", "deviations")


def extraction_data(log):
    """From extraction_logbook.logbook_data()."""
    head = dict(log.get("header") or [])
    materials, equipment, warnings, deviations = [], [], [], []
    for d in log.get("details") or []:
        stage = (d.get("title") or "").replace("Stage ", "").split(":")[0]
        for kind, rows in (("Reagent", d.get("reagents")), ("Consumable", d.get("consumables"))):
            for r in rows or []:
                materials.append({"stage": stage, "kind": kind, "name": r[0], "lot": r[1],
                                  "supplier": r[2], "qty": r[3], "conc": "", "expiry": r[4]})
        for r in d.get("solutions") or []:
            materials.append({"stage": stage, "kind": "Solution prepared", "name": r[0], "lot": r[1],
                              "supplier": "", "qty": r[3], "conc": r[2], "expiry": r[4]})
        for item, serial in d.get("equipment") or []:
            equipment.append({"stage": stage, "item": item, "serial": serial})
        warnings += ["%s: %s" % (d.get("title"), w) for w in d.get("warnings") or []]
        if d.get("deviations"):
            deviations.append("%s: %s" % (d.get("title"), d["deviations"]))
    pedigree = []
    for p in log.get("pedigree") or []:
        for r in p.get("rows") or []:
            pedigree.append("%s: %s" % (p.get("name"), ", ".join(_s(c) for c in r)))
    return {
        "batch_id": _s(head.get("Batch ID")), "batch_title": _s(head.get("Batch Title")),
        "method": _s(head.get("Method")), "lead_analyst": _s(head.get("Lead Analyst")),
        "started": _s(head.get("Started")), "finalized": _s(head.get("Finalized")),
        "reviewer": _s(head.get("Reviewing Analyst")), "generated": _s(head.get("PDF Generated")),
        "warnings": "\n".join(warnings), "deviations": "\n".join(deviations),
        "pedigree": "\n".join(pedigree),
        "stages": [dict((k, _s(s.get(k))) for k in ("order", "name", "completed", "analyst", "deviations"))
                   for s in log.get("summary") or []],
        "materials": [dict((k, _s(v)) for k, v in m.items()) for m in materials],
        "equipment": [dict((k, _s(v)) for k, v in e.items()) for e in equipment],
        "extracted": [dict(zip(("name", "role", "made_from", "matrix", "amount", "final_volume",
                                "spe_port"), [_s(c) for c in r])) for r in log.get("extracted") or []],
        "spikes": [dict(zip(("sample", "parent", "lot", "volume_ul", "ppt", "by", "at", "source"),
                            [_s(c) for c in r])) for r in log.get("spikes") or []],
    }


# ── QC Review report (senaite.pfas:QCReviewReport.pt) ──────────────────────

QC_FIELDS = [
    ("lab_name", "Laboratory", "DEMO Laboratory"),
    ("worksheet", "Worksheet", "WS-DEMO"), ("batch", "Batch", "B-DEMO"),
    ("batch_title", "Batch title", "DEMO batch"), ("method", "Method", "EPA_537_1"),
    ("matrix", "Matrix", "Drinking Water"), ("analyst", "Analyst", "AN1"),
    ("run_dates", "Acquisition date(s)", "2026-10-03"), ("unit", "Reporting unit", "ng/L"),
    ("matrix_factor", "Matrix factor applied", "1"), ("state", "Worksheet state", "verified"),
    ("qc_overall", "QC summary", "32 analytes · QC types LFB, MB · overall PASS"),
    ("spike_pending", "Spike level not recorded", ""),
    ("unresolved", "Traceability gaps", ""),
    ("planned", "Planned injections", "24"), ("acquired", "Injections acquired", "24"),
    ("not_run", "Planned but not run", "—"), ("unplanned", "Run but not planned", "—"),
    ("stamp", "Controlled stamp", "Controlled documentation publication · DEMO-0001-R1 · uncontrolled when printed"),
]
QC_OWN = QC_FIELDS
QC_FIELDS = _plus_signed(QC_FIELDS)
QC_GROUPS = _df.grouped(QC_FIELDS, _assign({
    "worksheet": _df.BATCH, "batch": _df.BATCH, "batch_title": _df.BATCH,
    "method": _df.ANALYSIS, "matrix": _df.ANALYSIS, "run_dates": _df.ANALYSIS,
    "unit": _df.ANALYSIS, "matrix_factor": _df.ANALYSIS, "analyst": _df.PREPARER,
    "state": _df.BATCH, "qc_overall": _df.QC, "spike_pending": _df.QC,
    "unresolved": _df.TRACE, "planned": _df.BATCH, "acquired": _df.BATCH,
    "not_run": _df.BATCH, "unplanned": _df.BATCH, "stamp": _df.DOCUMENT}))

QC_TABLES = {
    "criteria": _cols(("criterion", "Criterion", "Calibration r² minimum"), ("value", "Value", "0.99"),
                      ("source", "Source", "Method Profile")),
    "gates": _cols(("gate", "Gate", "Chain of Custody"), ("type", "Type", "Manual"),
                   ("verdict", "Verdict", "PASS"), ("detail", "Detail", "signed AN1")),
    "calibrations": _cols(("analyte", "Analyte", "PFOA"), ("r2", "r²", "0.999100"),
                          ("minimum", "Minimum", "0.99"), ("verdict", "Verdict", "PASS")),
    "qc_summary": _cols(("analyte", "Analyte", "PFOA"), ("qc_type", "QC type", "LFB"),
                        ("status", "Status", "98%")),
    "spike_qc": _cols(("analyte", "Analyte", "PFOA"), ("qc_type", "QC type", "LFSM"),
                      ("status", "Status", "102%")),
    "traceability": _cols(("item", "Standard / reagent", "PDS-A"), ("lot", "Lot", "DEMO-PS-1"),
                          ("resolves", "Resolves to", "prepared standard, 2 parent lot(s)")),
    "results": _cols(("sample", "Sample", "DEMO-0001"), ("analyte", "Analyte", "PFOA"),
                     ("result", "Result", "4.2"), ("qualifier", "Qualifier", ""),
                     ("state", "State", "verified")),
    "publications": _cols(("sample", "Sample", "DEMO-0001"), ("report_id", "Report ID", "DEMO-0001-R1"),
                          ("issued", "Issued", "2026-10-05"), ("by", "By", "AN3"),
                          ("status", "Status", "issued"), ("reason", "Amendment reason", "—")),
    "deviations": _cols(("deviation", "Deviation", "DEMO deviation"), ("raised", "Raised", "2026-10-02"),
                        ("state", "State", "open")),
    "flagged": _cols(("qc_type", "QC type", "LFB"), ("injection", "Injection", "LFB-1"),
                     ("analyte", "Analyte", "PFOA"), ("result", "Result", "1.0"), ("rt", "RT", "5.1"),
                     ("ion_ratio", "Ion ratio", "1.2"), ("flag", "Flag", "RT")),
    "measurements": _cols(("qc_type", "QC type", "LFB"), ("injection", "Injection", "LFB-1"),
                          ("analyte", "Analyte", "PFOA"), ("role", "Role", "native"),
                          ("result", "Result", "1.0"), ("rt", "RT", "5.1"), ("rrt", "RRT", "1.00"),
                          ("ion_ratio", "Ion ratio", "1.2"), ("expected", "Expected", "1.1"),
                          ("sn", "S/N", "120"), ("is_area", "IS area", "1e5"),
                          ("qual", "Qual.", ""), ("flag", "Flag", "")),
}
QC_ORDER = ("criteria", "gates", "calibrations", "qc_summary", "spike_qc", "traceability",
            "results", "publications", "deviations", "flagged", "measurements")
QC_REQUIRED = ("lab_name", "worksheet", "batch", "method", "matrix", "analyst", "state", "qc_overall",
               "spike_pending", "unresolved", "planned", "acquired", "not_run", "unplanned", "stamp")

_VERDICT = {"pass": "PASS", "fail": "FAIL", "blocked": "NOT EVALUATED"}


def _pivot(section, types_key):
    out = []
    for row in section.get("rows") or []:
        for t in section.get(types_key) or []:
            cell = (row.get("cells") or {}).get(t)
            out.append({"analyte": _s(row.get("analyte")), "qc_type": _s(t),
                        "status": _s(cell.get("badge") or cell.get("status")) if cell else "—"})
    return out


def qc_review_data(s):
    """From the QC Review view's sections: {identity, criteria, gates,
    calibrations, qc_summary, spike_qc, traceability, run_vs_plan, final_data,
    publications, deviations, exceptions, injections, stamp}."""
    ident = s.get("identity") or {}
    qc = s.get("qc_summary") or {}
    sq = s.get("spike_qc") or {}
    tr = s.get("traceability") or {}
    rp = s.get("run_vs_plan") or {}
    if qc.get("error"):
        overall = "QC results unavailable: %s" % qc["error"]
    else:
        overall = "%d analytes · QC types %s · overall %s" % (
            len(qc.get("rows") or []), ", ".join(qc.get("qc_types") or []),
            "PASS" if qc.get("overall_pass") else "FAIL")
    gates = []
    for g in s.get("gates") or []:
        detail = _s(g.get("reason"))
        if g.get("checked_by"):
            detail = (detail + " " if detail else "") + "signed %s" % g["checked_by"]
            if g.get("checked_at"):
                detail += " at %s" % _s(g["checked_at"])[:16]
        gates.append({"gate": _s(g.get("label")), "type": "Automatic" if g.get("auto") else "Manual",
                      "verdict": _VERDICT.get(g.get("verdict") or "pending", "PENDING"), "detail": detail})
    trace = [{"item": _s(p.get("title") or p.get("field")), "lot": _s(p.get("lot")),
              "resolves": ("prepared standard, %d parent lot(s)" % len(p.get("parent_reagents") or [])
                           if p.get("found") else "NOT IN INVENTORY")}
             for p in tr.get("prepared_standards") or []]
    trace += [{"item": _s(r.get("name")), "lot": _s(r.get("lot")),
               "resolves": "reagent lot" if r.get("resolved") else "NOT IN INVENTORY"}
              for r in tr.get("direct_reagents") or []]

    def meas(r):
        return {"qc_type": _s(r.get("qc_type")), "injection": _s(r.get("injection_name")),
                "analyte": _s(r.get("analyte")), "role": _s(r.get("role")),
                "result": _s(r.get("calc_conc")), "rt": _s(r.get("rt")), "rrt": _s(r.get("rrt")),
                "ion_ratio": _s(r.get("ion_ratio_obs")), "expected": _s(r.get("ion_ratio_exp")),
                "sn": _s(r.get("sn")), "is_area": _s(r.get("is_area")),
                "qual": _s(r.get("conc_qualifier")), "flag": _s(r.get("flag"))}
    return {
        "lab_name": _s(s.get("lab_name")),
        "worksheet": _s(ident.get("worksheet")), "batch": _s(ident.get("batch")),
        "batch_title": _s(ident.get("batch_title")), "method": _s(ident.get("method")),
        "matrix": _s(ident.get("matrix")), "analyst": _s(ident.get("analyst")),
        "run_dates": ", ".join(ident.get("run_dates") or []) or "—",
        "unit": _s(ident.get("unit")), "matrix_factor": _s(ident.get("matrix_factor")),
        "state": _s(ident.get("state")), "qc_overall": overall,
        "spike_pending": (("Spike level not recorded for: %s. Recovery cannot be evaluated until it is entered."
                           % ", ".join(_s(p.get("injection")) for p in sq.get("pending_spikes")))
                          if sq.get("pending_spikes") else ""),
        "unresolved": (("%d lot(s) named in the logbooks are not in inventory — the chain from "
                        "result to certified standard is incomplete." % len(tr["unresolved"]))
                       if tr.get("unresolved") else ""),
        "planned": _s(len(rp.get("planned") or [])), "acquired": _s(len(rp.get("actual") or [])),
        "not_run": ", ".join(rp.get("not_run") or []) or "—",
        "unplanned": ", ".join(rp.get("unplanned") or []) or "—",
        "stamp": _s(s.get("stamp")),
        "criteria": [{"criterion": _s(c.get("criterion")), "value": _s(c.get("value")),
                      "source": _s(c.get("source"))} for c in s.get("criteria") or []],
        "gates": gates,
        "calibrations": [{"analyte": _s(c.get("analyte")),
                          "r2": "%.6f" % c["r2"] if c.get("r2") is not None else "—",
                          "minimum": _s(c.get("limit")), "verdict": "PASS" if c.get("passed") else "FAIL"}
                         for c in s.get("calibrations") or []],
        "qc_summary": [] if qc.get("error") else _pivot(qc, "qc_types"),
        "spike_qc": _pivot(sq, "types"),
        "traceability": trace,
        "results": [{"sample": _s(r.get("client_sample_id") or r.get("sample_id")),
                     "analyte": _s(r.get("analyte")), "result": _s(r.get("result")),
                     "qualifier": _s(r.get("qualifier")), "state": _s(r.get("review_state"))}
                    for r in s.get("final_data") or []],
        "publications": [{"sample": _s(p.get("sample")), "report_id": _s(p.get("report_id")),
                          "issued": _s(p.get("issued_at"))[:16], "by": _s(p.get("authorizer")),
                          "status": _s(p.get("status")),
                          "reason": _s(p.get("amendment_reason")) or ("REASON NOT RECORDED"
                                                                     if p.get("reason_missing") else "—")}
                         for p in s.get("publications") or []],
        "deviations": [{"deviation": _s(d.get("title") or d.get("description")),
                        "raised": _s(d.get("created")), "state": _s(d.get("state") or d.get("review_state"))}
                       for d in s.get("deviations") or []],
        "flagged": [dict((k, v) for k, v in meas(r).items()
                         if k in ("qc_type", "injection", "analyte", "result", "rt", "ion_ratio", "flag"))
                    for r in s.get("exceptions") or []],
        "measurements": [meas(r) for r in s.get("injections") or []],
    }


# ── settings report (@@pfas-settings-report) ───────────────────────────────

SETTINGS_FIELDS = [
    ("title", "Title", "QC Settings Report"), ("revision_label", "Revision", "DRAFT"),
    ("generated", "Generated", "2026-10-05 10:00"), ("user", "Generated by", "AN3"),
    ("fingerprint", "Configuration id", "abc123def4567890"),
    ("methods", "Methods", "EPA 537.1 (EPA_537_1): Drinking Water; 25 analytes; Revision 2"),
    ("unread_switches", "Switches the pipeline does not read", ""),
    ("stale", "Project specs out of date", ""),
]
SETTINGS_GROUPS = _df.grouped(SETTINGS_FIELDS, {
    "title": _df.DOCUMENT, "revision_label": _df.DOCUMENT, "generated": _df.DOCUMENT,
    "user": _df.PREPARER, "fingerprint": _df.DOCUMENT, "methods": _df.ANALYSIS,
    "unread_switches": _df.QC, "stale": _df.QC})

SETTINGS_TABLES = {
    "qc_application": _cols(("method", "Method", "EPA_537_1"), ("code", "QC type", "LFSM"),
                            ("criterion", "Criterion", "Recovery window per tier"),
                            ("enabled", "On for this method", "Yes"), ("evaluated", "Judged by the pipeline", "Yes"),
                            ("how", "How", "Each LFSM injection x analyte"),
                            ("tiers", "Tiers", "Tier 1: 70–130% (all; all; method profile)")),
    "instrument_checks": _cols(("method", "Method", "EPA_537_1"), ("check", "Check", "Calibration"),
                               ("criterion", "Criterion", "r² minimum"), ("switch", "Rule switch", "Calibration r² on"),
                               ("evaluated", "Judged by the pipeline", "Yes"), ("how", "How", "Per analyte")),
    "recovery_grid": _cols(("method", "Method", "EPA_537_1"), ("analytes", "Analytes", "Key analytes"),
                           ("matrix", "Matrix", "Drinking Water"), ("window", "Window", "70–130%")),
    "revisions": _cols(("method", "Method", "EPA_537_1"), ("rev", "Revision", "2"),
                       ("issued", "Issued", "2026-10-02"), ("by", "By", "AN3"), ("reason", "Reason", "")),
    "settings": _cols(("method", "Method", "EPA_537_1"), ("section", "Section", "Calibration & CCV"),
                      ("setting", "Setting", "r² minimum"), ("value", "Value", "0.99")),
    "limits": _cols(("program", "Program", "US EPA"), ("limit", "Limit", "PFOA"),
                    ("analytes", "Analytes", "PFOA"), ("matrices", "Matrices", "Drinking Water"),
                    ("value", "Value", "4 ng/L"), ("kind", "Kind", "MCL"), ("verified", "Verified", "No"),
                    ("citation", "Citation", "")),
    "projects": _cols(("project", "Project", "DEMO"), ("client", "Client", "DEMO"), ("qapp", "QAPP", ""),
                      ("status", "Status", "active"), ("method", "Method", "EPA_537_1"),
                      ("scopes", "Specs for", "All matrices"),
                      ("departures", "Looser than the method", "")),
    "equipment_rules": _cols(("subject", "Applies to", "Balance"), ("rule", "Rule", "0.2 % of nominal")),
    "equipment_types": _cols(("type", "Type", "Balance"), ("kind", "Kind", "Balance"),
                             ("every", "Check every", "90 days"), ("correction", "Correction factor", "No"),
                             ("external", "External certificate", "Yes"), ("unit", "Unit", "g"),
                             ("tolerance", "Tolerance", "0.2 %"), ("worksheets", "In worksheets", "No")),
    "instruments": _cols(("name", "Instrument", "Balance 1"), ("type", "Type", "Balance"),
                         ("location", "Location", "Lab"), ("internal", "Internal check", "2026-10-01"),
                         ("external", "External certificate", "not required"),
                         ("correction", "Correction factor", ""), ("status", "Status", "OK")),
    "facility_defaults": _cols(("setting", "Setting", "Type 1 water, maximum TOC (ppb)"), ("value", "Value", "50")),
    "lab_settings": _cols(("setting", "Setting", "Laboratory name on reports"), ("value", "Value", "DEMO Lab")),
}
SETTINGS_ORDER = ("qc_application", "instrument_checks", "recovery_grid", "revisions", "settings",
                  "limits", "projects", "equipment_rules", "equipment_types", "instruments",
                  "facility_defaults", "lab_settings")
SETTINGS_REQUIRED = ("title", "revision_label", "generated", "user", "fingerprint", "methods",
                     "unread_switches", "stale")


def settings_data(report):
    """From PFASSettingsReportView.report()."""
    methods, unread, stale = [], [], []
    qc, inst, grid, revs, settings = [], [], [], [], []
    for m in report.get("methods") or []:
        mid = _s(m.get("method_id"))
        rv = m.get("revision") or {}
        methods.append("%s (%s): %s; %s analytes; %s" % (
            _s(m.get("name")), mid, ", ".join(m.get("matrices") or []) or "none", _s(m.get("panel")),
            ("Revision %s, issued %s by %s%s" % (rv["rev"], _s(rv.get("issued_at")), _s(rv.get("issued_by")),
                                                 "; settings changed since" if rv.get("unissued") else ""))
            if rv.get("rev") else "No revision issued yet"))
        unread += ["%s: %s" % (mid, sw.get("label") or sw.get("key"))
                   for sw in m.get("switches") or [] if not sw.get("read")]
        for q in m.get("qc") or []:
            qc.append({"method": mid, "code": _s(q.get("code")), "criterion": _s(q.get("criterion")),
                       "enabled": _s(bool(q.get("enabled"))), "evaluated": _s(bool(q.get("evaluated"))),
                       "how": _s(q.get("how")),
                       "tiers": "; ".join("%s: %s (%s; %s)" % (_s(t.get("name")), _s(t.get("criterion")),
                                                              _s(t.get("applies")), _s(t.get("source")))
                                          for t in q.get("tiers") or [])})
        for c in m.get("instrument") or []:
            inst.append({"method": mid, "check": _s(c.get("check")), "criterion": _s(c.get("criterion")),
                         "switch": "%s %s" % (_s(c.get("switch_label") or c.get("switch")), "on" if c.get("on") else "off"),
                         "evaluated": _s(bool(c.get("evaluated"))), "how": _s(c.get("how"))})
        g = m.get("grid") or {}
        for row in g.get("rows") or []:
            for mx, cell in zip(g.get("matrices") or [], row.get("cells") or []):
                window = _s(cell.get("text"))
                if cell.get("tier"):
                    window += " (%s)" % cell["tier"]
                if cell.get("low"):
                    window += " low level %s" % cell["low"]
                grid.append({"method": mid, "analytes": _s(row.get("title")), "matrix": _s(mx), "window": window})
        for r in m.get("revisions") or []:
            revs.append({"method": mid, "rev": _s(r.get("rev")), "issued": _s(r.get("issued_at")),
                         "by": _s(r.get("issued_by")), "reason": _s(r.get("reason"))})
        for sec in m.get("sections") or []:
            cols = sec.get("columns") or []
            for row in sec.get("rows") or []:
                rest = ["%s: %s" % (c, v) for c, v in zip(cols[1:], row[1:]) if _s(v)]
                settings.append({"method": mid, "section": _s(sec.get("title")),
                                 "setting": _s(row[0] if row else ""),
                                 "value": rest[0].split(": ", 1)[1] if len(rest) == 1 and len(cols) == 2
                                 else "; ".join(rest)})
    programs = report.get("programs") or {}
    limits = [{"program": _s((programs.get(l.get("program")) or {}).get("name") or l.get("program")),
               "limit": _s(l.get("label")), "analytes": ", ".join(l.get("analytes") or []),
               "matrices": ", ".join(l.get("matrices") or []) or "none assigned",
               "value": "%s %s" % (_s(l.get("value")), _s(l.get("unit"))), "kind": _s(l.get("kind")),
               "verified": _s(bool(l.get("verified"))), "citation": _s(l.get("citation"))}
              for l in report.get("limits") or []]
    projects = []
    for pj in report.get("projects") or []:
        base = {"project": "%s — %s" % (_s(pj.get("code")), _s(pj.get("title"))),
                "client": _s(pj.get("client")), "qapp": _s(pj.get("qapp")) or "none (internal quality system)",
                "status": _s(pj.get("status"))}
        if not pj.get("methods"):
            projects.append(dict(base, method="", scopes="", departures="No specs: linked batches run to the method."))
        for pm in pj.get("methods") or []:
            stale += ["%s %s: %s" % (_s(pj.get("code")), _s(pm.get("method_id")), _s(x)) for x in pm.get("stale") or []]
            projects.append(dict(base, method=_s(pm.get("method_id")), scopes=", ".join(pm.get("scopes") or []),
                                 departures="; ".join("%s %s → %s (%s; published %s)" % (
                                     _s(d.get("what")), _s(d.get("method")), _s(d.get("project")),
                                     _s(d.get("where")), _s(d.get("published")))
                                     for d in pm.get("departures") or [])))
    eq = report.get("equipment") or {}
    return {
        "title": _s(report.get("title")), "revision_label": _s(report.get("revision_label")),
        "generated": _s(report.get("generated")), "user": _s(report.get("user")),
        "fingerprint": _s(report.get("fingerprint")), "methods": "\n".join(methods),
        "unread_switches": ", ".join(unread), "stale": "\n".join(stale),
        "qc_application": qc, "instrument_checks": inst, "recovery_grid": grid, "revisions": revs,
        "settings": settings, "limits": limits, "projects": projects,
        "equipment_rules": [{"subject": _s(a[0]), "rule": _s(a[1])} for a in eq.get("application") or []],
        "equipment_types": [{"type": _s(t.get("title")) + ("" if t.get("configured") else " (not set up)"),
                             "kind": _s(t.get("kind")), "every": _s(t.get("every")),
                             "correction": _s(t.get("correction")), "external": _s(t.get("external")),
                             "unit": _s(t.get("unit")), "tolerance": _s(t.get("tolerance")),
                             "worksheets": _s(t.get("worksheets"))} for t in eq.get("types") or []],
        "instruments": [{"name": _s(i.get("name")) + (" (SN %s)" % i["serial"] if i.get("serial") else "")
                         + ("" if i.get("active", True) else " (inactive)"),
                         "type": _s(i.get("type")), "location": _s(i.get("location")),
                         "internal": _s(i.get("internal")), "external": _s(i.get("external")),
                         "correction": _s(i.get("correction")), "status": _s(i.get("status"))}
                        for i in eq.get("instruments") or []],
        "facility_defaults": [{"setting": _s(k), "value": _s(v)} for k, v in eq.get("defaults") or []],
        "lab_settings": [{"setting": _s(k), "value": _s(v)} for k, v in report.get("lab") or []],
    }


# ── a starting layout for any report ───────────────────────────────────────

def starter(title, fields, tables, order, long_fields=(), width=210.0, height=297.0):
    """Title and the identity fields on every page, then each paragraph and
    each table under its heading, page numbers in the footer. Everything a
    design must show is placed; the lab rearranges it."""
    every = {"pfasEveryPage": True}
    wide = width - 20.0
    out = [dict(_text("doc_title", 10, 10, wide, 7, 13, readOnly=True, content=title), **every)]
    short = [f for f in fields if f[0] not in long_fields]
    y = 18.0
    for i, (key, label, _e) in enumerate(short):
        col, row = i % 2, i // 2
        x = 10 + col * (wide / 2.0)
        out.append(dict(_text("label_" + key, x, y + row * 5, 32, 4.5, 7, readOnly=True, content=label), **every))
        out.append(dict(_text(key, x + 33, y + row * 5, wide / 2.0 - 35, 4.5, 7), **every))
    top = y + ((len(short) + 1) // 2) * 5 + 4
    out.append(dict({"name": "header_rule", "type": "line", "position": {"x": 10, "y": top - 2},
                     "width": wide, "height": 0.3, "readOnly": True, "color": "#444444"}, **every))
    pages = [out]
    page = out
    y = top + 2

    def room(need):
        """Start the next page when this one is full (each page's content
        still grows and flows on its own)."""
        if y + need <= height - 20:
            return y, page
        nxt = []
        pages.append(nxt)
        return top + 2, nxt

    for key in long_fields:
        label = dict((k, t) for k, t, _e in fields).get(key, key)
        y, page = room(12)
        page.append(_text("label_" + key, 10, y, wide, 4.5, 8, readOnly=True, content=label))
        page.append(_text(key, 10, y + 5, wide, 5, 7.5, overflow="expand"))
        y += 12
    for name in order:
        cols = tables[name]
        y, page = room(22)
        page.append(_text("heading_" + name, 10, y, wide, 5, 9, readOnly=True,
                          content=name.replace("_", " ").capitalize()))
        page.append({"name": name, "type": "table", "position": {"x": 10, "y": y + 6}, "width": wide,
                    "height": 12, "showHead": True, "repeatHead": True,
                    "head": [t for _k, t, _e in cols],
                    "headWidthPercentages": [100.0 / len(cols)] * len(cols),
                    "pfasColumns": [k for k, _t, _e in cols], "content": "[]",
                    "tableStyles": {"borderColor": "#444444", "borderWidth": 0.2},
                    "headStyles": {"fontSize": 6.5, "fontColor": "#222222", "backgroundColor": "",
                                   "borderColor": "#444444",
                                   "borderWidth": {"top": 0.3, "right": 0, "bottom": 0.3, "left": 0},
                                   "padding": {"top": 1, "right": 1, "bottom": 1, "left": 1}},
                    "bodyStyles": {"fontSize": 6.5, "borderColor": "#dddddd", "alternateBackgroundColor": "",
                                   "borderWidth": {"top": 0, "right": 0, "bottom": 0.1, "left": 0},
                                   "padding": {"top": 0.8, "right": 1, "bottom": 0.8, "left": 1}}})
        y += 22
    out.append(dict(_text("pager", width - 60, height - 12, 50, 5, 7, "right", readOnly=True,
                          content="Page {currentPage} of {totalPages}"), **every))
    return {"basePdf": {"width": width, "height": height, "padding": [top + 2, 10, 18, 10]},
            "schemas": pages}


def _text(name, x, y, w, h, size=8, align="left", **kw):
    f = {"name": name, "type": "text", "position": {"x": x, "y": y}, "width": w, "height": h,
         "fontSize": size, "alignment": align, "content": ""}
    f.update(kw)
    return f
