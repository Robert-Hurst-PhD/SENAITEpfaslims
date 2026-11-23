# -*- coding: utf-8 -*-
"""Document Templates: the lab draws its documents.

    @@pfas-document-templates   the templates, their revisions; new / issue /
                                archive / restore
    @@pfas-document-designer    the drag-and-drop designer (pdfme) for one
                                template's DRAFT; save_draft answers JSON

Drawing and issuing are lab configuration (TIER_CONFIG). A template prints
only from its ISSUED revision; the draft is work in progress. The model,
validation and store are senaite.pfas.document_templates. Python 2.7.
"""
from __future__ import absolute_import

import datetime
import json
import logging

from AccessControl import getSecurityManager
from bika.lims import api
from plone.protect import CheckAuthenticator
from Products.CMFPlone.utils import safe_unicode
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden

from senaite.pfas import document_templates as dt
from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action
from senaite.pfas.browser.perms import refuse
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.document_templates")

LIST_GATES = {"new": TIER_CONFIG, "issue": TIER_CONFIG, "archive": TIER_CONFIG,
              "restore": TIER_CONFIG, "from_starter": TIER_CONFIG}
DESIGNER_GATES = {"save_draft": TIER_CONFIG}


def _who():
    return getSecurityManager().getUser().getId()


def _text(form, key, default=u""):
    """A form value as text: Python 2 forms deliver UTF-8 bytes."""
    return safe_unicode(form.get(key) or default)


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def _history_view(entry):
    """What the change history records for a template: everything but the
    drawings themselves (their fingerprints stand in for them)."""
    if not entry:
        return {}
    return {"title": entry.get("title"), "size": entry.get("size"),
            "archived": bool(entry.get("archived")),
            "revisions": [dict((k, v) for k, v in r.items() if k != "template")
                          for r in entry.get("revisions") or []]}


def _track(portal, store, tid, label):
    try:
        from senaite.pfas import config_history
        config_history.track(portal, "document_template", tid,
                             lambda: _history_view(dt.load(portal).get(tid)), label=label)
    except Exception:                                       # noqa: BLE001
        logger.warning("document template change not tracked", exc_info=True)


class PFASDocumentTemplatesView(ViewHelpers, GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/document_templates.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, LIST_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req, "Forbidden")
            msg, tid = u"error:Unknown action.", None
            if action == "new":
                msg, tid = self._new(req.form)
            elif action == "issue":
                msg, tid = self._issue(req.form)
            elif action in ("archive", "restore"):
                msg, tid = self._archive(req.form, action == "archive")
            elif action == "from_starter":
                msg, tid = self._from_starter(req.form)
            url = "%s/@@pfas-document-templates" % self.portal_url()
            if action in ("new", "from_starter") and tid and not msg.startswith("error:"):
                url = "%s/@@pfas-document-designer?id=%s" % (self.portal_url(), tid)
            else:
                from six.moves.urllib.parse import urlencode
                kind, text = msg.split(":", 1)
                url += "?" + urlencode({kind: text.encode("utf-8")})
            req.response.redirect(url)
            return ""
        return self.template()

    def _new(self, form):
        portal = api.get_portal()
        store = dt.load(portal)
        kind = _text(form, "kind", u"label")
        try:
            if dt.size_of(kind, _text(form, "size")) is None or \
                    _text(form, "size") not in [z[0] for z in dt.offered_sizes(kind)]:
                return u"error:Choose a size.", None
            _track(portal, store, dt._slug(_text(form, "title"), store), u"New template")
            tid = dt.new(store, kind, _text(form, "title"), _text(form, "size"), _who(), _now())
        except (ValueError, KeyError) as exc:
            return u"error:%s" % exc, None
        dt.save(portal, store)
        return u"ok:Created.", tid

    def _existing(self, form):
        portal = api.get_portal()
        store = dt.load(portal)
        tid = _text(form, "id")
        if tid in store and store[tid].get("kind") not in dt.KINDS:
            # a design of a retired kind (a logbook's) is kept, never acted on:
            # the callers answer "No such template."
            return portal, store, None
        if tid in store:
            _track(portal, store, tid, store[tid].get("title") or tid)
        return portal, store, tid

    def _issue(self, form):
        portal, store, tid = self._existing(form)
        if tid not in store:
            return u"error:No such template.", None
        rec, problems = dt.issue(store, tid, _who(), _now(), _text(form, "note"))
        if rec is None:
            return u"error:" + u" ".join(problems), tid
        dt.save(portal, store)
        return u"ok:%s revision %d issued; it prints from now on." % (
            store[tid]["title"], rec["rev"]), tid

    def _from_starter(self, form):
        """The draft becomes the kind's current starting layout. Only the
        draft: what prints is the issued revision until the lab previews
        this draft and issues it."""
        portal, store, tid = self._existing(form)
        if tid not in store:
            return u"error:No such template.", None
        entry = store[tid]
        make = dt.KINDS.get(entry.get("kind"), {}).get("starter")
        if not make:
            return u"error:This kind of document has no starting layout.", None
        size = dt.size_of(entry["kind"], entry.get("size")) or {"width": 210.0, "height": 297.0}
        dt.save_draft(store, tid, make(size["width"], size["height"]), _who(), _now())
        dt.save(portal, store)
        return u"ok:Draft started from the current starting layout.", tid

    def _archive(self, form, archived):
        portal, store, tid = self._existing(form)
        if tid not in store:
            return u"error:No such template.", None
        store[tid]["archived"] = archived
        dt.save(portal, store)
        return u"ok:%s %s." % (store[tid]["title"], "archived" if archived else "restored"), tid

    # ── page data ───────────────────────────────────────────────────────────

    def message(self):
        return _text(self.request.form, "ok"), _text(self.request.form, "error")

    def kinds(self):
        store = dt.load(api.get_portal())
        return [{"id": k, "title": v["title"],
                 "sizes": [{"id": s[0], "title": s[1]} for s in dt.offered_sizes(k)],
                 "issued_with": v.get("issued_with"),
                 "single": bool(v.get("single")),
                 # a single design (the certificate) is created once
                 "can_add": not (v.get("single") and v["single"] in store)}
                for k, v in sorted(dt.KINDS.items(),
                                   key=lambda kv: (kv[0] != "coa", kv[0]))]

    def _with_report_template(self, entry):
        """A certificate design's status: issued with which reporting-template
        revision, and whether the draft differs from it."""
        from senaite.pfas import report_templates as rt
        portal = api.get_portal()
        snap, rev = rt.issued_snapshot(portal)
        issued = rt.designed_layout(snap)
        cur = (rt.current(rt.records(portal)) or {}) if issued is not None else {}
        return {"rev": rev if issued is not None else None, "issued_at": cur.get("issued_at") or u"",
                "issued_by": cur.get("issued_by") or u"",
                "none_issued": issued is None,
                "unissued": issued is None or dt.fingerprint(issued) != dt.fingerprint(entry.get("draft"))}

    @staticmethod
    def _issued_layout(kind, entry):
        """The layout a kind prints from, or None while none is issued: the
        certificate's is the one the issued reporting-template revision
        carries; any other kind's, its own issued revision."""
        if dt.KINDS[kind].get("issued_with"):
            from senaite.pfas import report_templates as rt
            snap, _rev = rt.issued_snapshot(api.get_portal())
            return rt.designed_layout(snap)
        cur = dt.current(entry)
        return cur["template"] if cur else None

    def rows(self, kind):
        store = dt.load(api.get_portal())
        out = []
        for tid in sorted(store, key=lambda t: (store[t].get("archived"), store[t].get("title"))):
            e = store[tid]
            if e.get("kind") != kind:
                continue
            issued = self._issued_layout(kind, e)
            st = (self._with_report_template(e) if dt.KINDS[kind].get("issued_with")
                  else dt.status(e))
            # the revision in force's issue date on the laboratory's clock
            st["issued_on"] = lab_time.show(st["issued_at"], "utc") if st.get("issued_at") else u""
            size = dt.size_of(kind, e.get("size")) or {}
            out.append({"id": tid, "title": e.get("title"), "size": size.get("title", e.get("size")),
                        "archived": bool(e.get("archived")), "status": st,
                        "problems": dt.validate(kind, e.get("draft")),
                        # an issued design drawn on an earlier definition (a
                        # kind whose fields changed) is refused at print
                        "issued_problems": (dt.validate(kind, dt.current(e)["template"])
                                            if dt.current(e) and not dt.KINDS[kind].get("issued_with") else []),
                        # an optional table the issued design (the certificate's:
                        # the issued reporting-template revision's) does not
                        # place: it prints without it
                        "optional_missing": [u"Optional table not placed: %s" % t.replace("_", " ").capitalize()
                                             for t in dt.unplaced_optional(kind, issued)]
                                            if issued is not None else [],
                        "draft_by": e.get("draft_by") or u"", "draft_at": e.get("draft_at") or u"",
                        "has_starter": bool(dt.KINDS[kind].get("starter")),
                        "history": sorted([dict((k, v) for k, v in r.items() if k != "template")
                                           for r in e.get("revisions") or []],
                                          key=lambda r: -r.get("rev", 0))})
        return out


    # ── the one table (lab, design canvas P89) ──────────────────────────────
    KIND_FILTERS = ((u"", u"All"), (u"certificates", u"Certificates"), (u"forms", u"Forms"),
                    (u"reports", u"Reports"), (u"labels", u"Labels"))

    @staticmethod
    def kind_group(kind):
        if kind in ("label", "extraction_label"):
            return u"labels"
        if kind == "coa":
            return u"certificates"
        if kind in ("coc", "sop_cover"):
            return u"forms"
        return u"reports"

    def status_filter(self):
        return u"archived" if self.request.form.get("status") == "archived" else u"active"

    def kind_filter(self):
        k = self.request.form.get("kind") or u""
        return k if k in [f[0] for f in self.KIND_FILTERS] else u""

    def table(self):
        """Every document in one list: the lab's designs, and a row for each
        single document not designed yet (it prints the form as on screen
        with the Print Settings header and footer until one is issued)."""
        archived = self.status_filter() == u"archived"
        group = self.kind_filter()
        out = []
        for k in self.kinds():
            if group and self.kind_group(k["id"]) != group:
                continue
            for r in self.rows(k["id"]):
                if r["archived"] != archived:
                    continue
                r.update(kind=k["title"], kind_id=k["id"], issued_with=k["issued_with"], placeholder=False)
                out.append(r)
            if k["single"] and k["can_add"] and not archived:
                out.append({"placeholder": True, "id": u"", "title": k["title"], "kind": k["title"],
                            "kind_id": k["id"], "size": u"", "issued_with": k["issued_with"],
                            "default_size": k["sizes"][0]["id"] if k["sizes"] else u"",
                            "problems": [], "issued_problems": [], "optional_missing": [], "history": [],
                            "has_starter": False,
                            # the template defines these before its conditions
                            "archived": False, "status": {}, "draft_at": u"", "draft_by": u""})
        return out

    def new_kinds(self):
        """What "+ New template" can make: the kinds a lab keeps several of."""
        return [k for k in self.kinds() if k["can_add"] and not k["single"]]


class PFASDocumentDesignerView(ViewHelpers, GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/document_designer.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, DESIGNER_GATES)
            if denied is not None:
                return json.dumps({"error": "Forbidden"})
            req.response.setHeader("Content-Type", "application/json")
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req, json.dumps({"error": "Forbidden"}))
            if action == "preview_inputs":
                return json.dumps(self._preview_inputs(req.form))
            if action == "save_draft":
                return json.dumps(self._save_draft(req.form))
            req.response.setStatus(400)
            return json.dumps({"error": "Unknown action."})
        if self.entry() is None:
            req.response.redirect("%s/@@pfas-document-templates?error=No+such+template."
                                  % self.portal_url())
            return ""
        return self.template()

    def _save_draft(self, form):
        portal = api.get_portal()
        store = dt.load(portal)
        tid = _text(form, "id")
        if tid not in store:
            self.request.response.setStatus(404)
            return {"error": "No such template."}
        try:
            template = json.loads(form.get("template") or "")
        except ValueError:
            self.request.response.setStatus(400)
            return {"error": "The template could not be read."}
        if dt.byte_size(form.get("template")) > dt.MAX_BYTES:
            self.request.response.setStatus(400)
            return {"error": "The template is larger than 2 MB: use smaller images."}
        _track(portal, store, tid, store[tid].get("title") or tid)
        problems = dt.save_draft(store, tid, template, _who(), _now())
        dt.save(portal, store)
        problems = problems + dt.warnings(store[tid]["kind"], template)
        return {"ok": True, "problems": problems, "status": dt.status(store[tid]),
                "saved_at": store[tid]["draft_at"]}

    def _preview_inputs(self, form):
        """The example data as pdfme input for the template being drawn, by
        the same rule a printed document uses (document_templates.inputs_for)."""
        e = dt.load(api.get_portal()).get(_text(form, "id"))
        if e is None:
            self.request.response.setStatus(404)
            return {"error": "No such template."}
        try:
            template = json.loads(form.get("template") or "")
        except ValueError:
            self.request.response.setStatus(400)
            return {"error": "The template could not be read."}
        problems = dt.validate(e["kind"], template) + dt.warnings(e["kind"], template)
        try:
            doc, inputs = dt.compile_document(e["kind"], template, dt.example_data(e["kind"]))
        except ValueError as exc:
            return {"problems": problems + [u"%s" % exc]}
        return {"template": doc, "inputs": inputs, "problems": problems}

    # ── page data ───────────────────────────────────────────────────────────

    def entry(self):
        if not hasattr(self, "_entry"):
            entry = dt.load(api.get_portal()).get(self.request.form.get("id", ""))
            # a design of a retired kind (a logbook's) is kept, not opened
            self._entry = entry if entry and entry.get("kind") in dt.KINDS else None
        return self._entry

    def status(self):
        return dt.status(self.entry())

    def _starter(self, kind, entry):
        """A starting layout for an empty design of a kind that has one."""
        make = dt.KINDS[kind].get("starter")
        if not make or [f for page in (entry.get("draft") or {}).get("schemas") or [] for f in page]:
            return None
        size = dt.size_of(kind, entry.get("size")) or {"width": 210.0, "height": 297.0}
        return make(size["width"], size["height"])

    @staticmethod
    def _table(kind, name, cols):
        """A data table as the designer's chooser and column links need it."""
        spec = dt.KINDS[kind]
        headings = (spec.get("column_headings") or {}).get(name) or {}
        return {"name": name, "title": name.replace("_", " ").capitalize(),
                "columns": [{"key": k, "title": t, "example": x, "heading": headings.get(k) or t}
                            for k, t, x in cols],
                # a heading links to the column whose name it contains:
                # after every change where each heading must name its column
                "names": [{"key": k, "name": n, "earlier": old} for k, n, old in dt.column_names(kind, name)],
                "by_title": bool(spec.get("headings_name_columns")),
                # column chooser groups (sample / analysis information)
                "groups": [{"title": g, "keys": list(ks)} for g, ks in
                           (spec.get("column_groups") or {}).get(name) or []],
                "defaults": list((spec.get("column_defaults") or {}).get(name) or []) or None,
                "widths": dict((spec.get("column_widths") or {}).get(name) or {}),
                "right": list((spec.get("right_aligned") or {}).get(name) or [])}

    def _fonts(self):
        from senaite.pfas import pdf_layout_data
        base = "%s/++resource++senaite.pfas/fonts/print/" % self.portal_url()
        return [{"name": n, "url": base + f, "fallback": n == pdf_layout_data.FALLBACK}
                for n, f in pdf_layout_data.FONT_FILES]

    def config_json(self):
        """Everything the designer script needs, as one JSON blob."""
        e = self.entry()
        kind = e["kind"]
        data = {"id": e["id"], "kind": kind, "title": e["title"],
                "template": e.get("draft") or dt.blank(kind, e.get("size")),
                "fields": [{"key": k, "title": t, "example": x} for k, t, x in dt.KINDS[kind]["fields"]],
                "tables": [self._table(kind, n, cols) for n, cols in sorted(dt.tables(kind).items())],
                "groups": [{"title": g, "keys": [k for k, _t, _x in fs]} for g, fs in dt.groups(kind)],
                "images": list(dt.images(kind)),
                "placeholder": dt._coa.placeholder_png() if dt.images(kind) else "",
                "every_page": dt.EVERY_PAGE, "columns_key": dt.COLUMNS,
                "long": list(dt.KINDS[kind].get("long") or ()),
                "starter": self._starter(kind, e),
                "bindable": list(dt.BINDABLE),
                "problems": dt.validate(kind, e.get("draft")) + dt.warnings(kind, e.get("draft")),
                # the renderer's fonts, so the designer wraps text as the PDF does
                "fonts": self._fonts(),
                "can_edit": bool(self.can_configure()),
                "endpoint": "%s/@@pfas-document-designer" % self.portal_url()}
        # a JSON string inside <script>: never let it close the tag
        return dt.script_json(data)
