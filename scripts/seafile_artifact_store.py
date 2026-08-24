#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import mimetypes
import os
import re
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


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
    def from_environment(cls) -> "SeafileShareLinks":
        upload_url = os.environ.get("VAST_SEAFILE_UPLOAD_LINK", "").strip()
        read_url = os.environ.get("VAST_SEAFILE_READ_LINK", "").strip()
        if not upload_url or not read_url:
            raise ArtifactStoreError(
                "VAST_SEAFILE_UPLOAD_LINK and VAST_SEAFILE_READ_LINK are required"
            )
        return cls.from_urls(upload_url, read_url)


def sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


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

    def _post_file(self, target: str, local_path: Path, remote_name: str) -> Any:
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
        content_length = len(fields) + len(file_header) + local_path.stat().st_size + len(ending)

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
            with local_path.open("rb") as source:
                for chunk in iter(lambda: source.read(self.chunk_size), b""):
                    connection.send(chunk)
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

    def preflight(self) -> dict[str, Any]:
        files = self.list_remote_files()
        # Resolving the upload endpoint is a GET-only permission check; the
        # capability URL itself is deliberately never returned or logged.
        self._upload_target()
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
            "upload_capability": "verified_get_only",
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
        resolved = local_path.resolve()
        if not resolved.is_file():
            raise ArtifactStoreError(f"local artifact does not exist: {resolved}")
        name = remote_name or resolved.name
        self._validate_remote_name(name)
        size = resolved.stat().st_size
        digest = sha256_file(resolved, chunk_size=self.chunk_size)

        if name in self.list_remote_files():
            verified = self.verify_remote(
                name,
                expected_sha256=digest,
                expected_size=size,
            )
            return {**verified, "status": "already_present_and_verified"}

        self._post_file(self._upload_target(), resolved, name)
        verified = self.verify_remote(
            name,
            expected_sha256=digest,
            expected_size=size,
        )
        return {**verified, "status": "uploaded_and_verified"}

    def materialize_remote(
        self,
        remote_name: str,
        *,
        destination: Path,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, Any]:
        self._validate_remote_name(remote_name)
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ArtifactIntegrityError("expected SHA-256 must be 64 lowercase hex characters")
        target = destination.resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file():
                raise ArtifactIntegrityError("materialize destination is not a regular file")
            if target.stat().st_size != int(expected_size) or sha256_file(
                target, chunk_size=self.chunk_size
            ) != expected_sha256:
                raise ArtifactIntegrityError("materialize destination collision")
            return {
                "status": "already_materialized_and_verified",
                "remote_name": remote_name,
                "size_bytes": int(expected_size),
                "sha256": expected_sha256,
                "destination": str(target),
            }

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
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
        )
        temporary = Path(temporary_name)
        digest = hashlib.sha256()
        downloaded = 0
        try:
            with os.fdopen(descriptor, "wb") as output:
                with self._open_request(request, label="remote materialization") as response:
                    for chunk in iter(lambda: response.read(self.chunk_size), b""):
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if downloaded != int(expected_size) or digest.hexdigest() != expected_sha256:
                raise ArtifactIntegrityError("materialized artifact does not match receipt")
            if target.exists():
                raise ArtifactIntegrityError("materialize destination collision")
            os.replace(temporary, target)
        except ArtifactStoreError:
            raise
        except BaseException:
            raise ArtifactIntegrityError("remote materialization failed") from None
        finally:
            temporary.unlink(missing_ok=True)
        return {
            "status": "materialized_and_verified",
            "remote_name": remote_name,
            "size_bytes": downloaded,
            "sha256": digest.hexdigest(),
            "destination": str(target),
        }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Upload VAST benchmark artifacts to Seafile and verify streamed readback."
    )
    parser.add_argument("--timeout-s", type=float, default=120.0)
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload = subparsers.add_parser("upload")
    upload.add_argument("path", type=Path)
    upload.add_argument("--remote-name")

    verify = subparsers.add_parser("verify")
    verify.add_argument("remote_name")
    verify.add_argument("--sha256", required=True)
    verify.add_argument("--size", type=int, required=True)

    subparsers.add_parser("preflight")

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--remote-name")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    store = SeafileArtifactStore(
        SeafileShareLinks.from_environment(),
        timeout_s=args.timeout_s,
    )
    if args.command == "preflight":
        result = store.preflight()
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
