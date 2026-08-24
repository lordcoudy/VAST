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

import backend_runtime_replay_runner_invocation_v2 as contract  # noqa: E402


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def independent_canonical_identity(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def typed(
    label: str, schema_version: int, artifact_kind: str,
    semantic: str,
) -> dict[str, object]:
    payload = (label + "\n").encode("utf-8")
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": {
            "path": f"qualification/replay-v2/{label}.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
        "content_identity_sha256": semantic,
    }


def expected_unsigned(kwargs: dict[str, object]) -> dict[str, object]:
    runner_ref = kwargs["runner_authority_ref"]
    request_ref = kwargs["request_ref"]
    record_ref = kwargs["expected_record_ref"]
    cell = kwargs["cell_index"]
    attempt = kwargs["attempt_ordinal"]
    challenge = kwargs["challenge"]
    argv = [
        kwargs["interpreter_path"], "-I", "-S", "-B", "-X", "utf8",
        kwargs["runner_path"], "--project-root", kwargs["project_root"],
        "--session-id", kwargs["session_id"], "--lease-id",
        kwargs["lease_id"], "--cell-index", str(cell),
        "--attempt-ordinal", str(attempt), "--challenge", challenge,
        "--runner-authority", runner_ref["descriptor"]["path"],
        "--runner-authority-file-sha256",
        runner_ref["descriptor"]["sha256"],
        "--runner-authority-sha256", kwargs["runner_authority_sha256"],
        "--request", request_ref["descriptor"]["path"],
        "--request-file-sha256", request_ref["descriptor"]["sha256"],
        "--request-sha256", kwargs["request_sha256"],
        "--expected-record", record_ref["descriptor"]["path"],
        "--expected-record-file-sha256",
        record_ref["descriptor"]["sha256"],
        "--expected-record-sha256", kwargs["expected_record_sha256"],
    ]
    ack = (
        f"VAST_REPLAY_CHALLENGE_ACK_V2 {kwargs['session_id']} "
        f"{kwargs['lease_id']} {cell} {attempt} {challenge}\n"
    )
    return {
        "schema_version": 2, "artifact_kind": contract.ARTIFACT_KIND,
        "status": "declarative_replay_invocation_candidate",
        "project_root": kwargs["project_root"],
        "interpreter_path": kwargs["interpreter_path"],
        "runner_path": kwargs["runner_path"],
        "runner_authority_ref": copy.deepcopy(runner_ref),
        "runner_authority_sha256": kwargs["runner_authority_sha256"],
        "request_ref": copy.deepcopy(request_ref),
        "request_sha256": kwargs["request_sha256"],
        "expected_record_ref": copy.deepcopy(record_ref),
        "expected_record_sha256": kwargs["expected_record_sha256"],
        "session_id": kwargs["session_id"], "lease_id": kwargs["lease_id"],
        "cell_index": cell, "attempt_ordinal": attempt,
        "challenge": challenge,
        "process_contract": {
            "argv": argv, "cwd": kwargs["project_root"],
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
                "framing": "exact_utf8_line", "expected_frame": ack,
                "diagnostics_allowed": False, "max_bytes": 512,
            },
            "shell": False, "check": False, "close_fds": True,
            "accepted_exit_codes": [0], "timeout_ms": 120000,
            "exit_code_handling": (
                "parent_process_metadata_validates_accepted_exit_codes"
            ),
            "failure_diagnostics_routing": "parent_process_metadata_only",
        },
        "process_executed": False, "execution_authorized": False,
        "challenge_freshness_validated": False,
        "lease_enforcement_validated": False,
        "sandbox_enforcement_validated": False,
    }


class Fixture:
    def __init__(self) -> None:
        self.runner_sha = sha("runner-authority")
        self.request_sha = sha("request")
        self.record_sha = sha("record")
        self.runner_ref = typed(
            "runner-authority", 1, contract.RUNNER_AUTHORITY_KIND,
            self.runner_sha,
        )
        self.request_ref = typed(
            "request-17", 2, contract.REQUEST_KIND, self.request_sha,
        )
        self.record_ref = typed(
            "record-17", 2, contract.RECORD_KIND, self.record_sha,
        )
        self.kwargs = {
            "project_root": "C:/vast/recovery-safe",
            "interpreter_path": "runtime/python/python.exe",
            "runner_path": "scripts/backend_runtime_replay_worker.py",
            "runner_authority_ref": self.runner_ref,
            "runner_authority_sha256": self.runner_sha,
            "request_ref": self.request_ref,
            "request_sha256": self.request_sha,
            "expected_record_ref": self.record_ref,
            "expected_record_sha256": self.record_sha,
            "session_id": "session-20260812-0001",
            "lease_id": "lease-candidate-0001",
            "cell_index": 17,
            "attempt_ordinal": 0,
            "challenge": sha("challenge"),
        }
        self.semantic = independent_canonical_identity(
            expected_unsigned(self.kwargs)
        )
        self.value = contract.build_backend_runtime_replay_runner_invocation_v2(
            **self.kwargs, expected_semantic_sha256=self.semantic,
        )

    def expected(self) -> dict[str, object]:
        expected = {
            "expected_semantic_sha256": self.semantic,
            **{f"expected_{key}": value for key, value in self.kwargs.items()},
        }
        expected["expected_record_ref"] = expected.pop(
            "expected_expected_record_ref"
        )
        expected["expected_record_sha256"] = expected.pop(
            "expected_expected_record_sha256"
        )
        return expected

    def expected_for_resealed(self, value: dict[str, object]) -> dict[str, object]:
        expected = self.expected()
        expected["expected_semantic_sha256"] = value["invocation_sha256"]
        return expected


class ReplayRunnerInvocationV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.f = Fixture()

    def test_exact_declarative_contract(self) -> None:
        value = self.f.value
        self.assertEqual(value["schema_version"], 2)
        self.assertEqual(value["artifact_kind"], contract.ARTIFACT_KIND)
        self.assertEqual(value["status"],
                         "declarative_replay_invocation_candidate")
        for field in (
            "process_executed", "execution_authorized",
            "challenge_freshness_validated", "lease_enforcement_validated",
            "sandbox_enforcement_validated",
        ):
            self.assertIs(value[field], False)
        process = value["process_contract"]
        self.assertEqual(process["cwd"], self.f.kwargs["project_root"])
        self.assertEqual(process["env"], {})
        self.assertEqual(process["stdin"], {"mode": "devnull"})
        self.assertEqual(process["accepted_exit_codes"], [0])
        self.assertEqual(
            process["exit_code_handling"],
            "parent_process_metadata_validates_accepted_exit_codes",
        )
        self.assertEqual(
            process["failure_diagnostics_routing"],
            "parent_process_metadata_only",
        )
        self.assertIs(process["shell"], False)
        self.assertIs(process["check"], False)
        self.assertIs(process["close_fds"], True)
        self.assertNotEqual(process["stdout"]["channel"],
                            process["stderr"]["channel"])

    def test_exact_argv_order_and_all_identity_pins(self) -> None:
        k = self.f.kwargs
        self.assertEqual(self.f.value["process_contract"]["argv"], [
            k["interpreter_path"], "-I", "-S", "-B", "-X", "utf8",
            k["runner_path"], "--project-root", k["project_root"],
            "--session-id", k["session_id"], "--lease-id", k["lease_id"],
            "--cell-index", "17", "--attempt-ordinal", "0",
            "--challenge", k["challenge"],
            "--runner-authority", self.f.runner_ref["descriptor"]["path"],
            "--runner-authority-file-sha256",
            self.f.runner_ref["descriptor"]["sha256"],
            "--runner-authority-sha256", self.f.runner_sha,
            "--request", self.f.request_ref["descriptor"]["path"],
            "--request-file-sha256", self.f.request_ref["descriptor"]["sha256"],
            "--request-sha256", self.f.request_sha,
            "--expected-record", self.f.record_ref["descriptor"]["path"],
            "--expected-record-file-sha256",
            self.f.record_ref["descriptor"]["sha256"],
            "--expected-record-sha256", self.f.record_sha,
        ])

    def test_stdout_and_ack_are_exact_distinct_bounded_channels(self) -> None:
        process = self.f.value["process_contract"]
        self.assertEqual(process["stdout"], {
            "channel": "stdout", "mode": "pipe",
            "purpose": "exact_canonical_validation_record_bytes_only",
            "max_bytes": 16 * 1024 * 1024,
        })
        expected = (
            "VAST_REPLAY_CHALLENGE_ACK_V2 session-20260812-0001 "
            "lease-candidate-0001 17 0 " + self.f.kwargs["challenge"] + "\n"
        )
        self.assertEqual(process["stderr"], {
            "channel": "stderr", "mode": "pipe",
            "purpose": "challenge_acknowledgement_only",
            "framing": "exact_utf8_line", "expected_frame": expected,
            "diagnostics_allowed": False, "max_bytes": 512,
        })

    def test_strict_numeric_and_boolean_json_types(self) -> None:
        for field, bad_values in {
            "cell_index": (True, 17.0, "17", -1, 560),
            "attempt_ordinal": (False, 0.0, "0", -1, 2),
        }.items():
            for bad in bad_values:
                with self.subTest(field=field, value=bad):
                    kwargs = copy.deepcopy(self.f.kwargs)
                    kwargs[field] = bad
                    with self.assertRaises(contract.ReplayRunnerInvocationV2Error):
                        contract.build_backend_runtime_replay_runner_invocation_v2(
                            **kwargs, expected_semantic_sha256=self.f.semantic,
                        )
        for field in (
            "process_executed", "execution_authorized",
            "challenge_freshness_validated", "lease_enforcement_validated",
            "sandbox_enforcement_validated",
        ):
            changed = copy.deepcopy(self.f.value)
            changed[field] = 0
            changed["invocation_sha256"] = independent_canonical_identity({
                key: item for key, item in changed.items()
                if key != "invocation_sha256"
            })
            with self.subTest(field=field), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.validate_backend_runtime_replay_runner_invocation_v2(
                    changed, **self.f.expected_for_resealed(changed)
                )

    def test_nested_process_types_reject_bool_int_float_smuggling(self) -> None:
        cases = (
            (("schema_version",), 2.0),
            (("process_contract", "timeout_ms"), True),
            (("process_contract", "timeout_ms"), 120000.0),
            (("process_contract", "accepted_exit_codes"), [False]),
            (("process_contract", "accepted_exit_codes"), [0.0]),
            (("process_contract", "accepted_exit_codes"), [0, 1]),
            (("process_contract", "stdout", "max_bytes"),
             float(16 * 1024 * 1024)),
            (("process_contract", "stderr", "max_bytes"), True),
            (("process_contract", "stderr", "max_bytes"), 512.0),
            (("process_contract", "shell"), 0),
            (("process_contract", "check"), 0),
            (("process_contract", "close_fds"), 1),
            (("process_contract", "stderr", "diagnostics_allowed"), 0),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.f.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            try:
                changed["invocation_sha256"] = independent_canonical_identity({
                    key: item for key, item in changed.items()
                    if key != "invocation_sha256"
                })
            except contract.ReplayRunnerInvocationV2Error:
                pass
            with self.subTest(path=path), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.validate_backend_runtime_replay_runner_invocation_v2(
                    changed, **self.f.expected_for_resealed(changed)
                )

    def test_non_json_containers_and_python_object_cycles_are_rejected(
        self,
    ) -> None:
        class DictSubclass(dict):
            pass

        for path, replacement in (
            (("process_contract", "argv"),
             tuple(self.f.value["process_contract"]["argv"])),
            (("process_contract", "accepted_exit_codes"), (0,)),
            (("process_contract", "env"), DictSubclass()),
        ):
            changed = copy.deepcopy(self.f.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.validate_backend_runtime_replay_runner_invocation_v2(
                    changed, **self.f.expected()
                )

        changed = copy.deepcopy(self.f.value)
        changed["process_contract"]["env"]["cycle"] = (
            changed["process_contract"]["env"]
        )
        with self.assertRaises(contract.ReplayRunnerInvocationV2Error):
            contract.validate_backend_runtime_replay_runner_invocation_v2(
                changed, **self.f.expected()
            )
        for value in ({"value": (1,)}, {"value": 1.0}, {"value": None}):
            with self.subTest(canonical=value), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.canonical_identity(value)

    def test_typed_reference_numeric_types_and_role_aliases_are_rejected(
        self,
    ) -> None:
        for path, replacement in (
            (("runner_authority_ref", "artifact_schema_version"), True),
            (("request_ref", "artifact_schema_version"), 2.0),
            (("expected_record_ref", "descriptor", "size_bytes"), True),
            (("request_ref", "descriptor", "size_bytes"), 8.0),
        ):
            kwargs = copy.deepcopy(self.f.kwargs)
            target = kwargs
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            with self.subTest(path=path), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.build_backend_runtime_replay_runner_invocation_v2(
                    **kwargs,
                    expected_semantic_sha256=independent_canonical_identity(
                        expected_unsigned(kwargs)
                    ),
                )

        for descriptor_field in ("path", "sha256"):
            kwargs = copy.deepcopy(self.f.kwargs)
            kwargs["request_ref"]["descriptor"][descriptor_field] = (
                kwargs["runner_authority_ref"]["descriptor"][descriptor_field]
            )
            with self.subTest(alias=descriptor_field), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.build_backend_runtime_replay_runner_invocation_v2(
                    **kwargs,
                    expected_semantic_sha256=independent_canonical_identity(
                        expected_unsigned(kwargs)
                    ),
                )

        for role_path in ("interpreter", "runner"):
            kwargs = copy.deepcopy(self.f.kwargs)
            if role_path == "interpreter":
                kwargs["runner_path"] = kwargs["interpreter_path"].upper()
            else:
                kwargs["request_ref"]["descriptor"]["path"] = (
                    kwargs["runner_path"].upper()
                )
            with self.subTest(role_path=role_path), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.build_backend_runtime_replay_runner_invocation_v2(
                    **kwargs,
                    expected_semantic_sha256=independent_canonical_identity(
                        expected_unsigned(kwargs)
                    ),
                )

    def test_missing_extra_and_reordered_argv_are_rejected_when_resealed(self) -> None:
        for mutation in ("missing", "extra", "reordered"):
            changed = copy.deepcopy(self.f.value)
            argv = changed["process_contract"]["argv"]
            if mutation == "missing":
                del argv[-2:]
            elif mutation == "extra":
                argv.append("--extra")
            else:
                argv[7], argv[9] = argv[9], argv[7]
            changed["invocation_sha256"] = independent_canonical_identity({
                key: item for key, item in changed.items()
                if key != "invocation_sha256"
            })
            with self.subTest(mutation=mutation), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.validate_backend_runtime_replay_runner_invocation_v2(
                    changed, **self.f.expected_for_resealed(changed)
                )

    def test_same_channel_and_ack_mutations_are_rejected_when_resealed(self) -> None:
        for mutation in ("same-channel", "ack-frame", "diagnostics"):
            changed = copy.deepcopy(self.f.value)
            stderr = changed["process_contract"]["stderr"]
            if mutation == "same-channel":
                stderr["channel"] = "stdout"
            elif mutation == "ack-frame":
                stderr["expected_frame"] += "extra"
            else:
                stderr["diagnostics_allowed"] = True
            changed["invocation_sha256"] = independent_canonical_identity({
                key: item for key, item in changed.items()
                if key != "invocation_sha256"
            })
            with self.subTest(mutation=mutation), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.validate_backend_runtime_replay_runner_invocation_v2(
                    changed, **self.f.expected_for_resealed(changed)
                )

    def test_unknown_cycle_and_true_claims_are_rejected_when_resealed(self) -> None:
        for mutation in ("unknown", "cycle"):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.f.value)
                if mutation == "unknown":
                    changed["output_receipt"] = {}
                else:
                    changed["request_ref"]["content_identity_sha256"] = (
                        changed["invocation_sha256"]
                    )
                changed["invocation_sha256"] = independent_canonical_identity({
                    key: item for key, item in changed.items()
                    if key != "invocation_sha256"
                })
                with self.assertRaises(contract.ReplayRunnerInvocationV2Error):
                    contract.validate_backend_runtime_replay_runner_invocation_v2(
                        changed, **self.f.expected_for_resealed(changed)
                    )
        for field in (
            "process_executed", "execution_authorized",
            "challenge_freshness_validated", "lease_enforcement_validated",
            "sandbox_enforcement_validated",
        ):
            with self.subTest(true_claim=field):
                changed = copy.deepcopy(self.f.value)
                changed[field] = True
                changed["invocation_sha256"] = independent_canonical_identity({
                    key: item for key, item in changed.items()
                    if key != "invocation_sha256"
                })
                with self.assertRaises(contract.ReplayRunnerInvocationV2Error):
                    contract.validate_backend_runtime_replay_runner_invocation_v2(
                        changed, **self.f.expected_for_resealed(changed)
                    )

    def test_attempt_one_and_last_cell_are_valid_candidates(self) -> None:
        kwargs = copy.deepcopy(self.f.kwargs)
        kwargs["cell_index"] = 559
        kwargs["attempt_ordinal"] = 1
        semantic = independent_canonical_identity(expected_unsigned(kwargs))
        value = contract.build_backend_runtime_replay_runner_invocation_v2(
            **kwargs, expected_semantic_sha256=semantic
        )
        self.assertEqual(value["cell_index"], 559)
        self.assertEqual(value["attempt_ordinal"], 1)

    def test_session_lease_challenge_and_paths_are_safe_external_values(
        self,
    ) -> None:
        for field, bad in (
            ("session_id", "session with space"),
            ("session_id", True),
            ("lease_id", "lease\nforged"),
            ("lease_id", ""),
            ("challenge", "not-a-sha256-token"),
            ("project_root", "C:/vast/../escape"),
            ("interpreter_path", "C:/host/python.exe"),
            ("runner_path", "../worker.py"),
        ):
            kwargs = copy.deepcopy(self.f.kwargs)
            kwargs[field] = bad
            with self.subTest(field=field, bad=bad), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.build_backend_runtime_replay_runner_invocation_v2(
                    **kwargs, expected_semantic_sha256=self.f.semantic,
                )

        for pin_field in (
            "runner_authority_sha256", "request_sha256",
            "expected_record_sha256",
        ):
            kwargs = copy.deepcopy(self.f.kwargs)
            kwargs[pin_field] = sha("wrong-" + pin_field)
            with self.subTest(pin=pin_field), self.assertRaises(
                contract.ReplayRunnerInvocationV2Error
            ):
                contract.build_backend_runtime_replay_runner_invocation_v2(
                    **kwargs, expected_semantic_sha256=self.f.semantic,
                )

    def test_external_self_hash_and_typed_ref_pins_are_mandatory(self) -> None:
        with self.assertRaises(contract.ReplayRunnerInvocationV2Error):
            contract.build_backend_runtime_replay_runner_invocation_v2(
                **self.f.kwargs, expected_semantic_sha256=sha("wrong")
            )
        changed = copy.deepcopy(self.f.value)
        changed["request_ref"]["artifact_schema_version"] = 1
        with self.assertRaises(contract.ReplayRunnerInvocationV2Error):
            contract.validate_backend_runtime_replay_runner_invocation_v2(
                changed, **self.f.expected()
            )

    def test_pure_source_and_all_external_pins_required(self) -> None:
        source = inspect.getsource(contract)
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
        for forbidden in (
            "subprocess", "socket", "requests", "pathlib", "open(",
            "exec(", "eval(", "compile(", "grant", "readiness", "dispatch",
        ):
            self.assertNotIn(forbidden, source.lower())
        for function in (
            contract.build_backend_runtime_replay_runner_invocation_v2,
            contract.validate_backend_runtime_replay_runner_invocation_v2,
        ):
            self.assertTrue(all(
                parameter.default is inspect.Parameter.empty
                for parameter in inspect.signature(function).parameters.values()
            ))
        self.assertNotIn(
            "preview_backend_runtime_replay_runner_invocation_v2",
            contract.__all__,
        )
        self.assertFalse(hasattr(
            contract, "preview_backend_runtime_replay_runner_invocation_v2"
        ))


if __name__ == "__main__":
    unittest.main()
