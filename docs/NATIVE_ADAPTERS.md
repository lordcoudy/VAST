# Native adapter contract

Publishable `--mode benchmark` runs require each adapter to write schema-v2
telemetry directly from its pipeline probes. The harness intentionally refuses
to derive scientific metrics from process duration.

## Local adapters

Each configured system command receives:

- `EXPERIMENT_RUN_ID`
- `EXPERIMENT_SCENARIO_JSON`
- `EXPERIMENT_PIPELINE_STAGES`
- `SCHEDULER_POLICY`
- `ADAPTER_DETECTOR`
- `ADAPTER_BACKEND`
- `VIDEO_LAYOUT_DIR`
- `DATASET_STREAMS_JSON`
- `EXPERIMENT_RUN_SEED`

The command must write:

- `frames.csv`: one row per completed frame using the columns defined in
  `scripts/benchmark_contract.py::FRAME_COLUMNS`
- `frame_events.csv`: one row per stage execution using
  `scripts/benchmark_contract.py::FRAME_EVENT_COLUMNS`

DeepStream and Savant adapters should use GStreamer pad probes. OpenVINO+GVA
and GStreamer custom adapters should use source/sink pad probes. The custom
CUDA+Qt adapter writes both files directly.

## Distributed adapters

The SSH executor launches roles in this order:

1. `aggregator`
2. `gpu_worker`
3. `edge`

For `--mode benchmark`, the built-in strict role commands support
`canonical_distributed` for DeepStream, Savant, OpenVINO+GVA, and
GStreamer custom. Host inventories may still override them with
`DISTRIBUTED_NATIVE_CMD_<SYSTEM>_<ROLE>` or the generic `DISTRIBUTED_NATIVE_CMD`
fallback for custom deployments. The command receives:

- `EXPERIMENT_HOST_ROLE`
- `EXPERIMENT_PIPELINE_STAGES`
- `EXPERIMENT_RTP_INPUT_PORT` when the role consumes RTP
- `EXPERIMENT_RTP_OUTPUT_HOST` and `EXPERIMENT_RTP_OUTPUT_PORT` when the role
  produces RTP
- `EXPERIMENT_TRACE_METADATA=rtp_header_extension`
- `EXPERIMENT_RTP_PORT_STRIDE`, default `1`

The role command must process only the assigned stages. It must propagate
`trace_id`, `stream_id`, `frame_id`, and the original edge ingress timestamp
through an RTP header extension. The aggregator writes E2E `frames.csv`; every
role writes `frame_events.csv`.

The canonical transport uses one UDP port per stream:

- edge to worker: `transport.role_ports.edge_to_gpu_worker + stream_id * stream_port_stride`
- worker to aggregator: `transport.role_ports.gpu_worker_to_aggregator + stream_id * stream_port_stride`

The native RTP trace header extension uses extension id `1` and URI
`urn:vast:rtp-trace:v1`. Its payload is 16 bytes:
`magic:u16`, `version:u8`, `stream_id:u8`, `frame_id:u32`,
`ingress_timestamp_ms:u64`, all encoded big-endian. The same serializer lives in
`scripts/rtp_trace.py` for tests and non-C++ tooling.

`vast_native_gst_probe` is the common non-CUDA runtime for edge/aggregator
roles and for host OpenVINO/GStreamer custom worker roles. Build it with:

```bash
cmake -S . -B build/cmake -DVAST_BUILD_NATIVE_GST_PROBE=ON -DVAST_BUILD_CUSTOM_CUDA_QT=OFF
cmake --build build/cmake --target vast_native_gst_probe
```

Containerized DeepStream and Savant roles use derived images:

```bash
scripts/build_native_probe_images.sh
```

Defaults:

- `vast/deepstream-native-probe:7.0`, based on `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`
- `vast/savant-native-probe:0.5.17-7.0`, based on `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0`
- Savant `gpu_worker` runs `python -m savant.entrypoint deploy/savant/canonical_distributed_module.yml`
- OpenVINO+GVA requires `gvadetect` or `object_detect`
- GStreamer custom requires `GST_CUSTOM_STRICT=1` and the configured plugin in `GST_PLUGIN_PATH`

The common RTP bridge in `scripts/run_system_template.sh` is intentionally
restricted to `--mode smoke`. It verifies transport wiring but does not satisfy
the native inference or trace propagation contract.

`--run-kind single-server-distributed` still uses SSH role launches, but all
roles target one server. The executor disables project sync and records
`same_host_loopback` network metrics instead of requiring chrony/ping/iperf
preflight between separate hosts.

## Acceptance

A distributed benchmark run is rejected when:

- `chronyc tracking` reports more than 5 ms offset on any role;
- required public dataset checksums are absent or invalid;
- the aggregator does not write E2E `frames.csv`;
- any role omits `frame_events.csv` or `system_metrics.csv`;
- any frame row is synthetic, legacy, malformed, or has a duplicate trace ID;
- any completed frame lacks native events for a required pipeline stage.
