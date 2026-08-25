#!/usr/bin/env python3
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification_pilot_executor_v2 as target  # noqa: E402
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationOutcomeV3,
    NativePublicationRequestV3,
)


def canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value).rstrip(b"\n")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(value))


def descriptor(root: Path, path: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def acceptance_payload(cell: target.QualificationPilotCellV2) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_checkpoint_qualification_pilot_acceptance_v1",
        "status": "accepted_native_qualification_pilot",
        "scope": "pre_run_policy_and_full_resource_qualification_only",
        "run_id": cell.run_id,
        "arm_id": cell.arm_id,
        "coordinate": {
            "system": cell.system,
            "resource": cell.resource,
            "codec": cell.codec,
            "topology_kind": cell.topology_kind,
        },
        "scenario": cell.scenario,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "accepted_for_full_publication": False,
        "publication_ready": False,
        "authorization_eligible": False,
        "blockers": ["qualification_pilot_is_not_full_publication_arm"],
    }


def write_child_evidence(
    output_dir: Path,
    cell: target.QualificationPilotCellV2,
    evidence_names: tuple[str, ...] = target.CHILD_EVIDENCE_FILES,
) -> None:
    candidate_name = "checkpoint_publication_candidate.json"
    for name in evidence_names:
        if name != candidate_name:
            (output_dir / name).write_text(
                f"{cell.run_id}:{name}\n", encoding="utf-8"
            )
    prefinal_names = target.CHILD_EVIDENCE_FILES[:-3]
    candidate = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_candidate",
        "status": "pending_full_resource_validation",
        "run_id": cell.run_id,
        "system": cell.system,
        "scenario": cell.scenario,
        "codec": cell.codec,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "execution_binding_provenance": "native_scheduler_execution_binding_v1",
        "topology_kind": cell.topology_kind,
        "cohort_id": f"cohort-{cell.arm_id}",
        "measurement_schedule_fingerprint_sha256": "6" * 64,
        "completed_frames_by_stream": {str(index): 1 for index in range(6)},
        "summary": {},
        "evidence_sha256": {
            name: sha256(output_dir / name) for name in prefinal_names
        },
        "pending_full_resource_evidence": [
            "resource_intervals.csv",
            "hardware_resource_samples.csv",
            "fanout_work_counters.csv",
        ],
    }
    write_json(output_dir / candidate_name, candidate)


def write_request_child_evidence(request: NativePublicationRequestV3) -> None:
    cell = next(
        item
        for item in target.qualification_pilot_cells_v2()
        if item.arm_id == request.arm_id
    )
    write_child_evidence(
        request.output_dir,
        cell,
        request.launcher_evidence_files,
    )


def commit_pilot_output(
    pilot_root: Path, cell: target.QualificationPilotCellV2
) -> Path:
    final = (
        pilot_root / cell.system / cell.resource / cell.codec / cell.topology_kind
    )
    final.mkdir(parents=True)
    write_child_evidence(final, cell)
    (final / "hardware_resource_samples.csv").write_text("hardware\n", encoding="utf-8")
    write_json(final / target.ACCEPTANCE_FILENAME, acceptance_payload(cell))
    return final


class InputFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.input_dir = root / "qualification-input"
        self.bootstrap_dir = root / "bootstrap"
        self.pilot_root = root / "pilots"
        self.checkpoint = root / "state/pilot-execution.v2.json"
        self.input_dir.mkdir(parents=True)
        self.bootstrap_dir.mkdir()
        self.pilot_root.mkdir()
        self.checkpoint.parent.mkdir()
        self.policy_contract_sha256 = "1" * 64
        self.parity_binding_sha256 = "3" * 64
        self.physical_evidence_sha256 = canonical_sha([])

        self.candidate_manifest = self.input_dir / "candidate-manifest.json"
        manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_capability_manifest",
            "policy_contract_sha256": self.policy_contract_sha256,
            "systems": {system: {} for system in target.SYSTEMS},
        }
        write_json(self.candidate_manifest, manifest)

        self.candidate_index = self.input_dir / "candidate-index.json"
        index = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_index",
            "policy_contract_sha256": self.policy_contract_sha256,
            "dataset_manifest": {
                "path": "configs/datasets.yaml",
                "size_bytes": 1,
                "sha256": "2" * 64,
            },
            "bindings": [
                {
                    "system": system,
                    "branch": branch,
                    "resource": resource,
                }
                for system in target.SYSTEMS
                for branch in ("plate_number", "vehicle_type", "damage", "foreign_object")
                for resource in target.RESOURCES
            ],
            "pilots": [],
        }
        write_json(self.candidate_index, index)

        self.candidate_receipt = self.input_dir / "candidate-receipt.json"
        receipt = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
            "status": "qualification_candidate_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "policy_contract_sha256": self.policy_contract_sha256,
            "qualification_index": descriptor(root, self.candidate_index),
            "candidate_manifest": descriptor(root, self.candidate_manifest),
            "blockers": ["candidate_is_not_a_full_publication_authority"],
        }
        receipt["sha256"] = canonical_sha(receipt)
        write_json(self.candidate_receipt, receipt)

        parity_dir = root / "accepted-parity"
        parity_dir.mkdir()
        self.parity_manifest = parity_dir / "manifest.yaml"
        self.parity_assessment = parity_dir / "assessment.json"
        self.parity_receipt = parity_dir / "receipt.json"
        self.parity_manifest.write_text("schema_version: 3\n", encoding="ascii")
        write_json(self.parity_assessment, {"accepted": True})
        write_json(self.parity_receipt, {"accepted": True})
        transaction_index = {
            "path": "accepted-parity/transaction-index.json",
            "size_bytes": 1,
            "sha256": "4" * 64,
        }

        calibrations: dict[str, object] = {}
        self.calibration_paths: dict[str, Path] = {}
        for system in target.SYSTEMS:
            path = self.bootstrap_dir / target.BOOTSTRAP_CALIBRATION_FILENAME.format(
                system=system
            )
            value = {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_calibration",
                "system": system,
                "policy_contract_sha256": self.policy_contract_sha256,
                "costs": {},
                "status": "qualification_bootstrap_not_accepted",
                "accepted": False,
                "publication_ready": False,
                "scope": "forced_resource_qualification_pilots_only",
                "authority": "nonaccepted_qualification_bootstrap_v2",
                "source_candidate_manifest_sha256": sha256(
                    self.candidate_manifest
                ),
                "source_model_parity_acceptance_binding_sha256": (
                    self.parity_binding_sha256
                ),
                "source_physical_response_evidence_sha256": (
                    self.physical_evidence_sha256
                ),
            }
            write_json(path, value)
            self.calibration_paths[system] = path
            calibrations[system] = value

        self.bootstrap_mapping = self.bootstrap_dir / "mapping.json"
        mapping = {
            "schema_version": 2,
            "artifact_kind": (
                "vast_publication_policy_qualification_bootstrap_calibration_mapping"
            ),
            "status": "qualification_bootstrap_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "policy_contract_sha256": self.policy_contract_sha256,
            "aggregation_rule": (
                "median_of_accepted_physical_model_parity_samples_v2"
            ),
            "minimum_samples_per_branch_resource": 30,
            "candidate_manifest_sha256": sha256(self.candidate_manifest),
            "candidate_receipt_sha256": sha256(self.candidate_receipt),
            "model_parity_acceptance_binding_sha256": self.parity_binding_sha256,
            "calibration_evidence_sha256": canonical_sha([]),
            "physical_response_evidence_sha256": self.physical_evidence_sha256,
            "calibrations": calibrations,
        }
        write_json(self.bootstrap_mapping, mapping)

        self.bootstrap_receipt = self.bootstrap_dir / "receipt.json"
        bootstrap_receipt = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_bootstrap_receipt",
            "status": "qualification_bootstrap_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "authority": "nonaccepted_qualification_bootstrap_v2",
            "policy_contract_sha256": self.policy_contract_sha256,
            "candidate_manifest": descriptor(root, self.candidate_manifest),
            "candidate_receipt": descriptor(root, self.candidate_receipt),
            "candidate_receipt_identity_sha256": receipt["sha256"],
            "qualification_index": descriptor(root, self.candidate_index),
            "accepted_model_parity_manifest": descriptor(
                root, self.parity_manifest
            ),
            "accepted_model_parity_assessment": descriptor(
                root, self.parity_assessment
            ),
            "accepted_model_parity_receipt": descriptor(
                root, self.parity_receipt
            ),
            "model_parity_acceptance_binding_sha256": self.parity_binding_sha256,
            "accepted_model_parity_evidence_sha256": "5" * 64,
            "calibration_evidence": [],
            "calibration_evidence_sha256": canonical_sha([]),
            "transaction_index": transaction_index,
            "physical_response_evidence": [],
            "physical_response_evidence_sha256": self.physical_evidence_sha256,
            "mapping": descriptor(root, self.bootstrap_mapping),
            "calibrations": {
                system: descriptor(root, path)
                for system, path in self.calibration_paths.items()
            },
            "blockers": [
                "bootstrap_is_not_policy_qualification_acceptance",
                "bootstrap_is_not_full_publication_authority",
                "bootstrap_is_valid_only_for_forced_cpu_only_gpu_only_pilots",
            ],
        }
        bootstrap_receipt["receipt_sha256"] = canonical_sha(bootstrap_receipt)
        write_json(self.bootstrap_receipt, bootstrap_receipt)

        self.socket_path = root / "analytics.sock"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(self.socket_path))
        self.socket.listen(8)

    def close(self) -> None:
        self.socket.close()
        self.socket_path.unlink(missing_ok=True)

    def arguments(self) -> dict[str, object]:
        return {
            "project_root": self.root,
            "candidate_index_path": self.candidate_index,
            "candidate_manifest_path": self.candidate_manifest,
            "candidate_receipt_path": self.candidate_receipt,
            "bootstrap_mapping_path": self.bootstrap_mapping,
            "bootstrap_receipt_path": self.bootstrap_receipt,
            "bootstrap_dir": self.bootstrap_dir,
            "pilot_root": self.pilot_root,
            "checkpoint_path": self.checkpoint,
            "deadline_ms": 100,
            "duration_s": 180,
        }

    def request(
        self,
        cell: target.QualificationPilotCellV2,
        output_dir: Path,
        evidence_names: tuple[str, ...],
    ) -> NativePublicationRequestV3:
        info = self.socket_path.stat()
        socket_binding = {
            "path": str(self.socket_path),
            "device": int(info.st_dev),
            "inode": int(info.st_ino),
            "owner_uid": int(info.st_uid),
            "owner_gid": int(info.st_gid),
        }
        runtime_key = target.RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
        endpoint = {
            **socket_binding,
            "container_path": "/run/vast/analytics-execution.sock",
        }
        contract = {
            "defer_full_resource_acceptance": True,
            "evidence_mapping": {name: name for name in evidence_names},
            "container_engine_socket": socket_binding,
            "endpoint_sockets": (
                [
                    {
                        "host_path": endpoint.pop("path"),
                        **endpoint,
                    }
                ]
                if cell.system in {"deepstream", "savant"}
                else {"analytics_execution": endpoint}
            ),
        }
        runtime_inputs = {
            "system": cell.system,
            "resource": cell.resource,
            "scenario": cell.scenario,
            "topology_kind": cell.topology_kind,
            "codec": cell.codec,
            "policy": cell.policy,
            "deadline_ms": cell.deadline_ms,
            "duration_s": cell.duration_s,
            "streams": 6,
            "run_id": cell.run_id,
            "dataset": {runtime_key: contract},
        }
        return NativePublicationRequestV3(
            system=cell.system,
            topology_kind=cell.topology_kind,
            scenario=cell.scenario,
            project_root=self.root,
            output_dir=output_dir,
            arm_contract_path=self.candidate_index,
            arm_contract_file_sha256=sha256(self.candidate_index),
            run_id=cell.run_id,
            arm_id=cell.arm_id,
            runtime_inputs=runtime_inputs,
            launcher_evidence_files=evidence_names,
        )


class FakeCollector:
    def __init__(self, path: Path, *, run_id: str, events: list[tuple[str, str]]) -> None:
        self.path = path
        self.run_id = run_id
        self.events = events
        self.started = False
        self.stopped = False
        self.joined = False

    def start(self) -> None:
        self.started = True
        self.events.append((self.run_id, "collector.start"))
        self.path.write_text("hardware\n", encoding="utf-8")

    def wait_until_ready(self, *, timeout_s: float) -> None:
        if not self.started or timeout_s <= 0:
            raise AssertionError("collector readiness ordering drifted")

    def stop(self) -> None:
        self.stopped = True
        self.events.append((self.run_id, "collector.stop"))

    def join(self, timeout: float | None = None) -> None:
        if not self.stopped or timeout is None or timeout <= 0:
            raise AssertionError("collector join ordering drifted")
        self.joined = True
        self.events.append((self.run_id, "collector.join"))

    def is_alive(self) -> bool:
        return False

    def raise_if_failed(self) -> None:
        if not self.joined:
            raise AssertionError("collector was not joined")


class QualificationPilotExecutorV2ContractTests(unittest.TestCase):
    def setUp(self) -> None:
        def validate_fake_acceptance(**kwargs: object) -> dict[str, object]:
            path = kwargs["acceptance_path"]
            self.assertIsInstance(path, Path)
            return json.loads(path.read_text(encoding="ascii"))  # type: ignore[union-attr]

        patcher = mock.patch.object(
            target,
            "validate_checkpoint_qualification_pilot_acceptance_v1",
            side_effect=validate_fake_acceptance,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_frozen_matrix_is_exact_and_forced_resource_only(self) -> None:
        cells = target.qualification_pilot_cells_v2(
            deadline_ms=100, duration_s=180
        )
        self.assertEqual(len(cells), 32)
        self.assertEqual(
            {(cell.system, cell.resource, cell.codec, cell.topology_kind) for cell in cells},
            {
                (system, resource, codec, topology)
                for system in target.SYSTEMS
                for resource in target.RESOURCES
                for codec in target.CODECS
                for topology in target.TOPOLOGIES
            },
        )
        self.assertEqual(
            {cell.policy for cell in cells}, {"cpu_only", "gpu_only"}
        )
        self.assertEqual(
            {cell.resource: cell.policy for cell in cells},
            {"cpu": "cpu_only", "gpu": "gpu_only"},
        )
        self.assertEqual(
            {cell.topology_kind: cell.scenario for cell in cells},
            target.SCENARIO_BY_TOPOLOGY,
        )
        self.assertEqual(len({cell.run_id for cell in cells}), 32)
        self.assertEqual(len({cell.arm_id for cell in cells}), 32)
        self.assertTrue(all(cell.deadline_ms == 100 for cell in cells))
        self.assertTrue(all(cell.duration_s == 180 for cell in cells))

    def test_registry_is_the_four_direct_lower_native_runtime_callables(self) -> None:
        from checkpoint_deepstream_publication_runtime_v3 import (
            run_checkpoint_deepstream_publication_runtime_v3,
        )
        from checkpoint_gstreamer_publication_runtime_v3 import (
            run_checkpoint_gstreamer_publication_runtime_v3,
        )
        from checkpoint_openvino_gva_publication_runtime_v3 import (
            run_checkpoint_openvino_gva_publication_runtime_v3,
        )
        from checkpoint_savant_publication_runtime_v3 import (
            run_checkpoint_savant_publication_runtime_v3,
        )

        self.assertEqual(set(target.NATIVE_RUNTIME_REGISTRY), set(target.SYSTEMS))
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["deepstream"],
            run_checkpoint_deepstream_publication_runtime_v3,
        )
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["savant"],
            run_checkpoint_savant_publication_runtime_v3,
        )
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["openvino_gva"],
            run_checkpoint_openvino_gva_publication_runtime_v3,
        )
        self.assertIs(
            target.NATIVE_RUNTIME_REGISTRY["gstreamer_custom"],
            run_checkpoint_gstreamer_publication_runtime_v3,
        )

    def test_executes_32_cells_with_host_collector_and_nonauthorizing_commit_last(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            events: list[tuple[str, str]] = []
            requests: list[NativePublicationRequestV3] = []

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                request = fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )
                requests.append(request)
                return request

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                events.append((request.run_id, "runtime"))
                self.assertFalse(
                    (request.output_dir / "hardware_resource_samples.csv").exists()
                )
                self.assertNotIn(
                    "hardware_resource_samples.csv", request.launcher_evidence_files
                )
                self.assertNotIn(
                    "checkpoint_publication_acceptance.json",
                    request.launcher_evidence_files,
                )
                self.assertNotIn(
                    target.ACCEPTANCE_FILENAME, request.launcher_evidence_files
                )
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def collector_factory(
                path: Path, *, run_id: str
            ) -> FakeCollector:
                return FakeCollector(path, run_id=run_id, events=events)

            def finalizer(**kwargs: object) -> dict[str, object]:
                run_id = str(kwargs["expected_run_id"])
                output = kwargs["output_dir"]
                self.assertIsInstance(output, Path)
                output = output  # type: ignore[assignment]
                events.append((run_id, "finalize"))
                self.assertTrue((output / "hardware_resource_samples.csv").is_file())
                self.assertFalse(
                    (output / "checkpoint_publication_acceptance.json").exists()
                )
                self.assertTrue(kwargs["hardware_collector_stopped"])
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                acceptance = acceptance_payload(cell)
                write_json(output / target.ACCEPTANCE_FILENAME, acceptance)
                return acceptance

            registry = {system: runtime for system in target.SYSTEMS}
            try:
                result = target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry=registry,
                    request_factory=request_factory,
                    collector_factory=collector_factory,
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["completed_cells"], 32)
                self.assertEqual(len(requests), 32)
                for request in requests:
                    contract = request.runtime_inputs["dataset"][
                        target.RUNTIME_INPUT_KEY_BY_SYSTEM[request.system]
                    ]
                    self.assertIs(contract["defer_full_resource_acceptance"], True)
                    self.assertEqual(
                        [event for rid, event in events if rid == request.run_id],
                        [
                            "collector.start",
                            "runtime",
                            "collector.stop",
                            "collector.join",
                            "finalize",
                        ],
                    )
                checkpoint = json.loads(fixture.checkpoint.read_text(encoding="ascii"))
                self.assertEqual(checkpoint["status"], "completed")
                self.assertEqual(len(checkpoint["completed"]), 32)
                self.assertTrue(
                    all(
                        (fixture.pilot_root / entry["pilot_path"] / target.ACCEPTANCE_FILENAME).is_file()
                        for entry in checkpoint["completed"]
                    )
                )
            finally:
                fixture.close()

    def test_resume_skips_valid_commits_and_never_overwrites_a_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            calls: list[str] = []
            fail_after = 1

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                calls.append(request.run_id)
                if len(calls) > fail_after:
                    raise RuntimeError("injected interruption")
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                output = kwargs["output_dir"]
                cell = next(
                    item
                    for item in target.qualification_pilot_cells_v2()
                    if item.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell)
                write_json(output / target.ACCEPTANCE_FILENAME, value)  # type: ignore[operator]
                return value

            collector_factory = lambda path, run_id: FakeCollector(  # noqa: E731
                path, run_id=run_id, events=[]
            )
            registry = {system: runtime for system in target.SYSTEMS}
            try:
                with self.assertRaisesRegex(RuntimeError, "injected interruption"):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry=registry,
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                first_calls = list(calls)
                self.assertEqual(len(first_calls), 2)
                checkpoint = json.loads(fixture.checkpoint.read_text(encoding="ascii"))
                self.assertEqual(len(checkpoint["completed"]), 1)

                fail_after = 10_000
                target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry=registry,
                    request_factory=request_factory,
                    collector_factory=collector_factory,
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(calls.count(first_calls[0]), 1)
                count_after_resume = len(calls)
                target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry=registry,
                    request_factory=request_factory,
                    collector_factory=collector_factory,
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(len(calls), count_after_resume)

                collision = fixture.pilot_root / "deepstream/cpu/h264/independent_processes"
                frames = collision / "frames.csv"
                frames_before = frames.read_bytes()
                frames.write_text("tampered child evidence\n", encoding="utf-8")
                with self.assertRaises(target.QualificationPilotExecutorV2Error):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry=registry,
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                self.assertEqual(frames.read_text(encoding="utf-8"), "tampered child evidence\n")
                frames.write_bytes(frames_before)
                acceptance = collision / target.ACCEPTANCE_FILENAME
                acceptance.write_text("tampered\n", encoding="utf-8")
                before = acceptance.read_bytes()
                with self.assertRaises(target.QualificationPilotExecutorV2Error):
                    target.execute_qualification_pilots_v2(
                        **fixture.arguments(),
                        runtime_registry=registry,
                        request_factory=request_factory,
                        collector_factory=collector_factory,
                        acceptance_finalizer=finalizer,
                    )
                self.assertEqual(acceptance.read_bytes(), before)
            finally:
                fixture.close()

    def test_resume_adopts_orphan_commit_and_cleans_owned_staging_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InputFixture(Path(tmp).resolve())
            cells = target.qualification_pilot_cells_v2(deadline_ms=100, duration_s=180)
            adopted = cells[0]
            commit_pilot_output(fixture.pilot_root, adopted)
            stale_attempt = fixture.pilot_root / ".qualification-pilot-staging-v2" / (
                f"{adopted.arm_id}.stale"
            )
            (stale_attempt / "pilot").mkdir(parents=True)
            (stale_attempt / ".hardware_resource_samples.host.csv").write_text(
                "hardware\n",
                encoding="utf-8",
            )
            calls: list[str] = []

            def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                return fixture.request(
                    kwargs["cell"],  # type: ignore[arg-type]
                    kwargs["output_dir"],  # type: ignore[arg-type]
                    kwargs["evidence_names"],  # type: ignore[arg-type]
                )

            def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                calls.append(request.run_id)
                write_request_child_evidence(request)
                return NativePublicationOutcomeV3(exit_code=0)

            def finalizer(**kwargs: object) -> dict[str, object]:
                output = kwargs["output_dir"]
                self.assertIsInstance(output, Path)
                output = output  # type: ignore[assignment]
                cell = next(
                    cell
                    for cell in cells
                    if cell.arm_id == kwargs["expected_arm_id"]
                )
                value = acceptance_payload(cell)
                write_json(output / target.ACCEPTANCE_FILENAME, value)
                return value

            try:
                result = target.execute_qualification_pilots_v2(
                    **fixture.arguments(),
                    runtime_registry={system: runtime for system in target.SYSTEMS},
                    request_factory=request_factory,
                    collector_factory=lambda path, run_id: FakeCollector(
                        path, run_id=run_id, events=[]
                    ),
                    acceptance_finalizer=finalizer,
                )
                self.assertEqual(result["completed_cells"], 32)
                self.assertNotIn(adopted.run_id, calls)
                self.assertEqual(len(calls), 31)
                self.assertFalse(stale_attempt.exists())
                self.assertFalse(
                    (fixture.pilot_root / ".qualification-pilot-staging-v2").exists()
                )
                checkpoint = json.loads(fixture.checkpoint.read_text(encoding="ascii"))
                self.assertEqual(len(checkpoint["completed"]), 32)
                self.assertIn(
                    adopted.arm_id,
                    {entry["arm_id"] for entry in checkpoint["completed"]},
                )
            finally:
                fixture.close()

    def test_child_parent_evidence_or_production_claim_is_rejected(self) -> None:
        for violation in (
            "hardware",
            "production_acceptance",
            "production_grant",
            "nonpending_candidate",
        ):
            with self.subTest(violation=violation), tempfile.TemporaryDirectory() as tmp:
                fixture = InputFixture(Path(tmp).resolve())

                def request_factory(**kwargs: object) -> NativePublicationRequestV3:
                    request = fixture.request(
                        kwargs["cell"],  # type: ignore[arg-type]
                        kwargs["output_dir"],  # type: ignore[arg-type]
                        kwargs["evidence_names"],  # type: ignore[arg-type]
                    )
                    if violation == "production_grant":
                        runtime_inputs = dict(request.runtime_inputs)
                        runtime_inputs["backend_runtime_grant_sha256"] = "a" * 64
                        request = NativePublicationRequestV3(
                            **{**request.__dict__, "runtime_inputs": runtime_inputs}
                        )
                    return request

                def runtime(request: NativePublicationRequestV3) -> NativePublicationOutcomeV3:
                    write_request_child_evidence(request)
                    if violation == "nonpending_candidate":
                        candidate_path = (
                            request.output_dir
                            / "checkpoint_publication_candidate.json"
                        )
                        candidate = json.loads(
                            candidate_path.read_text(encoding="ascii")
                        )
                        candidate["status"] = "accepted_native_checkpoint_arm"
                        write_json(candidate_path, candidate)
                    if violation == "hardware":
                        (request.output_dir / "hardware_resource_samples.csv").write_text(
                            "forbidden\n", encoding="utf-8"
                        )
                    if violation == "production_acceptance":
                        (request.output_dir / "checkpoint_publication_acceptance.json").write_text(
                            "forbidden\n", encoding="utf-8"
                        )
                    return NativePublicationOutcomeV3(exit_code=0)

                try:
                    with self.assertRaises(target.QualificationPilotExecutorV2Error):
                        target.execute_qualification_pilots_v2(
                            **fixture.arguments(),
                            runtime_registry={system: runtime for system in target.SYSTEMS},
                            request_factory=request_factory,
                            collector_factory=lambda path, run_id: FakeCollector(
                                path, run_id=run_id, events=[]
                            ),
                            acceptance_finalizer=mock.Mock(
                                side_effect=AssertionError("must not finalize")
                            ),
                        )
                    self.assertFalse(
                        any(fixture.pilot_root.rglob(target.ACCEPTANCE_FILENAME))
                    )
                finally:
                    fixture.close()

    def test_deadline_duration_and_defer_mode_are_not_user_configurable(self) -> None:
        with self.assertRaises(target.QualificationPilotExecutorV2Error):
            target.qualification_pilot_cells_v2(deadline_ms=99, duration_s=180)
        with self.assertRaises(target.QualificationPilotExecutorV2Error):
            target.qualification_pilot_cells_v2(deadline_ms=100, duration_s=179)
        with self.assertRaises(SystemExit):
            target._parse_args(  # noqa: SLF001
                [
                    "--project-root", "/tmp/project",
                    "--candidate-index", "index.json",
                    "--candidate-manifest", "manifest.json",
                    "--candidate-receipt", "receipt.json",
                    "--bootstrap-mapping", "mapping.json",
                    "--bootstrap-receipt", "bootstrap-receipt.json",
                    "--bootstrap-dir", "bootstrap",
                    "--pilot-root", "pilots",
                    "--checkpoint", "checkpoint.json",
                    "--defer-full-resource-acceptance", "false",
                ]
            )
        argv = [
            "--project-root", "/tmp/project",
            "--candidate-index", "index.json",
            "--candidate-manifest", "manifest.json",
            "--candidate-receipt", "receipt.json",
            "--bootstrap-mapping", "mapping.json",
            "--bootstrap-receipt", "bootstrap-receipt.json",
            "--bootstrap-dir", "bootstrap",
            "--pilot-root", "pilots",
            "--checkpoint", "checkpoint.json",
        ]
        completed = {
            "status": "completed",
            "completed_cells": 32,
            "checkpoint_path": Path("/tmp/project/checkpoint.json"),
        }
        with mock.patch.object(
            target, "execute_qualification_pilots_v2", return_value=completed
        ) as execute, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(target.main(argv), 0)
        execute.assert_called_once()
        self.assertEqual(execute.call_args.kwargs["deadline_ms"], 100)
        self.assertEqual(execute.call_args.kwargs["duration_s"], 180)
        self.assertNotIn("defer_full_resource_acceptance", execute.call_args.kwargs)
        self.assertEqual(json.loads(output.getvalue())["completed_cells"], 32)


if __name__ == "__main__":
    unittest.main()
