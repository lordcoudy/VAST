from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import struct
import sys
import tempfile
import threading
import unittest
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification_execution_closure_v1 as target  # noqa: E402
import publication_policy_qualification_execution_code_closure_v1 as code_closure_target  # noqa: E402
from publication_guardian_runtime_expectations_v1 import (  # noqa: E402
    runtime_expectations_from_preprocessing_receipt_v1,
)


ACCEPTANCE_FILENAME = target.ACCEPTANCE_FILENAME
FINAL_NAMESPACE_FILES = target.FINAL_NAMESPACE_FILES
qualification_pilot_cells_v2 = target.qualification_pilot_cells_v2


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def semantic_sha(value: object) -> str:
    return hashlib.sha256(canonical(value).rstrip(b"\n")).hexdigest()


def write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def descriptor(root: Path, path: Path) -> dict[str, object]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def identity_record(root: Path, path: Path) -> dict[str, object]:
    item = descriptor(root, path)
    info = path.lstat()
    return {
        **item,
        "snapshot": {
            "st_dev": int(info.st_dev),
            "st_ino": int(info.st_ino),
            "st_mode": int(info.st_mode),
            "st_nlink": int(info.st_nlink),
            "st_size": int(info.st_size),
            "st_mtime_ns": int(info.st_mtime_ns),
            "st_ctime_ns": int(info.st_ctime_ns),
            "st_file_attributes": int(getattr(info, "st_file_attributes", 0)),
        },
    }


def guardian_capacity() -> dict[str, object]:
    frozen_per_connection = 600 * 6 * len(target.BRANCHES) * 240
    cells = 32 + 560 + 560 + 5600
    return {
        "frozen_contract": {
            "frames_per_second": 600,
            "logical_streams": 6,
            "analytics_branches": len(target.BRANCHES),
            "cell_seconds_upper_bound": 240,
            "cell_count": cells,
            "connections_per_cell_upper_bound": 24,
            "unmargined_requests_per_connection": frozen_per_connection,
            "unmargined_connections": cells * 24,
            "unmargined_total_requests": frozen_per_connection * cells,
        },
        "controlled_margin": {"numerator": 5, "denominator": 4},
        "max_connections": 202560,
        "max_requests_per_connection": 4320000,
        "max_total_requests": 29168640000,
        "worker_request_upper_bound": 29168640000,
        "connection_limit_semantics": "upper_bound_not_exact_drain",
        "connection_eof_semantics": "clean_eof_below_upper_bound_allowed",
        "request_evidence_semantics": (
            "constant_memory_operational_counters_non_authorizing"
        ),
    }


def guardian_peer_identity(pid: int, *, uid: int = 1000, gid: int = 1000) -> dict[str, object]:
    raw = struct.pack("3i", pid, uid, gid)
    core: dict[str, object] = {
        "schema_version": 2,
        "policy_version": 2,
        "peer_identity_mode": "native-visible",
        "peer_pid": pid,
        "peer_uid": uid,
        "peer_gid": gid,
        "peer_raw_hex": raw.hex(),
        "peer_raw_sha256": hashlib.sha256(raw).hexdigest(),
        "container_state_pid": pid,
        "peer_uid_gid_exact": True,
        "container_state_pid_positive": True,
        "pid_positive": True,
        "pid_matches_container_state_pid": True,
        "peer_pid_visible_in_controller_namespace": True,
        "peer_pid_state_pid_equality_attested": True,
        "peer_identity_by_pid_attested": True,
        "peer_socket_to_container_pid_binding_attested": True,
        "docker_desktop_containerd_backend_attested": False,
        "wsl2_platform_attested": False,
        "platform_observation_sha256": None,
        "native_ext4_private_socket_attested": False,
        "native_ipc_custody_sha256": None,
        "protocol_nonce_capability_handshake_required": True,
        "protocol_nonce_capability_handshake_performed": True,
        "global_eight_worker_handshake_barrier_attested": True,
        "peer_identity_by_protocol_capability_attested": True,
    }
    return {**core, "identity_sha256": semantic_sha(core)}


def rewrite_lifecycle(
    path: Path, mutate: Callable[[dict[str, object]], None]
) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="ascii"))
    mutate(value)
    counters = value["counters"]
    counter_core = {
        key: item for key, item in counters.items() if key != "aggregate_sha256"
    }
    counters["aggregate_sha256"] = semantic_sha(counter_core)
    lifecycle_core = {
        key: item for key, item in value.items() if key != "identity"
    }
    value["identity"] = {
        "algorithm": "sha256",
        "sha256": semantic_sha(lifecycle_core),
    }
    write_json(path, value)
    return value


def model_parity_refresh_authority() -> dict[str, object]:
    def frozen_descriptor(path: str, identity: str) -> dict[str, object]:
        return {"path": path, "size_bytes": 1, "sha256": identity}

    return {
        "image_identity_patch": {},
        "execution_config": {
            **frozen_descriptor("authorities/execution-config.json", "a" * 64),
            "content_identity_sha256": "5" * 64,
            "worker_projection_sha256": "b" * 64,
        },
        "binding_set": {
            "index": frozen_descriptor(
                "authorities/bindings/index.json", "c" * 64
            ),
            "identity_sha256": "6" * 64,
            "bindings_identity_sha256": "7" * 64,
            "bindings": {
                f"{branch}:{resource}": frozen_descriptor(
                    f"authorities/bindings/{branch}-{resource}.json",
                    semantic_sha({"branch": branch, "resource": resource}),
                )
                for branch in (
                    "plate_number",
                    "vehicle_type",
                    "damage",
                    "foreign_object",
                )
                for resource in ("cpu", "gpu")
            },
        },
        "workers": {
            resource: {
                "image": f"vast/{resource}:fixture",
                "image_id": "sha256:"
                + ("8" if resource == "cpu" else "9") * 64,
                "worker_implementation_sha256": semantic_sha(
                    {"worker": resource}
                ),
                "source_set_sha256": semantic_sha({"source": resource}),
                "receipt_sha256": semantic_sha({"receipt": resource}),
            }
            for resource in ("cpu", "gpu")
        },
        "runtime_probes": {},
    }


class Fixture:
    def __init__(
        self,
        root: Path,
        *,
        service_execution_config_identity_sha256: str | None = None,
    ) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.hardware_resource_collector = root / "scripts/collect_metrics.py"
        self.hardware_resource_collector.parent.mkdir(parents=True, exist_ok=True)
        self.hardware_resource_collector.write_bytes(
            b"# qualification collector fixture\n"
        )
        for module in code_closure_target.SEED_MODULES:
            source = root / "scripts" / f"{module}.py"
            if not source.exists():
                source.write_text("from __future__ import annotations\n", encoding="utf-8")
        self.execution_code_closure_receipt = (
            root / "inputs/qualification-execution-code-closure.v1.json"
        )
        code_closure_target.materialize_execution_code_closure_v1(
            project_root=root,
            receipt_path=self.execution_code_closure_receipt,
        )
        self.cells = qualification_pilot_cells_v2()
        self.transaction = root / "inputs/qualification_input_transaction.v2.receipt.json"
        self.contract = root / "inputs/checkpoint_analytics_preprocessing_contract.v1.json"
        self.preprocessing_receipt = (
            root / "inputs/checkpoint_analytics_preprocessing_contract.v1.receipt.json"
        )
        self.runtime_root = root / "inputs/qualification-runtime-inputs-v2"
        self.runtime_receipt = (
            self.runtime_root / "qualification-runtime-inputs.materialization.v2.json"
        )
        self.authority_path = root / "guardian/service_authority.v1.json"
        self.lifecycle_path = root / "guardian/service_lifecycle.v1.json"
        self.pilot_root = root / "pilots"
        self.checkpoint = root / "qualification-execution-checkpoint.v3.json"
        self.output = root / "execution-closure"
        self.front_socket = (
            root / "guardian-runtime/analytics-execution.sock"
        ).as_posix()
        self.control_socket = (
            root / "guardian-runtime/analytics-control.sock"
        ).as_posix()
        self.service_execution_config_identity_sha256 = (
            service_execution_config_identity_sha256
        )
        self._materialize()

    def _materialize(self) -> None:
        self.qualification_source_files: dict[str, Path] = {}
        for name in (
            "candidate_index",
            "candidate_manifest",
            "candidate_receipt",
            "bootstrap_mapping",
            "bootstrap_receipt",
            *(f"bootstrap_calibration_{system}" for system in target.SYSTEMS),
        ):
            path = self.root / "inputs/checkpoint-anchor" / f"{name}.json"
            write_json(path, {"fixture": name})
            self.qualification_source_files[name] = path
        source_sha = {
            name: descriptor(self.root, path)["sha256"]
            for name, path in self.qualification_source_files.items()
        }
        self.fragments: dict[str, Path] = {}
        fragment_descriptors: dict[str, dict[str, object]] = {}
        for system in target.SYSTEMS:
            fragment = self.root / f"inputs/fragments/{system}/qualification_fragment.json"
            write_json(
                fragment,
                {
                    "schema_version": 1,
                    "artifact_kind": "fixture-qualification-fragment",
                    "system": system,
                },
            )
            self.fragments[system] = fragment
            fragment_descriptors[system] = descriptor(self.root, fragment)
        transaction_unsigned: dict[str, object] = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_input_transaction_v2",
            "status": "qualification_inputs_materialized_nonaccepted",
            "scope": "forced_resource_qualification_pilots_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "systems": ["deepstream", "savant", "openvino_gva", "gstreamer_custom"],
            "cell_count": 32,
            "hardware_resource_collector": descriptor(
                self.root, self.hardware_resource_collector
            ),
            "fragments": fragment_descriptors,
        }
        transaction = {
            **transaction_unsigned,
            "receipt_sha256": semantic_sha(transaction_unsigned),
        }
        write_json(self.transaction, transaction)

        contract = {"contract_id": "fixture-preprocessing-v1"}
        write_json(self.contract, contract)
        preprocessing_unsigned: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_guardian_preprocessing_contract_materialization_v1",
            "status": "materialized_from_verified_v4_acceptance",
            "preprocessing_contract": descriptor(self.root, self.contract),
            "preprocessing_contract_content_sha256": semantic_sha(contract),
            "qualification_transaction_receipt": descriptor(
                self.root, self.transaction
            ),
            "qualification_transaction_receipt_sha256": transaction[
                "receipt_sha256"
            ],
            "candidate_manifest": {
                "path": "inputs/candidate.json",
                "size_bytes": 1,
                "sha256": "1" * 64,
            },
            "policy_contract_sha256": "b" * 64,
            "model_parity_refresh_authority": (
                model_parity_refresh_authority()
            ),
        }
        preprocessing = {
            **preprocessing_unsigned,
            "receipt_sha256": semantic_sha(preprocessing_unsigned),
        }
        write_json(self.preprocessing_receipt, preprocessing)
        self.preprocessing_authority = {
            "schema_version": 1,
            "artifact_kind": "vast_guardian_preprocessing_contract_authority_v1",
            "preprocessing_contract_content_sha256": preprocessing[
                "preprocessing_contract_content_sha256"
            ],
            "preprocessing_contract_file_sha256": descriptor(
                self.root, self.contract
            )["sha256"],
            "materialization_receipt_identity_sha256": preprocessing[
                "receipt_sha256"
            ],
            "materialization_receipt_file_sha256": descriptor(
                self.root, self.preprocessing_receipt
            )["sha256"],
            "qualification_transaction_receipt_sha256": transaction[
                "receipt_sha256"
            ],
            "candidate_manifest_file_sha256": "1" * 64,
            "candidate_receipt_identity_sha256": "c" * 64,
            "model_parity_acceptance_binding_sha256": "d" * 64,
            "policy_contract_sha256": preprocessing["policy_contract_sha256"],
        }
        self.runtime_expectations = (
            runtime_expectations_from_preprocessing_receipt_v1(preprocessing)
        )

        socket_pin = {
            "path": self.front_socket,
            "device": 11,
            "inode": 12,
            "owner_uid": 1000,
            "owner_gid": 1000,
        }
        bundle_records: list[dict[str, object]] = []
        for cell in self.cells:
            relative = (
                Path(cell.system)
                / cell.resource
                / cell.codec
                / f"{cell.topology_kind}.json"
            )
            bundle = self.runtime_root / relative
            bundle_unsigned: dict[str, object] = {
                "schema_version": 2,
                "artifact_kind": "vast_qualification_native_runtime_input_bundle_v2",
                "status": "materialized_for_native_qualification_only",
                "accepted": False,
                "publication_ready": False,
                "authorization_eligible": False,
                "scope": "pre_run_policy_and_full_resource_qualification_only",
                "system": cell.system,
                "resource": cell.resource,
                "codec": cell.codec,
                "topology_kind": cell.topology_kind,
                "run_id": cell.run_id,
                "arm_id": cell.arm_id,
                "hardware_resource_collector": descriptor(
                    self.root, self.hardware_resource_collector
                ),
            }
            bundle_value = {
                **bundle_unsigned,
                "bundle_sha256": semantic_sha(bundle_unsigned),
            }
            write_json(bundle, bundle_value)
            item = descriptor(self.root, bundle)
            bundle_records.append(
                {
                    "arm_id": cell.arm_id,
                    "run_id": cell.run_id,
                    "path": relative.as_posix(),
                    "size_bytes": item["size_bytes"],
                    "sha256": item["sha256"],
                    "bundle_sha256": bundle_value["bundle_sha256"],
                }
            )
        runtime_unsigned: dict[str, object] = {
            "schema_version": 2,
            "artifact_kind": "vast_qualification_native_runtime_input_materialization_v2",
            "status": "materialized_for_native_qualification_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "scope": "pre_run_policy_and_full_resource_qualification_only",
            "matrix_sha256": target.matrix_sha256(self.cells),
            "inputs": {
                "candidate_index_sha256": source_sha["candidate_index"],
                "candidate_manifest_sha256": source_sha["candidate_manifest"],
                "candidate_receipt_sha256": source_sha["candidate_receipt"],
                "bootstrap_mapping_sha256": source_sha["bootstrap_mapping"],
                "bootstrap_receipt_sha256": source_sha["bootstrap_receipt"],
                "qualification_input_transaction_receipt_sha256": (
                    descriptor(self.root, self.transaction)["sha256"]
                ),
                "hardware_resource_collector": descriptor(
                    self.root, self.hardware_resource_collector
                ),
                "inventory_sha256": "a" * 64,
            },
            "container_engine": {"fixture": True},
            "live_sockets": {
                "container_engine": {
                    "path": "/var/run/docker.sock",
                    "device": 1,
                    "inode": 2,
                    "owner_uid": 0,
                    "owner_gid": 0,
                },
                "analytics_execution": socket_pin,
            },
            "bundles": bundle_records,
            "container_images": {},
            "device_probes": {},
            "generated_assets": [],
            "blockers": [
                "qualification_runtime_inputs_are_not_production_authority"
            ],
        }
        runtime = {
            **runtime_unsigned,
            "receipt_sha256": semantic_sha(runtime_unsigned),
        }
        write_json(self.runtime_receipt, runtime)

        owner = {
            "pid": 42,
            "proc_stat_starttime_ticks": 123456,
            "uid": 1000,
            "gid": 1000,
        }
        worker_images = {
            "cpu": "sha256:" + "8" * 64,
            "gpu": "sha256:" + "9" * 64,
        }
        capacity = guardian_capacity()
        control_pin = {
            **socket_pin,
            "path": self.control_socket,
            "inode": 13,
        }
        peers = []
        for ordinal, (branch, resource) in enumerate(
            (
                (branch, resource)
                for branch in target.BRANCHES
                for resource in target.RESOURCES
            ),
            start=1,
        ):
            peer = guardian_peer_identity(100 + ordinal)
            peers.append(
                {
                    "branch": branch,
                    "resource": resource,
                    "worker_image_id": worker_images[resource],
                    "peer_identity": peer,
                    "peer_identity_sha256": peer["identity_sha256"],
                }
            )
        authority_core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_gstreamer_analytics_production_service_authority_v1"
            ),
            "service_mode": "bounded_production_guardian_v1",
            "status": "live_operational_nonpublication",
            "publication_ready": False,
            "accepted_evidence_written": False,
            "lifecycle_id": "a" * 32,
            "owner_process": owner,
            "front_socket": socket_pin,
            "control_socket": control_pin,
            "protocol_identity_sha256": target.PROTOCOL_IDENTITY_SHA256,
            "execution_config_identity_sha256": (
                self.service_execution_config_identity_sha256
                or self.runtime_expectations[
                    "execution_config_identity_sha256"
                ]
            ),
            "binding_set_identity_sha256": "6" * 64,
            "preprocessing_contract_authority": self.preprocessing_authority,
            "worker_image_ids": worker_images,
            "capacity": capacity,
            "worker_count": 8,
            "attested_worker_count": 8,
            "peer_identities": peers,
            "started_monotonic_ns": 1_000,
            "readiness_artifact_path": self.authority_path.as_posix(),
            "lifecycle_artifact_path": self.lifecycle_path.as_posix(),
        }
        service_material = {
            "lifecycle_id": authority_core["lifecycle_id"],
            "owner_process": owner,
            "front_socket": socket_pin,
            "control_socket": control_pin,
            "protocol_identity_sha256": authority_core[
                "protocol_identity_sha256"
            ],
            "execution_config_identity_sha256": authority_core[
                "execution_config_identity_sha256"
            ],
            "binding_set_identity_sha256": authority_core[
                "binding_set_identity_sha256"
            ],
            "preprocessing_contract_authority": self.preprocessing_authority,
            "worker_image_ids": worker_images,
            "capacity": capacity,
        }
        authority_core["service_identity_sha256"] = semantic_sha(service_material)
        authority = {
            **authority_core,
            "service_authority_sha256": semantic_sha(authority_core),
        }
        write_json(self.authority_path, authority)
        stop_command = {
            "schema_version": 1,
            "message_type": "production_guardian_stop",
            "lifecycle_id": authority["lifecycle_id"],
            "service_authority_sha256": authority["service_authority_sha256"],
            "nonce": "f" * 64,
        }
        stop_core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_gstreamer_analytics_guardian_stop_attestation_v1"
            ),
            "lifecycle_id": authority["lifecycle_id"],
            "service_authority_sha256": authority["service_authority_sha256"],
            "nonce": stop_command["nonce"],
            "canonical_command_sha256": semantic_sha(stop_command),
            "peer_process": {
                "pid": 777,
                "uid": owner["uid"],
                "gid": owner["gid"],
                "proc_stat_starttime_ticks": 654321,
            },
            "accepted_monotonic_ns": 2_000,
        }
        stop_attestation = {
            **stop_core,
            "identity": {"algorithm": "sha256", "sha256": semantic_sha(stop_core)},
        }
        requests_by_worker = {
            f"{branch}:{resource}": 16
            for branch in target.BRANCHES
            for resource in target.RESOURCES
        }
        counter_core: dict[str, object] = {
            "connections_accepted": 32,
            "connections_active": 0,
            "connections_clean_eof": 32,
            "connections_failed": 0,
            "connections_shutdown_closed": 0,
            "requests_started": 128,
            "requests_completed": 128,
            "requests_failed": 0,
            "requests_by_worker": requests_by_worker,
            "evidence_role": "operational_non_authorizing_aggregate",
        }
        counters = {
            **counter_core,
            "aggregate_sha256": semantic_sha(counter_core),
        }
        runtime_directory = Path(self.front_socket).parent
        runtime_directory.mkdir(parents=True, exist_ok=True)
        retirement_directory = self.root / (
            ".vast-gst-analytics-retired-" + str(authority["lifecycle_id"])
        )
        retirement_directory.mkdir(mode=0o700)
        retirement_metadata = retirement_directory.lstat()
        active_names = [
            *(
                f"worker-{branch}-{resource}.sock"
                for branch in target.BRANCHES
                for resource in target.RESOURCES
            ),
            Path(self.front_socket).name,
            Path(self.control_socket).name,
        ]
        retired_socket_nodes: list[dict[str, object]] = []
        for ordinal, active_name in enumerate(active_names):
            retired_name = f"retired-{ordinal:02d}-{active_name}"
            retired_path = retirement_directory / retired_name
            bind_path = self.root / f".retired-source-{ordinal:02d}.sock"
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                endpoint.bind(str(bind_path))
            finally:
                endpoint.close()
            bind_path.rename(retired_path)
            metadata = retired_path.lstat()
            retired_core: dict[str, object] = {
                "schema_version": 1,
                "artifact_kind": (
                    "vast_gstreamer_analytics_retired_socket_node_v1"
                ),
                "lifecycle_id": authority["lifecycle_id"],
                "active_name": active_name,
                "retired_name": retired_name,
                "retirement_state": "retired_verified",
                "socket_identity": {
                    "st_dev": int(metadata.st_dev),
                    "st_ino": int(metadata.st_ino),
                    "st_mode_type": int(metadata.st_mode & 0o170000),
                    "st_nlink": int(metadata.st_nlink),
                },
                "retirement_directory": {
                    "path": retirement_directory.as_posix(),
                    "st_dev": int(retirement_metadata.st_dev),
                    "st_ino": int(retirement_metadata.st_ino),
                },
            }
            retired_socket_nodes.append(
                {
                    **retired_core,
                    "identity": {
                        "algorithm": "sha256",
                        "sha256": semantic_sha(retired_core),
                    },
                }
            )
        authority_payload = canonical(authority)
        lifecycle_core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_gstreamer_analytics_production_service_lifecycle_v1"
            ),
            "service_mode": "bounded_production_guardian_v1",
            "status": "clean_stop_nonpublication",
            "publication_ready": False,
            "accepted_evidence_written": False,
            "lifecycle_id": authority["lifecycle_id"],
            "service_identity_sha256": authority["service_identity_sha256"],
            "service_authority_sha256": authority["service_authority_sha256"],
            "readiness_artifact": {
                "path": authority["readiness_artifact_path"],
                "size_bytes": len(authority_payload),
                "sha256": hashlib.sha256(authority_payload).hexdigest(),
            },
            "front_socket": authority["front_socket"],
            "control_socket": authority["control_socket"],
            "capacity": capacity,
            "started_monotonic_ns": 1_000,
            "finished_monotonic_ns": 3_000,
            "duration_ns": 2_000,
            "guardian_stop_attestation": stop_attestation,
            "counters": counters,
            "cleanup_errors": [],
            "retired_socket_nodes": retired_socket_nodes,
            "failure": None,
            "evidence_role": "operational_non_authorizing_lifecycle",
        }
        lifecycle = {
            **lifecycle_core,
            "identity": {
                "algorithm": "sha256",
                "sha256": semantic_sha(lifecycle_core),
            },
        }
        write_json(self.lifecycle_path, lifecycle)

        completed: list[dict[str, object]] = []
        runtime_by_arm = {item["arm_id"]: item for item in bundle_records}
        runtime_receipt_descriptor = descriptor(self.root, self.runtime_receipt)
        transaction_descriptor = descriptor(self.root, self.transaction)
        preprocessing_receipt_descriptor = descriptor(
            self.root, self.preprocessing_receipt
        )
        authority_descriptor = descriptor(self.root, self.authority_path)
        for cell in self.cells:
            arm = (
                self.pilot_root
                / cell.system
                / cell.resource
                / cell.codec
                / cell.topology_kind
            )
            evidence: dict[str, dict[str, object]] = {}
            for name in FINAL_NAMESPACE_FILES:
                path = arm / name
                if name == ACCEPTANCE_FILENAME:
                    bundle_record = runtime_by_arm[cell.arm_id]
                    bundle_path = self.runtime_root / str(bundle_record["path"])
                    write_json(
                        path,
                        {
                            "schema_version": 1,
                            "artifact_kind": "fixture-qualification-acceptance",
                            "arm_id": cell.arm_id,
                            "run_id": cell.run_id,
                            "coordinate": {
                                "system": cell.system,
                                "resource": cell.resource,
                                "codec": cell.codec,
                                "topology_kind": cell.topology_kind,
                            },
                            "operational_binding": {
                                "hardware_resource_collector": descriptor(
                                    self.root,
                                    self.hardware_resource_collector,
                                ),
                                "qualification_input_transaction_receipt": (
                                    transaction_descriptor
                                ),
                                "qualification_input_transaction_receipt_identity_sha256": (
                                    transaction["receipt_sha256"]
                                ),
                                "runtime_input_materialization_receipt": (
                                    runtime_receipt_descriptor
                                ),
                                "runtime_input_materialization_receipt_identity_sha256": (
                                    runtime["receipt_sha256"]
                                ),
                                "runtime_input_bundle": descriptor(
                                    self.root, bundle_path
                                ),
                                "runtime_input_bundle_identity_sha256": (
                                    bundle_record["bundle_sha256"]
                                ),
                                "guardian_service_authority": authority_descriptor,
                                "guardian_service_authority_identity_sha256": (
                                    authority["service_authority_sha256"]
                                ),
                                "guardian_preprocessing_contract_receipt": (
                                    preprocessing_receipt_descriptor
                                ),
                                "guardian_preprocessing_contract_receipt_identity_sha256": (
                                    preprocessing["receipt_sha256"]
                                ),
                            },
                            "sha256": "4" * 64,
                        },
                    )
                elif name == "publication_policy_decisions.jsonl":
                    records: list[dict[str, object]] = []
                    for branch in target.BRANCHES:
                        decision_id = f"{cell.arm_id}:{branch}:{cell.resource}"
                        record_core: dict[str, object] = {
                            "schema_version": 1,
                            "system": cell.system,
                            "branch": branch,
                            "selected_resource": cell.resource,
                            "decision_id": decision_id,
                            "record_status": "accepted_native_runtime_decision",
                            "native_decision_evidence": {
                                "decision_id": decision_id,
                                "system": cell.system,
                                "branch": branch,
                                "selected_resource": cell.resource,
                                "telemetry_source": "native",
                                "terminal_status": "completed",
                            },
                        }
                        records.append(
                            {**record_core, "sha256": semantic_sha(record_core)}
                        )
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b"".join(canonical(record) for record in records))
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(f"{cell.arm_id}:{name}\n", encoding="utf-8")
                evidence[name] = descriptor(self.root, path)
            completed.append(
                {
                    "system": cell.system,
                    "resource": cell.resource,
                    "codec": cell.codec,
                    "topology_kind": cell.topology_kind,
                    "scenario": cell.scenario,
                    "policy": cell.policy,
                    "deadline_ms": cell.deadline_ms,
                    "duration_s": cell.duration_s,
                    "run_id": cell.run_id,
                    "arm_id": cell.arm_id,
                    "pilot_path": arm.relative_to(self.pilot_root).as_posix(),
                    "acceptance": evidence[ACCEPTANCE_FILENAME],
                    "evidence": evidence,
                }
            )
        checkpoint_inputs = {
            "candidate_index": source_sha["candidate_index"],
            "candidate_manifest": source_sha["candidate_manifest"],
            "candidate_receipt": source_sha["candidate_receipt"],
            "bootstrap_mapping": source_sha["bootstrap_mapping"],
            "bootstrap_receipt": source_sha["bootstrap_receipt"],
            "qualification_input_transaction_receipt": (
                transaction_descriptor["sha256"]
            ),
            "hardware_resource_collector": descriptor(
                self.root, self.hardware_resource_collector
            )["sha256"],
            "runtime_input_materialization_receipt": (
                runtime_receipt_descriptor["sha256"]
            ),
            "guardian_service_authority": authority_descriptor["sha256"],
            "guardian_preprocessing_contract": descriptor(
                self.root, self.contract
            )["sha256"],
            "guardian_preprocessing_contract_receipt": (
                preprocessing_receipt_descriptor["sha256"]
            ),
            **{
                f"bootstrap_calibration_{system}": source_sha[
                    f"bootstrap_calibration_{system}"
                ]
                for system in target.SYSTEMS
            },
            **{
                f"native_runtime_bundle_{arm_id}": item["sha256"]
                for arm_id, item in runtime_by_arm.items()
            },
        }
        closure_receipt = json.loads(
            self.execution_code_closure_receipt.read_text(encoding="ascii")
        )
        anchored_paths = {
            *self.qualification_source_files.values(),
            self.transaction,
            self.hardware_resource_collector,
            self.runtime_receipt,
            self.authority_path,
            self.contract,
            self.preprocessing_receipt,
            self.execution_code_closure_receipt,
            *(
                self.runtime_root / str(item["path"])
                for item in bundle_records
            ),
            *(
                self.root / str(item["path"])
                for item in closure_receipt["project_sources"]
            ),
        }
        input_identity = {
            "schema_version": 1,
            "named_sha256": checkpoint_inputs,
            "files": [
                identity_record(self.root, path)
                for path in sorted(
                    anchored_paths,
                    key=lambda item: item.relative_to(self.root).as_posix(),
                )
            ],
            "execution_code_closure_receipt_path": (
                self.execution_code_closure_receipt.relative_to(self.root).as_posix()
            ),
            "execution_code_closure_receipt_sha256": closure_receipt[
                "receipt_sha256"
            ],
            "execution_code_source_paths": [
                item["path"] for item in closure_receipt["project_sources"]
            ],
            "interpreter": closure_receipt["interpreter"],
        }
        checkpoint_unsigned: dict[str, object] = {
            "schema_version": 3,
            "artifact_kind": "vast_publication_policy_qualification_pilot_execution_v3",
            "status": "completed",
            "matrix_sha256": target.matrix_sha256(self.cells),
            "input_sha256": checkpoint_inputs,
            "input_identity": input_identity,
            "completed": completed,
            "publication_ready": False,
            "authorization_eligible": False,
            "blockers": ["qualification_pilots_are_not_full_publication_arms"],
        }
        checkpoint = {
            **checkpoint_unsigned,
            "checkpoint_sha256": semantic_sha(checkpoint_unsigned),
        }
        write_json(self.checkpoint, checkpoint)

    def dependencies(self) -> target.ExecutionClosureDependenciesV1:
        def load_preprocessing(**_kwargs: object) -> dict[str, object]:
            receipt = json.loads(self.preprocessing_receipt.read_text(encoding="ascii"))
            contract = json.loads(self.contract.read_text(encoding="ascii"))
            return {
                "preprocessing_contract": contract,
                "receipt": receipt,
                "authority": copy.deepcopy(self.preprocessing_authority),
            }

        def validate_authority(
            value: object, **expected: object
        ) -> dict[str, object]:
            if type(value) is not dict:
                raise RuntimeError("authority")
            required = {
                "expected_front_socket",
                "expected_execution_config_identity_sha256",
                "expected_binding_set_identity_sha256",
                "expected_worker_image_ids",
                "expected_preprocessing_contract_authority",
                "expected_service_identity_sha256",
                "expected_policy_contract_sha256",
            }
            if set(expected) != required:
                raise RuntimeError("authority expected inputs")
            if (
                expected["expected_front_socket"]
                != value["front_socket"]["path"]
                or expected["expected_execution_config_identity_sha256"]
                != value["execution_config_identity_sha256"]
                or expected["expected_binding_set_identity_sha256"]
                != value["binding_set_identity_sha256"]
                or expected["expected_worker_image_ids"]
                != value["worker_image_ids"]
                or expected["expected_preprocessing_contract_authority"]
                != value["preprocessing_contract_authority"]
                or expected["expected_service_identity_sha256"]
                != value["service_identity_sha256"]
                or expected["expected_policy_contract_sha256"]
                != value["preprocessing_contract_authority"][
                    "policy_contract_sha256"
                ]
            ):
                raise RuntimeError("authority expected identity drift")
            return copy.deepcopy(value)

        def validate_lifecycle(
            value: object, *, expected_authority: object
        ) -> dict[str, object]:
            if type(value) is not dict or type(expected_authority) is not dict:
                raise RuntimeError("lifecycle")
            if (
                value.get("service_authority_sha256")
                != expected_authority.get("service_authority_sha256")
            ):
                raise RuntimeError("lifecycle authority drift")
            return copy.deepcopy(value)

        def validate_acceptance(**kwargs: object) -> dict[str, object]:
            value = json.loads(
                Path(kwargs["acceptance_path"]).read_text(encoding="ascii")
            )
            expected = {
                "system": kwargs["expected_system"],
                "resource": kwargs["expected_resource"],
                "codec": kwargs["expected_codec"],
                "topology_kind": kwargs["expected_topology_kind"],
            }
            if value["coordinate"] != expected:
                raise RuntimeError("coordinate")
            if value["run_id"] != kwargs["expected_run_id"]:
                raise RuntimeError("run")
            if value["arm_id"] != kwargs["expected_arm_id"]:
                raise RuntimeError("arm")
            return value

        return target.ExecutionClosureDependenciesV1(
            load_preprocessing_contract=load_preprocessing,
            runtime_expectations_from_preprocessing_receipt=(
                runtime_expectations_from_preprocessing_receipt_v1
            ),
            validate_service_authority=validate_authority,
            validate_service_lifecycle=validate_lifecycle,
            validate_pilot_acceptance=validate_acceptance,
        )

    def invoke(
        self,
        dependencies: target.ExecutionClosureDependenciesV1 | None = None,
    ) -> dict[str, Path | int | str]:
        return target.materialize_publication_policy_qualification_execution_closure_v1(
            project_root=self.root,
            qualification_transaction_receipt_path=self.transaction,
            preprocessing_contract_path=self.contract,
            preprocessing_materialization_receipt_path=self.preprocessing_receipt,
            runtime_input_materialization_receipt_path=self.runtime_receipt,
            guardian_service_authority_path=self.authority_path,
            guardian_service_lifecycle_path=self.lifecycle_path,
            pilot_root=self.pilot_root,
            checkpoint_path=self.checkpoint,
            output_dir=self.output,
            dependencies=dependencies or self.dependencies(),
        )


class PublicationPolicyQualificationExecutionClosureV1Tests(unittest.TestCase):
    def test_closure_receipt_atomic_commit_three_windows_exact_retry(self) -> None:
        windows = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for window in windows:
            with self.subTest(window=window), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output = root / "closure"
                output.mkdir()
                path = output / "qualification-execution-closure.json"
                payload = b'{"closure":true}\n'

                def crash(step: str) -> None:
                    if step == window:
                        raise RuntimeError("synthetic physical crash")

                with target.PhysicalRootCustodyV1.open(
                    root, label="test closure root"
                ) as custody:
                    with self.assertRaisesRegex(
                        RuntimeError, "synthetic physical crash"
                    ):
                        target._write_or_verify_immutable(  # noqa: SLF001
                            custody,
                            path,
                            payload,
                            label="test closure receipt",
                            fault_hook=crash,
                        )
                    identity = None
                    if path.exists():
                        info = path.stat()
                        identity = (info.st_dev, info.st_ino)
                    target._write_or_verify_immutable(  # noqa: SLF001
                        custody,
                        path,
                        payload,
                        label="test closure receipt",
                    )
                self.assertEqual(path.read_bytes(), payload)
                if identity is not None:
                    info = path.stat()
                    self.assertEqual((info.st_dev, info.st_ino), identity)

    def test_receipt_last_closes_exact_32_cells_and_loads_cold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            result = fixture.invoke()
            receipt_path = Path(result["receipt_path"])
            receipt = json.loads(receipt_path.read_text(encoding="ascii"))
            self.assertEqual(result["cell_count"], 32)
            self.assertEqual(
                receipt["status"], "qualification_execution_closed_nonpublication"
            )
            self.assertEqual(len(receipt["pilot_execution"]["cells"]), 32)
            workload = receipt["pilot_execution"]["guardian_request_workload"]
            self.assertEqual(workload["request_count"], 128)
            self.assertEqual(workload["cell_count"], 32)
            self.assertEqual(
                workload["requests_by_worker"],
                {key: 16 for key in sorted(target._EXPECTED_WORKER_KEYS)},
            )
            self.assertEqual(
                receipt["guardian"]["accepted_workload_request_count"], 128
            )
            self.assertEqual(
                receipt["guardian"]["service_authority_sha256"],
                json.loads(fixture.authority_path.read_text(encoding="ascii"))[
                    "service_authority_sha256"
                ],
            )
            fixture.authority_path.unlink()
            fixture.lifecycle_path.unlink()
            loaded = target.load_publication_policy_qualification_execution_closure_v1(
                project_root=fixture.root,
                receipt_path=receipt_path,
                dependencies=fixture.dependencies(),
            )
            self.assertEqual(loaded["receipt"], receipt)
            self.assertEqual(
                len(loaded["lifecycle"]["retired_socket_nodes"]),
                target._RETIRED_SOCKET_NODE_COUNT,
            )
            self.assertEqual(loaded["receipt_descriptor"], descriptor(fixture.root, receipt_path))

    def test_wrong_runtime_socket_fails_before_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            runtime = json.loads(fixture.runtime_receipt.read_text(encoding="ascii"))
            runtime["live_sockets"]["analytics_execution"]["inode"] += 1
            unsigned = {key: value for key, value in runtime.items() if key != "receipt_sha256"}
            runtime["receipt_sha256"] = semantic_sha(unsigned)
            write_json(fixture.runtime_receipt, runtime)
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error,
                "authority header/input binding",
            ):
                fixture.invoke()
            self.assertFalse(fixture.output.exists())

    def test_wrong_authority_or_nonclean_lifecycle_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            lifecycle = json.loads(fixture.lifecycle_path.read_text(encoding="ascii"))
            lifecycle["service_authority_sha256"] = "f" * 64
            write_json(fixture.lifecycle_path, lifecycle)
            with self.assertRaisesRegex(target.QualificationExecutionClosureV1Error, "lifecycle"):
                fixture.invoke()

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            lifecycle = json.loads(fixture.lifecycle_path.read_text(encoding="ascii"))
            lifecycle["status"] = "failed_stop_nonpublication"
            write_json(fixture.lifecycle_path, lifecycle)
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error,
                "lifecycle authority/status/timing binding",
            ):
                fixture.invoke()

    def test_service_authority_must_bind_exact_preprocessing_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            dependencies = fixture.dependencies()

            def drifted_preprocessing(**kwargs: object) -> dict[str, object]:
                loaded = dependencies.load_preprocessing_contract(**kwargs)
                loaded["authority"]["candidate_receipt_identity_sha256"] = (
                    "e" * 64
                )
                return loaded

            drifted = target.ExecutionClosureDependenciesV1(
                load_preprocessing_contract=drifted_preprocessing,
                runtime_expectations_from_preprocessing_receipt=(
                    dependencies.runtime_expectations_from_preprocessing_receipt
                ),
                validate_service_authority=(
                    dependencies.validate_service_authority
                ),
                validate_service_lifecycle=(
                    dependencies.validate_service_lifecycle
                ),
                validate_pilot_acceptance=dependencies.validate_pilot_acceptance,
            )
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error,
                "authority",
            ):
                fixture.invoke(drifted)

    def test_external_runtime_expectations_reject_self_consistent_service_b(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(
                Path(tmp),
                service_execution_config_identity_sha256="e" * 64,
            )
            # The service authority/lifecycle remain an internally valid B pair,
            # while the independently verified preprocessing receipt selects A.
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error,
                "authority",
            ):
                fixture.invoke()

    def test_partial_checkpoint_cell_set_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            checkpoint = json.loads(fixture.checkpoint.read_text(encoding="ascii"))
            checkpoint["completed"].pop()
            checkpoint["status"] = "in_progress"
            unsigned = {
                key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"
            }
            checkpoint["checkpoint_sha256"] = semantic_sha(unsigned)
            write_json(fixture.checkpoint, checkpoint)
            with self.assertRaisesRegex(target.QualificationExecutionClosureV1Error, "32"):
                fixture.invoke()

    def test_drifted_acceptance_operational_binding_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            dependencies = fixture.dependencies()

            def drifted_acceptance(**kwargs: object) -> dict[str, object]:
                value = dependencies.validate_pilot_acceptance(**kwargs)
                value["operational_binding"][
                    "guardian_service_authority_identity_sha256"
                ] = "f" * 64
                return value

            drifted = target.ExecutionClosureDependenciesV1(
                load_preprocessing_contract=(
                    dependencies.load_preprocessing_contract
                ),
                runtime_expectations_from_preprocessing_receipt=(
                    dependencies.runtime_expectations_from_preprocessing_receipt
                ),
                validate_service_authority=dependencies.validate_service_authority,
                validate_service_lifecycle=dependencies.validate_service_lifecycle,
                validate_pilot_acceptance=drifted_acceptance,
            )
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error,
                "operational binding",
            ):
                fixture.invoke(drifted)

    def test_noop_guardian_dependencies_cannot_bypass_authenticated_stop(self) -> None:
        for mode in ("command", "schema", "self_hash", "timing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(Path(tmp))
                lifecycle = json.loads(
                    fixture.lifecycle_path.read_text(encoding="ascii")
                )
                stop = lifecycle["guardian_stop_attestation"]
                if mode == "command":
                    stop["canonical_command_sha256"] = "0" * 64
                elif mode == "schema":
                    stop["unexpected"] = True
                elif mode == "self_hash":
                    stop["identity"]["sha256"] = "0" * 64
                else:
                    stop["accepted_monotonic_ns"] = (
                        lifecycle["finished_monotonic_ns"] + 1
                    )
                if mode != "self_hash":
                    stop_core = {
                        key: item for key, item in stop.items() if key != "identity"
                    }
                    stop["identity"] = {
                        "algorithm": "sha256",
                        "sha256": semantic_sha(stop_core),
                    }
                lifecycle_core = {
                    key: item for key, item in lifecycle.items() if key != "identity"
                }
                lifecycle["identity"] = {
                    "algorithm": "sha256",
                    "sha256": semantic_sha(lifecycle_core),
                }
                write_json(fixture.lifecycle_path, lifecycle)
                dependencies = fixture.dependencies()
                noop = target.ExecutionClosureDependenciesV1(
                    load_preprocessing_contract=(
                        dependencies.load_preprocessing_contract
                    ),
                    runtime_expectations_from_preprocessing_receipt=(
                        dependencies.runtime_expectations_from_preprocessing_receipt
                    ),
                    validate_service_authority=(
                        lambda value, **_expected: copy.deepcopy(value)
                    ),
                    validate_service_lifecycle=(
                        lambda value, **_expected: copy.deepcopy(value)
                    ),
                    validate_pilot_acceptance=(
                        dependencies.validate_pilot_acceptance
                    ),
                )
                with self.assertRaisesRegex(
                    target.QualificationExecutionClosureV1Error,
                    "guardian (stop|authenticated-stop)",
                ):
                    fixture.invoke(noop)
                self.assertFalse(fixture.output.exists())

    def test_guardian_one_or_extra_request_cannot_match_accepted_workload(self) -> None:
        for mode in ("one", "extra"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(Path(tmp))

                def mutate(document: dict[str, object]) -> None:
                    counters = document["counters"]
                    by_worker = counters["requests_by_worker"]
                    if mode == "one":
                        for key in by_worker:
                            by_worker[key] = 0
                        by_worker["plate_number:cpu"] = 1
                        counters["requests_started"] = 1
                        counters["requests_completed"] = 1
                    else:
                        by_worker["plate_number:cpu"] += 1
                        counters["requests_started"] += 1
                        counters["requests_completed"] += 1

                rewrite_lifecycle(fixture.lifecycle_path, mutate)
                with self.assertRaisesRegex(
                    target.QualificationExecutionClosureV1Error,
                    "exactly match accepted 32-cell workload",
                ):
                    fixture.invoke()
                self.assertFalse(fixture.output.exists())

    def test_receipt_last_partial_commit_resumes_but_collisions_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            original = target._write_or_verify_immutable

            def fail_receipt(*args: object, **kwargs: object) -> object:
                if kwargs.get("label") == "qualification execution closure receipt":
                    raise target.QualificationExecutionClosureV1Error("injected receipt fault")
                return original(*args, **kwargs)

            with mock.patch.object(
                target, "_write_or_verify_immutable", side_effect=fail_receipt
            ):
                with self.assertRaisesRegex(
                    target.QualificationExecutionClosureV1Error,
                    "injected receipt fault",
                ):
                    fixture.invoke()
            self.assertFalse(
                (fixture.output / target.RECEIPT_FILENAME).exists()
            )
            resumed = fixture.invoke()
            self.assertTrue(Path(resumed["receipt_path"]).is_file())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            fixture.output.mkdir(parents=True)
            collision = fixture.output / target.AUTHORITY_SNAPSHOT_FILENAME
            collision.write_text("attacker-canary\n", encoding="ascii")
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error, "collision"
            ):
                fixture.invoke()
            self.assertEqual(collision.read_text(encoding="ascii"), "attacker-canary\n")

    def test_concurrent_identical_materializers_leave_one_exact_cold_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            gate = threading.Barrier(2)

            def invoke() -> object:
                gate.wait()
                try:
                    return fixture.invoke()
                except target.QualificationExecutionClosureV1Error as error:
                    return error

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcomes = list(pool.map(lambda _index: invoke(), range(2)))
            successes = [item for item in outcomes if isinstance(item, dict)]
            failures = [
                item
                for item in outcomes
                if isinstance(item, target.QualificationExecutionClosureV1Error)
            ]
            self.assertGreaterEqual(len(successes), 1)
            self.assertEqual(len(successes) + len(failures), 2)
            loaded = target.load_publication_policy_qualification_execution_closure_v1(
                project_root=fixture.root,
                receipt_path=fixture.output / target.RECEIPT_FILENAME,
                dependencies=fixture.dependencies(),
            )
            self.assertEqual(loaded["receipt"]["pilot_execution"]["pilot_root"]["cell_count"], 32)
            self.assertEqual(
                {path.name for path in fixture.output.iterdir()},
                {
                    target.AUTHORITY_SNAPSHOT_FILENAME,
                    target.LIFECYCLE_SNAPSHOT_FILENAME,
                    target.RECEIPT_FILENAME,
                },
            )

    @unittest.skipUnless(hasattr(os, "link") and hasattr(os, "symlink"), "links unavailable")
    def test_dangling_symlink_and_same_bytes_hardlink_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            fixture.output.mkdir(parents=True)
            dangling = fixture.output / target.AUTHORITY_SNAPSHOT_FILENAME
            os.symlink(fixture.root / "missing-target", dangling)
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error, "collision"
            ):
                fixture.invoke()
            self.assertTrue(dangling.is_symlink())

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Fixture(Path(tmp))
            fixture.output.mkdir(parents=True)
            donor = fixture.root / "same-authority-donor.json"
            donor.write_bytes(fixture.authority_path.read_bytes())
            os.chmod(donor, 0o444)
            linked = fixture.output / target.AUTHORITY_SNAPSHOT_FILENAME
            os.link(donor, linked)
            with self.assertRaisesRegex(
                target.QualificationExecutionClosureV1Error, "collision"
            ):
                fixture.invoke()
            self.assertEqual(linked.read_bytes(), fixture.authority_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
