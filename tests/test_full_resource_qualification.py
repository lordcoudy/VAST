from __future__ import annotations

import copy
import hashlib
import json
import os
import inspect
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_resource_qualification as target  # noqa: E402


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _descriptor(root: Path, path: Path) -> dict:
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": _sha(path),
    }


def _datasets() -> dict:
    return {
        codec: {
            "dataset_name": f"kpp_real_{codec}",
            "manifest_identity_sha256": ("1" if codec == "h264" else "2") * 64,
            "source_sha256": [
                ("3" if codec == "h264" else "5") * 64,
                ("4" if codec == "h264" else "6") * 64,
            ],
            "annotation_sha256": "7" * 64,
        }
        for codec in CODECS
    }


def _fixture(root: Path) -> tuple[Path, dict]:
    scripts = root / "scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    full_validator = scripts / "full_resource_contract.py"
    interval_validator = scripts / "resource_interval_contract.py"
    full_validator.write_text("FULL_RESOURCE_CONTRACT_VERSION = 2\n", encoding="utf-8")
    interval_validator.write_text("RESOURCE_INTERVAL_CONTRACT_VERSION = 2\n", encoding="utf-8")
    dataset_manifest = root / "configs" / "datasets.yaml"
    dataset_manifest.parent.mkdir(parents=True, exist_ok=True)
    dataset_manifest.write_text("schema_version: 1\ndatasets: {}\n", encoding="utf-8")

    bindings = []
    artifacts = root / "artifacts"
    artifacts.mkdir(exist_ok=True)
    emitter_roles = (
        "resource_intervals",
        "hardware_resource_samples",
        "fanout_work_counters",
    )
    for system in SYSTEMS:
        for resource in RESOURCES:
            stem = f"{system}-{resource}"
            implementation = artifacts / f"{stem}-implementation.bin"
            implementation.write_bytes(f"implementation:{stem}".encode("ascii"))
            emitters = {}
            for role in emitter_roles:
                path = artifacts / f"{stem}-{role}-emitter.bin"
                path.write_bytes(f"emitter:{stem}:{role}".encode("ascii"))
                emitters[role] = {
                    "emitter_id": f"{stem}-{role}-native-emitter-v1",
                    "artifact": _descriptor(root, path),
                }
            bindings.append({
                "system": system,
                "resource": resource,
                "implementation_id": f"{stem}-resource-v2-implementation-v1",
                "implementation_artifact": _descriptor(root, implementation),
                "runtime_binding": f"{stem}:native-resource-v2-runtime-v1",
                "runtime_identity": {
                    "runtime_backend": f"{system}-native-runtime-v1",
                    "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
                    "decoder_device_api": "NVIDIA_NVDEC",
                    "worker_image_digest": "sha256:" + f"{len(bindings) + 1:064x}",
                    "implementation_version": f"{stem}-resource-v2-v1",
                    "hardware_binding_id": "kpp-benchmark-host-gpu-binding-v1",
                },
                "emitters": emitters,
            })

    evidence_names = {
        "checkpoint_acceptance": "checkpoint_publication_acceptance.json",
        "frames": "frames.csv",
        "frame_events": "frame_events.csv",
        "ingress_ledger": "ingress_ledger.csv",
        "topology_events": "topology_events.csv",
        "resource_intervals": "resource_intervals.csv",
        "hardware_resource_samples": "hardware_resource_samples.csv",
        "fanout_work_counters": "fanout_work_counters.csv",
    }
    pilots = []
    for system in SYSTEMS:
        for resource in RESOURCES:
            for codec in CODECS:
                for topology in TOPOLOGIES:
                    arm = root / "pilots" / system / resource / codec / topology
                    arm.mkdir(parents=True, exist_ok=True)
                    evidence = {}
                    for role, filename in evidence_names.items():
                        path = arm / filename
                        path.write_text(
                            f"{role}:{system}:{resource}:{codec}:{topology}\n",
                            encoding="utf-8",
                        )
                        evidence[role] = _descriptor(root, path)
                    pilots.append({
                        "system": system,
                        "resource": resource,
                        "codec": codec,
                        "topology_kind": topology,
                        "evidence": evidence,
                    })

    index = {
        "schema_version": 1,
        "artifact_kind": "vast_pre_run_full_resource_qualification_index",
        "resource_contract": {
            "contract_version": 2,
            "publication_scope": "primary_architecture_full_resource_raw_evidence_v2",
            "full_resource_validator": _descriptor(root, full_validator),
            "interval_validator": _descriptor(root, interval_validator),
        },
        "dataset_manifest": _descriptor(root, dataset_manifest),
        "bindings": bindings,
        "pilots": pilots,
    }
    index_path = root / "full-resource-qualification-index.json"
    index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
    return index_path, index


def _fake_pilot_validator(pilot: dict, context: dict) -> dict:
    codec = pilot["codec"]
    topology = pilot["topology_kind"]
    cell = "-".join((pilot["system"], pilot["resource"], codec, topology))
    rows = []
    for sample in range(30):
        trace_id = f"trace-{cell}-{sample:03d}"
        for branch in BRANCHES:
            rows.append({
                "system": pilot["system"],
                "resource": pilot["resource"],
                "codec": codec,
                "topology_kind": topology,
                "branch": branch,
                "trace_id": trace_id,
                "stream_id": sample % 6,
                "frame_id": sample,
                "input_frame_key": f"input-{cell}-{sample:03d}",
            })
    shared = topology == "shared_video_dag"
    return {
        "system": pilot["system"],
        "resource": pilot["resource"],
        "codec": codec,
        "topology_kind": topology,
        "run_id": f"resource-pilot-{cell}",
        "dataset_name": f"kpp_real_{codec}",
        "source_sha256": context["datasets"][codec]["source_sha256"],
        "evidence_sha256": {
            role: descriptor["sha256"]
            for role, descriptor in pilot["evidence"].items()
        },
        "resource_summary": {
            "resource_contract_version": 2,
            "evidence_accepted": True,
            "publication_bundle_bound": True,
            "full_resource_coverage_complete": True,
            "nvdec_busy_equivalent_ns": 100,
            "nvdec_counter_scope": "device_sample",
            "fanout_thread_cpu_time_ns": 100 if shared else 0,
            "fanout_work_units": 30 if shared else 0,
            "fanout_counter_scope": "per_trace_resource_work",
        },
        "samples": rows,
    }


class FullResourceQualificationTests(unittest.TestCase):
    def _assess(self, root: Path, index_path: Path, validator=_fake_pilot_validator) -> dict:
        with mock.patch.object(target, "_load_and_verify_kpp_datasets", return_value=_datasets()):
            return target.assess_full_resource_qualification(
                project_root=root,
                index_path=index_path,
                pilot_validator=validator,
            )

    def test_complete_matrix_is_pure_and_separates_pre_run_from_per_arm_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _fixture(root)
            before = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            result = self._assess(root, index_path)
            after = sorted(path.relative_to(root).as_posix() for path in root.rglob("*"))
            self.assertTrue(result["passed"], result["blockers"])
            self.assertEqual(before, after)
            self.assertEqual(result["coverage"]["binding_count"], 8)
            self.assertEqual(result["coverage"]["pilot_cell_count"], 32)
            self.assertEqual(result["coverage"]["accepted_branch_sample_count"], 3840)
            manifest = result["capability_manifest"]
            self.assertEqual(manifest["artifact_kind"], "vast_pre_run_full_resource_capability_manifest")
            self.assertEqual(manifest["qualification_scope"], "pre_run_hardware_and_emitter_capability_only")
            self.assertTrue(manifest["post_run_per_arm_evidence"]["required"])
            self.assertFalse(manifest["post_run_per_arm_evidence"]["configuration_evidence_accepted_mutated"])

    def test_missing_cell_duplicate_sample_hash_drift_and_self_declaration_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _fixture(root)
            missing = copy.deepcopy(index)
            missing["pilots"].pop()
            index_path.write_text(json.dumps(missing, sort_keys=True) + "\n", encoding="utf-8")
            result = self._assess(root, index_path)
            self.assertFalse(result["passed"])
            self.assertIn("pilot_cell_set_mismatch", " ".join(result["blockers"]))

            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")

            def duplicate_validator(pilot: dict, context: dict) -> dict:
                value = _fake_pilot_validator(pilot, context)
                value["samples"][1] = copy.deepcopy(value["samples"][0])
                return value

            duplicate = self._assess(root, index_path, duplicate_validator)
            self.assertFalse(duplicate["passed"])
            self.assertIn("duplicate", " ".join(duplicate["blockers"]))

            artifact = root / index["bindings"][0]["implementation_artifact"]["path"]
            artifact.write_bytes(b"drift")
            drift = self._assess(root, index_path)
            self.assertFalse(drift["passed"])
            self.assertIn("drift", " ".join(drift["blockers"]))

            index_path, index = _fixture(root)
            index["pilots"][0]["evidence_accepted"] = True
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            declared = self._assess(root, index_path)
            self.assertFalse(declared["passed"])
            self.assertIn("fields drifted", " ".join(declared["blockers"]))

    def test_path_alias_hardlink_and_symlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _fixture(root)
            index["bindings"][1]["implementation_artifact"] = copy.deepcopy(
                index["bindings"][0]["implementation_artifact"]
            )
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            alias = self._assess(root, index_path)
            self.assertFalse(alias["passed"])
            self.assertIn("alias", " ".join(alias["blockers"]))

            index_path, index = _fixture(root)
            source = root / index["bindings"][0]["implementation_artifact"]["path"]
            hardlink = source.with_name("resource-hardlink.bin")
            try:
                os.link(source, hardlink)
            except OSError:
                self.skipTest("hard links are unavailable")
            index["bindings"][0]["implementation_artifact"] = _descriptor(root, hardlink)
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            linked = self._assess(root, index_path)
            self.assertFalse(linked["passed"])
            self.assertIn("hardlink", " ".join(linked["blockers"]))

            hardlink.unlink()
            index_path, index = _fixture(root)
            source = root / index["pilots"][0]["evidence"]["frames"]["path"]
            symlink = source.with_name("frames-link.csv")
            try:
                symlink.symlink_to(source)
            except OSError:
                self.skipTest("symbolic links are unavailable")
            index["pilots"][0]["evidence"]["frames"] = _descriptor(root, symlink)
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            linked = self._assess(root, index_path)
            self.assertFalse(linked["passed"])
            self.assertIn("symlink", " ".join(linked["blockers"]))

    def test_default_validator_rejects_self_declared_acceptance_before_heavy_validators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _fixture(root)
            with (
                mock.patch.object(target, "_load_and_verify_kpp_datasets", return_value=_datasets()),
                mock.patch.object(target, "_load_resource_validators", side_effect=AssertionError("too early")),
            ):
                result = target.assess_full_resource_qualification(
                    project_root=root,
                    index_path=index_path,
                )
            self.assertFalse(result["passed"])
            self.assertIn("checkpoint acceptance", " ".join(result["blockers"]))
            self.assertNotIn("too early", " ".join(result["blockers"]))

    def test_validator_contract_requires_policy_aware_hash_set_and_semantic_decisions(self) -> None:
        source = inspect.getsource(target._default_pilot_validator)
        self.assertIn('accepted_arm_evidence_files', source)
        self.assertIn('validate_frozen_policy_decisions', source)
        self.assertIn('publication_policy_decisions.jsonl', source)
        self.assertIn('require_online_policy_trace=(expected_policy == "adaptive_weights")', source)

    def test_promotion_writes_receipt_last_is_idempotent_and_rejects_collisions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _fixture(root)
            output = root / "promoted"
            writes = []
            immutable_writer = target._write_immutable_json

            def record_write(path: Path, value: dict) -> dict:
                writes.append(path.name)
                return immutable_writer(path, value)

            with (
                mock.patch.object(target, "_load_and_verify_kpp_datasets", return_value=_datasets()),
                mock.patch.object(target, "_default_pilot_validator", side_effect=_fake_pilot_validator),
                mock.patch.object(target, "_write_immutable_json", side_effect=record_write),
            ):
                result = target.promote_full_resource_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                )
                repeated = target.promote_full_resource_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                )
            self.assertEqual(result["receipt"], repeated["receipt"])
            self.assertEqual(
                writes,
                [
                    target.CAPABILITY_MANIFEST_FILENAME,
                    target.QUALIFICATION_RECEIPT_FILENAME,
                    target.CAPABILITY_MANIFEST_FILENAME,
                    target.QUALIFICATION_RECEIPT_FILENAME,
                ],
            )
            self.assertNotIn(
                "pilot_validator",
                inspect.signature(target.promote_full_resource_qualification).parameters,
            )
            receipt_path = output / target.QUALIFICATION_RECEIPT_FILENAME
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "accepted_pre_run_resource_capability_qualification")
            self.assertTrue(receipt["post_run_per_arm_evidence_required"])
            self.assertFalse(receipt["configuration_evidence_accepted_mutated"])
            unsigned = dict(receipt)
            claimed_sha = unsigned.pop("sha256")
            self.assertEqual(
                hashlib.sha256(
                    json.dumps(
                        unsigned,
                        sort_keys=True,
                        separators=(",", ":"),
                        ensure_ascii=True,
                        allow_nan=False,
                    ).encode("utf-8")
                ).hexdigest(),
                claimed_sha,
            )
            manifest_path = output / receipt["outputs"]["capability_manifest"]["path"]
            self.assertEqual(_sha(manifest_path), receipt["outputs"]["capability_manifest"]["sha256"])

            alias = output / "capability-manifest-hardlink.json"
            try:
                os.link(manifest_path, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            with (
                mock.patch.object(target, "_load_and_verify_kpp_datasets", return_value=_datasets()),
                mock.patch.object(target, "_default_pilot_validator", side_effect=_fake_pilot_validator),
            ):
                with self.assertRaisesRegex(
                    target.FullResourceQualificationError, "collision"
                ):
                    target.promote_full_resource_qualification(
                        project_root=root,
                        index_path=index_path,
                        output_dir=output,
                    )
            alias.unlink()

            manifest_path.write_text("{}\n", encoding="utf-8")
            with (
                mock.patch.object(target, "_load_and_verify_kpp_datasets", return_value=_datasets()),
                mock.patch.object(target, "_default_pilot_validator", side_effect=_fake_pilot_validator),
            ):
                with self.assertRaises(target.FullResourceQualificationError):
                    target.promote_full_resource_qualification(
                        project_root=root,
                        index_path=index_path,
                        output_dir=output,
                    )


if __name__ == "__main__":
    unittest.main()
