# -*- coding: utf-8 -*-
"""
Override of @@lims-setup to group SENAITE setup tiles by PFAS lab workflow,
with PFAS tools integrated into the relevant core sections.

Registered in browser/overrides.zcml on ISenaitePFASLayer (takes precedence
over senaite.core's own registration on the same layer).

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

from Products.CMFCore.utils import getToolByName
from Products.Five.browser.pagetemplatefile import ViewPageTemplateFile
from senaite.core.browser.controlpanel.setupview import SetupView


class VirtualTile(object):
    """Minimal setup-item stand-in for PFAS browser views.

    Passed directly through the tile loop alongside real ZODB setup items.
    get_icon_for / get_count / get_description in PFASSetupView handle this
    type without traversing ZODB.
    """

    def __init__(self, tile_id, title, url, description="", icon=""):
        self._id = tile_id
        self._title = title
        self._url = url
        self._description = description
        self._icon = icon          # FontAwesome class, e.g. "fa-flask"

    def getId(self):
        return self._id

    def Title(self):
        return self._title

    def absolute_url(self):
        return self._url

    def Description(self):
        return self._description


class _PFASRef(object):
    """Sentinel used in SETUP_GROUPS to reference a PFAS tool by ID."""

    def __init__(self, tool_id):
        self.tool_id = tool_id


def _p(tool_id):
    """Shorthand: embed a PFAS tool tile reference inside a SETUP_GROUPS list."""
    return _PFASRef(tool_id)


# ── PFAS tool definitions ────────────────────────────────────────────────────
# Each entry: (id, title, view_name, description, fa_icon_class)
# These are VirtualTile templates; the base URL is added at request time.

_PFAS_TOOL_DEFS = [
    ("pfas-sample-status",   "Batch Status",
     "@@pfas-sample-status",
     "Five-stage progress for every active worksheet",
     "fa-tasks"),

    ("pfas-control-chart",   "Control Charts",
     "@@pfas-control-chart",
     "Levey-Jennings + Westgard multi-rule charts",
     "fa-chart-line"),

    ("pfas-calibrations",    "Calibrations",
     "@@pfas-calibrations",
     "Calibration curve verification and sign-off",
     "fa-sliders-h"),

    ("pfas-method-profiles", "Method Profiles",
     "@@pfas-method-profiles",
     "Per-method QC acceptance criteria",
     "fa-cogs"),

    ("pfas-qc-rules",        "QC Rules",
     "@@pfas-qc-rules",
     "Toggle and configure QC rule library",
     "fa-toggle-on"),

    ("pfas-setup-refs",      "Setup Ref Defs",
     "@@pfas-setup-references",
     "Sync PFAS QC criteria to SENAITE Reference Definitions",
     "fa-sync-alt"),

    ("pfas-method-wizard",   "New Method Wizard",
     "@@pfas-method-wizard",
     "Step-by-step guided wizard for a new analytical method",
     "fa-magic"),

    ("pfas-import-studio",   "Import Studio",
     "@@pfas-import-studio",
     "Guided instrument column-mapping and profile editor",
     "fa-file-import"),

    ("pfas-reagents",        "Reagent Inventory",
     "@@pfas-reagents",
     "ISO 17025 lot/expiry tracking with barcode scan and OCR",
     "fa-flask"),

    ("pfas-track",           "Sample Tracker",
     "@@pfas-track",
     "Public client-facing sample progress lookup by tracking number",
     "fa-map-marker-alt"),

    ("pfas-extraction-guide", "Extraction Guide",
     "@@pfas-extraction-guide",
     "Step-by-step tablet workflow guiding analysts through each extraction stage",
     "fa-microscope"),

    ("pfas-logbooks",        "Logbooks",
     "@@pfas-logbook-admin",
     "Manage logbook definitions — rename, reorder, create custom logbooks",
     "fa-book"),

    ("pfas-egad-config",     "EGAD EDD Config",
     "@@pfas-egad-config",
     "Maine DEP EGAD EDD v6.0 submission settings: lab, methods, analyte CAS, qualifiers",
     "fa-file-export"),

    ("pfas-egad-batches",    "Batch EDDs",
     "@@pfas-egad-batches",
     "Download EGAD EDD files per batch; set per-sample SAMPLE_TYPE overrides",
     "fa-download"),
]


# ── Core tile descriptions ───────────────────────────────────────────────────
# Keyed by the setup item's getId() value.  Used by get_description().

_CORE_DESCRIPTIONS = {
    # 1. Storage & Inventory
    "storagelocations":    "Physical locations (freezers, fridges, rooms) where samples and extracts are stored",
    "samplecontainers":    "Container types (bottles, vials, bags) used to receive and store samples",
    "containertypes":      "Categories of containers (glass, HDPE, polypropylene) independent of specific container records",
    "sampleconditions":    "Acceptable conditions at sample receipt — e.g. frozen, ambient, chilled",
    "samplepreservations": "Preservation methods applied to samples post-collection — e.g. HCl, ascorbic acid",
    "labproducts":         "Consumables and reagents tracked for inventory and lot control",
    "suppliers":           "Vendors supplying lab products, reference standards, and consumables",
    "manufacturers":       "Equipment and instrument manufacturers referenced in instrument records",
    # 2. Instrument Setup
    "instrumentlocations":       "Physical lab locations where instruments are installed",
    "instrumenttypes":           "Categories of instruments (LC-MS/MS, GC-MS) for instrument records",
    "bika_instruments":          "Instrument records with calibration history, certification, and import profiles",
    "bika_referencedefinitions": "QC material specifications defining expected concentration ranges per analyte",
    # 3. Method & Analyte Setup
    "departments":           "Organisational units (Organics, Metals) that route analyses and report sections",
    "analysiscategories":    "Groups of analysis services (PFAS, Internal Standards) for reporting and filtering",
    "bika_analysisservices": "Individual analyte tests with units, precision, method links, and QC criteria",
    "bika_calculations":     "Custom formulas applied to raw results — e.g. dilution-corrected concentrations",
    "bika_methods":          "Analytical methods referenced by analysis services and instruments",
    "sampletypes":           "Matrix types (drinking water, food, serum) with retention periods and hazard flags",
    "samplematrices":        "High-level matrix classifications (water, food, soil) used for QC rule targeting",
    "bika_analysisspecs":    "Per-analyte acceptable ranges (min/max/warn) applied to samples and QC checks",
    "dynamicanalysisspecs":  "Specification sets where limits are computed from expressions rather than fixed values",
    "analysisprofiles":      "Pre-configured bundles of analysis services applied at sample receipt",
    "worksheettemplates":    "Layouts defining which analyses, QC samples, and columns appear on a worksheet",
    # General
    "bika_setup":               "Root configuration folder — contains all SENAITE setup objects",
    "attachmenttypes":          "File attachment categories for samples and analyses (CoA, chromatogram, SOP)",
    "auditlog":                 "Immutable record of all state changes and edits across the LIMS",
    "batchlabels":              "Text labels applied to sample batches for filtering and grouping",
    "interpretationtemplates":  "Narrative templates appended as interpretive commentary on published reports",
    "bika_labcontacts":         "Internal staff contacts linked to analyses, worksheets, and sign-off actions",
    "labels":                   "Configurable templates for barcodes and stickers printed at receipt or dispatch",
    "laboratory":               "Lab name, address, accreditation body, and branding used across all reports",
    "samplepoints":             "Named collection sites or sampling locations referenced on sample records",
    "sampletemplates":          "Pre-filled sample submission forms to speed up common order types",
    "samplingdeviations":       "Documented departures from the standard sampling protocol recorded per sample",
    "subgroups":                "Sub-groupings within analysis services for fine-grained report organisation",
}


# ── Group definitions ────────────────────────────────────────────────────────
# Each item_ids list may contain:
#   str       — getId() of a real SENAITE setup item
#   _PFASRef  — reference to a PFAS virtual tile (use _p("tool-id"))
#
# Order within each list = left-to-right, top-to-bottom tile display order.
# PFAS tools appear at the END of the relevant core section.

SETUP_GROUPS = [
    {
        "id":    "storage",
        "title": "1. Storage & Inventory",
        "item_ids": [
            "storagelocations",
            "samplecontainers",
            "containertypes",
            "sampleconditions",
            "samplepreservations",
            "labproducts",
            "suppliers",
            "manufacturers",
            _p("pfas-reagents"),        # Reagent Inventory
        ],
    },
    {
        "id":    "instruments",
        "title": "2. Instrument Setup",
        "item_ids": [
            "instrumentlocations",
            "instrumenttypes",
            "bika_instruments",
            "bika_referencedefinitions",
            _p("pfas-import-studio"),   # Import Studio
            _p("pfas-calibrations"),    # Calibrations
        ],
    },
    {
        "id":    "methods",
        "title": "3. Method & Analyte Setup",
        "item_ids": [
            "departments",
            "analysiscategories",
            "bika_analysisservices",
            "bika_calculations",
            "bika_methods",
            "sampletypes",
            "samplematrices",
            "bika_analysisspecs",
            "dynamicanalysisspecs",
            "analysisprofiles",
            "worksheettemplates",
            _p("pfas-method-profiles"), # Method Profiles
            _p("pfas-qc-rules"),        # QC Rules
            _p("pfas-setup-refs"),      # Setup Ref Defs
            _p("pfas-method-wizard"),   # New Method Wizard
        ],
    },
    {
        "id":    "workflow",
        "title": "4. Workflow & QC",
        "item_ids": [
            _p("pfas-sample-status"),       # Batch Status
            _p("pfas-control-chart"),       # Control Charts
            _p("pfas-track"),               # Sample Tracker
            _p("pfas-extraction-guide"),    # Extraction Guide
        ],
    },
    {
        "id":    "regulatory",
        "title": "5. Regulatory Reporting",
        "item_ids": [
            _p("pfas-egad-config"),         # Maine EGAD EDD Config
            _p("pfas-egad-batches"),        # Batch EDD Dashboard
            _p("pfas-logbooks"),            # Regulatory Logbooks
        ],
    },
]

# Flat set of core item IDs that belong to named groups (used for catch-all).
_GROUPED_IDS = set()
for _g in SETUP_GROUPS:
    for _item in _g["item_ids"]:
        if not isinstance(_item, _PFASRef):
            _GROUPED_IDS.add(_item)


class PFASSetupView(SetupView):
    """@@lims-setup override: groups setup tiles in PFAS lab workflow order,
    with PFAS tools integrated into the relevant core sections.

    UPGRADE NOTE: this view overrides senaite.core's SetupView.  On a
    senaite.core upgrade, re-check SetupView for API changes to
    setupitems(), get_icon_for(), and get_count().
    """

    template = ViewPageTemplateFile("templates/lims_setup.pt")

    def portal_url(self):
        return getToolByName(self.context, 'portal_url')()

    # -- Icon ----------------------------------------------------------------

    def get_icon_for(self, item, **kw):
        """Return icon HTML for a tile.

        VirtualTile → <i class="fas fa-..."> FontAwesome markup.
        Core item   → delegate to senaite.core's icon resolution.
        """
        if isinstance(item, VirtualTile):
            if item._icon:
                return '<i class="fas {0}" aria-hidden="true"></i>'.format(
                    item._icon)
            return ''
        try:
            return super(PFASSetupView, self).get_icon_for(item, **kw)
        except Exception:
            return ''

    # -- Description ---------------------------------------------------------

    def get_description(self, item):
        """Return a one-line description for a tile."""
        if isinstance(item, VirtualTile):
            return item.Description()
        return _CORE_DESCRIPTIONS.get(item.getId(), '')

    # -- Count ---------------------------------------------------------------

    def get_count(self, item):
        if isinstance(item, VirtualTile):
            return 0
        try:
            return super(PFASSetupView, self).get_count(item)
        except Exception:
            return 0

    # -- Data ----------------------------------------------------------------

    def current_section(self):
        """Return the ?section= query parameter, or '' for the full view."""
        return self.request.get('section', '')

    def grouped_setup_items(self):
        """Return groups of setup items in workflow dependency order.

        When ?section=<id> is present, only that group is returned.
        Items not belonging to any named group go into the General catch-all
        (only shown in the full, unfiltered view).
        """
        all_items = self.setupitems()
        by_id = {item.getId(): item for item in all_items}

        # Build PFAS virtual tiles keyed by tool ID
        base = self.portal_url()
        pfas_by_id = {}
        for tid, title, view, desc, icon in _PFAS_TOOL_DEFS:
            url = '{0}/{1}'.format(base, view)
            pfas_by_id[tid] = VirtualTile(tid, title, url, desc, icon)

        section = self.request.get('section', '')

        groups = []
        for gdef in SETUP_GROUPS:
            if section and gdef['id'] != section:
                continue
            tiles = []
            for item_ref in gdef["item_ids"]:
                if isinstance(item_ref, _PFASRef):
                    tile = pfas_by_id.get(item_ref.tool_id)
                    if tile:
                        tiles.append(tile)
                elif item_ref in by_id:
                    tiles.append(by_id[item_ref])
            if tiles:
                groups.append({
                    "id":    gdef["id"],
                    "title": gdef["title"],
                    "tiles": tiles,
                })

        # General catch-all only shown in the full unfiltered view.
        if not section:
            remainder = [
                item for item in all_items
                if item.getId() not in _GROUPED_IDS
            ]
            remainder.insert(0, self.setup)
            groups.append({
                "id":    "general",
                "title": "General",
                "tiles": remainder,
            })

        return groups
