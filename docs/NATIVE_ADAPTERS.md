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

For `--mode benchmark`, define `DISTRIBUTED_NATIVE_CMD` in the environment of
each host inventory entry. The command receives:

- `EXPERIMENT_HOST_ROLE`
- `EXPERIMENT_PIPELINE_STAGES`
- `EXPERIMENT_RTP_INPUT_PORT` when the role consumes RTP
- `EXPERIMENT_RTP_OUTPUT_HOST` and `EXPERIMENT_RTP_OUTPUT_PORT` when the role
  produces RTP
- `EXPERIMENT_TRACE_METADATA=rtp_header_extension`

The role command must process only the assigned stages. It must propagate
`trace_id`, `stream_id`, `frame_id`, and the original edge ingress timestamp
through an RTP header extension. The aggregator writes E2E `frames.csv`; every
role writes `frame_events.csv`.

The common RTP bridge in `scripts/run_system_template.sh` is intentionally
restricted to `--mode smoke`. It verifies transport wiring but does not satisfy
the native inference or trace propagation contract.

## Acceptance

A distributed benchmark run is rejected when:

- `chronyc tracking` reports more than 5 ms offset on any role;
- required public dataset checksums are absent or invalid;
- the aggregator does not write E2E `frames.csv`;
- any role omits `frame_events.csv` or `system_metrics.csv`;
- any frame row is synthetic, legacy, malformed, or has a duplicate trace ID.
