#!/usr/bin/env bash
# Amendment 7, 6D.5: 23 packaged checks (recipe run_packaged_checks.py, diff vs 20261008d).
set -euo pipefail
E=$(cd "$(dirname "$0")" && pwd)
base=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008e
python=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
cp "$E/run_packaged_checks.py" "$E/run_packaged_checks.py.recipe-diff.txt" "$base/"
set +e
"$python" -B "$base/run_packaged_checks.py" > "$base/packaged_checks.stdout.log" 2> "$base/packaged_checks.stderr.log"
rc=$?
set -e
echo "$rc" > "$base/packaged_checks.rc"
python3 "$E/engine_snapshot.py" "$E/build_prep/engine.after-packaged.v1.json"
echo "packaged rc=$rc"; cat "$base/packaged_checks.stdout.log"; exit "$rc"
