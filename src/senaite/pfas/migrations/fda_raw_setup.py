# -*- coding: utf-8 -*-
"""Set one method's raw-data processing values from a spec file.

The spec is the lab's own settings, kept outside the install tree:

    {"method": ..., "surrogates": {native: labelled standard},
     "unit_map": {matrix: unit},
     "confirmation": {"sn_quan_min": .., "sn_confirm_min": ..},
     "single_transition_remove": [keyword, ...],
     "labelled_conc": .., "fit_max_dev_pct": ..}

Every key but "method" is optional. What it does:

  * a surrogate link is written only where the native has none; a link the
    lab has set is never overwritten;
  * a standard that is not in the method's labelled standards grid, a native
    that is not in its panel and an unknown method refuse the whole run;
  * a matrix unit and the confirmation limits are set where they differ;
  * a listed analyte comes off the single-transition list only where its
    Integration row, or one of its isomer peaks' rows, lists a qualifier;
    one without stays on it and is named;
  * calibration.labelled_conc is written where unset;
  * integration.fit_max_dev_pct is written where the Integration block's
    area is gaussian or emg and the key is missing.

Each change goes through the store's own save, so the change history records
it. Run it twice and the second run reports nothing to do. Dry run first:

    bin/instance -O senaite run \
        src/senaite/pfas/migrations/fda_raw_setup.py SPEC.json --dry-run
    bin/instance -O senaite run \
        src/senaite/pfas/migrations/fda_raw_setup.py SPEC.json

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import copy
import io
import json
import sys

KEYS = ("method", "surrogates", "unit_map", "confirmation", "single_transition_remove",
        "labelled_conc", "fit_max_dev_pct")
FITTED_AREAS = ("gaussian", "emg")
LABEL = "Raw-data processing setup"


class SpecError(ValueError):
    """The spec cannot be applied to the method; nothing is written."""


def load_spec(path):
    with io.open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    unknown = sorted(set(spec) - set(KEYS))
    if unknown or not spec.get("method"):
        raise SpecError("spec needs a method and only the keys {0}; unknown: {1}".format(
            ", ".join(KEYS), ", ".join(unknown) or "none"))
    return spec


def _unset(v):
    return v is None or v == ""


def _show(v):
    return "(unset)" if _unset(v) else "{0}".format(v)


def _dig(profile, *path):
    node = profile
    for k in path:
        node = node.get(k) if isinstance(node, dict) else None
    return node


def _section(profile, *path):
    node = profile
    for k in path:
        if not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]
    return node


def _isomers():
    from senaite.pfas import isomers
    return isomers


def has_qualifier(profile, keyword):
    """Whether the analyte's Integration row, or one of its isomer peaks'
    rows, lists a qualifier transition: what confirms it once it is off the
    single-transition list."""
    rows = _dig(profile, "integration", "analytes") or {}
    names = _isomers().peaks_of(profile, keyword) or [keyword]
    return any((rows.get(n) or {}).get("quals") for n in names if isinstance(rows.get(n), dict))


def kept_text(keyword):
    return "{0} kept single-transition: no qualifier in Integration".format(keyword)


def apply_spec(profile, spec, notes=None):
    """(new profile, [(what, before, after)]); raises SpecError. `notes`
    receives a line for each listed analyte kept on the single-transition
    list."""
    profile = copy.deepcopy(profile)
    rows = []
    panel = profile.get("master_analyte_set") or []
    grid = profile.get("labelled_standards") or {}
    sur = spec.get("surrogates") or {}
    for native in sorted(sur):
        if native not in panel:
            raise SpecError("{0} is not in the method's analyte panel".format(native))
        if sur[native] not in grid:
            raise SpecError("{0} is not in the method's isotope standards grid, for {1}".format(
                sur[native], native))
    smap = [r for r in profile.get("surrogate_map") or []]
    for native in sorted(sur, key=lambda k: panel.index(k)):
        row = [r for r in smap if isinstance(r, dict) and r.get("analyte") == native]
        if row and not _unset(row[0].get("surrogate_is")):
            continue
        if row:
            row[0]["surrogate_is"] = sur[native]
        else:
            smap.append({"analyte": native, "surrogate_is": sur[native]})
        rows.append(("surrogate {0}".format(native), "(none)", sur[native]))
    if sur:
        profile["surrogate_map"] = smap

    for matrix in sorted(spec.get("unit_map") or {}):
        units = _section(profile, "unit_map")
        want = spec["unit_map"][matrix]
        if units.get(matrix) != want:
            rows.append(("unit {0}".format(matrix), _show(units.get(matrix)), want))
            units[matrix] = want

    conf = _dig(profile, "instrument_verification", "confirmation")
    for key in sorted(spec.get("confirmation") or {}):
        want = spec["confirmation"][key]
        have = (conf or {}).get(key)
        if _unset(have) or have != want:
            conf = _section(profile, "instrument_verification", "confirmation")
            rows.append(("confirmation.{0}".format(key), _show(have), want))
            conf[key] = want

    drop = spec.get("single_transition_remove") or []
    single = (conf or {}).get("single_transition_analytes")
    if isinstance(single, list):
        kept = [k for k in single if k in drop and not has_qualifier(profile, k)]
        if notes is not None:
            notes.extend(kept_text(k) for k in kept)
        drop = [k for k in drop if k not in kept]
        gone = [k for k in single if k in drop]
        if gone:
            rows.append(("single_transition_analytes", ", ".join(single),
                         ", ".join(k for k in single if k not in drop) or "(empty)"))
            conf["single_transition_analytes"] = [k for k in single if k not in drop]

    if not _unset(spec.get("labelled_conc")) and _unset(
            _dig(profile, "instrument_verification", "calibration", "labelled_conc")):
        _section(profile, "instrument_verification", "calibration")["labelled_conc"] = spec["labelled_conc"]
        rows.append(("calibration.labelled_conc", "(unset)", spec["labelled_conc"]))

    intg = profile.get("integration")
    if (not _unset(spec.get("fit_max_dev_pct")) and isinstance(intg, dict)
            and intg.get("area") in FITTED_AREAS and _unset(intg.get("fit_max_dev_pct"))):
        intg["fit_max_dev_pct"] = spec["fit_max_dev_pct"]
        rows.append(("integration.fit_max_dev_pct", "(unset)", spec["fit_max_dev_pct"]))
    return profile, rows


def print_table(method_id, rows):
    print("  {0}".format(method_id))
    for what, before, after in rows:
        print("    {0:<34} {1:<24} -> {2}".format(what, _show(before), _show(after)))


def run(portal, spec, dry_run=False, store=None):
    """Apply the spec through the store's save. Returns [(method_id, rows)];
    [] when there is nothing to do. A dry run returns the same and writes
    nothing."""
    if store is None:
        from senaite.pfas import method_profile_store as store
    method_id = spec["method"]
    profile = store.get_profile(portal, method_id)
    if not profile:
        raise SpecError("unknown method {0}".format(method_id))
    notes = []
    new, rows = apply_spec(profile, spec, notes)
    for line in notes:
        print("  {0}".format(line))
    if not rows:
        return []
    print_table(method_id, rows)
    if not dry_run:
        store.save_profile(portal, method_id, new, label=LABEL)
    return [(method_id, rows)]


def main(app, spec_path, dry_run):
    import transaction
    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.users import UnrestrictedUser
    portal = [o for o in app.objectValues(["Plone Site"])][0]
    newSecurityManager(None, UnrestrictedUser("admin", "", ["Manager"], []))
    print("Raw-data processing setup{0}".format(" (dry run)" if dry_run else ""))
    try:
        changed = run(portal, load_spec(spec_path), dry_run=dry_run)
    except SpecError as exc:
        transaction.abort()
        print("Refused: {0}".format(exc))
        return
    if not changed:
        print("Nothing to do.")
        transaction.abort()
    elif dry_run:
        print("Dry run: nothing written ({0} rows).".format(len(changed[0][1])))
        transaction.abort()
    else:
        transaction.commit()
        print("Committed: {0}".format(changed[0][0]))


if "app" in globals():
    _paths = [a for a in sys.argv[1:] if not a.startswith("-")]
    if not _paths:
        raise SystemExit("usage: fda_raw_setup.py SPEC.json [--dry-run]")
    main(globals()["app"], _paths[-1], "--dry-run" in sys.argv)      # noqa: F821  (bin/instance run)
