#!/bin/bash
# Amendment10: attempt J only (stock study, human decision 2026-10-06). Relative material args.
set -u
COMMIT=$1; CIDIR=$2; ATTEMPT=$3; OP=study
ROOT=/home/s-a-balashov/vf${COMMIT:0:7}J
[ "$ATTEMPT" = J ] || { echo "only attempt J is authorized" >&2; exit 89; }
[ -z "$(/usr/bin/docker ps -aq --filter label=vast.finite-study)" ] || { echo "study containers still present" >&2; exit 91; }
! pgrep -f "scripts/run_canonical_systems_study_v1.py" >/dev/null || { echo "study process still running" >&2; exit 92; }
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
T=/mnt/e/STUDY/VAST/tmp/finite-component-study-20261005
L=$T/launch-${ATTEMPT}-v1-logs
mkdir -p "$L"
echo "commit=$COMMIT root=$ROOT launch_monotonic_ns=$($PY -c 'import time;print(time.monotonic_ns())')" > "$L/launch.txt"
"$PY" -I -B "$T/bootstrap-private-current-root-v7.py" --commit "$COMMIT" --attempt-id "$ATTEMPT" \
  --ci-proof "$T/$CIDIR/original-provider-metadata.v1.json" \
  --project-root "$ROOT" --source-root /home/s-a-balashov/work/vast-component-release-20260930-d27 \
  > "$L/bootstrap.stdout" 2> "$L/bootstrap.stderr"
RC=$?; echo "bootstrap_rc=$RC" >> "$L/launch.txt"
[ $RC -eq 0 ] || exit $RC
read START BOOT TNS < <("$PY" -c "import json;c=json.load(open('$ROOT/b/preparation-clock.original.json'));print(c['started_monotonic_ns'],c['boot_id'],c['time_namespace'])")
echo "attempt=$ATTEMPT op=$OP started=$START boot=$BOOT domain=$TNS" >> "$L/launch.txt"
A=artifacts
"$PY" -I -B "$ROOT/scripts/run_canonical_systems_study_v1.py" "$OP" --project-root "$ROOT" --output-dir "$ROOT/s" \
  --engine /usr/bin/docker --engine-socket /run/docker.sock \
  --capability-manifest "$A/publication_policy_qualification_v2_fix_benchmark_20260928g/candidate/checkpoint_policy_capability_candidate_manifest.json" \
  --calibration "$A/publication_policy_qualification_v2_fix_benchmark_20260928g/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.gstreamer_custom.v2.json" \
  --model-parity-receipt "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json" \
  --worker-freeze-receipt "$A/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json" \
  --execution-code-closure "b/current-code-closure.original.json" \
  --front-gate /mnt/e/STUDY/VAST/data/videos/kpp/kpp_legacy_iss_v2/avi/iss_v2_front_gate.avi \
  --underbody /mnt/e/STUDY/VAST/data/videos/kpp/kpp_legacy_iss_v2/avi/iss_v2_underbody.avi \
  --preparation-started-monotonic-ns "$START" --preparation-boot-id "$BOOT" --preparation-time-namespace "$TNS" \
  > "$L/study.stdout" 2> "$L/study.stderr"
RC=$?; echo "study_rc=$RC closed_monotonic_ns=$($PY -c 'import time;print(time.monotonic_ns())')" >> "$L/launch.txt"
exit $RC
