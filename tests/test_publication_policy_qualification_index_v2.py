from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification as qualification  # noqa: E402
import publication_policy_qualification_index_v2 as target  # noqa: E402
from publication_physical_io_v1 import PhysicalRootCustodyV1  # noqa: E402
from tests.test_publication_policy_qualification import (  # noqa: E402
    SYSTEMS,
    _PolicyApi,
    _fake_fragment_validator,
    _fake_pilot_validator,
    _fragment_bound_fixture,
)


def _closure(
    root: Path, pilots: Path, fragments: dict[str, Path]
) -> tuple[Path, object]:
    path = root / "execution-closure/qualification_execution_closure.v1.receipt.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"fixture":"execution-closure-v1"}\n', encoding="ascii")

    def loader(*, project_root: Path, receipt_path: Path) -> dict:
        payload = Path(receipt_path).read_bytes()
        return {
            "receipt_descriptor": {
                "path": Path(receipt_path).relative_to(project_root).as_posix(),
                "size_bytes": len(payload),
                "sha256": __import__("hashlib").sha256(payload).hexdigest(),
            },
            "receipt": {
                "schema_version": 1,
                "artifact_kind": (
                    "vast_publication_policy_qualification_execution_closure_v1"
                ),
                "status": "qualification_execution_closed_nonpublication",
                "qualification_execution_complete": True,
                "accepted_for_full_publication": False,
                "publication_ready": False,
                "authorization_eligible": False,
                "qualification_input_transaction": {
                    "fragments": {
                        system: target._descriptor(
                            project_root,
                            fragment,
                            f"fixture {system} transaction fragment",
                        )
                        for system, fragment in fragments.items()
                    }
                },
                "pilot_execution": {
                    "pilot_root": {
                        "path": pilots.relative_to(project_root).as_posix(),
                        "cell_count": 32,
                    },
                    "cells": [{} for _ in range(32)],
                },
            },
        }

    return path, loader


class SyntheticAtomicCrash(BaseException):
    pass


class PublicationPolicyQualificationIndexV2Tests(unittest.TestCase):
    def test_drvfs_readonly_projection_accepts_0555_without_weakening_identity(self) -> None:
        root = Path("/project")
        path = root / "candidate.json"
        payload = b"{}\n"
        descriptor = {
            "path": "candidate.json",
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        identity = (119, 844424932099876)
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

        target._commit_or_adopt_output(
            custody,
            path,
            payload,
            label="qualification candidate",
        )

    def test_existing_drvfs_readonly_projection_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            path = root / "candidate.json"
            payload = b"{}\n"
            with PhysicalRootCustodyV1.open(root, label="test root") as custody:
                target._commit_or_adopt_output(
                    custody, path, payload, label="qualification candidate"
                )
                target._commit_or_adopt_output(
                    custody, path, payload, label="qualification candidate"
                )
                path.chmod(0o600)
                path.write_bytes(b'{"foreign":true}\n')
                with self.assertRaisesRegex(
                    target.PolicyQualificationIndexV2Error, "collision"
                ):
                    target._commit_or_adopt_output(
                        custody, path, payload, label="qualification candidate"
                    )

    def test_pilot_index_requires_distinct_qualification_acceptance_filename(self) -> None:
        self.assertEqual(
            target.PILOT_EVIDENCE_FILENAMES["checkpoint_acceptance"],
            "checkpoint_qualification_pilot_acceptance.json",
        )

    def _fixture(self, root: Path) -> tuple[dict[str, Path], Path]:
        _index_path, index = _fragment_bound_fixture(root)
        fragments = {}
        for system in SYSTEMS:
            row = next(value for value in index["bindings"] if value["system"] == system)
            fragments[system] = root / row["fragment_artifact"]["path"]
        return fragments, root / "pilots"

    def test_builds_nonaccepted_candidate_and_complete_fragment_bound_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            closure, closure_loader = _closure(root, pilots, fragments)
            output = root / "qualification-v2"
            result = target.build_policy_qualification_index_v2(
                project_root=root,
                fragment_paths=fragments,
                pilot_root=pilots,
                output_dir=output,
                policy=_PolicyApi,
                fragment_validator=_fake_fragment_validator,
                execution_closure_receipt_path=closure,
                execution_closure_loader=closure_loader,
            )
            candidate = json.loads(result["candidate_manifest_path"].read_text(encoding="utf-8"))
            receipt = json.loads(result["candidate_receipt_path"].read_text(encoding="utf-8"))
            index = json.loads(result["index_path"].read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(len(index["bindings"]), 32)
            self.assertEqual(len(index["pilots"]), 32)
            self.assertEqual(
                index["qualification_execution_closure"]["path"],
                closure.relative_to(root).as_posix(),
            )
            self.assertTrue(
                all(
                    pilot["evidence"]["checkpoint_acceptance"]["path"].endswith(
                        "/checkpoint_qualification_pilot_acceptance.json"
                    )
                    for pilot in index["pilots"]
                )
            )
            self.assertFalse(receipt["accepted"])
            self.assertFalse(receipt["publication_ready"])
            self.assertEqual(receipt["status"], "qualification_candidate_not_accepted")
            self.assertEqual(
                receipt["candidate_manifest"]["sha256"],
                target.sha256_file(result["candidate_manifest_path"]),
            )
            self.assertEqual(
                candidate["artifact_kind"],
                "vast_publication_policy_capability_manifest",
            )

            with mock.patch.object(
                qualification, "_load_policy_contract", return_value=_PolicyApi
            ), mock.patch.object(
                qualification,
                "_load_execution_closure",
                side_effect=closure_loader,
            ):
                assessment = qualification.assess_policy_qualification(
                    project_root=root,
                    index_path=result["index_path"],
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertTrue(assessment["passed"], assessment["blockers"])
            self.assertEqual(
                assessment["qualification_execution_closure"],
                index["qualification_execution_closure"],
            )

            missing_closure = root / "missing-closure-index.json"
            unbound = dict(index)
            unbound.pop("qualification_execution_closure")
            missing_closure.write_text(
                json.dumps(unbound, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="ascii",
            )
            with mock.patch.object(
                qualification, "_load_policy_contract", return_value=_PolicyApi
            ):
                rejected = qualification.assess_policy_qualification(
                    project_root=root,
                    index_path=missing_closure,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
                with self.assertRaises(qualification.QualificationError):
                    qualification.promote_policy_qualification(
                        project_root=root,
                        index_path=missing_closure,
                        output_dir=root / "must-not-promote",
                        pilot_validator=_fake_pilot_validator,
                        fragment_validator=_fake_fragment_validator,
                    )
            self.assertFalse(rejected["passed"])
            self.assertFalse((root / "must-not-promote").exists())

    def test_fragment_only_candidate_breaks_bootstrap_cycle_and_stays_nonaccepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, _pilots = self._fixture(root)
            result = target.build_policy_qualification_index_v2(
                project_root=root,
                fragment_paths=fragments,
                pilot_root=None,
                output_dir=root / "fragment-only-candidate",
                policy=_PolicyApi,
                fragment_validator=_fake_fragment_validator,
                execution_closure_receipt_path=None,
            )

            index = json.loads(result["index_path"].read_text(encoding="utf-8"))
            candidate = json.loads(
                result["candidate_manifest_path"].read_text(encoding="utf-8")
            )
            receipt = json.loads(
                result["candidate_receipt_path"].read_text(encoding="utf-8")
            )
            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(len(index["bindings"]), 32)
            self.assertEqual(index["pilots"], [])
            self.assertNotIn("qualification_execution_closure", index)
            self.assertEqual(
                receipt["scope"], "forced_resource_qualification_pilots_only"
            )
            self.assertFalse(receipt["accepted"])
            self.assertFalse(receipt["publication_ready"])
            self.assertIn(
                "requires_32_cell_native_pilot_validation_and_atomic_promotion",
                receipt["blockers"],
            )
            self.assertEqual(
                candidate["artifact_kind"],
                "vast_publication_policy_capability_manifest",
            )

            with mock.patch.object(
                qualification, "_load_policy_contract", return_value=_PolicyApi
            ):
                assessment = qualification.assess_policy_qualification(
                    project_root=root,
                    index_path=result["index_path"],
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse(assessment["passed"])
            self.assertIn("expected exactly 32 pilots", " ".join(assessment["blockers"]))

    def test_missing_pilot_evidence_and_fragment_drift_fail_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            missing = next(pilots.rglob("frames.csv"))
            missing.unlink()
            closure, closure_loader = _closure(root, pilots, fragments)
            with self.assertRaisesRegex(target.PolicyQualificationIndexV2Error, "pilot evidence"):
                target.build_policy_qualification_index_v2(
                    project_root=root,
                    fragment_paths=fragments,
                    pilot_root=pilots,
                    output_dir=root / "missing-output",
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )
            self.assertFalse((root / "missing-output").exists())

            fragments, pilots = self._fixture(root / "second")
            closure, closure_loader = _closure(root / "second", pilots, fragments)
            fragment = fragments["deepstream"]
            fragment.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(target.PolicyQualificationIndexV2Error, "fragment"):
                target.build_policy_qualification_index_v2(
                    project_root=root / "second",
                    fragment_paths=fragments,
                    pilot_root=pilots,
                    output_dir=root / "second" / "drift-output",
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )
            self.assertFalse((root / "second" / "drift-output").exists())

    def test_receipt_last_failure_is_safely_resumable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            closure, closure_loader = _closure(root, pilots, fragments)
            sentinel = root / "must-survive.txt"
            sentinel.write_text("workspace sentinel\n", encoding="utf-8")
            output = root / "qualification-v2"
            original_write = target._commit_or_adopt_output

            def fail_receipt(*args: object, **kwargs: object) -> None:
                path = args[1]
                if isinstance(path, Path) and path.name == target.CANDIDATE_RECEIPT_FILENAME:
                    raise target.PolicyQualificationIndexV2Error("injected receipt-last fault")
                original_write(*args, **kwargs)

            with mock.patch.object(target, "_commit_or_adopt_output", side_effect=fail_receipt):
                with self.assertRaisesRegex(
                    target.PolicyQualificationIndexV2Error,
                    "receipt-last fault",
                ):
                    target.build_policy_qualification_index_v2(
                        project_root=root,
                        fragment_paths=fragments,
                        pilot_root=pilots,
                        output_dir=output,
                        policy=_PolicyApi,
                        fragment_validator=_fake_fragment_validator,
                        execution_closure_receipt_path=closure,
                        execution_closure_loader=closure_loader,
                    )

            self.assertEqual(
                sentinel.read_text(encoding="utf-8"), "workspace sentinel\n"
            )
            self.assertTrue((output / target.INDEX_FILENAME).is_file())
            self.assertTrue((output / target.CANDIDATE_MANIFEST_FILENAME).is_file())
            self.assertFalse((output / target.CANDIDATE_RECEIPT_FILENAME).exists())

            resumed = target.build_policy_qualification_index_v2(
                project_root=root,
                fragment_paths=fragments,
                pilot_root=pilots,
                output_dir=output,
                policy=_PolicyApi,
                fragment_validator=_fake_fragment_validator,
                execution_closure_receipt_path=closure,
                execution_closure_loader=closure_loader,
            )
            self.assertTrue(resumed["candidate_receipt_path"].is_file())
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {
                    target.INDEX_FILENAME,
                    target.CANDIDATE_MANIFEST_FILENAME,
                    target.CANDIDATE_RECEIPT_FILENAME,
                },
            )

    def test_closure_rejects_same_bytes_from_a_different_fragment_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            closure, closure_loader = _closure(root, pilots, fragments)
            alternate = root / "alternate/deepstream-fragment.json"
            alternate.parent.mkdir(parents=True)
            alternate.write_bytes(fragments["deepstream"].read_bytes())
            supplied = dict(fragments)
            supplied["deepstream"] = alternate

            with self.assertRaisesRegex(
                target.PolicyQualificationIndexV2Error,
                "transaction fragment binding",
            ):
                target.build_policy_qualification_index_v2(
                    project_root=root,
                    fragment_paths=supplied,
                    pilot_root=pilots,
                    output_dir=root / "must-not-commit",
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )
            self.assertFalse((root / "must-not-commit").exists())

    def test_commit_is_idempotent_and_rejects_conflict_dangling_and_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            closure, closure_loader = _closure(root, pilots, fragments)

            def build(output: Path) -> dict[str, Path]:
                return target.build_policy_qualification_index_v2(
                    project_root=root,
                    fragment_paths=fragments,
                    pilot_root=pilots,
                    output_dir=output,
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )

            frozen = root / "frozen"
            first = build(frozen)
            first_bytes = {
                name: (frozen / name).read_bytes()
                for name in {
                    target.INDEX_FILENAME,
                    target.CANDIDATE_MANIFEST_FILENAME,
                    target.CANDIDATE_RECEIPT_FILENAME,
                }
            }
            second = build(frozen)
            self.assertEqual(first, second)
            self.assertEqual(
                first_bytes,
                {name: (frozen / name).read_bytes() for name in first_bytes},
            )

            conflict = root / "conflict"
            conflict.mkdir()
            conflict_leaf = conflict / target.INDEX_FILENAME
            conflict_leaf.write_text("foreign\n", encoding="ascii")
            with self.assertRaisesRegex(
                target.PolicyQualificationIndexV2Error, "collision"
            ):
                build(conflict)
            self.assertEqual(conflict_leaf.read_text(encoding="ascii"), "foreign\n")
            self.assertFalse((conflict / target.CANDIDATE_RECEIPT_FILENAME).exists())

            dangling = root / "dangling"
            dangling.mkdir()
            (dangling / target.INDEX_FILENAME).symlink_to(root / "missing-target")
            with self.assertRaisesRegex(
                target.PolicyQualificationIndexV2Error, "collision"
            ):
                build(dangling)
            self.assertTrue((dangling / target.INDEX_FILENAME).is_symlink())

            hardlinked = root / "hardlinked"
            hardlinked.mkdir()
            (hardlinked / target.INDEX_FILENAME).hardlink_to(
                frozen / target.INDEX_FILENAME
            )
            with self.assertRaisesRegex(
                target.PolicyQualificationIndexV2Error, "collision"
            ):
                build(hardlinked)
            self.assertGreater(
                (hardlinked / target.INDEX_FILENAME).stat().st_nlink,
                1,
            )

    def test_completed_index_requires_execution_closure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            with self.assertRaisesRegex(
                target.PolicyQualificationIndexV2Error, "execution closure"
            ):
                target.build_policy_qualification_index_v2(
                    project_root=root,
                    fragment_paths=fragments,
                    pilot_root=pilots,
                    output_dir=root / "must-not-exist",
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                )

    def test_candidate_receipt_recovers_every_atomic_physical_window(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fragments, pilots = self._fixture(root)
                closure, closure_loader = _closure(root, pilots, fragments)
                output = root / "atomic-candidate"
                fired = False

                def crash(observed_step: str, path: Path) -> None:
                    nonlocal fired
                    if (
                        not fired
                        and path.name == target.CANDIDATE_RECEIPT_FILENAME
                        and observed_step == step
                    ):
                        fired = True
                        raise SyntheticAtomicCrash(step)

                arguments = {
                    "project_root": root,
                    "fragment_paths": fragments,
                    "pilot_root": pilots,
                    "output_dir": output,
                    "policy": _PolicyApi,
                    "fragment_validator": _fake_fragment_validator,
                    "execution_closure_receipt_path": closure,
                    "execution_closure_loader": closure_loader,
                }
                with self.assertRaises(SyntheticAtomicCrash):
                    target.build_policy_qualification_index_v2(
                        **arguments,
                        after_physical_commit_step=crash,
                    )
                self.assertTrue(fired)
                receipt = output / target.CANDIDATE_RECEIPT_FILENAME
                published_identity = (
                    (receipt.stat().st_dev, receipt.stat().st_ino)
                    if step == "post_publish_pre_parent_fsync"
                    else None
                )
                result = target.build_policy_qualification_index_v2(**arguments)
                self.assertEqual(result["candidate_receipt_path"], receipt)
                if published_identity is not None:
                    self.assertEqual(
                        (receipt.stat().st_dev, receipt.stat().st_ino),
                        published_identity,
                    )
            self.assertFalse((root / "must-not-exist").exists())


if __name__ == "__main__":
    unittest.main()
