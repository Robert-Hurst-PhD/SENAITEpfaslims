# -*- coding: utf-8 -*-
"""A designed certificate's data, from the certificate's own assembly.


The HTML certificate is drawn from PFASCoASectionsView (lab(), doc_meta(),
_sample()) and PFASCoAAttestationView (signatories, QC qualifications,
accreditation scope, the controlled stamp). A designed certificate takes the
SAME values: data(...) only flattens them into the fields and tables of the
"coa" kind (document_templates.KINDS). Where the HTML composes a sentence
(the legend, departures, the regulatory comparison), the words here are the
template's words; test_coa_document pins each sentence to coa_sections.pt /
CertificateOfAnalysis.pt so the two cannot drift apart.

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

try:
    from senaite.pfas import coa_qc_standards as _qcs
    from senaite.pfas import doc_fields as _df
except ImportError:                                         # loaded by path (tests)
    import os, sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import coa_qc_standards as _qcs
    import doc_fields as _df

# The data fields, grouped as the designer offers them under the shared
# categories (doc_fields; 2026-10-05: sample; analysis; laboratory; preparer / reviewer / director; plus quality control and document control).
# (key, title, example). Image fields (logo, signatures) are listed in IMAGES.
GROUPS = [
    (_df.SAMPLE, [
        ("sample_id", "Lab sample ID", "DEMO-0001"),
        ("client_sid", "Client sample ID", "DEMO-CS-01"),
        ("client", "Client", "DEMO Client"),
        ("contact", "Client contact", "DEMO Contact"),
        ("matrix", "Matrix", "Drinking Water"),
        ("batch", "Batch", "B-DEMO"),
        ("sampled", "Sampled", "2026-10-01 09:00"),
        ("received", "Received", "2026-10-02 10:00"),
    ]),
    (_df.ANALYSIS, [
        ("method", "Method", "EPA 537.1"),
        ("analysed", "Date of analysis", "2026-10-03 14:00"),
        ("units", "Units", "ng/L"),
        ("legend", "Legend (qualifiers, RL, MDL)", "U = not detected at or above the reporting limit (RL)."),
        ("note", "Standard note", "DEMO standard note"),
        ("regulatory", "MCL / action level comparison", "DEMO regulatory comparison"),
        ("interpretation", "Results interpretation", "DEMO results interpretation"),
        ("remarks", "Remarks", "DEMO remarks"),
    ]),
    (_df.QC, [
        ("qc_standards_note", "Surrogate / internal-standard note", _qcs.DEFAULT_NOTE),
        ("qc_qualifications", "QC qualifications", "DEMO QC qualifications"),
        ("departures", "Project departures", "DEMO departures"),
    ]),
    (_df.LAB, [
        ("lab_name", "Laboratory", "DEMO Laboratory"),
        ("lab_logo", "Logo", ""),
        ("lab_address", "Address", "1 Example Road, Example Town"),
        ("lab_phone", "Phone", "000-000-0000"),
        ("lab_email", "Email", "lab@example.org"),
        ("lab_contact", "Contact information (address, phone, email)", "1 Example Road · 000-000-0000"),
        ("lab_accreditation", "Accreditation status", "ISO/IEC 17025:2017"),
        ("qs_statement", "Quality system statement", "DEMO quality system statement"),
        ("accreditation", "Accreditation scope (this sample)", "DEMO accreditation scope"),
    ]),
    (_df.PREPARER, [
        ("preparer_name", "Preparer", "AN1"),
        ("preparer_title", "Preparer title", "Analyst"),
        ("preparer_credentials", "Preparer credentials", "B.Sc."),
        ("preparer_date", "Prepared on", "2026-10-03"),
        ("preparer_signature", "Preparer signature", ""),
        ("prepared_by", "Prepared by (everyone, with dates)", "AN1 2026-10-03"),
    ]),
    (_df.REVIEWER, [
        ("reviewer_name", "Reviewer", "AN2"),
        ("reviewer_title", "Reviewer title", "QA Officer"),
        ("reviewer_credentials", "Reviewer credentials", "M.Sc."),
        ("reviewer_date", "Reviewed on", "2026-10-04"),
        ("reviewer_signature", "Reviewer signature", ""),
        ("verified_by", "Verified by (everyone, with dates)", "AN2 2026-10-04"),
    ]),
    (_df.DIRECTOR, [
        ("director_name", "Laboratory Director", "AN3"),
        ("director_title", "Director title", "Director, DEMO Laboratory"),
        ("director_credentials", "Director credentials", "Ph.D."),
        ("director_signature", "Director signature", ""),
        ("authorized_by", "Authorized by (who published)", "AN3 2026-10-05"),
    ]),
    (_df.DOCUMENT, [
        ("report_id", "Report", "DEMO-0001-R1"),
        ("issued", "Issued", "2026-10-05"),
        ("template_rev", "Template revision", "1"),
        ("stamp", "Controlled stamp", "Controlled documentation publication · DEMO-0001-R1 · uncontrolled when printed"),
    ]),
]
FIELDS = [f for _g, fs in GROUPS for f in fs]

# Image fields: the value is a picture (PNG / JPEG data URI); the designer
# places them as images bound to the data.
IMAGES = ("lab_logo", "preparer_signature", "reviewer_signature", "director_signature")

# (column key, title, example). "analyte" is the REPORTED name (the
# abbreviation, e.g. PFOS; a summed analyte's reported label); "analyte_name"
# the full name, isomer-aware (isomers.full_name).
RESULT_COLUMNS = [
    ("analyte_name", "Analyte", "Perfluorooctanoic acid"),
    ("analyte", "Abbreviation", "PFOA"),
    ("cas", "CAS No.", "335-67-1"),
    ("analysis_date", "Date of analysis", "2026-10-03"),
    ("result", "Result", "4.2"),
    ("dil", "Dilution", "1"),
    ("qual", "Qualifier", "J"),
    ("unit", "Units", "ng/L"),
    ("rl", "RL", "2.0"),
    ("mdl", "MDL", "0.5"),
    ("action_level", "MCL / action level", "4 ng/L (US EPA MCL)"),
]
RESULT_COLUMN_GROUPS = [
    (_df.SAMPLE, ("analyte_name", "analyte", "cas")),
    (_df.ANALYSIS, ("analysis_date", "result", "dil", "qual", "unit", "rl", "mdl", "action_level")),
]

# the surrogate / internal-standard sub-table
QC_STANDARD_COLUMNS = _qcs.COLUMNS

# Results columns the method x matrix Reporting format may hide (as the HTML
# hides them); dropped from that sample's table when the format says so.
_FORMAT_COLUMNS = (("cas", "coa_show_cas"), ("mdl", "coa_show_mdl"), ("dil", "coa_show_dilution"))

# A designed certificate cannot be issued without these: everything today's
# certificate states, disclosures included (an empty one prints nothing), and
# the three signatories with their signatures.
REQUIRED_FIELDS = ("report_id", "issued", "lab_name", "sample_id", "client", "matrix",
                   "method", "legend", "note", "qc_standards_note", "qs_statement", "departures", "regulatory",
                   "accreditation", "qc_qualifications", "remarks", "interpretation", "prepared_by",
                   "verified_by", "authorized_by", "stamp",
                   "preparer_signature", "reviewer_signature", "director_name", "director_signature")
REQUIRED_COLUMNS = {"results": ("analyte", "result", "qual", "rl", "unit"),
                    "qc_standards": _qcs.REQUIRED}

# words copied from the templates (test_coa_document checks they are there)
QC_TITLE = "Surrogate and internal-standard quality control"
LEGEND_U = "U = not detected at or above the reporting limit (RL)."
LEGEND_MDL = "MDL = method detection limit."
LEGEND_CODES = "Other codes: see Quality control qualifications."
LEGEND_NO_RL = "No reporting limits are configured for this method and matrix."
DEPARTURES_A = "Quality control criteria for project"
DEPARTURES_B = "less stringent than the laboratory method:"
REG_TITLE = "Regulatory comparison"
REG_EXCEEDS = "meets or exceeds"
REG_UNDETERMINED = "not all contributing analytes were detected at a reporting limit below the"
REG_CANNOT = "compliance cannot be determined"
REG_NO_UNIT = "not compared: the result unit cannot be converted to that of the"
REG_OTHERS_BELOW = "All other results compared are below the applicable limits."
REG_ALL_BELOW = "All results compared are below the applicable limits."
REG_MORE = "For more information:"
ACCRED_TITLE = "Not covered by the laboratory's accreditation"
ACCRED_TEXT = ("This sample was analysed under project-specific requirements that depart "
               "from the published method. The departures are stated below. Results are "
               "reported in full; they are not accredited results.")
QUALS_TITLE = "Quality control qualifications"
QUALS_TEXT = ("The results below were released although a quality control criterion was "
              "not met. Each qualified result carries the code shown.")
QUALS_AFFECTED = "Affected analytes:"


def _s(v):
    return "" if v is None else "%s" % v


def legend(smp):
    parts = [LEGEND_U, LEGEND_MDL]
    if smp.get("codes"):
        parts.append(LEGEND_CODES)
    if not smp.get("any_rl"):
        parts.append(LEGEND_NO_RL)
    return " ".join(parts)


def departures(smp):
    deps = smp.get("departures") or []
    if not deps:
        return ""
    items = ["%s %s (method %s; %s)" % (_s(d.get("what")), _s(d.get("project")),
                                        _s(d.get("method")), _s(d.get("where"))) for d in deps]
    return "%s %s %s %s." % (DEPARTURES_A, _s(smp.get("project_label")), DEPARTURES_B,
                             "; ".join(items))


def regulatory(reg):
    if not reg:
        return ""
    lines = [REG_TITLE]
    for f in reg.get("findings") or []:
        limit = "%s %s of %s" % (_s(f.get("program")), _s(f.get("kind")), _s(f.get("limit")))
        st = f.get("status")
        if st == "exceeds":
            text = "%s: %s%s %s the %s." % (_s(f.get("label")), _s(f.get("total")),
                                            " (sum of detected values)" if f.get("sum") else "",
                                            REG_EXCEEDS, limit)
        elif st == "undetermined":
            text = "%s: %s %s; %s." % (_s(f.get("label")), REG_UNDETERMINED, limit, REG_CANNOT)
        elif st == "no_unit":
            text = "%s: %s %s." % (_s(f.get("label")), REG_NO_UNIT, limit)
        else:
            text = "%s: %s." % (_s(f.get("label")), limit)
        if f.get("citation"):
            text += " (%s)" % f["citation"]
        if f.get("note"):
            text += " %s" % f["note"]
        lines.append(text)
    if reg.get("below"):
        lines.append(REG_OTHERS_BELOW if reg.get("findings") else REG_ALL_BELOW)
    if reg.get("links"):
        lines.append("%s %s" % (REG_MORE, " · ".join(
            "%s (%s)" % (_s(l.get("label")), _s(l.get("url"))) for l in reg["links"])))
    return "\n".join(lines)


def accreditation(accred):
    if not accred or not accred.get("out_of_scope"):
        return ""
    lines = [ACCRED_TITLE, ACCRED_TEXT] + ["• %s" % l for l in accred.get("lines") or []]
    return "\n".join(lines)


def qc_qualifications(quals):
    if not quals:
        return ""
    lines = [QUALS_TITLE, QUALS_TEXT]
    for q in quals:
        line = "%s  %s" % (_s(q.get("code")), _s(q.get("statement")))
        if q.get("analytes"):
            line += " (%s %s)" % (QUALS_AFFECTED, q["analytes"])
        lines.append(line)
    return "\n".join(lines)


def _plain(html):
    """Rich text (a results interpretation) as plain text: paragraphs and
    line breaks kept as new lines, tags dropped, entities decoded."""
    import re
    text = re.sub(r"(?i)<\s*(br|/p|/div|/li|/h[1-6])\s*/?>", "\n", html or "")
    text = re.sub(r"<[^>]+>", "", text)
    try:
        from html import unescape                           # Python 3
    except ImportError:                                     # Python 2
        from HTMLParser import HTMLParser
        unescape = HTMLParser().unescape
    text = unescape(text)
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


def interpretation(ris):
    """The sample's results interpretation, per department, as impress's
    interpretations section prints it (title, then the text)."""
    out = []
    for ri in ris or []:
        body = _plain(ri.get("richtext"))
        if body:
            out.append(("%s\n%s" % (ri.get("title"), body)) if ri.get("title") else body)
    return "\n\n".join(out)


def unsupported(signatories, attachments):
    """What the standard certificate would print that a designed one cannot
    show: a second signature image in a role (the design has ONE signature
    per role: preparer, reviewer, director), and attachments marked for the
    report. A certificate with either is refused, never printed without them."""
    out = []
    sig = signatories or {}
    for role, people in (("preparer", sig.get("prepared")), ("reviewer", sig.get("verified"))):
        signed = [p.get("fullname") or "" for p in people or [] if p and p.get("signature_url")]
        if len(signed) > 1:
            out.append("more than one %s signature (%s)" % (role, ", ".join(signed)))
    if attachments:
        out.append("attachments marked to show in the report (%s)" % ", ".join(attachments))
    return out


def _people(infos):
    return "; ".join(" ".join(x for x in (_s(i.get("fullname")), _s(i.get("jobtitle")),
                                          _s(i.get("date"))) if x) for i in infos if i)


def stamp(report_id):
    parts = ["Controlled documentation publication"]
    if report_id:
        parts.append(report_id)
    parts.append("uncontrolled when printed")
    return " · ".join(parts)


def hidden_columns(fmt):
    fmt = fmt or {}
    return [key for key, flag in _FORMAT_COLUMNS if not fmt.get(flag)]


def action_levels(limits, programs=None):
    """{keyword: "4 ng/L (US EPA MCL)"} from the limits that apply to this
    sample (already filtered as the regulatory comparison filters them).
    Only VERIFIED limits on ONE analyte belong on a results row: a sum or a
    hazard index is the regulatory comparison's, not a row's."""
    programs = programs or {}
    out = {}
    for lim in limits or []:
        analytes = lim.get("analytes") or []
        if not lim.get("verified") or len(analytes) != 1 or lim.get("value") is None:
            continue
        prog = (programs.get(lim.get("program")) or {}).get("name") or lim.get("program") or ""
        text = "%s %s (%s)" % (_s(lim.get("value")), _s(lim.get("unit")),
                               " ".join(x for x in (prog, _s(lim.get("kind"))) if x))
        kw = analytes[0]
        out[kw] = "; ".join(x for x in (out.get(kw), text.replace(" ()", "")) if x)
    return out


def enrich_rows(rows, full_names, dates, levels):
    """Add the full name, date of analysis and action level to each results
    row (by its keyword), in place; returns rows."""
    for r in rows or []:
        kw = r.get("keyword")
        r["analyte_name"] = full_names.get(kw) or ""
        r["analysis_date"] = dates.get(kw) or ""
        r["action_level"] = levels.get(kw) or ""
    return rows


def image_data_uri(raw):
    """A PNG or JPEG as a data URI for an image field; None for anything else
    (an SVG can carry script; other formats pdfme cannot place)."""
    import base64
    if not raw:
        return None
    if isinstance(raw, type(u"")):
        return None
    if raw[:8] == b"\x89PNG\r\n\x1a\n":
        kind = "png"
    elif raw[:3] == b"\xff\xd8\xff":
        kind = "jpeg"
    else:
        return None
    b64 = base64.b64encode(raw)
    if not isinstance(b64, type(u"")):
        b64 = b64.decode("ascii")
    return "data:image/%s;base64,%s" % (kind, b64)


def placeholder_png(width=120, height=40):
    """A grey, diagonally striped picture: what an image field shows in the
    designer's preview -- obviously not a real logo or signature."""
    import struct
    import zlib
    rows = []
    for y in range(height):
        row = bytearray([0])
        for x in range(width):
            v = 200 if ((x + y) // 6) % 2 else 235
            row += bytearray([v, v, v])
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))
    return image_data_uri(png)


def signatory(info, signature=""):
    """One signatory's fields: name, title, credentials, date, signature
    (a data URI or "")."""
    info = info or {}
    return {"name": _s(info.get("fullname")), "title": _s(info.get("jobtitle")),
            "credentials": _s(info.get("credentials")), "date": _s(info.get("date")),
            "signature": signature or ""}


def data(lab, meta, smp, signatories=None, quals=None, accred=None, remarks="", interpretation_text="",
         extra=None, preview=False):
    """One sample's certificate data. `lab`, `meta` and `smp` are what
    PFASCoASectionsView.lab(), doc_meta() and _sample() return; the rest come
    from PFASCoAAttestationView. A sample _sample() could not assemble raises
    ValueError: a certificate never silently loses a sample."""
    if smp.get("error"):
        raise ValueError("%s: %s" % (smp.get("id"), smp["error"]))
    if smp.get("enrich_error"):
        raise ValueError("%s: the designed certificate's fields could not be assembled (%s)"
                         % (smp.get("id"), smp["enrich_error"]))
    if smp.get("qc_error"):
        raise ValueError("%s: the surrogate and internal-standard results could not be read (%s)"
                         % (smp.get("id"), smp["qc_error"]))
    sig = signatories or {}
    fmt = smp.get("fmt") or {}
    qcs = smp.get("qc_standards") or {"state": "none", "rows": [], "injections": 0}
    if qcs.get("state") in _qcs.BLOCKS_PUBLISHING and not preview:
        # the lab's preview shows why; a certificate is refused
        raise ValueError("%s: %s" % (smp.get("id"), _qcs.note({}, qcs["state"])[len(_qcs.DEFAULT_NOTE):].strip()))
    extra = extra or {}
    people = dict((role, extra.get(role) or signatory(None)) for role in ("preparer", "reviewer", "director"))
    out = {
        "lab_name": _s(lab.get("name")), "lab_contact": _s(lab.get("contact")),
        "lab_accreditation": _s(lab.get("accreditation")),
        "report_id": _s(meta.get("report_id")), "issued": _s(meta.get("issued")),
        "template_rev": _s(meta.get("template_rev")),
        "sample_id": _s(smp.get("id")), "client": _s(smp.get("client")),
        "contact": _s(smp.get("contact")), "client_sid": _s(smp.get("client_sid")),
        "matrix": _s(smp.get("matrix")), "batch": _s(smp.get("batch")),
        "sampled": _s(smp.get("sampled")), "received": _s(smp.get("received")),
        "analysed": _s(smp.get("analysed")), "method": _s(smp.get("method")),
        "units": _s(smp.get("units")), "note": _s(fmt.get("coa_note")),
        "legend": legend(smp), "qs_statement": _s(smp.get("qs")),
        "departures": departures(smp), "regulatory": regulatory(smp.get("regulatory")),
        "accreditation": accreditation(accred), "qc_qualifications": qc_qualifications(quals),
        "remarks": _s(remarks), "interpretation": _s(interpretation_text),
        "prepared_by": _people(sig.get("prepared") or []),
        "verified_by": _people(sig.get("verified") or []),
        "authorized_by": _people([sig.get("authorized")] if sig.get("authorized") else []),
        "stamp": stamp(_s(meta.get("report_id"))),
        "results": [{"analyte": _s(r.get("title")), "analyte_name": _s(r.get("analyte_name")),
                     "cas": _s(r.get("cas")), "analysis_date": _s(r.get("analysis_date")),
                     "result": _s(r.get("result")), "qual": _s(r.get("qualifiers")),
                     "rl": _s(r.get("rl")), "mdl": _s(r.get("mdl")), "unit": _s(r.get("unit")),
                     "dil": _s(r.get("dilution")), "action_level": _s(r.get("action_level"))}
                    for r in smp.get("rows") or []],
        "qc_standards": [dict((k, _s(q.get(k))) for k, _t, _e in QC_STANDARD_COLUMNS)
                         for q in qcs.get("rows") or []],
        "qc_standards_note": _s(smp.get("qc_note")) or _qcs.note(fmt, qcs.get("state")),
        # one injection (the usual case): the column says nothing
        "_hidden_columns": {"results": hidden_columns(fmt),
                            "qc_standards": [] if (qcs.get("injections") or 0) > 1 else ["injection"]},
        "lab_address": _s(extra.get("lab_address")), "lab_phone": _s(extra.get("lab_phone")),
        "lab_email": _s(extra.get("lab_email")), "lab_logo": extra.get("lab_logo") or "",
    }
    for role, p in people.items():
        for k in ("name", "title", "credentials", "date", "signature"):
            if role == "director" and k == "date":
                continue
            out["%s_%s" % (role, k)] = p.get(k) or ""
    return out


# ── a starting layout ───────────────────────────────────────────────────────

def _t(name, x, y, w, h, size=9, align="left", **kw):
    f = {"name": name, "type": "text", "position": {"x": x, "y": y}, "width": w,
         "height": h, "fontSize": size, "alignment": align, "content": ""}
    f.update(kw)
    return f


def _image(name, x, y, w, h, **kw):
    f = {"name": name, "type": "image", "position": {"x": x, "y": y}, "width": w,
         "height": h, "content": ""}
    f.update(kw)
    return f


def _fixed(name, text, x, y, w, h, size=8, align="left", **kw):
    return _t(name, x, y, w, h, size, align, readOnly=True, content=text, **kw)


def starter(width=210.0, height=297.0):
    """A certificate laid out like the standard one, with every required part
    in place, for the lab to rearrange (the designer offers it when a
    certificate design is empty). pdfme fills in each field's other settings
    when the designer opens it. Coordinates in mm; content flows below the
    header and above the footer on every page."""
    every = {"pfasEveryPage": True}
    right = width - 10.0
    wide = width - 20.0
    header = [
        _image("lab_logo", 10, 8, 28, 18, **every),
        _t("lab_name", 42, 8, 80, 7, 14, **every),
        _t("lab_address", 42, 15.5, 80, 4.5, 7.5, **every),
        _t("lab_phone", 42, 20, 38, 4.5, 7.5, **every),
        _t("lab_email", 81, 20, 41, 4.5, 7.5, **every),
        _t("lab_accreditation", 42, 24.5, 80, 4.5, 7.5, **every),
        _fixed("title", "Certificate of Analysis", right - 80, 10, 80, 7, 13, "right", **every),
        _fixed("label_report", "Report", right - 80, 18, 25, 5, **every),
        _t("report_id", right - 55, 18, 55, 5, 9, "right", **every),
        _fixed("label_issued", "Issued", right - 80, 23, 25, 5, **every),
        _t("issued", right - 55, 23, 55, 5, 9, "right", **every),
        _fixed("label_template_rev", "Template revision", right - 80, 28, 30, 5, **every),
        _t("template_rev", right - 50, 28, 50, 5, 9, "right", **every),
        dict({"name": "header_rule", "type": "line", "position": {"x": 10, "y": 34},
              "width": wide, "height": 0.4, "readOnly": True, "color": "#222222"}, **every),
    ]
    block = []
    pairs = [("Client", "client", "Lab sample ID", "sample_id"),
             ("Contact", "contact", "Client sample ID", "client_sid"),
             ("Matrix", "matrix", "Batch", "batch"),
             ("Sampled", "sampled", "Received", "received"),
             ("Method", "method", "Analysed", "analysed")]
    for i, (l1, k1, l2, k2) in enumerate(pairs):
        y = 40 + i * 6
        block += [_fixed("label_" + k1, l1, 10, y, 28, 5), _t(k1, 38, y, 62, 5),
                  _fixed("label_" + k2, l2, 105, y, 30, 5), _t(k2, 135, y, right - 135, 5)]
    # the lab's column list: sample information then analysis
    # information; drop any in the designer
    cols = ("analyte_name", "analyte", "cas", "analysis_date", "result", "dil", "qual",
            "unit", "rl", "mdl", "action_level")
    titles = dict((k, t) for k, t, _e in RESULT_COLUMNS)
    table = {"name": "results", "type": "table", "position": {"x": 10, "y": 72},
             "width": wide, "height": 20, "showHead": True, "repeatHead": True,
             "head": [titles[k] for k in cols],
             "headWidthPercentages": [21, 9, 10, 10, 9, 6, 6, 6, 7, 7, 9],
             "pfasColumns": list(cols),
             "content": "[]",
             # the standard certificate's table: small, black on white, ruled
             "tableStyles": {"borderColor": "#222222", "borderWidth": 0.2},
             "headStyles": {"fontSize": 6.5, "fontColor": "#222222", "backgroundColor": "",
                            "borderColor": "#222222",
                            "borderWidth": {"top": 0.3, "right": 0, "bottom": 0.3, "left": 0},
                            "padding": {"top": 1.5, "right": 1.5, "bottom": 1.5, "left": 1.5}},
             "bodyStyles": {"fontSize": 7, "borderColor": "#dddddd", "alternateBackgroundColor": "",
                            "borderWidth": {"top": 0, "right": 0, "bottom": 0.1, "left": 0},
                            "padding": {"top": 1, "right": 1.5, "bottom": 1, "left": 1.5}}}
    flow = []
    y = 96
    for key in ("note", "legend"):
        flow.append(_t(key, 10, y, wide, 5, 8, overflow="expand"))
        y += 6
    # surrogates and internal standards: their own table and note
    qtitles = dict((k, ti) for k, ti, _e in QC_STANDARD_COLUMNS)
    qcols = [k for k, _t2, _e in QC_STANDARD_COLUMNS]
    import copy
    qtable = copy.deepcopy(table)
    flow.append(_fixed("label_qc_standards", QC_TITLE, 10, y + 2, wide, 5, 8.5))
    y += 6
    qtable.update(name="qc_standards", position={"x": 10, "y": y + 1}, height=10,
                  head=[qtitles[k] for k in qcols], headWidthPercentages=[18, 18, 17, 17, 9, 10, 11],
                  pfasColumns=list(qcols))
    flow.append(qtable)
    y += 13                 # the table grows with its rows and moves what follows down
    flow.append(_t("qc_standards_note", 10, y, wide, 5, 7.5, overflow="expand"))
    y += 6
    for key in ("qs_statement", "departures", "regulatory",
                "accreditation", "qc_qualifications", "remarks", "interpretation"):
        flow.append(_t(key, 10, y, wide, 5, 8, overflow="expand"))
        y += 6
    y += 4
    # signatories: name, title, credentials and date, the signature beside them
    for label, role, everyone in (("Prepared by", "preparer", "prepared_by"),
                                  ("Reviewed by", "reviewer", "verified_by"),
                                  ("Laboratory Director", "director", None)):
        flow += [_fixed("label_" + role, label, 10, y, 30, 5),
                 _t(role + "_name", 40, y, 70, 5, 9),
                 _t(role + "_title", 40, y + 5, 70, 4.5, 7.5),
                 _t(role + "_credentials", 40, y + 9.5, 70, 4.5, 7.5),
                 _image(role + "_signature", right - 55, y, 55, 16)]
        if role != "director":
            flow.append(_t(role + "_date", 40, y + 14, 70, 4.5, 7.5))
        if everyone:
            flow.append(_t(everyone, 10, y + 19, wide, 4.5, 7, overflow="expand"))
        y += 25
    flow += [_fixed("label_authorized_by", "Authorized by", 10, y, 30, 5),
             _t("authorized_by", 40, y, wide - 30, 5)]
    footer = [
        dict({"name": "footer_rule", "type": "line", "position": {"x": 10, "y": height - 17},
              "width": wide, "height": 0.3, "readOnly": True, "color": "#999999"}, **every),
        _t("stamp", 10, height - 15, wide - 50, 5, 7, **every),
        _fixed("pager", "Page {currentPage} of {totalPages}", right - 50, height - 15, 50, 5, 7,
               "right", **every),
    ]
    return {"basePdf": {"width": width, "height": height, "padding": [38, 10, 20, 10]},
            "schemas": [header + block + [table] + flow + footer]}
