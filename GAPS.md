# Gap register — senaite.pfas

What is verified, what is broken, and what is configured but never exercised.
Every entry here was established by running the code or querying the running
instance, not by reading it.

Re-verify with:

```bash
export PFAS_PROFILES_PATH="$PWD/data/qc/method_profiles.json"
export PFAS_ALLOW_LEGACY_VENDOR_MAP=1
for t in tests/*.py; do python3 "$t"; done
python3 tools/audit_configurable.py --profiles data/qc/method_profiles.json
python3 tools/generate_synthetic_runs.py --out /tmp/synth --list
```

Last updated: 2026-08-06.

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

- **`EPA_537_1.surrogate_map` is empty** and `surrogate_is_chain` is absent on
  both EPA methods. `qc_qualification.analytes_for_failure` therefore degrades
  to the labelled compound instead of the natives it quantifies — a certificate
  would name a compound the client never sees.
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
| `qc/control_chart.py` is entirely dead | ~700 lines, zero callers | Westgard rules, control limits, chart build, PNG render. `browser/controlchart.py` reimplements it inline. Neither is tested. |
| `calculate_mdl`, `single_transition_confirm_needed` | `qc_engine.py` | Zero call sites; the latter's docstring claims the run queue uses it. |
| `lfsm_check` / `lfsmd_check` | `qc_engine.py` | Re-implemented inline in `run_queue`. |
| `QCResultStore.add_results_bulk` / `add_result` / `flag_for_reanalysis` / `void_batch` | `qc/store.py` | Zero external callers; the Py3 pipeline writes raw SQL. So `voided`, `flagged_reanalysis` and `superseded` are read by Data Review and never produced. |
| `sn_min` toggle defaults **OFF** | `qc/rules.py:90,95` | Signal-to-noise is not evaluated for FDA_32PFAS or EPA_537_1. |
| `ccv_frequency`, `mdl_check` toggles | `RULE_LIBRARY` | Honoured nowhere. |
| `lfsm_recovery`, `lfsmd_rpd` toggles | read by `run_queue` | **Absent from `RULE_LIBRARY`** — no UI can set them. |
| `qq_ratio_*_pct` (three knobs) | `RULE_LIBRARY` | `qual_quan_check` reads one flat value. `sn_quan_min` is mapped onto `sn_min`, substituting the quantitation threshold for the detection one. |
| Facility QC: eyewash dashboard reads the wrong table | `facility_qc.py:707` | Its computed `passed` never surfaces; waste units always show green. |
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
