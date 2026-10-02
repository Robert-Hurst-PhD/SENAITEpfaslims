# Bench chemist day-to-day: extraction and inventory review (2026-10-02)

> **Status (2026-10-02): done.** Phases 1–4 and R9–R11 are implemented —
> GAPS §86–§89. The extraction-ui tablet service described in B1 is retired.
> Form numbers below are the lab's FM-ENV-00x codes (the slugs 250–253 are
> storage keys).

Goal (lab, 2026-10-02): a user-friendly bench interface that encourages the
chemist to document what they did, logs every item used through an
extraction, and makes it seamless, with the inventory integrated into that
experience. Read-only audit of the live system (screens walked as a chemist
would; a test session on demo batch B-002 was started and removed). Plans
below need sign-off (CLAUDE.md §8).

## What works
- The guided extraction (`@@pfas-extraction-guide`): method stages from the
  method profile, a stage list with progress, a reagent row per role, a camera
  scanner, a deviations box, "prepare a solution" (files a Prepared Standard),
  and now a working PDF logbook.
- The reagent inventory: search, status, CoA upload, scan/OCR to add, expiry
  defaults. Prepared standards keep their parent-reagent chain.

## Findings

### B1. Two extraction systems (high)
- A separate service, **extraction-ui** (FastAPI, port 9000, running 11
  days), is a tablet "extraction log" with its **own JSON reagent catalogue**
  and its own logs, which the pipeline embeds in report PDFs. Five small logs
  exist (June/July, demo worksheets).
- The SENAITE guided extraction and inventory do the same job. Two inventories
  and two extraction records break CLAUDE.md §1.3 (one source per fact) and
  §6 traceability: a lot scanned on the tablet is unknown to SENAITE.

### B2. No way in (high)
- The Bench landing is five link tiles; no queue of what needs extracting, no
  "Start extraction". The guided extraction opens only with a batch id in the
  address; without one it shows a blank form with no batch picker.
- On start, the chemist picks the method by hand (the batch already has one)
  and types their name (they are logged in).

### B3. Items used are typed, not taken from inventory (high)
- Each reagent row is a typed lot number, a typed expiry date, a free "qty
  used" and a status menu. A lot auto-fills only when exactly one inventory
  record matches the role's name; the live completed session stored **no
  inventory link** for any reagent (name, lot, supplier, volume as text).
- Prepared solutions (mobile phases, spike mixes) are not matched to the
  Prepared Standards they are. Consumables (tubes, syringes, vials, SPE) are
  listed under "equipment" and asked for a serial number, not a lot.

### B4. Nothing is checked when a stage is completed (high)
- An expired or quarantined lot, a role left empty, a balance not verified
  today: the stage saves regardless. Expiry warnings are colour only.

### B5. The inventory does not learn what was used (medium)
- No usage record: a lot's page cannot say which batches used it, and a
  recall ("which results used methanol lot X?") cannot be answered from it.
- Quantity is free text, never decremented; no low-stock signal.
- Storage location is typed text (senaite.storage is installed, unused).

### B6. Equipment is typed (medium)
- Serial numbers are typed; they are matched to facility units afterwards
  (`_resolve_equipment`), but whether the balance passed its verification
  that day is not shown or checked.

### B7. One extraction is documented on four or five screens (medium)
- Stages (guided extraction), per-sample aliquot masses (FM-ENV-004), solvent
  preparation (FM-ENV-001), standards (FM-ENV-002), extraction (FM-ENV-003,
  which redirects to the guide). The "Sample Weighing" stage records no
  sample weights.

## Review loose ends (reuse review)
- **R9. GS1 barcode parsing.** The SENAITE scanner reads the raw barcode; GS1
  (GTIN, lot, expiry) is parsed only in the tablet service, by hand. biip (the
  best-known Python parser) is Apache-2.0, not GPLv2-compatible;
  **gs1-barcode-parser-mod** (MIT, browser) fits, and scanning is in the
  browser.
- **R10.** `injection_builder.InjectionSequenceBuilder` is used only by tests
  (production runs come from the Run Builder); its `REVIEW_CHECKS` constant is
  live. Move the constant, delete the builder and its tests' dependency.
- **R11.** tesseract.js v2 → v5; @zxing/library → @zxing/browser.

## Proposed plan

**Phase 1 — a way in and one record (B1, B2, B7 part)**
- Bench landing becomes a queue: batches awaiting or in extraction (started /
  stage N of M / finished), one "Start" or "Continue" button each; reagent
  alerts (expiring, quarantined, low); today's balance verification status.
- Start takes the method from the batch and the analyst from the login.
- Retire extraction-ui: SENAITE's guided extraction is the one tablet
  interface (it already is tablet-friendly); the pipeline reads extraction
  data from SENAITE only.

**Phase 2 — every item from the inventory (B3, B4, R9)**
- Each reagent role offers only usable lots for that role (active / opened, in
  date, not quarantined), Prepared Standards included; scanning resolves the
  barcode (GS1 parsed) to the inventory record; expiry is read, never typed.
- An unknown barcode opens "receive into inventory" inline, then returns to
  the stage.
- Consumables become an inventory category recorded by lot.
- Completing a stage checks: no expired / quarantined lot; every role filled
  (or a stated reason); equipment chosen from facility units with today's
  verification shown.

**Phase 3 — the inventory learns (B5, B6)**
- A usage record per item per stage (lot, batch, stage, amount, who, when):
  the lot's page lists where it was used; a recall search by lot.
- Optional numeric quantity with deduction and a low-stock level.

**Phase 4 — one screen per extraction (B7)**
- The weighing stage carries the sample table (aliquot mass / volume per
  sample, dilution); the FM-ENV logbooks show the same data rather than ask
  for it again.

## Decisions needed
- **DB1.** Retire the extraction-ui tablet service (recommended).
- **DB2.** A lot not in the inventory: block, or allow with a stated reason.
- **DB3.** Quantities: numeric with deduction and low-stock, or a usage record
  only.
- **DB4.** Expired / quarantined lot or unverified balance at stage completion:
  block, or warn and require a deviation note.
