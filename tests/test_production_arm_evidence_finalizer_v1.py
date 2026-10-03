from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from backend_publication_dispatch_v3 import (  # noqa: E402
    ARM_CONTRACT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    build_backend_publication_arm_contract_v3,
    build_backend_publication_dispatch_resolution_v3,
    canonical_backend_publication_arm_contract_bytes_v3,
)
from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)
from backend_publication_output_transaction_production_v3 import (  # noqa: E402
    _fence_material as production_fence_material,
)
import checkpoint_deepstream_publication_launcher_v3 as launcher  # noqa: E402
import checkpoint_publication_runtime  # noqa: E402
import production_arm_evidence_finalizer_v1 as finalizer  # noqa: E402
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    NativePublicationOutcomeV3,
)
from full_publication_entrypoint import (  # noqa: E402
    publication_arm_semantic_evidence_validator_v3,
)
from production_arm_evidence_finalizer_v1 import (  # noqa: E402
    FINAL_ACCEPTANCE_FILENAME,
    HARDWARE_EVIDENCE_FILENAME,
    RUN_METADATA_FILENAME,
    finalized_production_evidence_files_v1,
    native_candidate_evidence_files_v1,
)
from publication_acceptance_evidence import (  # noqa: E402
    pre_finalization_acceptance_evidence_files,
)


def canonical(value: object) -> bytes:
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


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Collector:
    def __init__(self, path: Path, events: list[str]) -> None:
        self.path = path
        self.events = events
        self.alive = False
        self.failure: BaseException | None = None

    def start(self) -> None:
        self.events.append("collector:start")
        self.alive = True
        self.path.write_text("run_id,cpu_percent\nrun-001,1\n", encoding="ascii")

    def wait_until_ready(self, *, timeout_s: float) -> None:
        self.events.append(f"collector:ready:{timeout_s:g}")

    def stop(self) -> None:
        self.events.append("collector:stop")
        self.alive = False

    def join(self, *, timeout: float) -> None:
        self.events.append(f"collector:join:{timeout:g}")

    def is_alive(self) -> bool:
        return self.alive

    def raise_if_failed(self) -> None:
        self.events.append("collector:checked")
        if self.failure is not None:
            raise self.failure


class ProductionArmEvidenceFinalizerV1Tests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, str, dict[str, object]]:
        output = root / "runs" / "arm"
        output.mkdir(parents=True)
        arm_path = output / ARM_CONTRACT_FILENAME
        launcher_relative = Path("scripts/checkpoint_deepstream_publication_launcher_v3.py")
        launcher_copy = root / launcher_relative
        launcher_copy.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / launcher_relative, launcher_copy)
        coordinate = {
            "system": "deepstream",
            "codec": "h264",
            "topology_kind": "shared_video_dag",
            "policy": "cpu_only",
            "deadline_ms": 50,
        }
        invocation = publication_launcher_invocation_v3_contract()
        resolution = build_backend_publication_dispatch_resolution_v3(
            coordinate=coordinate,
            python_executable={
                "path": "runtime/python/python3",
                "size_bytes": 101,
                "sha256": "1" * 64,
            },
            publication_launcher={
                "path": launcher_relative.as_posix(),
                "size_bytes": launcher_copy.stat().st_size,
                "sha256": sha(launcher_copy),
            },
            launcher_invocation=invocation,
            backend_runtime_grant_sha256="3" * 64,
            identity_artifact_binding_sha256="4" * 64,
            cell_identity_sha256="5" * 64,
            validation_record_sha256="6" * 64,
            runtime_binding_identity_sha256="7" * 64,
        )
        execution = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_arm_execution_binding",
            "run_identity_sha256": "8" * 64,
            "sequence": 1,
            "pair_id": "pair-0001",
            "attempt": 1,
            "arm_id": "arm-0001-a",
        }
        raw_names = native_candidate_evidence_files_v1("cpu_only")
        runtime_inputs = {
            **coordinate,
            "scenario": "checkpoint_video_dag_shared",
            "dataset": {
                "name": "synthetic-kpp",
                "split": "test",
                "deepstream_publication_runtime_v3": {
                    "defer_full_resource_acceptance": True,
                    "scratch_root": str(root),
                    "evidence_mapping": {name: name for name in raw_names},
                },
            },
            "streams": 6,
            "duration_s": 180,
            "repeat_index": 0,
            "base_seed": 20260323,
            "run_seed": 8675309,
            "run_id": "run-001",
            "project_root": str(root),
            "output_dir": str(output),
            "arm_contract_path": str(arm_path),
        }
        evidence = finalized_production_evidence_files_v1("cpu_only")
        arm = build_backend_publication_arm_contract_v3(
            dispatch_resolution=resolution,
            full_publication_execution_binding=execution,
            resource_capability_grant_sha256="9" * 64,
            model_parity_grant_sha256="a" * 64,
            model_parity_acceptance_binding_sha256="b" * 64,
            runtime_inputs=runtime_inputs,
            launcher_evidence_files=evidence,
        )
        payload = canonical_backend_publication_arm_contract_bytes_v3(arm)
        arm_path.write_bytes(payload)
        arm_descriptor = {
            "path": ARM_CONTRACT_FILENAME,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        (output / LAUNCH_FENCE_FILENAME).write_bytes(canonical(
            production_fence_material(arm, arm_descriptor=arm_descriptor)
        ))
        return output, arm_path, hashlib.sha256(payload).hexdigest(), arm

    @staticmethod
    def _write_native_candidate(request: object, events: list[str]) -> None:
        events.append("native")
        base = pre_finalization_acceptance_evidence_files(
            request.runtime_inputs["policy"]
        )
        for name in base:
            (request.output_dir / name).write_text(
                "run_id\nrun-001\n" if name.endswith(".csv") else "{}\n",
                encoding="ascii",
            )
        (request.output_dir / "resource_intervals.csv").write_text(
            "run_id\nrun-001\n", encoding="ascii"
        )
        (request.output_dir / "fanout_work_counters.csv").write_text(
            "run_id\nrun-001\n", encoding="ascii"
        )
        candidate = {
            "schema_version": 2,
            "artifact_kind": "checkpoint_publication_runtime_candidate",
            "status": "pending_full_resource_validation",
            "run_id": "run-001",
            "system": "deepstream",
            "scenario": "checkpoint_video_dag_shared",
            "codec": "h264",
            "policy": "cpu_only",
            "deadline_ms": 50,
            "execution_binding_provenance": "native_scheduler_execution_binding_v1",
            "topology_kind": "shared_video_dag",
            "cohort_id": "run-001:measurement:1000:2000",
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
            },
            "evidence_sha256": {
                name: sha(request.output_dir / name) for name in base
            },
            "pending_full_resource_evidence": [
                "resource_intervals.csv",
                "hardware_resource_samples.csv",
                "fanout_work_counters.csv",
            ],
        }
        (request.output_dir / "checkpoint_publication_candidate.json").write_bytes(
            canonical(candidate)
        )

    @staticmethod
    def _argv(root: Path, output: Path, arm: Path, digest: str) -> list[str]:
        return [
            "--project-root", str(root),
            "--arm-contract", str(arm),
            "--arm-contract-sha256", digest,
            "--output-dir", str(output),
        ]

    def _run(self, argv: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = launcher.main(argv)
        self.assertEqual(stderr.getvalue(), "")
        return status, json.loads(stdout.getvalue())

    def test_native_candidate_is_promoted_and_passes_real_production_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, arm_path, digest, arm = self._fixture(root)
            events: list[str] = []
            collector_path: Path | None = None

            def native(request: object) -> NativePublicationOutcomeV3:
                self.assertIsNotNone(collector_path)
                self.assertEqual(collector_path.parent, request.output_dir.parent)
                self.assertNotEqual(collector_path.parent, request.output_dir)
                self.assertTrue(collector_path.exists())
                self.assertFalse(
                    (request.output_dir / HARDWARE_EVIDENCE_FILENAME).exists()
                )
                self._write_native_candidate(request, events)
                return NativePublicationOutcomeV3(exit_code=0)

            def collector_factory(path: Path, *, run_id: str) -> Collector:
                nonlocal collector_path
                self.assertEqual(run_id, "run-001")
                collector_path = path
                return Collector(path, events)

            resource_summary = {
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
            with (
                mock.patch.object(
                    launcher,
                    "NATIVE_TOPOLOGY_RUNNERS",
                    {"independent_processes": native, "shared_video_dag": native},
                ),
                mock.patch(
                    "production_arm_evidence_finalizer_v1."
                    "default_hardware_collector_factory_v1",
                    side_effect=collector_factory,
                ),
                mock.patch.object(
                    checkpoint_publication_runtime,
                    "validate_full_resource_evidence",
                    return_value={"summary": resource_summary},
                ),
            ):
                status, assessment = self._run(
                    self._argv(root, output, arm_path, digest)
                )

            self.assertEqual(status, 0)
            self.assertEqual(
                events,
                [
                    "collector:start",
                    "collector:ready:60",
                    "native",
                    "collector:stop",
                    "collector:join:30",
                    "collector:checked",
                ],
            )
            self.assertTrue(assessment["exact_child_evidence_validated"])
            self.assertNotIn("checkpoint_publication_candidate.json", {
                path.name for path in output.iterdir()
            })
            acceptance = json.loads(
                (output / FINAL_ACCEPTANCE_FILENAME).read_text(encoding="ascii")
            )
            self.assertEqual(acceptance["status"], "accepted_native_checkpoint_arm")
            self.assertEqual(
                acceptance["publication_metadata_binding"][
                    "backend_runtime_grant_sha256"
                ],
                arm["backend_runtime_grant_sha256"],
            )
            names = arm["launcher_output_protocol"]["launcher_evidence_files"]
            payloads = {name: (output / name).read_bytes() for name in names}
            descriptors = [
                {
                    "path": name,
                    "size_bytes": len(payloads[name]),
                    "sha256": hashlib.sha256(payloads[name]).hexdigest(),
                }
                for name in names
            ]
            request = {
                "schema_version": 3,
                "artifact_kind": (
                    "vast_backend_publication_production_semantic_evidence_request_v3"
                ),
                "arm_contract": arm,
                "arm_contract_file": {
                    "path": ARM_CONTRACT_FILENAME,
                    "size_bytes": arm_path.stat().st_size,
                    "sha256": digest,
                },
                "evidence_files": descriptors,
                "evidence_aggregate_sha256": "d" * 64,
                "evidence_payloads": payloads,
            }
            semantic = publication_arm_semantic_evidence_validator_v3(request)
            self.assertTrue(semantic["accepted"], semantic)
            metadata = json.loads(
                (output / RUN_METADATA_FILENAME).read_text(encoding="ascii")
            )
            self.assertEqual(
                metadata["publication_run_contract"][
                    "full_publication_execution_binding"
                ],
                arm["full_publication_execution_binding"],
            )

    def test_tampered_launcher_is_rejected_before_native_and_collector(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, arm_path, digest, _ = self._fixture(root)
            (root / "scripts/checkpoint_deepstream_publication_launcher_v3.py").write_text(
                "tampered\n", encoding="ascii"
            )
            native = mock.Mock()
            collector = mock.Mock()
            with (
                mock.patch.object(
                    launcher,
                    "NATIVE_TOPOLOGY_RUNNERS",
                    {"independent_processes": native, "shared_video_dag": native},
                ),
                mock.patch(
                    "production_arm_evidence_finalizer_v1."
                    "default_hardware_collector_factory_v1",
                    collector,
                ),
            ):
                status, assessment = self._run(
                    self._argv(root, output, arm_path, digest)
                )
            self.assertEqual(status, 78)
            self.assertEqual(assessment["blockers"], ["launcher_authority_file_drifted"])
            native.assert_not_called()
            collector.assert_not_called()
            self.assertFalse((output / FINAL_ACCEPTANCE_FILENAME).exists())

    def test_forged_parent_launch_fence_is_rejected_before_child_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, arm_path, digest, _ = self._fixture(root)
            (output / LAUNCH_FENCE_FILENAME).write_bytes(b"forged-fence\n")
            native = mock.Mock()
            collector = mock.Mock()
            with (
                mock.patch.object(
                    launcher,
                    "NATIVE_TOPOLOGY_RUNNERS",
                    {"independent_processes": native, "shared_video_dag": native},
                ),
                mock.patch(
                    "production_arm_evidence_finalizer_v1."
                    "default_hardware_collector_factory_v1",
                    collector,
                ),
            ):
                status, assessment = self._run(
                    self._argv(root, output, arm_path, digest)
                )
            self.assertEqual(status, 78)
            self.assertEqual(
                assessment["blockers"],
                ["production_launch_fence_authority_invalid"],
            )
            native.assert_not_called()
            collector.assert_not_called()
            self.assertFalse((output / FINAL_ACCEPTANCE_FILENAME).exists())

    def test_backend_grant_mismatch_is_rejected_before_child_work(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, arm_path, _digest, arm = self._fixture(root)
            tampered = copy.deepcopy(arm)
            tampered["backend_runtime_grant_sha256"] = "e" * 64
            unsigned = {
                key: value
                for key, value in tampered.items()
                if key != "contract_sha256"
            }
            tampered["contract_sha256"] = hashlib.sha256(
                canonical(unsigned)[:-1]
            ).hexdigest()
            payload = canonical(tampered)
            arm_path.write_bytes(payload)
            digest = hashlib.sha256(payload).hexdigest()
            native = mock.Mock()
            collector = mock.Mock()
            with (
                mock.patch.object(
                    launcher,
                    "NATIVE_TOPOLOGY_RUNNERS",
                    {"independent_processes": native, "shared_video_dag": native},
                ),
                mock.patch(
                    "production_arm_evidence_finalizer_v1."
                    "default_hardware_collector_factory_v1",
                    collector,
                ),
            ):
                status, assessment = self._run(
                    self._argv(root, output, arm_path, digest)
                )
            self.assertEqual(status, 78)
            self.assertEqual(
                assessment["blockers"], ["arm_contract_v3_semantics_invalid"]
            )
            native.assert_not_called()
            collector.assert_not_called()
            self.assertFalse((output / FINAL_ACCEPTANCE_FILENAME).exists())

    def test_collector_failure_and_native_timeout_leave_no_accepted_tail(self) -> None:
        for mode in ("collector_failure", "native_timeout"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                output, arm_path, digest, _ = self._fixture(root)
                events: list[str] = []

                def native(request: object) -> NativePublicationOutcomeV3:
                    if mode == "native_timeout":
                        events.append("native")
                        return NativePublicationOutcomeV3(
                            exit_code=75, blockers=("native_runtime_timeout",)
                        )
                    self._write_native_candidate(request, events)
                    return NativePublicationOutcomeV3(exit_code=0)

                def collector_factory(path: Path, *, run_id: str) -> Collector:
                    instance = Collector(path, events)
                    if mode == "collector_failure":
                        instance.failure = RuntimeError("nvml failed")
                    return instance

                with (
                    mock.patch.object(
                        launcher,
                        "NATIVE_TOPOLOGY_RUNNERS",
                        {
                            "independent_processes": native,
                            "shared_video_dag": native,
                        },
                    ),
                    mock.patch(
                        "production_arm_evidence_finalizer_v1."
                        "default_hardware_collector_factory_v1",
                        side_effect=collector_factory,
                    ),
                ):
                    status, _assessment = self._run(
                        self._argv(root, output, arm_path, digest)
                    )
                self.assertIn(status, (75, 78))
                self.assertFalse((output / FINAL_ACCEPTANCE_FILENAME).exists())
                self.assertFalse((output / RUN_METADATA_FILENAME).exists())

    def test_each_finalizer_leaf_class_survives_all_atomic_crash_windows(self) -> None:
        leaf_classes = {
            "hardware_evidence": (HARDWARE_EVIDENCE_FILENAME, b"hardware\n"),
            "final_evidence": ("runtime_probe.json", b'{"accepted":true}\n'),
            "run_metadata": (RUN_METADATA_FILENAME, b'{"metadata":true}\n'),
            "final_acceptance": (
                FINAL_ACCEPTANCE_FILENAME,
                b'{"status":"accepted_native_checkpoint_arm"}\n',
            ),
        }
        crash_windows = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for leaf_class, (name, payload) in leaf_classes.items():
            for crash_window in crash_windows:
                with (
                    self.subTest(leaf_class=leaf_class, crash_window=crash_window),
                    tempfile.TemporaryDirectory() as temporary,
                ):
                    output = Path(temporary).resolve() / "arm"
                    output.mkdir()
                    target = output / name

                    def crash(step: str) -> None:
                        if step == crash_window:
                            raise RuntimeError(f"synthetic hard crash at {step}")

                    with self.assertRaisesRegex(RuntimeError, "synthetic hard crash"):
                        finalizer._commit_or_adopt_exact(  # noqa: SLF001
                            target,
                            payload,
                            blocker="synthetic_commit_failed",
                            label=f"synthetic {leaf_class}",
                            fault_hook=crash,
                        )
                    published_identity = None
                    if target.exists():
                        published = target.stat()
                        published_identity = (published.st_dev, published.st_ino)
                        self.assertEqual(target.read_bytes(), payload)
                    resumed_identity = finalizer._commit_or_adopt_exact(  # noqa: SLF001
                        target,
                        payload,
                        blocker="synthetic_commit_failed",
                        label=f"synthetic {leaf_class}",
                    )
                    self.assertEqual(target.read_bytes(), payload)
                    if published_identity is not None:
                        self.assertEqual(resumed_identity, published_identity)

    def test_finalizer_atomic_retry_rejects_tamper_and_foreign_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "arm"
            output.mkdir()
            target = output / FINAL_ACCEPTANCE_FILENAME
            payload = b'{"status":"accepted_native_checkpoint_arm"}\n'
            finalizer._commit_or_adopt_exact(  # noqa: SLF001
                target,
                payload,
                blocker="synthetic_commit_failed",
                label="synthetic final acceptance",
            )
            target.chmod(0o644)
            target.write_bytes(b"tampered\n")
            with self.assertRaisesRegex(
                Exception, "synthetic_commit_failed"
            ):
                finalizer._commit_or_adopt_exact(  # noqa: SLF001
                    target,
                    payload,
                    blocker="synthetic_commit_failed",
                    label="synthetic final acceptance",
                )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve() / "arm"
            output.mkdir()
            target = output / FINAL_ACCEPTANCE_FILENAME
            payload = b'{"status":"accepted_native_checkpoint_arm"}\n'
            finalizer._commit_or_adopt_exact(  # noqa: SLF001
                target,
                payload,
                blocker="synthetic_commit_failed",
                label="synthetic final acceptance",
            )
            os.link(target, output / "foreign-hardlink")
            with self.assertRaisesRegex(
                Exception, "synthetic_commit_failed"
            ):
                finalizer._commit_or_adopt_exact(  # noqa: SLF001
                    target,
                    payload,
                    blocker="synthetic_commit_failed",
                    label="synthetic final acceptance",
                )


if __name__ == "__main__":
    unittest.main()
