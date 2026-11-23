# -*- coding: utf-8 -*-
"""Where the instrument's raw data is pulled from (System).

    share_path       the folder a run is pulled from when its instrument has
                     no folder of its own: an absolute path (the folder the
                     laboratory had before instruments held their own)
    settle_minutes   how long a run's raw folders must be unchanged before
                     they are pulled: a whole number of minutes, 1 or more
    delete_reinjection_files
                     whether an archived re-injection file whose results
                     were not reported and no corrective action claims is
                     deleted once its worksheet is verified
                     (instrument_files.decide): off unless turned on

Each analytical instrument (a core Instrument whose Instrument Type is of the
kind "analytical") holds its own raw data folder on its equipment record
(browser/equipment.py, "raw_folder"): a run is pulled from the folder of its
worksheet's instrument, else from share_path. The worker pulls nothing for a
run that has neither, nor until the settle time is set.

Kept on the portal and exported as JSON for the worker (its pull,
pfas_pipeline.raw_pull, reads the export):

    {"share_path", "settle_minutes", "delete_reinjection_files",
     "instruments": {instrument uid: {"name", "folder"}}}

The first three keys are what the export always held, so a worker that has
not learnt "instruments" still reads it. Pure apart from load/save and the
equipment lookup; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

import json
import os

KEY = "senaite.pfas.raw_share"
EXPORT = os.environ.get("PFAS_RAW_SHARE_EXPORT", "/data/qc/raw_share.json")
FIELDS = ("share_path", "settle_minutes", "delete_reinjection_files")


def settings(stored):
    stored = stored or {}
    out = dict((k, stored.get(k)) for k in FIELDS)
    # a switch: off unless turned on
    out["delete_reinjection_files"] = stored.get("delete_reinjection_files") is True
    return out


def from_form(form):
    """(settings, errors) from the System form; blank is unset."""
    path = (form.get("raw_share_path") or "").strip() or None
    minutes = (form.get("raw_settle_minutes") or "").strip() or None
    errors = []
    if path is not None and not path.startswith("/"):
        errors.append("The raw-data share is an absolute path, e.g. /mnt/lcms/data.")
    if minutes is not None:
        try:
            minutes = int(minutes)
            if minutes < 1:
                raise ValueError(minutes)
        except ValueError:
            errors.append("The settle time is a whole number of minutes, 1 or more.")
    return {"share_path": path, "settle_minutes": minutes,
            "delete_reinjection_files": form.get("raw_delete_reinjection_files") == "yes"}, errors


def folder_error(path):
    """Why `path` cannot be an instrument's raw data folder, or None; a blank
    path is no folder, not an error."""
    path = (path or "").strip()
    if path and not path.startswith("/"):
        return "The raw data folder is an absolute path, e.g. /mnt/lcms/data/instrument-1."
    return None


def instruments(portal):
    """The analytical instruments with their folders, by name:
    [{"uid", "name", "type", "folder"}]; folder is None when the instrument
    has none."""
    from senaite.pfas.browser import equipment
    out = []
    for u in equipment.list_units(True):
        if u.get("unit_type") != "analytical":
            continue
        out.append({"uid": u["id"], "name": u["name"], "type": u.get("type_title") or "",
                    "folder": (u.get("raw_folder") or "").strip() or None})
    return out


def _instrument_map(rows):
    return dict((r["uid"], {"name": r["name"], "folder": r["folder"]}) for r in rows)


def export(values, path=None, instrument_rows=None):
    """Write the worker's copy. `instrument_rows` (instruments()) adds the
    instruments; without them the export is the lab-wide settings alone."""
    path = path or EXPORT
    tmp = path + ".tmp"
    out = settings(values)
    if instrument_rows is not None:
        out["instruments"] = _instrument_map(instrument_rows)
    with open(tmp, "w") as fh:
        json.dump(out, fh, sort_keys=True)
    os.rename(tmp, path)


def pull_state(upload_dir):
    """{instrument uid: {"last": the UTC time of its newest pull, "waiting":
    runs expected and not yet pulled}} from the worker's files in the
    instrument upload folder. A run records its instrument in its manifest
    (.rawrun), or in its run record (_extraction.json) when it predates that."""
    out = {}

    def read(path):
        try:
            with open(path) as fh:
                return json.load(fh) or {}
        except (IOError, OSError, ValueError):
            return {}

    try:
        names = sorted(os.listdir(upload_dir))
    except OSError:
        return out
    have = set(names)
    for name in names:
        for suffix in (".rawrun", ".rawexpect.json"):
            if not name.endswith(suffix):
                continue
            stem = name[:-len(suffix)]
            if suffix == ".rawexpect.json" and (stem + ".rawrun" in have or stem + ".rawfail" in have):
                continue
            data = read(os.path.join(upload_dir, name))
            uid = data.get("instrument") if suffix == ".rawrun" else None
            if not uid:
                record = data.get("run_record") if suffix == ".rawexpect.json" else \
                    read(os.path.join(upload_dir, stem + "_extraction.json"))
                uid = (record or {}).get("instrument_uid")
            if not uid:
                continue
            row = out.setdefault(uid, {"last": None, "waiting": 0})
            if suffix == ".rawexpect.json":
                row["waiting"] += 1
            else:
                at = (data.get("converter") or {}).get("at")
                if at and (row["last"] is None or at > row["last"]):
                    row["last"] = at
    return out


def card_rows(rows, fallback, state):
    """The System card's list: one row per analytical instrument,
    [{"name", "type", "folder", "status", "last"}]. status is "Watching" (it
    has a folder), "Default folder" (none of its own, pulled from
    `fallback`), or "No folder"; last is the UTC time of its newest pull."""
    out = []
    for r in rows:
        if r["folder"]:
            status = "Watching"
        elif fallback:
            status = "Default folder"
        else:
            status = "No folder"
        out.append({"name": r["name"], "type": r["type"], "folder": r["folder"] or fallback or "",
                    "status": status, "last": (state.get(r["uid"]) or {}).get("last"),
                    "waiting": (state.get(r["uid"]) or {}).get("waiting", 0)})
    return out


def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def load(portal):
    try:
        return settings(json.loads(_ann(portal).get(KEY) or "{}"))
    except ValueError:
        return settings({})


def save(portal, values):
    from senaite.pfas import after_commit
    _ann(portal)[KEY] = json.dumps(settings(values), sort_keys=True)
    after_commit.run_once("raw share export", export, values, None, instruments(portal))


def export_again(portal):
    """The worker's copy after an instrument's folder changed."""
    from senaite.pfas import after_commit
    after_commit.run_once("raw share export", export, load(portal), None, instruments(portal))
