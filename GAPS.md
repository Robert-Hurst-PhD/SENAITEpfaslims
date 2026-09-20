# Gap register — senaite.pfas

What is verified, what is broken, and what is configured but never exercised.
Every entry here was established by running the code or querying the running
instance, not by reading it.

Re-verify with:

**Run it as ONE shell invocation.** The exports are not decoration: without
them four files fail in ways that look like real regressions and are not —
FDA drops to tier 2 (no `tight_matrices`), `deer muscle` stops resolving (no
matrix aliases), `br-PFOS` vanishes (no isomer summation) and `lfsm_low` goes
undetected (no spike levels). Four unrelated-looking failures with one shared
cause is the signature. See §16.

```bash
cd "$(git rev-parse --show-toplevel)" && \
export PFAS_PROFILES_PATH="$PWD/data/qc/method_profiles.json" && \
export PFAS_ALLOW_LEGACY_VENDOR_MAP=1 && \
for t in tests/*.py; do echo "=== $t"; python3 "$t"; done && \
python3 tools/audit_configurable.py --profiles data/qc/method_profiles.json && \
python3 tools/generate_synthetic_runs.py --out /tmp/synth --list
```

Last updated: 2026-09-19 — 19/19 test files pass, audit DEAD 0 / UNREACHABLE 0
/ SPLIT 0, 18 runs planned / 0 skipped.

---

## 1. Detection — verified by known-answer testing

`tools/generate_synthetic_runs.py` builds a run per method × matrix with
deviations deliberately injected; `tests/test_fault_injection.py` asserts the
flags raised equal the manifest, catching **misses and false positives**.

| Injected deviation | Detected as | Disposition |
|---|---|---|
| CCV recovery outside window | `ccv` flags | **blocks** (control material) |
| Calibration r² below `r2_min` | `calibration` flags | **blocks** |
| Blank above reporting limit | failing QC **result**, not a flag | **blocks** |
| Surrogate suppressed in a sample | `is_response` flags | qualifies `[M]` |
| Matrix spike recovery low | `lfsm` (+ `lfsmd`, real chemistry) | qualifies `[M]` |
| Spike/duplicate RPD breach | `lfsmd` flags | qualifies `[P]` |
| Ion ratio out on one analyte | `ion_ratio` flags | qualifies `[NC]` |
| Signal-to-noise below minimum | `sn` flags | qualifies `[J]` |
| **Clean run** | **zero flags, all 18 combinations** | — |

**A clean run raises nothing across all 18 method × matrix combinations.**
Without that baseline the detection results would be meaningless — anything can
"detect" a fault if it flags everything.

---

## 2. Fixed this cycle — each had shipped and did not work

| # | Defect | Evidence |
|---|---|---|
| A1 | Review checks matched flags on the **display string**. Wiring the profiled checks changed those strings, so calibration, r², CCV and RT reported `AUTO_PASS`. | 10 + 10 + 20 checks passing a run carrying **326 flags**. Now `AUTO_FAIL ×10`, `×10`, and RT 17 pass / 3 fail. |
| A2 | The "hold the report" path was inert **three ways** — an `active`-only SQL filter, a qc_type list excluding gap rows, and a `run_date` format mismatch. Fixing any one alone still yielded nothing. | Gate now reports *"1 result(s) could not be evaluated"*. |
| A3 | The QAO deviation was unreachable **three ways** — a `NameError` from calling a bound method bare (swallowed), gaps sourced from the cells A2 hid, and a registry key neither reader used. | `DEV-2026-003` filed and visible in **both** readers. |
| A4 | `is_check_profiled` was a dead twin of live code. | Deleted. |
| B | `classify_injection` defaulted to `Sample`, so `MxB`, `LRB`, `LFB` and `MB-01` were not recognised as control material, and `Dup-01` became `LFSMD`. | 23-case classification test. |
| C | The **watcher passed no method, matrix, batch id or pedigree** — every automated run silently lost the matrix factor, salt correction, dilutions and spike evaluation. | Sidecar and explicit routes now give an identical summary digest; a real file dropped in the watched directory pushed **224/224**. |
| E2 | EGAD CAS was built from a 34-entry FDA-era overlay, so **13 of 40 (1633A) and 2 of 18 (537.1) analytes had no CAS** — BLOCKING — while all 15 had valid CAS in the master table. | 0 BLOCKING across all three panels. |
| E3 | `egad_publish` stored an unsubmittable EDD and only logged, while the other two exits refused. | Now refuses and stores nothing. |
| E5 | Qualified release existed but nothing consumed it. | Gate reports *"released with 26 qualified result(s) [M]"*; 45 analyses stamped; CoA carries the statement. |

Two claims I reported that testing **disproved** — recorded so they are not
repeated:

- *"Every publish silently stores no reviewer snapshot."* False. Snapshots were
  identical (934,535 bytes) before and after the fix; `snapshot_for_publication`
  renders the body view, which never calls the missing `render_stamp`. Only the
  impress-rendered reviewer PDF was broken.
- *"A misclassified blank is reported as client material."* Too strong. The push
  requires a matching SENAITE sample. The real harm was quieter: its
  contamination was never judged, it was not used for `< LOD` subtraction, and
  under qualified release its failures would have been excused as matrix effects.

---

## 3. Open — configuration

**17 of 18 method × matrix combinations cannot evaluate a matrix spike**, and
**13 of 18 report on the extract basis** because no matrix factor is set.

| Method | Matrices | Matrix factor | Spike level | Notes |
|---|---|---|---|---|
| FDA_32PFAS | Animal Feed | 2.0 | **set** | the only fully configured combination |
| FDA_32PFAS | Eggs, Fish, Meat, Milk | 0.5 | none | spike required before LFSM can be judged |
| FDA_32PFAS | Aquatic Tissue | **none** | none | |
| EPA_537_1 | 3 matrices | **none** | none | profile still `_seeded: True` — never edited by a human |
| EPA_1633A | 9 matrices | **none** | none | acceptance is a single placeholder tier, 40–130, `verify_against_method: true` |

Also open:

- ~~**`EPA_537_1.surrogate_map` is empty**~~ — **fixed 2026-08-06, see §9.**
  `surrogate_is_chain` remains absent on both EPA methods and is **deliberately
  left unset**: it needs the injection IS each surrogate quantifies against,
  `INTERNAL_STANDARDS` carries no such column, and `surrogate_is` is empty for
  both. Asserting one would fabricate a regulatory value (§8) — EPA 537.1
  quantifies by isotope dilution against the labelled analog, not against one
  shared injection standard. A lab must enter it from its method copy.
- **Spike units vs result units.** A spike recorded in `ppt` against results in
  `ng/g` stops LFSM evaluation with an explicit message. Either record the spike
  in result units or configure the conversion.
- **FDA `MxB` is `enabled: false`** — matrix-blank QC is off.
- 1633A's empty `tight_matrices` silently inherits the hardcoded FDA trio via
  `spec_sync.py:142`; harmless only because none of its matrices are in it.

---

## 4. Open — code

| Gap | Where | Effect |
|---|---|---|
| ~~**Holding time is a manual checkbox**~~ | `data_review.py` | **Fixed 2026-08-06** — see §7. |
| Publication is not gated on the review | no guard registered | A sample can publish while its worksheet checklist fails. **Decided: warn and record**, not block — the entry now carries `review_state`. |
| ~~`qc/control_chart.py` is entirely dead~~ | — | **Removed 2026-08-07.** 584 lines, zero importers; `browser/controlchart.py` implements the same six Westgard rules (1-3S, 1-2S, 2-2S, R-4S, 4-1S, 10X) inline. Only `render_to_png_bytes` was unique, and it had no caller either. Control-chart page still renders. |
| `calculate_mdl`, `single_transition_confirm_needed` | `qc_engine.py` | Still zero call sites — **kept deliberately, now labelled NOT WIRED.** `single_transition_confirm_needed` implements FDA §10.2(4) (PFBA/PFPeA positives need LC-HRMS confirmation) and its docstring falsely claimed the run queue used it; that claim is corrected. Deleting either would erase the only record that a real obligation is unmet. **See §12.** |
| ~~`lfsm_check` / `lfsmd_check`~~ | — | **Removed 2026-08-07** as dead twins of the inline `run_queue` implementation (§1.3: a merged twin must be removed, not left). |
| `QCResultStore.add_results_bulk` / `add_result` / `flag_for_reanalysis` / `void_batch` | `qc/store.py` | Zero external callers; the Py3 pipeline writes raw SQL. So `voided`, `flagged_reanalysis` and `superseded` are read by Data Review and never produced. |
| `sn_min` toggle defaults **OFF** | `qc/rules.py:90,95` | Signal-to-noise is not evaluated for FDA_32PFAS or EPA_537_1. |
| `ccv_frequency`, `mdl_check` toggles | `RULE_LIBRARY` | Honoured nowhere. |
| ~~`lfsm_recovery`, `lfsmd_rpd` toggles~~ | `run_queue` | **Fixed 2026-08-06** — they now gate on the method profile's `qc_acceptance[QC].enabled`, the producer that already existed. See §8. |
| `qq_ratio_*_pct` (three knobs) | `RULE_LIBRARY` | `qual_quan_check` still reads one flat value — the per-group knobs (isotopically matched / key / non-iso) are not honoured. The `sn_quan_min` half of this entry is **fixed, see §11**, and the register's framing of it was wrong. |
| ~~Facility QC: eyewash dashboard reads the wrong table~~ | `facility_qc.py` | **Fixed 2026-08-07 — see §10.** The "waste units always show green" half of this entry was **wrong**: there is no `waste` unit type, so that branch was unreachable. The real catch-all defect was different and is also fixed. |
| 96 hardcoded lab values remain | mostly module tables | None decides a reported result. |

---

## 5. First end-to-end release — what it proved and what it exposed

On 2026-08-06 WS-0005 was driven through the full ISO 17025 §7.8.4 review and
one sample was published. This had never happened before; two entries that
previously sat here as "never exercised" are now closed, and running it exposed
two defects that only a real release could reveal — both since fixed.

**Closed:**

- **A sample reached `verified` and published.** WS-0005 → `to_be_verified` →
  `verified`, 288 analyses verified, `FEED-0002` → `published`. The 8 previously
  published samples were demo data.
- **The CoA renders the qualified release.** The certificate carries the QC
  Qualifications section with code `M`, its client-facing statement, and the
  affected native analytes (`4:2FTS, 6:2FTS, PFBA, PFHxDA, PFTeDA`) — resolved
  through the surrogate map, so it names the natives the client sees rather than
  the labelled compound.
- **The controlled-publication entry is written and complete.** `FEED-0002-R1`,
  `qc_snapshot: ok`, and `review_state: "qualified: 26 result(s) released with a
  qualifier"` — the publication carries the state of the review that authorised
  it.
- **The full client flow produces a real artifact.** `FEED-0003` was taken
  through the intended order — render at prospective R1 → store → transition →
  log R1 — via impress `save_reports`. A **61,635-byte PDF** is stored as
  `arreport-4` against the sample, and `FEED-0003-R1` is registered with
  `qc_snapshot: ok`. The certificate a client would actually receive carries
  **5 qualifier markers beside the values** (`BLoQ [M]`, `2.466 [M]`,
  `117.423 [M]`, `0.008 [M]`, `0.130 [M]`) plus the Qualifications section
  naming the same five analytes — confirmed by extracting the text back out of
  the stored PDF, not from the HTML it was rendered from.

**Exposed by the run:**

| # | Defect | Evidence |
|---|---|---|
| G1 | **The Data Review release path had never worked.** `doActionFor(ws, "submit")` failed with *"No workflow provides the '${action_id}' action"*: the pipeline pushes results without submitting them, so all 288 analyses sat in `assigned`, and the worksheet's `submit` guard only opens once its analyses are submitted. The same was true of `verify`, which is available on the analyses and not the worksheet. **Fixed** — both handlers now cascade to the analyses first. | WS-0005 reached `verified`; without the cascade no worksheet in this system could ever have been released. |
| G2 | **The per-result qualifier codes never reached the certificate.** `_stamp_qualifier_remarks` writes `QC: M` onto each affected analysis, justified in its own docstring by *"Remarks is the one per-analysis field core already prints"*. **Core prints no such thing.** `senaite/impress/.../results.pt` has no remarks cell at all, and `remarks.pt` renders only SAMPLE-level `model.getRemarks()` — a different field from the one being stamped. 14 analyses on `FEED-0002` carried the stamp; the rendered certificate contained none of them. **Fixed** — see below. | Rendered twice before the fix: default options (57,345 bytes) and **with `show_remarks: true`** (57,411 bytes). `QC: M` absent from both — so this was not an option left switched off, it was an unreachable field. |

G2 was the project's recurring defect shape once more: **a fact recorded
correctly in one place and never carried to where it is used.** The blanket
statement in the Qualifications section had always survived, so the client was
told the release was qualified and which analytes were affected — but could not
see the code beside the number, which is what the design called for.

**How G2 was fixed, without forking core.** `results.pt` formats each value
through `model.get_formatted_result(analysis)` and takes its models from
`view.collection` — so the formatter is reachable by supplying our own models,
leaving the core template alone (CLAUDE.md §6C).
`PublishView.get_report_view_controller` queries a **three-way** multiadapter on
`(context, model, request)` before falling back to impress's own two-way one;
impress registers no three-way adapter itself and its comment says the form
exists "to allow 3rd party overriding with a browser layer". `browser/
reportview.py` registers there, scoped to `ISenaitePFASLayer` — unlike the
`ISuperModel` adapter, which is registered `for="*"` with no request and could
only have been replaced site-wide.

The marker format now lives once, in `qc_qualification.REMARK_PREFIX`, with
`format_remark_codes` writing and `parse_remark_codes` reading. The stamp — not
a recomputation at render time — remains the record, so a certificate cannot
drift from the review that authorised it. `tests/test_qualifier_stamp.py` pins
the round trip, that unrelated remarks (`SUR`, `N.C.`, `br-PFOS:(QQ)`, all
present on FEED-0002) never become a qualifier, that no other module formats the
marker inline, and that the reader stays registered.

Verified on the re-rendered certificate: **5 markers, on exactly the five
natives the Qualifications section names** —
`4:2 FTS BLoQ [M]`, `6:2FTS 1.006 [M]`, `PFBA 104.432 [M]`,
`PFHxDA 0.032 [M]`, `PFTeDA 0.189 [M]` — and 10 markers across two samples
rendered together. Byte-identical output from **all four publish entry points**
(sample, client folder, samples listing, portal root), and the decoded document
grew by exactly the 708 bytes the markers and their stylesheet account for, with
every section count unchanged against the pre-change baseline.

One trap worth recording, because the first version of this fix fell into it:
the view accepts `context` from the three-way adapter and must **discard** it.
Core's `ReportView.__init__` sets `self.context = api.get_portal()`, and Five
binds TAL `context` to `view.context` — which the CoA passes to every core
section and to `@@pfas-coa-attestation`. Assigning the traversed object instead
made the certificate render **empty from the client folder and the samples
listing** while still rendering correctly from a sample, i.e. broken at the two
entry points production actually uses and working at the one being tested.

Still never exercised:

- **EGAD EDD export.** The publish subscriber is registered and fires, but exits
  at `is_egad_enabled(client_obj)` — KCP is a food client, not a Maine state
  agency, so no EDD is correct here. Neither the generate nor the refuse branch
  has run from a real publish.
- `tests/` covers the pipeline well and the add-on barely: no test exercises
  `data_review`'s gates, `qc_store`, `control_chart` or `facility_qc`.

---

## 6. What the audit tool cannot see

`tools/audit_configurable.py` reports DEAD 0 / UNREACHABLE 0 / SPLIT 0 — a clean
run is evidence, not proof. Three limits are structural:

1. leaves under an **iterated container** are credited as read;
2. a **self-contained feature** that stores and consumes its own config is
   indistinguishable from an inert one;
3. it only sees keys the exported profile actually contains.

See `docs/ISO17025_DESIGN.md` §6.

---

## 7. Holding time — computed, 2026-08-06

CLAUDE.md §10 calls holding times "a hard acceptance criterion" and names EPA
537.1's 14 days. Nothing computed one. `holding_time_ok` was a checkbox, no
method profile carried a limit, and the only evidence a sample had been
extracted in time was that somebody had ticked a box.

Both dates were **already being recorded and never read together** —
`sample_collection_date` on the Chain of Custody and `extraction_date` on
FM-ENV-252. The recurring shape again: a fact recorded correctly in one place
and never carried to where it is used.

`src/senaite/pfas/holding_time.py` computes it. Imports nothing from Plone, so
the arithmetic is testable outside the container and a test enforces that.

| Verdict | When | Effect on the CoC gate |
|---|---|---|
| `OK` | within the limit | tick still required |
| `EXCEEDED` | past the limit | **blocks, whether or not the box is ticked** |
| `INVALID` | extraction recorded before collection | **blocks** |
| `UNCONFIGURED` | no limit set for this method × matrix | refuse to judge |
| `NO_DATES` | either date missing or unreadable | refuse to judge, naming which |

The checkbox is kept — §10 requires it, and this is additive. What changed is
that a tick can no longer overrule the record.

**Only EPA 537.1 is seeded, at 14 days**, because §10 documents it. FDA and
1633A ship every matrix explicitly `None`: §8 forbids fabricating a regulatory
value, and refuse-to-judge already handles the blank correctly. The limit is
per matrix, edited as a column in Method Profiles → **Matrices & Units**,
alongside the reporting unit and tier-1 flag — one more fact about one matrix.

Ambiguous dates are refused rather than guessed: `03/04/2025` is 3 April or
4 March depending on who typed it, and it decides whether a result is
defensible. Only unambiguous ISO forms parse.

Live-verified on WS-0005 (FDA × Animal Feed, the one worksheet with real data):
unset → `unconfigured`; with a limit set through the real form POST →
`exceeded, 292 days against a limit of 14, blocking`. The test value was then
removed, because 14 days for animal feed is documented nowhere.

### 7.1 Found while verifying it: a partial POST nulls the instrument criteria

The verification POST carried only the Matrices & Units pane. The save handler
writes every instrument criterion **unconditionally** — `_float()` returns
`None` for an absent field and that `None` is stored — so the POST wiped, off
the **live** FDA profile:

```
calibration.point_pct_dev_max            20.0  -> None
confirmation.ion_ratio_tol_pct           30.0  -> None
confirmation.rrt_tol_pct                  1.0  -> None
confirmation.sn_quan_min                  3.0  -> None
confirmation.sn_confirm_min               3.0  -> None
confirmation.require_confirm_ion_check   True  -> False
is_response.vs_ical_avg_min / _max     50/150  -> None
```

plus `tight_matrices` (the 80–120% tier for meat, eggs and seafood) and all six
matrices' aliases. Every one of those decides whether a result passes QC.

All values were restored from a pre-session copy of the export; the profile now
differs from it by exactly the new `holding_times` key, verified key by key.

The codebase already knew this hazard — `matrix_settings_present` guards the
matrix list "so a POST from another pane cannot wipe it", and the recovery
tiers are guarded because blanking them "would stop every run". The instrument
block was simply missed. It is now behind `instrument_verification_present`,
and the same partial POST re-run against the guard changes **nothing**.

`tests/test_profile_form_guards.py` asserts the property structurally rather
than replaying one POST — every marker the handler reads is emitted by the
form, every marker the form emits is honoured by the handler, and the seven
criteria above sit inside the guard. A pane added later is covered without
anyone remembering to.

**The general rule, worth carrying:** on a multi-pane form whose handler
assigns rather than merges, *absent is not "unchanged" — absent is "clear it"*.
Normal use never exposes it, because the real form always submits every pane.

**Live-state check after the restore.** ZODB, the exported profile and the
pre-session copy were compared key by key across all three methods: the only
differences are the new `holding_times` key and `display_analyte_set`, which
`method_profile_store` **derives at export time** from the service-derived
master set (D60) rather than storing — so an empty stored value is by design,
and the exported list the worker reads is byte-identical to pre-session.

---

## 8. QC rule toggles — reconciled, 2026-08-06

There are two switch stores and they own different things:

- **`qc/rules.py RULE_LIBRARY`** — INSTRUMENT-level rules (IS response, RT, ion
  ratio, calibration r², CCV, S/N, MDL). Its own header says so.
- **the method profile's `qc_acceptance[QC_TYPE].enabled`** — EXTRACTION and
  matrix QC (LFSM, LFSMD, MB, LRB, LFB, Dup, MxB), where the limits also live.

`run_queue` gated LFSM and LFSMD on `_rule_enabled(toggles, "lfsm_recovery")`
and `"lfsmd_rpd"` — keys present in **no library, no defaults table and no UI**.
`_rule_enabled` defaults an absent key to `True`, which is the right default but
makes an unreachable key indistinguishable from one a lab deliberately enabled.
So both checks always ran, **and a lab that switched LFSM off in the Method
Profile was ignored**: the switch it was given did nothing, and the switch that
worked did not exist.

They now read `MethodProfile.qc_type_enabled()`, which applies the same flag
`qc_acceptance_rule` already honoured — one definition, on the object that owns
the data.

Live-verified on a synthetic FDA × Animal Feed run with `lfsm_low` injected:

| Profile state | Flags |
|---|---|
| LFSM enabled (as shipped) | **32 lfsm + 32 lfsmd** |
| LFSM disabled | **0** |
| LFSM + LFSMD disabled | **0** |

**A dependency worth knowing:** disabling LFSM alone also silences LFSMD. That
is real — the spike/duplicate RPD is computed *from* the LFSM recovery
(`recovery_pct`, `unfortified_conc`, `spike_value_ppt`), so with LFSM off there
is nothing to compare against. A Method Profile showing LFSMD enabled while it
can never fire is the silent-no-op shape again, so the run now logs a warning
naming the consequence rather than quietly evaluating nothing.

**Not a defect, checked:** `cal_r2` is present in all three tables — an earlier
survey reported it missing because the regex required `"label"` and the entry
reads `u"Calibration r²"`. And `ccv_frequency` / `mdl_check` gate no engine
check, but that is **declared** in `LIBRARY_KEY_TO_ENGINE_CHECKS` as an empty
list with a comment — a documented gap, not a lying switch. What each would
need is in §4.

`tests/test_rule_toggles.py` pins the three-way agreement — library ↔ mapping ↔
every method's defaults ↔ what the engine actually reads — by parsing the AST,
because the first version of the reconciliation matched
`_rule_enabled(toggles, "lfsm_recovery")` inside a *comment describing the fix*
and reported the defect as still present.

---

## 9. Surrogate maps — derived, not hand-copied, 2026-08-06

`qc_qualification.analytes_for_failure` reverses a method's `surrogate_map` to
work out which **natives** a surrogate failure affects. EPA 537.1 shipped with
`surrogate_map: []`, so it fell through to `[analyte]` — and a certificate would
have named `13C4-PFHpA` as the affected analyte, a compound the client never
ordered and never sees, instead of PFHpA.

Which labelled compound quantifies a native is a property of the **analyte**,
not of the method, and was already recorded once in
`analyte_reference.NATIVE_ANALYTES`. FDA and 1633A carried hand-maintained
copies of it in their profiles.

**The evidence this is derivation and not fabrication** (§8 forbids inventing a
regulatory value): the same `derive_surrogate_map()` reproduces both
hand-maintained maps **entry for entry and in the same order** — FDA 21/21,
1633A 25/25 — and a test now asserts it stays that way. Applying it to EPA
537.1 yields 15 entries from its 18-analyte panel.

| Method | Before | After |
|---|---|---|
| FDA_32PFAS | 21 (hand-copied) | 21, derived — identical |
| EPA_1633A | 25 (hand-copied) | 25, derived — identical |
| **EPA_537_1** | **0** | **15, derived** |

Verified live, per method, on a surrogate failure raised against the labelled
compound:

```
EPA_537_1   M4PFHpA   -> PFHpA
EPA_537_1   MPFDoA    -> PFDoA, PFTrDA     (one surrogate, two natives)
EPA_537_1   M8PFOS    -> PFOS
FDA_32PFAS  M8FOSA    -> FOSA
EPA_1633A   M2-6:2FTS -> 6:2FTS
```

### 9.1 The hand-copy had already drifted

Six of the 27 links in `NATIVE_ANALYTES` — the four FTS analytes, FOSA and GenX
— held a **display name** where the other 21 held a keyword
(`"13C8-FOSA"` rather than `"M8FOSA"`). The single consumer does
`_IS_KW_TO_NAME.get(value, "")`, so all six resolved to an **empty surrogate
column** in the FDA profile's `per_analyte` table. Normalised, and a test now
asserts every link names an IS keyword.

The migration `migrations/backfill_surrogate_maps.py` fills only **empty** maps,
so a lab's edit in the Method Profile editor always outranks the default; run
twice, the second run reports nothing to do. Confirmed against the live
instance: `EPA_1633A 25 entries already - left alone`, `FDA_32PFAS 21 entries
already - left alone`, `EPA_537_1 EMPTY -> 15`. The refreshed export differs
from its pre-migration copy by `surrogate_map` on EPA_537_1 and nothing else.

---

## 10. Facility QC — the eye wash dashboard, 2026-08-07

`dashboard_summary()` grouped eye wash stations with the temperature sensors:

```python
if ut in ("refrigerator", "freezer", "room_sensor", "eyewash"):
    reading = latest_reading(u["id"])      # SELECT ... FROM temperature_readings
```

An eye wash station never writes to `temperature_readings`. Every station
therefore reported `no_data` forever — while `save_eyewash_log` was computing
and storing a `passed` verdict (the station runs **and** its water is tepid) that
nothing ever read. The recurring shape once more: recorded correctly in one
place, never carried to where it is used.

Eye wash now reads `eyewash_logs`, and is judged on its own §6.4 cadence:
`out_of_range` when the stored verdict failed, `pending` when the last check
predates today, `ok` only when it passed today.

| State | Reported |
|---|---|
| never checked | `no_data` |
| runs, water tepid, checked today | `ok` |
| water at 40 °C | `out_of_range` |
| station does not run | `out_of_range` |
| passed, but the check is old | `pending` |
| a temperature reading filed against it | `no_data` — it is not consulted |

### 10.1 Two further defects found while fixing it

- **`log_time` is only `HH:MM`, so entries in the same minute tie.** Without an
  `id DESC` tiebreak SQLite returns the first by rowid — so **re-testing a
  station after a failure showed the earlier PASSING entry as current**. The
  first version of this fix had exactly that bug; the test caught it.
- **The `else` branch reported `status = "ok"`.** Every type in `UNIT_TYPES` is
  handled, so reaching it means a type was added with no check — and green
  would hide precisely that. It now reports `no_data` and logs a warning.

### 10.2 The correction to the previous entry

The old register said *"waste units always show green"*. That was **wrong**:
there is no `waste` unit type in `UNIT_TYPES`, so no unit could reach that
branch. Waste is recorded via `waste_logs` against a unit of some other type,
and `waste_logs` has no `passed` column at all — there is nothing for the
dashboard to judge. Whether SAA waste containers should carry a pass/fail
condition is a lab decision, not a code defect; it is not one today.

### 10.3 The subsystem has never held data

`/data/qc/facility_monitoring.db` is **empty** — the schema exists and every
one of its nine tables has **zero rows**, including `facility_units`. So no
temperature, balance, water, waste or eye wash record has ever been entered on
this instance, and none of the §6.4 monitoring the design calls for is
happening yet. The defects above were real but had never had data flow through
them.

`tests/test_facility_dashboard.py` runs against a scratch database via
`PFAS_FACILITY_QC_DB` and never touches the live one; all seven facility pages
were confirmed rendering (HTTP 200) and the live database confirmed still empty
afterwards.

---

## 11. Signal-to-noise — two limits, two questions, 2026-08-07

`sn_quan_min` is the minimum S/N to **quantitate**: below it the peak is real
but the number is an estimate, which is exactly what the `sn` failure type
means — code **J**, statement *"the affected results are estimated"*.
`sn_confirm_min` is the minimum S/N on the **confirmation (qualifier) ion**:
below it the identification is not confirmed, **N.C.**

`constants.py` mapped only the first, into a key named `sn_min`, and **both**
branches of `signal_to_noise_check` compared against it — reporting `(N.C.)`
for both. Two consequences:

- a low quantitation ion was labelled *"not confirmed"* while the taxonomy, the
  qualifier code and the certificate statement all say *"estimated"*;
- the qualifier ion was judged against the **quantitation** limit. On EPA
  1633A — the one method with this check enabled — that is 3.0 against a
  configured confirmation limit of **1.0**, so qualifier ions between 1 and 3
  were failed by a criterion the method does not apply to them.
  `sn_confirm_min` was configured and read by nothing.

Both limits now reach the engine under their own names and each branch uses its
own. An **unconfigured `sn_confirm_min` means the qualifier ion is not judged**
— it does not borrow the other threshold.

**The register's framing of this was wrong** and is corrected here. It said
`sn_quan_min` was "substituting the quantitation threshold for the detection
one", which assumed the check was a detection check. The failure taxonomy says
otherwise: the `sn` check yields J, so the quantitation limit was the right
source for that branch all along. The real defect was the qualifier-ion branch
sharing it, and the verdict string contradicting the code.

---

## 12. Regulatory obligations implemented but never wired

Two functions in `qc_engine` are correct and have **zero call sites**. Both are
kept rather than deleted, and now say so in their own docstrings — deleting
them would erase the only record that a real obligation is unmet.

| Function | Obligation | Why not wired |
|---|---|---|
| `single_transition_confirm_needed` | **FDA §10.2(4)** — a PFBA or PFPeA positive is a single-MS/MS-transition detection and must be confirmed by LC-HRMS (%diff < 20%). | Returns a review-prompt string. Its docstring **falsely claimed "used by the run queue"**; nothing calls it, so the confirmation is never prompted for. Wiring it means adding a review-queue prompt — new behaviour, needing verification against a run with PFBA/PFPeA positives. |
| `calculate_mdl` | MDL per 40 CFR 136 App B. | An MDL comes from a **periodic study over ≥7 replicates**, not from one run, and no such feature exists. The `mdl_check` toggle is declared UI-only for the same reason. The arithmetic is correct and kept for when that study is built. |

This is the same shape as the holding time was before §7: a requirement the
system can state but does not enforce. The difference is that these two are now
labelled at the point a maintainer will read them.

---

## 13. Where this stands — final review, 2026-08-07

**Verification as of this entry:** 144 assertions across 18 test files, all
passing; `audit_configurable` reports DEAD 0 / UNREACHABLE 0 / SPLIT 0; the
generator plans all 18 method × matrix runs with none skipped; a clean synthetic
run raises zero flags on every combination and each injected deviation is caught
with no false positives.

### Closed since the register opened

Detection (§1), the mechanisms that shipped and did not run (§2), the first
end-to-end release (§5), holding time (§7), the rule toggles (§8), the surrogate
maps (§9), the facility QC eye wash (§10), signal-to-noise (§11).

### What still needs to be addressed, in the order I would take it

**1 — Lab data entry, blocking real use.** *Nothing here is a code defect.*
- **17 of 18 method × matrix combinations have no spike level**, so LFSM cannot
  be evaluated for them. FDA × Animal Feed is the only complete one.
- **13 of 18 have no matrix factor**, so results stay on the extract basis.
- **No holding time is configured** for FDA or EPA 1633A (§7). Until a lab
  enters its own, every batch on those methods reports `unconfigured`.
- **EPA 1633A acceptance is one placeholder tier**, 40–130, still flagged
  `verify_against_method: true`.
- **EPA 537.1 has never been edited by a human** — its profile still carries
  `_seeded: True`.

**2 — Decisions only the lab can make.**
- **`sn_min` defaults OFF for FDA_32PFAS and EPA_537_1.** Signal-to-noise is
  therefore not evaluated on two of three methods. Whether that is correct is a
  method question, not a code one — I have not changed it.
- **`surrogate_is_chain` is unset on both EPA methods** (§9). It needs the
  injection IS each surrogate quantifies against; asserting one would fabricate
  a regulatory value.
- **FDA `MxB` is `enabled: false`** — matrix-blank QC is off.
- **Spike units vs result units**: a spike in `ppt` against results in `ng/g`
  stops LFSM evaluation with an explicit message.

**3 — Obligations the system states but does not enforce** (§12).
- **FDA §10.2(4)**: PFBA/PFPeA positives require LC-HRMS confirmation.
  `single_transition_confirm_needed` computes the prompt; nothing calls it.
  This is the most consequential remaining code gap.
- **MDL** has no periodic-study feature; `calculate_mdl` is correct and unused.
- **`ccv_frequency`** is declared UI-only: nothing verifies that a run actually
  carried a CCV every N injections. Implementing it needs one definition of
  which injections count toward the interval — the add-on has one
  (`run_builder._noncount_codes`, RefDef-driven) and the pipeline has none.

**4 — Smaller code gaps.**
- **`qq_ratio_matching_pct` / `_key_pct` / `_non_iso_pct`**: three UI knobs,
  `qual_quan_check` reads one flat value.
- **`water_qc_logs` orders by `log_time` only** — the same `HH:MM` tie that
  showed a stale PASS for eye wash (§10.1). No data yet, so no failing case.
- **`QCResultStore.add_results_bulk` / `add_result` / `flag_for_reanalysis` /
  `void_batch`** have no external callers; the Py3 pipeline writes raw SQL. So
  `voided`, `flagged_reanalysis` and `superseded` are read by Data Review and
  never produced.
- **96 hardcoded lab values** remain, mostly module tables. None decides a
  reported result.
- **Publication is not gated on the review** — decided: warn and record, and
  the publication entry now carries `review_state`.

**5 — Never exercised.**
- **The EGAD EDD** has never run from a real publish. The subscriber fires but
  exits at `is_egad_enabled()`; KCP is a food client, not a state agency.
  Neither the generate nor the refuse branch has been seen end to end.
- **Facility QC holds no data at all** (§10.3) — nine tables, zero rows,
  including `facility_units`. None of the §6.4 monitoring is happening.
- `tests/` covers the pipeline well and the add-on unevenly: `data_review`'s
  gates and `qc_store` still have no direct tests.

### The pattern worth carrying forward

Almost every defect in this register is one of two shapes, and both are
cheap to look for:

- **a fact recorded correctly in one place and never carried to where it is
  used** — the qualifier codes, the holding-time dates, the surrogate map, the
  eye wash verdict, `sn_confirm_min`;
- **a consumer with no producer, or a producer with no consumer** — the
  `unevaluated` status, the LFSM toggle keys, `single_transition_confirm_needed`.

The audit tool catches the second shape for method-profile keys only. The first
shape has no tool; it was found each time by running the thing end to end and
checking whether the value arrived.

---

## 14. Check-in — 2026-09-18

Six weeks since the last commit (8819e24, 2026-08-07). Working tree clean.
**This entry is a static read of code and documents — Docker Desktop is down,
so nothing below was re-verified against a running instance.** The stack must
not be brought up on the system daemon to check: that creates empty volumes and
a bare Plone site (see the infra restore procedure).

### 14.1 Repository risk — the top line, and not a design question

`d63-state-edd-profiles` @ 8819e24 carries everything from mid-July through
2026-08-07: D63 state EDD profiles, D64 QA sign-off attestation, D65 CoA
controlled publication, the Run Builder template work, the visual logbook
builder, the real-instrument E2E fixes, the first sample ever verified and
published, and all eight §7–§11 closures. `master` is still at D62 (015fc86).
No branch has an upstream — `git branch -vv` shows no remote tracking at all.

Six weeks of the highest-value work in this project exists on one disk, in one
branch, unmerged and unpushed. Merging and establishing a remote are both
decisions for the lab, not for me; this entry records the exposure.

### 14.2 Design conformance (CLAUDE.md §5/§6) — a previously unmeasured axis

This register has always been a QC-correctness instrument. The workspace and
layout architecture had never been audited against the spec. Doing so now:

| §6A site-wide sidebar | Status |
|---|---|
| One persistent sidebar on every page | **built** — `PFASSidebarManager` overrides core `SidebarViewletManager` by layer specificity |
| All seven accordion groups | **built** — Operations, QC & Methods, Bench, Facility QC, Instruments & Import, Reporting, Configuration all present in `pfas_sidebar.pt` |
| §6C: every core override documented in DECISIONS.md with upgrade fragility | **satisfied** — all three overrides (`lims-setup`, `senaite.sidebar`, `@@email`) carry inline upgrade notes *and* DECISIONS.md entries |
| §6C: Client Tracker carve-out, no sidebar, no chrome | **satisfied** — `templates/tracker.pt` pulls neither `render_sidebar` nor `pfas_macros` |

**§6B tabs conversion is effectively complete.** §6B flags itself unfinished
("finish converting the remaining collapsible-section pages to tabs"); that
instruction is now stale. Of 56 templates, only `qcrules.pt` still carries
collapse markup, and it carries tab markup too — one page to inspect, not a
programme of work. (`pfas_sidebar.pt`'s accordion is §6A by design.)

**§5 workspaces are the real divergence: 1 of 10 exists as a workspace.**
Only QC Management has a landing view (`PFASQCManagementView`, an 8-tile grid).
Data Review, Facility QC, Bench, Sample Workflow, Method & Analyte Setup,
Instrument & Import, Reporting & EDD have *pages* in `browser/` reachable from
the sidebar, but no unified role-scoped view over them. `PFASWorkspaceHomeView`
routes each role to a single page, not to a workspace:

```
LabManager/Manager → @@pfas-method-profiles   (a page, not QC Management)
Analyst/Verifier   → @@pfas-data-review
LabClerk           → @@pfas-reagents          (a page, not Bench)
Client             → @@pfas-track
```

So the launcher's Manager landing bypasses the one workspace that does exist.
The finding in one line: **the pages exist; the workspace layer as §5 defines
it does not.** Whether that matters is a lab decision — the sidebar may already
deliver the navigation §5 was reaching for, in which case §5 should be amended
rather than implemented. Three ways to resolve it, none chosen here:

1. Build the remaining workspace landings on the QC Management pattern.
2. Keep sidebar-only navigation and amend §5 to describe groups, not workspaces.
3. Build landings only where a role needs an at-a-glance view (Bench, Data
   Review), leave the rest as sidebar links.

At minimum the launcher should route Manager to QC Management rather than past
it — that one is a plain inconsistency, not a design choice.

### 14.3 What has not changed

§13's ranked list stands unaltered; no code has moved since it was written.
Restating it by **who can act**, since that is what decides what happens next:

- **Only the lab can move these** — §13 items 1 and 2, plus Q-014 (spike
  concentrations per matrix), Q-007 (MassLynx lr-/br- export names), Q-002,
  Q-003. 17 of 18 method × matrix combinations still cannot evaluate LFSM and
  13 of 18 still report on the extract basis because no number has been
  entered. **This, not any code gap, is what blocks production use.**
- **Code work remaining** — §13 items 3 and 4, with FDA §10.2(4)
  (`single_transition_confirm_needed`, computed and never called) the most
  consequential.
- **Never exercised** — §13 item 5: the EGAD EDD end to end, and Facility QC,
  which still holds zero rows across nine tables.

---

## 15. Three-tier criterion resolution — built, tested, unwired (2026-09-18)

`method_baselines.py` and `ruleset.py` are new, additive, and have **zero call
sites**, in the same spirit as §12's `calculate_mdl` and
`single_transition_confirm_needed` — kept and labelled rather than left to be
rediscovered, since §12's own entry exists because one of those two carried a
docstring that falsely claimed a consumer. Neither new module's docstring
claims one; both say plainly that nothing calls them yet.

What is built: `method_baselines.py` declares, per method and criterion key,
the value the PUBLISHED METHOD itself specifies (not what the lab currently
uses), tagged with a comparison shape — `SHAPE_MIN` (a floor), `SHAPE_MAX` (a
ceiling), or `SHAPE_WINDOW` (two-sided, each end judged independently) — and a
citation. `ruleset.py` resolves one criterion through project QAPP ruleset →
lab method profile → that baseline, and reports which tier answered, the
controlled-document provenance for a project-tier answer, and whether the
resolved value CONFORMS to, or DEPARTS from, the baseline (UNKNOWN if no
baseline was ever verified for that key — which is most of them; see below).
`tests/test_ruleset.py` pins the shape taxonomy, the tier fall-through, and
the provenance rules in 25 test functions / 93 assertions; all pass under
`python3 tests/test_ruleset.py`.

Only ONE criterion is seeded with a real baseline: EPA_1633A's per-analyte
`eis_recovery` window, from EPA 1633A (EPA 820-R-24-007, December 2024, Tables
6 and 8) — the same data QUESTIONS.md Q-004 closed on 2026-06-19 after
checking it against the official PDF. Every other criterion this project
tracks (`cal_r2_min`, `dup_rpd_max`, `ccv_recovery`, and anything else a later
phase registers) resolves fine through the project/lab tiers but reports
`UNKNOWN` conformance, because nothing else in this system has a closed,
citable verification against method text — Q-005 (`cal_r2_min`) was closed as
lab-owned, not method-derived, which is a different answer, not a gap. Adding
a new baseline means adding a new closed Q-xxx citation first, not a number
that "looks right."

Found while seeding, left alone (both in `data/qc/method_profiles.json`,
read-only, not touched here): EPA_1633A's `qc_acceptance.LFSMD` tier carries
the identical 40/130 recovery window as `LFB`/`LFSM`, which are explicitly
flagged `verify_against_method: true` — LFSMD carries no such flag, which
reads as a placeholder that lost its flag rather than a second verification.
And the out-of-process worker's own `EPA1633AProfile.qc_rules()` (Python 3,
`pfas_pipeline/method_profiles.py`) still returns `verify_against_method=True`
with a "VERIFY against purchased method copy" note on its EIS branch — D62
(2026-07-21) made that intentional for a reason unrelated to Q-004, but it now
sits beside a closed verification that says the opposite. Neither is this
module's data to fix; both are flagged here so the next phase does not have to
rediscover them.

Why not wired: this deliverable was scoped explicitly as build-and-prove, not
build-and-connect — the certificate-facing non-conformance statement this
enables (CLAUDE.md's "the sample leaves accreditation scope and the
certificate must state exactly how it departs") is a deliberate, separate
phase, so that wiring it can be verified against a real departing run rather
than assumed correct because the unit tests pass.

---

## 16. The verification block lied, two different ways (2026-09-19)

Running the suite for the first time since 2026-08-07 produced a failure and
then four more. None was a regression. Both causes are defects in **how this
register verifies itself**, which makes them worth more than the tests they
broke.

### 16.1 A date-anchored test rots

`tests/test_facility_dashboard.py::test_the_latest_entry_wins_even_within_the_same_minute`
stamped its entries `2026-08-07` — the day it was written. `dashboard_summary`
reports any eye wash entry older than today as `pending`, deliberately (§6.4
cadence). So the final assertion, that a repair logged after a failure reads
`ok`, held on the day of writing and has been false every day since.

The production code is correct. The very next test in the same file asserts
that an old passing check **must** read `pending` — the file pins the right
behaviour and then trips over it. Fixed by stamping today, which is what the
test meant: its subject is the same-minute tiebreak, not recency.

**§13 claimed "144 assertions across 18 test files, all passing."** That was
true when written and silently false from roughly the next day. A verification
result whose truth depends on the date it is read is not a verification result.

### 16.2 The documented command sequence produces four false failures

The block at the top of this file was three lines assuming a persistent shell.
Run the exports separately from the loop — the obvious thing to do, and what
happened here — and the tests fall back to the seeded built-in defaults instead
of the lab's configured profile. Result: `test_profiles`, `test_fault_injection`,
`test_salt_correction` and `test_unconfigured_criteria` fail with confident,
specific, entirely meaningless assertions.

Proven by running the loop twice, once with the exports and once without:
**19/19 pass with them, 15/19 without, and nothing fails with them set.** The
block is now a single `&&`-chained invocation.

### 16.3 Two stale flags found on the way

- **`EPA_1633A.qc_acceptance.LFSMD` carried the same 40–130 placeholder window
  as `LFB` and `LFSM` but had lost its `verify_against_method` flag** — so two
  unverified tiers announced themselves and the third looked verified. The flag
  is advisory only (it appends `[VERIFY limits vs method tables]` to a failing
  recovery; `qc_engine.py:610`) and changes no pass/fail outcome, so flagging it
  restores what §8 requires of a placeholder without altering evaluation.
  Applied. `data/qc/` is gitignored, so no commit captures it.
- **`pfas_pipeline/method_profiles.py` still hardcodes `verify_against_method=True`
  on its EIS branch** with a "VERIFY against purchased method copy" note, stale
  since Q-004 closed that verification on 2026-06-19 against EPA 820-R-24-007.
  The add-on profile no longer carries the flag there; the Py3 worker does.
  Left alone, recorded — it is a divergence between the two halves of §7's
  "one system, not two."

### The transferable rule

Both 16.1 and 16.2 are the same shape as everything else in this register: a
fact recorded correctly in one place and not carried to where it is used. Here
the fact was *"these tests pass"* — recorded without recording what it depended
on. A passing state has preconditions, and a register that states the state
without stating the preconditions will eventually be lying.

---

## 17. The resolution ↔ QC-engine JOIN is now proven; crossing the process
##     boundary still is not (2026-09-20)

The lab asked, in their own words, to "verify that this works and values
exceeding tolerances are flagged correctly" once "the QC is called." §15
proved tier resolution in isolation (`test_ruleset.py`); `test_fault_injection.py`
proved the QC engine flags an injected deviation in isolation. Neither proved
the JOIN: a criterion resolved through the tiers, handed to a real QC check,
produces the right flag AND the right absence of one.

`tests/test_resolved_criteria_flag.py` (7 test functions, all passing) now
proves that join, in-process, in one Python 3 interpreter:

1. A value inside a lab-tier `dup_rpd_max` → not flagged.
2. A value outside it → flagged, `(RPD)` issue, right source/value text.
3. A project QAPP LOOSENS `dup_rpd_max`: a value that fails at the lab tier
   passes at the project tier, and resolution reports `tier=project` with
   the supplied `source_doc`/`source_rev`.
4. A project QAPP TIGHTENS it: a lab-tier pass becomes a project-tier fail.
5. `eis_recovery` (the one seeded baseline, EPA 1633A Table 6/8): a project
   value loosens the floor below the method baseline. The QC engine correctly
   applies the resolved (project) window — a value between the project floor
   and the method floor passes — while resolution independently reports
   `DEPARTS` with `departure["ends"]` naming only the loosened end and
   carrying the baseline citation. Confirms conformance and QC pass/fail are
   genuinely separate axes, not two views of the same check.
6. `dup_rpd_max` has no seeded baseline anywhere → `conformance=UNKNOWN`
   regardless of whether the same resolved value is then flagged or not by
   the real check — UNKNOWN neither suppresses nor manufactures a flag.
7. Boundary values pinned against the engine's OWN comparisons, not assumed:
   `rpd_check_profiled` is `rpd_pct <= limit` (inclusive pass);
   `recovery_check_profiled` is `min <= pct <= max` (inclusive both ends).

**How the join was made, and what that costs.** `ruleset.resolve()` returns a
plain value (a float, or a `{"min":, "max":}` dict) plus provenance — it knows
nothing about `pfas_pipeline`'s `MethodProfile` interface, correctly, since
wiring the two live is explicitly out of scope (§15). `recovery_check_profiled()`
/ `rpd_check_profiled()` only ever call `profile.qc_rules(...)` and read
`profile.method_id`. The test bridges this with a duck-typed adapter
(`_ResolvedProfile`) carrying just the resolved value — not a stub of
qc_engine itself; every comparison and flag/no-flag decision in a passing run
is produced by the real, unmodified functions on both sides. The adapter's
narrowness has one traceable cost: a live `MethodProfile.qc_rules()` also
sets `is_guidance_only` / `verify_against_method` / `notes` on its `QCRule`,
which the real checks append to a failing message (e.g. "[VERIFY limits vs
method tables]"); the adapter leaves those at their dataclass defaults, so
the test proves the comparison and the base message, not that decoration.

**What this does NOT prove — the delivery gap.** `senaite.pfas.ruleset` is
Python-2.7 add-on code; `pfas_pipeline.qc_engine` is Python-3 worker code.
They are one system (CLAUDE.md §7) but two processes that share no memory —
a resolved criterion crosses that boundary only as JSON, and today NOTHING
performs that crossing. `resolve_for_batch()` has zero call sites (§15); the
worker reads only `data/qc/method_profiles.json` (the lab tier) and has no
channel to receive a project ruleset at all. Concretely: a project QAPP
override entered through the add-on today would be resolved by nobody and
delivered nowhere — the running pipeline would evaluate every sample against
the lab tier regardless of what a project's ruleset says. This is a
*delivery* gap, not a correctness gap — the two halves this file joins are
both individually correct and correctly composable; nothing yet carries the
composed answer to where a live run would use it.

**A second, independent, pre-existing wiring gap found while building case
5, left alone (not this task's to fix):** `EPA1633AProfile.qc_rules(analyte,
matrix, qc_type="EIS")` (`pfas_pipeline/method_profiles.py:986`) is real,
working code — it reads `eis_overrides` / `eis_matrix_overrides` (the same
data `method_baselines.py`'s seeded baseline cites) and returns a correct
per-analyte recovery window. **No call site in `pfas_pipeline/run_queue.py`
ever invokes it with `qc_type="EIS"`.** Live EIS monitoring instead runs
through `is_raw_check()` / `profile.is_rule()`, which applies ONE blanket
vs-ICAL-average window to every internal standard — not the per-analyte
Tables 6/8 windows this baseline verifies against. `is_rule()`'s own note
even says "EIS uses per-analyte limits," describing the very branch nothing
calls. Net effect: `eis_recovery` — the only criterion in this whole system
with a closed, citable method-text verification (Q-004) — has no live
consumer in the pipeline today. test_resolved_criteria_flag.py's case 5
proves the window-comparison mechanism is correct for that criterion's
shape; it does not and cannot prove that mechanism runs against real EIS
results, because nothing currently calls it that way. Older than, and
independent of, the ruleset.py wiring gap above — flagged here so the next
phase does not have to rediscover it either.
