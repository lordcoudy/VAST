#!/usr/bin/env bash
# Amendment 7, task 6D.8: nine physical integration tests on C_Q1''' in the root (precedent 5.6).
set -uo pipefail
R=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
N=$R/artifacts/qualify_full_benchmark_20261008e
OUT=$N/integration_lane
IDS=$R/artifacts/qualify_full_benchmark_20261007a/integration-test-ids.txt
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
[[ "$(id -u)" == 1000 && ! -e $OUT ]] || exit 64
cd $R
[[ "$(git rev-parse HEAD)" == 0aeb955bdf49d35ddb429c6a8e83d897608b00aa ]] || exit 64
mkdir -m 700 $OUT
cp $IDS $N/integration-test-ids.txt
git rev-parse HEAD > $OUT/commit.txt
date -u +%FT%TZ > $OUT/started.txt
: > $OUT/results.txt
while read -r id; do
  [[ -z "$id" ]] && continue
  VAST_LIVE_PREFLIGHT=1 VAST_RUN_OPENVINO_LIVE_DOCKER_TEST=1 TMPDIR=/var/tmp \
    "$PY" -B -m unittest -v "tests.$id" > "$OUT/$id.stdout.log" 2> "$OUT/$id.stderr.log"
  echo "$? $id" >> $OUT/results.txt
done < $IDS
date -u +%FT%TZ > $OUT/finished.txt
cat $OUT/results.txt
