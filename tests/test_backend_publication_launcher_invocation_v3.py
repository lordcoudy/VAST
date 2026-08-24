from __future__ import annotations

import ast
import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_runtime_qualification_v4_input_index as q4  # noqa: E402
from backend_publication_dispatch import launcher_invocation_contract  # noqa: E402
from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    ARTIFACT_KIND, INPUT_PROTOCOL_DOMAIN, INPUT_PROTOCOL_IDENTITY_SHA256,
    INVOCATION_KIND, INVOCATION_SCHEMA_VERSION, MAX_STDERR_BYTES,
    MAX_STDOUT_BYTES, OUTPUT_PROTOCOL_DOMAIN, OUTPUT_PROTOCOL_IDENTITY_SHA256,
    PROCESS_TIMEOUT_MS, PUBLICATION_LAUNCHER_INVOCATION_V3_KIND,
    PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION, SCHEMA_VERSION,
    BackendPublicationLauncherInvocationV3Error,
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def reseal(value: dict[str, object]) -> None:
    value.pop("invocation_sha256", None)
    value["invocation_sha256"] = canonical_sha(value)


class BackendPublicationLauncherInvocationV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.contract = publication_launcher_invocation_v3_contract()

    def test_constants_match_q4_and_protocol_domains_are_explicit_v3(self) -> None:
        self.assertEqual(SCHEMA_VERSION, 3)
        self.assertEqual(INVOCATION_SCHEMA_VERSION, SCHEMA_VERSION)
        self.assertEqual(PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION,
                         q4.PUBLICATION_LAUNCHER_INVOCATION_V3_SCHEMA_VERSION)
        self.assertEqual(ARTIFACT_KIND, q4.PUBLICATION_LAUNCHER_INVOCATION_V3_KIND)
        self.assertEqual(INVOCATION_KIND, ARTIFACT_KIND)
        self.assertEqual(PUBLICATION_LAUNCHER_INVOCATION_V3_KIND, ARTIFACT_KIND)
        self.assertEqual(INPUT_PROTOCOL_DOMAIN,
                         "vast-full-publication-arm-contract-json-v3")
        self.assertEqual(OUTPUT_PROTOCOL_DOMAIN,
                         "vast-full-publication-arm-output-receipt-json-v3")
        self.assertEqual(INPUT_PROTOCOL_IDENTITY_SHA256,
                         hashlib.sha256(INPUT_PROTOCOL_DOMAIN.encode("ascii")).hexdigest())
        self.assertEqual(OUTPUT_PROTOCOL_IDENTITY_SHA256,
                         hashlib.sha256(OUTPUT_PROTOCOL_DOMAIN.encode("ascii")).hexdigest())

    def test_contract_has_exact_caller_bound_argv_and_empty_environment(self) -> None:
        self.assertEqual(self.contract["schema_version"], 3)
        self.assertEqual(self.contract["artifact_kind"], ARTIFACT_KIND)
        self.assertEqual(self.contract["runtime_kind"], "python3_caller_bound_argv_v3")
        self.assertEqual(self.contract["argv_template"], [
            "{python_executable}", "{launcher_path}",
            "--project-root", "{project_root}",
            "--arm-contract", "{arm_contract_path}",
            "--arm-contract-sha256", "{arm_contract_file_sha256}",
            "--output-dir", "{output_dir}",
        ])
        self.assertEqual(self.contract["required_env_keys"], [])
        process = self.contract["process_contract"]
        self.assertIs(process["shell"], False)
        self.assertIs(process["check"], False)
        self.assertEqual(process["environment"], {})
        self.assertEqual(process["cwd_source"],
                         "caller_supplied_canonical_project_root")
        self.assertEqual(process["stdin"], "DEVNULL")
        self.assertEqual(process["stdout"], "bounded_capture_pipe")
        self.assertEqual(process["stderr"], "bounded_capture_pipe")
        self.assertIs(process["close_fds"], True)
        self.assertEqual(process["accepted_exit_codes"], [0])
        self.assertEqual(process["accepted_exit_code_semantics"],
                         "launcher_success_only_receipt_finalization_is_separate")
        self.assertEqual(process["timeout_ms"], PROCESS_TIMEOUT_MS)
        self.assertEqual(process["max_stdout_bytes"], MAX_STDOUT_BYTES)
        self.assertEqual(process["max_stderr_bytes"], MAX_STDERR_BYTES)
        self.assertGreater(PROCESS_TIMEOUT_MS, 0)
        self.assertGreater(MAX_STDOUT_BYTES, 0)
        self.assertGreater(MAX_STDERR_BYTES, 0)
        self.assertEqual(self.contract["input_protocol_identity_sha256"],
                         INPUT_PROTOCOL_IDENTITY_SHA256)
        self.assertEqual(self.contract["output_protocol_identity_sha256"],
                         OUTPUT_PROTOCOL_IDENTITY_SHA256)
        self.assertIs(self.contract["execution_authorized"], False)

    def test_contract_is_self_hashed_and_returns_independent_copies(self) -> None:
        unsigned = {key: value for key, value in self.contract.items()
                    if key != "invocation_sha256"}
        self.assertEqual(self.contract["invocation_sha256"], canonical_sha(unsigned))
        second = publication_launcher_invocation_v3_contract()
        self.contract["argv_template"].append("--unsafe")
        self.contract["process_contract"]["environment"]["UNSAFE"] = "1"
        self.assertNotEqual(self.contract, second)
        self.assertEqual(second, publication_launcher_invocation_v3_contract())

    def test_validator_accepts_only_the_exact_closed_contract(self) -> None:
        validated = validate_publication_launcher_invocation_v3(self.contract)
        self.assertEqual(validated, self.contract)
        validated["argv_template"].append("--unsafe")
        self.assertEqual(validate_publication_launcher_invocation_v3(self.contract),
                         self.contract)

    def test_abi_v2_and_relabelled_v2_are_rejected(self) -> None:
        old = launcher_invocation_contract()
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(old)
        relabelled = copy.deepcopy(old)
        relabelled["schema_version"] = 3
        relabelled["artifact_kind"] = ARTIFACT_KIND
        reseal(relabelled)
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(relabelled)

    def test_argv_drift_missing_file_sha_and_unsafe_placeholders_fail_closed(self) -> None:
        mutations: list[dict[str, object]] = []
        for action in ("missing_file_sha", "extra_arg", "unsafe", "reorder"):
            changed = copy.deepcopy(self.contract)
            argv = changed["argv_template"]
            if action == "missing_file_sha":
                del argv[6:8]
            elif action == "extra_arg":
                argv.extend(["--plan", "{plan_path}"])
            elif action == "unsafe":
                argv[3] = "{project_root};unsafe"
            else:
                argv[4:8] = argv[6:8] + argv[4:6]
            reseal(changed)
            mutations.append(changed)
        for changed in mutations:
            with self.subTest(argv=changed["argv_template"]), self.assertRaises(
                BackendPublicationLauncherInvocationV3Error
            ):
                validate_publication_launcher_invocation_v3(changed)

    def test_process_protocol_authorization_and_field_drift_fail_closed(self) -> None:
        mutations: list[dict[str, object]] = []
        for field, value in (
            ("shell", True), ("check", True),
            ("environment", {"PATH": "caller"}), ("cwd_source", "output_dir"),
            ("accepted_exit_codes", [0, 78]), ("timeout_ms", PROCESS_TIMEOUT_MS + 1),
            ("max_stdout_bytes", MAX_STDOUT_BYTES + 1),
            ("max_stderr_bytes", MAX_STDERR_BYTES + 1),
        ):
            changed = copy.deepcopy(self.contract)
            changed["process_contract"][field] = value
            reseal(changed)
            mutations.append(changed)
        for field, value in (
            ("input_protocol_identity_sha256", "0" * 64),
            ("output_protocol_identity_sha256", "1" * 64),
            ("execution_authorized", True),
        ):
            changed = copy.deepcopy(self.contract)
            changed[field] = value
            reseal(changed)
            mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["process_contract"]["unknown"] = False
        reseal(changed)
        mutations.append(changed)
        changed = copy.deepcopy(self.contract)
        changed["unknown"] = False
        reseal(changed)
        mutations.append(changed)
        for changed in mutations:
            with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
                validate_publication_launcher_invocation_v3(changed)

    def test_json_type_substitution_and_broken_self_hash_are_rejected(self) -> None:
        changed = copy.deepcopy(self.contract)
        changed["process_contract"]["shell"] = 0
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["schema_version"] = 3.0
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["argv_template"] = tuple(changed["argv_template"])
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["required_env_keys"] = tuple()
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["process_contract"]["timeout_ms"] = float(PROCESS_TIMEOUT_MS)
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["process_contract"]["max_stdout_bytes"] = True
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["process_contract"]["accepted_exit_codes"] = (0,)
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)
        changed = copy.deepcopy(self.contract)
        changed["invocation_sha256"] = "f" * 64
        with self.assertRaises(BackendPublicationLauncherInvocationV3Error):
            validate_publication_launcher_invocation_v3(changed)

    def test_source_is_pure_declarative_and_has_no_execution_surface(self) -> None:
        source = (ROOT / "scripts" /
                  "backend_publication_launcher_invocation_v3.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names}
        imported |= {(node.module or "").split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom)}
        self.assertTrue(imported <= {"__future__", "copy", "hashlib", "json", "typing"})
        called_names = {node.func.id for node in ast.walk(tree)
                        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
        self.assertFalse(called_names & {"open", "exec", "eval", "compile", "input", "__import__"})
        lowered = source.lower()
        for prohibited in ("subprocess", "socket", "pathlib", "backend_runtime_grant",
                           "publication_matrix", "readiness", "callback"):
            self.assertNotIn(prohibited, lowered)


if __name__ == "__main__":
    unittest.main()
