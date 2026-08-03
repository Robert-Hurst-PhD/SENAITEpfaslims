# -*- coding: utf-8 -*-
"""
E2E acceptance test — Stage 2: reagent lots and prepared standards.

Builds the three-level ISO 17025 6.6 traceability chain the CLAUDE.md 1.6
rule requires, for the real instrument run in `Test Sample.csv`:

    CRM / solvent reagent lot  ->  in-house prepared standard  ->  result

Prepared-standard lot codes deliberately end in the same 6-digit date suffix
the injection names carry (251006 for the calibration ladder, 251020 for the
CCV and the LFSM spike), which is the join the Run Builder relies on.

Uses the production save paths (reagents._save_reagent,
prepared_standards._save) rather than writing objects by hand.

Run:  bin/instance -O senaite run /addon/e2e_kcp_standards.py
"""
from __future__ import absolute_import, print_function

import transaction

REAGENTS = [
    {
        "name": u"PFAC-MXK Native PFAS Calibration Mix",
        "category": u"Standard / Reference Material",
        "supplier": u"Wellington Laboratories",
        "cat_number": u"PFAC-MXK",
        "lot_number": u"WL-PFACMXK-A2439",
        "received_date": u"2025-08-14",
        "manufacturer_expiry": u"2027-08-01",
        "storage_location": u"Std Freezer 1 / Box A",
        "quantity": u"1.2", "unit": u"mL",
        "notes": u"NIST-traceable CoA on file. E2E test data.",
    },
    {
        "name": u"MPFAC-C-ES Labelled Internal Standard Mix",
        "category": u"Internal Standard",
        "supplier": u"Wellington Laboratories",
        "cat_number": u"MPFAC-C-ES",
        "lot_number": u"WL-MPFACCES-B1177",
        "received_date": u"2025-08-14",
        "manufacturer_expiry": u"2027-06-01",
        "storage_location": u"Std Freezer 1 / Box A",
        "quantity": u"1.2", "unit": u"mL",
        "notes": u"E2E test data.",
    },
    {
        "name": u"Methanol, LC-MS grade",
        "category": u"Mobile Phase / Solvent",
        "supplier": u"Fisher Scientific",
        "cat_number": u"A456-4",
        "lot_number": u"FS-MEOH-2519834",
        "received_date": u"2025-09-02",
        "manufacturer_expiry": u"2028-09-01",
        "storage_location": u"Solvent Cabinet 2",
        "quantity": u"4", "unit": u"L",
        "notes": u"E2E test data.",
    },
    {
        "name": u"Ammonium Acetate, LC-MS grade",
        "category": u"Salt",
        "supplier": u"Sigma-Aldrich",
        "cat_number": u"73594",
        "lot_number": u"SA-NH4OAC-BCCF4471",
        "received_date": u"2025-07-11",
        "manufacturer_expiry": u"2027-07-01",
        "storage_location": u"Reagent Shelf B",
        "quantity": u"250", "unit": u"g",
        "notes": u"E2E test data.",
    },
    {
        "name": u"Water, LC-MS grade",
        "category": u"Mobile Phase / Solvent",
        "supplier": u"Fisher Scientific",
        "cat_number": u"W6-4",
        "lot_number": u"FS-H2O-2504112",
        "received_date": u"2025-09-02",
        "manufacturer_expiry": u"2028-09-01",
        "storage_location": u"Solvent Cabinet 2",
        "quantity": u"4", "unit": u"L",
        "notes": u"E2E test data.",
    },
]

# lot_number -> the reagents (by cat_number) each prepared standard consumed
STANDARDS = [
    {
        "title": u"FDA 32-PFAS Calibration Ladder A (CAL-1..10)",
        "lot_number": u"PS-KCP-CAL-251006",
        "standard_type": u"Calibration Standard",
        "logbook_slug": u"251",
        "logbook_title": u"Calibration Curve Prep Log",
        "prepared_by": u"KCP",
        "prepared_date": u"2025-10-06",
        "expiry_date": u"2026-04-06",
        "storage_location": u"Std Freezer 1 / Rack 3",
        "volume_prepared": u"10 x 1 mL",
        "notes": u"20 -> 0.039 ng/mL serial ladder. Injected as "
                 u"FDA-CAL-1-251006 .. FDA-CAL-10-251006.",
        "parents": [u"PFAC-MXK", u"MPFAC-C-ES", u"A456-4"],
    },
    {
        "title": u"FDA 32-PFAS CCV Check Standard (level 5)",
        "lot_number": u"PS-KCP-CCV-251020",
        "standard_type": u"QC Check Standard",
        "logbook_slug": u"251",
        "logbook_title": u"Calibration Curve Prep Log",
        "prepared_by": u"KCP",
        "prepared_date": u"2025-10-20",
        "expiry_date": u"2026-01-20",
        "storage_location": u"Std Freezer 1 / Rack 3",
        "volume_prepared": u"2 mL",
        "notes": u"1.25 ng/mL. Injected as FDA-CCV-251020.",
        "parents": [u"PFAC-MXK", u"A456-4"],
    },
    {
        "title": u"FDA 32-PFAS Matrix Spike, 100 ppt",
        "lot_number": u"PS-KCP-SPK-251020",
        "standard_type": u"Matrix Spike",
        "logbook_slug": u"251",
        "logbook_title": u"Calibration Curve Prep Log",
        "prepared_by": u"KCP",
        "prepared_date": u"2025-10-20",
        "expiry_date": u"2026-04-20",
        "storage_location": u"Std Freezer 1 / Rack 3",
        "volume_prepared": u"5 mL",
        "notes": u"Spiked into Egg-2 for LFSM / LFSMD Mid.",
        "parents": [u"PFAC-MXK", u"A456-4"],
    },
    {
        "title": u"FDA 32-PFAS Internal Standard Working Solution",
        "lot_number": u"PS-KCP-IS-251006",
        "standard_type": u"Internal Standard Mix",
        "logbook_slug": u"251",
        "logbook_title": u"Calibration Curve Prep Log",
        "prepared_by": u"KCP",
        "prepared_date": u"2025-10-06",
        "expiry_date": u"2026-04-06",
        "storage_location": u"Std Freezer 1 / Rack 3",
        "volume_prepared": u"10 mL",
        "notes": u"Added to every injection incl. blanks.",
        "parents": [u"MPFAC-C-ES", u"A456-4"],
    },
    {
        "title": u"Mobile Phase B — 4 mM Ammonium Acetate in MeOH",
        "lot_number": u"PS-KCP-MPB-251020",
        "standard_type": u"Solvent / Reagent",
        "logbook_slug": u"250",
        "logbook_title": u"Solvent / Reagent Prep Log",
        "prepared_by": u"KCP",
        "prepared_date": u"2025-10-20",
        "expiry_date": u"2025-10-27",
        "storage_location": u"LC-MS Bench",
        "volume_prepared": u"1 L",
        "notes": u"E2E test data.",
        "parents": [u"73594", u"A456-4"],
    },
]


def run(app):
    from zope.site.hooks import setSite, setHooks
    setHooks()
    portal = app.senaite
    setSite(portal)

    from AccessControl.SecurityManagement import newSecurityManager
    from AccessControl.User import UnrestrictedUser
    newSecurityManager(None, UnrestrictedUser('admin', '', ['Manager'], []))

    from senaite.pfas.browser.reagents import _save_reagent, _get_reagents_folder
    from senaite.pfas.browser import prepared_standards as ps

    # ── reagent lots ────────────────────────────────────────────────────
    folder = _get_reagents_folder(portal)
    by_cat = {}
    for obj in folder.objectValues():
        by_cat[getattr(obj, 'cat_number', u'') or u''] = obj

    for r in REAGENTS:
        if r['cat_number'] in by_cat:
            print('  reuse  reagent %s' % r['lot_number'])
            continue
        _save_reagent(portal, dict(r))
        print('  create reagent %-34s %s' % (r['name'][:34], r['lot_number']))
    transaction.savepoint(optimistic=True)

    by_cat = {}
    for obj in folder.objectValues():
        by_cat[getattr(obj, 'cat_number', u'') or u''] = obj

    def parent_entry(cat):
        obj = by_cat.get(cat)
        if obj is None:
            return None
        exp = getattr(obj, 'expiry_date', None) or getattr(
            obj, 'manufacturer_expiry', None)
        if exp is None:
            exp = u''
        elif not isinstance(exp, (str, bytes, unicode)):  # noqa: F821 (py2)
            exp = exp.strftime('%Y-%m-%d')
        return {
            "name": obj.title,
            "supplier": getattr(obj, 'supplier', u'') or u'',
            "lot": getattr(obj, 'lot_number', u'') or u'',
            "expiry": exp,
        }

    # ── prepared standards ──────────────────────────────────────────────
    existing = {}
    for d in ps._list(portal):
        existing[d.get('lot_number')] = d

    for s in STANDARDS:
        if s['lot_number'] in existing:
            print('  reuse  standard %s' % s['lot_number'])
            continue
        parents = [p for p in (parent_entry(c) for c in s['parents']) if p]
        if len(parents) != len(s['parents']):
            print('  !! missing parent reagent for %s' % s['lot_number'])
        data = dict(s)
        data.pop('parents')
        data['parent_reagents'] = parents
        data['status'] = ps.STATUS_ACTIVE
        ps._save(portal, data)
        print('  create standard %-24s %s  (%d parents)'
              % (s['lot_number'], s['standard_type'][:20], len(parents)))

    transaction.commit()

    print('')
    print('Prepared standards now on file:')
    for d in ps._list(portal):
        print('  %-22s %-24s %-10s parents=%d'
              % (d.get('lot_number'), (d.get('standard_type') or u'')[:24],
                 d.get('status'), len(d.get('parent_reagents') or [])))


if __name__ == '__main__':
    run(app)  # noqa: F821
