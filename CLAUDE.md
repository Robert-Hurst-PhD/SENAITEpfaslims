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

6. **Every output traces its parentage.** A result must be able to name: its
   analyte → method × matrix → batch → samples/QC → surrogate/IS → tier →
   factors/qualifiers applied. If a value can't name its parents, the model
   is wrong.

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

  BATCH  -> belongs to ONE method + ONE matrix; inherits that Method x Matrix
           panel, QC rules, factors, units; instantiates logbook templates as
           concrete logbooks (each with an ID referencing batch+method);
           contains SAMPLES (field + QC: MB/LFSM/LFSMD/Dup/LCS); produces
           RESULTS + QC RESULTS.

  REPORT -> assembled from a batch, full parentage at every line. Optional EGAD
           EDD export reads results + CAS map + qualifier map; BLOCKS if any
           analyte lacks a CAS code.
```

Rules: populate top-down in order; enforce prerequisites in the UI; scope every
analyte list to Method x Matrix (never a flat global list); show
method-conditional fields only for methods that use them; maintain referential
integrity on rename/delete.

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
- **Data Review** (Analyst) — the three-way comparison: extraction data packet
  vs QC results vs instrument data, per batch, to verify results. Default for
  Analyst.
- **Bench** (Bench Chemist) — reagent creation, logbooks/documentation, SOP
  access, SOP-deviation notes, append corrections to a batch. Default for Bench
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
  BENCH               Reagent Inventory · Logbooks · SOPs / Deviations
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
