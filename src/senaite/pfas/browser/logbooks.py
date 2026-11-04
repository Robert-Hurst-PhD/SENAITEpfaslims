# -*- coding: utf-8 -*-
"""
PFAS per-batch logbooks.

Every batch logbook is drawn by PFASDynamicLogbookView from its definition's
field schema; the extraction log is the guided extraction's record.

Logbook definitions (names, order, custom field config) are stored in ZODB
via logbook_store.py.  Data for each logbook per-batch is stored in
IAnnotations on the Batch object.

Annotation key pattern: "senaite.pfas.logbook.{slug}"
  slug "250"–"253"   → built-in logbooks
  slug "custom-xxx"  → user-created logbooks

Cal data is also exported to /data/qc/batches/{batch_uid}/cal_251.json
so the pipeline injection builder can read it.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging
import os

try:
    from urllib import quote_plus
except ImportError:                                         # Python 3
    from urllib.parse import quote_plus

from Products.CMFCore.utils import getToolByName
from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from senaite.pfas.browser.view_helpers import send_pdf
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zope.annotation.interfaces import IAnnotations
from senaite.pfas import lab_time
from senaite.pfas.browser.formutil import flatten_form, json_list
from senaite.pfas.browser.perms import refuse
from senaite.pfas.config_history import now
from senaite.pfas.records import with_earlier
from senaite.pfas.document_templates import script_json

logger = logging.getLogger("senaite.pfas.browser.logbooks")

_KEY_PREFIX = u"senaite.pfas.logbook."

# Fields that support the GLP strike-through correction model (text/date/number only; not table rows)
_CORR_FIELDS_252 = ["analyst", "extraction_date", "notes", "reviewed_by", "reviewed_date"]
_CORR_FIELDS_253 = ["analyst", "processing_date", "balance_sn", "notes"]


def _apply_field_corrections(form, existing, fields, data):
    """
    Process GLP correction submissions.

    When `_corr_by_FNAME` is present in the form, the field is being corrected:
      - `_newval_FNAME`  = the corrected value (submitted instead of the disabled main input)
      - `_corr_by_FNAME` = initials of the person making the correction
    The value replaced is kept in `_corrections[FNAME]` with who and when (UTC);
    a field corrected again keeps every earlier correction under "earlier"
    (oldest first): no corrected value is ever lost.

    For non-corrected fields the caller already populated `data[fname]` from the
    normal form field; this function only overrides fields being corrected.
    """
    corrections = dict(existing.get("_corrections") or {})
    for fname in fields:
        corr_by = (form.get("_corr_by_" + fname) or u"").strip()
        if corr_by:
            new_val = (form.get("_newval_" + fname) or u"").strip()
            corrections[fname] = with_earlier(corrections.get(fname), {
                u"original":     existing.get(fname, u""),
                u"corrected_by": corr_by,
                u"corrected_at": now(),
            })
            data[fname] = new_val
    data[u"_corrections"] = corrections
# ── Annotation helpers ─────────────────────────────────────────────────────────

def _get_logbook(batch, form_num):
    """Return the logbook dict for form_num (e.g. 250) on this batch."""
    key = _KEY_PREFIX + str(form_num)
    ann = IAnnotations(batch)
    raw = ann.get(key)
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {}


def _save_logbook(batch, form_num, data):
    """Persist logbook data dict for form_num on this batch."""
    key = _KEY_PREFIX + str(form_num)
    ann = IAnnotations(batch)
    ann[key] = json.dumps(data)
    from senaite.pfas import records
    records.log(batch, u"logbook %s saved" % form_num)


# ── Base class ─────────────────────────────────────────────────────────────────

def _rows_from_form(form, field, existing, key):
    """A logbook's row list from its hidden JSON field.

    The field is filled by the page's script; before this, a missing field
    defaulted to "[]" and an unreadable one was coerced to [], and either way
    the saved rows of a CONTROLLED RECORD were replaced by nothing. Now:
    absent -> the saved rows are kept; unreadable or not a list -> ValueError
    (the handler refuses the save); present -> the rows as submitted.
    """
    return json_list(form, field, "{0} table".format(key), (existing or {}).get(key))


class _LogbookBase(ViewHelpers, BrowserView):

    def form_code(self, slug):
        """The lab's form number for a logbook (FM-ENV-003...), from the pool --
        never the storage slug ("Form numbers")."""
        from senaite.pfas.logbook_store import form_code
        return form_code(getToolByName(self.context, "portal_url").getPortalObject(), slug)

    def _print_slug(self):
        slug = getattr(self, "_slug", None)
        if slug is not None:
            return slug()
        import re
        found = re.search(r"(\d{3})", type(self).__name__)
        return found.group(1) if found else u""

    def print_control(self):
        """What this logbook prints as: the form number the lab gave it, the
        revision of its template and when that revision was last changed, and
        the entry (the worksheet or batch it was filled for). The page macro
        draws the control block and footer from it."""
        from senaite.pfas.logbook_store import print_control
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        try:
            method = self.batch_method()
        except Exception:                                   # noqa: BLE001
            method = u""
        return print_control(portal, self._print_slug(), self.batch_id(), method)

    def stored_json(self, key):
        """The saved rows for `key`, rendered into the hidden field so the
        form carries them even before (or without) the page's script."""
        try:
            return json.dumps((self.data() or {}).get(key) or [])
        except Exception as exc:
            # No value rather than "[]": an empty field is refused on save,
            # while "[]" would be taken as clearing the saved rows.
            logger.warning("stored_json(%s): %s", key, exc)
            return None

    def batch_url(self):
        return self.context.absolute_url()

    def batch_id(self):
        return self.context.getId()

    def batch_title(self):
        return self.context.Title() if hasattr(self.context, "Title") else self.batch_id()

    def batch_method(self):
        """The batch's method, by the ONE resolver (batch_method.py; core
        first); a worksheet's by batch_method.for_worksheet."""
        from senaite.pfas import batch_method as bm
        batch = self.context
        kind = getattr(batch, "portal_type", "")
        if kind == "Worksheet":
            return bm.for_worksheet(batch)
        if kind != "Batch":
            return u""              # opened outside a batch: no method
        return bm.resolve(batch)[0]


    def _redirect_self(self, msg=""):
        url = self.batch_url() + "/" + self._VIEW_NAME
        if msg:
            url += "?ok=" + msg.replace(" ", "+")
        return self._redirect(url)

    def _redirect_error(self, msg):
        url = self.batch_url() + "/" + self._VIEW_NAME + "?error=" + msg.replace(" ", "+")
        return self._redirect(url)

    def processing_guide_url(self):
        """The guided extraction, when the batch's method has a stage that
        takes the test portion: that stage IS the Sample Processing Log,
        FM-ENV-004, so the form takes no new entries.
        "" when the method has none (the form stays the record)."""
        try:
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas.sample_table import processing_stage
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            method_id = self.batch_method()
            if not method_id or not processing_stage(
                    get_profile(portal, method_id).get("extraction_stages")):
                return ""
            return "{0}/@@pfas-extraction-guide?batch_uid={1}".format(
                self.portal_url(), self.context.UID())
        except Exception as exc:                            # noqa: BLE001
            logger.warning("processing_guide_url: %s", exc)
            return ""

    def _processing_moved(self):
        """GET with no earlier record -> the guide; POST -> refused there.
        A record made before the move is still shown, read as it was."""
        url = self.processing_guide_url()
        if not url:
            return None
        if self.request.method == "POST":
            return self._redirect(url + "&error=" + quote_plus(
                "Sample processing is recorded in the guided extraction now"))
        if not _get_logbook(self.context, 253):
            return self._redirect(url)
        return None

    def ok_msg(self):
        return self.request.form.get("ok", "").replace("+", " ")

    def error_msg(self):
        return self.request.form.get("error", "").replace("+", " ")


# ── Logbook index (sub-tab) ────────────────────────────────────────────────────

class PFASLogbookIndexView(_LogbookBase):
    """Index of all four logbooks for a batch."""

    _VIEW_NAME = "@@pfas-logbook-index"
    template = ViewPageTemplateFile("templates/logbook_index.pt")

    def __call__(self):
        flatten_form(self.request)
        return self.template()

    def logbooks(self):
        from senaite.pfas.logbook_store import batch_only, get_active_logbook_defs
        from senaite.pfas.method_profile_store import get_profile
        portal = getToolByName(self.context, "portal_url").getPortalObject()

        # All active batch logbooks indexed by slug (library logbooks make lots)
        all_defs = {d["slug"]: d for d in batch_only(get_active_logbook_defs(portal))}

        # Order by the method's required_logbooks list (falls back to all defs)
        method_id = self.batch_method()
        required_slugs = []
        if method_id:
            try:
                profile = get_profile(portal, method_id)
                required_slugs = profile.get("required_logbooks", [])
            except Exception:
                pass

        if required_slugs:
            ordered_defs = [all_defs[s] for s in required_slugs if s in all_defs]
            # Append any active logbook not in required list that already has data
            seen = set(required_slugs)
            for slug, d in sorted(all_defs.items(), key=lambda x: x[1].get("sort_order", 100)):
                if slug not in seen and _get_logbook(self.context, slug):
                    ordered_defs.append(d)
        else:
            ordered_defs = sorted(all_defs.values(), key=lambda d: d.get("sort_order", 100))

        # Load extraction session to determine logbook 252 status
        extraction_session = {}
        extraction_finalized = False
        try:
            from senaite.pfas.browser.extraction_guide import _load_session
            from senaite.pfas import extraction_batch
            extraction_session = _load_session(extraction_batch.home(self.context))
            extraction_finalized = bool(extraction_session.get("finalized", False))
        except Exception:
            pass

        base = self.batch_url()
        batch_uid = ""
        try:
            batch_uid = self.context.UID() or ""
        except Exception:
            pass

        _BUILTIN_SUBTITLES = {
            "252": "Stage-by-stage: reagent lots · equipment S/Ns · spike pedigree · deviations",
            "253": "Sample IDs · processing date · matrix · analyst",
        }

        rows = []
        for d in ordered_defs:
            slug = d["slug"]
            form_num = d.get("form_num", slug)
            title = d.get("title", slug)
            builtin = d.get("builtin", False)
            is_extraction_log = (slug == "252")
            processing_url = self.processing_guide_url() if slug == "253" else ""

            # Route: extraction log, and sample processing when the method has
            # a stage for it, -> guided extraction; others -> logbook views
            if processing_url:
                url = processing_url
            elif is_extraction_log:
                url = "{0}/@@pfas-extraction-guide?batch_uid={1}".format(
                    self.portal_url(), batch_uid)
            else:
                url = "{0}/@@pfas-logbook-dynamic?slug={1}".format(base, slug)

            # Filled: extraction log is filled if session is finalized OR annotation exists
            if is_extraction_log:
                filled = extraction_finalized or bool(_get_logbook(self.context, slug))
            elif processing_url:
                filled = bool(_get_logbook(self.context, slug)) or self._processing_done(
                    extraction_session)
            else:
                filled = bool(_get_logbook(self.context, slug))

            # Subtitle: built-in logbooks have fixed descriptions; custom ones derive from schema
            subtitle = _BUILTIN_SUBTITLES.get(slug, "")
            if not subtitle and not builtin:
                try:
                    fields = json.loads(d.get("field_schema_json") or "[]")
                    labels = [f.get("label", "") for f in fields[:4] if f.get("label")]
                    subtitle = " · ".join(labels)
                except (ValueError, TypeError):
                    pass

            rows.append({
                "num":               form_num,
                "title":             "{0}: {1}".format(form_num, title),
                "subtitle":          subtitle,
                "url":               url,
                "filled":            filled,
                "is_extraction_log": is_extraction_log,
                "eg_finalized":      extraction_finalized if is_extraction_log else False,
                "eg_started":        bool(extraction_session) if is_extraction_log else False,
            })
        return rows

    def _processing_done(self, session):
        """The guided extraction's processing stage is completed."""
        try:
            from senaite.pfas.method_profile_store import get_profile
            from senaite.pfas.sample_table import processing_stage
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            from senaite.pfas.stage_plan import stages_for
            st = processing_stage(stages_for(session, get_profile(portal, self.batch_method())))
            return bool(st) and u"%s" % st.get("order") in ((session or {}).get("stages") or {})
        except Exception:                                   # noqa: BLE001
            return False

    def admin_url(self):
        return self.portal_url() + "/@@pfas-logbook-admin"

    def is_manager(self):
        """Gate manager-only affordances. @@pfas-logbook-admin returns 403 to
        bench staff, so linking it unconditionally was a dead end."""
        return _require_manager(self.context, self.request)


# ── Logbook Admin (portal-level) ──────────────────────────────────────────────

# Single source for the management role gate — shared with prep_logbooks and
# logbook_media so all three enforce the same rule (see browser/perms.py).
from senaite.pfas.browser.perms import require_manager as _require_manager  # noqa: E402


class PFASLogbookAdminView(ViewHelpers, BrowserView):
    """
    @@pfas-logbook-admin — portal-level logbook definition manager.

    Tab 1-N: per-method required-logbook sequence (reads/writes method profile).
    Final tab: Logbook Pool — global definitions (rename, add, toggle, delete).
    """

    template = ViewPageTemplateFile("templates/logbook_admin.pt")

    def __call__(self):
        flatten_form(self.request)
        if not _require_manager(self.context, self.request):
            return refuse(self.request, "Forbidden")
        if self.request.method == "POST":
            return self._handle_post()
        if self.request.form.get("action") == "download_logbook_doc":
            return self._download_doc()
        return self.template()

    def _download_doc(self):
        from senaite.pfas.browser.logbook_docs import resolve_download
        slug = self.request.form.get("slug", "")
        try:
            rev_num = int(self.request.form.get("rev_num", 0))
        except (TypeError, ValueError):
            rev_num = 0
        path, fname = resolve_download(self._portal(), slug, rev_num)
        if not path or not os.path.exists(path):
            self.request.response.setStatus(404)
            return "Not found"
        inline = self.request.form.get("view", "0") == "1"
        with open(path, "rb") as fh:
            data = fh.read()
        return send_pdf(self.request.response, data, fname or "logbook.pdf", inline=inline)

    def logbook_defs(self):
        """Active logbook families for the pool table (archived ones excluded —
        they live under the Archived section)."""
        from senaite.pfas.logbook_store import get_logbook_defs
        from senaite.pfas.browser.logbook_docs import get_archived_slugs
        archived = get_archived_slugs(self._portal())
        return [d for d in get_logbook_defs(self._portal())
                if d["slug"] not in archived]

    def archived_logbooks(self):
        """Deleted logbooks — hidden from the pool, retained; FM-ENV numbers
        are never reused. Restorable."""
        from senaite.pfas.logbook_store import get_logbook_defs
        from senaite.pfas.browser.logbook_docs import get_archived_slugs
        archived = get_archived_slugs(self._portal())
        return [d for d in get_logbook_defs(self._portal())
                if d["slug"] in archived]

    # ── controlled-document (PDF) layer ──────────────────────────────────────

    def _uid(self):
        from AccessControl import getSecurityManager
        return getSecurityManager().getUser().getId() or ""

    def _fullname(self):
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        mt = getToolByName(self._portal(), "portal_membership", None)
        if mt:
            member = mt.getMemberById(user.getId())
            if member and member.getProperty("fullname", ""):
                return member.getProperty("fullname", "")
        return user.getUserName() or user.getId() or "Unknown"

    def logbook_doc_info(self, slug):
        """Controlled-PDF summary for one logbook (revisions, active, sign-off)."""
        from senaite.pfas.browser.logbook_docs import doc_info
        return doc_info(self._portal(), slug, self._uid())

    def saved(self):
        return self.request.get("saved", "")

    def admin_error(self):
        """Why a save was refused (a form number used twice)."""
        return self.request.get("error", "") if self.request.get("error", "") not in (
            "sequence_not_saved",) else ""

    # ── Method-aware helpers ──────────────────────────────────────────────────

    def available_methods(self):
        """[{method_id, display_name}] for every configured method."""
        from senaite.pfas import configured_methods
        return [{"method_id": m["id"], "display_name": m["label"]}
                for m in configured_methods.choices(self._portal())]

    def required_json(self, method_id):
        """The method's CURRENT required logbooks, rendered into the sequence
        form's hidden field, so a submit made before the script draws the list
        (a hidden tab, a script error) saves what is there -- not "[]", which
        wiped the sequence."""
        try:
            from senaite.pfas.method_profile_store import get_profile
            return json.dumps([str(x) for x in (get_profile(
                self._portal(), method_id).get("required_logbooks") or [])])
        except Exception:
            return "[]"

    def method_config_json(self):
        """
        JSON blob consumed by the admin template JS.

        {
          "FDA_32PFAS": {
            "required": [
              {"slug":"250","form_num":"FM-ENV-001","title":"Solvent / Reagent Prep Log"},.
              ..
            ],
            "available": [...]   # pool logbooks NOT in required
          },.
          ..
        }
        """
        from senaite.pfas.logbook_store import batch_only, get_logbook_defs
        from senaite.pfas.method_profile_store import get_profile
        from senaite.pfas import configured_methods
        portal = self._portal()
        # the method sequence is batch logbooks only (library logbooks make lots)
        all_defs = {d["slug"]: d for d in batch_only(get_logbook_defs(portal))}

        result = {}
        for mid in configured_methods.ids(portal):
            try:
                profile = get_profile(portal, mid)
                req_slugs = profile.get("required_logbooks", [])
            except Exception:
                req_slugs = []

            required = []
            for s in req_slugs:
                if s in all_defs:
                    d = all_defs[s]
                    required.append({
                        "slug":     s,
                        "form_num": d.get("form_num", s),
                        "title":    d.get("title", s),
                        "builtin":  d.get("builtin", False),
                    })

            req_set = set(req_slugs)
            available = []
            for s, d in sorted(all_defs.items()):
                if s not in req_set and d.get("active", True):
                    # Only offer logbooks with no method restriction, or matching this method
                    method_slug = d.get("method_slug", "") or ""
                    from senaite.pfas.logbook_store import method_key
                    if not method_slug or method_key(method_slug) == method_key(mid):
                        available.append({
                            "slug":     s,
                            "form_num": d.get("form_num", s),
                            "title":    d.get("title", s),
                        })

            result[mid] = {"required": required, "available": available}

        return script_json(result)

    # ── POST handlers ─────────────────────────────────────────────────────────

    def _handle_doc_action(self, action, slug, slugs):
        """Controlled-PDF actions on a logbook: upload / activate / sign, and
        delete->archive / restore. Mirrors the SOP document-control flow.
        `slugs` are the defined logbooks: the slug names a directory on disk,
        so an unknown one is refused before anything is read or written."""
        from senaite.pfas.browser import logbook_docs as ld
        portal = self._portal()
        uid = self._uid()
        def done(msg):
            self.request.response.redirect(
                "{0}/@@pfas-logbook-admin?saved={1}#lb-{2}".format(
                    self.portal_url(), msg, slug))
            return ""

        if not slug or slug not in slugs:
            return done("bad_request")
        if action == "upload_logbook_doc":
            upload = self.request.form.get("doc_file")
            notes = (self.request.form.get("release_notes") or "").strip()
            ok, msg = ld.upload_doc(portal, slug, upload, notes, uid)
            return done(msg)
        if action == "activate_logbook_doc":
            try:
                rev_num = int(self.request.form.get("rev_num", 0))
            except (TypeError, ValueError):
                rev_num = 0
            ok, msg = ld.activate_doc(portal, slug, rev_num, uid)
            return done(msg)
        if action == "sign_logbook_doc":
            ok, msg = ld.sign_doc(portal, slug, uid, self._fullname())
            return done(msg)
        if action == "archive_logbook":
            ld.archive_logbook(portal, slug)
            return done("archived")
        if action == "restore_logbook":
            ld.restore_logbook(portal, slug)
            return done("restored")
        return done("bad_request")

    def _handle_post(self):
        from senaite.pfas.logbook_store import get_logbook_defs, save_logbook_defs
        portal = self._portal()
        action = self.request.form.get("action", "")
        slug = self.request.form.get("slug", "")
        defs = get_logbook_defs(portal)
        slugs = [d["slug"] for d in defs]

        # ── Controlled-document (PDF) actions ────────────────────────────────
        if action in ("upload_logbook_doc", "activate_logbook_doc",
                      "sign_logbook_doc", "archive_logbook", "restore_logbook"):
            return self._handle_doc_action(action, slug, slugs)

        # ── Method sequence save ──────────────────────────────────────────────
        if action == "save_method_config":
            method_id = self.request.form.get("method_id", "").strip()
            raw = self.request.form.get("required_logbooks_json")
            try:
                req = json.loads(raw)
            except (ValueError, TypeError):
                req = None
            if not isinstance(req, list):
                # Refused, not coerced to []: an absent or broken list emptied
                # the method's required logbooks.
                self.request.response.redirect(
                    "{0}/@@pfas-logbook-admin?error=sequence_not_saved&tab={1}".format(
                        self.portal_url(), method_id))
                return u""
            if method_id:
                from senaite.pfas.method_profile_store import get_profile, save_profile
                profile = get_profile(portal, method_id)
                profile["required_logbooks"] = [str(s) for s in req]
                save_profile(portal, method_id, profile)
            self.request.response.redirect(
                "{0}/@@pfas-logbook-admin?saved=method&tab={1}".format(
                    self.portal_url(), method_id)
            )
            return ""

        elif action == "rename":
            new_title = self.request.form.get("title", "").strip()
            new_form_num = self.request.form.get("form_num", "").strip()
            for d in defs:
                if d["slug"] == slug:
                    if new_title:
                        d["title"] = new_title
                    if new_form_num:
                        d["form_num"] = new_form_num
                    break

        elif action == "toggle":
            for d in defs:
                if d["slug"] == slug:
                    d["active"] = not d.get("active", True)
                    break

        elif action == "move_up":
            idx = slugs.index(slug) if slug in slugs else -1
            if idx > 0:
                defs[idx - 1], defs[idx] = defs[idx], defs[idx - 1]

        elif action == "move_down":
            idx = slugs.index(slug) if slug in slugs else -1
            if 0 <= idx < len(defs) - 1:
                defs[idx + 1], defs[idx] = defs[idx], defs[idx + 1]

        elif action == "delete":
            from senaite.pfas.logbook_store import is_builtin
            if slug and not is_builtin(slug):
                defs = [d for d in defs if d["slug"] != slug]

        elif action == "reseed_builtins":
            from senaite.pfas.browser.prep_logbooks import seed_builtin_logbook_defs
            seed_builtin_logbook_defs(portal)
            self.request.response.redirect(
                self.portal_url() + "/@@pfas-logbook-admin?saved=reseed"
            )
            return ""

        try:
            save_logbook_defs(portal, defs)
        except ValueError as exc:
            self.request.response.redirect(
                self.portal_url() + "/@@pfas-logbook-admin?error=" + quote_plus(
                    (u"%s" % exc).encode("utf-8")))
            return ""
        self.request.response.redirect(
            self.portal_url() + "/@@pfas-logbook-admin?saved=1"
        )
        return ""


# ── Dynamic schema helpers ────────────────────────────────────────────────────

def _parse_schema(defn):
    """Parse field_schema_json from a PrepLogbookDef dict or object.  Returns []."""
    if isinstance(defn, dict):
        raw = defn.get("field_schema_json") or u"[]"
    else:
        raw = getattr(defn, "field_schema_json", None) or u"[]"
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return parsed
    except (ValueError, TypeError):
        pass
    return []


def _correctable_fields(schema_fields):
    """Return list of field names with correctable=True (excludes table/checkbox)."""
    return [
        f["name"] for f in schema_fields
        if f.get("correctable")
        and f.get("type") not in ("table", "checkbox")
        and f.get("name")
    ]


def _apply_receipt_thermometers(data, schema_fields):
    from senaite.pfas import receipt_temperature as rt
    names = rt.thermometer_fields(schema_fields)
    if not names:
        return
    from senaite.pfas import facility_qc as fq
    field = [f for f in schema_fields if f.get("name") == names[0]][0]
    as_of = (data.get(field.get("as_of") or "lab_received_date") or u"")[:10] \
        or lab_time.today().isoformat()
    rt.enrich(data, schema_fields, fq.get_unit, fq.calibration, as_of)


# Bookkeeping key on a logbook entry: the definition revision it is filled under.
PIN_KEY = "_def_rev"


def _extract_data_from_schema(form, schema_fields):
    """Build data dict from POST form data based on the field schema."""
    data = {}
    for field in schema_fields:
        fname = field.get("name")
        if not fname:
            continue
        ftype = field.get("type", "text")
        if ftype == "section":                  # a heading: holds no value
            continue
        if ftype == "choice" and field.get("display") == "checkboxes":
            from senaite.pfas.logbook_schema import OPTION_PARAM
            data[fname] = [o.get("value") for i, o in enumerate(field.get("options") or [])
                           if isinstance(o, dict) and form.get(OPTION_PARAM % (fname, i))]
            continue
        if ftype == "table":
            # absent -> the saved rows stay (the caller seeds from them);
            # unreadable -> ValueError, the save is refused
            if fname + "_json" not in form:
                continue
            data[fname] = _rows_from_form(form, fname + "_json", {}, fname)
        elif ftype == "checkbox":
            data[fname] = form.get(fname) == "yes"
        else:
            data[fname] = form.get(fname, "") or ""
    return data


def usable_lots(portal, lot_type="", q=""):
    """Prepared-standard lots an analyst may still use, most recent first.

    Single definition of "usable", shared by the autocomplete and by the
    defaulting blob so the picker and the pre-filled value can never disagree.

    Delegates to prepared_standards._list, which already resolves the
    PARENT-TIGHTENED expiry (a prep whose source CRM has expired is itself
    expired) and sorts by prepared_date descending. The previous implementation
    re-scanned the folder, checked only the stored status string, and sorted
    alphabetically — so it offered lots that were exhausted or effectively
    expired, and never surfaced the newest one first.
    """
    from senaite.pfas.browser.prepared_standards import (
        STATUS_ACTIVE, _list, build_parentage, equipment_gate_problems,
        parentage_problems)

    out = []
    for d in _list(portal, q=q, type_filter=lot_type):
        # _list derives `expired` from the effective expiry; anything not
        # active is either used up (exhausted) or out of date.
        if (d.get("status") or "") != STATUS_ACTIVE:
            continue
        # WHY the gate verdict travels with the offer: since the
        # traceability gate started checking level 1, an in-date unexhausted lot
        # can still block release -- because a parent is not in inventory, or the
        # in-house water it was made with has no Type 1 log for the day. The
        # picker offered those silently, so an analyst learned at data review
        # what they could have known at the bench.
        #
        # ANNOTATED, not filtered: an analyst holding the physical bottle who
        # cannot find it in the list learns nothing and works around the system.
        # The same walk the certificate and the gate use, so the reason shown at
        # the bench is the reason release will give.
        try:
            problems = parentage_problems(build_parentage(portal, d)) + \
                equipment_gate_problems(portal, d)
        except Exception as exc:          # a data-entry error must not break the picker
            logger.warning("usable_lots: parentage for %s: %s",
                           d.get("lot_number"), exc)
            problems = []
        out.append({
            "lot_number":    d.get("lot_number") or "",
            "title":         d.get("title") or d.get("lot_number") or "",
            "standard_type": d.get("standard_type") or "",
            "expiry_date":   d.get("effective_expiry") or d.get("expiry_date") or "",
            "prepared_date": d.get("prepared_date") or "",
            "status":        d.get("status") or "",
            "gate_ok":       not problems,
            "gate_problems": [p["reason"] for p in problems],
        })
    # _list sorts by prepared_date desc; make the tie-break explicit rather
    # than relying on sort stability. A lot with no prepared_date sorts last,
    # so it is never chosen as "most recent" but stays selectable.
    out.sort(key=lambda x: (x["prepared_date"], x["lot_number"]), reverse=True)
    return out


def _current_signer(context):
    """Display name for the logged-in user, for stamping a record."""
    try:
        from AccessControl import getSecurityManager
        user = getSecurityManager().getUser()
        try:
            portal = getToolByName(context, "portal_url").getPortalObject()
            mt = getToolByName(portal, "portal_membership", None)
            if mt:
                member = mt.getMemberById(user.getId())
                if member and member.getProperty("fullname", ""):
                    return member.getProperty("fullname", "")
        except Exception:
            pass
        return user.getUserName() or user.getId() or "Unknown"
    except Exception:
        return "Unknown"


def _stamp_struck_rows(context, data, schema_fields):
    """Stamp who/when onto any table row newly struck as not-applicable.

    The browser only ever sets the boolean flag; attribution is applied here so
    it cannot be forged from the client and the analyst types nothing. Rows that
    already carry a stamp keep it, so re-saving a logbook does not re-date an
    older strike.
    """
    from senaite.pfas.logbook_schema import NA_KEY, NA_BY_KEY, NA_AT_KEY
    signer = None
    today = lab_time.today().isoformat()
    for field in schema_fields or []:
        if field.get("type") != "table":
            continue
        rows = data.get(field.get("name"))
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get(NA_KEY):
                # Not struck: make sure no stale attribution lingers from a
                # previous strike that has since been undone.
                row.pop(NA_BY_KEY, None)
                row.pop(NA_AT_KEY, None)
                continue
            if not row.get(NA_BY_KEY):
                if signer is None:
                    signer = _current_signer(context)
                row[NA_BY_KEY] = signer
            if not row.get(NA_AT_KEY):
                row[NA_AT_KEY] = today



# ── Dynamic logbook renderer ──────────────────────────────────────────────────

class PFASDynamicLogbookView(_LogbookBase):
    """
    @@pfas-logbook-dynamic?slug=<slug>

    Renders a logbook form from a PrepLogbookDef's field_schema_json.
    All field types (text, date, number, textarea, lot_ref, reagent_ref,
    checkbox, table) are supported.  GLP corrections use the same
    _apply_field_corrections() as the hardcoded views.
    """

    _VIEW_NAME = "@@pfas-logbook-dynamic"
    template = ViewPageTemplateFile("templates/logbook_dynamic.pt")

    def __call__(self):
        flatten_form(self.request)
        if self._slug() == "253":
            moved = self._processing_moved()
            if moved is not None:
                return moved
        if self._slug() == "252":
            # the Extraction Log is the guided extraction's record
            guide = "{0}/@@pfas-extraction-guide?batch_uid={1}".format(self.portal_url(), self.context.UID())
            if self.request.method == "POST":
                return self._redirect(guide + "&error=" + quote_plus(
                    "The extraction is recorded in the guided extraction"))
            return self._redirect(guide)
        from senaite.pfas.logbook_roles import role_of
        if role_of(self._current_def() or {"logbook_slug": self._slug()}) == u"receipt":
            # sample receipt is recorded on the samples' CoC records
            coc = "{0}/@@pfas-coc".format(self.portal_url())
            if self.request.method == "POST":
                return self._redirect(coc + "?error=" + quote_plus(
                    "Sample receipt is recorded on the CoC records"))
            return self._redirect(coc)
        if self.request.method == "POST":
            return self._handle_post()
        return self.template()

    def signoff_noun(self):
        d = self._logbook_def()
        return (d.get("standard_type") or "logbook record").lower()

    def signoff_name(self):
        data = self.data()
        for key in ("prepared_by", "analyst", "reviewed_by"):
            if data.get(key):
                return data.get(key)
        return ""

    def signoff_date(self):
        data = self.data()
        for key in ("prepared_date", "extraction_date", "processing_date"):
            if data.get(key):
                return data.get(key)
        return ""

    def slug(self):
        return self.request.get("slug", "")

    def _slug(self):
        return self.slug()

    def _redirect_self(self, msg=""):
        url = "{0}/@@pfas-logbook-dynamic?slug={1}".format(
            self.batch_url(), self._slug())
        if msg:
            url += "&ok=" + msg.replace(" ", "+")
        return self._redirect(url)

    def _redirect_error(self, msg):
        """Back to THIS logbook (the base view's error redirect drops the slug)."""
        url = "{0}/@@pfas-logbook-dynamic?slug={1}&error={2}".format(
            self.batch_url(), self._slug(), msg.replace(" ", "+"))
        return self._redirect(url)

    def has_designed_pdf(self):
        """An issued design exists for this logbook (Document Templates)."""
        try:
            from senaite.pfas import document_templates as dt
            from senaite.pfas import logbook_documents as ld
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            entry = dt.load(portal).get("logbook-%s" % self._slug())
            return bool(entry and not entry.get("archived") and dt.current(entry)
                        and entry.get("kind") == ld.kind_id(self._slug()))
        except Exception:                                   # noqa: BLE001
            return False

    def _current_def(self):
        """The definition a new entry is filled on: the active revision,
        else the newest."""
        from senaite.pfas.browser.prep_logbooks import _list
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        slug = self._slug()
        defs = _list(portal, slug=slug, status_filter="active")
        if not defs:
            defs = _list(portal, slug=slug)
        return defs[0] if defs else {}

    def _logbook_def(self):
        """The definition this batch's entry is shown and saved with: the
        revision the entry was first saved under (PIN_KEY), so a new revision
        of the template never re-labels or drops what was recorded; a new
        entry uses the current revision."""
        from senaite.pfas.browser.prep_logbooks import _list
        pinned = (_get_logbook(self.context, self._slug()) or {}).get(PIN_KEY)
        if pinned:
            portal = getToolByName(self.context, "portal_url").getPortalObject()
            for d in _list(portal, slug=self._slug()):
                if d.get("revision") == pinned:
                    return d
        return self._current_def()

    def revision_note(self):
        """'' or a line saying the entry keeps an older template revision."""
        pinned = (_get_logbook(self.context, self._slug()) or {}).get(PIN_KEY)
        current = self._current_def().get("revision")
        if pinned and current and pinned != current:
            return (u"Filled under template revision %s, and kept on it; "
                    u"the current revision is %s." % (pinned, current))
        return u""

    def logbook_def(self):
        return self._logbook_def()

    def field_schema(self):
        """Parsed list of field definition dicts. A field core owns
        (core_fields.CORE_OWNED: the collection date) is marked read-only and
        never required: it shows the samples' own value."""
        from senaite.pfas.core_fields import CORE_OWNED
        fields = _parse_schema(self._logbook_def())
        for f in fields:
            if f.get("name") in CORE_OWNED:
                f["core_owned"] = True
                f["required"] = False
                f["correctable"] = False
        return fields

    def field_schema_json(self):
        return script_json(self.field_schema())

    def _shown(self):
        if not hasattr(self, "_shown_cache"):
            from senaite.pfas.logbook_schema import visible_names
            self._shown_cache = visible_names(self.field_schema(), self.data())
        return self._shown_cache

    def is_shown(self, field):
        """The question is shown for the answers saved so far (its show-if)."""
        name = (field or {}).get("name")
        return not name or name in self._shown()

    def show_if_json(self, field):
        """The question's show-if for logbook_runtime.js, or None."""
        cond = (field or {}).get("show_if")
        return json.dumps(cond) if isinstance(cond, dict) and cond.get("field") else None

    def option_param(self, name, index):
        """The form parameter of one answer of a several-answer choice."""
        from senaite.pfas.logbook_schema import OPTION_PARAM
        return OPTION_PARAM % (name, index)

    def lot_defaults_json(self):
        """{lot_type: most-recent-usable-lot} for the lot_ref fields on this
        logbook, so an empty lot box can pre-fill without a fetch per input.

        Computed server-side but APPLIED client-side, deliberately: writing it
        into view.data() would make a never-saved default indistinguishable
        from a recorded value, and data() is the same read model the Data
        Review traceability gate walks — a phantom lot would appear in the
        audit tree before anyone touched the form.
        """
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        wanted = set()
        for f in self.field_schema():
            if f.get("type") == "lot_ref":
                wanted.add((f.get("lot_type") or "").strip())
        out = {}
        for lot_type in wanted:
            lots = usable_lots(portal, lot_type=lot_type)
            if lots:
                out[lot_type] = lots[0]
        return script_json(out)

    def logbook_title(self):
        d = self._logbook_def()
        code = d.get("logbook_code") or d.get("logbook_slug") or self._slug()
        title = d.get("title") or self._slug()
        if code and code != title:
            return u"{0}: {1}".format(code, title)
        return title

    def logbook_code(self):
        d = self._logbook_def()
        return d.get("logbook_code") or self._slug()

    def data(self):
        """The stored entry, with the fields core owns shown from the samples
        (never stored: core_fields.py)."""
        if not hasattr(self, "_data_cache"):
            from senaite.pfas.core_fields import CORE_OWNED, core_values
            data = dict(_get_logbook(self.context, self._slug()))
            names = set(f.get("name") for f in _parse_schema(self._logbook_def())) & set(CORE_OWNED)
            if names:
                values = core_values(self.context)
                for n in names:
                    data[n] = values.get(n, u"")
            self._data_cache = data
        return self._data_cache

    def data_json(self):
        return script_json(self.data())

    def _handle_post(self):
        f = self.request.form
        slug = self._slug()
        schema_fields = self.field_schema()
        existing = self.data()

        # _save_logbook replaces the annotation wholesale: what the post does
        # not carry (a table left untouched) keeps its stored value
        data = dict(existing)
        try:
            data.update(_extract_data_from_schema(f, schema_fields))
        except ValueError as exc:
            return self._redirect_error(str(exc).replace(" ", "+"))

        from senaite.pfas.logbook_schema import hidden_names, missing_required, value_errors
        # a question its show-if hides is neither required nor kept
        for name in hidden_names(schema_fields, data):
            data.pop(name, None)
        missing = missing_required(schema_fields, data)
        if missing:
            return self._redirect_error(quote_plus((u"Not saved. Required: %s" % u", ".join(missing)).encode("utf-8")))
        wrong = value_errors(schema_fields, data)
        if wrong:
            return self._redirect_error(quote_plus((u"Not saved. %s" % u" ".join(wrong)).encode("utf-8")))

        correctable = _correctable_fields(schema_fields)
        _apply_field_corrections(f, existing, correctable, data)

        # fields core owns are shown, never stored (core_fields.py)
        from senaite.pfas.core_fields import CORE_OWNED
        for name in CORE_OWNED:
            data.pop(name, None)

        # A thermometer field (the CoC's receipt thermometer) freezes the
        # instrument and the correction factor in force on the receipt date,
        # and corrects the temperature columns that name it.
        _apply_receipt_thermometers(data, schema_fields)

        # Attribution for rows struck as not-applicable is applied server-side.
        _stamp_struck_rows(self.context, data, schema_fields)

        # the template revision this entry is filled under, kept from its first save
        if not data.get(PIN_KEY):
            data[PIN_KEY] = self._logbook_def().get("revision") or 1

        _save_logbook(self.context, slug, data)

        return self._redirect_self("Saved")


class PFASLogbookPDFView(PFASDynamicLogbookView):
    """@@pfas-logbook-pdf?slug=<slug> on a batch: this batch's logbook as a
    PDF from the logbook's ISSUED design (Document Templates).
    Without one there is no PDF (the form's Print Preview prints the page);
    an issued design that no longer fits the definition is refused."""

    def __call__(self):
        flatten_form(self.request)
        from senaite.pfas.browser.logbook_designs import LogbookDesignError, designed_logbook_pdf
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        slug = self._slug()
        defn = self._logbook_def()
        header = {"batch": self.context.getId(), "batch_title": self.context.Title(),
                  "method": PFASLogbookIndexView(self.context, self.request).batch_method(),
                  "form": self.form_code(slug), "title": defn.get("title"),
                  "revision": defn.get("revision")}
        try:
            pdf = designed_logbook_pdf(portal, slug, self.field_schema(), self.data(), header)
        except LogbookDesignError as exc:
            self.request.response.setStatus(409)
            return u"%s" % exc
        if pdf is None:
            self.request.response.setStatus(404)
            return u"No design is issued for this logbook: use Print Preview."
        return send_pdf(self.request.response, pdf, "%s-%s.pdf" % (
            self.form_code(slug) or slug, self.context.getId()))


def record_retired(parent, label, objs, reason):
    """Before a controlled record goes: which file, on its parent's trail
    (records.log: who, when, why)."""
    from senaite.pfas import records
    for obj in objs:
        try:
            f = obj.getAttachmentFile()
            name, size = getattr(f, "filename", u"") or u"", f.get_size() if f else 0
        except Exception:                                   # noqa: BLE001
            name, size = u"", 0
        records.log(parent, u"attachment retired", reason=reason,
                    detail={u"label": label, u"id": obj.getId(), u"file": name, u"bytes": size})


class PFASRetireAttachmentView(BrowserView):
    """
    POST @@pfas-retire-attachment  {parent_uid, label}

    Remove superseded attachments carrying *label* from a Worksheet or Client.

    senaite.jsonapi cannot delete an Attachment — its delete fires a
    "deactivate" transition the type has no workflow for, and answers HTTP 200
    with success:false. So a re-imported batch report stacked another copy each
    time (eight on one worksheet) and the worker could only report that it had
    failed to replace it. Deleting from inside the add-on works.

    Manager-only: this removes a controlled record.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import require_manager, disable_csrf
        if not require_manager(self.context, self.request):
            return refuse(self.request, json.dumps({"error": "Manager role required"}))
        disable_csrf(self.request)
        # it deletes: never from a plain link
        if (self.request.get("REQUEST_METHOD") or "").upper() != "POST":
            self.request.response.setStatus(405)
            self.request.response.setHeader("Allow", "POST")
            return json.dumps({"error": "POST required"})

        parent_uid = (self.request.get("parent_uid") or u"").strip()
        label = (self.request.get("label") or u"").strip()
        if not parent_uid or not label:
            self.request.response.setStatus(400)
            return json.dumps({
                "error": "parent_uid and label are both required"})

        from bika.lims import api as _api
        parent = _api.get_object_by_uid(parent_uid, None)
        if parent is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": "No object {0}".format(parent_uid)})

        doomed = []
        for obj in parent.objectValues(["Attachment"]):
            try:
                keys = obj.getAttachmentKeys() or u""
            except Exception:
                keys = u""
            if keys == label:
                doomed.append(obj.getId())
        if doomed:
            reason = (self.request.get("reason") or u"").strip() or u"superseded by a newer copy"
            record_retired(parent, label, [parent[i] for i in doomed], reason)
            parent.manage_delObjects(doomed)
        return json.dumps({"retired": doomed})


class PFASRunManifestView(BrowserView):
    """
    @@pfas-run-manifest?batch_id=demo-b-001

    The injection list the Run Builder planned, so the importer can reconcile
    what was actually run against it. This replaces validating names against
    hardcoded regexes — which rejected 8 of 20 hand-typed names and then 21 of
    22 names this system generated itself.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        batch_id = (self.request.get("batch_id") or u"").strip()
        ws_id = (self.request.get("worksheet_id") or u"").strip()
        if not batch_id and not ws_id:
            self.request.response.setStatus(400)
            return json.dumps({"error": "worksheet_id or batch_id parameter is required"})
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        from senaite.pfas import extraction_batch
        from senaite.pfas.batch_ref import get_batch
        # the Run Builder keeps the manifest on the extraction batch (the
        # worksheet); a client Batch id is followed to it
        batch = None
        if ws_id:
            from bika.lims import api
            hits = api.search({"portal_type": "Worksheet", "getId": ws_id}, "senaite_catalog_worksheet")
            batch = api.get_object(hits[0]) if hits else None
        if batch is None and batch_id:
            b = get_batch(portal, batch_id)
            batch = extraction_batch.home(b) if b is not None else None
        if batch is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": "No worksheet {0} / batch {1}".format(ws_id, batch_id)})
        try:
            from senaite.pfas.browser.run_builder import RUN_MANIFEST_KEY
            raw = IAnnotations(batch).get(RUN_MANIFEST_KEY)
        except Exception:
            raw = None
        if not raw:
            return json.dumps({"lab_zone": lab_time.zone()})
        try:
            manifest = json.loads(raw)
        except (ValueError, TypeError):
            return json.dumps({"lab_zone": lab_time.zone()})
        return json.dumps({
            "lab_zone": lab_time.zone(),
            "built_at": manifest.get("built_at", ""),
            "built_by": manifest.get("built_by", ""),
            "planned": [r.get("name") for r in (manifest.get("rows") or [])
                        if r.get("name")],
            # what each planned injection IS, as the Run Builder built it: the
            # pipeline never has to read a role from a name it issued
            "roles": dict((r["name"], r["role"]) for r in (manifest.get("rows") or [])
                          if r.get("name") and r.get("role")),
        })


def _mxb_reference(portal, lot_uid):
    """{"levels": {analyte: value}, "unit"} in force on a blank-matrix lot,
    or None."""
    try:
        from senaite.pfas.browser.assigned_levels import lot_record
        rec = lot_record(portal, lot_uid)
    except Exception as exc:                                # noqa: BLE001
        logger.warning("matrix blank reference for %s: %s", lot_uid, exc)
        return None
    if not rec or not rec.get("levels"):
        return None
    return {"levels": dict(rec["levels"]), "unit": rec.get("unit") or u""}


def _field_qc_code(member):
    """u"FRB" for a member sample whose CoC Field QC says it is a field
    reagent blank, u"TB" for a trip blank -- read from the sample, which owns
    it; else u"". The worker judges an FRB against the blank limit and a TB
    against the method's trip blank limit (a gap while none is set)."""
    if member.get("role") != u"Sample" or not member.get("sample_uid"):
        return u""
    try:
        from bika.lims import api
        sample = api.get_object_by_uid(member["sample_uid"], None)
        fld = sample.getField("FieldQCType") if sample is not None else None
        value = (fld.get(sample) if fld else u"") or u""
    except Exception:                                       # noqa: BLE001
        return u""
    from senaite.pfas.coc_records import WORKER_FIELD_QC
    return WORKER_FIELD_QC.get(value, u"")


class PFASBatchDilutionsView(BrowserView):
    """
    @@pfas-batch-dilutions?batch_id=demo-b-001

    The dilution map recorded on FM-ENV-003, as JSON, for the pipeline worker:

        {"DEMO Silage \"Egg-3\"; Dil. 1:10": {"parent": "DEMO Silage \"Egg-3\" Sample",
                                             "factor": 10.0}}

    Empty object when the batch records no dilutions — which is every batch
    logged before the columns existed, so the worker's behaviour is unchanged
    for them.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)

        batch_id = (self.request.get("batch_id") or u"").strip()
        ws_id = (self.request.get("worksheet_id") or u"").strip()
        if not batch_id and not ws_id:
            self.request.response.setStatus(400)
            return json.dumps({"error": "worksheet_id or batch_id parameter is required"})

        portal = getToolByName(self.context, "portal_url").getPortalObject()
        from senaite.pfas import extraction_batch
        from senaite.pfas.batch_ref import get_batch
        from senaite.pfas.dilution_ref import get_dilutions, get_sample_amounts, get_spikes
        # the extraction record lives on the worksheet; a
        # client Batch id is followed to its worksheet
        batch = None
        if ws_id:
            from bika.lims import api
            hits = api.search({"portal_type": "Worksheet", "getId": ws_id}, "senaite_catalog_worksheet")
            batch = api.get_object(hits[0]) if hits else None
        if batch is None and batch_id:
            batch = extraction_batch.home(get_batch(portal, batch_id))
        if batch is None:
            self.request.response.setStatus(404)
            return json.dumps({"error": "No worksheet {0} / batch {1}".format(ws_id, batch_id)})
        payload = get_dilutions(batch)
        # how the IS and the surrogate were handled when each dilution was
        # made (Run Builder step 4): the worker judges the IS by it
        for r in extraction_batch.load_requests(batch):
            prep = r.get("prep") or {}
            if r.get("kind") == u"dilution" and r.get("new_injection") in payload and prep:
                payload = dict(payload)
                payload[r["new_injection"]] = dict(payload[r["new_injection"]],
                                                   is_handling=prep.get("is_handling") or u"",
                                                   sur_handling=prep.get("sur_handling") or u"")
        # Spike pedigree rides along under a reserved key. A dilution id can
        # never collide with it: NAME_RE forbids a leading underscore.
        spikes = get_spikes(batch)
        if spikes:
            payload = dict(payload)
            payload["_spikes"] = spikes
        # the extraction batch's members: each LIMS-issued injection's role and
        # a sample's uid, so the worker matches by the record
        members = extraction_batch.load(batch)
        if members:
            payload = dict(payload)
            payload["_members"] = dict(
                (m.get("injection"), {"role": m.get("role") or u"Sample",
                                      "sample_uid": m.get("sample_uid") or u"",
                                      "field_qc": _field_qc_code(m),
                                      # the method blank to subtract
                                      "subtract": bool(m.get("subtract"))})
                for m in members if m.get("injection"))
            # a matrix blank's lot reference values, for the method that
            # judges it as a recovery against them (Matrix blanks)
            for m in members:
                if m.get("role") == u"MxB" and m.get("injection") and m.get("lot"):
                    ref = _mxb_reference(portal, m["lot"])
                    if ref:
                        payload["_members"][m["injection"]]["reference"] = ref
            # a re-injection made at the bench files as its original
            payload["_members"].update(extraction_batch.reinjection_aliases(
                extraction_batch.load_requests(batch), members))
        # per-sample amount / final volume, also under a reserved key
        amounts = get_sample_amounts(batch)
        if amounts:
            payload = dict(payload)
            payload["_samples"] = amounts
        return json.dumps(payload)


# ── AJAX: Prepared Standard lot autocomplete ──────────────────────────────────

class PFASLotAutocompleteView(BrowserView):
    """
    @@pfas-lot-autocomplete?type=Calibration+Standard&q=PDS

    Returns JSON list of PreparedStandard lots matching the query.
    Used by lot_ref fields in the dynamic logbook renderer.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)

        q = (self.request.get("q") or u"").strip()
        lot_type = (self.request.get("type") or u"").strip()
        portal = getToolByName(self.context, "portal_url").getPortalObject()
        return json.dumps(usable_lots(portal, lot_type=lot_type, q=q)[:50])


# ── AJAX: Reagent inventory autocomplete ──────────────────────────────────────

class PFASReagentAutocompleteView(BrowserView):
    """
    @@pfas-reagent-autocomplete?q=methanol

    Returns JSON list of active Reagent records matching the query.
    Used by reagent_ref fields in the dynamic logbook renderer.
    """

    def __call__(self):
        flatten_form(self.request)
        self.request.response.setHeader("Content-Type", "application/json")
        from senaite.pfas.browser.perms import disable_csrf
        disable_csrf(self.request)

        q = (self.request.get("q") or u"").lower().strip()

        portal = getToolByName(self.context, "portal_url").getPortalObject()
        folder = portal.get("pfas_reagents")
        if not folder:
            return json.dumps([])

        results = []
        for obj in folder.objectValues():
            if obj.portal_type != "Reagent":
                continue
            name = getattr(obj, "title", "") or ""
            lot = getattr(obj, "lot_number", "") or ""
            if q and q not in name.lower() and q not in lot.lower():
                continue
            results.append({
                "name":       name,
                "lot_number": lot,
                "supplier":   getattr(obj, "supplier", "") or "",
                "status":     (getattr(obj, "status", "active") or "active"),
            })
        results.sort(key=lambda x: x["name"])
        return json.dumps(results[:50])
