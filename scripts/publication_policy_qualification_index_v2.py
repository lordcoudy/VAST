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
import stat
from pathlib import Path
from typing import Any, Callable, Mapping

import publication_policy_qualification as qualification
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


INDEX_FILENAME = "checkpoint_policy_qualification_index.v2.json"
CANDIDATE_MANIFEST_FILENAME = "checkpoint_policy_capability_candidate_manifest.json"
CANDIDATE_RECEIPT_FILENAME = "checkpoint_policy_qualification_candidate_receipt.json"
_OUTPUT_NAMESPACE = frozenset(
    {INDEX_FILENAME, CANDIDATE_MANIFEST_FILENAME, CANDIDATE_RECEIPT_FILENAME}
)
# DrvFS without the metadata mount option projects chmod(0444) as 0555.  Both
# representations are world-readable and contain no write bit.
_IMMUTABLE_OUTPUT_MODES = frozenset({0o444, 0o555})

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


ExecutionClosureLoader = Callable[..., dict[str, Any]]


def _default_execution_closure_loader(**kwargs: Any) -> dict[str, Any]:
    from publication_policy_qualification_execution_closure_v1 import (
        load_publication_policy_qualification_execution_closure_v1,
    )

    return load_publication_policy_qualification_execution_closure_v1(**kwargs)


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
    return bindings, fragment_descriptors


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


def _validated_execution_closure_descriptor(
    *,
    root: Path,
    pilot_root: Path,
    receipt_path: Path,
    loader: ExecutionClosureLoader,
    expected_fragment_descriptors: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    descriptor = _descriptor(
        root, receipt_path, "qualification execution closure receipt"
    )
    pilot_directory = _physical_directory(root, pilot_root, "pilot_root")
    try:
        loaded = loader(project_root=root, receipt_path=root / descriptor["path"])
    except PolicyQualificationIndexV2Error:
        raise
    except Exception as exc:
        raise PolicyQualificationIndexV2Error(
            f"qualification execution closure validation failed: {exc}"
        ) from exc
    if type(loaded) is not dict or loaded.get("receipt_descriptor") != descriptor:
        raise PolicyQualificationIndexV2Error(
            "qualification execution closure descriptor drifted"
        )
    receipt = loaded.get("receipt")
    pilot_execution = receipt.get("pilot_execution") if type(receipt) is dict else None
    pilot_identity = (
        pilot_execution.get("pilot_root")
        if type(pilot_execution) is dict
        else None
    )
    cells = pilot_execution.get("cells") if type(pilot_execution) is dict else None
    transaction = (
        receipt.get("qualification_input_transaction")
        if type(receipt) is dict
        else None
    )
    transaction_fragments = (
        transaction.get("fragments") if type(transaction) is dict else None
    )
    if not (
        type(receipt) is dict
        and receipt.get("schema_version") == 1
        and receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_execution_closure_v1"
        and receipt.get("status") == "qualification_execution_closed_nonpublication"
        and receipt.get("qualification_execution_complete") is True
        and receipt.get("accepted_for_full_publication") is False
        and receipt.get("publication_ready") is False
        and receipt.get("authorization_eligible") is False
        and type(pilot_identity) is dict
        and pilot_identity.get("path")
        == pilot_directory.relative_to(root).as_posix()
        and pilot_identity.get("cell_count") == 32
        and type(cells) is list
        and len(cells) == 32
        and type(transaction_fragments) is dict
        and set(transaction_fragments) == set(expected_fragment_descriptors)
        and transaction_fragments
        == {
            system: dict(expected_fragment_descriptors[system])
            for system in expected_fragment_descriptors
        }
    ):
        raise PolicyQualificationIndexV2Error(
            "qualification execution closure identity/pilot/transaction fragment binding drifted"
        )
    return descriptor


def _output_destination(root: Path, output_dir: Path) -> Path:
    raw = Path(output_dir)
    if not raw.is_absolute() and any(part in {"", ".", ".."} for part in raw.parts):
        raise PolicyQualificationIndexV2Error("output_dir path is not normalized")
    candidate = Path(os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw)))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise PolicyQualificationIndexV2Error(
            "output_dir must remain under project_root"
        ) from exc
    if not relative.parts:
        raise PolicyQualificationIndexV2Error("output_dir must be a dedicated directory")
    return candidate


def _descriptor_for_payload(root: Path, final_path: Path, payload: bytes) -> dict[str, Any]:
    return {
        "path": final_path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _commit_or_adopt_output(
    custody: PhysicalRootCustodyV1,
    path: Path,
    payload: bytes,
    *,
    label: str,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> None:
    relative = path.relative_to(custody.root).as_posix()
    expected = _descriptor_for_payload(custody.root, path, payload)

    def physical_step(step: str) -> None:
        if after_physical_commit_step is not None:
            after_physical_commit_step(step, path)

    try:
        observed, identity, disposition = custody.commit_or_adopt_exact_identity(
            relative,
            payload,
            label=label,
            mode=0o444,
            create_parents=False,
            after_publish_step=physical_step,
        )
        cold, existing, cold_identity = custody.read_descriptor_identity(
            relative,
            label=f"committed {label}",
            maximum=len(payload),
            capture=True,
        )
        mode, stat_identity = custody.stat_regular_identity(
            relative, label=f"committed {label} mode"
        )
    except PublicationPhysicalIoV1Error as exc:
        raise PolicyQualificationIndexV2Error(
            f"immutable qualification candidate collision: {path.name}"
        ) from exc
    if (
        disposition not in {"published", "adopted"}
        or observed != expected
        or cold != expected
        or existing != payload
        or cold_identity != identity
        or stat_identity != identity
        or mode not in _IMMUTABLE_OUTPUT_MODES
    ):
        raise PolicyQualificationIndexV2Error(
            f"immutable qualification candidate identity drifted: {path.name}"
        )


def _commit_output(
    *,
    root: Path,
    destination: Path,
    index: dict[str, Any],
    candidate_manifest: dict[str, Any],
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Path]:
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
    expected_payloads = {
        INDEX_FILENAME: index_payload,
        CANDIDATE_MANIFEST_FILENAME: candidate_payload,
        CANDIDATE_RECEIPT_FILENAME: receipt_payload,
    }
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification candidate project_root"
        ) as custody:
            destination = custody.ensure_directory(
                destination, label="qualification candidate output_dir"
            )
            initial = set(
                custody.list_directory_names(
                    destination, label="qualification candidate namespace"
                )
            )
            if CANDIDATE_RECEIPT_FILENAME in initial:
                if initial != set(_OUTPUT_NAMESPACE):
                    raise PolicyQualificationIndexV2Error(
                        "completed qualification candidate namespace drifted"
                    )
            elif not initial <= {INDEX_FILENAME, CANDIDATE_MANIFEST_FILENAME}:
                raise PolicyQualificationIndexV2Error(
                    "incomplete qualification candidate namespace contains an extra entry"
                )
            _commit_or_adopt_output(
                custody,
                index_final,
                index_payload,
                label="qualification index",
                after_physical_commit_step=after_physical_commit_step,
            )
            _commit_or_adopt_output(
                custody,
                candidate_final,
                candidate_payload,
                label="qualification candidate manifest",
                after_physical_commit_step=after_physical_commit_step,
            )
            # Receipt is the final authority-bearing leaf and enables safe resume.
            _commit_or_adopt_output(
                custody,
                receipt_final,
                receipt_payload,
                label="qualification candidate receipt",
                after_physical_commit_step=after_physical_commit_step,
            )
            if set(
                custody.list_directory_names(
                    destination, label="committed qualification candidate namespace"
                )
            ) != set(_OUTPUT_NAMESPACE):
                raise PolicyQualificationIndexV2Error(
                    "committed qualification candidate namespace drifted"
                )
            custody.verify()

        # Reopen after producer descriptors close and verify the exact frozen bundle.
        with PhysicalRootCustodyV1.open(
            root, label="cold qualification candidate project_root"
        ) as custody:
            if set(
                custody.list_directory_names(
                    destination, label="cold qualification candidate namespace"
                )
            ) != set(_OUTPUT_NAMESPACE):
                raise PolicyQualificationIndexV2Error(
                    "cold qualification candidate namespace drifted"
                )
            for name, payload in expected_payloads.items():
                _descriptor, observed = custody.read_descriptor(
                    destination / name,
                    label=f"cold qualification candidate {name}",
                    maximum=len(payload),
                    capture=True,
                )
                mode, _identity = custody.stat_regular_identity(
                    destination / name,
                    label=f"cold qualification candidate {name}",
                )
                if observed != payload or mode not in _IMMUTABLE_OUTPUT_MODES:
                    raise PolicyQualificationIndexV2Error(
                        f"cold qualification candidate drifted: {name}"
                    )
            custody.verify()
    except PolicyQualificationIndexV2Error:
        raise
    except (PublicationPhysicalIoV1Error, OSError) as exc:
        raise PolicyQualificationIndexV2Error(
            f"immutable qualification candidate commit failed: {exc}"
        ) from exc
    return {
        "index_path": index_final,
        "candidate_manifest_path": candidate_final,
        "candidate_receipt_path": receipt_final,
    }


def build_policy_qualification_index_v2(
    *,
    project_root: Path,
    fragment_paths: Mapping[str, Path],
    pilot_root: Path | None,
    output_dir: Path,
    policy: Any | None = None,
    fragment_validator: qualification.FragmentValidator | None = None,
    execution_closure_receipt_path: Path | None = None,
    execution_closure_loader: ExecutionClosureLoader | None = None,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Path]:
    """Atomically publish either a fragment-only or complete nonaccepted index."""
    root = _root(project_root)
    policy_api = policy or qualification._load_policy_contract()
    validator = fragment_validator or qualification._default_fragment_validator
    destination = _output_destination(root, output_dir)

    try:
        bindings, fragment_descriptors = _build_bindings(
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

    if pilot_root is None:
        if execution_closure_receipt_path is not None:
            raise PolicyQualificationIndexV2Error(
                "fragment-only bootstrap candidate cannot consume an execution closure"
            )
        pilots: list[dict[str, Any]] = []
        execution_closure_descriptor: dict[str, Any] | None = None
    else:
        if execution_closure_receipt_path is None:
            raise PolicyQualificationIndexV2Error(
                "completed qualification index requires an execution closure receipt"
            )
        pilots = _build_pilots(root=root, pilot_root=pilot_root, policy=policy_api)
        execution_closure_descriptor = _validated_execution_closure_descriptor(
            root=root,
            pilot_root=pilot_root,
            receipt_path=execution_closure_receipt_path,
            loader=(execution_closure_loader or _default_execution_closure_loader),
            expected_fragment_descriptors=fragment_descriptors,
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
    if execution_closure_descriptor is not None:
        index["qualification_execution_closure"] = execution_closure_descriptor
    return _commit_output(
        root=root,
        destination=destination,
        index=index,
        candidate_manifest=candidate_manifest,
        after_physical_commit_step=after_physical_commit_step,
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
    parser.add_argument("--execution-closure-receipt", type=Path)
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
        execution_closure_receipt_path=args.execution_closure_receipt,
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
