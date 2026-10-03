#!/usr/bin/env python3
"""Materialize real KPP CPU/OpenVINO versus CUDA/TensorRT parity evidence.

This module is intentionally stricter than the read-only parity assessor.  The
frozen requirements manifest is never edited.  Production collection accepts
only the exact physical KPP files and exact protocol-v1 native endpoints.
Injected decoders/runners are confined to a non-publication API whose result
type is rejected by the promotion boundary.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import re
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import time
from collections import defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path, PurePath
from typing import Any

import yaml

from analytics_execution_evidence import (
    EvidenceError,
    persist_execution_bundle,
    verify_execution_bundle,
)
from analytics_execution_protocol import (
    ENGINE_OPENVINO_CPU,
    ENGINE_TENSORRT_CUDA,
    ProtocolError,
    canonical_json_bytes,
    canonical_sha256,
)
from analytics_execution_worker import (
    ExecutionClient,
    validate_inference_response,
    validate_worker_capability,
)
from benchmark_contract import ContractError
from checkpoint_gstreamer_analytics_bridge import preprocess_gstreamer_frame
from checkpoint_gstreamer_analytics_sidecar import (
    DockerWorkerProcessFactory,
    MaterializedBindingSet,
    SidecarError,
    WorkerLaunchSpec,
    _attest_worker_peer_identity,
    _close_owned_socket,
    _complete_peer_identity_after_handshake,
    _open_owned_listener,
    _validate_retired_socket_record_v1,
    load_execution_config,
    load_materialized_binding_set,
)
from checkpoint_model_parity import (
    BRANCHES,
    EVIDENCE_NAMES,
    MIN_CALIBRATION_SAMPLES,
    MIN_PARITY_SAMPLES,
    assess_model_parity,
    load_parity_manifest,
)
from checkpoint_model_parity_acceptance import (
    ModelParityAcceptanceError,
    load_verified_model_parity_acceptance,
    promote_model_parity_acceptance,
)
from publication_guardian_preprocessing_contract_v1 import DirectoryFdCustodyV1
from publication_immutable_directory_v1 import (
    JOURNAL_ROOT,
    commit_or_adopt_immutable_directory_v1,
)
from publication_owned_staging_cleanup_v1 import (
    OwnedStagingCleanupV1Error,
    OwnedStagingDirectoryV1,
    OwnedStagingFileV1,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from kpp_iss_publication_v3_dataset import (
    KppIssPublicationV3DatasetError,
    validate_kpp_iss_publication_v3_manifest_entry,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESOURCES = ("openvino_cpu", "tensorrt_cuda")
RESOURCE_ENGINES = {
    "openvino_cpu": ENGINE_OPENVINO_CPU,
    "tensorrt_cuda": ENGINE_TENSORRT_CUDA,
}
RESOURCE_LABELS = {"openvino_cpu": "cpu", "tensorrt_cuda": "cuda"}
KPP_DATASET_BY_CODEC = {
    "h264": "kpp_iss_publication_v3_h264",
    "h265": "kpp_iss_publication_v3_h265",
}
KPP_PUBLICATION_GENERATION_ID = "kpp_iss_publication_v3"
KPP_PUBLICATION_SCOPE = "performance_and_topology_benchmark_results_only"
KPP_PUBLICATION_MANIFEST_SHA256 = (
    "bbe2cca51cdcc95651492e0f28fc95ed00b9106dce73b5995280259701c91cc2"
)
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_STABLE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,160}$")
_EXTERNAL_WORKER_SOCKET_ROOT = Path("/var/tmp")
_FORBIDDEN_PRODUCTION_TOKENS = (
    "mock",
    "synthetic",
    "fake",
    "stub",
    "nonpublication",
    "non-publication",
    "dry_run",
    "dry-run",
)
_PRODUCTION_TOKEN = object()
_VALIDATED_RESPONSE_TOKEN = object()


class MaterializerError(RuntimeError):
    """A production materialization input or transaction failed closed."""


@dataclass(frozen=True)
class FrozenKppFile:
    relative_path: str
    sha256: str
    file_id: str
    codec: str | None
    container: str
    width: int | None = None
    height: int | None = None


FROZEN_KPP_FILES = (
    FrozenKppFile(
        "data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_underbody.mp4",
        "b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102",
        "kpp-iss-publication-v3-h264-underbody",
        "h264",
        "mp4",
        1700,
        236,
    ),
    FrozenKppFile(
        "data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_front_gate.mp4",
        "08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273",
        "kpp-iss-publication-v3-h264-front-gate",
        "h264",
        "mp4",
        1920,
        1080,
    ),
    FrozenKppFile(
        "data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_underbody.mp4",
        "5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839",
        "kpp-iss-publication-v3-h265-underbody",
        "h265",
        "mp4",
        1700,
        236,
    ),
    FrozenKppFile(
        "data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_front_gate.mp4",
        "fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728",
        "kpp-iss-publication-v3-h265-front-gate",
        "h265",
        "mp4",
        1920,
        1080,
    ),
    FrozenKppFile(
        "data/videos/kpp/kpp_iss_publication_v3/receipts/iss_v2_underbody_metadata.json",
        "d23872d4b4706ef7d804f917a72407f82326eb3cdd5d39d347913f20cc65b0d4",
        "kpp-iss-publication-v3-underbody-metadata",
        None,
        "json",
    ),
)
_FROZEN_BY_PATH = {item.relative_path: item for item in FROZEN_KPP_FILES}


@dataclass(frozen=True)
class PhysicalFileRecord:
    path: Path
    relative_path: str
    sha256: str
    size_bytes: int
    identity: tuple[int, int, int, int, int, int]


@dataclass(frozen=True)
class SamplePlan:
    branch: str
    role: str
    codec: str
    relative_path: str
    stream_index: int
    frame_index: int
    sample_id: str


@dataclass(frozen=True)
class DecodedFrame:
    plan: SamplePlan
    observed_frame_index: int
    pts_ns: int
    width: int
    height: int
    stride: int
    rgb: bytes


class ValidatedNativeResponse:
    """Response wrapper constructible only after protocol validation."""

    __slots__ = ("request", "response", "capability", "output")

    def __init__(
        self,
        token: object | None = None,
        *,
        request: Mapping[str, Any] | None = None,
        response: Mapping[str, Any] | None = None,
        capability: Mapping[str, Any] | None = None,
        output: bytes | None = None,
    ) -> None:
        if token is not _VALIDATED_RESPONSE_TOKEN:
            raise TypeError("ValidatedNativeResponse is internal to protocol validation")
        self.request = dict(request or {})
        self.response = dict(response or {})
        self.capability = dict(capability or {})
        self.output = bytes(output or b"")


class _ExecutionBundleLedger:
    """Persist and index one immutable native bundle per sample/resource cell."""

    def __init__(
        self,
        *,
        project_root: Path,
        staging_root: Path,
        final_root: Path,
        expected_coordinates: Iterable[tuple[str, str, str, str, str]],
    ) -> None:
        self._project_root = Path(project_root)
        self._staging_root = Path(staging_root)
        self._final_root = Path(final_root)
        try:
            self._final_root.relative_to(self._project_root)
        except ValueError as error:
            raise MaterializerError(
                "execution bundle final root escaped project_root"
            ) from error
        expected = frozenset(expected_coordinates)
        _require(expected, "execution bundle expected coverage is empty")
        _require(
            all(
                type(value) is str and value
                for coordinate in expected
                for value in coordinate
            ),
            "execution bundle expected coordinate is invalid",
        )
        _require(
            all(coordinate[4] in RESOURCES for coordinate in expected),
            "execution bundle expected resource is invalid",
        )
        self._expected = expected
        self._observed: set[tuple[str, str, str, str, str]] = set()
        self._rows: list[dict[str, Any]] = []
        self._finalized = False

    def persist(
        self,
        *,
        branch: str,
        role: str,
        codec: str,
        sample_id: str,
        resource: str,
        response: ValidatedNativeResponse,
        input_tensor: bytes,
    ) -> None:
        coordinate = (branch, role, codec, sample_id, resource)
        _require(
            coordinate in self._expected,
            "execution bundle coordinate is not in the frozen sample plan",
        )
        _require(
            coordinate not in self._observed,
            "duplicate execution bundle coordinate",
        )
        _require(not self._finalized, "execution bundle ledger is finalized")
        _require(
            type(response) is ValidatedNativeResponse,
            "execution bundle requires a protocol-validated response",
        )
        request_id = response.request.get("request_id")
        _require(
            type(request_id) is str
            and _STABLE_ID_RE.fullmatch(request_id) is not None
            and Path(request_id).name == request_id,
            "execution bundle request ID is invalid",
        )
        bundle_root = self._staging_root / "execution_bundles"
        try:
            manifest = persist_execution_bundle(
                bundle_root,
                request=response.request,
                response=response.response,
                input_tensor=input_tensor,
                output_tensor=response.output,
                capability=response.capability,
                project_root=self._project_root,
            )
            verified = verify_execution_bundle(
                bundle_root / request_id,
                capability=response.capability,
            )
        except (EvidenceError, ProtocolError) as error:
            raise MaterializerError(
                f"native execution evidence persistence failed: {error}"
            ) from error
        _require(verified == manifest, "execution bundle verification drifted")
        _require(
            manifest.get("request_id") == request_id,
            "execution bundle manifest request binding drifted",
        )
        files = manifest.get("files")
        identity = manifest.get("identity")
        _require(
            isinstance(files, Mapping)
            and set(files)
            == {"request", "response", "input_tensor", "output_tensor"}
            and isinstance(identity, Mapping)
            and _SHA256_RE.fullmatch(str(identity.get("sha256", ""))) is not None,
            "execution bundle manifest inventory is invalid",
        )
        for label in ("request", "response", "input_tensor", "output_tensor"):
            record = files[label]
            _require(
                isinstance(record, Mapping)
                and _SHA256_RE.fullmatch(str(record.get("sha256", ""))) is not None,
                f"execution bundle {label} identity is invalid",
            )
        manifest_payload = _canonical_json(manifest) + b"\n"
        manifest_path = bundle_root / request_id / "manifest.json"
        _require(
            manifest_path.read_bytes() == manifest_payload,
            "execution bundle manifest bytes drifted after verification",
        )
        final_manifest = self._final_root / "execution_bundles" / request_id / "manifest.json"
        self._rows.append(
            {
                "branch": branch,
                "role": role,
                "codec": codec,
                "sample_id": sample_id,
                "resource": resource,
                "request_id": request_id,
                "manifest": {
                    "path": final_manifest.relative_to(self._project_root).as_posix(),
                    "sha256": _sha256_bytes(manifest_payload),
                    "size_bytes": len(manifest_payload),
                },
                "manifest_identity_sha256": identity["sha256"],
                "request_sha256": files["request"]["sha256"],
                "response_sha256": files["response"]["sha256"],
                "input_tensor_sha256": files["input_tensor"]["sha256"],
                "output_tensor_sha256": files["output_tensor"]["sha256"],
            }
        )
        self._observed.add(coordinate)

    def finalize(self) -> tuple[dict[str, Any], ...]:
        missing = self._expected - self._observed
        extra = self._observed - self._expected
        _require(
            not missing and not extra,
            "execution bundle physical coverage is incomplete",
        )
        _require(
            len({row["request_id"] for row in self._rows}) == len(self._rows),
            "execution bundle request ID coverage is not unique",
        )
        self._finalized = True
        return tuple(copy.deepcopy(self._rows))


@dataclass(frozen=True)
class NonPublicationCollection:
    claim_status: str = "injected_test_evidence_nonpublication"
    record_count: int = 0


class ProductionCollection:
    """Opaque transaction handed from the collector to the promoter."""

    __slots__ = (
        "_token",
        "project_root",
        "materialization_dir",
        "base_manifest_record",
        "base_manifest",
        "evidence_refs",
        "promoted_manifest",
        "transaction_index_record",
    )

    def __init__(
        self,
        token: object | None = None,
        *,
        project_root: Path | None = None,
        materialization_dir: Path | None = None,
        base_manifest_record: PhysicalFileRecord | None = None,
        base_manifest: Mapping[str, Any] | None = None,
        evidence_refs: Mapping[tuple[str, str], Mapping[str, str]] | None = None,
        promoted_manifest: Mapping[str, Any] | None = None,
        transaction_index_record: PhysicalFileRecord | None = None,
    ) -> None:
        if token is not _PRODUCTION_TOKEN:
            raise TypeError("ProductionCollection is internal to real production collection")
        self._token = token
        self.project_root = Path(project_root or ".")
        self.materialization_dir = Path(materialization_dir or ".")
        self.base_manifest_record = base_manifest_record
        self.base_manifest = dict(base_manifest or {})
        self.evidence_refs = {
            key: dict(value) for key, value in (evidence_refs or {}).items()
        }
        self.promoted_manifest = dict(promoted_manifest or {})
        self.transaction_index_record = transaction_index_record


@dataclass(frozen=True)
class PromotionResult:
    accepted_manifest: PhysicalFileRecord
    assessment: Mapping[str, Any]
    parity_acceptance: Mapping[str, Any] | None = None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise MaterializerError(message)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise MaterializerError(f"value is not canonical JSON: {error}") from error


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    junction = getattr(os.path, "isjunction", lambda _path: False)
    if junction(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(
        attributes
        & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    )


def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(stat.S_IFMT(value.st_mode)),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_nlink),
    )


def _physical_root(project_root: Path | str) -> Path:
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    _require(lexical.is_dir(), "project_root is missing or not a directory")
    _require(not _is_reparse(lexical), "project_root is a symlink/reparse point")
    _require(lexical.resolve() == lexical, "project_root is an alias")
    _require(lexical != Path(lexical.anchor), "project_root cannot be a filesystem root")
    return lexical


def _assert_chain(root: Path, path: Path, *, label: str) -> None:
    _require(path == root or root in path.parents, f"{label} escaped project_root")
    cursor = root
    for part in path.relative_to(root).parts:
        cursor = cursor / part
        if cursor.exists() or os.path.lexists(cursor):
            _require(
                not _is_reparse(cursor),
                f"{label} path contains a symlink/reparse point",
            )


def _read_physical_file(
    root: Path,
    relative_path: str | Path,
    *,
    expected_sha256: str | None,
    expected_size: int | None,
    label: str,
    absolute_allowed: bool = False,
) -> tuple[PhysicalFileRecord, bytes]:
    raw = Path(relative_path)
    if raw.is_absolute():
        _require(absolute_allowed, f"{label} must be project-relative")
        candidate = Path(os.path.abspath(os.fspath(raw)))
    else:
        _require(
            raw.parts
            and ".." not in raw.parts
            and "." not in raw.parts,
            f"{label} path is unsafe",
        )
        candidate = Path(os.path.abspath(os.fspath(root / raw)))
    if not absolute_allowed:
        _assert_chain(root, candidate, label=label)
    else:
        _require(candidate != Path(candidate.anchor), f"{label} cannot be a root")
        cursor = candidate
        while cursor != Path(cursor.anchor):
            if cursor.exists() or os.path.lexists(cursor):
                _require(not _is_reparse(cursor), f"{label} contains a symlink/reparse point")
            cursor = cursor.parent
    _require(candidate.exists(), f"{label} is missing: {candidate}")
    _require(candidate.resolve() == candidate, f"{label} is an alias")
    _require(not _is_reparse(candidate), f"{label} is a symlink/reparse point")
    before = candidate.lstat()
    _require(stat.S_ISREG(before.st_mode), f"{label} is not a regular file")
    _require(int(before.st_nlink) == 1, f"{label} is a hardlink")
    flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    try:
        descriptor = os.open(candidate, flags)
    except OSError as error:
        raise MaterializerError(f"cannot open {label}: {error}") from error
    try:
        opened = os.fstat(descriptor)
        _require(
            _stat_identity(opened) == _stat_identity(before),
            f"{label} changed while opening",
        )
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    after = candidate.lstat()
    identity = _stat_identity(before)
    _require(
        identity == _stat_identity(after_fd) == _stat_identity(after),
        f"{label} changed during read",
    )
    payload = b"".join(chunks)
    digest = _sha256_bytes(payload)
    _require(len(payload) == int(before.st_size), f"{label} byte length changed")
    if expected_sha256 is not None:
        _require(
            _SHA256_RE.fullmatch(expected_sha256) is not None,
            f"{label} expected SHA-256 is invalid",
        )
        _require(digest == expected_sha256, f"{label} SHA-256 mismatch")
    if expected_size is not None:
        _require(len(payload) == expected_size, f"{label} size mismatch")
    relative = (
        candidate.relative_to(root).as_posix()
        if candidate == root or root in candidate.parents
        else str(candidate)
    )
    return (
        PhysicalFileRecord(
            path=candidate,
            relative_path=relative,
            sha256=digest,
            size_bytes=len(payload),
            identity=identity,
        ),
        payload,
    )


def verify_physical_file(
    project_root: Path | str,
    relative_path: str | Path,
    *,
    expected_sha256: str,
    label: str,
    expected_size: int | None = None,
) -> PhysicalFileRecord:
    root = _physical_root(project_root)
    record, _ = _read_physical_file(
        root,
        relative_path,
        expected_sha256=expected_sha256,
        expected_size=expected_size,
        label=label,
    )
    return record


def build_deterministic_sample_plan() -> tuple[SamplePlan, ...]:
    """Return 30 H264/H265-balanced calibration and evaluation rows per branch."""

    rows: list[SamplePlan] = []
    for branch_index, branch in enumerate(BRANCHES):
        for role_index, role in enumerate(("calibration", "evaluation")):
            for codec_index, codec in enumerate(("h264", "h265")):
                for index in range(15):
                    recording = 1 if (index + branch_index + role_index) % 3 == 0 else 2
                    frame_index = (
                        97
                        + branch_index * 8_000
                        + role_index * 4_000
                        + codec_index * 1_000
                        + index * 37
                    )
                    rows.append(
                        SamplePlan(
                            branch=branch,
                            role=role,
                            codec=codec,
                            relative_path=(
                                "data/videos/kpp/kpp_iss_publication_v3/"
                                f"{codec}/iss_v2_"
                                + ("underbody.mp4" if recording == 1 else "front_gate.mp4")
                            ),
                            stream_index=0,
                            frame_index=frame_index,
                            sample_id=(
                                f"mp.{branch}.{role}.{codec}.{index:02d}"
                            ),
                        )
                    )
    _require(
        len(rows)
        == len(BRANCHES)
        * (MIN_CALIBRATION_SAMPLES + MIN_PARITY_SAMPLES),
        "deterministic parity sample plan cardinality drifted",
    )
    return tuple(rows)


def collect_nonpublication_test_evidence(
    *,
    decoder: Callable[..., Any],
    runner: Callable[..., Any],
) -> NonPublicationCollection:
    """Return an explicitly non-promotable marker for injected unit fixtures."""

    _require(callable(decoder) and callable(runner), "test injections must be callable")
    return NonPublicationCollection()


def native_service_time_ms(value: ValidatedNativeResponse) -> float:
    if type(value) is not ValidatedNativeResponse:
        raise TypeError("native_service_time_ms requires ValidatedNativeResponse")
    timing = value.response["timing"]
    started = timing["inference_started_monotonic_ns"]
    finished = timing["inference_finished_monotonic_ns"]
    latency = timing["inference_latency_ns"]
    _require(
        type(started) is int
        and type(finished) is int
        and type(latency) is int
        and started < finished
        and latency == finished - started,
        "validated native timing drifted",
    )
    result = latency / 1_000_000.0
    _require(math.isfinite(result) and result > 0.0, "native service time is invalid")
    return result


def decode_validated_fp32_output(
    payload: bytes | bytearray | memoryview,
    *,
    expected_values: int,
) -> list[float]:
    value = bytes(payload)
    _require(
        type(expected_values) is int and expected_values > 0,
        "expected output value count is invalid",
    )
    _require(
        len(value) == expected_values * 4,
        "native output byte length is partial or drifted",
    )
    try:
        result = list(struct.unpack(f"<{expected_values}f", value))
    except struct.error as error:
        raise MaterializerError(f"native output cannot be decoded: {error}") from error
    _require(all(math.isfinite(item) for item in result), "native output contains non-finite values")
    return result


def build_promoted_manifest(
    base_manifest: Mapping[str, Any],
    *,
    evidence_refs: Mapping[tuple[str, str], Mapping[str, str]],
) -> dict[str, Any]:
    expected = {(branch, name) for branch in BRANCHES for name in EVIDENCE_NAMES}
    _require(set(evidence_refs) == expected, "promoted evidence reference coverage is not exact 32")
    result = json.loads(_canonical_json(base_manifest).decode("utf-8"))
    _require("identity" not in result, "base manifest copy must not contain derived identity")
    for branch in BRANCHES:
        evidence = result["workload_slots"][branch]["evidence"]
        _require(set(evidence) == set(EVIDENCE_NAMES), f"{branch} evidence fields drifted")
        for name in EVIDENCE_NAMES:
            reference = dict(evidence_refs[(branch, name)])
            _require(set(reference) == {"path", "sha256"}, "evidence reference fields drifted")
            path = reference["path"]
            digest = reference["sha256"]
            _require(
                type(path) is str
                and path
                and not Path(path).is_absolute()
                and ".." not in Path(path).parts
                and ".staging" not in path,
                "promoted evidence reference is not a final project-relative path",
            )
            _require(
                type(digest) is str and _SHA256_RE.fullmatch(digest) is not None,
                "promoted evidence reference SHA-256 is invalid",
            )
            evidence[name] = reference
    return result


def _validate_production_label(value: Any, *, label: str) -> str:
    result = str(value or "")
    lowered = result.lower()
    _require(
        result and not any(token in lowered for token in _FORBIDDEN_PRODUCTION_TOKENS),
        f"{label} is mock/synthetic/nonpublication",
    )
    return result


def _safe_output_path(
    root: Path,
    value: Path | str,
    *,
    label: str,
    must_not_exist: bool,
) -> Path:
    candidate = Path(os.path.abspath(os.fspath(value)))
    _require(candidate != root, f"{label} cannot equal project_root")
    _assert_chain(root, candidate, label=label)
    if must_not_exist:
        _require(
            not candidate.exists() and not os.path.lexists(candidate),
            f"{label} already exists or is unsafe: {candidate}",
        )
    return candidate


def _physical_directory(path: Path | str, *, label: str) -> Path:
    candidate = Path(os.path.abspath(os.fspath(path)))
    _require(candidate.is_dir(), f"{label} is missing or not a directory")
    _require(candidate.resolve() == candidate, f"{label} is an alias")
    _require(not _is_reparse(candidate), f"{label} is a symlink/reparse point")
    return candidate


def _external_worker_socket_identity(
    path: Path,
    *,
    phase: str,
    expected_identity: tuple[int, int] | None = None,
) -> tuple[int, int]:
    _require(
        os.name == "posix"
        and hasattr(os, "getuid")
        and hasattr(os, "getgid")
        and hasattr(os, "O_DIRECTORY")
        and hasattr(os, "O_NOFOLLOW"),
        "external worker socket namespace requires physical POSIX semantics",
    )
    flags = (
        os.O_RDONLY
        | int(getattr(os, "O_CLOEXEC", 0))
        | int(os.O_DIRECTORY)
        | int(os.O_NOFOLLOW)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise MaterializerError(
            f"external worker socket namespace is not a safe directory during {phase}: {error}"
        ) from error
    try:
        metadata = os.fstat(descriptor)
        identity = (int(metadata.st_dev), int(metadata.st_ino))
        _require(
            stat.S_ISDIR(metadata.st_mode),
            f"external worker socket namespace is not a directory during {phase}",
        )
        _require(
            (int(metadata.st_uid), int(metadata.st_gid))
            == (int(os.getuid()), int(os.getgid())),
            "external worker socket namespace must be owned by current uid/gid",
        )
        _require(
            stat.S_IMODE(metadata.st_mode) == 0o700,
            "external worker socket namespace mode must be 0700",
        )
        if expected_identity is not None:
            _require(
                identity == expected_identity,
                "external worker socket namespace inode identity changed",
            )
        try:
            entries = os.listdir(descriptor)
        except OSError as error:
            raise MaterializerError(
                f"external worker socket namespace cannot be listed during {phase}: {error}"
            ) from error
        _require(
            not entries,
            f"external worker socket namespace must be empty {phase}",
        )
        after = os.fstat(descriptor)
        _require(
            (
                int(after.st_dev),
                int(after.st_ino),
                int(after.st_uid),
                int(after.st_gid),
                stat.S_IMODE(after.st_mode),
            )
            == (
                identity[0],
                identity[1],
                int(metadata.st_uid),
                int(metadata.st_gid),
                stat.S_IMODE(metadata.st_mode),
            ),
            "external worker socket namespace metadata changed during validation",
        )
        try:
            path_metadata = path.lstat()
        except OSError as error:
            raise MaterializerError(
                f"external worker socket namespace path disappeared during {phase}: {error}"
            ) from error
        _require(
            not stat.S_ISLNK(path_metadata.st_mode)
            and stat.S_ISDIR(path_metadata.st_mode),
            f"external worker socket namespace became a symlink during {phase}",
        )
        _require(
            (int(path_metadata.st_dev), int(path_metadata.st_ino)) == identity,
            "external worker socket namespace inode identity changed",
        )
        _require(
            path.resolve(strict=True) == path,
            f"external worker socket namespace became an alias during {phase}",
        )
        return identity
    finally:
        os.close(descriptor)


@dataclass(frozen=True)
class _WorkerSocketNamespaceContract:
    path: Path
    external: bool
    _identity: tuple[int, int] | None

    def lifecycle(self) -> "_WorkerSocketNamespaceLifecycle":
        return _WorkerSocketNamespaceLifecycle(self)

    def _validate(self, *, phase: str) -> None:
        if self.external:
            _external_worker_socket_identity(
                self.path,
                phase=phase,
                expected_identity=self._identity,
            )


class _WorkerSocketNamespaceLifecycle:
    def __init__(self, contract: _WorkerSocketNamespaceContract) -> None:
        self._contract = contract

    def __enter__(self) -> Path:
        self._contract._validate(phase="before worker lifecycle")
        return self._contract.path

    def __exit__(self, *_args: object) -> None:
        self._contract._validate(phase="after worker lifecycle")


def _worker_socket_namespace_contract(
    project_root: Path | str,
    socket_dir: Path | str,
) -> _WorkerSocketNamespaceContract:
    root = _physical_directory(project_root, label="analytics worker project root")
    candidate = _physical_directory(
        socket_dir, label="analytics worker socket directory"
    )
    _require(candidate != root, "worker socket directory cannot equal project_root")
    if root in candidate.parents:
        return _WorkerSocketNamespaceContract(
            path=candidate,
            external=False,
            _identity=None,
        )

    _require(
        os.name == "posix",
        "external worker socket namespace requires physical POSIX semantics",
    )
    external_root = _physical_directory(
        _EXTERNAL_WORKER_SOCKET_ROOT,
        label="external worker socket namespace root",
    )
    _require(
        candidate.parent == external_root
        and candidate.name.startswith("vast-")
        and len(candidate.name) > len("vast-")
        and _STABLE_ID_RE.fullmatch(candidate.name) is not None,
        "external worker socket directory must be an exact /var/tmp/vast-* namespace",
    )
    identity = _external_worker_socket_identity(
        candidate,
        phase="before lifecycle",
    )
    return _WorkerSocketNamespaceContract(
        path=candidate,
        external=True,
        _identity=identity,
    )


def _project_relative(root: Path, path: Path | str, *, label: str) -> Path:
    raw = Path(path)
    candidate = Path(
        os.path.abspath(os.fspath(raw if raw.is_absolute() else root / raw))
    )
    _assert_chain(root, candidate, label=label)
    _require(candidate != root, f"{label} cannot equal project_root")
    return candidate.relative_to(root)


def _create_physical_directory_chain(root: Path, target: Path) -> None:
    _assert_chain(root, target, label="materialization parent")
    cursor = root
    for part in target.relative_to(root).parts:
        cursor = cursor / part
        if not cursor.exists() and not os.path.lexists(cursor):
            cursor.mkdir()
        _require(cursor.is_dir(), f"output component is not a directory: {cursor}")
        _require(not _is_reparse(cursor), f"output component is a reparse point: {cursor}")
        _require(cursor.resolve() == cursor, f"output component is an alias: {cursor}")


def _final_reference(
    root: Path,
    record: PhysicalFileRecord,
    *,
    staging_root: Path,
    final_root: Path,
    sized: bool = False,
) -> dict[str, Any]:
    _require(staging_root in record.path.parents, "staged artifact escaped transaction")
    final_path = final_root / record.path.relative_to(staging_root)
    result: dict[str, Any] = {
        "path": final_path.relative_to(root).as_posix(),
        "sha256": record.sha256,
    }
    if sized:
        result["size_bytes"] = record.size_bytes
    return result


def _write_new_file(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o444,
) -> PhysicalFileRecord:
    _require(path.parent.is_dir(), f"output parent is missing: {path.parent}")
    _require(
        not path.exists() and not os.path.lexists(path),
        f"output file collision: {path}",
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(getattr(os, "O_CLOEXEC", 0))
    descriptor = os.open(path, flags, 0o600)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            _require(written > 0, f"short write: {path}")
            offset += written
        os.fsync(descriptor)
        metadata = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    path.chmod(mode)
    after = path.lstat()
    _require(
        (
            int(metadata.st_dev),
            int(metadata.st_ino),
            int(metadata.st_size),
            int(metadata.st_mtime_ns),
            int(metadata.st_nlink),
        )
        == (
            int(after.st_dev),
            int(after.st_ino),
            int(after.st_size),
            int(after.st_mtime_ns),
            int(after.st_nlink),
        ),
        f"output changed after write: {path}",
    )
    return PhysicalFileRecord(
        path=path,
        relative_path=path.name,
        sha256=_sha256_bytes(payload),
        size_bytes=len(payload),
        identity=_stat_identity(after),
    )


def _write_json_file(path: Path, value: Mapping[str, Any]) -> PhysicalFileRecord:
    return _write_new_file(path, _canonical_json(dict(value)) + b"\n")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | int(getattr(os, "O_DIRECTORY", 0))
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _relative_reference(root: Path, record: PhysicalFileRecord) -> dict[str, Any]:
    _require(root in record.path.parents, "artifact reference escaped project_root")
    return {
        "path": record.path.relative_to(root).as_posix(),
        "sha256": record.sha256,
    }


def _sized_reference(root: Path, record: PhysicalFileRecord) -> dict[str, Any]:
    return {**_relative_reference(root, record), "size_bytes": record.size_bytes}


class _BundleWriter:
    """Exclusive append-only bundle writer with per-segment and whole-file SHA."""

    def __init__(self, path: Path) -> None:
        _require(path.parent.is_dir(), f"bundle parent is missing: {path.parent}")
        _require(
            not path.exists() and not os.path.lexists(path),
            f"bundle collision: {path}",
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | int(
            getattr(os, "O_CLOEXEC", 0)
        )
        self.path = path
        self._fd = os.open(path, flags, 0o600)
        self._digest = hashlib.sha256()
        self._size = 0
        self._closed = False

    def append(self, payload: bytes | bytearray | memoryview) -> dict[str, Any]:
        _require(not self._closed, "bundle writer is closed")
        value = bytes(payload)
        _require(value, "bundle segment cannot be empty")
        start = self._size
        offset = 0
        while offset < len(value):
            written = os.write(self._fd, value[offset:])
            _require(written > 0, f"bundle short write: {self.path}")
            offset += written
        self._digest.update(value)
        self._size += len(value)
        return {
            "offset_bytes": start,
            "length_bytes": len(value),
            "segment_sha256": _sha256_bytes(value),
        }

    def close(self) -> PhysicalFileRecord:
        _require(not self._closed, "bundle writer is already closed")
        os.fsync(self._fd)
        before = os.fstat(self._fd)
        os.close(self._fd)
        self._closed = True
        self.path.chmod(0o444)
        after = self.path.lstat()
        _require(
            (
                int(before.st_dev),
                int(before.st_ino),
                int(before.st_size),
                int(before.st_mtime_ns),
                int(before.st_nlink),
            )
            == (
                int(after.st_dev),
                int(after.st_ino),
                int(after.st_size),
                int(after.st_mtime_ns),
                int(after.st_nlink),
            ),
            f"bundle changed while closing: {self.path}",
        )
        return PhysicalFileRecord(
            path=self.path,
            relative_path=self.path.name,
            sha256=self._digest.hexdigest(),
            size_bytes=self._size,
            identity=_stat_identity(after),
        )

    def abort(self) -> None:
        if not self._closed:
            try:
                os.close(self._fd)
            finally:
                self._closed = True


@dataclass(frozen=True)
class DecoderContract:
    name: str
    version: str
    executable: PhysicalFileRecord
    executable_copy: PhysicalFileRecord
    invocation_contract: PhysicalFileRecord
    canonical_argv_sha256: str
    runtime_image_id: str


_SHOWINFO_RE = re.compile(
    r"\bn:\s*(?P<n>\d+)\s+pts:\s*(?P<pts>-?\d+)\s+"
    r"pts_time:(?P<pts_time>[-+0-9.eE]+).*?\bs:(?P<w>\d+)x(?P<h>\d+)"
)


class ProductionFfmpegDecoder:
    """Pinned ffmpeg RGB24 decoder; showinfo is the frame/PTS authority."""

    def __init__(
        self,
        executable: Path | str,
        *,
        project_root: Path,
        staging_root: Path,
    ) -> None:
        raw = Path(executable)
        _require(raw.is_absolute(), "ffmpeg executable path must be absolute")
        executable_record, executable_payload = _read_physical_file(
            project_root,
            raw,
            expected_sha256=None,
            expected_size=None,
            label="ffmpeg executable",
            absolute_allowed=True,
        )
        _validate_production_label(executable_record.path.name, label="ffmpeg executable")
        try:
            completed = subprocess.run(
                [str(executable_record.path), "-version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MaterializerError(f"ffmpeg version probe failed: {error}") from error
        version_lines = completed.stdout.splitlines()
        _require(version_lines, "ffmpeg version output is empty")
        version = _validate_production_label(version_lines[0].strip(), label="ffmpeg version")
        implementation_dir = staging_root / "support" / "decoder"
        implementation_dir.mkdir(parents=True, exist_ok=False)
        executable_copy = _write_new_file(
            implementation_dir / "ffmpeg.executable",
            executable_payload,
            mode=0o555,
        )
        self._root = project_root
        self._staging_root = staging_root
        self._executable = executable_record
        self._executable_copy = executable_copy
        self._version = version
        self._version_output_sha256 = _sha256_bytes(completed.stdout.encode("utf-8"))
        self._argv_records: list[list[str]] = []
        self.contract: DecoderContract | None = None

    def _assert_executable_unchanged(self) -> None:
        record, _ = _read_physical_file(
            self._root,
            self._executable.path,
            expected_sha256=self._executable.sha256,
            expected_size=self._executable.size_bytes,
            label="ffmpeg executable",
            absolute_allowed=True,
        )
        _require(
            record.identity == self._executable.identity,
            "ffmpeg executable stable stat drifted",
        )

    @staticmethod
    def _select_expression(frame_indices: Sequence[int]) -> str:
        _require(
            frame_indices
            and list(frame_indices) == sorted(set(frame_indices))
            and all(type(value) is int and value >= 0 for value in frame_indices),
            "decoder frame selection is invalid",
        )
        return "+".join(f"eq(n\\,{value})" for value in frame_indices)

    def decode(
        self,
        source: PhysicalFileRecord,
        plans: Sequence[SamplePlan],
    ) -> Iterator[DecodedFrame]:
        ordered = sorted(plans, key=lambda item: item.frame_index)
        indices = [item.frame_index for item in ordered]
        _require(len(indices) == len(set(indices)), "decoder plan contains duplicate frames")
        frozen = _FROZEN_BY_PATH.get(source.relative_path)
        _require(
            frozen is not None
            and frozen.codec is not None
            and frozen.width is not None
            and frozen.height is not None,
            "decoder source is not an exact frozen KPP video",
        )
        _require(
            all(
                plan.relative_path == source.relative_path and plan.codec == frozen.codec
                for plan in ordered
            ),
            "decoder plan/source binding drifted",
        )
        self._assert_executable_unchanged()
        source_before = source.path.lstat()
        _require(
            _stat_identity(source_before) == source.identity,
            "frozen KPP source drifted before decoder execution",
        )
        argv = [
            str(self._executable.path),
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "info",
            "-i",
            str(source.path),
            "-map",
            "0:v:0",
            "-vf",
            f"showinfo,select='{self._select_expression(indices)}'",
            "-fps_mode",
            "passthrough",
            "-frames:v",
            str(len(ordered)),
            "-pix_fmt",
            "rgb24",
            "-f",
            "rawvideo",
            "pipe:1",
        ]
        self._argv_records.append(list(argv))
        try:
            completed = subprocess.run(
                argv,
                check=True,
                capture_output=True,
                timeout=1800,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise MaterializerError(
                f"ffmpeg RGB decode failed for {source.relative_path}: {error}"
            ) from error
        source_after = source.path.lstat()
        _require(
            _stat_identity(source_after) == source.identity,
            "frozen KPP source drifted during decoder execution",
        )
        self._assert_executable_unchanged()
        try:
            diagnostic = completed.stderr.decode("utf-8", errors="strict")
        except UnicodeDecodeError as error:
            raise MaterializerError("ffmpeg showinfo output is not UTF-8") from error
        observations: dict[int, tuple[int, int, int, int]] = {}
        for match in _SHOWINFO_RE.finditer(diagnostic):
            frame_index = int(match.group("n"))
            if frame_index not in set(indices):
                continue
            _require(frame_index not in observations, "ffmpeg emitted duplicate showinfo frame")
            try:
                pts = Decimal(match.group("pts_time"))
                pts_ns = int(
                    (pts * Decimal(1_000_000_000)).to_integral_value(
                        rounding=ROUND_HALF_UP
                    )
                )
            except (InvalidOperation, ValueError) as error:
                raise MaterializerError("ffmpeg showinfo PTS is invalid") from error
            _require(pts_ns >= 0, "ffmpeg showinfo PTS is negative")
            observations[frame_index] = (
                frame_index,
                pts_ns,
                int(match.group("w")),
                int(match.group("h")),
            )
        _require(
            set(observations) == set(indices),
            "ffmpeg did not report every selected frame coordinate",
        )
        frame_bytes = int(frozen.width) * int(frozen.height) * 3
        _require(
            len(completed.stdout) == len(ordered) * frame_bytes,
            "ffmpeg RGB output byte length is partial or drifted",
        )
        for output_index, plan in enumerate(ordered):
            observed_frame_index, pts_ns, width, height = observations[
                plan.frame_index
            ]
            _require(
                (width, height) == (frozen.width, frozen.height),
                "ffmpeg decoded geometry differs from frozen KPP",
            )
            start = output_index * frame_bytes
            yield DecodedFrame(
                plan=plan,
                observed_frame_index=observed_frame_index,
                pts_ns=pts_ns,
                width=width,
                height=height,
                stride=width * 3,
                rgb=completed.stdout[start : start + frame_bytes],
            )

    def finalize_contract(
        self, *, project_root: Path, final_root: Path
    ) -> DecoderContract:
        _require(self.contract is None, "decoder contract was already finalized")
        _require(len(self._argv_records) == 4, "decoder must execute exact four KPP source commands")
        argv_digest = canonical_sha256(self._argv_records)
        invocation = {
            "schema_version": 1,
            "artifact_kind": "checkpoint_model_parity_decoder_invocation_contract",
            "decoder": "ffmpeg",
            "version": self._version,
            "version_output_sha256": self._version_output_sha256,
            "executable_source_path": str(self._executable.path),
            "executable_sha256": self._executable.sha256,
            "executable_size_bytes": self._executable.size_bytes,
            "executable_stable_stat": list(self._executable.identity),
            "executable_materialized": _final_reference(
                project_root,
                self._executable_copy,
                staging_root=self._staging_root,
                final_root=final_root,
                sized=True,
            ),
            "argv": self._argv_records,
            "canonical_argv_sha256": argv_digest,
            "pixel_format": "rgb24",
            "coordinate_authority": "ffmpeg_showinfo_n_and_pts_time",
        }
        invocation_record = _write_json_file(
            self._executable_copy.path.parent / "invocation_contract.json",
            invocation,
        )
        self.contract = DecoderContract(
            name="ffmpeg",
            version=self._version,
            executable=self._executable,
            executable_copy=self._executable_copy,
            invocation_contract=invocation_record,
            canonical_argv_sha256=argv_digest,
            runtime_image_id=f"sha256:{self._executable.sha256}",
        )
        return self.contract


def _worker_request_bounds(plan: Sequence[SamplePlan]) -> dict[str, int]:
    bounds = {branch: 0 for branch in BRANCHES}
    for row in plan:
        _require(row.branch in bounds, "sample plan contains an unknown worker branch")
        bounds[row.branch] += 1
    _require(
        all(1 <= count <= 1_000_000 for count in bounds.values()),
        "worker request bounds are empty or exceed the protocol maximum",
    )
    return bounds


class NativeEndpointRunner:
    """Own, attest, and drain the exact eight native Docker workers."""

    def __init__(
        self,
        *,
        socket_dir: Path | str,
        materialized_bindings: MaterializedBindingSet,
        execution_config: Mapping[str, Any],
        project_root: Path | str,
        request_bounds: Mapping[str, int],
        startup_timeout_s: float = 120.0,
        shutdown_timeout_s: float = 30.0,
    ) -> None:
        self._socket_dir = _physical_directory(
            socket_dir, label="analytics worker socket directory"
        )
        self._project_root = _physical_directory(
            project_root, label="analytics worker project root"
        )
        _require(
            type(startup_timeout_s) in {int, float}
            and 0 < float(startup_timeout_s) <= 3600,
            "analytics worker startup timeout is invalid",
        )
        _require(
            type(shutdown_timeout_s) in {int, float}
            and 0 < float(shutdown_timeout_s) <= 300,
            "analytics worker shutdown timeout is invalid",
        )
        self._startup_timeout_s = float(startup_timeout_s)
        self._shutdown_timeout_s = float(shutdown_timeout_s)
        _require(
            type(request_bounds) is dict
            and set(request_bounds) == set(BRANCHES)
            and all(
                type(value) is int and 1 <= value <= 1_000_000
                for value in request_bounds.values()
            ),
            "analytics worker request bounds are invalid",
        )
        self._request_bounds = dict(request_bounds)
        workers = execution_config.get("workers")
        _require(
            type(workers) is dict and set(workers) == {"cpu", "gpu"},
            "analytics execution worker inventory is not exact CPU/GPU",
        )
        self._workers = workers
        _require(
            set(materialized_bindings.capabilities)
            == {
                (branch, resource)
                for branch in BRANCHES
                for resource in ("cpu", "gpu")
            },
            "materialized worker capability coverage is not exact 8",
        )
        serialized = _canonical_json(
            {
                "index": materialized_bindings.index,
                "bindings": {
                    f"{branch}:{resource}": materialized_bindings.bindings[
                        (branch, resource)
                    ]
                    for branch in BRANCHES
                    for resource in ("cpu", "gpu")
                },
                "capabilities": {
                    f"{branch}:{resource}": materialized_bindings.capabilities[
                        (branch, resource)
                    ]
                    for branch in BRANCHES
                    for resource in ("cpu", "gpu")
                },
            }
        ).decode("ascii").lower()
        _require(
            not any(token in serialized for token in _FORBIDDEN_PRODUCTION_TOKENS),
            "materialized worker inventory is mock/synthetic/nonpublication",
        )
        self._materialized = materialized_bindings
        lifecycle_material = (
            f"{os.getpid()}:{time.monotonic_ns()}:{self._socket_dir}"
        ).encode("utf-8")
        self._lifecycle_id = hashlib.sha256(lifecycle_material).hexdigest()[:32]
        self._runtime_directory_custody: DirectoryFdCustodyV1 | None = None
        self._socket_retirement_directory = self._socket_dir.parent / (
            f".vast-model-parity-retired-{self._lifecycle_id}"
        )
        self._socket_retirement_directory_custody: (
            DirectoryFdCustodyV1 | None
        ) = None
        self._opened_socket_names: set[str] = set()
        self._retired_socket_nodes: list[dict[str, Any]] = []
        self._process_factory = DockerWorkerProcessFactory(
            project_root=self._project_root,
            binding_set_root=materialized_bindings.root,
            runtime_dir=self._socket_dir,
        )
        self._listeners: dict[tuple[str, str], Any] = {}
        self._handles: dict[tuple[str, str], Any] = {}
        self._sockets: dict[tuple[str, str], socket.socket] = {}
        self._clients: dict[tuple[str, str], ExecutionClient] = {}
        self._capabilities: dict[tuple[str, str], dict[str, Any]] = {}
        self._output_names: dict[tuple[str, str], str] = {}
        self._pending_peer_identities: dict[
            tuple[str, str], dict[str, Any]
        ] = {}
        self._peer_identities: dict[tuple[str, str], dict[str, Any]] = {}
        try:
            self._establish_socket_retirement_custody()
            self._launch_and_accept_workers()
        except BaseException:
            try:
                self.close(require_clean=False)
            except BaseException:
                pass
            raise

    def _establish_socket_retirement_custody(self) -> None:
        _require(
            os.name == "posix",
            "model-parity socket retirement requires POSIX dirfd custody",
        )
        retirement_custody: DirectoryFdCustodyV1 | None = None
        try:
            self._runtime_directory_custody = DirectoryFdCustodyV1.open_existing(
                self._socket_dir,
                label="model-parity analytics socket directory",
            )
            retirement_custody = DirectoryFdCustodyV1.open_existing(
                self._socket_dir.parent,
                label="model-parity socket retirement parent",
            )
            retirement_custody.mkdir_child_exclusive(
                self._socket_retirement_directory.name,
                mode=0o700,
            )
            runtime_metadata = os.fstat(
                self._runtime_directory_custody.directory_fd
            )
            retirement_metadata = os.fstat(retirement_custody.directory_fd)
            _require(
                stat.S_ISDIR(runtime_metadata.st_mode)
                and stat.S_ISDIR(retirement_metadata.st_mode)
                and int(runtime_metadata.st_dev)
                == int(retirement_metadata.st_dev)
                and not os.listdir(self._runtime_directory_custody.directory_fd)
                and not os.listdir(retirement_custody.directory_fd),
                "model-parity socket retirement namespace is invalid",
            )
            self._socket_retirement_directory_custody = retirement_custody
            retirement_custody = None
        except BaseException:
            if retirement_custody is not None:
                retirement_custody.close()
            if self._runtime_directory_custody is not None:
                self._runtime_directory_custody.close()
                self._runtime_directory_custody = None
            raise

    def _verify_socket_retirement_namespace(self, *, require_all: bool) -> None:
        runtime_custody = self._runtime_directory_custody
        retirement_custody = self._socket_retirement_directory_custody
        _require(
            runtime_custody is not None and retirement_custody is not None,
            "model-parity socket retirement custody is unavailable",
        )
        runtime_custody.verify()
        retirement_custody.verify()
        retirement_metadata = os.fstat(retirement_custody.directory_fd)
        records_by_retired_name: dict[str, dict[str, Any]] = {}
        retired_active_names: set[str] = set()
        for raw_record in self._retired_socket_nodes:
            record = _validate_retired_socket_record_v1(
                raw_record,
                expected_lifecycle_id=self._lifecycle_id,
            )
            active_name = record["active_name"]
            retired_name = record["retired_name"]
            _require(
                active_name in self._opened_socket_names
                and active_name not in retired_active_names
                and retired_name not in records_by_retired_name,
                "model-parity socket retirement ledger is duplicated or foreign",
            )
            directory = record["retirement_directory"]
            _require(
                directory
                == {
                    "path": str(retirement_custody.path),
                    "st_dev": int(retirement_metadata.st_dev),
                    "st_ino": int(retirement_metadata.st_ino),
                },
                "model-parity socket retirement directory identity drifted",
            )
            metadata = os.stat(
                retired_name,
                dir_fd=retirement_custody.directory_fd,
                follow_symlinks=False,
            )
            socket_identity = record["socket_identity"]
            _require(
                stat.S_ISSOCK(metadata.st_mode)
                and int(metadata.st_nlink) == 1
                and (
                    int(metadata.st_dev),
                    int(metadata.st_ino),
                    int(stat.S_IFMT(metadata.st_mode)),
                    int(metadata.st_nlink),
                )
                == (
                    socket_identity["st_dev"],
                    socket_identity["st_ino"],
                    socket_identity["st_mode_type"],
                    socket_identity["st_nlink"],
                ),
                "model-parity retired socket identity drifted",
            )
            retired_active_names.add(active_name)
            records_by_retired_name[retired_name] = record
        active_entries = set(os.listdir(runtime_custody.directory_fd))
        retirement_entries = set(os.listdir(retirement_custody.directory_fd))
        _require(
            active_entries == self._opened_socket_names - retired_active_names
            and retirement_entries == set(records_by_retired_name),
            "model-parity socket namespace coverage drifted",
        )
        if require_all:
            _require(
                not active_entries
                and retired_active_names == self._opened_socket_names,
                "model-parity socket retirement is incomplete",
            )
        runtime_custody.verify()
        retirement_custody.verify()

    def _retire_listener(self, owned: Any) -> None:
        record = _close_owned_socket(
            owned,
            directory_custody=self._runtime_directory_custody,
            retirement_custody=self._socket_retirement_directory_custody,
            lifecycle_id=self._lifecycle_id,
        )
        _require(
            record is not None,
            "model-parity POSIX listener retirement record is unavailable",
        )
        checked = _validate_retired_socket_record_v1(
            record,
            expected_lifecycle_id=self._lifecycle_id,
        )
        _require(
            checked["active_name"] in self._opened_socket_names
            and all(
                item["retired_name"] != checked["retired_name"]
                for item in self._retired_socket_nodes
            ),
            "model-parity listener retirement record drifted",
        )
        self._retired_socket_nodes.append(checked)
        self._verify_socket_retirement_namespace(require_all=False)

    def _close_socket_retirement_custody(self) -> None:
        runtime_custody = self._runtime_directory_custody
        retirement_custody = self._socket_retirement_directory_custody
        self._runtime_directory_custody = None
        self._socket_retirement_directory_custody = None
        if runtime_custody is not None:
            runtime_custody.close()
        if retirement_custody is not None:
            retirement_custody.close()

    def _assert_workers_live(self, *, phase: str) -> None:
        for key, handle in self._handles.items():
            status = handle.poll()
            _require(
                status is None,
                f"analytics worker {key[0]}/{key[1]} exited during {phase}: {status}",
            )

    def _launch_and_accept_workers(self) -> None:
        endpoint_engine = {
            "cpu": ENGINE_OPENVINO_CPU,
            "gpu": ENGINE_TENSORRT_CUDA,
        }
        endpoint_public = {
            "cpu": "openvino_cpu",
            "gpu": "tensorrt_cuda",
        }
        for branch in BRANCHES:
            for endpoint_resource in ("cpu", "gpu"):
                key = (branch, endpoint_resource)
                path = self._socket_dir / f"worker-{branch}-{endpoint_resource}.sock"
                owned = _open_owned_listener(path, backlog=1)
                self._listeners[key] = owned
                _require(
                    path.name not in self._opened_socket_names,
                    "model-parity listener name was reused",
                )
                self._opened_socket_names.add(path.name)
                binding_path = self._materialized.binding_paths[key]
                spec = WorkerLaunchSpec(
                    branch=branch,
                    resource=endpoint_resource,
                    engine=endpoint_engine[endpoint_resource],
                    binding_path=binding_path,
                    socket_path=path,
                    container_binding_path=f"/run/vast/bindings/{binding_path.name}",
                    container_socket_path=f"/run/vast/analytics/{path.name}",
                    worker_config=self._workers[endpoint_resource],
                    max_requests=self._request_bounds[branch],
                    lifecycle_id=self._lifecycle_id,
                )
                handle = self._process_factory.start(spec)
                _require(
                    type(handle.pid) is int and handle.pid > 0,
                    f"analytics worker {branch}/{endpoint_resource} supervisor PID is invalid",
                )
                self._handles[key] = handle
        expected_keys = {
            (branch, resource)
            for branch in BRANCHES
            for resource in ("cpu", "gpu")
        }
        _require(
            set(self._listeners) == expected_keys
            and set(self._handles) == expected_keys,
            "analytics worker lifecycle coverage is not exact 8",
        )

        deadline = time.monotonic() + self._startup_timeout_s
        for branch in BRANCHES:
            for endpoint_resource in ("cpu", "gpu"):
                endpoint_key = (branch, endpoint_resource)
                public_resource = endpoint_public[endpoint_resource]
                public_key = (branch, public_resource)
                handle = self._handles[endpoint_key]
                self._assert_workers_live(phase="startup")
                remaining = deadline - time.monotonic()
                _require(
                    remaining > 0,
                    f"timed out starting analytics worker {branch}/{endpoint_resource}",
                )
                expected_peer_pid = handle.expected_peer_pid(remaining)
                owned = self._listeners[endpoint_key]
                listener = owned.listener
                _require(
                    listener is not None,
                    f"analytics worker {branch}/{endpoint_resource} listener disappeared",
                )
                connection: socket.socket | None = None
                while connection is None:
                    self._assert_workers_live(phase="startup")
                    remaining = deadline - time.monotonic()
                    _require(
                        remaining > 0,
                        f"timed out accepting analytics worker {branch}/{endpoint_resource}",
                    )
                    listener.settimeout(min(0.1, remaining))
                    try:
                        connection, _address = listener.accept()
                    except socket.timeout:
                        continue
                try:
                    peer_identity = _attest_worker_peer_identity(
                        connection,
                        docker_state_pid=expected_peer_pid,
                        worker_handle=handle,
                        socket_dir=self._socket_dir,
                        socket_path=owned.path,
                    )
                except BaseException:
                    connection.close()
                    raise
                connection.settimeout(120.0)
                self._sockets[public_key] = connection
                self._pending_peer_identities[public_key] = peer_identity
                self._retire_listener(owned)
                del self._listeners[endpoint_key]

                expected = validate_worker_capability(
                    self._materialized.capabilities[endpoint_key]
                )
                client = ExecutionClient(connection, expected_capability=expected)
                actual = client.handshake()
                _require(
                    actual == expected,
                    f"{branch}/{public_resource} endpoint capability drifted",
                )
                self._clients[public_key] = client
                self._capabilities[public_key] = actual
                binding = self._materialized.bindings[endpoint_key]
                outputs = binding.get("outputs")
                _require(
                    type(outputs) is list
                    and len(outputs) == 1
                    and type(outputs[0]) is dict
                    and outputs[0].get("dtype") == "float32"
                    and outputs[0].get("shape") == [1, 1000]
                    and type(outputs[0].get("name")) is str
                    and bool(outputs[0]["name"]),
                    f"{branch}/{public_resource} materialized output contract drifted",
                )
                self._output_names[public_key] = outputs[0]["name"]
        _require(
            len(self._clients) == 8 and not self._listeners,
            "native endpoint handshake coverage is not exact 8",
        )
        _require(
            set(self._pending_peer_identities) == set(self._clients),
            "native endpoint pending peer identity coverage is not exact 8",
        )
        self._verify_socket_retirement_namespace(require_all=True)
        self._peer_identities = {
            key: _complete_peer_identity_after_handshake(peer)
            for key, peer in self._pending_peer_identities.items()
        }

    @property
    def capabilities(self) -> Mapping[tuple[str, str], Mapping[str, Any]]:
        return self._capabilities

    @property
    def peer_identities(self) -> Mapping[tuple[str, str], Mapping[str, Any]]:
        return self._peer_identities

    def infer(
        self,
        *,
        branch: str,
        resource: str,
        sample: DecodedFrame,
        tensor: bytes,
        tensor_descriptor: Mapping[str, Any],
        run_id: str,
    ) -> ValidatedNativeResponse:
        key = (branch, resource)
        _require(key in self._clients, "native endpoint coordinate is absent")
        capability = self._capabilities[key]
        _require(
            sample.plan.branch == branch,
            "native endpoint sample branch binding drifted",
        )
        request_id = (
            f"mp.{run_id}.{branch}.{RESOURCE_LABELS[resource]}."
            f"{sample.plan.role}.{sample.plan.codec}."
            f"{sample.observed_frame_index}"
        )
        _require(_STABLE_ID_RE.fullmatch(request_id) is not None, "request_id is invalid")
        request = {
            "schema_version": 1,
            "message_type": "infer_request",
            "request_id": request_id,
            "run_id": run_id,
            "arm_id": f"model-parity.{branch}.{RESOURCE_LABELS[resource]}",
            "worker_id": capability["worker_id"],
            "frame": {
                "input_frame_key": (
                    f"kpp:{sample.plan.codec}:{sample.plan.relative_path}:"
                    f"{sample.observed_frame_index}:{sample.pts_ns}"
                ),
                "stream_id": sample.plan.stream_index,
                "frame_id": sample.observed_frame_index,
                "transport_pts_ns": sample.pts_ns,
                "branch": branch,
            },
            "engine": RESOURCE_ENGINES[resource],
            "deadline_monotonic_ns": time.monotonic_ns() + 120_000_000_000,
            "model": {
                "model_id": capability["model_id"],
                "source_sha256": capability["source_model_sha256"],
                "runtime_artifact_sha256": capability["model_artifact_sha256"],
                "runtime_weights_sha256": capability["runtime_weights_sha256"],
            },
            "tensor": dict(tensor_descriptor),
            "expected_output_contract_sha256": capability[
                "output_contract_sha256"
            ],
        }
        try:
            response, output = self._clients[key].infer(request, tensor)
            checked = validate_inference_response(
                response,
                request=request,
                capability=capability,
            )
        except (ProtocolError, OSError) as error:
            raise MaterializerError(
                f"native inference failed for {branch}/{resource}: {error}"
            ) from error
        _require(
            checked["output"]["tensor_count"] == 1
            and checked["output"]["tensors"]
            == [
                {
                    "name": self._output_names[key],
                    "dtype": "float32",
                    "shape": [1, 1000],
                    "offset": 0,
                    "byte_length": 4000,
                }
            ],
            "native classification output tensor contract drifted",
        )
        _require(len(output) == 4000, "native classification output is partial")
        return ValidatedNativeResponse(
            _VALIDATED_RESPONSE_TOKEN,
            request=request,
            response=checked,
            capability=capability,
            output=output,
        )

    def close(self, *, require_clean: bool = False) -> None:
        errors: list[str] = []
        for value in tuple(self._sockets.values()):
            try:
                value.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                value.close()
            except OSError:
                pass
        self._sockets.clear()
        self._clients.clear()

        for key, owned in tuple(reversed(tuple(self._listeners.items()))):
            try:
                self._retire_listener(owned)
            except BaseException as error:
                errors.append(f"socket_cleanup:{key[0]}/{key[1]}:{error}")
            finally:
                self._listeners.pop(key, None)

        graceful_deadline = time.monotonic() + self._shutdown_timeout_s
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.wait(max(0.001, graceful_deadline - time.monotonic()))
                except (TimeoutError, subprocess.TimeoutExpired):
                    pass
                except BaseException as error:
                    errors.append(f"worker_wait:{key[0]}/{key[1]}:{error}")
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.terminate()
                except BaseException as error:
                    errors.append(f"worker_terminate:{key[0]}/{key[1]}:{error}")
        terminate_deadline = time.monotonic() + self._shutdown_timeout_s
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.wait(max(0.001, terminate_deadline - time.monotonic()))
                except (TimeoutError, subprocess.TimeoutExpired):
                    pass
                except BaseException as error:
                    errors.append(
                        f"worker_terminate_wait:{key[0]}/{key[1]}:{error}"
                    )
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.kill()
                except BaseException as error:
                    errors.append(f"worker_kill:{key[0]}/{key[1]}:{error}")
        kill_deadline = time.monotonic() + self._shutdown_timeout_s
        for key, handle in self._handles.items():
            if handle.poll() is None:
                try:
                    handle.wait(max(0.001, kill_deadline - time.monotonic()))
                except (TimeoutError, subprocess.TimeoutExpired) as error:
                    errors.append(f"worker_survived_kill:{key[0]}/{key[1]}:{error}")
                except BaseException as error:
                    errors.append(f"worker_kill_wait:{key[0]}/{key[1]}:{error}")
        for key, handle in self._handles.items():
            status = handle.poll()
            if status is None:
                errors.append(f"worker_still_live:{key[0]}/{key[1]}")
            elif require_clean and status != 0:
                errors.append(f"worker_nonzero:{key[0]}/{key[1]}:{status}")
        self._handles.clear()
        try:
            if self._runtime_directory_custody is not None:
                self._verify_socket_retirement_namespace(require_all=True)
        except BaseException as error:
            errors.append(f"socket_retirement_custody:{error}")
        finally:
            self._close_socket_retirement_custody()
        if errors:
            raise MaterializerError(
                "analytics worker lifecycle cleanup failed: " + "; ".join(errors)
            )

    def __enter__(self) -> "NativeEndpointRunner":
        return self

    def __exit__(self, *args: object) -> None:
        self.close(require_clean=not args or args[0] is None)


class _UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: yaml.SafeLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        _require(key not in result, f"duplicate YAML key: {key}")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _load_yaml_payload(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeyLoader)
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise MaterializerError(f"{label} is invalid YAML: {error}") from error
    _require(type(value) is dict, f"{label} must be a mapping")
    return value


def _load_canonical_json_payload(payload: bytes, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise MaterializerError(f"{label} is invalid JSON: {error}") from error
    _require(type(value) is dict, f"{label} must be a mapping")
    _require(
        payload == _canonical_json(value) or payload == _canonical_json(value) + b"\n",
        f"{label} is not canonical JSON",
    )
    return value


def _validate_frozen_dataset_config(value: Mapping[str, Any]) -> None:
    _require(value.get("schema_version") == 1, "dataset config schema drifted")
    datasets = value.get("datasets")
    _require(type(datasets) is dict, "dataset config inventory is invalid")
    expected_by_codec = {
        codec: {
            item.relative_path: item
            for item in FROZEN_KPP_FILES
            if item.codec == codec
        }
        for codec in ("h264", "h265")
    }
    annotation_record = _FROZEN_BY_PATH[
        "data/videos/kpp/kpp_iss_publication_v3/receipts/"
        "iss_v2_underbody_metadata.json"
    ]
    for codec in ("h264", "h265"):
        name = KPP_DATASET_BY_CODEC[codec]
        dataset = datasets.get(name)
        _require(type(dataset) is dict, f"{name} dataset is missing")
        try:
            validated = validate_kpp_iss_publication_v3_manifest_entry(
                name,
                dataset,
                project_root=PROJECT_ROOT,
                require_files=False,
            )
        except KppIssPublicationV3DatasetError as error:
            raise MaterializerError(
                f"{name} publication-v3 dataset contract drifted: {error}"
            ) from error
        _require(validated is True, f"{name} publication-v3 dataset was not recognized")
        _require(
            dataset.get("kind") == "frozen_publication_codec_corpus"
            and dataset.get("publishable") is True
            and dataset.get("codec_variant") == codec,
            f"{name} publication/codec binding drifted",
        )
        _require(
            dataset.get("dataset_contract_version") == 3
            and dataset.get("generation_id") == KPP_PUBLICATION_GENERATION_ID
            and dataset.get("status") == "frozen_publication_corpus"
            and dataset.get("publication_scope") == KPP_PUBLICATION_SCOPE
            and dataset.get("analytics_routing") == "unresolved"
            and dataset.get("logical_stream_instances") == 6,
            f"{name} frozen publication-v3 identity drifted",
        )
        preparation = dataset.get("preparation")
        _require(
            type(preparation) is dict
            and preparation.get("mode") == "check_only_frozen_publication_v3"
            and type(preparation.get("publication_manifest")) is dict
            and preparation["publication_manifest"].get("manifest_sha256")
            == KPP_PUBLICATION_MANIFEST_SHA256,
            f"{name} publication manifest binding drifted",
        )
        annotation = dataset.get("annotations")
        _require(
            type(annotation) is dict
            and annotation.get("path") == annotation_record.relative_path
            and annotation.get("sha256") == annotation_record.sha256
            and annotation.get("accuracy_ground_truth") is False,
            f"{name} frozen annotation binding drifted",
        )
        streams = dataset.get("streams")
        _require(
            type(streams) is list and len(streams) == 6,
            f"{name} streams are invalid",
        )
        observed: dict[str, int] = {}
        for stream in streams:
            _require(type(stream) is dict, f"{name} stream is invalid")
            relative = stream.get("path")
            _require(relative in expected_by_codec[codec], f"{name} stream path drifted")
            frozen = expected_by_codec[codec][relative]
            _require(
                stream.get("sha256") == frozen.sha256
                and stream.get("codec_name")
                == ("h264" if codec == "h264" else "hevc")
                and stream.get("container") == frozen.container
                and stream.get("width") == frozen.width
                and stream.get("height") == frozen.height,
                f"{name} stream physical identity drifted: {relative}",
            )
            observed[str(relative)] = observed.get(str(relative), 0) + 1
        _require(
            observed
            == {
                relative: (1 if relative.endswith("underbody.mp4") else 5)
                for relative in expected_by_codec[codec]
            },
            f"{name} frozen physical coverage is not exact",
        )


@dataclass(frozen=True)
class _Preflight:
    root: Path
    dataset_config_record: PhysicalFileRecord
    base_manifest_record: PhysicalFileRecord
    base_manifest: dict[str, Any]
    kpp_records: Mapping[str, PhysicalFileRecord]


def _preflight_real_inputs(
    *,
    project_root: Path | str,
    dataset_manifest_path: Path | str,
    base_manifest_path: Path | str,
    materialization_dir: Path | str,
    accepted_manifest_path: Path | str,
) -> _Preflight:
    """Verify all frozen KPP bytes before creating output or touching endpoints."""

    root = _physical_root(project_root)
    dataset_relative = _project_relative(
        root, dataset_manifest_path, label="frozen dataset config"
    )
    base_relative = _project_relative(
        root, base_manifest_path, label="frozen model-parity manifest"
    )
    dataset_record, dataset_payload = _read_physical_file(
        root,
        dataset_relative,
        expected_sha256=None,
        expected_size=None,
        label="frozen dataset config",
    )
    _validate_frozen_dataset_config(
        _load_yaml_payload(dataset_payload, label="frozen dataset config")
    )
    base_record, _ = _read_physical_file(
        root,
        base_relative,
        expected_sha256=None,
        expected_size=None,
        label="frozen model-parity manifest",
    )
    try:
        loaded = load_parity_manifest(base_record.path)
    except ContractError as error:
        raise MaterializerError(f"frozen model-parity manifest is invalid: {error}") from error
    base_manifest = {key: value for key, value in loaded.items() if key != "identity"}
    _require(
        all(
            base_manifest["workload_slots"][branch]["evidence"][name].get("sha256")
            is None
            for branch in BRANCHES
            for name in EVIDENCE_NAMES
        ),
        "frozen model-parity manifest is not the unmaterialized requirements copy",
    )
    base_after, _ = _read_physical_file(
        root,
        base_relative,
        expected_sha256=base_record.sha256,
        expected_size=base_record.size_bytes,
        label="frozen model-parity manifest",
    )
    _require(base_after.identity == base_record.identity, "frozen manifest drifted during load")

    kpp: dict[str, PhysicalFileRecord] = {}
    for frozen in FROZEN_KPP_FILES:
        record, _ = _read_physical_file(
            root,
            frozen.relative_path,
            expected_sha256=frozen.sha256,
            expected_size=None,
            label=f"frozen KPP {frozen.relative_path}",
        )
        _require(record.size_bytes > 0, f"frozen KPP file is empty: {frozen.relative_path}")
        kpp[frozen.relative_path] = record

    _safe_output_path(root, materialization_dir, label="materialization directory", must_not_exist=True)
    accepted = _safe_output_path(
        root, accepted_manifest_path, label="accepted manifest", must_not_exist=False
    )
    _require(accepted != base_record.path, "accepted manifest must be distinct from frozen manifest")
    return _Preflight(root, dataset_record, base_record, base_manifest, kpp)


def _model_hashes(
    slot: Mapping[str, Any], resource: str
) -> tuple[str | None, str | None, str | None]:
    if resource == "openvino_cpu":
        return (
            slot["openvino_ir"]["model"]["sha256"],
            slot["openvino_ir"]["weights"]["sha256"],
            None,
        )
    return (None, None, slot["tensorrt_engine"]["artifact"]["sha256"])


def build_execution_probe_document(
    *,
    branch: str,
    slot: Mapping[str, Any],
    source: Mapping[str, Any],
    resource: str,
    capability: Mapping[str, Any],
    sample_count: int,
) -> dict[str, Any]:
    """Bind a probe to the actual validated derived worker, never a claimed base ID."""

    _require(branch in BRANCHES and resource in RESOURCES, "execution probe coordinate is invalid")
    _require(type(sample_count) is int and sample_count > 0, "execution probe sample count is invalid")
    model_sha, weights_sha, engine_sha = _model_hashes(slot, resource)
    worker_image_id = capability.get("worker_image_id")
    worker_implementation_sha256 = capability.get("worker_implementation_sha256")
    _require(
        type(worker_image_id) is str and _IMAGE_ID_RE.fullmatch(worker_image_id) is not None,
        "validated worker image identity is invalid",
    )
    _require(
        type(worker_implementation_sha256) is str
        and _SHA256_RE.fullmatch(worker_implementation_sha256) is not None,
        "validated worker implementation identity is invalid",
    )
    cpu = resource == "openvino_cpu"
    return {
        "schema_version": 3,
        "artifact_kind": "checkpoint_model_execution_probe",
        "branch": branch,
        "workload_slot_id": slot["slot_id"],
        "resource": resource,
        "runtime": "openvino" if cpu else "tensorrt",
        "device_api": "OPENVINO_CPU" if cpu else "NVIDIA_CUDA",
        # The v3 evidence schema records the canonical OpenVINO selector here.
        # The physical CPU name remains hash-bound by the runtime probe/binding
        # set; copying it into this field would falsely fail the exact `CPU`
        # matrix coordinate.
        "device_id": "CPU" if cpu else capability["device_id"],
        "success": True,
        "source_sha256": capability["source_model_sha256"],
        "model_sha256": model_sha,
        "weights_sha256": weights_sha,
        "engine_sha256": engine_sha,
        "preprocessing_contract_sha256": capability["preprocessing_contract_sha256"],
        "output_contract_sha256": capability["output_contract_sha256"],
        "runtime_image_id": worker_image_id,
        "worker_implementation_sha256": worker_implementation_sha256,
        "input_name": source["input"]["name"],
        "input_shape": source["input"]["execution_shape"],
        "input_dtype": source["input"]["dtype"],
        "output_name": source["output"]["name"],
        "output_shape": source["output"]["execution_shape"],
        "output_dtype": source["output"]["dtype"],
        "sample_count": sample_count,
        "all_outputs_finite": True,
    }


def _validate_artifact_inventory(root: Path, manifest: Mapping[str, Any]) -> None:
    references: list[tuple[str, Mapping[str, Any]]] = []
    for source_id, source in manifest["source_registry"].items():
        references.append((f"canonical source {source_id}", source))
    for branch in BRANCHES:
        slot = manifest["workload_slots"][branch]
        references.extend(
            (
                (f"{branch} OpenVINO model", slot["openvino_ir"]["model"]),
                (f"{branch} OpenVINO weights", slot["openvino_ir"]["weights"]),
                (f"{branch} TensorRT engine", slot["tensorrt_engine"]["artifact"]),
            )
        )
    seen: set[tuple[str, str, int]] = set()
    for label, reference in references:
        key = (
            str(reference["path"]),
            str(reference["sha256"]),
            int(reference["size_bytes"]),
        )
        if key in seen:
            continue
        seen.add(key)
        _read_physical_file(
            root,
            key[0],
            expected_sha256=key[1],
            expected_size=key[2],
            label=label,
        )


def _validated_production_dependencies(
    preflight: _Preflight,
    *,
    execution_config_path: Path | str,
    binding_set_dir: Path | str,
    runtime_probe_paths: Mapping[str, Path | str],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], MaterializedBindingSet, bytes]:
    root = preflight.root
    _require(
        type(runtime_probe_paths) is dict and set(runtime_probe_paths) == {"cpu", "gpu"},
        "runtime probe path coverage must be exact CPU/GPU",
    )
    execution_relative = _project_relative(
        root, execution_config_path, label="execution config"
    )
    execution_record, _ = _read_physical_file(
        root,
        execution_relative,
        expected_sha256=None,
        expected_size=None,
        label="execution config",
    )
    try:
        execution_config = load_execution_config(execution_record.path)
    except SidecarError as error:
        raise MaterializerError(f"execution config is invalid: {error}") from error
    _require(
        execution_config["model_parity_manifest"]
        == preflight.base_manifest_record.relative_path,
        "execution config is not bound to the frozen parity manifest",
    )
    probes: dict[str, dict[str, Any]] = {}
    for resource in ("cpu", "gpu"):
        relative = _project_relative(
            root, runtime_probe_paths[resource], label=f"{resource} runtime probe"
        )
        _, payload = _read_physical_file(
            root,
            relative,
            expected_sha256=None,
            expected_size=None,
            label=f"{resource} runtime probe",
        )
        probes[resource] = _load_canonical_json_payload(
            payload, label=f"{resource} runtime probe"
        )

    binding_root = _physical_directory(binding_set_dir, label="materialized binding set")
    _require(root in binding_root.parents, "materialized binding set escaped project_root")
    for item in binding_root.iterdir():
        _require(item.is_file(), "materialized binding set contains a non-file")
        _read_physical_file(
            root,
            item.relative_to(root),
            expected_sha256=None,
            expected_size=None,
            label=f"materialized binding {item.name}",
        )
    try:
        bindings = load_materialized_binding_set(
            binding_root,
            execution_config=execution_config,
            runtime_probes=probes,
        )
    except (SidecarError, ProtocolError) as error:
        raise MaterializerError(f"materialized binding set is invalid: {error}") from error

    _validate_artifact_inventory(root, preflight.base_manifest)
    bridge_record, bridge_payload = _read_physical_file(
        root,
        "scripts/checkpoint_gstreamer_analytics_bridge.py",
        expected_sha256=None,
        expected_size=None,
        label="frozen preprocessing implementation",
    )
    _require(bridge_record.size_bytes > 0, "preprocessing implementation is empty")
    return execution_config, probes, bindings, bridge_payload


def _validate_capability_lineage(
    *,
    branch: str,
    resource: str,
    capability: Mapping[str, Any],
    binding: Mapping[str, Any],
    manifest: Mapping[str, Any],
    execution_config: Mapping[str, Any],
) -> None:
    slot = manifest["workload_slots"][branch]
    source = manifest["source_registry"][slot["source_ref"]]
    preprocessing_sha = _sha256_bytes(_canonical_json(manifest["preprocessing_contract"]))
    output_sha = _sha256_bytes(
        _canonical_json(
            {
                "classification_contract": manifest["classification_contract"],
                "source_output": source["output"],
            }
        )
    )
    model_sha, weights_sha, engine_sha = _model_hashes(slot, resource)
    expected_artifact = model_sha if resource == "openvino_cpu" else engine_sha
    execution_resource = "cpu" if resource == "openvino_cpu" else "gpu"
    runtime = manifest["worker_runtime_registry"][resource]
    worker = execution_config["workers"][execution_resource]
    _require(
        binding.get("input")
        == {
            "name": source["input"]["name"],
            "dtype": source["input"]["dtype"],
            "layout": source["input"]["layout"],
            "shape": source["input"]["execution_shape"],
        }
        and binding.get("outputs")
        == [
            {
                "name": source["output"]["name"],
                "dtype": source["output"]["dtype"],
                "shape": source["output"]["execution_shape"],
            }
        ],
        f"{branch}/{resource} materialized tensor binding mismatch",
    )
    _require(
        capability["branch"] == branch
        and capability["source_model_sha256"] == source["sha256"]
        and capability["model_artifact_sha256"] == expected_artifact
        and capability["runtime_weights_sha256"] == weights_sha
        and capability["preprocessing_contract_sha256"] == preprocessing_sha
        and capability["output_contract_sha256"] == output_sha
        and capability["worker_image_id"]
        == worker["image_id"]
        == runtime["image_id"]
        and capability["worker_implementation_sha256"]
        == worker["worker_implementation_sha256"]
        == runtime["worker_implementation_sha256"]
        and worker["image"] == runtime["image"]
        and worker["base_image"] == runtime["base_image"]
        and worker["base_image_id"] == runtime["base_image_id"],
        f"{branch}/{resource} validated capability lineage mismatch",
    )


def _dataset_document(preflight: _Preflight) -> tuple[dict[str, Any], str]:
    videos = [item for item in FROZEN_KPP_FILES if item.codec is not None]
    files = [
        {
            "file_id": item.file_id,
            "file_index": index,
            "path": item.relative_path,
            "sha256": item.sha256,
            "size_bytes": preflight.kpp_records[item.relative_path].size_bytes,
            "codec": item.codec,
            "container": item.container,
        }
        for index, item in enumerate(videos)
    ]
    dataset_id = "kpp-iss-publication-v3-h264-h265-frozen-v1"
    document = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_model_dataset_manifest",
        "dataset_id": dataset_id,
        "files": files,
        "files_sha256": _sha256_bytes(_canonical_json(files)),
    }
    aggregate = _sha256_bytes(_canonical_json({"dataset_id": dataset_id, "files": files}))
    return document, aggregate


def _descriptor(
    *,
    final_reference: Mapping[str, Any],
    segment: Mapping[str, Any],
    encoding: str,
    dtype: str,
    shape: list[int],
    layout: str,
    color_order: str,
) -> dict[str, Any]:
    return {
        **dict(final_reference),
        "offset_bytes": segment["offset_bytes"],
        "length_bytes": segment["length_bytes"],
        "segment_sha256": segment["segment_sha256"],
        "encoding": encoding,
        "dtype": dtype,
        "shape": shape,
        "layout": layout,
        "color_order": color_order,
    }


def _artifact_bindings(
    slot: Mapping[str, Any], source: Mapping[str, Any], resource: str
) -> dict[str, Any]:
    model, weights, engine = _model_hashes(slot, resource)
    return {
        "source_sha256": source["sha256"],
        "model_sha256": model,
        "weights_sha256": weights,
        "engine_sha256": engine,
    }


def _write_transaction_index(
    *,
    root: Path,
    staging_root: Path,
    final_root: Path,
    run_id: str,
    source_inventory: Mapping[str, PhysicalFileRecord],
    output_segments: Sequence[Mapping[str, Any]],
    execution_bundles: Sequence[Mapping[str, Any]],
) -> PhysicalFileRecord:
    files: list[dict[str, Any]] = []
    for path in sorted(staging_root.rglob("*"), key=lambda value: value.as_posix()):
        if path.is_dir():
            _require(not _is_reparse(path), "transaction contains a reparse directory")
            continue
        _require(path.is_file() and not _is_reparse(path), "transaction contains an unsafe file")
        record, _ = _read_physical_file(
            root,
            path.relative_to(root),
            expected_sha256=None,
            expected_size=None,
            label="staged transaction artifact",
        )
        final_path = final_root / path.relative_to(staging_root)
        files.append(
            {
                "path": final_path.relative_to(root).as_posix(),
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
            }
        )
    source_rows = [
        {
            "path": relative,
            "sha256": record.sha256,
            "size_bytes": record.size_bytes,
            "stable_stat": list(record.identity),
        }
        for relative, record in sorted(source_inventory.items())
    ]
    _require(
        len(execution_bundles) == len(output_segments),
        "transaction execution/output coverage cardinality mismatch",
    )
    _require(
        len({str(row.get("request_id")) for row in execution_bundles})
        == len(execution_bundles),
        "transaction execution bundle request IDs are not unique",
    )
    index = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_model_parity_materialization_transaction",
        "run_id": run_id,
        "final_materialization_path": final_root.relative_to(root).as_posix(),
        "document_count": 32,
        "files": files,
        "files_sha256": _sha256_bytes(_canonical_json(files)),
        "source_inventory": source_rows,
        "source_inventory_sha256": _sha256_bytes(_canonical_json(source_rows)),
        "output_segments": list(output_segments),
        "output_segments_sha256": _sha256_bytes(
            _canonical_json(list(output_segments))
        ),
        "execution_bundle_count": len(execution_bundles),
        "execution_bundles": list(execution_bundles),
        "execution_bundles_sha256": _sha256_bytes(
            _canonical_json(list(execution_bundles))
        ),
        "claimed_aggregates_accepted": False,
        "synthetic_or_mock_evidence_accepted": False,
    }
    index["transaction_sha256"] = _sha256_bytes(_canonical_json(index))
    return _write_json_file(staging_root / "transaction_index.json", index)


def _collect_production_evidence(
    preflight: _Preflight,
    *,
    materialization_dir: Path | str,
    ffmpeg_executable: Path | str,
    execution_config_path: Path | str,
    binding_set_dir: Path | str,
    runtime_probe_paths: Mapping[str, Path | str],
    socket_dir: Path | str,
    after_directory_publish_step: Callable[[str], None] | None = None,
) -> ProductionCollection:
    root = preflight.root
    final_root = _safe_output_path(
        root, materialization_dir, label="materialization directory", must_not_exist=False
    )
    run_id = final_root.name
    _require(
        _STABLE_ID_RE.fullmatch(run_id) is not None
        and len(run_id) <= 48
        and not any(token in run_id.lower() for token in _FORBIDDEN_PRODUCTION_TOKENS),
        "materialization run ID is invalid",
    )

    execution_config, _runtime_probes, bindings, bridge_payload = (
        _validated_production_dependencies(
            preflight,
            execution_config_path=execution_config_path,
            binding_set_dir=binding_set_dir,
            runtime_probe_paths=runtime_probe_paths,
        )
    )
    socket_namespace = _worker_socket_namespace_contract(root, socket_dir)
    socket_root = socket_namespace.path

    _create_physical_directory_chain(root, final_root.parent)
    staging_root = Path(
        tempfile.mkdtemp(prefix=f".{run_id}.staging.", dir=final_root.parent)
    )
    _require(not _is_reparse(staging_root), "materialization staging is a reparse point")
    try:
        cleanup_anchor = OwnedStagingDirectoryV1.capture(
            staging_root,
            expected_parent=final_root.parent,
            expected_prefix=f".{run_id}.staging.",
            label="model-parity materialization staging",
        )
    except OwnedStagingCleanupV1Error as error:
        raise MaterializerError(str(error)) from error

    writers: list[_BundleWriter] = []
    committed = False
    try:
        for name in ("support", "documents", "bundles", "execution_bundles"):
            (staging_root / name).mkdir()
        for branch in BRANCHES:
            (staging_root / "documents" / branch).mkdir()

        preprocessing_record = _write_new_file(
            staging_root / "support" / "checkpoint_gstreamer_analytics_bridge.py",
            bridge_payload,
        )
        dataset_document, dataset_aggregate = _dataset_document(preflight)
        dataset_record = _write_json_file(
            staging_root / "support" / "dataset_manifest.json", dataset_document
        )

        raw_writers = {
            branch: _BundleWriter(staging_root / "bundles" / f"{branch}.rgb24.bin")
            for branch in BRANCHES
        }
        tensor_writers = {
            branch: _BundleWriter(staging_root / "bundles" / f"{branch}.tensor.f32le.bin")
            for branch in BRANCHES
        }
        output_writers = {
            (branch, resource): _BundleWriter(
                staging_root
                / "bundles"
                / f"{branch}.{RESOURCE_LABELS[resource]}.output.f32le.bin"
            )
            for branch in BRANCHES
            for resource in RESOURCES
        }
        writers.extend(raw_writers.values())
        writers.extend(tensor_writers.values())
        writers.extend(output_writers.values())

        plan = build_deterministic_sample_plan()
        by_source: dict[str, list[SamplePlan]] = defaultdict(list)
        for row in plan:
            by_source[row.relative_path].append(row)
        decoded: dict[str, DecodedFrame] = {}
        decoder = ProductionFfmpegDecoder(
            ffmpeg_executable, project_root=root, staging_root=staging_root
        )
        for relative in sorted(by_source):
            for frame in decoder.decode(preflight.kpp_records[relative], by_source[relative]):
                _require(frame.plan.sample_id not in decoded, "decoder emitted a duplicate sample")
                decoded[frame.plan.sample_id] = frame
        _require(set(decoded) == {row.sample_id for row in plan}, "decoder output coverage is partial")
        decoder_contract = decoder.finalize_contract(
            project_root=root, final_root=final_root
        )

        preprocessing_sha = _sha256_bytes(
            _canonical_json(preflight.base_manifest["preprocessing_contract"])
        )
        preprocessing_argv_sha = canonical_sha256(
            {
                "callable": "checkpoint_gstreamer_analytics_bridge.preprocess_gstreamer_frame",
                "input_format": "RGB",
                "output_serialization": "raw_f32_le_c_contiguous_v1",
                "contract_sha256": preprocessing_sha,
            }
        )
        producer_contract = {
            "decoder": {
                "name": decoder_contract.name,
                "version": decoder_contract.version,
                "runtime_image_id": decoder_contract.runtime_image_id,
                "implementation": _final_reference(
                    root,
                    decoder_contract.executable_copy,
                    staging_root=staging_root,
                    final_root=final_root,
                    sized=True,
                ),
                "canonical_argv_sha256": decoder_contract.canonical_argv_sha256,
                "pixel_format": "rgb24",
            },
            "preprocessing": {
                "implementation": _final_reference(
                    root,
                    preprocessing_record,
                    staging_root=staging_root,
                    final_root=final_root,
                    sized=True,
                ),
                "canonical_argv_sha256": preprocessing_argv_sha,
                "contract_sha256": preprocessing_sha,
            },
        }

        staged_samples: dict[str, dict[str, Any]] = {}
        tensors: dict[str, tuple[bytes, dict[str, Any]]] = {}
        file_indices = {
            row["path"]: (row["file_id"], row["file_index"], row["sha256"])
            for row in dataset_document["files"]
        }
        for row in plan:
            frame = decoded[row.sample_id]
            raw_segment = raw_writers[row.branch].append(frame.rgb)
            source = preflight.base_manifest["source_registry"][
                preflight.base_manifest["workload_slots"][row.branch]["source_ref"]
            ]
            try:
                tensor, tensor_descriptor = preprocess_gstreamer_frame(
                    frame.rgb,
                    frame={
                        "format": "RGB",
                        "width": frame.width,
                        "height": frame.height,
                        "stride": frame.stride,
                    },
                    preprocessing_contract=preflight.base_manifest["preprocessing_contract"],
                    expected_contract_sha256=preprocessing_sha,
                    tensor_name=source["input"]["name"],
                )
            except (ContractError, ProtocolError, ValueError) as error:
                raise MaterializerError(f"frozen preprocessing failed: {error}") from error
            _require(
                tensor_descriptor
                == {
                    "name": source["input"]["name"],
                    "dtype": "float32",
                    "layout": "NCHW",
                    "shape": [1, 3, 224, 224],
                    "byte_length": len(tensor),
                    "sha256": _sha256_bytes(tensor),
                    "preprocessing_contract_sha256": preprocessing_sha,
                },
                "preprocessing tensor descriptor drifted",
            )
            tensor_segment = tensor_writers[row.branch].append(tensor)
            tensors[row.sample_id] = (tensor, tensor_descriptor)
            file_id, file_index, dataset_file_sha = file_indices[row.relative_path]
            physical_payload = {
                "dataset_aggregate_sha256": dataset_aggregate,
                "dataset_file_id": file_id,
                "dataset_file_sha256": dataset_file_sha,
                "codec": row.codec,
                "file_index": file_index,
                "stream_index": frame.plan.stream_index,
                "frame_index": frame.observed_frame_index,
                "pts_ns": frame.pts_ns,
                "raw_frame_sha256": raw_segment["segment_sha256"],
            }
            staged_samples[row.sample_id] = {
                "sample_id": row.sample_id,
                "physical_sample_sha256": _sha256_bytes(_canonical_json(physical_payload)),
                "dataset_file_id": file_id,
                "dataset_file_sha256": dataset_file_sha,
                "codec": row.codec,
                "file_index": file_index,
                "stream_index": frame.plan.stream_index,
                "frame_index": frame.observed_frame_index,
                "pts_ns": frame.pts_ns,
                "input_sha256": raw_segment["segment_sha256"],
                "preprocessed_tensor_sha256": tensor_segment["segment_sha256"],
                "_raw_segment": raw_segment,
                "_tensor_segment": tensor_segment,
            }

        raw_records = {branch: writer.close() for branch, writer in raw_writers.items()}
        tensor_records = {branch: writer.close() for branch, writer in tensor_writers.items()}

        corpus_documents: dict[tuple[str, str], dict[str, Any]] = {}
        for branch in BRANCHES:
            for role in ("calibration", "evaluation"):
                samples: list[dict[str, Any]] = []
                for row in plan:
                    if row.branch != branch or row.role != role:
                        continue
                    frame = decoded[row.sample_id]
                    staged = staged_samples[row.sample_id]
                    samples.append(
                        {
                            **{
                                key: value
                                for key, value in staged.items()
                                if not key.startswith("_")
                            },
                            "raw_frame": _descriptor(
                                final_reference=_final_reference(
                                    root,
                                    raw_records[branch],
                                    staging_root=staging_root,
                                    final_root=final_root,
                                    sized=True,
                                ),
                                segment=staged["_raw_segment"],
                                encoding="raw_bytes_v1",
                                dtype="uint8",
                                shape=[frame.height, frame.width, 3],
                                layout="HWC",
                                color_order="RGB",
                            ),
                            "preprocessed_tensor": _descriptor(
                                final_reference=_final_reference(
                                    root,
                                    tensor_records[branch],
                                    staging_root=staging_root,
                                    final_root=final_root,
                                    sized=True,
                                ),
                                segment=staged["_tensor_segment"],
                                encoding="raw_f32_le_c_contiguous_v1",
                                dtype="float32",
                                shape=[1, 3, 224, 224],
                                layout="NCHW",
                                color_order="RGB",
                            ),
                        }
                    )
                corpus_documents[(branch, role)] = {
                    "schema_version": 2,
                    "artifact_kind": "checkpoint_model_parity_corpus",
                    "branch": branch,
                    "workload_slot_id": preflight.base_manifest["workload_slots"][branch]["slot_id"],
                    "corpus_role": role,
                    "dataset_manifest": _final_reference(
                        root,
                        dataset_record,
                        staging_root=staging_root,
                        final_root=final_root,
                    ),
                    "dataset_aggregate_sha256": dataset_aggregate,
                    "producer_contract": producer_contract,
                    "sample_count": len(samples),
                    "samples": samples,
                    "samples_sha256": _sha256_bytes(_canonical_json(samples)),
                }

        response_records: dict[tuple[str, str], list[ValidatedNativeResponse]] = defaultdict(list)
        output_values: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        output_segments: list[dict[str, Any]] = []
        execution_ledger = _ExecutionBundleLedger(
            project_root=root,
            staging_root=staging_root,
            final_root=final_root,
            expected_coordinates={
                (row.branch, row.role, row.codec, row.sample_id, resource)
                for row in plan
                for resource in RESOURCES
            },
        )
        with socket_namespace.lifecycle(), NativeEndpointRunner(
            socket_dir=socket_root,
            materialized_bindings=bindings,
            execution_config=execution_config,
            project_root=root,
            request_bounds=_worker_request_bounds(plan),
        ) as runner:
            for branch in BRANCHES:
                for resource in RESOURCES:
                    _validate_capability_lineage(
                        branch=branch,
                        resource=resource,
                        capability=runner.capabilities[(branch, resource)],
                        binding=bindings.bindings[
                            (branch, "cpu" if resource == "openvino_cpu" else "gpu")
                        ],
                        manifest=preflight.base_manifest,
                        execution_config=execution_config,
                    )
            for row in plan:
                frame = decoded[row.sample_id]
                tensor, tensor_descriptor = tensors[row.sample_id]
                for resource in RESOURCES:
                    response = runner.infer(
                        branch=row.branch,
                        resource=resource,
                        sample=frame,
                        tensor=tensor,
                        tensor_descriptor=tensor_descriptor,
                        run_id=run_id,
                    )
                    values = decode_validated_fp32_output(
                        response.output, expected_values=1000
                    )
                    response_records[(row.branch, resource)].append(response)
                    segment = output_writers[(row.branch, resource)].append(response.output)
                    output_segments.append(
                        {
                            "branch": row.branch,
                            "resource": resource,
                            "sample_id": row.sample_id,
                            "input_sha256": staged_samples[row.sample_id]["input_sha256"],
                            "preprocessed_tensor_sha256": staged_samples[row.sample_id]["preprocessed_tensor_sha256"],
                            "encoding": "raw_f32_le_c_contiguous_v1",
                            "dtype": "float32",
                            "shape": [1, 1000],
                            **segment,
                        }
                    )
                    output_values[(row.branch, resource)].append(
                        {
                            "sample_id": row.sample_id,
                            "input_sha256": staged_samples[row.sample_id]["input_sha256"],
                            "preprocessed_tensor_sha256": staged_samples[row.sample_id]["preprocessed_tensor_sha256"],
                            "values": values,
                        }
                    )
                    execution_ledger.persist(
                        branch=row.branch,
                        role=row.role,
                        codec=row.codec,
                        sample_id=row.sample_id,
                        resource=resource,
                        response=response,
                        input_tensor=tensor,
                    )
        peer_identity_rows = [
            {
                "branch": branch,
                "resource": resource,
                "peer_identity": dict(runner.peer_identities[(branch, resource)]),
                "peer_identity_sha256": runner.peer_identities[
                    (branch, resource)
                ]["identity_sha256"],
            }
            for branch in BRANCHES
            for resource in RESOURCES
        ]
        _require(
            len(peer_identity_rows) == 8
            and all(
                row["peer_identity"][
                    "protocol_nonce_capability_handshake_performed"
                ]
                is True
                and row["peer_identity"][
                    "global_eight_worker_handshake_barrier_attested"
                ]
                is True
                for row in peer_identity_rows
            ),
            "native endpoint completed peer identity coverage is not exact 8",
        )
        _write_json_file(
            staging_root / "support" / "worker_peer_identity_attestation.json",
            {
                "schema_version": 1,
                "artifact_kind": (
                    "checkpoint_model_parity_worker_peer_identity_attestation"
                ),
                "worker_count": len(peer_identity_rows),
                "workers": peer_identity_rows,
                "workers_sha256": canonical_sha256(peer_identity_rows),
                "pid_visible_worker_count": sum(
                    row["peer_identity"][
                        "peer_pid_visible_in_controller_namespace"
                    ]
                    is True
                    for row in peer_identity_rows
                ),
                "namespace_hidden_worker_count": sum(
                    row["peer_identity"][
                        "peer_pid_visible_in_controller_namespace"
                    ]
                    is False
                    for row in peer_identity_rows
                ),
            },
        )
        execution_bundles = execution_ledger.finalize()
        output_records = {
            key: writer.close() for key, writer in output_writers.items()
        }
        for row in output_segments:
            record = output_records[(row["branch"], row["resource"])]
            row.update(
                _final_reference(
                    root,
                    record,
                    staging_root=staging_root,
                    final_root=final_root,
                    sized=True,
                )
            )

        evidence_records: dict[tuple[str, str], PhysicalFileRecord] = {}
        for branch in BRANCHES:
            slot = preflight.base_manifest["workload_slots"][branch]
            source = preflight.base_manifest["source_registry"][slot["source_ref"]]
            for role, evidence_name in (
                ("calibration", "calibration_corpus"),
                ("evaluation", "evaluation_corpus"),
            ):
                evidence_records[(branch, evidence_name)] = _write_json_file(
                    staging_root / "documents" / branch / f"{evidence_name}.json",
                    corpus_documents[(branch, role)],
                )
            for resource, prefix in (
                ("openvino_cpu", "cpu"),
                ("tensorrt_cuda", "cuda"),
            ):
                responses = response_records[(branch, resource)]
                _require(len(responses) == 60, "native response coordinate coverage is partial")
                capability = responses[0].capability
                _require(
                    all(response.capability == capability for response in responses),
                    "native capability drifted during collection",
                )
                probe_name = f"{prefix}_execution_probe"
                probe = build_execution_probe_document(
                    branch=branch,
                    slot=slot,
                    source=source,
                    resource=resource,
                    capability=capability,
                    sample_count=len(responses),
                )
                evidence_records[(branch, probe_name)] = _write_json_file(
                    staging_root / "documents" / branch / f"{probe_name}.json", probe
                )
                calibration_responses = [
                    response
                    for response in responses
                    if ".calibration." in response.request["request_id"]
                ]
                calibration_samples = [
                    {
                        "sample_id": decoded_plan.sample_id,
                        "service_time_ms": native_service_time_ms(response),
                    }
                    for response, decoded_plan in zip(
                        calibration_responses,
                        [
                            row
                            for row in plan
                            if row.branch == branch and row.role == "calibration"
                        ],
                    )
                ]
                _require(len(calibration_samples) == 30, "calibration timing coverage is partial")
                policy_name = f"{prefix}_policy_calibration"
                bindings_fields = _artifact_bindings(slot, source, resource)
                policy = {
                    "schema_version": 2,
                    "artifact_kind": "checkpoint_model_policy_calibration",
                    "branch": branch,
                    "workload_slot_id": slot["slot_id"],
                    "resource": resource,
                    **bindings_fields,
                    "runtime_image_id": capability["worker_image_id"],
                    "execution_probe_sha256": evidence_records[(branch, probe_name)].sha256,
                    "corpus_manifest_sha256": evidence_records[(branch, "calibration_corpus")].sha256,
                    "sample_count": len(calibration_samples),
                    "samples": calibration_samples,
                }
                evidence_records[(branch, policy_name)] = _write_json_file(
                    staging_root / "documents" / branch / f"{policy_name}.json", policy
                )
                evaluation_samples = [
                    sample
                    for sample in output_values[(branch, resource)]
                    if ".evaluation." in sample["sample_id"]
                ]
                _require(len(evaluation_samples) == 30, "evaluation output coverage is partial")
                raw_name = f"{prefix}_raw_output_bundle"
                output_sha = _sha256_bytes(
                    _canonical_json(
                        {
                            "classification_contract": preflight.base_manifest["classification_contract"],
                            "source_output": source["output"],
                        }
                    )
                )
                raw_document = {
                    "schema_version": 2,
                    "artifact_kind": "checkpoint_model_raw_output_bundle",
                    "branch": branch,
                    "workload_slot_id": slot["slot_id"],
                    "resource": resource,
                    **bindings_fields,
                    "runtime_image_id": capability["worker_image_id"],
                    "execution_probe_sha256": evidence_records[(branch, probe_name)].sha256,
                    "corpus_manifest_sha256": evidence_records[(branch, "evaluation_corpus")].sha256,
                    "preprocessing_contract_sha256": preprocessing_sha,
                    "output_contract_sha256": output_sha,
                    "tensor_name": source["output"]["name"],
                    "dtype": "float32",
                    "sample_shape": [1, 1000],
                    "sample_count": len(evaluation_samples),
                    "samples": evaluation_samples,
                }
                evidence_records[(branch, raw_name)] = _write_json_file(
                    staging_root / "documents" / branch / f"{raw_name}.json",
                    raw_document,
                )

        _require(
            set(evidence_records)
            == {(branch, name) for branch in BRANCHES for name in EVIDENCE_NAMES},
            "evidence document coverage is not exact 32",
        )
        evidence_refs = {
            key: _final_reference(
                root,
                record,
                staging_root=staging_root,
                final_root=final_root,
            )
            for key, record in evidence_records.items()
        }
        promoted_manifest = build_promoted_manifest(
            preflight.base_manifest, evidence_refs=evidence_refs
        )
        transaction_record = _write_transaction_index(
            root=root,
            staging_root=staging_root,
            final_root=final_root,
            run_id=run_id,
            source_inventory={
                **dict(preflight.kpp_records),
                preflight.dataset_config_record.relative_path: preflight.dataset_config_record,
                preflight.base_manifest_record.relative_path: preflight.base_manifest_record,
            },
            output_segments=output_segments,
            execution_bundles=execution_bundles,
        )
        _fsync_directory(staging_root)
        try:
            cleanup_anchor.seal_tree()
        except OwnedStagingCleanupV1Error as error:
            raise MaterializerError(str(error)) from error
        publication = commit_or_adopt_immutable_directory_v1(
            project_root=root,
            staging=staging_root,
            target=final_root,
            after_publish_step=after_directory_publish_step,
        )
        try:
            cleanup_anchor.cleanup_after_publication(final_target=final_root)
        except OwnedStagingCleanupV1Error as error:
            raise MaterializerError(str(error)) from error
        committed = True
        transaction_final = verify_physical_file(
            root,
            (final_root / "transaction_index.json").relative_to(root),
            expected_sha256=transaction_record.sha256,
            expected_size=transaction_record.size_bytes,
            label="committed materialization transaction index",
        )
        return ProductionCollection(
            _PRODUCTION_TOKEN,
            project_root=root,
            materialization_dir=final_root,
            base_manifest_record=preflight.base_manifest_record,
            base_manifest=preflight.base_manifest,
            evidence_refs=evidence_refs,
            promoted_manifest=promoted_manifest,
            transaction_index_record=transaction_final,
        )
    finally:
        for writer in writers:
            writer.abort()
        intent_key = hashlib.sha256(
            final_root.relative_to(root).as_posix().encode("utf-8")
        ).hexdigest()
        intent_exists = os.path.lexists(root / JOURNAL_ROOT / f"{intent_key}.json")
        try:
            if not committed and not intent_exists:
                try:
                    if not cleanup_anchor.sealed:
                        cleanup_anchor.seal_tree()
                    cleanup_anchor.cleanup_after_publication(final_target=final_root)
                except OwnedStagingCleanupV1Error as error:
                    raise MaterializerError(str(error)) from error
        finally:
            cleanup_anchor.close()


def _yaml_bytes(value: Mapping[str, Any]) -> bytes:
    try:
        rendered = yaml.safe_dump(
            dict(value),
            sort_keys=False,
            allow_unicode=False,
            default_flow_style=False,
        ).encode("utf-8")
    except yaml.YAMLError as error:
        raise MaterializerError(f"promoted manifest cannot be serialized: {error}") from error
    _require(b".staging" not in rendered, "promoted manifest contains a staging reference")
    return rendered


def _verify_collection_final_paths(collection: ProductionCollection) -> None:
    root = collection.project_root
    materialization = _physical_directory(
        collection.materialization_dir, label="committed materialization"
    )
    _require(root in materialization.parents, "committed materialization escaped project_root")
    _require(
        collection.transaction_index_record is not None,
        "committed materialization lacks transaction index binding",
    )
    transaction = verify_physical_file(
        root,
        collection.transaction_index_record.path.relative_to(root),
        expected_sha256=collection.transaction_index_record.sha256,
        expected_size=collection.transaction_index_record.size_bytes,
        label="committed materialization transaction index",
    )
    _require(
        transaction.identity == collection.transaction_index_record.identity,
        "committed transaction index stable stat drifted",
    )
    for key, reference in collection.evidence_refs.items():
        _read_physical_file(
            root,
            reference["path"],
            expected_sha256=reference["sha256"],
            expected_size=None,
            label=f"committed evidence {key[0]}/{key[1]}",
        )
    base = verify_physical_file(
        root,
        collection.base_manifest_record.path.relative_to(root),
        expected_sha256=collection.base_manifest_record.sha256,
        expected_size=collection.base_manifest_record.size_bytes,
        label="frozen model-parity manifest",
    )
    _require(
        base.identity == collection.base_manifest_record.identity,
        "frozen model-parity manifest stable stat drifted",
    )


def promote_model_parity_evidence(
    collection: ProductionCollection,
    *,
    accepted_manifest_path: Path | str,
    after_manifest_publish_step: Callable[[str], None] | None = None,
) -> PromotionResult:
    """Assess final-path evidence and write the accepted manifest last, or nothing."""

    if type(collection) is not ProductionCollection or collection._token is not _PRODUCTION_TOKEN:
        raise TypeError("promotion requires an internal ProductionCollection")
    root = collection.project_root
    accepted = _safe_output_path(
        root,
        accepted_manifest_path,
        label="accepted manifest",
        must_not_exist=False,
    )
    _require(
        accepted.suffix.lower() in {".yaml", ".yml"},
        "accepted manifest must be YAML",
    )
    _require(
        accepted != collection.base_manifest_record.path,
        "accepted manifest must be distinct from frozen manifest",
    )
    _require(accepted.parent.is_dir(), "accepted manifest parent is missing")
    _require(
        not _is_reparse(accepted.parent) and accepted.parent.resolve() == accepted.parent,
        "accepted manifest parent is unsafe",
    )
    payload = _yaml_bytes(collection.promoted_manifest)

    if accepted.exists() or os.path.lexists(accepted):
        existing, existing_payload = _read_physical_file(
            root,
            accepted.relative_to(root),
            expected_sha256=None,
            expected_size=None,
            label="existing accepted manifest",
        )
        _require(existing_payload == payload, "accepted manifest immutable collision")
        try:
            existing_manifest = load_parity_manifest(existing.path)
        except ContractError as error:
            raise MaterializerError(f"existing accepted manifest is invalid: {error}") from error
        expected_loaded = {key: value for key, value in existing_manifest.items() if key != "identity"}
        _require(
            expected_loaded == collection.promoted_manifest,
            "accepted manifest idempotence content mismatch",
        )
        _verify_collection_final_paths(collection)
        assessment = assess_model_parity(existing.path, project_root=root)
        _require(
            assessment.get("publication_ready") is True,
            "existing accepted manifest is no longer publication-ready",
        )
        return PromotionResult(existing, assessment)

    _verify_collection_final_paths(collection)
    candidate = accepted.parent / f".{accepted.name}.candidate.{os.getpid()}"
    _require(
        not candidate.exists() and not os.path.lexists(candidate),
        "promotion candidate collision",
    )
    candidate_record: PhysicalFileRecord | None = None
    candidate_anchor: OwnedStagingFileV1 | None = None
    try:
        candidate_record = _write_new_file(candidate, payload)
        try:
            candidate_anchor = OwnedStagingFileV1.capture(
                candidate, label="accepted model-parity candidate"
            )
        except OwnedStagingCleanupV1Error as error:
            raise MaterializerError(str(error)) from error
        try:
            loaded = load_parity_manifest(candidate)
        except ContractError as error:
            raise MaterializerError(f"promoted candidate manifest is invalid: {error}") from error
        loaded_without_identity = {key: value for key, value in loaded.items() if key != "identity"}
        _require(
            loaded_without_identity == collection.promoted_manifest,
            "promoted candidate manifest roundtrip drifted",
        )
        # The assessor dereferences only final materialization paths from this candidate.
        assessment = assess_model_parity(candidate, project_root=root)
        _require(
            type(assessment) is dict
            and type(assessment.get("blockers")) is list
            and type(assessment.get("publication_ready")) is bool,
            "model-parity assessor returned an invalid result",
        )
        if assessment["publication_ready"] is not True:
            raise MaterializerError(
                "model-parity evidence is not publication-ready: "
                + ", ".join(str(item) for item in assessment["blockers"])
            )
        _verify_collection_final_paths(collection)
        custody: PhysicalRootCustodyV1 | None = None
        try:
            custody = PhysicalRootCustodyV1.open(
                root, label="accepted model-parity project root"
            )
            custody.commit_or_adopt_exact_identity(
                accepted.relative_to(root).as_posix(),
                payload,
                label="accepted model-parity manifest",
                mode=0o444,
                create_parents=False,
                after_publish_step=after_manifest_publish_step,
            )
            custody.verify()
        except PublicationPhysicalIoV1Error as error:
            raise MaterializerError(
                "accepted model-parity manifest atomic commit/adoption failed"
            ) from error
        finally:
            if custody is not None:
                custody.close()
        result = verify_physical_file(
            root,
            accepted.relative_to(root),
            expected_sha256=_sha256_bytes(payload),
            expected_size=len(payload),
            label="accepted model-parity manifest",
        )
        return PromotionResult(result, assessment)
    finally:
        try:
            if candidate_record is not None and candidate_anchor is not None:
                try:
                    candidate_anchor.unlink_owned(final_target=accepted)
                except OwnedStagingCleanupV1Error as error:
                    raise MaterializerError(str(error)) from error
        finally:
            if candidate_anchor is not None:
                candidate_anchor.close()


def materialize_and_promote_model_parity(
    *,
    project_root: Path | str,
    dataset_manifest_path: Path | str,
    base_manifest_path: Path | str,
    materialization_dir: Path | str,
    accepted_manifest_path: Path | str,
    accepted_assessment_path: Path | str | None = None,
    acceptance_receipt_path: Path | str | None = None,
    ffmpeg_executable: Path | str,
    execution_config_path: Path | str,
    binding_set_dir: Path | str,
    runtime_probe_paths: Mapping[str, Path | str],
    socket_dir: Path | str,
) -> PromotionResult:
    """Run the only production path; no decoder/runner injection is accepted."""

    preflight = _preflight_real_inputs(
        project_root=project_root,
        dataset_manifest_path=dataset_manifest_path,
        base_manifest_path=base_manifest_path,
        materialization_dir=materialization_dir,
        accepted_manifest_path=accepted_manifest_path,
    )
    collection = _collect_production_evidence(
        preflight,
        materialization_dir=materialization_dir,
        ffmpeg_executable=ffmpeg_executable,
        execution_config_path=execution_config_path,
        binding_set_dir=binding_set_dir,
        runtime_probe_paths=runtime_probe_paths,
        socket_dir=socket_dir,
    )
    promoted = promote_model_parity_evidence(
        collection, accepted_manifest_path=accepted_manifest_path
    )
    accepted_manifest = Path(accepted_manifest_path)
    if accepted_assessment_path is None:
        accepted_assessment_path = accepted_manifest.with_name(
            f"{accepted_manifest.stem}.assessment.json"
        )
    if acceptance_receipt_path is None:
        acceptance_receipt_path = accepted_manifest.with_name(
            f"{accepted_manifest.stem}.acceptance_receipt.json"
        )
    root = _physical_root(project_root)
    assessment = _safe_output_path(
        root,
        accepted_assessment_path,
        label="accepted parity assessment",
        must_not_exist=False,
    )
    receipt = _safe_output_path(
        root,
        acceptance_receipt_path,
        label="parity acceptance receipt",
        must_not_exist=False,
    )
    assessment_exists = assessment.exists() or os.path.lexists(assessment)
    receipt_exists = receipt.exists() or os.path.lexists(receipt)
    _require(
        assessment_exists == receipt_exists,
        "partial model-parity acceptance transaction is prohibited",
    )
    if receipt_exists:
        parity_acceptance = load_verified_model_parity_acceptance(
            project_root=root,
            receipt_path=receipt,
        )
    else:
        parity_acceptance = promote_model_parity_acceptance(
            project_root=root,
            accepted_manifest_path=promoted.accepted_manifest.path,
            accepted_assessment_path=assessment,
            acceptance_receipt_path=receipt,
        )
    return PromotionResult(
        promoted.accepted_manifest,
        promoted.assessment,
        parity_acceptance,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize and promote real frozen-KPP native model-parity evidence."
    )
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument(
        "--datasets", type=Path, default=PROJECT_ROOT / "configs" / "datasets.yaml"
    )
    parser.add_argument(
        "--base-manifest",
        type=Path,
        default=PROJECT_ROOT / "configs" / "checkpoint_analytics_model_parity.yaml",
    )
    parser.add_argument("--materialization-dir", type=Path, required=True)
    parser.add_argument(
        "--accepted-manifest",
        type=Path,
        default=PROJECT_ROOT
        / "configs"
        / "checkpoint_analytics_model_parity.accepted.yaml",
    )
    parser.add_argument(
        "--accepted-assessment",
        type=Path,
        default=PROJECT_ROOT
        / "configs"
        / "checkpoint_analytics_model_parity.accepted.assessment.json",
    )
    parser.add_argument(
        "--acceptance-receipt",
        type=Path,
        default=PROJECT_ROOT
        / "configs"
        / "checkpoint_analytics_model_parity.accepted.acceptance_receipt.json",
    )
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument(
        "--execution-config",
        type=Path,
        default=PROJECT_ROOT / "configs" / "analytics_execution_layer.yaml",
    )
    parser.add_argument("--binding-set", type=Path, required=True)
    parser.add_argument("--cpu-runtime-probe", type=Path, required=True)
    parser.add_argument("--gpu-runtime-probe", type=Path, required=True)
    parser.add_argument("--socket-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = materialize_and_promote_model_parity(
            project_root=args.project_root,
            dataset_manifest_path=args.datasets,
            base_manifest_path=args.base_manifest,
            materialization_dir=args.materialization_dir,
            accepted_manifest_path=args.accepted_manifest,
            accepted_assessment_path=args.accepted_assessment,
            acceptance_receipt_path=args.acceptance_receipt,
            ffmpeg_executable=args.ffmpeg,
            execution_config_path=args.execution_config,
            binding_set_dir=args.binding_set,
            runtime_probe_paths={
                "cpu": args.cpu_runtime_probe,
                "gpu": args.gpu_runtime_probe,
            },
            socket_dir=args.socket_dir,
        )
    except (
        MaterializerError,
        ModelParityAcceptanceError,
        ContractError,
        SidecarError,
        ProtocolError,
    ) as error:
        print(f"model parity materialization blocked: {error}", file=sys.stderr)
        return 78
    print(
        json.dumps(
            {
                "accepted_manifest": str(result.accepted_manifest.path),
                "accepted_manifest_sha256": result.accepted_manifest.sha256,
                "publication_ready": result.assessment["publication_ready"],
                "parity_acceptance_receipt_sha256": (
                    result.parity_acceptance["acceptance_identity_sha256"]
                    if result.parity_acceptance is not None
                    else None
                ),
            },
            sort_keys=True,
        )
    )
    return 0


__all__ = [
    "FROZEN_KPP_FILES",
    "KPP_DATASET_BY_CODEC",
    "MaterializerError",
    "NonPublicationCollection",
    "ProductionCollection",
    "PromotionResult",
    "build_deterministic_sample_plan",
    "build_execution_probe_document",
    "build_promoted_manifest",
    "collect_nonpublication_test_evidence",
    "decode_validated_fp32_output",
    "materialize_and_promote_model_parity",
    "native_service_time_ms",
    "promote_model_parity_evidence",
    "verify_physical_file",
]


if __name__ == "__main__":
    raise SystemExit(main())
