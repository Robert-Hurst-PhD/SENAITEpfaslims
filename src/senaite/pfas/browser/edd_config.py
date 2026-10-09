# -*- coding: utf-8 -*-
"""
The EDD export's pages. Python 2.7.

    @@pfas-edd-config          the profiles and their settings (?profile=<id>)
    @@pfas-edd-client-config   a client's EDD settings: on/off, its profile and
                               the fields that profile asks for
    @@pfas-edd-export          the EDD file of a batch (or ?preview=1: its checks)
    @@pfas-edd-batches         batch EDD dashboard; ?batch_id= the per-sample
                               sample-type code editor

Every setting belongs to a profile: the settings page edits the selected
profile, and its forms (labels, hints, value lists) are the profile's
format's own (edd_profiles). Manager, LabManager, Owner.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import re

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import edd_profiles
from senaite.pfas import edd_store as store
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.browser.edd_config")


def _require_manager(context, request):
    # one gate, resolved at the portal
    from senaite.pfas.browser.perms import require_manager
    return require_manager(context, request)


def _portal(context):
    return context.portal_url.getPortalObject()


def _safe(key):
    return re.sub(r"[^A-Za-z0-9_]", "_", key)


def _methods(portal, codes):
    """The lab's methods (the method profiles), and any the profile codes."""
    out = []
    try:
        from senaite.pfas.method_profile_store import list_method_ids
        out = list(list_method_ids(portal))
    except Exception:                                        # noqa: BLE001
        out = []
    for mid in sorted(codes or {}):
        if mid not in out:
            out.append(mid)
    return out


# ── Profiles and their settings ──────────────────────────────────────────────

def weight_rows(profile):
    """[{matrix, code, basis}] for every matrix the profile maps: the basis
    the lab reports it on ("" until chosen)."""
    wb = profile.get("weight_basis_map") or {}
    return [{"matrix": m, "code": c, "basis": wb.get(m, u"")}
            for m, c in sorted((profile.get("matrix_map") or {}).items())]


def read_weight_basis(form, allowed):
    """{matrix: basis} from the posted wb_matrix / wb_basis pairs (in
    order), keeping only the format's codes; None when the form had none."""
    def _list(v):
        if v is None:
            return None
        return list(v) if isinstance(v, (list, tuple)) else [v]
    keys, vals = _list(form.get("wb_matrix")), _list(form.get("wb_basis"))
    if keys is None or vals is None or len(keys) != len(vals):
        return None
    return dict((k, v) for k, v in zip(keys, vals) if k and v in allowed)


class PFASEDDConfigView(BrowserView):
    """The selected profile's tabs: Defaults, Methods, Analytes, Qualifiers,
    QC types, Value lists, Test export, Profiles."""

    template = ViewPageTemplateFile("templates/edd_config.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden: Manager, LabManager, or Owner role required")
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    # selection
    def portal_url(self):
        return _portal(self.context).absolute_url()

    def profiles(self):
        return store.get_edd_profiles(_portal(self.context))

    def profile_id(self):
        pid = self.request.get("profile") or store.DEFAULT_PROFILE_ID
        return pid if pid in self.profiles() else store.DEFAULT_PROFILE_ID

    def profile(self):
        return self.profiles()[self.profile_id()]

    def fmt(self):
        return edd_profiles.format_of(self.profile())

    def active_tab(self):
        return self.request.get("tab", "defaults")

    def profile_options(self):
        return [{"id": k, "name": v.get("name", k)} for k, v in sorted(self.profiles().items())]

    def _list(self, name):
        return sorted((store.section(self.profile(), "value_lists") or {}).get(name) or [])

    def _field(self, spec, current):
        options = list(spec.get("options") or [])
        if spec.get("list"):
            options = self._list(spec["list"])
        if current and options and current not in options:
            options = [current] + options      # never hide what is stored
        return {"key": spec["key"], "name": _safe(spec["key"]), "label": spec.get("label", spec["key"]),
                "hint": spec.get("hint", u""), "value": current or u"", "options": options}

    # tabs
    def default_fields(self):
        values = store.section(self.profile(), "defaults") or {}
        return [self._field(s, values.get(s["key"], u"")) for s in getattr(self.fmt(), "DEFAULT_FIELDS", [])]

    def method_rows(self):
        codes = store.section(self.profile(), "method_codes") or {}
        out = []
        for mid in _methods(_portal(self.context), codes):
            c = codes.get(mid) or {}
            out.append({"method_id": mid,
                        "fields": [dict(self._field(s, c.get(s["key"], u"")),
                                        name="%s__%s" % (_safe(mid), _safe(s["key"])))
                                   for s in getattr(self.fmt(), "METHOD_FIELDS", [])]})
        return out

    def analyte_labels(self):
        return getattr(self.fmt(), "ANALYTE_LABELS", {"code": u"Code", "name": u"Name"})

    def analyte_rows(self):
        prof = self.profile()
        cas = store.profile_analyte_cas(prof)
        naming = store.section(prof, "analyte_naming") or {}
        guidance = getattr(self.fmt(), "analyte_guidance", lambda k, c: u"")
        rows = []
        for kw in sorted(cas):
            entry = cas[kw]
            code = entry.get("cas_no") or u""
            blocking = not code or code.upper() == "PLACEHOLDER"
            rows.append({"keyword": kw, "safe": _safe(kw), "code": code,
                         "override": (naming.get(kw) or {}).get("code_override", u""),
                         "name": entry.get("parameter_name") or u"",
                         "note": entry.get("override_note") or u"",
                         "tic": bool((naming.get(kw) or {}).get("tic")),
                         "blocking": blocking, "guidance": guidance(kw, code)})
        return rows

    def blocking_count(self):
        return sum(1 for r in self.analyte_rows() if r["blocking"])

    def qualifier_rows(self):
        return store.section(self.profile(), "qualifier_map") or []

    def qc_type_rows(self):
        return store.section(self.profile(), "qc_type_map") or []

    def qualifier_codes(self):
        return self._list(getattr(self.fmt(), "QUALIFIER_LIST", ""))

    def qc_type_codes(self):
        return self._list(getattr(self.fmt(), "QC_TYPE_LIST", ""))

    def value_list_counts(self):
        lists = store.section(self.profile(), "value_lists") or {}
        return [{"name": k.replace("_", " "), "n": len(v)} for k, v in sorted(lists.items())
                if isinstance(v, list)]

    def value_list_refreshed(self):
        lists = store.section(self.profile(), "value_lists") or {}
        return lists.get("last_refresh") or u""

    def value_list_source(self):
        return getattr(self.fmt(), "VALUE_LIST_SOURCE", None)

    def profile_rows(self):
        out = []
        for k, v in sorted(self.profiles().items()):
            out.append({
                "id": k, "name": v.get("name", k), "base": v.get("base", ""),
                "state": v.get("state", ""),
                "n_columns": len(v.get("columns") or []),
                "columns_text": "\n".join(v.get("columns") or []),
                "matrix_map_json": json.dumps(v.get("matrix_map") or {}, indent=1, sort_keys=True),
                "aliases_json": json.dumps(v.get("aliases") or {}, indent=1, sort_keys=True),
                "weight_rows": weight_rows(v),
            })
        return out

    def weight_bases(self):
        return list(getattr(self.fmt(), "WEIGHT_BASES", ()))

    # saving: every section is the selected profile's
    def _handle_post(self):
        form = self.request.form
        portal = _portal(self.context)
        section = form.get("section", "")
        pid = self.profile_id()
        prof = self.profile()

        if section == "profiles":
            act = form.get("edd_action", "")
            if act == "clone":
                src = form.get("source_id") or store.DEFAULT_PROFILE_ID
                name = (form.get("new_name") or "").strip() or "New EDD profile"
                new_id = re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")
                store.clone_edd_profile(portal, src, new_id, name)
                pid = new_id
            elif act == "save":
                target = form.get("profile_id", "")
                p = self.profiles().get(target)
                if p is not None:
                    p["name"] = form.get("name") or p.get("name") or target
                    p["state"] = (form.get("state") or p.get("state") or "").strip()
                    cols = [c.strip() for c in (form.get("columns") or "").splitlines() if c.strip()]
                    if cols:
                        p["columns"] = cols
                    wb = read_weight_basis(form, self.weight_bases())
                    if wb is not None:
                        p["weight_basis_map"] = wb
                    for field, key in (("matrix_map_json", "matrix_map"), ("aliases_json", "aliases")):
                        raw = form.get(field)
                        if raw and raw.strip():
                            try:
                                p[key] = json.loads(raw)
                            except (ValueError, TypeError):
                                pass          # bad JSON keeps the prior value
                    store.save_edd_profile(portal, target, p)
                    pid = target
            self.request.response.redirect("%s/@@pfas-edd-config?profile=%s&tab=profiles"
                                           % (portal.absolute_url(), pid))
            return u""

        if section == "defaults":
            values = store.section(prof, "defaults") or {}
            for s in getattr(self.fmt(), "DEFAULT_FIELDS", []):
                if _safe(s["key"]) in form:
                    values[s["key"]] = (form.get(_safe(s["key"])) or u"").strip()
            store.save_profile_section(portal, pid, "defaults", values)
        elif section == "methods":
            codes = store.section(prof, "method_codes") or {}
            for mid in _methods(portal, codes):
                c = dict(codes.get(mid) or {}, method_id=mid)
                for s in getattr(self.fmt(), "METHOD_FIELDS", []):
                    name = "%s__%s" % (_safe(mid), _safe(s["key"]))
                    if name in form:
                        c[s["key"]] = (form.get(name) or u"").strip()
                codes[mid] = c
            store.save_profile_section(portal, pid, "method_codes", codes)
        elif section == "analytes":
            naming = store.section(prof, "analyte_naming") or {}
            for kw in store.profile_analyte_cas(prof):
                s = _safe(kw)
                if ("name_" + s) not in form:
                    continue
                naming[kw] = {"code_override": (form.get("code_" + s) or u"").strip(),
                              "parameter_name": (form.get("name_" + s) or u"").strip(),
                              "note": (form.get("note_" + s) or u"").strip()}
                if form.get("tic_" + s):
                    naming[kw]["tic"] = True
            store.save_profile_section(portal, pid, "analyte_naming", naming)
        elif section in ("qualifiers", "qc_types"):
            key = "qualifier_map" if section == "qualifiers" else "qc_type_map"
            try:
                ours = "our_qualifier" if key == "qualifier_map" else "our_qc_type"
                rows = [r for r in json.loads(form.get("rows_json") or "[]") if (r.get(ours) or u"").strip()]
            except ValueError:
                return self._back(section, error=u"The rows could not be read; nothing saved.")
            store.save_profile_section(portal, pid, key, rows)
        elif section == "value_lists":
            uploaded = self.request.get("upload")
            if not (uploaded and hasattr(uploaded, "read") and uploaded.filename):
                return self._back(section, error=u"Choose the file first.")
            result = store.refresh_value_lists(portal, pid, uploaded.read())
            if result.get("errors") and not result.get("updated"):
                return self._back(section, error=u"; ".join(result["errors"]))
            return self._back(section, ok=u"Refreshed: " + u", ".join(result.get("updated") or []))
        else:
            return self._back("defaults", error=u"Unknown section.")
        return self._back(section, ok=u"Saved.")

    def _back(self, tab, ok=u"", error=u""):
        from six.moves.urllib.parse import urlencode
        q = {"profile": self.profile_id(), "tab": tab}
        if ok:
            q["ok"] = ok.encode("utf-8")
        if error:
            q["error"] = error.encode("utf-8")
        self.request.response.redirect("%s/@@pfas-edd-config?%s" % (self.portal_url(), urlencode(q)))
        return u""

    def message(self):
        return {"ok": self.request.get("ok", u""), "error": self.request.get("error", u"")}


# ── A client's EDD settings ─────────────────────────────────────────────────

class PFASEDDClientConfigView(BrowserView):
    """On/off, the client's profile and the fields that profile asks for."""

    template = ViewPageTemplateFile("templates/edd_client_config.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden")
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def settings(self):
        return store.get_client_settings(self.context)

    def profile(self):
        return store.get_edd_profile_for_client(_portal(self.context), self.settings())[1]

    def profile_options(self):
        profs = store.get_edd_profiles(_portal(self.context))
        return [{"id": k, "name": v.get("name", k)} for k, v in sorted(profs.items())]

    def client_fields(self):
        prof = self.profile()
        lists = store.section(prof, "value_lists") or {}
        values = self.settings().get("fields") or {}
        out = []
        for spec in store.section(prof, "client_fields") or []:
            current = values.get(spec["key"], u"") or u""
            options = sorted(lists.get(spec.get("list")) or []) if spec.get("list") else []
            if current and options and current not in options:
                options = [current] + options
            out.append({"key": spec["key"], "name": "field_" + _safe(spec["key"]),
                        "label": spec.get("label", spec["key"]), "hint": spec.get("hint", u""),
                        "value": current, "options": options})
        return out

    def _handle_post(self):
        form = self.request.form
        cfg = self.settings()
        cfg["edd_enabled"] = bool(form.get("edd_enabled"))
        # an unchecked box is not submitted
        cfg["per_report_override_default"] = bool(form.get("per_report_override_default"))
        cfg["edd_profile"] = (form.get("edd_profile") or store.DEFAULT_PROFILE_ID).strip()
        fields = dict(cfg.get("fields") or {})
        for f in self.client_fields():
            if f["name"] in form:
                fields[f["key"]] = (form.get(f["name"]) or u"").strip()
        cfg["fields"] = fields
        store.save_client_settings(self.context, cfg)
        self.request.response.redirect(self.context.absolute_url() + "/@@pfas-edd-client-config?saved=1")
        return u""

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def saved(self):
        return bool(self.request.get("saved"))


# ── EDD export ────────────────────────────────────────────────────────────────

class PFASEDDExportView(BrowserView):
    """
    GET @@pfas-edd-export?batch_id=B-001   the file (JSON report if blocked)
    GET ...&preview=1                      the checks only (JSON)
    """

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden")
        batch_id = self.request.get("batch_id", "")
        preview = bool(self.request.get("preview"))
        if not batch_id:
            return json.dumps({"error": "batch_id is required"})
        portal = _portal(self.context)
        batch_obj = None
        try:
            from senaite.pfas.batch_ref import get_batch
            batch_obj = get_batch(portal, batch_id)
        except Exception as exc:                            # noqa: BLE001
            logger.error("Cannot look up batch %s: %s", batch_id, exc)
        if batch_obj is None:
            return json.dumps({"error": "Batch not found: " + batch_id})

        client_obj = None
        try:
            client_obj = batch_obj.getClient()
        except AttributeError:
            pass
        if client_obj is None:
            # a batch is not always client-linked: its first sample's client
            try:
                cat = getToolByName(portal, "senaite_catalog_sample")
                brains = cat(portal_type="AnalysisRequest", getBatchUID=batch_obj.UID())
                if brains:
                    client_obj = brains[0].getObject().getClient()
            except Exception:                                # noqa: BLE001
                client_obj = None

        from senaite.pfas.edd_builder import EDDBuilder
        builder = EDDBuilder(portal)
        per_report = not bool(self.request.get("suppress"))
        csv_str, errors, filename = builder.generate_from_batch(
            batch_obj, client_obj=client_obj, per_report_override=per_report)
        blocking = [e for e in errors if e.get("type") == "BLOCKING"]
        report_text = builder.format_validation_report(errors)

        if preview:
            return json.dumps({
                "batch_id": batch_id, "filename": filename,
                "row_count": csv_str.count("\r\n") - 1 if csv_str else 0,
                "blocking_count": len(blocking), "error_count": len(errors),
                "validation_report": report_text, "has_csv": bool(csv_str)})
        if blocking:
            self.request.response.setHeader("Content-Type", "application/json")
            return json.dumps({
                "error": "BLOCKING validation errors — cannot generate EDD",
                "blocking_errors": [e["message"] for e in blocking],
                "validation_report": report_text})
        self.request.response.setHeader("Content-Type", "text/csv; charset=utf-8")
        self.request.response.setHeader(
            "Content-Disposition", "attachment; filename=\"{0}\"".format(filename or (batch_id + "_EDD.csv")))
        if isinstance(csv_str, unicode):                     # noqa: F821
            return csv_str.encode("utf-8")
        return csv_str


# ── Batch EDD dashboard + per-sample sample-type codes ───────────────────────

class PFASEDDBatchesView(BrowserView):
    """
    Without ?batch_id: recent batches with their EDD state and downloads.
    With ?batch_id=X: each sample's sample-type code (override) for the batch.
    POST: saves the overrides.
    """

    template = ViewPageTemplateFile("templates/edd_batches.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden")
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def _handle_post(self):
        from senaite.pfas.browser.edd_publish import set_ar_sample_type
        portal = _portal(self.context)
        cat = getToolByName(portal, "senaite_catalog_sample")
        batch_id = self.request.form.get("batch_id", "")
        saved = 0
        for key, value in self.request.form.items():
            if key.startswith("sampletype_") and value:
                ar_id = key[len("sampletype_"):]
                try:
                    brains = cat(portal_type="AnalysisRequest", getId=ar_id)
                    if brains:
                        set_ar_sample_type(brains[0].getObject(), value.strip().upper())
                        saved += 1
                except Exception as exc:                     # noqa: BLE001
                    logger.warning("Cannot save the sample-type code for %s: %s", ar_id, exc)
        self.request.response.redirect("{0}/@@pfas-edd-batches?batch_id={1}&saved={2}".format(
            self.portal_url(), batch_id, saved))
        return ""

    def portal_url(self):
        return _portal(self.context).absolute_url()

    def batch_id(self):
        return self.request.get("batch_id", "")

    def saved_count(self):
        try:
            return int(self.request.get("saved", 0))
        except (ValueError, TypeError):
            return 0

    def _batch(self, bid):
        try:
            from senaite.pfas.batch_ref import get_batch
            return get_batch(_portal(self.context), bid)
        except Exception:                                    # noqa: BLE001
            return None

    def recent_batches(self):
        """The 60 newest batches with their EDD state."""
        from senaite.pfas.browser.edd_publish import get_batch_edd
        portal = _portal(self.context)
        base = self.portal_url()
        from bika.lims import api
        # every batch, wherever it lives (a client's batch is in its folder)
        batches = sorted((b.getObject() for b in api.search({"portal_type": str("Batch")})),
                         key=lambda b: b.created(), reverse=True)[:60]
        rows = []
        for batch_obj in batches:
            try:
                bid = batch_obj.getId()
                client_obj = None
                try:
                    client_obj = batch_obj.getClient()
                except AttributeError:
                    pass
                cfg = store.get_client_settings(client_obj) if client_obj else {}
                stored = get_batch_edd(batch_obj)
                rows.append({
                    "batch_id": bid, "title": batch_obj.Title() or bid,
                    "created": batch_obj.created().strftime("%Y-%m-%d"),
                    "client_title": client_obj.Title() if client_obj else "",
                    "edd_enabled": bool(cfg.get("edd_enabled")),
                    "has_edd": stored is not None,
                    "edd_generated": (stored or {}).get("generated", "")[:10],
                    "edd_filename": (stored or {}).get("filename", ""),
                    "edd_error_count": (stored or {}).get("error_count", 0),
                    "edd_blocking": (stored or {}).get("blocking_count", 0),
                    "download_url": "{0}/@@pfas-edd-export?batch_id={1}".format(base, bid),
                    "preview_url": "{0}/@@pfas-edd-export?batch_id={1}&preview=1".format(base, bid),
                    "sampletype_url": "{0}/@@pfas-edd-batches?batch_id={1}".format(base, bid),
                })
            except Exception as exc:                         # noqa: BLE001
                logger.warning("EDD batch dashboard: %s", exc)
        return rows

    def _client_cfg(self, batch_obj):
        try:
            client_obj = batch_obj.getClient()
        except AttributeError:
            client_obj = None
        return store.get_client_settings(client_obj) if client_obj else {}

    def batch_sample_types(self):
        """Each sample's sample-type code for the batch's editor."""
        from senaite.pfas.browser.edd_publish import get_ar_sample_type
        bid = self.batch_id()
        batch_obj = self._batch(bid) if bid else None
        if batch_obj is None:
            return []
        default_type = store.client_field(self._client_cfg(batch_obj), "default_sample_type", "GW")
        cat = getToolByName(_portal(self.context), "senaite_catalog_sample")
        rows = []
        for brain in cat(portal_type="AnalysisRequest", getBatchUID=batch_obj.UID()):
            try:
                ar = brain.getObject()
                st = ar.getSampleType()
                rows.append({"ar_id": ar.getId(), "ar_title": ar.Title() or ar.getId(),
                             "senaite_sample_type": st.Title() if st else "",
                             "sample_type_code": get_ar_sample_type(ar, default=default_type),
                             "field_name": "sampletype_{0}".format(ar.getId())})
            except Exception as exc:                         # noqa: BLE001
                logger.warning("EDD sample-type editor: %s", exc)
        return rows

    def sample_type_options(self):
        """The sample-type codes of the batch's client's profile."""
        bid = self.batch_id()
        batch_obj = self._batch(bid) if bid else None
        cfg = self._client_cfg(batch_obj) if batch_obj is not None else {}
        prof = store.get_edd_profile_for_client(_portal(self.context), cfg)[1]
        return (store.section(prof, "value_lists") or {}).get("sample_types") or []
