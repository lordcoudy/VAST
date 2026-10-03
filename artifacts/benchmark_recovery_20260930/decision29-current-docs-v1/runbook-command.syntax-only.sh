ROOT=/home/s-a-balashov/work/vast-component-release-20260930-d27
PYTHON=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
CAPABILITY="$ROOT/artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/candidate/checkpoint_policy_capability_candidate_manifest.json"
CALIBRATION="$ROOT/artifacts/publication_policy_qualification_v2_fix_benchmark_20260928g/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.gstreamer_custom.v2.json"
MODEL="$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-20260928g.accepted.acceptance_receipt.json"
IMAGE="$ROOT/artifacts/benchmark_recovery_20260930/decision28-gstreamer-build-2a6a42c9-v1/gstreamer_custom.runtime.freeze.json"
WORKERS="$ROOT/artifacts/fix_benchmark_preparations_20260928g/worker_images/analytics-worker.freeze.json"
CLOSURE="$ROOT/artifacts/gstreamer_component_release_20260930_a4e145b7/host/execution-code-closure.ext4-decision28.v4.json"
RESOURCE=cpu
OUTPUT="$ROOT/artifacts/gstreamer-component-local/cpu-pair-new"
ENTRY="import runpy,sys;sys.path.insert(0,sys.argv[1]+'/scripts');root=sys.argv.pop(1);runpy.run_path(root+'/scripts/publication_gstreamer_component_cli_v1.py',run_name='__main__')"
"$PYTHON" -I -B -c "$ENTRY" "$ROOT" \
  --project-root "$ROOT" --resource "$RESOURCE" --output-dir "$OUTPUT" \
  --scratch-root /tmp --container-engine /usr/bin/docker \
  --container-engine-socket /run/docker.sock \
  --capability-manifest-path "$CAPABILITY" --calibration-path "$CALIBRATION" \
  --model-parity-receipt-path "$MODEL" --runtime-image-receipt-path "$IMAGE" \
  --worker-freeze-receipt-path "$WORKERS" --execution-code-closure-path "$CLOSURE"
