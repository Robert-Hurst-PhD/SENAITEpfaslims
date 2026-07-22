# -*- coding: utf-8 -*-
"""
PFAS Prepared Standards (@@pfas-prep-standards).

Manages in-house prepared reagents and standards.  Each record links to
a PrepLogbookDef revision (slug + revision number), stores the parent
reagents consumed (parentage), analyte concentrations, and generates an
internal certificate (HTML) at creation/update.

Complex nested data (parent_reagents, analyte_concentrations) is stored
in IAnnotations on the PreparedStandard object to avoid schema migration
overhead for list-of-dict fields.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os
import uuid
from datetime import date, datetime, timedelta

from zope.event import notify
from zope.lifecycleevent import ObjectModifiedEvent

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.browser.prepared_standards")

_ANN_PARENTS  = u"senaite.pfas.prepstd.parent_reagents"
_ANN_ANALYTES = u"senaite.pfas.prepstd.analyte_concentrations"

CERT_DIR = os.environ.get("PFAS_CERT_DIR", "/data/coa/certs")

STATUS_ACTIVE    = "active"
STATUS_EXHAUSTED = "exhausted"
STATUS_EXPIRED   = "expired"

# Vocabulary is OWNED by the PreparedStandard content type — single source of
# truth (was duplicated here). Imported so this view stays in lock-step.
from senaite.pfas.content.prepared_standard import STANDARD_TYPES  # noqa: F401


# ── Annotation helpers ─────────────────────────────────────────────────────────

def _get_ann(obj, key, default=None):
    try:
        ann = IAnnotations(obj)
        raw = ann.get(key)
        if raw:
            return json.loads(raw)
    except Exception:
        pass
    return default if default is not None else []


def _set_ann(obj, key, value):
    try:
        ann = IAnnotations(obj)
        ann[key] = json.dumps(value)
    except Exception as exc:
        logger.error("_set_ann %s: %s", key, exc)


# ── Date helpers ────────────────────────────────────────────────────────────────

def _date_str(d):
    if not d:
        return u""
    try:
        return d.strftime("%Y-%m-%d")
    except AttributeError:
        return unicode(d)[:10] if d else u""


def _parse_date(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _compute_expiry(prepared_date_str, expiry_days):
    """Return ISO expiry string = prepared_date + expiry_days."""
    d = _parse_date(prepared_date_str)
    if not d:
        d = date.today()
    try:
        exp = d + timedelta(days=int(expiry_days or 365))
    except (TypeError, ValueError):
        exp = date(d.year + 1, d.month, d.day)
    return exp.strftime("%Y-%m-%d")


def _is_expired(expiry_str):
    d = _parse_date(expiry_str)
    if not d:
        return False
    return d < date.today()


# ── Content object helpers ─────────────────────────────────────────────────────

def _get_folder(portal):
    folder = portal.get("pfas_prepared_standards")
    if folder is None:
        raise RuntimeError(
            "pfas_prepared_standards folder not found. Reinstall senaite.pfas."
        )
    return folder


def _obj_to_dict(obj):
    d = {
        "uid":             obj.getId(),
        "title":           obj.title or u"",
        "lot_number":      obj.lot_number or u"",
        "standard_type":   obj.standard_type or u"",
        "logbook_slug":    obj.logbook_slug or u"",
        "logbook_revision":obj.logbook_revision or 0,
        "logbook_title":   obj.logbook_title or u"",
        "prepared_by":     obj.prepared_by or u"",
        "prepared_date":   _date_str(obj.prepared_date),
        "expiry_date":     _date_str(obj.expiry_date),
        "expiry_notes":    obj.expiry_notes or u"",
        "storage_location":obj.storage_location or u"",
        "volume_prepared": obj.volume_prepared or u"",
        "status":          obj.status or STATUS_ACTIVE,
        "notes":           obj.notes or u"",
        "parent_reagents": _get_ann(obj, _ANN_PARENTS, []),
        "analyte_concentrations": _get_ann(obj, _ANN_ANALYTES, []),
    }
    # Auto-update expired status (transient read-time only — not written to DB here)
    if d["status"] == STATUS_ACTIVE and _is_expired(d["expiry_date"]):
        d["status"] = STATUS_EXPIRED
    return d


def _populate_obj(obj, data):
    obj.title = data.get("title") or u""
    obj.lot_number = data.get("lot_number") or u""
    obj.standard_type = data.get("standard_type") or u""
    obj.logbook_slug = data.get("logbook_slug") or u""
    try:
        obj.logbook_revision = int(data.get("logbook_revision") or 0)
    except (TypeError, ValueError):
        obj.logbook_revision = 0
    obj.logbook_title = data.get("logbook_title") or u""
    obj.prepared_by = data.get("prepared_by") or u""
    obj.prepared_date = _parse_date(data.get("prepared_date"))
    obj.expiry_date = _parse_date(data.get("expiry_date"))
    # Global-default assignment: an in-house prep with no stated expiry gets
    # prepared_date + the preset global period (Reagent Inventory → Expiry
    # Defaults). Parent-lot tightening is applied dynamically at read time.
    if obj.expiry_date is None and obj.prepared_date is not None:
        defaults = data.get("_expiry_defaults") or {}
        days = int(defaults.get("prepared_std_default_days", 365))
        obj.expiry_date = obj.prepared_date + timedelta(days=days)
        note = u"Expiry assigned from global default ({0} days from prep)".format(days)
        prev = data.get("expiry_notes") or u""
        data["expiry_notes"] = (prev + u"\n" + note).strip() if prev else note
    obj.expiry_notes = data.get("expiry_notes") or u""
    obj.storage_location = data.get("storage_location") or u""
    obj.volume_prepared = data.get("volume_prepared") or u""
    obj.notes = data.get("notes") or u""
    obj.status = data.get("status") or STATUS_ACTIVE

    # Store nested data in annotations
    _set_ann(obj, _ANN_PARENTS, data.get("parent_reagents") or [])
    _set_ann(obj, _ANN_ANALYTES, data.get("analyte_concentrations") or [])


def _save(portal, data):
    folder = _get_folder(portal)
    uid = (data.get("uid") or u"").strip() or None
    if uid and uid in folder:
        obj = folder[uid]
    else:
        uid = uid or uuid.uuid4().hex
        title = data.get("title") or u"Prepared Standard"
        folder.invokeFactory("PreparedStandard", id=uid, title=title)
        obj = folder[uid]
    try:
        from senaite.pfas.browser.reagents import get_expiry_defaults
        data["_expiry_defaults"] = get_expiry_defaults(portal)
    except Exception:
        pass
    _populate_obj(obj, data)
    try:
        obj.reindexObject()
    except Exception:
        pass
    try:
        notify(ObjectModifiedEvent(obj))
    except Exception:
        pass
    _write_cert(obj)
    return uid


def _get(portal, uid):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return None
    obj = folder.get(uid)
    return _obj_to_dict(obj) if obj else None


def effective_expiry_info(portal, d):
    """Inherited expiry: min(own expiry, every parent reagent lot's effective
    expiry). If a parent is tighter (earlier), the prep inherits it.
    Returns {"date": iso, "inherited_from": parent-name-or-empty}."""
    own = d.get("expiry_date") or ""
    eff, src = own, ""
    try:
        from senaite.pfas.browser.reagents import get_reagent_effective_expiry
        for p in d.get("parent_reagents") or []:
            pexp = get_reagent_effective_expiry(
                portal, p.get("lot", ""), p.get("name", ""))
            if pexp and (not eff or pexp < eff):
                eff, src = pexp, (p.get("name") or p.get("lot") or u"parent")
    except Exception:
        pass
    return {"date": eff, "inherited_from": src}


def _list(portal, q="", status_filter="", type_filter=""):
    try:
        folder = _get_folder(portal)
    except RuntimeError:
        return []
    q_lower = (q or "").lower().strip()
    results = []
    for obj in folder.objectValues():
        if obj.portal_type != "PreparedStandard":
            continue
        d = _obj_to_dict(obj)
        eff = effective_expiry_info(portal, d)
        d["effective_expiry"] = eff["date"]
        d["expiry_inherited_from"] = eff["inherited_from"]
        # a tighter parent expiry can also expire the prep
        if d["status"] == STATUS_ACTIVE and _is_expired(eff["date"]):
            d["status"] = STATUS_EXPIRED
        if status_filter and d["status"] != status_filter:
            continue
        if type_filter and d["standard_type"] != type_filter:
            continue
        if q_lower:
            searchable = u" ".join([
                d.get("title", ""),
                d.get("lot_number", ""),
                d.get("logbook_title", ""),
                d.get("prepared_by", ""),
            ]).lower()
            if q_lower not in searchable:
                continue
        results.append(d)
    results.sort(key=lambda x: x.get("prepared_date", "") or "", reverse=True)
    return results


# ── Internal certificate ────────────────────────────────────────────────────────

def _write_cert(obj):
    """Generate and store the internal certificate HTML for a prepared standard."""
    try:
        d = _obj_to_dict(obj)
        from senaite.pfas.print_settings import get_signoff_signers
        from bika.lims import api as _api
        html = _render_cert_html(d, get_signoff_signers(_api.get_portal()))
        path = os.path.join(CERT_DIR, "{}.html".format(obj.getId()))
        if not os.path.isdir(CERT_DIR):
            os.makedirs(CERT_DIR)
        with open(path, "w") as fh:
            fh.write(html.encode("utf-8") if isinstance(html, unicode) else html)
    except Exception as exc:
        logger.error("_write_cert %s: %s", obj.getId(), exc)


def _render_cert_html(d, signers=None):
    """Return the internal certificate HTML string for a prepared-standard dict.

    `signers` (optional) = {"qao": staff-dict-or-None, "director": ...} from
    print settings; drives the 3-tier QA attestation. Names only (this cert is
    written to a standalone file, so signature-image URLs are not embedded)."""
    signers = signers or {}
    _qao = signers.get("qao") or {}
    _dir = signers.get("director") or {}
    qao_name = _qao.get("fullname") or u"—"
    director_name = _dir.get("fullname") or u"—"
    rows_html = u""
    for row in d.get("analyte_concentrations") or []:
        rows_html += (
            u"<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
                row.get("analyte", ""), row.get("concentration", ""),
                row.get("unit", "")
            )
        )
    parents_html = u""
    for p in d.get("parent_reagents") or []:
        parents_html += (
            u"<tr><td>{}</td><td>{}</td><td>{}</td><td>{} {}</td></tr>".format(
                p.get("name", ""), p.get("supplier", ""), p.get("lot", ""),
                p.get("qty", ""), p.get("unit", "")
            )
        )
    return u"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Internal Certificate — {title}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 12px; margin: 30px 40px; color: #222; }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .cert-meta {{ background: #f4f6f8; padding: 12px 16px; border-radius: 6px;
               margin-bottom: 20px; display: grid; grid-template-columns: 1fr 1fr; gap: 6px 24px; }}
  .cert-meta dt {{ font-weight: 700; font-size: 11px; text-transform: uppercase; color: #555; }}
  .cert-meta dd {{ margin: 0 0 6px; }}
  table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  th {{ background: #e8edf2; padding: 6px 10px; text-align: left; font-size: 11px;
        text-transform: uppercase; letter-spacing: .04em; }}
  td {{ padding: 5px 10px; border-bottom: 1px solid #ddd; }}
  .footer {{ margin-top: 40px; padding-top: 10px; border-top: 1px solid #ccc;
             font-size: 11px; color: #888; }}
  .sig-block {{ margin-top: 30px; display: flex; gap: 60px; }}
  .sig-block div {{ border-top: 1px solid #333; padding-top: 4px; min-width: 160px; font-size: 11px; }}
  .signoff {{ margin-top: 28px; border: 1px solid #000; border-radius: 6px; padding: 12px 14px; }}
  .signoff-title {{ font-size: 11px; font-weight: 700; letter-spacing: .04em;
    text-transform: uppercase; color: #444; margin-bottom: 6px; }}
  .signoff-tbl {{ width: 100%; border-collapse: collapse; font-size: 11px; margin: 0; }}
  .signoff-tbl td {{ padding: 9px 8px; border-top: 1px solid #eee; vertical-align: bottom; }}
  .signoff-tbl .r {{ width: 92px; font-weight: 600; color: #555; white-space: nowrap; }}
  .signoff-tbl .dt {{ width: 150px; white-space: nowrap; color: #555; }}
  .signoff-tbl .ln {{ display: inline-block; min-width: 90px; border-bottom: 1px solid #888; }}
</style>
</head>
<body>
<h1>Internal Certificate of Preparation</h1>
<p style="margin-top:2px;color:#555;font-size:11px">PFAS Laboratory — {title}</p>
<dl class="cert-meta">
  <div><dt>Lot Number</dt><dd>{lot_number}</dd></div>
  <div><dt>Standard Type</dt><dd>{standard_type}</dd></div>
  <div><dt>Date Prepared</dt><dd>{prepared_date}</dd></div>
  <div><dt>Expiry Date</dt><dd>{expiry_date}</dd></div>
  <div><dt>Prepared By</dt><dd>{prepared_by}</dd></div>
  <div><dt>Storage Location</dt><dd>{storage_location}</dd></div>
  <div><dt>Volume / Amount</dt><dd>{volume_prepared}</dd></div>
  <div><dt>Prep Logbook</dt><dd>{logbook_title} (Rev {logbook_revision})</dd></div>
</dl>

<h2 style="font-size:13px;margin-bottom:8px">Analyte Concentrations</h2>
<table>
  <thead><tr><th>Analyte</th><th>Concentration</th><th>Unit</th></tr></thead>
  <tbody>{analyte_rows}</tbody>
</table>

<h2 style="font-size:13px;margin-bottom:8px">Parent Reagents (Parentage)</h2>
<table>
  <thead><tr><th>Reagent Name</th><th>Supplier</th><th>Lot Number</th><th>Amount Used</th></tr></thead>
  <tbody>{parent_rows}</tbody>
</table>

{expiry_note_section}

<div class="signoff">
  <div class="signoff-title">Quality Assurance Documentation</div>
  <table class="signoff-tbl">
    <tr><td class="r">Prepared&nbsp;by</td>
        <td>This standard was prepared by <strong>{prepared_by}</strong>.</td>
        <td class="dt">Date: {prepared_date}</td></tr>
    <tr><td class="r">Verified&nbsp;by</td>
        <td>Reviewed and verified by <strong>{qao_name}</strong>, Quality Assurance Officer.</td>
        <td class="dt">Date: <span class="ln">&nbsp;</span></td></tr>
    <tr><td class="r">Authorized&nbsp;by</td>
        <td>Authorized by <strong>{director_name}</strong>, Laboratory Director.</td>
        <td class="dt">Date: <span class="ln">&nbsp;</span></td></tr>
  </table>
</div>
<div class="footer">
  Generated automatically by senaite.pfas on {generated_date}.
  This document is an INTERNAL record and is not a manufacturer CoA.
</div>
</body>
</html>""".format(
        title=d.get("title", ""),
        lot_number=d.get("lot_number", ""),
        standard_type=d.get("standard_type", ""),
        prepared_date=d.get("prepared_date", ""),
        expiry_date=d.get("expiry_date", ""),
        prepared_by=d.get("prepared_by", "") or u"—",
        qao_name=qao_name,
        director_name=director_name,
        storage_location=d.get("storage_location", ""),
        volume_prepared=d.get("volume_prepared", ""),
        logbook_title=d.get("logbook_title", ""),
        logbook_revision=d.get("logbook_revision", ""),
        analyte_rows=rows_html or u"<tr><td colspan='3'>No analytes recorded</td></tr>",
        parent_rows=parents_html or u"<tr><td colspan='4'>No parent reagents recorded</td></tr>",
        expiry_note_section=(
            u"<p style='font-size:11px;color:#856404;background:#fff3cd;padding:8px 12px;"
            u"border-radius:4px'><strong>Expiry Note:</strong> {}</p>".format(
                d.get("expiry_notes", ""))
            if d.get("expiry_notes") else u""
        ),
        generated_date=date.today().strftime("%Y-%m-%d"),
    )


# ── View ──────────────────────────────────────────────────────────────────────

class PFASPrepStandardsView(BrowserView):
    """PFAS Prepared Standards — inventory, create, view certificate."""

    template = ViewPageTemplateFile("templates/prep_standards.pt")

    def __call__(self):
        action = self.request.form.get("action", "")
        if action == "cert":
            return self._serve_cert()
        if self.request.method == "POST":
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action in ("add", "edit"):
                return self._handle_upsert()
            if action == "status":
                return self._handle_status()
            if action == "delete":
                return self._handle_delete()
        return self.template()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _self_url(self):
        return "{}/@@pfas-prep-standards".format(self.context.absolute_url())

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    # ── Template data ─────────────────────────────────────────────────────

    def prepared_standards(self):
        return _list(
            self._portal(),
            q=self.request.form.get("q", ""),
            status_filter=self.request.form.get("status", ""),
            type_filter=self.request.form.get("type", ""),
        )

    def prep_logbooks(self):
        """Return active/draft logbooks for the prep form selector."""
        from senaite.pfas.browser.prep_logbooks import _get_active_families
        try:
            return _get_active_families(self._portal())
        except Exception as exc:
            logger.error("prep_logbooks: %s", exc)
            return []

    def standard_types(self):
        return STANDARD_TYPES

    def edit_uid(self):
        return self.request.form.get("edit_uid", "")

    def edit_data_json(self):
        uid = self.edit_uid()
        if uid:
            rec = _get(self._portal(), uid)
            if rec:
                return json.dumps(rec)
        return "null"

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def expiry_class(self, rec):
        # colour by the EFFECTIVE (possibly parent-inherited) expiry
        exp = rec.get("effective_expiry") or rec.get("expiry_date", "")
        if not exp:
            return ""
        try:
            d = datetime.strptime(exp, "%Y-%m-%d").date()
            today = date.today()
            if d < today:
                return "exp-expired"
            if (d - today).days <= 30:
                return "exp-warning"
        except (ValueError, TypeError):
            pass
        return ""

    # ── Action handlers ───────────────────────────────────────────────────

    def _handle_upsert(self):
        f = self.request.form
        title = f.get("title", "").strip()
        lot = f.get("lot_number", "").strip()
        if not title or not lot:
            return self._redirect("{0}?error=Title+and+Lot+Number+required".format(
                self._self_url()))

        # Parse parent reagents from JSON form field
        try:
            parents = json.loads(f.get("parent_reagents_json", "[]") or "[]")
        except (ValueError, TypeError):
            parents = []

        # Parse analyte concentrations from JSON form field
        try:
            analytes = json.loads(f.get("analyte_concentrations_json", "[]") or "[]")
        except (ValueError, TypeError):
            analytes = []

        # Compute default expiry if not supplied
        logbook_slug = f.get("logbook_slug", "").strip()
        expiry_date = f.get("expiry_date", "").strip()
        expiry_days = 365
        logbook_title = f.get("logbook_title", "").strip()
        logbook_revision = f.get("logbook_revision", "1")
        if logbook_slug and not expiry_date:
            # Look up default_expiry_days from the logbook
            try:
                from senaite.pfas.browser.prep_logbooks import _list as lb_list
                lbs = lb_list(self._portal(), slug=logbook_slug, status_filter="active")
                if not lbs:
                    lbs = lb_list(self._portal(), slug=logbook_slug)
                if lbs:
                    # Sort by revision desc, take highest
                    lbs.sort(key=lambda x: -x["revision"])
                    expiry_days = lbs[0].get("default_expiry_days") or 365
                    if not logbook_title:
                        logbook_title = lbs[0].get("title", "")
                    if not logbook_revision:
                        logbook_revision = lbs[0].get("revision", 1)
            except Exception as exc:
                logger.error("logbook lookup: %s", exc)
            prepared_date = f.get("prepared_date", "").strip()
            expiry_date = _compute_expiry(prepared_date, expiry_days)

        data = {
            "uid":              f.get("uid", "").strip() or None,
            "title":            title,
            "lot_number":       lot,
            "standard_type":    f.get("standard_type", "").strip(),
            "logbook_slug":     logbook_slug,
            "logbook_revision": logbook_revision,
            "logbook_title":    logbook_title,
            "prepared_by":      f.get("prepared_by", "").strip(),
            "prepared_date":    f.get("prepared_date", "").strip(),
            "expiry_date":      expiry_date,
            "expiry_notes":     f.get("expiry_notes", "").strip(),
            "storage_location": f.get("storage_location", "").strip(),
            "volume_prepared":  f.get("volume_prepared", "").strip(),
            "notes":            f.get("notes", "").strip(),
            "status":           f.get("status", STATUS_ACTIVE),
            "parent_reagents":  parents,
            "analyte_concentrations": analytes,
        }
        uid = _save(self._portal(), data)
        return self._redirect("{0}?ok=Prepared+standard+saved".format(self._self_url()))

    def _handle_status(self):
        uid = self.request.form.get("uid", "").strip()
        new_status = self.request.form.get("new_status", "").strip()
        rec = _get(self._portal(), uid)
        if not rec:
            return self._redirect("{0}?error=Not+found".format(self._self_url()))
        rec["status"] = new_status
        _save(self._portal(), rec)
        return self._redirect("{0}?ok=Status+updated".format(self._self_url()))

    def _handle_delete(self):
        uid = self.request.form.get("uid", "").strip()
        try:
            folder = _get_folder(self._portal())
            if uid in folder:
                folder.manage_delObjects([uid])
                # Remove cert file
                cert_path = os.path.join(CERT_DIR, "{}.html".format(uid))
                if os.path.exists(cert_path):
                    os.remove(cert_path)
                return self._redirect("{0}?ok=Deleted".format(self._self_url()))
        except Exception as exc:
            logger.error("delete prepared standard: %s", exc)
        return self._redirect("{0}?error=Not+found".format(self._self_url()))

    def _serve_cert(self):
        """Serve the internal certificate HTML file for a given uid."""
        uid = self.request.form.get("uid", "").strip()
        cert_path = os.path.join(CERT_DIR, "{}.html".format(uid))
        if not os.path.exists(cert_path):
            # Regenerate on-demand
            rec = _get(self._portal(), uid)
            if not rec:
                self.request.response.setStatus(404)
                return "Certificate not found"
            from senaite.pfas.print_settings import get_signoff_signers
            html = _render_cert_html(rec, get_signoff_signers(self._portal()))
        else:
            with open(cert_path, "r") as fh:
                html = fh.read()
        self.request.response.setHeader("Content-Type", "text/html; charset=utf-8")
        return html
