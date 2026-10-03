# CLAUDE.md — senaite.pfas

> Claude Code reads this file at the start of every session. It is the single
> source of truth for how this project is built. Follow it over your own
> defaults. If a request conflicts with it, say so and ask.
>
> Place this file at the PROJECT ROOT (the folder you launch `claude` from).
> Verify it loaded with `/memory`.

---

## 0. THE ONE-LINE MODEL

**The relational data model is the truth. Roles are who you are. Workspaces are
role-scoped views onto the truth. The panel layout is how every view is drawn.**

Everything in this project is one of those four things or it is a defect.
Read in order: data model (§3) → roles (§4) → workspaces (§5) → layout (§6).

---

## 1. GOLDEN RULES (these override your defaults)

1. **Configurable, not hardcoded. UI-driven, not code-driven.** If a person in
   the lab might ever want to change a value (a QC limit, a unit, a mapping,
   a CAS code), it lives in the UI and is editable by the right role — never
   in a Python constant. Finding a hardcoded lab value = a defect to migrate.

2. **Build ON the existing architecture; never replace working code wholesale.**
   Extend via the add-on. Reuse SENAITE core; don't reinvent it.

3. **Single source of truth.** Every fact (analyte identity, IS link, method
   criterion, CAS code, unit) is defined ONCE on its owning object and
   REFERENCED everywhere else. Duplicated data = a defect.

4. **Ask, don't guess.** You may read/edit files freely without asking. You may
   NOT guess on design decisions. When you hit one: stop, state your proposed
   assumption concretely, ask me to add/edit/delete, restate the agreed
   decision in one line, then execute. One decision at a time, at the moment
   you hit it — never batch guesses into code.

5. **Python 2.7 for all in-Plone add-on code.** No f-strings, no pathlib, no
   annotation syntax. Use `.format()`, `os.path`, `six`. The out-of-process
   worker may be Python 3 (it talks to SENAITE only over JSON/REST).

6. **Every output traces its parentage — in both directions.**

   OUTPUT (result → model): A result must name its analyte → method × matrix
   → batch/worksheet → samples/QC → surrogate/IS → tier → factors/qualifiers.

   INPUT (result → reagents): A result must also trace its inputs: extraction
   result → which prepared standard lots were used (Calibration Curve Prep Log,
   FM-ENV-002, lot_ref fields; Extraction Log, FM-ENV-003)
   → which reagent lots those standards were made from (PreparedStandard parent
   annotation at `senaite.pfas.prepstd.parent_reagents`) → the CRM/reference
   standard CoA (reagent inventory). Three levels: Reagent lot → Prepared
   Standard lot → Analysis result. Breaking any link = traceability failure =
   the result is not defensible under ISO 17025 §6.6.

   If a value can't name its parents in either direction, the model is wrong.

7. **Define UI once, inherit everywhere.** No page is styled independently.
   One shared layout + one shared tile/section style, inheriting SENAITE core
   theme tokens. This is the law that prevents the drift we have fought.

---

## 2. WHAT THIS SYSTEM IS

A PFAS laboratory LIMS built as a Plone add-on (`senaite.pfas`) on SENAITE
2.6.0 (Plone/Zope/Python-2.7, ZODB via ZEO, Docker), plus a loosely-coupled
out-of-process pipeline worker. Three methods, each with different per-analyte
and per-matrix QC: FDA C-010.04 (PFAS in food and feed, "FDA 32-PFAS"; the
lab is a co-author and the source for its values — do not edit the FDA
method's configuration on the basis of the public C-010.03), EPA 537.1 v2.0
(drinking water), EPA 1633A (aqueous, solid, biosolids, tissue).

Stack (each layer depends on the one below):
```
senaite.pfas (this add-on) + pipeline worker (Py3, via JSON)
SENAITE (the LIMS: core, lims, app.listing)
Plone (CMS framework: Dexterity content types, GenericSetup, permissions)
Zope (application server — runs the code)
ZODB/ZEO (object database — Data.fs in the senaite-data volume = BACK IT UP)
Python 2.7  /  Docker / Linux
```
Read `README.md` and `docs/REFERENCES.md` before doing anything.
`docs/REFERENCES.md` is where every regulatory value must trace to: the
published methods (EPA 537.1 v2.0 EPA/600/R-20/006, EPA 1633A
EPA 820-R-24-007), FDA C-010.04 through the lab (co-author), ISO/IEC
17025:2017 and the state EDD documents. The lab's
spreadsheets, the instrument exports supplied for testing and the demo/seeded
data are test material, never a source (§8).

For "what is wired to what," read `WIRING.md` first — generated
(`python3 tools/wiring_map.py > WIRING.md`), never hand-patched, covering
ZODB annotation keys, the add-on/worker file boundary, browser views, workflow
subscribers, and content types. `docs/history/` holds dated audits, reviews
and test reports (RESOURCE_MAP, SYSTEM_AUDIT, E2E reports): rationale and
history, not current reference.

---

## 3. THE RELATIONAL DATA MODEL (the truth)

A LIMS is a relational database with a UI on top. ZODB is an OBJECT store, so
relationships are object references, and referential integrity is YOUR code's
job (no SQL foreign keys enforce it). Every feature is a VIEW onto this:

> Every feature must be a view onto the hierarchy below — never a standalone
> island. If you are about to store a value or mapping that duplicates something
> another object already owns, STOP and reference the owning object instead.

```
LABORATORY
  └─ METHOD                       (FDA 32-PFAS / EPA 537.1 / EPA 1633A)
       ├─ supports MATRICES       (eggs, meat, seafood, milk, feed, DW, soil,
       │                           tissue, ...)
       ├─ owns a MASTER ANALYTE SET (natives + surrogates + internal standards,
       │                           chosen from the analyte library)
       │
       ├─ METHOD × MATRIX ANALYTE INCLUSION MATRIX   <-- THE KEY RELATION
       │     analytes (rows) x the method's matrices (cols), checkbox each
       │     intersection. An analyte in the method is NOT auto-reportable in
       │     every matrix (the lab decides per intersection, e.g. an analyte
       │     the method does not validate in one food matrix stays unchecked
       │     there). The reportable panel = checked intersections for that
       │     Method x Matrix.
       │
       ├─ SURROGATE MAP   native -> quantifying IS (many natives -> one IS).
       │                  QUANTIFICATION link. Drag-and-drop, never JSON.
       ├─ LABELLED STANDARDS  every isotopically labelled standard the method
       │                  uses, its ROLE in this method (extracted surrogate/EIS
       │                  or injection NIS) and the standard it is LINKED to
       │                  (MS Quan style; any used standard -> any other).
       │                  One grid, per method (DECISIONS 2026-09-30).
       ├─ RECOVERY TIERS  per analyte; for FDA the tier is MATRIX-DEPENDENT
       │                  (key analytes in key matrices, others, and analytes
       │                  with no labelled standard of their own); FDA numbers
       │                  are the lab's, per C-010.04.
       ├─ EIS RECOVERY    EPA 1633A ONLY (hidden for FDA/537.1). RECOVERY-QC
       │                  limits per analyte/matrix. DISTINCT from surrogate map.
       ├─ SALT FACTOR     per analyte x method (decimal < 1, from CoA).
       ├─ MATRIX ADJUST   ONE factor per method (sample-size correction).
       ├─ ISOMER SUM      lr+br -> reported analyte; toggle per analyte x method.
       ├─ QC RULESET      rules on/off + limits, per method.
       ├─ UNIT MAP        method x matrix -> reporting unit (DW->ng/L; food->ng/kg).
       ├─ CAS MAP         analyte -> CAS / Maine DEP code (for EGAD EDD).
       └─ LOGBOOK TEMPLATES owned by the method. Form code = FM (form) - ENV
          (environmental) - the logbook's sequence number, read from the
          logbook pool: FM-ENV-001 Solvent/Reagent Prep, 002 Calibration
          Curve Prep, 003 Extraction Log, 004 Sample Processing (+ COC). The
          slugs 250-253 are storage keys only, never shown as form numbers.

  BATCH
    ├─ belongs to ONE METHOD and ONE MATRIX
    ├─ inherits that Method × Matrix analyte panel, QC rules, factors, units
    ├─ instantiates the method's LOGBOOK TEMPLATES as concrete logbooks
    │   (each with a unique ID that references the batch + method)
    ├─ contains SAMPLES (field samples + QC: MB, LFSM, LFSMD, Dup, LCS)
    └─ produces RESULTS + QC RESULTS (each result references its analyte,
        which references its method/matrix parentage)

  WORKSHEET -> the ANALYTICAL PROCESSING UNIT inside a batch.
           Logbooks (FM-ENV-001…004, CoC), QC results, prepared-
           standard lot records, and the 5-item data-review release checklist
           all attach to the WORKSHEET via ZODB annotations (IAnnotations) —
           NOT to the Batch. Batch is the client-facing container; Worksheet
           is the science. (SENAITE indexes Worksheets in
           senaite_catalog_worksheet, not portal_catalog — see DECISIONS.md.)

  REPORT
    └─ assembled from a BATCH → carries full parentage at every line:
        result → analyte → method × matrix → batch → samples → QC → logbooks
        → factors/qualifiers applied. Optional EDD export reads results + CAS
        map + qualifier map; BLOCKS if any analyte in the batch lacks a CAS.

  EQUIPMENT (ISO 17025 §6.4; decided 2026-10-03, GAPS §100):
           every piece is a core SENAITE Instrument with a core Instrument
           Type (as the LC-MS/MS is). The TYPE owns the obligations
           (equipment_types.py, annotation on the type): kind, calibration /
           check frequency, correction factor, external certificate, unit,
           tolerance (% of nominal; balances always g at 0.2 %), offered in
           worksheets. Due = the type's frequency since the last internal
           record, and SENAITE's certificate when the type requires one.
           The per-item PFAS settings (sensor, temperature range, weight
           points) annotate the instrument. Time-stamped verification records
           -- temperature, balance verification, pipette calibration, reagent
           water, waste, eyewash -- stay in SQLite at
           /data/qc/facility_monitoring.db, keyed by the instrument UID
           (browser/equipment.py is facility_qc's unit provider). Independent
           compliance obligation: records do NOT gate batch release; audited
           on their own cadence by the QAO.
```

**Rules that follow from the hierarchy:**

1. **Populate in order; enforce prerequisites.** You cannot define a surrogate
   map before the method's analyte set exists; cannot create a batch before its
   Method × Matrix panel is configured; cannot export an EDD before every
   analyte has a CAS code. The UI must reflect and enforce this order.

2. **Method × Matrix scoping is mandatory.** Any tool that lists analytes —
   surrogate map, recovery tiers, QC, report, EDD — must list the analytes
   valid for THAT method × matrix intersection, never a flat global list:
   an analyte unchecked for a matrix must not appear for it anywhere.

3. **Show method-conditional fields only for the method that uses them.**
   EIS recovery limits appear only for EPA 1633A. FDA's matrix-dependent
   recovery tiers appear only for FDA. Never expose a criterion the method
   doesn't use.

4. **Referential integrity on rename/delete.** Deleting or renaming an analyte,
   IS, method, or matrix must surface what references it — never leave orphaned
   surrogate maps, result rows, or logbook entries pointing at nothing.

---

## 4. THE ROLE MODEL (who you are)

Roles map onto SENAITE's built-in roles and gate what each person can do and
which workspace they land in. Each role has a DEFAULT landing workspace and a
set of ACCESSIBLE workspaces; the left panel shows only what the role can reach.

| Role (this lab) | Maps to SENAITE | Focus | Default workspace |
|---|---|---|---|
| Manager / QAO / Director / Owner | LabManager (+ QC-author perms) | Create & review: QC rules, method profiles; create/process/review extractions; sign-off | QC Management |
| Analyst (data reviewer) | Verifier / Analyst | Compare & review: extraction packet vs QC data vs instrument data — three-way verification of results | Data Review |
| Bench Chemist | LabClerk (not Analyst — decided 2026-09-30) | Fast operational: reagent creation, documentation, SOP-deviation notes, SOP access, append corrections to a batch | Bench |
| Client | Client | Minimal: their sample tracker + their published reports ONLY | Client Tracker |

Only Manager/QAO/Director/Owner may edit QC criteria, method profiles, and the
configuration tables (CAS map, units, factors, rule toggles).

**Automation / robotics (future-ready hook):** when reagent creation is
automated by robotics, the robot acts as a NON-HUMAN SERVICE ACCOUNT performing
Bench-Chemist *tasks* via the API/pipeline, audit-tagged as automated. The
Bench Chemist role still exists for human oversight, exceptions, deviations, and
approving what the robot did. Design the Bench workspace so its actions can be
performed by either a human or a service account; do NOT couple them so tightly
that a robot identity can't perform them. This is a hook, not a current build —
do not build robotics now, but do not preclude it.

---

## 5. THE WORKSPACE ARCHITECTURE (role-scoped views onto the truth)

A workspace is a role's **landing page**: a tile grid (the
`PFASQCManagementView` pattern, `browser/workspace_home.py`) that gives a
daily-driver role a queue rather than a menu. Only a role that needs that
at-a-glance view gets one; **every other subject is a group of links in the
§6A sidebar**, not a workspace (decided 2026-09-18, DECISIONS.md — "two
landings, not ten"). Native SENAITE pages stay reachable underneath.

The role-aware launcher `@@pfas-home` sends each role (§4) to its landing:

| Landing | View | Who lands there |
|---|---|---|
| **QC Management** | `@@pfas-qc-management` | LabManager / Manager |
| **Data Review** | `@@pfas-data-review-home` | Analyst / Verifier |
| **Bench** | `@@pfas-bench` | LabClerk (Bench Chemist) |
| **Client Tracker** | `@@pfas-track` | Client — minimal, separate, see §6C |

What each landing is for:
- **QC Management** (Manager/QAO) — method profiles, QC rules, control charts,
  calibrations, the review queue, deviations, facility QC, SOPs; sign-off.
- **Data Review** (Analyst) — tiles onto the per-worksheet release queue
  `@@pfas-data-review` (a different view: that is the queue, this is the
  landing). Release is gated by a 5-item checklist, all of which must pass
  before submission:
    (1) Chain of Custody — sample receipt conditions verified (manual)
    (2) Reagent/Standard Traceability — 3-level chain auto-resolved (auto)
    (3) QC Summary — recovery results vs method acceptance criteria (auto)
    (4) Final Data Summary — analyst review of reported results (manual)
    (5) Instrument Report — raw data file attached and reviewed (manual)
  The Analyst submits when all five pass; the Manager verifies. Both actions
  cascade to the worksheet's ANALYSES first — the worksheet's own transition
  only opens once they have moved (GAPS §5). This is the formal technical review
  required under ISO 17025 §7.8.4.
- **Bench** (Bench Chemist) — reagent inventory, prepared standards (with
  parent-reagent traceability chain), batch logbooks, SOPs, deviations. Built
  so a robot service account can perform the same actions (§4).

**Not workspaces — sidebar groups (§6A):** Equipment (was Facility QC), Sample Workflow,
Method & Analyte Setup, Instrument & Import, Reporting & EDD, and
Configuration (which holds the lab-admin settings console `@@pfas-lab-settings`,
GAPS §45). A new landing for any of these is a new decision, not a gap.

**So "which workspace does it live in?" (§9) means:** which sidebar group, and
whether it belongs as a tile on one of the three landings. Every landing's
analyte lists, criteria, and actions are views onto the §3 relational spine and
obey the §4 role permissions. A landing never invents data the model doesn't
own.

---

## 6. THE LAYOUT & NAVIGATION (how every view is drawn)

Two parts: (A) the site-wide navigation shell that wraps EVERY page, and
(B) the panel content layout inside workspace pages.

### 6A. SITE-WIDE PERSISTENT SIDEBAR (the unifying navigation)

There is ONE persistent left sidebar present on EVERY page — core SENAITE
pages (Samples, Batches, Worksheets, Clients, Setup) AND PFAS workspaces alike.
It replaces the situation where important features were buried on a separate
"LIMS Setup" page. The sidebar is the single way to navigate the system.

- **Light theme.** Integrate toward SENAITE core's existing LIGHT theme to
  minimize core modification. Do NOT darken core. Bring PFAS pages into the
  light palette using core theme tokens.

- **Grouped, collapsible accordion structure.** Groups are collapsible
  accordions (click a heading to expand its items; others can collapse). The
  groups:

  ```
  OPERATIONS          Clients · Samples · Batches · Worksheets · Sample Tracker
  QC & METHODS        Method Profiles · QC Rules · Control Charts ·
                      Calibrations · Specifications/Recovery
  BENCH               Reagent Inventory · Prepared Standards ·
                      Logbooks (tabs: Templates -> Method sequence -> By
                      batch) · Extraction Guide · SOPs / Deviations
                      (Lot usage opens from "Where used", not the sidebar)
  EQUIPMENT           Equipment · Equipment Types · Daily Checklist ·
                      Temperature · Balance · Weight Sets · Pipettes ·
                      Reagent Water · Waste · Eyewash
  INSTRUMENTS & IMPORT  Instruments · Import Studio · Calibrations
  REPORTING           Reports · EGAD EDD
  CONFIGURATION       (collapsible, out-of-the-way) the old Setup tiles grouped:
                      Storage & Inventory · Instrument Setup ·
                      Method & Analyte Setup · General
  ```
  Keep CONFIGURATION as one group so setup is findable but out of the way;
  key setup items may ALSO be mirrored into their work group.

- **Role-driven visibility tied to EXISTING SENAITE privileges.** The sidebar
  shows/hides items based on the permissions SENAITE ALREADY enforces on the
  underlying pages — NOT a parallel permission system. A Bench Chemist sees the
  BENCH group expanded and items they lack permission for are hidden; a Manager
  sees QC & METHODS; etc. If a user can't access a page in SENAITE, it doesn't
  appear in their sidebar. This keeps navigation and access in sync by
  construction. (Map this to the role model §4, but enforce via existing
  Plone/SENAITE permissions, not new ones.)

- **Rationalize SENAITE's scattered nav.** SENAITE currently puts some items in
  the left nav (e.g. Methods) and others only in Setup. Unify them into the one
  grouped sidebar so there is a single coherent navigation, no buried features.

- **Collapsible to an icon rail** for focus mode (per the panel layout below).

### 6B. WORKSPACE PANEL CONTENT (MS Quan-style, inside the shell)

Inside a workspace page, content uses the panel layout proven on the Method
Profile pages:
- TOP BAR: ONE macro on every page, core and PFAS (templates/pfas_topbar.pt,
  AdminLTE 3 navbar; GAPS §93): menu + page title | context chip (core: the
  object's tabs) | global icons. Nothing clickable in the context zone.
- SUB-BAR under it: breadcrumb (left) + the page's actions and back buttons
  (`header-right` slot, right); fixed above the tabs.
- TOP SUB-HEADING TABS: a page's sections render as tabs across the top — NOT a
  long vertical accordion of collapsible sections. (Finish converting the
  remaining collapsible-section pages to tabs.)
- STABLE CONTENT AREA: changes by selection + active tab; does not reflow.
- PINNED ACTION BAR: primary action sticky, always visible; never floats
  mid-page.

### 6C. RULES

- **One frame, measured (decided 2026-09-30, GAPS §49).** The page title lives
  in the dark header bar, with a breadcrumb line under it; no page adds its own
  H1 title. Tables and lists use the full content width; reading and form pages
  (logbooks, editors, wizards) use ONE shared narrower width — never a
  page-chosen max-width. The sidebar opens on the user's landing (pinned at the
  top) with their role's group and the current page's group expanded and the
  rest collapsed. `tools/ui_audit.py` measures all of this; run it before and
  after any layout change.
- **Page-local styling only shrinks.** `tests/test_ui_ratchet.py` pins the count
  of per-page `<style>` blocks, `style=` attributes, hex colours and font sizes;
  lower the ceiling in the same commit that lowers the count.

- Define the shell + panel ONCE as shared templates; never restyle pages
  individually. Reuse core theme tokens.
- Build as an upgrade-safe THEME/OVERRIDE LAYER (diazo theme + view/viewlet
  registrations) in the add-on — do NOT edit or fork core. Document exactly
  what core views/templates are wrapped or overridden in DECISIONS.md; flag
  upgrade fragility.
- PHASED rollout: build the sidebar shell first; then wrap core pages group by
  group; verify native SENAITE still works after each.
- Client Tracker remains the exception: NO sidebar, NO chrome — minimal,
  separate, anxiety-sensitive, reached by tracking number, no login.

---

## 7. PIPELINE / INTEGRATION MODEL

- The in-Plone add-on and the out-of-process worker are ONE system, not two.
  They share the §3 model. The worker (Py3) talks to SENAITE only via
  `senaite.jsonapi` (JSON/REST) — that is the integration boundary and the
  reason the worker may be Py3 while the add-on is Py2.7.
- No logic duplicated across the two (analytes, QC rules, mappings, method
  profiles live once, referenced by both).
- **Import Studio is the single source of truth for instrument mappings.** The
  importer READS saved Studio profiles (per instrument + software version); it
  does NOT carry hardcoded vendor configs. No saved profile for a file's
  instrument/version -> the importer REFUSES and directs the user to Import
  Studio (never auto-guess into processing).
- Barcode scanning is wired into SENAITE (Batch/Worksheet + Reagent inventory +
  the guided extraction), not standalone. The guided extraction is the ONE
  extraction record (the separate tablet service is retired): it picks every
  lot from the inventory, records per-sample amounts and dilutions into the
  Extraction Log (FM-ENV-003) rows, and the Run Builder hands it to the worker
  as the run's sidecar.
- **Storage architecture — three tiers, each for a reason:**
  - **ZODB annotations** (`IAnnotations(obj)[key]`): per-object transactional
    data — logbook entries, release checklists, prepared-standard parent chains.
    Use when the data belongs to exactly one ZODB object and must participate in
    ZODB transactions.
  - **SQLite** (`/data/qc/*.db`): time-series and cross-object tabular data —
    facility QC readings (`facility_monitoring.db`), QC result sets for control
    charting (`pfas_qc_results.db`). Use when data is date-indexed, queried by
    range, and not owned by a single ZODB object. Both the Plone process
    (Py2.7) and the pipeline worker (Py3) can read the same SQLite file.
  - **Filesystem** (`/data/instrument_reports/{ws_uid}/`): binary uploads and
    pipeline-consumed artifacts — instrument data files, PDF certificates. Use
    when the file must survive ZODB restores or is a binary upload from a user.
  - Rule: one ZODB object → annotate it; time-series/cross-object → SQLite;
    binary file artifact → filesystem.

---

## 8. WORKING AGREEMENT

- Start each task with a short PLAN + dependency assessment. For schema/data-
  model or core-touching changes: AUDIT first, present a consolidation/design
  plan, get my sign-off BEFORE refactoring. Do not refactor the data model or
  override core templates until I approve the plan.
- `DECISIONS.md`: append every decision (proposed/confirmed/superseded) with
  date + context. `QUESTIONS.md`: open questions awaiting my answer. No
  assumption may live only in code.
- Commit to git after each significant change (restore points), **and push**.
  There is a remote as of 2026-09-25 (`origin`,
  github.com/Robert-Hurst-PhD/SENAITEpfaslims, SSH, **public**) — before it
  existed, 204 commits lived on one disk, which GAPS §14.1 called the top
  standing risk. A commit that is not pushed has not addressed that risk. Push
  the working branch at the end of any turn that produced a commit; do not batch
  a session's commits into one push at the end, because the session is exactly
  what might not finish.
- The repo is PUBLIC. Anything committed is published permanently: no lab data
  (`.gitignore` covers `data/`), no client identifiers in commit messages, and
  remember that GAPS.md / DECISIONS.md are readable by anyone.
- Licence is **GPLv2**, resolved 2026-09-25 (DECISIONS.md). `LICENSE` holds the
  verbatim GPL-2.0 text, `setup.py` declares it in both `license=` and
  `classifiers`, and README carries the notice. It was not a free choice:
  senaite.core/lims/storage are all GPLv2 and are imported directly, so this is a
  derivative work. Do not relicense, and do not add code under an incompatible
  licence. The copyright HOLDER is still the placeholder `PFAS Lab` and is the
  lab's to set — never infer it from an account name.
- Surface what a rename/delete would orphan before doing it.
- After each change, bring the stack up and verify against the running instance;
  confirm the pipeline still imports, runs QC (respecting toggles, factors,
  isomer sums, version-dependent IS correction), and reports. Show me how to
  verify in the browser.
- Respect placeholders (EPA 1633A per-analyte limits, some CAS, Waters import
  schema, MRM transitions): make them configurable + flagged "verify"; never
  fabricate a regulatory value.
- **Every shipped regulatory value cites a public source** in
  `docs/REFERENCES.md` (method, document number, section/table), or is the
  lab's own setting entered in the UI, or is flagged VERIFY there. The lab's
  spreadsheets ("FDA calculator", injection-list workbook), the instrument
  exports supplied for testing and the demo/seeded data are TEST MATERIAL:
  never cite them as the origin of a value, in code, comments or docs.
- Migration: when the model changes, MIGRATE existing configured data into the
  new structure without loss — not just define the new schema.

---

## 9. BEFORE BUILDING ANY MODULE, ASK YOURSELF

- What object in §3 OWNS this data? Am I referencing it, or duplicating it?
- Does every analyte list respect the Method x Matrix panel (not a flat list)?
- Can every value name its full parentage up the tree?
- Is this criterion scoped to the method that actually uses it?
- Which ROLE (§4) can see/edit this, and where does it live (§5) — which
  sidebar group, and is it a tile on one of the three landings?
- Am I using the shared panel layout (§6) and core theme tokens, not bespoke
  styling?
- If it can't be expressed as a view onto §3 scoped by §4 rendered in §6 —
  STOP and raise it with me; the model may need a new relationship, which is an
  explicit decision, not something to paper over.

---

## 10. LAB PRACTICE PRINCIPLES (ISO 17025 / PFAS-method grounding)

These are the regulatory obligations the system exists to enforce. A feature
that undermines one of these is a defect, not a design choice.

> **Read `docs/ISO17025_DESIGN.md` before changing anything in this section's
> scope.** This section states the obligations; that document derives them —
> for each one, what the model must own, the defect shape that violates it, how
> it was caught, and the file:line that now prevents it. Every entry is a real
> defect found in this system. It also records where refusing to proceed is
> correct and where it is wrong, which is not inferable from the rules alone.

**Chain of Custody as a sample acceptance prerequisite.** Under EPA 537.1,
EPA 1633A, and FDA PFAS methods, a sample without a completed CoC is formally
unreceivable. CoC records: client, project, collection date, field sampler,
preservation method, container condition, holding-time compliance, and every
custody transfer. No CoC → no analysis. CoC is gate #1 of the Data Review
checklist.

**Holding times are a hard acceptance criterion.** EPA 537.1 v2.0 §8.5:
samples extracted within 14 days of collection, extracts analysed within 28
days of extraction. FDA holding times are as the lab enters them (C-010.04). Samples
received past holding time have compromised integrity; this must be documented
in CoC condition notes. "Holding Times OK" is a required CoC field; if
unchecked, the CoC gate does not pass.

**Reagent lot traceability (3-level chain).** ISO 17025 §6.6 requires every
result to trace back to the reference standards and reagents used:
(1) Reagent lot (`pfas_reagents/`) — CoA, supplier, lot#, expiry — is the
    leaf node.
(2) Prepared Standard lot (`pfas_prepared_standards/`) — parent reagent lots
    stored via ZODB annotation (`senaite.pfas.prepstd.parent_reagents`) — is
    the middle link.
(3) Analysis result connects back via the Calibration Curve Prep Log
    (FM-ENV-002: which PS lots in calibration/QC) and the Extraction Log
    (FM-ENV-003: which reagent, standard and consumable lots in extraction).
Each link is explicit, not inferred. An expired CRM lot invalidates prepared
standards made from it; those results are not defensible.

**QC acceptance as a hard release gate.** Method blank, LCS, LFSM/LFSMD, and
IS recovery results are pass/fail — not informational. Each method specifies
acceptance limits per analyte per QC type; a failing result means the batch
CANNOT be released without a documented exception. The Data Review QC Summary
auto-check blocks submission if any non-voided QC result fails.

**Reference standard provenance (NIST-traceable).** CRM reagents must carry a
CoA from an accredited supplier establishing NIST traceability. Expired CRMs
must not be used; the reagent inventory displays expiry status.

**Equipment and facility checks as an independent compliance obligation (ISO
17025 §6.4).** Environmental monitoring and equipment verification
(temperature, balance verification, pipette calibration, reagent water, waste,
eyewash) are documented on their own cadence. What each piece of equipment owes
-- how often, whether readings are corrected, whether an external certificate
is required -- is set on its TYPE (Equipment Types), never per page. Records
are reviewed by the QAO independently, not per-batch. A failing reading on a
run date is noted on the Daily Checklist but evaluated separately from batch
release; the extraction's equipment chain (balance verification -> weight set
-> metrology certificate) is still traced in Data Review.

**Data Review as the formal technical review (ISO 17025 §7.8.4).** Report
issuance requires a documented technical review. The 5-item checklist + Analyst
submit + Manager approve IS this technical review — not a courtesy step.
Without it the Worksheet cannot transition to verified and no report can be
issued.
