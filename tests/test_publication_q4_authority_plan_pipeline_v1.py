from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


from test_checkpoint_external_execution_manifest import worker_manifest_fixture, producer as native_producer

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from backend_publication_launcher_invocation_v3 import (  # noqa: E402
    publication_launcher_invocation_v3_contract,
)
from backend_publication_launcher_runtime_authority import (  # noqa: E402
    build_backend_publication_launcher_runtime_authority,
)
from backend_publication_runtime_authority_v2 import (  # noqa: E402
    build_backend_publication_runtime_authority_v2,
)
from backend_runtime_validation_runner_authority import (  # noqa: E402
    build_backend_runtime_validation_runner_authority,
)
import backend_q4_two_phase_source_registry_v1 as source_registry  # noqa: E402
import publication_q4_authority_plan_pipeline_v1 as target  # noqa: E402
import publication_q4_runtime_contract_v4 as runtime_contract  # noqa: E402
import publication_q4_runtime_registry_materializer_v4 as runtime_registry  # noqa: E402
from test_publication_q4_runtime_contract_v4 import runtime_template  # noqa: E402


class InjectedCrash(BaseException):
    pass


def canonical(value: object, *, newline: bool = False) -> bytes:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return payload + (b"\n" if newline else b"")


def semantic(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def named_sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.engine_path = root / "engine.sock"
        self.analytics_path = root / "analytics.sock"
        self.engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.analytics = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.engine.bind(str(self.engine_path))
        self.analytics.bind(str(self.analytics_path))
        (root / "transactions" / "A").mkdir(parents=True)
        (root / "transactions" / "B").mkdir(parents=True)
        (root / "specs").mkdir()
        self._accepted_inputs()
        self._runtime_inputs()
        self._launcher_inputs()
        self._validator_runner_inputs()

    def close(self) -> None:
        self.analytics.close()
        self.engine.close()

    def write_bytes(self, relative: str, payload: bytes) -> dict[str, object]:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return self.descriptor(path)

    def write_json(self, relative: str, value: object) -> dict[str, object]:
        return self.write_bytes(relative, canonical(value, newline=True))

    def descriptor(self, path: Path) -> dict[str, object]:
        payload = path.read_bytes()
        return {
            "path": path.relative_to(self.root).as_posix(),
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    @staticmethod
    def artifact(role: str, item: dict[str, object]) -> dict[str, object]:
        return {
            "role": role, "descriptor": copy.deepcopy(item),
            "content_identity_sha256": item["sha256"],
        }

    @staticmethod
    def content(value: dict[str, object]) -> dict[str, object]:
        return {
            "content": copy.deepcopy(value),
            "content_identity_sha256": semantic(value),
        }

    @staticmethod
    def socket_binding(path: Path, *, endpoint: bool) -> dict[str, object]:
        info = path.lstat()
        value: dict[str, object] = {
            "device": int(info.st_dev), "inode": int(info.st_ino),
            "owner_uid": int(info.st_uid), "owner_gid": int(info.st_gid),
        }
        if endpoint:
            value.update({
                "host_path": str(path),
                "container_path": "/run/vast/analytics-execution.sock",
            })
        else:
            value["path"] = str(path)
        return value

    def _accepted_inputs(self) -> None:
        plain = lambda name: self.write_json(
            f"accepted/{name}.json", {"fixture": name}
        )
        self.parity_receipt = plain("parity-receipt")
        self.parity_manifest = plain("parity-manifest")
        self.parity_assessment = plain("parity-assessment")
        self.parity_binding = plain("parity-binding")
        self.execution_config = plain("execution-config")
        self.binding_index = plain("binding-index")
        self.workers = worker_manifest_fixture(self.execution_config)
        self.policy_capability = self.write_json("accepted/policy-capability.json", self.workers.policy)
        self.policy_calibration_values = {
            system: {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_calibration",
                "system": system,
                "policy_contract_sha256": named_sha("policy-contract"),
                "costs": {},
            }
            for system in runtime_contract.SYSTEMS
        }
        self.policy_calibrations = {
            system: self.write_json(
                f"accepted/policy-calibration/{system}.v1.json",
                self.policy_calibration_values[system],
            )
            for system in runtime_contract.SYSTEMS
        }
        self.policy_calibration_value = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_calibration_mapping",
            "policy_contract_sha256": named_sha("policy-contract"),
            "aggregation_rule": (
                "median_of_balanced_native_codec_topology_cells_v1"
            ),
            "minimum_samples_per_branch_cell": 30,
            "calibrations": copy.deepcopy(self.policy_calibration_values),
        }
        self.policy_calibration = self.write_json(
            "accepted/policy-calibration-mapping.v1.json",
            self.policy_calibration_value,
        )
        self.policy_static_maps = {
            system: self.write_json(
                f"accepted/policy-static-map/{system}.v1.json",
                {"system": system, "placement": {}},
            )
            for system in runtime_contract.SYSTEMS
        }
        self.policy_receipt = plain("policy-receipt")
        self.resource_capability = plain("resource-capability")
        self.resource_receipt = self.write_json(
            "accepted/resource-receipt.json",
            {
                "outputs": {
                    "capability_manifest": {
                        **copy.deepcopy(self.resource_capability),
                        "path": Path(
                            str(self.resource_capability["path"])
                        ).name,
                    }
                }
            },
        )
        self.service_authority = plain("service-authority")
        self.preprocessing_contract = plain("preprocessing-contract")
        self.preprocessing_receipt = self.write_json(
            "accepted/preprocessing-receipt.json",
            {
                "accepted_policy_capability_manifest": self.policy_capability,
                "accepted_policy_calibration_mapping": self.policy_calibration,
            },
        )
        self.dataset_manifest = self.write_bytes(
            "accepted/dataset-manifest.json", b"dataset-manifest"
        )
        self.upstream = {
            "dataset_manifest_sha256": self.dataset_manifest["sha256"],
            "policy_contract_sha256": named_sha("policy-contract"),
            "policy_qualification_receipt_sha256": named_sha("policy-receipt"),
            "resource_contract_identity_sha256": semantic({"contract_version": 2}),
            "resource_qualification_receipt_sha256": named_sha("resource-receipt"),
            "analytics_execution_config_identity_sha256": named_sha("execution"),
            "model_parity_manifest_identity_sha256": named_sha("parity-manifest"),
            "model_parity_acceptance_binding_sha256": named_sha("parity-binding"),
        }
        self.service_identity = named_sha("analytics-service")
        self.worker_images = {
            "cpu": {
                "image": "vast/analytics-openvino-worker:publication-v4",
                "image_id": "sha256:" + "1" * 64,
            },
            "gpu": {
                "image": "vast/analytics-tensorrt-worker:publication-v4",
                "image_id": "sha256:" + "2" * 64,
            },
        }
        self.system_images = {
            system: {
                "reference": f"vast/{system}:publication-v4",
                "image_id": "sha256:" + str(position + 3) * 64,
            }
            for position, system in enumerate(runtime_contract.SYSTEMS)
        }
        patch_unsigned: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_qualification_image_identity_patch_v1",
            "workers": {
                resource: {
                    "target_reference": row["image"],
                    "image_id": row["image_id"],
                }
                for resource, row in self.worker_images.items()
            },
            "systems": {
                system: {
                    "physical_identity": {
                        "final_reference": row["reference"],
                        "image_id": row["image_id"],
                        "os": "linux", "architecture": "amd64",
                    }
                }
                for system, row in self.system_images.items()
            },
        }
        self.image_patch_value = {
            **patch_unsigned, "patch_sha256": semantic(patch_unsigned)
        }
        self.image_patch = self.write_json(
            "accepted/image-patch.json", self.image_patch_value
        )
        self.preprocessing_authority = {
            "schema_version": 1,
            "artifact_kind": "vast_guardian_accepted_policy_preprocessing_contract_authority_v1",
            "preprocessing_contract_content_sha256": self.workers.preprocessing,
            "preprocessing_contract_file_sha256": self.preprocessing_contract["sha256"],
            "materialization_receipt_identity_sha256": named_sha("preprocessing-receipt"),
            "materialization_receipt_file_sha256": self.preprocessing_receipt["sha256"],
            "predecessor_qualification_preprocessing_receipt_identity_sha256": named_sha("predecessor-receipt"),
            "predecessor_qualification_preprocessing_receipt_file_sha256": named_sha("predecessor-receipt-file"),
            "accepted_policy_qualification_receipt_identity_sha256": self.upstream["policy_qualification_receipt_sha256"],
            "accepted_policy_qualification_receipt_file_sha256": self.policy_receipt["sha256"],
            "accepted_policy_capability_manifest_file_sha256": self.policy_capability["sha256"],
            "accepted_policy_capability_manifest_content_sha256": named_sha("accepted-policy-capability"),
            "accepted_policy_calibration_mapping_file_sha256": self.policy_calibration["sha256"],
            "accepted_policy_calibration_mapping_content_sha256": named_sha("accepted-policy-calibration"),
            "qualification_execution_closure_receipt_identity_sha256": named_sha("execution-closure"),
            "qualification_execution_closure_receipt_file_sha256": named_sha("execution-closure-file"),
            "execution_config_identity_sha256": self.upstream["analytics_execution_config_identity_sha256"],
            "execution_config_file_sha256": self.execution_config["sha256"],
            "binding_set_identity_sha256": named_sha("binding-set"),
            "bindings_identity_sha256": named_sha("bindings"),
            "binding_set_index_file_sha256": self.binding_index["sha256"],
            "binding_preprocessing_consensus_sha256": named_sha("binding-preprocessing-consensus"),
            "worker_image_ids": {
                resource: row["image_id"] for resource, row in self.worker_images.items()
            },
            "policy_contract_sha256": self.upstream["policy_contract_sha256"],
        }

    def _runtime_inputs(self) -> None:
        self.dataset_sources: list[dict[str, str]] = []
        self.dataset_files: dict[str, list[dict[str, object]]] = {}
        for codec in runtime_contract.CODECS:
            front = self.write_bytes(
                f"datasets/{codec}/front.mp4", f"front:{codec}".encode("ascii")
            )
            underbody = self.write_bytes(
                f"datasets/{codec}/underbody.mp4",
                f"underbody:{codec}".encode("ascii"),
            )
            self.dataset_sources.append({
                "codec_variant": codec,
                "front_gate_path": str(front["path"]),
                "underbody_path": str(underbody["path"]),
            })
            self.dataset_files[codec] = [front, underbody]
        analytics_capability = self.artifact(
            "analytics_endpoint_capability",
            self.write_bytes("runtime/analytics-capability.json", b"analytics-capability"),
        )
        analytics_binding = self.artifact(
            "analytics_worker_binding",
            self.write_bytes("runtime/analytics-binding.json", b"analytics-binding"),
        )
        analytics_authority = {
            "endpoint_authority": {
                "transport": "AF_UNIX/SOCK_SEQPACKET",
                "path_derivation_contract_sha256": named_sha("path-derivation"),
                "peer_capability_identity_sha256": named_sha("peer-capability"),
                "peer_binding_identity_sha256": named_sha("peer-binding"),
                "bind_before_backend_launch": True,
                "peer_credentials_required": True,
            },
            "capability": analytics_capability,
            "bindings": [analytics_binding],
            "preprocessing_contract_sha256": self.workers.preprocessing,
        }
        policy_capability = self.artifact("policy_capability", self.policy_capability)
        policy_calibrations = {
            system: self.artifact(
                "policy_calibration", self.policy_calibrations[system]
            )
            for system in runtime_contract.SYSTEMS
        }
        policy_static_maps = {
            system: self.artifact(
                "policy_static_map", self.policy_static_maps[system]
            )
            for system in runtime_contract.SYSTEMS
        }
        sources = {
            system: self.artifact(
                "source_binary",
                self.write_bytes(f"runtime/{system}/source.bin", system.encode("ascii")),
            )
            for system in runtime_contract.SYSTEMS
        }
        backends = {
            system: self.artifact(
                "runtime_binary",
                self.write_bytes(
                    f"runtime/{system}/backend.bin",
                    f"backend:{system}".encode("ascii"),
                ),
            )
            for system in runtime_contract.SYSTEMS
        }
        engine = self.socket_binding(self.engine_path, endpoint=False)
        endpoint = self.socket_binding(self.analytics_path, endpoint=True)
        self.runtime_file_descriptors: dict[
            str, dict[str, dict[str, object]]
        ] = {}
        for system in runtime_contract.SYSTEMS:
            role_descriptors: dict[str, dict[str, object]] = {}
            for role in runtime_contract.RUNTIME_MODULE_BY_SYSTEM[system].FILE_ROLES:
                if role == "analytics_execution_manifest":
                    _, payload, _ = native_producer._adapter_asset(self.workers.inventory, system=system, final_root=ROOT / "artifacts/test-q4-pipeline")
                    item = self.write_json(f"runtime/{system}/execution-manifest.json", json.loads(payload))
                elif role == "policy_capability_manifest":
                    item = self.policy_capability
                elif role == "policy_calibration":
                    item = self.policy_calibrations[system]
                else:
                    item = self.write_json(
                        f"runtime/{system}/files/{role}.json",
                        {"fixture": f"{system}:{role}"},
                    )
                role_descriptors[role] = copy.deepcopy(item)
            self.runtime_file_descriptors[system] = role_descriptors
        self.runtime_builds: list[dict[str, object]] = []
        for system in runtime_contract.SYSTEMS:
            for codec in runtime_contract.CODECS:
                for topology in runtime_contract.TOPOLOGIES:
                    for policy in runtime_contract.POLICIES:
                        coordinate = {
                            "system": system, "codec": codec,
                            "topology_kind": topology, "policy": policy,
                        }
                        template = runtime_template(system, policy, codec)
                        if system in {"openvino_gva", "gstreamer_custom"}:
                            template["preprocessing_contract_sha256"] = self.workers.preprocessing
                        template["source_files"] = [
                            {
                                **copy.deepcopy(self.dataset_files[codec][0]),
                                "container_path": f"/opt/vast/input/{codec}/front.mp4",
                            },
                            {
                                **copy.deepcopy(self.dataset_files[codec][1]),
                                "container_path": f"/opt/vast/input/{codec}/underbody.mp4",
                            },
                        ]
                        template["container_engine_socket"] = copy.deepcopy(engine)
                        template["endpoint_sockets"] = [copy.deepcopy(endpoint)]
                        template["container_image"] = {
                            "image_id": self.system_images[system]["image_id"]
                        }
                        template["files"] = {
                            role: {
                                **copy.deepcopy(item),
                                "container_path": (
                                    f"/opt/vast/{system}/{role}.json"
                                ),
                            }
                            for role, item in self.runtime_file_descriptors[
                                system
                            ].items()
                        }
                        if policy == "static_hybrid":
                            template["static_hybrid_map"] = {
                                **copy.deepcopy(self.policy_static_maps[system]),
                                "container_path": "/opt/vast/static-map.json",
                            }
                        launcher_input = (
                            runtime_registry.build_publication_q4_runtime_launcher_input_wrapper_v3(
                                system=system,
                                policy=policy,
                                qualification_runtime_input_template=template,
                                production_runtime_input_template=copy.deepcopy(
                                    template
                                ),
                            )
                        )
                        policy_authority = {
                            "capability": copy.deepcopy(policy_capability),
                            "calibration": copy.deepcopy(
                                policy_calibrations[system]
                            ),
                            "static_map": (
                                copy.deepcopy(policy_static_maps[system])
                                if policy == "static_hybrid" else None
                            ),
                        }
                        inputs: dict[str, object] = {
                            "dataset_manifest": copy.deepcopy(self.dataset_manifest),
                            "dataset_files": copy.deepcopy(self.dataset_files[codec]),
                            "source_runtime_artifacts": [copy.deepcopy(sources[system])],
                            "backend_runtime_artifacts": [copy.deepcopy(backends[system])],
                            "analytics_authority": copy.deepcopy(analytics_authority),
                            "policy_authority": policy_authority,
                            "cohort_topology_plan": self.content({
                                "topology_kind": topology,
                                "warmup_s": 30, "measurement_s": 180,
                                "source_decode_count": (
                                    1 if topology == "shared_video_dag" else 6
                                ),
                            }),
                            "resource_contract": self.content({"contract_version": 2}),
                            "system_specific_launcher_input": self.content(
                                launcher_input
                            ),
                        }
                        expected_policy_outputs = {
                            name: (
                                None if item is None
                                else copy.deepcopy(item["descriptor"])
                            )
                            for name, item in policy_authority.items()
                        }
                        authority = build_backend_publication_runtime_authority_v2(
                            project_root=self.root, **coordinate, **inputs,
                            upstream_identities=self.upstream,
                            expected_upstream_identities=self.upstream,
                            expected_policy_outputs=expected_policy_outputs,
                        )
                        self.runtime_builds.append({
                            "coordinate": coordinate,
                            "expected_authority_sha256": authority["authority_sha256"],
                            "inputs": inputs,
                        })

    def _launcher_inputs(self) -> None:
        self.invocation_sha = publication_launcher_invocation_v3_contract()[
            "invocation_sha256"
        ]
        python_path = "launcher/python"
        leaf_paths = ["launcher/lib/core.py", "launcher/lib/protocol.py"]
        self.write_bytes(python_path, b"python-runtime")
        for position, leaf in enumerate(leaf_paths):
            self.write_bytes(leaf, f"leaf:{position}".encode("ascii"))
        self.launcher_builds: list[dict[str, object]] = []
        for system in runtime_contract.SYSTEMS:
            launcher_path = (
                f"scripts/checkpoint_{system}_publication_launcher_v3.py"
            )
            self.write_bytes(launcher_path, f"SYSTEM={system!r}\n".encode("ascii"))
            interpreter_descriptor = self.descriptor(self.root / python_path)
            launcher_descriptor = self.descriptor(self.root / launcher_path)
            interpreter = {
                "descriptor": interpreter_descriptor,
                "content_identity_sha256": interpreter_descriptor["sha256"],
            }
            launcher = {
                "descriptor": launcher_descriptor,
                "content_identity_sha256": launcher_descriptor["sha256"],
            }
            leaves = []
            for leaf in leaf_paths:
                leaf_descriptor = self.descriptor(self.root / leaf)
                leaves.append({
                    "descriptor": leaf_descriptor,
                    "content_identity_sha256": leaf_descriptor["sha256"],
                })
            leaves.sort(key=lambda item: (
                str(item["descriptor"]["path"]).casefold(),
                str(item["descriptor"]["path"]),
            ))
            closure_set = {
                "schema_version": 1,
                "artifact_kind": "vast_backend_publication_launcher_runtime_closure_set",
                "python_executable": interpreter,
                "publication_launcher": launcher,
                "runtime_leaves": leaves,
            }
            set_sha = semantic(closure_set)
            manifest = {
                "schema_version": 1,
                "artifact_kind": "vast_backend_publication_launcher_runtime_closure_manifest",
                "system": system,
                "python_executable": interpreter,
                "publication_launcher": launcher,
                "runtime_leaves": leaves,
                "runtime_closure_set_sha256": set_sha,
                "publication_launcher_invocation_v3_sha256": self.invocation_sha,
            }
            manifest["closure_manifest_sha256"] = semantic(manifest)
            manifest_path = f"launcher/{system}.manifest.json"
            manifest_descriptor = self.write_json(manifest_path, manifest)
            authority_unsigned = {
                "schema_version": 1,
                "artifact_kind": "vast_backend_publication_launcher_runtime_authority",
                "system": system,
                "runtime_closure_manifest": {
                    "descriptor": manifest_descriptor,
                    "content_identity_sha256": manifest["closure_manifest_sha256"],
                },
                "runtime_closure_manifest_content": manifest,
                "python_executable": interpreter,
                "publication_launcher": launcher,
                "runtime_leaves": leaves,
                "runtime_closure_set_sha256": set_sha,
                "publication_launcher_invocation_v3_sha256": self.invocation_sha,
            }
            expected_authority = semantic(authority_unsigned)
            built = build_backend_publication_launcher_runtime_authority(
                project_root=self.root, system=system,
                runtime_closure_manifest_path=manifest_path,
                python_executable_path=python_path,
                publication_launcher_path=launcher_path,
                runtime_leaf_paths=list(reversed(leaf_paths)),
                expected_authority_sha256=expected_authority,
                expected_system=system,
                expected_publication_launcher_invocation_v3_sha256=self.invocation_sha,
                expected_closure_manifest_sha256=manifest["closure_manifest_sha256"],
                expected_runtime_closure_set_sha256=set_sha,
            )
            self.launcher_builds.append({
                "system": system,
                "runtime_closure_manifest_path": manifest_path,
                "python_executable_path": python_path,
                "publication_launcher_path": launcher_path,
                "runtime_leaf_paths": list(reversed(leaf_paths)),
                "expected_authority_sha256": built["launcher_runtime_authority_sha256"],
                "expected_closure_manifest_sha256": manifest["closure_manifest_sha256"],
                "expected_runtime_closure_set_sha256": set_sha,
            })

    def _validator_runner_inputs(self) -> None:
        implementation = self.write_bytes(
            "validator/q4.py", b"def validate(value):\n    return value\n"
        )
        self.protocol_sha = named_sha("validation-protocol")
        self.input_sha = named_sha("validation-input")
        self.output_sha = named_sha("validation-output")
        pins = {
            "qualification_input_schema_identity_sha256": named_sha("qualification-input"),
            "validation_system_context_schema_identity_sha256": named_sha("system-context"),
            "validation_request_schema_identity_sha256": named_sha("request-schema"),
            "validation_record_schema_identity_sha256": named_sha("record-schema"),
            "validation_system_shard_schema_identity_sha256": named_sha("shard-schema"),
            "validation_record_set_index_schema_identity_sha256": named_sha("record-index-schema"),
            "validation_protocol_identity_sha256": self.protocol_sha,
            "validation_input_schema_identity_sha256": self.input_sha,
            "validation_output_schema_identity_sha256": self.output_sha,
        }
        validator_unsigned = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_validator_authority_q4",
            "validator_id": "backend-runtime-q4-validator-v1",
            "implementation": {
                "descriptor": implementation,
                "content_identity_sha256": implementation["sha256"],
            },
            "supported_qualification_schema_version": 4,
            **pins,
            "deterministic": True,
            "execution_authorized": False,
            "validation_records_authenticated": False,
        }
        self.validator_build = {
            "validator_id": "backend-runtime-q4-validator-v1",
            "implementation_descriptor": implementation,
            **pins,
            "expected_authority_sha256": semantic(validator_unsigned),
        }
        python_path = "runner/python"
        runner_path = "runner/run.py"
        leaf_paths = ["runner/lib/core.py", "runner/lib/protocol.py"]
        self.write_bytes(python_path, b"runner-python")
        self.write_bytes(runner_path, b"def main():\n    return 0\n")
        for position, leaf in enumerate(leaf_paths):
            self.write_bytes(leaf, f"runner-leaf:{position}".encode("ascii"))
        leaf_refs = []
        for leaf in leaf_paths:
            item = self.descriptor(self.root / leaf)
            leaf_refs.append({
                "descriptor": item, "content_identity_sha256": item["sha256"]
            })
        python_descriptor = self.descriptor(self.root / python_path)
        runner_descriptor = self.descriptor(self.root / runner_path)
        manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_validation_bundle_manifest",
            "python_executable": {
                "descriptor": python_descriptor,
                "content_identity_sha256": python_descriptor["sha256"],
            },
            "runner": {
                "descriptor": runner_descriptor,
                "content_identity_sha256": runner_descriptor["sha256"],
            },
            "runtime_leaves": leaf_refs,
            "runtime_leaf_set_sha256": semantic(leaf_refs),
        }
        manifest["bundle_manifest_sha256"] = semantic(manifest)
        manifest_path = "runner/bundle.json"
        self.write_json(manifest_path, manifest)
        runner = build_backend_runtime_validation_runner_authority(
            project_root=self.root,
            runner_id="backend-runtime-validation-runner-v1",
            runtime_bundle_manifest_path=manifest_path,
            runtime_leaf_paths=list(reversed(leaf_paths)),
            python_executable_path=python_path, runner_path=runner_path,
            validation_protocol_identity_sha256=self.protocol_sha,
            input_schema_identity_sha256=self.input_sha,
            output_schema_identity_sha256=self.output_sha,
        )
        self.runner_build = {
            "runner_id": "backend-runtime-validation-runner-v1",
            "runtime_bundle_manifest_path": manifest_path,
            "runtime_leaf_paths": list(reversed(leaf_paths)),
            "python_executable_path": python_path,
            "runner_path": runner_path,
            "validation_protocol_identity_sha256": self.protocol_sha,
            "input_schema_identity_sha256": self.input_sha,
            "output_schema_identity_sha256": self.output_sha,
            "expected_runner_authority_sha256": runner["runner_authority_sha256"],
        }

    def accepted_sources(self) -> dict[str, object]:
        return {
            "model_parity_acceptance_receipt_path": self.parity_receipt["path"],
            "policy_qualification_receipt_path": self.policy_receipt["path"],
            "policy_capability_manifest_path": self.policy_capability["path"],
            "policy_calibration_mapping_path": self.policy_calibration["path"],
            "resource_qualification_receipt_path": self.resource_receipt["path"],
            "resource_capability_manifest_path": self.resource_capability["path"],
            "analytics_service_authority_path": self.service_authority["path"],
            "guardian_preprocessing_contract_path": self.preprocessing_contract["path"],
            "guardian_preprocessing_receipt_path": self.preprocessing_receipt["path"],
            "expected_analytics_service_identity_sha256": self.service_identity,
        }

    def source_spec(self, run: str) -> tuple[Path, dict[str, object]]:
        unsigned: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_q4_authority_source_spec_v1",
            "status": "externally_pinned_accepted_q4_authority_sources",
            "authorization_eligible": False,
            "execution_authorized": False,
            "accepted_upstream_identities": copy.deepcopy(self.upstream),
            "accepted_sources": self.accepted_sources(),
            "dataset_sources": copy.deepcopy(self.dataset_sources),
            "runtime_authority_builds": copy.deepcopy(self.runtime_builds),
            "launcher_runtime_authority_builds": copy.deepcopy(self.launcher_builds),
            "publication_launcher_invocation_v3_sha256": self.invocation_sha,
            "q4_validator_authority_build": copy.deepcopy(self.validator_build),
            "runner_authority_build": copy.deepcopy(self.runner_build),
            "planned_outputs": {
                "runtime_candidate_registry_path": f"transactions/{run}/runtime-candidate-registry.v4.json",
                "runtime_materialization_result_path": f"transactions/{run}/runtime-materialization-result.v4.json",
                "source_registry_path": f"transactions/{run}/q4-source-registry.v1.json",
                "source_materialization_result_path": f"transactions/{run}/source-materialization-result.v1.json",
            },
        }
        spec = target.build_publication_q4_authority_source_spec_v1(
            accepted_upstream_identities=unsigned["accepted_upstream_identities"],
            accepted_sources=unsigned["accepted_sources"],
            dataset_sources=unsigned["dataset_sources"],
            runtime_authority_builds=unsigned["runtime_authority_builds"],
            launcher_runtime_authority_builds=unsigned[
                "launcher_runtime_authority_builds"
            ],
            publication_launcher_invocation_v3_sha256=unsigned[
                "publication_launcher_invocation_v3_sha256"
            ],
            q4_validator_authority_build=unsigned["q4_validator_authority_build"],
            runner_authority_build=unsigned["runner_authority_build"],
            planned_outputs=unsigned["planned_outputs"],
        )
        path = self.root / "specs" / f"{run}.json"
        path.write_bytes(canonical(spec, newline=True))
        return path, spec

    def source_material(self, run: str) -> tuple[Path, dict[str, object]]:
        _spec_path, spec = self.source_spec(run)
        material = {
            key: copy.deepcopy(value)
            for key, value in spec.items()
            if key != "source_spec_sha256"
        }
        path = self.root / "specs" / f"{run}.material.json"
        path.write_bytes(canonical(material, newline=True))
        return path, material

    def dependencies(
        self, _runtime_descriptor: dict[str, object]
    ) -> source_registry.BackendQ4SourceRegistryDependenciesV1:
        parity_files = [
            self.parity_receipt, self.parity_manifest, self.parity_assessment,
            self.image_patch, self.execution_config, self.binding_index,
        ]

        def load_parity(**_kwargs: object) -> dict[str, object]:
            return {
                "receipt": copy.deepcopy(self.parity_receipt),
                "accepted_manifest": copy.deepcopy(self.parity_manifest),
                "accepted_assessment": copy.deepcopy(self.parity_assessment),
                "binding_descriptor": copy.deepcopy(self.parity_binding),
                "binding_sha256": self.upstream["model_parity_acceptance_binding_sha256"],
                "accepted_manifest_content_identity_sha256": self.upstream["model_parity_manifest_identity_sha256"],
                "files": copy.deepcopy(parity_files),
                "refresh_authority": {
                    "image_identity_patch": {
                        **copy.deepcopy(self.image_patch),
                        "patch_sha256": self.image_patch_value["patch_sha256"],
                    },
                    "workers": {
                        resource: {
                            **copy.deepcopy(row),
                            "worker_implementation_sha256": named_sha(resource),
                        }
                        for resource, row in self.worker_images.items()
                    },
                    "execution_config": {
                        **copy.deepcopy(self.execution_config),
                        "content_identity_sha256": self.upstream["analytics_execution_config_identity_sha256"],
                        "worker_projection_sha256": named_sha("projection"),
                    },
                    "binding_set": {
                        "index": copy.deepcopy(self.binding_index),
                        "identity_sha256": named_sha("binding-set"),
                        "bindings_identity_sha256": named_sha("bindings"),
                    },
                },
            }

        def load_policy(**_kwargs: object) -> dict[str, object]:
            return {
                "receipt": copy.deepcopy(self.policy_receipt),
                "capability_manifest": copy.deepcopy(self.policy_capability),
                "calibration_mapping": copy.deepcopy(self.policy_calibration),
                "receipt_document": {
                    "dataset_manifest_sha256": self.upstream["dataset_manifest_sha256"],
                    "policy_contract_sha256": self.upstream["policy_contract_sha256"],
                    "sha256": self.upstream["policy_qualification_receipt_sha256"],
                },
                "files": [
                    copy.deepcopy(self.policy_receipt), copy.deepcopy(self.policy_capability),
                    copy.deepcopy(self.policy_calibration),
                ],
            }

        def load_resource(**_kwargs: object) -> dict[str, object]:
            return {
                "receipt": copy.deepcopy(self.resource_receipt),
                "capability_manifest": copy.deepcopy(self.resource_capability),
                "receipt_document": {
                    "dataset_manifest_sha256": self.upstream["dataset_manifest_sha256"],
                    "resource_contract_identity_sha256": self.upstream["resource_contract_identity_sha256"],
                    "sha256": self.upstream["resource_qualification_receipt_sha256"],
                },
                "files": [copy.deepcopy(self.resource_receipt), copy.deepcopy(self.resource_capability)],
            }

        def load_preprocessing(**_kwargs: object) -> dict[str, object]:
            return {
                "contract": copy.deepcopy(self.preprocessing_contract),
                "receipt": copy.deepcopy(self.preprocessing_receipt),
                "authority": copy.deepcopy(self.preprocessing_authority),
                "runtime_expectations": {
                    "execution_config_identity_sha256": self.upstream["analytics_execution_config_identity_sha256"],
                    "binding_set_identity_sha256": named_sha("binding-set"),
                    "bindings_identity_sha256": named_sha("bindings"),
                    "worker_image_ids": {
                        resource: row["image_id"] for resource, row in self.worker_images.items()
                    },
                    "policy_contract_sha256": self.upstream["policy_contract_sha256"],
                    "preprocessing_contract_content_sha256": self.workers.preprocessing,
                },
                "files": [
                    copy.deepcopy(self.preprocessing_contract),
                    copy.deepcopy(self.preprocessing_receipt),
                ],
            }

        def load_service(**_kwargs: object) -> dict[str, object]:
            return {
                "descriptor": copy.deepcopy(self.service_authority),
                "authority": {
                    "front_socket": self.socket_binding(self.analytics_path, endpoint=False)
                },
            }

        images = {
            row["reference"]: row["image_id"] for row in self.system_images.values()
        }
        images.update({
            row["image"]: row["image_id"] for row in self.worker_images.values()
        })

        def inspect_image(*, reference: str, **_kwargs: object) -> dict[str, str]:
            return {
                "reference": reference, "image_id": images[reference],
                "os": "linux", "architecture": "amd64",
            }

        return source_registry.BackendQ4SourceRegistryDependenciesV1(
            load_model_parity=load_parity,
            load_policy_qualification=load_policy,
            load_resource_qualification=load_resource,
            load_accepted_guardian_preprocessing=load_preprocessing,
            load_service_authority=load_service,
            inspect_image=inspect_image,
        )


@unittest.skipUnless(
    os.name == "posix" and sys.platform.startswith("linux"),
    "Q4 authority plan pipeline is a WSL/Linux production boundary",
)
class PublicationQ4AuthorityPlanPipelineV1Tests(unittest.TestCase):
    @staticmethod
    def phase1(root: Path, fixture: Fixture, run: str) -> tuple[dict[str, object], Path, dict[str, object]]:
        spec_path, spec = fixture.source_spec(run)
        receipt = target.materialize_publication_q4_authority_plan_phase1_v1(
            project_root=root,
            source_spec_path=spec_path,
            expected_source_spec_file_sha256=hashlib.sha256(spec_path.read_bytes()).hexdigest(),
            expected_source_spec_sha256=spec["source_spec_sha256"],
            output_dir=f"transactions/{run}/phase1",
        )
        path = root / f"transactions/{run}/phase1" / target.PHASE1_RECEIPT_FILENAME
        return receipt, path, spec

    @staticmethod
    def runtime_materialize(
        root: Path, receipt: dict[str, object], spec: dict[str, object]
    ) -> tuple[dict[str, object], Path]:
        plan_path = root / receipt["runtime_materialization_plan"]["descriptor"]["path"]
        plan = json.loads(plan_path.read_bytes())
        result_path = root / spec["planned_outputs"]["runtime_materialization_result_path"]
        result = runtime_registry.materialize_publication_q4_runtime_candidate_registry_v4(
            project_root=root, plan=plan,
            output_path=spec["planned_outputs"]["runtime_candidate_registry_path"],
            result_output_path=spec["planned_outputs"][
                "runtime_materialization_result_path"
            ],
        )
        assert result_path.read_bytes() == canonical(result, newline=True)
        return result, result_path

    def test_source_spec_builder_materializer_and_cli_are_physically_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                material_path, material = fixture.source_material("producer")
                material_payload = material_path.read_bytes()
                material_sha = semantic(material)
                output_path = root / "specs/generated-source-spec.v1.json"
                source_spec = target.materialize_publication_q4_authority_source_spec_v1(
                    project_root=root,
                    source_material_path=material_path,
                    expected_source_material_file_sha256=hashlib.sha256(
                        material_payload
                    ).hexdigest(),
                    expected_source_material_sha256=material_sha,
                    output_path=output_path,
                )
                self.assertEqual(source_spec["source_spec_sha256"], material_sha)
                self.assertEqual(
                    output_path.read_bytes(), canonical(source_spec, newline=True)
                )
                output_identity = (output_path.stat().st_dev, output_path.stat().st_ino)
                self.assertEqual(
                    target.materialize_publication_q4_authority_source_spec_v1(
                        project_root=root,
                        source_material_path=material_path,
                        expected_source_material_file_sha256=hashlib.sha256(
                            material_payload
                        ).hexdigest(),
                        expected_source_material_sha256=material_sha,
                        output_path=output_path,
                    ),
                    source_spec,
                )
                self.assertEqual(
                    (output_path.stat().st_dev, output_path.stat().st_ino),
                    output_identity,
                )

                class Stream:
                    def __init__(self) -> None:
                        self.buffer = io.BytesIO()

                stdout = Stream()
                cli_output = root / "specs/generated-source-spec-cli.v1.json"
                with mock.patch.object(target.sys, "stdout", stdout):
                    code = target.run_cli([
                        "source-spec",
                        "--project-root", str(root),
                        "--source-material", str(material_path),
                        "--source-material-file-sha256",
                        hashlib.sha256(material_payload).hexdigest(),
                        "--source-material-sha256", material_sha,
                        "--output", str(cli_output),
                    ])
                self.assertEqual(code, 0)
                result = json.loads(stdout.buffer.getvalue())
                self.assertEqual(result["artifact_kind"], target.SOURCE_SPEC_RESULT_KIND)
                self.assertEqual(result["source_spec_sha256"], material_sha)
                self.assertEqual(
                    cli_output.read_bytes(), canonical(source_spec, newline=True)
                )
            finally:
                fixture.close()

    def test_source_spec_materializer_recovers_physical_crash_and_lost_response(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                material_path, material = fixture.source_material("source-spec-resume")
                material_payload = material_path.read_bytes()
                material_sha = semantic(material)
                steps = (
                    "mid_write",
                    "post_fsync_pre_publish",
                    "post_publish_pre_parent_fsync",
                    None,
                )
                for position, step in enumerate(steps):
                    with self.subTest(step=step or "lost-response"):
                        output = root / f"specs/resumed-source-spec-{position}.json"
                        expected_boundary = (
                            output.name
                            if step is None
                            else f"{output.name}:{step}"
                        )

                        def crash(observed: str) -> None:
                            if observed == expected_boundary:
                                raise InjectedCrash(observed)

                        arguments = {
                            "project_root": root,
                            "source_material_path": material_path,
                            "expected_source_material_file_sha256": hashlib.sha256(
                                material_payload
                            ).hexdigest(),
                            "expected_source_material_sha256": material_sha,
                            "output_path": output,
                        }
                        with self.assertRaises(InjectedCrash):
                            target.materialize_publication_q4_authority_source_spec_v1(
                                **arguments,
                                after_artifact_commit=crash,
                            )
                        before = (
                            (output.stat().st_dev, output.stat().st_ino)
                            if output.exists()
                            else None
                        )
                        result = (
                            target.materialize_publication_q4_authority_source_spec_v1(
                                **arguments
                            )
                        )
                        self.assertEqual(result["source_spec_sha256"], material_sha)
                        self.assertEqual(output.read_bytes(), canonical(result, newline=True))
                        if before is not None:
                            self.assertEqual(
                                (output.stat().st_dev, output.stat().st_ino),
                                before,
                            )
            finally:
                fixture.close()

    def test_held_dirfd_read_rejects_parent_namespace_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            source_dir = root / "source"
            source_dir.mkdir()
            source_path = source_dir / "value.json"
            source_path.write_bytes(canonical({"value": "accepted"}, newline=True))
            moved_dir = root / "source-held"
            original_read = target.os.read
            swapped = False

            def racing_read(descriptor: int, size: int) -> bytes:
                nonlocal swapped
                if not swapped:
                    swapped = True
                    source_dir.rename(moved_dir)
                    source_dir.mkdir()
                    (source_dir / "value.json").write_bytes(
                        canonical({"value": "foreign"}, newline=True)
                    )
                return original_read(descriptor, size)

            with mock.patch.object(target.os, "read", side_effect=racing_read):
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthorityPlanPipelineV1Error,
                    "custody changed|directory custody changed|changed while being read",
                ):
                    target._read_bytes_descriptor(
                        root, source_path, "racing source material",
                    )
            self.assertTrue(swapped)

    def test_receipt_tail_rejects_injected_namespace_member(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "transactions").mkdir()
            original_write = (
                target.PhysicalRootCustodyV1.commit_or_adopt_exact_identity
            )

            def injecting_write(
                custody: object,
                value: object,
                payload: bytes,
                **kwargs: object,
            ) -> tuple[dict[str, object], tuple[int, int], str]:
                result = original_write(custody, value, payload, **kwargs)
                if Path(value).name == "payload.json":
                    injected = root / "transactions/injected/injected.json"
                    injected.write_bytes(b"injected\n")
                    injected.chmod(0o400)
                return result

            with mock.patch.object(
                target.PhysicalRootCustodyV1,
                "commit_or_adopt_exact_identity",
                new=injecting_write,
            ):
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthorityPlanPipelineV1Error,
                    "namespace members drifted",
                ):
                    target._write_payloads_receipt_last(
                        root=root,
                        output_dir="transactions/injected",
                        payloads=[("payload.json", b"payload\n")],
                        receipt_name="receipt.json",
                        receipt_payload=b"receipt\n",
                        label="injected transaction",
                    )
            self.assertFalse(
                (root / "transactions/injected/receipt.json").exists()
            )

    def test_receipt_last_helper_resumes_every_commit_boundary_exactly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "transactions").mkdir()
            boundaries = (
                "output_directory",
                "a.json:mid_write",
                "a.json:post_fsync_pre_publish",
                "a.json:post_publish_pre_parent_fsync",
                "a.json",
                "b.json",
                "receipt.json:mid_write",
                "receipt.json:post_fsync_pre_publish",
                "receipt.json:post_publish_pre_parent_fsync",
                "receipt.json",
            )
            for position, boundary in enumerate(boundaries):
                output = root / "transactions" / f"resume-{position}"

                def crash(observed: str, *, expected: str = boundary) -> None:
                    if observed == expected:
                        raise InjectedCrash(expected)

                arguments = {
                    "root": root,
                    "output_dir": output,
                    "payloads": [("a.json", b"a\n"), ("b.json", b"b\n")],
                    "receipt_name": "receipt.json",
                    "receipt_payload": b"receipt\n",
                    "label": f"resumable transaction {position}",
                }
                with self.assertRaises(InjectedCrash):
                    target._write_payloads_receipt_last(
                        **arguments,
                        after_artifact_commit=crash,
                    )
                before = {
                    item.name: (item.stat().st_dev, item.stat().st_ino)
                    for item in output.iterdir()
                    if item.is_file()
                }
                target._write_payloads_receipt_last(**arguments)
                self.assertEqual(
                    sorted(item.name for item in output.iterdir()),
                    ["a.json", "b.json", "receipt.json"],
                )
                after = {
                    item.name: (item.stat().st_dev, item.stat().st_ino)
                    for item in output.iterdir()
                }
                for name, identity in before.items():
                    self.assertEqual(after[name], identity)
                self.assertEqual(output.stat().st_mode & 0o777, 0o500)
                target._write_payloads_receipt_last(**arguments)
                self.assertEqual(
                    {
                        item.name: (item.stat().st_dev, item.stat().st_ino)
                        for item in output.iterdir()
                    },
                    after,
                )

    def test_receipt_last_resume_rejects_tamper_foreign_redirect_and_aba(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "transactions").mkdir()

            def arguments(name: str) -> dict[str, object]:
                return {
                    "root": root,
                    "output_dir": root / "transactions" / name,
                    "payloads": [("a.json", b"a\n"), ("b.json", b"b\n")],
                    "receipt_name": "receipt.json",
                    "receipt_payload": b"receipt\n",
                    "label": name,
                }

            def crash_after_a(observed: str) -> None:
                if observed == "a.json":
                    raise InjectedCrash(observed)

            tamper_arguments = arguments("tamper")
            with self.assertRaises(InjectedCrash):
                target._write_payloads_receipt_last(
                    **tamper_arguments,
                    after_artifact_commit=crash_after_a,
                )
            tampered = root / "transactions/tamper/a.json"
            tampered.chmod(0o600)
            tampered.write_bytes(b"foreign\n")
            tampered.chmod(0o400)
            with self.assertRaisesRegex(
                Exception,
                "resumable payload drifted|exact immutable physical file",
            ):
                target._write_payloads_receipt_last(**tamper_arguments)
            self.assertEqual(tampered.read_bytes(), b"foreign\n")

            def crash_after_directory(observed: str) -> None:
                if observed == "output_directory":
                    raise InjectedCrash(observed)

            foreign_arguments = arguments("foreign")
            with self.assertRaises(InjectedCrash):
                target._write_payloads_receipt_last(
                    **foreign_arguments,
                    after_artifact_commit=crash_after_directory,
                )
            foreign = root / "transactions/foreign/foreign.json"
            foreign.write_bytes(b"preserve\n")
            with self.assertRaisesRegex(Exception, "exact resumable prefix"):
                target._write_payloads_receipt_last(**foreign_arguments)
            self.assertEqual(foreign.read_bytes(), b"preserve\n")

            redirect_arguments = arguments("redirect")
            with self.assertRaises(InjectedCrash):
                target._write_payloads_receipt_last(
                    **redirect_arguments,
                    after_artifact_commit=crash_after_directory,
                )
            redirected = root / "transactions/redirect"
            held = root / "transactions/redirect-held"
            redirected.rename(held)
            redirected.symlink_to(held, target_is_directory=True)
            with self.assertRaisesRegex(Exception, "link|custody|alias"):
                target._write_payloads_receipt_last(**redirect_arguments)
            self.assertEqual(list(held.iterdir()), [])

            aba_arguments = arguments("aba")

            def replace_exact(observed: str) -> None:
                if observed != "a.json":
                    return
                path = root / "transactions/aba/a.json"
                payload = path.read_bytes()
                path.unlink()
                path.write_bytes(payload)
                path.chmod(0o400)

            with self.assertRaisesRegex(
                Exception, "inode identity changed|namespace (?:changed|mutated)"
            ):
                target._write_payloads_receipt_last(
                    **aba_arguments,
                    after_artifact_commit=replace_exact,
                )
            self.assertFalse((root / "transactions/aba/receipt.json").exists())

    def test_real_phase1_and_phase2_resume_receipt_last_crash_windows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                spec_path, spec = fixture.source_spec("C")
                (root / "transactions/C").mkdir(parents=True, exist_ok=True)

                def crash_phase1(observed: str) -> None:
                    if observed == target.RUNTIME_PLAN_FILENAME:
                        raise InjectedCrash(observed)

                phase1_arguments = {
                    "project_root": root,
                    "source_spec_path": spec_path,
                    "expected_source_spec_file_sha256": hashlib.sha256(
                        spec_path.read_bytes()
                    ).hexdigest(),
                    "expected_source_spec_sha256": spec["source_spec_sha256"],
                    "output_dir": "transactions/C/phase1",
                }
                with self.assertRaises(InjectedCrash):
                    target.materialize_publication_q4_authority_plan_phase1_v1(
                        **phase1_arguments,
                        after_artifact_commit=crash_phase1,
                    )
                phase1_dir = root / "transactions/C/phase1"
                before_phase1 = {
                    item.name: (item.stat().st_dev, item.stat().st_ino)
                    for item in phase1_dir.iterdir()
                }
                phase1 = target.materialize_publication_q4_authority_plan_phase1_v1(
                    **phase1_arguments
                )
                self.assertEqual(len(phase1["runtime_authorities"]), 112)
                for item in phase1_dir.iterdir():
                    if item.name in before_phase1:
                        self.assertEqual(
                            (item.stat().st_dev, item.stat().st_ino),
                            before_phase1[item.name],
                        )

                phase1_path = phase1_dir / target.PHASE1_RECEIPT_FILENAME
                runtime_result, runtime_result_path = self.runtime_materialize(
                    root, phase1, spec
                )
                common_phase2 = {
                    "project_root": root,
                    "phase1_receipt_path": phase1_path,
                    "expected_phase1_receipt_file_sha256": hashlib.sha256(
                        phase1_path.read_bytes()
                    ).hexdigest(),
                    "expected_phase1_receipt_sha256": phase1["receipt_sha256"],
                    "runtime_materialization_result_path": runtime_result_path,
                    "expected_runtime_materialization_result_file_sha256": hashlib.sha256(
                        runtime_result_path.read_bytes()
                    ).hexdigest(),
                    "expected_runtime_materialization_result_sha256": runtime_result[
                        "result_sha256"
                    ],
                }
                for position, boundary in enumerate(
                    (
                        "output_directory",
                        target.SOURCE_PLAN_FILENAME,
                        target.PHASE2_RECEIPT_FILENAME,
                    )
                ):
                    phase2_arguments = {
                        **common_phase2,
                        "output_dir": f"transactions/C/phase2-{position}",
                    }

                    def crash_phase2(
                        observed: str, *, expected: str = boundary
                    ) -> None:
                        if observed == expected:
                            raise InjectedCrash(expected)

                    with self.assertRaises(InjectedCrash):
                        target.finalize_publication_q4_source_plan_phase2_v1(
                            **phase2_arguments,
                            after_artifact_commit=crash_phase2,
                        )
                    phase2_dir = root / f"transactions/C/phase2-{position}"
                    before_phase2 = {
                        item.name: (item.stat().st_dev, item.stat().st_ino)
                        for item in phase2_dir.iterdir()
                    }
                    phase2 = target.finalize_publication_q4_source_plan_phase2_v1(
                        **phase2_arguments
                    )
                    self.assertEqual(
                        phase2["phase1_receipt_sha256"], phase1["receipt_sha256"]
                    )
                    after_phase2 = {
                        item.name: (item.stat().st_dev, item.stat().st_ino)
                        for item in phase2_dir.iterdir()
                    }
                    for name, identity in before_phase2.items():
                        self.assertEqual(after_phase2[name], identity)
            finally:
                fixture.close()

    def test_cold_loader_rejects_exact_copy_inode_swap_restored_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                phase1, phase1_path, _spec = self.phase1(root, fixture, "A")
                expected_file_sha256 = hashlib.sha256(
                    phase1_path.read_bytes()
                ).hexdigest()
                invocation_path = root / phase1[
                    "publication_launcher_invocation_v3"
                ]["descriptor"]["path"]
                held_path = invocation_path.with_name(invocation_path.name + ".held")
                foreign_path = invocation_path.with_name(
                    invocation_path.name + ".foreign"
                )
                original_load = target._load_by_descriptor_from_custody
                swapped = False
                phase1_path.parent.chmod(0o700)

                def racing_load(*args: object, **kwargs: object) -> dict[str, object]:
                    nonlocal swapped
                    label = str(args[4] if len(args) > 4 else kwargs.get("label"))
                    if not swapped and label == "Q4 Phase1 launcher invocation":
                        swapped = True
                        invocation_path.rename(held_path)
                        shutil.copy2(held_path, invocation_path)
                        try:
                            return original_load(*args, **kwargs)
                        finally:
                            invocation_path.rename(foreign_path)
                            held_path.rename(invocation_path)
                    return original_load(*args, **kwargs)

                try:
                    with mock.patch.object(
                        target,
                        "_load_by_descriptor_from_custody",
                        side_effect=racing_load,
                    ):
                        with self.assertRaisesRegex(
                            target.PublicationQ4AuthorityPlanPipelineV1Error,
                            "descriptor/inode drifted",
                        ):
                            target.load_publication_q4_authority_plan_phase1_receipt_v1(
                                project_root=root,
                                receipt_path=phase1_path,
                                expected_receipt_file_sha256=expected_file_sha256,
                                expected_receipt_sha256=phase1["receipt_sha256"],
                            )
                    self.assertTrue(swapped)
                finally:
                    phase1_path.parent.chmod(0o500)
            finally:
                fixture.close()

    @unittest.skipUnless(os.name == "posix", "POSIX dirfd custody regression")
    def test_phase1_cold_loader_rejects_output_parent_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                phase1, phase1_path, _spec = self.phase1(root, fixture, "A")
                expected_file_sha256 = hashlib.sha256(
                    phase1_path.read_bytes()
                ).hexdigest()
                output_dir = phase1_path.parent
                held_dir = output_dir.with_name(output_dir.name + ".held")
                original_load = target._load_by_descriptor_from_custody
                swapped = False

                def racing_load(*args: object, **kwargs: object) -> dict[str, object]:
                    nonlocal swapped
                    label = str(args[4] if len(args) > 4 else kwargs.get("label"))
                    if not swapped and label == "Q4 Phase1 launcher invocation":
                        output_dir.rename(held_dir)
                        shutil.copytree(held_dir, output_dir, copy_function=shutil.copy2)
                        swapped = True
                    return original_load(*args, **kwargs)

                try:
                    with mock.patch.object(
                        target,
                        "_load_by_descriptor_from_custody",
                        side_effect=racing_load,
                    ):
                        with self.assertRaisesRegex(
                            target.PublicationQ4AuthorityPlanPipelineV1Error,
                            "custody changed|directory custody changed",
                        ):
                            target.load_publication_q4_authority_plan_phase1_receipt_v1(
                                project_root=root,
                                receipt_path=phase1_path,
                                expected_receipt_file_sha256=expected_file_sha256,
                                expected_receipt_sha256=phase1["receipt_sha256"],
                            )
                    self.assertTrue(swapped)
                finally:
                    if swapped:
                        output_dir.chmod(0o700)
                        shutil.rmtree(output_dir)
                        held_dir.rename(output_dir)
            finally:
                fixture.close()

    @unittest.skipUnless(os.name == "posix", "POSIX dirfd custody regression")
    def test_phase2_cold_loader_holds_parent_across_lineage_loads(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                phase1, phase1_path, spec = self.phase1(root, fixture, "A")
                runtime_result, runtime_result_path = self.runtime_materialize(
                    root, phase1, spec
                )
                runtime_registry_path = root / runtime_result[
                    "runtime_candidate_registry"
                ]["path"]
                runtime_registry_value = json.loads(
                    runtime_registry_path.read_bytes()
                )
                self.assertEqual(
                    len(runtime_registry_value["authority_snapshots"]), 112
                )
                for snapshot in runtime_registry_value["authority_snapshots"]:
                    system = snapshot["coordinate"]["system"]
                    self.assertEqual(
                        set(snapshot["runtime_input_template"]["files"]),
                        set(
                            runtime_contract.RUNTIME_MODULE_BY_SYSTEM[
                                system
                            ].FILE_ROLES
                        ),
                    )
                phase2 = target.finalize_publication_q4_source_plan_phase2_v1(
                    project_root=root,
                    phase1_receipt_path=phase1_path,
                    expected_phase1_receipt_file_sha256=hashlib.sha256(
                        phase1_path.read_bytes()
                    ).hexdigest(),
                    expected_phase1_receipt_sha256=phase1["receipt_sha256"],
                    runtime_materialization_result_path=runtime_result_path,
                    expected_runtime_materialization_result_file_sha256=(
                        hashlib.sha256(runtime_result_path.read_bytes()).hexdigest()
                    ),
                    expected_runtime_materialization_result_sha256=runtime_result[
                        "result_sha256"
                    ],
                    output_dir="transactions/A/phase2-parent-race",
                )
                phase2_path = (
                    root / "transactions/A/phase2-parent-race"
                    / target.PHASE2_RECEIPT_FILENAME
                )
                expected_file_sha256 = hashlib.sha256(
                    phase2_path.read_bytes()
                ).hexdigest()
                output_dir = phase2_path.parent
                held_dir = output_dir.with_name(output_dir.name + ".held")
                original_phase1_load = (
                    target.load_publication_q4_authority_plan_phase1_receipt_v1
                )
                swapped = False

                def racing_phase1_load(
                    *args: object, **kwargs: object,
                ) -> dict[str, object]:
                    nonlocal swapped
                    if not swapped:
                        output_dir.rename(held_dir)
                        shutil.copytree(held_dir, output_dir, copy_function=shutil.copy2)
                        swapped = True
                    return original_phase1_load(*args, **kwargs)

                try:
                    with mock.patch.object(
                        target,
                        "load_publication_q4_authority_plan_phase1_receipt_v1",
                        side_effect=racing_phase1_load,
                    ):
                        with self.assertRaisesRegex(
                            target.PublicationQ4AuthorityPlanPipelineV1Error,
                            "custody changed|directory custody changed",
                        ):
                            target.load_publication_q4_source_plan_phase2_receipt_v1(
                                project_root=root,
                                receipt_path=phase2_path,
                                expected_receipt_file_sha256=expected_file_sha256,
                                expected_receipt_sha256=phase2["receipt_sha256"],
                            )
                    self.assertTrue(swapped)
                finally:
                    if swapped:
                        output_dir.chmod(0o700)
                        shutil.rmtree(output_dir)
                        held_dir.rename(output_dir)
            finally:
                fixture.close()

    def test_phase1_and_phase2_form_one_materializable_receipt_chain(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                phase1, phase1_path, spec = self.phase1(root, fixture, "A")
                self.assertEqual(len(phase1["runtime_authorities"]), 112)
                self.assertEqual(len(phase1["launcher_runtime_authorities"]), 4)
                loaded1 = target.load_publication_q4_authority_plan_phase1_receipt_v1(
                    project_root=root, receipt_path=phase1_path,
                    expected_receipt_file_sha256=hashlib.sha256(phase1_path.read_bytes()).hexdigest(),
                    expected_receipt_sha256=phase1["receipt_sha256"],
                )
                self.assertEqual(loaded1, phase1)
                runtime_result, runtime_result_path = self.runtime_materialize(
                    root, phase1, spec
                )
                phase2 = target.finalize_publication_q4_source_plan_phase2_v1(
                    project_root=root,
                    phase1_receipt_path=phase1_path,
                    expected_phase1_receipt_file_sha256=hashlib.sha256(phase1_path.read_bytes()).hexdigest(),
                    expected_phase1_receipt_sha256=phase1["receipt_sha256"],
                    runtime_materialization_result_path=runtime_result_path,
                    expected_runtime_materialization_result_file_sha256=hashlib.sha256(runtime_result_path.read_bytes()).hexdigest(),
                    expected_runtime_materialization_result_sha256=runtime_result["result_sha256"],
                    output_dir="transactions/A/phase2",
                )
                phase2_path = root / "transactions/A/phase2" / target.PHASE2_RECEIPT_FILENAME
                loaded2 = target.load_publication_q4_source_plan_phase2_receipt_v1(
                    project_root=root, receipt_path=phase2_path,
                    expected_receipt_file_sha256=hashlib.sha256(phase2_path.read_bytes()).hexdigest(),
                    expected_receipt_sha256=phase2["receipt_sha256"],
                )
                source_plan_path = root / loaded2["source_registry_path_plan"]["descriptor"]["path"]
                source_result = source_registry.materialize_backend_q4_two_phase_source_registry_v1(
                    project_root=root, path_plan_path=source_plan_path,
                    expected_plan_file_sha256=hashlib.sha256(source_plan_path.read_bytes()).hexdigest(),
                    expected_plan_sha256=loaded2["source_registry_path_plan"]["content_identity_sha256"],
                    output_path=spec["planned_outputs"]["source_registry_path"],
                    result_output_path=spec["planned_outputs"][
                        "source_materialization_result_path"
                    ],
                    dependencies=fixture.dependencies(runtime_result["runtime_candidate_registry"]),
                )
                source_result_path = root / spec["planned_outputs"]["source_materialization_result_path"]
                self.assertEqual(
                    source_result["status"], "materialized_accepted_physical_q4_sources"
                )
                self.assertEqual(
                    source_result_path.read_bytes(), canonical(source_result, newline=True)
                )
                runtime_calibrations = source_result["identity_inputs"][
                    "policy_qualification"
                ]["runtime_calibrations"]
                self.assertEqual(
                    runtime_calibrations,
                    fixture.policy_calibrations,
                )
                self.assertEqual(
                    len(
                        {
                            item["path"]
                            for item in runtime_calibrations.values()
                        }
                    ),
                    4,
                )
                for system, item in runtime_calibrations.items():
                    self.assertEqual(
                        json.loads((root / item["path"]).read_bytes()),
                        fixture.policy_calibration_value["calibrations"][system],
                    )
                phase1_identities = {
                    item.name: (item.stat().st_dev, item.stat().st_ino)
                    for item in phase1_path.parent.iterdir()
                }
                resumed_phase1 = (
                    target.materialize_publication_q4_authority_plan_phase1_v1(
                        project_root=root, source_spec_path=root / "specs/A.json",
                        expected_source_spec_file_sha256=hashlib.sha256((root / "specs/A.json").read_bytes()).hexdigest(),
                        expected_source_spec_sha256=spec["source_spec_sha256"],
                        output_dir="transactions/A/phase1",
                    )
                )
                self.assertEqual(resumed_phase1, phase1)
                self.assertEqual(
                    {
                        item.name: (item.stat().st_dev, item.stat().st_ino)
                        for item in phase1_path.parent.iterdir()
                    },
                    phase1_identities,
                )

                phase1_dir = phase1_path.parent
                phase1_extra = phase1_dir / "untracked.json"
                phase1_dir.chmod(0o700)
                phase1_extra.write_bytes(b"untracked\n")
                phase1_dir.chmod(0o500)
                try:
                    with self.assertRaisesRegex(
                        target.PublicationQ4AuthorityPlanPipelineV1Error,
                        "namespace members drifted",
                    ):
                        target.load_publication_q4_authority_plan_phase1_receipt_v1(
                            project_root=root, receipt_path=phase1_path,
                            expected_receipt_file_sha256=hashlib.sha256(
                                phase1_path.read_bytes()
                            ).hexdigest(),
                            expected_receipt_sha256=phase1["receipt_sha256"],
                        )
                finally:
                    phase1_dir.chmod(0o700)
                    phase1_extra.unlink()
                    phase1_dir.chmod(0o500)

                phase2_dir = phase2_path.parent
                phase2_extra = phase2_dir / "untracked.json"
                phase2_dir.chmod(0o700)
                phase2_extra.write_bytes(b"untracked\n")
                phase2_dir.chmod(0o500)
                try:
                    with self.assertRaisesRegex(
                        target.PublicationQ4AuthorityPlanPipelineV1Error,
                        "namespace members drifted",
                    ):
                        target.load_publication_q4_source_plan_phase2_receipt_v1(
                            project_root=root, receipt_path=phase2_path,
                            expected_receipt_file_sha256=hashlib.sha256(
                                phase2_path.read_bytes()
                            ).hexdigest(),
                            expected_receipt_sha256=phase2["receipt_sha256"],
                        )
                finally:
                    phase2_dir.chmod(0o700)
                    phase2_extra.unlink()
                    phase2_dir.chmod(0o500)
            finally:
                fixture.close()

    def test_recomputed_foreign_runtime_result_cannot_cross_phase1_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                phase1_a, path_a, _spec_a = self.phase1(root, fixture, "A")
                phase1_b, _path_b, spec_b = self.phase1(root, fixture, "B")
                result_b, result_b_path = self.runtime_materialize(root, phase1_b, spec_b)
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthorityPlanPipelineV1Error,
                    "cross-run|planned runtime|plan binding",
                ):
                    target.finalize_publication_q4_source_plan_phase2_v1(
                        project_root=root,
                        phase1_receipt_path=path_a,
                        expected_phase1_receipt_file_sha256=hashlib.sha256(path_a.read_bytes()).hexdigest(),
                        expected_phase1_receipt_sha256=phase1_a["receipt_sha256"],
                        runtime_materialization_result_path=result_b_path,
                        expected_runtime_materialization_result_file_sha256=hashlib.sha256(result_b_path.read_bytes()).hexdigest(),
                        expected_runtime_materialization_result_sha256=result_b["result_sha256"],
                        output_dir="transactions/A/phase2-foreign",
                    )
                self.assertFalse(
                    (root / "transactions/A/phase2-foreign" / target.PHASE2_RECEIPT_FILENAME).exists()
                )
            finally:
                fixture.close()

    def test_same_plan_forged_registry_and_result_cannot_cross_phase1(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            fixture = Fixture(root)
            try:
                phase1, phase1_path, spec = self.phase1(root, fixture, "A")
                runtime_result, runtime_result_path = self.runtime_materialize(
                    root, phase1, spec
                )
                registry_path = root / runtime_result[
                    "runtime_candidate_registry"
                ]["path"]
                forged_registry = json.loads(registry_path.read_bytes())
                snapshot = forged_registry["authority_snapshots"][0]
                snapshot["runtime_input_template"]["scratch_root"] = (
                    "/var/tmp/vast-publication-forged-same-plan"
                )
                snapshot["authority_snapshot_sha256"] = semantic({
                    key: copy.deepcopy(item)
                    for key, item in snapshot.items()
                    if key != "authority_snapshot_sha256"
                })
                forged_registry["registry_sha256"] = semantic({
                    key: copy.deepcopy(item)
                    for key, item in forged_registry.items()
                    if key != "registry_sha256"
                })
                registry_path.chmod(0o600)
                registry_path.write_bytes(canonical(forged_registry, newline=True))

                forged_result = copy.deepcopy(runtime_result)
                forged_result["runtime_candidate_registry"] = fixture.descriptor(
                    registry_path
                )
                forged_result["runtime_candidate_registry_sha256"] = (
                    forged_registry["registry_sha256"]
                )
                forged_result["result_sha256"] = semantic({
                    key: copy.deepcopy(item)
                    for key, item in forged_result.items()
                    if key != "result_sha256"
                })
                runtime_result_path.chmod(0o600)
                runtime_result_path.write_bytes(
                    canonical(forged_result, newline=True)
                )
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthorityPlanPipelineV1Error,
                    "crossbinding failed|plan-pinned authority/template",
                ):
                    target.finalize_publication_q4_source_plan_phase2_v1(
                        project_root=root,
                        phase1_receipt_path=phase1_path,
                        expected_phase1_receipt_file_sha256=hashlib.sha256(
                            phase1_path.read_bytes()
                        ).hexdigest(),
                        expected_phase1_receipt_sha256=phase1[
                            "receipt_sha256"
                        ],
                        runtime_materialization_result_path=runtime_result_path,
                        expected_runtime_materialization_result_file_sha256=(
                            hashlib.sha256(
                                runtime_result_path.read_bytes()
                            ).hexdigest()
                        ),
                        expected_runtime_materialization_result_sha256=(
                            forged_result["result_sha256"]
                        ),
                        output_dir="transactions/A/phase2-forged-same-plan",
                    )
                self.assertFalse(
                    (
                        root
                        / "transactions/A/phase2-forged-same-plan"
                        / target.PHASE2_RECEIPT_FILENAME
                    ).exists()
                )
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main()
