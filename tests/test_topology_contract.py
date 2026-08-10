#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError, STAGE_SEMANTIC_CONTRACT_VERSION
from generate_vast_report_artifacts import (
    build_measurement_passports,
    validate_report_inputs,
    validate_report_matrix_membership,
)
from topology_contract import TOPOLOGY_EVENT_COLUMNS, validate_topology_events


BRANCHES = ["plate_number", "damage"]


def measurement_passport_fields(*, ingress_count: int = 1) -> dict[str, object]:
    payload = {
        "contract_version": 4,
        "resource_attribution": "native_per_trace_bounded_stage_interval_ingress_cohort_v3",
        "resource_time_components": ["cpu_time_ms", "gpu_time_ms"],
        "resource_time_aggregation": (
            "unweighted_sum_of_attributed_device_milliseconds_v1"
        ),
        "resource_time_non_equivalence": (
            "not_energy_flops_monetary_cost_or_cross_device_equivalent_work_v1"
        ),
        "resource_time_provenance": ["derived_from_native_stage_timestamps"],
        "resource_interval_linkage": "one_to_one_frame_event_stage_interval_v1",
        "resource_event_coverage": "all_frame_events_for_closed_ingress_cohort",
        "stage_interval_cohort_bounds": (
            "ingress_le_queue_enter_le_stage_start_le_stage_end_le_terminal_v1"
        ),
        "derived_time_semantics": "stage_end_minus_stage_start_excluding_queue_wait",
        "transfer_time_components": [],
        "nvdec_busy_time_included": False,
        "fanout_time_included": False,
        "stage_reduction_rule": "decode_preprocess_suffix_reduction_v1",
        "cohort_terminal_rule": "completed_or_native_drop_no_censored",
    }
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        "resource_attribution_complete": True,
        "resource_attribution": payload["resource_attribution"],
        "resource_attributed_ingress_count": ingress_count,
        "resource_unattributed_event_count": 0,
        "input_schedule_sha256": "b" * 64,
        "input_frame_key_sequence_sha256": "c" * 64,
        "measurement_window_duration_ms": 180_000.0,
        "measurement_signature": hashlib.sha256(payload_json.encode("utf-8")).hexdigest(),
        "measurement_signature_payload_json": payload_json,
        "c_obs_total_ms": 20.0,
        "c_obs_cpu_total_ms": 12.0,
        "c_obs_gpu_total_ms": 8.0,
        "c_obs_in_ms_per_ingress": 20.0 / ingress_count,
        "c_obs_cpu_in_ms_per_ingress": 12.0 / ingress_count,
        "c_obs_gpu_in_ms_per_ingress": 8.0 / ingress_count,
        "c_obs_comp_ms_per_completed": 20.0,
        "c_obs_is_partial": True,
    }


def scenario(kind: str) -> dict:
    return {
        "name": "topology_fixture",
        "topology": {
            "contract_version": 1,
            "kind": kind,
            "routing_mode": "all_branches_per_stream",
            "required_branches": BRANCHES,
        },
        "workload": {
            "streams": 1,
            "logical_stream_instances": 1,
            "analytics_function_types": len(BRANCHES),
            "routing_mode": "all_branches_per_stream",
        },
    }


def frames() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": "run-1",
                "trace_id": "run-1:0:1",
                "stream_id": 0,
                "frame_id": 1,
                "ingress_timestamp_ms": 1000,
                "egress_timestamp_ms": 1100,
            }
        ]
    )


def topology_row(
    *,
    topology_kind: str,
    event_kind: str,
    stage: str,
    branch_id: str,
    execution_id: str,
    parents: list[str],
    execution_domain: str,
    timestamp_ms: int,
) -> dict[str, object]:
    return {
        "schema_version": 2,
        "run_id": "run-1",
        "trace_id": "run-1:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "input_frame_key": "kpp-h264:stream0:pts90000",
        "topology_kind": topology_kind,
        "event_kind": event_kind,
        "stage": stage,
        "branch_id": branch_id,
        "execution_id": execution_id,
        "parent_execution_ids_json": json.dumps(parents),
        "execution_domain": execution_domain,
        "timestamp_ms": timestamp_ms,
        "event_provenance": "native_runtime_event",
        "telemetry_source": "native",
    }


def baseline_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    completion_ids: list[str] = []
    for index, branch in enumerate(BRANCHES):
        domain = f"host:container-{branch}:pid-{100 + index}"
        source_id = f"{branch}:source"
        decode_id = f"{branch}:decode"
        preprocess_id = f"{branch}:preprocess"
        analytics_id = f"{branch}:analytics"
        complete_id = f"{branch}:complete"
        rows.extend(
            [
                topology_row(
                    topology_kind="independent_processes",
                    event_kind="source_read",
                    stage="source",
                    branch_id=branch,
                    execution_id=source_id,
                    parents=[],
                    execution_domain=domain,
                    timestamp_ms=1000,
                ),
                topology_row(
                    topology_kind="independent_processes",
                    event_kind="stage_complete",
                    stage=f"decode_{branch}",
                    branch_id=branch,
                    execution_id=decode_id,
                    parents=[source_id],
                    execution_domain=domain,
                    timestamp_ms=1005 + index,
                ),
                topology_row(
                    topology_kind="independent_processes",
                    event_kind="stage_complete",
                    stage=f"preprocess_{branch}",
                    branch_id=branch,
                    execution_id=preprocess_id,
                    parents=[decode_id],
                    execution_domain=domain,
                    timestamp_ms=1010 + index,
                ),
                topology_row(
                    topology_kind="independent_processes",
                    event_kind="stage_complete",
                    stage=branch,
                    branch_id=branch,
                    execution_id=analytics_id,
                    parents=[preprocess_id],
                    execution_domain=domain,
                    timestamp_ms=1020 + index * 2,
                ),
                topology_row(
                    topology_kind="independent_processes",
                    event_kind="branch_complete",
                    stage=branch,
                    branch_id=branch,
                    execution_id=complete_id,
                    parents=[analytics_id],
                    execution_domain=domain,
                    timestamp_ms=1021 + index * 2,
                ),
            ]
        )
        completion_ids.append(complete_id)
    rows.append(
        topology_row(
            topology_kind="independent_processes",
            event_kind="join_complete",
            stage="join",
            branch_id="shared",
            execution_id="baseline:join",
            parents=completion_ids,
            execution_domain="host:aggregator:pid-200",
            timestamp_ms=1030,
        )
    )
    return rows


def shared_rows() -> list[dict[str, object]]:
    prefix_domain = "host:shared-prefix:pid-300"
    rows = [
        topology_row(
            topology_kind="shared_video_dag",
            event_kind="source_read",
            stage="source",
            branch_id="shared",
            execution_id="shared:source",
            parents=[],
            execution_domain=prefix_domain,
            timestamp_ms=1000,
        ),
        topology_row(
            topology_kind="shared_video_dag",
            event_kind="stage_complete",
            stage="decode",
            branch_id="shared",
            execution_id="shared:decode",
            parents=["shared:source"],
            execution_domain=prefix_domain,
            timestamp_ms=1005,
        ),
        topology_row(
            topology_kind="shared_video_dag",
            event_kind="stage_complete",
            stage="preprocess",
            branch_id="shared",
            execution_id="shared:preprocess",
            parents=["shared:decode"],
            execution_domain=prefix_domain,
            timestamp_ms=1010,
        ),
    ]
    completion_ids: list[str] = []
    for index, branch in enumerate(BRANCHES):
        fanout_id = f"{branch}:fanout"
        analytics_id = f"{branch}:analytics"
        complete_id = f"{branch}:complete"
        branch_domain = f"host:branch-{branch}:pid-{400 + index}"
        rows.extend(
            [
                topology_row(
                    topology_kind="shared_video_dag",
                    event_kind="fanout",
                    stage="fanout",
                    branch_id=branch,
                    execution_id=fanout_id,
                    parents=["shared:preprocess"],
                    execution_domain=prefix_domain,
                    timestamp_ms=1011,
                ),
                topology_row(
                    topology_kind="shared_video_dag",
                    event_kind="stage_complete",
                    stage=branch,
                    branch_id=branch,
                    execution_id=analytics_id,
                    parents=[fanout_id],
                    execution_domain=branch_domain,
                    timestamp_ms=1020 + index * 2,
                ),
                topology_row(
                    topology_kind="shared_video_dag",
                    event_kind="branch_complete",
                    stage=branch,
                    branch_id=branch,
                    execution_id=complete_id,
                    parents=[analytics_id],
                    execution_domain=branch_domain,
                    timestamp_ms=1021 + index * 2,
                ),
            ]
        )
        completion_ids.append(complete_id)
    rows.append(
        topology_row(
            topology_kind="shared_video_dag",
            event_kind="join_complete",
            stage="join",
            branch_id="shared",
            execution_id="shared:join",
            parents=completion_ids,
            execution_domain="host:aggregator:pid-500",
            timestamp_ms=1030,
        )
    )
    return rows


def frame_events(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": row["run_id"],
                "trace_id": row["trace_id"],
                "stream_id": row["stream_id"],
                "frame_id": row["frame_id"],
                "stage": row["stage"],
                "stage_end_timestamp_ms": row["timestamp_ms"],
            }
            for row in rows
            if row["event_kind"] == "stage_complete"
        ]
    )


def write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=TOPOLOGY_EVENT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


class TopologyContractTests(unittest.TestCase):
    def validate(self, rows: list[dict[str, object]], kind: str) -> pd.DataFrame:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology_events.csv"
            write_rows(path, rows)
            return validate_topology_events(
                path,
                frames=frames(),
                frame_events=frame_events(rows),
                scenario=scenario(kind),
            )

    def test_valid_independent_process_topology(self) -> None:
        self.assertEqual(len(self.validate(baseline_rows(), "independent_processes")), 11)

    def test_baseline_branches_require_independent_execution_domains(self) -> None:
        rows = baseline_rows()
        for row in rows:
            if row["branch_id"] in BRANCHES:
                row["execution_domain"] = "host:one-process:pid-100"
        with self.assertRaisesRegex(ContractError, "independent execution domains"):
            self.validate(rows, "independent_processes")

    def test_valid_shared_fanout_and_join_topology(self) -> None:
        self.assertEqual(len(self.validate(shared_rows(), "shared_video_dag")), 10)

    def test_shared_topology_requires_every_fanout_execution(self) -> None:
        rows = [row for row in shared_rows() if row["execution_id"] != "damage:fanout"]
        with self.assertRaisesRegex(ContractError, "parent .* outside the frame trace"):
            self.validate(rows, "shared_video_dag")

    def test_stage_completion_must_link_to_native_frame_event(self) -> None:
        rows = shared_rows()
        events = frame_events(rows)
        events.loc[events["stage"] == "decode", "stage_end_timestamp_ms"] = 9999
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "topology_events.csv"
            write_rows(path, rows)
            with self.assertRaisesRegex(ContractError, "does not match exactly one native frame event"):
                validate_topology_events(path, frames=frames(), frame_events=events, scenario=scenario("shared_video_dag"))

    def test_topology_trace_rejects_derived_provenance(self) -> None:
        rows = shared_rows()
        rows[0]["event_provenance"] = "derived_from_stage_labels"
        with self.assertRaisesRegex(ContractError, "not a native runtime event"):
            self.validate(rows, "shared_video_dag")

    def test_all_branches_must_share_input_frame_identity(self) -> None:
        rows = baseline_rows()
        rows[5]["input_frame_key"] = "different-source-frame"
        with self.assertRaisesRegex(ContractError, "do not share one input_frame_key"):
            self.validate(rows, "independent_processes")

    def test_publication_summary_requires_complete_topology_trace(self) -> None:
        config = {
            "benchmark": {"report_scenarios": ["proof"]},
            "scenarios": {"proof": {"benchmark_status": "supported"}},
        }
        summary = pd.DataFrame(
            [
                {
                    "scenario": "proof",
                    "system": "deepstream",
                    "policy": "heft",
                    "repeat": 1,
                    "status": "completed",
                    "run_mode": "benchmark",
                    "telemetry_source": "native",
                    "deadline_ms": 50.0,
                    "topology_trace_complete": False,
                }
            ]
        )
        with self.assertRaisesRegex(ContractError, "requires complete native topology traces"):
            validate_report_inputs(summary, config)

        summary["topology_trace_complete"] = True
        with self.assertRaisesRegex(ContractError, "missing ingress cohort fields"):
            validate_report_inputs(summary, config)

        summary["ingress_ledger_complete"] = True
        summary["ingress_frame_count"] = 1
        summary["completed_frame_count"] = 1
        summary["dropped_frame_count"] = 0
        summary["censored_frame_count"] = 0
        summary["ingress_censoring_rule"] = "drain_to_empty"
        summary["frames"] = 1
        with self.assertRaisesRegex(ContractError, "missing branch terminal fields"):
            validate_report_inputs(summary, config)

        summary["branch_terminal_trace_complete"] = True
        summary["branch_terminal_event_count"] = 4
        summary["native_branch_drop_event_count"] = 0
        summary["checkpoint_frame_aggregation_complete"] = True
        summary["branch_analytics_contract_sha256"] = "b" * 64
        with self.assertRaisesRegex(ContractError, "missing stage semantic contract fields"):
            validate_report_inputs(summary, config)

        summary["stage_semantic_contract_complete"] = True
        summary["semantic_contract_version"] = STAGE_SEMANTIC_CONTRACT_VERSION
        summary["semantic_prefix_contract_sha256"] = "a" * 64
        with self.assertRaisesRegex(ContractError, "missing measurement passport fields"):
            validate_report_inputs(summary, config)

        for field, value in measurement_passport_fields().items():
            summary[field] = value
        validate_report_inputs(summary, config)

        component_drift = summary.copy()
        component_drift.loc[0, "c_obs_gpu_total_ms"] = 7.0
        with self.assertRaisesRegex(ContractError, "complete native measurement passport"):
            validate_report_inputs(component_drift, config)

        canonical_payload = json.loads(
            str(summary.loc[0, "measurement_signature_payload_json"])
        )
        semantic_drifts = {}
        missing_semantics = dict(canonical_payload)
        missing_semantics.pop("resource_time_non_equivalence")
        semantic_drifts["missing_semantics"] = missing_semantics
        altered_components = dict(canonical_payload)
        altered_components["resource_time_components"] = ["gpu_time_ms"]
        semantic_drifts["altered_components"] = altered_components
        unsupported_provenance = dict(canonical_payload)
        unsupported_provenance["resource_time_provenance"] = ["summary_proxy"]
        semantic_drifts["unsupported_provenance"] = unsupported_provenance
        unordered_provenance = dict(canonical_payload)
        unordered_provenance["resource_time_provenance"] = [
            "native_hardware_counter",
            "derived_from_native_stage_timestamps",
        ]
        semantic_drifts["unordered_provenance"] = unordered_provenance
        unknown_field = dict(canonical_payload)
        unknown_field["future_component"] = "implicitly_supported"
        semantic_drifts["unknown_field"] = unknown_field

        for label, payload in semantic_drifts.items():
            with self.subTest(label=label):
                semantic_drift = summary.copy()
                payload_json = json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                semantic_drift.loc[0, "measurement_signature_payload_json"] = payload_json
                semantic_drift.loc[0, "measurement_signature"] = hashlib.sha256(
                    payload_json.encode("utf-8")
                ).hexdigest()
                with self.assertRaisesRegex(
                    ContractError,
                    "complete native measurement passport",
                ):
                    validate_report_inputs(semantic_drift, config)

        canonical_payload_json = str(
            summary.loc[0, "measurement_signature_payload_json"]
        )
        identity_drifts = {
            "reordered_keys": json.dumps(
                dict(reversed(list(canonical_payload.items()))),
                sort_keys=False,
                separators=(",", ":"),
                ensure_ascii=True,
            ),
            "noncanonical_whitespace": json.dumps(
                canonical_payload,
                sort_keys=True,
                indent=1,
                ensure_ascii=True,
            ),
            "duplicate_key": (
                canonical_payload_json[:-1] + ',"contract_version":4}'
            ),
        }
        for label, payload_json in identity_drifts.items():
            with self.subTest(label=label):
                identity_drift = summary.copy()
                identity_drift.loc[0, "measurement_signature_payload_json"] = payload_json
                with self.assertRaisesRegex(
                    ContractError,
                    "complete native measurement passport",
                ):
                    validate_report_inputs(identity_drift, config)

        duplicated = pd.concat(
            [
                summary.assign(summary_path="first/summary.csv"),
                summary.assign(summary_path="second/summary.csv"),
            ],
            ignore_index=True,
        )
        with self.assertRaisesRegex(
            ContractError,
            "duplicate rows for one expected matrix cell",
        ):
            validate_report_inputs(duplicated, config)

        summary["run_mode"] = "smoke"
        with self.assertRaisesRegex(ContractError, "only accepts run_mode=benchmark"):
            validate_report_inputs(summary, config)
        summary["run_mode"] = "benchmark"

        summary["ingress_frame_count"] = 2
        with self.assertRaisesRegex(ContractError, "closed or explicitly censored ingress balance"):
            validate_report_inputs(summary, config)

    def test_publication_summary_requires_matching_pair_censoring_rule(self) -> None:
        baseline = "checkpoint_independent_processes_baseline"
        shared = "checkpoint_video_dag_shared"
        config = {
            "benchmark": {"report_scenarios": [baseline, shared]},
            "scenarios": {
                baseline: {"benchmark_status": "supported"},
                shared: {"benchmark_status": "supported"},
            },
        }
        common = {
            "system": "deepstream",
            "policy": "static_hybrid",
            "dataset": "kpp_real_h264",
            "deadline_ms": 50.0,
            "streams": 6,
            "scenario_variant": "six_streams",
            "repeat": 1,
            "status": "completed",
            "run_mode": "benchmark",
            "telemetry_source": "native",
            "topology_trace_complete": True,
            "branch_terminal_trace_complete": True,
            "branch_terminal_event_count": 4,
            "native_branch_drop_event_count": 1,
            "checkpoint_frame_aggregation_complete": True,
            "branch_analytics_contract_sha256": "b" * 64,
            "stage_semantic_contract_complete": True,
            "semantic_contract_version": STAGE_SEMANTIC_CONTRACT_VERSION,
            "semantic_prefix_contract_sha256": "a" * 64,
            "ingress_ledger_complete": True,
            "ingress_frame_count": 2,
            "completed_frame_count": 1,
            "dropped_frame_count": 1,
            "censored_frame_count": 0,
            "frames": 1,
            **measurement_passport_fields(ingress_count=2),
        }
        summary = pd.DataFrame(
            [
                {**common, "scenario": baseline, "ingress_censoring_rule": "fixed_drain_500ms"},
                {**common, "scenario": shared, "ingress_censoring_rule": "fixed_drain_1000ms"},
            ]
        )

        with self.assertRaisesRegex(ContractError, "must use one ingress censoring rule"):
            validate_report_inputs(summary, config)

        summary.loc[:, "ingress_censoring_rule"] = "fixed_drain_500ms"
        validate_report_inputs(summary, config)
        passports = build_measurement_passports(summary, config)
        self.assertEqual(list(passports["scenario"]), [baseline, shared])
        self.assertEqual(set(passports["c_obs_is_partial"]), {True})

        summary.loc[summary["scenario"] == shared, "semantic_prefix_contract_sha256"] = "b" * 64
        with self.assertRaisesRegex(ContractError, "must use one semantic prefix contract"):
            validate_report_inputs(summary, config)

        summary.loc[:, "semantic_prefix_contract_sha256"] = "a" * 64
        summary.loc[
            summary["scenario"] == shared,
            "branch_analytics_contract_sha256",
        ] = "c" * 64
        with self.assertRaisesRegex(ContractError, "must use one branch analytics contract"):
            validate_report_inputs(summary, config)

        summary.loc[:, "branch_analytics_contract_sha256"] = "b" * 64
        summary.loc[summary["scenario"] == shared, "input_schedule_sha256"] = "d" * 64
        with self.assertRaisesRegex(ContractError, "must use one native input schedule"):
            validate_report_inputs(summary, config)

    def test_report_matrix_rejects_out_of_contract_rows_but_allows_missing_cells(self) -> None:
        config = {
            "protocol": {"repeats": 2},
            "benchmark": {
                "report_scenarios": ["proof"],
                "report_deadline_ms": [50],
                "report_datasets": ["dataset-a"],
                "scheduler_policies": ["static_hybrid"],
                "scheduler_ablations": [],
            },
            "scenarios": {
                "proof": {
                    "distributed": {"enabled": False},
                }
            },
            "systems": {"gstreamer_custom": {}},
        }
        row = {
            "dataset": "dataset-a",
            "scenario": "proof",
            "deadline_ms": 50.0,
            "deployment_mode": "heterogeneous",
            "host_topology": "single_host",
            "system": "gstreamer_custom",
            "policy": "static_hybrid",
            "repeat": 1,
        }
        # Repeat 2 is intentionally absent and remains visible as a missing audit cell.
        validate_report_matrix_membership(pd.DataFrame([row]), config, repeats=2)

        for field, value in (
            ("dataset", "dataset-b"),
            ("deadline_ms", 100.0),
            ("deployment_mode", "single-server-distributed"),
            ("host_topology", "single_host_ssh"),
            ("system", "other-system"),
            ("policy", "other-policy"),
            ("repeat", 3),
        ):
            with self.subTest(field=field):
                outside = pd.DataFrame([{**row, field: value}])
                with self.assertRaisesRegex(ContractError, "outside the expected matrix"):
                    validate_report_matrix_membership(outside, config, repeats=2)

        unknown = pd.DataFrame([{**row, "scenario": "not-a-report-scenario"}])
        with self.assertRaisesRegex(ContractError, "non-report scenarios"):
            validate_report_matrix_membership(unknown, config, repeats=2)

    def test_distributed_executor_collects_topology_fragments(self) -> None:
        body = (ROOT / "scripts" / "distributed_executor.py").read_text(encoding="utf-8")

        self.assertIn('"topology_events*.csv"', body)
        self.assertIn("distributed checkpoint run did not produce topology_events.csv", body)
        self.assertIn("_combine_csv(topology_paths, topology_events_csv, TOPOLOGY_EVENT_COLUMNS)", body)
        self.assertIn('"ingress_ledger*.csv"', body)
        self.assertIn("distributed checkpoint run did not produce ingress_ledger.csv", body)
        self.assertIn("_combine_csv(ingress_paths, ingress_ledger_csv, INGRESS_LEDGER_COLUMNS)", body)
        self.assertIn('"branch_terminals*.csv"', body)
        self.assertIn("distributed checkpoint run did not produce branch_terminals.csv", body)
        self.assertIn("_combine_csv(terminal_paths, branch_terminals_csv, BRANCH_TERMINAL_COLUMNS)", body)
        self.assertIn('"stage_contracts*.csv"', body)
        self.assertIn("distributed checkpoint run did not produce stage_contracts.csv", body)
        self.assertIn("_combine_csv(contract_paths, stage_contracts_csv, STAGE_CONTRACT_COLUMNS)", body)


if __name__ == "__main__":
    unittest.main()
