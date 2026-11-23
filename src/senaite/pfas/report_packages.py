# -*- coding: utf-8 -*-
"""Report packages: the job the certificate's storage queues for the worker,
and the package state kept on the report.

When a certificate is stored for a sample whose report tier has parts beyond
the certificate, each sample of the report gets one job file,
QUEUE_DIR/queue/<report uid>-<sample uid>.json, written once the transaction
commits; the worker builds the report's package from all of them. The
report's annotation PACKAGE_KEY holds the package state:

    {"state": "pending" | "ready" | "failed", "tier": {"id", "name"},
     "parts": [key], "queued_at", "built_at", "failed_at", "pages", "sha256",
     "reason", "revisions", "worker", "trace_key", "samples": [uid],
     "jobs": {sample uid: job}}

The worker hands the package back to @@pfas-package-done (complete or
fail, from pending only); a Manager queues a failed package again
(retry, then requeue for its jobs). A job file waits in queue/ and sits
in building/ while the worker builds it.

The certificate's storage calls prepare before it stores (everything that
can refuse) and attach for each report it stored. The job, the record and
the file are pure (Python 2.7 and 3); prepare, attach, record and
set_record read Plone and import it when called.

The worker seals each package with the lab key as its last write and
names the seal's certificate (cert_fp) in its hand-back. A certificate
stored with no package is sealed alone: queue_seal writes
QUEUE_DIR/seal/<report uid>.json after the commit and keeps the seal
state in the report's annotation SEAL_KEY:

    {"state": "pending" | "sealed" | "failed", "sha256", "cert_fp", "at",
     "reason", "queued_at", "job"}

The worker hands it back to @@pfas-seal-done; publishing waits while it is
pending or failed (seal_refusal). A certificate stored before seals,
with neither record, is never issued (never_sealed): it is generated
again.
"""
from __future__ import absolute_import, unicode_literals

import copy
import datetime
import errno
import io
import json
import logging
import os

from senaite.pfas import report_tiers

logger = logging.getLogger("senaite.pfas.report_packages")

PACKAGE_KEY = "senaite.pfas.report_package"
SEAL_KEY = "senaite.pfas.seal"
SEAL_DIR = "seal"
SEAL_PENDING = u"Seal pending"
SEAL_FAILED = u"Seal failed: %s"
SEAL_UNREADABLE = u"The seal record cannot be read"
NOT_SEALED = u"Generate the certificate again so it is sealed"
QUEUE_DIR = os.environ.get("PFAS_PACKAGE_DIR", "/data/qc/packages")
SUBDIRS = ("queue", "done", "failed", "traces")
# where a report's job files sit until the worker posts the package back:
# waiting, and moved aside while it builds
QUEUED_DIRS = ("queue", "building")
# the designs a package may print from, by Document Templates kind
DESIGN_KINDS = ("coa", "qc_review", "batch_record")

NOT_IN_CATALOGUE = u"Certificate tier %s is not in the issued catalogue: issue a revision or set the sample's tier."


def _labels():
    return dict((key, label) for key, label, _secs in report_tiers.PARTS)


def job(report_uid, sample, tier, catalogue_rev, revisions, base_url, queued_at, lab_name=u"", mono=False):
    """The worker's job for one sample of a report. `sample` holds the ids
    (sample_id, sample_uid, client_sample_id, batch_id, worksheet_id,
    worksheet_uid) and,
    from the shell, the register's next revision (1 when absent) and the
    run's latest countersign time ("" when absent). `lab_name` names the
    package's seal. `mono`: the client takes its certificates in black and
    white, and so every document of the package."""
    labels = _labels()
    parts = []
    # a tier read from an older revision names a renamed part by its old key
    for p in report_tiers.rename_parts(tier.get("parts") or [])[0]:
        part = dict(p)
        part["label"] = labels.get(p.get("key"), p.get("key"))
        parts.append(part)
    revision = int(sample.get("revision") or 1)
    return {
        "report_uid": report_uid,
        "report_id": u"%s-R%s" % (sample.get("sample_id") or u"", revision),
        "revision": revision,
        "sample_id": sample.get("sample_id") or u"",
        "sample_uid": sample.get("sample_uid") or u"",
        # the run names a sample's injections by its client sample id
        "client_sample_id": sample.get("client_sample_id") or u"",
        "batch_id": sample.get("batch_id") or u"",
        "worksheet_id": sample.get("worksheet_id") or u"",
        "worksheet_uid": sample.get("worksheet_uid") or u"",
        "countersign_at": sample.get("countersign_at") or u"",
        # the authoriser signed it as an interim certificate: the worker
        # stamps it so
        "interim": bool(sample.get("interim")),
        # every document of the package in black and white: the client of
        # the report's primary sample takes its certificates so
        "mono": bool(mono),
        # the seal is the lab's: "<lab name> records seal"
        "lab_name": lab_name or u"",
        "tier_id": tier.get("id"),
        "tier_name": tier.get("name") or u"",
        "parts": parts,
        "catalogue_revision": catalogue_rev,
        "design_revisions": dict(revisions or {}),
        "base_url": base_url,
        "queued_at": queued_at,
    }


def pending_record(tier, parts, queued_at):
    return {"state": "pending", "tier": {"id": tier.get("id"), "name": tier.get("name") or u""},
            "parts": list(parts), "queued_at": queued_at, "built_at": u"", "failed_at": u"", "pages": 0,
            "sha256": u"", "reason": u"", "revisions": {}, "worker": u"", "trace_key": u"", "cert_fp": u""}


def stamp():
    """A stored stamp, UTC to the second; shown through lab_time when read."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat()


def complete(rec, pages, sha256, built_at, revisions, worker, trace_key=u"", cert_fp=u""):
    """The record once the worker has built and sealed its package, with
    the cache key of the chromatogram pages it holds (u"" when none was
    kept) and the seal certificate's fingerprint. Only a pending package
    is completed: a second hand-back changes nothing."""
    if rec.get("state") != "pending":
        raise ValueError("not pending")
    out = copy.deepcopy(rec)
    out.update({"state": "ready", "pages": int(pages), "sha256": sha256, "built_at": built_at,
                "revisions": dict(revisions or {}), "worker": worker, "reason": u"",
                "trace_key": trace_key or u"", "cert_fp": cert_fp or u""})
    return out


def fail(rec, reason, at):
    """The record once the worker could not build its package, the reason
    kept for the person who retries it. Only a pending package fails."""
    if rec.get("state") != "pending":
        raise ValueError("not pending")
    out = copy.deepcopy(rec)
    out.update({"state": "failed", "reason": reason, "failed_at": at})
    return out


def retry(rec, at):
    """A failed package queued again: pending from `at`, its failure
    cleared. Only a failed package is retried."""
    if rec.get("state") != "failed":
        raise ValueError("not failed")
    out = copy.deepcopy(rec)
    out.update({"state": "pending", "reason": u"", "failed_at": u"", "queued_at": at})
    return out


def requeue(rec, revisions, at):
    """The record with its jobs as they are queued again at `at`: each job
    names the designs issued now (`revisions`, as design_revisions reads
    them), so a design issued or reissued since the job was first queued is
    printed rather than refused again; the certificate keeps the revision it
    was stored with, since its part is the stored PDF. The record and every
    job are queued from `at`."""
    out = copy.deepcopy(rec)
    out["queued_at"] = at
    for j in (out.get("jobs") or {}).values():
        found = dict((k, v) for k, v in (revisions or {}).items() if k != "coa")
        old = j.get("design_revisions") or {}
        if "coa" in old:
            found["coa"] = old["coa"]
        j["design_revisions"] = found
        j["queued_at"] = at
    return out


def register_fields(rec):
    """What the register records of a report's package at its issue, a
    copy, so the entry stays as it was issued: the tier, the package's
    state, the parts, the catalogue revision its jobs were queued from, the
    design revisions and chromatogram cache key the worker built from, and
    the package's pages, hash, build time and worker, whether its jobs
    were stamped interim, and the seal: the sealed package's hash and its
    certificate's fingerprint, blank until the package is sealed. A report
    with no record gives {}."""
    if not rec:
        return {}
    jobs = rec.get("jobs") or {}
    found = [jobs[uid].get("catalogue_revision") for uid in sorted(jobs)]
    tier = rec.get("tier") or {}
    # a package is sealed once it is ready with the seal's certificate named
    sealed = rec.get("state") == "ready" and bool(rec.get("cert_fp"))
    return {"report_tier": {"id": tier.get("id"), "name": tier.get("name") or u""},
            "package_state": rec.get("state") or u"",
            "package_parts": list(rec.get("parts") or []),
            "catalogue_revision": found[0] if found else None,
            "design_revisions": copy.deepcopy(rec.get("revisions") or {}),
            "trace_key": rec.get("trace_key") or u"",
            "package_pages": int(rec.get("pages") or 0),
            "package_sha256": rec.get("sha256") or u"",
            "package_built_at": rec.get("built_at") or u"",
            "package_worker": rec.get("worker") or u"",
            # what the jobs were stamped with; the register prefers the
            # pending signature it consumes at issue
            "interim": any(bool(jobs[uid].get("interim")) for uid in jobs),
            "sealed_sha256": (rec.get("sha256") or u"") if sealed else u"",
            "seal_cert": (rec.get("cert_fp") or u"") if sealed else u""}


def latest_countersign(state):
    """The newest countersign time of the run's Raw Data changes, u"" when
    none is countersigned (ISO times compare as text)."""
    found = [(r.get("verifier") or {}).get("at") or u""
             for r in (state or {}).get("raw_changes") or []]
    return max(found) if found else u""


def job_file_name(report_uid, sample_uid):
    return u"%s-%s.json" % (report_uid, sample_uid)


def job_path(report_uid, sample_uid, base=None):
    return os.path.join(base or QUEUE_DIR, "queue", job_file_name(report_uid, sample_uid))


def queued_names(base=None):
    """The job file names waiting in the worker's queue or being built. A
    folder not made yet holds none; one that cannot be read raises OSError,
    so nobody takes an unreadable queue for an empty one."""
    names = []
    for sub in QUEUED_DIRS:
        try:
            names.extend(os.listdir(os.path.join(base or QUEUE_DIR, sub)))
        except OSError as exc:
            if exc.errno != errno.ENOENT:
                raise
    return names


def _ensure_dir(d):
    if d and not os.path.isdir(d):
        try:
            os.makedirs(d, 0o770)
        except OSError:
            if not os.path.isdir(d):
                raise


def write_job(path, job):
    """Write the job whole: to a name the worker does not read, then renamed
    onto `path`, so a half-written job is never picked up."""
    _ensure_dir(os.path.dirname(path))
    text = json.dumps(job, sort_keys=True, indent=2)
    if isinstance(text, bytes):                             # Python 2
        text = text.decode("utf-8")
    tmp = path + ".tmp"
    with io.open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.rename(tmp, path)


def _unique(objs):
    """`objs` each once, in order, by uid; None dropped."""
    from bika.lims import api
    out, seen = [], set()
    for o in objs:
        if o is None or api.get_uid(o) in seen:
            continue
        seen.add(api.get_uid(o))
        out.append(o)
    return out


def _report_samples(report):
    """The report's sample uids, the primary first, each once."""
    from bika.lims import api
    found = [report.getAnalysisRequest()] + list(report.getContainedAnalysisRequests() or [])
    return [api.get_uid(s) for s in _unique(found)]


def _worksheet(sample):
    for an in sample.getAnalyses(full_objects=True):
        ws = an.getWorksheet() if hasattr(an, "getWorksheet") else None
        if ws is not None:
            return ws
    return None


def _sample_info(sample):
    from bika.lims import api
    from senaite.pfas.browser import controlled_publications
    from senaite.pfas.browser import manual_integration_view as miv
    ws = _worksheet(sample)
    batch = sample.getBatch()
    return {"sample_id": api.get_id(sample), "sample_uid": api.get_uid(sample),
            "client_sample_id": (sample.getClientSampleID() or u"").strip(),
            "batch_id": batch.getId() if batch is not None else u"",
            "worksheet_id": ws.getId() if ws is not None else u"",
            "worksheet_uid": api.get_uid(ws) if ws is not None else u"",
            "revision": len(controlled_publications.get_publication_log(sample)) + 1,
            "interim": bool((controlled_publications.pending_signature(sample) or {}).get("interim")),
            "countersign_at": latest_countersign(miv.load_state(ws)) if ws is not None else u""}


def worksheet_names(ws):
    """{client sample id: lab sample id} of every sample on the worksheet
    (sample_names.lab_names): what a package's parts print each sample's
    injections by. Reference analyses carry no client sample."""
    from senaite.pfas import sample_names
    pairs, seen = [], set()
    for an in (ws.getAnalyses() if ws is not None else None) or []:
        get = getattr(an, "getRequest", None)
        sample = get() if get is not None else None
        if sample is None or sample.getId() in seen:
            continue
        seen.add(sample.getId())
        pairs.append((sample.getId(), sample.getClientSampleID() or u""))
    return sample_names.lab_names(pairs)


def lab_name(portal):
    """The laboratory's name, u"" when it has none or cannot be read: the
    seal then names the laboratory alone."""
    from senaite.pfas import lab_identity
    return lab_identity.lab_name(portal)


def design_revisions(portal):
    """{kind: rev} of what a package prints from: the certificate is the
    issued reporting-template revision; the QC Review and the batch record
    their issued Document Templates design. A kind with nothing issued is
    left out."""
    from senaite.pfas import document_templates as dt
    from senaite.pfas import report_templates
    out = {}
    _snap, rev = report_templates.issued_snapshot(portal)
    if rev is not None:
        out["coa"] = rev
    store = dt.load(portal)
    for kind in DESIGN_KINDS:
        if kind == "coa" or dt.issued_design(store, kind) is None:
            continue
        cur = dt.current(store[dt.KINDS[kind]["single"]])
        if cur:
            out[kind] = cur["rev"]
    return out


def prepare(uids, request=None):
    """Everything about a certificate's package that can fail, done before
    the certificate is stored (impress commits the stored report at once): a
    plan {"record", "samples", "jobs": {sample uid: job}} with the report uid
    left blank, or None for a tier of the certificate alone. The primary
    sample's tier (the first of `uids`) decides; a tier id the issued
    catalogue does not hold refuses the certificate."""
    from bika.lims import api
    from senaite.pfas.browser.coa_storage import DesignedCertificateError
    portal = api.get_portal()
    samples = _unique([api.get_object(uid) for uid in uids or ()])
    if not samples:
        return None
    tier, tier_id, _catalogue, catalogue_rev = report_tiers.resolve(samples[0], portal)
    if tier is None:
        raise DesignedCertificateError(NOT_IN_CATALOGUE % tier_id)
    if not report_tiers.needs_package(tier):
        return None
    queued_at = stamp()
    revisions = design_revisions(portal)
    base_url = portal.absolute_url()
    lab = lab_name(portal)
    # the primary sample's client decides, as for the certificate
    from senaite.pfas.edd_store import certificate_mono
    mono = certificate_mono(samples[0].getClient())
    plan = {"record": pending_record(tier, [p.get("key") for p in tier.get("parts") or []], queued_at),
            "samples": [], "jobs": {}}
    for sample in samples:
        info = _sample_info(sample)
        plan["samples"].append(info["sample_uid"])
        plan["jobs"][info["sample_uid"]] = job(u"", info, tier, catalogue_rev, revisions, base_url, queued_at,
                                               lab_name=lab, mono=mono)
    return plan


def attach(report, plan):
    """Give a stored certificate its package: the record on the report and
    one job file per sample, written after the commit. A sample of the
    report the plan does not hold fails the package with the reason, and no
    job is written. None when there is no plan."""
    if not plan:
        return None
    from bika.lims import api
    from senaite.pfas import after_commit
    report_uid = api.get_uid(report)
    rec = copy.deepcopy(plan["record"])
    rec["samples"] = _report_samples(report)
    rec["jobs"] = {}
    missing = [uid for uid in rec["samples"] if uid not in plan["jobs"]]
    if missing:
        rec["state"] = "failed"
        rec["reason"] = u"Not prepared with the certificate: sample %s" % u", ".join(missing)
        set_record(report, rec)
        return rec
    for uid in rec["samples"]:
        rec["jobs"][uid] = dict(plan["jobs"][uid], report_uid=report_uid)
    set_record(report, rec)
    for uid in rec["samples"]:
        # one key per job file: run_once keeps one call per key
        after_commit.run_once("report package %s" % job_file_name(report_uid, uid), write_job,
                              job_path(report_uid, uid), rec["jobs"][uid])
    return rec


def is_certificate_report(report):
    """True for a stored certificate: a report printed from the
    certificate template, never a QC Review report of the same sample."""
    from senaite.pfas.browser.coa_storage import is_certificate
    return is_certificate((report.getMetadata() or {}).get("template"))


def record(report):
    """The report's package state, or None when it has none (or it cannot
    be read)."""
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(report).get(PACKAGE_KEY)
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("report package record: %s", exc)
        return None
    return found if isinstance(found, dict) else None


def set_record(report, rec):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(report)[PACKAGE_KEY] = json.dumps(rec, sort_keys=True)


# ── a certificate sealed alone (no package) ──────────────────────────────────

def seal_job(report_uid, sample_id, sample_uid, revision, lab, queued_at):
    """The worker's seal job for a certificate stored with no package."""
    revision = int(revision or 1)
    return {"report": report_uid, "sample": sample_uid,
            "report_id": u"%s-R%s" % (sample_id or u"", revision), "revision": revision,
            "lab_name": lab or u"", "queued_at": queued_at}


def seal_job_name(report_uid):
    return u"%s.json" % report_uid


def seal_job_path(report_uid, base=None):
    return os.path.join(base or QUEUE_DIR, SEAL_DIR, seal_job_name(report_uid))


def seal_queued_names(base=None):
    """The seal job file names waiting for the worker; a folder not made
    yet holds none, one that cannot be read raises OSError."""
    try:
        return [n for n in os.listdir(os.path.join(base or QUEUE_DIR, SEAL_DIR))
                if os.path.isfile(os.path.join(base or QUEUE_DIR, SEAL_DIR, n))]
    except OSError as exc:
        if exc.errno != errno.ENOENT:
            raise
        return []


def seal_pending(job, at):
    """A seal waiting for the worker, its job kept so a retry can queue it
    again."""
    return {"state": "pending", "sha256": u"", "cert_fp": u"", "at": u"", "reason": u"",
            "queued_at": at, "job": dict(job)}


def seal_sealed(rec, sha256, cert_fp, at):
    """The seal once the worker handed the sealed certificate back. Only a
    pending seal is completed."""
    if (rec or {}).get("state") != "pending":
        raise ValueError("not pending")
    out = copy.deepcopy(rec)
    out.update({"state": "sealed", "sha256": sha256, "cert_fp": cert_fp, "at": at, "reason": u""})
    return out


def seal_failed(rec, reason, at):
    """The seal once the worker could not make it. Only a pending seal fails."""
    if (rec or {}).get("state") != "pending":
        raise ValueError("not pending")
    out = copy.deepcopy(rec)
    out.update({"state": "failed", "reason": reason, "at": at})
    return out


def seal_requeue(rec, at):
    """A failed seal, or a pending one whose job file was lost, queued
    again from `at`."""
    out = copy.deepcopy(rec)
    out.update({"state": "pending", "reason": u"", "at": u"", "queued_at": at})
    out["job"] = dict(out.get("job") or {}, queued_at=at)
    return out


def seal_refusal(rec):
    """Why a certificate stored with no package may not be published yet:
    its seal is pending or failed. None when it is sealed, or when the
    report has no seal record."""
    if not rec:
        return None
    state = rec.get("state")
    if state == "sealed":
        return None
    if state == "pending":
        return SEAL_PENDING
    reason = (rec.get("reason") or u"").strip().rstrip(u".") or u"no reason given"
    return SEAL_FAILED % reason


def never_sealed(package, seal):
    """True for a stored certificate that holds no seal and is not on its
    way to one: stored before certificates were sealed, with neither a
    package record nor a seal record, or with a package built ready
    without the seal's certificate (every hand-back names one now).
    `package` is its package record, `seal` its seal record. Such a
    certificate is never issued: it is generated again (NOT_SEALED)."""
    if package:
        return package.get("state") == "ready" and not package.get("cert_fp")
    return not seal


def seal_fields(rec):
    """What the register records of a certificate sealed alone: the sealed
    PDF's hash and the seal certificate's fingerprint, blank unless it is
    sealed."""
    sealed = bool(rec) and rec.get("state") == "sealed"
    return {"sealed_sha256": (rec.get("sha256") or u"") if sealed else u"",
            "seal_cert": (rec.get("cert_fp") or u"") if sealed else u""}


def queue_seal(report):
    """Queue the worker's seal of a certificate stored with no package: the
    seal pending on the report, its job file written after the commit."""
    from bika.lims import api
    from senaite.pfas import after_commit
    from senaite.pfas.browser import controlled_publications
    report_uid = api.get_uid(report)
    sample = report.getAnalysisRequest()
    revision = len(controlled_publications.get_publication_log(sample)) + 1
    at = stamp()
    found = seal_job(report_uid, api.get_id(sample), api.get_uid(sample), revision,
                     lab_name(api.get_portal()), at)
    rec = seal_pending(found, at)
    set_seal_record(report, rec)
    after_commit.run_once(u"certificate seal %s" % report_uid, write_job, seal_job_path(report_uid), found)
    return rec


def seal_record(report):
    """The report's seal state, or None when it has none. A record that
    cannot be read is a failed seal: publishing waits rather than letting
    an unsealed certificate through."""
    from zope.annotation.interfaces import IAnnotations
    raw = IAnnotations(report).get(SEAL_KEY)
    if not raw:
        return None
    try:
        found = json.loads(raw)
    except (ValueError, TypeError) as exc:
        logger.warning("certificate seal record: %s", exc)
        found = None
    if not isinstance(found, dict):
        return {"state": "failed", "reason": SEAL_UNREADABLE}
    return found


def set_seal_record(report, rec):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(report)[SEAL_KEY] = json.dumps(rec, sort_keys=True)
