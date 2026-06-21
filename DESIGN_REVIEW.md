# Design Review — senaite.pfas UI/UX Audit
## 2026-06-18  Opus architecture review (all 9 valid PFAS pages)

Pages reviewed (screenshots at `/tmp/pfas_screenshots/`):
`method_profiles`, `profile_edit_fda`, `profile_edit_1633a`, `qc_type_grid`,
`qc_rules`, `control_chart`, `sample_status`, `egad_config`, `method_wizard`

---

## Critical / High issues

### Issue 1 — Fragmented navigation (CRITICAL)

Each PFAS page carries a different set of top-right links.
A user on the EGAD config page (`← Site Setup`) has no path to Method Profiles,
Control Charts, or Batch Status without going through SENAITE's Site Setup.

| Page | Current top-right nav |
|---|---|
| Method Profiles | `QC Type Grid · Control Charts · Site Setup` |
| Profile Edit | `← Cancel` only |
| QC Type Grid | `← Back to Method Profiles` |
| QC Rules | `← Back · Site Setup` |
| Control Charts | `Site Setup` only |
| Batch Status | `Method Profiles · Control Charts · Client Tracker` |
| EGAD Config | `← Site Setup` only |
| Method Wizard | `→ PFAS Setup` only |

**Fix:** Add a unified `pfas-nav` strip in `pfas_macros.pt` (the shared `page`
macro, just below the SENAITE breadcrumb) with the same 6 links on every page.
The active page gets a visual highlight.

Proposed strip:
```
Method Profiles | QC Type Grid | Control Charts | Batch Status | EGAD Config | Method Wizard
```

Implementation: a `<nav class="pfas-subnav">` block in the `pfas-macros.pt`
`page` macro, using a `pfas_active_view` variable set by each view.
A `<tal:link>` loop over a Python list of `(label, url_name)` tuples; if
`url_name == pfas_active_view` add the `active` class.

---

### Issue 2 — QC Rules page mixes too many concerns (HIGH)

`@@pfas-qc-rules` puts five conceptually distinct things on one vertical scroll:

1. Global instrument criteria (CAL, CCV, ICV, LCS, LFB, MB, MxB sections)
2. Matrix Adjustment Factors
3. Per-method rule toggle grid (method × rule, on/off pills)
4. Per-method limit overrides (tabbed by method)
5. Raw JSON editor (at the very bottom — "break glass" escape hatch)

This causes visual overload. The JSON editor is especially dangerous — a manager
who scrolls to the bottom may accidentally edit raw JSON instead of using the
structured fields above.

**Fix:** Two tabs within `@@pfas-qc-rules`:

- **Tab A — Rule Configuration:** items 1, 3, 4 (global criteria + per-method
  toggles + per-method overrides). This is the everyday-use tab.
- **Tab B — Corrections & Advanced:** item 2 (Matrix Adjustment Factors) and
  item 5 (JSON editor, wrapped in a `<details>` disclosure with label
  "Developer — Raw JSON (caution: overwrites UI settings)").

Use the same CSS tab pattern already in EGAD Config, but fix the JS-timing
default (see Issue 3 below).

---

### Issue 3 — EGAD config tab content blank on load (MEDIUM)

The EGAD Config page CSS-hides all tab panels and relies on JavaScript to show
the active one. The default "Lab Settings" panel content is invisible until JS
fires. On slow connections or in screenshots, the page appears blank.

**Fix (minimal):** Give the first `<div class="tab-panel">` the `active` class
server-side in the Chameleon template so it starts visible. The CSS already
has `.tab-panel.active { display: block }`. No JS change needed — JS toggling
other tabs still works.

```xml
<!-- In egad_config.pt, the first tab panel: -->
<div id="tab-lab" class="tab-panel active">
```

All other panels remain `class="tab-panel"` (hidden by default).

---

## Medium issues

### Issue 4 — Save button buried mid-page on Profile Editor (MEDIUM)

The "Save & Export to Worker" button on `@@pfas-method-profile-edit` appears
between the Instrument QC Criteria accordion section and the Sample Prep &
Corrections section — mid-way down the page. A user editing Spike Levels or
Extraction Stages (both below the save button) must scroll back up or all the
way down to save.

**Fix:** Add a sticky save bar at the top of the form:
```html
<div style="position:sticky; top:0; z-index:100; background:white;
            border-bottom:1px solid #e0e0e0; padding:8px 16px;
            display:flex; align-items:center; gap:12px;">
  <strong style="font-size:13px;" tal:content="view/method_label">FDA</strong>
  <span style="font-size:12px; color:var(--s-secondary);"
        tal:content="string:Last saved: ${view/last_saved}">Last saved: never</span>
  <button class="btn-primary" type="submit" style="margin-left:auto;">
    Save &amp; Export to Worker
  </button>
</div>
```
Keep the existing button at the bottom of the form as well.

---

### Issue 5 — Control chart failures have no call-to-action (MEDIUM)

Database Summary shows `CCV: 852 (23)` with the 23 in red, but clicking the
failure count does nothing. Users can't drill into which analytes failed or when.

**Fix:** Wrap each failure count in a link that pre-selects the filter:
```html
<a href="?qc_type=CCV&show_failures=1">(23)</a>
```
In `controlchart.py`, read `show_failures` from `request.form.get(...)` and
filter `chart_data()` to failed points only. Add a "Failures only" indicator
banner above the chart when this filter is active.

---

## Low issues

### Issue 6 — Method Wizard has an orphaned in-progress session (LOW)

The wizard page shows "(unnamed) — 0 of 9 steps" with a Resume button but no
Delete option. This is almost certainly a test session that was never completed
or abandoned.

**Fix:** Add a trash/delete button next to each in-progress session:
```
Resume →  |  Delete ✕
```
POST to `?action=delete_session&session_id=xxx`. Auto-purge sessions older than
30 days that remain at step 0 (never started).

---

### Issue 7 — `@@pfas-lims-setup` returns 404 (LOW)

Several pages have "Site Setup" links. Some point to `@@lims-setup` (works);
at least one context produces `@@pfas-lims-setup` which returns a 404 because
no such view is registered.

**Fix (option A):** Register `@@pfas-lims-setup` as a redirect to `@@lims-setup`.
**Fix (option B):** Audit all PFAS templates for `@@pfas-lims-setup` references
and change them to `@@lims-setup`.

---

## Integration gaps

### Gap A — Profile editor and QC Type Grid are disconnected

The Method Profile editor has an "INSTRUMENT QC CRITERIA" accordion section for
Calibration, CCV, IS Response, etc. But the *existence* of these QC type entries
is controlled by the QC Type Grid — a user must check "LFSMD" in the grid before
LFSMD criteria in the Profile editor do anything. There is no callout linking the
two.

**Fix:** Add an info box at the top of the Instrument QC Criteria accordion:
```
ℹ️ QC types must be enabled in the QC Type Grid before criteria here
   take effect. → Open QC Type Grid
```

### Gap B — New Method Wizard does not include QC Type Grid in its steps

The wizard (9 steps, Step 5 = Profile) opens the Method Profile editor in a new
tab but does not link to the QC Type Grid. A method created via the wizard will
have no QC types enabled until the analyst separately visits the grid.

**Fix:** Insert a "Step 5a — Configure QC types" between the current Step 5
(Profile) and Step 6, with a direct link to `@@pfas-qc-type-grid?method=<id>`.
Mark it complete when the method has at least one QC type enabled.

### Gap C — No "test export" button in EGAD config

EGAD Config has Lab Settings, Methods, CAS numbers, Qualifiers, and QC Types
sections, but no way to generate a preview EDD from a real batch to verify the
config is correct before go-live.

**Fix:** Add a "Generate Test EDD" button on the Batch EDDs tab. It should:
1. Find the most recent verified batch across all methods
2. Generate an EDD CSV (no email, no attachment — open in browser as download)
3. Show any validation errors (missing CAS, unrecognised qualifier codes, etc.)
   inline before generating the CSV

### Gap D — Batch Status has no EDD export path

From the Batch Status view, you can see a batch is at Stage 5 (Report Published)
but there is no "Export EDD" link or button. The analyst must navigate separately
to EGAD Config → Batch EDDs.

**Fix:** Add an "Export EDD →" button in the Stage 5 row for each published
batch. Link to `@@pfas-egad-config?tab=batch&batch_id=WS-XXXX`.

### Gap E — No connection between Batch Status and Control Charts

The batch tracker shows which worksheets are at Stage 4 (QC Review), but there
is no link to the control chart for the batch's method. An analyst reviewing
batch WS-0003 has no one-click path to see if CCV trends are clean for EPA_1633A.

**Fix:** Add a "Charts →" link in the Stage 4 row that opens
`@@pfas-control-charts?method=EPA_1633A` (or whatever method the batch uses).

---

## Design principles to maintain

1. **Method-scoped everywhere.** Every list (analytes, QC types, charts) must
   scope to the current method. Global lists are a defect (see §9.4 in CLAUDE.md).

2. **No hidden state.** If a QC type is disabled because it's not in the grid,
   say so visibly ("LFSMD is not enabled for this method — go to QC Type Grid").
   Never silently suppress a section.

3. **SENAITE colour tokens.** All custom CSS must use the `:root` token palette
   from `senaite.core.css`. No hand-picked hex colours. Tokens confirmed:
   `--s-primary: #428aaf`, `--s-text: #293333`, `--s-border: #dee2e6`.

4. **Python 2.7 in-Plone.** No f-strings, no pathlib, no type annotations in
   any `.py` file under `src/`. The worker (`pfas_pipeline/`) may use Python 3.

5. **Accordion-first for long editors.** The Method Profile editor's collapsible
   accordion approach is correct — keep it. Start all sections collapsed except
   the first (Method Information).
