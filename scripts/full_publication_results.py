#!/usr/bin/env python3
"""Deterministic compact export from locally retained accepted pair manifests."""

from __future__ import annotations

import csv
from contextlib import contextmanager
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

try:  # pragma: no cover - selected by the host platform
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

try:  # pragma: no cover - selected by the host platform
    import msvcrt
except ImportError:  # pragma: no cover - POSIX fallback
    msvcrt = None

from benchmark_contract import ContractError
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


_QUALIFICATION_AUTHORITY_FIELDS = frozenset({
    "identity_artifact_binding_sha256",
    "resource_capability_grant_sha256",
    "backend_runtime_grant_sha256",
    "model_parity_grant_sha256",
    "model_parity_acceptance_binding_sha256",
})
_RESULT_NAMES = (
    "full_pairs.jsonl",
    "full_arms.jsonl",
    "full_arms.csv",
    "result_bundle_manifest.json",
)
_RESULT_MANIFEST_NAME = _RESULT_NAMES[-1]
_INTENT_ROOT = ".full-publication-results-intents-v1"
_LOCK_PAYLOAD = b"vast-full-publication-results-bundle-lock-v1\n"

ResultPhysicalFault = Callable[[str, Path], None]


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


def _inside(root: Path, path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise ContractError(f"{label} escaped the finalized run root") from None
    if not relative.parts:
        raise ContractError(f"{label} must not equal the finalized run root")
    return resolved


def _lexical_descendant(root: Path, path: Path, *, label: str) -> tuple[Path, str]:
    absolute = Path(os.path.abspath(os.fspath(path)))
    try:
        relative = absolute.relative_to(root).as_posix()
    except ValueError:
        raise ContractError(f"{label} escaped the finalized run root") from None
    if not relative or relative == ".":
        raise ContractError(f"{label} must not equal the finalized run root")
    return absolute, relative


def _file_identity(info: os.stat_result) -> tuple[int, int]:
    return int(info.st_dev), int(info.st_ino)


@contextmanager
def _exclusive_bundle_lock(
    path: Path,
    *,
    expected_identity: tuple[int, int],
) -> Iterator[None]:
    """Hold one persistent non-causal coordination leaf for the bundle."""

    flags = os.O_RDWR | int(getattr(os, "O_CLOEXEC", 0))
    flags |= int(getattr(os, "O_NOFOLLOW", 0))
    if os.name == "nt":  # pragma: no cover - WSL is the production host
        flags |= int(getattr(os, "O_BINARY", 0))
    descriptor = -1
    locked = False
    try:
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        named = path.lstat()
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or stat.S_ISLNK(named.st_mode)
            or int(opened.st_nlink) != 1
            or int(named.st_nlink) != 1
            or _file_identity(opened) != expected_identity
            or _file_identity(named) != expected_identity
            or int(opened.st_size) != len(_LOCK_PAYLOAD)
        ):
            raise ContractError("compact result bundle lock identity drifted")
        if fcntl is not None:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        elif msvcrt is not None:  # pragma: no cover - Windows fallback
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:  # pragma: no cover - unsupported host
            raise ContractError("compact result bundle lock is unavailable")
        locked = True
        reopened = path.lstat()
        if (
            not stat.S_ISREG(reopened.st_mode)
            or stat.S_ISLNK(reopened.st_mode)
            or int(reopened.st_nlink) != 1
            or _file_identity(reopened) != expected_identity
            or _file_identity(os.fstat(descriptor)) != expected_identity
        ):
            raise ContractError("compact result bundle lock was rebound")
        yield
    except ContractError:
        raise
    except OSError as error:
        raise ContractError("compact result bundle lock failed") from error
    finally:
        if descriptor >= 0:
            if locked:
                try:
                    if fcntl is not None:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                    elif msvcrt is not None:  # pragma: no cover - Windows fallback
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            try:
                os.close(descriptor)
            except OSError:
                pass


def _commit_result_leaf(
    custody: PhysicalRootCustodyV1,
    relative: str,
    path: Path,
    payload: bytes,
    *,
    label: str,
    after_physical_commit_step: ResultPhysicalFault | None,
) -> tuple[dict[str, Any], tuple[int, int]]:
    def physical_step(step: str) -> None:
        if after_physical_commit_step is not None:
            after_physical_commit_step(step, path)

    descriptor, identity, _disposition = custody.commit_or_adopt_exact_identity(
        relative,
        payload,
        label=label,
        mode=0o444,
        create_parents=False,
        after_publish_step=physical_step,
    )
    cold_descriptor, cold_payload, cold_identity = custody.read_descriptor_identity(
        relative,
        label=f"cold {label}",
        maximum=len(payload),
        capture=True,
    )
    cold_mode, cold_stat_identity = custody.stat_regular_identity(
        relative,
        label=f"cold {label}",
    )
    if (
        cold_descriptor != descriptor
        or cold_payload != payload
        or cold_identity != identity
        or cold_stat_identity != identity
        or (
            custody.permission_modes_enforced
            and cold_mode != 0o444
        )
    ):
        raise ContractError(f"{label} changed across physical cold reload")
    return descriptor, identity


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
    after_physical_commit_step: ResultPhysicalFault | None = None,
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

    data_payloads = {
        "full_pairs.jsonl": pair_payload,
        "full_arms.jsonl": arm_payload,
        "full_arms.csv": csv_payload,
    }
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
            for name, payload in sorted(data_payloads.items())
        },
    }
    manifest_payload = _canonical_json(bundle) + b"\n"
    payloads = {
        **data_payloads,
        _RESULT_MANIFEST_NAME: manifest_payload,
    }
    destination_value = (
        Path(output_root) if output_root is not None else run_root / "results"
    )
    destination, destination_relative = _lexical_descendant(
        run_root,
        destination_value,
        label="compact result output",
    )
    intent_key = hashlib.sha256(destination_relative.encode("utf-8")).hexdigest()
    intent_relative = f"{_INTENT_ROOT}/{intent_key}.json"
    intent_path = run_root / Path(intent_relative)
    lock_relative = f"{_INTENT_ROOT}/.bundle.lock"
    lock_path = run_root / Path(lock_relative)
    intent = {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_compact_result_materialization_intent",
        "destination_relative_path": destination_relative,
        "matrix_identity": snapshot["matrix_identity"],
        "run_identity": snapshot["run_identity"],
        "source_finalization_sha256": bundle["source_finalization_sha256"],
        "receipt_last": _RESULT_MANIFEST_NAME,
        "files": {
            name: {
                "sha256": _sha256_bytes(payload),
                "size_bytes": len(payload),
            }
            for name, payload in sorted(payloads.items())
        },
    }
    intent_payload = _canonical_json(intent) + b"\n"

    try:
        with PhysicalRootCustodyV1.open(
            run_root, label="compact result finalized run root"
        ) as custody:
            custody.ensure_directory_owned(
                _INTENT_ROOT,
                label="compact result intent root",
            )
            _lock_descriptor, lock_identity, _lock_disposition = (
                custody.commit_or_adopt_exact_identity(
                    lock_relative,
                    _LOCK_PAYLOAD,
                    label="compact result bundle lock",
                    mode=0o600,
                    create_parents=False,
                )
            )
            with _exclusive_bundle_lock(
                lock_path,
                expected_identity=lock_identity,
            ):
                destination_preexisted = os.path.lexists(destination)
                intent_preexisted = os.path.lexists(intent_path)
                if destination_preexisted and not intent_preexisted:
                    raise ContractError(
                        "compact result output exists without its exact materialization intent"
                    )

                def intent_step(step: str) -> None:
                    if after_physical_commit_step is not None:
                        after_physical_commit_step(step, intent_path)

                _intent_descriptor, intent_identity, intent_disposition = (
                    custody.commit_or_adopt_exact_identity(
                        intent_relative,
                        intent_payload,
                        label="compact result materialization intent",
                        mode=0o444,
                        create_parents=False,
                        after_publish_step=intent_step,
                    )
                )
                _destination_path, created_directories = (
                    custody.ensure_directory_owned(
                        destination_relative,
                        label="compact result output",
                    )
                )
                destination_created = any(
                    path == destination_relative
                    for path, _identity in created_directories
                )
                if (
                    not destination_preexisted
                    and intent_disposition == "published"
                    and not destination_created
                ):
                    custody.unlink_owned_identity(
                        intent_relative,
                        intent_identity,
                        label="raced compact result materialization intent",
                    )
                    raise ContractError(
                        "compact result output was created by a foreign racer"
                    )
                destination_mode, _destination_identity = (
                    custody.stat_directory_identity(
                        destination_relative,
                        label="compact result output",
                    )
                )
                if destination_mode != 0o700:
                    raise ContractError("compact result output mode drifted")
                existing = set(
                    custody.list_directory_names(
                        destination_relative,
                        label="compact result output",
                    )
                )
                expected_names = set(_RESULT_NAMES)
                if not existing <= expected_names:
                    raise ContractError("compact result output contains foreign entries")
                if _RESULT_MANIFEST_NAME in existing and existing != expected_names:
                    raise ContractError(
                        "compact result manifest exists before its complete payload set"
                    )

                committed: dict[str, tuple[dict[str, Any], tuple[int, int]]] = {}
                for name in _RESULT_NAMES:
                    payload = payloads[name]
                    committed[name] = _commit_result_leaf(
                        custody,
                        f"{destination_relative}/{name}",
                        destination / name,
                        payload,
                        label=f"compact result {name}",
                        after_physical_commit_step=after_physical_commit_step,
                    )
                final_names = set(
                    custody.list_directory_names(
                        destination_relative,
                        label="completed compact result output",
                    )
                )
                if final_names != expected_names:
                    raise ContractError("compact result output did not close exactly")
                for name, (descriptor, identity) in committed.items():
                    cold_descriptor, cold_payload, cold_identity = (
                        custody.read_descriptor_identity(
                            f"{destination_relative}/{name}",
                            label=f"closed compact result {name}",
                            maximum=len(payloads[name]),
                            capture=True,
                        )
                    )
                    if (
                        cold_descriptor != descriptor
                        or cold_payload != payloads[name]
                        or cold_identity != identity
                    ):
                        raise ContractError(
                            f"compact result {name} changed before bundle close"
                        )
    except PublicationPhysicalIoV1Error as error:
        raise ContractError(f"compact result physical namespace rejected: {error}") from error
    return bundle


__all__ = ["ResultPhysicalFault", "export_finalized_results"]
