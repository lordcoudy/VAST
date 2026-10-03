#!/usr/bin/env python3
"""Snapshot failed guardian diagnostics without granting benchmark readiness.

Successful guardian lifecycles remain the sole input to the qualification
closure.  This collector is for preserving a bounded, failed guardian's
forensic evidence so a later non-authorizing preparation handoff can describe
the blocker without rewriting historical lifecycle v1 documents.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping


from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
    canonical_relative_path_v1,
)


AUTHORITY_FILENAME = "service_authority.v1.json"
LIFECYCLE_FILENAME = "service_lifecycle.v1.json"
DIAGNOSTIC_FILENAME = "protocol_failure_diagnostic.v1.json"
MAX_DIAGNOSTIC_BYTES = 8192
MAX_DOCUMENT_BYTES = 4 * 1024 * 1024
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_DIAGNOSTIC_SUFFIX_RE = re.compile(
    r"; protocol_diagnostic=(protocol_failure_diagnostic\.v1\.json); sha256=([0-9a-f]{64})$"
)


class BenchmarkPreparationEvidenceV1Error(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BenchmarkPreparationEvidenceV1Error(message)


def _canonical_bytes(value: Any) -> bytes:
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


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)[:-1]).hexdigest()


def _physical_directory(value: Path | str, *, label: str) -> Path:
    supplied = Path(os.path.abspath(os.fspath(value)))
    try:
        info = supplied.lstat()
        resolved = supplied.resolve(strict=True)
    except OSError as error:
        raise BenchmarkPreparationEvidenceV1Error(f"{label} is unavailable") from error
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    _require(
        supplied == resolved
        and stat.S_ISDIR(info.st_mode)
        and not stat.S_ISLNK(info.st_mode)
        and not bool(int(getattr(info, "st_file_attributes", 0)) & reparse),
        f"{label} is unsafe",
    )
    return resolved

def _sha256(value: object, *, label: str) -> str:
    _require(type(value) is str and _SHA256_RE.fullmatch(value) is not None, f"{label} is invalid")
    return value


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping), f"{label} is not an object")
    return dict(value)


def _read_canonical_mapping(
    custody: PhysicalRootCustodyV1,
    relative: str,
    *,
    maximum: int,
    label: str,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    descriptor, payload = custody.read_descriptor(
        relative, label=label, maximum=maximum, capture=True
    )
    _require(payload is not None, f"{label} payload was not captured")
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise BenchmarkPreparationEvidenceV1Error(f"{label} is not canonical JSON") from error
    result = _mapping(value, label=label)
    _require(payload == _canonical_bytes(result), f"{label} is not canonical JSON")
    return result, descriptor, payload


def _validate_authority_lifecycle(
    authority: Mapping[str, Any],
    authority_descriptor: Mapping[str, Any],
    lifecycle: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    checked_authority = _mapping(authority, label="guardian authority")
    authority_sha = _sha256(
        checked_authority.get("service_authority_sha256"),
        label="guardian authority self hash",
    )
    authority_core = {
        key: value for key, value in checked_authority.items() if key != "service_authority_sha256"
    }
    _require(
        authority_sha == _canonical_sha256(authority_core),
        "guardian authority self hash drifted",
    )
    lifecycle_id = checked_authority.get("lifecycle_id")
    service_identity = _sha256(
        checked_authority.get("service_identity_sha256"),
        label="guardian service identity",
    )
    _require(type(lifecycle_id) is str and bool(lifecycle_id), "guardian lifecycle id is invalid")

    checked_lifecycle = _mapping(lifecycle, label="guardian lifecycle")
    _require(
        checked_lifecycle.get("schema_version") == 1
        and checked_lifecycle.get("artifact_kind")
        == "vast_gstreamer_analytics_production_service_lifecycle_v1"
        and checked_lifecycle.get("status") == "failed_stop_nonpublication"
        and checked_lifecycle.get("lifecycle_id") == lifecycle_id
        and checked_lifecycle.get("service_identity_sha256") == service_identity
        and checked_lifecycle.get("service_authority_sha256") == authority_sha,
        "guardian failed lifecycle authority binding drifted",
    )
    readiness = _mapping(
        checked_lifecycle.get("readiness_artifact"), label="guardian lifecycle readiness descriptor"
    )
    _require(
        set(readiness) == {"path", "size_bytes", "sha256"}
        and type(readiness["path"]) is str
        and Path(readiness["path"]).name == AUTHORITY_FILENAME
        and readiness["size_bytes"] == authority_descriptor["size_bytes"]
        and readiness["sha256"] == authority_descriptor["sha256"],
        "guardian lifecycle readiness descriptor drifted",
    )
    identity = _mapping(checked_lifecycle.get("identity"), label="guardian lifecycle identity")
    _require(
        set(identity) == {"algorithm", "sha256"}
        and identity.get("algorithm") == "sha256"
        and identity.get("sha256")
        == _canonical_sha256({key: value for key, value in checked_lifecycle.items() if key != "identity"}),
        "guardian lifecycle self hash drifted",
    )
    failure = _mapping(checked_lifecycle.get("failure"), label="guardian lifecycle failure")
    _require(
        set(failure) == {"type", "message"}
        and type(failure["type"]) is str
        and type(failure["message"]) is str,
        "guardian lifecycle failure schema drifted",
    )
    return checked_authority, checked_lifecycle


def _validate_diagnostic(
    diagnostic: Mapping[str, Any], *, authority: Mapping[str, Any], lifecycle: Mapping[str, Any]
) -> dict[str, Any]:
    checked = _mapping(diagnostic, label="guardian protocol diagnostic")
    expected_fields = {
        "schema_version", "artifact_kind", "lifecycle_id", "service_authority_sha256",
        "observed_at_utc", "protocol_mode", "attribution", "request_id", "run_id",
        "arm_id", "branch", "resource", "expected", "observed", "failure_stage", "identity",
    }
    _require(set(checked) == expected_fields, "guardian protocol diagnostic schema drifted")
    _require(
        checked["schema_version"] == 1
        and checked["artifact_kind"] == "vast_gstreamer_analytics_protocol_failure_diagnostic_v1"
        and checked["lifecycle_id"] == lifecycle["lifecycle_id"]
        and checked["service_authority_sha256"] == authority["service_authority_sha256"]
        and checked["protocol_mode"] in {None, "gstreamer", "worker"}
        and checked["attribution"] in {"validated", "unavailable"}
        and type(checked["failure_stage"]) is str
        and bool(checked["failure_stage"]),
        "guardian protocol diagnostic authority binding drifted",
    )
    observed_at = checked["observed_at_utc"]
    _require(type(observed_at) is str and len(observed_at) <= 64, "guardian diagnostic observation time is invalid")
    try:
        parsed_time = datetime.fromisoformat(observed_at)
    except ValueError as error:
        raise BenchmarkPreparationEvidenceV1Error("guardian diagnostic observation time is invalid") from error
    _require(parsed_time.tzinfo is not None and parsed_time.utcoffset() == timedelta(0), "guardian diagnostic observation time is not UTC")
    for field in ("expected", "observed"):
        values = _mapping(checked[field], label=f"guardian diagnostic {field} facts")
        _require(set(values) == {"byte_length", "sha256", "seals"}, f"guardian diagnostic {field} facts drifted")
        _require(
            values["byte_length"] is None or (type(values["byte_length"]) is int and values["byte_length"] >= 0),
            f"guardian diagnostic {field} byte length is invalid",
        )
        _require(values["sha256"] is None or (type(values["sha256"]) is str and _SHA256_RE.fullmatch(values["sha256"]) is not None), f"guardian diagnostic {field} hash is invalid")
        _require(values["seals"] is None or (type(values["seals"]) is int and values["seals"] >= 0), f"guardian diagnostic {field} seals are invalid")
    for field in ("request_id", "run_id", "arm_id", "branch", "resource"):
        _require(checked[field] is None or type(checked[field]) is str, f"guardian diagnostic {field} is invalid")
    if checked["attribution"] == "unavailable":
        _require(
            all(checked[field] is None for field in ("request_id", "run_id", "arm_id", "branch", "resource")),
            "unattributed guardian diagnostic retained request facts",
        )
    identity = _mapping(checked["identity"], label="guardian protocol diagnostic identity")
    _require(
        set(identity) == {"algorithm", "sha256"}
        and identity.get("algorithm") == "sha256"
        and identity.get("sha256") == _canonical_sha256({key: value for key, value in checked.items() if key != "identity"}),
        "guardian protocol diagnostic self hash drifted",
    )
    return checked


def snapshot_failed_guardian_evidence(
    guardian_root: Path | str,
    output_dir: Path | str,
    *,
    lifecycle_path: Path | str | None = None,
) -> dict[str, Any]:
    """Create immutable copies for one failed guardian diagnostic.

    ``output_dir`` is the new final snapshot directory.  Historical failed
    lifecycles without the diagnostic suffix return an explicit missing result
    and do not create it.  This helper never produces readiness or grant data.
    """

    root = _physical_directory(guardian_root, label="guardian evidence root")
    supplied_target = Path(os.path.abspath(os.fspath(output_dir)))
    target_parent = _physical_directory(supplied_target.parent, label="guardian snapshot parent")
    target = target_parent / supplied_target.name
    _require(target.name not in {"", ".", ".."}, "evidence snapshot output path is invalid")
    source_custody: PhysicalRootCustodyV1 | None = None
    output_custody: PhysicalRootCustodyV1 | None = None
    try:
        source_custody = PhysicalRootCustodyV1.open(root, label="failed guardian evidence root")
        output_custody = PhysicalRootCustodyV1.open(target.parent, label="failed guardian snapshot parent")
    except PublicationPhysicalIoV1Error as error:
        if source_custody is not None:
            source_custody.close()
        raise BenchmarkPreparationEvidenceV1Error("guardian evidence root or output parent is unsafe") from error
    try:
        if lifecycle_path is None:
            lifecycle_relative = LIFECYCLE_FILENAME
        else:
            try:
                supplied_lifecycle = Path(os.path.abspath(os.fspath(lifecycle_path)))
                lifecycle_relative = canonical_relative_path_v1(
                    supplied_lifecycle.relative_to(root).as_posix(),
                    label="guardian lifecycle path",
                )
            except ValueError as error:
                raise BenchmarkPreparationEvidenceV1Error(
                    "guardian lifecycle path escaped the evidence root"
                ) from error
        _require(
            lifecycle_relative == LIFECYCLE_FILENAME,
            "guardian lifecycle path must be the canonical lifecycle leaf",
        )
        authority, authority_descriptor, authority_payload = _read_canonical_mapping(
            source_custody, AUTHORITY_FILENAME, maximum=MAX_DOCUMENT_BYTES, label="guardian authority"
        )
        lifecycle, lifecycle_descriptor, lifecycle_payload = _read_canonical_mapping(
            source_custody, lifecycle_relative, maximum=MAX_DOCUMENT_BYTES, label="guardian lifecycle"
        )
        authority, lifecycle = _validate_authority_lifecycle(authority, authority_descriptor, lifecycle)
        failure_message = lifecycle["failure"]["message"]
        suffix = _DIAGNOSTIC_SUFFIX_RE.search(failure_message)
        if suffix is None:
            _require(
                "protocol_diagnostic" not in failure_message,
                "guardian lifecycle diagnostic marker is malformed",
            )
            return {
                "status": "historical_diagnostic_missing",
                "non_authorizing": True,
                "snapshot_directory": None,
                "source_descriptors": {
                    "authority": authority_descriptor,
                    "lifecycle": lifecycle_descriptor,
                    "diagnostic": None,
                },
            }
        diagnostic_relative, lifecycle_hash = suffix.groups()
        diagnostic_relative = canonical_relative_path_v1(diagnostic_relative, label="guardian diagnostic")
        _require(diagnostic_relative == DIAGNOSTIC_FILENAME, "guardian diagnostic filename drifted")
        diagnostic, diagnostic_descriptor, diagnostic_payload = _read_canonical_mapping(
            source_custody,
            diagnostic_relative,
            maximum=MAX_DIAGNOSTIC_BYTES,
            label="guardian protocol diagnostic",
        )
        _require(
            diagnostic_descriptor["sha256"] == lifecycle_hash,
            "guardian lifecycle diagnostic hash drifted",
        )
        _validate_diagnostic(diagnostic, authority=authority, lifecycle=lifecycle)
        _require(not os.path.lexists(target), "guardian evidence snapshot output already exists")
        target_name = canonical_relative_path_v1(target.name, label="guardian evidence snapshot output")
        for name, payload in (
            (AUTHORITY_FILENAME, authority_payload),
            (LIFECYCLE_FILENAME, lifecycle_payload),
            (DIAGNOSTIC_FILENAME, diagnostic_payload),
        ):
            output_custody.write_exclusive(
                f"{target_name}/{name}", payload,
                label=f"failed guardian evidence copy {name}", mode=0o444,
            )
        descriptors: dict[str, dict[str, Any]] = {}
        for key, name, maximum in (
            ("authority", AUTHORITY_FILENAME, MAX_DOCUMENT_BYTES),
            ("lifecycle", LIFECYCLE_FILENAME, MAX_DOCUMENT_BYTES),
            ("diagnostic", DIAGNOSTIC_FILENAME, MAX_DIAGNOSTIC_BYTES),
        ):
            descriptor, _payload = output_custody.read_descriptor(
                f"{target_name}/{name}", label=f"published guardian {key}", maximum=maximum, capture=False
            )
            descriptors[key] = descriptor
        return {
            "status": "failed_guardian_diagnostic_snapshotted",
            "non_authorizing": True,
            "snapshot_directory": str(target),
            "descriptors": descriptors,
        }
    except PublicationPhysicalIoV1Error as error:
        raise BenchmarkPreparationEvidenceV1Error("guardian evidence physical custody failed") from error
    finally:
        if source_custody is not None:
            source_custody.close()
        if output_custody is not None:
            output_custody.close()


__all__ = [
    "AUTHORITY_FILENAME",
    "BenchmarkPreparationEvidenceV1Error",
    "DIAGNOSTIC_FILENAME",
    "LIFECYCLE_FILENAME",
    "MAX_DIAGNOSTIC_BYTES",
    "snapshot_failed_guardian_evidence",
]
