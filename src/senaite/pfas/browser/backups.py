# -*- coding: utf-8 -*-
"""@@pfas-backups: the backups of the system.

What the backup tool (tools/backup/pfasbackup.py) recorded: each backup,
restore and restore test (backup_log), the destination and the public key
fingerprints of its last run, and what needs attention (a failed backup, the
quarterly restore test due). And a partial restore of one method's
configuration: a key holder's decrypted method bundle is uploaded, its
before/after shown, and applied with a reason (method_restore), each part
through its store's tracked saver. Uploading and applying are a site
administrator's.
"""
from __future__ import absolute_import

import json
import logging

from bika.lims import api
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_SITE_ADMIN, GateMixin, deny_gated_action
from senaite.pfas.browser.view_helpers import ViewHelpers

logger = logging.getLogger("senaite.pfas.backups")

BACKUP_GATES = {"upload_bundle": TIER_SITE_ADMIN, "apply_restore": TIER_SITE_ADMIN,
                "save_setting": TIER_SITE_ADMIN, "withdraw_setting": TIER_SITE_ADMIN}
STATUS_KEY = "senaite.pfas.backup_status"
PENDING_KEY = "senaite.pfas.method_restore_pending"
MESSAGES = {"uploaded": u"Bundle read: check the changes, then apply.",
            "applied": u"Method restored.", "refused": u"Not done",
            "setting": u"Saved: the backup tool applies it at its next run.",
            "withdrawn": u"The change is withdrawn."}


class PFASBackupsView(ViewHelpers, GateMixin, BrowserView):
    template = ViewPageTemplateFile("templates/backups.pt")

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        if req.method == "POST":
            action = req.form.get("action", "")
            denied = deny_gated_action(self.context, req, action, BACKUP_GATES)
            if denied is not None:
                return denied
            from senaite.pfas.browser.perms import disable_csrf
            disable_csrf(req)
            if action == "upload_bundle":
                return self._upload_bundle()
            if action == "apply_restore":
                return self._apply_restore()
            if action == "save_setting":
                return self._save_setting()
            if action == "withdraw_setting":
                return self._withdraw_setting()
        return self.template()

    def _back(self, msg, detail=u"", bundle=u""):
        from six.moves.urllib.parse import urlencode
        q = {"msg": msg}
        if detail:
            q["detail"] = detail.encode("utf-8") if not isinstance(detail, str) else detail
        if bundle:
            q["bundle"] = bundle
        self.request.response.redirect("%s/@@pfas-backups?%s" % (self.portal_url(), urlencode(q)))
        return u""

    def message(self):
        msg = self.request.form.get("msg")
        if msg not in MESSAGES:
            return None
        detail = self.request.form.get("detail") or u""
        return {"ok": msg != "refused",
                "text": MESSAGES[msg] + (u": %s" % detail if detail else u"")}

    # ── what was recorded ────────────────────────────────────────────────
    def events(self):
        from senaite.pfas import backup_log
        return list(reversed(backup_log.load(api.get_portal())))[:50]

    def summary(self):
        from senaite.pfas import backup_log
        return backup_log.summary(backup_log.load(api.get_portal()), lab_time.today().isoformat())

    def status(self):
        """The backup tool's last report: destination, free space, the
        public key fingerprints, the timers."""
        from senaite.pfas.annotation_store import read_json
        return read_json(api.get_portal(), STATUS_KEY, {})

    # ── levels and the current chain ─────────────────────────────
    def level_rows(self):
        from senaite.pfas import backup_log
        return backup_log.LEVEL_ROWS

    def level_label(self, event):
        from senaite.pfas import backup_log
        if not hasattr(self, "_all_events"):
            self._all_events = backup_log.load(api.get_portal())
        return backup_log.level_label(event, self._all_events)

    # ── settings set here, applied by the tool ────────────
    def settings_state(self):
        if not hasattr(self, "_settings"):
            from senaite.pfas import backup_settings as bs
            state = bs.load(api.get_portal())
            if not state.get("current") and self.status():
                state = bs.from_status(state, self.status())
            self._settings = state
        return self._settings

    def setting_rows(self):
        from senaite.pfas import backup_settings as bs
        cur = self.settings_state().get("current") or {}
        waiting = dict((c["setting"], c) for c in bs.waiting(self.settings_state()))
        return [{"key": k, "label": label, "value": bs.describe(k, cur.get(k)), "raw": cur.get(k),
                 "waiting": bs.describe(k, waiting[k]["after"]) if k in waiting else u""}
                for k, label in bs.SETTINGS]

    def days(self):
        from senaite.pfas import backup_settings as bs
        return bs.DAYS

    def changes(self):
        from senaite.pfas import backup_settings as bs
        out = []
        for c in reversed(self.settings_state().get("changes") or []):
            state = {"waiting": u"Applies at the next run", "applied": u"Applied", "refused": u"Refused",
                     "withdrawn": u"Withdrawn", "replaced": u"Replaced by a later change"}.get(c["state"], c["state"])
            before = bs.describe(c["setting"], c.get("before")) if c.get("before") not in (None, u"") else u""
            change = u"%s%s \u2192 %s" % (bs.LABEL.get(c["setting"], c["setting"]), u" " + before if before else u"",
                                         bs.describe(c["setting"], c.get("after")))
            out.append(dict(c, change=change, state_label=state))
        return out

    def settings_line(self):
        """Saved when and by whom, applied when, what waits."""
        from senaite.pfas import backup_settings as bs
        ch = self.settings_state().get("changes") or []
        if not ch:
            return u""
        last = ch[-1]
        applied = [c for c in ch if c.get("state") == u"applied"]
        n = len(bs.waiting(self.settings_state()))
        parts = [u"Saved %s by %s" % (self.lab_at(last.get("at"), last.get("at")), last.get("by"))]
        if applied:
            parts.append(u"applied %s" % applied[-1].get("applied_at"))
        if n:
            parts.append(u"%d change%s at the next run" % (n, u" applies" if n == 1 else u"s apply"))
        return u" \u00b7 ".join(parts)

    def _save_setting(self):
        from senaite.pfas import backup_settings as bs
        f = self.request.form
        key = f.get("setting") or u""
        if key == u"prune":
            value = {"days": [d for d in bs.DAYS if f.get(u"prune.%s" % d)], "at": (f.get("prune_at") or u"").strip()}
        elif key == u"recipients":
            value = []
            for i in sorted(set(int(k.split(u".")[1]) for k in f if k.startswith(u"key.") and k.split(u".")[1].isdigit())):
                fpr = (f.get(u"key.%d.fpr" % i) or u"").strip().replace(u" ", u"").upper()
                if not fpr:
                    continue
                k = {"fpr": fpr, "holder": (f.get(u"key.%d.holder" % i) or u"").strip()}
                if (f.get(u"key.%d.key" % i) or u"").strip():
                    k["key"] = f.get(u"key.%d.key" % i).strip()
                value.append(k)
        else:
            value = (f.get("value") or u"").strip()
        who = api.get_current_user().getId()
        from datetime import datetime
        state, error = bs.request(self.settings_state(), key, value, f.get("reason") or u"", who,
                                  datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
        if error:
            return self._back("refused", error)
        bs.save(api.get_portal(), state)
        return self._back("setting")

    def _withdraw_setting(self):
        from senaite.pfas import backup_settings as bs
        from datetime import datetime
        state, error = bs.withdraw(self.settings_state(), self.request.form.get("change") or u"",
                                   api.get_current_user().getId(), datetime.utcnow().strftime("%Y-%m-%d %H:%M"))
        if error:
            return self._back("refused", error)
        bs.save(api.get_portal(), state)
        return self._back("withdrawn")

    # ── a method restore ─────────────────────────────────────────────────
    def _pending_store(self, create=True):
        from senaite.pfas.annotation_store import mapping
        return mapping(api.get_portal(), PENDING_KEY, create)

    def _upload_bundle(self):
        from senaite.pfas import method_restore as mr
        upload = self.request.form.get("bundle")
        try:
            raw = upload.read() if hasattr(upload, "read") else (upload or b"")
            bundle = mr.check_bundle(json.loads(raw))
        except ValueError as exc:
            return self._back("refused", u"%s" % exc)
        if bundle["bundle_id"] in mr.applied(api.get_portal()):
            return self._back("refused", u"This bundle was already applied.")
        store = self._pending_store()
        store.clear()
        store[bundle["bundle_id"]] = json.dumps(bundle)
        return self._back("uploaded", bundle=bundle["bundle_id"])

    def pending(self):
        bid = self.request.form.get("bundle") or u""
        raw = self._pending_store(create=False).get(bid) if bid else None
        return json.loads(raw) if raw else None

    def plan_rows(self):
        """The changes the pending bundle would make, one row per path."""
        from senaite.pfas import method_restore as mr
        bundle = self.pending()
        if bundle is None:
            return []
        current = mr.current_of(api.get_portal(), bundle["method_id"], bundle)
        rows = []
        for part in mr.plan(bundle, current):
            for path, before, after in part["changes"]:
                rows.append({"part": part["part"].replace(u"_", u" "), "key": part["key"],
                             "path": u" › ".join(u"%s" % p for p in path) or u"—",
                             "before": self._short(before), "after": self._short(after)})
        return rows

    @staticmethod
    def _short(value):
        text = u"—" if value is None else (
            value if isinstance(value, type(u"")) else json.dumps(value, sort_keys=True))
        return text if len(text) <= 120 else text[:117] + u"…"

    def _apply_restore(self):
        from AccessControl import getSecurityManager
        from senaite.pfas import backup_log
        from senaite.pfas import method_restore as mr
        portal = api.get_portal()
        bundle = self.pending()
        if bundle is None:
            return self._back("refused", u"Upload the bundle again.")
        who = getSecurityManager().getUser().getId()
        reason = (self.request.form.get("reason") or u"").strip()
        try:
            out = mr.apply(bundle, mr.current_of(portal, bundle["method_id"], bundle), reason, who,
                           mr.zope_savers(portal), mr.applied(portal))
        except ValueError as exc:
            return self._back("refused", u"%s" % exc, bundle=bundle["bundle_id"])
        backup_log.record(portal, {"kind": "method_restore", "status": "ok", "who": who,
                                   "point": bundle.get("point"), "ended": out["at"].replace(u" ", u"T"),
                                   "note": u"%s: %d part(s); %s" % (bundle["method_id"], out["parts"], reason)})
        self._pending_store().clear()
        return self._back("applied", u"%s, %d part(s)" % (bundle["method_id"], out["parts"]))
