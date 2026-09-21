from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import tracemalloc
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_pair_archive_sizing_receipts_v1 import (  # noqa: E402
    BackendPairArchiveSizingReceiptsV1Error,
    INDEX_FILENAME,
    SYSTEMS,
    load_seafile_sizing_rows_v1,
    materialize_backend_pair_archive_sizing_receipts_v1,
)
import backend_pair_archive_sizing_receipts_v1 as target  # noqa: E402


class InjectedCrash(BaseException):
    pass


def descriptor(path: str, marker: str) -> dict[str, object]:
    payload = marker.encode("ascii")
    return {
        "path": path,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def archive_fixture(
    root: Path,
    *,
    source_count: int = 2,
    source_size: int | None = None,
) -> tuple[
    Path, dict[str, object], str, list[dict[str, object]],
]:
    output = root / "accepted"
    output.mkdir()
    sources: list[dict[str, object]] = []
    for position in range(source_count):
        path = root / f"source-{position}.bin"
        payload = (
            f"physical-source-{position}".encode("ascii")
            if source_size is None
            else bytes([65 + position % 26]) * source_size
        )
        path.write_bytes(payload)
        sources.append({
            "path": path.relative_to(root).as_posix(),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    coordinate: dict[str, object] = {
        "system": "deepstream", "codec": "h264",
        "policy": "cpu_only", "deadline_ms": 16.7,
    }
    pair_identity = hashlib.sha256(b"pair-identity").hexdigest()
    arms: list[dict[str, object]] = [
        {
            "topology_kind": topology,
            "archive_entries": sources[position::len(target.TOPOLOGIES)],
        }
        for position, topology in enumerate(target.TOPOLOGIES)
    ]
    return output, coordinate, pair_identity, arms


class BackendPairArchiveSizingReceiptsV1ContractTests(unittest.TestCase):
    def test_public_contract_is_exact_280_pair_closed(self) -> None:
        self.assertEqual(
            SYSTEMS,
            ("deepstream", "savant", "openvino_gva", "gstreamer_custom"),
        )
        self.assertEqual(
            INDEX_FILENAME,
            "checkpoint_backend_pair_archive_sizing_index_v1.json",
        )
        self.assertTrue(callable(materialize_backend_pair_archive_sizing_receipts_v1))
        self.assertTrue(callable(load_seafile_sizing_rows_v1))
        self.assertTrue(issubclass(
            BackendPairArchiveSizingReceiptsV1Error, RuntimeError,
        ))

    def test_input_builder_requires_exact_ordered_280_pairs_and_560_arms(self) -> None:
        pairs = []
        for system in target.SYSTEMS:
            for codec in target.CODECS:
                for policy in target.POLICIES:
                    for deadline in target.DEADLINES_MS:
                        marker = f"{system}:{codec}:{policy}:{deadline}"
                        safe_marker = marker.replace(":", "-").replace(".", "p")
                        pairs.append({
                            "coordinate": {
                                "system": system, "codec": codec,
                                "policy": policy, "deadline_ms": deadline,
                            },
                            "arms": {
                                topology: {
                                    "output_receipt_authority": descriptor(
                                        f"q4/{safe_marker}/{topology}/authority.json",
                                        f"authority:{marker}:{topology}",
                                    ),
                                    "arm_payload": descriptor(
                                        f"q4/{safe_marker}/{topology}/arm.json",
                                        f"arm:{marker}:{topology}",
                                    ),
                                }
                                for topology in target.TOPOLOGIES
                            },
                        })
        value = target.build_backend_pair_archive_sizing_input_v1(
            q4_binding_index=descriptor("q4/binding.json", "q4-binding"),
            pairs=pairs,
        )
        self.assertEqual(value["coverage"]["pair_count"], 280)
        self.assertEqual(value["coverage"]["topology_arm_count"], 560)
        self.assertEqual(len({item["pair_identity_sha256"] for item in value["pairs"]}), 280)

        with self.assertRaisesRegex(
            BackendPairArchiveSizingReceiptsV1Error, "exactly 280",
        ):
            target.build_backend_pair_archive_sizing_input_v1(
                q4_binding_index=descriptor("q4/binding.json", "q4-binding"),
                pairs=pairs[:-1],
            )
        reordered = copy.deepcopy(pairs)
        reordered[0], reordered[1] = reordered[1], reordered[0]
        with self.assertRaisesRegex(
            BackendPairArchiveSizingReceiptsV1Error, "order/coordinate",
        ):
            target.build_backend_pair_archive_sizing_input_v1(
                q4_binding_index=descriptor("q4/binding.json", "q4-binding"),
                pairs=reordered,
            )

    def test_pair_archive_is_deterministic_rehashed_and_payload_tamper_detected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output = root / "accepted"
            output.mkdir()
            source_descriptors = []
            for topology in target.TOPOLOGIES:
                path = root / f"{topology}.bin"
                payload = f"physical:{topology}".encode("ascii")
                path.write_bytes(payload)
                source_descriptors.append({
                    "path": path.relative_to(root).as_posix(),
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                })
            coordinate = {
                "system": "deepstream", "codec": "h264",
                "policy": "cpu_only", "deadline_ms": 16.7,
            }
            pair_identity = hashlib.sha256(b"pair-identity").hexdigest()
            arms = [
                {
                    "topology_kind": topology,
                    "archive_entries": [source_descriptors[position]],
                }
                for position, topology in enumerate(target.TOPOLOGIES)
            ]
            registry = target._PhysicalRegistry(root)
            first, manifest_sha = target._commit_archive(
                root=root, output=output, coordinate=coordinate,
                pair_identity_sha256=pair_identity, arms=arms,
                registry=registry,
            )
            second, second_manifest = target._commit_archive(
                root=root, output=output, coordinate=coordinate,
                pair_identity_sha256=pair_identity, arms=arms,
                registry=registry,
            )
            self.assertEqual(first, second)
            self.assertEqual(manifest_sha, second_manifest)
            archive = root / first["path"]
            payload = archive.read_bytes()
            target._validate_archive_payload(
                payload, expected_descriptor=first,
                expected_coordinate=coordinate,
                expected_pair_identity=pair_identity,
                expected_manifest_sha256=manifest_sha,
            )
            archive.chmod(0o600)
            archive.write_bytes(payload[:-1] + bytes([payload[-1] ^ 1]))
            with self.assertRaises(Exception):
                target._PhysicalRegistry(root).read(first, "tampered archive")

    @unittest.skipUnless(os.name == "posix", "streaming WAL is POSIX-only")
    def test_pair_archive_recovers_every_streaming_publish_window(self) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for step in steps:
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                output, coordinate, pair_identity, arms = archive_fixture(root)

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    target._commit_archive(
                        root=root,
                        output=output,
                        coordinate=coordinate,
                        pair_identity_sha256=pair_identity,
                        arms=arms,
                        registry=target._PhysicalRegistry(root),
                        after_publish_step=crash,
                    )
                final = output / target._archive_filename(coordinate)
                published_identity = (
                    (final.stat().st_dev, final.stat().st_ino)
                    if final.exists()
                    else None
                )
                transaction_before = next(
                    (root / target._ARCHIVE_JOURNAL_ROOT).glob("txn-*")
                )
                staged_before = transaction_before / target._ARCHIVE_STAGE_NAME
                staged_identity = (
                    staged_before.stat().st_dev,
                    staged_before.stat().st_ino,
                )
                result, manifest_sha = target._commit_archive(
                    root=root,
                    output=output,
                    coordinate=coordinate,
                    pair_identity_sha256=pair_identity,
                    arms=arms,
                    registry=target._PhysicalRegistry(root),
                )
                self.assertEqual(result["path"], final.relative_to(root).as_posix())
                self.assertEqual(len(manifest_sha), 64)
                self.assertEqual(stat.S_IMODE(final.stat().st_mode), 0o444)
                self.assertEqual(final.stat().st_nlink, 1)
                self.assertEqual(
                    (final.stat().st_dev, final.stat().st_ino), staged_identity,
                )
                if published_identity is not None:
                    self.assertEqual(
                        (final.stat().st_dev, final.stat().st_ino),
                        published_identity,
                    )
                transactions = list(
                    (root / target._ARCHIVE_JOURNAL_ROOT).glob("txn-*")
                )
                self.assertEqual(len(transactions), 1)
                self.assertEqual(
                    {item.name for item in transactions[0].iterdir()},
                    {target._ARCHIVE_INTENT_NAME},
                )
                intent = json.loads(
                    (transactions[0] / target._ARCHIVE_INTENT_NAME).read_text(
                        encoding="ascii",
                    )
                )
                self.assertEqual(intent["target"], result)
                self.assertEqual(intent["manifest_sha256"], manifest_sha)
                self.assertEqual(
                    intent["stage_path"],
                    (
                        f"{target._ARCHIVE_JOURNAL_ROOT}/"
                        f"{transactions[0].name}/{target._ARCHIVE_STAGE_NAME}"
                    ),
                )

    @unittest.skipUnless(os.name == "posix", "streaming WAL is POSIX-only")
    def test_pair_archive_rejects_stage_replacement_and_foreign_entries(self) -> None:
        for replacement in ("symlink", "regular", "hardlink", "foreign_entry"):
            with (
                self.subTest(replacement=replacement),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary).resolve()
                output, coordinate, pair_identity, arms = archive_fixture(root)

                def crash(observed: str) -> None:
                    if observed == "post_fsync_pre_publish":
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    target._commit_archive(
                        root=root,
                        output=output,
                        coordinate=coordinate,
                        pair_identity_sha256=pair_identity,
                        arms=arms,
                        registry=target._PhysicalRegistry(root),
                        after_publish_step=crash,
                    )
                transaction = next(
                    (root / target._ARCHIVE_JOURNAL_ROOT).glob("txn-*")
                )
                stage = transaction / target._ARCHIVE_STAGE_NAME
                if replacement == "symlink":
                    stage.unlink()
                    stage.symlink_to(root / "source-0.bin")
                    expected_pattern = "stage is foreign"
                    replacement_identity = None
                    replacement_payload = None
                elif replacement == "regular":
                    stage.unlink()
                    replacement_payload = b"attacker-stage"
                    stage.write_bytes(replacement_payload)
                    stage.chmod(0o444)
                    replacement_identity = stage.stat().st_dev, stage.stat().st_ino
                    expected_pattern = "identity/mode/size|bytes"
                elif replacement == "hardlink":
                    os.link(stage, transaction / "stage-alias.bin")
                    expected_pattern = "foreign entries"
                    replacement_identity = None
                    replacement_payload = None
                else:
                    (transaction / "attacker.bin").write_bytes(b"attacker")
                    expected_pattern = "foreign entries"
                    replacement_identity = None
                    replacement_payload = None
                with self.assertRaisesRegex(
                    BackendPairArchiveSizingReceiptsV1Error,
                    expected_pattern,
                ):
                    target._commit_archive(
                        root=root,
                        output=output,
                        coordinate=coordinate,
                        pair_identity_sha256=pair_identity,
                        arms=arms,
                        registry=target._PhysicalRegistry(root),
                    )
                if replacement_identity is not None:
                    self.assertEqual(
                        (stage.stat().st_dev, stage.stat().st_ino),
                        replacement_identity,
                    )
                    self.assertEqual(stage.read_bytes(), replacement_payload)

    @unittest.skipUnless(os.name == "posix", "streaming WAL is POSIX-only")
    def test_pair_archive_rejects_final_tamper_and_post_link_stage_rebind(self) -> None:
        for tamper in ("final_bytes", "linked_stage"):
            with (
                self.subTest(tamper=tamper),
                tempfile.TemporaryDirectory() as temporary,
            ):
                root = Path(temporary).resolve()
                output, coordinate, pair_identity, arms = archive_fixture(root)
                final = output / target._archive_filename(coordinate)
                if tamper == "linked_stage":
                    def crash(observed: str) -> None:
                        if observed == "post_publish_pre_parent_fsync":
                            raise InjectedCrash(observed)

                    with self.assertRaises(InjectedCrash):
                        target._commit_archive(
                            root=root,
                            output=output,
                            coordinate=coordinate,
                            pair_identity_sha256=pair_identity,
                            arms=arms,
                            registry=target._PhysicalRegistry(root),
                            after_publish_step=crash,
                        )
                    transaction = next(
                        (root / target._ARCHIVE_JOURNAL_ROOT).glob("txn-*")
                    )
                    stage = transaction / target._ARCHIVE_STAGE_NAME
                    stage.unlink()
                    stage.symlink_to(root / "source-0.bin")
                    expected_pattern = "foreign stage"
                else:
                    target._commit_archive(
                        root=root,
                        output=output,
                        coordinate=coordinate,
                        pair_identity_sha256=pair_identity,
                        arms=arms,
                        registry=target._PhysicalRegistry(root),
                    )
                    original_size = final.stat().st_size
                    final.chmod(0o600)
                    final.write_bytes(b"x" * original_size)
                    final.chmod(0o444)
                    expected_pattern = "bytes or stable identity|collision"
                attacker_identity = final.stat().st_dev, final.stat().st_ino
                attacker_bytes = final.read_bytes()
                with self.assertRaisesRegex(
                    BackendPairArchiveSizingReceiptsV1Error,
                    expected_pattern,
                ):
                    target._commit_archive(
                        root=root,
                        output=output,
                        coordinate=coordinate,
                        pair_identity_sha256=pair_identity,
                        arms=arms,
                        registry=target._PhysicalRegistry(root),
                    )
                self.assertEqual(
                    (final.stat().st_dev, final.stat().st_ino), attacker_identity,
                )
                self.assertEqual(final.read_bytes(), attacker_bytes)

    @unittest.skipUnless(os.name == "posix", "dirfd ABA test is POSIX-only")
    def test_pair_archive_output_directory_rebind_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, coordinate, pair_identity, arms = archive_fixture(root)
            displaced = root / "accepted-displaced"
            attacker = root / "accepted-attacker"
            attacker.mkdir()
            canary = attacker / "canary.txt"
            canary.write_bytes(b"attacker-canary")
            swapped = False

            def swap(observed: str) -> None:
                nonlocal swapped
                if observed != "post_fsync_pre_publish":
                    return
                output.rename(displaced)
                attacker.rename(output)
                swapped = True

            with self.assertRaisesRegex(
                BackendPairArchiveSizingReceiptsV1Error,
                "directory|custody|rebound|changed",
            ):
                target._commit_archive(
                    root=root,
                    output=output,
                    coordinate=coordinate,
                    pair_identity_sha256=pair_identity,
                    arms=arms,
                    registry=target._PhysicalRegistry(root),
                    after_publish_step=swap,
                )
            self.assertTrue(swapped)
            self.assertEqual((output / "canary.txt").read_bytes(), b"attacker-canary")
            self.assertFalse((output / target._archive_filename(coordinate)).exists())

    @unittest.skipUnless(os.name == "posix", "memory bound is POSIX-only")
    def test_pair_archive_streaming_memory_is_bounded_below_archive_size(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, coordinate, pair_identity, arms = archive_fixture(
                root, source_count=24, source_size=1024 * 1024,
            )
            tracemalloc.start()
            try:
                result, _manifest_sha = target._commit_archive(
                    root=root,
                    output=output,
                    coordinate=coordinate,
                    pair_identity_sha256=pair_identity,
                    arms=arms,
                    registry=target._PhysicalRegistry(root),
                )
                _current, peak = tracemalloc.get_traced_memory()
            finally:
                tracemalloc.stop()
            self.assertGreater(result["size_bytes"], 24 * 1024 * 1024)
            self.assertLess(peak, 8 * 1024 * 1024)

    @unittest.skipUnless(
        os.name == "posix" and str(ROOT).startswith("/mnt/"),
        "DrvFS hard-link recovery requires WSL workspace",
    )
    def test_pair_archive_fd_anchored_hardlink_recovers_on_drvfs(self) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".pair-archive-drvfs-", dir=ROOT,
        ) as temporary:
            root = Path(temporary).resolve()
            output, coordinate, pair_identity, arms = archive_fixture(root)

            def crash(observed: str) -> None:
                if observed == "post_publish_pre_parent_fsync":
                    raise InjectedCrash(observed)

            with self.assertRaises(InjectedCrash):
                target._commit_archive(
                    root=root,
                    output=output,
                    coordinate=coordinate,
                    pair_identity_sha256=pair_identity,
                    arms=arms,
                    registry=target._PhysicalRegistry(root),
                    after_publish_step=crash,
                )
            final = output / target._archive_filename(coordinate)
            transaction = next(
                (root / target._ARCHIVE_JOURNAL_ROOT).glob("txn-*")
            )
            stage = transaction / target._ARCHIVE_STAGE_NAME
            self.assertEqual(final.stat().st_nlink, 2)
            self.assertEqual(
                (final.stat().st_dev, final.stat().st_ino),
                (stage.stat().st_dev, stage.stat().st_ino),
            )
            linked_identity = final.stat().st_dev, final.stat().st_ino
            target._commit_archive(
                root=root,
                output=output,
                coordinate=coordinate,
                pair_identity_sha256=pair_identity,
                arms=arms,
                registry=target._PhysicalRegistry(root),
            )
            self.assertFalse(stage.exists())
            self.assertEqual(final.stat().st_nlink, 1)
            self.assertEqual(
                (final.stat().st_dev, final.stat().st_ino), linked_identity,
            )

    def test_live_authority_is_persisted_outside_transaction_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            transaction = root / "transaction"
            transaction.mkdir()
            receipt_payload = b"physical-production-receipt\n"
            receipt_path = transaction / "backend_publication_output_receipt_v3.json"
            receipt_path.write_bytes(receipt_payload)
            sha = lambda marker: hashlib.sha256(marker.encode("ascii")).hexdigest()
            authority = {
                "schema_version": 4,
                "artifact_kind": (
                    "vast_backend_publication_production_output_receipt_authority_v4"
                ),
                "status": "accepted_publishable_backend_output",
                "execution_scope": "full_publication_measurement_v3",
                "path": receipt_path.name,
                "size_bytes": len(receipt_payload),
                "sha256": hashlib.sha256(receipt_payload).hexdigest(),
                "content_sha256": sha("receipt-content"),
                "arm_contract": {}, "launcher_result": {},
                "durable_process_journal_response": {},
                "evidence_files": [],
                "evidence_aggregate_sha256": sha("evidence"),
                "semantic_evidence_assessment": {},
                "semantic_evidence_assessment_sha256": sha("semantic"),
                "full_publication_execution_binding": {},
                "run_identity_sha256": sha("run"),
                "dispatch_resolution_sha256": sha("dispatch"),
                **{field: True for field in target._CLAIMS},
            }
            authority["authority_sha256"] = target._canonical_sha(authority)
            output = root / "authorities" / "deepstream-arm-a.json"
            descriptor_value = (
                target.persist_backend_production_output_receipt_authority_v1(
                    project_root=root, transaction_dir=transaction,
                    authority=authority, output_path=output,
                )
            )
            self.assertTrue(output.is_file())
            self.assertNotIn(output.name, {item.name for item in transaction.iterdir()})
            envelope = target._canonical_object(
                output.read_bytes(), "authority envelope",
                identity_field="envelope_sha256",
            )
            self.assertEqual(envelope["authority"], authority)
            self.assertEqual(descriptor_value["path"], "authorities/deepstream-arm-a.json")

            for step in (
                "mid_write",
                "post_fsync_pre_publish",
                "post_publish_pre_parent_fsync",
            ):
                with self.subTest(authority_step=step):
                    resumed_output = root / "authorities" / f"{step}.json"

                    def crash(observed: str) -> None:
                        if observed == step:
                            raise InjectedCrash(observed)

                    with self.assertRaises(InjectedCrash):
                        target.persist_backend_production_output_receipt_authority_v1(
                            project_root=root,
                            transaction_dir=transaction,
                            authority=authority,
                            output_path=resumed_output,
                            after_publish_step=crash,
                        )
                    published_identity = (
                        (resumed_output.stat().st_dev, resumed_output.stat().st_ino)
                        if resumed_output.exists()
                        else None
                    )
                    resumed = (
                        target.persist_backend_production_output_receipt_authority_v1(
                            project_root=root,
                            transaction_dir=transaction,
                            authority=authority,
                            output_path=resumed_output,
                        )
                    )
                    self.assertEqual(resumed["path"], f"authorities/{step}.json")
                    self.assertEqual(resumed_output.stat().st_nlink, 1)
                    self.assertEqual(
                        stat.S_IMODE(resumed_output.stat().st_mode), 0o444,
                    )
                    if published_identity is not None:
                        self.assertEqual(
                            (
                                resumed_output.stat().st_dev,
                                resumed_output.stat().st_ino,
                            ),
                            published_identity,
                        )


if __name__ == "__main__":
    unittest.main()
