#!/usr/bin/env python3
"""Atomically materialize and physically validate the accepted identity manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping

import full_publication_identity_artifacts as identity


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
    try:
        root = Path(project_root).resolve(strict=True)
    except OSError as exc:
        raise FullPublicationIdentityManifestV2Error(
            "project_root is unavailable"
        ) from exc
    if not root.is_dir() or _is_link(root):
        raise FullPublicationIdentityManifestV2Error(
            "project_root must be a physical directory"
        )
    return root


def _physical_file(root: Path, value: Any, label: str) -> tuple[Path, dict[str, Any]]:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} is missing or outside project_root"
        ) from exc
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_link(cursor):
            raise FullPublicationIdentityManifestV2Error(
                f"{label} path contains a symlink/reparse point"
            )
    before = resolved.stat()
    if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1 or before.st_size <= 0:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} must be a unique nonempty physical regular file"
        )
    digest = hashlib.sha256()
    with resolved.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    after = resolved.stat()
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
        int(getattr(before, "st_ctime_ns", 0)),
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
        int(getattr(after, "st_ctime_ns", 0)),
    )
    if before_identity != after_identity:
        raise FullPublicationIdentityManifestV2Error(
            f"{label} changed while hashing"
        )
    return resolved, {
        "path": relative.as_posix(),
        "size_bytes": int(after.st_size),
        "sha256": digest.hexdigest(),
    }


def _descriptor_registry(root: Path) -> tuple[
    Callable[[Any, str], dict[str, Any]],
    set[str],
    set[tuple[int, int]],
]:
    paths: set[str] = set()
    identities: set[tuple[int, int]] = set()

    def add(value: Any, label: str) -> dict[str, Any]:
        physical, descriptor = _physical_file(root, value, label)
        filesystem_identity = (int(physical.stat().st_dev), int(physical.stat().st_ino))
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
    if candidate.exists():
        raise FullPublicationIdentityManifestV2Error(
            "immutable identity manifest output already exists"
        )
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise FullPublicationIdentityManifestV2Error(
            "identity manifest output parent must exist under project_root"
        ) from exc
    if not parent.is_dir() or _is_link(parent):
        raise FullPublicationIdentityManifestV2Error(
            "identity manifest output parent must be physical"
        )
    return parent / candidate.name


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
) -> dict[str, Any]:
    """Commit only a candidate that the physical identity loader accepts."""
    root = _root(project_root)
    destination = _output(root, output_path)
    add, _, _ = _descriptor_registry(root)

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
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".full-identity-v2.", suffix=".json", dir=destination.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        try:
            identity_loader(project_root=root, manifest_path=temporary)
        except Exception as exc:
            raise FullPublicationIdentityManifestV2Error(
                f"candidate physical identity validation failed: {exc}"
            ) from exc
        try:
            os.replace(temporary, destination)
        except OSError as exc:
            raise FullPublicationIdentityManifestV2Error(
                f"identity manifest atomic commit failed: {exc}"
            ) from exc
        try:
            directory_descriptor = os.open(
                destination.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            except OSError:
                pass
            finally:
                os.close(directory_descriptor)
        try:
            accepted = identity_loader(project_root=root, manifest_path=destination)
        except Exception as exc:
            raise FullPublicationIdentityManifestV2Error(
                f"committed physical identity revalidation failed: {exc}"
            ) from exc
    finally:
        if temporary.exists():
            info = temporary.lstat()
            if (
                temporary.parent != destination.parent
                or not temporary.name.startswith(".full-identity-v2.")
                or not stat.S_ISREG(info.st_mode)
            ):
                raise FullPublicationIdentityManifestV2Error(
                    "refusing unsafe identity manifest temporary cleanup"
                )
            temporary.unlink()
    return {"manifest_path": str(destination), "binding": accepted}


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
