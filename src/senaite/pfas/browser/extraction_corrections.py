# -*- coding: utf-8 -*-
"""@@pfas-extraction-corrections on a Worksheet: a person corrects the
finalised extraction record. It takes a POST and redirects back to the
batch record page (back=record) or to Data Review (back=review):

    amend      one member fact (a QC type, a fortified blank's level, a
               parent, which sample a vial is, a spike lot), or a sample's
               amount or final volume copied wrongly
    revert     an amendment undone, with a reason, before it is confirmed
    confirm    the verifier confirms one correction
    send_back  the batch returned to its members, a stage, the run build or
               the data import
    reextract  members withheld for re-extraction; their analyses leave
               the worksheet for the next extraction batch

extraction_amendments refuses, before anything is written, what the
person, the worksheet's state, the member or the method does not allow;
the entry is appended to the worksheet's one log (extraction_amendments.KEY)
and to its trail (records.log). An amendment, an undo and a re-extraction
clear the Data Review sign-offs they judge again (kept on the entry) and,
once the save commits, queue the run again, as an identity correction
does. A released record is amended only by a Lab Manager, signed through
the signature dialog as the record's next revision; it keeps its review,
so nothing is cleared or judged again.

The pure parts (the levels offered, the stored run's judgement, the
analyses a re-extraction moves, the registry of re-extracted samples and
the rows the batch record lists) are functions here, read by the tests
outside Zope. Python 2.7 compatible.
"""
from __future__ import absolute_import, unicode_literals

import datetime
import json
import logging
import os

from senaite.pfas import extraction_amendments as ea

try:
    from Products.Five.browser import BrowserView
except ImportError:                                         # pragma: no cover
    # the pure parts are read by the tests outside Zope
    BrowserView = object

logger = logging.getLogger("senaite.pfas.browser.extraction_corrections")

# on the portal: {sample uid: {"ws", "ws_uid", "entry"}}, the worksheet and
# the re-extract entry that withheld each sample, read by the next batch
REGISTRY_KEY = "senaite.pfas.reextractions"

BACK_RECORD, BACK_REVIEW = "record", "review"
# the Data Review tabs a correction made there returns to
REVIEW_TABS = ("overview", "final_data", "instrument_report")

# a routine result awaiting verification (a retraction makes its retest);
# one not yet submitted, which leaves the worksheet as it is
AWAITING = "to_be_verified"
NOT_SUBMITTED = ("unassigned", "assigned")

DONE = {
    ea.AMEND: "Amended. The run is being judged again; release waits until it is.",
    "amend_released": "Amended and signed as the record's next revision.",
    ea.REVERT: "Amendment undone. The run is being judged again; release waits until it is.",
    ea.CONFIRM: "Correction confirmed.",
    ea.SEND_BACK: "Sent back. Every Data Review sign-off is cleared.",
    ea.REEXTRACT: ("Withheld for re-extraction. Its analyses left this worksheet for the next "
                   "extraction batch."),
}
NO_SIGN = "Sign the amendment to record it on a released record. Nothing was saved."
NO_SIGNER = ("A released record's next revision cannot be signed on this system yet. "
             "Nothing was saved.")
NOT_WRITTEN = "The worksheet's analyses could not be moved: {0}. Nothing was saved."


def _text(value):
    return ea._text(value)


def _now():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


# ── what the method offers ──────────────────────────────────────────────────

def _amount(value):
    return "%g" % value if isinstance(value, float) else _text(value)


def levels_for(profile, matrix, role, unit):
    """[(label, amount)]: the method's Spike levels for a member's QC type
    and the batch's matrix, each with its amount in the matrix's unit
    ("" where the method gives none). A profile keyed by QC type holds one
    list for every matrix."""
    from senaite.pfas.calibration_levels import level_value
    levels = (profile or {}).get("spike_levels") or {}
    keyed_by_type = bool([k for k in levels if k in ("LFSM", "LFB", "LCS", "LFSMD")])
    by_type = levels if keyed_by_type else (levels.get(matrix) or {})
    out, seen = [], set()
    for e in by_type.get(role) or []:
        lab = _text((e or {}).get("label"))
        if lab and lab not in seen:
            seen.add(lab)
            out.append((lab, _amount(level_value(e, unit))))
    return out


def spike_lot_numbers(lots):
    """The lot numbers of the spike lots usable today, as the members page
    lists them, once each."""
    out = []
    for lot in lots or ():
        n = _text((lot or {}).get("lot_number"))
        if n and n not in out:
            out.append(n)
    return out


# ── what the stored run judged ──────────────────────────────────────────────

def before_snapshot(conn, batch_id, names):
    """What the stored run judged for a member's injection, kept on an
    amendment because judging the same file again overwrites it:
    {"injection", "analytes": {analyte: {"expected", "recovery",
    "verdict"}}}; None when the run judged none of the names."""
    names = [n for n in (names or ()) if n]
    for name in names:
        rows = conn.execute(
            "SELECT analyte, expected_value, value, passed FROM qc_results WHERE batch_id=? "
            "AND result_status='active' AND instr(prov_key, ?) > 0 ORDER BY analyte",
            (batch_id, "|%s|" % name)).fetchall()
        if rows:
            return {"injection": name,
                    "analytes": dict((r[0], {"expected": r[1], "recovery": r[2],
                                             "verdict": "pass" if r[3] else "fail"}) for r in rows)}
    return None


# ── the analyses a re-extraction or a send back moves ───────────────────────

def release_analyses(ws, sample_uids, do, state_of, clear=None):
    """The routine analyses of the withheld samples leave the worksheet, so
    they wait for the next extraction batch: one not yet submitted has its
    pushed result cleared (`clear(analysis)`) and is taken off (unassigned);
    one awaiting verification is retracted and SENAITE's retest is taken
    off, as a rejected run's are. `do(obj, transition)` is the workflow's
    (True when done), `state_of(obj)` the review state. (moved, retests);
    ValueError when a retraction is refused."""
    uids = set(u for u in (sample_uids or ()) if u)
    moved, retests = [], []
    for analysis in list(ws.getAnalyses() or []):
        if getattr(analysis, "portal_type", "") != "Analysis":
            continue
        if analysis.getRequestUID() not in uids:
            continue
        state = state_of(analysis)
        if state == AWAITING:
            if not do(analysis, "retract"):
                raise ValueError("%s was not retracted" % analysis.getId())
            retest = analysis.getRetest()
            if retest is not None and retest.getWorksheet() is not None:
                ws.removeAnalysis(retest)
                retests.append(retest)
        elif state in NOT_SUBMITTED:
            if clear is not None:
                clear(analysis)
            ws.removeAnalysis(analysis)
            moved.append(analysis)
    return moved, retests


def clear_result(analysis):
    """A result the worker pushed, cleared before its analysis leaves."""
    analysis.setResult("")
    analysis.reindexObject()


# ── the samples re-extracted, for the next batch ────────────────────────────

def registry_add(registry, entry, ws_id, ws_uid, sample_uids):
    """The registry with each withheld sample naming its worksheet and the
    entry that withheld it (a new dict; a later re-extraction of the same
    sample replaces its line)."""
    out = dict((k, dict(v)) for k, v in (registry or {}).items())
    for uid in sample_uids or ():
        if uid:
            out[uid] = {"ws": _text(ws_id), "ws_uid": _text(ws_uid), "entry": _text(entry.get("id"))}
    return out


def reextraction_of(registry, sample_uid):
    """The worksheet a sample was withheld from for re-extraction, or ""."""
    return _text(((registry or {}).get(sample_uid) or {}).get("ws"))


def links_due(registry, ws_uid, sample_uids):
    """[(original worksheet uid, entry id)]: the re-extractions a finalised
    worksheet holds samples of, once each, never its own."""
    out = []
    for uid in sample_uids or ():
        rec = (registry or {}).get(uid)
        if not rec or rec.get("ws_uid") == ws_uid:
            continue
        pair = (rec.get("ws_uid"), rec.get("entry"))
        if pair not in out:
            out.append(pair)
    return out


# ── the rows the batch record lists ─────────────────────────────────────────

def correction_rows(state, members, show=None):
    """The batch record's rows when batch_record.corrections is not there
    to give them, in its shape: every entry but a confirmation and a link,
    oldest first: {id, action, what, before, after, reason, by, at,
    in_force, countersigned, countersign, can_undo}."""
    show = show or (lambda at: at)
    state = ea.load(state)
    confirms = dict((e.get("confirms"), e) for e in state["log"] if e.get("action") == ea.CONFIRM)
    undone = ea._reverted(state)
    out = []
    for e in state["log"]:
        act = e.get("action")
        if act in (ea.CONFIRM, ea.LINK):
            continue
        eid = e.get("id") or ""
        c = confirms.get(eid)
        standing = act in ea.CONFIRMED_KINDS and eid not in undone
        if c:
            word = "Countersigned by %s" % (c.get("name") or c.get("by"))
        elif standing and not e.get("after_release"):
            word = "Awaiting countersign"
        else:
            word = ""
        amended = act == ea.AMEND
        out.append({"id": eid, "action": act, "what": ea.describe(e, members),
                    "before": _text(e.get("from")) if amended else "",
                    "after": _text(e.get("to")) if amended else "",
                    "reason": e.get("reason") or "", "by": e.get("name_by") or e.get("by") or "",
                    "at": show(e.get("at")) if e.get("at") else "",
                    "in_force": standing, "countersigned": bool(c), "countersign": word,
                    "can_undo": bool(amended and standing and not c and not e.get("after_release"))})
    return out


# ── one worksheet's record, as a correction reads it ────────────────────────

class Facts(object):
    """The finalised record a correction of worksheet `ws` reads: the
    stored members and sample rows, the amendments in force, the session,
    and the values the method offers (through the members page's own
    reading of the profile, the matrix and the usable spike lots)."""

    def __init__(self, ws, request):
        self.ws, self.request = ws, request
        self._memo = {}

    def _once(self, key, fn):
        if key not in self._memo:
            self._memo[key] = fn()
        return self._memo[key]

    def state(self):
        from senaite.pfas import annotation_store
        return self._once("state", lambda: ea.load(annotation_store.read_json(self.ws, ea.KEY, {})))

    def members(self):
        from senaite.pfas import extraction_batch
        return self._once("members", lambda: list(extraction_batch.load(self.ws) or []))

    def in_force(self):
        return self._once("in_force", lambda: ea.members_in_force(self.members(), self.state()))

    def member(self, member_id):
        return dict((m.get("id"), m) for m in self.in_force()).get(member_id)

    def rows(self):
        """The extraction table's sample rows that count, keyed as every
        reader keys them (a sample by its member's injection name): what an
        amount amendment names and the record in force is read over."""
        from senaite.pfas import extraction_batch, extraction_store
        from senaite.pfas.logbook_schema import active_rows

        def read():
            table = extraction_store.load_table(self.ws) or {}
            return extraction_batch.rekey_rows(active_rows(table.get("samples") or []), self.members())
        return self._once("rows", read)

    def rows_in_force(self):
        return self._once("rows_in_force", lambda: ea.samples_in_force(self.rows(), self.state()))

    def session(self):
        from senaite.pfas.browser.extraction_guide import _load_session
        return self._once("session", lambda: _load_session(self.ws) or {})

    def finalised(self):
        return bool(self.session().get("finalized"))

    def review_state(self):
        from bika.lims import api
        return self._once("review_state", lambda: api.get_review_status(self.ws))

    def batch_view(self):
        def read():
            from senaite.pfas.browser.extraction_batch_view import PFASExtractionBatchView
            return PFASExtractionBatchView(self.ws, self.request)
        return self._once("batch_view", read)

    def levels(self, member):
        bv = self.batch_view()
        return levels_for(bv.profile(), bv.matrix(), (member or {}).get("role"), bv.unit())

    def level_amounts(self, member):
        return dict((lab, amount) for lab, amount in self.levels(member) if amount)

    def offered(self, field, member):
        """The values an amendment of `field` on the member may take."""
        if member is None:
            return []
        bv = self.batch_view()
        return ea.offered(field, member, self.in_force(),
                          profile_levels=[lab for lab, _a in self.levels(member)],
                          qc_types=bv.add_roles(), spike_lots=spike_lot_numbers(bv.spike_lots()))

    def dialog(self):
        """What the Amend window offers each member and sample row: {key:
        {label, fields: {field: {label, now, offered [[value, label]],
        number, rejudged}}}}; only the fields with something to offer."""
        out = {}
        labels = dict((m.get("id"), m.get("injection") or m.get("id")) for m in self.in_force())
        for m in self.in_force():
            fields = {}
            for field in ea.MEMBER_FIELDS:
                values = self.offered(field, m)
                if not values:
                    continue
                if field == ea.LEVEL:
                    amounts = self.level_amounts(m)
                    pairs = [[v, "%s · %s" % (v, amounts[v]) if amounts.get(v) else v] for v in values]
                elif field in (ea.PARENT, ea.SAMPLE):
                    pairs = [[v, labels.get(v) or v] for v in values]
                else:
                    pairs = [[v, v] for v in values]
                now = m.get("sample_id") if field == ea.SAMPLE else m.get(field)
                if field in (ea.PARENT,):
                    now = labels.get(now) or now
                fields[field] = {"label": ea.FIELD_LABELS[field], "now": _text(now) or "Not recorded",
                                 "offered": pairs, "number": False, "rejudged": ea.rejudged(field, m)}
            if fields:
                out[m.get("id")] = {"label": "%s · %s" % (labels.get(m.get("id")), m.get("role")),
                                    "fields": fields}
        for r in self.rows_in_force():
            sid = r.get("sample_id")
            if not sid:
                continue
            out["sample:" + sid] = {"label": "%s · extracted amount" % sid, "fields": dict(
                (field, {"label": ea.FIELD_LABELS[field], "now": _text(r.get(field)) or "Not recorded",
                         "offered": [], "number": True, "rejudged": ea.rejudged(field, {})})
                for field in ea.SAMPLE_FIELDS)}
        return out

    def dialog_json(self):
        """dialog() as the window's script reads it."""
        return json.dumps(self.dialog(), sort_keys=True)


# ── a later Finalise links each re-extraction back ──────────────────────────

def link_reextractions(ws, who, at):
    """Called once worksheet `ws` is finalised: each re-extraction whose
    samples it now holds gains a link entry in the original worksheet's log
    (extraction_amendments.link), once; the two records then name each
    other. Never raises past a lookup that fails: the Finalise stands."""
    from bika.lims import api
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import annotation_store, extraction_batch, records
    portal = api.get_portal()
    registry = annotation_store.read_json(portal, REGISTRY_KEY, {})
    if not registry:
        return []
    uids = [m.get("sample_uid") for m in extraction_batch.load(ws) or [] if m.get("role") == "Sample"]
    made = []
    for ws_uid, entry_id in links_due(registry, ws.UID(), uids):
        orig = api.get_object_by_uid(ws_uid, None)
        if orig is None:
            continue
        state = ea.load(annotation_store.read_json(orig, ea.KEY, {}))
        if entry_id in ea.links(state):
            continue
        problem, state, entry = ea.link(state, entry_id, ws.getId(), who, at)
        if problem:
            logger.info("re-extraction %s of %s not linked: %s", entry_id, orig.getId(), problem)
            continue
        IAnnotations(orig)[ea.KEY] = ea.dump(state)
        records.log(orig, "reextraction_linked", detail={"entry": entry_id, "ws": ws.getId()})
        made.append(entry["id"])
    return made


# ── the view ────────────────────────────────────────────────────────────────

class PFASExtractionCorrectionsView(BrowserView):
    """The POST target of every extraction correction."""

    def __call__(self):
        from senaite.pfas.browser.formutil import flatten_form
        from senaite.pfas.browser.perms import refuse
        flatten_form(self.request)
        if self.request.method != "POST":
            return self._back(error="")
        try:
            from plone.protect import CheckAuthenticator
            CheckAuthenticator(self.request)
        except ImportError:                                 # pragma: no cover
            pass
        if not (self._can_record() or self._is_analyst() or self._is_manager()):
            return refuse(self.request, "Forbidden: bench, analyst or manager role required")
        # recording a correction is data entry: a Lab Contact, initials and
        # a signature, as on the extraction and review pages
        from senaite.pfas import entry_rights
        from senaite.pfas.browser.staff import is_automation, may_enter
        if not is_automation() and not may_enter():
            return self._refuse(entry_rights.REFUSAL)
        return self._dispatch()

    def _dispatch(self):
        handler = {
            "amend": self._handle_amend,
            "revert": self._handle_revert,
            "confirm": self._handle_confirm,
            "send_back": self._handle_send_back,
            "reextract": self._handle_reextract,
        }.get(self.request.form.get("action") or "")
        if handler is None:
            return self._back(error="")
        return handler()

    def _back(self, ok="", error=""):
        """Back to the page the form came from: the batch record, or Data
        Review on the tab it names."""
        from six.moves.urllib.parse import quote
        f = self.request.form
        ws = self.context
        text = ok or error

        def q(value):
            return quote(_text(value).encode("utf-8"), safe="")
        if f.get("back") == BACK_REVIEW:
            tab = f.get("tab") if f.get("tab") in REVIEW_TABS else "overview"
            url = "%s/@@pfas-data-review?tab=%s" % (ws.absolute_url(), tab)
            if text:
                url += "&msg=%s&msg_type=%s&detail=%s" % (
                    "extraction_corrected" if ok else "extraction_refused", "ok" if ok else "error", q(text))
        else:
            from bika.lims import api
            url = "%s/@@pfas-batch-records?record=%s" % (api.get_portal().absolute_url(), ws.UID())
            if text:
                url += "&%s=%s&ea=1" % ("ok" if ok else "error", q(text))
        self.request.response.redirect(url)
        return ""

    def _refuse(self, problem):
        return self._back(error=problem)

    # ── who ─────────────────────────────────────────────────────────────

    def _user(self):
        from AccessControl import getSecurityManager
        return getSecurityManager().getUser()

    def _who(self):
        """The acting person's user id: what every entry records as "by",
        and what a confirmation is compared with."""
        return _text(self._user().getId())

    def _fullname(self):
        from senaite.pfas.browser.perms import signed_in_name
        return _text(signed_in_name(self.context)) or self._who()

    def _kind(self):
        from senaite.pfas.browser.data_review import _actor_kind
        return _actor_kind(self._user())

    def _can_record(self):
        """The extraction page's own roles: Bench, Analyst, Lab Manager."""
        from senaite.pfas.browser.extraction_batch_view import EDIT_ROLES
        from senaite.pfas.browser.perms import has_role_at_portal
        return has_role_at_portal(self.context, EDIT_ROLES)

    def _is_manager(self):
        from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
        return has_role_at_portal(self.context, MANAGER_ROLES)

    def _is_analyst(self):
        from senaite.pfas.browser.perms import ANALYST_ROLES, has_role_at_portal
        return has_role_at_portal(self.context, ANALYST_ROLES)

    def _portal(self):
        from bika.lims import api
        return api.get_portal()

    # ── the stores ──────────────────────────────────────────────────────

    def _checklist(self, ws):
        from senaite.pfas import annotation_store
        from senaite.pfas.study_runs import CHECKLIST_KEY
        return annotation_store.read_json(ws, CHECKLIST_KEY, {})

    def _save_checklist(self, ws, checklist):
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas.study_runs import CHECKLIST_KEY
        IAnnotations(ws)[CHECKLIST_KEY] = json.dumps(checklist)

    def _before(self, ws, member):
        """What the stored run judged for the member's injection (its name
        in force, then the name issued), or None."""
        import sqlite3
        from senaite.pfas.provenance_store import DEFAULT_DB_PATH
        if member is None or not os.path.exists(DEFAULT_DB_PATH):
            return None
        names = [member.get("injection")] + list(member.get("aliases") or [])
        conn = sqlite3.connect(DEFAULT_DB_PATH)
        try:
            return before_snapshot(conn, ws.getId(), names)
        except sqlite3.Error as exc:
            logger.warning("before values of %s unread: %s", member.get("id"), exc)
            return None
        finally:
            conn.close()

    def _requeue_args(self, ws):
        from senaite.pfas import annotation_store
        from senaite.pfas.browser.run_builder import RUN_FILES_KEY, RUN_MANIFEST_KEY, UPLOAD_DIR
        manifest = annotation_store.read_json(ws, RUN_MANIFEST_KEY, {})
        stem = (manifest.get("raw_expectation") or {}).get("stem") or ""
        return UPLOAD_DIR, stem, annotation_store.read_json(ws, RUN_FILES_KEY, [])

    def _commit(self, ws, state, entry, action, reset_for=None):
        """Store an entry a person made: on a released record only once a
        Lab Manager has signed it as the record's next revision (refused,
        nothing written, when not signed); otherwise with the sign-offs it
        judges again cleared and kept on it, and the run queued again once
        the save commits. Logged on the worksheet's trail."""
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas import after_commit, records
        from senaite.pfas import injection_identity as ii
        released = Facts(ws, self.request).review_state() in ea.RELEASED_STATES
        if released:
            from senaite.pfas import batch_record as br
            from senaite.pfas.browser.batch_records import PFASBatchRecordsView
            from senaite.pfas.esig import ledger, signing
            signer = getattr(br, "sign_corrected", None)
            if signer is None:
                return self._refuse(NO_SIGNER)
            if self.request.form.get("sign") != "1":
                return self._refuse(NO_SIGN)
            try:
                # the record as it reads with this amendment: what the
                # revision's signature binds; nothing is written before it
                record = PFASBatchRecordsView(ws, self.request).record_for(ws, amendments=state)
                signer(self._portal(), self.request, record, entry,
                       note=self.request.form.get("sign_note") or "")
            except (signing.SignatureRefused, ledger.LedgerError) as exc:
                return self._refuse(signing.reason(exc))
        else:
            checklist, cleared = ea.reset_signoffs(self._checklist(ws), reset_for or entry)
            if cleared:
                entry["cleared"] = cleared
                self._save_checklist(ws, checklist)
        IAnnotations(ws)[ea.KEY] = ea.dump(state)
        if not released:
            upload_dir, stem, files = self._requeue_args(ws)
            # the worker reads the record in force only once it is committed
            after_commit.run_once("extraction-requeue:" + ws.getId(), ii.requeue, upload_dir, stem, files)
        records.log(ws, action, reason=entry.get("reason") or "",
                    detail=dict((k, entry.get(k)) for k in ("id", "member", "sample", "field", "from", "to",
                                                            "reverts", "members", "what", "scope")
                                if entry.get(k) not in (None, "", [])))
        done = "amend_released" if released and action == ea.AMEND else action
        return self._back(ok=DONE.get(done, DONE[ea.AMEND]))

    # ── amend ───────────────────────────────────────────────────────────

    def _handle_amend(self):
        """One fact of a finalised member, or a sample's amount or final
        volume, amended to a value the method offers."""
        ws, f = self.context, self.request.form
        facts = Facts(ws, self.request)
        who, when, ws_state, kind = self._who(), _now(), facts.review_state(), self._kind()
        target, field = _text(f.get("member")), _text(f.get("field"))
        if target.startswith("sample:") or field in ea.SAMPLE_FIELDS:
            problem, state, entry = ea.amend_sample(
                facts.state(), facts.rows(), target[len("sample:"):] if target.startswith("sample:") else target,
                field, f.get("to"), f.get("reason"), who, when, ws_state, self._can_record(), kind,
                facts.finalised(), is_manager=self._is_manager(), name=self._fullname())
        else:
            member = facts.member(target)
            problem, state, entry = ea.amend(
                facts.state(), facts.members(), target, field, f.get("to"), f.get("reason"),
                who, when, ws_state, self._can_record(), kind, facts.finalised(),
                facts.offered(field, member), is_manager=self._is_manager(),
                level_amounts=facts.level_amounts(member), before=self._before(ws, member),
                name=self._fullname())
        if problem:
            return self._refuse(problem)
        return self._commit(ws, state, entry, ea.AMEND)

    def _handle_revert(self):
        """An amendment undone, with a reason, before it is confirmed."""
        ws, f = self.context, self.request.form
        facts = Facts(ws, self.request)
        state = facts.state()
        target = dict((e.get("id"), e) for e in state["log"]).get(_text(f.get("entry")))
        problem, state, entry = ea.revert(
            state, f.get("entry"), f.get("reason"), self._who(), _now(), facts.review_state(),
            self._can_record(), self._kind(), is_manager=self._is_manager())
        if problem:
            return self._refuse(problem)
        return self._commit(ws, state, entry, ea.REVERT, reset_for=target)

    # ── confirm ─────────────────────────────────────────────────────────

    def _handle_confirm(self):
        """The verifier confirms one correction: a Lab Manager with the
        reviewer sign right, never the person who made it, once the
        worksheet is submitted (a whole batch re-extracted: while open)."""
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas import records
        from senaite.pfas.browser import manual_integration_view as miv
        ws = self.context
        who = self._who()
        try:
            info = miv.staff_sign_info(who)
        except ValueError as exc:
            return self._refuse("%s" % exc)
        facts = Facts(ws, self.request)
        problem, state, entry = ea.confirm(
            facts.state(), self.request.form.get("entry"), who, _now(), facts.review_state(),
            self._is_manager(), self._kind(), info["sign_as"], info["name"])
        if problem:
            return self._refuse(problem)
        IAnnotations(ws)[ea.KEY] = ea.dump(state)
        records.log(ws, "confirm_extraction_correction", detail={"confirms": entry["confirms"]})
        return self._back(ok=DONE[ea.CONFIRM])

    # ── send back ───────────────────────────────────────────────────────

    def _handle_send_back(self):
        """The batch returned to an earlier step: an Analyst or a Lab
        Manager while open, a Lab Manager once submitted. The members or a
        stage reopen the extraction; the run build or the import mark the
        run so release waits. Every sign-off is cleared. From submitted the
        results awaiting verification are retracted; SENAITE's retests
        return the worksheet to open."""
        import transaction
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas import annotation_store, records
        from senaite.pfas import send_back as sb
        from senaite.pfas.browser.extraction_guide import _save_session
        from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
        ws, f = self.context, self.request.form
        facts = Facts(ws, self.request)
        who, when, ws_state = self._who(), _now(), facts.review_state()
        problem, state, entry = ea.send_back(
            facts.state(), f.get("to"), f.get("stage"), f.get("reason"), who, when, ws_state,
            self._is_analyst() or self._is_manager(), self._kind(), self._is_manager(),
            finalised=facts.finalised())
        if problem:
            return self._refuse(problem)
        try:
            manifest, session = sb.by_person(annotation_store.read_json(ws, RUN_MANIFEST_KEY, {}),
                                             facts.session(), entry["to"], entry["stage"],
                                             entry["reason"], who, when)
        except ValueError as exc:
            return self._refuse("%s Nothing was saved." % exc)
        if ws_state == ea.SUBMITTED:
            # core's worksheet retract, as Verify's send back uses: every
            # result awaiting verification retracted, its retest on the same
            # worksheet, the worksheet open again
            from bika.lims import api
            from bika.lims.workflow import doActionFor
            awaiting = [a for a in (ws.getAnalyses() or []) if api.get_review_status(a) == AWAITING]
            try:
                # Send back is the one route that reopens a submitted
                # worksheet: the reopen guard lets it through only here
                from senaite.pfas import reopen_guard
                with reopen_guard.allowing(self.request):
                    doActionFor(ws, "retract")
            except Exception as exc:                        # noqa: BLE001
                # a send back half made is none: nothing is kept
                transaction.abort()
                logger.error("send back of %s: %s", ws.getId(), exc)
                return self._refuse(NOT_WRITTEN.format(exc))
            if api.get_review_status(ws) != "open":
                transaction.abort()
                return self._refuse(NOT_WRITTEN.format("SENAITE did not reopen the worksheet"))
            entry["retracted"] = len(awaiting)
        checklist, cleared = ea.reset_all(self._checklist(ws))
        if cleared:
            entry["cleared"] = cleared
            self._save_checklist(ws, checklist)
        _save_session(ws, session)
        IAnnotations(ws)[RUN_MANIFEST_KEY] = json.dumps(manifest)
        IAnnotations(ws)[ea.KEY] = ea.dump(state)
        records.log(ws, ea.SEND_BACK, reason=entry["reason"],
                    detail={"id": entry["id"], "to": entry["to"], "stage": entry["stage"],
                            "from_state": ws_state, "cleared": [c["item"] for c in cleared],
                            "retracted": entry.get("retracted", 0)})
        if ws_state == ea.SUBMITTED or entry["to"] == "import":
            # the run files the retests, or is imported again, once this commits
            from senaite.pfas import after_commit
            from senaite.pfas import injection_identity as ii
            upload_dir, stem, files = self._requeue_args(ws)
            after_commit.run_once("ea-send-back-requeue:" + ws.getId(), ii.requeue, upload_dir, stem, files)
        return self._back(ok=DONE[ea.SEND_BACK])

    # ── re-extract ──────────────────────────────────────────────────────

    def _handle_reextract(self):
        """Members withheld for re-extraction: nothing they gave is filed
        or reported, and their samples' analyses leave the worksheet for
        the next extraction batch (unassigned while open; retracted with
        the retest taken off once submitted). Not undone."""
        import transaction
        from bika.lims import api
        from bika.lims.workflow import doActionFor
        from zope.annotation.interfaces import IAnnotations
        from senaite.pfas import annotation_store
        ws, f = self.context, self.request.form
        facts = Facts(ws, self.request)
        problem, state, entry = ea.reextract(
            facts.state(), facts.members(), f.get("member"), f.get("what"), f.get("scope"),
            f.get("sample_left") in ("1", "on", "true"), f.get("reason"), self._who(), _now(),
            facts.review_state(), self._can_record(), self._kind(), facts.finalised(),
            is_manager=self._is_manager())
        if problem:
            return self._refuse(problem)
        held = set(entry.get("members") or ())
        uids = [m.get("sample_uid") for m in facts.in_force()
                if m.get("id") in held and m.get("role") == "Sample" and m.get("sample_uid")]
        try:
            # a submitted worksheet's results are retracted on purpose here,
            # so the reopen guard lets them through
            from senaite.pfas import reopen_guard
            with reopen_guard.allowing(self.request):
                release_analyses(ws, uids, lambda o, t: doActionFor(o, t)[0], api.get_review_status,
                                 clear=clear_result)
        except Exception as exc:                            # noqa: BLE001
            transaction.abort()
            logger.error("re-extraction on %s: %s", ws.getId(), exc)
            return self._refuse(NOT_WRITTEN.format(exc))
        portal = self._portal()
        registry = registry_add(annotation_store.read_json(portal, REGISTRY_KEY, {}), entry,
                                ws.getId(), ws.UID(), uids)
        IAnnotations(portal)[REGISTRY_KEY] = json.dumps(registry, sort_keys=True)
        return self._commit(ws, state, entry, ea.REEXTRACT)
