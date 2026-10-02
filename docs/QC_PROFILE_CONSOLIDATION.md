# Method QC profile consolidation review (2026-10-02)

Scope: every place a method's QC criteria, calibration or QC composition is
stored or read, across the three live profiles (FDA 32-PFAS, EPA 537.1,
EPA 1633A). Read-only audit against the running instance; nothing changed.
This complements docs/CONFIG_ARCHITECTURE_REVIEW.md (F5 / R4 cover the
duplicated default tables in general; this review is QC-specific and lists
the live disagreements). Plans below need sign-off (CLAUDE.md §8).

## Verdict

The method profile is the right single home and most of it is already
there: declared editor sections, per-method tiers, key analytes, low-level
tiers, calibration levels, project specs as a patch over it. What remains
is **nine facts that still live in two or three places**. Three of them
**actively disagree today**, so two screens judge the same data against
different limits.

## Findings, worst first

### C1. A second set of QC criteria in qc_rules.json, with no editor (high)
- `qc_rules.json` holds `global` and `method_overrides` (R², CCV window, S/N,
  RT tolerance, ion ratio, IS response) and `qc_types` (CAL/ICV/CCV/CCB
  % deviation, LCS recovery, chart settings).
- Its editor is gone: `@@pfas-qc-rules` redirects to Method Profiles (D52).
  So these values cannot be changed in the UI.
- The **Calibrations review page** (`browser/calibrations.py`) still judges
  curves with them; the pipeline judges with the method profile.
- **12 live disagreements**, e.g.:

  | Method | Criterion | qc_rules.json | Method profile |
  |---|---|---|---|
  | all three | calibration R² min | 0.995 | 0.99 |
  | FDA | CCV recovery | 70–130 % | 72–128 % |
  | all three | S/N quantitation min | 10 | 3 |
  | FDA | ion ratio tolerance | 20 % | 30 % |
  | EPA 1633A | ion ratio tolerance | 20 % | 50 % |
  | FDA | RRT tolerance | 5 % | 1 % |
  | EPA 537.1 | absolute RT tolerance | 0.1 min | 0.05 min |
  | (Calibrations page) | cal point % deviation | 25 % (`qc_types.CAL`) | 20 / 30 / 30 % |

- Only the rule **toggles** in that file are still read by the pipeline.

### C2. Two project-override systems (high, but cheap now)
- Projects page "criteria" (7 keys + EIS) → `ruleset.py` project tier →
  `resolved_criteria_store`.
- Project Specs page (§70) → `project_specs.py` → the same per-batch file's
  `profile_patch`.
- Both can override, for example, Dup RPD and the CCV window. Which wins
  depends on the order the worker applies them.
- **No projects exist today**, so merging loses no data.

### C3. The calibration ladder is still also a code constant (high)
- `analyte_reference.CAL_LADDERS` still decides **how many calibrators the
  Run Builder puts in a run** and the FDA calibration rows in the logbooks
  and analyte list.
- EPA 1633A's constant is 8 levels (0.5–100 ng/mL); its profile is now 9
  levels (0.2–51.2). The run would not match the method's own curve.

### C4. CCV frequency stored twice (medium)
- The editor writes `instrument_verification.ccv.frequency`. That is what the
  Run Builder, the CCV-frequency check and project overrides read.
- `instrument_verification.sequence.ccv_frequency` is not editable, but the
  worker's `sequence_rule()` reads it first.
- The rest of `sequence.*` (blank_at_start, cal_at_start ...) is likewise
  unedited. The Run Builder uses `run_template` instead.
- The only user of `sequence_rule()` is `InjectionSequenceBuilder`, which runs
  only in tests.

### C5. "No labelled standard" has three sources (medium)
- This decides FDA's 40–140 % / RSD ≤ 30 tier.
  - The pipeline uses the **global** reference table (`no_labeled_names()`).
  - The per-method surrogate links own quantification since §54.
  - FDA also has `per_analyte[].no_labeled_std`, a raw-JSON field (display
    names, not keywords) outside the declared sections.
- A lab that links an analyte to its own labelled analog in one method does
  not move it out of tier 3.

### C6. SENAITE spec edits create a hidden override layer (medium)
- Editing a synced AnalysisSpec range in SENAITE writes
  `profile.spec_overrides` (spec_reverse.py).
- The QC engine never reads it, and the method editor never shows it. Core
  range icons and PFAS QC can therefore silently diverge.
- The same sync rewrites every spec on every save (~30 s for EPA 1633A,
  GAPS §80).

### C7. Worker built-in defaults (medium; F5)
- `_DEFAULT_PROFILE_CACHE` is used only if the exported file or a method is
  missing. It then judges with criteria the lab never set: an FDA LCS tier,
  1633A FTS EIS limits, the retired `associated_qc_types`.
- Its docstring claims a per-key fallback that does not happen.

### C8. Dead keys (low)
- `extraction_corrections.salt_factors`: empty; the worker reads
  `salt_adjustment_factors`.
- `spec_overrides`: see C6.
- `sequence`: see C4.
- `associated_qc_types`: in the worker defaults only.
- Migration markers (`low_level_tiers_seeded`, `level_unit`) are harmless. The
  unit marker is real data and stays.

### C9. EIS limits in two tables plus the baselines (low)
- `eis_overrides` (per analyte) and `eis_matrix_overrides` (per matrix group)
  are two tables over one fact.
- `method_baselines` holds the published Table 6 / 8 copy for departure
  comparison.

### C10. The engine's flat CRITERIA were FDA's for every method (high; found during P2)
- `constants.reload_criteria()` was called with no method, so it always built
  from FDA 32-PFAS. The run queue's ion-ratio, S/N and IS-response checks read
  it, so EPA 1633A was judged at ±30 % ion ratio instead of its 50 %, and
  EPA 537.1 (no ion-ratio criterion) at 30 %.

### C11. The Rule Toggles tab edited a second copy of the limits (high; found during P2)
- Rule "parameters" (R² 0.995, CCV 70–130, S/N 10, three ion-ratio tolerances,
  RT 5 % / 0.1 min, IS 50 %) and an Advanced "global defaults" table wrote
  `qc_rules.json`. Only the Calibrations page read them; the pipeline used
  the Calibration & CCV fields. Same fact, two tabs, two values.

## Status (2026-10-02)
- **P1 and P2 done** (GAPS §81); **P3 and P4 done** (GAPS §85); D4 (SENAITE
  specs read-only) done. Every finding C1-C11 is closed.

## Proposed plan

**P1 — make the copies agree, no new decisions** (small)
- C3: the Run Builder and logbooks take the calibrator count and levels from
  the profile; delete `CAL_LADDERS`.
- C4: one CCV frequency (`ccv.frequency`); drop `sequence.*` from profiles and
  defaults; `sequence_rule()` reads `ccv.frequency`.
- C7: the worker refuses (logs and stops the batch) when the file or a method
  is missing, instead of judging with built-in defaults; fix the docstring.
- C8: remove the dead keys with a migration; history records it.
- C6, second half: spec sync skips specs whose range has not changed.

**P2 — one set of criteria** (medium, needs decision D1)
- Calibrations review page reads R², point % deviation and the CCV window
  from the method profile.
- ICV/CCB % limits move into the profile's Calibration & CCV tab, where they
  belong per method. Today they are global.
- Retire `global` / `method_overrides` / the criteria half of `qc_types`.
  Chart presentation (chart type, labels, blank thresholds) stays with control
  charts.
- `qc_rules.json` then holds only rule toggles. Optionally fold those into the
  profile too, leaving one file per method (D2).

**P3 — one project system, one editing surface** (medium, D3, D4)
- C2: keep Project Specs (it covers every declared section). Remove the
  Projects-page criteria editor and the ruleset project tier.
  `project_specs.departures` already states what a project loosens.
- C6: AnalysisSpecs become read-only copies (reverse sync removed), or
  `spec_overrides` becomes a visible, engine-honoured layer.

**P4 — derive instead of store** (medium, D5)
- C5: "no labelled standard" derived per method: an analyte whose linked
  surrogate is not its own labelled analog. Retire
  `per_analyte.no_labeled_std` and the global set for this purpose.
  Prove it the §9 way: the derivation must reproduce today's FDA list exactly
  before the switch.
- C9: one EIS grid (analyte × matrix group).

## Decisions needed
- **D1.** For the 12 disagreements, the method profile's value wins. That is
  what results are judged with today, so no reported verdict changes; only the
  Calibrations page moves.
- **D2.** Rule toggles stay in qc_rules.json, or move into each profile.
- **D3.** Project Specs is the one project mechanism.
- **D4.** SENAITE AnalysisSpecs read-only (recommended), or honour their
  edits.
- **D5.** Derive "no labelled standard" from the surrogate links.
