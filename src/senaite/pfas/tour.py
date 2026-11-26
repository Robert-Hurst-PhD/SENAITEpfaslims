# -*- coding: utf-8 -*-
"""The system tour (@@pfas-tour): ten stops through the lab's work, for a
visitor who reads the system rather than uses it.

A stop is data. STOPS holds the defaults: an icon (icons.py), a title, two
plain lines on what it shows, and one or more targets, each a page under the
site. A target can be pointed at one record (a worksheet, a sample, a
certificate) by an override kept on the site, a JSON value at KEY:

    {"<target key>": {"path": "worksheets/WS-1", "caption": "A finished run"}}

A target's key is its stop's key; the extra targets of a stop are
"<stop key>.<name>". An override holds a path under the site and nothing
else: never a full address, a scheme, a leading slash or a step up the tree
(clean_path), so a tour cannot send a visitor off the site.

    visible_to(roles)                    whether a person is shown the tour
    load(raw)                            the overrides, as stored
    stops(overrides)                     the ten stops with their targets resolved
    clean_path(text) / clean_caption(text)   (value, "") or (None, why)
    availability(path, roles, can_open)  (True, "") or (False, the reason)
    dump(overrides)                      the JSON to store

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import copy
import json
import re

KEY = "senaite.pfas.tour_stops"
CAPTION_MAX = 120

# who is shown the tour: the lab's staff and the read-only inspector; a
# client is not
TOUR_ROLES = frozenset(("Manager", "LabManager", "Analyst", "Verifier", "LabClerk",
                        "RegulatoryInspector"))

# The ten stops, in order. icon: a drawing of icons.py; colour: its token.
STOPS = (
    {"key": "intake", "icon": "custody", "colour": "brand",
     "title": "Chain of custody",
     "lines": ("Every sample enters on a chain of custody that says who handed it over, what was collected and when.",
               "A sample without a completed chain of custody is not received and not analysed."),
     "targets": ({"key": "intake", "label": "Open chain of custody", "path": "@@pfas-coc"},)},
    {"key": "receipt", "icon": "temperature", "colour": "brand",
     "title": "Receipt and temperatures",
     "lines": ("On receipt the lab records the condition and the temperature of what arrived, and starts the holding time clock.",
               "A cooler outside its limit, or a sample past its holding time, is flagged before any work starts."),
     "targets": ({"key": "receipt", "label": "Open receipt", "path": "@@pfas-receipt"},)},
    {"key": "worksheet", "icon": "extraction", "colour": "brand",
     "title": "Worksheet and extraction",
     "lines": ("A worksheet gathers samples and their QC for one method. The extraction log records every lot, volume and deviation.",
               "That is how a result is traced back to the reagents and standards behind it."),
     "targets": ({"key": "worksheet", "label": "Open extraction", "path": "@@pfas-extraction-guide"},)},
    {"key": "import", "icon": "analysis", "colour": "brand",
     "title": "Run import and peak review",
     "lines": ("Instrument files are read through saved layouts and never guessed. Each peak can be reviewed and reintegrated.",
               "Every change keeps who made it, when and why."),
     "targets": ({"key": "import", "label": "Open import", "path": "@@pfas-import-studio"},)},
    {"key": "review", "icon": "verify", "colour": "brand",
     "title": "QC and Data Review gates",
     "lines": ("The QC engine judges each result against the limits of its method.",
               "Data Review's checks must pass, or be excused with a recorded reason, before anything is released."),
     "targets": ({"key": "review", "label": "Open Data Review", "path": "@@pfas-data-review"},)},
    {"key": "profiles", "icon": "settings", "colour": "brand",
     "title": "Method profiles",
     "lines": ("A method profile holds every criterion in one place: analytes, internal standards, recovery limits and reporting limits.",
               "Nothing a lab might change is fixed in the program."),
     "targets": ({"key": "profiles", "label": "Open method profiles", "path": "@@pfas-method-profiles"},)},
    {"key": "certificate", "icon": "issued", "colour": "brand",
     "title": "Certificate and report levels",
     "lines": ("The certificate states each result with its qualifiers and limits. Report levels T1 to T4 add more of the supporting evidence.",
               "An issued certificate is sealed and can be checked later."),
     "targets": ({"key": "certificate", "label": "Open certificates", "path": "@@pfas-controlled-publications"},)},
    {"key": "edd", "icon": "edd", "colour": "brand",
     "title": "The EDD",
     "lines": ("The electronic data deliverable hands the same results to a state or a client in their own file layout.",
               "It is built from the data behind the certificate, so the two cannot disagree."),
     "targets": ({"key": "edd", "label": "Open EDD settings", "path": "@@pfas-edd-config"},)},
    {"key": "integrity", "icon": "sig-signed", "colour": "brand",
     "title": "Data integrity",
     "lines": ("Signatures go into an append-only ledger. Configuration changes, corrections and deviations keep who, when and why.",
               "SOPs, equipment records and temperature logs are held with them."),
     "targets": ({"key": "integrity", "label": "Signatures", "path": "@@pfas-signatures"},
                 {"key": "integrity.history", "label": "Configuration history", "path": "@@pfas-config-history"},
                 {"key": "integrity.corrections", "label": "Corrections", "path": "@@pfas-batch-records"},
                 {"key": "integrity.sops", "label": "SOPs", "path": "@@pfas-sop"},
                 {"key": "integrity.equipment", "label": "Equipment", "path": "@@pfas-equipment"},
                 {"key": "integrity.temperatures", "label": "Temperature logs", "path": "@@pfas-temperature-log"})},
    {"key": "portal", "icon": "person", "colour": "brand",
     "title": "Client portal",
     "lines": ("Clients see only their own samples and issued reports, with a plain status.",
               "A tracking number alone shows progress without signing in."),
     "targets": ({"key": "portal", "label": "Open client portal", "path": "@@pfas-track"},)},
)

STOP_KEYS = tuple(s["key"] for s in STOPS)
TARGET_KEYS = tuple(t["key"] for s in STOPS for t in s["targets"])

_SEGMENT = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@_.%+~-]*$")
_QUERY = re.compile(r"^[A-Za-z0-9_=&.%+,-]*$")


def visible_to(roles):
    """True when a person holding these roles is shown the tour."""
    return bool(set(roles or ()) & TOUR_ROLES)


def clean_path(text):
    """(path, "") for a path under the site, else (None, why). Refused: an
    address with a scheme or a host, a leading slash, a backslash, a step up
    ("..") or along ("."), a fragment, a space or any control character."""
    raw = ("%s" % (text if text is not None else "")).strip()
    if not raw:
        return None, "A path is needed."
    if "\\" in raw or any(ord(c) < 33 or ord(c) == 127 for c in raw):
        return None, "A path holds no space, backslash or control character."
    if "://" in raw or raw.startswith("//") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", raw):
        return None, "Only a path under this site is allowed, never a full address."
    if raw.startswith("/"):
        return None, "Give the path from the site root without a leading slash."
    if "#" in raw:
        return None, "A path holds no fragment."
    path, _sep, query = raw.partition("?")
    steps = path.split("/")
    for step in steps:
        if step in ("", ".", ".."):
            return None, "A path holds no empty, . or .. step."
        if not _SEGMENT.match(step):
            return None, "A path step holds letters, digits and - _ . @ only."
    if query and not _QUERY.match(query):
        return None, "The query holds letters, digits and = & . , - _ only."
    return raw, ""


def clean_caption(text):
    """(caption, "") of at most CAPTION_MAX characters of plain text, else
    (None, why). An empty caption is no caption."""
    raw = " ".join(("%s" % (text or "")).split())
    if any(ord(c) < 32 for c in raw) or "<" in raw or ">" in raw:
        return None, "A caption is plain text."
    if len(raw) > CAPTION_MAX:
        return None, "A caption is at most %d characters." % CAPTION_MAX
    return raw, ""


def load(raw):
    """The overrides from their stored JSON: {target key: {"path", "caption"}}.
    A key no stop has, a path clean_path refuses and a value that does not
    parse are dropped, so a bad record shows the default rather than a
    link off the site."""
    try:
        data = json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for key, rec in data.items():
        if key not in TARGET_KEYS or not isinstance(rec, dict):
            continue
        path, why = clean_path(rec.get("path"))
        if path is None:
            continue
        caption, why = clean_caption(rec.get("caption"))
        out[key] = {"path": path, "caption": caption or ""}
    return out


def dump(overrides):
    return json.dumps(overrides, sort_keys=True, separators=(",", ":"))


def stops(overrides=None):
    """The ten stops in order, a copy each, with every target's path as the
    override gives it, `custom` set where it does, and the stop's caption
    (that of its own key's override)."""
    overrides = overrides or {}
    out = []
    for stop in STOPS:
        s = copy.deepcopy(stop)
        s["lines"] = list(s["lines"])
        s["targets"] = list(s["targets"])
        for t in s["targets"]:
            o = overrides.get(t["key"])
            t["custom"] = bool(o)
            if o:
                t["path"] = o["path"]
        s["caption"] = (overrides.get(s["key"]) or {}).get("caption", "")
        out.append(s)
    return out


def _view_of(path):
    first = path.split("?", 1)[0].rstrip("/").rsplit("/", 1)[-1]
    return first[2:] if first.startswith("@@") else first


def object_steps(path):
    """The steps of `path` that name objects, as a list of native strings:
    the query and any @@view step are left out. Zope's traversal takes a
    list; handed a unicode string (Python 2) it walks it one character at a
    time and finds nothing."""
    return [str(step) for step in path.split("?", 1)[0].split("/") if step and not step.startswith("@@")]


def traversal_check(traverse, path):
    """True when the person's own traversal (`traverse(steps)`, a site's
    restrictedTraverse) reaches the objects on `path`; False when it refuses
    them (Unauthorized); None when nothing is there."""
    steps = object_steps(path)
    if not steps:
        return True
    try:
        traverse(steps)
    except Exception as exc:                                # noqa: BLE001
        return False if exc.__class__.__name__ == "Unauthorized" else None
    return True


def availability(path, roles, can_open=None):
    """(True, "") when a person with `roles` can open the page at `path`
    (under the site), else (False, why). The rules are the ones the system
    already applies: the manager's pages (perms), the navigation map
    (page_groups) and, last, `can_open(path)` -- the site's own traversal,
    which raises or answers False when the page is not theirs or not there."""
    from senaite.pfas import page_groups
    from senaite.pfas.browser import perms
    roles = set(roles or ())
    view = _view_of(path)
    manager = bool(roles & set(("Manager", "LabManager")))
    inspector = "RegulatoryInspector" in roles
    if view in perms.MANAGER_VIEWS and not manager and not (inspector and view in perms.INSPECTOR_READ_VIEWS):
        return False, "For lab managers."
    mine = [p["url_path"] for p in page_groups.pages(roles)]
    every = [p["url_path"] for p in page_groups.pages(("Manager",))]
    here = path.split("?", 1)[0]
    if any(page_groups.same_page(here, e) for e in every) and not any(page_groups.same_page(here, m) for m in mine):
        return False, "Not open to your role."
    if can_open is not None:
        try:
            ok = can_open(path)
        except Exception:                                   # noqa: BLE001
            ok = None
        if ok is None:
            return False, "Not found on this site."
        if not ok:
            return False, "Not open to your role."
    return True, ""
