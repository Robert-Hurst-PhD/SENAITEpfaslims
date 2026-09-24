# -*- coding: utf-8 -*-
"""
Controlled CoA attestation (D65, Phase A2).

Renders the three-tier authorization block on the client-facing Certificate of
Analysis, resolved from the ACTUAL workflow actors (not a static Print Settings
pool):

  * Prepared by   -> the analyst(s) who SUBMITTED results (submit transition
                     on the sample and/or its analyses)
  * Verified by   -> the manager/QAO who VERIFIED (verify transition)
  * Authorized by -> the user publishing the report now (current user)

Each actor is resolved to a LabContact where one is linked (for fullname, job
title and signature image); a ruled line is drawn for a wet signature where no
signature image is on file. This is the ISO 17025 §7.8.4 technical-review trail
carried onto the issued certificate.

Invoked from templates/reports/CertificateOfAnalysis.pt in place of core's
render_signatures section. Core reports are untouched (§6C, Golden Rule 2).

Python 2.7 compatible (no f-strings / annotations).
"""
from __future__ import absolute_import

import logging

from collections import OrderedDict

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

logger = logging.getLogger("senaite.pfas.coa_attestation")


class PFASCoAAttestationView(BrowserView):
    """Resolve + render the controlled 3-tier attestation for a CoA."""

    attestation = ViewPageTemplateFile("templates/coa_attestation.pt")

    def __call__(self, collection=None, report_view=None):
        # `collection` is the impress report's list of SuperModels (one per
        # sample on the certificate); `report_view` is the impress ReportView.
        self.collection = collection or []
        self.report_view = report_view
        self.signatories = self.resolve_signatories(self.collection)
        self.meta = self.controlled_doc_meta(self.collection)
        return self.attestation()

    def controlled_doc_meta(self, collection=None):
        """Controlled-document identity for the primary sample. Computed at
        RENDER time, i.e. BEFORE the publish transition writes the log entry —
        so the revision shown is the PROSPECTIVE one this issuance will become
        (prior issues + 1). Used for the report header/footer stamp."""
        collection = collection if collection is not None else getattr(
            self, "collection", [])
        meta = {"report_id": u"", "revision": 1, "sample_id": u""}
        if not collection:
            return meta
        try:
            from senaite.pfas.browser.controlled_publications import \
                get_publication_log
            sample = api.get_object(collection[0])
            revision = len(get_publication_log(sample)) + 1
            sample_id = api.get_id(sample)
            meta.update({
                "report_id": u"{0}-R{1}".format(sample_id, revision),
                "revision": revision,
                "sample_id": sample_id,
            })
        except Exception:
            pass
        return meta

    def accreditation_disclosure(self, collection=None):
        """The accreditation statement for the sample(s) on this certificate,
        or None when there is nothing to state.

        Read from the criteria FROZEN on the worksheet at verification
        (`worksheet_criteria_snapshot`), never resolved live. A certificate is a
        claim about a judgement that already happened; resolving now would state
        what the lab would do today as though it were what the lab did — the
        defect GAPS.md §24 exists to prevent.

        This is deliberately SAMPLE-scoped and must stay visually separate from
        `qc_qualifications()` below, which is RESULT-scoped. "This result was
        released despite a failing QC criterion [M]" and "this sample falls
        outside the laboratory's accreditation" are different claims about
        different things; printing them as one list would blur a per-measurement
        caveat into a scope statement, or worse, the reverse.
        """
        collection = collection if collection is not None else getattr(
            self, "collection", [])
        if not collection:
            return None
        try:
            from senaite.pfas import disclosure
            from senaite.pfas import worksheet_criteria_snapshot as wcs
            from senaite.pfas.browser.qc_review_report import _worksheet_for
            sample = api.get_object(collection[0])
            worksheet = _worksheet_for(sample)
            if worksheet is None:
                return None
            snapshot = wcs.get_frozen_criteria(worksheet)
            if not snapshot:
                # No frozen record. The certificate says nothing rather than
                # implying conformance — and nothing rather than a guess.
                return None
            out = disclosure.build_disclosure(snapshot)
            out["lines"] = [disclosure.format_departure(i)
                            for i in out.get("items") or []]
            return out
        except Exception as exc:
            logger.error("accreditation_disclosure: %s", exc)
            return None

    def qc_qualifications(self, collection=None):
        """Qualifiers that apply to the sample(s) on this certificate.

        A qualified release means a failing QC result was issued anyway because
        the QAO's library says the failure is attributable to the sample. That
        is only defensible if the certificate SAYS so — ISO 17025 §7.8.4 permits
        releasing non-conforming work when the deviation is authorised,
        justified and recorded, and the certificate is where the client's half
        of that record lives.

        Grouped by code so the statement appears once, with the analytes it
        applies to — a blanket caveat on every result devalues the warning.
        """
        collection = collection if collection is not None else getattr(
            self, "collection", [])
        if not collection:
            return []
        try:
            from senaite.pfas.browser.qc_review_report import _worksheet_for
            sample = api.get_object(collection[0])
            worksheet = _worksheet_for(sample)
            if worksheet is None:
                return []
            review = worksheet.restrictedTraverse(str("@@pfas-data-review"))
            summary = review._get_qc_summary(worksheet) or {}
        except Exception as exc:                            # noqa: BLE001
            logger.warning("could not resolve QC qualifications: %s", exc)
            return []

        grouped = {}
        for entry in (summary.get("qualifiers") or []):
            code = entry.get("code") or u"?"
            row = grouped.setdefault(code, {
                "code": code,
                "statement": entry.get("statement") or u"",
                "analytes": set(),
            })
            if entry.get("analyte"):
                row["analytes"].add(entry["analyte"])
        out = []
        for code in sorted(grouped):
            row = grouped[code]
            out.append({
                "code": row["code"],
                "statement": row["statement"],
                "analytes": u", ".join(sorted(row["analytes"])),
            })
        return out

    def render_stamp(self, context=None):
        """The controlled-document stamp, as markup.

        QCReviewReport.pt has called this since D65 and it did not exist —
        repo-wide grep found the call and no definition. The report therefore
        could not render, and because BOTH the publish subscriber
        (`controlled_publications.record_publication`) and
        `qc_review_report.snapshot_for_publication` wrap the snapshot in a bare
        `except` that only logs, **every publish silently stored no reviewer
        snapshot at all.** The "freeze the reviewer report against this
        revision" guarantee has never once happened.

        The CoA inlines the same markup in TAL. This is now the one definition
        (§6C: define UI once) and the CoA template calls it too, so the two
        cannot drift.
        """
        collection = getattr(self, "collection", None)
        if not collection and context is not None:
            collection = [context]
        meta = self.controlled_doc_meta(collection)
        report_id = meta.get("report_id") or u""
        parts = [u"Controlled documentation publication"]
        if report_id:
            parts.append(report_id)
        parts.append(u"uncontrolled when printed")
        return (
            u'<div style="margin-top:10px; padding-top:6px; '
            u'border-top:1px solid #ccc; font-size:10px; color:#666; '
            u'text-align:center;">{0}</div>'
        ).format(u" &middot; ".join(parts))

    # ── resolution ────────────────────────────────────────────────────────

    def resolve_signatories(self, collection):
        """Return {"prepared": [info, ...], "verified": [info, ...],
        "authorized": info} resolved from the live workflow history of every
        sample (and its analyses) on the certificate."""
        prepared = OrderedDict()   # userid -> info (dedup, submit order kept)
        verified = OrderedDict()   # userid -> info
        for model in collection:
            try:
                sample = api.get_object(model)
            except Exception:
                continue
            # Sample-level workflow (rolls up submit/verify)…
            self._collect(sample, prepared, verified)
            # …and per-analysis workflow (who actually submitted each result).
            for brain in self._get_analyses(sample):
                an = api.get_object(brain)
                if an is None:
                    continue
                self._collect(an, prepared, verified)
        return {
            "prepared": list(prepared.values()),
            "verified": list(verified.values()),
            "authorized": self._current_actor_info(),
        }

    def _collect(self, obj, prepared, verified):
        """Fold an object's submit/verify actors into the dedup maps."""
        for entry in api.get_review_history(obj):
            action = entry.get("action")
            actor = entry.get("actor")
            if not actor:
                continue
            if action == "submit" and actor not in prepared:
                prepared[actor] = self._actor_info(actor, entry.get("time"))
            elif action == "verify" and actor not in verified:
                verified[actor] = self._actor_info(actor, entry.get("time"))

    def _get_analyses(self, sample):
        try:
            return sample.getAnalyses() or []
        except Exception:
            return []

    def _actor_info(self, userid, when=None):
        """Resolve a workflow actor's user id to display info + signature."""
        fullname = userid
        jobtitle = u""
        signature_url = None
        user = None
        contact = None
        try:
            user = api.get_user(userid)
        except Exception:
            user = None
        if user is not None:
            try:
                contact = api.get_user_contact(user, ["LabContact"])
            except Exception:
                contact = None
            props = {}
            try:
                props = api.get_user_properties(user)
            except Exception:
                props = {}
            if contact is not None and contact.getFullname():
                fullname = contact.getFullname()
            elif props.get("fullname"):
                fullname = props.get("fullname")
        if contact is not None:
            get_job = getattr(contact, "getJobTitle", None)
            if get_job:
                jobtitle = get_job() or u""
            if contact.getSignature():
                signature_url = "{0}/Signature".format(contact.absolute_url())
        return {
            "userid": userid,
            "fullname": fullname,
            "jobtitle": jobtitle,
            "signature_url": signature_url,
            "date": self._fmt(when),
        }

    def _current_actor_info(self):
        """The publisher = the authorizing actor (publish happens now)."""
        try:
            userid = api.get_current_user().getId()
        except Exception:
            userid = u""
        return self._actor_info(userid, DateTime())

    def _fmt(self, when):
        if not when:
            return u""
        try:
            return when.strftime("%d %b %Y %H:%M")
        except Exception:
            return str(when)
