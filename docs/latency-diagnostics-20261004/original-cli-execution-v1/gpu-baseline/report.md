# Retained component latency diagnostic

Diagnostic only. Qualification/publication/full campaign/Q4 readiness remain false.

Recorded run: qualification-v2-gstreamer_custom-gpu-h264-independent-processes; cohort: qualification-v2-gstreamer_custom-gpu-h264-independent-processes:measurement:1791017845725:1791018025725.
Observed topology: independent_processes; observed branches: damage, foreign_object, plate_number, vehicle_type.
The branch set is inferred from retained outcomes and does not certify a declared DAG.

Admissions 1080; completed 1070; dropped 10; censored 0.
Branch completions 4295; branch drops 25.
Completed coverage 0.990741; caller deadline 100 ms; completed misses 1067.

Quantiles use linear interpolation at q*(n-1), for completed frames only. Prefix + residual is verified per frame; marginal quantiles are not additive.

- End-to-end latency: count=1070, p50=2127, p95=6301, p99=6320; reason=None.
- Ingress-to-decoder envelope: count=1070, p50=2010, p95=6035, p99=6040; reason=None.
- Decoder-to-frame-join envelope: count=1070, p50=120, p95=272, p99=297; reason=None.
- Per-frame decoder share: count=1070, p50=0.9322881128412704, p95=0.9738003917395686, p99=0.9896201723178261; reason=None.

Stage and recorded queue spans (all retained stage rows):

- aggregate: parent-to-completion envelope count=1070, p50/p95/p99=4/10/21.31 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- damage: parent-to-completion envelope count=1073, p50/p95/p99=76/245.4/270.56 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_damage: parent-to-completion envelope count=1080, p50/p95/p99=2010/6031/6037 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_foreign_object: parent-to-completion envelope count=1080, p50/p95/p99=2009/6032.05/6038.21 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_plate_number: parent-to-completion envelope count=1080, p50/p95/p99=2009/6033.05/6038.21 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode_vehicle_type: parent-to-completion envelope count=1080, p50/p95/p99=2010/6032/6037.21 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- foreign_object: parent-to-completion envelope count=1074, p50/p95/p99=84/253/284 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- plate_number: parent-to-completion envelope count=1075, p50/p95/p99=69/233/256 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_damage: parent-to-completion envelope count=1073, p50/p95/p99=7/32.4/196.28 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_foreign_object: parent-to-completion envelope count=1074, p50/p95/p99=9/54/192.27 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_plate_number: parent-to-completion envelope count=1075, p50/p95/p99=5/17/191.04 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_vehicle_type: parent-to-completion envelope count=1073, p50/p95/p99=7/29/192.24 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_damage: parent-to-completion envelope count=1079, p50/p95/p99=4/10/16.22 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_foreign_object: parent-to-completion envelope count=1080, p50/p95/p99=4/10/15 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_plate_number: parent-to-completion envelope count=1080, p50/p95/p99=4/10.05/18 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess_vehicle_type: parent-to-completion envelope count=1080, p50/p95/p99=4/10/16 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- record: parent-to-completion envelope count=1070, p50/p95/p99=0/0/0 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- vehicle_type: parent-to-completion envelope count=1073, p50/p95/p99=74/240.4/266.56 ms; recorded queue span p50/p95/p99=0/0/0 ms.

Native policy paths:

Population: measured_completed_branch_paths_including_dropped_frames; count=4295.
Native timestamps have millisecond CSV comparison resolution; terminal may precede postprocess. Carried actual_service_ms is checked against terminal-minus-path with 0.001 ms serialization tolerance; both remain path envelopes, not pure inference service.

- damage carried_actual_service_ms: count=1073, p50/p95/p99=63.051995/245.1084318/266.2773 ms; native path envelopes include waits/execution.
- damage native_terminal_to_postprocess_ms: count=1073, p50/p95/p99=-0.4885/-0.0516/-0.007944 ms; native path envelopes include waits/execution.
- damage parent_to_path_ms: count=1073, p50/p95/p99=6.3696/80.40504/116.483248 ms; native path envelopes include waits/execution.
- damage path_to_terminal_ms: count=1073, p50/p95/p99=63.0521/245.1085/266.27746 ms; native path envelopes include waits/execution.
- foreign_object carried_actual_service_ms: count=1074, p50/p95/p99=69.774121/251.82371885/278.95415697 ms; native path envelopes include waits/execution.
- foreign_object native_terminal_to_postprocess_ms: count=1074, p50/p95/p99=-0.50425/-0.04413/-0.00746 ms; native path envelopes include waits/execution.
- foreign_object parent_to_path_ms: count=1074, p50/p95/p99=6.03525/92.190005/125.363558 ms; native path envelopes include waits/execution.
- foreign_object path_to_terminal_ms: count=1074, p50/p95/p99=69.77425/251.82353/278.95423 ms; native path envelopes include waits/execution.
- plate_number carried_actual_service_ms: count=1075, p50/p95/p99=58.169495/232.9263497/247.54405374 ms; native path envelopes include waits/execution.
- plate_number native_terminal_to_postprocess_ms: count=1075, p50/p95/p99=-0.4956/-0.06115/-0.01791 ms; native path envelopes include waits/execution.
- plate_number parent_to_path_ms: count=1075, p50/p95/p99=6.6482/72.89324/88.536476 ms; native path envelopes include waits/execution.
- plate_number path_to_terminal_ms: count=1075, p50/p95/p99=58.1695/232.92631/247.544172 ms; native path envelopes include waits/execution.
- vehicle_type carried_actual_service_ms: count=1073, p50/p95/p99=61.763376/241.7332536/259.75992248 ms; native path envelopes include waits/execution.
- vehicle_type native_terminal_to_postprocess_ms: count=1073, p50/p95/p99=-0.4998/-0.04612/-0.0066 ms; native path envelopes include waits/execution.
- vehicle_type parent_to_path_ms: count=1073, p50/p95/p99=6.1902/76.21292/93.718788 ms; native path envelopes include waits/execution.
- vehicle_type path_to_terminal_ms: count=1073, p50/p95/p99=61.7634/241.73358/259.75994 ms; native path envelopes include waits/execution.

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

- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-independent-processes/evidence/frames.csv (282852 bytes; SHA256 dafab9add58d980a88ac35e09c44219b95968b09cb32550caa94734a728a848e).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-independent-processes/evidence/ingress_ledger.csv (749622 bytes; SHA256 218203ecaff1fea88e9865237428ebcdfe94f08640cb0b5d2f4a1513184e73f5).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-independent-processes/evidence/branch_terminals.csv (3035390 bytes; SHA256 8a6364e28e9087c83ad6c902b08cd588767a2a0662e6fb197c3efddd96891ab7).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-independent-processes/evidence/frame_events.csv (6663972 bytes; SHA256 729a46e61d0b694250ed273ea3b708868e0ce978a3515e8b8a0ef8b7bb78d458).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-independent-processes/evidence/publication_policy_decisions.jsonl (20723574 bytes; SHA256 f0f4160be6f1f9fddbdd62d3f77d6c19e264ff59baaffee65ae3df0441dbfec8).
