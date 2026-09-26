from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_q4_two_phase_source_registry_v1 as target  # noqa: E402
from test_checkpoint_external_execution_manifest import worker_manifest_fixture, producer as native_producer


def canonical(value: object, *, newline: bool = True) -> bytes:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return payload + (b"\n" if newline else b"")


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def semantic(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


class InjectedCrash(BaseException):
    pass


@unittest.skipUnless(
    os.name == "posix" and sys.platform.startswith("linux"),
    "physical UNIX socket registry is WSL/Linux-only",
)
class BackendQ4TwoPhaseSourceRegistryV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.inputs = self.root / "inputs"
        self.inputs.mkdir()
        self.engine_path = self.root / "engine.sock"
        self.analytics_path = self.root / "analytics.sock"
        self.engine = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.analytics = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.engine.bind(str(self.engine_path))
        self.analytics.bind(str(self.analytics_path))
        self._make_inputs()

    def tearDown(self) -> None:
        self.analytics.close()
        self.engine.close()
        self.temporary.cleanup()

    def _plain_file(self, name: str, value: object | None = None) -> dict[str, object]:
        path = self.inputs / name
        write_json(path, {"fixture": name} if value is None else value)
        return descriptor(self.root, path)

    @staticmethod
    def _socket_binding(path: Path, *, endpoint: bool) -> dict[str, object]:
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

    def _make_inputs(self) -> None:
        self.parity_receipt = self._plain_file("parity-receipt.json")
        self.parity_manifest = self._plain_file("parity-manifest.json")
        self.parity_assessment = self._plain_file("parity-assessment.json")
        self.parity_binding = self._plain_file("parity-binding.json")
        self.execution_config = self._plain_file("execution-config.json")
        self.binding_index = self._plain_file("binding-index.json")
        self.policy_receipt = self._plain_file("policy-receipt.json")
        self.workers = worker_manifest_fixture(self.execution_config)
        self.policy_capability = self._plain_file("policy-capability.json", self.workers.policy)
        self.policy_calibration_values = {
            system: {
                "schema_version": 1,
                "artifact_kind": "vast_publication_policy_calibration",
                "system": system,
                "policy_contract_sha256": semantic("policy-contract"),
                "costs": {},
            }
            for system in target.SYSTEMS
        }
        self.policy_calibrations = {
            system: self._plain_file(
                f"policy-calibration-{system}.json",
                self.policy_calibration_values[system],
            )
            for system in target.SYSTEMS
        }
        self.policy_calibration_value = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_calibration_mapping",
            "policy_contract_sha256": semantic("policy-contract"),
            "aggregation_rule": (
                "median_of_balanced_native_codec_topology_cells_v1"
            ),
            "minimum_samples_per_branch_cell": 30,
            "calibrations": copy.deepcopy(self.policy_calibration_values),
        }
        self.policy_calibration = self._plain_file(
            "policy-calibration-mapping.json",
            self.policy_calibration_value,
        )
        self.resource_receipt = self._plain_file("resource-receipt.json")
        self.resource_capability = self._plain_file("resource-capability.json")
        self.service_authority = self._plain_file("service-authority.json")
        self.preprocessing_contract = self._plain_file("accepted-preprocessing.json")
        self.preprocessing_receipt = self._plain_file(
            "accepted-preprocessing-receipt.json"
        )
        self.service_identity = semantic("analytics-service")
        write_json(
            self.root / self.policy_receipt["path"],
            {
                "outputs": {
                    "capability_manifest": {
                        **self.policy_capability,
                        "path": Path(self.policy_capability["path"]).name,
                    },
                    "calibration_mapping": {
                        **self.policy_calibration,
                        "path": Path(self.policy_calibration["path"]).name,
                    },
                }
            },
        )
        self.policy_receipt = descriptor(
            self.root, self.root / self.policy_receipt["path"],
        )
        write_json(
            self.root / self.resource_receipt["path"],
            {
                "outputs": {
                    "capability_manifest": {
                        **self.resource_capability,
                        "path": Path(self.resource_capability["path"]).name,
                    }
                }
            },
        )
        self.resource_receipt = descriptor(
            self.root, self.root / self.resource_receipt["path"],
        )
        write_json(
            self.root / self.preprocessing_receipt["path"],
            {
                "accepted_policy_capability_manifest": self.policy_capability,
                "accepted_policy_calibration_mapping": self.policy_calibration,
            },
        )
        self.preprocessing_receipt = descriptor(
            self.root, self.root / self.preprocessing_receipt["path"],
        )

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
        self.preprocessing_authority = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_guardian_accepted_policy_preprocessing_contract_authority_v1"
            ),
            "preprocessing_contract_content_sha256": self.workers.preprocessing,
            "preprocessing_contract_file_sha256": self.preprocessing_contract[
                "sha256"
            ],
            "materialization_receipt_identity_sha256": semantic(
                "preprocessing-receipt"
            ),
            "materialization_receipt_file_sha256": self.preprocessing_receipt[
                "sha256"
            ],
            "predecessor_qualification_preprocessing_receipt_identity_sha256": semantic(
                "predecessor-receipt"
            ),
            "predecessor_qualification_preprocessing_receipt_file_sha256": semantic(
                "predecessor-receipt-file"
            ),
            "accepted_policy_qualification_receipt_identity_sha256": semantic(
                "accepted-policy-receipt"
            ),
            "accepted_policy_qualification_receipt_file_sha256": self.policy_receipt[
                "sha256"
            ],
            "accepted_policy_capability_manifest_file_sha256": self.policy_capability[
                "sha256"
            ],
            "accepted_policy_capability_manifest_content_sha256": semantic(
                "accepted-policy-capability"
            ),
            "accepted_policy_calibration_mapping_file_sha256": self.policy_calibration[
                "sha256"
            ],
            "accepted_policy_calibration_mapping_content_sha256": semantic(
                "accepted-policy-calibration"
            ),
            "qualification_execution_closure_receipt_identity_sha256": semantic(
                "execution-closure"
            ),
            "qualification_execution_closure_receipt_file_sha256": semantic(
                "execution-closure-file"
            ),
            "execution_config_identity_sha256": semantic("execution"),
            "execution_config_file_sha256": self.execution_config["sha256"],
            "binding_set_identity_sha256": semantic("binding-set"),
            "bindings_identity_sha256": semantic("bindings"),
            "binding_set_index_file_sha256": self.binding_index["sha256"],
            "binding_preprocessing_consensus_sha256": semantic(
                "binding-preprocessing-consensus"
            ),
            "worker_image_ids": {
                resource: row["image_id"]
                for resource, row in self.worker_images.items()
            },
            "policy_contract_sha256": semantic("policy-contract"),
        }
        self.system_images = {
            system: {
                "reference": f"vast/{system}:publication-v4",
                "image_id": "sha256:" + str(index + 3) * 64,
            }
            for index, system in enumerate(target.SYSTEMS)
        }
        patch_unsigned = {
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
        patch_value = {
            **patch_unsigned,
            "patch_sha256": target.canonical_sha256(patch_unsigned),
        }
        self.patch = self._plain_file("image-patch.json", patch_value)
        self.patch_value = patch_value

        self.upstream = {
            "dataset_manifest_sha256": semantic("dataset"),
            "policy_contract_sha256": semantic("policy-contract"),
            "policy_qualification_receipt_sha256": semantic("policy-receipt"),
            "resource_contract_identity_sha256": semantic("resource-contract"),
            "resource_qualification_receipt_sha256": semantic("resource-receipt"),
            "analytics_execution_config_identity_sha256": semantic("execution"),
            "model_parity_manifest_identity_sha256": semantic("parity-manifest"),
            "model_parity_acceptance_binding_sha256": semantic("parity-binding"),
        }
        engine = self._socket_binding(self.engine_path, endpoint=False)
        endpoint = self._socket_binding(self.analytics_path, endpoint=True)
        self.runtime_role_files: dict[str, dict[str, dict[str, object]]] = {}
        for system in target.SYSTEMS:
            roles: dict[str, dict[str, object]] = {}
            for role in target.RUNTIME_FILE_ROLES_BY_SYSTEM[system]:
                if role == "analytics_execution_manifest":
                    _, payload, _ = native_producer._adapter_asset(self.workers.inventory, system=system, final_root=ROOT / "artifacts/test-q4-registry")
                    manifest = json.loads(payload)
                    item = self._plain_file(f"{system}-execution-manifest.json", manifest)
                elif role == "policy_capability_manifest":
                    item = self.policy_capability
                elif role == "policy_calibration":
                    item = self.policy_calibrations[system]
                else:
                    item = self._plain_file(f"{system}-{role}.json")
                roles[role] = dict(item)
            self.runtime_role_files[system] = roles
        snapshots: list[dict[str, object]] = []
        for system in target.SYSTEMS:
            for codec in target.CODECS:
                for topology in target.TOPOLOGIES:
                    for policy in target.POLICIES:
                        snapshots.append({
                            "coordinate": {
                                "system": system, "codec": codec,
                                "topology_kind": topology, "policy": policy,
                            },
                            "upstream_identities": dict(self.upstream),
                            "runtime_input_template": {
                                "container_engine_socket": dict(engine),
                                "endpoint_sockets": [dict(endpoint)],
                                "container_image": {
                                    "image_id": self.system_images[system]["image_id"],
                                },
                                "preprocessing_contract_sha256": self.workers.preprocessing,
                                "files": {
                                    role: {
                                        **item,
                                        "container_path": (
                                            f"/opt/vast/{system}/{role}.json"
                                        ),
                                    }
                                    for role, item in self.runtime_role_files[
                                        system
                                    ].items()
                                },
                            },
                        })
        registry_unsigned = {
            "schema_version": 4,
            "artifact_kind": "vast_publication_q4_runtime_candidate_registry_v4",
            "status": "physically_prepared_runtime_candidates",
            "accepted_as_input": True,
            "authorization_eligible": False,
            "execution_authorized": False,
            "dataset_bindings": [],
            "authority_snapshots": snapshots,
        }
        self.registry_value = {
            **registry_unsigned,
            "registry_sha256": target.canonical_sha256(registry_unsigned),
        }
        self.runtime_registry = self._plain_file(
            "runtime-candidate-registry.json", self.registry_value,
        )

        plan = target.build_backend_q4_two_phase_source_registry_path_plan_v1(
            model_parity_acceptance_receipt_path=self.parity_receipt["path"],
            policy_qualification_receipt_path=self.policy_receipt["path"],
            policy_capability_manifest_path=self.policy_capability["path"],
            policy_calibration_mapping_path=self.policy_calibration["path"],
            resource_qualification_receipt_path=self.resource_receipt["path"],
            resource_capability_manifest_path=self.resource_capability["path"],
            runtime_candidate_registry_path=self.runtime_registry["path"],
            analytics_service_authority_path=self.service_authority["path"],
            guardian_preprocessing_contract_path=self.preprocessing_contract["path"],
            guardian_preprocessing_receipt_path=self.preprocessing_receipt["path"],
            expected_analytics_service_identity_sha256=self.service_identity,
        )
        self.plan_path = self.inputs / "source-path-plan.json"
        write_json(self.plan_path, plan)
        self.plan = plan

    def dependencies(self) -> target.BackendQ4SourceRegistryDependenciesV1:
        parity_files = [
            self.parity_receipt, self.parity_manifest, self.parity_assessment,
            self.parity_binding, self.patch, self.execution_config,
            self.binding_index,
        ]

        def load_parity(**_kwargs: object) -> dict[str, object]:
            return {
                "receipt": dict(self.parity_receipt),
                "accepted_manifest": dict(self.parity_manifest),
                "accepted_assessment": dict(self.parity_assessment),
                "binding_descriptor": dict(self.parity_binding),
                "binding_sha256": self.upstream["model_parity_acceptance_binding_sha256"],
                "accepted_manifest_content_identity_sha256": self.upstream[
                    "model_parity_manifest_identity_sha256"
                ],
                "files": [dict(item) for item in parity_files if item != self.parity_binding],
                "refresh_authority": {
                    "image_identity_patch": {
                        **self.patch,
                        "patch_sha256": self.patch_value["patch_sha256"],
                    },
                    "workers": {
                        resource: {
                            **row,
                            "worker_implementation_sha256": semantic(resource),
                        }
                        for resource, row in self.worker_images.items()
                    },
                    "execution_config": {
                        **self.execution_config,
                        "content_identity_sha256": self.upstream[
                            "analytics_execution_config_identity_sha256"
                        ],
                        "worker_projection_sha256": semantic("projection"),
                    },
                    "binding_set": {
                        "index": dict(self.binding_index),
                        "identity_sha256": semantic("binding-set"),
                        "bindings_identity_sha256": semantic("bindings"),
                    },
                },
            }

        def load_policy(**_kwargs: object) -> dict[str, object]:
            return {
                "receipt": dict(self.policy_receipt),
                "capability_manifest": dict(self.policy_capability),
                "calibration_mapping": dict(self.policy_calibration),
                "receipt_document": {
                    "dataset_manifest_sha256": self.upstream[
                        "dataset_manifest_sha256"
                    ],
                    "policy_contract_sha256": self.upstream["policy_contract_sha256"],
                    "sha256": self.upstream["policy_qualification_receipt_sha256"],
                },
                "files": [
                    dict(self.policy_receipt), dict(self.policy_capability),
                    dict(self.policy_calibration),
                ],
            }

        def load_resource(**_kwargs: object) -> dict[str, object]:
            return {
                "receipt": dict(self.resource_receipt),
                "capability_manifest": dict(self.resource_capability),
                "receipt_document": {
                    "dataset_manifest_sha256": self.upstream[
                        "dataset_manifest_sha256"
                    ],
                    "resource_contract_identity_sha256": self.upstream[
                        "resource_contract_identity_sha256"
                    ],
                    "sha256": self.upstream["resource_qualification_receipt_sha256"],
                },
                "files": [dict(self.resource_receipt), dict(self.resource_capability)],
            }

        def load_registry(**_kwargs: object) -> dict[str, object]:
            files = {self.runtime_registry["path"]: self.runtime_registry}
            for role_files in self.runtime_role_files.values():
                for item in role_files.values():
                    files[item["path"]] = item
            return {
                "registry": json.loads(json.dumps(self.registry_value)),
                "descriptor": dict(self.runtime_registry),
                "files": [
                    dict(files[path]) for path in sorted(files)
                ],
            }

        def load_service(**kwargs: object) -> dict[str, object]:
            self.assertEqual(kwargs["expected_front_socket"], self.analytics_path)
            self.assertEqual(
                kwargs["expected_execution_config_identity_sha256"],
                self.upstream["analytics_execution_config_identity_sha256"],
            )
            self.assertEqual(
                kwargs["expected_binding_set_identity_sha256"],
                semantic("binding-set"),
            )
            self.assertEqual(
                kwargs["expected_worker_image_ids"],
                {
                    resource: row["image_id"]
                    for resource, row in self.worker_images.items()
                },
            )
            self.assertEqual(
                kwargs["expected_preprocessing_contract_authority"],
                self.preprocessing_authority,
            )
            self.assertEqual(
                kwargs["expected_service_identity_sha256"],
                self.service_identity,
            )
            self.assertEqual(
                kwargs["expected_policy_contract_sha256"],
                self.upstream["policy_contract_sha256"],
            )
            return {
                "descriptor": dict(self.service_authority),
                "authority": {
                    "front_socket": self._socket_binding(
                        self.analytics_path, endpoint=False,
                    ),
                },
            }

        def load_preprocessing(**kwargs: object) -> dict[str, object]:
            self.assertEqual(
                kwargs["preprocessing_contract_path"],
                self.preprocessing_contract["path"],
            )
            self.assertEqual(
                kwargs["materialization_receipt_path"],
                self.preprocessing_receipt["path"],
            )
            self.assertEqual(
                kwargs["accepted_policy_capability_manifest_path"],
                self.policy_capability["path"],
            )
            return {
                "contract": dict(self.preprocessing_contract),
                "receipt": dict(self.preprocessing_receipt),
                "authority": copy.deepcopy(self.preprocessing_authority),
                "runtime_expectations": {
                    "execution_config_identity_sha256": self.upstream[
                        "analytics_execution_config_identity_sha256"
                    ],
                    "binding_set_identity_sha256": semantic("binding-set"),
                    "bindings_identity_sha256": semantic("bindings"),
                    "worker_image_ids": {
                        resource: row["image_id"]
                        for resource, row in self.worker_images.items()
                    },
                    "policy_contract_sha256": self.upstream[
                        "policy_contract_sha256"
                    ],
                    "preprocessing_contract_content_sha256": self.workers.preprocessing,
                },
                "files": [
                    dict(self.preprocessing_contract),
                    dict(self.preprocessing_receipt),
                ],
            }

        images = {
            row["reference"]: row["image_id"]
            for row in self.system_images.values()
        }
        images.update(
            (row["image"], row["image_id"])
            for row in self.worker_images.values()
        )

        def inspect_image(*, reference: str, **_kwargs: object) -> dict[str, str]:
            return {
                "reference": reference, "image_id": images[reference],
                "os": "linux", "architecture": "amd64",
            }

        return target.BackendQ4SourceRegistryDependenciesV1(
            load_model_parity=load_parity,
            load_policy_qualification=load_policy,
            load_resource_qualification=load_resource,
            load_runtime_candidate_registry=load_registry,
            load_accepted_guardian_preprocessing=load_preprocessing,
            load_service_authority=load_service,
            inspect_image=inspect_image,
        )

    def materialize(
        self,
        output: str = "q4-source-registry.json",
        *,
        after_artifact_commit: object = None,
    ) -> dict[str, Any]:
        return target.materialize_backend_q4_two_phase_source_registry_v1(
            project_root=self.root,
            path_plan_path=self.plan_path,
            expected_plan_file_sha256=hashlib.sha256(
                self.plan_path.read_bytes()
            ).hexdigest(),
            expected_plan_sha256=self.plan["plan_sha256"],
            output_path=self.root / output,
            result_output_path=self.root / f"{output}.result.json",
            dependencies=self.dependencies(),
            after_artifact_commit=after_artifact_commit,
        )

    def test_materializes_exact_registry_and_ready_identity_inputs(self) -> None:
        result = self.materialize("nested/source/q4-source-registry.json")
        registry_path = self.root / result["source_registry"]["path"]
        registry = json.loads(registry_path.read_bytes())
        self.assertEqual(
            set(registry),
            {
                "schema_version", "artifact_kind", "status", "accepted",
                "model_parity", "policy_qualification",
                "resource_qualification", "runtime_candidate_registry",
                "analytics_guardian", "files", "sockets", "images",
                "registry_sha256",
            },
        )
        self.assertEqual([row["role"] for row in registry["sockets"]], [
            "container_engine", "analytics_execution",
        ])
        self.assertEqual(
            [row["role"] for row in registry["images"]],
            sorted(target.IMAGE_ROLES),
        )
        self.assertEqual(
            set(result["identity_inputs"]),
            {
                "analytics_model_parity", "analytics_execution_layer",
                "policy_qualification", "resource_qualification",
            },
        )
        self.assertEqual(
            result["identity_inputs"]["policy_qualification"][
                "runtime_calibrations"
            ],
            self.policy_calibrations,
        )
        self.assertNotIn(
            "analytics_execution_manifest",
            self.registry_value["authority_snapshots"][0][
                "runtime_input_template"
            ]["files"],
        )
        loaded = target.load_backend_q4_two_phase_source_registry_v1(
            project_root=self.root,
            registry_path=registry_path,
            dependencies=self.dependencies(),
        )
        self.assertEqual(loaded["registry"], registry)
        self.assertEqual(loaded["identity_inputs"], result["identity_inputs"])
        result_path = self.root / "nested/source/q4-source-registry.json.result.json"
        identities = (registry_path.stat().st_ino, result_path.stat().st_ino)
        self.assertEqual(
            self.materialize("nested/source/q4-source-registry.json"),
            result,
        )
        self.assertEqual(
            (registry_path.stat().st_ino, result_path.stat().st_ino),
            identities,
        )

    def test_two_leaf_materializer_recovers_every_commit_and_lost_response(
        self,
    ) -> None:
        cases = (
            ("source_registry:mid_write", False, False),
            ("source_registry:post_fsync_pre_publish", False, False),
            ("source_registry:post_publish_pre_parent_fsync", True, False),
            ("source_registry", True, False),
            ("source_registry_materialization_result:mid_write", True, False),
            (
                "source_registry_materialization_result:post_fsync_pre_publish",
                True,
                False,
            ),
            (
                "source_registry_materialization_result:post_publish_pre_parent_fsync",
                True,
                True,
            ),
            ("source_registry_materialization_result", True, True),
        )
        for position, (boundary, registry_exists, result_exists) in enumerate(cases):
            output = f"resume-{position}/source-registry.json"

            def crash(observed: str) -> None:
                if observed == boundary:
                    raise InjectedCrash(observed)

            with self.subTest(boundary=boundary):
                with self.assertRaises(InjectedCrash):
                    self.materialize(output, after_artifact_commit=crash)
                registry_path = self.root / output
                result_path = self.root / f"{output}.result.json"
                self.assertEqual(registry_path.exists(), registry_exists)
                self.assertEqual(result_path.exists(), result_exists)
                registry_identity = (
                    registry_path.stat().st_ino if registry_path.exists() else None
                )
                result_identity = (
                    result_path.stat().st_ino if result_path.exists() else None
                )
                result = self.materialize(output)
                if registry_identity is not None:
                    self.assertEqual(registry_path.stat().st_ino, registry_identity)
                if result_identity is not None:
                    self.assertEqual(result_path.stat().st_ino, result_identity)
                committed_identities = (
                    registry_path.stat().st_ino,
                    result_path.stat().st_ino,
                )
                self.assertEqual(self.materialize(output), result)
                self.assertEqual(
                    (registry_path.stat().st_ino, result_path.stat().st_ino),
                    committed_identities,
                )

    def test_two_leaf_resume_rejects_tamper_foreign_result_and_redirect(
        self,
    ) -> None:
        output = "partial/source-registry.json"

        def crash(boundary: str) -> None:
            if boundary == "source_registry":
                raise InjectedCrash(boundary)

        with self.assertRaises(InjectedCrash):
            self.materialize(output, after_artifact_commit=crash)
        registry_path = self.root / output
        registry_path.chmod(0o644)
        registry_path.write_bytes(b'{"foreign":true}\n')
        registry_path.chmod(0o444)
        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "drifted|custody",
        ):
            self.materialize(output)

        result_only = self.root / "result-only/source-registry.json.result.json"
        result_only.parent.mkdir(parents=True)
        result_only.write_bytes(b'{"foreign":true}\n')
        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "without its causal registry",
        ):
            self.materialize("result-only/source-registry.json")

        foreign = self.root / "foreign-output"
        foreign.mkdir()
        (self.root / "redirect-output").symlink_to(
            foreign, target_is_directory=True
        )
        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "physical|custody|directory|link/reparse",
        ):
            self.materialize("redirect-output/source-registry.json")

    def test_two_leaf_materializer_rejects_same_invocation_aba(self) -> None:
        output = "aba/source-registry.json"

        def replace(boundary: str) -> None:
            if boundary != "source_registry":
                return
            path = self.root / output
            payload = path.read_bytes()
            path.unlink()
            path.write_bytes(payload)
            path.chmod(0o444)

        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "mutated|changed|custody",
        ):
            self.materialize(output, after_artifact_commit=replace)

    def test_runtime_file_roles_are_exact_for_each_real_abi(self) -> None:
        deepstream = self.registry_value["authority_snapshots"][0][
            "runtime_input_template"
        ]["files"]
        deepstream["analytics_execution_manifest"] = {
            **self.execution_config,
            "container_path": "/opt/vast/forged-execution.json",
        }
        self.runtime_role_files["deepstream"]["analytics_execution_manifest"] = self.execution_config
        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "file-role coverage",
        ):
            self.materialize("extra-deepstream-role.json")

        deepstream.pop("analytics_execution_manifest")
        self.runtime_role_files["deepstream"].pop("analytics_execution_manifest")
        openvino_position = len(target.CODECS) * len(target.TOPOLOGIES) * len(
            target.POLICIES
        ) * 2
        openvino = self.registry_value["authority_snapshots"][
            openvino_position
        ]["runtime_input_template"]["files"]
        openvino.pop("analytics_execution_manifest")
        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "file-role coverage",
        ):
            self.materialize("missing-openvino-role.json")

    def test_native_execution_manifest_rejects_repinned_authority_drift(self) -> None:
        system = "openvino_gva"
        original_descriptor = self.runtime_role_files[system]["analytics_execution_manifest"]
        original = json.loads((self.root / original_descriptor["path"]).read_bytes())
        mutations = {
            "config": lambda v: v["execution_config"].update(sha256="0" * 64),
            "policy": lambda v: v.update(policy_capability_manifest_sha256="0" * 64),
            "worker": lambda v: v["branches"]["damage"]["cpu"].update(worker_image_id="sha256:" + "0" * 64),
            "branch": lambda v: v["branches"].pop("damage"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                value = copy.deepcopy(original)
                mutate(value)
                changed = self._plain_file(f"drift-{label}.json", value)
                self.runtime_role_files[system]["analytics_execution_manifest"] = changed
                for snapshot in self.registry_value["authority_snapshots"]:
                    if snapshot["coordinate"]["system"] == system:
                        snapshot["runtime_input_template"]["files"]["analytics_execution_manifest"] = {**changed, "container_path": "/opt/vast/execution.json"}
                with self.assertRaisesRegex(target.BackendQ4SourceRegistryV1Error, "execution manifest"):
                    self.materialize(f"reject-{label}/registry.json")

    def test_runtime_calibration_projection_must_equal_accepted_mapping(self) -> None:
        system = "deepstream"
        path = self.root / self.policy_calibrations[system]["path"]
        drifted = copy.deepcopy(self.policy_calibration_values[system])
        drifted["costs"] = {"forged": {}}
        write_json(path, drifted)
        changed_descriptor = descriptor(self.root, path)
        self.policy_calibrations[system] = changed_descriptor
        for snapshot in self.registry_value["authority_snapshots"]:
            if snapshot["coordinate"]["system"] == system:
                snapshot["runtime_input_template"]["files"][
                    "policy_calibration"
                ] = {
                    **changed_descriptor,
                    "container_path": f"/opt/vast/{system}/policy_calibration.json",
                }
        self.runtime_role_files[system]["policy_calibration"] = dict(
            changed_descriptor
        )

        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "differs from accepted mapping",
        ):
            self.materialize("forged-calibration-projection.json")

    def test_default_service_loader_supplies_only_independent_expected_authority(
        self,
    ) -> None:
        import checkpoint_gstreamer_analytics_sidecar as sidecar

        checked = {
            "front_socket": self._socket_binding(
                self.analytics_path, endpoint=False,
            ),
            "service_identity_sha256": semantic("self-anchored-service"),
        }
        expectations = {
            "expected_front_socket": self.analytics_path,
            "expected_execution_config_identity_sha256": self.upstream[
                "analytics_execution_config_identity_sha256"
            ],
            "expected_binding_set_identity_sha256": semantic("binding-set"),
            "expected_worker_image_ids": {
                resource: row["image_id"]
                for resource, row in self.worker_images.items()
            },
            "expected_preprocessing_contract_authority": copy.deepcopy(
                self.preprocessing_authority
            ),
            "expected_service_identity_sha256": self.service_identity,
            "expected_policy_contract_sha256": self.upstream[
                "policy_contract_sha256"
            ],
        }
        with (
            mock.patch.object(
                sidecar,
                "validate_publication_sidecar_service_authority_v1",
                return_value=checked,
            ) as validate,
            mock.patch.object(
                sidecar,
                "assert_publication_sidecar_service_authority_v1",
                return_value=checked,
            ) as assert_authority,
        ):
            loaded = target._default_load_service_authority(
                project_root=self.root,
                authority_path=self.service_authority["path"],
                **expectations,
            )
        validate.assert_called_once()
        assert_authority.assert_called_once_with(checked, **expectations)
        self.assertEqual(loaded["authority"], checked)
        self.assertNotEqual(
            checked["service_identity_sha256"],
            expectations["expected_service_identity_sha256"],
        )

    def test_tamper_and_stale_upstream_fail_closed_after_commit(self) -> None:
        result = self.materialize()
        registry_path = self.root / result["source_registry"]["path"]
        (self.root / self.execution_config["path"]).write_bytes(b"tamper\n")
        with self.assertRaisesRegex(target.BackendQ4SourceRegistryV1Error, "descriptor|closure"):
            target.load_backend_q4_two_phase_source_registry_v1(
                project_root=self.root,
                registry_path=registry_path,
                dependencies=self.dependencies(),
            )
        with self.assertRaisesRegex(
            target.BackendQ4SourceRegistryV1Error,
            "descriptor|closure",
        ):
            self.materialize()

        write_json(
            self.root / self.execution_config["path"],
            {"fixture": "execution-config.json"},
        )
        self.registry_value["authority_snapshots"][0]["upstream_identities"][
            "dataset_manifest_sha256"
        ] = semantic("stale-dataset")
        with self.assertRaisesRegex(target.BackendQ4SourceRegistryV1Error, "upstream"):
            self.materialize("stale-registry.json")

    def test_socket_and_patch_image_drift_fail_closed(self) -> None:
        self.registry_value["authority_snapshots"][1]["runtime_input_template"][
            "endpoint_sockets"
        ][0]["inode"] += 1
        with self.assertRaisesRegex(target.BackendQ4SourceRegistryV1Error, "socket"):
            self.materialize("socket-drift.json")

        self.registry_value["authority_snapshots"][1]["runtime_input_template"][
            "endpoint_sockets"
        ][0]["inode"] -= 1
        self.registry_value["authority_snapshots"][0]["runtime_input_template"][
            "container_image"
        ]["image_id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(target.BackendQ4SourceRegistryV1Error, "image"):
            self.materialize("image-drift.json")

    def test_cli_exact_hashes_canonical_stdout_and_rejects_extra_argv(self) -> None:
        argv = [
            "--project-root", str(self.root),
            "--plan", str(self.plan_path),
            "--plan-file-sha256", hashlib.sha256(
                self.plan_path.read_bytes()
            ).hexdigest(),
            "--plan-sha256", self.plan["plan_sha256"],
            "--output", str(self.root / "cli-registry.json"),
            "--result-output", str(self.root / "cli-registry.result.json"),
        ]
        output = io.StringIO()
        errors = io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            code = target.run_cli(argv, dependencies=self.dependencies())
        self.assertEqual(code, 0)
        self.assertEqual(errors.getvalue(), "")
        value = json.loads(output.getvalue())
        self.assertEqual(output.getvalue().encode("ascii"), canonical(value))
        result_path = self.root / "cli-registry.result.json"
        self.assertTrue(result_path.is_file())
        self.assertEqual(json.loads(result_path.read_bytes()), value)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertNotEqual(
                target.run_cli(argv + ["--extra", "x"], dependencies=self.dependencies()),
                0,
            )


if __name__ == "__main__":
    unittest.main()
