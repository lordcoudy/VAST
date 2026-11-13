#!/usr/bin/env bash
set -euo pipefail
set -o noclobber
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
HOST="$(cd "$HERE/../../../../../" && pwd -P)"
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
BUILD=/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a
"$PY" -B "$HERE/prepare_fresh_check_catalog.py" "$BUILD" "$HOST" \
  aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795 \
  75922812dde1281dc57f7969d5cd5bd3d32fa6cd10e34a6638b8e54ce51fb95b \
  > "$HERE/fresh-inputs.catalog.v1.json"
