# -*- coding: utf-8 -*-
"""
Print template settings — single source for how EVERY printable form renders
(records, CoC / sample receipt, extraction reports, SOP copies).

Editable at Configuration → Print Settings (@@pfas-print-settings); consumed by
the shared `printhead` macro in pfas_macros.pt, so a standard form and a CoC
print with the same header/footer — the consistency an auditor expects when
requesting copies.

Storage: IAnnotations(portal)["senaite.pfas.print_settings"] (JSON string).
Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import json
import logging

logger = logging.getLogger("senaite.pfas.print_settings")

PRINT_SETTINGS_KEY = "senaite.pfas.print_settings"

from senaite.pfas import qs_statement as _qs

DEFAULTS = {
    # the six identity keys are core's Laboratory and site logo, read through
    # lab_identity on every call and never stored here
    "lab_name":        "",
    "lab_address":     "",
    "lab_phone":       "",
    "lab_email":       "",
    "logo_url":        "",
    "accreditation":   "",
    # no footer text, page footer or print date setting: every controlled
    # print carries the control block and its own footer line (print_doc)
    # QA sign-off attestation (rendered on SOPs, prep logs, prepared standards):
    # who signs as Quality Assurance Officer, stored as the LabContact's
    # initials (staff pool key); their uploaded Signature image is the stamp.
    # The Laboratory Director is the Laboratory page's (one place). Empty → the
    # sign-off block prints a blank ruled line.
    "qao_initials":       "",
    "show_signoff":       True,
    # Certificate sign-off layout (lab-wide). The certificate's results-table
    # format (CAS / MDL / dilution columns, non-detect format, significant
    # figures, regulatory notes, standard note) is set PER METHOD x MATRIX on
    # each method profile's Reporting tab (report_format.py).
    "coa_signature_style": "compact", # compact = one line per signatory | full
    # Which quality system the results were produced under (qs_statement.py): internal, or the batch's project QAPP.
    "coa_qs_internal": _qs.DEFAULT_INTERNAL,
    "coa_qs_qapp": _qs.DEFAULT_QAPP,
}


def get_signoff_signers(portal):
    """Resolve the QAO + Laboratory Director attestation signers, as staff
    dicts ({fullname, signature_url, job_title, placeholder, ...}) or None:
    the QAO from Print Settings, the Director from Laboratory; stamps:
    staff pool (LabContact Signature)."""
    from senaite.pfas.staff import find_by_initials
    ps = get_print_settings(portal)
    return {
        "qao": find_by_initials(portal, ps.get("qao_initials")),
        "director": director_staff(portal),
    }


def director_staff(portal):
    """The Laboratory page director as a staff dict, or None."""
    from senaite.pfas.browser.staff import contact_for, director_userid
    from senaite.pfas.staff import staff_record
    contact = contact_for(director_userid())
    return staff_record(contact) if contact is not None else None


IDENTITY_KEYS = ("lab_name", "lab_address", "lab_phone", "lab_email",
                 "logo_url", "accreditation")


def logo_src(settings, portal_url):
    """The logo as an <img src>: a relative value (the site logo) is resolved
    against the portal, so it works under any page URL; the stored value
    stays portal-relative so a frozen revision carries no host name."""
    value = (settings.get("logo_url") or u"").strip()
    if not value or value.startswith(("http://", "https://", "//", "data:")):
        return value
    return u"{}/{}".format(portal_url.rstrip("/"), value.lstrip("/"))


def get_print_settings(portal):
    """Merged settings dict (saved values over DEFAULTS); the identity keys
    are always core's, whatever is stored."""
    from senaite.pfas import lab_identity
    from zope.annotation.interfaces import IAnnotations
    out = dict(DEFAULTS)
    try:
        raw = IAnnotations(portal).get(PRINT_SETTINGS_KEY)
        if raw:
            # a key no longer in DEFAULTS is a retired setting: not read back
            out.update((k, v) for k, v in json.loads(raw).items() if k in DEFAULTS)
    except (ValueError, TypeError) as exc:
        logger.warning("get_print_settings: %s", exc)
    out.update(lab_identity.print_fields(portal))
    return out


def save_print_settings(portal, data):
    """Persist settings (only known, non-identity keys; replaces entry atomically)."""
    # the change history is strict: when its entry cannot be prepared the
    # save does not happen
    from senaite.pfas import config_history
    config_history.track(portal, 'print_settings', "lab", lambda: get_print_settings(portal), label=u"Print & certificate settings")
    from zope.annotation.interfaces import IAnnotations
    clean = {k: data[k] for k in DEFAULTS if k in data and k not in IDENTITY_KEYS}
    IAnnotations(portal)[PRINT_SETTINGS_KEY] = json.dumps(clean)
    return clean
