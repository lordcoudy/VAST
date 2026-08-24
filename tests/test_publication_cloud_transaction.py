from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_cloud_transaction as cloud_transaction_module  # noqa: E402
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
                "attempt": attempt,
                "arm_ids": ["baseline-arm", "shared-arm"],
                "qualification_authorities": {
                    "identity_artifact_binding_sha256": "a" * 64,
                    "resource_capability_grant_sha256": "b" * 64,
                    "backend_runtime_grant_sha256": "c" * 64,
                    "model_parity_grant_sha256": "d" * 64,
                    "model_parity_acceptance_binding_sha256": "e" * 64,
                },
                "pair_gates": {
                    "common_identity_and_qualification_authorities": True,
                },
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
    def test_pending_journal_recovers_torn_and_fully_appended_ledger_rows(self) -> None:
        with tempfile.TemporaryDirectory() as source_tmp:
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
            with self.subTest(suffix_size=suffix_size), tempfile.TemporaryDirectory() as tmp:
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
            "attempt": 2,
            "arm_ids": ["same-arm", "same-arm"],
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

    def test_successful_prune_calls_rmtree_only_for_exact_recorded_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, acceptance = prepare_pair(run_root)
            real_rmtree = shutil.rmtree
            observed: list[Path] = []

            def guarded_rmtree(path: Path, *args: object, **kwargs: object) -> None:
                observed.append(Path(path))
                self.assertEqual(Path(path), pair_dir)
                real_rmtree(path, *args, **kwargs)

            with mock.patch(
                "publication_cloud_transaction.shutil.rmtree",
                side_effect=guarded_rmtree,
            ):
                result = commit(
                    PublicationCloudTransaction(store=FakeStore(), run_root=run_root),
                    pair_dir,
                    acceptance,
                )

            self.assertEqual(result["state"], "local_pruned")
            self.assertEqual(observed, [pair_dir])

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


if __name__ == "__main__":
    unittest.main()
