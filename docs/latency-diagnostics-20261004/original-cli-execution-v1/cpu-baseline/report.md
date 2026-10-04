# Retained component latency diagnostic

Diagnostic only. Qualification/publication/full campaign/Q4 readiness remain false.

Recorded run: qualification-v2-gstreamer_custom-cpu-h264-independent-processes; cohort: qualification-v2-gstreamer_custom-cpu-h264-independent-processes:measurement:1791015830490:1791016010490.
Observed topology: independent_processes; observed branches: damage, foreign_object, plate_number, vehicle_type.
The branch set is inferred from retained outcomes and does not certify a declared DAG.

Admissions 1080; completed 516; dropped 564; censored 0.
Branch completions 3556; branch drops 764.
Completed coverage 0.477778; caller deadline 100 ms; completed misses 516.

Quantiles use linear interpolation at q*(n-1), for completed frames only. Prefix + residual is verified per frame; marginal quantiles are not additive.

- End-to-end latency: count=516, p50=5727.5, p95=9713.25, p99=9976.2; reason=None.
- Ingress-to-decoder envelope: count=516, p50=2071.5, p95=6361.25, p99=6390; reason=None.
- Decoder-to-frame-join envelope: count=516, p50=3113, p95=3965.25, p99=4145.85; reason=None.
- Per-frame decoder share: count=516, p50=0.382770588757073, p95=0.7573587077742202, p99=0.8054319179892735; reason=None.

Stage and recorded queue spans (all retained stage rows):

- aggregate: parent-to-completion envelope count=516, p50/p95/p99=2/4/11.85 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- damage: parent-to-completion envelope count=961, p50/p95/p99=1105/2020/2205 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_damage: parent-to-completion envelope count=1080, p50/p95/p99=2017/6036/6383.21 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_foreign_object: parent-to-completion envelope count=1080, p50/p95/p99=2017.5/6037/6383.84 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_plate_number: parent-to-completion envelope count=1080, p50/p95/p99=2015.5/6035/6381.21 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_vehicle_type: parent-to-completion envelope count=1080, p50/p95/p99=2015/6036/6379.42 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- foreign_object: parent-to-completion envelope count=553, p50/p95/p99=3155/4004.6/4177.48 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- plate_number: parent-to-completion envelope count=1074, p50/p95/p99=428/1007/1199.54 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_damage: parent-to-completion envelope count=961, p50/p95/p99=1/1/2 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_foreign_object: parent-to-completion envelope count=553, p50/p95/p99=1/2/2 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_plate_number: parent-to-completion envelope count=1074, p50/p95/p99=1/2/2 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_vehicle_type: parent-to-completion envelope count=968, p50/p95/p99=1/1/2 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_damage: parent-to-completion envelope count=1080, p50/p95/p99=4/11/16 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_foreign_object: parent-to-completion envelope count=1079, p50/p95/p99=4/11/18 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_plate_number: parent-to-completion envelope count=1080, p50/p95/p99=4/10/15 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_vehicle_type: parent-to-completion envelope count=1079, p50/p95/p99=4/10/16 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- record: parent-to-completion envelope count=516, p50/p95/p99=0/0/0 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- vehicle_type: parent-to-completion envelope count=968, p50/p95/p99=1104/1988.65/2202.97 ms; recorded queue span p50/p95/p99=0/0/0 ms.

Native policy paths:

Population: measured_completed_branch_paths_including_dropped_frames; count=3556.
Native timestamps have millisecond CSV comparison resolution; terminal may precede postprocess. Carried actual_service_ms is checked against terminal-minus-path with 0.001 ms serialization tolerance; both remain path envelopes, not pure inference service.

- damage carried_actual_service_ms: count=961, p50/p95/p99=901.980294/1193.931034/1303.497569 ms; native path envelopes include waits/execution.
- damage native_terminal_to_postprocess_ms: count=961, p50/p95/p99=-0.4944/-0.046/-0.00212 ms; native path envelopes include waits/execution.
- damage parent_to_path_ms: count=961, p50/p95/p99=58.5964/1006.6724/1166.33664 ms; native path envelopes include waits/execution.
- damage path_to_terminal_ms: count=961, p50/p95/p99=901.9803/1193.9314/1303.4977 ms; native path envelopes include waits/execution.
- foreign_object carried_actual_service_ms: count=553, p50/p95/p99=1960.625098/2271.2533314/2366.0672144 ms; native path envelopes include waits/execution.
- foreign_object native_terminal_to_postprocess_ms: count=553, p50/p95/p99=-0.493/-0.05318/-0.00978 ms; native path envelopes include waits/execution.
- foreign_object parent_to_path_ms: count=553, p50/p95/p99=1264.2866/2070.96624/2189.673664 ms; native path envelopes include waits/execution.
- foreign_object path_to_terminal_ms: count=553, p50/p95/p99=1960.625/2271.25344/2366.067032 ms; native path envelopes include waits/execution.
- plate_number carried_actual_service_ms: count=1074, p50/p95/p99=416.916223/621.8714928/642.08111314 ms; native path envelopes include waits/execution.
- plate_number native_terminal_to_postprocess_ms: count=1074, p50/p95/p99=-0.50065/-0.04561/-0.006811 ms; native path envelopes include waits/execution.
- plate_number parent_to_path_ms: count=1074, p50/p95/p99=4.46985/485.799895/596.598719 ms; native path envelopes include waits/execution.
- plate_number path_to_terminal_ms: count=1074, p50/p95/p99=416.9163/621.87157/642.080969 ms; native path envelopes include waits/execution.
- vehicle_type carried_actual_service_ms: count=968, p50/p95/p99=893.0331755/1181.2895238/1295.11441868 ms; native path envelopes include waits/execution.
- vehicle_type native_terminal_to_postprocess_ms: count=968, p50/p95/p99=-0.49285/-0.043225/-0.004204 ms; native path envelopes include waits/execution.
- vehicle_type parent_to_path_ms: count=968, p50/p95/p99=54.49075/998.3426/1140.369661 ms; native path envelopes include waits/execution.
- vehicle_type path_to_terminal_ms: count=968, p50/p95/p99=893.03305/1181.28947/1295.114256 ms; native path envelopes include waits/execution.

Unknown components:

- true_queue_wait_ms: null (promoted_queue_enter_and_start_do_not_observe_native_queue_boundaries).
- pure_inference_service_ms: null (stage_and_native_path_envelopes_include_preparation_transport_waits_and_execution).
- nvdec_busy_ms: null (ingress_to_decoder_completion_is_residence_envelope_not_hardware_busy_time).

Scientific limits:

- Recorded branch set does not certify the declared DAG or experiment acceptance.
- Completed-frame latency excludes dropped/censored frames; branch outcomes have separate denominators.
- Prefix plus residual equals latency per frame; marginal quantiles must not be added.
- Promoted stages are parent-to-completion envelopes; recorded zero queue spans do not prove zero queue wait.
- Native paths include preparation, transport, mapping/hash, waits and execution; carried actual_service_ms is not pure inference service.
- Decoder residence is not NVDEC busy time or proof of reorder/display/hardware causation.
- Overlapping partial C_obs is not work, energy or causal speedup; different completed subsets and baseline-first ordering remain confounders.
- Original deadlines, drops, workloads and source evidence are unchanged; no cold/full/Q4/publication authority is granted.

Exact input provenance:

- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-independent-processes/evidence/frames.csv (136512 bytes; SHA256 9bfcb7ed4e67b0f29a37bdb19156b817112b62e927a13491f3052ba245121145).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-independent-processes/evidence/ingress_ledger.csv (751336 bytes; SHA256 68cb1ec93a68034fc98edb67b4b7f5d28dfb6bd4584061fddd54ce10536e09b8).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-independent-processes/evidence/branch_terminals.csv (2839161 bytes; SHA256 425558c03c0abeefd823e741e3bebeffbb2a3016fe28a984312f4584dff0243a).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-independent-processes/evidence/frame_events.csv (5771832 bytes; SHA256 08636bd285d170fbc4b7fc6d48bd0f3fca8bbc802b8082334085c812335967b3).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-independent-processes/evidence/publication_policy_decisions.jsonl (17037969 bytes; SHA256 1e36877ae2831d705b7301000107636219f9d8727232f5e300bc6d542528afad).
