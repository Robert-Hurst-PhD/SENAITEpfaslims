# -*- coding: utf-8 -*-
"""@@pfas-coc-receive?coc=COC-…: the laboratory receives a CoC.
Lab staff only.

Records the receipt date and time, labels, compliance and a note; where a
sample's method sets a receipt temperature range, the receipt thermometer
with its correction frozen (receipt_temperature), that sample's temperature
(observed and corrected) and whether the shipment came on ice; where a
sample's method sets a holding time, whether it is within it
(coc_records.asked_checks); and -- for a paper CoC -- the scan of the
returned copy and who transcribed it. Completing receipt runs SENAITE's
receive transition on every sample of the CoC with the entered receipt
time. A non-compliant answer is received with a note and flagged; receipt
is refused while anything is unanswered (coc_records.receipt_problems).

A received CoC's receipt date is corrected here by a signed correction
(action=correct_date, coc_records.correction_problems): the receipt keeps
the date it was received with, the correction gives the date in force, and
every sample of the CoC takes it as its date received. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import logging
import os
import re
from datetime import datetime

from bika.lims import api
from DateTime import DateTime
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import coc_records as cr
from senaite.pfas import lab_time
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
    # samples put in by their field raise no event: a project-linked batch
    # gets its resolved criteria file after the commit here
    try:
        from senaite.pfas import project_ref
        project_ref.schedule_first_export(batch)
    except Exception:                                       # noqa: BLE001
        logger.warning("resolved criteria not scheduled for %r", batch, exc_info=True)
    return batch


def set_samples_received(rec):
    """Every sample of the CoC takes the receipt date in force as its date
    received (core DateReceived, read by the certificate and the EDD),
    typed on the laboratory's clock."""
    at = cr.received_in_force(rec)
    if not at:
        return
    when = lab_time.typed(at) or DateTime(at)
    for uid in rec.get("samples") or []:
        sample = api.get_object_by_uid(uid, None)
        if sample is not None:
            sample.setDateReceived(when)
            sample.reindexObject()


def withdraw_signed(portal, number, seq, by, at, reason, cache_rows=()):
    """The signature (ledger row `seq`) on a correction of CoC `number`'s
    receipt date was withdrawn: the correction is withdrawn, the receipt
    date in force returns to the one before it and every sample of the CoC
    takes it. Returns [number] when a correction changed; a correction
    already withdrawn is kept as it is, so a retried withdrawal changes
    nothing twice."""
    rec = cr.load(portal, number)
    if rec is None or not cr.withdraw_correction(rec, seq, by, at, reason, cache_rows):
        return []
    cr.save(portal, rec)
    set_samples_received(rec)
    return [number]


logger = logging.getLogger("senaite.pfas.coc_receive")

SCAN_DIR = os.environ.get("PFAS_COC_SCAN_DIR", "/data/coc_scans")


def _now():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")


def _yesno(v):
    """A Yes / No answer; N/A is not offered, and posted is unanswered."""
    return cr.check_answer(v, na=False)


NO_RANGE = u"no receipt range on its method"


def not_judged_line(items, samples, title_of, url_of):
    """The amber line for a receipt's unjudged temperatures, or None.

    `items`: the receipt's not_judged entries ("<sample id>: <reason>",
    coc_records.judge_temperatures); `samples`: the receive page's sample
    rows (id, method_id); title_of(method id) and url_of(method id) name a
    method and where its receipt range is set. A sample whose method is not
    identified gets no button."""
    unset, other = [], []
    for item in items or []:
        sid, _sep, why = (u"%s" % item).partition(u": ")
        if why == NO_RANGE:
            unset.append(sid)
        else:
            other.append(u"%s" % item)
    if not unset and not other:
        return None
    by_id = dict((s.get("id"), s.get("method_id")) for s in samples or [])
    mids = []
    for sid in unset:
        mid = by_id.get(sid)
        if mid and mid not in mids:
            mids.append(mid)
    return {"unset": unset, "other": other,
            "methods": [{"title": title_of(m), "url": url_of(m)} for m in mids]}


class PFASCoCReceiveView(ViewHelpers, BrowserView):
    template = ViewPageTemplateFile("templates/coc_receive.pt")

    def __call__(self):
        flatten_form(self.request)
        # receiving and correcting change records: only a role that may
        # change records does either, never the read-only inspector
        from senaite.pfas.browser.perms import may_write, refuse
        if not may_write(api.get_portal()):
            return refuse(self.request, u"Receipt is recorded by laboratory staff who may change records.")
        self.errors, self.done = [], u""
        if self.request.method == "POST" and self.record() is not None:
            action = self.request.form.get("action")
            if action == "scan":
                self._scan()
            elif action == "receive":
                self._receive()
            elif action == "correct_date":
                self._correct_date()
        return self.template()

    def record(self):
        if not hasattr(self, "_rec"):
            num = (self.request.form.get("coc") or u"").strip()
            self._rec = cr.load(api.get_portal(), num) if num else None
        return self._rec

    def user_name(self):
        user = api.get_current_user()
        return user.getProperty("fullname") or user.getId()

    def samples(self):
        if getattr(self, "_samples", None) is not None:
            return self._samples
        out = []
        for uid in (self.record() or {}).get("samples") or []:
            s = api.get_object_by_uid(uid, None)
            if s is not None:
                mid = self._profile_id(s)
                matrix = s.getSampleTypeTitle() or u""
                rng = self._range(s, mid, matrix)
                out.append({"uid": uid, "id": s.getId(), "csid": s.getClientSampleID() or u"",
                            "matrix": matrix,
                            # what its method sets decides what is asked; a
                            # sample whose method is not identified, or whose
                            # setting cannot be read, is asked everything
                            "temperature": rng is None or cr.range_is_set(rng),
                            "holding": mid is None or self._sets_holding(mid, matrix),
                            "sampled": self.lab_at(s.getDateSampled(), s.getDateSampled().strftime("%Y-%m-%d %H:%M"))
                            if s.getDateSampled() else u"",
                            "sampled_at": s.getDateSampled(),
                            "state": self.state_title(s), "range": rng, "method_id": mid,
                            "range_text": self._range_text(rng)})
        self._samples = out
        return out

    @staticmethod
    def state_title(sample):
        """The sample's workflow state as its title, read now."""
        state = api.get_review_status(sample)
        try:
            title = api.get_tool("portal_workflow").getTitleForStateOnType(state, sample.portal_type)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("state title of %s: %s", sample.getId(), exc)
            title = None
        return (title or state or u"").strip()

    @staticmethod
    def recorded_temperature(rec, sample_id):
        """The temperature the receipt recorded for a sample, observed and
        corrected."""
        for t in ((rec or {}).get("receipt") or {}).get("readings") or []:
            if t.get("sample_id") == sample_id:
                corrected = t.get("corrected")
                return u"%s \u00b0C" % t.get("observed") + (
                    u", corrected %s \u00b0C" % corrected if corrected is not None else u"")
        return u"\u2014"

    @staticmethod
    def verdict(receipt):
        """The recorded receipt in words (coc_records.receipt_verdict)."""
        return cr.receipt_verdict(receipt)

    @staticmethod
    def _profile_id(sample):
        """The method profile the sample is analysed by, or None when its
        method is not identified."""
        from senaite.pfas import sample_method
        from senaite.pfas.method_bridge import profile_id_for_method
        try:
            method, _why = sample_method.identify(sample)
            return profile_id_for_method(method) if method is not None else None
        except Exception as exc:                            # noqa: BLE001
            logger.warning("method of %s: %s", sample.getId(), exc)
            return None

    def asked(self):
        """The checks this receipt asks (coc_records.asked_checks)."""
        return cr.asked_checks(self.samples())

    def asks_temperature(self):
        return cr.TEMPERATURE in self.asked()

    def receipt_checks(self):
        """[(key, label)] of the Yes / No checks this receipt asks, in the
        order they are drawn."""
        asked = self.asked()
        return [(k, label) for k, label in (("on_ice", u"Received on ice"), ("labels_legible", u"Labels legible"),
                                            ("holding_time_ok", u"Within holding time"),
                                            ("compliant", u"Compliant overall")) if k in asked]

    @staticmethod
    def _sets_holding(mid, matrix):
        """The method sets a holding time in days for this matrix
        (holding_time.limit_for); a method that sets none, or has none
        entered, is not asked."""
        from senaite.pfas import holding_time
        from senaite.pfas.method_profile_store import get_profile
        try:
            limit = holding_time.limit_for(get_profile(api.get_portal(), mid), matrix)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("holding time of %s for %s: %s", mid, matrix, exc)
            return True
        return limit is not None and limit != holding_time.NONE_SET

    def _range(self, sample, mid, matrix=None):
        """The receipt range of the sample's matrix on its method: what the
        matrix sets for itself over All matrices, same-day on ice included
        (matrix_temperature.receipt_range); None when its method is not
        identified."""
        from senaite.pfas import matrix_temperature
        from senaite.pfas.method_profile_store import get_profile
        try:
            return matrix_temperature.receipt_range(get_profile(api.get_portal(), mid), matrix) if mid else None
        except Exception as exc:                            # noqa: BLE001
            logger.warning("receipt range for %s: %s", sample.getId(), exc)
            return None

    def not_judged(self):
        """The received CoC's temperatures nobody judged, as the amber line
        under the receipt says them, or None: {"unset": the samples whose
        method sets no receipt range, "other": any other reason in the
        receipt's words, "methods": [{"title", "url"}] where each of those
        methods' range is set}. Read from the stored receipt, so it shows on
        every later visit; a received temperature is never shown as judged."""
        rc = (self.record() or {}).get("receipt") or {}
        return not_judged_line(rc.get("not_judged"), self.samples(), self._method_title,
                               self.range_url)

    @staticmethod
    def _method_title(mid):
        from senaite.pfas.method_profile_store import get_profile
        try:
            return get_profile(api.get_portal(), mid).get("display_name") or mid
        except Exception:                                   # noqa: BLE001
            return mid

    def range_url(self, mid):
        """Where a method's receipt range is set: its section on the method
        profile's Matrices tab (the address site search gives it)."""
        from senaite.pfas import site_search as ss
        edit = u"%s/@@pfas-method-profile-edit?method_id=%s" % (self.portal_url(), mid)
        return ss._link(edit, ss.pane_for(u"rtemp"), s=u"rtemp")

    def may_set_range(self):
        """Only the people who edit method profiles open the setting."""
        from senaite.pfas.browser.perms import require_manager
        return require_manager(api.get_portal())

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
        """The "Received at" pre-fill: now on the laboratory's clock."""
        return lab_time.now().strftime("%Y-%m-%dT%H:%M")

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
        """The receipt as entered: a check this receipt does not ask, and
        the temperatures where none are asked, are left out."""
        from senaite.pfas import facility_qc as fq
        from senaite.pfas import receipt_temperature as rt
        f = self.request.form
        received_at = (f.get("received_at") or u"").strip()
        asked = self.asked()
        out = {"received_by": self.user_name(), "received_at": received_at.replace(u"T", u" "),
               "note": (f.get("note") or u"").strip()}
        for key in ("labels_legible", "holding_time_ok", "compliant", "on_ice"):
            if key in asked:
                out[key] = _yesno(f.get(key))
        if cr.TEMPERATURE not in asked:
            return out
        therm = None
        uid = (f.get("thermometer") or u"").strip()
        if uid:
            therm = rt.freeze(fq.get_unit(uid), fq.calibration(uid, received_at[:10]),
                              received_at[:10])
        temps = []
        for s in self.samples():
            obs = (f.get(u"t__%s" % s["uid"]) or u"").strip() if s.get("temperature") else u""
            if obs:
                temps.append({"sample_id": s["id"], "observed": obs,
                              "corrected": rt.corrected(obs, therm), "range": s["range"],
                              "same_day": self._same_day(s.get("sampled_at"), received_at)})
        blank = (f.get("temp_blank") or u"").strip()
        if blank:
            temps.append({"sample_id": u"temperature blank", "observed": blank,
                          "corrected": rt.corrected(blank, therm)})
        out.update(thermometer=therm, temperatures=[t["observed"] for t in temps], readings=temps)
        return out

    @staticmethod
    def _same_day(sampled_at, received_at):
        """Collected and received on the same laboratory day; the receipt
        time is typed on the laboratory's clock."""
        if not sampled_at:
            return False
        day = lab_time.lab_date(sampled_at)
        return day is not None and day == lab_time.lab_date(received_at, "lab")

    def _receive(self):
        rec = self.record()
        if rec.get("status") == cr.RECEIVED:
            self.errors.append(u"This CoC was received already.")
            return
        if not rec.get("samples"):
            self.errors.append(u"The CoC has no samples yet: enter or transcribe them first.")
            return
        receipt = self._receipt_from_form()
        asked = self.asked()
        if cr.TEMPERATURE in asked and receipt.get("thermometer") is None:
            self.errors.append(u"Choose the receipt thermometer.")
        # each sample's corrected temperature against its matrix's range on its method
        temp_flags, not_judged = cr.judge_temperatures(
            [t for t in receipt.get("readings") or [] if t.get("sample_id") != u"temperature blank"],
            receipt.get("on_ice") is True)
        receipt["not_judged"] = not_judged
        blocking, flags = cr.receipt_problems(rec, receipt, temp_flags, asked=asked)
        if blocking:
            self.errors.append(u"Not received yet. Give: " + u"; ".join(blocking) + u".")
        if self.errors:
            return
        receipt["flags"] = flags
        from bika.lims.workflow import doActionFor
        # typed on the laboratory's clock
        when = lab_time.typed(receipt["received_at"]) or DateTime(receipt["received_at"])
        for s in self.samples():
            sample = api.get_object_by_uid(s["uid"])
            if api.get_review_status(sample) in ("sample_due", "to_be_sampled", "scheduled_sampling"):
                doActionFor(sample, "receive")
            if api.get_review_status(sample) == "sample_received":
                sample.setDateReceived(when)
                sample.reindexObject()
            else:
                self.errors.append(u"%s could not be received (%s)."
                                   % (s["id"], self.state_title(sample)))
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
                           "after": cr.receipt_verdict(receipt), "reason": receipt["note"]})
        # a compliance sample received out of compliance with its method is
        # held from publishing and resampled (receipt_compliance)
        resample = self._resample_ids(flags)
        if resample:
            rec["resample"] = {"samples": resample, "requested_at": at, "by": by}
            rec["log"].append({"at": at, "by": by, "what": u"resample requested", "before": None,
                               "after": u", ".join(resample), "reason": u""})
        if flags:
            told = self._tell_client(rec, flags, receipt["note"], resample)
            rec["log"].append({"at": at, "by": by, "what": u"client told", "before": None,
                               "after": told, "reason": u""})
        cr.save(api.get_portal(), rec)
        self._samples = None            # the samples now stand in their new state
        # what was not judged is its own amber line (not_judged), never part
        # of the confirmation
        self.done = (u"Received, flagged: " + u"; ".join(flags)) if flags else u"Received."

    # ── a signed correction of the receipt date ───────────────────────────

    def received_in_force(self):
        """The receipt date in force (coc_records.received_in_force)."""
        return cr.received_in_force(self.record())

    def corrections(self):
        """The receipt date's corrections, oldest first, each with its line
        in words and its signature as signed: {"label" (the first row's
        heading), "line", "state", "signed"}."""
        out = []
        for c in cr.corrections(self.record()):
            sig = next((x for x in c.get("signatures") or [] if x.get("meaning") == cr.RECEIPT_MEANING), {})
            out.append({"label": u"" if out else u"Correction", "line": cr.correction_line(c),
                        "state": c.get("state"),
                        "signed": u"%s, %s" % (sig.get("fullname") or sig.get("signer") or u"",
                                               self._signed_at(sig.get("signed_at"))) if sig else u""})
        return out

    @staticmethod
    def _signed_at(value):
        try:
            return lab_time.show(value, "utc")
        except Exception:                                   # noqa: BLE001
            return value or u""

    def _correct_date(self):
        """Correct the receipt date with the corrector's e-signature: the
        date in force moves, the date received is kept, and every sample
        of the CoC takes the new date as its date received."""
        from senaite.pfas.esig import ledger, signing
        rec, f = self.record(), self.request.form
        new_at = (f.get("corrected_at") or u"").strip()
        reason = (f.get("correction_reason") or u"").strip()
        collected = [(s["id"], s.get("sampled") or u"") for s in self.samples()]
        problems = cr.correction_problems(rec, new_at, reason, self.now_local().replace(u"T", u" "),
                                          collected)
        if problems:
            self.errors.append(u"Not corrected. " + u" ".join(problems))
            return
        portal = api.get_portal()
        entry = cr.new_correction(rec, new_at, reason, signing.current_userid(self.request),
                                  self.user_name(), _now())
        record_hash = cr.correction_hash(rec, entry)
        try:
            row = signing.sign(portal, self.request, cr.RECEIPT_KIND, rec["number"], cr.RECEIPT_REVISION,
                               record_hash, cr.RECEIPT_MEANING, note=reason)
        except (signing.SignatureRefused, ledger.LedgerError) as exc:
            self.errors.append(u"Not corrected: " + signing.reason(exc))
            return
        cr.add_correction(rec, entry, {"seq": row["seq"], "hash": row["hash"], "record_hash": record_hash},
                          signing.cache([row]))
        cr.save(portal, rec)
        set_samples_received(rec)
        self._samples = None
        self.done = u"Receipt date corrected to %s." % entry["to"]

    def _resample_ids(self, flags):
        """The compliance samples this receipt breaches the method for."""
        from senaite.pfas import receipt_compliance as rc
        out = []
        for s in self.samples():
            sample = api.get_object_by_uid(s["uid"])
            fld = sample.getField("ComplianceSample")
            found = rc.breaches(flags, (s["id"], sample.getClientSampleID()))
            if rc.resample_required(fld.get(sample) if fld else False, found):
                out.append(s["id"])
        return out

    def _tell_client(self, rec, flags, note, resample=()):
        """Email the samples' contact a non-compliant receipt, through
        SENAITE's mail settings. Returns what happened, for the log -- a
        failure is said, never hidden."""
        from bika.lims.api import mail
        sample = api.get_object_by_uid((rec.get("samples") or [u""])[0], None)
        contact = sample.getContact() if sample is not None else None
        to = contact.getEmailAddress() if contact is not None else u""
        if not to:
            return u"not emailed: the client contact has no email address; tell them directly"
        from senaite.pfas import lab_identity
        lab = api.get_bika_setup().laboratory
        sender = lab.getEmailAddress() or api.get_portal().getProperty("email_from_address") or u""
        body = (u"Chain of custody %s was received by the laboratory on %s and is not "
                u"compliant: %s.\n\n%s\n\nThe samples are held as received with this note."
                % (rec["number"], (rec.get("receipt") or {}).get("received_at") or u"",
                   u"; ".join(flags), note))
        if resample:
            body += (u"\n\nThese compliance samples cannot be reported and must be resampled: %s."
                     % u", ".join(resample))
        try:
            email = mail.compose_email(mail.to_email_address(sender, lab_identity.lab_name()),
                                       mail.to_email_address(to, contact.getFullname()),
                                       u"Chain of custody %s: received not compliant" % rec["number"], body)
            ok = mail.send_email(email)
        except Exception as exc:                            # noqa: BLE001
            logger.warning("coc %s: client email failed: %s", rec["number"], exc)
            ok = False
        return (u"emailed %s" % to) if ok else (u"email to %s could not be sent; tell them directly" % to)
