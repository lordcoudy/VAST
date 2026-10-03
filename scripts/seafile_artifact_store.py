#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import http.client
import json
import mimetypes
import os
import re
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:
    import fcntl
except ImportError:  # pragma: no cover - canonical materialization runs in WSL.
    fcntl = None  # type: ignore[assignment]

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


class ArtifactStoreError(RuntimeError):
    pass


class ArtifactIntegrityError(ArtifactStoreError):
    pass


@dataclass(frozen=True)
class SeafileShareLinks:
    base_url: str
    upload_token: str = field(repr=False)
    read_token: str = field(repr=False)

    @classmethod
    def from_urls(cls, upload_url: str, read_url: str) -> "SeafileShareLinks":
        upload = urlsplit(upload_url.strip())
        read = urlsplit(read_url.strip())
        if upload.scheme != "https" or read.scheme != "https":
            raise ArtifactStoreError("Seafile links must use HTTPS")
        if (
            upload.username is not None
            or upload.password is not None
            or read.username is not None
            or read.password is not None
            or not upload.hostname
            or not read.hostname
            or upload.query
            or upload.fragment
            or read.query
            or read.fragment
        ):
            raise ArtifactStoreError("invalid Seafile capability link")
        upload_origin = (upload.scheme, upload.hostname.lower(), upload.port or 443)
        read_origin = (read.scheme, read.hostname.lower(), read.port or 443)
        if upload_origin != read_origin:
            raise ArtifactStoreError("Seafile upload and read links must use the same origin")
        upload_match = re.fullmatch(r"/u/d/([A-Za-z0-9]+)/?", upload.path)
        read_match = re.fullmatch(r"/d/([A-Za-z0-9]+)/?", read.path)
        if upload_match is None:
            raise ArtifactStoreError("invalid Seafile upload-link path")
        if read_match is None:
            raise ArtifactStoreError("invalid Seafile read-link path")
        return cls(
            base_url=f"https://{upload.netloc}",
            upload_token=upload_match.group(1),
            read_token=read_match.group(1),
        )

    @classmethod
    def from_file(cls, path: Path | str) -> "SeafileShareLinks":
        """Load one direct upload link and one direct read link without logging them."""
        source = Path(path)
        try:
            before = source.lstat()
            flags = os.O_RDONLY | getattr(os, "O_BINARY", 0)
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(source, flags)
        except OSError:
            raise ArtifactStoreError("Seafile link file is unavailable or unsafe") from None
        try:
            opened = os.fstat(descriptor)
            before_identity = (
                int(before.st_dev), int(before.st_ino), int(before.st_mode),
                int(before.st_nlink), int(before.st_size),
                int(before.st_mtime_ns), int(before.st_ctime_ns),
            )
            opened_identity = (
                int(opened.st_dev), int(opened.st_ino), int(opened.st_mode),
                int(opened.st_nlink), int(opened.st_size),
                int(opened.st_mtime_ns), int(opened.st_ctime_ns),
            )
            if (
                before_identity != opened_identity
                or not stat.S_ISREG(opened.st_mode)
                or int(opened.st_nlink) != 1
                or int(opened.st_size) > 64 * 1024
            ):
                raise ArtifactStoreError("Seafile link file is unavailable or unsafe")
            chunks: list[bytes] = []
            remaining = 64 * 1024 + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(8192, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            after = os.fstat(descriptor)
            after_identity = (
                int(after.st_dev), int(after.st_ino), int(after.st_mode),
                int(after.st_nlink), int(after.st_size),
                int(after.st_mtime_ns), int(after.st_ctime_ns),
            )
            if len(payload) > 64 * 1024 or after_identity != opened_identity:
                raise ArtifactStoreError("Seafile link file changed while being read")
        except ArtifactStoreError:
            raise
        except OSError:
            raise ArtifactStoreError("Seafile link file could not be read safely") from None
        finally:
            os.close(descriptor)
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            raise ArtifactStoreError("Seafile link file must be UTF-8") from None
        urls = re.findall(r"https://[^\s\x00]+", text)
        if len(urls) != 2:
            raise ArtifactStoreError(
                "Seafile link file must contain exactly one upload and one read URL"
            )
        candidates: list[SeafileShareLinks] = []
        for upload_url, read_url in ((urls[0], urls[1]), (urls[1], urls[0])):
            try:
                candidates.append(cls.from_urls(upload_url, read_url))
            except ArtifactStoreError:
                continue
        if len(candidates) != 1:
            raise ArtifactStoreError(
                "Seafile link file must contain one valid upload/read capability pair"
            )
        return candidates[0]

def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


_MATERIALIZATION_JOURNAL_ROOT = ".seafile-materialization-v1"
_MATERIALIZATION_INTENT = "intent.json"
_MATERIALIZATION_LOCK = ".lock"
_MATERIALIZATION_STAGE = "payload.stage"
_RENAME_NOREPLACE = 1
_RENAMEAT2: Any | None = None


def _canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _file_inode(metadata: os.stat_result) -> tuple[int, int]:
    return int(metadata.st_dev), int(metadata.st_ino)


def _regular_file_snapshot(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        int(metadata.st_dev),
        int(metadata.st_ino),
        int(metadata.st_mode),
        int(metadata.st_nlink),
        int(metadata.st_size),
        int(metadata.st_mtime_ns),
        int(metadata.st_ctime_ns),
        int(getattr(metadata, "st_uid", 0)),
        int(getattr(metadata, "st_gid", 0)),
        int(getattr(metadata, "st_file_attributes", 0)),
        int(getattr(metadata, "st_reparse_tag", 0)),
    )


def _directory_inode(metadata: os.stat_result) -> tuple[int, int]:
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or int(getattr(metadata, "st_file_attributes", 0)) & 0x400
    ):
        raise ArtifactIntegrityError("materialize directory custody is unsafe")
    return _file_inode(metadata)


def _open_directory_at(parent_fd: int, name: str, *, label: str) -> int:
    descriptor = -1
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        _directory_inode(named)
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_DIRECTORY", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        if _directory_inode(named) != _directory_inode(opened):
            raise ArtifactIntegrityError(f"{label} changed while opening")
        return descriptor
    except ArtifactStoreError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        raise ArtifactIntegrityError(f"{label} could not be opened safely") from None


def _verify_directory_at(
    parent_fd: int,
    name: str,
    descriptor: int,
    *,
    label: str,
) -> None:
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        opened = os.fstat(descriptor)
    except OSError:
        raise ArtifactIntegrityError(f"{label} changed during custody") from None
    if _directory_inode(named) != _directory_inode(opened):
        raise ArtifactIntegrityError(f"{label} changed during custody")


def _rename_noreplace_at(
    source_fd: int,
    source_name: str,
    destination_fd: int,
    destination_name: str,
) -> bool:
    """Try Linux renameat2(RENAME_NOREPLACE); False selects hard-link fallback."""

    global _RENAMEAT2
    if _RENAMEAT2 is False:
        return False
    if _RENAMEAT2 is None:
        library = ctypes.CDLL(None, use_errno=True)
        try:
            renameat2 = library.renameat2
        except AttributeError:
            _RENAMEAT2 = False
            return False
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        _RENAMEAT2 = renameat2
    ctypes.set_errno(0)
    result = int(
        _RENAMEAT2(
            source_fd,
            os.fsencode(source_name),
            destination_fd,
            os.fsencode(destination_name),
            _RENAME_NOREPLACE,
        )
    )
    if result == 0:
        return True
    error_number = ctypes.get_errno()
    if error_number == errno.EEXIST:
        raise FileExistsError(error_number, os.strerror(error_number))
    if error_number in {
        errno.EINVAL,
        errno.ENOSYS,
        errno.EXDEV,
        errno.EOPNOTSUPP,
        getattr(errno, "ENOTSUP", errno.EOPNOTSUPP),
    }:
        return False
    raise OSError(error_number, os.strerror(error_number))


def _hash_open_file(
    descriptor: int,
    *,
    chunk_size: int,
) -> tuple[int, str]:
    digest = hashlib.sha256()
    total = 0
    os.lseek(descriptor, 0, os.SEEK_SET)
    while True:
        chunk = os.read(descriptor, chunk_size)
        if not chunk:
            break
        digest.update(chunk)
        total += len(chunk)
    os.lseek(descriptor, 0, os.SEEK_SET)
    return total, digest.hexdigest()


def _open_verified_file_at(
    parent_fd: int,
    name: str,
    *,
    label: str,
    expected_size: int,
    expected_sha256: str,
    expected_inode: tuple[int, int] | None = None,
    allowed_links: frozenset[int] = frozenset({1}),
    chunk_size: int,
) -> tuple[int, tuple[int, int]]:
    descriptor = -1
    try:
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(named.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or int(named.st_nlink) not in allowed_links
            or int(named.st_size) != expected_size
        ):
            raise ArtifactIntegrityError(f"{label} physical identity is invalid")
        descriptor = os.open(
            name,
            os.O_RDONLY
            | int(getattr(os, "O_NONBLOCK", 0))
            | int(getattr(os, "O_NOFOLLOW", 0))
            | int(getattr(os, "O_CLOEXEC", 0)),
            dir_fd=parent_fd,
        )
        opened = os.fstat(descriptor)
        inode = _file_inode(opened)
        if _file_inode(named) != inode or (
            expected_inode is not None and inode != expected_inode
        ):
            raise ArtifactIntegrityError(f"{label} inode changed while opening")
        size, digest = _hash_open_file(descriptor, chunk_size=chunk_size)
        after_fd = os.fstat(descriptor)
        after_name = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (
            _file_inode(after_fd) != inode
            or _file_inode(after_name) != inode
            or int(after_fd.st_nlink) not in allowed_links
            or int(after_name.st_nlink) not in allowed_links
            or int(after_fd.st_size) != expected_size
            or int(after_name.st_size) != expected_size
            or size != expected_size
            or digest != expected_sha256
        ):
            raise ArtifactIntegrityError(f"{label} bytes or inode changed")
        os.fsync(descriptor)
        return descriptor, inode
    except ArtifactStoreError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError:
        if descriptor >= 0:
            os.close(descriptor)
        raise ArtifactIntegrityError(f"{label} could not be read safely") from None


def _materialization_key(
    *, remote_name: str, target_name: str, expected_sha256: str, expected_size: int
) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "expected_sha256": expected_sha256,
                "expected_size": expected_size,
                "remote_name": remote_name,
                "target_name": target_name,
            }
        )
    ).hexdigest()


class _SameOriginRedirectHandler(HTTPRedirectHandler):
    def __init__(self, expected_origin: tuple[str, str, int]) -> None:
        super().__init__()
        self.expected_origin = expected_origin

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Any:
        try:
            parsed = urlsplit(newurl)
            observed = (
                parsed.scheme,
                (parsed.hostname or "").lower(),
                parsed.port or 443,
            )
        except ValueError:
            raise ArtifactStoreError("Seafile redirect target is invalid") from None
        if (
            observed != self.expected_origin
            or parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ArtifactStoreError("Seafile redirect crossed the configured origin")
        return super().redirect_request(
            req, fp, code, msg, headers, newurl
        )


class SeafileArtifactStore:
    def __init__(
        self,
        links: SeafileShareLinks,
        *,
        timeout_s: float = 120.0,
        chunk_size: int = 8 * 1024 * 1024,
        opener: Any | None = None,
        retry_delays_s: Iterable[float] = (5.0, 15.0, 45.0, 120.0, 300.0),
        sleep_fn: Callable[[float], None] = time.sleep,
        materialize_physical_fault: Callable[[str, Path], None] | None = None,
        upload_physical_fault: Callable[[str, Path], None] | None = None,
    ) -> None:
        if timeout_s <= 0:
            raise ArtifactStoreError("timeout_s must be positive")
        if chunk_size <= 0:
            raise ArtifactStoreError("chunk_size must be positive")
        self.links = links
        self.timeout_s = float(timeout_s)
        self.chunk_size = int(chunk_size)
        self.opener = opener or build_opener(
            _SameOriginRedirectHandler(self._origin(links.base_url))
        )
        self.retry_delays_s = tuple(float(value) for value in retry_delays_s)
        if any(value < 0 for value in self.retry_delays_s):
            raise ArtifactStoreError("retry delays must be non-negative")
        self.sleep_fn = sleep_fn
        self.materialize_physical_fault = materialize_physical_fault
        self.upload_physical_fault = upload_physical_fault

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ArtifactStoreError("Seafile URL must use HTTPS")
        if parsed.username is not None or parsed.password is not None:
            raise ArtifactStoreError("Seafile URL must not contain user information")
        return (parsed.scheme, parsed.hostname.lower(), parsed.port or 443)

    def _validate_https_same_origin(self, url: str, *, label: str) -> None:
        try:
            observed = self._origin(url)
            expected = self._origin(self.links.base_url)
        except (ArtifactStoreError, ValueError):
            raise ArtifactStoreError(f"invalid {label}: HTTPS same-origin URL required") from None
        if observed != expected:
            raise ArtifactStoreError(f"invalid {label}: HTTPS same-origin URL required")

    @staticmethod
    def _validate_remote_name(remote_name: str) -> None:
        if (
            not remote_name
            or Path(remote_name).name != remote_name
            or "/" in remote_name
            or "\\" in remote_name
            or any(value in remote_name for value in ("\r", "\n", '"', "\x00"))
        ):
            raise ArtifactStoreError("remote_name must be a safe single file name")

    def _open_request(self, request: Request, *, label: str) -> Any:
        for attempt in range(len(self.retry_delays_s) + 1):
            try:
                response = self.opener.open(request, timeout=self.timeout_s)
                final_url = response.geturl() if hasattr(response, "geturl") else request.full_url
                try:
                    self._validate_https_same_origin(final_url, label="redirect target")
                except ArtifactStoreError:
                    try:
                        response.close()
                    finally:
                        raise ArtifactStoreError("Seafile redirect crossed the configured origin") from None
                status = int(getattr(response, "status", 200))
                if status in {408, 425, 429} or 500 <= status <= 599:
                    response.close()
                    if attempt == len(self.retry_delays_s):
                        raise ArtifactStoreError(
                            f"Seafile {label} failed after retryable HTTP responses"
                        )
                    self.sleep_fn(self.retry_delays_s[attempt])
                    continue
                return response
            except ArtifactStoreError:
                raise
            except HTTPError as error:
                if error.code not in {408, 425, 429} and not 500 <= error.code <= 599:
                    raise ArtifactStoreError(
                        f"Seafile {label} returned HTTP {error.code}"
                    ) from None
                if attempt == len(self.retry_delays_s):
                    break
                self.sleep_fn(self.retry_delays_s[attempt])
            except Exception:
                if attempt == len(self.retry_delays_s):
                    break
                self.sleep_fn(self.retry_delays_s[attempt])
        raise ArtifactStoreError(f"Seafile {label} failed after retries") from None

    def _json_get(self, path: str) -> Any:
        request = Request(
            self.links.base_url + path,
            headers={"Accept": "application/json", "User-Agent": "VAST-Benchmark/1"},
        )
        try:
            with self._open_request(request, label="JSON request") as response:
                payload = response.read()
                status = int(response.status)
        except ArtifactStoreError:
            raise
        except BaseException:
            raise ArtifactStoreError("Seafile JSON request failed") from None
        if status < 200 or status >= 300:
            raise ArtifactStoreError(f"Seafile JSON request returned HTTP {status}")
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            raise ArtifactStoreError("Seafile returned invalid JSON") from None

    def _upload_target(self) -> str:
        payload = self._json_get(
            f"/api/v2.1/upload-links/{quote(self.links.upload_token, safe='')}/upload/"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("upload_link"), str):
            raise ArtifactStoreError("Seafile upload-link response is missing upload_link")
        target = str(payload["upload_link"])
        self._validate_https_same_origin(target, label="upload target")
        parsed = urlsplit(target)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["ret-json"] = "1"
        return urlunsplit(
            (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
        )

    @staticmethod
    def _multipart_field(boundary: str, name: str, value: str) -> bytes:
        return (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"{name}\"\r\n\r\n"
            f"{value}\r\n"
        ).encode("utf-8")

    def _post_file(
        self,
        target: str,
        local_path: Path,
        remote_name: str,
        *,
        source_fd: int | None = None,
        source_size: int | None = None,
    ) -> Any:
        self._validate_remote_name(remote_name)
        self._validate_https_same_origin(target, label="upload target")

        boundary = "vast-" + uuid.uuid4().hex
        fields = (
            self._multipart_field(boundary, "parent_dir", "/")
            + self._multipart_field(boundary, "relative_path", "")
        )
        media_type = mimetypes.guess_type(remote_name)[0] or "application/octet-stream"
        file_header = (
            f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"{remote_name}\"\r\n"
            f"Content-Type: {media_type}\r\n\r\n"
        ).encode("utf-8")
        ending = f"\r\n--{boundary}--\r\n".encode("ascii")
        if source_fd is None:
            source_size = local_path.stat().st_size
        if type(source_size) is not int or source_size < 0:
            raise ArtifactStoreError("upload source size is invalid")
        content_length = len(fields) + len(file_header) + source_size + len(ending)

        parsed = urlsplit(target)
        connection = http.client.HTTPSConnection(
            parsed.hostname, parsed.port, timeout=self.timeout_s
        )
        request_target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
        try:
            connection.putrequest("POST", request_target)
            connection.putheader("Content-Type", f"multipart/form-data; boundary={boundary}")
            connection.putheader("Content-Length", str(content_length))
            connection.putheader("Accept", "application/json")
            connection.putheader("User-Agent", "VAST-Benchmark/1")
            connection.endheaders()
            connection.send(fields)
            connection.send(file_header)
            sent = 0
            if source_fd is None:
                with local_path.open("rb") as source:
                    for chunk in iter(lambda: source.read(self.chunk_size), b""):
                        connection.send(chunk)
                        sent += len(chunk)
            else:
                upload_fd = os.dup(source_fd)
                try:
                    os.lseek(upload_fd, 0, os.SEEK_SET)
                    while True:
                        chunk = os.read(upload_fd, self.chunk_size)
                        if not chunk:
                            break
                        connection.send(chunk)
                        sent += len(chunk)
                finally:
                    os.close(upload_fd)
            if sent != source_size:
                raise ArtifactIntegrityError(
                    "held upload source size changed during streaming"
                )
            connection.send(ending)
            response = connection.getresponse()
            status = int(response.status)
            payload = response.read()
        except BaseException:
            raise ArtifactStoreError("Seafile file upload failed") from None
        finally:
            connection.close()

        if status < 200 or status >= 300:
            raise ArtifactStoreError(f"Seafile file upload returned HTTP {status}")
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            raise ArtifactStoreError("Seafile upload returned invalid JSON") from None

    def list_remote_files(self) -> dict[str, dict[str, Any]]:
        payload = self._json_get(
            f"/api/v2.1/share-links/{quote(self.links.read_token, safe='')}/dirents/?"
            + urlencode({"path": "/"})
        )
        rows = payload.get("dirent_list") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ArtifactStoreError("Seafile dirents response is invalid")
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict) or bool(row.get("is_dir")):
                continue
            name = str(row.get("file_name", ""))
            if name:
                result[name] = dict(row)
        return result

    def preflight(
        self, *, live_upload_readback: bool = False,
    ) -> dict[str, Any]:
        files = self.list_remote_files()
        # Resolving the upload endpoint is a GET-only permission check; the
        # capability URL itself is deliberately never returned or logged.
        self._upload_target()
        upload_capability = "verified_get_only"
        if live_upload_readback:
            remote_name = (
                "vast-seafile-live-preflight-v1-"
                f"{uuid.uuid4().hex}.bin"
            )
            with tempfile.TemporaryDirectory(prefix="vast-seafile-live-preflight-") as tmp:
                payload = Path(tmp) / remote_name
                payload.write_bytes(b"VAST Seafile live upload/readback preflight v1\n")
                self.upload_and_verify(payload, remote_name=remote_name)
            files = self.list_remote_files()
            upload_capability = "verified_live_upload_readback"
        total_size = 0
        for row in files.values():
            try:
                size = int(row.get("size"))
            except (TypeError, ValueError):
                raise ArtifactStoreError("Seafile dirents contains an invalid size") from None
            if size < 0:
                raise ArtifactStoreError("Seafile dirents contains a negative size")
            total_size += size
        return {
            "schema_version": 1,
            "artifact_kind": "vast_seafile_preflight",
            "status": "ready",
            "transport": "https",
            "origin": self.links.base_url,
            "read_capability": "verified",
            "upload_capability": upload_capability,
            "remote_file_count": len(files),
            "remote_size_bytes": total_size,
            "quota_visibility": "not_exposed_by_share_link",
        }

    def verify_remote(
        self,
        remote_name: str,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, Any]:
        self._validate_remote_name(remote_name)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ArtifactIntegrityError("expected SHA-256 must be 64 lowercase hex characters")
        remote = self.list_remote_files().get(remote_name)
        if remote is None:
            raise ArtifactIntegrityError(f"remote artifact is missing: {remote_name}")
        try:
            listed_size = int(remote.get("size"))
        except (TypeError, ValueError):
            raise ArtifactIntegrityError("remote artifact size is invalid") from None
        if listed_size != int(expected_size):
            raise ArtifactIntegrityError(
                f"remote size mismatch for {remote_name}: {listed_size} != {expected_size}"
            )

        path = f"/{remote_name}"
        download_url = (
            f"{self.links.base_url}/d/{quote(self.links.read_token, safe='')}/files/?"
            + urlencode({"p": path, "dl": "1"})
        )
        request = Request(
            download_url,
            headers={"Accept": "application/octet-stream", "User-Agent": "VAST-Benchmark/1"},
        )
        digest = hashlib.sha256()
        downloaded = 0
        try:
            with self._open_request(request, label="remote readback") as response:
                for chunk in iter(lambda: response.read(self.chunk_size), b""):
                    digest.update(chunk)
                    downloaded += len(chunk)
        except ArtifactStoreError:
            raise
        except (OSError, http.client.IncompleteRead):
            raise ArtifactStoreError("remote readback transport failed") from None
        except BaseException:
            raise ArtifactIntegrityError("remote readback failed") from None

        observed_sha256 = digest.hexdigest()
        if downloaded != int(expected_size):
            raise ArtifactIntegrityError(
                f"readback size mismatch for {remote_name}: {downloaded} != {expected_size}"
            )
        if observed_sha256 != expected_sha256:
            raise ArtifactIntegrityError(
                f"readback SHA-256 mismatch for {remote_name}: "
                f"{observed_sha256} != {expected_sha256}"
            )
        return {
            "status": "verified",
            "remote_name": remote_name,
            "size_bytes": downloaded,
            "sha256": observed_sha256,
        }

    def upload_and_verify(
        self,
        local_path: Path,
        *,
        remote_name: str | None = None,
    ) -> dict[str, Any]:
        lexical = Path(os.path.abspath(os.fspath(local_path)))
        parent = lexical.parent
        try:
            resolved_parent = parent.resolve(strict=True)
            parent_before = parent.lstat()
        except OSError:
            raise ArtifactStoreError("local upload source is unavailable") from None
        if resolved_parent != parent or lexical != resolved_parent / lexical.name:
            raise ArtifactStoreError("local upload source parent is redirected")
        _directory_inode(parent_before)
        name = remote_name or lexical.name
        self._validate_remote_name(name)
        parent_fd = source_fd = -1
        try:
            parent_fd = os.open(
                resolved_parent,
                os.O_RDONLY
                | int(getattr(os, "O_DIRECTORY", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
            )
            if _directory_inode(os.fstat(parent_fd)) != _directory_inode(parent_before):
                raise ArtifactStoreError(
                    "local upload source parent changed while opening"
                )
            named = os.stat(
                lexical.name, dir_fd=parent_fd, follow_symlinks=False
            )
            if (
                not stat.S_ISREG(named.st_mode)
                or stat.S_ISLNK(named.st_mode)
                or int(named.st_nlink) != 1
            ):
                raise ArtifactStoreError(
                    "local upload source is not one physical file"
                )
            source_fd = os.open(
                lexical.name,
                os.O_RDONLY
                | int(getattr(os, "O_NONBLOCK", 0))
                | int(getattr(os, "O_NOFOLLOW", 0))
                | int(getattr(os, "O_CLOEXEC", 0)),
                dir_fd=parent_fd,
            )
            opened = os.fstat(source_fd)
            source_snapshot = _regular_file_snapshot(opened)
            if _regular_file_snapshot(named) != source_snapshot:
                raise ArtifactStoreError(
                    "local upload source changed while opening"
                )
            size, digest = _hash_open_file(
                source_fd, chunk_size=self.chunk_size
            )
            if size != int(opened.st_size) or (
                _regular_file_snapshot(os.fstat(source_fd)) != source_snapshot
            ):
                raise ArtifactStoreError(
                    "local upload source changed while hashing"
                )
            if self.upload_physical_fault is not None:
                self.upload_physical_fault("post_digest_pre_upload", lexical)
            named_before_upload = os.stat(
                lexical.name, dir_fd=parent_fd, follow_symlinks=False
            )
            held_size, held_digest = _hash_open_file(
                source_fd, chunk_size=self.chunk_size
            )
            if (
                _regular_file_snapshot(named_before_upload) != source_snapshot
                or _regular_file_snapshot(os.fstat(source_fd)) != source_snapshot
                or held_size != size
                or held_digest != digest
            ):
                raise ArtifactStoreError(
                    "local upload source was rebound or mutated before upload"
                )

            if name in self.list_remote_files():
                verified = self.verify_remote(
                    name,
                    expected_sha256=digest,
                    expected_size=size,
                )
                return {**verified, "status": "already_present_and_verified"}

            self._post_file(
                self._upload_target(),
                lexical,
                name,
                source_fd=source_fd,
                source_size=size,
            )
            verified = self.verify_remote(
                name,
                expected_sha256=digest,
                expected_size=size,
            )
            return {**verified, "status": "uploaded_and_verified"}
        except ArtifactStoreError:
            raise
        except OSError:
            raise ArtifactStoreError(
                "local upload source physical custody failed"
            ) from None
        finally:
            if source_fd >= 0:
                os.close(source_fd)
            if parent_fd >= 0:
                os.close(parent_fd)

    def materialize_remote(
        self,
        remote_name: str,
        *,
        destination: Path,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, Any]:
        """Download and durably publish one ledger-pinned remote object.

        The download inode stays open from the first byte through digest,
        durability, and no-replace publication.  A deterministic immutable
        intent binds the staging inode, so a retry can resume a hard-crash
        window but cannot adopt a same-UID path replacement.
        """

        self._validate_remote_name(remote_name)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ArtifactIntegrityError("expected SHA-256 must be 64 lowercase hex characters")
        if type(expected_size) is not int or expected_size < 0:
            raise ArtifactIntegrityError("expected materialize size is invalid")
        if os.name != "posix" or fcntl is None:
            raise ArtifactIntegrityError(
                "canonical remote materialization requires WSL POSIX custody"
            )

        lexical_target = Path(os.path.abspath(os.fspath(destination)))
        lexical_parent = lexical_target.parent
        lexical_parent.mkdir(parents=True, exist_ok=True)
        try:
            resolved_parent = lexical_parent.resolve(strict=True)
            parent_before = lexical_parent.lstat()
        except OSError:
            raise ArtifactIntegrityError(
                "materialize destination parent is unavailable"
            ) from None
        if (
            resolved_parent != lexical_parent
            or lexical_target != resolved_parent / lexical_target.name
        ):
            raise ArtifactIntegrityError(
                "materialize destination parent is redirected"
            )
        parent_inode = _directory_inode(parent_before)
        target = resolved_parent / lexical_target.name

        remote = self.list_remote_files().get(remote_name)
        if remote is None:
            raise ArtifactIntegrityError("remote artifact is missing")
        try:
            listed_size = int(remote.get("size"))
        except (TypeError, ValueError):
            raise ArtifactIntegrityError("remote artifact size is invalid") from None
        if listed_size != int(expected_size):
            raise ArtifactIntegrityError("remote artifact size does not match receipt")

        download_url = (
            f"{self.links.base_url}/d/{quote(self.links.read_token, safe='')}/files/?"
            + urlencode({"p": f"/{remote_name}", "dl": "1"})
        )
        request = Request(
            download_url,
            headers={"Accept": "application/octet-stream", "User-Agent": "VAST-Benchmark/1"},
        )

        transaction_key = _materialization_key(
            remote_name=remote_name,
            target_name=target.name,
            expected_sha256=expected_sha256,
            expected_size=expected_size,
        )
        transaction_relative = f"{_MATERIALIZATION_JOURNAL_ROOT}/{transaction_key}"
        intent_relative = f"{transaction_relative}/{_MATERIALIZATION_INTENT}"
        stage = resolved_parent / transaction_relative / _MATERIALIZATION_STAGE
        root_fd = journal_fd = transaction_fd = lock_fd = stage_fd = final_fd = -1
        try:
            with PhysicalRootCustodyV1.open(
                resolved_parent,
                label="Seafile materialize destination parent",
            ) as custody:
                custody.ensure_directory_owned(
                    _MATERIALIZATION_JOURNAL_ROOT,
                    label="Seafile materialization journal root",
                )
                custody.ensure_directory_owned(
                    transaction_relative,
                    label="Seafile materialization transaction",
                )
                for relative, label in (
                    (
                        _MATERIALIZATION_JOURNAL_ROOT,
                        "Seafile materialization journal root",
                    ),
                    (transaction_relative, "Seafile materialization transaction"),
                ):
                    mode, _identity = custody.stat_directory_identity(
                        relative, label=label
                    )
                    if custody.permission_modes_enforced and mode != 0o700:
                        raise ArtifactIntegrityError(f"{label} mode drifted")

                root_fd = os.open(
                    resolved_parent,
                    os.O_RDONLY
                    | int(getattr(os, "O_DIRECTORY", 0))
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                )
                if _directory_inode(os.fstat(root_fd)) != parent_inode:
                    raise ArtifactIntegrityError(
                        "materialize destination parent changed while opening"
                    )
                journal_fd = _open_directory_at(
                    root_fd,
                    _MATERIALIZATION_JOURNAL_ROOT,
                    label="Seafile materialization journal root",
                )
                transaction_fd = _open_directory_at(
                    journal_fd,
                    transaction_key,
                    label="Seafile materialization transaction",
                )
                lock_fd = os.open(
                    _MATERIALIZATION_LOCK,
                    os.O_RDWR
                    | os.O_CREAT
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    0o600,
                    dir_fd=transaction_fd,
                )
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                os.fchmod(lock_fd, 0o600)
                os.ftruncate(lock_fd, 0)
                os.fsync(lock_fd)
                lock_named = os.stat(
                    _MATERIALIZATION_LOCK,
                    dir_fd=transaction_fd,
                    follow_symlinks=False,
                )
                lock_opened = os.fstat(lock_fd)
                if (
                    not stat.S_ISREG(lock_opened.st_mode)
                    or int(lock_opened.st_nlink) != 1
                    or int(lock_opened.st_size) != 0
                    or _file_inode(lock_named) != _file_inode(lock_opened)
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization lock identity drifted"
                    )
                _verify_directory_at(
                    root_fd,
                    _MATERIALIZATION_JOURNAL_ROOT,
                    journal_fd,
                    label="Seafile materialization journal root",
                )
                _verify_directory_at(
                    journal_fd,
                    transaction_key,
                    transaction_fd,
                    label="Seafile materialization transaction",
                )
                custody.verify()

                entries = set(os.listdir(transaction_fd))
                allowed_entries = {
                    _MATERIALIZATION_LOCK,
                    _MATERIALIZATION_INTENT,
                    _MATERIALIZATION_STAGE,
                }
                if not entries <= allowed_entries:
                    raise ArtifactIntegrityError(
                        "Seafile materialization transaction contains foreign entries"
                    )

                intent: dict[str, Any] | None = None
                intent_names = custody.list_directory_names(
                    transaction_relative,
                    label="Seafile materialization transaction",
                )
                if _MATERIALIZATION_INTENT in intent_names:
                    descriptor, payload, _intent_inode = custody.read_descriptor_identity(
                        intent_relative,
                        label="Seafile materialization intent",
                        maximum=64 * 1024,
                        capture=True,
                    )
                    if payload is None:
                        raise ArtifactIntegrityError(
                            "Seafile materialization intent is unreadable"
                        )
                    try:
                        decoded = json.loads(payload)
                    except (TypeError, ValueError, UnicodeDecodeError):
                        raise ArtifactIntegrityError(
                            "Seafile materialization intent is invalid"
                        ) from None
                    expected_fields = {
                        "schema_version",
                        "remote_name",
                        "target_name",
                        "expected_sha256",
                        "expected_size",
                        "stage_name",
                        "stage_inode",
                    }
                    if (
                        type(decoded) is not dict
                        or set(decoded) != expected_fields
                        or decoded.get("schema_version")
                        != "vast-seafile-materialization-intent/v1"
                        or decoded.get("remote_name") != remote_name
                        or decoded.get("target_name") != target.name
                        or decoded.get("expected_sha256") != expected_sha256
                        or decoded.get("expected_size") != expected_size
                        or decoded.get("stage_name") != _MATERIALIZATION_STAGE
                        or type(decoded.get("stage_inode")) is not list
                        or len(decoded["stage_inode"]) != 2
                        or any(
                            type(value) is not int or value < 0
                            for value in decoded["stage_inode"]
                        )
                        or descriptor["sha256"] != hashlib.sha256(payload).hexdigest()
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization intent binding drifted"
                        )
                    intent = dict(decoded)

                def optional_stat(parent: int, name: str) -> os.stat_result | None:
                    try:
                        return os.stat(name, dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        return None

                stage_named = optional_stat(transaction_fd, _MATERIALIZATION_STAGE)
                final_named = optional_stat(root_fd, target.name)

                if intent is None and stage_named is not None:
                    raise ArtifactIntegrityError(
                        "Seafile materialization stage has no immutable intent"
                    )

                if intent is None and final_named is not None:
                    final_fd, _final_inode = _open_verified_file_at(
                        root_fd,
                        target.name,
                        label="existing materialize destination",
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        chunk_size=self.chunk_size,
                    )
                    os.fsync(root_fd)
                    return {
                        "status": "already_materialized_and_verified",
                        "remote_name": remote_name,
                        "size_bytes": expected_size,
                        "sha256": expected_sha256,
                        "destination": str(target),
                    }

                if intent is None:
                    stage_fd = os.open(
                        _MATERIALIZATION_STAGE,
                        os.O_RDWR
                        | os.O_CREAT
                        | os.O_EXCL
                        | int(getattr(os, "O_NOFOLLOW", 0))
                        | int(getattr(os, "O_CLOEXEC", 0)),
                        0o600,
                        dir_fd=transaction_fd,
                    )
                    created = os.fstat(stage_fd)
                    if not stat.S_ISREG(created.st_mode) or int(created.st_nlink) != 1:
                        raise ArtifactIntegrityError(
                            "Seafile materialization stage is not one physical file"
                        )
                    stage_inode = _file_inode(created)
                    intent = {
                        "schema_version": "vast-seafile-materialization-intent/v1",
                        "remote_name": remote_name,
                        "target_name": target.name,
                        "expected_sha256": expected_sha256,
                        "expected_size": expected_size,
                        "stage_name": _MATERIALIZATION_STAGE,
                        "stage_inode": list(stage_inode),
                    }
                    custody.commit_or_adopt_exact_identity(
                        intent_relative,
                        _canonical_json(intent),
                        label="Seafile materialization intent",
                        mode=0o444,
                        create_parents=False,
                    )
                    os.fsync(transaction_fd)
                else:
                    stage_inode = tuple(int(value) for value in intent["stage_inode"])

                stage_named = optional_stat(transaction_fd, _MATERIALIZATION_STAGE)
                final_named = optional_stat(root_fd, target.name)
                if final_named is not None:
                    if not stat.S_ISREG(final_named.st_mode):
                        raise ArtifactIntegrityError(
                            "resumed materialize destination is not one physical file"
                        )
                    final_inode_before = _file_inode(final_named)
                    same_link_recovery = False
                    if stage_named is None:
                        if int(final_named.st_nlink) != 1:
                            raise ArtifactIntegrityError(
                                "resumed materialize destination has foreign links"
                            )
                        allowed_final_links = frozenset({1})
                    else:
                        if (
                            not stat.S_ISREG(stage_named.st_mode)
                            or _file_inode(stage_named) != stage_inode
                        ):
                            raise ArtifactIntegrityError(
                                "Seafile materialization stage was rebound"
                            )
                        same_link_recovery = final_inode_before == stage_inode
                        if same_link_recovery:
                            if (
                                int(final_named.st_nlink) != 2
                                or int(stage_named.st_nlink) != 2
                            ):
                                raise ArtifactIntegrityError(
                                    "Seafile materialization linked recovery topology drifted"
                                )
                            allowed_final_links = frozenset({2})
                        else:
                            if (
                                int(final_named.st_nlink) != 1
                                or int(stage_named.st_nlink) != 1
                            ):
                                raise ArtifactIntegrityError(
                                    "Seafile materialization distinct final/stage topology has foreign links"
                                )
                            allowed_final_links = frozenset({1})
                    final_fd, final_inode = _open_verified_file_at(
                        root_fd,
                        target.name,
                        label="resumed materialize destination",
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        allowed_links=allowed_final_links,
                        chunk_size=self.chunk_size,
                    )
                    if stage_named is not None:
                        current = os.stat(
                            _MATERIALIZATION_STAGE,
                            dir_fd=transaction_fd,
                            follow_symlinks=False,
                        )
                        current_final = os.stat(
                            target.name,
                            dir_fd=root_fd,
                            follow_symlinks=False,
                        )
                        expected_links = 2 if same_link_recovery else 1
                        if (
                            _file_inode(current) != stage_inode
                            or _file_inode(current_final) != final_inode
                            or int(current.st_nlink) != expected_links
                            or int(current_final.st_nlink) != expected_links
                        ):
                            raise ArtifactIntegrityError(
                                "Seafile materialization final/stage topology changed before cleanup"
                            )
                        os.unlink(_MATERIALIZATION_STAGE, dir_fd=transaction_fd)
                        os.fsync(transaction_fd)
                    os.fsync(root_fd)
                    os.close(final_fd)
                    final_fd = -1
                    final_fd, _final_inode = _open_verified_file_at(
                        root_fd,
                        target.name,
                        label="durable resumed materialize destination",
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        chunk_size=self.chunk_size,
                    )
                    return {
                        "status": "already_materialized_and_verified",
                        "remote_name": remote_name,
                        "size_bytes": expected_size,
                        "sha256": expected_sha256,
                        "destination": str(target),
                    }

                if stage_named is None or _file_inode(stage_named) != stage_inode:
                    raise ArtifactIntegrityError(
                        "Seafile materialization stage is missing or rebound"
                    )
                if stage_fd < 0:
                    stage_fd = os.open(
                        _MATERIALIZATION_STAGE,
                        os.O_RDONLY
                        | int(getattr(os, "O_NOFOLLOW", 0))
                        | int(getattr(os, "O_CLOEXEC", 0)),
                        dir_fd=transaction_fd,
                    )
                opened_stage = os.fstat(stage_fd)
                if (
                    not stat.S_ISREG(opened_stage.st_mode)
                    or int(opened_stage.st_nlink) != 1
                    or _file_inode(opened_stage) != stage_inode
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization staged inode drifted"
                    )
                os.fchmod(stage_fd, 0o600)
                # A durable pre-publish crash leaves the owned stage 0444.
                # Pin/chmod it through the current descriptor before reopening
                # the exact inode for a deterministic restart.
                os.close(stage_fd)
                stage_fd = os.open(
                    _MATERIALIZATION_STAGE,
                    os.O_RDWR
                    | int(getattr(os, "O_NOFOLLOW", 0))
                    | int(getattr(os, "O_CLOEXEC", 0)),
                    dir_fd=transaction_fd,
                )
                if _file_inode(os.fstat(stage_fd)) != stage_inode:
                    raise ArtifactIntegrityError(
                        "Seafile materialization stage rebound while reopening"
                    )
                os.ftruncate(stage_fd, 0)
                os.lseek(stage_fd, 0, os.SEEK_SET)

                digest = hashlib.sha256()
                downloaded = 0
                mid_write_invoked = False

                def write_all(payload: bytes) -> None:
                    offset = 0
                    while offset < len(payload):
                        written = os.write(stage_fd, payload[offset:])
                        if written <= 0:
                            raise ArtifactIntegrityError(
                                "Seafile materialization write stalled"
                            )
                        offset += written

                with self._open_request(request, label="remote materialization") as response:
                    for chunk in iter(lambda: response.read(self.chunk_size), b""):
                        if not mid_write_invoked:
                            split = max(1, len(chunk) // 2)
                            first, remainder = chunk[:split], chunk[split:]
                            write_all(first)
                            digest.update(first)
                            downloaded += len(first)
                            mid_write_invoked = True
                            if self.materialize_physical_fault is not None:
                                self.materialize_physical_fault("mid_write", stage)
                            rebound = os.stat(
                                _MATERIALIZATION_STAGE,
                                dir_fd=transaction_fd,
                                follow_symlinks=False,
                            )
                            if _file_inode(rebound) != stage_inode:
                                raise ArtifactIntegrityError(
                                    "Seafile materialization stage was rebound mid-write"
                                )
                            write_all(remainder)
                            digest.update(remainder)
                            downloaded += len(remainder)
                        else:
                            write_all(chunk)
                            digest.update(chunk)
                            downloaded += len(chunk)
                if not mid_write_invoked and self.materialize_physical_fault is not None:
                    self.materialize_physical_fault("mid_write", stage)
                if downloaded != expected_size or digest.hexdigest() != expected_sha256:
                    raise ArtifactIntegrityError(
                        "materialized artifact does not match receipt"
                    )
                os.fchmod(stage_fd, 0o444)
                os.fsync(stage_fd)
                os.fsync(transaction_fd)
                held_size, held_sha256 = _hash_open_file(
                    stage_fd, chunk_size=self.chunk_size
                )
                staged_after = os.stat(
                    _MATERIALIZATION_STAGE,
                    dir_fd=transaction_fd,
                    follow_symlinks=False,
                )
                if (
                    _file_inode(staged_after) != stage_inode
                    or _file_inode(os.fstat(stage_fd)) != stage_inode
                    or int(staged_after.st_nlink) != 1
                    or held_size != expected_size
                    or held_sha256 != expected_sha256
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization stage changed before publication"
                    )
                if self.materialize_physical_fault is not None:
                    self.materialize_physical_fault("post_fsync_pre_publish", stage)
                staged_after_hook = os.stat(
                    _MATERIALIZATION_STAGE,
                    dir_fd=transaction_fd,
                    follow_symlinks=False,
                )
                hook_size, hook_sha256 = _hash_open_file(
                    stage_fd, chunk_size=self.chunk_size
                )
                if (
                    _file_inode(staged_after_hook) != stage_inode
                    or int(staged_after_hook.st_nlink) != 1
                    or hook_size != expected_size
                    or hook_sha256 != expected_sha256
                ):
                    raise ArtifactIntegrityError(
                        "Seafile materialization stage was rebound or mutated before publication"
                    )
                _verify_directory_at(
                    root_fd,
                    _MATERIALIZATION_JOURNAL_ROOT,
                    journal_fd,
                    label="Seafile materialization journal root",
                )
                _verify_directory_at(
                    journal_fd,
                    transaction_key,
                    transaction_fd,
                    label="Seafile materialization transaction",
                )
                custody.verify()

                try:
                    renamed = _rename_noreplace_at(
                        transaction_fd,
                        _MATERIALIZATION_STAGE,
                        root_fd,
                        target.name,
                    )
                    if not renamed:
                        os.link(
                            _MATERIALIZATION_STAGE,
                            target.name,
                            src_dir_fd=transaction_fd,
                            dst_dir_fd=root_fd,
                            follow_symlinks=False,
                        )
                except FileExistsError:
                    final_fd, _final_inode = _open_verified_file_at(
                        root_fd,
                        target.name,
                        label="raced materialize destination",
                        expected_size=expected_size,
                        expected_sha256=expected_sha256,
                        chunk_size=self.chunk_size,
                    )
                    current_stage = os.stat(
                        _MATERIALIZATION_STAGE,
                        dir_fd=transaction_fd,
                        follow_symlinks=False,
                    )
                    raced_final = os.stat(
                        target.name,
                        dir_fd=root_fd,
                        follow_symlinks=False,
                    )
                    if (
                        not stat.S_ISREG(current_stage.st_mode)
                        or _file_inode(current_stage) != stage_inode
                        or int(current_stage.st_nlink) != 1
                        or not stat.S_ISREG(raced_final.st_mode)
                        or int(raced_final.st_nlink) != 1
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization raced final/stage topology drifted"
                        )
                    os.unlink(_MATERIALIZATION_STAGE, dir_fd=transaction_fd)
                    os.fsync(transaction_fd)
                    os.fsync(root_fd)
                    status = "already_materialized_and_verified"
                else:
                    published = os.stat(
                        target.name, dir_fd=root_fd, follow_symlinks=False
                    )
                    if (
                        _file_inode(published) != stage_inode
                        or not stat.S_ISREG(published.st_mode)
                        or int(published.st_size) != expected_size
                        or int(published.st_nlink) not in {1, 2}
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization published inode drifted"
                        )
                    if self.materialize_physical_fault is not None:
                        self.materialize_physical_fault(
                            "post_publish_pre_parent_fsync", target
                        )
                    published_after_hook = os.stat(
                        target.name, dir_fd=root_fd, follow_symlinks=False
                    )
                    if (
                        _file_inode(published_after_hook) != stage_inode
                        or int(published_after_hook.st_size) != expected_size
                    ):
                        raise ArtifactIntegrityError(
                            "Seafile materialization destination was rebound after publish"
                        )
                    if not renamed:
                        linked_stage = os.stat(
                            _MATERIALIZATION_STAGE,
                            dir_fd=transaction_fd,
                            follow_symlinks=False,
                        )
                        if (
                            _file_inode(linked_stage) != stage_inode
                            or int(linked_stage.st_nlink) != 2
                            or int(published_after_hook.st_nlink) != 2
                        ):
                            raise ArtifactIntegrityError(
                                "Seafile materialization hard-link recovery drifted"
                            )
                        os.unlink(_MATERIALIZATION_STAGE, dir_fd=transaction_fd)
                    os.fsync(transaction_fd)
                    os.fsync(root_fd)
                    status = "materialized_and_verified"

                if final_fd >= 0:
                    os.close(final_fd)
                    final_fd = -1
                final_fd, final_inode = _open_verified_file_at(
                    root_fd,
                    target.name,
                    label="cold materialize destination",
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    expected_inode=(stage_inode if status == "materialized_and_verified" else None),
                    chunk_size=self.chunk_size,
                )
                if status == "materialized_and_verified" and final_inode != stage_inode:
                    raise ArtifactIntegrityError(
                        "Seafile materialization final inode changed across commit"
                    )
                os.fsync(root_fd)
                custody.verify()
        except ArtifactStoreError:
            raise
        except PublicationPhysicalIoV1Error:
            raise ArtifactIntegrityError(
                "remote materialization physical custody failed"
            ) from None
        except Exception:
            raise ArtifactIntegrityError("remote materialization failed") from None
        finally:
            for descriptor in (
                final_fd,
                stage_fd,
                lock_fd,
                transaction_fd,
                journal_fd,
                root_fd,
            ):
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
        return {
            "status": status,
            "remote_name": remote_name,
            "size_bytes": expected_size,
            "sha256": expected_sha256,
            "destination": str(target),
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload VAST benchmark artifacts to Seafile and verify streamed readback."
    )
    parser.add_argument("--timeout-s", type=float, default=120.0)
    parser.add_argument(
        "--links-file",
        type=Path,
        required=True,
        help="UTF-8 file containing one direct upload URL and one direct read URL",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload = subparsers.add_parser("upload")
    upload.add_argument("path", type=Path)
    upload.add_argument("--remote-name")

    verify = subparsers.add_parser("verify")
    verify.add_argument("remote_name")
    verify.add_argument("--sha256", required=True)
    verify.add_argument("--size", type=int, required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--live-upload-readback", action="store_true")

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--remote-name")
    return parser


def _production_links_from_file(path: Path) -> SeafileShareLinks:
    if path.name != "seafile.txt":
        raise ArtifactStoreError(
            "production Seafile links must come from seafile.txt"
        )
    return SeafileShareLinks.from_file(path)


def main() -> int:
    args = _build_parser().parse_args()
    links = _production_links_from_file(args.links_file)
    store = SeafileArtifactStore(
        links,
        timeout_s=args.timeout_s,
    )
    if args.command == "preflight":
        result = store.preflight(
            live_upload_readback=bool(args.live_upload_readback)
        )
    elif args.command == "upload":
        result = store.upload_and_verify(args.path, remote_name=args.remote_name)
    elif args.command == "verify":
        result = store.verify_remote(
            args.remote_name,
            expected_sha256=args.sha256,
            expected_size=args.size,
        )
    else:
        remote_name = args.remote_name or f"vast-cloud-smoke-{uuid.uuid4().hex}.bin"
        with tempfile.TemporaryDirectory(prefix="vast-cloud-smoke-") as tmp:
            payload = Path(tmp) / remote_name
            payload.write_bytes(b"VAST Seafile upload/readback smoke v1\n")
            result = store.upload_and_verify(payload, remote_name=remote_name)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
