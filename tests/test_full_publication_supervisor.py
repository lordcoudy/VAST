from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_publication_supervisor as supervisor_module  # noqa: E402
from full_publication_supervisor import (  # noqa: E402
    EXIT_COMPLETE,
    EXIT_PERMANENT,
    EXIT_TRANSIENT,
    FROZEN_FULL_PUBLICATION_MATRIX_SCHEMA_VERSION,
    FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
    FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256,
    FullPublicationSupervisor,
    InvocationUnavailable,
    SubprocessEntrypointInvoker,
    SupervisorError,
    UnexpectedProcessExit,
)


FROZEN_ENTRYPOINT_ARGS = (
    "--expected-matrix-sha256",
    FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
    "--expected-policy-contract-sha256",
    FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256,
)


def outcome(phase: str, code: int) -> tuple[int, dict[str, object]]:
    if code != EXIT_COMPLETE:
        return code, {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_command_error",
            "status": "transient_error" if code == EXIT_TRANSIENT else "permanent_error",
            "exit_code": code,
        }
    if phase == "run":
        return code, {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_command_result",
            "exit_code": 0,
            "status": "complete",
            "completed_pairs": 2800,
            "completed_arms": 5600,
            "total_pairs": 2800,
            "total_arms": 5600,
        }
    if phase == "verify":
        return code, {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_verification",
            "passed": True,
            "complete": True,
        }
    if phase == "finalize":
        return code, {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_finalization",
            "verified": True,
        }
    return code, {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_compact_result_bundle",
    }


class SequenceInvoker:
    def __init__(self, values: list[object]) -> None:
        self.values = list(values)
        self.phases: list[str] = []

    def __call__(self, phase: str) -> tuple[int, dict[str, object]]:
        self.phases.append(phase)
        value = self.values.pop(0)
        if isinstance(value, BaseException):
            raise value
        if isinstance(value, int):
            return outcome(phase, value)
        return value  # type: ignore[return-value]


class FullPublicationSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.state_path = Path(self.temp.name) / "full.supervisor.json"
        self.identity = {"entrypoint_sha256": "a" * 64, "args": ["--run-root", "run"]}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def supervisor(self, invoker: SequenceInvoker, sleeps: list[float], **kwargs: object) -> FullPublicationSupervisor:
        return FullPublicationSupervisor(
            state_path=self.state_path,
            invoker=invoker,
            command_identity=self.identity,
            backoff_s=(1.0, 5.0),
            sleep_fn=sleeps.append,
            **kwargs,
        )

    def test_retries_transient_run_and_finalize_then_exports(self) -> None:
        invoker = SequenceInvoker([
            EXIT_TRANSIENT,
            EXIT_COMPLETE,
            EXIT_COMPLETE,
            EXIT_TRANSIENT,
            EXIT_COMPLETE,
            EXIT_COMPLETE,
        ])
        sleeps: list[float] = []
        code, state = self.supervisor(invoker, sleeps).run()
        self.assertEqual(code, EXIT_COMPLETE)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(
            invoker.phases,
            ["run", "run", "verify", "finalize", "finalize", "export"],
        )
        self.assertEqual(sleeps, [1.0, 1.0])
        persisted = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(persisted["attempt_seq"], 6)
        self.assertIsNotNone(persisted["completed_at"])

    def test_permanent_result_stops_without_retry(self) -> None:
        invoker = SequenceInvoker([EXIT_PERMANENT])
        code, state = self.supervisor(invoker, []).run()
        self.assertEqual(code, EXIT_PERMANENT)
        self.assertEqual(state["phase"], "failed_permanent")
        self.assertEqual(invoker.phases, ["run"])

    def test_restart_resumes_persisted_phase_and_rejects_command_drift(self) -> None:
        first = SequenceInvoker([EXIT_TRANSIENT, EXIT_COMPLETE, EXIT_COMPLETE, EXIT_PERMANENT])
        code, state = self.supervisor(first, [][0:0]).run()
        self.assertEqual(code, EXIT_PERMANENT)
        self.assertEqual(state["phase"], "failed_permanent")
        with self.assertRaisesRegex(SupervisorError, "command identity drift"):
            FullPublicationSupervisor(
                state_path=self.state_path,
                invoker=SequenceInvoker([]),
                command_identity={"different": True},
                backoff_s=(0,),
                sleep_fn=lambda _: None,
            ).run()

    def test_invalid_success_payload_fails_closed_without_persisting_payload(self) -> None:
        secret = "https://seafile.invalid/u/d/TopSecretCapability"
        invoker = SequenceInvoker(
            [(0, {"artifact_kind": "wrong", "message": secret})]
        )
        code, state = self.supervisor(invoker, []).run()
        self.assertEqual(code, EXIT_PERMANENT)
        self.assertEqual(state["phase"], "failed_permanent")
        rendered = self.state_path.read_text(encoding="utf-8")
        self.assertNotIn(secret, rendered)

    def test_unexpected_process_failures_are_bounded_and_restart_safe(self) -> None:
        invoker = SequenceInvoker(
            [InvocationUnavailable("down"), InvocationUnavailable("down")]
        )
        sleeps: list[float] = []
        code, state = self.supervisor(
            invoker, sleeps, max_unexpected_retries=1
        ).run()
        self.assertEqual(code, EXIT_PERMANENT)
        self.assertEqual(state["unexpected_streak"], 2)
        self.assertEqual(sleeps, [1.0])

    def test_default_budget_stops_exceptions_and_unknown_exits_without_sleep(self) -> None:
        for failure in (
            InvocationUnavailable("entrypoint unavailable"),
            UnexpectedProcessExit("unexpected exit code 17"),
        ):
            with self.subTest(failure=type(failure).__name__):
                launches: list[str] = []

                self.state_path.unlink(missing_ok=True)
                def invoker(phase: str) -> tuple[int, dict[str, object]]:
                    launches.append(phase)
                    raise failure

                sleeps: list[float] = []
                code, state = self.supervisor(invoker, sleeps).run()

                self.assertEqual(code, EXIT_PERMANENT)
                self.assertEqual(state["phase"], "failed_permanent")
                self.assertEqual(launches, ["run"])
                self.assertEqual(sleeps, [])

    def test_cli_default_budget_stops_unknown_exit_after_one_launch(self) -> None:
        launches: list[str] = []

        class UnexpectedExitInvoker:
            def __init__(self, **_: object) -> None:
                pass

            @property
            def command_identity(self) -> dict[str, object]:
                return {"entrypoint_sha256": "a" * 64, "args": []}

            def __call__(self, phase: str) -> tuple[int, dict[str, object]]:
                launches.append(phase)
                raise UnexpectedProcessExit("unexpected exit code 17")

        with (
            mock.patch.object(
                supervisor_module,
                "SubprocessEntrypointInvoker",
                UnexpectedExitInvoker,
            ),
            mock.patch.object(FullPublicationSupervisor, "_delay") as delay,
        ):
            code = supervisor_module.main(["--state-path", str(self.state_path)])

        self.assertEqual(code, EXIT_PERMANENT)
        self.assertEqual(launches, ["run"])
        delay.assert_not_called()
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        self.assertEqual(state["phase"], "failed_permanent")

    def test_completed_state_is_idempotent(self) -> None:
        first = SequenceInvoker([EXIT_COMPLETE] * 4)
        code, _ = self.supervisor(first, []).run()
        self.assertEqual(code, EXIT_COMPLETE)
        second = SequenceInvoker([])
        code, state = self.supervisor(second, []).run()
        self.assertEqual(code, EXIT_COMPLETE)
        self.assertEqual(state["phase"], "complete")
        self.assertEqual(second.phases, [])

    def test_subprocess_invoker_rejects_bare_capability_token_in_output(self) -> None:
        entrypoint = Path(self.temp.name) / "entrypoint.py"
        entrypoint.write_text("# fixture\n", encoding="utf-8")
        token = "BareReadCapabilityToken99"

        def fake_process(*_: object, **__: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=EXIT_PERMANENT,
                stdout=json.dumps({"message": token}),
                stderr="",
            )

        invoker = SubprocessEntrypointInvoker(
            entrypoint=entrypoint,
            entrypoint_args=(*FROZEN_ENTRYPOINT_ARGS, "--run-root", "runs/full"),
            python_executable=sys.executable,
            run_process=fake_process,
            environment={
                "VAST_SEAFILE_UPLOAD_LINK": "https://seafile.example/u/d/UploadToken99",
                "VAST_SEAFILE_READ_LINK": f"https://seafile.example/d/{token}",
            },
        )
        with self.assertRaisesRegex(SupervisorError, "capability secret"):
            invoker("run")

    def test_subprocess_invoker_redacts_capabilities_loaded_from_link_file(self) -> None:
        root = Path(self.temp.name)
        entrypoint = root / "entrypoint.py"
        entrypoint.write_text("# fixture\n", encoding="utf-8")
        token = "FileReadCapabilityToken99"
        (root / "seafile.txt").write_text(
            "download link - https://seafile.example/d/" + token + "\n"
            "upload link - https://seafile.example/u/d/FileUploadCapabilityToken99\n",
            encoding="utf-8",
        )

        def fake_process(*_: object, **__: object) -> SimpleNamespace:
            return SimpleNamespace(
                returncode=EXIT_PERMANENT,
                stdout=json.dumps({"message": token}),
                stderr="",
            )

        invoker = SubprocessEntrypointInvoker(
            entrypoint=entrypoint,
            entrypoint_args=(
                *FROZEN_ENTRYPOINT_ARGS,
                "--project-root", str(root),
                "--cloud-links-file", "seafile.txt",
                "--run-root", "runs/full",
            ),
            python_executable=sys.executable,
            run_process=fake_process,
            environment={},
        )
        with self.assertRaisesRegex(SupervisorError, "capability secret"):
            invoker("run")

    def test_subprocess_invoker_requires_exact_frozen_contract_arguments(self) -> None:
        entrypoint = Path(self.temp.name) / "entrypoint.py"
        entrypoint.write_text("# fixture\n", encoding="utf-8")
        for arguments in (
            (),
            (
                "--expected-matrix-sha256",
                "0" * 64,
                "--expected-policy-contract-sha256",
                FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256,
            ),
            (
                "--expected-matrix-sha256",
                FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
                "--expected-policy-contract-sha256",
                "0" * 64,
            ),
        ):
            with self.subTest(arguments=arguments), self.assertRaisesRegex(
                SupervisorError, "exact frozen"
            ):
                SubprocessEntrypointInvoker(
                    entrypoint=entrypoint,
                    entrypoint_args=arguments,
                    python_executable=sys.executable,
                    environment={},
                )

    def test_command_identity_explicitly_binds_frozen_contract(self) -> None:
        entrypoint = Path(self.temp.name) / "entrypoint.py"
        entrypoint.write_text("# fixture\n", encoding="utf-8")
        invoker = SubprocessEntrypointInvoker(
            entrypoint=entrypoint,
            entrypoint_args=FROZEN_ENTRYPOINT_ARGS,
            python_executable=sys.executable,
            environment={},
        )
        self.assertEqual(
            invoker.command_identity["frozen_publication_contract"],
            {
                "matrix_schema_version": (
                    FROZEN_FULL_PUBLICATION_MATRIX_SCHEMA_VERSION
                ),
                "matrix_sha256": FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
                "policy_contract_sha256": (
                    FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256
                ),
            },
        )

    def test_subprocess_invoker_rejects_post_construction_source_replacement(self) -> None:
        root = Path(self.temp.name)
        entrypoint = root / "entrypoint.py"
        marker = root / "entrypoint-marker.txt"
        original = (
            "from pathlib import Path\n"
            f"Path({str(marker)!r}).write_text('original', encoding='utf-8')\n"
        )
        replacement = original.replace("original", "replaced")
        self.assertEqual(len(original.encode()), len(replacement.encode()))
        entrypoint.write_text(original, encoding="utf-8")
        invoker = SubprocessEntrypointInvoker(
            entrypoint=entrypoint,
            entrypoint_args=FROZEN_ENTRYPOINT_ARGS,
            python_executable=sys.executable,
            environment={},
        )
        candidate = entrypoint.with_suffix(".replacement")
        candidate.write_text(replacement, encoding="utf-8")
        os.replace(candidate, entrypoint)
        with self.assertRaisesRegex(
            UnexpectedProcessExit, "unexpected exit code"
        ):
            invoker("run")
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
