# -*- coding: utf-8 -*-
"""Lab identity: one reader and writer over core's Laboratory record.

The Laboratory (name, registration, contact, accreditation, addresses) and
the site title are core's; this add-on keeps no copy. A page, a print layout
and a certificate read and write them here.
"""
from __future__ import absolute_import, unicode_literals

import hashlib
import json
import logging
import re

logger = logging.getLogger("senaite.pfas.lab_identity")

# (key, core accessor stem, label)
FIELDS = (
    ("name", "Name", "Laboratory name"),
    ("tax_number", "TaxNumber", "Registration number"),
    ("phone", "Phone", "Phone"),
    ("fax", "Fax", "Fax"),
    ("email", "EmailAddress", "E-mail"),
    ("url", "LabURL", "Web address"),
    ("accredited", "LaboratoryAccredited", "Accredited"),
    ("accreditation_body", "AccreditationBody", "Accreditation body"),
    ("accreditation_body_url", "AccreditationBodyURL",
     "Accreditation body web address"),
    ("accreditation", "Accreditation", "Accreditation standard"),
    ("accreditation_reference", "AccreditationReference",
     "Accreditation reference"),
)

ADDRESS_KEYS = ("address", "city", "zip", "state", "district", "country")

STORE = "lab_identity"
KEY = "laboratory"
SITE_TITLE = "plone.site_title"
NEEDS_NAME = "The laboratory needs a name."
# every designed document of a certificate carries the logo: a big one times
# many samples would pass the renderer's request limit at publish
LOGO_MAX_BYTES = 1024 * 1024
BAD_EMAIL = u"Enter a valid e-mail address."
# core's Laboratory e-mail check (Products.validation isEmail), so this page
# accepts what core's own form accepts; an empty address is allowed
EMAIL_RE = re.compile(
    r"^([0-9a-zA-Z_&.'+-]+!)*[0-9a-zA-Z_&.'+-]+@"
    r"(([0-9a-zA-Z]([0-9a-zA-Z-]*[0-9a-z-A-Z])?\.)+[a-zA-Z]{2,}|([0-9]{1,3}\.){3}[0-9]{1,3})$")
LOGO_KIND = u"The logo must be a PNG or JPEG picture."
LOGO_SIZE = u"The logo is larger than 1 MB."


def _text(value):
    if value is None:
        return u""
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return u"{}".format(value)


def _lab():
    from bika.lims import api
    return api.get_setup().laboratory


def _registry():
    from plone.registry.interfaces import IRegistry
    from zope.component import getUtility
    return getUtility(IRegistry)


def _get(lab, stem):
    return lab.getField(stem).get(lab)


def _address(raw):
    raw = raw or {}
    return dict((k, _text(raw.get(k))) for k in ADDRESS_KEYS)


def _print_address(lab):
    """Core's print lines; when core prints none (it needs a city), the
    filled subfields of the postal address, else of the physical one, so an
    address without a city still prints."""
    lines = [_text(line).strip() for line in (lab.getPrintAddress() or [])]
    printed = u", ".join(line for line in lines if line)
    if printed:
        return printed
    for raw in (lab.getPostalAddress(), lab.getPhysicalAddress()):
        parts = [_text((raw or {}).get(k)).strip() for k in ADDRESS_KEYS]
        if any(parts):
            return u", ".join(p for p in parts if p)
    return u""


def _logo_raw():
    from bika.lims import api
    return api.get_senaite_setup().getSiteLogo()


def logo_sha(raw):
    """The first 16 hex of a logo's SHA-256; empty when there is none."""
    return u"%s" % hashlib.sha256(raw).hexdigest()[:16] if raw else u""


def _live_logo_data(portal):
    """The site logo's bytes, or None; an unreadable logo is logged and
    counts as none."""
    try:
        found = logo_bytes(portal)
    except Exception:                                       # noqa: BLE001
        logger.warning("site logo not readable", exc_info=True)
        return None
    return found[1] if found else None


def check_logo(upload):
    """The refusal text for an uploaded logo (filename, bytes), or None. Only
    a PNG or JPEG under the size cap is taken (an SVG can carry script)."""
    from senaite.pfas.coa_document import image_data_uri
    _filename, data = upload
    if not image_data_uri(data):
        return LOGO_KIND
    if len(data) > LOGO_MAX_BYTES:
        return LOGO_SIZE
    return None


def read(portal):
    lab = _lab()
    out = {}
    for key, stem, _label in FIELDS:
        value = _get(lab, stem)
        out[key] = bool(value) if key == "accredited" else _text(value)
    out["physical_address"] = _address(lab.getPhysicalAddress())
    out["postal_address"] = _address(lab.getPostalAddress())
    out["print_address"] = _print_address(lab)
    parts = [out["accreditation"], out["accreditation_body"],
             out["accreditation_reference"]]
    out["accreditation_line"] = (
        u" — ".join(p for p in parts if p) if out["accredited"] else u"")
    out["logo_url"] = u"@@site-logo" if _logo_raw() else u""
    try:
        out["supervisor_uid"] = _text(lab.getSupervisor().UID())
    except Exception:                                       # noqa: BLE001
        out["supervisor_uid"] = u""
    return out


def mail_prefix(portal):
    """The bracketed prefix of a notice e-mail subject: the laboratory's
    name, else the site title, else "LIMS"."""
    name = u""
    try:
        name = read(portal)["name"].strip()
    except Exception:                                       # noqa: BLE001
        logger.warning("laboratory name not readable", exc_info=True)
    if not name:
        try:
            name = _text(_registry()[SITE_TITLE]).strip()
        except Exception:                                   # noqa: BLE001
            name = u""
    return u"[%s]" % (name or u"LIMS")


def print_fields(portal):
    """The values print layouts use, under the legacy Print Settings keys,
    with the logo's fingerprint, so an issued revision names the logo it was
    issued with."""
    cur = read(portal)
    return {
        "logo_sha": logo_sha(_live_logo_data(portal)) if cur["logo_url"] else u"",
        "lab_name": cur["name"],
        "lab_address": cur["print_address"],
        "lab_phone": cur["phone"],
        "lab_email": cur["email"],
        "logo_url": cur["logo_url"],
        "accreditation": cur["accreditation_line"],
    }


def _state(portal):
    cur = read(portal)
    keep = [k for k, _s, _l in FIELDS] + ["physical_address", "postal_address"]
    state = dict((k, cur[k]) for k in keep)
    try:
        state["site_title"] = _text(_registry()[SITE_TITLE])
    except Exception:                                       # noqa: BLE001
        state["site_title"] = u""
    state["supervisor_uid"] = cur["supervisor_uid"]
    # the logo is SENAITE's site logo: its fingerprint records a change
    state["logo_sha"] = logo_sha(_live_logo_data(portal))
    return state


NOT_A_LOGIN = u"The Supervisor must be an active person who can sign in."


def director_userid(portal):
    """The user name of the Supervisor contact's linked user; empty when
    there is no Supervisor, the contact is inactive or has no account."""
    from bika.lims import api
    try:
        contact = _lab().getSupervisor()
        if not contact or not api.is_active(contact):
            return u""
        username = _text(contact.getUsername()).strip()
        if username and api.get_user(username) is not None:
            return username
    except Exception:                                       # noqa: BLE001
        logger.warning("supervisor not readable", exc_info=True)
    return u""


def set_supervisor(portal, contact_uid):
    """Make a contact the Laboratory's Supervisor (an empty uid clears it).
    Only an active contact with a login is accepted. Returns an error text
    or None."""
    from senaite.pfas import config_history, staff
    contact_uid = _text(contact_uid).strip()
    if contact_uid and contact_uid not in [
            d["uid"] for d in staff.list_staff(portal, active_with_login=True)]:
        return NOT_A_LOGIN
    config_history.track(portal, STORE, KEY, lambda: _state(portal),
                         label=u"Laboratory", action=u"Supervisor")
    lab = _lab()
    lab.getField("Supervisor").set(lab, contact_uid or None)
    lab.reindexObject()
    return None


def save(portal, values, reason=u""):
    """Write the Laboratory, the site title and, when values carry "logo"
    (filename, bytes), the site logo. Returns a list of errors; a blank name
    or a refused logo writes nothing."""
    name = _text(values.get("name")).strip()
    if not name:
        return [NEEDS_NAME]
    email = _text(values.get("email")).strip()
    if email and not EMAIL_RE.match(email):
        return [BAD_EMAIL]
    upload = values.get("logo")
    if upload:
        refusal = check_logo(upload)
        if refusal:
            return [refusal]
    from senaite.pfas import config_history
    config_history.track(portal, STORE, KEY, lambda: _state(portal),
                         label=u"Laboratory", action=u"", reason=reason)
    lab = _lab()
    for key, stem, _label in FIELDS:
        if key not in values:
            continue
        value = values[key]
        if key == "name":
            value = name
        elif key == "accredited":
            value = bool(value)
        else:
            value = _text(value).strip()
        lab.getField(stem).set(lab, value)
    if "physical_address" in values:
        lab.setPhysicalAddress(_address(values["physical_address"]))
    if "postal_address" in values:
        lab.setPostalAddress(_address(values["postal_address"]))
    _registry()[SITE_TITLE] = name
    if upload:
        from bika.lims import api
        from plone.formwidget.namedfile.converter import b64encode_file
        api.get_senaite_setup().setSiteLogo(b64encode_file(upload[0] or u"logo", upload[1]))
    lab.reindexObject()
    return []


def on_laboratory_modified(lab, event):
    """Core's own Laboratory form saved: the site title follows the
    laboratory's name; a blank name leaves it alone. A failure is logged and
    never stops core's save."""
    try:
        name = _text(_get(lab, "Name")).strip()
        if not name:
            return
        registry = _registry()
        if _text(registry[SITE_TITLE]) != name:
            registry[SITE_TITLE] = name
    except Exception:                                       # noqa: BLE001
        logger.warning("site title not kept to the laboratory name", exc_info=True)


def logo_bytes(portal):
    """(filename, bytes) of the site logo, or None."""
    raw = _logo_raw()
    if not raw:
        return None
    from plone.formwidget.namedfile.converter import b64decode_file
    filename, data = b64decode_file(raw)
    return filename, data


LOGO_VERSIONS = "senaite.pfas.logo_versions"


def _logo_versions(portal):
    from zope.annotation.interfaces import IAnnotations
    try:
        return json.loads(IAnnotations(portal).get(LOGO_VERSIONS) or u"{}")
    except (TypeError, ValueError):
        return {}


def keep_logo_version(portal, sha):
    """Store the live logo once under its fingerprint when it is the logo
    `sha` names, so a revision issued with it keeps printing it after the
    site logo is replaced. Returns True when it stored something."""
    if not sha:
        return False
    versions = _logo_versions(portal)
    if sha in versions:
        return False
    found = logo_bytes(portal)
    if not found or logo_sha(found[1]) != sha:
        logger.warning("logo %s is not the site logo: not kept", sha)
        return False
    from plone.formwidget.namedfile.converter import b64encode_file
    from zope.annotation.interfaces import IAnnotations
    encoded = b64encode_file(found[0] or u"logo", found[1])
    if isinstance(encoded, bytes):
        encoded = encoded.decode("ascii")
    versions = dict(versions)
    versions[sha] = encoded
    IAnnotations(portal)[LOGO_VERSIONS] = json.dumps(versions)
    return True


def logo_for_sha(portal, sha):
    """The bytes of the logo a fingerprint names: the live logo when it is
    that one, else the kept version, else None."""
    live = _live_logo_data(portal)
    if live and logo_sha(live) == sha:
        return live
    encoded = _logo_versions(portal).get(sha)
    if not encoded:
        return None
    from plone.formwidget.namedfile.converter import b64decode_file
    return b64decode_file(encoded.encode("ascii"))[1]


PRINT_SETTINGS_KEY = "senaite.pfas.print_settings"
LEGACY_KEYS = ("lab_address", "lab_phone", "lab_email", "accreditation",
               "logo_url")
SITE_LOGO = u"@@site-logo"
MIGRATED = u"moved from Print Settings"
EDIT_ROLES = ("LabManager", "Manager", "Site Administrator")
EDIT_PERMISSIONS = ("Modify portal content", "senaite.core: Manage Bika")
LAB_WORKFLOW = "senaite_laboratory_workflow"


def legacy_logo_bytes(portal, url):
    """The bytes of an image on this site named by a portal-relative path or
    a URL on this portal, or None. The server never fetches an outside
    address."""
    url = (url or u"").strip()
    if not url or url == SITE_LOGO:
        return None
    base = portal.absolute_url() if hasattr(portal, "absolute_url") else u""
    if base and url.startswith(base):
        url = url[len(base):]
    elif "://" in url or url.startswith("//"):
        logger.warning("logo %s is not on this site", url)
        return None
    path = str(url.split("?")[0].lstrip("/"))
    try:
        obj = portal.unrestrictedTraverse(path)
    except Exception:                                       # noqa: BLE001
        logger.warning("logo %s not found", url)
        return None
    from senaite.pfas.browser.staff import image_bytes
    for candidate in (obj, getattr(obj, "image", None)):
        raw = image_bytes(candidate) if candidate is not None else None
        if raw:
            return raw
    return None


def _empty_supervisor(lab):
    try:
        return not lab.getSupervisor()
    except Exception:                                       # noqa: BLE001
        return True


def migrate_print_identity(portal):
    """Move Print Settings' identity copies (and the Director) into the
    Laboratory. A legacy value goes only into an empty core field, so a
    re-run never overwrites what the lab has since set. Returns the names of
    the core fields filled."""
    from bika.lims import api
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas import config_history
    from senaite.pfas.browser import staff

    ann = IAnnotations(portal)
    try:
        stored = json.loads(ann.get(PRINT_SETTINGS_KEY) or "{}")
    except (ValueError, TypeError):
        stored = {}
    if not isinstance(stored, dict):
        stored = {}
    legacy = dict((k, stored[k]) for k in LEGACY_KEYS if k in stored)
    director = ann.get(staff.DIRECTOR_KEY) or u""
    lab = _lab()
    setup = api.get_senaite_setup()

    def value(key):
        return _text(legacy.get(key)).strip()

    plan = []                       # (core name, writer)
    for key, stem in (("lab_phone", "Phone"), ("lab_email", "EmailAddress")):
        if value(key) and not _text(_get(lab, stem)).strip():
            plan.append((stem, lambda v=value(key), s=stem:
                         lab.getField(s).set(lab, v)))
    phys = lab.getPhysicalAddress() or {}
    if value("lab_address") and not _text(phys.get("address")).strip():
        plan.append((u"PhysicalAddress", lambda: lab.setPhysicalAddress(
            dict(phys, address=value("lab_address")))))
    if value("accreditation") and not _text(_get(lab, "Accreditation")).strip():
        def write_accreditation():
            lab.getField("Accreditation").set(lab, value("accreditation"))
            lab.getField("LaboratoryAccredited").set(lab, True)
        plan.append((u"Accreditation", write_accreditation))
    logo_url, logo_data = value("logo_url"), None
    if logo_url and logo_url != SITE_LOGO and not _logo_raw():
        logo_data = legacy_logo_bytes(portal, logo_url)
        if logo_data:
            from plone.formwidget.namedfile.converter import b64encode_file
            name = logo_url.split("?")[0].rstrip("/").split("/")[-1] or u"logo"
            plan.append((u"SiteLogo", lambda: setup.setSiteLogo(
                b64encode_file(name, logo_data))))
    supervisor = None
    if director and _empty_supervisor(lab):
        contact = staff.contact_for(director)
        if contact is not None:
            supervisor = contact.UID()
            plan.append((u"Supervisor", lambda: lab.getField("Supervisor").set(
                lab, supervisor)))

    rest = dict((k, v) for k, v in stored.items() if k not in LEGACY_KEYS)
    if logo_url and logo_url != SITE_LOGO and not logo_data and not _logo_raw():
        rest["logo_url"] = stored["logo_url"]               # not found: keep
    # once the Laboratory has a Supervisor the old Director goes, so a later
    # run cannot bring it back
    drop_director = bool(director) and (
        supervisor is not None or not _empty_supervisor(lab))

    if plan or rest != stored or drop_director:
        # the history's "before" carries every old Print Settings value and
        # the old Director, so nothing the move removes is lost, also a
        # value that lost to a filled core field
        holder = {"v": dict(legacy, director=director)}

        def getter():
            state = _state(portal)
            state["print_settings"] = holder["v"]
            return state
        config_history.track(portal, STORE, KEY, getter, label=u"Laboratory",
                             action=MIGRATED)
        for _name, write in plan:
            write()
        holder["v"] = {}
        if plan:
            lab.reindexObject()

    if rest != stored:
        ann[PRINT_SETTINGS_KEY] = json.dumps(rest)
    if drop_director:
        del ann[staff.DIRECTOR_KEY]
    return [name for name, _w in plan]


def restrict_laboratory_edit(portal):
    """Only Lab Manager, Manager and Site Administrator edit the Laboratory:
    the laboratory workflow's edit permissions are set for those roles and
    not acquired. Returns True when it changed anything."""
    from bika.lims import api
    wf = api.get_tool("portal_workflow").getWorkflowById(LAB_WORKFLOW)
    state = wf.states["active"]
    changed = False
    for perm in EDIT_PERMISSIONS:
        if perm not in wf.permissions:
            wf.permissions = tuple(wf.permissions) + (perm,)
            changed = True
        info = state.getPermissionInfo(perm)
        if info["acquired"] or tuple(info["roles"]) != EDIT_ROLES:
            state.setPermission(perm, 0, EDIT_ROLES)
            changed = True
    # run every time: it repairs an object whose stored roles are stale
    lab = api.get_setup().laboratory
    updated = wf.updateRoleMappingsFor(lab)
    if hasattr(lab, "reindexObjectSecurity"):
        lab.reindexObjectSecurity()
    return bool(changed or updated)
