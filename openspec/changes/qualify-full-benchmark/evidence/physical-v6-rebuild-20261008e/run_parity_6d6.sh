#!/usr/bin/env bash
# Amendment 7, 6D.6: parity 480/32 in namespace qfb-20261008e (recipe run_model_parity.sh, diff vs 20261008d).
set -euo pipefail
E=$(cd "$(dirname "$0")" && pwd)
base=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008e
cp "$E/run_model_parity.sh" "$E/run_model_parity.sh.recipe-diff.txt" "$base/"
date -u +%FT%TZ > "$base/parity.started.txt"
set +e
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy bash "$base/run_model_parity.sh"
rc=$?
set -e
echo "$rc" > "$base/parity.rc"; date -u +%FT%TZ > "$base/parity.finished.txt"
python3 "$E/engine_snapshot.py" "$E/build_prep/engine.after-parity.v1.json"
echo "parity rc=$rc"; exit "$rc"
