#!/usr/bin/env python3
"""Provision isolated final/scratch Seafile libraries without exposing tokens."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from seafile_artifact_store import SeafileArtifactStore, SeafileShareLinks
from seafile_capacity_attestation_v1 import (
    build_seafile_capacity_attestation_v1,
    build_sizing_projection,
)


_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_TOKEN_RE = re.compile(r"^[A-Za-z0-9]+$")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SeafileDestinationProvisionV1Error(RuntimeError):
    """Provisioning failed without returning account or capability secrets."""


class AccountClient(Protocol):
    base_url: str

    def get_account_info(self) -> dict[str, int]: ...

    def create_repository(self, name: str) -> dict[str, str]: ...

    def create_upload_link(self, repo_id: str) -> str: ...

    def create_read_link(self, repo_id: str) -> str: ...

    def delete_repository(self, repo_id: str) -> None: ...


class _SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int]) -> None:
        super().__init__()
        self.origin = origin

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
            raise SeafileDestinationProvisionV1Error(
                "Seafile API redirect is invalid"
            ) from None
        if observed != self.origin or parsed.username is not None or parsed.password is not None:
            raise SeafileDestinationProvisionV1Error(
                "Seafile API redirect crossed the configured HTTPS origin"
            )
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class SeafileAccountClient:
    """Minimal non-retrying account API client; repr never includes the token."""

    def __init__(
        self,
        base_url: str,
        account_token: str,
        *,
        timeout_s: float = 60.0,
        opener: Any | None = None,
    ) -> None:
        try:
            parsed = urlsplit(base_url.strip())
        except ValueError:
            raise SeafileDestinationProvisionV1Error(
                "Seafile base URL must be a valid HTTPS origin"
            ) from None
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
        ):
            raise SeafileDestinationProvisionV1Error(
                "Seafile base URL must be an exact HTTPS origin"
            )
        token = str(account_token).strip()
        if not token or any(character in token for character in "\r\n\x00"):
            raise SeafileDestinationProvisionV1Error("Seafile account token is invalid")
        if timeout_s <= 0:
            raise SeafileDestinationProvisionV1Error("Seafile timeout must be positive")
        netloc = parsed.hostname.lower()
        if parsed.port is not None:
            netloc += f":{parsed.port}"
        self.base_url = f"https://{netloc}"
        self._account_token = token
        self.timeout_s = float(timeout_s)
        self._origin = ("https", parsed.hostname.lower(), parsed.port or 443)
        self._opener = opener or build_opener(_SameOriginRedirect(self._origin))

    def __repr__(self) -> str:
        return (
            f"SeafileAccountClient(base_url={self.base_url!r}, "
            "account_token=<redacted>)"
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Mapping[str, Any] | None = None,
        form_body: Mapping[str, str] | None = None,
    ) -> Any:
        if not path.startswith("/") or "//" in path:
            raise SeafileDestinationProvisionV1Error("Seafile API path is invalid")
        if json_body is not None and form_body is not None:
            raise SeafileDestinationProvisionV1Error("Seafile API body mode is ambiguous")
        data: bytes | None = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Token {self._account_token}",
            "User-Agent": "VAST-Benchmark-Provisioner/1",
        }
        if json_body is not None:
            data = json.dumps(
                dict(json_body), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            headers["Content-Type"] = "application/json"
        elif form_body is not None:
            data = urlencode(dict(form_body)).encode("ascii")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = Request(
            self.base_url + path,
            data=data,
            method=method,
            headers=headers,
        )
        try:
            with self._opener.open(request, timeout=self.timeout_s) as response:
                status = int(getattr(response, "status", 200))
                final = urlsplit(response.geturl())
                observed = (
                    final.scheme,
                    (final.hostname or "").lower(),
                    final.port or 443,
                )
                if observed != self._origin:
                    raise SeafileDestinationProvisionV1Error(
                        "Seafile API response crossed the configured HTTPS origin"
                    )
                payload = response.read()
        except SeafileDestinationProvisionV1Error:
            raise
        except HTTPError as exc:
            raise SeafileDestinationProvisionV1Error(
                f"Seafile API request returned HTTP {exc.code}"
            ) from None
        except Exception:
            raise SeafileDestinationProvisionV1Error(
                "Seafile API request failed"
            ) from None
        if status < 200 or status >= 300:
            raise SeafileDestinationProvisionV1Error(
                f"Seafile API request returned HTTP {status}"
            )
        if not payload:
            return None
        try:
            return json.loads(payload)
        except (TypeError, ValueError):
            raise SeafileDestinationProvisionV1Error(
                "Seafile API returned invalid JSON"
            ) from None

    @staticmethod
    def _integer(value: Any, label: str) -> int:
        if isinstance(value, bool):
            raise SeafileDestinationProvisionV1Error(f"{label} is invalid")
        try:
            result = int(value)
        except (TypeError, ValueError):
            raise SeafileDestinationProvisionV1Error(f"{label} is invalid") from None
        if result < 0:
            raise SeafileDestinationProvisionV1Error(f"{label} is invalid")
        return result

    def get_account_info(self) -> dict[str, int]:
        value = self._request("GET", "/api2/account/info/")
        if type(value) is not dict:
            raise SeafileDestinationProvisionV1Error(
                "Seafile account quota response is invalid"
            )
        return {
            "total": self._integer(value.get("total"), "account total quota"),
            "usage": self._integer(value.get("usage"), "account quota usage"),
        }

    def create_repository(self, name: str) -> dict[str, str]:
        value = self._request("POST", "/api2/repos/", form_body={"name": name})
        if type(value) is not dict:
            raise SeafileDestinationProvisionV1Error(
                "Seafile create-library response is invalid"
            )
        repo_id = str(value.get("repo_id") or value.get("id") or "")
        returned_name = str(value.get("repo_name") or value.get("name") or name)
        if not _UUID_RE.fullmatch(repo_id) or returned_name != name:
            raise SeafileDestinationProvisionV1Error(
                "Seafile create-library identity drifted"
            )
        return {"repo_id": repo_id, "name": returned_name}

    def _link(self, endpoint: str, repo_id: str, *, upload: bool) -> str:
        if not _UUID_RE.fullmatch(repo_id):
            raise SeafileDestinationProvisionV1Error("Seafile repo identity is invalid")
        value = self._request(
            "POST", endpoint, json_body={"repo_id": repo_id, "path": "/"}
        )
        if type(value) is not dict:
            raise SeafileDestinationProvisionV1Error(
                "Seafile capability response is invalid"
            )
        direct = value.get("link") or value.get("upload_link") or value.get("share_link")
        token = str(value.get("token") or "")
        if isinstance(direct, str) and direct:
            candidate = direct
        elif _TOKEN_RE.fullmatch(token):
            candidate = self.base_url + (("/u/d/" if upload else "/d/") + token)
        else:
            raise SeafileDestinationProvisionV1Error(
                "Seafile capability response is incomplete"
            )
        try:
            parsed = SeafileShareLinks.from_urls(
                candidate if upload else self.base_url + "/u/d/ValidationToken99",
                self.base_url + "/d/ValidationToken99" if upload else candidate,
            )
        except Exception:
            raise SeafileDestinationProvisionV1Error(
                "Seafile capability response is invalid"
            ) from None
        if parsed.base_url != self.base_url:
            raise SeafileDestinationProvisionV1Error(
                "Seafile capability response crossed origin"
            )
        return candidate

    def create_upload_link(self, repo_id: str) -> str:
        return self._link("/api/v2.1/upload-links/", repo_id, upload=True)

    def create_read_link(self, repo_id: str) -> str:
        return self._link("/api/v2.1/share-links/", repo_id, upload=False)

    def delete_repository(self, repo_id: str) -> None:
        if not _UUID_RE.fullmatch(repo_id):
            raise SeafileDestinationProvisionV1Error("Seafile repo identity is invalid")
        self._request("DELETE", f"/api2/repos/{quote(repo_id, safe='')}/")


StoreFactory = Callable[[str, str], Any]
FilesystemTypeResolver = Callable[[Path], str]


def _default_store_factory(upload_url: str, read_url: str) -> SeafileArtifactStore:
    return SeafileArtifactStore(SeafileShareLinks.from_urls(upload_url, read_url))


def _secure_write(path: Path, payload: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload.encode("utf-8"))
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    os.chmod(path, 0o600)
    if stat.S_IMODE(path.stat().st_mode) != 0o600:
        path.unlink(missing_ok=True)
        raise SeafileDestinationProvisionV1Error(
            "secret environment file cannot be secured as mode 0600"
        )


def _env_payload(
    upload_url: str,
    read_url: str,
    repo_id: str,
    *,
    final: bool,
    capacity_attestation_path: Path | None = None,
) -> str:
    values = {
        "VAST_SEAFILE_UPLOAD_LINK": upload_url,
        "VAST_SEAFILE_READ_LINK": read_url,
        "VAST_SEAFILE_DESTINATION_ID": repo_id,
    }
    if final:
        if capacity_attestation_path is None or not capacity_attestation_path.is_absolute():
            raise SeafileDestinationProvisionV1Error(
                "final capacity attestation path must be absolute"
            )
        values["VAST_SEAFILE_CAPACITY_ATTESTATION"] = str(
            capacity_attestation_path
        )
    for value in values.values():
        if any(character in value for character in "'\r\n\x00"):
            raise SeafileDestinationProvisionV1Error(
                "secret environment value contains unsafe characters"
            )
    return "".join(f"{key}='{value}'\n" for key, value in values.items())


def _is_junction(path: Path) -> bool:
    predicate = getattr(os.path, "isjunction", None)
    if predicate is None:
        return False
    try:
        return bool(predicate(path))
    except OSError:
        return True


def _physical_directory(path: Path, *, label: str) -> Path:
    lexical = Path(path)
    if not lexical.is_absolute():
        raise SeafileDestinationProvisionV1Error(f"{label} must be absolute")
    try:
        resolved = lexical.resolve(strict=True)
        info = lexical.lstat()
    except OSError as exc:
        raise SeafileDestinationProvisionV1Error(
            f"{label} is unavailable"
        ) from exc
    if (
        lexical != resolved
        or lexical.is_symlink()
        or _is_junction(lexical)
        or not stat.S_ISDIR(info.st_mode)
    ):
        raise SeafileDestinationProvisionV1Error(
            f"{label} must be a physical directory"
        )
    return resolved


def _new_destination(path: Path, *, label: str) -> tuple[Path, Path]:
    lexical = Path(path)
    if not lexical.is_absolute():
        raise SeafileDestinationProvisionV1Error(f"{label} must be absolute")
    if lexical.exists() or lexical.is_symlink() or _is_junction(lexical):
        raise SeafileDestinationProvisionV1Error(f"{label} collision")
    parent = _physical_directory(lexical.parent, label=f"{label} parent")
    candidate = parent / lexical.name
    if lexical != candidate or candidate.parent != parent or not lexical.name:
        raise SeafileDestinationProvisionV1Error(
            f"{label} parent must be a physical directory"
        )
    return candidate, parent


def _findmnt_filesystem_type(path: Path) -> str:
    executable = shutil.which("findmnt")
    if os.name != "posix" or executable is None:
        raise SeafileDestinationProvisionV1Error(
            "secret output filesystem cannot be verified as ext4"
        )
    try:
        completed = subprocess.run(
            [executable, "--noheadings", "--output", "FSTYPE", "--target", str(path)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10.0,
        )
    except (OSError, subprocess.SubprocessError):
        raise SeafileDestinationProvisionV1Error(
            "secret output filesystem cannot be verified as ext4"
        ) from None
    lines = [
        line.strip().lower()
        for line in completed.stdout.splitlines()
        if line.strip()
    ]
    if completed.returncode != 0 or len(lines) != 1:
        raise SeafileDestinationProvisionV1Error(
            "secret output filesystem cannot be verified as ext4"
        )
    return lines[0]


def _validated_destinations(
    *,
    project_root: Path,
    secret_output_dir: Path,
    capacity_attestation_path: Path,
    secret_filesystem_type_resolver: FilesystemTypeResolver,
) -> tuple[Path, Path, Path, Path, Path]:
    root = _physical_directory(project_root, label="project_root")
    secret, secret_parent = _new_destination(
        secret_output_dir, label="secret output directory"
    )
    capacity, capacity_parent = _new_destination(
        capacity_attestation_path, label="capacity attestation output"
    )
    try:
        relative_capacity = capacity.relative_to(root)
    except ValueError:
        raise SeafileDestinationProvisionV1Error(
            "capacity attestation output must be inside project_root"
        ) from None
    if not relative_capacity.parts:
        raise SeafileDestinationProvisionV1Error(
            "capacity attestation output must be inside project_root"
        )
    try:
        secret.relative_to(root)
    except ValueError:
        pass
    else:
        raise SeafileDestinationProvisionV1Error(
            "secret output directory must be outside project_root"
        )
    protected = capacity_parent
    while True:
        try:
            if os.path.samefile(secret_parent, protected):
                raise SeafileDestinationProvisionV1Error(
                    "secret output parent aliases capacity attestation ancestry"
                )
        except FileNotFoundError:
            raise SeafileDestinationProvisionV1Error(
                "output ancestry became unavailable"
            ) from None
        if protected == root:
            break
        if root not in protected.parents:
            raise SeafileDestinationProvisionV1Error(
                "capacity attestation ancestry escaped project_root"
            )
        protected = protected.parent
    try:
        filesystem_type = secret_filesystem_type_resolver(secret_parent)
    except SeafileDestinationProvisionV1Error:
        raise
    except Exception:
        raise SeafileDestinationProvisionV1Error(
            "secret output filesystem cannot be verified as ext4"
        ) from None
    if not isinstance(filesystem_type, str) or filesystem_type.strip().lower() != "ext4":
        raise SeafileDestinationProvisionV1Error(
            "secret output directory must be on an ext4 filesystem"
        )
    return root, secret, secret_parent, capacity, capacity_parent


def _cleanup_staging(path: Path, parent: Path) -> None:
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return
    if (
        resolved.parent != parent
        or not resolved.name.startswith(".seafile-provision-v1.")
        or not resolved.is_dir()
        or resolved.is_symlink()
        or _is_junction(resolved)
    ):
        raise SeafileDestinationProvisionV1Error(
            "refusing unsafe provisioning staging cleanup"
        )
    entries = list(resolved.iterdir())
    if not {entry.name for entry in entries}.issubset({"final.env", "scratch.env"}):
        raise SeafileDestinationProvisionV1Error(
            "refusing provisioning staging cleanup with foreign entries"
        )
    for entry in entries:
        info = entry.lstat()
        if (
            not stat.S_ISREG(info.st_mode)
            or int(info.st_nlink) != 1
            or stat.S_IMODE(info.st_mode) != 0o600
        ):
            raise SeafileDestinationProvisionV1Error(
                "refusing provisioning staging cleanup after entry drift"
            )
    for entry in entries:
        entry.unlink()
    resolved.rmdir()


def _stage_attestation(
    parent: Path, destination_name: str, value: Mapping[str, Any]
) -> tuple[Path, bytes]:
    payload = (
        json.dumps(dict(value), sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination_name}.seafile-provision-v1.",
        suffix=".tmp",
        dir=parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        info = temporary.lstat()
        if not stat.S_ISREG(info.st_mode) or int(info.st_nlink) != 1:
            raise SeafileDestinationProvisionV1Error(
                "capacity attestation staging is not a unique physical file"
            )
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return temporary, payload


def _commit_attestation_exclusive(
    staging: Path, destination: Path, payload: bytes
) -> tuple[int, int]:
    owner: tuple[int, int] | None = None
    try:
        os.link(staging, destination, follow_symlinks=False)
        staged_info = staging.lstat()
        destination_info = destination.lstat()
        owner = (int(destination_info.st_dev), int(destination_info.st_ino))
        if (
            not stat.S_ISREG(destination_info.st_mode)
            or int(destination_info.st_dev) != int(staged_info.st_dev)
            or int(destination_info.st_ino) != int(staged_info.st_ino)
            or int(destination_info.st_nlink) != 2
            or destination.read_bytes() != payload
        ):
            raise SeafileDestinationProvisionV1Error(
                "capacity attestation exclusive commit drifted"
            )
        staging.unlink()
        destination_info = destination.lstat()
        if int(destination_info.st_nlink) != 1 or destination.read_bytes() != payload:
            raise SeafileDestinationProvisionV1Error(
                "capacity attestation exclusive commit drifted"
            )
        return owner
    except Exception:
        if owner is not None:
            try:
                destination_info = destination.lstat()
                if (
                    int(destination_info.st_dev),
                    int(destination_info.st_ino),
                ) == owner:
                    destination.unlink()
            except OSError:
                pass
        else:
            try:
                staged_info = staging.lstat()
                destination_info = destination.lstat()
                if (
                    int(staged_info.st_dev) == int(destination_info.st_dev)
                    and int(staged_info.st_ino) == int(destination_info.st_ino)
                ):
                    destination.unlink()
            except OSError:
                pass
        staging.unlink(missing_ok=True)
        raise


def _remove_owned_attestation(
    destination: Path, owner: tuple[int, int], payload: bytes
) -> None:
    info = destination.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or (int(info.st_dev), int(info.st_ino)) != owner
        or int(info.st_nlink) != 1
        or destination.read_bytes() != payload
    ):
        raise SeafileDestinationProvisionV1Error(
            "refusing to remove unowned capacity attestation"
        )
    destination.unlink()


def _create_secret_directory(destination: Path) -> tuple[int, int]:
    os.mkdir(destination, 0o700)
    info = destination.lstat()
    owner = (int(info.st_dev), int(info.st_ino))
    if (
        not stat.S_ISDIR(info.st_mode)
        or destination.is_symlink()
        or _is_junction(destination)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise SeafileDestinationProvisionV1Error(
            "secret output directory cannot be secured as mode 0700"
        )
    return owner


def _commit_secret_directory(
    staging: Path, destination: Path, owner: tuple[int, int]
) -> None:
    info = destination.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or destination.is_symlink()
        or _is_junction(destination)
        or (int(info.st_dev), int(info.st_ino)) != owner
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise SeafileDestinationProvisionV1Error(
            "secret output directory identity drifted"
        )
    for filename in ("final.env", "scratch.env"):
        source = staging / filename
        source_info = source.lstat()
        if (
            not stat.S_ISREG(source_info.st_mode)
            or int(source_info.st_nlink) != 1
            or stat.S_IMODE(source_info.st_mode) != 0o600
        ):
            raise SeafileDestinationProvisionV1Error(
                "secret environment staging drifted"
            )
        os.rename(source, destination / filename)
    staging.rmdir()
    for filename in ("final.env", "scratch.env"):
        committed = destination / filename
        committed_info = committed.lstat()
        if (
            not stat.S_ISREG(committed_info.st_mode)
            or int(committed_info.st_nlink) != 1
            or stat.S_IMODE(committed_info.st_mode) != 0o600
        ):
            raise SeafileDestinationProvisionV1Error(
                "secret environment commit drifted"
            )


def _remove_owned_secret_directory(
    destination: Path, owner: tuple[int, int]
) -> None:
    info = destination.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or destination.is_symlink()
        or _is_junction(destination)
        or (int(info.st_dev), int(info.st_ino)) != owner
    ):
        raise SeafileDestinationProvisionV1Error(
            "refusing to remove unowned secret output directory"
        )
    entries = {entry.name: entry for entry in destination.iterdir()}
    if not set(entries).issubset({"final.env", "scratch.env"}):
        raise SeafileDestinationProvisionV1Error(
            "refusing to remove secret output directory with foreign entries"
        )
    for entry in entries.values():
        entry_info = entry.lstat()
        if (
            not stat.S_ISREG(entry_info.st_mode)
            or int(entry_info.st_nlink) != 1
            or stat.S_IMODE(entry_info.st_mode) != 0o600
        ):
            raise SeafileDestinationProvisionV1Error(
                "refusing to remove drifted secret environment file"
            )
    for entry in entries.values():
        entry.unlink()
    destination.rmdir()


def provision_seafile_destinations_v1(
    *,
    client: AccountClient,
    observed_pair_archives: Sequence[Mapping[str, Any]],
    project_root: Path,
    secret_output_dir: Path,
    capacity_attestation_path: Path,
    observed_at_utc: str,
    server_identity: Mapping[str, Any],
    store_factory: StoreFactory = _default_store_factory,
    secret_filesystem_type_resolver: FilesystemTypeResolver = _findmnt_filesystem_type,
) -> dict[str, Any]:
    """Create two new libraries and split public/secret local bindings safely."""
    (
        _root,
        secret_destination,
        secret_parent,
        capacity_destination,
        capacity_parent,
    ) = _validated_destinations(
        project_root=project_root,
        secret_output_dir=secret_output_dir,
        capacity_attestation_path=capacity_attestation_path,
        secret_filesystem_type_resolver=secret_filesystem_type_resolver,
    )
    projection = build_sizing_projection(observed_pair_archives)
    try:
        account = client.get_account_info()
    except Exception:
        raise SeafileDestinationProvisionV1Error(
            "Seafile quota preflight failed"
        ) from None
    if type(account) is not dict or set(account) != {"total", "usage"}:
        raise SeafileDestinationProvisionV1Error("Seafile quota response drifted")
    total = account.get("total")
    usage = account.get("usage")
    if (
        isinstance(total, bool)
        or isinstance(usage, bool)
        or not isinstance(total, int)
        or not isinstance(usage, int)
        or total <= 0
        or usage < 0
        or usage > total
        or total - usage < int(projection["required_capacity_bytes"])
    ):
        raise SeafileDestinationProvisionV1Error(
            "Seafile account quota is below the sizing requirement"
        )

    created: list[str] = []
    secret_staging: Path | None = None
    attestation_staging: Path | None = None
    attestation_payload: bytes | None = None
    attestation_owner: tuple[int, int] | None = None
    secret_owner: tuple[int, int] | None = None
    try:
        suffix = observed_at_utc.replace(":", "").replace("-", "")
        scratch = client.create_repository(f"VAST qualification scratch {suffix}")
        scratch_id = str(scratch.get("repo_id", ""))
        if not _UUID_RE.fullmatch(scratch_id):
            raise SeafileDestinationProvisionV1Error("scratch repo identity drifted")
        created.append(scratch_id)
        scratch_upload = client.create_upload_link(scratch_id)
        scratch_read = client.create_read_link(scratch_id)
        scratch_preflight = store_factory(scratch_upload, scratch_read).preflight()
        if (
            type(scratch_preflight) is not dict
            or scratch_preflight.get("remote_file_count") != 0
            or scratch_preflight.get("remote_size_bytes") != 0
        ):
            raise SeafileDestinationProvisionV1Error(
                "scratch destination is not empty"
            )

        final = client.create_repository(f"VAST full publication final {suffix}")
        final_id = str(final.get("repo_id", ""))
        if not _UUID_RE.fullmatch(final_id) or final_id == scratch_id:
            raise SeafileDestinationProvisionV1Error("final repo identity drifted")
        created.append(final_id)
        final_upload = client.create_upload_link(final_id)
        final_read = client.create_read_link(final_id)
        final_preflight = store_factory(final_upload, final_read).preflight()

        attestation = build_seafile_capacity_attestation_v1(
            account_info=account,
            repository=final,
            preflight=final_preflight,
            upload_url=final_upload,
            read_url=final_read,
            observed_pair_archives=observed_pair_archives,
            observed_at_utc=observed_at_utc,
            server_identity=server_identity,
        )

        attestation_staging, attestation_payload = _stage_attestation(
            capacity_parent, capacity_destination.name, attestation
        )
        secret_staging = Path(
            tempfile.mkdtemp(prefix=".seafile-provision-v1.", dir=secret_parent)
        )
        os.chmod(secret_staging, 0o700)
        if stat.S_IMODE(secret_staging.stat().st_mode) != 0o700:
            raise SeafileDestinationProvisionV1Error(
                "secret staging directory cannot be secured as mode 0700"
            )
        _secure_write(
            secret_staging / "final.env",
            _env_payload(
                final_upload,
                final_read,
                final_id,
                final=True,
                capacity_attestation_path=capacity_destination,
            ),
        )
        _secure_write(
            secret_staging / "scratch.env",
            _env_payload(scratch_upload, scratch_read, scratch_id, final=False),
        )
        attestation_owner = _commit_attestation_exclusive(
            attestation_staging, capacity_destination, attestation_payload
        )
        attestation_staging = None
        secret_owner = _create_secret_directory(secret_destination)
        _commit_secret_directory(
            secret_staging, secret_destination, secret_owner
        )
        secret_staging = None
        result = {
            "status": "provisioned",
            "final_repo_id": final_id,
            "scratch_repo_id": scratch_id,
            "capacity_attestation_sha256": attestation["sha256"],
            "capacity_attestation": str(capacity_destination),
            "final_environment": str(secret_destination / "final.env"),
            "scratch_environment": str(secret_destination / "scratch.env"),
            "secrets_redacted": True,
        }
        return result
    except Exception:
        local_cleanup_failed = False
        if secret_owner is not None:
            try:
                _remove_owned_secret_directory(secret_destination, secret_owner)
            except Exception:
                local_cleanup_failed = True
        if attestation_owner is not None and attestation_payload is not None:
            try:
                _remove_owned_attestation(
                    capacity_destination, attestation_owner, attestation_payload
                )
            except Exception:
                local_cleanup_failed = True
        rollback_failed: list[str] = []
        for repo_id in reversed(created):
            try:
                client.delete_repository(repo_id)
            except Exception:
                rollback_failed.append(repo_id)
        if rollback_failed or local_cleanup_failed:
            detail = ""
            if rollback_failed:
                detail = ": " + ",".join(sorted(rollback_failed))
            raise SeafileDestinationProvisionV1Error(
                "Seafile provisioning failed and rollback was incomplete for newly "
                "created artifacts" + detail
            ) from None
        raise SeafileDestinationProvisionV1Error(
            "Seafile provisioning failed; newly created repositories were rolled back"
        ) from None
    finally:
        if attestation_staging is not None:
            attestation_staging.unlink(missing_ok=True)
        if secret_staging is not None and secret_staging.exists():
            _cleanup_staging(secret_staging, secret_parent)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--account-token-env", default="VAST_SEAFILE_ACCOUNT_TOKEN")
    parser.add_argument("--sizing-json", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--secret-output-dir", type=Path, required=True)
    parser.add_argument("--capacity-attestation-output", type=Path, required=True)
    parser.add_argument("--observed-at-utc", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--server-version", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    token = os.environ.pop(args.account_token_env, "")
    if not token:
        raise SeafileDestinationProvisionV1Error(
            f"account token environment variable is required: {args.account_token_env}"
        )
    try:
        observed = json.loads(args.sizing_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SeafileDestinationProvisionV1Error(f"invalid sizing JSON: {exc}") from exc
    result = provision_seafile_destinations_v1(
        client=SeafileAccountClient(args.base_url, token),
        observed_pair_archives=observed,
        project_root=args.project_root,
        secret_output_dir=args.secret_output_dir,
        capacity_attestation_path=args.capacity_attestation_output,
        observed_at_utc=args.observed_at_utc,
        server_identity={
            "deployment_id": args.deployment_id,
            "server_version": args.server_version,
            "storage_scope": "account_quota_api",
        },
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "SeafileAccountClient",
    "SeafileDestinationProvisionV1Error",
    "provision_seafile_destinations_v1",
]
