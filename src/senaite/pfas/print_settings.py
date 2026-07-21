# -*- coding: utf-8 -*-
"""
Print template settings — single source for how EVERY printable form renders
(logbooks FM-ENV-25x, CoC / sample receipt, extraction reports, SOP copies).

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

DEFAULTS = {
    "lab_name":        "Pine State Laboratories",
    "lab_address":     "",
    "lab_phone":       "",
    "lab_email":       "",
    "logo_url":        "",            # absolute or portal-relative image URL
    "accreditation":   "",            # e.g. "ISO/IEC 17025:2017 — Cert #XXXX"
    "footer_text":     "Controlled document — printed copies are uncontrolled unless stamped.",
    "show_form_code":  True,          # FM-ENV-xxx block top-right
    "show_print_date": True,
    "show_page_footer": True,
}


def get_print_settings(portal):
    """Merged settings dict (saved values over DEFAULTS)."""
    from zope.annotation.interfaces import IAnnotations
    out = dict(DEFAULTS)
    try:
        raw = IAnnotations(portal).get(PRINT_SETTINGS_KEY)
        if raw:
            out.update(json.loads(raw))
    except Exception as exc:
        logger.warning("get_print_settings: %s", exc)
    return out


def save_print_settings(portal, data):
    """Persist settings (only known keys; replaces entry atomically)."""
    from zope.annotation.interfaces import IAnnotations
    clean = {k: data[k] for k in DEFAULTS if k in data}
    IAnnotations(portal)[PRINT_SETTINGS_KEY] = json.dumps(clean)
    return clean
