# Why the model is shaped this way — ISO 17025 design rationale

`CLAUDE.md` states the law. `DECISIONS.md` records what happened, in order.
This document is the layer in between: for each accreditation obligation, what
the data model must therefore own, the shape of defect that violates it, how
that defect was actually caught, and the code that now prevents it.

Anchors below name **symbols, not line numbers** — deliberately. Line numbers
in `method_profiles.py` moved three times while this work was in progress, and
a reference doc with stale anchors teaches readers not to trust it.

It exists because the obligations in CLAUDE.md §10 are stated but not derived.
A reader who knows *that* reagent traceability is required still cannot tell,
from the rule alone, why `salt_adjustment_factors` living in the Method Profile
rather than the QC rulebook is a compliance decision and not a filing
preference. Every entry below is a real defect found in this system, not an
illustration.

**Read the shape, not just the instance.** Ten separate defects in this system
have had one shape: *a fact recorded correctly in one place and never carried
to where it is used.* The instances differ — a dilution relationship, an
analyte alias, a salt factor, a surrogate map — and the fix is always the same:
find the consumer, or delete the record. `tools/audit_configurable.py` exists
to find the eleventh mechanically.

---

## 1. §6.6 — Reagent and reference-standard traceability

**Obligation.** Every result traces to the reference standards and reagents
behind it: reagent lot → prepared-standard lot → analysis result, each link
explicit rather than inferred. An expired CRM invalidates the standards made
from it, and therefore the results.

**What the model must own.** The correction a reference standard implies is
part of the *method*, not of the QC rulebook. A salt-form standard reads high
by the mass of its counter-ion; the correction is a property of the analyte ×
method and of the specific CoA lot it came from.

**The defect shape.** Recorded in one place, never carried to the consumer.
Salt adjustment was editable in **two** user interfaces and stored under
**three** keys — `salt_adjustment_factors` (Method Profile editor, complete
with the CoA lot per analyte, which is exactly the traceability §6.6 asks for),
`qc_rules.salt_factors` (QC Rules page), and a seeded empty
`extraction_corrections.salt_factors`. It was applied by none of them. The
string `salt` appeared nowhere in `pfas_pipeline/` except a shelf-life table.
D53 had correctly deprecated the QC-engine copy on the grounds that this is a
core per-method sample correction; the replacement was never wired.

**How it was caught.** Not by reading the code — it looks alive from every
angle: a form, a saved value, the value redisplayed. It was caught by asking a
question static analysis can answer: *does anything other than this editor read
this key?* That is the UI-ONLY check in `tools/audit_configurable.py`.

**Cost.** FDA_32PFAS carries 0.9636 for PFOA against lot MXA-2453-A. Every PFOA
result issued before 2026-08-03 was 3.6% high.

**Where it is enforced.** `pfas_pipeline/pipeline.apply_extract_corrections()` — one named function, because "which corrections
were applied, in what order" is a question a reviewer asks of every result and
it should have exactly one answer to read. Factors resolve through
`method_profiles.get_salt_factors()` and expand to isomer components,
because `lr-`/`br-` rows come from the same salt-form standard as the analyte
they sum to.

---

## 2. §7.8.4 — Technical review, and whose document a finding belongs on

**Obligation.** Report issuance requires a documented technical review. The
review is a distinct activity with a distinct audience: the reviewer and the
auditor, not the client.

**What the model must own.** A reviewer finding and a client-reportable
qualifier are different kinds of fact and must not share a field. `BLoQ` and
`< LOD` belong on the certificate; "the method profile named a different
surrogate than the instrument used" does not.

**The defect shape.** Right fact, wrong surface. The surrogate-map mismatch was
appended to `SummaryResult.flags` — which reads naturally until you follow it:
`SummaryResult.display()` folds `flags` into the reported value string
(`10.6 (BLoQ; SUR)`), and `senaite_connector.py` pushes them to Analysis
**Remarks**. Both reach the client certificate. Zero occurrences existed, so
nothing leaked; the exposure was latent and would have surfaced on the first
genuine disagreement.

**How it was caught.** By review, not by testing. No test failed, because the
fixture had no mismatch. The question that found it was structural: *which
fields on this object are client-visible?*

**Where it is enforced.** `pfas_pipeline/models.SummaryResult.is_mismatch`, a field the QC Review Report reads, plus a
`QCFlag` so the finding reaches Data Review through the same channel as every
other reviewer finding. `tests/test_surrogate_map.py` asserts it never reaches
`flags`.

**The general rule.** The QC Review Report exists precisely because reviewer
findings do not belong on the client document. Before adding a field to a
result, establish which document renders it.

---

## 3. QC acceptance as a hard release gate

**Obligation.** Method blank, LCS, LFSM/LFSMD and IS recovery are pass/fail,
not informational. A failing result means the batch cannot be released without
a documented exception.

**What the model must own.** The criterion itself. A gate that judges against a
limit nobody configured is not a gate.

**The defect shape.** Silent substitution. The FDA tier resolver ended with an
unconditional `QCRule(65.0, 135.0, rsd_max=25.0)` and carried ~59 inline
fallbacks of the form `tier.get("recovery_min", 40.0)`. When the profile was
silent, the code supplied a plausible limit and said nothing.

This is the CCV defect **inverted**. In the CCV case the editor displayed and
saved 72–128% while runs were judged against a nested 70–130% — a wrong number,
visible to anyone who compared them. Here the number never appears at all: a
result is measured against a criterion no one chose, and it *passes*. A wrong
result draws scrutiny; a passing result never does. That asymmetry is why this
was worth hard-blocking over.

**Where it is enforced.** `pfas_pipeline/method_profiles.UnconfiguredCriterion`, raised from
`_tier_rule()`, `_ccv_rule()`, and the 1633A and 537.1 paths. The legacy `recovery_tiers` branch — a
second, divergent copy of the tier logic — was deleted with it, because a
fallback copy can only ever mask the absence it is compensating for.

### 3a. The two corrections, and the rule they produced

Getting the refusal right took two wrong attempts, and both are instructive
because both were *reasonable*:

1. Demanding `recovery_min`/`recovery_max` everywhere refused a correctly
   configured **Dup** tier — a duplicate is judged by **RPD**, and has no
   recovery window by design.
2. Accepting any of recovery/RSD/RPD then refused every **method blank** —
   an MB is judged by `max_conc_x_rl`, contamination against the reporting
   limit.

Each fix was an enumeration, and each enumeration was incomplete in a way I
could not see from inside it. The rule that finally held:

> **"Configured" is the absence of nothing, not the presence of one of a list
> you thought of.**

A tier counts as configured when it carries any key beyond the structural ones
(`_TIER_STRUCTURAL_KEYS`) — name, analyte group, matrix scope. A
criterion type added next year does not silently start refusing.

This generalises past QC: whenever you are about to write "valid if it has one
of A, B, or C", ask whether you can instead write "valid unless it has nothing
at all." The second form survives extension; the first fails closed on
precisely the cases nobody anticipated.

### 3b. Where refusal is right, and where it is wrong

This call was made three times with two different answers, and the discriminator
is not obvious:

| Situation | Answer | Why |
|---|---|---|
| Tier carries no criterion | **Refuse** | Nobody decided. A gate against an unchosen limit is not a gate. |
| Rename orphans matrix-keyed data | **Refuse** | Nobody decided that the data is disposable. |
| FDA §2024.10.1(5) surrogate 50–150% | **Keep, cite, allow override** | The *method* decided. §8 forbids fabricating a regulatory value — and a cited value is not a fabrication. |
| EPA 537.1 §9.3.5 surrogate 70–130% | **Keep, cite, allow override** | Same. |

> **Refuse when nobody decided. Keep-and-cite when the method decided and the
> lab has not overridden it.**

The published limits were never the problem. The problem was that they could
not be overridden, so a lab whose SOP is tighter than the method floor had
nowhere to say so. `qc_acceptance.SUR` now wins when configured
(`_method_text_rule`); the cited value stands otherwise.

Without this distinction the next person applies refuse-to-judge to the
published limits and breaks every 537.1 run.

### 3c. The eleventh instance — found while deleting the wrong thing

`recovery_tiers` was reported as UI-ONLY and looked like migration residue: a
retired key with an editor still attached. The agreed action was to delete the
field. Reading the JavaScript first showed the Recovery Tiers **grid** is driven
by it — and that the live value is `[]`, so **the tab rendered empty** while
80–120 / 65–135 / 40–140 sat in `qc_acceptance.LFSM.tiers`. Any tier a manager
added there was written to a key nothing reads.

So it was not residue. It was the CCV defect again, in the one editor where it
matters most: the recovery window is the pass/fail gate on a certificate. The
grid now reads and writes `qc_acceptance.{qc_type}.tiers`, verified end to end —
UI edit → enforced structure → engine verdict (120 → 118 → reverted).

**Two lessons, both about method rather than PFAS:**

- *A finding's classification is a hypothesis.* "Residue" and "disconnected
  editor" look identical from the audit output and call for opposite actions.
  The distinguishing evidence was one file the audit does not read.
- *Deleting is not the safe default.* Removing the field would have destroyed a
  UI that should exist, and the resulting profile would have looked correct.
  Before removing something that appears dead, establish what would have to be
  true for it to be alive, then check that.

---

## 3d. §8 — Migrate configured data, do not merely define the schema

**Obligation.** When the model changes, existing configured data moves into the
new structure without loss. A lab's limits are its own; a schema change is not
permission to reset them.

**Three defects in one script**, `migrate_profile_structure.py`, found while
closing out the `duplicate` key:

1. **It listed `salt_adjustment_factors` as obsolete.** That key is
   authoritative — applied since 2026-08-03, and it carries the CoA lot behind
   every factor. Running the migration would have deleted a lab's salt
   corrections *and* their §6.6 traceability. The `UnconfiguredCriterion`
   message points users straight at this script, so the instruction to run it
   was itself the hazard.
2. **It deleted `duplicate` and `recovery_tiers` without carrying their
   values.** A profile configured only on the flat key was silently reset to
   the seed.
3. **It operated on the wrong store.** Live profiles are Dexterity objects
   under `/senaite/pfas_method_profiles`; the migration read the legacy
   annotation mapping. It cleaned a stale copy, printed "saved", and left every
   real profile untouched. The annotation store held `salt=0` while the live
   store held `salt=2`.

The third is the interesting one. `get_profile_store()`'s own docstring says
*"use get_profile() / save_profile() for all live read/write"*, and the sibling
migration `backfill_matrix_uid_map.py` does exactly that. **The correct pattern
already existed in the same directory.** This was not unknown territory — it
was inconsistency, which is harder to see precisely because nothing looks
wrong in the file you are reading.

**Where it is enforced.** `carry_legacy_values()` is extracted and named so the
step that decides whether a lab keeps its limits can be tested directly
(`tests/test_profile_migration.py`, including idempotence and never
overwriting a newer value). The migration now reads and writes through
`list_method_ids` / `get_profile` / `save_profile`.

**The same shape lived one layer down.** The annotation mapping the migration
had been reading was not merely unused — it was a divergent copy of live
config. Purging it reported FDA_32PFAS differing in 11 keys including the
acceptance limits, the matrix factor applied to every concentration, and the
reportable panel. The fallback that would have served it now raises
`StaleProfileStore`, and the distinction that keeps that safe is worth copying:
it fires only when the live store is missing AND a legacy copy exists. Written
as the obvious "no folder → raise", it would have broken every fresh install,
which has neither store and must fall through to defaults.

**Verify a migration against live data, not against its own output.** This one
printed a clean success report while doing nothing. What proved the fix was
reading the Dexterity objects before and after and confirming the salt factors
survived — not the script's summary line.

---

## 4. §3 rule 4 — Referential integrity on rename and delete

**Obligation.** Deleting or renaming an analyte, IS, method or matrix must
surface what references it — never leave orphaned maps, result rows or logbook
entries pointing at nothing. ZODB is an object store: no foreign key enforces
this, so it is the application's job.

**The defect shape.** Silent orphaning across a title-keyed join.
`matrix_factors`, `spike_levels` and `analyte_matrix_inclusion` are all keyed by
matrix **title**. The first version of the Matrices & Units editor pruned
`matrix_uid_map` and stopped — so renaming "Meat / Muscle" would have stranded
its matrix factor, the multiplier applied to every native concentration on the
certificate.

**Where it is enforced.** `src/senaite/pfas/browser/method_profiles._matrix_references()`; the save refuses and names what would be stranded:

> Removing or renaming Meat / Muscle would orphan matrix factors for
> Meat / Muscle; spike levels for Meat / Muscle; analyte × matrix inclusion for
> Meat / Muscle. Move or clear that data first, or restore the matrix name.

Deciding that lab data is disposable because a title changed is not a form's
call to make.

---

## 5. The method owns its own relations

**Obligation.** §3: the METHOD owns its master analyte set, its surrogate map,
its recovery tiers, its units. Two methods may disagree about the same
compound, and both may be right.

**The defect shape.** A global table quietly standing in for a per-method
relation. The Method Profile stored the surrogate map three ways —
`surrogate_map`, `surrogate_is`, `surrogate_is_chain` — and **the analysis read
none of them**. It took the surrogate/IS relationship from the instrument
file's own `linked_is` column, falling back to a global `analyte_reference`
table that is not method-scoped. §3's "SURROGATE MAP … drag-and-drop, never
JSON" was, as built, decorative.

**Why it mattered.** A surrogate is added before extraction and is diluted with
the sample; the injection standard is added at reconstitution, after any
dilution, and must not be scaled. Getting that backwards makes a dilution's
surrogates look like recovery failures — which is exactly what was observed,
and was diagnosed by hand as "a notation issue in the method profile which is
not being carried over to the analysis." The notation was not mis-transcribed.
The analysis had never consulted the profile for it.

**Two spelling gaps had to close first**, and they are worth recording because
both silently produced *plausible* output:

- The alias table was built by walking only `NATIVE_ANALYTES`, so nothing could
  tell that `M8PFOA` (profile) and `13C8-PFOA` (instrument) are one compound.
  Both spellings had been sitting in `INTERNAL_STANDARDS` all along.
- Comparing raw names therefore reported all 20 surrogates as disagreements —
  a mismatch detector that fires on everything is as useless as one that never
  fires, and rather more convincing.

**Where it is enforced.** `pfas_pipeline/pipeline._quantifying_is()`
(profile authoritative, instrument column and alias table as fallbacks,
disagreement flagged); `pfas_pipeline/qc_engine.is_raw_check()` (the method's `surrogate_is_chain`
decides which compound is the injection standard);
`method_profiles.get_surrogate_map()` keys both spellings.

---

## 6. What the audit tool can and cannot see

`tools/audit_configurable.py` reports DEAD, UNREACHABLE, UI-ONLY, SPLIT KEY and
hardcoded lab values. **A clean run is evidence, not proof.** Three limits are
structural, not bugs to fix later:

1. **Iterated containers credit their leaves as read.** Where the engine does
   `for key in qc_acceptance`, no literal-name scan can tell which leaves the
   loop body touches. The tool under-reports there rather than crying wolf —
   deliberately, because a noisy audit gets ignored and an ignored audit is
   worse than none.
2. **A self-contained feature is indistinguishable from an inert one.** The Run
   Builder both stores and consumes its own template, which looks exactly like
   dead config. UI-ONLY is a prompt to judge, never a verdict.
3. **It only sees what the profile JSON contains.** Keys a method has never
   been configured with are invisible.

Two false-positive classes cost a round trip each and will recur:

- Keying a file's identity on its **basename** collided
  `pfas_pipeline/method_profiles.py` with `browser/method_profiles.py` and
  wrote off the pipeline — the actual consumer — as "the editor reading itself
  back."
- Enumerating data-keyed containers **by name** produced 679 keys and 404 false
  DEAD entries, nearly all one `analyte × matrix` cell. The data-vs-schema test
  must be content-based, or it degrades as the lab adds analytes.

**Run it after any change to the profile schema**, and treat a new finding as
real until shown otherwise — including one you introduced yourself. Removing the
legacy `recovery_tiers` branch from the pipeline left the Method Profile editor
exposing a `recovery_tiers` field that nothing consumes, and the next audit run
reported it. That is the tool working.

```
python3 tools/audit_configurable.py --profiles data/qc/method_profiles.json
python3 tools/audit_configurable.py --profiles ... --format md > CONFIG_AUDIT.md
```

---

## 7. Verifying a change to any of the above

A criterion change is not verified by a passing test suite. The suite reads
`PFAS_PROFILES_PATH`, which **defaults to the container path** — without it the
tests silently exercise `_DEFAULT_PROFILE_CACHE`, which has no `tight_matrices`,
so tier 1 never resolves and the suite passes on defaults rather than on the
lab's profile.

Verify in both states, and sweep rather than sample:

```bash
export PFAS_PROFILES_PATH="$PWD/data/qc/method_profiles.json"
# and again with PFAS_PROFILES_PATH=/nonexistent for the fresh-container path
```

The refuse-to-judge change was swept across every analyte × matrix × QC-type
combination in all three methods — 4248 configured, 150 on defaults, 0 refused
in either. A sweep of the *configured* state alone would have proved nothing:
that is the state where nothing should refuse. The cost of a refusal lives
entirely in the unconfigured state, so that is the state that must be measured.

---

## Related

- `CLAUDE.md` §10 — the obligations, stated as law
- `DECISIONS.md` — the chronological record, including superseded decisions
- `CONFIG_AUDIT.md` — current audit output
- `E2E_TEST_2026-08-02.md`, `E2E_FIXES_2026-08-03.md` — the run that surfaced
  most of this
