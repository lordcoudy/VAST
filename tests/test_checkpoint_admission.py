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

from benchmark_contract import ContractError, INGRESS_LEDGER_COLUMNS, validate_ingress_ledger
from checkpoint_admission import (
    ADMISSION_PROVENANCE,
    DirectAdmissionCoordinator,
    SourceBinding,
    require_matching_persisted_schedule_fingerprints,
    require_matching_schedule_fingerprints,
)
from checkpoint_runtime import (
    DirectRuntimeJoinCoordinator,
    SourceLaunchSpec,
    WorkerBinding,
    WorkerLaunchSpec,
    build_runtime_reset_evidence,
    run_worker_processes,
)
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
SOURCE_SHA256 = "1" * 64
PAYLOAD_SHA256 = hashlib.sha256(b"compressed-access-unit").hexdigest()
WORKER_FIXTURE = ROOT / "tests" / "fixtures" / "checkpoint_event_worker.py"
SOURCE_FIXTURE = ROOT / "tests" / "fixtures" / "checkpoint_admission_source.py"


def admission_line(
    *,
    run_id: str,
    sequence: int = 1,
    source_cycle: int = 0,
    pts_ns: int = 90_000,
    schedule_offset_ns: int = 1_000_000,
    payload_sha256: str = PAYLOAD_SHA256,
) -> str:
    stream_id = 0
    return json.dumps(
        {
            "protocol_version": 1,
            "source_process_id": "stream-0-source-coordinator",
            "sequence": sequence,
            "run_id": run_id,
            "dataset_id": "kpp_real_h264",
            "stream_id": stream_id,
            "admission_id": f"{run_id}:{stream_id}:admission:{sequence}",
            "input_frame_key": f"kpp_real_h264:{stream_id}:{SOURCE_SHA256}:{source_cycle}:{pts_ns}",
            "source_sha256": SOURCE_SHA256,
            "source_cycle": source_cycle,
            "access_unit_pts_ns": pts_ns,
            "payload_sha256": payload_sha256,
            "payload_size_bytes": 22,
            "schedule_offset_ns": schedule_offset_ns,
            "admission_timestamp_ms": 1_000 + sequence,
            "event_provenance": ADMISSION_PROVENANCE,
        },
        separators=(",", ":"),
    )


def runtime_source_line(*, run_id: str, branch: str, sequence: int, payload_sha256: str = PAYLOAD_SHA256) -> str:
    return json.dumps(
        {
            "protocol_version": 2,
            "worker_id": f"stream-0-branch-{branch}",
            "sequence": 1,
            "run_id": run_id,
            "trace_id": f"{run_id}:{branch}:local:0",
            "stream_id": 0,
            "frame_id": 0,
            "input_frame_key": f"kpp_real_h264:0:{SOURCE_SHA256}:0:90000",
            "topology_kind": INDEPENDENT_PROCESSES,
            "event_kind": "source_read",
            "stage": "source",
            "branch_id": branch,
            "execution_id": f"{run_id}:{branch}:source:{sequence}",
            "parent_execution_ids": [],
            "timestamp_ms": 1_010 + sequence,
            "admission_id": f"{run_id}:0:admission:1",
            "payload_sha256": payload_sha256,
        },
        separators=(",", ":"),
    )


def admission_coordinator(run_id: str, *, topology_kind: str = INDEPENDENT_PROCESSES) -> DirectAdmissionCoordinator:
    return DirectAdmissionCoordinator(
        run_id=run_id,
        topology_kind=topology_kind,
        branches=BRANCHES,
        bindings=[
            SourceBinding(
                source_process_id="stream-0-source-coordinator",
                stream_id=0,
                pid=700,
                dataset_id="kpp_real_h264",
                source_sha256=SOURCE_SHA256,
                native_source=True,
            )
        ],
    )


class CheckpointAdmissionTests(unittest.TestCase):
    def test_process_runtime_acknowledges_source_before_fanout_to_workers(self) -> None:
        run_id = "process-admission-run"
        worker_specs = [
            WorkerLaunchSpec(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                command=(
                    sys.executable,
                    str(WORKER_FIXTURE),
                    "--mode",
                    "baseline",
                    "--branches",
                    ",".join(BRANCHES),
                    "--admission-linked",
                ),
            )
            for branch in BRANCHES
        ]
        source_specs = [
            SourceLaunchSpec(
                source_process_id="stream-0-source-coordinator",
                stream_id=0,
                dataset_id="kpp_real_h264",
                source_sha256=SOURCE_SHA256,
                command=(sys.executable, str(SOURCE_FIXTURE)),
                native_source=True,
            )
        ]
        result = run_worker_processes(
            run_id=run_id,
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            specs=worker_specs,
            source_specs=source_specs,
            timeout_s=3.0,
            synchronized_lifecycle=True,
            warmup_s=0.0,
            measurement_s=0.05,
            drain_timeout_s=0.25,
            start_lead_s=0.03,
            measurement_end_boundary_guard_ns=1_000_000,
        )
        self.assertEqual(len(result.process_ids), 4)
        self.assertEqual(set(result.source_process_ids), {"stream-0-source-coordinator"})
        self.assertEqual(sum(row["event_kind"] == "source_read" for row in result.events), 4)
        self.assertEqual(sum(row["event_kind"] == "join_complete" for row in result.events), 1)
        self.assertEqual(result.unresolved_frames, ())
        self.assertEqual(result.measurement_end_schedule_offset_ns, 49_000_000)
        self.assertIsNotNone(result.admission_audit)
        assert result.admission_audit is not None
        self.assertEqual(len(result.admission_records), 1)
        self.assertEqual(result.admission_records[0]["sequence"], 1)
        self.assertEqual(result.admission_audit["admission_count"], 1)
        self.assertEqual(result.admission_audit["complete_consumer_coverage_count"], 1)
        self.assertFalse(result.admission_audit["terminal_ingress_ledger_complete"])
        self.assertEqual(len(result.terminal_ingress_rows), 1)
        terminal_row = result.terminal_ingress_rows[0]
        self.assertEqual(terminal_row["terminal_status"], "completed")
        self.assertEqual(terminal_row["terminal_reason"], "all_required_branches_joined")
        self.assertEqual(terminal_row["telemetry_source"], "engineering_runtime")
        self.assertEqual(terminal_row["terminal_provenance"], "runtime_contract_test_completion_event")
        self.assertIsNotNone(result.terminal_admission_audit)
        assert result.terminal_admission_audit is not None
        self.assertTrue(result.terminal_admission_audit["engineering_terminal_closure_complete"])
        self.assertTrue(result.terminal_admission_audit["engineering_terminal_accounting_complete"])
        self.assertTrue(result.terminal_admission_audit["engineering_cohort_closed_without_censoring"])
        self.assertFalse(result.terminal_admission_audit["terminal_ingress_ledger_complete"])
        self.assertFalse(result.terminal_admission_audit["accepted_ingress_ledger_written"])
        self.assertEqual(
            result.lifecycle_statuses["stream-0-source-coordinator"],
            ("READY", "STARTED", "ADMISSION_STOPPED", "DRAINED"),
        )
        reset_rows, reset_audit = build_runtime_reset_evidence(
            run_id=run_id,
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            specs=worker_specs,
            source_specs=source_specs,
            result=result,
            telemetry_sink_id="d" * 64,
            telemetry_sink_preexisting_entry_count=0,
        )
        self.assertEqual(len(reset_rows), 5)
        self.assertEqual({row["telemetry_source"] for row in reset_rows}, {"engineering_runtime"})
        self.assertEqual(len({row["process_start_token"] for row in reset_rows}), 5)
        self.assertTrue(reset_audit["engineering_reset_state_complete"])
        self.assertFalse(reset_audit["accepted_reset_evidence_written"])

    def test_incomplete_admitted_shared_frame_is_explicitly_censored_at_drain(self) -> None:
        run_id = "process-admission-censored"
        result = run_worker_processes(
            run_id=run_id,
            topology_kind=SHARED_VIDEO_DAG,
            branches=BRANCHES,
            specs=[
                WorkerLaunchSpec(
                    worker_id="stream-0-shared-video-dag",
                    stream_id=0,
                    branch_id=None,
                    command=(
                        sys.executable,
                        str(WORKER_FIXTURE),
                        "--mode",
                        "shared",
                        "--branches",
                        ",".join(BRANCHES),
                        "--omit-branch",
                        "damage",
                        "--admission-linked",
                    ),
                )
            ],
            source_specs=[
                SourceLaunchSpec(
                    source_process_id="stream-0-source-coordinator",
                    stream_id=0,
                    dataset_id="kpp_real_h264",
                    source_sha256=SOURCE_SHA256,
                    command=(sys.executable, str(SOURCE_FIXTURE)),
                    native_source=True,
                )
            ],
            timeout_s=3.0,
            synchronized_lifecycle=True,
            warmup_s=0.0,
            measurement_s=0.05,
            drain_timeout_s=0.25,
            start_lead_s=0.03,
        )

        self.assertEqual(len(result.unresolved_frames), 1)
        self.assertEqual(len(result.terminal_ingress_rows), 1)
        terminal_row = result.terminal_ingress_rows[0]
        self.assertEqual(terminal_row["terminal_status"], "censored")
        self.assertEqual(terminal_row["terminal_timestamp_ms"], result.drain_end_timestamp_ms)
        self.assertEqual(terminal_row["censoring_rule"], "explicit_censoring_at_drain_end")
        self.assertEqual(terminal_row["terminal_provenance"], "explicit_censoring_at_drain_end")
        self.assertIsNotNone(result.terminal_admission_audit)
        assert result.terminal_admission_audit is not None
        self.assertEqual(result.terminal_admission_audit["completed_count"], 0)
        self.assertEqual(result.terminal_admission_audit["drop_count"], 0)
        self.assertEqual(result.terminal_admission_audit["censored_count"], 1)
        self.assertTrue(result.terminal_admission_audit["engineering_terminal_closure_complete"])
        self.assertTrue(result.terminal_admission_audit["engineering_terminal_accounting_complete"])
        self.assertFalse(result.terminal_admission_audit["engineering_cohort_closed_without_censoring"])
        self.assertFalse(result.terminal_admission_audit["native_drop_event_coverage_complete"])

    def test_runtime_terminal_ledger_is_rejected_by_publishable_validator(self) -> None:
        row = {
            "schema_version": 2,
            "run_id": "runtime-ledger-rejection",
            "cohort_id": "runtime-ledger-rejection:engineering-window:1000:2000",
            "trace_id": "runtime-ledger-rejection:0:0",
            "input_frame_key": f"kpp_real_h264:0:{SOURCE_SHA256}:0:90000",
            "admission_seq": 1,
            "source_sha256": SOURCE_SHA256,
            "source_cycle": 0,
            "access_unit_pts_ns": 90_000,
            "payload_sha256": PAYLOAD_SHA256,
            "payload_size_bytes": 4096,
            "schedule_offset_ns": 1_000_000,
            "stream_id": 0,
            "frame_id": 0,
            "ingress_timestamp_ms": 1100,
            "window_start_timestamp_ms": 1000,
            "window_end_timestamp_ms": 2000,
            "terminal_status": "completed",
            "terminal_timestamp_ms": 1200,
            "drain_end_timestamp_ms": 2200,
            "terminal_reason": "all_required_branches_joined",
            "censoring_rule": "drain_to_empty",
            "ingress_provenance": "native_ingress_event",
            "terminal_provenance": "native_completion_event",
            "telemetry_source": "engineering_runtime",
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "ingress_ledger.runtime.csv"
            with path.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=INGRESS_LEDGER_COLUMNS)
                writer.writeheader()
                writer.writerow(row)
            with self.assertRaisesRegex(
                ContractError,
                "benchmark mode only accepts telemetry_source=native in ingress_ledger.runtime.csv",
            ):
                validate_ingress_ledger(path, frames=pd.DataFrame())

    def test_direct_source_admission_precedes_and_matches_all_baseline_consumers(self) -> None:
        run_id = "baseline-run"
        admissions = admission_coordinator(run_id)
        admissions.accept(
            admission_line(run_id=run_id),
            observed_source_process_id="stream-0-source-coordinator",
            observed_pid=700,
        )
        bindings = [
            WorkerBinding(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                pid=800 + index,
                execution_domain=f"host:pid-{800 + index}",
                native_event_source=True,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        runtime = DirectRuntimeJoinCoordinator(
            run_id=run_id,
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
            admission_coordinator=admissions,
        )
        for index, branch in enumerate(BRANCHES):
            runtime.accept(
                runtime_source_line(run_id=run_id, branch=branch, sequence=index + 1),
                observed_worker_id=f"stream-0-branch-{branch}",
                observed_pid=800 + index,
            )
        audit = admissions.audit()
        self.assertTrue(audit["direct_source_schedule_observed"])
        self.assertEqual(audit["admission_count"], 1)
        self.assertEqual(audit["complete_consumer_coverage_count"], 1)
        self.assertFalse(audit["terminal_ingress_ledger_complete"])
        self.assertFalse(audit["accepted_ingress_ledger_written"])

    def test_worker_cannot_forge_payload_or_precede_source_admission(self) -> None:
        run_id = "baseline-run"
        admissions = admission_coordinator(run_id)
        binding = WorkerBinding(
            worker_id="stream-0-branch-plate_number",
            stream_id=0,
            branch_id="plate_number",
            pid=801,
            execution_domain="host:pid-801",
            native_event_source=True,
        )
        runtime = DirectRuntimeJoinCoordinator(
            run_id=run_id,
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=[
                binding,
                *[
                    WorkerBinding(
                        worker_id=f"stream-0-branch-{branch}",
                        stream_id=0,
                        branch_id=branch,
                        pid=802 + index,
                        execution_domain=f"host:pid-{802 + index}",
                        native_event_source=True,
                    )
                    for index, branch in enumerate(BRANCHES[1:])
                ],
            ],
            admission_coordinator=admissions,
        )
        with self.assertRaisesRegex(ContractError, "precedes its direct source admission"):
            runtime.accept(
                runtime_source_line(run_id=run_id, branch="plate_number", sequence=1),
                observed_worker_id=binding.worker_id,
                observed_pid=binding.pid,
            )

        admissions.accept(
            admission_line(run_id=run_id),
            observed_source_process_id="stream-0-source-coordinator",
            observed_pid=700,
        )
        with self.assertRaisesRegex(ContractError, "payload differs"):
            runtime.accept(
                runtime_source_line(
                    run_id=run_id,
                    branch="plate_number",
                    sequence=1,
                    payload_sha256="2" * 64,
                ),
                observed_worker_id=binding.worker_id,
                observed_pid=binding.pid,
            )

    def test_source_cycles_are_ordered_and_pair_fingerprint_excludes_run_id(self) -> None:
        baseline = admission_coordinator("baseline-run")
        shared = admission_coordinator("shared-run", topology_kind=SHARED_VIDEO_DAG)
        for coordinator, run_id in ((baseline, "baseline-run"), (shared, "shared-run")):
            for line in (
                admission_line(run_id=run_id, sequence=1, pts_ns=90_000, schedule_offset_ns=1_000_000),
                admission_line(run_id=run_id, sequence=2, pts_ns=120_000, schedule_offset_ns=2_000_000),
                admission_line(
                    run_id=run_id,
                    sequence=3,
                    source_cycle=1,
                    pts_ns=30_000,
                    schedule_offset_ns=3_000_000,
                ),
            ):
                coordinator.accept(
                    line,
                    observed_source_process_id="stream-0-source-coordinator",
                    observed_pid=700,
                )
        fingerprint = require_matching_schedule_fingerprints(baseline, shared)
        self.assertEqual(len(fingerprint), 64)
        baseline_audit = baseline.audit()
        shared_audit = shared.audit()
        baseline_audit["complete_consumer_coverage_count"] = baseline_audit["admission_count"]
        shared_audit["complete_consumer_coverage_count"] = shared_audit["admission_count"]
        self.assertEqual(
            require_matching_persisted_schedule_fingerprints(baseline_audit, shared_audit),
            fingerprint,
        )

        drifted = admission_coordinator("drifted-run", topology_kind=SHARED_VIDEO_DAG)
        drifted.accept(
            admission_line(run_id="drifted-run", schedule_offset_ns=1_000_001),
            observed_source_process_id="stream-0-source-coordinator",
            observed_pid=700,
        )
        with self.assertRaisesRegex(ContractError, "schedules differ"):
            require_matching_schedule_fingerprints(baseline, drifted)
        drifted_audit = drifted.audit()
        drifted_audit["complete_consumer_coverage_count"] = drifted_audit["admission_count"]
        with self.assertRaisesRegex(ContractError, "persisted baseline/shared admission schedules differ"):
            require_matching_persisted_schedule_fingerprints(baseline_audit, drifted_audit)

    def test_source_rejects_sequence_gap_and_nonincreasing_schedule(self) -> None:
        coordinator = admission_coordinator("run")
        coordinator.accept(
            admission_line(run_id="run"),
            observed_source_process_id="stream-0-source-coordinator",
            observed_pid=700,
        )
        with self.assertRaisesRegex(ContractError, "sequence is not gap-free"):
            coordinator.accept(
                admission_line(run_id="run", sequence=3, pts_ns=120_000, schedule_offset_ns=2_000_000),
                observed_source_process_id="stream-0-source-coordinator",
                observed_pid=700,
            )
        with self.assertRaisesRegex(ContractError, "schedule offsets must be strictly increasing"):
            coordinator.accept(
                admission_line(run_id="run", sequence=2, pts_ns=80_000, schedule_offset_ns=1_000_000),
                observed_source_process_id="stream-0-source-coordinator",
                observed_pid=700,
            )

    def test_source_accepts_decode_order_with_reordered_native_pts(self) -> None:
        coordinator = admission_coordinator("run")
        for line in (
            admission_line(run_id="run", sequence=1, pts_ns=0, schedule_offset_ns=0),
            admission_line(run_id="run", sequence=2, pts_ns=400_000, schedule_offset_ns=100_000),
            admission_line(run_id="run", sequence=3, pts_ns=200_000, schedule_offset_ns=200_000),
            admission_line(
                run_id="run",
                sequence=4,
                source_cycle=1,
                pts_ns=0,
                schedule_offset_ns=300_000,
            ),
        ):
            coordinator.accept(
                line,
                observed_source_process_id="stream-0-source-coordinator",
                observed_pid=700,
            )


if __name__ == "__main__":
    unittest.main()
