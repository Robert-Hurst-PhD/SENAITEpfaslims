# -*- coding: utf-8 -*-
"""
Seed a full FDA 32-PFAS field sample (all analytes) + QC, driven to `verified`
so it can be PUBLISHED through the real workflow to exercise the D65 controlled
CoA publication + amend/republish register.

Creates sample COA-DEMO-0001 in client-1 (Eggs matrix, FDA method) with all 32
FDA-linked analyte results, real submit/verify review-history (so the CoA
attestation resolves actual actors), and MB/LCS/LFSM/LFSMD/CCV/CCB QC rows in
the QC SQLite for the run. Leaves the sample in `verified` — publish it via the
real transition (jsonapi) so the publication subscriber fires.

Run:  docker exec -u senaite senaite_pfas-senaite-1 \
          bin/instance run /addon/seed_published_coa.py

Idempotent: deletes an existing COA-DEMO-0001 first. Python 2.7.
"""
from __future__ import absolute_import, print_function

import os
import random
import sqlite3

import transaction
from DateTime import DateTime
from Testing.makerequest import makerequest

import Zope2
app = makerequest(Zope2.app())

from AccessControl.SecurityManagement import newSecurityManager
from zope.component.hooks import setSite, setHooks

setHooks()
portal = app.senaite
setSite(portal)
admin = app.acl_users.getUserById("admin")
newSecurityManager(None, admin.__of__(app.acl_users))

from bika.lims import api
from bika.lims.utils.analysisrequest import create_analysisrequest

SAMPLE_ID = "COA-DEMO-0001"
DB_PATH = os.environ.get("PFAS_QC_DB", "/data/qc/pfas_qc_results.db")
wf_tool = api.get_tool("portal_workflow")
scat = api.get_tool("senaite_catalog_setup")

AR_WF = "senaite_sample_workflow"
ANA_WF = "senaite_analysis_workflow"


def set_wf_state(obj, wf_id, state_id, action):
    """Force a workflow state (bypasses guards) but ADD a review-history entry
    so downstream (the CoA attestation) can resolve the actor."""
    wf_tool.setStatusOf(wf_id, obj, {
        "review_state": state_id, "action": action,
        "actor": "admin", "time": DateTime(), "comments": "COA demo seed",
    })
    obj.reindexObject(idxs=["review_state"])


# ── reference data ──────────────────────────────────────────────────────────
methods = {b.Title: b.getObject() for b in scat(portal_type="Method")}
fda = [m for t, m in methods.items() if "FDA" in t or "32" in t][0]
sample_types = {b.Title: b.getObject() for b in scat(portal_type="SampleType")}
eggs = sample_types["Eggs"]

svcs = [b.getObject() for b in scat(portal_type="AnalysisService")]
def _role(s):
    try:
        return s.Schema()["pfas_role"].get(s)
    except Exception:
        return None
def _fda_linked(s):
    try:
        return fda in (s.getMethods() or [])
    except Exception:
        return False
analyte_svcs = [s for s in svcs if _role(s) == "analyte" and _fda_linked(s)]
print("FDA analyte services:", len(analyte_svcs))

client = portal.clients["client-1"]
contact = list(client.objectValues("Contact"))[0]

# ── idempotent: remove prior demo sample ────────────────────────────────────
if SAMPLE_ID in client.objectIds():
    client.manage_delObjects([SAMPLE_ID])
    transaction.savepoint(optimistic=True)
    print("removed prior", SAMPLE_ID)

# ── create the field sample with the full analyte panel ─────────────────────
values = {
    "Client": client, "Contact": contact, "SampleType": eggs,
    "DateSampled": DateTime() - 3, "Method": fda,
    "Analyses": [s.UID() for s in analyte_svcs],
}
ar = create_analysisrequest(client, app.REQUEST, values)
# rename to a stable id
if ar.getId() != SAMPLE_ID:
    client.manage_renameObject(ar.getId(), SAMPLE_ID)
    ar = client[SAMPLE_ID]
transaction.savepoint(optimistic=True)

analyses = [o for o in ar.objectValues() if o.portal_type == "Analysis"]
print("created", SAMPLE_ID, "with", len(analyses), "analyses")

# Enable self-verification so admin can verify its own submitted results when
# the workflow is driven end-to-end (below, via jsonapi over HTTP).
try:
    portal.bika_setup.setSelfVerificationEnabled(True)
except Exception as exc:
    print("self-verification toggle warn:", exc)

# ── mock results only — leave the workflow to REAL transitions ──────────────
# (setStatusOf would force the state but skip the bookkeeping the publish guard
#  checks, leaving the sample non-publishable. So we set results here and drive
#  receive -> submit -> verify -> publish through the real workflow afterwards.)
random.seed(42)
for ana in analyses:
    if random.random() < 0.4:
        ana.setResult("0")            # below reporting limit
    else:
        ana.setResult(str(round(random.uniform(0.05, 4.5), 3)))
ar.reindexObject()
transaction.commit()

# ── QC SQLite: MB/LCS/LFSM/LFSMD/CCV/CCB for every analyte ──────────────────
BATCH_ID = "BATCH-COA-DEMO"
RUN_DATE = (DateTime()).strftime("%Y-%m-%d")
keywords = [s.getKeyword() for s in analyte_svcs]

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
# discover columns actually present
cur.execute("PRAGMA table_info(qc_results)")
cols = set(r[1] for r in cur.fetchall())
# clear prior demo rows
cur.execute("DELETE FROM qc_results WHERE batch_id=?", (BATCH_ID,))

def add_qc(qc_type, level, analyte, value, expected, passed, flag=""):
    row = {
        "batch_id": BATCH_ID, "run_date": RUN_DATE, "analyte": analyte,
        "qc_type": qc_type, "qc_level": level, "method": "FDA_32PFAS",
        "analyst": "admin", "instrument_id": "SCIEX-7500",
        "value": value, "expected_value": expected, "units": "ng/kg",
        "flag": flag, "passed": 1 if passed else 0, "result_status": "active",
        "created_at": DateTime().ISO(),
    }
    use = [(k, v) for k, v in row.items() if k in cols]
    cur.execute("INSERT INTO qc_results ({0}) VALUES ({1})".format(
        ",".join(k for k, _ in use), ",".join("?" for _ in use)),
        [v for _, v in use])

n = 0
for kw in keywords:
    exp = 100.0
    for qc_type, level, lo, hi in [("LCS", "LCS-1", 70, 130),
                                    ("LFSM", "LFSM-1", 70, 130),
                                    ("LFSMD", "LFSMD-1", 70, 130),
                                    ("CCV", "CCV-1", 80, 120)]:
        rec = random.uniform(78, 118)
        add_qc(qc_type, level, kw, round(exp * rec / 100.0, 2), exp, lo <= rec <= hi)
        n += 1
    for qc_type, level in [("MB", "MB-1"), ("CCB", "CCB-1")]:
        val = round(random.uniform(0.0, 0.06), 4)
        add_qc(qc_type, level, kw, val, None, val < 0.5)
        n += 1
conn.commit()
conn.close()

print("QC rows seeded:", n, "for batch", BATCH_ID)
print("RESULT sample=%s uid=%s state=%s analytes=%d" % (
    SAMPLE_ID, api.get_uid(ar), api.get_review_status(ar), len(analyses)))
