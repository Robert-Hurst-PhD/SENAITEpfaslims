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

from senaite.pfas.print_style import PALETTE as _P

from senaite.pfas import coa_qc_standards as _qcs
from senaite.pfas import doc_fields as _df

# The data fields, grouped as the designer offers them under the shared
# categories (doc_fields: sample; analysis; laboratory; preparer / reviewer /
# director; quality control; document control).
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
        ("result_unit", "Result unit", "ng/L"),
        ("dilution_notes", "Dilution notes", "\u00b9 Re-analysed at a 1:5 dilution on 2026-10-07 09:12"),
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
        ("preparer_label", "Preparer heading", "Prepared by"),
        ("preparer_name", "Preparer", "AN1"),
        ("preparer_title", "Preparer title", "Analyst"),
        ("preparer_credentials", "Preparer credentials", "B.Sc."),
        ("preparer_date", "Prepared on", "2026-10-03"),
        ("preparer_signature", "Preparer signature", ""),
        ("prepared_by", "Prepared by (everyone, with dates)", "AN1 2026-10-03"),
    ]),
    (_df.REVIEWER, [
        ("reviewer_label", "Reviewer heading", "Reviewed by"),
        ("reviewer_name", "Reviewer", "AN2"),
        ("reviewer_title", "Reviewer title", "QA Officer"),
        ("reviewer_credentials", "Reviewer credentials", "M.Sc."),
        ("reviewer_date", "Reviewed on", "2026-10-04"),
        ("reviewer_signature", "Reviewer signature", ""),
        ("verified_by", "Verified by (everyone, with dates)", "AN2 2026-10-04"),
    ]),
    (_df.DIRECTOR, [
        ("director_label", "Director heading", "Laboratory Director"),
        ("director_name", "Laboratory Director", "AN3"),
        ("director_title", "Director title", "Director, DEMO Laboratory"),
        ("director_credentials", "Director credentials", "Ph.D."),
        ("director_signature", "Director signature", ""),
        # the director's own block: empty when the director reviewed, whose
        # one block is then "Reviewed and authorized by"
        ("director2_name", "Director block: name", "AN3"),
        ("director2_title", "Director block: title", "Director, DEMO Laboratory"),
        ("director2_credentials", "Director block: credentials", "Ph.D."),
        ("director2_signature", "Director block: signature", ""),
        ("authorized_by", "Authorized by (who published)", "AN3 2026-10-05"),
        ("authorizer", "Authorizing person: name and role", "AN3 \u00b7 Laboratory Director"),
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
IMAGES = ("lab_logo", "preparer_signature", "reviewer_signature", "director_signature",
          "director2_signature")

# (column key, title, example), in the lab's order. "analyte" is the REPORTED
# name (the abbreviation, e.g. PFOS; a summed analyte's reported label);
# "analyte_name" the full name, isomer-aware (isomers.full_name). The unit is
# not a column: one per matrix, it is data()["result_unit"], for the Result
# heading.
RESULT_COLUMNS = [
    ("analyte_name", "Analyte", "Perfluorooctanoic acid"),
    ("analyte", "Abbreviation", "PFOA"),
    ("cas", "CAS No.", "335-67-1"),
    ("analysis_date", "Analysed", "2026-10-03"),
    ("result", "Result", "4.2"),
    ("qual", "Qualifier", "J"),
    ("mdl", "MDL", "0.5"),
    ("rl", "RL", "2.0"),
    ("action_level", "MCL", "4 ng/L (US EPA MCL)"),
    ("dil", "Dilution", "1"),
]
RESULT_COLUMN_GROUPS = [
    (_df.SAMPLE, ("analyte_name", "analyte", "cas")),
    (_df.ANALYSIS, ("analysis_date", "result", "qual", "mdl", "rl", "action_level", "dil")),
]
# printed in an MDL or MCL cell with no value: no limit is ever invented
NONE_MARK = "\u2014"
# Columns a layout issued earlier may still carry: they keep printing (each
# results row keeps its "unit") and re-issue with a warning, not a refusal.
RETIRED_COLUMNS = {"results": {"unit": "the unit now heads the Result column, from the Result unit field"}}
# A heading names its column: it contains the column's title or a title the
# column had before (a layout issued earlier keeps its headings), also for a
# retired column. document_templates.column_for and the designer match so.
# A heading that names two columns ("Analyte") keeps the one it is linked to.
COLUMN_ALIASES = {"results": {"analysis_date": ("Date of analysis",), "unit": ("Units",),
                              "analyte": ("Analyte",), "qual": ("Qual",), "dil": ("Dil.",)},
                  "qc_standards": {"standard": ("Labelled standard",)}}
# Signer headings that layouts issued earlier print as fixed text: a warning
# on re-issue, not a refusal (document_templates.warnings).
HEADING_FIELDS = ("preparer_label", "reviewer_label", "director_label")

# the surrogate / internal-standard sub-table
QC_STANDARD_COLUMNS = _qcs.COLUMNS

# Results columns the method x matrix Reporting format may hide (as the HTML
# hides them); dropped from that sample's table when the format says so.
_FORMAT_COLUMNS = (("cas", "coa_show_cas"), ("mdl", "coa_show_mdl"), ("dil", "coa_show_dilution"))

# A designed certificate cannot be issued without these: everything the standard
# certificate states, disclosures included (an empty one prints nothing), and
# the three signatories with their signatures. A tuple is one part shown by
# any of its fields (each signer's block, or the lines of names and dates
# layouts issued earlier print; the authorizing person as name and role, or
# in the older shape; the director's own block, or the director's fields).
REQUIRED_FIELDS = ("report_id", "issued", "lab_name", "sample_id", "client", "matrix",
                   "method", "legend", "note", "qc_standards_note", "qs_statement", "departures", "regulatory",
                   "accreditation", "qc_qualifications", "remarks", "interpretation",
                   ("preparer_name", "prepared_by"), ("reviewer_name", "verified_by"),
                   ("authorizer", "authorized_by"), "stamp",
                   "preparer_signature", "reviewer_signature", ("director2_name", "director_name"),
                   ("director2_signature", "director_signature"))
REQUIRED_COLUMNS = {"results": ("analyte", "result", "qual", "rl"),
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
    # the J and D lines, in the lab's wording (QC Qualifiers), when a row
    # carries them
    parts += [c.get("line") or "" for c in smp.get("rule_codes") or [] if c.get("line")]
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


def enrich_rows(rows, full_names, dates, levels, times=None):
    """Add the full name, date of analysis (the day), the analysis' date and
    time and the action level to each results row (by its keyword), in
    place; returns rows."""
    times = times or {}
    for r in rows or []:
        kw = r.get("keyword")
        r["analyte_name"] = full_names.get(kw) or ""
        r["analysis_date"] = dates.get(kw) or ""
        r["analysed_at"] = times.get(kw) or ""
        r["action_level"] = levels.get(kw) or ""
    return rows


_SUPERSCRIPT = dict(zip("0123456789", "\u2070\u00b9\u00b2\u00b3\u2074\u2075\u2076\u2077\u2078\u2079"))


def superscript(n):
    """A footnote mark: 1 is '\u00b9', 12 is '\u00b9\u00b2'."""
    return "".join(_SUPERSCRIPT[c] for c in "%d" % n)


DILUTION_NOTE = "Re-analysed at a 1:%s dilution"


def dilution_notes(rows):
    """(marks, notes): one footnote per diluted row, numbered in row order;
    marks[i] is row i's superscript ("" for a row not diluted)."""
    marks, notes = [], []
    for r in rows or []:
        fold = _s(r.get("dilution"))
        if not fold:
            marks.append("")
            continue
        mark = superscript(len(notes) + 1)
        when = _s(r.get("analysed_at")) or _s(r.get("analysis_date"))
        text = DILUTION_NOTE % fold + (" on %s" % when if when else "")
        marks.append(mark)
        notes.append("%s %s" % (mark, text))
    return marks, notes


def signers(preparer=None, reviewer=None, director=None, reviewer_is_director=False):
    """{role: signatory fields + "label"}. The fields keep their meaning in
    every case (a layout issued earlier prints them): the director's are the
    director's even when the director also reviewed. The labels say how the
    roles fall: when the reviewer is the Laboratory Director the reviewer's
    heading is "Reviewed and authorized by", with the director's title when
    the reviewer has none, and the director's heading is empty."""
    empty = signatory(None)
    out = {"preparer": dict(preparer or empty, label="Prepared by"),
           "reviewer": dict(reviewer or empty, label="Reviewed by"),
           "director": dict(director or empty, label="Laboratory Director")}
    if reviewer_is_director and reviewer:
        d = director or {}
        out["reviewer"] = dict(reviewer, label="Reviewed and authorized by",
                               title=reviewer.get("title") or d.get("title") or "")
        out["director"]["label"] = ""
    return out


AUTHORIZING_PLACEHOLDER = "[authorizing person]"
# a submitter or verifier with neither a Lab Contact name nor a full name
NO_STAFF_RECORD = "[no lab staff record]"
NO_PUBLISHER = "The person publishing has no lab staff record; add one in People & Roles"


def staff_name(info, userid):
    """A staff member as a message names them: the full name staff_info
    found, else the placeholder; never the account id it falls back to."""
    name = (info or {}).get("fullname") or ""
    return name if name and name != (userid or "") else NO_STAFF_RECORD


def authorizing_role(jobtitle, is_director=False, sign_as=None):
    """The role printed beside the authorizing person's name: their job
    title on People & Roles, else Laboratory Director when they are the one the
    Laboratory page names, else the roles they sign as."""
    if jobtitle:
        return jobtitle
    if is_director:
        return "Laboratory Director"
    names = {"preparer": "Preparer", "reviewer": "Reviewer"}
    return " and ".join(names[r] for r in ("preparer", "reviewer") if r in (sign_as or []))


def _authorizing_name(info):
    """The publishing person's name from their People & Roles record, or the
    placeholder: never an account id."""
    return _s(info.get("fullname")) if info.get("has_contact") else AUTHORIZING_PLACEHOLDER


def authorized_line(info):
    """"Name \u00b7 Role" of the person who publishes (the authorizer field)."""
    if not info:
        return ""
    return " \u00b7 ".join(x for x in (_authorizing_name(info), _s(info.get("role"))) if x)


def authorized_by(info):
    """The authorized_by field in the shape layouts issued earlier print:
    name, job title and date, the name from People & Roles."""
    if not info:
        return ""
    return _people([dict(info, fullname=_authorizing_name(info),
                         jobtitle=info.get("jobtitle") if info.get("has_contact") else "")])


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
    authorized = sig.get("authorized")
    if signatories is not None and not preview and not (authorized or {}).get("has_contact"):
        # the authorizing line names the person and role on their People & Roles
        # record, never an account
        raise ValueError(NO_PUBLISHER)
    people = signers(extra.get("preparer"), extra.get("reviewer"), extra.get("director"),
                     extra.get("reviewer_is_director"))
    rows = smp.get("rows") or []
    marks, notes = dilution_notes(rows)
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
        "result_unit": _s(smp.get("result_unit") or smp.get("units")),
        "dilution_notes": notes,
        "legend": legend(smp), "qs_statement": _s(smp.get("qs")),
        "departures": departures(smp), "regulatory": regulatory(smp.get("regulatory")),
        "accreditation": accreditation(accred), "qc_qualifications": qc_qualifications(quals),
        "remarks": _s(remarks), "interpretation": _s(interpretation_text),
        "prepared_by": _people(sig.get("prepared") or []),
        "verified_by": _people(sig.get("verified") or []),
        "authorized_by": authorized_by(authorized),
        "authorizer": authorized_line(authorized),
        "stamp": stamp(_s(meta.get("report_id"))),
        # "unit" stays on each row for a layout issued with a Units column
        "results": [{"analyte": _s(r.get("title")), "analyte_name": _s(r.get("analyte_name")),
                     "cas": _s(r.get("cas")), "analysis_date": _s(r.get("analysis_date")),
                     "analysed_at": _s(r.get("analysed_at")),
                     "result": _s(r.get("result")), "qual": _s(r.get("qualifiers")),
                     "rl": _s(r.get("rl")), "mdl": _s(r.get("mdl")) or NONE_MARK,
                     "unit": _s(r.get("unit")), "dil": _s(r.get("dilution")),
                     "action_level": _s(r.get("action_level")) or NONE_MARK}
                    for r in rows],
        # a diluted row's mark on its date prints only on a layout that
        # prints the notes it points to (document_templates.compile_document)
        "_footnotes": {"field": "dilution_notes", "table": "results", "column": "analysis_date",
                       "marks": marks},
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
        for k in ("label", "name", "title", "credentials", "date", "signature"):
            if role == "director" and k == "date":
                continue
            out["%s_%s" % (role, k)] = p.get(k) or ""
    # the director's own block prints only when the director did not review
    own = people["director"] if people["director"]["label"] else {}
    for k in ("name", "title", "credentials", "signature"):
        out["director2_%s" % k] = own.get(k) or ""
    return out


# ── a starting layout ───────────────────────────────────────────────────────

def _t(name, x, y, w, h, size=9, align="left", **kw):
    return _df.text_field(name, x, y, w, h, size, align, **kw)


_image = _df.image_field


def _fixed(name, text, x, y, w, h, size=8, align="left", **kw):
    return _t(name, x, y, w, h, size, align, readOnly=True, content=text, **kw)


# the results table: each column's share of the width (Analyte, the full
# name, widest) and the columns whose numbers align right
RESULT_WIDTHS = {"analyte_name": 21.5, "analyte": 11, "cas": 9, "analysis_date": 10, "result": 9,
                 "qual": 7, "mdl": 6, "rl": 6, "action_level": 14.5, "dil": 6}
RIGHT_ALIGNED = ("result", "mdl", "rl", "action_level")
# the columns the designer's table chooser starts ticked: the starting
# layout's, Dilution included (it prints only where Certificate format
# shows it)
RESULT_DEFAULT_COLUMNS = ("analyte_name", "analyte", "cas", "analysis_date", "result", "qual", "mdl", "rl",
                          "action_level", "dil")
# a heading may name a data field in braces: the Result heading carries the
# unit ("Result ng/L"; document_templates.compile_document)
RESULT_HEADING = "Result {result_unit}"


def starter(width=210.0, height=297.0):
    """A certificate laid out like the standard one, with every required part
    in place, for the lab to rearrange (the designer offers it when a
    certificate design is empty, and Document Templates starts a draft from
    it). pdfme fills in each field's other settings when the designer opens
    it. Coordinates in mm; content flows below the header and above the
    footer on every page."""
    every = {"pfasEveryPage": True}
    right = width - 10.0
    wide = width - 20.0
    header = [
        _image("lab_logo", 10, 8, 28, 18, **every),
        # two fixed lines: a long name or address prints smaller, never over
        # the line under it
        _t("lab_name", 42, 8, 80, 7, 14, dynamicFontSize={"min": 9, "max": 14, "fit": "horizontal"},
           **every),
        _t("lab_address", 42, 15.5, 80, 4.5, 7.5,
           dynamicFontSize={"min": 6, "max": 7.5, "fit": "horizontal"}, **every),
        _t("lab_phone", 42, 20, 38, 4.5, 7.5, **every),
        _t("lab_email", 81, 20, 41, 4.5, 7.5, **every),
        _t("lab_accreditation", 42, 24.5, 80, 4.5, 7.5, **every),
        _fixed("title", "Certificate of Analysis", right - 76, 10, 76, 7, 13, "right", **every),
        _fixed("label_report", "Report", right - 76, 18, 25, 5, **every),
        _t("report_id", right - 51, 18, 51, 5, 9, "right", **every),
        _fixed("label_issued", "Issued", right - 76, 23, 25, 5, **every),
        _t("issued", right - 51, 23, 51, 5, 9, "right", **every),
        _fixed("label_template_rev", "Template revision", right - 76, 28, 30, 5, **every),
        _t("template_rev", right - 46, 28, 46, 5, 9, "right", **every),
        dict({"name": "header_rule", "type": "line", "position": {"x": 10, "y": 34},
              "width": wide, "height": 0.4, "readOnly": True, "color": _P["s-body"]}, **every),
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
    # the lab's column list, in its order; drop any in the designer
    cols = list(RESULT_DEFAULT_COLUMNS)
    titles = dict((k, t) for k, t, _e in RESULT_COLUMNS)
    titles["result"] = RESULT_HEADING
    table = {"name": "results", "type": "table", "position": {"x": 10, "y": 72},
             "width": wide, "height": 20, "showHead": True, "repeatHead": True,
             "head": [titles[k] for k in cols],
             "headWidthPercentages": [RESULT_WIDTHS[k] for k in cols],
             "pfasColumns": list(cols),
             "content": "[]",
             # the standard certificate's table: small, black on white, ruled
             "tableStyles": {"borderColor": _P["s-body"], "borderWidth": 0.2},
             "headStyles": {"fontSize": 6.5, "fontColor": _P["s-body"], "backgroundColor": "",
                            "borderColor": _P["s-body"],
                            "borderWidth": {"top": 0.3, "right": 0, "bottom": 0.3, "left": 0},
                            "padding": {"top": 1.5, "right": 1.5, "bottom": 1.5, "left": 1.5}},
             "bodyStyles": {"fontSize": 7, "borderColor": _P["s-border"], "alternateBackgroundColor": "",
                            "borderWidth": {"top": 0, "right": 0, "bottom": 0.1, "left": 0},
                            "padding": {"top": 1, "right": 1.5, "bottom": 1, "left": 1.5}},
             "columnStyles": {"alignment": dict((str(i), "right") for i, k in enumerate(cols)
                                                if k in RIGHT_ALIGNED)}}
    flow = []
    # under the table: the dilution notes its marks point to, then the legend
    flow.append(_t("dilution_notes", 10, 93, wide, 3.5, 7, overflow="expand"))
    y = 97
    for key in ("legend", "note"):
        flow.append(_t(key, 10, y, wide, 5, 8 if key == "note" else 7.5, overflow="expand"))
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
                  pfasColumns=list(qcols), columnStyles={})
    flow.append(qtable)
    y += 13                 # the table grows with its rows and moves what follows down
    flow.append(_t("qc_standards_note", 10, y, wide, 5, 7.5, overflow="expand"))
    y += 6
    for key in ("qs_statement", "departures", "regulatory",
                "accreditation", "qc_qualifications", "remarks", "interpretation"):
        flow.append(_t(key, 10, y, wide, 5, 8, overflow="expand"))
        y += 6
    y += 4
    # one block per role: name, title, credentials and date, the signature
    # beside them. The headings are data ("Reviewed and authorized by" when
    # the reviewer is the Laboratory Director); the director's own block is
    # then empty.
    for role, who in (("preparer", "preparer"), ("reviewer", "reviewer"), ("director", "director2")):
        flow += [_t(role + "_label", 10, y, 30, 5, 8),
                 _t(who + "_name", 40, y, 70, 5, 9),
                 _t(who + "_title", 40, y + 5, 70, 4.5, 7.5),
                 _t(who + "_credentials", 40, y + 9.5, 70, 4.5, 7.5),
                 _image(who + "_signature", right - 55, y, 55, 16)]
        if role != "director":
            flow.append(_t(role + "_date", 40, y + 14, 70, 4.5, 7.5))
        y += 21
    # who published: name and role from People & Roles
    flow += [_fixed("label_authorizer", "Authorized by", 10, y, 30, 5),
             _t("authorizer", 40, y, wide - 30, 5)]
    footer = [
        dict({"name": "footer_rule", "type": "line", "position": {"x": 10, "y": height - 17},
              "width": wide, "height": 0.3, "readOnly": True, "color": _P["s-input-border"]}, **every),
        _t("stamp", 10, height - 15, wide - 50, 5, 7, **every),
        _fixed("pager", "Page {currentPage} of {totalPages}", right - 50, height - 15, 50, 5, 7,
               "right", **every),
    ]
    return {"basePdf": {"width": width, "height": height, "padding": [38, 10, 20, 10]},
            "schemas": [header + block + [table] + flow + footer]}
