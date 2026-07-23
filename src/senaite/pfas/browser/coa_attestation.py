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

from collections import OrderedDict

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile


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
