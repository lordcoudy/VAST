#!/usr/bin/env python3
"""Immutable launcher result receipts for full-publication backend arms."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend_publication_dispatch import (
    INPUT_PROTOCOL_IDENTITY_SHA256,
    OUTPUT_PROTOCOL_IDENTITY_SHA256,
    validate_launcher_invocation,
)
from publication_acceptance_evidence import pre_finalization_acceptance_evidence_files


ARM_CONTRACT_FILENAME = "backend_publication_arm_contract.json"
LAUNCHER_RESULT_FILENAME = "backend_publication_launcher_result.json"
OUTPUT_RECEIPT_FILENAME = "backend_publication_output_receipt.json"
ARM_CONTRACT_KIND = "vast_backend_publication_arm_dispatch_contract"
LAUNCHER_RESULT_KIND = "vast_backend_publication_launcher_result"
OUTPUT_RECEIPT_KIND = "vast_backend_publication_output_receipt"
ARM_CONTRACT_AUTHORITY_KIND = "vast_backend_publication_arm_contract_authority"
OUTPUT_RECEIPT_AUTHORITY_KIND = "vast_backend_publication_output_receipt_authority"
OUTPUT_PROTOCOL_KIND = "vast_backend_publication_launcher_output_protocol"
EXECUTION_BINDING_KIND = "vast_full_publication_arm_execution_binding"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DESCRIPTOR_FIELDS = frozenset({"path", "size_bytes", "sha256"})
_EXECUTION_FIELDS = frozenset({
    "schema_version", "artifact_kind", "run_identity_sha256", "sequence",
    "pair_id", "attempt", "arm_id",
})
_AUTHORITY_FIELDS = frozenset({
    "schema_version", "artifact_kind", "path", "size_bytes", "sha256",
    "content_sha256", "full_publication_execution_binding",
    "run_identity_sha256", "run_id", "output_dir",
    "dispatch_resolution_sha256", "cell_identity_sha256", "launcher_sha256",
    "launcher_invocation_sha256", "backend_runtime_grant_sha256",
    "resource_capability_grant_sha256", "model_parity_grant_sha256",
    "model_parity_acceptance_binding_sha256",
    "identity_artifact_binding_sha256",
})
_RECEIPT_AUTHORITY_FIELDS = frozenset(
    set(_AUTHORITY_FIELDS) | {"arm_contract", "launcher_result", "evidence_files"}
)


class BackendPublicationOutputReceiptError(RuntimeError):
    """Launcher output is absent, mutable, or not bound to its dispatched arm."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BackendPublicationOutputReceiptError(
            "backend publication artifact is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: Any) -> bool:
    return type(value) is str and _SHA_RE.fullmatch(value) is not None


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _checked_output_root(output_dir: Path) -> Path:
    try:
        root = Path(output_dir).resolve(strict=True)
    except OSError as error:
        raise BackendPublicationOutputReceiptError(
            "backend publication output directory is missing"
        ) from error
    if not root.is_dir() or _is_link_or_reparse(root):
        raise BackendPublicationOutputReceiptError(
            "backend publication output directory is unsafe"
        )
    return root


def _checked_relative_name(value: Any, *, label: str) -> str:
    if type(value) is not str or not value:
        raise BackendPublicationOutputReceiptError(f"{label} path is invalid")
    relative = Path(value)
    if (
        relative.is_absolute() or relative.as_posix() != value
        or len(relative.parts) != 1
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BackendPublicationOutputReceiptError(f"{label} path is not canonical")
    return value


def _read_unique_file(
    output_dir: Path, relative_name: str, *, label: str,
) -> tuple[bytes, dict[str, Any]]:
    root = _checked_output_root(output_dir)
    name = _checked_relative_name(relative_name, label=label)
    path = root / name
    try:
        if _is_link_or_reparse(path):
            raise BackendPublicationOutputReceiptError(
                f"{label} contains a link/reparse point"
            )
        before = path.stat()
        if not stat.S_ISREG(before.st_mode):
            raise BackendPublicationOutputReceiptError(f"{label} is not a regular file")
        if int(before.st_nlink) != 1:
            raise BackendPublicationOutputReceiptError(
                f"{label} hardlink alias is prohibited"
            )
        payload = path.read_bytes()
        after = path.stat()
    except FileNotFoundError as error:
        raise BackendPublicationOutputReceiptError(f"{label} is missing") from error
    except OSError as error:
        raise BackendPublicationOutputReceiptError(f"{label} cannot be read: {error}") from error
    if (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
        before.st_nlink,
    ) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
        after.st_nlink,
    ):
        raise BackendPublicationOutputReceiptError(f"{label} changed while reading")
    return payload, {
        "path": name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _read_object(
    output_dir: Path, relative_name: str, *, label: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload, descriptor = _read_unique_file(output_dir, relative_name, label=label)
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BackendPublicationOutputReceiptError(f"{label} is not valid JSON") from error
    if type(value) is not dict:
        raise BackendPublicationOutputReceiptError(f"{label} must be a JSON object")
    return value, descriptor


def _descriptor(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        raise BackendPublicationOutputReceiptError(f"{label} descriptor fields drifted")
    _checked_relative_name(value.get("path"), label=label)
    if (
        type(value.get("size_bytes")) is not int or value["size_bytes"] < 0
        or not _valid_sha(value.get("sha256"))
    ):
        raise BackendPublicationOutputReceiptError(f"{label} descriptor is invalid")
    return copy.deepcopy(value)


def _execution(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _EXECUTION_FIELDS:
        raise BackendPublicationOutputReceiptError(
            "full publication execution binding fields drifted"
        )
    if (
        value.get("schema_version") != 1
        or value.get("artifact_kind") != EXECUTION_BINDING_KIND
        or not _valid_sha(value.get("run_identity_sha256"))
        or type(value.get("sequence")) is not int or value["sequence"] < 0
        or type(value.get("pair_id")) is not str or not value["pair_id"]
        or type(value.get("attempt")) is not int or value["attempt"] < 1
        or type(value.get("arm_id")) is not str or not value["arm_id"]
    ):
        raise BackendPublicationOutputReceiptError(
            "full publication execution binding is invalid"
        )
    return copy.deepcopy(value)


def launcher_output_protocol(policy: Any) -> dict[str, Any]:
    """Return the exact launcher-owned output set for one frozen policy."""
    normalized = str(policy).strip().lower()
    if not normalized:
        raise BackendPublicationOutputReceiptError(
            "backend launcher output protocol requires a policy"
        )
    material = {
        "schema_version": 2,
        "artifact_kind": OUTPUT_PROTOCOL_KIND,
        "input_protocol_identity_sha256": INPUT_PROTOCOL_IDENTITY_SHA256,
        "output_protocol_identity_sha256": OUTPUT_PROTOCOL_IDENTITY_SHA256,
        "policy": normalized,
        "launcher_evidence_files": list(
            pre_finalization_acceptance_evidence_files(normalized)
        ),
        "launcher_result_file": LAUNCHER_RESULT_FILENAME,
        "output_receipt_file": OUTPUT_RECEIPT_FILENAME,
        "atomicity": "launcher_result_then_output_receipt_last_v2",
    }
    material["protocol_sha256"] = _canonical_sha(material)
    return material


def _deadline_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        first, second = float(left), float(right)
    except (TypeError, ValueError):
        return False
    return math.isfinite(first) and math.isfinite(second) and math.isclose(
        first, second, rel_tol=0.0, abs_tol=1e-9
    )


def _validate_dispatch_resolution(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise BackendPublicationOutputReceiptError("backend dispatch resolution is missing")
    unsigned = {key: item for key, item in value.items() if key != "resolution_sha256"}
    try:
        invocation = validate_launcher_invocation(value.get("launcher_invocation"))
    except Exception as error:
        raise BackendPublicationOutputReceiptError(
            "backend dispatch launcher invocation is invalid"
        ) from error
    launcher = value.get("launcher")
    if type(launcher) is not dict or set(launcher) != _DESCRIPTOR_FIELDS:
        raise BackendPublicationOutputReceiptError(
            "backend dispatch launcher descriptor drifted"
        )
    if (
        value.get("schema_version") != 2
        or value.get("artifact_kind") != "vast_backend_publication_dispatch_resolution"
        or any(not _valid_sha(value.get(field)) for field in (
            "backend_runtime_grant_sha256", "identity_artifact_binding_sha256",
            "cell_identity_sha256", "validation_record_sha256",
            "runtime_binding_identity_sha256", "resolution_sha256",
        ))
        or value["resolution_sha256"] != _canonical_sha(unsigned)
        or value.get("launcher_invocation_sha256") != invocation["invocation_sha256"]
        or type(value.get("system")) is not str or not value["system"]
        or value.get("codec") not in {"h264", "h265"}
        or value.get("topology_kind") not in {
            "independent_processes", "shared_video_dag",
        }
        or type(value.get("policy")) is not str or not value["policy"]
        or not _deadline_equal(value.get("deadline_ms"), value.get("deadline_ms"))
        or type(launcher.get("path")) is not str or not launcher["path"]
        or type(launcher.get("size_bytes")) is not int or launcher["size_bytes"] <= 0
        or not _valid_sha(launcher.get("sha256"))
    ):
        raise BackendPublicationOutputReceiptError("backend dispatch resolution is invalid")
    return copy.deepcopy(value)


def validate_backend_publication_arm_contract(value: Any) -> dict[str, Any]:
    """Validate the complete self-hashed immutable launcher input."""
    expected_fields = {
        "schema_version", "artifact_kind", "full_publication_execution_binding",
        "resource_capability_grant_sha256", "model_parity_grant_sha256",
        "model_parity_acceptance_binding_sha256",
        "backend_runtime_grant_sha256",
        "identity_artifact_binding_sha256", "dispatch_resolution",
        "runtime_inputs", "launcher_output_protocol", "contract_sha256",
    }
    if type(value) is not dict or set(value) != expected_fields:
        raise BackendPublicationOutputReceiptError(
            "backend publication arm contract fields drifted"
        )
    unsigned = {key: item for key, item in value.items() if key != "contract_sha256"}
    _execution(value.get("full_publication_execution_binding"))
    dispatch = _validate_dispatch_resolution(value.get("dispatch_resolution"))
    runtime = value.get("runtime_inputs")
    runtime_fields = {
        "system", "scenario", "topology_kind", "codec", "policy", "deadline_ms",
        "dataset", "streams", "duration_s", "repeat_index", "base_seed",
        "run_seed", "run_id", "output_dir",
    }
    if type(runtime) is not dict or set(runtime) != runtime_fields:
        raise BackendPublicationOutputReceiptError(
            "backend publication runtime input fields drifted"
        )
    protocol = launcher_output_protocol(runtime.get("policy"))
    if value.get("launcher_output_protocol") != protocol:
        raise BackendPublicationOutputReceiptError(
            "backend launcher output protocol drifted"
        )
    if (
        value.get("schema_version") != 2
        or value.get("artifact_kind") != ARM_CONTRACT_KIND
        or not _valid_sha(value.get("contract_sha256"))
        or value["contract_sha256"] != _canonical_sha(unsigned)
        or not _valid_sha(value.get("resource_capability_grant_sha256"))
        or not _valid_sha(value.get("model_parity_grant_sha256"))
        or not _valid_sha(
            value.get("model_parity_acceptance_binding_sha256")
        )
        or value.get("backend_runtime_grant_sha256")
        != dispatch["backend_runtime_grant_sha256"]
        or value.get("identity_artifact_binding_sha256")
        != dispatch["identity_artifact_binding_sha256"]
        or runtime.get("system") != dispatch["system"]
        or runtime.get("topology_kind") != dispatch["topology_kind"]
        or runtime.get("codec") != dispatch["codec"]
        or runtime.get("policy") != dispatch["policy"]
        or not _deadline_equal(runtime.get("deadline_ms"), dispatch["deadline_ms"])
        or type(runtime.get("scenario")) is not str or not runtime["scenario"]
        or type(runtime.get("dataset")) is not dict
        or type(runtime.get("streams")) is not int or runtime["streams"] <= 0
        or type(runtime.get("duration_s")) is not int or runtime["duration_s"] <= 0
        or type(runtime.get("repeat_index")) is not int or runtime["repeat_index"] < 0
        or type(runtime.get("base_seed")) is not int
        or type(runtime.get("run_seed")) is not int
        or type(runtime.get("run_id")) is not str or not runtime["run_id"]
        or type(runtime.get("output_dir")) is not str
        or not Path(runtime["output_dir"]).is_absolute()
        or protocol["input_protocol_identity_sha256"]
        != dispatch["launcher_invocation"]["input_protocol_identity_sha256"]
        or protocol["output_protocol_identity_sha256"]
        != dispatch["launcher_invocation"]["output_protocol_identity_sha256"]
    ):
        raise BackendPublicationOutputReceiptError(
            "backend publication arm contract is invalid or crossbound incorrectly"
        )
    return copy.deepcopy(value)


def _authority_material(
    *, kind: str, file_descriptor: Mapping[str, Any], content_sha256: str,
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    dispatch = contract["dispatch_resolution"]
    runtime = contract["runtime_inputs"]
    execution = contract["full_publication_execution_binding"]
    return {
        "schema_version": 2,
        "artifact_kind": kind,
        **copy.deepcopy(dict(file_descriptor)),
        "content_sha256": content_sha256,
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "run_id": runtime["run_id"],
        "output_dir": runtime["output_dir"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher_sha256": dispatch["launcher"]["sha256"],
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": contract["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": contract[
            "resource_capability_grant_sha256"
        ],
        "model_parity_grant_sha256": contract[
            "model_parity_grant_sha256"
        ],
        "model_parity_acceptance_binding_sha256": contract[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": contract[
            "identity_artifact_binding_sha256"
        ],
    }


def _validate_authority(value: Any, *, kind: str, receipt: bool) -> dict[str, Any]:
    expected_fields = _RECEIPT_AUTHORITY_FIELDS if receipt else _AUTHORITY_FIELDS
    if type(value) is not dict or set(value) != expected_fields:
        raise BackendPublicationOutputReceiptError(
            "backend publication authority fields drifted"
        )
    _descriptor({key: value[key] for key in _DESCRIPTOR_FIELDS}, label="authority")
    _execution(value.get("full_publication_execution_binding"))
    if (
        value.get("schema_version") != 2 or value.get("artifact_kind") != kind
        or not _valid_sha(value.get("content_sha256"))
        or not _valid_sha(value.get("run_identity_sha256"))
        or value["run_identity_sha256"]
        != value["full_publication_execution_binding"]["run_identity_sha256"]
        or type(value.get("run_id")) is not str or not value["run_id"]
        or type(value.get("output_dir")) is not str
        or not Path(value["output_dir"]).is_absolute()
        or any(not _valid_sha(value.get(field)) for field in (
            "dispatch_resolution_sha256", "cell_identity_sha256", "launcher_sha256",
            "launcher_invocation_sha256", "backend_runtime_grant_sha256",
            "resource_capability_grant_sha256", "model_parity_grant_sha256",
            "model_parity_acceptance_binding_sha256",
            "identity_artifact_binding_sha256",
        ))
    ):
        raise BackendPublicationOutputReceiptError(
            "backend publication authority is invalid"
        )
    if receipt:
        _descriptor(value.get("arm_contract"), label="arm contract")
        _descriptor(value.get("launcher_result"), label="launcher result")
        files = value.get("evidence_files")
        if type(files) is not list or not files:
            raise BackendPublicationOutputReceiptError(
                "backend publication receipt evidence descriptors are invalid"
            )
        validated = [_descriptor(item, label="launcher evidence") for item in files]
        names = [item["path"] for item in validated]
        if names != sorted(names) or len(set(names)) != len(names):
            raise BackendPublicationOutputReceiptError(
                "backend publication receipt evidence descriptors are not unique/sorted"
            )
    return copy.deepcopy(value)


def validate_backend_publication_arm_contract_authority(value: Any) -> dict[str, Any]:
    return _validate_authority(
        value, kind=ARM_CONTRACT_AUTHORITY_KIND, receipt=False,
    )


def validate_backend_publication_output_receipt_authority(value: Any) -> dict[str, Any]:
    return _validate_authority(
        value, kind=OUTPUT_RECEIPT_AUTHORITY_KIND, receipt=True,
    )


def _atomic_create_json(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    payload = _canonical_bytes(dict(value)) + b"\n"
    if path.exists():
        raise BackendPublicationOutputReceiptError(
            f"immutable backend publication artifact already exists: {path.name}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        with path.open("rb+") as persisted:
            os.fsync(persisted.fileno())
        if os.name != "nt":
            try:
                directory_descriptor = os.open(
                    path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
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
    finally:
        temporary.unlink(missing_ok=True)
    observed, file_descriptor = _read_unique_file(
        path.parent, path.name, label=f"persisted {path.name}",
    )
    if observed != payload:
        raise BackendPublicationOutputReceiptError(
            f"persisted backend publication artifact bytes drifted: {path.name}"
        )
    return file_descriptor


def write_immutable_backend_publication_arm_contract(
    path: Path, value: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate, atomically create, and return the contract's authority."""
    if Path(path).name != ARM_CONTRACT_FILENAME:
        raise BackendPublicationOutputReceiptError(
            "backend publication arm contract filename drifted"
        )
    contract = validate_backend_publication_arm_contract(dict(value))
    expected_output = Path(contract["runtime_inputs"]["output_dir"]).resolve(
        strict=True
    )
    if Path(path).parent.resolve(strict=True) != expected_output:
        raise BackendPublicationOutputReceiptError(
            "backend publication arm contract output directory drifted"
        )
    descriptor = _atomic_create_json(Path(path), contract)
    authority = _authority_material(
        kind=ARM_CONTRACT_AUTHORITY_KIND,
        file_descriptor=descriptor,
        content_sha256=contract["contract_sha256"],
        contract=contract,
    )
    return validate_backend_publication_arm_contract_authority(authority)


def _read_contract_from_path(
    arm_contract_path: Path, *, output_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _checked_output_root(output_dir)
    try:
        if Path(arm_contract_path).resolve(strict=True) != (
            root / ARM_CONTRACT_FILENAME
        ).resolve(strict=True):
            raise BackendPublicationOutputReceiptError(
                "backend publication arm contract path drifted"
            )
    except OSError as error:
        raise BackendPublicationOutputReceiptError(
            "backend publication arm contract is missing"
        ) from error
    contract, descriptor = _read_object(
        root, ARM_CONTRACT_FILENAME, label="backend publication arm contract",
    )
    contract = validate_backend_publication_arm_contract(contract)
    if Path(contract["runtime_inputs"]["output_dir"]).resolve(strict=True) != root:
        raise BackendPublicationOutputReceiptError(
            "backend publication arm contract output directory is replayed/swapped"
        )
    authority = _authority_material(
        kind=ARM_CONTRACT_AUTHORITY_KIND,
        file_descriptor=descriptor,
        content_sha256=contract["contract_sha256"],
        contract=contract,
    )
    return (
        contract,
        descriptor,
        validate_backend_publication_arm_contract_authority(authority),
    )


def _physical_descriptors(
    output_dir: Path, relative_names: Sequence[str],
) -> list[dict[str, Any]]:
    descriptors: list[dict[str, Any]] = []
    for name in sorted(relative_names):
        _payload, descriptor = _read_unique_file(
            output_dir, name, label=f"launcher evidence {name}",
        )
        descriptors.append(descriptor)
    return descriptors


def _launcher_result_material(
    contract: Mapping[str, Any], *,
    arm_contract_descriptor: Mapping[str, Any],
    evidence_descriptors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dispatch = contract["dispatch_resolution"]
    execution = contract["full_publication_execution_binding"]
    runtime = contract["runtime_inputs"]
    material = {
        "schema_version": 2,
        "artifact_kind": LAUNCHER_RESULT_KIND,
        "status": "completed",
        "arm_contract": copy.deepcopy(dict(arm_contract_descriptor)),
        "arm_contract_content_sha256": contract["contract_sha256"],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "run_id": runtime["run_id"],
        "output_dir": runtime["output_dir"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher": copy.deepcopy(dispatch["launcher"]),
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": contract["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": contract[
            "resource_capability_grant_sha256"
        ],
        "model_parity_grant_sha256": contract[
            "model_parity_grant_sha256"
        ],
        "model_parity_acceptance_binding_sha256": contract[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": contract[
            "identity_artifact_binding_sha256"
        ],
        "output_protocol_sha256": contract["launcher_output_protocol"][
            "protocol_sha256"
        ],
        "evidence_files": [copy.deepcopy(dict(item)) for item in evidence_descriptors],
    }
    material["result_sha256"] = _canonical_sha(material)
    return material


def _receipt_material(
    contract: Mapping[str, Any], *,
    arm_contract_descriptor: Mapping[str, Any],
    launcher_result_descriptor: Mapping[str, Any],
    launcher_result: Mapping[str, Any],
    evidence_descriptors: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    dispatch = contract["dispatch_resolution"]
    execution = contract["full_publication_execution_binding"]
    runtime = contract["runtime_inputs"]
    material = {
        "schema_version": 2,
        "artifact_kind": OUTPUT_RECEIPT_KIND,
        "status": "accepted_launcher_output",
        "arm_contract": copy.deepcopy(dict(arm_contract_descriptor)),
        "arm_contract_content_sha256": contract["contract_sha256"],
        "launcher_result": copy.deepcopy(dict(launcher_result_descriptor)),
        "launcher_result_content_sha256": launcher_result["result_sha256"],
        "full_publication_execution_binding": copy.deepcopy(execution),
        "run_identity_sha256": execution["run_identity_sha256"],
        "run_id": runtime["run_id"],
        "output_dir": runtime["output_dir"],
        "dispatch_resolution_sha256": dispatch["resolution_sha256"],
        "cell_identity_sha256": dispatch["cell_identity_sha256"],
        "launcher": copy.deepcopy(dispatch["launcher"]),
        "launcher_invocation_sha256": dispatch["launcher_invocation_sha256"],
        "backend_runtime_grant_sha256": contract["backend_runtime_grant_sha256"],
        "resource_capability_grant_sha256": contract[
            "resource_capability_grant_sha256"
        ],
        "model_parity_grant_sha256": contract[
            "model_parity_grant_sha256"
        ],
        "model_parity_acceptance_binding_sha256": contract[
            "model_parity_acceptance_binding_sha256"
        ],
        "identity_artifact_binding_sha256": contract[
            "identity_artifact_binding_sha256"
        ],
        "output_protocol_sha256": contract["launcher_output_protocol"][
            "protocol_sha256"
        ],
        "evidence_files": [copy.deepcopy(dict(item)) for item in evidence_descriptors],
    }
    material["receipt_sha256"] = _canonical_sha(material)
    return material


def _receipt_authority(
    receipt: Mapping[str, Any], *, descriptor: Mapping[str, Any],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    authority = _authority_material(
        kind=OUTPUT_RECEIPT_AUTHORITY_KIND,
        file_descriptor=descriptor,
        content_sha256=receipt["receipt_sha256"],
        contract=contract,
    )
    authority.update({
        "arm_contract": copy.deepcopy(receipt["arm_contract"]),
        "launcher_result": copy.deepcopy(receipt["launcher_result"]),
        "evidence_files": copy.deepcopy(receipt["evidence_files"]),
    })
    return validate_backend_publication_output_receipt_authority(authority)


def commit_backend_publication_output_receipt(
    *, arm_contract_path: Path, output_dir: Path,
) -> dict[str, Any]:
    """Launcher API: atomically emit self-hashed result, then receipt last."""
    root = _checked_output_root(output_dir)
    contract, contract_descriptor, _contract_authority = _read_contract_from_path(
        arm_contract_path, output_dir=root,
    )
    evidence = _physical_descriptors(
        root, contract["launcher_output_protocol"]["launcher_evidence_files"],
    )
    result = _launcher_result_material(
        contract,
        arm_contract_descriptor=contract_descriptor,
        evidence_descriptors=evidence,
    )
    result_descriptor = _atomic_create_json(
        root / LAUNCHER_RESULT_FILENAME, result,
    )
    receipt = _receipt_material(
        contract,
        arm_contract_descriptor=contract_descriptor,
        launcher_result_descriptor=result_descriptor,
        launcher_result=result,
        evidence_descriptors=evidence,
    )
    receipt_descriptor = _atomic_create_json(
        root / OUTPUT_RECEIPT_FILENAME, receipt,
    )
    return _receipt_authority(
        receipt, descriptor=receipt_descriptor, contract=contract,
    )


def validate_backend_publication_output_receipt(
    *, output_dir: Path,
    expected_arm_contract_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Runner API: rehash the contract, result, receipt, and exact evidence."""
    root = _checked_output_root(output_dir)
    contract, contract_descriptor, contract_authority = _read_contract_from_path(
        root / ARM_CONTRACT_FILENAME, output_dir=root,
    )
    if expected_arm_contract_authority is not None:
        expected_contract = validate_backend_publication_arm_contract_authority(
            dict(expected_arm_contract_authority)
        )
        if contract_authority != expected_contract:
            raise BackendPublicationOutputReceiptError(
                "backend publication arm contract authority drifted"
            )
    receipt, receipt_descriptor = _read_object(
        root, OUTPUT_RECEIPT_FILENAME,
        label="backend publication output receipt",
    )
    evidence = _physical_descriptors(
        root, contract["launcher_output_protocol"]["launcher_evidence_files"],
    )
    result, result_descriptor = _read_object(
        root, LAUNCHER_RESULT_FILENAME,
        label="backend publication launcher result",
    )
    expected_result = _launcher_result_material(
        contract,
        arm_contract_descriptor=contract_descriptor,
        evidence_descriptors=evidence,
    )
    if result != expected_result:
        raise BackendPublicationOutputReceiptError(
            "backend publication launcher result is tampered/swapped/replayed"
        )
    expected_receipt = _receipt_material(
        contract,
        arm_contract_descriptor=contract_descriptor,
        launcher_result_descriptor=result_descriptor,
        launcher_result=expected_result,
        evidence_descriptors=evidence,
    )
    if receipt != expected_receipt:
        raise BackendPublicationOutputReceiptError(
            "backend publication output receipt is tampered/swapped/replayed"
        )
    return _receipt_authority(
        receipt, descriptor=receipt_descriptor, contract=contract,
    )


def validate_backend_publication_artifacts(
    *, output_dir: Path,
    expected_arm_contract_authority: Mapping[str, Any],
    expected_output_receipt_authority: Mapping[str, Any],
) -> dict[str, Any]:
    """Revalidate both detached authorities against current physical bytes."""
    contract_authority = validate_backend_publication_arm_contract_authority(
        dict(expected_arm_contract_authority)
    )
    receipt_authority = validate_backend_publication_output_receipt_authority(
        dict(expected_output_receipt_authority)
    )
    observed_receipt = validate_backend_publication_output_receipt(
        output_dir=output_dir,
        expected_arm_contract_authority=contract_authority,
    )
    if observed_receipt != receipt_authority:
        raise BackendPublicationOutputReceiptError(
            "backend publication output receipt authority drifted"
        )
    crossbind_fields = (
        "full_publication_execution_binding", "run_identity_sha256", "run_id",
        "output_dir", "dispatch_resolution_sha256", "cell_identity_sha256",
        "launcher_sha256", "launcher_invocation_sha256",
        "backend_runtime_grant_sha256", "resource_capability_grant_sha256",
        "model_parity_grant_sha256",
        "model_parity_acceptance_binding_sha256",
        "identity_artifact_binding_sha256",
    )
    if any(
        contract_authority[field] != receipt_authority[field]
        for field in crossbind_fields
    ) or receipt_authority["arm_contract"] != {
        key: contract_authority[key] for key in _DESCRIPTOR_FIELDS
    }:
        raise BackendPublicationOutputReceiptError(
            "backend publication contract/receipt authorities are not crossbound"
        )
    return {
        "arm_contract_authority": contract_authority,
        "output_receipt_authority": receipt_authority,
    }


__all__ = [
    "ARM_CONTRACT_FILENAME",
    "LAUNCHER_RESULT_FILENAME",
    "OUTPUT_RECEIPT_FILENAME",
    "BackendPublicationOutputReceiptError",
    "commit_backend_publication_output_receipt",
    "launcher_output_protocol",
    "validate_backend_publication_arm_contract",
    "validate_backend_publication_arm_contract_authority",
    "validate_backend_publication_artifacts",
    "validate_backend_publication_output_receipt",
    "validate_backend_publication_output_receipt_authority",
    "write_immutable_backend_publication_arm_contract",
]
