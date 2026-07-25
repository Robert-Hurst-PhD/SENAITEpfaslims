# -*- coding: utf-8 -*-
"""
PFAS New-Method Wizard -- association-driven, 10-step flow.

Each step provides inline selection/association rather than just linking
to SENAITE admin pages.  State is persisted in ZODB portal annotations
so the user can return to a wizard in progress.

URL pattern:
  GET  @@pfas-method-wizard              -- landing page
  POST @@pfas-method-wizard?action=new   -- create session, redirect step 1
  GET  @@pfas-method-wizard?wid=X&step=N -- render step N
  POST @@pfas-method-wizard?wid=X&step=N -- process step N, advance

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import uuid

from persistent.mapping import PersistentMapping
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form

try:
    from bika.lims import api as bika_api
    _HAS_BIKA_API = True
except ImportError:
    _HAS_BIKA_API = False

logger = logging.getLogger("senaite.pfas.browser.method_wizard")

WIZARD_SESSIONS_KEY = u"senaite.pfas.wizard_sessions"
METHOD_ASSOC_KEY = u"senaite.pfas.method_associations"
NUM_STEPS = 10

# (num, id, title, explain, depends)
STEP_META = [
    (1, "method",
     "Method Identity",
     "Name and create the SENAITE Method record. The Method is the anchor "
     "that analytes, instruments, QC criteria, and specifications link to. "
     "You can also select an existing method to configure from here.",
     None),
    (2, "deptcat",
     "Lab Dept & Analysis Category",
     "Select the Lab Department and Analysis Category for this method. "
     "All Analysis Services must belong to a Category, and Categories to "
     "a Department.  For most PFAS work, 'PFAS' already exists -- "
     "confirm or change the selection.",
     "Method (Step 1)"),
    (3, "services",
     "Associate Analytes (Analysis Services)",
     "Select which Analysis Services (analytes and internal standards) "
     "are run under this method.  The wizard links each checked service "
     "to the Method so SENAITE knows which analytes belong to this protocol.",
     "Analysis Category (Step 2)"),
    (4, "sampletypes",
     "Associate Sample Types / Matrices",
     "Select the Sample Types (matrices) this method analyzes: Drinking "
     "Water, Fish Tissue, Soil, Serum, etc.  This association is used in "
     "Step 7 to prompt you to create the appropriate Analysis Specifications.",
     "Method (Step 1)"),
    (5, "qctypes",
     "Associate QC Types",
     "Select which QC sample types from the PFAS QC Type Pool apply to "
     "this method.  Each selected type will require acceptance criteria to "
     "be defined in the Method Profile (Step 6).  No fallbacks — only "
     "associated types will be evaluated during a batch run.",
     "Sample Types (Step 4)"),
    (6, "profile",
     "Method Profile",
     "Review and configure the extraction parameters, instrument verification "
     "criteria, and QC acceptance windows for this method.  Instrument "
     "Verification covers calibration, CCV, IS response, and confirmation. "
     "QC Acceptance defines tiered recovery and RPD limits for each QC type "
     "associated in Step 5.",
     "QC Types (Step 5)"),
    (7, "specs",
     "Analysis Specifications (Per Matrix)",
     "Confirm that Analysis Specifications exist for each sample type you "
     "selected in Step 4.  Specs define the reportable range and regulatory "
     "action levels (e.g. PFOA in Drinking Water: MRL 4 ng/L, limit 70 ng/L). "
     "A spec must exist for every matrix you report.",
     "Analytes (Step 3) + Sample Types (Step 4)"),
    (8, "storage",
     "Storage Locations & Sample Containers",
     "Select the storage locations and sample containers associated with "
     "samples analyzed by this method.  Stored in the wizard record so "
     "analysts can quickly identify where to hold samples and which "
     "containers to expect on receipt.",
     None),
    (9, "ivrules",
     "Instrument Verification Rules",
     "Enable or disable individual instrument verification checks for this "
     "method: calibration r-squared, CCV frequency and recovery window, "
     "IS response drift, ion-ratio tolerance, RRT/RT confirmation tolerance, "
     "and S/N thresholds.  Defaults are pre-loaded from the Method Profile "
     "— review before your first batch.",
     "Method Profile (Step 6)"),
    (10, "instruments",
     "Link Instruments",
     "Select which laboratory instruments are certified to run this method. "
     "The wizard links each instrument to the Method so SENAITE can track "
     "which instrument produced each result and schedule calibrations.",
     "Method (Step 1)"),
]


# ---------------------------------------------------------------------------
# Session store helpers
# ---------------------------------------------------------------------------

def _get_sessions_store(portal):
    ann = IAnnotations(portal)
    if WIZARD_SESSIONS_KEY not in ann:
        ann[WIZARD_SESSIONS_KEY] = PersistentMapping()
    return ann[WIZARD_SESSIONS_KEY]


def _load_session(portal, wid):
    store = _get_sessions_store(portal)
    raw = store.get(wid)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _save_session(portal, wid, data):
    store = _get_sessions_store(portal)
    store[wid] = json.dumps(data)


# ---------------------------------------------------------------------------
# Catalog helpers
# ---------------------------------------------------------------------------

def _query_setup(context, portal_type, **kw):
    """Query senaite_catalog_setup; return list of {uid, title} dicts."""
    catalog = getToolByName(context, "senaite_catalog_setup")
    query = {"portal_type": portal_type, "sort_on": "sortable_title"}
    query.update(kw)
    result = []
    for brain in catalog(query):
        try:
            obj = brain.getObject()
            uid = obj.UID() if hasattr(obj, "UID") else ""
            title = obj.Title() if hasattr(obj, "Title") else str(obj)
            result.append({"uid": uid, "title": title, "obj": obj})
        except Exception:
            pass
    return result


def _get_by_uid(context, uid):
    """Resolve a UID to a content object."""
    if _HAS_BIKA_API:
        try:
            return bika_api.get_object_by_uid(uid)
        except Exception:
            pass
    catalog = getToolByName(context, "uid_catalog")
    brains = catalog(UID=uid)
    if brains:
        try:
            return brains[0].getObject()
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# QC Type Pool helpers
# ---------------------------------------------------------------------------

def _get_pfas_ref_defs(context):
    """
    Return all ReferenceDefinitions that have pfas_qc_code set.
    Each entry: {uid, title, qc_code, category, acceptance_schema}.
    """
    catalog = getToolByName(context, "senaite_catalog_setup")
    result = []
    for brain in catalog({"portal_type": "ReferenceDefinition",
                           "sort_on": "sortable_title"}):
        try:
            obj = brain.getObject()
            code = ""
            try:
                code = obj.getPfas_qc_code() or ""
            except AttributeError:
                try:
                    f = obj.getField("pfas_qc_code")
                    code = f.get(obj) if f else ""
                except Exception:
                    pass
            if not code:
                continue
            category = ""
            schema = ""
            try:
                category = obj.getPfas_category() or ""
                schema = obj.getPfas_acceptance_schema() or ""
            except AttributeError:
                pass
            result.append({
                "uid":               obj.UID(),
                "title":             obj.Title(),
                "qc_code":           code,
                "category":          category,
                "acceptance_schema": schema,
            })
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# View
# ---------------------------------------------------------------------------

class PFASMethodWizardView(BrowserView):
    """Association-driven new-method wizard."""

    _template = ViewPageTemplateFile("templates/method_wizard.pt")

    # -- Dispatch --------------------------------------------------------

    def __call__(self):
        flatten_form(self.request)
        rq = self.request
        action = rq.form.get("action", "")

        if rq.method == "POST" and action == "new":
            return self._start_new()

        if rq.method == "POST" and action == "delete_session":
            return self._delete_session(rq.form.get("wid", ""))

        wid = rq.form.get("wid", "")
        step = self._parse_step()

        if rq.method == "POST" and wid:
            return self._handle_post(wid, step)

        if wid and "step" not in rq.form:
            sess = _load_session(self._portal(), wid)
            next_step = self._next_pending_step(sess)
            url = self._step_url(wid, next_step)
            rq.response.redirect(url)
            return ""

        return self._template()

    # -- Basic helpers ---------------------------------------------------

    def portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _parse_step(self):
        try:
            s = int(self.request.form.get("step", 1))
            return max(1, min(s, NUM_STEPS))
        except (ValueError, TypeError):
            return 1

    def _step_url(self, wid, step):
        return "{0}/@@pfas-method-wizard?wid={1}&step={2}".format(
            self.context.absolute_url(), wid, step)

    def _redirect(self, url):
        self.request.response.redirect(url)
        return ""

    def _redirect_step(self, wid, step, error=""):
        url = self._step_url(wid, step)
        if error:
            url += "&error=" + error.replace(" ", "+")
        return self._redirect(url)

    # -- Template data ---------------------------------------------------

    def wid(self):
        return self.request.form.get("wid", "")

    def current_step(self):
        return self._parse_step()

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")

    def success_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def session(self):
        wid = self.wid()
        if not wid:
            return {}
        return _load_session(self._portal(), wid)

    def step_meta(self, num=None):
        n = num if num is not None else self.current_step()
        for meta in STEP_META:
            if meta[0] == n:
                return meta
        return STEP_META[0]

    def step_explain(self, num=None):
        return self.step_meta(num)[3]

    def step_depends(self, num=None):
        return self.step_meta(num)[4] or ""

    def step_title(self, num=None):
        return self.step_meta(num)[2]

    # -- Landing page ----------------------------------------------------

    def existing_sessions(self):
        portal = self._portal()
        store = _get_sessions_store(portal)
        result = []
        for wid, raw in store.items():
            try:
                sess = json.loads(raw)
                step1 = sess.get("step1", {})
                method_name = step1.get("title", "(unnamed)")
                done = sess.get("completed_steps", [])
                result.append({
                    "wid": wid,
                    "method_name": method_name,
                    "steps_done": len(done),
                    "url": "{0}/@@pfas-method-wizard?wid={1}".format(
                        self.context.absolute_url(), wid),
                })
            except Exception:
                pass
        return sorted(result, key=lambda x: x["method_name"])

    def _start_new(self):
        wid = uuid.uuid4().hex[:12]
        _save_session(self._portal(), wid, {"completed_steps": []})
        return self._redirect(self._step_url(wid, 1))

    def _delete_session(self, wid):
        if wid:
            portal = self._portal()
            store = _get_sessions_store(portal)
            if wid in store:
                del store[wid]
        return self._redirect(self.context.absolute_url() + "/@@pfas-method-wizard")

    # -- Stepper sidebar -------------------------------------------------

    def steps_summary(self):
        wid = self.wid()
        sess = self.session()
        current = self.current_step()
        result = []
        for meta in STEP_META:
            num = meta[0]
            status = self._detect_step_status(num, sess, wid)
            result.append({
                "num": num,
                "title": meta[2],
                "status": status,
                "is_current": num == current,
                "url": self._step_url(wid, num),
            })
        return result

    def _detect_step_status(self, num, sess, wid):
        done = sess.get("completed_steps", [])
        if num in done:
            return "done"
        if num == 5:
            if sess.get("step5", {}).get("qc_type_codes"):
                return "done"
        if num == 6:
            mid = sess.get("method_id")
            if mid:
                from senaite.pfas.method_profile_store import (
                    get_profile, DEFAULT_PROFILES)
                portal = self._portal()
                p = get_profile(portal, mid)
                if p and not p.get("_seeded"):
                    return "done"
                if mid in DEFAULT_PROFILES:
                    return "defaults"
        if num == 9:
            return "defaults"
        return "pending"

    def _next_pending_step(self, sess):
        done = sess.get("completed_steps", [])
        for n in range(1, NUM_STEPS + 1):
            if n not in done:
                return n
        return NUM_STEPS

    # -- Step 1: Method identity -----------------------------------------

    def existing_methods(self):
        catalog = getToolByName(self.context, "senaite_catalog_setup")
        result = []
        for brain in catalog({"portal_type": "Method",
                               "sort_on": "sortable_title"}):
            try:
                obj = brain.getObject()
                result.append({
                    "uid": obj.UID(),
                    "title": obj.Title(),
                    "method_id": getattr(obj, "getMethodID", lambda: "")(),
                })
            except Exception:
                pass
        return result

    def step1_data(self):
        return self.session().get("step1", {})

    def _handle_step1(self, wid, sess):
        f = self.request.form
        existing_uid = f.get("existing_method_uid", "").strip()

        if existing_uid:
            obj = _get_by_uid(self.context, existing_uid)
            if obj is None:
                return self._redirect_step(wid, 1, error="Method+not+found")
            sess["method_uid"] = existing_uid
            sess["method_id"] = (getattr(obj, "getMethodID", lambda: "")()
                                 or existing_uid)
            sess["step1"] = {
                "title": obj.Title(),
                "method_id": sess["method_id"],
                "description": (obj.Description()
                                if hasattr(obj, "Description") else ""),
            }
        else:
            title = f.get("new_method_title", "").strip()
            mid = f.get("new_method_id", "").strip()
            desc = f.get("new_method_description", "").strip()
            if not title:
                return self._redirect_step(wid, 1, error="Title+is+required")
            if not mid:
                return self._redirect_step(wid, 1, error="Method+ID+is+required")

            portal = self._portal()
            method_folder = portal.get("methods")
            if method_folder is None:
                return self._redirect_step(wid, 1, error="No+methods+folder")

            existing = [o for o in method_folder.objectValues()
                        if o.Title() == title]
            if existing:
                obj = existing[0]
            else:
                try:
                    if _HAS_BIKA_API:
                        obj = bika_api.create(method_folder, "Method",
                                              title=title)
                    else:
                        method_folder.invokeFactory("Method", id=mid,
                                                   title=title)
                        obj = method_folder[mid]
                except Exception as exc:
                    logger.exception("Failed to create Method")
                    return self._redirect_step(
                        wid, 1,
                        error="Create+failed:+" + str(exc)[:40])
                try:
                    if hasattr(obj, "setMethodID"):
                        obj.setMethodID(mid)
                    if desc and hasattr(obj, "setDescription"):
                        obj.setDescription(desc)
                    obj.reindexObject()
                except Exception:
                    pass

            sess["method_uid"] = obj.UID()
            sess["method_id"] = mid
            sess["step1"] = {"title": title, "method_id": mid,
                             "description": desc}

        self._mark_done(sess, 1)
        return self._advance(wid, sess, 2)

    # -- Step 2: Dept & Category -----------------------------------------

    def departments(self):
        return _query_setup(self.context, "Department")

    def categories(self):
        return _query_setup(self.context, "AnalysisCategory")

    def step2_data(self):
        return self.session().get("step2", {})

    def _handle_step2(self, wid, sess):
        f = self.request.form
        dept_uid = f.get("dept_uid", "").strip()
        cat_uid = f.get("category_uid", "").strip()
        if not dept_uid:
            return self._redirect_step(wid, 2, error="Select+a+department")
        sess["step2"] = {"dept_uid": dept_uid, "category_uid": cat_uid}
        self._mark_done(sess, 2)
        return self._advance(wid, sess, 3)

    # -- Step 3: Associate analysis services -----------------------------

    def all_services(self):
        sess = self.session()
        method_uid = sess.get("method_uid", "")
        method_obj = (_get_by_uid(self.context, method_uid)
                      if method_uid else None)

        linked_uids = set()
        if method_obj and hasattr(method_obj, "getAnalysisServices"):
            try:
                for svc in method_obj.getAnalysisServices():
                    linked_uids.add(svc.UID())
            except Exception:
                pass

        catalog = getToolByName(self.context, "senaite_catalog_setup")
        result = []
        for brain in catalog({"portal_type": "AnalysisService",
                               "sort_on": "sortable_title"}):
            try:
                obj = brain.getObject()
                uid = obj.UID()
                cat = ""
                if hasattr(obj, "getCategory") and obj.getCategory():
                    cat = obj.getCategory().Title()

                is_linked = uid in linked_uids
                if not is_linked and hasattr(obj, "getMethods"):
                    try:
                        for m in obj.getMethods():
                            if m.UID() == method_uid:
                                is_linked = True
                                break
                    except Exception:
                        pass

                result.append({
                    "uid": uid,
                    "title": obj.Title(),
                    "category": cat,
                    "is_linked": is_linked,
                })
            except Exception:
                pass
        result.sort(key=lambda x: (x["category"], x["title"]))
        return result

    def step3_data(self):
        return self.session().get("step3", {})

    def _handle_step3(self, wid, sess):
        selected_uids = self.request.form.get("service_uid", [])
        if isinstance(selected_uids, str):
            selected_uids = [selected_uids]

        method_uid = sess.get("method_uid", "")
        method_obj = (_get_by_uid(self.context, method_uid)
                      if method_uid else None)

        if method_obj:
            for uid in selected_uids:
                svc = _get_by_uid(self.context, uid)
                if (svc and hasattr(svc, "getMethods")
                        and hasattr(svc, "setMethods")):
                    try:
                        existing = list(svc.getMethods() or [])
                        existing_uids = [m.UID() for m in existing]
                        if method_uid not in existing_uids:
                            existing.append(method_obj)
                            svc.setMethods(existing)
                            svc.reindexObject()
                    except Exception as exc:
                        logger.warning("setMethods failed for %s: %s",
                                       uid, exc)

        sess["step3"] = {"service_uids": selected_uids}
        self._mark_done(sess, 3)
        return self._advance(wid, sess, 4)

    # -- Step 4: Sample types --------------------------------------------

    def sample_types(self):
        return _query_setup(self.context, "SampleType")

    def step4_data(self):
        return self.session().get("step4", {})

    def _handle_step4(self, wid, sess):
        selected_uids = self.request.form.get("sampletype_uid", [])
        if isinstance(selected_uids, str):
            selected_uids = [selected_uids]
        sess["step4"] = {"sampletype_uids": selected_uids}
        self._mark_done(sess, 4)
        return self._advance(wid, sess, 5)

    # -- Step 5: Associate QC Types --------------------------------------

    def pfas_qc_types(self):
        """Return all PFAS QC types from the pool, with is_selected flag."""
        sess = self.session()
        selected_codes = set(sess.get("step5", {}).get("qc_type_codes", []))
        pool = _get_pfas_ref_defs(self.context)
        for entry in pool:
            entry["is_selected"] = entry["qc_code"] in selected_codes
        return pool

    def step5_data(self):
        return self.session().get("step5", {})

    def _handle_step5(self, wid, sess):
        selected_codes = self.request.form.get("qc_type_code", [])
        if isinstance(selected_codes, str):
            selected_codes = [selected_codes]

        if not selected_codes:
            return self._redirect_step(wid, 5,
                                       error="Select+at+least+one+QC+type")

        pool = _get_pfas_ref_defs(self.context)
        selected_uids = [e["uid"] for e in pool
                         if e["qc_code"] in selected_codes]

        sess["step5"] = {
            "qc_type_codes": selected_codes,
            "qc_type_uids":  selected_uids,
        }
        self._mark_done(sess, 5)

        # Persist associated QC types into the method profile store so
        # Step 6 (Method Profile) knows which acceptance sections to show.
        mid = sess.get("method_id")
        if mid:
            try:
                from senaite.pfas.method_profile_store import (
                    get_profile, save_profile)
                portal = self._portal()
                profile = get_profile(portal, mid) or {}
                profile["associated_qc_types"] = selected_codes
                save_profile(portal, mid, profile)
            except Exception as exc:
                logger.warning(
                    "step5: could not persist associated_qc_types: %s", exc)

        return self._advance(wid, sess, 6)

    # -- Step 6: Method Profile ------------------------------------------

    def profile_status_label(self):
        sess = self.session()
        mid = sess.get("method_id")
        if not mid:
            return "Pending -- complete Step 1 first"
        from senaite.pfas.method_profile_store import get_profile, DEFAULT_PROFILES
        portal = self._portal()
        p = get_profile(portal, mid)
        if not p:
            return "No profile found"
        if p.get("_seeded"):
            return "Default values loaded -- review recommended"
        return "Customised and saved"

    def profile_edit_url(self):
        sess = self.session()
        mid = sess.get("method_id", "")
        return "{0}/@@pfas-method-profile-edit?method_id={1}".format(
            self.context.absolute_url(), mid)

    def _handle_step6(self, wid, sess):
        self._mark_done(sess, 6)
        return self._advance(wid, sess, 7)

    # -- Step 7: Analysis Specifications ---------------------------------

    def sample_types_spec_status(self):
        sess = self.session()
        stype_uids = sess.get("step4", {}).get("sampletype_uids", [])
        if not stype_uids:
            return []

        catalog = getToolByName(self.context, "senaite_catalog_setup")
        spec_brains = catalog({"portal_type": "AnalysisSpec"})
        spec_stype_uids = set()
        for brain in spec_brains:
            try:
                obj = brain.getObject()
                if hasattr(obj, "getSampleType") and obj.getSampleType():
                    spec_stype_uids.add(obj.getSampleType().UID())
            except Exception:
                pass

        portal_url = self.portal_url()
        result = []
        for uid in stype_uids:
            stype = _get_by_uid(self.context, uid)
            if not stype:
                continue
            has_spec = uid in spec_stype_uids
            result.append({
                "uid": uid,
                "title": stype.Title() if hasattr(stype, "Title") else uid,
                "has_spec": has_spec,
                "status_label": "Spec exists" if has_spec else "No spec yet",
                "create_url": (
                    "{0}/bika_setup/bika_analysisspecs/"
                    "createObject?type_name=AnalysisSpec".format(portal_url)),
            })
        return result

    def _handle_step7(self, wid, sess):
        self._mark_done(sess, 7)
        return self._advance(wid, sess, 8)

    # -- Step 8: Storage & containers ------------------------------------

    def storage_locations(self):
        return _query_setup(self.context, "StorageLocation")

    def containers(self):
        return _query_setup(self.context, "SampleContainer")

    def step8_selected_storage(self):
        return self.session().get("step8", {}).get("storage_uids", [])

    def step8_selected_containers(self):
        return self.session().get("step8", {}).get("container_uids", [])

    def _handle_step8(self, wid, sess):
        storage_uids = self.request.form.get("storage_uid", [])
        container_uids = self.request.form.get("container_uid", [])
        if isinstance(storage_uids, str):
            storage_uids = [storage_uids]
        if isinstance(container_uids, str):
            container_uids = [container_uids]
        sess["step8"] = {
            "storage_uids": storage_uids,
            "container_uids": container_uids,
        }
        self._mark_done(sess, 8)
        return self._advance(wid, sess, 9)

    # -- Step 9: Instrument Verification Rules (link) --------------------

    def ivrules_url(self):
        sess = self.session()
        mid = sess.get("method_id", "")
        url = "{0}/@@pfas-qc-rules".format(self.context.absolute_url())
        if mid:
            url += "?method=" + mid
        return url

    def _handle_step9(self, wid, sess):
        self._mark_done(sess, 9)
        return self._advance(wid, sess, 10)

    # -- Step 10: Instruments --------------------------------------------

    def instruments(self):
        sess = self.session()
        method_uid = sess.get("method_uid", "")
        method_obj = (_get_by_uid(self.context, method_uid)
                      if method_uid else None)

        linked_uids = set()
        if method_obj and hasattr(method_obj, "getInstruments"):
            try:
                for instr in method_obj.getInstruments():
                    linked_uids.add(instr.UID())
            except Exception:
                pass

        catalog = getToolByName(self.context, "senaite_catalog_setup")
        result = []
        for brain in catalog({"portal_type": "Instrument",
                               "sort_on": "sortable_title"}):
            try:
                obj = brain.getObject()
                uid = obj.UID()
                result.append({
                    "uid": uid,
                    "title": obj.Title(),
                    "is_linked": uid in linked_uids,
                })
            except Exception:
                pass
        return result

    def _handle_step10(self, wid, sess):
        selected_uids = self.request.form.get("instrument_uid", [])
        if isinstance(selected_uids, str):
            selected_uids = [selected_uids]

        method_uid = sess.get("method_uid", "")
        method_obj = (_get_by_uid(self.context, method_uid)
                      if method_uid else None)

        if method_obj:
            for uid in selected_uids:
                instr = _get_by_uid(self.context, uid)
                if (instr and hasattr(instr, "getMethods")
                        and hasattr(instr, "setMethods")):
                    try:
                        existing = list(instr.getMethods() or [])
                        existing_uids = [m.UID() for m in existing]
                        if method_uid not in existing_uids:
                            existing.append(method_obj)
                            instr.setMethods(existing)
                            instr.reindexObject()
                    except Exception as exc:
                        logger.warning(
                            "setMethods on instrument failed: %s", exc)

        sess["step10"] = {"instrument_uids": selected_uids}
        self._mark_done(sess, 10)

        self._persist_associations(sess)
        _save_session(self._portal(), wid, sess)

        ok_url = ("{0}/@@pfas-method-wizard?wid={1}&step=10"
                  "&ok=Wizard+complete".format(
                      self.context.absolute_url(), wid))
        return self._redirect(ok_url)

    # -- Association persistence -----------------------------------------

    def _persist_associations(self, sess):
        mid = sess.get("method_id")
        if not mid:
            return
        portal = self._portal()
        ann = IAnnotations(portal)
        if METHOD_ASSOC_KEY not in ann:
            ann[METHOD_ASSOC_KEY] = PersistentMapping()
        store = ann[METHOD_ASSOC_KEY]
        data = {
            "method_uid":      sess.get("method_uid", ""),
            "dept_uid":        sess.get("step2", {}).get("dept_uid", ""),
            "category_uid":    sess.get("step2", {}).get("category_uid", ""),
            "service_uids":    sess.get("step3", {}).get("service_uids", []),
            "sampletype_uids": sess.get("step4", {}).get("sampletype_uids", []),
            "qc_type_codes":   sess.get("step5", {}).get("qc_type_codes", []),
            "qc_type_uids":    sess.get("step5", {}).get("qc_type_uids", []),
            "storage_uids":    sess.get("step8", {}).get("storage_uids", []),
            "container_uids":  sess.get("step8", {}).get("container_uids", []),
            "instrument_uids": sess.get("step10", {}).get("instrument_uids", []),
        }
        store[mid] = json.dumps(data)

    # -- Shared POST dispatch --------------------------------------------

    def _handle_post(self, wid, step):
        portal = self._portal()
        sess = _load_session(portal, wid)

        handlers = {
            1:  self._handle_step1,
            2:  self._handle_step2,
            3:  self._handle_step3,
            4:  self._handle_step4,
            5:  self._handle_step5,
            6:  self._handle_step6,
            7:  self._handle_step7,
            8:  self._handle_step8,
            9:  self._handle_step9,
            10: self._handle_step10,
        }
        handler = handlers.get(step)
        if handler is None:
            return self._redirect(self._step_url(wid, 1))
        return handler(wid, sess)

    def _mark_done(self, sess, step_num):
        done = sess.setdefault("completed_steps", [])
        if step_num not in done:
            done.append(step_num)

    def _advance(self, wid, sess, next_step):
        portal = self._portal()
        _save_session(portal, wid, sess)
        return self._redirect(self._step_url(wid, next_step))

    # -- Wizard complete -------------------------------------------------

    def wizard_complete(self):
        done = self.session().get("completed_steps", [])
        return len(done) >= NUM_STEPS

    def method_display_name(self):
        sess = self.session()
        return sess.get("step1", {}).get("title", "New Method")
