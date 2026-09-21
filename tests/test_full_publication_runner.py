from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
import full_publication_runner as runner_module  # noqa: E402
from full_publication_runner import (  # noqa: E402
    CallbackDecision,
    CloudTransactionReceipt,
    ExitCode,
    FullPublicationRunner,
    PermanentRunError,
    RunnerCallbacks,
    TransientRunError,
)


class SimulatedProcessCrash(BaseException):
    pass


def canonical_sha256(value) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def acceptance_manifest_sha256(pair_id: str) -> str:
    return hashlib.sha256(f"acceptance.json:{pair_id}".encode("utf-8")).hexdigest()


def cloud_receipt_details(context, acceptance_details) -> dict:
    pair_id = context.pair["pair_id"]
    return {
        "state": "local_pruned",
        "matrix_sha256": context.run.matrix_identity["sha256"],
        "run_id": context.run.run_identity["sha256"],
        "pair_sequence": context.sequence,
        "pair_id": pair_id,
        "acceptance_sha256": acceptance_details["acceptance_manifest_sha256"],
        "archive_remote_name": f"pair-{context.sequence}.tar.zst",
        "archive_sha256": hashlib.sha256(
            f"archive:{context.sequence}:{pair_id}".encode("utf-8")
        ).hexdigest(),
        "archive_size_bytes": 1000 + context.sequence,
        "receipt_remote_name": f"pair-{context.sequence}.receipt.json",
        "receipt_sha256": hashlib.sha256(
            f"receipt:{context.sequence}:{pair_id}".encode("utf-8")
        ).hexdigest(),
        "receipt_size_bytes": 2000 + context.sequence,
        "local_archive_path": str(
            context.run.run_root / "cloud_spool" / f"pair-{context.sequence}.tar.zst"
        ),
        "local_receipt_path": str(
            context.run.run_root
            / "cloud_receipts"
            / f"pair-{context.sequence}.receipt.json"
        ),
        "ledger_entry_sha256": hashlib.sha256(
            f"ledger:{context.sequence}:{pair_id}".encode("utf-8")
        ).hexdigest(),
    }


def load_config() -> dict:
    with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
        return yaml.safe_load(source)


def small_matrix_factory(config: dict) -> dict:
    del config
    pairs = []
    for sequence in range(3):
        pair_id = f"pair-{sequence}"
        pairs.append(
            {
                "pair_id": pair_id,
                "system": "test-system",
                "codec": "h264",
                "dataset": "test-dataset",
                "policy": "test-policy",
                "deadline_ms": 100.0,
                "repeat": sequence + 1,
                "arms": [
                    {
                        "arm_id": f"{pair_id}-baseline",
                        "arm_position": 1,
                        "scenario": "checkpoint_independent_processes_baseline",
                    },
                    {
                        "arm_id": f"{pair_id}-shared",
                        "arm_position": 2,
                        "scenario": "checkpoint_video_dag_shared",
                    },
                ],
            }
        )
    return {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_matrix",
        "publication_scope": "test-scope",
        "seed": 1,
        "expected_pairs": 3,
        "expected_arms": 6,
        "pairs": pairs,
    }


class CallbackHarness:
    def __init__(self) -> None:
        self.events: list[tuple] = []
        self.arm_attempts: dict[str, int] = {}
        self.fail_arm_once: str | None = None
        self.crash_arm_once: str | None = None
        self.cloud_transient_once: str | None = None
        self.cloud_crash_once: str | None = None
        self.verify_cloud_unverified: str | None = None
        self.reject_pair: str | None = None
        self.preflight_error: Exception | None = None

    def preflight(self, context):
        self.events.append(("preflight", context.next_sequence, context.run_root))
        if self.preflight_error is not None:
            error = self.preflight_error
            self.preflight_error = None
            raise error
        return CallbackDecision.passed({"stand": "test"})

    def execute_arm(self, context):
        arm_id = context.arm["arm_id"]
        self.events.append(("arm", context.sequence, arm_id, context.attempt))
        self.arm_attempts[arm_id] = self.arm_attempts.get(arm_id, 0) + 1
        if self.fail_arm_once == arm_id and self.arm_attempts[arm_id] == 1:
            raise TransientRunError("temporary arm failure")
        if self.crash_arm_once == arm_id:
            self.crash_arm_once = None
            raise SimulatedProcessCrash("crash inside arm transaction")
        return {"arm_id": arm_id, "accepted_input": True}

    def accept_pair(self, context, arm_results):
        self.events.append(("accept", context.sequence, len(arm_results)))
        if self.reject_pair == context.pair["pair_id"]:
            return CallbackDecision.rejected("scientific acceptance failed")
        return CallbackDecision.passed(
            {
                "pair_id": context.pair["pair_id"],
                "arm_ids": [result["arm_id"] for result in arm_results],
                "acceptance_manifest_sha256": acceptance_manifest_sha256(
                    context.pair["pair_id"]
                ),
            }
        )

    def cloud_transaction(self, context, acceptance):
        self.events.append(("cloud", context.sequence, acceptance.accepted))
        pair_id = context.pair["pair_id"]
        if self.cloud_crash_once == pair_id:
            self.cloud_crash_once = None
            raise SimulatedProcessCrash("crash after cloud commit and local prune")
        if self.cloud_transient_once == pair_id:
            self.cloud_transient_once = None
            raise TransientRunError("temporary cloud failure")
        return CloudTransactionReceipt.verified_receipt(
            cloud_receipt_details(context, acceptance.details)
        )

    def verify_cloud(self, context, receipt):
        self.events.append(("verify_cloud", context.sequence, receipt.verified))
        if self.verify_cloud_unverified == context.pair["pair_id"]:
            return CloudTransactionReceipt.unverified(
                "remote receipt is temporarily unavailable",
                details=dict(receipt.details),
                retryable=True,
            )
        return CloudTransactionReceipt.verified_receipt(dict(receipt.details))

    def callbacks(self) -> RunnerCallbacks:
        return RunnerCallbacks(
            preflight=self.preflight,
            execute_arm=self.execute_arm,
            accept_pair=self.accept_pair,
            cloud_transaction=self.cloud_transaction,
            verify_cloud=self.verify_cloud,
        )


class FullPublicationRunnerTests(unittest.TestCase):
    def make_runner(
        self,
        root: Path,
        harness: CallbackHarness | None = None,
        *,
        identity_inputs: dict | None = None,
        callbacks: RunnerCallbacks | None = None,
        immutable_artifact_physical_fault=None,
    ) -> FullPublicationRunner:
        selected_callbacks = callbacks
        if selected_callbacks is None and harness is not None:
            selected_callbacks = harness.callbacks()
        return FullPublicationRunner(
            root,
            config={"test": True},
            identity_inputs=identity_inputs or {"source_sha256": "source-a"},
            callbacks=selected_callbacks,
            matrix_builder=small_matrix_factory,
            immutable_artifact_physical_fault=(
                immutable_artifact_physical_fault
            ),
        )

    def test_plan_uses_the_frozen_2800_pair_publication_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = FullPublicationRunner(
                Path(tmp),
                config=load_config(),
                identity_inputs={"source_sha256": "source-a"},
            )

            plan = runner.plan()

        self.assertEqual(plan["expected_pairs"], 2800)
        self.assertEqual(plan["expected_arms"], 5600)
        self.assertEqual(
            plan["matrix_identity"]["sha256"],
            "a1115ea9fa5f496f45d75636b8376366a48413cdc4c9787cb7ca4baac04b230e",
        )
        self.assertEqual(
            [item["sequence"] for item in plan["pairs"]],
            list(range(2800)),
        )

    def test_complete_run_executes_each_pair_in_sequence_and_finalizes(self) -> None:
        harness = CallbackHarness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, harness)

            result = runner.run()
            status = runner.status()
            verification = runner.verify()
            finalization = runner.finalize()
            second_finalization = runner.finalize()

            checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
            manifest = json.loads((root / "run_manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(result.exit_code, ExitCode.COMPLETE)
        self.assertEqual(result.status, "complete")
        self.assertEqual(harness.events[0], ("preflight", 0, root))
        self.assertEqual(status["completed_pairs"], 3)
        self.assertEqual(status["completed_arms"], 6)
        self.assertTrue(verification["passed"])
        self.assertTrue(finalization["verified"])
        self.assertEqual(finalization, second_finalization)
        self.assertEqual(finalization["remote_verified_pairs"], 3)
        self.assertRegex(finalization["remote_verification_sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(checkpoint["verified_prefix_length"], 3)
        self.assertEqual(
            [record["sequence"] for record in checkpoint["verified_pairs"]],
            [0, 1, 2],
        )
        self.assertEqual(manifest["matrix"]["expected_pairs"], 3)
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "accept"],
            [0, 1, 2],
        )
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "cloud"],
            [0, 1, 2],
        )
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "verify_cloud"],
            [0, 1, 2],
        )

    def test_run_manifest_recovers_each_physical_crash_window(self) -> None:
        for crash_step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(crash_step=crash_step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                harness = CallbackHarness()
                faulted = False

                def fault(step: str, path: Path) -> None:
                    nonlocal faulted
                    if path.name == "run_manifest.json" and step == crash_step:
                        faulted = True
                        raise SimulatedProcessCrash(step)

                with self.assertRaises(SimulatedProcessCrash):
                    self.make_runner(
                        root,
                        harness,
                        immutable_artifact_physical_fault=fault,
                    ).run()
                manifest = root / "run_manifest.json"
                published_inode = manifest.stat().st_ino if manifest.exists() else None
                resumed = self.make_runner(root, harness).run()
                self.assertTrue(faulted)
                self.assertEqual(resumed.exit_code, ExitCode.COMPLETE)
                if published_inode is not None:
                    self.assertEqual(manifest.stat().st_ino, published_inode)

    def test_finalization_recovers_each_physical_crash_window(self) -> None:
        for crash_step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(crash_step=crash_step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                harness = CallbackHarness()
                self.assertEqual(
                    self.make_runner(root, harness).run().exit_code,
                    ExitCode.COMPLETE,
                )
                faulted = False

                def fault(step: str, path: Path) -> None:
                    nonlocal faulted
                    if path.name == "finalization.json" and step == crash_step:
                        faulted = True
                        raise SimulatedProcessCrash(step)

                with self.assertRaises(SimulatedProcessCrash):
                    self.make_runner(
                        root,
                        harness,
                        immutable_artifact_physical_fault=fault,
                    ).finalize()
                finalization = root / "finalization.json"
                published_inode = (
                    finalization.stat().st_ino if finalization.exists() else None
                )
                resumed = self.make_runner(root, harness).finalize()
                self.assertTrue(faulted)
                self.assertTrue(resumed["verified"])
                if published_inode is not None:
                    self.assertEqual(finalization.stat().st_ino, published_inode)

    def test_run_manifest_rejects_racing_foreign_and_rebound_final(self) -> None:
        for attack_step in (
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(attack_step=attack_step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                manifest = root / "run_manifest.json"

                def attack(step: str, path: Path) -> None:
                    if path.name != manifest.name or step != attack_step:
                        return
                    if path.exists():
                        path.unlink()
                    path.write_bytes(b"foreign-run-manifest\n")
                    path.chmod(0o600)

                result = self.make_runner(
                    root,
                    CallbackHarness(),
                    immutable_artifact_physical_fault=attack,
                ).run()
                self.assertEqual(result.exit_code, ExitCode.PERMANENT)
                foreign_inode = manifest.stat().st_ino
                foreign_payload = manifest.read_bytes()
                retry = self.make_runner(root, CallbackHarness()).run()
                self.assertEqual(retry.exit_code, ExitCode.PERMANENT)
                self.assertEqual(manifest.stat().st_ino, foreign_inode)
                self.assertEqual(manifest.read_bytes(), foreign_payload)

    def test_finalization_rejects_racing_foreign_and_rebound_final(self) -> None:
        for attack_step in (
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(attack_step=attack_step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                harness = CallbackHarness()
                runner = self.make_runner(root, harness)
                self.assertEqual(runner.run().exit_code, ExitCode.COMPLETE)
                finalization = root / "finalization.json"

                def attack(step: str, path: Path) -> None:
                    if path.name != finalization.name or step != attack_step:
                        return
                    if path.exists():
                        path.unlink()
                    path.write_bytes(b"foreign-finalization\n")
                    path.chmod(0o600)

                with self.assertRaises(ContractError):
                    self.make_runner(
                        root,
                        harness,
                        immutable_artifact_physical_fault=attack,
                    ).finalize()
                foreign_inode = finalization.stat().st_ino
                foreign_payload = finalization.read_bytes()
                with self.assertRaises(ContractError):
                    self.make_runner(root, harness).finalize()
                self.assertEqual(finalization.stat().st_ino, foreign_inode)
                self.assertEqual(finalization.read_bytes(), foreign_payload)

    def test_transient_failure_resumes_same_attempt_without_rerunning_committed_arm(self) -> None:
        harness = CallbackHarness()
        harness.fail_arm_once = "pair-1-shared"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.make_runner(root, harness).run()
            first_checkpoint = json.loads(
                (root / "checkpoint.json").read_text(encoding="utf-8")
            )
            second = self.make_runner(root, harness).run()

        self.assertEqual(first.exit_code, ExitCode.TRANSIENT)
        self.assertEqual(first.completed_pairs, 1)
        self.assertEqual(first_checkpoint["verified_prefix_length"], 1)
        self.assertEqual(first_checkpoint["inflight"]["phase"], "executing")
        self.assertEqual(first_checkpoint["inflight"]["sequence"], 1)
        self.assertEqual(first_checkpoint["inflight"]["attempt"], 1)
        self.assertEqual(
            [item["state"] for item in first_checkpoint["inflight"]["arm_states"]],
            ["committed", "executing"],
        )
        self.assertEqual(second.exit_code, ExitCode.COMPLETE)
        self.assertEqual(harness.arm_attempts["pair-1-baseline"], 1)
        self.assertEqual(harness.arm_attempts["pair-1-shared"], 2)
        shared_attempts = [
            event[3]
            for event in harness.events
            if event[:3] == ("arm", 1, "pair-1-shared")
        ]
        self.assertEqual(shared_attempts, [1, 1])

    def test_cloud_failure_resumes_from_durable_acceptance_without_rerunning_arms(self) -> None:
        harness = CallbackHarness()
        harness.cloud_transient_once = "pair-1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.make_runner(root, harness).run()
            checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
            second = self.make_runner(root, harness).run()

        self.assertEqual(first.exit_code, ExitCode.TRANSIENT)
        self.assertEqual(checkpoint["verified_prefix_length"], 1)
        self.assertEqual(checkpoint["inflight"]["phase"], "accepted")
        self.assertEqual(
            checkpoint["inflight"]["acceptance_sha256"],
            canonical_sha256(checkpoint["inflight"]["acceptance"]),
        )
        self.assertEqual(second.exit_code, ExitCode.COMPLETE)
        self.assertEqual(harness.arm_attempts["pair-1-baseline"], 1)
        self.assertEqual(harness.arm_attempts["pair-1-shared"], 1)
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "accept"].count(1),
            1,
        )
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "cloud"].count(1),
            2,
        )

    def test_process_crash_inside_arm_resumes_same_attempt_and_skips_committed_prefix(self) -> None:
        harness = CallbackHarness()
        harness.crash_arm_once = "pair-1-shared"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(SimulatedProcessCrash, "arm transaction"):
                self.make_runner(root, harness).run()
            checkpoint = json.loads(
                (root / "checkpoint.json").read_text(encoding="utf-8")
            )
            resumed = self.make_runner(root, harness).run()

        self.assertEqual(checkpoint["schema_version"], 2)
        self.assertEqual(checkpoint["inflight"]["attempt"], 1)
        self.assertEqual(
            [item["state"] for item in checkpoint["inflight"]["arm_states"]],
            ["committed", "executing"],
        )
        self.assertEqual(resumed.exit_code, ExitCode.COMPLETE)
        self.assertEqual(harness.arm_attempts["pair-1-baseline"], 1)
        self.assertEqual(harness.arm_attempts["pair-1-shared"], 2)
        self.assertEqual(
            [
                event[3]
                for event in harness.events
                if event[:3] == ("arm", 1, "pair-1-shared")
            ],
            [1, 1],
        )

    def test_process_crash_inside_cloud_transaction_resumes_from_acceptance(self) -> None:
        harness = CallbackHarness()
        harness.cloud_crash_once = "pair-1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(SimulatedProcessCrash, "local prune"):
                self.make_runner(root, harness).run()
            checkpoint = json.loads((root / "checkpoint.json").read_text(encoding="utf-8"))
            resumed = self.make_runner(root, harness).run()

        self.assertEqual(checkpoint["verified_prefix_length"], 1)
        self.assertEqual(checkpoint["inflight"]["phase"], "accepted")
        self.assertEqual(resumed.exit_code, ExitCode.COMPLETE)
        self.assertEqual(harness.arm_attempts["pair-1-baseline"], 1)
        self.assertEqual(harness.arm_attempts["pair-1-shared"], 1)
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "cloud"].count(1),
            2,
        )

    def test_atomic_checkpoint_replace_retries_windows_sharing_races(self) -> None:
        sharing_error = PermissionError(5, "sharing race")
        sharing_error.winerror = 5
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "checkpoint.json"
            real_replace = runner_module.os.replace
            real_os_name = runner_module.os.name
            attempts = 0

            def flaky_replace(source, destination):
                nonlocal attempts
                attempts += 1
                if attempts == 1:
                    raise sharing_error
                return real_replace(source, destination)

            with (
                mock.patch.object(runner_module.os, "replace", side_effect=flaky_replace),
                mock.patch.object(runner_module.time, "sleep") as sleep,
                mock.patch.object(
                    runner_module,
                    "_is_windows_runtime",
                    return_value=True,
                ),
            ):
                runner_module._atomic_write_json(target, {"state": "accepted"})

            self.assertEqual(runner_module.os.name, real_os_name)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"state": "accepted"})
            self.assertEqual(attempts, 2)
            sleep.assert_called_once()

    def test_atomic_checkpoint_replace_does_not_mask_permanent_or_exhausted_errors(self) -> None:
        cases = ((87, 1, 0), (32, 6, 5))
        for winerror, expected_attempts, expected_sleeps in cases:
            with self.subTest(winerror=winerror), tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp) / "checkpoint.json"
                real_os_name = runner_module.os.name
                replace_error = PermissionError(winerror, "replace failed")
                replace_error.winerror = winerror
                with (
                    mock.patch.object(
                        runner_module.os, "replace", side_effect=replace_error
                    ) as replace,
                    mock.patch.object(runner_module.time, "sleep") as sleep,
                    mock.patch.object(
                        runner_module,
                        "_is_windows_runtime",
                        return_value=True,
                    ),
                    self.assertRaises(PermissionError),
                ):
                    runner_module._atomic_write_json(target, {"state": "accepted"})

                self.assertEqual(runner_module.os.name, real_os_name)
                self.assertEqual(replace.call_count, expected_attempts)
                self.assertEqual(sleep.call_count, expected_sleeps)
                self.assertFalse(target.exists())
                self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_callback_decisions_require_exact_bools_strings_and_json_objects(self) -> None:
        invalid_decisions = [
            CallbackDecision(accepted=1),  # type: ignore[arg-type]
            CallbackDecision(accepted=True, retryable=0),  # type: ignore[arg-type]
            CallbackDecision(accepted=True, reason=7),  # type: ignore[arg-type]
            CallbackDecision(accepted=True, details=[]),  # type: ignore[arg-type]
            CallbackDecision.passed([]),  # type: ignore[arg-type]
            CallbackDecision(accepted=True, details={"tuple": (1, 2)}),
            CallbackDecision(accepted=True, details={"nan": float("nan")}),
        ]
        for index, decision in enumerate(invalid_decisions):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                harness = CallbackHarness()
                callbacks = replace(
                    harness.callbacks(), preflight=lambda _context, value=decision: value
                )
                result = self.make_runner(Path(tmp), callbacks=callbacks).run()

                self.assertEqual(result.exit_code, ExitCode.PERMANENT)
                self.assertFalse(any(event[0] == "arm" for event in harness.events))

    def test_acceptance_requires_manifest_hash_before_cloud(self) -> None:
        harness = CallbackHarness()

        def invalid_acceptance(context, arm_results):
            del context, arm_results
            return CallbackDecision.passed({"pair_id": "pair-0"})

        callbacks = replace(harness.callbacks(), accept_pair=invalid_acceptance)
        with tempfile.TemporaryDirectory() as tmp:
            result = self.make_runner(Path(tmp), callbacks=callbacks).run()

        self.assertEqual(result.exit_code, ExitCode.PERMANENT)
        self.assertIn("acceptance_manifest_sha256", result.message)
        self.assertFalse(any(event[0] == "cloud" for event in harness.events))

    def test_verified_cloud_receipt_has_strict_envelope_and_identity_schema(self) -> None:
        def set_value(field, value):
            return lambda details: details.__setitem__(field, value)

        def remove_value(field):
            return lambda details: details.pop(field)

        schema_mutations = [
            ("state", set_value("state", "receipt_verified")),
            ("matrix", set_value("matrix_sha256", "0" * 64)),
            ("run", set_value("run_id", "0" * 64)),
            ("sequence_type", set_value("pair_sequence", True)),
            ("pair", set_value("pair_id", "other-pair")),
            ("acceptance", set_value("acceptance_sha256", "0" * 64)),
            ("archive_hash", set_value("archive_sha256", "A" * 64)),
            ("archive_size", set_value("archive_size_bytes", 0)),
            ("receipt_size_type", set_value("receipt_size_bytes", True)),
            ("ledger_missing", remove_value("ledger_entry_sha256")),
            ("extra_field", set_value("unexpected", "field")),
        ]

        for label, mutate in schema_mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                harness = CallbackHarness()

                def invalid_cloud(context, acceptance, mutation=mutate):
                    details = cloud_receipt_details(context, acceptance.details)
                    mutation(details)
                    return CloudTransactionReceipt.verified_receipt(details)

                callbacks = replace(
                    harness.callbacks(), cloud_transaction=invalid_cloud
                )
                result = self.make_runner(Path(tmp), callbacks=callbacks).run()

                self.assertEqual(result.exit_code, ExitCode.PERMANENT)

        invalid_envelopes = [
            lambda context, acceptance: CloudTransactionReceipt(
                verified=1,  # type: ignore[arg-type]
                details=cloud_receipt_details(context, acceptance.details),
                retryable=False,
            ),
            lambda context, acceptance: CloudTransactionReceipt(
                verified=True,
                details=cloud_receipt_details(context, acceptance.details),
                reason=3,  # type: ignore[arg-type]
                retryable=False,
            ),
            lambda _context, _acceptance: CloudTransactionReceipt(
                verified=True,
                details={"not_json": {1, 2}},
                retryable=False,
            ),
            lambda _context, _acceptance: CloudTransactionReceipt(
                verified=True,
                details={},
                retryable=0,  # type: ignore[arg-type]
            ),
            lambda _context, _acceptance: CloudTransactionReceipt.unverified(
                "unverified with non-object details",
                details=[],  # type: ignore[arg-type]
                retryable=True,
            ),
        ]
        for index, callback in enumerate(invalid_envelopes):
            with self.subTest(envelope=index), tempfile.TemporaryDirectory() as tmp:
                harness = CallbackHarness()
                callbacks = replace(
                    harness.callbacks(), cloud_transaction=callback
                )
                result = self.make_runner(Path(tmp), callbacks=callbacks).run()

                self.assertEqual(result.exit_code, ExitCode.PERMANENT)

    def test_pair_rejection_is_permanent_and_never_reaches_cloud(self) -> None:
        harness = CallbackHarness()
        harness.reject_pair = "pair-0"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.make_runner(root, harness).run()
            second = self.make_runner(root, harness).run()

        self.assertEqual(first.exit_code, ExitCode.PERMANENT)
        self.assertEqual(first.completed_pairs, 0)
        self.assertEqual(second.exit_code, ExitCode.PERMANENT)
        self.assertEqual(harness.arm_attempts["pair-0-baseline"], 1)
        self.assertEqual(harness.arm_attempts["pair-0-shared"], 1)
        self.assertFalse(any(event[0] == "cloud" for event in harness.events))

    def test_preflight_classifies_transient_and_untyped_failures(self) -> None:
        with tempfile.TemporaryDirectory() as first_tmp, tempfile.TemporaryDirectory() as second_tmp:
            transient_harness = CallbackHarness()
            transient_harness.preflight_error = TransientRunError("stand busy")
            transient = self.make_runner(Path(first_tmp), transient_harness).run()

            permanent_harness = CallbackHarness()
            permanent_harness.preflight_error = RuntimeError("broken contract")
            permanent = self.make_runner(Path(second_tmp), permanent_harness).run()

        self.assertEqual(transient.exit_code, ExitCode.TRANSIENT)
        self.assertEqual(permanent.exit_code, ExitCode.PERMANENT)

    def test_each_callback_boundary_receives_fresh_immutable_snapshot(self) -> None:
        events: list[tuple[str, int, str]] = []

        def preflight(context):
            context.matrix_identity["sha256"] = "mutated"
            context.run_identity["sha256"] = "mutated"
            return CallbackDecision.passed({"preflight": True})

        def execute_arm(context):
            pair_id = context.pair_context.pair["pair_id"]
            arm_id = context.arm["arm_id"]
            self.assertEqual(pair_id, f"pair-{context.sequence}")
            self.assertNotEqual(context.pair_context.run.matrix_identity["sha256"], "mutated")
            events.append(("arm", context.sequence, arm_id))
            context.pair_context.pair["pair_id"] = "mutated"
            context.pair_context.run.matrix_identity["sha256"] = "mutated"
            context.arm["arm_id"] = "mutated"
            return {"arm_id": arm_id}

        def accept_pair(context, arm_results):
            pair_id = context.pair["pair_id"]
            self.assertEqual(pair_id, f"pair-{context.sequence}")
            self.assertEqual(
                [result["arm_id"] for result in arm_results],
                [f"{pair_id}-baseline", f"{pair_id}-shared"],
            )
            details = {
                "pair_id": pair_id,
                "arm_ids": [result["arm_id"] for result in arm_results],
                "acceptance_manifest_sha256": acceptance_manifest_sha256(pair_id),
            }
            events.append(("accept", context.sequence, pair_id))
            context.pair["pair_id"] = "mutated"
            return CallbackDecision.passed(details)

        def cloud_transaction(context, acceptance):
            pair_id = context.pair["pair_id"]
            self.assertEqual(pair_id, f"pair-{context.sequence}")
            self.assertEqual(acceptance.details["pair_id"], pair_id)
            details = cloud_receipt_details(context, acceptance.details)
            events.append(("cloud", context.sequence, pair_id))
            context.pair["pair_id"] = "mutated"
            acceptance.details["pair_id"] = "mutated"
            return CloudTransactionReceipt.verified_receipt(details)

        def verify_cloud(context, receipt):
            pair_id = context.pair["pair_id"]
            self.assertEqual(pair_id, f"pair-{context.sequence}")
            self.assertEqual(receipt.details["pair_id"], pair_id)
            details = dict(receipt.details)
            events.append(("verify", context.sequence, pair_id))
            context.pair["pair_id"] = "mutated"
            receipt.details["pair_id"] = "mutated"
            return CloudTransactionReceipt.verified_receipt(details)

        callbacks = RunnerCallbacks(
            preflight=preflight,
            execute_arm=execute_arm,
            accept_pair=accept_pair,
            cloud_transaction=cloud_transaction,
            verify_cloud=verify_cloud,
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, callbacks=callbacks)
            result = runner.run()
            finalization = runner.finalize()
            checkpoint = json.loads(
                (root / "checkpoint.json").read_text(encoding="utf-8")
            )

        self.assertEqual(result.exit_code, ExitCode.COMPLETE)
        self.assertTrue(finalization["verified"])
        self.assertEqual(
            [record["pair_id"] for record in checkpoint["verified_pairs"]],
            ["pair-0", "pair-1", "pair-2"],
        )
        self.assertEqual(
            [record["acceptance"]["pair_id"] for record in checkpoint["verified_pairs"]],
            ["pair-0", "pair-1", "pair-2"],
        )
        self.assertEqual(
            [event[1] for event in events if event[0] == "verify"], [0, 1, 2]
        )

    def test_identity_drift_aborts_before_any_callback(self) -> None:
        first_harness = CallbackHarness()
        second_harness = CallbackHarness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_harness.fail_arm_once = "pair-0-baseline"
            first = self.make_runner(
                root,
                first_harness,
                identity_inputs={"source_sha256": "source-a"},
            ).run()
            drifted = self.make_runner(
                root,
                second_harness,
                identity_inputs={"source_sha256": "source-b"},
            ).run()

        self.assertEqual(first.exit_code, ExitCode.TRANSIENT)
        self.assertEqual(drifted.exit_code, ExitCode.PERMANENT)
        self.assertIn("identity drift", drifted.message)
        self.assertEqual(second_harness.events, [])

    def test_noncontiguous_or_tampered_verified_prefix_fails_closed(self) -> None:
        harness = CallbackHarness()
        harness.cloud_transient_once = "pair-1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.make_runner(root, harness).run()
            self.assertEqual(first.completed_pairs, 1)
            checkpoint_path = root / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["verified_pairs"][0]["sequence"] = 2
            checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")

            with self.assertRaisesRegex(ContractError, "contiguous verified prefix"):
                self.make_runner(root).verify()
            resumed = self.make_runner(root, CallbackHarness()).run()

        self.assertEqual(resumed.exit_code, ExitCode.PERMANENT)

    def test_tampered_durable_arm_result_fails_closed_before_callback(self) -> None:
        harness = CallbackHarness()
        harness.fail_arm_once = "pair-1-shared"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.make_runner(root, harness).run()
            self.assertEqual(first.exit_code, ExitCode.TRANSIENT)
            checkpoint_path = root / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["inflight"]["arm_states"][0]["result"]["arm_id"] = "tampered"
            checkpoint_path.write_text(json.dumps(checkpoint), encoding="utf-8")
            fresh_harness = CallbackHarness()
            resumed = self.make_runner(root, fresh_harness).run()

        self.assertEqual(resumed.exit_code, ExitCode.PERMANENT)
        self.assertIn("arm result drift", resumed.message)
        self.assertEqual(fresh_harness.events, [])

    def test_run_root_lock_rejects_concurrent_run_and_status(self) -> None:
        entered_arm = threading.Event()
        release_arm = threading.Event()
        first_harness = CallbackHarness()
        second_harness = CallbackHarness()
        original_execute = first_harness.execute_arm

        def blocking_execute(context):
            if context.sequence == 0 and context.arm_index == 0:
                entered_arm.set()
                if not release_arm.wait(timeout=10):
                    raise RuntimeError("test did not release blocked arm")
            return original_execute(context)

        first_callbacks = replace(
            first_harness.callbacks(), execute_arm=blocking_execute
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first_runner = self.make_runner(root, callbacks=first_callbacks)
            first_result: dict[str, object] = {}

            def run_first() -> None:
                first_result["value"] = first_runner.run()

            worker = threading.Thread(target=run_first, daemon=True)
            worker.start()
            try:
                self.assertTrue(entered_arm.wait(timeout=5))
                concurrent = self.make_runner(root, second_harness).run()
                with self.assertRaises(TransientRunError):
                    self.make_runner(root).status()
            finally:
                release_arm.set()
                worker.join(timeout=10)

        self.assertFalse(worker.is_alive())
        self.assertEqual(concurrent.exit_code, ExitCode.TRANSIENT)
        self.assertIn("locked", concurrent.message)
        self.assertEqual(second_harness.events, [])
        self.assertEqual(first_result["value"].exit_code, ExitCode.COMPLETE)

    def test_finalize_requires_remote_verification_of_every_receipt(self) -> None:
        harness = CallbackHarness()
        harness.verify_cloud_unverified = "pair-1"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, harness)
            result = runner.run()
            with self.assertRaises(TransientRunError):
                runner.finalize()
            self.assertFalse((root / "finalization.json").exists())
            self.assertEqual(runner.status()["state"], "complete")

            harness.verify_cloud_unverified = None
            finalization = runner.finalize()

        self.assertEqual(result.exit_code, ExitCode.COMPLETE)
        self.assertEqual(finalization["remote_verified_pairs"], 3)
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "verify_cloud"],
            [0, 1, 0, 1, 2],
        )

    def test_finalize_crash_after_file_reverifies_remote_before_checkpoint_commit(
        self,
    ) -> None:
        harness = CallbackHarness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, harness)
            self.assertEqual(runner.run().exit_code, ExitCode.COMPLETE)
            real_write_checkpoint = runner._write_checkpoint  # noqa: SLF001

            def crash_before_finalized_checkpoint(checkpoint: dict) -> None:
                if checkpoint.get("state") == "finalized":
                    raise SimulatedProcessCrash(
                        "crash after finalization file before checkpoint"
                    )
                real_write_checkpoint(checkpoint)

            with mock.patch.object(
                runner,
                "_write_checkpoint",
                side_effect=crash_before_finalized_checkpoint,
            ):
                with self.assertRaises(SimulatedProcessCrash):
                    runner.finalize()

            self.assertTrue((root / "finalization.json").is_file())
            checkpoint = json.loads(
                (root / "checkpoint.json").read_text(encoding="utf-8")
            )
            self.assertEqual(checkpoint["state"], "complete")

            recovered = self.make_runner(root, harness).finalize()
            checkpoint = json.loads(
                (root / "checkpoint.json").read_text(encoding="utf-8")
            )

        self.assertTrue(recovered["verified"])
        self.assertEqual(checkpoint["state"], "finalized")
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "verify_cloud"],
            [0, 1, 2, 0, 1, 2],
        )

    def test_preexisting_finalization_cannot_bypass_live_remote_verification(
        self,
    ) -> None:
        harness = CallbackHarness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, harness)
            self.assertEqual(runner.run().exit_code, ExitCode.COMPLETE)
            runner.finalize()

            checkpoint_path = root / "checkpoint.json"
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            checkpoint["state"] = "complete"
            checkpoint_path.write_text(
                json.dumps(checkpoint, sort_keys=True) + "\n", encoding="utf-8"
            )
            harness.events.clear()
            harness.verify_cloud_unverified = "pair-0"

            with self.assertRaises(TransientRunError):
                self.make_runner(root, harness).finalize()

            unchanged = json.loads(checkpoint_path.read_text(encoding="utf-8"))

        self.assertEqual(unchanged["state"], "complete")
        self.assertEqual(
            [event[1] for event in harness.events if event[0] == "verify_cloud"],
            [0],
        )

    def test_status_rejects_unknown_finalization_fields(self) -> None:
        harness = CallbackHarness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, harness)
            self.assertEqual(runner.run().exit_code, ExitCode.COMPLETE)
            runner.finalize()
            finalization_path = root / "finalization.json"
            finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
            finalization["unexpected"] = True
            finalization_path.write_text(json.dumps(finalization), encoding="utf-8")

            with self.assertRaisesRegex(ContractError, "finalization drift"):
                runner.status()

    def test_run_rejects_malformed_existing_finalization(self) -> None:
        harness = CallbackHarness()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runner = self.make_runner(root, harness)
            self.assertEqual(runner.run().exit_code, ExitCode.COMPLETE)
            runner.finalize()
            finalization_path = root / "finalization.json"
            finalization = json.loads(finalization_path.read_text(encoding="utf-8"))
            finalization["finalized_at"] = "not-a-timestamp"
            finalization_path.write_text(json.dumps(finalization), encoding="utf-8")

            resumed = self.make_runner(root, CallbackHarness()).run()

        self.assertEqual(resumed.exit_code, ExitCode.PERMANENT)
        self.assertIn("finalization drift", resumed.message)

    def test_finalize_refuses_incomplete_run_and_run_requires_callbacks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runner = self.make_runner(Path(tmp))
            missing_callbacks = runner.run()
            with self.assertRaisesRegex(ContractError, "cannot finalize incomplete run"):
                runner.finalize()

        self.assertEqual(missing_callbacks.exit_code, ExitCode.PERMANENT)


if __name__ == "__main__":
    unittest.main()
