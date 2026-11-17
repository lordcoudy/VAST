#!/usr/bin/env bash
set -euo pipefail

CHECK_RECIPE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PHYSICAL_ROOT=/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a
PHYSICAL_BUILD_COMMIT=aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795
ROOT="${VAST_REPAIR_CHECK_ROOT:-$PHYSICAL_ROOT}"
OLD_ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
RUNTIME=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1
CHECK_BASE="$ROOT/artifacts/accepted_policy_repair_20261011a/checks-01"

assert_frozen_root() {
  local expected="$1"
  [[ "$expected" =~ ^[0-9a-f]{40}$ ]]
  [[ "$ROOT" == "$PHYSICAL_ROOT" || "$ROOT" == /home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-"$expected" ]]
  [[ "$(id -u)" == 1000 && "$HOME" == /home/s-a-balashov ]]
  [[ "$(realpath -e "$ROOT")" == "$ROOT" && -x "$PY" ]]
  if [[ "$ROOT" != "$PHYSICAL_ROOT" ]]; then
    [[ "$(findmnt -rn -T "$ROOT" -o FSTYPE)" == ext4 ]]
  fi
  [[ "$(git -C "$ROOT" rev-parse HEAD)" == "$expected" ]]
  [[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]
  [[ "$CHECK_RECIPE_DIR" == "$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01" ]]
}

assert_committed_bytes() {
  "$PY" -B - "$1" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(root / "scripts"))
import run_ci_checks
run_ci_checks.verify_committed_bytes(root, run_ci_checks.tracked_paths(root))
PY
}

assert_nine_ids() {
  "$PY" -B - "$ROOT" "$CHECK_RECIPE_DIR/integration-test-ids.txt" <<'PY'
import json
import sys
from pathlib import Path
root, ids_path = map(Path, sys.argv[1:])
ids = ids_path.read_text(encoding="ascii").splitlines()
document = json.loads((root / ".ci/integration-test-selection.v1.json").read_bytes())
declared = sorted(row["test_id"] for row in document["integration_declarations"])
if len(ids) != 9 or len(set(ids)) != 9 or ids != declared:
    raise RuntimeError("nine integration IDs differ from the committed CI selection")
PY
}
