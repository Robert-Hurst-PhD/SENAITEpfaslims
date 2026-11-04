#!/bin/sh
# The raw-data converter service (docs/RAW_DATA.md): runs inside ProteoWizard's
# image as the pfas-convert service, with no network, beside the worker on
# the raw-runs volume. The worker hands each copied raw folder over as a
# request in the queue folder:
#
#     <run>__<folder>.request    line 1 the raw folder, line 2 the output
#                                folder, line 3 the conversion profile
#
# and this answers <run>__<folder>.done (the mzML written) or
# <run>__<folder>.failed (msconvert's exit code and the end of its output).
# --once: one pass, then exit (tests).
QUEUE="${PFAS_CONVERT_QUEUE:-/data/raw_runs/queue}"
EVERY="${PFAS_CONVERT_EVERY:-5}"

one_pass() {
    [ -d "$QUEUE" ] || return 0             # the worker makes the queue (its owner)
    for req in "$QUEUE"/*.request; do
        [ -e "$req" ] || continue
        base="${req%.request}"
        if [ -e "$base.done" ] || [ -e "$base.failed" ]; then
            continue
        fi
        in=$(sed -n 1p "$req")
        out=$(sed -n 2p "$req")
        args=$(sed -n 3p "$req")
        name=$(basename "$in")
        name="${name%.*}"
        log="$base.log"
        # the profile's words are separate arguments
        # shellcheck disable=SC2086
        wine msconvert "$in" $args -o "$out" > "$log" 2>&1
        rc=$?
        if [ "$rc" -eq 0 ] && [ -s "$out/$name.mzML" ]; then
            printf '%s\n' "$out/$name.mzML" > "$base.done.part" && mv "$base.done.part" "$base.done"
        else
            { echo "exit $rc"; tail -c 2000 "$log"; } > "$base.failed.part" && mv "$base.failed.part" "$base.failed"
        fi
        rm -f "$log"
    done
}

if [ "$1" = "--once" ]; then
    one_pass
    exit 0
fi
while true; do
    one_pass
    sleep "$EVERY"
done
