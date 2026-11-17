set -u
W=/mnt/c/Users/s-a-balashov/.codex/worktrees/qfb-clock/VAST
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
T=$(mktemp -d /tmp/vast-gate-red.XXXXXX)
cd "$W"
mkdir -p "$T/tests" && cp tests/test_legacy_wall_clock_static_gate_v1.py "$T/tests/"
for f in scripts/checkpoint_deepstream_sdk_runtime.py scripts/checkpoint_deepstream_protocol_bridge.py scripts/checkpoint_savant_sdk_runtime_v3.py scripts/publication_guardian_operational_recorder_v1.py; do cp --parents "$f" "$T"; done
find deploy -name 'Dockerfile*' -exec cp --parents {} "$T" \;
# Injected violations in the temporary copy only: the recorder default reads raw CLOCK_REALTIME
# again, and the native OpenVINO Dockerfile no longer copies the clock header.
sed -i 's/clock_ns: Callable\[\[\], int\] = wall_time_ns)/clock_ns: Callable[[], int] = time.time_ns)/' "$T/scripts/publication_guardian_operational_recorder_v1.py"
sed -i '/checkpoint_admission_transport.hpp/d' "$T/deploy/native_gst_probe/Dockerfile.openvino"
echo "# temporary copy: $T"
diff -r "$W/scripts/publication_guardian_operational_recorder_v1.py" "$T/scripts/publication_guardian_operational_recorder_v1.py"
diff "$W/deploy/native_gst_probe/Dockerfile.openvino" "$T/deploy/native_gst_probe/Dockerfile.openvino"
cd "$T" && $PY -m unittest -v tests.test_legacy_wall_clock_static_gate_v1 2>&1
rm -rf "$T"
