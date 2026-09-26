from __future__ import annotations

import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_cloud_transaction as cloud_transaction_module  # noqa: E402
from publication_archive import PairArchiveError, build_pair_archive  # noqa: E402
from publication_cloud_transaction import (  # noqa: E402
    CloudTransactionError,
    LedgerIntegrityError,
    PublicationCloudTransaction,
    TRANSACTION_STATES,
    _exclusive_file_lock,
    _canonical_json,
    verify_cloud_ledger,
)
from seafile_artifact_store import ArtifactIntegrityError  # noqa: E402
from publication_article_statistics_v1 import (  # noqa: E402
    build_article_statistics_pair_record_v1,
    persist_article_statistics_pair_record_v1,
    validate_article_statistics_binding_v1,
)
from tests.test_publication_article_statistics_v1 import _arm_material  # noqa: E402


MATRIX_SHA256 = "a" * 64


class SimulatedCrash(BaseException):
    pass


class FakeStore:
    def __init__(self) -> None:
        self.remote: dict[str, bytes] = {}
        self.upload_calls: list[str] = []
        self.fail_after_first_upload = False
        self._failure_raised = False

    def upload_and_verify(self, path: Path, *, remote_name: str) -> dict[str, object]:
        payload = path.read_bytes()
        self.upload_calls.append(remote_name)
        if remote_name in self.remote and self.remote[remote_name] != payload:
            raise ArtifactIntegrityError("remote collision")
        already_present = remote_name in self.remote
        self.remote[remote_name] = payload
        if self.fail_after_first_upload and not self._failure_raised:
            self._failure_raised = True
            raise CloudTransactionError("simulated lost upload response")
        return {
            "status": (
                "already_present_and_verified" if already_present else "uploaded_and_verified"
            ),
            "remote_name": remote_name,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def verify_remote(
        self,
        remote_name: str,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        payload = self.remote.get(remote_name)
        if payload is None:
            raise ArtifactIntegrityError("remote missing")
        if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise ArtifactIntegrityError("remote integrity mismatch")
        return {
            "status": "verified",
            "remote_name": remote_name,
            "size_bytes": len(payload),
            "sha256": expected_sha256,
        }

    def materialize_remote(
        self,
        remote_name: str,
        *,
        destination: Path,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, object]:
        result = self.verify_remote(
            remote_name,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.remote[remote_name])
        return {**result, "status": "materialized_and_verified", "path": str(destination)}


def prepare_pair(
    run_root: Path,
    *,
    pair_id: str = "pair-0001",
    pair_sequence: int = 1,
    attempt: int = 1,
    matrix_sha256: str = MATRIX_SHA256,
    run_id: str = "full-run-001",
) -> tuple[Path, Path]:
    pair_dir = (
        run_root
        / "pairs"
        / f"{pair_sequence:04d}_{pair_id}"
        / f"attempt-{attempt:04d}"
    )
    pair_dir.mkdir(parents=True)
    pair_sha256 = "b" * 64
    statistics_record = build_article_statistics_pair_record_v1(
        pair_identity={
            "matrix_sha256": matrix_sha256,
            "run_id": run_id,
            "pair_sequence": pair_sequence,
            "pair_id": pair_id,
            "pair_sha256": pair_sha256,
            "attempt": attempt,
        },
        arms=[_arm_material(pair_dir, 0), _arm_material(pair_dir, 1)],
        primary_architecture_pair_metric=None,
    )
    statistics_binding = persist_article_statistics_pair_record_v1(
        statistics_record,
        run_root=run_root,
        pair_dir=pair_dir,
    )
    acceptance = pair_dir / "acceptance.json"
    acceptance.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "artifact_kind": "vast_full_publication_pair_acceptance",
                "status": "accepted",
                "matrix_sha256": matrix_sha256,
                "run_id": run_id,
                "pair_sequence": pair_sequence,
                "pair_id": pair_id,
                "pair_sha256": pair_sha256,
                "attempt": attempt,
                "arm_ids": ["arm-1", "arm-2"],
                "qualification_authorities": {
                    "identity_artifact_binding_sha256": "a" * 64,
                    "resource_capability_grant_sha256": "b" * 64,
                    "backend_runtime_grant_sha256": "c" * 64,
                    "model_parity_grant_sha256": "d" * 64,
                    "model_parity_acceptance_binding_sha256": "e" * 64,
                },
                "pair_gates": {
                    "common_identity_and_qualification_authorities": True,
                    "article_statistics_sealed_and_cross_bound": True,
                },
                "article_statistics": statistics_binding,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (pair_dir / "baseline" / "raw").mkdir(parents=True)
    (pair_dir / "baseline" / "raw" / "frames.bin").write_bytes(b"baseline-evidence")
    (pair_dir / "shared" / "raw").mkdir(parents=True)
    (pair_dir / "shared" / "raw" / "frames.bin").write_bytes(b"shared-evidence")
    return pair_dir, acceptance


def commit(
    transaction: PublicationCloudTransaction,
    pair_dir: Path,
    acceptance: Path,
) -> dict[str, object]:
    return transaction.commit_pair(
        pair_dir=pair_dir,
        acceptance_manifest=acceptance,
        matrix_sha256=MATRIX_SHA256,
        run_id="full-run-001",
        pair_sequence=1,
        pair_id="pair-0001",
    )


class PublicationCloudTransactionTests(unittest.TestCase):
    def test_ledger_bytes_are_exact_across_crash_and_restart_recovery(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_after_first(state: str) -> None:
                if state == "accepted":
                    raise SimulatedCrash(state)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        transition_hook=crash_after_first,
                    ),
                    pair_dir,
                    acceptance,
                )

            ledger = run_root / "cloud_ledger.jsonl"
            first_rows = verify_cloud_ledger(ledger)
            expected_first = b"".join(
                _canonical_json(row) + b"\n" for row in first_rows
            )
            actual_first = ledger.read_bytes()
            self.assertEqual(ledger.stat().st_size, len(expected_first))
            self.assertEqual(actual_first, expected_first)
            self.assertEqual(
                hashlib.sha256(actual_first).hexdigest(),
                hashlib.sha256(expected_first).hexdigest(),
            )

            result = commit(
                PublicationCloudTransaction(store=store, run_root=run_root),
                pair_dir,
                acceptance,
            )

            self.assertEqual(result["state"], "local_pruned")
            recovered_rows = verify_cloud_ledger(ledger)
            expected_recovered = b"".join(
                _canonical_json(row) + b"\n" for row in recovered_rows
            )
            actual_recovered = ledger.read_bytes()
            self.assertEqual(ledger.stat().st_size, len(expected_recovered))
            self.assertEqual(actual_recovered, expected_recovered)
            self.assertEqual(
                hashlib.sha256(actual_recovered).hexdigest(),
                hashlib.sha256(expected_recovered).hexdigest(),
            )
            durable_binding = recovered_rows[-1]["article_statistics_binding"]
            self.assertEqual(
                result["article_statistics_record_identity_sha256"],
                durable_binding["record_identity_sha256"],
            )
            retained = run_root / durable_binding["retained_copy"]["relative_path"]
            self.assertTrue(retained.is_file())
            validate_article_statistics_binding_v1(
                durable_binding,
                run_root=run_root,
                pair_dir=pair_dir,
                require_attempt_copy=False,
                require_retained_copy=True,
                require_raw_evidence=False,
            )
            receipt_names = [
                name for name in store.remote if name.endswith(".receipt.json")
            ]
            self.assertEqual(len(receipt_names), 1)
            remote_receipt = json.loads(store.remote[receipt_names[0]])
            self.assertEqual(
                remote_receipt["article_statistics"], durable_binding
            )

    def test_all_ledger_write_descriptors_use_portable_binary_mode(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            base = Path(tmp)
            append_root = base / "append"
            append_transaction = PublicationCloudTransaction(
                store=FakeStore(), run_root=append_root
            )
            snapshot = {
                "matrix_sha256": MATRIX_SHA256,
                "run_id": "full-run-001",
                "pair_sequence": 1,
                "pair_id": "pair-0001",
            }
            observed_flags: list[int] = []
            real_open = os.open

            def recording_open(
                path: os.PathLike[str] | str,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                resolved = Path(path).resolve()
                if (
                    resolved.name == "cloud_ledger.jsonl"
                    and flags & os.O_WRONLY
                ):
                    observed_flags.append(flags)
                if dir_fd is None:
                    return real_open(path, flags, mode)
                return real_open(path, flags, mode, dir_fd=dir_fd)

            with mock.patch(
                "publication_cloud_transaction.os.open",
                side_effect=recording_open,
            ):
                entry = append_transaction._append_transition(
                    snapshot, state="accepted"
                )
                payload = _canonical_json(entry) + b"\n"

                recovery_root = base / "recovery"
                recovery_root.mkdir()
                recovery_ledger = recovery_root / "cloud_ledger.jsonl"
                recovery_ledger.write_bytes(payload[: len(payload) // 2])
                pending = {
                    "schema_version": "vast-cloud-ledger-pending/v1",
                    "expected_ledger_size": 0,
                    "payload_size": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "entry": entry,
                }
                (recovery_root / "cloud_ledger.jsonl.pending").write_bytes(
                    _canonical_json(pending) + b"\n"
                )
                recovered = PublicationCloudTransaction(
                    store=FakeStore(), run_root=recovery_root
                )._load_entries()

            self.assertEqual(recovered, [])
            self.assertEqual(recovery_ledger.read_bytes(), b"")
            self.assertEqual(len(observed_flags), 2)
            append_flags = [flags for flags in observed_flags if flags & os.O_APPEND]
            recovery_flags = [flags for flags in observed_flags if not flags & os.O_APPEND]
            self.assertEqual(len(append_flags), 1)
            self.assertEqual(len(recovery_flags), 1)
            binary_flag = getattr(os, "O_BINARY", 0)
            for flags in observed_flags:
                self.assertEqual(flags & binary_flag, binary_flag)

    def test_pending_journal_recovers_torn_and_fully_appended_ledger_rows(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as source_tmp:
            source_root = Path(source_tmp) / "run"
            pair_dir, acceptance = prepare_pair(source_root)
            source_transaction = PublicationCloudTransaction(
                store=FakeStore(), run_root=source_root
            )

            def crash_after_first(state: str) -> None:
                if state == "accepted":
                    raise SimulatedCrash(state)

            source_transaction.transition_hook = crash_after_first
            with self.assertRaises(SimulatedCrash):
                commit(source_transaction, pair_dir, acceptance)
            entry = json.loads(
                (source_root / "cloud_ledger.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()[0]
            )
            payload = _canonical_json(entry) + b"\n"

        for suffix_size, expected_rows in (
            (max(1, len(payload) // 2), 0),
            (len(payload), 1),
        ):
            with self.subTest(suffix_size=suffix_size), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                run_root = Path(tmp) / "run"
                run_root.mkdir()
                ledger = run_root / "cloud_ledger.jsonl"
                ledger.write_bytes(payload[:suffix_size])
                pending = {
                    "schema_version": "vast-cloud-ledger-pending/v1",
                    "expected_ledger_size": 0,
                    "payload_size": len(payload),
                    "payload_sha256": hashlib.sha256(payload).hexdigest(),
                    "entry": entry,
                }
                (run_root / "cloud_ledger.jsonl.pending").write_bytes(
                    _canonical_json(pending) + b"\n"
                )
                transaction = PublicationCloudTransaction(
                    store=FakeStore(), run_root=run_root
                )
                rows = transaction._load_entries()
                self.assertEqual(len(rows), expected_rows)
                self.assertFalse((run_root / "cloud_ledger.jsonl.pending").exists())
                self.assertEqual(
                    ledger.stat().st_size,
                    len(payload) if expected_rows else 0,
                )

    def test_cloud_lock_is_exclusive_and_nonblocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock_path = Path(tmp) / "run" / ".cloud_transaction.lock"
            with _exclusive_file_lock(lock_path):
                with self.assertRaisesRegex(CloudTransactionError, "locked"):
                    with _exclusive_file_lock(lock_path):
                        self.fail("exclusive lock unexpectedly re-entered")

    def test_failed_partial_ledger_append_rolls_back_to_last_durable_offset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            real_write = os.write
            calls = 0

            def partial_then_fail(descriptor: int, payload: bytes) -> int:
                nonlocal calls
                calls += 1
                if calls == 1:
                    prefix = payload[: max(1, len(payload) // 2)]
                    return real_write(descriptor, prefix)
                raise OSError("simulated append failure")

            with mock.patch(
                "publication_cloud_transaction.os.write",
                side_effect=partial_then_fail,
            ):
                with self.assertRaises(CloudTransactionError):
                    commit(
                        PublicationCloudTransaction(store=store, run_root=run_root),
                        pair_dir,
                        acceptance,
                    )

            ledger = run_root / "cloud_ledger.jsonl"
            self.assertEqual(ledger.read_bytes(), b"")
            result = commit(
                PublicationCloudTransaction(store=store, run_root=run_root),
                pair_dir,
                acceptance,
            )
            self.assertEqual(result["state"], "local_pruned")

    def test_unverified_status_never_authorizes_prune(self) -> None:
        class UnverifiedStore(FakeStore):
            def upload_and_verify(self, path: Path, *, remote_name: str) -> dict[str, object]:
                result = super().upload_and_verify(path, remote_name=remote_name)
                return {**result, "status": "unverified"}

        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            with self.assertRaisesRegex(CloudTransactionError, "verification"):
                commit(
                    PublicationCloudTransaction(store=UnverifiedStore(), run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertTrue(pair_dir.is_dir())

    def test_zero_based_pair_sequence_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root, pair_sequence=0)
            result = PublicationCloudTransaction(
                store=FakeStore(), run_root=run_root
            ).commit_pair(
                pair_dir=pair_dir,
                acceptance_manifest=acceptance,
                matrix_sha256=MATRIX_SHA256,
                run_id="full-run-001",
                pair_sequence=0,
                pair_id="pair-0001",
            )
            self.assertEqual(result["pair_sequence"], 0)

    def test_acceptance_manifest_identity_is_fail_closed(self) -> None:
        mutations = {
            "schema_version": 1,
            "artifact_kind": "wrong-kind",
            "matrix_sha256": "b" * 64,
            "run_id": "other-run",
            "pair_sequence": 2,
            "pair_id": "other-pair",
            "pair_sha256": "c" * 64,
            "attempt": 2,
            "arm_ids": ["other-arm-1", "other-arm-2"],
            "qualification_authorities": {
                "identity_artifact_binding_sha256": "a" * 64,
            },
            "pair_gates": {
                "common_identity_and_qualification_authorities": False,
            },
        }
        for field, value in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                manifest = json.loads(acceptance.read_text(encoding="utf-8"))
                manifest[field] = value
                acceptance.write_text(
                    json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(CloudTransactionError, "acceptance manifest"):
                    commit(
                        PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                        pair_dir,
                        acceptance,
                    )

    def test_resume_reverifies_remote_before_prune(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_after(state: str) -> None:
                if state == "local_ledger_committed":
                    raise SimulatedCrash(state)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        transition_hook=crash_after,
                    ),
                    pair_dir,
                    acceptance,
                )
            state = json.loads(next((run_root / "cloud_state").glob("*.json")).read_text())
            store.remote[state["archive_remote_name"]] = b"remote-corruption"

            with self.assertRaises((CloudTransactionError, ArtifactIntegrityError)):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertTrue(pair_dir.is_dir())

    def test_resume_rejects_pair_tree_mutation_after_archive_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_after(state: str) -> None:
                if state == "archive_ready":
                    raise SimulatedCrash(state)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        transition_hook=crash_after,
                    ),
                    pair_dir,
                    acceptance,
                )
            (pair_dir / "shared" / "raw" / "frames.bin").write_bytes(b"changed")

            with self.assertRaises(Exception):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertTrue(pair_dir.is_dir())

    def test_commit_uses_content_addressed_archive_and_receipt_then_prunes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            transaction = PublicationCloudTransaction(store=store, run_root=run_root)

            result = commit(transaction, pair_dir, acceptance)

            self.assertEqual(result["state"], "local_pruned")
            self.assertRegex(str(result["acceptance_sha256"]), r"^[0-9a-f]{64}$")
            self.assertRegex(str(result["ledger_entry_sha256"]), r"^[0-9a-f]{64}$")
            self.assertFalse(pair_dir.exists())
            self.assertFalse(Path(str(result["local_archive_path"])).exists())
            self.assertTrue(Path(str(result["local_receipt_path"])).is_file())
            self.assertIn(str(result["archive_sha256"]), str(result["archive_remote_name"]))
            self.assertIn(str(result["receipt_sha256"]), str(result["receipt_remote_name"]))
            self.assertLessEqual(len(str(result["archive_remote_name"])), 255)
            self.assertLessEqual(len(str(result["receipt_remote_name"])), 255)
            self.assertEqual(
                set(store.remote),
                {result["archive_remote_name"], result["receipt_remote_name"]},
            )

            entries = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")
            self.assertEqual([entry["state"] for entry in entries], list(TRANSACTION_STATES))
            self.assertEqual(entries[-1]["entry_seq"], len(TRANSACTION_STATES))

    def test_pair_is_not_deleted_before_receipt_and_durable_ledger(self) -> None:
        for crash_state in ("remote_receipt_verified", "local_ledger_committed"):
            with self.subTest(crash_state=crash_state), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                store = FakeStore()

                def crash_after(state: str) -> None:
                    if state == crash_state:
                        raise SimulatedCrash(state)

                transaction = PublicationCloudTransaction(
                    store=store,
                    run_root=run_root,
                    transition_hook=crash_after,
                )
                with self.assertRaises(SimulatedCrash):
                    commit(transaction, pair_dir, acceptance)
                self.assertTrue(pair_dir.is_dir())

                result = commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
                self.assertEqual(result["state"], "local_pruned")
                self.assertFalse(pair_dir.exists())

    def test_all_durable_states_resume_without_duplicate_ledger_entries(self) -> None:
        for crash_state in TRANSACTION_STATES[:-1]:
            with self.subTest(crash_state=crash_state), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                store = FakeStore()

                def crash_after(state: str) -> None:
                    if state == crash_state:
                        raise SimulatedCrash(state)

                with self.assertRaises(SimulatedCrash):
                    commit(
                        PublicationCloudTransaction(
                            store=store,
                            run_root=run_root,
                            transition_hook=crash_after,
                        ),
                        pair_dir,
                        acceptance,
                    )

                result = commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
                self.assertEqual(result["state"], "local_pruned")
                entries = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")
                self.assertEqual([entry["state"] for entry in entries], list(TRANSACTION_STATES))

    def test_mid_prune_crash_resumes_partial_tombstone_without_reupload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            observed_entries: list[str] = []

            def crash_mid_prune(entry: str) -> None:
                observed_entries.append(entry)
                raise SimulatedCrash(entry)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        prune_entry_hook=crash_mid_prune,
                    ),
                    pair_dir,
                    acceptance,
                )

            self.assertTrue(observed_entries)
            self.assertFalse(pair_dir.exists())
            entries = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")
            self.assertEqual(entries[-1]["state"], "prune_started")
            tombstone = run_root / str(entries[-1]["prune_tombstone_relative_path"])
            self.assertTrue(tombstone.is_dir())
            uploads_before_resume = list(store.upload_calls)

            result = commit(
                PublicationCloudTransaction(store=store, run_root=run_root),
                pair_dir,
                acceptance,
            )

            self.assertEqual(result["state"], "local_pruned")
            self.assertEqual(store.upload_calls, uploads_before_resume)
            self.assertFalse(pair_dir.exists())
            self.assertFalse(tombstone.exists())

    def test_crash_after_tombstone_rename_resumes_without_reupload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_before_first_delete(**_: object) -> None:
                raise SimulatedCrash("after-tombstone-rename")

            with mock.patch(
                "publication_cloud_transaction._remove_owned_tombstone_tree",
                side_effect=crash_before_first_delete,
            ):
                with self.assertRaises(SimulatedCrash):
                    commit(
                        PublicationCloudTransaction(store=store, run_root=run_root),
                        pair_dir,
                        acceptance,
                    )

            latest = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")[-1]
            self.assertEqual(latest["state"], "prune_started")
            tombstone = run_root / str(latest["prune_tombstone_relative_path"])
            self.assertFalse(pair_dir.exists())
            self.assertTrue(tombstone.is_dir())
            uploads_before_resume = list(store.upload_calls)

            result = commit(
                PublicationCloudTransaction(store=store, run_root=run_root),
                pair_dir,
                acceptance,
            )

            self.assertEqual(result["state"], "local_pruned")
            self.assertEqual(store.upload_calls, uploads_before_resume)
            self.assertFalse(tombstone.exists())

    def test_crash_after_delete_before_local_pruned_wal_resumes(self) -> None:
        class CrashBeforeLocalPruned(PublicationCloudTransaction):
            crashed = False

            def _append_transition(
                self, snapshot: object, *, state: str
            ) -> dict[str, object]:
                if state == "local_pruned" and not self.crashed:
                    self.crashed = True
                    raise SimulatedCrash("before-local-pruned-wal")
                return super()._append_transition(snapshot, state=state)  # type: ignore[arg-type]

        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            transaction = CrashBeforeLocalPruned(store=store, run_root=run_root)

            with self.assertRaises(SimulatedCrash):
                commit(transaction, pair_dir, acceptance)

            latest = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")[-1]
            self.assertEqual(latest["state"], "prune_started")
            tombstone = run_root / str(latest["prune_tombstone_relative_path"])
            self.assertFalse(pair_dir.exists())
            self.assertFalse(tombstone.exists())
            self.assertFalse(Path(str(latest["local_archive_path"])).exists())
            uploads_before_resume = list(store.upload_calls)

            result = commit(
                PublicationCloudTransaction(store=store, run_root=run_root),
                pair_dir,
                acceptance,
            )

            self.assertEqual(result["state"], "local_pruned")
            self.assertEqual(store.upload_calls, uploads_before_resume)

    def test_resume_rejects_source_replacement_after_tombstoning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            crashed = False

            def replace_source_and_crash(entry: str) -> None:
                nonlocal crashed
                if crashed:
                    return
                crashed = True
                pair_dir.mkdir(parents=True)
                (pair_dir / "must-survive.txt").write_text(
                    "replacement", encoding="utf-8"
                )
                raise SimulatedCrash(entry)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        prune_entry_hook=replace_source_and_crash,
                    ),
                    pair_dir,
                    acceptance,
                )

            with self.assertRaisesRegex(
                CloudTransactionError,
                "source and tombstone both exist|source path was replaced",
            ):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertEqual(
                (pair_dir / "must-survive.txt").read_text(encoding="utf-8"),
                "replacement",
            )

    def test_resume_rejects_tombstone_aba_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_mid_prune(entry: str) -> None:
                raise SimulatedCrash(entry)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        prune_entry_hook=crash_mid_prune,
                    ),
                    pair_dir,
                    acceptance,
                )
            latest = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")[-1]
            tombstone = run_root / str(latest["prune_tombstone_relative_path"])
            displaced = run_root / "displaced-owned-tombstone"
            tombstone.rename(displaced)
            tombstone.mkdir()
            sentinel = tombstone / "must-survive.txt"
            sentinel.write_text("replacement", encoding="utf-8")

            with self.assertRaisesRegex(
                CloudTransactionError, "tombstone identity changed"
            ):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "replacement")

    def test_resume_rejects_tombstone_redirect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_mid_prune(entry: str) -> None:
                raise SimulatedCrash(entry)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        prune_entry_hook=crash_mid_prune,
                    ),
                    pair_dir,
                    acceptance,
                )
            latest = verify_cloud_ledger(run_root / "cloud_ledger.jsonl")[-1]
            tombstone = run_root / str(latest["prune_tombstone_relative_path"])
            displaced = run_root / "displaced-owned-tombstone"
            tombstone.rename(displaced)
            outside = root / "must-survive"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            try:
                tombstone.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            with self.assertRaisesRegex(
                CloudTransactionError, "not a plain directory"
            ):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")

    def test_lost_upload_response_reuses_existing_spool_and_remote_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            store.fail_after_first_upload = True
            transaction = PublicationCloudTransaction(store=store, run_root=run_root)

            with self.assertRaises(CloudTransactionError):
                commit(transaction, pair_dir, acceptance)
            spool_archives = list((run_root / "cloud_spool").glob("*.tar.zst"))
            self.assertEqual(len(spool_archives), 1)
            first_digest = hashlib.sha256(spool_archives[0].read_bytes()).hexdigest()
            self.assertTrue(pair_dir.exists())

            result = commit(
                PublicationCloudTransaction(store=store, run_root=run_root),
                pair_dir,
                acceptance,
            )
            self.assertEqual(result["archive_sha256"], first_digest)
            self.assertEqual(result["state"], "local_pruned")

    def test_remote_collision_fails_closed_and_preserves_local_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_after(state: str) -> None:
                if state == "archive_ready":
                    raise SimulatedCrash(state)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        transition_hook=crash_after,
                    ),
                    pair_dir,
                    acceptance,
                )
            state = json.loads(next((run_root / "cloud_state").glob("*.json")).read_text())
            store.remote[state["archive_remote_name"]] = b"collision"

            with self.assertRaises((CloudTransactionError, ArtifactIntegrityError)):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
            self.assertTrue(pair_dir.is_dir())

    def test_ledger_tampering_is_detected_before_resume(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            transaction = PublicationCloudTransaction(store=FakeStore(), run_root=run_root)
            commit(transaction, pair_dir, acceptance)
            ledger = run_root / "cloud_ledger.jsonl"
            body = ledger.read_text(encoding="utf-8")
            ledger.write_text(body.replace("local_pruned", "local_broken", 1), encoding="utf-8")

            with self.assertRaises(LedgerIntegrityError):
                verify_cloud_ledger(ledger)
            with self.assertRaises(LedgerIntegrityError):
                transaction.verify_pair_remote(pair_sequence=1, pair_id="pair-0001")

    def test_resume_cannot_redirect_prune_outside_recorded_pair_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_after(state: str) -> None:
                if state == "local_ledger_committed":
                    raise SimulatedCrash(state)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        transition_hook=crash_after,
                    ),
                    pair_dir,
                    acceptance,
                )
            outside = root / "must-survive"
            outside.mkdir()
            (outside / "sentinel.txt").write_text("keep", encoding="utf-8")

            with self.assertRaisesRegex(CloudTransactionError, "durable transaction identity"):
                PublicationCloudTransaction(store=store, run_root=run_root).commit_pair(
                    pair_dir=outside,
                    acceptance_manifest=acceptance,
                    matrix_sha256=MATRIX_SHA256,
                    run_id="full-run-001",
                    pair_sequence=1,
                    pair_id="pair-0001",
                )

            self.assertEqual((outside / "sentinel.txt").read_text(encoding="utf-8"), "keep")
            self.assertTrue(pair_dir.is_dir())

    def test_pair_directory_must_match_exact_production_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, _ = prepare_pair(run_root)
            wrong_pair_dir = run_root / "pairs" / "pair-0001"
            pair_dir.rename(wrong_pair_dir)
            acceptance = wrong_pair_dir / "acceptance.json"

            with self.assertRaisesRegex(CloudTransactionError, "pair directory layout"):
                commit(
                    PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                    wrong_pair_dir,
                    acceptance,
                )
            self.assertTrue(wrong_pair_dir.is_dir())

    def test_pair_directory_lexical_alias_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            alias = pair_dir.parent / ".." / pair_dir.parent.name / pair_dir.name

            with self.assertRaisesRegex(CloudTransactionError, "lexically canonical"):
                commit(
                    PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                    alias,
                    alias / "acceptance.json",
                )
            self.assertTrue(pair_dir.is_dir())
            self.assertTrue(acceptance.is_file())

    def test_acceptance_must_be_exact_recorded_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            duplicate = pair_dir / "nested" / "acceptance.json"
            duplicate.parent.mkdir()
            duplicate.write_bytes(acceptance.read_bytes())

            with self.assertRaisesRegex(CloudTransactionError, "exact pair acceptance marker"):
                commit(
                    PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                    pair_dir,
                    duplicate,
                )
            self.assertTrue(pair_dir.is_dir())

    def test_resume_rejects_symlink_prune_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()

            def crash_after(state: str) -> None:
                if state == "local_ledger_committed":
                    raise SimulatedCrash(state)

            with self.assertRaises(SimulatedCrash):
                commit(
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        transition_hook=crash_after,
                    ),
                    pair_dir,
                    acceptance,
                )

            preserved = root / "preserved-pair"
            pair_dir.rename(preserved)
            outside = root / "must-survive"
            outside.mkdir()
            sentinel = outside / "sentinel.txt"
            sentinel.write_text("keep", encoding="utf-8")
            try:
                pair_dir.symlink_to(outside, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("directory symlinks are unavailable")

            with self.assertRaisesRegex(CloudTransactionError, "link, junction, or reparse"):
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    pair_dir / "acceptance.json",
                )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep")
            self.assertTrue(preserved.is_dir())

    def test_mocked_junction_or_reparse_target_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            real_check = cloud_transaction_module._is_link_junction_or_reparse

            def mark_pair_as_reparse(path: Path) -> bool:
                return path == pair_dir or real_check(path)

            with mock.patch(
                "publication_cloud_transaction._is_link_junction_or_reparse",
                side_effect=mark_pair_as_reparse,
            ):
                with self.assertRaisesRegex(
                    CloudTransactionError, "link, junction, or reparse"
                ):
                    commit(
                        PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                        pair_dir,
                        acceptance,
                    )
            self.assertTrue(pair_dir.is_dir())

    def test_lstat_identity_drift_aborts_immediately_before_rmtree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            original = root / "original-pair"
            real_validate = cloud_transaction_module._validate_pair_archive
            calls = 0

            def validate_then_swap(*, archive_path: Path, pair_dir: Path) -> dict[str, object]:
                nonlocal calls
                result = real_validate(archive_path=archive_path, pair_dir=pair_dir)
                calls += 1
                if calls == 1:
                    pair_dir.rename(original)
                    pair_dir.mkdir()
                    (pair_dir / "must-survive.txt").write_text(
                        "replacement", encoding="utf-8"
                    )
                return result

            with mock.patch(
                "publication_cloud_transaction._validate_pair_archive",
                side_effect=validate_then_swap,
            ):
                with self.assertRaisesRegex(CloudTransactionError, "identity changed"):
                    commit(
                        PublicationCloudTransaction(store=store, run_root=run_root),
                        pair_dir,
                        acceptance,
                    )

            self.assertEqual(
                (pair_dir / "must-survive.txt").read_text(encoding="utf-8"),
                "replacement",
            )
            self.assertTrue((original / "acceptance.json").is_file())

    def test_acceptance_hash_is_rechecked_immediately_before_rmtree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            real_validate = cloud_transaction_module._validate_pair_archive

            def validate_then_mutate_marker(
                *, archive_path: Path, pair_dir: Path
            ) -> dict[str, object]:
                result = real_validate(archive_path=archive_path, pair_dir=pair_dir)
                payload = acceptance.read_bytes()
                acceptance.write_bytes(payload.replace(b'"accepted"', b'"rejected"'))
                return result

            with mock.patch(
                "publication_cloud_transaction._validate_pair_archive",
                side_effect=validate_then_mutate_marker,
            ):
                with self.assertRaisesRegex(
                    CloudTransactionError, "acceptance manifest changed before local prune"
                ):
                    commit(
                        PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                        pair_dir,
                        acceptance,
                    )
            self.assertTrue(pair_dir.is_dir())

    def test_successful_prune_uses_exact_recorded_source_and_tombstone(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            real_remove = cloud_transaction_module._remove_owned_tombstone_tree
            observed: list[dict[str, object]] = []

            def guarded_remove(**kwargs: object) -> None:
                observed.append(dict(kwargs))
                self.assertEqual(kwargs["run_root"], run_root)
                self.assertEqual(
                    kwargs["source_relative"],
                    pair_dir.relative_to(run_root),
                )
                self.assertEqual(
                    Path(str(kwargs["tombstone_relative"])).parent,
                    Path("cloud_prune_tombstones"),
                )
                real_remove(**kwargs)

            with mock.patch(
                "publication_cloud_transaction._remove_owned_tombstone_tree",
                side_effect=guarded_remove,
            ):
                result = commit(
                    PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                    pair_dir,
                    acceptance,
                )

            self.assertEqual(result["state"], "local_pruned")
            self.assertEqual(len(observed), 1)

    def test_materialize_restores_pair_only_after_remote_verification(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            transaction = PublicationCloudTransaction(store=store, run_root=run_root)
            result = commit(transaction, pair_dir, acceptance)
            destination_root = Path(tmp) / "materialized"

            restored = transaction.materialize_pair(
                pair_sequence=1,
                pair_id="pair-0001",
                destination_root=destination_root,
            )

            restored_pair = Path(str(restored["pair_path"]))
            self.assertEqual(restored_pair, destination_root / "attempt-0001")
            self.assertEqual(
                (restored_pair / "baseline" / "raw" / "frames.bin").read_bytes(),
                b"baseline-evidence",
            )
            self.assertEqual(
                (restored_pair / "shared" / "raw" / "frames.bin").read_bytes(),
                b"shared-evidence",
            )

            shutil.rmtree(restored_pair)
            store.remote[str(result["archive_remote_name"])] = b"tampered"
            with self.assertRaises((CloudTransactionError, ArtifactIntegrityError)):
                transaction.materialize_pair(
                    pair_sequence=1,
                    pair_id="pair-0001",
                    destination_root=destination_root,
                )
            self.assertFalse(restored_pair.exists())

    def test_materialize_rejects_self_consistent_foreign_archive_not_in_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run_root = root / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            original_store = FakeStore()
            committed = commit(
                PublicationCloudTransaction(
                    store=original_store, run_root=run_root
                ),
                pair_dir,
                acceptance,
            )

            foreign_pair = root / "foreign" / "attempt-0001"
            foreign_pair.mkdir(parents=True)
            (foreign_pair / "foreign-evidence.bin").write_bytes(
                b"self-consistent-but-not-ledger-authorized\n"
            )
            foreign_archive = root / "foreign.tar.zst"
            build_pair_archive(
                pair_dir=foreign_pair,
                archive_path=foreign_archive,
                compression_level=3,
            )
            foreign_payload = foreign_archive.read_bytes()
            expected_archive_size = int(committed["archive_size_bytes"])
            padding_size = expected_archive_size - len(foreign_payload)
            self.assertGreaterEqual(padding_size, 8)
            # Zstandard skippable frame: keep the foreign tar stream valid and
            # force its archive size to equal the ledger-pinned archive size,
            # so this regression exercises the SHA binding rather than only
            # the size gate.
            foreign_payload += struct.pack(
                "<II", 0x184D2A50, padding_size - 8
            ) + (b"\x00" * (padding_size - 8))
            self.assertEqual(len(foreign_payload), expected_archive_size)
            self.assertNotEqual(
                hashlib.sha256(foreign_payload).hexdigest(),
                committed["archive_sha256"],
            )

            class ForeignMaterializeStore(FakeStore):
                def materialize_remote(
                    self,
                    remote_name: str,
                    *,
                    destination: Path,
                    expected_sha256: str,
                    expected_size: int,
                ) -> dict[str, object]:
                    self.verify_remote(
                        remote_name,
                        expected_sha256=expected_sha256,
                        expected_size=expected_size,
                    )
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    destination.write_bytes(foreign_payload)
                    # Model a compromised/downstream-raced store response that
                    # repeats ledger fields while publishing a different,
                    # internally valid tar.zst.
                    return {
                        "status": "materialized_and_verified",
                        "remote_name": remote_name,
                        "size_bytes": expected_size,
                        "sha256": expected_sha256,
                        "destination": str(destination),
                    }

            malicious = ForeignMaterializeStore()
            malicious.remote = dict(original_store.remote)
            destination = root / "materialized"
            with self.assertRaisesRegex(
                PairArchiveError, "cloud ledger receipt"
            ):
                PublicationCloudTransaction(
                    store=malicious, run_root=run_root
                ).materialize_pair(
                    pair_sequence=1,
                    pair_id="pair-0001",
                    destination_root=destination,
                )
            self.assertFalse((destination / "attempt-0001").exists())

    def test_materialize_never_reuses_or_deletes_predictable_temporary_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            store = FakeStore()
            transaction = PublicationCloudTransaction(store=store, run_root=run_root)
            result = commit(transaction, pair_dir, acceptance)
            destination_root = Path(tmp) / "materialized"
            destination_root.mkdir()
            sentinel = destination_root / (
                f".attempt-0001.{result['archive_sha256']}.tar.zst"
            )
            sentinel.write_bytes(b"must-survive")

            restored = transaction.materialize_pair(
                pair_sequence=1,
                pair_id="pair-0001",
                destination_root=destination_root,
            )

            self.assertTrue(Path(str(restored["pair_path"])).is_dir())
            self.assertEqual(sentinel.read_bytes(), b"must-survive")

    def test_materialize_directory_recovers_each_physical_crash_window(self) -> None:
        for crash_step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(crash_step=crash_step), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                store = FakeStore()
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
                destination = Path(tmp) / "materialized"
                final = destination / "attempt-0001"
                faulted = False

                def fault(step: str, path: Path) -> None:
                    nonlocal faulted
                    self.assertEqual(path, final)
                    if step == crash_step and not faulted:
                        faulted = True
                        raise SimulatedCrash(step)

                with self.assertRaises(SimulatedCrash):
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        materialize_directory_physical_fault=fault,
                    ).materialize_pair(
                        pair_sequence=1,
                        pair_id="pair-0001",
                        destination_root=destination,
                    )
                published_inode = final.stat().st_ino if final.exists() else None
                staged_inodes = {
                    path.stat().st_ino
                    for path in destination.glob(".attempt-0001.*.tmp")
                    if path.is_dir()
                }

                restored = PublicationCloudTransaction(
                    store=store,
                    run_root=run_root,
                ).materialize_pair(
                    pair_sequence=1,
                    pair_id="pair-0001",
                    destination_root=destination,
                )
                self.assertTrue(faulted)
                self.assertEqual(
                    Path(str(restored["pair_path"])),
                    final,
                )
                if published_inode is not None:
                    self.assertEqual(final.stat().st_ino, published_inode)
                elif crash_step == "post_fsync_pre_publish":
                    self.assertIn(final.stat().st_ino, staged_inodes)

    def test_materialize_directory_rejects_racing_foreign_and_rebind(self) -> None:
        for attack_step in (
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(attack_step=attack_step), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                store = FakeStore()
                commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
                destination = Path(tmp) / "materialized"
                final = destination / "attempt-0001"

                def attack(step: str, path: Path) -> None:
                    if step != attack_step:
                        return
                    if path.exists():
                        shutil.rmtree(path)
                    path.mkdir()
                    (path / "foreign.txt").write_bytes(b"foreign-materialization\n")

                with self.assertRaises(PairArchiveError):
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                        materialize_directory_physical_fault=attack,
                    ).materialize_pair(
                        pair_sequence=1,
                        pair_id="pair-0001",
                        destination_root=destination,
                    )
                foreign_inode = final.stat().st_ino
                foreign_payload = (final / "foreign.txt").read_bytes()
                with self.assertRaises(PairArchiveError):
                    PublicationCloudTransaction(
                        store=store,
                        run_root=run_root,
                    ).materialize_pair(
                        pair_sequence=1,
                        pair_id="pair-0001",
                        destination_root=destination,
                    )
                self.assertEqual(final.stat().st_ino, foreign_inode)
                self.assertEqual(
                    (final / "foreign.txt").read_bytes(),
                    foreign_payload,
                )

    def test_local_receipt_recovers_each_physical_crash_window(self) -> None:
        for crash_step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(crash_step=crash_step), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                store = FakeStore()
                faulted = False

                def fault(step: str, path: Path) -> None:
                    nonlocal faulted
                    self.assertEqual(path.parent, run_root / "cloud_receipts")
                    if step == crash_step and not faulted:
                        faulted = True
                        raise SimulatedCrash(step)

                with self.assertRaises(SimulatedCrash):
                    commit(
                        PublicationCloudTransaction(
                            store=store,
                            run_root=run_root,
                            immutable_receipt_physical_fault=fault,
                        ),
                        pair_dir,
                        acceptance,
                    )
                receipts = tuple((run_root / "cloud_receipts").glob("*.receipt.json"))
                self.assertLessEqual(len(receipts), 1)
                published_inode = receipts[0].stat().st_ino if receipts else None

                result = commit(
                    PublicationCloudTransaction(store=store, run_root=run_root),
                    pair_dir,
                    acceptance,
                )
                receipt_path = Path(str(result["local_receipt_path"]))
                self.assertTrue(faulted)
                self.assertEqual(result["state"], "local_pruned")
                if published_inode is not None:
                    self.assertEqual(receipt_path.stat().st_ino, published_inode)

    def test_local_receipt_rejects_racing_foreign_and_rebound_final(self) -> None:
        for attack_step in (
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(attack_step=attack_step), tempfile.TemporaryDirectory() as tmp:
                run_root = Path(tmp) / "run"
                pair_dir, acceptance = prepare_pair(run_root)
                store = FakeStore()
                attacked_path: Path | None = None

                def attack(step: str, path: Path) -> None:
                    nonlocal attacked_path
                    if step != attack_step:
                        return
                    attacked_path = path
                    if path.exists():
                        path.unlink()
                    path.write_bytes(b"foreign-cloud-receipt\n")
                    path.chmod(0o444)

                with self.assertRaises(CloudTransactionError):
                    commit(
                        PublicationCloudTransaction(
                            store=store,
                            run_root=run_root,
                            immutable_receipt_physical_fault=attack,
                        ),
                        pair_dir,
                        acceptance,
                    )
                assert attacked_path is not None
                foreign_inode = attacked_path.stat().st_ino
                foreign_payload = attacked_path.read_bytes()
                with self.assertRaises(CloudTransactionError):
                    commit(
                        PublicationCloudTransaction(store=store, run_root=run_root),
                        pair_dir,
                        acceptance,
                    )
                self.assertEqual(attacked_path.stat().st_ino, foreign_inode)
                self.assertEqual(attacked_path.read_bytes(), foreign_payload)
                self.assertTrue(pair_dir.is_dir())


if __name__ == "__main__":
    unittest.main()
