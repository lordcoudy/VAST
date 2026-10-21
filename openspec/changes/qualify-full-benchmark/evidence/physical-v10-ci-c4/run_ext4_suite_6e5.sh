#!/usr/bin/env bash
# Amendment 8, 6E.5: full ext4 suite on C_Q1'''' = C_B'''' (recipe: run_ext4_suite_6d8_rerun2.sh of 6D.8).
set -euo pipefail
sha=$1
E=$(cd "$(dirname "$0")" && pwd)
R=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
C=/home/s-a-balashov/work/vast-qfb-ci-20261009-${sha:0:8}
OUT=$C-original-output
[[ ! -e "$C" && ! -e "$OUT" ]]
git clone -q --depth 8 --branch codex/qualify-full-benchmark file:///mnt/e/STUDY/VAST "$C"
git -C "$C" checkout -q --detach "$sha"
[[ "$(git -C "$C" rev-parse HEAD)" == "$sha" ]]
tag=artifacts/qualify_full_benchmark_20261008e
while read -r rel; do mkdir -p "$(dirname "$C/$tag/$rel")"; cp "$R/$tag/$rel" "$C/$tag/$rel"; done < "$E/receipts.list"
(cd "$C/$tag" && sha256sum $(sed 's#^#./#' "$E/receipts.list")) > "$E/ext4-clone.copied-ignored-receipts.sha256"
while read -r rel; do mkdir -p "$(dirname "$C/$rel")"; cp "$R/$rel" "$C/$rel"; done < "$E/models.list"
(cd "$C" && sha256sum $(cat "$E/models.list")) > "$E/ext4-clone.copied-models.sha256"
date -u +%FT%TZ > "$E/ext4-suite.started.txt"
set +e
(cd "$C" && "$PY" -B scripts/run_ci_checks.py --expected-commit "$sha" --output-dir "$OUT" \
   --job-started-monotonic-ns "$(python3 -c 'import time;print(time.monotonic_ns())')") \
   > "$E/ext4-suite.run.stdout.log" 2> "$E/ext4-suite.run.stderr.log"
rc=$?
set -e
echo "$rc" > "$E/ext4-suite.rc"; date -u +%FT%TZ > "$E/ext4-suite.finished.txt"
cp "$OUT/report.json" "$E/ext4-suite.report.json" || true
echo "ext4 suite rc=$rc"
