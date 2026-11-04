# -*- coding: utf-8 -*-
"""Lab Settings — one page that lists every setting the lab owns.

WHY
---
Configuration is spread across six sidebar groups, and the group actually named
"Configuration" holds mostly deep links into core SENAITE's setup. So "where do I
change X" currently requires knowing which group owns X. This page answers it in
one place, enumerated from `settings_registry` rather than from a hand-maintained
list, so a newly declared setting appears here without anyone remembering to add
it.

READ-ONLY, DELIBERATELY
-----------------------
Every setting declared so far is `linked` -- an existing editor owns it (Rule 2:
build on working code). This page lists, shows status, and LINKS to that editor;
it does not write. A second writer to data another editor owns would recreate at
a larger scale the split-key defect WIRING.md §1.4 reports. Inline editing
arrives only for `registry`-owned settings, which are created one at a time
together with the consumer that reads them.

The status column is the point of the page:

    Default          the seed in code; the lab has not changed it
    Customised       the lab has set it
    NOT CONFIGURED   a JUDGING setting with no value -- this blocks a run
    Derived          computed from something else; no editor exists by design
    Unknown          the owning store could not be read

`NOT CONFIGURED` exists because of the to refuse rather than
substitute: an unset acceptance criterion stops a batch instead of quietly
passing it, and until now nothing showed a lab WHICH criterion.

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import logging

from Products.Five.browser import BrowserView
from senaite.pfas.browser.view_helpers import ViewHelpers
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile

from senaite.pfas import settings_registry as reg
from senaite.pfas.browser.formutil import flatten_form

logger = logging.getLogger("senaite.pfas.browser.lab_settings")

# Status -> (badge class, label). The classes are the ones already defined
# globally in pfas_macros.pt, so this page adds no colours of its own (§6C).
_STATUS_META = {
    "seed":     ("badge-default", u"Default"),
    "override": ("badge-custom", u"Customised"),
    "unset":    ("badge-expired", u"NOT CONFIGURED"),
    "derived":  ("badge-opened", u"Derived"),
    "unknown":  ("badge-quarantine", u"Unknown"),
}


# QC limits and acceptance criteria belong to the method profiles, which own
# and edit them; the console does not list them.
CONSOLE_GROUPS = tuple(g for g in reg.GROUPS if g != reg.GROUP_QC_LIMITS)


# A QC check's two settings read as one row on the reference: what happens
# when it fails, then the certificate's wording beneath.
DISPOSITION_WORDS = {"block": u"Hold the result", "qualify": u"Report with qualifier"}


def merge_qc_wording(rows):
    """The "qualifier.<check>.disposition" and ".statement" settings of one QC
    check as ONE row, named for the check: its default says what a failure
    does ("Hold the result" / "Report with qualifier") with the wording
    beneath. Keys and storage are unchanged; only the listing merges."""
    by_key = dict((r.get("key"), r) for r in rows)
    out, done = [], set()
    for r in rows:
        key = r.get("key") or u""
        parts = key.split(u".")
        if len(parts) == 3 and parts[0] == u"qualifier" and parts[2] in (u"disposition", u"statement"):
            check = parts[1]
            if check in done:
                continue
            done.add(check)
            disp = by_key.get(u"qualifier.%s.disposition" % check) or {}
            stmt = by_key.get(u"qualifier.%s.statement" % check) or {}
            row = dict(stmt or disp)
            row["label"] = (row.get("label") or u"").split(u" \u2014 ", 1)[-1]
            row["display_seed"] = DISPOSITION_WORDS.get(disp.get("seed"), disp.get("seed") or u"\u2014")
            row["seed_detail"] = stmt.get("seed") or u""
            row["help"] = u""
            out.append(row)
        else:
            out.append(r)
    return out


class PFASLabSettingsView(ViewHelpers, BrowserView):
    """@@pfas-lab-settings — Help › Settings reference: every setting the
    lab owns, its default, who may change it and the page that edits it.
    Documentation: no live values (the editors show those), no status; a
    judging setting with no value is raised on the QC Management landing."""

    template = ViewPageTemplateFile("templates/lab_settings.pt")

    def __call__(self):
        flatten_form(self.request)
        # Declaring on every render rather than at import time: the adapters
        # reach into other stores, and an import-time failure would take down
        # whichever page happened to import first. declare_all() guards itself
        # against running twice.
        try:
            from senaite.pfas import settings_adapters
            settings_adapters.declare_all(self._portal())
        except Exception as exc:                            # noqa: BLE001
            logger.error("settings declarations failed: %s", exc)
        return self.template()

    # ── Context ─────────────────────────────────────────────────────────────

    # ── Filters, all server-side so the page stays LINKABLE ─────────────────
    # "send me the URL of the unset limits" is the thing a lab admin actually
    # wants; a client-side filter cannot be linked or bookmarked.

    def query(self):
        return (self.request.form.get("q") or u"").strip()

    def tier_filter(self):
        val = (self.request.form.get("tier") or u"").strip()
        return val if val in reg.TIERS else u""

    def status_filter(self):
        val = (self.request.form.get("status") or u"").strip()
        return val if val in _STATUS_META else u""

    def _matches(self, row):
        q = self.query().lower()
        if q:
            haystack = u" ".join([
                row.get("key") or u"", row.get("label") or u"",
                row.get("group_label") or u"", row.get("unit") or u"",
                row.get("help") or u"",
            ]).lower()
            if q not in haystack:
                return False
        tier = self.tier_filter()
        if tier and row.get("tier") != tier:
            return False
        status = self.status_filter()
        if status and row.get("source") != status:
            return False
        return True

    # ── Rows ────────────────────────────────────────────────────────────────

    def _rows(self):
        """Every declared setting, described once, with display fields added."""
        portal = self._portal()
        try:
            rows = reg.describe_all(portal)
        except Exception as exc:                            # noqa: BLE001
            logger.error("describe_all failed: %s", exc)
            return []
        rows = [r for r in rows if r.get("group") in CONSOLE_GROUPS]
        for row in rows:
            css, label = _STATUS_META.get(
                row.get("source"), _STATUS_META["unknown"])
            row["status_class"] = css
            row["status_label"] = label
            row["display_value"] = self._display(row)
            row["display_seed"] = self._display(row, field="seed")
            row["owner_href"] = self._owner_href(row)
            # a value and its unit always apart: "7 days", "25.0 °C"
            unit = row.get("unit") or u""
            if unit and row["display_seed"] not in (u"\u2014", u""):
                row["display_seed"] = u"%s %s" % (row["display_seed"], unit)
        return merge_qc_wording(rows)

    def _display(self, row, field="value"):
        """A value a person can read. Long wording is truncated here rather than
        with CSS, so the cell cannot silently hide the fact that it is long."""
        val = row.get(field)
        if val is None:
            return u"—"
        if isinstance(val, bool):
            return u"Yes" if val else u"No"
        if isinstance(val, (list, tuple)):
            return u", ".join([u"{0}".format(v) for v in val]) or u"—"
        text = u"{0}".format(val)
        if len(text) > 90:
            return text[:90] + u"…"
        return text

    def _owner_href(self, row):
        view = row.get("owner_view") or u""
        if not view:
            return u""
        url = u"{0}/@@{1}".format(self.portal_url(), view.lstrip("@"))
        anchor = row.get("anchor") or u""
        if anchor:
            url += u"?tab={0}".format(anchor)
        return url

    def groups(self):
        """[{id, label, rows, total, unset}] in the declared group order.

        `total` is the count BEFORE filtering, so a filtered view still tells the
        admin how much it is hiding — a section reading "(2)" when the lab has 27
        wording settings would be actively misleading.
        """
        rows = self._rows()
        out = []
        for gid in CONSOLE_GROUPS:
            in_group = [r for r in rows if r.get("group") == gid]
            shown = [r for r in in_group if self._matches(r)]
            out.append({
                "id": gid,
                "label": reg.GROUP_LABELS.get(gid, gid),
                "rows": shown,
                "total": len(in_group),
                "shown": len(shown),
                "unset": len([r for r in in_group
                              if r.get("source") == "unset"]),
            })
        return out

    def total_count(self):
        return len(self._rows())

    def help_tabs(self):
        """The Help page's tabs, this one ("Settings reference") among them."""
        from senaite.pfas.browser.help import PFASHelpView
        return PFASHelpView(self.context, self.request).tabs()

    def filtering(self):
        return bool(self.query() or self.tier_filter() or self.status_filter())

    def tier_options(self):
        return [(reg.TIER_LAB, u"Lab values"),
                (reg.TIER_STRUCTURAL, u"Structural")]

