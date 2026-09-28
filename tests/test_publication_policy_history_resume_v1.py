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

import tests.test_checkpoint_native_policy_runtime as native_fixture  # noqa: E402
import tests.test_full_publication_runtime as arm_fixture  # noqa: E402
from benchmark_contract import (  # noqa: E402
    ContractError,
    FULL_RESOURCE_PUBLICATION_SCOPE,
    build_publication_evidence_bundle,
    publication_evidence_bundle_identity,
    scenario_contract_identity,
)
from checkpoint_acceptance_metadata_binding import (  # noqa: E402
    bind_checkpoint_acceptance_to_durable_metadata,
)
from checkpoint_native_policy_runtime import NativePolicyRuntimeCoordinator  # noqa: E402
from full_publication_runner import ArmContext  # noqa: E402
from full_publication_runtime import FullPublicationRuntime  # noqa: E402
from publication_policy_contract import ANALYTICS_BRANCHES  # noqa: E402
from run_experiments import load_resumable_result, summary_fieldnames  # noqa: E402

HISTORY = "publication_policy_runtime_history.jsonl"


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class _AcceptedArmFixture:
    """Exercise physical custody; unrelated resource/authority facts use fixtures.

    New adaptive policy evidence is emitted by the actual in-process coordinator.
    This fixture never launches a video pipeline, service, worker, or cloud call.
    """

    def __init__(self, root: Path, *, policy: str, runtime_history: bool) -> None:
        self.root = root
        self.context = arm_fixture.pair_context(root, policy=policy)
        self.arm = self.context.pair["arms"][0]
        self.history_enabled = runtime_history
        self.runtime = FullPublicationRuntime(
            run_root=root,
            config={"benchmark": {}},
            cloud_store=arm_fixture.PreflightStore(),
            arm_runner=self._runner,
            readiness_validator=lambda _config: {"passed": True, "blockers": []},
            minimum_free_bytes=1,
            capacity_confirmed_gib=500,
        )
        self.result = self.runtime.execute_arm(ArmContext(self.context, 0, self.arm))
        self.arm_root = root / self.result["arm_root_relative_path"]
        self.acceptance_path = self.arm_root / "checkpoint_publication_acceptance.json"
        self.metadata_path = self.arm_root / "run_metadata.json"
        self.acceptance = json.loads(self.acceptance_path.read_text())
        self.metadata = json.loads(self.metadata_path.read_text())
        self.execution_binding = self.acceptance["publication_metadata_binding"]["execution_binding"]

    def _publish_adaptive_evidence(self, arm_root: Path, context: ArmContext) -> None:
        manifest = native_fixture.capability_manifest()
        coordinator = NativePolicyRuntimeCoordinator(
            run_id=context.arm["arm_id"],
            arm_id=context.arm["arm_id"],
            system=context.arm["system"],
            scenario=context.arm["scenario"],
            codec=context.arm["codec"],
            policy="adaptive_weights",
            deadline_ms=100.0,
            branches=ANALYTICS_BRANCHES,
            capability_manifest=manifest,
            calibration=native_fixture.calibration(manifest),
        )
        requests = []
        for frame_id in (1, 2):
            request = native_fixture.request_message(frame_id=frame_id, run_id=context.arm["arm_id"])
            request["trace_id"] = f"{context.arm['arm_id']}:0:{frame_id}:worker-plate"
            response = coordinator.handle_message(request["worker_id"], request)
            coordinator.handle_message(request["worker_id"], native_fixture.path_message(response, request=request))
            coordinator.handle_message(request["worker_id"], native_fixture.terminal_message(response, request=request))
            requests.append(request)
        measured = requests[1]
        with tempfile.TemporaryDirectory(dir=arm_root, prefix="policy-fixture-") as tmp:
            source = Path(tmp)
            coordinator.promote(source, canonical_frames={measured["input_frame_key"]: {
                "trace_id": f"{context.arm['arm_id']}:0:2", "stream_id": 0, "frame_id": 2,
            }})
            for name in (
                "policy_decisions.csv",
                "publication_policy_decisions.jsonl", "publication_policy_feedback.jsonl", HISTORY,
            ):
                (arm_root / name).write_bytes((source / name).read_bytes())

    def _runner(self, context: ArmContext, arm_root: Path) -> dict[str, object]:
        result = arm_fixture.accepted_arm_runner(context, arm_root)
        acceptance_path = arm_root / "checkpoint_publication_acceptance.json"
        metadata_path = arm_root / "run_metadata.json"
        acceptance = json.loads(acceptance_path.read_text())
        metadata = json.loads(metadata_path.read_text())
        original_binding = acceptance.pop("publication_metadata_binding")
        execution_binding = original_binding["execution_binding"]
        if self.history_enabled:
            self._publish_adaptive_evidence(arm_root, context)
            acceptance["evidence_sha256"][HISTORY] = _sha(arm_root / HISTORY)
        for name in acceptance["evidence_sha256"]:
            acceptance["evidence_sha256"][name] = _sha(arm_root / name)
        result_row = {field: "" for field in summary_fieldnames()}
        result_row.update(metadata["result"])
        result_row.update({
            "timestamp": "2026-09-28T00:00:00+00:00", "run_mode": "benchmark",
            "duration_s": 180, "telemetry_source": "native",
        })
        metadata["result"] = result_row
        metadata["resolved_scenario"] = {"topology": {"kind": "independent_processes"}}
        metadata["scenario_contract_identity"] = scenario_contract_identity(metadata["resolved_scenario"])
        bundle = build_publication_evidence_bundle(
            arm_root, scope=FULL_RESOURCE_PUBLICATION_SCOPE, policy=context.arm["policy"],
        )
        metadata["publication_evidence_bundle"] = bundle
        identity = publication_evidence_bundle_identity(bundle)
        metadata["publication_evidence_bundle_identity"] = {
            "schema_version": identity["schema_version"], "sha256": identity["sha256"],
        }
        _write(metadata_path, metadata)
        # The authority fixture emits a legacy backend output receipt before
        # our real adaptive policy bytes are installed. Isolate that unrelated
        # grant resolver, while retaining actual metadata bytes and binding.
        self.authority_setup = {
            key: value for key, value in original_binding.items()
            if key not in {"schema_version", "artifact_kind", "binding_sha256"}
        }
        self.authority_setup.update({
            "run_metadata_size_bytes": metadata_path.stat().st_size,
            "run_metadata_sha256": _sha(metadata_path),
            "publication_evidence_bundle_identity": metadata["publication_evidence_bundle_identity"],
        })
        with mock.patch("checkpoint_acceptance_metadata_binding._metadata_authorities", return_value=self.authority_setup):
            acceptance = bind_checkpoint_acceptance_to_durable_metadata(
                acceptance, run_metadata_path=metadata_path, expected_execution_binding=execution_binding,
            )
        _write(acceptance_path, acceptance)
        return result

    def read_arm(self) -> dict[str, object]:
        with mock.patch("checkpoint_acceptance_metadata_binding._metadata_authorities", return_value=self.authority_setup):
            return self.runtime._validate_arm_result(self.context, self.arm, self.result, arm_index=0)

    def resume(self) -> dict[str, object] | None:
        # Grant/scenario resolution is unrelated setup. Metadata binding, bundle
        # reconstruction, physical hash reads, and both target readers stay real.
        with (
            mock.patch("checkpoint_acceptance_metadata_binding._metadata_authorities", return_value=self.authority_setup),
            mock.patch("run_experiments.resolve_publication_run_contract", return_value=self.metadata["publication_run_contract"]),
            mock.patch("run_experiments.resolve_publication_evidence_bundle_scope", return_value=FULL_RESOURCE_PUBLICATION_SCOPE),
        ):
            return load_resumable_result(
                self.metadata_path,
                system_key=self.arm["system"], scenario_key=self.arm["scenario"],
                repeat_index=1, streams=6, duration_s=180, policy=self.arm["policy"],
                dataset_name=self.arm["dataset"], mode="benchmark", deadline_ms=100.0,
                scenario_contract=self.metadata["resolved_scenario"], config={},
                resource_capability_grant={"fixture": "unrelated-resource-setup"},
                backend_runtime_grant={"fixture": "unrelated-backend-setup"},
                model_parity_grant={"fixture": "unrelated-parity-setup"},
                expected_execution_binding=self.execution_binding,
            )

    def remove_only_history_pin(self) -> None:
        current = json.loads(self.acceptance_path.read_text())
        current["evidence_sha256"].pop(HISTORY)
        _write(self.acceptance_path, current)


class PublicationPolicyHistoryResumeTests(unittest.TestCase):
    def test_arm_reader_accepts_legacy_and_new_physical_namespaces(self) -> None:
        for policy, history in (("cpu_only", False), ("adaptive_weights", False), ("adaptive_weights", True)):
            with self.subTest(policy=policy, history=history), tempfile.TemporaryDirectory() as tmp:
                fixture = _AcceptedArmFixture(Path(tmp) / "run", policy=policy, runtime_history=history)
                record = fixture.read_arm()
                self.assertEqual(HISTORY in record["evidence_sha256"], history)
                if history:
                    self.assertEqual(record["evidence_sha256"][HISTORY], _sha(fixture.arm_root / HISTORY))

    def test_arm_reader_rejects_only_removed_history_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedArmFixture(Path(tmp) / "run", policy="adaptive_weights", runtime_history=True)
            self.assertIn(HISTORY, fixture.read_arm()["evidence_sha256"])
            metadata_bytes = fixture.metadata_path.read_bytes()
            history_bytes = (fixture.arm_root / HISTORY).read_bytes()
            fixture.remove_only_history_pin()
            self.assertEqual(fixture.metadata_path.read_bytes(), metadata_bytes)
            self.assertEqual((fixture.arm_root / HISTORY).read_bytes(), history_bytes)
            with self.assertRaises(ContractError):
                fixture.read_arm()

    def test_resume_reader_accepts_legacy_and_new_physical_namespaces(self) -> None:
        for policy, history in (("cpu_only", False), ("adaptive_weights", False), ("adaptive_weights", True)):
            with self.subTest(policy=policy, history=history), tempfile.TemporaryDirectory() as tmp:
                fixture = _AcceptedArmFixture(Path(tmp) / "run", policy=policy, runtime_history=history)
                self.assertEqual(fixture.resume(), fixture.metadata["result"])

    def test_resume_reader_rejects_only_removed_history_pin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = _AcceptedArmFixture(Path(tmp) / "run", policy="adaptive_weights", runtime_history=True)
            self.assertEqual(fixture.resume(), fixture.metadata["result"])
            metadata_bytes = fixture.metadata_path.read_bytes()
            history_bytes = (fixture.arm_root / HISTORY).read_bytes()
            fixture.remove_only_history_pin()
            self.assertEqual(fixture.metadata_path.read_bytes(), metadata_bytes)
            self.assertEqual((fixture.arm_root / HISTORY).read_bytes(), history_bytes)
            with self.assertRaises(ContractError):
                fixture.resume()


if __name__ == "__main__":
    unittest.main()
