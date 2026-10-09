# -*- coding: utf-8 -*-
"""Pages shown as ONE page with sub-tabs.

Each group is a set of existing pages; each page keeps its own address and
view. The shared page frame (pfas_macros.pt) draws the group's tab strip on
every member page, and the sidebar shows the group as one item. Who sees a
tab follows the sidebar's role rules (pfas_sidebar.pt), and each page still
applies its own permission check.

    group_for(view_name)          the group a page belongs to, or None
    tabs_for(group, roles)        [(view_name, label)] the person may open
    first_for(group, roles)       where the sidebar item goes

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

STAFF = "staff"            # any lab role (Manager, LabManager, Analyst, Verifier, LabClerk)
MGR_ANA = "mgr_ana"        # managers and analysts / verifiers
MGR = "mgr"                # managers only

GROUPS = [
    {"id": "equipment-checks", "label": "Equipment Checks", "tabs": [
        ("pfas-facility-qc", "Daily Checklist", STAFF),
        ("pfas-temperature-log", "Temperature", STAFF),
        ("pfas-balance-log", "Balance", STAFF),
        ("pfas-weight-sets", "Weight Sets", STAFF),
        ("pfas-pipette-calibration", "Pipettes", STAFF),
        ("pfas-water-log", "Reagent Water", STAFF),
        ("pfas-waste-log", "Waste (SAA)", STAFF),
        ("pfas-eyewash-log", "Eye Wash", STAFF),
    ]},
    {"id": "reporting-setup", "label": "Reporting Setup", "tabs": [
        ("pfas-report-template", "Reporting Template", MGR_ANA),
        ("pfas-document-templates", "Document Templates", MGR),
        ("pfas-edd-config", "EDD Export", MGR_ANA),
        ("pfas-print-settings", "Print Settings", MGR),
    ]},
    {"id": "settings", "label": "Settings", "tabs": [
        ("pfas-lab-settings", "Lab Settings", MGR),
        ("pfas-site-settings", "Site Settings", MGR),
        ("pfas-lab-staff", "Lab Staff", MGR),
        ("pfas-terminals", "Terminals", MGR),
    ]},
]

_BY_VIEW = dict((view, g) for g in GROUPS for view, _label, _who in g["tabs"])


def _allowed(who, roles):
    roles = set(roles or ())
    mgr = bool(roles & set(("Manager", "LabManager")))
    ana = bool(roles & set(("Analyst", "Verifier")))
    clk = "LabClerk" in roles
    if who == MGR:
        return mgr
    if who == MGR_ANA:
        return mgr or ana
    return mgr or ana or clk


def view_name(url):
    """'.../@@pfas-balance-log?x=1' or '.../pfas-balance-log' -> 'pfas-balance-log'."""
    path = ("%s" % (url or "")).split("?", 1)[0].rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return last[2:] if last.startswith("@@") else last


def group_for(view):
    return _BY_VIEW.get(view)


def tabs_for(group, roles):
    return [(view, label) for view, label, who in (group or {}).get("tabs", []) if _allowed(who, roles)]


def first_for(group, roles):
    tabs = tabs_for(group, roles)
    return tabs[0][0] if tabs else None


def group_by_id(group_id):
    for g in GROUPS:
        if g["id"] == group_id:
            return g
    return None
