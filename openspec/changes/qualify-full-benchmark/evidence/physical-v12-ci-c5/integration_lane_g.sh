#!/usr/bin/env bash
# Amendment 9, task 6F.5: nine physical integration tests on C_Q1''''' in the root (recipe: integration_lane_e.sh of 6D.8).
set -uo pipefail
R=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
N=$R/artifacts/qualify_full_benchmark_20261008e
OUT=$N/integration_lane_g
IDS=$R/artifacts/qualify_full_benchmark_20261007a/integration-test-ids.txt
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
[[ "$(id -u)" == 1000 && ! -e $OUT ]] || exit 64
cd $R
[[ "$(git rev-parse HEAD)" == d1a78805dd41f9f946e3f6c4ca673bfeced228b5 ]] || exit 64
mkdir -m 700 $OUT
cmp $IDS $N/integration-test-ids.txt
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
