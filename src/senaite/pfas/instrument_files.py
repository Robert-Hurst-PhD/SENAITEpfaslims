# -*- coding: utf-8 -*-
"""The instrument export files a run is imported from: kept as long as the
records of their run, moved to the archive once processed.

    folder        the upload folder the worker watches (run_builder
                  UPLOAD_DIR, the worker's WATCH_DIR: one volume)
    archive       <folder>/archive: an export the worker imported is moved
                  there (`archive`), so the folder holds only what waits;
                  a file of the same name already there with other content
                  is kept under <folder>/archive/<its first 12 sha256
                  characters>/<name>. Only an export moves (EXPORT_SUFFIXES):
                  a raw run's record (.rawrun), its edits (.overrides.json),
                  the sidecars (_extraction.json, .rawexpect.json) and the
                  raw folders stay where the run reads them.
    locate        a record names a file by its base name: the folder first,
                  then the archive.

A re-injection's file is not kept unless its results were reported or a
corrective action uses it:

    re-injection file  an upload Run Builder recorded (its worksheet's run
                  files, RUN_FILES_KEY) as a follow-up ("supplementary") run
                  that carried the requests it names, at least one, every
                  one of them a re-injection Data Review asked for (none a
                  dilution). An upload recorded without the requests it
                  carried is never one. Its injections are the names the
                  LIMS issued for those requests and those its imported rows
                  carry.
    QC member     it re-injects a QC member of the worksheet (any role but
                  Sample): always kept, whether or not its use can be shown,
                  since a QC result taken over several injections (an RSD
                  set, a blank without a limit) names none of them. Members
                  not known, or injections not known, count as QC.
    reported      a result of one of its injections was written onto a core
                  analysis (the push log: written, or there but locked), or
                  a QC result in force was judged on one (qc_results, active,
                  its provenance key naming the injection). Judged only once
                  its worksheet is verified, when what is reported is final
                  and the worker imports nothing more for it. A store that
                  cannot be read counts as reporting it.
    claim         a CAR (a deviation record of type "car", not closed) lists
                  the file under "claimed_files" ({"file", "worksheet",
                  "by", "at"}); only a file of a worksheet the CAR names as
                  affected, once.
    decide        an archived file is deleted only when the switch is on
                  (raw_share "delete_reinjection_files", off unless a Site
                  Administrator turns it on), it is a re-injection file, no
                  CAR claims it, it re-injects no QC member, its worksheet
                  is verified and its results were not reported. Anything else is kept, with the reason.
    plan          each archived file with what decide made of it; a file to
                  delete carries its sha256 and the worksheets whose run
                  files name it. The run-files entry is kept, marked
                  "deleted" ({"at", "sha256", "reason"}), and the
                  worksheet's log names the file and its checksum, so the
                  record outlives the file; `remove` then deletes the
                  archived file, only while its checksum is still that one.

Pure apart from the file moves and `remove`; Python 2.7 and 3 (the worker
loads it from the add-on).
"""
from __future__ import absolute_import, unicode_literals

import hashlib
import io
import os
import shutil

ARCHIVE = "archive"
EXPORT_SUFFIXES = (".csv", ".txt", ".tsv")
SUPPLEMENTARY = "supplementary"

KEPT_SWITCH_OFF = "the deletion switch is off"
KEPT_NOT_REINJECTION = "not a re-injection file"
KEPT_CLAIMED = "claimed by %s"
KEPT_OPEN = "its worksheet is not verified"
KEPT_REPORTED = "its results were reported: %s"
KEPT_UNKNOWN = "the injections it carried are not on record"
KEPT_OTHER = "the archived file is not the one its run files recorded"
KEPT_QC_MEMBER = "a QC member's re-injection, always kept"
DELETED = "deleted"
DELETED_REASON = "a re-injection's file whose results were not reported and no CAR claims"

NOT_A_CAR = "Only a corrective action record claims an instrument file."
CLOSED = "A closed record is read-only."
NOT_AFFECTED = "%s is not a file of a worksheet this record names as affected."
ALREADY = "%s is already claimed by this record."


def archive_dir(folder):
    return os.path.join(folder, ARCHIVE)


def is_export(name):
    return os.path.splitext(name or "")[1].lower() in EXPORT_SUFFIXES


def _sha256(path):
    h = hashlib.sha256()
    with io.open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def archive(path):
    """Move the imported export `path` into its folder's archive; returns
    where it now is, or None when it is not an export (left in place). A
    different file of the same name already archived is kept under its
    checksum first; the same file archived again is not kept twice."""
    folder, name = os.path.split(path)
    if not is_export(name) or not os.path.isfile(path):
        return None
    dest_dir = archive_dir(folder)
    if not os.path.isdir(dest_dir):
        os.makedirs(dest_dir)
    dest = os.path.join(dest_dir, name)
    if os.path.exists(dest):
        old = _sha256(dest)
        if old == _sha256(path):
            os.remove(path)
            return dest
        keep = os.path.join(dest_dir, old[:12])
        if not os.path.isdir(keep):
            os.makedirs(keep)
        shutil.move(dest, os.path.join(keep, name))
    shutil.move(path, dest)
    return dest


def locate(folder, name):
    """The file a record names by its base name: in the upload folder, else
    in the archive; None when it is in neither."""
    base = os.path.basename(name or "")
    if not base or base != name:
        return None
    for path in (os.path.join(folder, base), os.path.join(archive_dir(folder), base)):
        if os.path.isfile(path):
            return path
    return None


def reinjection_file(entry, requests):
    """True when the run-files entry is a follow-up run that carried only
    re-injections: it names the requests it carried, at least one, and each
    is a re-injection request of the worksheet."""
    entry = entry or {}
    carried = list(entry.get("requests") or [])
    if entry.get("kind") != SUPPLEMENTARY or not carried:
        return False
    kinds = dict((r.get("id"), r.get("kind")) for r in requests or [] if isinstance(r, dict))
    return all(kinds.get(rid) == "reinjection" for rid in carried)


def claims(registry):
    """{file: [CAR id]} of every claim on record."""
    out = {}
    for dev in registry or []:
        for c in (dev or {}).get("claimed_files") or []:
            if c.get("file"):
                out.setdefault(c["file"], []).append(dev.get("dev_id") or "")
    return out


def claim(dev, file_name, worksheet, files_of, by, at):
    """Add the claim of `file_name` (a file of `worksheet`) to the CAR
    `dev`; returns the refusal, or None once added. `files_of(worksheet)`
    lists that worksheet's uploaded files."""
    from senaite.pfas.qc_deviation import closed_refusal
    if (dev or {}).get("type") != "car":
        return NOT_A_CAR
    if closed_refusal(dev):
        return CLOSED
    if worksheet not in (dev.get("affected_worksheets") or []) or file_name not in (files_of(worksheet) or []):
        return NOT_AFFECTED % file_name
    held = dev.setdefault("claimed_files", [])
    if any(c.get("file") == file_name and c.get("worksheet") == worksheet for c in held):
        return ALREADY % file_name
    held.append({"file": file_name, "worksheet": worksheet, "by": by or "", "at": at or ""})
    return None


def decide(name, reinjection, enabled, claimed_by, reported_by, settled=False, qc_member=False):
    """(delete, reason) for one archived file: deleted only when the switch
    is on, it is a re-injection file, no CAR claims it, it re-injects no QC
    member (`qc_member`: a QC sample's re-injection is always kept, its use
    shown or not), its worksheet is verified (`settled`) and its results
    were not reported (`claimed_by`, `reported_by`: what claims it, what
    shows its results reported)."""
    if not enabled:
        return False, KEPT_SWITCH_OFF
    if not reinjection:
        return False, KEPT_NOT_REINJECTION
    if claimed_by:
        return False, KEPT_CLAIMED % ", ".join(sorted(claimed_by))
    if qc_member:
        return False, KEPT_QC_MEMBER
    if not settled:
        return False, KEPT_OPEN
    if reported_by:
        return False, KEPT_REPORTED % ", ".join(sorted(reported_by))
    return True, DELETED


def injections_of(entry, requests):
    """The LIMS-issued names of the injections a follow-up run carried: the
    new injection of each request it names."""
    by_id = dict((r.get("id"), r) for r in requests or [] if isinstance(r, dict))
    return sorted(set((by_id.get(rid) or {}).get("new_injection") for rid in (entry or {}).get("requests") or []
                      if (by_id.get(rid) or {}).get("new_injection")))


def reported_by_db(conn, worksheet_id, name, injections):
    """What in the QC database shows the results of the file `name` of the
    worksheet `worksheet_id` were reported: a result of one of its
    injections (`injections`, with those its imported rows carry) written
    onto a core analysis, or there but locked (the push log), or a QC result
    in force judged on one (its provenance key "<kind>|<injection>|..."). A
    store that cannot be read reports it, as far as anyone knows; so does a
    file whose injections are not known."""
    names = set(injections or [])
    try:
        names |= set(r[0] for r in conn.execute(
            "SELECT DISTINCT injection_name FROM injection_results WHERE batch_id=? AND source_file=?",
            (worksheet_id, name)) if r[0])
    except Exception:                                       # noqa: BLE001
        return ["the injection results"]
    if not names:
        return [KEPT_UNKNOWN]
    names = sorted(names)
    out = []
    marks = ",".join("?" * len(names))
    checks = (("the results written to the analyses",
               "SELECT 1 FROM result_pushes WHERE batch_id=? AND injection IN (%s) "
               "AND (ok=1 OR analysis_uid != '') LIMIT 1" % marks, [worksheet_id] + names),
              ("the QC results",
               "SELECT 1 FROM qc_results WHERE batch_id=? AND result_status='active' AND (%s) LIMIT 1"
               % " OR ".join(["instr(prov_key, ?) > 0"] * len(names)),
               [worksheet_id] + [u"|%s|" % n for n in names]))
    for what, sql, params in checks:
        try:
            if conn.execute(sql, params).fetchone():
                out.append(what)
        except Exception:                                   # noqa: BLE001
            out.append(what)
    return out


def qc_reinjections(requests, members):
    """The LIMS-issued names of the re-injections of a QC member (any role
    but Sample; a member not found counts as QC)."""
    roles = dict((m.get("injection"), m.get("role")) for m in members or [] if isinstance(m, dict))
    return set(r.get("new_injection") for r in requests or [] if isinstance(r, dict)
               and r.get("kind") == "reinjection" and r.get("new_injection")
               and (roles.get(r.get("injection")) or "") != "Sample")


def plan(folder, conn, run_files, requests_of, registry, enabled, verified=(), members_of=None):
    """Each archived file, top level only, with what `decide` made of it:
    [{"file", "delete", "reason"}], a file to delete also with its "sha256"
    and the "worksheets" whose run files name it. `run_files` = {worksheet
    id: its run files entries}; `requests_of(worksheet id)` its requests;
    `registry`, the deviation records; `verified`, the ids of the verified
    worksheets; `members_of(worksheet id)` its members (none given: every
    re-injection counts as a QC one). Nothing is removed here (`remove`). An entry already marked
    deleted whose file is still archived, with the checksum it recorded, is
    planned again (a removal that did not happen after its record)."""
    out = []
    root = archive_dir(folder)
    if not os.path.isdir(root):
        return out
    by_claim = claims(registry)
    verified = set(verified or ())
    owners, gone = {}, {}
    for ws_id, entries in (run_files or {}).items():
        for e in entries or []:
            if e.get("file"):
                (gone if e.get("deleted") else owners).setdefault(e["file"], []).append((ws_id, e))
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        mine = owners.get(name) or []
        if not enabled:
            out.append({"file": name, "delete": False, "reason": KEPT_SWITCH_OFF})
            continue
        sha = _sha256(path)
        if not mine and gone.get(name):
            redo = all((e.get("deleted") or {}).get("sha256") == sha for _ws, e in gone[name])
            out.append({"file": name, "delete": redo, "reason": DELETED if redo else KEPT_OTHER,
                        "sha256": sha, "worksheets": [], "recorded": True})
            continue
        reinjection = bool(mine) and all(reinjection_file(e, requests_of(ws)) for ws, e in mine)
        if reinjection and any(e.get("sha256") and e["sha256"] != sha for _ws, e in mine):
            out.append({"file": name, "delete": False, "reason": KEPT_OTHER})
            continue
        reported, qc_member = [], False
        settled = bool(mine) and all(ws in verified for ws, _e in mine)
        if reinjection:
            for ws, e in mine:
                carried = injections_of(e, requests_of(ws))
                qc = qc_reinjections(requests_of(ws), members_of(ws)) if members_of else None
                if qc is None or set(carried) & qc or not carried:
                    qc_member = True
                if settled:
                    reported += reported_by_db(conn, ws, name, carried)
        delete, reason = decide(name, reinjection, enabled, by_claim.get(name), sorted(set(reported)), settled,
                                qc_member)
        item = {"file": name, "delete": delete, "reason": reason}
        if delete:
            item.update(sha256=sha, worksheets=sorted(set(ws for ws, _e in mine)))
        out.append(item)
    return out


def mark_deleted(entries, name, sha256, at):
    """The run files `entries` with every live entry of `name` marked
    deleted: {"at", "sha256", "reason"}; the entry itself stays, so the
    record names the file after it is gone."""
    out = []
    for e in entries or []:
        e = dict(e)
        if e.get("file") == name and not e.get("deleted"):
            e["deleted"] = {"at": at or "", "sha256": sha256, "reason": DELETED_REASON}
        out.append(e)
    return out


def remove(folder, name, sha256):
    """Delete the archived file `name` while its checksum is `sha256`; True
    when it went. A file of that name archived since is another file and is
    kept."""
    path = os.path.join(archive_dir(folder), os.path.basename(name or ""))
    if not name or os.path.basename(name) != name or not os.path.isfile(path):
        return False
    if _sha256(path) != sha256:
        return False
    os.remove(path)
    return True
