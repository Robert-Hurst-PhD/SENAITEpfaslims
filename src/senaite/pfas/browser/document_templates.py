# -*- coding: utf-8 -*-
"""Document Templates: the lab draws its documents.

    @@pfas-document-templates   the templates, their revisions; new / issue /
                                archive / restore
    @@pfas-document-designer    the drag-and-drop designer (pdfme) for one
                                template's DRAFT; save_draft answers JSON

Drawing and issuing are lab configuration (TIER_CONFIG). A template prints
only from its ISSUED revision; the draft is work in progress. Labels print in
the browser (@@pfas-label); the model, validation and store are
senaite.pfas.document_templates. Python 2.7.
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
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action
from senaite.pfas.browser.perms import refuse

logger = logging.getLogger("senaite.pfas.document_templates")

LIST_GATES = {"new": TIER_CONFIG, "issue": TIER_CONFIG, "archive": TIER_CONFIG,
              "restore": TIER_CONFIG}
DESIGNER_GATES = {"save_draft": TIER_CONFIG}


def _who():
    return getSecurityManager().getUser().getId()


def _text(form, key, default=u""):
    """A form value as text: Python 2 forms deliver UTF-8 bytes."""
    return safe_unicode(form.get(key) or default)


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def _register_logbooks():
    """Each active logbook definition is a document kind."""
    try:
        from senaite.pfas.browser.logbook_designs import register_all
        register_all(api.get_portal())
    except Exception:                                       # noqa: BLE001
        logger.warning("logbook kinds not registered", exc_info=True)


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


class PFASDocumentTemplatesView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/document_templates.pt")

    def __call__(self):
        flatten_form(self.request)
        _register_logbooks()
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
            url = "%s/@@pfas-document-templates" % self.portal_url()
            if action == "new" and tid and not msg.startswith("error:"):
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
            if dt.size_of(kind, _text(form, "size")) is None:
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

    def _archive(self, form, archived):
        portal, store, tid = self._existing(form)
        if tid not in store:
            return u"error:No such template.", None
        store[tid]["archived"] = archived
        dt.save(portal, store)
        return u"ok:%s %s." % (store[tid]["title"], "archived" if archived else "restored"), tid

    # ── page data ───────────────────────────────────────────────────────────

    def portal_url(self):
        return api.get_portal().absolute_url()

    def message(self):
        return _text(self.request.form, "ok"), _text(self.request.form, "error")

    def kinds(self):
        store = dt.load(api.get_portal())
        return [{"id": k, "title": v["title"],
                 "sizes": [{"id": s[0], "title": s[1]} for s in v["sizes"]],
                 "issued_with": v.get("issued_with"),
                 "single": bool(v.get("single")),
                 # a single design (the certificate) is created once
                 "can_add": not (v.get("single") and v["single"] in store)}
                for k, v in sorted(dt.KINDS.items(),
                                   key=lambda kv: (kv[0] != "coa", kv[0].startswith("logbook:"), kv[0]))]

    def _with_report_template(self, entry):
        """A certificate design's status: issued with which reporting-template
        revision, and whether the draft differs from it."""
        from senaite.pfas import report_templates as rt
        snap, rev = rt.issued_snapshot(api.get_portal())
        issued = rt.designed_layout(snap)
        return {"rev": rev if issued is not None else None, "issued_at": u"",
                "none_issued": issued is None,
                "unissued": issued is None or dt.fingerprint(issued) != dt.fingerprint(entry.get("draft"))}

    def rows(self, kind):
        store = dt.load(api.get_portal())
        out = []
        for tid in sorted(store, key=lambda t: (store[t].get("archived"), store[t].get("title"))):
            e = store[tid]
            if e.get("kind") != kind:
                continue
            st = (self._with_report_template(e) if dt.KINDS[kind].get("issued_with")
                  else dt.status(e))
            size = dt.size_of(kind, e.get("size")) or {}
            out.append({"id": tid, "title": e.get("title"), "size": size.get("title", e.get("size")),
                        "archived": bool(e.get("archived")), "status": st,
                        "problems": dt.validate(kind, e.get("draft")),
                        # an issued design drawn on an earlier definition (a
                        # logbook whose fields changed) is refused at print
                        "issued_problems": (dt.validate(kind, dt.current(e)["template"])
                                            if dt.current(e) and not dt.KINDS[kind].get("issued_with") else []),
                        "draft_by": e.get("draft_by") or u"", "draft_at": e.get("draft_at") or u"",
                        "history": sorted([dict((k, v) for k, v in r.items() if k != "template")
                                           for r in e.get("revisions") or []],
                                          key=lambda r: -r.get("rev", 0))})
        return out


class PFASDocumentDesignerView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/document_designer.pt")

    def __call__(self):
        flatten_form(self.request)
        _register_logbooks()
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
        problems = dt.validate(e["kind"], template)
        try:
            doc, inputs = dt.compile_document(e["kind"], template, dt.example_data(e["kind"]))
        except ValueError as exc:
            return {"problems": problems + [u"%s" % exc]}
        return {"template": doc, "inputs": inputs, "problems": problems}

    # ── page data ───────────────────────────────────────────────────────────

    def portal_url(self):
        return api.get_portal().absolute_url()

    def entry(self):
        if not hasattr(self, "_entry"):
            self._entry = dt.load(api.get_portal()).get(self.request.form.get("id", ""))
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

    def config_json(self):
        """Everything the designer script needs, as one JSON blob."""
        e = self.entry()
        kind = e["kind"]
        data = {"id": e["id"], "kind": kind, "title": e["title"],
                "template": e.get("draft") or dt.blank(kind, e.get("size")),
                "fields": [{"key": k, "title": t, "example": x} for k, t, x in dt.KINDS[kind]["fields"]],
                "tables": [{"name": n, "title": n.replace("_", " ").capitalize(),
                            "columns": [{"key": k, "title": t, "example": x} for k, t, x in cols],
                            # column chooser groups (sample / analysis information)
                            "groups": [{"title": g, "keys": list(ks)} for g, ks in
                                       (dt.KINDS[kind].get("column_groups") or {}).get(n) or []]}
                           for n, cols in sorted(dt.tables(kind).items())],
                "groups": [{"title": g, "keys": [k for k, _t, _x in fs]} for g, fs in dt.groups(kind)],
                "images": list(dt.images(kind)),
                "placeholder": dt._coa.placeholder_png() if dt.images(kind) else "",
                "every_page": dt.EVERY_PAGE, "columns_key": dt.COLUMNS,
                "long": list(dt.KINDS[kind].get("long") or ()),
                "starter": self._starter(kind, e),
                "bindable": list(dt.BINDABLE),
                "problems": dt.validate(kind, e.get("draft")),
                "can_edit": bool(self.can_configure()),
                "endpoint": "%s/@@pfas-document-designer" % self.portal_url()}
        # a JSON string inside <script>: never let it close the tag
        return dt.script_json(data)
