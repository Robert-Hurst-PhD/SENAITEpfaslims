#!/usr/bin/env python3
"""
Relabel an instrument export so its injection names come from the LIMS worklist.

The `Test Sample.csv` training set was created synthetically, with no input from
the LIMS, so its injection names were whatever the author typed. That is the
whole reason the importer could not bind the calibration standards: the names
had no relationship to anything the system had issued.

This maps each injection in the export onto the row the Run Builder generated
for it and rewrites `Injection Name` (and `Sample Description`) to match, so the
file reads as though the run had been driven from the worklist in the first
place. Nothing else in the file is touched — every measurement, timestamp and
qualifier is left exactly as exported.

Matching is by QC role and acquisition order, which is unambiguous here:
  * calibrators pair by LEVEL (Level 3 -> the worklist's L3 calibrator);
  * repeat injections of one name (the CCV was run three times) pair with the
    worklist's successive bracketing injections in time order;
  * samples already carry their Client Sample ID, which IS the worklist name.

Usage:
  relabel_run_from_worklist.py <export.csv> <worklist.csv> <output.csv>
"""
import argparse
import csv
import datetime
import io
import sys
from collections import OrderedDict

ACQ_FORMATS = ("%b %d, %Y %H:%M:%S", "%B %d, %Y %H:%M:%S",
               "%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S")


def parse_acq(value):
    for fmt in ACQ_FORMATS:
        try:
            return datetime.datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def classify(name):
    upper = name.upper()
    if "LFSMD" in name or "DUP" in upper:
        return "LFSMD"
    if "LFSM" in name:
        return "LFSM"
    if "MB" in name.split():
        return "MB"
    if "CCV" in upper:
        return "CCV"
    if "ICV" in upper:
        return "ICV"
    if "-CAL-" in upper or " CAL " in upper:
        return "CAL"
    return "Sample"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("worklist")
    ap.add_argument("output")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with io.open(args.export, encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        fieldnames = reader.fieldnames
        rows = list(reader)

    with io.open(args.worklist, encoding="utf-8-sig", newline="") as fh:
        worklist = list(csv.DictReader(fh))

    # every distinct injection in the export, in acquisition order
    injections = OrderedDict()
    for row in rows:
        key = (row["Injection Name"], row["Acquisition Date Time"])
        injections.setdefault(key, parse_acq(row["Acquisition Date Time"]))
    ordered = sorted(injections, key=lambda k: injections[k] or datetime.datetime.min)

    # worklist rows grouped by role, in vial order
    wl_by_role = {}
    for w in worklist:
        wl_by_role.setdefault(classify(w["Sample Name"]), []).append(w)
    wl_names = {w["Sample Name"] for w in worklist}

    rename = {}
    describe = {}
    used = set()
    cal_by_level = {}
    for w in wl_by_role.get("CAL", []):
        # "…-L7" -> level 7
        tail = w["Sample Name"].rsplit("-L", 1)
        if len(tail) == 2 and tail[1].isdigit():
            cal_by_level[int(tail[1])] = w

    # level for each calibration injection, read from the export itself
    level_of = {}
    for row in rows:
        key = (row["Injection Name"], row["Acquisition Date Time"])
        if classify(row["Injection Name"]) == "CAL" and row.get("Level", "").strip():
            level_of.setdefault(key, row["Level"].strip())

    for key in ordered:
        name = key[0]
        acq = injections[key]      # parsed datetime, not the raw string
        role = classify(name)

        # already a worklist name (samples carry their Client Sample ID)
        if name in wl_names:
            match = next(w for w in worklist if w["Sample Name"] == name)
            rename[key] = name
            describe[key] = match["Description"]
            used.add(match["Sample Name"])
            continue

        match = None
        if role == "CAL":
            lvl = level_of.get(key)
            if lvl and lvl.isdigit():
                match = cal_by_level.get(int(lvl))
        if match is None:
            # First worklist row of this role that has not been claimed yet.
            # The pool is already filtered by `used`, so an extra cursor would
            # advance twice per injection and skip rows — which paired the
            # second CCV with the THIRD bracketing injection.
            pool = [w for w in wl_by_role.get(role, [])
                    if w["Sample Name"] not in used]
            if pool:
                match = pool[0]
        if match is None:
            print("  !! no worklist row for %-40s (%s)" % (name[:40], role),
                  file=sys.stderr)
            rename[key] = name
            describe[key] = None
            continue
        used.add(match["Sample Name"])
        rename[key] = match["Sample Name"]
        # The builder stamps descriptions with TODAY. Substituting the
        # injection's real acquisition date keeps the training set internally
        # consistent — a run acquired in October 2025 should not describe
        # itself as having been prepared today.
        desc = match["Description"]
        if acq:
            parts = desc.rsplit("·", 1)
            if len(parts) == 2 and parts[1].strip().count("-") == 2:
                desc = "%s· %s" % (parts[0], acq.strftime("%Y-%m-%d"))
        describe[key] = desc

    print("%-42s -> %s" % ("EXPORT INJECTION", "WORKLIST NAME"))
    for key in ordered:
        flag = "" if rename[key] != key[0] else "   (unchanged)"
        print("%-42s -> %s%s" % (key[0][:42], rename[key], flag))
    unused = [w["Sample Name"] for w in worklist if w["Sample Name"] not in used]
    if unused:
        print("\nworklist rows not present in the run (planned, not injected):")
        for u in unused:
            print("   ", u)

    if args.dry_run:
        return

    for row in rows:
        key = (row["Injection Name"], row["Acquisition Date Time"])
        new_desc = describe.get(key)
        row["Injection Name"] = rename.get(key, row["Injection Name"])
        if new_desc:
            row["Sample Description"] = new_desc

    with io.open(args.output, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    print("\nwrote %s (%d rows)" % (args.output, len(rows)))


if __name__ == "__main__":
    main()
