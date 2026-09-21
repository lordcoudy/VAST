from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_resource_qualification as qualification  # noqa: E402
import full_resource_qualification_index_v1 as target  # noqa: E402
from tests.test_full_resource_qualification import (  # noqa: E402
    _datasets,
    _fake_pilot_validator,
)


SYSTEMS = qualification.SYSTEMS
RESOURCES = qualification.RESOURCES
CODECS = qualification.CODECS
TOPOLOGIES = qualification.TOPOLOGIES


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def execution_closure(
    root: Path, pilots: Path, fragments: dict[str, Path]
) -> tuple[Path, object]:
    path = root / "execution-closure/qualification_execution_closure.v1.receipt.json"
    write_json(path, {"fixture": "execution-closure-v1"})

    def loader(*, project_root: Path, receipt_path: Path) -> dict:
        return {
            "receipt_descriptor": descriptor(project_root, Path(receipt_path)),
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
                        system: descriptor(project_root, fragment)
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


def fake_fragment_validator(system: str, path: Path, project_root: Path) -> dict:
    del project_root
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("system") != system:
        raise RuntimeError("fragment system drift")
    return value


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        scripts = root / "scripts"
        scripts.mkdir(parents=True)
        self.full_validator = scripts / "full_resource_contract.py"
        self.interval_validator = scripts / "resource_interval_contract.py"
        self.full_validator.write_text("FULL_RESOURCE_CONTRACT_VERSION = 2\n", encoding="utf-8")
        self.interval_validator.write_text("RESOURCE_INTERVAL_CONTRACT_VERSION = 2\n", encoding="utf-8")
        dataset = root / "configs/datasets.yaml"
        dataset.parent.mkdir(parents=True)
        dataset.write_text("schema_version: 1\ndatasets: {}\n", encoding="utf-8")
        shared = root / "native"
        shared.mkdir()
        self.interval_emitter = shared / "checkpoint_resource_interval_emitter.hpp"
        self.hardware_collector = shared / "collect_metrics.py"
        self.interval_emitter.write_text("// native interval + fanout emitter\n", encoding="utf-8")
        self.hardware_collector.write_text("# native hardware collector\n", encoding="utf-8")
        self.fragments = self._fragments()
        self.pilot_root = self._pilots()

    def _fragments(self) -> dict[str, Path]:
        fragments: dict[str, Path] = {}
        for system_index, system in enumerate(SYSTEMS, start=1):
            rows = []
            for resource_index, resource in enumerate(RESOURCES, start=1):
                stem = f"{system}-{resource}"
                runtime_identity = {
                    "runtime_backend": f"{system}-native-runtime-v3",
                    "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
                    "decoder_device_api": "NVIDIA_NVDEC",
                    "worker_image_digest": "sha256:" + f"{system_index * 10 + resource_index:064x}",
                    "implementation_version": f"{stem}-resource-v2-v1",
                    "hardware_binding_id": "nvidia-gpu:frozen-qualification-host-v1",
                }
                binding = {
                    "schema_version": 1,
                    "artifact_kind": f"vast_{system}_resource_binding_material_v1",
                    "system": system,
                    "branch": "all_branches",
                    "resource": resource,
                    "role": "resource",
                    "implementation_id": f"{stem}-resource-v2-implementation-v1",
                    "emitter_id": f"{stem}-native-resource-v2-emitter-v1",
                    "runtime_identity": runtime_identity,
                    "resource_v2_evidence": {
                        "contract_version": 2,
                        "publication_scope": qualification.PUBLICATION_SCOPE,
                        "full_resource_validator": descriptor(self.root, self.full_validator),
                        "interval_validator": descriptor(self.root, self.interval_validator),
                        "native_emitters": {
                            "cuda_transfer_intervals": descriptor(self.root, self.interval_emitter),
                            "nvdec_intervals": descriptor(self.root, self.interval_emitter),
                            "fanout_intervals": descriptor(self.root, self.interval_emitter),
                            "fanout_work_counters": descriptor(self.root, self.interval_emitter),
                            "hardware_resource_samples": descriptor(self.root, self.hardware_collector),
                        },
                    },
                }
                binding_path = self.root / f"artifacts/{system}/bindings/resource/{resource}.binding.json"
                write_json(binding_path, binding)
                item = descriptor(self.root, binding_path)
                rows.append(
                    {
                        "role": "resource",
                        "branch": "all_branches",
                        "resource": resource,
                        "path": item["path"],
                        "size": item["size_bytes"],
                        "sha256": item["sha256"],
                        "implementation_id": binding["implementation_id"],
                        "emitter_id": binding["emitter_id"],
                        "runtime_identity": runtime_identity,
                    }
                )
            fragment = {
                "schema_version": 1,
                "artifact_kind": "vast_publication_qualification_system_fragment_v1",
                "system": system,
                "policy_bindings": [],
                "resource_bindings": rows,
                "pilots": [],
            }
            path = self.root / f"artifacts/{system}/qualification_fragment.json"
            write_json(path, fragment)
            fragments[system] = path
        return fragments

    def _pilots(self) -> Path:
        pilot_root = self.root / "pilots"
        for system in SYSTEMS:
            for resource in RESOURCES:
                for codec in CODECS:
                    for topology in TOPOLOGIES:
                        arm = pilot_root / system / resource / codec / topology
                        arm.mkdir(parents=True)
                        for role, filename in target.PILOT_EVIDENCE_FILENAMES.items():
                            (arm / filename).write_text(
                                f"{role}:{system}:{resource}:{codec}:{topology}\n",
                                encoding="utf-8",
                            )
        return pilot_root


class SyntheticAtomicCrash(BaseException):
    pass


class FullResourceQualificationIndexV1Tests(unittest.TestCase):
    def test_builds_exact_index_from_fragments_and_reuses_the_same_32_pilots(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            closure, closure_loader = execution_closure(
                root, fixture.pilot_root, fixture.fragments
            )
            output = root / "qualification/full-resource-index.v1.json"
            output.parent.mkdir(parents=True)
            result = target.build_full_resource_qualification_index_v1(
                project_root=root,
                fragment_paths=fixture.fragments,
                pilot_root=fixture.pilot_root,
                output_path=output,
                fragment_validator=fake_fragment_validator,
                execution_closure_receipt_path=closure,
                execution_closure_loader=closure_loader,
            )
            index = json.loads(result.read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(len(index["bindings"]), 8)
            self.assertEqual(len(index["pilots"]), 32)
            self.assertEqual(
                index["qualification_execution_closure"], descriptor(root, closure)
            )
            interval_paths = {
                row["emitters"]["resource_intervals"]["artifact"]["path"]
                for row in index["bindings"]
            }
            self.assertEqual(interval_paths, {"native/checkpoint_resource_interval_emitter.hpp"})

            with mock.patch.object(
                qualification, "_load_and_verify_kpp_datasets", return_value=_datasets()
            ), mock.patch.object(
                qualification,
                "_load_execution_closure",
                side_effect=closure_loader,
            ):
                assessment = qualification.assess_full_resource_qualification(
                    project_root=root,
                    index_path=result,
                    pilot_validator=_fake_pilot_validator,
                )
            self.assertTrue(assessment["passed"], assessment["blockers"])
            self.assertEqual(assessment["coverage"]["pilot_cell_count"], 32)

            missing_closure = root / "qualification/missing-closure-index.json"
            unbound = dict(index)
            unbound.pop("qualification_execution_closure")
            write_json(missing_closure, unbound)
            rejected = qualification.assess_full_resource_qualification(
                project_root=root,
                index_path=missing_closure,
                pilot_validator=_fake_pilot_validator,
            )
            self.assertFalse(rejected["passed"])
            with self.assertRaises(qualification.FullResourceQualificationError):
                qualification.promote_full_resource_qualification(
                    project_root=root,
                    index_path=missing_closure,
                    output_dir=root / "must-not-promote",
                )
            self.assertFalse((root / "must-not-promote").exists())

    def test_missing_pilot_and_fragment_descriptor_drift_fail_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            missing = next(fixture.pilot_root.rglob("frames.csv"))
            missing.unlink()
            closure, closure_loader = execution_closure(
                root, fixture.pilot_root, fixture.fragments
            )
            output = root / "missing.json"
            with self.assertRaisesRegex(target.FullResourceQualificationIndexV1Error, "pilot evidence"):
                target.build_full_resource_qualification_index_v1(
                    project_root=root,
                    fragment_paths=fixture.fragments,
                    pilot_root=fixture.pilot_root,
                    output_path=output,
                    fragment_validator=fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )
            self.assertFalse(output.exists())

            fixture = Fixture(root / "second")
            closure, closure_loader = execution_closure(
                root / "second", fixture.pilot_root, fixture.fragments
            )
            fragment_path = fixture.fragments["deepstream"]
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["resource_bindings"][0]["sha256"] = "0" * 64
            write_json(fragment_path, fragment)
            output = root / "second/drift.json"
            with self.assertRaisesRegex(target.FullResourceQualificationIndexV1Error, "binding"):
                target.build_full_resource_qualification_index_v1(
                    project_root=root / "second",
                    fragment_paths=fixture.fragments,
                    pilot_root=fixture.pilot_root,
                    output_path=output,
                    fragment_validator=fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )
            self.assertFalse(output.exists())

    def test_same_bytes_from_a_different_fragment_path_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            closure, closure_loader = execution_closure(
                root, fixture.pilot_root, fixture.fragments
            )
            alternate = root / "alternate/deepstream-fragment.json"
            alternate.parent.mkdir(parents=True)
            alternate.write_bytes(fixture.fragments["deepstream"].read_bytes())
            supplied = dict(fixture.fragments)
            supplied["deepstream"] = alternate
            output = root / "must-not-commit.json"

            with self.assertRaisesRegex(
                target.FullResourceQualificationIndexV1Error,
                "transaction fragment binding",
            ):
                target.build_full_resource_qualification_index_v1(
                    project_root=root,
                    fragment_paths=supplied,
                    pilot_root=fixture.pilot_root,
                    output_path=output,
                    fragment_validator=fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )
            self.assertFalse(output.exists())

    def test_commit_is_idempotent_and_rejects_conflict_dangling_and_hardlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            closure, closure_loader = execution_closure(
                root, fixture.pilot_root, fixture.fragments
            )

            def build(output: Path) -> Path:
                return target.build_full_resource_qualification_index_v1(
                    project_root=root,
                    fragment_paths=fixture.fragments,
                    pilot_root=fixture.pilot_root,
                    output_path=output,
                    fragment_validator=fake_fragment_validator,
                    execution_closure_receipt_path=closure,
                    execution_closure_loader=closure_loader,
                )

            frozen = root / "frozen/full-resource-index.json"
            first = build(frozen)
            frozen_bytes = first.read_bytes()
            self.assertEqual(build(frozen), first)
            self.assertEqual(first.read_bytes(), frozen_bytes)

            conflict = root / "conflict/full-resource-index.json"
            conflict.parent.mkdir()
            conflict.write_text("foreign\n", encoding="ascii")
            with self.assertRaisesRegex(
                target.FullResourceQualificationIndexV1Error, "collision"
            ):
                build(conflict)
            self.assertEqual(conflict.read_text(encoding="ascii"), "foreign\n")

            dangling = root / "dangling/full-resource-index.json"
            dangling.parent.mkdir()
            dangling.symlink_to(root / "missing-target")
            with self.assertRaisesRegex(
                target.FullResourceQualificationIndexV1Error, "collision"
            ):
                build(dangling)
            self.assertTrue(dangling.is_symlink())

            hardlinked = root / "hardlinked/full-resource-index.json"
            hardlinked.parent.mkdir()
            hardlinked.hardlink_to(frozen)
            with self.assertRaisesRegex(
                target.FullResourceQualificationIndexV1Error, "collision"
            ):
                build(hardlinked)
            self.assertGreater(hardlinked.stat().st_nlink, 1)

    def test_execution_closure_is_mandatory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            with self.assertRaisesRegex(
                target.FullResourceQualificationIndexV1Error, "execution closure"
            ):
                target.build_full_resource_qualification_index_v1(
                    project_root=root,
                    fragment_paths=fixture.fragments,
                    pilot_root=fixture.pilot_root,
                    output_path=root / "must-not-exist.json",
                    fragment_validator=fake_fragment_validator,
                )

    def test_index_recovers_every_atomic_physical_window_same_path(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = Fixture(root)
                closure, closure_loader = execution_closure(
                    root, fixture.pilot_root, fixture.fragments
                )
                output = root / "atomic/full-resource-index.v1.json"
                fired = False

                def crash(observed_step: str, path: Path) -> None:
                    nonlocal fired
                    if not fired and path == output and observed_step == step:
                        fired = True
                        raise SyntheticAtomicCrash(step)

                arguments = {
                    "project_root": root,
                    "fragment_paths": fixture.fragments,
                    "pilot_root": fixture.pilot_root,
                    "output_path": output,
                    "fragment_validator": fake_fragment_validator,
                    "execution_closure_receipt_path": closure,
                    "execution_closure_loader": closure_loader,
                }
                with self.assertRaises(SyntheticAtomicCrash):
                    target.build_full_resource_qualification_index_v1(
                        **arguments,
                        after_physical_commit_step=crash,
                    )
                self.assertTrue(fired)
                published_identity = (
                    (output.stat().st_dev, output.stat().st_ino)
                    if step == "post_publish_pre_parent_fsync"
                    else None
                )
                self.assertEqual(
                    target.build_full_resource_qualification_index_v1(**arguments),
                    output,
                )
                if published_identity is not None:
                    self.assertEqual(
                        (output.stat().st_dev, output.stat().st_ino),
                        published_identity,
                    )


if __name__ == "__main__":
    unittest.main()
