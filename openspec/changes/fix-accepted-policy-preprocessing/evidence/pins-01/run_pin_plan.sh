#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
set -o noclobber
case "${1:?inventory-plan | render | apply PLAN_SHA256}" in
  inventory-plan)
    "$PY" -B "$HERE/repair_pin_plan.py" inventory > "$HERE/host-pin-rebind.inventory.v1.json"
    "$PY" -B "$HERE/repair_pin_plan.py" plan > "$HERE/host-pin-rebind.plan.v1.json"
    ;;
  render)
    "$PY" -B "$HERE/repair_pin_plan.py" render > "$HERE/host-pin-rebind.review.v1.json"
    ;;
  apply)
    "$PY" -B "$HERE/repair_pin_plan.py" apply "${2:?reviewed plan SHA required}" > "$HERE/host-pin-rebind.applied.v1.json"
    ;;
  *) exit 64 ;;
esac
