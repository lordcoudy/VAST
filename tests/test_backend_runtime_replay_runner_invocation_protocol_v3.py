from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_runtime_replay_runner_invocation_protocol_v3 as protocol  # noqa: E402
import backend_runtime_replay_runner_invocation_v2 as old_v2  # noqa: E402


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


class ReplayRunnerInvocationProtocolV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.value = protocol.replay_runner_invocation_protocol_v3_contract()
        self.pin = self.value["protocol_sha256"]

    _DEFAULT = object()

    def validate(self, value=None, pin=_DEFAULT):
        return protocol.validate_replay_runner_invocation_protocol_v3_contract(
            self.value if value is None else value,
            expected_protocol_sha256=self.pin if pin is self._DEFAULT else pin,
        )

    @staticmethod
    def reseal(value):
        value["protocol_sha256"] = canonical_sha({
            key: item for key, item in value.items()
            if key != "protocol_sha256"
        })
        return value

    def test_exact_closed_contract_and_independent_identity(self) -> None:
        self.assertEqual(set(self.value), {
            "schema_version", "artifact_kind", "status", "supported_host_os",
            "concrete_invocation_header", "typed_reference_roles",
            "placeholder_roles", "session_lease_challenge_abi",
            "argv_template", "process_contract_template",
            "exact_false_claims", "protocol_sha256",
        })
        self.assertEqual(self.value["schema_version"], 3)
        self.assertEqual(self.value["artifact_kind"], protocol.ARTIFACT_KIND)
        self.assertEqual(self.value["status"], "immutable_protocol_contract")
        self.assertEqual(self.value["supported_host_os"], ["nt"])
        unsigned = {key: item for key, item in self.value.items()
                    if key != "protocol_sha256"}
        self.assertEqual(self.pin, canonical_sha(unsigned))
        self.assertEqual(self.validate(), self.value)
        second = protocol.replay_runner_invocation_protocol_v3_contract()
        self.assertEqual(second, self.value)
        self.assertIsNot(second, self.value)
        second["argv_template"].append("--mutation")
        self.assertNotEqual(second, self.value)

    def test_future_headers_roles_and_old_v2_are_incompatible(self) -> None:
        header = self.value["concrete_invocation_header"]
        self.assertEqual(header, {
            "schema_version": 3,
            "artifact_kind": (
                "vast_backend_runtime_replay_runner_invocation_contract_v3"
            ),
            "status": "declarative_replay_invocation_candidate",
        })
        roles = self.value["typed_reference_roles"]
        self.assertEqual(roles, {
            "runner_authority": {
                "artifact_schema_version": 2,
                "artifact_kind": "vast_backend_runtime_replay_runner_authority_v2",
            },
            "validator_authority": {
                "artifact_schema_version": 1,
                "artifact_kind": "vast_backend_runtime_validator_authority_q4",
            },
            "request": {
                "artifact_schema_version": 2,
                "artifact_kind": "vast_backend_runtime_validation_replay_request_v2",
            },
            "expected_record": {
                "artifact_schema_version": 2,
                "artifact_kind": "vast_backend_runtime_cell_validation_record_v2",
            },
        })
        self.assertNotEqual(old_v2.SCHEMA_VERSION, header["schema_version"])
        self.assertNotEqual(old_v2.ARTIFACT_KIND, header["artifact_kind"])
        self.assertNotEqual(old_v2.RUNNER_AUTHORITY_KIND,
                            roles["runner_authority"]["artifact_kind"])
        self.assertFalse(hasattr(old_v2, "VALIDATOR_AUTHORITY_KIND"))
        self.assertNotIn("--validator-authority", inspect.getsource(old_v2))

    def test_exact_placeholder_roles_and_argv(self) -> None:
        placeholders = self.value["placeholder_roles"]
        self.assertEqual(set(placeholders), {
            "interpreter_path", "runner_path", "project_root", "session_id",
            "lease_id", "cell_index_decimal", "attempt_ordinal_decimal",
            "challenge_sha256", "runner_authority_path",
            "runner_authority_file_sha256", "runner_authority_sha256",
            "validator_authority_path", "validator_authority_file_sha256",
            "validator_authority_sha256", "request_path",
            "request_file_sha256", "request_sha256", "expected_record_path",
            "expected_record_file_sha256", "expected_record_sha256",
        })
        self.assertEqual(
            placeholders["project_root"]["constraint"],
            "windows_canonical_absolute_path_v2",
        )
        self.assertEqual(self.value["argv_template"], [
            "{interpreter_path}", "-I", "-S", "-B", "-X", "utf8",
            "{runner_path}", "--project-root", "{project_root}",
            "--session-id", "{session_id}", "--lease-id", "{lease_id}",
            "--cell-index", "{cell_index_decimal}", "--attempt-ordinal",
            "{attempt_ordinal_decimal}", "--challenge", "{challenge_sha256}",
            "--runner-authority", "{runner_authority_path}",
            "--runner-authority-file-sha256", "{runner_authority_file_sha256}",
            "--runner-authority-sha256", "{runner_authority_sha256}",
            "--validator-authority", "{validator_authority_path}",
            "--validator-authority-file-sha256",
            "{validator_authority_file_sha256}",
            "--validator-authority-sha256", "{validator_authority_sha256}",
            "--request", "{request_path}", "--request-file-sha256",
            "{request_file_sha256}", "--request-sha256", "{request_sha256}",
            "--expected-record", "{expected_record_path}",
            "--expected-record-file-sha256",
            "{expected_record_file_sha256}",
            "--expected-record-sha256", "{expected_record_sha256}",
        ])

    def test_exact_process_session_abi_and_false_claims(self) -> None:
        ack = (
            "VAST_REPLAY_CHALLENGE_ACK_V3 {session_id} {lease_id} "
            "{cell_index_decimal} {attempt_ordinal_decimal} "
            "{challenge_sha256}\n"
        )
        process = self.value["process_contract_template"]
        self.assertEqual(process, {
            "argv_source": "exact_protocol_argv_template",
            "cwd": "{project_root}",
            "cwd_semantics": "caller_supplied_canonical_project_root",
            "env": {}, "stdin": {"mode": "devnull"},
            "stdout": {
                "channel": "stdout", "mode": "pipe",
                "purpose": "exact_canonical_validation_record_bytes_only",
                "max_bytes": 16 * 1024 * 1024,
            },
            "stderr": {
                "channel": "stderr", "mode": "pipe",
                "purpose": "challenge_acknowledgement_only",
                "framing": "exact_utf8_line",
                "expected_frame_template": ack,
                "diagnostics_allowed": False, "max_bytes": 512,
            },
            "shell": False, "check": False, "close_fds": True,
            "accepted_exit_codes": [0], "timeout_ms": 120000,
            "exit_code_handling": (
                "parent_process_metadata_validates_accepted_exit_codes"
            ),
            "failure_diagnostics_routing": "parent_process_metadata_only",
        })
        self.assertEqual(self.value["session_lease_challenge_abi"], {
            "schema_version": 3,
            "artifact_kind": protocol.SESSION_LEASE_CHALLENGE_ABI_KIND,
            "session_id": {"json_type": "string",
                           "constraint": "safe_token_1_to_128"},
            "lease_id": {"json_type": "string",
                         "constraint": "safe_token_1_to_128"},
            "cell_index": {"json_type": "strict_integer", "minimum": 0,
                           "maximum": 559,
                           "argv_rendering": "canonical_decimal"},
            "attempt_ordinal": {"json_type": "strict_integer", "minimum": 0,
                                "maximum": 1,
                                "argv_rendering": "canonical_decimal"},
            "challenge": {"json_type": "string",
                          "constraint": "lowercase_sha256"},
            "acknowledgement": {"channel": "stderr",
                                "framing": "exact_utf8_line",
                                "template": ack,
                                "diagnostics_allowed": False},
        })
        self.assertEqual(self.value["exact_false_claims"], {
            "atomic_runtime_closure_snapshot_validated": False,
            "lease_enforcement_validated": False,
            "sandbox_enforcement_validated": False,
            "challenge_freshness_validated": False,
            "process_executed": False,
            "validation_records_authenticated": False,
            "execution_authorized": False,
        })

    def test_resealed_old_unknown_reordered_and_true_claims_fail(self) -> None:
        cases = (
            (("schema_version",), 2),
            (("supported_host_os",), ["posix"]),
            (("concrete_invocation_header", "artifact_kind"), old_v2.ARTIFACT_KIND),
            (("typed_reference_roles", "runner_authority", "artifact_kind"),
             old_v2.RUNNER_AUTHORITY_KIND),
            (("process_contract_template", "stderr", "channel"), "stdout"),
            (("process_contract_template", "stderr", "diagnostics_allowed"),
             True),
            (("session_lease_challenge_abi", "cell_index", "maximum"), 560),
            (("exact_false_claims", "execution_authorized"), True),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            self.reseal(changed)
            with self.subTest(path=path), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV3Error
            ):
                self.validate(changed, changed["protocol_sha256"])
        for mutation in ("unknown", "reordered", "missing-validator"):
            changed = copy.deepcopy(self.value)
            if mutation == "unknown":
                changed["dispatch_receipt"] = {}
            elif mutation == "reordered":
                changed["argv_template"][25:31] = reversed(
                    changed["argv_template"][25:31]
                )
            else:
                del changed["argv_template"][25:31]
            self.reseal(changed)
            with self.subTest(mutation=mutation), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV3Error
            ):
                self.validate(changed, changed["protocol_sha256"])

    def test_strict_json_types_external_pin_and_cycles(self) -> None:
        cases = (
            (("schema_version",), 3.0),
            (("supported_host_os",), ("nt",)),
            (("concrete_invocation_header", "schema_version"), True),
            (("typed_reference_roles", "request", "artifact_schema_version"),
             2.0),
            (("process_contract_template", "timeout_ms"), True),
            (("process_contract_template", "timeout_ms"), 120000.0),
            (("process_contract_template", "accepted_exit_codes"), [False]),
            (("process_contract_template", "stdout", "max_bytes"),
             float(16 * 1024 * 1024)),
            (("session_lease_challenge_abi", "cell_index", "maximum"), 559.0),
            (("exact_false_claims", "process_executed"), 0),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV3Error
            ):
                self.validate(changed)
        changed = copy.deepcopy(self.value)
        changed["process_contract_template"]["env"]["cycle"] = changed
        with self.assertRaises(protocol.ReplayRunnerInvocationProtocolV3Error):
            self.validate(changed)
        for bad in (None, True, 1, "A" * 64, "0" * 63,
                    hashlib.sha256(b"wrong").hexdigest()):
            with self.subTest(pin=bad), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV3Error
            ):
                self.validate(pin=bad)

    def test_resealed_equal_bool_int_float_and_container_smuggling_fails(
        self,
    ) -> None:
        class DictSubclass(dict):
            pass

        class ListSubclass(list):
            pass

        cases = (
            (("typed_reference_roles", "validator_authority",
              "artifact_schema_version"), True),
            (("session_lease_challenge_abi", "cell_index", "minimum"), False),
            (("session_lease_challenge_abi", "attempt_ordinal", "maximum"),
             True),
            (("process_contract_template", "shell"), 0),
            (("process_contract_template", "check"), 0),
            (("process_contract_template", "close_fds"), 1),
            (("process_contract_template", "accepted_exit_codes"), [False]),
            (("schema_version",), 3.0),
            (("process_contract_template", "env"), DictSubclass()),
            (("supported_host_os",), ListSubclass(["nt"])),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            changed["protocol_sha256"] = canonical_sha({
                key: item for key, item in changed.items()
                if key != "protocol_sha256"
            })
            with self.subTest(path=path), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV3Error
            ):
                self.validate(changed, changed["protocol_sha256"])

    def test_validator_uses_exact_type_skeleton_and_unsigned_identity(self) -> None:
        source = inspect.getsource(
            protocol.validate_replay_runner_invocation_protocol_v3_contract
        )
        self.assertIn("_exact_type_skeleton(value, expected)", source)
        self.assertIn("_canonical_sha(unsigned)", source)
        self.assertIn("_canonical_sha(expected_unsigned)", source)
        self.assertNotIn("value == expected", source)

    def test_pure_source_and_closed_public_api(self) -> None:
        source = inspect.getsource(protocol)
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue(imports <= {
            "__future__", "copy", "hashlib", "json", "re", "typing",
        })
        for forbidden in ("subprocess", "socket", "requests", "pathlib",
                          "open(", "exec(", "eval(",
                          "readiness", "dispatch", "grant"):
            self.assertNotIn(forbidden, source.lower())
        self.assertEqual(set(protocol.__all__), {
            "SCHEMA_VERSION", "ARTIFACT_KIND",
            "CONCRETE_INVOCATION_SCHEMA_VERSION", "CONCRETE_INVOCATION_KIND",
            "RUNNER_AUTHORITY_SCHEMA_VERSION", "RUNNER_AUTHORITY_KIND",
            "VALIDATOR_AUTHORITY_SCHEMA_VERSION", "VALIDATOR_AUTHORITY_KIND",
            "REQUEST_SCHEMA_VERSION", "REQUEST_KIND", "RECORD_SCHEMA_VERSION",
            "RECORD_KIND", "SESSION_LEASE_CHALLENGE_ABI_KIND",
            "ReplayRunnerInvocationProtocolV3Error",
            "replay_runner_invocation_protocol_v3_contract",
            "validate_replay_runner_invocation_protocol_v3_contract",
        })
        signature = inspect.signature(
            protocol.validate_replay_runner_invocation_protocol_v3_contract
        )
        self.assertEqual(list(signature.parameters),
                         ["value", "expected_protocol_sha256"])
        self.assertEqual(
            signature.parameters["expected_protocol_sha256"].kind,
            inspect.Parameter.KEYWORD_ONLY,
        )
        self.assertIs(signature.parameters[
            "expected_protocol_sha256"
        ].default, inspect.Parameter.empty)


if __name__ == "__main__":
    unittest.main()
