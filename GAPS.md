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
python3 tools/audit_configurable.py --profiles data/qc/method_profiles.json \
    --strict && \
python3 tools/wiring_map.py > WIRING.md && \
python3 tools/generate_synthetic_runs.py --out /tmp/synth --list
```

`--strict` is live as of 2026-09-25: the audit now EXITS NON-ZERO on a profile
key the code reads that nothing writes. It was held back deliberately while two
such keys existed (`extraction_logbook`, `internal_standards` — §30), because a
gate that fails by default teaches you to ignore it. Both are closed, so the
count is 0 and the block breaks if a new one appears.

Last updated: 2026-09-25 — 26/26 test files pass, audit DEAD 0 / UNREACHABLE 0
/ SPLIT 0 / NO PRODUCER 0, wiring §1.4 real duplicates 0 / §5 orphans 0.

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

## 28. The project tier is reachable for the first time — a QAPP criteria
##     editor on the Projects UI (2026-09-24)

Every prior entry in this file assumed the project tier of `senaite.pfas.
ruleset` would eventually be written to. It never was. `ruleset.
set_project_criterion` / `set_project_ruleset` had zero call sites outside
their own definitions and tests -- so every resolved criterion, on every
batch, forever, read `tier: "lab"`. No departure could ever exist. The
out-of-scope disclosure (`disclosure.build_disclosure`, wired to the Data
Review banner in §27) had a fully correct, fully tested rendering path for a
state that could never occur. This entry closes that.

### What was built

`@@pfas-projects` (`browser/projects.py` / `templates/projects.pt`) gained a
"QAPP Criteria" panel per project, scoped **method x matrix** like every
other analyte-bearing structure (CLAUDE.md §3 rule 2): pick a method, pick
one of its matrices, and every one of ruleset.py's 8 registered keys is
editable there --

  - `cal_r2_min`, `sn_quan_min`, `dup_rpd_max` — a single number field
  - `ccv_recovery` — a min/max window
  - `ccv_frequency`, `lfsm_frequency` — an integer interval
  - `duplicate_all_samples` — a tri-state select (inherit / true / false)
  - `eis_recovery` — analyte-scoped, so it gets its own sub-panel: a table of
    every analyte already overridden (with a per-row Clear), plus an
    add/update mini-form keyed on an analyte picker

`eis_recovery` was **not** treated as optional, per the task brief: it is the
only key with a seeded published-method baseline (EPA 1633A Tables 6/8,
Q-004), so it is the only key that can ever produce a DEPARTS verdict. Every
other key resolves UNKNOWN forever (no baseline registered -- see method_
baselines.py's SEEDING DISCIPLINE) and the editor's own conformance column
shows exactly that live, honestly, rather than hiding a column that mostly
says UNKNOWN.

Every value shown -- inherited AND currently-effective -- is produced by
`ruleset.resolve()`, called twice per row (once with the project's real
ruleset, once with `project_ruleset=None`) -- never read off the method
profile directly. The second call is what makes "what happens if you clear
it" a provable claim rather than a guess: it is the literal resolve() call
a clear produces.

### The four things the task called out, and how each was met

**1. Writes go through `set_project_criterion` only, one key at a time.**
Both handlers (`_handle_save_criteria`, `_handle_save_eis_criterion`,
`_handle_clear_eis_criterion`) parse the whole form FIRST -- a bad number
anywhere aborts the entire save before any write happens -- then loop over
the 8 keys calling `ruleset.set_project_criterion(project, method_id, matrix,
key, value)` individually. `set_project_ruleset` (the wholesale-replace
function) is never called from this editor. `eis_recovery`'s per-analyte
shape is one level deeper (its stored node is `{analyte: {min,max}, ...}`,
not a scalar), so `_set_eis_analyte()` reads that one node via `ruleset.
get_project_ruleset()`, edits ONE analyte's entry, and writes the whole node
back through `set_project_criterion` -- still one key, per that function's
own merge contract; only the key's own shape is nested.

**2. Clearing falls back to the lab tier, proven by test.** The editor
clears a scalar/window/int/bool key by calling `set_project_criterion(...,
key, None)` -- the SAME function, not a second write path. `ruleset.
_project_value()`'s `if node is None: return None` already treats a stored
None as silence (verified, not assumed), so resolution falls through to lab.
`tests/test_ruleset.py::test_clearing_a_project_criterion_falls_back_to_lab_tier`
asserts `tier == "lab"`, `value == <the lab's real number>`, and `value is
not None` -- the third assertion is the one that would catch a project tier
silently carrying None. A second test,
`test_clearing_one_eis_analyte_override_does_not_leak_to_a_sibling`, proves
the per-analyte isolation `_set_eis_analyte` exists for: clearing one
analyte's eis_recovery override leaves a sibling analyte's override on the
same (method, matrix, key) node fully intact at `tier == "project"`.

**3. A criteria edit refreshes every linked batch's resolved-criteria
file.** `_refresh_resolved_criteria_for_project()` walks `batch_ref.
list_batches(portal)` -- every Batch in the site -- and calls `project_ref.
get_project_uid(batch)` on each, comparing against the edited project's REAL
Plone UID (`bika_api.get_uid(project_obj)`, never the folder id the
`?uid=` query param carries -- `batch_project_viewlet.py`'s own docstring
warns these differ). For every batch that matches, it derives that batch's
own method_id/matrix (reusing `batch_project_viewlet._batch_method_id` /
`_batch_matrix` -- not a second derivation path) and calls `resolved_
criteria_store.export_resolved_criteria()` again, wrapped in a per-batch
try/except so one batch's export failure (that function raises on I/O
failure, unlike `project_ref`'s own caller, which swallows it) cannot 500 a
save that already succeeded in ZODB. The ok-message reports how many batches
were refreshed and how many were skipped, so a save is never silently
ineffective for the worker.

**What this does NOT close**: there is no reverse index from Project to
Batch -- the link is an annotation on the Batch (`project_ref.
PROJECT_UID_KEY`), not a back-reference on the Project. `_refresh_
resolved_criteria_for_project` is therefore a site-wide linear scan, the same
cost `batch_ref.list_batches()` already documents as the cheap option when
no catalog metadata exists for what is being searched. Fine at today's scale;
if it ever is not, the fix is a catalog index on that annotation, not
anything in this editor.

**4. Manager-gated both ways.** `save_criteria` / `save_eis_criterion` /
`clear_eis_criterion` all run through the same `require_manager` 403 gate the
existing add/edit/delete actions use. The whole panel (`tal:condition="python:
view.can_manage() and view.criteria_uid()"`) is absent from the rendered HTML
for a non-manager -- not hidden by CSS -- per CLAUDE.md §6A.

### A pre-existing defect this work exposed, and fixed in passing

Creating the FIRST-EVER QAPP document and selecting it in the existing "New
Project" form's QAPP dropdown 500'd `@@pfas-projects` outright:

```
UnicodeDecodeError: 'ascii' codec can't decode byte 0xe2 in position 3
```

`templates/projects.pt`'s QAPP `<option>` label was built as `python:'%s —
%s' % (q['sop_id'], q['title'])` -- a **byte-string** literal (TAL `python:`
expressions are not affected by a `.py` file's `from __future__ import
unicode_literals`) containing the UTF-8 bytes of an em-dash, combined via `%`
with `q['title']`, which is `unicode` (JSON-decoded). Python 2 tried to
ASCII-decode the byte-string literal to reconcile the mix, and the em-dash's
lead byte (`0xE2`) is not valid ASCII. This is exactly this project's
recurring shape (§27's rule: "the case that gets loaded is rarely the case
that breaks") -- `qapp_docs()` had always returned `[]` before today, so the
`tal:repeat` loop containing this expression had never actually executed it.
The very first QAPP this system ever had triggered a defect that had been
sitting in the template since the Projects UI shipped. Fixed by prefixing the
literal `u'%s — %s'` (and the one other place this editor's own new markup
did the same thing, in the criteria panel's header). Left everywhere else in
the codebase alone -- this was the one instance blocking this task's own
required live verification, not a general audit.

### End-to-end evidence (live, against the running instance)

A real Project (`E2E-D63-TEST`, uid `754b95326f164d4fb9012ba08c42e962`) was
created and linked to a real QAPP document (`QAPP-001`, revision 1, activated
so provenance would populate). An `eis_recovery` override for
`EPA_1633A` / `Groundwater` / `13C4-PFBA` was set to `{"min": 0.0, "max":
200.0}` -- looser at both ends than the seeded EPA 1633A Table 6 baseline
(`5.0`-`130.0`). Resolving it (`ruleset.resolve`, run inside the actual Zope
instance via `bin/instance run`) reported, verbatim:

```
tier: project
conformance: DEPARTS
value: {'max': 200.0, 'min': 0.0}
source_doc / source_rev: QAPP-001 / 1
departure.ends:
  min floor loosened: method requires >= 5.0, resolved value allows >= 0.0
  max ceiling loosened: method requires <= 130.0, resolved value allows <= 200.0
citation: EPA 1633A (December 2024, EPA 820-R-24-007), Tables 6 and 8 ...
```

Feeding a snapshot built from that row into `disclosure.build_disclosure()`
reported `outcome: departs_from_method`, `out_of_scope: True`, and one
itemised line via `format_departure()`:

```
eis_recovery (13C4-PFBA): {'max': 200.0, 'min': 0.0} applied per QAPP-001
rev 1, where the method requires {'max': 130.0, 'min': 5.0} (min floor
loosened: method requires >= 5.0, resolved value allows >= 0.0; max ceiling
loosened: method requires <= 130.0, resolved value allows <= 200.0)
[EPA 1633A (December 2024, EPA 820-R-24-007), Tables 6 and 8 ...]
```

The DEPARTS badge rendered live on the `@@pfas-projects` criteria panel
itself, not just in a script. Clearing the override (`clear_eis_criterion`
via the same POST handler the UI uses) then re-resolving reported:

```
tier: lab
value: {'max': 130.0, 'min': 5.0}
conformance: CONFORMS
```

-- the lab's real value, not a project tier carrying None. The general
(non-analyte-scoped) path was exercised too: `dup_rpd_max` was set to `25.0`
(tier flipped to `project`), then cleared (tier returned to `lab`, value
`30.0` -- the lab's real configured RPD ceiling).

**Item 3's refresh loop was proven live, not just by unit test on its pure
half.** A second, real Batch (`B-002`, an existing FDA_32PFAS x Eggs batch --
not fabricated for this test) was linked to a second test project (`E2E-D63-
REFRESH` / `QAPP-002`) via the actual `@@pfas-batch-project-assign` endpoint,
which reported "resolved criteria exported" and wrote a baseline `/data/qc/
resolved/B-002.json` with `dup_rpd_max: {tier: lab, value: 20.0}`. Editing
that project's `dup_rpd_max` to `12.0` through the new criteria editor
reported `"1 batch(es) refreshed"` (not the `"0 batch(es)"` a project with no
linked batch reports), and the file on disk changed under it: `dup_rpd_max`
now read `{tier: project, value: 12.0, source_doc: "QAPP-002", source_rev:
1}`, with a newer mtime. Clearing the criterion reported `"1 batch(es)
refreshed"` again and the file returned to `{tier: lab, value: 20.0,
source_doc: null}`. This is the file the Py3 worker actually overlays --
confirmed changing, not merely exercised in isolation.

An earlier draft of this entry claimed the refresh loop was "exercised by
unit test" when in fact `_refresh_resolved_criteria_for_project`'s body --
the UID comparison, the method/matrix derivation, the per-batch try/except --
had zero coverage at that point (the first test project had no linked batch,
so the loop body never ran; `test_resolved_criteria_store.py` tests only the
pure `build_resolved_rows`/`write_resolved_file` half). That draft also
passed `request=None` into `_batch_method_id()`, which -- silently, inside a
swallowed try/except -- would have degraded every real batch to "method/
matrix not known" the first time this ran against one. Caught before commit;
fixed to thread the handler's real `self.request` through, and the B-002 run
above is what actually exercises that fixed path.

Cleanup: both test Projects were deleted via the same `action=delete` handler
every project uses (`?ok=Project+deleted`, confirmed absent from the listing
afterward); both test QAPPs were archived via `@@pfas-sop`'s existing soft-
delete (`action=delete_sop` -- this module keeps archived documents for audit
rather than hard-deleting, matching every other controlled document in the
system, so "removed" here means removed from active use exactly as it does
for every SOP/JA/Supplemental in the registry); B-002's project link was
cleared via `@@pfas-batch-project-assign`'s `clear` action, which deleted its
resolved-criteria file too, restoring it to exactly its pre-test state (no
project link, no resolved file). All confirmed live.

### Suite / live status

Full suite (`tests/*.py`, one invocation) green, including two new tests in
`test_ruleset.py` for the clearing/isolation guarantees above. `@@pfas-
projects` and `@@pfas-data-review` both `200` after a restart.

### What is still open

- No reverse index Project -> Batch (noted above under item 3) -- a
  linear scan today, fine at lab scale.
- The 7 non-`eis_recovery` keys have no seeded baseline anywhere
  (method_baselines.py's SEEDING DISCIPLINE, unchanged by this work) -- an
  operator can override them at the project tier, and the UI shows exactly
  that ("UNKNOWN", not invented), but none of them can ever show DEPARTS
  until a citable baseline is added for one, which is a data-verification
  task, not a code gap.
- The editor writes the project tier; nothing yet prompts an operator to open
  it when a new QAPP is attached to a project, or warns a QAPP revision was
  superseded while an override citing the old revision is still live. Both
  are workflow nudges, not correctness gaps -- `source_rev` is still recorded
  accurately at the moment of resolution either way.

---

## 29. Containment is not output (2026-09-24)

Two defects in a single sentence, both shipped past a fully green suite, both
found by reading one line of real output.

The sentence is `disclosure.format_departure()`'s — the itemised
non-conformance statement printed on a client's certificate. Its entire purpose
is that a human can read it and tell what changed.

### 29.1 A Python dict on a certificate

Window criteria travel as `{"min": x, "max": y}`. Interpolated raw, the
certificate read:

> where the method requires `{'min': 5.0, 'max': 130.0}`

Now rendered through `format_value()`: `5.0-130.0`, `>= 5.0` for a half-open
window, `required` / `not required` for a boolean.

### 29.2 The lab's own registers on a client document

`EIS_CITATION` appended the internal verification trail — *"Verified against
the official PDF -- QUESTIONS.md Q-004, closed 2026-06-19 (DECISIONS.md same
date)"* — and it printed. Two problems at once: internal bookkeeping on a
client-facing document, and a duplication of the comment sitting directly above
the constant, so §1 rule 3 was already broken and the leak was only its visible
symptom. The citation now names the regulatory authority and stops.

### Why a green suite missed both

**Every assertion checked that a fragment was PRESENT.**

```python
assert "5.0" in line          # passes for 5.0-130.0 AND for {'min': 5.0}
```

Worse, the fixture that appeared to prove formatting — `"applied_value":
"40-140%"` — was a string **I had written by hand**. The test proved that a
value I supplied pre-formatted survived interpolation. The code's own
formatting had never been exercised at all.

`assert X in output` is a containment test. It answers "is this present",
never "is this right". For anything a person reads, those are different
questions, and only the second one matters.

The new tests assert `"{" not in line`, and that no citation contains
`QUESTIONS.md` / `DECISIONS.md` / `GAPS.md` / `Q-004`.

### The taxonomy this completes

Five defects this cycle, none caught by tests written beside the code:

| Shape | Instance |
|---|---|
| Tests sharing the code's assumptions | composition applied to zero rows — fixtures used `role=""`, reality uses `role="Sample"` |
| A test certifying the bug as expected | MB classification asserted `FDA-MB-01` → `""`, comment calling it out of scope |
| A code path never given data | Projects UI 500 (`--` in a comment); the em-dash crash that needed the first QAPP to exist |
| A page never loaded in the failing case | Data Review 500 for `to_be_verified`/`verified` (§27) |
| **Assertions about containment, not output** | **§29.1, §29.2** |

The fault-injection harness remains the standing exception for one structural
reason: it asserts against an independently built manifest, not against the
implementation's own idea of itself. Everything else on that list was written
by the same mind, at the same time, as the thing it was checking.

**The working rule:** for any artefact a person reads, print it and read it.
No assertion about its substrings is a substitute.

---

## 30. Surrogate recovery: both halves existed, and had never met (2026-09-25)

`recovery_check_profiled()` had exactly **one** call site in the whole system —
`run_queue.py`, passing the literal `"LFSM"`. Nothing ever asked it for a
surrogate window. So this entire chain was unreachable from a live run:

```
EPA 1633A Tables 6/8 per-analyte limits   (seeded, 24 analytes)
  -> qc_acceptance.LFSM tiers as the base  (configured)
  -> eis_matrix_overrides per matrix class (configured)
  -> ruleset.resolve three tiers, QAPP above lab   (§15, tested)
  -> resolved_criteria_store export              (§17, tested)
  -> worker overlay per batch                    (§22, tested)
  -> EPA1633AProfile.qc_rules(..., "EIS")        <-- NOTHING CALLS THIS
```

Task #8 was marked complete on the strength of everything above the last line.
Each layer was individually tested and correct. The thing none of those tests
could see is that the last arrow does not exist.

On the other side of the same check, `InstrumentRow.pct_recovery_is` — column 30
of the export, the instrument's own % recovery for each labelled compound,
parsed by `importer`, mapped in `instrument_columns`, carried on every row — was
read by **nothing**. Both halves of surrogate recovery monitoring were present,
configured and tested, and no line of code connected them.

### 30.1 And the loop above it iterated nothing

`get_is_list()` read a profile key `internal_standards` that no editor field, no
seed and no migration has ever written, falling back to an inline FDA list. So
it returned 21 names for FDA and **`[]` for both EPA methods** — the `is_response`
loop iterated an empty list and no labelled compound was checked at all on EPA
537.1 or EPA 1633A (§19). This is the key that held `--strict` back.

It is now derived, not stored: `{surrogate_map values} + {injection IS}`, keyword
to display name. Both inputs are already method-scoped, and every name it yields
exists as an AnalysisService — which matters, see below.

### 30.2 The names diverge, and it is not a spelling problem

EPA 1633A's `eis_overrides` is keyed by **Table 6's own designations**. Ten of
the twenty-four name compounds that exist as **no AnalysisService at all**,
because `setupdata/internal_standards.csv` is the only thing that creates them
and it carries the lab's catalogue spellings:

| Table 6 (EPA 820-R-24-007) | The lab's catalogue | Same substance? |
|---|---|---|
| `13C4-PFBA`   | `13C3-PFBA`   | **No** — four ¹³C vs three |
| `13C5-PFPeA`  | `13C3-PFPeA`  | **No** |
| `13C6-PFDA`   | `13C2-PFDA`   | **No** |
| `13C9-PFNA`   | `13C5-PFNA`   | **No** |
| `13C2-4:2FTS` | `13C2,D4-4:2FTS` | probably — abbreviation |
| `13C2-6:2FTS` | `13C2,D4-6:2FTS` | probably |
| `13C2-8:2FTS` | `13C2,D4-8:2FTS` | probably |
| `13C3-HFPO-DA`| `13C3-GenX (HFPO-DA)` | yes — native synonym |
| `13C7-PFUnA`  | `13C2-PFUDA`  | native synonym, **different label** |
| `13C8-PFOSA`  | `13C8-FOSA`   | yes — native synonym |

**This is an open question for the QA manager, not a code question.** Four of
these are unambiguously different isotopologues from the ones EPA 1633A
specifies. Whether the lab should be purchasing EPA's isotopologues, or whether
the catalogue is right and Table 6's designations are being read too literally,
is a purchasing-and-method decision. Nothing in this repo can settle it.

Worth stating plainly because it bears on §9: that entry recorded the surrogate
maps as "proven" by reproducing the hand-maintained FDA/1633A maps exactly. That
proves the derivation is self-consistent with what was already there. It says
**nothing** about whether the 1633A entries were ever right for 1633A. Same
shape as the §22.1 mistake — a check that confirms agreement with an existing
value, mistaken for a check that the value is correct.

### 30.3 What was implemented instead

The join is on the **native** the standard labels, never on the labelled name:

```
instrument name -> keyword -> native (INTERNAL_STANDARDS row[2])
                -> the Table 6 row whose designation labels that native
```

This embeds no claim that `13C3-PFBA` and `13C4-PFBA` are one substance. It
claims only that whatever the lab spikes as PFBA's extracted internal standard
is judged against the method's limit *for PFBA's EIS* — the relationship Table 6
actually states. The flag keeps the lab's name, so a certificate names what was
in the vial while the limit comes from the method.

Proven total, not assumed: of 24 Table 6 designations, 21 reach a native by
stripping the isotopic label alone, and the 3 that do not (`HFPO-DA`, `PFUnA`,
`PFOSA`) are **exactly** the 3 natives the method's own surrogate map leaves
otherwise uncovered. Complementary sets, a 24/24 bijection once the injection
standard is excluded, and `test_the_table_6_join_is_total_and_one_to_one` fails
if that ever drifts.

The injection standard (`13C4-PFOA`) is excluded from recovery: it goes in at
reconstitution, *after* extraction, so it has no recovery to measure — its area
is what `KIND_IS_RESPONSE` tests. It stays in `get_is_list` for that check.

`surrogate_recovery` is declared on the extracted injection types only (Sample,
LFSM, LFSMD, Dup, LFB, MB, MxB, LRB) and not on CAL/ICV/CCV/CCB, which are
prepared in solvent. `_is_extracted()` derives "was this extracted" *from that
declaration* rather than keeping a second list of QC codes, so the loop and the
review queue cannot disagree.

### 30.4 The test that would have caught it, and the one that would not

The discriminator is chosen so it can only pass if the name join works. Table 6
floors PFBA's EIS at **5%** and PFPeA's at **40%**; the generic window floors
both at 40%. One run, both compounds at 20% recovery:

* a lookup on the instrument's name misses both, applies 40–130 to each, and
  fails **both**
* the native join applies 5–130 and 40–130, so PFBA **passes** and PFPeA fails

A test asserting `get_is_list()` is non-empty passes in a world where the EIS
branch is still unreachable. A test asserting the window equals 5–130 passes in a
world where nothing evaluates it. Only a test that runs the queue and reads the
*check status* distinguishes all three.

### The rule this adds

Seven entries now share one shape: a criterion that resolves, exports, overlays,
persists and renders — and is never *asked for*. §12 named it ("implemented but
never wired"), §19 and §22.2 repeated it, and this is the largest instance yet.

**A layer-by-layer test suite cannot see a missing call.** Every layer here had
tests and every layer passed. What was needed was one question asked of the
whole: *who calls this, with what arguments?* `grep` for the function name,
then read the arguments at each site — `recovery_check_profiled` would have
answered in one line, because `"LFSM"` is right there in the only call.

That question is now partly mechanised: `WIRING.md` §3/§4 enumerate view and
subscriber call sites, and `audit_configurable.py --strict` fails the build on a
profile key the code reads that nothing writes. Neither would have caught THIS
one — a function with a caller, called with the wrong literal. The check that
would is "every branch of a `qc_type` dispatch is reached by some call site",
which nothing currently does. Logged as the next auditor to build.

### 30.5 Two defects introduced by the fix, and found by review not by tests

The sixteen tests written alongside §30 all passed on an implementation with two
behaviour-changing defects in it. Both are the "criterion applied where it does
not belong" shape, which is the mirror of §30's "criterion never applied".

**Every diluted injection would have failed.** The loop iterated `all_rows` and
its guard fell through to the Sample default for a dilution, because
`classify_injection` returns `"Dilution"` and that is not a `REVIEW_CHECKS` key.
A 1:10 dilution's surrogate reads about a tenth of nominal, so every diluted
injection in every batch would have AUTO_FAILed — against a criterion this same
module already excludes dilutions from, in a comment 200 lines above that names
**recovery** explicitly. `is_raw_check` is the deliberate exception and corrects
for the recorded factor internally; a recovery does not. Now uses `rows`, and the
guard excludes `"Dilution"` explicitly rather than by fallthrough. Renamed
`_takes_surrogate_recovery` — the question is not "was this extracted" (a
dilution was) but "does the criterion apply".

**Every FDA batch would have been gated on guidance.** FDA §2024.10.1(5) makes
surrogate recovery advisory, and `FDA32PFASProfile.qc_rules(..., "SUR")` says so
via `is_guidance_only=True`. But `recovery_check_profiled` returns a flag anyway,
tagged "[guidance only]" in its text — so attaching `KIND_SURROGATE` to it made
an advisory exceedance an AUTO_FAIL on a release gate. Guidance-only exceedances
are now recorded with **no** `check_kind`: they appear in the QC log and on the
injection, and cannot fail a check. The check is left PENDING rather than passed,
because a human should read an advisory exceedance and AUTO_PASS beside a visible
flag would say the opposite. An in-range result still AUTO_PASSes, so "advisory"
does not become "permanently pending".

**Why no test caught either.** Every one of the sixteen asserted something about
the compound, the window, or the status of an injection the test itself
constructed. None asked "what does this now do to an injection type I did not
think about" — and the two that mattered, a dilution and a guidance-only method,
are both *absences* from the test set rather than wrong assertions in it. A test
suite can only be wrong about what it mentions.

The transferable form: when a check starts applying where it did not before,
enumerate the injection types and methods it will now touch, and ask of each
whether the criterion belongs. That list is short and finite —
`REVIEW_CHECKS.keys()` and the three methods — which is exactly why not consulting
it was careless rather than unlucky.

### 30.6 Still open on this subsystem

* **`surrogate_is_chain` is empty for both EPA methods.** FDA carries 20 entries.
  With it empty, `is_raw_check` cannot take its method-scoped branch and falls
  back to the global reference table, which names FDA's `13C4-PFOA` as the
  injection standard. That was inert while the loop iterated nothing; it is
  reachable now. EPA 1633A uses non-extracted internal standards (NIS) that are
  its own, so this needs the method's chain configured rather than a code change.
* **Column 30 in real exports is unverified.** `pct_recovery_is` drives the new
  check and `data/instrument_output/` is empty, so whether the lab's instrument
  actually reports "% Recovery (Internal Standard)" is untested against a real
  file. If it does not, `surrogate_recovery` shows PENDING on every injection —
  visible, not silent, and the correct failure direction, but it should be
  confirmed on the next real run before anyone reads it as meaningful.
* **The ten divergent EIS designations** (§30.2) remain a QA-manager question.

---

## 31. FDA §10.2(4) confirmation — wired (2026-09-25)

§13 ranked this "the most consequential remaining code gap", and it was the same
shape as §30: `single_transition_confirm_needed()` computed the rule correctly
and had **no caller** from the day it was written. Its docstring claimed "used by
the run queue". Nothing did.

PFBA and PFPeA have one usable MS/MS transition, so their identity cannot be
established by ion ratio the way every other analyte's is. FDA §10.2(4) therefore
requires a positive to be confirmed by an orthogonal technique (LC-HRMS, agreeing
within `confirm_pct_diff_max`, 20%). Until now nothing prompted for it.

### Where it had to go, and why not the run queue

It lives in `pipeline.build_summary`, which is the only place that knows whether
an analyte was **detected**. The run queue was the obvious home and is the wrong
one: `auto_evaluate()` runs at `pipeline.py:715` and `build_summary` at 720, and
they cannot be swapped because the summary consumes `batch.is_results`, which
auto_evaluate produces. Deciding detection again inside the queue would be two
answers to one question — the §1 rule-3 violation this register keeps finding.

So the obligation is settled in two passes:

1. `build_summary` appends `QUALIFIER_CONF` to the result's existing `flags`
   list — the same mechanism that already carries `N.C.` and `SUR` onto the
   certificate, so no new plumbing — and records the prompt on
   `batch.confirmations_required`.
2. `RunQueue.resolve_confirmations()`, called after `build_summary`, settles the
   new `identity_confirmation` review check: **PENDING** where a confirmation is
   genuinely owed, with the prompt attached; **AUTO_PASS** where §10.2(4) does
   not apply.

That second pass exists because of §30.5. `identity_confirmation` is deliberately
absent from `auto_evaluate`'s `_CHECK_KINDS`, which leaves it PENDING — and
without the resolve pass it would sit PENDING on every injection of every batch
forever, which is a check nobody reads.

**AUTO_PASS here means "§10.2(4) does not apply to this injection", NOT "the
confirmation was done."** An owed confirmation is closed by a human accepting the
check with the LC-HRMS result, which `accept()` already exists for.

### Two things reach alone would have got wrong

**It must be silent on the EPA methods.** `single_transition_analytes` is
populated only by FDA's `confirmation_rule()`; both EPA methods inherit the
dataclass default `()`. So the check is method-conditional **by data**, not by an
`if method_id ==` — which is what CLAUDE.md §3 rule 3 requires. A test pins that
EPA 1633A raises nothing, so if it ever does, the cause is a profile edit.

**"Detected" is not "quantified".** BLoQ is a detection *below* the quantitation
limit — build_summary's own comment says so — and ALoQ is one above the range.
§10.2(4) is about establishing identity, not about the number, so both count. A
test pins BLoQ.

### The policy this follows

An owed confirmation does **not** hard-block release. It raises a prompt the
reviewer must dispose of, and if the result is released without confirmation it
carries the `HRMS` qualifier. That follows the lab's stated rule verbatim — "You
can always output data that does not conform. It just needs to be appropriately
qualified" — rather than inventing a refusal branch. FDA gets its prompt; the lab
keeps its release policy.

### Still open

* **Recording the confirmation itself.** `confirm_pct_diff_max` (20%) is
  resolved and nothing computes a %diff, because there is nowhere to enter the
  LC-HRMS result. Today the reviewer closes the check by accepting it with a
  comment. Entering the second value and having the system judge the 20% is the
  next increment.
* **`calculate_mdl` is now the only remaining NOT WIRED function** in the
  pipeline. It needs a periodic-study feature (≥7 replicates over time), which is
  a data-entry surface, not a missing call.

### 31.2 Corrected: the prompt insisted on one instrument, and could not be switched off

Robin's correction, 2026-09-25: *"The HRMS check should be an optional toggle
setting. There are other ways to confirm PFBA that do not require HRMS."*

Both halves were CLAUDE.md §1 rule 1 — configurable, not hardcoded — and §31 as
first written violated it twice.

**The technique was hardcoded.** FDA §10.2(4) cites LC-HRMS as an example; a
second column, a different ionisation mode or an alternative transition can also
establish identity. The prompt named LC-HRMS unconditionally, telling a lab to
run an instrument it may not own. `confirmation.confirm_technique` is now a
configurable field with a form input in the Method Profile confirmation pane, and
the prompt quotes whatever the lab names, falling back to the method's cited
example only when left blank. The qualifier code changed `HRMS` → **`CONF`**: a
code on a certificate should say confirmation is outstanding, not assert which
instrument is required. The review check is `identity_confirmation`, not
`hrms_confirmation`, for the same reason.

**The prompt could not be switched off.** Now gated on
`single_transition_confirm` in `RULE_LIBRARY`, with an entry in
`LIBRARY_KEY_TO_ENGINE_CHECKS` and in all three methods' defaults. The obligation
is method text and is not in question; what is optional is whether this system
prompts, since a lab confirming PFBA another way may be recording it elsewhere.

### 31.3 The toggle guard had the same blind spot it exists to catch

`tests/test_rule_toggles.py` harvests every key passed to `_rule_enabled` and
fails if one is absent from `RULE_LIBRARY` — the guard written after §8, where
`lfsm_recovery` was read by the engine and present in no library, no defaults and
no UI, so the switch the lab was given did nothing.

It scanned **`run_queue.py` alone**. This confirmation prompt is gated in
`pipeline.py`, because `build_summary` is the only place that knows whether an
analyte was detected — so the gate would have been invisible to the very test
that exists to catch an unreachable toggle. Now scans a `GATING_MODULES` list.

The blind spot was in the checker, not the checked, which is the third instance
of that shape in this register: §1 could not see the IS defect (§19.2), the
configurability audit could not see a key nothing writes (§30.1), and this.
**A guard that scans one file asserts something only about that file.**

Two new tests: one pinning all three halves of "reachable" (in the library, in
every method's defaults, and actually read by a gating module), and one
behavioural — with the rule OFF, a PFBA positive gets no qualifier and nothing is
recorded as owed. Structural agreement between tables is what §8 already had;
proving the switch *does something* is what it lacked.

### 31.1 The reported value never matched its own documented format

Printing `SummaryResult.display()` on a result carrying the new flag — rather
than asserting anything about the list — found a defect older than this work.
`build_summary`'s docstring records three strings taken from REAL output:
`8.39 (BLoQ)`, `0.0537 (BLoQ; N.C.)`, `10.6 (BLoQ; SUR)`. `display()` reproduced
the first and **neither of the others**. It emitted a separate parenthesis per
group, and joined multiple flags with the empty string:

| | was | now |
|---|---|---|
| one code | `8.39 (BLoQ)` | `8.39 (BLoQ)` |
| qualifier + flag | `0.0537 (BLoQ) (N.C.)` | `0.0537 (BLoQ; N.C.)` |
| two flags | `12 (N.C.HRMS)` | `12 (N.C.; HRMS)` |

`N.C.HRMS` is not two qualifier codes. It is a third string that is not a code at
all, on a document a client reads and an assessor audits.

Reachable all along via `N.C.` + `SUR`; §31 only made a second code common. It
survived because the sole consumer is `report.py:94` and nothing had ever asserted
on the rendered string — the §29 shape exactly, for the third time: **an assertion
about structure standing in for reading the output.** The test now pins all three
documented strings, which are an independent reference rather than this project's
own idea of the format.

---

## 32. A machine's finding is evidence; a person's sign-off is authorisation (2026-09-25)

Asked whether the §10.2(4) review could be performed by an agent. Investigating
it turned up something worth more than the answer.

### 32.1 The review queue an agent would act on is write-only

`RunQueue` looked like the release gate. It is not:

* `is_complete` — **no callers**
* `RunQueue.load` — **no callers**
* `{batch_id}_queue.json` — written at `pipeline.py:846`, read by nothing
* review checks reach neither SQLite nor the add-on; `check_name` does not appear
  anywhere in `src/`

So an agent disposing of `identity_confirmation` in the pipeline queue would
change nothing that gates a release. Adding an `AUTO_ACCEPTED` status there — the
first plan — would have been a mechanism with no consumer: the §12/§30 defect,
built deliberately.

**The actual gate** is the 5-item checklist in ZODB on the Worksheet
(`senaite.pfas.data_review.checklist`), whose `all_items_pass()` drives submission
and whose `submitted_by`/`approved_by` feed the CoA attestation. That is where the
distinction had to go, and it is a different subsystem from the one the question
was about.

### 32.2 What was actually wrong

`checked_by` was a **free string**, and `all_items_pass()` read only `checked`. Any
account able to POST the handler could tick a manual item and open the gate,
leaving a record indistinguishable from a person's. There was no status, field or
flag separating the two — so "reviewed" and "computed" were one state.

That is the same shape as §30.5 and §31: a pass that quietly means nobody looked.
Here it would have meant nobody *authorised*, which under ISO 17025 is the one
thing a person has to do.

### 32.3 What was built

**Identity from a group, not a name.** `AUTOMATION_GROUP = "PFAS Automation"`;
`_actor_kind()` reads Plone group membership. Not a name pattern (`svc_*`), not a
tuple of user ids — CLAUDE.md §6A requires authority to key off the permissions
SENAITE already enforces, so granting automation is an ordinary group membership
change that an auditor can see. A test asserts the absence of name-pattern
matching, because that is the cheap wrong implementation.

**It fails closed to `human`.** An unreadable group list must not reclassify a
person's sign-off as machine output, which would discard a valid attestation. The
risk runs the other way, and explicit membership is what addresses it.

**A service account may propose; it may not attest.** `_handle_check_item` now
branches on actor kind *before* setting `checked`, and the automated branch records
`proposed_by` / `proposed_at` / `proposed_notes` and returns. `proposed_notes` is
deliberately separate from `notes`, which a human owns: sharing one field would
erase the evidence that a machine looked first, which is the provenance the whole
distinction exists to keep.

**Enforced at the gate as well as at entry.** `all_items_pass()` now also requires
that no manual item carries an automated attestation, and
`machine_attested_items()` names which ones do. Entry-point enforcement alone is
not enough: an item can be written by a migration or a scripted POST that never
reaches the handler — §7.1 is exactly that shape. Submission reports
"machine attested" distinctly from "incomplete", because telling a reviewer the
checklist is incomplete sends them hunting for an empty box that does not exist.

**An unlabelled attestation reads as human.** Every existing one predates
`checked_by_kind` and was written by a handler that has always required an
authenticated user and typed initials. Treating them as machine output would
retroactively invalidate real sign-offs; new automated ones are labelled, so the
ambiguity does not grow.

### 32.4 What this settles about agents

| step | who |
|---|---|
| detect that confirmation is owed | code — §31 |
| compute the %diff and judge the tolerance | code — still to build |
| gather evidence, draft a disposition | a service account, now recordable as such |
| authorise and release | a person, now enforced |

An agent is useful as a *drafter*. It cannot be the authoriser, and as of this
entry the system can tell the difference — which it could not before, and which had
to exist before automating any part of this, not after.

### 32.5 The group id was the silent-failure mode, so the installer creates it

First written as `AUTOMATION_GROUP = "PFAS Automation"` and left as an
instruction: *"you'll need to create that group."* Two things wrong with that.

`getGroups()` returns group **IDs**, not titles. An id that does not match raises
nothing — it classifies every service account as **human**, which is the one
direction that matters, because a machine attestation would then open the release
gate looking like a person's sign-off. And this site's ids are CamelCase with no
spaces (`Analysts`, `LabManagers`, `RegulatoryInspectors`), so a space also risked
the Plone UI transforming what a lab typed into something that no longer matched.

So the id is now `PFASAutomation`, and `setuphandlers.setup_automation_group()`
**creates** it rather than leaving a human to type it correctly. A silent-failure
mode with no symptom is not something to close with documentation.

It grants **no roles**, deliberately and asserted by a test: it classifies an
account, it does not empower one. A service account still needs Analyst or
LabManager through the normal role model to reach the view at all (`can_act`), so
capability and classification stay separate — attaching permissions here later
would mean adding an account to it silently widens what it may do.

Verified live: created, idempotent on re-run, no roles, no members. And proven
end to end on a throwaway account — `human` before joining, `automated` after,
`human` again after removal, transaction aborted so nothing persisted.

### Still open

* Nothing yet WRITES a proposal: no automated actor exists, and the group has no
  members. That is deliberate — the
  audit distinction is the prerequisite, and building the producer first is how
  the LFSM toggle went wrong (§8). The next increment that needs it is recording
  an LC-HRMS value and computing the 20% agreement.
* The pipeline `RunQueue` remains write-only. Either wire it to something or
  retire it; a queue nothing reads is a standing invitation to build against it.

---

## 33. Traceability & throughput audit — reagent lot → in-house standard → result (2026-09-25)

Asked for an audit of throughput: can work flow through, and does a lot prepared
in-house link back to the manufacturer's material? Levels 1→2 exercised **through
the web forms** on the live instance, plus the 2→3 gate. Lots named `AUDIT-*`,
all removed afterwards — the final baseline is byte-identical to the as-found one
and `method_profiles.json` verified unchanged by sha256.

**Throughput itself works.** A manufacturer lot was created with full provenance,
a CoA uploaded and served back, an in-house standard prepared from it, the parent
link written and resolved, and a Certificate of Preparation issued correctly
labelled "not a manufacturer CoA". The chain *can* be built correctly.

The problem is that nothing requires it to be, and the bench path actively breaks
the model.

### As-found data state

| | |
|---|---|
| reagent lots / prepared standards | 14 / 11 |
| **reagent lots with a CoA on file** | **0 of 14** |
| prepared standards with no parentage | 1 (`PS-FDA-2026-A`) |
| prepared standards expired | 11 of 11 (latest 2026-09-22) |
| tests exercising the traceability gate | **0** |

### HIGH — structural

**33.1 Preparing a solution in-house creates a MANUFACTURER reagent.**
`extraction_guide._handle_prepare_solution` (`:347`) calls `_save_reagent`, not the
prepared-standard path. Demonstrated live: the form produced a `Reagent` with
`supplier="In-house"`, empty `cat_number`, empty `manufacturer_expiry`, and
composition/preparer buried in a free-text `notes` string. It sits in inventory
beside genuine Wellington/Fisher CRMs with the same shape.

The link back is not merely absent, it is **impossible**: `IReagent` has no
parent/parentage/source field at all. So the three-level chain collapses to two the
moment a bench chemist prepares anything, and the resulting object *claims to be*
the manufacturer material. Contradicts DECISIONS.md D50 (`:2380`), which states this
path records "a new Prepared Standard lot (parents = the stage's reagents) …
completing the 3-level traceability chain the review gate checks."

**33.2 The item labelled "3-level chain auto-resolved" gates two levels.**
Proven by contrast, reproduced identically twice:

| logbook names | gate |
|---|---|
| a standard whose parent lot does not exist | **PASS** |
| a *reagent* lot that does not exist | fail (`unresolved=1`) |

Level 2 genuinely gates; level 1 does not. `_build_traceability_tree`
(`data_review.py:1212-1226`) is the only branch with no
`else: tree["unresolved"].append(...)`, and `_compute_traceability_status` (`:591`)
keys solely off `unresolved`. The tree even *computes and displays*
`unresolved_parents` — the information exists and is shown, and is not gated. A
standard with zero parents also passes, as does a corrupt annotation
(`except Exception: parents = []`, `:1210`).

**33.3 A fabricated parentage is certified as fact.** A standard naming parent lot
`AUDIT-DOES-NOT-EXIST` saved without error, and its Certificate of Preparation
printed `Nonexistent CRM | Nowhere Labs | AUDIT-DOES-NOT-EXIST | 50 uL` under
"Parent Reagents (Parentage)" with the 3-tier QA attestation attached and **no flag
anywhere** that the lot is not in inventory.

**33.4 A standard with no parentage is saved and certified.** Only `title` and
`lot_number` are validated (`prepared_standards.py:524`). The certificate is then
issued printing "No parent reagents recorded" — the document that exists to
establish parentage is issued precisely when there is none.

### MODERATE-HIGH

**33.5 A CoA can be "uploaded" against nothing, reporting success.** `_save_coa`
(`reagents.py:422`) writes the file to disk *before* resolving the reagent, then
`if obj is not None:` skips the annotation, then `return True` unconditionally.
Demonstrated: `uid=1000` (not a reagent) returned `?ok=CoA+uploaded` and left an
orphan `/data/coa/1000.pdf` attached to nothing. The operator is told the lot is
documented. It is not.

**33.6 A dangling parent silently disables expiry protection.**
`get_reagent_effective_expiry` returns `''` for an unknown lot (`reagents.py:158`),
and `effective_expiry_info` treats `''` as "no constraint" inside a bare
`except Exception: pass` (`prepared_standards.py:235`). Unresolvable and
unconstrained are indistinguishable, so §10's "an expired CRM invalidates prepared
standards made from it" cannot fire when the parent cannot be found at all.

### MODERATE

**33.7 The stored parent `uid` is dead — the root cause of 33.3 and 33.6.** The
annotation carries a `uid` per parent and nothing reads it; resolution is by
lot-number STRING (`data_review.py:1221`, `prepared_standards.py:233`). The repo
already holds the correct pattern: D54 stores salt-factor CoA links as
`{analyte, factor, lot_uid, lot_number}` and resolves by uid
(`method_profiles.py:1102`). `parent_reagents` was never brought up to it.

**33.8 The gate resolves against ARCHIVED lots.** Demonstrated: after archiving a
parent reagent while a standard still cited it, `_build_lot_indices` still returned
it (it walks `objectValues()` with no status/archive filter), `resolved=True`, gate
`True`. A lot the lab has deliberately withdrawn still satisfies traceability.
*(Correction made during the audit: I first read this as the link breaking, because
`_list_reagents()` does filter archived lots. That is not the resolver the gate uses.)*

**33.9 Three resolvers, three answers, for one parent.** At the same moment for the
same archived parent: `_list_reagents()` → absent; `get_reagent_effective_expiry()`
→ `'2028-03-31'`; `_build_lot_indices()` → present. "Is this parent real" depends on
which you ask.

**33.10 A row with no lot satisfies "has data".** `direct_reagents.append(entry)`
sits outside the `if lot:` branch (`data_review.py:1148`), so one 252 row with a
name and an empty lot makes `has_data` True and adds nothing to `unresolved` —
traceability passes with zero lots resolved. Confirmed live.

**33.11 The lot picker offers undocumented standards.** `usable_lots()` offered the
parentless and the ghost-parented standard alongside the properly documented one,
with nothing distinguishing them.

**33.12 `extraction_materials[]` lots are traced nowhere.** The gate reads only
`reagents[]` and `standards[]` (`:1132, :1151`). Cartridge/sorbent lots are neither
resolved nor reported unresolved.

**33.13 No expiry means never expires.** `_is_expired()` (`reagents.py:161`):
`if not exp: return False`. A lot created with no dates at all reports not-expired.
Fails open, against this project's own precedent — `tests/test_holding_time.py` pins
that an unset limit must REFUSE rather than pass.

### LOW-MODERATE, and data/design items

- **33.14** A manufacturer lot needs no manufacturer identity: POST with only
  `name` + `lot_number` saved cleanly, leaving supplier, catalogue number and all
  dates empty. It is then eligible as a prepared-standard parent.
- **33.15** No NIST/CRM traceability field exists anywhere in `content/` or the
  reagent UI. CLAUDE.md §10 "Reference standard provenance (NIST-traceable)" is
  **unrecordable**, not merely unenforced.
- **33.16** `extraction_guide.py:358` calls `_auto_expiry_from_open` without the
  `defaults` argument, so the one path that creates lots automatically bypasses the
  lab-configurable expiry defaults (golden rule 1).
- **DATA:** 0 of 14 lots have a CoA — including the two Wellington CRMs every
  calibration standard descends from. The mechanism works; it has never been used.
- **DESIGN QUESTION for the QA manager:** should parent links be UID references
  (33.7)? That is a data-migration decision, not a bug fix.

### What this audit did not cover

Level 3 was verified only as a mechanism in this pass; §34 carries it out against
real worksheets. The 2→3 seeding used worksheet annotations directly; note the
dual read (`data_review.py:1091`) takes the worksheet before the linked batch.

**CORRECTION, see §34.3.** This paragraph first read "The instance holds no samples
or AnalysisRequests". That was wrong. There are **39 AnalysisRequests** across three
clients, and **WS-0005 is `verified` with 288 analyses** — the real August
end-to-end run. The cause was a ZCatalog queried in a way that returns an empty
result set, which is not the same thing as an empty catalog; the same mistake had
already been caught once earlier in this session. The reagent and prepared-standard
counts in the table above were each taken by two structurally different routes,
agreed, and stand.

### The transferable point

This subsystem had **one incidental mention** in 32 sections of this register before
today, and no test at all. Every finding above was reachable by driving the forms
for an afternoon. The gate that was supposed to catch them reports green — and
33.2's contrast shows it is not a broken gate, it is a gate with one link missing,
which is far harder to notice than a gate that never worked.

---

## 34. The fixes, verified at level 3 against real released data (2026-09-25)

§33's fixes change what the release gate allows, so the question that matters is
not "do the probes pass" but "does a worksheet that was legitimately released still
pass". Run against every worksheet on the instance.

### The gate now enforces level 1 and does not regress a released worksheet

| worksheet | state | analyses | gate | unresolved |
|---|---|---|---|---|
| **WS-0005** | **verified** | 288 | **PASS** | 0 |
| WS-0001 | open | 0 | **fail** | 1 — `PS-FDA-2026-A`, "no parent reagents recorded" |
| WS-001 | open | 0 | PASS | 0 |
| WS-0002/3/6/7/8 | open / to_be_verified | 0 | fail | 0 rows of any kind |
| WS-0004 | **verified** | 0 | fail | 0 rows of any kind |

Two things this establishes:

**No regression.** WS-0005 is the real August end-to-end run — 288 analyses,
`verified`, published. All twelve of its parent links resolve, and it still passes
the tightened gate. So level-1 enforcement is not a blanket block; it discriminates.

**The fix catches the real defect on real data.** WS-0001 fails on
`PS-FDA-2026-A` — the parentless standard found in §33's as-found pass, not a
fixture. Under the old gate that worksheet reported green. It is `open`, so nothing
released is retrospectively blocked.

### 34.1 A verified worksheet has no traceability evidence at all

WS-0004 is `verified` with zero reagent, standard and prepared-standard rows — so
`has_data` is False and it would not pass the gate today. Either it was released
before the gate existed in its current form, or it is seed data that was pushed to
`verified` directly. Both are worth knowing and I have not established which;
recorded rather than guessed at.

### 34.2 Every released result traces to a CRM with no CoA on file

`has_coa` is **False for all twelve** of WS-0005's resolved parents, including
`WL-PFACMXK-A2439` and `WL-MPFACCES-B1177` — the Wellington CRMs its published
results descend from. §33 reported 0 of 14 lots carrying a CoA as a data gap; this
is what that means in practice. The chain resolves, the lots exist, and the
document establishing what is in them is absent at every node.

Nothing in the code can fix this. It is lot documentation the lab has to upload,
and the upload path now works and refuses to lie about it (§33.5).

### 34.3 A second catalog mistake, same cause

§33 stated "0 samples / 0 AnalysisRequests". Wrong: there are 39, across three
clients. The cause is the same one already caught earlier in this session — a
ZCatalog queried in a way that returns an empty result set is not an empty catalog.
Having been caught once, it was repeated, which is the useful part: the lesson had
been recorded but not converted into a habit.

**The habit:** for a count that a finding rests on, cross-check by a second,
structurally different route before writing it down. The as-found reagent and
prepared-standard figures in §33 were taken by folder walk *and* by the production
readers, agreed, and were right. The sample figure was taken one way and was wrong.

### Still open from §33

- **§33.1 — the bench path.** `_handle_prepare_solution` still files an in-house
  solution as a manufacturer `Reagent` with no parentage, and `IReagent` still has
  no field that could hold one. The correct fix is a `PreparedStandard` with the
  stage's reagents as parents, which is what DECISIONS.md D50 already claims
  happens. It is a bench-workflow change, so it is not being slipped in alongside
  gate fixes.
- **§33.3** the Certificate of Preparation still prints an unresolvable parent as
  fact, with no flag. The gate now refuses such a standard, so the document and the
  gate disagree — which is better than both being wrong, and still wrong.
- **§33.11** `usable_lots` still offers standards the gate will now reject. An
  analyst can pick a lot that blocks release, with no warning at the point of
  choice.
- **as-of-date expiry** (DECISIONS.md 2026-08-03 item 7): `_is_expired` now takes
  `as_of`, and nothing passes it yet. Judging against today would condemn
  historical batches whose standards were in date when used, so the USE date has to
  be threaded through the gate first.

---

## 35. The bench path now builds the chain instead of faking it (2026-09-26)

§33.1 fixed. `extraction_guide._handle_prepare_solution` creates a
**PreparedStandard** whose parents are the stage's reagent lots, not a
manufacturer `Reagent` with supplier `"In-house"` and no parentage.

DECISIONS.md D50 has claimed this since 2026-07-02 — "records a new Prepared
Standard lot (parents = the stage's reagents; expiry inherits) … completing the
3-level traceability chain the review gate checks". It is now true.

### The parents are UID-linked, which is stronger than D50 asked for

The stage's reagent rows already carry `inventory_uid`, a real Reagent UID, so the
template posts that alongside the lot string and §33.7's uid-first resolution reads
it. Supplier is deliberately **not** copied into the parent record — the resolved
Reagent owns it, and duplicating it is what let the old records drift.

Proven live, and this is the part that matters:

    bench standard, parent intact                gate=True   parent resolved
    after the parent's LOT NUMBER is corrected   gate=True   parent resolved

Under the old code a lot-number correction silently dangled the level-1 link, and
the old gate silently passed it anyway. Now it survives the correction.

### It refuses rather than producing an untraceable lot

With no reagent lots recorded, the handler redirects with
*"Record the reagent lots this solution was made from before saving it"*, and the
template blocks it client-side first with the reason. A parentless prepared
standard is §33.4, the gate now rejects one, and telling the analyst at the bench
beats telling them at release.

### Verified

    in pfas_reagents           : []                     <- old behaviour gone
    in pfas_prepared_standards : ['AUDIT2-BENCH-001']    <- level 2, correct
    standard_type              : 'Solvent / Reagent'
    parent lot FISHER-MEOH-260510, uid 933266ac...
      resolves by UID -> 'Methanol LC-MS Grade'
      supplier on the resolved object -> 'Fisher Scientific'

So an in-house preparation now reaches a named manufacturer. Test lot removed; the
baseline is byte-identical to as-found.

### 35.1 A restart was required, and that is worth recording

The first run of this test appeared to fail — the refusal did not fire and the old
handler ran. Cause: `/addon` is a live mount, but the module was already imported
in the long-running Zope process. `bin/instance run` starts a fresh process and
therefore saw the new code, which is why every gate probe reflected the fixes
immediately; **curl hits the running server, which did not.**

That also means the §33 form-driven findings were genuine — they exercised the code
as loaded at container start, which was the unfixed code. But any future audit that
drives forms after editing add-on Python must restart the instance first, or it
tests the old code and says so convincingly. Two stray Reagents created by the
stale handler during that confusion were removed.

### Still open

- **§33.3** the Certificate of Preparation still prints an unresolvable parent as
  fact. The gate now refuses such a standard, so document and gate disagree.
- **§33.11** `usable_lots` still offers standards the gate will reject, so a lot can
  be chosen that blocks release with no warning at the point of choice.
- **as-of-date expiry**: `_is_expired` takes `as_of` and nothing passes it; the USE
  date has to be threaded through the gate before it can be used, or historical
  batches would be condemned for standards that were in date when used.
- **`IReagent` still has no parentage field.** Not needed now that in-house
  preparations are PreparedStandards, but it is what made the old behaviour
  unfixable in place, and any future "in-house reagent" would hit it again.

---

## 36. The Certificate of Preparation carries the hierarchy to its source (2026-09-26)

Requirement, verbatim: *"The certificate of preparation should include details and
links to the stocks used to prepare it. It should produce a hierarchy map. Certain
lots will come from other lots which should always link back to the manufacturer
with the exception of reagent grade water, this should link to the type 1 water
source log. There must always be an entry if the in house water system was used
day of."*

### One walk, three endings, no fourth

`prepared_standards.build_parentage(portal, rec, used_on=...)` recurses from a
prepared standard up through however many lots it descends from. Every branch
terminates in exactly one of three ways, and that is enforced by construction
rather than by a check somebody remembered to write — which is how level 1 went
unenforced for so long (§33.2):

| ending | provenance |
|---|---|
| `manufacturer` | a Reagent with a supplier, catalogue number and CoA status |
| `water` | in-house Type 1 water — the water QC log **for the day of use** |
| `unresolved` | not in inventory, no supplier, archived, or water with no log |

A parent may now be **another prepared standard**, which is what "certain lots
come from other lots" requires. Resolution is UID-first (§33.7), so a lot-number
correction anywhere in the chain does not break it.

Cycle-safe and depth-bounded (`MAX_PARENTAGE_DEPTH = 12`): a mis-keyed parent
pointing into its own chain is reported as `circular parentage` rather than
recursing until the request dies. A data-entry error must not be able to take a
page down.

### What the certificate now prints

Resolved and rendered as an indented hierarchy with links, not the stored parent
record reprinted. Real output from a three-level chain:

    PREPARED IN HOUSE  CERT-PRIMARY   made from the lot(s) below
      MANUFACTURER     CERT-CRM       Wellington Laboratories · cat. PFAC-MXK
                                      · no CoA on file
    TYPE 1 WATER       CERT-H2O       in-house system · QC 2026-09-26 10:36
                                      · conductivity 0.055 µS/cm · TOC 3.0 ppb · PASS
    UNRESOLVED         CERT-DOES-NOT-EXIST   not traceable
                                      ⚠ lot CERT-DOES-NOT-EXIST is not in inventory
    ⚠ THIS PARENTAGE IS NOT FULLY SUBSTANTIATED — 1 unresolved link(s).

That closes §33.3: the document previously printed a fabricated parent as
established fact with the 3-tier QA attestation attached and no flag anywhere.

### The water rule

In-house water is identified by a new reagent category,
`CATEGORY_INHOUSE_WATER = u"Reagent Water — in-house Type 1"` — **not** by matching
the word "water", because purchased LC-MS water (Fisher `FISHER-H2O-260510`) is an
ordinary manufactured lot that must keep tracing to its supplier. The distinction
is which category the bench selected, not what the lot is called.

`facility_qc.get_water_qc_for_date(log_date)` is the single definition of "was the
system verified that day". The facility dashboard's inline copy of that query now
calls it too — and the shared version orders by `log_time` **and `id`**, fixing the
same-minute tie that §10.1 found for the eye wash, where a stale PASS could beat a
later FAIL.

The check is keyed on the date of **use**, threaded down the recursion: a working
standard made today from a stock made last month asks about today for its own water
and about last month for the stock's. Judging everything against today would be the
§33.13 mistake in another form.

**A missing entry fails the gate.** Confirmed as the intended reading. Verified
live: with no entry the walk reports *"in-house Type 1 water was used on 2026-09-26
and there is no water QC entry for that date"*; recording one clears it; a recorded
entry whose `passed` is 0 is reported as a FAIL rather than accepted.

### The document and the gate cannot disagree again

`data_review` calls the same `build_parentage` and turns `parentage_problems()`
straight into `tree["unresolved"]`. Before, the certificate and the gate had
different ideas of the same chain, and §33.9 found three resolvers giving three
answers about whether one parent existed. A branch the certificate prints as broken
is now exactly the one that blocks release.

### Operational consequence, stated plainly

`facility_units` and `water_qc_logs` hold **zero rows** (§10.3). So the moment a lab
marks a lot as in-house Type 1 water, every preparation using it fails the gate
until daily water QC logging starts. That is the requirement working as asked, not
a defect — but it is a real prerequisite, and no existing lot carries the new
category, so nothing is blocked today.

Verified: 10/10 gate probes still correct, 15 structural tests, instance baseline
byte-identical to as-found. A water QC row created during the probe was removed —
test data in a compliance log is worse than none.

### Still open

- **§33.11** `usable_lots` still offers standards the gate will reject.
- **as-of-date expiry**: `_is_expired` takes `as_of`; nothing passes it yet.
- **0 of 14 lots have a CoA**, so every `manufacturer` node prints "no CoA on file".
  The hierarchy now makes that visible on every certificate, which is the point.

---

## 37. Specimen CoAs, certificate review against ISO 17025 / GMP, ISO dates (2026-09-27)

### 37.1 Fourteen specimen CoAs attached, and why they are marked

`scripts/seed_example_coas.py` attaches a Certificate of Analysis to all 14 reagent
lots through the production `_save_coa` path. Verified: 14/14, retrievable over HTTP
(200, correct content type), and `has_coa` now True on every manufacturer node.

Each carries the fields a supplier's certificate carries and that §6.6 needs from
it: product, catalogue number, lot, certificate number, a **test-results table**
(test / specification / result / verdict) chosen per material category, storage,
expiry, an assigned-value traceability section, measurement uncertainty, and an
identified authorising signatory with an issue date. All dates ISO 8601.

Every page is marked SPECIMEN — title, banner, watermark, footer, `SPECIMEN-*`
certificate number, and an explicit "establishes no traceability" statement. That
is not decoration: a fabricated manufacturer CoA is exactly the record that does
damage if it is later taken as genuine, because it would assert traceability to a
reference value nobody measured. CLAUDE.md §8 says flag placeholders, never
fabricate a regulatory value.

### 37.2 The review caught the marking being laundered

With the specimens attached, the §6.5 statement on every Certificate of Preparation
immediately read *"each of which has a supplier certificate of analysis on file"* —
a traceability claim resting on illustrative documents. Presence had been treated as
sufficiency.

Fixed: `build_parentage` reads the CoA **metadata**, not merely its presence, and
carries `coa_specimen`. The hierarchy row now prints *"SPECIMEN CoA only — establishes
nothing"*, and the §6.5 statement counts a specimen as **no** certificate:

> NOT ESTABLISHED. …3 of 3 source lot(s) have no USABLE certificate of analysis on
> file (…). 3 of them carry only a SPECIMEN certificate, which is illustrative and
> establishes nothing.

Worth recording as its own defect shape: **adding review data almost created the
false assurance the review existed to find.** The certificate was right to be
suspicious of its own inputs.

### 37.3 Certificate of Preparation vs ISO 17025 and GMP — gaps closed

Reviewed against the specimen CoA as comparator and against §7.8.2.1 / §6.5.

| was missing | now |
|---|---|
| unique certificate identification (§7.8.2.1(b)) | `COP-<lot>-r<version>`, in header and footer |
| date of issue | stated, ISO 8601 |
| name and address of the laboratory (§7.8.2.1(a)) | read from `bika_setup.laboratory` |
| metrological traceability (§6.5) | derived from the parentage walk, not asserted |
| preparation record (GMP reproducibility) | component / lot / amount-taken table + final volume |
| scope of validity | "relates only to the lot identified above" |
| date convention | declared ISO 8601 on the document |

**The lab identity is unconfigured**, and the certificate says so rather than
printing SENAITE's stock "Laboratory Information" as though it were the lab's name.
That is a §7.8.2.1(a) requirement the lab has to satisfy by filling it in.

### 37.4 The certificate asserted a review that had not happened

The sign-off block read *"Reviewed and verified by <QAO name>"* — past tense, name
pre-filled from print settings, date line blank. The certificate is generated
automatically when the lot is recorded, so nobody had reviewed anything.

That is §32's defect in another document: a record that reads as approved because a
name appears on it. Now headed **UNSIGNED UNTIL DATED**, with rows *"Reserved for
<name>"* and the explicit statement that the certificate "does not itself constitute
verification or authorisation".

### 37.5 Two data gaps the rendered certificate exposed

Neither is a code defect; both show on the document now, which is the point.

- **No analyte concentrations** on `PS-KCP-CAL-251006` — a calibration standard
  certificate with no concentrations is not fit for purpose.
- **No component amounts**: every parentage row prints "(not recorded)", so the
  preparation is not reproducible from the record. GMP expects the amounts.
- **Equipment is recorded nowhere against a lot** — no balance, pipette or
  calibration status. The certificate states this and points at the prep logbook
  rather than implying it was captured.

### 37.6 ISO 8601 dates, with one deliberate exception

Display dates are now ISO 8601 everywhere. Two were not:
`coa_attestation._fmt` used `%d %b %Y %H:%M` on the **client-facing** attestation
block, and `deviations` used `%B %d, %Y` on a controlled record. Month names and D/M
ordering are locale-dependent: the same string can mean a different day.

**The exception, pinned by a test:** `egad_builder` emits `%m/%d/%Y` because Maine
DEP's EGAD EDD specifies it. Making that ISO would break the state submission, so
`test_the_egad_export_keeps_its_required_non_iso_format` exists specifically to stop
a future blanket sweep from "fixing" it. Date CODES (`%y%m%d` in injection names and
tracking IDs, `%Y%m%d%H%M%S` in `concat_id`) are identifiers, not displayed dates,
and are untouched — the Run Builder joins on them.

The ISO-date test scans the **argument of each `strftime` call via the AST**. Its
first version scanned raw text and flagged the comment explaining the fix — the
identical mistake `tests/test_rule_toggles.py` records having made, repeated here.

---

## 38. Equipment provenance: balance and pipette to the metrology lab (2026-09-27)

Requirement: equipment records link to the standards used for their calibration;
balance logs link to the equipment, which links to the extraction/sample processing
performed **that day**; pipette calibration is recorded (quarterly or external);
and the weight sets used for balance verification are checked by a metrology lab.

This is the equipment analogue of §36's reagent chain, and it terminates the same
way — at someone else's accredited measurement:

```
extraction stage (day X)
  → equipment serial → registered Facility QC unit
      balance  → verification for DAY X → weight set → metrology lab certificate
      pipette  → calibration in force at day X
                   internal: balance + weight set → metrology lab certificate
                   external: provider + certificate number
```

### What was added

* **`weight_sets`** — the lab's reference weights with their EXTERNAL calibration:
  issuing metrology laboratory, its accreditation, certificate number, calibration
  and due dates, NIST traceability, weight class, serial.
* **`pipette_calibrations`** — `kind` of `internal` (quarterly gravimetric, carrying
  the balance and weight set used) or `external` (provider, accreditation,
  certificate). Both with `cal_date` and `due_date`.
* **`balance_verifications.weight_set_id`** — added via an idempotent `ALTER`
  (`_ADDED_COLUMNS`), because `CREATE TABLE IF NOT EXISTS` cannot add a column and
  an instance already collecting verifications must not lose them.
* **`pipette` unit type**, `unit_by_serial()`, `get_balance_verification_for_date()`,
  `get_pipette_calibration_in_force()`, and `equipment_provenance(unit_id, as_of)`.

Judged **as of the date of use**, not today, with `cal_date<=?` so a later
calibration cannot excuse an earlier run — the same rule the water log (§36) and
reagent expiry (§33.13) follow.

### The extraction join that never existed

`equipment_sns` — `{equipment_name: serial}` captured per extraction stage — was
read by `extraction_pdf` alone: printed, never resolved, never checked. The gate now
resolves each serial to a registered unit and asks about its calibration for the
stage's own completion date, using the **dual read** (worksheet then linked batch)
that `_logbook_json` uses. The first version read the batch alone, found nothing on
WS-0002, and reported `equipment=0` — the §33 mistake exactly.

### 38.1 The first version demanded a weight set from a vortex mixer

Running it against the real released WS-0005 failed it with **13 unresolved**, a
retroactive block on published work. Diagnosis: 9 of the 13 were a **cryogenic mill,
vortex mixer, centrifuge and mechanical shaker**. They measure nothing and have no
calibration standard to trace to, so the check could never be satisfied — worse than
no check.

The obligation belongs to the **unit type**, which is data:
`CALIBRATED_UNIT_TYPES = (balance_analytical, balance_prep, pipette)`. Everything
else is recorded as used and nothing more.

### 38.2 Enforce where the obligation is established; report where it is unknown

The remaining question was an unregistered serial. Blocking on it is wrong — we
cannot tell whether that equipment owed a calibration at all — so:

| situation | effect |
|---|---|
| unregistered serial | **warning**: "calibration status is unknown" |
| non-measuring registered unit | recorded as used, no obligation |
| registered balance, no verification for the day used | **BLOCKS** |
| registered pipette, no calibration covering the day | **BLOCKS** |
| weight set with no external certificate, or expired before use | **BLOCKS** |
| weight set not NIST-traceable | **BLOCKS** |

That line is not a compromise: it enforces every obligation the system KNOWS about,
and the gap for the rest is **registration**, which the lab closes by registering the
unit — at which point enforcement begins automatically. `facility_units` holds zero
rows (§10.3), so nothing is blocked today.

Verified live, all four cases, with WS-0005 back to `gate=True unresolved=0` and
WS-0001 still failing on its reagent parentage. Every probe cleaned up after itself:
0 units, 0 weight sets, 0 verifications left.

### Still open

- No UI yet for weight sets or pipette calibration — the schema and API exist and
  the Facility QC pages do not expose them. Deliberate: §8's lesson is that the
  producer comes after the thing it feeds, not before, and the gate already reads
  them.
- `PreparedStandard` still records no equipment, so a prepared standard's
  certificate cannot name the balance used to weigh it (§37.5). The extraction path
  now can; the prep path needs a field.

---

## 39. The Facility QC pages for weight sets and pipette calibration (2026-09-27)

§38 built the schema, the API and the gate reading; this is the producer. Both pages
follow the existing Facility QC pattern (`@@pfas-macros/macros/page`, theme tokens,
no bespoke styling — CLAUDE.md §6) and are registered in the sidebar's FACILITY QC
group alongside Balance Verification.

### `@@pfas-weight-sets`

Records a reference weight set and, required, its **external metrology-laboratory
calibration**: issuing laboratory, that laboratory's accreditation, certificate
number, calibration and due dates, NIST traceability, class and serial.

The list column does not say "saved" — it says whether the set is **TRACEABLE**, and
when it is not it prints the reasons the gate would give:

    AUDIT-WS-001   TRACEABLE
    AUDIT-WS-BAD   NOT TRACEABLE
                     no external calibration certificate recorded
                     not recorded as NIST-traceable
                     no calibration due date recorded

That is deliberate. The QAO sees at the point of entry exactly what would block a
release, instead of discovering it at data review on someone else's worksheet.

### `@@pfas-pipette-calibration`

Per-pipette history plus a single banner answering the question a reviewer actually
asks — *is this in calibration?* — rather than leaving them to read dates off a list:

    In calibration today. internal check dated 2026-07-01, due 2026-10-01

The form branches on kind, and only shows the evidence that kind requires: an
**in-house** check asks for the balance and weight set used (its own provenance,
which runs on to the metrology lab); an **external** one asks for the provider, its
accreditation and the certificate number. A form that asked for a balance on an
external certificate would invite someone to invent one.

Where a prerequisite is missing the page says so in place: "No weight sets
registered — an in-house check cannot be traced without one."

### Verified through HTTP, not by reading the code

Both pages rendered 200, then driven with real POSTs: a fully-calibrated set saved
and shown TRACEABLE; an uncalibrated one saved and shown NOT TRACEABLE with all three
reasons; a pipette and balance registered through the existing Units page; an
in-house quarterly calibration recorded and read back in the banner. Then
`equipment_provenance` was asked about the data the FORMS had written:

    pipette on 2026-08-15 -> problems=0
       pipette_calibration kind=internal cal=2026-07-01 due=2026-10-01
       weight_set AUDIT-WS-001 cal_lab=Regional Metrology Laboratory cert=RML-2026-4471
    pipette on 2026-11-15 -> problems=1
       PROBLEM: Pipette P200 calibration was due 2026-10-01, before it was used on 2026-11-15

So the chain the gate reads is the chain the pages write, and the as-of-date rule
holds in both directions. A restart was required for the new ZCML — the §35.1 lesson,
applied rather than rediscovered.

Every AUDIT-* row removed afterwards: `facility_units`, `weight_sets`,
`pipette_calibrations`, `balance_verifications` and `water_qc_logs` all back to 0.
WS-0005 still passes, WS-0001 still fails on its reagent parentage.

### Still open

- The balance verification form does not yet offer the weight set used — the column
  and the API accept it, and `@@pfas-balance-log` still posts without it, so a
  verification recorded through the UI today traces to nothing. That is the next
  small step and it is the last link in this chain still unwired.
- `PreparedStandard` records no equipment, so a prep certificate cannot name the
  balance used to weigh it (§37.5).

---

## 40. The Reagent Inventory 500, and why three months of checks missed it (2026-09-28)

Reported: "Reagent inventory is now producing an error with the changes."

```
ExpressionError: $ must be doubled or followed by a simple path
  reagents.pt line 414
  "${view/portal_url}/@@pfas-reagents?action=coa&uid=${python:rg.get('uid','')}"
```

A `string:` expression may interpolate only a **simple path**. `${python:...}`
inside one is invalid and raises at render time.

### It was not caused by the change; it was REVEALED by it

`git log -L` puts that line at commit `ec506f1`, **2026-06-24** — three months old.
It renders only inside `tal:condition="coa"`, and until §37 attached specimen
certificates **no reagent had a CoA**, so the branch was never taken and the
expression was never evaluated. Attaching 14 of them made it reachable on the first
page load.

The same shape as §35.1's missing PEP 263 declaration, which a stale `.pyc` had
masked: **a latent defect in a branch that data had never reached.** Adding correct
data is what surfaced both. Worth stating because it is the opposite of the usual
worry — the risk was not that the specimens would be mistaken for real, which §37.2
handled, but that attaching them would exercise code nothing ever had.

### Why nothing caught it

- Not the Python suite: it is a template.
- Not `tools/wiring_map.py` or `audit_configurable.py`: neither reads TAL.
- Not compiling the template — it compiles fine. The expression is only parsed when
  the branch is **rendered**.
- Not a page-load smoke test: the page returned 200 for three months, because the
  data never entered the branch.

A page is only as tested as its data.

### The fix, and the guard

`rg_uid` is bound with `tal:define` and the `string:` interpolates that simple path.
Two cached layers had to be cleared to see it: the template was already compiled in
the long-running process, so the error kept reporting the OLD expression after the
file was corrected — §35.1's restart lesson applies to templates, not only to
Python.

`tests/test_template_expressions.py` scans every `.pt` statically for `${python:`,
`${string:`, `${structure` and `${nocall:` inside an interpolation. It is a **static**
check on purpose: it would have caught this in June, with no CoAs and no data,
which no runtime check could.

Verified live afterwards: reagents 200 with CoA links carrying real uids, a CoA
fetch 200 `text/html`, and prep-standards / extraction-guide / weight-sets /
facility-qc all 200.

### 40.1 The comment-scanning trap, for the third time

The first version of that guard failed on `reagents.pt:411` — **the HTML comment I
had just written explaining the defect**. `test_rule_toggles.py` records this
happening once ("matched `_rule_enabled(...)` inside a COMMENT describing the fix");
the ISO-date test in §37.6 was the second; this is the third. The guard now blanks
HTML comments before scanning, preserving line numbers.

Three occurrences is a pattern, not bad luck: **prose about a defect contains the
defect's text.** Any scanner for a code smell must exclude comments and docstrings,
or the fix trips it.

### 40.2 A check I wrote and deleted

I also attempted a "`metal:fill-slot` must not nest" check, after §39's pipette page
was first written with the `scripts` slot nested inside `content`. A regex
depth-count flagged **150 lines across 50 templates, every one valid** —
`<tal:styles metal:fill-slot="head-extra">` defeats it completely. Deleted, with a
comment in its place so the next person does not repeat it. A check that cannot
distinguish valid from invalid is worse than no check, and compiling the template
already catches nesting, which is how §39 caught it.

---

## 41. The last unwired link, and four latent defects the data revealed (2026-09-28)

Continuing the ranked list at the end of §39/§40: item 1 was the balance verification
form not offering the weight set, item 2 was `usable_lots` offering standards the gate
rejects. Both are closed. Getting there surfaced **four separate defects that had
never executed**, each for the same structural reason — the code path required data
the instance had never held.

### 41.1 The balance form now names the reference weight set (item 1)

`facility_balance.pt` offers the registered sets and the handler records the choice;
`equipment_provenance` then closes the chain to the metrology laboratory. Proven live
rather than by reading the column back — recorded through the **form**, then asked the
gate:

    verification recorded WITH a weight set    problems: NONE
      -> traced to AUDIT-WS-001, Northeast Metrology Laboratory,
         cert NML-2026-4417, due 2027-03-02, NIST=True
    verification recorded WITHOUT one          problems: [no reference weight set
         recorded, so the verification cannot be traced to a calibrated standard]
    no verification that day at all            problems: [no balance verification
         for 2026-09-20, the day it was used]

The field is **required**, not optional: a verification is a measurement, and a
measurement with no reference standard establishes nothing. With no set registered the
form cannot be submitted, and says why, with a link to Weight Sets. Optional would
have built the field and left the defect in place.

`(f.get("weight_set_id", "").strip() or None)` — an empty string is not NULL, and a
`weight_set_id IS NOT NULL` audit query would count a traceless row as traced.

The pipette log stopped printing `(weight_set_id or '')[:8]`, a truncated uuid that
identified the set to nobody. Both logs now resolve the label through one helper.

### 41.2 The Balance Verification Log had never rendered at all

Selecting a balance 500'd:

    LocationError: (RepeatDictWrapper, 'wp')
    facility_balance.pt: <tal:each tal:repeat="wp view/weight_points"
                                   tal:define="i repeat/wp/index">

**`tal:define` executes before `tal:repeat` on the same element**, so `repeat['wp']`
does not exist yet. Proven pre-existing by contrast: HEAD's template fails identically
with none of this work applied. Invisible because the whole form sits inside
`tal:condition="unit"` and `facility_units` held zero rows — no balance could be
selected, so the form never rendered. Registering the first balance revealed it.
`i` is now defined on the child `<tr>`.

### 41.3 Three py2 `sqlite3.Row` defects, invisible to a py3 test suite

`list_balance_verifications` raised `IndexError: Index must be int or string` the
moment a verification existed. A `sqlite3.Row` accepts only an int or a **byte**
string as a key; `facility_qc.py` has `unicode_literals`, so every `row["col"]` in it
passes a unicode key:

    >>> r['id']        # python 2.7.18
    IndexError: Index must be int or string
    >>> dict(r)['id']
    1

Three sites carried it — `list_balance_verifications`, `dashboard_summary`'s eye wash
and balance branches, and `save_study_point`. **The py3 test suite cannot see this
class of defect at all**, because `sqlite3.Row` accepts `str` keys under py3; the
defect exists only in the interpreter that runs production. The reason it never bit:
§10.4's finding that the facility database has never held a row. So a quarterly NIST
temperature study would have crashed on its first point, and the eye wash dashboard
branch on the first log.

All four verified under py2 with rows present:

    OK  list_balance_verifications          read back 2 verifications, 4 points
    OK  dashboard_summary (balance branch)  status='ok'
    OK  dashboard_summary (eyewash branch)  status='ok'
    OK  save_study_point                    5 points judged, study status='pass'

### 41.4 The lot picker had never opened in this deployment

Driving the real page with a browser, the autocomplete fetch returned 500:

    GET /@@pfas-lot-autocomplete  ->  AttributeError: portal_url

`data-ac` was the root-relative `/@@pfas-lot-autocomplete`. **The site is not at the
server root**: Zope serves it at `/senaite`, and nginx roots VirtualHostMonster there
as well, so the path reached the Zope root — 500 direct, 404 through nginx. Four sites
carried it (both logbook autocompletes and two reagent lookups); every other place
prefixes `PORTAL_URL`. All now build from `view/portal_url`.

This also explains the shape of item 2: the picker could not have been observed
offering blocked lots, because it never opened.

Fixing four URLs made three more paths reachable for the first time, which is the
pattern that produced §41.2 and §41.3 — so each was exercised rather than assumed:

    @@pfas-reagent-autocomplete?q=methanol          200, real reagent rows
    @@pfas-reagents?action=lookup_json&q=methanol   200, real inventory items
    @@pfas-logbook-250                              200, INV_URL interpolated
    @@pfas-prep-standards                           200, LOOKUP_URL interpolated
    @@pfas-logbook-dynamic?slug=251 (concise)       200, data-ac absolute
    @@pfas-logbook-dynamic?slug=251&mode=guided     200, data-ac absolute

The guided runtime renders the same field macro through a different view, so it was
checked separately: `PFASLogbook250View` and the dynamic view both inherit
`portal_url` from `_LogbookBase`, and `view/portal_url` would have raised on a view
that only had `_portal()`. The mode cookie was set back to concise afterwards.

No logbook definition currently contains a `reagent_ref` field, so the reagent
autocomplete has no live consumer — the endpoint answers, and the URL is right for
the day one is added.

### 41.5 The gate verdict now travels with the offer (item 2)

`usable_lots` returns `gate_ok` and `gate_problems` per lot, from the same
`build_parentage` walk the certificate and the release gate use — so the reason shown
at the bench is the reason release will give. The dropdown and the default hint both
show it, verified in a browser:

    [BLOCKED] AUDIT-NOPARENT-001  exp 2027-03-01
              ⚠ blocks release: no parent lots recorded — this lot cannot be traced
    [  ok   ] AUDIT-CLEAN-001     exp 2027-03-01
    [BLOCKED] AUDIT-BROKEN-001    exp 2027-03-01
              ⚠ blocks release: lot NO-SUCH-LOT-9999 is not in inventory

**Annotated, not filtered.** An analyst holding the physical bottle who cannot find it
in the list learns nothing and works around the system. For the same reason the
default still offers the most recent lot even when it blocks, flagged rather than
silently swapped: the analyst uses the bottle they have, and the record must reflect
that. Quietly defaulting to a different lot to make a gate pass would falsify the
record.

Cost measured rather than assumed, since this sits on a typeahead:

    with the parentage walk      5.1 ms/call
    with the walk stubbed out    4.5 ms/call
    -> 0.2 ms per lot; 6.6 ms to walk all 14 including the water-log query

### 41.6 Four static guards, and one that was worthless until mutated

`tests/test_equipment_chain.py` (12 tests) covers the chain functionally against a
scratch database, plus the form/handler wiring. `tests/test_template_expressions.py`
gained two guards: the `tal:define`/`tal:repeat` ordering trap, and root-relative view
URLs.

**Every guard was mutation-tested** — the defect reintroduced, the guard required to
fail. That is not ceremony. The root-URL guard passed with the real defect reinstated:
its pattern anchored on a quote (`'/@@view'`, the JS form) and the TAL form is
`string:/@@view"`, with the quote at the far end of the attribute. A test that cannot
fail is worse than no test because it reports safety. Only the mutation found it.

The per-function scoping of the `sqlite3.Row` guard came the same way: collecting
fetch-bound names module-wide produced **20 false positives** — `row` is fetch-bound
in `get_unit` and a plain `dict(u)` in `dashboard_summary`, and a name means different
things in different scopes.

And the comment-scanning trap appeared for a **fourth** time: the JS comment explaining
the root-relative URL defect contains a root-relative URL. `_strip_js_comments` now
blanks `/* */` and `//` runs the way `_strip_comments` blanks HTML comments.

### 41.7 One more self-inflicted scare, recorded

The suite first reported 4 failures — `test_fault_injection`, `test_profiles`,
`test_salt_correction`, `test_unconfigured_criteria`. They fail at HEAD too — because the suite must be run with `PFAS_PROFILES_PATH` set, exactly as
documented at the top of this file. With the documented environment: **31/31 test files
pass**, `audit_configurable --strict` exit 0. Checked before reporting a regression
that was not one.

### Verification

Every `AUDIT-*` record removed: 11 prepared standards (the as-found count) and 0 rows
in all nine facility tables. Balance log, weight sets, pipette calibration, facility
QC, reagents, prep standards and facility units all HTTP 200.

### Still open

- **as-of-date expiry**: `_is_expired` takes `as_of` and nothing passes it. The USE
  date has to be threaded through the gate first, or historical batches would be
  condemned for standards that were in date when used. Changes release behaviour on
  real data, so the WS-0005 verdict must be captured before and diffed after.
- `PreparedStandard` records no equipment, so a prep certificate cannot name the
  balance that weighed it (§37.5). Two pieces: the field, and the certificate section
  that reads it — certificate first, so the field has a consumer the day it exists.
- §33.3 the Certificate of Preparation still prints an unresolvable parent as fact on
  certificates generated before the §36 fix.
- `IReagent` still has no parentage field.
- The facility database is empty again by design, so §41.2 and §41.3's code paths are
  once more unexercised in production until the lab records its first verification.

---

## 42. A prepared standard's certificate now names the balance (2026-09-28)

§37.5, item 4 on the list. The Certificate of Preparation carried this sentence:

> Equipment used (balance, pipettes and their calibration status) is *not recorded
> against this lot* — see the prep logbook entry named above.

A prepared standard's assigned value rests on a **mass and a volume**. Under ISO 17025
§6.5 the balance and the pipette that measured them are part of its traceability, so a
certificate that cannot name them cannot substantiate the value it carries. Pointing at
a logbook is not traceability; it is a promise that traceability exists somewhere else.

### The consumer was built before the producer

Deliberately, and it is the §39 lesson applied in the right order: the certificate
section was written first, so the field had a reader the day it existed rather than
accumulating data nothing looked at.

`build_equipment(portal, rec)` resolves each recorded unit through
**`facility_qc.equipment_provenance`** — the same calibration walk the release gate
uses for an extraction. One function, so the chain a prep certificate prints is the
chain release checks. A second implementation would be a second answer.

**`as_of` is the PREPARED date, not today.** A standard weighed on a balance that was in
calibration that morning stays defensible after the calibration lapses; judging against
today would condemn correct historical work. Same reason `build_parentage` takes
`used_on`.

Stored as `[{"unit_id", "role"}]` in `senaite.pfas.prepstd.equipment`, referencing the
Facility QC registry rather than copying names and certificate numbers onto the lot —
a copy rots, a reference resolves.

### Three cases, verified live

    AUDIT2-WITH-EQUIP  prepared 2026-09-28
      Analytical balance -> balance_verification, weight_set
         AUDIT2-WS, Northeast Metrology, cert NML-2026-9001
      Pipette 1000 uL    -> calibration 2026-07-01 by Pipette Services Ltd
                            (cert PS-2026-55), due 2026-10-01
    AUDIT2-NO-EQUIP    -> "No equipment recorded against this lot"
    AUDIT2-STALE-CAL   prepared 2026-09-20, same balance
      -> PROBLEMS: no balance verification for 2026-09-20, the day it was used
         and the certificate prints the banner, on the document

The third case is the one that matters: the certificate does not go quiet when the
chain breaks, it states the break — the same treatment §36 gave an unresolvable parent.

### 42.1 The first version dated the pipette without saying who calibrated it

It printed `calibration 2026-07-01, due 2026-10-01`. For an **external** check the
provider and its certificate number *are* the traceability endpoint — the role the
metrology laboratory plays for a weight set — so a row that omits them asserts the
pipette was calibrated while withholding by whom. Now named.

### 42.2 The bench path inherits equipment instead of asking again

An extraction stage already collects equipment serial numbers, so a solution prepared
during it takes them from the page rather than asking the analyst a second time. Each
serial is resolved against the Facility QC registry with `unit_by_serial`, and **only a
serial that resolves is recorded** — an unregistered one has no calibration chain to
follow, so keeping it would put a name on the certificate with nothing behind it.

### 42.3 The `status` trap, avoided by construction

`_populate_obj` writes the annotation only when the caller supplied the key, and the
handler sets it only when the form posts `equipment_posted`. Without both, any save
through a path that does not post the field would wipe the record — which is exactly
how an unconditional `status` assignment once resurrected exhausted lots. Verified:

    equipment survives a save that does not post it: yes

### Verification

31/31 test files (`test_equipment_chain.py` now 16 tests), `audit_configurable
--strict` exit 0. Form renders the pickers and the POST records both units. Every
`AUDIT*` record removed: 11 prepared standards and 0 rows in all facility tables.

### Still open

- **as-of-date expiry** — the last item on the list. `_is_expired` takes `as_of` and
  nothing passes it. Before changing it, the WS-0005 gate verdict has to be captured
  and diffed, and one question settled in code: which date is the USE date — the
  worksheet's, the FM-ENV-251 extraction date, or the analysis date. A lot in date on
  one and expired on another is the case that will show up.
- §33.3 certificates generated before §36 still print an unresolvable parent as fact.
- `IReagent` has no parentage field.
- Prep equipment is stated on the certificate but does **not** gate release. Adding it
  to `parentage_problems`/`gate_problems` would change release behaviour on historical
  data and is a separate decision for the QA manager.

---

## 43. A lot is judged against the day it was used — and WS-0005 now FAILS (2026-09-28)

The last item on the list. DECISIONS.md 2026-08-03 item 7 decided this and
`reagents._is_expired` grew an `as_of` parameter that **nothing ever passed**. Judging
a lot against TODAY makes a released batch less defensible as time passes: every
standard on this instance is expired now, yet the runs that used them were in date at
the time. A gate keyed on today would retroactively condemn correct work, which is the
opposite of what it is for.

### 43.1 There is no single use date, and the data says so

The question was which date to thread through — the worksheet's, the extraction date,
the analysis date. The data answered it. On the real released WS-0005:

    FM-ENV-250  prepared_date    2025-10-20
    FM-ENV-251  prepared_date    2025-10-06
    FM-ENV-252  extraction_date  2026-08-03
    FM-ENV-253  processing_date  2025-10-17

**Ten months apart.** Each logbook carries the date ITS OWN rows were used, so each set
of lots is judged against its own date. A worksheet-wide date would have condemned one
set or excused the other, and either would be wrong. `_use_date(lb, *fields)` reads it
per logbook; `_expired_at_use` decides.

A prepared standard is judged on its **parent-tightened** expiry — a prep whose source
CRM expired first expired with it — so the stored date on the lot is not the one that
counts.

A logbook with no date is **reported, not enforced**: an unrecorded date is not
evidence of expiry. That is the same posture the equipment walk takes for an
unregistered serial (§38), and it goes in a new `tree["warnings"]` so an unenforceable
check never looks like a satisfied one.

### 43.2 The verdict captured before, diffed after — and one worksheet changed

Every worksheet's gate verdict was written to a file first, because "still passes"
needs a recorded before-value:

    WS-0001  before=False  after=False
    WS-0002  before=False  after=False
    WS-0003  before=False  after=False
    WS-0004  before=False  after=False
    WS-0006  before=False  after=False
    WS-0007  before=False  after=False
    WS-0008  before=False  after=False
    WS-001   before=True   after=True
    WS-0005  before=True   after=False   <-- CHANGED

**WS-0005 is the released, verified worksheet — the only sample ever published (§5).**
It now fails traceability on:

    prepared standard lot PS-KCP-IS-251006  expired 2026-04-06, used 2026-08-03
    prepared standard lot PS-KCP-MPA-251020 expired 2025-10-27, used 2026-08-03
    prepared standard lot PS-KCP-CAL-251006 expired 2026-04-06 (via 251 fields)
    prepared standard lot PS-KCP-SPK-251020 expired 2026-04-20 (via 251 fields)

### 43.3 This is the DATA, and it was checked rather than assumed

The check was interrogated at the boundary before the failure was believed:

    lot PS-KCP-IS-251006, effective expiry 2026-04-06
      used 2025-10-21 -> in date, passes
      used 2026-04-05 -> in date, passes
      used 2026-04-06 -> in date, passes
      used 2026-04-07 -> EXPIRED
      used 2026-08-03 -> EXPIRED

So the logic is right at the day boundary, and WS-0005's failure is a property of the
recorded data: the FM-ENV-252 extraction date is **2026-08-03** — the E2E run on real
instrument data (§ E2E_TEST_2026-08-02) — while its standards are from the October 2025
KCP scaffold and expired months earlier. The 252 logbook was re-dated for that E2E run
and the standards were not re-prepared.

**This is not a recall.** The gate governs RELEASE, and WS-0005 was released and
published months ago; a gate that fails it today has no retroactive effect on the
certificate already issued. What the failure means is that the same worksheet could not
be released again as it stands — which is the correct answer, because as recorded it
used expired standards.

**Left as found.** Editing lot expiry dates or the extraction date to make the gate
green would falsify a record to satisfy a check, which is precisely the failure mode the
check exists to prevent. Whether the E2E data should be re-scaffolded with in-date
standards, or WS-0005 treated as a historical artefact, is the lab's call — but the
gate is now telling the truth about it, and it was not before.

### 43.4 The reagent check could not fire, and passing was how I found out

The first version handed `self._reagent_dict(...)` to the expiry resolver.
`_reagent_dict` is the **display projection** — `title, url, supplier, cat_number,
lot_number, has_coa` — and carries no expiry of any kind, so `_effective_expiry`
returned `""`, `_is_expired` answered False, and **every reagent read as in date**.

Found by demanding the check fail: forcing the use date to 2030-01-01, when every
reagent on the instance is expired, and watching it report nothing. `_reagent_record()`
now supplies the full record, and forcing the date proves each branch fires at its real
call site:

    use date forced to 2030-01-01
      252.reagents      7   lot FISHER-H2O-260510 expired 2028-01-01
      252.standards     3
      pds_a_lot / pds_b_lot / analyte_pds_lot / analyte_spike_lot / cal_a_lot  1 each

That is the second check this session that reported safety it could not deliver — the
first being §41.6's root-URL guard. Both were caught the same way, by requiring the
test to fail on the defect, and neither would have been caught by running the suite.

### 43.5 And the line-scoped-check mistake, for the second time

The guard written to pin §43.4 also passed with the defect reinstated, because it
scanned line by line and the call spans two lines — `self._expired_at_use(` on one, its
first argument on the next. Exactly the shape that defeated the root-URL guard.
Rewritten on the AST: find every `Call` to `_expired_at_use` and inspect its first
argument. **A textual scan cannot see a multi-line construct; use the parse tree.**

### 43.6 A gate that blocks must say why on the page that blocks

Adding `reason` to the unresolved entries changed nothing on screen at first: the
Traceability tab rendered `u/lot` and `u/source` and **never read `reason`**, under one
blanket line — *"Ensure reagent/standard lot numbers are entered in the inventory."*
For an expiry-at-use failure that advice is simply wrong: the lot IS in the inventory,
and the reviewer would have been sent to fix something that was not broken.

The tab now lists each blocked link with its own reason, and **every** entry carries
one — including the four "not in inventory" sites that previously relied on the reader
inferring it. Making the data self-describing removed the template's fallback branch
entirely, which also removed a `not:u/reason|nothing` precedence question of the kind
that was deliberately avoided in `facility_balance.pt`.

`tree["warnings"]` gets its own **"Not checked"** box, visually distinct from a
failure. A check that cannot be performed must not look like one that passed, and it
must not look like one that failed either.

All three shapes were rendered and confirmed: WS-0001 (old-shaped entries), WS-0005
(expiry reasons shown), WS-0002 (warnings, no failures).

### Verification

32/32 test files (`test_expiry_at_use.py`, 7 tests, every one mutation-tested),
`audit_configurable --strict` exit 0. No test data created, so nothing to clean up.

### Still open

- **WS-0005's expiry failure is unresolved by design** — a data decision for the lab,
  §43.2/43.3.
- **FM-ENV-253's `processing_materials` lots are traced NOWHERE.** The tree reads 252
  and 251 only. The rows carry lots, `processing_date` records when they were used, and
  nothing reads either — so a sorbent or cartridge lot named in 253 is neither resolved
  nor reported unresolved. This is the *same class* as §33.12 (`extraction_materials`
  traced nowhere), which was fixed; it is not a smaller version of an open item, it is
  the identical structural gap in the one logbook the walk never learned to read.
- §33.3 certificates generated before §36 still print an unresolvable parent as fact.
- `IReagent` has no parentage field.
- Prep equipment is stated on the certificate but does not gate release (§42).

---

## 44. FM-ENV-253 enters the chain, and a certificate stops replaying the past (2026-09-28)

Two gaps closed, two deliberately left. A fresh gate baseline was captured first,
recording the **reason set** and not only the verdict — WS-0005 already failed, so
"failed before" had to stay distinguishable from "now fails for more reasons".

### 44.1 The one logbook the walk never read

FM-ENV-253 (sample processing / homogenisation) was loaded nowhere. Its rows carry
lots, `processing_date` records when they were used, and `balance_sn` names the balance
the samples were **weighed** on. None of it was read — so this is not a smaller version
of an open item, it is the identical structural gap §33.12 fixed for
`extraction_materials`, in the last logbook still outside the walk.

`processing_materials` now resolves against inventory, judged against
`processing_date` — **not** the extraction date, which on WS-0005 is ten months later.
The rows land in `direct_reagents`, the same bucket `extraction_materials` uses: they
are the same kind of thing, and a separate tree key would need separate rendering for
no gain.

### 44.2 The balance the samples were weighed on

`balance_sn` is free text and nothing resolved it, so **the mass every result is
calculated from rested on a balance with no calibration chain** — exactly the defect
§38 fixed for the extraction stages' `equipment_sns`. It now resolves through
`unit_by_serial` and `equipment_provenance` as of the processing date, reusing the
settled policy rather than inventing a third: an **unregistered** serial is a warning
(we cannot tell what it owed), a **registered** unit with no verification for the day
is a problem.

### 44.3 `N/A` is an analyst saying "no lot", not a lot that failed to resolve

WS-0005's FM-ENV-253 records `{"name": "Dry ice", "lot": "N/A"}`. Dry ice genuinely has
no lot number. Resolving that text would have invented a traceability failure for dry
ice the first time the 253 walk ran — a false positive shipped on day one.

`lot_or_none()` recognises the sentinel forms (`n/a`, `na`, `none`, `nil`, `-`, …,
case-insensitively) and yields an **empty** lot, which the walk already skips
everywhere. Not a new hole: a blank lot is skipped today, so this only recognises the
same statement written a different way. It is **reported** as a warning, because the
supported way to say not-applicable is to strike the row — `active_rows` already makes
a struck row inert — and free text saying it informally should not be silently
equivalent.

One sentinel exists across every logbook on the instance, and it is that one.

### 44.4 The diff: no verdict moved, and one real finding

    WS-0001..WS-0008, WS-001   verdict unchanged
      + warns: FM-ENV-253 records no date, so the lots it names cannot be checked

    WS-0005                    verdict unchanged (already failing)
      + BLOCKS: GRD-2025-003 — lot is not in the inventory
      + warns : Dry ice recorded with lot "N/A", so it is traced to nothing
      + warns : balance MT-XPR205-4471 is not registered in Facility QC

**The grinder blades that touched every sample in the batch were never entered in
inventory.** That is the finding; the walk simply could not see it before.

### 44.5 A certificate was replaying a document written in August

`_serve_cert` preferred the **stored file** whenever it existed. Seven of the eleven
prepared standards had one dating to **2026-08-03** — before §36's parentage hierarchy
and before §42's equipment section:

    stored on disk   3831–4244 bytes   parentage=old flat section   equipment=NO
    served now       7816–8628 bytes   full hierarchy               equipment section

So every certificate written before §36 still asserted an unresolvable parent as
established fact with the QA attestation attached — the exact claim §33.3 recorded as
wrong — and the document disagreed with the release gate about the same lot.

**And the fallback reproduced the defect it existed to cover.** The
regenerate-when-missing branch called `_render_cert_html(rec, signers)` with **no
`portal=`**, and without the portal the renderer cannot walk parentage or equipment at
all. The branch meant to handle a missing file rendered the same wrong document.

Now rendered on every serve, resolved. It costs a parentage walk (~0.2 ms/lot, measured
in §41.5) and cannot go stale. Demonstrated on the exact lot §33.3 named:
`PS-FDA-2026-A`, which has no parents, now prints **"THIS PARENTAGE IS NOT FULLY
SUBSTANTIATED"** where it previously printed its parentage as fact. A bogus uid still
404s.

**When sign-off is built, this has to change with it.** A *signed* certificate must be
frozen, the way §26 freezes resolved criteria at the moment they judge. Nothing captures
a signature yet — every certificate prints "UNSIGNED UNTIL DATED" with reserved rows —
so there is nothing to freeze and a fresh render is unambiguously the truthful answer
today. Said in the code, at the place that will need it.

### 44.6 Two more guards that could not fail

Four mutations were run against the new tests. Two passed with the defect reinstated:

  * promoting the unregistered-balance **warning** to a blocking **problem**, and
  * reading `row["lot"]` directly instead of through `lot_or_none`.

Same cause both times: the test split on a start marker and read **to the end of the
function**, so `"is not registered in Facility QC"` was satisfied by the extraction
equipment block further down, and `"if sentinel:"` by a hard-coded `sentinel = u""`.
A region that includes neighbouring code cannot test that region. `_section(src, start,
end)` now bounds it, and the policy is asserted structurally — *which list the append
goes to* — rather than by message text.

That is the third and fourth such guard this week. The pattern is consistent enough to
state as a rule: **a guard is not finished until the defect has been reintroduced and
the guard has failed.**

### Deliberately NOT done, and why

- **Prep equipment does not gate release.** §42 records it as a QA-manager decision and
  "fix the gaps" does not retire that. It would also fail immediately and universally:
  the facility database is empty, so *every* prepared standard has zero equipment
  recorded, and gating it would block every worksheet using any prepared standard. A
  check that fails everything on day one teaches a lab to ignore the gate. Stated on the
  certificate, not enforced, until the lab records equipment.
- **`IReagent` still has no parentage field.** §35 already concluded it is not needed now
  that in-house preparations are PreparedStandards. Adding it would create a field with
  no producer and no consumer — the exact "consumer with no producer" shape §14 lists as
  one of this codebase's two recurring defect forms.

### Verification

32/32 test files (`test_traceability_gate.py` now 38 tests), `audit_configurable
--strict` exit 0. Certificates served fresh at 200 with both new sections, bogus uid
404. No test data created. No gate verdict changed.

### Still open

- WS-0005's expiry failures and the unregistered `GRD-2025-003` lot and
  `MT-XPR205-4471` balance — all data decisions for the lab, §43.3 and §44.4.
- Prep equipment stated but not gated (above).
- Certificate freezing on sign-off, once sign-off exists (§44.5).

---

## 45. A configuration layer the lab admin owns (2026-09-29)

Asked for: *"include these incremental customisations into the system under the
system admin account so that I can make smaller edits without diving into the pile
of code."* Agreed shape: a console **and** a registry; all four categories (QC
limits, vocabularies, document wording, thresholds); and split roles, because
withdrawing a vocabulary term can orphan records that reference it.

### 45.1 It is the main line of the roadmap, not a side quest

Auditing the registers for what remains produced this unprompted: **the largest
single class of remaining work is "there is no surface on which to enter the
data."** GAPS already says so in its own words — *"a data-entry surface, not a
missing call"* (§31), *"unrecordable, not merely unenforced"* (§33.15), *"nowhere
to enter"* (§31) — and §14.3 is blunt that the un-entered numbers, *"not any code
gap, is what blocks production use."* Eleven register items are blocked on a
missing surface. So this layer is the highest-leverage thing left.

### 45.2 The registry — `src/senaite/pfas/settings_registry.py`

Generalises what `qc_qualification.get_library` and `facility_qc`'s defaults
arrived at independently: seed in code, the lab's edits in a portal annotation,
saved edits winning **field by field**, and **only the difference stored** so a
seed correction still reaches anything never overridden.

**Two read paths, deliberately.** `get()` refuses for a judging setting with no
value — the 2026-08-03 decision. `describe()` never raises, because a console must
RENDER the unset rows: they are the ones that block a run, and if `describe()`
raised they would be the only rows it could not draw.

`register()` refuses a duplicate key (rule 3, enforced where WIRING §1.4 can only
report) and refuses `judging=True` carrying a seed. Storage is one annotation,
`senaite.pfas.settings_registry` — **not** `senaite.pfas.lab_settings`, which
`browser/reagents.py:53` already owns. Not a fourth storage tier either: §7's
first rule is "one ZODB object → annotate it" and the portal is one object.

### 45.3 The console — `@@pfas-lab-settings`

40 settings declared, every one `linked`: an existing editor owns it and the
console links there. **The view has no POST branch at all** and a test asserts it
— a second writer to data another editor owns would recreate the split-key defect
at a larger scale. A registry-owned key may be created only in the same change as
the consumer that reads it, so the console can never list a setting that changes
nothing.

Two settings already read **NOT CONFIGURED** — holding time for FDA 32-PFAS and
EPA 1633A. That is the state that blocks those batches, and until now nothing told
a lab *which* criterion was missing.

### 45.4 What the console found on its first day

**`balance_tolerance` and `study_tolerance` were editable and inert.** Both are
collected by the Unit Registry's Defaults panel, saved, and displayed back, and no
consumer read either. A lab could loosen or tighten its balance criterion and no
verification changed its verdict.

The comment beside the one consumer claimed the opposite — *"A weight point with no
tolerance falls back to the lab's configured default rather than a literal, so one
place sets it"* — while reading the module constant. **A comment asserting a fix
that was never made is harder to catch than no comment at all.**

Fixed and proven live on a deviation of 0.003 g, which sits between the seed and a
loosened setting:

    seed 0.001        -> passed=0
    lab sets 0.005    -> passed=1   (the same reading)
    point's own 0.001 -> passed=0   (per-point precedence preserved)

No behaviour change on this instance today — the value is not overridden and the
facility tables are empty. The change is that the field now works when the lab
sets it.

### 45.5 Three defects in the register's own instruments

- **`registry.xml` ships four dead settings.** `senaite.pfas.instrument_watch_dir`,
  `report_output_dir`, `default_method`, `ccv_frequency_override` — **nothing reads
  any of them** (verified repo-wide). They appear editable in Plone's control panel
  and change nothing, and `ccv_frequency_override` reads like it changes QC
  behaviour. `audit_configurable` reports DEAD 0 because its reachability analysis
  covers the method-profile JSON only. Decide per record: wire or delete.
- **`CONFIG_AUDIT.md` had drifted** — 108 keys / 96 values committed against 118 /
  107 live — because GAPS' verification chain regenerates `WIRING.md` but runs the
  audit with `--strict`, which writes nothing. Add `--format md > CONFIG_AUDIT.md`
  to that chain.
- **`UNIT_TYPES` left the register silently.** `_looks_like_lab_table` inspects a
  15-line window from the opening brace, and the `("pipette", "Pipette")` row added
  in §38 pushed its lab signal out of range. A real finding disappeared and nothing
  noticed. The window heuristic is its own fix.

### 45.6 I nearly disabled the audit, and only the count showed it

Excluding `_REGISTRY = {}` by widening the *match* pattern with a negative
lookahead dropped the hardcoded count **109 → 13**: most real tables open a brace
and put their contents on the NEXT line, so the lookahead's end-of-line
alternative excluded nearly all of them. Narrowed to a same-line empty pair; 108 →
107, removing exactly the one false positive.

`tests/test_audit_hardcoded_hints.py` now pins the scan by BEHAVIOUR on
representative line shapes rather than by a total, because a total changes
legitimately whenever the code does and a test that must be edited after every
real change stops being read.

### 45.7 The comment-scanning trap, fifth occurrence

The comment written to explain *which* badge colours are global names
`.badge-custom`, and the scan for a page-local redefinition matched the prose.
Comments are stripped before scanning. Five occurrences (§40.1, §41.6, the ISO-date
test, `test_rule_toggles`, and this) make it a standing rule rather than bad luck:
**prose about a name contains the name.**

### 45.8 Corrections to my own audit of the authorisation gap

Two things I asserted and had to withdraw after checking properly:
`browser/projects.py:44,465` and `prep_logbooks.py:26,403` **do** call
`perms.require_manager`, and `lims_setup.py` has **zero** POST handling. My greps
matched patterns those modules do not use. The real ungated list is seven surfaces
— the three `facility_qc` config views, `import_studio`, `reagents` (incl. expiry
defaults), `prepared_standards`, `deviations`.

And the correction that mattered most: **five of `facility_qc`'s ten views are the
daily bench logs.** Tightening the module wholesale — which "fix the ungated
surfaces" invited — would have stopped the lab recording temperatures.

### Still open

- ~~**Phase 3, authorisation.**~~ Done — §46.
- ~~**Never re-run the GenericSetup profile on this instance.**~~ Fixed — §47.
  Both claims here were half right: the profile is not "never re-run", it re-runs
  on **every restart**; and the unpack does not raise, it was swallowed as a
  warning every time.
- Vocabularies remain code-only, so the console's Vocabulary group is empty and
  says so. Retire-not-delete with usage counts is Phase 6.
- ~~**CLAUDE.md §5 still describes ten workspaces.**~~ Rewritten — §48.4.

---

## 46. Configuration POSTs are gated per action; the bench stays open (2026-09-29)

Phase 3 of §45. Seven configuration surfaces accepted a POST from any
authenticated user. After checking each handler rather than its name, **five
needed a gate** — §45.8's list was wrong twice more:

- **`deviations` was already gated.** `can_manage()` guards add_ca, complete_ca,
  mark_notification_sent and close_deviation; `can_edit()` guards the rest. My
  greps looked for `require_manager` and this module does not use it. (Its
  `can_manage` omits `Owner`, unlike `perms.ALLOWED_ROLES` — left as found.)
- **`prepared_standards` delete was worse than listed.** It removes the object
  AND its certificate outright, in production too, breaking the middle link of
  the traceability chain for every result that used the lot.

### 46.1 The mechanism

`perms.deny_gated_action(context, request, action, gates)` over a module-level
table per view — `UNITS_GATES`, `WEIGHT_SET_GATES`, `STUDIO_GATES`,
`REAGENT_GATES`, `PREP_STANDARD_GATES`. Role checks, not Zope permissions: see
DECISIONS 2026-09-29 for why the plan changed. Two tiers — `config` (Manager,
LabManager, Owner) and `site_admin` (Manager, Owner), the latter only for the
sensor API key. An action absent from a table is open; **an unknown tier
denies**, so a typo in a tier fails closed.

The gate is the first statement of each POST branch — ahead of the CSRF-disable,
every handler and every redirect.

### 46.2 What stays open, deliberately

All five daily logs, **pipette calibration** (decided: an in-house check is a
measurement, like the balance log), reagent add/edit/open/status/CoA/scan/
delete/restore (delete archives in production), prepared-standard add/edit/
status. CLAUDE.md §4 requires the bench to be performable by any lab user and by
a future service account, so a bench action becoming manager-only is as much a
defect as a config action left open, and the test says so.

### 46.3 The test — `tests/test_action_gates.py`

Behaviour for the helper (stubbed `AccessControl`), AST for the wiring. It pins
the agreed split in both directions, that each view consults **its own** table as
the first statement of its POST branch and returns the result, that no bench log
calls a gate, and — the one easy to miss — that **every gated action name is one
the view actually dispatches**. A misspelt key gates nothing and leaves the real
action open, silently.

Mutation-tested: 12 mutations (gate removed, moved after the CSRF-disable, result
not returned, wrong table, key typo in the table, typo in spec and table
together, API key downgraded to config, LabManager added to site_admin, unknown
tier permits, broken security context permits, a bench log gated, a bench action
gated). **All 12 killed.**

### 46.4 Verified live

After a restart (`method_profiles.json` md5 identical before and after), with
three throwaway users created by `bin/instance run` and deleted afterwards:

    action                         LabClerk  LabManager  Manager
    facility-units delete          403       302         302
    weight-sets delete             403       302         302
    import-studio retire_profile   403       302         302
    prep-standards delete          403       302         302
    reagents purge_test            403       (ran)       not sent
    facility-units save_api_key    403       403         302

Probes used nonexistent ids so the permitted paths changed nothing. The stored
API key's md5 was identical before and after. Bench paths as the LabClerk:
prep-standard status 302, reagent status 302, **water log 302 and the row was
recorded** — removed afterwards, `water_qc_logs` back to 0.

**My error, recorded.** The probe loop excluded only the Manager from
`purge_test`, so it **really ran as the LabManager** — a hard delete of every
reagent created before `production_since`. It matched none: `production_since`
is 2026-06-22 and the reagent folder held the same 14 objects before each of the
three most recent transactions (read with `db.open(before=tid)`) as after. No
data was lost. From that point destructive actions were probed on the refusal
path only. **A permitted-path probe of a destructive action is a destructive
action.**

Also found: the sensor API key is **unset**. The ingest endpoint refuses every
reading when it is (`not expected_key` → 403), so it fails closed; no sensor can
post until a Manager or Owner sets one.

### 46.5 The gate could be walked around through any object a user created

Found in review, after the commit above, and proven live before fixing. The five
views are registered `for="*"`, and Plone gives the **`Owner` local role** to
whoever creates an object. `Owner` is in both tiers, and the check resolved roles
at the traversal context. So a LabClerk with a local `Owner` role on a reagent
posted `…/pfas_reagents/<id>/@@pfas-facility-units`:

    context                         action                  before  after
    portal                          save_api_key (empty)    403     403
    a reagent the clerk owns        save_api_key (empty)    302     403
    a reagent the clerk owns        weight-set delete       302     403
    a reagent the clerk owns        purge_test              —       403
    a reagent the clerk owns        reagent status (bench)  —       302

Every bench chemist is `Owner` of every reagent and standard they have added, so
this was not an edge case: **the site_admin tier, whose whole point was to be
narrower than LabManager, was open to any bench user who had created anything.**

Fixed in `perms._has_any_role`: roles are resolved **at the portal**, never at the
context. Every store these gates protect is portal-scoped (portal annotations,
SQLite), so the portal is the only place the question means anything. Failure to
resolve the portal denies. Two tests added — a clerk carrying a local Owner via
the traversed object is refused at both tiers, and an unresolvable portal denies —
and reverting the anchoring is killed by the first.

No side doors: every writer behind these gates (`set_api_key`, `delete_unit`,
`save_unit`, `save_facility_defaults`, `save_weight_set`, `save_vendor_profile`,
`set_vendor_profile_retired`, `_save_lab_settings`, `_purge_test_reagents`) is
reached only from the gated handlers, `_maybe_record_production_since`, or
setuphandlers seeding. `@@pfas-instrument-profile` copies before annotating its
response and writes nothing.

**The same flaw is in the pre-existing gates, NOT fixed here.**
`perms.require_manager` resolves at the context, and so do the private copies in
`method_profiles.py:39` and `egad_config.py:93`, each with `Owner` in its role
set. Nine modules call one of them — `logbook_media`, `logbook_batches`,
`projects`, `batch_project_viewlet`, `egad_config`, `prep_logbooks`, `logbooks`,
`method_profiles`, `data_review`. **`method_profiles` is the QC-criteria editor.**
Not probed live; the mechanism is identical. Awaiting a decision (below).

### 46.6 The QC-criteria editor was open to the bench, and is now closed

Probed live with the same throwaway LabClerk holding a local `Owner` on one
reagent, GET only:

    view                        clerk@portal  clerk via owned reagent
                                              before   after
    pfas-method-profiles        403           200      403
    pfas-method-profile-edit    403           200      403
    pfas-prep-logbooks          403           200      403
    pfas-egad-config            403           —        403

**A bench chemist could open and submit the QC-criteria editor** by adding any
reagent and going through it. `perms.require_manager` now delegates to the
portal-anchored `_has_any_role`. `method_profiles.py` and `egad_config.py` each
kept a private copy resolving at the context, so fixing `perms` alone would have
left the editor open: both now delegate, and their private role sets are gone.
Two tests added — `require_manager` refuses a clerk carrying a local Owner, and no
module keeps a private copy — and each is killed by its mutation. A manager
still reaches every gated page (smoke test: 200 across the gated views).
`pfas-logbook-custom` and `pfas-logbook-macros` return 500 as admin **at HEAD
without this change too**: a LocationError without parameters and a macro
provider that is not callable. Not a regression.

**Five more role checks resolve at the context and were left:**
`qcrules._check_manager`, `setuprefs._is_manager`, `calibrations._is_manager`,
`run_builder._is_manager`, `data_review._is_manager` / `_is_analyst`. None
includes `Owner`, so they are open only to a LOCAL Manager/LabManager/Analyst
grant, and nothing in this add-on makes one (`manage_setLocalRoles` appears
nowhere). Lower risk, same shape; consolidating them onto `perms` is the tidy
next step. `data_review._is_analyst` must be checked for any intended reliance
on a worksheet-local role before it is moved.

### 46.7 Controls a user cannot use are no longer drawn — and the key is no longer shown

`perms.GateMixin` gives a gated view `can_configure()` / `can_site_admin()` for
its template; the server-side gate stays authoritative. Hidden from those who
would be refused: Facility Units' API-key card (site_admin), unit edit/
deactivate, the add/edit form and Facility Defaults; the Weight Sets form;
Import Studio's upload, save-profile, retire/reactivate and edit links; the
reagent Expiry Defaults and Purge button. Each hidden block is replaced by one
line saying who does it. Prepared-standard and weight-set delete have no control
in the UI, so there was nothing to hide.

**The sensor API key was rendered into Facility Units for anyone who could view
it.** §46's gate stopped a bench user CHANGING the key, not READING it — and
reading is enough to post readings. `api_key()` now returns nothing to a user who
may not set it, so no template change can reintroduce the leak.

Live, rendered per role (all 200):

    page / control           LabClerk  LabManager  Manager
    units: api key card      hidden    hidden      shown
    units: defaults, form    hidden    shown       shown
    weight-set form          hidden    shown       shown
    studio upload            hidden    shown       shown
    reagents expiry defaults hidden    shown       shown

### 46.8 Every role lookup is now at the portal

The five checks §46.6 left — `qcrules._check_manager`, `setuprefs._is_manager`,
`calibrations._is_manager`, `run_builder._is_manager`, `data_review._is_manager`
/ `_is_analyst` — delegate to `perms.has_role_at_portal` with their own sets
unchanged (`MANAGER_ROLES`, `ANALYST_ROLES`; neither has Owner). Checked first
that nothing relied on a local grant: **SENAITE core only ever grants `Owner`
locally** — to a contact on their own object, and to each client's group on
the client folder (`bika/lims/content/client.py:273`). So moving these to the
portal changes WHERE roles are resolved, never WHO passes.

That last reference sharpens §46.6: **before these fixes a CLIENT user could
reach the QC-criteria editor through their own client folder**, not only a
bench chemist through a reagent. Not probed with a client account; the mechanism
is the one proven live.

`tests/test_action_gates.py` now scans the whole add-on: any `getRolesInContext`
call whose argument is not `portal` fails. It also pins every hidden control to
its enclosing condition — by parsing the templates, comments stripped (§45.7) —
and that `api_key()` refuses first. 12 mutations, all killed. Smoke: the moved
modules' pages render for clerk and manager; `@@pfas-qc-rules` still 403s a
clerk and redirects a manager to the unified console, as before.

### Still open

- Nothing further on authorisation beyond the `Owner` question below.
- ~~**Does Zope's `Owner` belong in either tier at all?**~~ Kept — §48.3. CLAUDE.md §4's business
  "Owner" maps to SENAITE `LabManager`; Zope's `Owner` is the creator-of-object
  role. Its presence in `ALLOWED_ROLES` looks like a name collision, not a
  decision. With portal anchoring it only matters for whoever owns the portal.
- ~~The refused buttons are still visible.~~ Done — §46.7.
- ~~`deviations.can_manage` omits `Owner`.~~ Delegates to `perms` — §48.3.
- Everything else in §45's list is unchanged.

---

## 47. Every restart re-ran the installer, and it reverted the lab's edits (2026-09-29)

§45 said "never re-run the GenericSetup profile on this instance". It had been
re-run **325 times**. The container entrypoint runs `buildout -c custom.cfg` on
every start, and `custom.cfg` enables `collective.recipe.plonesite` with
`senaite.pfas:default`; `portal_setup` holds one `import-all-profile-
senaite.pfas_default-*.log` per restart, the latest from the restart that
verified this fix. §22.3 had seen exactly this for `method_profiles.json`; nobody
had asked what else the same re-run did.

### 47.1 Proven, then fixed

`setup_handler` found each seeded object by Title and then wrote the CSV value
onto it regardless. Live, before the fix: a Method description tagged in setup
came back as the CSV text after one restart. So **any edit made in SENAITE setup
to a seeded Method's ID or description, a seeded service's precision or
category, or a seeded sample type's retention or hazardous flag has been
silently reverted at every restart** — including the restarts CLAUDE.md's own
workflow requires after a template change. All live values equal their seeds
today, consistent with that and with nobody having edited them.

`_get_or_create` now returns `(obj, created)`, and every seed setter sits under
`if created:`. The service-category collapse, which had been a one-time
migration re-applied at each start, is done and no longer repeats.

Live, after the fix — one field on each code path tagged, restart, read back
(and the profile confirmed re-run by a new import log):

    field                                  tagged    after restart
    Method description (FDA 32-PFAS)       +PROBE    +PROBE
    SampleType retention (first seeded)    4242 d    4242 d
    AnalysisService precision (first)      7         7
    Built-in logbook 251 sort_order        4242      4242

All four restored afterwards; the seed comparison is back to 0 differences.

### 47.2 The logbook seeder reverted the editor, and hid an editor defect

`seed_builtin_logbook_defs` re-wrote `sort_order`, `active`, `logbook_code` and
`method_slug` on the four built-in definitions each start — all four are on the
editor's form, so a manager who deactivated or re-ordered a built-in logbook had
it undone. It now re-stamps only the `builtin` identity and fills an empty field
schema.

The re-stamp had been covering for a real defect: the editor read `builtin`
from the form, **which never sends it**, so every save of a built-in logbook
cleared the flag and lifted its protection from hard delete until the next
restart. The editor now keeps the prior value on edit; a new definition is never
built in.

### 47.3 The Reference Definition path never ran

`create_reference_definitions` unpacked `QC_REF_SPEC`'s 5-tuples as 3, raised on
the first row, and `setup_handler`'s `try` logged it as a warning — every
restart. The accidental upside is that no Reference Definition was ever
overwritten. Fixed arity, and now create-only: an existing definition is skipped
(`@@pfas-setup-references` maintains them). All 11 codes already exist (13
definitions live), so this changes nothing on this instance; it matters on a
fresh one.

### 47.4 Every seeder, audited

| Seeder (runs every restart) | On existing data | Evidence |
|---|---|---|
| `setup_handler` CSV setters | **overwrote** — fixed | live tag reverted, then survived |
| `create_reference_definitions` | never ran — fixed, create-only | unpack arity |
| `seed_builtin_logbook_defs` | **overwrote 4 editor fields** — fixed | `prep_logbooks.py` + form fields |
| `seed_default_profiles` | fills missing ids; **re-exports the JSON** | §22.3; md5 unchanged across 4 restarts today |
| `egad_store.seed_defaults` | fills only (`if key not in store`) | code |
| `migrate_state_profile_vocab` | fills missing vocab keys only | code |
| `logbook_store.seed_defaults` | fills only | code |
| `seed_vendor_templates` | fills only | code |
| `link_method_analytes` | additive from the profile's own analyte set | code |
| `setup_automation_group`, `setup_*_catalog`, `migrate_*_from_annotations` | create-if-missing / migrate-if-present | code |
| `_stamp_pfas_role` | re-stamps an identity annotation, not editable | code |

A new seeder must be added to this table, must fill only, and must match on a
stable key where the type has one (§48.1).

**Trade-off, recorded in DECISIONS:** a correction to the CSV seeds no longer
reaches objects that already exist. It needs an explicit upgrade step.

### 47.5 Tests

`tests/test_installer_idempotence.py`, static: no `set*` on a get-or-created
object outside `if created:`; `_get_or_create` returns `(obj, created)`; the
Reference Definition loop's arity matches `QC_REF_SPEC` and skips existing; the
logbook seeder writes no field the editor's form carries; the editor never reads
`builtin` from the form. 7 mutations, all killed. 37/37 test files.

### Still open

- ~~**Title is the match key.**~~ Stable key first — §48.1. A seeded Method, service or sample type the lab
  RENAMES is not found at the next restart, and a fresh copy is created from the
  seed. Both extra sample types today (`FDA 32-PFAS in Food LFSM` / `LFSMD`) are
  lab-added, not re-creations, so it has not happened yet. Matching on a stable
  key (MethodID, Keyword, Prefix) is a design decision — asked.
- ~~**Whether the profile should re-run at start at all.**~~ Keeps re-running — §48.2. Stopping it would also
  stop `post_install`'s migrations, which then need proper upgrade steps. Asked,
  not changed.
- `seed_default_profiles` still re-exports `method_profiles.json` from ZODB on
  every start (§22.3); harmless while the file is only ever written through the
  store, which is the rule.


---

## 48. Seeds are found by their key; Owner stays, in one place; §5 rewritten (2026-09-29)

The lab answered the three questions §46 and §47 left open. Decisions are
recorded in DECISIONS.md; this section covers what changed and how it was proven.

### 48.1 A renamed seed is found, not re-seeded

`_get_or_create` takes an optional `key=(accessor, value)` and matches it
before Title: Method → `getMethodID`, AnalysisService → `getKeyword` (both
calls), SampleType → `getPrefix`. Title is the fallback only when **no** object
carries the key, and it refuses a Title match whose key is set to something
else. That matters because not everything is under `if created:`:
`_stamp_pfas_role` stamps whatever object is returned, so a loose fallback would
decide which service gets a PFAS role. If two objects share a key, the one whose
Title matches wins and a warning is logged.

**Live, before:** 3 Methods, 16 sample types, 74 services. None of the three
types has a duplicate key, and every seeded object carries its key, so this
selects exactly the same objects as Title did.

**Live, after:** `method-2` retitled `… PROBE48`, then a restart. Import log 328
confirms the profile re-ran. Result: still 3 Methods, the rename survived, and
16 / 74 unchanged. The title was then restored. The pre-fix bug was deliberately
**not** reproduced live: it would have created a second Method with
`MethodID=EPA_537_1`, and the cal-code lookup keys on that.

**Renames are now safe for the installer, not for everything.** Other code
still matches on Title:
- **Sample type titles are the matrix vocabulary** in `method_profile_store`
  (`_FDA_MATRICES`, `_EPA537_MATRICES`, the unit map) and in
  `egad_store._DEFAULT_MATRIX_MAP`. Renaming a sample type in SENAITE setup
  detaches it from the method × matrix panel. This is CLAUDE.md §3 rule 4
  (referential integrity on rename), and it is open.
- `method_bridge.get_core_method` uses the stored UID first. Its Title fallback
  is only reached before backfill, and all three associations have a UID.
- `method_wizard` looks for an existing Method by Title, so it can create a
  second Method with a MethodID that already exists. Open.

### 48.2 The profile keeps re-running

Kept, as the lab decided. The guard is `test_installer_idempotence.py`, which
already existed from §47. Its contract (§47.4) now also requires a new seeder to
match on a stable key where the type has one.

### 48.3 Owner stays; deviations delegates

`deviations.can_manage` used its own `{LabManager, Manager}`. It now calls
`has_role_at_portal(self.context, ALLOWED_ROLES)`. It had already resolved roles
at the portal, so adding Owner cannot reach a deviation's creator. Checked live
with throwaway users in an **aborted** transaction (none left behind):

    user        roles at portal          can_manage
    t48clerk    LabClerk                 False
    t48owner    LabClerk + Owner@portal  True
    t48mgr      LabManager               True

One behaviour change: the old check fell back to `user.getRoles()` if it could
not resolve the portal. The shared check denies instead, as every other gate
does.

### 48.4 CLAUDE.md §5

§5 now describes the three landings `@@pfas-home` actually routes to (QC
Management, Data Review, Bench) plus Client Tracker, and lists the rest as §6A
sidebar groups. §9's "which workspace?" is reworded to "which sidebar group, and
is it a tile on a landing?". The Data Review text now also says the release
cascades to the analyses (§5 G1). Before, it said the worksheet transitions
directly, which had never worked.

### 48.5 Tests

- `test_installer_idempotence.py`, 12 tests:
  - a static AST check that each keyed call passes the right accessor;
  - six behavioural tests that run the **real** `_get_or_create`, extracted
    from source with `bika.lims.api` stubbed, against a fake folder.
  - Six mutations, all killed: dropped key, wrong accessor, key ignored,
    fallback adopts a mismatched key, no Title preference on a shared key, no
    Title fallback.
- `test_action_gates.py`: `can_manage` must delegate with `ALLOWED_ROLES` and
  hold no private role list. Two mutations, both killed.

**37/37 test files, but only with `PFAS_PROFILES_PATH` set.**
`test_fault_injection`, `test_profiles`, `test_salt_correction` and
`test_unconfigured_criteria` fail on a bare host, both at `fcd142b` and now.
Without the variable, `pfas_pipeline.method_profiles` falls back to
`/data/qc/method_profiles.json`, which exists only in the containers, and then
to built-in defaults.

Run the suite as:

    PFAS_PROFILES_PATH=$PWD/data/qc/method_profiles.json python3 tests/test_X.py

`data/` is gitignored, so **a fresh clone cannot pass these four**. They test
lab data, not code. Recorded, not changed.

### Still open

- Sample type rename breaks the matrix vocabulary (48.1). Needs a stable
  matrix key (the Prefix), which is a data-model change → plan first (§8).
- `method_wizard` Title match can duplicate a MethodID (48.1).
- Four test files depend on gitignored lab data (48.5).
- Vocabularies code-only / Phase 6, unchanged from §45.
- ~~**§4 and §5 disagree on a Bench Chemist holding `Analyst`.**~~ LabClerk only — DECISIONS 2026-09-30; §4 corrected. §4 maps Bench
  Chemist to SENAITE `Analyst / LabClerk`, landing on Bench; the launcher tests
  `Analyst` before `LabClerk`, so such a user lands on Data Review. Pre-existing
  in §4 vs `workspace_home.py`; the §5 rewrite follows the code. Which role a
  bench chemist holds is the lab's call — asked.
- Second restart after the commit: import log 329, 3 / 16 / 74 unchanged — the
  web process now serves this code. `@@pfas-deviations` not yet looked at in a
  browser.

---

## 49. The UI audit: one shared layout, used by almost nothing (2026-09-30)

The lab reported that the site felt cluttered and scattered, and asked for a
review before any more features. `tools/ui_audit.py` (new) logs in, walks every
sidebar link plus the pages the sidebar does not reach (the role landings, the
editors, one level of deep links), screenshots each at 1440×900, and measures
the geometry that should be identical everywhere. **60 pages.**

### 49.1 What was measured

- **The sidebar moves.** Core pages: first row at y=60, row pitch 33px. PFAS
  pages: y=52, 29px. `pfas_sidebar.pt` sets no line-height, so each host page's
  line-height decides it (1.5 on core, tighter on PFAS).
- **About ten content frames.** Real left edges (widest visible block) at
  242, 250, 259, 262, 266, 300, 350, 526 and 580px, widths 500–1176. The two
  big clusters:
  - 17 pages at x=300, width 1060: they use the macro's
    `.page-body {max-width:1100px; margin:auto; padding:20px}` *on top of*
    `.pfas-content-area`'s own 22px gutter;
  - 11 pages at x=242, width 1176: they fill the slot directly.
  - Core pages sit at x=250.
- **Two title patterns.** Core pages: breadcrumb plus an in-page H1 with an
  icon. PFAS pages: the title only in the dark header bar.
- **The shared components are barely used.** In screen templates,
  `.pfas-tabs` appears on 2 pages, `.pfas-table` on 7 and `.pfas-action-bar` on
  2. Pages instead define 63 button classes, 34 table classes, 86 card/panel
  classes and 121 badge/status classes of their own. 51 screen templates carry
  a page-local `<style>` (3,332 lines), with 968 `style=` attributes,
  223 distinct hex colours against 22 tokens, and 23 font sizes (9–36px).
  Print templates (certificates, labels, receipts) are excluded: their pt
  sizes are deliberate.
- **Navigation.** 44 sidebar links in 7 groups, all expanded, so the list runs
  past the fold. **The three role landings (§5) are not in the sidebar**; the
  only way in is a "PFAS Workspace" tile on the SENAITE dashboard. Accordions on
  five pages, tabs on one (§6B asks for tabs).

### 49.2 Phase 0 — defects fixed, ratchet added

- **All three role landings rendered unstyled** (serif fallback, a stray title
  line above the header). Cause: the macro defines the `title` slot on the
  `<title>` element itself, and `pfas_qc_management`, `pfas_bench`,
  `pfas_data_review_home` and `qc_grid` filled it with a bare
  `<metal:fill>`. That replaced the `<title>` tag with loose text, so the
  browser closed `<head>` early and the page's styles landed inside a `<p>` in
  `<body>`. It was not the missing `xmlns`, which was the first suspect.
  **Fixed** on all four. Verified after a restart: correct title, system font.
- **The method profile editor's 11 tabs ran off the right edge** under
  `overflow-x:auto` with no scroll cue, so "Lab Workflow" and "Advanced" could
  not be seen. `.pfas-tabs` now wraps on desktop and still scrolls on phones.
  Verified: two rows, all 11 visible.
- **The Data Review queue showed the worksheet ID twice** (Worksheet and Title
  columns; a worksheet's Title is its ID). The Title column is gone; a title
  that differs from the ID is shown under it.
- **`tests/test_ui_ratchet.py`** pins the four counts above at their current
  values (51 / 968 / 223 / 23), so page-local styling can only shrink, and
  requires the title slot to be filled on a `<title>` element. Four mutations,
  all killed. The first version of the title check survived its own mutation:
  it required the `metal:` prefix, which the broken form does not carry.

38/38 test files (with `PFAS_PROFILES_PATH`, §48.5).

### 49.3 Decisions and remaining phases

Decisions are recorded in DECISIONS 2026-09-30 and CLAUDE.md §6C: title in the
header bar with a breadcrumb; full width for lists and one shared narrow width
for forms; the sidebar opens on the role's landing and groups.

1. **Frame and tokens.** Fixed sidebar line-height/pitch; `.page-body` becomes
   full width on the shared gutter; `.page-body-narrow` is the one form width,
   left-aligned so the left edge never moves; spacing, type and radius tokens.
2. **Components.** One button set, one table, one badge scale and one card,
   migrated a sidebar group at a time, deleting page CSS and lowering the
   ratchet ceilings in the same commit.
3. **Navigation.** Landing pinned atop the sidebar; role and current groups
   open, the rest collapsed and remembered.
4. **Accordions → tabs** on the five remaining pages.
5. **Not yet addressed.** `@@pfas-calibrations` is 8,500px tall.
