#!/usr/bin/env python3
"""Extract deterministic AVI candidates from legacy ISS archive payloads."""

from __future__ import annotations

import argparse
import ctypes
import ctypes.wintypes as wintypes
import errno
import hashlib
import json
import ntpath
import os
import re
import secrets
import stat
import subprocess
import sys
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Callable, NamedTuple, Sequence


GENERATION_ID = "kpp_legacy_iss_v2"
RECEIPT_NAME = "kpp_iss_v2_extraction_receipt.json"
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
MARKER_SCAN_LIMIT = 16 * 1024 * 1024
MARKER_CHUNK_SIZE = 1024 * 1024

ROLE_RECIPES = {
    "underbody": {
        "demuxer": "mjpeg",
        "fps": 200,
        "output_name": "iss_v2_underbody.avi",
        "codec_name": "mjpeg",
        "width": 1700,
        "height": 236,
        "frame_count": 11882,
        "duration_ns": 59_410_000_000,
    },
    "front_gate": {
        "demuxer": "h264",
        "fps": 25,
        "output_name": "iss_v2_front_gate.avi",
        "codec_name": "h264",
        "width": 1920,
        "height": 1080,
        "frame_count": 1380,
        "duration_ns": 55_200_000_000,
    },
}


class ExtractionError(RuntimeError):
    pass


Runner = Callable[[tuple[str, ...]], None]
Prober = Callable[[Path], dict[str, object]]
VersionReader = Callable[[Path], bytes]


class _TestAdapters(NamedTuple):
    runner: Runner
    prober: Prober
    version_reader: VersionReader


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _UnicodeString(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.USHORT),
        ("MaximumLength", wintypes.USHORT),
        ("Buffer", wintypes.LPWSTR),
    ]


class _ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("Length", wintypes.ULONG),
        ("RootDirectory", wintypes.HANDLE),
        ("ObjectName", ctypes.POINTER(_UnicodeString)),
        ("Attributes", wintypes.ULONG),
        ("SecurityDescriptor", ctypes.c_void_p),
        ("SecurityQualityOfService", ctypes.c_void_p),
    ]


class _IoStatusBlock(ctypes.Structure):
    _fields_ = [
        ("StatusOrPointer", ctypes.c_void_p),
        ("Information", ctypes.c_size_t),
    ]


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [
        ("Sid", ctypes.c_void_p),
        ("Attributes", wintypes.DWORD),
    ]


class _TokenUser(ctypes.Structure):
    _fields_ = [("User", _SidAndAttributes)]


class _ByHandleFileInformation(ctypes.Structure):
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


class _FileRenameInfo(ctypes.Structure):
    _fields_ = [
        ("ReplaceIfExists", wintypes.BOOL),
        ("RootDirectory", wintypes.HANDLE),
        ("FileNameLength", wintypes.DWORD),
        ("FileName", wintypes.WCHAR * 1),
    ]


class _FileDispositionInfo(ctypes.Structure):
    _fields_ = [("DeleteFile", wintypes.BOOL)]


class _WindowsDirectoryCustody:
    def __init__(
        self,
        *,
        handle: int,
        identity: tuple[int, int],
        label: str,
    ) -> None:
        self._handle: int | None = handle
        self.identity = identity
        self.label = label

    @property
    def handle(self) -> int:
        if self._handle is None:
            raise ExtractionError(f"{self.label} custody handle is closed")
        return self._handle

    def close(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        if not close_handle(wintypes.HANDLE(handle)):
            raise ExtractionError(
                f"could not close {self.label} custody handle: "
                f"Win32 error {ctypes.get_last_error()}"
            )


def _require_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or SHA256_RE.fullmatch(value) is None:
        raise ExtractionError(f"{label} must be an exact lowercase SHA-256")
    return value


def _is_reparse_or_symlink(path: Path) -> bool:
    observed = path.lstat()
    if stat.S_ISLNK(observed.st_mode):
        return True
    attributes = getattr(observed, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return bool(attributes & reparse_flag)


def _require_regular_file(path: Path, *, label: str) -> os.stat_result:
    if not path.is_absolute():
        raise ExtractionError(f"{label} must be absolute")
    try:
        if _is_reparse_or_symlink(path):
            raise ExtractionError(f"{label} must not be a symlink or reparse point")
        observed = path.stat()
    except FileNotFoundError as exc:
        raise ExtractionError(f"{label} does not exist") from exc
    if not stat.S_ISREG(observed.st_mode):
        raise ExtractionError(f"{label} must be a regular file")
    if observed.st_size <= 0:
        raise ExtractionError(f"{label} must be non-empty")
    return observed


def _file_identity(observed: os.stat_result) -> tuple[int, int]:
    return int(observed.st_dev), int(observed.st_ino)


def _stable_sha256(path: Path, *, label: str) -> tuple[str, os.stat_result]:
    before = _require_regular_file(path, label=label)
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
        handle_state = os.fstat(source.fileno())
    after = path.stat()
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(handle_state, field) for field in fields):
        raise ExtractionError(f"{label} changed while it was hashed")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        raise ExtractionError(f"{label} changed after it was hashed")
    return digest.hexdigest(), after


def _read_tool_version(path: Path) -> bytes:
    completed = subprocess.run(
        [str(path), "-version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ExtractionError(
            f"{path.name} -version failed with exit code "
            f"{completed.returncode}: {diagnostic}"
        )
    if not completed.stdout:
        raise ExtractionError(f"{path.name} -version returned no stdout bytes")
    return bytes(completed.stdout)


def _validate_tool(
    *,
    role: str,
    path: Path,
    expected_sha256: str,
    expected_version_sha256: str,
    version_reader: VersionReader,
) -> tuple[Path, dict[str, object], tuple[int, int]]:
    tool_path = path.absolute()
    expected_binary = _require_sha256(
        expected_sha256, label=f"{role} executable SHA-256"
    )
    expected_version = _require_sha256(
        expected_version_sha256, label=f"{role} version output SHA-256"
    )
    observed_binary, observed = _stable_sha256(
        tool_path, label=f"{role} executable"
    )
    if observed_binary != expected_binary:
        raise ExtractionError(f"{role} executable SHA-256 does not match its external pin")
    try:
        version_bytes = version_reader(tool_path)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"{role} version query failed") from exc
    if type(version_bytes) is not bytes or not version_bytes:
        raise ExtractionError(f"{role} version query must return non-empty bytes")
    observed_version = hashlib.sha256(version_bytes).hexdigest()
    if observed_version != expected_version:
        raise ExtractionError(
            f"{role} version output SHA-256 does not match its external pin"
        )
    return (
        tool_path,
        {
            "role": role,
            "executable_sha256": observed_binary,
            "version_output_sha256": observed_version,
        },
        _file_identity(observed),
    )


def _first_pattern_offset(path: Path, patterns: Sequence[bytes]) -> int | None:
    maximum_pattern = max(len(pattern) for pattern in patterns)
    overlap = b""
    consumed = 0
    with path.open("rb") as source:
        while consumed < MARKER_SCAN_LIMIT:
            chunk = source.read(min(MARKER_CHUNK_SIZE, MARKER_SCAN_LIMIT - consumed))
            if not chunk:
                break
            haystack = overlap + chunk
            base = consumed - len(overlap)
            candidates = [haystack.find(pattern) for pattern in patterns]
            candidates = [candidate for candidate in candidates if candidate >= 0]
            if candidates:
                return base + min(candidates)
            consumed += len(chunk)
            overlap = haystack[-(maximum_pattern - 1) :]
    return None


def detect_payload_offset(path: Path, stream_kind: str) -> int:
    _require_regular_file(path, label=f"{stream_kind} archive")
    if stream_kind == "mjpeg":
        patterns = (b"\xff\xd8\xff",)
    elif stream_kind == "h264":
        patterns = (b"\x00\x00\x00\x01\x67", b"\x00\x00\x01\x67")
    else:
        raise ExtractionError(f"unknown stream kind: {stream_kind}")
    offset = _first_pattern_offset(path, patterns)
    if offset is None:
        raise ExtractionError(
            f"{stream_kind} payload marker was not found in the first {MARKER_SCAN_LIMIT} bytes"
        )
    return offset


def build_ffmpeg_command(
    *,
    source: Path,
    target: Path,
    role: str,
    payload_offset: int,
    ffmpeg: str,
) -> tuple[str, ...]:
    recipe = ROLE_RECIPES.get(role)
    if recipe is None:
        raise ExtractionError(f"unknown archive role: {role}")
    if type(payload_offset) is not int or payload_offset < 0:
        raise ExtractionError("payload offset must be a non-negative integer")
    return (
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-nostdin",
        "-r",
        str(recipe["fps"]),
        "-f",
        str(recipe["demuxer"]),
        "-skip_initial_bytes",
        str(payload_offset),
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-c:v",
        "copy",
        "-f",
        "avi",
        str(target),
    )


def _run(command: tuple[str, ...]) -> None:
    completed = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        diagnostic = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ExtractionError(
            f"ffmpeg extraction failed with exit code {completed.returncode}: {diagnostic}"
        )


def _probe(path: Path, *, ffprobe: Path) -> dict[str, object]:
    command = (
        str(ffprobe),
        "-v",
        "error",
        "-count_frames",
        "-show_entries",
        "stream=codec_name,width,height,r_frame_rate,avg_frame_rate,nb_frames,nb_read_frames,duration",
        "-of",
        "json",
        str(path),
    )
    completed = subprocess.run(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        shell=False,
    )
    if completed.returncode != 0:
        raise ExtractionError(
            "ffprobe validation failed: "
            + completed.stderr.decode("utf-8", errors="replace").strip()
        )
    try:
        value = json.loads(completed.stdout.decode("utf-8"))
        streams = value["streams"]
        if type(streams) is not list or len(streams) != 1 or type(streams[0]) is not dict:
            raise ValueError("expected exactly one stream")
        stream = streams[0]
        duration = Decimal(str(stream["duration"]))
        frame_count = int(stream.get("nb_read_frames") or stream["nb_frames"])
    except (KeyError, TypeError, ValueError, InvalidOperation, json.JSONDecodeError) as exc:
        raise ExtractionError("ffprobe returned an invalid stream description") from exc
    if duration <= 0 or frame_count <= 0:
        raise ExtractionError("ffprobe returned non-positive duration or frame count")
    return {
        "codec_name": str(stream["codec_name"]),
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "r_frame_rate": str(stream["r_frame_rate"]),
        "avg_frame_rate": str(stream["avg_frame_rate"]),
        "frame_count": frame_count,
        "duration_ns": int(duration * Decimal(1_000_000_000)),
    }


def _validated_project_root(value: Path) -> Path:
    root = value.absolute()
    if not root.is_dir() or _is_reparse_or_symlink(root):
        raise ExtractionError("project_root must be a plain existing directory")
    return root


def _validated_output_dir(project_root: Path, value: Path) -> Path:
    candidate = value.absolute()
    try:
        relative = candidate.relative_to(project_root)
    except ValueError as exc:
        raise ExtractionError("output_dir must stay inside project_root/staging") from exc
    if not relative.parts:
        raise ExtractionError("output_dir must stay inside project_root/staging")
    staging_component = relative.parts[0]
    component_matches = (
        staging_component.casefold() == "staging"
        if os.name == "nt"
        else staging_component == "staging"
    )
    if not component_matches:
        raise ExtractionError("output_dir must stay inside project_root/staging")
    if len(relative.parts) != 2:
        raise ExtractionError("output_dir must be a direct child directory of staging")
    current = project_root
    for component in relative.parts:
        current = current / component
        if current.exists() and _is_reparse_or_symlink(current):
            raise ExtractionError("output_dir path must not contain links or reparse points")
    return candidate


def _validate_probe(role: str, value: dict[str, object]) -> dict[str, object]:
    recipe = ROLE_RECIPES[role]
    expected_rate = f"{recipe['fps']}/1"
    expected = {
        "codec_name": recipe["codec_name"],
        "width": recipe["width"],
        "height": recipe["height"],
        "r_frame_rate": expected_rate,
        "avg_frame_rate": expected_rate,
    }
    for key, expected_value in expected.items():
        if value.get(key) != expected_value:
            raise ExtractionError(
                f"{role} output {key} mismatch: expected {expected_value!r}, "
                f"got {value.get(key)!r}"
            )
    frame_count = value.get("frame_count")
    duration_ns = value.get("duration_ns")
    if type(frame_count) is not int or frame_count <= 0:
        raise ExtractionError(f"{role} output frame_count must be a positive integer")
    if type(duration_ns) is not int or duration_ns <= 0:
        raise ExtractionError(f"{role} output duration_ns must be a positive integer")
    if frame_count != recipe["frame_count"]:
        raise ExtractionError(
            f"{role} output frame_count mismatch: expected "
            f"{recipe['frame_count']}, got {frame_count}"
        )
    if duration_ns != recipe["duration_ns"]:
        raise ExtractionError(
            f"{role} output duration_ns mismatch: expected "
            f"{recipe['duration_ns']}, got {duration_ns}"
        )
    return {
        "codec_name": str(value["codec_name"]),
        "width": int(value["width"]),
        "height": int(value["height"]),
        "r_frame_rate": str(value["r_frame_rate"]),
        "avg_frame_rate": str(value["avg_frame_rate"]),
        "frame_count": frame_count,
        "duration_ns": duration_ns,
    }


def _canonical_bytes(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _receipt_sha256(value: dict[str, object]) -> str:
    payload = _canonical_bytes(value)
    return hashlib.sha256(
        b"VAST:kpp-legacy-iss-extraction-receipt:v1\0" + payload
    ).hexdigest()


def _copy_pinned_snapshot(
    *,
    source: Path,
    target: Path,
    expected_sha256: str,
    label: str,
) -> tuple[dict[str, object], Path]:
    before = _require_regular_file(source, label=label)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream, target.open("xb") as output_stream:
            while True:
                chunk = input_stream.read(8 * 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                output_stream.write(chunk)
            output_stream.flush()
            os.fsync(output_stream.fileno())
            source_handle = os.fstat(input_stream.fileno())
        after = source.stat()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns")
    if any(getattr(before, field) != getattr(source_handle, field) for field in fields):
        target.unlink(missing_ok=True)
        raise ExtractionError(f"{label} changed while its private snapshot was copied")
    if any(getattr(before, field) != getattr(after, field) for field in fields):
        target.unlink(missing_ok=True)
        raise ExtractionError(f"{label} changed after its private snapshot was copied")
    observed_sha256 = digest.hexdigest()
    if observed_sha256 != expected_sha256:
        target.unlink(missing_ok=True)
        raise ExtractionError(f"{label} SHA-256 does not match its external pin")
    snapshot_sha256, snapshot_state = _stable_sha256(
        target, label=f"{label} private snapshot"
    )
    if (
        snapshot_sha256 != observed_sha256
        or int(snapshot_state.st_size) != int(before.st_size)
    ):
        target.unlink(missing_ok=True)
        raise ExtractionError(f"{label} private snapshot does not match its source")
    return (
        {
            "archive_logical_id": source.name,
            "size_bytes": int(before.st_size),
            "sha256": observed_sha256,
        },
        target,
    )


def _windows_current_user_sid() -> str:
    if os.name != "nt":
        raise ExtractionError("Windows token inspection is unavailable")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    get_current_process = kernel32.GetCurrentProcess
    get_current_process.argtypes = []
    get_current_process.restype = wintypes.HANDLE
    get_current_thread = kernel32.GetCurrentThread
    get_current_thread.argtypes = []
    get_current_thread.restype = wintypes.HANDLE
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    open_process_token = advapi32.OpenProcessToken
    open_process_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_process_token.restype = wintypes.BOOL
    open_thread_token = advapi32.OpenThreadToken
    open_thread_token.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.BOOL,
        ctypes.POINTER(wintypes.HANDLE),
    ]
    open_thread_token.restype = wintypes.BOOL
    get_token_information = advapi32.GetTokenInformation
    get_token_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
    ]
    get_token_information.restype = wintypes.BOOL
    convert_sid = advapi32.ConvertSidToStringSidW
    convert_sid.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)]
    convert_sid.restype = wintypes.BOOL

    token = wintypes.HANDLE()
    if not open_thread_token(get_current_thread(), 0x0008, True, ctypes.byref(token)):
        code = ctypes.get_last_error()
        if code != 1008:
            raise ExtractionError(
                "could not query the current Windows thread token: "
                f"Win32 error {code}"
            )
        if not open_process_token(get_current_process(), 0x0008, ctypes.byref(token)):
            raise ExtractionError(
                "could not query the current Windows process token: "
                f"Win32 error {ctypes.get_last_error()}"
            )
    try:
        required = wintypes.DWORD()
        get_token_information(token, 1, None, 0, ctypes.byref(required))
        if ctypes.get_last_error() != 122 or required.value < ctypes.sizeof(_TokenUser):
            raise ExtractionError("could not size the current Windows token user")
        buffer = ctypes.create_string_buffer(required.value)
        if not get_token_information(
            token,
            1,
            buffer,
            required,
            ctypes.byref(required),
        ):
            raise ExtractionError(
                "could not read the current Windows token user: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        token_user = ctypes.cast(buffer, ctypes.POINTER(_TokenUser)).contents
        sid_text = ctypes.c_wchar_p()
        if not convert_sid(token_user.User.Sid, ctypes.byref(sid_text)):
            raise ExtractionError(
                "could not render the current Windows user SID: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        try:
            if sid_text.value is None:
                raise ExtractionError("current Windows user SID is empty")
            return str(sid_text.value)
        finally:
            local_free(ctypes.cast(sid_text, ctypes.c_void_p))
    finally:
        close_handle(token)


def _windows_private_directory_sddl() -> str:
    user_sid = _windows_current_user_sid()
    return (
        f"O:{user_sid}D:P"
        f"(A;OICI;FA;;;{user_sid})"
        "(A;OICI;FA;;;SY)"
        "(A;OICI;FA;;;BA)"
    )


def _windows_private_directory_acl_is_exact(path: Path) -> bool:
    if os.name != "nt":
        return False
    if _is_reparse_or_symlink(path):
        return False
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_security = advapi32.GetNamedSecurityInfoW
    get_security.argtypes = [
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    get_security.restype = wintypes.DWORD
    convert_descriptor = advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW
    convert_descriptor.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_descriptor.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    result = get_security(
        str(path),
        1,
        0x00000005,
        None,
        None,
        None,
        None,
        ctypes.byref(descriptor),
    )
    if result != 0 or not descriptor.value:
        raise ExtractionError(
            f"could not read private directory ACL: Win32 error {result}"
        )
    rendered = ctypes.c_wchar_p()
    rendered_length = wintypes.DWORD()
    try:
        if not convert_descriptor(
            descriptor,
            1,
            0x00000005,
            ctypes.byref(rendered),
            ctypes.byref(rendered_length),
        ):
            raise ExtractionError(
                "could not render private directory ACL: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        try:
            return rendered.value == _windows_private_directory_sddl()
        finally:
            if rendered:
                local_free(ctypes.cast(rendered, ctypes.c_void_p))
    finally:
        local_free(descriptor)


def _windows_directory_information(handle: int, *, label: str) -> tuple[int, int]:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_information = kernel32.GetFileInformationByHandle
    get_information.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(_ByHandleFileInformation),
    ]
    get_information.restype = wintypes.BOOL
    information = _ByHandleFileInformation()
    if not get_information(wintypes.HANDLE(handle), ctypes.byref(information)):
        raise ExtractionError(
            f"could not inspect {label} custody handle: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    if not information.dwFileAttributes & 0x00000010:
        raise ExtractionError(f"{label} custody object must be a directory")
    if information.dwFileAttributes & 0x00000400:
        raise ExtractionError(f"{label} custody object must not be a reparse point")
    file_index = (int(information.nFileIndexHigh) << 32) | int(
        information.nFileIndexLow
    )
    return int(information.dwVolumeSerialNumber), file_index


def _windows_directory_final_path(handle: int, *, label: str) -> str:
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
        raise ExtractionError(
            f"could not size {label} final path: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    buffer = ctypes.create_unicode_buffer(required + 1)
    observed = get_final_path(
        wintypes.HANDLE(handle), buffer, len(buffer), 0
    )
    if observed == 0 or observed >= len(buffer):
        raise ExtractionError(
            f"could not read {label} final path: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    return str(buffer.value)


def _normalized_windows_handle_path(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    return ntpath.normcase(ntpath.normpath(value))


def _open_windows_directory_custody(
    path: Path,
    *,
    label: str,
    require_delete_access: bool,
) -> _WindowsDirectoryCustody:
    if os.name != "nt":
        raise ExtractionError("Windows directory custody is unavailable")
    candidate = path.absolute()
    if not candidate.is_dir() or _is_reparse_or_symlink(candidate):
        raise ExtractionError(f"{label} must be a plain existing directory")

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

    desired_access = 0x00000080 | 0x00000020 | 0x00000004
    if require_delete_access:
        desired_access |= 0x00010000
    handle = create_file(
        str(candidate),
        desired_access,
        0x00000001 | 0x00000002,
        None,
        3,
        0x02000000 | 0x00200000,
        None,
    )
    invalid_handle = ctypes.c_void_p(-1).value
    if handle in (None, invalid_handle):
        raise ExtractionError(
            f"could not acquire {label} custody: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    handle_value = int(handle)
    try:
        identity = _windows_directory_information(handle_value, label=label)
        _windows_directory_final_path(handle_value, label=label)

        verification = create_file(
            str(candidate),
            0x00000080,
            0x00000001 | 0x00000002 | 0x00000004,
            None,
            3,
            0x02000000 | 0x00200000,
            None,
        )
        if verification in (None, invalid_handle):
            raise ExtractionError(
                f"could not verify {label} path identity: "
                f"Win32 error {ctypes.get_last_error()}"
            )
        try:
            verification_identity = _windows_directory_information(
                int(verification), label=f"{label} path verification"
            )
        finally:
            close_handle(verification)
        if verification_identity != identity:
            raise ExtractionError(f"{label} path identity changed during custody")
        return _WindowsDirectoryCustody(
            handle=handle_value,
            identity=identity,
            label=label,
        )
    except Exception:
        close_handle(wintypes.HANDLE(handle_value))
        raise


def _require_single_windows_name(value: str, *, label: str) -> str:
    if (
        not value
        or value in (".", "..")
        or "\x00" in value
        or "/" in value
        or "\\" in value
        or ntpath.basename(value) != value
    ):
        raise ExtractionError(f"{label} must be one direct child name")
    return value


def _validate_windows_direct_child_custody(
    *,
    parent: _WindowsDirectoryCustody,
    child: _WindowsDirectoryCustody,
    expected_name: str,
) -> None:
    name = _require_single_windows_name(expected_name, label="directory name")
    if parent.identity[0] != child.identity[0]:
        raise ExtractionError("custodied directories must be on the same volume")
    parent_path = _normalized_windows_handle_path(
        _windows_directory_final_path(parent.handle, label=parent.label)
    )
    child_path = _normalized_windows_handle_path(
        _windows_directory_final_path(child.handle, label=child.label)
    )
    if ntpath.dirname(child_path) != parent_path:
        raise ExtractionError("working directory is not a direct child of staging")
    if ntpath.normcase(ntpath.basename(child_path)) != ntpath.normcase(name):
        raise ExtractionError("custodied directory name does not match its expected name")
    if _windows_directory_information(parent.handle, label=parent.label) != parent.identity:
        raise ExtractionError("staging parent custody identity changed")
    if _windows_directory_information(child.handle, label=child.label) != child.identity:
        raise ExtractionError("working directory custody identity changed")


def _windows_publish_directory_by_handle(
    *,
    source: _WindowsDirectoryCustody,
    parent: _WindowsDirectoryCustody,
    target_name: str,
) -> None:
    name = _require_single_windows_name(target_name, label="publication target")
    if source.identity[0] != parent.identity[0]:
        raise ExtractionError("publication source and parent must be on the same volume")
    if _windows_directory_information(parent.handle, label=parent.label) != parent.identity:
        raise ExtractionError("publication parent custody identity changed")
    parent_path = _windows_directory_final_path(parent.handle, label=parent.label)
    encoded_name = ntpath.join(parent_path, name).encode("utf-16-le")
    name_offset = _FileRenameInfo.FileName.offset
    buffer_size = max(
        ctypes.sizeof(_FileRenameInfo), name_offset + len(encoded_name) + 2
    )
    buffer = ctypes.create_string_buffer(buffer_size)
    information = ctypes.cast(
        buffer, ctypes.POINTER(_FileRenameInfo)
    ).contents
    information.ReplaceIfExists = False
    # SetFileInformationByHandle rejects a non-null RootDirectory with
    # ERROR_INVALID_NAME on supported desktop Windows.  The target namespace is
    # still bound to custody: its absolute parent is obtained from the held
    # staging handle, never from a caller-supplied publication path.
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
    if not set_information(
        wintypes.HANDLE(source.handle),
        3,
        buffer,
        buffer_size,
    ):
        code = ctypes.get_last_error()
        if code in (80, 183):
            raise ExtractionError(f"output already exists: {name}")
        raise ExtractionError(
            f"custodied Windows directory publication failed with Win32 error {code}"
        )


def _mark_windows_directory_delete_pending_by_handle(
    *,
    handle: int,
    label: str,
) -> None:
    """Mark the exact held empty directory for deletion when its handle closes."""

    if os.name != "nt":
        raise ExtractionError("Windows handle-based directory rollback is unavailable")
    information = _FileDispositionInfo(True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    set_information = kernel32.SetFileInformationByHandle
    set_information.argtypes = [
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    set_information.restype = wintypes.BOOL
    if not set_information(
        wintypes.HANDLE(handle),
        4,  # FileDispositionInfo
        ctypes.byref(information),
        ctypes.sizeof(information),
    ):
        raise ExtractionError(
            f"could not mark {label} delete-pending by handle: "
            f"Win32 error {ctypes.get_last_error()}"
        )


def _create_windows_private_working_directory_with_custody(
    *,
    parent: _WindowsDirectoryCustody,
    prefix: str,
    suffix: str,
    label: str,
) -> tuple[Path, _WindowsDirectoryCustody]:
    if os.name != "nt":
        raise ExtractionError("atomic Windows private directory creation is unavailable")
    if any(separator in prefix + suffix for separator in ("/", "\\")):
        raise ExtractionError("private extraction name fragments must be path-free")
    if _windows_directory_information(parent.handle, label=parent.label) != parent.identity:
        raise ExtractionError("staging parent custody identity changed")

    parent_path_text = _windows_directory_final_path(
        parent.handle,
        label=parent.label,
    )
    if parent_path_text.startswith("\\\\?\\UNC\\"):
        parent_path_text = "\\\\" + parent_path_text[8:]
    elif parent_path_text.startswith("\\\\?\\"):
        parent_path_text = parent_path_text[4:]
    parent_path = Path(parent_path_text)

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    convert_descriptor = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_descriptor.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_descriptor.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    nt_create_file = ntdll.NtCreateFile
    nt_create_file.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.DWORD,
        ctypes.POINTER(_ObjectAttributes),
        ctypes.POINTER(_IoStatusBlock),
        ctypes.c_void_p,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        wintypes.ULONG,
        ctypes.c_void_p,
        wintypes.ULONG,
    ]
    nt_create_file.restype = wintypes.LONG
    rtl_nt_status_to_dos_error = ntdll.RtlNtStatusToDosError
    rtl_nt_status_to_dos_error.argtypes = [wintypes.LONG]
    rtl_nt_status_to_dos_error.restype = wintypes.ULONG

    descriptor = ctypes.c_void_p()
    descriptor_size = wintypes.DWORD()
    if not convert_descriptor(
        _windows_private_directory_sddl(),
        1,
        ctypes.byref(descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise ExtractionError(
            "could not construct private directory ACL: "
            f"Win32 error {ctypes.get_last_error()}"
        )

    FILE_CREATE = 2
    FILE_CREATED = 2
    FILE_DIRECTORY_FILE = 0x00000001
    FILE_OPEN_REPARSE_POINT = 0x00200000
    FILE_ATTRIBUTE_NORMAL = 0x00000080
    FILE_SHARE_READ = 0x00000001
    FILE_SHARE_WRITE = 0x00000002
    OBJ_CASE_INSENSITIVE = 0x00000040
    STATUS_OBJECT_NAME_COLLISION = 0xC0000035
    desired_access = (
        0x00010000  # DELETE: required for later handle-based publication.
        | 0x00020000  # READ_CONTROL: permits custody-time security inspection.
        | 0x00000080  # FILE_READ_ATTRIBUTES.
        | 0x00000020  # FILE_TRAVERSE.
        | 0x00000004  # FILE_ADD_SUBDIRECTORY.
    )

    try:
        for _ in range(32):
            name = _require_single_windows_name(
                f"{prefix}{secrets.token_hex(16)}{suffix}",
                label="private working directory",
            )
            name_buffer = ctypes.create_unicode_buffer(name)
            name_bytes = name.encode("utf-16-le")
            unicode_name = _UnicodeString(
                len(name_bytes),
                ctypes.sizeof(name_buffer),
                ctypes.cast(name_buffer, wintypes.LPWSTR),
            )
            object_attributes = _ObjectAttributes()
            object_attributes.Length = ctypes.sizeof(_ObjectAttributes)
            object_attributes.RootDirectory = wintypes.HANDLE(parent.handle)
            object_attributes.ObjectName = ctypes.pointer(unicode_name)
            object_attributes.Attributes = OBJ_CASE_INSENSITIVE
            object_attributes.SecurityDescriptor = descriptor
            object_attributes.SecurityQualityOfService = None
            io_status = _IoStatusBlock()
            raw_handle = wintypes.HANDLE()
            status = int(
                nt_create_file(
                    ctypes.byref(raw_handle),
                    desired_access,
                    ctypes.byref(object_attributes),
                    ctypes.byref(io_status),
                    None,
                    FILE_ATTRIBUTE_NORMAL,
                    FILE_SHARE_READ | FILE_SHARE_WRITE,
                    FILE_CREATE,
                    FILE_DIRECTORY_FILE | FILE_OPEN_REPARSE_POINT,
                    None,
                    0,
                )
            )
            if status < 0:
                if status & 0xFFFFFFFF == STATUS_OBJECT_NAME_COLLISION:
                    continue
                code = int(rtl_nt_status_to_dos_error(status))
                raise ExtractionError(
                    "could not atomically create private extraction directory: "
                    f"NTSTATUS 0x{status & 0xFFFFFFFF:08x}, Win32 error {code}"
                )
            if raw_handle.value is None:
                raise ExtractionError(
                    "atomic private directory creation returned no custody handle"
                )

            handle_value = int(raw_handle.value)
            custody: _WindowsDirectoryCustody | None = None
            try:
                candidate = parent_path / name
                if int(io_status.Information) != FILE_CREATED:
                    raise ExtractionError(
                        "atomic private directory creation did not create a new object"
                    )
                identity = _windows_directory_information(handle_value, label=label)
                _windows_directory_final_path(handle_value, label=label)
                custody = _WindowsDirectoryCustody(
                    handle=handle_value,
                    identity=identity,
                    label=label,
                )
                _validate_windows_direct_child_custody(
                    parent=parent,
                    child=custody,
                    expected_name=name,
                )
                if not _windows_private_directory_acl_is_exact(candidate):
                    raise ExtractionError(
                        "private extraction directory ACL does not match its policy"
                    )
                return candidate, custody
            except BaseException as validation_exc:
                disposition_exc: BaseException | None = None
                close_exc: BaseException | None = None
                try:
                    _mark_windows_directory_delete_pending_by_handle(
                        handle=handle_value,
                        label=label,
                    )
                except BaseException as exc:
                    disposition_exc = exc
                try:
                    if custody is not None:
                        custody.close()
                    elif not close_handle(wintypes.HANDLE(handle_value)):
                        raise ExtractionError(
                            f"could not close failed {label} custody handle: "
                            f"Win32 error {ctypes.get_last_error()}"
                        )
                except BaseException as exc:
                    close_exc = exc

                if disposition_exc is not None or close_exc is not None:
                    if disposition_exc is not None:
                        message = (
                            f"{label} post-create validation failed; protected "
                            f"candidate {name} was retained because exact-handle "
                            "delete-pending failed"
                        )
                    else:
                        message = (
                            f"{label} post-create validation failed; exact-handle "
                            f"rollback for candidate {name} could not be confirmed"
                        )
                    rollback_error = ExtractionError(message)
                    rollback_error.add_note(
                        f"original validation failure: {validation_exc}"
                    )
                    if disposition_exc is not None:
                        rollback_error.add_note(
                            f"delete-pending failure: {disposition_exc}"
                        )
                    if close_exc is not None:
                        rollback_error.add_note(f"handle close failure: {close_exc}")
                    raise rollback_error from validation_exc
                raise
        raise ExtractionError("could not allocate a unique private extraction directory")
    finally:
        local_free(descriptor)


def _create_private_working_directory(
    *, parent: Path, prefix: str, suffix: str
) -> Path:
    if not parent.is_absolute() or not parent.is_dir():
        raise ExtractionError("private extraction parent must be an existing directory")
    if _is_reparse_or_symlink(parent):
        raise ExtractionError("private extraction parent must not be a reparse point")
    if any(separator in prefix + suffix for separator in ("/", "\\")):
        raise ExtractionError("private extraction name fragments must be path-free")
    if os.name != "nt":
        created = Path(
            tempfile.mkdtemp(prefix=prefix, suffix=suffix, dir=parent)
        )
        if _is_reparse_or_symlink(created):
            created.rmdir()
            raise ExtractionError("private extraction directory must not be a link")
        if stat.S_IMODE(created.stat().st_mode) != 0o700:
            created.rmdir()
            raise ExtractionError("private extraction directory must have mode 0700")
        return created

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    convert_descriptor = advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert_descriptor.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    convert_descriptor.restype = wintypes.BOOL
    create_directory = kernel32.CreateDirectoryW
    create_directory.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(_SecurityAttributes),
    ]
    create_directory.restype = wintypes.BOOL
    remove_directory = kernel32.RemoveDirectoryW
    remove_directory.argtypes = [wintypes.LPCWSTR]
    remove_directory.restype = wintypes.BOOL
    local_free = kernel32.LocalFree
    local_free.argtypes = [ctypes.c_void_p]
    local_free.restype = ctypes.c_void_p

    descriptor = ctypes.c_void_p()
    descriptor_size = wintypes.DWORD()
    if not convert_descriptor(
        _windows_private_directory_sddl(),
        1,
        ctypes.byref(descriptor),
        ctypes.byref(descriptor_size),
    ):
        raise ExtractionError(
            "could not construct private directory ACL: "
            f"Win32 error {ctypes.get_last_error()}"
        )
    attributes = _SecurityAttributes(
        ctypes.sizeof(_SecurityAttributes), descriptor, False
    )
    try:
        for _ in range(32):
            candidate = parent / f"{prefix}{secrets.token_hex(16)}{suffix}"
            if create_directory(str(candidate), ctypes.byref(attributes)):
                try:
                    if _is_reparse_or_symlink(candidate):
                        raise ExtractionError(
                            "private extraction directory must not be a reparse point"
                        )
                    if not _windows_private_directory_acl_is_exact(candidate):
                        raise ExtractionError(
                            "private extraction directory ACL does not match its policy"
                        )
                    return candidate
                except Exception:
                    remove_directory(str(candidate))
                    raise
            code = ctypes.get_last_error()
            if code not in (80, 183):
                raise ExtractionError(
                    "could not create private extraction directory: "
                    f"Win32 error {code}"
                )
        raise ExtractionError("could not allocate a unique private extraction directory")
    finally:
        local_free(descriptor)


def _atomic_publish_directory(source: Path, target: Path) -> None:
    if target.exists():
        raise ExtractionError(f"output already exists: {target.name}")
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        move_file_ex = kernel32.MoveFileExW
        move_file_ex.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        move_file_ex.restype = ctypes.c_int
        if not move_file_ex(str(source), str(target), 0):
            code = ctypes.get_last_error()
            if code in (80, 183):
                raise ExtractionError(f"output already exists: {target.name}")
            raise ExtractionError(
                f"atomic directory publication failed with Win32 error {code}"
            )
        return
    if sys.platform.startswith("linux"):
        libc = ctypes.CDLL(None, use_errno=True)
        renameat2 = getattr(libc, "renameat2", None)
        if renameat2 is None:
            raise ExtractionError("atomic no-replace publication is unavailable")
        renameat2.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        renameat2.restype = ctypes.c_int
        source_bytes = os.fsencode(source)
        target_bytes = os.fsencode(target)
        if renameat2(-100, source_bytes, -100, target_bytes, 1) != 0:
            code = ctypes.get_errno()
            if code == errno.EEXIST:
                raise ExtractionError(f"output already exists: {target.name}")
            raise ExtractionError(
                f"atomic directory publication failed with errno {code}"
            )
        return
    raise ExtractionError("atomic no-replace directory publication is unsupported")


def _validate_private_publication_set(working: Path, files: Sequence[Path]) -> None:
    for path in (working, *files):
        if _is_reparse_or_symlink(path):
            raise ExtractionError("publication set must not contain links or reparse points")
    if os.name == "nt":
        if not _windows_private_directory_acl_is_exact(working):
            raise ExtractionError(
                "private publication directory ACL changed before publication"
            )
        return
    if stat.S_IMODE(working.stat().st_mode) != 0o700:
        raise ExtractionError("private publication directory mode changed")


def _cleanup_private_tree(
    *,
    working: Path,
    source_snapshots: Sequence[Path],
    tool_snapshots: Sequence[Path],
    outputs: Sequence[Path],
    receipt: Path,
) -> None:
    receipt.unlink(missing_ok=True)
    for path in outputs:
        path.unlink(missing_ok=True)
    for path in source_snapshots:
        path.unlink(missing_ok=True)
    for path in tool_snapshots:
        path.unlink(missing_ok=True)
    source_dir = working / ".sources"
    try:
        source_dir.rmdir()
    except FileNotFoundError:
        pass
    tool_dir = working / ".tools"
    try:
        tool_dir.rmdir()
    except FileNotFoundError:
        pass
    try:
        working.rmdir()
    except FileNotFoundError:
        pass


def _extract_pair_impl(
    *,
    project_root: Path,
    underbody_archive: Path,
    front_archive: Path,
    output_dir: Path,
    expected_underbody_sha256: str,
    expected_front_sha256: str,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    test_adapters: _TestAdapters | None,
) -> dict[str, object]:
    if test_adapters is None:
        runner = _run
        prober: Prober | None = None
        version_reader = _read_tool_version
        authoritative = True
    else:
        runner = test_adapters.runner
        prober = test_adapters.prober
        version_reader = test_adapters.version_reader
        authoritative = False
    if authoritative and os.name != "nt":
        raise ExtractionError("authoritative extraction requires Windows")
    root = _validated_project_root(project_root)
    destination = _validated_output_dir(root, output_dir)
    if destination.exists():
        raise ExtractionError(f"output already exists: {destination.name}")
    source_paths = {
        "underbody": underbody_archive.absolute(),
        "front_gate": front_archive.absolute(),
    }
    expected_hashes = {
        "underbody": _require_sha256(
            expected_underbody_sha256, label="underbody archive SHA-256"
        ),
        "front_gate": _require_sha256(
            expected_front_sha256, label="front archive SHA-256"
        ),
    }
    tool_paths = {
        "ffmpeg": ffmpeg.absolute(),
        "ffprobe": ffprobe.absolute(),
    }
    expected_tool_hashes = {
        "ffmpeg": _require_sha256(
            expected_ffmpeg_sha256, label="ffmpeg executable SHA-256"
        ),
        "ffprobe": _require_sha256(
            expected_ffprobe_sha256, label="ffprobe executable SHA-256"
        ),
    }
    expected_tool_versions = {
        "ffmpeg": _require_sha256(
            expected_ffmpeg_version_sha256,
            label="ffmpeg version output SHA-256",
        ),
        "ffprobe": _require_sha256(
            expected_ffprobe_version_sha256,
            label="ffprobe version output SHA-256",
        ),
    }
    tool_identities = {
        role: _file_identity(_require_regular_file(path, label=f"{role} executable"))
        for role, path in tool_paths.items()
    }
    if tool_identities["ffmpeg"] == tool_identities["ffprobe"]:
        raise ExtractionError("ffmpeg and ffprobe must be physically distinct executables")

    source_descriptors: dict[str, dict[str, object]] = {}
    identities: set[tuple[int, int]] = set()
    for role in ("underbody", "front_gate"):
        observed = _require_regular_file(source_paths[role], label=f"{role} archive")
        identity = _file_identity(observed)
        if identity in identities:
            raise ExtractionError("underbody and front archives must be physically distinct")
        identities.add(identity)

    root_custody: _WindowsDirectoryCustody | None = None
    parent_custody: _WindowsDirectoryCustody | None = None
    working_custody: _WindowsDirectoryCustody | None = None
    if authoritative:
        root_custody = _open_windows_directory_custody(
            root,
            label="project root",
            require_delete_access=False,
        )
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination = _validated_output_dir(root, destination)
        if destination.exists():
            raise ExtractionError(f"output already exists: {destination.name}")
        if authoritative:
            if root_custody is None:
                raise ExtractionError("project root custody was not acquired")
            parent_custody = _open_windows_directory_custody(
                destination.parent,
                label="staging parent",
                require_delete_access=False,
            )
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=destination.parent.name,
            )
    except Exception:
        if parent_custody is not None:
            parent_custody.close()
            parent_custody = None
        if root_custody is not None:
            root_custody.close()
            root_custody = None
        raise
    try:
        if authoritative:
            if root_custody is None or parent_custody is None:
                raise ExtractionError("project root/staging custody was not acquired")
            working, working_custody = _create_windows_private_working_directory_with_custody(
                parent=parent_custody,
                prefix=f".{destination.name}.",
                suffix=".candidate",
                label="working directory",
            )
        else:
            working = _create_private_working_directory(
                parent=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".candidate",
            )
        if _is_reparse_or_symlink(working):
            raise ExtractionError(
                "private extraction directory must not be a reparse point"
            )
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise ExtractionError("private Windows custody was not acquired")
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=destination.parent.name,
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=working.name,
            )
            if not _windows_private_directory_acl_is_exact(working):
                raise ExtractionError(
                    "private extraction directory ACL changed before snapshots"
                )
        snapshot_dir = working / ".sources"
        snapshot_dir.mkdir()
        tool_snapshot_dir = working / ".tools"
        tool_snapshot_dir.mkdir()
    except Exception:
        # Authoritative failures deliberately retain the protected candidate.
        # Closing its no-delete-sharing handle is routed only after deciding
        # that no destructive path cleanup will occur.
        if not authoritative and "working" in locals():
            try:
                _cleanup_private_tree(
                    working=working,
                    source_snapshots=[],
                    tool_snapshots=[],
                    outputs=[],
                    receipt=working / RECEIPT_NAME,
                )
            except OSError:
                pass
        if working_custody is not None:
            working_custody.close()
            working_custody = None
        if parent_custody is not None:
            parent_custody.close()
            parent_custody = None
        if root_custody is not None:
            root_custody.close()
            root_custody = None
        raise
    snapshot_paths: dict[str, Path] = {}
    tool_snapshot_paths: dict[str, Path] = {}
    tool_descriptors: dict[str, dict[str, object]] = {}
    working_outputs = {
        role: working / str(ROLE_RECIPES[role]["output_name"])
        for role in ("underbody", "front_gate")
    }
    working_receipt = working / RECEIPT_NAME
    outputs: list[dict[str, object]] = []
    recipes: list[dict[str, object]] = []
    published = False
    try:
        for role in ("ffmpeg", "ffprobe"):
            snapshot_target = tool_snapshot_dir / f"{role}.exe"
            _copy_pinned_snapshot(
                source=tool_paths[role],
                target=snapshot_target,
                expected_sha256=expected_tool_hashes[role],
                label=f"{role} executable",
            )
            validated_path, descriptor, _ = _validate_tool(
                role=role,
                path=snapshot_target,
                expected_sha256=expected_tool_hashes[role],
                expected_version_sha256=expected_tool_versions[role],
                version_reader=version_reader,
            )
            tool_snapshot_paths[role] = validated_path
            tool_descriptors[role] = descriptor
        ffmpeg_path = tool_snapshot_paths["ffmpeg"]
        ffprobe_path = tool_snapshot_paths["ffprobe"]
        active_prober: Prober
        if prober is None:
            active_prober = lambda path: _probe(path, ffprobe=ffprobe_path)
        else:
            active_prober = prober

        for role in ("underbody", "front_gate"):
            snapshot_target = snapshot_dir / f"{role}.iss"
            descriptor, snapshot = _copy_pinned_snapshot(
                source=source_paths[role],
                target=snapshot_target,
                expected_sha256=expected_hashes[role],
                label=f"{role} archive",
            )
            descriptor["role"] = role
            descriptor["payload_offset"] = detect_payload_offset(
                snapshot, str(ROLE_RECIPES[role]["demuxer"])
            )
            source_descriptors[role] = descriptor
            snapshot_paths[role] = snapshot

        for role in ("underbody", "front_gate"):
            working_target = working_outputs[role]
            command = build_ffmpeg_command(
                source=snapshot_paths[role],
                target=working_target,
                role=role,
                payload_offset=int(source_descriptors[role]["payload_offset"]),
                ffmpeg=str(ffmpeg_path),
            )
            runner(command)
            output_sha256, output_state_before = _stable_sha256(
                working_target, label=f"{role} AVI candidate"
            )
            media = _validate_probe(role, active_prober(working_target))
            output_sha256_after, output_state_after = _stable_sha256(
                working_target, label=f"{role} AVI candidate after probe"
            )
            if (
                output_sha256_after != output_sha256
                or int(output_state_after.st_size) != int(output_state_before.st_size)
            ):
                raise ExtractionError(f"{role} AVI candidate changed during validation")
            relative_target = (
                destination / str(ROLE_RECIPES[role]["output_name"])
            ).relative_to(root).as_posix()
            outputs.append(
                {
                    "role": role,
                    "path": relative_target,
                    "size_bytes": int(output_state_after.st_size),
                    "sha256": output_sha256,
                    "media": media,
                }
            )
            recipes.append(
                {
                    "role": role,
                    "demuxer": ROLE_RECIPES[role]["demuxer"],
                    "source_fps": ROLE_RECIPES[role]["fps"],
                    "payload_offset": source_descriptors[role]["payload_offset"],
                    "codec_mode": "stream_copy",
                    "container": "avi",
                }
            )

        for role in ("underbody", "front_gate"):
            observed_hash, observed = _stable_sha256(
                snapshot_paths[role], label=f"{role} private snapshot post-extraction"
            )
            descriptor = source_descriptors[role]
            if (
                observed_hash != descriptor["sha256"]
                or int(observed.st_size) != descriptor["size_bytes"]
            ):
                raise ExtractionError(f"{role} archive changed during extraction")
        for role in ("ffmpeg", "ffprobe"):
            observed_hash, _ = _stable_sha256(
                tool_snapshot_paths[role],
                label=f"{role} private executable snapshot post-extraction",
            )
            if observed_hash != expected_tool_hashes[role]:
                raise ExtractionError(
                    f"{role} private executable snapshot changed during extraction"
                )

        receipt: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_extraction_receipt",
            "generation_id": GENERATION_ID,
            "status": (
                "headless_stream_copy_candidate"
                if authoritative
                else "test_adapter_candidate"
            ),
            "source_archives": [
                source_descriptors["underbody"], source_descriptors["front_gate"]
            ],
            "tools": [
                tool_descriptors["ffmpeg"],
                tool_descriptors["ffprobe"],
            ],
            "recipes": recipes,
            "outputs": outputs,
            "claims": {
                "source_bytes_externally_pinned": True,
                "source_private_snapshots_verified": True,
                "tool_bytes_and_version_outputs_externally_pinned": authoritative,
                "payload_offsets_detected": True,
                "video_payloads_stream_copied": authoritative,
                "output_set_directory_published_atomically": authoritative,
                "windows_project_root_staging_and_working_directory_handle_custody_validated": (
                    authoritative
                ),
                "source_timestamps_preserved": False,
                "archiveplayer_export_reproduced": False,
                "v1_dataset_identity_equivalent": False,
                "accuracy_ground_truth_validated": False,
                "publication_authorized": False,
            },
        }
        receipt["extraction_receipt_sha256"] = _receipt_sha256(receipt)
        encoded = _canonical_bytes(receipt)
        with working_receipt.open("xb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())

        for snapshot in snapshot_paths.values():
            snapshot.unlink()
        snapshot_dir.rmdir()
        for snapshot in tool_snapshot_paths.values():
            snapshot.unlink()
        tool_snapshot_dir.rmdir()
        expected_names = {
            RECEIPT_NAME,
            str(ROLE_RECIPES["underbody"]["output_name"]),
            str(ROLE_RECIPES["front_gate"]["output_name"]),
        }
        observed_names = {entry.name for entry in working.iterdir()}
        if observed_names != expected_names:
            raise ExtractionError("private output set has unexpected entries")
        _validate_private_publication_set(
            working,
            [*working_outputs.values(), working_receipt],
        )
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise ExtractionError("Windows publication custody is incomplete")
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=destination.parent.name,
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=working.name,
            )
            _windows_publish_directory_by_handle(
                source=working_custody,
                parent=parent_custody,
                target_name=destination.name,
            )
            published = True
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=destination.name,
            )
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=destination.parent.name,
            )
        else:
            _atomic_publish_directory(working, destination)
            published = True

        for output in outputs:
            final_path = root / str(output["path"])
            final_sha256, final_state = _stable_sha256(
                final_path, label=f"{output['role']} published AVI"
            )
            if (
                final_sha256 != output["sha256"]
                or int(final_state.st_size) != output["size_bytes"]
            ):
                raise ExtractionError(
                    f"{output['role']} published AVI does not match its receipt"
                )
        if (destination / RECEIPT_NAME).read_bytes() != encoded:
            raise ExtractionError("published receipt bytes changed")
        if authoritative:
            if (
                root_custody is None
                or parent_custody is None
                or working_custody is None
            ):
                raise ExtractionError("Windows post-publication custody is incomplete")
            _validate_windows_direct_child_custody(
                parent=root_custody,
                child=parent_custody,
                expected_name=destination.parent.name,
            )
            _validate_windows_direct_child_custody(
                parent=parent_custody,
                child=working_custody,
                expected_name=destination.name,
            )
        return receipt
    except Exception:
        # The authoritative candidate stays in place for bounded forensic
        # recovery.  Adapters own their path-only fixtures and may remove them.
        if not authoritative:
            cleanup_root = destination if published else working
            try:
                _cleanup_private_tree(
                    working=cleanup_root,
                    source_snapshots=[
                        cleanup_root / ".sources" / f"{role}.iss"
                        for role in ("underbody", "front_gate")
                    ],
                    tool_snapshots=[
                        cleanup_root / ".tools" / f"{role}.exe"
                        for role in ("ffmpeg", "ffprobe")
                    ],
                    outputs=[
                        cleanup_root / str(ROLE_RECIPES[role]["output_name"])
                        for role in ("underbody", "front_gate")
                    ],
                    receipt=cleanup_root / RECEIPT_NAME,
                )
            except OSError:
                pass
        raise
    finally:
        if working_custody is not None:
            working_custody.close()
        if parent_custody is not None:
            parent_custody.close()
        if root_custody is not None:
            root_custody.close()


def extract_pair(
    *,
    project_root: Path,
    underbody_archive: Path,
    front_archive: Path,
    output_dir: Path,
    expected_underbody_sha256: str,
    expected_front_sha256: str,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
) -> dict[str, object]:
    return _extract_pair_impl(
        project_root=project_root,
        underbody_archive=underbody_archive,
        front_archive=front_archive,
        output_dir=output_dir,
        expected_underbody_sha256=expected_underbody_sha256,
        expected_front_sha256=expected_front_sha256,
        ffmpeg=ffmpeg,
        expected_ffmpeg_sha256=expected_ffmpeg_sha256,
        expected_ffmpeg_version_sha256=expected_ffmpeg_version_sha256,
        ffprobe=ffprobe,
        expected_ffprobe_sha256=expected_ffprobe_sha256,
        expected_ffprobe_version_sha256=expected_ffprobe_version_sha256,
        test_adapters=None,
    )


def _extract_pair_with_test_adapters(
    *,
    project_root: Path,
    underbody_archive: Path,
    front_archive: Path,
    output_dir: Path,
    expected_underbody_sha256: str,
    expected_front_sha256: str,
    ffmpeg: Path,
    expected_ffmpeg_sha256: str,
    expected_ffmpeg_version_sha256: str,
    ffprobe: Path,
    expected_ffprobe_sha256: str,
    expected_ffprobe_version_sha256: str,
    runner: Runner,
    prober: Prober,
    version_reader: VersionReader,
) -> dict[str, object]:
    return _extract_pair_impl(
        project_root=project_root,
        underbody_archive=underbody_archive,
        front_archive=front_archive,
        output_dir=output_dir,
        expected_underbody_sha256=expected_underbody_sha256,
        expected_front_sha256=expected_front_sha256,
        ffmpeg=ffmpeg,
        expected_ffmpeg_sha256=expected_ffmpeg_sha256,
        expected_ffmpeg_version_sha256=expected_ffmpeg_version_sha256,
        ffprobe=ffprobe,
        expected_ffprobe_sha256=expected_ffprobe_sha256,
        expected_ffprobe_version_sha256=expected_ffprobe_version_sha256,
        test_adapters=_TestAdapters(runner, prober, version_reader),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Extract one underbody/front-gate AVI pair from externally pinned "
            "legacy ISS archives into one atomically published staging directory."
        )
    )
    parser.add_argument("--project-root", required=True, type=Path)
    parser.add_argument("--underbody-archive", required=True, type=Path)
    parser.add_argument("--front-archive", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--expected-underbody-sha256", required=True)
    parser.add_argument("--expected-front-sha256", required=True)
    parser.add_argument("--ffmpeg", required=True, type=Path)
    parser.add_argument("--expected-ffmpeg-sha256", required=True)
    parser.add_argument("--expected-ffmpeg-version-sha256", required=True)
    parser.add_argument("--ffprobe", required=True, type=Path)
    parser.add_argument("--expected-ffprobe-sha256", required=True)
    parser.add_argument("--expected-ffprobe-version-sha256", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    arguments = parser.parse_args(argv)
    try:
        receipt = extract_pair(
            project_root=arguments.project_root,
            underbody_archive=arguments.underbody_archive,
            front_archive=arguments.front_archive,
            output_dir=arguments.output_dir,
            expected_underbody_sha256=arguments.expected_underbody_sha256,
            expected_front_sha256=arguments.expected_front_sha256,
            ffmpeg=arguments.ffmpeg,
            expected_ffmpeg_sha256=arguments.expected_ffmpeg_sha256,
            expected_ffmpeg_version_sha256=(
                arguments.expected_ffmpeg_version_sha256
            ),
            ffprobe=arguments.ffprobe,
            expected_ffprobe_sha256=arguments.expected_ffprobe_sha256,
            expected_ffprobe_version_sha256=(
                arguments.expected_ffprobe_version_sha256
            ),
        )
    except ExtractionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write(_canonical_bytes(receipt).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
