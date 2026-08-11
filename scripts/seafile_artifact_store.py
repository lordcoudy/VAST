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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen


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
        if upload.scheme not in {"http", "https"} or read.scheme not in {"http", "https"}:
            raise ArtifactStoreError("Seafile links must use HTTP or HTTPS")
        if (upload.scheme, upload.netloc) != (read.scheme, read.netloc):
            raise ArtifactStoreError("Seafile upload and read links must use the same origin")
        upload_match = re.fullmatch(r"/u/d/([A-Za-z0-9]+)/?", upload.path)
        read_match = re.fullmatch(r"/d/([A-Za-z0-9]+)/?", read.path)
        if upload_match is None:
            raise ArtifactStoreError("invalid Seafile upload-link path")
        if read_match is None:
            raise ArtifactStoreError("invalid Seafile read-link path")
        return cls(
            base_url=f"{upload.scheme}://{upload.netloc}",
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


class SeafileArtifactStore:
    def __init__(
        self,
        links: SeafileShareLinks,
        *,
        timeout_s: float = 120.0,
        chunk_size: int = 8 * 1024 * 1024,
    ) -> None:
        if timeout_s <= 0:
            raise ArtifactStoreError("timeout_s must be positive")
        if chunk_size <= 0:
            raise ArtifactStoreError("chunk_size must be positive")
        self.links = links
        self.timeout_s = float(timeout_s)
        self.chunk_size = int(chunk_size)

    def _json_get(self, path: str) -> Any:
        request = Request(
            self.links.base_url + path,
            headers={"Accept": "application/json", "User-Agent": "VAST-Benchmark/1"},
        )
        try:
            with urlopen(request, timeout=self.timeout_s) as response:
                payload = response.read()
                status = int(response.status)
        except Exception as exc:
            raise ArtifactStoreError("Seafile JSON request failed") from exc
        if status < 200 or status >= 300:
            raise ArtifactStoreError(f"Seafile JSON request returned HTTP {status}")
        try:
            return json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreError("Seafile returned invalid JSON") from exc

    def _upload_target(self) -> str:
        payload = self._json_get(
            f"/api/v2.1/upload-links/{quote(self.links.upload_token, safe='')}/upload/"
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("upload_link"), str):
            raise ArtifactStoreError("Seafile upload-link response is missing upload_link")
        target = str(payload["upload_link"])
        parsed = urlsplit(target)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ArtifactStoreError("Seafile returned an invalid upload target")
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
        if Path(remote_name).name != remote_name or "/" in remote_name or "\\" in remote_name:
            raise ArtifactStoreError("remote_name must be a single file name")
        if any(value in remote_name for value in ("\r", "\n", "\"")):
            raise ArtifactStoreError("remote_name contains an unsafe character")

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
        connection_type = (
            http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        )
        connection = connection_type(parsed.hostname, parsed.port, timeout=self.timeout_s)
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
        except Exception as exc:
            raise ArtifactStoreError("Seafile file upload failed") from exc
        finally:
            connection.close()

        if status < 200 or status >= 300:
            raise ArtifactStoreError(f"Seafile file upload returned HTTP {status}")
        try:
            return json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise ArtifactStoreError("Seafile upload returned invalid JSON") from exc

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

    def verify_remote(
        self,
        remote_name: str,
        *,
        expected_sha256: str,
        expected_size: int,
    ) -> dict[str, Any]:
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ArtifactIntegrityError("expected SHA-256 must be 64 lowercase hex characters")
        remote = self.list_remote_files().get(remote_name)
        if remote is None:
            raise ArtifactIntegrityError(f"remote artifact is missing: {remote_name}")
        try:
            listed_size = int(remote.get("size"))
        except (TypeError, ValueError) as exc:
            raise ArtifactIntegrityError("remote artifact size is invalid") from exc
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
            with urlopen(request, timeout=self.timeout_s) as response:
                for chunk in iter(lambda: response.read(self.chunk_size), b""):
                    digest.update(chunk)
                    downloaded += len(chunk)
        except Exception as exc:
            raise ArtifactIntegrityError("remote readback failed") from exc

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

    smoke = subparsers.add_parser("smoke")
    smoke.add_argument("--remote-name")
    return parser


def main() -> int:
    args = _build_parser().parse_args()
    store = SeafileArtifactStore(
        SeafileShareLinks.from_environment(),
        timeout_s=args.timeout_s,
    )
    if args.command == "upload":
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
