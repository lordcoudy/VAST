from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
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
                            f"analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=CompiledModel;device=CPU"
                            if resource == "cpu"
                            else f"analytics-execution:tensorrt_cuda;runtime=TensorRT;native_api=enqueueV3;device=NVIDIA_CUDA:0"
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


class PublicationPolicyQualificationTests(unittest.TestCase):
    def test_active_publication_dataset_ids_are_kpp_iss_v3(self) -> None:
        self.assertEqual(
            target.KPP_DATASET_BY_CODEC,
            {
                "h264": "kpp_iss_publication_v3_h264",
                "h265": "kpp_iss_publication_v3_h265",
            },
        )

    def _assess(self, root: Path, index_path: Path) -> dict:
        with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
            return target.assess_policy_qualification(project_root=root, index_path=index_path, pilot_validator=_fake_pilot_validator)

    def test_complete_matrix_is_pure_and_derives_manifest_and_balanced_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _fixture(root)
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
            index_path, index = _fixture(root)
            index["bindings"][0]["runtime_identity"].pop("terminal_backend")
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            missing = self._assess(root, index_path)
            self.assertFalse(missing["passed"])
            self.assertIn("runtime_identity fields", " ".join(missing["blockers"]))

            index_path, index = _fixture(root)
            cpu = next(item for item in index["bindings"] if item["resource"] == "cpu")
            cpu["runtime_identity"]["gpu_id"] = 0
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            mismatched = self._assess(root, index_path)
            self.assertFalse(mismatched["passed"])
            self.assertIn("CPU runtime identity", " ".join(mismatched["blockers"]))

    def test_schema_v2_derives_bindings_only_from_revalidated_system_fragments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _fragment_bound_fixture(root)
            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
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
            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
                rejected = target.assess_policy_qualification(
                    project_root=root,
                    index_path=index_path,
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse(rejected["passed"])
            self.assertIn("fragment policy binding drift", " ".join(rejected["blockers"]))

    def test_missing_cell_duplicate_sample_and_hash_drift_fail_closed(self) -> None:
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

            def duplicate_validator(pilot: dict, context: dict) -> list[dict]:
                rows = _fake_pilot_validator(pilot, context)
                rows[1]["decision_id"] = rows[0]["decision_id"]
                return rows

            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
                duplicate = target.assess_policy_qualification(project_root=root, index_path=index_path, pilot_validator=duplicate_validator)
            self.assertFalse(duplicate["passed"])
            self.assertIn("duplicate", " ".join(duplicate["blockers"]))
            artifact = root / index["bindings"][0]["implementation_artifact"]["path"]
            artifact.write_bytes(b"drift")
            drift = self._assess(root, index_path)
            self.assertFalse(drift["passed"])
            self.assertIn("artifact", " ".join(drift["blockers"]))

    def test_duplicate_and_hardlink_artifact_aliases_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, index = _fixture(root)
            index["bindings"][1]["emitter_artifact"] = copy.deepcopy(index["bindings"][0]["emitter_artifact"])
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            duplicate = self._assess(root, index_path)
            self.assertFalse(duplicate["passed"])
            self.assertIn("alias", " ".join(duplicate["blockers"]))

            index_path, index = _fixture(root)
            source = root / index["bindings"][0]["implementation_artifact"]["path"]
            alias = source.with_name("hardlink-alias.bin")
            try:
                os.link(source, alias)
            except OSError:
                self.skipTest("hard links are unavailable")
            index["bindings"][0]["implementation_artifact"] = _descriptor(root, alias)
            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
            hardlink = self._assess(root, index_path)
            self.assertFalse(hardlink["passed"])
            self.assertIn("hardlink", " ".join(hardlink["blockers"]))

    def test_default_validator_rejects_self_declared_fake_acceptance_before_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index_path, _ = _fixture(root)
            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
                result = target.assess_policy_qualification(project_root=root, index_path=index_path)
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
            index_path, _ = _fixture(root)
            output = root / "promoted"
            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
                result = target.promote_policy_qualification(project_root=root, index_path=index_path, output_dir=output, pilot_validator=_fake_pilot_validator)
                repeated = target.promote_policy_qualification(project_root=root, index_path=index_path, output_dir=output, pilot_validator=_fake_pilot_validator)
            self.assertTrue(result["passed"])
            self.assertEqual(result["receipt"], repeated["receipt"])
            receipt = json.loads((output / target.QUALIFICATION_RECEIPT_FILENAME).read_text(encoding="utf-8"))
            self.assertEqual(receipt["status"], "accepted_evidence_driven_policy_qualification")
            for role in ("capability_manifest", "calibration_mapping"):
                path = output / receipt["outputs"][role]["path"]
                self.assertEqual(_sha(path), receipt["outputs"][role]["sha256"])
            capability_path = output / target.CAPABILITY_MANIFEST_FILENAME
            capability_path.write_text("{}\n", encoding="utf-8")
            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
                with self.assertRaises(target.QualificationError):
                    target.promote_policy_qualification(project_root=root, index_path=index_path, output_dir=output, pilot_validator=_fake_pilot_validator)


if __name__ == "__main__":
    unittest.main()
