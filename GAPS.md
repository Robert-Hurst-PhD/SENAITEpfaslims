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

> **This sentence is CORRECT. A "correction" filed against it on 2026-09-22 was
> itself wrong and has been withdrawn — see §22.1.** Querying ZODB directly:
> EPA_537_1 and EPA_1633A store **zero** `matrix_factors` rows, and FDA stores
> five (Aquatic Tissue has none). The 13 really are unset.

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

---

## 18. EIS recovery wiring investigated, NOT implemented — the producer chain
##     does not exist for EPA 1633A (2026-09-20)

§17 flagged that `EPA1633AProfile.qc_rules(qc_type="EIS")`
(`pfas_pipeline/method_profiles.py:986`) has no caller. This entry is the
follow-up investigation into whether it can safely be wired, per three
questions. Short answer: **no — stop and report, per the task's own
condition.** Wiring it now would mean inventing a compound list, a role map,
and a name-alias table that does not exist anywhere in this codebase, then
building a synthetic fixture that validates against those inventions. That is
the "confident, wrong regulatory verdict" shape this project exists to catch,
one layer up. Nothing in `qc_engine.py`, `run_queue.py`, `method_profiles.py`,
`analyte_alias.py`, `analyte_reference.py`, or the synthetic generator was
changed.

**Q1 — does the pipeline compute an EIS recovery percent anywhere?**
No, but it already **imports** one, and that import is itself a second,
independent dead field. The real SCIEX OS export used for the FDA E2E test
(`/media/robin/STORAGE/PFAS Work/Test Sample.csv`) carries a native
`% Recovery (IS)` column, mapped straight through to `InstrumentRow
.pct_recovery_is` (`src/senaite/pfas/instrument_columns.py:124` →
`pfas_pipeline/constants.py:242` → `pfas_pipeline/importer.py:317`). It is
populated on **462/462** `Internal Standard` rows in that file, across all
four sample types (Standard, Unknown, Quality Control, Blank) — every row
carries `Expected Concentration = 1` and a computed `Calculated
Concentration`. Spot-checking 10 rows: `calculated_conc / expected_conc *
100` reproduces the vendor's own `% Recovery (IS)` value to full floating-
point precision — the exact pattern already trusted elsewhere in this file
for `ccv_check_profiled` (`pfas_pipeline/qc_engine.py:658-660`,
`rec = r.calculated_conc / r.expected_conc * 100.0`). So the *formula* and
the *fields* (`calculated_conc`, `expected_conc`) both exist on
`InstrumentRow` and both get populated by real instrument output — for
FDA_32PFAS, on the one real export this system has ever processed.
`pct_recovery_is` itself is parsed by `importer.py` and then **read by
nothing** downstream — the same dead-field shape as the `EIS` qc_type,
just one layer closer to the wire. That is a cheap, low-risk fix on its own
and is recorded here as a distinct finding, not folded into the EIS work
below.

**Q2 — what would be required to compute/consume a genuine EIS recovery
for EPA 1633A, and do those requirements hold today?** No, on four
independent counts, each a hard blocker on its own:

1. **No compound list to iterate.** `get_is_list("EPA_1633A")`
   (`pfas_pipeline/method_profiles.py:1193-1205`) reads
   `internal_standards` from the profile; that key is absent from the live
   `EPA_1633A` block in `data/qc/method_profiles.json`, so the function
   falls through to `return []`. Consequence, verified by reading
   `run_queue.py:295` (`for is_cmp in _get_is_list(_method): ...`): **no
   internal-standard check of any kind — not the existing NIS area screen,
   not a hypothetical EIS recovery check — currently executes for EPA
   1633A.** This is a bigger gap than the one named in the task: it is not
   "the wrong check runs," it is "no check runs."
2. **No EIS/NIS role map.** `get_surrogate_is_chain("EPA_1633A")`
   (`method_profiles.py:1287`) returns `{}` — the live profile's
   `surrogate_is_chain` key is empty. `tests/test_surrogate_map.py
   ::test_the_epa_is_chain_is_left_unset_on_purpose` confirms this is a
   **recorded decision, not an oversight**: EPA 537.1 and EPA 1633A quantify
   every labelled compound by isotope dilution against its own calibration
   curve, not against one shared injection standard the way FDA's surrogates
   quantify against M4PFOA — so there is no "chain" to encode, and asserting
   one would fabricate a regulatory value. Practical effect on
   `is_raw_check()`: with an empty chain it falls back to the global
   `injection_is_names()`, which knows exactly one compound (FDA's
   `13C4-PFOA`/`M4PFOA`) — a fallback that happens not to misfire for 1633A
   today only because 1633A's own surrogate list doesn't collide with it,
   not because the role split is actually represented for this method.
3. **No join key between the Table 6/8 window table and any compound name
   the pipeline would see on a row.** `eis_overrides` in the live
   `EPA_1633A` profile carries 24 analyte names verified verbatim against
   EPA 820-R-24-007 Tables 6/8 (Q-004: closed, citable). Running all 24
   through `analyte_alias.keyword_for()` — the exact resolver
   `is_raw_check()` uses to reconcile a surrogate's instrument-export name
   with its profile identity — leaves **10 of 24 unresolved** (passthrough,
   meaning "unknown to `analyte_reference.COMPOUND_NAME_TO_KEYWORD`"):
   `13C4-PFBA`, `13C5-PFPeA`, `13C9-PFNA`, `13C6-PFDA`, `13C7-PFUnA`,
   `13C2-4:2FTS`, `13C2-6:2FTS`, `13C2-8:2FTS`, `13C8-PFOSA`,
   `13C3-HFPO-DA`. Splitting those 10 by what they actually diverge on:
   - **5 are genuine isotopologue divergences, not spelling** — the EPA
     table and `analyte_reference.INTERNAL_STANDARDS`
     (`src/senaite/pfas/analyte_reference.py:81-109`) name *different*
     labelled reference materials for the same native analyte: `13C4-PFBA`
     (EPA) vs `13C3-PFBA` (this codebase's table); `13C5-PFPeA` vs
     `13C3-PFPeA`; `13C9-PFNA` vs `13C5-PFNA`; `13C6-PFDA` vs `13C2-PFDA`;
     `13C7-PFUnA` vs `13C2-PFUDA` (also a PFUnA/PFUDA abbreviation
     difference on top of the isotope-count difference). Since Q-004 says
     the EPA names are read verbatim off the official method PDF, the
     inference is that `INTERNAL_STANDARDS` — a single table shared across
     all three methods — holds **FDA's own SIL standard list** for these
     five analytes, not 1633A's. Aliasing `13C4-PFBA` to `13C3-PFBA` in code
     would silently treat two different physical reference materials as
     the same compound. Not done.
   - **5 look like notational variants of the same compound, unconfirmed**:
     `13C2-4:2FTS` / `13C2-6:2FTS` / `13C2-8:2FTS` (EPA) vs this codebase's
     `13C2,D4-4:2FTS` / `13C2,D4-6:2FTS` / `13C2,D4-8:2FTS` (the D4 co-label
     is standard on commercial fluorotelomer sulfonate surrogates, so the
     EPA table may just be abbreviating); `13C8-PFOSA` (EPA) vs `13C8-FOSA`
     (this codebase, same isotope count, "P"-prefix convention only);
     `13C3-HFPO-DA` (EPA) vs `13C3-GenX (HFPO-DA)` (this codebase, same
     isotope count, parenthetical naming only). These were NOT merged in
     code either — a wrong guess here has the same blast radius as #1, just
     lower probability — but they are named separately so whoever edits
     `method_profiles.json` next knows which 5 need a brand-new
     `INTERNAL_STANDARDS` row for 1633A and which 5 might only need an
     alias entry.
   The remaining 14 of 24 `eis_overrides` names do resolve today
   (`13C5-PFHxA`→`M5PFHxA`, `13C8-PFOA`→`M8PFOA`, `D3-NMeFOSA`→
   `MD3NMeFOSA`, etc.) — but a window table that is right for 14/24 analytes
   and silently falls back to a generic LFSM-tier default for the other 10
   is exactly the "confident, wrong verdict" failure mode the task warned
   against.
4. **No real EPA 1633A instrument export exists anywhere to confirm the
   producer chain holds for this method at all.** Q1's cross-check
   (`calculated_conc`/`expected_conc` populated and correct) was verified
   against FDA_32PFAS/SCIEX data only — the one real export this system has
   ever processed. `pfas_pipeline/vendor_profiles.py`'s own module
   docstring says 537.1/1633A labs commonly export from Waters
   MassLynx/TargetLynx or Agilent MassHunter, not SCIEX; those two vendor
   profiles map generic `Exp. Conc.`/`Std. Conc.` and `Conc.`/`Final
   Conc.` columns that WOULD carry a labelled-compound recovery if the
   vendor software populates them for `Internal Standard`-type rows — but
   there is no 1633A file on this machine, real or synthetic (the
   synthetic generator does not set `calculated`/`expected` on surrogate
   rows either — see below), to confirm that inference rather than assume
   it.

**Q3 — is the EIS-vs-NIS role distinction represented in the data at
all?** For FDA: yes, exactly once, via `INTERNAL_STANDARDS`'s fourth column
(`analyte_reference.py:81-109`) — 26 rows role `surrogate`, one
(`M4PFOA`/`13C4-PFOA`) role `injection_is`. For EPA 1633A: no. Per
`test_the_epa_is_chain_is_left_unset_on_purpose`, 1633A has no injection-IS
concept at all in this method's own chemistry (isotope dilution against each
compound's own curve) — so the FDA-shaped role split does not even apply,
and there is no method-specific column recording that fact; it is only
recorded in a test docstring.

**What a real fix needs, in order (none attempted — `data/qc/method_profiles
.json` is read-only in this session, and `analyte_reference.py`/
`method_profiles.py` changes without it would be unverifiable guesses):**
1. Populate `internal_standards` and (if the EPA methods ever need one)
   `surrogate_is_chain` for the `EPA_1633A` block in the profile store.
2. Reconcile the 10 `eis_overrides` names against `INTERNAL_STANDARDS` —
   add 1633A-specific SIL rows for the 5 genuine isotopologue divergences
   (do not alias them to FDA's compounds); confirm the other 5 are
   notational and add aliases only after that confirmation.
3. Obtain one real EPA 1633A instrument export (Waters or Agilent, per the
   vendor-profile module's own expectation) to confirm `calculated_conc`/
   `expected_conc` are actually populated on `Internal Standard` rows the
   way they are on the FDA/SCIEX file — the same kind of proof Q1 relied on,
   not an assumption.
4. Only then wire `qc_type="EIS"` into `run_queue.py`, and only then extend
   `generate_synthetic_runs.py` / `test_fault_injection.py` — a fixture
   authored against unverified assumptions about all three of the above
   would produce a "0 false positives across 18 combinations" result that
   proves the test author's assumptions are self-consistent, not that the
   check is correct.

**Flag behaviour change from this task: none.** No file under
`pfas_pipeline/` was modified. Live QC verdicts for EPA 1633A, EPA 537.1,
and FDA_32PFAS are byte-for-byte unchanged. The dead `qc_type="EIS"` branch
and the dead `pct_recovery_is` field both remain dead, now for a recorded
reason instead of a silent one.

---

## 19. No IS check runs on either EPA method, and §1 could not have seen it (2026-09-20)

Established while investigating §18, verified directly against the live profile
store and the run queue.

### 19.1 The loop iterates nothing

`internal_standards` is **absent from all three method profiles**. `get_is_list`
(`pfas_pipeline/method_profiles.py:1193-1205`) falls back to a hardcoded inline
list for FDA and returns an empty list for everything else:

```python
if method_id == "FDA_32PFAS":
    return list(_FDA_IS_DISPLAY_NAMES)
return []
```

`run_queue.py:295` then does `for is_cmp in _get_is_list(_method)`. For
**EPA 537.1 and EPA 1633A that loop body never executes.** The `is_response`
rule is enabled, the toggle check passes, zero compounds are examined, and no
flag is raised. Silence is indistinguishable from "everything passed."

So §18's framing — that 1633A EIS is judged by a blanket window instead of the
per-analyte tables — was too generous. **Neither window is applied. No
internal-standard or surrogate response monitoring happens on either EPA method
at all.** FDA works, and only because of a fallback constant that the other two
methods have no equivalent of.

### 19.2 Why the known-answer harness never caught it

`tests/test_fault_injection.py:61` — every deviation-detection case runs against
one combination:

```python
def _generate(deviations, method="FDA_32PFAS", matrix="Animal Feed"):
```

The file's own docstring says as much. `test_every_method_and_matrix_imports`
covers all 18 combinations, but it asserts only that they **import** — not that
any deviation injected into them is detected.

**§1's detection table is therefore proven for FDA_32PFAS × Animal Feed alone.**
The clean-run baseline genuinely spans all 18 combinations; the detection half
does not, and the table does not say so. A reader — including me, yesterday —
takes "Surrogate suppressed in a sample → `is_response` flags" as a property of
the system. It is a property of one method.

That entry is still true. It is just narrower than it reads, and the missing
scope is exactly where the defect lives: inject a suppressed surrogate into a
1633A run today and nothing would flag it, because there is no compound list to
iterate.

### 19.3 What this costs

Surrogate and internal-standard recovery is how a PFAS method detects matrix
suppression and extraction loss per sample. On EPA 537.1 and EPA 1633A that
signal is currently not evaluated. No result is wrong as a consequence — nothing
is miscalculated — but a class of failure that should qualify a result `[M]` is
not being looked for.

### The transferable rule, again

§13 named two defect shapes. This is both at once: a producer with no consumer
(`pct_recovery_is`, parsed and read by nothing, §18), and a claim recorded
without its precondition (§1's detection table, true for one method, written as
though true for all). The harness did not fail — it was never asked the
question, and the register did not record which question it had been asked.

---

## 20. The resolution/delivery gap (§17) is closed for the mechanism; the UI
##     that would actually trigger it does not exist (2026-09-20)

§17 named the gap precisely: `ruleset.resolve_for_batch()` had zero call
sites, the worker read only the lab tier from `method_profiles.json`, and "a
project QAPP override entered through the add-on today would be resolved by
nobody and delivered nowhere." This entry closes the mechanism the same way
D59-era work always has here — as a FILE bridge, not a second REST channel,
because profiles already cross the add-on/worker process boundary that way
(`method_profile_store.export_profiles_to_file()` -> `method_profiles.
reload_from_profiles()`) and a second mechanism for the same kind of data is
the duplication CLAUDE.md §1 rule 3 forbids.

**What is built.**

- `senaite.pfas.resolved_criteria_store` (new module, not folded into
  ruleset.py) — mirrors method_profile_store.py's own split: ruleset.py stays
  pure resolution + a thin ZODB shell, exactly as its docstring already
  promised; this module is the file bridge for the RESOLVED (project-aware)
  answer, one batch at a time. `build_resolved_rows()` / `write_resolved_file()`
  / `_analytes_for_key()` are pure (already-fetched `profile` /
  `project_ruleset` dicts in, JSON-ready rows out) and are exercised directly
  by `tests/test_resolved_criteria_store.py` under plain Python 3, the same
  way `test_ruleset.py` exercises `resolve()`. `export_resolved_criteria()` /
  `remove_resolved_criteria()` are the thin shells — not exercised by the
  plain-Python-3 harness (no Zope there to fetch from), proven live instead
  (below). The file lands at
  `{dirname(PFAS_PROFILES_PATH)}/resolved/{batch_id}.json` — the directory is
  DERIVED from the same env var the existing export already honours, per the
  task's instruction, not a second hardcoded `/data/qc` path.
- Every criterion in `ruleset.SHAPES_BY_KEY` is resolved and written, with
  tier, source doc/rev, and the full CONFORMS/DEPARTS/UNKNOWN + departure
  detail — nothing in the file's shape drops provenance the disclosure work
  will need later.
- The call site: `senaite.pfas.project_ref.set_project_uid()` — the ONE
  function that establishes or clears a batch<->project link (see below for
  why this is the right choke point and also not the whole answer). Linking
  now best-effort-derives a method_id (via `batch.getMethod()` +
  `method_bridge.profile_id_for_method`, request-free) and, if a matrix is
  also known, exports the resolved file; unlinking deletes it, so a cleared
  project link never leaves a stale project-tier answer for the worker to
  read. Both directions are wrapped so a failure is logged and swallowed,
  never blocking the annotation write that already happened.
- `pfas_pipeline/method_profiles.reload_from_profiles()` gained an optional
  `batch_id` argument. When given, it reads that batch's resolved file (if
  any) back and injects each already-resolved value into
  `_profile_data_cache` at the same key paths the global-file load already
  fills — `instrument_verification.calibration.r2_min`,
  `...confirmation.sn_quan_min`, `qc_acceptance.Dup.tiers[0].rpd_max`,
  `instrument_verification.ccv.recovery_{min,max}`, and per-analyte
  `eis_overrides`. **It performs no resolution** — no tier comparison, no
  fallthrough — only plumbing, per the task's explicit constraint that a
  second copy of tier logic in the worker would be the dead-twin shape this
  project has already removed twice (§2 A4, §4). The one thing duplicated
  across the process boundary is a small, static key->path map — the same
  kind of small duplication `method_baselines.matrix_class()` already
  carries for the identical reason (worker is Python-3-only and dependency-
  free of the Python-2.7 add-on package; that module's own comment says so).
  `pfas_pipeline/pipeline.py`'s sidecar-parsing block (which resolves
  `senaite_batch_id`) was moved a few lines earlier, ahead of the
  `reload_from_profiles()` call, so the batch id is known in time to pass —
  the two blocks only ever read function arguments/the sidecar file, so nothing
  else about either changed; `tests/test_watcher_parity.py`'s ordering
  assertions still hold (sidecar is read even earlier than before).
- The malformed-file contract is intentionally all-or-nothing: a corrupt
  JSON file, a file with no recognizable `method_id`, or a file containing
  even one structurally-broken row causes the WHOLE file to be ignored (one
  log line) rather than applied row-by-row — the §7.1 partial-write shape
  one layer over. A row with a recognized shape but an unmapped/foreign key
  is a normal per-row no-op, not corruption, so it does not sink its
  siblings — forward-compatible with a future criterion key this worker
  version does not yet consume.
- **Found while wiring this, not by the tests first written for it:**
  `_profile_data_cache` is not the only live reader of `cal_r2_min` /
  `sn_quan_min`. `constants.CRITERIA` — a flat dict `reload_criteria()`
  builds by re-reading the global profiles file DIRECTLY, never through the
  cache this overlay patches — still has two real consumers that never
  migrated to the "profiled" path Decision C (2026-06-17) declared
  authoritative: `qc_engine.signal_to_noise_check()` reads
  `CRITERIA["sn_quan_min"]` unconditionally (no profiled variant exists to
  call instead), and `qc_engine.calibration_check()` — the fallback
  `run_queue.py` uses only when no profile resolved at all — reads
  `CRITERIA["cal_r2_min"]`. Overlaying `_profile_data_cache` alone would have
  left those two consumers silently seeing the un-overridden lab value for a
  project-linked batch: the same "merged half-way" inconsistency this
  entry's tests exist to rule out at the file level, reappearing one
  consumer layer down. `_apply_resolved_overlay()` now also writes the
  resolved `cal_r2_min`/`sn_quan_min` (+ its `sn_min` alias) into `CRITERIA`
  from the same rows — no new resolution, the same values, one more
  destination. **Scoped to `method_id == "FDA_32PFAS"` only**, because
  `reload_criteria()` is called with no `method_id` argument anywhere in
  this codebase and so always builds `CRITERIA` from FDA_32PFAS regardless
  of the run's actual method — a PRE-EXISTING behaviour this entry did not
  introduce and does not fix (recorded here so the next reader does not
  have to rediscover it): an EPA_537_1/EPA_1633A run's signal-to-noise check
  is judged against FDA's calibration/S/N numbers today, project-linked or
  not. Overlaying CRITERIA for a non-FDA resolved payload would not fix
  that; it would just make an already-wrong dict wrong in a different,
  more confusing way, so it is deliberately left alone outside that scope.
  `tests/test_resolved_overlay.py::test_a_project_override_of_cal_r2_min_also_reaches_criteria`
  and `::test_criteria_overlay_is_scoped_to_fda_32pfas_only` pin both halves.

**The safety property, proven, not assumed.** `tests/test_resolved_overlay.py`
pins byte-for-byte identity for `batch_id=None` and for `batch_id` set but no
file present (the state of every batch today) against the same global-file
load with no batch_id argument at all — plus the malformed/partial-file
rejection cases, a null-valued row not clobbering a real lab value, the
eis_recovery per-analyte path, the CRITERIA agreement above, and — since the
worker process is long-lived and runs batches back-to-back against the same
module-global cache — that a project-linked run's overlay does NOT leak into
the next batch processed in the same process when that batch has no project
(`test_a_project_overlay_does_not_leak_into_the_next_batch_without_one`,
deliberately run WITHOUT the cache reset every other test uses, since
production never resets between batches either). 22 new test functions
across the two new files (9 + 13), all passing; full suite (22 files) green
as one invocation.

**Is `resolve_for_batch()` still at zero call sites? No — but read what
"a call site" means here before treating this as closed.** It is called
from `resolved_criteria_store.export_resolved_criteria()`, itself called
from `project_ref.set_project_uid()`. That is a real call site, not a test
harness. But — and this is the honest part — **nothing in this add-on calls
`set_project_uid()` either**, in production code, today. `senaite.pfas.
browser.projects` (`@@pfas-projects`, added the same day as this entry)
manages `PFASProject` entities — create, edit, list — and never links one to
a Batch. There is no UI anywhere that lets a user say "this batch belongs to
this project." So the honest chain is:

```
a manager enters a QAPP override        -- UI exists (project ruleset
                                            get/set helpers in ruleset.py,
                                            tested, e.g. set_project_criterion)
        |
a batch gets linked to that project     -- NO UI EXISTS. set_project_uid()
                                            is callable and correct, and now
                                            triggers the export, but nothing
                                            calls it.
        |
the resolved file is exported           -- WIRED, this entry, IF the above
                                            fires with a known method_id/matrix
        |
the worker overlays it at run time      -- WIRED, this entry
```

**Is `set_project_uid()` the right hook, or is the UI layer better?** Both,
for different halves of the same reason `export_profiles_to_file()` lives
inside `method_profile_store.save_profile()` rather than at each of its UI
callers: the choke point should be the function that changes the fact, not
every place that might one day call it, so a future caller cannot forget to
re-export. `set_project_uid()` is that choke point for "the link changed" —
correct to put the trigger there, and now done. But the choke point cannot
manufacture context it was never given: nothing on a bare Batch reliably
names its method_id and matrix without a request/worksheet in scope (the
existing helpers that come closest — `run_builder.batch_method()`,
`data_review._batch_matrix()` — both need a request, and the latter needs a
worksheet with analyses already on it, which will not exist yet at the
moment a project is first linked). `set_project_uid()` therefore takes
`method_id`/`matrix` as optional arguments and does its best without them
(a request-free method_id lookup only; matrix is never guessed, per CLAUDE.md
§8's "never fabricate"). A future "link this batch to a project" UI already
has to know the batch's method and matrix to render sensibly — a batch is
created against exactly one of each (§3) — so it is the natural place to
supply both explicitly. **Verdict: `set_project_uid()` is the right permanent
home for the trigger; it is not, by itself, sufficient — it is waiting on a
UI that does not exist yet to supply the two pieces of context it cannot
derive alone.**

**So would a QAPP override entered in the UI today actually reach a run?**
No, and the missing step is now narrow and specific: the QAPP-override UI
(project ruleset editing) exists at the data-layer/helper level
(`ruleset.get_project_ruleset` / `set_project_criterion`) but has no browser
view either — DECISIONS.md 2026-09-20 explicitly deferred that ("QC
composition" was reprioritised ahead of it) — AND no UI links a batch to a
project at all. Fix both and the rest of the chain now genuinely fires:
`set_project_uid()` exports, `reload_from_profiles(batch_id=...)` overlays,
and the worker evaluates QC against the resolved value with zero further
code changes needed in either half — for `dup_rpd_max`, `ccv_recovery`, and
`eis_recovery` unconditionally, and for `cal_r2_min`/`sn_quan_min` when the
batch's method is FDA_32PFAS (the CRITERIA scoping above; an EPA_537_1/
EPA_1633A project override of either would still resolve and export
correctly but not reach `signal_to_noise_check()`/the calibration fallback,
because `CRITERIA` does not represent those methods today regardless of any
project link). That is a materially smaller remaining gap than §17
described — a batch-to-project linking control and a ruleset edit form, not
a cross-process delivery mechanism — but it is not zero, and the CRITERIA
scoping is a second, narrower edge worth remembering alongside it.

### The transferable rule, once more

The same shape as §15/§17/§18: a mechanism can be built, tested, and wired to
its one real call site, and the feature can still not fire in production
because the call site it was wired to is itself unreached. "Has a call site"
and "is reachable from the UI a user actually operates" are different
claims; this register now distinguishes them explicitly rather than letting
it stand -- see the next entry for the same pattern closed by half.

## 21. Batch-to-project linking control — built as a viewlet, proven live end
##     to end (2026-09-22)

§20 named the exact remaining gap: "a batch-to-project linking control and a
ruleset edit form, not a cross-process delivery mechanism." This entry closes
the first half. `set_project_uid()` now has a real, UI-reachable call site.

**What is built** — `senaite.pfas.browser.batch_project_viewlet`, following
`senaite.pfas.method-profile-link` (`browser/method_viewlet.py`) exactly:

- `PFASBatchProjectViewlet`, registered `for="bika.lims.interfaces.IBatch"`,
  manager `IAboveContentBody`, layer `ISenaitePFASLayer` — always renders
  (unlike the method-profile viewlet, which renders nothing when there is no
  profile): shows the batch's current Project (code + client + QAPP), or
  states plainly "No project assigned — the lab's internal quality system
  applies." A manager (`browser.perms.require_manager`) additionally sees a
  dropdown of existing Projects + Assign/Clear buttons; a non-manager sees
  only the read-only state, no control they cannot use (CLAUDE.md §6A).
  Every attribute the template reads is pre-initialised to the benign "none
  assigned" state before a single try/except wraps the whole update body, so
  a failure on any one batch's data cannot 500 that batch's page.
- `PFASBatchProjectAssignView`, a companion `browser:page`
  (`@@pfas-batch-project-assign`) on the same interface — the POST-only
  target the viewlet's form submits to. Manager-gated server-side (403 on an
  unauthorised POST, matching `projects.py`), CSRF-disabled the same way,
  redirect-after-POST back to the batch. It never writes the project_uid
  annotation directly — always through `project_ref.set_project_uid()` /
  `set_project_uid(batch, None)` — the one choke point §20 already
  identified as correct.
- method_id/matrix for a new assignment are best-effort derived at the POST
  handler and passed to `set_project_uid()` explicitly, never guessed inside
  `project_ref` itself, exactly as its docstring specifies. method_id reuses
  the SAME resolver `run_builder.py` already calls for a batch context —
  `logbooks.PFASLogbookIndexView.batch_method()`. matrix comes from the
  batch's linked samples' SampleType, via `senaite_catalog_sample.
  unrestrictedSearchResults(getBatchUID=...)` — the pattern `run_builder.py`'s
  own batch-linked-samples fallback uses, deliberately NOT `data_review.
  _batch_matrix()`, which walks a WORKSHEET's analyses and so needs a
  worksheet that will not exist yet when a project is first linked to a
  fresh batch. When neither resolves the link is still recorded but the
  viewlet says so honestly ("Project assigned - resolved criteria NOT
  exported (method/matrix not yet known for this batch)") rather than
  claiming a success it did not achieve.

**A UID trap found and avoided, not inherited.** `browser.projects.
_list_projects()`/`_obj_to_dict()` expose a project's FOLDER id (the
`uuid4().hex` used as its Zope object id) under the field name `"uid"`.
`project_ref.get_project()`/`set_project_uid()` resolve through the object's
REAL Plone UID (`bika.lims.api.get_uid()`) via `api.get_object_by_uid()` /
a catalog `UID` search. Verified live, on a throwaway PFASProject created
and deleted for the check: folder id `76d752...` vs real UID `ac5dc7...` —
different values. Reusing `projects.py`'s dict for this viewlet's dropdown
would have silently assigned the WRONG identifier and `get_project()` would
never have resolved it back. This viewlet builds its own project list
(`_list_projects_for_select()`) keyed by `api.get_uid(obj)`, and reads the
CURRENTLY-linked project directly off the object `project_ref.get_project()`
already resolved, never through `projects.py`'s dict. `projects.py` itself is
unchanged — its `_get_project()`/`_delete_project()` deliberately key off the
folder id for their own (different) purposes — this is a naming trap to
remember, not a bug to fix there.

**Verified live, on the running instance, real data.**

Only two Batches exist in this installation, not the nine a prior session
believed (`GAPS.md`/memory predates this correction) —
`pfas-demo-client/B-001` ("Test Demo", 0 linked samples, no extraction-guide
session, no FM-ENV-251/252 method annotation, no `getMethod` field on core
Batch — method_id and matrix both resolve to `""`) and
`kcp-feed-forage/kcp-b-001` (9 real samples, matrix "Animal Feed", method
`FDA_32PFAS`). Both facts checked directly against `senaite_catalog_sample.
unrestrictedSearchResults()`, not inferred.

1. Both batches loaded at HTTP 200 before any change, viewlet rendering "No
   project assigned" on each — the untouched-batch case (task step 7),
   captured for kcp-b-001 before it was touched at all.
2. Created a throwaway Project (`TEST-PROJ-CHAIN-01`) via `@@pfas-projects`.
3. Assigned it to **B-001** via the viewlet's POST target. Response: `ok=
   Project assigned - resolved criteria NOT exported (method/matrix not yet
   known for this batch)`. Instance log, verbatim:
   `project_ref: batch <Batch at .../B-001> linked to a project but
   method_id/matrix not known (u''/u'') -- resolved-criteria export skipped,
   not guessed`. `IAnnotations(b)[PROJECT_UID_KEY]` set correctly;
   `/data/qc/resolved/` did not even exist yet. This is the documented safety
   property (§20/`resolved_criteria_store.py`) behaving exactly as specified
   — not a defect in the viewlet.
4. Assigned the same Project to **kcp-b-001**. Response: `ok=Project
   assigned - resolved criteria exported`. `/data/qc/resolved/kcp-b-001.json`
   now exists:
   ```
   batch_id:     kcp-b-001
   method_id:    FDA_32PFAS
   matrix:       Animal Feed
   generated_at: 2026-09-23T00:54:44.621689Z
   criteria (4 rows, every key in ruleset.SHAPES_BY_KEY today):
     cal_r2_min:    value=0.99                    tier=lab  conformance=UNKNOWN
     ccv_recovery:  value={min:72.0, max:128.0}    tier=lab  conformance=UNKNOWN
     dup_rpd_max:   value=20.0                     tier=lab  conformance=UNKNOWN
     sn_quan_min:   value=3.0                      tier=lab  conformance=UNKNOWN
   ```
   Every row carries `value`, `tier`, `source_doc`, `source_rev`,
   `conformance`, `departure` per the task's requirement (`source_doc`/
   `source_rev`/`departure` are `null` here because nothing departs from an
   un-set baseline at project tier yet — the fields are present and correct,
   not fabricated). **This is the mechanism firing end to end, live, for the
   first time**: link → export → file on disk, exactly the shape the Py3
   worker's `reload_from_profiles(batch_id=...)` already overlays (§20).
5. Cleared both batches via the viewlet's Clear button.
   `PROJECT_UID_KEY in IAnnotations(b)` is `False` on both (the key is
   deleted, not merely falsy) and `/data/qc/resolved/` is empty again (the
   directory itself is not removed by `remove_resolved_criteria()` — it only
   unlinks the file — so an empty `resolved/` directory persisting is
   expected, not a leftover to clean up).
6. Deleted the throwaway Project via `@@pfas-projects`.
7. Final state confirmed identical to initial: both batches HTTP 200, both
   viewlets read "No project assigned", no `PROJECT_UID_KEY` annotation on
   either, no files under `/data/qc/resolved/`.

**So does a QAPP override reach a run now? Half of it does.** The transport
this entry adds is real and proven (step 4's file is the evidence) — a
Project linked to a batch now produces a resolved-criteria file the worker
overlays. But every row in that file resolved to **tier: "lab"**, because
`ruleset.get_project_ruleset(project)` reads a per-project annotation
(`PROJECT_RULESET_KEY`) that `set_project_criterion()`/`set_project_ruleset()`
can write — and grepping the entire add-on turns up ZERO call sites for
either outside `ruleset.py`'s own definition and `tests/test_ruleset.py`.
§20 already flagged this half as deferred (DECISIONS.md 2026-09-20); this
entry confirms empirically that it is still true four days later: there is
still no authoring surface anywhere a manager could actually enter a QAPP
override value. So today, a Project can be linked to a batch (this entry)
and the link will faithfully export and overlay whatever ruleset the project
has (nothing, always) — **a QAPP override would reach a run if one could be
authored, but nothing in this codebase lets anyone author one yet.** The
remaining gap is exactly, and only, a project-ruleset edit form; no further
plumbing work is needed once it exists.

**Found during verification, unrelated to this feature, left alone but
serious enough to flag prominently: a plain `docker compose restart senaite`
silently rewrote `data/qc/method_profiles.json`.** CLAUDE.md's own gotcha (b)
requires exactly this restart after any `.pt`/`.py` change — this is not an
edge case, it is the documented, required workflow, and this session
followed it once for this task. A snapshot taken immediately before the
restart differs from the file 2 minutes after it: five `matrix_adjust`
`factor` values regressed by ~1000x (e.g. Meat/Muscle 500.0 -> 0.5, Animal
Feed 2000.0 -> 2.0) and a `verify_against_method: true` flag on an EPA_1633A
tier disappeared. Root cause CONFIRMED from the container's own startup log
(`docker logs senaite_pfas-senaite-1`), not guessed from timing alone:

```
INFO:collective.recipe.plonesite:Running profiles: ['senaite.lims:default',
    'senaite.storage:default', 'senaite.pfas:default']
INFO:Products.GenericSetup.tool:Importing profile
    profile-senaite.pfas:default with dependency strategy reapply.
INFO:Products.GenericSetup.tool:Applying main profile
    profile-senaite.pfas:default
INFO:senaite.pfas:Found existing Method: USDA/FDA 32-PFAS in Food v10
... (existing content, not re-created)
```

`collective.recipe.plonesite` reapplies every listed site profile —
including `senaite.pfas:default` — with GenericSetup's **`reapply`**
dependency strategy on EVERY instance startup, not only on an explicit
(re)install. Reapplying the profile re-runs `setuphandlers.post_install`,
which calls `method_profile_store.seed_default_profiles()` unconditionally;
that function calls `export_profiles_to_file(portal)` at its end regardless
of whether anything was newly seeded (all 3 method profiles already
existed, so no `"Seeded N..."` line appears — that function only logs on
the seed path, not the export, so the rewrite itself is invisible in the
log; only the `Importing profile .../reapply` trail upstream of it is
visible). `export_profiles_to_file()` re-derives the on-disk JSON purely
from current ZODB state, so it silently reverted whatever the file held
that ZODB did not agree with. The practical implication: if
`data/qc/method_profiles.json` ever holds a value that was written into the
file directly (or by an older code path) without also being persisted into
ZODB via `method_profile_store.save_profile()`, the NEXT container restart —
including one done only to pick up a template change, as this task's own
workflow requires — silently reverts that value with no error, no log line
naming what changed, and no operator-visible signal. The file was restored
byte-for-byte from the pre-restart snapshot (`md5sum` verified identical)
before any further work in this session; this note is the only record of
the incident. Not fixed here — it is a separate subsystem (method profile
seeding/export and the buildout's profile-reapply strategy) from the
batch-project link this entry is about, and a real fix needs to decide the
harder question of which side (ZODB or file) is supposed to be
authoritative, which is a design decision for whoever owns that subsystem,
not a slip to correct in passing. Flagged here because the
discovery mechanism (snapshot-before-touching-shared-state) is exactly what
this task's own instructions required, and the next person who runs `docker
compose restart senaite` without a fresh snapshot in hand will not see it
coming.

Suite: all 22 test files green as one invocation (`for t in tests/*.py; do
python3 "$t"; done`), same command as always — this feature adds no new
plain-Python-3-testable module (the viewlet and its POST handler are
Zope/Plone browser code, proven live above, the same category
`resolved_criteria_store.export_resolved_criteria()`/`remove_resolved_
criteria()` already were in §20).
the first stand in for the second.

---

## 22. The export erases a configured 1.0, and ZODB never got the factor fix (2026-09-22)

Three findings, established by querying the running instance's profile editor
directly rather than reading the exported file.

### 22.1 WITHDRAWN — this entry was wrong, and how it went wrong is the point

**The claim filed here on 2026-09-22 — that the 13 "unset" matrices actually
hold a factor of 1.0 which the export drops — is false.** §3 was right all
along. Reading `get_profile()` inside Zope, which is the store itself:

| Method | supported_matrices | `matrix_factors` rows STORED |
|---|---|---|
| FDA_32PFAS | 6 | **5** — Aquatic Tissue has none |
| EPA_537_1 | 3 | **0** |
| EPA_1633A | 9 | **0** |

So the 13 genuinely have no factor, and Aquatic Tissue genuinely has none —
exactly as originally recorded.

**Where the false claim came from.** The retraction was based on
`@@pfas-method-profile-edit` rendering `value="1.0"` for every one of those
matrices. That is the **form supplying a display default for a matrix with no
stored row**, not a stored value. The rendered HTML was read as if it were the
store.

That is the same defect shape this register exists to catalogue, committed by
the register itself: a derived surface mistaken for the source of truth. It is
worse than the ones in §13, because those were the code doing it — this was the
audit doing it, and an audit that reads a rendering will confidently certify
whatever the rendering says.

It was caught only because a *write* was planned. The dry run written to make
the write safe printed the stored rows, and they did not match the form. Had
the correction been filed without intending to change anything, it would have
stood.

**The rule:** when the question is "is this configured?", the form cannot
answer it. A form's job is to show something editable, so it must invent a
value where none exists. Only the store distinguishes *unset* from *set to the
default*.

### 22.2 The 1000x factor correction was never persisted — FIXED 2026-09-23

The factors corrected on 2026-09-18 (500 / 500 / 500 / 200 / 2000, §14) were
written to `data/qc/method_profiles.json` — the **export**. ZODB, the source of
truth, still holds the originals:

```
Meat / Muscle 0.5   Eggs 0.5   Fish / Seafood 0.5   Milk 0.5   Animal Feed 2.0
```

The file is regenerated from ZODB, so the correction survives only until
something regenerates it. **The 1000x under-reporting defect is not fixed.** It
is masked in a file that gets overwritten. Applying it properly means saving the
Matrices & Units pane in the Method Profile UI — a human clicking Save, or a
full-pane POST; a *partial* POST is what nulled seven live QC criteria in §7.1,
and the 823b546 guard stops an absent pane clobbering, it does not make a
scripted partial POST safe.

### 22.3 Restarting Zope silently reverts live config

`docker compose restart senaite` reapplies the `senaite.pfas:default`
GenericSetup profile on startup (`collective.recipe.plonesite`, dependency
strategy `reapply`) and regenerates the profile export from ZODB. Any live edit
to `data/qc/method_profiles.json` is discarded.

This is a **process defect, not an incident**. This project's own workflow
requires a Zope restart after every template change, so every such restart has
been silently reverting live config. Anyone editing that file must either
persist through the UI or expect the edit to last until the next restart.

### The transferable rule

§13 named the recurring shape: a fact recorded correctly in one place and never
carried to where it is used. Every entry above is a variant, including the one
that had to be withdrawn.

**22.1 is the shape turned on the auditor.** The store said one thing, the form
rendered another, and the audit believed the form. Nothing in the code was
wrong; the reading was. An audit that consults a derived surface will certify
whatever that surface happens to show, and it will do so with citations.

**22.2 is the same boundary in the other direction.** A value was written to the
export and not to the store, so the system agreed with the fix exactly until
something regenerated the file.

Both reduce to one working rule, which is now the price of entry for anything
filed here: **a claim about configuration must come from the store.** Not the
export, which drops and reshapes; not the form, which must invent a value to
have something to show. If an entry cannot name where in ZODB it read a value,
it is a claim about a rendering, and it does not belong in this register.

The withdrawal was caught only because a write was planned and a dry run was
written to make the write safe. That is luck, not method. The method is to read
the store first.

---

## 23. Both file-only edits persisted to ZODB, and §22.3 refined (2026-09-23)

### 23.1 What was applied

Two corrections that existed only in the export are now in the store, applied
by read-modify-write through `get_profile()` / `save_profile()` inside
`bin/instance run` — NOT through the form handler.

| Correction | Before (ZODB) | After (ZODB) |
|---|---|---|
| FDA matrix factors (§14, §22.2) | 0.5 / 0.5 / 0.5 / 0.5 / 2.0 | **500 / 500 / 500 / 200 / 2000** |
| EPA_1633A LFSMD `verify_against_method` (§16.3) | absent | **True** |

**The 1000x under-reporting defect is now actually fixed.** It was previously
masked in a regenerable file.

Why this route was safe where a scripted form POST is not: `save_profile()`
replaces the whole entry from a dict, and the dict came from `get_profile()`,
so every existing key rides along. The §7.1 hazard is a property of the FORM
handler, which builds its dict from request fields and therefore turns an
absent field into a cleared value. Starting from the stored dict removes the
failure mode rather than guarding it.

Verified by diffing every top-level key across the write: 27 before / 27 after
on FDA and 26 / 26 on 1633A, none lost, none gained, and `matrix_factors` /
`qc_acceptance` respectively the only values that moved. The factor change then
survived a full `docker compose restart senaite`.

### 23.2 §22.3 was overstated, and the truth is less convenient

§22.3 said a Zope restart "silently reverts live config". Observed directly:
after `docker compose restart senaite`, the LFSMD flag — which existed **only**
in the export — was still in the file, and ZODB still did not have it. The
export was not regenerated by that restart.

So the export is **not** rewritten on every restart. It is rewritten when
something calls `export_profiles_to_file()` — every `save_profile()` does, and
the GenericSetup reapply can. Which restarts trigger it is not predictable from
the outside.

That is worse than a guaranteed revert, not better. A file-only edit that
always died on restart would be caught the first time. One that usually
survives, and disappears whenever an unrelated profile save happens to run,
produces a config that is correct for days and then silently is not — with no
event to correlate against.

Until the LFSMD flag was persisted above, the file and the store actively
disagreed: the export said the tier was flagged as unverified, ZODB said it
was not. Anything reading the export saw one lab; anything reading ZODB saw
another.

### The rule this adds

§22.1 said a claim about configuration must come from the store. This adds the
write half: **a change to configuration must go to the store.** The export is
downstream of ZODB in both directions — it cannot be trusted as evidence and it
cannot be used as a destination. Editing `data/qc/method_profiles.json` by hand
is not a way to change this system's behaviour; it is a way to disagree with it
temporarily.

---

## 24. The resolved-criteria record is mutable, and a certificate depends on it (2026-09-23)

Found by checking this project against how regulated-industry LIMS version
specifications: a spec is bound with an effective date, activating a new
revision supersedes the old one, and **the version in force at the time of the
decision** is what flags pass/fail — not the current one.

### What is actually stored

`resolved_criteria_store.write_resolved_file()` writes
`{dirname(PFAS_PROFILES_PATH)}/resolved/{batch_id}.json` and **overwrites
unconditionally**. The write is atomic (`.tmp` then rename) and stamps
`generated_at`, but keeps no history. The key is the **batch**, not the run and
not the report.

Its only trigger today is `project_ref.set_project_uid()` — assigning or
clearing a project link.

### Why that is a parentage problem, not a tidiness one

- **Re-assigning a project rewrites the basis of a judgement already made.** A
  batch judged and reported under one set of criteria, then re-linked, resolves
  afterwards to whatever the criteria are *now*. The certificate says one thing;
  the system's record of why says another.
- **A QAPP revision after the run leaves the file stale rather than rewritten** —
  accidentally immutable, for want of a trigger rather than by design. Both
  failure modes come from the same place: nothing ties the record to a moment.
- **One file per batch, not per run.** A batch analysed twice has one record,
  and the second overwrites the first.

CLAUDE.md §1 rule 6 requires a result to name its parentage in both directions.
A parent that can be edited after the fact is not parentage; the non-conformance
statement §5 will build on this is a claim about a specific moment, and nothing
currently fixes that moment.

### The shape of the fix

The precedent already exists here: `snapshot_for_publication` captures a report
at issue time rather than re-rendering it later. The same applies — the resolved
criteria that governed a run must be **snapshotted where the judgement is
recorded** (the worksheet or the publication record), and the certificate must
read the snapshot, never the live file.

That makes the per-batch file what it should be: a **working artefact** for the
worker to consume on the next run, freely regenerable, with no historical claim
attached to it.

**This is a precondition for §5, not a follow-up to it.** A disclosure that
itemises departures is only as good as the immutability of what it itemises,
and it is much cheaper to snapshot before anything reads from the live file than
to retrofit provenance onto certificates already issued.

### The rule

§22 established that configuration must be read from and written to the store.
This adds the time axis: **a criterion that decided something must be frozen at
the moment it decided it.** Live config answers "what would we do now"; only a
snapshot answers "what did we do then", and an audit only ever asks the second.

---

## 25. QC COMPOSITION is now a resolvable override class, distinct from the
##     numeric criteria (2026-09-23)

The lab's own framing: *"QAPPs can require things like all samples run in
duplicate, an additional surrogate is used, or LFSMs get run in more regular
intervals."* Everything §15/§20 built resolves a criterion's **numeric limit**
(a recovery window, an RPD ceiling, an r² floor). None of that touches WHICH
injections a run contains or HOW OFTEN — a QAPP can vary that too, and nothing
in `ruleset.py` or `run_builder.py` had a place for it.

### What is now wired

Three keys, registered in `ruleset.SHAPES_BY_KEY` and resolved through the
identical project → lab → baseline path the numeric criteria use:

| Key | Shape | Lab-tier source | Baseline seeded? |
|---|---|---|---|
| `ccv_frequency` | `SHAPE_MAX` | `instrument_verification.ccv.frequency` (same path `run_builder.ccv_interval()` already read directly) | No |
| `lfsm_frequency` | `SHAPE_MAX` | `qc_acceptance.LFSM.frequency` (forward-looking — no shipped profile has this field yet) | No |
| `duplicate_all_samples` | `SHAPE_MIN` (boolean read as 1/0 — True is strictly tighter) | `qc_acceptance.Dup.duplicate_all_samples` (forward-looking) | No |

**Explicitly out of scope, on purpose:** "an additional surrogate is used."
That changes the surrogate-to-IS map, a method-owned single-source fact
(CLAUDE.md §3, and the exact defect class §9/§13 already catalog for
duplicated analyte data). No code here touches `analyte_reference`, any
surrogate map, or an IS list.

**No baseline is seeded for any of the three**, and none should be: these are
QAPP-level demands *on top of* a method's own minimum QC — no EPA/FDA method
text specifies a duplicate frequency or an LFSM interval as part of its
minimum program, so there is nothing to cite (CLAUDE.md §8). Absent means
UNKNOWN (rule 1), permanently, not a placeholder for a baseline someone forgot
to add. Consequence: `method_baselines.compare()` never actually runs on
`duplicate_all_samples` in production — its `SHAPE_MIN` assignment is
declarative, pinned only by a synthetic baseline in
`tests/test_ruleset.py::test_duplicate_all_samples_shape_min_direction_synthetic_baseline`.

### The direction rule, proven

Frequencies are intervals: a **larger** number is a **looser** requirement
(1 LFSM per 20 samples is less QC than 1 per 5), so both frequency keys are
`SHAPE_MAX` — the same "looser means higher" direction as `dup_rpd_max`, not
`SHAPE_MIN`. `tests/test_ruleset.py::test_frequency_direction_rule_is_not_inverted_ccv_and_lfsm`
and `::test_more_qc_than_required_never_departs_certificate_language` pin this
with a synthetic baseline: a project asking for MORE QC (a smaller interval,
or `duplicate_all_samples=True` under a `True`-requiring baseline) always
resolves `CONFORMS`, never `DEPARTS`.

### Where composition is consumed — the integration point, and why

`senaite.pfas.browser.run_builder.PFASRunBuilderView` — the add-on view that
actually assembles a run — not `resolved_criteria_store` (the per-batch file
export). That store exists for the Py3 pipeline worker's evaluation of
already-produced results (§17/§20); composition is a **build-time** decision
about what the run itself contains, made before any result exists, so it is
resolved directly via `ruleset.resolve_for_batch()` from a new
`_resolve_composition()` helper on the view, called from `ccv_interval()` and
from `_handle_build()`.

The actual sequence transform (duplicate insertion, LFSM-interval insertion)
is a new Zope-free module, `senaite.pfas.run_composition`, in the same "pure
core, thin ZODB shell" style as `ruleset.py` / `method_baselines.py` /
`holding_time.py` — required because `run_builder.py` imports
`zope.annotation` / `Products.CMFCore` / `Products.Five` at module load and so
cannot be unit-tested outside a Plone container at all; the part with real
risk of an inverted or silently-wrong composition change needed to be
testable on its own. `compose_sample_block()` is IDENTITY when both overrides
are `None`/falsy — the project-less default — which both a Zope-free test
(`tests/test_run_composition.py`) and a live before/after CSV diff on batch
B-002 (md5 `749af8f6897e7f9754790ceb0781a0cb`, byte-identical) confirm.

`run_builder._role_from_sample` (redundant-QC suppression: a registered
LFSM/MB sample must not also get a sequence-token injection) now delegates to
`run_composition.classify_sample_role` rather than carrying its own copy —
the same judgement decides `is_field_sample()`, so `duplicate_all_samples`
and `lfsm_frequency` never touch a row that is already a registered QC sample,
one definition instead of two (CLAUDE.md §3).

**Recorded decision, not an accident:** an interval-driven extra LFSM is
emitted even when the batch also registers its own LFSM sample elsewhere in
the sequence. Emitting more QC than the template calls for is always safe
under the direction rule; suppressing it would need a second definition of
"already have enough LFSM" that does not exist and was not built here.

### A bug the unit tests could not have caught, found by testing the positive
### case live

Every unit test built against hand-written fixtures had `role=""` or no
`role` key for an ordinary field sample. Against the REAL extraction log on
B-002, `run_builder.sample_rows()` sets `row["role"] = "Sample"` for every
field sample — an explicit, non-blank value. `is_field_sample()`'s first cut
treated *any* non-empty role as "this is a registered QC sample, not a field
sample" — so against real data, `duplicate_all_samples=True` and
`lfsm_frequency=2` both silently applied to **zero rows**, while every
Zope-free test still passed, because none of them used a row shaped like the
ones the add-on actually produces.

Found by linking B-002 to a throwaway `PFASProject` (`bin/instance run`,
`transaction.abort()` at the end — nothing committed, temp project deleted),
setting `ccv_frequency=3` / `lfsm_frequency=2` / `duplicate_all_samples=True`
via `ruleset.set_project_criterion()`, and building the real sequence through
`build_sequence()`. Before the fix: 0 duplicate rows, 0 extra LFSM rows.
Fixed by replacing "any non-empty role disqualifies" with an explicit set of
recognized QC role codes (`run_composition._QC_ROLE_CODES`) that a row's
`role` must match to be excluded; `role="Sample"` (or any role senaite.pfas
doesn't recognize) now falls through to the id-based guess, same as blank.
After the fix, the same live rebuild produced 3 duplicate rows, 2 LFSM rows
(1 interval-inserted + 1 already-registered), and 5 CCV rows (interval 3
instead of 6) — all correct. `tests/test_run_composition.py
::test_an_explicit_sample_role_is_still_a_field_sample` pins the shape of
the bug directly so it cannot reappear silently. The project-less safety
property (B-002 byte-identical CSV) was re-confirmed after the fix.

This is the same lesson the fault-injection register (§1/§16) keeps proving:
a transform this consequential is only trustworthy once it has been run
against a shape of data nobody hand-wrote for it.

### What is still open

- **`qc/rules.py`'s `RULE_LIBRARY` `ccv_frequency` toggle is a different
  thing and remains unwired** — `LIBRARY_KEY_TO_ENGINE_CHECKS["ccv_frequency"]`
  is still `[]`. Nothing verifies that a produced run *actually carried* a CCV
  every N injections after the fact; §4's and §13's entries on this stay open.
  What changed here is narrower and upstream of that: the build-time interval
  itself is now project-overridable and provenance-bearing, not that
  compliance with it is checked post-hoc.
- **No UI sets a project-tier composition criterion yet.** Exactly the same
  gap §20 recorded for the numeric criteria — `ruleset.set_project_criterion()`
  works and is tested, but nothing in `@@pfas-projects` calls it for any key,
  numeric or compositional. The positive case (a project actually forcing
  duplicates and a tighter LFSM/CCV interval into a built run) WAS proven
  live — a throwaway `PFASProject` was linked to B-002, given
  `ccv_frequency=3` / `lfsm_frequency=2` / `duplicate_all_samples=True`, and
  the real sequence was rebuilt through `build_sequence()` (see the bug
  writeup above) — but only via a one-off `bin/instance run` script with
  `transaction.abort()`, never committed, and the temp project was deleted
  immediately after. No lab user can reach this through the UI today.
- **`run_composition._QC_ROLE_CODES` is a second, hardcoded copy of a
  vocabulary that already lives in `run_builder._noncount_codes()` /
  `_blank_codes()` (Reference-Definition-driven) — by necessity, since
  deriving it the same way needs Zope and this module must stay Zope-free
  to be unit-testable at all (see this task's report). A QC code added to
  the RefDef vocabulary later and not also added here falls through to
  `classify_sample_role()`'s id-guess — safe under the direction rule (it
  reads as a field sample, so it gets MORE QC applied, not less) but silent.
- **The `is_field_sample()` pre-existing MB-id quirk now has a live
  consequence.** `classify_sample_role()`'s MB match is `"MB" in
  sid.split()` — a literal, space-separated token, copied verbatim from the
  original `run_builder._role_from_sample` (pre-existing, out of scope to
  fix here). A method blank registered with the id shape `_qc_injection`
  itself generates — `FDA_32PFAS-MB-260923-01`, hyphenated — does NOT match,
  so it classifies as `""` (a field sample). Before this task that only
  risked a redundant MB injection (§1.3's shape, harmless over-QC). Now that
  `is_field_sample()` rides on the same classifier, such a row would ALSO
  get duplicated under `duplicate_all_samples` and counted toward the LFSM
  interval. The live verification's own MB/blank rows were saved by an
  explicit `role` field from the extraction log (`role="LFSM"` for the one
  QC-role row present); a batch whose extraction log leaves `role` blank on
  a hyphenated MB id would not be.
- **The surrogate-composition class ("an additional surrogate is used")
  remains unbuilt, deliberately.** It is a different kind of override than
  either the numeric criteria or the two composition keys here: it would add
  a new analyte relationship (which injection standard a QAPP wants used to
  quantify a given native) rather than override an existing one's cadence or
  count. CLAUDE.md §3 makes the surrogate-to-IS map a method-owned
  single-source fact; §9 already shows what duplicating it produces. Building
  a project-tier override for it needs its own design decision — where the
  override is stored, whether it can name a standard the method's own map
  does not carry, how a certificate discloses a per-project quantification
  ion — not an extension of this module's shape.

## 26. The resolved-criteria record is now frozen at the moment it judges
##     (2026-09-23)

Closes §24. The per-batch file (`resolved_criteria_store.write_resolved_
file()`) still overwrites unconditionally and is unchanged — it stays what
it always should have been: a freely regenerable working artefact for the
Py3 pipeline worker's *next* run. What changed is that history no longer
depends on it.

### What is frozen, and where

A new ZODB annotation on the **Worksheet** —
`senaite.pfas.worksheet_criteria_snapshot` (module of the same name, key
`SNAPSHOT_KEY`) — holding the full resolved rows (value, tier, source_doc,
source_rev, conformance, departure — `resolved_criteria_store._row_from_
resolved()`'s exact shape, unchanged) plus `batch_id`, `method_id`,
`matrix`, and `frozen_at`. Per CLAUDE.md §7: this is data belonging to
exactly one ZODB object (the worksheet that was judged), so it is annotated
onto that object, not written to SQLite or the filesystem.

**The hook point** is `src/senaite/pfas/browser/data_review.py`,
`_handle_approve_release()` — the ISO 17025 §7.8.4 technical review itself:
immediately after the worksheet's analyses and the worksheet transition to
`verified` (right after the `wf_tool.doActionFor(ws, "verify")` block, before
the checklist bookkeeping), a new `self._freeze_resolved_criteria(ws)` call
gathers the linked Batch (`_linked_batch`), `method_id` (`batch_method`), and
`matrix` (`_batch_matrix`) — the same three sources every other panel on
this view already uses — and delegates to
`worksheet_criteria_snapshot.freeze_resolved_criteria()`. The whole call is
wrapped in its own `try/except` in `_handle_approve_release`, on top of
`freeze_resolved_criteria()`'s own internal guards: record-keeping must
never be able to block a workflow transition that has already happened
(requirement 3).

### The write-once guarantee, and how it is enforced

`worksheet_criteria_snapshot.store_snapshot(store, payload)` is the single
choke point that writes `SNAPSHOT_KEY`. It checks whether a payload with
`status == "frozen"` is already present; if so it returns `(False,
<the original payload, untouched>)` and does **not** write. Every other
status (`"unresolved"`, `"failed"`, or nothing at all) may be replaced —
those are not judgement history, because nothing was judged. The real
trigger this protects against is retract → fix something → re-submit →
re-approve on the same worksheet, or a project re-link followed by someone
re-running the approval handler: `tests/test_worksheet_criteria_snapshot.py
::test_second_verification_does_not_overwrite_the_frozen_snapshot` simulates
exactly that (freezes with FDA_32PFAS/Eggs, then calls
`freeze_resolved_criteria()` again with EPA_1633A/Drinking Water on the SAME
worksheet object, and asserts the second call returns the FIRST result,
`frozen_at` included).

Three states, not two — an empty `criteria` list is never stamped `"frozen"`:

| status | meaning | may a later attempt replace it? |
|---|---|---|
| `frozen` | resolution succeeded; `criteria` holds the rows | **No — this is the guarantee.** |
| `unresolved` | method_id/matrix not both known at verification time; resolution never attempted (mirrors `export_resolved_criteria`'s own refusal to write a partial/guessed file) | Yes |
| `failed` | method_id/matrix known, resolution raised | Yes — including by a subsequent `frozen` payload, which carries the failed marker forward under its own `superseded` key so a "failed once, then froze on retry" history is never silently erased by the fix that made it succeed |

`tests/test_worksheet_criteria_snapshot.py::test_unresolved_when_method_or_
matrix_unknown_never_an_empty_frozen_payload` pins the `unresolved` case;
`test_build_failure_marker_carries_superseded_marker_forward` and
`test_store_snapshot_replaces_unresolved_and_failed_markers` pin a
failed→failed retry; `test_failed_then_fixed_retry_carries_the_failure_
forward_as_superseded` is the one that matters most and was initially
missing — an earlier version of this change let `build_snapshot_payload()`
(the SUCCESS path) drop the prior marker on the floor, which would have
silently erased a recorded failure the moment the retry that followed it
succeeded. `build_snapshot_payload()` now also takes `superseded`, and
`freeze_resolved_criteria()` passes the pre-existing marker (if any) on
every path, not just failure→failure.

### What a reader gets when no snapshot exists

`worksheet_criteria_snapshot.get_frozen_criteria(ws)` is the ONLY sanctioned
way to ask "what governed this worksheet's batch?" It returns a deep copy of
the frozen payload, or **`None`** if nothing was ever frozen — every
worksheet verified before this change, and any worksheet approved through a
code path that predates this hook. `None` (or a non-`"frozen"` status) means
**not recorded**; a caller must present exactly that, in those words or
equivalent, and must never fall back to resolving live criteria and
presenting the result as if it were history. That is §15's rule (UNKNOWN
must never read as CONFORMS) applied to the time axis, and it is the failure
§24 exists to prevent — `tests/test_worksheet_criteria_snapshot.py
::test_worksheet_with_no_snapshot_reports_not_recorded` pins it.
`read_snapshot()` returns a `copy.deepcopy` specifically so a reader cannot
mutate the frozen record through the dict it was handed back
(`test_read_snapshot_returns_a_deep_copy_not_the_live_dict`).

No existing UI reads resolved criteria as a history claim today — the one
browser-side consumer of `ruleset`/`resolve_for_batch` besides this feature,
`browser/batch_project_viewlet.py`, only ever shows the CURRENT project/QAPP
link and derives `method_id`/`matrix` best-effort for a NEW assignment; it
never displays a resolved value or a departure and is correctly a
build-time/"what would we do now" view, not a history one — it needed no
change. The disclosure work this section is a precondition for (§24's
closing paragraph) is the first intended consumer of `get_frozen_criteria()`.

### What remains mutable by design

- **The per-batch file** (`{resolved-dir}/{batch_id}.json`, written by
  `resolved_criteria_store.write_resolved_file()`) — unchanged, still
  overwritten unconditionally on every `project_ref.set_project_uid()` call.
  It is consumed only by the Py3 pipeline worker's *next* run and carries no
  historical claim; nothing reads it for "what governed" anymore.
- **Live QC criteria themselves** (method profiles, QAPP/project rulesets) —
  still fully editable at any time, by design; a QAPP revision or profile
  correction must be able to change what governs FUTURE runs. Only the
  worksheet's own frozen copy of a PAST resolution is protected.
- **A worksheet in `open` or `to_be_verified`** has no snapshot yet, and
  correctly so — nothing has been judged. `get_frozen_criteria()` on such a
  worksheet returns `None`, same as "not recorded"; that is accurate, not a
  gap, until the §7.8.4 review actually happens.
- ~~**A worksheet verified through a route OTHER than `@@pfas-data-review`'s
  Approve action never gets a snapshot at all.**~~ **CLOSED, see §26.1.**
  The hook lived in `_handle_approve_release()`, which made the freeze a
  property of one button: a Manager verifying the underlying analyses from a
  native SENAITE listing — the path §5 records as historically the one that
  actually worked, before the checklist handler's workflow cascade was fixed —
  reached `verified` with no snapshot. Safe by construction (`None` /
  "not recorded", never a fabricated answer) but silently zero disclosure
  basis for a lab that releases outside this one workspace.

### 26.1 The freeze is a property of the transition, not of a button

`data_review.on_after_transition` is registered on
`Products.DCWorkflow.interfaces.IAfterTransitionEvent` in
`browser/configure.zcml`, beside `controlled_publications.on_after_transition`
— which exists for the same reason, so that an immutable issuance entry is
written every time a CoA is published rather than every time someone uses the
expected screen.

**One producer, not two.** The direct call in `_handle_approve_release()` is
removed. That handler's own `doActionFor(ws, "verify")` is now what fires the
freeze. Two call sites writing one record is the dead-twin shape removed twice
already (§2 A4, §4); write-once remains a safety property rather than a licence
to write from two places.

**The guard is exact and lives once.** `worksheet_criteria_snapshot.should_freeze
(portal_type, transition_id)` is Zope-free and returns True only for a
`Worksheet` completing `verify`. It is the reject-fast path of a handler that
runs on **every** workflow transition in the site: `AnalysisRequest`, `Analysis`
and others all have a `verify` transition and all fire this subscriber, so
freezing on any of them would write a snapshot onto an object whose criteria
nobody asked about. Three tests cover the matrix.

**It cannot abort a transaction.** A subscriber that raises rolls back the
transition it was watching — here, the verification itself. The handler's body
is wrapped whole, and `freeze_resolved_criteria()` already never raises. A
record-keeping failure logs and leaves a `failed` marker; it does not undo a
review that happened.

Confirmed registered in the running instance, not merely present in ZCML:
`getGlobalSiteManager().registeredHandlers()` lists
`senaite.pfas.browser.data_review.on_after_transition` with
`required=['Interface', 'IAfterTransitionEvent']`.

### Refactor along the way

`resolved_criteria_store.export_resolved_criteria()`'s row-resolution loop
(project → lab → baseline for every `SHAPES_BY_KEY` entry) is extracted into
a new `resolve_rows_for_batch(portal, batch, method_id, matrix)`, called by
both `export_resolved_criteria()` (writes the working file) and
`worksheet_criteria_snapshot.freeze_resolved_criteria()` (freezes the
worksheet snapshot) — one resolution path, not two (CLAUDE.md §3).
`tests/test_resolved_criteria_store.py` (unchanged, still green) pins the
behavior this was extracted from.

### Verification

- `tests/test_worksheet_criteria_snapshot.py` — 14 new tests: payload shape,
  write-once on `store_snapshot()` directly, replacement of `unresolved`/
  `failed` markers, `None` on no snapshot, deep-copy on read (both from
  `read_snapshot()` and from `freeze_resolved_criteria()`'s own
  already-frozen early return), provenance round-trip through the real
  `resolved_criteria_store.build_resolved_rows()` (tier/source_doc/
  source_rev/conformance/departure all survive a `json.dumps`/`loads`
  cycle), and five thin-shell tests that exercise
  `freeze_resolved_criteria()`/`get_frozen_criteria()` end to end against a
  faked `zope.annotation.interfaces.IAnnotations` (a per-object attribute,
  not an `id(obj)`-keyed registry that could collide after GC) — including
  the literal "verify, then re-verify" scenario and the failed→fixed→frozen
  supersession chain.
- Full suite (`tests/*.py`, one invocation) green: every existing file
  unchanged in behavior, `test_resolved_criteria_store.py` still green after
  the `resolve_rows_for_batch` extraction.
- Live, under the real Zope Python 2.7 environment (`bin/zopepy`, not the
  plain-python3 test harness): `senaite.pfas.worksheet_criteria_snapshot`
  and `senaite.pfas.resolved_criteria_store.resolve_rows_for_batch` import
  cleanly; `senaite.pfas.browser.data_review.PFASDataReviewView` carries the
  new `_freeze_resolved_criteria` method.
- Live, after restarting the `senaite` container: `@@pfas-data-review` and
  `@@pfas-projects` both still return `200`.
- **Not exercised**: an actual verify → freeze → re-verify cycle against a
  real worksheet on the running instance. The task's own instruction was to
  do this only against a worksheet that could be restored and was not part
  of the lab's real reported work; no such disposable worksheet was
  identified this session, so this relies on the unit coverage above (which
  drives the real `freeze_resolved_criteria()`/`store_snapshot()` code, not
  a reimplementation of it) plus the live import/200 checks. Flagged here
  rather than silently skipped.

---

## 27. Data Review 500'd for the two states it exists to review (2026-09-23)

Found while verifying an unrelated banner, by loading the page against a real
worksheet in **each** review state instead of one convenient one.

### The defect

`data_review.PFASDataReviewView.spike_qc_page()` had three early returns:

```python
if not self.db_available:      return {"rows": [], "types": []}
if ws is None:                 return {"rows": [], "types": []}
if summary.get("error"):       return {"rows": [], "types": [], "error": ...}
```

The template dereferences `page/pending_spikes` and `page['specs']`
unconditionally (`data_review.pt:1012,1020,1046`). A missing key in a TAL path
raises `LocationError`, and because the expression sits inside the shared page
macro, it took down the **entire Data Review page** — not the Spike QC pane.

The trigger is a worksheet whose QC summary returns `no_batch_record`, i.e. one
with no rows in the QC store. Live, before the fix:

| Worksheet | State | Result |
|---|---|---|
| WS-0001 | `open` | 200 — happened to have QC rows |
| WS-0003 | `to_be_verified` | **500** |
| WS-0004 | `verified` | **500** |

So the page was broken for exactly the two states it exists to serve: a
worksheet awaiting review, and one already reviewed. Every exit now returns the
same keys.

### Why it survived this long

Every prior check was satisfied by a 200 that proved nothing:

- `curl @@pfas-data-review` with no worksheet renders the **worklist**, a
  different code path that never touches `spike_qc_page`.
- The one worksheet anybody loaded by hand had QC rows.

§5 records this page driving a sample to `verified` and publishing a
certificate, which is true — that worksheet had QC data. The failure needs a
worksheet without it, and nothing had ever asked for one.

### The rule

**A page that renders is not a page that works, and the case that gets loaded
is rarely the case that breaks.** Four defects this cycle were found only by
real data or a real request, none by the tests written beside the code:

- the Projects UI 500 (`--` in a template comment) — invisible to every static check
- composition applying to zero rows while its whole suite passed, because
  fixtures used `role=""` and reality uses `role="Sample"`
- a test that actively certified the MB classification bug as expected behaviour
- this one, where the only worksheet ever loaded by hand was the one that worked

The fault-injection harness is the standing exception, and the reason is
structural: it asserts against an independently built manifest rather than
against the implementation's own idea of itself. Tests written beside code
inherit its assumptions; a page loaded against arbitrary real data does not.

### Also in this entry: the disclosure is surfaced

`disclosure.build_disclosure()` (§26's frozen snapshot → a statement) now
renders as a banner above the Data Review tabs, so a reviewer cannot approve an
out-of-scope report without being told. Three modes, because criteria freeze AT
verification and conflating them would recreate §24:

- **preview** — not verified yet: what *would* be recorded, labelled as such
- **recorded** — verified with a snapshot: what *did* govern the results
- **not_recorded** — verified WITHOUT one: says so, and deliberately does not
  substitute live criteria

WS-0004 exercises the third path live and reports "not recorded" rather than
presenting today's criteria as history.
