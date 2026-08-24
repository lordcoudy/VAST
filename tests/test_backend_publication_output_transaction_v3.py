from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "backend_publication_v3_process_fixture.py"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backend_publication_dispatch_v3 as dispatch  # noqa: E402
import backend_publication_output_transaction_v3 as transaction  # noqa: E402
import backend_publication_process_supervisor_v3 as supervisor  # noqa: E402
from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class SyntheticTransactionAbort(BaseException):
    pass


class BackendPublicationOutputTransactionV3Tests(unittest.TestCase):
    maxDiff = None

    def setUp(self) -> None:
        if os.name == "nt":
            scratch = ROOT / ".test-tmp"
            scratch.mkdir(exist_ok=True)
            self.temporary = tempfile.TemporaryDirectory(dir=scratch)
            self.project_root = ROOT.resolve(strict=True)
            self.python_path = Path(sys.executable).resolve(strict=True)
            self.assertEqual(
                self.python_path.relative_to(self.project_root).parts[0], ".venv"
            )
        else:
            self.temporary = tempfile.TemporaryDirectory()
            self.project_root = Path("/").resolve(strict=True)
            self.python_path = Path(sys.executable).resolve(strict=True)
        self.addCleanup(self.temporary.cleanup)
        self.output_dir = Path(self.temporary.name).resolve(strict=True) / "transaction"
        self.arm_path = self.output_dir / dispatch.ARM_CONTRACT_FILENAME
        self.fixture_path = FIXTURE.resolve(strict=True)
        self.python_descriptor = self._project_descriptor(self.python_path)
        self.launcher_descriptor = self._project_descriptor(self.fixture_path)
        self.coordinate = {
            "system": "deepstream",
            "codec": "h264",
            "topology_kind": "shared_video_dag",
            "policy": "cpu_only",
            "deadline_ms": 50,
        }
        self.invocation = publication_launcher_invocation_v3_contract()
        self.dispatch_pins = {
            "expected_coordinate": self.coordinate,
            "expected_python_executable": self.python_descriptor,
            "expected_publication_launcher": self.launcher_descriptor,
            "expected_launcher_invocation_sha256": self.invocation[
                "invocation_sha256"
            ],
            "expected_backend_runtime_grant_sha256": "3" * 64,
            "expected_identity_artifact_binding_sha256": "4" * 64,
            "expected_cell_identity_sha256": "5" * 64,
            "expected_validation_record_sha256": "6" * 64,
            "expected_runtime_binding_identity_sha256": "7" * 64,
        }
        self.resolution = dispatch.build_backend_publication_dispatch_resolution_v3(
            coordinate=self.coordinate,
            python_executable=self.python_descriptor,
            publication_launcher=self.launcher_descriptor,
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
        self.evidence = ["latency_samples.json", "runtime_assessment.json"]
        self.arm_pins = {
            "expected_dispatch_resolution_sha256": self.resolution[
                "resolution_sha256"
            ],
            "expected_full_publication_execution_binding": self.execution,
            "expected_resource_capability_grant_sha256": "9" * 64,
            "expected_model_parity_grant_sha256": "a" * 64,
            "expected_model_parity_acceptance_binding_sha256": "b" * 64,
            "expected_launcher_evidence_files": self.evidence,
        }
        self._set_arm("success")

    def _project_descriptor(self, path: Path) -> dict[str, object]:
        relative = path.relative_to(self.project_root).as_posix()
        info = path.stat()
        return {
            "path": relative,
            "size_bytes": int(info.st_size),
            "sha256": _sha_file(path),
        }

    def _set_arm(self, mode: str) -> None:
        self.runtime_inputs = {
            **self.coordinate,
            "scenario": "checkpoint_video_dag_shared",
            "dataset": {
                "name": "synthetic-kpp",
                "split": "test",
                "synthetic_process_fixture_mode": mode,
                "synthetic_stdout_hex": b"stdout\x00\xff\n".hex(),
                "synthetic_stderr_hex": b"stderr\x00\xfe\n".hex(),
            },
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
        self.arm = dispatch.build_backend_publication_arm_contract_v3(
            dispatch_resolution=self.resolution,
            full_publication_execution_binding=self.execution,
            resource_capability_grant_sha256="9" * 64,
            model_parity_grant_sha256="a" * 64,
            model_parity_acceptance_binding_sha256="b" * 64,
            runtime_inputs=self.runtime_inputs,
            launcher_evidence_files=self.evidence,
        )
        self.arm_pins["expected_runtime_inputs"] = self.runtime_inputs

    def _prepare(self) -> dict[str, object]:
        return transaction.prepare_backend_publication_engineering_transaction_v3(
            output_dir=self.output_dir,
            arm_contract=self.arm,
        )

    def _arguments(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "project_root": self.project_root,
            "output_dir": self.output_dir,
            "expected_arm_contract_file_sha256": hashlib.sha256(
                dispatch.canonical_backend_publication_arm_contract_bytes_v3(self.arm)
            ).hexdigest(),
            "execution_scope": transaction.NONPUBLICATION_ENGINEERING_SCOPE,
            **self.dispatch_pins,
            **self.arm_pins,
        }
        values.update(overrides)
        return values

    def _run(self, **overrides: object) -> dict[str, object]:
        return transaction.run_or_resume_backend_publication_engineering_transaction_v3(
            **self._arguments(**overrides)
        )

    def _resealed_process_run(
        self, result: object, **changes: object
    ) -> supervisor.BackendPublicationProcessRunV3:
        forged = result.observation  # type: ignore[attr-defined]
        forged.update(changes)
        unsigned = copy.deepcopy(forged)
        unsigned.pop("observation_sha256")
        forged["observation_sha256"] = hashlib.sha256(
            supervisor.OBSERVATION_DOMAIN
            + json.dumps(
                unsigned,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii")
        ).hexdigest()
        return supervisor.BackendPublicationProcessRunV3(
            stdout=result.stdout,  # type: ignore[attr-defined]
            stderr=result.stderr,  # type: ignore[attr-defined]
            observation=forged,
        )

    def test_end_to_end_commit_and_read_only_resume(self) -> None:
        contract_authority = self._prepare()
        self.assertEqual(contract_authority["path"], dispatch.ARM_CONTRACT_FILENAME)
        before = self.arm_path.read_bytes()
        authority = self._run()
        self.assertEqual(self.arm_path.read_bytes(), before)
        self.assertEqual(authority["status"], "committed_nonpublication_engineering_output")
        for field in transaction._FALSE_CLAIM_FIELDS:  # noqa: SLF001 - exact contract
            self.assertIs(authority[field], False)
        expected_names = {
            dispatch.ARM_CONTRACT_FILENAME,
            dispatch.LAUNCH_FENCE_FILENAME,
            dispatch.CAPTURE_STDOUT_FILENAME,
            dispatch.CAPTURE_STDERR_FILENAME,
            dispatch.LAUNCHER_RESULT_FILENAME,
            dispatch.OUTPUT_RECEIPT_FILENAME,
            *self.evidence,
        }
        self.assertEqual({item.name for item in self.output_dir.iterdir()}, expected_names)
        snapshot = {
            item.name: (item.read_bytes(), item.stat().st_mtime_ns)
            for item in self.output_dir.iterdir()
        }
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("committed resume spawned child"),
        ):
            repeated = transaction.validate_backend_publication_engineering_transaction_v3(
                **self._arguments()
            )
        self.assertEqual(repeated, authority)
        self.assertEqual(
            snapshot,
            {
                item.name: (item.read_bytes(), item.stat().st_mtime_ns)
                for item in self.output_dir.iterdir()
            },
        )

        unsigned = copy.deepcopy(authority)
        declared = unsigned.pop("authority_sha256")
        self.assertEqual(
            declared,
            hashlib.sha256(
                json.dumps(
                    unsigned,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("ascii")
            ).hexdigest(),
        )

    def test_read_only_validator_never_spawns_a_prepared_arm(self) -> None:
        self._prepare()
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("read-only validation spawned child"),
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "read-only validation cannot spawn",
            ):
                transaction.validate_backend_publication_engineering_transaction_v3(
                    **self._arguments()
                )
        self.assertEqual(
            {item.name for item in self.output_dir.iterdir()},
            {dispatch.ARM_CONTRACT_FILENAME},
        )

    def test_nonzero_leaves_fence_and_never_relaunches_same_attempt(self) -> None:
        self._set_arm("nonzero")
        self._prepare()
        with self.assertRaises(transaction.BackendPublicationOutputTransactionV3Error):
            self._run()
        self.assertTrue((self.output_dir / dispatch.LAUNCH_FENCE_FILENAME).is_file())
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("fence-only resume relaunched child"),
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "ambiguous",
            ):
                self._run()

    def test_result_only_resume_finalizes_receipt_without_spawn(self) -> None:
        self._prepare()

        def fault(phase: str) -> None:
            if phase == "after_result_commit":
                raise SyntheticTransactionAbort()

        with self.assertRaises(SyntheticTransactionAbort):
            self._run(_fault_hook=fault)
        self.assertTrue((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).is_file())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("result-only resume spawned child"),
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "cannot finalize a result-only transaction",
            ):
                transaction.validate_backend_publication_engineering_transaction_v3(
                    **self._arguments()
                )
            self.assertFalse(
                (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists()
            )
            authority = self._run()
        self.assertEqual(authority["status"], "committed_nonpublication_engineering_output")
        self.assertTrue((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file())

    def test_fence_collision_and_extra_namespace_never_overwrite(self) -> None:
        self._prepare()
        collision = self.output_dir / dispatch.LAUNCH_FENCE_FILENAME
        collision.write_bytes(b"attacker-owned\n")
        before = collision.read_bytes()
        with self.assertRaises(transaction.BackendPublicationOutputTransactionV3Error):
            self._run()
        self.assertEqual(collision.read_bytes(), before)
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
        extra = self.output_dir / "unexpected.bin"
        extra.write_bytes(b"unexpected")
        with self.assertRaises(transaction.BackendPublicationOutputTransactionV3Error):
            self._run()
        self.assertEqual(extra.read_bytes(), b"unexpected")

    def test_committed_tamper_hardlink_and_subdirectory_fail_closed(self) -> None:
        self._prepare()
        self._run()
        receipt = self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME
        original = receipt.read_bytes()
        payload = bytearray(original)
        payload[len(payload) // 2] ^= 1
        receipt.write_bytes(payload)
        with self.assertRaises(transaction.BackendPublicationOutputTransactionV3Error):
            self._run()

        receipt.write_bytes(original)
        evidence = self.output_dir / self.evidence[0]
        alias = self.output_dir / "alias.bin"
        try:
            os.link(evidence, alias)
        except OSError:
            pass
        else:
            with self.assertRaises(transaction.BackendPublicationOutputTransactionV3Error):
                self._run()
            alias.unlink()

        nested = self.output_dir / "nested"
        nested.mkdir()
        with self.assertRaises(transaction.BackendPublicationOutputTransactionV3Error):
            self._run()

    def test_child_cannot_precreate_parent_owned_receipt(self) -> None:
        self._prepare()
        real_run = transaction.run_backend_publication_process_v3
        attacker_payload = b"attacker-owned-receipt\n"

        def observed(*args: object, **kwargs: object) -> object:
            result = real_run(*args, **kwargs)
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).write_bytes(
                attacker_payload
            )
            return result

        with mock.patch.object(
            transaction, "run_backend_publication_process_v3", side_effect=observed
        ):
            with self.assertRaises(
                transaction.BackendPublicationOutputTransactionV3Error
            ):
                self._run()
        self.assertEqual(
            (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).read_bytes(),
            attacker_payload,
        )
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())

    def test_partial_receipt_write_is_invalid_and_never_overwritten(self) -> None:
        self._prepare()
        real_write = transaction._write_all  # noqa: SLF001 - fault injection

        def interrupted(descriptor: int, payload: bytes) -> None:
            if transaction.RECEIPT_KIND.encode("ascii") in payload:
                os.write(descriptor, payload[:17])
                raise OSError("synthetic receipt write interruption")
            real_write(descriptor, payload)

        with mock.patch.object(transaction, "_write_all", side_effect=interrupted):
            with self.assertRaises(
                transaction.BackendPublicationOutputTransactionV3Error
            ):
                self._run()
        receipt = self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME
        partial = receipt.read_bytes()
        self.assertEqual(len(partial), 17)
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("invalid receipt resume spawned child"),
        ):
            with self.assertRaises(
                transaction.BackendPublicationOutputTransactionV3Error
            ):
                self._run()
        self.assertEqual(receipt.read_bytes(), partial)

    def test_postcommit_close_fault_does_not_reverse_durable_commit(self) -> None:
        self._prepare()
        original_close = transaction._HeldFile.close  # noqa: SLF001
        injected = False

        def close_then_raise(held: object, *, suppress: bool = False) -> None:
            nonlocal injected
            original_close(held, suppress=suppress)  # type: ignore[arg-type]
            if held.label == "output receipt" and not injected:  # type: ignore[attr-defined]
                injected = True
                raise OSError("synthetic postcommit release fault")

        with mock.patch.object(
            transaction._HeldFile, "close", new=close_then_raise  # noqa: SLF001
        ):
            authority = self._run()
        self.assertTrue(injected)
        self.assertEqual(
            authority["status"], "committed_nonpublication_engineering_output"
        )
        self.assertTrue((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file())

    def test_postreceipt_namespace_race_never_returns_authority(self) -> None:
        self._prepare()
        extra = self.output_dir / "postreceipt-race.bin"

        def fault(phase: str) -> None:
            if phase == "after_receipt_commit":
                extra.write_bytes(b"same-principal-race")

        with self.assertRaisesRegex(
            transaction.BackendPublicationOutputTransactionV3Error,
            "namespace is not exact",
        ):
            self._run(_fault_hook=fault)
        self.assertTrue((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).is_file())
        self.assertEqual(extra.read_bytes(), b"same-principal-race")
        with self.assertRaises(
            transaction.BackendPublicationOutputTransactionV3Error
        ):
            transaction.validate_backend_publication_engineering_transaction_v3(
                **self._arguments()
            )

    @unittest.skipIf(os.name == "nt", "POSIX directory-fsync ordering")
    def test_posix_parent_and_transaction_dirents_are_synchronized(self) -> None:
        observed: list[Path] = []
        original = transaction._DirectoryHold.sync_created_entry  # noqa: SLF001

        def synchronized(hold: object) -> None:
            observed.append(Path(hold.path))  # type: ignore[attr-defined]
            original(hold)  # type: ignore[arg-type]

        with mock.patch.object(
            transaction._DirectoryHold,  # noqa: SLF001
            "sync_created_entry",
            new=synchronized,
        ):
            self._prepare()
            self._run()
        self.assertEqual(observed[0], self.output_dir.parent)
        self.assertGreaterEqual(observed.count(self.output_dir), 6)

    def test_evidence_path_replacement_is_denied_or_detected(self) -> None:
        self._prepare()
        replacement = Path(self.temporary.name) / "replacement.bin"
        replacement_succeeded = False
        replacement_denied = False

        def fault(phase: str) -> None:
            nonlocal replacement_succeeded, replacement_denied
            if phase != "after_result_commit":
                return
            target = self.output_dir / self.evidence[0]
            payload = bytearray(target.read_bytes())
            payload[0] ^= 1
            replacement.write_bytes(payload)
            try:
                os.replace(replacement, target)
            except OSError:
                replacement_denied = True
            else:
                replacement_succeeded = True

        try:
            authority = self._run(_fault_hook=fault)
        except transaction.BackendPublicationOutputTransactionV3Error:
            self.assertTrue(replacement_succeeded)
            self.assertFalse(
                (self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists()
            )
        else:
            self.assertTrue(replacement_denied)
            self.assertEqual(
                authority["status"], "committed_nonpublication_engineering_output"
            )

    def test_evidence_cap_fails_before_parent_result_or_receipt(self) -> None:
        self._prepare()
        with mock.patch.object(transaction, "MAX_EVIDENCE_FILE_BYTES", 1):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "byte bound",
            ):
                self._run()
        self.assertTrue((self.output_dir / dispatch.LAUNCH_FENCE_FILENAME).is_file())
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())

    def test_evidence_aggregate_budget_is_enforced_incrementally(self) -> None:
        self._prepare()
        with mock.patch.object(transaction, "MAX_EVIDENCE_AGGREGATE_BYTES", 1):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "byte bound",
            ):
                self._run()
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())

    def test_evidence_and_namespace_entry_counts_are_bounded_before_spawn(self) -> None:
        self.evidence = [
            f"evidence-{index:03d}.json"
            for index in range(transaction.MAX_EVIDENCE_FILES + 1)
        ]
        self.arm_pins["expected_launcher_evidence_files"] = self.evidence
        self._set_arm("success")
        self._prepare()
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("oversized evidence set spawned child"),
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "evidence set exceeds its entry bound",
            ):
                self._run()

        # A separate fresh fixture is unnecessary for the namespace primitive:
        # the bounded scanner itself must reject before allocating every name.
        for index in range(transaction.MAX_TRANSACTION_NAMESPACE_ENTRIES):
            (self.output_dir / f"extra-{index:03d}.bin").write_bytes(b"x")
        with transaction._DirectoryHold(self.output_dir) as hold:  # noqa: SLF001
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "namespace exceeds its entry bound",
            ):
                hold.names()

    def test_external_pin_and_scope_drift_fail_before_spawn(self) -> None:
        self._prepare()
        with mock.patch.object(
            transaction,
            "run_backend_publication_process_v3",
            side_effect=AssertionError("invalid external authority spawned child"),
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "restricted to synthetic nonpublication scope",
            ):
                self._run(execution_scope="publication")
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "raw file SHA-256 drifted",
            ):
                self._run(expected_arm_contract_file_sha256="0" * 64)
        self.assertFalse((self.output_dir / dispatch.LAUNCH_FENCE_FILENAME).exists())

    def test_process_observation_is_crossbound_to_exact_argv(self) -> None:
        self._prepare()
        real_run = transaction.run_backend_publication_process_v3

        def observed(*args: object, **kwargs: object) -> object:
            result = real_run(*args, **kwargs)
            return self._resealed_process_run(result, argv_sha256="0" * 64)

        with mock.patch.object(
            transaction, "run_backend_publication_process_v3", side_effect=observed
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "not an exact success",
            ):
                self._run()
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())
        self.assertFalse((self.output_dir / dispatch.OUTPUT_RECEIPT_FILENAME).exists())

    def test_process_observation_rejects_bool_as_integer(self) -> None:
        self._prepare()
        real_run = transaction.run_backend_publication_process_v3

        def observed(*args: object, **kwargs: object) -> object:
            result = real_run(*args, **kwargs)
            return self._resealed_process_run(result, exit_code=False)

        with mock.patch.object(
            transaction, "run_backend_publication_process_v3", side_effect=observed
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "not an exact success",
            ):
                self._run()
        self.assertFalse((self.output_dir / dispatch.LAUNCHER_RESULT_FILENAME).exists())

    def test_control_json_requires_unique_canonical_bytes(self) -> None:
        with self.assertRaisesRegex(
            transaction.BackendPublicationOutputTransactionV3Error,
            "duplicate keys",
        ):
            transaction._parse_canonical_object(  # noqa: SLF001 - contract test
                b'{"a":1,"a":1}\n', label="synthetic control"
            )
        with self.assertRaisesRegex(
            transaction.BackendPublicationOutputTransactionV3Error,
            "not canonical",
        ):
            transaction._parse_canonical_object(  # noqa: SLF001 - contract test
                b'{"a": 1}\n', label="synthetic control"
            )

    @unittest.skipUnless(os.name == "nt", "Windows directory custody attack")
    def test_windows_directory_swap_before_native_custody_is_rejected(self) -> None:
        self._prepare()
        parked = self.output_dir.with_name(self.output_dir.name + ".parked")
        attacker = self.output_dir.with_name(self.output_dir.name + ".attacker")
        attacker.mkdir()
        original_open = transaction._DirectoryHold._open_windows  # noqa: SLF001
        attacked = False

        def swapped(hold: object) -> None:
            nonlocal attacked
            if Path(hold.path) != self.output_dir:  # type: ignore[attr-defined]
                original_open(hold)  # type: ignore[arg-type]
                return
            attacked = True
            os.replace(self.output_dir, parked)
            os.replace(attacker, self.output_dir)
            try:
                original_open(hold)  # type: ignore[arg-type]
            except BaseException:
                hold.close(suppress=True)  # type: ignore[attr-defined]
                os.replace(self.output_dir, attacker)
                os.replace(parked, self.output_dir)
                raise

        with mock.patch.object(
            transaction._DirectoryHold, "_open_windows", new=swapped  # noqa: SLF001
        ):
            with self.assertRaisesRegex(
                transaction.BackendPublicationOutputTransactionV3Error,
                "changed while opening",
            ):
                self._run()
        self.assertTrue(attacked)
        self.assertTrue(self.arm_path.is_file())
        attacker.rmdir()

    def test_two_coordinators_spawn_at_most_once(self) -> None:
        self._prepare()
        real_run = transaction.run_backend_publication_process_v3
        entered = threading.Event()
        release = threading.Event()
        calls = 0
        lock = threading.Lock()

        def observed(*args: object, **kwargs: object) -> object:
            nonlocal calls
            with lock:
                calls += 1
            entered.set()
            release.wait(5)
            return real_run(*args, **kwargs)

        outcomes: list[object] = []

        def worker() -> None:
            try:
                outcomes.append(self._run())
            except BaseException as exc:  # test records the competing outcome
                outcomes.append(exc)

        with mock.patch.object(
            transaction, "run_backend_publication_process_v3", side_effect=observed
        ):
            first = threading.Thread(target=worker)
            second = threading.Thread(target=worker)
            first.start()
            self.assertTrue(entered.wait(5))
            second.start()
            second.join(5)
            release.set()
            first.join(15)
        self.assertEqual(calls, 1)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(
            sum(type(item) is dict for item in outcomes),
            1,
            repr(outcomes),
        )
        self.assertEqual(
            sum(isinstance(item, transaction.BackendPublicationOutputTransactionV3Error)
                for item in outcomes),
            1,
            repr(outcomes),
        )

    def test_source_has_no_replace_tempfile_or_path_unlink(self) -> None:
        source = (
            ROOT / "scripts" / "backend_publication_output_transaction_v3.py"
        ).read_text(encoding="utf-8")
        for prohibited in ("os.replace", "tempfile", ".unlink(", "shell=True"):
            self.assertNotIn(prohibited, source)


if __name__ == "__main__":
    unittest.main()
