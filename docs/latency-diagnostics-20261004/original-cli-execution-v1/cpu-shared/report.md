# Retained component latency diagnostic

Diagnostic only. Qualification/publication/full campaign/Q4 readiness remain false.

Recorded run: qualification-v2-gstreamer_custom-cpu-h264-shared-video-dag; cohort: qualification-v2-gstreamer_custom-cpu-h264-shared-video-dag:measurement:1791016140521:1791016320521.
Observed topology: shared_video_dag; observed branches: damage, foreign_object, plate_number, vehicle_type.
The branch set is inferred from retained outcomes and does not certify a declared DAG.

Admissions 1080; completed 664; dropped 416; censored 0.
Branch completions 3371; branch drops 949.
Completed coverage 0.614815; caller deadline 100 ms; completed misses 664.

Quantiles use linear interpolation at q*(n-1), for completed frames only. Prefix + residual is verified per frame; marginal quantiles are not additive.

- End-to-end latency: count=664, p50=3621, p95=8026.85, p99=8160.37; reason=None.
- Ingress-to-decoder envelope: count=664, p50=1237.5, p95=6216, p99=6238.59; reason=None.
- Decoder-to-frame-join envelope: count=664, p50=1926, p95=2617.1, p99=2851.85; reason=None.
- Per-frame decoder share: count=664, p50=0.415472552763942, p95=0.8292605768498486, p99=0.8531182397879454; reason=None.

Stage and recorded queue spans (all retained stage rows):

- aggregate: parent-to-completion envelope count=664, p50/p95/p99=2/3/4 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- damage: parent-to-completion envelope count=856, p50/p95/p99=1703.5/2564/2746.8 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode: parent-to-completion envelope count=1080, p50/p95/p99=2006/6030.05/6235 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- foreign_object: parent-to-completion envelope count=794, p50/p95/p99=1777.5/2570.75/2732.19 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- plate_number: parent-to-completion envelope count=866, p50/p95/p99=1691/2523.5/2762.05 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_damage: parent-to-completion envelope count=856, p50/p95/p99=1/1/1 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_foreign_object: parent-to-completion envelope count=794, p50/p95/p99=1/1/2 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_plate_number: parent-to-completion envelope count=866, p50/p95/p99=1/1/1 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_vehicle_type: parent-to-completion envelope count=855, p50/p95/p99=1/1/1.46 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess: parent-to-completion envelope count=1080, p50/p95/p99=3/4/4 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- record: parent-to-completion envelope count=664, p50/p95/p99=0/0/0 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- vehicle_type: parent-to-completion envelope count=855, p50/p95/p99=1692/2526.3/2733.9 ms; recorded queue span p50/p95/p99=0/0/0 ms.

Native policy paths:

Population: measured_completed_branch_paths_including_dropped_frames; count=3371.
Native timestamps have millisecond CSV comparison resolution; terminal may precede postprocess. Carried actual_service_ms is checked against terminal-minus-path with 0.001 ms serialization tolerance; both remain path envelopes, not pure inference service.

- damage carried_actual_service_ms: count=856, p50/p95/p99=1278.782187/1458.5652505/1578.2048576 ms; native path envelopes include waits/execution.
- damage native_terminal_to_postprocess_ms: count=856, p50/p95/p99=-0.51355/-0.048/-0.00644 ms; native path envelopes include waits/execution.
- damage parent_to_path_ms: count=856, p50/p95/p99=410.9875/1207.1426/1346.940625 ms; native path envelopes include waits/execution.
- damage path_to_terminal_ms: count=856, p50/p95/p99=1278.78225/1458.565325/1578.204795 ms; native path envelopes include waits/execution.
- foreign_object carried_actual_service_ms: count=794, p50/p95/p99=1292.6994445/1439.3008255/1539.83468786 ms; native path envelopes include waits/execution.
- foreign_object native_terminal_to_postprocess_ms: count=794, p50/p95/p99=-0.45825/-0.038055/-0.003825 ms; native path envelopes include waits/execution.
- foreign_object parent_to_path_ms: count=794, p50/p95/p99=477.4404/1233.95826/1329.948469 ms; native path envelopes include waits/execution.
- foreign_object path_to_terminal_ms: count=794, p50/p95/p99=1292.6994/1439.300875/1539.834713 ms; native path envelopes include waits/execution.
- plate_number carried_actual_service_ms: count=866, p50/p95/p99=1282.2778235/1454.613349/1584.4842979 ms; native path envelopes include waits/execution.
- plate_number native_terminal_to_postprocess_ms: count=866, p50/p95/p99=-0.39/-0.0354/-0.00945 ms; native path envelopes include waits/execution.
- plate_number parent_to_path_ms: count=866, p50/p95/p99=407.3062/1183.5926/1297.02958 ms; native path envelopes include waits/execution.
- plate_number path_to_terminal_ms: count=866, p50/p95/p99=1282.27795/1454.613575/1584.48417 ms; native path envelopes include waits/execution.
- vehicle_type carried_actual_service_ms: count=855, p50/p95/p99=1281.896304/1455.8721464/1563.69415392 ms; native path envelopes include waits/execution.
- vehicle_type native_terminal_to_postprocess_ms: count=855, p50/p95/p99=-0.4631/-0.04619/-0.001878 ms; native path envelopes include waits/execution.
- vehicle_type parent_to_path_ms: count=855, p50/p95/p99=416.8296/1162.92274/1265.604998 ms; native path envelopes include waits/execution.
- vehicle_type path_to_terminal_ms: count=855, p50/p95/p99=1281.8963/1455.8724/1563.694136 ms; native path envelopes include waits/execution.

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

- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-shared-video-dag/evidence/frames.csv (168947 bytes; SHA256 ad873819e62f5abd176ea88da9a18fb94b41e15a59f0c794c292a46e4672ba23).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-shared-video-dag/evidence/ingress_ledger.csv (734631 bytes; SHA256 fb4f2c9680a4d99672f7f8b7356d625b44016c70e5266713f731b145c451b80a).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-shared-video-dag/evidence/branch_terminals.csv (2756398 bytes; SHA256 8a141bab3d67cb94c1139ccbdc49ec37b790b10c2a2b80e5635946ac0a5bf152).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-shared-video-dag/evidence/frame_events.csv (3464477 bytes; SHA256 ed9c746d2caa0f5978ef678c74353a2ffc9d33951f504fa1b9efe351f0ba0143).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/cpu-pair-08/operations/arms/component-gstreamer_custom-cpu-h264-shared-video-dag/evidence/publication_policy_decisions.jsonl (15914290 bytes; SHA256 e07f2088f24b158852f862ce5011c9f30bb6f55bf468ea9a0eaded52f8b0b329).
