#!/usr/bin/env python3
"""Build an immutable quota- and sizing-bound Seafile capacity attestation."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

from seafile_artifact_store import ArtifactStoreError, SeafileShareLinks


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
POLICIES = (
    "cpu_only",
    "gpu_only",
    "static_hybrid",
    "heft",
    "deadline_aware_heft",
    "queue_aware_edf",
    "adaptive_weights",
)
DEADLINES_MS: tuple[int | float, ...] = (16.7, 33.3, 50, 100, 500)
MEASUREMENT_REPEAT_MULTIPLIER = 10
MINIMUM_CAPACITY_BYTES = 500 * 1024**3
SIZING_RESERVE_BYTES = 5 * 1024**3
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_PREFLIGHT_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "transport",
    "origin",
    "read_capability",
    "upload_capability",
    "remote_file_count",
    "remote_size_bytes",
    "quota_visibility",
}
_TOP_FIELDS = {
    "schema_version",
    "artifact_kind",
    "status",
    "scope",
    "observed_at_utc",
    "server_identity",
    "account_quota",
    "destination",
    "preflight_observation",
    "sizing_projection",
    "sha256",
}
_PROJECTION_FIELDS = {
    "formula",
    "observed_cell_count",
    "observed_pair_archive_bytes",
    "observed_cells_sha256",
    "pair_receipts_sha256",
    "measurement_repeat_multiplier",
    "projected_remote_bytes",
    "safety_factor_numerator",
    "safety_factor_denominator",
    "reserve_bytes",
    "minimum_capacity_bytes",
    "required_capacity_bytes",
}


class SeafileCapacityAttestationV1Error(RuntimeError):
    """Capacity, destination, sizing evidence, or immutable output is unsafe."""


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation is not canonical JSON"
        ) from exc


def _sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _positive_int(value: Any, label: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SeafileCapacityAttestationV1Error(f"{label} must be an integer")
    if value < 0 or (value == 0 and not allow_zero):
        raise SeafileCapacityAttestationV1Error(f"{label} is outside its range")
    return value


def _normalize_deadline(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SeafileCapacityAttestationV1Error("sizing deadline is invalid")
    matches = [candidate for candidate in DEADLINES_MS if float(candidate) == float(value)]
    if len(matches) != 1:
        raise SeafileCapacityAttestationV1Error("sizing deadline is outside frozen matrix")
    return matches[0]


def build_sizing_projection(
    observed_pair_archives: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate one full-duration pair observation for every 280 matrix cells."""
    expected = {
        (system, codec, policy, deadline)
        for system in SYSTEMS
        for codec in CODECS
        for policy in POLICIES
        for deadline in DEADLINES_MS
    }
    if not isinstance(observed_pair_archives, (list, tuple)) or len(observed_pair_archives) != 280:
        raise SeafileCapacityAttestationV1Error(
            "sizing projection requires exactly 280 observed pair cells"
        )
    normalized: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, int | float]] = set()
    receipt_hashes: set[str] = set()
    fields = {
        "system",
        "codec",
        "policy",
        "deadline_ms",
        "observed_pair_archive_bytes",
        "pair_receipt_sha256",
    }
    for position, raw in enumerate(observed_pair_archives):
        if type(raw) is not dict or set(raw) != fields:
            raise SeafileCapacityAttestationV1Error(
                f"sizing cell[{position}] fields drifted"
            )
        deadline = _normalize_deadline(raw["deadline_ms"])
        coordinate = (
            str(raw["system"]),
            str(raw["codec"]),
            str(raw["policy"]),
            deadline,
        )
        if coordinate not in expected or coordinate in seen:
            raise SeafileCapacityAttestationV1Error(
                "sizing coordinate set contains a duplicate or unknown cell"
            )
        size = _positive_int(raw["observed_pair_archive_bytes"], "pair archive size")
        receipt_sha = str(raw["pair_receipt_sha256"])
        if not _SHA_RE.fullmatch(receipt_sha) or receipt_sha in receipt_hashes:
            raise SeafileCapacityAttestationV1Error(
                "sizing pair receipt identity is invalid or aliased"
            )
        seen.add(coordinate)
        receipt_hashes.add(receipt_sha)
        normalized.append(
            {
                "system": coordinate[0],
                "codec": coordinate[1],
                "policy": coordinate[2],
                "deadline_ms": deadline,
                "observed_pair_archive_bytes": size,
                "pair_receipt_sha256": receipt_sha,
            }
        )
    if seen != expected:
        raise SeafileCapacityAttestationV1Error(
            "sizing coordinate set does not cover exact 280 cells"
        )
    normalized.sort(
        key=lambda row: (
            SYSTEMS.index(str(row["system"])),
            CODECS.index(str(row["codec"])),
            POLICIES.index(str(row["policy"])),
            DEADLINES_MS.index(row["deadline_ms"]),
        )
    )
    observed_bytes = sum(int(row["observed_pair_archive_bytes"]) for row in normalized)
    projected_bytes = MEASUREMENT_REPEAT_MULTIPLIER * observed_bytes
    safety_bytes = (projected_bytes * 5 + 3) // 4 + SIZING_RESERVE_BYTES
    required_bytes = max(MINIMUM_CAPACITY_BYTES, safety_bytes)
    return {
        "formula": "max(500GiB,ceil(projected_remote_bytes*1.25)+5GiB)",
        "observed_cell_count": len(normalized),
        "observed_pair_archive_bytes": observed_bytes,
        "observed_cells_sha256": _sha(normalized),
        "pair_receipts_sha256": _sha(
            [row["pair_receipt_sha256"] for row in normalized]
        ),
        "measurement_repeat_multiplier": MEASUREMENT_REPEAT_MULTIPLIER,
        "projected_remote_bytes": projected_bytes,
        "safety_factor_numerator": 5,
        "safety_factor_denominator": 4,
        "reserve_bytes": SIZING_RESERVE_BYTES,
        "minimum_capacity_bytes": MINIMUM_CAPACITY_BYTES,
        "required_capacity_bytes": required_bytes,
    }


def _validate_preflight(value: Any, *, origin: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _PREFLIGHT_FIELDS:
        raise SeafileCapacityAttestationV1Error("Seafile preflight fields drifted")
    if (
        value.get("schema_version") != 1
        or value.get("artifact_kind") != "vast_seafile_preflight"
        or value.get("status") != "ready"
        or value.get("transport") != "https"
        or value.get("origin") != origin
        or value.get("read_capability") != "verified"
        or value.get("upload_capability") != "verified_get_only"
        or value.get("quota_visibility") != "not_exposed_by_share_link"
    ):
        raise SeafileCapacityAttestationV1Error(
            "Seafile preflight identity/origin drifted"
        )
    count = _positive_int(value.get("remote_file_count"), "remote file count", allow_zero=True)
    size = _positive_int(value.get("remote_size_bytes"), "remote size", allow_zero=True)
    if count != 0 or size != 0:
        raise SeafileCapacityAttestationV1Error(
            "final Seafile destination must be empty and dedicated"
        )
    return dict(value)


def build_seafile_capacity_attestation_v1(
    *,
    account_info: Mapping[str, Any],
    repository: Mapping[str, Any],
    preflight: Mapping[str, Any],
    upload_url: str,
    read_url: str,
    observed_pair_archives: Sequence[Mapping[str, Any]],
    observed_at_utc: str,
    server_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a secret-free attestation only when quota and sizing both pass."""
    if type(account_info) is not dict or set(account_info) != {"total", "usage"}:
        raise SeafileCapacityAttestationV1Error("account quota response fields drifted")
    total = _positive_int(account_info["total"], "account quota total")
    usage = _positive_int(account_info["usage"], "account quota usage", allow_zero=True)
    if usage > total:
        raise SeafileCapacityAttestationV1Error("account quota usage exceeds total")
    available = total - usage

    if type(repository) is not dict or set(repository) != {"repo_id", "name"}:
        raise SeafileCapacityAttestationV1Error("repository response fields drifted")
    repo_id = str(repository["repo_id"])
    repo_name = str(repository["name"])
    if not _UUID_RE.fullmatch(repo_id) or not repo_name or len(repo_name) > 255:
        raise SeafileCapacityAttestationV1Error("Seafile repo identity is invalid")
    if not _UTC_RE.fullmatch(str(observed_at_utc)):
        raise SeafileCapacityAttestationV1Error("quota observation timestamp is invalid")
    if type(server_identity) is not dict or set(server_identity) != {
        "deployment_id",
        "server_version",
        "storage_scope",
    }:
        raise SeafileCapacityAttestationV1Error("server identity fields drifted")
    if (
        not all(
            isinstance(server_identity[field], str)
            and 3 <= len(str(server_identity[field])) <= 160
            and str(server_identity[field]) == str(server_identity[field]).strip()
            for field in server_identity
        )
        or server_identity.get("storage_scope") != "account_quota_api"
    ):
        raise SeafileCapacityAttestationV1Error("server identity is incomplete")

    try:
        links = SeafileShareLinks.from_urls(upload_url, read_url)
    except ArtifactStoreError as exc:
        raise SeafileCapacityAttestationV1Error(
            f"Seafile capability origin is invalid: {exc}"
        ) from exc
    checked_preflight = _validate_preflight(preflight, origin=links.base_url)
    projection = build_sizing_projection(observed_pair_archives)
    if available < projection["required_capacity_bytes"]:
        raise SeafileCapacityAttestationV1Error(
            "Seafile account quota is below the sizing requirement"
        )

    capability_identity = {
        "origin": links.base_url,
        "repo_id": repo_id,
        "upload_token_sha256": hashlib.sha256(
            links.upload_token.encode("ascii")
        ).hexdigest(),
        "read_token_sha256": hashlib.sha256(
            links.read_token.encode("ascii")
        ).hexdigest(),
    }
    destination_identity = {
        "origin": links.base_url,
        "repo_id": repo_id,
        "repository_name_sha256": hashlib.sha256(repo_name.encode("utf-8")).hexdigest(),
        "capability_pair_sha256": _sha(capability_identity),
    }
    value: dict[str, Any] = {
        "schema_version": 1,
        "artifact_kind": "vast_seafile_capacity_attestation_v1",
        "status": "accepted_dedicated_capacity",
        "scope": "full_publication_cloud_destination_only",
        "observed_at_utc": str(observed_at_utc),
        "server_identity": dict(server_identity),
        "account_quota": {
            "total_bytes": total,
            "usage_bytes": usage,
            "available_bytes": available,
            "source": "GET /api2/account/info/",
        },
        "destination": {
            **destination_identity,
            "destination_identity_sha256": _sha(destination_identity),
            "dedicated_namespace": True,
            "remote_file_count": 0,
            "remote_size_bytes": 0,
        },
        "preflight_observation": checked_preflight,
        "sizing_projection": projection,
    }
    value["sha256"] = _sha(value)
    return value


def validate_seafile_capacity_attestation_v1(
    value: Any,
    *,
    upload_url: str,
    read_url: str,
    repo_id: str,
) -> dict[str, Any]:
    """Validate a persisted attestation against the live capability pair."""
    if type(value) is not dict or set(value) != _TOP_FIELDS:
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation fields drifted"
        )
    if (
        value.get("schema_version") != 1
        or value.get("artifact_kind") != "vast_seafile_capacity_attestation_v1"
        or value.get("status") != "accepted_dedicated_capacity"
        or value.get("scope") != "full_publication_cloud_destination_only"
        or not _UTC_RE.fullmatch(str(value.get("observed_at_utc", "")))
    ):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation identity/status drifted"
        )
    expected_self_sha = value.get("sha256")
    unsigned = {key: child for key, child in value.items() if key != "sha256"}
    if not _SHA_RE.fullmatch(str(expected_self_sha)) or expected_self_sha != _sha(unsigned):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation self-hash drifted"
        )

    server = value.get("server_identity")
    if type(server) is not dict or set(server) != {
        "deployment_id",
        "server_version",
        "storage_scope",
    } or server.get("storage_scope") != "account_quota_api":
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation server identity drifted"
        )
    if not all(
        isinstance(server[field], str)
        and 3 <= len(server[field]) <= 160
        and server[field] == server[field].strip()
        for field in server
    ):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation server identity is incomplete"
        )

    quota = value.get("account_quota")
    if type(quota) is not dict or set(quota) != {
        "total_bytes",
        "usage_bytes",
        "available_bytes",
        "source",
    } or quota.get("source") != "GET /api2/account/info/":
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation account quota fields drifted"
        )
    total = _positive_int(quota.get("total_bytes"), "attested quota total")
    usage = _positive_int(
        quota.get("usage_bytes"), "attested quota usage", allow_zero=True
    )
    available = _positive_int(
        quota.get("available_bytes"), "attested quota available", allow_zero=True
    )
    if usage > total or available != total - usage:
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation quota arithmetic drifted"
        )

    try:
        links = SeafileShareLinks.from_urls(upload_url, read_url)
    except ArtifactStoreError as exc:
        raise SeafileCapacityAttestationV1Error(
            f"capacity attestation capability origin is invalid: {exc}"
        ) from exc
    if not _UUID_RE.fullmatch(str(repo_id)):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation destination repo identity is invalid"
        )
    destination = value.get("destination")
    destination_fields = {
        "origin",
        "repo_id",
        "repository_name_sha256",
        "capability_pair_sha256",
        "destination_identity_sha256",
        "dedicated_namespace",
        "remote_file_count",
        "remote_size_bytes",
    }
    if type(destination) is not dict or set(destination) != destination_fields:
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation destination fields drifted"
        )
    if (
        destination.get("origin") != links.base_url
        or destination.get("repo_id") != repo_id
        or destination.get("dedicated_namespace") is not True
        or destination.get("remote_file_count") != 0
        or destination.get("remote_size_bytes") != 0
        or not _SHA_RE.fullmatch(str(destination.get("repository_name_sha256")))
    ):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation destination identity drifted"
        )
    capability_identity = {
        "origin": links.base_url,
        "repo_id": repo_id,
        "upload_token_sha256": hashlib.sha256(
            links.upload_token.encode("ascii")
        ).hexdigest(),
        "read_token_sha256": hashlib.sha256(
            links.read_token.encode("ascii")
        ).hexdigest(),
    }
    expected_capability_sha = _sha(capability_identity)
    destination_identity = {
        "origin": links.base_url,
        "repo_id": repo_id,
        "repository_name_sha256": destination["repository_name_sha256"],
        "capability_pair_sha256": expected_capability_sha,
    }
    if (
        destination.get("capability_pair_sha256") != expected_capability_sha
        or destination.get("destination_identity_sha256")
        != _sha(destination_identity)
    ):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation capability binding drifted"
        )

    _validate_preflight(value.get("preflight_observation"), origin=links.base_url)
    projection = value.get("sizing_projection")
    if type(projection) is not dict or set(projection) != _PROJECTION_FIELDS:
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation sizing projection fields drifted"
        )
    observed_count = _positive_int(
        projection.get("observed_cell_count"), "sizing observed cell count"
    )
    observed_bytes = _positive_int(
        projection.get("observed_pair_archive_bytes"), "sizing observed bytes"
    )
    projected_bytes = _positive_int(
        projection.get("projected_remote_bytes"), "sizing projected bytes"
    )
    required_bytes = _positive_int(
        projection.get("required_capacity_bytes"), "sizing required capacity"
    )
    if (
        projection.get("formula")
        != "max(500GiB,ceil(projected_remote_bytes*1.25)+5GiB)"
        or observed_count != 280
        or projection.get("measurement_repeat_multiplier")
        != MEASUREMENT_REPEAT_MULTIPLIER
        or projected_bytes != observed_bytes * MEASUREMENT_REPEAT_MULTIPLIER
        or projection.get("safety_factor_numerator") != 5
        or projection.get("safety_factor_denominator") != 4
        or projection.get("reserve_bytes") != SIZING_RESERVE_BYTES
        or projection.get("minimum_capacity_bytes") != MINIMUM_CAPACITY_BYTES
        or required_bytes
        != max(
            MINIMUM_CAPACITY_BYTES,
            (projected_bytes * 5 + 3) // 4 + SIZING_RESERVE_BYTES,
        )
        or not _SHA_RE.fullmatch(str(projection.get("observed_cells_sha256")))
        or not _SHA_RE.fullmatch(str(projection.get("pair_receipts_sha256")))
        or available < required_bytes
    ):
        raise SeafileCapacityAttestationV1Error(
            "capacity attestation sizing/quota proof drifted"
        )
    return json.loads(_canonical_bytes(value).decode("utf-8"))


def write_immutable_attestation(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    """Atomically write once; identical replay is allowed, drift is rejected."""
    destination = Path(path).resolve(strict=False)
    parent = destination.parent.resolve(strict=True)
    if not parent.is_dir() or destination.parent != parent:
        raise SeafileCapacityAttestationV1Error(
            "attestation output parent must be a physical directory"
        )
    payload = _canonical_bytes(dict(value)) + b"\n"
    if destination.exists():
        try:
            info = destination.lstat()
            existing = destination.read_bytes()
        except OSError as exc:
            raise SeafileCapacityAttestationV1Error(
                f"immutable attestation collision: {exc}"
            ) from exc
        if not stat.S_ISREG(info.st_mode) or int(info.st_nlink) != 1 or existing != payload:
            raise SeafileCapacityAttestationV1Error("immutable attestation collision")
    else:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.", suffix=".tmp", dir=parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
        except Exception as exc:
            raise SeafileCapacityAttestationV1Error(
                f"immutable attestation commit failed: {exc}"
            ) from exc
        finally:
            temporary.unlink(missing_ok=True)
    return {
        "path": str(destination),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        inputs = json.loads(args.input_json.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SeafileCapacityAttestationV1Error(f"invalid input JSON: {exc}") from exc
    if type(inputs) is not dict:
        raise SeafileCapacityAttestationV1Error("input JSON must be an object")
    value = build_seafile_capacity_attestation_v1(**inputs)
    descriptor = write_immutable_attestation(args.output, value)
    print(json.dumps(descriptor, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CODECS",
    "DEADLINES_MS",
    "POLICIES",
    "SYSTEMS",
    "SeafileCapacityAttestationV1Error",
    "build_seafile_capacity_attestation_v1",
    "build_sizing_projection",
    "validate_seafile_capacity_attestation_v1",
    "write_immutable_attestation",
]
