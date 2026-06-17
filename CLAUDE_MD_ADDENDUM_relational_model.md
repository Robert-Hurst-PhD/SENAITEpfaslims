## 9. THE RELATIONAL DATA MODEL (read this before touching any module)

> Added after repeated drift where features were built "floating" — operating
> on free-typed values or their own private lists instead of on defined
> relationships. A LIMS IS a relational database with a UI on top. Every
> feature in this project must be a VIEW onto the relational hierarchy below,
> never a standalone island. If you are about to store a value or a mapping
> that duplicates something another object already owns, STOP — reference the
> owning object instead.

### 9.1 The hierarchy (parentage flows top-down; you populate in this order)

```
LABORATORY
  └─ METHOD              (FDA 32-PFAS / EPA 537.1 / EPA 1633A)
       ├─ supports one or more MATRICES   (eggs, meat, seafood, milk, feed,
       │                                    drinking water, soil, tissue, ...)
       ├─ owns a MASTER ANALYTE SET        (natives + surrogates + internal
       │                                    standards chosen from the library)
       │
       ├─ METHOD × MATRIX ANALYTE INCLUSION MATRIX   ◄── THE KEY RELATION
       │     analytes as rows, the method's matrices as columns, a checkbox at
       │     each intersection. An analyte "in the method" is NOT automatically
       │     reportable in every matrix. Example: under FDA, PFODA is NOT
       │     reportable in eggs but IS in meat. The reportable panel is the
       │     SET OF CHECKED INTERSECTIONS for a given Method × Matrix.
       │
       ├─ SURROGATE MAP        native analyte → its quantifying IS/surrogate
       │                        (many natives may map to one IS). Operates ONLY
       │                        on this method's analyte set.
       ├─ RECOVERY TIERS       per analyte, and for FDA the tier is itself
       │                        MATRIX-DEPENDENT (80–120% big-four in
       │                        egg/meat/seafood; 65–135% elsewhere; 40–140%
       │                        no-labeled-std). Relation: Method → Analyte →
       │                        (matrix-conditional) tier.
       ├─ EIS RECOVERY LIMITS  EPA 1633A ONLY. Hidden for FDA/537.1. Per
       │                        analyte (sometimes per matrix). Distinct from
       │                        the surrogate map: surrogate map = QUANTIFICATION
       │                        link; EIS limits = RECOVERY-QC limits.
       ├─ SALT FACTOR          per analyte × method (decimal < 1).
       ├─ MATRIX ADJUSTMENT    ONE factor per method (sample-size correction).
       ├─ ISOMER SUMMATION     lr+br → reported analyte, toggle per analyte ×
       │                        method.
       ├─ QC RULESET           which rules on/off + limits, per method.
       ├─ UNIT MAP             method × matrix → reporting unit.
       ├─ CAS MAP              analyte → CAS / Maine DEP code (for EDD).
       └─ LOGBOOK TEMPLATES    owned by the method; instantiated per batch.

  BATCH
    ├─ belongs to ONE METHOD and ONE MATRIX
    ├─ inherits that Method × Matrix analyte panel, QC rules, factors, units
    ├─ instantiates the method's LOGBOOK TEMPLATES as concrete logbooks
    │   (each with a unique ID that references the batch + method)
    ├─ contains SAMPLES (field samples + QC: MB, LFSM, LFSMD, Dup, LCS)
    └─ produces RESULTS + QC RESULTS (each result references its analyte,
        which references its method/matrix parentage)

  REPORT
    └─ assembled from a BATCH → carries full parentage at every line:
        result → analyte → method × matrix → batch → samples → QC → logbooks
        → factors/qualifiers applied. Optional EDD export reads results + CAS
        map + qualifier map; BLOCKS if any analyte in the batch lacks a CAS.
```

### 9.2 Rules that follow from the hierarchy (enforce these)

1. **Single source of truth.** Analyte identities, IS links, method criteria,
   CAS codes, units — each is defined ONCE on its owning object and REFERENCED
   everywhere else. No feature keeps its own private copy or free-typed value.

2. **Populate in order; enforce prerequisites.** You cannot define a surrogate
   map before the method's analyte set exists; cannot build a batch before its
   Method × Matrix panel exists; cannot export an EDD before every analyte has
   a CAS code. The UI must reflect and enforce this order (the new-method
   wizard walks it).

3. **Every report line must trace its parentage.** A result must be able to
   answer: which analyte, under which method × matrix, in which batch, with
   which surrogate/IS, which recovery tier, which factors and qualifiers
   applied. If a value can't name its parent, the model is wrong.

4. **Method × Matrix scoping is mandatory.** Any tool that lists analytes
   (surrogate map, recovery tiers, QC, report, EDD) must list the analytes
   valid for THAT method × matrix intersection — never a flat global list.
   PFODA must not appear for FDA × eggs.

5. **Method-conditional features.** EIS overrides appear only for 1633A.
   FDA's matrix-dependent recovery tiers appear only for FDA. Do not show a
   method criteria field that the method doesn't use.

6. **Referential integrity.** Deleting/renaming an analyte, IS, method, or
   matrix must surface what references it — never leave orphaned mappings or
   results pointing at nothing.

### 9.3 When building or fixing ANY module, ask first:

- What object OWNS this data in the hierarchy above?
- Am I referencing the owner, or duplicating its data? (Duplication = defect.)
- Does this list of analytes respect the Method × Matrix panel?
- Can every value I produce name its full parentage up the tree?
- If this is a criterion, is it correctly scoped to the method that uses it?

If a requested change can't be expressed as a view onto this hierarchy, STOP
and raise it with the lab before building — it may indicate the model needs a
new relationship, which is a decision to make explicitly, not to paper over.
