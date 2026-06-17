# CLAUDE.md — senaite.pfas project context

> Claude Code reads this file automatically at the start of every session.
> It defines how this project must be built. Follow it over your own defaults.

---

## 0. The single most important principle

**Configurable, not hardcoded. UI-driven, not code-driven.**

The previous iteration of this project hardcoded PFAS QC values (recovery
limits, CCV frequency, r² thresholds, ion-ratio tolerances) directly into
Python modules. That is the #1 thing to fix. Every QC criterion a laboratory
manager might ever want to change MUST be editable through the SENAITE web
interface — never by editing source code.

When you find a hardcoded value that a manager, QA officer, director, or owner
would reasonably want to change, treat that as a defect to be migrated into
configuration, not as acceptable.

Default rule when unsure: **if a human in the lab might want to change it, it
belongs in the UI, not in the code.**

---

## 1. What this system is

A PFAS analytical laboratory LIMS built as an add-on (`senaite.pfas`) to
SENAITE LIMS, plus a loosely-coupled pipeline worker. It handles three
methods — FDA 32-PFAS in Food, EPA 537.1, EPA 1633A — each with different,
per-analyte and per-matrix QC criteria.

The lab runs SENAITE **2.6.0** (Plone/Zope, **Python 2.7** — this is a hard
constraint of the core; all in-Plone add-on code must be Python 2.7
compatible). The out-of-process pipeline worker may use Python 3.

Existing structure you must BUILD ON, not replace:
- `src/senaite/pfas/` — the Plone add-on (content types, setup data, handlers)
- `pfas_pipeline/` — the worker (QC engine, importer, report, injection builder)
- `src/senaite/pfas/setupdata/*.csv` — 34 analytes, 21 internal standards,
  3 methods, sample types, containers, storage locations (already populated)

Read `README.md` and `RESOURCE_MAP.md` before doing anything.

---

## 2. Architecture principles (non-negotiable)

1. **Expand SENAITE's existing machinery; don't reinvent it.**
   - QC criteria belong in SENAITE **Analysis Specifications** (min/max/warn
     per analyte per sample type) for simple ranges, PLUS a custom **Method
     Profile control panel** in Site Setup for method-specific logic that
     specs can't express (three-tier recovery, CCV frequency, RRT mode).
   - Use SENAITE's existing **sample workflow** and **worksheet** system.
     Do not build a parallel workflow engine.
   - Use SENAITE Analysis Services, Methods, Sample Types, Containers,
     Storage Locations that already exist from the setup data.

2. **Modular and loosely coupled.** Each pipeline stage (import → QC →
   review → report) is an independent module with a clear interface, so a
   manager can re-run or re-tool any single stage without the others. Favor
   small, composable functions over monoliths.

3. **Python 2.7 for all in-Plone code.** No f-strings, no `pathlib`, no
   `from __future__ import annotations`, no type-annotation syntax in
   function signatures inside the add-on. Use `.format()`, `os.path`, `six`
   where needed. (The worker package may use Python 3.)

4. **Migrate configuration into GenericSetup + control panels** so it
   installs cleanly and is editable afterward in the UI.

---

## 3. The headline feature: sample status tracking

Two audiences, two views, one underlying workflow.

### Client-facing tracker ("Domino's pizza tracker")
- Clients receive a **tracking number** when they drop off a sample.
- A **simplified, public, no-login** page where a client enters that tracking
  number and sees their sample's progress.
- Stages the client sees:
  **Received → Extraction → On Instrument → QC Review → Report Published**
- Must include a **fun animation/visualization** of progress (not a data
  table) and a **time estimate per stage**, where the estimate is the
  **average time samples of that method type historically spend at that
  stage**. Compute the rolling average from completed samples per method.
- No QC detail, no internal data — just the friendly progress view.

### Analyst / manager view
- The same five stages, but annotated with **who** is responsible at each
  (e.g. the extracting analyst, the reviewing analyst).
- This internal view may show more, but per the lab's instruction the
  per-check QC detail is NOT required on the tracker itself — keep the
  tracker focused on stage + animation + time estimate. QC detail lives in
  the normal SENAITE analysis/worksheet views.

### Who configures what
- The **Method Profile control panel** and QC criteria are editable by
  Manager, QA Officer (QAO), Lab Director, and Owner roles. Build/verify a
  permission so these roles — and not bench analysts — can edit criteria.

---

## 4. Build order (do them in this sequence; finish one before the next)

**Stage 1 — De-hardcode QC into the UI.**
Move every hardcoded QC value out of Python into (a) SENAITE Analysis
Specifications for simple per-analyte/sample-type ranges, and (b) a custom
**PFAS Method Profile** content type / control panel in Site Setup for the
method-specific logic (FDA three-tier recovery, CCV frequency, RRT relative
vs absolute, ion-ratio tolerance, r² minimum, surrogate guidance flag,
per-matrix sample factors). The QC engine must READ from these, not from
constants. Keep the current values as the seeded defaults so behavior is
unchanged until someone edits them.

**Stage 2 — Analyst step-by-step status UI.**
A clear per-sample and per-batch view showing which of the five stages the
sample is in, who is responsible, and what happens next. Drive it from the
real SENAITE workflow state — do not invent a separate status field that can
drift from the workflow.

**Stage 3 — Client tracker + tracking numbers.**
Generate a tracking number at sample receipt, the public lookup page, the
animation, and the per-method per-stage time estimates from historical
averages.

After all three: regression-test that the existing pipeline still imports,
runs QC, and produces a report.

---

## 5. How to handle ambiguity (the ask-don't-guess rule)

You have full permission to read and modify files without asking. You do NOT
have permission to guess on design decisions.

When you hit a design decision that isn't specified here or in the repo docs:

1. **Stop before coding it.**
2. **Present your proposed assumption** as a concrete, specific statement —
   what you'd do and why.
3. **Ask whether to add, edit, or delete** that assumption.
4. **Wait for confirmation.** Restate the final agreed decision in one line.
5. **Then execute**, and log it (see §6).

Do not batch ten guesses into code and surface them later. Surface each
material decision at the moment you hit it.

Examples of things to STOP and ASK about: exact stage names or transitions,
what a tracking number looks like, which roles get which permission, how a
QC limit should be represented in the UI, anything touching Docker volumes
or the instrument share path, anything that deletes or restructures existing
working modules.

Things you do NOT need to ask about: editing files, adding tests, fixing
obvious bugs, Python-2.7 syntax corrections, formatting.

---

## 6. Decision log

Maintain a `DECISIONS.md` file in the repo root. Every time a design decision
is made (whether you proposed it or the lab specified it), append an entry:

```
## [date] <short title>
- Decision: <the agreed decision in one or two sentences>
- Status: proposed | confirmed | superseded
- Context: <why this came up>
```

Keep a separate `QUESTIONS.md` for open questions awaiting the lab's answer.
Never let an assumption live only in code — it must be traceable here.

---

## 7. Environment / testing

- SENAITE 2.6.0 in Docker; you have `docker compose` access.
- After changes, bring the stack up and verify against the running instance
  rather than assuming. Tail logs with `docker compose logs -f senaite`.
- The add-on installs via the GenericSetup profile; re-running it must be
  idempotent (get-or-create everything).
- Mount paths in `docker-compose.yml` (e.g. the instrument share) are
  environment-specific placeholders — confirm the real paths with the lab
  before relying on them.

### Infrastructure restart procedure (full recovery after power loss)

**Step 1 — Start Docker stack** (run from project root `/home/robin/Downloads/senaite_pfas`):
```
docker compose up -d
```
Note: `robin` is NOT in the `docker` group. If the above fails with permission
denied, fix the socket temporarily:
```
sudo chmod 666 /run/docker.sock
```
Then re-run `docker compose up -d`. Confirm all five containers are Up:
```
docker compose ps
```
Expected services: nginx, zeo, senaite, pfas-worker, extraction-ui.

**Step 2 — Confirm SENAITE is responding locally:**
```
curl -I http://localhost:8080/senaite
```
Should return `200 OK`. Zope/Plone takes ~60s to fully boot after a cold start.

**Step 3 — Start the Cloudflare tunnel:**
`cloudflared` is NOT installed as a system package or service. The binary must
be downloaded each time (or kept at `/usr/local/bin/cloudflared`):
```
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o /tmp/cloudflared && chmod +x /tmp/cloudflared
```
Then start the tunnel pointing at nginx on port 80:
```
/tmp/cloudflared tunnel --url http://localhost:80 --no-autoupdate &
```
Wait ~8 seconds — the new public URL will appear in the terminal output:
```
https://<random-words>.trycloudflare.com
```

**TryCloudflare quick tunnel** — the public URL is ephemeral and changes on
every restart. There is no persistent domain — clients must be given the new
URL each time the tunnel restarts. The full SENAITE login URL is:
`https://<random-words>.trycloudflare.com/senaite`

**To do this permanently:** register `pinestatelaboratories.com` with Cloudflare
and set up a named tunnel. Named tunnels have a persistent URL that survives
reboots without needing a new URL each time.

### nginx VirtualHostMonster — known working config

The nginx rewrite MUST use `VirtualHostRoot/senaite/$1` (NOT `senaite/VirtualHostRoot/$1`).
The correct line in `nginx.conf`:
```
rewrite ^/senaite/(.*)$
    /VirtualHostBase/https/$http_host:443/VirtualHostRoot/senaite/$1
    break;
```
The wrong order (`senaite/VirtualHostRoot/`) causes SENAITE to generate login
redirect URLs as `/login` instead of `/senaite/login`, producing a 404 from nginx.
After editing nginx.conf, a `docker compose restart nginx` is required — `nginx -s reload`
does not always pick up bind-mounted file changes.

---

## 8. Known placeholders to flag, never silently invent

- EPA 1633A per-analyte EIS/OPR limits — must be lab-verified against the
  purchased method; surface as configurable with a "verify" flag.
- Some CAS numbers marked PLACEHOLDER.
- Waters MassLynx sample-list import schema (version-specific).
- MRM transitions / instrument acquisition method.

If a value like these is needed and unknown, ask — do not fabricate it.

---

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
