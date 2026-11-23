# -*- coding: utf-8 -*-
"""
Controlled publication register (Phase B).

Every issuance of a Certificate of Analysis is a controlled documentation
publication. The issuance event is the sample's `publish` / `publish_immediately`
workflow transition (the confirmed authorization event, D45/D65 — NOT ARReport
creation, which also fires on a plain "Save" draft).

On each publish transition we APPEND an immutable entry to a publication log
annotated on the sample. The log is authoritative for revision numbering and
supersede chains; it REFERENCES the core ARReport artifact (for the live PDF /
recipients / date) rather than duplicating it (Golden Rule 3).

  revision      = position in the log (1 = original issue, 2+ = amended reissue)
  issued_at     = ISO timestamp of the publish transition
  authorizer    = the publishing user (= the CoA "Authorized by" actor)
  report_uid    = the newest certificate whose samples include the sample, at
                  issue time: its own, or the primary's that contains it
  amendment_reason / reason_missing = per the best-effort policy: a reissue
                  (revision >= 2) with no reason captured is FLAGGED, not blocked.
  report_tier, package_* = the report's tier and, when it has one, its
                  package as it stood at issue (report_packages.register_fields)
  Status is COMPUTED (latest revision = current; earlier = superseded) — never
  stored, so the historical entries are never mutated.

Python 2.7 compatible.
"""
from __future__ import absolute_import

import logging

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from ZODB.POSException import ConflictError
from senaite.pfas import report_packages
from senaite.pfas import report_tiers
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.view_helpers import LabTime, publisher_url

logger = logging.getLogger("senaite.pfas.controlled_publications")

# Publication log lives on the sample (AnalysisRequest).
PUBLICATION_LOG_KEY = u"senaite.pfas.controlled_pub_log"
# Transient amendment reason, set by the PFAS "Generate COA" path just before a
# reissue and consumed (cleared) by the publish subscriber.
PENDING_REASON_KEY = u"senaite.pfas.pending_amendment_reason"
# The authoriser's signature given on Data Review before the certificate is
# generated, {userid, meaning, note, interim, at}: the publish guard asks for
# it, the publish subscriber consumes it into the ledger row.
PENDING_SIGNATURE_KEY = u"senaite.pfas.pending_signature"
# On the stored certificate (ARReport): whether it was generated interim or
# final, {interim, at}, from the pending signature at Generate; the publish
# guard refuses a signature of the other kind.
ISSUE_MARK_KEY = u"senaite.pfas.issue_mark"

# Every transition core fires when a CoA is issued/re-issued. Core's EmailView
# maps sample status -> transition: verified->publish, published->REPUBLISH
# (the amended-reissue case — must be captured or the register misses every
# revision >= 2), else prepublish/publish_immediately.
# prepublish issues an interim certificate before verification: it is
# recorded and signed like the others.
PUBLISH_TRANSITIONS = ("publish", "publish_immediately", "republish", "prepublish")

# the catalogue of stored reports: its sample_uid index holds every
# sample a report covers, the primary and each contained sample
REPORT_CATALOG = "senaite_catalog_report"
# the address key of the Awaiting issue list's page
AWAITING_PAGE = "apage"

# the Package cell of the register: the package's state as it is now
BUILDING = u"Building since %s"
READY = u"Ready, %s %s"
FAILED_LINE = u"Failed: %s"
CERTIFICATE_ONLY = u"Certificate only"
NO_RECORD_LINE = u"No certificate record"
# the retry a certificate with no package offers: its seal's
RETRY_SEAL = u"Retry the seal"
# the Awaiting issue list's state: a sample whose current revision is an
# interim certificate waits for its final
INTERIM_PENDING = u"Interim issued, final pending"
NOT_YET_ISSUED = u"Not yet issued"


def package_line(rec, tier, shown, found):
    """The Package cell's text for an issued report: its package's state
    (`shown` gives a stored time as the screen shows it), else "Certificate
    only" at a tier of the certificate alone, else "No certificate record" at a
    tier that needs one, said only of a report that was found (`found`): a
    sample contained in another sample's report holds no report of its
    own. u"" when the entry names no tier, or the record is in no state it
    can be read in."""
    if rec is None:
        if tier is None:
            return u""
        if not report_tiers.needs_package(tier):
            return CERTIFICATE_ONLY
        return NO_RECORD_LINE if found else u""
    state = rec.get("state")
    if state == "pending":
        return BUILDING % shown(rec.get("queued_at") or u"")
    if state == "ready":
        pages = int(rec.get("pages") or 0)
        return READY % (pages, u"page" if pages == 1 else u"pages")
    if state == "failed":
        return FAILED_LINE % (rec.get("reason") or u"")
    return u""


def package_flag(rec, line):
    """What the issued register says of a package beside its tier: nothing
    for a ready package or a certificate alone, else its line."""
    if line == CERTIFICATE_ONLY or (rec is not None and rec.get("state") == "ready"):
        return u""
    return line


# ── event subscriber (mirrors edd_publish.on_after_transition) ─────────────

def on_after_transition(instance, event):
    """Record a controlled publication on every CoA issuance."""
    if getattr(event, "transition", None) is None:
        return
    if instance.portal_type != "AnalysisRequest":
        return
    if event.transition.id not in PUBLISH_TRANSITIONS:
        return
    from senaite.pfas.esig import ledger, signing
    try:
        record_publication(instance)
    except ConflictError:
        raise                     # Zope retries the transaction
    except (ledger.LedgerError, signing.SignatureRefused):
        raise                     # no certificate is issued without its ledger row
    except Exception as exc:  # anything else never breaks the publish transition
        logger.error("controlled-pub: failed to record for %s: %s",
                     api.get_id(instance), exc)


def _review_state_at_issue(ar):
    """"passed" / "qualified" / "not passed" / "unknown" for the sample's
    worksheet checklist, evaluated at the moment of issue."""
    try:
        from senaite.pfas.browser.qc_review_report import _worksheet_for
        worksheet = _worksheet_for(ar)
        if worksheet is None:
            return u"unknown: no worksheet"
        review = worksheet.restrictedTraverse(str("@@pfas-data-review"))
        if review.all_items_pass():
            summary = review._get_qc_summary(worksheet) or {}
            if summary.get("qualifiers"):
                return u"qualified: {0} result(s) released with a qualifier".format(
                    len(summary["qualifiers"]))
            return u"passed"
        outstanding = [i.get("key") for i in review.checklist_status()
                       if not i.get("checked")]
        # the manual integrations and the Raw Data changes say what they lack
        for ok_need in (review.mi_gate(), review.raw_changes_gate()):
            if not ok_need[0]:
                outstanding.extend(ok_need[1])
        return u"NOT PASSED: {0}".format(u", ".join(outstanding) or u"unknown")
    except ConflictError:
        raise
    except Exception as exc:                                # noqa: BLE001
        logger.warning("could not evaluate the review state for %s: %s",
                       getattr(ar, "getId", lambda: "?")(), exc)
        return u"unknown"


def _template_rev():
    try:
        from senaite.pfas.report_templates import issued_snapshot
        return issued_snapshot(api.get_portal())[1]
    except ConflictError:
        raise
    except Exception as exc:                                # noqa: BLE001
        logger.error("controlled-pub: no template revision: %s", exc)
        return None


def record_publication(ar):
    """Append an immutable issuance entry to the sample's publication log."""
    ann = IAnnotations(ar)
    log = list(ann.get(PUBLICATION_LOG_KEY, []))
    revision = len(log) + 1

    reason = _pop_pending_reason(ar)
    # consumed whatever happens next: a retried transaction restores it
    pending = pop_pending_signature(ar)
    prev = log[-1] if log else None
    # a final certificate superseding an interim of a sample whose batch
    # was corrected names the latest correction, unless a reason was given
    if not reason and prev and prev.get("interim") and not (pending or {}).get("interim"):
        try:
            reason = _batch_correction_reason(ar)
        except ConflictError:
            raise                 # Zope retries the transaction
        except Exception as exc:  # never break the publish transition
            logger.warning("controlled-pub: the corrections of %s were not read: %s", api.get_id(ar), exc)
    reason_missing = bool(revision >= 2 and not reason)

    entry = {
        "revision": revision,
        "report_id": u"{0}-R{1}".format(api.get_id(ar), revision),
        "issued_at": DateTime().ISO(),
        "authorizer": _current_userid(),
        "report_uid": None,
        "amendment_reason": reason or u"",
        "reason_missing": reason_missing,
        "supersedes": prev["report_id"] if prev else None,
        # Whether the reviewer snapshot was actually taken. Recorded, because
        # for weeks it never was: QCReviewReport.pt called a render_stamp that
        # did not exist, and both this handler and snapshot_for_publication
        # caught the failure and logged it. The certificate issued fine, the
        # log said nothing, and an auditor would have assumed a snapshot
        # existed. A guarantee that fails silently is not a guarantee.
        "qc_snapshot": u"pending",
        # Whether the §7.8.4 technical review had actually passed when this was
        # issued. Publication is NOT blocked on it — that was a deliberate
        # decision — but an auditor must be able to see that a certificate went
        # out ahead of its review, rather than having to infer it.
        "review_state": _review_state_at_issue(ar),
        # the reporting-template revision the certificate was drawn from
        "template_rev": _template_rev(),
        "interim": False,
    }

    # The certificate issued, its tier and its package as they stand at
    # issue: a sample contained in another sample's certificate records
    # that certificate's tier and package; a certificate with no package
    # records its primary sample's tier alone. A lookup that fails is
    # recorded on the entry, never drops the issuance.
    report = None
    try:
        report = _certificate_report(ar)
        if report is not None:
            entry["report_uid"] = api.get_uid(report)
        rec = report_packages.record(report) if report is not None else None
        primary = report.getAnalysisRequest() if report is not None else ar
        entry.update(report_packages.register_fields(rec) or {"report_tier": _sample_tier(primary)})
        # a certificate with no package was sealed alone: its sealed hash
        # and the seal's certificate
        if rec is None and report is not None:
            entry.update(report_packages.seal_fields(report_packages.seal_record(report)))
    except ConflictError:
        raise                     # Zope retries the transaction
    except Exception as exc:      # never break the publish transition
        entry["package_record"] = u"failed: {0}".format(exc)
        logger.error("controlled-pub: package fields failed for %s: %s",
                     api.get_id(ar), exc)

    # The authoriser's signature, bound to the stored PDF as it goes out. A
    # signature the signing core refuses, or a row the ledger cannot write,
    # aborts the publish: no certificate leaves without its ledger row. A
    # missing pending signature is the guard's to refuse; any other fault
    # here is recorded unsigned on the entry.
    from senaite.pfas.esig import ledger, signing
    try:
        from senaite.pfas import lab_time
        from senaite.pfas.esig import certificate as esig_certificate
        entry.update(esig_certificate.sign_issue(
            api.get_portal(), api.get_request(), entry, prev, pending, _pdf_bytes(report),
            shown=lambda value: lab_time.show(value, "utc")))
    except ConflictError:
        raise                     # Zope retries the transaction
    except (ledger.LedgerError, signing.SignatureRefused):
        raise                     # the publish transition aborts with the reason
    except Exception as exc:      # recorded unsigned, the publish goes on
        entry.update({"signature_seq": None, "unsigned": True,
                      "signature_error": u"{0}".format(exc)})
        logger.error("controlled-pub: the certificate of %s was not signed: %s",
                     api.get_id(ar), exc)

    # Freeze the reviewer report against this revision. Regenerating it later
    # would show the data as it is THEN; an auditor asking about a certificate
    # issued months ago needs what was true when it was issued.
    try:
        from senaite.pfas.browser.qc_review_report import (
            snapshot_for_publication)
        taken = snapshot_for_publication(ar, revision)
        entry["qc_snapshot"] = u"ok" if taken else u"failed: not stored"
    except ConflictError:
        raise                     # Zope retries the transaction
    except Exception as exc:      # never break the publish transition
        entry["qc_snapshot"] = u"failed: {0}".format(exc)
        logger.error("controlled-pub: QC review snapshot failed for %s: %s",
                     api.get_id(ar), exc)

    # an interim certificate marked when Verify sent its run back: this
    # issue supersedes it, and its entry says which and why (its e-mail
    # tells the client); the interim's own entry is never changed
    try:
        import json as _json
        from senaite.pfas import interim_certificates as ic
        from senaite.pfas.interim_certificates import MARKS_KEY as INTERIM_MARKS_KEY
        marks, carried = ic.resolve(_json.loads(ann.get(INTERIM_MARKS_KEY) or "[]"), entry["report_id"],
                                    entry["issued_at"])
        if carried:
            entry["supersedes_interim"] = carried
            ann[INTERIM_MARKS_KEY] = _json.dumps(marks)
    except ConflictError:
        raise                     # Zope retries the transaction
    except Exception as exc:      # never break the publish transition
        entry["supersedes_interim_error"] = u"{0}".format(exc)
        logger.error("controlled-pub: interim marks of %s not read: %s", api.get_id(ar), exc)

    log.append(entry)
    ann[PUBLICATION_LOG_KEY] = log

    # The issue's e-mail is queued on the report in the issue's own
    # transaction: an issue never loses its delivery. Send e-mails it.
    try:
        from senaite.pfas import certificate_delivery
        certificate_delivery.queue_for_issue(ar, entry, report)
    except ConflictError:
        raise                     # Zope retries the transaction
    except Exception as exc:      # never break the publish transition
        logger.error("controlled-pub: the e-mail of %s was not queued: %s", entry["report_id"], exc)

    logger.info("controlled-pub: %s issued (rev %s%s)",
                entry["report_id"], revision,
                ", reason not recorded" if reason_missing else "")
    return entry


# ── read side (register view + report header) ───────────────────────────────

def get_publication_log(ar):
    """Return the sample's issuance entries, newest first, with computed
    status ('current' for the latest revision, else 'superseded')."""
    ann = IAnnotations(ar)
    log = list(ann.get(PUBLICATION_LOG_KEY, []))
    if not log:
        return []
    top = len(log)
    out = []
    for entry in log:
        row = dict(entry)
        row["status"] = "current" if entry["revision"] == top else "superseded"
        out.append(row)
    out.reverse()
    return out



def set_pending_amendment_reason(ar, reason):
    """Stash a reissue reason to be consumed by the next publish transition."""
    ann = IAnnotations(ar)
    if reason:
        ann[PENDING_REASON_KEY] = api.safe_unicode(reason)
    elif PENDING_REASON_KEY in ann:
        del ann[PENDING_REASON_KEY]


def update_amendment_reason(ar, revision, reason):
    """Fill in (or correct) the amendment reason on an EXISTING issuance entry
    — the QAO's fill-in-later path for a flagged reissue. Only the reason field
    is edited; the issuance facts (revision/date/authorizer/supersede) stay
    immutable, and a reason replaced is kept in reason_history with who
    replaced it and when. Clears the reason_missing flag once a reason is present."""
    from senaite.pfas.config_history import actor, now
    ann = IAnnotations(ar)
    log = list(ann.get(PUBLICATION_LOG_KEY, []))
    reason = (reason or u"").strip()
    for i, entry in enumerate(log):
        if entry.get("revision") == revision:
            new = dict(entry)
            at, who = now(), actor()
            old = entry.get("amendment_reason") or u""
            if old and old != reason:
                new["reason_history"] = list(entry.get("reason_history") or []) + [
                    {"reason": old, "replaced_at": at, "replaced_by": who}]
            new["amendment_reason"] = api.safe_unicode(reason)
            new["reason_set_at"], new["reason_set_by"] = at, who
            new["reason_missing"] = bool(revision >= 2 and not reason)
            log[i] = new
            ann[PUBLICATION_LOG_KEY] = log
            return True
    return False


def set_pending_signature(ar, rec):
    """Keep the authoriser's signature on the sample until its certificate
    is published (esig.certificate.pending_record)."""
    IAnnotations(ar)[PENDING_SIGNATURE_KEY] = dict(rec)


def pending_signature(ar):
    """The signature waiting on the sample, or None."""
    rec = IAnnotations(ar).get(PENDING_SIGNATURE_KEY)
    return dict(rec) if rec else None


def pop_pending_signature(ar):
    """The signature waiting on the sample, removed; None when there is none."""
    ann = IAnnotations(ar)
    rec = ann.get(PENDING_SIGNATURE_KEY)
    if PENDING_SIGNATURE_KEY in ann:
        del ann[PENDING_SIGNATURE_KEY]
    return dict(rec) if rec else None


def record_issue_mark(report):
    """Record on a stored certificate whether it was generated interim or
    final, and the signature it printed (who, the image kept, when): the
    pending signature on its primary sample decides, none waiting is a
    final signed by nobody. Publishing refuses another signature."""
    from senaite.pfas.esig import certificate as esig_certificate
    pending = pending_signature(report.getAnalysisRequest()) or {}
    IAnnotations(report)[ISSUE_MARK_KEY] = {"interim": bool(pending.get("interim")),
                                            "at": report_packages.stamp(),
                                            "signature": esig_certificate.mark_signature(pending)}


def issue_mark(report):
    """The stored certificate's interim mark, or None when none was
    recorded."""
    rec = IAnnotations(report).get(ISSUE_MARK_KEY)
    return dict(rec) if rec else None


def current_is_interim(ar):
    """True when the sample's newest issue is an interim certificate."""
    log = IAnnotations(ar).get(PUBLICATION_LOG_KEY) or []
    return bool(log and log[-1].get("interim"))


def signature_refusal(ar, userid, stored=True):
    """Why userid may not publish the sample, or None: the publish guard
    and Send both ask this, on one clock. stored=False asks about the
    signature and its signer alone, not the stored certificate: generating
    a certificate asks so, as it makes the certificate those checks read.
    Annotations first: a listing
    asks it per row, and the rest is asked only once the signature itself
    would issue. The signer must still be able to sign it (a sign right or
    a signature image removed since signing refuses here, before the
    transition), the image kept at signing must still be on disk, and the
    ledger must take the row: one that cannot be
    written refuses here, before Send emails anything. The newest
    certificate (a catalogue query) must be sealed,
    or be on its way to a seal: one stored before certificates were sealed
    is generated again. Its interim mark must be the signature's."""
    from senaite.pfas.esig import certificate as esig_certificate
    from senaite.pfas.esig import ledger, signing
    why = esig_certificate.refusal(pending_signature(ar), userid, current_is_interim(ar), signing.utcnow())
    if why:
        return why
    # before verification only an interim certificate issues
    why = esig_certificate.state_refusal(pending_signature(ar), api.get_review_status(ar))
    if why:
        return why
    msgs = esig_certificate.problems(api.get_request(), (pending_signature(ar) or {}).get("interim"),
                                     pending=pending_signature(ar) or {})
    if msgs:
        return u" ".join(msgs)
    # the row is recorded with the image kept at signing: gone, the
    # publish would abort after Send had emailed
    kept = (pending_signature(ar) or {}).get("image_sha256")
    if kept and not signing.has_kept_image(kept):
        return esig_certificate.KEPT_IMAGE_GONE
    if not ledger.writable():
        return ledger.UNWRITABLE
    if not stored:
        return None
    report = _certificate_report(ar)
    if report is not None and report_packages.never_sealed(report_packages.record(report),
                                                           report_packages.seal_record(report)):
        return report_packages.NOT_SEALED
    return esig_certificate.mark_refusal(pending_signature(ar), issue_mark(report) if report is not None else None)


# ── helpers ─────────────────────────────────────────────────────────────────

def _pdf_bytes(report):
    """The stored certificate's bytes, the ones the authoriser's signature
    binds to; None when there is no report or no PDF."""
    if report is None:
        return None
    pdf = report.getPdf()
    data = getattr(pdf, "data", None) if pdf is not None else None
    return data or None


# the register's reason for a final certificate that supersedes an interim,
# from the latest correction of the sample's batch
CORRECTION_REASONS = {"send_back": u"Batch sent back: %s", "amend": u"Amended: %s",
                      "reextract": u"Re-extraction: %s"}


def correction_reason(states):
    """The latest correction in force across the corrections logs of a
    sample's batches (extraction_amendments), in the register's words
    ("Batch sent back: ...", "Amended: ...", "Re-extraction: ..."); an
    undone one is never named; u"" with none."""
    from senaite.pfas import extraction_amendments as ea
    latest = None
    for state in states or ():
        for e in ea.entries_in_force(state):
            if latest is None or (e.get("at") or u"") >= (latest.get("at") or u""):
                latest = e
    if latest is None:
        return u""
    return CORRECTION_REASONS[latest.get("action")] % (latest.get("reason") or u"").strip()


def _batch_correction_reason(ar):
    """correction_reason of every worksheet the sample's analyses stood on,
    a retracted analysis's included."""
    from senaite.pfas import annotation_store
    from senaite.pfas import extraction_amendments as ea
    seen, states = set(), []
    for analysis in ar.objectValues(["Analysis"]):
        ws = analysis.getWorksheet()
        if ws is None or api.get_uid(ws) in seen:
            continue
        seen.add(api.get_uid(ws))
        states.append(annotation_store.read_json(ws, ea.KEY, {}))
    return correction_reason(states)


def _pop_pending_reason(ar):
    ann = IAnnotations(ar)
    reason = ann.get(PENDING_REASON_KEY)
    if PENDING_REASON_KEY in ann:
        del ann[PENDING_REASON_KEY]
    return reason

def _current_userid():
    try:
        return api.get_current_user().getId()
    except Exception:
        return u""

def _report_brains():
    """Every stored report, newest first, unwoken. A catalogue that cannot
    be read is logged and reads as none: the register lists nothing
    awaiting, it decides nothing."""
    try:
        # ZCatalog reads a sort order only as str
        return api.search({"portal_type": "ARReport", "sort_on": "created",
                           "sort_order": str("descending")}, REPORT_CATALOG)
    except ConflictError:
        raise
    except Exception as exc:                                # noqa: BLE001
        logger.error("controlled-pub: the stored reports cannot be read: %s", exc)
        return []

def _sample_key(brain):
    """The id of the sample a stored report is in (its primary sample),
    read from the catalogue path: the report is not woken."""
    return api.get_path(brain).rstrip("/").split("/")[-2]


def newest_unissued(brains, issued, uid_of, sample_of, certificate_of):
    """[(sample id, report)]: each sample's newest certificate while it is
    not yet issued, in the order of the samples' newest reports. `brains`
    are the stored reports newest first; `issued` the uids the register
    names; `sample_of(brain)` the sample it is in; `certificate_of(brain)`
    the report woken when it is a certificate, else None. A report the
    register names is passed over unwoken and settles its sample: an older
    draft behind a sample's newest certificate is never listed, as the
    publishing guard judges the newest alone."""
    settled, out = set(), []
    for brain in brains:
        sid = sample_of(brain)
        if sid in settled:
            continue
        if uid_of(brain) in issued:
            settled.add(sid)
            continue
        report = certificate_of(brain)
        if report is None:
            continue
        settled.add(sid)
        out.append((sid, report))
    return out


def _sample_reports(uid):
    """The stored reports whose samples include the sample `uid`, newest
    first, found by the report catalogue's sample index. A catalogue that
    cannot be read raises: publishing is held on it, never let through."""
    brains = api.search({"portal_type": "ARReport", "sample_uid": uid, "sort_on": "created",
                         "sort_order": "descending"}, REPORT_CATALOG)
    return [api.get_object(b) for b in brains]

def certificate_reports(ar):
    """The certificates whose primary or contained samples include the
    sample, newest first: the ones it holds itself and, when it is
    contained in another sample's certificate, that one. Never a QC Review
    report."""
    uid = api.get_uid(ar)
    # by meta type, so the sample's analyses are never woken
    own = [o for o in ar.objectValues("ARReport") if o.portal_type == "ARReport"]
    found = {}
    for report in own + _sample_reports(uid):
        if report is None or api.get_uid(report) in found:
            continue
        if not report_packages.is_certificate_report(report):
            continue
        if uid in report_packages._report_samples(report):
            found[api.get_uid(report)] = report
    return sorted(found.values(), key=lambda o: o.created(), reverse=True)

def _certificate_report(ar):
    """The newest certificate whose samples include the sample, the one a
    publication of the sample is issued in; None when there is none."""
    reports = certificate_reports(ar)
    return reports[0] if reports else None

def report_issued(report):
    """True when a register entry names the report: it was issued, and its
    PDF is the one sent. The entries are on its samples."""
    uid = api.get_uid(report)
    for sample_uid in report_packages._report_samples(report):
        sample = api.get_object_by_uid(sample_uid, default=None)
        if sample is None:
            continue
        if [e for e in IAnnotations(sample).get(PUBLICATION_LOG_KEY, []) if e.get("report_uid") == uid]:
            return True
    return False

def _sample_tier(ar):
    """{"id", "name"} of the tier the sample reports at; the name is blank
    when the issued catalogue does not hold the id."""
    tier, tier_id, _catalogue, _rev = report_tiers.resolve(ar, api.get_portal())
    return {"id": tier_id, "name": (tier or {}).get("name") or u""}


# ── register view (Reporting → Controlled Publications) ─────────────────────

class PFASControlledPublicationsView(BrowserView, LabTime):
    """Auditor-facing, read-only register of every issued CoA (all clients).

    A view onto the §3 relational spine: each row is a controlled issuance
    entry from a sample's publication log, with artifact facts (recipients,
    PDF) read LIVE from the referenced core ARReport.
    """
    template = ViewPageTemplateFile("templates/controlled_publications.pt")

    def __call__(self):
        flatten_form(self.request)
        if self.request.method == "POST":
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(self.request)
            return self._handle_post()
        if self.request.form.get("format") == "csv":
            return self._csv()
        return self.template()

    def _csv(self):
        """The issued certificates as the page lists them, as a CSV file."""
        from senaite.pfas import certificate_register, lab_time
        resp = self.request.response
        resp.setHeader(str("Content-Type"), str("text/csv; charset=utf-8"))
        resp.setHeader(str("Content-Disposition"), str(
            'attachment; filename="certificate-register-%s.csv"' % lab_time.today().isoformat()))
        return certificate_register.csv_text(self.publications(), self._shown).encode("utf-8")

    def csv_url(self):
        show = u"&show=interim" if self.interim_only() else u""
        return u"%s/@@pfas-controlled-publications?format=csv%s" % (api.get_url(api.get_portal()), show)

    def may_change(self):
        """Whether the person may act on the register (record a reason,
        send, print): a lab manager. The inspector reads it only."""
        if getattr(self, "_may_change", None) is None:
            from senaite.pfas.browser.perms import require_manager
            self._may_change = require_manager(api.get_portal())
        return self._may_change

    def _handle_post(self):
        """QAO fills in an amendment reason on a flagged issuance entry."""
        form = self.request.form
        if form.get("action") == "record_reason":
            sample = api.get_object_by_uid(form.get("sample_uid", ""), default=None)
            try:
                revision = int(form.get("revision", "0"))
            except (TypeError, ValueError):
                revision = 0
            reason = (form.get("reason") or u"").strip()
            if sample is not None and revision and reason:
                update_amendment_reason(sample, revision, reason)
        self.request.response.redirect(
            "{0}/@@pfas-controlled-publications".format(api.get_url(api.get_portal())))
        return u""

    def publications(self):
        """All issuance rows across all samples, newest issue first; with
        the interim filter, only the current revisions issued as interim."""
        rows = []
        interim_only = self.interim_only()
        for ar in self._samples_with_log():
            client = self._client_title(ar)
            for entry in get_publication_log(ar):  # newest revision first
                if interim_only and not (entry.get("interim") and entry.get("status") == "current"):
                    continue
                recipients, pdf_url = self._artifact_info(entry.get("report_uid"))
                # Fallback: the CURRENT revision with no stored CoA artifact
                # (e.g. published without going through impress) still links to
                # the sample's publisher so the final CoA can be viewed/printed.
                coa_live = None
                if not pdf_url and entry.get("status") == "current":
                    coa_live = publisher_url(api.get_url(ar), [api.get_uid(ar)])
                row = dict(entry)
                row.update({
                    "sample_id": api.get_id(ar),
                    "sample_uid": api.get_uid(ar),
                    "sample_url": api.get_url(ar),
                    "client": client,
                    "recipients": recipients,
                    "pdf_url": pdf_url,
                    "coa_live": coa_live,
                    # the bytes the authoriser signed, as the register shows them
                    "hash_prefix": (entry.get("certificate_sha256") or u"")[:12],
                    "signed_by": entry.get("signed_by") or u"",
                    "interim": bool(entry.get("interim")),
                    "unsigned": bool(entry.get("unsigned")),
                })
                row.update(self._package(entry))
                row.update(self._delivery(entry))
                rows.append(row)
        rows.sort(key=lambda r: r.get("issued_at") or "", reverse=True)
        return rows

    def _delivery(self, entry):
        """The row's e-mail: the newest delivery of the report the entry
        issued, as a line, and whether it waits to be sent again (offered
        to a Manager on the current revision only)."""
        from senaite.pfas import certificate_delivery as cd
        uid = entry.get("report_uid")
        report = api.get_object_by_uid(uid, default=None) if uid else None
        last = cd.newest(cd.load(report)) if report is not None else None
        return {"delivery_line": cd.delivery_line(last, self._shown, entry.get("issued_at")),
                "delivery_waiting": bool(cd.is_waiting(last) and entry.get("status") == "current")}


    def awaiting(self):
        """One page of the certificates awaiting issue: each sample's
        newest certificate while it is not yet issued, read from every
        stored report, newest first (newest_unissued), then the samples
        whose current revision is an interim certificate still awaiting its
        final. Only the page's rows are built."""
        if getattr(self, "_awaiting", None) is None:
            from senaite.pfas.browser.list_paging import list_url, page_number, paging
            found = newest_unissued(_report_brains(), self._issued_uids(), api.get_uid, _sample_key,
                                    self._certificate_of)
            items = self._with_interims([{"sample_id": sid, "report": report} for sid, report in found])
            base = u"%s/@@pfas-controlled-publications" % api.get_url(api.get_portal())
            show = u"interim" if self.interim_only() else None
            pg = paging(len(items), page_number(self.request.form, AWAITING_PAGE),
                        lambda p: list_url(base, [(AWAITING_PAGE, p), ("show", show)]))
            rows = []
            for item in items[pg["start"]:pg["end"]]:
                if item.get("ar") is not None:
                    rows.append(self._interim_row(item["ar"]))
                    continue
                row = self._awaiting_row(item["report"])
                if item.get("interim"):
                    row["state"] = INTERIM_PENDING
                rows.append(row)
            self._awaiting, self._awaiting_pg = rows, pg
        return self._awaiting

    def awaiting_paging(self):
        self.awaiting()
        return self._awaiting_pg

    def _certificate_of(self, brain):
        """The stored report when it is a certificate, else None."""
        report = api.get_object(brain)
        if report is None or not report_packages.is_certificate_report(report):
            return None
        return report

    def _with_interims(self, items):
        """The awaiting items with the samples whose current revision is an
        interim certificate: it still awaits its final. Its stored final,
        when there is one, is marked so; else the sample is listed."""
        by_sample = dict((item["sample_id"], item) for item in items)
        out = list(items)
        for ar in self._samples_with_log():
            if not current_is_interim(ar):
                continue
            sid = api.get_id(ar)
            if sid in by_sample:
                by_sample[sid]["interim"] = True
            else:
                out.append({"sample_id": sid, "ar": ar})
        return out

    def _interim_row(self, ar):
        """The Awaiting issue row of a sample whose current revision is an
        interim certificate."""
        entry = get_publication_log(ar)[0]
        _recipients, pdf_url = self._artifact_info(entry.get("report_uid"))
        row = {"report_uid": entry.get("report_uid"), "sample_id": api.get_id(ar), "sample_url": api.get_url(ar),
               "client": self._client_title(ar), "created": self.lab_at(entry.get("issued_at"),
                                                                     entry.get("issued_at") or u""),
               "pdf_url": pdf_url, "package_retry": False, "state": INTERIM_PENDING}
        row.update(self._package(entry))
        return row

    def _awaiting_row(self, report):
        from senaite.pfas import lab_time
        uid = api.get_uid(report)
        sample = report.getAnalysisRequest()
        rec = report_packages.record(report)
        if rec is not None:
            named = rec.get("tier") or {}
            tier = None
        else:
            tier, tier_id, _catalogue, _rev = report_tiers.resolve(sample, api.get_portal())
            named = {"id": tier_id, "name": (tier or {}).get("name")}
        _recipients, pdf_url = self._artifact_info(uid)
        row = {"report_uid": uid, "sample_id": api.get_id(sample), "sample_url": api.get_url(sample),
               "client": self._client_title(sample), "created": lab_time.show(report.created(), "utc"),
               "pdf_url": pdf_url,
               "package_tier": u" ".join(x for x in (named.get("id"), named.get("name")) if x),
               "tier_code": named.get("id") or u"",
               "package_line": package_line(rec, tier, self._shown, True),
               "package_retry": self._may_retry(rec, uid), "state": NOT_YET_ISSUED,
               # a draft that holds publishing is deleted from here too
               "may_delete": self._may_delete(report, rec, uid),
               # Send on the sample's e-mail form issues it; the package gate refuses it there
               "send_url": u"%s/email?uids=%s" % (api.get_url(sample), uid)}
        if rec is None:
            # a certificate with no package waits for its seal, as publishing does
            row.update(self._seal_cell(report, uid))
        return row

    def _seal_cell(self, report, report_uid):
        """The Package cell of a certificate with no package while its seal
        holds publishing: the guard's own reason, and a retry when the
        retry view would queue the seal again. A certificate with no seal
        record was stored before certificates were sealed: it says to
        generate it again, with no retry. {} once it is sealed."""
        seal = report_packages.seal_record(report)
        if report_packages.never_sealed(None, seal):
            return {"package_line": report_packages.NOT_SEALED, "package_retry": False}
        held = report_packages.seal_refusal(seal)
        if not held:
            return {}
        return {"package_line": held, "package_retry": self._may_retry_seal(seal, report_uid),
                "retry_label": RETRY_SEAL}

    def _may_delete(self, report, rec, report_uid):
        """Whether @@pfas-certificate-delete would delete this certificate,
        not yet issued: the same refusal it applies, with the worker's
        queues read once a page. A queue that cannot be read offers no
        delete."""
        from senaite.pfas.browser.report_packages_view import delete_refusal
        names, seals = self._queued(), self._seal_queued()
        if names is None or seals is None:
            return False
        return delete_refusal(True, False, rec, report_packages.seal_record(report) if rec is None else None,
                              names, seals, report_uid) is None

    def _may_retry_seal(self, seal, report_uid):
        """Whether @@pfas-package-retry would queue this certificate's seal
        again; a seal queue that cannot be read offers no retry."""
        from senaite.pfas.browser.report_packages_view import seal_retry_refusal
        names = self._seal_queued()
        return names is not None and seal_retry_refusal(seal, names, report_uid, False) is None

    def _seal_queued(self):
        if not hasattr(self, "_seal_names"):
            try:
                self._seal_names = report_packages.seal_queued_names()
            except OSError as exc:
                logger.error("controlled-pub: the worker's seal queue cannot be read: %s", exc)
                self._seal_names = None
        return self._seal_names

    def _may_retry(self, rec, report_uid):
        """Whether @@pfas-package-retry would queue this report's package
        again: the same refusal it applies, with the worker's queue read
        once a page. A queue that cannot be read offers no retry."""
        if rec is None:
            return False
        from senaite.pfas.browser.report_packages_view import retry_refusal
        names = self._queued()
        return names is not None and retry_refusal(rec, names, report_uid, False) is None

    def _queued(self):
        if not hasattr(self, "_queue_names"):
            try:
                self._queue_names = report_packages.queued_names()
            except OSError as exc:
                logger.error("controlled-pub: the worker's queue cannot be read: %s", exc)
                self._queue_names = None
        return self._queue_names

    def _issued_uids(self):
        """The reports the register names: issued."""
        uids = set()
        for ar in self._samples_with_log():
            for entry in IAnnotations(ar).get(PUBLICATION_LOG_KEY, []):
                if entry.get("report_uid"):
                    uids.add(entry["report_uid"])
        return uids

    def can_retry(self):
        """Whether the person may queue a failed package again: what
        @@pfas-package-retry asks for, Manage Bika and the LabManager or
        Manager role at the portal."""
        if getattr(self, "_can_retry", None) is None:
            from AccessControl import getSecurityManager
            from senaite.core.permissions import ManageBika
            from senaite.pfas.browser.perms import MANAGER_ROLES, has_role_at_portal
            portal = api.get_portal()
            self._can_retry = bool(getSecurityManager().checkPermission(ManageBika, portal)
                                   and has_role_at_portal(portal, MANAGER_ROLES))
        return self._can_retry

    def status_messages(self):
        """The messages left for the page (why a retry was refused), each
        shown once."""
        from Products.statusmessages.interfaces import IStatusMessage
        return [{"text": m.message,
                 "cls": "alert alert-danger" if m.type == "error" else "alert alert-info"}
                for m in IStatusMessage(self.request).show()]

    def retried(self):
        return self.request.form.get("retried") == "1"

    def deleted(self):
        return self.request.form.get("deleted") == "1"

    def interim_only(self):
        """The register filtered to the interim certificates still awaiting
        their final."""
        return self.request.form.get("show") == "interim"

    # ── helpers ─────────────────────────────────────────────────────────

    def _package(self, entry):
        """The row's Package cell: the tier the entry records and the
        package's state read live from the report. An issued report is
        never rebuilt, so its row offers no retry."""
        uid = entry.get("report_uid")
        report = api.get_object_by_uid(uid, default=None) if uid else None
        rec = report_packages.record(report) if report is not None else None
        named = entry.get("report_tier") or {}
        tier_id = named.get("id")
        tier = report_tiers.tier(self._issued_tiers(), tier_id) if tier_id else None
        line = package_line(rec, tier, self._shown, report is not None)
        return {"package_tier": u" ".join(x for x in (tier_id, named.get("name")) if x),
                "tier_code": tier_id or u"", "package_line": line, "package_flag": package_flag(rec, line)}

    def _issued_tiers(self):
        if getattr(self, "_tiers", None) is None:
            from senaite.pfas import report_templates
            self._tiers = report_templates.issued_tiers(api.get_portal())[0] or []
        return self._tiers

    def _shown(self, value):
        """A stored UTC stamp as the register shows it, on the lab's clock."""
        from senaite.pfas import lab_time
        return lab_time.show(value, "utc")

    def _samples_with_log(self):
        if getattr(self, "_logged", None) is not None:
            return self._logged
        out = []
        try:
            brains = api.search({"portal_type": "AnalysisRequest"},
                                catalog="senaite_catalog_sample")
        except Exception:
            brains = []
        for brain in brains:
            ar = api.get_object(brain)
            if ar is None:
                continue
            if IAnnotations(ar).get(PUBLICATION_LOG_KEY):
                out.append(ar)
        self._logged = out
        return out

    def _client_title(self, ar):
        try:
            client = ar.getClient()
            return client.Title() if client else u""
        except Exception:
            return u""

    def _artifact_info(self, report_uid):
        """(recipients-string, coa-url) read live from the core ARReport. The
        URL points at the printed CoA PDF (@@pfas-certificate-pdf, which the
        inspector opens too) when one is stored, else at the ARReport (its
        rendered HTML report)."""
        if not report_uid:
            return (u"", None)
        report = api.get_object_by_uid(report_uid, default=None)
        if report is None:
            return (u"", None)
        names = []
        try:
            for r in (report.getRecipients() or []):
                nm = r.get("Fullname") or r.get("EmailAddress") or ""
                if nm:
                    names.append(nm)
        except Exception:
            pass
        url = api.get_url(report)
        try:
            pdf = report.getPdf()
            if pdf and pdf.get_size():
                # stream the printed CoA PDF
                url = u"%s/@@pfas-certificate-pdf?report=%s" % (
                    api.get_url(api.get_portal()), report_uid)
        except Exception:
            pass
        return (u", ".join(names), url)
