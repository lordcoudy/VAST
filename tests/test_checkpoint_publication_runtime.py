#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError
from checkpoint_publication_runtime import (
    _accepted_branch_rows,
    _accepted_frame_event_rows,
    _accepted_ingress_rows,
)
from checkpoint_runtime import RuntimeRunResult


RUN_ID = "publication-fixture"
TRACE_ID = f"{RUN_ID}:0:31"
INPUT_FRAME_KEY = "kpp_real_h264:0:" + "1" * 64 + ":0:2700000"


def runtime_result(**overrides: object) -> RuntimeRunResult:
    values: dict[str, object] = {
        "events": (),
        "unresolved_frames": (),
        "process_ids": {},
        "event_observed_ns": {},
        "process_exit_ns": {},
    }
    values.update(overrides)
    return RuntimeRunResult(**values)  # type: ignore[arg-type]


def ingress_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "run_id": RUN_ID,
        "trace_id": TRACE_ID,
        "input_frame_key": INPUT_FRAME_KEY,
        "stream_id": 0,
        "frame_id": 31,
        "window_start_timestamp_ms": 1_000,
        "window_end_timestamp_ms": 2_000,
        "terminal_status": "completed",
        "terminal_provenance": "native_completion_event",
    }
    row.update(overrides)
    return row


def event(
    *,
    kind: str,
    stage: str,
    execution_id: str,
    parents: str,
    timestamp_ms: int,
    branch_id: str = "not_applicable",
) -> dict[str, object]:
    return {
        "run_id": RUN_ID,
        "trace_id": TRACE_ID,
        "input_frame_key": INPUT_FRAME_KEY,
        "stream_id": 0,
        "frame_id": 31,
        "event_kind": kind,
        "stage": stage,
        "execution_id": execution_id,
        "parent_execution_ids_json": parents,
        "timestamp_ms": timestamp_ms,
        "execution_domain": "host:pid=100",
        "branch_id": branch_id,
    }


class CheckpointPublicationRuntimeTests(unittest.TestCase):
    def test_ingress_promotion_rejects_censoring_and_non_native_terminal_provenance(self) -> None:
        cases = (
            (
                ingress_row(
                    terminal_status="censored",
                    terminal_provenance="explicit_censoring_at_drain_end",
                ),
                "rejects censored",
            ),
            (ingress_row(terminal_provenance="runtime_contract_test_completion_event"), "non-native"),
        )
        for row, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ContractError, message):
                _accepted_ingress_rows(
                    runtime_result(terminal_ingress_rows=(row,)),
                    run_id=RUN_ID,
                )

    def test_branch_promotion_requires_protocol_v3_native_outcomes(self) -> None:
        ledger, cohort_id = _accepted_ingress_rows(
            runtime_result(terminal_ingress_rows=(ingress_row(),)),
            run_id=RUN_ID,
        )
        branch = {
            "run_id": RUN_ID,
            "trace_id": TRACE_ID,
            "input_frame_key": INPUT_FRAME_KEY,
            "stream_id": 0,
            "frame_id": 31,
            "branch_id": "damage",
            "runtime_protocol_version": 2,
            "telemetry_source": "native",
            "event_provenance": "native_runtime_event",
            "terminal_status": "completed",
            "terminal_timestamp_ms": 1_150,
            "objects": 1,
            "detector": "damage;model_sha256=" + "a" * 64,
            "backend": "gvadetect",
            "terminal_reason": "native_result_committed",
        }
        with self.assertRaisesRegex(ContractError, "protocol-v3"):
            _accepted_branch_rows(
                runtime_result(branch_terminal_records=(branch,)),
                ledger_rows=ledger,
                cohort_id=cohort_id,
                required_branches=["damage"],
            )

        branch["runtime_protocol_version"] = 3
        promoted = _accepted_branch_rows(
            runtime_result(branch_terminal_records=(branch,)),
            ledger_rows=ledger,
            cohort_id=cohort_id,
            required_branches=["damage"],
        )
        self.assertEqual(len(promoted), 1)
        self.assertEqual(promoted[0]["telemetry_source"], "native")

    def test_frame_intervals_are_derived_from_direct_parent_and_join_timestamps(self) -> None:
        events = (
            event(kind="source_read", stage="source", execution_id="source", parents="[]", timestamp_ms=1_100),
            event(kind="stage_complete", stage="decode", execution_id="decode", parents='["source"]', timestamp_ms=1_110),
            event(kind="stage_complete", stage="preprocess", execution_id="preprocess", parents='["decode"]', timestamp_ms=1_120),
            event(kind="stage_complete", stage="damage", execution_id="damage", parents='["preprocess"]', timestamp_ms=1_145, branch_id="damage"),
            event(kind="branch_complete", stage="damage", execution_id="terminal", parents='["damage"]', timestamp_ms=1_150, branch_id="damage"),
            event(kind="join_complete", stage="aggregate", execution_id="join", parents='["terminal"]', timestamp_ms=1_153),
        )
        rows = _accepted_frame_event_rows(
            runtime_result(events=events),
            ledger_rows=[ingress_row()],
            policy="static_hybrid",
        )
        by_stage = {str(row["stage"]): row for row in rows}
        self.assertEqual(by_stage["decode"]["stage_start_timestamp_ms"], 1_100)
        self.assertEqual(by_stage["preprocess"]["stage_start_timestamp_ms"], 1_110)
        self.assertEqual(by_stage["aggregate"]["stage_start_timestamp_ms"], 1_150)
        self.assertEqual(by_stage["aggregate"]["stage_end_timestamp_ms"], 1_153)
        self.assertEqual(by_stage["record"]["stage_start_timestamp_ms"], 1_153)
        self.assertEqual(by_stage["record"]["stage_end_timestamp_ms"], 1_153)


if __name__ == "__main__":
    unittest.main()
