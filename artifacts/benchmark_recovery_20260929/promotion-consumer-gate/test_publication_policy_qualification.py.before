from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification as target  # noqa: E402


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _descriptor(root: Path, path: Path) -> dict:
    return {"path": path.relative_to(root).as_posix(), "size_bytes": path.stat().st_size, "sha256": _sha(path)}


class _PolicyApi:
    PUBLISHABLE_SYSTEMS = SYSTEMS
    ANALYTICS_BRANCHES = BRANCHES
    RESOURCES = RESOURCES
    POLICY_SCOPE = "analytics_only"
    MIN_CALIBRATION_SAMPLES = 30

    @staticmethod
    def policy_contract_identity() -> dict:
        return {"schema_version": 1, "sha256": "a" * 64}

    @staticmethod
    def assess_capability_manifest(manifest: dict) -> dict:
        implementation_ids = []
        emitter_ids = []
        for system in SYSTEMS:
            for branch in BRANCHES:
                for resource in RESOURCES:
                    binding = manifest["systems"][system]["branches"][branch][resource]
                    implementation_ids.append(binding["implementation_id"])
                    emitter_ids.append(binding["native_evidence"]["emitter_id"])
        passed = set(manifest["systems"]) == set(SYSTEMS) and len(set(implementation_ids)) == 32 and len(set(emitter_ids)) == 32
        return {"passed": passed, "blockers": [] if passed else ["fake_api_rejected"]}

    @staticmethod
    def validate_decision_record(record: dict, manifest: dict) -> dict:
        del record, manifest
        return {"passed": True, "blockers": []}


def _fixture(root: Path) -> tuple[Path, dict]:
    artifacts = root / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    dataset_manifest = root / "configs" / "datasets.yaml"
    dataset_manifest.parent.mkdir(parents=True, exist_ok=True)
    dataset_manifest.write_text("schema_version: 1\ndatasets: {}\n", encoding="utf-8")

    bindings = []
    for system in SYSTEMS:
        for branch in BRANCHES:
            for resource in RESOURCES:
                stem = f"{system}-{branch}-{resource}"
                implementation = artifacts / f"{stem}-implementation.bin"
                emitter = artifacts / f"{stem}-emitter.bin"
                implementation.write_bytes(f"implementation:{stem}".encode("ascii"))
                emitter.write_bytes(f"emitter:{stem}".encode("ascii"))
                bindings.append({
                    "system": system, "branch": branch, "resource": resource,
                    "implementation_id": f"{stem}-implementation-v1",
                    "implementation_artifact": _descriptor(root, implementation),
                    "emitter_id": f"{stem}-native-emitter-v1",
                    "emitter_artifact": _descriptor(root, emitter),
                    "runtime_binding": f"{system}:{branch}:{resource}:worker-v1",
                    "runtime_identity": {
                        "runtime_backend": f"{system}-{resource}-native-backend-v1",
                        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
                        "gpu_id": None if resource == "cpu" else 0,
                        "worker_image_digest": "sha256:" + f"{len(bindings) + 1:064x}",
                        "implementation_version": f"{system}-{branch}-{resource}-v1",
                        "terminal_detector": f"model-{system}-{branch}-{resource}-v1",
                        "terminal_backend": (
                            f"analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=CompiledModel;device=CPU:fixture-cpu"
                            if resource == "cpu"
                            else f"analytics-execution:tensorrt_cuda;runtime=TensorRT;native_api=enqueueV3;device=NVIDIA_CUDA:GPU-fixture"
                        ),
                    },
                })

    evidence_names = {
        "checkpoint_acceptance": "checkpoint_qualification_pilot_acceptance.json",
        "policy_decisions_jsonl": "publication_policy_decisions.jsonl",
        "resource_intervals": "resource_intervals.csv",
        "ingress_ledger": "ingress_ledger.csv",
        "topology_events": "topology_events.csv",
        "frames": "frames.csv",
        "frame_events": "frame_events.csv",
        "branch_terminals": "branch_terminals.csv",
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
                        path.write_text(f"{role}:{system}:{resource}:{codec}:{topology}\n", encoding="utf-8")
                        evidence[role] = _descriptor(root, path)
                    pilots.append({"system": system, "resource": resource, "codec": codec, "topology_kind": topology, "evidence": evidence})

    index = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_qualification_index",
        "policy_contract_sha256": "a" * 64,
        "dataset_manifest": _descriptor(root, dataset_manifest),
        "bindings": bindings,
        "pilots": pilots,
    }
    index_path = root / "qualification-index.json"
    index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
    return index_path, index


def _fragment_bound_fixture(root: Path) -> tuple[Path, dict]:
    index_path, index = _fixture(root)
    fragment_bound = []
    for system in SYSTEMS:
        source_rows = [row for row in index["bindings"] if row["system"] == system]
        policy_rows = []
        for row in source_rows:
            artifact = row["implementation_artifact"]
            policy_rows.append({
                "role": "policy",
                "branch": row["branch"],
                "resource": row["resource"],
                "path": artifact["path"],
                "size": artifact["size_bytes"],
                "sha256": artifact["sha256"],
                "implementation_id": row["implementation_id"],
                "emitter_id": row["emitter_id"],
                "runtime_identity": copy.deepcopy(row["runtime_identity"]),
            })
        fragment = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_qualification_system_fragment_v1",
            "system": system,
            "policy_bindings": policy_rows,
            "resource_bindings": [],
            "pilots": [],
        }
        fragment_path = root / "artifacts" / f"{system}-qualification-fragment.json"
        fragment_path.write_text(json.dumps(fragment, sort_keys=True) + "\n", encoding="utf-8")
        fragment_descriptor = _descriptor(root, fragment_path)
        for row in source_rows:
            binding_artifact = copy.deepcopy(row["implementation_artifact"])
            fragment_bound.append({
                "system": row["system"],
                "branch": row["branch"],
                "resource": row["resource"],
                "implementation_id": row["implementation_id"],
                "emitter_id": row["emitter_id"],
                "binding_artifact": binding_artifact,
                "fragment_artifact": copy.deepcopy(fragment_descriptor),
                "runtime_binding": (
                    f"{row['system']}:{row['branch']}:{row['resource']}:"
                    f"fragment-v1:{binding_artifact['sha256']}"
                ),
                "runtime_identity": copy.deepcopy(row["runtime_identity"]),
            })
    index["schema_version"] = 2
    index["bindings"] = fragment_bound
    index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
    return index_path, index


def _fake_fragment_validator(system: str, fragment_path: Path, project_root: Path) -> dict:
    del project_root
    value = json.loads(fragment_path.read_text(encoding="utf-8"))
    if value.get("system") != system:
        raise target.QualificationError("fake fragment system drift")
    return value


def _fake_pilot_validator(pilot: dict, context: dict) -> list[dict]:
    del context
    rows = []
    cell = "-".join((pilot["system"], pilot["resource"], pilot["codec"], pilot["topology_kind"]))
    for branch_index, branch in enumerate(BRANCHES, start=1):
        for sample in range(30):
            rows.append({
                "system": pilot["system"], "resource": pilot["resource"], "codec": pilot["codec"],
                "topology_kind": pilot["topology_kind"], "branch": branch,
                "decision_id": f"decision-{cell}-{branch}-{sample:03d}",
                "trace_id": f"trace-{cell}-{branch}-{sample:03d}",
                "service_ms": float(branch_index + sample / 100.0),
                "transfer_ms": 0.0 if pilot["resource"] == "cpu" else 0.5,
            })
    return rows


def _attach_fake_execution_closure(root: Path, index: dict) -> dict:
    closure_path = root / "qualification-execution-closure.v1.receipt.json"
    closure_path.write_text("{}\n", encoding="utf-8")
    descriptor = _descriptor(root, closure_path)
    index["qualification_execution_closure"] = copy.deepcopy(descriptor)
    return {
        "receipt_descriptor": descriptor,
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
            "pilot_execution": {"cells": [{} for _ in range(32)]},
        },
    }


def _completed_v2_fixture(root: Path) -> tuple[Path, dict]:
    index_path, index = _fragment_bound_fixture(root)
    _attach_fake_execution_closure(root, index)
    index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
    return index_path, index


def _fake_execution_closure_loader(
    *, project_root: Path, receipt_path: Path
) -> dict:
    descriptor = _descriptor(project_root, Path(receipt_path))
    return {
        "receipt_descriptor": descriptor,
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
            "pilot_execution": {"cells": [{} for _ in range(32)]},
        },
    }


class SyntheticAtomicCrash(BaseException):
    pass


class PublicationPolicyQualificationTests(unittest.TestCase):
    def test_active_publication_dataset_ids_are_kpp_iss_v3(self) -> None:
        self.assertEqual(
            target.KPP_DATASET_BY_CODEC,
            {
                "h264": "kpp_iss_publication_v3_h264",
                "h265": "kpp_iss_publication_v3_h265",
            },
        )

    def _assess(
        self,
        root: Path,
        index_path: Path,
        validator=_fake_pilot_validator,
    ) -> dict:
        with (
            mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
            mock.patch.object(
                target,
                "_load_execution_closure",
                side_effect=_fake_execution_closure_loader,
            ),
        ):
            return target.assess_policy_qualification(
                project_root=root,
                index_path=index_path,
                pilot_validator=validator,
                fragment_validator=_fake_fragment_validator,
            )

    def test_complete_matrix_is_pure_and_derives_manifest_and_balanced_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _completed_v2_fixture(root)
            assessment = self._assess(root, index_path)
            self.assertTrue(assessment["passed"], assessment["blockers"])
            self.assertEqual(assessment["coverage"]["binding_count"], 32)
            self.assertEqual(assessment["coverage"]["pilot_cell_count"], 32)
            self.assertEqual(assessment["coverage"]["accepted_sample_count"], 3840)
            row = assessment["calibration_mapping"]["calibrations"]["deepstream"]["costs"]["plate_number"]["gpu"]
            self.assertEqual(row["samples"], 120)
            self.assertAlmostEqual(row["service_ms"], 1.145)
            self.assertEqual(row["transfer_ms"], 0.5)
            binding = assessment["capability_manifest"]["systems"]["deepstream"]["branches"]["plate_number"]["gpu"]
            self.assertEqual(
                set(binding["runtime_identity"]),
                {
                    "runtime_backend",
                    "device_api",
                    "gpu_id",
                    "worker_image_digest",
                    "implementation_version",
                    "terminal_detector",
                    "terminal_backend",
                },
            )
            for field, value in binding["runtime_identity"].items():
                self.assertEqual(binding[field], value)
            self.assertFalse((root / target.CAPABILITY_MANIFEST_FILENAME).exists())

    def test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _completed_v2_fixture(root)
            index["bindings"][0]["runtime_identity"].pop("terminal_backend")
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            missing = self._assess(root, index_path)
            self.assertFalse(missing["passed"])
            self.assertIn("runtime_identity fields", " ".join(missing["blockers"]))

            index_path, index = _completed_v2_fixture(root)
            cpu = next(item for item in index["bindings"] if item["resource"] == "cpu")
            cpu["runtime_identity"]["gpu_id"] = 0
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            mismatched = self._assess(root, index_path)
            self.assertFalse(mismatched["passed"])
            self.assertIn("CPU runtime identity", " ".join(mismatched["blockers"]))

            index_path, index = _completed_v2_fixture(root)
            cpu = next(item for item in index["bindings"] if item["resource"] == "cpu")
            cpu["runtime_identity"]["terminal_backend"] = (
                "analytics-execution:openvino_cpu;device=CPU"
            )
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            abbreviated = self._assess(root, index_path)
            self.assertFalse(abbreviated["passed"])
            self.assertIn("CPU runtime identity", " ".join(abbreviated["blockers"]))

    def test_schema_v2_derives_bindings_only_from_revalidated_system_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _fragment_bound_fixture(root)
            loaded_closure = _attach_fake_execution_closure(root, index)
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            with (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    return_value=loaded_closure,
                ),
            ):
                assessment = target.assess_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertTrue(assessment["passed"], assessment["blockers"])
            binding = assessment["capability_manifest"]["systems"]["deepstream"][
                "branches"
            ]["plate_number"]["cpu"]
            source = next(
                row for row in index["bindings"]
                if (row["system"], row["branch"], row["resource"])
                == ("deepstream", "plate_number", "cpu")
            )
            self.assertEqual(binding["implementation_sha256"], source["binding_artifact"]["sha256"])
            self.assertEqual(binding["native_evidence"]["emitter_sha256"], source["binding_artifact"]["sha256"])

            drifted = copy.deepcopy(index)
            row = next(
                value for value in drifted["bindings"]
                if (value["system"], value["branch"], value["resource"])
                == ("savant", "damage", "gpu")
            )
            row["emitter_id"] += "-relabelled"
            index_path.write_text(json.dumps(drifted, sort_keys=True) + "\n", encoding="utf-8")
            with (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    return_value=loaded_closure,
                ),
            ):
                rejected = target.assess_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse(rejected["passed"])
            self.assertIn("fragment policy binding drift", " ".join(rejected["blockers"]))

    def test_completed_legacy_schema_or_missing_closure_cannot_be_assessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _completed_v2_fixture(root)

            legacy = copy.deepcopy(index)
            legacy["schema_version"] = 1
            index_path.write_text(
                json.dumps(legacy, sort_keys=True) + "\n", encoding="utf-8"
            )
            rejected_legacy = self._assess(root, index_path)
            self.assertFalse(rejected_legacy["passed"])
            self.assertIn("schema/fields", " ".join(rejected_legacy["blockers"]))

            missing = copy.deepcopy(index)
            missing.pop("qualification_execution_closure")
            index_path.write_text(
                json.dumps(missing, sort_keys=True) + "\n", encoding="utf-8"
            )
            rejected_missing = self._assess(root, index_path)
            self.assertFalse(rejected_missing["passed"])
            self.assertIn("schema/fields", " ".join(rejected_missing["blockers"]))

    def test_missing_cell_duplicate_sample_and_hash_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _completed_v2_fixture(root)
            missing = copy.deepcopy(index)
            missing["pilots"].pop()
            index_path.write_text(json.dumps(missing, sort_keys=True) + "\n", encoding="utf-8")
            result = self._assess(root, index_path)
            self.assertFalse(result["passed"])
            self.assertIn("pilot_cell_set_mismatch", " ".join(result["blockers"]))
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")

            def duplicate_validator(pilot: dict, context: dict) -> list[dict]:
                rows = _fake_pilot_validator(pilot, context)
                rows[1]["decision_id"] = rows[0]["decision_id"]
                return rows

            duplicate = self._assess(root, index_path, duplicate_validator)
            self.assertFalse(duplicate["passed"])
            self.assertIn("duplicate", " ".join(duplicate["blockers"]))
            artifact = root / index["bindings"][0]["binding_artifact"]["path"]
            artifact.write_bytes(b"drift")
            drift = self._assess(root, index_path)
            self.assertFalse(drift["passed"])
            self.assertIn("artifact", " ".join(drift["blockers"]))

    def test_duplicate_and_hardlink_artifact_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _completed_v2_fixture(root)
            index["bindings"][1]["binding_artifact"] = copy.deepcopy(
                index["bindings"][0]["binding_artifact"]
            )
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            duplicate = self._assess(root, index_path)
            self.assertFalse(duplicate["passed"])
            self.assertIn("alias", " ".join(duplicate["blockers"]))

            index_path, index = _completed_v2_fixture(root)
            source = root / index["bindings"][0]["binding_artifact"]["path"]
            alias = source.with_name("hardlink-alias.bin")
            try:
                os.link(source, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            index["bindings"][0]["binding_artifact"] = _descriptor(root, alias)
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            hardlink = self._assess(root, index_path)
            self.assertFalse(hardlink["passed"])
            self.assertIn("hardlink", " ".join(hardlink["blockers"]))

    def test_default_validator_rejects_self_declared_fake_acceptance_before_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _completed_v2_fixture(root)
            with (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
            ):
                result = target.assess_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse(result["passed"])
            self.assertIn("checkpoint acceptance", " ".join(result["blockers"]))

    def test_default_validator_uses_exact_policy_aware_acceptance_set(self) -> None:
        import inspect

        source = inspect.getsource(target._default_pilot_validator)
        self.assertIn(
            "validate_checkpoint_qualification_pilot_acceptance_v1", source
        )
        self.assertNotIn(
            "validate_checkpoint_acceptance_metadata_binding_envelope", source
        )
        self.assertIn("accepted_arm_evidence_files", source)
        self.assertIn("expected_identity[\"policy\"]", source)
        self.assertIn('"contract_version": 2', source)
        self.assertNotIn("policy_feedback.csv", source)

    def test_promotion_writes_receipt_last_and_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _completed_v2_fixture(root)
            output = root / "promoted"
            with (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
            ):
                result = target.promote_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
                repeated = target.promote_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertTrue(result["passed"])
            self.assertEqual(result["receipt"], repeated["receipt"])
            receipt = json.loads((output / target.QUALIFICATION_RECEIPT_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "accepted_evidence_driven_policy_qualification")
            for role in ("capability_manifest", "calibration_mapping"):
                path = output / receipt["outputs"][role]["path"]
                self.assertEqual(_sha(path), receipt["outputs"][role]["sha256"])
                self.assertEqual(path.stat().st_mode & 0o777, 0o444)
            self.assertEqual(
                (output / target.QUALIFICATION_RECEIPT_FILENAME).stat().st_mode
                & 0o777,
                0o444,
            )
            capability_path = output / target.CAPABILITY_MANIFEST_FILENAME
            capability_path.chmod(0o600)
            capability_path.write_text("{}\n", encoding="utf-8")
            with (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
            ):
                with self.assertRaises(target.QualificationError):
                    target.promote_policy_qualification(
                        project_root=root,
                        index_path=index_path,
                        output_dir=output,
                        pilot_validator=_fake_pilot_validator,
                        fragment_validator=_fake_fragment_validator,
                    )

    def test_promotion_rejects_same_bytes_hardlink_no_overwrite_race_and_parent_symlink(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _completed_v2_fixture(root)
            output = root / "promoted"
            patches = (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
            )
            with patches[0], patches[1]:
                target.promote_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )

            capability = output / target.CAPABILITY_MANIFEST_FILENAME
            alias = output / "capability-hardlink.json"
            try:
                os.link(capability, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            try:
                with (
                    mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                    mock.patch.object(
                        target,
                        "_load_execution_closure",
                        side_effect=_fake_execution_closure_loader,
                    ),
                    self.assertRaisesRegex(
                        target.QualificationError, "collision|namespace"
                    ),
                ):
                    target.promote_policy_qualification(
                        project_root=root,
                        index_path=index_path,
                        output_dir=output,
                        pilot_validator=_fake_pilot_validator,
                        fragment_validator=_fake_fragment_validator,
                    )
            finally:
                alias.unlink()

            race_path = root / "race.json"
            race_value = {"stable": True}
            race_payload = target._canonical_bytes(race_value) + b"\n"
            race_path.write_bytes(race_payload)
            with (
                mock.patch.object(target.os.path, "lexists", return_value=False),
                self.assertRaisesRegex(target.QualificationError, "collision"),
            ):
                target._write_immutable_json(race_path, race_value)
            self.assertEqual(race_path.read_bytes(), race_payload)

            physical = root / "physical-output"
            physical.mkdir()
            linked = root / "linked-output"
            try:
                linked.symlink_to(physical, target_is_directory=True)
            except OSError:
                self.skipTest("directory symlinks are unavailable")
            with (
                mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
                self.assertRaises(target.QualificationError),
            ):
                target.promote_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=linked,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )

    def test_immutable_writer_accepts_only_completed_identical_concurrent_commit(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            value = {"stable": True}
            expected = target._canonical_bytes(value) + b"\n"
            identical = root / "identical.json"
            identical.write_bytes(expected)
            identical.chmod(0o444)
            descriptor = target._write_immutable_json(identical, value)
            self.assertEqual(descriptor["sha256"], _sha(identical))

            conflicting = root / "conflicting.json"
            conflicting.write_bytes(
                target._canonical_bytes({"stable": False}) + b"\n"
            )
            conflicting.chmod(0o444)
            before = conflicting.read_bytes()
            with self.assertRaisesRegex(target.QualificationError, "collision"):
                target._write_immutable_json(conflicting, value)
            self.assertEqual(conflicting.read_bytes(), before)

    def test_immutable_writer_waits_when_concurrent_leaf_is_already_visible(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            value = {"stable": True}
            stuck = root / "visible-foreign-partial.json"
            stuck.write_bytes(b"pending")
            stuck.chmod(0o600)
            with self.assertRaisesRegex(target.QualificationError, "collision"):
                target._write_immutable_json(stuck, value)
            self.assertEqual(stuck.read_bytes(), b"pending")

    def test_promotion_resumes_exact_prefix_after_pre_receipt_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _completed_v2_fixture(root)
            output = root / "promoted"
            immutable_writer = target._write_immutable_json

            def fail_before_receipt(
                path: Path, value: dict, **kwargs: object
            ) -> dict:
                if path.name == target.QUALIFICATION_RECEIPT_FILENAME:
                    raise target.QualificationError("injected pre-receipt failure")
                return immutable_writer(path, value, **kwargs)

            common = (
                mock.patch.object(
                    target, "_load_policy_contract", return_value=_PolicyApi
                ),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
            )
            with (
                common[0],
                common[1],
                mock.patch.object(
                    target, "_write_immutable_json", side_effect=fail_before_receipt
                ),
                self.assertRaisesRegex(target.QualificationError, "pre-receipt"),
            ):
                target.promote_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertEqual(
                set(entry.name for entry in output.iterdir()),
                {
                    target.CAPABILITY_MANIFEST_FILENAME,
                    target.CALIBRATION_MAPPING_FILENAME,
                },
            )
            with (
                mock.patch.object(
                    target, "_load_policy_contract", return_value=_PolicyApi
                ),
                mock.patch.object(
                    target,
                    "_load_execution_closure",
                    side_effect=_fake_execution_closure_loader,
                ),
            ):
                resumed = target.promote_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    output_dir=output,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertTrue(resumed["passed"])
            self.assertEqual(
                set(entry.name for entry in output.iterdir()),
                set(target._PROMOTION_FILE_SEQUENCE),
            )

    def test_promotion_receipt_recovers_every_atomic_physical_window(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                index_path, _ = _completed_v2_fixture(root)
                output = root / "atomic-promoted"
                receipt_path = output / target.QUALIFICATION_RECEIPT_FILENAME
                fired = False

                def crash(observed_step: str, path: Path) -> None:
                    nonlocal fired
                    if not fired and path == receipt_path and observed_step == step:
                        fired = True
                        raise SyntheticAtomicCrash(step)

                arguments = {
                    "project_root": root,
                    "index_path": index_path,
                    "output_dir": output,
                    "pilot_validator": _fake_pilot_validator,
                    "fragment_validator": _fake_fragment_validator,
                }
                with (
                    mock.patch.object(
                        target, "_load_policy_contract", return_value=_PolicyApi
                    ),
                    mock.patch.object(
                        target,
                        "_load_execution_closure",
                        side_effect=_fake_execution_closure_loader,
                    ),
                    self.assertRaises(SyntheticAtomicCrash),
                ):
                    target.promote_policy_qualification(
                        **arguments,
                        after_physical_commit_step=crash,
                    )
                self.assertTrue(fired)
                published_identity = (
                    (receipt_path.stat().st_dev, receipt_path.stat().st_ino)
                    if step == "post_publish_pre_parent_fsync"
                    else None
                )
                with (
                    mock.patch.object(
                        target, "_load_policy_contract", return_value=_PolicyApi
                    ),
                    mock.patch.object(
                        target,
                        "_load_execution_closure",
                        side_effect=_fake_execution_closure_loader,
                    ),
                ):
                    resumed = target.promote_policy_qualification(**arguments)
                self.assertTrue(resumed["passed"])
                if published_identity is not None:
                    self.assertEqual(
                        (receipt_path.stat().st_dev, receipt_path.stat().st_ino),
                        published_identity,
                    )


if __name__ == "__main__":
    unittest.main()
