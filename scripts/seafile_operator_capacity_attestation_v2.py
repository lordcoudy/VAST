#!/usr/bin/env python3
"""Build a secret-free Seafile capacity attestation from an operator guarantee.

Version 2 deliberately makes no account-quota API, repository UUID, empty
namespace, or dedicated-layout claim.  It binds an explicit operator lower
bound to the exact capability pair, a stable caller destination identifier,
the live share-link preflight, and the physical 280-row Q4 sizing projection.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from seafile_artifact_store import (
    ArtifactStoreError,
    SeafileArtifactStore,
    SeafileShareLinks,
)
from seafile_capacity_attestation_v1 import (
    MINIMUM_CAPACITY_BYTES,
    SeafileCapacityAttestationV1Error,
    build_sizing_projection,
)


GIB = 1024**3
SCHEMA_VERSION = 2
ARTIFACT_KIND = "vast_seafile_operator_capacity_attestation_v2"
STATUS = "accepted_operator_capacity_lower_bound"
SCOPE = "full_publication_cloud_capability_destination_only"
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_DESTINATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")
_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$")
_PREFLIGHT_FIELDS = {
    "schema_version", "artifact_kind", "status", "transport", "origin",
    "read_capability", "upload_capability", "remote_file_count",
    "remote_size_bytes", "quota_visibility",
}
_CONFIRMATION_FIELDS = {
    "basis", "available_capacity_lower_bound_bytes", "confirmed_at_utc",
    "confirmation_reference", "confirmation_statement",
}
_OPERATOR_FIELDS = {
    "basis", "available_capacity_lower_bound_bytes", "confirmed_at_utc",
    "confirmation_reference", "confirmation_statement_sha256",
    "authority_semantics", "quota_visibility",
}
_CAPABILITY_FIELDS = {
    "origin", "upload_token_sha256", "read_token_sha256",
    "capability_pair_sha256",
}
_DESTINATION_FIELDS = {
    "origin", "destination_id_sha256", "capability_pair_sha256",
    "destination_binding_sha256", "dedicated_namespace_claimed",
}
_PROJECTION_FIELDS = {
    "formula", "observed_cell_count", "observed_pair_archive_bytes",
    "observed_cells_sha256", "pair_receipts_sha256",
    "measurement_repeat_multiplier", "projected_remote_bytes",
    "safety_factor_numerator", "safety_factor_denominator", "reserve_bytes",
    "minimum_capacity_bytes", "required_capacity_bytes",
}
_TOP_FIELDS = {
    "schema_version", "artifact_kind", "status", "scope", "observed_at_utc",
    "capability_binding", "destination", "preflight_observation",
    "operator_capacity", "sizing_projection", "sha256",
}


class SeafileOperatorCapacityAttestationV2Error(RuntimeError):
    """The operator capacity, capability, sizing, or persisted proof is unsafe."""


def _fail(message: str) -> None:
    raise SeafileOperatorCapacityAttestationV2Error(message)


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError, RecursionError) as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            "operator capacity attestation is not canonical JSON"
        ) from error


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _nonnegative_int(value: Any, label: str, *, positive: bool = False) -> int:
    if type(value) is not int or value < 0 or (positive and value == 0):
        _fail(f"{label} must be {'positive' if positive else 'nonnegative'} integer")
    return value


def _timestamp(value: Any, label: str) -> str:
    if type(value) is not str or _UTC_RE.fullmatch(value) is None:
        _fail(f"{label} timestamp is invalid")
    return value


def _destination_id(value: Any) -> str:
    if type(value) is not str or value != value.strip() or _DESTINATION_RE.fullmatch(value) is None:
        _fail("Seafile destination ID must be a stable 8-128 character identifier")
    return value


def _links(upload_url: str, read_url: str) -> SeafileShareLinks:
    try:
        return SeafileShareLinks.from_urls(upload_url, read_url)
    except ArtifactStoreError as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            f"Seafile capability pair is invalid: {error}"
        ) from error


def _capability_binding(
    links: SeafileShareLinks, *, destination_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    capability: dict[str, Any] = {
        "origin": links.base_url,
        "upload_token_sha256": hashlib.sha256(
            links.upload_token.encode("ascii")
        ).hexdigest(),
        "read_token_sha256": hashlib.sha256(
            links.read_token.encode("ascii")
        ).hexdigest(),
    }
    capability["capability_pair_sha256"] = _canonical_sha(capability)
    destination_material = {
        "origin": links.base_url,
        "destination_id_sha256": hashlib.sha256(
            destination_id.encode("utf-8")
        ).hexdigest(),
        "capability_pair_sha256": capability["capability_pair_sha256"],
    }
    destination = {
        **destination_material,
        "destination_binding_sha256": _canonical_sha(destination_material),
        "dedicated_namespace_claimed": False,
    }
    return capability, destination


def _validate_preflight(value: Any, *, origin: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _PREFLIGHT_FIELDS:
        _fail("Seafile preflight fields drifted")
    if (
        value.get("schema_version") != 1
        or value.get("artifact_kind") != "vast_seafile_preflight"
        or value.get("status") != "ready"
        or value.get("transport") != "https"
        or value.get("origin") != origin
        or value.get("read_capability") != "verified"
        or value.get("upload_capability") not in {
            "verified_get_only", "verified_live_upload_readback",
        }
        or value.get("quota_visibility") != "not_exposed_by_share_link"
    ):
        _fail("Seafile preflight identity/origin/capability drifted")
    count = _nonnegative_int(value.get("remote_file_count"), "remote file count")
    size = _nonnegative_int(value.get("remote_size_bytes"), "remote size")
    if count == 0 and size != 0:
        _fail("Seafile preflight remote count/size relation drifted")
    return json.loads(_canonical_bytes(value).decode("ascii"))


def _validate_confirmation(value: Any) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _CONFIRMATION_FIELDS:
        _fail("operator confirmation fields drifted")
    lower_bound = _nonnegative_int(
        value.get("available_capacity_lower_bound_bytes"),
        "operator capacity lower bound", positive=True,
    )
    if lower_bound < MINIMUM_CAPACITY_BYTES:
        _fail("operator capacity lower bound is below 500 GiB")
    confirmed_at = _timestamp(value.get("confirmed_at_utc"), "operator confirmation")
    reference = value.get("confirmation_reference")
    statement = value.get("confirmation_statement")
    if (
        value.get("basis") != "operator_explicit_guarantee"
        or type(reference) is not str
        or _REFERENCE_RE.fullmatch(reference) is None
        or type(statement) is not str
        or statement != statement.strip()
        or not statement
        or len(statement) > 4096
    ):
        _fail("operator confirmation authority is incomplete")
    return {
        "basis": "operator_explicit_guarantee",
        "available_capacity_lower_bound_bytes": lower_bound,
        "confirmed_at_utc": confirmed_at,
        "confirmation_reference": reference,
        "confirmation_statement_sha256": hashlib.sha256(
            statement.encode("utf-8")
        ).hexdigest(),
        "authority_semantics": "available_bytes_lower_bound_not_api_quota",
        "quota_visibility": "not_exposed_by_share_link",
    }


def _validate_projection(value: Any, *, lower_bound: int) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _PROJECTION_FIELDS:
        _fail("operator capacity sizing projection fields drifted")
    observed = _nonnegative_int(
        value.get("observed_pair_archive_bytes"), "sizing observed bytes",
        positive=True,
    )
    projected = _nonnegative_int(
        value.get("projected_remote_bytes"), "sizing projected bytes",
        positive=True,
    )
    reserve = _nonnegative_int(value.get("reserve_bytes"), "sizing reserve")
    required = _nonnegative_int(
        value.get("required_capacity_bytes"), "sizing required capacity",
        positive=True,
    )
    expected_required = max(
        MINIMUM_CAPACITY_BYTES, (projected * 5 + 3) // 4 + reserve,
    )
    if (
        value.get("formula")
        != "max(500GiB,ceil(projected_remote_bytes*1.25)+5GiB)"
        or value.get("observed_cell_count") != 280
        or value.get("measurement_repeat_multiplier") != 10
        or projected != observed * 10
        or value.get("safety_factor_numerator") != 5
        or value.get("safety_factor_denominator") != 4
        or reserve != 5 * GIB
        or value.get("minimum_capacity_bytes") != MINIMUM_CAPACITY_BYTES
        or required != expected_required
        or any(
            _SHA_RE.fullmatch(str(value.get(field))) is None
            for field in ("observed_cells_sha256", "pair_receipts_sha256")
        )
    ):
        _fail("operator capacity sizing projection arithmetic/identity drifted")
    if lower_bound < required:
        _fail("operator capacity lower bound is below the physical sizing requirement")
    return json.loads(_canonical_bytes(value).decode("ascii"))


def build_seafile_operator_capacity_attestation_v2(
    *,
    preflight: Mapping[str, Any],
    upload_url: str,
    read_url: str,
    destination_id: str,
    observed_pair_archives: Sequence[Mapping[str, Any]],
    observed_at_utc: str,
    operator_confirmation: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a user/operator lower bound to live capabilities and Q4 sizing."""
    links = _links(upload_url, read_url)
    normalized_destination = _destination_id(destination_id)
    observed_at = _timestamp(observed_at_utc, "capacity observation")
    checked_preflight = _validate_preflight(preflight, origin=links.base_url)
    checked_confirmation = _validate_confirmation(operator_confirmation)
    if observed_at < checked_confirmation["confirmed_at_utc"]:
        _fail("capacity observation predates the operator confirmation")
    try:
        projection = build_sizing_projection(observed_pair_archives)
    except SeafileCapacityAttestationV1Error as error:
        raise SeafileOperatorCapacityAttestationV2Error(str(error)) from error
    projection = _validate_projection(
        projection,
        lower_bound=checked_confirmation["available_capacity_lower_bound_bytes"],
    )
    capability, destination = _capability_binding(
        links, destination_id=normalized_destination,
    )
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_kind": ARTIFACT_KIND,
        "status": STATUS,
        "scope": SCOPE,
        "observed_at_utc": observed_at,
        "capability_binding": capability,
        "destination": destination,
        "preflight_observation": checked_preflight,
        "operator_capacity": checked_confirmation,
        "sizing_projection": projection,
    }
    value["sha256"] = _canonical_sha(value)
    return validate_seafile_operator_capacity_attestation_v2(
        value,
        upload_url=upload_url,
        read_url=read_url,
        destination_id=normalized_destination,
    )


def validate_seafile_operator_capacity_attestation_v2(
    value: Any, *, upload_url: str, read_url: str, destination_id: str,
) -> dict[str, Any]:
    """Rehash and cross-bind a persisted v2 proof to the live link pair."""
    if type(value) is not dict or set(value) != _TOP_FIELDS:
        _fail("operator capacity attestation fields drifted")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("artifact_kind") != ARTIFACT_KIND
        or value.get("status") != STATUS
        or value.get("scope") != SCOPE
        or _UTC_RE.fullmatch(str(value.get("observed_at_utc", ""))) is None
        or _SHA_RE.fullmatch(str(value.get("sha256", ""))) is None
        or value.get("sha256") != _canonical_sha({
            key: child for key, child in value.items() if key != "sha256"
        })
    ):
        _fail("operator capacity attestation identity/self-hash drifted")
    links = _links(upload_url, read_url)
    normalized_destination = _destination_id(destination_id)
    capability, destination = _capability_binding(
        links, destination_id=normalized_destination,
    )
    if (
        type(value.get("capability_binding")) is not dict
        or set(value["capability_binding"]) != _CAPABILITY_FIELDS
        or value["capability_binding"] != capability
    ):
        _fail("operator capacity capability binding drifted")
    if (
        type(value.get("destination")) is not dict
        or set(value["destination"]) != _DESTINATION_FIELDS
        or value["destination"] != destination
    ):
        _fail("operator capacity destination binding drifted")
    _validate_preflight(value.get("preflight_observation"), origin=links.base_url)
    operator = value.get("operator_capacity")
    if type(operator) is not dict or set(operator) != _OPERATOR_FIELDS:
        _fail("operator capacity authority fields drifted")
    lower_bound = _nonnegative_int(
        operator.get("available_capacity_lower_bound_bytes"),
        "operator capacity lower bound", positive=True,
    )
    if (
        operator.get("basis") != "operator_explicit_guarantee"
        or operator.get("authority_semantics")
        != "available_bytes_lower_bound_not_api_quota"
        or operator.get("quota_visibility") != "not_exposed_by_share_link"
        or lower_bound < MINIMUM_CAPACITY_BYTES
        or _UTC_RE.fullmatch(str(operator.get("confirmed_at_utc", ""))) is None
        or _REFERENCE_RE.fullmatch(str(operator.get("confirmation_reference", ""))) is None
        or _SHA_RE.fullmatch(str(operator.get("confirmation_statement_sha256", ""))) is None
        or str(value["observed_at_utc"]) < str(operator["confirmed_at_utc"])
    ):
        _fail("operator capacity authority semantics drifted")
    _validate_projection(value.get("sizing_projection"), lower_bound=lower_bound)
    return json.loads(_canonical_bytes(value).decode("ascii"))


def write_immutable_attestation_v2(
    path: Path,
    value: Mapping[str, Any],
    *,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Durably publish once or adopt only one exact physical attestation."""

    destination = Path(os.path.abspath(os.fspath(path)))
    try:
        parent = destination.parent.resolve(strict=True)
    except OSError as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            f"operator attestation parent is unavailable: {error}"
        ) from error
    if not parent.is_dir() or destination.parent != parent:
        _fail("operator attestation output parent must be a physical directory")
    payload = _canonical_bytes(dict(value)) + b"\n"
    expected = {
        "path": destination.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    def physical_step(step: str) -> None:
        if after_physical_commit_step is not None:
            after_physical_commit_step(step, destination)

    try:
        with PhysicalRootCustodyV1.open(
            parent, label="Seafile operator capacity attestation parent"
        ) as custody:
            descriptor, identity, _disposition = (
                custody.commit_or_adopt_exact_identity(
                    destination.name,
                    payload,
                    label="Seafile operator capacity attestation",
                    mode=0o444,
                    create_parents=False,
                    after_publish_step=physical_step,
                )
            )
            cold_descriptor, cold_payload, cold_identity = (
                custody.read_descriptor_identity(
                    destination.name,
                    label="cold Seafile operator capacity attestation",
                    maximum=len(payload),
                    capture=True,
                )
            )
            cold_mode, cold_stat_identity = custody.stat_regular_identity(
                destination.name,
                label="cold Seafile operator capacity attestation",
            )
            if (
                descriptor != expected
                or cold_descriptor != expected
                or cold_payload != payload
                or cold_identity != identity
                or cold_stat_identity != identity
                or (
                    custody.permission_modes_enforced
                    and cold_mode != 0o444
                )
            ):
                _fail("immutable operator attestation changed across cold reload")
    except PublicationPhysicalIoV1Error as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            "immutable operator attestation collision"
        ) from error
    return {**expected, "path": str(destination)}


def materialize_seafile_operator_capacity_attestation_v2(
    *,
    project_root: Path | str,
    sizing_index_path: Path | str,
    output_path: Path | str,
    destination_id: str,
    observed_at_utc: str,
    operator_confirmation: Mapping[str, Any],
    links_file_path: Path | str,
    rows_loader: Callable[..., Sequence[Mapping[str, Any]]] | None = None,
    store_factory: Callable[[SeafileShareLinks], Any] = SeafileArtifactStore,
    after_physical_commit_step: Callable[[str, Path], None] | None = None,
) -> dict[str, Any]:
    """Consume project-root seafile.txt and physically load Q4 sizing evidence."""
    root_input = Path(project_root)
    if not root_input.is_dir() or root_input.is_symlink():
        _fail("operator attestation project root is unsafe")
    root = root_input.resolve(strict=True)
    source_input = Path(sizing_index_path)
    source = source_input if source_input.is_absolute() else root / source_input
    try:
        source = source.resolve(strict=True)
        source.relative_to(root)
    except (OSError, ValueError) as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            "operator attestation sizing index escapes or is unavailable"
        ) from error
    target_input = Path(output_path)
    target = target_input if target_input.is_absolute() else root / target_input
    try:
        target_parent = target.parent.resolve(strict=True)
        target_parent.relative_to(root)
    except (OSError, ValueError) as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            "operator attestation output parent escapes or is unavailable"
        ) from error
    if target.parent != target_parent or target.name in {"", ".", ".."}:
        _fail("operator attestation output path is unsafe")
    try:
        links_input = Path(links_file_path)
        links_candidate = (
            links_input if links_input.is_absolute() else root / links_input
        )
        try:
            links_lexical = Path(os.path.abspath(os.fspath(links_candidate)))
            links_parent = links_lexical.parent.resolve(strict=True)
            links_parent.relative_to(root)
        except (OSError, ValueError) as error:
            raise SeafileOperatorCapacityAttestationV2Error(
                "Seafile link file escapes or is unavailable"
            ) from error
        if (
            links_parent != links_lexical.parent
            or links_lexical != root / "seafile.txt"
            or links_lexical.name != "seafile.txt"
        ):
            _fail("production Seafile links must come only from project_root/seafile.txt")
        links = SeafileShareLinks.from_file(links_lexical)
    except ArtifactStoreError as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            f"Seafile capability input is invalid: {error}"
        ) from error
    finally:
        os.environ.pop("VAST_SEAFILE_UPLOAD_LINK", None)
        os.environ.pop("VAST_SEAFILE_READ_LINK", None)
    if rows_loader is None:
        from backend_pair_archive_sizing_receipts_v1 import (
            load_operator_sizing_rows_v1,
        )

        rows_loader = load_operator_sizing_rows_v1
    try:
        rows = rows_loader(project_root=root, index_path=source)
    except SeafileOperatorCapacityAttestationV2Error:
        raise
    except Exception as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            f"physical Q4 sizing rows are unavailable: {error}"
        ) from error
    try:
        preflight = store_factory(links).preflight(live_upload_readback=True)
    except (ArtifactStoreError, OSError) as error:
        raise SeafileOperatorCapacityAttestationV2Error(
            f"live Seafile preflight failed: {error}"
        ) from error
    value = build_seafile_operator_capacity_attestation_v2(
        preflight=preflight,
        upload_url=f"{links.base_url}/u/d/{links.upload_token}",
        read_url=f"{links.base_url}/d/{links.read_token}",
        destination_id=destination_id,
        observed_pair_archives=rows,
        observed_at_utc=observed_at_utc,
        operator_confirmation=operator_confirmation,
    )
    descriptor = write_immutable_attestation_v2(
        target,
        value,
        after_physical_commit_step=after_physical_commit_step,
    )
    return {
        "artifact_kind": "vast_seafile_operator_capacity_materialization_v2",
        "schema_version": SCHEMA_VERSION,
        "status": value["status"],
        "attestation": descriptor,
        "attestation_sha256": value["sha256"],
        "capacity_lower_bound_bytes": value["operator_capacity"][
            "available_capacity_lower_bound_bytes"
        ],
        "required_capacity_bytes": value["sizing_projection"][
            "required_capacity_bytes"
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    from_input = commands.add_parser("from-input")
    from_input.add_argument("--input-json", type=Path, required=True)
    from_input.add_argument("--output", type=Path, required=True)
    materialize = commands.add_parser("materialize")
    materialize.add_argument("--project-root", type=Path, required=True)
    materialize.add_argument("--sizing-index", type=Path, required=True)
    materialize.add_argument("--output", type=Path, required=True)
    materialize.add_argument("--destination-id", required=True)
    materialize.add_argument("--operator-lower-bound-bytes", type=int, required=True)
    materialize.add_argument("--confirmed-at-utc", required=True)
    materialize.add_argument("--observed-at-utc", required=True)
    materialize.add_argument("--confirmation-reference", required=True)
    materialize.add_argument("--confirmation-statement", required=True)
    materialize.add_argument("--links-file", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    arguments = _parse_args()
    if arguments.command == "from-input":
        try:
            inputs = json.loads(arguments.input_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise SeafileOperatorCapacityAttestationV2Error(
                f"invalid operator attestation input JSON: {error}"
            ) from error
        if type(inputs) is not dict:
            _fail("operator attestation input JSON must be an object")
        value = build_seafile_operator_capacity_attestation_v2(**inputs)
        descriptor = write_immutable_attestation_v2(arguments.output, value)
    else:
        descriptor = materialize_seafile_operator_capacity_attestation_v2(
            project_root=arguments.project_root,
            sizing_index_path=arguments.sizing_index,
            output_path=arguments.output,
            destination_id=arguments.destination_id,
            observed_at_utc=arguments.observed_at_utc,
            operator_confirmation={
                "basis": "operator_explicit_guarantee",
                "available_capacity_lower_bound_bytes": (
                    arguments.operator_lower_bound_bytes
                ),
                "confirmed_at_utc": arguments.confirmed_at_utc,
                "confirmation_reference": arguments.confirmation_reference,
                "confirmation_statement": arguments.confirmation_statement,
            },
            links_file_path=arguments.links_file,
        )
    print(json.dumps(descriptor, sort_keys=True, separators=(",", ":")))
    return 0


__all__ = [
    "ARTIFACT_KIND", "GIB", "SCHEMA_VERSION", "SCOPE", "STATUS",
    "SeafileOperatorCapacityAttestationV2Error",
    "build_seafile_operator_capacity_attestation_v2",
    "materialize_seafile_operator_capacity_attestation_v2",
    "validate_seafile_operator_capacity_attestation_v2",
    "write_immutable_attestation_v2",
]


if __name__ == "__main__":
    raise SystemExit(main())
