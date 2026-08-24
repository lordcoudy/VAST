from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_runtime_validator_authority as physical_reader  # noqa: E402
import backend_runtime_validator_authority_v4 as authority_v4  # noqa: E402
from backend_runtime_validator_authority_v4 import (  # noqa: E402
    ARTIFACT_KIND,
    ASSESSMENT_KIND,
    BackendRuntimeValidatorAuthorityV4Error,
    assess_backend_runtime_validator_authority_v4,
    build_backend_runtime_validator_authority_v4,
    validate_backend_runtime_validator_authority_v4,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


class BackendRuntimeValidatorAuthorityV4Test(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "validators").mkdir()
        self.implementation = self.root / "validators" / "q4_validator.py"
        self.payload = b"def validate_q4(value):\n    return value\n"
        self.implementation.write_bytes(self.payload)
        self.descriptor = {
            "path": "validators/q4_validator.py",
            "size_bytes": len(self.payload),
            "sha256": hashlib.sha256(self.payload).hexdigest(),
        }
        self.pins = {
            "qualification_input_schema_identity_sha256": sha("q4-input-schema"),
            "validation_system_context_schema_identity_sha256": sha("context-schema-v1"),
            "validation_request_schema_identity_sha256": sha("request-schema-v1"),
            "validation_record_schema_identity_sha256": sha("record-schema-v1"),
            "validation_system_shard_schema_identity_sha256": sha("shard-schema-v1"),
            "validation_record_set_index_schema_identity_sha256": sha("record-index-schema-v1"),
            "validation_protocol_identity_sha256": sha("validation-protocol-v2"),
            "validation_input_schema_identity_sha256": sha("runner-wire-input-v2"),
            "validation_output_schema_identity_sha256": sha("runner-wire-output-v2"),
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def material(self, *, descriptor: dict[str, object] | None = None) -> dict[str, object]:
        checked = copy.deepcopy(descriptor or self.descriptor)
        value: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": ARTIFACT_KIND,
            "validator_id": "backend-runtime-q4-validator-v1",
            "implementation": {
                "descriptor": checked,
                "content_identity_sha256": checked["sha256"],
            },
            "supported_qualification_schema_version": 4,
            **self.pins,
            "deterministic": True,
            "execution_authorized": False,
            "validation_records_authenticated": False,
        }
        value["authority_sha256"] = canonical_sha(value)
        return value

    def build(self, *, descriptor: dict[str, object] | None = None) -> dict[str, object]:
        expected = self.material(descriptor=descriptor)
        return build_backend_runtime_validator_authority_v4(
            validator_id="backend-runtime-q4-validator-v1",
            implementation_descriptor=copy.deepcopy(descriptor or self.descriptor),
            expected_authority_sha256=expected["authority_sha256"],
            **self.pins,
        )

    def test_public_abi_requires_external_authority_pin_everywhere(self) -> None:
        for function in (
            build_backend_runtime_validator_authority_v4,
            validate_backend_runtime_validator_authority_v4,
            assess_backend_runtime_validator_authority_v4,
        ):
            with self.subTest(function=function.__name__):
                parameter = inspect.signature(function).parameters[
                    "expected_authority_sha256"
                ]
                self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)
                self.assertIs(parameter.default, inspect.Parameter.empty)

    def test_builder_validates_external_pin_before_untrusted_descriptor(self) -> None:
        with self.assertRaisesRegex(
            BackendRuntimeValidatorAuthorityV4Error,
            "expected Q4 validator authority pin is invalid",
        ):
            build_backend_runtime_validator_authority_v4(
                validator_id="backend-runtime-q4-validator-v1",
                implementation_descriptor={"not": "a descriptor"},
                expected_authority_sha256="invalid",
                **self.pins,
            )

    def test_builder_rejects_descriptor_container_type_drift(self) -> None:
        expected = self.material()
        with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
            build_backend_runtime_validator_authority_v4(
                validator_id="backend-runtime-q4-validator-v1",
                implementation_descriptor=list(self.descriptor.items()),  # type: ignore[arg-type]
                expected_authority_sha256=expected["authority_sha256"],
                **self.pins,
            )

    def test_builder_emits_closed_q4_authority_with_lossless_protocol_pins(self) -> None:
        authority = self.build()
        self.assertEqual(authority, self.material())
        self.assertEqual(authority["artifact_kind"], ARTIFACT_KIND)
        self.assertEqual(authority["supported_qualification_schema_version"], 4)
        for field, expected in self.pins.items():
            self.assertEqual(authority[field], expected)
        self.assertIs(authority["deterministic"], True)
        self.assertIs(authority["execution_authorized"], False)
        self.assertIs(authority["validation_records_authenticated"], False)
        self.assertEqual(
            validate_backend_runtime_validator_authority_v4(
                authority,
                expected_authority_sha256=authority["authority_sha256"],
            ), authority,
        )

    def test_v3_authority_is_not_a_q4_authority(self) -> None:
        old = physical_reader.build_backend_runtime_cell_validator_authority(
            project_root=self.root,
            validator_id="backend-runtime-cell-validator-v1",
            implementation_path="validators/q4_validator.py",
            validation_protocol_identity_sha256=self.pins["validation_protocol_identity_sha256"],
            input_schema_identity_sha256=self.pins["validation_input_schema_identity_sha256"],
            output_schema_identity_sha256=self.pins["validation_output_schema_identity_sha256"],
        )
        with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
            validate_backend_runtime_validator_authority_v4(
                old, expected_authority_sha256=old["authority_sha256"]
            )

    def test_external_pin_and_all_schema_protocol_pins_fail_closed(self) -> None:
        authority = self.build()
        with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
            validate_backend_runtime_validator_authority_v4(
                authority, expected_authority_sha256=sha("wrong-authority")
            )
        for field in self.pins:
            with self.subTest(field=field):
                changed = copy.deepcopy(authority)
                changed[field] = sha(f"changed-{field}")
                changed["authority_sha256"] = canonical_sha({
                    key: value for key, value in changed.items()
                    if key != "authority_sha256"
                })
                with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
                    validate_backend_runtime_validator_authority_v4(
                        changed,
                        expected_authority_sha256=authority["authority_sha256"],
                    )

    def test_top_schema_version_rejects_json_number_smuggling(self) -> None:
        authority = self.build()
        for schema_version in (True, 1.0, 3.0, 0):
            with self.subTest(schema_version=schema_version):
                changed = copy.deepcopy(authority)
                changed["schema_version"] = schema_version
                changed["authority_sha256"] = canonical_sha({
                    key: value for key, value in changed.items()
                    if key != "authority_sha256"
                })
                with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
                    validate_backend_runtime_validator_authority_v4(
                        changed,
                        expected_authority_sha256=changed["authority_sha256"],
                    )

    def test_supported_schema_version_rejects_json_number_smuggling(self) -> None:
        authority = self.build()
        for schema_version in (True, 4.0, 3.0, 0):
            with self.subTest(schema_version=schema_version):
                changed = copy.deepcopy(authority)
                changed["supported_qualification_schema_version"] = schema_version
                changed["authority_sha256"] = canonical_sha({
                    key: value for key, value in changed.items()
                    if key != "authority_sha256"
                })
                with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
                    validate_backend_runtime_validator_authority_v4(
                        changed,
                        expected_authority_sha256=changed["authority_sha256"],
                    )

    def test_unknown_downstream_and_cyclic_fields_fail_before_hashing(self) -> None:
        authority = self.build()
        for field in ("grant_sha256", "dispatch_sha256", "receipt_sha256"):
            changed = copy.deepcopy(authority)
            changed[field] = "0" * 64
            changed["authority_sha256"] = canonical_sha({
                key: value for key, value in changed.items()
                if key != "authority_sha256"
            })
            with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
                validate_backend_runtime_validator_authority_v4(
                    changed, expected_authority_sha256=changed["authority_sha256"]
                )
        cyclic = copy.deepcopy(authority)
        cyclic["downstream"] = cyclic
        with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
            validate_backend_runtime_validator_authority_v4(
                cyclic, expected_authority_sha256=authority["authority_sha256"]
            )

    def test_self_pinned_authorizing_or_nondeterministic_claims_fail_closed(self) -> None:
        authority = self.build()
        for field, claim in (
            ("execution_authorized", True),
            ("validation_records_authenticated", True),
            ("deterministic", False),
        ):
            with self.subTest(field=field):
                changed = copy.deepcopy(authority)
                changed[field] = claim
                changed["authority_sha256"] = canonical_sha({
                    key: value for key, value in changed.items()
                    if key != "authority_sha256"
                })
                with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
                    validate_backend_runtime_validator_authority_v4(
                        changed,
                        expected_authority_sha256=changed["authority_sha256"],
                    )

    def test_descriptor_path_grammar_is_cross_platform_strict(self) -> None:
        invalid = (
            "/outside.py", "../outside.py", "validators/../outside.py",
            "C:/outside.py", "C:outside.py", "validators\\q4_validator.py",
            "validators/q4_validator.py:ads", "CON.py", "aux.txt",
            "validators./q4_validator.py", "validators/q4_validator.py.",
            "validators/q4_validator.py ", "validators//q4_validator.py",
        )
        for path in invalid:
            with self.subTest(path=path):
                descriptor = {**self.descriptor, "path": path}
                expected = self.material(descriptor=descriptor)
                with self.assertRaises(BackendRuntimeValidatorAuthorityV4Error):
                    build_backend_runtime_validator_authority_v4(
                        validator_id="backend-runtime-q4-validator-v1",
                        implementation_descriptor=descriptor,
                        expected_authority_sha256=expected["authority_sha256"],
                        **self.pins,
                    )

    def test_assessment_validates_q4_pin_before_physical_reader_projection(self) -> None:
        authority = self.build()
        with mock.patch.object(
            physical_reader, "assess_backend_runtime_cell_validator_authority"
        ) as adapter:
            assessment = assess_backend_runtime_validator_authority_v4(
                authority, project_root=self.root,
                expected_authority_sha256=sha("wrong-q4-pin"),
            )
        adapter.assert_not_called()
        self.assertEqual(assessment["status"], "blocked")
        self.assertIs(assessment["q4_authority_pin_validated"], False)
        self.assertIsNone(assessment["physical_reader_projection_sha256"])
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_handle_bound_assessment_reports_nontrusting_projection_scope(self) -> None:
        authority = self.build()
        assessment = assess_backend_runtime_validator_authority_v4(
            authority, project_root=self.root,
            expected_authority_sha256=authority["authority_sha256"],
        )
        self.assertEqual(assessment["artifact_kind"], ASSESSMENT_KIND)
        self.assertEqual(assessment["status"], "physically_valid")
        self.assertIs(assessment["q4_authority_pin_validated"], True)
        self.assertEqual(assessment["physical_assessment_scope"], "single_validator_implementation_descriptor")
        self.assertEqual(assessment["physical_reader_adapter_kind"], physical_reader.ARTIFACT_KIND)
        self.assertRegex(assessment["physical_reader_projection_sha256"], r"^[0-9a-f]{64}$")
        self.assertIs(assessment["physical_reader_projection_is_trust_anchor"], False)
        self.assertEqual(assessment["checked_artifact_count"], 1)
        self.assertEqual(assessment["blockers"], [])
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_physical_tamper_and_hardlink_block_without_authorization(self) -> None:
        authority = self.build()
        self.implementation.write_bytes(b"def validate_q4(value):\n    return None\n")
        tampered = assess_backend_runtime_validator_authority_v4(
            authority, project_root=self.root,
            expected_authority_sha256=authority["authority_sha256"],
        )
        self.assertEqual(tampered["status"], "blocked")
        self.assertEqual(tampered["checked_artifact_count"], 0)
        self.assertIs(tampered["execution_authorized"], False)
        self.implementation.write_bytes(self.payload)
        os.link(self.implementation, self.root / "validators" / "alias.py")
        aliased = assess_backend_runtime_validator_authority_v4(
            authority, project_root=self.root,
            expected_authority_sha256=authority["authority_sha256"],
        )
        self.assertEqual(aliased["status"], "blocked")
        self.assertEqual(aliased["checked_artifact_count"], 0)
        self.assertIs(aliased["validation_records_authenticated"], False)

    def test_malformed_adapter_success_cannot_authenticate_or_authorize(self) -> None:
        authority = self.build()
        forged = {
            "schema_version": 1, "artifact_kind": physical_reader.ASSESSMENT_KIND,
            "status": "physically_valid", "authority_sha256": "0" * 64,
            "validator_id": authority["validator_id"], "checked_artifact_count": 1,
            "blockers": [], "execution_authorized": True,
            "validation_records_authenticated": True,
        }
        with mock.patch.object(
            physical_reader, "assess_backend_runtime_cell_validator_authority",
            return_value=forged,
        ):
            assessment = assess_backend_runtime_validator_authority_v4(
                authority, project_root=self.root,
                expected_authority_sha256=authority["authority_sha256"],
            )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(assessment["blockers"])
        self.assertIs(assessment["execution_authorized"], False)
        self.assertIs(assessment["validation_records_authenticated"], False)

    def test_source_has_no_process_network_callback_or_private_reader_surface(self) -> None:
        source = inspect.getsource(authority_v4)
        for forbidden in (
            "subprocess", "socket", "requests", "docker", "Callable",
            "Popen", "os.system", "exec(", "eval(",
            "_physical_descriptor", "_read_physical_descriptor",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        self.assertIn(
            "physical_reader.assess_backend_runtime_cell_validator_authority", source
        )
        tree = ast.parse(source)
        forbidden_calls = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in {"exec", "eval", "compile"}
        }
        self.assertEqual(forbidden_calls, set())


if __name__ == "__main__":
    unittest.main()
