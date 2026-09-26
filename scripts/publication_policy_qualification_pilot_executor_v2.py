#!/usr/bin/env python3
"""Execute the closed 32-cell native qualification pilot matrix.

This module is deliberately separate from the production launcher and grants.
Its output may qualify policy and full-resource contracts, but it can never be
used as a full-publication arm or authority.
"""
from __future__ import annotations

import argparse
import copy
import errno
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import partial, wraps
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence


sys.dont_write_bytecode = True

from checkpoint_deepstream_publication_runtime_v3 import (
    run_checkpoint_deepstream_publication_runtime_v3,
)
from checkpoint_gstreamer_publication_runtime_v3 import (
    run_checkpoint_gstreamer_publication_runtime_v3,
)
from checkpoint_openvino_gva_publication_runtime_v3 import (
    run_checkpoint_openvino_gva_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (
    NativePublicationOutcomeV3,
    NativePublicationRequestV3,
)
from checkpoint_publication_runtime import NATIVE_EXECUTION_BINDING_PROVENANCE
from checkpoint_savant_publication_runtime_v3 import (
    run_checkpoint_savant_publication_runtime_v3,
)
from collect_metrics import HardwareResourceCollector
from checkpoint_qualification_pilot_acceptance_v1 import (
    ACCEPTANCE_FILENAME,
    QualificationPilotAcceptanceV1Error,
    validate_checkpoint_qualification_pilot_acceptance_v1,
)
from publication_acceptance_evidence import (
    FULL_RESOURCE_EVIDENCE_FILES,
    pre_finalization_acceptance_evidence_files,
)
from publication_policy_qualification_bootstrap_v2 import (
    CALIBRATION_FILENAME as BOOTSTRAP_CALIBRATION_FILENAME,
)
from publication_policy_qualification_transaction_v2 import (
    HARDWARE_RESOURCE_COLLECTOR_PATH,
    REFRESH_ONLY_BLOCKERS as INPUT_TRANSACTION_REFRESH_BLOCKERS,
    TRANSACTION_KIND as INPUT_TRANSACTION_KIND,
    TRANSACTION_RECEIPT_FILENAME as INPUT_TRANSACTION_RECEIPT_FILENAME,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_owned_staging_cleanup_v1 import (
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
    OwnedStagingFileV1,
)
from publication_policy_qualification_execution_code_closure_v1 import (
    ExecutionCodeClosureV1Error,
    assert_loaded_project_modules_covered_v1,
    load_execution_code_closure_v1,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
POLICY_BY_RESOURCE = {"cpu": "cpu_only", "gpu": "gpu_only"}
SCENARIO_BY_TOPOLOGY = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}
RUNTIME_INPUT_KEY_BY_SYSTEM = {
    "deepstream": "deepstream_publication_runtime_v3",
    "savant": "savant_publication_runtime_v3",
    "openvino_gva": "openvino_gva_publication_runtime_v3",
    "gstreamer_custom": "gstreamer_custom_publication_runtime_v3",
}
NATIVE_RUNTIME_REGISTRY = MappingProxyType(
    {
        "deepstream": run_checkpoint_deepstream_publication_runtime_v3,
        "savant": run_checkpoint_savant_publication_runtime_v3,
        "openvino_gva": run_checkpoint_openvino_gva_publication_runtime_v3,
        "gstreamer_custom": run_checkpoint_gstreamer_publication_runtime_v3,
    }
)
PRODUCTION_ACCEPTANCE_FILENAME = "checkpoint_publication_acceptance.json"
HARDWARE_EVIDENCE_FILENAME = "hardware_resource_samples.csv"
OBSERVED_OPENVINO_DEVICE_PROBE_FILENAME = "openvino_device_probe.observed.json"
FAILED_CELL_EVIDENCE_DIRNAME = ".failed-cell-evidence-v1"
FAILED_CELL_PRESERVE_FILENAMES = (
    HARDWARE_EVIDENCE_FILENAME,
    OBSERVED_OPENVINO_DEVICE_PROBE_FILENAME,
)
CHILD_EVIDENCE_FILES = (
    *pre_finalization_acceptance_evidence_files("cpu_only"),
    "resource_intervals.csv",
    "fanout_work_counters.csv",
    "checkpoint_publication_candidate.json",
)
FINAL_NAMESPACE_FILES = frozenset(
    (*CHILD_EVIDENCE_FILES, HARDWARE_EVIDENCE_FILENAME, ACCEPTANCE_FILENAME)
)
CHECKPOINT_SCHEMA_VERSION = 3
CHECKPOINT_KIND = "vast_publication_policy_qualification_pilot_execution_v3"
RUNTIME_BUNDLE_KIND = "vast_qualification_native_runtime_input_bundle_v2"
RUNTIME_BUNDLE_SCOPE = "pre_run_policy_and_full_resource_qualification_only"
RUNTIME_BUNDLE_DIRECTORY = "qualification-runtime-inputs-v2"
RUNTIME_MATERIALIZATION_RECEIPT_FILENAME = (
    "qualification-runtime-inputs.materialization.v2.json"
)
RUNTIME_MATERIALIZATION_RECEIPT_KIND = (
    "vast_qualification_native_runtime_input_materialization_v2"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_ATTEMPT_NAME_RE = re.compile(
    r"^qualification-arm-v2-"
    r"(?:deepstream|savant|openvino_gva|gstreamer_custom)-"
    r"(?:cpu|gpu)-(?:h264|h265)-"
    r"(?:independent-processes|shared-video-dag)\.[A-Za-z0-9_-]+$"
)
_WINDOWS_DIRECTORY_COMMIT_EXECUTABLE = Path("/mnt/c/Python314/python.exe")
_WINDOWS_DIRECTORY_COMMIT_EXECUTABLE_SIZE = 106_208
_WINDOWS_DIRECTORY_COMMIT_EXECUTABLE_SHA256 = (
    "4942b86a6597e5aee0128daa00050ed79bc21f6e709a78eb19cbfeb0c2f39ac9"
)
_WINDOWS_DIRECTORY_COMMIT_SCRIPT = (
    "import os,sys;os.rename(sys.argv[1],sys.argv[2])"
)
_WINDOWS_DIRECTORY_COMMIT_SCRIPT_SHA256 = (
    "f40f2c7ff6098ae9af6b610fa4925a018f59f4096054a42bb821b95ebd84db04"
)
_ATTEMPT_OWNER_FILENAME = ".qualification-attempt-owner.v2.json"
_STAGING_OWNER_FILENAME = ".qualification-staging-owner.v2.json"
_BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
_CANDIDATE_INDEX_FIELDS = {
    "schema_version",
    "artifact_kind",
    "policy_contract_sha256",
    "dataset_manifest",
    "bindings",
    "pilots",
}
_CANDIDATE_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "policy_contract_sha256",
    "qualification_index",
    "candidate_manifest",
    "blockers",
    "sha256",
}
_BOOTSTRAP_MAPPING_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "authority",
    "policy_contract_sha256",
    "aggregation_rule",
    "minimum_samples_per_branch_resource",
    "candidate_manifest_sha256",
    "candidate_receipt_sha256",
    "model_parity_acceptance_binding_sha256",
    "calibration_evidence_sha256",
    "physical_response_evidence_sha256",
    "calibrations",
}
_MODEL_PARITY_REFRESH_FIELD = "model_parity_refresh_authority"
_BOOTSTRAP_CALIBRATION_FIELDS = {
    "schema_version",
    "artifact_kind",
    "system",
    "policy_contract_sha256",
    "costs",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "authority",
    "source_candidate_manifest_sha256",
    "source_model_parity_acceptance_binding_sha256",
    "source_physical_response_evidence_sha256",
}
_BOOTSTRAP_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "scope",
    "authority",
    "policy_contract_sha256",
    "candidate_manifest",
    "candidate_receipt",
    "candidate_receipt_identity_sha256",
    "qualification_index",
    "accepted_model_parity_manifest",
    "accepted_model_parity_assessment",
    "accepted_model_parity_receipt",
    "model_parity_acceptance_binding_sha256",
    "accepted_model_parity_evidence_sha256",
    "calibration_evidence",
    "calibration_evidence_sha256",
    "transaction_index",
    "physical_response_evidence",
    "physical_response_evidence_sha256",
    "mapping",
    "calibrations",
    "blockers",
    "receipt_sha256",
}
_INPUT_TRANSACTION_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "accepted",
    "publication_ready",
    "authorization_eligible",
    "systems",
    "cell_count",
    "hardware_resource_collector",
    "image_identity_patch",
    "image_identity_patch_sha256",
    "accepted_model_parity_manifest",
    "accepted_model_parity_assessment",
    "accepted_model_parity_receipt",
    "model_parity_acceptance_binding_sha256",
    "model_parity_acceptance_schema_version",
    "image_patch_resolution",
    "fragments",
    "candidate",
    "bootstrap",
    "blockers",
    "receipt_sha256",
}
_PENDING_CANDIDATE_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "run_id",
    "system",
    "scenario",
    "codec",
    "policy",
    "deadline_ms",
    "execution_binding_provenance",
    "topology_kind",
    "cohort_id",
    "measurement_schedule_fingerprint_sha256",
    "completed_frames_by_stream",
    "summary",
    "evidence_sha256",
    "pending_full_resource_evidence",
}
_RUNTIME_MATERIALIZATION_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "accepted",
    "publication_ready",
    "authorization_eligible",
    "scope",
    "matrix_sha256",
    "inputs",
    "container_engine",
    "live_sockets",
    "container_images",
    "device_probes",
    "generated_assets",
    "bundles",
    "blockers",
    "receipt_sha256",
}
_RUNTIME_MATERIALIZATION_INPUT_FIELDS = {
    "candidate_index_sha256",
    "candidate_manifest_sha256",
    "candidate_receipt_sha256",
    "bootstrap_mapping_sha256",
    "bootstrap_receipt_sha256",
    "qualification_input_transaction_receipt_sha256",
    "hardware_resource_collector",
    "inventory_sha256",
}
_RUNTIME_BUNDLE_RECORD_FIELDS = {
    "arm_id",
    "run_id",
    "path",
    "size_bytes",
    "sha256",
    "bundle_sha256",
}
_RUNTIME_EXPECTATION_FIELDS = {
    "execution_config_identity_sha256",
    "binding_set_identity_sha256",
    "bindings_identity_sha256",
    "worker_image_ids",
    "policy_contract_sha256",
    "preprocessing_contract_content_sha256",
}
_FORBIDDEN_PRODUCTION_KEYS = frozenset(
    {
        "full_publication_execution_binding",
        "identity_artifact_binding_sha256",
        "resource_capability_grant_sha256",
        "backend_runtime_grant_sha256",
        "model_parity_grant_sha256",
        "pre_run_resource_capability_grant",
        "pre_run_backend_runtime_grant",
        "pre_run_model_parity_grant",
        "run_metadata",
        "run_metadata_path",
        "publication_acceptance_metadata_binding",
    }
)


class QualificationPilotExecutorV2Error(RuntimeError):
    """The closed qualification execution contract was violated."""


_ACTIVE_PHYSICAL_CUSTODY: ContextVar[PhysicalRootCustodyV1 | None] = ContextVar(
    "qualification_pilot_v2_physical_custody", default=None
)


def _active_custody(root: Path | None = None) -> PhysicalRootCustodyV1 | None:
    custody = _ACTIVE_PHYSICAL_CUSTODY.get()
    if custody is None:
        return None
    _require(root is None or custody.root == root, "active custody belongs to another root")
    try:
        custody.verify()
    except PublicationPhysicalIoV1Error as error:
        raise QualificationPilotExecutorV2Error(
            f"qualification pilot physical custody changed: {error}"
        ) from error
    return custody


@dataclass(frozen=True)
class QualificationPilotCellV2:
    system: str
    resource: str
    codec: str
    topology_kind: str
    scenario: str
    policy: str
    deadline_ms: int | float
    duration_s: int
    run_id: str
    arm_id: str


@dataclass(frozen=True)
class _PinnedFile:
    path: Path
    snapshot: tuple[int, ...]
    sha256: str


@dataclass(frozen=True)
class _PinnedJSON(_PinnedFile):
    value: dict[str, Any]


@dataclass(frozen=True)
class _ExecutionCodeClosure:
    receipt_pin: _PinnedJSON
    receipt: Mapping[str, Any]
    source_pins: tuple[_PinnedFile, ...]
    interpreter: Mapping[str, Any]

    @property
    def pins(self) -> tuple[_PinnedFile, ...]:
        return (self.receipt_pin, *self.source_pins)


@dataclass(frozen=True)
class _QualificationInputs:
    root: Path
    candidate_index: _PinnedJSON
    candidate_manifest: _PinnedJSON
    candidate_receipt: _PinnedJSON
    bootstrap_mapping: _PinnedJSON
    bootstrap_receipt: _PinnedJSON
    calibrations: Mapping[str, _PinnedJSON]
    transaction_receipt: _PinnedJSON | None
    hardware_resource_collector: _PinnedFile | None

    @property
    def pins(self) -> tuple[_PinnedFile, ...]:
        pins = (
            self.candidate_index,
            self.candidate_manifest,
            self.candidate_receipt,
            self.bootstrap_mapping,
            self.bootstrap_receipt,
            *(self.calibrations[system] for system in SYSTEMS),
        )
        if self.transaction_receipt is None:
            return pins
        _require(
            self.hardware_resource_collector is not None,
            "hardware resource collector pin is required with transaction authority",
        )
        return (*pins, self.transaction_receipt, self.hardware_resource_collector)


@dataclass(frozen=True)
class _OperationalInputs:
    runtime_materialization_receipt: _PinnedJSON
    runtime_bundles: Mapping[str, _PinnedJSON]
    guardian_service_authority: _PinnedJSON
    guardian_authority: Mapping[str, Any]
    preprocessing_contract: _PinnedJSON
    preprocessing_receipt: _PinnedJSON
    preprocessing_authority: Mapping[str, Any]

    @property
    def pins(self) -> tuple[_PinnedJSON, ...]:
        return (
            self.runtime_materialization_receipt,
            *(self.runtime_bundles[arm_id] for arm_id in sorted(self.runtime_bundles)),
            self.guardian_service_authority,
            self.preprocessing_contract,
            self.preprocessing_receipt,
        )


@dataclass(frozen=True)
class _CommittedPilotCellV2:
    final: Path
    anchor: OwnedStagingDirectoryV1 | None


class _Collector(Protocol):
    def start(self) -> None: ...

    def wait_until_ready(self, *, timeout_s: float) -> None: ...

    def stop(self) -> None: ...

    def join(self, timeout: float | None = None) -> None: ...

    def is_alive(self) -> bool: ...

    def raise_if_failed(self) -> None: ...


RuntimeRunner = Callable[[NativePublicationRequestV3], NativePublicationOutcomeV3]
RequestFactory = Callable[..., NativePublicationRequestV3]
CollectorFactory = Callable[..., _Collector]
AcceptanceFinalizer = Callable[..., dict[str, Any]]
ServiceAuthorityValidator = Callable[..., dict[str, Any]]
PreprocessingContractLoader = Callable[..., dict[str, Any]]
RuntimeExpectationsLoader = Callable[[Mapping[str, Any]], dict[str, Any]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationPilotExecutorV2Error(message)


def _canonical_bytes(value: object) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise QualificationPilotExecutorV2Error(
            "qualification material is not canonical JSON"
        ) from error


def _canonical_sha(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value).rstrip(b"\n")).hexdigest()


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _is_link_or_reparse(info: os.stat_result) -> bool:
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(
        int(getattr(info, "st_file_attributes", 0)) & reparse
    )


def _physical_root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        info = lexical.lstat()
        resolved = lexical.resolve(strict=True)
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            "project_root is missing or unreadable"
        ) from error
    _require(
        stat.S_ISDIR(info.st_mode)
        and not _is_link_or_reparse(info)
        and resolved == lexical,
        "project_root must be a canonical physical directory",
    )
    return resolved


def _under_root(root: Path, value: Path | str, *, label: str) -> Path:
    raw = Path(value)
    path = Path(os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw)))
    try:
        path.relative_to(root)
    except ValueError as error:
        raise QualificationPilotExecutorV2Error(f"{label} escaped project_root") from error
    return path


def _regular_path(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        before = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationPilotExecutorV2Error(f"{label} is missing") from error
    _require(
        stat.S_ISREG(before.st_mode)
        and not _is_link_or_reparse(before)
        and int(before.st_nlink) == 1
        and resolved == path,
        f"{label} is not a canonical single-link regular file",
    )
    return path


def _physical_directory(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise QualificationPilotExecutorV2Error(f"{label} is missing") from error
    _require(
        stat.S_ISDIR(info.st_mode)
        and not _is_link_or_reparse(info)
        and resolved == path,
        f"{label} is not a canonical physical directory",
    )
    return path


def _pin_file(
    root: Path,
    value: Path | str,
    *,
    label: str,
    expected_descriptor: Mapping[str, Any] | None = None,
) -> _PinnedFile:
    custody = _active_custody(root)
    if custody is not None:
        path = _under_root(root, value, label=label)
        try:
            descriptor, _payload, identity = custody.read_descriptor_identity(
                value,
                label=label,
                maximum=1024 * 1024 * 1024,
                capture=False,
            )
            info = path.lstat()
        except (OSError, PublicationPhysicalIoV1Error) as error:
            raise QualificationPilotExecutorV2Error(
                f"{label} custody read failed: {error}"
            ) from error
        _require(
            (int(info.st_dev), int(info.st_ino)) == identity
            and int(info.st_nlink) == 1
            and (expected_descriptor is None or descriptor == expected_descriptor),
            f"{label} physical identity drifted while pinned",
        )
        return _PinnedFile(
            path=path,
            snapshot=_snapshot(info),
            sha256=descriptor["sha256"],
        )
    path = _regular_path(root, value, label=label)
    try:
        before = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(f"{label} is unreadable") from error
    observed = {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    _require(
        _snapshot(before) == _snapshot(after)
        and len(payload) == int(after.st_size)
        and (expected_descriptor is None or observed == expected_descriptor),
        f"{label} physical identity drifted while pinned",
    )
    return _PinnedFile(
        path=path,
        snapshot=_snapshot(after),
        sha256=observed["sha256"],
    )


def _pin_json(root: Path, value: Path | str, *, label: str) -> _PinnedJSON:
    custody = _active_custody(root)
    if custody is not None:
        path = _under_root(root, value, label=label)
        try:
            descriptor, payload, identity = custody.read_descriptor_identity(
                value,
                label=label,
                maximum=1024 * 1024 * 1024,
                capture=True,
            )
            info = path.lstat()
        except (OSError, PublicationPhysicalIoV1Error) as error:
            raise QualificationPilotExecutorV2Error(
                f"{label} custody read failed: {error}"
            ) from error
        assert payload is not None
        _require(
            (int(info.st_dev), int(info.st_ino)) == identity
            and int(info.st_nlink) == 1
            and descriptor["size_bytes"] == len(payload)
            and descriptor["sha256"] == hashlib.sha256(payload).hexdigest(),
            f"{label} physical identity drifted while pinned",
        )
        try:
            parsed = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError) as error:
            raise QualificationPilotExecutorV2Error(
                f"{label} is unreadable JSON"
            ) from error
        _require(type(parsed) is dict, f"{label} must be a JSON object")
        _require(payload == _canonical_bytes(parsed), f"{label} bytes are not canonical JSON")
        return _PinnedJSON(
            path=path,
            snapshot=_snapshot(info),
            sha256=descriptor["sha256"],
            value=parsed,
        )
    path = _regular_path(root, value, label=label)
    try:
        before = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
        parsed = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationPilotExecutorV2Error(f"{label} is unreadable JSON") from error
    _require(
        _snapshot(before) == _snapshot(after) and len(payload) == int(after.st_size),
        f"{label} changed while pinned",
    )
    _require(type(parsed) is dict, f"{label} must be a JSON object")
    _require(
        payload == _canonical_bytes(parsed),
        f"{label} bytes are not canonical JSON",
    )
    return _PinnedJSON(
        path=path,
        snapshot=_snapshot(after),
        sha256=hashlib.sha256(payload).hexdigest(),
        value=parsed,
    )


def _assert_pin_unchanged(pin: _PinnedFile, *, label: str) -> None:
    custody = _active_custody()
    if custody is not None:
        try:
            descriptor, _payload, identity = custody.read_descriptor_identity(
                pin.path,
                label=label,
                maximum=1024 * 1024 * 1024,
            )
            info = pin.path.lstat()
        except (OSError, PublicationPhysicalIoV1Error) as error:
            raise QualificationPilotExecutorV2Error(
                f"{label} disappeared: {error}"
            ) from error
        _require(
            _snapshot(info) == pin.snapshot
            and (int(info.st_dev), int(info.st_ino)) == identity
            and descriptor["sha256"] == pin.sha256,
            f"{label} changed after execution started",
        )
        return
    try:
        info = pin.path.lstat()
        digest = hashlib.sha256(pin.path.read_bytes()).hexdigest()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(f"{label} disappeared") from error
    _require(
        _snapshot(info) == pin.snapshot
        and not _is_link_or_reparse(info)
        and digest == pin.sha256,
        f"{label} changed after execution started",
    )


def _snapshot_record(snapshot: tuple[int, ...]) -> dict[str, int]:
    names = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_nlink",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
        "st_file_attributes",
    )
    _require(len(snapshot) == len(names), "physical snapshot shape drifted")
    return dict(zip(names, snapshot, strict=True))


def _pin_identity_record(root: Path, pin: _PinnedFile) -> dict[str, Any]:
    return {
        "path": pin.path.relative_to(root).as_posix(),
        "size_bytes": pin.snapshot[4],
        "sha256": pin.sha256,
        "snapshot": _snapshot_record(pin.snapshot),
    }


def _assert_external_identity_record(record: Mapping[str, Any], *, label: str) -> None:
    expected_fields = {"path", "size_bytes", "sha256", "snapshot"}
    _require(set(record) == expected_fields, f"{label} descriptor shape drifted")
    path = Path(str(record["path"]))
    _require(path.is_absolute(), f"{label} path is not absolute")
    try:
        info = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(f"{label} is unreadable") from error
    _require(
        _snapshot(info) == _snapshot(after)
        and _snapshot_record(_snapshot(after)) == record["snapshot"]
        and len(payload) == record["size_bytes"]
        and hashlib.sha256(payload).hexdigest() == record["sha256"]
        and stat.S_ISREG(after.st_mode)
        and not _is_link_or_reparse(after)
        and int(after.st_nlink) == 1,
        f"{label} changed after execution started",
    )


def _load_execution_code_closure(
    *, root: Path, receipt_path: Path | str
) -> _ExecutionCodeClosure:
    try:
        loaded = load_execution_code_closure_v1(
            project_root=root, receipt_path=receipt_path
        )
    except ExecutionCodeClosureV1Error as error:
        raise QualificationPilotExecutorV2Error(
            f"qualification execution code closure is invalid: {error}"
        ) from error
    receipt = loaded["receipt"]
    receipt_pin = _pin_json(root, receipt_path, label="execution code closure receipt")
    _require(
        receipt_pin.value == receipt,
        "execution code closure receipt changed between cold load and custody pin",
    )
    source_pins: list[_PinnedFile] = []
    for position, record in enumerate(receipt["project_sources"]):
        _require(
            type(record) is dict
            and set(record) == {"path", "size_bytes", "sha256", "snapshot"},
            f"execution code closure source[{position}] shape drifted",
        )
        descriptor = {
            "path": record["path"],
            "size_bytes": record["size_bytes"],
            "sha256": record["sha256"],
        }
        pin = _pin_file(
            root,
            record["path"],
            label=f"execution code closure source[{position}]",
            expected_descriptor=descriptor,
        )
        _require(
            _snapshot_record(pin.snapshot) == record["snapshot"],
            f"execution code closure source[{position}] physical snapshot drifted",
        )
        source_pins.append(pin)
    _assert_external_identity_record(
        receipt["interpreter"], label="qualification Python interpreter"
    )
    try:
        assert_loaded_project_modules_covered_v1(project_root=root, receipt=receipt)
    except ExecutionCodeClosureV1Error as error:
        raise QualificationPilotExecutorV2Error(str(error)) from error
    return _ExecutionCodeClosure(
        receipt_pin=receipt_pin,
        receipt=receipt,
        source_pins=tuple(source_pins),
        interpreter=receipt["interpreter"],
    )


def _assert_execution_barrier(
    *, root: Path, pins: Sequence[_PinnedFile], code_closure: _ExecutionCodeClosure
) -> None:
    seen: set[Path] = set()
    for pin in pins:
        if pin.path in seen:
            continue
        seen.add(pin.path)
        _assert_pin_unchanged(pin, label=pin.path.name)
    _assert_external_identity_record(
        code_closure.interpreter, label="qualification Python interpreter"
    )
    try:
        assert_loaded_project_modules_covered_v1(
            project_root=root, receipt=code_closure.receipt
        )
    except ExecutionCodeClosureV1Error as error:
        raise QualificationPilotExecutorV2Error(str(error)) from error


def _descriptor_matches(root: Path, value: Any, pin: _PinnedFile) -> bool:
    if type(value) is not dict:
        return False
    return (
        value.get("path") == pin.path.relative_to(root).as_posix()
        and value.get("size_bytes") == pin.snapshot[4]
        and value.get("sha256") == pin.sha256
    )


def _valid_descriptor_shape(value: Any) -> bool:
    return (
        type(value) is dict
        and set(value) == {"path", "size_bytes", "sha256"}
        and type(value.get("path")) is str
        and bool(value["path"])
        and not Path(value["path"]).is_absolute()
        and ".." not in Path(value["path"]).parts
        and type(value.get("size_bytes")) is int
        and value["size_bytes"] > 0
        and type(value.get("sha256")) is str
        and _SHA_RE.fullmatch(value["sha256"]) is not None
    )


def _validated_physical_descriptor(
    root: Path, value: Any, *, label: str
) -> dict[str, Any]:
    _require(_valid_descriptor_shape(value), f"{label} descriptor fields drifted")
    descriptor = dict(value)
    path = _regular_path(root, descriptor["path"], label=label)
    try:
        before = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            f"{label} descriptor cannot be rehashed"
        ) from error
    _require(
        _snapshot(before) == _snapshot(after)
        and len(payload) == descriptor["size_bytes"] == int(after.st_size)
        and hashlib.sha256(payload).hexdigest() == descriptor["sha256"],
        f"{label} descriptor content drifted",
    )
    return descriptor


def _validate_model_parity_refresh_authority(
    *,
    root: Path,
    mapping_value: Mapping[str, Any],
    bootstrap_value: Mapping[str, Any],
) -> dict[str, Any] | None:
    mapping_has_refresh = _MODEL_PARITY_REFRESH_FIELD in mapping_value
    receipt_has_refresh = _MODEL_PARITY_REFRESH_FIELD in bootstrap_value
    _require(
        mapping_has_refresh == receipt_has_refresh,
        "bootstrap model-parity refresh authority coverage drifted",
    )
    if not mapping_has_refresh:
        return None
    try:
        from checkpoint_model_parity_acceptance_v4 import (
            validate_refresh_authority_v4,
        )

        refresh = validate_refresh_authority_v4(
            mapping_value[_MODEL_PARITY_REFRESH_FIELD]
        )
    except Exception as error:
        raise QualificationPilotExecutorV2Error(
            f"bootstrap model-parity v4 refresh authority failed: {error}"
        ) from error
    _require(
        refresh
        == mapping_value[_MODEL_PARITY_REFRESH_FIELD]
        == bootstrap_value[_MODEL_PARITY_REFRESH_FIELD],
        "bootstrap model-parity v4 refresh authority cross-binding drifted",
    )
    physical_descriptors = [
        ("image identity patch", refresh["image_identity_patch"]),
        ("execution config", refresh["execution_config"]),
        ("binding-set index", refresh["binding_set"]["index"]),
        *(
            (
                f"{resource} runtime probe",
                refresh["runtime_probes"][resource],
            )
            for resource in RESOURCES
        ),
        *(
            (f"endpoint binding {coordinate}", descriptor)
            for coordinate, descriptor in sorted(
                refresh["binding_set"]["bindings"].items()
            )
        ),
    ]
    for label, authority_descriptor in physical_descriptors:
        _validated_physical_descriptor(
            root,
            {
                key: authority_descriptor[key]
                for key in ("path", "size_bytes", "sha256")
            },
            label=f"model-parity refresh {label}",
        )
    return refresh


def _validate_input_transaction_receipt(
    *,
    root: Path,
    transaction: _PinnedJSON,
    index: _PinnedJSON,
    manifest: _PinnedJSON,
    receipt: _PinnedJSON,
    mapping: _PinnedJSON,
    bootstrap_receipt: _PinnedJSON,
    calibrations: Mapping[str, _PinnedJSON],
    refresh: Mapping[str, Any] | None,
) -> None:
    value = transaction.value
    _require(
        transaction.path.name == INPUT_TRANSACTION_RECEIPT_FILENAME
        and set(value) == _INPUT_TRANSACTION_RECEIPT_FIELDS
        and value.get("schema_version") == 2
        and value.get("artifact_kind") == INPUT_TRANSACTION_KIND
        and value.get("status") == "qualification_inputs_materialized_nonaccepted"
        and value.get("scope") == "forced_resource_qualification_pilots_only"
        and value.get("accepted") is False
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and value.get("systems") == list(SYSTEMS)
        and value.get("cell_count") == 32
        and value.get("blockers")
        == [
            "transaction_is_not_policy_qualification_acceptance",
            "transaction_is_not_full_publication_authority",
            "transaction_requires_exact_32_physical_pilots",
        ]
        and value.get("receipt_sha256")
        == _canonical_sha(
            {
                key: item
                for key, item in value.items()
                if key != "receipt_sha256"
            }
        ),
        "qualification input transaction receipt identity drifted",
    )
    candidate = value.get("candidate")
    bootstrap = value.get("bootstrap")
    fragments = value.get("fragments")
    _require(
        type(candidate) is dict
        and set(candidate) == {"index", "manifest", "receipt"}
        and _descriptor_matches(root, candidate.get("index"), index)
        and _descriptor_matches(root, candidate.get("manifest"), manifest)
        and _descriptor_matches(root, candidate.get("receipt"), receipt)
        and type(bootstrap) is dict
        and set(bootstrap) == {"mapping", "calibrations", "receipt"}
        and _descriptor_matches(root, bootstrap.get("mapping"), mapping)
        and _descriptor_matches(
            root, bootstrap.get("receipt"), bootstrap_receipt
        )
        and type(bootstrap.get("calibrations")) is dict
        and set(bootstrap["calibrations"]) == set(SYSTEMS)
        and all(
            _descriptor_matches(
                root,
                bootstrap["calibrations"].get(system),
                calibrations[system],
            )
            for system in SYSTEMS
        )
        and type(fragments) is dict
        and set(fragments) == set(SYSTEMS),
        "qualification input transaction candidate/bootstrap binding drifted",
    )
    for system in SYSTEMS:
        _validated_physical_descriptor(
            root,
            fragments[system],
            label=f"qualification transaction {system} fragment",
        )
    authority_descriptors = {
        field: _validated_physical_descriptor(
            root, value.get(field), label=f"qualification transaction {field}"
        )
        for field in (
            "hardware_resource_collector",
            "image_identity_patch",
            "accepted_model_parity_manifest",
            "accepted_model_parity_assessment",
            "accepted_model_parity_receipt",
        )
    }
    _require(
        authority_descriptors["hardware_resource_collector"]["path"]
        == HARDWARE_RESOURCE_COLLECTOR_PATH,
        "qualification transaction hardware collector path drifted",
    )
    resolution = value.get("image_patch_resolution")
    parity_schema = value.get("model_parity_acceptance_schema_version")
    parity_binding = value.get("model_parity_acceptance_binding_sha256")
    _require(
        type(parity_binding) is str
        and _SHA_RE.fullmatch(parity_binding) is not None
        and parity_binding
        == mapping.value.get("model_parity_acceptance_binding_sha256")
        == bootstrap_receipt.value.get(
            "model_parity_acceptance_binding_sha256"
        )
        and bootstrap_receipt.value.get("accepted_model_parity_manifest")
        == authority_descriptors["accepted_model_parity_manifest"]
        and bootstrap_receipt.value.get("accepted_model_parity_assessment")
        == authority_descriptors["accepted_model_parity_assessment"]
        and bootstrap_receipt.value.get("accepted_model_parity_receipt")
        == authority_descriptors["accepted_model_parity_receipt"],
        "qualification transaction model-parity authority binding drifted",
    )
    if refresh is None:
        _require(
            parity_schema == 2
            and resolution
            == {
                "candidate_binding_eligible": True,
                "resolved_blockers": [],
                "resolution": "unchanged_v3_parity",
            },
            "legacy qualification transaction parity resolution drifted",
        )
    else:
        refresh_patch = {
            key: refresh["image_identity_patch"][key]
            for key in ("path", "size_bytes", "sha256")
        }
        _require(
            parity_schema == 4
            and resolution
            == {
                "candidate_binding_eligible": False,
                "resolved_blockers": list(
                    INPUT_TRANSACTION_REFRESH_BLOCKERS
                ),
                "resolution": "physical_patch_bound_v4_parity_refresh",
            }
            and refresh_patch == authority_descriptors["image_identity_patch"]
            and value.get("image_identity_patch_sha256")
            == refresh["image_identity_patch"]["patch_sha256"],
            "v4 qualification transaction parity refresh binding drifted",
        )
    _walk_forbidden_production_claims(
        value, location="qualification input transaction receipt"
    )


def _walk_forbidden_production_claims(value: Any, *, location: str) -> None:
    if type(value) is dict:
        forbidden = {
            key
            for key in value
            if type(key) is not str
            or key in _FORBIDDEN_PRODUCTION_KEYS
            or "grant" in key.lower()
            or key.lower()
            in {
                "metadata",
                "metadata_sha256",
                "publication_metadata",
                "publication_metadata_sha256",
            }
        }
        _require(
            not forbidden,
            "production authority claim is forbidden in "
            f"{location}: {sorted(map(str, forbidden))}",
        )
        for key, child in value.items():
            _walk_forbidden_production_claims(
                child, location=f"{location}.{key}"
            )
    elif type(value) is list:
        for index, child in enumerate(value):
            _walk_forbidden_production_claims(
                child, location=f"{location}[{index}]"
            )


def _load_qualification_inputs(
    *,
    project_root: Path | str,
    candidate_index_path: Path | str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_receipt_path: Path | str,
    bootstrap_dir: Path | str,
    transaction_receipt_path: Path | str | None = None,
) -> _QualificationInputs:
    root = _physical_root(project_root)
    bootstrap_root = _physical_directory(root, bootstrap_dir, label="bootstrap_dir")
    index = _pin_json(root, candidate_index_path, label="candidate index")
    manifest = _pin_json(root, candidate_manifest_path, label="candidate manifest")
    receipt = _pin_json(root, candidate_receipt_path, label="candidate receipt")
    mapping = _pin_json(root, bootstrap_mapping_path, label="bootstrap mapping")
    bootstrap_receipt = _pin_json(
        root, bootstrap_receipt_path, label="bootstrap receipt"
    )
    _require(
        mapping.path.parent == bootstrap_root
        and bootstrap_receipt.path.parent == bootstrap_root,
        "bootstrap mapping/receipt must be direct bootstrap_dir children",
    )
    calibrations = {
        system: _pin_json(
            root,
            bootstrap_root / BOOTSTRAP_CALIBRATION_FILENAME.format(system=system),
            label=f"{system} bootstrap calibration",
        )
        for system in SYSTEMS
    }

    index_value = index.value
    policy_sha = manifest.value.get("policy_contract_sha256")
    _require(
        type(policy_sha) is str and _SHA_RE.fullmatch(policy_sha) is not None,
        "candidate manifest policy identity drifted",
    )
    bindings = index_value.get("bindings")
    _require(
        set(index_value) == _CANDIDATE_INDEX_FIELDS
        and index_value.get("schema_version") == 2
        and index_value.get("artifact_kind")
        == "vast_publication_policy_qualification_index"
        and index_value.get("policy_contract_sha256") == policy_sha
        and type(bindings) is list
        and len(bindings) == 32
        and index_value.get("pilots") == [],
        "candidate index is not the exact fragment-only v2 bootstrap index",
    )
    coordinates = {
        (binding.get("system"), binding.get("branch"), binding.get("resource"))
        for binding in bindings
        if type(binding) is dict
    }
    _require(
        len(coordinates) == 32
        and coordinates
        == {
            (system, branch, resource)
            for system in SYSTEMS
            for branch in _BRANCHES
            for resource in RESOURCES
        },
        "candidate index binding coordinates drifted",
    )
    manifest_value = manifest.value
    _require(
        manifest_value.get("schema_version") == 1
        and manifest_value.get("artifact_kind")
        == "vast_publication_policy_capability_manifest"
        and manifest_value.get("policy_contract_sha256") == policy_sha
        and type(manifest_value.get("systems")) is dict
        and set(manifest_value["systems"]) == set(SYSTEMS),
        "candidate manifest identity/system set drifted",
    )
    receipt_value = receipt.value
    _require(
        set(receipt_value) == _CANDIDATE_RECEIPT_FIELDS
        and receipt_value.get("schema_version") == 1
        and receipt_value.get("artifact_kind")
        == "vast_publication_policy_qualification_candidate_receipt"
        and receipt_value.get("status") == "qualification_candidate_not_accepted"
        and receipt_value.get("accepted") is False
        and receipt_value.get("publication_ready") is False
        and receipt_value.get("scope") == "forced_resource_qualification_pilots_only"
        and receipt_value.get("policy_contract_sha256") == policy_sha
        and _descriptor_matches(
            root, receipt_value.get("qualification_index"), index
        )
        and _descriptor_matches(
            root, receipt_value.get("candidate_manifest"), manifest
        )
        and type(receipt_value.get("blockers")) is list
        and "candidate_is_not_a_full_publication_authority"
        in receipt_value["blockers"]
        and receipt_value.get("sha256")
        == _canonical_sha(
            {key: value for key, value in receipt_value.items() if key != "sha256"}
        ),
        "candidate receipt binding drifted",
    )
    mapping_value = mapping.value
    mapping_fields = frozenset(mapping_value)
    _require(
        mapping_fields
        in {
            frozenset(_BOOTSTRAP_MAPPING_FIELDS),
            frozenset(_BOOTSTRAP_MAPPING_FIELDS | {_MODEL_PARITY_REFRESH_FIELD}),
        }
        and mapping_value.get("schema_version") == 2
        and mapping_value.get("artifact_kind")
        == "vast_publication_policy_qualification_bootstrap_calibration_mapping"
        and mapping_value.get("status") == "qualification_bootstrap_not_accepted"
        and mapping_value.get("accepted") is False
        and mapping_value.get("publication_ready") is False
        and mapping_value.get("scope") == "forced_resource_qualification_pilots_only"
        and mapping_value.get("authority")
        == "nonaccepted_qualification_bootstrap_v2"
        and mapping_value.get("policy_contract_sha256") == policy_sha
        and mapping_value.get("aggregation_rule")
        == "median_of_accepted_physical_model_parity_samples_v2"
        and mapping_value.get("minimum_samples_per_branch_resource") == 30
        and mapping_value.get("candidate_manifest_sha256") == manifest.sha256
        and mapping_value.get("candidate_receipt_sha256") == receipt.sha256
        and type(mapping_value.get("model_parity_acceptance_binding_sha256"))
        is str
        and _SHA_RE.fullmatch(
            mapping_value["model_parity_acceptance_binding_sha256"]
        )
        is not None
        and type(mapping_value.get("calibrations")) is dict
        and set(mapping_value["calibrations"]) == set(SYSTEMS),
        "bootstrap mapping binding drifted",
    )
    bootstrap_value = bootstrap_receipt.value
    bootstrap_fields = frozenset(bootstrap_value)
    _require(
        bootstrap_fields
        in {
            frozenset(_BOOTSTRAP_RECEIPT_FIELDS),
            frozenset(_BOOTSTRAP_RECEIPT_FIELDS | {_MODEL_PARITY_REFRESH_FIELD}),
        }
        and bootstrap_value.get("schema_version") == 2
        and bootstrap_value.get("artifact_kind")
        == "vast_publication_policy_qualification_bootstrap_receipt"
        and bootstrap_value.get("status") == "qualification_bootstrap_not_accepted"
        and bootstrap_value.get("accepted") is False
        and bootstrap_value.get("publication_ready") is False
        and bootstrap_value.get("scope") == "forced_resource_qualification_pilots_only"
        and bootstrap_value.get("authority")
        == "nonaccepted_qualification_bootstrap_v2"
        and bootstrap_value.get("policy_contract_sha256") == policy_sha
        and bootstrap_value.get("candidate_receipt_identity_sha256")
        == receipt_value["sha256"]
        and bootstrap_value.get("model_parity_acceptance_binding_sha256")
        == mapping_value["model_parity_acceptance_binding_sha256"]
        and _descriptor_matches(
            root, bootstrap_value.get("candidate_manifest"), manifest
        )
        and _descriptor_matches(
            root, bootstrap_value.get("candidate_receipt"), receipt
        )
        and _descriptor_matches(
            root, bootstrap_value.get("qualification_index"), index
        )
        and _descriptor_matches(root, bootstrap_value.get("mapping"), mapping)
        and type(bootstrap_value.get("calibrations")) is dict
        and all(
            _descriptor_matches(
                root,
                bootstrap_value["calibrations"].get(system),
                calibrations[system],
            )
            for system in SYSTEMS
        )
        and type(bootstrap_value.get("calibration_evidence")) is list
        and bootstrap_value.get("calibration_evidence_sha256")
        == _canonical_sha(bootstrap_value["calibration_evidence"])
        and type(bootstrap_value.get("physical_response_evidence")) is list
        and bootstrap_value.get("physical_response_evidence_sha256")
        == _canonical_sha(bootstrap_value["physical_response_evidence"])
        and bootstrap_value.get("calibration_evidence_sha256")
        == mapping_value.get("calibration_evidence_sha256")
        and bootstrap_value.get("physical_response_evidence_sha256")
        == mapping_value.get("physical_response_evidence_sha256")
        and all(
            _valid_descriptor_shape(bootstrap_value.get(field))
            for field in (
                "accepted_model_parity_manifest",
                "accepted_model_parity_assessment",
                "accepted_model_parity_receipt",
            )
        )
        and type(bootstrap_value.get("transaction_index")) is dict
        and type(bootstrap_value.get("blockers")) is list
        and "bootstrap_is_not_full_publication_authority"
        in bootstrap_value["blockers"]
        and bootstrap_value.get("receipt_sha256")
        == _canonical_sha(
            {
                key: value
                for key, value in bootstrap_value.items()
                if key != "receipt_sha256"
            }
        ),
        "bootstrap receipt binding drifted",
    )
    refresh = _validate_model_parity_refresh_authority(
        root=root,
        mapping_value=mapping_value,
        bootstrap_value=bootstrap_value,
    )
    for system, pin in calibrations.items():
        value = pin.value
        _require(
            set(value) == _BOOTSTRAP_CALIBRATION_FIELDS
            and value.get("schema_version") == 1
            and value.get("artifact_kind") == "vast_publication_policy_calibration"
            and value.get("system") == system
            and value.get("policy_contract_sha256") == policy_sha
            and type(value.get("costs")) is dict
            and value.get("status") == "qualification_bootstrap_not_accepted"
            and value.get("accepted") is False
            and value.get("publication_ready") is False
            and value.get("scope") == "forced_resource_qualification_pilots_only"
            and value.get("authority")
            == "nonaccepted_qualification_bootstrap_v2"
            and value.get("source_candidate_manifest_sha256") == manifest.sha256
            and value.get("source_model_parity_acceptance_binding_sha256")
            == mapping_value["model_parity_acceptance_binding_sha256"]
            and value.get("source_physical_response_evidence_sha256")
            == mapping_value["physical_response_evidence_sha256"]
            and mapping_value["calibrations"].get(system) == value,
            f"{system} bootstrap calibration drifted",
        )
    identities = {
        (pin.snapshot[0], pin.snapshot[1]) for pin in (
            index,
            manifest,
            receipt,
            mapping,
            bootstrap_receipt,
            *calibrations.values(),
        )
    }
    _require(len(identities) == 9, "qualification bootstrap artifacts contain an alias")
    for label, value in (
        ("candidate index", index_value),
        ("candidate manifest", manifest_value),
        ("candidate receipt", receipt_value),
        ("bootstrap mapping", mapping_value),
        ("bootstrap receipt", bootstrap_value),
        *(
            (f"{system} bootstrap calibration", calibrations[system].value)
            for system in SYSTEMS
        ),
    ):
        _walk_forbidden_production_claims(value, location=label)
    transaction_receipt = (
        None
        if transaction_receipt_path is None
        else _pin_json(
            root,
            transaction_receipt_path,
            label="qualification input transaction receipt",
        )
    )
    hardware_resource_collector: _PinnedFile | None = None
    if transaction_receipt is not None:
        _validate_input_transaction_receipt(
            root=root,
            transaction=transaction_receipt,
            index=index,
            manifest=manifest,
            receipt=receipt,
            mapping=mapping,
            bootstrap_receipt=bootstrap_receipt,
            calibrations=calibrations,
            refresh=refresh,
        )
        _require(
            (transaction_receipt.snapshot[0], transaction_receipt.snapshot[1])
            not in identities,
            "qualification input transaction receipt aliases a bootstrap input",
        )
        collector_descriptor = transaction_receipt.value.get(
            "hardware_resource_collector"
        )
        _require(
            type(collector_descriptor) is dict
            and collector_descriptor.get("path")
            == HARDWARE_RESOURCE_COLLECTOR_PATH,
            "qualification input transaction hardware collector binding drifted",
        )
        hardware_resource_collector = _pin_file(
            root,
            HARDWARE_RESOURCE_COLLECTOR_PATH,
            label="hardware resource collector",
            expected_descriptor=collector_descriptor,
        )
        collector_identity = (
            hardware_resource_collector.snapshot[0],
            hardware_resource_collector.snapshot[1],
        )
        _require(
            collector_identity not in identities
            and collector_identity
            != (
                transaction_receipt.snapshot[0],
                transaction_receipt.snapshot[1],
            ),
            "hardware resource collector aliases a qualification input",
        )
    return _QualificationInputs(
        root=root,
        candidate_index=index,
        candidate_manifest=manifest,
        candidate_receipt=receipt,
        bootstrap_mapping=mapping,
        bootstrap_receipt=bootstrap_receipt,
        calibrations=MappingProxyType(calibrations),
        transaction_receipt=transaction_receipt,
        hardware_resource_collector=hardware_resource_collector,
    )


def qualification_pilot_cells_v2(
    *, deadline_ms: int | float = 100.0, duration_s: int = 180
) -> tuple[QualificationPilotCellV2, ...]:
    """Return the exact deterministic 4x2x2x2 forced-resource matrix."""

    if isinstance(deadline_ms, bool) or deadline_ms != 100:
        raise QualificationPilotExecutorV2Error(
            "qualification deadline_ms must be exactly 100"
        )
    if type(duration_s) is not int or duration_s != 180:
        raise QualificationPilotExecutorV2Error(
            "qualification duration_s must be exactly 180"
        )
    cells: list[QualificationPilotCellV2] = []
    for system in SYSTEMS:
        for resource in RESOURCES:
            for codec in CODECS:
                for topology in TOPOLOGIES:
                    slug = f"{system}-{resource}-{codec}-{topology.replace('_', '-')}"
                    cells.append(
                        QualificationPilotCellV2(
                            system=system,
                            resource=resource,
                            codec=codec,
                            topology_kind=topology,
                            scenario=SCENARIO_BY_TOPOLOGY[topology],
                            policy=POLICY_BY_RESOURCE[resource],
                            deadline_ms=100.0,
                            duration_s=duration_s,
                            run_id=f"qualification-v2-{slug}",
                            arm_id=f"qualification-arm-v2-{slug}",
                        )
                    )
    return tuple(cells)


def _matrix_sha(cells: Sequence[QualificationPilotCellV2]) -> str:
    return hashlib.sha256(
        _canonical_bytes([cell.__dict__ for cell in cells]).rstrip(b"\n")
    ).hexdigest()


def _socket_records(contract: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    engine = contract.get("container_engine_socket")
    _require(type(engine) is dict, "container engine socket pin is missing")
    records: list[dict[str, Any]] = [dict(engine)]
    endpoints = contract.get("endpoint_sockets")
    if type(endpoints) is list:
        _require(bool(endpoints), "analytics endpoint socket set is empty")
        for endpoint in endpoints:
            _require(type(endpoint) is dict, "analytics endpoint pin is invalid")
            normalized = dict(endpoint)
            host_path = normalized.pop("host_path", None)
            _require(type(host_path) is str, "analytics endpoint host path is missing")
            normalized["path"] = host_path
            records.append(normalized)
    elif type(endpoints) is dict:
        _require(
            set(endpoints) == {"analytics_execution"},
            "analytics endpoint role set drifted",
        )
        endpoint = endpoints["analytics_execution"]
        _require(type(endpoint) is dict, "analytics endpoint pin is invalid")
        records.append(dict(endpoint))
    else:
        raise QualificationPilotExecutorV2Error(
            "analytics endpoint socket pins are missing"
        )
    return tuple(records)


def _validate_live_socket_record(value: Mapping[str, Any], *, label: str) -> None:
    required = {"path", "device", "inode", "owner_uid", "owner_gid"}
    _require(
        frozenset(value)
        in {frozenset(required), frozenset((*required, "container_path"))},
        f"{label} fields drifted",
    )
    path_value = value.get("path")
    _require(
        type(path_value) is str
        and path_value.startswith("/")
        and "\x00" not in path_value
        and os.path.normpath(path_value) == path_value,
        f"{label} path is invalid",
    )
    path = Path(path_value)
    try:
        info = path.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(f"{label} is not live") from error
    _require(
        stat.S_ISSOCK(info.st_mode)
        and not _is_link_or_reparse(info)
        and value.get("device") == int(info.st_dev)
        and value.get("inode") == int(info.st_ino)
        and value.get("owner_uid") == int(info.st_uid)
        and value.get("owner_gid") == int(info.st_gid),
        f"{label} live identity drifted",
    )
    container_path = value.get("container_path")
    if container_path is not None:
        _require(
            type(container_path) is str
            and container_path.startswith("/")
            and "\x00" not in container_path,
            f"{label} container path is invalid",
        )


def _validate_request(
    request: NativePublicationRequestV3,
    *,
    inputs: _QualificationInputs,
    cell: QualificationPilotCellV2,
    output_dir: Path,
) -> dict[str, Any]:
    _require(
        type(request) is NativePublicationRequestV3,
        "request_factory did not return NativePublicationRequestV3",
    )
    expected_identity = {
        "system": cell.system,
        "topology_kind": cell.topology_kind,
        "scenario": cell.scenario,
        "project_root": inputs.root,
        "output_dir": output_dir,
        "arm_contract_path": inputs.candidate_index.path,
        "arm_contract_file_sha256": inputs.candidate_index.sha256,
        "run_id": cell.run_id,
        "arm_id": cell.arm_id,
        "launcher_evidence_files": CHILD_EVIDENCE_FILES,
    }
    for field, expected in expected_identity.items():
        _require(
            getattr(request, field) == expected,
            f"native request {field} drifted for {cell.arm_id}",
        )
    _require(
        not request.environment and not request.native_argv,
        "qualification request may not inject environment or native argv",
    )
    runtime = request.runtime_inputs
    _require(type(runtime) is dict, "native request runtime_inputs must be an object")
    expected_runtime = {
        "system": cell.system,
        "resource": cell.resource,
        "scenario": cell.scenario,
        "topology_kind": cell.topology_kind,
        "codec": cell.codec,
        "policy": cell.policy,
        "duration_s": cell.duration_s,
        "streams": 6,
        "run_id": cell.run_id,
    }
    for field, expected in expected_runtime.items():
        _require(
            runtime.get(field) == expected,
            f"native runtime input {field} drifted for {cell.arm_id}",
        )
    _require(
        not isinstance(runtime.get("deadline_ms"), bool)
        and isinstance(runtime.get("deadline_ms"), (int, float))
        and math.isclose(
            float(runtime["deadline_ms"]),
            float(cell.deadline_ms),
            rel_tol=0.0,
            abs_tol=1e-9,
        ),
        f"native runtime deadline drifted for {cell.arm_id}",
    )
    dataset = runtime.get("dataset")
    runtime_key = RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
    contract = dataset.get(runtime_key) if type(dataset) is dict else None
    _require(type(contract) is dict, "native runtime contract is missing")
    _require(
        contract.get("defer_full_resource_acceptance") is True,
        "defer_full_resource_acceptance must be hard-wired true",
    )
    mapping = contract.get("evidence_mapping")
    _require(
        type(mapping) is dict
        and set(mapping) == set(CHILD_EVIDENCE_FILES)
        and len(set(mapping.values())) == len(mapping)
        and all(
            type(value) is str
            and Path(value).name == value
            and value not in {
                HARDWARE_EVIDENCE_FILENAME,
                ACCEPTANCE_FILENAME,
                PRODUCTION_ACCEPTANCE_FILENAME,
                "run_metadata.json",
            }
            for value in mapping.values()
        ),
        "child evidence mapping escaped the qualification namespace",
    )
    _walk_forbidden_production_claims(runtime, location=f"runtime {cell.arm_id}")
    for position, record in enumerate(_socket_records(contract)):
        _validate_live_socket_record(
            record, label=f"{cell.arm_id} live socket[{position}]"
        )
    return contract


def _runtime_bundle_path(
    bootstrap_dir: Path, cell: QualificationPilotCellV2
) -> Path:
    return (
        bootstrap_dir
        / RUNTIME_BUNDLE_DIRECTORY
        / cell.system
        / cell.resource
        / cell.codec
        / f"{cell.topology_kind}.json"
    )


def _pin_runtime_bundles(
    *,
    inputs: _QualificationInputs,
    bootstrap_dir: Path,
    cells: Sequence[QualificationPilotCellV2],
) -> Mapping[str, _PinnedJSON]:
    pinned = {
        cell.arm_id: _pin_json(
            inputs.root,
            _runtime_bundle_path(bootstrap_dir, cell),
            label=f"{cell.arm_id} native runtime input bundle",
        )
        for cell in cells
    }
    _require(
        len(pinned) == 32
        and len({(pin.snapshot[0], pin.snapshot[1]) for pin in pinned.values()})
        == 32,
        "native runtime input bundles contain a physical alias",
    )
    return MappingProxyType(pinned)


def _validate_runtime_materialization_receipt(
    *,
    inputs: _QualificationInputs,
    bootstrap_dir: Path,
    cells: Sequence[QualificationPilotCellV2],
    receipt: _PinnedJSON,
    runtime_bundles: Mapping[str, _PinnedJSON],
) -> dict[str, Any]:
    _require(
        inputs.transaction_receipt is not None,
        "qualification input transaction receipt is required",
    )
    _require(
        inputs.hardware_resource_collector is not None,
        "hardware resource collector authority is required",
    )
    runtime_root = bootstrap_dir / RUNTIME_BUNDLE_DIRECTORY
    value = receipt.value
    receipt_inputs = value.get("inputs")
    bundles = value.get("bundles")
    expected_input_hashes = {
        "candidate_index_sha256": inputs.candidate_index.sha256,
        "candidate_manifest_sha256": inputs.candidate_manifest.sha256,
        "candidate_receipt_sha256": inputs.candidate_receipt.sha256,
        "bootstrap_mapping_sha256": inputs.bootstrap_mapping.sha256,
        "bootstrap_receipt_sha256": inputs.bootstrap_receipt.sha256,
        "qualification_input_transaction_receipt_sha256": (
            inputs.transaction_receipt.sha256
        ),
        "hardware_resource_collector": _pinned_descriptor(
            inputs.root,
            inputs.hardware_resource_collector,
        ),
    }
    expected_records = []
    for cell in cells:
        pin = runtime_bundles[cell.arm_id]
        bundle_value = pin.value
        expected_records.append(
            {
                "arm_id": cell.arm_id,
                "run_id": cell.run_id,
                "path": pin.path.relative_to(runtime_root).as_posix(),
                "size_bytes": pin.snapshot[4],
                "sha256": pin.sha256,
                "bundle_sha256": bundle_value.get("bundle_sha256"),
            }
        )
    _require(
        receipt.path
        == runtime_root / RUNTIME_MATERIALIZATION_RECEIPT_FILENAME
        and set(value) == _RUNTIME_MATERIALIZATION_RECEIPT_FIELDS
        and value.get("schema_version") == 2
        and value.get("artifact_kind")
        == RUNTIME_MATERIALIZATION_RECEIPT_KIND
        and value.get("status")
        == "materialized_for_native_qualification_only"
        and value.get("accepted") is False
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and value.get("scope") == RUNTIME_BUNDLE_SCOPE
        and value.get("matrix_sha256") == _matrix_sha(cells)
        and type(receipt_inputs) is dict
        and set(receipt_inputs) == _RUNTIME_MATERIALIZATION_INPUT_FIELDS
        and all(
            receipt_inputs.get(field) == sha256
            for field, sha256 in expected_input_hashes.items()
        )
        and type(receipt_inputs.get("inventory_sha256")) is str
        and _SHA_RE.fullmatch(receipt_inputs["inventory_sha256"]) is not None
        and type(bundles) is list
        and all(
            type(record) is dict
            and set(record) == _RUNTIME_BUNDLE_RECORD_FIELDS
            for record in bundles
        )
        and bundles == expected_records
        and value.get("blockers")
        == ["qualification_runtime_inputs_are_not_production_authority"]
        and value.get("receipt_sha256")
        == _canonical_sha(
            {
                key: item
                for key, item in value.items()
                if key != "receipt_sha256"
            }
        ),
        "runtime-input materialization receipt binding drifted",
    )
    engine = value.get("container_engine")
    sockets = value.get("live_sockets")
    _require(
        type(engine) is dict
        and set(engine)
        == {"source_path", "asset_path", "size_bytes", "sha256"}
        and type(engine.get("source_path")) is str
        and Path(engine["source_path"]).is_absolute()
        and type(sockets) is dict
        and set(sockets) == {"container_engine", "analytics_execution"}
        and type(value.get("container_images")) is dict
        and set(value["container_images"]) == set(SYSTEMS)
        and all(
            type(value["container_images"][system]) is dict
            for system in SYSTEMS
        )
        and type(value.get("device_probes")) is dict
        and set(value["device_probes"])
        == {"gstreamer_custom", "openvino_gva"}
        and type(value.get("generated_assets")) is list,
        "runtime-input materialization operational inventory drifted",
    )
    _validated_physical_descriptor(
        inputs.root,
        {
            "path": engine["asset_path"],
            "size_bytes": engine["size_bytes"],
            "sha256": engine["sha256"],
        },
        label="materialized container engine asset",
    )
    for role in ("container_engine", "analytics_execution"):
        socket_record = sockets[role]
        _require(
            type(socket_record) is dict,
            f"runtime-input {role} socket pin is invalid",
        )
        _validate_live_socket_record(
            socket_record, label=f"runtime-input {role} socket"
        )
    generated_systems: set[str] = set()
    for row in value["generated_assets"]:
        _require(
            type(row) is dict
            and set(row)
            == {
                "system",
                "path",
                "container_path",
                "size_bytes",
                "sha256",
            }
            and row.get("system") in SYSTEMS
            and row["system"] not in generated_systems,
            "runtime-input generated asset inventory drifted",
        )
        generated_systems.add(row["system"])
        _validated_physical_descriptor(
            inputs.root,
            {key: row[key] for key in ("path", "size_bytes", "sha256")},
            label=f"materialized {row['system']} adapter asset",
        )
    _require(
        generated_systems == set(SYSTEMS),
        "runtime-input generated adapter coverage drifted",
    )
    _walk_forbidden_production_claims(
        value, location="runtime-input materialization receipt"
    )
    return value


def _default_service_authority_validator(
    value: Mapping[str, Any],
    *,
    expected_preprocessing_contract_authority: Mapping[str, Any],
    expected_runtime_expectations: Mapping[str, Any],
) -> dict[str, Any]:
    from checkpoint_gstreamer_analytics_sidecar import (
        assert_publication_sidecar_service_authority_v1,
        validate_publication_sidecar_service_authority_v1,
    )

    checked = validate_publication_sidecar_service_authority_v1(value)
    return assert_publication_sidecar_service_authority_v1(
        value,
        expected_front_socket=checked["front_socket"]["path"],
        expected_execution_config_identity_sha256=expected_runtime_expectations[
            "execution_config_identity_sha256"
        ],
        expected_binding_set_identity_sha256=expected_runtime_expectations[
            "binding_set_identity_sha256"
        ],
        expected_worker_image_ids=expected_runtime_expectations[
            "worker_image_ids"
        ],
        expected_preprocessing_contract_authority=(
            expected_preprocessing_contract_authority
        ),
        expected_service_identity_sha256=checked["service_identity_sha256"],
        expected_policy_contract_sha256=(
            expected_preprocessing_contract_authority[
                "policy_contract_sha256"
            ]
        ),
    )


def _default_preprocessing_contract_loader(**kwargs: Any) -> dict[str, Any]:
    from publication_guardian_preprocessing_contract_v1 import (
        load_guardian_preprocessing_contract_v1,
    )

    return load_guardian_preprocessing_contract_v1(**kwargs)


def _default_runtime_expectations_loader(
    receipt: Mapping[str, Any],
) -> dict[str, Any]:
    from publication_guardian_runtime_expectations_v1 import (
        runtime_expectations_from_preprocessing_receipt_v1,
    )

    return runtime_expectations_from_preprocessing_receipt_v1(receipt)


def _load_operational_inputs(
    *,
    inputs: _QualificationInputs,
    bootstrap_dir: Path,
    cells: Sequence[QualificationPilotCellV2],
    runtime_input_materialization_receipt_path: Path | str,
    guardian_service_authority_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_contract_receipt_path: Path | str,
    service_authority_validator: ServiceAuthorityValidator,
    preprocessing_contract_loader: PreprocessingContractLoader,
    runtime_expectations_loader: RuntimeExpectationsLoader,
) -> _OperationalInputs:
    _require(
        inputs.transaction_receipt is not None,
        "qualification input transaction receipt is required",
    )
    runtime_bundles = _pin_runtime_bundles(
        inputs=inputs, bootstrap_dir=bootstrap_dir, cells=cells
    )
    materialization = _pin_json(
        inputs.root,
        runtime_input_materialization_receipt_path,
        label="runtime-input materialization receipt",
    )
    materialization_value = _validate_runtime_materialization_receipt(
        inputs=inputs,
        bootstrap_dir=bootstrap_dir,
        cells=cells,
        receipt=materialization,
        runtime_bundles=runtime_bundles,
    )
    service_pin = _pin_json(
        inputs.root,
        guardian_service_authority_path,
        label="guardian service authority",
    )
    preprocessing_contract = _pin_json(
        inputs.root,
        preprocessing_contract_path,
        label="guardian preprocessing contract",
    )
    preprocessing_receipt = _pin_json(
        inputs.root,
        preprocessing_contract_receipt_path,
        label="guardian preprocessing materialization receipt",
    )
    try:
        preprocessing = preprocessing_contract_loader(
            project_root=inputs.root,
            preprocessing_contract_path=preprocessing_contract.path,
            materialization_receipt_path=preprocessing_receipt.path,
            candidate_manifest_path=inputs.candidate_manifest.path,
        )
    except Exception as error:
        raise QualificationPilotExecutorV2Error(
            f"guardian preprocessing receipt failed validation: {error}"
        ) from error
    authority = preprocessing.get("authority") if type(preprocessing) is dict else None
    _require(
        type(preprocessing) is dict
        and set(preprocessing) == {"preprocessing_contract", "receipt", "authority"}
        and preprocessing.get("preprocessing_contract")
        == preprocessing_contract.value
        and preprocessing.get("receipt") == preprocessing_receipt.value
        and type(authority) is dict
        and type(authority.get("materialization_receipt_identity_sha256"))
        is str
        and _SHA_RE.fullmatch(
            authority["materialization_receipt_identity_sha256"]
        )
        is not None
        and authority.get("materialization_receipt_file_sha256")
        == preprocessing_receipt.sha256
        and authority.get("qualification_transaction_receipt_sha256")
        == inputs.transaction_receipt.value["receipt_sha256"],
        "guardian preprocessing receipt operational binding drifted",
    )
    try:
        runtime_expectations = runtime_expectations_loader(
            preprocessing_receipt.value
        )
    except Exception as error:
        raise QualificationPilotExecutorV2Error(
            f"guardian runtime expectations failed validation: {error}"
        ) from error
    worker_image_ids = (
        runtime_expectations.get("worker_image_ids")
        if type(runtime_expectations) is dict
        else None
    )
    _require(
        type(runtime_expectations) is dict
        and set(runtime_expectations) == _RUNTIME_EXPECTATION_FIELDS
        and all(
            type(runtime_expectations.get(field)) is str
            and _SHA_RE.fullmatch(runtime_expectations[field]) is not None
            for field in (
                "execution_config_identity_sha256",
                "binding_set_identity_sha256",
                "bindings_identity_sha256",
                "policy_contract_sha256",
                "preprocessing_contract_content_sha256",
            )
        )
        and type(worker_image_ids) is dict
        and set(worker_image_ids) == set(RESOURCES)
        and all(
            type(worker_image_ids.get(resource)) is str
            and _IMAGE_ID_RE.fullmatch(worker_image_ids[resource]) is not None
            for resource in RESOURCES
        )
        and runtime_expectations["policy_contract_sha256"]
        == authority.get("policy_contract_sha256")
        and runtime_expectations["preprocessing_contract_content_sha256"]
        == authority.get("preprocessing_contract_content_sha256"),
        "guardian runtime expectations/preprocessing authority binding drifted",
    )
    try:
        service_authority = service_authority_validator(
            service_pin.value,
            expected_preprocessing_contract_authority=authority,
            expected_runtime_expectations=runtime_expectations,
        )
    except Exception as error:
        raise QualificationPilotExecutorV2Error(
            f"guardian service authority failed live validation: {error}"
        ) from error
    _require(
        type(service_authority) is dict
        and service_authority == service_pin.value
        and type(service_authority.get("service_authority_sha256")) is str
        and _SHA_RE.fullmatch(service_authority["service_authority_sha256"])
        is not None
        and type(service_authority.get("service_identity_sha256")) is str
        and _SHA_RE.fullmatch(service_authority["service_identity_sha256"])
        is not None
        and service_authority.get("preprocessing_contract_authority")
        == authority
        and service_authority.get("execution_config_identity_sha256")
        == runtime_expectations["execution_config_identity_sha256"]
        and service_authority.get("binding_set_identity_sha256")
        == runtime_expectations["binding_set_identity_sha256"]
        and service_authority.get("worker_image_ids") == worker_image_ids
        and type(service_authority.get("front_socket")) is dict
        and service_authority["front_socket"]
        == materialization_value["live_sockets"]["analytics_execution"],
        "guardian authority is not cross-bound to runtime materialization/preprocessing",
    )
    identities = {
        (pin.snapshot[0], pin.snapshot[1])
        for pin in (
            materialization,
            *runtime_bundles.values(),
            service_pin,
            preprocessing_contract,
            preprocessing_receipt,
        )
    }
    _require(
        len(identities) == 36,
        "qualification operational inputs contain a physical alias",
    )
    return _OperationalInputs(
        runtime_materialization_receipt=materialization,
        runtime_bundles=runtime_bundles,
        guardian_service_authority=service_pin,
        guardian_authority=MappingProxyType(dict(service_authority)),
        preprocessing_contract=preprocessing_contract,
        preprocessing_receipt=preprocessing_receipt,
        preprocessing_authority=MappingProxyType(dict(authority)),
    )


def _request_from_bootstrap_bundle(
    *,
    inputs: _QualificationInputs,
    bootstrap_dir: Path,
    cell: QualificationPilotCellV2,
    output_dir: Path,
    evidence_names: tuple[str, ...],
    bundle_pins: Mapping[str, _PinnedJSON] | None = None,
) -> NativePublicationRequestV3:
    """Load one exact, pre-materialized live runtime input from bootstrap_dir."""

    pin = (
        bundle_pins[cell.arm_id]
        if bundle_pins is not None
        else _pin_json(
            inputs.root,
            _runtime_bundle_path(bootstrap_dir, cell),
            label=f"{cell.arm_id} native runtime input bundle",
        )
    )
    _assert_pin_unchanged(pin, label=f"{cell.arm_id} native runtime input bundle")
    value = pin.value
    self_hash = value.get("bundle_sha256")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    _require(
        set(value)
        == {
            "schema_version",
            "artifact_kind",
            "status",
            "accepted",
            "publication_ready",
            "authorization_eligible",
            "scope",
            "system",
            "resource",
            "codec",
            "topology_kind",
            "run_id",
            "arm_id",
            "hardware_resource_collector",
            "runtime_inputs",
            "launcher_evidence_files",
            "bundle_sha256",
        }
        and value.get("schema_version") == 2
        and value.get("artifact_kind") == RUNTIME_BUNDLE_KIND
        and value.get("status") == "materialized_for_native_qualification_only"
        and value.get("accepted") is False
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and value.get("scope") == RUNTIME_BUNDLE_SCOPE
        and value.get("system") == cell.system
        and value.get("resource") == cell.resource
        and value.get("codec") == cell.codec
        and value.get("topology_kind") == cell.topology_kind
        and value.get("run_id") == cell.run_id
        and value.get("arm_id") == cell.arm_id
        and inputs.hardware_resource_collector is not None
        and value.get("hardware_resource_collector")
        == _pinned_descriptor(inputs.root, inputs.hardware_resource_collector)
        and value.get("launcher_evidence_files") == list(evidence_names)
        and type(value.get("runtime_inputs")) is dict
        and type(self_hash) is str
        and _SHA_RE.fullmatch(self_hash) is not None
        and self_hash == _canonical_sha(unsigned),
        f"{cell.arm_id} native runtime input bundle drifted",
    )
    runtime_inputs = copy.deepcopy(value["runtime_inputs"])
    runtime_key = RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
    dataset = runtime_inputs.get("dataset")
    contract = dataset.get(runtime_key) if type(dataset) is dict else None
    files = contract.get("files") if type(contract) is dict else None
    capability = files.get("policy_capability_manifest") if type(files) is dict else None
    calibration = files.get("policy_calibration") if type(files) is dict else None
    expected_capability = inputs.candidate_manifest.path.relative_to(inputs.root).as_posix()
    expected_calibration = inputs.calibrations[cell.system].path.relative_to(
        inputs.root
    ).as_posix()
    _require(
        type(capability) is dict
        and capability.get("path") == expected_capability
        and capability.get("size_bytes") == inputs.candidate_manifest.snapshot[4]
        and capability.get("sha256") == inputs.candidate_manifest.sha256
        and type(calibration) is dict
        and calibration.get("path") == expected_calibration
        and calibration.get("size_bytes")
        == inputs.calibrations[cell.system].snapshot[4]
        and calibration.get("sha256") == inputs.calibrations[cell.system].sha256,
        f"{cell.arm_id} runtime bundle is not bound to candidate/bootstrap inputs",
    )
    return NativePublicationRequestV3(
        system=cell.system,
        topology_kind=cell.topology_kind,
        scenario=cell.scenario,
        project_root=inputs.root,
        output_dir=output_dir,
        arm_contract_path=inputs.candidate_index.path,
        arm_contract_file_sha256=inputs.candidate_index.sha256,
        run_id=cell.run_id,
        arm_id=cell.arm_id,
        runtime_inputs=runtime_inputs,
        launcher_evidence_files=evidence_names,
    )


def _default_collector_factory(path: Path, *, run_id: str) -> _Collector:
    return HardwareResourceCollector(path, run_id=run_id, interval_s=1.0)


def _default_acceptance_finalizer(**kwargs: Any) -> dict[str, Any]:
    from checkpoint_qualification_pilot_acceptance_v1 import (
        finalize_checkpoint_qualification_pilot_acceptance_v1,
    )

    return finalize_checkpoint_qualification_pilot_acceptance_v1(**kwargs)


def _descriptor(root: Path, path: Path) -> dict[str, Any]:
    try:
        before = path.lstat()
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            f"committed file {path.name} is unreadable"
        ) from error
    _require(
        stat.S_ISREG(before.st_mode)
        and not _is_link_or_reparse(before)
        and int(before.st_nlink) == 1
        and _snapshot(before) == _snapshot(after)
        and len(payload) == int(after.st_size),
        f"committed file {path.name} is unsafe",
    )
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _pinned_descriptor(root: Path, pin: _PinnedFile) -> dict[str, Any]:
    return {
        "path": pin.path.relative_to(root).as_posix(),
        "size_bytes": pin.snapshot[4],
        "sha256": pin.sha256,
    }


def _expected_operational_binding(
    *,
    inputs: _QualificationInputs,
    operational: _OperationalInputs,
    cell: QualificationPilotCellV2,
) -> dict[str, Any]:
    _require(
        inputs.transaction_receipt is not None,
        "qualification input transaction receipt is required",
    )
    _require(
        inputs.hardware_resource_collector is not None,
        "hardware resource collector authority is required",
    )
    bundle = operational.runtime_bundles[cell.arm_id]
    return {
        "hardware_resource_collector": _pinned_descriptor(
            inputs.root,
            inputs.hardware_resource_collector,
        ),
        "qualification_input_transaction_receipt": _pinned_descriptor(
            inputs.root, inputs.transaction_receipt
        ),
        "qualification_input_transaction_receipt_identity_sha256": (
            inputs.transaction_receipt.value["receipt_sha256"]
        ),
        "runtime_input_materialization_receipt": _pinned_descriptor(
            inputs.root, operational.runtime_materialization_receipt
        ),
        "runtime_input_materialization_receipt_identity_sha256": (
            operational.runtime_materialization_receipt.value["receipt_sha256"]
        ),
        "runtime_input_bundle": _pinned_descriptor(inputs.root, bundle),
        "runtime_input_bundle_identity_sha256": bundle.value[
            "bundle_sha256"
        ],
        "guardian_service_authority": _pinned_descriptor(
            inputs.root, operational.guardian_service_authority
        ),
        "guardian_service_authority_identity_sha256": operational.guardian_authority[
            "service_authority_sha256"
        ],
        "guardian_preprocessing_contract_receipt": _pinned_descriptor(
            inputs.root, operational.preprocessing_receipt
        ),
        "guardian_preprocessing_contract_receipt_identity_sha256": operational.preprocessing_authority[
            "materialization_receipt_identity_sha256"
        ],
    }


def _validate_nonauthorizing_acceptance(
    path: Path,
    *,
    root: Path,
    cell: QualificationPilotCellV2,
    expected_operational_binding: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        value = validate_checkpoint_qualification_pilot_acceptance_v1(
            project_root=root,
            acceptance_path=path,
            expected_system=cell.system,
            expected_resource=cell.resource,
            expected_codec=cell.codec,
            expected_topology_kind=cell.topology_kind,
            expected_run_id=cell.run_id,
            expected_arm_id=cell.arm_id,
        )
    except (
        QualificationPilotAcceptanceV1Error,
        OSError,
        UnicodeError,
        json.JSONDecodeError,
    ) as error:
        raise QualificationPilotExecutorV2Error(
            f"{cell.arm_id} qualification acceptance validation failed"
        ) from error
    coordinate = value.get("coordinate") if type(value) is dict else None
    _require(
        type(value) is dict
        and value.get("artifact_kind")
        == "vast_checkpoint_qualification_pilot_acceptance_v1"
        and value.get("status") == "accepted_native_qualification_pilot"
        and value.get("run_id") == cell.run_id
        and value.get("arm_id") == cell.arm_id
        and coordinate
        == {
            "system": cell.system,
            "resource": cell.resource,
            "codec": cell.codec,
            "topology_kind": cell.topology_kind,
        }
        and value.get("scenario") == cell.scenario
        and value.get("policy") == cell.policy
        and value.get("accepted_for_full_publication") is False
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and value.get("blockers")
        == ["qualification_pilot_is_not_full_publication_arm"]
        and value.get("operational_binding")
        == dict(expected_operational_binding),
        f"{cell.arm_id} qualification acceptance is authorizing or drifted",
    )
    _walk_forbidden_production_claims(value, location=f"acceptance {cell.arm_id}")
    return value


def _validate_pending_candidate(
    path: Path, *, root: Path, cell: QualificationPilotCellV2
) -> dict[str, Any]:
    pin = _pin_json(root, path, label=f"{cell.arm_id} pending runtime candidate")
    value = pin.value
    _require(
        set(value) == _PENDING_CANDIDATE_FIELDS
        and value.get("schema_version") == 2
        and value.get("artifact_kind")
        == "checkpoint_publication_runtime_candidate"
        and value.get("status") == "pending_full_resource_validation"
        and value.get("run_id") == cell.run_id
        and value.get("system") == cell.system
        and value.get("scenario") == cell.scenario
        and value.get("codec") == cell.codec
        and value.get("policy") == cell.policy
        and value.get("execution_binding_provenance")
        == NATIVE_EXECUTION_BINDING_PROVENANCE
        and value.get("topology_kind") == cell.topology_kind
        and not isinstance(value.get("deadline_ms"), bool)
        and isinstance(value.get("deadline_ms"), (int, float))
        and math.isclose(
            float(value["deadline_ms"]),
            float(cell.deadline_ms),
            rel_tol=0.0,
            abs_tol=1e-9,
        )
        and type(value.get("cohort_id")) is str
        and bool(value["cohort_id"])
        and type(value.get("measurement_schedule_fingerprint_sha256")) is str
        and _SHA_RE.fullmatch(value["measurement_schedule_fingerprint_sha256"])
        is not None
        and type(value.get("completed_frames_by_stream")) is dict
        and bool(value["completed_frames_by_stream"])
        and all(
            type(stream_id) is str
            and stream_id.isdigit()
            and type(count) is int
            and count > 0
            for stream_id, count in value["completed_frames_by_stream"].items()
        )
        and type(value.get("summary")) is dict
        and value.get("pending_full_resource_evidence")
        == list(FULL_RESOURCE_EVIDENCE_FILES),
        f"pending runtime candidate identity drifted for {cell.arm_id}",
    )
    expected_names = pre_finalization_acceptance_evidence_files(cell.policy)
    expected_evidence = {
        name: _descriptor(root, path.parent / name)["sha256"]
        for name in expected_names
    }
    _require(
        value.get("evidence_sha256") == expected_evidence,
        f"pending runtime candidate evidence drifted for {cell.arm_id}",
    )
    _walk_forbidden_production_claims(
        value, location=f"pending candidate {cell.arm_id}"
    )
    return value


def _pilot_path(pilot_root: Path, cell: QualificationPilotCellV2) -> Path:
    return pilot_root / cell.system / cell.resource / cell.codec / cell.topology_kind


def _validate_final_namespace(
    path: Path,
    *,
    root: Path,
    cell: QualificationPilotCellV2,
    expected_operational_binding: Mapping[str, Any],
) -> None:
    try:
        names = {entry.name for entry in path.iterdir()}
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            f"{cell.arm_id} committed pilot directory is unreadable"
        ) from error
    _require(
        names == FINAL_NAMESPACE_FILES,
        f"{cell.arm_id} final evidence namespace drifted",
    )
    for name in FINAL_NAMESPACE_FILES:
        try:
            info = (path / name).lstat()
        except OSError as error:
            raise QualificationPilotExecutorV2Error(
                f"{cell.arm_id} evidence {name} is unreadable"
            ) from error
        _require(
            stat.S_ISREG(info.st_mode)
            and not _is_link_or_reparse(info)
            and int(info.st_nlink) == 1,
            f"{cell.arm_id} evidence {name} is unsafe",
        )
    _require(
        not (path / PRODUCTION_ACCEPTANCE_FILENAME).exists()
        and not (path / "run_metadata.json").exists(),
        f"{cell.arm_id} contains forbidden production evidence",
    )
    _validate_nonauthorizing_acceptance(
        path / ACCEPTANCE_FILENAME,
        root=root,
        cell=cell,
        expected_operational_binding=expected_operational_binding,
    )


def _checkpoint_payload(
    *,
    matrix_sha256: str,
    input_sha256: Mapping[str, str],
    input_identity: Mapping[str, Any],
    completed: list[dict[str, Any]],
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "artifact_kind": CHECKPOINT_KIND,
        "status": "completed" if len(completed) == 32 else "in_progress",
        "matrix_sha256": matrix_sha256,
        "input_sha256": dict(input_sha256),
        "input_identity": copy.deepcopy(dict(input_identity)),
        "completed": completed,
        "publication_ready": False,
        "authorization_eligible": False,
        "blockers": ["qualification_pilots_are_not_full_publication_arms"],
    }
    value["checkpoint_sha256"] = _canonical_sha(value)
    return value


def _write_checkpoint(
    path: Path,
    value: Mapping[str, Any],
    *,
    expected_previous_identity: tuple[int, int] | None,
    expected_completed_prefix: Sequence[str],
    _fault_hook: Callable[[str], None] | None = None,
) -> tuple[int, int]:
    payload = _canonical_bytes(dict(value))
    completed = value.get("completed")
    _require(
        type(completed) is list
        and all(type(entry) is dict and type(entry.get("arm_id")) is str for entry in completed),
        "checkpoint completed prefix is invalid",
    )
    completed_ids = tuple(entry["arm_id"] for entry in completed)
    previous_prefix = tuple(expected_completed_prefix)
    _require(
        completed_ids[: len(previous_prefix)] == previous_prefix
        and len(completed_ids) >= len(previous_prefix),
        "checkpoint replacement is not a deterministic prefix extension",
    )
    custody = _active_custody()
    if custody is not None:
        try:
            if expected_previous_identity is None:
                _require(
                    not os.path.lexists(path),
                    "checkpoint appeared before exclusive first commit",
                )
                _descriptor, identity, _disposition = (
                    custody.commit_or_adopt_exact_identity(
                        path,
                        payload,
                        label="qualification execution checkpoint",
                        mode=0o600,
                        create_parents=False,
                        after_publish_step=_fault_hook,
                    )
                )
                return identity
            _mode, observed_identity = custody.stat_regular_identity(
                path, label="qualification execution checkpoint prior inode"
            )
            _require(
                observed_identity == expected_previous_identity,
                "checkpoint prior inode changed before replacement",
            )
            # Recheck immediately before the held-dirfd atomic replacement.
            _mode, observed_identity = custody.stat_regular_identity(
                path, label="qualification execution checkpoint prior inode recheck"
            )
            _require(
                observed_identity == expected_previous_identity,
                "checkpoint prior inode changed during replacement",
            )
            custody.replace_atomic(
                path,
                payload,
                label="qualification execution checkpoint",
                mode=0o600,
                create_parents=False,
            )
            _descriptor, _captured, identity = custody.read_descriptor_identity(
                path,
                label="qualification execution checkpoint replacement",
                maximum=len(payload),
            )
            _require(
                identity != expected_previous_identity,
                "checkpoint replacement did not publish a fresh inode",
            )
            return identity
        except PublicationPhysicalIoV1Error as error:
            raise QualificationPilotExecutorV2Error(
                f"checkpoint custody commit failed: {error}"
            ) from error
    path.parent.mkdir(parents=True, exist_ok=True)
    _require(
        path.parent.is_dir() and not path.parent.is_symlink(),
        "checkpoint parent is unsafe",
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        if expected_previous_identity is None:
            _require(not os.path.lexists(path), "checkpoint collision is unsafe")
        else:
            info = path.lstat()
            _require(
                stat.S_ISREG(info.st_mode)
                and not _is_link_or_reparse(info)
                and int(info.st_nlink) == 1
                and (int(info.st_dev), int(info.st_ino))
                == expected_previous_identity,
                "checkpoint collision is unsafe",
            )
        os.replace(temporary, path)
        directory_descriptor: int | None = None
        try:
            directory_descriptor = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            os.fsync(directory_descriptor)
        except OSError:
            pass
        finally:
            if directory_descriptor is not None:
                os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)
    info = path.lstat()
    _require(
        stat.S_ISREG(info.st_mode)
        and not _is_link_or_reparse(info)
        and int(info.st_nlink) == 1,
        "committed checkpoint is unsafe",
    )
    return int(info.st_dev), int(info.st_ino)


def _load_checkpoint(
    *,
    path: Path,
    matrix_sha256: str,
    input_sha256: Mapping[str, str],
    input_identity: Mapping[str, Any],
    cells: Sequence[QualificationPilotCellV2],
    root: Path,
    pilot_root: Path,
    inputs: _QualificationInputs,
    operational: _OperationalInputs,
) -> list[dict[str, Any]]:
    if not os.path.lexists(path):
        return []
    pin = _pin_json(root, path, label="qualification execution checkpoint")
    value = pin.value
    unsigned = {key: item for key, item in value.items() if key != "checkpoint_sha256"}
    completed = value.get("completed")
    _require(
        value.get("schema_version") == CHECKPOINT_SCHEMA_VERSION
        and value.get("artifact_kind") == CHECKPOINT_KIND
        and value.get("status") in {"in_progress", "completed"}
        and value.get("matrix_sha256") == matrix_sha256
        and value.get("input_sha256") == dict(input_sha256)
        and value.get("input_identity") == dict(input_identity)
        and value.get("publication_ready") is False
        and value.get("authorization_eligible") is False
        and type(completed) is list
        and (value.get("status") == "completed") == (len(completed) == 32)
        and value.get("blockers")
        == ["qualification_pilots_are_not_full_publication_arms"]
        and value.get("checkpoint_sha256") == _canonical_sha(unsigned),
        "qualification execution checkpoint drifted",
    )
    by_arm = {cell.arm_id: cell for cell in cells}
    seen: set[str] = set()
    for entry in completed:
        _require(type(entry) is dict, "checkpoint completed entry is invalid")
        arm_id = entry.get("arm_id")
        _require(
            type(arm_id) is str and arm_id in by_arm and arm_id not in seen,
            "checkpoint completed arm set drifted",
        )
        seen.add(arm_id)
        cell = by_arm[arm_id]
        final = _pilot_path(pilot_root, cell)
        _validate_final_namespace(
            final,
            root=root,
            cell=cell,
            expected_operational_binding=_expected_operational_binding(
                inputs=inputs, operational=operational, cell=cell
            ),
        )
        expected_entry = _checkpoint_entry(
            root=root,
            pilot_root=pilot_root,
            final=final,
            cell=cell,
        )
        _require(
            entry == expected_entry,
            f"checkpoint binding drifted for {arm_id}",
        )
    _require(
        [entry["arm_id"] for entry in completed]
        == [cell.arm_id for cell in cells[: len(completed)]],
        "checkpoint completed arms are not the deterministic matrix prefix",
    )
    return list(completed)


def _ensure_output_root(root: Path, value: Path | str, *, label: str) -> Path:
    path = _under_root(root, value, label=label)
    _require(path != root, f"{label} cannot be project_root")
    custody = _active_custody(root)
    if custody is not None:
        try:
            return custody.ensure_directory(path, label=label)
        except PublicationPhysicalIoV1Error as error:
            raise QualificationPilotExecutorV2Error(
                f"{label} custody failed: {error}"
            ) from error
    if not path.exists():
        ancestor = path.parent
        while not ancestor.exists() and ancestor != root:
            ancestor = ancestor.parent
        _require(ancestor.exists(), f"{label} has no physical parent")
        cursor = root
        for part in ancestor.relative_to(root).parts:
            cursor = cursor / part
            info = cursor.lstat()
            _require(
                stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
                f"{label} parent contains a link/reparse point",
            )
        path.mkdir(parents=True, exist_ok=False)
    return _physical_directory(root, path, label=label)


def _ensure_final_parent(pilot_root: Path, final: Path) -> None:
    _require(
        final != pilot_root and pilot_root in final.parents,
        "pilot final path escaped pilot_root",
    )
    custody = _active_custody()
    if custody is not None:
        try:
            custody.ensure_directory(final.parent, label="pilot final parent")
        except PublicationPhysicalIoV1Error as error:
            raise QualificationPilotExecutorV2Error(
                f"pilot final parent custody failed: {error}"
            ) from error
        return
    final.parent.mkdir(parents=True, exist_ok=True)
    cursor = pilot_root
    for part in final.parent.relative_to(pilot_root).parts:
        cursor = cursor / part
        info = cursor.lstat()
        _require(
            stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
            "pilot final parent contains a link/reparse point",
        )


def _drvfs_mountpoint(path: Path) -> Path | None:
    """Return the exact standard WSL DrvFS mount containing path."""

    if os.name != "posix" or not path.is_absolute():
        return None
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(
            encoding="ascii"
        )
        mount_lines = Path("/proc/self/mountinfo").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return None
    if "microsoft" not in release.lower():
        return None
    matches: list[Path] = []
    for line in mount_lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mountpoint_text = re.sub(
                r"\\([0-7]{3})",
                lambda match: chr(int(match.group(1), 8)),
                fields[4],
            )
            mountpoint = Path(mountpoint_text)
            filesystem = fields[separator + 1]
            super_options = fields[separator + 3 :]
        except (IndexError, ValueError):
            continue
        if path != mountpoint and mountpoint not in path.parents:
            continue
        if filesystem == "drvfs" or (
            filesystem == "9p"
            and any("aname=drvfs" in item for item in super_options)
        ):
            matches.append(mountpoint)
    if not matches:
        return None
    mountpoint = max(matches, key=lambda item: len(item.parts))
    _require(
        len(mountpoint.parts) == 3
        and mountpoint.parts[:2] == ("/", "mnt")
        and len(mountpoint.name) == 1
        and mountpoint.name.isascii()
        and mountpoint.name.isalpha(),
        "Windows no-replace bridge requires exact /mnt/<drive> DrvFS",
    )
    return mountpoint


def _windows_path_from_drvfs(path: Path, *, mountpoint: Path) -> str:
    try:
        relative = path.relative_to(mountpoint)
    except ValueError as error:
        raise QualificationPilotExecutorV2Error(
            "Windows no-replace path escaped its DrvFS mount"
        ) from error
    _require(
        relative.parts
        and all(
            part not in {"", ".", ".."}
            and "\\" not in part
            and ":" not in part
            and "\x00" not in part
            for part in relative.parts
        ),
        "Windows no-replace path is not a canonical DrvFS path",
    )
    return str(
        PureWindowsPath(f"{mountpoint.name.upper()}:\\", *relative.parts)
    )


def _directory_commit_snapshot(path: Path, *, label: str) -> tuple[tuple[Any, ...], ...]:
    """Pin one link-free tree by relative names, inodes, sizes, and bytes."""

    try:
        root_info = path.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            f"{label} root is unavailable"
        ) from error
    _require(
        stat.S_ISDIR(root_info.st_mode) and not _is_link_or_reparse(root_info),
        f"{label} root is unsafe",
    )
    rows: list[tuple[Any, ...]] = [
        (".", "directory", int(root_info.st_dev), int(root_info.st_ino))
    ]

    def visit(directory: Path) -> None:
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as error:
            raise QualificationPilotExecutorV2Error(
                f"{label} tree is unreadable"
            ) from error
        for entry in entries:
            current = directory / entry.name
            relative = current.relative_to(path).as_posix()
            try:
                before = current.lstat()
            except OSError as error:
                raise QualificationPilotExecutorV2Error(
                    f"{label} entry is unavailable: {relative}"
                ) from error
            _require(
                not _is_link_or_reparse(before),
                f"{label} contains a link/reparse point: {relative}",
            )
            if stat.S_ISDIR(before.st_mode):
                rows.append(
                    (
                        relative,
                        "directory",
                        int(before.st_dev),
                        int(before.st_ino),
                    )
                )
                visit(current)
                continue
            _require(
                stat.S_ISREG(before.st_mode) and int(before.st_nlink) == 1,
                f"{label} contains a non-regular entry: {relative}",
            )
            try:
                payload = current.read_bytes()
                after = current.lstat()
            except OSError as error:
                raise QualificationPilotExecutorV2Error(
                    f"{label} file is unreadable: {relative}"
                ) from error
            _require(
                _snapshot(before) == _snapshot(after)
                and len(payload) == int(after.st_size),
                f"{label} file changed while pinned: {relative}",
            )
            rows.append(
                (
                    relative,
                    "file",
                    int(after.st_dev),
                    int(after.st_ino),
                    len(payload),
                    hashlib.sha256(payload).hexdigest(),
                )
            )

    visit(path)
    return tuple(rows)


def _pinned_windows_directory_commit_executable() -> Path:
    executable = _WINDOWS_DIRECTORY_COMMIT_EXECUTABLE
    try:
        before = executable.lstat()
        payload = executable.read_bytes()
        after = executable.lstat()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            "pinned Windows no-replace executable is unavailable"
        ) from error
    _require(
        stat.S_ISREG(before.st_mode)
        and not _is_link_or_reparse(before)
        and int(before.st_nlink) == 1
        and _snapshot(before) == _snapshot(after)
        and len(payload)
        == int(after.st_size)
        == _WINDOWS_DIRECTORY_COMMIT_EXECUTABLE_SIZE
        and hashlib.sha256(payload).hexdigest()
        == _WINDOWS_DIRECTORY_COMMIT_EXECUTABLE_SHA256,
        "pinned Windows no-replace executable identity drifted",
    )
    _require(
        hashlib.sha256(
            _WINDOWS_DIRECTORY_COMMIT_SCRIPT.encode("ascii")
        ).hexdigest()
        == _WINDOWS_DIRECTORY_COMMIT_SCRIPT_SHA256,
        "pinned Windows no-replace script identity drifted",
    )
    return executable


def _rename_directory_noreplace_drvfs(
    source: Path, destination: Path, *, mountpoint: Path
) -> None:
    """Use Windows MoveFile no-replace semantics for one exact DrvFS tree."""

    _require(
        _drvfs_mountpoint(destination) == mountpoint,
        "Windows no-replace source/destination are not on one DrvFS drive",
    )
    _require(
        not os.path.lexists(destination),
        "immutable directory output commit collided",
    )
    before = _directory_commit_snapshot(
        source, label="Windows no-replace source"
    )
    executable = _pinned_windows_directory_commit_executable()
    environment = dict(os.environ)
    for name in tuple(environment):
        if name.upper().startswith("PYTHON"):
            environment.pop(name, None)
    windows_source = _windows_path_from_drvfs(source, mountpoint=mountpoint)
    windows_destination = _windows_path_from_drvfs(
        destination, mountpoint=mountpoint
    )
    process: subprocess.CompletedProcess[bytes] | None = None
    bridge_error: BaseException | None = None
    try:
        process = subprocess.run(
            (
                os.fspath(executable),
                "-I",
                "-S",
                "-B",
                "-X",
                "utf8",
                "-c",
                _WINDOWS_DIRECTORY_COMMIT_SCRIPT,
                windows_source,
                windows_destination,
            ),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=environment,
            cwd="/",
            check=False,
            timeout=60.0,
        )
    except (OSError, subprocess.SubprocessError) as error:
        bridge_error = error
    _pinned_windows_directory_commit_executable()

    source_exists = os.path.lexists(source)
    destination_exists = os.path.lexists(destination)
    if not source_exists and destination_exists:
        after = _directory_commit_snapshot(
            destination, label="Windows no-replace destination"
        )
        _require(
            after == before,
            "Windows no-replace destination differs from the pinned source",
        )
        return
    if source_exists:
        _require(
            _directory_commit_snapshot(
                source, label="failed Windows no-replace source"
            )
            == before,
            "failed Windows no-replace source identity drifted",
        )
    detail = (
        "collision/refusal"
        if process is not None and process.returncode != 0
        else "bridge invocation failure"
        if bridge_error is not None
        else "inconsistent success state"
    )
    failure = QualificationPilotExecutorV2Error(
        f"pinned Windows no-replace commit {detail}"
    )
    if bridge_error is not None:
        raise failure from bridge_error
    raise failure


def _rename_directory_noreplace(source: Path, destination: Path) -> None:
    """Atomically commit a directory while refusing every destination collision."""

    if os.name == "nt":
        try:
            os.rename(source, destination)
        except OSError as error:
            raise QualificationPilotExecutorV2Error(
                "immutable pilot output commit collided"
            ) from error
        return
    import ctypes

    source = Path(os.path.abspath(os.fspath(source)))
    destination = Path(os.path.abspath(os.fspath(destination)))
    _require(
        source != destination
        and source.is_absolute()
        and destination.is_absolute(),
        "immutable directory output paths are invalid",
    )
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    error_number = errno.ENOSYS
    if renameat2 is not None:
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        result = renameat2(
            -100,
            os.fsencode(source),
            -100,
            os.fsencode(destination),
            1,
        )
        if result == 0:
            return
        error_number = ctypes.get_errno()
    mountpoint = _drvfs_mountpoint(source)
    if error_number in {errno.EINVAL, errno.ENOSYS} and mountpoint is not None:
        _rename_directory_noreplace_drvfs(
            source, destination, mountpoint=mountpoint
        )
        return
    raise QualificationPilotExecutorV2Error(
        "immutable pilot output commit failed without overwrite: "
        f"{os.strerror(error_number)}"
    )


def _commit_file_noreplace(source: Path, destination: Path) -> None:
    custody = _active_custody()
    if custody is not None:
        source_anchor: OwnedStagingFileV1 | None = None
        try:
            if os.name == "posix":
                source_anchor = OwnedStagingFileV1.capture(
                    source,
                    label=f"qualification staging file {source.name}",
                )
            descriptor, payload = custody.read_descriptor(
                source,
                label=f"immutable staging file {source.name}",
                maximum=1024 * 1024 * 1024,
                capture=True,
            )
            assert payload is not None
            committed, _identity, disposition = custody.commit_or_adopt_exact_identity(
                destination,
                payload,
                label=f"immutable evidence {destination.name}",
                mode=0o444,
            )
            _require(
                committed["size_bytes"] == descriptor["size_bytes"]
                and committed["sha256"] == descriptor["sha256"]
                and disposition == "published",
                f"immutable file commit was not one fresh exact publication: {destination.name}",
            )
            if source_anchor is not None:
                source_anchor.unlink_owned(
                    final_target=source.with_name(
                        f".{source.name}.published-source-sentinel"
                    )
                )
            else:
                source.unlink()
                _fsync_directory(source.parent)
            return
        except (PublicationPhysicalIoV1Error, OwnedStagingCleanupV1Error) as error:
            raise QualificationPilotExecutorV2Error(
                f"immutable file custody commit failed: {destination.name}: {error}"
            ) from error
        finally:
            if source_anchor is not None:
                source_anchor.close()
    try:
        payload = source.read_bytes()
        with destination.open("xb", buffering=0) as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        _fsync_directory(destination.parent)
        source.unlink()
        _fsync_directory(source.parent)
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            f"immutable file commit collided: {destination.name}"
        ) from error


def _fsync_directory(path: Path) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            path,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
        )
        os.fsync(descriptor)
    except OSError as error:
        if os.name != "nt":
            raise QualificationPilotExecutorV2Error(
                f"directory durability barrier failed: {path}"
            ) from error
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _durable_directory_tree(path: Path) -> None:
    directories: list[Path] = []
    for current, child_directories, filenames in os.walk(path, topdown=False):
        current_path = Path(current)
        directories.append(current_path)
        for filename in filenames:
            leaf = current_path / filename
            descriptor = os.open(
                leaf,
                os.O_RDONLY
                | int(getattr(os, "O_BINARY", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        del child_directories
    for directory in directories:
        _fsync_directory(directory)


@contextmanager
def _exclusive_execution_lock(path: Path) -> Iterator[None]:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            "qualification pilot execution lock is unsafe"
        ) from error
    handle = os.fdopen(descriptor, "r+b", buffering=0)
    locked = False
    try:
        opened = os.fstat(handle.fileno())
        named = path.lstat()
        _require(
            stat.S_ISREG(opened.st_mode)
            and not _is_link_or_reparse(named)
            and int(opened.st_dev) == int(named.st_dev)
            and int(opened.st_ino) == int(named.st_ino)
            and int(opened.st_nlink) == 1
            and int(named.st_nlink) == 1,
            "qualification pilot execution lock identity drifted",
        )
        if int(opened.st_size) == 0:
            handle.write(b"qualification-pilot-executor-v2\n")
            os.fsync(handle.fileno())
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise QualificationPilotExecutorV2Error(
                "qualification pilot_root is locked by another executor"
            ) from error
        locked = True
        yield
    finally:
        if locked:
            try:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            finally:
                handle.close()
        else:
            handle.close()


def _directory_identity(path: Path, *, label: str) -> tuple[int, int]:
    info = path.lstat()
    _require(
        stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
        f"{label} directory identity is unsafe",
    )
    return int(info.st_dev), int(info.st_ino)


def _owner_marker_value(
    directory: Path, *, kind: str, arm_id: str | None = None
) -> dict[str, Any]:
    device, inode = _directory_identity(directory, label=kind)
    value: dict[str, Any] = {
        "schema_version": 2,
        "artifact_kind": kind,
        "directory_device": device,
        "directory_inode": inode,
    }
    if arm_id is not None:
        value["arm_id"] = arm_id
    value["owner_sha256"] = _canonical_sha(value)
    return value


def _write_owner_marker(
    directory: Path, *, filename: str, kind: str, arm_id: str | None = None
) -> tuple[int, int]:
    value = _owner_marker_value(directory, kind=kind, arm_id=arm_id)
    marker = directory / filename
    _require(not os.path.lexists(marker), f"{kind} owner marker collided")
    payload = _canonical_bytes(value)
    with marker.open("xb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())
    info = marker.lstat()
    _require(
        stat.S_ISREG(info.st_mode)
        and not _is_link_or_reparse(info)
        and int(info.st_nlink) == 1,
        f"{kind} owner marker is unsafe",
    )
    return _directory_identity(directory, label=kind)


def _validate_owner_marker(
    directory: Path,
    *,
    filename: str,
    kind: str,
    arm_id: str | None = None,
) -> tuple[int, int]:
    identity = _directory_identity(directory, label=kind)
    marker = directory / filename
    try:
        info = marker.lstat()
        payload = marker.read_bytes()
        value = json.loads(payload)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise QualificationPilotExecutorV2Error(
            f"{kind} owner marker is unavailable"
        ) from error
    unsigned = {key: item for key, item in value.items() if key != "owner_sha256"}
    _require(
        stat.S_ISREG(info.st_mode)
        and not _is_link_or_reparse(info)
        and int(info.st_nlink) == 1
        and payload == _canonical_bytes(value)
        and value.get("artifact_kind") == kind
        and value.get("directory_device") == identity[0]
        and value.get("directory_inode") == identity[1]
        and value.get("arm_id") == arm_id
        and value.get("owner_sha256") == _canonical_sha(unsigned),
        f"{kind} owner marker drifted",
    )
    return identity


def _remove_owner_marker(
    directory: Path, *, filename: str, kind: str, arm_id: str | None = None
) -> None:
    _validate_owner_marker(directory, filename=filename, kind=kind, arm_id=arm_id)
    marker = directory / filename
    marker_info = marker.lstat()
    marker.unlink()
    _require(
        (int(marker_info.st_dev), int(marker_info.st_ino))
        != _directory_identity(directory, label=kind),
        f"{kind} marker aliased its directory",
    )


def _preserve_failed_hardware_samples(
    attempt: Path,
    *,
    pilot_root: Path,
    cell: QualificationPilotCellV2,
) -> None:
    destination_dir = None
    for filename in FAILED_CELL_PRESERVE_FILENAMES:
        source = attempt / "pilot" / filename
        try:
            info = source.lstat()
        except OSError:
            continue
        if (
            not stat.S_ISREG(info.st_mode)
            or _is_link_or_reparse(info)
            or int(info.st_size) <= 0
        ):
            continue
        if destination_dir is None:
            destination_dir = pilot_root / FAILED_CELL_EVIDENCE_DIRNAME / cell.arm_id
            destination_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        destination = destination_dir / filename
        if destination.exists() or os.path.lexists(destination):
            continue
        payload = source.read_bytes()
        if len(payload) != int(info.st_size):
            continue
        partial = destination.with_name(destination.name + ".partial")
        if partial.exists() or os.path.lexists(partial):
            continue
        with partial.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(partial, destination)
    if destination_dir is not None:
        _fsync_directory(destination_dir)


def _safe_remove_attempt(
    attempt: Path,
    *,
    staging_root: Path,
    expected_identity: tuple[int, int],
) -> None:
    if not os.path.lexists(attempt):
        return
    try:
        resolved_attempt = attempt.resolve(strict=True)
        resolved_staging = staging_root.resolve(strict=True)
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            "qualification staging cleanup target is unresolved"
        ) from error
    _require(
        resolved_attempt.parent == resolved_staging
        and _ATTEMPT_NAME_RE.fullmatch(resolved_attempt.name) is not None
        and stat.S_ISDIR(resolved_attempt.lstat().st_mode)
        and not _is_link_or_reparse(resolved_attempt.lstat()),
        "refusing unsafe qualification staging cleanup",
    )
    arm_id = resolved_attempt.name.rsplit(".", 1)[0]
    if os.name == "posix":
        try:
            with OwnedStagingDirectoryV1.capture(
                resolved_attempt,
                expected_parent=resolved_staging,
                expected_prefix=f"{arm_id}.",
                label=f"qualification staging attempt {arm_id}",
            ) as anchor:
                anchor.seal_tree()
                _require(
                    (anchor.root_snapshot[0], anchor.root_snapshot[1])
                    == expected_identity,
                    "qualification staging attempt inode changed before cleanup",
                )
                _require(
                    _validate_owner_marker(
                        resolved_attempt,
                        filename=_ATTEMPT_OWNER_FILENAME,
                        kind="vast_qualification_pilot_attempt_owner_v2",
                        arm_id=arm_id,
                    )
                    == expected_identity,
                    "qualification staging attempt owner changed before cleanup",
                )
                cleanup_evidence_names = FINAL_NAMESPACE_FILES | {
                    PRODUCTION_ACCEPTANCE_FILENAME,
                    "run_metadata.json",
                    OBSERVED_OPENVINO_DEVICE_PROBE_FILENAME,
                }
                for relative, node in anchor.anchors.items():
                    if relative in {
                        _ATTEMPT_OWNER_FILENAME,
                        ".hardware_resource_samples.host.csv",
                    }:
                        _require(
                            node.kind == "file",
                            "qualification staging contains an unowned attempt entry",
                        )
                        continue
                    if relative == "pilot":
                        _require(
                            node.kind == "directory",
                            "refusing unsafe qualification pilot staging cleanup",
                        )
                        continue
                    _require(
                        relative.startswith("pilot/")
                        and "/" not in relative[len("pilot/") :]
                        and relative[len("pilot/") :] in cleanup_evidence_names
                        and node.kind == "file",
                        "qualification staging contains an unowned evidence entry",
                    )
                anchor.cleanup_after_publication(
                    final_target=resolved_attempt.with_name(
                        f".{resolved_attempt.name}.cleanup-sentinel"
                    )
                )
                return
        except OwnedStagingCleanupV1Error as error:
            raise QualificationPilotExecutorV2Error(
                f"qualification staging cleanup custody failed: {error}"
            ) from error
    _require(
        _validate_owner_marker(
            resolved_attempt,
            filename=_ATTEMPT_OWNER_FILENAME,
            kind="vast_qualification_pilot_attempt_owner_v2",
            arm_id=arm_id,
        )
        == expected_identity,
        "qualification staging attempt inode changed before cleanup",
    )
    allowed_attempt_files = {
        ".hardware_resource_samples.host.csv",
        _ATTEMPT_OWNER_FILENAME,
    }
    for entry in tuple(resolved_attempt.iterdir()):
        info = entry.lstat()
        if entry.name == "pilot":
            _require(
                stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
                "refusing unsafe qualification pilot staging cleanup",
            )
            cleanup_evidence_names = FINAL_NAMESPACE_FILES | {
                PRODUCTION_ACCEPTANCE_FILENAME,
                "run_metadata.json",
                OBSERVED_OPENVINO_DEVICE_PROBE_FILENAME,
            }
            for evidence in tuple(entry.iterdir()):
                evidence_info = evidence.lstat()
                _require(
                    evidence.name in cleanup_evidence_names
                    and stat.S_ISREG(evidence_info.st_mode)
                    and not _is_link_or_reparse(evidence_info)
                    and int(evidence_info.st_nlink) == 1,
                    "qualification staging contains an unowned evidence entry",
                )
                evidence.unlink()
            entry.rmdir()
            continue
        _require(
            entry.name in allowed_attempt_files
            and stat.S_ISREG(info.st_mode)
            and not _is_link_or_reparse(info)
            and int(info.st_nlink) == 1,
            "qualification staging contains an unowned attempt entry",
        )
        entry.unlink()
    resolved_attempt.rmdir()


def _cleanup_staging_root(staging_root: Path) -> None:
    _validate_owner_marker(
        staging_root,
        filename=_STAGING_OWNER_FILENAME,
        kind="vast_qualification_pilot_staging_owner_v2",
    )
    for entry in tuple(staging_root.iterdir()):
        if entry.name == _STAGING_OWNER_FILENAME:
            continue
        _require(
            entry.is_dir() and not entry.is_symlink(),
            "qualification staging root contains an unsafe entry",
        )
        _safe_remove_attempt(
            entry,
            staging_root=staging_root,
            expected_identity=_validate_owner_marker(
                entry,
                filename=_ATTEMPT_OWNER_FILENAME,
                kind="vast_qualification_pilot_attempt_owner_v2",
                arm_id=entry.name.rsplit(".", 1)[0],
            ),
        )


def _refuse_orphaned_staging_state(staging_root: Path) -> None:
    _validate_owner_marker(
        staging_root,
        filename=_STAGING_OWNER_FILENAME,
        kind="vast_qualification_pilot_staging_owner_v2",
    )
    names = {entry.name for entry in staging_root.iterdir()}
    _require(
        names == {_STAGING_OWNER_FILENAME},
        "orphan qualification writer/container state requires explicit recovery",
    )


def _recover_committed_staging_attempts(
    staging_root: Path,
    *,
    root: Path,
    pilot_root: Path,
    cells: Sequence[QualificationPilotCellV2],
    inputs: _QualificationInputs,
    operational: _OperationalInputs,
) -> int:
    """Remove only owner-authenticated attempts whose exact final is complete.

    The executor process lock is already held by the caller.  Reaching the
    final-directory rename also proves that the runtime and collector joined.
    Any attempt retaining evidence or lacking its exact final remains a hard
    orphan refusal; it may still have a live or possibly-successful writer.
    """

    _validate_owner_marker(
        staging_root,
        filename=_STAGING_OWNER_FILENAME,
        kind="vast_qualification_pilot_staging_owner_v2",
    )
    by_arm = {cell.arm_id: cell for cell in cells}
    recoverable: list[tuple[Path, tuple[int, int]]] = []
    for attempt in tuple(staging_root.iterdir()):
        if attempt.name == _STAGING_OWNER_FILENAME:
            continue
        info = attempt.lstat()
        _require(
            stat.S_ISDIR(info.st_mode)
            and not _is_link_or_reparse(info)
            and _ATTEMPT_NAME_RE.fullmatch(attempt.name) is not None,
            "orphan qualification writer/container state requires explicit recovery",
        )
        arm_id = attempt.name.rsplit(".", 1)[0]
        cell = by_arm.get(arm_id)
        _require(
            cell is not None,
            "orphan qualification writer/container state requires explicit recovery",
        )
        identity = _validate_owner_marker(
            attempt,
            filename=_ATTEMPT_OWNER_FILENAME,
            kind="vast_qualification_pilot_attempt_owner_v2",
            arm_id=arm_id,
        )
        _require(
            {entry.name for entry in attempt.iterdir()}
            == {_ATTEMPT_OWNER_FILENAME},
            "orphan qualification writer/container state requires explicit recovery",
        )
        final = _pilot_path(pilot_root, cell)
        _require(
            os.path.lexists(final),
            "orphan qualification writer/container state requires explicit recovery",
        )
        _validate_final_namespace(
            final,
            root=root,
            cell=cell,
            expected_operational_binding=_expected_operational_binding(
                inputs=inputs,
                operational=operational,
                cell=cell,
            ),
        )
        _fsync_directory(final.parent)
        recoverable.append((attempt, identity))
    for attempt, identity in recoverable:
        _safe_remove_attempt(
            attempt,
            staging_root=staging_root,
            expected_identity=identity,
        )
    if recoverable:
        _fsync_directory(staging_root)
    return len(recoverable)


def _remove_empty_staging_root(staging_root: Path) -> None:
    _validate_owner_marker(
        staging_root,
        filename=_STAGING_OWNER_FILENAME,
        kind="vast_qualification_pilot_staging_owner_v2",
    )
    _require(
        {entry.name for entry in staging_root.iterdir()} == {_STAGING_OWNER_FILENAME},
        "qualification staging root is not empty",
    )
    _remove_owner_marker(
        staging_root,
        filename=_STAGING_OWNER_FILENAME,
        kind="vast_qualification_pilot_staging_owner_v2",
    )
    staging_root.rmdir()


def _input_sha256(
    inputs: _QualificationInputs,
    *,
    operational: _OperationalInputs,
) -> dict[str, str]:
    _require(
        inputs.transaction_receipt is not None,
        "qualification input transaction receipt is required",
    )
    _require(
        inputs.hardware_resource_collector is not None,
        "hardware resource collector authority is required",
    )
    result = {
        "candidate_index": inputs.candidate_index.sha256,
        "candidate_manifest": inputs.candidate_manifest.sha256,
        "candidate_receipt": inputs.candidate_receipt.sha256,
        "bootstrap_mapping": inputs.bootstrap_mapping.sha256,
        "bootstrap_receipt": inputs.bootstrap_receipt.sha256,
        "qualification_input_transaction_receipt": (
            inputs.transaction_receipt.sha256
        ),
        "hardware_resource_collector": (
            inputs.hardware_resource_collector.sha256
        ),
        "runtime_input_materialization_receipt": (
            operational.runtime_materialization_receipt.sha256
        ),
        "guardian_service_authority": (
            operational.guardian_service_authority.sha256
        ),
        "guardian_preprocessing_contract": (
            operational.preprocessing_contract.sha256
        ),
        "guardian_preprocessing_contract_receipt": (
            operational.preprocessing_receipt.sha256
        ),
    }
    result.update(
        {
            f"bootstrap_calibration_{system}": inputs.calibrations[system].sha256
            for system in SYSTEMS
        }
    )
    result.update(
        {
            f"native_runtime_bundle_{arm_id}": pin.sha256
            for arm_id, pin in sorted(operational.runtime_bundles.items())
        }
    )
    return result


def _input_identity(
    *,
    root: Path,
    input_sha256: Mapping[str, str],
    pins: Sequence[_PinnedFile],
    code_closure: _ExecutionCodeClosure,
) -> dict[str, Any]:
    by_path: dict[str, dict[str, Any]] = {}
    for pin in pins:
        record = _pin_identity_record(root, pin)
        prior = by_path.setdefault(record["path"], record)
        _require(prior == record, f"conflicting physical pins for {record['path']}")
    return {
        "schema_version": 1,
        "named_sha256": dict(input_sha256),
        "files": [by_path[path] for path in sorted(by_path)],
        "execution_code_closure_receipt_path": (
            code_closure.receipt_pin.path.relative_to(root).as_posix()
        ),
        "execution_code_closure_receipt_sha256": code_closure.receipt[
            "receipt_sha256"
        ],
        "execution_code_source_paths": [
            pin.path.relative_to(root).as_posix()
            for pin in code_closure.source_pins
        ],
        "interpreter": dict(code_closure.interpreter),
    }


def _assert_pilot_anchor(
    anchor: OwnedStagingDirectoryV1 | None, *, final: Path, label: str
) -> None:
    if anchor is None:
        return
    try:
        if Path(os.path.abspath(os.fspath(anchor.path))) == Path(
            os.path.abspath(os.fspath(final))
        ):
            anchor.assert_staging_unchanged()
        else:
            anchor.assert_published_to(final)
    except OwnedStagingCleanupV1Error as error:
        raise QualificationPilotExecutorV2Error(f"{label}: {error}") from error


def _checkpoint_entry(
    *,
    root: Path,
    pilot_root: Path,
    final: Path,
    cell: QualificationPilotCellV2,
    anchor: OwnedStagingDirectoryV1 | None = None,
) -> dict[str, Any]:
    _assert_pilot_anchor(
        anchor, final=final, label=f"{cell.arm_id} pre-checkpoint anchor drifted"
    )
    evidence = {
        name: _descriptor(root, final / name)
        for name in sorted(FINAL_NAMESPACE_FILES)
    }
    result = {
        "system": cell.system,
        "resource": cell.resource,
        "codec": cell.codec,
        "topology_kind": cell.topology_kind,
        "scenario": cell.scenario,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "duration_s": cell.duration_s,
        "run_id": cell.run_id,
        "arm_id": cell.arm_id,
        "pilot_path": final.relative_to(pilot_root).as_posix(),
        "acceptance": evidence[ACCEPTANCE_FILENAME],
        "evidence": evidence,
    }
    _assert_pilot_anchor(
        anchor, final=final, label=f"{cell.arm_id} checkpoint anchor drifted"
    )
    return result


def _adopt_untracked_completed_cells(
    *,
    root: Path,
    pilot_root: Path,
    cells: Sequence[QualificationPilotCellV2],
    completed: list[dict[str, Any]],
    inputs: _QualificationInputs,
    operational: _OperationalInputs,
) -> tuple[bool, tuple[tuple[Path, OwnedStagingDirectoryV1], ...]]:
    adopted = False
    anchors: list[tuple[Path, OwnedStagingDirectoryV1]] = []
    first_missing: int | None = None
    try:
        for position, cell in enumerate(
            cells[len(completed) :], start=len(completed)
        ):
            final = _pilot_path(pilot_root, cell)
            exists = final.exists()
            lexists = os.path.lexists(final)
            _require(
                exists == lexists,
                f"untracked immutable pilot output collision: {cell.arm_id}",
            )
            if not exists:
                first_missing = position
                break
            anchor: OwnedStagingDirectoryV1 | None = None
            if os.name == "posix":
                anchor = OwnedStagingDirectoryV1.capture(
                    final,
                    expected_parent=final.parent,
                    expected_prefix="",
                    label=f"cold qualification pilot {cell.arm_id}",
                )
                anchor.seal_tree()
                anchor.assert_staging_unchanged()
                anchors.append((final, anchor))
            _validate_final_namespace(
                final,
                root=root,
                cell=cell,
                expected_operational_binding=_expected_operational_binding(
                    inputs=inputs, operational=operational, cell=cell
                ),
            )
            completed.append(
                _checkpoint_entry(
                    root=root,
                    pilot_root=pilot_root,
                    final=final,
                    cell=cell,
                    anchor=anchor,
                )
            )
            adopted = True
        if first_missing is not None:
            for cell in cells[first_missing + 1 :]:
                final = _pilot_path(pilot_root, cell)
                _require(
                    not final.exists() and not os.path.lexists(final),
                    "non-prefix untracked pilot output cannot be adopted: "
                    f"{cell.arm_id}",
                )
        return adopted, tuple(anchors)
    except BaseException:
        for _final, anchor in reversed(anchors):
            anchor.close()
        raise


def _run_one_cell(
    *,
    inputs: _QualificationInputs,
    bootstrap_dir: Path,
    pilot_root: Path,
    staging_root: Path,
    cell: QualificationPilotCellV2,
    runtime: RuntimeRunner,
    request_factory: RequestFactory,
    collector_factory: CollectorFactory,
    acceptance_finalizer: AcceptanceFinalizer,
    operational: _OperationalInputs,
    execution_barrier: Callable[[], None],
) -> _CommittedPilotCellV2:
    transaction_receipt = inputs.transaction_receipt
    _require(
        transaction_receipt is not None,
        "qualification input transaction receipt is required",
    )
    final = _pilot_path(pilot_root, cell)
    _require(
        not final.exists() and not os.path.lexists(final),
        f"immutable pilot output collision: {cell.arm_id}",
    )
    attempt = Path(
        tempfile.mkdtemp(prefix=f"{cell.arm_id}.", dir=staging_root)
    )
    attempt_identity = _write_owner_marker(
        attempt,
        filename=_ATTEMPT_OWNER_FILENAME,
        kind="vast_qualification_pilot_attempt_owner_v2",
        arm_id=cell.arm_id,
    )
    output_dir = attempt / "pilot"
    hardware_staging = attempt / ".hardware_resource_samples.host.csv"
    output_dir.mkdir(mode=0o700)
    output_anchor: OwnedStagingDirectoryV1 | None = None
    if os.name == "posix":
        try:
            output_anchor = OwnedStagingDirectoryV1.capture(
                output_dir,
                expected_parent=attempt,
                expected_prefix="",
                label=f"qualification pilot output {cell.arm_id}",
            )
        except OwnedStagingCleanupV1Error as error:
            raise QualificationPilotExecutorV2Error(
                f"qualification pilot output custody failed: {error}"
            ) from error
    collector: _Collector | None = None
    collector_started = False
    collector_stopped = False
    collector_joined = False
    runtime_error: BaseException | None = None
    try:
        request = request_factory(
            inputs=inputs,
            bootstrap_dir=bootstrap_dir,
            cell=cell,
            output_dir=output_dir,
            evidence_names=CHILD_EVIDENCE_FILES,
        )
        contract = _validate_request(
            request, inputs=inputs, cell=cell, output_dir=output_dir
        )
        _require(
            not any(output_dir.iterdir()),
            "request_factory mutated the child evidence namespace",
        )
        collector = collector_factory(hardware_staging, run_id=cell.run_id)
        collector.start()
        collector_started = True
        collector.wait_until_ready(timeout_s=60.0)
        try:
            outcome = runtime(request)
            _require(
                type(outcome) is NativePublicationOutcomeV3
                and outcome.exit_code == 0
                and outcome.blockers == (),
                f"native runtime returned non-success for {cell.arm_id}",
            )
        except BaseException as error:
            runtime_error = error
        finally:
            collector.stop()
            collector_stopped = True
            collector.join(timeout=30.0)
            collector_joined = True
        _require(
            not collector.is_alive(),
            f"hardware collector survived bounded stop for {cell.arm_id}",
        )
        collector.raise_if_failed()
        if runtime_error is not None:
            raise runtime_error
        # Barrier A: runtime and collector are quiescent; no acceptance/final
        # publication may observe code or authority different from the anchor.
        execution_barrier()
        for position, record in enumerate(_socket_records(contract)):
            _validate_live_socket_record(
                record, label=f"{cell.arm_id} post-runtime live socket[{position}]"
            )
        child_names = {entry.name for entry in output_dir.iterdir()}
        _require(
            child_names == set(CHILD_EVIDENCE_FILES),
            f"child evidence namespace drifted for {cell.arm_id}",
        )
        for name in CHILD_EVIDENCE_FILES:
            info = (output_dir / name).lstat()
            _require(
                stat.S_ISREG(info.st_mode)
                and not _is_link_or_reparse(info)
                and int(info.st_nlink) == 1,
                f"child evidence is unsafe for {cell.arm_id}: {name}",
            )
        _validate_pending_candidate(
            output_dir / "checkpoint_publication_candidate.json",
            root=inputs.root,
            cell=cell,
        )
        _require(
            HARDWARE_EVIDENCE_FILENAME not in child_names
            and ACCEPTANCE_FILENAME not in child_names
            and PRODUCTION_ACCEPTANCE_FILENAME not in child_names
            and "run_metadata.json" not in child_names,
            f"child wrote parent/production evidence for {cell.arm_id}",
        )
        try:
            hardware_info = hardware_staging.lstat()
        except OSError as error:
            raise QualificationPilotExecutorV2Error(
                f"host hardware evidence is missing for {cell.arm_id}"
            ) from error
        _require(
            stat.S_ISREG(hardware_info.st_mode)
            and not _is_link_or_reparse(hardware_info)
            and int(hardware_info.st_nlink) == 1
            and int(hardware_info.st_size) > 0,
            f"host hardware evidence is unsafe for {cell.arm_id}",
        )
        _commit_file_noreplace(
            hardware_staging, output_dir / HARDWARE_EVIDENCE_FILENAME
        )
        _require(
            not (output_dir / ACCEPTANCE_FILENAME).exists()
            and not (output_dir / PRODUCTION_ACCEPTANCE_FILENAME).exists(),
            f"acceptance existed before host finalization for {cell.arm_id}",
        )
        acceptance = acceptance_finalizer(
            project_root=inputs.root,
            output_dir=output_dir,
            expected_run_id=cell.run_id,
            expected_arm_id=cell.arm_id,
            expected_system=cell.system,
            expected_resource=cell.resource,
            expected_scenario=cell.scenario,
            expected_codec=cell.codec,
            expected_policy=cell.policy,
            expected_deadline_ms=cell.deadline_ms,
            topology_kind=cell.topology_kind,
            hardware_collector_stopped=True,
            candidate_manifest_path=inputs.candidate_manifest.path,
            candidate_receipt_path=inputs.candidate_receipt.path,
            qualification_index_path=inputs.candidate_index.path,
            bootstrap_mapping_path=inputs.bootstrap_mapping.path,
            bootstrap_calibration_path=inputs.calibrations[cell.system].path,
            bootstrap_receipt_path=inputs.bootstrap_receipt.path,
            qualification_transaction_receipt_path=transaction_receipt.path,
            runtime_input_materialization_receipt_path=(
                operational.runtime_materialization_receipt.path
            ),
            runtime_input_bundle_path=operational.runtime_bundles[
                cell.arm_id
            ].path,
            guardian_service_authority_path=(
                operational.guardian_service_authority.path
            ),
            preprocessing_contract_path=operational.preprocessing_contract.path,
            preprocessing_contract_receipt_path=(
                operational.preprocessing_receipt.path
            ),
        )
        _require(
            type(acceptance) is dict,
            f"qualification finalizer returned invalid data for {cell.arm_id}",
        )
        _validate_final_namespace(
            output_dir,
            root=inputs.root,
            cell=cell,
            expected_operational_binding=_expected_operational_binding(
                inputs=inputs, operational=operational, cell=cell
            ),
        )
        _ensure_final_parent(pilot_root, final)
        _require(
            not final.exists() and not os.path.lexists(final),
            f"immutable pilot output appeared during execution: {cell.arm_id}",
        )
        _durable_directory_tree(output_dir)
        if output_anchor is not None:
            output_anchor.seal_tree()
        # Precommit barrier: final existence must causally prove that every
        # input/code check passed after the finalizer and namespace validation.
        # A process-local late import cannot be forgotten by a fresh restart
        # after an already-published final directory.
        execution_barrier()
        if output_anchor is not None:
            output_anchor.assert_staging_unchanged()
        _rename_directory_noreplace(output_dir, final)
        if output_anchor is not None:
            output_anchor.assert_published_to(final)
        _fsync_directory(final.parent)
        _fsync_directory(attempt)
        # Barrier B: the final namespace is durable, but no checkpoint has yet
        # recorded it.  A contaminated cell must stop in this causal window.
        execution_barrier()
        if output_anchor is not None:
            output_anchor.assert_published_to(final)
        _safe_remove_attempt(
            attempt,
            staging_root=staging_root,
            expected_identity=attempt_identity,
        )
        return _CommittedPilotCellV2(final=final, anchor=output_anchor)
    except BaseException:
        if collector is not None and collector_started and not collector_stopped:
            try:
                collector.stop()
                collector_stopped = True
            except BaseException:
                pass
        if collector is not None and collector_started and not collector_joined:
            try:
                collector.join(timeout=30.0)
                collector_joined = True
            except BaseException:
                pass
        if output_anchor is not None:
            output_anchor.close()
        try:
            _preserve_failed_hardware_samples(
                attempt, pilot_root=pilot_root, cell=cell
            )
        except BaseException:
            pass
        _safe_remove_attempt(
            attempt,
            staging_root=staging_root,
            expected_identity=attempt_identity,
        )
        raise


def _execute_qualification_pilots_v2_locked(
    *,
    project_root: Path | str,
    candidate_index_path: Path | str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_receipt_path: Path | str,
    bootstrap_dir: Path | str,
    transaction_receipt_path: Path | str,
    runtime_input_materialization_receipt_path: Path | str,
    guardian_service_authority_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_contract_receipt_path: Path | str,
    execution_code_closure_receipt_path: Path | str,
    pilot_root: Path | str,
    checkpoint_path: Path | str,
    deadline_ms: int | float = 100,
    duration_s: int = 180,
    runtime_registry: Mapping[str, RuntimeRunner] | None = None,
    request_factory: RequestFactory | None = None,
    collector_factory: CollectorFactory | None = None,
    acceptance_finalizer: AcceptanceFinalizer | None = None,
    service_authority_validator: ServiceAuthorityValidator | None = None,
    preprocessing_contract_loader: PreprocessingContractLoader | None = None,
    runtime_expectations_loader: RuntimeExpectationsLoader | None = None,
) -> dict[str, Any]:
    """Run/resume the exact physical matrix without creating publication authority."""

    cells = qualification_pilot_cells_v2(
        deadline_ms=deadline_ms, duration_s=duration_s
    )
    inputs = _load_qualification_inputs(
        project_root=project_root,
        candidate_index_path=candidate_index_path,
        candidate_manifest_path=candidate_manifest_path,
        candidate_receipt_path=candidate_receipt_path,
        bootstrap_mapping_path=bootstrap_mapping_path,
        bootstrap_receipt_path=bootstrap_receipt_path,
        bootstrap_dir=bootstrap_dir,
        transaction_receipt_path=transaction_receipt_path,
    )
    bootstrap_root = _physical_directory(
        inputs.root, bootstrap_dir, label="bootstrap_dir"
    )
    pilots = _ensure_output_root(inputs.root, pilot_root, label="pilot_root")
    checkpoint = _under_root(inputs.root, checkpoint_path, label="checkpoint")
    checkpoint_parent = (
        inputs.root
        if checkpoint.parent == inputs.root
        else _ensure_output_root(
            inputs.root, checkpoint.parent, label="checkpoint parent"
        )
    )
    checkpoint = checkpoint_parent / checkpoint.name
    _require(
        checkpoint != inputs.root
        and checkpoint != pilots
        and pilots not in checkpoint.parents,
        "checkpoint must be outside the pilot evidence tree",
    )
    _require(
        checkpoint not in {pin.path for pin in inputs.pins}
        and bootstrap_root not in checkpoint.parents,
        "checkpoint may not overwrite qualification/bootstrap inputs",
    )
    code_closure = _load_execution_code_closure(
        root=inputs.root,
        receipt_path=execution_code_closure_receipt_path,
    )
    _require(
        checkpoint not in {pin.path for pin in code_closure.pins},
        "checkpoint may not overwrite execution code closure inputs",
    )
    registry = runtime_registry or NATIVE_RUNTIME_REGISTRY
    _require(
        set(registry) == set(SYSTEMS)
        and all(callable(registry[system]) for system in SYSTEMS),
        "native runtime registry must contain exactly four direct callables",
    )
    operational = _load_operational_inputs(
        inputs=inputs,
        bootstrap_dir=bootstrap_root,
        cells=cells,
        runtime_input_materialization_receipt_path=(
            runtime_input_materialization_receipt_path
        ),
        guardian_service_authority_path=guardian_service_authority_path,
        preprocessing_contract_path=preprocessing_contract_path,
        preprocessing_contract_receipt_path=(
            preprocessing_contract_receipt_path
        ),
        service_authority_validator=(
            service_authority_validator or _default_service_authority_validator
        ),
        preprocessing_contract_loader=(
            preprocessing_contract_loader or _default_preprocessing_contract_loader
        ),
        runtime_expectations_loader=(
            runtime_expectations_loader or _default_runtime_expectations_loader
        ),
    )
    runtime_bundle_pins = operational.runtime_bundles
    if request_factory is None:
        request_builder = partial(
            _request_from_bootstrap_bundle,
            bundle_pins=runtime_bundle_pins,
        )
        for cell in cells:
            preflight_request = request_builder(
                inputs=inputs,
                bootstrap_dir=bootstrap_root,
                cell=cell,
                output_dir=pilots,
                evidence_names=CHILD_EVIDENCE_FILES,
            )
            _validate_request(
                preflight_request,
                inputs=inputs,
                cell=cell,
                output_dir=pilots,
            )
    else:
        request_builder = request_factory
    collector_builder = collector_factory or _default_collector_factory
    finalizer = acceptance_finalizer or _default_acceptance_finalizer
    matrix_sha = _matrix_sha(cells)
    input_hashes = _input_sha256(
        inputs, operational=operational
    )
    execution_pins = (*inputs.pins, *operational.pins, *code_closure.pins)
    input_identity = _input_identity(
        root=inputs.root,
        input_sha256=input_hashes,
        pins=execution_pins,
        code_closure=code_closure,
    )
    checkpoint_preexisted = os.path.lexists(checkpoint)
    completed = _load_checkpoint(
        path=checkpoint,
        matrix_sha256=matrix_sha,
        input_sha256=input_hashes,
        input_identity=input_identity,
        cells=cells,
        root=inputs.root,
        pilot_root=pilots,
        inputs=inputs,
        operational=operational,
    )
    checkpoint_identity: tuple[int, int] | None = None
    if os.path.lexists(checkpoint):
        info = checkpoint.lstat()
        _require(
            stat.S_ISREG(info.st_mode)
            and not _is_link_or_reparse(info)
            and int(info.st_nlink) == 1,
            "qualification execution checkpoint inode is unsafe",
        )
        checkpoint_identity = (int(info.st_dev), int(info.st_ino))
    checkpoint_prefix = tuple(entry["arm_id"] for entry in completed)
    staging_root = pilots / ".qualification-pilot-staging-v2"
    if os.path.lexists(staging_root):
        staging_root = _physical_directory(
            inputs.root, staging_root, label="qualification staging root"
        )
        if checkpoint_preexisted:
            _assert_execution_barrier(
                root=inputs.root, pins=execution_pins, code_closure=code_closure
            )
            _recover_committed_staging_attempts(
                staging_root,
                root=inputs.root,
                pilot_root=pilots,
                cells=cells,
                inputs=inputs,
                operational=operational,
            )
        _refuse_orphaned_staging_state(staging_root)
    if not checkpoint_preexisted:
        for cell in cells:
            final = _pilot_path(pilots, cell)
            _require(
                not final.exists() and not os.path.lexists(final),
                "qualification final exists without an initial anchor checkpoint: "
                f"{cell.arm_id}",
            )
        _assert_execution_barrier(
            root=inputs.root, pins=execution_pins, code_closure=code_closure
        )
        checkpoint_identity = _write_checkpoint(
            checkpoint,
            _checkpoint_payload(
                matrix_sha256=matrix_sha,
                input_sha256=input_hashes,
                input_identity=input_identity,
                completed=[],
            ),
            expected_previous_identity=None,
            expected_completed_prefix=(),
        )
    if not os.path.lexists(staging_root):
        staging_root.mkdir(mode=0o700)
        _write_owner_marker(
            staging_root,
            filename=_STAGING_OWNER_FILENAME,
            kind="vast_qualification_pilot_staging_owner_v2",
        )
    staging_root = _physical_directory(
        inputs.root, staging_root, label="qualification staging root"
    )
    _refuse_orphaned_staging_state(staging_root)
    _assert_execution_barrier(
        root=inputs.root, pins=execution_pins, code_closure=code_closure
    )
    adopted_untracked, adopted_anchors = _adopt_untracked_completed_cells(
        root=inputs.root,
        pilot_root=pilots,
        cells=cells,
        completed=completed,
        inputs=inputs,
        operational=operational,
    )
    if adopted_untracked:
        try:
            _assert_execution_barrier(
                root=inputs.root, pins=execution_pins, code_closure=code_closure
            )
            for final, anchor in adopted_anchors:
                _assert_pilot_anchor(
                    anchor,
                    final=final,
                    label="cold-adopted pilot immediate pre-checkpoint drifted",
                )
            checkpoint_identity = _write_checkpoint(
                checkpoint,
                _checkpoint_payload(
                    matrix_sha256=matrix_sha,
                    input_sha256=input_hashes,
                    input_identity=input_identity,
                    completed=completed,
                ),
                expected_previous_identity=checkpoint_identity,
                expected_completed_prefix=checkpoint_prefix,
            )
            for final, anchor in adopted_anchors:
                _assert_pilot_anchor(
                    anchor,
                    final=final,
                    label="cold-adopted pilot post-checkpoint drifted",
                )
            checkpoint_prefix = tuple(entry["arm_id"] for entry in completed)
        finally:
            for _final, anchor in reversed(adopted_anchors):
                anchor.close()
    completed_ids = {entry["arm_id"] for entry in completed}
    for cell in cells:
        _assert_execution_barrier(
            root=inputs.root, pins=execution_pins, code_closure=code_closure
        )
        final = _pilot_path(pilots, cell)
        if cell.arm_id in completed_ids:
            _validate_final_namespace(
                final,
                root=inputs.root,
                cell=cell,
                expected_operational_binding=_expected_operational_binding(
                    inputs=inputs, operational=operational, cell=cell
                ),
            )
            continue
        _require(
            not final.exists() and not os.path.lexists(final),
            f"untracked immutable pilot output collision: {cell.arm_id}",
        )
        committed_cell = _run_one_cell(
            inputs=inputs,
            bootstrap_dir=bootstrap_root,
            pilot_root=pilots,
            staging_root=staging_root,
            cell=cell,
            runtime=registry[cell.system],
            request_factory=request_builder,
            collector_factory=collector_builder,
            acceptance_finalizer=finalizer,
            operational=operational,
            execution_barrier=partial(
                _assert_execution_barrier,
                root=inputs.root,
                pins=execution_pins,
                code_closure=code_closure,
            ),
        )
        final = committed_cell.final
        try:
            completed.append(
                _checkpoint_entry(
                    root=inputs.root,
                    pilot_root=pilots,
                    final=final,
                    cell=cell,
                    anchor=committed_cell.anchor,
                )
            )
            completed_ids.add(cell.arm_id)
            _assert_pilot_anchor(
                committed_cell.anchor,
                final=final,
                label=f"{cell.arm_id} immediate pre-checkpoint drifted",
            )
            checkpoint_identity = _write_checkpoint(
                checkpoint,
                _checkpoint_payload(
                    matrix_sha256=matrix_sha,
                    input_sha256=input_hashes,
                    input_identity=input_identity,
                    completed=completed,
                ),
                expected_previous_identity=checkpoint_identity,
                expected_completed_prefix=checkpoint_prefix,
            )
            _assert_pilot_anchor(
                committed_cell.anchor,
                final=final,
                label=f"{cell.arm_id} post-checkpoint drifted",
            )
        finally:
            if committed_cell.anchor is not None:
                committed_cell.anchor.close()
        checkpoint_prefix = tuple(entry["arm_id"] for entry in completed)
    _require(len(completed) == 32, "qualification matrix did not close")
    checkpoint_identity = _write_checkpoint(
        checkpoint,
        _checkpoint_payload(
            matrix_sha256=matrix_sha,
            input_sha256=input_hashes,
            input_identity=input_identity,
            completed=completed,
        ),
        expected_previous_identity=checkpoint_identity,
        expected_completed_prefix=checkpoint_prefix,
    )
    _remove_empty_staging_root(staging_root)
    _assert_execution_barrier(
        root=inputs.root, pins=execution_pins, code_closure=code_closure
    )
    return {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "artifact_kind": CHECKPOINT_KIND,
        "status": "completed",
        "completed_cells": 32,
        "pilot_root": pilots,
        "checkpoint_path": checkpoint,
        "publication_ready": False,
        "authorization_eligible": False,
        "blockers": ["qualification_pilots_are_not_full_publication_arms"],
    }


def _cold_validate_pilot_checkpoint(
    *, root: Path, checkpoint_path: Path | str, custody: PhysicalRootCustodyV1
) -> None:
    # The first read only discovers the complete bounded namespace.  No result
    # from it is accepted; every byte is read again inside the mutation watch.
    try:
        _descriptor, discovery_payload = custody.read_descriptor(
            checkpoint_path,
            label="cold qualification checkpoint discovery",
            maximum=1024 * 1024 * 1024,
            capture=True,
        )
    except PublicationPhysicalIoV1Error as error:
        raise QualificationPilotExecutorV2Error(
            f"cold qualification checkpoint custody failed: {error}"
        ) from error
    assert discovery_payload is not None
    try:
        discovery = json.loads(discovery_payload)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise QualificationPilotExecutorV2Error(
            "cold qualification checkpoint is not JSON"
        ) from error
    completed_discovery = discovery.get("completed")
    input_identity = discovery.get("input_identity")
    _require(
        type(discovery) is dict
        and discovery.get("schema_version") == CHECKPOINT_SCHEMA_VERSION
        and type(completed_discovery) is list
        and len(completed_discovery) == 32
        and type(input_identity) is dict
        and type(input_identity.get("files")) is list
        and type(input_identity.get("interpreter")) is dict,
        "cold qualification checkpoint discovery drifted",
    )
    paths: list[str] = [Path(checkpoint_path).relative_to(root).as_posix()]
    identity_by_path: dict[str, Mapping[str, Any]] = {}
    for record in input_identity["files"]:
        _require(type(record) is dict and type(record.get("path")) is str, "cold input identity shape drifted")
        relative = record["path"]
        _require(relative not in identity_by_path, "cold input identity duplicates a path")
        identity_by_path[relative] = record
        paths.append(relative)
    evidence_by_path: dict[str, Mapping[str, Any]] = {}
    for entry in completed_discovery:
        evidence = entry.get("evidence") if type(entry) is dict else None
        _require(type(evidence) is dict, "cold checkpoint evidence coverage drifted")
        for descriptor in evidence.values():
            _require(type(descriptor) is dict and type(descriptor.get("path")) is str, "cold checkpoint evidence descriptor drifted")
            relative = descriptor["path"]
            _require(relative not in evidence_by_path, "cold checkpoint evidence duplicates a path")
            evidence_by_path[relative] = descriptor
            paths.append(relative)
    _require(len(evidence_by_path) == 32 * len(FINAL_NAMESPACE_FILES), "cold checkpoint does not cover all 512 evidence leaves")
    _require(len(paths) == len(set(paths)), "cold validation namespace overlaps unexpectedly")
    watch = None
    try:
        namespace = custody.capture_read_namespace(paths, label="cold qualification namespace")
        epochs = custody.capture_pinned_directory_epochs(label="cold qualification epochs")
        watch = custody.begin_read_namespace_mutation_watch(paths, label="cold qualification mutation watch")
        _assert_external_identity_record(
            input_identity["interpreter"], label="cold qualification Python interpreter"
        )
        _checkpoint_descriptor, payload = custody.read_descriptor(
            checkpoint_path,
            label="cold qualification checkpoint",
            maximum=1024 * 1024 * 1024,
            capture=True,
        )
        assert payload is not None
        checkpoint = json.loads(payload)
        unsigned = {
            key: value for key, value in checkpoint.items() if key != "checkpoint_sha256"
        }
        completed = checkpoint.get("completed")
        _require(
            checkpoint == discovery
            and payload == _canonical_bytes(checkpoint)
            and checkpoint.get("schema_version") == CHECKPOINT_SCHEMA_VERSION
            and checkpoint.get("artifact_kind") == CHECKPOINT_KIND
            and checkpoint.get("status") == "completed"
            and checkpoint.get("checkpoint_sha256") == _canonical_sha(unsigned)
            and type(completed) is list
            and len(completed) == 32,
            "cold qualification checkpoint identity drifted",
        )
        for position, (relative, record) in enumerate(sorted(identity_by_path.items())):
            descriptor, _payload = custody.read_descriptor(
                relative,
                label=f"cold qualification input/code[{position}]",
                maximum=1024 * 1024 * 1024,
            )
            info = (root / relative).lstat()
            _require(
                descriptor
                == {
                    "path": record["path"],
                    "size_bytes": record["size_bytes"],
                    "sha256": record["sha256"],
                }
                and _snapshot_record(_snapshot(info)) == record["snapshot"],
                f"cold qualification input/code drifted: {relative}",
            )
        for position, (relative, descriptor) in enumerate(sorted(evidence_by_path.items())):
            observed, _evidence_payload = custody.read_descriptor(
                relative,
                label=f"cold checkpoint evidence[{position}]",
                maximum=1024 * 1024 * 1024,
            )
            _require(
                observed == descriptor,
                f"cold checkpoint evidence drifted: {relative}",
            )
        _assert_external_identity_record(
            input_identity["interpreter"], label="cold qualification Python interpreter"
        )
        custody.verify_read_namespace(namespace, label="cold qualification namespace")
        custody.verify_pinned_directory_epochs(epochs, label="cold qualification epochs")
        custody.verify_pinned_directory_mutation_watch(
            watch, label="cold qualification mutation watch"
        )
        watch = None
    except PublicationPhysicalIoV1Error as error:
        raise QualificationPilotExecutorV2Error(
            f"cold qualification custody scan failed: {error}"
        ) from error
    finally:
        if watch is not None:
            watch.close()


def _execute_qualification_pilots_v2_entry_held(
    *,
    project_root: Path | str,
    candidate_index_path: Path | str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_receipt_path: Path | str,
    bootstrap_dir: Path | str,
    transaction_receipt_path: Path | str,
    runtime_input_materialization_receipt_path: Path | str,
    guardian_service_authority_path: Path | str,
    preprocessing_contract_path: Path | str,
    preprocessing_contract_receipt_path: Path | str,
    execution_code_closure_receipt_path: Path | str,
    pilot_root: Path | str,
    checkpoint_path: Path | str,
    deadline_ms: int | float = 100,
    duration_s: int = 180,
    runtime_registry: Mapping[str, RuntimeRunner] | None = None,
    request_factory: RequestFactory | None = None,
    collector_factory: CollectorFactory | None = None,
    acceptance_finalizer: AcceptanceFinalizer | None = None,
    service_authority_validator: ServiceAuthorityValidator | None = None,
    preprocessing_contract_loader: PreprocessingContractLoader | None = None,
    runtime_expectations_loader: RuntimeExpectationsLoader | None = None,
) -> dict[str, Any]:
    """Exclusively run/resume the exact nonauthorizing physical pilot matrix."""

    root = _physical_root(project_root)
    pilots = _ensure_output_root(root, pilot_root, label="pilot_root")
    lock_path = pilots / ".qualification-pilot-executor-v2.lock"
    with _exclusive_execution_lock(lock_path):
        return _execute_qualification_pilots_v2_locked(
            project_root=root,
            candidate_index_path=candidate_index_path,
            candidate_manifest_path=candidate_manifest_path,
            candidate_receipt_path=candidate_receipt_path,
            bootstrap_mapping_path=bootstrap_mapping_path,
            bootstrap_receipt_path=bootstrap_receipt_path,
            bootstrap_dir=bootstrap_dir,
            transaction_receipt_path=transaction_receipt_path,
            runtime_input_materialization_receipt_path=(
                runtime_input_materialization_receipt_path
            ),
            guardian_service_authority_path=guardian_service_authority_path,
            preprocessing_contract_path=preprocessing_contract_path,
            preprocessing_contract_receipt_path=(
                preprocessing_contract_receipt_path
            ),
            execution_code_closure_receipt_path=(
                execution_code_closure_receipt_path
            ),
            pilot_root=pilots,
            checkpoint_path=checkpoint_path,
            deadline_ms=deadline_ms,
            duration_s=duration_s,
            runtime_registry=runtime_registry,
            request_factory=request_factory,
            collector_factory=collector_factory,
            acceptance_finalizer=acceptance_finalizer,
            service_authority_validator=service_authority_validator,
            preprocessing_contract_loader=preprocessing_contract_loader,
            runtime_expectations_loader=runtime_expectations_loader,
        )


@wraps(_execute_qualification_pilots_v2_entry_held)
def execute_qualification_pilots_v2(*args: Any, **kwargs: Any) -> dict[str, Any]:
    """Execute with held custody, then cold-load the final checkpoint."""

    _require(not args, "qualification pilot executor accepts keyword arguments only")
    root = _physical_root(kwargs.get("project_root"))
    try:
        with PhysicalRootCustodyV1.open(
            root, label="qualification pilot project_root"
        ) as custody:
            token = _ACTIVE_PHYSICAL_CUSTODY.set(custody)
            try:
                result = _execute_qualification_pilots_v2_entry_held(**kwargs)
                custody.verify()
            finally:
                _ACTIVE_PHYSICAL_CUSTODY.reset(token)
        with PhysicalRootCustodyV1.open(
            root, label="qualification pilot cold project_root"
        ) as cold:
            _cold_validate_pilot_checkpoint(
                root=root,
                checkpoint_path=result["checkpoint_path"],
                custody=cold,
            )
            cold.verify()
        return result
    except QualificationPilotExecutorV2Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        raise QualificationPilotExecutorV2Error(
            f"qualification pilot physical custody failed: {error}"
        ) from error


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--candidate-index", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--bootstrap-mapping", type=Path, required=True)
    parser.add_argument("--bootstrap-receipt", type=Path, required=True)
    parser.add_argument("--bootstrap-dir", type=Path, required=True)
    parser.add_argument(
        "--qualification-transaction-receipt", type=Path, required=True
    )
    parser.add_argument(
        "--runtime-input-materialization-receipt", type=Path, required=True
    )
    parser.add_argument(
        "--guardian-service-authority", type=Path, required=True
    )
    parser.add_argument("--preprocessing-contract", type=Path, required=True)
    parser.add_argument(
        "--preprocessing-contract-receipt", type=Path, required=True
    )
    parser.add_argument(
        "--execution-code-closure-receipt", type=Path, required=True
    )
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--deadline-ms", type=float, default=100.0)
    parser.add_argument("--duration-s", type=int, default=180)
    parser.add_argument("--checkpoint", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    result = execute_qualification_pilots_v2(
        project_root=args.project_root,
        candidate_index_path=args.candidate_index,
        candidate_manifest_path=args.candidate_manifest,
        candidate_receipt_path=args.candidate_receipt,
        bootstrap_mapping_path=args.bootstrap_mapping,
        bootstrap_receipt_path=args.bootstrap_receipt,
        bootstrap_dir=args.bootstrap_dir,
        transaction_receipt_path=args.qualification_transaction_receipt,
        runtime_input_materialization_receipt_path=(
            args.runtime_input_materialization_receipt
        ),
        guardian_service_authority_path=args.guardian_service_authority,
        preprocessing_contract_path=args.preprocessing_contract,
        preprocessing_contract_receipt_path=(
            args.preprocessing_contract_receipt
        ),
        execution_code_closure_receipt_path=(
            args.execution_code_closure_receipt
        ),
        pilot_root=args.pilot_root,
        checkpoint_path=args.checkpoint,
        deadline_ms=args.deadline_ms,
        duration_s=args.duration_s,
    )
    print(
        json.dumps(
            {
                key: str(value) if isinstance(value, Path) else value
                for key, value in result.items()
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACCEPTANCE_FILENAME",
    "BOOTSTRAP_CALIBRATION_FILENAME",
    "CHILD_EVIDENCE_FILES",
    "CODECS",
    "NATIVE_RUNTIME_REGISTRY",
    "POLICY_BY_RESOURCE",
    "QualificationPilotCellV2",
    "QualificationPilotExecutorV2Error",
    "RESOURCES",
    "RUNTIME_INPUT_KEY_BY_SYSTEM",
    "SCENARIO_BY_TOPOLOGY",
    "SYSTEMS",
    "TOPOLOGIES",
    "execute_qualification_pilots_v2",
    "qualification_pilot_cells_v2",
]
