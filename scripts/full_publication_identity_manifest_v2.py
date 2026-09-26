#!/usr/bin/env python3
"""Atomically materialize and physically validate the accepted identity manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

import full_publication_identity_artifacts as identity
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SYSTEMS = identity.SYSTEMS
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
IdentityLoader = Callable[..., dict[str, Any]]


class FullPublicationIdentityManifestV2Error(RuntimeError):
    """A physical accepted artifact or immutable manifest commit is unsafe."""


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
        raise FullPublicationIdentityManifestV2Error(
            "identity manifest is not canonical JSON"
        ) from exc


def _is_link(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _root(project_root: Path) -> Path:
    supplied = Path(os.path.abspath(os.fspath(project_root)))
    try:
        info = supplied.lstat()
        root = supplied.resolve(strict=True)
    except OSError as exc:
        raise FullPublicationIdentityManifestV2Error(
            "project_root is unavailable"
        ) from exc
    if root != supplied or not stat.S_ISDIR(info.st_mode) or _is_link(supplied):
        raise FullPublicationIdentityManifestV2Error(
            "project_root must be a physical directory"
        )
    return root


def _physical_file(
    root: Path,
    custody: PhysicalRootCustodyV1,
    value: Any,
    label: str,
) -> tuple[Path, dict[str, Any], tuple[int, int]]:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        absolute = Path(os.path.abspath(os.fspath(candidate)))
        relative = absolute.relative_to(root)
        descriptor, _payload, filesystem_identity = custody.read_descriptor_identity(
            absolute,
            label=label,
            maximum=512 * 1024 * 1024,
            capture=False,
        )
    except (OSError, ValueError, PublicationPhysicalIoV1Error) as exc:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} is missing or outside project_root"
        ) from exc
    if descriptor["path"] != relative.as_posix():
        raise FullPublicationIdentityManifestV2Error(
            f"{label} physical path normalization drifted"
        )
    return absolute, descriptor, filesystem_identity


def _descriptor_registry(
    root: Path, custody: PhysicalRootCustodyV1
) -> tuple[
    Callable[[Any, str], dict[str, Any]],
    set[str],
    set[tuple[int, int]],
]:
    paths: set[str] = set()
    identities: set[tuple[int, int]] = set()

    def add(value: Any, label: str) -> dict[str, Any]:
        _physical, descriptor, filesystem_identity = _physical_file(
            root, custody, value, label
        )
        if descriptor["path"] in paths or filesystem_identity in identities:
            raise FullPublicationIdentityManifestV2Error(
                f"{label} artifact alias is prohibited"
            )
        paths.add(str(descriptor["path"]))
        identities.add(filesystem_identity)
        return descriptor

    return add, paths, identities


def _mapping(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != fields:
        raise FullPublicationIdentityManifestV2Error(f"{label} fields drifted")
    return value


def _output(root: Path, output_path: Path) -> Path:
    candidate = Path(output_path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise FullPublicationIdentityManifestV2Error(
            "identity manifest output escaped project_root"
        ) from exc
    try:
        parent_info = candidate.parent.lstat()
    except OSError as exc:
        raise FullPublicationIdentityManifestV2Error(
            "identity manifest output parent must exist under project_root"
        ) from exc
    if not stat.S_ISDIR(parent_info.st_mode) or _is_link(candidate.parent):
        raise FullPublicationIdentityManifestV2Error(
            "identity manifest output parent must be physical"
        )
    return candidate


def _guarded_identity_load(
    *,
    custody: PhysicalRootCustodyV1,
    root: Path,
    manifest_path: Path,
    bound_paths: list[Path],
    identity_loader: IdentityLoader,
    label: str,
) -> dict[str, Any]:
    try:
        token = custody.capture_read_namespace(
            [manifest_path, *bound_paths],
            label=f"{label} physical closure",
        )
    except PublicationPhysicalIoV1Error as exc:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} physical closure could not be pinned: {exc}"
        ) from exc
    load_error: Exception | None = None
    accepted: dict[str, Any] | None = None
    try:
        accepted = identity_loader(project_root=root, manifest_path=manifest_path)
    except Exception as exc:  # the namespace check below remains mandatory
        load_error = exc
    try:
        custody.verify_read_namespace(
            token,
            label=f"{label} physical closure",
        )
    except PublicationPhysicalIoV1Error as exc:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} namespace changed during physical validation: {exc}"
        ) from exc
    if load_error is not None:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} physical identity validation failed: {load_error}"
        ) from load_error
    if type(accepted) is not dict:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} physical identity validation returned a non-object"
        )
    return accepted


def _build_full_publication_identity_manifest_v2_with_custody(
    *,
    root: Path,
    custody: PhysicalRootCustodyV1,
    output_path: Path,
    analytics_model_parity: Mapping[str, Any],
    analytics_execution_layer: Mapping[str, Any],
    policy_qualification: Mapping[str, Any],
    resource_qualification: Mapping[str, Any],
    backend_runtime_qualification: Mapping[str, Any],
    identity_loader: IdentityLoader = identity.load_full_publication_identity_artifacts,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Commit only a candidate that the physical identity loader accepts."""
    destination = _output(root, output_path)
    add, registered_paths, _ = _descriptor_registry(root, custody)

    parity = _mapping(
        analytics_model_parity,
        {"receipt", "accepted_manifest", "accepted_assessment"},
        "analytics model parity",
    )
    execution = _mapping(
        analytics_execution_layer,
        {"artifact", "content_identity_sha256"},
        "analytics execution layer",
    )
    execution_identity = str(execution["content_identity_sha256"])
    if not _SHA_RE.fullmatch(execution_identity):
        raise FullPublicationIdentityManifestV2Error(
            "analytics execution content identity is invalid"
        )
    policy = _mapping(
        policy_qualification,
        {"receipt", "capability_manifest", "calibration_mapping"},
        "policy qualification",
    )
    resource = _mapping(
        resource_qualification,
        {"receipt", "capability_manifest"},
        "resource qualification",
    )
    backend = _mapping(
        backend_runtime_qualification,
        {"binding_index", "receipts"},
        "backend runtime qualification",
    )
    receipts = _mapping(
        backend["receipts"], set(SYSTEMS), "backend qualification receipts"
    )

    manifest = {
        "schema_version": identity.SCHEMA_VERSION,
        "artifact_kind": identity.MANIFEST_KIND,
        "bindings": {
            "analytics_model_parity": {
                "receipt": add(parity["receipt"], "model parity receipt"),
                "accepted_manifest": add(
                    parity["accepted_manifest"], "accepted model parity manifest"
                ),
                "accepted_assessment": add(
                    parity["accepted_assessment"], "accepted model parity assessment"
                ),
            },
            "analytics_execution_layer": {
                "artifact": add(execution["artifact"], "analytics execution layer"),
                "content_identity_sha256": execution_identity,
            },
            "policy_qualification": {
                "receipt": add(policy["receipt"], "policy qualification receipt"),
                "outputs": {
                    "capability_manifest": add(
                        policy["capability_manifest"], "policy capability manifest"
                    ),
                    "calibration_mapping": add(
                        policy["calibration_mapping"], "policy calibration mapping"
                    ),
                },
            },
            "resource_qualification": {
                "receipt": add(resource["receipt"], "resource qualification receipt"),
                "outputs": {
                    "capability_manifest": add(
                        resource["capability_manifest"], "resource capability manifest"
                    )
                },
            },
            "backend_runtime_qualification": {
                "binding_index": add(
                    backend["binding_index"], "backend qualification binding index"
                ),
                "receipts": {
                    system: add(
                        receipts[system], f"backend qualification receipt {system}"
                    )
                    for system in SYSTEMS
                },
            },
        },
    }
    payload = _canonical_bytes(manifest)
    bound_paths = [root / item for item in sorted(registered_paths)]
    temporary: Path | None = None
    temporary_identity: tuple[int, int] | None = None
    try:
        for _attempt in range(32):
            token = hashlib.sha256(os.urandom(32)).hexdigest()[:24]
            candidate = destination.parent / f".full-identity-v2.{token}.json"
            try:
                _temporary_descriptor, temporary_identity = (
                    custody.write_exclusive_identity(
                        candidate,
                        payload,
                        label="identity manifest private candidate",
                        mode=0o400,
                        create_parents=False,
                    )
                )
                temporary = candidate
                break
            except PublicationPhysicalIoV1Error as exc:
                if "already exists" in str(exc):
                    continue
                raise FullPublicationIdentityManifestV2Error(
                    f"identity manifest private candidate commit failed: {exc}"
                ) from exc
        if temporary is None or temporary_identity is None:
            raise FullPublicationIdentityManifestV2Error(
                "identity manifest private candidate namespace is exhausted"
            )
        _guarded_identity_load(
            custody=custody,
            root=root,
            manifest_path=temporary,
            bound_paths=bound_paths,
            identity_loader=identity_loader,
            label="candidate",
        )
        try:
            custody.commit_or_adopt_exact_identity(
                destination,
                payload,
                label="immutable identity manifest output",
                mode=0o444,
                create_parents=False,
                after_publish_step=after_publish_step,
            )
        except PublicationPhysicalIoV1Error as exc:
            raise FullPublicationIdentityManifestV2Error(
                "identity manifest atomic no-overwrite/resume commit failed: "
                f"{exc}"
            ) from exc
        accepted = _guarded_identity_load(
            custody=custody,
            root=root,
            manifest_path=destination,
            bound_paths=bound_paths,
            identity_loader=identity_loader,
            label="committed",
        )
    finally:
        if temporary is not None and temporary_identity is not None:
            try:
                custody.unlink_owned_identity(
                    temporary,
                    temporary_identity,
                    label="identity manifest private candidate",
                )
            except PublicationPhysicalIoV1Error as exc:
                raise FullPublicationIdentityManifestV2Error(
                    f"identity manifest private candidate retirement failed: {exc}"
                ) from exc
    return {"manifest_path": str(destination), "binding": accepted}


def build_full_publication_identity_manifest_v2(
    *,
    project_root: Path,
    output_path: Path,
    analytics_model_parity: Mapping[str, Any],
    analytics_execution_layer: Mapping[str, Any],
    policy_qualification: Mapping[str, Any],
    resource_qualification: Mapping[str, Any],
    backend_runtime_qualification: Mapping[str, Any],
    identity_loader: IdentityLoader = identity.load_full_publication_identity_artifacts,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    root = _root(project_root)
    try:
        with PhysicalRootCustodyV1.open(
            root, label="full-publication identity project_root"
        ) as custody:
            return _build_full_publication_identity_manifest_v2_with_custody(
                root=root,
                custody=custody,
                output_path=output_path,
                analytics_model_parity=analytics_model_parity,
                analytics_execution_layer=analytics_execution_layer,
                policy_qualification=policy_qualification,
                resource_qualification=resource_qualification,
                backend_runtime_qualification=backend_runtime_qualification,
                identity_loader=identity_loader,
                after_publish_step=after_publish_step,
            )
    except FullPublicationIdentityManifestV2Error:
        raise
    except PublicationPhysicalIoV1Error as exc:
        raise FullPublicationIdentityManifestV2Error(
            f"full-publication identity physical custody failed: {exc}"
        ) from exc


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument(
        "--output-path",
        type=Path,
        default=identity.DEFAULT_MANIFEST,
    )
    parser.add_argument("--parity-receipt", type=Path, required=True)
    parser.add_argument("--parity-manifest", type=Path, required=True)
    parser.add_argument("--parity-assessment", type=Path, required=True)
    parser.add_argument("--execution-artifact", type=Path, required=True)
    parser.add_argument("--execution-identity-sha256", required=True)
    parser.add_argument("--policy-receipt", type=Path, required=True)
    parser.add_argument("--policy-capability", type=Path, required=True)
    parser.add_argument("--policy-calibration", type=Path, required=True)
    parser.add_argument("--resource-receipt", type=Path, required=True)
    parser.add_argument("--resource-capability", type=Path, required=True)
    parser.add_argument("--backend-index", type=Path, required=True)
    for system in SYSTEMS:
        parser.add_argument(
            f"--backend-{system.replace('_', '-')}-receipt",
            dest=f"backend_{system}_receipt",
            type=Path,
            required=True,
        )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = build_full_publication_identity_manifest_v2(
        project_root=args.project_root,
        output_path=args.output_path,
        analytics_model_parity={
            "receipt": args.parity_receipt,
            "accepted_manifest": args.parity_manifest,
            "accepted_assessment": args.parity_assessment,
        },
        analytics_execution_layer={
            "artifact": args.execution_artifact,
            "content_identity_sha256": args.execution_identity_sha256,
        },
        policy_qualification={
            "receipt": args.policy_receipt,
            "capability_manifest": args.policy_capability,
            "calibration_mapping": args.policy_calibration,
        },
        resource_qualification={
            "receipt": args.resource_receipt,
            "capability_manifest": args.resource_capability,
        },
        backend_runtime_qualification={
            "binding_index": args.backend_index,
            "receipts": {
                system: getattr(args, f"backend_{system}_receipt")
                for system in SYSTEMS
            },
        },
    )
    print(
        json.dumps(
            {
                "manifest_path": result["manifest_path"],
                "binding_sha256": result["binding"]["binding_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FullPublicationIdentityManifestV2Error",
    "build_full_publication_identity_manifest_v2",
]
