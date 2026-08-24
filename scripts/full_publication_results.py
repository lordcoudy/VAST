#!/usr/bin/env python3
"""Deterministic compact export from locally retained accepted pair manifests."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from benchmark_contract import ContractError


_QUALIFICATION_AUTHORITY_FIELDS = frozenset({
    "identity_artifact_binding_sha256",
    "resource_capability_grant_sha256",
    "backend_runtime_grant_sha256",
    "model_parity_grant_sha256",
    "model_parity_acceptance_binding_sha256",
})


def _qualification_authorities(value: Any) -> dict[str, str]:
    if (
        type(value) is not dict
        or set(value) != _QUALIFICATION_AUTHORITY_FIELDS
        or any(
            type(item) is not str
            or len(item) != 64
            or any(character not in "0123456789abcdef" for character in item)
            for item in value.values()
        )
    ):
        raise ContractError(
            "compact pair qualification authorities are invalid"
        )
    return dict(value)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ContractError(f"compact result is not canonical JSON: {error}") from error


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _immutable_write(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise ContractError(f"compact result collision: {path.name}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _inside(root: Path, path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ContractError(f"{label} escaped the finalized run root") from None
    if not relative.parts:
        raise ContractError(f"{label} must not equal the finalized run root")
    return resolved


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ContractError(f"{label} is not a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid {label}: {error}") from error
    if type(value) is not dict:
        raise ContractError(f"invalid {label}: expected an object")
    _canonical_json(value)
    return value


def _flatten(prefix: str, value: Mapping[str, Any], row: dict[str, Any]) -> None:
    for key in sorted(value):
        item = value[key]
        name = f"{prefix}{key}"
        if item is None or type(item) in {bool, int, float, str}:
            row[name] = item
        else:
            row[name] = _canonical_json(item).decode("utf-8")


def export_finalized_results(
    runner: Any,
    *,
    output_root: Path | str | None = None,
) -> dict[str, Any]:
    """Export compact long-form artifacts without downloading pruned raw evidence."""

    run_root = Path(runner.run_root).resolve()
    snapshot = runner.finalized_snapshot()
    if (
        type(snapshot) is not dict
        or snapshot.get("artifact_kind")
        != "vast_full_publication_finalized_snapshot"
    ):
        raise ContractError("runner did not return a finalized publication snapshot")
    matrix = snapshot.get("matrix")
    records = snapshot.get("verified_pairs")
    if type(matrix) is not dict or type(records) is not list:
        raise ContractError("finalized publication snapshot schema drifted")
    pairs = matrix.get("pairs")
    if (
        type(pairs) is not list
        or matrix.get("expected_pairs") != len(pairs)
        or matrix.get("expected_arms") != len(pairs) * 2
        or len(records) != len(pairs)
    ):
        raise ContractError("finalized publication snapshot cardinality drifted")

    accepted_root = (run_root / "accepted_pairs").resolve()
    pair_lines: list[bytes] = []
    arm_lines: list[bytes] = []
    csv_rows: list[dict[str, Any]] = []
    matrix_sha = str((snapshot.get("matrix_identity") or {}).get("sha256", ""))
    run_sha = str((snapshot.get("run_identity") or {}).get("sha256", ""))

    for sequence, (pair, record) in enumerate(zip(pairs, records, strict=True)):
        if (
            type(pair) is not dict
            or type(record) is not dict
            or record.get("sequence") != sequence
            or record.get("pair_id") != pair.get("pair_id")
        ):
            raise ContractError("finalized verified pair order drifted")
        decision = record.get("acceptance")
        if type(decision) is not dict:
            raise ContractError("verified pair lacks compact acceptance identity")
        relative = decision.get("compact_acceptance_relative_path")
        expected_sha = decision.get("acceptance_manifest_sha256")
        if type(relative) is not str or type(expected_sha) is not str:
            raise ContractError("verified pair compact acceptance identity is invalid")
        compact_path = _inside(
            run_root, run_root / relative, label="compact pair acceptance"
        )
        try:
            compact_path.relative_to(accepted_root)
        except ValueError:
            raise ContractError("compact pair acceptance escaped accepted_pairs") from None
        if _sha256_file(compact_path) != expected_sha:
            raise ContractError("compact pair acceptance hash drift")
        acceptance = _read_object(compact_path, label="compact pair acceptance")
        expected_identity = {
            "schema_version": 2,
            "artifact_kind": "vast_full_publication_pair_acceptance",
            "status": "accepted",
            "matrix_sha256": matrix_sha,
            "run_id": run_sha,
            "pair_sequence": sequence,
            "pair_id": pair["pair_id"],
        }
        for field, expected in expected_identity.items():
            actual = acceptance.get(field)
            if type(actual) is not type(expected) or actual != expected:
                raise ContractError(f"compact pair acceptance identity drift: {field}")
        qualification_authorities = _qualification_authorities(
            acceptance.get("qualification_authorities")
        )
        pair_gates = acceptance.get("pair_gates")
        if (
            type(pair_gates) is not dict
            or pair_gates.get(
                "common_identity_and_qualification_authorities"
            ) is not True
        ):
            raise ContractError(
                "compact pair qualification authority gate is not accepted"
            )
        expected_arms = pair.get("arms")
        accepted_arms = acceptance.get("arms")
        if (
            type(expected_arms) is not list
            or len(expected_arms) != 2
            or type(accepted_arms) is not list
            or len(accepted_arms) != 2
        ):
            raise ContractError("compact pair acceptance arm cardinality drifted")
        accepted_by_id = {
            str(value.get("arm_id")): value
            for value in accepted_arms
            if type(value) is dict
        }
        if set(accepted_by_id) != {
            str(value.get("arm_id")) for value in expected_arms
        }:
            raise ContractError("compact pair acceptance arm identity drifted")

        pair_lines.append(_canonical_json(acceptance) + b"\n")
        for expected_arm in expected_arms:
            arm_id = str(expected_arm["arm_id"])
            accepted_arm = accepted_by_id[arm_id]
            if _qualification_authorities(
                accepted_arm.get("qualification_authorities")
            ) != qualification_authorities:
                raise ContractError(
                    "compact accepted arm qualification authorities drifted"
                )
            result = accepted_arm.get("result")
            arm_summary = accepted_arm.get("arm_acceptance_summary")
            resource_summary = accepted_arm.get("full_resource_summary")
            if (
                type(result) is not dict
                or result.get("status") != "completed"
                or type(arm_summary) is not dict
                or type(resource_summary) is not dict
            ):
                raise ContractError("compact accepted arm result schema drifted")
            arm_payload = {
                "sequence": sequence,
                "pair_id": pair["pair_id"],
                "arm": expected_arm,
                "accepted": accepted_arm,
            }
            arm_lines.append(_canonical_json(arm_payload) + b"\n")
            row: dict[str, Any] = {
                "sequence": sequence,
                "pair_id": pair["pair_id"],
                "arm_id": arm_id,
            }
            _flatten("", expected_arm, row)
            _flatten("result_", result, row)
            _flatten("acceptance_", arm_summary, row)
            _flatten("resource_", resource_summary, row)
            csv_rows.append(row)

    destination = Path(output_root) if output_root is not None else run_root / "results"
    destination = _inside(run_root, destination, label="compact result output")
    if destination.exists() and (destination.is_symlink() or not destination.is_dir()):
        raise ContractError("compact result output is not a regular directory")
    destination.mkdir(parents=True, exist_ok=True)

    pair_payload = b"".join(pair_lines)
    arm_payload = b"".join(arm_lines)
    fields = sorted({field for row in csv_rows for field in row})
    with tempfile.TemporaryFile(mode="w+", newline="", encoding="utf-8") as temporary:
        writer = csv.DictWriter(
            temporary, fieldnames=fields, extrasaction="raise", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(csv_rows)
        temporary.seek(0)
        csv_payload = temporary.read().encode("utf-8")

    payloads = {
        "full_pairs.jsonl": pair_payload,
        "full_arms.jsonl": arm_payload,
        "full_arms.csv": csv_payload,
    }
    for name, payload in payloads.items():
        _immutable_write(destination / name, payload)
    bundle = {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_compact_result_bundle",
        "matrix_identity": snapshot["matrix_identity"],
        "run_identity": snapshot["run_identity"],
        "verified_pairs": len(pair_lines),
        "verified_arms": len(arm_lines),
        "source_finalization_sha256": _sha256_bytes(
            _canonical_json(snapshot["finalization"])
        ),
        "files": {
            name: {
                "sha256": _sha256_bytes(payload),
                "size_bytes": len(payload),
            }
            for name, payload in sorted(payloads.items())
        },
    }
    _immutable_write(
        destination / "result_bundle_manifest.json",
        _canonical_json(bundle) + b"\n",
    )
    return bundle


__all__ = ["export_finalized_results"]
