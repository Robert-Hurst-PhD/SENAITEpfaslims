# -*- coding: utf-8 -*-
"""Manual integration review.

    @@pfas-manual-integration   on a worksheet: the manual integrations (from
                                the export, or added from the report), each
                                with a reason, its before / after pages and
                                the analyst's then a different reviewer's
                                signature; the page viewer; Stamp
    @@pfas-mi-report?which=original|stamped   the report PDF, for the viewer
    @@pfas-mi-reasons           the lab's reason list (managers)

The rules live in manual_integration.py (pure). The records are stored on the
worksheet (annotation); the report files stay on disk, the stamped copy in a
sub-folder beside the original, which is never altered. A page view never
writes: what the export detected and a changed report are applied to a COPY
for display and for the gate, and saved with the next action. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import copy
import datetime
import hashlib
import io
import json
import logging
import os

from AccessControl import getSecurityManager
from bika.lims import api
from Products.CMFPlone.utils import safe_unicode
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations

from senaite.pfas import manual_integration as mi
from senaite.pfas import report_scan
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import GateMixin, TIER_CONFIG, deny_gated_action, refuse

logger = logging.getLogger("senaite.pfas.manual_integration")

KEY = "senaite.pfas.manual_integration"
SETTINGS_KEY = "senaite.pfas.manual_integration.settings"
REPORT_DIR = os.environ.get("PFAS_INSTRUMENT_REPORTS", "/data/instrument_reports")
STAMPED_DIR = "manual-integration-stamped"
RENDER_URL = os.environ.get("PFAS_RENDER_URL", "http://pfas-render:3000")
WORK_ROLES = frozenset(("Manager", "LabManager", "Analyst", "Verifier", "LabClerk"))
SIGN_RIGHT = {"analyst": "preparer", "reviewer": "reviewer"}
REASON_GATES = {"save_reasons": TIER_CONFIG}


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def _who():
    return safe_unicode(getSecurityManager().getUser().getId() or u"")


# ── the lab's settings: reasons, report heading ────────────────────────────

def get_settings(portal=None):
    portal = portal or api.get_portal()
    raw = IAnnotations(portal).get(SETTINGS_KEY)
    try:
        data = json.loads(raw) if raw else {}
    except (ValueError, TypeError):
        data = {}
    if not data.get("reasons"):
        data["reasons"] = [{"id": i, "text": t, "source": s, "active": True}
                           for i, t, s in mi.SEED_REASONS]
    data.setdefault("heading", u"Manual Integration")
    return data


def save_settings(portal, data):
    try:
        from senaite.pfas import config_history
        config_history.track(portal, "manual_integration_settings", "settings",
                             lambda: get_settings(portal), label=u"Manual integration reasons")
    except Exception:                                       # noqa: BLE001
        logger.warning("manual integration settings not tracked", exc_info=True)
    IAnnotations(portal)[SETTINGS_KEY] = json.dumps(data, sort_keys=True)


# ── a worksheet's records and report ───────────────────────────────────────

def load_state(ws):
    raw = IAnnotations(ws).get(KEY)
    try:
        return json.loads(raw) if raw else mi.empty_state()
    except (ValueError, TypeError):
        return mi.empty_state()


def save_state(ws, state):
    IAnnotations(ws)[KEY] = json.dumps(state, sort_keys=True)


def _report_dir(ws):
    return os.path.join(REPORT_DIR, ws.UID())


def report_files(ws):
    """[file name] of the worksheet's PDF reports, newest first."""
    d = _report_dir(ws)
    if not os.path.isdir(d):
        return []
    pdfs = [n for n in os.listdir(d)
            if n.lower().endswith(".pdf") and os.path.isfile(os.path.join(d, n))]
    return sorted(pdfs, key=lambda n: os.path.getmtime(os.path.join(d, n)), reverse=True)


def resolve_report(ws, state):
    """The report under review: the pinned file; else the one whose content
    the records refer to; else the only PDF. Several PDFs and none of these
    -> None (someone chooses). Never "the newest wins": a second upload must
    not move the pages to another file."""
    names = report_files(ws)
    d = _report_dir(ws)
    pinned = state.get("report_file")
    if pinned in names:
        return os.path.join(d, pinned)
    if state.get("report_fp"):
        for n in names:
            if file_fp(os.path.join(d, n)) == state["report_fp"]:
                return os.path.join(d, n)
    if len(names) == 1:
        return os.path.join(d, names[0])
    return None


_FP_CACHE = {}


def file_fp(path):
    """sha256 of a file, cached by (path, size, mtime): a large report is
    hashed once, not on every page view."""
    if not path:
        return u""
    st = os.stat(path)
    key = (path, st.st_size, st.st_mtime)
    if key not in _FP_CACHE:
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        if len(_FP_CACHE) > 256:
            _FP_CACHE.clear()
        _FP_CACHE[key] = h.hexdigest()
    return _FP_CACHE[key]


def detected(ws):
    """([{"injection", "analyte", "qc_type"}] flagged manual, captured): what
    the export of this worksheet's run said. captured False = the export
    carried no manual-integration column (or no run is stored)."""
    import sqlite3
    from senaite.pfas.qc.store import DEFAULT_DB_PATH
    if not os.path.exists(DEFAULT_DB_PATH):
        return [], False
    con = sqlite3.connect(DEFAULT_DB_PATH)
    try:
        cols = [r[1] for r in con.execute("PRAGMA table_info(injection_results)")]
        if "manual_integration" not in cols:
            return [], False
        rows = con.execute("SELECT injection_name, analyte, qc_type, manual_integration "
                           "FROM injection_results WHERE batch_id=?", (ws.getId(),)).fetchall()
    finally:
        con.close()
    captured = any(r[3] is not None for r in rows)
    flagged, seen = [], set()
    for inj, an, qc, flag in rows:
        if flag and (inj, an) not in seen:
            seen.add((inj, an))
            flagged.append({"injection": inj, "analyte": an, "qc_type": qc or u""})
    return flagged, captured


def current_state(ws, who=u"system"):
    """(state, report path, report fp, captured): the stored records with the
    export's detections and a changed report applied -- a copy, unsaved."""
    state = copy.deepcopy(load_state(ws))
    path = resolve_report(ws, state)
    fp = file_fp(path)
    mi.rebind_report(state, fp, who, _now())
    state["report_file"] = os.path.basename(path) if path else u""
    rows, captured = detected(ws)
    mi.merge_detected(state, rows, who, _now())
    return state, path, fp, captured


NOT_SCANNED = u"the report has not been scanned: Scan the report (manual integration page)"


def server_scan(fp):
    """(server pages for mi.gate, status): status "scanned", "no text" (a
    scanned image: no scan, the typed record stands in) or "not scanned".
    Reads the kept scan only; never scans."""
    if not fp:
        return None, u""
    texts = report_scan.get(fp)
    if texts is None:
        return None, u"not scanned"
    pages = mi.server_heading_pages(texts, get_settings().get("heading"))
    return pages, (u"scanned" if pages is not None else u"no text")


def evaluate(state, fp, captured):
    """(ok, [missing], server pages, status): the gate with the server's scan.
    A report not yet scanned is refused: the gate never scans (seconds on a
    large report) and never passes on a scan it has not seen."""
    server, status = server_scan(fp)
    ok, need = mi.gate(state, fp, captured, server)
    if status == u"not scanned":
        ok, need = False, [NOT_SCANNED] + need
    return ok, need, server, status


def gate_state(ws):
    """(ok, [missing], state) for the Instrument Report gate of Data Review;
    a stamped copy that is missing or altered on disk counts as none."""
    state, _path, fp, captured = current_state(ws)
    stamped = state.get("stamped") or {}
    if stamped:
        stamped_path = os.path.join(_report_dir(ws), STAMPED_DIR, stamped.get("file") or u"")
        if not os.path.isfile(stamped_path) or file_fp(stamped_path) != stamped.get("fp"):
            state["stamped"] = None
    ok, need, _server, _status = evaluate(state, fp, captured)
    return ok, need, state


def scan_quietly(path):
    """Scan a report on upload; a failure is logged, and the gate then says
    the report has not been scanned."""
    try:
        if path and path.lower().endswith(".pdf"):
            fp = file_fp(path)
            if report_scan.get(fp) is None:
                report_scan.scan_file(path, fp)
    except Exception:                                       # noqa: BLE001
        logger.warning("instrument report not scanned: %s", path, exc_info=True)


def gate(ws):
    """(ok, [missing]) for the Instrument Report gate of Data Review."""
    return gate_state(ws)[:2]


def _render(path, body):
    import urllib2
    # a byte-string URL: a unicode one makes httplib's headers unicode, and
    # appending the binary PDF to them then fails (Python 2)
    req = urllib2.Request(str(RENDER_URL + path), body)
    try:
        return urllib2.urlopen(req, timeout=180).read()
    except urllib2.HTTPError as exc:
        try:
            msg = json.loads(exc.read()).get("error")
        except Exception:                                   # noqa: BLE001
            msg = u"%s" % exc
        raise ValueError(u"the stamping service refused: %s" % msg)


def page_count(path):
    with open(path, "rb") as fh:
        return int(json.loads(_render("/pages", fh.read())).get("pages") or 0)


# ── views ──────────────────────────────────────────────────────────────────

class PFASManualIntegrationView(BrowserView):

    template = ViewPageTemplateFile("templates/manual_integration.pt")

    def __call__(self):
        flatten_form(self.request)
        self.error = self.request.form.get("error") or u""
        self.ok = self.request.form.get("ok") or u""
        if self.request.method == "POST":
            if not self.can_work():
                return refuse(self.request)
            from plone.protect import CheckAuthenticator
            from zExceptions import Forbidden
            try:
                CheckAuthenticator(self.request)
            except Forbidden:
                return refuse(self.request)
            try:
                msg = self._act(self.request.form.get("action") or u"")
                return self._back(ok=msg)
            except (ValueError, KeyError) as exc:
                return self._back(error=u"%s" % exc)
        return self.template()

    # who
    def _roles(self):
        user = getSecurityManager().getUser()
        portal = api.get_portal()
        try:
            # at the portal: a local role on the worksheet (Owner) grants nothing
            return set(user.getRolesInContext(portal))
        except Exception:                                   # noqa: BLE001
            return set()

    def can_work(self):
        return bool(self._roles() & WORK_ROLES)

    def _back(self, ok=u"", error=u""):
        from six.moves.urllib.parse import quote_plus
        q = ("ok=" + quote_plus(ok.encode("utf-8"))) if ok else ("error=" + quote_plus(error.encode("utf-8")))
        self.request.response.redirect("%s/@@pfas-manual-integration?%s" % (self.context.absolute_url(), q))
        return u""

    # data for the page
    def data(self):
        if not hasattr(self, "_data"):
            state, path, fp, captured = current_state(self.context, _who())
            ok, need, server, scan_status = evaluate(state, fp, captured)
            reasons = get_settings()["reasons"]
            files = report_files(self.context)
            scan = state.get("heading_scan") or {}
            self._data = {"state": state, "path": path, "fp": fp, "captured": captured,
                          "ok": ok, "missing": need,
                          "files": files, "choose": len(files) > 1,
                          "scan": scan if scan.get("fp") == fp and fp else None,
                          # what was recorded: the pages, or "none" (an attestation)
                          "scan_text": (u", ".join(u"%d" % p for p in scan["pages"]) or u"none")
                          if scan.get("fp") == fp and fp else u"",
                          "uncovered": mi.uncovered(state, server),
                          "server": server, "scan_status": scan_status,
                          "dismissed": sorted((int(k), v) for k, v in (state.get("dismissed") or {}).items()),
                          "none": state.get("none_in_report"),
                          "reasons": [r for r in reasons if r.get("active", True)],
                          "file": os.path.basename(path) if path else u"",
                          "heading": get_settings().get("heading"),
                          "stamped": (state.get("stamped") or {}).get("file")}
        return self._data

    def records(self):
        out = []
        for r in self.data()["state"].get("records") or []:
            row = dict(r)
            row["qc_flag"] = (r.get("qc_type") or u"") in mi.QC_TYPES_FLAGGED
            out.append(row)
        return out

    def history(self):
        return list(reversed(self.data()["state"].get("history") or []))[:200]

    def portal_url(self):
        return api.get_portal().absolute_url()

    # actions
    def _act(self, action):
        ws = self.context
        who, when = _who(), _now()
        state, path, fp, captured = current_state(ws, who)
        form = self.request.form
        if action == "save":
            reasons = dict((r["id"], r) for r in get_settings()["reasons"])
            heading = mi.parse_pages(form.get("heading_pages"))
            found = mi.parse_pages(form.get("scan_found"))     # the viewer's own result
            pages = page_count(path) if path and (heading or any(
                form.get("%s.%s" % (r["id"], k)) for r in state.get("records") or []
                for k in ("before_page", "after_page"))) else 0
            if heading is not None and path:
                if form.get("scan_fp") and form.get("scan_fp") != fp:
                    raise ValueError(u"The report changed while the page was open: reload it.")
                over = [p for p in heading + (found or []) if pages and p > pages]
                if over:
                    raise ValueError(u"Heading page %d is not in the report (%d pages)." % (over[0], pages))
                mi.record_scan(state, fp, heading, who, when, found)
            for r in state.get("records") or []:
                fields = {}
                rid = form.get("%s.reason_id" % r["id"])
                if rid is not None:
                    fields["reason_id"] = rid
                    fields["reason"] = reasons[rid]["text"] if rid in reasons else u""
                for k in ("detail", "before_page", "after_page"):
                    if ("%s.%s" % (r["id"], k)) in form:
                        fields[k] = form.get("%s.%s" % (r["id"], k))
                for k in ("before_page", "after_page"):
                    v = fields.get(k)
                    if v not in (None, u"") and pages and int(v) > pages:
                        raise ValueError(u"%s: page %s is not in the report (%d pages)" % (r["id"], v, pages))
                mi.update(state, r["id"], fields, who, when)
            msg = u"Saved."
        elif action == "add":
            inj = (form.get("injection") or u"").strip()
            an = (form.get("analyte") or u"").strip()
            if not inj or not an:
                raise ValueError(u"Give the injection and the analyte.")
            mi.add(state, inj, an, u"report", (form.get("qc_type") or u"").strip(), who, when)
            msg = u"Added."
        elif action in ("sign_analyst", "sign_reviewer"):
            role = action.split("_")[1]
            # one scalar field per row (sel.<id>): PFAS forms post no lists
            ids = [r["id"] for r in state.get("records") or [] if form.get("sel.%s" % r["id"])]
            if not ids:
                raise ValueError(u"Tick the manual integrations to sign.")
            from senaite.pfas.browser import staff
            info = staff.staff_info(who)
            if SIGN_RIGHT[role] not in info["sign_as"]:
                raise ValueError(u"%s may not sign as %s (Lab Staff)." % (info["fullname"] or who, SIGN_RIGHT[role]))
            if not info["signature"]:
                raise ValueError(u"%s has no signature on file (Profile & signature)." % (info["fullname"] or who))
            for rid in ids:
                mi.sign(state, rid, role, who, when, info["fullname"] or who)
            msg = u"Signed %d as %s." % (len(ids), role)
        elif action == "use_report":
            name = form.get("report") or u""
            if name not in report_files(ws):
                raise ValueError(u"Choose one of the worksheet's reports.")
            new = os.path.join(_report_dir(ws), name)
            mi.rebind_report(state, file_fp(new), who, when)
            if state.get("report_file") != name:
                mi._log(state, who, when, u"", u"report under review", {"file": [state.get("report_file") or None, name]})
            state["report_file"] = name
            scan_quietly(new)
            msg = u"Reviewing %s." % name
        elif action == "dismiss":
            page = form.get("page") or u""
            if not page.isdigit():
                raise ValueError(u"Which page?")
            mi.dismiss(state, int(page), form.get("dismiss_reason"), who, when, server_scan(fp)[0])
            msg = u"Page %s dismissed." % page
        elif action == "countersign":
            from senaite.pfas.browser import staff
            info = staff.staff_info(who)
            if SIGN_RIGHT["reviewer"] not in info["sign_as"]:
                raise ValueError(u"%s may not countersign (reviewer sign right, Lab Staff)." % (info["fullname"] or who))
            kind = form.get("kind") or u""
            page = form.get("page") or u""
            mi.countersign(state, kind, who, when, info["fullname"] or who,
                           page=int(page) if page.isdigit() else None)
            msg = u"Countersigned."
        elif action == "scan":
            if not path:
                raise ValueError(u"No instrument report PDF.")
            texts = report_scan.scan_file(path, fp)
            found = mi.server_heading_pages(texts, get_settings().get("heading"))
            mi._log(state, who, when, u"", u"report scanned", {"heading pages": [None, found]})
            msg = (u"Scanned: heading on pages %s." % (u", ".join(u"%d" % p for p in found) or u"none")
                   if found is not None else u"Scanned: the report has no text; record the heading pages by hand.")
        elif action == "confirm_none":
            from senaite.pfas.browser import staff
            mi.confirm_none(state, who, when, staff.staff_info(who)["fullname"] or who)
            msg = u"Recorded: no manual integration in the report."
        elif action == "stamp":
            msg = self._stamp(state, path, fp, captured, who, when)
        else:
            raise ValueError(u"Unknown action.")
        save_state(ws, state)
        return msg

    def _stamp(self, state, path, fp, captured, who, when):
        ok, need = evaluate(dict(state, stamped={"of": mi.signed_fingerprint(state)}), fp, captured)[:2]
        if not ok:
            raise ValueError(u"Not ready to stamp: " + u"; ".join(need))
        if not path:
            raise ValueError(u"No instrument report PDF.")
        from senaite.pfas.browser import staff
        sigs = {}
        for r in state.get("records") or []:
            for role in ("analyst", "reviewer"):
                uid = r[role]["userid"]
                if uid not in sigs:
                    sigs[uid] = staff.staff_info(uid)["signature"]
                if not sigs[uid]:
                    raise ValueError(u"%s has no signature on file." % r[role]["name"])
        # one block per record per page: several chromatograms on one page
        # each get their own block, stacked in that page's strip; before and
        # after on the same page share one block
        by_page = {}
        for r in state.get("records") or []:
            sides = ((("BEFORE AND AFTER", r["before_page"]),) if r["before_page"] == r["after_page"] else
                     (("BEFORE (automatic integration)", r["before_page"]),
                      ("AFTER (manual integration)", r["after_page"])))
            for which, page in sides:
                block = {"title": u"MANUAL INTEGRATION - %s: %s / %s" % (which, r["injection"], r["analyte"]),
                         "lines": [u"Reason: %s" % r["reason"]]
                         + ([u"Detail: %s" % r["detail"]] if r.get("detail") else [])
                         + [u"Record %s, worksheet %s" % (r["id"], self.context.getId())],
                         "signatures": [
                             {"label": u"Analyst: %s %s" % (r["analyst"]["name"], r["analyst"]["at"][:10]),
                              "png": sigs[r["analyst"]["userid"]]},
                             {"label": u"Reviewer: %s %s" % (r["reviewer"]["name"], r["reviewer"]["at"][:10]),
                              "png": sigs[r["reviewer"]["userid"]]}]}
                if block not in by_page.setdefault(page, []):
                    by_page[page].append(block)
        spec = {"stamps": [{"page": p, "blocks": b} for p, b in sorted(by_page.items())]}
        with open(path, "rb") as fh:
            pdf = _render("/stamp", json.dumps(spec).encode("utf-8") + b"\n" + fh.read())
        out_dir = os.path.join(_report_dir(self.context), STAMPED_DIR)
        if not os.path.isdir(out_dir):
            os.makedirs(out_dir)
        n = len([x for x in os.listdir(out_dir) if x.endswith(".pdf")]) + 1
        name = u"%s-manual-integration-%d.pdf" % (os.path.splitext(os.path.basename(path))[0], n)
        with io.open(os.path.join(out_dir, name), "wb") as fh:
            fh.write(pdf)
        state["stamped"] = {"file": name, "fp": hashlib.sha256(pdf).hexdigest(),
                            "of": mi.signed_fingerprint(state), "at": when, "by": who}
        mi._log(state, who, when, u"", u"stamped", {"file": [None, name]})
        return u"Stamped copy %s written; the original is unchanged." % name


class PFASMIReportView(BrowserView):
    """The worksheet's report PDF (original or stamped copy), for the viewer
    and for download; only for those who may view the worksheet."""

    def __call__(self):
        flatten_form(self.request)
        if not getSecurityManager().checkPermission("View", self.context):
            return refuse(self.request)
        which = self.request.form.get("which") or u"original"
        if which == "stamped":
            st = load_state(self.context).get("stamped") or {}
            path = os.path.join(_report_dir(self.context), STAMPED_DIR, st.get("file") or u"_")
        else:
            # the report under review, never simply the newest file
            path = resolve_report(self.context, load_state(self.context))
        if not path or not os.path.isfile(path):
            self.request.response.setStatus(404)
            return u"No such report."
        resp = self.request.response
        resp.setHeader("Content-Type", "application/pdf")
        resp.setHeader("Content-Disposition", str('inline; filename="%s"' % os.path.basename(path)))
        with open(path, "rb") as fh:
            return fh.read()


class PFASMIReasonsView(GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/manual_integration_reasons.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, req.form.get("action", ""), REASON_GATES)
            if denied is not None:
                return denied
            from plone.protect import CheckAuthenticator
            CheckAuthenticator(req)
            portal = api.get_portal()
            data = get_settings(portal)
            reasons, i = [], 0
            while ("r.%d.text" % i) in req.form:
                text = (req.form.get("r.%d.text" % i) or u"").strip()
                rid = (req.form.get("r.%d.id" % i) or u"").strip() or u"lab-%d" % (i + 1)
                if text:
                    reasons.append({"id": rid, "text": text,
                                    "source": (req.form.get("r.%d.source" % i) or u"").strip(),
                                    "active": bool(req.form.get("r.%d.active" % i))})
                i += 1
            if not reasons:
                req.response.redirect(api.get_portal().absolute_url() + "/@@pfas-mi-reasons?error=Keep+at+least+one+reason.")
                return u""
            data["reasons"] = reasons
            data["heading"] = (req.form.get("heading") or u"").strip() or u"Manual Integration"
            save_settings(portal, data)
            req.response.redirect(api.get_portal().absolute_url() + "/@@pfas-mi-reasons?saved=1")
            return u""
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def settings(self):
        return get_settings()

    def improper(self):
        return mi.IMPROPER
