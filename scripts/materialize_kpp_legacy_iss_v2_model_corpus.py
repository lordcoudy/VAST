#!/usr/bin/env python3
"""Build a receipt-bound, deliberately non-promotable KPP v2 corpus candidate.

The output is not model-parity evidence.  It preserves neutral frame selection,
decoded RGB bytes, preprocessed tensor bytes, and exact provenance so a PI can
later decide whether a separately reviewed promotion transaction is warranted.
This module never edits the parity manifest or any dataset configuration.
Its terminal tree validation is point-in-time evidence; future same-token
directory-namespace immutability is explicitly not attested.
"""

from __future__ import annotations

import argparse
import copy
import ctypes
import hashlib
import io
import json
import math
import ntpath
import os
import re
import secrets
import select
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO

import yaml

import benchmark_contract as _benchmark_contract_module
import backend_publication_dispatch as _backend_publication_dispatch_module
import backend_publication_output_receipt as _backend_publication_output_receipt_module
import backend_runtime_grant as _backend_runtime_grant_module
import checkpoint_acceptance_metadata_binding as _checkpoint_acceptance_metadata_binding_module
import checkpoint_model_parity as _checkpoint_model_parity_module
import extract_kpp_legacy_iss as _extract_kpp_legacy_iss_module
import formal_aw_heft_reference as _formal_aw_heft_reference_module
import kpp_legacy_iss_v2_manifest as _kpp_legacy_iss_v2_manifest_module
import model_parity_grant as _model_parity_grant_module
import publication_acceptance_evidence as _publication_acceptance_evidence_module
from benchmark_contract import ContractError
from checkpoint_model_parity import validate_manifest_identity
from extract_kpp_legacy_iss import (
    ExtractionError,
    _WindowsDirectoryCustody,
    _atomic_publish_directory,
    _create_private_working_directory,
    _create_windows_private_working_directory_with_custody,
    _normalized_windows_handle_path,
    _open_windows_directory_custody,
    _validate_private_publication_set,
    _validate_windows_direct_child_custody,
    _windows_directory_final_path,
    _windows_directory_information,
    _windows_publish_directory_by_handle,
)
from kpp_legacy_iss_v2_manifest import (
    EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
    EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256,
    EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES,
    KppLegacyIssV2ManifestError,
    validate_kpp_legacy_iss_v2_manifest_entry,
)


GENERATION_ID = "kpp_legacy_iss_v2"
DATASET_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
MATERIALIZATION_RECEIPT_PATH = (
    f"{DATASET_ROOT}/kpp_iss_v2_materialization_receipt.json"
)
MATERIALIZATION_RECEIPT_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-materialization-receipt:v1\0"
)
MATERIALIZATION_RECEIPT_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_materialization_receipt"
)
CORPUS_CANDIDATE_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_model_corpus_candidate"
)
DATASET_CANDIDATE_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_model_corpus_dataset_candidate"
)
RECEIPT_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_model_corpus_candidate_receipt"
)
RECEIPT_NAME = "kpp_legacy_iss_v2_model_corpus_candidate_receipt.json"
CANDIDATE_RECEIPT_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-model-corpus-candidate-receipt:v1\0"
)
CANDIDATE_RECEIPT_CORE_DOMAIN = (
    b"VAST:kpp-legacy-iss-v2-model-corpus-candidate-receipt-core:v1\0"
)
AUTHORITATIVE_FAILURE_MARKER_NAME = "authoritative_failure.json"
AUTHORITATIVE_FAILURE_MARKER_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_model_corpus_authoritative_failure_marker"
)
AUTHORITATIVE_COMMIT_PENDING_NAME = ".authoritative_commit_pending"
AUTHORITATIVE_COMMIT_RECORD_NAME = "authoritative_commit.json"
AUTHORITATIVE_COMMIT_RECORD_ARTIFACT_KIND = (
    "vast_kpp_legacy_iss_v2_model_corpus_authoritative_commit_record"
)
_AUTHORITATIVE_FAILED_PREFIX = ".kpp-v2-model-corpus."
_AUTHORITATIVE_FAILED_SUFFIX = ".failed"
_AUTHORITATIVE_FAILED_TOKEN_RE = re.compile(r"[0-9a-f]{32}")
_AUTHORITATIVE_FAILED_NAME_ATTEMPTS = 32

BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
CODECS = ("h264", "h265")
SOURCE_ROLES = ("front_gate", "underbody")
BRANCH_SOURCE_ROLE = {
    "plate_number": "front_gate",
    "vehicle_type": "front_gate",
    "damage": "front_gate",
    "foreign_object": "underbody",
}
MEDIA_PATHS = {
    ("h264", "underbody"): f"{DATASET_ROOT}/h264/iss_v2_underbody.mp4",
    ("h264", "front_gate"): f"{DATASET_ROOT}/h264/iss_v2_front_gate.mp4",
    ("h265", "underbody"): f"{DATASET_ROOT}/h265/iss_v2_underbody.mp4",
    ("h265", "front_gate"): f"{DATASET_ROOT}/h265/iss_v2_front_gate.mp4",
}
DATASET_NAMES = {
    "h264": "kpp_legacy_iss_v2_h264",
    "h265": "kpp_legacy_iss_v2_h265",
}
FILE_INDEX = {"underbody": 0, "front_gate": 1}
STRATA_PER_SOURCE_ROLE = 60
SAMPLES_PER_CODEC_ROLE = 15

SAMPLING_RULE: dict[str, object] = {
    "schema_version": 1,
    "rule_id": "kpp_v2_midpoint_60_interleaved_codec_corpus_v1",
    "source_roles": ["front_gate", "underbody"],
    "branch_source_role": dict(BRANCH_SOURCE_ROLE),
    "strata_per_source_role": STRATA_PER_SOURCE_ROLE,
    "index_formula": "floor((2*j+1)*N/(2*60));j=0..59",
    "assignment_by_j_modulo_4": {
        "0": {"corpus_role": "calibration", "codec": "h264"},
        "1": {"corpus_role": "evaluation", "codec": "h264"},
        "2": {"corpus_role": "calibration", "codec": "h265"},
        "3": {"corpus_role": "evaluation", "codec": "h265"},
    },
    "selection_inputs": ["frame_count"],
    "content_inspection_used_for_selection": False,
    "event_or_label_selection_used": False,
    "performance_or_outcome_selection_used": False,
    "identical_relative_strata_across_front_branches": True,
    "codec_frame_count_equality_required_per_source_role": True,
}

CLAIMS: dict[str, bool] = {
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

_SUBPROCESS_RESOURCE_POLICIES: dict[str, dict[str, object]] = {
    "tool_version": {
        "timeout_seconds": 60,
        "stdout_limit_bytes": 1024 * 1024,
        "stderr_limit_bytes": 1024 * 1024,
    },
    "ffprobe_frame_catalog": {
        "timeout_seconds": 1800,
        "stdout_limit_bytes": 64 * 1024 * 1024,
        "stderr_limit_bytes": 4 * 1024 * 1024,
    },
    "ffmpeg_selected_frame_decode": {
        "timeout_seconds": 1800,
        "stdout_limit_bytes": "exact_expected_rgb_bytes",
        "stdout_maximum_bytes": 512 * 1024 * 1024,
        "stderr_limit_bytes": 16 * 1024 * 1024,
    },
}
_PIPE_CAPTURE_CHUNK_BYTES = 64 * 1024
_PIPE_READER_JOIN_GRACE_SECONDS = 1.0

# Read-only resume validation must reject attacker-sized leaves from metadata
# before opening or allocating their full contents.  The descriptor cap reuses
# the current gateway's largest accepted payload budget and is conservative for
# the frozen candidate topology.
AUTHORITATIVE_CANDIDATE_RECEIPT_MAX_BYTES = 4 * 1024 * 1024
AUTHORITATIVE_COMMIT_RECORD_MAX_BYTES = 64 * 1024
AUTHORITATIVE_DESCRIPTOR_PAYLOAD_MAX_BYTES = int(
    _SUBPROCESS_RESOURCE_POLICIES["ffmpeg_selected_frame_decode"][
        "stdout_maximum_bytes"
    ]
)

EXPECTED_MATERIALIZATION_CLAIMS: dict[str, bool] = {
    "source_receipts_externally_pinned": True,
    "authoritative_receipt_graph_validated": True,
    "media_sources_derived_from_validated_receipts": True,
    "source_and_installed_bytes_stably_rehashed": True,
    "physical_artifact_bytes_assessed": True,
    "exact_output_tree_validated": True,
    "output_set_directory_published_atomically": True,
    (
        "windows_project_root_data_videos_kpp_and_working_directory_"
        "handle_custody_validated"
    ): True,
    "publishable": False,
    "publication_authorized": False,
}

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_TIME_BASE_RE = re.compile(r"^(0|[1-9][0-9]*)/([1-9][0-9]*)$")
_SHOWINFO_FRAME_RE = re.compile(
    r"\[(Parsed_showinfo_[^ @\]]+).*?\]\s+n:\s*(?P<n>[0-9]+)\s+"
    r"pts:\s*(?P<pts>-?[0-9]+).*?\bs:(?P<w>[0-9]+)x(?P<h>[0-9]+)\b"
)
_SHOWINFO_CONFIG_RE = re.compile(
    r"\[(Parsed_showinfo_[^ @\]]+).*?\]\s+config in time_base:\s*([^,\s]+)"
)


class _UniqueKeyLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects every duplicate mapping key."""


def _construct_unique_mapping(
    loader: yaml.SafeLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    loader.flatten_mapping(node)
    result: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicated = key in result
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "mapping key is not hashable",
                key_node.start_mark,
            ) from exc
        if duplicated:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"duplicate key: {key}",
                key_node.start_mark,
            )
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


_UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping
)


class ModelCorpusError(RuntimeError):
    """A corpus candidate input or custody invariant failed closed."""


class ScientificChoiceRequired(ModelCorpusError):
    """Neutral deterministic materialization cannot continue without approval."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelCorpusError(message)


def _canonical(value: object) -> bytes:
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
    except (TypeError, ValueError) as exc:
        raise ModelCorpusError(f"value is not canonical JSON: {exc}") from exc


def _authoritative_commit_record_payload(
    *,
    canonical_output_root: str,
    canonical_output_name: str,
    outputs_sha256: str,
    sampling_rule_sha256: str,
    source_set_canonical_aggregate_sha256: str,
    source_materialization_receipt: Mapping[str, object],
    source_model_parity_manifest_sha256: str,
    candidate_receipt_core_sha256: str,
) -> bytes:
    _require(
        type(canonical_output_root) is str
        and canonical_output_root not in {"", ".", ".."}
        and not canonical_output_root.startswith("/")
        and "\\" not in canonical_output_root
        and len(PurePosixPath(canonical_output_root).parts) == 2
        and PurePosixPath(canonical_output_root).parts[0].casefold()
        == "staging"
        and all(
            component not in {"", ".", ".."}
            for component in PurePosixPath(canonical_output_root).parts
        )
        and PurePosixPath(canonical_output_root).name == canonical_output_name,
        "authoritative commit record output root is invalid",
    )
    _require(
        type(canonical_output_name) is str
        and canonical_output_name not in {"", ".", ".."}
        and ntpath.basename(canonical_output_name) == canonical_output_name,
        "authoritative commit record output name is invalid",
    )
    for label, value in (
        ("outputs", outputs_sha256),
        ("sampling rule", sampling_rule_sha256),
        ("source set", source_set_canonical_aggregate_sha256),
        ("model parity manifest", source_model_parity_manifest_sha256),
        ("candidate receipt core", candidate_receipt_core_sha256),
    ):
        _require(
            type(value) is str and _SHA256_RE.fullmatch(value) is not None,
            f"authoritative commit record {label} SHA-256 is invalid",
        )
    _require(
        set(source_materialization_receipt)
        == {
            "path",
            "size_bytes",
            "sha256",
            "materialization_receipt_sha256",
        },
        "authoritative commit record source receipt binding is not exact",
    )
    _require(
        source_materialization_receipt
        == {
            "path": MATERIALIZATION_RECEIPT_PATH,
            "size_bytes": EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES,
            "sha256": EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
            "materialization_receipt_sha256": (
                EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
            ),
        },
        "authoritative commit record source receipt is not frozen authority",
    )
    _require(
        type(source_materialization_receipt["path"]) is str
        and type(source_materialization_receipt["size_bytes"]) is int
        and source_materialization_receipt["size_bytes"] > 0,
        "authoritative commit record source receipt identity is invalid",
    )
    for key in ("sha256", "materialization_receipt_sha256"):
        value = source_materialization_receipt[key]
        _require(
            type(value) is str and _SHA256_RE.fullmatch(value) is not None,
            "authoritative commit record source receipt SHA-256 is invalid",
        )
    return _canonical(
        {
            "schema_version": 1,
            "artifact_kind": AUTHORITATIVE_COMMIT_RECORD_ARTIFACT_KIND,
            "generation_id": GENERATION_ID,
            "status": "authoritative_nonpromotable_candidate_commit_record",
            "canonical_output_root": canonical_output_root,
            "canonical_output_name": canonical_output_name,
            "canonical_commit_record_name": AUTHORITATIVE_COMMIT_RECORD_NAME,
            "outputs_sha256": outputs_sha256,
            "sampling_rule_sha256": sampling_rule_sha256,
            "source_set_canonical_aggregate_sha256": (
                source_set_canonical_aggregate_sha256
            ),
            "source_materialization_receipt": dict(
                source_materialization_receipt
            ),
            "source_model_parity_manifest_sha256": (
                source_model_parity_manifest_sha256
            ),
            "candidate_receipt_core_sha256": (
                candidate_receipt_core_sha256
            ),
            "candidate_transaction_committed_only_when_present_at_"
            "canonical_name": True,
            "commit_semantics": (
                "presence_at_canonical_commit_record_name_after_native_"
                "no_replace_move"
            ),
            "model_acceptance_attested": False,
            "runtime_acceptance_attested": False,
            "future_tree_immutability_attested": False,
            "promotable": False,
            "publication_authorized": False,
            "evidence_accepted": False,
        }
    )
def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _content_sha256(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ModelCorpusError(f"value is not canonical JSON: {exc}") from exc
    return _sha256(payload)


def _sha(value: object, *, label: str) -> str:
    _require(
        type(value) is str and _SHA256_RE.fullmatch(value) is not None,
        f"{label} must be a lowercase SHA-256",
    )
    return str(value)


def _positive_int(value: object, *, label: str) -> int:
    _require(type(value) is int and value > 0, f"{label} must be a positive integer")
    return int(value)


def _require_frozen_materialization_receipt_pins(
    *,
    expected_size_bytes: int,
    expected_file_sha256: str,
    expected_self_sha256: str,
) -> None:
    """Reject caller-selected v2 receipts; authority lives in the frozen contract."""

    _require(
        type(expected_size_bytes) is int
        and expected_size_bytes == EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES,
        "frozen materialization receipt size authority does not match",
    )
    _require(
        expected_file_sha256 == EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
        "frozen materialization receipt file authority does not match",
    )
    _require(
        expected_self_sha256 == EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256,
        "frozen materialization receipt self authority does not match",
    )


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} must be an object")
    return dict(value)


def _sequence(value: object, *, label: str) -> list[Any]:
    _require(type(value) is list, f"{label} must be a list")
    return list(value)


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(os.path, "isjunction", lambda _path: False)
    if is_junction(path):
        return True
    try:
        attributes = int(getattr(path.lstat(), "st_file_attributes", 0))
    except OSError:
        return False
    return bool(attributes & int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _snapshot(value: os.stat_result) -> tuple[int, int, int, int, int, int, int]:
    return (
        int(value.st_dev),
        int(value.st_ino),
        int(value.st_mode),
        int(value.st_size),
        int(value.st_mtime_ns),
        int(value.st_ctime_ns),
        int(value.st_nlink),
    )


def _same_path_and_handle(
    path_before: tuple[int, int, int, int, int, int, int],
    path_after: tuple[int, int, int, int, int, int, int],
    handle_before: tuple[int, int, int, int, int, int, int],
    handle_after: tuple[int, int, int, int, int, int, int],
) -> bool:
    # Windows reports creation/change time differently through path and handle
    # stat APIs.  Each observation class must be internally stable; their
    # device/inode/type/size/mtime and link count must agree across classes.
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


def _directory_identity(value: os.stat_result) -> tuple[int, int, int]:
    return (int(value.st_dev), int(value.st_ino), int(stat.S_IFMT(value.st_mode)))


def _validated_root(value: Path) -> Path:
    root = Path(os.path.abspath(os.fspath(value)))
    _require(root.is_dir(), "project_root must be an existing directory")
    _require(root != Path(root.anchor), "project_root cannot be a filesystem root")
    _require(not _is_link(root), "project_root cannot be a link or reparse point")
    _require(root.resolve() == root, "project_root cannot be an alias")
    return root


def _assert_plain_chain(root: Path, path: Path, *, label: str) -> None:
    candidate = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise ModelCorpusError(f"{label} escaped project_root") from exc
    current = root
    for part in relative.parts:
        current = current / part
        if os.path.lexists(current):
            _require(not _is_link(current), f"{label} path contains a link/reparse point")


def _leaf_is_plain_file(path: Path, *, label: str) -> os.stat_result:
    try:
        observed = path.lstat()
    except FileNotFoundError as exc:
        raise ModelCorpusError(f"{label} is missing: {path}") from exc
    except OSError as exc:
        raise ModelCorpusError(f"cannot inspect {label}: {exc}") from exc
    _require(stat.S_ISREG(observed.st_mode), f"{label} is not a regular file")
    _require(not _is_link(path), f"{label} is a link or reparse point")
    _require(int(observed.st_nlink) == 1, f"{label} is a hardlink")
    return observed


def _open_binary_custody(path: Path, *, label: str) -> BinaryIO:
    """Open read custody; Windows denies concurrent write/delete/rename access."""

    if os.name != "nt":
        flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            return os.fdopen(os.open(path, flags), "rb")
        except OSError as exc:
            raise ModelCorpusError(f"cannot acquire {label} custody: {exc}") from exc

    from ctypes import wintypes
    import msvcrt

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
        raise ModelCorpusError(
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


def _open_new_output_custody(path: Path, *, label: str) -> BinaryIO:
    """Atomically create an output leaf and retain a write-exclusive handle."""

    if os.name != "nt":
        flags = os.O_CREAT | os.O_EXCL | os.O_RDWR
        flags |= int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            return os.fdopen(os.open(path, flags, 0o600), "w+b")
        except OSError as exc:
            raise ModelCorpusError(f"cannot create held {label}: {exc}") from exc

    from ctypes import wintypes
    import msvcrt

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
        0x80000000 | 0x40000000 | 0x00010000,  # READ | WRITE | DELETE
        0x00000001 | 0x00000004,  # FILE_SHARE_READ | FILE_SHARE_DELETE
        None,
        1,  # CREATE_NEW
        0x00000080 | 0x00200000,  # NORMAL | OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise ModelCorpusError(
            f"cannot create held {label}: Win32 error {ctypes.get_last_error()}"
        )
    try:
        descriptor = msvcrt.open_osfhandle(
            int(handle), os.O_RDWR | int(getattr(os, "O_BINARY", 0))
        )
    except BaseException:
        kernel32.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "w+b")


def _open_new_atomic_marker_temp(path: Path) -> BinaryIO:
    """CREATE_NEW a noncanonical marker temp with DELETE access and no write sharing."""

    if os.name != "nt":
        raise ModelCorpusError("authoritative failure marker requires Windows")
    from ctypes import wintypes
    import msvcrt

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
        0x80000000 | 0x40000000 | 0x00010000,  # READ | WRITE | DELETE
        0x00000001,  # FILE_SHARE_READ only
        None,
        1,  # CREATE_NEW
        0x00000080 | 0x00200000,  # NORMAL | OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        code = ctypes.get_last_error()
        if code in (80, 183):
            raise FileExistsError(f"atomic marker temp already exists: {path.name}")
        raise ModelCorpusError(
            f"cannot create atomic failure marker temp: Win32 error {code}"
        )
    try:
        descriptor = msvcrt.open_osfhandle(
            int(handle), os.O_RDWR | int(getattr(os, "O_BINARY", 0))
        )
    except BaseException:
        kernel32.CloseHandle(handle)
        raise
    return os.fdopen(descriptor, "w+b")


def _open_commit_pending_final_custody(path: Path) -> BinaryIO:
    """Open the published sentinel with DELETE access and no write/delete sharing."""

    if os.name != "nt":
        raise ModelCorpusError("authoritative commit sentinel requires Windows")
    from ctypes import wintypes
    import msvcrt

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
        0x80000000 | 0x00010000,  # GENERIC_READ | DELETE
        0x00000001,  # FILE_SHARE_READ only
        None,
        3,  # OPEN_EXISTING
        0x00000080 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise ModelCorpusError(
            "cannot acquire published commit-pending sentinel custody: "
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


def _mark_windows_stream_delete_pending(stream: BinaryIO, *, label: str) -> None:
    if os.name != "nt":
        raise ModelCorpusError("exact-handle delete-pending requires Windows")
    from ctypes import wintypes
    import msvcrt

    class FileDispositionInfo(ctypes.Structure):
        _fields_ = [("DeleteFile", wintypes.BOOL)]

    information = FileDispositionInfo(True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    raw_handle = msvcrt.get_osfhandle(stream.fileno())
    if not set_information(
        wintypes.HANDLE(raw_handle),
        4,  # FileDispositionInfo
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ModelCorpusError(
            f"could not mark exact held {label} delete-pending: "
            f"Win32 error {ctypes.get_last_error()}"
        )


def _windows_stream_delete_pending(stream: BinaryIO, *, label: str) -> bool:
    if os.name != "nt":
        raise ModelCorpusError("delete-pending inspection requires Windows")
    from ctypes import wintypes
    import msvcrt

    class FileStandardInfo(ctypes.Structure):
        _fields_ = [
            ("AllocationSize", ctypes.c_longlong),
            ("EndOfFile", ctypes.c_longlong),
            ("NumberOfLinks", wintypes.DWORD),
            ("DeletePending", wintypes.BOOLEAN),
            ("Directory", wintypes.BOOLEAN),
        ]

    information = FileStandardInfo()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandleEx
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    get_information.restype = wintypes.BOOL
    raw_handle = msvcrt.get_osfhandle(stream.fileno())
    if not get_information(
        wintypes.HANDLE(raw_handle),
        1,  # FileStandardInfo
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ModelCorpusError(
            f"could not inspect {label} delete-pending state: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    return bool(information.DeletePending)


def _close_commit_pending_stream(stream: BinaryIO) -> None:
    stream.close()


def _windows_move_held_file_no_replace(
    *,
    raw_handle: int,
    target_path: str,
) -> tuple[bool, int]:
    """Execute one no-replace native rename with no post-success inspection."""

    if os.name != "nt":
        raise ModelCorpusError("native commit move requires Windows")
    _require(
        type(raw_handle) is int and raw_handle not in {-1, 0},
        "native commit move handle is invalid",
    )
    _require(
        type(target_path) is str
        and bool(target_path)
        and "\x00" not in target_path,
        "native commit target path is invalid",
    )
    from ctypes import wintypes

    class FileRenameInfo(ctypes.Structure):
        _fields_ = [
            ("ReplaceIfExists", wintypes.BOOL),
            ("RootDirectory", wintypes.HANDLE),
            ("FileNameLength", wintypes.DWORD),
            ("FileName", wintypes.WCHAR * 1),
        ]

    encoded_name = target_path.encode("utf-16-le")
    name_offset = FileRenameInfo.FileName.offset
    buffer_size = max(
        ctypes.sizeof(FileRenameInfo),
        name_offset + len(encoded_name) + 2,
    )
    buffer = ctypes.create_string_buffer(buffer_size)
    information = ctypes.cast(
        buffer, ctypes.POINTER(FileRenameInfo)
    ).contents
    information.ReplaceIfExists = False
    information.RootDirectory = None
    information.FileNameLength = len(encoded_name)
    ctypes.memmove(
        ctypes.addressof(buffer) + name_offset,
        encoded_name,
        len(encoded_name),
    )
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    moved = bool(
        set_information(
            wintypes.HANDLE(raw_handle),
            3,  # FileRenameInfo
            buffer,
            buffer_size,
        )
    )
    if moved:
        return True, 0
    return False, int(ctypes.get_last_error())


def _windows_plain_file_information(handle: int, *, label: str) -> tuple[int, int]:
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
        raise ModelCorpusError(
            f"could not inspect {label}: Win32 error {ctypes.get_last_error()}"
        )
    _require(
        not information.dwFileAttributes & 0x00000010
        and not information.dwFileAttributes & 0x00000400,
        f"{label} must be a plain non-reparse file",
    )
    file_index = (int(information.nFileIndexHigh) << 32) | int(
        information.nFileIndexLow
    )
    return int(information.dwVolumeSerialNumber), file_index


def _write_authoritative_failure_marker_atomic(
    *,
    candidate_custody: _WindowsDirectoryCustody,
    quarantine_path: Path,
    marker_payload: bytes,
    _test_fault_hook: Callable[[str], None] | None = None,
) -> None:
    """Commit the canonical marker only after exact temp bytes are held and verified."""

    _require(
        type(marker_payload) is bytes and bool(marker_payload),
        "authoritative failure marker payload is invalid",
    )
    hook = _test_fault_hook or (lambda _stage: None)
    stream: BinaryIO | None = None
    temp_path: Path | None = None
    renamed = False
    primary: BaseException | None = None
    try:
        for _attempt in range(_AUTHORITATIVE_FAILED_NAME_ATTEMPTS):
            temp_path = quarantine_path / (
                ".authoritative-failure-marker."
                f"{secrets.token_hex(16)}.tmp"
            )
            try:
                stream = _open_new_atomic_marker_temp(temp_path)
            except FileExistsError:
                continue
            break
        _require(
            stream is not None and temp_path is not None,
            "could not allocate a unique atomic failure marker temp",
        )
        hook("write")
        stream.write(marker_payload)
        hook("flush")
        stream.flush()
        hook("fsync")
        os.fsync(stream.fileno())
        hook("verify")
        before_path = _leaf_is_plain_file(
            temp_path, label="authoritative failure marker temp"
        )
        before_handle = os.fstat(stream.fileno())
        before_path_snapshot = _snapshot(before_path)
        before_handle_snapshot = _snapshot(before_handle)
        stream.seek(0)
        observed_payload = stream.read(len(marker_payload) + 1)
        stream.seek(0)
        _require(
            _same_path_and_handle(
                before_path_snapshot,
                before_path_snapshot,
                before_handle_snapshot,
                before_handle_snapshot,
            )
            and observed_payload == marker_payload,
            "authoritative failure marker temp bytes or identity drifted",
        )
        from ctypes import wintypes
        import msvcrt

        raw_handle = msvcrt.get_osfhandle(stream.fileno())
        file_identity = _windows_plain_file_information(
            raw_handle, label="authoritative failure marker temp"
        )
        file_custody = _WindowsDirectoryCustody(
            handle=raw_handle,
            identity=file_identity,
            label="authoritative failure marker temp",
        )
        _windows_publish_directory_by_handle(
            source=file_custody,
            parent=candidate_custody,
            target_name=AUTHORITATIVE_FAILURE_MARKER_NAME,
        )
        renamed = True
        marker_path = quarantine_path / AUTHORITATIVE_FAILURE_MARKER_NAME
        after_path = _leaf_is_plain_file(
            marker_path, label="authoritative failure marker"
        )
        after_handle = os.fstat(stream.fileno())
        stream.seek(0)
        final_payload = stream.read(len(marker_payload) + 1)
        after_path_snapshot = _snapshot(after_path)
        after_handle_snapshot = _snapshot(after_handle)
        stable_before = (
            before_path_snapshot[0],
            before_path_snapshot[1],
            stat.S_IFMT(before_path_snapshot[2]),
            before_path_snapshot[3],
            before_path_snapshot[4],
            before_path_snapshot[6],
        )
        stable_after = (
            after_path_snapshot[0],
            after_path_snapshot[1],
            stat.S_IFMT(after_path_snapshot[2]),
            after_path_snapshot[3],
            after_path_snapshot[4],
            after_path_snapshot[6],
        )
        _require(
            stable_before == stable_after
            and
            _same_path_and_handle(
                after_path_snapshot,
                after_path_snapshot,
                after_handle_snapshot,
                after_handle_snapshot,
            )
            and final_payload == marker_payload,
            "canonical authoritative failure marker bytes or identity drifted",
        )
        stream.close()
        stream = None
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if stream is not None:
            cleanup_diagnostics: list[str] = []
            try:
                _mark_windows_stream_delete_pending(
                    stream,
                    label=(
                        "canonical authoritative failure marker"
                        if renamed
                        else "authoritative failure marker temp"
                    ),
                )
            except BaseException as cleanup_exc:
                cleanup_diagnostics.append(
                    "exact marker rollback delete-pending failed: "
                    f"{type(cleanup_exc).__name__}: "
                    f"{_sanitized_error_text(cleanup_exc)}"
                )
            try:
                stream.close()
            except BaseException as cleanup_exc:
                cleanup_diagnostics.append(
                    "exact marker rollback close failed: "
                    f"{type(cleanup_exc).__name__}: "
                    f"{_sanitized_error_text(cleanup_exc)}"
                )
            if primary is not None:
                _attach_exception_diagnostics(primary, cleanup_diagnostics)


def _open_move_compatible_output_custody(path: Path, *, label: str) -> BinaryIO:
    """Open read custody whose sharing permits the held parent-directory rename."""

    if os.name != "nt":
        flags = os.O_RDONLY | int(getattr(os, "O_CLOEXEC", 0))
        flags |= int(getattr(os, "O_NOFOLLOW", 0))
        try:
            return os.fdopen(os.open(path, flags), "rb")
        except OSError as exc:
            raise ModelCorpusError(
                f"cannot acquire move-compatible {label} custody: {exc}"
            ) from exc

    from ctypes import wintypes
    import msvcrt

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
        0x80000000,  # GENERIC_READ
        0x00000001 | 0x00000002 | 0x00000004,  # READ | WRITE | DELETE sharing
        None,
        3,  # OPEN_EXISTING
        0x00000080 | 0x00200000,
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise ModelCorpusError(
            f"cannot acquire move-compatible {label} custody: "
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


def _open_windows_final_directory_identity_custody(
    path: Path, *, label: str
) -> _WindowsDirectoryCustody:
    """Hold directory-object identity; this does not seal its child namespace."""

    if os.name != "nt":
        raise ModelCorpusError("final namespace custody requires Windows")
    candidate = path.absolute()
    _require(
        candidate.is_dir() and not _is_link(candidate),
        f"{label} must be a plain existing directory",
    )
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
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = create_file(
        str(candidate),
        0x00000001 | 0x00000080 | 0x00020000,  # LIST | READ_ATTRIBUTES | READ_CONTROL
        0x00000001,  # FILE_SHARE_READ only
        None,
        3,
        0x02000000 | 0x00200000,  # BACKUP_SEMANTICS | OPEN_REPARSE_POINT
        None,
    )
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        raise ModelCorpusError(
            f"could not acquire {label}: Win32 error {ctypes.get_last_error()}"
        )
    handle_value = int(handle)
    try:
        identity = _windows_directory_information(handle_value, label=label)
        final_path = _windows_directory_final_path(handle_value, label=label)
        _require(
            _normalized_windows_handle_path(final_path)
            == _normalized_windows_handle_path(str(candidate)),
            f"{label} final path identity drifted",
        )
        return _WindowsDirectoryCustody(
            handle=handle_value,
            identity=identity,
            label=label,
        )
    except BaseException:
        close_handle(wintypes.HANDLE(handle_value))
        raise


def _duplicate_windows_directory_custody(
    source: _WindowsDirectoryCustody, *, label: str
) -> _WindowsDirectoryCustody:
    """Duplicate a held Win32 directory handle without inheritance or reopening."""

    if os.name != "nt":
        raise ModelCorpusError("directory custody duplication requires Windows")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    duplicate_handle = kernel32.DuplicateHandle
    duplicate_handle.argtypes = [
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        wintypes.BOOL,
        wintypes.DWORD,
    ]
    duplicate_handle.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    process_handle = get_current_process()
    duplicated = wintypes.HANDLE()
    if not duplicate_handle(
        process_handle,
        wintypes.HANDLE(source.handle),
        process_handle,
        ctypes.byref(duplicated),
        0,
        False,  # bInheritHandle
        0x00000002,  # DUPLICATE_SAME_ACCESS
    ):
        raise ModelCorpusError(
            f"could not duplicate {label}: Win32 error {ctypes.get_last_error()}"
        )
    handle_value = int(duplicated.value)
    try:
        identity = _windows_directory_information(handle_value, label=label)
        _require(
            identity == source.identity,
            f"{label} duplicate FileId differs from its source custody",
        )
        source_path = _normalized_windows_handle_path(
            _windows_directory_final_path(source.handle, label=source.label)
        )
        duplicate_path = _normalized_windows_handle_path(
            _windows_directory_final_path(handle_value, label=label)
        )
        _require(
            duplicate_path == source_path,
            f"{label} duplicate final path differs from its source custody",
        )
        return _WindowsDirectoryCustody(
            handle=handle_value,
            identity=identity,
            label=label,
        )
    except BaseException:
        close_handle(wintypes.HANDLE(handle_value))
        raise


def _acquire_authoritative_quarantine_guards(
    *,
    parent_custody: _WindowsDirectoryCustody,
    candidate_custody: _WindowsDirectoryCustody,
    expected_candidate_name: str,
) -> tuple[_WindowsDirectoryCustody, _WindowsDirectoryCustody]:
    parent_guard: _WindowsDirectoryCustody | None = None
    candidate_guard: _WindowsDirectoryCustody | None = None
    try:
        parent_guard = _duplicate_windows_directory_custody(
            parent_custody,
            label="authoritative staging parent quarantine guard",
        )
        candidate_guard = _duplicate_windows_directory_custody(
            candidate_custody,
            label="authoritative candidate quarantine guard",
        )
        _validate_windows_direct_child_custody(
            parent=parent_guard,
            child=candidate_guard,
            expected_name=expected_candidate_name,
        )
        return parent_guard, candidate_guard
    except BaseException as primary:
        diagnostics: list[str] = []
        for guard_label, guard in (
            ("candidate_guard", candidate_guard),
            ("parent_guard", parent_guard),
        ):
            if guard is None:
                continue
            try:
                guard.close()
            except BaseException as exc:
                diagnostics.append(
                    f"failed to release partial {guard_label}: "
                    f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
                )
        _attach_exception_diagnostics(primary, diagnostics)
        raise


@dataclass(frozen=True)
class MediaProbe:
    codec: str
    width: int
    height: int
    stream_index: int
    time_base: str
    frame_count: int
    frame_pts: tuple[int, ...]


@dataclass(frozen=True)
class DecodedFrame:
    frame_index: int
    source_pts: int
    source_time_base: str
    pts_ns: int
    width: int
    height: int
    stride: int
    rgb: bytes


@dataclass(frozen=True)
class PlannedSample:
    branch: str
    source_role: str
    corpus_role: str
    codec: str
    stratum_index: int
    frame_index: int


@dataclass(frozen=True)
class SubprocessContext:
    cwd: Path
    cwd_identity: tuple[int, int, int]
    environment: dict[str, str]
    descriptor: dict[str, object]


@dataclass(frozen=True)
class _TestAdapters:
    probe: Callable[["HeldMedia", Path], MediaProbe]
    decode: Callable[
        ["HeldMedia", tuple[int, ...], MediaProbe, Path],
        dict[int, DecodedFrame],
    ]
    preprocess: Callable[
        [DecodedFrame, dict[str, object], str, str],
        tuple[bytes, dict[str, object]],
    ]
    version_reader: Callable[[Path], bytes]


def _windows_directory_from_api() -> str:
    if os.name != "nt":
        raise ModelCorpusError("Windows directory API is unavailable")
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_windows_directory = kernel32.GetWindowsDirectoryW
    get_windows_directory.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    get_windows_directory.restype = wintypes.UINT
    capacity = 32768
    buffer = ctypes.create_unicode_buffer(capacity)
    length = int(get_windows_directory(buffer, capacity))
    _require(
        0 < length < capacity,
        f"GetWindowsDirectoryW failed: Win32 error {ctypes.get_last_error()}",
    )
    value = os.path.normpath(str(buffer.value))
    _require(
        Path(value).is_absolute()
        and Path(value).is_dir()
        and "\x00" not in value,
        "WinAPI returned an invalid Windows directory",
    )
    return value


def _capture_storage_projection() -> dict[str, object]:
    """Describe the platform-specific capture storage without overclaiming."""

    if os.name == "nt":
        return {
            "platform_family": "windows",
            "storage_kind": "EXCLUSIVE_DELETE_ON_CLOSE_FILE",
            "creation_primitive": "CREATEFILEW_CREATE_NEW_SHARE_MODE_NONE",
            "namespace_visibility": "NAMED_INSIDE_PRIVATE_CWD_WHILE_OPEN",
            "same_token_path_reopen_for_write_denied": True,
            "capture_file_exists": True,
        }
    return {
        "platform_family": "posix",
        "storage_kind": "PARENT_PRIVATE_MEMORY",
        "creation_primitive": "BYTESIO_WITH_INTERNAL_HARD_LIMIT",
        "namespace_visibility": "NO_FILESYSTEM_ENTRY",
        "same_token_path_reopen_for_write_denied": None,
        "capture_file_exists": False,
    }


def _build_subprocess_context(
    *, root: Path, cwd: Path, published_cwd: Path
) -> SubprocessContext:
    actual_cwd = cwd.absolute()
    _assert_plain_chain(root, actual_cwd, label="subprocess private cwd")
    _require(
        actual_cwd.is_dir() and not _is_link(actual_cwd),
        "subprocess cwd must be a private candidate directory",
    )
    try:
        published_relative = published_cwd.absolute().relative_to(root).as_posix()
    except ValueError as exc:
        raise ModelCorpusError("published subprocess cwd escapes project_root") from exc

    environment: dict[str, str] = {
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    if os.name == "nt":
        windows_directory = _windows_directory_from_api()
        environment["SystemRoot"] = windows_directory
        environment["WINDIR"] = windows_directory
    _require(
        all(
            type(key) is str
            and type(value) is str
            and key
            and "\x00" not in key
            and "\x00" not in value
            for key, value in environment.items()
        ),
        "sanitized subprocess environment is invalid",
    )
    projection: dict[str, object] = {
        "schema_version": 4,
        "policy_id": "kpp_model_corpus_minimal_subprocess_context_v4",
        "inherited_environment_used": False,
        "windows_directory_source": (
            "GetWindowsDirectoryW" if os.name == "nt" else None
        ),
        "environment": dict(sorted(environment.items())),
        "environment_allowlist": sorted(environment),
        "forbidden_inherited_examples": [
            "FFREPORT",
            "FFMPEG_DATADIR",
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "DYLD_INSERT_LIBRARIES",
            "PYTHONHOME",
            "PYTHONPATH",
            "CUDA_CACHE_PATH",
            "CUDA_VISIBLE_DEVICES",
            "GST_PLUGIN_PATH",
            "OPENVINO_LIB_PATHS",
            "OPENCV_OPENCL_RUNTIME",
        ],
        "cwd": {
            "role": "private_candidate_root_prepublication",
            "published_path": published_relative,
            "same_directory_published_atomically": True,
        },
        "stdin": "DEVNULL",
        "stdout": "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE",
        "stderr": "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE",
        "capture_transport": "PARENT_DRAINED_OS_PIPE",
        "capture_storage": _capture_storage_projection(),
        "shell": False,
        "dynamic_library_closure_attested": False,
        "process_tree_termination_attested": False,
        "capture_files_inside_private_cwd": os.name == "nt",
        "capture_file_handles_inherited_by_child": False,
        "accepted_output_size_bounded": True,
        "temporary_capture_file_growth_hard_limited": (
            True if os.name == "nt" else None
        ),
        "capture_storage_growth_hard_limited": True,
        "filesystem_allocation_quota_attested": False,
        "direct_child_output_truncation_on_success": False,
        "descendant_output_completion_attested": False,
        "pipe_capture_chunk_bytes": _PIPE_CAPTURE_CHUNK_BYTES,
        "pipe_reader_join_grace_seconds": _PIPE_READER_JOIN_GRACE_SECONDS,
        "resource_poll_interval_seconds": 0.01,
        "direct_child_kill_reap_grace_seconds": 5,
        "subprocess_resource_policies": copy.deepcopy(
            _SUBPROCESS_RESOURCE_POLICIES
        ),
    }
    descriptor = {
        "canonical_projection": projection,
        "canonical_sha256": _sha256(_canonical(projection)),
    }
    return SubprocessContext(
        cwd=actual_cwd,
        cwd_identity=_directory_identity(actual_cwd.lstat()),
        environment=dict(projection["environment"]),
        descriptor=descriptor,
    )


def _terminate_and_reap_direct_child(
    process: subprocess.Popen[bytes],
    *,
    policy_id: str,
    kill_grace_seconds: float,
) -> list[str]:
    """Best-effort bounded cleanup that never replaces the primary failure."""

    diagnostics: list[str] = []
    returncode: int | None = None
    try:
        returncode = process.poll()
    except BaseException as exc:
        diagnostics.append(
            f"subprocess {policy_id} cleanup poll failed: {type(exc).__name__}"
        )
    if returncode is None:
        try:
            process.kill()
        except BaseException as exc:
            diagnostics.append(
                f"subprocess {policy_id} cleanup kill failed: {type(exc).__name__}"
            )
    try:
        process.wait(timeout=kill_grace_seconds)
    except subprocess.TimeoutExpired:
        diagnostics.append(
            f"subprocess {policy_id} direct child was not reaped within "
            f"{kill_grace_seconds} seconds after cleanup termination request"
        )
    except BaseException as exc:
        diagnostics.append(
            f"subprocess {policy_id} cleanup reap failed: {type(exc).__name__}"
        )
    return diagnostics


def _attach_exception_diagnostics(
    primary: BaseException, diagnostics: Sequence[str]
) -> None:
    add_note = getattr(primary, "add_note", None)
    if not callable(add_note):
        return
    for diagnostic in diagnostics:
        try:
            add_note(str(diagnostic))
        except BaseException:
            return


def _sanitized_error_text(value: object, *, maximum_characters: int = 2048) -> str:
    try:
        raw = str(value)
    except BaseException:
        raw = f"unprintable {type(value).__name__}"
    printable = "".join(
        character if character.isprintable() else " " for character in raw
    )
    normalized = " ".join(printable.split())
    if not normalized:
        normalized = "unspecified failure"
    return normalized[:maximum_characters]


def _format_model_corpus_error(error: BaseException) -> str:
    """Render the primary error plus bounded, printable custody diagnostics."""

    lines = [
        f"{type(error).__name__}: {_sanitized_error_text(error)}"
    ]
    notes = getattr(error, "__notes__", ())
    if type(notes) is list:
        for note in notes[:8]:
            lines.append(
                f"DIAGNOSTIC: {_sanitized_error_text(note, maximum_characters=1024)}"
            )
    return "\n".join(lines)


def _close_required_authoritative_resources(
    resources: Sequence[tuple[str, Callable[[], None]]],
) -> BaseException | None:
    """Close every required resource; return the first failure with later notes."""

    primary: BaseException | None = None
    for label, close_resource in resources:
        try:
            close_resource()
        except BaseException as exc:
            diagnostic = (
                f"required authoritative close failed for {label}: "
                f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
            )
            if primary is None:
                primary = exc
            _attach_exception_diagnostics(primary, [diagnostic])
    return primary


def _emit_nonthrowing_operational_warning(message: str) -> None:
    try:
        print(
            f"WARNING: {_sanitized_error_text(message, maximum_characters=1024)}",
            file=sys.stderr,
        )
    except BaseException:
        pass


def _release_postcommit_authoritative_guards(
    guards: Sequence[tuple[str, object]],
) -> None:
    """Release the irreducible final guards after commit without changing success."""

    for label, guard in guards:
        try:
            close_guard = getattr(guard, "close")
            close_guard()
        except BaseException as exc:
            _emit_nonthrowing_operational_warning(
                f"postcommit {label} release failed: "
                f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
            )


def _raw_capture_storage_size(stream: BinaryIO) -> int:
    try:
        return int(os.fstat(stream.fileno()).st_size)
    except (AttributeError, OSError, ValueError, io.UnsupportedOperation):
        position = stream.tell()
        stream.seek(0, os.SEEK_END)
        size = int(stream.tell())
        stream.seek(position, os.SEEK_SET)
        return size


def _capture_storage_size(stream: BinaryIO) -> int:
    size_reader = getattr(stream, "capture_size", None)
    size = (
        int(size_reader())
        if callable(size_reader)
        else _raw_capture_storage_size(stream)
    )
    _require(size >= 0, "subprocess capture storage size is invalid")
    return size


class _HardBoundedCaptureStorage:
    """Parent-only storage with an internal write ceiling."""

    def __init__(
        self,
        stream: BinaryIO,
        *,
        limit: int,
        path: Path | None,
    ) -> None:
        self.stream = stream
        self.limit = limit
        self.path = path

    def capture_size(self) -> int:
        return _raw_capture_storage_size(self.stream)

    def write(self, payload: bytes | memoryview) -> int:
        view = memoryview(payload)
        before = self.capture_size()
        position = int(self.stream.tell())
        _require(
            0 <= position <= self.limit
            and before <= self.limit
            and max(before, position + len(view)) <= self.limit,
            "subprocess capture storage hard limit rejected a write",
        )
        written = self.stream.write(view)
        self.stream.flush()
        after = self.capture_size()
        _require(
            type(written) is int
            and 0 <= written <= len(view)
            and after <= self.limit,
            "subprocess capture storage hard limit failed",
        )
        return written

    def close(self) -> None:
        self.stream.close()

    def __enter__(self) -> "_HardBoundedCaptureStorage":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def __getattr__(self, name: str) -> object:
        return getattr(self.stream, name)


def _open_windows_exclusive_capture_storage(
    *, directory: Path, prefix: str
) -> tuple[BinaryIO, Path]:
    """Create a delete-on-close file whose handle denies every later open."""

    from ctypes import wintypes
    import msvcrt

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
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    invalid = ctypes.c_void_p(-1).value
    handle: object | None = None
    path: Path | None = None
    for _attempt in range(64):
        path = directory / f"{prefix}{secrets.token_hex(16)}.tmp"
        handle = create_file(
            str(path),
            0x80000000 | 0x40000000 | 0x00010000,
            0,
            None,
            1,
            0x00000100 | 0x00200000 | 0x04000000,
            None,
        )
        if handle not in (None, invalid):
            break
        error = ctypes.get_last_error()
        if error not in {80, 183}:
            raise ModelCorpusError(
                "cannot create exclusive subprocess capture storage: "
                f"Win32 error {error}"
            )
    else:
        raise ModelCorpusError(
            "cannot allocate a unique exclusive subprocess capture name"
        )
    assert handle not in (None, invalid) and path is not None

    flags = os.O_RDWR | int(getattr(os, "O_BINARY", 0))
    try:
        descriptor = msvcrt.open_osfhandle(int(handle), flags)
    except BaseException:
        close_handle(handle)
        raise
    try:
        os.set_inheritable(descriptor, False)
        stream = os.fdopen(descriptor, "w+b")
    except BaseException:
        os.close(descriptor)
        raise
    return stream, path


def _open_private_hard_bounded_capture(
    *, directory: Path, prefix: str, limit: int
) -> _HardBoundedCaptureStorage:
    _require(
        directory.is_dir()
        and not _is_link(directory)
        and type(prefix) is str
        and bool(prefix)
        and "/" not in prefix
        and "\\" not in prefix
        and type(limit) is int
        and limit > 0,
        "private subprocess capture storage parameters are invalid",
    )
    if os.name == "nt":
        raw, path = _open_windows_exclusive_capture_storage(
            directory=directory,
            prefix=prefix,
        )
    else:
        raw = io.BytesIO()
        path = None
    storage = _HardBoundedCaptureStorage(raw, limit=limit, path=path)
    try:
        _require(
            storage.capture_size() == 0,
            "private subprocess capture storage is not empty",
        )
        if os.name == "nt":
            observed = os.fstat(storage.fileno())
            _require(
                stat.S_ISREG(observed.st_mode)
                and int(observed.st_nlink) == 1
                and not os.get_inheritable(storage.fileno()),
                "Windows subprocess capture storage is not exclusive and private",
            )
        else:
            _require(
                storage.path is None,
                "POSIX subprocess memory capture unexpectedly has a path",
            )
    except BaseException:
        storage.close()
        raise
    return storage


def _cancel_windows_synchronous_reader(thread: threading.Thread) -> str | None:
    """Cancel a blocking pipe read without claiming process-tree control."""

    if os.name != "nt" or not thread.is_alive():
        return None
    native_id = thread.native_id
    if native_id is None:
        return "reader thread has no native identifier for cancellation"
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_thread = kernel32.OpenThread
    open_thread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_thread.restype = wintypes.HANDLE
    cancel_io = kernel32.CancelSynchronousIo
    cancel_io.argtypes = [wintypes.HANDLE]
    cancel_io.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL

    handle = open_thread(0x0001, False, int(native_id))  # THREAD_TERMINATE
    invalid = ctypes.c_void_p(-1).value
    if handle in (None, invalid):
        return (
            "cannot open reader thread for synchronous-I/O cancellation: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    try:
        if not cancel_io(handle):
            code = ctypes.get_last_error()
            if code != 1168:  # ERROR_NOT_FOUND: no pending synchronous I/O.
                return (
                    "cannot cancel reader synchronous I/O: "
                    f"Win32 error {code}"
                )
    finally:
        close_handle(handle)
    return None


class _BoundedPipeCapture:
    """Drain one child pipe while never growing its private capture past limit."""

    def __init__(
        self,
        *,
        policy_id: str,
        name: str,
        pipe: BinaryIO,
        capture: BinaryIO,
        limit: int,
        chunk_bytes: int,
        lifecycle_event: threading.Event,
    ) -> None:
        self.policy_id = policy_id
        self.name = name
        self.pipe = pipe
        self.capture = capture
        self.limit = limit
        self.chunk_bytes = chunk_bytes
        self.lifecycle_event = lifecycle_event
        self.stop_event = threading.Event()
        self.overflow = False
        self.eof = False
        self.error: BaseException | None = None
        self.captured_size = 0
        self.thread = threading.Thread(
            target=self._drain,
            name=f"kpp-capture-{policy_id}-{name}",
            daemon=True,
        )

    def start(self) -> None:
        self.thread.start()

    def _drain(self) -> None:
        try:
            descriptor = self.pipe.fileno()
            while not self.stop_event.is_set():
                if os.name != "nt":
                    ready, _writeable, _exceptional = select.select(
                        [descriptor], [], [], 0.05
                    )
                    if not ready:
                        continue
                remaining = self.limit - self.captured_size
                requested = min(self.chunk_bytes, remaining + 1)
                block = os.read(descriptor, requested)
                if not block:
                    self.eof = True
                    break
                accepted = min(len(block), remaining)
                if accepted:
                    view = memoryview(block)[:accepted]
                    while view:
                        written = self.capture.write(view)
                        _require(
                            type(written) is int and 0 < written <= len(view),
                            f"subprocess {self.policy_id} {self.name} capture write failed",
                        )
                        view = view[written:]
                    self.capture.flush()
                    self.captured_size += accepted
                    _require(
                        self.captured_size <= self.limit
                        and _capture_storage_size(self.capture) <= self.limit,
                        f"subprocess {self.policy_id} {self.name} capture hard limit failed",
                    )
                if len(block) > accepted:
                    self.overflow = True
                    break
        except BaseException as exc:
            if not self.stop_event.is_set():
                self.error = exc
        finally:
            self.lifecycle_event.set()

    def request_stop(self) -> list[str]:
        diagnostics: list[str] = []
        self.stop_event.set()
        cancellation = _cancel_windows_synchronous_reader(self.thread)
        if cancellation is not None:
            diagnostics.append(
                f"subprocess {self.policy_id} {self.name} {cancellation}"
            )
        try:
            self.pipe.close()
        except BaseException as exc:
            diagnostics.append(
                f"subprocess {self.policy_id} {self.name} pipe close failed: "
                f"{type(exc).__name__}"
            )
        self.lifecycle_event.set()
        return diagnostics

    def join(self, timeout: float) -> None:
        self.thread.join(max(0.0, timeout))


def _wait_for_pipe_readers(
    captures: Sequence[_BoundedPipeCapture], *, grace_seconds: float
) -> bool:
    deadline = time.perf_counter() + grace_seconds
    for capture in captures:
        capture.join(deadline - time.perf_counter())
    return all(not capture.thread.is_alive() for capture in captures)


def _close_pipe_readers(
    captures: Sequence[_BoundedPipeCapture], *, grace_seconds: float
) -> list[str]:
    diagnostics: list[str] = []
    for capture in captures:
        diagnostics.extend(capture.request_stop())
    _wait_for_pipe_readers(captures, grace_seconds=grace_seconds)
    for capture in captures:
        if capture.thread.is_alive():
            diagnostics.append(
                f"subprocess {capture.policy_id} {capture.name} reader did not stop "
                f"within {grace_seconds} seconds"
            )
    return diagnostics


def _pipe_capture_failure(
    captures: Sequence[_BoundedPipeCapture],
) -> str | None:
    for capture in captures:
        if capture.overflow:
            return (
                f"subprocess {capture.policy_id} {capture.name} exceeded "
                f"{capture.limit} bytes"
            )
    for capture in captures:
        if capture.error is not None:
            return (
                f"subprocess {capture.policy_id} {capture.name} reader failed: "
                f"{type(capture.error).__name__}"
            )
    return None


def _run_sanitized_subprocess(
    command: Sequence[str],
    *,
    context: SubprocessContext,
    policy_id: str,
    exact_stdout_limit_bytes: int | None = None,
) -> subprocess.CompletedProcess[bytes]:
    _require(
        type(command) in {list, tuple}
        and bool(command)
        and all(type(item) is str and bool(item) and "\x00" not in item for item in command),
        "subprocess command is invalid",
    )
    _require(
        _directory_identity(context.cwd.lstat()) == context.cwd_identity,
        "subprocess private cwd identity changed",
    )
    projection = _mapping(
        context.descriptor.get("canonical_projection"),
        label="subprocess context projection",
    )
    _require(
        context.descriptor.get("canonical_sha256") == _sha256(_canonical(projection))
        and context.environment == projection.get("environment")
        and projection.get("inherited_environment_used") is False,
        "subprocess context descriptor drifted",
    )
    policies = _mapping(
        projection.get("subprocess_resource_policies"),
        label="subprocess resource policies",
    )
    policy = _mapping(
        policies.get(policy_id), label=f"subprocess policy {policy_id}"
    )
    timeout_value = policy.get("timeout_seconds")
    stderr_limit = policy.get("stderr_limit_bytes")
    _require(
        type(timeout_value) in {int, float}
        and math.isfinite(float(timeout_value))
        and float(timeout_value) > 0,
        f"subprocess policy {policy_id} timeout is invalid",
    )
    _require(
        type(stderr_limit) is int and 0 < stderr_limit <= 64 * 1024 * 1024,
        f"subprocess policy {policy_id} stderr limit is invalid",
    )
    stdout_policy = policy.get("stdout_limit_bytes")
    if stdout_policy == "exact_expected_rgb_bytes":
        maximum = policy.get("stdout_maximum_bytes")
        _require(
            type(maximum) is int
            and 0 < maximum <= 1024 * 1024 * 1024
            and type(exact_stdout_limit_bytes) is int
            and 0 < exact_stdout_limit_bytes <= maximum,
            f"subprocess policy {policy_id} exact stdout limit is invalid",
        )
        stdout_limit = exact_stdout_limit_bytes
    else:
        _require(
            exact_stdout_limit_bytes is None
            and type(stdout_policy) is int
            and 0 < stdout_policy <= 1024 * 1024 * 1024,
            f"subprocess policy {policy_id} stdout limit is invalid",
        )
        stdout_limit = stdout_policy

    poll_interval = projection.get("resource_poll_interval_seconds")
    kill_grace = projection.get("direct_child_kill_reap_grace_seconds")
    pipe_chunk_bytes = projection.get("pipe_capture_chunk_bytes")
    pipe_join_grace = projection.get("pipe_reader_join_grace_seconds")
    capture_storage_projection = _mapping(
        projection.get("capture_storage"),
        label="subprocess capture storage projection",
    )
    _require(
        type(poll_interval) in {int, float}
        and math.isfinite(float(poll_interval))
        and 0 < float(poll_interval) <= 1,
        "subprocess resource poll interval is invalid",
    )
    _require(
        type(kill_grace) in {int, float}
        and math.isfinite(float(kill_grace))
        and 0 < float(kill_grace) <= 60,
        "subprocess direct-child reap grace is invalid",
    )
    _require(
        projection.get("schema_version") == 4
        and projection.get("policy_id")
        == "kpp_model_corpus_minimal_subprocess_context_v4"
        and projection.get("stdout")
        == "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE"
        and projection.get("stderr")
        == "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE"
        and projection.get("capture_transport") == "PARENT_DRAINED_OS_PIPE"
        and capture_storage_projection == _capture_storage_projection()
        and projection.get("capture_files_inside_private_cwd")
        is (os.name == "nt")
        and projection.get("capture_file_handles_inherited_by_child") is False
        and projection.get("accepted_output_size_bounded") is True
        and projection.get("temporary_capture_file_growth_hard_limited")
        is (True if os.name == "nt" else None)
        and projection.get("capture_storage_growth_hard_limited") is True
        and projection.get("filesystem_allocation_quota_attested") is False
        and projection.get("direct_child_output_truncation_on_success") is False
        and projection.get("process_tree_termination_attested") is False
        and projection.get("descendant_output_completion_attested") is False,
        "subprocess hard-bounded capture contract drifted",
    )
    _require(
        type(pipe_chunk_bytes) is int
        and 0 < pipe_chunk_bytes <= 1024 * 1024,
        "subprocess pipe capture chunk size is invalid",
    )
    _require(
        type(pipe_join_grace) in {int, float}
        and math.isfinite(float(pipe_join_grace))
        and 0 < float(pipe_join_grace) <= 60,
        "subprocess pipe reader join grace is invalid",
    )

    with (
        _open_private_hard_bounded_capture(
            limit=stdout_limit,
            prefix=".subprocess-stdout.",
            directory=context.cwd,
        ) as stdout_capture,
        _open_private_hard_bounded_capture(
            limit=stderr_limit,
            prefix=".subprocess-stderr.",
            directory=context.cwd,
        ) as stderr_capture,
    ):
        process: subprocess.Popen[bytes] | None = None
        stdout_pipe: BinaryIO | None = None
        stderr_pipe: BinaryIO | None = None
        pipe_captures: list[_BoundedPipeCapture] = []
        lifecycle_event = threading.Event()
        deadline = time.monotonic() + float(timeout_value)
        try:
            process = subprocess.Popen(
                list(command),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                cwd=str(context.cwd),
                env=dict(context.environment),
                bufsize=0,
                close_fds=True,
            )
        except OSError as exc:
            raise ModelCorpusError(
                f"subprocess {policy_id} could not be started"
            ) from exc

        try:
            _require(
                _capture_storage_size(stdout_capture) == 0
                and _capture_storage_size(stderr_capture) == 0
                and (
                    os.name != "nt"
                    or (
                        not os.get_inheritable(stdout_capture.fileno())
                        and not os.get_inheritable(stderr_capture.fileno())
                    )
                ),
                f"subprocess {policy_id} capture storage is not private and empty",
            )
            stdout_pipe = process.stdout
            stderr_pipe = process.stderr
            _require(
                stdout_pipe is not None and stderr_pipe is not None,
                f"subprocess {policy_id} parent pipe endpoints are missing",
            )
            pipe_captures = [
                _BoundedPipeCapture(
                    policy_id=policy_id,
                    name="stdout",
                    pipe=stdout_pipe,
                    capture=stdout_capture,
                    limit=stdout_limit,
                    chunk_bytes=pipe_chunk_bytes,
                    lifecycle_event=lifecycle_event,
                ),
                _BoundedPipeCapture(
                    policy_id=policy_id,
                    name="stderr",
                    pipe=stderr_pipe,
                    capture=stderr_capture,
                    limit=stderr_limit,
                    chunk_bytes=pipe_chunk_bytes,
                    lifecycle_event=lifecycle_event,
                ),
            ]
            for capture in pipe_captures:
                capture.start()

            failure: str | None = None
            returncode: int | None = None
            while True:
                observed_at = time.monotonic()
                if observed_at >= deadline:
                    failure = (
                        f"subprocess {policy_id} timed out after "
                        f"{timeout_value} seconds"
                    )
                    break
                failure = _pipe_capture_failure(pipe_captures)
                if failure is not None:
                    break
                returncode = process.poll()
                if returncode is not None:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    failure = (
                        f"subprocess {policy_id} timed out after "
                        f"{timeout_value} seconds"
                    )
                    break
                lifecycle_event.wait(
                    min(float(poll_interval), remaining)
                )
                lifecycle_event.clear()

            if failure is not None:
                raise ModelCorpusError(failure)

            _require(returncode is not None, "subprocess direct child did not exit")
            if not _wait_for_pipe_readers(
                pipe_captures,
                grace_seconds=float(pipe_join_grace),
            ):
                raise ModelCorpusError(
                    f"subprocess {policy_id} parent pipe readers did not close "
                    "after direct-child exit; inherited descendant descriptors "
                    "may remain"
                )
            failure = _pipe_capture_failure(pipe_captures)
            if failure is not None:
                raise ModelCorpusError(failure)
            _require(
                all(capture.eof for capture in pipe_captures),
                f"subprocess {policy_id} parent pipe readers ended without EOF",
            )
            try:
                returncode = process.wait(timeout=float(kill_grace))
            except subprocess.TimeoutExpired as exc:
                raise ModelCorpusError(
                    f"subprocess {policy_id} direct child could not be reaped"
                ) from exc

            def read_capture(
                capture: _BoundedPipeCapture,
            ) -> bytes:
                stream = capture.capture
                stream.flush()
                before = _capture_storage_size(stream)
                _require(
                    before == capture.captured_size <= capture.limit,
                    f"subprocess {policy_id} {capture.name} exceeded "
                    f"{capture.limit} bytes",
                )
                stream.seek(0)
                payload = stream.read(capture.limit + 1)
                after = _capture_storage_size(stream)
                _require(
                    len(payload) == capture.captured_size
                    and len(payload) <= capture.limit
                    and after == before,
                    f"subprocess {policy_id} {capture.name} capture changed "
                    "after parent drain",
                )
                return bytes(payload)

            stdout = read_capture(pipe_captures[0])
            stderr = read_capture(pipe_captures[1])
            completed = subprocess.CompletedProcess(
                list(command), returncode, stdout=stdout, stderr=stderr
            )
        except BaseException as primary:
            diagnostics: list[str] = []
            for capture in pipe_captures:
                diagnostics.extend(capture.request_stop())
            if process is not None:
                diagnostics.extend(
                    _terminate_and_reap_direct_child(
                        process,
                        policy_id=policy_id,
                        kill_grace_seconds=float(kill_grace),
                    )
                )
            _wait_for_pipe_readers(
                pipe_captures,
                grace_seconds=float(pipe_join_grace),
            )
            if any(capture.thread.is_alive() for capture in pipe_captures):
                for capture in pipe_captures:
                    diagnostics.extend(capture.request_stop())
                _wait_for_pipe_readers(
                    pipe_captures,
                    grace_seconds=float(pipe_join_grace),
                )
            for capture in pipe_captures:
                if capture.thread.is_alive():
                    diagnostics.append(
                        f"subprocess {policy_id} {capture.name} reader survived "
                        "bounded cleanup"
                    )
            _attach_exception_diagnostics(primary, diagnostics)
            # An active exception retains this frame.  Drop every joined
            # Popen/pipe/thread reference before re-raising so Windows can
            # release the private cwd deterministically during caller cleanup.
            process = None
            stdout_pipe = None
            stderr_pipe = None
            pipe_captures.clear()
            raise
        cleanup_diagnostics = _close_pipe_readers(
            pipe_captures,
            grace_seconds=float(pipe_join_grace),
        )
        if cleanup_diagnostics:
            cleanup_failure = ModelCorpusError(
                f"subprocess {policy_id} pipe reader cleanup failed"
            )
            _attach_exception_diagnostics(
                cleanup_failure, cleanup_diagnostics
            )
            process = None
            stdout_pipe = None
            stderr_pipe = None
            pipe_captures.clear()
            raise cleanup_failure
        process = None
        stdout_pipe = None
        stderr_pipe = None
        pipe_captures.clear()
        return completed


class HeldMedia:
    """Identity-held, externally pinned installed media."""

    __slots__ = (
        "root",
        "path",
        "codec",
        "role",
        "descriptor",
        "stream",
        "_before",
        "_opened_before",
        "_digest",
        "_closed",
    )

    def __init__(
        self,
        *,
        root: Path,
        path: Path,
        codec: str,
        role: str,
        descriptor: Mapping[str, object],
    ) -> None:
        _assert_plain_chain(root, path, label=f"{codec}/{role} installed media")
        before = _leaf_is_plain_file(path, label=f"{codec}/{role} installed media")
        stream = _open_binary_custody(path, label=f"{codec}/{role} installed media")
        opened = os.fstat(stream.fileno())
        before_snapshot = _snapshot(before)
        opened_snapshot = _snapshot(opened)
        if not _same_path_and_handle(
            before_snapshot, before_snapshot, opened_snapshot, opened_snapshot
        ):
            stream.close()
            raise ModelCorpusError(f"{codec}/{role} media changed while custody opened")
        self.root = root
        self.path = path
        self.codec = codec
        self.role = role
        self.descriptor = dict(descriptor)
        self.stream = stream
        self._before = before_snapshot
        self._opened_before = opened_snapshot
        self._digest = self._hash_handle()
        self._closed = False
        expected_sha = _sha(descriptor.get("sha256"), label=f"{codec}/{role} receipt SHA-256")
        expected_size = _positive_int(
            descriptor.get("size_bytes"), label=f"{codec}/{role} receipt size"
        )
        if self._digest != expected_sha or self._before[3] != expected_size:
            self.close()
            raise ModelCorpusError(f"{codec}/{role} media does not match receipt")

    @property
    def sha256(self) -> str:
        return self._digest

    @property
    def size_bytes(self) -> int:
        return self._before[3]

    def _hash_handle(self) -> str:
        self.stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: self.stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
        self.stream.seek(0)
        return digest.hexdigest()

    def verify(self) -> None:
        _assert_plain_chain(self.root, self.path, label=f"{self.codec}/{self.role} media")
        after_path = _leaf_is_plain_file(
            self.path, label=f"{self.codec}/{self.role} installed media"
        )
        after_handle = os.fstat(self.stream.fileno())
        _require(
            _same_path_and_handle(
                self._before,
                _snapshot(after_path),
                self._opened_before,
                _snapshot(after_handle),
            ),
            f"{self.codec}/{self.role} media identity changed under custody",
        )
        _require(
            self._hash_handle() == self._digest,
            f"{self.codec}/{self.role} media bytes changed under custody",
        )

    def close(self) -> None:
        if not self._closed:
            self.stream.close()
            self._closed = True

    def __enter__(self) -> "HeldMedia":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _HeldPinnedFile:
    """Long-lived exact-byte custody for a tool invoked later by path."""

    def __init__(
        self, path: Path, *, label: str, expected_sha256: str | None
    ) -> None:
        self.path = path.absolute()
        self.label = label
        _require(self.path.resolve() == self.path, f"{label} path is an alias")
        before = _leaf_is_plain_file(self.path, label=label)
        self.stream = _open_binary_custody(self.path, label=label)
        try:
            opened = os.fstat(self.stream.fileno())
            self._path_snapshot = _snapshot(before)
            self._handle_snapshot = _snapshot(opened)
            _require(
                _same_path_and_handle(
                    self._path_snapshot,
                    self._path_snapshot,
                    self._handle_snapshot,
                    self._handle_snapshot,
                ),
                f"{label} changed while custody opened",
            )
            self.stream.seek(0)
            digest = hashlib.sha256()
            for block in iter(lambda: self.stream.read(8 * 1024 * 1024), b""):
                digest.update(block)
            self.stream.seek(0)
            self.sha256 = digest.hexdigest()
            if expected_sha256 is not None:
                _require(
                    self.sha256
                    == _sha(expected_sha256, label=f"{label} external pin"),
                    f"{label} does not match its external pin",
                )
            self.size_bytes = self._path_snapshot[3]
        except BaseException:
            self.stream.close()
            raise

    def verify(self) -> None:
        after_path = _leaf_is_plain_file(self.path, label=self.label)
        after_handle = os.fstat(self.stream.fileno())
        _require(
            _same_path_and_handle(
                self._path_snapshot,
                _snapshot(after_path),
                self._handle_snapshot,
                _snapshot(after_handle),
            ),
            f"{self.label} identity changed under custody",
        )
        self.stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: self.stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
        self.stream.seek(0)
        _require(digest.hexdigest() == self.sha256, f"{self.label} bytes changed under custody")

    def read_bytes(self) -> bytes:
        self.verify()
        self.stream.seek(0)
        payload = self.stream.read()
        self.stream.seek(0)
        _require(
            len(payload) == self.size_bytes and _sha256(payload) == self.sha256,
            f"{self.label} held payload drifted",
        )
        return bytes(payload)

    def close(self) -> None:
        self.stream.close()

    def __enter__(self) -> "_HeldPinnedFile":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _local_source_component_paths() -> tuple[tuple[str, str, Path], ...]:
    modules = (
        (
            "materializer",
            "scripts/materialize_kpp_legacy_iss_v2_model_corpus.py",
            Path(__file__).resolve(),
        ),
        (
            "benchmark_contract",
            "scripts/benchmark_contract.py",
            Path(str(_benchmark_contract_module.__file__)).resolve(),
        ),
        (
            "checkpoint_model_parity",
            "scripts/checkpoint_model_parity.py",
            Path(str(_checkpoint_model_parity_module.__file__)).resolve(),
        ),
        (
            "extract_kpp_legacy_iss",
            "scripts/extract_kpp_legacy_iss.py",
            Path(str(_extract_kpp_legacy_iss_module.__file__)).resolve(),
        ),
        (
            "kpp_legacy_iss_v2_manifest",
            "scripts/kpp_legacy_iss_v2_manifest.py",
            Path(str(_kpp_legacy_iss_v2_manifest_module.__file__)).resolve(),
        ),
        (
            "backend_runtime_grant",
            "scripts/backend_runtime_grant.py",
            Path(str(_backend_runtime_grant_module.__file__)).resolve(),
        ),
        (
            "model_parity_grant",
            "scripts/model_parity_grant.py",
            Path(str(_model_parity_grant_module.__file__)).resolve(),
        ),
        (
            "checkpoint_acceptance_metadata_binding",
            "scripts/checkpoint_acceptance_metadata_binding.py",
            Path(
                str(_checkpoint_acceptance_metadata_binding_module.__file__)
            ).resolve(),
        ),
        (
            "backend_publication_output_receipt",
            "scripts/backend_publication_output_receipt.py",
            Path(str(_backend_publication_output_receipt_module.__file__)).resolve(),
        ),
        (
            "formal_aw_heft_reference",
            "scripts/formal_aw_heft_reference.py",
            Path(str(_formal_aw_heft_reference_module.__file__)).resolve(),
        ),
        (
            "publication_acceptance_evidence",
            "scripts/publication_acceptance_evidence.py",
            Path(str(_publication_acceptance_evidence_module.__file__)).resolve(),
        ),
        (
            "backend_publication_dispatch",
            "scripts/backend_publication_dispatch.py",
            Path(str(_backend_publication_dispatch_module.__file__)).resolve(),
        ),
    )
    _require(
        len({component for component, _relative, _path in modules}) == len(modules)
        and len({relative for _component, relative, _path in modules}) == len(modules)
        and len({path for _component, _relative, path in modules}) == len(modules),
        "local source component set is not exact and unique",
    )
    for _component, canonical_path, path in modules:
        _require(
            path.name == PurePosixPath(canonical_path).name,
            "loaded local source module path does not match its canonical component",
        )
    return modules


def _source_set_projection(
    components: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "kpp_v2_model_corpus_local_python_source_set_v1",
        "components": [
            {
                "component": item["component"],
                "canonical_path": item["canonical_path"],
                "size_bytes": item["size_bytes"],
                "sha256": item["sha256"],
            }
            for item in components
        ],
    }


def _source_set_external_pin_for_tests() -> str:
    """Compute the source-set pin for private synthetic tests, never authority."""

    components = []
    for component, canonical_path, path in _local_source_component_paths():
        payload = path.read_bytes()
        components.append(
            {
                "component": component,
                "canonical_path": canonical_path,
                "size_bytes": len(payload),
                "sha256": _sha256(payload),
            }
        )
    return _sha256(_canonical(_source_set_projection(components)))


def _held_local_source_set(
    *,
    root: Path,
    require_canonical_runtime_paths: bool,
    expected_aggregate_sha256: str,
    custody: ExitStack,
    held_files: list[_HeldPinnedFile],
) -> tuple[dict[str, object], dict[str, bytes]]:
    components: list[dict[str, object]] = []
    payloads: dict[str, bytes] = {}
    for component, canonical_path, path in _local_source_component_paths():
        if require_canonical_runtime_paths:
            expected_path = root / Path(*PurePosixPath(canonical_path).parts)
            _require(
                path == expected_path,
                f"loaded local source component {component} is not at its canonical path",
            )
        held = custody.enter_context(
            _HeldPinnedFile(
                path,
                label=f"local source component {component}",
                expected_sha256=None,
            )
        )
        held_files.append(held)
        payload = held.read_bytes()
        payloads[component] = payload
        components.append(
            {
                "component": component,
                "canonical_path": canonical_path,
                "runtime_path": str(held.path),
                "size_bytes": held.size_bytes,
                "sha256": held.sha256,
            }
        )
    projection = _source_set_projection(components)
    aggregate_sha256 = _sha256(_canonical(projection))
    _require(
        aggregate_sha256
        == _sha(
            expected_aggregate_sha256,
            label="local source set external aggregate pin",
        ),
        "local source set does not match its external pin",
    )
    return (
        {
            "schema_version": 1,
            "artifact_kind": "vast_local_python_source_set_pin",
            "canonical_projection": projection,
            "canonical_aggregate_sha256": aggregate_sha256,
            "source_bytes_externally_pinned_and_held": True,
            "executed_python_bytecode_attested": False,
            "launcher_execution_attested": False,
            "components": components,
        },
        payloads,
    )


class _HeldOutputFile:
    """An exact output leaf held from CREATE_NEW through final verification."""

    def __init__(
        self,
        *,
        working_path: Path,
        published_path: Path,
        label: str,
        payload: bytes,
    ) -> None:
        self.working_path = working_path.absolute()
        self.published_path = published_path.absolute()
        self.label = label
        self.sha256 = _sha256(payload)
        self.size_bytes = len(payload)
        self._closed = False
        self.stream = _open_new_output_custody(self.working_path, label=label)
        try:
            self.stream.write(payload)
            self.stream.flush()
            os.fsync(self.stream.fileno())
            path_observed = _leaf_is_plain_file(self.working_path, label=label)
            handle_observed = os.fstat(self.stream.fileno())
            self._path_snapshot = _snapshot(path_observed)
            self._handle_snapshot = _snapshot(handle_observed)
            _require(
                _same_path_and_handle(
                    self._path_snapshot,
                    self._path_snapshot,
                    self._handle_snapshot,
                    self._handle_snapshot,
                ),
                f"{label} identity drifted while created",
            )
            self.verify(published=False)
        except BaseException:
            self.stream.close()
            self._closed = True
            raise

    def _hash_handle(self) -> str:
        self.stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: self.stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
        self.stream.seek(0)
        return digest.hexdigest()

    def verify(self, *, published: bool) -> None:
        path = self.published_path if published else self.working_path
        after_path = _leaf_is_plain_file(path, label=self.label)
        after_handle = os.fstat(self.stream.fileno())
        _require(
            _same_path_and_handle(
                self._path_snapshot,
                _snapshot(after_path),
                self._handle_snapshot,
                _snapshot(after_handle),
            ),
            f"held {self.label} path/handle identity drifted",
        )
        _require(
            after_path.st_size == self.size_bytes
            and self._hash_handle() == self.sha256,
            f"held {self.label} bytes drifted",
        )

    def acquire_final_custody(self) -> None:
        """Downgrade the creator handle to final no-write/no-delete custody."""

        if not self._closed:
            self.verify(published=True)
            self.stream.close()
            self._closed = True
        final_stream: BinaryIO | None = None
        try:
            before = _leaf_is_plain_file(self.published_path, label=self.label)
            final_stream = _open_binary_custody(
                self.published_path, label=f"published {self.label}"
            )
            opened = os.fstat(final_stream.fileno())
            after = _leaf_is_plain_file(self.published_path, label=self.label)
            _require(
                _same_path_and_handle(
                    self._path_snapshot,
                    _snapshot(after),
                    self._handle_snapshot,
                    _snapshot(opened),
                )
                and _snapshot(before) == _snapshot(after),
                f"held {self.label} final path/handle identity drifted",
            )
            self.stream = final_stream
            final_stream = None
            self._closed = False
            self.verify(published=True)
        except BaseException:
            if final_stream is not None:
                final_stream.close()
            raise

    def prepare_for_parent_publish(self) -> None:
        """Replace the creator handle with a FileId-bound move-compatible hold."""

        self.verify(published=False)
        self.stream.close()
        self._closed = True
        move_stream: BinaryIO | None = None
        try:
            before = _leaf_is_plain_file(self.working_path, label=self.label)
            move_stream = _open_move_compatible_output_custody(
                self.working_path, label=self.label
            )
            opened = os.fstat(move_stream.fileno())
            after = _leaf_is_plain_file(self.working_path, label=self.label)
            _require(
                _same_path_and_handle(
                    self._path_snapshot,
                    _snapshot(after),
                    self._handle_snapshot,
                    _snapshot(opened),
                )
                and _snapshot(before) == _snapshot(after),
                f"held {self.label} move-compatible identity drifted",
            )
            self.stream = move_stream
            move_stream = None
            self._closed = False
            self.verify(published=False)
        except BaseException:
            if move_stream is not None:
                move_stream.close()
            raise

    def release_for_parent_publish(self) -> None:
        """Close the verified descendant handle required by Windows parent rename."""

        self.verify(published=False)
        self.stream.close()
        self._closed = True

    def close(self) -> None:
        if not self._closed:
            self.stream.close()
            self._closed = True

    def __enter__(self) -> "_HeldOutputFile":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class _AuthoritativeCommitPending:
    """Held final commit-record bytes kept under a precommit-only name."""

    def __init__(
        self,
        *,
        working_path: Path,
        published_path: Path,
        commit_record_path: Path,
        payload: bytes,
    ) -> None:
        self.working_path = working_path.absolute()
        self.published_path = published_path.absolute()
        self.commit_record_path = commit_record_path.absolute()
        self.canonical_output_name = self.published_path.parent.name
        _require(
            self.commit_record_path.parent == self.published_path.parent
            and self.commit_record_path.name
            == AUTHORITATIVE_COMMIT_RECORD_NAME,
            "authoritative commit record path is not the canonical child",
        )
        _require(
            type(payload) is bytes and payload != b"",
            "authoritative commit record payload is empty",
        )
        self.payload = payload
        self.sha256 = _sha256(self.payload)
        self.size_bytes = len(self.payload)
        self._closed = False
        self._committed = False
        self.stream = _open_new_output_custody(
            self.working_path,
            label="authoritative commit-pending sentinel",
        )
        try:
            self.stream.write(self.payload)
            self.stream.flush()
            os.fsync(self.stream.fileno())
            path_observed = _leaf_is_plain_file(
                self.working_path,
                label="authoritative commit-pending sentinel",
            )
            handle_observed = os.fstat(self.stream.fileno())
            self._path_snapshot = _snapshot(path_observed)
            self._handle_snapshot = _snapshot(handle_observed)
            self.verify(published=False)
        except BaseException:
            self.stream.close()
            self._closed = True
            raise

    def _hash_handle(self) -> str:
        self.stream.seek(0)
        digest = hashlib.sha256()
        for block in iter(lambda: self.stream.read(1024 * 1024), b""):
            digest.update(block)
        self.stream.seek(0)
        return digest.hexdigest()

    def verify(self, *, published: bool) -> None:
        _require(not self._closed, "commit-pending sentinel custody is closed")
        path = self.published_path if published else self.working_path
        path_observed = _leaf_is_plain_file(
            path, label="authoritative commit-pending sentinel"
        )
        handle_observed = os.fstat(self.stream.fileno())
        path_snapshot = _snapshot(path_observed)
        handle_snapshot = _snapshot(handle_observed)
        _require(
            _same_path_and_handle(
                self._path_snapshot,
                path_snapshot,
                self._handle_snapshot,
                handle_snapshot,
            )
            and path_observed.st_size == self.size_bytes
            and self._hash_handle() == self.sha256,
            "authoritative commit-pending sentinel bytes or identity drifted",
        )

    def prepare_for_parent_publish(self) -> None:
        self.verify(published=False)
        self.stream.close()
        self._closed = True

    def acquire_after_publish(self) -> None:
        _require(self._closed, "commit-pending sentinel prepublish handle is still open")
        final_stream: BinaryIO | None = None
        try:
            before = _leaf_is_plain_file(
                self.published_path,
                label="published authoritative commit-pending sentinel",
            )
            final_stream = _open_commit_pending_final_custody(
                self.published_path
            )
            opened = os.fstat(final_stream.fileno())
            after = _leaf_is_plain_file(
                self.published_path,
                label="published authoritative commit-pending sentinel",
            )
            _require(
                _same_path_and_handle(
                    self._path_snapshot,
                    _snapshot(after),
                    self._handle_snapshot,
                    _snapshot(opened),
                )
                and _snapshot(before) == _snapshot(after),
                "published commit-pending sentinel FileId drifted",
            )
            self.stream = final_stream
            final_stream = None
            self._closed = False
            self.verify(published=True)
        except BaseException:
            if final_stream is not None:
                final_stream.close()
            raise

    def semantic_commit_observed(self) -> bool:
        return self._committed

    def validate_committed_record(self) -> None:
        """Validate native-rename truth through the still-held exact FileId."""

        _require(not self._closed, "commit-record custody is closed")
        _require(
            not os.path.lexists(self.published_path),
            "commit-pending name remains after purported commit",
        )
        path_observed = _leaf_is_plain_file(
            self.commit_record_path,
            label="authoritative commit record",
        )
        handle_observed = os.fstat(self.stream.fileno())
        path_snapshot = _snapshot(path_observed)
        handle_snapshot = _snapshot(handle_observed)
        original = self._handle_snapshot
        _require(
            (
                path_snapshot[0],
                path_snapshot[1],
                stat.S_IFMT(path_snapshot[2]),
                path_snapshot[3],
                path_snapshot[4],
                path_snapshot[6],
            )
            == (
                handle_snapshot[0],
                handle_snapshot[1],
                stat.S_IFMT(handle_snapshot[2]),
                handle_snapshot[3],
                handle_snapshot[4],
                handle_snapshot[6],
            )
            and (
                handle_snapshot[0],
                handle_snapshot[1],
                stat.S_IFMT(handle_snapshot[2]),
                handle_snapshot[3],
                handle_snapshot[6],
            )
            == (
                original[0],
                original[1],
                stat.S_IFMT(original[2]),
                original[3],
                original[6],
            )
            and path_observed.st_size == self.size_bytes
            and self._hash_handle() == self.sha256,
            "held authoritative commit record identity or bytes drifted",
        )

    def accept_validated_filesystem_commit(self) -> None:
        self._committed = True

    def commit_success(
        self,
        *,
        parent_custody: _WindowsDirectoryCustody,
        canonical_output_name: str,
        _test_fault_hook: Callable[[str], None] | None = None,
    ) -> None:
        _require(
            not self._committed,
            "authoritative commit-pending sentinel was already committed",
        )
        self.verify(published=True)
        hook = _test_fault_hook or (lambda _stage: None)
        parent_path = _normalized_windows_handle_path(
            _windows_directory_final_path(
                parent_custody.handle,
                label="authoritative commit-record parent",
            )
        )
        _require(
            canonical_output_name == self.canonical_output_name,
            "canonical output name does not match the bound commit guard",
        )
        expected_output_path = _normalized_windows_handle_path(
            ntpath.join(parent_path, canonical_output_name)
        )
        _require(
            _normalized_windows_handle_path(str(self.published_path.parent))
            == expected_output_path,
            "commit-pending sentinel is not under the held canonical output",
        )
        expected_record_path = _normalized_windows_handle_path(
            ntpath.join(
                expected_output_path,
                AUTHORITATIVE_COMMIT_RECORD_NAME,
            )
        )
        _require(
            _normalized_windows_handle_path(str(self.commit_record_path))
            == expected_record_path,
            "authoritative commit record target is not under the held output",
        )
        _require(
            not os.path.lexists(self.commit_record_path),
            "authoritative commit record already exists",
        )
        _require(
            _windows_directory_information(
                parent_custody.handle,
                label="authoritative commit-record parent",
            )
            == parent_custody.identity,
            "authoritative commit-record parent identity drifted",
        )
        import msvcrt

        raw_handle = msvcrt.get_osfhandle(self.stream.fileno())
        file_identity = _windows_plain_file_information(
            raw_handle,
            label="authoritative commit-pending sentinel",
        )
        _require(
            file_identity[0] == parent_custody.identity[0],
            "authoritative commit-pending sentinel changed volume",
        )
        hook("before_native_commit")
        moved, move_error = _windows_move_held_file_no_replace(
            raw_handle=raw_handle,
            target_path=str(self.commit_record_path),
        )
        if not moved:
            if move_error in (80, 183):
                raise ModelCorpusError(
                    "authoritative commit record already exists"
                )
            raise ModelCorpusError(
                "authoritative native commit move returned FALSE: "
                f"Win32 error {move_error}"
            )
        # Native TRUE places the already-receipt-bound bytes at the permanent
        # required name.  That filesystem fact, rather than this Python flag,
        # resolves an exception between the syscall return and this assignment.
        self._committed = True
        try:
            hook("after_native_commit")
        except BaseException as exc:
            _emit_nonthrowing_operational_warning(
                "postcommit observer failed after permanent commit record: "
                f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
            )

    def release_postcommit_nonthrowing(self) -> None:
        if self._closed:
            return
        try:
            _close_commit_pending_stream(self.stream)
        except BaseException as exc:
            _emit_nonthrowing_operational_warning(
                "postcommit commit-record final close failed: "
                f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
            )
        self._closed = bool(getattr(self.stream, "closed", self._closed))

    def close_for_failure(self) -> None:
        if self.semantic_commit_observed():
            self.release_postcommit_nonthrowing()
            return
        if not self._closed:
            self.stream.close()
            self._closed = True


def _finalize_commit_pending_sentinel(
    commit_pending: _AuthoritativeCommitPending,
    *,
    active_primary: BaseException | None,
) -> None:
    if commit_pending.semantic_commit_observed():
        commit_pending.release_postcommit_nonthrowing()
        return
    try:
        commit_pending.close_for_failure()
    except BaseException as exc:
        if active_primary is None:
            raise
        _attach_exception_diagnostics(
            active_primary,
            [
                "commit-pending sentinel final close also failed: "
                f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
            ],
        )


def build_neutral_sample_plan(
    frame_counts: Mapping[str, int],
) -> tuple[PlannedSample, ...]:
    """Select 30 calibration and 30 evaluation rows per branch by frame rank only."""

    _require(set(frame_counts) == set(SOURCE_ROLES), "frame counts must cover exact source roles")
    role_rows: dict[str, list[tuple[str, str, int, int]]] = {}
    assignments = (
        ("calibration", "h264"),
        ("evaluation", "h264"),
        ("calibration", "h265"),
        ("evaluation", "h265"),
    )
    for source_role in SOURCE_ROLES:
        count = frame_counts[source_role]
        _require(type(count) is int and count >= STRATA_PER_SOURCE_ROLE, f"{source_role} has fewer than 60 frames")
        rows: list[tuple[str, str, int, int]] = []
        indexes: set[int] = set()
        for stratum in range(STRATA_PER_SOURCE_ROLE):
            frame_index = ((2 * stratum + 1) * count) // (2 * STRATA_PER_SOURCE_ROLE)
            _require(frame_index not in indexes, f"{source_role} midpoint strata are not unique")
            indexes.add(frame_index)
            corpus_role, codec = assignments[stratum % 4]
            rows.append((corpus_role, codec, stratum, frame_index))
        role_rows[source_role] = rows

    plan = tuple(
        PlannedSample(
            branch=branch,
            source_role=BRANCH_SOURCE_ROLE[branch],
            corpus_role=corpus_role,
            codec=codec,
            stratum_index=stratum,
            frame_index=frame_index,
        )
        for branch in BRANCHES
        for corpus_role, codec, stratum, frame_index in role_rows[
            BRANCH_SOURCE_ROLE[branch]
        ]
    )
    _require(len(plan) == len(BRANCHES) * 60, "neutral plan cardinality drifted")
    for branch in BRANCHES:
        rows = [row for row in plan if row.branch == branch]
        for corpus_role in ("calibration", "evaluation"):
            selected = [row for row in rows if row.corpus_role == corpus_role]
            _require(len(selected) == 30, f"{branch}/{corpus_role} count drifted")
            counts = Counter(row.codec for row in selected)
            _require(counts == {"h264": 15, "h265": 15}, f"{branch}/{corpus_role} codec balance drifted")
        calibration = {row.frame_index for row in rows if row.corpus_role == "calibration"}
        evaluation = {row.frame_index for row in rows if row.corpus_role == "evaluation"}
        _require(calibration.isdisjoint(evaluation), f"{branch} corpus roles overlap")
    return plan


def _stable_payload(
    root: Path,
    path: Path,
    *,
    expected_sha256: str | None,
    expected_size: int | None,
    label: str,
    maximum_size: int | None = None,
) -> tuple[bytes, dict[str, object]]:
    _assert_plain_chain(root, path, label=label)
    before = _leaf_is_plain_file(path, label=label)
    if maximum_size is not None:
        _require(
            type(maximum_size) is int and maximum_size > 0,
            f"{label} size limit is invalid",
        )
        _require(
            int(before.st_size) <= maximum_size,
            f"{label} exceeds its finite size limit",
        )
    if expected_size is not None:
        _require(
            type(expected_size) is int and expected_size >= 0,
            f"{label} expected size is invalid",
        )
        _require(
            int(before.st_size) == expected_size,
            f"{label} size does not match its external pin",
        )
    with _open_binary_custody(path, label=label) as source:
        opened_before = os.fstat(source.fileno())
        _require(
            _same_path_and_handle(
                _snapshot(before),
                _snapshot(before),
                _snapshot(opened_before),
                _snapshot(opened_before),
            ),
            f"{label} changed before read",
        )
        if maximum_size is not None:
            _require(
                int(opened_before.st_size) <= maximum_size,
                f"{label} exceeds its finite size limit under custody",
            )
            payload = source.read(maximum_size + 1)
            _require(
                len(payload) <= maximum_size,
                f"{label} exceeded its finite size limit while read",
            )
        else:
            payload = source.read()
        opened_after = os.fstat(source.fileno())
    after = _leaf_is_plain_file(path, label=label)
    _require(
        _same_path_and_handle(
            _snapshot(before),
            _snapshot(after),
            _snapshot(opened_before),
            _snapshot(opened_after),
        ),
        f"{label} changed while read",
    )
    digest = _sha256(payload)
    if expected_sha256 is not None:
        _require(
            digest == _sha(expected_sha256, label=f"{label} external pin"),
            f"{label} does not match its external pin",
        )
    if expected_size is not None:
        _require(len(payload) == expected_size, f"{label} size does not match its external pin")
    return payload, {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": digest,
    }


class _HeldStablePayload:
    """Stream-validate one leaf and retain no-write/no-delete custody."""

    _READ_CHUNK_BYTES = 8 * 1024 * 1024

    def __init__(
        self,
        root: Path,
        path: Path,
        *,
        expected_sha256: str | None,
        expected_size: int | None,
        label: str,
        maximum_size: int,
        retain_payload: bool,
    ) -> None:
        _require(
            type(maximum_size) is int and maximum_size > 0,
            f"{label} size limit is invalid",
        )
        if expected_size is not None:
            _require(
                type(expected_size) is int and expected_size >= 0,
                f"{label} expected size is invalid",
            )
        expected_digest = (
            None
            if expected_sha256 is None
            else _sha(expected_sha256, label=f"{label} external pin")
        )
        self.root = root.absolute()
        self.path = path.absolute()
        self.label = label
        self.maximum_size = maximum_size
        self._retained_payload: bytes | None = None
        self._closed = False

        _assert_plain_chain(self.root, self.path, label=label)
        before = _leaf_is_plain_file(self.path, label=label)
        _require(
            int(before.st_size) <= maximum_size,
            f"{label} exceeds its finite size limit",
        )
        if expected_size is not None:
            _require(
                int(before.st_size) == expected_size,
                f"{label} size does not match its external pin",
            )

        self.stream = _open_binary_custody(self.path, label=label)
        try:
            opened_before = os.fstat(self.stream.fileno())
            before_snapshot = _snapshot(before)
            opened_snapshot = _snapshot(opened_before)
            _require(
                _same_path_and_handle(
                    before_snapshot,
                    before_snapshot,
                    opened_snapshot,
                    opened_snapshot,
                ),
                f"{label} changed while custody opened",
            )
            _require(
                int(opened_before.st_size) <= maximum_size,
                f"{label} exceeds its finite size limit under custody",
            )
            if expected_size is not None:
                _require(
                    int(opened_before.st_size) == expected_size,
                    f"{label} size does not match its external pin under custody",
                )

            digest = hashlib.sha256()
            retained = bytearray() if retain_payload else None
            total = 0
            self.stream.seek(0)
            while True:
                remaining = maximum_size - total
                block = self.stream.read(
                    min(self._READ_CHUNK_BYTES, remaining + 1)
                )
                if not block:
                    break
                total += len(block)
                _require(
                    total <= maximum_size,
                    f"{label} exceeded its finite size limit while read",
                )
                digest.update(block)
                if retained is not None:
                    retained.extend(block)
            self.stream.seek(0)

            opened_after = os.fstat(self.stream.fileno())
            after = _leaf_is_plain_file(self.path, label=label)
            _assert_plain_chain(self.root, self.path, label=label)
            _require(
                _same_path_and_handle(
                    before_snapshot,
                    _snapshot(after),
                    opened_snapshot,
                    _snapshot(opened_after),
                ),
                f"{label} changed while read under retained custody",
            )
            observed_digest = digest.hexdigest()
            if expected_digest is not None:
                _require(
                    observed_digest == expected_digest,
                    f"{label} does not match its external pin",
                )
            if expected_size is not None:
                _require(
                    total == expected_size,
                    f"{label} size does not match its external pin",
                )
            self._path_snapshot = before_snapshot
            self._handle_snapshot = opened_snapshot
            self.size_bytes = total
            self.sha256 = observed_digest
            if retained is not None:
                self._retained_payload = bytes(retained)
        except BaseException:
            self.stream.close()
            self._closed = True
            raise

    @property
    def payload(self) -> bytes:
        _require(
            self._retained_payload is not None,
            f"{self.label} payload was intentionally not retained",
        )
        return self._retained_payload

    @property
    def descriptor(self) -> dict[str, object]:
        return {
            "path": self.path.relative_to(self.root).as_posix(),
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    def verify(self) -> None:
        _require(not self._closed, f"{self.label} custody is closed")
        _assert_plain_chain(self.root, self.path, label=self.label)
        path_before = _leaf_is_plain_file(self.path, label=self.label)
        handle_before = os.fstat(self.stream.fileno())
        _require(
            _same_path_and_handle(
                self._path_snapshot,
                _snapshot(path_before),
                self._handle_snapshot,
                _snapshot(handle_before),
            ),
            f"{self.label} path/handle identity changed under custody",
        )

        digest = hashlib.sha256()
        total = 0
        self.stream.seek(0)
        while True:
            remaining = self.maximum_size - total
            block = self.stream.read(
                min(self._READ_CHUNK_BYTES, remaining + 1)
            )
            if not block:
                break
            total += len(block)
            _require(
                total <= self.maximum_size,
                f"{self.label} exceeded its finite size limit during final verification",
            )
            digest.update(block)
        self.stream.seek(0)
        handle_after = os.fstat(self.stream.fileno())
        path_after = _leaf_is_plain_file(self.path, label=self.label)
        _assert_plain_chain(self.root, self.path, label=self.label)
        _require(
            _same_path_and_handle(
                self._path_snapshot,
                _snapshot(path_after),
                self._handle_snapshot,
                _snapshot(handle_after),
            )
            and _snapshot(path_before) == _snapshot(path_after)
            and _snapshot(handle_before) == _snapshot(handle_after),
            f"{self.label} path/handle identity changed during final verification",
        )
        _require(
            total == self.size_bytes and digest.hexdigest() == self.sha256,
            f"{self.label} bytes changed under custody",
        )

    def close(self) -> None:
        if not self._closed:
            self.stream.close()
            self._closed = True

    def __enter__(self) -> "_HeldStablePayload":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _receipt_self_sha(value: Mapping[str, object]) -> str:
    unsigned = copy.deepcopy(dict(value))
    unsigned.pop("materialization_receipt_sha256", None)
    return _sha256(MATERIALIZATION_RECEIPT_DOMAIN + _canonical(unsigned))


def _validated_materialization_receipt(
    *,
    root: Path,
    path: Path,
    expected_size: int,
    expected_sha256: str,
    expected_self_sha256: str,
) -> tuple[dict[str, Any], bytes, dict[tuple[str, str], dict[str, Any]]]:
    expected_path = root / Path(*PurePosixPath(MATERIALIZATION_RECEIPT_PATH).parts)
    _require(path.absolute() == expected_path, "materialization receipt path is not the fixed v2 path")
    payload, _descriptor = _stable_payload(
        root,
        path,
        expected_sha256=expected_sha256,
        expected_size=_positive_int(expected_size, label="materialization receipt expected size"),
        label="materialization receipt",
    )
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ModelCorpusError("materialization receipt is not canonical ASCII JSON") from exc
    receipt = _mapping(value, label="materialization receipt")
    _require(payload == _canonical(receipt), "materialization receipt bytes are not canonical")
    exact_keys = {
        "schema_version",
        "artifact_kind",
        "generation_id",
        "status",
        "dataset_root",
        "publishable",
        "publication_authorized",
        "source_receipt_external_pins",
        "installed_artifacts",
        "dataset_entries",
        "claims",
        "materialization_receipt_sha256",
    }
    _require(set(receipt) == exact_keys, "materialization receipt schema drifted")
    expected_scalars = {
        "schema_version": 1,
        "artifact_kind": MATERIALIZATION_RECEIPT_ARTIFACT_KIND,
        "generation_id": GENERATION_ID,
        "status": "physically_assessed_candidate",
        "dataset_root": DATASET_ROOT,
        "publishable": False,
        "publication_authorized": False,
    }
    for key, expected in expected_scalars.items():
        _require(receipt.get(key) == expected and type(receipt.get(key)) is type(expected), f"materialization receipt {key} drifted")
    _require(
        receipt.get("claims") == EXPECTED_MATERIALIZATION_CLAIMS,
        "materialization receipt claims are not authoritative and exact",
    )
    declared = _sha(
        receipt.get("materialization_receipt_sha256"),
        label="materialization receipt self SHA-256",
    )
    _require(declared == _sha(expected_self_sha256, label="materialization receipt external self pin"), "materialization receipt self SHA-256 does not match its external pin")
    _require(declared == _receipt_self_sha(receipt), "materialization receipt self SHA-256 is invalid")

    installed = _sequence(receipt.get("installed_artifacts"), label="installed_artifacts")
    _require(len(installed) == 9, "materialization receipt must bind exact nine artifacts")
    observed_paths: set[str] = set()
    media: dict[tuple[str, str], dict[str, Any]] = {}
    receipt_artifacts: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(installed):
        item = _mapping(raw, label=f"installed artifact {index}")
        path_text = item.get("installed_path")
        _require(type(path_text) is str and path_text not in observed_paths, f"installed artifact {index} path is invalid or duplicated")
        observed_paths.add(str(path_text))
        _positive_int(item.get("size_bytes"), label=f"installed artifact {index} size")
        _sha(item.get("sha256"), label=f"installed artifact {index} SHA-256")
        if item.get("artifact_kind") == "media":
            codec = item.get("codec_variant")
            role = item.get("role")
            if codec in CODECS and role in SOURCE_ROLES:
                key = (str(codec), str(role))
                _require(str(path_text) == MEDIA_PATHS[key], f"{codec}/{role} installed media path drifted")
                media[key] = item
        elif item.get("artifact_kind") == "receipt":
            receipt_artifacts[str(item.get("receipt_role"))] = item
    _require(set(media) == set(MEDIA_PATHS), "receipt does not bind exact H264/H265 source-role media")
    pins = _mapping(receipt.get("source_receipt_external_pins"), label="source receipt pins")
    _require(set(pins) == {"extraction", "transcode", "metadata"}, "source receipt pin roles drifted")
    for role in pins:
        _require(role in receipt_artifacts, f"{role} installed receipt is missing")
        _require(pins[role] == receipt_artifacts[role].get("sha256"), f"{role} external pin is not receipt-bound")

    entries = _mapping(receipt.get("dataset_entries"), label="dataset_entries")
    for codec, dataset_name in DATASET_NAMES.items():
        entry = _mapping(entries.get(dataset_name), label=f"{dataset_name} entry")
        _require(entry.get("publishable") is False and entry.get("codec_variant") == codec, f"{dataset_name} candidate binding drifted")
        streams = _sequence(entry.get("streams"), label=f"{dataset_name} streams")
        expected = {
            MEDIA_PATHS[(codec, role)]: media[(codec, role)]["sha256"]
            for role in SOURCE_ROLES
        }
        observed = {
            str(_mapping(stream, label="dataset stream").get("path")): _mapping(stream, label="dataset stream").get("sha256")
            for stream in streams
        }
        _require(observed == expected, f"{dataset_name} streams are not bound to installed media")
    return receipt, payload, media


def _validated_parity_manifest(
    *, root: Path, path: Path, expected_sha256: str
) -> tuple[dict[str, Any], bytes, dict[str, Any]]:
    payload, descriptor = _stable_payload(
        root,
        path.absolute(),
        expected_sha256=expected_sha256,
        expected_size=None,
        label="model parity manifest",
    )
    try:
        value = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeyLoader)
    except (UnicodeDecodeError, TypeError, yaml.YAMLError) as exc:
        raise ModelCorpusError("model parity manifest is invalid YAML") from exc
    manifest = _mapping(value, label="model parity manifest")
    manifest_with_identity = copy.deepcopy(manifest)
    manifest_with_identity["identity"] = {
        "schema_version": 2,
        "algorithm": "sha256",
        "canonicalization": "sorted_compact_json_utf8_v2",
        "sha256": _content_sha256(manifest),
    }
    try:
        validate_manifest_identity(manifest_with_identity)
    except ContractError as exc:
        raise ModelCorpusError(
            f"model parity manifest violates the full v3 contract: {exc}"
        ) from exc
    slots = _mapping(manifest.get("workload_slots"), label="workload slots")
    sources = _mapping(manifest.get("source_registry"), label="source registry")
    branch_bindings: dict[str, Any] = {}
    tensor_names: set[str] = set()
    for branch in BRANCHES:
        slot = _mapping(slots[branch], label=f"{branch} workload slot")
        _require(slot.get("semantic_claim") == "topology_load_proxy_only", f"{branch} semantic claim drifted")
        source_ref = slot.get("source_ref")
        _require(type(source_ref) is str and source_ref in sources, f"{branch} source_ref is invalid")
        source = _mapping(sources[str(source_ref)], label=f"{branch} source")
        input_contract = _mapping(source.get("input"), label=f"{branch} source input")
        tensor_name = input_contract.get("name")
        _require(type(tensor_name) is str and tensor_name, f"{branch} tensor name is invalid")
        tensor_names.add(str(tensor_name))
        branch_bindings[branch] = {
            "branch": branch,
            "workload_slot_id": slot.get("slot_id"),
            "source_ref": source_ref,
            "source_role": BRANCH_SOURCE_ROLE[branch],
            "semantic_claim": "topology_load_proxy_only",
            "tensor_name": tensor_name,
        }
    if len(tensor_names) != 1:
        raise ScientificChoiceRequired(
            "branch tensor names differ; a scientific preprocessing choice requires PI approval"
        )
    contract = _mapping(manifest.get("preprocessing_contract"), label="preprocessing contract")
    return manifest, payload, {
        "descriptor": descriptor,
        "branch_bindings": branch_bindings,
        "tensor_name": next(iter(tensor_names)),
        "preprocessing_contract": contract,
        "preprocessing_contract_sha256": _content_sha256(contract),
    }


def _validated_frozen_dataset_config(
    *, root: Path, receipt: Mapping[str, Any]
) -> tuple[bytes, dict[str, object]]:
    """Bind both codec entries to the canonical frozen datasets contract."""

    path = root / "configs" / "datasets.yaml"
    payload, descriptor = _stable_payload(
        root,
        path,
        expected_sha256=None,
        expected_size=None,
        label="datasets manifest",
    )
    try:
        value = yaml.load(payload.decode("utf-8"), Loader=_UniqueKeyLoader)
    except (UnicodeDecodeError, TypeError, yaml.YAMLError) as exc:
        raise ModelCorpusError("datasets manifest is invalid YAML") from exc
    document = _mapping(value, label="datasets manifest")
    _require(
        set(document) == {"schema_version", "datasets"}
        and document.get("schema_version") == 1,
        "datasets manifest top-level contract drifted",
    )
    datasets = _mapping(document.get("datasets"), label="datasets registry")
    embedded = _mapping(receipt.get("dataset_entries"), label="dataset_entries")
    for name in DATASET_NAMES.values():
        configured = _mapping(datasets.get(name), label=f"configured dataset {name}")
        try:
            validated = validate_kpp_legacy_iss_v2_manifest_entry(
                name,
                configured,
                project_root=root,
                require_files=False,
            )
        except KppLegacyIssV2ManifestError as exc:
            raise ModelCorpusError(
                f"frozen v2 dataset config authority failed for {name}: {exc}"
            ) from exc
        _require(validated is True, f"frozen v2 dataset {name} was not recognized")
        without_preparation = copy.deepcopy(configured)
        without_preparation.pop("preparation", None)
        _require(
            _canonical(without_preparation) == _canonical(embedded.get(name)),
            f"receipt dataset entry {name} differs from frozen config authority",
        )
    return payload, descriptor


def _read_tool_version(path: Path, context: SubprocessContext) -> bytes:
    completed = _run_sanitized_subprocess(
        [str(path), "-version"],
        context=context,
        policy_id="tool_version",
    )
    if completed.returncode != 0 or not completed.stdout:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ModelCorpusError(f"{path.name} -version failed: {diagnostic}")
    return bytes(completed.stdout)


def _validated_tool(
    *,
    path: Path,
    role: str,
    expected_sha256: str,
    expected_version_sha256: str,
    version_reader: Callable[[Path], bytes],
    custody: ExitStack,
    held_tools: list[_HeldPinnedFile],
) -> dict[str, object]:
    candidate = path.absolute()
    held = custody.enter_context(
        _HeldPinnedFile(
            candidate,
            label=f"{role} executable",
            expected_sha256=expected_sha256,
        )
    )
    held_tools.append(held)
    try:
        version = version_reader(candidate)
    except ModelCorpusError:
        raise
    except Exception as exc:
        raise ModelCorpusError(f"{role} version query failed") from exc
    _require(type(version) is bytes and bool(version), f"{role} version output is empty")
    version_sha = _sha256(version)
    _require(version_sha == _sha(expected_version_sha256, label=f"{role} version pin"), f"{role} version does not match its external pin")
    held.verify()
    return {
        "role": role,
        "path": str(candidate),
        "size_bytes": held.size_bytes,
        "sha256": held.sha256,
        "version_output_sha256": version_sha,
    }


def _run_ffprobe(
    media: HeldMedia, tool: Path, context: SubprocessContext
) -> MediaProbe:
    command = [
        str(tool),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-count_frames",
        "-show_entries",
        "stream=index,codec_name,width,height,time_base,nb_read_frames:frame=stream_index,best_effort_timestamp",
        "-show_frames",
        "-of",
        "json",
        str(media.path),
    ]
    completed = _run_sanitized_subprocess(
        command,
        context=context,
        policy_id="ffprobe_frame_catalog",
    )
    if completed.returncode != 0:
        raise ModelCorpusError(
            f"ffprobe failed for {media.codec}/{media.role}: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
        streams = value["streams"]
        if type(streams) is not list or len(streams) != 1:
            raise ValueError("expected one video stream")
        stream = streams[0]
        frames = value["frames"]
        codec_name = str(stream["codec_name"])
        expected_codec = "hevc" if media.codec == "h265" else "h264"
        if codec_name != expected_codec:
            raise ValueError("codec mismatch")
        result = MediaProbe(
            codec=media.codec,
            width=int(stream["width"]),
            height=int(stream["height"]),
            stream_index=int(stream["index"]),
            time_base=str(stream["time_base"]),
            frame_count=int(stream["nb_read_frames"]),
            frame_pts=tuple(
                int(frame["best_effort_timestamp"])
                for frame in frames
                if int(frame["stream_index"]) == int(stream["index"])
            ),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ModelCorpusError(f"ffprobe result is invalid for {media.codec}/{media.role}") from exc
    return result


def _run_ffmpeg_decode(
    media: HeldMedia,
    indexes: tuple[int, ...],
    probe: MediaProbe,
    tool: Path,
    context: SubprocessContext,
) -> dict[int, DecodedFrame]:
    _require(indexes == tuple(sorted(set(indexes))), "decode indexes must be sorted and unique")
    expression = "+".join(f"eq(n\\,{index})" for index in indexes)
    filtergraph = f"select={expression},showinfo,settb=expr=1/1000000000,showinfo"
    command = [
        str(tool),
        "-hide_banner",
        "-loglevel",
        "info",
        "-nostdin",
        "-i",
        str(media.path),
        "-map",
        "0:v:0",
        "-an",
        "-sn",
        "-dn",
        "-vf",
        filtergraph,
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    frame_size = probe.width * probe.height * 3
    expected_stdout_bytes = frame_size * len(indexes)
    completed = _run_sanitized_subprocess(
        command,
        context=context,
        policy_id="ffmpeg_selected_frame_decode",
        exact_stdout_limit_bytes=expected_stdout_bytes,
    )
    if completed.returncode != 0:
        raise ModelCorpusError(
            f"ffmpeg decode failed for {media.codec}/{media.role}: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    stderr = completed.stderr.decode("utf-8", errors="replace")
    time_bases: dict[str, str] = {}
    rows: dict[str, list[tuple[int, int, int, int]]] = {}
    for line in stderr.splitlines():
        config = _SHOWINFO_CONFIG_RE.search(line)
        if config:
            time_bases[config.group(1)] = config.group(2)
        match = _SHOWINFO_FRAME_RE.search(line)
        if match:
            component = match.group(1)
            rows.setdefault(component, []).append(
                (
                    int(match.group("n")),
                    int(match.group("pts")),
                    int(match.group("w")),
                    int(match.group("h")),
                )
            )
    source_components = [name for name, tb in time_bases.items() if tb == probe.time_base]
    ns_components = [name for name, tb in time_bases.items() if tb == "1/1000000000"]
    _require(len(source_components) == len(ns_components) == 1, "ffmpeg showinfo time-base evidence is ambiguous")
    source_rows = rows.get(source_components[0], [])
    ns_rows = rows.get(ns_components[0], [])
    _require(len(source_rows) == len(ns_rows) == len(indexes), "ffmpeg decoded frame/PTS coverage is partial")
    _require(len(completed.stdout) == frame_size * len(indexes), "ffmpeg raw RGB byte count is partial")
    result: dict[int, DecodedFrame] = {}
    for ordinal, frame_index in enumerate(indexes):
        source_n, source_pts, width, height = source_rows[ordinal]
        ns_n, pts_ns, ns_width, ns_height = ns_rows[ordinal]
        _require(source_n == ns_n == ordinal, "ffmpeg showinfo order drifted")
        _require(
            source_pts == probe.frame_pts[frame_index],
            "ffmpeg decoded source PTS does not match the probed frame index",
        )
        _require((width, height) == (ns_width, ns_height) == (probe.width, probe.height), "ffmpeg decoded dimensions drifted")
        start = ordinal * frame_size
        rgb = bytes(completed.stdout[start : start + frame_size])
        result[frame_index] = DecodedFrame(
            frame_index=frame_index,
            source_pts=source_pts,
            source_time_base=probe.time_base,
            pts_ns=pts_ns,
            width=width,
            height=height,
            stride=width * 3,
            rgb=rgb,
        )
    return result


def _default_preprocess(
    frame: DecodedFrame,
    contract: dict[str, object],
    contract_sha256: str,
    tensor_name: str,
) -> tuple[bytes, dict[str, object]]:
    """Apply the frozen parity resize/crop/normalization without runtime imports."""

    import numpy as np

    _require(_content_sha256(contract) == contract_sha256, "preprocessing contract SHA-256 mismatch")
    required = {
        "contract_id": "imagenet_resnet_fp32_center_crop_v2",
        "decoded_color_order": "RGB",
        "tensor_color_order": "RGB",
        "decode_dtype": "uint8",
        "resize_shorter_side": 256,
        "resize_long_side_formula": "floor(long_side*256/short_side+0.5)",
        "resize_algorithm": "bilinear",
        "resize_coordinate_transform": "half_pixel",
        "half_pixel_coordinate_formula": "src=(dst+0.5)*src_size/dst_size-0.5",
        "border_mode": "edge_clamp",
        "interpolation_accumulator_dtype": "float32",
        "interpolation_output_dtype": "float32",
        "interpolation_rounding": "none",
        "resize_rounding": "round_half_up",
        "center_crop": [224, 224],
        "normalization_scale": 1.0 / 255.0,
        "normalization_mean": [0.485, 0.456, 0.406],
        "normalization_std": [0.229, 0.224, 0.225],
        "normalization_evaluation_order": (
            "float32((float32(pixel)*scale-mean[channel])/std[channel])"
        ),
        "normalization_accumulator_dtype": "float32",
        "channel_transform": "HWC_RGB_to_CHW_RGB",
        "output_dtype": "float32",
        "output_layout": "NCHW",
        "execution_shape": [1, 3, 224, 224],
        "tensor_serialization": "raw_f32_le_c_contiguous_v1",
        "tensor_header": "none",
        "tensor_endianness": "little",
        "tensor_memory_order": "C",
    }
    _require(
        set(contract) == set(required),
        "preprocessing contract fields drifted",
    )
    for key, expected in required.items():
        _require(contract.get(key) == expected, f"preprocessing {key} drifted")
    scale = contract.get("normalization_scale")
    mean = contract.get("normalization_mean")
    std = contract.get("normalization_std")
    assert type(scale) is float and type(mean) is list and type(std) is list
    _require(frame.stride == frame.width * 3 and len(frame.rgb) == frame.height * frame.stride, "decoded RGB frame is not packed")
    rows = np.frombuffer(frame.rgb, dtype=np.uint8).reshape(frame.height, frame.stride)
    source = rows[:, : frame.width * 3].reshape(frame.height, frame.width, 3).astype(np.float32, copy=False)
    shorter = min(frame.height, frame.width)
    longer = max(frame.height, frame.width)
    resized_long = math.floor(longer * 256 / shorter + 0.5)
    if frame.height <= frame.width:
        resized_height, resized_width = 256, resized_long
    else:
        resized_height, resized_width = resized_long, 256
    f32 = np.float32
    y = (np.arange(resized_height, dtype=np.float32) + f32(0.5)) * f32(frame.height / resized_height) - f32(0.5)
    x = (np.arange(resized_width, dtype=np.float32) + f32(0.5)) * f32(frame.width / resized_width) - f32(0.5)
    y0_raw = np.floor(y).astype(np.int64)
    x0_raw = np.floor(x).astype(np.int64)
    y1_raw = y0_raw + 1
    x1_raw = x0_raw + 1
    wy = (y - y0_raw.astype(np.float32)).reshape(-1, 1, 1)
    wx = (x - x0_raw.astype(np.float32)).reshape(1, -1, 1)
    y0 = np.clip(y0_raw, 0, frame.height - 1)
    y1 = np.clip(y1_raw, 0, frame.height - 1)
    x0 = np.clip(x0_raw, 0, frame.width - 1)
    x1 = np.clip(x1_raw, 0, frame.width - 1)
    one = f32(1.0)
    top = np.add(
        np.multiply(source[y0[:, None], x0[None, :], :], one - wx, dtype=np.float32),
        np.multiply(source[y0[:, None], x1[None, :], :], wx, dtype=np.float32),
        dtype=np.float32,
    )
    bottom = np.add(
        np.multiply(source[y1[:, None], x0[None, :], :], one - wx, dtype=np.float32),
        np.multiply(source[y1[:, None], x1[None, :], :], wx, dtype=np.float32),
        dtype=np.float32,
    )
    resized = np.add(
        np.multiply(top, one - wy, dtype=np.float32),
        np.multiply(bottom, wy, dtype=np.float32),
        dtype=np.float32,
    )
    top_offset = (resized_height - 224) // 2
    left_offset = (resized_width - 224) // 2
    crop = resized[top_offset : top_offset + 224, left_offset : left_offset + 224, :]
    _require(crop.shape == (224, 224, 3), "preprocessing center crop is incomplete")
    normalized = np.multiply(crop, f32(scale), dtype=np.float32)
    normalized = np.subtract(normalized, np.asarray(mean, dtype=np.float32), dtype=np.float32)
    normalized = np.divide(normalized, np.asarray(std, dtype=np.float32), dtype=np.float32)
    tensor = np.ascontiguousarray(normalized.transpose(2, 0, 1)[None, ...], dtype="<f4")
    payload = tensor.tobytes(order="C")
    return payload, {
        "name": tensor_name,
        "dtype": "float32",
        "layout": "NCHW",
        "shape": [1, 3, 224, 224],
        "byte_length": len(payload),
        "sha256": _sha256(payload),
        "preprocessing_contract_sha256": contract_sha256,
    }


def _validate_probe(probe: MediaProbe, *, media: HeldMedia) -> MediaProbe:
    _require(type(probe) is MediaProbe, f"{media.codec}/{media.role} probe type is invalid")
    _require(probe.codec == media.codec, f"{media.codec}/{media.role} probe codec drifted")
    _require(probe.width > 0 and probe.height > 0, f"{media.codec}/{media.role} dimensions are invalid")
    _require(probe.stream_index == 0, f"{media.codec}/{media.role} physical stream index must be zero")
    _require(_TIME_BASE_RE.fullmatch(probe.time_base) is not None, f"{media.codec}/{media.role} time base is invalid")
    _require(probe.frame_count >= 60, f"{media.codec}/{media.role} has fewer than 60 frames")
    _require(
        type(probe.frame_pts) is tuple
        and len(probe.frame_pts) == probe.frame_count
        and all(type(value) is int for value in probe.frame_pts)
        and all(
            later > earlier
            for earlier, later in zip(probe.frame_pts, probe.frame_pts[1:])
        ),
        f"{media.codec}/{media.role} frame PTS catalog is incomplete or non-monotonic",
    )
    return probe


def _validated_frames(
    frames: object,
    *,
    indexes: tuple[int, ...],
    probe: MediaProbe,
    media: HeldMedia,
) -> dict[int, DecodedFrame]:
    _require(type(frames) is dict and set(frames) == set(indexes), f"{media.codec}/{media.role} decoded frame coverage is not exact")
    result: dict[int, DecodedFrame] = {}
    previous_pts: int | None = None
    for index in indexes:
        frame = frames[index]
        _require(type(frame) is DecodedFrame, "decoder returned an invalid frame type")
        _require(frame.frame_index == index, "decoded source frame index drifted")
        _require(frame.source_time_base == probe.time_base, "decoded source time base drifted")
        _require(
            frame.source_pts == probe.frame_pts[index],
            "decoded source PTS/frame-index binding drifted",
        )
        _require(type(frame.source_pts) is int and type(frame.pts_ns) is int and frame.pts_ns >= 0, "decoded PTS is invalid")
        match = _TIME_BASE_RE.fullmatch(frame.source_time_base)
        assert match is not None
        numerator = int(match.group(1))
        denominator = int(match.group(2))
        exact_ns_numerator = frame.source_pts * numerator * 1_000_000_000
        _require(
            abs(frame.pts_ns * denominator - exact_ns_numerator) <= denominator,
            "decoded nanosecond PTS is not the source-PTS rescale",
        )
        _require(previous_pts is None or frame.pts_ns > previous_pts, "decoded PTS is not strictly increasing")
        previous_pts = frame.pts_ns
        _require((frame.width, frame.height, frame.stride) == (probe.width, probe.height, probe.width * 3), "decoded RGB geometry drifted")
        _require(type(frame.rgb) is bytes and len(frame.rgb) == frame.height * frame.stride, "decoded RGB bytes are partial")
        result[index] = frame
    return result


def _validated_output(
    root: Path,
    output_dir: Path,
    *,
    allow_existing: bool = False,
) -> tuple[Path, Path]:
    output = output_dir.absolute()
    try:
        relative = output.relative_to(root)
    except ValueError as exc:
        raise ModelCorpusError("output_dir escaped project_root/staging") from exc
    _require(len(relative.parts) == 2 and relative.parts[0].casefold() == "staging", "output_dir must be one direct child of project_root/staging")
    _require(relative.parts[1] not in ("", ".", ".."), "output candidate name is invalid")
    parent = root / relative.parts[0]
    _require(parent.is_dir() and not _is_link(parent), "staging parent must be a plain existing directory")
    _assert_plain_chain(root, parent, label="output staging parent")
    if os.path.lexists(output):
        _require(allow_existing, "output candidate already exists")
    return parent, output


def _descriptor(
    root: Path,
    path: Path,
    payload: bytes,
    *,
    role: str,
) -> dict[str, object]:
    return {
        "role": role,
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": _sha256(payload),
    }


def _write_new(
    root: Path,
    path: Path,
    payload: bytes,
    *,
    role: str,
    custody: ExitStack,
    held_outputs: list[_HeldOutputFile],
    published_path: Path | None = None,
) -> dict[str, object]:
    _require(path.parent.is_dir() and not _is_link(path.parent), f"{role} parent is invalid")
    held = custody.enter_context(
        _HeldOutputFile(
            working_path=path,
            published_path=published_path or path,
            label=role,
            payload=payload,
        )
    )
    held_outputs.append(held)
    return _descriptor(root, published_path or path, payload, role=role)


def _write_bundle(
    *,
    root: Path,
    path: Path,
    role: str,
    chunks: Sequence[tuple[tuple[str, str, int], bytes]],
    custody: ExitStack,
    held_outputs: list[_HeldOutputFile],
    published_path: Path | None = None,
) -> tuple[dict[str, object], dict[tuple[str, str, int], dict[str, int | str]]]:
    payload = b"".join(chunk for _key, chunk in chunks)
    descriptor = _write_new(
        root,
        path,
        payload,
        role=role,
        custody=custody,
        held_outputs=held_outputs,
        published_path=published_path,
    )
    segments: dict[tuple[str, str, int], dict[str, int | str]] = {}
    offset = 0
    for key, chunk in chunks:
        segments[key] = {
            "offset_bytes": offset,
            "segment_size_bytes": len(chunk),
            "segment_sha256": _sha256(chunk),
        }
        offset += len(chunk)
    return descriptor, segments


def _candidate_self_sha(value: Mapping[str, object]) -> str:
    unsigned = copy.deepcopy(dict(value))
    unsigned.pop("candidate_receipt_sha256", None)
    return _sha256(CANDIDATE_RECEIPT_DOMAIN + _canonical(unsigned))


def _candidate_receipt_core(value: Mapping[str, object]) -> dict[str, object]:
    core = copy.deepcopy(dict(value))
    core.pop("authoritative_commit_record", None)
    core.pop("candidate_receipt_sha256", None)
    return core


def _candidate_receipt_core_sha(value: Mapping[str, object]) -> str:
    return _sha256(
        CANDIDATE_RECEIPT_CORE_DOMAIN
        + _canonical(_candidate_receipt_core(value))
    )


def _authoritative_failed_name(token: str) -> str:
    _require(
        type(token) is str
        and _AUTHORITATIVE_FAILED_TOKEN_RE.fullmatch(token) is not None,
        "authoritative failure quarantine token is invalid",
    )
    return (
        f"{_AUTHORITATIVE_FAILED_PREFIX}{token}"
        f"{_AUTHORITATIVE_FAILED_SUFFIX}"
    )


def _authoritative_candidate_namespace_state(
    *,
    parent_custody: _WindowsDirectoryCustody,
    candidate_custody: _WindowsDirectoryCustody,
    private_candidate_name: str,
    canonical_output_name: str,
) -> tuple[str, str]:
    observed_path = _normalized_windows_handle_path(
        _windows_directory_final_path(
            candidate_custody.handle,
            label="authoritative failed candidate namespace",
        )
    )
    observed_name = ntpath.basename(observed_path)
    allowed = {
        ntpath.normcase(private_candidate_name): (
            private_candidate_name,
            "prepublication_private_candidate",
        ),
        ntpath.normcase(canonical_output_name): (
            canonical_output_name,
            "canonical_output_after_atomic_move",
        ),
    }
    selected = allowed.get(ntpath.normcase(observed_name))
    _require(
        selected is not None,
        "authoritative failed candidate moved outside its permitted namespaces",
    )
    current_name, namespace_state = selected
    _validate_windows_direct_child_custody(
        parent=parent_custody,
        child=candidate_custody,
        expected_name=current_name,
    )
    return current_name, namespace_state


def _quarantine_authoritative_candidate(
    *,
    parent_custody: _WindowsDirectoryCustody,
    candidate_custody: _WindowsDirectoryCustody,
    private_candidate_name: str,
    canonical_output_name: str,
    primary: BaseException,
) -> Path:
    """Atomically move the exact held failed candidate and add a CREATE_NEW marker."""

    _require(os.name == "nt", "authoritative failure quarantine requires Windows")
    source_name, source_state = _authoritative_candidate_namespace_state(
        parent_custody=parent_custody,
        candidate_custody=candidate_custody,
        private_candidate_name=private_candidate_name,
        canonical_output_name=canonical_output_name,
    )
    quarantine_name: str | None = None
    for _attempt in range(_AUTHORITATIVE_FAILED_NAME_ATTEMPTS):
        candidate_name = _authoritative_failed_name(secrets.token_hex(16))
        try:
            _windows_publish_directory_by_handle(
                source=candidate_custody,
                parent=parent_custody,
                target_name=candidate_name,
            )
        except ExtractionError as exc:
            if str(exc) == f"output already exists: {candidate_name}":
                continue
            raise ModelCorpusError(
                "authoritative failed candidate could not be atomically "
                f"quarantined: {_sanitized_error_text(exc)}"
            ) from exc
        quarantine_name = candidate_name
        break
    _require(
        quarantine_name is not None,
        "authoritative failure quarantine could not allocate a unique no-overwrite name",
    )
    _validate_windows_direct_child_custody(
        parent=parent_custody,
        child=candidate_custody,
        expected_name=quarantine_name,
    )
    parent_path = Path(
        _normalized_windows_handle_path(
            _windows_directory_final_path(
                parent_custody.handle,
                label="authoritative failure quarantine parent",
            )
        )
    )
    quarantine_path = parent_path / quarantine_name
    marker = {
        "schema_version": 1,
        "artifact_kind": AUTHORITATIVE_FAILURE_MARKER_ARTIFACT_KIND,
        "generation_id": GENERATION_ID,
        "status": "quarantined_authoritative_failure",
        "source_namespace_state": source_state,
        "source_namespace_name": source_name,
        "canonical_output_name": canonical_output_name,
        "quarantine_namespace_name": quarantine_name,
        "candidate_directory_identity": {
            "volume_serial_number": candidate_custody.identity[0],
            "file_index": candidate_custody.identity[1],
        },
        "primary_exception": {
            "type": type(primary).__name__,
            "message": _sanitized_error_text(primary),
        },
        "promotable": False,
        "publication_authorized": False,
        "evidence_accepted": False,
        "candidate_success_attested": False,
        "manual_forensic_review_required": True,
        "forensic_remnant_only": True,
        "tree_integrity_attested": False,
        "directory_namespace_immutability_attested": False,
        "future_candidate_tree_immutability_attested": False,
    }
    marker_payload = _canonical(marker)
    try:
        _write_authoritative_failure_marker_atomic(
            candidate_custody=candidate_custody,
            quarantine_path=quarantine_path,
            marker_payload=marker_payload,
        )
        _validate_windows_direct_child_custody(
            parent=parent_custody,
            child=candidate_custody,
            expected_name=quarantine_name,
        )
    except BaseException as exc:
        raise ModelCorpusError(
            f"authoritative candidate was quarantined as {quarantine_name}, "
            "but its CREATE_NEW failure marker could not be committed: "
            f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
        ) from exc
    return quarantine_path


def _quarantine_authoritative_failure(
    *,
    parent_custody: _WindowsDirectoryCustody,
    candidate_custody: _WindowsDirectoryCustody,
    private_candidate_name: str,
    canonical_output_name: str,
    output_file_custody: ExitStack,
    primary: BaseException,
) -> Path | None:
    diagnostics: list[str] = []
    try:
        output_file_custody.close()
    except BaseException as exc:
        diagnostics.append(
            "authoritative failure descendant custody close failed: "
            f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
        )
    _attach_exception_diagnostics(primary, diagnostics)
    try:
        return _quarantine_authoritative_candidate(
            parent_custody=parent_custody,
            candidate_custody=candidate_custody,
            private_candidate_name=private_candidate_name,
            canonical_output_name=canonical_output_name,
            primary=primary,
        )
    except BaseException as exc:
        _attach_exception_diagnostics(
            primary,
            [
                "authoritative failure quarantine failed: "
                f"{type(exc).__name__}: {_sanitized_error_text(exc)}"
            ],
        )
        return None


def _resolve_authoritative_commit_failure(
    *,
    project_root: Path,
    authoritative: bool,
    succeeded: bool,
    commit_pending: _AuthoritativeCommitPending | None,
    parent_custody: _WindowsDirectoryCustody | None,
    candidate_custody: _WindowsDirectoryCustody | None,
    private_candidate_name: str | None,
    canonical_output_name: str,
    output_file_custody: ExitStack,
    primary: BaseException,
) -> bool:
    """Apply the exact main-path commit decision and quarantine policy."""

    semantic_commit_observed = bool(
        authoritative
        and succeeded
        and commit_pending is not None
        and commit_pending.semantic_commit_observed()
    )
    if semantic_commit_observed:
        return True
    if authoritative and succeeded and commit_pending is not None:
        try:
            _validate_committed_authoritative_candidate(
                project_root=project_root,
                output=commit_pending.commit_record_path.parent,
                held_commit_record=commit_pending,
            )
            commit_pending.accept_validated_filesystem_commit()
            return True
        except ModelCorpusError as validation_exc:
            _attach_exception_diagnostics(
                primary,
                [
                    "permanent commit-record validation before quarantine "
                    "failed: "
                    f"{_sanitized_error_text(validation_exc)}"
                ],
            )
    if commit_pending is not None:
        try:
            commit_pending.close_for_failure()
        except BaseException as sentinel_close_exc:
            _attach_exception_diagnostics(
                primary,
                [
                    "commit-pending sentinel close before quarantine failed: "
                    f"{type(sentinel_close_exc).__name__}: "
                    f"{_sanitized_error_text(sentinel_close_exc)}"
                ],
            )
    if (
        authoritative
        and candidate_custody is not None
        and parent_custody is not None
        and private_candidate_name is not None
    ):
        _quarantine_authoritative_failure(
            parent_custody=parent_custody,
            candidate_custody=candidate_custody,
            private_candidate_name=private_candidate_name,
            canonical_output_name=canonical_output_name,
            output_file_custody=output_file_custody,
            primary=primary,
        )
    return False


def _cleanup_test_candidate(path: Path) -> None:
    if not os.path.lexists(path):
        return
    _require(
        path.parent.name.casefold() == "staging"
        and path.name.startswith(".kpp-v2-model-corpus.")
        and path.name.endswith(".candidate")
        and not _is_link(path),
        "refusing to clean an unowned test candidate",
    )
    for current, directories, files in os.walk(path, topdown=False, followlinks=False):
        current_path = Path(current)
        for name in files:
            item = current_path / name
            _require(not _is_link(item), "refusing to clean a linked candidate file")
            item.unlink()
        for name in directories:
            item = current_path / name
            _require(not _is_link(item), "refusing to clean a linked candidate directory")
            item.rmdir()
    path.rmdir()


def _validate_exact_tree(root: Path, expected_files: set[str], expected_dirs: set[str]) -> None:
    observed_files: set[str] = set()
    observed_dirs: set[str] = set()
    root_before = _snapshot(root.lstat())
    pending = [root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                path = Path(entry.path)
                _require(not _is_link(path), "candidate tree contains a link/reparse point")
                # Windows DirEntry.stat may report st_nlink=0; lstat provides
                # the link count used by the held-file checks as well.
                observed = path.lstat()
                relative = path.relative_to(root).as_posix()
                if stat.S_ISDIR(observed.st_mode):
                    observed_dirs.add(relative)
                    pending.append(path)
                elif stat.S_ISREG(observed.st_mode):
                    _require(int(observed.st_nlink) == 1, "candidate tree contains a hardlink")
                    observed_files.add(relative)
                else:
                    raise ModelCorpusError("candidate tree contains a non-file object")
    _require(observed_files == expected_files, "candidate file set is not exact")
    _require(observed_dirs == expected_dirs, "candidate directory set is not exact")
    _require(_snapshot(root.lstat()) == root_before, "candidate root changed while scanned")


def _exact_receipt_mapping(
    value: object,
    *,
    keys: set[str],
    label: str,
) -> dict[str, object]:
    _require(
        type(value) is dict and set(value) == keys,
        f"{label} schema is not exact",
    )
    return value


def _validate_sha256_value(value: object, *, label: str) -> str:
    _require(
        type(value) is str and _SHA256_RE.fullmatch(value) is not None,
        f"{label} SHA-256 is invalid",
    )
    return value


def _validate_output_descriptor_schema(
    value: object,
    *,
    label: str,
) -> dict[str, object]:
    descriptor = _exact_receipt_mapping(
        value,
        keys={"role", "path", "size_bytes", "sha256"},
        label=label,
    )
    _require(
        type(descriptor["role"]) is str
        and bool(descriptor["role"])
        and type(descriptor["path"]) is str
        and bool(descriptor["path"])
        and type(descriptor["size_bytes"]) is int
        and descriptor["size_bytes"] >= 0,
        f"{label} values are invalid",
    )
    _validate_sha256_value(descriptor["sha256"], label=label)
    return descriptor


def _validate_authoritative_candidate_receipt_schema(
    receipt: Mapping[str, object],
) -> None:
    _require(
        set(receipt)
        == {
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
        },
        "authoritative candidate receipt top-level schema is not exact",
    )
    _require(
        receipt["schema_version"] == 1
        and receipt["artifact_kind"] == RECEIPT_ARTIFACT_KIND
        and receipt["generation_id"] == GENERATION_ID
        and receipt["status"] == "materialized_nonpromotable_candidate"
        and receipt["promotable"] is False
        and receipt["publication_authorized"] is False
        and receipt["evidence_accepted"] is False
        and receipt["pi_approval_status"] == "required"
        and receipt["sampling_rule"] == SAMPLING_RULE
        and receipt["sampling_rule_sha256"]
        == _sha256(_canonical(SAMPLING_RULE))
        and receipt["claims"] == CLAIMS,
        "authoritative candidate receipt fixed contract drifted",
    )
    output_root = receipt["output_root"]
    _require(
        type(output_root) is str
        and len(PurePosixPath(output_root).parts) == 2
        and PurePosixPath(output_root).parts[0].casefold() == "staging"
        and all(
            component not in {"", ".", ".."}
            for component in PurePosixPath(output_root).parts
        ),
        "authoritative candidate output_root is invalid",
    )
    _validate_sha256_value(
        receipt["source_model_parity_manifest_sha256"],
        label="source model parity manifest",
    )
    _validate_sha256_value(
        receipt["dataset_aggregate_sha256"],
        label="dataset aggregate",
    )
    _validate_sha256_value(
        receipt["candidate_receipt_sha256"],
        label="candidate receipt self hash",
    )
    _require(
        receipt["source_materialization_receipt"]
        == {
            "path": MATERIALIZATION_RECEIPT_PATH,
            "size_bytes": EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES,
            "sha256": EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
            "materialization_receipt_sha256": (
                EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256
            ),
        },
        "authoritative candidate source receipt authority drifted",
    )
    source_dataset = _exact_receipt_mapping(
        receipt["source_dataset_config"],
        keys={"source", "snapshot", "canonical_frozen_validator_applied"},
        label="source dataset config",
    )
    _require(
        source_dataset["canonical_frozen_validator_applied"] is True,
        "source dataset config is not canonical-authority validated",
    )
    dataset_source = _exact_receipt_mapping(
        source_dataset["source"],
        keys={"path", "size_bytes", "sha256"},
        label="source dataset config source",
    )
    _require(
        dataset_source["path"] == "configs/datasets.yaml"
        and type(dataset_source["size_bytes"]) is int
        and dataset_source["size_bytes"] > 0,
        "source dataset config source values are invalid",
    )
    _validate_sha256_value(
        dataset_source["sha256"], label="source dataset config"
    )
    dataset_snapshot = _validate_output_descriptor_schema(
        source_dataset["snapshot"], label="source dataset config snapshot"
    )
    _require(
        dataset_snapshot["role"]
        == "source frozen dataset config snapshot"
        and dataset_snapshot["path"]
        == f"{output_root}/source_dataset_config.yaml"
        and dataset_snapshot["size_bytes"] == dataset_source["size_bytes"]
        and dataset_snapshot["sha256"] == dataset_source["sha256"],
        "source dataset config snapshot binding drifted",
    )
    branch_bindings = _exact_receipt_mapping(
        receipt["branch_source_mapping"],
        keys=set(BRANCHES),
        label="branch source mapping",
    )
    expected_slots = {
        "plate_number": ("opaque_rn18", "resnet18_v1_7"),
        "vehicle_type": ("opaque_rn34", "resnet34_v1_7"),
        "damage": ("opaque_rn50", "resnet50_v1_12"),
        "foreign_object": ("opaque_rn101", "resnet101_v1_7"),
    }
    for branch in BRANCHES:
        binding = _exact_receipt_mapping(
            branch_bindings[branch],
            keys={
                "branch",
                "workload_slot_id",
                "source_ref",
                "source_role",
                "semantic_claim",
                "tensor_name",
            },
            label=f"{branch} source binding",
        )
        slot_id, source_ref = expected_slots[branch]
        _require(
            binding
            == {
                "branch": branch,
                "workload_slot_id": slot_id,
                "source_ref": source_ref,
                "source_role": BRANCH_SOURCE_ROLE[branch],
                "semantic_claim": "topology_load_proxy_only",
                "tensor_name": "data",
            },
            f"{branch} source binding drifted",
        )
    outputs = receipt["outputs"]
    _require(type(outputs) is list, "candidate receipt outputs are invalid")
    output_by_path: dict[str, dict[str, object]] = {}
    for index, item in enumerate(outputs):
        descriptor = _validate_output_descriptor_schema(
            item, label=f"candidate output descriptor {index}"
        )
        path = descriptor["path"]
        assert type(path) is str
        _require(
            path not in output_by_path,
            "candidate receipt output paths are not unique",
        )
        output_by_path[path] = descriptor
    _require(
        outputs == sorted(outputs, key=lambda item: str(item["path"])),
        "candidate receipt outputs are not canonically ordered",
    )
    _require(
        output_by_path.get(str(dataset_snapshot["path"]))
        == dataset_snapshot,
        "source dataset snapshot is not in the exact output set",
    )
    source_receipt_snapshot = output_by_path.get(
        f"{output_root}/source_materialization_receipt.json"
    )
    _require(
        source_receipt_snapshot
        == {
            "role": "source materialization receipt snapshot",
            "path": f"{output_root}/source_materialization_receipt.json",
            "size_bytes": EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES,
            "sha256": EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
        },
        "source materialization receipt snapshot binding drifted",
    )
    source_parity_snapshot = output_by_path.get(
        f"{output_root}/source_model_parity_manifest.yaml"
    )
    _require(
        type(source_parity_snapshot) is dict
        and source_parity_snapshot.get("role")
        == "source model parity manifest snapshot"
        and source_parity_snapshot.get("path")
        == f"{output_root}/source_model_parity_manifest.yaml"
        and source_parity_snapshot.get("sha256")
        == receipt["source_model_parity_manifest_sha256"],
        "source model parity snapshot binding drifted",
    )
    expected_output_roles = {
        f"{output_root}/source_materialization_receipt.json": (
            "source materialization receipt snapshot"
        ),
        f"{output_root}/source_model_parity_manifest.yaml": (
            "source model parity manifest snapshot"
        ),
        f"{output_root}/source_dataset_config.yaml": (
            "source frozen dataset config snapshot"
        ),
        f"{output_root}/dataset_manifest.json": "candidate dataset manifest",
    }
    for component_name in (
        component
        for component, _canonical_path, _runtime_path
        in _local_source_component_paths()
    ):
        expected_output_roles[
            f"{output_root}/source_code_{component_name}.py"
        ] = f"externally pinned {component_name} source snapshot"
    for branch in BRANCHES:
        for corpus_role in ("calibration", "evaluation"):
            expected_output_roles[
                f"{output_root}/corpus_{branch}_{corpus_role}.json"
            ] = f"{branch}/{corpus_role} corpus candidate"
    for codec in CODECS:
        for source_role in SOURCE_ROLES:
            expected_output_roles[
                f"{output_root}/raw_{codec}_{source_role}.rgb24.bin"
            ] = f"{codec}/{source_role} decoded RGB bundle"
            expected_output_roles[
                f"{output_root}/tensor_{codec}_{source_role}.f32.bin"
            ] = f"{codec}/{source_role} preprocessed tensor bundle"
    _require(
        set(output_by_path) == set(expected_output_roles)
        and all(
            output_by_path[path]["role"] == role
            for path, role in expected_output_roles.items()
        ),
        "authoritative candidate output role/path set drifted",
    )
    tool_pins = _exact_receipt_mapping(
        receipt["tool_pins"],
        keys={
            "ffmpeg",
            "ffprobe",
            "materializer",
            "preprocessor",
            "local_source_set",
            "subprocess_context",
        },
        label="tool pins",
    )
    argv_hashes = {
        "ffprobe": _sha256(
            _canonical(
                [
                    "FFPROBE", "-v", "error", "-select_streams", "v:0",
                    "-count_frames", "-show_entries",
                    "stream=index,codec_name,width,height,time_base,nb_read_frames:frame=stream_index,best_effort_timestamp",
                    "-show_frames", "-of", "json", "SOURCE",
                ]
            )
        ),
        "ffmpeg": _sha256(
            _canonical(
                [
                    "FFMPEG", "-hide_banner", "-loglevel", "info", "-nostdin",
                    "-i", "SOURCE", "-map", "0:v:0", "-an", "-sn", "-dn",
                    "-vf",
                    "select=EXACT_FRAME_INDEX_SET,showinfo,settb=expr=1/1000000000,showinfo",
                    "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f",
                    "rawvideo", "pipe:1",
                ]
            )
        ),
    }
    for role in ("ffmpeg", "ffprobe"):
        pin = _exact_receipt_mapping(
            tool_pins[role],
            keys={
                "role",
                "path",
                "size_bytes",
                "sha256",
                "version_output_sha256",
                "canonical_argv_template_sha256",
            },
            label=f"{role} pin",
        )
        _require(
            pin["role"] == role
            and type(pin["path"]) is str
            and bool(pin["path"])
            and type(pin["size_bytes"]) is int
            and pin["size_bytes"] > 0
            and pin["canonical_argv_template_sha256"] == argv_hashes[role],
            f"{role} pin values drifted",
        )
        _validate_sha256_value(pin["sha256"], label=f"{role} executable")
        _validate_sha256_value(
            pin["version_output_sha256"], label=f"{role} version"
        )
    local_source_set = _exact_receipt_mapping(
        tool_pins["local_source_set"],
        keys={
            "schema_version",
            "artifact_kind",
            "canonical_projection",
            "canonical_aggregate_sha256",
            "source_bytes_externally_pinned_and_held",
            "executed_python_bytecode_attested",
            "launcher_execution_attested",
            "components",
        },
        label="local source set",
    )
    _require(
        local_source_set["schema_version"] == 1
        and local_source_set["artifact_kind"]
        == "vast_local_python_source_set_pin"
        and local_source_set["source_bytes_externally_pinned_and_held"] is True
        and local_source_set["executed_python_bytecode_attested"] is False
        and local_source_set["launcher_execution_attested"] is False
        and type(local_source_set["components"]) is list,
        "local source set fixed contract drifted",
    )
    components = local_source_set["components"]
    assert type(components) is list
    expected_components = {
        component: canonical_path
        for component, canonical_path, _path in _local_source_component_paths()
    }
    component_by_name: dict[str, dict[str, object]] = {}
    for component in components:
        item = _exact_receipt_mapping(
            component,
            keys={
                "component",
                "canonical_path",
                "runtime_path",
                "size_bytes",
                "sha256",
                "source_snapshot",
            },
            label="local source component",
        )
        name = item["component"]
        _require(
            type(name) is str
            and name in expected_components
            and name not in component_by_name
            and item["canonical_path"] == expected_components[name]
            and type(item["runtime_path"]) is str
            and bool(item["runtime_path"])
            and type(item["size_bytes"]) is int
            and item["size_bytes"] > 0,
            "local source component values drifted",
        )
        _validate_sha256_value(
            item["sha256"], label=f"local source component {name}"
        )
        snapshot = _validate_output_descriptor_schema(
            item["source_snapshot"],
            label=f"local source component {name} snapshot",
        )
        _require(
            snapshot["role"] == f"externally pinned {name} source snapshot"
            and snapshot["path"] == f"{output_root}/source_code_{name}.py"
            and snapshot["size_bytes"] == item["size_bytes"]
            and snapshot["sha256"] == item["sha256"]
            and output_by_path.get(str(snapshot["path"])) == snapshot,
            f"local source component {name} snapshot binding drifted",
        )
        component_by_name[name] = item
    _require(
        set(component_by_name) == set(expected_components)
        and [item["component"] for item in components]
        == list(expected_components),
        "local source component set drifted",
    )
    projection = _exact_receipt_mapping(
        local_source_set["canonical_projection"],
        keys={"schema_version", "contract_id", "components"},
        label="local source set projection",
    )
    expected_projection = _source_set_projection(components)
    _require(
        projection == expected_projection
        and local_source_set["canonical_aggregate_sha256"]
        == _sha256(_canonical(expected_projection)),
        "local source set aggregate binding drifted",
    )
    source_set_sha256 = local_source_set["canonical_aggregate_sha256"]
    materializer_snapshot = component_by_name["materializer"][
        "source_snapshot"
    ]
    for role in ("materializer", "preprocessor"):
        expected_role = {
            "materializer": "model corpus materializer source",
            "preprocessor": "candidate preprocessing implementation source",
        }[role]
        expected_keys = {
            "path",
            "size_bytes",
            "sha256",
            "source_set_canonical_aggregate_sha256",
            "source_bytes_externally_pinned_and_held",
            "executed_python_bytecode_attested",
            "launcher_execution_attested",
            "role",
            "source_snapshot",
        }
        if role == "preprocessor":
            expected_keys.add("implementation_symbol")
        pin = _exact_receipt_mapping(
            tool_pins[role], keys=expected_keys, label=f"{role} source pin"
        )
        _require(
            pin["source_set_canonical_aggregate_sha256"] == source_set_sha256
            and pin["source_bytes_externally_pinned_and_held"] is True
            and pin["executed_python_bytecode_attested"] is False
            and pin["launcher_execution_attested"] is False
            and pin["source_snapshot"] == materializer_snapshot
            and pin["size_bytes"] == component_by_name["materializer"]["size_bytes"]
            and pin["sha256"] == component_by_name["materializer"]["sha256"]
            and pin["path"] == component_by_name["materializer"]["runtime_path"]
            and pin["role"] == expected_role,
            f"{role} source pin binding drifted",
        )
        if role == "preprocessor":
            _require(
                pin["implementation_symbol"] == "_default_preprocess",
                "preprocessor implementation symbol drifted",
            )
    subprocess_pin = _exact_receipt_mapping(
        tool_pins["subprocess_context"],
        keys={"canonical_projection", "canonical_sha256"},
        label="subprocess context pin",
    )
    subprocess_projection = _exact_receipt_mapping(
        subprocess_pin["canonical_projection"],
        keys={
            "schema_version",
            "policy_id",
            "inherited_environment_used",
            "windows_directory_source",
            "environment",
            "environment_allowlist",
            "forbidden_inherited_examples",
            "cwd",
            "stdin",
            "stdout",
            "stderr",
            "capture_transport",
            "capture_storage",
            "shell",
            "dynamic_library_closure_attested",
            "process_tree_termination_attested",
            "capture_files_inside_private_cwd",
            "capture_file_handles_inherited_by_child",
            "accepted_output_size_bounded",
            "temporary_capture_file_growth_hard_limited",
            "capture_storage_growth_hard_limited",
            "filesystem_allocation_quota_attested",
            "direct_child_output_truncation_on_success",
            "descendant_output_completion_attested",
            "pipe_capture_chunk_bytes",
            "pipe_reader_join_grace_seconds",
            "resource_poll_interval_seconds",
            "direct_child_kill_reap_grace_seconds",
            "subprocess_resource_policies",
        },
        label="subprocess context projection",
    )
    capture_storage = _exact_receipt_mapping(
        subprocess_projection["capture_storage"],
        keys={
            "platform_family",
            "storage_kind",
            "creation_primitive",
            "namespace_visibility",
            "same_token_path_reopen_for_write_denied",
            "capture_file_exists",
        },
        label="subprocess capture storage projection",
    )
    environment = _exact_receipt_mapping(
        subprocess_projection["environment"],
        keys={"LANG", "LC_ALL", "SystemRoot", "TZ", "WINDIR"},
        label="subprocess environment",
    )
    cwd = _exact_receipt_mapping(
        subprocess_projection["cwd"],
        keys={"role", "published_path", "same_directory_published_atomically"},
        label="subprocess cwd",
    )
    _require(
        subprocess_projection["schema_version"] == 4
        and subprocess_projection["policy_id"]
        == "kpp_model_corpus_minimal_subprocess_context_v4"
        and subprocess_projection["inherited_environment_used"] is False
        and subprocess_projection["windows_directory_source"]
        == "GetWindowsDirectoryW"
        and environment["LANG"] == environment["LC_ALL"] == "C"
        and environment["TZ"] == "UTC"
        and environment["SystemRoot"] == environment["WINDIR"]
        and subprocess_projection["environment_allowlist"]
        == ["LANG", "LC_ALL", "SystemRoot", "TZ", "WINDIR"]
        and subprocess_projection["forbidden_inherited_examples"]
        == [
            "FFREPORT", "FFMPEG_DATADIR", "LD_PRELOAD", "LD_LIBRARY_PATH",
            "DYLD_INSERT_LIBRARIES", "PYTHONHOME", "PYTHONPATH",
            "CUDA_CACHE_PATH", "CUDA_VISIBLE_DEVICES", "GST_PLUGIN_PATH",
            "OPENVINO_LIB_PATHS", "OPENCV_OPENCL_RUNTIME",
        ]
        and cwd
        == {
            "role": "private_candidate_root_prepublication",
            "published_path": output_root,
            "same_directory_published_atomically": True,
        }
        and subprocess_projection["stdin"] == "DEVNULL"
        and subprocess_projection["stdout"]
        == "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE"
        and subprocess_projection["stderr"]
        == "PARENT_DRAINED_PIPE_TO_PRIVATE_HARD_BOUNDED_CAPTURE"
        and subprocess_projection["capture_transport"]
        == "PARENT_DRAINED_OS_PIPE"
        and capture_storage == _capture_storage_projection()
        and subprocess_projection["shell"] is False
        and subprocess_projection["dynamic_library_closure_attested"] is False
        and subprocess_projection["process_tree_termination_attested"] is False
        and subprocess_projection["capture_files_inside_private_cwd"]
        is (os.name == "nt")
        and subprocess_projection["capture_file_handles_inherited_by_child"] is False
        and subprocess_projection["accepted_output_size_bounded"] is True
        and subprocess_projection["temporary_capture_file_growth_hard_limited"]
        is (True if os.name == "nt" else None)
        and subprocess_projection["capture_storage_growth_hard_limited"] is True
        and subprocess_projection["filesystem_allocation_quota_attested"] is False
        and subprocess_projection["direct_child_output_truncation_on_success"] is False
        and subprocess_projection["descendant_output_completion_attested"] is False
        and subprocess_projection["pipe_capture_chunk_bytes"]
        == _PIPE_CAPTURE_CHUNK_BYTES
        and subprocess_projection["pipe_reader_join_grace_seconds"]
        == _PIPE_READER_JOIN_GRACE_SECONDS
        and subprocess_projection["resource_poll_interval_seconds"] == 0.01
        and subprocess_projection["direct_child_kill_reap_grace_seconds"] == 5
        and subprocess_projection["subprocess_resource_policies"]
        == _SUBPROCESS_RESOURCE_POLICIES
        and subprocess_pin["canonical_sha256"]
        == _sha256(_canonical(subprocess_projection)),
        "subprocess context binding drifted",
    )


def _authoritative_commit_record_from_receipt(
    receipt: Mapping[str, object],
) -> tuple[bytes, dict[str, object]]:
    try:
        output_root = receipt["output_root"]
        outputs = receipt["outputs"]
        sampling_rule_sha256 = receipt["sampling_rule_sha256"]
        source_receipt = receipt["source_materialization_receipt"]
        parity_sha256 = receipt["source_model_parity_manifest_sha256"]
        tool_pins = receipt["tool_pins"]
        descriptor = receipt["authoritative_commit_record"]
    except KeyError as exc:
        raise ModelCorpusError(
            "candidate receipt omits the authoritative commit-record binding"
        ) from exc
    _require(
        type(output_root) is str
        and output_root not in {"", ".", ".."}
        and not output_root.startswith("/")
        and "\\" not in output_root,
        "candidate receipt output_root is invalid",
    )
    output_name = PurePosixPath(output_root).name
    _require(
        type(outputs) is list,
        "candidate receipt outputs are invalid",
    )
    _require(
        sampling_rule_sha256 == _sha256(_canonical(SAMPLING_RULE)),
        "candidate receipt sampling rule does not match the canonical rule",
    )
    _require(
        type(source_receipt) is dict
        and type(tool_pins) is dict
        and type(tool_pins.get("local_source_set")) is dict,
        "candidate receipt commit-record provenance is invalid",
    )
    local_source_set = tool_pins["local_source_set"]
    source_set_sha256 = local_source_set.get(
        "canonical_aggregate_sha256"
    )
    _require(
        type(descriptor) is dict
        and set(descriptor) == {"path", "size_bytes", "sha256"},
        "candidate receipt authoritative commit-record descriptor is not exact",
    )
    payload = _authoritative_commit_record_payload(
        canonical_output_root=output_root,
        canonical_output_name=output_name,
        outputs_sha256=_sha256(_canonical(outputs)),
        sampling_rule_sha256=sampling_rule_sha256,
        source_set_canonical_aggregate_sha256=source_set_sha256,
        source_materialization_receipt=source_receipt,
        source_model_parity_manifest_sha256=parity_sha256,
        candidate_receipt_core_sha256=(
            _candidate_receipt_core_sha(receipt)
        ),
    )
    expected_descriptor = {
        "path": (
            f"{output_root}/{AUTHORITATIVE_COMMIT_RECORD_NAME}"
        ),
        "size_bytes": len(payload),
        "sha256": _sha256(payload),
    }
    _require(
        descriptor == expected_descriptor,
        "candidate receipt authoritative commit-record binding drifted",
    )
    return payload, expected_descriptor


def _validate_committed_authoritative_candidate(
    *,
    project_root: Path,
    output: Path,
    held_commit_record: _AuthoritativeCommitPending | None = None,
) -> dict[str, object]:
    """Point-in-time validator whose success requires the permanent record."""

    root = project_root.absolute()
    candidate = output.absolute()
    _require(root.is_dir() and not _is_link(root), "project root is invalid")
    _assert_plain_chain(root, candidate, label="authoritative candidate output")
    _require(
        candidate.is_dir() and not _is_link(candidate),
        "authoritative candidate output is invalid",
    )
    parent = candidate.parent
    _require(parent.is_dir() and not _is_link(parent), "candidate parent is invalid")
    root_identity = _directory_identity(root.lstat())
    parent_identity = _directory_identity(parent.lstat())
    candidate_identity = _directory_identity(candidate.lstat())

    with ExitStack() as validation_custody:
        held_payloads: list[_HeldStablePayload] = []
        receipt_hold = validation_custody.enter_context(
            _HeldStablePayload(
                root,
                candidate / RECEIPT_NAME,
                expected_sha256=None,
                expected_size=None,
                label="authoritative candidate receipt",
                maximum_size=AUTHORITATIVE_CANDIDATE_RECEIPT_MAX_BYTES,
                retain_payload=True,
            )
        )
        held_payloads.append(receipt_hold)
        receipt_payload = receipt_hold.payload
        try:
            receipt = json.loads(receipt_payload.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelCorpusError(
                "authoritative candidate receipt is not canonical ASCII JSON"
            ) from exc
        _require(
            type(receipt) is dict and _canonical(receipt) == receipt_payload,
            "authoritative candidate receipt is not exact canonical JSON",
        )
        _validate_authoritative_candidate_receipt_schema(receipt)
        output_root = receipt["output_root"]
        assert type(output_root) is str
        expected_output = root / Path(*PurePosixPath(output_root).parts)
        _require(
            candidate == expected_output.absolute(),
            "authoritative candidate receipt binds a different output root",
        )
        record_payload, record_descriptor = (
            _authoritative_commit_record_from_receipt(receipt)
        )
        outputs = receipt["outputs"]
        assert type(outputs) is list
        expected_files = {RECEIPT_NAME, AUTHORITATIVE_COMMIT_RECORD_NAME}
        validation_paths = [
            candidate / RECEIPT_NAME,
            candidate / AUTHORITATIVE_COMMIT_RECORD_NAME,
        ]
        for item in outputs:
            _require(
                type(item) is dict
                and set(item) == {"role", "path", "size_bytes", "sha256"}
                and type(item["path"]) is str
                and type(item["size_bytes"]) is int
                and item["size_bytes"] >= 0
                and type(item["sha256"]) is str
                and _SHA256_RE.fullmatch(item["sha256"]) is not None,
                "authoritative candidate output descriptor is invalid",
            )
            path = root / Path(*PurePosixPath(item["path"]).parts)
            try:
                relative = path.relative_to(candidate).as_posix()
            except ValueError as exc:
                raise ModelCorpusError(
                    "authoritative candidate output descriptor escaped output root"
                ) from exc
            _require(
                len(PurePosixPath(relative).parts) == 1
                and relative
                not in {
                    RECEIPT_NAME,
                    AUTHORITATIVE_COMMIT_PENDING_NAME,
                    AUTHORITATIVE_COMMIT_RECORD_NAME,
                },
                "authoritative candidate output descriptor is not a data leaf",
            )
            expected_files.add(relative)
            validation_paths.append(path)
            output_hold = validation_custody.enter_context(
                _HeldStablePayload(
                    root,
                    path,
                    expected_sha256=item["sha256"],
                    expected_size=item["size_bytes"],
                    label=f"authoritative candidate output {relative}",
                    maximum_size=AUTHORITATIVE_DESCRIPTOR_PAYLOAD_MAX_BYTES,
                    retain_payload=False,
                )
            )
            held_payloads.append(output_hold)
            _require(
                output_hold.size_bytes == item["size_bytes"],
                "authoritative candidate output size drifted",
            )
        _require(
            len(expected_files) == len(outputs) + 2,
            "authoritative candidate output paths are not unique",
        )

        commit_record_hold: _HeldStablePayload | None = None
        if held_commit_record is None:
            commit_record_hold = validation_custody.enter_context(
                _HeldStablePayload(
                    root,
                    candidate / AUTHORITATIVE_COMMIT_RECORD_NAME,
                    expected_sha256=str(record_descriptor["sha256"]),
                    expected_size=int(record_descriptor["size_bytes"]),
                    label="authoritative commit record",
                    maximum_size=AUTHORITATIVE_COMMIT_RECORD_MAX_BYTES,
                    retain_payload=True,
                )
            )
            held_payloads.append(commit_record_hold)
            observed_record = commit_record_hold.payload
            observed_descriptor = commit_record_hold.descriptor
        else:
            _require(
                held_commit_record.commit_record_path
                == candidate / AUTHORITATIVE_COMMIT_RECORD_NAME,
                "held commit record belongs to a different candidate",
            )
            held_commit_record.validate_committed_record()
            observed_record = held_commit_record.payload
            observed_descriptor = {
                "path": held_commit_record.commit_record_path.relative_to(
                    root
                ).as_posix(),
                "size_bytes": held_commit_record.size_bytes,
                "sha256": held_commit_record.sha256,
            }

        _validate_exact_tree(candidate, expected_files, set())
        _validate_private_publication_set(candidate, validation_paths)
        _require(
            observed_record == record_payload
            and observed_descriptor == record_descriptor,
            "authoritative commit record bytes drifted",
        )
        # The permanent record authenticates the full closed receipt core first;
        # the receipt's self hash is then checked as a separate envelope identity.
        _require(
            receipt["candidate_receipt_sha256"]
            == _candidate_self_sha(receipt),
            "authoritative candidate receipt self hash drifted",
        )

        for held_payload in held_payloads:
            held_payload.verify()
        if held_commit_record is not None:
            held_commit_record.validate_committed_record()
        _assert_plain_chain(root, candidate, label="authoritative candidate output")
        _require(
            _directory_identity(root.lstat()) == root_identity,
            "project root identity changed during committed validation",
        )
        _require(
            _directory_identity(parent.lstat()) == parent_identity,
            "candidate parent identity changed during committed validation",
        )
        _require(
            _directory_identity(candidate.lstat()) == candidate_identity,
            "candidate directory identity changed during committed validation",
        )
        return receipt


def _validate_resumed_candidate_invocation(
    receipt: Mapping[str, object],
    *,
    project_root: Path,
    materialization_receipt: Path,
    expected_materialization_receipt_size_bytes: int,
    expected_materialization_receipt_sha256: str,
    expected_materialization_receipt_self_sha256: str,
    expected_model_parity_manifest_sha256: str,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    expected_source_set_sha256: str,
) -> None:
    root = project_root.absolute()
    _require_frozen_materialization_receipt_pins(
        expected_size_bytes=expected_materialization_receipt_size_bytes,
        expected_file_sha256=expected_materialization_receipt_sha256,
        expected_self_sha256=expected_materialization_receipt_self_sha256,
    )
    _require(
        materialization_receipt.absolute()
        == root / Path(*PurePosixPath(MATERIALIZATION_RECEIPT_PATH).parts),
        "resume materialization receipt path differs from frozen authority",
    )
    _require(
        receipt["source_model_parity_manifest_sha256"]
        == _sha(
            expected_model_parity_manifest_sha256,
            label="resume model parity manifest pin",
        ),
        "resume model parity manifest pin differs from committed receipt",
    )
    tool_pins = receipt["tool_pins"]
    assert type(tool_pins) is dict
    expected_tools = {
        "ffmpeg": (
            ffmpeg.absolute(),
            expected_ffmpeg_sha256,
            expected_ffmpeg_version_sha256,
        ),
        "ffprobe": (
            ffprobe.absolute(),
            expected_ffprobe_sha256,
            expected_ffprobe_version_sha256,
        ),
    }
    for role, (path, file_sha256, version_sha256) in expected_tools.items():
        pin = tool_pins[role]
        assert type(pin) is dict
        _require(
            pin["path"] == str(path)
            and pin["sha256"]
            == _sha(file_sha256, label=f"resume {role} executable pin")
            and pin["version_output_sha256"]
            == _sha(version_sha256, label=f"resume {role} version pin"),
            f"resume {role} pins differ from committed receipt",
        )
    local_source_set = tool_pins["local_source_set"]
    assert type(local_source_set) is dict
    _require(
        local_source_set["canonical_aggregate_sha256"]
        == _sha(
            expected_source_set_sha256,
            label="resume local source set external aggregate pin",
        ),
        "resume local source set pin differs from committed receipt",
    )


def _materialize_model_corpus_impl(
    *,
    project_root: Path,
    materialization_receipt: Path,
    expected_materialization_receipt_size_bytes: int,
    expected_materialization_receipt_sha256: str,
    expected_materialization_receipt_self_sha256: str,
    model_parity_manifest: Path,
    expected_model_parity_manifest_sha256: str,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    expected_source_set_sha256: str,
    output_dir: Path,
    test_adapters: _TestAdapters | None,
) -> dict[str, object]:
    root = _validated_root(project_root)
    authoritative = test_adapters is None
    if authoritative and os.name != "nt":
        raise ModelCorpusError("authoritative model-corpus materialization requires Windows custody")
    parent, output = _validated_output(
        root,
        output_dir,
        allow_existing=authoritative,
    )
    if authoritative and os.path.lexists(output):
        resumed = _validate_committed_authoritative_candidate(
            project_root=root,
            output=output,
        )
        _validate_resumed_candidate_invocation(
            resumed,
            project_root=root,
            materialization_receipt=materialization_receipt,
            expected_materialization_receipt_size_bytes=(
                expected_materialization_receipt_size_bytes
            ),
            expected_materialization_receipt_sha256=(
                expected_materialization_receipt_sha256
            ),
            expected_materialization_receipt_self_sha256=(
                expected_materialization_receipt_self_sha256
            ),
            expected_model_parity_manifest_sha256=(
                expected_model_parity_manifest_sha256
            ),
            ffmpeg=ffmpeg,
            expected_ffmpeg_sha256=expected_ffmpeg_sha256,
            expected_ffmpeg_version_sha256=(
                expected_ffmpeg_version_sha256
            ),
            ffprobe=ffprobe,
            expected_ffprobe_sha256=expected_ffprobe_sha256,
            expected_ffprobe_version_sha256=(
                expected_ffprobe_version_sha256
            ),
            expected_source_set_sha256=expected_source_set_sha256,
        )
        return copy.deepcopy(resumed)
    root_snapshot = _directory_identity(root.lstat())
    parent_snapshot = _directory_identity(parent.lstat())

    if authoritative:
        _require_frozen_materialization_receipt_pins(
            expected_size_bytes=expected_materialization_receipt_size_bytes,
            expected_file_sha256=expected_materialization_receipt_sha256,
            expected_self_sha256=expected_materialization_receipt_self_sha256,
        )

    receipt, receipt_payload, media_descriptors = _validated_materialization_receipt(
        root=root,
        path=materialization_receipt.absolute(),
        expected_size=expected_materialization_receipt_size_bytes,
        expected_sha256=expected_materialization_receipt_sha256,
        expected_self_sha256=expected_materialization_receipt_self_sha256,
    )
    if authoritative:
        dataset_config_payload, dataset_config_source = (
            _validated_frozen_dataset_config(root=root, receipt=receipt)
        )
    else:
        dataset_config_payload = _canonical(
            {
                "schema_version": 1,
                "artifact_kind": "synthetic_test_adapter_dataset_config",
                "dataset_entries": receipt["dataset_entries"],
            }
        )
        dataset_config_source = {
            "path": "private_test_adapter",
            "size_bytes": len(dataset_config_payload),
            "sha256": _sha256(dataset_config_payload),
            "canonical_frozen_validator_applied": False,
        }
    _manifest, manifest_payload, parity = _validated_parity_manifest(
        root=root,
        path=model_parity_manifest,
        expected_sha256=expected_model_parity_manifest_sha256,
    )
    tool_custody = ExitStack()
    held_tools: list[_HeldPinnedFile] = []
    working = None
    working_custody = None
    parent_custody = None
    commit_media_custody = ExitStack()
    commit_media_holds: list[HeldMedia] = []
    output_file_custody = ExitStack()
    held_output_files: list[_HeldOutputFile] = []
    final_directory_custody: _WindowsDirectoryCustody | None = None
    parent_quarantine_guard: _WindowsDirectoryCustody | None = None
    candidate_quarantine_guard: _WindowsDirectoryCustody | None = None
    commit_pending: _AuthoritativeCommitPending | None = None
    required_close_phase_complete = False
    namespace_moved = False
    succeeded = False
    try:
        if authoritative:
            parent_custody = _open_windows_directory_custody(
                parent, label="model corpus staging parent", require_delete_access=False
            )
            working, working_custody = _create_windows_private_working_directory_with_custody(
                parent=parent_custody,
                prefix=".kpp-v2-model-corpus.",
                suffix=".candidate",
                label="model corpus candidate",
            )
        else:
            working = _create_private_working_directory(
                parent=parent,
                prefix=".kpp-v2-model-corpus.",
                suffix=".candidate",
            )
        assert working is not None
        subprocess_context = _build_subprocess_context(
            root=root, cwd=working, published_cwd=output
        )
        if authoritative:
            version_reader = lambda path: _read_tool_version(
                path, subprocess_context
            )
        else:
            version_reader = test_adapters.version_reader

        local_source_set, local_source_payloads = _held_local_source_set(
            root=root,
            require_canonical_runtime_paths=authoritative,
            expected_aggregate_sha256=expected_source_set_sha256,
            custody=tool_custody,
            held_files=held_tools,
        )
        materializer_component = next(
            item
            for item in local_source_set["components"]
            if item["component"] == "materializer"
        )
        shared_source_pin = {
            "path": materializer_component["runtime_path"],
            "size_bytes": materializer_component["size_bytes"],
            "sha256": materializer_component["sha256"],
            "source_set_canonical_aggregate_sha256": local_source_set[
                "canonical_aggregate_sha256"
            ],
            "source_bytes_externally_pinned_and_held": True,
            "executed_python_bytecode_attested": False,
            "launcher_execution_attested": False,
        }
        tool_pins = {
            "ffmpeg": _validated_tool(
                path=ffmpeg,
                role="ffmpeg",
                expected_sha256=expected_ffmpeg_sha256,
                expected_version_sha256=expected_ffmpeg_version_sha256,
                version_reader=version_reader,
                custody=tool_custody,
                held_tools=held_tools,
            ),
            "ffprobe": _validated_tool(
                path=ffprobe,
                role="ffprobe",
                expected_sha256=expected_ffprobe_sha256,
                expected_version_sha256=expected_ffprobe_version_sha256,
                version_reader=version_reader,
                custody=tool_custody,
                held_tools=held_tools,
            ),
            "materializer": {
                **shared_source_pin,
                "role": "model corpus materializer source",
            },
            "preprocessor": {
                **shared_source_pin,
                "role": "candidate preprocessing implementation source",
                "implementation_symbol": "_default_preprocess",
            },
            "local_source_set": local_source_set,
            "subprocess_context": copy.deepcopy(subprocess_context.descriptor),
        }
        tool_pins["ffprobe"]["canonical_argv_template_sha256"] = _sha256(
            _canonical([
                "FFPROBE", "-v", "error", "-select_streams", "v:0", "-count_frames",
                "-show_entries",
                "stream=index,codec_name,width,height,time_base,nb_read_frames:frame=stream_index,best_effort_timestamp",
                "-show_frames", "-of", "json", "SOURCE",
            ])
        )
        tool_pins["ffmpeg"]["canonical_argv_template_sha256"] = _sha256(
            _canonical([
                "FFMPEG", "-hide_banner", "-loglevel", "info", "-nostdin", "-i", "SOURCE",
                "-map", "0:v:0", "-an", "-sn", "-dn", "-vf",
                "select=EXACT_FRAME_INDEX_SET,showinfo,settb=expr=1/1000000000,showinfo",
                "-fps_mode", "passthrough", "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1",
            ])
        )
        outputs: list[dict[str, object]] = []
        outputs.append(
            _write_new(
                root,
                working / "source_materialization_receipt.json",
                receipt_payload,
                role="source materialization receipt snapshot",
                custody=output_file_custody,
                held_outputs=held_output_files,
                published_path=output / "source_materialization_receipt.json",
            )
        )
        outputs.append(
            _write_new(
                root,
                working / "source_model_parity_manifest.yaml",
                manifest_payload,
                role="source model parity manifest snapshot",
                custody=output_file_custody,
                held_outputs=held_output_files,
                published_path=output / "source_model_parity_manifest.yaml",
            )
        )
        dataset_config_snapshot = _write_new(
            root,
            working / "source_dataset_config.yaml",
            dataset_config_payload,
            role="source frozen dataset config snapshot",
            custody=output_file_custody,
            held_outputs=held_output_files,
            published_path=output / "source_dataset_config.yaml",
        )
        outputs.append(dataset_config_snapshot)
        source_snapshots: dict[str, dict[str, object]] = {}
        for component in local_source_set["components"]:
            component_name = str(component["component"])
            filename = f"source_code_{component_name}.py"
            snapshot = _write_new(
                root,
                working / filename,
                local_source_payloads[component_name],
                role=f"externally pinned {component_name} source snapshot",
                custody=output_file_custody,
                held_outputs=held_output_files,
                published_path=output / filename,
            )
            outputs.append(snapshot)
            source_snapshots[component_name] = snapshot
            component["source_snapshot"] = copy.deepcopy(snapshot)
        materializer_snapshot = source_snapshots["materializer"]
        for source_role in ("materializer", "preprocessor"):
            tool_pins[source_role]["source_snapshot"] = copy.deepcopy(
                materializer_snapshot
            )

        decoded: dict[tuple[str, str, int], DecodedFrame] = {}
        probes: dict[tuple[str, str], MediaProbe] = {}
        media_records: dict[tuple[str, str], HeldMedia] = {}
        if authoritative:
            probe_fn = lambda media, tool: _run_ffprobe(
                media, tool, subprocess_context
            )
            decode_fn = lambda media, indexes, probe, tool: _run_ffmpeg_decode(
                media, indexes, probe, tool, subprocess_context
            )
        else:
            probe_fn = test_adapters.probe
            decode_fn = test_adapters.decode
        preprocess_fn = _default_preprocess if authoritative else test_adapters.preprocess

        with ExitStack() as held:
            for key in sorted(MEDIA_PATHS):
                codec, role = key
                media_path = root / Path(*PurePosixPath(MEDIA_PATHS[key]).parts)
                media = held.enter_context(
                    HeldMedia(
                        root=root,
                        path=media_path,
                        codec=codec,
                        role=role,
                        descriptor=media_descriptors[key],
                    )
                )
                media_records[key] = media
                probes[key] = _validate_probe(
                    probe_fn(media, Path(tool_pins["ffprobe"]["path"])), media=media
                )
                media.verify()

            frame_counts: dict[str, int] = {}
            for role in SOURCE_ROLES:
                h264_count = probes[("h264", role)].frame_count
                h265_count = probes[("h265", role)].frame_count
                if h264_count != h265_count:
                    raise ScientificChoiceRequired(
                        f"{role} codec frame counts differ; scientific alignment requires PI approval"
                    )
                frame_counts[role] = h264_count
            plan = build_neutral_sample_plan(frame_counts)

            physical_indexes: dict[tuple[str, str], tuple[int, ...]] = {}
            for key in sorted(MEDIA_PATHS):
                codec, role = key
                indexes = tuple(sorted({
                    row.frame_index
                    for row in plan
                    if row.codec == codec and row.source_role == role
                }))
                _require(len(indexes) == 30, f"{codec}/{role} selection is not exact 30")
                physical_indexes[key] = indexes
                frames = decode_fn(
                    media_records[key], indexes, probes[key], Path(tool_pins["ffmpeg"]["path"])
                )
                validated = _validated_frames(
                    frames, indexes=indexes, probe=probes[key], media=media_records[key]
                )
                decoded.update({(codec, role, index): frame for index, frame in validated.items()})
                media_records[key].verify()

            tensors: dict[tuple[str, str, int], tuple[bytes, dict[str, object]]] = {}
            contract = dict(parity["preprocessing_contract"])
            contract_sha = str(parity["preprocessing_contract_sha256"])
            tensor_name = str(parity["tensor_name"])
            for key in sorted(decoded):
                tensor, descriptor = preprocess_fn(
                    decoded[key], contract, contract_sha, tensor_name
                )
                _require(type(tensor) is bytes and bool(tensor), "preprocessor returned no tensor bytes")
                descriptor = _mapping(descriptor, label="preprocessed tensor descriptor")
                _require(descriptor.get("sha256") == _sha256(tensor), "preprocessed tensor hash drifted")
                _require(descriptor.get("preprocessing_contract_sha256") == contract_sha, "preprocessed tensor contract binding drifted")
                _require(
                    descriptor.get("dtype") == "float32"
                    and descriptor.get("layout") == "NCHW"
                    and descriptor.get("shape") == [1, 3, 224, 224]
                    and descriptor.get("byte_length") == len(tensor)
                    and len(tensor) == 1 * 3 * 224 * 224 * 4,
                    "preprocessed tensor representation drifted",
                )
                tensors[key] = (tensor, descriptor)

            raw_bundles: dict[tuple[str, str], dict[str, object]] = {}
            tensor_bundles: dict[tuple[str, str], dict[str, object]] = {}
            raw_segments: dict[tuple[str, str, int], dict[str, int | str]] = {}
            tensor_segments: dict[tuple[str, str, int], dict[str, int | str]] = {}
            for key in sorted(MEDIA_PATHS):
                codec, role = key
                indexes = physical_indexes[key]
                raw_descriptor, raw_part = _write_bundle(
                    root=root,
                    path=working / f"raw_{codec}_{role}.rgb24.bin",
                    role=f"{codec}/{role} decoded RGB bundle",
                    chunks=[((codec, role, index), decoded[(codec, role, index)].rgb) for index in indexes],
                    custody=output_file_custody,
                    held_outputs=held_output_files,
                    published_path=output / f"raw_{codec}_{role}.rgb24.bin",
                )
                tensor_descriptor, tensor_part = _write_bundle(
                    root=root,
                    path=working / f"tensor_{codec}_{role}.f32.bin",
                    role=f"{codec}/{role} preprocessed tensor bundle",
                    chunks=[((codec, role, index), tensors[(codec, role, index)][0]) for index in indexes],
                    custody=output_file_custody,
                    held_outputs=held_output_files,
                    published_path=output / f"tensor_{codec}_{role}.f32.bin",
                )
                outputs.extend([raw_descriptor, tensor_descriptor])
                raw_bundles[key] = raw_descriptor
                tensor_bundles[key] = tensor_descriptor
                raw_segments.update(raw_part)
                tensor_segments.update(tensor_part)

            dataset_media = []
            for codec, role in sorted(MEDIA_PATHS):
                probe = probes[(codec, role)]
                descriptor = media_descriptors[(codec, role)]
                dataset_media.append({
                    "dataset_file_id": f"kpp-legacy-iss-v2-{codec}-{role}",
                    "codec": codec,
                    "source_role": role,
                    "file_index": FILE_INDEX[role],
                    "stream_index": probe.stream_index,
                    "path": MEDIA_PATHS[(codec, role)],
                    "size_bytes": descriptor["size_bytes"],
                    "sha256": descriptor["sha256"],
                    "width": probe.width,
                    "height": probe.height,
                    "time_base": probe.time_base,
                    "frame_count": probe.frame_count,
                })
            dataset_aggregate = _sha256(_canonical(dataset_media))
            source_receipt_descriptor = next(
                item for item in outputs if item["role"] == "source materialization receipt snapshot"
            )
            source_manifest_descriptor = next(
                item for item in outputs if item["role"] == "source model parity manifest snapshot"
            )
            dataset_document = {
                "schema_version": 1,
                "artifact_kind": DATASET_CANDIDATE_ARTIFACT_KIND,
                "generation_id": GENERATION_ID,
                "promotable": False,
                "publication_authorized": False,
                "evidence_accepted": False,
                "pi_approval_status": "required",
                "source_materialization_receipt": {
                    **source_receipt_descriptor,
                    "external_size_bytes": expected_materialization_receipt_size_bytes,
                    "external_sha256": expected_materialization_receipt_sha256,
                    "external_self_sha256": expected_materialization_receipt_self_sha256,
                },
                "source_model_parity_manifest": source_manifest_descriptor,
                "source_dataset_config": {
                    "source": dataset_config_source,
                    "snapshot": dataset_config_snapshot,
                    "canonical_frozen_validator_applied": authoritative,
                },
                "dataset_entries": {
                    name: copy.deepcopy(receipt["dataset_entries"][name])
                    for name in DATASET_NAMES.values()
                },
                "media": dataset_media,
                "dataset_aggregate_sha256": dataset_aggregate,
                "branch_source_mapping": parity["branch_bindings"],
                "sampling_rule": SAMPLING_RULE,
                "sampling_rule_sha256": _sha256(_canonical(SAMPLING_RULE)),
                "preprocessing_contract": contract,
                "preprocessing_contract_sha256": contract_sha,
                "tool_pins": tool_pins,
                "claims": CLAIMS,
            }
            dataset_payload = _canonical(dataset_document)
            dataset_descriptor = _write_new(
                root,
                working / "dataset_manifest.json",
                dataset_payload,
                role="candidate dataset manifest",
                custody=output_file_custody,
                held_outputs=held_output_files,
                published_path=output / "dataset_manifest.json",
            )
            outputs.append(dataset_descriptor)

            producer_contract = {
                "candidate_only": True,
                "sampling_rule_sha256": _sha256(_canonical(SAMPLING_RULE)),
                "preprocessing_contract_sha256": contract_sha,
                "materialization_receipt_sha256": expected_materialization_receipt_sha256,
                "materialization_receipt_self_sha256": expected_materialization_receipt_self_sha256,
                "model_parity_manifest_sha256": expected_model_parity_manifest_sha256,
                "tool_pins_sha256": _sha256(_canonical(tool_pins)),
            }
            for branch in BRANCHES:
                binding = parity["branch_bindings"][branch]
                for corpus_role in ("calibration", "evaluation"):
                    samples: list[dict[str, object]] = []
                    ordinal = 0
                    for row in plan:
                        if row.branch != branch or row.corpus_role != corpus_role:
                            continue
                        key = (row.codec, row.source_role, row.frame_index)
                        frame = decoded[key]
                        media = media_records[(row.codec, row.source_role)]
                        raw_bundle = raw_bundles[(row.codec, row.source_role)]
                        tensor_bundle = tensor_bundles[(row.codec, row.source_role)]
                        raw_segment = raw_segments[key]
                        tensor_segment = tensor_segments[key]
                        physical_payload = {
                            "dataset_aggregate_sha256": dataset_aggregate,
                            "dataset_file_sha256": media.sha256,
                            "codec": row.codec,
                            "source_role": row.source_role,
                            "stream_index": 0,
                            "frame_index": frame.frame_index,
                            "source_pts": frame.source_pts,
                            "source_time_base": frame.source_time_base,
                            "pts_ns": frame.pts_ns,
                            "decoded_frame_sha256": _sha256(frame.rgb),
                        }
                        sample_id = (
                            f"kpp-v2-candidate.{branch}.{corpus_role}."
                            f"{row.codec}.{ordinal:02d}"
                        )
                        tensor_payload, tensor_meta = tensors[key]
                        samples.append({
                            "sample_id": sample_id,
                            "physical_sample_sha256": _sha256(_canonical(physical_payload)),
                            "branch": branch,
                            "source_role": row.source_role,
                            "corpus_role": corpus_role,
                            "stratum_index": row.stratum_index,
                            "dataset_file_id": f"kpp-legacy-iss-v2-{row.codec}-{row.source_role}",
                            "dataset_file_sha256": media.sha256,
                            "codec": row.codec,
                            "file_index": FILE_INDEX[row.source_role],
                            "stream_index": 0,
                            "frame_index": frame.frame_index,
                            "source_pts": frame.source_pts,
                            "source_time_base": frame.source_time_base,
                            "pts_ns": frame.pts_ns,
                            "input_sha256": _sha256(frame.rgb),
                            "preprocessed_tensor_sha256": _sha256(tensor_payload),
                            "raw_frame": {
                                **{key: raw_bundle[key] for key in ("path", "size_bytes", "sha256")},
                                **raw_segment,
                                "encoding": "raw_bytes_v1",
                                "dtype": "uint8",
                                "shape": [frame.height, frame.width, 3],
                                "layout": "HWC",
                                "color_order": "RGB",
                            },
                            "preprocessed_tensor": {
                                **{key: tensor_bundle[key] for key in ("path", "size_bytes", "sha256")},
                                **tensor_segment,
                                "encoding": "raw_f32_le_c_contiguous_v1",
                                "dtype": tensor_meta.get("dtype"),
                                "shape": tensor_meta.get("shape"),
                                "layout": tensor_meta.get("layout"),
                                "preprocessing_contract_sha256": contract_sha,
                            },
                        })
                        ordinal += 1
                    _require(len(samples) == 30, f"{branch}/{corpus_role} sample count drifted")
                    document = {
                        "schema_version": 1,
                        "artifact_kind": CORPUS_CANDIDATE_ARTIFACT_KIND,
                        "branch": branch,
                        "workload_slot_id": binding["workload_slot_id"],
                        "source_ref": binding["source_ref"],
                        "source_role": binding["source_role"],
                        "semantic_claim": "topology_load_proxy_candidate_only",
                        "corpus_role": corpus_role,
                        "promotable": False,
                        "publication_authorized": False,
                        "evidence_accepted": False,
                        "pi_approval_status": "required",
                        "dataset_manifest": dataset_descriptor,
                        "dataset_aggregate_sha256": dataset_aggregate,
                        "producer_contract": producer_contract,
                        "sample_count": len(samples),
                        "samples": samples,
                        "samples_sha256": _sha256(_canonical(samples)),
                        "claims": CLAIMS,
                    }
                    payload = _canonical(document)
                    descriptor = _write_new(
                        root,
                        working / f"corpus_{branch}_{corpus_role}.json",
                        payload,
                        role=f"{branch}/{corpus_role} corpus candidate",
                        custody=output_file_custody,
                        held_outputs=held_output_files,
                        published_path=output / f"corpus_{branch}_{corpus_role}.json",
                    )
                    outputs.append(descriptor)

            for media in media_records.values():
                media.verify()

        # Reacquire every installed media object after decode.  A swap in the
        # close/reopen boundary fails its receipt hash; successful custody is
        # retained through the no-replace candidate commit.
        for key in sorted(MEDIA_PATHS):
            codec, role = key
            commit_media_holds.append(
                commit_media_custody.enter_context(
                    HeldMedia(
                        root=root,
                        path=root / Path(*PurePosixPath(MEDIA_PATHS[key]).parts),
                        codec=codec,
                        role=role,
                        descriptor=media_descriptors[key],
                    )
                )
            )

        outputs = sorted(outputs, key=lambda item: str(item["path"]))
        source_materialization_receipt_binding = {
            "path": MATERIALIZATION_RECEIPT_PATH,
            "size_bytes": expected_materialization_receipt_size_bytes,
            "sha256": expected_materialization_receipt_sha256,
            "materialization_receipt_sha256": (
                expected_materialization_receipt_self_sha256
            ),
        }
        sampling_rule_sha256 = _sha256(_canonical(SAMPLING_RULE))
        receipt_core: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": RECEIPT_ARTIFACT_KIND,
            "generation_id": GENERATION_ID,
            "status": "materialized_nonpromotable_candidate",
            "promotable": False,
            "publication_authorized": False,
            "evidence_accepted": False,
            "pi_approval_status": "required",
            "output_root": output.relative_to(root).as_posix(),
            "source_materialization_receipt": (
                source_materialization_receipt_binding
            ),
            "source_model_parity_manifest_sha256": expected_model_parity_manifest_sha256,
            "source_dataset_config": {
                "source": dataset_config_source,
                "snapshot": dataset_config_snapshot,
                "canonical_frozen_validator_applied": authoritative,
            },
            "dataset_aggregate_sha256": dataset_aggregate,
            "branch_source_mapping": parity["branch_bindings"],
            "sampling_rule": SAMPLING_RULE,
            "sampling_rule_sha256": sampling_rule_sha256,
            "tool_pins": tool_pins,
            "outputs": outputs,
            "claims": CLAIMS,
        }
        authoritative_commit_record: dict[str, object] | None = None
        if authoritative:
            commit_record_payload = _authoritative_commit_record_payload(
                canonical_output_root=output.relative_to(root).as_posix(),
                canonical_output_name=output.name,
                outputs_sha256=_sha256(_canonical(outputs)),
                sampling_rule_sha256=sampling_rule_sha256,
                source_set_canonical_aggregate_sha256=str(
                    local_source_set["canonical_aggregate_sha256"]
                ),
                source_materialization_receipt=(
                    source_materialization_receipt_binding
                ),
                source_model_parity_manifest_sha256=(
                    expected_model_parity_manifest_sha256
                ),
                candidate_receipt_core_sha256=(
                    _candidate_receipt_core_sha(receipt_core)
                ),
            )
            commit_pending = _AuthoritativeCommitPending(
                working_path=working / AUTHORITATIVE_COMMIT_PENDING_NAME,
                published_path=output / AUTHORITATIVE_COMMIT_PENDING_NAME,
                commit_record_path=(
                    output / AUTHORITATIVE_COMMIT_RECORD_NAME
                ),
                payload=commit_record_payload,
            )
            authoritative_commit_record = {
                "path": (
                    output / AUTHORITATIVE_COMMIT_RECORD_NAME
                ).relative_to(root).as_posix(),
                "size_bytes": len(commit_record_payload),
                "sha256": _sha256(commit_record_payload),
            }
        receipt_document = copy.deepcopy(receipt_core)
        receipt_document["authoritative_commit_record"] = (
            authoritative_commit_record
        )
        receipt_document["candidate_receipt_sha256"] = _candidate_self_sha(receipt_document)
        receipt_payload_out = _canonical(receipt_document)
        _write_new(
            root,
            working / RECEIPT_NAME,
            receipt_payload_out,
            role="candidate receipt",
            custody=output_file_custody,
            held_outputs=held_output_files,
            published_path=output / RECEIPT_NAME,
        )

        expected_files = {
            (root / Path(*PurePosixPath(str(item["path"])).parts))
            .relative_to(output)
            .as_posix()
            for item in outputs
        }
        expected_files.add(RECEIPT_NAME)
        precommit_expected_tree_files = set(expected_files)
        if authoritative:
            precommit_expected_tree_files.add(
                AUTHORITATIVE_COMMIT_PENDING_NAME
            )
        expected_dirs: set[str] = set()
        _require(
            {item.working_path.name for item in held_output_files} == expected_files
            and len(held_output_files) == len(expected_files),
            "held output leaf set is not exact",
        )
        _validate_exact_tree(
            working, precommit_expected_tree_files, expected_dirs
        )
        # Before publication descriptors point at final paths; validate their
        # bytes through corresponding candidate paths instead.
        candidate_paths = [
            working
            / (root / Path(*PurePosixPath(str(item["path"])).parts)).relative_to(output)
            for item in outputs
        ]
        candidate_validation_paths = [*candidate_paths, working / RECEIPT_NAME]
        if authoritative:
            candidate_validation_paths.append(
                working / AUTHORITATIVE_COMMIT_PENDING_NAME
            )
        _validate_private_publication_set(
            working, candidate_validation_paths
        )
        for held_output in held_output_files:
            held_output.verify(published=False)
        for held_tool in held_tools:
            held_tool.verify()
        for held_media in commit_media_holds:
            held_media.verify()
        _require(_directory_identity(root.lstat()) == root_snapshot, "project_root identity changed")
        _require(_directory_identity(parent.lstat()) == parent_snapshot, "staging parent identity changed")
        for held_output in held_output_files:
            held_output.prepare_for_parent_publish()
        # Windows refuses to rename a parent directory while any descendant
        # handle remains open, even with full sharing.  Retain the exact
        # FileId/nlink/size/hash snapshots, close this verified set together,
        # then bind every final leaf back to those snapshots before validation.
        for held_output in held_output_files:
            held_output.release_for_parent_publish()
        if authoritative:
            assert commit_pending is not None
            commit_pending.prepare_for_parent_publish()

        if authoritative:
            assert parent_custody is not None and working_custody is not None
            _validate_windows_direct_child_custody(
                parent=parent_custody, child=working_custody, expected_name=working.name
            )
            _windows_publish_directory_by_handle(
                source=working_custody, parent=parent_custody, target_name=output.name
            )
            published_directory_identity = working_custody.identity
        else:
            _atomic_publish_directory(working, output)
            published_directory_identity = None
        namespace_moved = True
        if authoritative:
            assert parent_custody is not None and working_custody is not None
            _require(
                working_custody.identity == published_directory_identity,
                "published candidate directory FileId drifted across publish",
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=output.name,
            )
        elif os.name == "nt":
            final_directory_custody = _open_windows_final_directory_identity_custody(
                output, label="published candidate directory identity"
            )
            if published_directory_identity is not None:
                _require(
                    final_directory_custody.identity
                    == published_directory_identity,
                    "published candidate directory FileId drifted across publish",
                )
                assert parent_custody is not None
                _validate_windows_direct_child_custody(
                    parent=parent_custody,
                    child=final_directory_custody,
                    expected_name=output.name,
                )
        if authoritative:
            assert commit_pending is not None
            commit_pending.acquire_after_publish()
        for held_output in held_output_files:
            held_output.acquire_final_custody()
        _validate_exact_tree(
            output, precommit_expected_tree_files, expected_dirs
        )
        published_paths = [
            root / Path(*PurePosixPath(str(item["path"])).parts)
            for item in outputs
        ]
        published_validation_paths = [*published_paths, output / RECEIPT_NAME]
        if authoritative:
            published_validation_paths.append(
                output / AUTHORITATIVE_COMMIT_PENDING_NAME
            )
        _validate_private_publication_set(
            output, published_validation_paths
        )
        for item in outputs:
            path = root / Path(*PurePosixPath(str(item["path"])).parts)
            payload = path.read_bytes()
            _require(len(payload) == item["size_bytes"] and _sha256(payload) == item["sha256"], "published candidate output drifted")
        final_receipt = (output / RECEIPT_NAME).read_bytes()
        _require(final_receipt == receipt_payload_out, "published candidate receipt drifted")
        for held_output in held_output_files:
            held_output.verify(published=True)
        for held_output in held_output_files:
            held_output.verify(published=True)
        for held_tool in held_tools:
            held_tool.verify()
        for held_media in commit_media_holds:
            held_media.verify()
        _require(_directory_identity(root.lstat()) == root_snapshot, "project_root changed after publication")
        if authoritative:
            assert parent_custody is not None and working_custody is not None
            _require(
                _windows_directory_information(
                    working_custody.handle,
                    label="published authoritative candidate final verification",
                )
                == working_custody.identity,
                "published authoritative candidate directory identity drifted",
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=output.name,
            )
        elif final_directory_custody is not None:
            _require(
                _windows_directory_information(
                    final_directory_custody.handle,
                    label="published candidate directory final verification",
                )
                == final_directory_custody.identity,
                "published candidate directory identity drifted",
            )
        # Terminal point-in-time enumeration.  Same-token future namespace
        # immutability is deliberately not claimed by this candidate.
        _validate_exact_tree(
            output, precommit_expected_tree_files, expected_dirs
        )
        result = copy.deepcopy(receipt_document)
        if authoritative:
            assert parent_custody is not None and working_custody is not None
            (
                parent_quarantine_guard,
                candidate_quarantine_guard,
            ) = _acquire_authoritative_quarantine_guards(
                parent_custody=parent_custody,
                candidate_custody=working_custody,
                expected_candidate_name=output.name,
            )
            original_working_custody = working_custody
            original_parent_custody = parent_custody
            working_custody = None
            parent_custody = None
            close_failure = _close_required_authoritative_resources(
                [
                    ("output_file_custody", output_file_custody.close),
                    ("commit_media_custody", commit_media_custody.close),
                    ("tool_custody", tool_custody.close),
                    (
                        "working_directory_custody",
                        original_working_custody.close,
                    ),
                    (
                        "parent_directory_custody",
                        original_parent_custody.close,
                    ),
                ]
            )
            required_close_phase_complete = True
            if close_failure is not None:
                raise close_failure
            assert commit_pending is not None
            # The final native no-replace move changes only the held guard's
            # name.  Its bytes already match the receipt-bound permanent
            # record, so filesystem validation resolves an uncertain Python
            # return without relying on this provisional in-memory state.
            succeeded = True
            assert parent_quarantine_guard is not None
            commit_pending.commit_success(
                parent_custody=parent_quarantine_guard,
                canonical_output_name=output.name,
            )
        else:
            succeeded = True
        if authoritative:
            assert (
                parent_quarantine_guard is not None
                and candidate_quarantine_guard is not None
            )
            _release_postcommit_authoritative_guards(
                [
                    ("candidate_guard", candidate_quarantine_guard),
                    ("parent_guard", parent_quarantine_guard),
                ]
            )
            candidate_quarantine_guard = None
            parent_quarantine_guard = None
        return result
    except BaseException as primary:
        quarantine_parent = parent_quarantine_guard or parent_custody
        quarantine_candidate = candidate_quarantine_guard or working_custody
        semantic_commit_observed = _resolve_authoritative_commit_failure(
            project_root=root,
            authoritative=authoritative,
            succeeded=succeeded,
            commit_pending=commit_pending,
            parent_custody=quarantine_parent,
            candidate_custody=quarantine_candidate,
            private_candidate_name=(
                working.name if working is not None else None
            ),
            canonical_output_name=output.name,
            output_file_custody=output_file_custody,
            primary=primary,
        )
        if succeeded and not semantic_commit_observed:
            succeeded = False
        if semantic_commit_observed:
            _emit_nonthrowing_operational_warning(
                "postcommit exception did not reverse the committed candidate: "
                f"{type(primary).__name__}: {_sanitized_error_text(primary)}"
            )
            if (
                candidate_quarantine_guard is not None
                and parent_quarantine_guard is not None
            ):
                _release_postcommit_authoritative_guards(
                    [
                        ("candidate_guard", candidate_quarantine_guard),
                        ("parent_guard", parent_quarantine_guard),
                    ]
                )
                candidate_quarantine_guard = None
                parent_quarantine_guard = None
            return result
        if isinstance(primary, ExtractionError):
            converted = ModelCorpusError(str(primary))
            notes = getattr(primary, "__notes__", ())
            if type(notes) is list:
                _attach_exception_diagnostics(converted, notes)
            raise converted from primary
        raise
    finally:
        active_primary = sys.exception()
        remaining_resources: list[tuple[str, Callable[[], None]]] = []
        if commit_pending is not None:
            if commit_pending.semantic_commit_observed():
                _finalize_commit_pending_sentinel(
                    commit_pending,
                    active_primary=active_primary,
                )
            else:
                remaining_resources.append(
                    (
                        "commit_pending_sentinel",
                        commit_pending.close_for_failure,
                    )
                )
        if not required_close_phase_complete:
            remaining_resources.extend(
                [
                    ("output_file_custody", output_file_custody.close),
                    ("commit_media_custody", commit_media_custody.close),
                    ("tool_custody", tool_custody.close),
                ]
            )
        if final_directory_custody is not None:
            remaining_resources.append(
                ("final_directory_custody", final_directory_custody.close)
            )
        if working_custody is not None:
            remaining_resources.append(
                ("working_directory_custody", working_custody.close)
            )
        if parent_custody is not None:
            remaining_resources.append(
                ("parent_directory_custody", parent_custody.close)
            )
        if candidate_quarantine_guard is not None:
            remaining_resources.append(
                ("candidate_quarantine_guard", candidate_quarantine_guard.close)
            )
        if parent_quarantine_guard is not None:
            remaining_resources.append(
                ("parent_quarantine_guard", parent_quarantine_guard.close)
            )
        cleanup_failure = _close_required_authoritative_resources(
            remaining_resources
        )
        if cleanup_failure is not None:
            if active_primary is None:
                raise cleanup_failure
            _attach_exception_diagnostics(
                active_primary,
                [
                    "cleanup after primary failure also failed: "
                    f"{type(cleanup_failure).__name__}: "
                    f"{_sanitized_error_text(cleanup_failure)}"
                ],
            )
        if working is not None and not namespace_moved and not authoritative:
            try:
                _cleanup_test_candidate(working)
            except BaseException as cleanup_exc:
                if active_primary is None:
                    raise
                _attach_exception_diagnostics(
                    active_primary,
                    [
                        "synthetic candidate cleanup after primary failure "
                        f"also failed: {type(cleanup_exc).__name__}: "
                        f"{_sanitized_error_text(cleanup_exc)}"
                    ],
                )


def materialize_model_corpus(
    *,
    project_root: Path,
    materialization_receipt: Path,
    expected_materialization_receipt_size_bytes: int,
    expected_materialization_receipt_sha256: str,
    expected_materialization_receipt_self_sha256: str,
    model_parity_manifest: Path,
    expected_model_parity_manifest_sha256: str,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    expected_source_set_sha256: str,
    output_dir: Path,
) -> dict[str, object]:
    return _materialize_model_corpus_impl(
        project_root=project_root,
        materialization_receipt=materialization_receipt,
        expected_materialization_receipt_size_bytes=expected_materialization_receipt_size_bytes,
        expected_materialization_receipt_sha256=expected_materialization_receipt_sha256,
        expected_materialization_receipt_self_sha256=expected_materialization_receipt_self_sha256,
        model_parity_manifest=model_parity_manifest,
        expected_model_parity_manifest_sha256=expected_model_parity_manifest_sha256,
        ffmpeg=ffmpeg,
        expected_ffmpeg_sha256=expected_ffmpeg_sha256,
        expected_ffmpeg_version_sha256=expected_ffmpeg_version_sha256,
        ffprobe=ffprobe,
        expected_ffprobe_sha256=expected_ffprobe_sha256,
        expected_ffprobe_version_sha256=expected_ffprobe_version_sha256,
        expected_source_set_sha256=expected_source_set_sha256,
        output_dir=output_dir,
        test_adapters=None,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--expected-materialization-receipt-size-bytes", type=int, required=True)
    parser.add_argument("--expected-materialization-receipt-sha256", required=True)
    parser.add_argument("--expected-materialization-receipt-self-sha256", required=True)
    parser.add_argument("--model-parity-manifest", type=Path, required=True)
    parser.add_argument("--expected-model-parity-manifest-sha256", required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--expected-ffmpeg-sha256", required=True)
    parser.add_argument("--expected-ffmpeg-version-sha256", required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--expected-ffprobe-sha256", required=True)
    parser.add_argument("--expected-ffprobe-version-sha256", required=True)
    parser.add_argument("--expected-source-set-sha256", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = materialize_model_corpus(
            project_root=args.project_root,
            materialization_receipt=args.materialization_receipt,
            expected_materialization_receipt_size_bytes=args.expected_materialization_receipt_size_bytes,
            expected_materialization_receipt_sha256=args.expected_materialization_receipt_sha256,
            expected_materialization_receipt_self_sha256=args.expected_materialization_receipt_self_sha256,
            model_parity_manifest=args.model_parity_manifest,
            expected_model_parity_manifest_sha256=args.expected_model_parity_manifest_sha256,
            ffmpeg=args.ffmpeg,
            expected_ffmpeg_sha256=args.expected_ffmpeg_sha256,
            expected_ffmpeg_version_sha256=args.expected_ffmpeg_version_sha256,
            ffprobe=args.ffprobe,
            expected_ffprobe_sha256=args.expected_ffprobe_sha256,
            expected_ffprobe_version_sha256=args.expected_ffprobe_version_sha256,
            expected_source_set_sha256=args.expected_source_set_sha256,
            output_dir=args.output_dir,
        )
    except ModelCorpusError as exc:
        print(f"ERROR: {_format_model_corpus_error(exc)}", file=sys.stderr)
        return 2
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BRANCHES",
    "BRANCH_SOURCE_ROLE",
    "CANDIDATE_RECEIPT_DOMAIN",
    "CORPUS_CANDIDATE_ARTIFACT_KIND",
    "DecodedFrame",
    "HeldMedia",
    "MATERIALIZATION_RECEIPT_DOMAIN",
    "MediaProbe",
    "ModelCorpusError",
    "RECEIPT_ARTIFACT_KIND",
    "RECEIPT_NAME",
    "SAMPLING_RULE",
    "ScientificChoiceRequired",
    "build_neutral_sample_plan",
    "materialize_model_corpus",
]
