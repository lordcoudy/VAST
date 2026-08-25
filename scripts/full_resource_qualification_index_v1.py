#!/usr/bin/env python3
"""Build the immutable 32-cell pre-run FULL-RESOURCE qualification index.

This builder only inventories native runtime/resource implementations and the
shared physical qualification pilots.  It does not promote the resulting
index and cannot authorize a full-publication benchmark arm.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

import full_resource_qualification as qualification
import publication_policy_qualification as policy_qualification
import publication_policy_qualification_index_v2 as policy_index


DEFAULT_FRAGMENT_PATHS = {
    "deepstream": Path(
        "artifacts/deepstream_publication_v3/qualification/qualification_fragment.json"
    ),
    "savant": Path(
        "artifacts/savant_publication_v3/qualification/qualification_fragment.json"
    ),
    "openvino_gva": Path(
        "artifacts/openvino_gva_publication_v3/qualification/qualification_fragment.json"
    ),
    "gstreamer_custom": Path(
        "artifacts/gstreamer_publication_v3/qualification/qualification_fragment.json"
    ),
}

PILOT_EVIDENCE_FILENAMES = {
    "checkpoint_acceptance": "checkpoint_qualification_pilot_acceptance.json",
    "frames": "frames.csv",
    "frame_events": "frame_events.csv",
    "ingress_ledger": "ingress_ledger.csv",
    "topology_events": "topology_events.csv",
    "resource_intervals": "resource_intervals.csv",
    "hardware_resource_samples": "hardware_resource_samples.csv",
    "fanout_work_counters": "fanout_work_counters.csv",
}

_BINDING_REQUIRED_FIELDS = {
    "schema_version",
    "artifact_kind",
    "system",
    "branch",
    "resource",
    "role",
    "implementation_id",
    "emitter_id",
    "runtime_identity",
    "resource_v2_evidence",
}
_RUNTIME_IDENTITY_FIELDS = {
    "runtime_backend",
    "analytics_device_api",
    "decoder_device_api",
    "worker_image_digest",
    "implementation_version",
    "hardware_binding_id",
}
_EMITTER_SOURCE_BY_ROLE = {
    "resource_intervals": "nvdec_intervals",
    "hardware_resource_samples": "hardware_resource_samples",
    "fanout_work_counters": "fanout_work_counters",
}

FragmentValidator = Callable[[str, Path, Path], dict[str, Any]]


class FullResourceQualificationIndexV1Error(RuntimeError):
    """An index input or immutable commit is incomplete or unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise FullResourceQualificationIndexV1Error(
            "qualification index is not canonical JSON"
        ) from exc


def _load_json_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FullResourceQualificationIndexV1Error(f"invalid {label}: {exc}") from exc
    if type(value) is not dict:
        raise FullResourceQualificationIndexV1Error(f"{label} must be a JSON object")
    return value


def _descriptor_matches(raw: Any, actual: Mapping[str, Any], label: str) -> None:
    if type(raw) is not dict or set(raw) != {"path", "size_bytes", "sha256"}:
        raise FullResourceQualificationIndexV1Error(
            f"{label} descriptor fields drifted"
        )
    if dict(raw) != dict(actual):
        raise FullResourceQualificationIndexV1Error(
            f"{label} descriptor size/SHA drifted"
        )


def _build_resource_contract(root: Path) -> dict[str, Any]:
    return {
        "contract_version": 2,
        "publication_scope": qualification.PUBLICATION_SCOPE,
        "full_resource_validator": policy_index._descriptor(
            root,
            root / "scripts" / "full_resource_contract.py",
            "full resource validator",
        ),
        "interval_validator": policy_index._descriptor(
            root,
            root / "scripts" / "resource_interval_contract.py",
            "resource interval validator",
        ),
    }


def _read_binding(
    *,
    root: Path,
    system: str,
    resource: str,
    row: Mapping[str, Any],
    fragment_artifact: Mapping[str, Any],
    resource_contract: Mapping[str, Any],
) -> dict[str, Any]:
    coordinate = f"{system}/{resource}"
    if row.get("role") != "resource" or row.get("branch") != "all_branches":
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} fragment binding role/branch drifted"
        )
    try:
        artifact = policy_index._descriptor(
            root,
            str(row["path"]),
            f"{coordinate} physical resource binding",
        )
    except (KeyError, TypeError, policy_index.PolicyQualificationIndexV2Error) as exc:
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} binding artifact failed: {exc}"
        ) from exc
    if row.get("size") != artifact["size_bytes"] or row.get("sha256") != artifact["sha256"]:
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} binding descriptor drifted"
        )

    material = _load_json_object(root / str(artifact["path"]), f"{coordinate} binding")
    if not _BINDING_REQUIRED_FIELDS <= set(material):
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} binding material fields drifted"
        )
    expected_kind = f"vast_{system}_resource_binding_material_v1"
    if (
        material.get("schema_version") != 1
        or material.get("artifact_kind") != expected_kind
        or material.get("system") != system
        or material.get("resource") != resource
        or material.get("branch") != "all_branches"
        or material.get("role") != "resource"
        or material.get("implementation_id") != row.get("implementation_id")
        or material.get("emitter_id") != row.get("emitter_id")
        or material.get("runtime_identity") != row.get("runtime_identity")
    ):
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} binding material identity drifted"
        )

    runtime_identity = material["runtime_identity"]
    if type(runtime_identity) is not dict or set(runtime_identity) != _RUNTIME_IDENTITY_FIELDS:
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} runtime identity fields drifted"
        )
    expected_api = "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA"
    image = str(runtime_identity.get("worker_image_digest", ""))
    if (
        runtime_identity.get("analytics_device_api") != expected_api
        or runtime_identity.get("decoder_device_api") != "NVIDIA_NVDEC"
        or not image.startswith("sha256:")
        or len(image) != 71
    ):
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} runtime identity device/image drifted"
        )

    evidence = material["resource_v2_evidence"]
    if (
        type(evidence) is not dict
        or evidence.get("contract_version") != 2
        or evidence.get("publication_scope") != qualification.PUBLICATION_SCOPE
    ):
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} resource-v2 evidence contract drifted"
        )
    _descriptor_matches(
        evidence.get("full_resource_validator"),
        resource_contract["full_resource_validator"],
        f"{coordinate} full resource validator",
    )
    _descriptor_matches(
        evidence.get("interval_validator"),
        resource_contract["interval_validator"],
        f"{coordinate} interval validator",
    )
    native_emitters = evidence.get("native_emitters")
    if type(native_emitters) is not dict:
        raise FullResourceQualificationIndexV1Error(
            f"{coordinate} native emitter set is missing"
        )

    base_emitter_id = str(material["emitter_id"])
    emitters: dict[str, Any] = {}
    for role, source_name in _EMITTER_SOURCE_BY_ROLE.items():
        source = native_emitters.get(source_name)
        try:
            source_artifact = policy_index._descriptor(
                root,
                str((source or {})["path"]),
                f"{coordinate}/{role} native emitter",
            )
        except (KeyError, TypeError, policy_index.PolicyQualificationIndexV2Error) as exc:
            raise FullResourceQualificationIndexV1Error(
                f"{coordinate}/{role} native emitter failed: {exc}"
            ) from exc
        _descriptor_matches(source, source_artifact, f"{coordinate}/{role} native emitter")
        emitters[role] = {
            "emitter_id": f"{base_emitter_id}:{role}",
            "artifact": source_artifact,
        }

    binding_sha = str(artifact["sha256"])
    return {
        "system": system,
        "resource": resource,
        "implementation_id": material["implementation_id"],
        "implementation_artifact": artifact,
        "runtime_binding": f"{system}:{resource}:fragment-v1:{binding_sha}",
        "runtime_identity": dict(runtime_identity),
        "emitters": emitters,
    }


def _build_bindings(
    *,
    root: Path,
    fragment_paths: Mapping[str, Path],
    fragment_validator: FragmentValidator,
    resource_contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    systems = tuple(qualification.SYSTEMS)
    resources = tuple(qualification.RESOURCES)
    if set(fragment_paths) != set(systems):
        raise FullResourceQualificationIndexV1Error(
            "fragment system set must exactly match the four publishable systems"
        )

    bindings: list[dict[str, Any]] = []
    for system in systems:
        try:
            _, fragment_artifact, fragment = policy_index._read_fragment(
                root=root,
                system=system,
                path_value=Path(fragment_paths[system]),
                fragment_validator=fragment_validator,
            )
        except policy_index.PolicyQualificationIndexV2Error as exc:
            raise FullResourceQualificationIndexV1Error(
                f"{system} fragment validation failed: {exc}"
            ) from exc
        rows = fragment.get("resource_bindings")
        if type(rows) is not list or len(rows) != len(resources):
            raise FullResourceQualificationIndexV1Error(
                f"{system} fragment resource coverage drifted"
            )
        by_resource: dict[str, Mapping[str, Any]] = {}
        for position, row in enumerate(rows):
            if type(row) is not dict:
                raise FullResourceQualificationIndexV1Error(
                    f"{system} fragment resource binding[{position}] is invalid"
                )
            resource = str(row.get("resource", ""))
            if resource in by_resource:
                raise FullResourceQualificationIndexV1Error(
                    f"{system} fragment contains a duplicate resource binding"
                )
            by_resource[resource] = row
        if set(by_resource) != set(resources):
            raise FullResourceQualificationIndexV1Error(
                f"{system} fragment resource coordinate set drifted"
            )
        for resource in resources:
            bindings.append(
                _read_binding(
                    root=root,
                    system=system,
                    resource=resource,
                    row=by_resource[resource],
                    fragment_artifact=fragment_artifact,
                    resource_contract=resource_contract,
                )
            )
    if len(bindings) != 8:
        raise FullResourceQualificationIndexV1Error(
            "binding set must contain exactly 8 system/resource rows"
        )
    return bindings


def _build_pilots(*, root: Path, pilot_root: Path) -> list[dict[str, Any]]:
    try:
        root_directory = policy_index._physical_directory(root, pilot_root, "pilot_root")
    except policy_index.PolicyQualificationIndexV2Error as exc:
        raise FullResourceQualificationIndexV1Error(
            f"pilot evidence root is missing or unsafe: {exc}"
        ) from exc
    pilots: list[dict[str, Any]] = []
    global_identities: set[tuple[int, int]] = set()
    for system in qualification.SYSTEMS:
        for resource in qualification.RESOURCES:
            for codec in qualification.CODECS:
                for topology in qualification.TOPOLOGIES:
                    coordinate = f"{system}/{resource}/{codec}/{topology}"
                    arm_value = root_directory / system / resource / codec / topology
                    try:
                        arm = policy_index._physical_directory(root, arm_value, "pilot arm")
                    except policy_index.PolicyQualificationIndexV2Error as exc:
                        raise FullResourceQualificationIndexV1Error(
                            f"pilot evidence arm is missing or unsafe: {coordinate}"
                        ) from exc
                    evidence: dict[str, dict[str, Any]] = {}
                    for role in qualification.PILOT_EVIDENCE_ROLES:
                        filename = PILOT_EVIDENCE_FILENAMES[role]
                        try:
                            item = policy_index._descriptor(
                                root,
                                arm / filename,
                                f"pilot evidence {coordinate}/{role}",
                            )
                            info = (root / item["path"]).stat()
                        except (OSError, policy_index.PolicyQualificationIndexV2Error) as exc:
                            raise FullResourceQualificationIndexV1Error(
                                f"pilot evidence is missing or unsafe: {coordinate}/{role}"
                            ) from exc
                        identity = (int(info.st_dev), int(info.st_ino))
                        if identity in global_identities:
                            raise FullResourceQualificationIndexV1Error(
                                f"pilot evidence alias is prohibited: {coordinate}/{role}"
                            )
                        global_identities.add(identity)
                        evidence[role] = item
                    pilots.append(
                        {
                            "system": system,
                            "resource": resource,
                            "codec": codec,
                            "topology_kind": topology,
                            "evidence": evidence,
                        }
                    )
    if len(pilots) != 32:
        raise FullResourceQualificationIndexV1Error(
            "pilot evidence cell set must contain exactly 32 cells"
        )
    return pilots


def _destination(root: Path, output_path: Path) -> Path:
    candidate = Path(output_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.exists():
        raise FullResourceQualificationIndexV1Error(
            "immutable full-resource qualification index already exists"
        )
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FullResourceQualificationIndexV1Error(
            "output parent must be a physical directory under project_root"
        ) from exc
    try:
        policy_index._physical_directory(root, parent, "output parent")
    except policy_index.PolicyQualificationIndexV2Error as exc:
        raise FullResourceQualificationIndexV1Error(str(exc)) from exc
    return parent / candidate.name


def _atomic_write(destination: Path, payload: bytes) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".full-resource-index-v1.", suffix=".tmp", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        directory_descriptor: int | None = None
        try:
            directory_descriptor = os.open(
                destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            os.fsync(directory_descriptor)
        except OSError:
            pass
        finally:
            if directory_descriptor is not None:
                os.close(directory_descriptor)
    except Exception as exc:
        raise FullResourceQualificationIndexV1Error(
            f"atomic index commit failed: {exc}"
        ) from exc
    finally:
        try:
            if temporary.exists():
                info = temporary.lstat()
                if stat.S_ISREG(info.st_mode) and temporary.parent == destination.parent:
                    temporary.unlink()
        except OSError as exc:
            raise FullResourceQualificationIndexV1Error(
                f"private temporary cleanup failed: {exc}"
            ) from exc


def build_full_resource_qualification_index_v1(
    *,
    project_root: Path,
    fragment_paths: Mapping[str, Path],
    pilot_root: Path,
    output_path: Path,
    fragment_validator: FragmentValidator | None = None,
) -> Path:
    """Validate all physical inputs and atomically commit one immutable index."""
    try:
        root = policy_index._root(project_root)
    except policy_index.PolicyQualificationIndexV2Error as exc:
        raise FullResourceQualificationIndexV1Error(str(exc)) from exc
    destination = _destination(root, output_path)
    validator = fragment_validator or policy_qualification._default_fragment_validator
    try:
        resource_contract = _build_resource_contract(root)
        bindings = _build_bindings(
            root=root,
            fragment_paths=fragment_paths,
            fragment_validator=validator,
            resource_contract=resource_contract,
        )
        pilots = _build_pilots(root=root, pilot_root=pilot_root)
        dataset = policy_index._descriptor(
            root, root / "configs" / "datasets.yaml", "dataset manifest"
        )
    except FullResourceQualificationIndexV1Error:
        raise
    except policy_index.PolicyQualificationIndexV2Error as exc:
        raise FullResourceQualificationIndexV1Error(str(exc)) from exc
    except Exception as exc:
        raise FullResourceQualificationIndexV1Error(
            f"full-resource qualification index validation failed: {exc}"
        ) from exc

    index = {
        "schema_version": qualification.QUALIFICATION_INDEX_SCHEMA_VERSION,
        "artifact_kind": "vast_pre_run_full_resource_qualification_index",
        "resource_contract": resource_contract,
        "dataset_manifest": dataset,
        "bindings": bindings,
        "pilots": pilots,
    }
    _atomic_write(destination, _canonical_bytes(index))
    return destination


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    for system, default in DEFAULT_FRAGMENT_PATHS.items():
        parser.add_argument(
            f"--{system.replace('_', '-')}-fragment",
            dest=f"{system}_fragment",
            type=Path,
            default=default,
        )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    fragments = {
        system: getattr(args, f"{system}_fragment")
        for system in qualification.SYSTEMS
    }
    output = build_full_resource_qualification_index_v1(
        project_root=args.project_root,
        fragment_paths=fragments,
        pilot_root=args.pilot_root,
        output_path=args.output_path,
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_FRAGMENT_PATHS",
    "PILOT_EVIDENCE_FILENAMES",
    "FullResourceQualificationIndexV1Error",
    "build_full_resource_qualification_index_v1",
]
