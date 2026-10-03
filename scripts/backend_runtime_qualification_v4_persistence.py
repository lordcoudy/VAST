#!/usr/bin/env python3
"""Physical persistence boundary for the pure Q4 backend graph.

This module reopens every referenced artifact by handle, validates the exact
560-cell graph, writes four immutable receipts, and commits one binding index
last.  It never derives an execution grant directly.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import stat
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterator, Mapping

from backend_publication_launcher_invocation_v3 import (
    validate_publication_launcher_invocation_v3,
)
from backend_publication_launcher_runtime_authority import (
    assess_backend_publication_launcher_runtime_authority,
    validate_backend_publication_launcher_runtime_authority,
)
from backend_publication_runtime_authority_v2 import (
    assess_backend_publication_runtime_authority_v2,
    validate_backend_publication_runtime_authority_v2,
)
from backend_runtime_qualification_v4_catalog import (
    validate_backend_runtime_qualification_v4_catalog,
)
from backend_runtime_qualification_v4_input_index import (
    validate_backend_runtime_qualification_v4_input_index,
)
from backend_runtime_validation_records_v2 import (
    QUALIFIED_REPLAY_RESULT,
    coordinate_for_cell_index_v2,
    validate_backend_runtime_validation_index_v2,
    validate_backend_runtime_validation_record_v2,
    validate_backend_runtime_validation_request_v2,
    validate_backend_runtime_validation_system_context_v2,
    validate_backend_runtime_validation_system_shard_v2,
)
from backend_runtime_validation_runner_authority import (
    assess_backend_runtime_validation_runner_authority,
    validate_backend_runtime_validation_runner_authority,
)
from backend_runtime_validator_authority_v4 import (
    assess_backend_runtime_validator_authority_v4,
    validate_backend_runtime_validator_authority_v4,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
SCHEMA_VERSION = 4
RECEIPT_KIND = "vast_backend_runtime_qualification_v4_receipt"
INDEX_KIND = "vast_backend_runtime_qualification_v4_binding_index"
STATUS = "accepted_persisted_physical_q4_qualification"
QUALIFICATION_SCOPE = "backend_native_runtime_q4_physical_qualification"
BINDING_INDEX_FILENAME = (
    "checkpoint_backend_runtime_qualification_v4_binding_index.json"
)
RECEIPT_FILENAME_TEMPLATE = (
    "checkpoint_{system}_backend_runtime_qualification_v4_receipt.json"
)
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_RESERVED = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_REF_FIELDS = frozenset({"descriptor", "content_identity_sha256"})
_TYPED_REF_FIELDS = frozenset({
    "artifact_schema_version", "artifact_kind", "descriptor",
    "content_identity_sha256",
})
_COORDINATE_FIELDS = (
    "system", "codec", "topology_kind", "policy", "deadline_ms",
    "cell_index",
)
_COVERAGE = {
    "system_count": 4,
    "runtime_authority_count": 112,
    "runtime_authorities_per_system": 28,
    "runtime_cell_count": 560,
    "cells_per_system": 140,
    "validation_request_count": 560,
    "validation_record_count": 560,
}
_PRODUCTION_PROTOCOL_PATHS = {
    "full_publication_entrypoint": "scripts/full_publication_entrypoint.py",
    "production_output_transaction": (
        "scripts/backend_publication_output_transaction_production_v3.py"
    ),
    "engineering_output_transaction": (
        "scripts/backend_publication_output_transaction_v3.py"
    ),
    "dispatch_abi": "scripts/backend_publication_dispatch_v3.py",
    "process_supervisor": (
        "scripts/backend_publication_process_supervisor_v3.py"
    ),
}


class BackendRuntimeQualificationV4PersistenceError(RuntimeError):
    """The physical Q4 graph cannot be promoted or reloaded safely."""


def _fail(message: str) -> None:
    raise BackendRuntimeQualificationV4PersistenceError(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            "Q4 persistence material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _sha(value: Any, label: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        _fail(f"{label} is not a SHA-256 identity")
    return value


def _relative(value: Any, label: str) -> str:
    if type(value) is not str or not value:
        _fail(f"{label} path is invalid")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        "\\" in value or ":" in value or "\x00" in value or "//" in value
        or value.endswith("/") or posix.is_absolute() or posix.anchor
        or windows.drive or windows.root or windows.anchor
        or posix.as_posix() != value or not posix.parts
        or any(
            part in {"", ".", ".."} or part.endswith((".", " "))
            or any(ord(character) < 32 for character in part)
            or part.split(".", 1)[0].upper() in _RESERVED
            for part in posix.parts
        )
    ):
        _fail(f"{label} path is unsafe")
    return value


def _descriptor(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        _fail(f"{label} descriptor fields drifted")
    size = value.get("size_bytes")
    if type(size) is not int or size < 0:
        _fail(f"{label} size is invalid")
    return {
        "path": _relative(value.get("path"), label),
        "size_bytes": size,
        "sha256": _sha(value.get("sha256"), f"{label} file"),
    }


def _reference(value: Any, label: str, *, typed: bool = False) -> dict[str, Any]:
    expected = _TYPED_REF_FIELDS if typed else _REF_FIELDS
    if type(value) is not dict or set(value) != expected:
        _fail(f"{label} reference fields drifted")
    result = {
        "descriptor": _descriptor(value.get("descriptor"), label),
        "content_identity_sha256": _sha(
            value.get("content_identity_sha256"), f"{label} content",
        ),
    }
    if typed:
        version = value.get("artifact_schema_version")
        kind = value.get("artifact_kind")
        if (
            type(version) is not int or version <= 0
            or type(kind) is not str or not kind
        ):
            _fail(f"{label} typed reference header drifted")
        result = {
            "artifact_schema_version": version,
            "artifact_kind": kind,
            **result,
        }
    return result


def _is_link(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


class _PhysicalRegistry:
    """Handle-bound reader with exact repeat sharing and alias rejection."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.descriptors: dict[str, dict[str, Any]] = {}
        self.identities: dict[tuple[int, int], str] = {}

    def read(self, value: Any, label: str) -> bytes:
        return b"".join(self.iter_read(value, label))

    def iter_read(
        self,
        value: Any,
        label: str,
        *,
        chunk_size: int = 1024 * 1024,
    ) -> Iterator[bytes]:
        """Cold-read one descriptor in bounded chunks under stable identity."""

        if type(chunk_size) is not int or chunk_size <= 0:
            _fail(f"{label} chunk size is invalid")
        descriptor = _descriptor(value, label)
        previous = self.descriptors.get(descriptor["path"])
        if previous is not None:
            if previous != descriptor:
                _fail(f"{label} repeated descriptor drifted")
            yield from self._iter_once(
                descriptor,
                label,
                repeated=True,
                chunk_size=chunk_size,
            )
            return
        yield from self._iter_once(
            descriptor,
            label,
            repeated=False,
            chunk_size=chunk_size,
        )
        self.descriptors[descriptor["path"]] = descriptor

    def _read_once(
        self, descriptor: Mapping[str, Any], label: str, *, repeated: bool,
    ) -> bytes:
        return b"".join(self._iter_once(
            descriptor,
            label,
            repeated=repeated,
            chunk_size=1024 * 1024,
        ))

    def _iter_once(
        self,
        descriptor: Mapping[str, Any],
        label: str,
        *,
        repeated: bool,
        chunk_size: int,
    ) -> Iterator[bytes]:
        relative = PurePosixPath(str(descriptor["path"]))
        cursor = self.root
        try:
            for part in relative.parts:
                cursor /= part
                if _is_link(cursor):
                    _fail(f"{label} path contains a link/reparse point")
            path = cursor.resolve(strict=True)
            path.relative_to(self.root)
            before = path.stat()
        except BackendRuntimeQualificationV4PersistenceError:
            raise
        except (OSError, ValueError) as error:
            raise BackendRuntimeQualificationV4PersistenceError(
                f"{label} is missing or outside project_root"
            ) from error
        if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1:
            _fail(f"{label} must be one non-hardlinked regular file")
        identity = (int(before.st_dev), int(before.st_ino))
        owner = self.identities.get(identity)
        if owner is not None and owner != descriptor["path"]:
            _fail(f"{label} aliases physical file {owner}")
        stable = (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
            before.st_ctime_ns, before.st_nlink,
        )
        descriptor_fd: int | None = None
        try:
            flags = os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
            flags |= int(getattr(os, "O_NOFOLLOW", 0))
            descriptor_fd = os.open(path, flags)
            opened = os.fstat(descriptor_fd)
            if (
                (opened.st_dev, opened.st_ino, opened.st_size,
                 opened.st_mtime_ns, opened.st_ctime_ns, opened.st_nlink)
                != stable
            ):
                _fail(f"{label} changed while opening")
            digest = hashlib.sha256()
            observed = 0
            while True:
                chunk = os.read(descriptor_fd, chunk_size)
                if not chunk:
                    break
                observed += len(chunk)
                if observed > descriptor["size_bytes"]:
                    _fail(f"{label} exceeded declared size")
                digest.update(chunk)
                yield chunk
            after = os.fstat(descriptor_fd)
            path_after = path.lstat()
        except BackendRuntimeQualificationV4PersistenceError:
            raise
        except OSError as error:
            raise BackendRuntimeQualificationV4PersistenceError(
                f"{label} physical read failed: {error}"
            ) from error
        finally:
            if descriptor_fd is not None:
                os.close(descriptor_fd)
        after_tuple = (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
            after.st_ctime_ns, after.st_nlink,
        )
        path_tuple = (
            path_after.st_dev, path_after.st_ino, path_after.st_size,
            path_after.st_mtime_ns, path_after.st_ctime_ns,
            path_after.st_nlink,
        )
        if (
            stable != after_tuple or stable != path_tuple
            or observed != descriptor["size_bytes"]
            or digest.hexdigest() != descriptor["sha256"]
        ):
            _fail(f"{label} physical size/SHA or stable identity drifted")
        if not repeated:
            self.identities[identity] = str(descriptor["path"])

    def json(
        self, reference: Mapping[str, Any], label: str, *, typed: bool,
        identity_field: str,
    ) -> dict[str, Any]:
        checked = _reference(reference, label, typed=typed)
        payload = self.read(checked["descriptor"], label)
        if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
            _fail(f"{label} must be canonical JSON with one trailing LF")
        try:
            value = json.loads(payload[:-1].decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise BackendRuntimeQualificationV4PersistenceError(
                f"{label} is not canonical JSON"
            ) from error
        if type(value) is not dict or payload != _canonical_bytes(value) + b"\n":
            _fail(f"{label} JSON bytes are noncanonical")
        if value.get(identity_field) != checked["content_identity_sha256"]:
            _fail(f"{label} content identity drifted")
        unsigned = {key: item for key, item in value.items()
                    if key != identity_field}
        if _canonical_sha(unsigned) != value[identity_field]:
            _fail(f"{label} self-hash drifted")
        return value

    def records(self) -> list[dict[str, Any]]:
        return [self.descriptors[path] for path in sorted(self.descriptors)]

    def revalidate(self) -> None:
        for position, descriptor in enumerate(self.records()):
            self._read_once(
                descriptor, f"registered Q4 artifact[{position}]",
                repeated=True,
            )


def _root(project_root: Path | str) -> Path:
    supplied = Path(project_root)
    if not supplied.is_absolute():
        _fail("project_root must be absolute")
    try:
        root = supplied.resolve(strict=True)
        if _is_link(root) or not root.is_dir():
            _fail("project_root must be a physical directory")
    except BackendRuntimeQualificationV4PersistenceError:
        raise
    except OSError as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            "project_root is unavailable"
        ) from error
    return root


def _path_in_root(root: Path, value: Path | str, label: str) -> Path:
    supplied = Path(value)
    candidate = supplied if supplied.is_absolute() else root / supplied
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            f"{label} is missing or outside project_root"
        ) from error
    return resolved


def _descriptor_for(root: Path, path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _load_catalog(
    root: Path, catalog_path: Path | str,
) -> tuple[dict[str, Any], dict[str, Any], _PhysicalRegistry]:
    path = _path_in_root(root, catalog_path, "Q4 catalog")
    descriptor = _descriptor_for(root, path)
    registry = _PhysicalRegistry(root)
    payload = registry.read(descriptor, "Q4 catalog")
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        _fail("Q4 catalog must have one trailing LF")
    try:
        catalog = json.loads(payload[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            "Q4 catalog is invalid JSON"
        ) from error
    if type(catalog) is not dict or payload != _canonical_bytes(catalog) + b"\n":
        _fail("Q4 catalog bytes are noncanonical")
    catalog_sha = catalog.get("catalog_sha256")
    _sha(catalog_sha, "Q4 catalog")
    if catalog_sha != _canonical_sha({
        key: item for key, item in catalog.items() if key != "catalog_sha256"
    }):
        _fail("Q4 catalog self-hash drifted")
    return catalog, descriptor, registry


def _policy_outputs(authority: Mapping[str, Any]) -> dict[str, Any]:
    policy = authority.get("policy_authority")
    if type(policy) is not dict:
        _fail("runtime authority policy output binding is missing")
    return {
        name: None if policy.get(name) is None
        else copy.deepcopy(policy[name].get("descriptor"))
        for name in ("capability", "calibration", "static_map")
    }


def _runtime_leaf_descriptors(
    value: Mapping[str, Any],
) -> list[dict[str, Any]]:
    dataset = value["dataset"]
    descriptors = [dataset["manifest"], *dataset["files"]]
    for section in ("source_runtime_artifacts", "backend_runtime_artifacts"):
        descriptors.extend(item["descriptor"] for item in value[section])
    analytics = value["analytics_authority"]
    descriptors.append(analytics["capability"]["descriptor"])
    descriptors.extend(item["descriptor"] for item in analytics["bindings"])
    policy = value["policy_authority"]
    descriptors.extend(
        item["descriptor"] for item in (
            policy["capability"], policy["calibration"], policy["static_map"],
        ) if item is not None
    )
    return [copy.deepcopy(item) for item in descriptors]


def _launcher_leaf_descriptors(
    value: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        value["runtime_closure_manifest"]["descriptor"],
        value["python_executable"]["descriptor"],
        value["publication_launcher"]["descriptor"],
        *(item["descriptor"] for item in value["runtime_leaves"]),
    ]


def _runner_leaf_descriptors(
    value: Mapping[str, Any],
) -> list[dict[str, Any]]:
    return [
        value["runtime_bundle_manifest"]["descriptor"],
        value["python_executable"]["descriptor"],
        value["runner"]["descriptor"],
        *(item["descriptor"] for item in value["runtime_leaves"]),
    ]


def _coordinate(value: Mapping[str, Any], position: int) -> dict[str, Any]:
    expected = coordinate_for_cell_index_v2(position)
    observed = {field: value.get(field) for field in _COORDINATE_FIELDS}
    if observed != expected:
        _fail(f"Q4 validation cell[{position}] coordinate drifted")
    return expected


def _load_roots(
    *, root: Path, catalog: Mapping[str, Any], registry: _PhysicalRegistry,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    q4_ref = _reference(catalog.get("q4_input_ref"), "Q4 input", typed=True)
    q4 = registry.json(
        q4_ref, "Q4 input", typed=True, identity_field="input_index_sha256",
    )
    systems = q4.get("systems")
    upstream = q4.get("upstream_identities")
    if type(systems) is not list or type(upstream) is not dict:
        _fail("Q4 input graph is incomplete")
    validate_backend_runtime_qualification_v4_input_index(
        q4,
        expected_semantic_sha256=q4["input_index_sha256"],
        expected_upstream_identities=upstream,
        expected_publication_launcher_invocation_v3_sha256=q4[
            "publication_launcher_invocation_v3_sha256"
        ],
        expected_runtime_binding_identity_v4_sha256_by_system={
            item["system"]: item["runtime_binding_identity_v4_sha256"]
            for item in systems
        },
        expected_runtime_authority_set_sha256_by_system={
            item["system"]: item["runtime_authority_set_sha256"]
            for item in systems
        },
        expected_launcher_runtime_authority_sha256_by_system={
            item["system"]: item["launcher_runtime_authority_sha256"]
            for item in systems
        },
    )
    if catalog.get("q4_input_sha256") != q4["input_index_sha256"]:
        _fail("Q4 catalog/input semantic cross-binding drifted")

    validator_ref = _reference(
        catalog.get("q4_validator_authority_ref"), "Q4 validator", typed=True,
    )
    validator = registry.json(
        validator_ref, "Q4 validator", typed=True,
        identity_field="authority_sha256",
    )
    validate_backend_runtime_validator_authority_v4(
        validator,
        expected_authority_sha256=validator_ref["content_identity_sha256"],
    )
    assessment = assess_backend_runtime_validator_authority_v4(
        validator, project_root=root,
        expected_authority_sha256=validator_ref["content_identity_sha256"],
    )
    if assessment.get("status") != "physically_valid":
        _fail("Q4 validator physical assessment blocked: " + ";".join(
            str(item) for item in assessment.get("blockers", [])
        ))
    registry.read(
        validator["implementation"]["descriptor"],
        "Q4 validator implementation",
    )

    runner_ref = _reference(
        catalog.get("runner_authority_ref"), "Q4 runner", typed=True,
    )
    runner = registry.json(
        runner_ref, "Q4 runner", typed=True,
        identity_field="runner_authority_sha256",
    )
    validate_backend_runtime_validation_runner_authority(
        runner,
        expected_runner_authority_sha256=runner_ref[
            "content_identity_sha256"
        ],
    )
    assessment = assess_backend_runtime_validation_runner_authority(
        runner, project_root=root,
        expected_runner_authority_sha256=runner_ref[
            "content_identity_sha256"
        ],
    )
    if assessment.get("status") != "physically_valid":
        _fail("Q4 runner physical assessment blocked: " + ";".join(
            str(item) for item in assessment.get("blockers", [])
        ))
    for position, descriptor in enumerate(_runner_leaf_descriptors(runner)):
        registry.read(descriptor, f"Q4 runner closure[{position}]")

    abi_ref = _reference(
        catalog.get("publication_launcher_invocation_v3_ref"),
        "publication launcher ABI v3", typed=True,
    )
    abi = registry.json(
        abi_ref, "publication launcher ABI v3", typed=True,
        identity_field="invocation_sha256",
    )
    abi = validate_publication_launcher_invocation_v3(abi)
    if (
        q4["publication_launcher_invocation_v3_ref"] != abi_ref
        or q4["publication_launcher_invocation_v3_sha256"]
        != abi["invocation_sha256"]
    ):
        _fail("Q4 input/launcher ABI v3 cross-binding drifted")
    return q4, validator, runner, abi


def _validate_catalog_graph(
    *, catalog: Mapping[str, Any], q4: Mapping[str, Any],
    validator: Mapping[str, Any], runner: Mapping[str, Any],
    abi: Mapping[str, Any], registry: _PhysicalRegistry,
) -> tuple[dict[str, Any], list[Any], list[Any], list[Any], list[Any]]:
    index_ref = _reference(
        catalog.get("records_v2_global_index_ref"),
        "Q4 validation-record index", typed=True,
    )
    index = registry.json(
        index_ref, "Q4 validation-record index", typed=True,
        identity_field="index_sha256",
    )
    context_refs = [item["context_ref"] for item in index["system_shards"]]
    shard_refs = [item["system_shard_ref"] for item in index["system_shards"]]
    request_refs = [
        item["validation_request_ref"] for item in catalog["validation_cells"]
    ]
    record_refs = [
        item["validation_record_ref"] for item in catalog["validation_cells"]
    ]
    try:
        validate_backend_runtime_qualification_v4_catalog(
            dict(catalog),
            q4_input_ref=catalog["q4_input_ref"],
            q4_validator_authority_ref=catalog["q4_validator_authority_ref"],
            runner_authority_ref=catalog["runner_authority_ref"],
            publication_launcher_invocation_v3_ref=catalog[
                "publication_launcher_invocation_v3_ref"
            ],
            records_v2_global_index=index,
            records_v2_global_index_ref=index_ref,
            system_context_refs=context_refs,
            system_shard_refs=shard_refs,
            validation_request_refs=request_refs,
            validation_record_refs=record_refs,
            expected_q4_input_sha256=catalog["q4_input_sha256"],
            expected_q4_validator_authority_sha256=catalog[
                "q4_validator_authority_sha256"
            ],
            expected_runner_authority_sha256=catalog[
                "runner_authority_sha256"
            ],
            expected_publication_launcher_invocation_v3_sha256=catalog[
                "publication_launcher_invocation_v3_sha256"
            ],
            expected_runner_invocation_identity_sha256=catalog[
                "runner_invocation_identity_sha256"
            ],
            expected_records_v2_global_index_sha256=catalog[
                "records_v2_global_index_sha256"
            ],
            expected_system_context_set_sha256=catalog[
                "system_context_set_sha256"
            ],
            expected_system_shard_set_sha256=catalog[
                "system_shard_set_sha256"
            ],
            expected_validation_request_global_set_sha256=catalog[
                "validation_request_global_set_sha256"
            ],
            expected_validation_record_global_set_sha256=catalog[
                "validation_record_global_set_sha256"
            ],
            expected_catalog_semantic_sha256=catalog["catalog_sha256"],
        )
    except Exception as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            f"Q4 catalog graph validation failed: {error}"
        ) from error
    q4_systems = {item["system"]: item for item in q4["systems"]}
    context_values: list[dict[str, Any]] = []
    shard_values: list[dict[str, Any]] = []
    for position, system in enumerate(SYSTEMS):
        source = q4_systems[system]
        context = registry.json(
            context_refs[position], f"Q4 context {system}", typed=True,
            identity_field="context_sha256",
        )
        shard = registry.json(
            shard_refs[position], f"Q4 shard {system}", typed=True,
            identity_field="system_shard_sha256",
        )
        if context.get("system") != system or shard.get("system") != system:
            _fail(f"Q4 {system} context/shard system drifted")
        try:
            validate_backend_runtime_validation_system_context_v2(
                context,
                expected_semantic_sha256=context["context_sha256"],
                expected_system=system,
                expected_q4_input_ref=catalog["q4_input_ref"],
                expected_q4_input_sha256=q4["input_index_sha256"],
                expected_q4_validator_authority_ref=catalog[
                    "q4_validator_authority_ref"
                ],
                expected_q4_validator_authority_sha256=validator[
                    "authority_sha256"
                ],
                expected_runner_authority_ref=catalog["runner_authority_ref"],
                expected_runner_authority_sha256=runner[
                    "runner_authority_sha256"
                ],
                expected_publication_launcher_invocation_v3_ref=catalog[
                    "publication_launcher_invocation_v3_ref"
                ],
                expected_publication_launcher_invocation_v3_sha256=abi[
                    "invocation_sha256"
                ],
                expected_runner_invocation_identity_sha256=catalog[
                    "runner_invocation_identity_sha256"
                ],
                expected_runtime_binding_identity_v4_sha256=source[
                    "runtime_binding_identity_v4_sha256"
                ],
                expected_runtime_authority_set_sha256=source[
                    "runtime_authority_set_sha256"
                ],
                expected_launcher_runtime_authority_ref=source[
                    "launcher_runtime_authority_ref"
                ],
                expected_launcher_runtime_authority_sha256=source[
                    "launcher_runtime_authority_sha256"
                ],
            )
            validate_backend_runtime_validation_system_shard_v2(
                shard,
                expected_semantic_sha256=shard["system_shard_sha256"],
                expected_system=system,
                expected_context_ref=context_refs[position],
                expected_validation_record_refs=record_refs[
                    position * 140:(position + 1) * 140
                ],
                expected_q4_input_ref=catalog["q4_input_ref"],
                expected_q4_input_sha256=q4["input_index_sha256"],
                expected_q4_validator_authority_ref=catalog[
                    "q4_validator_authority_ref"
                ],
                expected_q4_validator_authority_sha256=validator[
                    "authority_sha256"
                ],
                expected_runner_authority_ref=catalog["runner_authority_ref"],
                expected_runner_authority_sha256=runner[
                    "runner_authority_sha256"
                ],
                expected_publication_launcher_invocation_v3_ref=catalog[
                    "publication_launcher_invocation_v3_ref"
                ],
                expected_publication_launcher_invocation_v3_sha256=abi[
                    "invocation_sha256"
                ],
                expected_runner_invocation_identity_sha256=catalog[
                    "runner_invocation_identity_sha256"
                ],
                expected_runtime_binding_identity_v4_sha256=source[
                    "runtime_binding_identity_v4_sha256"
                ],
                expected_runtime_authority_set_sha256=source[
                    "runtime_authority_set_sha256"
                ],
                expected_launcher_runtime_authority_ref=source[
                    "launcher_runtime_authority_ref"
                ],
                expected_launcher_runtime_authority_sha256=source[
                    "launcher_runtime_authority_sha256"
                ],
            )
        except Exception as error:
            raise BackendRuntimeQualificationV4PersistenceError(
                f"Q4 {system} context/shard graph rejected: {error}"
            ) from error
        context_values.append(context)
        shard_values.append(shard)
    try:
        validate_backend_runtime_validation_index_v2(
            index,
            expected_semantic_sha256=index["index_sha256"],
            expected_system_shards=shard_values,
            expected_q4_input_ref=catalog["q4_input_ref"],
            expected_q4_input_sha256=q4["input_index_sha256"],
            expected_q4_validator_authority_ref=catalog[
                "q4_validator_authority_ref"
            ],
            expected_q4_validator_authority_sha256=validator[
                "authority_sha256"
            ],
            expected_runner_authority_ref=catalog["runner_authority_ref"],
            expected_runner_authority_sha256=runner[
                "runner_authority_sha256"
            ],
            expected_publication_launcher_invocation_v3_ref=catalog[
                "publication_launcher_invocation_v3_ref"
            ],
            expected_publication_launcher_invocation_v3_sha256=abi[
                "invocation_sha256"
            ],
            expected_runner_invocation_identity_sha256=catalog[
                "runner_invocation_identity_sha256"
            ],
            expected_runtime_binding_identity_v4_sha256_by_system={
                system: q4_systems[system][
                    "runtime_binding_identity_v4_sha256"
                ] for system in SYSTEMS
            },
            expected_runtime_authority_set_sha256_by_system={
                system: q4_systems[system]["runtime_authority_set_sha256"]
                for system in SYSTEMS
            },
            expected_launcher_runtime_authority_ref_by_system={
                system: q4_systems[system]["launcher_runtime_authority_ref"]
                for system in SYSTEMS
            },
            expected_launcher_runtime_authority_sha256_by_system={
                system: q4_systems[system][
                    "launcher_runtime_authority_sha256"
                ] for system in SYSTEMS
            },
        )
    except Exception as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            f"Q4 validation-record index graph rejected: {error}"
        ) from error
    return index, context_refs, shard_refs, request_refs, record_refs


def _validate_runtime_authorities(
    *, root: Path, q4: Mapping[str, Any], abi: Mapping[str, Any],
    registry: _PhysicalRegistry,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    upstream = q4["upstream_identities"]
    q4_systems = {item["system"]: item for item in q4["systems"]}
    normalized: dict[str, dict[str, Any]] = {}
    authority_values: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        source = q4_systems[system]
        authorities: list[dict[str, Any]] = []
        for position, item in enumerate(source["runtime_authorities"]):
            reference = _reference(
                item["authority_ref"],
                f"Q4 {system} runtime authority[{position}]", typed=True,
            )
            authority = registry.json(
                reference, f"Q4 {system} runtime authority[{position}]",
                typed=True, identity_field="authority_sha256",
            )
            coordinate = item["coordinate"]
            expected_outputs = _policy_outputs(authority)
            try:
                validate_backend_publication_runtime_authority_v2(
                    authority,
                    expected_system=coordinate["system"],
                    expected_codec=coordinate["codec"],
                    expected_topology_kind=coordinate["topology_kind"],
                    expected_policy=coordinate["policy"],
                    expected_upstream_identities=upstream,
                    expected_policy_outputs=expected_outputs,
                )
                assessment = assess_backend_publication_runtime_authority_v2(
                    authority, project_root=root,
                    expected_system=coordinate["system"],
                    expected_codec=coordinate["codec"],
                    expected_topology_kind=coordinate["topology_kind"],
                    expected_policy=coordinate["policy"],
                    expected_upstream_identities=upstream,
                    expected_policy_outputs=expected_outputs,
                )
            except Exception as error:
                raise BackendRuntimeQualificationV4PersistenceError(
                    f"Q4 {system} runtime authority[{position}] rejected: {error}"
                ) from error
            if assessment.get("status") != "physically_valid":
                _fail(
                    f"Q4 {system} runtime authority[{position}] physical "
                    "assessment blocked"
                )
            for leaf_position, descriptor in enumerate(
                _runtime_leaf_descriptors(authority)
            ):
                registry.read(
                    descriptor,
                    f"Q4 {system} authority[{position}] leaf[{leaf_position}]",
                )
            authority_values[reference["descriptor"]["path"]] = authority
            authorities.append({
                **copy.deepcopy(coordinate),
                "artifact": reference["descriptor"],
                "runtime_authority_sha256": authority["authority_sha256"],
            })

        launcher_ref = _reference(
            source["launcher_runtime_authority_ref"],
            f"Q4 {system} launcher authority", typed=True,
        )
        launcher = registry.json(
            launcher_ref, f"Q4 {system} launcher authority", typed=True,
            identity_field="launcher_runtime_authority_sha256",
        )
        manifest = launcher["runtime_closure_manifest_content"]
        expected = {
            "expected_authority_sha256": source[
                "launcher_runtime_authority_sha256"
            ],
            "expected_system": system,
            "expected_publication_launcher_invocation_v3_sha256": abi[
                "invocation_sha256"
            ],
            "expected_closure_manifest_sha256": manifest[
                "closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": launcher[
                "runtime_closure_set_sha256"
            ],
        }
        try:
            validate_backend_publication_launcher_runtime_authority(
                launcher, **expected,
            )
            assessment = assess_backend_publication_launcher_runtime_authority(
                launcher, project_root=root, **expected,
            )
        except Exception as error:
            raise BackendRuntimeQualificationV4PersistenceError(
                f"Q4 {system} launcher authority rejected: {error}"
            ) from error
        if assessment.get("status") != "physically_valid":
            _fail(f"Q4 {system} launcher authority physical assessment blocked")
        for position, descriptor in enumerate(
            _launcher_leaf_descriptors(launcher)
        ):
            registry.read(descriptor, f"Q4 {system} launcher closure[{position}]")
        normalized[system] = {
            "system": system,
            "runtime_binding_identity_sha256": source[
                "runtime_binding_identity_v4_sha256"
            ],
            "runtime_authority_set_sha256": source[
                "runtime_authority_set_sha256"
            ],
            "runtime_authorities": authorities,
            "launcher_runtime_authority": launcher_ref["descriptor"],
            "launcher_runtime_authority_sha256": source[
                "launcher_runtime_authority_sha256"
            ],
            "launcher": launcher["publication_launcher"]["descriptor"],
            "launcher_invocation": copy.deepcopy(abi),
            "launcher_kind": "dedicated_publication_runtime_v3",
            "publication_capable": True,
            "qualified_cells": [],
        }
    return normalized, authority_values


def _validate_cells(
    *, catalog: Mapping[str, Any], q4: Mapping[str, Any],
    validator: Mapping[str, Any], abi: Mapping[str, Any],
    runner: Mapping[str, Any], context_refs: list[Any],
    registry: _PhysicalRegistry, systems: dict[str, dict[str, Any]],
) -> None:
    q4_systems = {item["system"]: item for item in q4["systems"]}
    cells = catalog.get("validation_cells")
    if type(cells) is not list or len(cells) != 560:
        _fail("Q4 catalog requires exactly 560 validation cells")
    for position, node in enumerate(cells):
        coordinate = _coordinate(node["coordinate"], position)
        system = coordinate["system"]
        request = registry.json(
            node["validation_request_ref"],
            f"Q4 validation request[{position}]", typed=True,
            identity_field="request_sha256",
        )
        record = registry.json(
            node["validation_record_ref"],
            f"Q4 validation record[{position}]", typed=True,
            identity_field="validation_record_sha256",
        )
        if (
            {field: request.get(field) for field in _COORDINATE_FIELDS}
            != coordinate
            or {field: record.get(field) for field in _COORDINATE_FIELDS}
            != coordinate
            or record.get("request_ref") != node["validation_request_ref"]
            or record.get("request_sha256") != request["request_sha256"]
            or record.get("runtime_authority_ref")
            != request.get("runtime_authority_ref")
            or record.get("raw_evidence_ref") != request.get("raw_evidence_ref")
            or record.get("replay_result") != QUALIFIED_REPLAY_RESULT
            or record.get("authorization_eligible") is not False
            or record.get("execution_authorized") is not False
            or record.get("validation_records_authenticated") is not False
        ):
            _fail(f"Q4 validation record[{position}] trust graph drifted")
        source = q4_systems[system]["cells"][position % 140]
        authority_candidates = [
            item for item in q4_systems[system]["runtime_authorities"]
            if item["coordinate"] == {
                field: coordinate[field]
                for field in ("system", "codec", "topology_kind", "policy")
            }
        ]
        if len(authority_candidates) != 1:
            _fail(f"Q4 validation cell[{position}] authority is ambiguous")
        authority_source = authority_candidates[0]
        if (
            {field: source.get(field) for field in _COORDINATE_FIELDS}
            != coordinate
            or source.get("runtime_authority_sha256")
            != record.get("runtime_authority_sha256")
            or source.get("raw_evidence_ref") != record.get("raw_evidence_ref")
            or record.get("runtime_binding_identity_v4_sha256")
            != systems[system]["runtime_binding_identity_sha256"]
            or record.get("runtime_authority_set_sha256")
            != systems[system]["runtime_authority_set_sha256"]
            or record.get("launcher_runtime_authority_sha256")
            != systems[system]["launcher_runtime_authority_sha256"]
        ):
            _fail(f"Q4 validation record[{position}] input cross-binding drifted")
        system_position = SYSTEMS.index(system)
        try:
            validate_backend_runtime_validation_request_v2(
                request,
                expected_semantic_sha256=request["request_sha256"],
                expected_coordinate=coordinate,
                expected_context_ref=context_refs[system_position],
                expected_runtime_authority_ref=authority_source["authority_ref"],
                expected_runtime_authority_sha256=authority_source[
                    "authority_sha256"
                ],
                expected_raw_evidence_ref=source["raw_evidence_ref"],
                expected_q4_input_ref=catalog["q4_input_ref"],
                expected_q4_input_sha256=q4["input_index_sha256"],
                expected_q4_validator_authority_ref=catalog[
                    "q4_validator_authority_ref"
                ],
                expected_q4_validator_authority_sha256=validator[
                    "authority_sha256"
                ],
                expected_runner_authority_ref=catalog["runner_authority_ref"],
                expected_runner_authority_sha256=runner[
                    "runner_authority_sha256"
                ],
                expected_publication_launcher_invocation_v3_ref=catalog[
                    "publication_launcher_invocation_v3_ref"
                ],
                expected_publication_launcher_invocation_v3_sha256=abi[
                    "invocation_sha256"
                ],
                expected_runner_invocation_identity_sha256=catalog[
                    "runner_invocation_identity_sha256"
                ],
                expected_runtime_binding_identity_v4_sha256=systems[system][
                    "runtime_binding_identity_sha256"
                ],
                expected_runtime_authority_set_sha256=systems[system][
                    "runtime_authority_set_sha256"
                ],
                expected_launcher_runtime_authority_ref=q4_systems[system][
                    "launcher_runtime_authority_ref"
                ],
                expected_launcher_runtime_authority_sha256=systems[system][
                    "launcher_runtime_authority_sha256"
                ],
            )
            validate_backend_runtime_validation_record_v2(
                record,
                expected_semantic_sha256=record["validation_record_sha256"],
                expected_coordinate=coordinate,
                expected_request_ref=node["validation_request_ref"],
                expected_runtime_authority_ref=authority_source["authority_ref"],
                expected_runtime_authority_sha256=authority_source[
                    "authority_sha256"
                ],
                expected_raw_evidence_ref=source["raw_evidence_ref"],
                expected_q4_input_ref=catalog["q4_input_ref"],
                expected_q4_input_sha256=q4["input_index_sha256"],
                expected_q4_validator_authority_ref=catalog[
                    "q4_validator_authority_ref"
                ],
                expected_q4_validator_authority_sha256=validator[
                    "authority_sha256"
                ],
                expected_runner_authority_ref=catalog["runner_authority_ref"],
                expected_runner_authority_sha256=runner[
                    "runner_authority_sha256"
                ],
                expected_publication_launcher_invocation_v3_ref=catalog[
                    "publication_launcher_invocation_v3_ref"
                ],
                expected_publication_launcher_invocation_v3_sha256=abi[
                    "invocation_sha256"
                ],
                expected_runner_invocation_identity_sha256=catalog[
                    "runner_invocation_identity_sha256"
                ],
                expected_runtime_binding_identity_v4_sha256=systems[system][
                    "runtime_binding_identity_sha256"
                ],
                expected_runtime_authority_set_sha256=systems[system][
                    "runtime_authority_set_sha256"
                ],
                expected_launcher_runtime_authority_ref=q4_systems[system][
                    "launcher_runtime_authority_ref"
                ],
                expected_launcher_runtime_authority_sha256=systems[system][
                    "launcher_runtime_authority_sha256"
                ],
            )
        except Exception as error:
            raise BackendRuntimeQualificationV4PersistenceError(
                f"Q4 validation request/record[{position}] rejected: {error}"
            ) from error
        raw_ref = _reference(
            record["raw_evidence_ref"], f"Q4 raw evidence[{position}]",
        )
        registry.read(raw_ref["descriptor"], f"Q4 raw evidence[{position}]")
        cell_identity = _canonical_sha({
            **coordinate,
            "runtime_authority_sha256": record["runtime_authority_sha256"],
            "request_sha256": request["request_sha256"],
            "validation_record_sha256": record["validation_record_sha256"],
        })
        systems[system]["qualified_cells"].append({
            **{field: coordinate[field] for field in _COORDINATE_FIELDS[:-1]},
            "cell_identity_sha256": cell_identity,
            "runtime_authority_sha256": record["runtime_authority_sha256"],
            "raw_evidence": raw_ref["descriptor"],
            "launcher_invocation_sha256": abi["invocation_sha256"],
            "validator_identity_sha256": validator["authority_sha256"],
            "validation_record_sha256": record["validation_record_sha256"],
        })
    for system in SYSTEMS:
        value = systems[system]
        if (
            len(value["runtime_authorities"]) != 28
            or len(value["qualified_cells"]) != 140
        ):
            _fail(f"Q4 {system} authority/cell coverage drifted")
        value["qualified_cells_sha256"] = _canonical_sha(
            value["qualified_cells"]
        )
        value["raw_evidence_set_sha256"] = _canonical_sha([
            item["raw_evidence"] for item in value["qualified_cells"]
        ])


def _read_and_validate_graph(
    *, root: Path, catalog: Mapping[str, Any], registry: _PhysicalRegistry,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], dict[str, Any]]:
    q4, validator, runner, abi = _load_roots(
        root=root, catalog=catalog, registry=registry,
    )
    index, context_refs, _, _, _ = _validate_catalog_graph(
        catalog=catalog, q4=q4, validator=validator, runner=runner,
        abi=abi, registry=registry,
    )
    systems, authorities = _validate_runtime_authorities(
        root=root, q4=q4, abi=abi, registry=registry,
    )
    _validate_cells(
        catalog=catalog, q4=q4, validator=validator, runner=runner, abi=abi,
        context_refs=context_refs,
        registry=registry, systems=systems,
    )
    protocol_files: dict[str, dict[str, Any]] = {}
    for role, relative_path in _PRODUCTION_PROTOCOL_PATHS.items():
        descriptor = _descriptor_for(root, root / relative_path)
        registry.read(descriptor, f"production-v3 receipt protocol {role}")
        protocol_files[role] = descriptor
    trust = {
        "q4_input_sha256": q4["input_index_sha256"],
        "q4_validator_authority_sha256": validator["authority_sha256"],
        "runner_authority_sha256": runner["runner_authority_sha256"],
        "runner_invocation_identity_sha256": catalog[
            "runner_invocation_identity_sha256"
        ],
        "publication_launcher_invocation_v3_sha256": abi[
            "invocation_sha256"
        ],
        "records_v2_global_index_sha256": index["index_sha256"],
        "catalog_sha256": catalog["catalog_sha256"],
    }
    return trust, systems, {
        "upstream_identities": copy.deepcopy(q4["upstream_identities"]),
        "runtime_authorities": authorities,
        "production_receipt_protocol_files": protocol_files,
    }


def _atomic_immutable(
    root: Path,
    path: Path,
    value: Mapping[str, Any],
    *,
    after_publish_step: Callable[[str], None] | None = None,
) -> tuple[
    dict[str, Any], tuple[int, int], str
]:
    payload = _canonical_bytes(dict(value)) + b"\n"
    try:
        with PhysicalRootCustodyV1.open(
            root, label="backend Q4 persistence project_root"
        ) as custody:
            return custody.commit_or_adopt_exact_identity(
                path,
                payload,
                label=f"immutable Q4 output {path.name}",
                mode=0o444,
                create_parents=True,
                after_publish_step=after_publish_step,
            )
    except PublicationPhysicalIoV1Error as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            f"immutable Q4 output collision/commit failed: {path.name}: {error}"
        ) from error


def _output_directory(root: Path, output_dir: Path | str) -> Path:
    supplied = Path(output_dir)
    candidate = Path(os.path.abspath(
        supplied if supplied.is_absolute() else root / supplied
    ))
    try:
        candidate.relative_to(root)
        if candidate != root:
            with PhysicalRootCustodyV1.open(
                root, label="backend Q4 output project_root",
            ) as custody:
                custody.ensure_directory(
                    candidate, label="backend Q4 output directory",
                )
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError, PublicationPhysicalIoV1Error) as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            "Q4 output directory is outside project_root"
        ) from error
    cursor = root
    for part in resolved.relative_to(root).parts:
        cursor /= part
        if _is_link(cursor):
            _fail("Q4 output directory contains a link/reparse point")
    return resolved


def promote_backend_runtime_qualification_v4(
    *, project_root: Path | str, catalog_path: Path | str,
    output_dir: Path | str,
    after_physical_commit_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Physically validate Q4 and commit four receipts plus one index."""
    root = _root(project_root)
    catalog, catalog_descriptor, registry = _load_catalog(root, catalog_path)
    trust, systems, graph = _read_and_validate_graph(
        root=root, catalog=catalog, registry=registry,
    )
    registry.revalidate()
    registered_files = registry.records()
    registered_files_sha = _canonical_sha(registered_files)
    output = _output_directory(root, output_dir)
    receipt_values: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        material: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "artifact_kind": RECEIPT_KIND,
            "status": STATUS,
            "qualification_scope": QUALIFICATION_SCOPE,
            "system": system,
            "catalog": catalog_descriptor,
            "trust_identities": trust,
            "upstream_identities": graph["upstream_identities"],
            "system_binding": systems[system],
            "coverage": {
                **_COVERAGE,
                "system_count": 1,
                "runtime_authority_count": 28,
                "runtime_cell_count": 140,
                "validation_request_count": 140,
                "validation_record_count": 140,
            },
            "registered_files": registered_files,
            "registered_files_sha256": registered_files_sha,
            "post_run_per_arm_evidence_required": True,
            "configuration_evidence_accepted_mutated": False,
        }
        material["receipt_sha256"] = _canonical_sha(material)
        receipt_values[system] = material
        _atomic_immutable(
            root,
            output / RECEIPT_FILENAME_TEMPLATE.format(system=system),
            material,
            after_publish_step=(
                None
                if after_physical_commit_step is None
                else lambda step, system=system: after_physical_commit_step(
                    f"receipt:{system}:{step}"
                )
            ),
        )
    receipt_descriptors = {
        system: _descriptor_for(
            root, output / RECEIPT_FILENAME_TEMPLATE.format(system=system),
        ) for system in SYSTEMS
    }
    index: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": INDEX_KIND,
        "status": STATUS,
        "qualification_scope": QUALIFICATION_SCOPE,
        "systems": list(SYSTEMS),
        "catalog": catalog_descriptor,
        "trust_identities": trust,
        "upstream_identities": graph["upstream_identities"],
        "receipts": receipt_descriptors,
        "registered_files": registered_files,
        "registered_files_sha256": registered_files_sha,
        "coverage": _COVERAGE,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    index["binding_sha256"] = _canonical_sha(index)
    index_path = output / BINDING_INDEX_FILENAME
    _atomic_immutable(
        root,
        index_path,
        index,
        after_publish_step=(
            None
            if after_physical_commit_step is None
            else lambda step: after_physical_commit_step(f"index:{step}")
        ),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": "vast_backend_runtime_qualification_v4_promotion",
        "status": "promoted_physical_q4_qualification",
        "binding_index_descriptor": _descriptor_for(root, index_path),
        "receipt_descriptors": receipt_descriptors,
        "binding_index": copy.deepcopy(index),
    }


def _read_plain_json(
    registry: _PhysicalRegistry, descriptor: Mapping[str, Any], label: str,
    *, identity_field: str,
) -> dict[str, Any]:
    payload = registry.read(descriptor, label)
    if not payload.endswith(b"\n") or payload.endswith(b"\n\n"):
        _fail(f"{label} trailing-LF contract drifted")
    try:
        value = json.loads(payload[:-1].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            f"{label} is invalid JSON"
        ) from error
    if type(value) is not dict or payload != _canonical_bytes(value) + b"\n":
        _fail(f"{label} JSON bytes are noncanonical")
    if value.get(identity_field) != _canonical_sha({
        key: item for key, item in value.items() if key != identity_field
    }):
        _fail(f"{label} self-hash drifted")
    return value


def _validate_persisted_index(index: Any) -> list[dict[str, Any]]:
    expected_fields = {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "systems", "catalog", "trust_identities", "upstream_identities",
        "receipts", "registered_files", "registered_files_sha256",
        "coverage", "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated", "binding_sha256",
    }
    if (
        type(index) is not dict or set(index) != expected_fields
        or index.get("schema_version") != SCHEMA_VERSION
        or index.get("artifact_kind") != INDEX_KIND
        or index.get("status") != STATUS
        or index.get("qualification_scope") != QUALIFICATION_SCOPE
        or index.get("systems") != list(SYSTEMS)
        or index.get("coverage") != _COVERAGE
        or index.get("post_run_per_arm_evidence_required") is not True
        or index.get("configuration_evidence_accepted_mutated") is not False
    ):
        _fail("Q4 binding index fields/status/coverage drifted")
    registered = index.get("registered_files")
    if type(registered) is not list:
        _fail("Q4 registered physical file set is missing")
    checked = [
        _descriptor(item, f"Q4 registered file[{position}]")
        for position, item in enumerate(registered)
    ]
    if (
        checked != sorted(checked, key=lambda item: item["path"])
        or len({item["path"] for item in checked}) != len(checked)
        or index.get("registered_files_sha256") != _canonical_sha(checked)
    ):
        _fail("Q4 registered physical file set identity drifted")
    return checked


def _validate_persisted_receipt(
    value: Any, *, system: str, index: Mapping[str, Any],
    registered_files: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_fields = {
        "schema_version", "artifact_kind", "status", "qualification_scope",
        "system", "catalog", "trust_identities", "upstream_identities",
        "system_binding", "coverage", "registered_files",
        "registered_files_sha256", "post_run_per_arm_evidence_required",
        "configuration_evidence_accepted_mutated", "receipt_sha256",
    }
    expected_coverage = {
        **_COVERAGE,
        "system_count": 1,
        "runtime_authority_count": 28,
        "runtime_cell_count": 140,
        "validation_request_count": 140,
        "validation_record_count": 140,
    }
    if (
        type(value) is not dict or set(value) != expected_fields
        or value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != RECEIPT_KIND
        or value.get("status") != STATUS
        or value.get("qualification_scope") != QUALIFICATION_SCOPE
        or value.get("system") != system
        or value.get("catalog") != index.get("catalog")
        or value.get("trust_identities") != index.get("trust_identities")
        or value.get("upstream_identities") != index.get("upstream_identities")
        or value.get("coverage") != expected_coverage
        or value.get("registered_files") != registered_files
        or value.get("registered_files_sha256")
        != index.get("registered_files_sha256")
        or value.get("post_run_per_arm_evidence_required") is not True
        or value.get("configuration_evidence_accepted_mutated") is not False
    ):
        _fail(f"Q4 persisted receipt {system} fields/cross-binding drifted")
    return copy.deepcopy(value["system_binding"])


def _validate_loaded_system(
    value: Any, *, system: str, registry: _PhysicalRegistry,
    trust: Mapping[str, Any],
) -> dict[str, Any]:
    expected_fields = {
        "system", "runtime_binding_identity_sha256",
        "runtime_authority_set_sha256", "runtime_authorities",
        "launcher_runtime_authority", "launcher_runtime_authority_sha256",
        "launcher", "launcher_invocation", "launcher_kind",
        "publication_capable", "qualified_cells", "qualified_cells_sha256",
        "raw_evidence_set_sha256",
    }
    if (
        type(value) is not dict or set(value) != expected_fields
        or value.get("system") != system
        or value.get("launcher_kind") != "dedicated_publication_runtime_v3"
        or value.get("publication_capable") is not True
    ):
        _fail(f"Q4 persisted system binding {system} drifted")
    invocation = validate_publication_launcher_invocation_v3(
        value.get("launcher_invocation")
    )
    if (
        invocation["invocation_sha256"]
        != trust.get("publication_launcher_invocation_v3_sha256")
    ):
        _fail(f"Q4 persisted system {system} launcher ABI drifted")
    launcher_authority_descriptor = _descriptor(
        value.get("launcher_runtime_authority"),
        f"Q4 persisted {system} launcher authority",
    )
    launcher_authority = _read_plain_json(
        registry, launcher_authority_descriptor,
        f"Q4 persisted {system} launcher authority",
        identity_field="launcher_runtime_authority_sha256",
    )
    if (
        launcher_authority.get("system") != system
        or launcher_authority.get("launcher_runtime_authority_sha256")
        != value.get("launcher_runtime_authority_sha256")
        or launcher_authority.get("publication_launcher", {}).get("descriptor")
        != value.get("launcher")
        or launcher_authority.get(
            "publication_launcher_invocation_v3_sha256"
        ) != invocation["invocation_sha256"]
    ):
        _fail(f"Q4 persisted {system} launcher authority binding drifted")
    try:
        validate_backend_publication_launcher_runtime_authority(
            launcher_authority,
            expected_authority_sha256=value["launcher_runtime_authority_sha256"],
            expected_system=system,
            expected_publication_launcher_invocation_v3_sha256=invocation[
                "invocation_sha256"
            ],
            expected_closure_manifest_sha256=launcher_authority[
                "runtime_closure_manifest_content"
            ]["closure_manifest_sha256"],
            expected_runtime_closure_set_sha256=launcher_authority[
                "runtime_closure_set_sha256"
            ],
        )
    except Exception as error:
        raise BackendRuntimeQualificationV4PersistenceError(
            f"Q4 persisted {system} launcher authority rejected: {error}"
        ) from error

    raw_authorities = value.get("runtime_authorities")
    if type(raw_authorities) is not list or len(raw_authorities) != 28:
        _fail(f"Q4 persisted {system} runtime authority coverage drifted")
    authorities: list[dict[str, Any]] = []
    observed_coordinates: set[tuple[str, str, str, str]] = set()
    for position, raw in enumerate(raw_authorities):
        fields = {
            "system", "codec", "topology_kind", "policy", "artifact",
            "runtime_authority_sha256",
        }
        if type(raw) is not dict or set(raw) != fields:
            _fail(f"Q4 persisted {system} authority[{position}] fields drifted")
        coordinate = (
            raw.get("system"), raw.get("codec"), raw.get("topology_kind"),
            raw.get("policy"),
        )
        if coordinate[0] != system or coordinate in observed_coordinates:
            _fail(f"Q4 persisted {system} runtime authority coordinate drifted")
        authority_descriptor = _descriptor(
            raw.get("artifact"),
            f"Q4 persisted {system} runtime authority[{position}]",
        )
        authority = _read_plain_json(
            registry, authority_descriptor,
            f"Q4 persisted {system} runtime authority[{position}]",
            identity_field="authority_sha256",
        )
        if authority.get("authority_sha256") != raw.get(
            "runtime_authority_sha256"
        ):
            _fail(f"Q4 persisted {system} runtime authority identity drifted")
        observed_coordinates.add(coordinate)
        authorities.append({
            **{key: raw[key] for key in (
                "system", "codec", "topology_kind", "policy",
                "runtime_authority_sha256",
            )},
            # The production selector deliberately consumes validated semantic
            # authority content, never an in-memory callback result.
            "artifact": authority,
            "artifact_descriptor": authority_descriptor,
        })

    cells = value.get("qualified_cells")
    if type(cells) is not list or len(cells) != 140:
        _fail(f"Q4 persisted {system} qualified-cell coverage drifted")
    expected_cell_fields = {
        "system", "codec", "topology_kind", "policy", "deadline_ms",
        "cell_identity_sha256", "runtime_authority_sha256", "raw_evidence",
        "launcher_invocation_sha256", "validator_identity_sha256",
        "validation_record_sha256",
    }
    normalized_cells: list[dict[str, Any]] = []
    seen_cells: set[tuple[Any, ...]] = set()
    for position, raw in enumerate(cells):
        if type(raw) is not dict or set(raw) != expected_cell_fields:
            _fail(f"Q4 persisted {system} cell[{position}] fields drifted")
        coordinate = tuple(raw.get(field) for field in _COORDINATE_FIELDS[:-1])
        if raw.get("system") != system or coordinate in seen_cells:
            _fail(f"Q4 persisted {system} cell coordinate drifted")
        if raw.get("launcher_invocation_sha256") != invocation["invocation_sha256"]:
            _fail(f"Q4 persisted {system} cell launcher ABI drifted")
        evidence = _descriptor(
            raw.get("raw_evidence"),
            f"Q4 persisted {system} cell[{position}] raw evidence",
        )
        registry.read(evidence, f"Q4 persisted {system} cell[{position}] raw evidence")
        normalized = copy.deepcopy(raw)
        normalized["raw_evidence"] = evidence
        normalized_cells.append(normalized)
        seen_cells.add(coordinate)
    if (
        value.get("qualified_cells_sha256") != _canonical_sha(normalized_cells)
        or value.get("raw_evidence_set_sha256") != _canonical_sha([
            item["raw_evidence"] for item in normalized_cells
        ])
    ):
        _fail(f"Q4 persisted {system} cell set hash drifted")
    return {
        **{
            key: copy.deepcopy(value[key])
            for key in expected_fields
            if key not in {
                "runtime_authorities", "launcher_runtime_authority",
                "qualified_cells",
            }
        },
        "runtime_authorities": authorities,
        "launcher_runtime_authority": launcher_authority,
        "launcher_runtime_authority_descriptor": launcher_authority_descriptor,
        "qualified_cells": normalized_cells,
    }


def _production_receipt_protocol_binding(
    *, systems: Mapping[str, Mapping[str, Any]],
    physical_files: list[dict[str, Any]],
) -> dict[str, Any]:
    by_path = {item["path"]: item for item in physical_files}
    protocol_files: dict[str, dict[str, Any]] = {}
    for role, path in _PRODUCTION_PROTOCOL_PATHS.items():
        descriptor = by_path.get(path)
        if descriptor is None:
            _fail(f"production-v3 receipt protocol file {role} is unregistered")
        protocol_files[role] = copy.deepcopy(descriptor)
    material: dict[str, Any] = {
        "schema_version": 4,
        "artifact_kind": (
            "vast_backend_publication_production_output_receipt_protocol_binding_v4"
        ),
        "execution_scope": "full_publication_measurement_v3",
        "receipt_kind": "vast_backend_publication_production_output_receipt_v4",
        "receipt_authority_kind": (
            "vast_backend_publication_production_output_receipt_authority_v4"
        ),
        "atomicity": "durable_journal_then_launcher_result_then_output_receipt_last_v4",
        "parent_owned_transaction_required": True,
        "semantic_evidence_validation_required": True,
        "protocol_files": protocol_files,
        "systems": {
            system: {
                "launcher": copy.deepcopy(systems[system]["launcher"]),
                "launcher_runtime_authority_descriptor": copy.deepcopy(
                    systems[system]["launcher_runtime_authority_descriptor"]
                ),
                "launcher_runtime_authority_sha256": systems[system][
                    "launcher_runtime_authority_sha256"
                ],
                "launcher_invocation_sha256": systems[system][
                    "launcher_invocation"
                ]["invocation_sha256"],
            }
            for system in SYSTEMS
        },
    }
    material["protocol_binding_sha256"] = _canonical_sha(material)
    return material


def load_backend_runtime_qualification_v4_binding(
    *, project_root: Path | str, binding_index_path: Path | str,
) -> dict[str, Any]:
    """Reload one committed Q4 set through the physical trust boundary.

    The returned schema-v3 identity binding is authorization-eligible only
    because every source, receipt, authority, launcher and evidence descriptor
    has been reopened and rehashed.  Callers still have to register this full
    physical set in the full-publication identity manifest before deriving a
    grant.
    """
    root = _root(project_root)
    path = _path_in_root(root, binding_index_path, "Q4 binding index")
    if path.name != BINDING_INDEX_FILENAME:
        _fail("Q4 binding index filename drifted")
    index_descriptor = _descriptor_for(root, path)
    registry = _PhysicalRegistry(root)
    index = _read_plain_json(
        registry, index_descriptor, "Q4 binding index",
        identity_field="binding_sha256",
    )
    registered = _validate_persisted_index(index)
    for position, descriptor in enumerate(registered):
        registry.read(descriptor, f"Q4 registered input[{position}]")

    # Re-run the complete semantic graph.  Descriptor/self-hash checks alone
    # would permit a mutually consistent rewrite with every hash recomputed;
    # a grant is eligible only after the original validators accept the
    # physically reopened graph again.
    catalog_reference = _descriptor(index.get("catalog"), "Q4 persisted catalog")
    catalog, catalog_descriptor, graph_registry = _load_catalog(
        root, catalog_reference["path"],
    )
    recomputed_trust, recomputed_systems, recomputed_graph = (
        _read_and_validate_graph(
            root=root, catalog=catalog, registry=graph_registry,
        )
    )
    graph_registry.revalidate()
    if (
        catalog_descriptor != catalog_reference
        or graph_registry.records() != registered
    ):
        _fail("Q4 persisted physical graph closure drifted")

    receipt_map = index.get("receipts")
    if type(receipt_map) is not dict or set(receipt_map) != set(SYSTEMS):
        _fail("Q4 persisted receipt descriptor set drifted")
    receipt_descriptors: dict[str, dict[str, Any]] = {}
    source_systems: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        descriptor = _descriptor(
            receipt_map[system], f"Q4 persisted receipt {system}",
        )
        receipt_path = _path_in_root(
            root, descriptor["path"], f"Q4 persisted receipt {system}",
        )
        if receipt_path.name != RECEIPT_FILENAME_TEMPLATE.format(system=system):
            _fail(f"Q4 persisted receipt {system} filename drifted")
        receipt = _read_plain_json(
            registry, descriptor, f"Q4 persisted receipt {system}",
            identity_field="receipt_sha256",
        )
        source_systems[system] = _validate_persisted_receipt(
            receipt, system=system, index=index, registered_files=registered,
        )
        receipt_descriptors[system] = descriptor

    trust = index.get("trust_identities")
    expected_trust = {
        "q4_input_sha256", "q4_validator_authority_sha256",
        "runner_authority_sha256", "runner_invocation_identity_sha256",
        "publication_launcher_invocation_v3_sha256",
        "records_v2_global_index_sha256", "catalog_sha256",
    }
    upstream = index.get("upstream_identities")
    expected_upstream = {
        "dataset_manifest_sha256", "policy_contract_sha256",
        "policy_qualification_receipt_sha256",
        "resource_contract_identity_sha256",
        "resource_qualification_receipt_sha256",
        "analytics_execution_config_identity_sha256",
        "model_parity_manifest_identity_sha256",
        "model_parity_acceptance_binding_sha256",
    }
    if (
        type(trust) is not dict or set(trust) != expected_trust
        or not all(_SHA_RE.fullmatch(str(item)) for item in trust.values())
        or type(upstream) is not dict or set(upstream) != expected_upstream
        or not all(_SHA_RE.fullmatch(str(item)) for item in upstream.values())
        or trust != recomputed_trust
        or upstream != recomputed_graph["upstream_identities"]
    ):
        _fail("Q4 persisted trust/upstream identity set drifted")

    for system in SYSTEMS:
        if source_systems[system] != recomputed_systems[system]:
            _fail(f"Q4 persisted {system} receipt/semantic graph drifted")

    normalized_systems = {
        system: _validate_loaded_system(
            source_systems[system], system=system, registry=registry,
            trust=trust,
        )
        for system in SYSTEMS
    }
    registry.revalidate()
    physical_files = registry.records()
    persisted_output_paths = {
        index_descriptor["path"],
        *(descriptor["path"] for descriptor in receipt_descriptors.values()),
    }
    runtime_authority_leaves = [
        descriptor for descriptor in physical_files
        if descriptor["path"] not in persisted_output_paths
    ]
    receipt_protocol = _production_receipt_protocol_binding(
        systems=normalized_systems, physical_files=physical_files,
    )
    normalized: dict[str, Any] = {
        "schema_version": 3,
        "artifact_kind": (
            "vast_full_publication_backend_runtime_qualification_binding_v3"
        ),
        "source_status": STATUS,
        "source_qualification_scope": QUALIFICATION_SCOPE,
        "authorization_eligible": True,
        "validation_trust_status": "authenticated_persisted_physical_q4_v4",
        "semantic_crossbinding_complete": True,
        "authorization_blockers": [],
        "observed_validator_identity_sha256": trust[
            "q4_validator_authority_sha256"
        ],
        "qualification_index_sha256": trust[
            "records_v2_global_index_sha256"
        ],
        "catalog_sha256": trust["catalog_sha256"],
        "binding_index": index_descriptor,
        "receipts": receipt_descriptors,
        "upstream_identities": copy.deepcopy(upstream),
        "systems": normalized_systems,
        "coverage": copy.deepcopy(_COVERAGE),
        "runtime_authority_leaves": runtime_authority_leaves,
        "runtime_authority_leaf_set_sha256": _canonical_sha(
            runtime_authority_leaves
        ),
        "physical_files": physical_files,
        "physical_files_sha256": _canonical_sha(physical_files),
        "production_output_receipt_protocol": receipt_protocol,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    normalized["identity_binding_sha256"] = _canonical_sha(normalized)
    return normalized


def _main() -> int:
    parser = argparse.ArgumentParser(
        description="Physically validate and persist backend Q4 qualification",
    )
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        result = promote_backend_runtime_qualification_v4(
            project_root=arguments.project_root,
            catalog_path=arguments.catalog,
            output_dir=arguments.output_dir,
        )
    except BackendRuntimeQualificationV4PersistenceError as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = [
    "BINDING_INDEX_FILENAME",
    "BackendRuntimeQualificationV4PersistenceError",
    "INDEX_KIND",
    "QUALIFICATION_SCOPE",
    "RECEIPT_FILENAME_TEMPLATE",
    "RECEIPT_KIND",
    "SCHEMA_VERSION",
    "STATUS",
    "SYSTEMS",
    "load_backend_runtime_qualification_v4_binding",
    "promote_backend_runtime_qualification_v4",
]


if __name__ == "__main__":
    raise SystemExit(_main())
