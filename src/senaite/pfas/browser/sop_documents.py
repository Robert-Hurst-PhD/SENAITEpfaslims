from __future__ import print_function
import json
import logging
import os
import re
from datetime import datetime, date

from AccessControl import getSecurityManager
from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from zope.annotation.interfaces import IAnnotations

logger = logging.getLogger("senaite.pfas.sop")

_ANN_REGISTRY  = u"senaite.pfas.sop.registry"
_ANN_REVISIONS = u"senaite.pfas.sop.{sop_id}.revisions"
_ANN_SIGNOFFS  = u"senaite.pfas.sop.{sop_id}.signoffs"

SOP_DIR = os.environ.get("PFAS_SOP_DIR", "/data/sops")

RISK_COLOURS = {
    "green":  range(1, 5),    # 1-4
    "yellow": range(5, 10),   # 5-9
    "orange": range(10, 15),  # 10-14
    "red":    range(15, 26),  # 15-25
}

# Legacy SOP method slugs (what existing SOP records are stored under) mapped to
# the canonical method id. The slug VALUES stay stable for backward compat, but
# the option LIST is derived from the single-source method registry
# (analyte_reference.get_method_ids) so a newly-added method appears
# automatically instead of being frozen here.
_METHOD_ID_TO_SLUG = {
    "FDA_32PFAS": "fda",
    "EPA_537_1":  "epa5371",
    "EPA_1633A":  "epa1633",
}
_METHOD_SHORT_LABELS = {
    "FDA_32PFAS": "FDA 32-PFAS",
    "EPA_537_1":  "EPA 537.1",
    "EPA_1633A":  "EPA 1633A",
}


def _method_slug_label_pairs():
    """[(slug, label)] derived from the live method registry (single source)."""
    from senaite.pfas.analyte_reference import get_method_ids
    pairs = []
    for mid in get_method_ids():
        pairs.append((_METHOD_ID_TO_SLUG.get(mid, mid.lower()),
                      _METHOD_SHORT_LABELS.get(mid, mid)))
    return pairs


# slug → label, derived (kept as a module constant for the display helpers that
# resolve a stored slug back to a label). "General Lab" covers the empty slug.
METHOD_LABELS = dict(_method_slug_label_pairs())
METHOD_LABELS[None] = "General Lab"
METHOD_LABELS[""] = "General Lab"


# ── Annotation helpers ────────────────────────────────────────────────────────

def _get_registry(portal):
    ann = IAnnotations(portal)
    raw = ann.get(_ANN_REGISTRY)
    return json.loads(raw) if raw else []


def _save_registry(portal, data):
    ann = IAnnotations(portal)
    ann[_ANN_REGISTRY] = json.dumps(data)


def _rev_key(sop_id):
    return _ANN_REVISIONS.format(sop_id=sop_id)


def _sig_key(sop_id):
    return _ANN_SIGNOFFS.format(sop_id=sop_id)


def _get_revisions(portal, sop_id):
    ann = IAnnotations(portal)
    raw = ann.get(_rev_key(sop_id))
    return json.loads(raw) if raw else []


def _save_revisions(portal, sop_id, data):
    ann = IAnnotations(portal)
    ann[_rev_key(sop_id)] = json.dumps(data)


def _get_signoffs(portal, sop_id):
    ann = IAnnotations(portal)
    raw = ann.get(_sig_key(sop_id))
    return json.loads(raw) if raw else {}


def _save_signoffs(portal, sop_id, data):
    ann = IAnnotations(portal)
    ann[_sig_key(sop_id)] = json.dumps(data)


def _next_sop_id(registry):
    if not registry:
        return "SOP-001"
    nums = []
    for entry in registry:
        try:
            nums.append(int(entry["sop_id"].split("-")[1]))
        except (IndexError, ValueError):
            pass
    return "SOP-{:03d}".format(max(nums) + 1 if nums else 1)


# ── View class ────────────────────────────────────────────────────────────────

class PFASSOPView(BrowserView):

    def __call__(self):
        action = self.request.form.get("action", "")
        if self.request.method == "POST":
            if action == "upload_sop":
                return self._handle_upload()
            if action == "activate_revision":
                return self._handle_activate()
            if action == "sign_sop":
                return self._handle_sign()
        if action == "download_sop":
            return self._handle_download()
        return self.index()

    # ── Data access ──────────────────────────────────────────────────────────

    def _portal(self):
        return getToolByName(self.context, "portal_url").getPortalObject()

    def _portal_url(self):
        return getToolByName(self.context, "portal_url")()

    def _current_user(self):
        user = getSecurityManager().getUser()
        return user

    def _current_user_id(self):
        return self._current_user().getId() or ""

    def _current_user_fullname(self):
        user = self._current_user()
        portal = self._portal()
        mt = getToolByName(portal, "portal_membership", None)
        if mt:
            member = mt.getMemberById(user.getId())
            if member:
                full = member.getProperty("fullname", "")
                if full:
                    return full
        return user.getUserName() or user.getId() or "Unknown"

    def _user_roles(self):
        portal = self._portal()
        user = self._current_user()
        try:
            return list(user.getRolesInContext(portal))
        except Exception:
            return list(user.getRoles())

    def can_manage(self):
        roles = self._user_roles()
        return "LabManager" in roles or "Manager" in roles

    def portal_url(self):
        return self._portal_url()

    def list_sops(self):
        """Return all SOPs with their current revision info and sign-off counts."""
        portal = self._portal()
        registry = _get_registry(portal)
        result = []
        uid = self._current_user_id()
        for entry in registry:
            sop_id = entry["sop_id"]
            revs = _get_revisions(portal, sop_id)
            active_rev = None
            draft_revs = []
            for r in revs:
                if r.get("status") == "active":
                    active_rev = r
                elif r.get("status") == "draft":
                    draft_revs.append(r)
            sigs = _get_signoffs(portal, sop_id)
            # compute sign-off status for current rev
            if active_rev:
                rev_num = active_rev["rev_num"]
                signers = [v for v in sigs.values()
                           if v.get("rev_num") == rev_num]
                user_signed = uid in sigs and sigs[uid].get("rev_num") == rev_num
            else:
                signers = []
                user_signed = False
            result.append({
                "sop_id":       sop_id,
                "title":        entry.get("title", ""),
                "method_slug":  entry.get("method_slug") or "",
                "method_label": METHOD_LABELS.get(entry.get("method_slug"), "General Lab"),
                "category":     entry.get("category", ""),
                "description":  entry.get("description", ""),
                "status":       entry.get("status", "active"),
                "active_rev":   active_rev,
                "draft_revs":   draft_revs,
                "all_revs":     revs,
                "signer_count": len(signers),
                "user_signed":  user_signed,
            })
        return result

    def get_sop(self, sop_id):
        portal = self._portal()
        registry = _get_registry(portal)
        entry = next((e for e in registry if e["sop_id"] == sop_id), None)
        if not entry:
            return None
        revs = _get_revisions(portal, sop_id)
        sigs = _get_signoffs(portal, sop_id)
        uid = self._current_user_id()
        active_rev = next((r for r in revs if r.get("status") == "active"), None)
        rev_num = active_rev["rev_num"] if active_rev else None
        user_signed = uid in sigs and sigs[uid].get("rev_num") == rev_num
        return {
            "sop_id":      sop_id,
            "title":       entry.get("title", ""),
            "method_slug": entry.get("method_slug") or "",
            "method_label": METHOD_LABELS.get(entry.get("method_slug"), "General Lab"),
            "category":    entry.get("category", ""),
            "description": entry.get("description", ""),
            "status":      entry.get("status", "active"),
            "active_rev":  active_rev,
            "all_revs":    revs,
            "signoffs":    sigs,
            "user_signed": user_signed,
        }

    def unsigned_sops(self):
        """Return SOPs with an active revision the current user hasn't signed."""
        uid = self._current_user_id()
        if not uid:
            return []
        result = []
        for sop in self.list_sops():
            if sop["active_rev"] and not sop["user_signed"]:
                result.append(sop)
        return result

    def method_options(self):
        """Method choices for the SOP form — derived from the single-source
        method registry so new methods appear automatically."""
        opts = [{"slug": "", "label": "General Lab"}]
        for slug, label in _method_slug_label_pairs():
            opts.append({"slug": slug, "label": label})
        return opts

    def filter_tabs(self):
        """Tabs for filtering SOP list — derived from the method registry."""
        tabs = [{"key": "", "label": "All"}]
        for slug, label in _method_slug_label_pairs():
            tabs.append({"key": slug, "label": label})
        tabs.append({"key": "general", "label": "General Lab"})
        return tabs

    def active_tab(self):
        return self.request.form.get("method", "")

    # ── POST handlers ─────────────────────────────────────────────────────────

    def _handle_upload(self):
        if not self.can_manage():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form = self.request.form
        sop_id   = (form.get("sop_id") or "").strip()
        title    = (form.get("title") or "").strip()
        method   = (form.get("method_slug") or "").strip()
        category = (form.get("category") or "").strip()
        desc     = (form.get("description") or "").strip()
        notes    = (form.get("release_notes") or "").strip()
        upload   = form.get("sop_file")

        if not upload or not getattr(upload, "filename", None):
            return self._redirect("?msg=no_file&msg_type=error")

        portal = self._portal()
        registry = _get_registry(portal)

        if not sop_id:
            # new SOP
            if not title:
                return self._redirect("?msg=no_title&msg_type=error")
            sop_id = _next_sop_id(registry)
            registry.append({
                "sop_id":      sop_id,
                "title":       title,
                "method_slug": method or None,
                "category":    category,
                "description": desc,
                "current_rev": 0,
                "status":      "active",
            })
            _save_registry(portal, registry)
        else:
            # updating existing SOP metadata optionally
            for entry in registry:
                if entry["sop_id"] == sop_id:
                    if title:
                        entry["title"] = title
                    if category:
                        entry["category"] = category
                    if desc:
                        entry["description"] = desc
                    break
            _save_registry(portal, registry)

        # determine new rev_num
        revs = _get_revisions(portal, sop_id)
        rev_num = len(revs) + 1

        # write file
        file_data = upload.read()
        raw_name  = os.path.basename(getattr(upload, "filename", "") or "sop.pdf")
        ext       = os.path.splitext(raw_name)[1].lower() or ".pdf"
        safe_name = re.sub(r"[^\w\.\-]", "_", raw_name) or "sop{0}".format(ext)
        sop_dir   = os.path.join(SOP_DIR, sop_id)
        if not os.path.isdir(sop_dir):
            os.makedirs(sop_dir)
        dest_name = "rev_{0}{1}".format(rev_num, ext)
        dest_path = os.path.join(sop_dir, dest_name)
        tmp_path  = dest_path + ".tmp"
        with open(tmp_path, "wb") as fh:
            fh.write(file_data)
        os.rename(tmp_path, dest_path)

        ct = getattr(upload, "headers", {}).get("content-type", "application/octet-stream")
        revs.append({
            "rev_num":       rev_num,
            "filename":      safe_name,
            "filepath":      dest_path,
            "content_type":  ct,
            "uploaded_by":   self._current_user_id(),
            "uploaded_at":   date.today().isoformat(),
            "status":        "draft",
            "activated_by":  None,
            "activated_at":  None,
            "release_notes": notes,
        })
        _save_revisions(portal, sop_id, revs)
        return self._redirect("?msg=uploaded&msg_type=success&sop_id={0}".format(sop_id))

    def _handle_activate(self):
        if not self.can_manage():
            return self._redirect("?msg=permission_denied&msg_type=error")
        form = self.request.form
        sop_id  = (form.get("sop_id") or "").strip()
        rev_num = int(form.get("rev_num", 0))
        if not sop_id or not rev_num:
            return self._redirect("?msg=bad_request&msg_type=error")

        portal = self._portal()
        revs = _get_revisions(portal, sop_id)
        now  = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        uid  = self._current_user_id()

        found = False
        for r in revs:
            if r.get("status") == "active":
                r["status"] = "superseded"
            if r["rev_num"] == rev_num:
                r["status"]       = "active"
                r["activated_by"] = uid
                r["activated_at"] = now
                found = True
        if not found:
            return self._redirect("?msg=rev_not_found&msg_type=error")

        _save_revisions(portal, sop_id, revs)

        # update registry current_rev
        registry = _get_registry(portal)
        for entry in registry:
            if entry["sop_id"] == sop_id:
                entry["current_rev"] = rev_num
                break
        _save_registry(portal, registry)

        # clear all sign-offs — everyone must re-sign new revision
        _save_signoffs(portal, sop_id, {})

        return self._redirect("?msg=activated&msg_type=success&sop_id={0}".format(sop_id))

    def _handle_sign(self):
        form     = self.request.form
        sop_id   = (form.get("sop_id") or "").strip()
        if not sop_id:
            return self._redirect("?msg=bad_request&msg_type=error")

        portal = self._portal()
        revs   = _get_revisions(portal, sop_id)
        active = next((r for r in revs if r.get("status") == "active"), None)
        if not active:
            return self._redirect("?msg=no_active_rev&msg_type=error&sop_id={0}".format(sop_id))

        uid  = self._current_user_id()
        sigs = _get_signoffs(portal, sop_id)
        sigs[uid] = {
            "rev_num":   active["rev_num"],
            "signed_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "full_name": self._current_user_fullname(),
        }
        _save_signoffs(portal, sop_id, sigs)
        return self._redirect("?msg=signed&msg_type=success&sop_id={0}".format(sop_id))

    def _handle_download(self):
        form    = self.request.form
        sop_id  = (form.get("sop_id") or "").strip()
        rev_num = int(form.get("rev_num", 0))
        inline  = form.get("view", "0") == "1"

        if not sop_id:
            self.request.response.setStatus(400)
            return "Missing sop_id"

        portal = self._portal()
        revs   = _get_revisions(portal, sop_id)
        if rev_num:
            rev = next((r for r in revs if r["rev_num"] == rev_num), None)
        else:
            rev = next((r for r in revs if r.get("status") == "active"), None)

        if not rev or not rev.get("filepath"):
            self.request.response.setStatus(404)
            return "Revision not found"

        filepath = os.path.realpath(rev["filepath"])
        safe_root = os.path.realpath(SOP_DIR)
        if not filepath.startswith(safe_root):
            self.request.response.setStatus(403)
            return "Forbidden"

        if not os.path.isfile(filepath):
            self.request.response.setStatus(404)
            return "File not on disk"

        ct = rev.get("content_type", "application/octet-stream")
        disposition = "inline" if inline else "attachment"
        fname = rev.get("filename", "sop.pdf")

        with open(filepath, "rb") as fh:
            data = fh.read()

        response = self.request.response
        response.setHeader("Content-Type", ct)
        response.setHeader(
            "Content-Disposition",
            '{0}; filename="{1}"'.format(disposition, fname)
        )
        response.setHeader("Content-Length", str(len(data)))
        return data

    def _redirect(self, qs=""):
        base = "{0}/@@pfas-sop".format(self._portal_url())
        self.request.response.redirect("{0}{1}".format(base, qs))
        return ""

    def msg(self):
        return self.request.form.get("msg", "")

    def msg_type(self):
        return self.request.form.get("msg_type", "info")

    def selected_sop_id(self):
        return self.request.form.get("sop_id", "")

    MSG_TEXTS = {
        "uploaded":         "SOP revision uploaded successfully (draft — activate when ready).",
        "activated":        "Revision activated. All users must re-sign.",
        "signed":           "Sign-off recorded.",
        "permission_denied":"You do not have permission to perform this action.",
        "no_file":          "No file was attached.",
        "no_title":         "A title is required for new SOPs.",
        "bad_request":      "Invalid request.",
        "rev_not_found":    "Revision not found.",
        "no_active_rev":    "No active revision to sign.",
    }

    def msg_text(self):
        return self.MSG_TEXTS.get(self.msg(), self.msg())
