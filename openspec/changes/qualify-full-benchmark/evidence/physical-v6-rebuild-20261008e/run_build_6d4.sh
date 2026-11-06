#!/usr/bin/env bash
# Amendment 7, 6D.4: runtime x4 rebuild in tag 20261008e (recipe build_downstream_images.sh, diff vs 20261008d).
set -euo pipefail
E=$(cd "$(dirname "$0")" && pwd)
base=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008e
cp "$E/build_downstream_images.sh" "$E/build_downstream_images.sh.recipe-diff.txt" "$base/"
python3 "$E/engine_snapshot.py" "$E/build_prep/engine.before-build.v1.json"
df -B1 --output=target,avail / /mnt/c /mnt/e /var/tmp > "$E/build_prep/disk.before-build.txt"
date -u +%FT%TZ > "$base/build.started.txt"
set +e
env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy bash "$base/build_downstream_images.sh" runtime
rc=$?
set -e
echo "$rc" > "$base/build.rc"; date -u +%FT%TZ > "$base/build.finished.txt"
python3 "$E/engine_snapshot.py" "$E/build_prep/engine.after-build.v1.json"
df -B1 --output=target,avail / /mnt/c /mnt/e /var/tmp > "$E/build_prep/disk.after-build.txt"
echo "build rc=$rc"; exit "$rc"
