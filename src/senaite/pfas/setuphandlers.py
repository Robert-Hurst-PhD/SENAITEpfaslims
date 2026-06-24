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


def _stamp_pfas_role(obj, role):
    """Stamp pfas_role onto an AnalysisService via mutator or field.set()."""
    setter = "setPfas_role"
    try:
        getattr(obj, setter)(role)
    except AttributeError:
        try:
            obj.getField("pfas_role").set(obj, role)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("_stamp_pfas_role: %s = %r failed: %s",
                       getattr(obj, "getKeyword", lambda: "?")(), role, exc)


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
    # Two categories only: target analytes in "PFAS", IS in "PFAS - Internal Standards".
    cat_folder = new_setup["analysiscategories"]
    categories = {}
    for cat in [u"PFAS", u"PFAS - Internal Standards"]:
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
    pfas_cat = categories[u"PFAS"]
    for row in _read("analysis_services.csv"):
        svc = _get_or_create(svc_folder, "AnalysisService", row["Title"],
                             Keyword=row["Keyword"], Category=pfas_cat)
        try:
            svc.setCategory(pfas_cat)   # migrate existing services to collapsed category
            svc.setCASNumber(row["CAS"] if row["CAS"] != "PLACEHOLDER" else "")
            svc.setPrecision(int(row["PrecisionDigits"]))
        except Exception:
            pass
        _stamp_pfas_role(svc, "analyte")

    # ── Internal standards / surrogates ─────────────────────────────────
    is_cat = categories[u"PFAS - Internal Standards"]
    for row in _read("internal_standards.csv"):
        svc = _get_or_create(svc_folder, "AnalysisService", row["Title"],
                             Keyword=row["Keyword"], Category=is_cat)
        try:
            svc.setCategory(is_cat)     # migrate existing IS services
        except Exception:
            pass
        _stamp_pfas_role(svc, row.get("Role", "surrogate"))

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

    # ── EGAD EDD config ───────────────────────────────────────────────────
    try:
        from senaite.pfas.egad_store import seed_defaults as seed_egad_defaults
        seed_egad_defaults(portal)
    except Exception as e:
        logger.warning("EGAD EDD defaults not seeded: %s", e)

    # ── Logbook definitions ───────────────────────────────────────────────
    try:
        from senaite.pfas.logbook_store import seed_defaults as seed_logbook_defaults
        seed_logbook_defaults(portal)
    except Exception as e:
        logger.warning("Logbook defaults not seeded: %s", e)

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
        try:
            catalog = api.get_tool("senaite_catalog_setup")
        except Exception:
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


def setup_reagents_catalog(portal):
    """Register Reagent portal_type in senaite_catalog_setup and create container.

    Must run after the Reagent FTI is installed (i.e. in post_install, not
    setup_handler).  Idempotent.
    """
    try:
        from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    except ImportError:
        logger.warning("setup_reagents_catalog: senaite.core.catalog unavailable; skipping")
        return None

    set_catalogs("Reagent", [SETUP_CATALOG])
    logger.info("Reagent registered in %s", SETUP_CATALOG)

    # Create pfas_reagents Folder at portal root if not yet present.
    # Reagent.xml uses global_allow=True because this SENAITE environment's
    # Plone Folder does not support ISelectableConstrainTypes.
    if "pfas_reagents" not in portal:
        from bika.lims import api as bika_api
        folder = bika_api.create(portal, "Folder",
                                 id="pfas_reagents",
                                 title="PFAS Reagents")
        logger.info("Created pfas_reagents folder at portal root")
    else:
        folder = portal["pfas_reagents"]

    return folder


def migrate_reagents_from_annotations(portal):
    """Migrate reagent records from portal.annotations into Reagent content objects.

    Idempotent: records already present as content objects (same Zope id as
    annotation uid) are skipped.  Returns (migrated, skipped) counts.
    """
    import json
    from datetime import datetime

    from zope.annotation.interfaces import IAnnotations

    REAGENTS_KEY = u"senaite.pfas.reagents"
    ann = IAnnotations(portal)
    store = ann.get(REAGENTS_KEY)

    if not store:
        logger.info("migrate_reagents_from_annotations: annotation store empty; nothing to migrate")
        return 0, 0

    if "pfas_reagents" not in portal:
        logger.warning("migrate_reagents_from_annotations: pfas_reagents folder missing; "
                       "run setup_reagents_catalog() first")
        return 0, 0

    folder = portal["pfas_reagents"]
    migrated = 0
    skipped = 0
    errors = 0

    for uid, raw in store.items():
        if uid in folder:
            skipped += 1
            continue
        try:
            data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
        except (ValueError, TypeError, UnicodeDecodeError):
            logger.warning("migrate_reagents: unreadable record uid=%s; skipping", uid)
            errors += 1
            continue

        try:
            name = data.get("name") or data.get("title") or u"Unnamed Reagent"
            # invokeFactory with explicit id preserves the annotation UUID
            folder.invokeFactory("Reagent", id=uid, title=name)
            obj = folder[uid]

            obj.category = data.get("category") or u""
            obj.supplier = (data.get("supplier") or data.get("manufacturer") or u"")
            obj.cat_number = (data.get("cat_number") or data.get("catalog_number") or u"")
            obj.lot_number = data.get("lot_number") or u""
            obj.storage_location = data.get("storage_location") or u""
            obj.barcode = data.get("barcode") or u""
            obj.scan_count = int(data.get("scan_count") or 0)
            obj.status = data.get("status") or u"active"
            obj.notes = data.get("notes") or u""

            # Parse ISO date strings → datetime.date
            date_mapping = [
                ("received_date", ["received_date"]),
                ("expiry_date", ["expiry_date"]),
                ("manufacturer_expiry", ["manufacturer_expiry"]),
                ("opened_date", ["opened_date"]),
            ]
            for field_name, ann_keys in date_mapping:
                raw_date = None
                for k in ann_keys:
                    raw_date = data.get(k)
                    if raw_date:
                        break
                if raw_date:
                    try:
                        d = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                        setattr(obj, field_name, d)
                    except (ValueError, TypeError):
                        pass

            try:
                obj.reindexObject()
            except Exception:
                pass
            migrated += 1
            logger.info("Migrated reagent %r -> pfas_reagents/%s", name, uid)

        except Exception as exc:
            logger.error("migrate_reagents: failed on uid=%s: %s", uid, exc)
            errors += 1

    logger.info("migrate_reagents_from_annotations: migrated=%d, skipped=%d, errors=%d",
                migrated, skipped, errors)
    return migrated, skipped


def setup_logbook_defs_catalog(portal):
    """Register LogbookDef in senaite_catalog_setup and create container.

    Idempotent.  Must run after the LogbookDef FTI is installed.
    """
    try:
        from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    except ImportError:
        logger.warning("setup_logbook_defs_catalog: senaite.core.catalog unavailable; skipping")
        return None

    set_catalogs("LogbookDef", [SETUP_CATALOG])
    logger.info("LogbookDef registered in %s", SETUP_CATALOG)

    if "pfas_logbook_defs" not in portal:
        from bika.lims import api as bika_api
        folder = bika_api.create(portal, "Folder",
                                 id="pfas_logbook_defs",
                                 title="PFAS Logbook Definitions")
        logger.info("Created pfas_logbook_defs folder at portal root")
    else:
        folder = portal["pfas_logbook_defs"]

    return folder


def migrate_logbook_defs_from_annotations(portal):
    """Migrate logbook defs from annotation list into LogbookDef content objects.

    Idempotent: slugs already present as content objects are skipped.
    Returns (migrated, skipped) counts.
    """
    import json
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.logbook_store import DEFAULT_LOGBOOK_DEFS

    LOGBOOK_DEFS_KEY = u"senaite.pfas.logbook_defs"
    ann = IAnnotations(portal)

    if "pfas_logbook_defs" not in portal:
        logger.warning("migrate_logbook_defs_from_annotations: pfas_logbook_defs folder missing")
        return 0, 0

    folder = portal["pfas_logbook_defs"]

    raw = ann.get(LOGBOOK_DEFS_KEY)
    if raw:
        try:
            defs = json.loads(raw)
        except (ValueError, TypeError):
            defs = [dict(d) for d in DEFAULT_LOGBOOK_DEFS]
    else:
        defs = [dict(d) for d in DEFAULT_LOGBOOK_DEFS]

    migrated = 0
    skipped = 0
    errors = 0

    for i, d in enumerate(defs):
        slug = d.get("slug", "")
        if not slug:
            continue
        if slug in folder:
            skipped += 1
            continue
        try:
            title = d.get("title") or slug
            folder.invokeFactory("LogbookDef", id=slug, title=title)
            obj = folder[slug]
            obj.title = title
            obj.form_num = d.get("form_num") or u""
            obj.builtin = bool(d.get("builtin", False))
            obj.active = bool(d.get("active", True))
            obj.sort_order = i
            obj.table_columns = [c for c in (d.get("table_columns") or []) if c]
            try:
                obj.reindexObject()
            except Exception:
                pass
            migrated += 1
            logger.info("Migrated logbook def %r -> pfas_logbook_defs/%s", title, slug)
        except Exception as exc:
            logger.error("migrate_logbook_defs: failed on slug=%s: %s", slug, exc)
            errors += 1

    logger.info(
        "migrate_logbook_defs_from_annotations: migrated=%d, skipped=%d, errors=%d",
        migrated, skipped, errors,
    )
    return migrated, skipped


def setup_method_profiles_catalog(portal):
    """Register MethodProfile in senaite_catalog_setup and create container.

    Idempotent.  Must run after the MethodProfile FTI is installed.
    """
    try:
        from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    except ImportError:
        logger.warning("setup_method_profiles_catalog: senaite.core.catalog unavailable; skipping")
        return None

    set_catalogs("MethodProfile", [SETUP_CATALOG])
    logger.info("MethodProfile registered in %s", SETUP_CATALOG)

    if "pfas_method_profiles" not in portal:
        from bika.lims import api as bika_api
        folder = bika_api.create(portal, "Folder",
                                 id="pfas_method_profiles",
                                 title="PFAS Method Profiles")
        logger.info("Created pfas_method_profiles folder at portal root")
    else:
        folder = portal["pfas_method_profiles"]

    return folder


def migrate_method_profiles_from_annotations(portal):
    """Migrate method profiles from annotation PersistentMapping to MethodProfile objects.

    Idempotent: method_ids already present as Dexterity objects are skipped.
    Copies the raw JSON string verbatim — preserves _seeded flags and user edits.
    Returns (migrated, skipped) counts.
    """
    import json
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.method_profile_store import DEFAULT_PROFILES, PFAS_METHOD_PROFILES_KEY

    if "pfas_method_profiles" not in portal:
        logger.warning("migrate_method_profiles_from_annotations: pfas_method_profiles folder missing")
        return 0, 0

    folder = portal["pfas_method_profiles"]
    ann = IAnnotations(portal)
    store = ann.get(PFAS_METHOD_PROFILES_KEY)

    migrated = 0
    skipped = 0
    errors = 0

    # Migrate profiles stored in the annotation PersistentMapping (verbatim copy).
    if store is not None:
        for method_id, raw in store.items():
            if method_id in folder:
                skipped += 1
                continue
            try:
                display_name = method_id
                try:
                    display_name = json.loads(raw).get("display_name") or method_id
                except (ValueError, TypeError):
                    pass
                folder.invokeFactory("MethodProfile", id=method_id, title=display_name)
                obj = folder[method_id]
                obj.title = display_name
                obj.profile_json = raw  # verbatim copy — preserves _seeded and user edits
                try:
                    obj.reindexObject()
                except Exception:
                    pass
                migrated += 1
                logger.info("Migrated method profile %r -> pfas_method_profiles/%s",
                            method_id, method_id)
            except Exception as exc:
                logger.error("migrate_method_profiles: failed on method_id=%s: %s",
                             method_id, exc)
                errors += 1

    # Seed any DEFAULT_PROFILES methods not covered above (missing from annotation store).
    for method_id, data in DEFAULT_PROFILES.items():
        if method_id in folder:
            continue
        try:
            display_name = data.get("display_name") or method_id
            seeded_data = dict(data)
            seeded_data["_seeded"] = True
            folder.invokeFactory("MethodProfile", id=method_id, title=display_name)
            obj = folder[method_id]
            obj.title = display_name
            obj.profile_json = json.dumps(seeded_data)
            try:
                obj.reindexObject()
            except Exception:
                pass
            migrated += 1
            logger.info("Seeded default profile %r -> pfas_method_profiles/%s",
                        method_id, method_id)
        except Exception as exc:
            logger.error("migrate_method_profiles: failed seeding method_id=%s: %s",
                         method_id, exc)
            errors += 1

    logger.info(
        "migrate_method_profiles_from_annotations: migrated=%d, skipped=%d, errors=%d",
        migrated, skipped, errors,
    )
    return migrated, skipped


def setup_egad_config_catalog(portal):
    """Register EGADConfig in senaite_catalog_setup and create singleton container.

    Idempotent.  Must run after the EGADConfig FTI is installed.
    """
    try:
        from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    except ImportError:
        logger.warning("setup_egad_config_catalog: senaite.core.catalog unavailable; skipping")
        return None

    set_catalogs("EGADConfig", [SETUP_CATALOG])
    logger.info("EGADConfig registered in %s", SETUP_CATALOG)

    if "pfas_egad_config" not in portal:
        from bika.lims import api as bika_api
        folder = bika_api.create(portal, "Folder",
                                 id="pfas_egad_config",
                                 title="PFAS EGAD Config")
        logger.info("Created pfas_egad_config folder at portal root")
    else:
        folder = portal["pfas_egad_config"]

    return folder


def migrate_egad_config_from_annotations(portal):
    """Migrate EGAD config from annotation PersistentMapping to EGADConfig singleton.

    Idempotent: if pfas_egad_config/egad_config already exists, do nothing.
    Copies each sub-key's raw JSON string verbatim to the corresponding blob
    field — no deserialise/reserialise, preserving any user edits exactly.
    Any sub-key absent from the annotation store is seeded from DEFAULT_*.
    Returns (migrated, skipped) counts (0 or 1 each).
    """
    import json
    from zope.annotation.interfaces import IAnnotations
    from senaite.pfas.egad_store import (
        PFAS_EGAD_KEY,
        DEFAULT_LAB, DEFAULT_METHOD_EGAD, DEFAULT_ANALYTE_CAS,
        DEFAULT_QUALIFIER_MAP, DEFAULT_QC_TYPE_MAP, DEFAULT_LOOKUPS,
    )

    if "pfas_egad_config" not in portal:
        logger.warning("migrate_egad_config_from_annotations: pfas_egad_config folder missing; "
                       "run setup_egad_config_catalog() first")
        return 0, 0

    folder = portal["pfas_egad_config"]

    if "egad_config" in folder:
        logger.info("migrate_egad_config_from_annotations: singleton already present; skipping")
        return 0, 1

    try:
        folder.invokeFactory("EGADConfig", id="egad_config", title="EGAD Configuration")
        obj = folder["egad_config"]
    except Exception as exc:
        logger.error("migrate_egad_config_from_annotations: cannot create EGADConfig: %s", exc)
        return 0, 0

    # Read annotation store (may be absent on fresh install)
    ann = IAnnotations(portal)
    store = ann.get(PFAS_EGAD_KEY)

    _field_map = [
        ("lab_json",           "lab",           DEFAULT_LAB),
        ("method_egad_json",   "method_egad",   DEFAULT_METHOD_EGAD),
        ("analyte_cas_json",   "analyte_cas",   DEFAULT_ANALYTE_CAS),
        ("qualifier_map_json", "qualifier_map", DEFAULT_QUALIFIER_MAP),
        ("qc_type_map_json",   "qc_type_map",   DEFAULT_QC_TYPE_MAP),
        ("lookups_json",       "lookups",       DEFAULT_LOOKUPS),
    ]

    for attr, key, default in _field_map:
        if store is not None and key in store:
            # Verbatim copy — preserves user edits exactly
            setattr(obj, attr, store[key])
        else:
            # Sub-key absent (fresh install or partial store): seed from DEFAULT
            setattr(obj, attr, json.dumps(default))

    try:
        obj.reindexObject()
    except Exception:
        pass

    logger.info("migrate_egad_config_from_annotations: created EGADConfig singleton")
    return 1, 0


def post_install(context):
    logger.info("senaite.pfas post_install")
    portal = context.getSite()

    # ── Import Studio vendor templates ────────────────────────────────────
    try:
        from senaite.pfas.browser.import_studio import seed_vendor_templates
        n = seed_vendor_templates(portal)
        logger.info("Import Studio: seeded %d vendor template(s)", n)
    except Exception as exc:
        logger.error("Failed to seed vendor templates: %s", exc)

    # ── Reagent catalog integration + migration ───────────────────────────
    try:
        setup_reagents_catalog(portal)
        migrated, skipped = migrate_reagents_from_annotations(portal)
        logger.info("Reagent migration: %d migrated, %d already present", migrated, skipped)
    except Exception as exc:
        logger.error("Failed to set up Reagent catalog / migration: %s", exc)

    # ── LogbookDef catalog integration + migration ────────────────────────
    try:
        setup_logbook_defs_catalog(portal)
        migrated, skipped = migrate_logbook_defs_from_annotations(portal)
        logger.info("LogbookDef migration: %d migrated, %d already present", migrated, skipped)
    except Exception as exc:
        logger.error("Failed to set up LogbookDef catalog / migration: %s", exc)

    # ── MethodProfile catalog integration + migration ─────────────────────
    try:
        setup_method_profiles_catalog(portal)
        migrated, skipped = migrate_method_profiles_from_annotations(portal)
        logger.info("MethodProfile migration: %d migrated, %d already present", migrated, skipped)
    except Exception as exc:
        logger.error("Failed to set up MethodProfile catalog / migration: %s", exc)

    # ── EGADConfig catalog integration + migration ────────────────────────
    try:
        setup_egad_config_catalog(portal)
        migrated, skipped = migrate_egad_config_from_annotations(portal)
        logger.info("EGADConfig migration: %d migrated, %d already present", migrated, skipped)
    except Exception as exc:
        logger.error("Failed to set up EGADConfig catalog / migration: %s", exc)

    # ── Prep logbook definitions catalog ──────────────────────────────────
    try:
        setup_prep_logbooks_catalog(portal)
    except Exception as exc:
        logger.error("Failed to set up PrepLogbookDef catalog: %s", exc)

    # ── Seed built-in logbook definitions (250/251/252/253) ───────────────
    try:
        from senaite.pfas.browser.prep_logbooks import seed_builtin_logbook_defs
        seed_builtin_logbook_defs(portal)
        logger.info("Built-in logbook defs seeded (250/251/252/253)")
    except Exception as exc:
        logger.error("Failed to seed built-in logbook defs: %s", exc)

    # ── Prepared standards catalog ────────────────────────────────────────
    try:
        setup_prepared_standards_catalog(portal)
    except Exception as exc:
        logger.error("Failed to set up PreparedStandard catalog: %s", exc)

    # ── CoA filesystem directory ──────────────────────────────────────────
    try:
        _ensure_dir("/data/coa")
        _ensure_dir("/data/coa/certs")
    except Exception as exc:
        logger.error("Failed to create /data/coa directories: %s", exc)


def _ensure_dir(path):
    """Create directory if it does not exist."""
    import os
    if not os.path.isdir(path):
        os.makedirs(path)
        logger.info("Created directory: %s", path)


def setup_prep_logbooks_catalog(portal):
    """Register PrepLogbookDef in setup catalog and create container folder."""
    try:
        from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    except ImportError:
        logger.warning("setup_prep_logbooks_catalog: senaite.core.catalog unavailable; skipping")
        return None

    set_catalogs("PrepLogbookDef", [SETUP_CATALOG])
    logger.info("PrepLogbookDef registered in %s", SETUP_CATALOG)

    if "pfas_prep_logbooks" not in portal:
        from bika.lims import api as bika_api
        bika_api.create(portal, "Folder",
                        id="pfas_prep_logbooks",
                        title="PFAS Preparation Logbooks")
        logger.info("Created pfas_prep_logbooks folder")

    return portal.get("pfas_prep_logbooks")


def setup_prepared_standards_catalog(portal):
    """Register PreparedStandard in setup catalog and create container folder."""
    try:
        from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    except ImportError:
        logger.warning("setup_prepared_standards_catalog: senaite.core.catalog unavailable; skipping")
        return None

    set_catalogs("PreparedStandard", [SETUP_CATALOG])
    logger.info("PreparedStandard registered in %s", SETUP_CATALOG)

    if "pfas_prepared_standards" not in portal:
        from bika.lims import api as bika_api
        bika_api.create(portal, "Folder",
                        id="pfas_prepared_standards",
                        title="PFAS Prepared Standards")
        logger.info("Created pfas_prepared_standards folder")

    return portal.get("pfas_prepared_standards")


def post_uninstall(context):
    logger.info("senaite.pfas post_uninstall")
