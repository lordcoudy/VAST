from __future__ import annotations

import ast
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_publication_dispatch import launcher_invocation_contract  # noqa: E402
from backend_publication_dispatch_v3 import (  # noqa: E402
    ARM_CONTRACT_FILENAME,
    CAPTURE_STDERR_FILENAME,
    CAPTURE_STDOUT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    MAX_ARM_CONTRACT_BYTES,
    OUTPUT_RECEIPT_FILENAME,
    BackendPublicationDispatchV3Error,
    backend_publication_coordinate_sha256_v3,
    backend_publication_launcher_output_protocol_v3,
    build_backend_publication_arm_contract_v3,
    build_backend_publication_command_v3,
    build_backend_publication_dispatch_resolution_v3,
    canonical_backend_publication_arm_contract_bytes_v3,
    parse_backend_publication_arm_contract_v3_bytes,
    validate_backend_publication_arm_contract_v3,
    validate_backend_publication_dispatch_resolution_v3,
    validate_backend_publication_launcher_output_protocol_v3,
)
from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    INPUT_PROTOCOL_IDENTITY_SHA256,
    OUTPUT_PROTOCOL_IDENTITY_SHA256,
    publication_launcher_invocation_v3_contract,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()


def reseal(value: dict[str, object], field: str) -> None:
    value.pop(field, None)
    value[field] = canonical_sha(value)


class BackendPublicationDispatchV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.project_root = Path(self.temporary.name)
        self.output_dir = self.project_root / "synthetic" / "run-0001"
        self.arm_path = self.output_dir / ARM_CONTRACT_FILENAME
        self.coordinate = {
            "system": "deepstream",
            "codec": "h264",
            "topology_kind": "shared_video_dag",
            "policy": "cpu_only",
            "deadline_ms": 50,
        }
        self.python = {
            "path": "runtime/python/python3.exe",
            "size_bytes": 101,
            "sha256": "1" * 64,
        }
        self.launcher = {
            "path": "runtime/deepstream/publication_launcher.py",
            "size_bytes": 202,
            "sha256": "2" * 64,
        }
        self.invocation = publication_launcher_invocation_v3_contract()
        self.pins = {
            "expected_coordinate": self.coordinate,
            "expected_python_executable": self.python,
            "expected_publication_launcher": self.launcher,
            "expected_launcher_invocation_sha256": self.invocation[
                "invocation_sha256"
            ],
            "expected_backend_runtime_grant_sha256": "3" * 64,
            "expected_identity_artifact_binding_sha256": "4" * 64,
            "expected_cell_identity_sha256": "5" * 64,
            "expected_validation_record_sha256": "6" * 64,
            "expected_runtime_binding_identity_sha256": "7" * 64,
        }
        self.resolution = build_backend_publication_dispatch_resolution_v3(
            coordinate=self.coordinate,
            python_executable=self.python,
            publication_launcher=self.launcher,
            launcher_invocation=self.invocation,
            backend_runtime_grant_sha256="3" * 64,
            identity_artifact_binding_sha256="4" * 64,
            cell_identity_sha256="5" * 64,
            validation_record_sha256="6" * 64,
            runtime_binding_identity_sha256="7" * 64,
        )
        self.execution = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_arm_execution_binding",
            "run_identity_sha256": "8" * 64,
            "sequence": 4,
            "pair_id": "pair-0004",
            "attempt": 1,
            "arm_id": "arm-0004-b",
        }
        self.runtime_inputs = {
            **self.coordinate,
            "scenario": "checkpoint_video_dag_shared",
            "dataset": {"name": "synthetic-kpp", "split": "test"},
            "streams": 6,
            "duration_s": 30,
            "repeat_index": 0,
            "base_seed": 20260323,
            "run_seed": 8675309,
            "run_id": "run-0001",
            "project_root": str(self.project_root),
            "output_dir": str(self.output_dir),
            "arm_contract_path": str(self.arm_path),
        }
        self.evidence = [
            "latency_samples.json",
            "runtime_assessment.json",
        ]
        self.arm_pins = {
            "expected_dispatch_resolution_sha256": self.resolution[
                "resolution_sha256"
            ],
            "expected_full_publication_execution_binding": self.execution,
            "expected_resource_capability_grant_sha256": "9" * 64,
            "expected_model_parity_grant_sha256": "a" * 64,
            "expected_model_parity_acceptance_binding_sha256": "b" * 64,
            "expected_runtime_inputs": self.runtime_inputs,
            "expected_launcher_evidence_files": self.evidence,
        }
        self.arm = build_backend_publication_arm_contract_v3(
            dispatch_resolution=self.resolution,
            full_publication_execution_binding=self.execution,
            resource_capability_grant_sha256="9" * 64,
            model_parity_grant_sha256="a" * 64,
            model_parity_acceptance_binding_sha256="b" * 64,
            runtime_inputs=self.runtime_inputs,
            launcher_evidence_files=reversed(self.evidence),
        )

    def test_dispatch_resolution_is_exact_v3_self_hashed_and_non_authorizing(self) -> None:
        self.assertEqual(self.resolution["schema_version"], 3)
        self.assertEqual(
            self.resolution["artifact_kind"],
            "vast_backend_publication_dispatch_resolution_v3",
        )
        self.assertEqual(self.resolution["coordinate"], self.coordinate)
        self.assertEqual(
            self.resolution["coordinate_sha256"],
            backend_publication_coordinate_sha256_v3(self.coordinate),
        )
        self.assertEqual(self.resolution["python_executable"], self.python)
        self.assertEqual(self.resolution["publication_launcher"], self.launcher)
        self.assertEqual(self.resolution["launcher_invocation"], self.invocation)
        self.assertEqual(
            self.resolution["launcher_invocation_sha256"],
            self.invocation["invocation_sha256"],
        )
        self.assertEqual(
            self.resolution["input_protocol_identity_sha256"],
            INPUT_PROTOCOL_IDENTITY_SHA256,
        )
        self.assertEqual(
            self.resolution["output_protocol_identity_sha256"],
            OUTPUT_PROTOCOL_IDENTITY_SHA256,
        )
        for field in (
            "publication_execution_authorized", "publication_ready",
            "executed_bytes_attested", "accepted_measurement_evidence_emitted",
        ):
            self.assertIs(self.resolution[field], False)
        unsigned = {key: item for key, item in self.resolution.items()
                    if key != "resolution_sha256"}
        self.assertEqual(self.resolution["resolution_sha256"], canonical_sha(unsigned))

    def test_resolution_requires_all_external_pins_and_returns_detached_copy(self) -> None:
        checked = validate_backend_publication_dispatch_resolution_v3(
            self.resolution, **self.pins,
        )
        self.assertEqual(checked, self.resolution)
        checked["coordinate"]["policy"] = "gpu_only"
        self.assertEqual(
            validate_backend_publication_dispatch_resolution_v3(
                self.resolution, **self.pins,
            ),
            self.resolution,
        )
        mutations = {
            "expected_coordinate": {**self.coordinate, "policy": "gpu_only"},
            "expected_python_executable": {**self.python, "sha256": "c" * 64},
            "expected_publication_launcher": {**self.launcher, "sha256": "c" * 64},
            "expected_launcher_invocation_sha256": "c" * 64,
            "expected_backend_runtime_grant_sha256": "c" * 64,
            "expected_identity_artifact_binding_sha256": "c" * 64,
            "expected_cell_identity_sha256": "c" * 64,
            "expected_validation_record_sha256": "c" * 64,
            "expected_runtime_binding_identity_sha256": "c" * 64,
        }
        for field, value in mutations.items():
            pins = copy.deepcopy(self.pins)
            pins[field] = value
            with self.subTest(field=field), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                validate_backend_publication_dispatch_resolution_v3(
                    self.resolution, **pins,
                )

    def test_v2_relabelled_v2_and_resolution_drift_fail_closed(self) -> None:
        old = launcher_invocation_contract()
        for invocation in (old, {**old, "schema_version": 3}):
            with self.subTest(invocation=invocation), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                build_backend_publication_dispatch_resolution_v3(
                    coordinate=self.coordinate,
                    python_executable=self.python,
                    publication_launcher=self.launcher,
                    launcher_invocation=invocation,
                    backend_runtime_grant_sha256="3" * 64,
                    identity_artifact_binding_sha256="4" * 64,
                    cell_identity_sha256="5" * 64,
                    validation_record_sha256="6" * 64,
                    runtime_binding_identity_sha256="7" * 64,
                )
        for mutation in (
            lambda value: value.__setitem__("schema_version", 2),
            lambda value: value.__setitem__(
                "artifact_kind", "vast_backend_publication_dispatch_resolution"
            ),
            lambda value: value.__setitem__("publication_ready", True),
            lambda value: value.__setitem__("executed_bytes_attested", True),
            lambda value: value.__setitem__("unexpected", False),
        ):
            changed = copy.deepcopy(self.resolution)
            mutation(changed)
            reseal(changed, "resolution_sha256")
            with self.assertRaises(BackendPublicationDispatchV3Error):
                validate_backend_publication_dispatch_resolution_v3(
                    changed, **self.pins,
                )

    def test_coordinate_and_descriptor_forms_are_closed_and_canonical(self) -> None:
        bad_coordinates = [
            {**self.coordinate, "codec": "hevc"},
            {**self.coordinate, "deadline_ms": 50.0},
            {**self.coordinate, "deadline_ms": True},
            {**self.coordinate, "system": "DeepStream"},
            {**self.coordinate, "extra": "x"},
        ]
        for coordinate in bad_coordinates:
            with self.subTest(coordinate=coordinate), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                backend_publication_coordinate_sha256_v3(coordinate)
        bad_descriptors = [
            {**self.python, "path": "/absolute/python"},
            {**self.python, "path": "runtime/../python"},
            {**self.python, "path": "runtime\\python.exe"},
            {**self.python, "path": "runtime//python.exe"},
            {**self.python, "path": "CON"},
            {**self.python, "size_bytes": True},
            {**self.python, "size_bytes": 0},
            {**self.python, "sha256": "A" * 64},
            {**self.python, "extra": False},
        ]
        for descriptor in bad_descriptors:
            with self.subTest(descriptor=descriptor), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                build_backend_publication_dispatch_resolution_v3(
                    coordinate=self.coordinate,
                    python_executable=descriptor,
                    publication_launcher=self.launcher,
                    launcher_invocation=self.invocation,
                    backend_runtime_grant_sha256="3" * 64,
                    identity_artifact_binding_sha256="4" * 64,
                    cell_identity_sha256="5" * 64,
                    validation_record_sha256="6" * 64,
                    runtime_binding_identity_sha256="7" * 64,
                )

    def test_output_protocol_closes_ownership_reserved_names_and_commit_order(self) -> None:
        protocol = backend_publication_launcher_output_protocol_v3(
            reversed(self.evidence)
        )
        self.assertEqual(protocol["launcher_evidence_files"], self.evidence)
        self.assertEqual(protocol["controller_owned_files"], [ARM_CONTRACT_FILENAME])
        self.assertEqual(protocol["parent_finalizer_owned_files"], [
            LAUNCH_FENCE_FILENAME,
            CAPTURE_STDOUT_FILENAME,
            CAPTURE_STDERR_FILENAME,
            LAUNCHER_RESULT_FILENAME,
            OUTPUT_RECEIPT_FILENAME,
        ])
        self.assertEqual(protocol["commit_order"], [
            LAUNCH_FENCE_FILENAME,
            CAPTURE_STDOUT_FILENAME,
            CAPTURE_STDERR_FILENAME,
            LAUNCHER_RESULT_FILENAME,
            OUTPUT_RECEIPT_FILENAME,
        ])
        self.assertEqual(protocol["reserved_files"], sorted({
            ARM_CONTRACT_FILENAME, LAUNCH_FENCE_FILENAME,
            CAPTURE_STDOUT_FILENAME, CAPTURE_STDERR_FILENAME,
            LAUNCHER_RESULT_FILENAME, OUTPUT_RECEIPT_FILENAME,
        }))
        for field in (
            "accepted_measurement_evidence_emitted",
            "publication_execution_authorized", "publication_ready",
            "executed_bytes_attested",
        ):
            self.assertIs(protocol[field], False)
        self.assertEqual(
            validate_backend_publication_launcher_output_protocol_v3(
                protocol, expected_launcher_evidence_files=self.evidence,
            ),
            protocol,
        )
        for names in (
            ["z.json", "Z.JSON"],
            ["nested/evidence.json"],
            ["../evidence.json"],
            [OUTPUT_RECEIPT_FILENAME],
            [OUTPUT_RECEIPT_FILENAME.upper()],
            ["CON"],
        ):
            with self.subTest(names=names), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                backend_publication_launcher_output_protocol_v3(names)

    def test_arm_contract_is_exact_v3_crossbound_and_non_authorizing(self) -> None:
        self.assertEqual(self.arm["schema_version"], 3)
        self.assertEqual(
            self.arm["artifact_kind"],
            "vast_backend_publication_arm_dispatch_contract_v3",
        )
        self.assertEqual(self.arm["dispatch_resolution"], self.resolution)
        self.assertEqual(self.arm["runtime_inputs"], self.runtime_inputs)
        self.assertEqual(
            self.arm["launcher_output_protocol"]["launcher_evidence_files"],
            self.evidence,
        )
        self.assertEqual(
            self.arm["backend_runtime_grant_sha256"],
            self.resolution["backend_runtime_grant_sha256"],
        )
        self.assertEqual(
            self.arm["identity_artifact_binding_sha256"],
            self.resolution["identity_artifact_binding_sha256"],
        )
        for field in (
            "publication_execution_authorized", "publication_ready",
            "executed_bytes_attested", "accepted_measurement_evidence_emitted",
        ):
            self.assertIs(self.arm[field], False)
        unsigned = {key: item for key, item in self.arm.items()
                    if key != "contract_sha256"}
        self.assertEqual(self.arm["contract_sha256"], canonical_sha(unsigned))
        checked = validate_backend_publication_arm_contract_v3(
            self.arm, **self.arm_pins,
        )
        checked["runtime_inputs"]["run_id"] = "changed"
        self.assertEqual(
            validate_backend_publication_arm_contract_v3(
                self.arm, **self.arm_pins,
            ),
            self.arm,
        )

    def test_arm_coordinate_path_protocol_and_claim_drift_fail_closed(self) -> None:
        mutations = (
            lambda value: value["runtime_inputs"].__setitem__("codec", "h265"),
            lambda value: value["runtime_inputs"].__setitem__(
                "scenario", "checkpoint_independent_processes_baseline"
            ),
            lambda value: value["runtime_inputs"].__setitem__(
                "output_dir", str(self.project_root.parent)
            ),
            lambda value: value["runtime_inputs"].__setitem__(
                "arm_contract_path", str(self.output_dir / "other.json")
            ),
            lambda value: value["launcher_output_protocol"].__setitem__(
                "output_protocol_identity_sha256", "c" * 64
            ),
            lambda value: value.__setitem__("publication_execution_authorized", True),
            lambda value: value.__setitem__("accepted_measurement_evidence_emitted", True),
            lambda value: value.__setitem__("schema_version", 2),
            lambda value: value.__setitem__("unexpected", False),
        )
        for mutation in mutations:
            changed = copy.deepcopy(self.arm)
            mutation(changed)
            protocol = changed.get("launcher_output_protocol")
            if type(protocol) is dict:
                reseal(protocol, "protocol_sha256")
            reseal(changed, "contract_sha256")
            with self.assertRaises(BackendPublicationDispatchV3Error):
                validate_backend_publication_arm_contract_v3(
                    changed, **self.arm_pins,
                )

    def test_arm_validation_requires_external_dispatch_execution_grant_and_input_pins(self) -> None:
        mutations = {
            "expected_dispatch_resolution_sha256": "c" * 64,
            "expected_full_publication_execution_binding": {
                **self.execution, "arm_id": "other"
            },
            "expected_resource_capability_grant_sha256": "c" * 64,
            "expected_model_parity_grant_sha256": "c" * 64,
            "expected_model_parity_acceptance_binding_sha256": "c" * 64,
            "expected_runtime_inputs": {**self.runtime_inputs, "run_id": "other"},
            "expected_launcher_evidence_files": ["other.json"],
        }
        for field, value in mutations.items():
            pins = copy.deepcopy(self.arm_pins)
            pins[field] = value
            with self.subTest(field=field), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                validate_backend_publication_arm_contract_v3(self.arm, **pins)

    def test_canonical_arm_bytes_are_ascii_lf_unique_and_raw_sha_pinned(self) -> None:
        payload = canonical_backend_publication_arm_contract_bytes_v3(self.arm)
        self.assertTrue(payload.endswith(b"\n"))
        self.assertEqual(payload.decode("ascii").encode("ascii"), payload)
        file_sha = hashlib.sha256(payload).hexdigest()
        self.assertEqual(
            parse_backend_publication_arm_contract_v3_bytes(
                payload, expected_file_sha256=file_sha,
            ),
            self.arm,
        )
        failures = [
            (payload, "c" * 64),
            (payload[:-1], hashlib.sha256(payload[:-1]).hexdigest()),
            (payload.replace(b'"schema_version":3', b'"schema_version": 3'),
             None),
            (b'\xef\xbb\xbf' + payload, None),
        ]
        for changed, expected in failures:
            pin = expected or hashlib.sha256(changed).hexdigest()
            with self.subTest(payload=changed[:20]), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                parse_backend_publication_arm_contract_v3_bytes(
                    changed, expected_file_sha256=pin,
                )
        duplicate = payload.replace(
            b"{", b'{"schema_version":3,', 1,
        )
        with self.assertRaises(BackendPublicationDispatchV3Error):
            parse_backend_publication_arm_contract_v3_bytes(
                duplicate,
                expected_file_sha256=hashlib.sha256(duplicate).hexdigest(),
            )

    def test_command_is_exact_immutable_ten_token_v3_argv(self) -> None:
        payload = canonical_backend_publication_arm_contract_bytes_v3(self.arm)
        file_sha = hashlib.sha256(payload).hexdigest()
        argv = build_backend_publication_command_v3(
            self.resolution,
            **self.pins,
            project_root=self.project_root,
            arm_contract_path=self.arm_path,
            arm_contract_file_sha256=file_sha,
            output_dir=self.output_dir,
        )
        self.assertIsInstance(argv, tuple)
        self.assertEqual(len(argv), 10)
        self.assertEqual(argv, (
            str(self.project_root / Path(*self.python["path"].split("/"))),
            str(self.project_root / Path(*self.launcher["path"].split("/"))),
            "--project-root", str(self.project_root),
            "--arm-contract", str(self.arm_path),
            "--arm-contract-sha256", file_sha,
            "--output-dir", str(self.output_dir),
        ))
        self.assertNotIn("run_system_template.sh", " ".join(argv))
        self.assertNotIn("--env", argv)

    def test_command_rejects_noncanonical_escape_and_non_direct_child_paths(self) -> None:
        payload = canonical_backend_publication_arm_contract_bytes_v3(self.arm)
        file_sha = hashlib.sha256(payload).hexdigest()
        common = {
            **self.pins,
            "project_root": self.project_root,
            "arm_contract_path": self.arm_path,
            "arm_contract_file_sha256": file_sha,
            "output_dir": self.output_dir,
        }
        mutations = [
            {"project_root": Path("relative/root")},
            {"project_root": str(self.project_root) + os.sep + "."},
            {"output_dir": self.project_root},
            {"output_dir": self.project_root.parent / "escaped"},
            {"output_dir": str(self.output_dir) + os.sep + "."},
            {"arm_contract_path": self.output_dir / "other.json"},
            {"arm_contract_path": self.output_dir / "nested" / ARM_CONTRACT_FILENAME},
            {"arm_contract_file_sha256": "C" * 64},
        ]
        for mutation in mutations:
            arguments = {**common, **mutation}
            with self.subTest(mutation=mutation), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                build_backend_publication_command_v3(
                    self.resolution, **arguments,
                )

    def test_json_type_substitution_and_broken_hashes_are_rejected(self) -> None:
        resolution = copy.deepcopy(self.resolution)
        resolution["python_executable"]["size_bytes"] = True
        reseal(resolution, "resolution_sha256")
        with self.assertRaises(BackendPublicationDispatchV3Error):
            validate_backend_publication_dispatch_resolution_v3(
                resolution, **self.pins,
            )
        arm = copy.deepcopy(self.arm)
        arm["runtime_inputs"]["streams"] = True
        reseal(arm, "contract_sha256")
        with self.assertRaises(BackendPublicationDispatchV3Error):
            validate_backend_publication_arm_contract_v3(arm, **self.arm_pins)
        arm = copy.deepcopy(self.arm)
        arm["contract_sha256"] = "c" * 64
        with self.assertRaises(BackendPublicationDispatchV3Error):
            validate_backend_publication_arm_contract_v3(arm, **self.arm_pins)
        resolution = copy.deepcopy(self.resolution)
        resolution["cell_identity_sha256"] = True
        reseal(resolution, "resolution_sha256")
        with self.assertRaises(BackendPublicationDispatchV3Error):
            validate_backend_publication_dispatch_resolution_v3(
                resolution, **self.pins,
            )
        arm = copy.deepcopy(self.arm)
        arm["resource_capability_grant_sha256"] = 9
        reseal(arm, "contract_sha256")
        with self.assertRaises(BackendPublicationDispatchV3Error):
            validate_backend_publication_arm_contract_v3(arm, **self.arm_pins)
        for dataset in (
            {1: "non-string-key"},
            {1: "ambiguous", "1": "duplicate-after-encoding"},
            {"tuple_is_not_json": (1, 2)},
            {"not_finite": float("nan")},
        ):
            runtime = copy.deepcopy(self.runtime_inputs)
            runtime["dataset"] = dataset
            with self.subTest(dataset=dataset), self.assertRaises(
                BackendPublicationDispatchV3Error
            ):
                build_backend_publication_arm_contract_v3(
                    dispatch_resolution=self.resolution,
                    full_publication_execution_binding=self.execution,
                    resource_capability_grant_sha256="9" * 64,
                    model_parity_grant_sha256="a" * 64,
                    model_parity_acceptance_binding_sha256="b" * 64,
                    runtime_inputs=runtime,
                    launcher_evidence_files=self.evidence,
                )

    def test_builder_wrong_container_types_fail_with_the_public_error(self) -> None:
        with self.assertRaises(BackendPublicationDispatchV3Error):
            build_backend_publication_dispatch_resolution_v3(
                coordinate=self.coordinate,
                python_executable=None,  # type: ignore[arg-type]
                publication_launcher=self.launcher,
                launcher_invocation=self.invocation,
                backend_runtime_grant_sha256="3" * 64,
                identity_artifact_binding_sha256="4" * 64,
                cell_identity_sha256="5" * 64,
                validation_record_sha256="6" * 64,
                runtime_binding_identity_sha256="7" * 64,
            )
        with self.assertRaises(BackendPublicationDispatchV3Error):
            build_backend_publication_arm_contract_v3(
                dispatch_resolution=None,  # type: ignore[arg-type]
                full_publication_execution_binding=self.execution,
                resource_capability_grant_sha256="9" * 64,
                model_parity_grant_sha256="a" * 64,
                model_parity_acceptance_binding_sha256="b" * 64,
                runtime_inputs=self.runtime_inputs,
                launcher_evidence_files=self.evidence,
            )
        oversized_runtime = copy.deepcopy(self.runtime_inputs)
        oversized_runtime["dataset"] = {"padding": "x" * MAX_ARM_CONTRACT_BYTES}
        with self.assertRaises(BackendPublicationDispatchV3Error):
            build_backend_publication_arm_contract_v3(
                dispatch_resolution=self.resolution,
                full_publication_execution_binding=self.execution,
                resource_capability_grant_sha256="9" * 64,
                model_parity_grant_sha256="a" * 64,
                model_parity_acceptance_binding_sha256="b" * 64,
                runtime_inputs=oversized_runtime,
                launcher_evidence_files=self.evidence,
            )

    def test_source_is_pure_and_exposes_no_execution_or_grant_bypass(self) -> None:
        source = (ROOT / "scripts" / "backend_publication_dispatch_v3.py").read_text(
            encoding="utf-8"
        )
        tree = ast.parse(source)
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        }
        imported |= {
            (node.module or "").split(".")[0]
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        self.assertTrue(imported <= {
            "__future__", "copy", "hashlib", "json", "math", "os", "re",
            "pathlib", "typing", "backend_publication_launcher_invocation_v3",
        })
        called_attributes = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertFalse(called_attributes & {
            "run", "Popen", "system", "spawn", "open", "read_bytes",
            "write_bytes", "resolve", "stat", "lstat", "mkdir", "replace",
        })
        lowered = source.lower()
        for prohibited in (
            "subprocess", "socket", "docker", "shell=true",
            "publication_execution_authorized\": true",
            "publication_ready\": true", "executed_bytes_attested\": true",
        ):
            self.assertNotIn(prohibited, lowered)


if __name__ == "__main__":
    unittest.main()
