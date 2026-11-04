# -*- coding: utf-8 -*-
"""The System map's nodes: the lab's live model as a tree, one level at a time.

    lab
      method (one per method profile)
        Analyte panel, QC rules          (settings, leaves)
        matrix (the method's matrices)
          worksheet (open, or created in the chosen period: PERIODS)
            Stages                       (Processing, Extraction, Analysis, Review)
            sample
              result (one per analysis with a result)
      Lots used by recent worksheets
        lot (reagent or prepared standard)
          parent lot (a prepared standard's reagents)
      Equipment
        type (core Instrument Type)
          item (core Instrument)

A matrix's worksheets come grouped by month (or status) when the page asks,
and only those of the chosen period: open ones always.

A node is {"id", "label", "kind", "sub", "url", "has_children", "facts":
[[label, value]], "badge", "badge_kind", "links": [node id]}. `links` are the
cross-links the page draws as arcs when both ends are open: a worksheet to
the lots and equipment it used, a lot to the worksheets that used it, a
prepared standard to the equipment it was made with.

Pure: the browser view gathers the inputs (profiles, worksheets, samples,
usage rows) and these functions shape them. Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

MAX_CHILDREN = 40          # beyond this a "N more" node, never a giant payload

KINDS = ("lab", "method", "matrix", "config", "worksheet", "stages", "sample",
         "result", "group", "lot", "more", "equipment", "wsgroup")

# "Worksheets from": days back (0 = all); open worksheets always show
PERIODS = ((30, u"30 days"), (90, u"90 days"), (365, u"1 year"), (0, u"All"))
GROUPINGS = (("month", u"Month"), ("status", u"Status"), ("none", u"None"))


def node(nid, label, kind, sub=u"", url=u"", has_children=False, facts=None,
         badge=u"", badge_kind=u"", links=None, panel=None):
    out = {"id": nid, "label": label or nid, "kind": kind, "sub": sub or u"",
           "url": url or u"", "has_children": bool(has_children),
           "facts": [[k, u"%s" % v] for k, v in (facts or []) if v not in (None, u"")],
           "badge": badge or u"", "badge_kind": badge_kind or u"",
           "links": list(links or [])}
    if panel:
        out["panel"] = panel
    return out


# ── the panel's parts for a selected node: why it is highlighted,
# where it is set, its records and files ──────────────────────────────────────

def method_panel(mid, purl, why):
    edit = u"%s/@@pfas-method-profile-edit?method_id=%s" % (purl, mid)
    return {"why": list(why or []),
            "set": [[u"Method profile", edit], [u"QC criteria", edit + u"#pane-qc"],
                    [u"Reporting limits", edit + u"#pane-analytes"], [u"Engine", edit + u"#pane-engine"],
                    [u"Logbook sequence", u"%s/@@pfas-logbook-admin?tab=sequence" % purl],
                    [u"EDD method codes", u"%s/@@pfas-edd-config" % purl],
                    [u"Import layouts", u"%s/@@pfas-import-studio" % purl]],
            "records": [[u"Issued revisions", edit + u"#pane-engine"],
                        [u"Logbook templates", u"%s/@@pfas-prep-logbooks" % purl],
                        [u"Configuration history", u"%s/@@pfas-config-history" % purl],
                        [u"Method studies", u"%s/@@pfas-method-studies" % purl]]}


def lot_panel(lot, purl, why):
    uid = lot.get("uid") or u""
    if lot.get("kind") == u"prepared_standard":
        return {"why": list(why or []),
                "set": [[u"Prepared Standards", u"%s/@@pfas-prep-standards" % purl]],
                "records": [[u"Lot record", u"%s/@@pfas-prep-standards?record=%s" % (purl, uid)],
                            [u"Usage", u"%s/@@pfas-lot-usage?kind=prepared_standard&uid=%s" % (purl, uid)]]}
    return {"why": list(why or []),
            "set": [[u"Reagent Inventory", u"%s/@@pfas-reagents" % purl]],
            "records": [[u"Usage", u"%s/@@pfas-lot-usage?kind=reagent&uid=%s" % (purl, uid)]]}


def equipment_panel(unit_id, purl, why):
    return {"why": list(why or []),
            "set": [[u"Equipment settings", u"%s/@@pfas-equipment-settings?uid=%s" % (purl, unit_id)]],
            "records": [[u"Equipment", u"%s/@@pfas-equipment" % purl]]}


def capped(nodes, parent_id, what=u"more"):
    """At most MAX_CHILDREN nodes, then one node saying how many are left."""
    if len(nodes) <= MAX_CHILDREN:
        return nodes
    rest = len(nodes) - MAX_CHILDREN
    return nodes[:MAX_CHILDREN] + [node(u"%s|more" % parent_id, u"%d more %s" % (rest, what), "more",
                                        sub=u"Open the list to see them")]


def norm(text):
    return u" ".join((text or u"").lower().replace(u"_", u" ").split())


def matrix_of(method_matrices, sample_types):
    """The method's matrix a worksheet's samples belong to: the most common
    sample type that names one of the method's matrices, else ""."""
    wanted = dict((norm(m), m) for m in method_matrices or [])
    counts = {}
    for t in sample_types or []:
        m = wanted.get(norm(t))
        if m:
            counts[m] = counts.get(m, 0) + 1
    if not counts:
        return u""
    return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]


def lab_children(methods, lot_count, equipment_count=None):
    """methods: [{"id", "label", "matrices": [..], "url"}]."""
    out = [node(u"m:%s" % m["id"], m.get("label") or m["id"], "method",
                sub=u"Method · %d matrices" % len(m.get("matrices") or []),
                url=m.get("url"), has_children=True,
                facts=[(u"Matrices", u", ".join(m.get("matrices") or []) or u"none set"),
                       (u"Revision", m.get("revision"))], panel=m.get("panel"))
           for m in methods]
    # lot_count None: not counted yet (the root is drawn without opening a worksheet)
    out.append(node(u"lots", u"Lots used by worksheets", "group",
                    sub=(u"%d lots" % lot_count) if lot_count is not None else u"Reagents and standards",
                    has_children=lot_count is None or lot_count > 0,
                    facts=[(u"Lots", lot_count)] if lot_count is not None else []))
    out.append(node(u"unresolved", u"Method not resolved", "group",
                    sub=u"Worksheets with no extraction or run yet", has_children=True,
                    facts=[(u"Why", u"No extraction started and no run processed, so the map "
                                    u"does not yet know the worksheet's method")]))
    out.append(node(u"equipment", u"Equipment", "equipment",
                    sub=(u"%d items" % equipment_count) if equipment_count is not None else u"Types and items",
                    has_children=equipment_count is None or equipment_count > 0,
                    facts=[(u"Items", equipment_count)] if equipment_count is not None else []))
    return out


def equipment_types(units):
    """The types the lab's equipment belongs to, each with its count.
    units: [{"id", "name", "type_title", "type_uid", ...}]."""
    by = {}
    for u in units or []:
        key = u.get("type_uid") or u"none"
        rec = by.setdefault(key, {"title": u.get("type_title") or u"No type", "n": 0})
        rec["n"] += 1
    return [node(u"eqt:%s" % k, v["title"], "equipment", sub=u"%d item%s" % (v["n"], u"" if v["n"] == 1 else u"s"),
                 has_children=True, facts=[(u"Items", v["n"])])
            for k, v in sorted(by.items(), key=lambda kv: kv[1]["title"].lower())]


def equipment_items(units, type_key, kind_labels=None, purl=None):
    """The items of one type (type_key: its uid, or "none")."""
    rows = [u for u in units or [] if (u.get("type_uid") or u"none") == type_key]
    rows.sort(key=lambda u: (u.get("name") or u"").lower())
    kinds = kind_labels or {}
    return capped([node(eq_id(u["id"]), u.get("name") or u["id"], "equipment",
                        sub=u"S/N %s" % u["serial_number"] if u.get("serial_number") else u"Equipment",
                        url=u.get("url"),
                        facts=[(u"Type", u.get("type_title")), (u"Kind", kinds.get(u.get("unit_type"), u.get("unit_type"))),
                               (u"Serial", u.get("serial_number")), (u"Location", u.get("location"))],
                        panel=equipment_panel(u["id"], purl, u.get("why")) if purl else None)
                   for u in rows], u"eqt:%s" % type_key, u"items")


def eq_id(unit_id):
    return u"eq:%s" % unit_id


def group_key(ws, mode):
    if mode == "month":
        return (ws.get("created") or u"")[:7] or u"undated"
    if mode == "status":
        return ws.get("state") or u"unknown"
    return u""


def worksheet_groups(worksheets, mode, parent_id):
    """A matrix's worksheets as groups (by month, newest first, or by status)
    with their counts, so a method opens to a few nodes, not hundreds."""
    counts = {}
    for w in worksheets or []:
        k = group_key(w, mode)
        counts[k] = counts.get(k, 0) + 1
    keys = sorted(counts, reverse=(mode == "month"))
    return [node(u"g:%s:%s@%s" % (mode, k, parent_id),
                 k.replace(u"_", u" ").capitalize() if mode == "status" else k, "wsgroup",
                 sub=u"%d worksheet%s" % (counts[k], u"" if counts[k] == 1 else u"s"), has_children=True,
                 facts=[(u"Worksheets", counts[k])])
            for k in keys]


def parse_group(nid):
    """(mode, key, parent node id) from a group node's id, or None."""
    if not nid.startswith(u"g:") or u"@" not in nid:
        return None
    head, _sep, parent = nid[2:].partition(u"@")
    mode, _sep, key = head.partition(u":")
    if mode not in dict(GROUPINGS) or mode == "none":
        return None
    return mode, key, parent


def method_children(method, ws_counts, profile_url):
    """The method's settings, then its matrices with their worksheet counts.
    ws_counts: {matrix: n} (u"" = samples whose type names no matrix)."""
    mid = method["id"]
    out = [node(u"cfg:panel:%s" % mid, u"Analyte panel", "config", sub=u"Method × matrix inclusion",
                url=profile_url + u"#tab-analytes"),
           node(u"cfg:qc:%s" % mid, u"QC rules", "config", sub=u"Rules on and off, limits",
                url=profile_url + u"#tab-qc")]
    for mx in method.get("matrices") or []:
        n = ws_counts.get(mx, 0)
        out.append(node(u"mx:%s|%s" % (mid, mx), mx, "matrix",
                        sub=u"%d worksheet%s" % (n, u"" if n == 1 else u"s"), has_children=n > 0,
                        facts=[(u"Recent worksheets", n)]))
    if ws_counts.get(u""):
        n = ws_counts[u""]
        out.append(node(u"mx:%s|" % mid, u"Matrix not matched", "matrix",
                        sub=u"%d worksheet%s" % (n, u"" if n == 1 else u"s"), has_children=True,
                        facts=[(u"Why", u"The samples' type names none of the method's matrices")]))
    return out


def worksheet_node(ws):
    """ws: {"id", "state", "url", "analyst", "samples", "created", "lots": [lot node ids]}."""
    state = ws.get("state") or u""
    kind = {"open": "badge-opened", "to_be_verified": "badge-quarantine",
            "verified": "badge-active", "published": "badge-active"}.get(state, "badge")
    return node(u"ws:%s" % ws["id"], ws["id"], "worksheet",
                sub=u"Worksheet · %s" % state.replace(u"_", u" "), url=ws.get("url"),
                has_children=True, badge=state.replace(u"_", u" "), badge_kind=kind,
                facts=[(u"Analyst", ws.get("analyst")), (u"Samples", ws.get("samples")),
                       (u"Created", ws.get("created"))],
                links=ws.get("lots"))


def matrix_children(worksheets, parent_id):
    rows = sorted(worksheets, key=lambda w: (w.get("created") or u"", w["id"]), reverse=True)
    return capped([worksheet_node(w) for w in rows], parent_id, u"worksheets")


STAGE_WORDS = {1: u"Processing", 2: u"Extraction", 3: u"Analysis", 4: u"Review", 5: u"Reported"}


def worksheet_children(ws_id, stage_steps, samples, review_url):
    """stage_steps: [{"num", "label", "status"}]; samples: [{"id", "csid",
    "state", "url", "results"}]."""
    marks = {"done": u"✓", "active": u"…", "pending": u"·"}
    sub = u" ".join(u"%s %s" % (STAGE_WORDS.get(s.get("num"), s.get("label"))[:4], marks.get(s.get("status"), u""))
                    for s in stage_steps if s.get("num") in (1, 2, 3, 4))
    out = [node(u"st:%s" % ws_id, u"Stages", "stages", sub=sub, url=review_url,
                facts=[(STAGE_WORDS.get(s.get("num"), s.get("label")), s.get("status"))
                       for s in stage_steps])]
    for s in samples:
        out.append(node(u"s:%s" % s["id"], s["id"], "sample",
                        sub=u"Sample · %s" % (s.get("state") or u"").replace(u"_", u" "),
                        url=s.get("url"), has_children=bool(s.get("results")),
                        facts=[(u"Client sample ID", s.get("csid")), (u"Results", s.get("results"))]))
    return capped(out, u"ws:%s" % ws_id, u"samples")


def sample_children(sample_id, analyses):
    """analyses: [{"keyword", "title", "result", "unit", "state", "url"}],
    those with a result only."""
    out = []
    for a in analyses:
        value = (u"%s %s" % (a.get("result") or u"", a.get("unit") or u"")).strip()
        state = (a.get("state") or u"").replace(u"_", u" ")
        out.append(node(u"r:%s|%s" % (sample_id, a.get("keyword")), u"%s %s" % (a.get("title") or a.get("keyword"), value),
                        "result", sub=u"Result · %s" % state, url=a.get("url"),
                        badge=state, badge_kind="badge-active" if a.get("state") in ("verified", "published") else "badge-quarantine",
                        facts=[(u"Analyte", a.get("title") or a.get("keyword")), (u"Value", value), (u"State", state)]))
    return capped(out, u"s:%s" % sample_id, u"results")


def lot_id(kind, uid):
    return u"lot:%s:%s" % (kind or u"reagent", uid)


def lots_from_uses(uses):
    """The lots in usage rows, each with the worksheets that used it:
    [{"id", "kind", "uid", "lot", "name", "worksheets": [ids]}], most used first."""
    by = {}
    for u in uses or []:
        if not u.get("uid"):
            continue
        key = lot_id(u.get("kind"), u["uid"])
        rec = by.setdefault(key, {"id": key, "kind": u.get("kind") or u"reagent", "uid": u["uid"],
                                  "lot": u.get("lot") or u"", "name": u.get("item_name") or u"",
                                  "worksheets": []})
        ws = u.get("batch_id")
        if ws and ws not in rec["worksheets"]:
            rec["worksheets"].append(ws)
    return sorted(by.values(), key=lambda r: (-len(r["worksheets"]), r["lot"]))


def lot_node(lot, has_parents=False, url=u"", equipment=None, purl=None):
    kind_word = u"Prepared standard" if lot["kind"] in (u"prepared_standard", u"standard") else u"Reagent lot"
    return node(lot["id"], lot.get("lot") or lot.get("name") or lot["uid"], "lot",
                sub=u"%s · %s" % (kind_word, lot.get("name") or u""), url=url,
                has_children=has_parents,
                facts=[(u"Item", lot.get("name")), (u"Lot", lot.get("lot")),
                       (u"Used by", u", ".join(lot.get("worksheets") or []))],
                links=[u"ws:%s" % w for w in lot.get("worksheets") or []] + [eq_id(e) for e in equipment or []],
                panel=lot_panel(lot, purl, lot.get("why")) if purl else None)


def ws_lot_links(uses):
    """{worksheet id: [lot node ids]} from usage rows."""
    out = {}
    for u in uses or []:
        if u.get("uid") and u.get("batch_id"):
            lid = lot_id(u.get("kind"), u["uid"])
            lst = out.setdefault(u["batch_id"], [])
            if lid not in lst:
                lst.append(lid)
    return out
