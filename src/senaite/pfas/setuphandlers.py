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
        except AttributeError:
            pass
    except Exception as exc:
        logger.warning("_stamp_pfas_role: %s = %r failed: %s",
                       getattr(obj, "getKeyword", lambda: "?")(), role, exc)


def _seed_service(svc, created, role):
    """A seeded service's PFAS identity. The role and the compound library's
    facts (compound_library_store) are written when the install CREATES the
    service, and the role also when it has none: a role or fact the lab set
    in Setup is the lab's, and this runs on every restart."""
    from senaite.pfas import compound_library_store as cls
    if created or not cls._get(svc, "pfas_role"):
        _stamp_pfas_role(svc, role)
    if created:
        row = cls.seed_row(svc.getKeyword())
        if row:
            try:
                cls.stamp_seed(svc, row)
            except Exception as exc:                        # noqa: BLE001
                logger.warning("compound library facts not written on %s: %s",
                               svc.getKeyword(), exc)


def _get_or_create(container, portal_type, title, key=None, **kw):
    """Idempotent get-or-create using bika.lims.api. Returns (obj, created).

    THIS RUNS ON EVERY RESTART, not only on install: the container's buildout
    re-applies senaite.pfas:default through collective.recipe.plonesite each
    time it starts. So a seed value may be written only to an object
    this call has just CREATED; writing it to an existing one reverts whatever
    the lab set there.

    ``key`` is ``(accessor_name, value)`` for a type with a stable identifier
    (Method -> getMethodID, AnalysisService -> getKeyword, SampleType ->
    getPrefix). The key is matched FIRST, so an object the lab renames is still
    found and no copy is seeded next to it. Title is the fallback
    only when no object carries the key, and a Title match whose key is set to
    something ELSE is a different object, never adopted -- what this returns
    has a role stamped on it even when not created. Types with no stable key
    (categories, containers, preservations, storage locations) pass no key and
    stay on Title.
    """
    from bika.lims import api

    def _key_of(o):
        try:
            return getattr(o, key[0])() or ""
        except AttributeError:
            return ""

    def _title_of(o):
        return getattr(o, "Title", lambda: None)()

    objs = container.objectValues()
    if key is not None and key[1]:
        keyed = [o for o in objs if _key_of(o) == key[1]]
        if keyed:
            if len(keyed) > 1:
                logger.warning("%s: %d objects share %s=%r; preferring Title %r",
                               portal_type, len(keyed), key[0], key[1], title)
                titled = [o for o in keyed if _title_of(o) == title]
                if titled:
                    return titled[0], False
            return keyed[0], False
        existing = [o for o in objs if _title_of(o) == title
                    and _key_of(o) in ("", key[1])]
    else:
        existing = [o for o in objs if _title_of(o) == title]
    if existing:
        return existing[0], False
    try:
        obj = api.create(container, portal_type, title=title, **kw)
    except Exception as e:
        logger.error("FAILED to create %s '%s': %s", portal_type, title, e)
        raise
    logger.info("Created %s: %s", portal_type, title)
    return obj, True


def setup_handler(context):
    # installer and seeder writes are attributed to "installer" in history
    from senaite.pfas.config_history import set_actor
    set_actor(u"installer")
    marker = context.readDataFile("senaite.pfas.install.txt")
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
        categories[cat], _ = _get_or_create(cat_folder, "AnalysisCategory", cat)

    # ── Methods ─────────────────────────────────────────────────────────
    method_folder = portal["methods"]
    methods = {}
    from senaite.pfas.method_delete import deleted_ids
    deleted = deleted_ids(portal)      # a deleted method is not made again
    for row in _read("methods.csv"):
        if row["MethodID"] in deleted:
            continue
        m, created = _get_or_create(method_folder, "Method", row["Title"],
                                    key=("getMethodID", row["MethodID"]))
        if created:
            m.setMethodID(row["MethodID"])
            m.setDescription(row["Description"])
        methods[row["MethodID"]] = m

    # ── Native analyte AnalysisServices ─────────────────────────────────
    svc_folder = bika_setup["bika_analysisservices"]
    pfas_cat = categories[u"PFAS"]
    for row in _read("analysis_services.csv"):
        svc, created = _get_or_create(svc_folder, "AnalysisService", row["Title"],
                                      key=("getKeyword", row["Keyword"]),
                                      Keyword=row["Keyword"], Category=pfas_cat)
        if created:
            # once created, the category and precision are the lab's
            svc.setCategory(pfas_cat)
            svc.setPrecision(int(row["PrecisionDigits"]))
        # NOTE: SENAITE 2.6 core AnalysisService has NO CAS field: the CAS is
        # the PFAS tab's pfas_cas (compound_library), seeded with the other
        # library facts when the service is created.
        _seed_service(svc, created, "analyte")

    # ── Internal standards / surrogates ─────────────────────────────────
    is_cat = categories[u"PFAS - Internal Standards"]
    for row in _read("internal_standards.csv"):
        svc, created = _get_or_create(svc_folder, "AnalysisService", row["Title"],
                                      key=("getKeyword", row["Keyword"]),
                                      Keyword=row["Keyword"], Category=is_cat)
        if created:
            svc.setCategory(is_cat)
        _seed_service(svc, created, row.get("Role", "surrogate"))

    # ── Sample types ────────────────────────────────────────────────────
    st_folder = new_setup["sampletypes"]
    for row in _read("sample_types.csv"):
        st, created = _get_or_create(st_folder, "SampleType", row["Title"],
                                     key=("getPrefix", row["Prefix"]),
                                     Prefix=row["Prefix"])
        if created:
            # No retention period is seeded: core's Retention Period is how long
            # the lab keeps a sample, the lab's own policy -- not the holding
            # time, which the method profile owns.
            st.setHazardous(row["Hazardous"] == "Y")

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
                           description="{}: {}".format(row["TargetTemp"], row["Notes"]))
    except (KeyError, AttributeError):
        logger.info("senaite.storage not present; storage locations skipped")

    # ── Method Profiles ──────────────────────────────────────────────────
    # Seed defaults into ZODB and export /data/qc/method_profiles.json.
    # Must run before Reference Definitions so refs can read from the profile.
    # The add-on's own modules are imported outside the handlers: a seed that
    # fails is logged and the install goes on, an import that fails raises.
    from senaite.pfas.method_profile_store import seed_default_profiles
    from senaite.pfas.edd_store import seed_defaults as seed_edd_defaults
    try:
        seed_default_profiles(portal)
    except Exception as e:
        logger.warning("Method profiles not seeded: %s", e)

    # ── EDD export: the default profile ──────────────────────────────────
    try:
        seed_edd_defaults(portal)
    except Exception as e:
        logger.warning("EDD export settings not seeded: %s", e)

    # ── Reagent lots: where each expiry came from, recorded once ─────────
    _migrate_expiry_source(portal)

    # ── Reference Definitions ────────────────────────────────────────────
    # Build one ReferenceDefinition per QC type from QC rules.
    # Deferred until after AnalysisServices are created above.
    try:
        create_reference_definitions(portal)
    except Exception as e:
        logger.warning("Reference definitions not created: %s", e)

    logger.info("=== senaite.pfas: setup data load complete ===")


REFERENCE_METHOD_KEY = "senaite.pfas.reference_definition_method"


def get_reference_method(portal):
    """Which method's limits the global Reference Definitions use, or ""."""
    from zope.annotation.interfaces import IAnnotations
    return IAnnotations(portal).get(REFERENCE_METHOD_KEY) or ""


def set_reference_method(portal, method_id):
    from zope.annotation.interfaces import IAnnotations
    IAnnotations(portal)[REFERENCE_METHOD_KEY] = method_id or ""


def _primary_method_profile(portal):
    """The method profile Reference Definitions are built from.

    SENAITE Reference Definitions are GLOBAL — one per QC code — while PFAS
    acceptance limits are per METHOD, so one method has to supply them. That
    choice is CONFIGURED, never inferred.

    Unset, this returns {} and no ranges are written: the QC rules store
    holds no criteria, and nothing is invented.
    """
    method_id = get_reference_method(portal)
    if not method_id:
        logger.info(
            "No reference-definition method configured; QC reference ranges "
            "are not written. Set one under Configuration -> Setup Reference "
            "Definitions so control charts match the limits the QC engine "
            "enforces.")
        return {}
    from senaite.pfas.method_profile_store import get_profile
    profile = get_profile(portal, method_id) or {}
    if not profile:
        logger.warning("reference-definition method %s has no profile; no "
                       "ranges are written", method_id)
    return profile


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

    # Reference Definitions are GLOBAL in SENAITE — one per QC code — while
    # acceptance limits are per METHOD. They are built from the primary method's
    # profile so the control charts match what the engine enforces for it; a lab
    # running methods with different windows for the same QC code needs
    # per-method definitions, which the object model does not yet carry.
    ref_profile = _primary_method_profile(portal)

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

    if not analyte_uids:
        logger.info("create_reference_definitions: no AnalysisServices yet; skipping")
        return

    try:
        folder = portal.bika_setup.bika_referencedefinitions
    except AttributeError as e:
        logger.warning("create_reference_definitions: %s", e)
        return

    # QC_REF_SPEC rows are 5-tuples: index them, never unpack a fixed count
    for code, spec in sorted(QC_REF_SPEC.items()):
        title, is_blank = spec[0], spec[1]
        try:
            obj, is_new = _get_or_create_ref_def(folder, code, title, is_blank=is_blank)
            if not is_new:
                # Runs on every restart: an existing definition is the lab's,
                # maintained through @@pfas-setup-references.
                continue
            records = _build_reference_results(code, rules, analyte_uids,
                                               profile=ref_profile)
            obj.setReferenceResults(records)
            obj.setBlank(is_blank)
            obj.reindexObject()
            logger.info("%s ReferenceDefinition: %s",
                        "Created" if is_new else "Updated", title)
        except Exception as e:
            logger.error("create_reference_definitions %s: %s", code, e)


# portal_type -> (folder id, folder title): catalogued in the setup catalog
# and kept in its own folder at the portal root. The types use
# global_allow=True because this SENAITE's Plone Folder does not support
# ISelectableConstrainTypes. Runs after the FTIs are installed.
SETUP_TYPES = (
    ("Reagent", "pfas_reagents", "PFAS Reagents"),
    ("PFASProject", "pfas_projects", "PFAS Projects"),
    ("MethodProfile", "pfas_method_profiles", "PFAS Method Profiles"),
    ("PreparedStandard", "pfas_prepared_standards", "PFAS Prepared Standards"),
)


def setup_catalogs(portal):
    """Each SETUP_TYPES type in the setup catalog, with its folder. Idempotent."""
    from bika.lims import api as bika_api
    from senaite.core.catalog import set_catalogs, SETUP_CATALOG
    for portal_type, folder_id, title in SETUP_TYPES:
        set_catalogs(portal_type, [SETUP_CATALOG])
        if folder_id not in portal:
            bika_api.create(portal, "Folder", id=folder_id, title=title)
            logger.info("Created %s folder", folder_id)


def setup_automation_group(portal):
    """Create the group that marks an account as a NON-HUMAN service account.

    Returns True if it was created, False if it already existed. Idempotent.

    Seeded, not documented: `data_review._actor_kind()` decides
    human-vs-automated from `user.getGroups()`, which returns group **IDs**. A
    mistyped id fails silently and classifies every service account as a person,
    so a machine attestation would open the release gate as a human sign-off.

    IT GRANTS NO ROLES, deliberately: the group classifies an account, it does
    not empower one. A service account still needs Analyst or LabManager through
    the normal role model. Do NOT attach permissions to this group.

    Nobody is a member on install: the classification exists before any
    automated actor does.
    """
    # Local imports, matching this module's convention (see
    # setup_catalogs): setuphandlers runs during install, where a
    # module-level import of a tool or a browser module can order badly.
    from Products.CMFCore.utils import getToolByName
    from senaite.pfas.browser.data_review import AUTOMATION_GROUP
    gtool = getToolByName(portal, "portal_groups")
    if AUTOMATION_GROUP in gtool.getGroupIds():
        return False
    gtool.addGroup(
        AUTOMATION_GROUP,
        title="PFAS Automation (service accounts)",
        description=(
            "Non-human service accounts. Membership marks an attestation as "
            "AUTOMATED: such an account may record a proposed disposition on the "
            "Data Review checklist but cannot sign an item off, because ISO "
            "17025 requires a competent, authorised person to authorise results. "
            "Grants no roles of its own."),
        roles=[],
    )
    return True


def setup_worker_role(portal):
    """The pipeline worker's role, its permission and its group
    (browser/perms.WORKER_*): the role defined at the portal, the worker
    permission granted there to Manager, Site Administrator and the role, and
    the group holding the role and the core roles the worker's pushes need.
    Idempotent; makes no account (tools/worker_account.py does).
    Returns the changes made, as words."""
    from Products.CMFCore.utils import getToolByName
    from senaite.pfas.browser import perms
    done = []
    if perms.WORKER_ROLE not in portal.validRoles():
        portal._addRole(perms.WORKER_ROLE)
        done.append("role")
    held = set(r["name"] for r in portal.rolesOfPermission(perms.WORKER_PERMISSION) if r["selected"])
    if not set(perms.WORKER_PERMISSION_ROLES) <= held:
        portal.manage_permission(perms.WORKER_PERMISSION,
                                 roles=sorted(held | set(perms.WORKER_PERMISSION_ROLES)), acquire=0)
        done.append("permission")
    gtool = getToolByName(portal, "portal_groups")
    if perms.WORKER_GROUP not in gtool.getGroupIds():
        gtool.addGroup(perms.WORKER_GROUP, roles=list(perms.WORKER_GROUP_ROLES),
                       title="PFAS Worker (the pipeline's account)",
                       description="The pipeline worker's account only: its role and the core "
                                   "roles its pushes need. Never a person.")
        done.append("group")
    else:
        group = gtool.getGroupById(perms.WORKER_GROUP)
        roles = set(group.getRoles()) - set(("Authenticated",))
        if set(perms.WORKER_GROUP_ROLES) - roles:
            gtool.editGroup(perms.WORKER_GROUP, roles=sorted(roles | set(perms.WORKER_GROUP_ROLES)))
            done.append("group roles")
    return done


# The lab never adds or removes analytes on a sample: the panel comes from
# the method x matrix. Core's "Manage Analyses" tab
# shows for the site manager only.
MANAGE_ANALYSES_CONDITION = "python:'Manager' in member.getRolesInContext(object)"


def hide_manage_analyses(portal):
    """The sample's Manage Analyses tab for the site manager only. True when
    the type's action changed. Idempotent."""
    from Products.CMFCore.Expression import Expression
    fti = portal.portal_types.getTypeInfo("AnalysisRequest")
    for action in fti.listActions():
        if action.getId() == "analyses":
            if action.condition and action.condition.text == MANAGE_ANALYSES_CONDITION:
                return False
            action.condition = Expression(MANAGE_ANALYSES_CONDITION)
            fti._p_changed = True
            return True
    return False


def worksheet_opens_on_review(portal):
    """A worksheet opens on its Data Review (@@pfas-ws-open); core's results
    grid is its "Results entry" tab. True when the
    type changed. Idempotent."""
    fti = portal.portal_types.getTypeInfo("Worksheet")
    changed = False
    aliases = dict(fti.getMethodAliases())
    if aliases.get("(Default)") != "pfas-ws-open":
        aliases["(Default)"] = "pfas-ws-open"
        fti.setMethodAliases(aliases)
        changed = True
    for action in fti.listActions():
        if action.getId() == "manage_results" and action.title != "Results entry":
            action.title = "Results entry"
            changed = True
    if changed:
        fti._p_changed = True
    return changed


def setup_lab_identity(portal):
    """Move the identity into the Laboratory and limit its edit right. Each
    step has its own try: a failed move never leaves Lab Clerk able to edit."""
    from senaite.pfas import lab_identity
    try:
        filled = lab_identity.migrate_print_identity(portal)
        if filled:
            logger.info("Lab identity moved into the Laboratory: %s",
                        ", ".join(filled))
    except Exception as exc:
        logger.error("Failed to move the lab identity into the Laboratory: "
                     "%s", exc)
    try:
        if lab_identity.restrict_laboratory_edit(portal):
            logger.info("Laboratory edit limited to Lab Manager and Site "
                        "Administrator")
    except Exception as exc:
        logger.error("Failed to limit the Laboratory edit: %s", exc)


# the extraction log's design is the batch record's: same tables and fields,
# and more; an install that issued one keeps printing it
OLD_DESIGN_ID, NEW_DESIGN_ID, NEW_DESIGN_KIND = "extraction-log", "batch-record", "batch_record"


def carry_over(store):
    """The Document Templates store with the extraction log's design moved
    to the batch record's id and kind, its revisions, draft and the rest
    kept. A store that already holds a batch record design, or no
    extraction log design, comes back as it was. The input is not changed."""
    import copy
    out = copy.deepcopy(store or {})
    if OLD_DESIGN_ID not in out or NEW_DESIGN_ID in out:
        return out
    entry = out.pop(OLD_DESIGN_ID)
    entry["id"], entry["kind"] = NEW_DESIGN_ID, NEW_DESIGN_KIND
    out[NEW_DESIGN_ID] = entry
    return out


def carry_over_extraction_design(portal):
    """Install step: the issued extraction log design prints as the batch record,
    and a saved report-tier catalogue names the batch record where it named
    the extraction log. Idempotent: an install with nothing to carry writes
    nothing."""
    from senaite.pfas import document_templates as dt
    from senaite.pfas import report_tiers
    store = dt.load(portal)
    out = carry_over(store)
    if out != store:
        dt.save(portal, out)
        logger.info("the extraction log design is now the batch record design")
    saved = report_tiers.saved_catalogue(portal)
    if saved is not None:
        catalogue, changed = report_tiers.carry_over_parts(saved)
        if changed:
            problems = report_tiers.save_catalogue(portal, catalogue)
            if problems:
                logger.error("report tiers not carried over: %s", "; ".join(problems))
            else:
                logger.info("report tiers name the batch record where they named the extraction log")


def _migrate_expiry_source(portal):
    """Each reagent lot saved before its expiry's source was kept is given
    one (reagents.migrate_expiry_source); a lot that has one is left, so
    running it again changes nothing."""
    try:
        from senaite.pfas.browser.reagents import migrate_expiry_source
        n = migrate_expiry_source(portal)
        if n:
            logger.info("Reagent lots given their expiry's source: %d", n)
    except Exception as exc:                                # noqa: BLE001
        logger.error("Reagent expiry sources not recorded: %s", exc)


def post_install(context):
    # installer and seeder writes are attributed to "installer" in history
    from senaite.pfas.config_history import set_actor
    set_actor(u"installer")
    logger.info("senaite.pfas post_install")
    # Defensive portal resolution: in some invocation contexts (e.g. a
    # bin/instance interpreter bootstrap) `context` is a RequestContainer with
    # no getSite(); fall back to locating the site.
    if hasattr(context, "getSite"):
        portal = context.getSite()
    else:
        try:
            from bika.lims import api
            portal = api.get_portal()
        except Exception:
            portals = [o for o in context.objectValues("Plone Site")] \
                if hasattr(context, "objectValues") else []
            portal = portals[0] if portals else None
    if portal is None:
        logger.error("post_install: cannot resolve portal — aborting")
        return

    # The add-on's own modules are imported outside the handlers: a step that
    # fails is logged and the install goes on, an import that fails raises.
    from senaite.pfas.method_profile_store import (
        refresh_analyte_sets, seed_default_profiles)

    # ── Automation service-account group ──────────────────────────────────
    try:
        created = setup_automation_group(portal)
        logger.info("Automation group: %s",
                    "created" if created else "already present")
    except Exception as exc:
        logger.error("Failed to set up the automation group: %s", exc)

    # ── The pipeline worker's role, permission and group ───────────────────
    try:
        logger.info("Worker role: %s", ", ".join(setup_worker_role(portal)) or "already present")
    except Exception as exc:
        logger.error("Failed to set up the worker role: %s", exc)

    # ── Lab identity moves into the Laboratory; Lab Clerk loses its edit ──
    setup_lab_identity(portal)

    # ── The laboratory time zone moves into Plone's own record ────────────
    try:
        from senaite.pfas import lab_time
        if lab_time.migrate_zone(portal):
            logger.info("Laboratory time zone moved into Plone's record")
    except Exception as exc:
        logger.error("Failed to move the laboratory time zone: %s", exc)

    # ── The add-on's setup-catalog types and their folders; the seeds ─────
    try:
        setup_catalogs(portal)
        seed_default_profiles(portal)
    except Exception as exc:
        logger.error("Failed to set up the catalogs / seed the profiles: %s", exc)

    # ── The analyte panels follow the services' Method links ─────────
    # A profile seen for the first time links the services of its stored
    # list (the shipped seeds); from then on the links own the panel.
    try:
        changed = refresh_analyte_sets(portal)
        if changed:
            logger.info("analyte panels refreshed from the services' links: %s",
                        ", ".join(sorted(changed)))
    except Exception as exc:
        logger.error("Failed to refresh the analyte panels: %s", exc)

    # ── Each method names its curve fit: linear where none is set ────────
    try:
        from senaite.pfas.migrations import calibration_fit_default
        named = calibration_fit_default.run(portal)
        if named:
            logger.info("Curve fit named on: %s", ", ".join(named))
    except Exception as exc:
        logger.error("Curve fit not named: %s", exc)

    # ── Reagent lots: where each expiry came from, recorded once ─────────
    _migrate_expiry_source(portal)

    # ── Configuration History moves into the results database ────────────
    move_config_history(portal)

    # ── The extraction log's design carries over to the batch record ─────
    try:
        carry_over_extraction_design(portal)
    except Exception as exc:
        logger.error("Extraction log design not carried over: %s", exc)

    # ── The sample's Manage Analyses tab: the site manager only ──────────
    try:
        hide_manage_analyses(portal)
    except Exception as exc:
        logger.error("Manage Analyses tab not limited: %s", exc)
    try:
        worksheet_opens_on_review(portal)
    except Exception as exc:
        logger.error("Worksheet not opened on Data Review: %s", exc)

    # ── CoA filesystem directory ──────────────────────────────────────────
    try:
        _ensure_dir("/data/coa")
        _ensure_dir("/data/coa/certs")
    except Exception as exc:
        logger.error("Failed to create /data/coa directories: %s", exc)


def move_config_history(portal):
    """Copy the history entries kept on the portal into the results
    database and verify the copy (config_history.move_from_annotation). The
    portal's entries are kept; a copy that does not verify is logged and
    tried again at the next install."""
    try:
        from senaite.pfas import config_history
        r = config_history.move_from_annotation(portal)
    except Exception as exc:                                # noqa: BLE001
        logger.error("Configuration History not moved: %s", exc)
        return None
    if r["ok"]:
        logger.info("Configuration History in the results database: %d entries, sha256 %s; "
                    "%d copied now", r["count_table"], r["sum_table"], r["copied"])
    else:
        logger.error("Configuration History copy does not verify: %d of %d entries, sha256 %s "
                     "against %s; missing %s, different %s. The entries stay on the portal.",
                     r["count_table"], r["count_source"], r["sum_table"], r["sum_source"],
                     r["missing"][:5], r["different"][:5])
    return r


def _ensure_dir(path):
    """Create directory if it does not exist."""
    import os
    if not os.path.isdir(path):
        os.makedirs(path)
        logger.info("Created directory: %s", path)


def post_uninstall(context):
    logger.info("senaite.pfas post_uninstall")
