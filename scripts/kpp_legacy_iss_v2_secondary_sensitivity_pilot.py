#!/usr/bin/env python3
"""Plan one fail-closed, candidate-bound, nonpublication KPP v2 GPU pilot.

This module is deliberately planning-only.  It never imports a Docker client,
spawns a process, reads media/tensor payloads, performs inference, or writes an
artifact.  Docker image availability is an external caller assertion and is
treated as missing unless the exact frozen image ID is supplied.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import ntpath
import os
import re
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import kpp_legacy_iss_v2_secondary_sensitivity_decision as decision_contract


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
CORPUS_ROLES = ("calibration", "evaluation")
CODECS = ("h264", "h265")
BRANCH_BINDINGS: dict[str, dict[str, str]] = {
    "plate_number": {
        "workload_slot_id": "opaque_rn18",
        "source_ref": "resnet18_v1_7",
        "source_role": "front_gate",
    },
    "vehicle_type": {
        "workload_slot_id": "opaque_rn34",
        "source_ref": "resnet34_v1_7",
        "source_role": "front_gate",
    },
    "damage": {
        "workload_slot_id": "opaque_rn50",
        "source_ref": "resnet50_v1_12",
        "source_role": "front_gate",
    },
    "foreign_object": {
        "workload_slot_id": "opaque_rn101",
        "source_ref": "resnet101_v1_7",
        "source_role": "underbody",
    },
}

RECEIPT_NAME = "kpp_legacy_iss_v2_model_corpus_candidate_receipt.json"
RECEIPT_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_model_corpus_candidate_receipt"
)
CORPUS_ARTIFACT_KIND = "vast_kpp_legacy_iss_v2_model_corpus_candidate"
PLAN_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_secondary_sensitivity_nonpublication_pilot_plan"
)
ASSESSMENT_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_secondary_sensitivity_nonpublication_pilot_assessment"
)
CANDIDATE_RECEIPT_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-model-corpus-candidate-receipt:v1\0"
)
PLAN_DOMAIN = b"VAST:kpp-legacy-iss-v2-nonpublication-pilot-plan:v1\0"
ASSESSMENT_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-nonpublication-pilot-assessment:v1\0"
)

TENSOR_SEGMENT_BYTES = 1 * 3 * 224 * 224 * 4
TENSORRT_IMAGE = "vast/analytics-tensorrt-worker:v2"
TENSORRT_IMAGE_ID = (
    "sha256:29ad51f4057f5aa77eb18e572c5055ed465fac39d49365d8eb5ffafe4fe8001f"
)
TENSORRT_BASE_IMAGE_ID = (
    "sha256:277bb99b1b23b5b763332041703905242a1238c3faeb72533aa6045c9d2d7489"
)
TENSORRT_ENTRYPOINT = "/opt/vast/bin/vast_tensorrt_worker"
TENSORRT_GPU_UUID = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
TENSORRT_ENGINE_PINS: dict[str, dict[str, object]] = {
    "plate_number": {
        "model_id": "opaque_rn18",
        "source_ref": "resnet18_v1_7",
        "engine_path": (
            "models/parity/derived/tensorrt-8.6.1.6-cuda12.2.2-cc86-"
            "fp32-static-b1/resnet18-v1-7.engine"
        ),
        "engine_sha256": (
            "07031b0493b5f1d9e27beffd51e622b74cc204505536f8a1618bde3e904d8fbe"
        ),
        "size_bytes": 62258620,
    },
    "vehicle_type": {
        "model_id": "opaque_rn34",
        "source_ref": "resnet34_v1_7",
        "engine_path": (
            "models/parity/derived/tensorrt-8.6.1.6-cuda12.2.2-cc86-"
            "fp32-static-b1/resnet34-v1-7.engine"
        ),
        "engine_sha256": (
            "bfa8303f89639d4033ee71389e77c009bf3bf1ab7e526e91949e0e0870f885d9"
        ),
        "size_bytes": 126793356,
    },
    "damage": {
        "model_id": "opaque_rn50",
        "source_ref": "resnet50_v1_12",
        "engine_path": (
            "models/parity/derived/tensorrt-8.6.1.6-cuda12.2.2-cc86-"
            "fp32-static-b1/resnet50-v1-12.engine"
        ),
        "engine_sha256": (
            "ecd41a7f7037a233da5629f87ff8d51e455b582c996963815a085cd139c3a7a5"
        ),
        "size_bytes": 118354276,
    },
    "foreign_object": {
        "model_id": "opaque_rn101",
        "source_ref": "resnet101_v1_7",
        "engine_path": (
            "models/parity/derived/tensorrt-8.6.1.6-cuda12.2.2-cc86-"
            "fp32-static-b1/resnet101-v1-7.engine"
        ),
        "engine_sha256": (
            "f981e1da75813ae30d18b03d422c37d6047245962d2b5552eb54c4deedb48f97"
        ),
        "size_bytes": 225698788,
    },
}

CANDIDATE_CLAIMS: dict[str, bool] = {
    "topology_load_proxy_candidate_only": True,
    "accuracy": False,
    "representative": False,
    "production_semantics": False,
    "statistical_independence": False,
    "model_acceptance": False,
    "runtime_acceptance": False,
    "materializer_source_bytes_externally_pinned_and_held": True,
    "local_python_source_set_externally_pinned_and_held": True,
    "executed_python_bytecode_attested": False,
    "launcher_execution_attested": False,
    "subprocess_environment_sanitized_and_bound": True,
    "subprocess_private_cwd_bound": True,
    "subprocess_dynamic_library_closure_attested": False,
    "directory_namespace_point_in_time_validated": True,
    "directory_namespace_immutability_attested": False,
    "future_candidate_tree_immutability_attested": False,
}

FAIL_CLOSED_FLAGS = (
    "publication_ready",
    "publication_capable",
    "publishable",
    "accepted_evidence",
    "accepted_evidence_written",
    "accepted_measurement_evidence_emitted",
    "evidence_accepted",
    "benchmark",
    "promotable",
    "publication_authorized",
    "canonical_publication_outputs_written",
    "publication_receipt_written",
    "result_accepted",
    "docker_spawned",
    "inference_performed",
)
_FALSE_FLAGS = {key: False for key in FAIL_CLOSED_FLAGS}
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_IMAGE_ID_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TIME_BASE_RE = re.compile(
    r"^(0|[1-9][0-9]{0,9})/([1-9][0-9]{0,9})$"
)
_MAX_DECISION_BYTES = 64 * 1024
_MAX_RECEIPT_BYTES = 1024 * 1024
_MAX_CORPUS_BYTES = 4 * 1024 * 1024
_MAX_JSON_DEPTH = 128
_READ_CHUNK_BYTES = 64 * 1024
_OPEN_SUPPORTS_DIR_FD = os.open in os.supports_dir_fd
_DESCRIPTOR_FIELDS = {"role", "path", "size_bytes", "sha256"}
_RECEIPT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "generation_id",
    "status",
    "promotable",
    "publication_authorized",
    "evidence_accepted",
    "pi_approval_status",
    "output_root",
    "source_materialization_receipt",
    "source_model_parity_manifest_sha256",
    "source_dataset_config",
    "dataset_aggregate_sha256",
    "branch_source_mapping",
    "sampling_rule",
    "sampling_rule_sha256",
    "tool_pins",
    "outputs",
    "claims",
    "authoritative_commit_record",
    "candidate_receipt_sha256",
}
_CORPUS_FIELDS = {
    "schema_version",
    "artifact_kind",
    "branch",
    "workload_slot_id",
    "source_ref",
    "source_role",
    "semantic_claim",
    "corpus_role",
    "promotable",
    "publication_authorized",
    "evidence_accepted",
    "pi_approval_status",
    "dataset_manifest",
    "dataset_aggregate_sha256",
    "producer_contract",
    "sample_count",
    "samples",
    "samples_sha256",
    "claims",
}
_PRODUCER_FIELDS = {
    "candidate_only",
    "sampling_rule_sha256",
    "preprocessing_contract_sha256",
    "materialization_receipt_sha256",
    "materialization_receipt_self_sha256",
    "model_parity_manifest_sha256",
    "tool_pins_sha256",
}
_TENSOR_FIELDS = {
    "path",
    "size_bytes",
    "sha256",
    "offset_bytes",
    "segment_size_bytes",
    "segment_sha256",
    "encoding",
    "dtype",
    "shape",
    "layout",
    "preprocessing_contract_sha256",
}
_RAW_FRAME_FIELDS = {
    "path",
    "size_bytes",
    "sha256",
    "offset_bytes",
    "segment_size_bytes",
    "segment_sha256",
    "encoding",
    "dtype",
    "shape",
    "layout",
    "color_order",
}
_SAMPLE_FIELDS = {
    "sample_id",
    "physical_sample_sha256",
    "branch",
    "source_role",
    "corpus_role",
    "stratum_index",
    "dataset_file_id",
    "dataset_file_sha256",
    "codec",
    "file_index",
    "stream_index",
    "frame_index",
    "source_pts",
    "source_time_base",
    "pts_ns",
    "input_sha256",
    "preprocessed_tensor_sha256",
    "raw_frame",
    "preprocessed_tensor",
}
_RAW_GEOMETRY = {
    "front_gate": (1920, 1080),
    "underbody": (1700, 236),
}
_FILE_INDEX = {"underbody": 0, "front_gate": 1}


class PilotContractError(RuntimeError):
    """A required nonpublication pilot binding is absent or has drifted."""


def canonical_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except RecursionError as exc:
        raise PilotContractError("JSON nesting exceeds contract limit") from exc
    except (TypeError, ValueError) as exc:
        raise PilotContractError(f"value is not canonical JSON: {exc}") from exc


def canonical_line(value: object) -> bytes:
    return canonical_json(value) + b"\n"


def candidate_receipt_self_sha(value: Mapping[str, object]) -> str:
    try:
        unsigned = copy.deepcopy(dict(value))
    except RecursionError as exc:
        raise PilotContractError("JSON nesting exceeds contract limit") from exc
    unsigned.pop("candidate_receipt_sha256", None)
    return hashlib.sha256(
        CANDIDATE_RECEIPT_DOMAIN + canonical_line(unsigned)
    ).hexdigest()


def _sha(value: object, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise PilotContractError(
            f"{label} must be a lowercase SHA-256 string"
        )
    return value


def _string(value: object, label: str) -> str:
    if type(value) is not str or not value:
        raise PilotContractError(f"{label} must be a nonempty string")
    return value


def _integer(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise PilotContractError(f"{label} must be an integer >= {minimum}")
    return value


def _source_time_base_parts(value: object) -> tuple[str, int, int]:
    if type(value) is not str:
        raise PilotContractError("source time base is invalid")
    matched = _TIME_BASE_RE.fullmatch(value)
    if matched is None:
        raise PilotContractError("source time base is invalid")
    try:
        numerator = int(matched.group(1))
        denominator = int(matched.group(2))
    except (ValueError, OverflowError) as exc:
        raise PilotContractError("source time base is invalid") from exc
    return value, numerator, denominator


def _candidate_claims_match(value: object) -> bool:
    return (
        type(value) is dict
        and set(value) == set(CANDIDATE_CLAIMS)
        and all(
            type(value[key]) is bool and value[key] is expected
            for key, expected in CANDIDATE_CLAIMS.items()
        )
    )


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise PilotContractError(f"{label} must be an object")
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise PilotContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _is_link_or_reparse(path: Path, observed: os.stat_result | None = None) -> bool:
    try:
        value = observed if observed is not None else path.lstat()
    except OSError:
        return True
    if stat.S_ISLNK(value.st_mode):
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if is_junction(path):
        return True
    attributes = int(getattr(value, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return bool(attributes & reparse)


def _stat_snapshot(value: os.stat_result) -> tuple[int, ...]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_nlink),
    )


def _directory_snapshot(path: Path, *, label: str) -> tuple[int, ...]:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise PilotContractError(f"cannot inspect {label}: {exc}") from exc
    if not stat.S_ISDIR(observed.st_mode) or _is_link_or_reparse(path, observed):
        raise PilotContractError(f"{label} must be one plain directory")
    return _stat_snapshot(observed)


def _normalized_windows_handle_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


def _windows_directory_information(handle: int, *, label: str) -> tuple[int, int]:
    import ctypes
    from ctypes import wintypes

    class ByHandleFileInformation(ctypes.Structure):
        _fields_ = [
            ("dwFileAttributes", wintypes.DWORD),
            ("ftCreationTime", wintypes.FILETIME),
            ("ftLastAccessTime", wintypes.FILETIME),
            ("ftLastWriteTime", wintypes.FILETIME),
            ("dwVolumeSerialNumber", wintypes.DWORD),
            ("nFileSizeHigh", wintypes.DWORD),
            ("nFileSizeLow", wintypes.DWORD),
            ("nNumberOfLinks", wintypes.DWORD),
            ("nFileIndexHigh", wintypes.DWORD),
            ("nFileIndexLow", wintypes.DWORD),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    information = ByHandleFileInformation()
    if not get_information(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise PilotContractError(
            f"cannot inspect {label} custody handle: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    if not information.dwFileAttributes & 0x00000010:
        raise PilotContractError(f"{label} custody object is not a directory")
    if information.dwFileAttributes & 0x00000400:
        raise PilotContractError(f"{label} custody object is a reparse point")
    file_index = (int(information.nFileIndexHigh) << 32) | int(
        information.nFileIndexLow
    )
    return int(information.dwVolumeSerialNumber), file_index


def _windows_directory_final_path(handle: int, *, label: str) -> str:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        wintypes.HANDLE,
        wintypes.LPWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
    ]
    get_final_path.restype = wintypes.DWORD
    required = get_final_path(wintypes.HANDLE(handle), None, 0, 0)
    if required == 0:
        raise PilotContractError(
            f"cannot size {label} final path: Win32 error {ctypes.get_last_error()}"
        )
    buffer = ctypes.create_unicode_buffer(required + 1)
    observed = get_final_path(
        wintypes.HANDLE(handle), buffer, len(buffer), 0
    )
    if observed == 0 or observed >= len(buffer):
        raise PilotContractError(
            f"cannot read {label} final path: Win32 error {ctypes.get_last_error()}"
        )
    return str(buffer.value)


class _DirectoryHold:
    def __init__(
        self,
        *,
        path: Path,
        label: str,
        path_snapshot: tuple[int, ...],
        handle_identity: tuple[int, ...],
        posix_fd: int | None = None,
        windows_handle: int | None = None,
        windows_final_path: str | None = None,
    ) -> None:
        self.path = path
        self.label = label
        self.path_snapshot = path_snapshot
        self.handle_identity = handle_identity
        self.posix_fd = posix_fd
        self.windows_handle = windows_handle
        self.windows_final_path = windows_final_path

    def verify_handle(self) -> None:
        if os.name == "nt":
            if self.windows_handle is None or self.windows_final_path is None:
                raise PilotContractError(f"{self.label} custody handle is closed")
            if (
                _windows_directory_information(
                    self.windows_handle, label=self.label
                )
                != self.handle_identity
                or _normalized_windows_handle_path(
                    _windows_directory_final_path(
                        self.windows_handle, label=self.label
                    )
                )
                != self.windows_final_path
            ):
                raise PilotContractError(f"{self.label} handle identity changed")
            return
        if self.posix_fd is None:
            raise PilotContractError(f"{self.label} custody handle is closed")
        try:
            observed = _stat_snapshot(os.fstat(self.posix_fd))
        except OSError as exc:
            raise PilotContractError(
                f"cannot inspect {self.label} custody handle: {exc}"
            ) from exc
        if observed != self.handle_identity:
            raise PilotContractError(f"{self.label} handle identity changed")

    def close(self) -> None:
        if os.name == "nt":
            handle = self.windows_handle
            self.windows_handle = None
            if handle is None:
                return
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            close_handle = kernel32.CloseHandle
            close_handle.argtypes = [wintypes.HANDLE]
            close_handle.restype = wintypes.BOOL
            if not close_handle(wintypes.HANDLE(handle)):
                raise PilotContractError(
                    f"cannot close {self.label} custody handle: "
                    f"Win32 error {ctypes.get_last_error()}"
                )
            return
        descriptor = self.posix_fd
        self.posix_fd = None
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError as exc:
                raise PilotContractError(
                    f"cannot close {self.label} custody handle: {exc}"
                ) from exc


def _open_directory_hold(
    path: Path, *, label: str, parent: _DirectoryHold | None
) -> _DirectoryHold:
    before = _directory_snapshot(path, label=label)
    if os.name != "nt":
        directory_flag = int(getattr(os, "O_DIRECTORY", 0))
        nofollow_flag = int(getattr(os, "O_NOFOLLOW", 0))
        if (
            directory_flag == 0
            or nofollow_flag == 0
            or (parent is not None and not _OPEN_SUPPORTS_DIR_FD)
        ):
            raise PilotContractError(
                "held directory custody is unsupported on this platform"
            )
        flags = os.O_RDONLY | directory_flag | nofollow_flag
        flags |= int(getattr(os, "O_CLOEXEC", 0))
        descriptor: int | None = None
        try:
            if parent is None:
                descriptor = os.open(path, flags)
            else:
                if parent.posix_fd is None or path.parent != parent.path:
                    raise PilotContractError("directory custody parent drifted")
                descriptor = os.open(path.name, flags, dir_fd=parent.posix_fd)
            os.set_inheritable(descriptor, False)
            opened = _stat_snapshot(os.fstat(descriptor))
            after = _directory_snapshot(path, label=label)
            if (
                before != after
                or (before[0], before[1], stat.S_IFMT(before[2]))
                != (opened[0], opened[1], stat.S_IFMT(opened[2]))
            ):
                raise PilotContractError(f"{label} changed while custody was acquired")
            return _DirectoryHold(
                path=path,
                label=label,
                path_snapshot=before,
                handle_identity=opened,
                posix_fd=descriptor,
            )
        except OSError as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise PilotContractError(
                f"cannot acquire {label} directory custody: {exc}"
            ) from exc
        except BaseException:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x00000001 | 0x00000080 | 0x00020000,
        0x00000001,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise PilotContractError(
            f"cannot acquire {label} no-delete custody: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    handle_value = int(handle)
    try:
        identity = _windows_directory_information(handle_value, label=label)
        final_path = _normalized_windows_handle_path(
            _windows_directory_final_path(handle_value, label=label)
        )
        if final_path != _normalized_windows_handle_path(str(path)):
            raise PilotContractError(f"{label} final path identity drifted")
        if parent is not None:
            if parent.windows_handle is None:
                raise PilotContractError("directory custody parent is closed")
            parent_path = _normalized_windows_handle_path(
                _windows_directory_final_path(
                    parent.windows_handle, label=parent.label
                )
            )
            if (
                ntpath.dirname(final_path) != parent_path
                or ntpath.normcase(ntpath.basename(final_path))
                != ntpath.normcase(path.name)
            ):
                raise PilotContractError("directory custody parent drifted")
        after = _directory_snapshot(path, label=label)
        if after != before:
            raise PilotContractError(f"{label} changed while custody was acquired")
        return _DirectoryHold(
            path=path,
            label=label,
            path_snapshot=before,
            handle_identity=identity,
            windows_handle=handle_value,
            windows_final_path=final_path,
        )
    except BaseException:
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(wintypes.HANDLE(handle_value))
        raise


class _NamespaceCustody:
    """Retain directory identity and use openat on POSIX for all leaf reads."""

    def __init__(self, root: _DirectoryHold) -> None:
        self._holds: dict[Path, _DirectoryHold] = {root.path: root}
        self._closed = False

    @classmethod
    def capture(
        cls, entries: Sequence[tuple[str, Path]]
    ) -> "_NamespaceCustody":
        if len(entries) != 1:
            raise PilotContractError("root custody requires exactly one directory")
        label, path = entries[0]
        return cls(_open_directory_hold(path, label=label, parent=None))

    def extend(
        self, entries: Sequence[tuple[str, Path]]
    ) -> "_NamespaceCustody":
        self.verify()
        for label, path in entries:
            if path in self._holds:
                continue
            parent = self._holds.get(path.parent)
            if parent is None:
                raise PilotContractError(
                    f"{label} parent lacks held directory custody"
                )
            hold = _open_directory_hold(path, label=label, parent=parent)
            self._holds[path] = hold
            self.verify()
        return self

    def path_snapshot(self, path: Path) -> tuple[int, ...]:
        hold = self._holds.get(path)
        if hold is None:
            raise PilotContractError("directory is not held")
        return hold.path_snapshot

    def parent_hold(self, path: Path) -> _DirectoryHold:
        hold = self._holds.get(path.parent)
        if hold is None:
            raise PilotContractError("file parent lacks held directory custody")
        return hold

    def verify(self) -> None:
        if self._closed:
            raise PilotContractError("directory custody is closed")
        for hold in self._holds.values():
            observed = _directory_snapshot(hold.path, label=hold.label)
            if observed != hold.path_snapshot:
                raise PilotContractError(f"{hold.label} identity changed")
            hold.verify_handle()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        first_error: BaseException | None = None
        for hold in reversed(tuple(self._holds.values())):
            try:
                hold.close()
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
        if first_error is not None:
            raise first_error

    def __enter__(self) -> "_NamespaceCustody":
        return self

    def __exit__(self, exc_type: object, exc: BaseException | None, tb: object) -> bool:
        try:
            self.close()
        except BaseException as close_error:
            if exc is None:
                raise
            exc.add_note(f"directory custody close failed: {close_error}")
        return False


def _leaf_snapshot(
    path: Path, *, label: str, maximum_bytes: int
) -> tuple[int, ...]:
    try:
        observed = path.lstat()
    except OSError as exc:
        raise PilotContractError(f"cannot inspect {label}: {exc}") from exc
    if (
        not stat.S_ISREG(observed.st_mode)
        or _is_link_or_reparse(path, observed)
        or observed.st_nlink != 1
    ):
        raise PilotContractError(f"{label} must be one regular nonlinked file")
    if observed.st_size <= 0 or observed.st_size > maximum_bytes:
        raise PilotContractError(f"{label} size is invalid")
    return _stat_snapshot(observed)


def _same_path_and_handle(
    path_before: tuple[int, ...],
    path_after: tuple[int, ...],
    handle_before: tuple[int, ...],
    handle_after: tuple[int, ...],
) -> bool:
    return (
        path_before == path_after
        and handle_before == handle_after
        and (
            path_before[0],
            path_before[1],
            stat.S_IFMT(path_before[2]),
            path_before[3],
            path_before[4],
        )
        == (
            handle_before[0],
            handle_before[1],
            stat.S_IFMT(handle_before[2]),
            handle_before[3],
            handle_before[4],
        )
        and path_before[6] == handle_before[6] == 1
    )


def _open_binary_custody(
    path: Path, *, label: str, custody: _NamespaceCustody
) -> BinaryIO:
    """Open a no-follow read handle; Windows also denies write/delete sharing."""

    if os.name != "nt":
        if not _OPEN_SUPPORTS_DIR_FD:
            raise PilotContractError(
                "handle-relative file custody is unsupported on this platform"
            )
        parent = custody.parent_hold(path)
        if parent.posix_fd is None:
            raise PilotContractError("file parent custody handle is closed")
        flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
        nofollow = int(getattr(os, "O_NOFOLLOW", 0))
        if nofollow == 0:
            raise PilotContractError(
                "handle-relative no-follow custody is unsupported on this platform"
            )
        flags |= nofollow
        descriptor: int | None = None
        try:
            descriptor = os.open(
                path.name, flags, dir_fd=parent.posix_fd
            )
            os.set_inheritable(descriptor, False)
            return os.fdopen(descriptor, "rb")
        except OSError as exc:
            if descriptor is not None:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            raise PilotContractError(f"cannot acquire {label} custody: {exc}") from exc

    import ctypes
    import msvcrt
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(
        str(path),
        0x80000000,
        0x00000001,
        None,
        3,
        0x00000080 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise PilotContractError(
            f"cannot acquire {label} no-write/no-delete custody: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    try:
        descriptor = msvcrt.open_osfhandle(
            int(handle), os.O_RDONLY | int(getattr(os, "O_BINARY", 0))
        )
    except BaseException:
        kernel32.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "rb")


def _read_handle_payload(
    source: BinaryIO,
    *,
    path: Path,
    label: str,
    maximum_bytes: int,
) -> tuple[bytes, str, tuple[int, ...], tuple[int, ...]]:
    del path  # Included so race tests bind the exact namespace leaf being read.
    try:
        before = _stat_snapshot(os.fstat(source.fileno()))
        chunks: list[bytes] = []
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = source.read(_READ_CHUNK_BYTES)
            if not chunk:
                break
            total += len(chunk)
            if total > maximum_bytes:
                raise PilotContractError(f"{label} exceeds its finite size limit")
            chunks.append(chunk)
            digest.update(chunk)
        after = _stat_snapshot(os.fstat(source.fileno()))
    except OSError as exc:
        raise PilotContractError(f"cannot read {label}: {exc}") from exc
    return b"".join(chunks), digest.hexdigest(), before, after


def _assert_json_depth(value: object) -> None:
    pending: list[tuple[object, int]] = [(value, 1)]
    while pending:
        current, depth = pending.pop()
        if depth > _MAX_JSON_DEPTH:
            raise PilotContractError("JSON nesting exceeds contract limit")
        if type(current) is dict:
            pending.extend((item, depth + 1) for item in current.values())
        elif type(current) is list:
            pending.extend((item, depth + 1) for item in current)


def _load_canonical_object(
    path: Path,
    *,
    label: str,
    maximum_bytes: int,
    custody: _NamespaceCustody,
) -> tuple[dict[str, Any], bytes, str]:
    custody.verify()
    before = _leaf_snapshot(path, label=label, maximum_bytes=maximum_bytes)
    with _open_binary_custody(path, label=label, custody=custody) as source:
        payload, payload_sha, handle_before, handle_after = _read_handle_payload(
            source,
            path=path,
            label=label,
            maximum_bytes=maximum_bytes,
        )
        during = _leaf_snapshot(path, label=label, maximum_bytes=maximum_bytes)
        if not _same_path_and_handle(
            before, during, handle_before, handle_after
        ):
            raise PilotContractError(f"{label} changed while reading")
    after = _leaf_snapshot(path, label=label, maximum_bytes=maximum_bytes)
    if after != before or len(payload) != before[3]:
        raise PilotContractError(f"{label} changed while reading")
    custody.verify()
    try:
        parsed = json.loads(
            payload.decode("ascii"), object_pairs_hook=_unique_object
        )
    except PilotContractError:
        raise
    except RecursionError as exc:
        raise PilotContractError("JSON nesting exceeds contract limit") from exc
    except (UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PilotContractError(f"{label} is not strict JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PilotContractError(f"{label} root must be an object")
    _assert_json_depth(parsed)
    if payload != canonical_line(parsed):
        raise PilotContractError(f"{label} is not canonical JSON")
    return parsed, payload, payload_sha


def _relative_parts(value: Path | str, label: str) -> tuple[str, ...]:
    if isinstance(value, Path):
        if value.is_absolute() or value.drive or value.root:
            raise PilotContractError(f"{label} must be project-relative")
        parts = tuple(value.parts)
    elif type(value) is str:
        raw = value
        if not raw or "\\" in raw or "\n" in raw or "\r" in raw:
            raise PilotContractError(f"{label} is not a canonical relative path")
        posix = PurePosixPath(raw)
        if posix.is_absolute():
            raise PilotContractError(f"{label} must be project-relative")
        parts = tuple(posix.parts)
    else:
        raise PilotContractError(f"{label} must be a path string")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise PilotContractError(f"{label} contains an unsafe component")
    return parts


def _safe_root(project_root: Path | str) -> tuple[Path, _NamespaceCustody]:
    if not isinstance(project_root, (Path, str)):
        raise PilotContractError("project root must be a path")
    lexical = Path(os.path.abspath(os.fspath(project_root)))
    try:
        before = _directory_snapshot(lexical, label="project root")
        if _is_link_or_reparse(lexical):
            raise PilotContractError("project root is missing or linked")
        resolved = lexical.resolve(strict=True)
    except OSError as exc:
        raise PilotContractError(f"cannot resolve project root: {exc}") from exc
    after = _directory_snapshot(resolved, label="project root")
    if before != after:
        raise PilotContractError("project root identity changed while resolving")
    # Windows may expand the caller's 8.3 spelling while resolving an otherwise
    # ordinary directory.  All descendants are bound to this canonical result.
    custody = _NamespaceCustody.capture((("project root", resolved),))
    if custody.path_snapshot(resolved) != after:
        custody.close()
        raise PilotContractError("project root identity changed while binding")
    return resolved, custody


def _under_root(
    root: Path,
    value: Path | str,
    *,
    label: str,
    directory: bool,
    custody: _NamespaceCustody,
) -> tuple[Path, str]:
    custody.verify()
    parts = _relative_parts(value, label)
    target = root.joinpath(*parts)
    cursor = root
    try:
        for part in parts:
            cursor = cursor / part
            if _is_link_or_reparse(cursor):
                raise PilotContractError(f"{label} chain contains a link")
        resolved = target.resolve(strict=True)
    except OSError as exc:
        raise PilotContractError(f"cannot resolve {label}: {exc}") from exc
    if resolved != target.absolute() or root not in resolved.parents:
        raise PilotContractError(f"{label} escaped the project root")
    if directory is not resolved.is_dir():
        kind = "directory" if directory else "file"
        raise PilotContractError(f"{label} must be a {kind}")
    custody.verify()
    return resolved, PurePosixPath(*parts).as_posix()


def _descriptor(value: object, *, label: str, output_root: str) -> dict[str, Any]:
    item = _mapping(value, label)
    if set(item) != _DESCRIPTOR_FIELDS:
        raise PilotContractError(f"{label} fields drifted")
    path = _string(item.get("path"), f"{label} path")
    role = _string(item.get("role"), f"{label} role")
    size = item.get("size_bytes")
    if (
        not role
        or not path.startswith(f"{output_root}/")
        or type(size) is not int
        or size <= 0
    ):
        raise PilotContractError(f"{label} values are invalid")
    _relative_parts(path, f"{label} path")
    return {
        "role": role,
        "path": path,
        "size_bytes": size,
        "sha256": _sha(item.get("sha256"), f"{label} SHA-256"),
    }


def _load_decision(
    root: Path, decision_path: Path | str, custody: _NamespaceCustody
) -> tuple[dict[str, Any], dict[str, object]]:
    path, logical = _under_root(
        root,
        decision_path,
        label="pilot decision",
        directory=False,
        custody=custody,
    )
    decision_custody = custody.extend((("pilot decision parent", path.parent),))
    loaded, payload, file_sha = _load_canonical_object(
        path,
        label="pilot decision",
        maximum_bytes=_MAX_DECISION_BYTES,
        custody=decision_custody,
    )
    declared = _sha(loaded.get("decision_sha256"), "decision self hash")
    unsigned = copy.deepcopy(loaded)
    unsigned.pop("decision_sha256", None)
    computed = hashlib.sha256(
        decision_contract.DECISION_DOMAIN
        + decision_contract.canonical_bytes(unsigned)
    ).hexdigest()
    if declared != computed:
        raise PilotContractError("decision self hash drifted")
    if loaded != decision_contract.expected_decision():
        raise PilotContractError("decision differs from the approved exact scope")
    if file_sha != decision_contract.EXPECTED_DECISION_FILE_SHA256:
        raise PilotContractError("decision file SHA-256 drifted")
    authorization = _mapping(loaded.get("pilot_authorization"), "pilot authorization")
    if not (
        authorization.get("authorized") is True
        and authorization.get("environments") == ["wsl", "docker", "gpu"]
        and authorization.get("nonpublication_only") is True
        and authorization.get("accepted_evidence_authorized") is False
        and authorization.get("publication_readiness_elevation_authorized") is False
        and authorization.get("network_download_authorized") is False
    ):
        raise PilotContractError("decision authorization is not fail closed")
    decision_custody.verify()
    return loaded, {
        "path": logical,
        "size_bytes": len(payload),
        "sha256": file_sha,
        "decision_sha256": declared,
    }


def _expected_branch_mapping() -> dict[str, dict[str, str]]:
    return {
        branch: {
            "branch": branch,
            **copy.deepcopy(binding),
            "semantic_claim": "topology_load_proxy_only",
            "tensor_name": "data",
        }
        for branch, binding in BRANCH_BINDINGS.items()
    }


def _bundle_ordinal(corpus_role: str, ordinal: int) -> int:
    return 2 * (ordinal // 2) + (0 if corpus_role == "calibration" else 1)


def _validate_raw_frame(
    value: object,
    *,
    branch: str,
    source_role: str,
    corpus_role: str,
    codec: str,
    ordinal: int,
    output_root: str,
    input_sha: str,
    bundle_descriptor: Mapping[str, Any],
) -> dict[str, object]:
    raw = _mapping(value, "raw frame")
    if set(raw) != _RAW_FRAME_FIELDS:
        raise PilotContractError("raw frame fields drifted")
    width, height = _RAW_GEOMETRY[source_role]
    segment_bytes = width * height * 3
    expected_path = f"{output_root}/raw_{codec}_{source_role}.rgb24.bin"
    expected_offset = _bundle_ordinal(corpus_role, ordinal) * segment_bytes
    shape = raw.get("shape")
    if not (
        type(raw.get("path")) is str
        and raw.get("path") == expected_path
        and type(raw.get("size_bytes")) is int
        and raw.get("size_bytes") == 30 * segment_bytes
        and type(raw.get("offset_bytes")) is int
        and raw.get("offset_bytes") == expected_offset
        and type(raw.get("segment_size_bytes")) is int
        and raw.get("segment_size_bytes") == segment_bytes
        and type(raw.get("encoding")) is str
        and raw.get("encoding") == "raw_bytes_v1"
        and type(raw.get("dtype")) is str
        and raw.get("dtype") == "uint8"
        and type(shape) is list
        and len(shape) == 3
        and all(type(item) is int for item in shape)
        and shape == [height, width, 3]
        and type(raw.get("layout")) is str
        and raw.get("layout") == "HWC"
        and type(raw.get("color_order")) is str
        and raw.get("color_order") == "RGB"
    ):
        raise PilotContractError(
            f"{branch}/{corpus_role}/{codec}/{ordinal:02d} raw frame contract drifted"
        )
    bundle_sha = _sha(raw.get("sha256"), "raw frame bundle SHA-256")
    segment_sha = _sha(raw.get("segment_sha256"), "raw frame segment SHA-256")
    if not (
        bundle_descriptor.get("role")
        == f"{codec}/{source_role} decoded RGB bundle"
        and bundle_descriptor.get("path") == expected_path
        and bundle_descriptor.get("size_bytes") == 30 * segment_bytes
        and bundle_descriptor.get("sha256") == bundle_sha
    ):
        raise PilotContractError("raw bundle descriptor binding drifted")
    if segment_sha != input_sha:
        raise PilotContractError("sample/raw-frame SHA-256 binding drifted")
    return {
        "path": expected_path,
        "size_bytes": 30 * segment_bytes,
        "sha256": bundle_sha,
        "offset_bytes": expected_offset,
        "segment_size_bytes": segment_bytes,
        "segment_sha256": segment_sha,
        "encoding": "raw_bytes_v1",
        "dtype": "uint8",
        "shape": [height, width, 3],
        "layout": "HWC",
        "color_order": "RGB",
    }


def _validate_tensor(
    value: object,
    *,
    branch: str,
    source_role: str,
    corpus_role: str,
    codec: str,
    ordinal: int,
    output_root: str,
    preprocessing_sha: str,
    bundle_descriptor: Mapping[str, Any],
) -> dict[str, object]:
    tensor = _mapping(value, "preprocessed tensor")
    if set(tensor) != _TENSOR_FIELDS:
        raise PilotContractError("preprocessed tensor fields drifted")
    expected_path = f"{output_root}/tensor_{codec}_{source_role}.f32.bin"
    expected_offset = _bundle_ordinal(corpus_role, ordinal) * TENSOR_SEGMENT_BYTES
    shape = tensor.get("shape")
    if not (
        type(tensor.get("path")) is str
        and tensor.get("path") == expected_path
        and type(tensor.get("size_bytes")) is int
        and tensor.get("size_bytes") == 30 * TENSOR_SEGMENT_BYTES
        and type(tensor.get("offset_bytes")) is int
        and tensor.get("offset_bytes") == expected_offset
        and type(tensor.get("segment_size_bytes")) is int
        and tensor.get("segment_size_bytes") == TENSOR_SEGMENT_BYTES
        and type(tensor.get("encoding")) is str
        and tensor.get("encoding") == "raw_f32_le_c_contiguous_v1"
        and type(tensor.get("dtype")) is str
        and tensor.get("dtype") == "float32"
        and type(shape) is list
        and len(shape) == 4
        and all(type(item) is int for item in shape)
        and shape == [1, 3, 224, 224]
        and type(tensor.get("layout")) is str
        and tensor.get("layout") == "NCHW"
        and type(tensor.get("preprocessing_contract_sha256")) is str
        and tensor.get("preprocessing_contract_sha256") == preprocessing_sha
    ):
        raise PilotContractError(
            f"{branch}/{corpus_role}/{codec}/{ordinal:02d} tensor contract drifted"
        )
    bundle_sha = _sha(tensor.get("sha256"), "tensor bundle SHA-256")
    segment_sha = _sha(tensor.get("segment_sha256"), "tensor segment SHA-256")
    if not (
        bundle_descriptor.get("role")
        == f"{codec}/{source_role} preprocessed tensor bundle"
        and bundle_descriptor.get("path") == expected_path
        and bundle_descriptor.get("size_bytes") == 30 * TENSOR_SEGMENT_BYTES
        and bundle_descriptor.get("sha256") == bundle_sha
    ):
        raise PilotContractError("tensor bundle descriptor binding drifted")
    return {
        "path": expected_path,
        "size_bytes": int(tensor["size_bytes"]),
        "sha256": bundle_sha,
        "offset_bytes": expected_offset,
        "segment_size_bytes": TENSOR_SEGMENT_BYTES,
        "segment_sha256": segment_sha,
        "encoding": "raw_f32_le_c_contiguous_v1",
        "dtype": "float32",
        "shape": [1, 3, 224, 224],
        "layout": "NCHW",
        "preprocessing_contract_sha256": preprocessing_sha,
    }


def _validate_corpus(
    document: Mapping[str, Any],
    *,
    branch: str,
    corpus_role: str,
    output_root: str,
    receipt: Mapping[str, Any],
    bundle_descriptors: Mapping[str, Mapping[str, Any]],
) -> tuple[dict[str, dict[str, object]], list[dict[str, object]]]:
    binding = BRANCH_BINDINGS[branch]
    if set(document) != _CORPUS_FIELDS or not (
        type(document.get("schema_version")) is int
        and document.get("schema_version") == 1
        and document.get("artifact_kind") == CORPUS_ARTIFACT_KIND
        and document.get("branch") == branch
        and document.get("workload_slot_id") == binding["workload_slot_id"]
        and document.get("source_ref") == binding["source_ref"]
        and document.get("source_role") == binding["source_role"]
        and document.get("semantic_claim")
        == "topology_load_proxy_candidate_only"
        and document.get("corpus_role") == corpus_role
        and document.get("promotable") is False
        and document.get("publication_authorized") is False
        and document.get("evidence_accepted") is False
        and document.get("pi_approval_status") == "required"
        and document.get("dataset_aggregate_sha256")
        == receipt["dataset_aggregate_sha256"]
        and _candidate_claims_match(document.get("claims"))
    ):
        raise PilotContractError(f"{branch}/{corpus_role} corpus fixed contract drifted")

    dataset = _descriptor(
        document.get("dataset_manifest"),
        label=f"{branch}/{corpus_role} dataset manifest",
        output_root=output_root,
    )
    if not (
        dataset["role"] == "candidate dataset manifest"
        and dataset["path"] == f"{output_root}/dataset_manifest.json"
    ):
        raise PilotContractError("candidate dataset manifest descriptor drifted")

    producer = _mapping(document.get("producer_contract"), "producer contract")
    if set(producer) != _PRODUCER_FIELDS or not (
        producer.get("candidate_only") is True
        and producer.get("sampling_rule_sha256")
        == receipt["sampling_rule_sha256"]
        and producer.get("model_parity_manifest_sha256")
        == receipt["source_model_parity_manifest_sha256"]
    ):
        raise PilotContractError("candidate producer contract drifted")
    preprocessing_sha = _sha(
        producer.get("preprocessing_contract_sha256"),
        "preprocessing contract SHA-256",
    )
    for field in (
        "materialization_receipt_sha256",
        "materialization_receipt_self_sha256",
        "tool_pins_sha256",
    ):
        _sha(producer.get(field), field)

    samples = document.get("samples")
    if (
        type(samples) is not list
        or type(document.get("sample_count")) is not int
        or document.get("sample_count") != 30
        or len(samples) != 30
        or type(document.get("samples_sha256")) is not str
        or document.get("samples_sha256")
        != hashlib.sha256(canonical_line(samples)).hexdigest()
    ):
        raise PilotContractError(f"{branch}/{corpus_role} sample set drifted")

    selected: dict[str, dict[str, object]] = {}
    provenance: list[dict[str, object]] = []
    for ordinal, raw_sample in enumerate(samples):
        sample = _mapping(raw_sample, f"{branch}/{corpus_role} sample {ordinal}")
        if set(sample) != _SAMPLE_FIELDS:
            raise PilotContractError(
                f"{branch}/{corpus_role} sample fields drifted"
            )
        codec = CODECS[ordinal % 2]
        sample_id = (
            f"kpp-v2-candidate.{branch}.{corpus_role}.{codec}.{ordinal:02d}"
        )
        if not (
            sample.get("sample_id") == sample_id
            and sample.get("branch") == branch
            and sample.get("source_role") == binding["source_role"]
            and sample.get("corpus_role") == corpus_role
            and sample.get("codec") == codec
        ):
            raise PilotContractError(
                f"{branch}/{corpus_role} sample identity/order drifted"
            )
        dataset_file_sha = _sha(
            sample.get("dataset_file_sha256"), "dataset file SHA-256"
        )
        input_sha = _sha(sample.get("input_sha256"), "input SHA-256")
        tensor_sample_sha = _sha(
            sample.get("preprocessed_tensor_sha256"),
            "preprocessed tensor SHA-256",
        )
        physical_sample_sha = _sha(
            sample.get("physical_sample_sha256"), "physical sample SHA-256"
        )
        source_time_base, numerator, denominator = _source_time_base_parts(
            sample.get("source_time_base")
        )
        stratum_index = 2 * ordinal + (
            0 if corpus_role == "calibration" else 1
        )
        frame_index = sample.get("frame_index")
        source_pts = sample.get("source_pts")
        pts_ns = sample.get("pts_ns")
        if not (
            type(sample.get("sample_id")) is str
            and type(sample.get("branch")) is str
            and type(sample.get("source_role")) is str
            and type(sample.get("corpus_role")) is str
            and type(sample.get("codec")) is str
            and type(sample.get("stratum_index")) is int
            and sample.get("stratum_index") == stratum_index
            and type(sample.get("dataset_file_id")) is str
            and sample.get("dataset_file_id")
            == f"kpp-legacy-iss-v2-{codec}-{binding['source_role']}"
            and type(sample.get("file_index")) is int
            and sample.get("file_index") == _FILE_INDEX[binding["source_role"]]
            and type(sample.get("stream_index")) is int
            and sample.get("stream_index") == 0
            and type(frame_index) is int
            and frame_index >= 0
            and type(source_pts) is int
            and source_pts >= 0
            and type(pts_ns) is int
            and pts_ns >= 0
        ):
            raise PilotContractError(
                f"{branch}/{corpus_role} sample provenance drifted"
            )
        exact_ns_numerator = source_pts * numerator * 1_000_000_000
        if abs(pts_ns * denominator - exact_ns_numerator) > denominator:
            raise PilotContractError(
                f"{branch}/{corpus_role} sample provenance drifted"
            )
        raw_bundle_path = (
            f"{output_root}/raw_{codec}_{binding['source_role']}.rgb24.bin"
        )
        tensor_bundle_path = (
            f"{output_root}/tensor_{codec}_{binding['source_role']}.f32.bin"
        )
        raw_bundle_descriptor = bundle_descriptors.get(raw_bundle_path)
        tensor_bundle_descriptor = bundle_descriptors.get(tensor_bundle_path)
        if raw_bundle_descriptor is None or tensor_bundle_descriptor is None:
            raise PilotContractError("bundle descriptor binding drifted")
        raw_frame = _validate_raw_frame(
            sample.get("raw_frame"),
            branch=branch,
            source_role=binding["source_role"],
            corpus_role=corpus_role,
            codec=codec,
            ordinal=ordinal,
            output_root=output_root,
            input_sha=input_sha,
            bundle_descriptor=raw_bundle_descriptor,
        )
        tensor = _validate_tensor(
            sample.get("preprocessed_tensor"),
            branch=branch,
            source_role=binding["source_role"],
            corpus_role=corpus_role,
            codec=codec,
            ordinal=ordinal,
            output_root=output_root,
            preprocessing_sha=preprocessing_sha,
            bundle_descriptor=tensor_bundle_descriptor,
        )
        if tensor_sample_sha != tensor["segment_sha256"]:
            raise PilotContractError("sample/tensor SHA-256 binding drifted")
        physical_payload = {
            "dataset_aggregate_sha256": receipt["dataset_aggregate_sha256"],
            "dataset_file_sha256": dataset_file_sha,
            "codec": codec,
            "source_role": binding["source_role"],
            "stream_index": 0,
            "frame_index": frame_index,
            "source_pts": source_pts,
            "source_time_base": source_time_base,
            "pts_ns": pts_ns,
            "decoded_frame_sha256": input_sha,
        }
        if physical_sample_sha != hashlib.sha256(
            canonical_line(physical_payload)
        ).hexdigest():
            raise PilotContractError("physical sample SHA-256 drifted")
        provenance.append(
            {
                "physical_sample_sha256": physical_sample_sha,
                "stratum_index": stratum_index,
                "dataset_file_id": sample["dataset_file_id"],
                "dataset_file_sha256": dataset_file_sha,
                "codec": codec,
                "file_index": sample["file_index"],
                "stream_index": 0,
                "frame_index": frame_index,
                "source_pts": source_pts,
                "source_time_base": source_time_base,
                "pts_ns": pts_ns,
                "input_sha256": input_sha,
                "preprocessed_tensor_sha256": tensor_sample_sha,
                "raw_frame": raw_frame,
                "preprocessed_tensor": tensor,
            }
        )
        if corpus_role == "calibration" and ordinal in (0, 1):
            selected[codec] = {
                "sample_id": sample_id,
                "branch": branch,
                "codec": codec,
                "corpus_role": "calibration",
                "source_role": binding["source_role"],
                "tensor": tensor,
            }
    if corpus_role == "calibration" and set(selected) != set(CODECS):
        raise PilotContractError(f"{branch} fixed calibration selection is incomplete")
    return selected, provenance


def _load_candidate(
    root: Path,
    candidate_root: Path | str,
    *,
    custody: _NamespaceCustody,
    approved_decision: Mapping[str, Any],
    expected_receipt_file_sha256: str,
    expected_receipt_self_sha256: str,
) -> tuple[dict[str, Any], dict[str, object], list[dict[str, object]]]:
    candidate, logical_root = _under_root(
        root,
        candidate_root,
        label="candidate root",
        directory=True,
        custody=custody,
    )
    root_parts = tuple(PurePosixPath(logical_root).parts)
    if len(root_parts) != 2 or root_parts[0] != "staging":
        raise PilotContractError("candidate root must be one direct staging child")
    candidate_custody = custody.extend(
        (
            ("candidate parent", candidate.parent),
            ("candidate root", candidate),
        )
    )
    receipt_path = candidate / RECEIPT_NAME
    receipt, payload, observed_file_sha = _load_canonical_object(
        receipt_path,
        label="candidate receipt",
        maximum_bytes=_MAX_RECEIPT_BYTES,
        custody=candidate_custody,
    )
    expected_file_sha = _sha(
        expected_receipt_file_sha256, "expected candidate receipt file SHA-256"
    )
    if observed_file_sha != expected_file_sha:
        raise PilotContractError("candidate receipt file SHA-256 drifted")
    expected_self_sha = _sha(
        expected_receipt_self_sha256, "expected candidate receipt self SHA-256"
    )
    declared_self_sha = _sha(
        receipt.get("candidate_receipt_sha256"), "candidate receipt self SHA-256"
    )
    if (
        declared_self_sha != expected_self_sha
        or declared_self_sha != candidate_receipt_self_sha(receipt)
    ):
        raise PilotContractError("candidate receipt self SHA-256 drifted")
    if set(receipt) != _RECEIPT_FIELDS or not (
        type(receipt.get("schema_version")) is int
        and receipt.get("schema_version") == 1
        and receipt.get("artifact_kind") == RECEIPT_ARTIFACT_KIND
        and receipt.get("generation_id") == "kpp_legacy_iss_v2"
        and receipt.get("status") == "materialized_nonpromotable_candidate"
        and receipt.get("promotable") is False
        and receipt.get("publication_authorized") is False
        and receipt.get("evidence_accepted") is False
        and receipt.get("pi_approval_status") == "required"
        and receipt.get("output_root") == logical_root
        and receipt.get("sampling_rule") == approved_decision["sampling_rule"]
        and _candidate_claims_match(receipt.get("claims"))
        and receipt.get("branch_source_mapping") == _expected_branch_mapping()
    ):
        raise PilotContractError("candidate receipt fixed contract drifted")
    sampling_sha = hashlib.sha256(
        canonical_line(receipt["sampling_rule"])
    ).hexdigest()
    if receipt.get("sampling_rule_sha256") != sampling_sha:
        raise PilotContractError("candidate sampling-rule SHA-256 drifted")
    _sha(receipt.get("dataset_aggregate_sha256"), "dataset aggregate SHA-256")
    _sha(
        receipt.get("source_model_parity_manifest_sha256"),
        "source model-parity manifest SHA-256",
    )

    outputs = receipt.get("outputs")
    if type(outputs) is not list:
        raise PilotContractError("candidate receipt outputs must be a list")
    checked_outputs = [
        _descriptor(item, label=f"candidate output {index}", output_root=logical_root)
        for index, item in enumerate(outputs)
    ]
    paths = [item["path"] for item in checked_outputs]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise PilotContractError("candidate output descriptors are not unique and ordered")
    by_path = {str(item["path"]): item for item in checked_outputs}
    expected_corpus_paths = {
        f"{logical_root}/corpus_{branch}_{corpus_role}.json"
        for branch in BRANCHES
        for corpus_role in CORPUS_ROLES
    }
    corpus_like = {
        path
        for path, item in by_path.items()
        if PurePosixPath(path).name.startswith("corpus_")
        or str(item["role"]).endswith(" corpus candidate")
    }
    if corpus_like != expected_corpus_paths:
        raise PilotContractError("candidate receipt exact 8 corpus descriptors drifted")
    expected_bundle_paths = {
        f"{logical_root}/{kind}_{codec}_{source_role}.{suffix}"
        for codec in CODECS
        for source_role in ("front_gate", "underbody")
        for kind, suffix in (
            ("raw", "rgb24.bin"),
            ("tensor", "f32.bin"),
        )
    }
    bundle_like = {
        path
        for path, item in by_path.items()
        if PurePosixPath(path).name.startswith(("raw_", "tensor_"))
        or str(item["role"]).endswith(" bundle")
    }
    if bundle_like != expected_bundle_paths:
        raise PilotContractError("candidate receipt exact bundle descriptors drifted")
    bundle_descriptors = {
        path: by_path[path] for path in sorted(expected_bundle_paths)
    }

    descriptors: list[dict[str, object]] = []
    requests_by_branch: dict[str, dict[str, dict[str, object]]] = {}
    shared_provenance: dict[tuple[str, str], list[dict[str, object]]] = {}
    branch_role_physical_addresses: dict[
        str, dict[str, set[tuple[object, object, object, object]]]
    ] = {
        branch: {} for branch in BRANCHES
    }
    for branch in BRANCHES:
        for corpus_role in CORPUS_ROLES:
            logical = f"{logical_root}/corpus_{branch}_{corpus_role}.json"
            descriptor = by_path.get(logical)
            if descriptor is None or descriptor["role"] != (
                f"{branch}/{corpus_role} corpus candidate"
            ):
                raise PilotContractError("candidate corpus descriptor role drifted")
            path = root.joinpath(*PurePosixPath(logical).parts)
            corpus, corpus_payload, corpus_file_sha = _load_canonical_object(
                path,
                label=f"{branch}/{corpus_role} corpus",
                maximum_bytes=_MAX_CORPUS_BYTES,
                custody=candidate_custody,
            )
            if not (
                len(corpus_payload) == descriptor["size_bytes"]
                and corpus_file_sha == descriptor["sha256"]
            ):
                raise PilotContractError("candidate corpus descriptor bytes drifted")
            selected, provenance = _validate_corpus(
                corpus,
                branch=branch,
                corpus_role=corpus_role,
                output_root=logical_root,
                receipt=receipt,
                bundle_descriptors=bundle_descriptors,
            )
            branch_role_physical_addresses[branch][corpus_role] = {
                (
                    item["dataset_file_id"],
                    item["dataset_file_sha256"],
                    item["stream_index"],
                    item["frame_index"],
                )
                for item in provenance
            }
            if (
                len(branch_role_physical_addresses[branch][corpus_role])
                != len(provenance)
            ):
                raise PilotContractError(
                    f"{branch}/{corpus_role} physical frame addresses are not unique"
                )
            if corpus_role == "evaluation" and (
                branch_role_physical_addresses[branch]["calibration"]
                & branch_role_physical_addresses[branch]["evaluation"]
            ):
                raise PilotContractError(
                    f"{branch} calibration/evaluation physical frames overlap"
                )
            provenance_key = (BRANCH_BINDINGS[branch]["source_role"], corpus_role)
            if provenance_key in shared_provenance:
                if provenance != shared_provenance[provenance_key]:
                    raise PilotContractError(
                        "shared-source sample provenance drifted"
                    )
            else:
                shared_provenance[provenance_key] = copy.deepcopy(provenance)
            if corpus_role == "calibration":
                requests_by_branch[branch] = selected
            descriptors.append(copy.deepcopy(descriptor))

    requests: list[dict[str, object]] = []
    for branch in BRANCHES:
        for codec in CODECS:
            request = copy.deepcopy(requests_by_branch[branch][codec])
            request["request_id"] = (
                f"kpp-v2-nonpublication-{branch}-{codec}-calibration-smoke-v1"
            )
            request["model"] = copy.deepcopy(TENSORRT_ENGINE_PINS[branch])
            requests.append(request)
    candidate_custody.verify()
    return receipt, {
        "root": logical_root,
        "receipt": {
            "path": f"{logical_root}/{RECEIPT_NAME}",
            "size_bytes": len(payload),
            "sha256": observed_file_sha,
            "candidate_receipt_sha256": declared_self_sha,
        },
        "dataset_aggregate_sha256": receipt["dataset_aggregate_sha256"],
        "sampling_rule_sha256": receipt["sampling_rule_sha256"],
        "corpora": descriptors,
    }, requests


def _identity(domain: bytes, core: Mapping[str, object]) -> str:
    return hashlib.sha256(domain + canonical_line(core)).hexdigest()


def build_pilot_plan(
    *,
    project_root: Path | str,
    decision_path: Path | str = decision_contract.DECISION_PATH,
    candidate_root: Path | str,
    role: str,
    expected_receipt_file_sha256: str,
    expected_receipt_self_sha256: str,
) -> dict[str, object]:
    if role not in {"secondary", "sensitivity"}:
        raise PilotContractError("pilot role must be secondary or sensitivity")
    root, custody = _safe_root(project_root)
    with custody:
        approved, decision_descriptor = _load_decision(
            root, decision_path, custody
        )
        if role not in approved["authorized_dataset_roles"]:
            raise PilotContractError("pilot role is not authorized by the decision")
        _receipt, candidate_descriptor, requests = _load_candidate(
            root,
            candidate_root,
            custody=custody,
            approved_decision=approved,
            expected_receipt_file_sha256=expected_receipt_file_sha256,
            expected_receipt_self_sha256=expected_receipt_self_sha256,
        )
    matrix_identity = _identity(
        PLAN_DOMAIN,
        {
            "role": role,
            "decision_sha256": decision_descriptor["decision_sha256"],
            "candidate_receipt_sha256": candidate_descriptor["receipt"][
                "candidate_receipt_sha256"
            ],
            "worker_image_id": TENSORRT_IMAGE_ID,
            "gpu_uuid": TENSORRT_GPU_UUID,
            "request_sample_ids": [item["sample_id"] for item in requests],
        },
    )
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": PLAN_ARTIFACT_KIND,
        "claim_status": "planning_only_nonpublication_not_execution",
        "role": role,
        "matrix_identity_sha256": matrix_identity,
        "decision": decision_descriptor,
        "candidate": candidate_descriptor,
        "runtime": {
            "engine": "tensorrt_cuda",
            "worker_image": TENSORRT_IMAGE,
            "worker_image_id": TENSORRT_IMAGE_ID,
            "base_image_id": TENSORRT_BASE_IMAGE_ID,
            "entrypoint": TENSORRT_ENTRYPOINT,
            "gpu_uuid": TENSORRT_GPU_UUID,
            "gpu_device_index": 0,
            "pull_policy": "never",
            "network": "none",
            "read_only_project_mount_required": True,
            "max_requests_per_worker": 2,
            "image_availability_source": "external_caller_assertion_only",
        },
        "request_count": len(requests),
        "requests": requests,
        "claims": {
            "semantic_claim": "topology_load_proxy_candidate_only",
            "accuracy": False,
            "representative": False,
            "statistical_independence": False,
            "production_semantics": False,
            "model_acceptance": False,
            "runtime_acceptance": False,
            "performance": False,
            "latency": False,
            "throughput": False,
        },
        **_FALSE_FLAGS,
    }
    return {**core, "pilot_plan_sha256": _identity(PLAN_DOMAIN, core)}


def blocked_image_assessment(
    plan: Mapping[str, object], available_image_ids: Sequence[str]
) -> dict[str, object] | None:
    if any(type(item) is not str for item in available_image_ids):
        raise PilotContractError("available Docker image IDs must be strings")
    available = sorted(set(available_image_ids))
    if any(_IMAGE_ID_RE.fullmatch(item) is None for item in available):
        raise PilotContractError("available Docker image IDs are invalid")
    if TENSORRT_IMAGE_ID in available:
        return None
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": ASSESSMENT_ARTIFACT_KIND,
        "claim_status": "blocked_nonpublication_preflight_not_execution",
        "status": "blocked_missing_exact_pinned_docker_image",
        "role": plan["role"],
        "pilot_plan_sha256": plan["pilot_plan_sha256"],
        "required_image_id": TENSORRT_IMAGE_ID,
        "available_image_ids": available,
        "blockers": [
            "exact pinned TensorRT worker image is absent from the external inventory",
            "network download is not authorized by the bound decision",
        ],
        **_FALSE_FLAGS,
    }
    return {**core, "assessment_sha256": _identity(ASSESSMENT_DOMAIN, core)}


def create_pilot_artifact(
    *,
    available_image_ids: Sequence[str],
    **plan_arguments: Any,
) -> tuple[dict[str, object], int]:
    plan = build_pilot_plan(**plan_arguments)
    assessment = blocked_image_assessment(plan, available_image_ids)
    return (assessment, 78) if assessment is not None else (plan, 0)


def _contract_error_assessment(role: str, error: PilotContractError) -> dict[str, object]:
    message = " ".join(str(error).split())[:512]
    core: dict[str, object] = {
        "schema_version": 1,
        "artifact_kind": ASSESSMENT_ARTIFACT_KIND,
        "claim_status": "blocked_nonpublication_contract_validation",
        "status": "blocked_contract_validation_failed",
        "role": role,
        "blockers": [message],
        **_FALSE_FLAGS,
    }
    return {**core, "assessment_sha256": _identity(ASSESSMENT_DOMAIN, core)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic, no-write KPP v2 nonpublication GPU pilot plan."
    )
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--decision-path", type=Path, default=decision_contract.DECISION_PATH)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--role", choices=("secondary", "sensitivity"), required=True)
    parser.add_argument("--expected-receipt-file-sha256", required=True)
    parser.add_argument("--expected-receipt-self-sha256", required=True)
    parser.add_argument(
        "--available-image-id",
        action="append",
        default=[],
        help="Externally observed local image ID; no Docker command is executed.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        artifact, status = create_pilot_artifact(
            project_root=args.project_root,
            decision_path=args.decision_path,
            candidate_root=args.candidate_root,
            role=args.role,
            expected_receipt_file_sha256=args.expected_receipt_file_sha256,
            expected_receipt_self_sha256=args.expected_receipt_self_sha256,
            available_image_ids=args.available_image_id,
        )
    except RecursionError:
        artifact = _contract_error_assessment(
            args.role, PilotContractError("JSON nesting exceeds contract limit")
        )
        status = 78
    except PilotContractError as error:
        artifact = _contract_error_assessment(args.role, error)
        status = 78
    print(canonical_line(artifact).decode("ascii"), end="")
    return status


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ASSESSMENT_ARTIFACT_KIND",
    "BRANCHES",
    "BRANCH_BINDINGS",
    "CANDIDATE_CLAIMS",
    "CORPUS_ARTIFACT_KIND",
    "CORPUS_ROLES",
    "FAIL_CLOSED_FLAGS",
    "PLAN_ARTIFACT_KIND",
    "PilotContractError",
    "RECEIPT_ARTIFACT_KIND",
    "RECEIPT_NAME",
    "TENSORRT_ENGINE_PINS",
    "TENSORRT_GPU_UUID",
    "TENSORRT_IMAGE_ID",
    "TENSOR_SEGMENT_BYTES",
    "blocked_image_assessment",
    "build_pilot_plan",
    "candidate_receipt_self_sha",
    "canonical_line",
    "create_pilot_artifact",
    "main",
]
