# Retained component latency diagnostic

Diagnostic only. Qualification/publication/full campaign/Q4 readiness remain false.

Recorded run: qualification-v2-gstreamer_custom-gpu-h264-shared-video-dag; cohort: qualification-v2-gstreamer_custom-gpu-h264-shared-video-dag:measurement:1791018162560:1791018342560.
Observed topology: shared_video_dag; observed branches: damage, foreign_object, plate_number, vehicle_type.
The branch set is inferred from retained outcomes and does not certify a declared DAG.

Admissions 1080; completed 1075; dropped 5; censored 0.
Branch completions 4300; branch drops 20.
Completed coverage 0.99537; caller deadline 100 ms; completed misses 1074.

Quantiles use linear interpolation at q*(n-1), for completed frames only. Prefix + residual is verified per frame; marginal quantiles are not additive.

- End-to-end latency: count=1075, p50=2168, p95=6364, p99=6391.26; reason=None.
- Ingress-to-decoder envelope: count=1075, p50=2006, p95=6016, p99=6018; reason=None.
- Decoder-to-frame-join envelope: count=1075, p50=152, p95=381, p99=445; reason=None.
- Per-frame decoder share: count=1075, p50=0.9193840579710145, p95=0.9707781724249274, p99=0.97886431457231; reason=None.

Stage and recorded queue spans (all retained stage rows):

- aggregate: parent-to-completion envelope count=1075, p50/p95/p99=2/5/6 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- damage: parent-to-completion envelope count=1075, p50/p95/p99=87/356/406.04 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- decode: parent-to-completion envelope count=1080, p50/p95/p99=2005/6015/6018 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- foreign_object: parent-to-completion envelope count=1075, p50/p95/p99=97/361.3/418.26 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- plate_number: parent-to-completion envelope count=1075, p50/p95/p99=74/348/409.26 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_damage: parent-to-completion envelope count=1075, p50/p95/p99=5/31/253.04 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_foreign_object: parent-to-completion envelope count=1075, p50/p95/p99=7/45.3/246.78 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_plate_number: parent-to-completion envelope count=1075, p50/p95/p99=3/17.3/248.78 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- postprocess_vehicle_type: parent-to-completion envelope count=1075, p50/p95/p99=5/27.3/237.78 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- preprocess: parent-to-completion envelope count=1080, p50/p95/p99=3/4/5 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- record: parent-to-completion envelope count=1075, p50/p95/p99=0/0/0 ms; recorded queue span p50/p95/p99=0/0/0 ms.
- vehicle_type: parent-to-completion envelope count=1075, p50/p95/p99=82/357.3/419.26 ms; recorded queue span p50/p95/p99=0/0/0 ms.

Native policy paths:

Population: measured_completed_branch_paths_including_dropped_frames; count=4300.
Native timestamps have millisecond CSV comparison resolution; terminal may precede postprocess. Carried actual_service_ms is checked against terminal-minus-path with 0.001 ms serialization tolerance; both remain path envelopes, not pure inference service.

- damage carried_actual_service_ms: count=1075, p50/p95/p99=75.846692/327.5658411/362.68677662 ms; native path envelopes include waits/execution.
- damage native_terminal_to_postprocess_ms: count=1075, p50/p95/p99=-0.4866/-0.05093/-0.01174 ms; native path envelopes include waits/execution.
- damage parent_to_path_ms: count=1075, p50/p95/p99=5.1714/98.88403/345.27317 ms; native path envelopes include waits/execution.
- damage path_to_terminal_ms: count=1075, p50/p95/p99=75.8468/327.56568/362.68687 ms; native path envelopes include waits/execution.
- foreign_object carried_actual_service_ms: count=1075, p50/p95/p99=78.484091/336.3138157/366.57313172 ms; native path envelopes include waits/execution.
- foreign_object native_terminal_to_postprocess_ms: count=1075, p50/p95/p99=-0.5137/-0.0476/-0.0095 ms; native path envelopes include waits/execution.
- foreign_object parent_to_path_ms: count=1075, p50/p95/p99=5.8872/102.19535/350.454958 ms; native path envelopes include waits/execution.
- foreign_object path_to_terminal_ms: count=1075, p50/p95/p99=78.4842/336.31401/366.573246 ms; native path envelopes include waits/execution.
- plate_number carried_actual_service_ms: count=1075, p50/p95/p99=70.091807/326.8424231/351.09552994 ms; native path envelopes include waits/execution.
- plate_number native_terminal_to_postprocess_ms: count=1075, p50/p95/p99=-0.4966/-0.05974/-0.011292 ms; native path envelopes include waits/execution.
- plate_number parent_to_path_ms: count=1075, p50/p95/p99=2.8826/86.09234/334.633034 ms; native path envelopes include waits/execution.
- plate_number path_to_terminal_ms: count=1075, p50/p95/p99=70.0918/326.84254/351.095636 ms; native path envelopes include waits/execution.
- vehicle_type carried_actual_service_ms: count=1075, p50/p95/p99=74.303801/332.5976225/360.19224432 ms; native path envelopes include waits/execution.
- vehicle_type native_terminal_to_postprocess_ms: count=1075, p50/p95/p99=-0.4802/-0.05171/-0.005 ms; native path envelopes include waits/execution.
- vehicle_type parent_to_path_ms: count=1075, p50/p95/p99=4.6614/92.60042/348.610912 ms; native path envelopes include waits/execution.
- vehicle_type path_to_terminal_ms: count=1075, p50/p95/p99=74.3037/332.59766/360.192304 ms; native path envelopes include waits/execution.

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

- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-shared-video-dag/evidence/frames.csv (273427 bytes; SHA256 5174a4da28bf3f38e203ef4d77b28ee6ef2c4635798fb274a1ab670a1ee16733).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-shared-video-dag/evidence/ingress_ledger.csv (733398 bytes; SHA256 c9ddf3e1e1f7a071797ceb4ab40ea0413fd2935e96f7f3e6ddbc7a14f6e32331).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-shared-video-dag/evidence/branch_terminals.csv (2971211 bytes; SHA256 3c60c993a60b090909880090d30ee1923db10695720d476f5ee9a2b970eb82f0).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-shared-video-dag/evidence/frame_events.csv (4372641 bytes; SHA256 20b43079100ec18a4dcf3ac9bd0c16c148f293e8440cb02b0a166cf2a71eb02e).
- /home/s-a-balashov/work/vast-component-release-20260930-d27/artifacts/gstreamer_component_release_20260930_a4e145b7/gpu-pair-02/operations/arms/component-gstreamer_custom-gpu-h264-shared-video-dag/evidence/publication_policy_decisions.jsonl (20420882 bytes; SHA256 16cc7d0674365e19f01fd96c204e1fa8a266b708103c14c3b7fd228cc2a12569).
