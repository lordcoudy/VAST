#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from checkpoint_publication_runtime import (  # noqa: E402
    commit_checkpoint_publication_acceptance,
    finalize_checkpoint_publication_acceptance as finalize_acceptance,
    prepare_checkpoint_publication_acceptance,
)
from tests.test_checkpoint_acceptance_metadata_binding import (  # noqa: E402
    execution,
    metadata,
    write,
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_candidate(run_dir: Path, *, policy: str = "static_hybrid") -> Path:
    run_dir.mkdir(parents=True)
    base_evidence = (
        "frames.csv",
        "frame_events.csv",
        "resource_events.csv",
        "policy_decisions.csv",
        "publication_policy_decisions.jsonl",
        "drop_counters.csv",
        "topology_events.csv",
        "ingress_ledger.csv",
        "branch_terminals.csv",
        "stage_contracts.csv",
        "reset_evidence.csv",
    )
    adaptive_evidence = (
        "publication_policy_feedback.jsonl",
    ) if policy == "adaptive_weights" else ()
    evidence_files = (*base_evidence, *adaptive_evidence)
    for name in evidence_files:
        (run_dir / name).write_text(
            "run_id\nrun-001\n" if name in {
                "ingress_ledger.csv",
                "topology_events.csv",
                "frame_events.csv",
            } else (
                '{"artifact_kind":"test-native-policy-evidence"}\n'
                if name.endswith(".jsonl")
                else f"{name}\n"
            ),
            encoding="utf-8",
        )
    for name, payload in {
        "resource_intervals.csv": b"resource-native\n",
        "hardware_resource_samples.csv": b"hardware-native\n",
        "fanout_work_counters.csv": b"fanout-native\n",
    }.items():
        (run_dir / name).write_bytes(payload)
    candidate = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_candidate",
        "status": "pending_full_resource_validation",
        "run_id": "run-001",
        "system": "gstreamer_custom",
        "scenario": "checkpoint_video_dag_shared",
        "codec": "h264",
        "policy": policy,
        "deadline_ms": 100.0,
        "execution_binding_provenance": "native_scheduler_execution_binding_v1",
        "topology_kind": "shared_video_dag",
        "cohort_id": "run-001:measurement:1000:2000",
        "measurement_schedule_fingerprint_sha256": "a" * 64,
        "completed_frames_by_stream": {str(index): 1 for index in range(6)},
        "summary": {"ingress_ledger_complete": True},
        "evidence_sha256": {
            name: sha256(run_dir / name)
            for name in evidence_files
        },
        "pending_full_resource_evidence": [
            "resource_intervals.csv",
            "hardware_resource_samples.csv",
            "fanout_work_counters.csv",
        ],
    }
    path = run_dir / "checkpoint_publication_candidate.json"
    path.write_text(json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8")
    return path


def ensure_run_metadata(output_dir: Path) -> tuple[dict[str, object], Path]:
    expected_execution = execution()
    metadata_path = output_dir / "run_metadata.json"
    if not metadata_path.exists():
        write(metadata_path, metadata(expected_execution, output_dir))
        candidate_path = output_dir / "checkpoint_publication_candidate.json"
        candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
        evidence = candidate["evidence_sha256"]
        candidate["evidence_sha256"] = {
            name: sha256(output_dir / name) for name in evidence
        }
        candidate_path.write_text(
            json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8"
        )
    return expected_execution, metadata_path


def finalize_checkpoint_publication_acceptance(
    *, output_dir: Path, **kwargs: object
) -> dict[str, object]:
    expected_execution, metadata_path = ensure_run_metadata(output_dir)
    return finalize_acceptance(
        output_dir=output_dir,
        run_metadata_path=metadata_path,
        expected_execution_binding=expected_execution,
        **kwargs,
    )


class CheckpointAcceptanceFinalizationTests(unittest.TestCase):
    def test_every_policy_binds_canonical_policy_decisions_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir, policy="static_hybrid")
            assessment = {
                "summary": {
                    "resource_contract_version": 2,
                    "evidence_accepted": True,
                    "publication_bundle_bound": True,
                    "full_resource_coverage_complete": True,
                    "nvdec_busy_equivalent_ns": 123,
                    "nvdec_counter_scope": "device_sample",
                    "fanout_thread_cpu_time_ns": 456,
                    "fanout_work_units": 789,
                    "fanout_counter_scope": "per_trace_resource_work",
                }
            }
            with mock.patch(
                "checkpoint_publication_runtime.validate_full_resource_evidence",
                return_value=assessment,
            ):
                result = finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="static_hybrid",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )
            self.assertIn(
                "publication_policy_decisions.jsonl",
                result["evidence_sha256"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir, policy="gpu_only")
            ensure_run_metadata(run_dir)
            (run_dir / "publication_policy_decisions.jsonl").write_text(
                "mutated\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "candidate evidence hash drift"):
                finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="gpu_only",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )

    def test_adaptive_finalization_binds_both_canonical_policy_jsonl_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir, policy="adaptive_weights")
            assessment = {
                "summary": {
                    "resource_contract_version": 2,
                    "evidence_accepted": True,
                    "publication_bundle_bound": True,
                    "full_resource_coverage_complete": True,
                    "nvdec_busy_equivalent_ns": 123,
                    "nvdec_counter_scope": "device_sample",
                    "fanout_thread_cpu_time_ns": 456,
                    "fanout_work_units": 789,
                    "fanout_counter_scope": "per_trace_resource_work",
                }
            }
            with mock.patch(
                "checkpoint_publication_runtime.validate_full_resource_evidence",
                return_value=assessment,
            ):
                result = finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="adaptive_weights",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )
            self.assertIn(
                "publication_policy_decisions.jsonl",
                result["evidence_sha256"],
            )
            self.assertIn(
                "publication_policy_feedback.jsonl",
                result["evidence_sha256"],
            )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir, policy="adaptive_weights")
            ensure_run_metadata(run_dir)
            (run_dir / "publication_policy_feedback.jsonl").write_text(
                "mutated\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "candidate evidence hash drift"):
                finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="adaptive_weights",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )

    def test_final_acceptance_is_written_only_after_closed_hardware_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir)
            assessment = {
                "summary": {
                    "resource_contract_version": 2,
                    "evidence_accepted": True,
                    "publication_bundle_bound": True,
                    "full_resource_coverage_complete": True,
                    "nvdec_busy_equivalent_ns": 123,
                    "nvdec_counter_scope": "device_sample",
                    "fanout_thread_cpu_time_ns": 456,
                    "fanout_work_units": 789,
                    "fanout_counter_scope": "per_trace_resource_work",
                }
            }
            with mock.patch(
                "checkpoint_publication_runtime.validate_full_resource_evidence",
                return_value=assessment,
            ) as validate:
                result = prepare_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="static_hybrid",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )

            self.assertFalse(
                (run_dir / "checkpoint_publication_acceptance.json").exists()
            )
            write(
                run_dir / "run_metadata.json",
                metadata(execution(), run_dir),
            )
            committed = commit_checkpoint_publication_acceptance(
                output_dir=run_dir,
                acceptance=result,
                run_metadata_path=run_dir / "run_metadata.json",
                expected_execution_binding=execution(),
            )

            self.assertEqual(committed["status"], "accepted_native_checkpoint_arm")
            self.assertTrue(committed["summary"]["full_resource_evidence_accepted"])
            self.assertEqual(committed["summary"]["nvdec_counter_scope"], "device_sample")
            self.assertEqual(committed["summary"]["fanout_work_units"], 789)
            self.assertEqual(
                committed["summary"]["fanout_counter_scope"],
                "per_trace_resource_work",
            )
            self.assertEqual(
                set(committed["full_resource_evidence_sha256"]),
                {
                    "resource_intervals.csv",
                    "hardware_resource_samples.csv",
                    "fanout_work_counters.csv",
                },
            )
            self.assertTrue(
                (run_dir / "checkpoint_publication_acceptance.json").is_file()
            )
            self.assertTrue((run_dir / "checkpoint_publication_candidate.json").is_file())
            validate.assert_called_once()

    def test_finalizer_rejects_open_collector_and_candidate_evidence_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir)
            with self.assertRaisesRegex(ContractError, "collector"):
                finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="static_hybrid",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=False,
                )

            (run_dir / "frames.csv").write_bytes(b"mutated\n")
            with self.assertRaisesRegex(ContractError, "candidate evidence hash drift"):
                finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="static_hybrid",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )

    def test_finalizer_rejects_candidate_schema_deadline_and_topology_drift(self) -> None:
        mutations = (
            ("unexpected", True, "fields drifted"),
            ("deadline_ms", "not-a-number", "deadline_ms"),
            ("topology_kind", "independent_processes", "topology_kind"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "arm"
                candidate_path = prepare_candidate(run_dir)
                candidate = json.loads(candidate_path.read_text(encoding="utf-8"))
                candidate[field] = value
                candidate_path.write_text(
                    json.dumps(candidate, sort_keys=True) + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(ContractError, message):
                    finalize_checkpoint_publication_acceptance(
                        output_dir=run_dir,
                        expected_run_id="run-001",
                        expected_system="gstreamer_custom",
                        expected_scenario="checkpoint_video_dag_shared",
                        expected_codec="h264",
                        expected_policy="static_hybrid",
                        expected_deadline_ms=100.0,
                        topology_kind="shared_video_dag",
                        hardware_collector_stopped=True,
                    )

    def test_finalizer_rejects_missing_resource_summary_counters_as_contract_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "arm"
            prepare_candidate(run_dir)
            assessment = {
                "summary": {
                    "resource_contract_version": 2,
                    "evidence_accepted": True,
                    "publication_bundle_bound": True,
                    "full_resource_coverage_complete": True,
                }
            }
            with mock.patch(
                "checkpoint_publication_runtime.validate_full_resource_evidence",
                return_value=assessment,
            ), self.assertRaisesRegex(ContractError, "nvdec_busy_equivalent_ns"):
                finalize_checkpoint_publication_acceptance(
                    output_dir=run_dir,
                    expected_run_id="run-001",
                    expected_system="gstreamer_custom",
                    expected_scenario="checkpoint_video_dag_shared",
                    expected_codec="h264",
                    expected_policy="static_hybrid",
                    expected_deadline_ms=100.0,
                    topology_kind="shared_video_dag",
                    hardware_collector_stopped=True,
                )

    def test_finalizer_rejects_resource_scope_and_work_counter_drift(self) -> None:
        valid_summary = {
            "resource_contract_version": 2,
            "evidence_accepted": True,
            "publication_bundle_bound": True,
            "full_resource_coverage_complete": True,
            "nvdec_busy_equivalent_ns": 123,
            "nvdec_counter_scope": "device_sample",
            "fanout_thread_cpu_time_ns": 456,
            "fanout_work_units": 789,
            "fanout_counter_scope": "per_trace_resource_work",
        }
        mutations = (
            ("fanout_work_units", "invalid", "fanout_work_units"),
            ("nvdec_counter_scope", "unavailable", "nvdec_counter_scope"),
            ("fanout_counter_scope", "unavailable", "fanout_counter_scope"),
        )
        for field, value, message in mutations:
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                run_dir = Path(tmp) / "arm"
                prepare_candidate(run_dir)
                summary = dict(valid_summary)
                summary[field] = value
                with mock.patch(
                    "checkpoint_publication_runtime.validate_full_resource_evidence",
                    return_value={"summary": summary},
                ), self.assertRaisesRegex(ContractError, message):
                    finalize_checkpoint_publication_acceptance(
                        output_dir=run_dir,
                        expected_run_id="run-001",
                        expected_system="gstreamer_custom",
                        expected_scenario="checkpoint_video_dag_shared",
                        expected_codec="h264",
                        expected_policy="static_hybrid",
                        expected_deadline_ms=100.0,
                        topology_kind="shared_video_dag",
                        hardware_collector_stopped=True,
                    )

if __name__ == "__main__":
    unittest.main()
