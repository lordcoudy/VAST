#!/usr/bin/env python3
"""Build a fragment-bound policy qualification index without accepting it.

The resulting capability manifest is a qualification candidate.  It may be
used to execute forced-resource pilots, but it is deliberately accompanied by
a non-acceptance receipt and is never a full-publication authority.  Only
``publication_policy_qualification.promote_policy_qualification`` can derive
and atomically promote the accepted capability/calibration pair from all 32
native pilot cells.  Omitting ``pilot_root`` emits a fragment-only candidate
with an empty pilot inventory; that deliberately blocked candidate exists only
to bootstrap the forced-resource qualification runs that materialize the 32
physical pilot cells.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping

import publication_policy_qualification as qualification


INDEX_FILENAME = "checkpoint_policy_qualification_index.v2.json"
CANDIDATE_MANIFEST_FILENAME = "checkpoint_policy_capability_candidate_manifest.json"
CANDIDATE_RECEIPT_FILENAME = "checkpoint_policy_qualification_candidate_receipt.json"

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
    "policy_decisions_jsonl": "publication_policy_decisions.jsonl",
    "resource_intervals": "resource_intervals.csv",
    "ingress_ledger": "ingress_ledger.csv",
    "topology_events": "topology_events.csv",
    "frames": "frames.csv",
    "frame_events": "frame_events.csv",
    "branch_terminals": "branch_terminals.csv",
}


class PolicyQualificationIndexV2Error(RuntimeError):
    """An input or atomic candidate-index publication is unsafe."""


def sha256_file(path: Path) -> str:
    """Return the SHA-256 of *path* without trusting file metadata."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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
        raise PolicyQualificationIndexV2Error(
            "qualification candidate is not canonical JSON"
        ) from exc


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError as exc:
        raise PolicyQualificationIndexV2Error(f"path stat failed: {path}: {exc}") from exc
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)


def _root(project_root: Path) -> Path:
    try:
        root = Path(project_root).resolve(strict=True)
    except OSError as exc:
        raise PolicyQualificationIndexV2Error(
            f"project_root is unavailable: {project_root}"
        ) from exc
    if not root.is_dir() or _is_link(root):
        raise PolicyQualificationIndexV2Error(
            "project_root must be a physical non-reparse directory"
        )
    return root


def _relative_under_root(root: Path, value: Path, label: str) -> str:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PolicyQualificationIndexV2Error(
            f"{label} must exist under project_root"
        ) from exc
    relative_text = relative.as_posix()
    if not relative_text or any(part in ("", ".", "..") for part in relative.parts):
        raise PolicyQualificationIndexV2Error(f"{label} path is not normalized")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_link(cursor):
            raise PolicyQualificationIndexV2Error(
                f"{label} path contains a symlink/reparse point"
            )
    return relative_text


def _regular_file(root: Path, value: Path | str, label: str) -> Path:
    relative = _relative_under_root(root, Path(value), label)
    path = root.joinpath(*Path(relative).parts)
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise PolicyQualificationIndexV2Error(f"{label} stat failed") from exc
    if not stat.S_ISREG(mode):
        raise PolicyQualificationIndexV2Error(f"{label} is not a regular file")
    return path


def _physical_directory(root: Path, value: Path, label: str) -> Path:
    relative = _relative_under_root(root, value, label)
    directory = root.joinpath(*Path(relative).parts)
    if not directory.is_dir():
        raise PolicyQualificationIndexV2Error(f"{label} is not a directory")
    return directory


def _descriptor(root: Path, value: Path | str, label: str) -> dict[str, Any]:
    path = _regular_file(root, value, label)
    before = path.stat()
    if int(before.st_nlink) != 1:
        raise PolicyQualificationIndexV2Error(f"{label} hardlink alias is prohibited")
    digest = sha256_file(path)
    after = path.stat()
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
        raise PolicyQualificationIndexV2Error(f"{label} changed while hashing")
    if before.st_size <= 0:
        raise PolicyQualificationIndexV2Error(f"{label} is empty")
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": int(before.st_size),
        "sha256": digest,
    }


def _read_fragment(
    *,
    root: Path,
    system: str,
    path_value: Path,
    fragment_validator: qualification.FragmentValidator,
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = _regular_file(root, path_value, f"{system} fragment")
    descriptor = _descriptor(root, path, f"{system} fragment")
    try:
        fragment = fragment_validator(system, path, root)
    except Exception as exc:
        raise PolicyQualificationIndexV2Error(
            f"{system} fragment validation failed: {exc}"
        ) from exc
    expected_fields = {
        "schema_version",
        "artifact_kind",
        "system",
        "policy_bindings",
        "resource_bindings",
        "pilots",
    }
    if (
        type(fragment) is not dict
        or set(fragment) != expected_fields
        or fragment.get("schema_version") != 1
        or fragment.get("artifact_kind")
        != "vast_publication_qualification_system_fragment_v1"
        or fragment.get("system") != system
    ):
        raise PolicyQualificationIndexV2Error(
            f"{system} fragment identity/schema drifted"
        )
    return path, descriptor, fragment


def _build_bindings(
    *,
    root: Path,
    fragment_paths: Mapping[str, Path],
    policy: Any,
    fragment_validator: qualification.FragmentValidator,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    systems = tuple(policy.PUBLISHABLE_SYSTEMS)
    branches = tuple(policy.ANALYTICS_BRANCHES)
    resources = tuple(policy.RESOURCES)
    if set(fragment_paths) != set(systems):
        raise PolicyQualificationIndexV2Error(
            "fragment system set must exactly match the four publishable systems"
        )

    fragments: dict[str, dict[str, Any]] = {}
    fragment_descriptors: dict[str, dict[str, Any]] = {}
    for system in systems:
        _, descriptor, fragment = _read_fragment(
            root=root,
            system=system,
            path_value=Path(fragment_paths[system]),
            fragment_validator=fragment_validator,
        )
        fragments[system] = fragment
        fragment_descriptors[system] = descriptor

    bindings: list[dict[str, Any]] = []
    for system in systems:
        rows = fragments[system].get("policy_bindings")
        if type(rows) is not list or len(rows) != len(branches) * len(resources):
            raise PolicyQualificationIndexV2Error(
                f"{system} fragment policy coverage drifted"
            )
        by_coordinate: dict[tuple[str, str], dict[str, Any]] = {}
        for position, row in enumerate(rows):
            if type(row) is not dict:
                raise PolicyQualificationIndexV2Error(
                    f"{system} fragment policy binding[{position}] is invalid"
                )
            coordinate = (str(row.get("branch", "")), str(row.get("resource", "")))
            if coordinate in by_coordinate:
                raise PolicyQualificationIndexV2Error(
                    f"{system} fragment contains a duplicate policy binding"
                )
            by_coordinate[coordinate] = row
        expected = {(branch, resource) for branch in branches for resource in resources}
        if set(by_coordinate) != expected:
            raise PolicyQualificationIndexV2Error(
                f"{system} fragment policy coordinate set drifted"
            )

        for branch in branches:
            for resource in resources:
                row = by_coordinate[(branch, resource)]
                if row.get("role") != "policy":
                    raise PolicyQualificationIndexV2Error(
                        f"{system} fragment {branch}/{resource} role drifted"
                    )
                try:
                    artifact = _descriptor(
                        root,
                        str(row["path"]),
                        f"{system} fragment {branch}/{resource} physical binding",
                    )
                except (KeyError, TypeError, PolicyQualificationIndexV2Error) as exc:
                    raise PolicyQualificationIndexV2Error(
                        f"{system} fragment {branch}/{resource} binding artifact failed: {exc}"
                    ) from exc
                if (
                    row.get("size") != artifact["size_bytes"]
                    or row.get("sha256") != artifact["sha256"]
                ):
                    raise PolicyQualificationIndexV2Error(
                        f"{system} fragment {branch}/{resource} binding size/SHA drifted"
                    )
                binding_sha = artifact["sha256"]
                bindings.append(
                    {
                        "system": system,
                        "branch": branch,
                        "resource": resource,
                        "implementation_id": row.get("implementation_id"),
                        "emitter_id": row.get("emitter_id"),
                        "binding_artifact": artifact,
                        "fragment_artifact": dict(fragment_descriptors[system]),
                        "runtime_binding": (
                            f"{system}:{branch}:{resource}:fragment-v1:{binding_sha}"
                        ),
                        "runtime_identity": row.get("runtime_identity"),
                    }
                )
    return bindings, fragments


def _build_pilots(
    *, root: Path, pilot_root: Path, policy: Any
) -> list[dict[str, Any]]:
    root_directory = _physical_directory(root, pilot_root, "pilot_root")
    pilots: list[dict[str, Any]] = []
    for system in policy.PUBLISHABLE_SYSTEMS:
        for resource in policy.RESOURCES:
            for codec in qualification.CODECS:
                for topology in qualification.TOPOLOGIES:
                    arm = root_directory / system / resource / codec / topology
                    try:
                        arm = _physical_directory(root, arm, "pilot arm")
                    except PolicyQualificationIndexV2Error as exc:
                        raise PolicyQualificationIndexV2Error(
                            "pilot evidence arm is missing or unsafe: "
                            f"{system}/{resource}/{codec}/{topology}"
                        ) from exc
                    evidence: dict[str, dict[str, Any]] = {}
                    identities: set[tuple[int, int]] = set()
                    for role in qualification.PILOT_EVIDENCE_ROLES:
                        filename = PILOT_EVIDENCE_FILENAMES[role]
                        try:
                            descriptor = _descriptor(
                                root,
                                arm / filename,
                                f"pilot evidence {system}/{resource}/{codec}/{topology}/{role}",
                            )
                            info = (root / descriptor["path"]).stat()
                        except (OSError, PolicyQualificationIndexV2Error) as exc:
                            raise PolicyQualificationIndexV2Error(
                                "pilot evidence is missing or unsafe: "
                                f"{system}/{resource}/{codec}/{topology}/{role}"
                            ) from exc
                        identity = (int(info.st_dev), int(info.st_ino))
                        if identity in identities:
                            raise PolicyQualificationIndexV2Error(
                                "pilot evidence alias is prohibited: "
                                f"{system}/{resource}/{codec}/{topology}/{role}"
                            )
                        identities.add(identity)
                        evidence[role] = descriptor
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
        raise PolicyQualificationIndexV2Error(
            "pilot evidence cell set must contain exactly 32 cells"
        )
    return pilots


def _output_destination(root: Path, output_dir: Path) -> Path:
    candidate = Path(output_dir)
    if not candidate.is_absolute():
        candidate = root / candidate
    if candidate.exists():
        raise PolicyQualificationIndexV2Error(
            "immutable qualification candidate output already exists"
        )
    try:
        parent = candidate.parent.resolve(strict=True)
        parent.relative_to(root)
    except (OSError, ValueError) as exc:
        raise PolicyQualificationIndexV2Error(
            "output_dir parent must be a physical directory under project_root"
        ) from exc
    _physical_directory(root, parent, "output_dir parent")
    return parent / candidate.name


def _descriptor_for_payload(root: Path, final_path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": final_path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write_fsync(path: Path, payload: bytes) -> None:
    with path.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def _cleanup_staging_directory(staging: Path, *, parent: Path) -> None:
    """Remove only the private sibling directory allocated by this module."""
    try:
        resolved_parent = parent.resolve(strict=True)
        resolved_staging = staging.resolve(strict=True)
    except OSError as exc:
        raise PolicyQualificationIndexV2Error(
            "qualification staging cleanup target cannot be resolved"
        ) from exc
    if (
        resolved_staging.parent != resolved_parent
        or not resolved_staging.name.startswith(".qualification-index-v2.")
        or resolved_staging == Path.cwd().resolve()
        or _is_link(resolved_staging)
        or not resolved_staging.is_dir()
    ):
        raise PolicyQualificationIndexV2Error(
            "refusing unsafe qualification staging cleanup target"
        )
    shutil.rmtree(resolved_staging)


def _commit_output(
    *,
    root: Path,
    destination: Path,
    index: dict[str, Any],
    candidate_manifest: dict[str, Any],
) -> dict[str, Path]:
    parent = destination.parent
    staging: Path | None = Path(
        tempfile.mkdtemp(prefix=".qualification-index-v2.", dir=parent)
    )
    try:
        index_payload = _canonical_bytes(index)
        candidate_payload = _canonical_bytes(candidate_manifest)
        index_final = destination / INDEX_FILENAME
        candidate_final = destination / CANDIDATE_MANIFEST_FILENAME
        receipt_final = destination / CANDIDATE_RECEIPT_FILENAME
        index_descriptor = _descriptor_for_payload(root, index_final, index_payload)
        candidate_descriptor = _descriptor_for_payload(
            root, candidate_final, candidate_payload
        )
        receipt: dict[str, Any] = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
            "status": "qualification_candidate_not_accepted",
            "accepted": False,
            "publication_ready": False,
            "scope": "forced_resource_qualification_pilots_only",
            "policy_contract_sha256": candidate_manifest["policy_contract_sha256"],
            "qualification_index": index_descriptor,
            "candidate_manifest": candidate_descriptor,
            "blockers": [
                "candidate_is_not_a_full_publication_authority",
                "requires_32_cell_native_pilot_validation_and_atomic_promotion",
            ],
        }
        receipt["sha256"] = hashlib.sha256(
            _canonical_bytes(receipt).rstrip(b"\n")
        ).hexdigest()
        receipt_payload = _canonical_bytes(receipt)

        _write_fsync(staging / INDEX_FILENAME, index_payload)
        _write_fsync(staging / CANDIDATE_MANIFEST_FILENAME, candidate_payload)
        _write_fsync(staging / CANDIDATE_RECEIPT_FILENAME, receipt_payload)
        directory_descriptor = None
        try:
            directory_descriptor = os.open(
                staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            os.fsync(directory_descriptor)
        except OSError:
            pass
        finally:
            if directory_descriptor is not None:
                os.close(directory_descriptor)

        os.replace(staging, destination)
        staging = None
        directory_descriptor = None
        try:
            directory_descriptor = os.open(
                parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            os.fsync(directory_descriptor)
        except OSError:
            pass
        finally:
            if directory_descriptor is not None:
                os.close(directory_descriptor)
        return {
            "index_path": index_final,
            "candidate_manifest_path": candidate_final,
            "candidate_receipt_path": receipt_final,
        }
    except Exception as exc:
        raise PolicyQualificationIndexV2Error(
            f"atomic qualification candidate commit failed: {exc}"
        ) from exc
    finally:
        if staging is not None and staging.exists():
            _cleanup_staging_directory(staging, parent=parent)


def build_policy_qualification_index_v2(
    *,
    project_root: Path,
    fragment_paths: Mapping[str, Path],
    pilot_root: Path | None,
    output_dir: Path,
    policy: Any | None = None,
    fragment_validator: qualification.FragmentValidator | None = None,
) -> dict[str, Path]:
    """Atomically publish either a fragment-only or complete nonaccepted index."""
    root = _root(project_root)
    policy_api = policy or qualification._load_policy_contract()
    validator = fragment_validator or qualification._default_fragment_validator
    destination = _output_destination(root, output_dir)

    try:
        bindings, _ = _build_bindings(
            root=root,
            fragment_paths=fragment_paths,
            policy=policy_api,
            fragment_validator=validator,
        )
        candidate_manifest, _ = qualification._derive_fragment_bound_manifest(
            bindings,
            project_root=root,
            policy=policy_api,
            fragment_validator=validator,
        )
    except PolicyQualificationIndexV2Error:
        raise
    except Exception as exc:
        raise PolicyQualificationIndexV2Error(
            f"fragment-bound capability candidate validation failed: {exc}"
        ) from exc

    pilots = (
        []
        if pilot_root is None
        else _build_pilots(root=root, pilot_root=pilot_root, policy=policy_api)
    )
    dataset = _descriptor(root, root / "configs" / "datasets.yaml", "dataset manifest")
    index = {
        "schema_version": qualification.QUALIFICATION_INDEX_SCHEMA_VERSION,
        "artifact_kind": "vast_publication_policy_qualification_index",
        "policy_contract_sha256": policy_api.policy_contract_identity()["sha256"],
        "dataset_manifest": dataset,
        "bindings": bindings,
        "pilots": pilots,
    }
    return _commit_output(
        root=root,
        destination=destination,
        index=index,
        candidate_manifest=candidate_manifest,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument(
        "--pilot-root",
        type=Path,
        help=(
            "32-cell physical pilot root; omit only for the explicit "
            "fragment-only forced-resource bootstrap candidate"
        ),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
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
        for system in DEFAULT_FRAGMENT_PATHS
    }
    result = build_policy_qualification_index_v2(
        project_root=args.project_root,
        fragment_paths=fragments,
        pilot_root=args.pilot_root,
        output_dir=args.output_dir,
    )
    print(
        json.dumps(
            {key: str(value) for key, value in result.items()},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CANDIDATE_MANIFEST_FILENAME",
    "CANDIDATE_RECEIPT_FILENAME",
    "INDEX_FILENAME",
    "PolicyQualificationIndexV2Error",
    "build_policy_qualification_index_v2",
    "sha256_file",
]
