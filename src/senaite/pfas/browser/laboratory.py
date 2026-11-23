# -*- coding: utf-8 -*-
"""@@pfas-laboratory: the laboratory's identity, one page over core's
Laboratory record.

The record itself (name, registration, addresses, contact, accreditation and
the Supervisor who is the Director) stays core's; lab_identity reads and
writes it, so this page keeps no copy. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

from plone.protect import CheckAuthenticator
from Products.Five.browser import BrowserView
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from zExceptions import Forbidden

from senaite.pfas.browser.formutil import flatten_form
from senaite.pfas.browser.perms import TIER_CONFIG, GateMixin, deny_gated_action, refuse
from senaite.pfas.browser.view_helpers import ViewHelpers

LAB_GATES = {"save": TIER_CONFIG}

ADDRESS_FIELDS = (
    ("address", "Street address"),
    ("city", "City"),
    ("zip", "Postal code"),
    ("state", "State or province"),
    ("district", "District"),
    ("country", "Country"),
)

# the values print layouts take from the identity, as issued with a revision;
# the logo picture is named by its fingerprint
# what an issued revision freezes and this page compares with it; the name
# and address print from this record whatever revision is issued
PRINT_LABELS = (
    ("lab_phone", "Phone"),
    ("lab_email", "E-mail"),
    ("logo_url", "Logo"),
    ("logo_sha", "Logo picture"),
    ("accreditation", "Accreditation"),
)


def _text(value):
    if value is None:
        return u""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return u"{}".format(value)


def values_from_form(form):
    """What lab_identity.save takes: the plain fields, the two addresses
    (fields named physical_address.city and so on) and the Accredited switch,
    which is absent from the form when off."""
    from senaite.pfas import lab_identity
    values = {}
    for key, _stem, _label in lab_identity.FIELDS:
        if key == "accredited":
            values[key] = bool(form.get(key))
        else:
            values[key] = _text(form.get(key))
    for which in ("physical_address", "postal_address"):
        values[which] = dict(
            (k, _text(form.get("{}.{}".format(which, k)))) for k in lab_identity.ADDRESS_KEYS)
    return values


def logo_upload(form):
    """(file name, bytes) of a logo chosen on the form, or None when no file
    was chosen (the logo then stays as it is)."""
    f = form.get("logo")
    if f is None or not hasattr(f, "read"):
        return None
    try:
        f.seek(0)
    except Exception:                                       # noqa: BLE001
        pass
    data = f.read()
    if not data:
        return None
    # a browser may send the full client path
    name = _text(getattr(f, "filename", u"")).replace(u"\\", u"/").split(u"/")[-1]
    return name or u"logo", data


class PFASLaboratoryView(ViewHelpers, GateMixin, BrowserView):

    template = ViewPageTemplateFile("templates/laboratory.pt")
    _message = u""
    _posted = None

    def __call__(self):
        flatten_form(self.request)
        req = self.request
        action = req.form.get("action", "")
        if req.method == "POST":
            denied = deny_gated_action(self.context, req, action, LAB_GATES)
            if denied is not None:
                return denied
            try:
                CheckAuthenticator(req)
            except Forbidden:
                return refuse(req)
            if action == "save":
                errors = self._save(req.form)
                if errors:
                    self._message = u" ".join(errors)
                    self._posted = values_from_form(req.form)
                    self._posted["supervisor_uid"] = _text(req.form.get("supervisor")).strip()
                    return self.template()
                req.response.redirect("%s/@@pfas-laboratory?saved=1" % self.portal_url())
                return ""
        return self.template()

    def _save(self, form):
        """Errors as a list. The Director choice is checked before anything
        is written, so a refused choice leaves the record untouched."""
        from senaite.pfas import lab_identity
        from senaite.pfas.staff import list_staff
        portal = self._portal()
        uid = _text(form.get("supervisor")).strip() if "supervisor" in form else None
        if uid and uid not in [d["uid"] for d in list_staff(portal, active_with_login=True)]:
            return [lab_identity.NOT_A_LOGIN]
        values = values_from_form(form)
        upload = logo_upload(form)
        if upload is not None:
            values["logo"] = upload
        errors = list(lab_identity.save(portal, values))
        if not errors and uid is not None:
            error = lab_identity.set_supervisor(portal, uid)
            if error:
                errors.append(error)
        return errors

    def message(self):
        return self._message

    def saved(self):
        return bool(self.request.form.get("saved"))

    def lab(self):
        from senaite.pfas import lab_identity
        current = lab_identity.read(self._portal())
        if self._posted is not None:        # a refused save shows what was typed
            current.update(self._posted)
        return current

    def address_fields(self):
        return ADDRESS_FIELDS

    def director_choices(self):
        """[(contact uid, name)] of active people who can sign in."""
        from senaite.pfas.staff import list_staff
        return [(d["uid"], d["fullname"])
                for d in list_staff(self._portal(), active_with_login=True)]

    def revision_differences(self):
        """[{"field", "issued", "now"}] for each identity value that differs
        from the latest issued report-template revision; empty when none is
        issued or nothing differs."""
        from senaite.pfas import lab_identity, report_templates
        portal = self._portal()
        snapshot, _rev = report_templates.issued_snapshot(portal)
        if not snapshot:
            return []
        issued = snapshot.get("print_settings") or {}
        now = lab_identity.print_fields(portal)
        out = []
        for key, label in PRINT_LABELS:
            if _text(issued.get(key)) != _text(now.get(key)):
                out.append({"field": label, "issued": _text(issued.get(key)),
                            "now": _text(now.get(key))})
        return out
