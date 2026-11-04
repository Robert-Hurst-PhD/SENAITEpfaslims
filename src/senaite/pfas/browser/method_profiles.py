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

Both views require Manager, LabManager, or Owner role.
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

class PFASMethodProfilesView(ViewHelpers, BrowserView):
    """List all PFAS method profiles."""

    template = ViewPageTemplateFile("templates/method_profiles.pt")

    def is_manager(self):
        """Managers start a new method here (the New Method Wizard)."""
        return _require_manager(self.context, self.request)

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
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

    def methods(self):
        portal = _portal(self.context)
        from senaite.pfas.method_bridge import get_association, get_core_method
        # the stored profiles: a deleted method (a shipped one included) is
        # not listed again from the seeds
        all_ids = sorted(list_method_ids(portal))
        from senaite.pfas import method_revisions as mr
        from senaite.pfas.browser.settings_report_view import _shown_revision
        from senaite.pfas.method_profile_store import raw_profile
        from senaite.pfas.qc.rules import method_toggles
        result = []
        for mid in all_ids:
            p = get_profile(portal, mid)
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
                "revision": _shown_revision(mr.status(mr.records(portal, mid), mr.fingerprint(
                    raw_profile(portal, mid) or {},
                    method_toggles(raw_profile(portal, mid) or {}, mid)))),
            }
            if get_association is not None:
                assoc = get_association(portal, mid)
                if assoc.get("method_uid"):
                    core = get_core_method(portal, mid)
                    row["core_method_title"] = assoc.get("method_title", "")
                    row["core_method_url"] = core.absolute_url() if core is not None else ""
                    row["linked_services"] = len(assoc.get("service_uids", []))
                    row["linked_sampletypes"] = len(assoc.get("sampletype_uids", []))
            result.append(row)
        return result


# ── Edit view ─────────────────────────────────────────────────────────────────

class PFASMethodProfileEditView(ViewHelpers, BrowserView):
    """Edit a single PFAS method profile."""

    template = ViewPageTemplateFile("templates/method_profile_edit.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden: Manager, LabManager, or Owner role required")

        if self.request.form.get("_preview") == "rt":
            return self._preview_recovery_grid()
        if self.request.method == "POST":
            if self.request.form.get("action") == "delete_method":
                return self._delete_method()
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
        the CoA-lot dropdown. Expired lots are flagged so they aren't picked."""
        try:
            from senaite.pfas.browser.reagents import _list_reagents
            portal = _portal(self.context)
            recs = _list_reagents(portal,
                                  category_filter=u"Standard / Reference Material")
        except Exception as exc:
            logger.warning("standard_lot_options: %s", exc)
            return []
        out = []
        for d in recs:
            lot = d.get("lot_number", "") or ""
            name = d.get("name", "") or ""
            expired = d.get("status") == "expired"
            label = u"{0} — lot {1}".format(name, lot) if lot else name
            if expired:
                label += u" (EXPIRED)"
            out.append({
                "uid": d.get("uid", ""), "lot_number": lot,
                "name": name, "label": label, "expired": expired,
            })
        return sorted(out, key=lambda x: x["label"].lower())

    def extraction_stages_json(self):
        stages = self.profile().get("extraction_stages", [])
        return json.dumps(sorted(stages, key=lambda s: s.get("order", 0)), indent=2)

    # ── Analytes tab ─────────────────────────────────────────────────────────

    def analytes_sheet(self):
        """The Analytes tab's grid, drawn from the stored profile and the
        page's section env: the same value the section stamps and the save
        read, so what is drawn is what a stale-save check compares."""
        from senaite.pfas import profile_grids
        from senaite.pfas.method_profile_store import raw_profile
        return profile_grids.analytes_sheet(raw_profile(_portal(self.context), self.method_id()),
                                            self.section_env())

    # ── Labelled standards tab ───────────────────────────────────────────────

    def standards_sheet(self):
        """The Labelled standards tab's grid, drawn from the stored profile
        and the page's section env, as the stamps and the save read them."""
        from senaite.pfas import profile_grids
        from senaite.pfas.method_profile_store import raw_profile
        return profile_grids.standards_sheet(raw_profile(_portal(self.context), self.method_id()),
                                             self.section_env())

    # ── Matrices tab ─────────────────────────────────────────────────────────

    def matrices_sheet(self):
        """The Matrices tab's grid, drawn from the stored profile and the
        page's section env, as the stamps and the save read them."""
        from senaite.pfas import profile_grids
        return profile_grids.matrices_sheet(self._raw(), self.section_env())

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

    def _utc_note(self):
        return u"" if self.zone_active() else u" UTC"

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

    def rules_table(self):
        """The rule table, drawn from the stored profile and the page's
        section env, as the stamps and the save read them."""
        from senaite.pfas import profile_grids
        return profile_grids.rules_table(self._raw(), self.section_env())

    def windows_sheet(self):
        """The applied windows (LFSM, ordinary spike) the tab opens on."""
        from senaite.pfas import profile_grids
        return profile_grids.windows_sheet(self._raw(), self.section_env())

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
        runs, the same resolver the page draws with). Nothing is written."""
        from senaite.pfas import profile_grids
        html, errors = profile_grids.preview_windows(self._raw(), self.request.form, self.section_env())
        if errors:
            self.request.response.setHeader("X-Preview-Errors", "1")
            return u'<div id="qc-windows"><p class="alert alert-error">%s</p></div>' % (
                escape(u" ".join(errors)))
        self.request.response.setHeader("Content-Type", "text/html; charset=utf-8")
        return u'<div id="qc-windows">%s</div>' % html

    # ── one home per setting ─────────────────────────────────────
    def required_rows(self, group):
        """A Required toggle per numeric criterion of `group` (calibration,
        is_response, confirmation): what Engine listed as code names."""
        from senaite.pfas import profile_grids
        return profile_grids.required_rows(self._raw(), group)

    def run_template_editor(self):
        """The method's run template as the editor draws it (the Run Builder
        builds every run from it)."""
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
            from senaite.pfas import regulatory_limits
            self._section_env = {"standard_lots": self.standard_lot_options(),
                                 "services": self._pfas_service_index(),
                                 "qc_codes": self._qc_codes(),
                                 "regulatory": regulatory_limits.get_store(_portal(self.context)),
                                 # a field governed by a rule switch reads N/A while it is off
                                 "rules": self._rule_state(), "rule_labels": self._rule_labels(),
                                 # Storage and holding: the matrices homogenised by default
                                 "homogenised": self._homogenised_matrices()}
        return self._section_env

    def _homogenised_matrices(self):
        """The Sample Types whose default homogenisation is a method (not
        blank, not "Not homogenised"); a processed-sample clock elsewhere
        reads "not homogenised"."""
        from bika.lims import api
        from senaite.pfas import homogenisation as hg
        try:
            brains = api.search({"portal_type": "SampleType"}, "senaite_catalog_setup")
            return sorted(api.get_title(b) for b in brains
                          if hg.type_default(api.get_object(b)) not in (u"", hg.NONE_ID))
        except Exception as exc:                            # noqa: BLE001
            logger.warning("homogenised matrices: %s", exc)
            return None

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
            cache[section_id] = config_forms.render(SECTIONS[section_id],
                                                    raw_profile(_portal(self.context), self.method_id()),
                                                    self.section_env())
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
                    u"Not saved: {0} was changed by {1} at {2}{3} after you opened "
                    u"it. Reload to see their change, then re-apply yours.").format(
                        section.title, last.get("who", "someone"),
                        config_history.shown_at(last.get("at", "?")), self._utc_note()), pane)
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
        from senaite.pfas.method_profile_sections import PROFILE_CHECKS
        for watched, check in PROFILE_CHECKS:
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
                    "Not saved: this profile was changed by {0} at {1}{2} after "
                    "you opened it. Reload to see their change, then re-apply "
                    "yours.").format(last.get("who", "someone"),
                                     config_history.shown_at(last.get("at", "?")), self._utc_note()))
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
