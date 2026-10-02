# Reuse review: existing tools instead of our own code (2026-10-02)

Scope: the whole codebase (~64 k lines of Python, plus templates and
JavaScript). For each piece of generic plumbing: is there a well-tested
tool, in SENAITE/Plone or outside, that does the job? Lab logic (QC rules,
tiers, method criteria, traceability) is ours by design and out of scope.
Plans need sign-off (CLAUDE.md §8). Constraints: GPLv2 (MIT/BSD/ISC fine,
Apache-2.0 and GPLv3 not), Python 2.7 in the add-on, Python 3.12 in the worker.

## Verdict

The code already leans on good tools where it matters: pandas for instrument
files, Playwright for CoA fetching, Chart.js, ZXing, Tesseract, JsBarcode,
qrcode, WeasyPrint via senaite.impress. What remains is **four replacements
worth doing, two of them correctness fixes**, two internal duplicates of the
kind this project keeps removing, and a list of tools considered and rejected
with the reason.

## Recommended

### U1. Extraction logbook PDF: ReportLab → WeasyPrint (high; a dead feature)
- `@@pfas-extraction-pdf` builds the PDF with ReportLab, which is **not
  installed** in the SENAITE container, so the view returns HTTP 500 ("ReportLab
  is not installed") at the end of every guided extraction.
- WeasyPrint is already installed (senaite.impress uses it; so does our
  settings report). Rewrite the ~350 lines of ReportLab layout as one page
  template rendered by WeasyPrint, styled with the shared print CSS.
- Removes a dependency we could not install for Python 2.7 anyway.
- Proof: render a real completed extraction session; compare fields to the
  session data line by line.

### U2. Calibration curve maths on the Calibrations page (high; correctness)
- **Correction after measuring (2026-10-02):** on the FDA and EPA 1633A ladders
  the old solver and bisection were accurate (~1e-13 against numpy); the
  numerical-fragility risk below was overstated. The real defect was R²: up
  to 0.076 away from the weighted R² (a forced-origin 1/x² curve), and the
  old code ignored "force through origin" for quadratic fits.
- Hand-written JavaScript: weighted linear fit, quadratic fit by **Cramer's
  rule** (numerically fragile for ranges like 0.039–20 ng/mL), back-calculation
  by **60-step bisection** (a quadratic has a closed-form inverse), and
  **R² computed unweighted even for 1/x and 1/x² fits**.
- Replace the solver with **ml-matrix** (MIT, jsDelivr): weighted least squares
  via QR decomposition for linear and quadratic, closed-form inverse for
  back-calculation.
- **Decision needed (D-U2):** weighted or unweighted R² for weighted fits.
  Instrument software (SCIEX OS, MassHunter) reports the weighted one; ours
  currently differs from the instrument for every weighted curve.
- Proof: refit the 36 stored calibrations; the linear unweighted results must
  match to 1e-9, and the weighted R² must match the instrument's reported r².

### U3. Drag-and-drop: hand-rolled HTML5 → SortableJS (medium)
- Run Builder sequence and the method editor's drag lists use raw HTML5 drag
  events, which **do not work on touch screens** (bench tablets).
- **SortableJS** (MIT, 1.15) gives touch support, keyboard-safe reordering and
  animation; our code keeps only the "on reorder, write the order" callback.
- Proof: the same orders saved before and after; manual check on a touch
  device.

### U4. Chart limit zones: custom plugin → chartjs-plugin-annotation (low)
- Calibrations and control charts draw limit bands with a hand-written
  Chart.js plugin (`zoneBg`) plus an unused limit-line helper; Chart.js is
  loaded in **two versions** (4.4.0 and 4.4.3).
- One Chart.js version, and **chartjs-plugin-annotation** (MIT, 3.x for
  Chart.js 4) for bands and lines.

## Internal duplicates (same principle: one copy)

### U5. The EDD generator exists twice
- `pfas_pipeline/egad_edd.py` (Py3) and `src/senaite/pfas/egad_builder.py`
  (Py2.7) are declared twins ("keep them in sync"). Production uses the add-on
  builder; the worker copy is used only as a command-line preview.
- Make the worker load the add-on builder by path (as it now does for
  calibration_levels.py), or delete the worker copy.

### U6. The QC results database schema is defined in three places
- `pfas_qc_results.db` tables are created by `qc/store.py` (add-on),
  `pfas_pipeline/seed_calibrations.py` and `pfas_pipeline/injection_store.py`,
  each with its own `ALTER TABLE` patch list (18 between them).
- One shared, pure schema module both processes load, with migrations
  numbered by SQLite's `PRAGMA user_version`. No migration library fits both
  Python versions under our licence (Alembic needs SQLAlchemy on Py3; yoyo is
  Apache-2.0).

## Fix in our own code (no suitable library)

### U7. Westgard rules: keep ours, fix it
- No maintained package exists; the one SPC library (pyspc) is GPLv3 and
  stale.
- Defect: the loop starts at index 1, so the **first point is never checked**
  against 1-2s / 1-3s.
- Note: R-4s is implemented as "adjacent points ≥ 4 SD apart"; the classic
  definition is "one above +2 SD and one below −2 SD". Equivalent in most
  cases; say which the lab uses (D-U7).

### U8. MDL t-values (low; not wired yet)
- `calculate_mdl` uses a typed t-table that stops at n = 20 and reuses n = 20
  beyond it, overstating the MDL. It has no caller (no MDL study feature).
- When the MDL study is built: compute the one-sided 99 % t quantile with
  **SciPy** (BSD) in the worker, or extend the table from 40 CFR 136 App. B.

## Considered and not recommended

| Area | Tool | Why not |
|---|---|---|
| 45 tables on PFAS pages | senaite.app.listing | Static tables with no sort/filter need; a React listing per page is heavier than what it replaces |
| config_forms framework | z3c.form / plone.autoform | Ours stores JSON sections with stale-save stamps, patches and change history (90 tests); a rewrite risks exactly what those tests pin, for no user gain |
| Facility equipment | SENAITE Instrument certifications | CLAUDE.md §7 puts time-series QC in SQLite; better: link each facility unit to its SENAITE Instrument, not migrate |
| Config diff / project patches | jsonpatch, dictdiffer | Our diff treats "missing" and "None" as the same, which the no-op save audit depends on; RFC 6902 does not |
| Unit conversion | pint | No Python 2.7 release in use; the table is 11 lines |
| Date parsing | python-dateutil | Instrument dates are parsed with explicit formats on purpose; a guessing parser could swap day and month |
| Sig-fig formatting | sigfig etc. | 30 lines, tested, no exponent output required |

## Maintenance notes (no replacement, just upkeep)
- tesseract.js is pinned at v2 (current v5); @zxing/library 0.19 is superseded
  by @zxing/browser. Upgrade when the reagent scanner is next touched.

## Status
- 2026-10-02: U1, U2, U7 done (GAPS §82). D-U2 decided: fit, weighting and
  origin are selectable per curve and R² follows the chosen weighting. D-U7
  decided: Levey-Jennings by default, Westgard as a view, warnings dismissible
  and points removable (DECISIONS 2026-10-02).

## Decisions needed
- **D-U0:** which of U1–U8 to do, and in what order. Recommended: U1, U2,
  U7, U5, U6, U3, U4, U8.
- **D-U2:** weighted or unweighted R² for weighted calibration fits.
- **D-U7:** R-4s definition.
