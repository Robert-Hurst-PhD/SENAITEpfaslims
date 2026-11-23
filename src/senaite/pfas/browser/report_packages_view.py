# -*- coding: utf-8 -*-
"""What the package worker reads to build a report's package
(@@pfas-package-source; report_packages holds the record and the jobs).

    ?job=<report uid>
        JSON {"ok": true, "state", "samples": [uid],
              "worksheet_verified": {sample uid: bool},
              "jobs": {sample uid: job}, "sample_names",
              "translation": [{"sample_id", "client_sample_id"}]}: the
        preconditions the worker checks before it fetches a part, and the
        package's translation page: the report's own samples of its
        client, each lab sample ID beside the client's own sample name
    ?job=<report uid>&sample=<sample uid>&part=<n>
        the PDF of part n of that sample's job; a part that cannot be
        produced, or whose design was reissued since the job was queued,
        answers HTTP 409 {"ok": false, "error": "<part label>: <reason>"}

An unknown report, sample or part answers 404 {"ok": false, "error"}. A
part is produced from its issued design or not at all: there is no other
layout to fall back on. Nothing is written.

@@pfas-package-done, POST multipart from the worker: job (the report uid),
state (ready | failed), pdf, sha256, pages, revisions (a JSON object),
worker, trace_key (the chromatogram pages' cache key, "" when none),
cert_fp (the fingerprint of the certificate the package was sealed with),
reason. A ready package is stored on the report (its Pdf) only while the
record is pending, only when the bytes received hash to the sha256 sent,
and only sealed (cert_fp named); a failed one keeps its reason. 200 {"ok": true}; 409 for a
wrong hash or a record no longer pending, 400 for a post it cannot read,
404 for an unknown report; nothing is written on a refusal. A report
already issued answers 409 ISSUED to any hand-back, and its record, when
still pending, fails with that reason.

@@pfas-seal-source?report=<uid>, GET from the worker: the stored PDF of a
certificate with no package whose seal is pending (report_packages
queue_seal), to be sealed; anything else answers 404 or 409 {"ok": false,
"error"}.

@@pfas-seal-done, POST multipart from the worker: report, state (sealed |
failed), pdf, sha256, cert_fp, reason. A sealed certificate replaces the
stored PDF only while its seal is pending, only with the bytes its hash
names, and only as an incremental update of the stored PDF; a failed one
keeps its reason. A report already issued refuses either, and a pending
seal of it fails with ISSUED.

@@pfas-package-retry, POST job from a Manager's form: a failed package, or
a pending one whose job files are neither queued nor being built, of a
report not yet issued, is queued again with every job file rewritten
after the commit, then back to Controlled Publications with ?retried=1; a
retry refused goes back there with the reason as a status message. A
certificate with no package whose seal failed, or is pending with its
job file lost, has its seal queued again the same way.

Only a caller who may manage the site (senaite.core: Manage Bika on the
portal) is answered, by any of the three; a retry asks besides for the
LabManager or Manager role at the portal, since core grants Manage Bika to
the LabClerk too. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import hashlib
import io
import json
import logging
import os

from AccessControl import getSecurityManager
from plone.protect import CheckAuthenticator
from Products.Five.browser import BrowserView
from zExceptions import Forbidden
from ZODB.POSException import ConflictError

from senaite.pfas import report_packages as rp
from senaite.pfas import report_tiers
from senaite.pfas.browser.coa_storage import DesignedCertificateError
from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal, refuse
from senaite.pfas.browser.report_designs import DesignedReportError

logger = logging.getLogger("senaite.pfas.browser.report_packages_view")

# the worker draws these parts itself; the view has nothing to serve for them
GENERATED = ("contents", "chromatograms")
NO_QC_DESIGN = u"No issued design for the QC Review report: issue one in Reporting Setup"
NO_INSTRUMENT_REPORT = u"No instrument report uploaded on Data Review"
SEVERAL_INSTRUMENT_REPORTS = (u"Several instrument reports are uploaded and none is the one under "
                              u"review: choose it on Data Review")
REISSUED = u"The %s design was reissued (revision %s, the job expected %s): retry the certificate"
# the worker's hand-back
HASH_MISMATCH = u"Hash does not match"
NOT_PENDING = u"Not pending"
BAD_STATE = u"State must be ready or failed"
NO_PDF = u"No PDF received"
BAD_PAGES = u"Pages must be a whole number greater than 0"
REPEATED = u"Sent more than once: %s"
# the fields of the hand-back, each sent once
FORM_FIELDS = ("job", "state", "pdf", "sha256", "pages", "revisions", "worker", "trace_key", "reason", "cert_fp")
# a package is taken sealed or not at all
NO_SEAL = u"No seal certificate named: the worker seals every PDF"
# the worker's seal of a certificate with no package
SEAL_FORM_FIELDS = ("report", "state", "pdf", "sha256", "cert_fp", "reason")
BAD_SEAL_STATE = u"State must be sealed or failed"
NOT_THE_STORED = u"The sealed PDF is not the stored certificate"
HAS_PACKAGE = u"The report has a package"
NO_SEAL_RECORD = u"The report has no seal"
BAD_REVISIONS = u"Revisions is not a JSON object"
NO_REASON = u"The worker gave no reason"
# a Manager's retry
NOT_FAILED = u"Not failed"
STILL_QUEUED = u"Still queued"
NOTHING_TO_QUEUE = u"No job to queue: store the certificate again"
QUEUE_UNREADABLE = u"The worker's queue cannot be read: %s"
ISSUED = u"Issued reports are never rebuilt: generate the certificate again"
# a Manager's delete of a certificate not yet issued
ISSUED_KEPT = u"An issued certificate is never deleted"
NOT_A_CERTIFICATE = u"Only a certificate not yet issued is deleted here"
STILL_BUILDING_DELETE = u"The certificate is still building: delete it once it is ready or has failed"


class PartError(Exception):
    """A part cannot be produced; the message is the reason."""


# a part refused for a reason it states: answered without a traceback
EXPECTED = (PartError, DesignedReportError, DesignedCertificateError)


def part_sections(key):
    """The QC Review sections a part prints (report_tiers.PARTS)."""
    for k, _label, secs in report_tiers.PARTS:
        if k == key:
            return tuple(secs)
    return ()


def error_text(exc):
    """An exception's message as text: a certificate error keeps UTF-8 bytes
    under Python 2; an error with several arguments ("[Errno 2] No such
    file") reads as it prints."""
    args = exc.args
    if len(args) == 1 and isinstance(args[0], bytes):
        msg = args[0].decode("utf-8", "replace")
    else:
        try:
            msg = u"%s" % (exc,)
        except UnicodeError:
            msg = u"%r" % (args,)
    return msg or u"%s" % type(exc).__name__


def reissued(title, rev, expected):
    """The refusal when a design was reissued after the job was queued: the
    package prints from the revisions the job names, or not at all."""
    if rev == expected:
        return None
    return REISSUED % (title, rev, expected if expected is not None else u"none")


def expected_revision(job, kind):
    """The design revision a job was queued with for a kind; a job queued
    before a kind's rename names it under the old key (report_tiers.part_key)."""
    revs = job.get("design_revisions") or {}
    if kind in revs:
        return revs[kind]
    for key in sorted(revs):
        if report_tiers.part_key(key) == kind:
            return revs[key]
    return None


def worksheet_state_verified(state):
    """A worksheet whose review is done: its traces are the reviewed ones."""
    return state in ("verified", "published")


def summary(rec, verified, names=None, translation=None):
    """The preconditions the worker checks, `names`, {sample uid:
    {client sample id: lab sample id}} of each sample's run, read now: what
    its chromatogram pages name each injection by, and `translation`, the
    package's translation page (translation_rows)."""
    return {"ok": True, "state": rec.get("state"), "samples": list(rec.get("samples") or []),
            "worksheet_verified": verified, "jobs": rec.get("jobs") or {}, "sample_names": names or {},
            "translation": list(translation or [])}


def translation_rows(samples, client_uid):
    """The translation page's rows: [{"sample_id", "client_sample_id"}] of
    the report's own samples, in order, from [(lab sample id, client sample
    id, client uid)]. A package names every sample by the lab sample ID;
    this page gives the client their own names for them. Only samples of
    `client_uid`, the client the report goes to: another client's sample,
    or one whose client cannot be read, is never listed."""
    out = []
    for lab_id, client_sid, uid in samples or []:
        if client_uid and uid == client_uid:
            out.append({"sample_id": lab_id or u"", "client_sample_id": (client_sid or u"").strip()})
    return out


def pick_part(rec, sample_uid, n):
    """(job, part, None) for part `n` of the sample's job, else
    (job or None, None, reason)."""
    if not sample_uid:
        return None, None, u"No sample given"
    job = (rec.get("jobs") or {}).get(sample_uid)
    if not job:
        return None, None, u"No job for sample %s on this report" % sample_uid
    try:
        i = int(n)
    except (TypeError, ValueError):
        return job, None, u"Part %s is not a number" % (n,)
    parts = job.get("parts") or []
    if i < 0 or i >= len(parts):
        return job, None, u"No part %s for sample %s" % (n, sample_uid)
    return job, parts[i], None


def stamped_report(state, stamped_dir, fp_of, signed):
    """The stamped copy of the instrument report, when it stands for the
    report under review: a file of `stamped_dir` that is on disk, unaltered
    (`fp_of(path)` is the fingerprint kept with it) and stamped of the
    records and the report as they are now (`signed`, their signed
    fingerprint). None otherwise: the package then carries the original."""
    found = (state or {}).get("stamped") or {}
    name = found.get("file") or u""
    if not name or os.path.basename(name) != name:
        return None
    path = os.path.join(stamped_dir, name)
    if not os.path.isfile(path):
        return None
    if found.get("of") != signed or fp_of(path) != found.get("fp"):
        return None
    return path


def job_worksheet(job, by_uid):
    """The worksheet a job names, looked up by `by_uid`; PartError when the
    job names none or it is gone."""
    uid = job.get("worksheet_uid") or u""
    if not uid:
        raise PartError(u"Sample %s is on no worksheet" % (job.get("sample_id") or job.get("sample_uid")))
    ws = by_uid(uid)
    if ws is None:
        raise PartError(u"Worksheet %s is not found" % (job.get("worksheet_id") or uid))
    return ws


class _JSONView(BrowserView):
    """A view the worker reads: it answers JSON."""

    def _json(self, body, status=200):
        resp = self.request.response
        resp.setHeader("Content-Type", "application/json")
        if status != 200:
            resp.setStatus(status)
        return json.dumps(body)


class PFASPackageSourceView(_JSONView):
    """The package worker's source: the report's preconditions and its
    parts, one request each."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        self.request.response.setHeader("Content-Type", "application/json")
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request, json.dumps({"ok": False, "error": u"not allowed"}))
        form = self.request.form
        report = api.get_object_by_uid(form.get("job") or u"", default=None)
        if report is None or api.get_portal_type(report) != "ARReport":
            return self._json({"ok": False, "error": u"No such report"}, 404)
        from senaite.pfas.report_packages import record
        rec = record(report)
        if rec is None:
            return self._json({"ok": False, "error": u"The report has no package"}, 404)
        self.report = report
        if form.get("part") is None:
            return self._summary(rec)
        return self._part(rec, form.get("sample") or u"", form.get("part"))

    def _summary(self, rec):
        """Whether each sample's run is verified: the worksheet its job was
        queued from, the one its parts are drawn from."""
        from bika.lims import api
        verified, names = {}, {}
        jobs = rec.get("jobs") or {}
        for uid in rec.get("samples") or []:
            ws_uid = (jobs.get(uid) or {}).get("worksheet_uid") or u""
            ws = api.get_object_by_uid(ws_uid, default=None) if ws_uid else None
            verified[uid] = worksheet_state_verified(api.get_review_status(ws) if ws is not None else None)
            names[uid] = rp.worksheet_names(ws) if ws is not None else {}
        return self._json(summary(rec, verified, names, self._translation(rec)))

    def _translation(self, rec):
        """The translation page's rows: the report's samples of the client
        its primary sample belongs to (translation_rows)."""
        from bika.lims import api
        found = []
        for uid in rec.get("samples") or []:
            sample = api.get_object_by_uid(uid, default=None)
            if sample is None:
                continue
            found.append((api.get_id(sample), api.safe_unicode(sample.getClientSampleID() or u""),
                          sample.getClientUID()))
        return translation_rows(found, self.report.getAnalysisRequest().getClientUID())

    def _producer(self, key):
        """The producer of a part the view serves, None for any other key. A
        job queued before a part was renamed names it by its old key."""
        key = report_tiers.part_key(key)
        if key not in [k for k, _l, _s in report_tiers.PARTS]:
            return None
        if key.startswith("qc_"):
            return self.part_qc_review
        return getattr(self, "part_" + key, None)

    def _part(self, rec, sample_uid, n):
        job, part, why = pick_part(rec, sample_uid, n)
        if why:
            return self._json({"ok": False, "error": why}, 404)
        key = part.get("key")
        try:
            if key in GENERATED:
                raise PartError(u"generated by the worker")
            producer = self._producer(key)
            if producer is None:
                raise PartError(u"no part of this name can be produced")
            data, content_type = producer(job, part)
        except ConflictError:
            raise                                           # Zope retries the request
        except Exception as exc:                            # noqa: BLE001
            if not isinstance(exc, EXPECTED):
                logger.exception("package part %s failed for %s", key, sample_uid)
            reason = u"%s: %s" % (part.get("label") or part.get("key"), error_text(exc))
            return self._json({"ok": False, "error": reason}, 409)
        self.request.response.setHeader("Content-Type", content_type)
        return data

    def _worksheet(self, job):
        """The run the job was queued from (its frozen worksheet_uid), so
        every part of a package comes from the one run, whatever the
        sample's analyses moved to since."""
        from bika.lims import api
        return job_worksheet(job, lambda uid: api.get_object_by_uid(uid, default=None))

    def _names(self, job):
        """{client sample id: lab sample id} of the job's run: a package's
        parts name every sample by the lab sample id."""
        return rp.worksheet_names(self._worksheet(job))

    # ── the producers: (self, job, part) -> (bytes, content type) ──────────

    def part_certificate(self, job, part):
        pdf = self.report.getPdf()
        data = getattr(pdf, "data", None) if pdf else None
        if not data:
            raise PartError(u"The stored certificate has no PDF")
        return data, "application/pdf"

    def part_qc_review(self, job, part):
        from senaite.pfas.browser.coa_storage import designed_qc_review
        secs = list(part_sections(part.get("key")))
        pdf, rev = designed_qc_review([job["sample_uid"]], self.request, sections=secs, names=self._names(job),
                                      mono=bool(job.get("mono")))
        if pdf is None:
            raise PartError(NO_QC_DESIGN)
        why = reissued(u"QC Review Report", rev, (job.get("design_revisions") or {}).get("qc_review"))
        if why:
            raise PartError(why)
        return pdf, "application/pdf"

    def part_batch_record(self, job, part):
        from senaite.pfas.browser.extraction_pdf import batch_record_pdf_bytes
        pdf, rev = batch_record_pdf_bytes(self._worksheet(job), self.request, names=self._names(job),
                                          mono=bool(job.get("mono")))
        why = reissued(u"Batch record", rev, expected_revision(job, "batch_record"))
        if why:
            raise PartError(why)
        return pdf, "application/pdf"

    def part_instrument_report(self, job, part):
        from senaite.pfas import manual_integration as mi
        from senaite.pfas.browser import manual_integration_view as miv
        ws = self._worksheet(job)
        if not miv.report_files(ws):
            raise PartError(NO_INSTRUMENT_REPORT)
        state = miv.load_state(ws)
        # the stamped copy where one stands for the report under review;
        # else the report Data Review reviews: the pinned file, else the one
        # its records refer to, else the only one; never the newest by
        # default, and only an uploaded PDF
        path = (stamped_report(state, os.path.join(miv._report_dir(ws), miv.STAMPED_DIR), miv.file_fp,
                               mi.signed_fingerprint(state))
                or miv.resolve_report(ws, state))
        if path is None:
            raise PartError(SEVERAL_INSTRUMENT_REPORTS)
        with io.open(path, "rb") as fh:
            return fh.read(), "application/pdf"


# ── the worker's hand-back and a Manager's retry ─────────────────────────────

def _text(value):
    """A form value as text: Zope hands Python 2 views UTF-8 bytes."""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return value or u""


def repeated(form, fields=FORM_FIELDS):
    """The refusal for a hand-back field sent more than once, else None."""
    for key in fields:
        if isinstance(form.get(key), (list, tuple)):
            return REPEATED % key
    return None


def done_outcome(rec, form, data, at, issued):
    """(HTTP status, JSON body, the record to store or None) for the worker's
    hand-back of `rec`. A package is stored only from pending and only with
    the bytes its hash names; a refusal names no record, so nothing is
    written, except that a report already issued (`issued`, in the
    register) refuses any hand-back and a pending record of it fails with
    ISSUED: its PDF is the one sent and never changes."""
    why = repeated(form)
    if why:
        return 400, {"ok": False, "error": why}, None
    if issued:
        failed = rp.fail(rec, ISSUED, at) if rec.get("state") == "pending" else None
        return 409, {"ok": False, "error": ISSUED}, failed
    state = form.get("state")
    if state not in ("ready", "failed"):
        return 400, {"ok": False, "error": BAD_STATE}, None
    if rec.get("state") != "pending":
        return 409, {"ok": False, "error": NOT_PENDING}, None
    if state == "failed":
        reason = _text(form.get("reason")).strip() or NO_REASON
        return 200, {"ok": True}, rp.fail(rec, reason, at)
    if not data:
        return 400, {"ok": False, "error": NO_PDF}, None
    digest = hashlib.sha256(data).hexdigest()
    if digest != _text(form.get("sha256")).strip().lower():
        return 409, {"ok": False, "error": HASH_MISMATCH}, None
    cert_fp = _text(form.get("cert_fp")).strip().lower()
    if not cert_fp:
        return 400, {"ok": False, "error": NO_SEAL}, None
    try:
        pages = int(form.get("pages"))
    except (TypeError, ValueError):
        return 400, {"ok": False, "error": BAD_PAGES}, None
    if pages < 1:
        return 400, {"ok": False, "error": BAD_PAGES}, None
    try:
        revisions = json.loads(form.get("revisions") or u"")
    except (TypeError, ValueError):
        revisions = None
    if not isinstance(revisions, dict):
        return 400, {"ok": False, "error": BAD_REVISIONS}, None
    return 200, {"ok": True}, rp.complete(rec, pages, digest, at, revisions,
                                          _text(form.get("worker")), _text(form.get("trace_key")).strip(),
                                          cert_fp)


def seal_source_refusal(seal, issued):
    """None when the worker may fetch the certificate to seal: its seal is
    pending and the report not issued (`issued`). Else the reason."""
    if not seal:
        return NO_SEAL_RECORD
    if issued:
        return ISSUED
    if seal.get("state") != "pending":
        return NOT_PENDING
    return None


def seal_done_outcome(seal, form, data, stored, at, issued):
    """(HTTP status, JSON body, the seal record to store or None) for the
    worker's hand-back of a certificate's seal. The sealed PDF replaces
    the stored one only from pending, only with the bytes its hash names,
    only with the seal's certificate named, and only as an incremental
    update of the stored PDF (`stored`): every byte of it, then the seal.
    A report already issued (`issued`) refuses any hand-back, and a
    pending seal of it fails with ISSUED."""
    why = repeated(form, SEAL_FORM_FIELDS)
    if why:
        return 400, {"ok": False, "error": why}, None
    if issued:
        failed = rp.seal_failed(seal, ISSUED, at) if seal.get("state") == "pending" else None
        return 409, {"ok": False, "error": ISSUED}, failed
    state = form.get("state")
    if state not in ("sealed", "failed"):
        return 400, {"ok": False, "error": BAD_SEAL_STATE}, None
    if seal.get("state") != "pending":
        return 409, {"ok": False, "error": NOT_PENDING}, None
    if state == "failed":
        reason = _text(form.get("reason")).strip() or NO_REASON
        return 200, {"ok": True}, rp.seal_failed(seal, reason, at)
    if not data:
        return 400, {"ok": False, "error": NO_PDF}, None
    cert_fp = _text(form.get("cert_fp")).strip().lower()
    if not cert_fp:
        return 400, {"ok": False, "error": NO_SEAL}, None
    digest = hashlib.sha256(data).hexdigest()
    if digest != _text(form.get("sha256")).strip().lower():
        return 409, {"ok": False, "error": HASH_MISMATCH}, None
    if not stored or len(data) <= len(stored) or not data.startswith(stored):
        return 409, {"ok": False, "error": NOT_THE_STORED}, None
    return 200, {"ok": True}, rp.seal_sealed(seal, digest, cert_fp, at)


def seal_retry_refusal(seal, queued, report_uid, issued):
    """None when a certificate's seal may be queued again: it failed, or it
    is pending with its job file not in the seal queue (`queued`,
    rp.seal_queued_names), so the write after its commit was lost. Else
    the reason. An issued report is never resealed; a seal with no job
    kept has nothing to queue."""
    if issued:
        return ISSUED
    if not seal.get("job"):
        return NOTHING_TO_QUEUE
    state = seal.get("state")
    if state == "pending":
        if rp.seal_job_name(report_uid) in queued:
            return STILL_QUEUED
        return None
    if state != "failed":
        return NOT_FAILED
    return None


def retry_refusal(rec, queued, report_uid, issued):
    """None when the package may be queued again: it failed, or it is
    pending with none of its job files queued or being built (`queued`,
    rp.queued_names), so the write after its commit was lost. Else the reason.
    A report already issued (`issued`, in the register) is never rebuilt:
    its PDF is the one sent. A package with no job has nothing to queue."""
    if issued:
        return ISSUED
    state = rec.get("state")
    if state == "pending":
        prefix = u"%s-" % report_uid
        if [n for n in queued if n.startswith(prefix)]:
            return STILL_QUEUED
    elif state != "failed":
        return NOT_FAILED
    if not rec.get("jobs"):
        return NOTHING_TO_QUEUE
    return None


def delete_refusal(certificate, issued, rec, seal, queued, seal_queued, report_uid=u""):
    """None when a Manager may delete the stored report: a certificate
    (`certificate`) the register does not name (`issued`) whose package or
    seal the worker is not making now: a pending package with a job file
    queued or being built (`queued`, rp.queued_names), or a pending seal
    with its job file queued (`seal_queued`, rp.seal_queued_names). Else
    the reason."""
    if issued:
        return ISSUED_KEPT
    if not certificate:
        return NOT_A_CERTIFICATE
    if rec is not None:
        prefix = u"%s-" % report_uid
        if rec.get("state") == "pending" and [n for n in queued if n.startswith(prefix)]:
            return STILL_BUILDING_DELETE
    elif (seal or {}).get("state") == "pending" and rp.seal_job_name(report_uid) in seal_queued:
        return STILL_BUILDING_DELETE
    return None


def _received(upload):
    """The bytes of a multipart file field, b"" when none was sent."""
    if upload is None:
        return b""
    if hasattr(upload, "read"):
        return upload.read() or b""
    return upload if isinstance(upload, bytes) else b""


def pdf_filename(report):
    """The name the stored certificate's PDF already has (its e-mail
    attachment name), else the report's id."""
    old = report.getPdf()
    getter = getattr(old, "getFilename", None)
    name = getter() if getter is not None else getattr(old, "filename", None)
    return name or u"%s.pdf" % report.getId()


def store_pdf(report, data):
    """The package replaces the report's PDF through its blob field, which
    keeps the file's name and type."""
    report.getField("Pdf").set(report, data, filename=pdf_filename(report), mimetype="application/pdf")


def _stored(report):
    """The stored certificate's bytes, b"" when there are none."""
    pdf = report.getPdf()
    return (getattr(pdf, "data", None) if pdf else None) or b""


def store_outcome(report, new_rec, data):
    """Write what the hand-back decided: the package's PDF only for a ready
    record, so a failure leaves the stored certificate as it is; then the
    record."""
    if new_rec["state"] == "ready":
        store_pdf(report, data)
    rp.set_record(report, new_rec)


def _report(report_uid):
    from bika.lims import api
    report = api.get_object_by_uid(report_uid or u"", default=None)
    if report is None or api.get_portal_type(report) != "ARReport":
        return None
    return report


class PFASPackageDoneView(_JSONView):
    """The worker hands a report's package back: built, or failed with the
    reason."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        from senaite.pfas.browser.perms import disable_csrf
        self.request.response.setHeader("Content-Type", "application/json")
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request, json.dumps({"ok": False, "error": u"not allowed"}))
        if self.request.method != "POST":
            return self._json({"ok": False, "error": u"POST only"}, 405)
        # the worker's post carries no form token; the gate above has run
        disable_csrf(self.request)
        form = self.request.form
        why = repeated(form)
        if why:
            return self._json({"ok": False, "error": why}, 400)
        report = _report(form.get("job"))
        if report is None:
            return self._json({"ok": False, "error": u"No such report"}, 404)
        rec = rp.record(report)
        if rec is None:
            return self._json({"ok": False, "error": u"The report has no package"}, 404)
        from senaite.pfas.browser.controlled_publications import report_issued
        data = _received(form.get("pdf")) if form.get("state") == "ready" else b""
        status, body, new_rec = done_outcome(rec, form, data, rp.stamp(), report_issued(report))
        if new_rec is not None:
            store_outcome(report, new_rec, data)
        return self._json(body, status)


class PFASSealSourceView(_JSONView):
    """The worker fetches a certificate stored with no package, to seal it."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        self.request.response.setHeader("Content-Type", "application/json")
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request, json.dumps({"ok": False, "error": u"not allowed"}))
        if self.request.method != "GET":
            return self._json({"ok": False, "error": u"GET only"}, 405)
        report = _report(self.request.form.get("report"))
        if report is None:
            return self._json({"ok": False, "error": u"No such report"}, 404)
        if rp.record(report) is not None:
            # a package is sealed by its own build
            return self._json({"ok": False, "error": HAS_PACKAGE}, 404)
        from senaite.pfas.browser.controlled_publications import report_issued
        why = seal_source_refusal(rp.seal_record(report), report_issued(report))
        if why:
            return self._json({"ok": False, "error": why}, 409)
        pdf = report.getPdf()
        data = getattr(pdf, "data", None) if pdf else None
        if not data:
            return self._json({"ok": False, "error": u"The stored certificate has no PDF"}, 409)
        self.request.response.setHeader("Content-Type", "application/pdf")
        return data


class PFASSealDoneView(_JSONView):
    """The worker hands a certificate's seal back: sealed, or failed with the
    reason."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        from senaite.pfas.browser.perms import disable_csrf
        self.request.response.setHeader("Content-Type", "application/json")
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request, json.dumps({"ok": False, "error": u"not allowed"}))
        if self.request.method != "POST":
            return self._json({"ok": False, "error": u"POST only"}, 405)
        # the worker's post carries no form token; the gate above has run
        disable_csrf(self.request)
        form = self.request.form
        why = repeated(form, SEAL_FORM_FIELDS)
        if why:
            return self._json({"ok": False, "error": why}, 400)
        report = _report(form.get("report"))
        if report is None:
            return self._json({"ok": False, "error": u"No such report"}, 404)
        if rp.record(report) is not None:
            return self._json({"ok": False, "error": HAS_PACKAGE}, 404)
        seal = rp.seal_record(report)
        if seal is None:
            return self._json({"ok": False, "error": NO_SEAL_RECORD}, 404)
        from senaite.pfas.browser.controlled_publications import report_issued
        data = _received(form.get("pdf")) if form.get("state") == "sealed" else b""
        status, body, new_seal = seal_done_outcome(seal, form, data, _stored(report), rp.stamp(), report_issued(report))
        if new_seal is not None:
            # the sealed bytes replace the stored certificate: nothing writes it after
            if new_seal["state"] == "sealed":
                store_pdf(report, data)
            rp.set_seal_record(report, new_seal)
        return self._json(body, status)


class PFASPackageRetryView(BrowserView):
    """A Manager queues a report's package again from Controlled
    Publications."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        from senaite.pfas import after_commit
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request)
        # a Lab Manager's: core grants Manage Bika to the LabClerk too
        if not has_role_at_portal(self.context, MANAGER_ROLES):
            return refuse(self.request)
        if self.request.method != "POST":
            self.request.response.setStatus(405)
            return u"POST only"
        try:
            CheckAuthenticator(self.request)
        except Forbidden:
            return refuse(self.request)
        report = _report(self.request.form.get("job"))
        rec = rp.record(report) if report is not None else None
        if rec is None and report is not None and rp.seal_record(report) is not None:
            # a certificate with no package: its seal is what is retried
            return self._retry_seal(report)
        if rec is None:
            return self._refused(u"No package for this report")
        report_uid = api.get_uid(report)
        from senaite.pfas.browser.controlled_publications import report_issued
        issued = report_issued(report)
        names = []
        if not issued:
            try:
                names = rp.queued_names()
            except OSError as exc:
                logger.error("report package retry: %s", exc)
                return self._refused(QUEUE_UNREADABLE % error_text(exc))
        why = retry_refusal(rec, names, report_uid, issued)
        if why:
            return self._refused(why)
        at = rp.stamp()
        if rec.get("state") == "failed":
            rec = rp.retry(rec, at)
        # a pending package whose job files were lost is queued from now too
        rec = rp.requeue(rec, rp.design_revisions(api.get_portal()), at)
        rp.set_record(report, rec)
        for uid in sorted(rec.get("jobs") or {}):
            # one key per job file, the keys the certificate's storage uses
            after_commit.run_once("report package %s" % rp.job_file_name(report_uid, uid),
                                  rp.write_job, rp.job_path(report_uid, uid), rec["jobs"][uid])
        self.request.response.redirect(
            "{0}/@@pfas-controlled-publications?retried=1".format(api.get_url(api.get_portal())))
        return u""

    def _retry_seal(self, report):
        """A certificate's failed seal, or a pending one whose job file was
        lost, queued again after the commit."""
        from bika.lims import api
        from senaite.pfas import after_commit
        from senaite.pfas.browser.controlled_publications import report_issued
        report_uid = api.get_uid(report)
        seal = rp.seal_record(report)
        issued = report_issued(report)
        names = []
        if not issued:
            try:
                names = rp.seal_queued_names()
            except OSError as exc:
                logger.error("certificate seal retry: %s", exc)
                return self._refused(QUEUE_UNREADABLE % error_text(exc))
        why = seal_retry_refusal(seal, names, report_uid, issued)
        if why:
            return self._refused(why)
        seal = rp.seal_requeue(seal, rp.stamp())
        rp.set_seal_record(report, seal)
        # the key the certificate's storage queued it under
        after_commit.run_once(u"certificate seal %s" % report_uid, rp.write_job,
                              rp.seal_job_path(report_uid), seal["job"])
        self.request.response.redirect(
            "{0}/@@pfas-controlled-publications?retried=1".format(api.get_url(api.get_portal())))
        return u""

    def _refused(self, why):
        """Back to Controlled Publications, which shows the reason; nothing
        was written."""
        from bika.lims import api
        from Products.statusmessages.interfaces import IStatusMessage
        IStatusMessage(self.request).add(why, type="error")
        self.request.response.redirect(
            "{0}/@@pfas-controlled-publications".format(api.get_url(api.get_portal())))
        return u""


class PFASCertificateDeleteView(PFASPackageRetryView):
    """A Manager deletes a stored certificate not yet issued from
    Controlled Publications' Awaiting issue list: a draft that holds
    publishing, its package failed or never recorded, goes, and the
    sample's next newest certificate is judged instead. An issued
    certificate is the record sent and is never deleted. A refusal goes
    back to the register as the retry's does."""

    def __call__(self):
        from bika.lims import api
        from senaite.core.permissions import ManageBika
        if not getSecurityManager().checkPermission(ManageBika, api.get_portal()):
            return refuse(self.request)
        if not has_role_at_portal(self.context, MANAGER_ROLES):
            return refuse(self.request)
        if self.request.method != "POST":
            self.request.response.setStatus(405)
            return u"POST only"
        try:
            CheckAuthenticator(self.request)
        except Forbidden:
            return refuse(self.request)
        report = _report(self.request.form.get("job"))
        if report is None:
            return self._refused(u"No such certificate")
        from senaite.pfas.browser.controlled_publications import report_issued
        report_uid = api.get_uid(report)
        issued = report_issued(report)
        queued, seal_queued = [], []
        if not issued:
            try:
                queued, seal_queued = rp.queued_names(), rp.seal_queued_names()
            except OSError as exc:
                logger.error("certificate delete: %s", exc)
                return self._refused(QUEUE_UNREADABLE % error_text(exc))
        why = delete_refusal(rp.is_certificate_report(report), issued, rp.record(report), rp.seal_record(report),
                             queued, seal_queued, report_uid)
        if why:
            return self._refused(why)
        sample = api.get_parent(report)
        name, sample_id = api.get_id(report), api.get_id(sample)
        # the stored report is the sample's content; the sample's workflow
        # keeps a published sample's contents from its users, and a draft
        # never issued is the Manager's to remove once this gate has passed
        sample._delObject(name)
        # the deletion stays on the sample's own audit trail, in the same
        # transaction, so a removed draft is never silently gone
        from senaite.pfas import records
        records.log(sample, u"certificate deleted", detail={u"certificate": name, u"issued": False})
        logger.info("certificate %s of %s, never issued, deleted by %s", name, sample_id,
                    getSecurityManager().getUser().getId())
        self.request.response.redirect(
            "{0}/@@pfas-controlled-publications?deleted=1".format(api.get_url(api.get_portal())))
        return u""
