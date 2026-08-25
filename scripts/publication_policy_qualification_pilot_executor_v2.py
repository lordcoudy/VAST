#!/usr/bin/env python3
"""Execute the closed 32-cell native qualification pilot matrix.

This module is deliberately separate from the production launcher and grants.
Its output may qualify policy and full-resource contracts, but it can never be
used as a full-publication arm or authority.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from functools import partial
from pathlib import Path
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
CHILD_EVIDENCE_FILES = (
    *pre_finalization_acceptance_evidence_files("cpu_only"),
    "resource_intervals.csv",
    "fanout_work_counters.csv",
    "checkpoint_publication_candidate.json",
)
FINAL_NAMESPACE_FILES = frozenset(
    (*CHILD_EVIDENCE_FILES, HARDWARE_EVIDENCE_FILENAME, ACCEPTANCE_FILENAME)
)
CHECKPOINT_SCHEMA_VERSION = 2
CHECKPOINT_KIND = "vast_publication_policy_qualification_pilot_execution_v2"
RUNTIME_BUNDLE_KIND = "vast_qualification_native_runtime_input_bundle_v2"
RUNTIME_BUNDLE_SCOPE = "pre_run_policy_and_full_resource_qualification_only"
RUNTIME_BUNDLE_DIRECTORY = "qualification-runtime-inputs-v2"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_NAME_RE = re.compile(
    r"^qualification-arm-v2-"
    r"(?:deepstream|savant|openvino_gva|gstreamer_custom)-"
    r"(?:cpu|gpu)-(?:h264|h265)-"
    r"(?:independent-processes|shared-video-dag)\.[A-Za-z0-9_-]+$"
)
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
class _PinnedJSON:
    path: Path
    snapshot: tuple[int, ...]
    sha256: str
    value: dict[str, Any]


@dataclass(frozen=True)
class _QualificationInputs:
    root: Path
    candidate_index: _PinnedJSON
    candidate_manifest: _PinnedJSON
    candidate_receipt: _PinnedJSON
    bootstrap_mapping: _PinnedJSON
    bootstrap_receipt: _PinnedJSON
    calibrations: Mapping[str, _PinnedJSON]

    @property
    def pins(self) -> tuple[_PinnedJSON, ...]:
        return (
            self.candidate_index,
            self.candidate_manifest,
            self.candidate_receipt,
            self.bootstrap_mapping,
            self.bootstrap_receipt,
            *(self.calibrations[system] for system in SYSTEMS),
        )


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


def _pin_json(root: Path, value: Path | str, *, label: str) -> _PinnedJSON:
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


def _assert_pin_unchanged(pin: _PinnedJSON, *, label: str) -> None:
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


def _descriptor_matches(root: Path, value: Any, pin: _PinnedJSON) -> bool:
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
    _require(
        set(mapping_value) == _BOOTSTRAP_MAPPING_FIELDS
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
    _require(
        set(bootstrap_value) == _BOOTSTRAP_RECEIPT_FIELDS
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
    return _QualificationInputs(
        root=root,
        candidate_index=index,
        candidate_manifest=manifest,
        candidate_receipt=receipt,
        bootstrap_mapping=mapping,
        bootstrap_receipt=bootstrap_receipt,
        calibrations=MappingProxyType(calibrations),
    )


def qualification_pilot_cells_v2(
    *, deadline_ms: int | float = 100, duration_s: int = 180
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
                            deadline_ms=deadline_ms,
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
        and tuple(mapping) == CHILD_EVIDENCE_FILES
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


def _validate_nonauthorizing_acceptance(
    path: Path, *, root: Path, cell: QualificationPilotCellV2
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
        == ["qualification_pilot_is_not_full_publication_arm"],
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
    path: Path, *, root: Path, cell: QualificationPilotCellV2
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
        path / ACCEPTANCE_FILENAME, root=root, cell=cell
    )


def _checkpoint_payload(
    *, matrix_sha256: str, input_sha256: Mapping[str, str], completed: list[dict[str, Any]]
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "artifact_kind": CHECKPOINT_KIND,
        "status": "completed" if len(completed) == 32 else "in_progress",
        "matrix_sha256": matrix_sha256,
        "input_sha256": dict(input_sha256),
        "completed": completed,
        "publication_ready": False,
        "authorization_eligible": False,
        "blockers": ["qualification_pilots_are_not_full_publication_arms"],
    }
    value["checkpoint_sha256"] = _canonical_sha(value)
    return value


def _write_checkpoint(path: Path, value: Mapping[str, Any]) -> None:
    payload = _canonical_bytes(dict(value))
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
        if path.exists():
            info = path.lstat()
            _require(
                stat.S_ISREG(info.st_mode) and not _is_link_or_reparse(info),
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


def _load_checkpoint(
    *,
    path: Path,
    matrix_sha256: str,
    input_sha256: Mapping[str, str],
    cells: Sequence[QualificationPilotCellV2],
    root: Path,
    pilot_root: Path,
) -> list[dict[str, Any]]:
    if not path.exists():
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
        _validate_final_namespace(final, root=root, cell=cell)
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
    final.parent.mkdir(parents=True, exist_ok=True)
    cursor = pilot_root
    for part in final.parent.relative_to(pilot_root).parts:
        cursor = cursor / part
        info = cursor.lstat()
        _require(
            stat.S_ISDIR(info.st_mode) and not _is_link_or_reparse(info),
            "pilot final parent contains a link/reparse point",
        )


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

    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    _require(
        renameat2 is not None,
        "atomic no-replace directory commit is unavailable",
    )
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
    if result != 0:
        error_number = ctypes.get_errno()
        raise QualificationPilotExecutorV2Error(
            "immutable pilot output commit failed without overwrite: "
            f"{os.strerror(error_number)}"
        )


def _commit_file_noreplace(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination, follow_symlinks=False)
        source.unlink()
    except OSError as error:
        raise QualificationPilotExecutorV2Error(
            f"immutable file commit collided: {destination.name}"
        ) from error


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


def _safe_remove_attempt(attempt: Path, *, staging_root: Path) -> None:
    if not attempt.exists():
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
    allowed_attempt_files = {".hardware_resource_samples.host.csv"}
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
    for entry in tuple(staging_root.iterdir()):
        _require(
            entry.is_dir() and not entry.is_symlink(),
            "qualification staging root contains an unsafe entry",
        )
        _safe_remove_attempt(entry, staging_root=staging_root)


def _input_sha256(
    inputs: _QualificationInputs,
    *,
    runtime_bundles: Mapping[str, _PinnedJSON],
) -> dict[str, str]:
    result = {
        "candidate_index": inputs.candidate_index.sha256,
        "candidate_manifest": inputs.candidate_manifest.sha256,
        "candidate_receipt": inputs.candidate_receipt.sha256,
        "bootstrap_mapping": inputs.bootstrap_mapping.sha256,
        "bootstrap_receipt": inputs.bootstrap_receipt.sha256,
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
            for arm_id, pin in sorted(runtime_bundles.items())
        }
    )
    return result


def _checkpoint_entry(
    *, root: Path, pilot_root: Path, final: Path, cell: QualificationPilotCellV2
) -> dict[str, Any]:
    evidence = {
        name: _descriptor(root, final / name)
        for name in sorted(FINAL_NAMESPACE_FILES)
    }
    return {
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


def _adopt_untracked_completed_cells(
    *,
    root: Path,
    pilot_root: Path,
    cells: Sequence[QualificationPilotCellV2],
    completed: list[dict[str, Any]],
) -> bool:
    adopted = False
    first_missing: int | None = None
    for position, cell in enumerate(cells[len(completed) :], start=len(completed)):
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
        _validate_final_namespace(final, root=root, cell=cell)
        completed.append(
            _checkpoint_entry(
                root=root,
                pilot_root=pilot_root,
                final=final,
                cell=cell,
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
    return adopted


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
) -> Path:
    final = _pilot_path(pilot_root, cell)
    _require(
        not final.exists() and not os.path.lexists(final),
        f"immutable pilot output collision: {cell.arm_id}",
    )
    attempt = Path(
        tempfile.mkdtemp(prefix=f"{cell.arm_id}.", dir=staging_root)
    )
    output_dir = attempt / "pilot"
    hardware_staging = attempt / ".hardware_resource_samples.host.csv"
    output_dir.mkdir(mode=0o700)
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
        )
        _require(
            type(acceptance) is dict,
            f"qualification finalizer returned invalid data for {cell.arm_id}",
        )
        _validate_final_namespace(output_dir, root=inputs.root, cell=cell)
        _ensure_final_parent(pilot_root, final)
        _require(
            not final.exists() and not os.path.lexists(final),
            f"immutable pilot output appeared during execution: {cell.arm_id}",
        )
        _rename_directory_noreplace(output_dir, final)
        attempt.rmdir()
        return final
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
        _safe_remove_attempt(attempt, staging_root=staging_root)
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
    pilot_root: Path | str,
    checkpoint_path: Path | str,
    deadline_ms: int | float = 100,
    duration_s: int = 180,
    runtime_registry: Mapping[str, RuntimeRunner] | None = None,
    request_factory: RequestFactory | None = None,
    collector_factory: CollectorFactory | None = None,
    acceptance_finalizer: AcceptanceFinalizer | None = None,
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
    registry = runtime_registry or NATIVE_RUNTIME_REGISTRY
    _require(
        set(registry) == set(SYSTEMS)
        and all(callable(registry[system]) for system in SYSTEMS),
        "native runtime registry must contain exactly four direct callables",
    )
    runtime_bundle_pins: Mapping[str, _PinnedJSON]
    if request_factory is None:
        pinned = {
            cell.arm_id: _pin_json(
                inputs.root,
                _runtime_bundle_path(bootstrap_root, cell),
                label=f"{cell.arm_id} native runtime input bundle",
            )
            for cell in cells
        }
        _require(
            len({(pin.snapshot[0], pin.snapshot[1]) for pin in pinned.values()})
            == 32,
            "native runtime input bundles contain a physical alias",
        )
        runtime_bundle_pins = MappingProxyType(pinned)
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
        runtime_bundle_pins = MappingProxyType({})
        request_builder = request_factory
    collector_builder = collector_factory or _default_collector_factory
    finalizer = acceptance_finalizer or _default_acceptance_finalizer
    matrix_sha = _matrix_sha(cells)
    input_hashes = _input_sha256(
        inputs, runtime_bundles=runtime_bundle_pins
    )
    execution_pins = (*inputs.pins, *runtime_bundle_pins.values())
    completed = _load_checkpoint(
        path=checkpoint,
        matrix_sha256=matrix_sha,
        input_sha256=input_hashes,
        cells=cells,
        root=inputs.root,
        pilot_root=pilots,
    )
    staging_root = pilots / ".qualification-pilot-staging-v2"
    if not staging_root.exists():
        staging_root.mkdir(mode=0o700)
    staging_root = _physical_directory(
        inputs.root, staging_root, label="qualification staging root"
    )
    _cleanup_staging_root(staging_root)
    if _adopt_untracked_completed_cells(
        root=inputs.root,
        pilot_root=pilots,
        cells=cells,
        completed=completed,
    ):
        _write_checkpoint(
            checkpoint,
            _checkpoint_payload(
                matrix_sha256=matrix_sha,
                input_sha256=input_hashes,
                completed=completed,
            ),
        )
    completed_ids = {entry["arm_id"] for entry in completed}
    for cell in cells:
        for pin in execution_pins:
            _assert_pin_unchanged(pin, label=pin.path.name)
        final = _pilot_path(pilots, cell)
        if cell.arm_id in completed_ids:
            _validate_final_namespace(final, root=inputs.root, cell=cell)
            continue
        _require(
            not final.exists() and not os.path.lexists(final),
            f"untracked immutable pilot output collision: {cell.arm_id}",
        )
        final = _run_one_cell(
            inputs=inputs,
            bootstrap_dir=bootstrap_root,
            pilot_root=pilots,
            staging_root=staging_root,
            cell=cell,
            runtime=registry[cell.system],
            request_factory=request_builder,
            collector_factory=collector_builder,
            acceptance_finalizer=finalizer,
        )
        completed.append(
            _checkpoint_entry(
                root=inputs.root,
                pilot_root=pilots,
                final=final,
                cell=cell,
            )
        )
        completed_ids.add(cell.arm_id)
        _write_checkpoint(
            checkpoint,
            _checkpoint_payload(
                matrix_sha256=matrix_sha,
                input_sha256=input_hashes,
                completed=completed,
            ),
        )
    _require(len(completed) == 32, "qualification matrix did not close")
    _write_checkpoint(
        checkpoint,
        _checkpoint_payload(
            matrix_sha256=matrix_sha,
            input_sha256=input_hashes,
            completed=completed,
        ),
    )
    if not any(staging_root.iterdir()):
        staging_root.rmdir()
    for pin in execution_pins:
        _assert_pin_unchanged(pin, label=pin.path.name)
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


def execute_qualification_pilots_v2(
    *,
    project_root: Path | str,
    candidate_index_path: Path | str,
    candidate_manifest_path: Path | str,
    candidate_receipt_path: Path | str,
    bootstrap_mapping_path: Path | str,
    bootstrap_receipt_path: Path | str,
    bootstrap_dir: Path | str,
    pilot_root: Path | str,
    checkpoint_path: Path | str,
    deadline_ms: int | float = 100,
    duration_s: int = 180,
    runtime_registry: Mapping[str, RuntimeRunner] | None = None,
    request_factory: RequestFactory | None = None,
    collector_factory: CollectorFactory | None = None,
    acceptance_finalizer: AcceptanceFinalizer | None = None,
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
            pilot_root=pilots,
            checkpoint_path=checkpoint_path,
            deadline_ms=deadline_ms,
            duration_s=duration_s,
            runtime_registry=runtime_registry,
            request_factory=request_factory,
            collector_factory=collector_factory,
            acceptance_finalizer=acceptance_finalizer,
        )


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--candidate-index", type=Path, required=True)
    parser.add_argument("--candidate-manifest", type=Path, required=True)
    parser.add_argument("--candidate-receipt", type=Path, required=True)
    parser.add_argument("--bootstrap-mapping", type=Path, required=True)
    parser.add_argument("--bootstrap-receipt", type=Path, required=True)
    parser.add_argument("--bootstrap-dir", type=Path, required=True)
    parser.add_argument("--pilot-root", type=Path, required=True)
    parser.add_argument("--deadline-ms", type=float, default=100)
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
