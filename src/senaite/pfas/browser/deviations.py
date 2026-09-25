from __future__ import print_function
import json
import logging
from datetime import datetime, date

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from zope.annotation.interfaces import IAnnotations
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.qc_deviation import (
    get_registry as _get_registry,
    save_registry as _save_registry,
)

logger = logging.getLogger("senaite.pfas.deviations")


EVENT_TYPES = [
    ("missed_calibration",   "Missed Calibration"),
    ("missed_verification",  "Missed Verification"),
    ("procedure_deviation",  "Procedure Deviation"),
    ("equipment_failure",    "Equipment Failure"),
    ("reagent_issue",        "Reagent / Standard Issue"),
    ("data_entry_error",     "Data Entry Error"),
    ("other",                "Other"),
]

EVENT_LABELS = dict(EVENT_TYPES)

LIKELIHOOD_LABELS = {
    1: "1 — Rare",
    2: "2 — Unlikely",
    3: "3 — Possible",
    4: "4 — Likely",
    5: "5 — Almost Certain",
}

SEVERITY_LABELS = {
    1: "1 — Insignificant",
    2: "2 — Minor",
    3: "3 — Moderate",
    4: "4 — Major",
    5: "5 — Catastrophic",
}


def _risk_colour(score):
    if score <= 4:
        return "green"
    if score <= 9:
        return "yellow"
    if score <= 14:
        return "orange"
    return "red"


def _risk_label(score):
    if score <= 4:
        return "Low"
    if score <= 9:
        return "Medium"
    if score <= 14:
        return "High"
    return "Critical"


# ── Annotation helpers ────────────────────────────────────────────────────────
# Imported, not redeclared. This module used to carry its own copy of the key
# string plus an identical accessor pair; senaite.pfas.qc_deviation owns both.


def _next_dev_id(registry, dev_type):
    year = date.today().year
    prefix = "CAR" if dev_type == "car" else "DEV"
    existing = [
        e["dev_id"] for e in registry
        if e["dev_id"].startswith("{0}-{1}-".format(prefix, year))
    ]
    seq = len(existing) + 1
    return "{0}-{1}-{2:03d}".format(prefix, year, seq)


# ── View class ────────────────────────────────────────────────────────────────

class PFASDeviationView(BrowserView):

    def __call__(self):
        flatten_form(self.request)
        action = self.request.form.get("action", "")
        if action == "generate_notification":
            return self._handle_notification()
        if action == "lookup_worksheets":
            return self._handle_lookup_worksheets()
        if self.request.method == "POST":
            # PFAS forms don't carry a CSRF _authenticator token; every other
            # PFAS POST view disables plone.protect the same way. Without this a
            # browser-session POST (cookie auth) is blocked/rolled back while
            # basic-auth works — so filing a deviation/CAR failed only in the UI.
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            if action == "file_deviation":
                return self._handle_file()
            if action == "update_scale_rootcause":
                return self._handle_update_scale()
            if action == "add_corrective_action":
                return self._handle_add_ca()
            if action == "complete_ca":
                return self._handle_complete_ca()
            if action == "acknowledge_training":
                return self._handle_ack_training()
            if action == "mark_notification_sent":
                return self._handle_notification_sent()
            if action == "close_deviation":
                return self._handle_close()
        return self.index()

    # ── Data helpers ──────────────────────────────────────────────────────────

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def _current_user(self):
        return getSecurityManager().getUser()

    def _current_user_id(self):
        return self._current_user().getId() or ""

    def _current_user_fullname(self):
        user = self._current_user()
        portal = self._portal()
        mt = getToolByName(portal, "portal_membership", None)
        if mt:
            member = mt.getMemberById(user.getId())
            if member:
                full = member.getProperty("fullname", "")
                if full:
                    return full
        return user.getUserName() or user.getId() or "Unknown"

    def _user_roles(self):
        portal = self._portal()
        user = self._current_user()
        try:
            return list(user.getRolesInContext(portal))
        except Exception:
            return list(user.getRoles())

    def can_manage(self):
        roles = self._user_roles()
        return "LabManager" in roles or "Manager" in roles

    def can_edit(self):
        """Any lab role may edit open/in-progress records; only managers may close."""
        roles = self._user_roles()
        _LAB_ROLES = {"LabManager", "Manager", "LabAnalyst", "Analyst",
                      "Verifier", "LabClerk", "RegulatoryInspector"}
        return bool(_LAB_ROLES & set(roles))

    def portal_url(self):
        return self._portal_url()

    def _now_iso(self):
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    def _today(self):
        return date.today().isoformat()

    # ── Template data methods ─────────────────────────────────────────────────

    def list_deviations(self):
        registry = _get_registry(self._portal())
        ftype  = self.request.form.get("filter_type", "")
        fstatus = self.request.form.get("filter_status", "")
        result = []
        for dev in reversed(registry):
            if ftype and dev.get("type") != ftype:
                continue
            if fstatus and dev.get("status") != fstatus:
                continue
            dev = dict(dev)
            dev["risk_colour"] = _risk_colour(dev.get("risk_score", 0))
            dev["risk_label"]  = _risk_label(dev.get("risk_score", 0))
            dev["event_label"] = EVENT_LABELS.get(dev.get("event_type", ""), dev.get("event_type", ""))
            dev["ca_count"]    = len(dev.get("corrective_actions", []))
            dev["ca_pending"]  = sum(
                1 for ca in dev.get("corrective_actions", [])
                if ca.get("status") != "complete"
            )
            result.append(dev)
        return result

    def current_deviation(self):
        dev_id = self.request.form.get("dev_id", "").strip()
        if not dev_id:
            return None
        portal = self._portal()
        for dev in _get_registry(portal):
            if dev.get("dev_id") == dev_id:
                dev = dict(dev)
                dev["risk_colour"] = _risk_colour(dev.get("risk_score", 0))
                dev["risk_label"]  = _risk_label(dev.get("risk_score", 0))
                dev["event_label"] = EVENT_LABELS.get(dev.get("event_type", ""), "")
                dev["all_cas_complete"] = all(
                    ca.get("status") == "complete"
                    for ca in dev.get("corrective_actions", [])
                ) if dev.get("corrective_actions") else False
                return dev
        return None

    def is_detail_view(self):
        return bool(self.request.form.get("dev_id", "").strip())

    def event_types(self):
        return EVENT_TYPES

    def likelihood_range(self):
        return list(range(1, 6))

    def severity_range(self):
        return list(range(1, 6))

    def likelihood_label(self, n):
        return LIKELIHOOD_LABELS.get(n, str(n))

    def severity_label(self, n):
        return SEVERITY_LABELS.get(n, str(n))

    def risk_colour_for(self, l, s):
        return _risk_colour(l * s)

    def risk_colour_css(self, colour):
        return {
            "green":  "#28a745",
            "yellow": "#ffc107",
            "orange": "#fd7e14",
            "red":    "#dc3545",
        }.get(colour, "#6c757d")

    def recent_worksheets(self):
        """Recent open/to_be_verified worksheets for affected_worksheets picker."""
        try:
            cat = getToolByName(self.context, "senaite_catalog_worksheet")
            brains = cat(portal_type="Worksheet",
                         review_state=["open", "to_be_verified", "verified"])
        except Exception:
            return []
        result = []
        for b in brains[:100]:
            try:
                result.append({"id": b.getId(), "title": b.Title or b.getId()})
            except Exception:
                pass
        return result

    def available_methods(self):
        """Active core SENAITE Method objects, via the setup catalog.

        Dynamically links to the real Method objects (the same ones worksheets
        are tagged with), so the selector matches worksheet lookups. Was reading
        a non-existent ``bika_setup.bika_methods`` folder (SENAITE 2.6 uses
        ``bika_setup.methods``), which silently returned an empty list.
        """
        try:
            from Products.CMFCore.utils import getToolByName
            catalog = getToolByName(self.context, "senaite_catalog_setup")
            result = []
            for brain in catalog(portal_type="Method",
                                 is_active=True,
                                 sort_on="sortable_title"):
                try:
                    obj = brain.getObject()
                    result.append({
                        "id":    obj.getId(),
                        "title": obj.Title() or obj.getId(),
                    })
                except Exception:
                    continue
            return result
        except Exception:
            return []

    def _handle_lookup_worksheets(self):
        """Return JSON list of worksheets matching a method and optional date range."""
        from DateTime import DateTime
        method_id = (self.request.form.get("method_id") or "").strip()
        date_from  = (self.request.form.get("date_from") or "").strip()
        date_to    = (self.request.form.get("date_to")   or "").strip()

        self.request.response.setHeader("Content-Type", "application/json")

        if not method_id:
            return json.dumps({"error": "no_method", "results": []})

        try:
            cat = getToolByName(self.context, "senaite_catalog_worksheet")
            query = {"portal_type": "Worksheet"}
            if date_from:
                try:
                    q_from = DateTime(date_from)
                    q_to   = (DateTime(date_to) + 1) if date_to else DateTime("2099/12/31")
                    query["created"] = {"query": [q_from, q_to], "range": "minmax"}
                except Exception:
                    pass
            brains = cat(**query)
        except Exception as exc:
            return json.dumps({"error": str(exc), "results": []})

        results = []
        for b in brains:
            try:
                ws = b.getObject()
                ws_method_id = ""
                try:
                    m = ws.getMethod()
                    if m:
                        ws_method_id = m.getId()
                except Exception:
                    pass
                if not ws_method_id:
                    try:
                        for an in ws.getAnalyses():
                            m = an.getMethod()
                            if m:
                                ws_method_id = m.getId()
                                break
                    except Exception:
                        pass
                if ws_method_id == method_id:
                    created_str = ""
                    try:
                        created_str = str(ws.created())[:10]
                    except Exception:
                        pass
                    results.append({
                        "id":      ws.getId(),
                        "title":   ws.Title() or ws.getId(),
                        "created": created_str,
                    })
            except Exception:
                pass

        results.sort(key=lambda x: x.get("created", ""), reverse=True)
        return json.dumps({"results": results})

    def current_user_id(self):
        return self._current_user_id()

    def current_user_fullname(self):
        return self._current_user_fullname()

    def active_tab(self):
        return self.request.form.get("tab", "overview")

    def filter_type(self):
        return self.request.form.get("filter_type", "")

    def filter_status(self):
        return self.request.form.get("filter_status", "")

    def msg(self):
        return self.request.form.get("msg", "")

    def msg_type(self):
        return self.request.form.get("msg_type", "info")

    def msg_text(self):
        msgs = {
            "filed":            "Deviation/CAR filed successfully.",
            "updated":          "Record updated.",
            "ca_added":         "Corrective action added.",
            "ca_completed":     "Corrective action marked complete.",
            "acknowledged":     "Training acknowledgment recorded.",
            "notif_sent":       "Notification marked as sent.",
            "closed":           "Record closed.",
            "permission_denied":"Permission denied.",
            "incomplete_cas":   "All corrective actions must be complete before closing.",
            "bad_request":      "Invalid request.",
            "description_required": "A description is required to file a deviation/CAR.",
            "not_found":        "Record not found.",
        }
        return msgs.get(self.msg(), self.msg())

    def active_deviations_for_worksheet(self, ws_id):
        result = []
        for dev in _get_registry(self._portal()):
            if dev.get("status") == "closed":
                continue
            if ws_id in dev.get("affected_worksheets", []):
                result.append(dev)
        return result

    # ── POST handlers ─────────────────────────────────────────────────────────

    def _handle_file(self):
        if not self.can_edit():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form      = self.request.form
        def _one(name, default=""):
            v = form.get(name, default)
            if isinstance(v, (list, tuple)):
                v = v[0] if v else default
            return v

        def _score(name):
            try:
                return max(1, min(5, int(_one(name, 3) or 3)))
            except (TypeError, ValueError):
                return 3

        dev_type   = "car" if _one("type") == "car" else "deviation"
        event_type = _one("event_type", "other")
        event_date = _one("event_date") or self._today()
        description = (_one("description") or "").strip()
        if not description:
            return self._redirect("?msg=description_required&msg_type=error")
        likelihood = _score("likelihood")
        severity   = _score("severity")

        portal   = self._portal()
        registry = _get_registry(portal)
        dev_id   = _next_dev_id(registry, dev_type)
        score    = likelihood * severity
        registry.append({
            "dev_id":      dev_id,
            "type":        dev_type,
            "filed_by":    self._current_user_id(),
            "filed_at":    self._today(),
            "status":      "open",
            "event_type":  event_type,
            "event_date":  event_date,
            "description": description,
            "likelihood":  likelihood,
            "severity":    severity,
            "risk_score":  score,
            "risk_colour": _risk_colour(score),
            "affected_worksheets": [],
            "affected_date_from":  "",
            "affected_date_to":    "",
            "scale_description":   "",
            "root_cause":          "",
            "corrective_actions":  [],
            "closed_by":   None,
            "closed_at":   None,
            "closure_notes": "",
        })
        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=overview&msg=filed&msg_type=success".format(dev_id)
        )

    def _handle_update_scale(self):
        if not self.can_edit():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form   = self.request.form
        dev_id = form.get("dev_id", "").strip()
        portal = self._portal()
        registry = _get_registry(portal)
        for dev in registry:
            if dev["dev_id"] == dev_id:
                dev["affected_worksheets"] = [
                    w.strip() for w in form.get("affected_worksheets", "").split(",")
                    if w.strip()
                ]
                dev["affected_date_from"]  = form.get("affected_date_from", "")
                dev["affected_date_to"]    = form.get("affected_date_to", "")
                dev["scale_description"]   = form.get("scale_description", "").strip()
                dev["root_cause"]          = form.get("root_cause", "").strip()
                try:
                    li = max(1, min(5, int(form.get("likelihood", dev.get("likelihood", 3)))))
                    si = max(1, min(5, int(form.get("severity",   dev.get("severity",   3)))))
                    dev["likelihood"]  = li
                    dev["severity"]    = si
                    dev["risk_score"]  = li * si
                    dev["risk_colour"] = _risk_colour(li * si)
                    dev["risk_label"]  = _risk_label(li * si)
                except (ValueError, TypeError):
                    pass
                if dev.get("status") == "open":
                    dev["status"] = "in_progress"
                break
        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=rootcause&msg=updated&msg_type=success".format(dev_id)
        )

    def _handle_add_ca(self):
        if not self.can_manage():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form    = self.request.form
        dev_id  = form.get("dev_id", "").strip()
        ca_type = form.get("ca_type", "")
        portal  = self._portal()
        registry = _get_registry(portal)

        for dev in registry:
            if dev["dev_id"] != dev_id:
                continue
            cas = dev.get("corrective_actions", [])
            ca_id = "ca-{0}".format(len(cas) + 1)
            if ca_type == "sop_revision":
                cas.append({
                    "ca_id":       ca_id,
                    "type":        "sop_revision",
                    "description": form.get("ca_description", "").strip(),
                    "sop_id":      form.get("ca_sop_id", "").strip(),
                    "new_rev_num": None,
                    "status":      "pending",
                    "completed_at": None,
                    "completed_by": None,
                })
            elif ca_type == "training":
                users_raw = form.get("ca_required_users", "")
                req_users = [u.strip() for u in users_raw.split(",") if u.strip()]
                cas.append({
                    "ca_id":           ca_id,
                    "type":            "training",
                    "description":     form.get("ca_description", "").strip(),
                    "required_users":  req_users,
                    "acknowledgments": {},
                    "status":          "pending",
                    "completed_at":    None,
                    "completed_by":    None,
                })
            elif ca_type == "notification":
                cas.append({
                    "ca_id":       ca_id,
                    "type":        "notification",
                    "subtype":     form.get("ca_subtype", "impact"),
                    "description": form.get("ca_description", "").strip(),
                    "affected_worksheets": [
                        w.strip()
                        for w in form.get("ca_affected_ws", "").split(",")
                        if w.strip()
                    ],
                    "notification_text": form.get("ca_notification_text", "").strip(),
                    "status":       "pending",
                    "sent_at":      None,
                    "sent_by":      None,
                })
            dev["corrective_actions"] = cas
            if dev.get("status") == "open":
                dev["status"] = "in_progress"
            break

        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=actions&msg=ca_added&msg_type=success".format(dev_id)
        )

    def _handle_complete_ca(self):
        if not self.can_manage():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form   = self.request.form
        dev_id = form.get("dev_id", "").strip()
        ca_id  = form.get("ca_id", "").strip()
        portal = self._portal()
        registry = _get_registry(portal)
        for dev in registry:
            if dev["dev_id"] != dev_id:
                continue
            for ca in dev.get("corrective_actions", []):
                if ca["ca_id"] == ca_id:
                    ca["status"]       = "complete"
                    ca["completed_at"] = self._now_iso()
                    ca["completed_by"] = self._current_user_id()
                    break
            break
        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=actions&msg=ca_completed&msg_type=success".format(dev_id)
        )

    def _handle_ack_training(self):
        form   = self.request.form
        dev_id = form.get("dev_id", "").strip()
        ca_id  = form.get("ca_id", "").strip()
        uid    = self._current_user_id()
        portal = self._portal()
        registry = _get_registry(portal)
        for dev in registry:
            if dev["dev_id"] != dev_id:
                continue
            for ca in dev.get("corrective_actions", []):
                if ca["ca_id"] != ca_id:
                    continue
                if uid not in ca.get("required_users", []):
                    break
                acks = ca.get("acknowledgments", {})
                acks[uid] = {
                    "acked_at":  self._now_iso(),
                    "full_name": self._current_user_fullname(),
                }
                ca["acknowledgments"] = acks
                # auto-complete when all required users have acknowledged
                req = ca.get("required_users", [])
                if req and all(u in acks for u in req):
                    ca["status"]       = "complete"
                    ca["completed_at"] = self._now_iso()
                    ca["completed_by"] = "auto"
                break
            break
        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=actions&msg=acknowledged&msg_type=success".format(dev_id)
        )

    def _handle_notification_sent(self):
        if not self.can_manage():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form   = self.request.form
        dev_id = form.get("dev_id", "").strip()
        ca_id  = form.get("ca_id", "").strip()
        portal = self._portal()
        registry = _get_registry(portal)
        for dev in registry:
            if dev["dev_id"] != dev_id:
                continue
            for ca in dev.get("corrective_actions", []):
                if ca["ca_id"] == ca_id:
                    ca["status"]  = "complete"
                    ca["sent_at"] = self._now_iso()
                    ca["sent_by"] = self._current_user_id()
                    ca["completed_at"] = self._now_iso()
                    ca["completed_by"] = self._current_user_id()
                    break
            break
        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=actions&msg=notif_sent&msg_type=success".format(dev_id)
        )

    def _handle_close(self):
        if not self.can_manage():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form   = self.request.form
        dev_id = form.get("dev_id", "").strip()
        notes  = form.get("closure_notes", "").strip()
        portal = self._portal()
        registry = _get_registry(portal)
        for dev in registry:
            if dev["dev_id"] != dev_id:
                continue
            open_cas = [
                ca for ca in dev.get("corrective_actions", [])
                if ca.get("status") != "complete"
            ]
            if open_cas:
                return self._redirect(
                    "?dev_id={0}&tab=closure&msg=incomplete_cas&msg_type=error".format(dev_id)
                )
            dev["status"]        = "closed"
            dev["closed_by"]     = self._current_user_id()
            dev["closed_at"]     = self._now_iso()
            dev["closure_notes"] = notes
            break
        _save_registry(portal, registry)
        return self._redirect(
            "?dev_id={0}&tab=closure&msg=closed&msg_type=success".format(dev_id)
        )

    def _handle_notification(self):
        """Return a printable HTML notification letter (no sidebar/chrome)."""
        dev_id = self.request.form.get("dev_id", "").strip()
        ca_id  = self.request.form.get("ca_id", "").strip()
        portal = self._portal()

        dev = None
        for d in _get_registry(portal):
            if d.get("dev_id") == dev_id:
                dev = d
                break

        if not dev:
            self.request.response.setStatus(404)
            return "<h1>Not found</h1>"

        ca = None
        for c in dev.get("corrective_actions", []):
            if c.get("ca_id") == ca_id and c.get("type") == "notification":
                ca = c
                break

        if not ca:
            # fallback: find first notification CA
            for c in dev.get("corrective_actions", []):
                if c.get("type") == "notification":
                    ca = c
                    break

        subtype = (ca or {}).get("subtype", "impact")
        notif_text = (ca or {}).get("notification_text", "")
        affected_ws = (ca or {}).get("affected_worksheets",
                       dev.get("affected_worksheets", []))

        score   = dev.get("risk_score", 0)
        colour  = _risk_colour(score)
        colour_css = {"green": "#28a745", "yellow": "#856404",
                      "orange": "#d26b00", "red": "#721c24"}.get(colour, "#333")
        bg_css  = {"green": "#d4edda", "yellow": "#fff3cd",
                   "orange": "#ffe5cc", "red": "#f8d7da"}.get(colour, "#f0f0f0")

        if subtype == "retest":
            subject_line = "Sample Retest Notification"
            action_para = (
                u"<p>We are pleased to offer a complimentary retest for the "
                u"affected samples listed below. Please contact our laboratory "
                u"to arrange sample submission at your earliest convenience.</p>"
            )
        else:
            subject_line = "Sample Data Impact Notification"
            action_para = (
                u"<p>Please be advised that the results for the samples listed "
                u"below may have been affected by the above non-conformance. "
                u"Our laboratory quality officer has reviewed the potential "
                u"impact and determined the following:</p>"
            )

        ws_list_html = u""
        if affected_ws:
            ws_list_html = u"<ul>" + u"".join(
                u"<li>{0}</li>".format(ws) for ws in affected_ws
            ) + u"</ul>"
        else:
            ws_list_html = u"<p><em>No specific worksheets referenced.</em></p>"

        today_str = date.today().strftime("%B %d, %Y")

        html = u"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{subject} — {dev_id}</title>
<style>
  body {{ font-family: Arial, sans-serif; font-size: 13px; color: #333;
          max-width: 760px; margin: 40px auto; padding: 0 24px; }}
  h1 {{ font-size: 18px; margin-bottom: 4px; }}
  .header-bar {{ border-bottom: 2px solid #333; padding-bottom: 12px;
                 margin-bottom: 20px; }}
  .label {{ font-size: 11px; font-weight: 700; color: #666;
            text-transform: uppercase; margin-bottom: 2px; }}
  .meta-grid {{ display: grid; grid-template-columns: 1fr 1fr 1fr;
                gap: 16px; margin: 16px 0; }}
  .risk-badge {{ display: inline-block; padding: 4px 14px; border-radius: 8px;
                 font-weight: 700; font-size: 12px;
                 color: {colour_css}; background: {bg_css}; }}
  .section {{ margin: 18px 0; }}
  .section h2 {{ font-size: 14px; font-weight: 700; margin-bottom: 6px;
                 border-bottom: 1px solid #ddd; padding-bottom: 4px; }}
  ul {{ margin: 6px 0 6px 20px; }}
  .sig-block {{ margin-top: 40px; display: grid; grid-template-columns: 1fr 1fr; gap: 32px; }}
  .sig-line {{ border-top: 1px solid #333; padding-top: 6px; font-size: 11px; color: #666; }}
  @media print {{
    body {{ margin: 0; padding: 16px; }}
    .no-print {{ display: none !important; }}
  }}
</style>
</head>
<body>

<div class="no-print" style="background:#fff3cd;padding:10px 16px;
     border-radius:4px;margin-bottom:16px;font-size:12px;color:#856404">
  &#9888; This is a preview. Use your browser&rsquo;s Print function (Ctrl+P / Cmd+P)
  to save as PDF or print. <a href="javascript:window.print()" style="color:#856404;
  font-weight:700">Print now</a>
</div>

<div class="header-bar">
  <div class="label">Laboratory Notification</div>
  <h1>{subject}</h1>
  <div style="font-size:12px;color:#666;margin-top:4px">
    Reference: <strong>{dev_id}</strong> &nbsp;&bull;&nbsp; Date: {today}
  </div>
</div>

<div class="meta-grid">
  <div>
    <div class="label">Non-conformance Type</div>
    <div>{dev_type}</div>
  </div>
  <div>
    <div class="label">Event Date</div>
    <div>{event_date}</div>
  </div>
  <div>
    <div class="label">Risk Assessment</div>
    <div><span class="risk-badge">Score {score} — {risk_label}</span></div>
  </div>
</div>

<div class="section">
  <h2>Event Description</h2>
  <p>{description}</p>
</div>

<div class="section">
  <h2>Affected Samples / Worksheets</h2>
  {ws_list}
</div>

{action_para}

<div class="section">
  <p style="white-space:pre-wrap">{notif_text}</p>
</div>

<div class="section">
  <h2>Corrective Action</h2>
  <p>Our quality management team has investigated this non-conformance and
  implemented corrective actions to prevent recurrence. A full corrective
  action report is maintained in our quality management system (Ref: {dev_id}).</p>
</div>

<div class="sig-block">
  <div>
    <div style="height:40px"></div>
    <div class="sig-line">Quality Assurance Officer / Laboratory Director</div>
  </div>
  <div>
    <div style="height:40px"></div>
    <div class="sig-line">Date</div>
  </div>
</div>

</body>
</html>""".format(
            subject=subject_line,
            dev_id=dev_id,
            today=today_str,
            dev_type="Corrective Action Report (CAR)" if dev.get("type") == "car" else "Deviation",
            event_date=dev.get("event_date", ""),
            score=score,
            risk_label=_risk_label(score),
            colour_css=colour_css,
            bg_css=bg_css,
            description=dev.get("description", "").replace("<", "&lt;").replace(">", "&gt;"),
            ws_list=ws_list_html,
            action_para=action_para,
            notif_text=notif_text.replace("<", "&lt;").replace(">", "&gt;"),
        )

        response = self.request.response
        response.setHeader("Content-Type", "text/html; charset=utf-8")
        return html.encode("utf-8")

    def _redirect(self, qs=""):
        base = "{0}/@@pfas-deviations".format(self._portal_url())
        self.request.response.redirect("{0}{1}".format(base, qs))
        return ""
