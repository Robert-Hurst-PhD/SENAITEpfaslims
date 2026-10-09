# -*- coding: utf-8 -*-
"""@@pfas-project-specs: a project's differences from its method
(project_specs.py holds the logic).

The page draws the method's own declared sections (PROJECT_SECTIONS) for one
method and one scope ("All matrices" or a matrix), pre-filled with what the
project's batches would run to; saving stores only the cells that differ from
the method (for a matrix scope: from the method plus "All matrices"), then
re-exports every batch linked to the project. Manager only,
like the project's QAPP criteria. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import json
import logging

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import config_forms as cf
from senaite.pfas import project_specs as ps
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import require_manager
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.project_specs")

FORM_ID = "project-specs"
# the page's tabs: (id, label, section ids)
TABS = [("an", u"Analytes & limits", ("px", "rl")),
        ("rec", u"Recovery & RPD", ("groups", "tiers", "tiers_lfb", "dup", "lfsmd")),
        ("std", u"Standards & links", ("ls", "sur")),
        ("ins", u"Calibration & QC run", ("cal", "qc_comp")),
        ("eis", u"SUR limits", ("eis_grid",))]


class PFASProjectSpecsView(BrowserView):

    template = ViewPageTemplateFile("templates/project_specs.pt")
    rt_grid_template = ViewPageTemplateFile("templates/rt_grid.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            if not require_manager(self.context, self.request):
                return refuse(self.request, "Forbidden")
            try:
                from plone.protect.interfaces import IDisableCSRFProtection
                from zope.interface import alsoProvides
                alsoProvides(self.request, IDisableCSRFProtection)
            except ImportError:
                pass
            return self._save()
        return self.template()

    # ── selection ────────────────────────────────────────────────────────

    def portal_url(self):
        return api.get_portal().absolute_url()

    def uid(self):
        return (self.request.form.get("uid") or "").strip()

    def project(self):
        return ps.project_by_id(api.get_portal(), self.uid())

    def project_title(self):
        p = self.project()
        return (getattr(p, "title", None) or self.uid()) if p is not None else u""

    def can_manage(self):
        return require_manager(self.context, self.request)

    def method_ids(self):
        from senaite.pfas.browser.projects import _method_ids
        return _method_ids(api.get_portal())

    def method_id(self):
        mid = (self.request.form.get("method_id") or "").strip()
        ids = self.method_ids()
        return mid if mid in ids else (ids[0] if ids else u"")

    def method_profile(self):
        if getattr(self, "_profile", None) is None:
            from senaite.pfas.method_profile_store import raw_profile
            self._profile = raw_profile(api.get_portal(), self.method_id()) or {}
        return self._profile

    def scopes(self):
        return [(ps.ALL, u"All matrices")] + [
            (m, m) for m in self.method_profile().get("supported_matrices") or []]

    def scope(self):
        s = self.request.form.get("scope") or ps.ALL
        return s if s in [x[0] for x in self.scopes()] else ps.ALL

    def env(self):
        if getattr(self, "_env", None) is None:
            self._env = ps.site_env()
        return self._env

    def specs(self):
        return ps.get_specs(self.project())

    def _states(self):
        """(base, shown, stale): what this scope is measured against, and what
        the page shows (base + this scope's differences)."""
        if getattr(self, "_st", None) is None:
            mspecs = self.specs().get(self.method_id())
            base, st1 = ps.scope_base(self.method_profile(), mspecs, self.scope(),
                                      self.sections(), self.env())
            shown, st2 = ps._apply_scopes(base, mspecs, [self.scope()], self.sections(), self.env())
            self._st = (base, shown, st1 + st2)
        return self._st

    # ── sections ─────────────────────────────────────────────────────────

    def sections(self):
        from senaite.pfas.method_profile_sections import PROJECT_SECTIONS
        qca = (self.method_profile().get("qc_acceptance") or {})
        skip = set()
        if "Dup" not in qca:
            skip.add("dup")
        if "LFSMD" not in qca:
            skip.add("lfsmd")
        if "LFB" not in qca:
            skip.add("tiers_lfb")
        if "eis_overrides" not in self.method_profile():
            skip.update(s.id for s in PROJECT_SECTIONS if s.id.startswith("eis"))   # EPA 1633A only
        return [s for s in PROJECT_SECTIONS if s.id not in skip]

    def section_ids(self):
        return [s.id for s in self.sections()]

    def tabs(self):
        ids = set(self.section_ids())
        tabs = [{"id": t, "label": label, "sections": [s for s in sids if s in ids]}
                for t, label, sids in TABS]
        return [t for t in tabs if t["sections"]]       # no empty tab (FDA has no SUR limits)

    def _section(self, sid):
        return dict((s.id, s) for s in self.sections())[sid]

    def kind(self, sid):
        s = self._section(sid)
        return "table" if isinstance(s, cf.Table) else "collection" if isinstance(s, cf.Collection) else "section"

    def title(self, sid):
        return self._section(sid).title

    def section_groups(self, sid):
        return cf.render(self._section(sid), self._states()[1], self.env())

    def section_stamp(self, sid):
        return cf.stamp(self._section(sid), self._states()[1], self.env())

    def recovery_grid_html(self):
        from senaite.pfas.method_profile_sections import recovery_grid
        return self.rt_grid_template(grid=recovery_grid(self._states()[1]))

    # ── what differs ─────────────────────────────────────────────────────

    def differences(self):
        """Readable lines for this scope's stored differences."""
        patches = (self.specs().get(self.method_id()) or {}).get(self.scope()) or {}
        out = []
        for s in self.sections():
            patch = patches.get(s.id)
            if not patch:
                continue
            if isinstance(s, cf.Collection):
                for name, vals in sorted((patch.get("changed") or {}).items()):
                    out.append(u"%s — %s: %s" % (s.title, name, _vals(vals)))
                for row in patch.get("added") or []:
                    out.append(u"%s — added %s" % (s.title, row.get(s.key.path[0])))
                for name in patch.get("removed") or []:
                    out.append(u"%s — removed %s" % (s.title, name))
            elif isinstance(s, cf.Table):
                for tok, vals in sorted(patch.items()):
                    out.append(u"%s — %s: %s" % (s.title, u" / ".join(json.loads(tok)), _vals(vals)))
            else:
                out.append(u"%s — %s" % (s.title, _vals(patch)))
        return out

    def departures(self):
        mid = self.method_id()
        m = None if self.scope() == ps.ALL else self.scope()
        eff, _st = ps.effective(self.method_profile(), self.specs().get(mid), m,
                                self.sections(), self.env())
        return ps.departures(self.method_profile(), eff, mid, [m] if m else None)

    def stale(self):
        return self._states()[2]

    def needs(self):
        """What an added analyte still needs before it can be reported."""
        from senaite.pfas.method_profile_sections import EXTRAS_KEY
        shown = self._states()[1]
        links = dict((r.get("analyte"), r.get("surrogate_is")) for r in shown.get("surrogate_map") or []
                     if isinstance(r, dict))
        from senaite.pfas.report_limits import limits_for
        out = []
        for kw in shown.get(EXTRAS_KEY) or []:
            missing = []
            if not links.get(kw):
                missing.append(u"a quantifying IS (Standards & links)")
            no_rl = [m for m in shown.get("supported_matrices") or []
                     if limits_for(shown, m, kw).get("rl") is None]
            if no_rl:
                missing.append(u"an RL in %s" % u", ".join(no_rl))
            if missing:
                out.append(u"%s needs %s." % (kw, u" and ".join(missing)))
        return out

    # ── save ─────────────────────────────────────────────────────────────

    def _back(self, **msg):
        q = "uid=%s&method_id=%s&scope=%s" % (self.uid(), self.method_id(), self.scope())
        for k, v in msg.items():
            q += "&%s=%s" % (k, _q(v))
        self.request.response.redirect("%s/@@pfas-project-specs?%s" % (self.portal_url(), q))
        return ""

    def _save(self):
        form = self.request.form
        if self.project() is None:
            return self._back(error=u"No such project.")
        base, shown, _stale = self._states()
        env = self.env()
        for s in self.sections():
            if (form.get("section_stamp__" + s.id) or "") != cf.stamp(s, shown, env):
                return self._back(error=u"Not saved: %s changed after you opened this page "
                                        u"(the project or its method). Reload and re-apply." % s.title)
        parsed, errors = [], []
        for s in self.sections():
            updates, errs = cf.parse(s, form, shown, env)
            parsed.append((s, updates))
            errors.extend(errs)
        if errors:
            return self._back(error=u"Not saved: " + u" ".join(errors))
        new = shown
        for s, updates in parsed:
            new = cf.apply(s, new, updates, env)
        from senaite.pfas.method_profile_sections import check_profile
        problems = check_profile(new)
        if problems:
            return self._back(error=u"Not saved: " + u" ".join(problems))
        specs = ps.set_scope(self.specs(), self.method_id(), self.scope(),
                             ps.scope_patches(base, new, self.sections(), env))
        refreshed, skipped = ps.save_for_project(api.get_portal(), self.uid(), specs, self.request)
        msg = u"Saved. %d linked batch file(s) refreshed." % refreshed
        if skipped:
            msg += u" Not refreshed: %s." % u", ".join(u"%s (%s)" % s for s in skipped)
        return self._back(ok=msg)

    def ok_msg(self):
        return self.request.form.get("ok", "")

    def error_msg(self):
        return self.request.form.get("error", "")


def _vals(vals):
    parts = []
    for k, v in sorted(vals.items()):
        name = k.split("__")[-1].replace("_", " ")
        if isinstance(v, dict):
            v = u"+%s -%s" % (u",".join(v.get("add") or []) or u"0", u",".join(v.get("remove") or []) or u"0")
        parts.append(u"%s %s" % (name, u"blank" if v in (None, u"") else v))
    return u"; ".join(parts)


def _q(text):
    try:
        from urllib import quote
    except ImportError:                       # pragma: no cover
        from urllib.parse import quote
    return quote((u"%s" % text).encode("utf-8"))
