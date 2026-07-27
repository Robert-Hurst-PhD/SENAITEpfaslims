# -*- coding: utf-8 -*-
"""
Seed DEMO surrogate-recovery QC data so the control chart can plot ongoing
surrogate recoveries.

Surrogate recovery (recovery of the isotopically-labeled analogs spiked into
every field sample) is a per-sample QC metric with a 100 % target. It is
stored as qc_type='SURR' rows in qc_results (qc_level = sample_id), so the
existing control-chart machinery — qc-type dropdown, get_chart_data, date
range, Levey-Jennings limits and Westgard rules — picks it up with no new
reader.

Creates a realistic multi-date series (>=5 points per surrogate, several run
dates) because control limits need >=5 in-control points to compute. This is
DEMONSTRATION data, not real instrument output.

Run inside the container:
    docker exec -u senaite senaite_pfas-senaite-1 \
        sh -lc 'cd /home/senaite/senaitelims && bin/instance -O senaite run /addon/seed_surrogate_recovery.py'

Python 2.7 compatible.
"""
from __future__ import absolute_import, print_function, unicode_literals

import os
import random
import sqlite3

DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
METHOD = "FDA_32PFAS"
INSTRUMENT = "LCMS-1"

# Labeled surrogate -> (per-surrogate mean recovery %, sd). Kept mostly
# in-control so limits compute; small biases make the charts distinguishable.
SURROGATES = [
    ("13C8-PFOA", 101.0, 6.0),
    ("13C5-PFNA",  98.0, 7.0),
    ("13C8-PFOS",  95.0, 8.0),
    ("13C3-PFHxS", 103.0, 6.0),
]

SAMPLES = ["EGG-0001", "MEAT-0001", "FEED-0001"]
RUN_DATES = [
    "2026-06-19", "2026-06-26", "2026-07-03",
    "2026-07-10", "2026-07-17", "2026-07-23",
]
ANALYSTS = ["A. Rivera", "J. Smith"]


def run(app=None):
    random.seed(20260727)  # deterministic demo series
    from senaite.pfas.qc.store import QCResultStore
    store = QCResultStore(DB_PATH)

    # Idempotent: clear any prior demo SURR rows first.
    with sqlite3.connect(DB_PATH) as conn:
        removed = conn.execute(
            "DELETE FROM qc_results WHERE qc_type='SURR'").rowcount
    print("Cleared %d existing SURR rows" % (removed or 0))

    n = 0
    for di, run_date in enumerate(RUN_DATES):
        batch_id = "B-%s" % run_date
        analyst = ANALYSTS[di % len(ANALYSTS)]
        # qc_results.batch_id is a FK into batches — register the batch first.
        store.register_batch(
            batch_id=batch_id, run_date=run_date, analyst=analyst,
            instrument_id=INSTRUMENT, method=METHOD, status="reviewed",
            notes="demo surrogate-recovery batch")
        for surr, mean, sd in SURROGATES:
            for sample_id in SAMPLES:
                value = round(random.gauss(mean, sd), 1)
                # occasional realistic excursion
                if random.random() < 0.04:
                    value = round(value - random.uniform(18, 30), 1)
                passed = 70.0 <= value <= 130.0
                flag = "" if passed else "(R) surrogate recovery out of limits"
                store.add_result(
                    batch_id=batch_id,
                    run_date=run_date,
                    analyte=surr,
                    qc_type="SURR",
                    qc_level=sample_id,      # per-sample
                    value=value,
                    units="pct_recovery",
                    flag=flag,
                    passed=passed,
                    method=METHOD,
                    analyst=analyst,
                    instrument_id=INSTRUMENT,
                )
                n += 1

    print("Seeded %d SURR (surrogate recovery) rows" % n)
    print("Surrogates: %s" % ", ".join(s[0] for s in SURROGATES))
    print("Run dates : %s" % ", ".join(RUN_DATES))
    print("Points per surrogate: %d" % (len(RUN_DATES) * len(SAMPLES)))
    print("Open QC Control Charts -> QC Type 'SURR' -> pick a surrogate.")


if __name__ == "__main__":
    run(globals().get("app"))
