# -*- coding: utf-8 -*-
"""@@pfas-coc-receive?coc=COC-…: the laboratory receives a CoC.
Lab staff only.

Records the receipt date and time, the receipt thermometer with its
correction frozen (receipt_temperature), a temperature per sample (observed
and corrected), seals, labels, holding time, compliance and a note, and --
for a paper CoC -- the scan of the returned copy and who transcribed it.
Completing receipt runs SENAITE's receive transition on every sample of the
CoC with the entered receipt time. A non-compliant answer is received with a
note and flagged; receipt is refused while anything is unanswered
(coc_records.receipt_problems). Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
import os
import re
from datetime import datetime

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import coc_records as cr
from senaite.pfas.browser.formutil import flatten_form


def ensure_coc_batch(rec, samples):
    """The CoC's SENAITE Batch, made the first time (titled by its LIMS CoC
    number, for its client) and every sample of the CoC put in it. A sample
    already in another batch is left there (a person put it there)."""
    batch = api.get_object_by_uid(rec.get("batch_uid"), None) if rec.get("batch_uid") else None
    if batch is None:
        batch = api.create(api.get_portal().batches, "Batch", title=rec["number"],
                           Client=rec.get("client_uid") or None,
                           description=u"Chain of custody %s" % rec["number"])
    for sample in samples:
        if sample is None or sample.getBatch() is not None:
            continue
        sample.getField("Batch").set(sample, batch)
        sample.reindexObject()
    return batch

logger = logging.getLogger("senaite.pfas.coc_receive")

SCAN_DIR = os.environ.get("PFAS_COC_SCAN_DIR", "/data/coc_scans")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _yesno(v):
    return True if v == u"yes" else (False if v == u"no" else None)


class PFASCoCReceiveView(BrowserView):
    template = ViewPageTemplateFile("templates/coc_receive.pt")

    def __call__(self):
        flatten_form(self.request)
        from senaite.pfas.browser.perms import is_staff, refuse
        if not is_staff(api.get_portal()):
            return refuse(self.request, u"Receipt is recorded by laboratory staff.")
        self.errors, self.done = [], u""
        if self.request.method == "POST" and self.record() is not None:
            action = self.request.form.get("action")
            if action == "scan":
                self._scan()
            elif action == "receive":
                self._receive()
        return self.template()

    def portal_url(self):
        return api.get_portal().absolute_url()

    def record(self):
        if not hasattr(self, "_rec"):
            num = (self.request.form.get("coc") or u"").strip()
            self._rec = cr.load(api.get_portal(), num) if num else None
        return self._rec

    def user_name(self):
        user = api.get_current_user()
        return user.getProperty("fullname") or user.getId()

    def samples(self):
        if hasattr(self, "_samples"):
            return self._samples
        out = []
        for uid in (self.record() or {}).get("samples") or []:
            s = api.get_object_by_uid(uid, None)
            if s is not None:
                rng = self._range(s)
                out.append({"uid": uid, "id": s.getId(), "csid": s.getClientSampleID() or u"",
                            "matrix": s.getSampleTypeTitle() or u"",
                            "sampled": s.getDateSampled().strftime("%Y-%m-%d %H:%M")
                            if s.getDateSampled() else u"",
                            "state": api.get_review_status(s), "range": rng,
                            "range_text": self._range_text(rng)})
        self._samples = out
        return out

    def _range(self, sample):
        """The sample's METHOD receipt range (method profile), or None when its method is not identified."""
        from senaite.pfas import sample_method
        from senaite.pfas.method_bridge import profile_id_for_method
        from senaite.pfas.method_profile_store import get_profile
        try:
            method, _why = sample_method.identify(sample)
            mid = profile_id_for_method(method) if method is not None else None
            return (get_profile(api.get_portal(), mid).get("receipt_temperature") or {}) if mid else None
        except Exception as exc:                            # noqa: BLE001
            logger.warning("receipt range for %s: %s", sample.getId(), exc)
            return None

    @staticmethod
    def _range_text(rng):
        rng = rng or {}
        lo, hi = rng.get("min_c"), rng.get("max_c")
        if lo in (None, u"") and hi in (None, u""):
            return u"not set on the method"
        return u"%s to %s \u00b0C" % (u"%s" % lo if lo not in (None, u"") else u"\u2013",
                                       u"%s" % hi if hi not in (None, u"") else u"\u2013")

    def thermometers(self):
        """Receipt thermometers and IR guns registered under Equipment."""
        try:
            from senaite.pfas import equipment_types as et
            from senaite.pfas import facility_qc as fq
            return [u for u in fq.list_units() if (u.get("unit_type") or u"") in et.RECEIPT_KINDS]
        except Exception as exc:                            # noqa: BLE001
            logger.warning("receipt thermometers: %s", exc)
            return []

    def value(self, name, default=u""):
        f = self.request.form
        return f.get(name, default) if self.errors else default

    def now_local(self):
        return datetime.utcnow().strftime("%Y-%m-%dT%H:%M")

    # ── scan (paper CoC) ──────────────────────────────────────────────────

    def _scan(self):
        rec = self.record()
        upload = self.request.form.get("scan")
        if not hasattr(upload, "read"):
            self.errors.append(u"Choose the scan of the paper CoC.")
            return
        data = upload.read()
        if not data:
            self.errors.append(u"The scan is empty.")
            return
        ext = os.path.splitext(getattr(upload, "filename", "") or "")[1].lower() or ".pdf"
        if ext not in (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"):
            self.errors.append(u"A scan is a PDF or an image.")
            return
        folder = os.path.join(SCAN_DIR, re.sub(r"[^\w\-]", "_", rec["number"]))
        if not os.path.isdir(folder):
            os.makedirs(folder)
        n = len([x for x in os.listdir(folder) if x.startswith("scan")]) + 1
        path = os.path.join(folder, "scan_%d%s" % (n, ext))
        with open(path + ".tmp", "wb") as fh:
            fh.write(data)
        os.rename(path + ".tmp", path)
        at, by = _now(), self.user_name()
        rec["scan"] = {"filename": getattr(upload, "filename", "") or os.path.basename(path),
                       "path": path, "by": by, "at": at}
        if rec.get("origin") == cr.PAPER and rec.get("samples"):
            rec["transcribed"] = rec.get("transcribed") or {"by": by, "at": at}
        rec["log"].append({"at": at, "by": by, "what": u"scan attached", "before": None,
                           "after": rec["scan"]["filename"], "reason": u""})
        cr.save(api.get_portal(), rec)
        self.done = u"Scan attached."

    # ── receive ───────────────────────────────────────────────────────────

    def _receipt_from_form(self):
        from senaite.pfas import facility_qc as fq
        from senaite.pfas import receipt_temperature as rt
        f = self.request.form
        received_at = (f.get("received_at") or u"").strip()
        therm = None
        uid = (f.get("thermometer") or u"").strip()
        if uid:
            therm = rt.freeze(fq.get_unit(uid), fq.current_correction(uid, received_at[:10]),
                              received_at[:10])
        temps = []
        for s in self.samples():
            obs = (f.get(u"t__%s" % s["uid"]) or u"").strip()
            if obs:
                temps.append({"sample_id": s["id"], "observed": obs,
                              "corrected": rt.corrected(obs, therm), "range": s["range"],
                              "same_day": bool(s["sampled"]) and s["sampled"][:10] == received_at[:10]})
        blank = (f.get("temp_blank") or u"").strip()
        if blank:
            temps.append({"sample_id": u"temperature blank", "observed": blank,
                          "corrected": rt.corrected(blank, therm)})
        return {"received_by": self.user_name(), "received_at": received_at.replace(u"T", u" "),
                "thermometer": therm, "temperatures": [t["observed"] for t in temps],
                "readings": temps,
                "seals_intact": _yesno(f.get("seals_intact")),
                "labels_legible": _yesno(f.get("labels_legible")),
                "holding_time_ok": _yesno(f.get("holding_time_ok")),
                "compliant": _yesno(f.get("compliant")),
                "on_ice": f.get("on_ice") == u"on",
                "note": (f.get("note") or u"").strip()}

    def _receive(self):
        rec = self.record()
        if rec.get("status") == cr.RECEIVED:
            self.errors.append(u"This CoC was received already.")
            return
        if not rec.get("samples"):
            self.errors.append(u"The CoC has no samples yet: enter or transcribe them first.")
            return
        receipt = self._receipt_from_form()
        if receipt["thermometer"] is None:
            self.errors.append(u"Choose the receipt thermometer.")
        # each sample's corrected temperature against its method's range
        temp_flags, not_judged = cr.judge_temperatures(
            [t for t in receipt["readings"] if t.get("sample_id") != u"temperature blank"],
            receipt["on_ice"])
        receipt["not_judged"] = not_judged
        blocking, flags = cr.receipt_problems(rec, receipt, temp_flags)
        if blocking:
            self.errors.append(u"Not received yet. Give: " + u"; ".join(blocking) + u".")
        if self.errors:
            return
        receipt["flags"] = flags
        from bika.lims.workflow import doActionFor
        when = DateTime(receipt["received_at"])
        for s in self.samples():
            sample = api.get_object_by_uid(s["uid"])
            if api.get_review_status(sample) in ("sample_due", "to_be_sampled", "scheduled_sampling"):
                doActionFor(sample, "receive")
            if api.get_review_status(sample) == "sample_received":
                sample.setDateReceived(when)
                sample.reindexObject()
            else:
                self.errors.append(u"%s could not be received (%s)." % (s["id"], s["state"]))
        at, by = _now(), self.user_name()
        # one SENAITE Batch per CoC: the client-facing container, so its
        # samples get an EDD and project links like batched samples
        # (live tier finding F13)
        try:
            batch = ensure_coc_batch(rec, [api.get_object_by_uid(s["uid"]) for s in self.samples()])
            rec["batch_uid"] = api.get_uid(batch)
        except Exception as exc:                            # noqa: BLE001
            logger.error("CoC %s: no batch: %s", rec.get("number"), exc)
            self.errors.append(u"Received, but the CoC's batch could not be made: %s" % exc)
        rec["receipt"] = receipt
        rec["status"] = cr.RECEIVED
        last = (rec.get("transfers") or [{}])[-1] if rec.get("transfers") else None
        if last is not None and not last.get("received_by"):
            last.update(received_by=by, received_at=receipt["received_at"])
        else:
            rec.setdefault("transfers", []).append({"relinquished_by": rec.get("carrier") or
                                                    (u"see paper CoC" if rec.get("origin") == cr.PAPER else u""),
                                                    "relinquished_at": u"", "received_by": by,
                                                    "received_at": receipt["received_at"]})
        if rec.get("origin") == cr.PAPER and not rec.get("transcribed"):
            rec["transcribed"] = {"by": by, "at": at}
        rec["log"].append({"at": at, "by": by, "what": u"received", "before": None,
                           "after": u"; ".join(flags) or u"compliant", "reason": receipt["note"]})
        if flags:
            told = self._tell_client(rec, flags, receipt["note"])
            rec["log"].append({"at": at, "by": by, "what": u"client told", "before": None,
                               "after": told, "reason": u""})
        cr.save(api.get_portal(), rec)
        self.done = ((u"Received, flagged: " + u"; ".join(flags)) if flags else u"Received.") + (
            (u" Not judged: " + u"; ".join(not_judged) + u".") if not_judged else u"")

    def _tell_client(self, rec, flags, note):
        """Email the samples' contact a non-compliant receipt, through
        SENAITE's mail settings. Returns what happened, for the log -- a
        failure is said, never hidden."""
        from bika.lims.api import mail
        sample = api.get_object_by_uid((rec.get("samples") or [u""])[0], None)
        contact = sample.getContact() if sample is not None else None
        to = contact.getEmailAddress() if contact is not None else u""
        if not to:
            return u"not emailed: the client contact has no email address; tell them directly"
        lab = api.get_bika_setup().laboratory
        sender = lab.getEmailAddress() or api.get_portal().getProperty("email_from_address") or u""
        body = (u"Chain of custody %s was received by the laboratory on %s and is not "
                u"compliant: %s.\n\n%s\n\nThe samples are held as received with this note."
                % (rec["number"], (rec.get("receipt") or {}).get("received_at") or u"",
                   u"; ".join(flags), note))
        try:
            email = mail.compose_email(mail.to_email_address(sender, lab.getName()),
                                       mail.to_email_address(to, contact.getFullname()),
                                       u"Chain of custody %s: received not compliant" % rec["number"], body)
            ok = mail.send_email(email)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coc %s: client email failed: %s", rec["number"], exc)
            ok = False
        return (u"emailed %s" % to) if ok else (u"email to %s could not be sent; tell them directly" % to)
