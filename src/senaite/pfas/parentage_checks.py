# -*- coding: utf-8 -*-
"""The expiry checks of the parentage review: every lot a run used, to full
depth, as the nodes prepared_standards.build_parentage returns.

A node is flagged when it is
    - expired by the run date (a lot expiring on the run date is in date,
      as bench_queue.is_usable has it), or has no expiry date at all;
    - made from a parent that was out of date on the day it was prepared,
      unless the preparation kept a reason on that parent;
    - set to expire after one of its parents;
    - pending acceptance, quarantined, or without its storage conditions.

    in_force(node, day)                         -> the node's expiry in force on day
    node_problems(node, parent_nodes, run_date) -> [reason]
    walk_problems(nodes, run_date)              -> [{"lot", "name", "reason", "pending"}]
    walk_below(root, use_date)                  -> walk_problems without the
                                                   root's own expiry / status
    capped_expiry(own, parent_expiries)         -> the earliest known, or ""
    default_expiry(prepared_date, days, cap)    -> (expiry, capped by a parent)

Dates are ISO strings (YYYY-MM-DD), compared as text. Pure; Python 2.7 and 3.
"""
from __future__ import absolute_import, unicode_literals

from senaite.pfas.lot_expiry import expired_on

PENDING_REASON = u"pending acceptance"
_CHECKED_KINDS = (u"manufacturer", u"water", u"prepared", None)


def _d(value):
    return (u"%s" % (value or u""))[:10]


def default_expiry(prepared_date, days, parent_cap):
    """(expiry, capped): a prep with no stated expiry, the default period
    from its prep date, capped by its parents' effective expiry."""
    import datetime
    made = datetime.datetime.strptime(_d(prepared_date), "%Y-%m-%d").date()
    own = (made + datetime.timedelta(days=int(days))).isoformat()
    cap = _d(parent_cap)
    return (cap, True) if cap and cap < own else (own, False)


def capped_expiry(own, parent_expiries):
    known = [_d(e) for e in [own] + list(parent_expiries or []) if _d(e)]
    return min(known) if known else u""


def in_force(node, day):
    """A node's expiry in force on `day`: its latest extension QA approved by
    then (lot_extension.in_force) over its own date ("expiry_base" when the
    node shows the extended date as "expiry"); a node that carries no
    extensions is its "expiry"."""
    if not node.get("extensions"):
        return _d(node.get("expiry"))
    from senaite.pfas import lot_extension
    base = node.get("expiry_base") if "expiry_base" in node else node.get("expiry")
    return _d(lot_extension.in_force(_d(base), node.get("extensions"), _d(day) or None))


def node_problems(node, parent_nodes, run_date):
    """The reasons one lot fails the review. Each lot is judged on the date
    in force on the day in question (in_force): the lot on the run date, a
    parent on the day this lot was prepared."""
    out = []
    expiry, made, run_date = in_force(node, run_date), _d(node.get("prepared_date")), _d(run_date)
    if not expiry:
        # a lot whose category has no expiry is not missing a date
        if not node.get("no_expiry"):
            out.append(u"no expiry date")
    elif expired_on(expiry, run_date):
        out.append(u"expired on the run date (%s)" % expiry)
    for p in parent_nodes or []:
        pexp = in_force(p, run_date)
        if not pexp:
            continue
        # a parent used out of date with a reason kept on it (lot_expiry.gate)
        # is a recorded use, not a finding
        if expired_on(in_force(p, made), made) and not (p.get("expired_reason") or u"").strip():
            out.append(u"parent %s was out of date when this lot was prepared" % p.get("lot"))
        if expiry and expiry > pexp:
            out.append(u"expires after its parent %s (%s)" % (p.get("lot"), pexp))
    status = node.get("status")
    if status == u"pending":
        out.append(PENDING_REASON)
    elif status == u"quarantine":
        out.append(u"quarantined")
    if not (node.get("storage_conditions") or u"").strip():
        out.append(u"storage conditions not recorded")
    return out


def walk_problems(nodes, run_date):
    """Depth-first over the tree: every node's reasons, with the lot."""
    out = []
    for n in nodes or []:
        if n.get("kind") in _CHECKED_KINDS:
            for reason in node_problems(n, n.get("children"), run_date):
                out.append({"lot": n.get("lot") or u"", "name": n.get("name") or u"",
                            "reason": reason, "pending": reason == PENDING_REASON,
                            # the lot itself, for the reviewer's approve / reject
                            "uid": n.get("uid") or u"", "kind": n.get("kind")})
        out.extend(walk_problems(n.get("children"), run_date))
    return out


_OWN = (u"no expiry date", u"quarantined", PENDING_REASON)


def walk_below(root, use_date):
    """walk_problems for a lot whose own expiry and status are judged
    elsewhere (an extraction's lot: expiry at use, pending, a quarantined
    lot picked with a note): its parents to full depth, its storage
    conditions and its expiry against its parents."""
    out = []
    for p in walk_problems([root], use_date):
        if p["uid"] == root.get("uid") and p["lot"] == root.get("lot") and (
                p["reason"] in _OWN or p["reason"].startswith(u"expired on")):
            continue
        out.append(p)
    return out
