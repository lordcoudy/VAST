from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_guardian_preprocessing_contract_v1 as target  # noqa: E402


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")


def canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def semantic_sha(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.hardware_resource_collector = root / "scripts/collect_metrics.py"
        self.hardware_resource_collector.parent.mkdir(parents=True, exist_ok=True)
        self.hardware_resource_collector.write_bytes(
            b"# qualification collector fixture\n"
        )
        self.contract = {
            "contract_id": "fixture-preprocessing-v1",
            "decoded_color_order": "RGB",
            "output_layout": "NCHW",
        }
        self.manifest_path = root / "configs" / "accepted-parity-v4.json"
        write_json(
            self.manifest_path,
            {
                "schema_version": 4,
                "artifact_kind": "checkpoint_analytics_model_parity_manifest_v4",
                "preprocessing_contract": self.contract,
            },
        )
        self.assessment_path = root / "configs" / "accepted-assessment-v4.json"
        write_json(self.assessment_path, {"fixture": "assessment"})
        self.deep_files: list[Path] = []
        for index in range(50):
            path = root / "evidence" / f"deep-{index:02d}.json"
            write_json(path, {"fixture": "deep", "index": index})
            self.deep_files.append(path)
        self.files = [descriptor(root, path) for path in self.deep_files]
        self.transaction_index_path = root / "evidence" / "transaction_index.json"
        write_json(self.transaction_index_path, {"fixture": "transaction-index"})
        self.v4_transaction = {
            **descriptor(root, self.transaction_index_path),
            "transaction_sha256": semantic_sha({"fixture": "transaction"}),
            "files_sha256": semantic_sha({"fixture": "transaction-files"}),
            "output_segments_sha256": semantic_sha({"fixture": "segments"}),
            "execution_bundle_count": 480,
            "execution_bundles_sha256": semantic_sha({"fixture": "bundles"}),
        }
        self.refresh_authority = {"fixture": "refresh-authority"}
        self.acceptance_binding_path = root / "configs" / "accepted-binding-v4.json"
        self.acceptance_receipt_path = root / "configs" / "accepted-receipt-v4.json"
        acceptance_receipt = {
            "schema_version": 4,
            "artifact_kind": "vast_checkpoint_model_parity_acceptance_receipt_v4",
            "acceptance_binding_path": self.acceptance_binding_path.relative_to(root).as_posix(),
        }
        write_json(self.acceptance_receipt_path, acceptance_receipt)
        binding_unsigned = {
            "schema_version": 4,
            "artifact_kind": "vast_verified_model_parity_acceptance_binding_v4",
            "accepted_manifest": descriptor(root, self.manifest_path),
            "accepted_assessment": descriptor(root, self.assessment_path),
            "receipt": descriptor(root, self.acceptance_receipt_path),
            "transaction_index": self.v4_transaction,
            "refresh_authority": self.refresh_authority,
            "files": self.files,
            "files_sha256": semantic_sha(self.files),
        }
        self.binding = {
            **binding_unsigned,
            "binding_sha256": semantic_sha(binding_unsigned),
        }
        write_json(self.acceptance_binding_path, self.binding)

        self.candidate_root = root / "qualification" / "candidate"
        self.index_path = self.candidate_root / "checkpoint_policy_qualification_index.v2.json"
        write_json(self.index_path, {"fixture": "index"})
        self.candidate_manifest_path = (
            self.candidate_root / "checkpoint_policy_capability_candidate_manifest.json"
        )
        self.policy_sha = semantic_sha({"fixture": "policy"})
        write_json(
            self.candidate_manifest_path,
            {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_capability_manifest",
                "policy_scope": "analytics_only",
                "policy_contract_sha256": self.policy_sha,
                "systems": {system: {} for system in SYSTEMS},
            },
        )
        self.candidate_receipt_path = (
            self.candidate_root / "checkpoint_policy_qualification_candidate_receipt.json"
        )
        candidate_unsigned = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
            "status": "qualification_candidate_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "policy_contract_sha256": self.policy_sha,
            "qualification_index": descriptor(root, self.index_path),
            "candidate_manifest": descriptor(root, self.candidate_manifest_path),
            "blockers": ["candidate_is_not_a_full_publication_authority"],
        }
        self.candidate_receipt = {
            **candidate_unsigned,
            "sha256": semantic_sha(candidate_unsigned),
        }
        write_json(self.candidate_receipt_path, self.candidate_receipt)

        self.transaction_path = root / "qualification" / "qualification_input_transaction.v2.receipt.json"
        placeholder = {"path": "fixture.json", "size_bytes": 1, "sha256": "a" * 64}
        transaction_unsigned = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_input_transaction_v2",
            "status": "qualification_inputs_materialized_nonaccepted",
            "scope": "forced_resource_qualification_pilots_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "systems": list(SYSTEMS),
            "cell_count": 32,
            "hardware_resource_collector": descriptor(
                root, self.hardware_resource_collector
            ),
            "image_identity_patch": placeholder,
            "image_identity_patch_sha256": "b" * 64,
            "accepted_model_parity_manifest": descriptor(root, self.manifest_path),
            "accepted_model_parity_assessment": descriptor(root, self.assessment_path),
            "accepted_model_parity_receipt": descriptor(root, self.acceptance_receipt_path),
            "model_parity_acceptance_binding_sha256": self.binding["binding_sha256"],
            "model_parity_acceptance_schema_version": 4,
            "image_patch_resolution": {
                "candidate_binding_eligible": False,
                "resolved_blockers": [
                    "analytics_worker:cpu_identity_changed_requires_parity_refresh",
                    "analytics_worker:gpu_identity_changed_requires_parity_refresh",
                ],
                "resolution": "physical_patch_bound_v4_parity_refresh",
            },
            "fragments": {system: placeholder for system in SYSTEMS},
            "candidate": {
                "index": descriptor(root, self.index_path),
                "manifest": descriptor(root, self.candidate_manifest_path),
                "receipt": descriptor(root, self.candidate_receipt_path),
            },
            "bootstrap": {
                "mapping": placeholder,
                "calibrations": {system: placeholder for system in SYSTEMS},
                "receipt": placeholder,
            },
            "blockers": [
                "transaction_is_not_policy_qualification_acceptance",
                "transaction_is_not_full_publication_authority",
                "transaction_requires_exact_32_physical_pilots",
            ],
        }
        self.transaction = {
            **transaction_unsigned,
            "receipt_sha256": semantic_sha(transaction_unsigned),
        }
        write_json(self.transaction_path, self.transaction)

    def acceptance_loader(self, *, project_root: Path, receipt_path: Path) -> dict[str, Any]:
        self.assert_paths(project_root, receipt_path)
        for record in self.binding["files"]:
            path = project_root.joinpath(*Path(record["path"]).parts)
            if descriptor(project_root, path) != record:
                raise RuntimeError("deep model-parity v4 file descriptor drifted")
        if descriptor(project_root, self.assessment_path) != self.binding["accepted_assessment"]:
            raise RuntimeError("model-parity v4 assessment descriptor drifted")
        return copy.deepcopy(self.binding)

    def assert_paths(self, project_root: Path, receipt_path: Path) -> None:
        if project_root != self.root or receipt_path != self.acceptance_receipt_path:
            raise AssertionError((project_root, receipt_path))


class SyntheticAtomicCrash(BaseException):
    pass


class GuardianPreprocessingContractV1Tests(unittest.TestCase):
    def test_drvfs_readonly_projection_accepts_0555_without_weakening_identity(
        self,
    ) -> None:
        root = Path("/project")
        path = root / "intent.json"
        payload = b"{}\n"
        descriptor = {
            "path": "intent.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        identity = (119, 1125899908819318)
        custody = mock.Mock(root=root)
        custody.commit_or_adopt_exact_identity.return_value = (
            descriptor,
            identity,
            "adopted",
        )
        custody.read_descriptor_identity.return_value = (
            descriptor,
            payload,
            identity,
        )
        custody.stat_regular_identity.return_value = (0o555, identity)

        self.assertEqual(
            target._commit_or_adopt_atomic_leaf(
                custody,
                path,
                payload,
                label="guardian preprocessing intent",
            ),
            descriptor,
        )

    def test_atomic_leaf_still_rejects_any_writable_projection(self) -> None:
        root = Path("/project")
        path = root / "intent.json"
        payload = b"{}\n"
        descriptor = {
            "path": "intent.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        identity = (119, 1125899908819318)
        custody = mock.Mock(root=root)
        custody.commit_or_adopt_exact_identity.return_value = (
            descriptor,
            identity,
            "adopted",
        )
        custody.read_descriptor_identity.return_value = (
            descriptor,
            payload,
            identity,
        )
        custody.stat_regular_identity.return_value = (0o644, identity)

        with self.assertRaisesRegex(
            target.GuardianPreprocessingContractV1Error,
            "identity drifted",
        ):
            target._commit_or_adopt_atomic_leaf(
                custody,
                path,
                payload,
                label="guardian preprocessing intent",
            )

    def test_materializer_rejects_hardware_collector_descriptor_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            fixture.hardware_resource_collector.write_bytes(
                b"# tampered qualification collector\n"
            )
            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "hardware resource collector|descriptor",
            ):
                target.materialize_guardian_preprocessing_contract_v1(
                    project_root=root,
                    qualification_transaction_receipt_path=(
                        fixture.transaction_path
                    ),
                    output_dir=root / "guardian-inputs/preprocessing-contract-v1",
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(
                        fixture.contract
                    ),
                )

    def test_materializes_receipt_last_and_loader_cross_binds_candidate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = root / "guardian-inputs" / "preprocessing-contract-v1"

            result = target.materialize_guardian_preprocessing_contract_v1(
                project_root=root,
                qualification_transaction_receipt_path=fixture.transaction_path,
                output_dir=output,
                acceptance_loader=fixture.acceptance_loader,
                expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
            )

            self.assertEqual(
                set(path.name for path in output.iterdir()),
                {
                    target.CONTRACT_FILENAME,
                    target.RECEIPT_FILENAME,
                },
            )
            loaded = target.load_guardian_preprocessing_contract_v1(
                project_root=root,
                preprocessing_contract_path=result["contract_path"],
                materialization_receipt_path=result["receipt_path"],
                candidate_manifest_path=fixture.candidate_manifest_path,
                acceptance_loader=fixture.acceptance_loader,
                expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
            )
            self.assertEqual(loaded["preprocessing_contract"], fixture.contract)
            authority = loaded["authority"]
            self.assertEqual(
                authority["preprocessing_contract_content_sha256"],
                semantic_sha(fixture.contract),
            )
            self.assertEqual(
                authority["model_parity_acceptance_binding_sha256"],
                fixture.binding["binding_sha256"],
            )
            self.assertEqual(
                authority["qualification_transaction_receipt_sha256"],
                fixture.transaction["receipt_sha256"],
            )
            self.assertEqual(authority["policy_contract_sha256"], fixture.policy_sha)

    def test_loader_rejects_candidate_changed_after_receipt_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = root / "guardian-inputs" / "preprocessing-contract-v1"
            result = target.materialize_guardian_preprocessing_contract_v1(
                project_root=root,
                qualification_transaction_receipt_path=fixture.transaction_path,
                output_dir=output,
                acceptance_loader=fixture.acceptance_loader,
                expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
            )
            fixture.candidate_manifest_path.write_bytes(
                fixture.candidate_manifest_path.read_bytes() + b" "
            )
            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "candidate manifest|descriptor",
            ):
                target.load_guardian_preprocessing_contract_v1(
                    project_root=root,
                    preprocessing_contract_path=result["contract_path"],
                    materialization_receipt_path=result["receipt_path"],
                    candidate_manifest_path=fixture.candidate_manifest_path,
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
                )

    def test_loader_reruns_full_v4_validation_after_deep_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = root / "guardian-inputs" / "preprocessing-contract-v1"
            result = target.materialize_guardian_preprocessing_contract_v1(
                project_root=root,
                qualification_transaction_receipt_path=fixture.transaction_path,
                output_dir=output,
                acceptance_loader=fixture.acceptance_loader,
                expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
            )
            fixture.deep_files[-1].write_bytes(
                fixture.deep_files[-1].read_bytes() + b" "
            )
            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "v4 acceptance chain|deep.*descriptor",
            ):
                target.load_guardian_preprocessing_contract_v1(
                    project_root=root,
                    preprocessing_contract_path=result["contract_path"],
                    materialization_receipt_path=result["receipt_path"],
                    candidate_manifest_path=fixture.candidate_manifest_path,
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(
                        fixture.contract
                    ),
                )

    def test_materializer_rejects_foreign_v4_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            foreign_assessment = root / "configs" / "foreign-assessment-v4.json"
            write_json(foreign_assessment, {"fixture": "foreign-assessment"})
            transaction = copy.deepcopy(fixture.transaction)
            transaction["accepted_model_parity_assessment"] = descriptor(
                root, foreign_assessment
            )
            unsigned = {
                key: value
                for key, value in transaction.items()
                if key != "receipt_sha256"
            }
            transaction["receipt_sha256"] = semantic_sha(unsigned)
            write_json(fixture.transaction_path, transaction)
            output = root / "guardian-inputs" / "preprocessing-contract-v1"

            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "assessment.*cross-link|assessment.*drift",
            ):
                target.materialize_guardian_preprocessing_contract_v1(
                    project_root=root,
                    qualification_transaction_receipt_path=fixture.transaction_path,
                    output_dir=output,
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(
                        fixture.contract
                    ),
                )
            self.assertFalse(output.exists())

    def test_materializer_rejects_transaction_acceptance_binding_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            transaction = copy.deepcopy(fixture.transaction)
            transaction["model_parity_acceptance_binding_sha256"] = "0" * 64
            unsigned = {key: value for key, value in transaction.items() if key != "receipt_sha256"}
            transaction["receipt_sha256"] = semantic_sha(unsigned)
            write_json(fixture.transaction_path, transaction)
            output = root / "guardian-inputs" / "preprocessing-contract-v1"

            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "acceptance binding",
            ):
                target.materialize_guardian_preprocessing_contract_v1(
                    project_root=root,
                    qualification_transaction_receipt_path=fixture.transaction_path,
                    output_dir=output,
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
                )
            self.assertFalse(output.exists())

    def test_materializer_never_overwrites_existing_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = root / "guardian-inputs" / "preprocessing-contract-v1"
            output.mkdir(parents=True)
            canary = output / "KEEP"
            canary.write_text("keep\n", encoding="ascii")
            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "already exists|overwrite",
            ):
                target.materialize_guardian_preprocessing_contract_v1(
                    project_root=root,
                    qualification_transaction_receipt_path=fixture.transaction_path,
                    output_dir=output,
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
                )
            self.assertEqual(canary.read_text(encoding="ascii"), "keep\n")

    def test_materializer_requires_output_outside_transaction_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            output = fixture.transaction_path.parent / "guardian-inputs"

            with self.assertRaisesRegex(
                target.GuardianPreprocessingContractV1Error,
                "outside.*transaction",
            ):
                target.materialize_guardian_preprocessing_contract_v1(
                    project_root=root,
                    qualification_transaction_receipt_path=fixture.transaction_path,
                    output_dir=output,
                    acceptance_loader=fixture.acceptance_loader,
                    expected_preprocessing_contract_sha256=semantic_sha(fixture.contract),
                )
            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == "posix", "dirfd race requires POSIX")
    def test_fd_custody_rejects_named_file_swap_during_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source = root / "source.json"
            replacement = root / "replacement.json"
            displaced = root / "displaced.json"
            write_json(source, {"source": True})
            write_json(replacement, {"source": False})
            original_read = target.os.read
            swapped = False

            def race_read(descriptor_value: int, byte_count: int) -> bytes:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    source.rename(displaced)
                    replacement.rename(source)
                return original_read(descriptor_value, byte_count)

            with (
                mock.patch.object(target.os, "read", side_effect=race_read),
                self.assertRaisesRegex(
                    target.GuardianPreprocessingContractV1Error,
                    "changed|replaced|identity",
                ),
            ):
                target._read_canonical_json(root, source, label="race source")

    @unittest.skipUnless(os.name == "posix", "symlink custody requires POSIX")
    def test_project_root_rejects_lexical_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            physical = Path(temporary).resolve()
            alias = physical.parent / f"{physical.name}-alias"
            alias.symlink_to(physical, target_is_directory=True)
            try:
                with self.assertRaisesRegex(
                    target.GuardianPreprocessingContractV1Error,
                    "project_root.*symlink|physical",
                ):
                    target._physical_root(alias)
            finally:
                alias.unlink()

    @unittest.skipUnless(os.name == "posix", "dirfd write race requires POSIX")
    def test_exclusive_write_parent_swap_never_redirects_output(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            parent = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            parent.mkdir()
            attacker.mkdir()
            custody = target.DirectoryFdCustodyV1.open_existing(
                parent, label="trusted output"
            )
            original_open = target.os.open
            swapped = False

            def race_open(
                path: object,
                flags: int,
                mode: int = 0o777,
                *,
                dir_fd: int | None = None,
            ) -> int:
                nonlocal swapped
                if (
                    not swapped
                    and dir_fd == custody.directory_fd
                    and path == "receipt.json"
                    and bool(flags & os.O_WRONLY)
                ):
                    swapped = True
                    parent.rename(displaced)
                    parent.symlink_to(attacker, target_is_directory=True)
                return original_open(path, flags, mode, dir_fd=dir_fd)

            try:
                with (
                    mock.patch.object(target.os, "open", side_effect=race_open),
                    self.assertRaisesRegex(
                        target.GuardianPreprocessingContractV1Error,
                        "directory chain|parent.*identity|changed",
                    ),
                ):
                    custody.write_exclusive(
                        "receipt.json", b"owned\n", mode=0o400
                    )
                self.assertTrue(swapped)
                self.assertFalse((attacker / "receipt.json").exists())
                self.assertFalse((displaced / "receipt.json").exists())
            finally:
                custody.close()

    @unittest.skipUnless(os.name == "posix", "dirfd rollback race requires POSIX")
    def test_owned_rollback_parent_swap_preserves_attacker_canary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            parent = root / "trusted"
            displaced = root / "trusted-displaced"
            attacker = root / "attacker"
            parent.mkdir()
            attacker.mkdir()
            custody = target.DirectoryFdCustodyV1.open_existing(
                parent, label="trusted rollback"
            )
            identity = custody.write_exclusive(
                "receipt.json", b"owned\n", mode=0o400
            )
            parent.rename(displaced)
            parent.symlink_to(attacker, target_is_directory=True)
            canary = attacker / "receipt.json"
            canary.write_bytes(b"attacker-canary\n")

            try:
                with self.assertRaisesRegex(
                    target.GuardianPreprocessingContractV1Error,
                    "directory chain|parent.*identity|changed",
                ):
                    custody.unlink_owned("receipt.json", identity)
                self.assertEqual(canary.read_bytes(), b"attacker-canary\n")
                self.assertFalse((displaced / "receipt.json").exists())
            finally:
                custody.close()

    def test_receipt_recovers_every_atomic_physical_window_same_path(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                fixture = Fixture(root)
                output = root / "atomic-guardian/preprocessing-contract-v1"
                receipt = output / target.RECEIPT_FILENAME
                fired = False

                def crash(observed_step: str, path: Path) -> None:
                    nonlocal fired
                    if not fired and path == receipt and observed_step == step:
                        fired = True
                        raise SyntheticAtomicCrash(step)

                arguments = {
                    "project_root": root,
                    "qualification_transaction_receipt_path": fixture.transaction_path,
                    "output_dir": output,
                    "acceptance_loader": fixture.acceptance_loader,
                    "expected_preprocessing_contract_sha256": semantic_sha(
                        fixture.contract
                    ),
                }
                with self.assertRaises(SyntheticAtomicCrash):
                    target.materialize_guardian_preprocessing_contract_v1(
                        **arguments,
                        after_physical_commit_step=crash,
                    )
                self.assertTrue(fired)
                published_identity = (
                    (receipt.stat().st_dev, receipt.stat().st_ino)
                    if step == "post_publish_pre_parent_fsync"
                    else None
                )
                result = target.materialize_guardian_preprocessing_contract_v1(
                    **arguments
                )
                self.assertEqual(Path(result["receipt_path"]), receipt)
                self.assertEqual(
                    {path.name for path in output.iterdir()},
                    {target.CONTRACT_FILENAME, target.RECEIPT_FILENAME},
                )
                if published_identity is not None:
                    self.assertEqual(
                        (receipt.stat().st_dev, receipt.stat().st_ino),
                        published_identity,
                    )


if __name__ == "__main__":
    unittest.main()
