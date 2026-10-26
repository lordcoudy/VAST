"""Purpose-built native protocol fixtures; never campaign qualification authority.

This producer runs the actual policy coordinator and validators. Its native
messages are artificial protocol observations, not claims of physical execution.
Full consumer tests must attach genuine upstream cold-validation authority and
complete sidecars before treating these files as accepted fixture evidence.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import pandas as pd

from benchmark_contract import (
    BRANCH_TERMINAL_COLUMNS, CHECKPOINT_FRAME_AGGREGATE_DETECTOR,
    DROP_COUNTER_COLUMNS, FRAME_COLUMNS, FRAME_EVENT_COLUMNS,
    INGRESS_LEDGER_COLUMNS, RESET_EVIDENCE_COLUMNS, RESOURCE_EVENT_COLUMNS,
    STAGE_CONTRACT_COLUMNS,
)

from checkpoint_native_policy_runtime import NativePolicyRuntimeCoordinator
from publication_policy_contract import ANALYTICS_BRANCHES, RESOURCES
from full_resource_contract import FANOUT_WORK_COUNTER_COLUMNS, HARDWARE_RESOURCE_SAMPLE_COLUMNS
from resource_interval_contract import RESOURCE_INTERVAL_COLUMNS, _expected_transfer_keys, _normalized_linkage
from topology_contract import TOPOLOGY_EVENT_COLUMNS
from tests.fixtures.accepted_policy_native_rows_v2 import (
    branch_terminal_row, ingress_ledger_row, interval_row, native_event_row,
    native_frame_row, resource_event_row, stage_contract_row,
)
from tests.fixtures.accepted_policy_fixture_provenance_v1 import fixture_metadata_identity_v1


MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2 = 985


def fixture_calibration_v2(capability: Mapping[str, Any], system: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_calibration",
        "system": system,
        "policy_contract_sha256": capability["policy_contract_sha256"],
        "costs": {
            branch: {
                resource: {
                    "implementation_id": capability["systems"][system]["branches"][branch][resource]["implementation_id"],
                    "service_ms": 2.0,
                    "transfer_ms": 0.0 if resource == "cpu" else 1.0,
                    "samples": 30,
                }
                for resource in RESOURCES
            }
            for branch in ANALYTICS_BRANCHES
        },
    }


def write_native_policy_fixture_cell_v2(
    *,
    output_dir: Path,
    capability: Mapping[str, Any],
    system: str,
    resource: str,
    codec: str,
    topology_kind: str,
    samples_per_branch: int = 30,
    dropped_ingress: bool = False,
    source_sha256_by_stream: Mapping[int, str] | None = None,
    run_id: str | None = None,
    arm_id: str | None = None,
    calibration: Mapping[str, Any] | None = None,
    operational_context: Mapping[str, Any] | None = None,
    worker_ids_by_branch_stream: Mapping[tuple[str, int], str] | None = None,
    limits_path: Path | None = None,
) -> dict[str, Any]:
    if (type(samples_per_branch) is not int
            or not 1 <= samples_per_branch <= MAX_FIXTURE_COMPLETED_SAMPLES_PER_BRANCH_V2):
        raise ValueError("native fixture completed sample count must be in 1..985")
    if type(dropped_ingress) is not bool:
        raise ValueError("native fixture dropped_ingress requires an exact Boolean")
    if resource not in RESOURCES or codec not in {"h264", "h265"}:
        raise ValueError("unsupported fixture coordinate")
    if topology_kind not in {"independent_processes", "shared_video_dag"}:
        raise ValueError("unsupported fixture topology")
    # Both resources feed calibration; selected-resource labels also enter
    # protocol messages and sidecars. Admit originals before any output exists.
    for branch in ANALYTICS_BRANCHES:
        for selected_resource in RESOURCES:
            binding = capability["systems"][system]["branches"][branch][selected_resource]
            for field in ("implementation_id", "terminal_detector", "terminal_backend"):
                fixture_metadata_identity_v1(binding[field])
    output_dir.mkdir(parents=True, exist_ok=False)
    stem = f"fixture-{system}-{resource}-{codec}-{topology_kind}"
    run_id = run_id or stem + "-run"
    arm_id = arm_id or stem + "-arm"
    policy = "cpu_only" if resource == "cpu" else "gpu_only"
    scenario = (
        "checkpoint_independent_processes_baseline"
        if topology_kind == "independent_processes"
        else "checkpoint_video_dag_shared"
    )
    coordinator = NativePolicyRuntimeCoordinator(
        run_id=run_id,
        arm_id=operational_context["header"]["initial_state"]["arm_id"] if operational_context else arm_id,
        system=system,
        scenario=scenario,
        codec=codec,
        policy=policy,
        deadline_ms=100.0,
        branches=ANALYTICS_BRANCHES,
        capability_manifest=capability,
        calibration=calibration or fixture_calibration_v2(capability, system),
        operational_context=operational_context,
    )
    frames: dict[str, dict[str, Any]] = {}
    observations: list[dict[str, Any]] = []
    for position in range(samples_per_branch + int(dropped_ingress)):
        stream_id = position % 6
        frame_id = position // 6 + 1
        is_drop = position == samples_per_branch
        input_frame_key = f"{stem}:source:{stream_id}:{frame_id}"
        trace_id = f"{run_id}:{stream_id}:{frame_id}"
        transport_pts_ns = frame_id * 40_000_000
        frames[input_frame_key] = {
            "trace_id": trace_id,
            "stream_id": stream_id,
            "frame_id": frame_id,
        }
        for branch_position, branch in enumerate(ANALYTICS_BRANCHES):
            # One pre-detector branch drop closes the dropped ingress; no
            # decision exists for that branch. Other branches really complete
            # under protocol validation, but the frame has no transfer sample.
            if is_drop and branch == ANALYTICS_BRANCHES[-1]:
                continue
            worker_id = (worker_ids_by_branch_stream or {}).get((branch, stream_id), f"{stem}-worker-{stream_id}")
            decision_ms = 1000.0 + position * 20.0 + branch_position
            request = {
                "schema_version": 1,
                "message_type": "decision_request",
                "run_id": run_id,
                "worker_id": worker_id,
                "input_frame_key": input_frame_key,
                "trace_id": trace_id,
                "stream_id": stream_id,
                "frame_id": frame_id,
                "transport_pts_ns": transport_pts_ns,
                "branch": branch,
                "arrival_ms": decision_ms - 10.0,
                "decision_time_ms": decision_ms,
                "feature_observed_timestamp_ms": decision_ms - 1.0,
                "queue_depths": {"cpu": 0, "gpu": 0},
            }
            response = coordinator.handle_message(worker_id, request)
            if response["selected_resource"] != resource:
                raise AssertionError("fixture forced-resource decision drifted")
            binding = capability["systems"][system]["branches"][branch][resource]
            entered = {
                "schema_version": 1,
                "message_type": "path_enter",
                "run_id": run_id,
                "worker_id": worker_id,
                "decision_id": response["decision_id"],
                "input_frame_key": input_frame_key,
                "branch": branch,
                "transport_pts_ns": transport_pts_ns,
                "selected_resource": resource,
                "implementation_id": binding["implementation_id"],
                "emitter_id": binding["native_evidence"]["emitter_id"],
                "emitter_sha256": binding["native_evidence"]["emitter_sha256"],
                "event_id": f"{stem}-event-{position}-{branch}",
                "timestamp_ms": decision_ms + 1.0,
            }
            coordinator.handle_message(worker_id, entered)
            terminal = {
                "schema_version": 1,
                "message_type": "terminal",
                "run_id": run_id,
                "worker_id": worker_id,
                "decision_id": response["decision_id"],
                "input_frame_key": input_frame_key,
                "branch": branch,
                "transport_pts_ns": transport_pts_ns,
                "selected_resource": resource,
                "terminal_status": "completed",
                "terminal_timestamp_ms": decision_ms + 3.0,
                "actual_service_ms": 2.0,
                "detector": binding["terminal_detector"],
                "backend": binding["terminal_backend"],
            }
            coordinator.handle_message(worker_id, terminal)
            observations.append({
                "request": request,
                "response": response,
                "path_enter": entered,
                "terminal": terminal,
                "ingress_terminal": "drop" if is_drop else "completed",
            })
    coordinator.promote(output_dir, canonical_frames=frames)
    limits = {
        "schema_version": 1,
        "artifact_kind": "vast_artificial_native_policy_fixture_limits_v1",
        "campaign_authority": False,
        "physical_runtime_execution_observed": False,
        "scope": "test_protocol_messages_only",
        "coordinate": {"system": system, "resource": resource, "codec": codec, "topology_kind": topology_kind},
        "completed_samples_per_branch": samples_per_branch,
        "dropped_ingress_frames": int(dropped_ingress),
    }
    limits_path = limits_path or output_dir / "fixture_limits.json"
    limits_path.parent.mkdir(parents=True, exist_ok=True)
    limits_path.write_text(
        json.dumps(limits, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    metadata = {
        "run_id": run_id,
        "arm_id": arm_id,
        "scenario": scenario,
        "policy": policy,
        "canonical_frames": frames,
        "observations": observations,
        "source_sha256_by_stream": dict(source_sha256_by_stream or {}),
        "limits": limits,
    }
    _write_native_sidecars_v1(output_dir, capability, metadata)
    return metadata


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _write_native_sidecars_v1(output: Path, capability: Mapping[str, Any], metadata: Mapping[str, Any]) -> None:
    coordinate = metadata["limits"]["coordinate"]
    system, resource, topology_kind = (coordinate[key] for key in ("system", "resource", "topology_kind"))
    shared = topology_kind == "shared_video_dag"
    run_id = metadata["run_id"]
    cohort = run_id + ":cohort:1"
    observations = {(row["request"]["input_frame_key"], row["request"]["branch"]): row for row in metadata["observations"]}
    policies = pd.read_csv(output / "policy_decisions.csv")
    policy_by_key = {(str(row["trace_id"]), str(row["stage"])): row for row in policies.to_dict("records")}
    completed = metadata["limits"]["completed_samples_per_branch"]
    window_start, window_end = 900.0, 1000.0 + len(metadata["canonical_frames"]) * 20.0
    frame_rows, event_rows, ledger_rows, terminal_rows, topology_rows, resource_rows = [], [], [], [], [], []
    for position, (input_key, canonical) in enumerate(metadata["canonical_frames"].items()):
        key = {"run_id": run_id, **canonical}
        base, ingress, terminal = 1000.0 + position * 20.0, 990.0 + position * 20.0, 1007.0 + position * 20.0
        dropped = position >= completed
        ledger_rows.append(ingress_ledger_row(
            **key, cohort_id=cohort, input_frame_key=input_key,
            ingress_timestamp_ms=ingress, window_start_timestamp_ms=window_start,
            window_end_timestamp_ms=window_end, terminal_timestamp_ms=terminal,
            drain_end_timestamp_ms=window_end + 20.0, access_unit_pts_ns=int(canonical["frame_id"]) * 40_000_000,
            terminal_status="drop" if dropped else "completed",
            terminal_reason="native_branch_drop" if dropped else "native_output_committed",
            terminal_provenance="native_drop_event" if dropped else "native_completion_event",
            source_sha256=metadata["source_sha256_by_stream"].get(canonical["stream_id"], _sha(f"fixture-source-{coordinate['codec']}-{canonical['stream_id']}")),
        ))
        if not dropped:
            frame_rows.append(native_frame_row(
                **key, ingress_timestamp_ms=ingress, egress_timestamp_ms=terminal,
                e2e_latency_ms=terminal - ingress, objects=4,
                detector=CHECKPOINT_FRAME_AGGREGATE_DETECTOR, backend="checkpoint-native-join-v1",
            ))

        def topology_event(kind: str, stage: str, branch: str, domain: str, at: float, parents: list[str]) -> str:
            execution = f"{canonical['trace_id']}:{kind}:{stage}:{branch}"
            if not dropped:
                topology_rows.append({
                    "schema_version": 2, **key, "input_frame_key": input_key,
                    "topology_kind": topology_kind, "event_kind": kind, "stage": stage,
                    "branch_id": branch, "execution_id": execution,
                    "parent_execution_ids_json": json.dumps(parents, separators=(",", ":")),
                    "execution_domain": domain, "timestamp_ms": int(at),
                    "event_provenance": "native_runtime_event", "telemetry_source": "native",
                })
            return execution

        def stage_event(stage: str, selected_resource: str, start: float, end: float) -> None:
            decision = policy_by_key.get((canonical["trace_id"], stage))
            event_rows.append(native_event_row(
                **key, stage=stage, resource=selected_resource,
                queue_enter_timestamp_ms=start, stage_start_timestamp_ms=start,
                stage_end_timestamp_ms=end, estimated_cost_ms=float(decision["estimated_cost_ms"]) if decision else end - start,
                queue_depth=int(decision["queue_depth"]) if decision else 0,
                policy_action=str(decision["decision"]) if decision else "native:fixture-fixed-prefix",
            ))
            resource_rows.append(resource_event_row(
                **key, stage=stage, resource=selected_resource, timestamp_ms=end,
                cpu_time_ms=0.0 if selected_resource == "gpu" else end - start,
                gpu_time_ms=end - start if selected_resource == "gpu" else 0.0,
            ))

        common_domain = f"fixture-stream-{canonical['stream_id']}-shared"
        shared_prefix = None
        if shared:
            source = topology_event("source_read", "source", "shared", common_domain, ingress, [])
            decode = topology_event("stage_complete", "decode", "shared", common_domain, base - 3.0, [source])
            shared_prefix = topology_event("stage_complete", "preprocess", "shared", common_domain, base - 1.0, [decode])
            stage_event("decode", "nvdec", ingress, base - 3.0)
            stage_event("preprocess", "cpu", base - 3.0, base - 1.0)
        branch_completions = []
        for branch_index, branch in enumerate(ANALYTICS_BRANCHES):
            binding = capability["systems"][system]["branches"][branch][resource]
            observation = observations.get((input_key, branch))
            domain = common_domain if shared else f"fixture-stream-{canonical['stream_id']}-{branch}"
            if not shared:
                source = topology_event("source_read", "source", branch, domain, ingress, [])
                decode = topology_event("stage_complete", f"decode_{branch}", branch, domain, base - 3.0, [source])
                prefix = topology_event("stage_complete", f"preprocess_{branch}", branch, domain, base - 1.0, [decode])
                stage_event(f"decode_{branch}", "nvdec", ingress, base - 3.0)
                stage_event(f"preprocess_{branch}", "cpu", base - 3.0, base - 1.0)
            else:
                prefix = topology_event("fanout", "fanout", branch, domain, base, [shared_prefix])
            at = observation["terminal"]["terminal_timestamp_ms"] if observation else terminal
            terminal_rows.append(branch_terminal_row(
                **key, cohort_id=cohort, input_frame_key=input_key, branch_id=branch,
                terminal_timestamp_ms=at, detector=binding["terminal_detector"], backend=binding["terminal_backend"],
                terminal_status="completed" if observation else "drop", objects=1 if observation else 0,
                terminal_reason="native_result_committed" if observation else "native_pre_detector_queue_full_drop_newest",
                terminal_provenance="native_completion_event" if observation else "native_drop_event",
            ))
            if observation:
                stage_event(branch, resource, observation["path_enter"]["timestamp_ms"], at)
                analytics = topology_event("stage_complete", branch, branch, domain, at, [prefix])
                stage_event(f"postprocess_{branch}", "cpu", at, at)
                postprocess = topology_event("stage_complete", f"postprocess_{branch}", branch, domain, at, [analytics])
                branch_completions.append(topology_event("branch_complete", branch, branch, domain, at, [postprocess]))
        topology_event("join_complete", "join", "shared", common_domain, terminal, branch_completions)

    reset_rows = []
    for stream in range(6):
        process_roles = [("source_coordinator", "not_applicable", {})]
        process_roles.extend(
            [("shared_graph_worker", "not_applicable", {branch: 0 for branch in ANALYTICS_BRANCHES})]
            if shared else [("independent_branch_worker", branch, {branch: 0}) for branch in ANALYTICS_BRANCHES]
        )
        for role, branch, queues in process_roles:
            instance = f"{run_id}:process:{stream}:{role}:{branch}"
            reset_rows.append({
                "schema_version": 2, "reset_contract_version": 1, "run_id": run_id, "cohort_id": cohort,
                "stream_id": stream, "process_instance_id": instance, "process_role": role,
                "branch_id": branch, "observed_pid": 1001 + len(reset_rows), "process_start_token": _sha(instance),
                "ready_timestamp_ns": 1_000_000 + len(reset_rows), "telemetry_sink_id": _sha(run_id + ":sink"),
                "telemetry_sink_preexisting_entry_count": 0, "analytics_queue_depths_json": json.dumps(queues),
                "source_cycle_first": 0 if role == "source_coordinator" else -1,
                "admission_seq_first": 1 if role == "source_coordinator" else -1,
                "warmup_included_in_measurement": "false", "admission_stopped_before_drain": "true",
                "terminal_state": "DRAINED", "reset_provenance": "native_process_lifecycle_queue_and_sink_snapshot_v1",
                "telemetry_source": "native",
            })
    from checkpoint_publication_runtime import _accepted_drop_rows
    tables = {
        "frames.csv": (FRAME_COLUMNS, frame_rows), "frame_events.csv": (FRAME_EVENT_COLUMNS, event_rows),
        "resource_events.csv": (RESOURCE_EVENT_COLUMNS, resource_rows),
        "ingress_ledger.csv": (INGRESS_LEDGER_COLUMNS, ledger_rows),
        "branch_terminals.csv": (BRANCH_TERMINAL_COLUMNS, terminal_rows),
        "topology_events.csv": (TOPOLOGY_EVENT_COLUMNS, topology_rows), "reset_evidence.csv": (RESET_EVIDENCE_COLUMNS, reset_rows),
        "drop_counters.csv": (DROP_COUNTER_COLUMNS, _accepted_drop_rows(ledger_rows, frame_rows, deadline_ms=100.0, camera_roles={index: "fixture" for index in range(6)})),
    }
    contracts = {(row["execution_domain"], row["stage"]) for row in topology_rows if row["event_kind"] == "stage_complete" and (row["stage"].startswith("decode") or row["stage"].startswith("preprocess"))}
    tables["stage_contracts.csv"] = (STAGE_CONTRACT_COLUMNS, [stage_contract_row(run_id=run_id, execution_domain=domain, stage=stage, contract_id=f"{run_id}:{domain}:{stage}") for domain, stage in sorted(contracts)])
    ingress_df, topology_df, event_df = pd.DataFrame(ledger_rows), pd.DataFrame(topology_rows), pd.DataFrame(event_rows)
    _, topology_by_key, event_by_key = _normalized_linkage(ingress_df, topology_df, event_df)
    transfer_keys = _expected_transfer_keys(topology_by_key, event_by_key)
    intervals, fanout_counters = [], []
    for (frame_key, execution), row in topology_by_key.items():
        component = "fanout" if row["event_kind"] == "fanout" else "nvdec_submit_complete" if row["event_kind"] == "stage_complete" and row["stage"].startswith("decode") else None
        directions = ["none"] if component else [direction for direction in ("h2d", "d2h") if (frame_key, execution, direction) in transfer_keys]
        for direction in directions:
            selected_component = component or "transfer"
            end = int(row["timestamp_ms"] * 1_000_000)
            intervals.append(interval_row(
                **{name: row[name] for name in ("run_id", "trace_id", "stream_id", "frame_id", "input_frame_key", "stage", "branch_id", "execution_id")},
                component=selected_component, direction=direction,
                host_start_timestamp_ns=end - 500_000, host_end_timestamp_ns=end,
                duration_ns=500_000, bytes=4096,
                device_id={"fanout": "host:tee0", "nvdec_submit_complete": "nvdec:0", "transfer": "gpu:0"}[selected_component],
                native_event_id=_sha(execution + ":" + direction),
                duration_provenance={"fanout": "native_gstreamer_pad_probe_interval_v1", "nvdec_submit_complete": "native_decoder_submit_complete_interval_v1", "transfer": "native_cuda_event_interval_v1"}[selected_component],
            ))
        if component == "fanout":
            fanout_counters.append({
                "schema_version": 2, "resource_contract_version": 2,
                **{name: row[name] for name in ("run_id", "trace_id", "stream_id", "frame_id", "input_frame_key", "branch_id", "execution_id")},
                "thread_cpu_time_ns": 25000, "work_units": 1, "device_id": "host:fanout",
                "counter_scope": "per_trace_resource_work", "counter_provenance": "native_thread_cpu_time_v1", "telemetry_source": "native",
            })
    hardware = [{
        "schema_version": 2, "resource_contract_version": 2, "run_id": run_id,
        "sample_seq": index + 1, "timestamp_ns": int(at * 1_000_000),
        "sample_period_us": int((window_end - window_start) * 500), "device_id": "gpu:0",
        "nvdec_util_percent": 25, "gpu_util_percent": 25, "memory_util_percent": 10,
        "vram_used_bytes": 1_000_000, "counter_scope": "device_sample",
        "sample_provenance": "nvml_device_decoder_utilization_v1", "telemetry_source": "native",
    } for index, at in enumerate((window_start, (window_start + window_end) / 2.0, window_end))]
    tables.update({"resource_intervals.csv": (RESOURCE_INTERVAL_COLUMNS, intervals),
                   "fanout_work_counters.csv": (FANOUT_WORK_COUNTER_COLUMNS, fanout_counters),
                   "hardware_resource_samples.csv": (HARDWARE_RESOURCE_SAMPLE_COLUMNS, hardware)})
    for filename, (columns, rows) in tables.items():
        pd.DataFrame(rows, columns=columns).to_csv(output / filename, index=False)
