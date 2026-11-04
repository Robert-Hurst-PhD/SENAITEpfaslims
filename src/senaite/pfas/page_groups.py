# -*- coding: utf-8 -*-
"""The navigation map: sections, their items, the items' pages.

SECTIONS lists the six sections and their items. An item is a family of
pages (GROUPS: an item and its tabs, a nested family's tabs a level below)
or a page of its own (ITEMS, Logbooks with its pages as children). Each
page keeps its own address and view. Who sees a row is _allowed on its
`who`, the role SENAITE enforces on the page; each page still applies its
own permission check.

    sections(roles)               the sections the person may open
    tree(section, roles, path, query)  a section's rows, the page's branch open
    node_for(path, query)         (section, item, child, check) of a page, or None
    crumbs(path, query, roles)    [(label, url_path)] from the section down
    pages(roles)                  every page the person may open, with its place
    nav_model(roles, path, query, landing, pins)  the rail and the panel for a page

A family of pages:

    group_for(view_name)          the group a page belongs to, or None
    tabs_for(group, roles)        [(key, label)] the person may open
    first_for(group, roles)       the first of them
    match(path, params)           (group, key) of a page, by its path and query

Pure: Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

STAFF = "staff"            # any lab role (Manager, LabManager, Analyst, Verifier, LabClerk)
MGR_ANA = "mgr_ana"        # managers and analysts / verifiers
MGR = "mgr"                # managers only
MGR_CLK = "mgr_clk"        # managers and clerks (the core instruments list)

# A tab is (key, label, who) for a PFAS view @@<key>, or (key, label, who,
# path) for any other page under the site: a core listing ("samples"), or a
# view with the query that tells its pages apart ("@@lims-setup?section=
# storage"). A tab "group:<id>" is that whole group, its first page the
# tab's link: the group's own strip follows under its parent's. A group
# that is another's tab is not a sidebar item of its own.
GROUPS = [
    {"id": "samples", "label": "Samples", "tabs": [
        ("samples", "Samples", STAFF, "samples"),
        ("pfas-track", "Sample Tracker", STAFF),
    ]},
    {"id": "data-review", "label": "Data Review", "tabs": [
        ("pfas-data-review", "Data Review", MGR_ANA),
        ("pfas-control-chart", "Control Charts", MGR_ANA),
    ]},
    {"id": "method-profiles", "label": "Method Profiles & QC", "tabs": [
        ("pfas-method-profiles", "Method Profiles & QC", MGR),
        ("pfas-method-studies", "Method Studies", MGR_ANA),
    ]},
    {"id": "reagents", "label": "Reagents & Standards", "tabs": [
        ("pfas-reagents", "Reagent Inventory", STAFF),
        ("pfas-prep-standards", "Prepared Standards", STAFF),
    ]},
    {"id": "extraction", "label": "Extraction", "tabs": [
        ("pfas-homogenisation", "Homogenisation", STAFF),
        ("pfas-extraction-guide", "Extraction Guide", STAFF),
        ("pfas-run-builder", "Run Builder", STAFF),
    ]},
    {"id": "equipment", "label": "Equipment", "tabs": [
        ("pfas-equipment", "Equipment", STAFF),
        ("pfas-equipment-types", "Equipment Types", MGR),
        ("pfas-homogenisation-setup", "Homogenisation Methods", MGR),
        ("group:equipment-checks", "Equipment Checks", STAFF),
    ]},
    {"id": "equipment-checks", "label": "Equipment Checks", "tabs": [
        ("pfas-facility-qc", "Daily Checklist", STAFF),
        ("pfas-temperature-log", "Facility Monitoring", STAFF),
        ("pfas-balance-log", "Balance", STAFF),
        ("pfas-weight-sets", "Weight Sets", STAFF),
        ("pfas-reference-thermometers", "Reference Thermometers", STAFF),
        ("pfas-pipette-calibration", "Pipettes", STAFF),
        ("pfas-water-log", "Reagent Water", STAFF),
        ("pfas-waste-log", "Waste (SAA)", STAFF),
        ("pfas-eyewash-log", "Eye Wash", STAFF),
    ]},
    {"id": "instruments", "label": "Instruments", "tabs": [
        ("instruments", "Instruments", MGR_CLK, "bika_setup/bika_instruments"),
        ("pfas-import-studio", "Import Studio", STAFF),
        ("pfas-calibrations", "Calibration Archive", STAFF),
    ]},
    {"id": "reports", "label": "Reports", "tabs": [
        ("reports", "Reports", MGR_ANA, "samples?review_state=published"),
        ("pfas-controlled-publications", "Controlled Publications", MGR),
        ("pfas-edd-batches", "Delivered EDDs", MGR),
    ]},
    {"id": "reporting-setup", "label": "Reporting Setup", "tabs": [
        ("pfas-report-template", "Reporting Template", MGR_ANA),
        ("pfas-document-templates", "Document Templates", MGR),
        ("pfas-edd-config", "EDD Export", MGR_ANA),
        ("pfas-print-settings", "Print Settings", MGR),
        ("pfas-qc-qualifiers", "QC Qualifiers", MGR),
        ("pfas-regulatory-limits", "Regulatory Limits", MGR),
    ]},
    {"id": "settings", "label": "Settings", "tabs": [
        ("pfas-laboratory", "Laboratory", MGR),
        ("pfas-people", "People & Roles", MGR),
        ("pfas-time-language", "Time & Language", MGR),
        ("pfas-system", "System", MGR),
        ("pfas-terminals", "Terminals", MGR),
        ("pfas-backups", "Backups", MGR),
        ("pfas-config-history", "Configuration History", MGR),
        ("pfas-system-map", "System Map", MGR),
    ]},
    {"id": "setup", "label": "Setup", "tabs": [
        ("lims-setup", "General", MGR, "@@lims-setup"),
        ("lims-setup-storage", "Storage & Inventory", MGR, "@@lims-setup?section=storage"),
        ("lims-setup-instruments", "Instrument Setup", MGR, "@@lims-setup?section=instruments"),
        ("lims-setup-methods", "Method & Analyte Setup", MGR, "@@lims-setup?section=methods"),
        ("lims-setup-workflow", "Workflow & QC", MGR, "@@lims-setup?section=workflow"),
        ("lims-setup-regulatory", "Regulatory Reporting", MGR, "@@lims-setup?section=regulatory"),
    ]},
]

NESTED = "group:"

# Pages that are part of a tab's page without being tabs themselves: the
# group's strip shows them under that tab, and the sidebar marks its item.
# A page under a tab's path (an instrument under the instruments list) is
# that tab's too.
ALSO = {
    "pfas-equipment": ["pfas-equipment-settings"],
    "pfas-method-profiles": ["pfas-method-profile-edit", "pfas-method-wizard"],
    "pfas-reagents": ["pfas-lot-usage", "pfas-assigned-levels"],
}

# Pages that ARE their row's own page under another address (the landing of
# Data Review, which draws the tab's title; a batch's logbook list, which
# draws By batch's): they mark the row like ALSO pages, but the breadcrumb
# ends at the row and adds no title. A tab's are joined to ALSO here; an
# item's child names its pages in the item's children_also.
SAME = {
    "pfas-data-review": ["pfas-data-review-home"],
    "pfas-logbook-batches": ["pfas-logbook-index"],
}
for _key, _pages_of in SAME.items():
    if _key in set(t[0] for g in GROUPS for t in g["tabs"]):
        ALSO[_key] = ALSO.get(_key, []) + list(_pages_of)


def is_row_page(path):
    """True when `path` is a page that is its row's own page (SAME), at the
    site or as a view on a record (a batch's logbooks)."""
    mine = set(_norm(p) for pages_of in SAME.values() for p in pages_of)
    here = _norm(path)
    return here in mine or here.rsplit("/", 1)[-1] in mine


def is_dashboard(path):
    """True when `path` (under the site) is the Dashboard, which is no page
    of the map."""
    return _norm(path) in _DASHBOARD


def same_page(a, b):
    """True when two paths (a query ignored) name the same page."""
    return _norm(("%s" % a).split("?", 1)[0]) == _norm(("%s" % b).split("?", 1)[0])


def _tab(t):
    """(key, label, who, path) for a tab written with or without its path."""
    return (t[0], t[1], t[2], t[3] if len(t) > 3 else "@@" + t[0])


def _pages():
    """(group, key, path) for every tab that is a page (not a nested group),
    and for each page that is part of one (ALSO)."""
    for g in GROUPS:
        for t in g["tabs"]:
            key, _label, _who, path = _tab(t)
            if not key.startswith(NESTED):
                yield g, key, path
                for other in ALSO.get(key, ()):
                    yield g, key, "@@" + other


_BY_VIEW = dict((key, g) for g, key, _path in _pages())


def _allowed(who, roles):
    roles = set(roles or ())
    mgr = bool(roles & set(("Manager", "LabManager")))
    ana = bool(roles & set(("Analyst", "Verifier")))
    clk = "LabClerk" in roles
    if who == MGR:
        return mgr
    if who == MGR_ANA:
        return mgr or ana
    if who == MGR_CLK:
        return mgr or clk
    return mgr or ana or clk


def view_name(url):
    """'.../@@pfas-balance-log?x=1' or '.../pfas-balance-log' -> 'pfas-balance-log'."""
    path = ("%s" % (url or "")).split("?", 1)[0].rstrip("/")
    last = path.rsplit("/", 1)[-1]
    return last[2:] if last.startswith("@@") else last


def group_for(view):
    return _BY_VIEW.get(view)


def group_by_id(group_id):
    for g in GROUPS:
        if g["id"] == group_id:
            return g
    return None


def parent_of(group):
    """The group that holds this one as a tab, or None."""
    want = NESTED + (group or {}).get("id", "")
    for g in GROUPS:
        if any(_tab(t)[0] == want for t in g["tabs"]):
            return g
    return None


def tabs_for(group, roles):
    """[(key, label)] of the group's tabs this person may open; a nested
    group's tab only while one of its own is open to them."""
    out = []
    for t in (group or {}).get("tabs", []):
        key, label, who, _path = _tab(t)
        if not _allowed(who, roles):
            continue
        if key.startswith(NESTED) and not tabs_for(group_by_id(key[len(NESTED):]), roles):
            continue
        out.append((key, label))
    return out


def path_for(group, key, roles):
    """Where a tab goes, under the site: its page, or a nested group's first."""
    if key.startswith(NESTED):
        inner = group_by_id(key[len(NESTED):])
        tabs = tabs_for(inner, roles)
        return path_for(inner, tabs[0][0], roles) if tabs else None
    for t in group["tabs"]:
        if _tab(t)[0] == key:
            return _tab(t)[3]
    return None


def first_for(group, roles):
    tabs = tabs_for(group, roles)
    return tabs[0][0] if tabs else None


def _norm(path):
    """A path under the site, each step without "@@", no trailing /view."""
    steps = [p[2:] if p.startswith("@@") else p for p in ("%s" % path).strip("/").split("/") if p]
    if steps and steps[-1] in ("view", "base_view"):
        steps = steps[:-1]
    return "/".join(steps)


def _query(text):
    out = {}
    for part in ("%s" % (text or "")).split("&"):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k] = v
    return out


def match(path, params):
    """(group, key) of the page at `path` (under the site) with query
    `params` ({name: value}), or (None, None): the tab whose path is the
    page's and whose query the page carries; of several, the one naming the
    most of the query (the published samples are Reports, the others Samples)."""
    here = _norm(path)
    best, best_n = (None, None), (-1, -1)
    for g, key, tpath in _pages():
        tp, _sep, tq = tpath.partition("?")
        want, where = _query(tq), _norm(tp)
        exact = where == here
        if not (exact or (where and here.startswith(where + "/"))):
            continue
        if any(params.get(k) != v for k, v in want.items()):
            continue
        rank = (1 if exact else 0, len(want))         # its own page before a page under it
        if rank > best_n:
            best, best_n = (g, key), rank
    return best


def chain(group):
    """The group and the groups it is a tab of, outermost first."""
    out = [group]
    while parent_of(out[0]) is not None:
        out.insert(0, parent_of(out[0]))
    return out


# -- The map: sections > items > children > checks ---------------------------
#
# The navigation is six sections, each a list of items. An item is a family
# above (its children are the family's tabs, a nested family's tabs the
# grandchildren), or one of the pages below. Who sees a row is _allowed on
# its `who`; a section shows when its `who` admits the person and one of its
# items is open to them.

SECTIONS = (
    {"id": "operations", "label": "Operations", "short": "Operations", "icon": "ico-batches",
     "who": STAFF, "items": ["clients", "samples", "batches", "worksheets", "chain-of-custody", "projects"]},
    {"id": "qc", "label": "QC & Methods", "short": "QC & Methods", "icon": "ico-qc-rules",
     "who": MGR_ANA, "items": ["data-review", "method-profiles"]},
    {"id": "bench", "label": "Bench", "short": "Bench", "icon": "ico-extraction",
     "who": STAFF, "items": ["reagents", "logbooks", "extraction", "controlled-documents", "deviations"]},
    {"id": "equipment", "label": "Equipment & Instruments", "short": "Equipment", "icon": "ico-instruments",
     "who": STAFF, "items": ["equipment", "instruments"]},
    {"id": "reporting", "label": "Reporting", "short": "Reporting", "icon": "ico-book",
     "who": MGR_ANA, "items": ["reports", "reporting-setup"]},
    {"id": "config", "label": "Configuration", "short": "Config", "icon": "ico-workflow",
     "who": MGR, "items": ["settings", "setup"]},
)

# Items that are not a family: their own page, and the pages that are part
# of it (`also`, as ALSO; `children_also` for its children). Logbooks opens
# By batch and has its four pages as children; By batch also holds a
# batch's logbook list and its forms.
ITEMS = {
    "clients": {"label": "Clients", "who": STAFF, "path": "clients"},
    "batches": {"label": "Batches", "who": STAFF, "path": "batches", "also": ["pfas-sample-status"]},
    "worksheets": {"label": "Worksheets", "who": STAFF, "path": "worksheets"},
    "chain-of-custody": {"label": "Chain of Custody", "who": STAFF, "path": "@@pfas-coc"},
    "projects": {"label": "Projects", "who": STAFF, "path": "@@pfas-projects"},
    "logbooks": {"label": "Logbooks", "who": STAFF, "path": "@@pfas-logbook-batches", "children": [
        ("pfas-prep-logbooks", "Templates", MGR),
        ("pfas-logbook-admin", "Method sequence", MGR),
        ("pfas-logbook-batches", "By batch", STAFF),
        ("pfas-recipes", "Recipes", MGR),
    ], "children_also": {"pfas-logbook-batches": ["pfas-logbook-index", "pfas-logbook-dynamic"]}},
    "controlled-documents": {"label": "Controlled Documents", "who": STAFF, "path": "@@pfas-sop"},
    "deviations": {"label": "Deviations / CARs", "who": STAFF, "path": "@@pfas-deviations"},
}


def _spec_tabs(tabs, also):
    """Row specs for a list of tabs; a nested family is a row of its own tabs."""
    out = []
    for t in tabs:
        key, label, who, path = _tab(t)
        if key.startswith(NESTED):
            inner = group_by_id(key[len(NESTED):])
            out.append({"key": inner["id"], "label": label, "who": who, "path": None,
                        "also": [], "children": _spec_tabs(inner["tabs"], also)})
        else:
            out.append({"key": key, "label": label, "who": who, "path": path,
                        "also": ["@@" + v for v in also.get(key, ())], "children": []})
    return out


def _spec(item_id):
    """An item as a row spec {"key", "label", "who", "path", "also",
    "children"}; a family's item has no page of its own (path None)."""
    item = ITEMS.get(item_id)
    if item is None:
        group = group_by_id(item_id)
        return {"key": item_id, "label": group["label"], "who": STAFF, "path": None,
                "also": [], "children": _spec_tabs(group["tabs"], ALSO)}
    return {"key": item_id, "label": item["label"], "who": item["who"], "path": item["path"],
            "also": ["@@" + v for v in item.get("also", ())],
            "children": _spec_tabs(item.get("children", ()), item.get("children_also", {}))}


def _visible(spec, roles):
    """The row as this person sees it: {"keys", "label", "url_path",
    "children"}, or None when nothing in it is open to them. A row with one
    child open is that child's page: it keeps its own name when it names a
    page of its own (Logbooks), else it takes the child's (a family). `keys`
    are the map keys the row stands for, outermost first."""
    if not _allowed(spec["who"], roles):
        return None
    if not spec["children"]:
        return {"keys": (spec["key"],), "label": spec["label"], "url_path": spec["path"], "children": []}
    kids = [v for v in (_visible(c, roles) for c in spec["children"]) if v is not None]
    if not kids:
        return None
    if len(kids) == 1 and not kids[0]["children"]:
        one = kids[0]
        return {"keys": (spec["key"],) + one["keys"],
                "label": spec["label"] if spec["path"] else one["label"],
                "url_path": one["url_path"], "children": []}
    return {"keys": (spec["key"],), "label": spec["label"],
            "url_path": spec["path"] or kids[0]["url_path"], "children": kids}


def _section(section_id):
    for s in SECTIONS:
        if s["id"] == section_id:
            return s
    return None


def _items(section, roles):
    """The section's item rows this person sees, in order; none when the
    section itself is not theirs."""
    if section is None or not _allowed(section["who"], roles):
        return []
    rows = (_visible(_spec(i), roles) for i in section["items"])
    return [r for r in rows if r is not None]


def sections(roles):
    """The sections this person may open, in order, each a copy of its
    SECTIONS entry with only the items open to them."""
    out = []
    for s in SECTIONS:
        rows = _items(s, roles)
        if rows:
            out.append(dict(s, items=[r["keys"][0] for r in rows]))
    return out


def _params(path, query):
    """(path, {name: value}): the query as a dict or a query string, and any
    query the path itself carries (a stored pin)."""
    path, _sep, inline = ("%s" % (path or "")).partition("?")
    params = _query(inline)
    params.update(query if isinstance(query, dict) else _query(query))
    return path, params


def _map_pages():
    """(section id, keys, path) of every page in the map, ALSO included,
    whoever may open it."""
    for s in SECTIONS:
        for item_id in s["items"]:
            stack = [(_spec(item_id), ())]
            while stack:
                spec, above = stack.pop()
                keys = above + (spec["key"],)
                for path in ([spec["path"]] if spec["path"] else []) + spec["also"]:
                    yield s["id"], keys, path
                stack.extend((c, keys) for c in spec["children"])


def node_for(path, query):
    """Where a page is in the map: (section id, item key, child key, check
    key), the levels below its own None; or None when it is in no section.

    `path` is under the site, `query` a query string or {name: value}. A
    page is the map page whose path is its own and whose query it carries;
    else a map view it shows on some record (a batch's logbooks); else the
    map page it is under (a record view). Of several, the one naming the
    most of the query, then the deepest (a child before its item)."""
    path, params = _params(path, query)
    here = _norm(path)
    if not here:
        return None
    last = here.rsplit("/", 1)[-1]
    best, best_rank = None, None
    for section_id, keys, mpath in _map_pages():
        mp, _sep, mq = mpath.partition("?")
        want, where = _query(mq), _norm(mp)
        if any(params.get(k) != v for k, v in want.items()):
            continue
        if where == here:
            tier = (2, 0)
        elif mp.startswith("@@") and "/" not in where and where == last:
            tier = (1, 0)
        elif here.startswith(where + "/"):
            tier = (0, where.count("/"))                   # the nearest page above it
        else:
            continue
        rank = tier + (len(want), len(keys))
        if best_rank is None or rank > best_rank:
            best, best_rank = (section_id,) + keys, rank
    if best is None:
        return None
    return tuple(best) + (None,) * (4 - len(best))


def _branch(where, section_id):
    """The keys below the section on the way to the page, if it is in this
    section."""
    if where is None or where[0] != section_id:
        return ()
    return tuple(k for k in where[1:] if k is not None)


def _on(row, branch):
    """How many of the branch's keys this row stands for, or 0 when it is
    not on the branch."""
    keys = row["keys"]
    n = min(len(keys), len(branch))
    return n if n and keys[:n] == branch[:n] else 0


def _node(row, branch):
    n = _on(row, branch)
    rest = branch[n:] if n else ()
    return {"key": row["keys"][0], "label": row["label"], "url_path": row["url_path"],
            "children": [_node(c, rest) for c in row["children"]],
            "open": bool(n and row["children"]),
            "current": bool(n and not rest)}


def tree(section_id, roles, path, query):
    """The section's rows for this person: [{"key", "label", "url_path",
    "children", "open", "current"}]. The current page's row is current and
    the rows above it are open; a page they cannot open marks no row."""
    branch = _branch(node_for(path, query), section_id)
    return [_node(r, branch) for r in _items(_section(section_id), roles)]


def crumbs(path, query, roles):
    """[(label, url_path)] from the section (no page of its own: None) down
    to the page's row, as this person's tree shows it; a child named as its
    item is not named twice. [] for a page on none of their rows, as the
    tree then marks none."""
    where = node_for(path, query)
    section = _section(where[0]) if where else None
    rows = _items(section, roles)
    if not rows:
        return []
    out, branch = [(section["label"], None)], _branch(where, section["id"])
    while branch:
        row = next((r for r in rows if _on(r, branch)), None)
        if row is None:
            break
        if row["label"] != out[-1][0]:
            out.append((row["label"], row["url_path"]))
        branch, rows = branch[_on(row, branch):], row["children"]
    return out if len(out) > 1 else []


def pages(roles):
    """Every page this person may open from the navigation:
    [{"key", "label", "url_path", "section", "place"}], `place` naming the
    rows above it ("Equipment & Instruments > Equipment > Equipment
    Checks"). A row with children is not a page of its own: it opens one
    of them. A page is in one place in the map, so each is listed once; a
    page put in two places is listed twice, not hidden."""
    out = []

    def walk(row, section_id, above):
        if row["children"]:
            for c in row["children"]:
                walk(c, section_id, above + [row["label"]])
        else:
            out.append({"key": row["keys"][-1], "label": row["label"], "url_path": row["url_path"],
                        "section": section_id, "place": " > ".join(above)})

    for s in SECTIONS:
        for row in _items(s, roles):
            walk(row, s["id"], [s["label"]])
    return out


# -- The rail and the panel ---------------------------------------------------
#
# The rail is Home and the sections the person may open; the panel holds one
# tree per rail button. Home is the Dashboard (the launcher, which sends each
# role to its landing) and the person's pins.

HOME = {"id": "home", "label": "Home", "short": "Home", "icon": "ico-home",
        "dashboard": {"key": "dashboard", "label": "Dashboard", "url_path": "@@pfas-home"},
        "pins_label": "Pinned"}
_DASHBOARD = ("", "pfas-home")      # the site root and the launcher, under the site


def _drawn(node, row, section_id, above, leaves, labels):
    """A tree row (_node) for the panel, from the person's row (_visible) it
    was made of: its group's id (for aria-owns, unique on the page), its
    place in the map as node_for gives a page's (section, item, child,
    check), pinned (False; nav_model marks pins) and pinnable (a page of the
    map: its row menu offers Pin). Each page row is added to `leaves` by its
    place, with `labels`, the labels of the rows above it, section first."""
    keys = above + row["keys"]
    where = ((section_id,) + keys + (None,) * 3)[:4]
    gid = "pfas-nav-%s-%s" % (section_id, "-".join(keys)) if node["children"] else None
    below = labels + (node["label"],)
    out = dict(node, group_id=gid, where=where, pinned=False, pinnable=True,
               children=[_drawn(n, r, section_id, keys, leaves, below)
                         for n, r in zip(node["children"], row["children"])])
    if not node["children"]:
        leaves.setdefault(where, (out, labels))
    return out


def _pin_rows(leaves, pins):
    """The stored pins that are page rows of this person's (`leaves`, as
    _drawn fills it), each page once, in pin order: [{"path" as stored,
    "url_path", "label", "place", "ambiguous"}]. `place` names the rows
    above the page as pages() does; `ambiguous` is true when another pin
    has the same label, so the list names the place too. Each pin's page
    row is marked pinned."""
    out, seen = [], set()
    for stored in pins or ():
        key = node_for(stored, "")
        hit = leaves.get(key)
        if hit is None or key in seen:
            continue
        seen.add(key)
        row, labels = hit
        row["pinned"] = True
        out.append({"path": stored, "url_path": row["url_path"], "label": row["label"],
                    "place": " > ".join(labels)})
    count = {}
    for r in out:
        count[r["label"]] = count.get(r["label"], 0) + 1
    for r in out:
        r["ambiguous"] = count[r["label"]] > 1
    return out


def nav_model(roles, path, query, landing=None, pins=()):
    """The rail and the panel for this person on the page at `path` (under the
    site) with `query`: {"section": the section shown, "sections": [{"id",
    "label", "short", "icon", "shown", "here", "tree", "pins"}]}, Home first,
    then sections(roles). `tree` is tree() with each row's group_id, its
    place (`where`, as node_for gives it) and pinned: a row is pinned when
    its own page is a stored pin, so a family's row never is; and pinnable,
    which the Dashboard is not (it is no page of the map). `pins` (Home
    only, else None) the stored pins that are pages this person may open,
    each once, by the map's label (_pin_rows). Each stored pin is resolved
    once.

    The section shown is the page's own when the person may open it; Home on
    the dashboard; else `landing` (the role's section, workspace_home
    LANDINGS) when it is theirs; else Home. `here` marks the section of the
    current page; a page in none of theirs marks none."""
    path, params = _params(path, query)
    secs = sections(roles)
    ids = [s["id"] for s in secs]
    where = node_for(path, params)
    on_dashboard = _norm(path) in _DASHBOARD
    page_section = "home" if on_dashboard else (where[0] if where and where[0] in ids else None)
    shown = page_section or (landing if landing in ids else "home")

    leaves, drawn = {}, []
    for s in secs:
        branch = _branch(where, s["id"])
        rows = [_drawn(_node(r, branch), r, s["id"], (), leaves, (s["label"],))
                for r in _items(_section(s["id"]), roles)]
        drawn.append((s, rows))
    pin_rows = _pin_rows(leaves, pins)

    dash = dict(HOME["dashboard"], children=[], open=False, current=on_dashboard, pinned=False,
                pinnable=False, group_id=None, where=None)
    out = [{"id": HOME["id"], "label": HOME["label"], "short": HOME["short"], "icon": HOME["icon"],
            "pins_label": HOME["pins_label"], "tree": [dash], "pins": pin_rows}]
    for s, rows in drawn:
        out.append({"id": s["id"], "label": s["label"], "short": s["short"], "icon": s["icon"],
                    "tree": rows, "pins": None})
    for s in out:
        s["shown"] = s["id"] == shown
        s["here"] = s["id"] == page_section
    return {"section": shown, "sections": out}

