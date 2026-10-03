from __future__ import annotations

import contextlib
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
    LAUNCHER_RESULT_FILENAME,
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
import checkpoint_deepstream_publication_launcher_v3 as deepstream  # noqa: E402
import checkpoint_gstreamer_custom_publication_launcher_v3 as gstreamer  # noqa: E402
import checkpoint_openvino_gva_publication_launcher_v3 as openvino  # noqa: E402
from checkpoint_publication_launcher_adapter_v3 import (  # noqa: E402
    DETERMINISTIC_NUMERIC_THREAD_ENVIRONMENT_V1,
    NativePublicationOutcomeV3,
    NativePublicationPermanentErrorV3,
    NativePublicationTransientErrorV3,
    deterministic_numeric_thread_environment_argv_v1,
)
import checkpoint_savant_publication_launcher_v3 as savant  # noqa: E402
from production_arm_evidence_finalizer_v1 import (  # noqa: E402
    finalized_production_evidence_files_v1,
    native_candidate_evidence_files_v1,
)


LAUNCHERS = (
    ("deepstream", deepstream),
    ("savant", savant),
    ("openvino_gva", openvino),
    ("gstreamer_custom", gstreamer),
)
TOPOLOGIES = (
    ("independent_processes", "checkpoint_independent_processes_baseline"),
    ("shared_video_dag", "checkpoint_video_dag_shared"),
)
EVIDENCE_NAME = "native-runtime-evidence.json"


class PublicationLauncherAdaptersV3Tests(unittest.TestCase):
    def test_numeric_thread_environment_is_closed_and_deterministic(self) -> None:
        self.assertEqual(
            DETERMINISTIC_NUMERIC_THREAD_ENVIRONMENT_V1,
            (
                "OPENBLAS_NUM_THREADS=1",
                "OMP_NUM_THREADS=1",
                "MKL_NUM_THREADS=1",
                "NUMEXPR_NUM_THREADS=1",
            ),
        )
        self.assertEqual(
            deterministic_numeric_thread_environment_argv_v1(),
            (
                "--env", "OPENBLAS_NUM_THREADS=1",
                "--env", "OMP_NUM_THREADS=1",
                "--env", "MKL_NUM_THREADS=1",
                "--env", "NUMEXPR_NUM_THREADS=1",
            ),
        )

    def _fixture(
        self, root: Path, *, system: str, topology: str, scenario: str,
    ) -> tuple[Path, Path, str, list[str]]:
        output = root / "runs" / f"{system}-{topology}"
        output.mkdir(parents=True)
        arm_path = output / ARM_CONTRACT_FILENAME
        launcher_relative = Path(
            f"scripts/checkpoint_{system}_publication_launcher_v3.py"
        )
        launcher_copy = root / launcher_relative
        launcher_copy.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / launcher_relative, launcher_copy)
        coordinate = {
            "system": system,
            "codec": "h264",
            "topology_kind": topology,
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
                "sha256": hashlib.sha256(launcher_copy.read_bytes()).hexdigest(),
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
        runtime_inputs = {
            **coordinate,
            "scenario": scenario,
            "dataset": {
                "name": "synthetic-kpp",
                "split": "test",
                f"{system}_publication_runtime_v3": {
                    "defer_full_resource_acceptance": True,
                    "scratch_root": str(root),
                    "evidence_mapping": {
                        name: name
                        for name in native_candidate_evidence_files_v1("cpu_only")
                    },
                },
            },
            "streams": 6,
            "duration_s": 30,
            "repeat_index": 0,
            "base_seed": 20260824,
            "run_seed": 8675309,
            "run_id": "run-0001",
            "project_root": str(root),
            "output_dir": str(output),
            "arm_contract_path": str(arm_path),
        }
        evidence = list(finalized_production_evidence_files_v1("cpu_only"))
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
        (output / LAUNCH_FENCE_FILENAME).write_bytes(
            (
                json.dumps(
                    production_fence_material(arm, arm_descriptor=arm_descriptor),
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                )
                + "\n"
            ).encode("ascii")
        )
        return output, arm_path, hashlib.sha256(payload).hexdigest(), evidence

    @staticmethod
    def _argv(root: Path, output: Path, arm: Path, digest: str) -> list[str]:
        return [
            "--project-root", str(root),
            "--arm-contract", str(arm),
            "--arm-contract-sha256", digest,
            "--output-dir", str(output),
        ]

    def _run(self, launcher: object, argv: list[str]) -> tuple[int, dict[str, object]]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = launcher.main(argv)
        self.assertEqual(stderr.getvalue(), "")
        return status, json.loads(stdout.getvalue())

    @staticmethod
    def _fake_finalizer(**kwargs: object) -> NativePublicationOutcomeV3:
        request = kwargs["request"]
        outcome = kwargs["native_runner"](request)
        if outcome.exit_code == 0:
            for name in request.launcher_evidence_files:
                (request.output_dir / name).write_bytes(b'{"fixture":true}\n')
        return outcome

    def test_each_backend_dispatches_both_topologies_exactly_with_sanitized_request(self) -> None:
        for system, launcher in LAUNCHERS:
            for topology, scenario in TOPOLOGIES:
                with self.subTest(system=system, topology=topology), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp).resolve()
                    output, arm, digest, evidence = self._fixture(
                        root, system=system, topology=topology, scenario=scenario,
                    )
                    calls: list[object] = []

                    def selected(request: object) -> NativePublicationOutcomeV3:
                        calls.append(request)
                        self.assertEqual(request.system, system)
                        self.assertEqual(request.topology_kind, topology)
                        self.assertEqual(dict(request.environment), {})
                        self.assertEqual(
                            set(request.launcher_evidence_files), set(evidence)
                        )
                        self.assertEqual(request.output_dir, output)
                        return NativePublicationOutcomeV3(exit_code=0)

                    rejected = mock.Mock(side_effect=AssertionError("wrong topology dispatched"))
                    runners = {
                        topology: selected,
                        next(value for value, _ in TOPOLOGIES if value != topology): rejected,
                    }
                    poison = {
                        "VAST_UNTRUSTED_RUNTIME_ARGV": "--output-dir=escaped",
                        "VAST_UNTRUSTED_RUNTIME_ENV": "secret",
                    }
                    with mock.patch.object(launcher, "NATIVE_TOPOLOGY_RUNNERS", runners), \
                            mock.patch(
                                "production_arm_evidence_finalizer_v1."
                                "finalize_production_arm_evidence_v1",
                                side_effect=self._fake_finalizer,
                            ), \
                            mock.patch.dict(os.environ, poison, clear=False):
                        status, assessment = self._run(
                            launcher, self._argv(root, output, arm, digest),
                        )
                    self.assertEqual(status, 0, assessment)
                    self.assertEqual(len(calls), 1)
                    rejected.assert_not_called()
                    self.assertTrue(assessment["native_runtime_invoked"])
                    self.assertTrue(assessment["exact_child_evidence_validated"])
                    self.assertEqual(assessment["blockers"], [])

    def test_real_entrypoints_reject_drifted_launcher_authority_before_native(self) -> None:
        for system, launcher in LAUNCHERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output, arm, digest, _ = self._fixture(
                    root,
                    system=system,
                    topology="shared_video_dag",
                    scenario="checkpoint_video_dag_shared",
                )
                launcher_path = (
                    root / f"scripts/checkpoint_{system}_publication_launcher_v3.py"
                )
                launcher_path.write_bytes(b"drifted\n")
                before = sorted((path.name, path.read_bytes()) for path in output.iterdir())
                status, assessment = self._run(
                    launcher, self._argv(root, output, arm, digest),
                )
                self.assertEqual(status, 78)
                self.assertTrue(launcher.PUBLICATION_READY)
                self.assertFalse(assessment["native_runtime_invoked"])
                self.assertEqual(
                    assessment["blockers"], ["launcher_authority_file_drifted"]
                )
                self.assertEqual(
                    sorted((path.name, path.read_bytes()) for path in output.iterdir()),
                    before,
                )

    def test_parent_owned_collision_and_arm_mutation_fail_permanently(self) -> None:
        for mutation in ("result_collision", "arm_overwrite"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output, arm, digest, _ = self._fixture(
                    root,
                    system="deepstream",
                    topology="shared_video_dag",
                    scenario="checkpoint_video_dag_shared",
                )

                def runner(request: object) -> NativePublicationOutcomeV3:
                    (request.output_dir / EVIDENCE_NAME).write_bytes(b"evidence\n")
                    if mutation == "result_collision":
                        (request.output_dir / LAUNCHER_RESULT_FILENAME).write_bytes(b"child\n")
                    else:
                        request.arm_contract_path.write_bytes(b"child-overwrite\n")
                    return NativePublicationOutcomeV3(exit_code=0)

                with mock.patch.object(
                    deepstream,
                    "NATIVE_TOPOLOGY_RUNNERS",
                    {value: runner for value, _ in TOPOLOGIES},
                ), mock.patch(
                    "production_arm_evidence_finalizer_v1."
                    "finalize_production_arm_evidence_v1",
                    side_effect=self._fake_finalizer,
                ):
                    status, assessment = self._run(
                        deepstream, self._argv(root, output, arm, digest),
                    )
                self.assertEqual(status, 78)
                self.assertTrue(any(
                    blocker in assessment["blockers"]
                    for blocker in (
                        "parent_owned_namespace_collision",
                        "parent_owned_input_mutated_by_native_runtime",
                    )
                ))

    def test_backend_outcomes_and_errors_map_only_to_0_75_78(self) -> None:
        cases = (
            (NativePublicationOutcomeV3(exit_code=75, blockers=("device_busy",)), 75),
            (NativePublicationOutcomeV3(exit_code=78, blockers=("artifact_missing",)), 78),
            (NativePublicationTransientErrorV3("runtime_temporarily_unavailable"), 75),
            (NativePublicationPermanentErrorV3("runtime_contract_invalid"), 78),
            (RuntimeError("unexpected"), 78),
        )
        for result, expected in cases:
            with self.subTest(result=result), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output, arm, digest, _ = self._fixture(
                    root,
                    system="openvino_gva",
                    topology="independent_processes",
                    scenario="checkpoint_independent_processes_baseline",
                )

                def runner(_request: object) -> NativePublicationOutcomeV3:
                    if isinstance(result, BaseException):
                        raise result
                    return result

                with mock.patch.object(
                    openvino,
                    "NATIVE_TOPOLOGY_RUNNERS",
                    {value: runner for value, _ in TOPOLOGIES},
                ), mock.patch(
                    "production_arm_evidence_finalizer_v1."
                    "finalize_production_arm_evidence_v1",
                    side_effect=self._fake_finalizer,
                ):
                    status, assessment = self._run(
                        openvino, self._argv(root, output, arm, digest),
                    )
                self.assertEqual(status, expected)
                self.assertIn(status, (0, 75, 78))
                self.assertTrue(assessment["native_runtime_invoked"])


if __name__ == "__main__":
    unittest.main()
