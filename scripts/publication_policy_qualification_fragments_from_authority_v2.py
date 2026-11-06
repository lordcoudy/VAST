#!/usr/bin/env python3
"""Materialize four qualification fragments from current physical authorities.

The legacy per-system fragment builders freeze image and model-parity identities
in source constants.  This module is the versioned transaction boundary used
after a physical image refreeze.  It accepts either the unchanged v3 authority
or the patch-bound v4 refresh authority, re-hashes the analytics binding set,
runtime probes, image patch, and parity acceptance, verifies live Docker image
identity, and writes fresh non-authorizing fragment binding documents.

No production grant or publication acceptance is created here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
from functools import wraps
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_policy_qualification_fragment_validation_v2 import (
    BINDING_KIND,
    BRANCHES,
    DEFAULT_DEPENDENCIES,
    ENGINE_BY_RESOURCE,
    FRAGMENT_KIND,
    FragmentAuthorityDependenciesV2,
    OMZ_MANIFEST,
    PATCH_KIND,
    POLICY_CONTRACT,
    QualificationFragmentsFromAuthorityV2Error,
    REFRESH_BLOCKERS,
    RESOURCES,
    SCHEMA_VERSION,
    SYSTEMS,
    V3_BINDING_INDEX,
    V3_BINDING_KIND,
    V3_RUNTIME_PROBES,
    V4_BINDING_KIND,
    _DESCRIPTOR_FIELDS,
    _IMAGE,
    _IMAGE_REFERENCE,
    _SHA,
    _binding_authority,
    _binding_files,
    _canonical_bytes,
    _canonical_sha,
    _default_inspect_image,
    _default_load_identity_patch,
    _default_load_v3_acceptance,
    _default_load_v4_acceptance,
    _descriptor,
    _file_sha,
    _inspect_projection,
    _is_link,
    _load_parity_authority,
    _load_patch_authority,
    _materialization_inputs,
    _normalize_v4_refresh_authority,
    _nvidia_identity,
    _omz_bindings,
    _physical_directory,
    _physical_file,
    _policy_runtime_identity,
    _primary_descriptors,
    _read_json,
    _read_yaml,
    _receipt_kind,
    _require,
    _resource_runtime_identity,
    _root,
    _self_sha,
    _system_image_projection,
    _under_root,
    _v3_refresh_authority,
    _validate_binding_document,
    _validate_one_fragment,
    _verify_live_images,
    file_descriptor,
    validate_publication_policy_qualification_fragment_from_authority_v2,
    validate_publication_policy_qualification_fragments_from_authority_v2,
)


def _document(
    *,
    system: str,
    role: str,
    branch: str,
    resource: str,
    implementation_id: str,
    emitter_id: str,
    runtime_identity: Mapping[str, Any],
    authority: Mapping[str, Any],
    system_image: Mapping[str, Any],
    nvidia: Mapping[str, str],
    policy_contract: Mapping[str, Any],
    execution_config: Mapping[str, Any],
    binding_index: Mapping[str, Any],
    analytics_binding: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
    runtime_probe: tuple[Mapping[str, Any], Mapping[str, Any]] | None,
    local_omz: Mapping[str, Any] | None,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": BINDING_KIND,
        "system": system,
        "role": role,
        "branch": branch,
        "resource": resource,
        "implementation_id": implementation_id,
        "emitter_id": emitter_id,
        "runtime_identity": copy.deepcopy(runtime_identity),
        "authority": copy.deepcopy(authority),
        "policy_contract": copy.deepcopy(policy_contract),
        "system_image": copy.deepcopy(system_image),
        "nvidia_hardware_binding": copy.deepcopy(nvidia),
        "execution_config": copy.deepcopy(execution_config),
        "analytics_execution_binding_index": copy.deepcopy(binding_index),
    }
    value.update(copy.deepcopy(system_image))
    if analytics_binding is not None and runtime_probe is not None:
        descriptor, binding = analytics_binding
        probe_descriptor, probe = runtime_probe
        value.update(
            {
                "analytics_execution_worker_binding": copy.deepcopy(descriptor),
                "analytics_execution_worker_binding_identity": {
                    key: binding.get(key)
                    for key in (
                        "artifact_kind",
                        "model_id",
                        "source_model_sha256",
                        "model_artifact_sha256",
                        "worker_image_id",
                    )
                },
                "analytics_runtime_probe": copy.deepcopy(probe_descriptor),
                "analytics_runtime_probe_identity_sha256": _canonical_sha(probe),
            }
        )
    if local_omz is not None:
        field = (
            "gva_sdk_binding_nonterminal"
            if system == "openvino_gva"
            else "openvino_cpu_binding"
        )
        value[field] = copy.deepcopy(local_omz)
        if system == "openvino_gva":
            value["terminal_authority"] = "external_analytics_execution_worker_only"
    value["binding_sha256"] = _self_sha(value, "binding_sha256")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> tuple[int, str]:
    payload = _canonical_bytes(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    path.chmod(0o444)
    return len(payload), hashlib.sha256(payload).hexdigest()


def _fragment_row(
    *, root: Path, path: Path, value: Mapping[str, Any]
) -> dict[str, Any]:
    return {
        "branch": value["branch"],
        "resource": value["resource"],
        "role": value["role"],
        "implementation_id": value["implementation_id"],
        "emitter_id": value["emitter_id"],
        "path": path.relative_to(root).as_posix(),
        "size": int(path.stat().st_size),
        "sha256": _file_sha(path),
        "runtime_identity": copy.deepcopy(value["runtime_identity"]),
    }


def _directory_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link(path, info),
        "fragment directory identity is unsafe",
    )
    return int(info.st_dev), int(info.st_ino)


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    from publication_policy_qualification_pilot_executor_v2 import (
        _rename_directory_noreplace as publish,
    )

    publish(source, destination)


def _cleanup_staging(
    staging: Path,
    *,
    destination: Path,
    expected_staging_identity: tuple[int, int],
    expected_destination_identity: tuple[int, int],
) -> None:
    _require(
        staging.parent == destination
        and staging.name.startswith(".authority-fragments-v2.")
        and _directory_identity(destination) == expected_destination_identity
        and _directory_identity(staging) == expected_staging_identity,
        "unsafe fragment staging cleanup target",
    )
    for path in staging.rglob("*"):
        info = path.lstat()
        _require(
            (
                stat.S_ISDIR(info.st_mode)
                and not _is_link(path, info)
            )
            or (
                stat.S_ISREG(info.st_mode)
                and not _is_link(path, info)
                and int(info.st_nlink) == 1
            ),
            "fragment staging cleanup found an unowned inode",
        )
    shutil.rmtree(staging)


def _materialize_publication_policy_qualification_fragments_from_authority_v2_held(
    *,
    project_root: Path | str,
    fragments_root: Path | str,
    identity_patch_path: Path | str,
    accepted_model_parity_manifest_path: Path | str,
    accepted_model_parity_assessment_path: Path | str,
    accepted_model_parity_receipt_path: Path | str,
    docker: str = "docker",
    dependencies: FragmentAuthorityDependenciesV2 = DEFAULT_DEPENDENCIES,
) -> dict[str, Path]:
    """Create exact 4 fragments/40 binding files after physical preflight."""

    root = _root(project_root)
    _require(type(dependencies) is FragmentAuthorityDependenciesV2, "fragment dependencies are invalid")
    destination = _physical_directory(root, fragments_root, label="fragments root")
    _require(destination != root, "fragments root cannot be project_root")
    _require(
        not any(os.path.lexists(destination / system) for system in SYSTEMS),
        "fragment output already exists",
    )
    inputs = _materialization_inputs(
        root=root,
        identity_patch_path=identity_patch_path,
        accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
        accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
        accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
        docker=docker,
        dependencies=dependencies,
        verify_live=True,
    )
    authority = _binding_authority(
        patch_descriptor=inputs["patch_descriptor"],
        patch=inputs["patch"],
        parity=inputs["parity"],
    )
    refresh = inputs["parity"]["refresh"]
    execution_descriptor = copy.deepcopy(refresh["execution_config"])
    binding_index = {
        **copy.deepcopy(refresh["binding_set"]["index"]),
        "identity_sha256": refresh["binding_set"]["identity_sha256"],
        "bindings_identity_sha256": refresh["binding_set"]["bindings_identity_sha256"],
    }
    staging = Path(tempfile.mkdtemp(prefix=".authority-fragments-v2.", dir=destination))
    destination_identity = _directory_identity(destination)
    staging_identity = _directory_identity(staging)
    committed: list[Path] = []
    try:
        for system in SYSTEMS:
            system_root = staging / system
            policy_root = system_root / "bindings" / "policy"
            resource_root = system_root / "bindings" / "resource"
            policy_rows: list[dict[str, Any]] = []
            resource_rows: list[dict[str, Any]] = []
            system_image = _system_image_projection(inputs["patch"], system)
            image_id = inputs["patch"]["systems"][system]["fragment_identity"]["image_id"]
            for branch in BRANCHES:
                for resource in RESOURCES:
                    binding_record, binding_value = inputs["bindings"][(branch, resource)]
                    probe_record, probe_value = inputs["probes"][resource]
                    runtime_identity = _policy_runtime_identity(
                        system=system,
                        resource=resource,
                        binding=binding_value,
                        probe=probe_value,
                    )
                    coordinate_sha = _canonical_sha(
                        {
                            "system": system,
                            "branch": branch,
                            "resource": resource,
                            "patch_sha256": inputs["patch"]["patch_sha256"],
                            "parity_binding_sha256": inputs["parity"]["binding_sha256"],
                            "analytics_binding_sha256": binding_record["sha256"],
                            "runtime_probe_sha256": probe_record["sha256"],
                        }
                    )
                    implementation_id = (
                        f"{system}-qualification-authority-v2:{branch}:{resource}:"
                        f"{coordinate_sha}"
                    )
                    emitter_id = (
                        f"{system}-native-policy-emitter-v2:{branch}:{resource}:"
                        f"{coordinate_sha}"
                    )
                    document = _document(
                        system=system,
                        role="policy",
                        branch=branch,
                        resource=resource,
                        implementation_id=implementation_id,
                        emitter_id=emitter_id,
                        runtime_identity=runtime_identity,
                        authority=authority,
                        system_image=system_image,
                        nvidia=inputs["nvidia"],
                        policy_contract=inputs["policy_contract"],
                        execution_config=execution_descriptor,
                        binding_index=binding_index,
                        analytics_binding=(binding_record, binding_value),
                        runtime_probe=(probe_record, probe_value),
                        local_omz=(
                            inputs["omz"][branch]
                            if system in {"openvino_gva", "gstreamer_custom"}
                            else None
                        ),
                    )
                    path = policy_root / f"{branch}.{resource}.binding.json"
                    _write_json(path, document)
                    policy_rows.append(_fragment_row(root=root, path=path, value=document))
            for resource in RESOURCES:
                coordinate_sha = _canonical_sha(
                    {
                        "system": system,
                        "resource": resource,
                        "image_id": image_id,
                        "patch_sha256": inputs["patch"]["patch_sha256"],
                    }
                )
                implementation_id = (
                    f"{system}-full-resource-authority-v2:{resource}:{coordinate_sha}"
                )
                emitter_id = (
                    f"{system}-native-resource-emitter-v2:{resource}:{coordinate_sha}"
                )
                document = _document(
                    system=system,
                    role="resource",
                    branch="all_branches",
                    resource=resource,
                    implementation_id=implementation_id,
                    emitter_id=emitter_id,
                    runtime_identity=_resource_runtime_identity(
                        system=system,
                        resource=resource,
                        image_id=image_id,
                        patch_sha256=inputs["patch"]["patch_sha256"],
                        nvidia=inputs["nvidia"],
                    ),
                    authority=authority,
                    system_image=system_image,
                    nvidia=inputs["nvidia"],
                    policy_contract=inputs["policy_contract"],
                    execution_config=execution_descriptor,
                    binding_index=binding_index,
                    analytics_binding=None,
                    runtime_probe=None,
                    local_omz=None,
                )
                path = resource_root / f"{resource}.binding.json"
                _write_json(path, document)
                resource_rows.append(_fragment_row(root=root, path=path, value=document))
            fragment = {
                "schema_version": 1,
                "artifact_kind": FRAGMENT_KIND,
                "system": system,
                "policy_bindings": policy_rows,
                "resource_bindings": resource_rows,
                "pilots": [],
            }
            _write_json(system_root / "qualification_fragment.json", fragment)

        # Paths in the staged documents must name final paths, not private staging.
        # Rebase once before commit and regenerate the 40 dependent hashes.
        for system in SYSTEMS:
            system_root = staging / system
            fragment_path = system_root / "qualification_fragment.json"
            fragment = json.loads(fragment_path.read_bytes())
            for rows in (fragment["policy_bindings"], fragment["resource_bindings"]):
                for row in rows:
                    raw = PurePosixPath(row["path"])
                    marker = PurePosixPath(staging.relative_to(root).as_posix()) / system
                    _require(tuple(raw.parts[: len(marker.parts)]) == tuple(marker.parts), "staged binding path escaped transaction")
                    final_relative = PurePosixPath(destination.relative_to(root).as_posix()) / system / PurePosixPath(*raw.parts[len(marker.parts):])
                    row["path"] = final_relative.as_posix()
            fragment_path.chmod(0o600)
            fragment_path.unlink()
            _write_json(fragment_path, fragment)

        for system in SYSTEMS:
            source = staging / system
            target = destination / system
            _require(not target.exists() and not os.path.lexists(target), f"{system} fragment collided before commit")
            _require(
                _directory_identity(destination) == destination_identity,
                "fragments root changed before commit",
            )
            _rename_directory_noreplace(source, target)
            committed.append(target)
        staging.rmdir()
        result = {
            system: destination / system / "qualification_fragment.json"
            for system in SYSTEMS
        }
        validate_publication_policy_qualification_fragments_from_authority_v2(
            project_root=root,
            fragment_paths=result,
            identity_patch=inputs["patch"],
            identity_patch_path=identity_patch_path,
            accepted_model_parity_manifest_path=accepted_model_parity_manifest_path,
            accepted_model_parity_assessment_path=accepted_model_parity_assessment_path,
            accepted_model_parity_receipt_path=accepted_model_parity_receipt_path,
            dependencies=dependencies,
        )
        return result
    except Exception:
        # Committed system directories are immutable phase artifacts.  Never
        # erase them here: a partial phase must remain visible and fail closed.
        raise
    finally:
        if staging.exists():
            _cleanup_staging(
                staging,
                destination=destination,
                expected_staging_identity=staging_identity,
                expected_destination_identity=destination_identity,
            )


@wraps(_materialize_publication_policy_qualification_fragments_from_authority_v2_held)
def materialize_publication_policy_qualification_fragments_from_authority_v2(
    *args: Any, **kwargs: Any
) -> dict[str, Path]:
    """Materialize under held custody, then validate from a fresh root handle."""

    _require(not args, "fragment materializer accepts keyword arguments only")
    root = _root(kwargs.get("project_root"))
    input_paths = (
        kwargs.get("identity_patch_path"),
        kwargs.get("accepted_model_parity_manifest_path"),
        kwargs.get("accepted_model_parity_assessment_path"),
        kwargs.get("accepted_model_parity_receipt_path"),
    )
    destination = _physical_directory(
        root, kwargs.get("fragments_root"), label="fragments root"
    )
    destination_identity = _directory_identity(destination)
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification fragments project_root"
        ) as custody:
            namespace = custody.capture_read_namespace(
                input_paths, label="qualification fragment authorities"
            )
            result = _materialize_publication_policy_qualification_fragments_from_authority_v2_held(
                **kwargs
            )
            custody.verify_read_namespace(
                namespace, label="qualification fragment authorities"
            )
            _require(
                _directory_identity(destination) == destination_identity,
                "fragments root changed during materialization",
            )
            custody.verify()
        with PhysicalRootCustodyV1.open(
            root, label="qualification fragments cold project_root"
        ) as cold:
            validated = validate_publication_policy_qualification_fragments_from_authority_v2(
                project_root=root,
                fragment_paths=result,
                identity_patch_path=kwargs.get("identity_patch_path"),
                accepted_model_parity_manifest_path=kwargs.get(
                    "accepted_model_parity_manifest_path"
                ),
                accepted_model_parity_assessment_path=kwargs.get(
                    "accepted_model_parity_assessment_path"
                ),
                accepted_model_parity_receipt_path=kwargs.get(
                    "accepted_model_parity_receipt_path"
                ),
                dependencies=kwargs.get("dependencies", DEFAULT_DEPENDENCIES),
            )
            _require(set(validated) == set(SYSTEMS), "cold fragment coverage drifted")
            cold.verify()
        return result
    except QualificationFragmentsFromAuthorityV2Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise QualificationFragmentsFromAuthorityV2Error(
            f"qualification fragment physical custody failed: {error}"
        ) from error


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--fragments-root", type=Path, required=True)
    parser.add_argument("--identity-patch", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-manifest", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-assessment", type=Path, required=True)
    parser.add_argument("--accepted-model-parity-receipt", type=Path, required=True)
    parser.add_argument("--docker", default="docker")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        result = materialize_publication_policy_qualification_fragments_from_authority_v2(
            project_root=args.project_root,
            fragments_root=args.fragments_root,
            identity_patch_path=args.identity_patch,
            accepted_model_parity_manifest_path=args.accepted_model_parity_manifest,
            accepted_model_parity_assessment_path=args.accepted_model_parity_assessment,
            accepted_model_parity_receipt_path=args.accepted_model_parity_receipt,
            docker=args.docker,
        )
    except (OSError, QualificationFragmentsFromAuthorityV2Error) as error:
        print(f"qualification fragment materialization blocked: {error}", file=os.sys.stderr)
        return 78
    print(json.dumps({system: str(result[system]) for system in SYSTEMS}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BINDING_KIND",
    "DEFAULT_DEPENDENCIES",
    "FragmentAuthorityDependenciesV2",
    "QualificationFragmentsFromAuthorityV2Error",
    "SYSTEMS",
    "materialize_publication_policy_qualification_fragments_from_authority_v2",
    "validate_publication_policy_qualification_fragment_from_authority_v2",
    "validate_publication_policy_qualification_fragments_from_authority_v2",
]
