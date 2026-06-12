#!/usr/bin/env bash
# Create test samples at all 5 stages via the SENAITE HTTP API.
set -euo pipefail

BASE="http://localhost:8080/senaite"
AUTH="admin:admin"
API="$BASE/@@API/senaite/v1"

# Sample type UIDs
ST_WATER="154f45b0b286477e9063941e374a7e27"
ST_GROUND="5badb2ca51a648f2acb943e9565cfe0e"
ST_SOIL="4ac5fca2998c4d09bd9ba415bd37e7a2"
ST_SW="fe4d2828973640f4a458bac3da1aa1e1"

# Method UIDs
M_537="dc3d72d685294ab78e1a11d9bae208cd"
M_FDA="3dc1817f9b7d40c4a4bf4d238d36e44c"
M_1633="4fe2e8fc516b42a0b6a20c1e26f275d0"

# Analysis service UIDs (3 for the demo)
SVC1="e772d4e1ee6341bfabe1c54e7610d75e"   # PFBA
SVC2="19852b35233b451aa269d609631bb8b0"   # PFOA
SVC3="24deb8b5253846f0a6cfe73865bdc0e3"   # PFBS

LOG_DIR="/home/robin/Downloads/senaite_pfas/data/extraction_logs"
mkdir -p "$LOG_DIR"

echo "=========================================================="
echo "Creating test samples (one per stage)"
echo "=========================================================="

# ── Client ─────────────────────────────────────────────────────────────────────
echo ""
echo "[0] Client ..."
CLIENT=$(curl -s -u "$AUTH" "$API/client" \
  | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['items'][0]['uid'] if d['items'] else '')")

if [ -z "$CLIENT" ]; then
  CLIENT=$(curl -s -u "$AUTH" -X POST "$API/client" \
    -H "Content-Type: application/json" \
    -d '{"Name":"PFAS Demo Client","ClientID":"DEMO001"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('uid',''))")
  echo "    Created client: $CLIENT"
else
  echo "    Re-using client: $CLIENT"
fi

# ── Helpers ────────────────────────────────────────────────────────────────────
api_post() {
  # api_post <endpoint> <json_body>
  curl -s -u "$AUTH" -X POST "$API/$1" \
    -H "Content-Type: application/json" -d "$2"
}

api_patch() {
  curl -s -u "$AUTH" -X PATCH "$API/$1" \
    -H "Content-Type: application/json" -d "$2" > /dev/null
}

transition() {
  local OBJ_UID="$1" ACTION="$2"
  curl -s -u "$AUTH" -X POST "$API/$OBJ_UID/workflow/$ACTION" \
    -H "Content-Type: application/json" -d '{}' > /dev/null 2>&1 || true
}

obj_id() {
  local OBJ_UID="$1"
  curl -s -u "$AUTH" "$API/$OBJ_UID" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))"
}

create_ar() {
  local ST="$1" METHOD="$2"
  local NOW; NOW=$(date -u +"%Y-%m-%dT%H:%M:%S")
  api_post "analysisrequest" \
    "{\"Client\":\"$CLIENT\",\"SampleType\":\"$ST\",\"Method\":\"$METHOD\",\"DateSampled\":\"$NOW\",\"Analyses\":[\"$SVC1\",\"$SVC2\",\"$SVC3\"]}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('uid',''))"
}

create_ws() {
  local AR_OBJUID="$1"
  api_post "worksheet" "{\"Analyses\":[\"$AR_OBJUID\"]}" \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('uid',''))"
}

set_and_submit_results() {
  local AR_OBJUID="$1"
  local UIDS
  UIDS=$(curl -s -u "$AUTH" "$API/$AR_OBJUID/analyses" \
    | python3 -c "import sys,json; [print(i['uid']) for i in json.load(sys.stdin).get('items',[])]")
  for A in $UIDS; do
    api_patch "$A" '{"Result":"0.001"}' || true
    transition "$A" "submit" || true
  done
}

assign_tn() {
  # Assign tracking number via instance run (needs direct ZODB access)
  local AR_OBJUID="$1"
  local SCRIPT; SCRIPT=$(mktemp /tmp/tn_XXXX.py)
  cat > "$SCRIPT" <<PYEOF
from __future__ import print_function
from Testing.makerequest import makerequest
import Zope2, transaction
app = makerequest(Zope2.app())
from AccessControl.SecurityManagement import newSecurityManager
from AccessControl.User import UnrestrictedUser
newSecurityManager(None, UnrestrictedUser('admin','',['Manager'],[]))
portal = app.senaite
from senaite.pfas.tracking_store import get_or_assign_tracking
from bika.lims import api as bapi
try:
    from zope.site.hooks import setSite; setSite(portal)
except Exception: pass
ar = bapi.get_object_by_uid('${AR_OBJUID}', None)
if ar:
    tn = get_or_assign_tracking(portal, ar)
    transaction.commit()
    print(tn)
else:
    print('ERROR_NO_AR')
PYEOF
  docker cp "$SCRIPT" senaite_pfas-senaite-1:/tmp/tn_assign.py > /dev/null 2>&1
  rm -f "$SCRIPT"
  docker compose exec senaite bin/instance run /tmp/tn_assign.py 2>/dev/null \
    | grep -v "^WARNING\|^time=" | tail -1
}

iso_ago() {
  # iso_ago <hours> — prints ISO timestamp N hours ago
  python3 -c "from datetime import datetime,timedelta; print((datetime.utcnow()-timedelta(hours=$1)).isoformat())"
}

# ── Stage 1: Received ──────────────────────────────────────────────────────────
echo ""
echo "[1] Stage 1 — Received (no worksheet) ..."
AR1=$(create_ar "$ST_WATER" "$M_537")
echo "    AR: $(obj_id "$AR1")"
transition "$AR1" "receive"
TN1=$(assign_tn "$AR1")
echo "    Tracking: $TN1"

# ── Stage 2: Extraction in progress ───────────────────────────────────────────
echo ""
echo "[2] Stage 2 — Extraction in progress ..."
AR2=$(create_ar "$ST_GROUND" "$M_537")
echo "    AR: $(obj_id "$AR2")"
transition "$AR2" "receive"
WS2=$(create_ws "$AR2")
WS2_ID=$(obj_id "$WS2")
echo "    Worksheet: $WS2_ID"
echo "{\"batch_id\":\"$WS2_ID\",\"analyst\":\"J. Smith\",\"started\":\"$(iso_ago 2)\"}" \
  > "$LOG_DIR/${WS2_ID}_extraction.json"
echo "    Extraction log: in progress"
TN2=$(assign_tn "$AR2")
echo "    Tracking: $TN2"

# ── Stage 3: On Instrument ─────────────────────────────────────────────────────
echo ""
echo "[3] Stage 3 — On Instrument ..."
AR3=$(create_ar "$ST_SOIL" "$M_FDA")
echo "    AR: $(obj_id "$AR3")"
transition "$AR3" "receive"
WS3=$(create_ws "$AR3")
WS3_ID=$(obj_id "$WS3")
echo "    Worksheet: $WS3_ID"
echo "{\"batch_id\":\"$WS3_ID\",\"analyst\":\"M. Johnson\",\"started\":\"$(iso_ago 4)\",\"completed\":\"$(iso_ago 1)\"}" \
  > "$LOG_DIR/${WS3_ID}_extraction.json"
echo "    Extraction log: completed"
TN3=$(assign_tn "$AR3")
echo "    Tracking: $TN3"

# ── Stage 4: QC Review ────────────────────────────────────────────────────────
echo ""
echo "[4] Stage 4 — QC Review ..."
AR4=$(create_ar "$ST_SW" "$M_1633")
echo "    AR: $(obj_id "$AR4")"
transition "$AR4" "receive"
WS4=$(create_ws "$AR4")
WS4_ID=$(obj_id "$WS4")
echo "    Worksheet: $WS4_ID"
set_and_submit_results "$AR4"
transition "$WS4" "submit"
echo "    WS submitted (to_be_verified)"
TN4=$(assign_tn "$AR4")
echo "    Tracking: $TN4"

# ── Stage 5: Report Published ──────────────────────────────────────────────────
echo ""
echo "[5] Stage 5 — Report Published ..."
AR5=$(create_ar "$ST_WATER" "$M_537")
echo "    AR: $(obj_id "$AR5")"
transition "$AR5" "receive"
WS5=$(create_ws "$AR5")
WS5_ID=$(obj_id "$WS5")
echo "    Worksheet: $WS5_ID"
set_and_submit_results "$AR5"
transition "$WS5" "submit"
transition "$WS5" "verify"
transition "$AR5" "publish"
echo "    WS verified, AR published"
TN5=$(assign_tn "$AR5")
echo "    Tracking: $TN5"

# ── Summary ────────────────────────────────────────────────────────────────────
echo ""
echo "=========================================================="
echo "Tracker URLs (open in browser — no login needed):"
echo "=========================================================="
for PAIR in \
    "Stage 1 — Received|$TN1" \
    "Stage 2 — Extraction|$TN2" \
    "Stage 3 — On Instrument|$TN3" \
    "Stage 4 — QC Review|$TN4" \
    "Stage 5 — Report Published|$TN5"; do
  LABEL="${PAIR%%|*}"
  TN="${PAIR##*|}"
  printf "  %-30s  %s/@@pfas-track?t=%s\n" "$LABEL" "$BASE" "$TN"
done
echo "=========================================================="
