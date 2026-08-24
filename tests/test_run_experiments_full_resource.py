from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError, FULL_RESOURCE_PUBLICATION_SCOPE  # noqa: E402
from collect_metrics import HardwareResourceCollector  # noqa: E402
from run_experiments import (  # noqa: E402
    checkpoint_full_resource_acceptance_transaction,
    make_hardware_resource_collector,
    summary_fieldnames,
)
from checkpoint_gstreamer_runtime import full_resource_publication_requested  # noqa: E402
from tests.test_checkpoint_acceptance_metadata_binding import execution  # noqa: E402


def load_config() -> dict:
    with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
        return yaml.safe_load(source)


def resource_capability_grant() -> dict:
    grant = {
        "schema_version": 1,
        "artifact_kind": "vast_verified_pre_run_resource_capability_grant",
        "status": "accepted_pre_run_resource_capability_qualification",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": "a" * 64,
        "qualification_receipt": {
            "path": "artifacts/checkpoint_full_resource_qualification_receipt.json",
            "size_bytes": 101,
            "sha256": "b" * 64,
        },
        "capability_manifest": {
            "path": "artifacts/checkpoint_full_resource_capability_manifest.json",
            "size_bytes": 202,
            "sha256": "c" * 64,
        },
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    grant["grant_sha256"] = hashlib.sha256(
        json.dumps(
            grant,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return grant


class RunExperimentsFullResourceTests(unittest.TestCase):
    def test_verified_full_resource_path_explicitly_defers_child_acceptance(self) -> None:
        config = load_config()
        extension = config["benchmark"]["resource_interval_extension"]
        self.assertFalse(extension["evidence_accepted"])
        self.assertFalse(full_resource_publication_requested(config))
        self.assertTrue(
            full_resource_publication_requested(config, explicit_defer=True)
        )
        template = (ROOT / "scripts" / "run_system_template.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("CHECKPOINT_DEFER_FULL_RESOURCE_ACCEPTANCE", template)
        self.assertIn("--defer-full-resource-acceptance", template)

    def test_summary_schema_exposes_article_ready_v2_resource_metrics(self) -> None:
        expected = {
            "full_resource_evidence_accepted",
            "full_resource_coverage_complete",
            "resource_contract_version",
            "nvdec_busy_equivalent_ns",
            "nvdec_counter_scope",
            "fanout_thread_cpu_time_ns",
            "fanout_work_units",
            "fanout_counter_scope",
        }
        self.assertTrue(expected.issubset(summary_fieldnames()))
    def test_collector_is_disabled_until_v2_scope_is_accepted(self) -> None:
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            collector = make_hardware_resource_collector(
                config,
                mode="benchmark",
                system="deepstream",
                scenario=config["scenarios"]["checkpoint_video_dag_shared"],
                scenario_name="checkpoint_video_dag_shared",
                policy="adaptive_weights",
                run_dir=Path(tmp),
                run_id="run-1",
                interval_s=1.0,
            )
        self.assertIsNone(collector)

    def test_verified_pre_run_grant_binds_collector_while_post_run_config_is_false(self) -> None:
        config = copy.deepcopy(load_config())
        self.assertFalse(config["benchmark"]["resource_interval_extension"]["evidence_accepted"])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = make_hardware_resource_collector(
                config,
                mode="benchmark",
                system="deepstream",
                scenario=config["scenarios"]["checkpoint_video_dag_shared"],
                scenario_name="checkpoint_video_dag_shared",
                policy="adaptive_weights",
                run_dir=root,
                run_id="run-1",
                interval_s=1.0,
                resource_capability_grant=resource_capability_grant(),
            )

            self.assertIsInstance(collector, HardwareResourceCollector)
            assert collector is not None
            self.assertEqual(collector.output_csv, root / "hardware_resource_samples.csv")
            self.assertEqual(collector.run_id, "run-1")

    @staticmethod
    def _transaction_kwargs(
        root: Path,
        collector: object | None,
        *,
        required: bool = True,
        mode: str = "benchmark",
        scenario: dict | None = None,
        codec: str | None = "h264",
        started: bool = True,
        closed: bool = True,
    ) -> dict:
        return {
            "full_resource_required": required,
            "mode": mode,
            "scenario": scenario
            or {
                "name": "checkpoint_video_dag_shared",
                "topology": {"kind": "shared_video_dag"},
            },
            "checkpoint_codec": codec,
            "hardware_collector": collector,
            "hardware_collector_started": started,
            "hardware_collector_closed": closed,
            "output_dir": root,
            "expected_run_id": "run-1",
            "expected_system": "gstreamer_custom",
            "expected_policy": "adaptive_weights",
            "expected_deadline_ms": 100.0,
            "run_metadata_path": root / "run_metadata.json",
            "expected_execution_binding": execution(),
        }

    @staticmethod
    def _final_acceptance() -> dict:
        return {
            "artifact_kind": "checkpoint_publication_runtime_acceptance",
            "status": "accepted_native_checkpoint_arm",
            "summary": {
                "resource_contract_version": 1,
                "full_resource_evidence_accepted": False,
                "full_resource_coverage_complete": False,
                "nvdec_busy_equivalent_ns": 0,
                "nvdec_counter_scope": "unavailable",
                "fanout_thread_cpu_time_ns": 0,
                "fanout_work_units": 0,
                "fanout_counter_scope": "unavailable",
            },
            "full_resource_summary": {
                "resource_contract_version": 2,
                "evidence_accepted": True,
                "publication_bundle_bound": True,
                "full_resource_coverage_complete": True,
                "nvdec_busy_equivalent_ns": 123,
                "nvdec_counter_scope": "device_sample",
                "fanout_thread_cpu_time_ns": 456,
                "fanout_work_units": 789,
                "fanout_counter_scope": "per_trace_resource_work",
            },
            "acceptance_finalization": {
                "hardware_collector_stopped": True,
                "validation": "full_resource_evidence_v2_passed",
            },
        }

    def test_finalization_uses_authoritative_resource_summary_not_stale_candidate(self) -> None:
        collector = mock.Mock()
        collector.is_alive.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acceptance_path = root / "checkpoint_publication_acceptance.json"

            acceptance = self._final_acceptance()

            def commit(
                *, output_dir: Path, acceptance: dict,
                run_metadata_path: Path,
                expected_execution_binding: dict,
            ) -> dict:
                acceptance_path.write_text(
                    json.dumps(acceptance, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                return acceptance

            with mock.patch(
                "run_experiments.prepare_checkpoint_publication_acceptance",
                return_value=acceptance,
            ) as prepare, mock.patch(
                "run_experiments.commit_checkpoint_publication_acceptance",
                side_effect=commit,
            ) as commit_acceptance:
                with checkpoint_full_resource_acceptance_transaction(
                    **self._transaction_kwargs(root, collector)
                ) as finalized_summary:
                    self.assertFalse(acceptance_path.exists())
                    self.assertEqual(
                        finalized_summary,
                        {
                            "resource_contract_version": 2,
                            "full_resource_evidence_accepted": True,
                            "full_resource_coverage_complete": True,
                            "nvdec_busy_equivalent_ns": 123,
                            "nvdec_counter_scope": "device_sample",
                            "fanout_thread_cpu_time_ns": 456,
                            "fanout_work_units": 789,
                            "fanout_counter_scope": "per_trace_resource_work",
                        },
                    )

            prepare.assert_called_once_with(
                output_dir=root,
                expected_run_id="run-1",
                expected_system="gstreamer_custom",
                expected_scenario="checkpoint_video_dag_shared",
                expected_codec="h264",
                expected_policy="adaptive_weights",
                expected_deadline_ms=100.0,
                topology_kind="shared_video_dag",
                hardware_collector_stopped=True,
            )
            commit_acceptance.assert_called_once_with(
                output_dir=root,
                acceptance=acceptance,
                run_metadata_path=root / "run_metadata.json",
                expected_execution_binding=execution(),
            )
            self.assertTrue(acceptance_path.is_file())

    def test_finalization_fails_closed_without_started_and_closed_collector(self) -> None:
        cases = (
            (None, True, True, "collector"),
            (mock.Mock(), False, True, "started"),
            (mock.Mock(), True, False, "closed"),
        )
        for collector, started, closed, message in cases:
            if collector is not None:
                collector.is_alive.return_value = False
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                with mock.patch(
                    "run_experiments.prepare_checkpoint_publication_acceptance"
                ) as prepare, mock.patch(
                    "run_experiments.commit_checkpoint_publication_acceptance"
                ) as commit, self.assertRaisesRegex(ContractError, message):
                    with checkpoint_full_resource_acceptance_transaction(
                        **self._transaction_kwargs(
                            Path(tmp),
                            collector,
                            started=started,
                            closed=closed,
                        )
                    ):
                        self.fail("unreachable")
                prepare.assert_not_called()
                commit.assert_not_called()

    def test_finalization_rejects_alive_collector_and_non_checkpoint_scope(self) -> None:
        collector = mock.Mock()
        cases = (
            ({"alive": True}, "collector"),
            ({"mode": "smoke"}, "checkpoint benchmark topology"),
            ({"scenario": {"name": "other", "topology": {"kind": "other"}}}, "checkpoint"),
            ({"codec": None}, "checkpoint"),
        )
        for raw_overrides, message in cases:
            overrides = dict(raw_overrides)
            collector.is_alive.return_value = bool(overrides.pop("alive", False))
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                kwargs = self._transaction_kwargs(Path(tmp), collector, **overrides)
                with mock.patch(
                    "run_experiments.prepare_checkpoint_publication_acceptance"
                ) as prepare, mock.patch(
                    "run_experiments.commit_checkpoint_publication_acceptance"
                ) as commit, self.assertRaisesRegex(ContractError, message):
                    with checkpoint_full_resource_acceptance_transaction(**kwargs):
                        self.fail("unreachable")
                prepare.assert_not_called()
                commit.assert_not_called()

    def test_non_full_resource_run_never_calls_finalizer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch(
            "run_experiments.prepare_checkpoint_publication_acceptance"
        ) as prepare, mock.patch(
            "run_experiments.commit_checkpoint_publication_acceptance"
        ) as commit:
            with checkpoint_full_resource_acceptance_transaction(
                **self._transaction_kwargs(
                    Path(tmp),
                    None,
                    required=False,
                    started=False,
                    closed=False,
                )
            ) as finalized_summary:
                self.assertIsNone(finalized_summary)
        prepare.assert_not_called()
        commit.assert_not_called()

    def test_exception_before_last_commit_never_creates_accepted_arm(self) -> None:
        collector = mock.Mock()
        collector.is_alive.return_value = False
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            acceptance_path = root / "checkpoint_publication_acceptance.json"

            with mock.patch(
                "run_experiments.prepare_checkpoint_publication_acceptance",
                return_value=self._final_acceptance(),
            ) as prepare, mock.patch(
                "run_experiments.commit_checkpoint_publication_acceptance"
            ) as commit, self.assertRaisesRegex(RuntimeError, "metadata failed"):
                with checkpoint_full_resource_acceptance_transaction(
                    **self._transaction_kwargs(root, collector)
                ):
                    raise RuntimeError("metadata failed")

            prepare.assert_called_once()
            commit.assert_not_called()
            self.assertFalse(acceptance_path.exists())

    def test_process_kill_after_durable_metadata_cannot_leave_accepted_arm(self) -> None:
        script = r'''
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import run_experiments as target

root = Path(sys.argv[2])
acceptance = {
    "artifact_kind": "checkpoint_publication_runtime_acceptance",
    "status": "accepted_native_checkpoint_arm",
    "summary": {},
    "full_resource_summary": {
        "resource_contract_version": 2,
        "evidence_accepted": True,
        "publication_bundle_bound": True,
        "full_resource_coverage_complete": True,
        "nvdec_busy_equivalent_ns": 123,
        "nvdec_counter_scope": "device_sample",
        "fanout_thread_cpu_time_ns": 456,
        "fanout_work_units": 789,
        "fanout_counter_scope": "per_trace_resource_work",
    },
    "acceptance_finalization": {
        "hardware_collector_stopped": True,
        "validation": "full_resource_evidence_v2_passed",
    },
}

class ClosedCollector:
    def is_alive(self):
        return False

def prepare(**_kwargs):
    return acceptance

def commit(*, output_dir, acceptance, run_metadata_path, expected_execution_binding):
    (output_dir / "checkpoint_publication_acceptance.json").write_text(
        "accepted\n", encoding="utf-8"
    )
    return acceptance

target.prepare_checkpoint_publication_acceptance = prepare
target.commit_checkpoint_publication_acceptance = commit
with target.checkpoint_full_resource_acceptance_transaction(
    full_resource_required=True,
    mode="benchmark",
    scenario={
        "name": "checkpoint_video_dag_shared",
        "topology": {"kind": "shared_video_dag"},
    },
    checkpoint_codec="h264",
    hardware_collector=ClosedCollector(),
    hardware_collector_started=True,
    hardware_collector_closed=True,
    output_dir=root,
    expected_run_id="run-1",
    expected_system="gstreamer_custom",
    expected_policy="adaptive_weights",
    expected_deadline_ms=100.0,
    run_metadata_path=root / "run_metadata.json",
    expected_execution_binding={
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_arm_execution_binding",
        "run_identity_sha256": "1" * 64,
        "sequence": 7,
        "pair_id": "pair-7",
        "attempt": 2,
        "arm_id": "arm-1",
    },
):
    target.write_durable_json(root / "run_metadata.json", {"status": "durable"})
    os._exit(73)
'''
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            completed = subprocess.run(
                [sys.executable, "-c", script, str(ROOT / "scripts"), str(root)],
                check=False,
            )
            self.assertEqual(completed.returncode, 73)
            self.assertEqual(
                json.loads((root / "run_metadata.json").read_text(encoding="utf-8")),
                {"status": "durable"},
            )
            self.assertFalse(
                (root / "checkpoint_publication_acceptance.json").exists()
            )


if __name__ == "__main__":
    unittest.main()
