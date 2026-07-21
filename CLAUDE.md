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
   result → which prepared standard lots were used (FM-ENV-251 lot_ref fields)
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
and per-matrix QC: FDA 32-PFAS in Food, EPA 537.1, EPA 1633A.

Stack (each layer depends on the one below):
```
senaite.pfas (this add-on) + pipeline worker (Py3, via JSON)
SENAITE (the LIMS: core, lims, app.listing)
Plone (CMS framework: Dexterity content types, GenericSetup, permissions)
Zope (application server — runs the code)
ZODB/ZEO (object database — Data.fs in the senaite-data volume = BACK IT UP)
Python 2.7  /  Docker / Linux
```
Read `README.md` and `RESOURCE_MAP.md` before doing anything.

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
       │     every matrix. Canonical example: under FDA, PFODA is NOT reportable
       │     in eggs but IS in meat. The reportable panel = checked
       │     intersections for that Method x Matrix.
       │
       ├─ SURROGATE MAP   native -> quantifying IS (many natives -> one IS).
       │                  QUANTIFICATION link. Drag-and-drop, never JSON.
       ├─ RECOVERY TIERS  per analyte; for FDA the tier is MATRIX-DEPENDENT
       │                  (80-120 big-four in egg/meat/seafood; 65-135 else;
       │                  40-140 +RSDr<=30 for no-labeled-standard analytes).
       ├─ EIS RECOVERY    EPA 1633A ONLY (hidden for FDA/537.1). RECOVERY-QC
       │                  limits per analyte/matrix. DISTINCT from surrogate map.
       ├─ SALT FACTOR     per analyte x method (decimal < 1, from CoA).
       ├─ MATRIX ADJUST   ONE factor per method (sample-size correction).
       ├─ ISOMER SUM      lr+br -> reported analyte; toggle per analyte x method.
       ├─ QC RULESET      rules on/off + limits, per method.
       ├─ UNIT MAP        method x matrix -> reporting unit (DW->ng/L; food->ng/kg).
       ├─ CAS MAP         analyte -> CAS / Maine DEP code (for EGAD EDD).
       └─ LOGBOOK TEMPLATES (FM-ENV-250/251/252/253) owned by the method.

  BATCH
    ├─ belongs to ONE METHOD and ONE MATRIX
    ├─ inherits that Method × Matrix analyte panel, QC rules, factors, units
    ├─ instantiates the method's LOGBOOK TEMPLATES as concrete logbooks
    │   (each with a unique ID that references the batch + method)
    ├─ contains SAMPLES (field samples + QC: MB, LFSM, LFSMD, Dup, LCS)
    └─ produces RESULTS + QC RESULTS (each result references its analyte,
        which references its method/matrix parentage)

  WORKSHEET -> the ANALYTICAL PROCESSING UNIT inside a batch.
           Logbooks (FM-ENV-250/251/252/253/CoC), QC results, prepared-
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

  FACILITY QC RECORDS (parallel compliance subsystem, ISO 17025 §6.4):
           Time-stamped environmental and equipment verification records:
           temperature (refrigerators, freezers, room), balance verification,
           reagent water, waste, eyewash. Stored in SQLite at
           /data/qc/facility_monitoring.db. Independent facility compliance
           obligation — records do NOT gate individual batch release; audited
           on their own cadence by the QAO.
```

**Rules that follow from the hierarchy:**

1. **Populate in order; enforce prerequisites.** You cannot define a surrogate
   map before the method's analyte set exists; cannot create a batch before its
   Method × Matrix panel is configured; cannot export an EDD before every
   analyte has a CAS code. The UI must reflect and enforce this order.

2. **Method × Matrix scoping is mandatory.** Any tool that lists analytes —
   surrogate map, recovery tiers, QC, report, EDD — must list the analytes
   valid for THAT method × matrix intersection, never a flat global list.
   PFODA must not appear for FDA × eggs.

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
| Bench Chemist | Analyst / LabClerk | Fast operational: reagent creation, documentation, SOP-deviation notes, SOP access, append corrections to a batch | Bench |
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

The system is organized into subject workspaces, gated by role (§4). Each
workspace is the SAME panel layout (§6), scoped to one subject and one role's
needs. A role-aware **workspace launcher** is the landing page; native SENAITE
pages remain reachable underneath. (Replace-vs-alongside native nav: current
decision = alongside/launcher; revisitable.)

Workspaces:
- **QC Management** (Manager/QAO) — method profiles, QC rule toggles, recovery
  tiers, control charts review, sign-off. Default for Manager.
- **Data Review** (Analyst) — per-worksheet release gating via a 5-item
  checklist (all must pass before submission):
    (1) Chain of Custody — sample receipt conditions verified (manual)
    (2) Reagent/Standard Traceability — 3-level chain auto-resolved (auto)
    (3) QC Summary — recovery results vs method acceptance criteria (auto)
    (4) Final Data Summary — analyst review of reported results (manual)
    (5) Instrument Report — raw data file attached and reviewed (manual)
  Analyst submits when all five pass (Worksheet → to_be_verified); Manager
  approves (Worksheet → verified). This is the formal technical review
  required under ISO 17025 §7.8.4. Default for Analyst.
- **Facility QC** (Manager/QAO) — environmental monitoring and equipment
  verification dashboard (ISO 17025 §6.4): temperature sensors, balance
  verification, reagent water, waste, eyewash. Reviewed by QAO independently
  of batch release. Records in SQLite (/data/qc/facility_monitoring.db).
- **Bench** (Bench Chemist) — reagent creation, prepared standards (with
  parent-reagent traceability chain), logbooks/documentation, SOP access,
  SOP-deviation notes, append corrections to a batch. Default for Bench
  Chemist. Built so a robot service account can perform the same actions.
- **Sample Workflow** (Manager/Analyst) — walks Method -> Matrix -> Batch ->
  Samples -> Results: receive -> extract -> run -> review -> report.
- **Method & Analyte Setup** (Manager) — the relational config: analyte x matrix
  inclusion, surrogate map, factors, units, CAS map; the new-method wizard.
- **Instrument & Import** (Manager/Analyst) — Import Studio (column mapping per
  instrument+software version), instruments, calibrations.
- **Reporting & EDD** (Manager/Analyst) — report assembly, EGAD EDD generation
  + delivery.
- **Client Tracker** (Client) — minimal, separate, see §6.

Every workspace's analyte lists, criteria, and actions are views onto the §3
relational spine and obey the §4 role permissions. A workspace never invents
data the model doesn't own.

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
                      Prep Logbooks · Batch Logbooks · SOPs / Deviations
  FACILITY QC         Temperature · Balance · Reagent Water ·
                      Waste · Eyewash
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
- TOP HEADER BAR: page title (left), context badge + back/switch (right).
- TOP SUB-HEADING TABS: a page's sections render as tabs across the top — NOT a
  long vertical accordion of collapsible sections. (Finish converting the
  remaining collapsible-section pages to tabs.)
- STABLE CONTENT AREA: changes by selection + active tab; does not reflow.
- PINNED ACTION BAR: primary action sticky, always visible; never floats
  mid-page.

### 6C. RULES

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
  extraction logbooks), not standalone.
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
- Commit to git after each significant change (restore points). Surface what a
  rename/delete would orphan before doing it.
- After each change, bring the stack up and verify against the running instance;
  confirm the pipeline still imports, runs QC (respecting toggles, factors,
  isomer sums, version-dependent IS correction), and reports. Show me how to
  verify in the browser.
- Respect placeholders (EPA 1633A per-analyte limits, some CAS, Waters import
  schema, MRM transitions): make them configurable + flagged "verify"; never
  fabricate a regulatory value.
- Migration: when the model changes, MIGRATE existing configured data into the
  new structure without loss — not just define the new schema.

---

## 9. BEFORE BUILDING ANY MODULE, ASK YOURSELF

- What object in §3 OWNS this data? Am I referencing it, or duplicating it?
- Does every analyte list respect the Method x Matrix panel (not a flat list)?
- Can every value name its full parentage up the tree?
- Is this criterion scoped to the method that actually uses it?
- Which ROLE (§4) can see/edit this, and which WORKSPACE (§5) does it live in?
- Am I using the shared panel layout (§6) and core theme tokens, not bespoke
  styling?
- If it can't be expressed as a view onto §3 scoped by §4 rendered in §6 —
  STOP and raise it with me; the model may need a new relationship, which is an
  explicit decision, not something to paper over.

---

## 10. LAB PRACTICE PRINCIPLES (ISO 17025 / PFAS-method grounding)

These are the regulatory obligations the system exists to enforce. A feature
that undermines one of these is a defect, not a design choice.

**Chain of Custody as a sample acceptance prerequisite.** Under EPA 537.1,
EPA 1633A, and FDA PFAS methods, a sample without a completed CoC is formally
unreceivable. CoC records: client, project, collection date, field sampler,
preservation method, container condition, holding-time compliance, and every
custody transfer. No CoC → no analysis. CoC is gate #1 of the Data Review
checklist.

**Holding times are a hard acceptance criterion.** EPA 537.1: 14 days for
drinking water PFAS. FDA methods specify per-matrix holding times. Samples
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
(3) Analysis result connects back via FM-ENV-251 (which PS lots in calibration/
    QC) and FM-ENV-252 (which reagent lots in extraction).
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

**Facility QC as an independent compliance obligation (ISO 17025 §6.4).**
Environmental monitoring (temperature, balance verification, reagent water,
waste, eyewash) is documented on its own cadence — continuous/daily for
sensors, daily for balance and water, periodic for eyewash and waste. Records
are reviewed by the QAO independently, not per-batch. A failing reading on a
run date is noted in the Facility QC dashboard but evaluated separately from
batch release.

**Data Review as the formal technical review (ISO 17025 §7.8.4).** Report
issuance requires a documented technical review. The 5-item checklist + Analyst
submit + Manager approve IS this technical review — not a courtesy step.
Without it the Worksheet cannot transition to verified and no report can be
issued.
