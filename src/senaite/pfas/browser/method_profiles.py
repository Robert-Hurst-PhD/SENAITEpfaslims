# -*- coding: utf-8 -*-
"""
PFAS Method Profile browser views.

@@pfas-method-profiles
    List all configured methods; links to edit each one.

@@pfas-method-profile-edit?method_id=FDA_32PFAS
    Edit a single method profile; POST saves to ZODB and exports
    /data/qc/method_profiles.json for the pipeline worker.
    ...&delete=check lists what uses the method (method_delete.py) and,
    when nothing does, offers to delete it (POST action=delete_method).

A manager reads and writes both; the read-only inspector reads both by
GET, drawn view-only (read_only), and posts nothing.
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import urllib

from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse
from senaite.pfas import method_proposals as mp
from senaite.pfas.html_text import escape
from senaite.pfas.method_profile_store import (
    get_profile,
    list_method_ids,
    save_profile,
)

logger = logging.getLogger("senaite.pfas.browser.method_profiles")


# Roles that may edit Method Profiles are perms.ALLOWED_ROLES (Q-006:
# LabManager covers QAO/Lab Director).


def _require_manager(context, request):
    # One gate, resolved at the portal. This module kept a private
    # copy that resolved at the context, so a bench user's local Owner role on
    # anything they had created passed it.
    from senaite.pfas.browser.perms import require_manager
    return require_manager(context, request)


def _qa_approver(context):
    """True when the signed-in person holds the QA approver sign right in
    People & Roles: they countersign or refuse a change proposed from a
    run. False when their record cannot be read."""
    try:
        from AccessControl import getSecurityManager
        from senaite.pfas.browser import staff
        userid = getSecurityManager().getUser().getId()
        return "qa_approver" in (staff.staff_info(userid).get("sign_as") or ())
    except Exception:                                       # noqa: BLE001
        logger.warning("QA approver right unread", exc_info=True)
        return False


def _may_read(context, request):
    """A manager in any way; the read-only inspector by GET or HEAD, the
    pages drawn view-only for it (perms.may_read_config); and by GET or
    HEAD, drawn view-only, the holder of the QA approver sign right, who
    decides the changes proposed from a run there and edits nothing else."""
    from senaite.pfas.browser.perms import may_read_config
    if may_read_config(context, request):
        return True
    getter = getattr(request, "get", None)
    method = ((getter("REQUEST_METHOD") if getter else None) or "GET").upper()
    return method in ("GET", "HEAD") and _qa_approver(context)


def _portal(context):
    return context.portal_url.getPortalObject()


# ── List view ─────────────────────────────────────────────────────────────────


def _stages_from_form(stages):
    """The Lab workflow stages as saved: a stage designed as questions gets
    the keys the rest of the system reads derived from them
    (stage_form.apply_fields); a stage id appears once (an extraction keeps
    its records by stage). A ValueError refuses the save with its reason."""
    from senaite.pfas import stage_form
    out, ids = [], set()
    for st in stages or []:
        if not isinstance(st, dict):
            continue
        sid = (st.get("id") or u"").strip()
        if sid and sid in ids:
            raise ValueError(u"two stages share the id '%s'." % sid)
        ids.add(sid)
        if isinstance(st.get("fields"), list):
            errors = stage_form.validate(st["fields"])
            if errors:
                raise ValueError(u"stage '%s': %s" % (st.get("name") or sid, u" ".join(errors)))
            st = stage_form.apply_fields(st, st["fields"])
        out.append(st)
    return out

def standard_lots(portal, named=()):
    """Standard / Reference-Material lots from the reagent inventory: what a
    salt factor's CoA lot is chosen from and named by, on the method's page
    and on its Settings Report alike. Expired lots are flagged so they
    aren't picked. A lot in `named` (ids a method row holds) that the list
    leaves out, an archived lot or one of another category, is added under
    its own name and lot number, so a row never shows an internal id."""
    try:
        from senaite.pfas.browser.reagents import _list_reagents
        recs = _list_reagents(portal,
                              category_filter=u"Standard / Reference Material")
    except Exception as exc:
        logger.warning("standard_lots: %s", exc)
        return []
    out = []
    for d in recs:
        lot = d.get("lot_number", "") or ""
        name = d.get("name", "") or ""
        expired = d.get("status") == "expired"
        label = u"{0} \u2014 lot {1}".format(name, lot) if lot else name
        if expired:
            label += u" (EXPIRED)"
        out.append({
            "uid": d.get("uid", ""), "lot_number": lot,
            "name": name, "label": label, "expired": expired,
            "mw": _certificate_masses(portal, d.get("uid", "")),
        })
    listed = set(o["uid"] for o in out)
    for uid in named:
        if not uid or uid in listed:
            continue
        listed.add(uid)
        try:
            from senaite.pfas.browser.reagents import _get_reagent
            d = _get_reagent(portal, uid)
        except Exception as exc:
            logger.warning("standard_lots %s: %s", uid, exc)
            d = None
        if not d:
            continue
        lot, name = d.get("lot_number", "") or "", d.get("name", "") or ""
        label = u"{0} \u2014 lot {1}".format(name, lot) if lot else name
        out.append({"uid": uid, "lot_number": lot, "name": name,
                    "label": label + (u" (archived)" if d.get("is_archived") else u""),
                    "expired": d.get("status") == "expired"})
    return sorted(out, key=lambda x: x["label"].lower())


def _certificate_masses(portal, uid):
    """{analyte: [molar mass of the acid, of the salt]} the lot's
    certificate values state, for the salt factor calculator; {} when the
    lot has no certificate values or states none."""
    from senaite.pfas import certificate_values as cv
    try:
        from senaite.pfas.annotation_store import read_json
        from senaite.pfas.browser.reagents import _get_reagents_folder
        obj = _get_reagents_folder(portal).get(uid) if uid else None
        cert = read_json(obj, cv.KEY, {}) if obj is not None else {}
    except Exception as exc:                                # noqa: BLE001
        logger.warning("certificate masses %s: %s", uid, exc)
        cert = {}
    return dict((a.get("analyte"), [a.get("mw_acid"), a.get("mw_salt")])
                for a in cert.get("analytes") or []
                if a.get("analyte") and a.get("mw_acid") and a.get("mw_salt"))


def lots_named_by(profiles):
    """The lot ids the salt rows of these method profiles hold."""
    return [r.get("lot_uid") or r.get("source") for p in profiles
            for r in (p or {}).get("salt_adjustment_factors") or [] if isinstance(r, dict)]


class PFASMethodProfilesView(ViewHelpers, BrowserView):
    """List all PFAS method profiles."""

    template = ViewPageTemplateFile("templates/method_profiles.pt")

    def is_manager(self):
        """Managers start a new method here (the New Method Wizard)."""
        return _require_manager(self.context, self.request)

    def read_only(self):
        """The list drawn view-only: no new method, no Issue revision."""
        return not self.is_manager()

    def __call__(self):
        flatten_form(self.request)
        if not _may_read(self.context, self.request):
            return refuse(self.request, "Forbidden: Manager, LabManager, or Owner role required")
        return self.template()

    def matrix_problems(self):
        """Profile matrices out of step with core's Sample Types (a rename
        where no event fired, an unlinked or deleted type, an alias that is
        now another matrix's name)."""
        from bika.lims import api
        from senaite.pfas import method_profile_store as mps
        from senaite.pfas.matrix_rename import consistency
        portal = _portal(self.context)
        try:
            titles = dict((api.get_uid(st), st.Title()) for st in
                          api.get_senaite_setup()["sampletypes"].objectValues())
            profiles = dict((m, mps.raw_profile(portal, m) or {}) for m in mps.list_method_ids(portal))
            return consistency(profiles, titles)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("matrix consistency: %s", exc)
            return []

    def issue_preview(self, mid):
        """What issuing `mid` now makes: {"label": "4.1", "level": "sub",
        "groups": ["Integration"]}; the level follows from what changed
        since the last issued revision (method_revisions.next_issue)."""
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
        portal = _portal(self.context)
        raw = raw_profile(portal, mid) or {}
        return mr.issue_preview(mid, mr.records(portal, mid), raw, method_toggles(raw, mid))

    @staticmethod
    def issue_sentence(preview):
        """The Issue dialog's line: "Issues revision 4.1: Integration
        changed."; "Level not known." when the preview could not be made."""
        from senaite.pfas import revision_level
        return revision_level.sentence(preview or {}) if preview else u""

    def methods(self):
        # read once per request: the table and its Issue dialogs share it
        if getattr(self, "_methods", None) is not None:
            return self._methods
        portal = _portal(self.context)
        from senaite.pfas.method_bridge import get_association, get_core_method
        # the stored profiles: a deleted method (a shipped one included) is
        # not listed again from the seeds
        all_ids = sorted(list_method_ids(portal))
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.browser.settings_report_view import _shown_revision
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
        proposals = mp.load(portal)
        result = []
        for mid in all_ids:
            p = get_profile(portal, mid)
            raw = raw_profile(portal, mid) or {}
            # _seeded=True means the profile was written by seed_default_profiles
            # and has not yet been edited by a user.
            # User-saved profiles don't include _seeded, so it defaults to False.
            is_customised = not p.get("_seeded", False)
            row = {
                "method_id": mid,
                "display_name": p.get("display_name", mid),
                "description": p.get("description", ""),
                "is_customised": is_customised,
                # profile ⇄ core SENAITE Method bridge (method_associations)
                "core_method_title": "",
                "core_method_url": "",
                "linked_services": 0,
                "linked_sampletypes": 0,
                # issued revisions
                "revision": _shown_revision(mr.status(mr.records(portal, mid), mr.fingerprints(
                    raw, method_toggles(raw, mid)))),
            }
            # changes proposed from a run, waiting for a countersign
            row["pending"] = len(mp.pending(proposals, mid))
            # what Issue revision would issue, for its dialog
            row["issue"] = (self.issue_preview(mid) if row["revision"]["unissued"] and not self.read_only()
                            else None)
            if get_association is not None:
                assoc = get_association(portal, mid)
                if assoc.get("method_uid"):
                    core = get_core_method(portal, mid)
                    row["core_method_title"] = assoc.get("method_title", "")
                    row["core_method_url"] = core.absolute_url() if core is not None else ""
                    row["linked_services"] = len(assoc.get("service_uids", []))
                    row["linked_sampletypes"] = len(assoc.get("sampletype_uids", []))
            result.append(row)
        self._methods = result
        return result


# ── Edit view ─────────────────────────────────────────────────────────────────

class PFASMethodProfileEditView(ViewHelpers, BrowserView):
    """Edit a single PFAS method profile."""

    template = ViewPageTemplateFile("templates/method_profile_edit.pt")

    def read_only(self):
        """The editor drawn view-only (the inspector reading it): no Save,
        no Delete, no edit window; every write is refused below."""
        return not _require_manager(self.context, self.request)

    # a proposed change's countersign and refusal: a manager, or the QA
    # approver sign right without a manager's role (the handler asks)
    PROPOSAL_DECISIONS = ("countersign_proposal", "refuse_proposal")
    PROPOSAL_ACTIONS = {"countersign_proposal": "_countersign_proposal",
                        "refuse_proposal": "_refuse_proposal",
                        "withdraw_proposal": "_withdraw_proposal",
                        # a manager's edit, as any other save
                        "remove_processing": "_remove_processing"}

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST" and self.request.form.get("action") in self.PROPOSAL_DECISIONS:
            # the right is asked before anything is read: no proposal's
            # state is told to one who may not decide it
            rights = self._rights()
            if not (rights["manager"] or rights["qa"]):
                return refuse(self.request, mp.NO_RIGHT)
            return getattr(self, self.PROPOSAL_ACTIONS[self.request.form["action"]])()
        # a manager reads and writes; the read-only inspector reads by GET
        # (the JSON reads below included) and posts nothing
        if not _require_manager(self.context, self.request):
            if not _may_read(self.context, self.request):
                return refuse(self.request, "Forbidden: Manager, LabManager, or Owner role required")
            if self.request.form.get("delete"):
                return refuse(self.request, "Forbidden: Manager, LabManager, or Owner role required")

        if self.request.form.get("_preview") == "rt":
            return self._preview_recovery_grid()
        if self.request.form.get("_copy_from") and self.request.method == "GET":
            return self._copy_values()
        if self.request.form.get("_copy_tiers") and self.request.method == "GET":
            return self._tier_differences()
        if self.request.method == "POST":
            if self.request.form.get("action") == "delete_method":
                return self._delete_method()
            # withdraw and remove past the manager's gate above
            if self.request.form.get("action") in self.PROPOSAL_ACTIONS:
                return getattr(self, self.PROPOSAL_ACTIONS[self.request.form["action"]])()
            return self._handle_post()
        return self.template()

    # ── Delete method (method_delete.py) ──────────────────────────────────────

    def delete_requested(self):
        """The confirm step: what uses the method, or what a deletion removes."""
        return self.request.form.get("delete") == "check" and bool(self.method_id())

    def delete_report(self):
        """{"uses": [(what, which)], "removes": [(what, which)]}. A failure to
        read is a use ("Could not be checked"), never a free method."""
        if not hasattr(self, "_delete_report"):
            from senaite.pfas import method_delete
            try:
                uses, removes = method_delete.report(_portal(self.context), self.method_id())
            except Exception as exc:                        # noqa: BLE001
                logger.exception("delete check for %s", self.method_id())
                uses, removes = [(u"Could not be checked", u"%s" % exc)], []
            self._delete_report = {"uses": uses, "removes": removes}
        return self._delete_report

    def _delete_method(self):
        """POST: delete the method when nothing uses it (read again here);
        refused, back to the confirm step that lists what uses it."""
        import transaction
        from senaite.pfas import method_delete
        try:
            from plone.protect import CheckAuthenticator
            CheckAuthenticator(self.request)
        except ImportError:
            pass
        mid = self.method_id()
        portal = _portal(self.context)
        if self.request.form.get("confirm") != "yes":
            return self._redirect_error(mid, u"Not deleted: confirm the deletion.")
        label = self.display_name()
        try:
            method_delete.delete(portal, mid)
        except method_delete.MethodInUse:
            transaction.abort()
            self.request.response.redirect(
                "{0}/@@pfas-method-profile-edit?method_id={1}&delete=check".format(
                    self.context.absolute_url(), urllib.quote(mid.encode("utf-8"))))
            return u""
        except Exception as exc:                            # noqa: BLE001
            transaction.abort()
            logger.exception("method %s not deleted", mid)
            return self._redirect_error(mid, u"Not deleted: {0}".format(exc))
        self.request.response.redirect("{0}/@@pfas-method-profiles?ok={1}".format(
            portal.absolute_url(), urllib.quote(u"{0} deleted.".format(label).encode("utf-8"))))
        return u""

    # ── Template helpers ──────────────────────────────────────────────────────

    def method_id(self):
        return self.request.form.get("method_id", "").strip()

    def profile(self):
        mid = self.method_id()
        if not mid:
            return {}
        return get_profile(_portal(self.context), mid)

    def saved(self):
        return self.request.form.get("saved", "") == "1"

    def error(self):
        return self.request.form.get("error", "")

    def note(self):
        """What a saved action did, named on the page (e.g. a standard removed
        with its limits)."""
        return self.request.form.get("note", "")

    # Convenience accessors for individual profile sections.
    #
    # These read the NESTED instrument_verification structure, which is what
    # the engine enforces. They used to read the retired flat keys, so the
    # editor showed — and saved — values nothing applied: the CCV window said
    # 72-128% here while every run was judged against the nested 70-130%.
    def _iv_section(self, nested, legacy):
        profile = self.profile()
        section = (profile.get("instrument_verification") or {}).get(nested)
        if section:
            return section
        return profile.get(legacy, {})

    def cal(self):
        return self._iv_section("calibration", "calibration")

    def ccv(self):
        return self._iv_section("ccv", "ccv")


    def confirmation(self):
        return self._iv_section("confirmation", "confirmation")

    # The QC type whose tiers the Recovery Tiers grid edits. Recovery tiers are
    # an LFSM concept: LFSMD carries RPD as well, Dup carries only RPD, and MB
    # is judged against the reporting limit.
    RECOVERY_TIER_QC_TYPE = "LFSM"

    def per_analyte_notes(self):
        """Notes typed on the retired Per-Analyte table, listed under the
        method's label for the analyte until each is moved by hand and
        discarded: [{analyte, label, notes}]."""
        from senaite.pfas import compound_library, compound_library_store
        from senaite.pfas.method_profile_sections import _analyte_titles
        profile = self.profile()
        labels = _analyte_titles(profile)
        library = compound_library_store.library()
        out = []
        for row in profile.get("per_analyte") or []:
            if not isinstance(row, dict) or not (row.get("notes") or "").strip():
                continue
            kw = compound_library.keyword_of(library, row.get("analyte")) or row.get("analyte")
            out.append({"analyte": row.get("analyte"),
                        "label": labels.get(kw) or row.get("analyte"),
                        "notes": row["notes"].strip()})
        return out

    def standard_lot_options(self):
        """Standard / Reference-Material lots from the reagent inventory, for
        the CoA-lot dropdown (standard_lots)."""
        return standard_lots(_portal(self.context), lots_named_by([self.profile()]))

    def extraction_stages_json(self):
        stages = self.profile().get("extraction_stages", [])
        return json.dumps(sorted(stages, key=lambda s: s.get("order", 0)), indent=2)

    # ── Analytes tab ─────────────────────────────────────────────────────────

    # ── Copy tiers from method: the tier lists of another method ─────────

    def _tier_plan(self, portal, other):
        """tier_copy.plan of `other`'s tiers onto this method, or None when
        `other` is no other method."""
        from senaite.pfas import tier_copy
        from senaite.pfas.method_profile_store import list_method_ids, raw_profile
        mid = self.method_id()
        if not other or other == mid or other not in list_method_ids(portal):
            return None
        return tier_copy.plan(raw_profile(portal, mid) or {}, raw_profile(portal, other) or {})

    def _tier_differences(self):
        """GET ?_copy_tiers=<method>: what replacing this method's tiers by
        that method's would change, as JSON. Reads only; Replace posts
        action=copy_tiers."""
        from senaite.pfas.method_profile_store import raw_profile
        portal = _portal(self.context)
        other = self.request.form.get("_copy_tiers", "").strip()
        self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
        found = self._tier_plan(portal, other)
        if found is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": u"No such method."})
        return json.dumps({"method": (raw_profile(portal, other) or {}).get("display_name") or other,
                           "types": found["types"], "skipped": found["skipped"], "errors": found["errors"]})

    def copy_tier_methods(self):
        """The other methods, as JSON [[id, name]], for Copy tiers from
        method; "" when there is none."""
        others = self._other_methods()
        return json.dumps([[m, n] for m, n in others]) if others else u""

    def tier_stamps(self):
        """[(input name, stamp)] of every tier section, for Replace."""
        from senaite.pfas import profile_grids
        return [("section_stamp__" + sid, self.section_stamp(sid)) for _qc, sid in profile_grids.TIER_SECTIONS]

    def _copy_tiers(self, portal, mid):
        """Replace this method's tiers of each QC type both methods run by
        the other method's (tier_copy.plan): refused when a tier section
        changed since the page was drawn, or when the copy would be refused
        as an edit would. The change history names the source method."""
        from senaite.pfas import config_forms, profile_grids
        from senaite.pfas.method_profile_sections import PROFILE_CHECKS, SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        form = self.request.form
        pane = "pane-qc"
        stored = raw_profile(portal, mid)
        if not stored:
            return self._redirect_error(mid, u"No profile for %s" % mid, pane)
        env = self.section_env()
        for _qc, sid in profile_grids.TIER_SECTIONS:
            if (form.get("section_stamp__" + sid) or "").strip() != config_forms.stamp(SECTIONS[sid], stored, env):
                return self._redirect_error(mid, (
                    u"Not copied: {0} changed after you opened it. Reload to see the "
                    u"change, then try again.").format(SECTIONS[sid].title), pane)
        other = (form.get("source") or "").strip()
        found = self._tier_plan(portal, other)
        if found is None:
            return self._redirect_error(mid, u"Not copied: choose another method.", pane)
        if found["errors"]:
            return self._redirect_error(mid, u"Not copied: " + u" ".join(found["errors"]), pane)
        if not found["types"]:
            return self._redirect_error(mid, u"Not copied: the two methods run no QC type in common.", pane)
        profile = get_profile(portal, mid)
        for t in found["types"]:
            profile.setdefault("qc_acceptance", {})[t["qc"]] = found["profile"]["qc_acceptance"][t["qc"]]
        for watched, check in PROFILE_CHECKS:
            if set(watched) & set(sid for _qc, sid in profile_grids.TIER_SECTIONS):
                problems = check(profile)
                if problems:
                    return self._redirect_error(mid, u"Not copied: " + u" ".join(problems), pane)
        profile.pop("_seeded", None)
        name = (raw_profile(portal, other) or {}).get("display_name") or other
        done = u"Recovery tiers copied from {0}".format(name)
        save_profile(portal, mid, profile, label=done)
        return self._redirect_saved(mid, pane, note=done)

    # ── Copy from method: another method's values for one grid ──────────────

    def _other_methods(self):
        """[(method id, name)]: every other method with a profile."""
        from senaite.pfas.method_profile_store import list_method_ids, raw_profile
        portal, mine = _portal(self.context), self.method_id()
        out = []
        for mid in sorted(list_method_ids(portal)):
            if mid != mine:
                out.append((mid, (raw_profile(portal, mid) or {}).get("display_name") or mid))
        return out

    def _copyable(self, sheet, tab):
        sheet.copy_from = (tab, self._other_methods())
        return sheet

    def _copy_values(self):
        """GET ?_copy_from=<method>&_tab=<tab>: that method's values for the
        grid on `tab`, by posted name, as JSON. Reads only; the page shows
        them against this method's and writes none until the person applies
        them, and the tab's own Save stores them."""
        from senaite.pfas import profile_grids
        from senaite.pfas.method_profile_store import list_method_ids, raw_profile
        portal = _portal(self.context)
        other, tab = self.request.form.get("_copy_from", "").strip(), self.request.form.get("_tab", "").strip()
        self.request.response.setHeader("Content-Type", "application/json; charset=utf-8")
        if other not in list_method_ids(portal) or other == self.method_id() or tab not in profile_grids.COPY_TABS:
            self.request.response.setStatus(404)
            return json.dumps({"error": u"No such method or grid."})
        profile = raw_profile(portal, other) or {}
        return json.dumps({"method": profile.get("display_name") or other,
                           "values": profile_grids.copy_values(profile, self.section_env(), tab)})

    def analytes_sheet(self):
        """The Analytes tab's grid, drawn from the stored profile and the
        page's section env: the same value the section stamps and the save
        read, so what is drawn is what a stale-save check compares; built
        once per request, as the list beside it reads the same rows."""
        if getattr(self, "_analytes_sheet", None) is None:
            from senaite.pfas import profile_grids
            from senaite.pfas.method_profile_store import raw_profile
            self._analytes_sheet = self._copyable(
                profile_grids.analytes_sheet(raw_profile(_portal(self.context), self.method_id()),
                                             self.section_env()), "analytes")
        return self._analytes_sheet

    def analytes_list_html(self):
        """The Analytes tab's List view: Regulated analytes, Other analytes
        and Method settings, each row beside its card; of an analyte it
        posts nothing (the grid does), and its Method settings card holds
        Surrogate recovery in a diluted sample with its posted input."""
        from senaite.pfas import profile_grids
        return profile_grids.render_analytes_list(self._raw(), self.section_env(), self.analytes_sheet(),
                                                  self.dilution_recovery_html(), self.analyte_set_confirmed())

    # ── Labelled standards tab ───────────────────────────────────────────────

    def standards_sheet(self):
        """The Labelled standards tab's grid, drawn from the stored profile
        and the page's section env, as the stamps and the save read them;
        built once per request, as the list beside it reads the same rows."""
        if getattr(self, "_standards_sheet", None) is None:
            from senaite.pfas import profile_grids
            self._standards_sheet = self._copyable(profile_grids.standards_sheet(self._raw(), self.section_env()),
                                                   "standards")
        return self._standards_sheet

    def standards_rules_sheet(self):
        """The rules the Isotope standards tab holds (IS Response, IS vs
        CCV, Surrogate Recovery), their states posting to its form; drawn
        once per request, as the list's group cards write the same inputs."""
        if getattr(self, "_standards_rules", None) is None:
            from senaite.pfas import profile_grids
            self._standards_rules = profile_grids.standards_rules_table(self._raw(), self.section_env())
        return self._standards_rules

    def standards_link_warning(self):
        """The Isotope standards tab's warning: each surrogate with no Linked
        to, which the tab's Save refuses (LINK_CHECKS); "" with none."""
        from senaite.pfas import profile_grids
        return profile_grids.standards_link_warning(self._raw())

    def analytes_link_warning(self):
        """The Analytes tab's warning: each analyte reported in a matrix with
        no Quantified by, which the tab's Save refuses; "" with none."""
        from senaite.pfas import profile_grids
        return profile_grids.analytes_link_warning(self._raw())

    def dilution_recovery_html(self):
        """The Analytes tab's Surrogate recovery in a dilution, its posted
        input with it (profile_grids.render_dilution_recovery)."""
        from senaite.pfas import profile_grids
        return profile_grids.render_dilution_recovery(self._raw(), self.section_env())

    def analytes_table_settings_html(self):
        """The Analytes tab's Method settings under the sheet: the dilution
        setting's tile, writing the one input the List's card holds."""
        from senaite.pfas import profile_grids
        return profile_grids.analytes_table_settings(self._raw(), self.section_env())

    def standards_list_html(self):
        """The Isotope standards tab's List view: the grid's rows grouped SUR
        and IS, each group opening on its rules and the tab's other settings
        of the group, each standard beside its card; it posts nothing (the
        grid, the rules block and the sections under it post)."""
        from senaite.pfas import profile_grids
        return profile_grids.render_standards_list(self._raw(), self.section_env(), self.standards_sheet(),
                                                   self.standards_rules_sheet(), self.section_groups)

    # ── Matrices tab ─────────────────────────────────────────────────────────

    def matrices_sheet(self):
        """The Matrices tab's grid, drawn from the stored profile and the
        page's section env, as the stamps and the save read them; built once
        per request, as the list beside it reads the same rows."""
        if getattr(self, "_matrices_sheet", None) is None:
            from senaite.pfas import profile_grids
            self._matrices_sheet = self._copyable(profile_grids.matrices_sheet(self._raw(), self.section_env()),
                                                  "matrices")
        return self._matrices_sheet

    def storage_conflicts(self):
        """Each fridge or freezer holding this method's matrices whose storage
        ranges do not overlap ("Freezer B: ... ranges"): a setting to fix,
        said where the ranges are set (matrix_temperature.method_conflicts)."""
        from senaite.pfas import facility_qc as db
        from senaite.pfas import matrix_temperature as mt
        from senaite.pfas.method_profile_store import raw_profile
        portal = _portal(self.context)
        try:
            units = db.list_units()
        except Exception as exc:                            # noqa: BLE001
            logger.warning("storage conflicts: %s", exc)
            return []
        return mt.method_conflicts(self.method_id(), units, lambda mid: raw_profile(portal, mid),
                                   self.section_env().get("homogenised"))

    def matrices_list_html(self):
        """The Matrices tab's List view: All matrices, then each matrix
        beside its card, then the Correction group; it posts nothing (the
        grid and Sample correction post)."""
        from senaite.pfas import profile_grids
        return profile_grids.render_matrices_list(self._raw(), self.section_env(), self.matrices_sheet(),
                                                  self.section_groups)

    def run_list_html(self):
        """Run & reporting's List view: Run, Extraction, Channels and
        Reporting, each row beside its card; it posts nothing (the folds of
        the Table view post)."""
        from senaite.pfas import profile_cards
        # the site's address, for Action levels' Open Regulatory Limits
        env = dict(self.section_env(), portal_url=_portal(self.context).absolute_url())
        return profile_cards.render_run_list(self._raw(), env, self.run_template_editor(),
                                             self.section_groups)

    def engine_list_html(self):
        """Engine's List view: Names, Matrices, Results and Studies, each
        group's node beside its card; it posts nothing (the folds of the
        Table view post)."""
        from senaite.pfas import profile_cards
        return profile_cards.render_engine_list(self._raw(), self.section_env(), self.section_groups,
                                                (self.display_name(), self.description()))

    def report_format_list_html(self):
        """Certificate format's List view: All matrices, then each matrix
        with what it sets; it posts nothing (the table posts)."""
        from senaite.pfas import profile_grids
        return profile_grids.render_report_format_list(self._raw(), self.section_env(), self.section_groups("rf"))

    def integration_list_html(self):
        """Integration's List view: the method defaults, then each compound
        that sets its own, and every compound's transitions and windows; it
        posts nothing (the form and the table post)."""
        from senaite.pfas import profile_grids
        return profile_grids.render_integration_list(self._raw(), self.section_env(), self.section_groups("intg"),
                                                     self.section_groups("intg_an"))

    def _engine(self):
        from senaite.pfas import method_engine
        return method_engine.engine(self.profile())

    def analyte_matrix_needs_verification(self):
        # a published method's inclusion is confirmed against its text; a
        # method whose values are the lab's own is not (Engine setting)
        return self._engine()["inclusion_needs_verification"]

    def analyte_set_confirmed(self):
        """The note the verification banner becomes while the flag is off:
        who turned it off and when, or that the analyte set is not flagged
        when no confirmation is on record. The history is read once per
        request."""
        if not hasattr(self, "_confirmed_note"):
            from senaite.pfas import config_history, profile_grids
            entry = config_history.last_change(_portal(self.context), "method_profile", self.method_id(),
                                               path=profile_grids.CONFIRMED_PATH)
            self._confirmed_note = profile_grids.confirmed_note(entry) or profile_grids.NOT_FLAGGED
        return self._confirmed_note

    # ── Surrogate IS lane data ────────────────────────────────────────────────

    def _pfas_service_index(self):
        """{keyword: {role, name, uid, url}} for every core AnalysisService
        that carries a pfas_role: the source for the analyte / surrogate / IS
        lists, pulled from the services that report, not code tables. The
        native-to-surrogate link is each method's own Surrogate Map."""
        from senaite.pfas.method_profile_store import service_index
        return service_index()


    def display_name(self):
        return self.profile().get("display_name", self.method_id())

    def description(self):
        return self.profile().get("description", "")

    # ── POST handler ──────────────────────────────────────────────────────────

    @staticmethod
    def _stamp_value(portal, mid):
        """What this editor saves for one method: the stored profile (its rule
        switches included since QC consolidation P2), so any colleague's save
        makes an open page stale."""
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.config_history import IGNORED_KEYS
        profile = dict((k, v) for k, v in raw_profile(portal, mid).items()
                       if k not in IGNORED_KEYS and k not in ("updated_at", "updated_by", "_seeded"))
        return {"profile": profile}

    def config_stamp(self):
        """Version stamp of what this editor saves, carried by the form."""
        from senaite.pfas import config_history
        return config_history.stamp(self._stamp_value(_portal(self.context), self.method_id()))

    def last_change(self):
        """This profile's newest history entry, its time shown on the
        laboratory's clock."""
        from senaite.pfas import config_history
        entry = config_history.last_change(_portal(self.context), "method_profile",
                                           self.method_id())
        return dict(entry, at=config_history.shown_at(entry["at"])) if entry else entry

    def integration_log(self):
        """The Integration section's change log: this method's history kept to
        where results come from, the method defaults and each compound's
        overrides (method_profile_sections.integration_log)."""
        from senaite.pfas import config_history, method_profile_sections
        portal, mid = _portal(self.context), self.method_id()
        return method_profile_sections.integration_log(
            lambda offset, n: config_history.entries(portal, "method_profile", mid, limit=n, offset=offset))

    # ── declared sections (R2, config_forms) ─────────────────────────────────
    # A tab migrated to config_forms is its own form and its own save: only its
    # fields are parsed, against its own stamp, and nothing else in the POST
    # chain runs -- the rule-toggle and surrogate-link writers read fields this
    # form does not carry, and would switch every rule off / rewrite the links.

    # ── QC criteria tab ──────────────────────────────────────────────────────

    def _raw(self):
        """The stored profile, read once per request: the page's builders and
        its two dozen summaries only read it (tests/test_profile_tabs.py
        holds them to that)."""
        if getattr(self, "_raw_profile", None) is None:
            from senaite.pfas.method_profile_store import raw_profile
            self._raw_profile = raw_profile(_portal(self.context), self.method_id())
        return self._raw_profile

    def run_limit_states(self):
        """[(input name, state)]: the limit boxes Run & reporting posts
        (limit_states.RUN_BOXES), each the state it reads."""
        from senaite.pfas import limit_placard, limit_states
        return limit_placard.hidden_values(self._raw(), list(limit_states.RUN_BOXES))

    def rules_table(self):
        """The rule table, drawn from the stored profile and the page's
        section env, as the stamps and the save read them; built once per
        request, as the list beside it reads the same rows."""
        if getattr(self, "_rules_sheet", None) is None:
            from senaite.pfas import profile_grids
            self._rules_sheet = profile_grids.rules_table(self._raw(), self.section_env())
        return self._rules_sheet

    def flag_choices_json(self):
        """The codes and places every Flag tile's window offers (once per page)."""
        from senaite.pfas import profile_grids
        url = "%s/%s" % (_portal(self.context).absolute_url(), profile_grids.QUALIFIERS_PAGE)
        return profile_grids.flag_choices_json(self.section_env(), url)

    def rules_list_html(self):
        """The Rules section's List view: the rule table's rows grouped,
        each group beside its card; it posts nothing (the Table view posts).
        A card's tiles read the sections as the Table view draws them."""
        from senaite.pfas import profile_grids
        # the site's address, for a card's row that goes to another page
        env = dict(self.section_env(), portal_url=_portal(self.context).absolute_url())
        return profile_grids.render_rules_list(self._raw(), env, self.rules_table(),
                                               self.section_groups, self.copy_tier_methods())

    def windows_sheet(self):
        """The applied windows (LFSM, ordinary spike) the tab opens on."""
        from senaite.pfas import profile_grids
        return profile_grids.windows_sheet(self._raw(), self.section_env(), kept=True)

    def windows_box(self):
        """The grid's region as the tab opens on it: the sheet in its box,
        greyed while the QC type shown is Off."""
        from senaite.pfas import profile_grids
        raw = self._raw()
        return profile_grids.windows_box(raw, self.section_env(), "LFSM",
                                         profile_grids.render_sheet(self, self.windows_sheet()))

    def windows_controls(self):
        from senaite.pfas import profile_grids
        return profile_grids.windows_controls(self._raw(), self.section_env())

    def rule_editors(self):
        from senaite.pfas import profile_grids
        return profile_grids.rule_editors(self._raw(), self.section_env())

    def section_part(self, part):
        """What one region part draws: a whole section, or one group of it."""
        groups = self.section_groups(part["sid"])
        if part["kind"] != "section" or not part.get("group"):
            return groups
        return [g for g in groups if g["title"] == part["group"]]

    def _preview_recovery_grid(self):
        """The applied-window grid for the QC criteria form AS EDITED, not
        saved (profile_grids.preview_windows: the same parse and apply a save
        runs, the same resolver the page draws with), then the tiers of the
        same edits as the Rules list draws them under each QC type
        (profile_grids.preview_tree, <div id="qc-tree">). Nothing is
        written. A form that does not parse returns the grid's refusal
        alone: the list stays as drawn."""
        from senaite.pfas import profile_grids
        html, errors = profile_grids.preview_windows(self._raw(), self.request.form, self.section_env())
        if errors:
            self.request.response.setHeader("X-Preview-Errors", "1")
            return u'<div id="qc-windows"><p class="alert alert-error">%s</p></div>' % (
                escape(u" ".join(errors)))
        self.request.response.setHeader("Content-Type", "text/html; charset=utf-8")
        tree = profile_grids.preview_tree(self._raw(), self.request.form, self.section_env())
        box = profile_grids.windows_box(self._raw(), self.section_env(),
                                        self.request.form.get("qc_type") or "LFSM", html)
        return box + tree

    # ── one home per setting ─────────────────────────────────────
    def run_template_editor(self):
        """The method's run template as the editor draws it (the Run Builder
        builds every run from it); read once per request, as the Table view's
        table and the List view's card both draw it."""
        if "_run_template" not in self.__dict__:
            self._run_template = self._run_template_editor()
        return self._run_template

    def _run_template_editor(self):
        try:
            from zope.component import getMultiAdapter
            rb = getMultiAdapter((self.context, self.request), name="pfas-run-builder")
            mid = self.method_id()
            return {"tpl": rb.current_template(mid), "vocab": rb.add_vocabulary(), "ccv": rb.ccv_interval(mid)}
        except Exception as exc:                            # noqa: BLE001
            logger.warning("run template editor: %s", exc)
            return None

    def qc_section_ids(self):
        """Every section form#section-qc saves (and carries a stamp for)."""
        from senaite.pfas import profile_grids
        return profile_grids.qc_section_ids(self._raw())

    def calibration_base_levels_json(self):
        """The method's base ladder, for the per-analyte range note that
        recomputes as a multiple or a highest standard is typed."""
        import json
        from senaite.pfas import calibration_levels as cl
        base = sorted(v for v in (cl._num(r["conc"]) for r in cl.rows(self.profile())) if v is not None)
        return json.dumps(base)

    def recommended_spikes(self):
        """Low / Mid / High from this method's calibration levels: in the
        level unit, and per matrix in that matrix's reporting unit (the spike
        grids' unit); None without at least two levels."""
        import json
        from senaite.pfas import calibration_levels as cl
        profile = self.profile()
        base = cl.recommended_spikes(profile)
        if not base:
            return None
        fmt = cl.fmt
        per = []
        for m in profile.get("supported_matrices") or []:
            rec = cl.recommended_spikes_in_unit(profile, m)
            per.append({"matrix": m, "unit": cl.matrix_unit(profile, m),
                        "low": fmt(rec.get("Low")), "mid": fmt(rec.get("Mid")),
                        "high": fmt(rec.get("High")), "ok": bool(rec)})
        return {"unit": cl.unit(profile), "low": fmt(base["Low"]), "mid": fmt(base["Mid"]),
                "high": fmt(base["High"]), "matrices": per,
                "missing": [p["matrix"] for p in per if not p["ok"]],
                "any": any(p["ok"] for p in per),
                "json": json.dumps([[p["low"], p["mid"], p["high"]] for p in per])}

    def section_env(self):
        """What a declared section needs from the site that the profile does
        not hold: the reagent inventory's standard lots (salt CoA lots), the
        services, and the regulatory limits (Reporting tab)."""
        if getattr(self, "_section_env", None) is None:
            from senaite.pfas import fit_accept, regulatory_limits
            self._section_env = {"fit_accept_default": fit_accept.load(_portal(self.context)),
                                 "standard_lots": self.standard_lot_options(),
                                 "services": self._pfas_service_index(),
                                 "qc_codes": self._qc_codes(),
                                 "regulatory": regulatory_limits.get_store(_portal(self.context)),
                                 # a field governed by a rule switch reads N/A while it is off
                                 "rules": self._rule_state(), "rule_labels": self._rule_labels(),
                                 # Storage and holding: the matrices homogenised by default
                                 "homogenised": self._homogenised_matrices(),
                                 # the units that name each matrix among what they hold
                                 "held_by": self._held_by(),
                                 # each rule's Flag: the QC Qualifiers entries its Code offers
                                 "qualifiers": self._qualifier_library()}
        return self._section_env

    def _qualifier_library(self):
        """The QC Qualifiers library (its seeds when it cannot be read)."""
        from senaite.pfas import qc_qualification
        try:
            return qc_qualification.get_library(_portal(self.context))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("qualifier library: %s", exc)
            return qc_qualification.library_from({})

    def _homogenised_matrices(self):
        """The Sample Types whose default homogenisation is a method (not
        blank, not "Not homogenised"); a processed-sample clock elsewhere
        reads "not homogenised", and the matrix draws no processed range."""
        from senaite.pfas import homogenisation as hg
        return hg.homogenised_titles()

    def _held_by(self):
        """{matrix: [unit names]}: the units whose list of matrices held
        names the matrix for this method (matrix_temperature.units_holding),
        named on the matrix's Remove."""
        from senaite.pfas import facility_qc as db
        from senaite.pfas import matrix_temperature as mt
        try:
            return mt.units_holding(self.method_id(), db.list_units())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("units holding matrices: %s", exc)
            return {}

    def _rule_state(self):
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
        try:
            mid = self.method_id()
            return method_toggles(raw_profile(_portal(self.context), mid), mid)
        except Exception:                                   # noqa: BLE001
            return {}

    def _rule_labels(self):
        from senaite.pfas.qc.rules import RULE_LIBRARY
        return dict((r["key"], r["label"]) for r in RULE_LIBRARY)

    def _qc_codes(self):
        """The QC type codes the lab defines (the tagged Reference Definitions)."""
        from senaite.pfas import qc_labels
        try:
            return sorted(qc_labels.get_qc_label_map(_portal(self.context)).keys())
        except Exception:
            return []

    def section_groups(self, section_id):
        """A section as drawn (config_forms.render), rendered once per page:
        a tier collection's pickers, drawn under "Who each tier applies to",
        come from the render that drew its table."""
        cache = self.__dict__.setdefault("_section_groups", {})
        if section_id not in cache:
            from senaite.pfas import config_forms
            from senaite.pfas.method_profile_sections import SECTIONS
            from senaite.pfas.method_profile_store import raw_profile
            from senaite.pfas import profile_grids
            profile = raw_profile(_portal(self.context), self.method_id())
            # as the tab's fold shows it: a field the tab's grid holds is the grid's
            cache[section_id] = profile_grids.fold_groups(
                section_id, config_forms.render(SECTIONS[section_id], profile, self.section_env()), profile)
        return cache[section_id]

    def section_summary(self, sid):
        """The one phrase a section's summary line states
        (profile_grids.section_summary); the run template's steps come from
        the Run Builder and the retired notes from the profile, counted here."""
        from senaite.pfas import profile_grids
        if sid == "run_template":
            rte = self.run_template_editor()
            tpl = rte["tpl"] if rte else None
            return profile_grids.counted(len((tpl or {}).get("sequence_labelled") or []), u"step")
        if sid == "notes":
            return profile_grids.counted(len(self.per_analyte_notes()), u"note")
        return profile_grids.section_summary(self._raw(), self.section_env(), sid)

    def section_help(self, sid):
        """The Help entry a section's header opens
        (help_dictionary.SECTION_HELP); a section with none opens the method
        profile's own."""
        from senaite.pfas import help_dictionary
        return help_dictionary.SECTION_HELP.get(sid, u"method-profile")

    def section_stamp(self, section_id):
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        return config_forms.stamp(SECTIONS[section_id],
                                  raw_profile(_portal(self.context), self.method_id()),
                                  self.section_env())

    def _save_section(self, portal, mid, section_ids):
        """Save the declared section(s) one tab's form carries ("_section" is a
        comma-separated list; each carries its own section_stamp__<id>). All
        are checked before any is applied: one stale or refused section saves
        nothing, so a tab is never left half-saved."""
        from senaite.pfas import config_forms, config_history
        from senaite.pfas.method_profile_sections import SECTIONS
        from senaite.pfas.method_profile_store import raw_profile
        form = self.request.form
        pane = (form.get("_pane") or "").strip()
        ids = [i.strip() for i in section_ids.split(",") if i.strip()]
        sections = [SECTIONS.get(i) for i in ids]
        if not ids or None in sections:
            return self._redirect_error(mid, "Unknown section: %s" % section_ids)
        pane = pane or "pane-" + ids[0]
        stored = raw_profile(portal, mid)
        if not stored:
            return self._redirect_error(mid, "No profile for %s" % mid, pane)
        env = self.section_env()
        for section in sections:
            sent = (form.get("section_stamp__" + section.id) or "").strip()
            if sent != config_forms.stamp(section, stored, env):
                last = config_history.last_change(portal, "method_profile", mid) or {}
                return self._redirect_error(mid, (
                    u"Not saved: {0} was changed by {1} at {2} after you opened "
                    u"it. Reload to see their change, then re-apply yours.").format(
                        section.title, last.get("who", "someone"),
                        config_history.shown_at(last.get("at", "?"))), pane)
        # parsed with the panel as posted: an RL typed for a cell reported in
        # this save is read, a matrix left out lists no RL row
        from senaite.pfas.profile_form import posted_panel
        base = posted_panel(stored, form)
        parsed, errors = [], []
        for section in sections:
            updates, errs = config_forms.parse(section, form, base, env)
            parsed.append((section, updates))
            errors.extend(errs)
        if errors:
            return self._redirect_error(mid, u"Not saved: " + u" ".join(errors), pane)
        profile = get_profile(portal, mid)
        # a tier renamed in this save carries what is posted under its stored name
        from senaite.pfas.profile_form import carry_renamed_tiers
        profile = carry_renamed_tiers(profile, form, parsed, env)
        for section, updates in parsed:
            profile = config_forms.apply(section, profile, updates, env)
        # the switches, names and grids this tab's form carries besides its
        # sections: only what it carries is applied
        from senaite.pfas.profile_form import apply_loose
        from senaite.pfas.qc.rules import RULE_LIBRARY, method_toggles
        apply_loose(profile, form, [r["key"] for r in RULE_LIBRARY], current=method_toggles(stored, mid))
        stages = profile.pop("extraction_stages_json_raw", None)
        if stages is not None:
            profile["extraction_stages"] = _stages_from_form(stages)
        from senaite.pfas.method_profile_sections import LINK_CHECKS, LINKED_RATIO, PROFILE_CHECKS, migrate_linked_ratio
        if LINKED_RATIO.id in ids:
            migrate_linked_ratio(profile)
        # a tab's Save also refuses while a link it holds is missing
        for watched, check in PROFILE_CHECKS + LINK_CHECKS:
            if set(watched) & set(ids):
                problems = check(profile)
                if problems:
                    return self._redirect_error(mid, u"Not saved: " + u" ".join(problems), pane)
        # A user-saved profile is no longer factory-default (the installer
        # re-runs on every start and treats _seeded profiles as its own).
        profile.pop("_seeded", None)
        save_profile(portal, mid, profile)
        return self._redirect_saved(mid, pane)

    def _standards_action(self, portal, mid, action):
        """Add a labelled standard to the method or remove some: membership
        is presence. An added standard is a SUR linked to nothing. Remove
        takes the ticked rows (one from a row's menu): while any native's
        Quantified by points at one of them, nothing is removed and each is
        named with its natives (the server refuses, whatever the page
        offered). Refused when the standards changed since the page was
        drawn, and the whole-profile checks on the standards still hold
        after either."""
        from senaite.pfas import config_forms, labelled_standards, profile_grids
        from senaite.pfas.method_profile_sections import (PROFILE_CHECKS, SECTIONS, drop_eis_limits,
                                                          eis_names_for)
        from senaite.pfas.method_profile_store import raw_profile
        form = self.request.form
        pane = "pane-standards"
        picked = form.get("standard") or []
        picked = [picked] if not isinstance(picked, (list, tuple)) else picked
        kws = []
        for k in picked:                    # each once, in the order ticked
            k = (k or "").strip()
            if k and k not in kws:
                kws.append(k)
        kw = kws[0] if kws else u""
        stored = raw_profile(portal, mid)
        if not stored:
            return self._redirect_error(mid, u"No profile for %s" % mid, pane)
        env = self.section_env()
        section = SECTIONS["ls"]
        if (form.get("section_stamp__ls") or "").strip() != config_forms.stamp(section, stored, env):
            return self._redirect_error(mid, (
                u"Not saved: {0} changed after you opened it. Reload to see the "
                u"change, then try again.").format(section.title), pane)
        profile = get_profile(portal, mid)
        grid = dict(labelled_standards.grid(profile))
        if action == "add_standard":
            if kw not in [k for k, _l in profile_grids.standards_to_add(stored, env)]:
                return self._redirect_error(
                    mid, u"Not added: choose an isotope standard this method does not use yet.", pane)
            grid[kw] = {"role": u"surrogate", "reference": u""}
            done = u"Added {0}".format(kw)
        else:
            if not kws:
                return self._redirect_error(mid, u"Not removed: tick the standards to remove.", pane)
            unknown = [k for k in kws if k not in grid]
            if unknown:
                return self._redirect_error(mid, u"Not removed: {0} {1} not one of this method's standards.".format(
                    u", ".join(unknown), u"is" if len(unknown) == 1 else u"are"), pane)
            blocked = [(k, labelled_standards.removal_blocked_by(profile, k)) for k in kws]
            blocked = [u"{0}: it quantifies {1}".format(k, u", ".join(n)) for k, n in blocked if n]
            # a member of a composite stays while the composite averages it
            blocked += [u"{0}: it is a member of {1}".format(k, u", ".join(held)) for k, held in
                        [(k, labelled_standards.composites_holding(profile, k)) for k in kws]
                        if held and not labelled_standards.removal_blocked_by(profile, k)]
            if blocked:
                return self._redirect_error(mid, u"Cannot remove " + u"; ".join(blocked), pane)
            held = []
            for k in kws:
                grid.pop(k)
                # its own SUR limits go with it, under any spelling that is its
                held += drop_eis_limits(profile, eis_names_for(profile, k))
            done = u"Removed {0}".format(u", ".join(kws))
            if held and len(kws) == 1:
                done += u" and its limits for {0} class{1}".format(len(held), u"" if len(held) == 1 else u"es")
            elif held:
                done += u" and their limits"
        profile[labelled_standards.KEY] = grid
        for watched, check in PROFILE_CHECKS:
            if "ls" in watched:
                problems = check(profile)
                if problems:
                    return self._redirect_error(mid, u"Not saved: " + u" ".join(problems), pane)
        profile.pop("_seeded", None)
        save_profile(portal, mid, profile, label=done)
        return self._redirect_saved(mid, pane, note=done)

    def _remove_matrix(self, portal, mid):
        """Remove the ticked matrices from the method, in one save: refused
        whole while anything points at one or holds data for it
        (matrix_references names each), when the matrices changed since the
        page was drawn, and when none would be left. A matrix is never
        renamed here: core owns the Sample Type's name."""
        from senaite.pfas import config_forms
        from senaite.pfas.method_profile_sections import (PROFILE_CHECKS, SECTIONS, matrix_references,
                                                          read_matrices, write_matrices)
        from senaite.pfas.method_profile_store import raw_profile
        form = self.request.form
        pane = "pane-matrices"
        picked = form.get("matrix") or []
        picked = [picked] if not isinstance(picked, (list, tuple)) else picked
        gone = []
        for m in picked:                    # each once, in the order ticked
            m = (m or "").strip()
            if m and m not in gone:
                gone.append(m)
        stored = raw_profile(portal, mid)
        if not stored:
            return self._redirect_error(mid, u"No profile for %s" % mid, pane)
        env = self.section_env()
        section = SECTIONS["mtx"]
        if (form.get("section_stamp__mtx") or "").strip() != config_forms.stamp(section, stored, env):
            return self._redirect_error(mid, (
                u"Not saved: {0} changed after you opened it. Reload to see the "
                u"change, then try again.").format(section.title), pane)
        profile = get_profile(portal, mid)
        matrices = list(profile.get("supported_matrices") or [])
        if not gone:
            return self._redirect_error(mid, u"Not removed: tick the matrices to remove.", pane)
        unknown = [m for m in gone if m not in matrices]
        if unknown:
            return self._redirect_error(mid, u"Not removed: {0} {1} not one of this method's matrices.".format(
                u", ".join(unknown), u"is" if len(unknown) == 1 else u"are"), pane)
        if len(gone) >= len(matrices):
            return self._redirect_error(mid, u"Not removed: a method needs at least one matrix.", pane)
        blocked = [(m, matrix_references(profile, [m])) for m in gone]
        blocked = [u"{0}: it still has {1}".format(m, u"; ".join(found)) for m, found in blocked if found]
        if blocked:
            return self._redirect_error(mid, u"Cannot remove " + u". ".join(blocked), pane)
        write_matrices(profile, [r for r in read_matrices(profile) if r["name"] not in gone])
        for watched, check in PROFILE_CHECKS:
            if "mtx" in watched:
                problems = check(profile)
                if problems:
                    return self._redirect_error(mid, u"Not saved: " + u" ".join(problems), pane)
        profile.pop("_seeded", None)
        done = u"Removed {0}".format(u", ".join(gone))
        save_profile(portal, mid, profile, label=done)
        # taken off the units that name it among what they hold, each in the history
        from senaite.pfas.browser.equipment import release_matrices
        released = release_matrices(mid, gone)
        if released:
            done += u"; taken off {0}".format(u", ".join(released))
        return self._redirect_saved(mid, pane, note=done)

    def _handle_post(self):
        mid = self.request.form.get("method_id", "").strip()
        if not mid:
            return self._redirect_error("", "method_id is required")

        portal = _portal(self.context)
        action = (self.request.form.get("action") or "").strip()
        if action in ("add_standard", "remove_standard"):
            return self._standards_action(portal, mid, action)
        if action == "remove_matrix":
            return self._remove_matrix(portal, mid)
        if action == "copy_tiers":
            return self._copy_tiers(portal, mid)
        section_id = (self.request.form.get("_section") or "").strip()
        if section_id:
            return self._save_section(portal, mid, section_id)
        # Stale-save protection (R1): refuse, before applying anything, a save
        # made from a page opened before someone else changed this profile --
        # the second save used to replace the first without a word.
        sent = (self.request.form.get("config_stamp") or "").strip()
        if sent:
            from senaite.pfas import config_history
            if sent != config_history.stamp(self._stamp_value(portal, mid)):
                candidates = [e for e in (config_history.last_change(portal, "method_profile", mid),) if e]
                last = max(candidates, key=lambda e: e.get("at", "")) if candidates else {}
                return self._redirect_error(mid, (
                    "Not saved: this profile was changed by {0} at {1} after "
                    "you opened it. Reload to see their change, then re-apply "
                    "yours.").format(last.get("who", "someone"),
                                     config_history.shown_at(last.get("at", "?"))))
        profile = get_profile(portal, mid)   # start from existing to preserve unknown keys

        try:
            profile = self._apply_form(profile)
        except ValueError as exc:
            return self._redirect_error(mid, "Validation error: " + str(exc))
        except Exception as exc:
            logger.exception("Error saving method profile %s", mid)
            return self._redirect_error(mid, "Save failed: " + str(exc))

        save_profile(portal, mid, profile)

        # The surrogate map is saved above, as submitted, on THIS method only
        # (superseding D58's write-back): it is no longer
        # copied to the analysis services nor rebuilt from them, which is what
        # made one method's edit change the link for every method.

        return self._redirect_saved(mid)

    def _apply_form(self, profile):
        f = self.request.form
        # Clear the seed flag — a user-saved profile is no longer factory-default.
        profile.pop("_seeded", None)

        def _float(key, default=None):
            v = f.get(key, "").strip()
            if not v:
                return default
            return float(v)

        def _int(key, default=None):
            v = f.get(key, "").strip()
            if not v:
                return default
            return int(v)

        def _bool(key):
            return f.get(key, "") in ("on", "true", "1", "yes")

        def _json_field(key, default=None):
            raw = f.get(key, "").strip()
            if not raw:
                return default if default is not None else []
            return json.loads(raw)

        profile["display_name"] = f.get("display_name",
                                         profile.get("display_name", "")).strip()
        profile["description"]  = f.get("description",
                                         profile.get("description", "")).strip()

        # Instrument verification (calibration, CCV, IS response, confirmation)
        # is NOT parsed here any more: the Calibration & CCV tab is its own
        # form, saved by _save_section (R2). This form no longer carries those
        # inputs, and the old handler assigned every one unconditionally --
        # parsing them here would null them on every Save & Export.

        # Recovery tiers, spike levels and the Dup RPD are NOT parsed here: the
        # Recovery Tiers tab is its own form (declared grids, R2).

        # Salt and matrix adjustment factors are NOT parsed here: the Sample
        # Corrections tab is its own form (config_forms tables, R2), saved by
        # _save_section. The old fallbacks that re-read a hidden JSON copy of
        # each on every other save are gone with them -- no field sent either.

        # Matrices & Units is NOT parsed here: it is its own form (config_forms
        # collection, R2), saved by _save_section, which refuses a removal or
        # rename that would orphan matrix-keyed data.

        # Reporting limits, salt factors, the surrogate map and the isomers
        # are NOT parsed here: they are the Analytes tab's grid, its own form
        # (config_forms tables), saved by _save_section.

        # The labelled standards and the SUR limits are NOT parsed here: the
        # Labelled standards tab is its own form (declared sections), and a
        # standard is added or removed by its own action.

        profile["extraction_stages"] = _stages_from_form(_json_field(
            "extraction_stages_json",
            profile.get("extraction_stages", [])))

        # The analyte x matrix panel is NOT parsed here: its switches are on
        # the Analytes tab's own form (profile_form.apply_loose).

        # The QC types' and blanks' states are NOT parsed here: their rows are
        # on the QC criteria tab's own form (profile_form.apply_loose).

        # Disabled QC types carry NO spike levels: prune their entries from
        # every matrix (e.g. LFB toggled off -> LFB spike rows removed).
        qca = profile.get("qc_acceptance", {}) or {}
        disabled = set(k for k, v in qca.items() if not (v or {}).get("enabled"))
        if disabled:
            sl = profile.get("spike_levels") or {}
            removed = 0
            for matrix, per_qc in list(sl.items()):
                if not isinstance(per_qc, dict):
                    continue
                for qc in list(per_qc.keys()):
                    if qc in disabled:
                        del per_qc[qc]
                        removed += 1
            if removed:
                profile["spike_levels"] = sl
                logger.info("pruned %d spike-level blocks for disabled QC "
                            "types: %s", removed, sorted(disabled))

        return profile

    # ── changes proposed from a run (method_proposals) ───────────────────────

    def _userid(self):
        """The person's user id as unicode: compared with the stored one."""
        from AccessControl import getSecurityManager
        from Products.CMFPlone.utils import safe_unicode
        return safe_unicode(getSecurityManager().getUser().getId() or u"")

    def _rights(self):
        """{"manager", "qa"} of the person: a manager's role at the portal,
        and the QA approver sign right in People & Roles (none when their
        record cannot be read). Once per request."""
        if not hasattr(self, "_rights_cache"):
            self._rights_cache = {"manager": bool(_require_manager(self.context, self.request)),
                                  "qa": _qa_approver(self.context)}
        return self._rights_cache

    def _proposal_form(self):
        """(portal, method id, proposal id, now as a stored stamp), after the
        form's authenticator is checked: a countersign writes its revision's
        files before the end of the request, where plone.protect would."""
        try:
            from plone.protect import CheckAuthenticator
            CheckAuthenticator(self.request)
        except ImportError:
            pass
        from datetime import datetime
        when = datetime.utcnow().replace(microsecond=0).isoformat()
        return (_portal(self.context), self.method_id(), (self.request.form.get("proposal") or u"").strip(), when)

    def pending_proposals(self):
        """The changes proposed from a run waiting on this method, each
        {"id", "trace", "change" (the Processing changes list's words),
        "run", "run_url" (its Data Review, Integration Review tab), "who", "when",
        "may_decide", "may_withdraw", "actions" (the row's menu)}."""
        if hasattr(self, "_pending_cache"):
            return self._pending_cache
        from six.moves.urllib.parse import quote
        from senaite.pfas import lab_time, raw_review, row_menu
        from senaite.pfas.browser import staff
        portal, mid = _portal(self.context), self.method_id()
        rights, me = self._rights(), self._userid()
        out = []
        for p in mp.pending(mp.load(portal), mid) if mid else []:
            src = p.get("source") or {}
            try:
                who = staff.staff_info(p["proposed_by"]).get("fullname") or p["proposed_by"]
            except Exception:                               # noqa: BLE001
                who = p["proposed_by"]
            decide = bool(rights["manager"] or rights["qa"]) and p["proposed_by"] != me
            withdraw = p["proposed_by"] == me
            url = u"%s/worksheets/%s/@@pfas-data-review?tab=raw&mode=compound&analyte=%s" % (
                portal.absolute_url(), src.get("worksheet") or u"", quote(p["analyte"].encode("utf-8"), safe=""))
            out.append({"id": p["id"], "trace": mp.trace_text(p["analyte"], p.get("transition"), p.get("record")),
                        "change": raw_review.processing_text(p["record"]),
                        "run": u"%s, change %s" % (src.get("worksheet") or u"", src.get("change") or u""),
                        "run_url": url, "who": who,
                        "when": lab_time.show(p.get("proposed_at")) if p.get("proposed_at") else u"",
                        "may_decide": decide, "may_withdraw": withdraw,
                        "actions": row_menu.actions(
                            (u"Open the run", "href", url),
                            (u"Countersign", "modal", u"prop-cs-%s" % p["id"]) if decide else None,
                            (u"Refuse", "modal", u"prop-rf-%s" % p["id"], {"danger": True}) if decide else None,
                            (u"Withdraw", "modal", u"prop-wd-%s" % p["id"], {"danger": True}) if withdraw else None)})
        self._pending_cache = out
        return out

    def countersign_sentence(self):
        """What a countersign issues, for its dialog: "Issues revision
        4.1." when the method has no other unissued change, else why it is
        refused."""
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
        portal, mid = _portal(self.context), self.method_id()
        raw = raw_profile(portal, mid) or {}
        recs = mr.records(portal, mid)
        if mr.status(recs, mr.fingerprints(raw, method_toggles(raw, mid)))["unissued"]:
            return mp.UNISSUED
        return u"Issues revision %d.%d." % mr.next_label(recs, "sub")

    # the confirm Remove asks
    REMOVE_CONFIRM = u"Remove the method's saved processing for %s?"

    def method_processing(self):
        """The processing changes the method holds as its own, each
        {"trace", "change", "misfit" (why the compound can no longer take
        it: the worker leaves it out), "actions" (Remove, a manager's)}:
        applied to every run's trace that holds none."""
        from senaite.pfas import raw_review, row_menu
        raw = self._raw()
        misfit = dict(((a, t), why) for a, t, why in mp.misfits(raw))
        rows = ((raw.get("integration") or {}).get("analytes") or {})
        out = []
        for kw in sorted(rows):
            entry = rows[kw].get("processing") if isinstance(rows[kw], dict) else None
            if mp.empty_processing(entry):
                continue
            for transition, record in mp.saved_traces(entry):
                try:
                    words = raw_review.processing_text(raw_review.processing_of(record))
                except ValueError:
                    words = mp.UNREADABLE
                trace = mp.trace_text(kw, transition)
                remove = None if self.read_only() else (
                    u"Remove", "form", "processing-remove",
                    {"values": {"analyte": kw, "transition": transition or u""}, "danger": True,
                     "confirm": self.REMOVE_CONFIRM % trace})
                out.append({"trace": trace, "change": words, "misfit": misfit.get((kw, transition), u""),
                            "actions": row_menu.actions(remove)})
        return out

    def _remove_processing(self):
        """POST: a manager takes one saved processing change off its
        compound: an ordinary profile edit (Config History; a sub revision
        when issued)."""
        try:
            from plone.protect import CheckAuthenticator
            CheckAuthenticator(self.request)
        except ImportError:
            pass
        portal, mid = _portal(self.context), self.method_id()
        f = self.request.form
        transition = (f.get("transition") or u"").strip() or None
        try:
            profile = mp.without_entry(get_profile(portal, mid), (f.get("analyte") or u"").strip(), transition)
        except ValueError as exc:
            return self._redirect_error(mid, u"Not removed: %s" % exc, "pane-run")
        profile.pop("_seeded", None)
        save_profile(portal, mid, profile)
        return self._redirect_saved(mid, "pane-run", note=u"Saved processing removed.")

    def _countersign_proposal(self):
        """POST: a different manager or QA officer countersigns a proposed
        change. In one transaction it saves the change into the compound's
        processing entry (Config History, as any save) and issues the sub
        revision, whose record names the run and the change. Refused before
        anything is saved: no right, the proposer, not waiting, the method
        unable to take it, or other changes not yet issued (the revision
        would be mislabelled); a refused issue aborts the whole countersign."""
        import transaction
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.browser.report_designs import DesignedReportError
        from senaite.pfas.browser.settings_report_view import issue_revision
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
        portal, mid, pid, when = self._proposal_form()
        pane, no = "pane-run", u"Not countersigned: "
        data = mp.load(portal)
        try:
            p = mp.countersign(data, mid, pid, self._userid(), when, self._rights())
        except ValueError as exc:
            return self._redirect_error(mid, no + u"%s" % exc, pane)
        raw = raw_profile(portal, mid) or {}
        recs = mr.records(portal, mid)
        if mr.status(recs, mr.fingerprints(raw, method_toggles(raw, mid)))["unissued"]:
            return self._redirect_error(mid, no + mp.UNISSUED, pane)
        try:
            profile = mp.with_change(get_profile(portal, mid), p)
        except ValueError as exc:
            return self._redirect_error(mid, no + u"%s" % exc, pane)
        # a countersigned profile is the lab's, no longer the installer's
        profile.pop("_seeded", None)
        save_profile(portal, mid, profile)
        saved = raw_profile(portal, mid) or {}
        # a processing entry is a sub change; a last revision kept with no
        # snapshot grades every change major: issue that first
        if mr.next_issue(mid, recs, saved, method_toggles(saved, mid))["level"] != "sub":
            transaction.abort()
            return self._redirect_error(mid, no + mp.NOT_SUB, pane)
        from bika.lims import api
        user = api.get_current_user()
        who = (user.getProperty("fullname") or user.getId()) if user else u""
        try:
            rec = issue_revision(portal, mid, who, mp.revision_reason(p["source"]), source=p["source"])
        except (ValueError, ImportError, DesignedReportError) as exc:
            transaction.abort()
            logger.warning("method %s: proposal %s not countersigned: %s", mid, pid, exc)
            why = (u"PDF rendering (WeasyPrint) is not installed on this server." if isinstance(exc, ImportError)
                   else u"%s" % exc)
            return self._redirect_error(mid, no + u"the revision was not issued. " + why, pane)
        p["revision"] = mr.label(rec)
        mp.save(portal, data)
        logger.info("method %s: proposal %s countersigned by %s, revision %s", mid, pid, who, p["revision"])
        return self._redirect_saved(mid, pane, note=u"Countersigned: revision %s issued." % p["revision"])

    def _refuse_proposal(self):
        """POST: one who may countersign a proposed change refuses it, with
        a reason. The profile is not touched."""
        portal, mid, pid, when = self._proposal_form()
        data = mp.load(portal)
        try:
            mp.refuse(data, mid, pid, self._userid(), when, self.request.form.get("reason"), self._rights())
        except ValueError as exc:
            return self._redirect_error(mid, u"Not refused: %s" % exc, "pane-run")
        mp.save(portal, data)
        return self._redirect_saved(mid, "pane-run", note=u"Proposed change refused.")

    def _withdraw_proposal(self):
        """POST: the person who proposed a change withdraws it, with a
        reason. The profile is not touched."""
        portal, mid, pid, when = self._proposal_form()
        data = mp.load(portal)
        try:
            mp.withdraw(data, mid, pid, self._userid(), when, self.request.form.get("reason"))
        except ValueError as exc:
            return self._redirect_error(mid, u"Not withdrawn: %s" % exc, "pane-run")
        mp.save(portal, data)
        return self._redirect_saved(mid, "pane-run", note=u"Proposed change withdrawn.")

    def _redirect_saved(self, mid, pane="", note=u""):
        url = "{}/@@pfas-method-profile-edit?method_id={}&saved=1{}{}".format(
            self.context.absolute_url(), mid,
            "&note=" + urllib.quote(note.encode("utf-8")) if note else "", "#" + pane if pane else "")
        self.request.response.redirect(url)
        return ""

    def _redirect_error(self, mid, msg, pane=""):
        url = "{}/@@pfas-method-profile-edit?method_id={}&error={}{}".format(
            self.context.absolute_url(), mid,
            urllib.quote(msg.encode("utf-8")), "#" + pane if pane else "")
        self.request.response.redirect(url)
        return ""
