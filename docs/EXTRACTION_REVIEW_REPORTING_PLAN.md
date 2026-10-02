# Extraction UI, Data Review and the reporting template — review and plan (2026-10-02)

Goal (lab, 2026-10-02): make the guided extraction easy to use, carry what it
records into Data Review, and finish with issuing a reporting template.
Evidence: every stage of the FDA method walked at desktop (1366 px) and tablet
(820 px) width on the probe batch (cleaned up after); Data Review walked on the
released worksheet WS-0005; the certificate path read in code.

## A. The guided extraction

| # | Finding | Effect |
|---|---|---|
| A1 | At tablet width the site sidebar and the stage list take ~470 of 820 px; the sample table overflows (the unit column is cut off). | The bench device shows a third of the form. |
| A2 | Progress reads "0 % complete" until the last stage: `int(done / total * 100)` is integer division under Python 2. | The progress bar never moves. |
| A3 | Every stage asks for the analyst again (prefilled with the login). | A field to skip 8 times. |
| A4 | The Dilutions card is on every stage. | Noise on 7 of 8 stages; a dilution follows the run. |
| A5 | "Complete stage" is at the bottom of a long page; no pinned action bar (CLAUDE.md §6B). | Scrolling to finish every stage. |
| A6 | Completed stages cannot be opened again (the stage list is not clickable). | No way to look back or correct a stage before finalizing. |
| A7 | No review step before Finalize: nothing shows everything recorded across stages and what needed a note. | The chemist signs off blind. |
| A8 | The older cards (Solutions prepared, Standard / IS pedigree) keep inline styles and colours and the old typed-field pattern. | Two visual languages on one page. |

## B. Data Review

| # | Finding |
|---|---|
| B1 | No view of the extraction at all: stages with who / when, deviations and what needed a note, lots per stage, consumables, sample amounts and final volumes, dilutions, equipment and balance verification, finalized or not. The record exists; the reviewer cannot see it. |
| B2 | Traceability messages name storage slugs — "(252.standards)", "(253.processing_materials)" — instead of the form numbers. |
| B3 | Final Data lists a neat reading and its dilution retest side by side without marking which is reported. |
| B4 | Overview has no link to the extraction logbook PDF or the lot-usage record. |

## C. Issuing a reporting template

Today: after the Manager approves, Data Review links to SENAITE's publisher
(senaite.impress) with this add-on's certificate template; the format is set
per method × matrix on the method profile's Reporting tab (CAS / MDL / dilution
columns, non-detect format, significant figures, regulatory notes, standard
note); the attestation block names who prepared, verified and authorized; a
reissue requires an amendment reason (D65). What does not exist: a certificate
template that is itself a controlled, versioned document (drafted, previewed,
issued, superseded), and a single "issue certificate" step from Data Review.

## Proposed order

1. **Extraction UI (A1–A8):** a top stepper replacing the side stage list on
   narrow screens; progress fixed; the analyst shown once (recorded by the
   login, changeable); a pinned action bar; completed stages open read-only
   with "Correct this stage"; a Review & finalize screen listing every stage,
   lot, amount, warning and note; Dilutions only after the last stage; the old
   cards on the shared styles.
2. **Data Review (B1–B4):** an Extraction tab (the record above, links to the
   logbook PDF and lot usage), form numbers in messages, the reported value
   marked in Final Data.
3. **Reporting template (C):** per the decision below.

## Decisions needed

Answered 2026-10-02 (DECISIONS "Extraction UI, Data Review, reporting
template"): reporting = controlled template + issue step; extraction shown in
Data Review, not a release gate; a completed stage is corrected by reopening
it with a reason (previous version kept).
