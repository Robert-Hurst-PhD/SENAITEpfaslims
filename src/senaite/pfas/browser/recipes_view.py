# -*- coding: utf-8 -*-
"""Logbooks › 4 · Recipes: each method's recipes.

A recipe says how the lab prepares one standard or reagent: what it is made
from, the log that records it, its steps and what is made from it. The list
per method; a recipe's card with its steps and its concentrations, calculated
from the parent down to a purchased lot's certificate values (as acid); the
editor, whose save issues a new revision (recipes.py). Purchased materials
are not recipes: they appear as the parents. Saving is the manager's.

Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
from datetime import datetime

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import recipe_calc as rc
from senaite.pfas import recipes as rs
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import refuse, require_manager

logger = logging.getLogger("senaite.pfas.browser.recipes_view")

LOGS = (("250", u"FM-ENV-001"), ("251", u"FM-ENV-002"))


class PFASRecipesView(BrowserView):

    template = ViewPageTemplateFile("templates/recipes.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            if not require_manager(self.context, self.request):
                return refuse(self.request, "Forbidden")
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
            return self._save()
        return self.template()

    # ── selection ────────────────────────────────────────────────────────

    def portal(self):
        return api.get_portal()

    def portal_url(self):
        return self.portal().absolute_url()

    def methods(self):
        from senaite.pfas import configured_methods
        return configured_methods.choices(self.portal())

    def method_id(self):
        mid = self.request.form.get("method") or u""
        ids = [m["id"] for m in self.methods()]
        return mid if mid in ids else (ids[0] if ids else u"")

    def method_label(self):
        return dict((m["id"], m["label"]) for m in self.methods()).get(self.method_id(), self.method_id())

    def store(self):
        if getattr(self, "_store", None) is None:
            self._store = rs.load(self.portal())
        return self._store

    def log_label(self, slug):
        from senaite.pfas.logbook_store import form_code
        return form_code(self.portal(), slug, dict(LOGS).get(slug, slug))

    def logs(self):
        return [(slug, self.log_label(slug)) for slug, _c in LOGS]

    def channel_choices(self):
        """The LC channels the methods name (the Run Builder's slots)."""
        from senaite.pfas.method_profile_sections import solvent_channels
        from senaite.pfas.method_profile_store import raw_profile
        out = []
        for m in self.methods():
            for c in solvent_channels(raw_profile(self.portal(), m["id"]) or {}, u"lc"):
                if c["channel"] not in out:
                    out.append(c["channel"])
        return out

    def can_edit(self):
        return require_manager(self.context, self.request)

    def is_print(self):
        return bool(self.request.form.get("print"))

    # ── the list ─────────────────────────────────────────────────────────

    def _name(self, rid):
        a = rc._rev(self.store(), rid)
        return (a or {}).get("name") or rid

    def _made_from_text(self, rev):
        return u", ".join(self._name(m.get("ref")) if m.get("kind") == u"recipe" else (m.get("ref") or u"")
                          for m in rev.get("made_from") or [])

    def _used_in(self, rid):
        out = []
        for other in sorted(self.store()):
            a = rs.active(self.store(), other)
            if a and any(m.get("kind") == u"recipe" and m.get("ref") == rid for m in a.get("made_from") or []):
                out.append(a.get("name") or other)
        return out

    def _makes_text(self, rev):
        levels = (rev.get("series") or {}).get("levels") or []
        if not levels:
            return u""
        names = [l.get("level") for l in levels]
        return u"makes %s in one sitting" % (u"%s … %s" % (names[0], names[-1]) if len(names) > 2
                                             else u", ".join(names))

    def rows(self):
        out = []
        for r in rs.for_method(self.store(), self.method_id()):
            out.append({"id": r["id"], "name": r.get("name") or r["id"], "makes": self._makes_text(r),
                        "made_from": self._made_from_text(r), "log": self.log_label(r.get("log")),
                        "used_in": u", ".join(self._used_in(r["id"])) or u"—",
                        "url": u"%s/@@pfas-recipes?method=%s&recipe=%s" % (self.portal_url(), self.method_id(),
                                                                           r["id"])})
        return out

    # ── a recipe's card ──────────────────────────────────────────────────

    def _purchased(self, name):
        """A purchased product's concentrations: the newest lot of that name
        with certificate values, as acid in ng/mL; None when none is on file."""
        from senaite.pfas import certificate_values as cv
        from senaite.pfas.annotation_store import read_json
        from senaite.pfas.browser.reagents import _get_reagents_folder, _obj_to_dict
        try:
            folder = _get_reagents_folder(self.portal())
        except RuntimeError:
            return None
        lots = []
        for obj in folder.objectValues():
            d = _obj_to_dict(obj) or {}
            if (d.get("name") or u"") != name:
                continue
            cert = read_json(obj, cv.KEY, {})
            if cert.get("analytes"):
                lots.append((d.get("received_date") or u"", cert))
        if not lots:
            return None
        return rc.certificate_concentrations(sorted(lots, key=lambda x: x[0])[-1][1], u"ng/mL")

    def recipe_id(self):
        rid = self.request.form.get("recipe") or u""
        return rid if rid in self.store() else u""

    def card(self, rid=None):
        rid = rid or self.recipe_id()
        rev = rs.active(self.store(), rid) if rid else None
        if rev is None:
            return None
        res = rc.resolve(self.store(), rid, self._purchased)
        levels = res["levels"]
        analytes = sorted(set(a for l in levels for a in (l.get("conc") or {})))
        ser = (rev.get("series") or {}).get("levels") or []
        storage = rev.get("storage") or {}
        unit_of = rev.get("unit") or u"ng/mL"
        return {"id": rid, "name": rev.get("name") or rid, "revision": rev.get("revision"),
                "log": self.log_label(rev.get("log")), "made_from": self._made_from_text(rev),
                "makes": (u"%d levels in one sitting" % len(ser)) if ser else u"one lot",
                "shelf_life": rs.shelf_life(rev, self._log_defaults()),
                "storage": u" · ".join(x for x in (storage.get("location"), storage.get("conditions")) if x),
                "steps": rev.get("steps") or [], "unit": unit_of,
                "levels": [l.get("level") or rev.get("name") for l in levels],
                "taken": [lv.get("take") for lv in ser] if ser else [((rev.get("made_from") or [{}])[0]).get("take")],
                "final": [lv.get("final") for lv in ser] if ser else [rev.get("final_volume")],
                "conc": [{"analyte": a, "values": [(l.get("conc") or {}).get(a) for l in levels]} for a in analytes],
                "edit_url": u"%s/@@pfas-recipes?method=%s&recipe=%s&edit=1" % (self.portal_url(), self.method_id(), rid)}

    def cards(self):
        return [c for c in (self.card(r["id"]) for r in self.rows()) if c]

    def _log_defaults(self):
        """Each prep log's default expiry, the default shelf life of its recipes."""
        out = {}
        try:
            from senaite.pfas.browser.prep_logbooks import _list
            for d in _list(self.portal()):
                if d.get("status") == "active" and d.get("default_expiry_days"):
                    out[d["logbook_slug"]] = d["default_expiry_days"]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("log defaults: %s", exc)
        return out

    # ── the editor ───────────────────────────────────────────────────────

    def editing(self):
        f = self.request.form
        if not self.can_edit():
            return None
        if f.get("new"):
            return {"id": u"", "rev": {"methods": [self.method_id()], "log": f.get("log") or u"251",
                                       "made_from": [{"kind": u"purchased", "ref": u"", "take_unit": u"mL"}],
                                       "steps": [{}], "unit": u"ng/mL", "final_unit": u"mL", "storage": {}}}
        rid = self.recipe_id()
        if f.get("edit") and rid:
            return {"id": rid, "rev": rs.active(self.store(), rid) or rs.revisions(self.store(), rid)[-1]}
        return None

    def recipe_choices(self):
        return [(rid, (rc._rev(self.store(), rid) or {}).get("name") or rid) for rid in sorted(self.store())]

    def _save(self):
        f = self.request.form
        data = rs.from_form(f)
        rid = (f.get("recipe") or u"").strip()
        back = u"%s/@@pfas-recipes?method=%s" % (self.portal_url(), self.method_id())
        errors = rs.problems(data)
        if errors:
            return self._redirect(back + (u"&recipe=%s&edit=1" % rid if rid else u"&new=1"), u" ".join(errors))
        who = api.get_current_user().getId()
        at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M")
        store = self.store()
        if rid and rid in store:
            store, rev = rs.new_revision(store, rid, who, at)
            store, err = rs.save_draft(store, rid, rev, data)
            store = rs.activate(store, rid, rev, who, at)
        else:
            store, rid = rs.new_recipe(store, data, who, at)
            store = rs.activate(store, rid, 1, who, at)
        rs.save(self.portal(), store)
        return self._redirect(back + u"&recipe=%s" % rid, ok=u"Recipe saved")

    def _redirect(self, url, error=u"", ok=u""):
        try:
            from urllib import quote_plus
        except ImportError:                                 # pragma: no cover
            from urllib.parse import quote_plus
        if error:
            url += u"&error=" + quote_plus(error.encode("utf-8"))
        if ok:
            url += u"&ok=" + quote_plus(ok.encode("utf-8"))
        self.request.response.redirect(url)
        return u""

    def error_msg(self):
        return self.request.form.get("error") or u""

    def ok_msg(self):
        return self.request.form.get("ok") or u""

    def fmt(self, v):
        if v is None:
            return u"\u2014"
        return u"%.4g" % v
