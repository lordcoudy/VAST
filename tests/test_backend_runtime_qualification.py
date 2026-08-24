from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

target = importlib.import_module("backend_runtime_qualification")

SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
RESOURCES = ("cpu", "gpu")
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
POLICIES = (
    "cpu_only", "gpu_only", "static_hybrid", "heft",
    "deadline_aware_heft", "queue_aware_edf", "adaptive_weights",
)
DEADLINES_MS = (16.7, 33.3, 50, 100, 500)


def canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode() + b"\n")


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def self_hashed(value: dict) -> dict:
    result = copy.deepcopy(value)
    result["sha256"] = canonical_sha(result)
    return result


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        contract = importlib.import_module("publication_policy_contract")
        self.policy_contract_sha = contract.policy_contract_identity()["sha256"]
        self.resource_contract_sha = hashlib.sha256(b"resource-contract").hexdigest()
        self.execution_identity = hashlib.sha256(b"execution-config").hexdigest()
        self.parity_identity = hashlib.sha256(b"parity-manifest").hexdigest()
        self.sources = {codec: [hashlib.sha256(f"{codec}-{i}".encode()).hexdigest() for i in (1, 2)] for codec in CODECS}
        self._build_upstream()
        self.index = self._build_index()
        self.index_path = root / "evidence/backend/qualification_index.json"
        write_json(self.index_path, self.index)

    def _artifact(self, relative: str, payload: bytes) -> dict[str, object]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return descriptor(self.root, path)

    def _build_upstream(self) -> None:
        self.dataset_descriptor = self._artifact("configs/datasets.yaml", b"real-kpp-dataset-manifest\n")
        self.execution_descriptor = self._artifact("configs/analytics_execution_layer.yaml", b"execution-config\n")
        self.parity_descriptor = self._artifact("configs/checkpoint_analytics_model_parity.yaml", b"parity-manifest\n")
        systems = {}
        for system in SYSTEMS:
            branches = {}
            for branch in BRANCHES:
                resources = {}
                for resource in RESOURCES:
                    resources[resource] = {
                        "status": "implemented_and_native_evidence_bound",
                        "implementation_id": f"{system}.{branch}.{resource}.implementation.v1",
                        "implementation_sha256": hashlib.sha256(f"impl:{system}:{branch}:{resource}".encode()).hexdigest(),
                        "runtime_binding": f"{system}.{branch}.{resource}.binding.v1",
                        "runtime_identity": {
                            "runtime_backend": f"{system}.native.backend.v1",
                            "device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
                            "worker_image_digest": "sha256:" + hashlib.sha256(f"worker:{resource}".encode()).hexdigest(),
                            "implementation_version": f"{system}.runtime.implementation.v1",
                        },
                        "native_evidence": {
                            "status": "accepted_native_runtime_emitter", "telemetry_source": "native",
                            "emitter_id": f"{system}.{branch}.{resource}.emitter.v1",
                            "emitter_sha256": hashlib.sha256(f"emitter:{system}:{branch}:{resource}".encode()).hexdigest(),
                            "implementation_id_field": "implementation_id", "resource_field": "selected_resource",
                        },
                    }
                branches[branch] = resources
            systems[system] = {"branches": branches}
        self.policy_capability = {
            "schema_version": 1, "artifact_kind": "vast_publication_policy_capability_manifest",
            "policy_scope": "analytics_only", "policy_contract_sha256": self.policy_contract_sha,
            "systems": systems,
        }
        policy_cap_path = self.root / "evidence/policy/checkpoint_policy_capability_manifest.json"
        write_json(policy_cap_path, self.policy_capability)
        self.policy_capability_descriptor = descriptor(self.root, policy_cap_path)
        policy_receipt_core = {
            "schema_version": 1, "artifact_kind": "vast_publication_policy_qualification_receipt",
            "status": "accepted_evidence_driven_policy_qualification", "policy_contract_sha256": self.policy_contract_sha,
            "qualification_index_sha256": hashlib.sha256(b"policy-index").hexdigest(),
            "dataset_manifest_sha256": self.dataset_descriptor["sha256"],
            "coverage": {"binding_count": 32, "pilot_cell_count": 32, "accepted_sample_count": 3840, "minimum_samples_per_branch_cell": 30},
            "outputs": {
                "capability_manifest": {"path": policy_cap_path.name, "size_bytes": self.policy_capability_descriptor["size_bytes"], "sha256": self.policy_capability_descriptor["sha256"]},
                "calibration_mapping": {"path": "checkpoint_policy_calibration_mapping.json", "size_bytes": 1, "sha256": hashlib.sha256(b"x").hexdigest()},
            },
        }
        policy_receipt_path = self.root / "evidence/policy/checkpoint_policy_qualification_receipt.json"
        write_json(policy_receipt_path, self_hashed(policy_receipt_core))
        self.policy_receipt_descriptor = descriptor(self.root, policy_receipt_path)

        resource_systems = {}
        for system in SYSTEMS:
            resources = {}
            for resource in RESOURCES:
                emitters = {role: {"status": "native_emitter_implementation_bound", "emitter_id": f"{system}.{resource}.{role}.v2", "artifact_sha256": hashlib.sha256(f"resource:{system}:{resource}:{role}".encode()).hexdigest(), "telemetry_source": "native"} for role in ("resource_intervals", "hardware_resource_samples", "fanout_work_counters")}
                resources[resource] = {
                    "status": "implemented_and_pre_run_pilot_required", "implementation_id": f"{system}.{resource}.resource.v2",
                    "implementation_sha256": hashlib.sha256(f"resource-impl:{system}:{resource}".encode()).hexdigest(),
                    "runtime_binding": f"{system}.{resource}.resource.binding.v2",
                    "runtime_identity": {
                        "runtime_backend": f"{system}.native.backend.v2", "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
                        "decoder_device_api": "NVIDIA_NVDEC", "worker_image_digest": "sha256:" + hashlib.sha256(f"worker:{resource}".encode()).hexdigest(),
                        "implementation_version": f"{system}.resource.runtime.v2", "hardware_binding_id": f"{system}.{resource}.hardware.binding.v2",
                    },
                    "emitters": emitters,
                }
            resource_systems[system] = {"resources": resources}
        self.resource_capability = {
            "schema_version": 1, "artifact_kind": "vast_pre_run_full_resource_capability_manifest",
            "qualification_scope": "pre_run_hardware_and_emitter_capability_only",
            "publication_scope": "primary_architecture_full_resource_raw_evidence_v2",
            "resource_contract": {"contract_version": 2, "publication_scope": "primary_architecture_full_resource_raw_evidence_v2", "full_resource_validator_sha256": hashlib.sha256(b"full-validator").hexdigest(), "interval_validator_sha256": hashlib.sha256(b"interval-validator").hexdigest()},
            "resource_contract_identity_sha256": self.resource_contract_sha,
            "dataset_manifest_sha256": self.dataset_descriptor["sha256"],
            "datasets": {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.sources[codec]} for codec in CODECS},
            "systems": resource_systems, "pilot_cells": [],
            "coverage": {"binding_count": 8, "pilot_cell_count": 32, "accepted_branch_sample_count": 3840, "minimum_samples_per_branch_coordinate": 30, "systems": 4, "resources": 2, "codecs": 2, "topology_kinds": 2, "branches": 4},
            "post_run_per_arm_evidence": {"required": True, "acceptance_artifact_kind": "checkpoint_publication_runtime_acceptance", "validator": "validate_full_resource_evidence", "configuration_evidence_accepted_mutated": False},
        }
        self.resource_capability["content_sha256"] = canonical_sha(self.resource_capability)
        resource_cap_path = self.root / "evidence/resource/checkpoint_full_resource_capability_manifest.json"
        write_json(resource_cap_path, self.resource_capability)
        self.resource_capability_descriptor = descriptor(self.root, resource_cap_path)
        resource_receipt_core = {
            "schema_version": 1, "artifact_kind": "vast_pre_run_full_resource_capability_qualification_receipt",
            "status": "accepted_pre_run_resource_capability_qualification", "qualification_index_sha256": hashlib.sha256(b"resource-index").hexdigest(),
            "dataset_manifest_sha256": self.dataset_descriptor["sha256"], "resource_contract_identity_sha256": self.resource_contract_sha,
            "capability_manifest_content_sha256": self.resource_capability["content_sha256"], "coverage": self.resource_capability["coverage"],
            "post_run_per_arm_evidence_required": True, "configuration_evidence_accepted_mutated": False,
            "outputs": {"capability_manifest": {"path": resource_cap_path.name, "size_bytes": self.resource_capability_descriptor["size_bytes"], "sha256": self.resource_capability_descriptor["sha256"]}},
        }
        resource_receipt_path = self.root / "evidence/resource/checkpoint_full_resource_qualification_receipt.json"
        write_json(resource_receipt_path, self_hashed(resource_receipt_core))
        self.resource_receipt_descriptor = descriptor(self.root, resource_receipt_path)

    def _runtime_binding(self, system: str) -> dict:
        image_digest = hashlib.sha256(f"image:{system}".encode()).hexdigest()
        image = self._artifact(
            f"evidence/runtime/{system}/image.txt",
            f"sha256:{image_digest}\n".encode(),
        )
        source = self._artifact(
            f"evidence/runtime/{system}/runtime.py",
            f"# native runtime {system}\n".encode(),
        )
        binary = self._artifact(
            f"evidence/runtime/{system}/runtime.bin",
            f"native-binary:{system}\n".encode(),
        )
        worker = self._artifact(
            f"evidence/runtime/{system}/worker.bin",
            f"worker-binary:{system}\n".encode(),
        )
        return {
            "system": system,
            "runtime_id": f"{system}.accepted.native.runtime.v1",
            "runtime_backend": f"{system}.native.backend.v1",
            "hardware_binding_id": f"{system}.kpp.rtx3070.binding.v1",
            "runtime_image_digest": "sha256:" + image_digest,
            "artifacts": {"image_descriptor": image, "runtime_source": source, "runtime_binary": binary, "worker_binary": worker},
        }

    def _pilot(self, system: str, codec: str, topology: str) -> dict:
        root = f"evidence/pilots/{system}/{codec}/{topology}"
        evidence = {}
        for role in ("checkpoint_acceptance", "native_policy_decisions", "resource_intervals", "hardware_resource_samples", "fanout_work_counters", "runtime_probe"):
            evidence[role] = self._artifact(f"{root}/{role}.dat", f"{system}:{codec}:{topology}:{role}\n".encode())
        return {"system": system, "codec": codec, "topology_kind": topology, "evidence": evidence}

    def _build_index(self) -> dict:
        runtime_bindings = [self._runtime_binding(system) for system in SYSTEMS]
        runtime_identities = {}
        for value in runtime_bindings:
            normalized = copy.deepcopy(value)
            runtime_identities[value["system"]] = canonical_sha(normalized)
        return {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_qualification_index",
            "dataset_manifest": self.dataset_descriptor,
            "policy_qualification": {"receipt": self.policy_receipt_descriptor, "capability_manifest": self.policy_capability_descriptor},
            "resource_qualification": {"receipt": self.resource_receipt_descriptor, "capability_manifest": self.resource_capability_descriptor},
            "analytics_execution": {
                "config": self.execution_descriptor,
                "config_identity_sha256": self.execution_identity,
                "model_parity_manifest": self.parity_descriptor,
                "model_parity_manifest_identity_sha256": self.parity_identity,
            },
            "runtime_bindings": runtime_bindings,
            "runtime_cells": [
                {
                    "system": system, "codec": codec,
                    "topology_kind": topology, "policy": policy,
                    "deadline_ms": deadline,
                    "reachability_status": "native_runtime_cell_reachable",
                    "runtime_binding_identity_sha256": runtime_identities[system],
                    "policy_contract_sha256": self.policy_contract_sha,
                    "policy_capability_artifact_sha256": self.policy_capability_descriptor["sha256"],
                    "resource_contract_identity_sha256": self.resource_contract_sha,
                    "resource_capability_content_sha256": self.resource_capability["content_sha256"],
                    "analytics_execution_config_identity_sha256": self.execution_identity,
                    "model_parity_manifest_identity_sha256": self.parity_identity,
                }
                for system in SYSTEMS for codec in CODECS
                for topology in TOPOLOGIES for policy in POLICIES
                for deadline in DEADLINES_MS
            ],
            "pilots": [self._pilot(system, codec, topology) for system in SYSTEMS for codec in CODECS for topology in TOPOLOGIES],
        }


def fake_validator(pilot: dict, context: dict) -> dict:
    system, codec, topology = pilot["system"], pilot["codec"], pilot["topology_kind"]
    rows = []
    for resource in RESOURCES:
        for branch in BRANCHES:
            rows.append({
                "resource": resource,
                "branch": branch,
                "implementation_id": context["policy_capability"]["systems"][system]["branches"][branch][resource]["implementation_id"],
                "policy_emitter_id": context["policy_capability"]["systems"][system]["branches"][branch][resource]["native_evidence"]["emitter_id"],
                "resource_emitter_ids": {role: context["resource_capability"]["systems"][system]["resources"][resource]["emitters"][role]["emitter_id"] for role in ("resource_intervals", "hardware_resource_samples", "fanout_work_counters")},
                "worker_image_digest": context["resource_capability"]["systems"][system]["resources"][resource]["runtime_identity"]["worker_image_digest"],
                "native_execution": True,
            })
    return {
        "system": system, "codec": codec, "topology_kind": topology,
        "dataset_name": f"kpp_real_{codec}", "source_sha256": context["dataset_sources"][codec],
        "publication_scope": "backend_native_runtime_hardware_capability_only",
        "accepted": True, "synthetic": False, "nonpublication": False,
        "runtime_id": context["runtime_binding"]["runtime_id"],
        "runtime_image_digest": context["runtime_binding"]["runtime_image_digest"],
        "hardware_binding_id": context["runtime_binding"]["hardware_binding_id"],
        "evidence_sha256": {role: value["sha256"] for role, value in context["pilot_evidence"].items()},
        "resource_branch_executions": rows,
    }


class BackendRuntimeQualificationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assess(self, fixture: Fixture | None = None) -> dict:
        item = fixture or self.fixture
        return target.assess_backend_runtime_qualification(
            project_root=item.root, index_path=item.index_path,
            pilot_validator=fake_validator,
            dataset_loader=lambda *_args, **_kwargs: {
                codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": item.sources[codec]}
                for codec in CODECS
            },
            execution_identity_loader=lambda *_args, **_kwargs: (item.execution_identity, item.parity_identity),
        )

    def test_exact_four_systems_and_sixteen_hardware_cells_pass(self) -> None:
        result = self.assess()
        self.assertTrue(result["passed"], result["blockers"])
        self.assertEqual(result["coverage"]["system_count"], 4)
        self.assertEqual(result["coverage"]["hardware_pilot_cell_count"], 16)
        self.assertEqual(result["coverage"]["benchmark_arm_pilot_count"], 16)
        self.assertEqual(result["coverage"]["runtime_cell_count"], 560)
        self.assertEqual(result["coverage"]["resource_branch_execution_count"], 128)
        self.assertEqual(result["coverage"]["deadlines_ms"], list(DEADLINES_MS))
        self.assertEqual(set(result["system_qualifications"]), set(SYSTEMS))

    def test_missing_duplicate_and_relabelled_cells_fail_closed(self) -> None:
        cases = []
        missing = copy.deepcopy(self.fixture.index)
        missing["pilots"].pop()
        cases.append(missing)
        duplicate = copy.deepcopy(self.fixture.index)
        duplicate["pilots"][-1] = copy.deepcopy(duplicate["pilots"][0])
        cases.append(duplicate)
        relabelled = copy.deepcopy(self.fixture.index)
        relabelled["pilots"][0]["system"] = "generic_backend"
        cases.append(relabelled)
        for position, value in enumerate(cases):
            with self.subTest(position=position):
                write_json(self.fixture.index_path, value)
                result = self.assess()
                self.assertFalse(result["passed"])
                write_json(self.fixture.index_path, self.fixture.index)

    def test_all_560_policy_deadline_runtime_cells_are_exact_and_relabel_proof(self) -> None:
        mutations = []
        missing = copy.deepcopy(self.fixture.index)
        missing["runtime_cells"].pop()
        mutations.append(missing)
        duplicate = copy.deepcopy(self.fixture.index)
        duplicate["runtime_cells"][-1] = copy.deepcopy(duplicate["runtime_cells"][0])
        mutations.append(duplicate)
        wrong_deadline = copy.deepcopy(self.fixture.index)
        wrong_deadline["runtime_cells"][0]["deadline_ms"] = 75
        mutations.append(wrong_deadline)
        generic = copy.deepcopy(self.fixture.index)
        generic["runtime_cells"][0]["reachability_status"] = "generic_capability_probe"
        mutations.append(generic)
        identity_drift = copy.deepcopy(self.fixture.index)
        identity_drift["runtime_cells"][0]["policy_contract_sha256"] = hashlib.sha256(b"relabel").hexdigest()
        mutations.append(identity_drift)
        for position, value in enumerate(mutations):
            with self.subTest(position=position):
                write_json(self.fixture.index_path, value)
                self.assertFalse(self.assess()["passed"])
        write_json(self.fixture.index_path, self.fixture.index)

    def test_synthetic_nonpublication_unaccepted_and_generic_probes_fail(self) -> None:
        mutations = (
            ("synthetic", True), ("nonpublication", True), ("accepted", False),
            ("publication_scope", "generic_capability_probe"),
        )
        for field, value in mutations:
            with self.subTest(field=field):
                def invalid(pilot: dict, context: dict, *, _field=field, _value=value) -> dict:
                    result = fake_validator(pilot, context)
                    result[_field] = _value
                    return result
                result = target.assess_backend_runtime_qualification(
                    project_root=self.root, index_path=self.fixture.index_path,
                    pilot_validator=invalid,
                    dataset_loader=lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
                    execution_identity_loader=lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
                )
                self.assertFalse(result["passed"])

    def test_both_resources_four_branches_and_exact_native_bindings_are_required(self) -> None:
        def incomplete(pilot: dict, context: dict) -> dict:
            result = fake_validator(pilot, context)
            result["resource_branch_executions"].pop()
            return result
        result = target.assess_backend_runtime_qualification(
            project_root=self.root, index_path=self.fixture.index_path,
            pilot_validator=incomplete,
            dataset_loader=lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
            execution_identity_loader=lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
        )
        self.assertFalse(result["passed"])

        def drift(pilot: dict, context: dict) -> dict:
            result = fake_validator(pilot, context)
            result["resource_branch_executions"][0]["policy_emitter_id"] += ".relabel"
            return result
        result = target.assess_backend_runtime_qualification(
            project_root=self.root, index_path=self.fixture.index_path,
            pilot_validator=drift,
            dataset_loader=lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
            execution_identity_loader=lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
        )
        self.assertFalse(result["passed"])

    def test_upstream_receipt_self_hash_and_all_artifact_descriptors_are_rechecked(self) -> None:
        tampered = self.root / self.fixture.index["runtime_bindings"][0]["artifacts"]["runtime_binary"]["path"]
        tampered.write_bytes(b"tampered\n")
        self.assertFalse(self.assess()["passed"])
        self.fixture = Fixture(self.root)
        receipt_path = self.root / self.fixture.policy_receipt_descriptor["path"]
        receipt = json.loads(receipt_path.read_text())
        receipt["status"] = "accepted_evidence_driven_policy_qualification_relabelled"
        write_json(receipt_path, receipt)
        self.fixture.index["policy_qualification"]["receipt"] = descriptor(self.root, receipt_path)
        write_json(self.fixture.index_path, self.fixture.index)
        self.assertFalse(self.assess()["passed"])

    def test_alias_hardlink_and_symlink_artifacts_are_rejected(self) -> None:
        original = self.root / self.fixture.index["runtime_bindings"][0]["artifacts"]["runtime_source"]["path"]
        hardlink = self.root / "evidence/runtime/hardlink.py"
        try:
            os.link(original, hardlink)
        except OSError:
            self.skipTest("hardlinks unavailable")
        self.fixture.index["runtime_bindings"][0]["artifacts"]["runtime_source"] = descriptor(self.root, hardlink)
        write_json(self.fixture.index_path, self.fixture.index)
        self.assertFalse(self.assess()["passed"])

    def test_assessment_is_pure(self) -> None:
        before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file())
        self.assertTrue(self.assess()["passed"])
        after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*") if path.is_file())
        self.assertEqual(before, after)

    def test_promote_writes_four_receipts_then_binding_index_last_and_is_idempotent(self) -> None:
        output = self.root / "evidence/backend/promoted"
        order = []
        real_writer = target._write_immutable_json

        def recording(path: Path, value: dict) -> dict:
            order.append(path.name)
            return real_writer(path, value)

        kwargs = {
            "project_root": self.root, "index_path": self.fixture.index_path,
            "output_dir": output, "pilot_validator": fake_validator,
            "dataset_loader": lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
            "execution_identity_loader": lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
        }
        with mock.patch.object(target, "_write_immutable_json", side_effect=recording):
            result = target.promote_backend_runtime_qualification(**kwargs)
        self.assertTrue(result["passed"])
        self.assertEqual(order[-1], target.BINDING_INDEX_FILENAME)
        self.assertEqual(len(order), 5)
        repeated = target.promote_backend_runtime_qualification(**kwargs)
        self.assertEqual(result["binding_index"], repeated["binding_index"])
        index = json.loads((output / target.BINDING_INDEX_FILENAME).read_text())
        self.assertEqual(index["sha256"], canonical_sha({k: v for k, v in index.items() if k != "sha256"}))
        self.assertEqual(index["coverage"]["hardware_pilot_cell_count"], 16)
        self.assertEqual(index["coverage"]["runtime_cell_count"], 560)
        self.assertEqual(index["coverage"]["deadlines_ms"], list(DEADLINES_MS))
        for system in SYSTEMS:
            receipt = json.loads((output / f"checkpoint_{system}_backend_runtime_qualification_receipt.json").read_text())
            self.assertEqual(receipt["coverage"]["hardware_pilot_cell_count"], 4)
            self.assertEqual(receipt["coverage"]["benchmark_arm_pilot_count"], 4)
            self.assertEqual(receipt["coverage"]["resource_branch_execution_count"], 32)
            self.assertEqual(receipt["coverage"]["runtime_cell_count"], 140)
            self.assertEqual(receipt["coverage"]["deadlines_ms"], list(DEADLINES_MS))
            self.assertTrue(receipt["post_run_per_arm_evidence_required"])
            self.assertFalse(receipt["configuration_evidence_accepted_mutated"])
            self.assertNotIn("pilot_arm_count", receipt["coverage"])

    def test_promoted_outputs_are_accepted_by_identity_backend_validator(self) -> None:
        output = self.root / "evidence/backend/promoted"
        result = target.promote_backend_runtime_qualification(
            project_root=self.root, index_path=self.fixture.index_path,
            output_dir=output, pilot_validator=fake_validator,
            dataset_loader=lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
            execution_identity_loader=lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
        )
        identity = importlib.import_module("full_publication_identity_artifacts")
        canonical_root = Path(os.path.abspath(os.fspath(self.root)))
        canonical_output = output.resolve(strict=True)
        canonical_root = canonical_output.parents[2]
        registry = identity._Registry(canonical_root)
        binding = {
            "binding_index": descriptor(canonical_root, canonical_output / target.BINDING_INDEX_FILENAME),
            "receipts": {
                system: descriptor(canonical_root, canonical_output / f"checkpoint_{system}_backend_runtime_qualification_receipt.json")
                for system in SYSTEMS
            },
        }
        accepted = identity._validate_backends(
            binding, registry=registry,
            parity_identity=self.fixture.parity_identity,
            parity_acceptance_binding_sha256=hashlib.sha256(
                b"parity-acceptance-binding"
            ).hexdigest(),
            execution_identity=self.fixture.execution_identity,
            policy_record=self.fixture.policy_receipt_descriptor,
            policy_receipt=json.loads((self.root / self.fixture.policy_receipt_descriptor["path"]).read_text()),
            policy_outputs={},
            resource_record=self.fixture.resource_receipt_descriptor,
            resource_receipt=json.loads((self.root / self.fixture.resource_receipt_descriptor["path"]).read_text()),
        )
        self.assertEqual(accepted["binding_index"]["sha256"], result["binding_index_descriptor"]["sha256"])

    def test_output_collision_fails_closed_without_replacing_binding_index(self) -> None:
        output = self.root / "evidence/backend/promoted"
        output.mkdir(parents=True)
        collision = output / "checkpoint_deepstream_backend_runtime_qualification_receipt.json"
        collision.write_bytes(b"collision\n")
        with self.assertRaises(target.BackendRuntimeQualificationError):
            target.promote_backend_runtime_qualification(
                project_root=self.root, index_path=self.fixture.index_path,
                output_dir=output, pilot_validator=fake_validator,
                dataset_loader=lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
                execution_identity_loader=lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
            )
        self.assertFalse((output / target.BINDING_INDEX_FILENAME).exists())
        for system in SYSTEMS[1:]:
            self.assertFalse((output / f"checkpoint_{system}_backend_runtime_qualification_receipt.json").exists())

    def test_default_validator_never_accepts_declared_fixture_evidence(self) -> None:
        result = target.assess_backend_runtime_qualification(
            project_root=self.root, index_path=self.fixture.index_path,
            dataset_loader=lambda *_a, **_k: {codec: {"dataset_name": f"kpp_real_{codec}", "source_sha256": self.fixture.sources[codec]} for codec in CODECS},
            execution_identity_loader=lambda *_a, **_k: (self.fixture.execution_identity, self.fixture.parity_identity),
        )
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
