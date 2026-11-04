# Raw data processing: installing and switching it on

The LIMS can integrate the instrument's raw MRM chromatograms itself and
report its own results (design: `docs/plans/RAW_DATA_PROCESSING_design.md`).
Nothing of it runs until the lab completes the steps below; until then every
method's results come from the instrument software's export, as before.

## 1. Only if a converter is needed

A Waters MassLynx `.raw` folder is read by the worker itself (see "How a run
is read"): it needs no vendor licence, no converter image and no setting.
Skip this section unless the lab has raw data in another vendor's folder.

For those, raw files are converted to mzML by ProteoWizard `msconvert`
(Apache 2.0). It reads each vendor's format through that vendor's own reader
library, which is distributed under the vendor's licence inside
ProteoWizard's Docker image
(`proteowizard/pwiz-skyline-i-agree-to-the-vendor-licenses`).

- Read the vendor licences linked from ProteoWizard's download page. Pulling
  the image is the lab's acceptance of them, as the end user.
- Nothing of the image or the vendor readers is in this repository or the
  public install.
- Then start the converter service. In the `.env` file beside
  `docker-compose.yml`:

      PFAS_PWIZ_IMAGE=proteowizard/pwiz-skyline-i-agree-to-the-vendor-licenses:<tag>
      PFAS_CONVERTER=service

  and run `docker compose --profile raw-data up -d`. The `pfas-convert`
  service runs msconvert under Wine with no network; it sees only the
  raw-runs volume, where the worker hands it each copied raw folder and it
  answers with the mzML. The worker is never given the host's Docker.
- With `PFAS_CONVERTER` unset, Waters folders are read natively and a run
  with any other folder fails, naming `PFAS_CONVERTER`. `service` keeps the
  native read and adds `pfas-convert` for the folders that are not MassLynx.
  `native` takes the mzML a Windows PC converted, in place of the reader for
  every folder (section 6).

## 2. Share the instrument's data folder (IT)

- Share the acquisition PC's data folder **read-only**. Nothing is installed
  on, or changed on, the acquisition PC.
- Mount it on the server and into the worker container (for example at
  `/mnt/lcms/data`): a `volumes:` line on the `pfas-worker` service in
  `docker-compose.yml`, `- /mnt/lcms/data:/mnt/lcms/data:ro`, and the same
  path on System, in the Raw data share card.
- The copied runs are kept in the `pfas-raw-runs` volume (`RAW_RUN_DIR`,
  `/data/raw_runs`): each run's raw folders, any mzML files and checksums. The
  worker hands each run over in the instrument upload folder, which it mounts
  writable.

## 3. System (a site administrator)

System > Raw data share:

- **Instrument data share**: the mount's absolute path.
- **Unchanged before it is pulled, minutes**: how long every file of a run's
  raw folders must be unchanged before the run is pulled (a folder still
  being written is never copied).

## 4. The method's Integration tab (a manager)

Method Profiles > the method > Integration. Nothing is preset; a raw run of a
method with any of it unset is refused, naming what is missing.

- **Peak integration**: the engine, then its settings.
  - **Engine.** Classic: a fixed smoothing finds each peak in its window.
    Adaptive: the slope of the signal finds each peak and splits its
    shoulders. Adaptive follows the peak-finding method published by Nagura
    Lab (naguralab.com/integration), re-implemented from its description
    (`pfas_pipeline/raw_adaptive.py`). An engine never saved is integrated
    as Classic and is shown as Classic chosen, with its Baseline.
  - **Smoothing**: the filter's window, an odd number of points n (Classic,
    5 or more; Adaptive, 3 or more; Adaptive runs it as the half-width
    m = (n - 1) / 2), or `auto` under Adaptive: the half-width is then learnt
    for each compound from its median-concentration calibrator whose
    quantifier has not overflowed, and each peak names that calibrator. Saving
    the method checks the number against the engine.
  - **Edge points** (6 when blank; Classic only, shown only for it, beside
    the smoothing; a compound's column overrides it): each automatic
    baseline end is the mean of this many raw points just outside the peak,
    so the setting changes every automatic Classic peak and its reported
    area. A manual Classic line reads its ends the same way.
  - **Baseline** (valley to valley, or flat at the lower edge; Classic only, shown only
    for it: Adaptive draws each group's baseline itself), **area**
    (trapezoid, or a Gaussian or exponentially modified Gaussian fit) and the
    **smallest signal-to-noise reported**.
  - **Transition tolerance**, in m/z: how far a file's transition may lie from the method's
    on both Q1 and Q3 (see "How a run is read").
  - Adaptive only: **sensitivity** (the slope that starts a peak, as a
    multiple of the noise), **shoulder split** (a flat stretch above this
    share of the peak height is a shoulder), **qualifier apex tolerance**
    (the qualifier's peak lies this close to the quantifier's apex) and
    **expected time**: Fixed, each peak sought at its own retention time, or
    Isotope standard, a native's time moved with its isotope standard's
    found time in each injection (a standard not found leaves the native at
    its own time, with the note "anchor not found").
  - **Largest fit deviation**, required for a Gaussian or EMG area under
    either engine: a fitted area further than this from the trapezoid over
    the same edges, or a fit that fails, falls back to that trapezoid, and
    the peak says why.
  - **Peak review** (a group of nine settings, each blank for its default,
    drawn in the box; a compound's column overrides all but the search slope
    and smoothing): **fewest points in a peak** (5; a
    re-integration with fewer points between its edges is refused),
    **edges past the tail** (2 sigma; an edge nearer its apex is noted),
    **valley limit for a perpendicular drop** (25 %), **tangent skim ratio**
    (25 %), **peak search slope** (0.7, for a peak of unit height; Add peak
    at cursor takes a top as a peak only when the smoothed derivative falls
    across it by more than this over the square of the automatic peak's
    width at half height, in points, the fall read per count of the found
    peak's height above its line, so a broad climb is refused), **peak search amplitude** (the smallest S/N for a manual peak
    when set, else 3; a neighbour, and a peak Add peak at cursor finds,
    must rise this many noise deviations above the valley or line),
    **peak search smoothing** (50 %; Add peak at cursor searches the raw
    signal averaged over this share of the automatic peak's points at half
    height, at least one), **fewest points in a candidate** (3 raw samples
    at or above half the candidate's height) and **smallest candidate
    width** (40 % of the automatic peak's width at half height). They
    change what the review offers and notes, never an automatic peak, and
    they are part of the method's revision once set. The two candidate
    settings also decide which saved apex choices still replay: raising
    either can leave a saved apex choice unapplied until it is undone. The
    run is processed, the trace stays automatic and the panel's row says
    "no effect: the chosen apex is no longer a peak in its window".
- **Transitions and windows**: for every analyte and every labelled standard
  of the method, the quantifier ("Q1 > Q3"), the qualifiers, the retention
  time and window, and how the peak is taken: a single peak, one of a
  co-eluting pair fitted together (name its partner), or summed isomers.
  Adaptive fits no pair: a pair under it is refused, in the editor and when
  a run is read. An isomer's linear peak is always a single peak. A
  compound's own smoothing, area, smallest S/N, sensitivity, qualifier
  detection S/N and expected time override the method's; blank uses the
  method's.
- **Isomers.** An analyte with isomers (the Isomers tab) is integrated as lr
  and br rows: the linear peak is its lr row, and each br row covers the
  peaks in its own window, less the linear peak. Each is quantified on its
  own curve, and the two are summed only at reporting. When the analyst
  re-integrates an lr peak, its br row is summed again the same way, less
  whatever the lr peak now covers, so no peak area is counted in both rows;
  a br row re-integrated by hand stays as set. A br peak no
  calibrator states a concentration for (a linear-only standard) is read on
  its lr partner's curve. FOSA is integrated whole, one co-eluting cluster.
- **Qualifier S/N.** Each qualifier is integrated at the quantifier's apex;
  the first qualifier's signal-to-noise is the row's qualifier S/N. The
  compound's qualifier detection S/N, else the method's confirmation value,
  decides only whether the qualifier is found; under Adaptive, a qualifier
  not found beside a found quantifier reads 0. Whether the identity is
  confirmed (N.C. below it) is judged against the method's confirmation
  S/N alone.
- **Qualifier on a summed row.** On a summed row (a br cluster, FOSA) the
  quantifier area is the whole cluster, but the qualifier is the one peak
  at the tallest member's apex. The row's ion ratio is that qualifier peak
  over the summed quantifier, and its qualifier S/N is that peak's. The
  calibrators are measured the same way, so a ratio judged against the
  calibrators' mean holds; a typed expected ion ratio must be entered on
  the same basis.
- **Calibrators off the curve.** A calibrator with no quantifier peak, or
  none of its isotope standard, has no response: it is left off the curve,
  which names it with the reason "not detected" or "isotope standard not
  detected", and its row is not a calibrator of the curve. The lowest
  calibrator level the run holds is judged whether it was fitted or not: not
  detected, or below the method's quantifier or confirmation S/N, the
  calibration check fails, naming the analyte and the level.
- Quantitation uses the Calibration & CCV tab's origin and weighting. A
  labelled standard is at one level in every calibrator: when the method's
  Engine setting `labelled_compound_fit` says so, its concentration in the
  calibration lot (Prepared Standards, the lot's analyte concentrations) is
  what its mean response factor is fitted on.

**Drafting the transitions from a calibrator.** The transitions and the
quantifier choice come from the publication's MS conditions table (its SI
Table S7, where an ID ending in "a" is the quantifier); the retention times
come from a calibrator scanned on the lab's own instrument:

    python3 tools/raw/draft_integration.py SI.xlsx CAL_FOLDER [--csv OUT]

It maps each SI name to its keyword through the compound library, matches
each SI transition to the calibrator's nearest within 0.5 on both masses and
drafts the file's own values to two decimals, the retention time from the
scanned apex and the window blank. Its problems column lists an SI
transition not in the file, a file transition not in the SI, a compound with
no "a" mark or more than one, a name the library does not know, and an
isomer peak whose branched time must be read off the trace. It never writes
a profile: the analyst reviews the draft and enters it on the Integration
tab. `--library` reads a compound library export instead of the install
seed; `--profile` (with `--method`) takes the isomers from a method profile
instead of the library's branched compounds.

## 5. Validation, then LIMS integration

Neither has to wait for a check of the raw data: each can be chosen at any
time. The change log records who chose it, and when.

1. **Validation.** Set "Results come from" to Validation.
   For each built run the Run Builder writes what it expects
   (`<run>.rawexpect.json`); when every injection's raw folder is on the
   share and settled, the worker copies, checksums and reads them and
   imports the run from its raw data. The reported results stay the
   instrument software's; the raw side is kept for comparison. Data Review's
   Comparison tab lists every peak both ways and exports the validation
   record (CSV). The number of runs and the agreement the lab accepts are the
   lab's to set in its validation plan.
2. **LIMS integration.** Set "Results come from" to LIMS integration
   (Configuration History keeps who and when). The raw data's results are
   reported; an export imported for the run is kept for comparison.

## Reviewing a raw run

- **Raw Data tab** (Data Review): every chromatogram of the run as a small
  thumbnail. A switch picks the overview: By compound (one analyte across
  every injection, a compound chosen from the list) or By injection (every
  analyte of one injection). A thumbnail shows its edit: Automatic, Edited,
  Peak deleted, or Waiting while the run has yet to be processed again.
  Under By compound a note names the calibrators taken off the curve by a
  deleted peak. Rows are paired with their traces through the compound
  library (a row carries the display name, a trace and an edit the keyword);
  the tab shows the display name.
- **The card.** A click on a thumbnail opens the full card in a dialog,
  laid out as a result is read: the Quantifier / Qualifier switch; the
  trace alone (the isotope standard is named under Details), with zoom
  tools above it: zoom in, zoom out, zoom to a box dragged on the chart, and
  back to the whole window, the counts fitting the view once zoomed; a
  readout strip of area (with
  the automatic area and the signed change once the peak is edited),
  retention time, S/N, ion ratio with its expected value, concentration with
  its unit, and how the peak was integrated; the flags as chips; the
  controls; and, closed, Details. Details holds the engine (Classic when
  the peak names none), smoothing (the points the filter ran over, 2m + 1
  for the peak's half-width m, and the calibrator it was learnt from), FWHM
  in seconds, tailing, plates, the qualifier S/N, the file's transition
  where it differs from the method's, the isotope standard, the peak's note
  ("anchor not found", "baseline dip", "summed N peaks") and, with a
  concentration, the curve it was quantified against with a button to the
  Calibration tab. The calibration lots are not on the card; they stay on the
  Calibration tab and in the traceability tree. A quantifier whose apex
  the reader could not restore (see Ceiling below) reads Overflow. A fitted
  area refused for the trapezoid reads "Fit refused" with the reason; a pair
  fit that failed while the area kept its own fit reads "Pair fit failed";
  either marks the card for review. Previous and Next in the dialog's head
  (and PageUp, PageDown) open the neighbouring card in the grid's order and
  scroll the grid to it; with a change not applied, the page asks first in
  its own dialog ("Keep editing" or "Leave it"). An edit waiting for the run
  to be processed is drawn on the chart and named in the trace line; an
  edit the server refused reopens on the edges, line and levels as posted
  and says why.
- **Editing a peak.** Each trace of the card, the quantifier and every
  qualifier, is edited on its own, on the chart:
  - the baseline is a line with a hollow handle at each end. Dragging a
    handle sideways moves that edge to the nearest sample, inside the stored
    full-resolution region and never on or past the other edge, its level
    following the signal. Dragging it up or down sets that end's level by
    hand (kept within the trace's counts, both ends together on a flat
    line); the level boxes under the edges show the values. Shift, or a
    double-click on the handle, puts the level back on the signal. Dragging
    the line moves both edges by the same number of samples. The arrow keys
    nudge the focused handle a sample (Shift five); Tab moves between the
    handles;
  - a right-click on the chart, the Actions button in the footer and the
    menu key (or Shift+F10) open one menu. Set start here and Set end here
    take the cursor's time; Drop baseline here sets both levels to the
    smoothed signal at the cursor, a horizontal line; Baseline offers the four modes; Peaks found lists the other
    peaks; Add peak at cursor and Split at cursor act at the cursor; Delete
    peak, Undo edit and Restore automatic; Zoom to peak, Zoom to window and
    Copy values. An entry that cannot act is shown with its reason and is
    never acted on. A card that cannot be edited offers the last group only.
    The keys are `[` `]` `D` `A` `S` Delete `U` `Z` `W`, Enter to apply and
    Escape to close; Escape with a change not applied asks first, and inside
    a text box only Escape acts;
  - the four baseline modes:
    - **Valley to valley** joins the two edge levels, the method's line for
      a peak that stands clear;
    - **Perpendicular drop** draws one line under a pair of touching peaks,
      between the pair's outer edges, and measures each peak above it. The
      outer edges come from a walk: from each chosen edge the smoothed
      signal falls to the valley, climbs to a neighbour's top and falls to
      its far edge. A neighbour counts only if its top lies inside the trace,
      rises at least the peak search amplitude times the noise above the
      valley and falls by as much again beyond. With no neighbour the drop is
      the valley line. A valley share, the valley's height over the smaller
      peak's, is noted when it stands above the valley limit;
    - **Tangent skim** is for a rider on a tall peak's tail: the line runs
      from the smoothed signal at the start to the smoothed signal at the
      end. Its share, the rider's height above the line over its parent's
      height, is noted when above the skim ratio; with no parent the skim is
      its own line;
    - **Flat at the lower edge** is a horizontal line at the lower of the two
      edge levels (the Classic method's old "Drop line", renamed);
  - a level set by hand replaces the level its mode reads: the line between
    the two levels for valley and skim, flat at the lower of them for flat,
    and the line's values at the pair's outer edges for a drop. An area from
    levels is signed, with no clamping at zero. Without levels, Classic
    clips each point at zero under the line and Adaptive clips only the
    total;
  - Peaks found lists the other peaks the worker found in the window, each
    with time, area and S/N; a click chooses one. Another apex is offered on
    a single peak only, not on a summed row or a co-eluting pair. Peaks that
    share one apex are offered once, the automatic peak where it is one of
    them, else the larger; two the card still lists at one apex are refused,
    to be chosen by their edges instead. A candidate needs the fewest points
    in a candidate (raw samples at or above half its height) and the
    smallest candidate width, both measured above its own edge levels, so a
    fragment on a tall peak's tail is not offered. At 0.5 s sampling beside a
    2.5 s peak the narrowest real peak offered is about 0.9 s wide at half
    height (Classic, Adaptive with m = 2), 1.1 s (Adaptive with m = 1) and a
    rider 1.2 to 1.6 s; a narrower real peak needs the setting lowered to 2
    for its compound or an edge dragged by hand. The floor is not drawn on
    the card: a dropped candidate is simply absent;
  - Add peak at cursor is the browser's own search from the cursor, on the
    raw signal averaged over the peak search smoothing's share of the
    automatic peak's points at half height: it climbs to the top, follows
    each side down, and keeps the peak only when its S/N reaches the peak
    search amplitude and its top passes the peak search slope. With no
    automatic peak to read a width from, it climbs the engine's smoothing
    and asks no slope; Split at
    cursor keeps the side of the automatic peak that holds its apex, cut at
    the cursor with a perpendicular drop, and needs a neighbour across the
    cursor. Both post a re-integration and are judged by the server like any;
  - delete the peak (an isotope standard's deletion is confirmed first);
  - undo the edit, which goes back to the automatic integration, or Restore
    automatic, which also lets a change not yet applied go.

  The card previews the new peak with the same arithmetic as the worker. An
  edge can go only as far as the stored full-resolution region; to go
  further, widen the method's window and process the run again. An edit
  needs no reason when it is made. "Set expected retention time from this
  peak" is not offered: only the method editor writes a compound's retention
  time, and a role decision would be needed to let an analyst's card do it.
- **What the method refuses.** The review refuses an edit before anything is
  written, in the worker's own words, and the dialog gives the same texts.
  In the order they are judged for a re-integration:
  1. the edges and the stored full-resolution region;
  2. levels set by hand outside the stored trace's counts (checked before
     the points, as the worker does);
  3. fewer points between the edges than the compound's fewest points in a
     peak (both edges counted);
  4. a perpendicular drop or tangent skim whose neighbour walk, or the edge
     level window beside it, reads past the samples kept at full resolution
     ("choose other edges or another baseline"), and, on a trace stored
     before records kept where full resolution ends, "process the run
     again";
  5. an area that moves less than the method's Smallest manual change (5 %
     unless set, a default and a per-compound override) from the automatic
     area;
  6. a manual peak under Smallest S/N for a manual peak (its height over the
     trace's automatic noise, worked out again on every processing).

  A re-integration is compared like with like, the trapezoid over the manual
  edges and line against the automatic peak's stored area. Another apex
  chosen as found, with no baseline of its own, is judged on the candidate's
  own area and S/N from the worker's record against the automatic peak's
  stored area (a record with no stored area leaves the change unjudged); an
  apex with a baseline of its own is judged as a re-integration. Both limits
  apply to qualifier edits, with the one S/N setting. A deleted peak is
  exempt. Notes are never refusals: the valley and skim shares above, and an
  edge nearer its apex than the method's edges past the tail (the edge's
  distance from the apex over the peak's standard deviation, read from its
  half width at half height). Notes show as warning chips beside the
  readout.
- **What a deletion does.**
  - A deleted quantifier makes the analyte N.D.
  - A deleted qualifier makes the result N.C., and the ion ratio is taken
    from the qualifiers left. The N.C. is judged on every run and holds the
    release, whatever the S/N rule's switch or state; the ordinary qualifier
    S/N keeps its switch.
  - A qualifier is read only beside a quantifier peak. A qualifier edit is
    refused while the quantifier has no peak, or its deletion waits. One
    made before the quantifier lost its peak, or beside a quantifier not
    detected, is kept but has no effect: its card reads "No effect: the
    quantifier has no peak in <injection>", and it does not hold submit.
  - A deleted peak of an isotope standard asks for a confirmation that names
    the natives in that injection. They lose their concentration, and a
    native left without one raises a QC issue that holds the release. The
    injection's calibrators come off the curve with the reason "isotope
    standard peak deleted". A deleted calibrator peak comes off with "peak
    deleted".
  - A deleted linear isomer peak's automatic span still bounds its branched
    partner's sum, so no area is counted twice.
  - More deletions on one analyte's curve than Most calibrators dropped
    (a calibration setting) fails that analyte's curve check, and the
    lowest calibrator fails its level if any of its qualifiers is deleted,
    where the method sets a confirmation S/N limit.
- **After an edit.** The edits are kept beside the run
  (`<run>.overrides.json`, one record per trace and transition) and replayed
  whenever the run is processed; the automatic peak stays in the value's
  record. A manual line's area is the trapezoid of the signal above the line
  the analyst chose, whatever the method's or the compound's area setting
  (the record says "trapezoid, manual line"); an apex chosen as found keeps
  the candidate's own measure. The run is processed again. Submit and release are refused while
  edits wait for it, and a run whose processing failed says why. A chosen
  apex is found again as the candidate whose own apex is nearest it, within
  half the local median sample spacing (a shoulder's apex can sit on its own
  edge, or just outside its span); two equally near refuse the run, naming
  the trace. An edit the run cannot make
  (levels outside the trace, fewer points than the compound's fewest, a span
  the engine cannot measure, a chosen apex no peak's is that near, as when
  a raised candidate floor no longer offers it) is not a refusal of the run: the trace stays
  automatic, the card and the Manual changes panel read "No effect" with the
  reason, and no signature is asked. A record kept before edits carried a
  version is read as it was (its "drop" is the flat line, it is exempt from
  the fewest points and from levels), so it replays with the numbers it had. Rows integrated from raw data are not read as
  export detections.
- **Manual changes.** At the end of review a Manual changes panel lists
  every edit of the run, with what the peak was and is. The analyst gives a
  reason for each and initials once; submit is blocked until that is done.
  At verify the verifier's Approve Release countersigns them all; the
  countersign is saved only once the worksheet is verified, so it names the
  person who released it. Initials need the preparer sign right in Lab
  Staff, and the countersign the reviewer sign right, as for the instrument
  report's records. The countersigner is neither the analyst who initialled
  nor anyone who edited the record since its last undo. An edit that is
  undone, a peak left automatic, or an edit with no effect needs neither a
  reason nor a signature; the panel lists the last as "No effect" with why,
  and the history keeps them all. An edit in the run's file that no change
  lists holds submit and release ("an edit has no record; undo it on the Raw
  Data tab"); an undo retried after its edit was already removed completes
  by closing the change.
  These changes are stored apart from the instrument report's manual
  integrations, which keep their own flow.
- **Deploying.** The worker replays the edits with the add-on's own
  `raw_preview` and `raw_review`, so the worker and the add-on are deployed
  together, in lockstep: an add-on newer than the worker (or the other way
  round) can preview a peak the worker then integrates differently. The
  worker also calls a new endpoint of the add-on after each push,
  `@@pfas-unconfigured-deviation` (POST only, Manager permission, like the
  notice reminders it already calls), which files the run's
  unconfigured-criteria deviation; a page GET no longer writes one. An
  add-on without it makes the worker log that the deviation was not raised,
  and the run still stands; the worker's notice tick (every 15 minutes) files
  it for every open worksheet that has a run. After deploying, process every
  raw run again: touch each `<run>.rawrun` in the upload folder, then confirm
  Data Review's waiting banner clears on each worksheet once its import log
  reads imported. A run stored before edits existed keeps no full-resolution
  region, so its traces cannot be edited and an older re-integration reads
  as waiting until it is processed again. A run stored before the stored
  trace recorded where its full resolution reaches (`full_res_reach`)
  refuses a perpendicular drop or tangent skim, with "process the run
  again", until it is processed again. Processing again also rewrites the
  provenance of a stored manual edit (its baseline is named, a former "drop"
  reads "flat", the area method reads "trapezoid, manual line") without
  changing a number, except that on a method with a Gaussian or EMG area a
  stored manual edit's area becomes the trapezoid above its line.
- **Instrument Report**: the raw folders, their files' checksums, what each
  injection was read as (the MassLynx folder, or an mzML) and how: read from
  the MassLynx folder, converted with msconvert, or both, with the number of
  injections converted. A run still waiting names the injections not on the
  share or still being written; a failed pull says why, and its "Pull
  again" button asks for the run again. Injections acquired before one
  earlier in the sequence are named: "Acquired out of sequence order".

## How a run is read

A Waters `.raw` folder is read function by function, one function per MRM
transition: `_functns.inf` (the transitions and their scan counts),
`_funcNNN.idx` and `_funcNNN.dat` (the times and the intensities) and
`_header.txt` (when it was acquired). Nothing is filtered or centroided.

- **Transitions.** Each of the method's transitions is matched to the
  file's nearest within the method's m/z tolerance on both Q1 and Q3; two
  equally near refuse the run, naming both, and none within it refuses the
  run, naming the injection and the analyte. Where the file's transition
  differs from the method's, the peak's record names it (the card's File
  transition). One transition scheduled in two windows serves each analyte
  from the window it elutes in.
- **Time.** The idx time of a function's first scan is the scheduled
  window's start in seconds; each later one is the elapsed time in minutes
  from it. The retention time in minutes is `t0 / 60 + (t - t0)`.
- **Ceiling.** The 2-byte word is a 13-bit mantissa and a 3-bit exponent of
  4, so as stored it tops out at 134 201 344. Above that the value needs
  exponent 8 or more, which the three bits keep modulo 8 while the mantissa
  stays normalised (2048 or more); read as stored, the apex would be a
  trough. The reader restores the lost 8: a word with a normalised mantissa
  right after a word at exponent 7 or higher takes whichever exponent gives
  the value nearer the one before it. The DEMO set's 43 apexes above the
  ceiling read back whole this way, continuing the calibrators' doubling.
  An apex the reading still leaves as a trough is reported as overflowed:
  the peak's record says so and its area is not the peak's. A calibrator overflowed this way is left off the curve and is
  not judged as a calibrator; the run's range then ends at the highest
  calibrator still on the curve. An overflowed quantifier with a peak keeps
  its number and reads ALoQ ("Overflow at the apex: the stored value is above
  the file's number range"), as a result above that calibrator does, so the dilution is
  reported where there is one; with no detectable peak it reads Overflow (stored as
  the qualifier token Saturated), never N.D.
- **A folder that is not MassLynx** goes to the converter when one is set
  (`PFAS_CONVERTER=service`, section 1). With none set, the run fails naming
  `PFAS_CONVERTER`. A MassLynx folder that is damaged is never passed to a
  converter: the run fails naming the folder.
- **Converted data** (another vendor's folder, or a Waters folder converted
  on a Windows PC) is `msconvert --mzML --64 --zlib`
  (`pfas_pipeline/raw_pull.py`, CONVERT_ARGS): every chromatogram is kept.

## 6. Fallback: convert natively on a Windows PC

If Wine does not read another vendor's MRM data faithfully, convert on
Windows instead. Nothing downstream changes. `PFAS_CONVERTER=native`
replaces the reader for every folder of that worker: a Waters folder too is
then taken from the mzML the PC wrote.

- Use a Windows PC that can read the instrument's data folder and write
  into that same shared folder, the one the worker reads (System >
  Raw data share); the share then needs write access for that PC's account only.
  Prefer a PC other than the acquisition PC, so nothing is installed on the
  acquisition PC.
- Install ProteoWizard on it (its vendor readers are under the same
  licences).
- Schedule `tools/convert/convert_native.ps1 -Share <data folder>` in Task
  Scheduler every few minutes (`-OutDir` only when the mzML are written
  into a sub-folder of the share, `-Msconvert` with msconvert's full
  path). It converts each `<name>.raw` folder that has stopped changing,
  with the same profile as the server, and writes `<name>.mzML` only when
  complete.
- Set `PFAS_CONVERTER=native` for the worker (and stop the `pfas-convert`
  service). The worker then waits for each injection's `<name>.mzML`, copies
  and checksums it, copies and checksums its raw folder too when the share
  holds it, and records the conversion as native.
- The PC is then part of the validated system: record its ProteoWizard
  version, and keep the scheduled task's log.

The service's conversion of one run is given `PFAS_CONVERT_TIMEOUT` seconds
(1800 by default) before the pull is recorded as failed.

## Not built yet

- A raw run computes no surrogate recovery: the fortified concentration
  would come from the extraction record. The surrogate check stays pending,
  so under LIMS integration the run is held; under Validation the raw side
  is compared, not reported.
- A run on a reused calibration curve is refused ("Run a new curve"): stored
  curves keep no responses.
- A supplementary run is imported from the export: its sequence carries no
  calibrator levels.
