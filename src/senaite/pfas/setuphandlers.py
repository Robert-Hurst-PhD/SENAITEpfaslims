# -*- coding: utf-8 -*-
"""
GenericSetup install handlers for senaite.pfas.

SENAITE 2.6 content structure (differs from 1.x):
  portal/setup/analysiscategories   AnalysisCategories
  portal/setup/sampletypes          SampleTypes
  portal/setup/samplecontainers     SampleContainers
  portal/setup/samplepreservations  SamplePreservations
  portal/setup/storagelocations     StorageLocations
  portal/setup/samplepoints         SamplePoints
  portal/bika_setup/bika_analysisservices  AnalysisServices
  portal/methods                    Methods
"""
import csv
import os
import logging

logger = logging.getLogger("senaite.pfas")

SETUPDATA = os.path.join(os.path.dirname(__file__), "setupdata")


def _read(name):
    path = os.path.join(SETUPDATA, name)
    with open(path) as f:
        return list(csv.DictReader(f))


def _get_or_create(container, portal_type, title, **kw):
    """Idempotent get-or-create using bika.lims.api."""
    from bika.lims import api
    existing = [o for o in container.objectValues()
                if getattr(o, "Title", lambda: None)() == title]
    if existing:
        logger.info("Found existing %s: %s", portal_type, title)
        return existing[0]
    try:
        obj = api.create(container, portal_type, title=title, **kw)
    except Exception as e:
        logger.error("FAILED to create %s '%s': %s", portal_type, title, e)
        raise
    logger.info("Created %s: %s", portal_type, title)
    return obj


def setup_handler(context):
    marker = context.readDataFile("senaite.pfas.install.txt")
    logger.info("DEBUG setup_handler marker=%r profile=%r", marker, getattr(context, '_profile_path', '?'))
    if marker is None:
        return
    logger.info("=== senaite.pfas: loading PFAS setup data ===")

    portal = context.getSite()
    new_setup = portal["setup"]      # SENAITE 2.x Setup object
    bika_setup = portal["bika_setup"]  # legacy BikaSetup (still holds AnalysisServices)

    # ── Analysis categories ─────────────────────────────────────────────
    cat_folder = new_setup["analysiscategories"]
    categories = {}
    for cat in [u"PFAS - PFCA", u"PFAS - PFSA", u"PFAS - FTS", u"PFAS - FOSA",
                u"PFAS - PFECA", u"PFAS - Cl-PFAES", u"PFAS - other",
                u"PFAS - Internal Standards"]:
        categories[cat] = _get_or_create(cat_folder, "AnalysisCategory", cat)

    # ── Methods ─────────────────────────────────────────────────────────
    method_folder = portal["methods"]
    methods = {}
    for row in _read("methods.csv"):
        m = _get_or_create(method_folder, "Method", row["Title"])
        try:
            m.setMethodID(row["MethodID"])
            m.setDescription(row["Description"])
        except Exception:
            pass
        methods[row["MethodID"]] = m

    # ── Native analyte AnalysisServices ─────────────────────────────────
    svc_folder = bika_setup["bika_analysisservices"]
    for row in _read("analysis_services.csv"):
        cat = categories.get(row["Category"], categories[u"PFAS - other"])
        svc = _get_or_create(svc_folder, "AnalysisService", row["Title"],
                             Keyword=row["Keyword"], Category=cat)
        try:
            svc.setCASNumber(row["CAS"] if row["CAS"] != "PLACEHOLDER" else "")
            svc.setPrecision(int(row["PrecisionDigits"]))
        except Exception:
            pass

    # ── Internal standards / surrogates ─────────────────────────────────
    for row in _read("internal_standards.csv"):
        _get_or_create(svc_folder, "AnalysisService", row["Title"],
                       Keyword=row["Keyword"],
                       Category=categories[u"PFAS - Internal Standards"])

    # ── Sample types ────────────────────────────────────────────────────
    st_folder = new_setup["sampletypes"]
    for row in _read("sample_types.csv"):
        st = _get_or_create(st_folder, "SampleType", row["Title"],
                            Prefix=row["Prefix"])
        try:
            st.setRetentionPeriod({"days": int(row["RetentionDays"]),
                                   "hours": 0, "minutes": 0})
            st.setHazardous(row["Hazardous"] == "Y")
        except Exception:
            pass

    # ── Sample containers ───────────────────────────────────────────────
    cont_folder = new_setup["samplecontainers"]
    for row in _read("containers.csv"):
        _get_or_create(cont_folder, "SampleContainer", row["Title"],
                       description=row["Notes"])

    # ── Sample preservations ────────────────────────────────────────────
    pres_folder = new_setup["samplepreservations"]
    for row in _read("preservations.csv"):
        _get_or_create(pres_folder, "SamplePreservation", row["Title"])

    # ── Storage locations (senaite.storage) ─────────────────────────────
    try:
        sl_folder = new_setup["storagelocations"]
        for row in _read("storage_locations.csv"):
            _get_or_create(sl_folder, "StorageLocation", row["Title"],
                           description="{} -- {}".format(row["TargetTemp"], row["Notes"]))
    except (KeyError, AttributeError):
        logger.info("senaite.storage not present; storage locations skipped")

    # ── Method Profiles ──────────────────────────────────────────────────
    # Seed defaults into ZODB and export /data/qc/method_profiles.json.
    # Must run before Reference Definitions so refs can read from the profile.
    try:
        from senaite.pfas.method_profile_store import seed_default_profiles
        seed_default_profiles(portal)
    except Exception as e:
        logger.warning("Method profiles not seeded: %s", e)

    # ── Reference Definitions ────────────────────────────────────────────
    # Build one ReferenceDefinition per QC type from QC rules.
    # Deferred until after AnalysisServices are created above.
    try:
        create_reference_definitions(portal)
    except Exception as e:
        logger.warning("Reference definitions not created: %s", e)

    logger.info("=== senaite.pfas: setup data load complete ===")


def create_reference_definitions(portal):
    """
    Create or update SENAITE ReferenceDefinition objects for all PFAS QC types.
    Called from setup_handler and from @@pfas-setup-references.

    One definition per QC type shortcode with per-analyte min/max/error
    derived from the current QC rules store.
    """
    from senaite.pfas.browser.setuprefs import (
        QC_REF_SPEC, _get_or_create_ref_def, _build_reference_results
    )
    from senaite.pfas.qc.rules import get_rules

    rules = get_rules()

    # Collect AnalysisService (uid, keyword) pairs
    try:
        from bika.lims import api
        catalog = api.get_tool("bika_setup_catalog")
        brains = catalog(portal_type="AnalysisService")
        analyte_uids = []
        for brain in brains:
            obj = brain.getObject()
            kw = getattr(obj, "getKeyword", lambda: "")() or ""
            analyte_uids.append((api.get_uid(obj), kw))
    except Exception as e:
        logger.warning("create_reference_definitions: cannot list services: %s", e)
        return

    if not analyte_uids:
        logger.info("create_reference_definitions: no AnalysisServices yet; skipping")
        return

    try:
        folder = portal.bika_setup.bika_referencedefinitions
    except AttributeError as e:
        logger.warning("create_reference_definitions: %s", e)
        return

    for code, (title, is_blank, _strategy) in sorted(QC_REF_SPEC.items()):
        try:
            obj, is_new = _get_or_create_ref_def(folder, title, is_blank=is_blank)
            records = _build_reference_results(code, rules, analyte_uids)
            obj.setReferenceResults(records)
            obj.setBlank(is_blank)
            try:
                obj.reindexObject()
            except Exception:
                pass
            logger.info("%s ReferenceDefinition: %s",
                        "Created" if is_new else "Updated", title)
        except Exception as e:
            logger.error("create_reference_definitions %s: %s", code, e)


def post_install(context):
    logger.info("senaite.pfas post_install")


def post_uninstall(context):
    logger.info("senaite.pfas post_uninstall")
