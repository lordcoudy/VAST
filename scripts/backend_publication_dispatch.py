#!/usr/bin/env python3
"""Grant-bound, shell-free dispatch for qualified publication backends."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import stat
from pathlib import Path
from typing import Any, Mapping


INVOCATION_SCHEMA_VERSION = 2
INVOCATION_KIND = "vast_backend_publication_launcher_invocation"
RUNTIME_KIND = "python3_argv_v1"
ARGV_TEMPLATE = (
    "{python_executable}",
    "{launcher_path}",
    "--arm-contract",
    "{arm_contract_path}",
    "--output-dir",
    "{output_dir}",
)
REQUIRED_ENV_KEYS: tuple[str, ...] = ()
INPUT_PROTOCOL_IDENTITY_SHA256 = hashlib.sha256(
    b"vast-full-publication-arm-contract-json-v2"
).hexdigest()
OUTPUT_PROTOCOL_IDENTITY_SHA256 = hashlib.sha256(
    b"vast-full-publication-arm-output-receipt-json-v2"
).hexdigest()
INVOCATION_FIELDS = frozenset(
    {
        "schema_version",
        "artifact_kind",
        "runtime_kind",
        "argv_template",
        "required_env_keys",
        "input_protocol_identity_sha256",
        "output_protocol_identity_sha256",
        "invocation_sha256",
    }
)
SCENARIO_TO_TOPOLOGY = {
    "checkpoint_independent_processes_baseline": "independent_processes",
    "checkpoint_video_dag_shared": "shared_video_dag",
}
_SHA_RE = re.compile(r"[0-9a-f]{64}")


class BackendPublicationDispatchError(RuntimeError):
    """The qualified backend cannot be dispatched without weakening its grant."""


class BackendPublicationDispatchResolver:
    """Immutable indexed view of one fully validated backend runtime grant."""

    def __init__(self, backend_runtime_grant: Any) -> None:
        try:
            from backend_runtime_grant import validate_pre_run_backend_runtime_grant

            self.grant = validate_pre_run_backend_runtime_grant(
                backend_runtime_grant
            )
        except Exception as error:
            raise BackendPublicationDispatchError(
                f"pre-run backend runtime grant is unavailable or invalid: {error}"
            ) from error
        self._systems: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
        self._cells: dict[
            tuple[str, str, str, str, int], dict[str, Any]
        ] = {}
        for system, system_binding in self.grant["systems"].items():
            invocation = validate_launcher_invocation(
                system_binding.get("launcher_invocation")
            )
            self._systems[system] = (system_binding, invocation)
            for cell in system_binding["qualified_cells"]:
                coordinate = (
                    cell["system"],
                    cell["codec"],
                    cell["topology_kind"],
                    cell["policy"],
                    cell["deadline_ms"],
                )
                if coordinate in self._cells:
                    raise BackendPublicationDispatchError(
                        "backend publication coordinate is qualified more than once"
                    )
                self._cells[coordinate] = cell
        if len(self._cells) != 560:
            raise BackendPublicationDispatchError(
                "backend publication qualified coordinate cardinality drifted"
            )

    def resolve(
        self,
        *,
        system: str,
        scenario: str,
        codec: str,
        policy: str,
        deadline_ms: Any,
    ) -> dict[str, Any]:
        topology = SCENARIO_TO_TOPOLOGY.get(str(scenario))
        if topology is None:
            raise BackendPublicationDispatchError(
                "backend publication coordinate scenario is unsupported"
            )
        system_material = self._systems.get(str(system))
        if system_material is None:
            raise BackendPublicationDispatchError(
                "backend publication coordinate system is unqualified"
            )
        system_binding, invocation = system_material
        coordinate = (
            str(system),
            str(codec).strip().lower().replace("hevc", "h265"),
            topology,
            str(policy),
            _deadline(deadline_ms),
        )
        cell = self._cells.get(coordinate)
        if cell is None:
            raise BackendPublicationDispatchError(
                "backend publication coordinate is not qualified exactly once"
            )
        if (
            cell.get("launcher_invocation_sha256")
            != invocation["invocation_sha256"]
        ):
            raise BackendPublicationDispatchError(
                "backend publication cell invocation binding drifted"
            )
        material = {
            "schema_version": 2,
            "artifact_kind": "vast_backend_publication_dispatch_resolution",
            "backend_runtime_grant_sha256": self.grant["grant_sha256"],
            "identity_artifact_binding_sha256": self.grant[
                "identity_artifact_binding_sha256"
            ],
            "system": coordinate[0],
            "codec": coordinate[1],
            "topology_kind": coordinate[2],
            "policy": coordinate[3],
            "deadline_ms": coordinate[4],
            "cell_identity_sha256": cell["cell_identity_sha256"],
            "validation_record_sha256": cell["validation_record_sha256"],
            "runtime_binding_identity_sha256": system_binding[
                "runtime_binding_identity_sha256"
            ],
            "launcher": copy.deepcopy(system_binding["launcher"]),
            "launcher_invocation": copy.deepcopy(invocation),
            "launcher_invocation_sha256": invocation["invocation_sha256"],
        }
        material["resolution_sha256"] = _canonical_sha(material)
        return material


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise BackendPublicationDispatchError(
            "backend publication dispatch material is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def launcher_invocation_contract() -> dict[str, Any]:
    """Return the single closed invocation ABI accepted by publication dispatch."""

    value = {
        "schema_version": INVOCATION_SCHEMA_VERSION,
        "artifact_kind": INVOCATION_KIND,
        "runtime_kind": RUNTIME_KIND,
        "argv_template": list(ARGV_TEMPLATE),
        "required_env_keys": list(REQUIRED_ENV_KEYS),
        "input_protocol_identity_sha256": INPUT_PROTOCOL_IDENTITY_SHA256,
        "output_protocol_identity_sha256": OUTPUT_PROTOCOL_IDENTITY_SHA256,
    }
    value["invocation_sha256"] = _canonical_sha(value)
    return value


def validate_launcher_invocation(value: Any) -> dict[str, Any]:
    """Reject arbitrary argv placeholders, shells, environment, and protocol drift."""

    if type(value) is not dict or set(value) != INVOCATION_FIELDS:
        raise BackendPublicationDispatchError(
            "backend launcher invocation fields drifted"
        )
    expected = launcher_invocation_contract()
    if value != expected:
        raise BackendPublicationDispatchError(
            "backend launcher invocation contract drifted"
        )
    return copy.deepcopy(expected)


def runtime_binding_identity(
    *,
    system: str,
    launcher: Mapping[str, Any],
    launcher_invocation: Mapping[str, Any],
    upstream_identities: Mapping[str, Any],
) -> str:
    """Bind one runtime identity to its launcher, ABI, and frozen upstreams."""

    invocation = validate_launcher_invocation(dict(launcher_invocation))
    descriptor = dict(launcher)
    if type(launcher) is not dict or set(descriptor) != {
        "path",
        "size_bytes",
        "sha256",
    }:
        raise BackendPublicationDispatchError(
            "runtime binding launcher descriptor drifted"
        )
    if (
        type(descriptor["path"]) is not str
        or not descriptor["path"]
        or type(descriptor["size_bytes"]) is not int
        or descriptor["size_bytes"] <= 0
        or type(descriptor["sha256"]) is not str
        or _SHA_RE.fullmatch(descriptor["sha256"]) is None
    ):
        raise BackendPublicationDispatchError(
            "runtime binding launcher descriptor is invalid"
        )
    upstream = dict(upstream_identities)
    if (
        type(upstream_identities) is not dict
        or not upstream
        or any(
            type(value) is not str or _SHA_RE.fullmatch(value) is None
            for value in upstream.values()
        )
    ):
        raise BackendPublicationDispatchError(
            "runtime binding upstream identities are invalid"
        )
    return _canonical_sha(
        {
            "schema_version": 1,
            "artifact_kind": "vast_backend_publication_runtime_binding",
            "system": str(system),
            "launcher": descriptor,
            "launcher_invocation_sha256": invocation["invocation_sha256"],
            "upstream_identities": upstream,
        }
    )


def _deadline(value: Any) -> int | float:
    if isinstance(value, bool):
        raise BackendPublicationDispatchError(
            "backend publication coordinate deadline is invalid"
        )
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise BackendPublicationDispatchError(
            "backend publication coordinate deadline is invalid"
        ) from error
    if not math.isfinite(number):
        raise BackendPublicationDispatchError(
            "backend publication coordinate deadline is invalid"
        )
    return int(number) if number.is_integer() else number


def resolve_backend_publication_dispatch(
    backend_runtime_grant: Any,
    *,
    system: str,
    scenario: str,
    codec: str,
    policy: str,
    deadline_ms: Any,
) -> dict[str, Any]:
    """Resolve exactly one qualified cell and its grant-bound invocation ABI."""

    return BackendPublicationDispatchResolver(backend_runtime_grant).resolve(
        system=system,
        scenario=scenario,
        codec=codec,
        policy=policy,
        deadline_ms=deadline_ms,
    )


def _is_link_or_reparse(path: Path) -> bool:
    info = path.lstat()
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _sha_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_backend_publication_launcher(
    resolution: Mapping[str, Any],
    *,
    project_root: Path,
    identity_artifacts: Mapping[str, Any],
) -> Path:
    """Re-derive authorization, then rehash the physical launcher before spawn."""

    try:
        from backend_runtime_grant import backend_runtime_grant_from_identity_artifacts

        grant = backend_runtime_grant_from_identity_artifacts(
            copy.deepcopy(dict(identity_artifacts))
        )
    except Exception as error:
        raise BackendPublicationDispatchError(
            f"backend launcher identity binding is invalid: {error}"
        ) from error
    if (
        resolution.get("backend_runtime_grant_sha256") != grant["grant_sha256"]
        or resolution.get("identity_artifact_binding_sha256")
        != grant["identity_artifact_binding_sha256"]
    ):
        raise BackendPublicationDispatchError(
            "backend launcher resolution/identity binding drifted"
        )
    scenario_by_topology = {
        topology: scenario
        for scenario, topology in SCENARIO_TO_TOPOLOGY.items()
    }
    topology = str(resolution.get("topology_kind", ""))
    scenario = scenario_by_topology.get(topology)
    if scenario is None:
        raise BackendPublicationDispatchError(
            "backend launcher resolution topology drifted"
        )
    try:
        expected_resolution = BackendPublicationDispatchResolver(grant).resolve(
            system=str(resolution.get("system", "")),
            scenario=scenario,
            codec=str(resolution.get("codec", "")),
            policy=str(resolution.get("policy", "")),
            deadline_ms=resolution.get("deadline_ms"),
        )
    except BackendPublicationDispatchError as error:
        raise BackendPublicationDispatchError(
            f"backend launcher resolution is not grant-authorized: {error}"
        ) from error
    if dict(resolution) != expected_resolution:
        raise BackendPublicationDispatchError(
            "backend launcher resolution differs from the exact grant cell"
        )
    descriptor = resolution.get("launcher")
    if type(descriptor) is not dict or set(descriptor) != {
        "path",
        "size_bytes",
        "sha256",
    }:
        raise BackendPublicationDispatchError(
            "backend launcher descriptor drifted"
        )
    files = identity_artifacts.get("files")
    if type(files) is not list or sum(item == descriptor for item in files) != 1:
        raise BackendPublicationDispatchError(
            "backend launcher descriptor is not uniquely identity-bound"
        )
    root = Path(project_root).resolve(strict=True)
    relative = Path(str(descriptor["path"]))
    if (
        relative.is_absolute()
        or relative.as_posix() != descriptor["path"]
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise BackendPublicationDispatchError("backend launcher path is unsafe")
    cursor = root
    for part in relative.parts:
        cursor = cursor / part
        if _is_link_or_reparse(cursor):
            raise BackendPublicationDispatchError(
                "backend launcher path contains a link/reparse point"
            )
    try:
        launcher = (root / relative).resolve(strict=True)
        launcher.relative_to(root)
    except (OSError, ValueError) as error:
        raise BackendPublicationDispatchError(
            "backend launcher path escaped project root"
        ) from error
    before = launcher.stat()
    if not stat.S_ISREG(before.st_mode) or int(before.st_nlink) != 1:
        raise BackendPublicationDispatchError(
            "backend launcher is not a unique regular file"
        )
    digest = _sha_file(launcher)
    after = launcher.stat()
    if (
        (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        or int(after.st_size) != descriptor["size_bytes"]
        or digest != descriptor["sha256"]
    ):
        raise BackendPublicationDispatchError(
            "backend launcher physical size/SHA drift"
        )
    return launcher


def build_backend_publication_command(
    resolution: Mapping[str, Any],
    *,
    project_root: Path,
    identity_artifacts: Mapping[str, Any],
    python_executable: Path,
    arm_contract_path: Path,
    output_dir: Path,
) -> list[str]:
    """Materialize the only authorized argv list; no shell or environment input."""

    invocation = validate_launcher_invocation(
        resolution.get("launcher_invocation")
    )
    launcher = validate_backend_publication_launcher(
        resolution,
        project_root=project_root,
        identity_artifacts=identity_artifacts,
    )
    python = Path(python_executable).resolve(strict=True)
    if not python.is_file():
        raise BackendPublicationDispatchError("Python executable is invalid")
    values = {
        "python_executable": str(python),
        "launcher_path": str(launcher),
        "arm_contract_path": str(Path(arm_contract_path).resolve(strict=False)),
        "output_dir": str(Path(output_dir).resolve(strict=False)),
    }
    return [values.get(item[1:-1], item) for item in invocation["argv_template"]]


__all__ = [
    "ARGV_TEMPLATE",
    "BackendPublicationDispatchError",
    "BackendPublicationDispatchResolver",
    "INPUT_PROTOCOL_IDENTITY_SHA256",
    "OUTPUT_PROTOCOL_IDENTITY_SHA256",
    "build_backend_publication_command",
    "launcher_invocation_contract",
    "resolve_backend_publication_dispatch",
    "runtime_binding_identity",
    "validate_backend_publication_launcher",
    "validate_launcher_invocation",
]
