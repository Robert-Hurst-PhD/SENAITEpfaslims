# -*- coding: utf-8 -*-
"""The facts a column-mapped EDD profile writes, collected from a batch
(see edd_delimited for the shape and the writer). Python 2.7, Zope.

Field samples are the batch's samples, read as the default format reads them
(the certificate's rounded rows: result, detected, RL, MDL, qualifiers; the
dilution; acquisition and extraction times). Lab QC samples are the members
of each worksheet's extraction batch (extraction_batch: LRB, MB, LFB, LCS,
LFSM, LFSMD, Dup, MxB, each with its injection name and parent), with the
worker's judged QC results for that worksheet (the QC database: measured
concentration per injection, recovery and its limits, RPD and its limit,
pass / fail). A QC row's reporting limit and MDL are the batch's for the
analyte. The database holds no QC injection's acquisition time: a QC row
has the run's date (analysis.run_date) and when the worker judged it
(analysis.judged_at); a lab QC sample's preparation is its extraction's
finish (sample.date_prepared).
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging
import sqlite3
from datetime import date, datetime

logger = logging.getLogger("senaite.pfas.edd_facts")

LAB_QC = (u"MB", u"LRB", u"MxB", u"LFB", u"LCS", u"LCSD", u"LFSM", u"LFSMD", u"Dup")
_ROLE = {"analyte": u"target", "surrogate": u"surrogate", "injection_is": u"internal standard",
         "internal_standard": u"internal standard"}


def _py(v):
    """A Zope DateTime (or datetime) as a naive datetime on its own clock."""
    if v is None or v == u"":
        return None
    if isinstance(v, (datetime, date)):
        return v
    try:
        y, mo, d, h, mi, s = v.parts()[:6]
        return datetime(int(y), int(mo), int(d), int(h), int(mi), int(s))
    except Exception:                                       # noqa: BLE001
        return None


def _field(obj, name):
    try:
        f = obj.getField(name)
        return f.get(obj) if f is not None else None
    except Exception:                                       # noqa: BLE001
        return None


def _our_qc_type(ar):
    """The sample's own QC role (as the default format derives it)."""
    from zope.annotation.interfaces import IAnnotations
    try:
        ours = (IAnnotations(ar).get("senaite.pfas.qc_type", "") or "").strip()
    except Exception:                                       # noqa: BLE001
        ours = ""
    if not ours:
        try:
            from senaite.pfas.coc_records import FIELD_QC_CODES
            ours = FIELD_QC_CODES.get(_field(ar, "FieldQCType") or u"", "")
        except Exception:                                   # noqa: BLE001
            ours = ""
    return ours or u"NA"


def _unit(portal, method_id, matrix, analysis):
    try:
        from senaite.pfas.method_profile_store import get_profile
        u = ((get_profile(portal, method_id) or {}).get("unit_map") or {}).get(matrix or u"", u"")
        if u:
            return u
    except Exception:                                       # noqa: BLE001
        pass
    try:
        return analysis.getUnit() or u""
    except Exception:                                       # noqa: BLE001
        return u""


def _library():
    from senaite.pfas import compound_library_store
    return compound_library_store.library()


def field_sample(builder, ar, batch_profile_id, library):
    """{sample facts, "results": [...]} of one batch sample, or None (a
    dilution is the same extract, folded into its parent)."""
    from zope.annotation.interfaces import IAnnotations
    from bika.lims import api
    from senaite.pfas import compound_library
    try:
        if (IAnnotations(ar).get("senaite.pfas.qc_type", "") or "").strip() == "Dilution":
            return None
    except Exception:                                       # noqa: BLE001
        pass
    portal = builder.portal
    st = ar.getSampleType()
    matrix = st.Title() if st else u""
    sp = ar.getSamplePoint() if hasattr(ar, "getSamplePoint") else None
    qc_type = _our_qc_type(ar)
    field_qc = _field(ar, "FieldQCType") or u""
    s = {"id": ar.getId(), "client_sample_id": getattr(ar, "getClientSampleID", lambda: u"")() or u"",
         "date_sampled": _py(ar.getDateSampled()), "date_received": _py(getattr(ar, "getDateReceived",
                                                                                  lambda: None)()),
         "date_prepared": None,
         "matrix": matrix, "qc_type": qc_type,
         "origin": u"lab" if qc_type in LAB_QC else u"field",
         "sample_point": sp.Title() if sp else u"", "coc_number": _field(ar, "CoCNumber") or u"",
         "duplicate_of": (_field(ar, "FieldQCOf") or u"") if field_qc == u"Field duplicate" else u"",
         "results": []}
    method_id = u""
    try:
        method = ar.getMethod()
        if method:
            from senaite.pfas.method_bridge import get_profile_id_for_method
            method_id = get_profile_id_for_method(portal, method) or u""
    except Exception:                                       # noqa: BLE001
        pass
    method_id = method_id or batch_profile_id or u""
    cas = compound_library.cas_by_keyword(library, dashed=True)
    roles = dict((kw, c.get("role")) for kw, c in compound_library.compounds(library).items())
    cert, reported = builder._certificate_rows(ar)
    for analysis in ar.getAnalyses(full_objects=True):
        try:
            if analysis.isRetested():
                continue
        except Exception:                                   # noqa: BLE001
            pass
        if api.get_uid(analysis) not in reported:
            continue
        kw = analysis.getKeyword()
        row = cert.get(kw)
        if row is None:
            continue
        test_kind, factor = u"initial", 1
        try:
            if analysis.isRetest():
                from senaite.pfas.browser.dilution_retests import _load
                rec = _load(analysis.getRetestOf()) or {}
                factor = rec.get("factor") or 1
                test_kind = u"dilution 1" if rec.get("factor") else u"reanalysis"
        except Exception:                                   # noqa: BLE001
            pass
        codes = ["N.D."] if row["detected"] is False else []
        codes += [c.strip() for c in (row.get("qualifiers") or "").split(",") if c.strip() and c.strip() != "U"]
        for interim in analysis.getInterimFields() or []:
            if (interim.get("keyword") or "").lower() in ("qualifier", "lab_qualifier") and interim.get("value"):
                codes.append(u"%s" % interim.get("value"))
        ws = None
        try:
            ws = analysis.getWorksheet()
        except Exception:                                   # noqa: BLE001
            ws = None
        try:
            precision = analysis.getPrecision()
        except Exception:                                   # noqa: BLE001
            precision = None
        s["results"].append({
            "keyword": kw, "cas": cas.get(kw) or u"", "role": _ROLE.get(roles.get(kw), u"target"),
            "method": method_id, "test_kind": test_kind,
            "acquired_at": _py(builder._acquired(analysis)), "run_date": None, "judged_at": None,
            "worksheet": ws.getId() if ws is not None else u"",
            "value": row["result"] if row["detected"] else u"",
            "detected": u"detected" if row["detected"] else u"not detected",
            "unit": _unit(portal, method_id, matrix, analysis), "rl": row.get("rl") or u"",
            "mdl": row.get("mdl") or u"", "dilution_factor": factor, "qualifiers": codes,
            "reportable": u"reported", "prep_date": _py(builder._extracted(analysis)),
            "precision": precision, "qc": {}})
    return s


def _qc_db():
    from senaite.pfas.qc.store import DEFAULT_DB_PATH
    conn = sqlite3.connect(DEFAULT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _fmt(value, precision):
    if value is None:
        return u""
    try:
        p = int(precision)
    except (TypeError, ValueError):
        return u"%s" % value
    return (u"%." + u"%d" % p + u"f") % float(value)


def judged_kind(level, injection):
    """What a judged QC row of a spiked QC injection states: u"rpd", u"recovery"
    or None when the row belongs to another injection. The pipeline names a
    row's level by the injection it judges ("<injection>"), or by the kind with
    the injection after it ("RPD <injection>", "Recovery <injection>"); older
    rows carry the kind alone or nothing."""
    level = level or u""
    for kind, word in ((u"rpd", u"RPD"), (u"recovery", u"Recovery")):
        if level == word:
            return kind
        if level.startswith(word + u" "):
            return kind if level[len(word) + 1:] == (injection or u"") else None
    if level in (u"", injection):
        return u"recovery"
    return None


def lab_qc_samples(builder, worksheets, field, library):
    """The lab QC samples of the worksheets, with the worker's judged QC
    results: [{sample facts, "results": [...]}]."""
    from senaite.pfas import compound_library, extraction_batch
    n2k = compound_library.name_to_keyword(library)
    cas = compound_library.cas_by_keyword(library, dashed=True)
    by_member = dict((s["id"], s) for s in field)
    by_csid = dict((s["client_sample_id"], s) for s in field)
    # the batch's reporting facts per analyte (RL, MDL, unit, precision,
    # method), as its field samples carry them
    per_kw = {}
    for s in field:
        for r in s["results"]:
            per_kw.setdefault(r["keyword"], r)
    out = []
    try:
        conn = _qc_db()
    except Exception as exc:                               # noqa: BLE001
        logger.warning("EDD: the QC database cannot be read: %s", exc)
        return out
    try:
        for ws in worksheets:
            ws_id = ws.getId()
            everyone = extraction_batch.load(ws)
            member_by_id = dict((m.get("id"), m) for m in everyone)
            members = [m for m in everyone if m.get("role") in LAB_QC]
            try:
                judged = [dict(r) for r in conn.execute(
                    "SELECT qc_type, qc_level, analyte, value, passed, limit_low, limit_high, applies_to, "
                    "run_date, created_at FROM qc_results WHERE batch_id=? AND result_status='active'", (ws_id,))]
            except sqlite3.Error as exc:
                logger.warning("EDD: %s's QC results cannot be read: %s", ws_id, exc)
                continue
            finished = None
            try:
                finished = builder._extracted(type(str("_A"), (object,), {"getWorksheet": lambda self: ws})())
            except Exception:                               # noqa: BLE001
                finished = None
            for m in members:
                inj = m.get("injection") or u""
                # the parent is a sample member (its id); that member names
                # the sample
                pm = member_by_id.get(m.get("parent") or u"") or {}
                parent = by_member.get(pm.get("sample_id") or u"") or by_csid.get(pm.get("client_sid") or u"")
                role = m.get("role")
                s = {"id": inj, "client_sample_id": inj, "date_sampled": parent["date_sampled"] if parent else None,
                     "date_received": None, "date_prepared": finished, "matrix": (parent or {}).get("matrix") or m.get("matrix") or (
                         field[0]["matrix"] if field else u""),
                     "qc_type": role, "origin": u"lab", "sample_point": u"", "coc_number": u"",
                     "duplicate_of": parent["client_sample_id"] if (parent and role in (
                         u"LFSM", u"LFSMD", u"Dup", u"MxB")) else u"", "results": []}
                try:
                    injected = [dict(r) for r in conn.execute(
                        "SELECT analyte, calc_conc, run_date FROM injection_results WHERE batch_id=? AND "
                        "injection_name=? AND role='analyte'", (ws_id, inj))]
                except sqlite3.Error as exc:
                    logger.warning("EDD: %s's injections cannot be read: %s", ws_id, exc)
                    injected = []
                for r in injected:
                    kw = n2k.get(r["analyte"], r["analyte"])
                    ref = per_kw.get(kw)
                    if ref is None:                         # an analyte the batch does not report
                        continue
                    conc = r["calc_conc"]
                    rl = ref.get("rl")
                    try:
                        detected = conc is not None and float(conc) >= float(rl)
                    except (TypeError, ValueError):
                        detected = conc is not None and float(conc) > 0
                    qc = {"measured": _fmt(conc, ref.get("precision"))}
                    for j in judged:
                        if n2k.get(j["analyte"], j["analyte"]) != kw or j["qc_type"] != role:
                            continue
                        kind = judged_kind(j["qc_level"], inj)
                        if kind is None:
                            continue
                        if j["applies_to"] and parent and j["applies_to"] != parent["id"]:
                            continue
                        if kind == u"rpd":
                            qc.update({"rpd": _fmt(j["value"], 1), "rpd_limit": _fmt(j["limit_high"], 0),
                                       "rpd_outside": u"inside" if j["passed"] else u"outside"})
                        elif role not in (u"MB", u"LRB", u"MxB"):
                            qc.update({"recovery": _fmt(j["value"], 0), "recovery_low": _fmt(j["limit_low"], 0),
                                       "recovery_high": _fmt(j["limit_high"], 0),
                                       "recovery_outside": u"inside" if j["passed"] else u"outside"})
                    run_date = judged_at = None
                    try:
                        run_date = datetime.strptime(r["run_date"][:10], "%Y-%m-%d").date()
                    except (TypeError, ValueError):
                        run_date = None
                    for j in judged:
                        if j["qc_type"] == role and j.get("created_at"):
                            try:
                                judged_at = datetime.strptime(j["created_at"][:19], "%Y-%m-%dT%H:%M:%S")
                            except ValueError:
                                judged_at = None
                            break
                    s["results"].append({
                        "keyword": kw, "cas": cas.get(kw) or u"", "role": u"target", "method": ref["method"],
                        "test_kind": u"initial", "acquired_at": None, "run_date": run_date,
                        "judged_at": judged_at, "worksheet": ws_id,
                        "value": qc["measured"] if detected else u"",
                        "detected": u"detected" if detected else u"not detected", "unit": ref["unit"],
                        "rl": ref.get("rl") or u"", "mdl": ref.get("mdl") or u"", "dilution_factor": 1,
                        "qualifiers": [] if detected else ["N.D."], "reportable": u"reported",
                        "prep_date": finished, "precision": ref.get("precision"), "qc": qc})
                if s["results"]:
                    out.append(s)
    finally:
        conn.close()
    return out


def collect(builder, batch_obj, client_obj, client_cfg):
    """The facts of a batch for the builder's (column-mapped) profile."""
    from bika.lims import api
    prof = builder._edd_profile or {}
    batch_id = batch_obj.getId()
    try:
        ars = batch_obj.getAnalysisRequests()
    except AttributeError:
        ars = []
    if not ars:
        try:
            from Products.CMFCore.utils import getToolByName
            cat = getToolByName(builder.portal, "senaite_catalog_sample")
            ars = [b.getObject() for b in cat(portal_type="AnalysisRequest", getBatchUID=batch_obj.UID())]
        except Exception:                                   # noqa: BLE001
            ars = []
    library = _library()
    batch_pid = builder._batch_method_profile(batch_obj)
    field = [s for s in (field_sample(builder, ar, batch_pid, library) for ar in ars) if s is not None]
    worksheets, seen = [], set()
    for ar in ars:
        for a in ar.getAnalyses(full_objects=True):
            try:
                ws = a.getWorksheet()
            except Exception:                               # noqa: BLE001
                ws = None
            if ws is not None and api.get_uid(ws) not in seen:
                seen.add(api.get_uid(ws))
                worksheets.append(ws)
    qc = lab_qc_samples(builder, worksheets, field, library)
    fields = dict((client_cfg or {}).get("fields") or {})
    return {"batch": {"id": batch_id, "sdg": builder._build_sdg(batch_id),
                      "title": batch_obj.Title() if hasattr(batch_obj, "Title") else batch_id},
            "client": fields, "samples": field + qc}


def generate(builder, batch_obj, client_obj, client_cfg):
    """(content, errors, filename): the delivery of a batch in the builder's
    column-mapped profile -- one file as text, several as a zip (bytes)."""
    from senaite.pfas import edd_delimited
    facts = collect(builder, batch_obj, client_obj, client_cfg)
    out = edd_delimited.write(builder._edd_profile, facts)
    builder._last_rows = sum(out["rows"].values())
    errors = list(out["errors"]) + list(getattr(builder, "_rounding_errors", []) or []) + list(
        getattr(builder, "_qualifier_errors", []) or [])
    if out["delivery"] is None:
        return (u"", errors, u"")
    name, data = out["delivery"]
    if len(out["files"]) == 1:
        return (data.decode("utf-8"), errors, name)
    return (data, errors, name)
