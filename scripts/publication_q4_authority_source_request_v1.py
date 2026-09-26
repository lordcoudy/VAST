#!/usr/bin/env python3
"""Build and commit the canonical production Q4 source-material request.

This is the missing boundary between accepted pre-run qualification artifacts
and :mod:`publication_q4_authority_source_material_v1`.  It cold-loads the
accepted inputs, projects the accepted calibration mapping into four exact
per-system calibration leaves, derives the four static-hybrid maps through the
public policy contract, expands the 32 qualification runtime templates into
the exact 112 Q4 authority requests, and closes the launcher/validator/runner
runtime material.  The request is committed before a self-hashed receipt; no
file is overwritten and no execution or publication authority is issued.
"""
from __future__ import annotations

import argparse
import ast
import copy
import hashlib
import json
import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, MutableMapping, Sequence

from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
)
from backend_publication_launcher_runtime_authority import (
    build_backend_publication_launcher_runtime_authority,
)
from backend_publication_runtime_authority_v2 import (
    build_backend_publication_runtime_authority_v2,
)
from backend_runtime_validation_runner_authority import (
    build_backend_runtime_validation_runner_authority,
)
from backend_runtime_validator_authority_v4 import (
    assess_backend_runtime_validator_authority_v4,
    build_backend_runtime_validator_authority_v4,
)
from production_arm_evidence_finalizer_v1 import (
    native_candidate_evidence_files_v1,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
    canonical_relative_path_v1,
)
from publication_policy_contract import (
    assess_capability_manifest,
    policy_contract_identity,
    select_static_hybrid_map,
)
from publication_q4_authority_source_material_v1 import (
    build_publication_q4_authority_source_material_request_v1,
    build_publication_q4_authority_source_material_v1,
    validate_publication_q4_authority_source_material_request_v1,
)
from publication_q4_runtime_contract_v4 import (
    CODECS,
    DURATION_S,
    POLICIES,
    RUNTIME_INPUT_KEY_BY_SYSTEM,
    RUNTIME_MODULE_BY_SYSTEM,
    STREAMS,
    SYSTEMS,
    TOPOLOGIES,
    WARMUP_S,
)
from publication_q4_runtime_registry_materializer_v4 import (
    build_publication_q4_runtime_launcher_input_wrapper_v3,
    canonical_sha256,
)


SCHEMA_VERSION = 1
RECEIPT_KIND = (
    "vast_publication_q4_authority_source_material_request_"
    "materialization_receipt_v1"
)
REQUEST_FILENAME = "publication_q4_authority_source_material.request.v1.json"
RECEIPT_FILENAME = (
    "publication_q4_authority_source_material.request.materialization.v1.receipt.json"
)
EXIT_REJECTED = 78
MAX_JSON_BYTES = 256 * 1024 * 1024
MAX_SOURCE_BYTES = 8 * 1024 * 1024 * 1024
MAX_PYTHON_BYTES = 256 * 1024 * 1024

_SHA_RE = re.compile(r"[0-9a-f]{64}\Z")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_ACCEPTED_PATH_FIELDS = (
    "model_parity_acceptance_receipt_path",
    "policy_qualification_receipt_path",
    "policy_capability_manifest_path",
    "policy_calibration_mapping_path",
    "resource_qualification_receipt_path",
    "resource_capability_manifest_path",
    "analytics_service_authority_path",
    "guardian_preprocessing_contract_path",
    "guardian_preprocessing_receipt_path",
)
_SUPPORT_FIELDS = frozenset(
    {
        "policy_calibrations",
        "policy_static_maps",
        "python_executable",
        "launcher_runtime_closure_manifests",
        "runner_runtime_bundle_manifest",
        "validator_implementation",
    }
)
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "request",
        "request_sha256",
        "projected_source_material_sha256",
        "qualification_runtime_input_materialization_receipt",
        "accepted_source_descriptors",
        "support_artifacts",
        "support_directories",
        "dataset_source_count",
        "runtime_authority_request_count",
        "launcher_runtime_authority_build_count",
        "receipt_sha256",
    }
)
_LAUNCHER_PATH_BY_SYSTEM = {
    "deepstream": "scripts/checkpoint_deepstream_publication_launcher_v3.py",
    "savant": "scripts/checkpoint_savant_publication_launcher_v3.py",
    "openvino_gva": "scripts/checkpoint_openvino_gva_publication_launcher_v3.py",
    "gstreamer_custom": (
        "scripts/checkpoint_gstreamer_custom_publication_launcher_v3.py"
    ),
}
_RUNTIME_PATH_BY_SYSTEM = {
    "deepstream": "scripts/checkpoint_deepstream_publication_runtime_v3.py",
    "savant": "scripts/checkpoint_savant_publication_runtime_v3.py",
    "openvino_gva": "scripts/checkpoint_openvino_gva_publication_runtime_v3.py",
    "gstreamer_custom": "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
}


class PublicationQ4AuthoritySourceRequestV1Error(RuntimeError):
    """The production request transaction is incomplete or inconsistent."""


@dataclass(frozen=True)
class PreparedPublicationQ4SourceRequestV1:
    request: dict[str, Any]
    qualification_runtime_input_materialization_receipt: dict[str, Any]
    support_artifacts: dict[str, Any]
    support_directories: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProductionPublicationQ4SourceRequestInputsV1:
    accepted_source_paths: Mapping[str, Path | str]
    dataset_manifest_path: Path | str
    qualification_runtime_input_materialization_receipt_path: Path | str
    planned_outputs: Mapping[str, Path | str]
    python_executable_source: Path | str = Path(sys.executable)


class _OwnedMaterializationV1(dict[str, tuple[int, int]]):
    """Current-run ownership plus exact crash-resume transaction state."""

    def __init__(
        self,
        *,
        allow_exact_resume: bool,
        after_owned_commit: Callable[[str, str], None] | None,
        after_physical_commit_step: Callable[[str, str], None] | None,
    ) -> None:
        super().__init__()
        self.allow_exact_resume = allow_exact_resume
        self.after_owned_commit = after_owned_commit
        self.after_physical_commit_step = after_physical_commit_step
        self.output_relative = ""
        self.directories: dict[str, tuple[int, ...]] = {}
        self.adopted_files: dict[str, tuple[int, int]] = {}

    def committed(self, kind: str, path: str) -> None:
        if self.after_owned_commit is not None:
            self.after_owned_commit(kind, path)

    def commit(
        self,
        custody: PhysicalRootCustodyV1,
        path: str,
        payload: bytes,
        *,
        label: str,
        mode: int,
    ) -> dict[str, Any]:
        """Atomically publish, or durably adopt one exact resumable leaf."""

        _require(
            path not in self and path not in self.adopted_files,
            f"{label} path was committed twice",
        )
        expected = {
            "path": path,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

        def physical_step(step: str) -> None:
            _require(
                step
                in {
                    "mid_write",
                    "post_fsync_pre_publish",
                    "post_publish_pre_parent_fsync",
                },
                f"{label} atomic commit step drifted",
            )
            if self.after_physical_commit_step is not None:
                self.after_physical_commit_step(step, path)

        try:
            descriptor, identity, disposition = (
                custody.commit_or_adopt_exact_identity(
                    path,
                    payload,
                    label=label,
                    mode=mode,
                    create_parents=False,
                    after_publish_step=physical_step,
                )
            )
        except PublicationPhysicalIoV1Error as error:
            if self.allow_exact_resume:
                raise PublicationQ4AuthoritySourceRequestV1Error(
                    f"{label} existing partial artifact is not byte-exact"
                ) from error
            raise
        _require(descriptor == expected, f"{label} committed descriptor drifted")
        if disposition == "adopted":
            _require(
                self.allow_exact_resume,
                f"{label} immutable output already exists; overwrite refused",
            )
            self.adopted_files[path] = identity
            return descriptor
        _require(disposition == "published", f"{label} commit disposition drifted")
        self[path] = identity
        self.committed("file", path)
        return descriptor


PrepareRequestV1 = Callable[
    [
        PhysicalRootCustodyV1,
        str,
        MutableMapping[str, tuple[int, int]],
    ],
    PreparedPublicationQ4SourceRequestV1,
]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationQ4AuthoritySourceRequestV1Error(message)


def _canonical_bytes(value: Any, *, newline: bool = False) -> bytes:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (RecursionError, TypeError, UnicodeError, ValueError) as error:
        raise PublicationQ4AuthoritySourceRequestV1Error(
            "Q4 request producer value is not canonical JSON"
        ) from error
    return payload + (b"\n" if newline else b"")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    _require(
        type(value) is str and _SHA_RE.fullmatch(value) is not None,
        f"{label} is not a SHA-256 identity",
    )
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    _require(
        type(value) is dict and set(value) == _DESCRIPTOR_FIELDS,
        f"{label} descriptor fields drifted",
    )
    path = canonical_relative_path_v1(value.get("path"), label=f"{label} path")
    size = value.get("size_bytes")
    _require(
        type(size) is int and 0 < size <= MAX_SOURCE_BYTES,
        f"{label} descriptor size is invalid",
    )
    return {
        "path": path,
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} descriptor"),
    }


def _artifact(role: str, descriptor: Mapping[str, Any]) -> dict[str, Any]:
    checked = _descriptor(dict(descriptor), role)
    return {
        "role": role,
        "descriptor": checked,
        "content_identity_sha256": checked["sha256"],
    }


def _content(value: Mapping[str, Any]) -> dict[str, Any]:
    material = copy.deepcopy(dict(value))
    return {"content": material, "content_identity_sha256": _canonical_sha(material)}


def _read_canonical_json(
    custody: PhysicalRootCustodyV1,
    path: Path | str,
    *,
    label: str,
    maximum: int = MAX_JSON_BYTES,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    descriptor, payload = custody.read_descriptor(
        path, label=label, maximum=maximum, capture=True
    )
    assert payload is not None
    try:
        value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise PublicationQ4AuthoritySourceRequestV1Error(
            f"{label} is not canonical JSON"
        ) from error
    _require(
        type(value) is dict and payload == _canonical_bytes(value, newline=True),
        f"{label} is not canonical JSON",
    )
    return descriptor, value, payload


def _self_hash(value: Mapping[str, Any], field: str, label: str) -> str:
    claimed = _sha(value.get(field), label)
    unsigned = {key: item for key, item in value.items() if key != field}
    _require(claimed == _canonical_sha(unsigned), f"{label} self-hash drifted")
    return claimed


def _collect_descriptors(
    value: Any,
    *,
    label: str,
    result: dict[str, dict[str, Any]] | None = None,
) -> dict[str, dict[str, Any]]:
    output = {} if result is None else result
    if type(value) is dict and set(value) == _DESCRIPTOR_FIELDS:
        item = _descriptor(value, label)
        previous = output.get(item["path"])
        _require(
            previous is None or previous == item,
            f"{label} reuses one path with conflicting pins",
        )
        output[item["path"]] = item
    elif type(value) is dict:
        for key, item in value.items():
            _collect_descriptors(item, label=f"{label}.{key}", result=output)
    elif type(value) is list or type(value) is tuple:
        for position, item in enumerate(value):
            _collect_descriptors(
                item, label=f"{label}[{position}]", result=output
            )
    return output


def _verify_descriptors(
    custody: PhysicalRootCustodyV1,
    descriptors: Mapping[str, Mapping[str, Any]],
    *,
    label: str,
) -> None:
    for position, path in enumerate(
        sorted(descriptors, key=lambda item: (item.casefold(), item))
    ):
        expected = dict(descriptors[path])
        observed, _payload = custody.read_descriptor(
            path,
            label=f"{label}[{position}]",
            maximum=int(expected["size_bytes"]),
            capture=False,
        )
        _require(observed == expected, f"{label}[{position}] drifted")


def _relative_join(parent: str, child: str, *, label: str) -> str:
    safe_child = canonical_relative_path_v1(child, label=label)
    return canonical_relative_path_v1(
        PurePosixPath(parent, safe_child).as_posix(), label=label
    )


def _write_owned(
    custody: PhysicalRootCustodyV1,
    owned: MutableMapping[str, tuple[int, int]],
    path: str,
    payload: bytes,
    *,
    label: str,
    mode: int = 0o444,
) -> dict[str, Any]:
    _require(
        isinstance(owned, _OwnedMaterializationV1),
        f"{label} transaction ownership state is unavailable",
    )
    parent = PurePosixPath(path).parent.as_posix()
    _ensure_owned_directory(custody, owned, parent, label=f"{label} parent")
    return owned.commit(custody, path, payload, label=label, mode=mode)


def _write_owned_json(
    custody: PhysicalRootCustodyV1,
    owned: MutableMapping[str, tuple[int, int]],
    path: str,
    value: Mapping[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    return _write_owned(
        custody,
        owned,
        path,
        _canonical_bytes(dict(value), newline=True),
        label=label,
    )


def _rollback_owned(
    custody: PhysicalRootCustodyV1,
    owned: Mapping[str, tuple[int, int]],
) -> None:
    for path, identity in reversed(tuple(owned.items())):
        try:
            custody.unlink_owned_identity(
                path, identity, label=f"rollback Q4 request artifact {path}"
            )
        except (PublicationPhysicalIoV1Error, OSError):
            # Never unlink an entry whose caller-owned identity can no longer be
            # proven.  The primary failure remains the actionable diagnostic.
            pass
    if isinstance(owned, _OwnedMaterializationV1):
        for path, identity in reversed(tuple(owned.directories.items())):
            try:
                custody.rmdir_owned_identity(
                    path,
                    identity,
                    label=f"rollback Q4 request directory {path}",
                )
            except (PublicationPhysicalIoV1Error, OSError):
                # Foreign content or a rebound directory is never removed.
                pass


def _ensure_owned_directory(
    custody: PhysicalRootCustodyV1,
    owned: MutableMapping[str, tuple[int, int]],
    path: str,
    *,
    label: str,
) -> Path:
    _require(
        isinstance(owned, _OwnedMaterializationV1),
        f"{label} transaction ownership state is unavailable",
    )
    relative = canonical_relative_path_v1(path, label=label)
    result: Path | None = None
    parts = PurePosixPath(relative).parts
    for count in range(1, len(parts) + 1):
        prefix = PurePosixPath(*parts[:count]).as_posix()
        result, created = custody.ensure_directory_owned(prefix, label=label)
        _require(
            len(created) <= 1
            and all(created_path == prefix for created_path, _identity in created),
            f"{label} directory creation journal drifted",
        )
        for created_path, identity in created:
            _require(
                created_path not in owned.directories,
                f"{label} directory was created twice",
            )
            owned.directories[created_path] = identity
            owned.committed("directory", created_path)
        if owned.allow_exact_resume and (
            prefix == owned.output_relative
            or prefix.startswith(owned.output_relative + "/")
        ):
            observed_mode, observed_identity = custody.stat_directory_identity(
                prefix, label=f"exact resumed {label}"
            )
            _require(
                observed_mode == 0o700
                and (
                    not created
                    or observed_identity == created[0][1]
                ),
                f"{label} resumed directory identity or mode drifted",
            )
    assert result is not None
    return result


def publication_q4_validation_identity_pins_v1(
    implementation_descriptor: Mapping[str, Any],
) -> dict[str, str]:
    """Derive all validator protocol pins from one exact implementation leaf."""

    implementation = _descriptor(
        dict(implementation_descriptor), "Q4 validator implementation"
    )
    roles = (
        "qualification_input_schema_identity_sha256",
        "validation_system_context_schema_identity_sha256",
        "validation_request_schema_identity_sha256",
        "validation_record_schema_identity_sha256",
        "validation_system_shard_schema_identity_sha256",
        "validation_record_set_index_schema_identity_sha256",
        "validation_protocol_identity_sha256",
        "validation_input_schema_identity_sha256",
        "validation_output_schema_identity_sha256",
    )
    return {
        role: _canonical_sha(
            {
                "schema_version": 1,
                "artifact_kind": "vast_publication_q4_validation_identity_v1",
                "identity_role": role,
                "validator_schema_version": 4,
                "validator_implementation": implementation,
            }
        )
        for role in roles
    }


def _socket_binding_from_live(
    path: Path | str, *, endpoint: bool, container_path: str | None = None
) -> dict[str, Any]:
    raw = Path(path)
    _require(raw.is_absolute(), "runtime socket path is not absolute")
    normalized = Path(os.path.abspath(os.fspath(raw)))
    _require(normalized == raw, "runtime socket path is not normalized")
    try:
        before = raw.lstat()
        _require(
            stat.S_ISSOCK(before.st_mode) and not stat.S_ISLNK(before.st_mode),
            "runtime socket is not one physical Unix socket",
        )
        after = raw.lstat()
    except OSError as error:
        raise PublicationQ4AuthoritySourceRequestV1Error(
            "runtime socket is unavailable"
        ) from error
    snapshot = lambda item: (
        int(item.st_dev),
        int(item.st_ino),
        int(item.st_mode),
        int(item.st_uid),
        int(item.st_gid),
        int(item.st_ctime_ns),
    )
    _require(snapshot(before) == snapshot(after), "runtime socket changed while pinned")
    result: dict[str, Any] = {
        "device": int(after.st_dev),
        "inode": int(after.st_ino),
        "owner_uid": int(after.st_uid),
        "owner_gid": int(after.st_gid),
    }
    if endpoint:
        _require(type(container_path) is str and bool(container_path),
                 "endpoint container path is missing")
        result.update({"path": str(raw), "container_path": container_path})
    else:
        result["path"] = str(raw)
    return result


def _external_regular_bytes(path: Path | str) -> bytes:
    supplied = Path(os.path.abspath(os.fspath(path)))
    try:
        resolved = supplied.resolve(strict=True)
        descriptor = os.open(
            resolved,
            os.O_RDONLY
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
    except OSError as error:
        raise PublicationQ4AuthoritySourceRequestV1Error(
            "Python executable source is unavailable"
        ) from error
    chunks: list[bytes] = []
    try:
        before = os.fstat(descriptor)
        _require(
            stat.S_ISREG(before.st_mode)
            and 0 < int(before.st_size) <= MAX_PYTHON_BYTES,
            "Python executable source is not one bounded regular file",
        )
        remaining = int(before.st_size)
        while remaining:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            _require(bool(chunk), "Python executable source was truncated")
            chunks.append(chunk)
            remaining -= len(chunk)
        _require(os.read(descriptor, 1) == b"", "Python executable grew while read")
        after = os.fstat(descriptor)
        identity = lambda item: (
            int(item.st_dev), int(item.st_ino), int(item.st_mode),
            int(item.st_nlink), int(item.st_size), int(item.st_mtime_ns),
            int(item.st_ctime_ns),
        )
        _require(identity(before) == identity(after),
                 "Python executable changed while pinned")
    finally:
        os.close(descriptor)
    payload = b"".join(chunks)
    _require(len(payload) == int(before.st_size), "Python executable size drifted")
    return payload


def _python_import_closure(
    custody: PhysicalRootCustodyV1, entry_path: str
) -> list[str]:
    """Return the deterministic recursive closure of local ``scripts/*.py`` imports."""

    entry = canonical_relative_path_v1(entry_path, label="Python closure entry")
    pending = [entry]
    visited: set[str] = set()
    leaves: set[str] = set()
    while pending:
        current = pending.pop()
        if current in visited:
            continue
        visited.add(current)
        _descriptor_value, payload = custody.read_descriptor(
            current,
            label=f"Python closure source {current}",
            maximum=MAX_JSON_BYTES,
            capture=True,
        )
        assert payload is not None
        try:
            tree = ast.parse(payload.decode("utf-8"), filename=current)
        except (UnicodeError, SyntaxError) as error:
            raise PublicationQ4AuthoritySourceRequestV1Error(
                f"Python closure source {current} is not parseable"
            ) from error
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names.add(node.module.split(".", 1)[0])
        for name in sorted(names):
            candidate = f"scripts/{name}.py"
            try:
                custody.read_descriptor(
                    candidate,
                    label=f"Python imported source {candidate}",
                    maximum=MAX_JSON_BYTES,
                    capture=False,
                )
            except PublicationPhysicalIoV1Error:
                continue
            if candidate != entry:
                leaves.add(candidate)
            if candidate not in visited:
                pending.append(candidate)
    return sorted(leaves, key=lambda item: (item.casefold(), item))


def _ref(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    checked = _descriptor(dict(descriptor), "runtime closure leaf")
    return {"descriptor": checked, "content_identity_sha256": checked["sha256"]}


def _build_launcher_closure(
    *,
    custody: PhysicalRootCustodyV1,
    owned: MutableMapping[str, tuple[int, int]],
    output_relative: str,
    system: str,
    python_path: str,
    invocation_sha: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    launcher_path = _LAUNCHER_PATH_BY_SYSTEM[system]
    leaf_paths = _python_import_closure(custody, launcher_path)
    _require(bool(leaf_paths), f"{system} launcher local runtime closure is empty")
    python_descriptor, _ = custody.read_descriptor(
        python_path, label="embedded Python runtime", maximum=MAX_PYTHON_BYTES
    )
    launcher_descriptor, _ = custody.read_descriptor(
        launcher_path, label=f"{system} launcher", maximum=MAX_JSON_BYTES
    )
    leaf_refs = []
    for leaf in leaf_paths:
        item, _ = custody.read_descriptor(
            leaf, label=f"{system} launcher leaf", maximum=MAX_JSON_BYTES
        )
        leaf_refs.append(_ref(item))
    leaf_refs.sort(key=lambda item: item["descriptor"]["path"])
    closure_set = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_publication_launcher_runtime_closure_set",
        "python_executable": _ref(python_descriptor),
        "publication_launcher": _ref(launcher_descriptor),
        "runtime_leaves": leaf_refs,
    }
    set_sha = _canonical_sha(closure_set)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_publication_launcher_runtime_closure_manifest",
        "system": system,
        "python_executable": _ref(python_descriptor),
        "publication_launcher": _ref(launcher_descriptor),
        "runtime_leaves": leaf_refs,
        "runtime_closure_set_sha256": set_sha,
        "publication_launcher_invocation_v3_sha256": invocation_sha,
    }
    manifest["closure_manifest_sha256"] = _canonical_sha(manifest)
    manifest_path = f"{output_relative}/support/launcher/{system}.manifest.v1.json"
    manifest_descriptor = _write_owned_json(
        custody,
        owned,
        manifest_path,
        manifest,
        label=f"{system} launcher closure manifest",
    )
    authority_unsigned = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_publication_launcher_runtime_authority",
        "system": system,
        "runtime_closure_manifest": {
            "descriptor": manifest_descriptor,
            "content_identity_sha256": manifest["closure_manifest_sha256"],
        },
        "runtime_closure_manifest_content": manifest,
        "python_executable": _ref(python_descriptor),
        "publication_launcher": _ref(launcher_descriptor),
        "runtime_leaves": leaf_refs,
        "runtime_closure_set_sha256": set_sha,
        "publication_launcher_invocation_v3_sha256": invocation_sha,
    }
    expected_authority = _canonical_sha(authority_unsigned)
    build = {
        "system": system,
        "runtime_closure_manifest_path": manifest_path,
        "python_executable_path": python_path,
        "publication_launcher_path": launcher_path,
        "runtime_leaf_paths": leaf_paths,
        "expected_authority_sha256": expected_authority,
        "expected_closure_manifest_sha256": manifest["closure_manifest_sha256"],
        "expected_runtime_closure_set_sha256": set_sha,
    }
    built = build_backend_publication_launcher_runtime_authority(
        project_root=custody.root,
        expected_system=system,
        expected_publication_launcher_invocation_v3_sha256=invocation_sha,
        **build,
    )
    _require(
        built["launcher_runtime_authority_sha256"] == expected_authority,
        f"{system} launcher public authority build drifted",
    )
    return build, manifest_descriptor


def _build_validator_runner(
    *,
    custody: PhysicalRootCustodyV1,
    owned: MutableMapping[str, tuple[int, int]],
    output_relative: str,
    python_path: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    validator_path = "scripts/publication_q4_evidence_validator_v4.py"
    runner_path = "scripts/publication_q4_evidence_runner_v4.py"
    validator_descriptor, _ = custody.read_descriptor(
        validator_path, label="Q4 validator implementation", maximum=MAX_JSON_BYTES
    )
    pins = publication_q4_validation_identity_pins_v1(validator_descriptor)
    validator_unsigned = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_validator_authority_q4",
        "validator_id": "backend-runtime-q4-validator-v1",
        "implementation": _ref(validator_descriptor),
        "supported_qualification_schema_version": 4,
        **pins,
        "deterministic": True,
        "execution_authorized": False,
        "validation_records_authenticated": False,
    }
    validator_build = {
        "validator_id": "backend-runtime-q4-validator-v1",
        "implementation_descriptor": validator_descriptor,
        **pins,
        "expected_authority_sha256": _canonical_sha(validator_unsigned),
    }
    validator = build_backend_runtime_validator_authority_v4(**validator_build)
    assessment = assess_backend_runtime_validator_authority_v4(
        validator,
        project_root=custody.root,
        expected_authority_sha256=validator_build["expected_authority_sha256"],
    )
    _require(assessment.get("status") == "physically_valid",
             "Q4 validator public physical assessment blocked")

    runner_descriptor, _ = custody.read_descriptor(
        runner_path, label="Q4 validation runner", maximum=MAX_JSON_BYTES
    )
    python_descriptor, _ = custody.read_descriptor(
        python_path, label="embedded Python runtime", maximum=MAX_PYTHON_BYTES
    )
    leaf_paths = _python_import_closure(custody, runner_path)
    if validator_path not in leaf_paths:
        leaf_paths.append(validator_path)
    leaf_paths = sorted(set(leaf_paths), key=lambda item: (item.casefold(), item))
    leaf_refs = []
    for path in leaf_paths:
        item, _ = custody.read_descriptor(
            path, label="Q4 validation runner leaf", maximum=MAX_JSON_BYTES
        )
        leaf_refs.append(_ref(item))
    leaf_refs.sort(key=lambda item: item["descriptor"]["path"])
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_validation_bundle_manifest",
        "python_executable": _ref(python_descriptor),
        "runner": _ref(runner_descriptor),
        "runtime_leaves": leaf_refs,
        "runtime_leaf_set_sha256": _canonical_sha(leaf_refs),
    }
    manifest["bundle_manifest_sha256"] = _canonical_sha(manifest)
    manifest_path = f"{output_relative}/support/runner/bundle.manifest.v1.json"
    manifest_descriptor = _write_owned_json(
        custody,
        owned,
        manifest_path,
        manifest,
        label="Q4 validation runner bundle manifest",
    )
    runner = build_backend_runtime_validation_runner_authority(
        project_root=custody.root,
        runner_id="backend-runtime-validation-runner-v1",
        runtime_bundle_manifest_path=manifest_path,
        runtime_leaf_paths=leaf_paths,
        python_executable_path=python_path,
        runner_path=runner_path,
        validation_protocol_identity_sha256=pins[
            "validation_protocol_identity_sha256"
        ],
        input_schema_identity_sha256=pins[
            "validation_input_schema_identity_sha256"
        ],
        output_schema_identity_sha256=pins[
            "validation_output_schema_identity_sha256"
        ],
    )
    runner_build = {
        "runner_id": "backend-runtime-validation-runner-v1",
        "runtime_bundle_manifest_path": manifest_path,
        "runtime_leaf_paths": leaf_paths,
        "python_executable_path": python_path,
        "runner_path": runner_path,
        "validation_protocol_identity_sha256": pins[
            "validation_protocol_identity_sha256"
        ],
        "input_schema_identity_sha256": pins[
            "validation_input_schema_identity_sha256"
        ],
        "output_schema_identity_sha256": pins[
            "validation_output_schema_identity_sha256"
        ],
        "expected_runner_authority_sha256": runner["runner_authority_sha256"],
    }
    return validator_build, runner_build, manifest_descriptor, validator_descriptor


def _validate_policy_resource_inputs(
    *,
    custody: PhysicalRootCustodyV1,
    documents: Mapping[str, Mapping[str, Any]],
    descriptors: Mapping[str, Mapping[str, Any]],
    dataset_manifest_descriptor: Mapping[str, Any],
) -> tuple[str, str, str]:
    policy_receipt = documents["policy_qualification_receipt_path"]
    capability = documents["policy_capability_manifest_path"]
    mapping = documents["policy_calibration_mapping_path"]
    _require(
        policy_receipt.get("schema_version") == 1
        and policy_receipt.get("artifact_kind")
        == "vast_publication_policy_qualification_receipt"
        and policy_receipt.get("status")
        == "accepted_evidence_driven_policy_qualification",
        "accepted policy qualification receipt header drifted",
    )
    policy_receipt_sha = _self_hash(
        policy_receipt, "sha256", "accepted policy qualification receipt"
    )
    assessment = assess_capability_manifest(capability)
    _require(
        assessment.get("passed") is True and assessment.get("blockers") == [],
        "accepted policy capability manifest failed the public assessment",
    )
    policy_sha = _sha(
        policy_receipt.get("policy_contract_sha256"), "accepted policy contract"
    )
    _require(
        policy_sha == policy_contract_identity()["sha256"]
        and capability.get("policy_contract_sha256") == policy_sha
        and mapping.get("schema_version") == 1
        and mapping.get("artifact_kind")
        == "vast_publication_policy_calibration_mapping"
        and mapping.get("policy_contract_sha256") == policy_sha
        and type(mapping.get("calibrations")) is dict
        and set(mapping["calibrations"]) == set(SYSTEMS)
        and policy_receipt.get("dataset_manifest_sha256")
        == dataset_manifest_descriptor["sha256"],
        "accepted policy qualification lineage drifted",
    )
    policy_parent = PurePosixPath(
        descriptors["policy_qualification_receipt_path"]["path"]
    ).parent.as_posix()
    if policy_parent == ".":
        policy_parent = ""
    for output_name, source_key in (
        ("capability_manifest", "policy_capability_manifest_path"),
        ("calibration_mapping", "policy_calibration_mapping_path"),
    ):
        raw = (policy_receipt.get("outputs") or {}).get(output_name)
        _require(type(raw) is dict, f"accepted policy {output_name} output is missing")
        expected_path = (
            raw.get("path")
            if not policy_parent
            else _relative_join(policy_parent, raw.get("path"), label="policy output")
        )
        expected = {**raw, "path": expected_path}
        _require(
            _descriptor(expected, f"accepted policy {output_name}")
            == descriptors[source_key],
            f"accepted policy {output_name} descriptor drifted",
        )

    resource_receipt = documents["resource_qualification_receipt_path"]
    resource_manifest = documents["resource_capability_manifest_path"]
    _require(
        resource_receipt.get("schema_version") == 1
        and resource_receipt.get("artifact_kind")
        == "vast_pre_run_full_resource_capability_qualification_receipt"
        and resource_receipt.get("status")
        == "accepted_pre_run_resource_capability_qualification",
        "accepted full-resource qualification receipt header drifted",
    )
    resource_receipt_sha = _self_hash(
        resource_receipt, "sha256", "accepted full-resource qualification receipt"
    )
    resource_unsigned = {
        key: item for key, item in resource_manifest.items() if key != "content_sha256"
    }
    _require(
        resource_manifest.get("schema_version") == 1
        and resource_manifest.get("artifact_kind")
        == "vast_pre_run_full_resource_capability_manifest"
        and resource_manifest.get("content_sha256") == _canonical_sha(resource_unsigned)
        and resource_receipt.get("capability_manifest_content_sha256")
        == resource_manifest["content_sha256"]
        and resource_receipt.get("dataset_manifest_sha256")
        == dataset_manifest_descriptor["sha256"]
        and resource_receipt.get("resource_contract_identity_sha256")
        == resource_manifest.get("resource_contract_identity_sha256"),
        "accepted full-resource qualification lineage drifted",
    )
    resource_parent = PurePosixPath(
        descriptors["resource_qualification_receipt_path"]["path"]
    ).parent.as_posix()
    if resource_parent == ".":
        resource_parent = ""
    raw_resource = (resource_receipt.get("outputs") or {}).get("capability_manifest")
    _require(type(raw_resource) is dict, "accepted resource capability output is missing")
    resource_path = (
        raw_resource.get("path")
        if not resource_parent
        else _relative_join(resource_parent, raw_resource.get("path"), label="resource output")
    )
    _require(
        _descriptor({**raw_resource, "path": resource_path}, "resource output")
        == descriptors["resource_capability_manifest_path"],
        "accepted resource capability descriptor drifted",
    )
    return policy_receipt_sha, resource_receipt_sha, policy_sha


def _dataset_sources(
    *,
    custody: PhysicalRootCustodyV1,
    dataset_manifest_path: Path | str,
    dataset_manifest_descriptor: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    from benchmark_contract import load_dataset

    result: list[dict[str, Any]] = []
    files_by_codec: dict[str, list[dict[str, Any]]] = {}
    for codec in CODECS:
        dataset = load_dataset(
            custody.root.joinpath(
                *PurePosixPath(dataset_manifest_descriptor["path"]).parts
            ),
            f"kpp_iss_publication_v3_{codec}",
            mode="benchmark",
            project_root=custody.root,
            require_files=True,
        )
        _require(
            dataset.get("codec_variant") == codec
            and dataset.get("logical_stream_instances") == STREAMS,
            f"{codec} publication dataset contract drifted",
        )
        unique: dict[str, dict[str, Any]] = {}
        for stream in dataset.get("streams") or []:
            _require(type(stream) is dict, f"{codec} dataset stream is malformed")
            path = canonical_relative_path_v1(
                stream.get("path"), label=f"{codec} dataset stream"
            )
            unique[path] = stream
        _require(len(unique) == 2, f"{codec} dataset does not contain two recordings")
        front_paths = {
            canonical_relative_path_v1(stream["path"], label=f"{codec} front stream")
            for stream in dataset["streams"]
            if stream.get("camera_role") != "foreign_object"
        }
        under_paths = {
            canonical_relative_path_v1(stream["path"], label=f"{codec} underbody stream")
            for stream in dataset["streams"]
            if stream.get("camera_role") == "foreign_object"
        }
        _require(
            len(front_paths) == len(under_paths) == 1
            and front_paths.isdisjoint(under_paths),
            f"{codec} front/underbody dataset roles drifted",
        )
        front, _ = custody.read_descriptor(
            next(iter(front_paths)),
            label=f"{codec} front-gate dataset",
            maximum=MAX_SOURCE_BYTES,
        )
        underbody, _ = custody.read_descriptor(
            next(iter(under_paths)),
            label=f"{codec} underbody dataset",
            maximum=MAX_SOURCE_BYTES,
        )
        files_by_codec[codec] = sorted(
            [front, underbody], key=lambda item: item["path"]
        )
        result.append(
            {
                "codec_variant": codec,
                "front_gate": front,
                "underbody": underbody,
            }
        )
    observed, _ = custody.read_descriptor(
        dataset_manifest_descriptor["path"],
        label="dataset manifest post-public-loader",
        maximum=int(dataset_manifest_descriptor["size_bytes"]),
    )
    _require(observed == dataset_manifest_descriptor,
             "dataset manifest changed during public dataset loading")
    return result, files_by_codec


def _runtime_templates(
    *,
    custody: PhysicalRootCustodyV1,
    receipt_path: Path | str,
) -> tuple[dict[str, Any], dict[tuple[str, str, str, str], dict[str, Any]]]:
    receipt_descriptor, receipt, _payload = _read_canonical_json(
        custody, receipt_path, label="qualification runtime-input receipt"
    )
    _require(
        receipt.get("schema_version") == 2
        and receipt.get("artifact_kind")
        == "vast_qualification_native_runtime_input_materialization_v2"
        and receipt.get("status") == "materialized_for_native_qualification_only"
        and receipt.get("accepted") is False
        and receipt.get("publication_ready") is False
        and receipt.get("authorization_eligible") is False
        and receipt.get("scope")
        == "pre_run_policy_and_full_resource_qualification_only"
        and receipt.get("blockers")
        == ["qualification_runtime_inputs_are_not_production_authority"],
        "qualification runtime-input receipt header drifted",
    )
    _self_hash(receipt, "receipt_sha256", "qualification runtime-input receipt")
    records = receipt.get("bundles")
    _require(type(records) is list and len(records) == 32,
             "qualification runtime-input bundle coverage drifted")
    receipt_parent = PurePosixPath(receipt_descriptor["path"]).parent.as_posix()
    templates: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    physical_identities: set[tuple[int, int]] = set()
    for position, record in enumerate(records):
        _require(type(record) is dict, f"qualification bundle[{position}] record drifted")
        bundle_path = _relative_join(
            receipt_parent,
            record.get("path"),
            label=f"qualification bundle[{position}] path",
        )
        descriptor, payload, identity = custody.read_descriptor_identity(
            bundle_path,
            label=f"qualification bundle[{position}]",
            maximum=MAX_JSON_BYTES,
            capture=True,
        )
        assert payload is not None
        _require(identity not in physical_identities,
                 "qualification runtime bundles alias physically")
        physical_identities.add(identity)
        _require(
            descriptor["size_bytes"] == record.get("size_bytes")
            and descriptor["sha256"] == record.get("sha256"),
            f"qualification bundle[{position}] descriptor drifted",
        )
        try:
            bundle = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
            raise PublicationQ4AuthoritySourceRequestV1Error(
                f"qualification bundle[{position}] is invalid JSON"
            ) from error
        _require(
            type(bundle) is dict
            and payload == _canonical_bytes(bundle, newline=True)
            and bundle.get("schema_version") == 2
            and bundle.get("artifact_kind")
            == "vast_qualification_native_runtime_input_bundle_v2"
            and bundle.get("status") == "materialized_for_native_qualification_only"
            and bundle.get("accepted") is False
            and bundle.get("publication_ready") is False
            and bundle.get("authorization_eligible") is False,
            f"qualification bundle[{position}] header drifted",
        )
        bundle_sha = _self_hash(
            bundle, "bundle_sha256", f"qualification bundle[{position}]"
        )
        _require(bundle_sha == record.get("bundle_sha256"),
                 f"qualification bundle[{position}] semantic pin drifted")
        key = (
            bundle.get("system"),
            bundle.get("resource"),
            bundle.get("codec"),
            bundle.get("topology_kind"),
        )
        _require(
            key[0] in SYSTEMS
            and key[1] in {"cpu", "gpu"}
            and key[2] in CODECS
            and key[3] in TOPOLOGIES
            and key not in templates,
            f"qualification bundle[{position}] coordinate drifted",
        )
        runtime_inputs = bundle.get("runtime_inputs")
        dataset = runtime_inputs.get("dataset") if type(runtime_inputs) is dict else None
        template = (
            dataset.get(RUNTIME_INPUT_KEY_BY_SYSTEM[key[0]])
            if type(dataset) is dict
            else None
        )
        _require(type(template) is dict,
                 f"qualification bundle[{position}] runtime template is missing")
        templates[key] = copy.deepcopy(template)
    expected = {
        (system, resource, codec, topology)
        for system in SYSTEMS
        for resource in ("cpu", "gpu")
        for codec in CODECS
        for topology in TOPOLOGIES
    }
    _require(set(templates) == expected,
             "qualification runtime-input exact coordinate coverage drifted")
    return receipt_descriptor, templates


def _endpoint_template(
    template: Mapping[str, Any], service: Mapping[str, Any]
) -> Any:
    front = service["front_socket"]
    endpoints = template.get("endpoint_sockets")
    if type(endpoints) is list:
        _require(len(endpoints) == 1 and type(endpoints[0]) is dict,
                 "list endpoint ABI drifted")
        container_path = endpoints[0].get("container_path")
        result = _socket_binding_from_live(
            front["path"], endpoint=True, container_path=container_path
        )
        result["host_path"] = result.pop("path")
        return [result]
    _require(
        type(endpoints) is dict
        and set(endpoints) == {"analytics_execution"}
        and type(endpoints["analytics_execution"]) is dict,
        "mapping endpoint ABI drifted",
    )
    return {
        "analytics_execution": _socket_binding_from_live(
            front["path"],
            endpoint=True,
            container_path=endpoints["analytics_execution"].get("container_path"),
        )
    }


def _patch_runtime_template(
    *,
    custody: PhysicalRootCustodyV1,
    template: Mapping[str, Any],
    system: str,
    policy: str,
    codec: str,
    dataset_files: Sequence[Mapping[str, Any]],
    capability_descriptor: Mapping[str, Any],
    calibration_descriptor: Mapping[str, Any],
    static_map_descriptor: Mapping[str, Any],
    execution_descriptor: Mapping[str, Any],
    service: Mapping[str, Any],
    preprocessing_identity_sha256: str,
    scratch_root: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(template))
    module = RUNTIME_MODULE_BY_SYSTEM[system]
    _require(
        type(result.get("files")) is dict
        and set(result["files"]) == set(module.FILE_ROLES),
        f"{system} qualification template file roles drifted",
    )
    source_by_name = {PurePosixPath(item["path"]).name: dict(item) for item in dataset_files}
    patched_sources = []
    for source in result.get("source_files") or []:
        _require(type(source) is dict, f"{system} source descriptor drifted")
        name = PurePosixPath(source.get("path", "")).name
        replacement = source_by_name.get(name)
        _require(replacement is not None, f"{system} {codec} source role drifted")
        patched_sources.append(
            {**replacement, "container_path": source.get("container_path")}
        )
    _require(len(patched_sources) == 2,
             f"{system} {codec} source descriptor coverage drifted")
    result["source_files"] = patched_sources
    result["container_engine_socket"] = _socket_binding_from_live(
        result["container_engine_socket"]["path"], endpoint=False
    )
    result["endpoint_sockets"] = _endpoint_template(result, service)
    result["scratch_root"] = scratch_root
    result["evidence_mapping"] = {
        name: name for name in native_candidate_evidence_files_v1(policy)
    }
    for role, descriptor in (
        ("policy_capability_manifest", capability_descriptor),
        ("policy_calibration", calibration_descriptor),
    ):
        _require(role in result["files"], f"{system} required {role} role is missing")
        result["files"][role] = {
            **_descriptor(dict(descriptor), f"{system} {role}"),
            "container_path": f"/opt/vast/input/runtime/{descriptor['path']}",
        }
    if "analytics_execution_manifest" in module.FILE_ROLES:
        _require("analytics_execution_manifest" in result["files"],
                 f"{system} analytics execution role is missing")
        from checkpoint_native_policy_runtime import (
            EXTERNAL_EXECUTION_MANIFEST_KIND,
            assess_gstreamer_native_policy_execution_manifest,
        )

        manifest_pin = result["files"]["analytics_execution_manifest"]
        observed, manifest, _ = _read_canonical_json(
            custody, manifest_pin["path"], label=f"{system} execution manifest",
        )
        _require(
            observed == {key: manifest_pin.get(key) for key in ("path", "size_bytes", "sha256")}
            and manifest.get("artifact_kind") == EXTERNAL_EXECUTION_MANIFEST_KIND
            and manifest.get("execution_config") == dict(execution_descriptor),
            f"{system} execution manifest/config cross-binding drifted",
        )
        observed_policy, accepted_policy, _ = _read_canonical_json(
            custody, capability_descriptor["path"], label=f"{system} accepted policy",
        )
        _require(observed_policy == dict(capability_descriptor),
                 f"{system} accepted policy descriptor drifted")
        assessment = assess_gstreamer_native_policy_execution_manifest(
            manifest, system=system, capability_manifest=accepted_policy,
            preprocessing_contract_sha256=preprocessing_identity_sha256,
        )
        _require(assessment["passed"],
                 f"{system} execution manifest authority drifted: " + ",".join(assessment["blockers"]))
        # Preserve the exact qualification asset. A changed accepted policy or
        # worker authority requires fresh qualification, never silent rebinding.
    else:
        _require("analytics_execution_manifest" not in result["files"],
                 f"{system} gained a non-ABI analytics execution role")
    if "preprocessing_contract_sha256" in result:
        result["preprocessing_contract_sha256"] = preprocessing_identity_sha256
    result["static_hybrid_map"] = (
        {
            **_descriptor(dict(static_map_descriptor), f"{system} static map"),
            "container_path": f"/opt/vast/input/runtime/{static_map_descriptor['path']}",
        }
        if policy == "static_hybrid"
        else None
    )
    _require(set(result["files"]) == set(module.FILE_ROLES),
             f"{system} runtime file roles changed during production projection")
    return result


def _prepare_production_request(
    *,
    inputs: ProductionPublicationQ4SourceRequestInputsV1,
) -> PrepareRequestV1:
    def prepare(
        custody: PhysicalRootCustodyV1,
        output_relative: str,
        owned: MutableMapping[str, tuple[int, int]],
    ) -> PreparedPublicationQ4SourceRequestV1:
        _require(
            set(inputs.accepted_source_paths) == set(_ACCEPTED_PATH_FIELDS),
            "accepted source path coverage drifted",
        )
        descriptors: dict[str, dict[str, Any]] = {}
        documents: dict[str, dict[str, Any]] = {}
        for key in _ACCEPTED_PATH_FIELDS:
            descriptor, document, _payload = _read_canonical_json(
                custody,
                inputs.accepted_source_paths[key],
                label=f"accepted source {key}",
            )
            descriptors[key] = descriptor
            documents[key] = document
        dataset_manifest_descriptor, _ = custody.read_descriptor(
            inputs.dataset_manifest_path,
            label="accepted dataset manifest",
            maximum=MAX_JSON_BYTES,
        )
        policy_receipt_sha, resource_receipt_sha, policy_sha = (
            _validate_policy_resource_inputs(
                custody=custody,
                documents=documents,
                descriptors=descriptors,
                dataset_manifest_descriptor=dataset_manifest_descriptor,
            )
        )

        from checkpoint_model_parity_acceptance_v4 import (
            load_verified_model_parity_acceptance_v4,
        )
        from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
            load_accepted_policy_guardian_preprocessing_contract_v1,
        )

        parity_binding = load_verified_model_parity_acceptance_v4(
            project_root=custody.root,
            receipt_path=inputs.accepted_source_paths[
                "model_parity_acceptance_receipt_path"
            ],
        )
        _require(
            parity_binding.get("receipt")
            == descriptors["model_parity_acceptance_receipt_path"],
            "accepted model-parity receipt descriptor drifted",
        )
        guardian = load_accepted_policy_guardian_preprocessing_contract_v1(
            project_root=custody.root,
            preprocessing_contract_path=inputs.accepted_source_paths[
                "guardian_preprocessing_contract_path"
            ],
            materialization_receipt_path=inputs.accepted_source_paths[
                "guardian_preprocessing_receipt_path"
            ],
            accepted_policy_capability_manifest_path=inputs.accepted_source_paths[
                "policy_capability_manifest_path"
            ],
        )
        guardian_receipt = guardian["receipt"]
        guardian_authority = guardian["authority"]
        _require(
            guardian_receipt.get("accepted_policy_qualification_receipt")
            == descriptors["policy_qualification_receipt_path"]
            and guardian_receipt.get("accepted_policy_calibration_mapping")
            == descriptors["policy_calibration_mapping_path"]
            and guardian_authority.get("policy_contract_sha256") == policy_sha,
            "accepted guardian/policy lineage drifted",
        )
        # This public validator is POSIX-only because its production module
        # owns Unix-domain socket custody.  Keep the import lazy so pure
        # transaction tests remain importable on Windows.
        from checkpoint_gstreamer_analytics_sidecar import (
            validate_publication_sidecar_service_authority_v1,
        )

        service = validate_publication_sidecar_service_authority_v1(
            documents["analytics_service_authority_path"]
        )
        _require(
            service.get("preprocessing_contract_authority") == guardian_authority,
            "analytics service is not bound to accepted guardian preprocessing",
        )
        execution_descriptor = _descriptor(
            guardian_receipt.get("execution_config"),
            "accepted guardian execution config",
        )
        execution_observed, _ = custody.read_descriptor(
            execution_descriptor["path"],
            label="accepted guardian execution config",
            maximum=int(execution_descriptor["size_bytes"]),
        )
        _require(execution_observed == execution_descriptor,
                 "accepted guardian execution config descriptor drifted")

        mapping = documents["policy_calibration_mapping_path"]
        capability = documents["policy_capability_manifest_path"]
        calibrations: dict[str, dict[str, Any]] = {}
        static_maps: dict[str, dict[str, Any]] = {}
        for system in SYSTEMS:
            calibration = copy.deepcopy(mapping["calibrations"][system])
            _require(
                type(calibration) is dict
                and calibration.get("schema_version") == 1
                and calibration.get("artifact_kind")
                == "vast_publication_policy_calibration"
                and calibration.get("system") == system
                and calibration.get("policy_contract_sha256") == policy_sha,
                f"accepted {system} calibration projection drifted",
            )
            calibration_path = (
                f"{output_relative}/support/policy-calibration/{system}.v1.json"
            )
            calibrations[system] = _write_owned_json(
                custody,
                owned,
                calibration_path,
                calibration,
                label=f"accepted {system} calibration projection",
            )
            # The exact accepted mapping remains an upstream source.  Only the
            # public per-system calibration value is passed to policy semantics.
            static_map = select_static_hybrid_map(system, calibration, capability)
            static_path = f"{output_relative}/support/policy-static-map/{system}.v1.json"
            static_maps[system] = _write_owned_json(
                custody,
                owned,
                static_path,
                static_map,
                label=f"{system} static-hybrid map",
            )

        python_path = f"{output_relative}/support/runtime/python3"
        python_descriptor = _write_owned(
            custody,
            owned,
            python_path,
            _external_regular_bytes(inputs.python_executable_source),
            label="embedded Q4 Python executable",
            mode=0o555,
        )
        invocation_sha = publication_launcher_invocation_v3_contract()[
            "invocation_sha256"
        ]
        launcher_builds: list[dict[str, Any]] = []
        launcher_manifests: dict[str, dict[str, Any]] = {}
        for system in SYSTEMS:
            build, manifest_descriptor = _build_launcher_closure(
                custody=custody,
                owned=owned,
                output_relative=output_relative,
                system=system,
                python_path=python_path,
                invocation_sha=invocation_sha,
            )
            launcher_builds.append(build)
            launcher_manifests[system] = manifest_descriptor
        validator_build, runner_build, runner_manifest, validator_descriptor = (
            _build_validator_runner(
                custody=custody,
                owned=owned,
                output_relative=output_relative,
                python_path=python_path,
            )
        )

        dataset_sources, dataset_files_by_codec = _dataset_sources(
            custody=custody,
            dataset_manifest_path=inputs.dataset_manifest_path,
            dataset_manifest_descriptor=dataset_manifest_descriptor,
        )
        qualification_receipt_descriptor, templates = _runtime_templates(
            custody=custody,
            receipt_path=inputs.qualification_runtime_input_materialization_receipt_path,
        )
        resource_manifest = documents["resource_capability_manifest_path"]
        resource_contract = resource_manifest.get("resource_contract")
        _require(
            type(resource_contract) is dict
            and _canonical_sha(resource_contract)
            == resource_manifest.get("resource_contract_identity_sha256"),
            "accepted resource contract content/identity drifted",
        )
        upstream = {
            "dataset_manifest_sha256": dataset_manifest_descriptor["sha256"],
            "policy_contract_sha256": policy_sha,
            "policy_qualification_receipt_sha256": policy_receipt_sha,
            "resource_contract_identity_sha256": resource_manifest[
                "resource_contract_identity_sha256"
            ],
            "resource_qualification_receipt_sha256": resource_receipt_sha,
            "analytics_execution_config_identity_sha256": guardian_authority[
                "execution_config_identity_sha256"
            ],
            "model_parity_manifest_identity_sha256": parity_binding[
                "accepted_manifest_content_identity_sha256"
            ],
            "model_parity_acceptance_binding_sha256": parity_binding[
                "binding_sha256"
            ],
        }
        analytics_authority = {
            "endpoint_authority": {
                "transport": "AF_UNIX/SOCK_SEQPACKET",
                "path_derivation_contract_sha256": _canonical_sha(
                    {
                        "schema_version": 1,
                        "transport": "AF_UNIX/SOCK_SEQPACKET",
                        "service_identity_sha256": service["service_identity_sha256"],
                        "front_socket_path": service["front_socket"]["path"],
                    }
                ),
                "peer_capability_identity_sha256": service[
                    "service_identity_sha256"
                ],
                "peer_binding_identity_sha256": service[
                    "service_authority_sha256"
                ],
                "bind_before_backend_launch": True,
                "peer_credentials_required": True,
            },
            "capability": _artifact(
                "analytics_endpoint_capability",
                descriptors["analytics_service_authority_path"],
            ),
            "bindings": [
                _artifact(
                    "analytics_worker_binding",
                    descriptors["guardian_preprocessing_receipt_path"],
                )
            ],
            "preprocessing_contract_sha256": guardian_authority[
                "preprocessing_contract_content_sha256"
            ],
        }
        source_artifacts: dict[str, dict[str, Any]] = {}
        backend_artifacts: dict[str, dict[str, Any]] = {}
        for system in SYSTEMS:
            source_descriptor, _ = custody.read_descriptor(
                _RUNTIME_PATH_BY_SYSTEM[system],
                label=f"{system} production runtime implementation",
                maximum=MAX_JSON_BYTES,
            )
            backend_descriptor, _ = custody.read_descriptor(
                _LAUNCHER_PATH_BY_SYSTEM[system],
                label=f"{system} production launcher implementation",
                maximum=MAX_JSON_BYTES,
            )
            source_artifacts[system] = _artifact("source_binary", source_descriptor)
            backend_artifacts[system] = _artifact("runtime_binary", backend_descriptor)

        support_directories: list[str] = []
        scratch_by_system: dict[str, str] = {}
        for system in SYSTEMS:
            relative = f"{output_relative}/support/scratch/{system}"
            directory = _ensure_owned_directory(
                custody,
                owned,
                relative,
                label=f"{system} production Q4 scratch directory",
            )
            scratch_by_system[system] = str(directory)
            support_directories.append(relative)

        runtime_requests: list[dict[str, Any]] = []
        capability_artifact = _artifact(
            "policy_capability", descriptors["policy_capability_manifest_path"]
        )
        for system in SYSTEMS:
            for codec in CODECS:
                for topology in TOPOLOGIES:
                    for policy in POLICIES:
                        resource = "gpu" if policy == "gpu_only" else "cpu"
                        template = _patch_runtime_template(
                            custody=custody,
                            template=templates[(system, resource, codec, topology)],
                            system=system,
                            policy=policy,
                            codec=codec,
                            dataset_files=dataset_files_by_codec[codec],
                            capability_descriptor=descriptors[
                                "policy_capability_manifest_path"
                            ],
                            calibration_descriptor=calibrations[system],
                            static_map_descriptor=static_maps[system],
                            execution_descriptor=execution_descriptor,
                            service=service,
                            preprocessing_identity_sha256=guardian_authority[
                                "preprocessing_contract_content_sha256"
                            ],
                            scratch_root=scratch_by_system[system],
                        )
                        wrapper = build_publication_q4_runtime_launcher_input_wrapper_v3(
                            system=system,
                            policy=policy,
                            qualification_runtime_input_template=template,
                            production_runtime_input_template=copy.deepcopy(template),
                        )
                        calibration_artifact = _artifact(
                            "policy_calibration", calibrations[system]
                        )
                        static_artifact = (
                            _artifact("policy_static_map", static_maps[system])
                            if policy == "static_hybrid"
                            else None
                        )
                        policy_authority = {
                            "capability": copy.deepcopy(capability_artifact),
                            "calibration": calibration_artifact,
                            "static_map": static_artifact,
                        }
                        authority_inputs = {
                            "dataset_manifest": dataset_manifest_descriptor,
                            "dataset_files": dataset_files_by_codec[codec],
                            "source_runtime_artifacts": [source_artifacts[system]],
                            "backend_runtime_artifacts": [backend_artifacts[system]],
                            "analytics_authority": analytics_authority,
                            "policy_authority": policy_authority,
                            "cohort_topology_plan": _content(
                                {
                                    "topology_kind": topology,
                                    "warmup_s": WARMUP_S,
                                    "measurement_s": DURATION_S,
                                    "source_decode_count": (
                                        1 if topology == "shared_video_dag" else STREAMS
                                    ),
                                }
                            ),
                            "resource_contract": _content(resource_contract),
                            "system_specific_launcher_input": _content(wrapper),
                        }
                        coordinate = {
                            "system": system,
                            "codec": codec,
                            "topology_kind": topology,
                            "policy": policy,
                        }
                        expected_policy_outputs = {
                            "capability": capability_artifact["descriptor"],
                            "calibration": calibration_artifact["descriptor"],
                            "static_map": (
                                None
                                if static_artifact is None
                                else static_artifact["descriptor"]
                            ),
                        }
                        build_backend_publication_runtime_authority_v2(
                            project_root=custody.root,
                            **coordinate,
                            **authority_inputs,
                            upstream_identities=upstream,
                            expected_upstream_identities=upstream,
                            expected_policy_outputs=expected_policy_outputs,
                        )
                        runtime_requests.append(
                            {"coordinate": coordinate, "inputs": authority_inputs}
                        )

        planned = {
            key: canonical_relative_path_v1(value, label=f"planned output {key}")
            for key, value in inputs.planned_outputs.items()
        }
        request = build_publication_q4_authority_source_material_request_v1(
            accepted_upstream_identities=upstream,
            accepted_source_descriptors=descriptors,
            expected_analytics_service_identity_sha256=service[
                "service_identity_sha256"
            ],
            dataset_source_descriptors=dataset_sources,
            runtime_authority_requests=runtime_requests,
            launcher_runtime_authority_builds=launcher_builds,
            publication_launcher_invocation_v3_sha256=invocation_sha,
            q4_validator_authority_build=validator_build,
            runner_authority_build=runner_build,
            planned_outputs=planned,
        )
        support = {
            "policy_calibrations": calibrations,
            "policy_static_maps": static_maps,
            "python_executable": python_descriptor,
            "launcher_runtime_closure_manifests": launcher_manifests,
            "runner_runtime_bundle_manifest": runner_manifest,
            "validator_implementation": validator_descriptor,
        }
        return PreparedPublicationQ4SourceRequestV1(
            request=request,
            qualification_runtime_input_materialization_receipt=(
                qualification_receipt_descriptor
            ),
            support_artifacts=support,
            support_directories=tuple(
                sorted(support_directories, key=lambda item: (item.casefold(), item))
            ),
        )

    return prepare


def _validate_support_artifacts(value: Any) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _SUPPORT_FIELDS,
             "Q4 request support artifact fields drifted")
    calibrations = value.get("policy_calibrations")
    static_maps = value.get("policy_static_maps")
    launchers = value.get("launcher_runtime_closure_manifests")
    _require(
        type(calibrations) is dict
        and type(static_maps) is dict
        and type(launchers) is dict
        and set(calibrations) == set(SYSTEMS)
        and set(static_maps) == set(SYSTEMS)
        and set(launchers) == set(SYSTEMS),
        "Q4 request support system coverage drifted",
    )
    checked = {
        "policy_calibrations": {
            system: _descriptor(calibrations[system], f"{system} calibration support")
            for system in SYSTEMS
        },
        "policy_static_maps": {
            system: _descriptor(static_maps[system], f"{system} static-map support")
            for system in SYSTEMS
        },
        "python_executable": _descriptor(value.get("python_executable"), "Python support"),
        "launcher_runtime_closure_manifests": {
            system: _descriptor(launchers[system], f"{system} launcher support")
            for system in SYSTEMS
        },
        "runner_runtime_bundle_manifest": _descriptor(
            value.get("runner_runtime_bundle_manifest"), "runner support"
        ),
        "validator_implementation": _descriptor(
            value.get("validator_implementation"), "validator support"
        ),
    }
    for name in (
        "policy_calibrations",
        "policy_static_maps",
        "launcher_runtime_closure_manifests",
    ):
        paths = [checked[name][system]["path"] for system in SYSTEMS]
        _require(
            len({path.casefold() for path in paths}) == len(SYSTEMS),
            f"Q4 request support {name} paths alias",
        )
    return checked


def validate_publication_q4_authority_source_request_receipt_v1(
    value: Any,
) -> dict[str, Any]:
    _require(type(value) is dict and set(value) == _RECEIPT_FIELDS,
             "Q4 request receipt fields drifted")
    _require(
        value.get("schema_version") == SCHEMA_VERSION
        and value.get("artifact_kind") == RECEIPT_KIND
        and value.get("status")
        == "materialized_non_authorizing_q4_authority_source_request"
        and value.get("authorization_eligible") is False
        and value.get("execution_authorized") is False,
        "Q4 request receipt header/claims drifted",
    )
    request = _descriptor(value.get("request"), "Q4 request receipt")
    request_sha = _sha(value.get("request_sha256"), "Q4 request semantic")
    material_sha = _sha(
        value.get("projected_source_material_sha256"),
        "projected Q4 source material",
    )
    qualification = _descriptor(
        value.get("qualification_runtime_input_materialization_receipt"),
        "qualification runtime-input receipt",
    )
    accepted = value.get("accepted_source_descriptors")
    _require(
        type(accepted) is dict and set(accepted) == set(_ACCEPTED_PATH_FIELDS),
        "Q4 request receipt accepted-source coverage drifted",
    )
    checked_accepted = {
        key: _descriptor(accepted[key], f"accepted source {key}")
        for key in _ACCEPTED_PATH_FIELDS
    }
    support = _validate_support_artifacts(value.get("support_artifacts"))
    directories = value.get("support_directories")
    _require(type(directories) is list,
             "Q4 request receipt support directories are invalid")
    checked_directories = [
        canonical_relative_path_v1(item, label="Q4 support directory")
        for item in directories
    ]
    _require(
        checked_directories
        == sorted(set(checked_directories), key=lambda item: (item.casefold(), item)),
        "Q4 request receipt support directories are not sorted and unique",
    )
    _require(
        value.get("dataset_source_count") == len(CODECS)
        and value.get("runtime_authority_request_count")
        == len(SYSTEMS) * len(CODECS) * len(TOPOLOGIES) * len(POLICIES)
        and value.get("launcher_runtime_authority_build_count") == len(SYSTEMS),
        "Q4 request receipt coverage drifted",
    )
    unsigned = {key: item for key, item in value.items() if key != "receipt_sha256"}
    receipt_sha = _sha(value.get("receipt_sha256"), "Q4 request receipt")
    _require(receipt_sha == _canonical_sha(unsigned),
             "Q4 request receipt self-hash drifted")
    return {
        **copy.deepcopy(unsigned),
        "request": request,
        "request_sha256": request_sha,
        "projected_source_material_sha256": material_sha,
        "qualification_runtime_input_materialization_receipt": qualification,
        "accepted_source_descriptors": checked_accepted,
        "support_artifacts": support,
        "support_directories": checked_directories,
        "receipt_sha256": receipt_sha,
    }


def _expected_namespace(
    output_relative: str,
    descriptors: Mapping[str, Mapping[str, Any]],
    directories: Sequence[str],
) -> dict[str, set[str]]:
    tree: dict[str, set[str]] = {output_relative: set()}
    paths = [
        *(
            path
            for path in descriptors
            if path.startswith(output_relative + "/")
        ),
        *directories,
    ]
    for path in paths:
        safe = canonical_relative_path_v1(path, label="Q4 request namespace path")
        _require(
            safe == output_relative or safe.startswith(output_relative + "/"),
            "Q4 request namespace path escaped output directory",
        )
        parts = PurePosixPath(safe).parts
        root_parts = PurePosixPath(output_relative).parts
        for index in range(len(root_parts), len(parts)):
            parent = PurePosixPath(*parts[:index]).as_posix()
            tree.setdefault(parent, set()).add(parts[index])
            if index < len(parts) - 1 or safe in directories:
                tree.setdefault(PurePosixPath(*parts[: index + 1]).as_posix(), set())
    return tree


def _verify_namespace(
    custody: PhysicalRootCustodyV1,
    *,
    output_relative: str,
    owned_descriptors: Mapping[str, Mapping[str, Any]],
    support_directories: Sequence[str],
) -> None:
    expected = _expected_namespace(
        output_relative, owned_descriptors, support_directories
    )
    for path in sorted(expected, key=lambda item: (item.count("/"), item)):
        observed = custody.list_directory_names(path, label=f"Q4 namespace {path}")
        _require(
            observed == tuple(sorted(expected[path])),
            f"Q4 request namespace {path} drifted",
        )


def load_publication_q4_authority_source_request_receipt_v1(
    *,
    project_root: Path | str,
    receipt_path: Path | str,
    expected_receipt_file_sha256: str,
    expected_receipt_sha256: str,
) -> dict[str, Any]:
    with PhysicalRootCustodyV1.open(
        project_root, label="Q4 request receipt project_root"
    ) as custody:
        receipt_descriptor, raw, _payload = _read_canonical_json(
            custody, receipt_path, label="Q4 request receipt"
        )
        _require(
            receipt_descriptor["sha256"]
            == _sha(expected_receipt_file_sha256, "expected Q4 request receipt file"),
            "Q4 request receipt raw-file pin drifted",
        )
        receipt = validate_publication_q4_authority_source_request_receipt_v1(raw)
        _require(
            receipt["receipt_sha256"]
            == _sha(expected_receipt_sha256, "expected Q4 request receipt semantic"),
            "Q4 request receipt semantic pin drifted",
        )
        request_descriptor, request_raw, _request_payload = _read_canonical_json(
            custody, receipt["request"]["path"], label="Q4 source-material request"
        )
        request = validate_publication_q4_authority_source_material_request_v1(
            request_raw
        )
        _require(
            request_descriptor == receipt["request"]
            and request["request_sha256"] == receipt["request_sha256"]
            and request["accepted_source_descriptors"]
            == receipt["accepted_source_descriptors"],
            "Q4 request receipt/request binding drifted",
        )
        closure = _collect_descriptors(
            request, label="Q4 cold-loaded request input"
        )
        _collect_descriptors(
            receipt["support_artifacts"],
            label="Q4 request support",
            result=closure,
        )
        closure[request_descriptor["path"]] = request_descriptor
        closure[receipt_descriptor["path"]] = receipt_descriptor
        _verify_descriptors(custody, closure, label="Q4 committed request closure")
        output_relative = PurePosixPath(receipt_descriptor["path"]).parent.as_posix()
        _verify_namespace(
            custody,
            output_relative=output_relative,
            owned_descriptors=closure,
            support_directories=receipt["support_directories"],
        )
        return receipt


def materialize_publication_q4_authority_source_request_v1(
    *,
    project_root: Path | str,
    output_dir: Path | str,
    production_inputs: ProductionPublicationQ4SourceRequestInputsV1 | None = None,
    prepare_request: PrepareRequestV1 | None = None,
    after_preflight: Callable[[], None] | None = None,
    after_owned_commit: Callable[[str, str], None] | None = None,
    after_physical_commit_step: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    """Commit a fully preflighted request and then its receipt, without overwrite."""

    _require(
        (production_inputs is None) != (prepare_request is None),
        "exactly one production_inputs or prepare_request source is required",
    )
    prepare = (
        _prepare_production_request(inputs=production_inputs)
        if production_inputs is not None
        else prepare_request
    )
    assert prepare is not None
    owned = _OwnedMaterializationV1(
        allow_exact_resume=production_inputs is not None,
        after_owned_commit=after_owned_commit,
        after_physical_commit_step=after_physical_commit_step,
    )
    with PhysicalRootCustodyV1.open(
        project_root, label="Q4 request producer project_root"
    ) as custody:
        output_relative = canonical_relative_path_v1(
            output_dir, label="Q4 request producer output directory"
        )
        owned.output_relative = output_relative
        try:
            _ensure_owned_directory(
                custody,
                owned,
                output_relative,
                label="Q4 request producer output directory",
            )
            existing_entries = custody.list_directory_names(
                output_relative, label="Q4 request producer output preflight"
            )
            if owned.allow_exact_resume:
                _require(
                    set(existing_entries)
                    <= {"support", REQUEST_FILENAME, RECEIPT_FILENAME},
                    "Q4 request producer output contains a foreign partial entry; "
                    "overwrite refused",
                )
            else:
                _require(
                    existing_entries == (),
                    "Q4 request producer output directory is not empty; "
                    "overwrite refused",
                )
            prepared = prepare(custody, output_relative, owned)
            _require(
                isinstance(prepared, PreparedPublicationQ4SourceRequestV1),
                "Q4 request preparation result type drifted",
            )
            request = validate_publication_q4_authority_source_material_request_v1(
                prepared.request
            )
            qualification = _descriptor(
                prepared.qualification_runtime_input_materialization_receipt,
                "qualification runtime-input receipt",
            )
            support = _validate_support_artifacts(prepared.support_artifacts)
            directories = tuple(
                canonical_relative_path_v1(item, label="Q4 support directory")
                for item in prepared.support_directories
            )
            _require(
                list(directories)
                == sorted(set(directories), key=lambda item: (item.casefold(), item)),
                "Q4 support directories are not sorted and unique",
            )
            request_path = f"{output_relative}/{REQUEST_FILENAME}"
            receipt_path = f"{output_relative}/{RECEIPT_FILENAME}"
            request_descriptor = _write_owned(
                custody,
                owned,
                request_path,
                _canonical_bytes(request, newline=True),
                label="canonical Q4 source-material request",
            )
            initial_descriptors = _collect_descriptors(
                request, label="Q4 request preflight inputs"
            )
            _collect_descriptors(
                support, label="Q4 request support", result=initial_descriptors
            )
            initial_descriptors[qualification["path"]] = qualification
            _material, projected_sha = build_publication_q4_authority_source_material_v1(
                project_root=custody.root, request=request
            )
            if after_preflight is not None:
                after_preflight()
            _verify_descriptors(
                custody, initial_descriptors, label="Q4 request post-build input"
            )
            observed_request, observed_payload = custody.read_descriptor(
                request_path,
                label="Q4 request post-build commit",
                maximum=request_descriptor["size_bytes"],
                capture=True,
            )
            _require(
                observed_request == request_descriptor
                and observed_payload == _canonical_bytes(request, newline=True),
                "Q4 source-material request changed during public preflight",
            )
            receipt_unsigned = {
                "schema_version": SCHEMA_VERSION,
                "artifact_kind": RECEIPT_KIND,
                "status": "materialized_non_authorizing_q4_authority_source_request",
                "authorization_eligible": False,
                "execution_authorized": False,
                "request": request_descriptor,
                "request_sha256": request["request_sha256"],
                "projected_source_material_sha256": projected_sha,
                "qualification_runtime_input_materialization_receipt": qualification,
                "accepted_source_descriptors": copy.deepcopy(
                    request["accepted_source_descriptors"]
                ),
                "support_artifacts": support,
                "support_directories": list(directories),
                "dataset_source_count": len(request["dataset_source_descriptors"]),
                "runtime_authority_request_count": len(
                    request["runtime_authority_requests"]
                ),
                "launcher_runtime_authority_build_count": len(
                    request["launcher_runtime_authority_builds"]
                ),
            }
            receipt = validate_publication_q4_authority_source_request_receipt_v1(
                {
                    **receipt_unsigned,
                    "receipt_sha256": _canonical_sha(receipt_unsigned),
                }
            )
            receipt_descriptor = _write_owned(
                custody,
                owned,
                receipt_path,
                _canonical_bytes(receipt, newline=True),
                label="Q4 request receipt-last commit",
            )
            owned_descriptors = _collect_descriptors(
                support, label="Q4 committed support"
            )
            owned_descriptors[request_path] = request_descriptor
            owned_descriptors[receipt_path] = receipt_descriptor
            _verify_namespace(
                custody,
                output_relative=output_relative,
                owned_descriptors=owned_descriptors,
                support_directories=directories,
            )
        except BaseException:
            _rollback_owned(custody, owned)
            raise
    return load_publication_q4_authority_source_request_receipt_v1(
        project_root=project_root,
        receipt_path=receipt_path,
        expected_receipt_file_sha256=receipt_descriptor["sha256"],
        expected_receipt_sha256=receipt["receipt_sha256"],
    )


def run_cli(argv: Sequence[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the canonical production Q4 source request."
    )
    parser.add_argument("--project-root", required=True)
    for field in _ACCEPTED_PATH_FIELDS:
        parser.add_argument("--" + field.removesuffix("_path").replace("_", "-"), required=True)
    parser.add_argument("--dataset-manifest", required=True)
    parser.add_argument("--qualification-runtime-inputs-receipt", required=True)
    parser.add_argument("--runtime-candidate-registry-output", required=True)
    parser.add_argument("--runtime-materialization-result-output", required=True)
    parser.add_argument("--source-registry-output", required=True)
    parser.add_argument("--source-materialization-result-output", required=True)
    parser.add_argument("--python-executable-source", default=sys.executable)
    parser.add_argument("--output-dir", required=True)
    try:
        arguments = parser.parse_args(list(argv))
        accepted = {
            field: getattr(
                arguments, field.removesuffix("_path")
            )
            for field in _ACCEPTED_PATH_FIELDS
        }
        receipt = materialize_publication_q4_authority_source_request_v1(
            project_root=arguments.project_root,
            output_dir=arguments.output_dir,
            production_inputs=ProductionPublicationQ4SourceRequestInputsV1(
                accepted_source_paths=accepted,
                dataset_manifest_path=arguments.dataset_manifest,
                qualification_runtime_input_materialization_receipt_path=(
                    arguments.qualification_runtime_inputs_receipt
                ),
                planned_outputs={
                    "runtime_candidate_registry_path": (
                        arguments.runtime_candidate_registry_output
                    ),
                    "runtime_materialization_result_path": (
                        arguments.runtime_materialization_result_output
                    ),
                    "source_registry_path": arguments.source_registry_output,
                    "source_materialization_result_path": (
                        arguments.source_materialization_result_output
                    ),
                },
                python_executable_source=arguments.python_executable_source,
            ),
        )
        sys.stdout.buffer.write(_canonical_bytes(receipt, newline=True))
        sys.stdout.buffer.flush()
        return 0
    except SystemExit as error:
        return int(error.code)
    except Exception as error:
        sys.stderr.write(f"Q4 authority source-request producer rejected: {error}\n"[:4096])
        sys.stderr.flush()
        return EXIT_REJECTED


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_REJECTED",
    "RECEIPT_FILENAME",
    "RECEIPT_KIND",
    "REQUEST_FILENAME",
    "PreparedPublicationQ4SourceRequestV1",
    "ProductionPublicationQ4SourceRequestInputsV1",
    "PublicationQ4AuthoritySourceRequestV1Error",
    "load_publication_q4_authority_source_request_receipt_v1",
    "main",
    "materialize_publication_q4_authority_source_request_v1",
    "publication_q4_validation_identity_pins_v1",
    "run_cli",
    "validate_publication_q4_authority_source_request_receipt_v1",
]
