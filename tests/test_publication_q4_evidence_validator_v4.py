from __future__ import annotations

import copy
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import publication_q4_evidence_validator_v4 as target  # noqa: E402


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def write_csv(path: Path, columns: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=list(columns), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def text_row(columns: tuple[str, ...], *, run_id: str) -> dict[str, object]:
    row: dict[str, object] = {column: "native" for column in columns}
    for column in columns:
        if column == "schema_version":
            row[column] = 2
        elif column == "run_id":
            row[column] = run_id
        elif column in {
            "stream_id", "frame_id", "queue_depth", "objects", "dropped_frames",
            "late_frames", "total_frames", "admission_seq", "source_cycle",
            "access_unit_pts_ns", "payload_size_bytes", "schedule_offset_ns",
            "semantic_contract_version", "reset_contract_version", "observed_pid",
            "ready_timestamp_ns", "source_cycle_first", "admission_seq_first",
            "telemetry_sink_preexisting_entry_count", "decision_seq", "update_seq",
            "first_consumer_decision_seq",
        }:
            row[column] = 0
        elif column.endswith("_ms") or column.endswith("_percent"):
            row[column] = 1
        elif column.endswith("_json"):
            row[column] = "{}"
        elif column.endswith("_sha256"):
            row[column] = "a" * 64
    return row


class EvidenceFixture:
    def __init__(
        self, root: Path, *, policy: str = "cpu_only",
        topology: str = "independent_processes",
        runtime_authority_sha: str = "1" * 64,
    ) -> None:
        self.root = root
        self.evidence = root / "runs/cell-000/evidence"
        self.evidence.mkdir(parents=True)
        self.coordinate = {
            "system": "deepstream",
            "codec": "h264",
            "topology_kind": topology,
            "policy": policy,
            "deadline_ms": 16.7,
            "cell_index": (
                target.TOPOLOGIES.index(topology) * len(target.POLICIES) * 5
                + target.POLICIES.index(policy) * 5
            ),
        }
        self.run_id = "q4-cell-000"
        self.policy_contract_sha = hashlib.sha256(
            b"policy_contract_sha256"
        ).hexdigest()
        self.runtime_authority_sha = runtime_authority_sha
        self.contract_path = root / "runs/cell-000/native-runtime-v4/publication-runtime-contract-v4.json"
        self._write_contract()
        self._write_evidence()

    def _write_contract(self) -> None:
        def typed_ref(label: str, schema: int, kind: str) -> dict[str, object]:
            identity = hashlib.sha256(label.encode("ascii")).hexdigest()
            return {
                "artifact_schema_version": schema,
                "artifact_kind": kind,
                "descriptor": {
                    "path": f"authority/{label}.json",
                    "size_bytes": 1,
                    "sha256": hashlib.sha256((label + "-file").encode("ascii")).hexdigest(),
                },
                "content_identity_sha256": identity,
            }

        source_a = hashlib.sha256(b"source-a").hexdigest()
        source_b = hashlib.sha256(b"source-b").hexdigest()
        streams = [
            {
                "stream_id": index,
                "codec_name": self.coordinate["codec"],
                "sha256": source_a if index < 5 else source_b,
            }
            for index in range(6)
        ]
        dataset_core = {
            "name": "kpp_iss_publication_v3_h264",
            "codec_variant": "h264",
            "logical_stream_instances": 6,
            "streams": streams,
        }
        dataset_binding = {
            "schema_version": 4,
            "artifact_kind": "vast_frozen_publication_dataset_binding_v4",
            "status": "frozen_publication_codec_corpus",
            "codec_variant": "h264",
            "dataset": copy.deepcopy(dataset_core),
        }
        dataset_binding_sha = target.canonical_sha256(dataset_binding)
        evidence_names = target.qualification_launcher_evidence_files_v4(
            self.coordinate["policy"]
        )
        template = {
            field: None
            for field in target._RUNTIME_TEMPLATE_FIELDS_BY_SYSTEM["deepstream"]
        }
        template.update({
            "schema_version": 3,
            "artifact_kind": "vast_deepstream_publication_runtime_inputs_v3",
            "source_files": [
                {"path": "dataset/source-a.h264", "size_bytes": 1, "sha256": source_a},
                {"path": "dataset/source-b.h264", "size_bytes": 1, "sha256": source_b},
            ],
            "static_hybrid_map": (
                {"status": "frozen-test-map"}
                if self.coordinate["policy"] == "static_hybrid"
                else None
            ),
            "defer_full_resource_acceptance": True,
            "evidence_mapping": {name: name for name in evidence_names},
        })
        runtime_inputs = {
            "system": self.coordinate["system"],
            "scenario": "checkpoint_independent_processes_baseline",
            "topology_kind": self.coordinate["topology_kind"],
            "codec": self.coordinate["codec"],
            "policy": self.coordinate["policy"],
            "deadline_ms": self.coordinate["deadline_ms"],
            "duration_s": 180,
            "warmup_s": 30,
            "streams": 6,
            "base_seed": 20260323,
            "run_id": self.run_id,
            "dataset": {**copy.deepcopy(dataset_core), "deepstream_publication_runtime_v3": template},
        }
        runtime_ref = typed_ref(
            "runtime-authority", 2, "vast_backend_publication_runtime_authority_v2"
        )
        runtime_ref["content_identity_sha256"] = self.runtime_authority_sha
        launcher_ref = typed_ref(
            "launcher-authority", 1,
            "vast_backend_publication_launcher_runtime_authority",
        )
        invocation_ref = typed_ref(
            "launcher-invocation", 3,
            "vast_backend_publication_launcher_invocation_v3",
        )
        validator_ref = typed_ref(
            "validator-authority", 1, "vast_backend_runtime_validator_authority_q4"
        )
        runner_ref = typed_ref(
            "runner-authority", 1,
            "vast_backend_runtime_validation_runner_authority",
        )
        graph = {
            "schema_version": 4,
            "artifact_kind": "vast_publication_native_runtime_graph_contract_v4",
            "status": "bound_non_authorizing_native_runtime_graph",
            "authorization_eligible": False,
            "execution_authorized": False,
            "coordinate": copy.deepcopy(self.coordinate),
            "run_id": self.run_id,
            "duration_s": 180,
            "authority_snapshot_sha256": "2" * 64,
            "dataset_binding_sha256": dataset_binding_sha,
            "upstream_identities": {
                field: hashlib.sha256(field.encode("ascii")).hexdigest()
                for field in target._UPSTREAM_IDENTITY_FIELDS
            },
            "runtime_authority_ref": runtime_ref,
            "runtime_authority_sha256": self.runtime_authority_sha,
            "runtime_authority_set_sha256": "3" * 64,
            "runtime_binding_identity_v4_sha256": "4" * 64,
            "launcher_runtime_authority_ref": launcher_ref,
            "launcher_runtime_authority_sha256": launcher_ref["content_identity_sha256"],
            "publication_launcher_invocation_v3_ref": invocation_ref,
            "publication_launcher_invocation_v3_sha256": invocation_ref["content_identity_sha256"],
            "q4_validator_authority_ref": validator_ref,
            "q4_validator_authority_sha256": validator_ref["content_identity_sha256"],
            "runner_authority_ref": runner_ref,
            "runner_authority_sha256": runner_ref["content_identity_sha256"],
            "runner_invocation_identity_sha256": "5" * 64,
            "runtime_inputs_sha256": target.canonical_sha256(runtime_inputs),
            "launcher_evidence_files": list(target.qualification_launcher_evidence_files_v4(self.coordinate["policy"])),
        }
        graph["graph_contract_sha256"] = target.canonical_sha256(graph)
        contract = {
            "schema_version": 4,
            "artifact_kind": "vast_publication_runtime_contract_v4",
            "status": "bound_non_authorizing_arbitrary_q4_runtime",
            "authorization_eligible": False,
            "execution_authorized": False,
            "coordinate": copy.deepcopy(self.coordinate),
            "run_id": self.run_id,
            "duration_s": 180,
            "authority_snapshot_sha256": "2" * 64,
            "dataset_binding_sha256": dataset_binding_sha,
            "runtime_inputs": runtime_inputs,
            "native_graph_contract": graph,
        }
        contract["contract_sha256"] = target.canonical_sha256(contract)
        write_json(self.contract_path, contract)

    def _write_evidence(self) -> None:
        # Six independent frame identities, one per frozen logical stream.
        ingress_rows: list[dict[str, object]] = []
        topology_rows: list[dict[str, object]] = []
        frame_event_rows: list[dict[str, object]] = []
        frame_rows: list[dict[str, object]] = []
        terminal_rows: list[dict[str, object]] = []
        interval_rows: list[dict[str, object]] = []
        policy_rows: list[dict[str, object]] = []
        decisions: list[dict[str, object]] = []
        evidence_names = target.pre_finalization_evidence_files_v4(self.coordinate["policy"])
        static_placement = {
            "plate_number": "cpu", "vehicle_type": "gpu",
            "damage": "cpu", "foreign_object": "gpu",
        }

        for stream_id in range(6):
            trace = f"trace-{stream_id}"
            input_key = f"input-{stream_id}"
            ingress = text_row(target.INGRESS_LEDGER_COLUMNS, run_id=self.run_id)
            ingress.update({
                "cohort_id": "cohort-q4", "trace_id": trace,
                "input_frame_key": input_key, "admission_seq": stream_id,
                "stream_id": stream_id, "frame_id": 0,
                "ingress_timestamp_ms": 0, "window_start_timestamp_ms": 0,
                "window_end_timestamp_ms": 180000, "terminal_status": "completed",
                "terminal_timestamp_ms": 100, "drain_end_timestamp_ms": 101,
                "telemetry_source": "native",
            })
            ingress_rows.append(ingress)
            frame = text_row(target.FRAME_COLUMNS, run_id=self.run_id)
            frame.update({
                "trace_id": trace, "stream_id": stream_id, "frame_id": 0,
                "ingress_timestamp_ms": 0, "egress_timestamp_ms": 100,
                "e2e_latency_ms": 100, "objects": 4,
                "detector": "checkpoint_all_branches_per_stream_v1",
                "backend": "deepstream_native_branch_aggregate_v1",
                "telemetry_source": "native",
            })
            frame_rows.append(frame)

            source_execution = f"source-{stream_id}"
            decode_execution = f"decode-{stream_id}"
            for event_kind, stage, execution, parents, timestamp in (
                ("source_read", "source", source_execution, [], 0.0),
                ("stage_complete", "decode", decode_execution, [source_execution], 2.0),
            ):
                row = text_row(target.TOPOLOGY_EVENT_COLUMNS, run_id=self.run_id)
                row.update({
                    "trace_id": trace, "stream_id": stream_id, "frame_id": 0,
                    "input_frame_key": input_key,
                    "topology_kind": self.coordinate["topology_kind"],
                    "event_kind": event_kind, "stage": stage, "branch_id": "decode",
                    "execution_id": execution,
                    "parent_execution_ids_json": json.dumps(parents, separators=(",", ":")),
                    "execution_domain": "native", "timestamp_ms": timestamp,
                    "event_provenance": "native_runtime_event", "telemetry_source": "native",
                })
                topology_rows.append(row)
            decode_event = text_row(target.FRAME_EVENT_COLUMNS, run_id=self.run_id)
            decode_event.update({
                "trace_id": trace, "stream_id": stream_id, "frame_id": 0,
                "stage": "decode", "resource": "nvdec",
                "queue_enter_timestamp_ms": 0, "stage_start_timestamp_ms": 0,
                "stage_end_timestamp_ms": 2,
            })
            frame_event_rows.append(decode_event)

            interval = text_row(target.RESOURCE_INTERVAL_COLUMNS, run_id=self.run_id)
            interval.update({
                "interval_contract_version": 2, "trace_id": trace,
                "stream_id": stream_id, "frame_id": 0, "input_frame_key": input_key,
                "component": "nvdec_submit_complete", "direction": "none",
                "stage": "decode", "branch_id": "decode", "execution_id": decode_execution,
                "host_start_timestamp_ns": 1, "host_end_timestamp_ns": 1000000,
                "duration_ns": 999999, "bytes": 1, "device_id": "nvdec:0",
                "counter_scope": "per_trace_interval",
                "native_event_id": hashlib.sha256(f"event-{stream_id}".encode()).hexdigest(),
                "duration_provenance": "native_decoder_submit_complete_interval_v1",
                "telemetry_source": "native",
            })
            interval_rows.append(interval)

            for branch in target.BRANCHES:
                policy = self.coordinate["policy"]
                selected_resource = (
                    "cpu" if policy == "cpu_only"
                    else "gpu" if policy == "gpu_only"
                    else static_placement[branch] if policy == "static_hybrid"
                    else "gpu"
                )
                execution = f"{branch}-{stream_id}"
                topology = text_row(target.TOPOLOGY_EVENT_COLUMNS, run_id=self.run_id)
                topology.update({
                    "trace_id": trace, "stream_id": stream_id, "frame_id": 0,
                    "input_frame_key": input_key, "topology_kind": self.coordinate["topology_kind"],
                    "event_kind": "stage_complete", "stage": branch, "branch_id": branch,
                    "execution_id": execution,
                    "parent_execution_ids_json": json.dumps([decode_execution]),
                    "execution_domain": "native", "timestamp_ms": 10,
                    "event_provenance": "native_runtime_event", "telemetry_source": "native",
                })
                topology_rows.append(topology)
                event = text_row(target.FRAME_EVENT_COLUMNS, run_id=self.run_id)
                event.update({
                    "trace_id": trace, "stream_id": stream_id, "frame_id": 0,
                    "stage": branch, "resource": selected_resource,
                    "queue_enter_timestamp_ms": 2, "stage_start_timestamp_ms": 2,
                    "stage_end_timestamp_ms": 10, "policy_action": self.coordinate["policy"],
                })
                frame_event_rows.append(event)
                terminal = text_row(target.BRANCH_TERMINAL_COLUMNS, run_id=self.run_id)
                terminal.update({
                    "cohort_id": "cohort-q4", "trace_id": trace,
                    "input_frame_key": input_key, "stream_id": stream_id, "frame_id": 0,
                    "branch_id": branch, "terminal_status": "completed",
                    "terminal_timestamp_ms": 10, "objects": 1,
                    "detector": f"detector-{branch}",
                    "backend": f"native-{selected_resource}",
                    "terminal_provenance": "native", "telemetry_source": "native",
                })
                terminal_rows.append(terminal)
                decision_id = f"decision-{stream_id}-{branch}"
                decision_seq = len(decisions) + 1
                selected_implementation = f"impl-{branch}-{selected_resource}"
                policy_row = text_row(target.POLICY_DECISION_COLUMNS, run_id=self.run_id)
                policy_row.update({
                    "trace_id": trace, "stream_id": stream_id, "frame_id": 0,
                    "stage": branch, "policy": policy,
                    "decision": selected_implementation,
                    "resource": selected_resource, "decision_id": decision_id,
                    "decision_seq": decision_seq, "decision_timestamp_ms": 2,
                    "policy_version": "vast-publication-policy-engine-v1",
                    "terminal_status": "completed", "terminal_timestamp_ms": 10,
                    "causal_trace_completeness": "full",
                    "decision_provenance": "native_scheduler_trace",
                    "trace_completeness": "full", "telemetry_source": "native",
                })
                policy_rows.append(policy_row)
                forced = policy in {"cpu_only", "gpu_only", "static_hybrid"}
                candidates = {
                    "cpu": {
                        "allowed": (not forced or selected_resource == "cpu"),
                        "implementation_id": f"impl-{branch}-cpu",
                        "available_ms": 0.0,
                        "queue_depth": 0,
                        "estimated_service_ms": 5.0,
                        "transfer_ms": 0.0,
                    },
                    "gpu": {
                        "allowed": (not forced or selected_resource == "gpu"),
                        "implementation_id": f"impl-{branch}-gpu",
                        "available_ms": 0.0,
                        "queue_depth": 0,
                        "estimated_service_ms": 2.0,
                        "transfer_ms": 1.0,
                    },
                }
                evaluations = {
                    "cpu": {
                        **candidates["cpu"], "predicted_start_ms": 2.0,
                        "predicted_finish_ms": 7.0, "predicted_lateness_ms": 0.0,
                    },
                    "gpu": {
                        **candidates["gpu"], "predicted_start_ms": 2.0,
                        "predicted_finish_ms": 5.0, "predicted_lateness_ms": 0.0,
                    },
                }
                if policy == "queue_aware_edf":
                    evaluations["cpu"]["queue_completion_ms"] = 7.0
                    evaluations["gpu"]["queue_completion_ms"] = 5.0
                if policy == "adaptive_weights":
                    for resource, service in (("cpu", 5.0), ("gpu", 2.0)):
                        evaluations[resource].update({
                            "service_basis_ms": service,
                            "adaptive_weight": 1.0,
                            "adaptive_score_ms": service
                            + float(evaluations[resource]["transfer_ms"]),
                        })
                reason = {
                    "cpu_only": "forced_policy_resource",
                    "gpu_only": "forced_policy_resource",
                    "static_hybrid": "frozen_calibrated_mixed_map",
                    "heft": "minimum_earliest_finish_time",
                    "deadline_aware_heft": "minimum_feasible_finish_time",
                    "queue_aware_edf": "edf_task_minimum_queue_completion",
                    "adaptive_weights": "minimum_bounded_queue_ewma_cost",
                }[policy]
                decision = {
                    "schema_version": 1,
                    "artifact_kind": "vast_publication_policy_decision",
                    "policy_contract_sha256": self.policy_contract_sha,
                    "engine_implementation_id": "vast-publication-policy-engine-v1",
                    "policy_scope": "analytics_only",
                    "policy": policy,
                    "system": self.coordinate["system"],
                    "arm_id": self.run_id,
                    "decision_id": decision_id,
                    "decision_seq": decision_seq,
                    "trace_id": trace,
                    "branch": branch,
                    "request": {
                        "decision_id": decision_id, "decision_seq": decision_seq,
                        "trace_id": trace, "branch": branch,
                        "arrival_ms": 0.0, "decision_time_ms": 2.0,
                        "deadline_ms": 16.7, "rank_u_ms": 1.0,
                        "candidates": candidates,
                    },
                    "state_before": {
                        "arm_id": self.run_id,
                        "weights": {"cpu": 1.0, "gpu": 1.0},
                        "service_ewma_ms": {},
                    },
                    "static_hybrid_map_sha256": (
                        "e" * 64 if policy == "static_hybrid" else None
                    ),
                    "static_hybrid_placement": (
                        copy.deepcopy(static_placement)
                        if policy == "static_hybrid" else None
                    ),
                    "evaluations": evaluations,
                    "selected_resource": selected_resource,
                    "selected_implementation_id": selected_implementation,
                    "reason": reason,
                    "record_status": "accepted_native_runtime_decision",
                    "native_decision_evidence": {
                        "event_id": f"native-{decision_id}",
                        "decision_id": decision_id,
                        "system": self.coordinate["system"],
                        "branch": branch,
                        "selected_resource": selected_resource,
                        "implementation_id": selected_implementation,
                        "emitter_id": "native-emitter",
                        "emitter_sha256": "b" * 64,
                        "telemetry_source": "native",
                        "path_entry_timestamp_ms": 3.0,
                        "terminal_status": "completed",
                        "terminal_timestamp_ms": 10.0,
                        "actual_service_ms": 7.0,
                        "detector": f"detector-{branch}",
                        "backend": f"native-{selected_resource}",
                        "worker_id": f"worker-{stream_id}-{branch}",
                        "input_frame_key": input_key,
                        "transport_pts_ns": stream_id,
                    },
                }
                decision["sha256"] = target.canonical_sha256(decision)
                decisions.append(decision)

        write_csv(self.evidence / "frames.csv", target.FRAME_COLUMNS, frame_rows)
        write_csv(self.evidence / "frame_events.csv", target.FRAME_EVENT_COLUMNS, frame_event_rows)
        write_csv(self.evidence / "topology_events.csv", target.TOPOLOGY_EVENT_COLUMNS, topology_rows)
        write_csv(self.evidence / "ingress_ledger.csv", target.INGRESS_LEDGER_COLUMNS, ingress_rows)
        write_csv(self.evidence / "branch_terminals.csv", target.BRANCH_TERMINAL_COLUMNS, terminal_rows)
        write_csv(self.evidence / "policy_decisions.csv", target.POLICY_DECISION_COLUMNS, policy_rows)
        write_csv(self.evidence / "resource_intervals.csv", target.RESOURCE_INTERVAL_COLUMNS, interval_rows)

        for name, columns in (
            ("resource_events.csv", target.RESOURCE_EVENT_COLUMNS),
            ("drop_counters.csv", target.DROP_COUNTER_COLUMNS),
            ("stage_contracts.csv", target.STAGE_CONTRACT_COLUMNS),
            ("reset_evidence.csv", target.RESET_EVIDENCE_COLUMNS),
        ):
            row = text_row(columns, run_id=self.run_id)
            if name == "drop_counters.csv":
                row.update({"stream_id": 0, "total_frames": 1, "deadline_ms": 16.7})
            write_csv(self.evidence / name, columns, [row])

        decisions_payload = b"".join(canonical(value) + b"\n" for value in decisions)
        (self.evidence / "publication_policy_decisions.jsonl").write_bytes(decisions_payload)
        if self.coordinate["policy"] == "adaptive_weights":
            feedback_records: list[dict[str, object]] = []
            for decision in decisions:
                feedback = {
                    "schema_version": 1,
                    "artifact_kind": "vast_publication_policy_feedback",
                    "policy_contract_sha256": decision["policy_contract_sha256"],
                    "engine_implementation_id": decision["engine_implementation_id"],
                    "policy": "adaptive_weights",
                    "system": self.coordinate["system"],
                    "arm_id": self.run_id,
                    "decision_id": decision["decision_id"],
                    "actual_service_ms": 7.0,
                    "completed_at_ms": 10.0,
                    "deadline_ms": 16.7,
                    "outcome": "on_time",
                    "state_before": copy.deepcopy(decision["state_before"]),
                    "state_after": copy.deepcopy(decision["state_before"]),
                }
                feedback["sha256"] = target.canonical_sha256(feedback)
                feedback_records.append(feedback)
            (self.evidence / "publication_policy_feedback.jsonl").write_bytes(
                b"".join(canonical(value) + b"\n" for value in feedback_records)
            )
        write_csv(self.evidence / "fanout_work_counters.csv", target.FANOUT_WORK_COUNTER_COLUMNS, [])
        hardware = text_row(target.HARDWARE_RESOURCE_SAMPLE_COLUMNS, run_id=self.run_id)
        hardware.update({
            "resource_contract_version": 2, "sample_seq": 1,
            "timestamp_ns": 180000000000, "sample_period_us": 180000000,
            "device_id": "gpu:0", "nvdec_util_percent": 10,
            "gpu_util_percent": 10, "memory_util_percent": 10,
            "vram_used_bytes": 1, "counter_scope": "device_sample",
            "sample_provenance": "nvml_device_decoder_utilization_v1",
            "telemetry_source": "native",
        })
        write_csv(self.evidence / "hardware_resource_samples.csv", target.HARDWARE_RESOURCE_SAMPLE_COLUMNS, [hardware])

        hashes = {
            name: hashlib.sha256((self.evidence / name).read_bytes()).hexdigest()
            for name in evidence_names
        }
        candidate = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_publication_runtime_candidate",
            "status": "pending_full_resource_validation",
            "run_id": self.run_id,
            "system": self.coordinate["system"],
            "scenario": "checkpoint_independent_processes_baseline",
            "codec": self.coordinate["codec"],
            "policy": self.coordinate["policy"],
            "deadline_ms": self.coordinate["deadline_ms"],
            "execution_binding_provenance": "native_scheduler_execution_binding_v1",
            "topology_kind": self.coordinate["topology_kind"],
            "cohort_id": "cohort-q4",
            "measurement_schedule_fingerprint_sha256": "c" * 64,
            "completed_frames_by_stream": {str(index): 1 for index in range(6)},
            "summary": {
                "ingress_ledger_complete": True,
                "ingress_cohort_closed": True,
                "branch_terminal_trace_complete": True,
                "checkpoint_frame_aggregation_complete": True,
                "stage_semantic_contract_complete": True,
                "decoder_placement_verified": True,
                "resource_attribution_complete": True,
                "reset_state_verified": True,
                "c_obs_total_ms": 1.0,
            },
            "evidence_sha256": hashes,
            "pending_full_resource_evidence": [
                "resource_intervals.csv", "hardware_resource_samples.csv", "fanout_work_counters.csv"
            ],
        }
        write_json(self.evidence / "checkpoint_publication_candidate.json", candidate)

    def manifest(self) -> dict[str, object]:
        return target.build_publication_q4_raw_evidence_manifest_v4(
            project_root=self.root,
            evidence_dir=self.evidence,
            runtime_contract_path=self.contract_path,
            coordinate=self.coordinate,
            run_id=self.run_id,
            duration_s=180,
        )


class PublicationQ4EvidenceValidatorV4Tests(unittest.TestCase):
    def test_build_and_validate_exact_native_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            manifest = fixture.manifest()
            checked = target.validate_publication_q4_raw_evidence_manifest_v4(
                manifest,
                expected_coordinate=fixture.coordinate,
                expected_run_id=fixture.run_id,
                expected_runtime_authority_sha256=fixture.runtime_authority_sha,
            )
            result = target.validate_publication_q4_evidence_files_v4(
                project_root=fixture.root,
                raw_evidence_manifest=checked,
            )
            self.assertEqual(result["replay_result"], target.QUALIFIED_REPLAY_RESULT)

    def test_tampered_file_and_candidate_coordinate_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            manifest = fixture.manifest()
            (fixture.evidence / "frames.csv").write_bytes(b"tampered\n")
            with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "physical descriptor"):
                target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=manifest,
                )

        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            candidate_path = fixture.evidence / "checkpoint_publication_candidate.json"
            candidate = json.loads(candidate_path.read_bytes())
            candidate["codec"] = "h265"
            write_json(candidate_path, candidate)
            manifest = fixture.manifest()
            with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "candidate identity"):
                target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=manifest,
                )

    def test_policy_aware_feedback_and_full_resource_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            manifest = fixture.manifest()
            hardware = fixture.evidence / "hardware_resource_samples.csv"
            payload = hardware.read_text(encoding="utf-8").replace("q4-cell-000", "wrong-run")
            hardware.write_text(payload, encoding="utf-8", newline="")
            # Rebuild updates the physical hash; semantic run binding must still fail.
            manifest = fixture.manifest()
            with self.assertRaisesRegex(target.PublicationQ4EvidenceV4Error, "hardware.*run_id"):
                target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=manifest,
                )

    def test_candidate_gates_and_native_topology_provenance_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            candidate_path = fixture.evidence / "checkpoint_publication_candidate.json"
            candidate = json.loads(candidate_path.read_bytes())
            candidate["summary"]["reset_state_verified"] = False
            write_json(candidate_path, candidate)
            with self.assertRaisesRegex(
                target.PublicationQ4EvidenceV4Error, "summary gate",
            ):
                target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=fixture.manifest(),
                )

        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            topology_path = fixture.evidence / "topology_events.csv"
            with topology_path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))
            rows[0]["event_provenance"] = "self_claimed_native"
            write_csv(topology_path, target.TOPOLOGY_EVENT_COLUMNS, rows)
            candidate_path = fixture.evidence / "checkpoint_publication_candidate.json"
            candidate = json.loads(candidate_path.read_bytes())
            candidate["evidence_sha256"]["topology_events.csv"] = hashlib.sha256(
                topology_path.read_bytes()
            ).hexdigest()
            write_json(candidate_path, candidate)
            with self.assertRaisesRegex(
                target.PublicationQ4EvidenceV4Error, "topology/event identity",
            ):
                target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=fixture.manifest(),
                )

    def test_runtime_contract_exact_fields_and_runtime_input_hash_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            contract = json.loads(fixture.contract_path.read_bytes())
            contract["unexpected_claim"] = True
            contract.pop("contract_sha256")
            contract["contract_sha256"] = target.canonical_sha256(contract)
            write_json(fixture.contract_path, contract)
            with self.assertRaisesRegex(
                target.PublicationQ4EvidenceV4Error, "contract v4 fields",
            ):
                fixture.manifest()

        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve())
            contract = json.loads(fixture.contract_path.read_bytes())
            contract["runtime_inputs"]["base_seed"] += 1
            contract.pop("contract_sha256")
            contract["contract_sha256"] = target.canonical_sha256(contract)
            write_json(fixture.contract_path, contract)
            with self.assertRaisesRegex(
                target.PublicationQ4EvidenceV4Error,
                "runtime input identity|runtime-input identity",
            ):
                fixture.manifest()

    def test_all_seven_frozen_policy_paths_replay(self) -> None:
        for policy in target.POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as directory:
                fixture = EvidenceFixture(Path(directory).resolve(), policy=policy)
                manifest = fixture.manifest()
                result = target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=manifest,
                )
                self.assertEqual(result["replay_result"], target.QUALIFIED_REPLAY_RESULT)

    def test_resealed_policy_decision_drift_fails_frozen_replay(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = EvidenceFixture(Path(directory).resolve(), policy="heft")
            decisions_path = fixture.evidence / "publication_policy_decisions.jsonl"
            decisions = [
                json.loads(line)
                for line in decisions_path.read_text(encoding="utf-8").splitlines()
            ]
            decisions[0]["reason"] = "forged_reason"
            decisions[0].pop("sha256")
            decisions[0]["sha256"] = target.canonical_sha256(decisions[0])
            decisions_path.write_bytes(
                b"".join(canonical(item) + b"\n" for item in decisions)
            )
            candidate_path = fixture.evidence / "checkpoint_publication_candidate.json"
            candidate = json.loads(candidate_path.read_bytes())
            candidate["evidence_sha256"]["publication_policy_decisions.jsonl"] = (
                hashlib.sha256(decisions_path.read_bytes()).hexdigest()
            )
            write_json(candidate_path, candidate)
            manifest = fixture.manifest()
            with self.assertRaisesRegex(
                target.PublicationQ4EvidenceV4Error, "frozen policy replay",
            ):
                target.validate_publication_q4_evidence_files_v4(
                    project_root=fixture.root,
                    raw_evidence_manifest=manifest,
                )


if __name__ == "__main__":
    unittest.main()
