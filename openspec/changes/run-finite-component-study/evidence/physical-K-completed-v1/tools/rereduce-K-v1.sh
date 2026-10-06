#!/bin/bash
# Task 5.4: independent re-reduction of attempt K raw inputs with the original campaign deadline (no fresh clock).
set -eu
ROOT=/home/s-a-balashov/vffefab7aK
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
T=/mnt/e/STUDY/VAST/tmp/finite-component-study-20261005
L=$T/launch-K-v1-logs
B=$ROOT/s/run/closed-inputs.original.json
RES=$ROOT/s/run/study-results.original.json
[ -f "$B" ] || { echo "no closed-inputs binding" >&2; exit 3; }
SIZE=$(stat -c %s "$B"); SHA=$(sha256sum "$B" | cut -d' ' -f1)
# campaign deadline = run() started + 14400 s; started_monotonic_ns is recorded in the completed document
STARTED=$("$PY" -c "import json,sys;print(json.load(open(sys.argv[1]))['started_monotonic_ns'])" "$RES")
[ -n "$STARTED" ] || { echo "no campaign started_monotonic_ns" >&2; exit 4; }
DEADLINE=$("$PY" -c "print($STARTED/1e9+14400.0)")
echo "binding=$B size=$SIZE sha=$SHA started_ns=$STARTED deadline=$DEADLINE now=$("$PY" -c 'import time;print(time.monotonic())') results=$RES" > "$L/rereduce.txt"
cd "$ROOT"
"$PY" -I -B scripts/reduce_canonical_systems_study_v1.py --binding "$B" --binding-size-bytes "$SIZE" --binding-sha256 "$SHA" \
  --output "$T/launch-K-v1-logs/independent-rereduce.K.v1.json" --deadline-monotonic "$DEADLINE" \
  > "$L/rereduce.stdout" 2> "$L/rereduce.stderr" && RC=0 || RC=$?
echo "rereduce_rc=$RC" >> "$L/rereduce.txt"; exit $RC
