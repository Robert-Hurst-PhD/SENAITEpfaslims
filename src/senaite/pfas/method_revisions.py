# -*- coding: utf-8 -*-
"""Issued revisions of a method profile.

A manager issues a revision when a method's settings are final, and that
method's settings report PDF is frozen:

    PDF       {dirname(PFAS_PROFILES_PATH)}/method_revisions/<method>/rev-0004.pdf
              (binary artifact -> filesystem tier)
    snapshot  rev-0004.json beside it: the settings it was issued with
              (snapshot_of), written before the PDF
    record    portal annotation KEY = {method: [{"rev", "major", "sub",
              "level", "changed", "issued_at", "issued_by", "reason",
              "fingerprint", "file", "snapshot", "source"}]}

`rev` is the issue sequence number: the `?rev=` key, the file names and
every stored reference. The number a revision is known by is major.sub
(`label`); issuing chooses the level from what changed since the last
issued revision's snapshot (revision_level). A record issued before
major.sub holds no `major` and reads "<rev>.0", its PDF keeping its file;
a reference stored as an integer (a stage plan, a batch record's hash)
predates major.sub and reads the same way (`revision_text`).

"Unissued changes" = the method's current settings fingerprint differs from
the latest revision's. The fingerprint covers what the method report is made
from: the profile (save stamps and the compounds' expected retention times
excluded: an analyst updates those from run to run, expected_rt) and the
method's rule switches. A revision issued while the fingerprint still
covered the expected times stays current while they are unchanged
(`fingerprints`). A compound's empty processing entry is no setting and is
left out of both (method_proposals.without_empty_processing).

Pure helpers + a thin storage shell. Python 2.7.
"""
from __future__ import absolute_import, unicode_literals

import copy
import errno
import io
import json
import logging
import numbers
import os
import time

logger = logging.getLogger("senaite.pfas.method_revisions")

KEY = "senaite.pfas.method_revisions"
_STAMPS = ("updated_at", "updated_by")


def _stripped(profile, with_times=False):
    from senaite.pfas import expected_rt
    from senaite.pfas.method_proposals import without_empty_processing
    p = copy.deepcopy(profile or {}) if with_times else expected_rt.exempt(profile)
    for k in _STAMPS:
        p.pop(k, None)
    # a compound's processing entry with no change in it is no setting:
    # adding empty entries leaves every issued revision current
    intg = p.get("integration")
    if isinstance(intg, dict) and isinstance(intg.get("analytes"), dict):
        p["integration"] = dict(intg, analytes=without_empty_processing(intg["analytes"]))
    return p


def snapshot_of(profile, toggles):
    """The settings a revision is issued with, as the fingerprint hashes
    them: {"profile": the profile, expected times and save stamps removed,
    "toggles": the rule switches}."""
    return {"profile": _stripped(profile), "toggles": dict(toggles or {})}


def _settings_fingerprint(profile, toggles, with_times=False):
    from senaite.pfas import settings_report as sr
    if with_times:
        return sr.fingerprint(_stripped(profile, with_times=True), toggles or {})
    snap = snapshot_of(profile, toggles)
    return sr.fingerprint(snap["profile"], snap["toggles"])


fingerprint = _settings_fingerprint


def fingerprints(profile, toggles):
    """(the fingerprint a revision is issued with, the one a revision issued
    before the expected times were exempt holds): either is current."""
    return (_settings_fingerprint(profile, toggles),
            _settings_fingerprint(profile, toggles, with_times=True))


def next_number(records):
    return max([r.get("rev", 0) for r in records] or [0]) + 1


def last_record(records):
    """The last issued revision: the highest issue number."""
    return sorted(records, key=lambda r: r.get("rev", 0))[-1] if records else None


def _major_sub(rec):
    if rec.get("major") is None:
        return int(rec.get("rev") or 0), 0
    return int(rec["major"]), int(rec.get("sub") or 0)


def label(rec):
    """The number a revision is known by, "4.1"; a record issued before
    major.sub reads "<rev>.0"; u"" when there is none."""
    if not rec or rec.get("rev") is None:
        return u""
    return u"%d.%d" % _major_sub(rec)


def revision_text(value):
    """A stored reference to a method revision as it prints: an integer
    predates major.sub and reads "N.0", a label stands as stored, None
    reads u""."""
    if value is None or value == u"":
        return u""
    if isinstance(value, numbers.Integral) and not isinstance(value, bool):
        return u"%d.0" % value
    return u"%s" % value


def next_label(records, level):
    """(major, sub) of the next revision: (1, 0) for the first; the last
    revision's major plus one for a major change, its sub plus one for a
    sub change."""
    last = last_record(records)
    if last is None:
        return 1, 0
    major, sub = _major_sub(last)
    return (major, sub + 1) if level == "sub" else (major + 1, 0)


def status(records, current_fingerprint):
    """{"rev", "label", "issued_at", "issued_by", "unissued"} for the list
    page; rev None when never issued (unissued is then True).
    `current_fingerprint` is one fingerprint or the pair `fingerprints`
    gives, either current."""
    if not records:
        return {"rev": None, "label": u"", "issued_at": u"", "issued_by": u"", "unissued": True}
    last = last_record(records)
    current = (current_fingerprint if isinstance(current_fingerprint, (tuple, list))
               else (current_fingerprint,))
    return {"rev": last.get("rev"), "label": label(last), "issued_at": last.get("issued_at", u""),
            "issued_by": last.get("issued_by", u""),
            "unissued": last.get("fingerprint") not in current}


def file_name(rev):
    return u"rev-%04d.pdf" % int(rev)


def snapshot_name(rev):
    return u"rev-%04d.json" % int(rev)


# ── storage (Zope + filesystem) ──────────────────────────────────────────────

def revisions_dir(method_id, base=None):
    if base is None:
        base = os.path.dirname(os.environ.get("PFAS_PROFILES_PATH", "/data/qc/method_profiles.json"))
    safe = u"".join(c for c in u"%s" % method_id if c.isalnum() or c in u"_-.")
    return os.path.join(base, "method_revisions", safe)


def _ann(portal):
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal)


def records(portal, method_id):
    raw = _ann(portal).get(KEY)
    data = json.loads(raw) if raw else {}
    return list(data.get(method_id) or [])


def write_snapshot(method_id, rev, snap, overwrite=False, keep=False):
    """Write a revision's snapshot beside its PDF, atomically; returns its
    file name. An existing snapshot is kept (ValueError) unless
    `overwrite`; with `keep` (issue(), which holds the revision's claim)
    one already there is the same issue's and is kept as it is."""
    folder = revisions_dir(method_id)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    name = snapshot_name(rev)
    path = os.path.join(folder, name)
    blob = json.dumps(snap, sort_keys=True)
    if not isinstance(blob, bytes):
        blob = blob.encode("utf-8")
    if keep:
        _place(path, blob)
        return name
    if os.path.exists(path) and not overwrite:
        raise ValueError(u"The snapshot of revision %s of %s already exists on disk." % (rev, method_id))
    tmp = path + ".tmp"
    with io.open(tmp, "wb") as fh:
        fh.write(blob)
    os.rename(tmp, path)
    return name


def read_snapshot(method_id, rec):
    """The snapshot a revision record names, or None: none kept (issued
    before snapshots and not rebuilt), or its file unreadable."""
    name = (rec or {}).get("snapshot")
    if not name:
        return None
    try:
        with io.open(os.path.join(revisions_dir(method_id), os.path.basename(name)), "rb") as fh:
            return json.loads(fh.read().decode("utf-8"))
    except (IOError, OSError, ValueError):
        return None


def next_issue(method_id, records, profile, toggles):
    """What issuing now makes: {"major", "sub", "label", "level", "groups",
    "snapshot"}. The level is chosen from the last revision's snapshot
    (revision_level.level); the first revision is 1.0 and names no change."""
    from senaite.pfas import revision_level
    # as it is stored: a tuple or a key type the JSON file changes is no change
    snap = json.loads(json.dumps(snapshot_of(profile, toggles), sort_keys=True))
    if not records:
        lvl, groups = revision_level.MAJOR_LEVEL, []
    else:
        lvl, groups = revision_level.level(read_snapshot(method_id, last_record(records)), snap)
        if lvl is None:
            # the fingerprint moved where the comparison sees no change (a
            # value emptied): what cannot be named is never a sub
            lvl, groups = revision_level.MAJOR_LEVEL, [revision_level.OTHER]
    major, sub = next_label(records, lvl)
    return {"major": major, "sub": sub, "label": u"%d.%d" % (major, sub), "level": lvl,
            "groups": groups, "snapshot": snap}


def issue_preview(method_id, records, profile, toggles):
    """What issuing now would make, for the Issue dialog: {"label",
    "level", "groups"}. A preview that cannot be made is logged and reads
    label None ("Level not known"): the list of methods still renders, and
    the issue itself chooses the level again."""
    try:
        nxt = next_issue(method_id, records, profile, toggles)
    except Exception:                                       # noqa: BLE001
        logger.warning("issue preview of %s not made", method_id, exc_info=True)
        return {"label": None, "level": None, "groups": []}
    return {"label": nxt["label"], "level": nxt["level"], "groups": nxt["groups"]}


def revision_named(records, rev):
    """The revision `?rev=` asks for, as it is named: its record's
    major.sub, an issue number with no record as "N.0", else as given."""
    try:
        n = int(rev)
    except (TypeError, ValueError):
        return u"%s" % rev
    rec = [r for r in records or [] if r.get("rev") == n]
    return label(rec[0]) if rec else revision_text(n)


def issue(portal, method_id, pdf_bytes, fingerprint_value, who, when, reason, rev=None,
          major=None, sub=None, snapshot=None, level=None, changed=None, source=None):
    """Write the snapshot, then the frozen PDF, then record the revision.
    Returns the record. Each file is placed before the record that names
    it, and never over a file that is there (_place): a record never points
    at a file that is not there, and an issued revision's files are never
    overwritten.

    Who writes a revision's files is settled first, by its claim
    (<pdf>.claim, created only if absent): the method, number, settings
    fingerprint, who, reason and source (_claim) and the time. A claim of
    the same issue newer than ISSUE_SETTLE_SECONDS is the same issue's:
    Zope's retry after a ConflictError, or a second click on Issue. It
    writes nothing and records the files there, at the claim's time, which
    they print; a second click's commit then conflicts with the first's and
    its retry is refused by the first's record. Another issue's fresh claim
    refuses (IN_PROGRESS); a stale claim, or files with none, are left by
    an issue that never recorded them and are set aside beside them
    (_set_aside), never lost. `major`/`sub` not given: the next number for
    `level` (major when none). `source` names where the change came from
    (a run's processing change), else None."""
    raw = _ann(portal).get(KEY)
    data = json.loads(raw) if raw else {}
    recs = list(data.get(method_id) or [])
    rev = rev or next_number(recs)
    folder = revisions_dir(method_id)
    path = os.path.join(folder, file_name(rev))
    if any(r.get("rev") == rev for r in recs):
        raise ValueError(u"Revision %s of %s already exists on disk." % (rev, method_id))
    if not os.path.isdir(folder):
        os.makedirs(folder)
    claim = _claim(method_id, rev, fingerprint_value, who, reason, source)
    when, taken = _take_claim(method_id, rev, path, claim, when)
    if major is None:
        level = level or "major"
        major, sub = next_label(recs, level)
    try:
        snap_name = write_snapshot(method_id, rev, snapshot, keep=True) if snapshot is not None else None
        placed = _place(path, pdf_bytes)
    except (IOError, OSError):
        raise ValueError(IN_PROGRESS % (rev, method_id))
    # a claim just taken finds no file of another writer; the claim is
    # still this issue's when its record is made
    if (taken and not placed) or (_read_claim(path + ".claim") or {}).get("claim") != claim:
        raise ValueError(IN_PROGRESS % (rev, method_id))
    rec = {"rev": rev, "major": int(major), "sub": int(sub or 0), "level": level,
           "changed": list(changed or []), "issued_at": when, "issued_by": who, "reason": reason or u"",
           "fingerprint": fingerprint_value, "file": file_name(rev), "snapshot": snap_name,
           "source": source}
    recs.append(rec)
    data[method_id] = recs
    _ann(portal)[KEY] = json.dumps(data, sort_keys=True)
    return rec


# an issue writes its files and commits its record within one request: a
# claim no record names that is newer than this may be an issue in flight
ISSUE_SETTLE_SECONDS = 300
IN_PROGRESS = u"Revision %s of %s is being issued: try again in a few minutes."


def _fresh(path):
    return time.time() - os.path.getmtime(path) < ISSUE_SETTLE_SECONDS


# the method's issues decide their claims one at a time under this lock
# (flock, released with its process); one that cannot take it refuses
ISSUE_LOCK = ".issue.lock"
ISSUE_LOCK_TRIES = 20


def _take_claim(method_id, rev, path, claim, when):
    """(the time this issue records, whether it took the claim now): its
    own, once it holds the revision's claim, or the claim's, the same
    issue's fresh claim being there. Decided under the method's issue lock.
    ValueError (IN_PROGRESS) while another issue holds the lock, its fresh
    claim or fresh files with none are there, or a file vanishes mid-step;
    what is stale is set aside first, each file looked at again just before."""
    import fcntl
    lock = io.open(os.path.join(os.path.dirname(path), ISSUE_LOCK), "a")
    try:
        for _try in range(ISSUE_LOCK_TRIES):
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (IOError, OSError):
                time.sleep(0.1)
        else:
            raise ValueError(IN_PROGRESS % (rev, method_id))
        try:
            return _decide_claim(method_id, rev, path, claim, when)
        except (IOError, OSError):
            raise ValueError(IN_PROGRESS % (rev, method_id))
    finally:
        lock.close()                            # the lock goes with its file


def _decide_claim(method_id, rev, path, claim, when):
    claim_path = path + ".claim"
    snap_path = os.path.join(os.path.dirname(path), snapshot_name(rev))
    held = _read_claim(claim_path)
    if held is not None and _fresh(claim_path):
        if held.get("claim") == claim:
            return held.get("when") or when, False
        raise ValueError(IN_PROGRESS % (rev, method_id))
    # stale, or files no claim names: an issue that never recorded them.
    # Each is looked at again just before: a fresh one is someone's
    for leftover in (claim_path, path, snap_path):
        if os.path.exists(leftover):
            if _fresh(leftover):
                raise ValueError(IN_PROGRESS % (rev, method_id))
            _set_aside(leftover)
    if not _place(claim_path, json.dumps({"claim": claim, "when": when}, sort_keys=True).encode("utf-8")):
        raise ValueError(IN_PROGRESS % (rev, method_id))
    if (_read_claim(claim_path) or {}).get("claim") != claim:
        raise ValueError(IN_PROGRESS % (rev, method_id))
    return when, True


def _claim(method_id, rev, fingerprint_value, who, reason, source):
    """What names one issue across the attempts of its request: the same
    method, number, settings, person, reason and source. Not the time or
    the PDF's bytes, which each attempt makes anew."""
    import hashlib
    body = json.dumps([method_id, rev, fingerprint_value, who, reason or u"", source], sort_keys=True)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _read_claim(claim_path):
    """The claim written beside a revision's PDF, {"claim", "when"}, or None."""
    try:
        with io.open(claim_path, "r", encoding="utf-8") as fh:
            held = json.loads(fh.read())
    except (IOError, OSError, ValueError):
        return None
    return held if isinstance(held, dict) else None


def _place(path, blob):
    """`blob` written at `path` only if no file is there: written in full
    under a name of its own, then linked into place, which fails rather
    than replace a file another writer placed first. True when placed."""
    import uuid
    tmp = u"%s.tmp-%s" % (path, uuid.uuid4().hex)
    with io.open(tmp, "wb") as fh:
        fh.write(blob)
    try:
        os.link(tmp, path)
        return True
    except OSError as exc:
        if exc.errno != errno.EEXIST:
            raise
        return False
    finally:
        os.remove(tmp)


def _set_aside(path):
    """A file no record names moved to "<name>.unrecorded-<n>", the first n
    free: kept for whoever looks into the failed issue that left it."""
    n = 1
    while os.path.exists(u"%s.unrecorded-%d" % (path, n)):
        n += 1
    os.rename(path, u"%s.unrecorded-%d" % (path, n))


def save_records(portal, method_id, recs):
    """Replace one method's revision records (the numbering migration)."""
    raw = _ann(portal).get(KEY)
    data = json.loads(raw) if raw else {}
    data[method_id] = list(recs)
    _ann(portal)[KEY] = json.dumps(data, sort_keys=True)


def read_pdf(method_id, rec):
    """The frozen PDF of a revision: `rec`, its record (the file it names),
    or its issue number."""
    if isinstance(rec, dict):
        name = os.path.basename(rec.get("file") or u"") or file_name(rec["rev"])
    else:
        name = file_name(rec)
    path = os.path.join(revisions_dir(method_id), name)
    with io.open(path, "rb") as fh:
        return fh.read()
