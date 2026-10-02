# Configuration architecture review

> **Status:** R1 and R2 implemented (GAPS §52–§70); see GAPS for what remains.

*2026-09-30. Question asked: can a laboratory configure every QC parameter this
analysis needs without editing Python, and is the structure sound enough to
trust with that? Evidence is from the code at commit `4dc2fc2`, the live
no-op-save audit (GAPS §51) and `tools/audit_configurable.py`.*

## Verdict

**Tuning an existing method: yes, now.**

Acceptance limits, recovery tiers, rule toggles, units, factors, holding times,
RL/MDL, qualifiers, certificate wording and regulatory limits are all editable
in the UI. After today's fixes, saving them records what was entered and
nothing else. Criteria are frozen onto each worksheet at verification, so a
later edit cannot rewrite an issued result.

**Extending the analysis: no.** Adding a method, an analyte, a QC type or a
vocabulary entry still needs Python. So does keeping a controlled history of
who changed which criterion. For a laboratory that will add methods and
analytes (EPA 533, state methods, new PFAS), these are the gaps that matter.

**The editing layer was the weakest part.** One audit found nine save
defects. They did not come from one careless page. They came from one design:
each editor hand-writes its rendering, script serialisation and parsing,
separately and differently. That is fixable as a structure, not just defect by
defect.

## What is sound (keep it)

- **One stored profile per method,** exported to the worker as JSON. The add-on
  and the worker read the same values (§7 of CLAUDE.md).
- **Refuse, don't assume.** An unset judging criterion blocks release instead
  of substituting a plausible number (`settings_registry.UnconfiguredSetting`).
- **Criteria frozen on the worksheet** at verification
  (`worksheet_criteria_snapshot`), so certificates cannot drift from the review
  that authorised them.
- **The Lab Settings console** enumerates declared settings, with status and
  owner.
- **Per-action authorisation tiers** (§46), a **fill-only installer** (§47),
  and **guards that are mutation-tested**.

## Findings, ranked by how often a laboratory hits them

### F1. A new method needs Python (high)

The pipeline's QC engine has a fixed registry of three classes:

```python
_PROFILES = {"FDA_32PFAS": FDA32PFASProfile(), "EPA_537_1": EPA537Profile(),
             "EPA_1633A": EPA1633AProfile()}
```

- **A method made in the Method Wizard gets a stored profile, but
  `get_profile()` raises "Unknown method profile"** for it, so its runs cannot
  be QC-evaluated.
- Method-specific behaviour lives in those subclasses: FDA's matrix-dependent
  tiers, 1633A's EIS limits, and 537.1's origin-forced curve.
- **Thirteen modules carry the three method IDs** literally. The worst are
  `pfas_pipeline/method_profiles.py` (33), `analyte_reference.py` (31),
  `seed_calibrations.py` (14), `method_profile_store.py` (13) and
  `qc/rules.py` (9). Others include `method_baselines.py`, `egad_store.py`,
  `sop_documents.py`, `qc_grid.py`, `egad_config.py`, `settings_adapters.py`
  and `egad_edd.py`.
- Calibration levels for FDA and 537.1 are also constants in
  `injection_builder.py`, which duplicates the method's calibration ladder.

### F2. The analyte library is code, and there are two of them (high)

- `analyte_reference.NATIVE_ANALYTES` (110 rows: keyword, CAS, class, chain,
  surrogate, labelled-standard flag, key flag) is read by 22 modules.
- A second table, `analytes.PFAS_ANALYTES`, holds the MRM transitions
  (`IS_MRM`) and feeds the confirm-ion map and the EDD builder.
- **Adding a PFAS, correcting a CAS number, or changing a native's surrogate
  is a code edit**, contrary to Golden Rule 1. Two tables describing the same
  analytes can drift apart, contrary to Golden Rule 3.
- Placeholder CAS values live in code, and the certificate had to learn to
  suppress them.

### F3. No change history on method configuration (high, for ISO 17025)

- A method profile is one JSON value, **overwritten on every save.** Only the
  recovery limits synced to SENAITE AnalysisSpecs, and settings saved through
  the settings registry, leave an audit entry.
- **CCV windows, S/N limits, holding times, RL/MDL, factors, rule toggles,
  print wording and regulatory limits keep no record** of the previous value,
  who changed it, or when. §8.3 and §7.5 (control of documents and records)
  expect that record for acceptance criteria.
- Results are protected by the worksheet freeze. The configuration itself is
  not.
- **No protection against concurrent edits.** Two people with the editor open:
  the second save silently replaces the first.

### F4. The editing layer is hand-built per page (high, the root cause)

- The Method Profile editor is **~3,500 lines**: `method_profiles.py` 1,228,
  the template 1,369, the script 895. **One 361-line handler parses twelve
  panes from one POST.**
- Values travel by three routes: named fields; JSON built by script at submit
  time; and JSON built by script on change.
- Presence markers (`*_present`) were added pane by pane after partial-POST
  wipes (GAPS §7), and they are still inconsistent.
- **Today's nine defects all come from that shape:** defaults written into
  fields; a serialiser crash that silently dropped edits; tiers rebuilt without
  their scope fields; hidden lists starting empty; selects unable to show the
  stored value; blanks coerced to 0, 1.0 or 365; a checkbox with a true
  default.
- Guards and the live audit now catch each pattern. **Structurally, nothing
  stops the next page from repeating them.**

### F5. Default criteria are defined three times (medium)

- **Three copies:**
  - `method_profile_store.DEFAULT_PROFILES` (the add-on seeds);
  - the pipeline's `_DEFAULT_PROFILE_CACHE` plus class attributes;
  - `constants._DEFAULT_CRITERIA`.
- A stored profile overlays the pipeline's class defaults, so **a key the lab
  never set silently takes the pipeline's value**, which may not match what the
  editor shows as the default.
- `audit_configurable` flags four acceptance values inlined as fallbacks
  (`setuprefs.py` and the pipeline).

### F6. Vocabularies are code (medium)

All of these are lists in code:
- QC type codes and priorities (`analytes.QC_TYPE_CODES`, `_QC_PRIORITY`);
- injection-name patterns;
- spike level names (`Low/Mid/High`);
- QC failure types (`qc_qualification.FAILURE_TYPES`);
- EIS matrix classes;
- the non-detect words the certificate recognises;
- the unit conversion table;
- limit kinds;
- EDD required columns.

A laboratory using "LCS" where the code says "LFB", or a new instrument that
names injections differently, needs a code change. §45 already records this
("Vocabulary group is empty").

### F7. Storage is fragmented (medium)

- 24 PFAS annotation stores on the portal, 7 `pfas_*` folders of objects, two
  JSON files, `pfas_*` fields on core services, and a per-client annotation.
- Each store has its own shape, its own validation (or none), and its own
  export (or none).
- **Snapshotting "the configuration" for the audit needed a purpose-built
  tool.** A laboratory asked to hand an assessor "the configuration in force on
  date X" has no way to produce it.

### F8. Seeds harden on first save (low, a policy decision)

- A page that shows code defaults stores them on its first save:
  - EDD CAS rows;
  - print and certificate settings;
  - reagent expiry defaults;
  - regulatory seeds.
- **After that, a corrected seed never reaches the stored copy.** This matches
  the §47 "fill only" rule, but it is not visible to the laboratory.

## Recommendations, as plans for sign-off (CLAUDE.md §8)

Ordered by value for effort. Each changes the data model or the pipeline
boundary, so none starts without approval.

### R1. A change record for every configuration save (addresses F3; small to medium, first)

- **Every save through a configuration store appends one entry** to that
  store's history: who, when, the section, and the path-level diff (the audit's
  diff code already produces this).
- **Each editor shows "last changed by X on date".**
- **A History page per method** shows the diffs, with restore of a single
  change.
- **A version stamp in each form,** so a stale save is refused rather than
  silently overwriting a colleague's edit.
- This is additive. It does not change what is stored, only records it.

### R2. One editor framework, defined by a schema (addresses F4; medium)

- **Each section of a configuration page is declared once:** fields, types,
  units, allowed values, required/optional, and what "unset" means.
- **The framework does the rest from that declaration:** renders the fields
  (stored value as value, default as placeholder), parses the POST (only the
  section submitted; absent = unchanged; unparseable = refused with the field
  named), validates, diffs, and writes the R1 history.
- **Pages keep their layout;** they stop owning parsing.
- **Migrate the Method Profile editor pane by pane,** each pane saving on its
  own. The twelve-pane single POST disappears, and with it the partial-POST
  class.
- **Tables** (tiers, EIS, surrogate map, analyte × matrix) become schema'd row
  editors that post named fields, not script-built JSON.

### R3. The analyte library as data (addresses F2; medium)

- **One analyte store** (keyword, name, CAS, class, chain, role, surrogate,
  labelled-standard flag, MRM transitions, verified flag), edited in the UI,
  with CSV import/export.
- The two code tables become its seed and are then retired.
- **Referential integrity on rename/delete** (CLAUDE.md §3 rule 4) is enforced
  by the store: it lists every method, profile and result that references an
  analyte before allowing the change.

### R4. Method as data in the pipeline (addresses F1 and F5; large, the most valuable)

- **One generic engine driven entirely by the stored profile,** with the
  method-specific behaviours expressed as named options the profile selects.
  Examples: "recovery tiers by matrix", "EIS recovery limits", "origin-forced
  calibration", "single-transition confirmation".
- **The three classes become three stored profiles.** A new method is created
  in the wizard by choosing options, not by writing a class.
- **Defaults come from one source** that both the add-on and the worker read,
  and the literal method IDs in 13 modules are replaced by lookups.
- **Prerequisite:** the pipeline's regression tests are extended to prove the
  generic engine reproduces today's verdicts on the stored FDA, 537.1 and 1633A
  runs, exactly as the surrogate-map derivation was proven in §9.

### R5. A vocabulary registry (addresses F6; small)

- **Declared vocabularies** (QC types, injection patterns, spike levels,
  failure types, non-detect words, limit kinds) are stored and edited in the
  Lab Settings console's empty Vocabulary group.
- **Retire rather than delete,** with usage counts (the §45 Phase 6 plan).

### R6. One configuration export (addresses F7 and F8; small)

- **Promote `tools/config_snapshot.py` into a download:** "configuration in
  force, as of now", and with R1, "as of date X".
- **Mark seeded-but-unchanged values** in each editor, and offer "take the
  current code default" for them, so seed corrections can be adopted
  deliberately.

## Suggested order

1. **R1, change history.** Smallest change, closes the ISO gap, and makes
   every later migration safer to review.
2. **R2 on the Method Profile editor.** Removes the source of the save
   defects where they do the most harm.
3. **R3, analytes.**
4. **R5, vocabularies,** alongside R3.
5. **R4, method as data.** Largest; it rests on R2's schemas and R3's analyte
   store.
6. **R6** at any point.

## Decisions needed

1. **Approve R1** (change history) as the next piece of work?
2. **R2's direction:** one schema-driven editor framework, migrating the
   Method Profile editor pane by pane with per-pane saves?
3. **R4's scope:** will the laboratory add methods beyond FDA 32-PFAS, EPA
   537.1 and EPA 1633A? If so, which first? That sets how much of R4 is needed
   and in what order.
4. **Seed policy (F8):** keep "stored on first save", or show seeded values
   as defaults until the laboratory confirms each one?
