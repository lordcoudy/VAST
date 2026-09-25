#!/usr/bin/env python3
"""Materialize fail-closed OpenVINO/GVA publication-v3 qualification bindings."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping, Sequence

import checkpoint_gstreamer_custom_qualification_fragment_v3 as common


SCHEMA_VERSION = 1
ARTIFACT_KIND = "vast_publication_qualification_system_fragment_v1"
SYSTEM = "openvino_gva"
FRAGMENT_FILENAME = "qualification_fragment.json"
BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
RESOURCES = ("cpu", "gpu")
ROW_FIELDS = {
    "role", "branch", "resource", "path", "sha256", "size",
    "implementation_id", "emitter_id", "runtime_identity",
}
FRAGMENT_FIELDS = {
    "schema_version", "artifact_kind", "system", "policy_bindings",
    "resource_bindings", "pilots",
}
POLICY_RUNTIME_FIELDS = {
    "runtime_backend", "device_api", "gpu_id", "worker_image_digest",
    "implementation_version", "terminal_detector", "terminal_backend",
}
RESOURCE_RUNTIME_FIELDS = {
    "runtime_backend", "analytics_device_api", "decoder_device_api",
    "worker_image_digest", "implementation_version", "hardware_binding_id",
}
RESOURCE_RECEIPT_FIELDS = (
    "process_cpu_time_ns",
    "rss_before_bytes",
    "rss_after_bytes",
    "accelerator_memory_bytes",
    "cuda_h2d_bytes",
    "cuda_d2h_bytes",
    "cuda_transfer_intervals",
)
CUDA_INTERVAL_FIELDS = (
    "direction",
    "host_start_monotonic_ns",
    "host_end_monotonic_ns",
    "device_elapsed_ns",
    "bytes",
    "device_id",
    "timing_source",
)

PROTOCOL_IDENTITY_SHA256 = (
    "3bed4ad0e5cd46b01649b054fa520c0f728a1ceeb14502fb9fe1f0f8f5941eff"
)
CPU_WORKER_IMAGE_ID = (
    "sha256:a12ade38a28cf06c55ffd1bb9a4bffe966886576577ae08f96108eef200ceac1"
)
GPU_WORKER_IMAGE_ID = (
    "sha256:4c4cbe52e615d73189afa4f15d3053e88f569fbc31ff5f1c3d27aaec47285744"
)
WORKER_IMPLEMENTATIONS = {
    "cpu": "b5782c91b6bdab9958a4f63485acae8975b4930843453a61e2fbe61b2c4da63b",
    "gpu": "b8e6250e6f3871a2ffa5753a62300aeea77f132194b4309728ff74f49fbb9feb",
}
OPENVINO_GVA_IMAGE_REFERENCE = (
    "vast/openvino-gva-publication-runtime-v3:materialized"
)
OPENVINO_GVA_IMAGE_ID = (
    "sha256:c5aadcf691448991dfe3b52732013fe9e6b6f4f9efa774f08fffc9298d035d90"
)
OPENVINO_GVA_REPOSITORY_DIGEST = (
    "vast/openvino-gva-publication-runtime-v3@"
    "sha256:c5aadcf691448991dfe3b52732013fe9e6b6f4f9efa774f08fffc9298d035d90"
)
OPENVINO_GVA_IMAGE_PROJECTION_SHA256 = (
    "99e671f433387da6e8a680d679a80e4c60fc821a8064171d033c9068cf9db93c"
)
OPENVINO_GVA_BASE_IMAGE_ID = (
    "sha256:f2579dc4c2977e2127c874273369c6c5ac7d99b4cb8e8c8a28e974a3a6195ca8"
)
OPENVINO_GVA_RUNTIME_SOURCE_SHA256 = (
    "ee5ce81e798d38bba8c6c46a8ac448166134ea8d4bb18d6dd19fb1d25af05532"
)
OPENVINO_GVA_NATIVE_SOURCE_SHA256 = (
    "ae7ba6d2e74de0e5a84abe4cd187ff070606eeea7a9dcaf94e03e2958a984546"
)
OPENVINO_GVA_DEPENDENCY_SET_SHA256 = (
    "0f338b3aeca6756d31dccdbbc8caeb6239e8e07fec0541c1df3fea91dfc1963e"
)
OPENVINO_GVA_SOURCE_ALLOWLIST_SHA256 = (
    "c6ac2d9b54b2a9f9ba883ba814a35c39f319fba9c923497a4fe46432fce7cff9"
)
OPENVINO_GVA_EMBEDDED_SET_SHA256 = (
    "abc2c68d3ad0d50d5f1d72aa49e5bd77d7cac001d185325460de1e23b4d91c0f"
)
GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
GPU_NAME = "NVIDIA GeForce RTX 3060"
GPU_DRIVER = "610.47"

QualificationFragmentError = common.QualificationFragmentError


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationFragmentError(message)


def _source_set_identity(root: Path) -> dict[str, Any]:
    relative = "deploy/openvino_gva/publication/runtime-source-allowlist.txt"
    descriptor = common._descriptor(root, relative, "OpenVINO source allowlist")
    _require(
        descriptor["sha256"] == OPENVINO_GVA_SOURCE_ALLOWLIST_SHA256,
        "OpenVINO source allowlist identity drifted",
    )
    raw = (root / relative).read_bytes()
    _require(raw.endswith(b"\n") and b"\r" not in raw, "OpenVINO allowlist is not canonical")
    values = raw.decode("utf-8").splitlines()
    _require(
        values == sorted(set(values)) and relative not in values,
        "OpenVINO allowlist is unordered, duplicated, or self-referential",
    )
    rows = bytearray()
    native_rows = bytearray()
    for value in values:
        path = common._relative_file(root, value, "OpenVINO runtime source")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        row = f"{digest}  {value}\n".encode("ascii")
        rows.extend(row)
        if value.startswith("deploy/native_gst_probe/"):
            native_rows.extend(row)
    _require(bool(rows) and bool(native_rows), "OpenVINO runtime source set is empty")
    runtime_sha = hashlib.sha256(rows).hexdigest()
    native_sha = hashlib.sha256(native_rows).hexdigest()
    _require(
        runtime_sha == OPENVINO_GVA_RUNTIME_SOURCE_SHA256
        and native_sha == OPENVINO_GVA_NATIVE_SOURCE_SHA256,
        "OpenVINO transitive runtime source identity drifted",
    )
    return {
        **descriptor,
        "runtime_source_sha256": runtime_sha,
        "native_source_sha256": native_sha,
        "self_reference_forbidden": True,
    }


def _runtime_sources(root: Path) -> dict[str, dict[str, Any]]:
    paths = {
        "native_probe_source": "deploy/native_gst_probe/vast_native_gst_probe.cpp",
        "analytics_execution_client": "deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp",
        "resource_interval_emitter": "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
        "analytics_execution_protocol": "scripts/analytics_execution_protocol.py",
        "analytics_execution_worker": "scripts/analytics_execution_worker.py",
        "analytics_bridge": "scripts/checkpoint_gstreamer_analytics_bridge.py",
        "gstreamer_runtime": "scripts/checkpoint_gstreamer_runtime.py",
        "image_coordinator": "scripts/checkpoint_openvino_gva_container_coordinator_v3.py",
        "host_runtime": "scripts/checkpoint_openvino_gva_publication_runtime_v3.py",
        "execution_bridge": "scripts/checkpoint_openvino_execution_bridge.py",
        "topology_contract": "scripts/topology_contract.py",
        "full_resource_validator": "scripts/full_resource_contract.py",
        "interval_validator": "scripts/resource_interval_contract.py",
        "hardware_collector": "scripts/collect_metrics.py",
        "image_builder": "scripts/build_openvino_gva_publication_runtime_v3.sh",
        "dockerfile": "deploy/openvino_gva/publication/Dockerfile",
        "source_closure_validator": "deploy/openvino_gva/publication/validate_runtime_source_closure_v3.py",
    }
    return {role: common._descriptor(root, path, role) for role, path in paths.items()}


def _image_identity(root: Path) -> dict[str, Any]:
    return {
        "final_reference": OPENVINO_GVA_IMAGE_REFERENCE,
        "image_id": OPENVINO_GVA_IMAGE_ID,
        "repository_digest": OPENVINO_GVA_REPOSITORY_DIGEST,
        "inspect_projection_sha256": OPENVINO_GVA_IMAGE_PROJECTION_SHA256,
        "base_image_id": OPENVINO_GVA_BASE_IMAGE_ID,
        "runtime_source_sha256": OPENVINO_GVA_RUNTIME_SOURCE_SHA256,
        "native_source_sha256": OPENVINO_GVA_NATIVE_SOURCE_SHA256,
        "dependency_set_sha256": OPENVINO_GVA_DEPENDENCY_SET_SHA256,
        "source_allowlist_sha256": OPENVINO_GVA_SOURCE_ALLOWLIST_SHA256,
        "embedded_set_sha256": OPENVINO_GVA_EMBEDDED_SET_SHA256,
        "entrypoint": ["/usr/local/bin/vast_openvino_gva_publication_runtime_v3"],
        "publication_ready_label": "false",
        "source_set": _source_set_identity(root),
    }


def _policy_identity(
    resource: str,
    binding: Mapping[str, Any],
    probe: Mapping[str, Any],
) -> dict[str, Any]:
    device = "CPU" if resource == "cpu" else "NVIDIA_CUDA:0"
    return {
        "runtime_backend": (
            "openvino_gva_external_openvino_cpu_worker_v3"
            if resource == "cpu"
            else "openvino_gva_external_tensorrt_cuda_worker_v3"
        ),
        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "gpu_id": None if resource == "cpu" else 0,
        "worker_image_digest": (
            CPU_WORKER_IMAGE_ID if resource == "cpu" else GPU_WORKER_IMAGE_ID
        ),
        "implementation_version": "sha256:" + WORKER_IMPLEMENTATIONS[resource],
        "terminal_detector": (
            f"{binding['model_id']};"
            f"model_sha256={binding['source_model_sha256']}"
        ),
        "terminal_backend": (
            f"analytics-execution:{probe['engine']};runtime={probe['runtime_name']};"
            f"native_api={probe['native_inference_api']};device={device}"
        ),
    }


def _resource_identity(resource: str) -> dict[str, str]:
    return {
        "runtime_backend": "openvino_gva_immutable_dlstreamer_container_v3",
        "analytics_device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
        "decoder_device_api": "NVIDIA_NVDEC",
        "worker_image_digest": OPENVINO_GVA_IMAGE_ID,
        "implementation_version": "sha256:" + OPENVINO_GVA_RUNTIME_SOURCE_SHA256,
        "hardware_binding_id": f"nvidia-gpu:{GPU_UUID}:driver-{GPU_DRIVER}",
    }


def _receipt_contract(branch: str, resource: str) -> dict[str, Any]:
    value: dict[str, Any] = {
        "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
        "fields": list(RESOURCE_RECEIPT_FIELDS),
        "cuda_interval_fields": list(CUDA_INTERVAL_FIELDS),
        "cuda_transfer_intervals": (
            "exact_empty" if resource == "cpu" else "exact_h2d_then_d2h"
        ),
        "cuda_interval_order": [] if resource == "cpu" else ["h2d", "d2h"],
        "execution_stage_binding": (
            {}
            if resource == "cpu"
            else {"h2d": branch, "d2h": f"postprocess_{branch}"}
        ),
        "timing_source": (
            None if resource == "cpu" else "cudaEventElapsedTime"
        ),
        "device_id": None if resource == "cpu" else GPU_UUID,
    }
    return value


def _topology_contract(branch: str) -> dict[str, Any]:
    return {
        "contract_version": 2,
        "terminal_chain": [branch, f"postprocess_{branch}", "branch_complete"],
        "analytics_parent_of_postprocess": True,
        "postprocess_parent_of_branch_complete": True,
        "postprocess_resource": "HOST_CPU",
        "invariant_across_cpu_gpu_selection": True,
    }


def _material_values(root: Path) -> list[tuple[str, str, str, dict[str, Any]]]:
    parity = common._accepted_parity(root)
    binding_index, bindings = common._analytics_bindings(root)
    probes = common._runtime_probes(root)
    gva_manifest, gva_bindings = common._openvino_bindings(root)
    policy_contract = common._policy_contract(root)
    sources = _runtime_sources(root)
    image = _image_identity(root)
    materials: list[tuple[str, str, str, dict[str, Any]]] = []
    for branch in BRANCHES:
        for resource in RESOURCES:
            worker = bindings[(branch, resource)]
            binding = worker["binding"]
            probe = probes[resource]["probe"]
            identity = _policy_identity(resource, binding, probe)
            artifact = {
                "schema_version": 1,
                "artifact_kind": "vast_openvino_gva_policy_binding_material_v1",
                "system": SYSTEM,
                "role": "policy",
                "branch": branch,
                "resource": resource,
                "implementation_id": (
                    f"openvino-gva-external-analytics-v3:{branch}:{resource}:"
                    f"{WORKER_IMPLEMENTATIONS[resource]}:{OPENVINO_GVA_RUNTIME_SOURCE_SHA256}"
                ),
                "emitter_id": (
                    f"vast-openvino-gva-native-terminal-v3:{branch}:{resource}:"
                    f"{OPENVINO_GVA_NATIVE_SOURCE_SHA256}"
                ),
                "runtime_identity": identity,
                "terminal_authority": "external_analytics_execution_worker_only",
                "policy_contract": policy_contract,
                "accepted_model_parity_manifest": parity,
                "protocol_identity_sha256": PROTOCOL_IDENTITY_SHA256,
                "analytics_execution_binding_index": binding_index,
                "analytics_execution_worker_binding": worker["descriptor"],
                "analytics_execution_worker_binding_identity": {
                    "artifact_kind": binding["artifact_kind"],
                    "worker_id": binding["worker_id"],
                    "worker_image_id": binding["worker_image_id"],
                    "worker_implementation_sha256": WORKER_IMPLEMENTATIONS[resource],
                    "model_id": binding["model_id"],
                    "model_artifact_sha256": binding["model_artifact_sha256"],
                },
                "analytics_runtime_probe": probes[resource]["descriptor"],
                "analytics_execution_resource_receipt_contract": _receipt_contract(
                    branch, resource,
                ),
                "topology_contract": _topology_contract(branch),
                "openvino_gva_runtime_image": image,
                "gva_sdk_model_manifest": gva_manifest,
                "gva_sdk_binding_nonterminal": gva_bindings[branch],
                "runtime_sources": sources,
                "nvidia_hardware_binding": {
                    "uuid": GPU_UUID,
                    "name": GPU_NAME,
                    "driver_version": GPU_DRIVER,
                },
            }
            materials.append(("policy", branch, resource, artifact))
    for resource in RESOURCES:
        artifact = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_gva_resource_binding_material_v1",
            "system": SYSTEM,
            "role": "resource",
            "branch": "all_branches",
            "resource": resource,
            "implementation_id": (
                f"openvino-gva-full-resource-v2:{resource}:{OPENVINO_GVA_IMAGE_ID}"
            ),
            "emitter_id": (
                f"vast-openvino-gva-native-resource-v2:{resource}:"
                f"{OPENVINO_GVA_NATIVE_SOURCE_SHA256}"
            ),
            "runtime_identity": _resource_identity(resource),
            "accepted_model_parity_manifest": parity,
            "openvino_gva_runtime_image": image,
            "analytics_runtime_probe": probes[resource]["descriptor"],
            "resource_v2_evidence": {
                "contract_version": 2,
                "publication_scope": "primary_architecture_full_resource_raw_evidence_v2",
                "decoder_device_api": "NVIDIA_NVDEC",
                "native_emitters": {
                    "nvdec_intervals": sources["resource_interval_emitter"],
                    "fanout_intervals": sources["resource_interval_emitter"],
                    "fanout_work_counters": sources["resource_interval_emitter"],
                    "cuda_transfer_intervals": sources["resource_interval_emitter"],
                    "hardware_resource_samples": sources["hardware_collector"],
                },
                "full_resource_validator": sources["full_resource_validator"],
                "interval_validator": sources["interval_validator"],
                "shared_topology_fanout_required": True,
                "independent_topology_fanout_header_only": True,
            },
            "topology_contract": {
                "contract_version": 2,
                "invariant_across_cpu_gpu_selection": True,
                "postprocess_resource": "HOST_CPU",
            },
            "runtime_sources": sources,
            "nvidia_hardware_binding": {
                "uuid": GPU_UUID,
                "name": GPU_NAME,
                "driver_version": GPU_DRIVER,
            },
        }
        materials.append(("resource", "all_branches", resource, artifact))
    return materials


def _artifact_path(
    root: Path, output: Path, role: str, branch: str, resource: str,
) -> str:
    name = (
        f"{branch}.{resource}.binding.json"
        if role == "policy" else f"{resource}.binding.json"
    )
    return (output / "bindings" / role / name).relative_to(root).as_posix()


def _expected(root: Path, output: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    policy: list[dict[str, Any]] = []
    resources: list[dict[str, Any]] = []
    payloads: dict[str, bytes] = {}
    for role, branch, resource, artifact in _material_values(root):
        relative = _artifact_path(root, output, role, branch, resource)
        payload = common._canonical_bytes(artifact)
        payloads[relative] = payload
        row = {
            "role": role,
            "branch": branch,
            "resource": resource,
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size": len(payload),
            "implementation_id": artifact["implementation_id"],
            "emitter_id": artifact["emitter_id"],
            "runtime_identity": artifact["runtime_identity"],
        }
        (policy if role == "policy" else resources).append(row)
    return ({
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "system": SYSTEM,
        "policy_bindings": policy,
        "resource_bindings": resources,
        "pilots": [],
    }, payloads)


def _failure(message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_qualification_system_fragment_assessment_v1",
        "passed": False,
        "status": "blocked",
        "blockers": [message],
        "coverage": {
            "policy_binding_count": 0,
            "resource_binding_count": 0,
            "pilot_cell_count": 0,
        },
    }


def assess_qualification_fragment(
    *, project_root: Path, fragment_path: Path,
) -> dict[str, Any]:
    try:
        root = common._project_root(project_root)
        candidate = Path(fragment_path).resolve(strict=True)
        try:
            candidate.relative_to(root)
        except ValueError as error:
            raise QualificationFragmentError("fragment escaped project_root") from error
        info = candidate.lstat()
        _require(
            candidate.name == FRAGMENT_FILENAME
            and not common._is_link(candidate)
            and stat.S_ISREG(info.st_mode)
            and int(info.st_nlink) == 1,
            "fragment must be a physical regular file",
        )
        value = common._json(candidate, "OpenVINO qualification fragment")
        _require(set(value) == FRAGMENT_FIELDS, "qualification fragment fields drifted")
        _require(
            value.get("schema_version") == 1
            and value.get("artifact_kind") == ARTIFACT_KIND
            and value.get("system") == SYSTEM,
            "qualification fragment identity drifted",
        )
        _require(value.get("pilots") == [], "phase-one pilots must remain empty")
        expected, payloads = _expected(root, candidate.parent)
        _require(value == expected, "qualification fragment binding values drifted")
        paths: set[str] = set()
        inodes: set[tuple[int, int]] = set()
        implementations: set[str] = set()
        emitters: set[str] = set()
        for row in (*value["policy_bindings"], *value["resource_bindings"]):
            _require(type(row) is dict and set(row) == ROW_FIELDS, "binding row fields drifted")
            fields = POLICY_RUNTIME_FIELDS if row["role"] == "policy" else RESOURCE_RUNTIME_FIELDS
            _require(
                type(row["runtime_identity"]) is dict
                and set(row["runtime_identity"]) == fields,
                "binding runtime identity fields drifted",
            )
            implementation = str(row["implementation_id"])
            emitter = str(row["emitter_id"])
            _require(
                common._ID_RE.fullmatch(implementation) is not None
                and common._ID_RE.fullmatch(emitter) is not None
                and implementation not in implementations
                and emitter not in emitters,
                "binding implementation/emitter identity drifted",
            )
            implementations.add(implementation)
            emitters.add(emitter)
            path = common._relative_file(root, row["path"], "physical binding")
            inode = (int(path.lstat().st_dev), int(path.lstat().st_ino))
            _require(row["path"] not in paths and inode not in inodes, "physical binding alias prohibited")
            paths.add(row["path"])
            inodes.add(inode)
            payload = path.read_bytes()
            _require(
                payload == payloads[row["path"]]
                and len(payload) == row["size"]
                and hashlib.sha256(payload).hexdigest() == row["sha256"],
                "physical binding bytes/size/SHA-256 drifted",
            )
        _require(
            len(paths) == len(inodes) == len(implementations) == len(emitters) == 10,
            "binding coverage drifted",
        )
        return {
            "schema_version": 1,
            "artifact_kind": "vast_publication_qualification_system_fragment_assessment_v1",
            "passed": True,
            "status": "bindings_materialized_pilots_pending",
            "blockers": [],
            "fragment_sha256": common._stable_hash(candidate, "qualification fragment")[1],
            "coverage": {
                "policy_binding_count": 8,
                "resource_binding_count": 2,
                "pilot_cell_count": 0,
            },
        }
    except QualificationFragmentError as error:
        return _failure(str(error))
    except Exception as error:
        return _failure(f"qualification fragment validation failed closed: {error}")


def materialize_qualification_fragment(
    *, project_root: Path, output_dir: Path,
) -> dict[str, Any]:
    root = common._project_root(project_root)
    output = common._output_dir(root, output_dir)
    fragment, payloads = _expected(root, output)
    for relative, payload in payloads.items():
        common._write_immutable(root / relative, payload)
    fragment_path = output / FRAGMENT_FILENAME
    common._write_immutable(fragment_path, common._canonical_bytes(fragment))
    assessment = assess_qualification_fragment(
        project_root=root, fragment_path=fragment_path,
    )
    if not assessment["passed"]:
        raise QualificationFragmentError(
            "materialized fragment blocked: " + ", ".join(assessment["blockers"])
        )
    return {
        "fragment_path": fragment_path,
        "fragment_sha256": assessment["fragment_sha256"],
        "coverage": assessment["coverage"],
        "status": assessment["status"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize OpenVINO GVA qualification fragment")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--assess-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.assess_only:
        result = assess_qualification_fragment(
            project_root=args.project_root,
            fragment_path=args.output_dir / FRAGMENT_FILENAME,
        )
    else:
        result = materialize_qualification_fragment(
            project_root=args.project_root, output_dir=args.output_dir,
        )
        result = {**result, "fragment_path": str(result["fragment_path"])}
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result.get("passed", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARTIFACT_KIND", "BRANCHES", "CPU_WORKER_IMAGE_ID", "FRAGMENT_FILENAME",
    "GPU_WORKER_IMAGE_ID", "OPENVINO_GVA_IMAGE_ID",
    "OPENVINO_GVA_IMAGE_REFERENCE", "POLICY_RUNTIME_FIELDS",
    "QualificationFragmentError", "RESOURCES", "RESOURCE_RUNTIME_FIELDS",
    "ROW_FIELDS", "assess_qualification_fragment", "materialize_qualification_fragment",
]
