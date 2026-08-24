from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_runtime_validation_runner_authority import (  # noqa: E402
    ARTIFACT_KIND,
    ASSESSMENT_KIND,
    BackendRuntimeValidationRunnerAuthorityError,
    assess_backend_runtime_validation_runner_authority,
    build_backend_runtime_validation_runner_authority,
    runner_invocation_contract,
    validate_backend_runtime_validation_runner_authority,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def reseal(value: dict[str, object]) -> None:
    value.pop("runner_authority_sha256", None)
    value["runner_authority_sha256"] = canonical_sha(value)


class BackendRuntimeValidationRunnerAuthorityTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        files = {
            "runtime/python.exe": b"pinned-project-python-runtime",
            "runtime/validation_runner.py": b"def main():\n    return 0\n",
            "runtime/lib/core.py": b"CANONICAL_JSON = True\n",
            "runtime/lib/protocol.py": b"PROTOCOL_VERSION = 1\n",
        }
        for relative, payload in files.items():
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        def descriptor(relative: str) -> dict[str, object]:
            payload = (self.root / relative).read_bytes()
            return {
                "path": relative, "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        leaves = [
            {"descriptor": descriptor(relative),
             "content_identity_sha256": descriptor(relative)["sha256"]}
            for relative in ("runtime/lib/core.py", "runtime/lib/protocol.py")
        ]
        manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_validation_bundle_manifest",
            "python_executable": {
                "descriptor": descriptor("runtime/python.exe"),
                "content_identity_sha256": descriptor("runtime/python.exe")["sha256"],
            },
            "runner": {
                "descriptor": descriptor("runtime/validation_runner.py"),
                "content_identity_sha256": descriptor(
                    "runtime/validation_runner.py"
                )["sha256"],
            },
            "runtime_leaves": leaves,
            "runtime_leaf_set_sha256": canonical_sha(leaves),
        }
        manifest["bundle_manifest_sha256"] = canonical_sha(manifest)
        (self.root / "runtime/bundle-manifest.json").write_bytes(
            json.dumps(
                manifest, sort_keys=True, separators=(",", ":"),
                ensure_ascii=True, allow_nan=False,
            ).encode("utf-8") + b"\n"
        )
        self.protocol_sha = hashlib.sha256(b"validation-protocol-v1").hexdigest()
        self.input_sha = hashlib.sha256(b"replay-request-schema-v1").hexdigest()
        self.output_sha = hashlib.sha256(b"validation-record-schema-v1").hexdigest()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "project_root": self.root,
            "runner_id": "backend-runtime-validation-runner-v1",
            "runtime_bundle_manifest_path": "runtime/bundle-manifest.json",
            "runtime_leaf_paths": [
                "runtime/lib/protocol.py", "runtime/lib/core.py",
            ],
            "python_executable_path": "runtime/python.exe",
            "runner_path": "runtime/validation_runner.py",
            "validation_protocol_identity_sha256": self.protocol_sha,
            "input_schema_identity_sha256": self.input_sha,
            "output_schema_identity_sha256": self.output_sha,
        }
        arguments.update(overrides)
        return build_backend_runtime_validation_runner_authority(**arguments)

    def test_validate_requires_external_runner_pin(self) -> None:
        parameter = inspect.signature(
            validate_backend_runtime_validation_runner_authority
        ).parameters["expected_runner_authority_sha256"]
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_builds_closed_nonauthorizing_physically_valid_authority(self) -> None:
        authority = self.build()
        self.assertEqual(authority["artifact_kind"], ARTIFACT_KIND)
        self.assertEqual(
            [item["descriptor"]["path"] for item in authority["runtime_leaves"]],
            ["runtime/lib/core.py", "runtime/lib/protocol.py"],
        )
        self.assertEqual(
            authority["runtime_leaf_set_sha256"],
            canonical_sha(authority["runtime_leaves"]),
        )
        self.assertEqual(authority["invocation_contract"], runner_invocation_contract())
        self.assertNotEqual(
            authority["runtime_bundle_manifest"]["content_identity_sha256"],
            authority["runtime_bundle_manifest"]["descriptor"]["sha256"],
        )
        validated = validate_backend_runtime_validation_runner_authority(
            authority,
            expected_runner_authority_sha256=authority["runner_authority_sha256"],
        )
        self.assertEqual(validated, authority)
        assessment = assess_backend_runtime_validation_runner_authority(
            authority, project_root=self.root,
            expected_runner_authority_sha256=authority["runner_authority_sha256"],
        )
        self.assertEqual(assessment["artifact_kind"], ASSESSMENT_KIND)
        self.assertEqual(assessment["status"], "physically_valid")
        self.assertEqual(assessment["checked_artifact_count"], 5)
        self.assertEqual(assessment["blockers"], [])
        self.assertIs(assessment["individual_artifact_reads_handle_bound"], True)
        self.assertIs(assessment["atomic_runtime_closure_snapshot_validated"], False)
        self.assertIs(assessment["interpreter_execution_validated"], False)
        self.assertIs(assessment["sandbox_enforcement_validated"], False)
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_invocation_contract_is_exact_isolated_shell_free_and_self_hashed(self) -> None:
        invocation = runner_invocation_contract()
        self.assertEqual(invocation["argv_template"][:8], [
            "{python_executable}", "-I", "-S", "-B", "-X", "utf8",
            "{runner_path}", "--project-root",
        ])
        process = invocation["process_contract"]
        self.assertIs(process["shell"], False)
        self.assertIs(process["check"], False)
        self.assertEqual(process["environment"], "exact_empty_mapping")
        self.assertEqual(process["cwd_source"], "caller_supplied_canonical_project_root")
        self.assertEqual(process["filesystem_writes"], "denied")
        self.assertEqual(process["network"], "denied")
        unsigned = {key: value for key, value in invocation.items()
                    if key != "invocation_sha256"}
        self.assertEqual(invocation["invocation_sha256"], canonical_sha(unsigned))

    def test_top_and_supported_schema_versions_reject_json_number_smuggling(self) -> None:
        authority = self.build()
        for field in (
            "schema_version", "supported_validator_authority_schema_version",
        ):
            for schema_version in (True, 1.0, 3.0, 0):
                with self.subTest(field=field, schema_version=schema_version):
                    changed = copy.deepcopy(authority)
                    changed[field] = schema_version
                    reseal(changed)
                    with self.assertRaises(
                        BackendRuntimeValidationRunnerAuthorityError
                    ):
                        validate_backend_runtime_validation_runner_authority(
                            changed,
                            expected_runner_authority_sha256=changed[
                                "runner_authority_sha256"
                            ],
                        )

    def test_manifest_schema_version_rejects_stale_hash_type_smuggling(self) -> None:
        authority = self.build()
        for schema_version in (True, 1.0, 3.0, 0):
            with self.subTest(schema_version=schema_version):
                changed = copy.deepcopy(authority)
                manifest = changed["runtime_bundle_manifest_content"]
                manifest["schema_version"] = schema_version
                unsigned = {
                    key: value for key, value in manifest.items()
                    if key != "bundle_manifest_sha256"
                }
                self.assertNotEqual(
                    manifest["bundle_manifest_sha256"], canonical_sha(unsigned)
                )
                reseal(changed)
                with self.assertRaises(
                    BackendRuntimeValidationRunnerAuthorityError
                ):
                    validate_backend_runtime_validation_runner_authority(
                        changed,
                        expected_runner_authority_sha256=changed[
                            "runner_authority_sha256"
                        ],
                    )

    def test_invocation_contract_rejects_type_smuggling_with_stale_hash(self) -> None:
        authority = self.build()

        def schema_true(invocation: dict[str, object]) -> None:
            invocation["schema_version"] = True

        def schema_float(invocation: dict[str, object]) -> None:
            invocation["schema_version"] = 1.0

        def schema_three_float(invocation: dict[str, object]) -> None:
            invocation["schema_version"] = 3.0

        def schema_zero(invocation: dict[str, object]) -> None:
            invocation["schema_version"] = 0

        def shell_integer(invocation: dict[str, object]) -> None:
            invocation["process_contract"]["shell"] = 0

        def close_fds_integer(invocation: dict[str, object]) -> None:
            invocation["process_contract"]["close_fds"] = 1

        def exit_code_bool(invocation: dict[str, object]) -> None:
            invocation["process_contract"]["accepted_exit_codes"] = [False]

        def timeout_float(invocation: dict[str, object]) -> None:
            invocation["process_contract"]["timeout_ms"] = 30000.0

        for mutate in (
            schema_true, schema_float, schema_three_float, schema_zero,
            shell_integer, close_fds_integer, exit_code_bool, timeout_float,
        ):
            with self.subTest(mutation=mutate.__name__):
                changed = copy.deepcopy(authority)
                invocation = changed["invocation_contract"]
                mutate(invocation)
                unsigned = {
                    key: value for key, value in invocation.items()
                    if key != "invocation_sha256"
                }
                self.assertNotEqual(
                    invocation["invocation_sha256"], canonical_sha(unsigned)
                )
                reseal(changed)
                with self.assertRaises(
                    BackendRuntimeValidationRunnerAuthorityError
                ):
                    validate_backend_runtime_validation_runner_authority(
                        changed,
                        expected_runner_authority_sha256=changed[
                            "runner_authority_sha256"
                        ],
                    )

    def test_manifest_path_casefold_aliases_all_top_roles_fail_closed(self) -> None:
        authority = self.build()
        top_roles = [
            authority["python_executable"], authority["runner"],
            *authority["runtime_leaves"],
        ]
        for role in top_roles:
            role_path = role["descriptor"]["path"]
            with self.subTest(role_path=role_path):
                changed = copy.deepcopy(authority)
                changed["runtime_bundle_manifest"]["descriptor"][
                    "path"
                ] = role_path.swapcase()
                reseal(changed)
                with self.assertRaises(
                    BackendRuntimeValidationRunnerAuthorityError
                ):
                    validate_backend_runtime_validation_runner_authority(
                        changed,
                        expected_runner_authority_sha256=changed[
                            "runner_authority_sha256"
                        ],
                    )

    def test_casefold_aliases_between_runtime_roles_fail_closed(self) -> None:
        authority = self.build()
        cases = (
            (("python_executable", None), ("runner", None)),
            (("runner", None), ("runtime_leaves", 0)),
            (("runtime_leaves", 0), ("python_executable", None)),
        )

        def role(
            container: dict[str, object], location: tuple[str, int | None],
        ) -> dict[str, object]:
            field, index = location
            return (container[field] if index is None
                    else container[field][index])

        for source, target in cases:
            with self.subTest(source=source, target=target):
                changed = copy.deepcopy(authority)
                manifest = changed["runtime_bundle_manifest_content"]
                target_path = role(changed, target)["descriptor"]["path"]
                alias_path = target_path.swapcase()
                role(changed, source)["descriptor"]["path"] = alias_path
                role(manifest, source)["descriptor"]["path"] = alias_path
                changed["runtime_leaf_set_sha256"] = canonical_sha(
                    changed["runtime_leaves"]
                )
                manifest["runtime_leaf_set_sha256"] = canonical_sha(
                    manifest["runtime_leaves"]
                )
                manifest.pop("bundle_manifest_sha256")
                manifest["bundle_manifest_sha256"] = canonical_sha(manifest)
                changed["runtime_bundle_manifest"][
                    "content_identity_sha256"
                ] = manifest["bundle_manifest_sha256"]
                reseal(changed)
                with self.assertRaises(
                    BackendRuntimeValidationRunnerAuthorityError
                ):
                    validate_backend_runtime_validation_runner_authority(
                        changed,
                        expected_runner_authority_sha256=changed[
                            "runner_authority_sha256"
                        ],
                    )

    def test_wrong_pin_tamper_extra_and_downstream_fields_fail_closed(self) -> None:
        authority = self.build()
        with self.assertRaises(BackendRuntimeValidationRunnerAuthorityError):
            validate_backend_runtime_validation_runner_authority(
                authority,
                expected_runner_authority_sha256=hashlib.sha256(b"wrong").hexdigest(),
            )
        mutations = []
        changed = copy.deepcopy(authority)
        changed["runner"]["descriptor"]["sha256"] = "0" * 64
        mutations.append(changed)
        changed = copy.deepcopy(authority)
        changed["invocation_contract"]["process_contract"]["shell"] = True
        reseal(changed)
        mutations.append(changed)
        for field in ("grant_sha256", "validation_record_set_sha256"):
            changed = copy.deepcopy(authority)
            changed[field] = "1" * 64
            reseal(changed)
            mutations.append(changed)
        for changed in mutations:
            with self.assertRaises(BackendRuntimeValidationRunnerAuthorityError):
                validate_backend_runtime_validation_runner_authority(
                    changed,
                    expected_runner_authority_sha256=changed["runner_authority_sha256"],
                )

    def test_absolute_host_interpreter_and_unsafe_paths_are_rejected(self) -> None:
        invalid = (
            str(Path(sys.executable).resolve()), "../python.exe", "C:python.exe",
            "runtime/python.exe:ads", "runtime\\python.exe", "CON.exe",
            "runtime/python.exe.", "runtime/python.exe ",
        )
        for path in invalid:
            with self.subTest(path=path):
                with self.assertRaises(BackendRuntimeValidationRunnerAuthorityError):
                    self.build(python_executable_path=path)

    def test_all_artifact_paths_are_unique_and_runtime_leaves_cannot_duplicate_roles(self) -> None:
        for leaves in (
            ["runtime/lib/core.py", "runtime/lib/core.py"],
            ["runtime/python.exe", "runtime/lib/core.py"],
            ["runtime/validation_runner.py", "runtime/lib/core.py"],
            ["runtime/bundle-manifest.json", "runtime/lib/core.py"],
        ):
            with self.subTest(leaves=leaves):
                with self.assertRaises(BackendRuntimeValidationRunnerAuthorityError):
                    self.build(runtime_leaf_paths=leaves)

    def test_physical_tamper_blocks_and_never_authorizes(self) -> None:
        authority = self.build()
        (self.root / "runtime/lib/core.py").write_bytes(b"TAMPERED=True\n")
        assessment = assess_backend_runtime_validation_runner_authority(
            authority, project_root=self.root,
            expected_runner_authority_sha256=authority["runner_authority_sha256"],
        )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(assessment["blockers"])
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_manifest_closure_drift_is_rejected_even_when_authority_is_resealed(self) -> None:
        authority = self.build()
        for mutation in ("missing_leaf", "swapped_runner", "wrong_leaf_set"):
            changed = copy.deepcopy(authority)
            if mutation == "missing_leaf":
                changed["runtime_bundle_manifest_content"]["runtime_leaves"].pop()
            elif mutation == "swapped_runner":
                changed["runtime_bundle_manifest_content"]["runner"] = copy.deepcopy(
                    changed["python_executable"]
                )
            else:
                changed["runtime_bundle_manifest_content"][
                    "runtime_leaf_set_sha256"
                ] = "3" * 64
            manifest = changed["runtime_bundle_manifest_content"]
            manifest.pop("bundle_manifest_sha256", None)
            manifest["bundle_manifest_sha256"] = canonical_sha(manifest)
            changed["runtime_bundle_manifest"][
                "content_identity_sha256"
            ] = manifest["bundle_manifest_sha256"]
            reseal(changed)
            with self.subTest(mutation=mutation), self.assertRaises(
                BackendRuntimeValidationRunnerAuthorityError
            ):
                validate_backend_runtime_validation_runner_authority(
                    changed,
                    expected_runner_authority_sha256=changed[
                        "runner_authority_sha256"
                    ],
                )

    def test_hardlink_and_symlink_are_rejected(self) -> None:
        alias = self.root / "runtime/lib/core-alias.py"
        os.link(self.root / "runtime/lib/core.py", alias)
        with self.assertRaises(BackendRuntimeValidationRunnerAuthorityError):
            self.build(runtime_leaf_paths=["runtime/lib/core.py"])
        alias.unlink()
        link = self.root / "runtime/lib/core-link.py"
        try:
            link.symlink_to(self.root / "runtime/lib/core.py")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink unavailable: {error}")
        with self.assertRaises(BackendRuntimeValidationRunnerAuthorityError):
            self.build(runtime_leaf_paths=["runtime/lib/core-link.py"])

    def test_module_has_no_process_execution_surface(self) -> None:
        import backend_runtime_validation_runner_authority as module
        source = inspect.getsource(module)
        self.assertNotIn("import subprocess", source)
        self.assertNotIn("os.system", source)
        self.assertNotIn("Popen", source)


if __name__ == "__main__":
    unittest.main()
