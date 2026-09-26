#!/usr/bin/env python3
"""Fail-closed orchestration state machine for the full publication matrix.

The module intentionally knows nothing about benchmark, acceptance, or cloud
implementations.  Those effects are injected as callbacks.  A pair becomes
resumable progress only after both arms pass acceptance and the cloud callback
returns a verified receipt.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping

from benchmark_contract import ContractError
from publication_matrix import build_full_publication_matrix, publication_matrix_identity
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


RUN_MANIFEST_SCHEMA_VERSION = 1
CHECKPOINT_SCHEMA_VERSION = 2
FINALIZATION_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_WINDOWS_REPLACE_RETRY_DELAYS_S = (0.01, 0.025, 0.05, 0.1, 0.2)
_WINDOWS_RETRYABLE_REPLACE_ERRORS = frozenset({5, 32, 33})
_IMMUTABLE_INTENT_ROOT = ".full-publication-runner-immutable-intents-v1"
_CLOUD_RECEIPT_FIELDS = frozenset(
    {
        "state",
        "matrix_sha256",
        "run_id",
        "pair_sequence",
        "pair_id",
        "acceptance_sha256",
        "archive_remote_name",
        "archive_sha256",
        "archive_size_bytes",
        "receipt_remote_name",
        "receipt_sha256",
        "receipt_size_bytes",
        "local_archive_path",
        "local_receipt_path",
        "ledger_entry_sha256",
    }
)


class ExitCode(IntEnum):
    """Supervisor-facing process semantics."""

    COMPLETE = 0
    TRANSIENT = 75
    PERMANENT = 78


class RunError(RuntimeError):
    """Base class for explicitly classified orchestration failures."""


class TransientRunError(RunError):
    """The same frozen run may be retried later."""


class PermanentRunError(RunError):
    """The frozen run must stop and requires operator intervention."""


class IdentityDriftError(PermanentRunError):
    """Current inputs differ from the immutable run manifest."""


class RunRootLockedError(TransientRunError):
    """Another process or thread owns the run root."""


@dataclass(frozen=True)
class CallbackDecision:
    """Result returned by preflight and scientific pair acceptance callbacks."""

    accepted: bool
    details: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    retryable: bool = False

    @classmethod
    def passed(cls, details: Mapping[str, Any] | None = None) -> "CallbackDecision":
        return cls(accepted=True, details={} if details is None else details)

    @classmethod
    def rejected(
        cls,
        reason: str,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool = False,
    ) -> "CallbackDecision":
        return cls(
            accepted=False,
            details={} if details is None else details,
            reason=reason,
            retryable=retryable,
        )


@dataclass(frozen=True)
class CloudTransactionReceipt:
    """Durable result of upload plus remote read-back verification."""

    verified: bool
    details: Mapping[str, Any] = field(default_factory=dict)
    reason: str = ""
    retryable: bool = True

    @classmethod
    def verified_receipt(
        cls, details: Mapping[str, Any]
    ) -> "CloudTransactionReceipt":
        return cls(verified=True, details=details, retryable=False)

    @classmethod
    def unverified(
        cls,
        reason: str,
        *,
        details: Mapping[str, Any] | None = None,
        retryable: bool = True,
    ) -> "CloudTransactionReceipt":
        return cls(
            verified=False,
            details={} if details is None else details,
            reason=reason,
            retryable=retryable,
        )


@dataclass(frozen=True)
class RunContext:
    run_root: Path
    matrix_identity: Mapping[str, Any]
    run_identity: Mapping[str, Any]
    next_sequence: int
    total_pairs: int
    recovering_accepted_pair: bool = False


@dataclass(frozen=True)
class PairContext:
    run: RunContext
    sequence: int
    pair: Mapping[str, Any]
    attempt: int


@dataclass(frozen=True)
class ArmContext:
    pair_context: PairContext
    arm_index: int
    arm: Mapping[str, Any]

    @property
    def sequence(self) -> int:
        return self.pair_context.sequence

    @property
    def attempt(self) -> int:
        return self.pair_context.attempt


PreflightCallback = Callable[[RunContext], CallbackDecision]
ArmExecutor = Callable[[ArmContext], Any]
PairAcceptanceCallback = Callable[
    [PairContext, tuple[Any, Any]], CallbackDecision
]
CloudTransactionCallback = Callable[
    [PairContext, CallbackDecision], CloudTransactionReceipt
]
CloudVerificationCallback = Callable[
    [PairContext, CloudTransactionReceipt], CloudTransactionReceipt
]


@dataclass(frozen=True)
class RunnerCallbacks:
    preflight: PreflightCallback
    execute_arm: ArmExecutor
    accept_pair: PairAcceptanceCallback
    cloud_transaction: CloudTransactionCallback
    verify_cloud: CloudVerificationCallback
    before_pair: Callable[[PairContext], CallbackDecision] | None = None


@dataclass(frozen=True)
class RunResult:
    exit_code: ExitCode
    status: str
    completed_pairs: int
    completed_arms: int
    total_pairs: int
    total_arms: int
    next_sequence: int | None
    message: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        raise ContractError(f"value is not canonical JSON: {error}") from error


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _strict_json_copy(value: Any, *, label: str) -> Any:
    """Copy JSON while rejecting Python-only values accepted by json.dumps."""

    def validate(item: Any, path: str) -> None:
        if item is None or type(item) in {bool, int, str}:
            return
        if type(item) is float:
            if not math.isfinite(item):
                raise ContractError(f"{label} is not strict JSON at {path}")
            return
        if type(item) is list:
            for index, child in enumerate(item):
                validate(child, f"{path}[{index}]")
            return
        if type(item) is dict:
            for key, child in item.items():
                if type(key) is not str:
                    raise ContractError(f"{label} has a non-string key at {path}")
                validate(child, f"{path}.{key}")
            return
        raise ContractError(f"{label} is not strict JSON at {path}")

    validate(value, "$")
    return _json_copy(value)


def _strict_json_object(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ContractError(f"{label} must be a JSON object")
    copied = _strict_json_copy(value, label=label)
    if type(copied) is not dict:  # pragma: no cover - guarded above
        raise ContractError(f"{label} must be a JSON object")
    return copied


def _identity(value: Any) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "sha256": hashlib.sha256(_canonical_json(value)).hexdigest(),
    }


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise ContractError(f"invalid {label}: expected a JSON object")
    return value


def _is_windows_runtime() -> bool:
    return os.name == "nt"


def _replace_atomic_file(source: Path, destination: Path) -> None:
    """Bound known transient Windows sharing races without masking other failures."""

    for delay_s in (*_WINDOWS_REPLACE_RETRY_DELAYS_S, None):
        try:
            os.replace(source, destination)
            return
        except OSError as error:
            retryable = (
                _is_windows_runtime()
                and getattr(error, "winerror", None)
                in _WINDOWS_RETRYABLE_REPLACE_ERRORS
                and delay_s is not None
            )
            if not retryable:
                raise
            time.sleep(delay_s)


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    """Write canonical JSON with same-directory replace and file fsync."""

    payload = _canonical_json(value) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        _replace_atomic_file(temporary_path, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            except OSError:
                pass
            finally:
                os.close(directory_descriptor)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


class FullPublicationRunner:
    """Transactional executor for immutable, ordered two-arm publication pairs."""

    MANIFEST_NAME = "run_manifest.json"
    CHECKPOINT_NAME = "checkpoint.json"
    FINALIZATION_NAME = "finalization.json"
    LOCK_NAME = ".full_publication.lock"

    def __init__(
        self,
        run_root: Path | str,
        *,
        config: Mapping[str, Any],
        identity_inputs: Mapping[str, Any],
        callbacks: RunnerCallbacks | None = None,
        matrix_builder: Callable[[dict[str, Any]], dict[str, Any]] = (
            build_full_publication_matrix
        ),
        immutable_artifact_physical_fault: (
            Callable[[str, Path], None] | None
        ) = None,
    ) -> None:
        self.run_root = Path(run_root)
        self.config = _json_copy(config)
        self.identity_inputs = _json_copy(identity_inputs)
        self.callbacks = callbacks
        self.matrix_builder = matrix_builder
        self.immutable_artifact_physical_fault = immutable_artifact_physical_fault

    @property
    def manifest_path(self) -> Path:
        return self.run_root / self.MANIFEST_NAME

    @property
    def checkpoint_path(self) -> Path:
        return self.run_root / self.CHECKPOINT_NAME

    @property
    def finalization_path(self) -> Path:
        return self.run_root / self.FINALIZATION_NAME

    @property
    def lock_path(self) -> Path:
        return self.run_root / self.LOCK_NAME

    def _immutable_intent_path(self, target: Path) -> Path:
        return self.run_root / _IMMUTABLE_INTENT_ROOT / target.name

    def _commit_immutable_json(
        self,
        path: Path,
        value: Mapping[str, Any],
        *,
        label: str,
        expose_fault: bool,
        mode: int,
    ) -> tuple[int, int]:
        payload = _canonical_json(value) + b"\n"
        try:
            relative = path.relative_to(self.run_root).as_posix()
        except ValueError:
            raise ContractError(f"{label} escaped run_root") from None

        def physical_step(step: str) -> None:
            if expose_fault and self.immutable_artifact_physical_fault is not None:
                self.immutable_artifact_physical_fault(step, path)

        try:
            with PhysicalRootCustodyV1.open(
                self.run_root, label="full publication immutable run_root"
            ) as custody:
                descriptor, identity, _disposition = (
                    custody.commit_or_adopt_exact_identity(
                        relative,
                        payload,
                        label=label,
                        mode=mode,
                        create_parents=True,
                        after_publish_step=(physical_step if expose_fault else None),
                    )
                )
                expected = {
                    "path": relative,
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                cold_descriptor, cold_payload, cold_identity = (
                    custody.read_descriptor_identity(
                        relative,
                        label=f"cold {label}",
                        maximum=len(payload),
                        capture=True,
                    )
                )
                cold_mode, cold_stat_identity = custody.stat_regular_identity(
                    relative,
                    label=f"cold {label}",
                )
                if (
                    descriptor != expected
                    or cold_descriptor != expected
                    or cold_payload != payload
                    or cold_identity != identity
                    or cold_stat_identity != identity
                    or (
                        custody.permission_modes_enforced
                        and cold_mode != mode
                    )
                ):
                    raise ContractError(f"{label} changed across cold reload")
                return identity
        except PublicationPhysicalIoV1Error as error:
            raise ContractError(f"{label} immutable collision") from error

    def _load_or_create_immutable_intent(
        self,
        target: Path,
        candidate: Mapping[str, Any],
        *,
        label: str,
    ) -> dict[str, Any]:
        intent_path = self._immutable_intent_path(target)
        intended = (
            _read_json(intent_path, label=f"{label} materialization intent")
            if intent_path.exists()
            else _strict_json_object(candidate, label=f"{label} intent candidate")
        )
        self._commit_immutable_json(
            intent_path,
            intended,
            label=f"{label} materialization intent",
            expose_fault=False,
            mode=0o444,
        )
        return intended

    @contextmanager
    def _exclusive_run_root_lock(self) -> Iterator[None]:
        self.run_root.mkdir(parents=True, exist_ok=True)
        handle = self.lock_path.open("a+b")
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt

                handle.seek(0, os.SEEK_END)
                if handle.tell() == 0:
                    handle.write(b"\0")
                    handle.flush()
                    os.fsync(handle.fileno())
                handle.seek(0)
                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError as error:
                    raise RunRootLockedError(
                        f"full publication run root is locked: {self.run_root}"
                    ) from error
            else:
                import fcntl

                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except OSError as error:
                    raise RunRootLockedError(
                        f"full publication run root is locked: {self.run_root}"
                    ) from error
            acquired = True
            yield
        finally:
            if acquired:
                try:
                    if os.name == "nt":
                        import msvcrt

                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
            else:
                handle.close()

    def plan(self) -> dict[str, Any]:
        matrix = self._current_matrix()
        matrix_identity = publication_matrix_identity(matrix)
        run_identity = self._run_identity(matrix_identity, self.identity_inputs)
        return {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_execution_plan",
            "matrix_identity": matrix_identity,
            "run_identity": run_identity,
            "expected_pairs": matrix["expected_pairs"],
            "expected_arms": matrix["expected_arms"],
            "pairs": [
                {
                    "sequence": sequence,
                    "pair_id": pair["pair_id"],
                    "arm_ids": [arm["arm_id"] for arm in pair["arms"]],
                }
                for sequence, pair in enumerate(matrix["pairs"])
            ],
        }

    def run(self) -> RunResult:
        try:
            with self._exclusive_run_root_lock():
                return self._run_locked()
        except RunRootLockedError as error:
            return self._unopened_error_result(ExitCode.TRANSIENT, str(error))

    def _run_locked(self) -> RunResult:
        checkpoint: dict[str, Any] | None = None
        manifest: dict[str, Any] | None = None
        try:
            manifest, checkpoint = self._initialize_or_resume()
            total_pairs = int(manifest["matrix"]["expected_pairs"])

            if checkpoint["state"] in {"complete", "finalized"}:
                return self._result(checkpoint, manifest, ExitCode.COMPLETE)
            if checkpoint["state"] == "failed_permanent":
                return self._result(
                    checkpoint,
                    manifest,
                    ExitCode.PERMANENT,
                    str((checkpoint.get("last_error") or {}).get("message", "")),
                )
            if self.callbacks is None:
                raise PermanentRunError("runner callbacks are not configured")

            prefix = int(checkpoint["verified_prefix_length"])
            inflight = checkpoint.get("inflight")
            run_context = self._run_context(
                manifest, next_sequence=prefix,
                recovering_accepted_pair=(
                    isinstance(inflight, dict)
                    and inflight.get("phase") == "accepted"
                    and inflight.get("sequence") == prefix
                ),
            )
            preflight = self._require_decision(
                self.callbacks.preflight(run_context), callback_name="preflight"
            )
            if not preflight.accepted:
                self._raise_rejected(preflight, "preflight rejected the frozen run")

            for sequence in range(prefix, total_pairs):
                pair = manifest["matrix"]["pairs"][sequence]
                previous_inflight = checkpoint.get("inflight")
                if (
                    isinstance(previous_inflight, dict)
                    and previous_inflight.get("phase") == "accepted"
                    and previous_inflight.get("sequence") == sequence
                ):
                    attempt = int(previous_inflight["attempt"])
                    acceptance_details = _strict_json_object(
                        previous_inflight["acceptance"],
                        label="durable pair acceptance",
                    )
                    acceptance = CallbackDecision.passed(acceptance_details)
                else:
                    if self.callbacks.before_pair is not None:
                        admission = self._require_decision(
                            self.callbacks.before_pair(self._pair_context(
                                manifest, sequence=sequence,
                                attempt=(int(previous_inflight["attempt"])
                                         if isinstance(previous_inflight, dict) else 1),
                            )),
                            callback_name="before_pair",
                        )
                        if not admission.accepted:
                            self._raise_rejected(admission, "pair admission rejected")
                    if (
                        isinstance(previous_inflight, dict)
                        and previous_inflight.get("phase") == "executing"
                        and previous_inflight.get("sequence") == sequence
                    ):
                        attempt = int(previous_inflight["attempt"])
                    else:
                        attempt = 1
                        checkpoint["state"] = "running"
                        checkpoint["inflight"] = self._executing_inflight_identity(
                            pair,
                            sequence=sequence,
                            attempt=attempt,
                        )
                        checkpoint["last_error"] = None
                        self._write_checkpoint(checkpoint)

                    arm_results: list[Any] = []
                    for arm_index, arm in enumerate(pair["arms"]):
                        inflight = checkpoint.get("inflight")
                        if (
                            type(inflight) is not dict
                            or inflight.get("phase") != "executing"
                        ):
                            raise PermanentRunError(
                                "executing pair lost its durable arm state"
                            )
                        arm_states = inflight.get("arm_states")
                        if type(arm_states) is not list or len(arm_states) != 2:
                            raise PermanentRunError(
                                "executing pair has invalid durable arm state"
                            )
                        arm_state = arm_states[arm_index]
                        if arm_state.get("state") == "committed":
                            arm_results.append(
                                _strict_json_copy(
                                    arm_state["result"],
                                    label="durable arm result",
                                )
                            )
                            continue
                        if arm_state.get("state") not in {"pending", "executing"}:
                            raise PermanentRunError(
                                "executing pair has an invalid arm transition"
                            )
                        if arm_state["state"] == "pending":
                            arm_state["state"] = "executing"
                            checkpoint["state"] = "running"
                            checkpoint["last_error"] = None
                            self._write_checkpoint(checkpoint)
                        raw_arm_result = self.callbacks.execute_arm(
                            ArmContext(
                                pair_context=self._pair_context(
                                    manifest, sequence=sequence, attempt=attempt
                                ),
                                arm_index=arm_index,
                                arm=copy.deepcopy(arm),
                            )
                        )
                        arm_result = _strict_json_copy(
                            raw_arm_result,
                            label="execute_arm callback result",
                        )
                        arm_state["state"] = "committed"
                        arm_state["result"] = copy.deepcopy(arm_result)
                        arm_state["result_sha256"] = _identity(arm_result)["sha256"]
                        checkpoint["state"] = "running"
                        checkpoint["last_error"] = None
                        self._write_checkpoint(checkpoint)
                        arm_results.append(arm_result)
                    if len(arm_results) != 2:
                        raise PermanentRunError(
                            "pair executor did not produce exactly two arms"
                        )

                    acceptance = self._require_decision(
                        self.callbacks.accept_pair(
                            self._pair_context(
                                manifest, sequence=sequence, attempt=attempt
                            ),
                            (arm_results[0], arm_results[1]),
                        ),
                        callback_name="accept_pair",
                    )
                    if not acceptance.accepted:
                        self._raise_rejected(
                            acceptance,
                            f"pair {pair['pair_id']} failed scientific acceptance",
                        )
                    acceptance_details = self._require_acceptance_manifest_hash(
                        acceptance.details
                    )
                    accepted_inflight = self._inflight_identity(
                        pair, sequence=sequence, attempt=attempt, phase="accepted"
                    )
                    accepted_inflight["acceptance"] = copy.deepcopy(
                        acceptance_details
                    )
                    accepted_inflight["acceptance_sha256"] = _identity(
                        acceptance_details
                    )["sha256"]
                    checkpoint["inflight"] = accepted_inflight
                    checkpoint["last_error"] = None
                    self._write_checkpoint(checkpoint)
                    acceptance = CallbackDecision.passed(
                        copy.deepcopy(acceptance_details)
                    )

                cloud_callback_context = self._pair_context(
                    manifest, sequence=sequence, attempt=attempt
                )
                cloud_value = self.callbacks.cloud_transaction(
                    cloud_callback_context,
                    CallbackDecision.passed(copy.deepcopy(acceptance_details)),
                )
                cloud_receipt = self._require_cloud_receipt(
                    cloud_value,
                    context=self._pair_context(
                        manifest, sequence=sequence, attempt=attempt
                    ),
                    acceptance_details=acceptance_details,
                    callback_name="cloud_transaction",
                )

                record = self._verified_pair_record(
                    self._pair_context(manifest, sequence=sequence, attempt=attempt),
                    CallbackDecision.passed(copy.deepcopy(acceptance_details)),
                    cloud_receipt,
                )
                checkpoint["verified_pairs"].append(record)
                checkpoint["verified_prefix_length"] = sequence + 1
                checkpoint["inflight"] = None
                checkpoint["state"] = (
                    "complete" if sequence + 1 == total_pairs else "running"
                )
                checkpoint["last_error"] = None
                self._write_checkpoint(checkpoint)

            return self._result(checkpoint, manifest, ExitCode.COMPLETE)
        except TransientRunError as error:
            if checkpoint is not None and manifest is not None:
                self._record_failure(checkpoint, error, transient=True)
                return self._result(
                    checkpoint, manifest, ExitCode.TRANSIENT, str(error)
                )
            return self._unopened_error_result(ExitCode.TRANSIENT, str(error))
        except (PermanentRunError, ContractError) as error:
            if checkpoint is not None and manifest is not None:
                self._record_failure(checkpoint, error, transient=False)
                return self._result(
                    checkpoint, manifest, ExitCode.PERMANENT, str(error)
                )
            return self._unopened_error_result(ExitCode.PERMANENT, str(error))
        except Exception as error:
            classified = PermanentRunError(
                f"unclassified runner failure: {type(error).__name__}: {error}"
            )
            if checkpoint is not None and manifest is not None:
                self._record_failure(checkpoint, classified, transient=False)
                return self._result(
                    checkpoint, manifest, ExitCode.PERMANENT, str(classified)
                )
            return self._unopened_error_result(ExitCode.PERMANENT, str(classified))

    def status(self) -> dict[str, Any]:
        with self._exclusive_run_root_lock():
            return self._status_locked()

    def _status_locked(self) -> dict[str, Any]:
        manifest, checkpoint = self._load_existing()
        total_pairs = int(manifest["matrix"]["expected_pairs"])
        prefix = int(checkpoint["verified_prefix_length"])
        state = str(checkpoint["state"])
        if state in {"complete", "finalized"}:
            exit_code = ExitCode.COMPLETE
        elif state == "failed_permanent":
            exit_code = ExitCode.PERMANENT
        else:
            exit_code = ExitCode.TRANSIENT
        return {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_status",
            "state": state,
            "exit_code": int(exit_code),
            "matrix_identity": copy.deepcopy(manifest["matrix_identity"]),
            "run_identity": copy.deepcopy(manifest["run_identity"]),
            "completed_pairs": prefix,
            "completed_arms": prefix * 2,
            "total_pairs": total_pairs,
            "total_arms": total_pairs * 2,
            "next_sequence": prefix if prefix < total_pairs else None,
            "inflight": copy.deepcopy(checkpoint.get("inflight")),
            "resumable": state in {"initialized", "running", "paused_transient"},
            "last_error": copy.deepcopy(checkpoint.get("last_error")),
        }

    def verify(self) -> dict[str, Any]:
        with self._exclusive_run_root_lock():
            return self._verify_locked()

    def _verify_locked(self) -> dict[str, Any]:
        manifest, checkpoint = self._load_existing()
        total_pairs = int(manifest["matrix"]["expected_pairs"])
        prefix = int(checkpoint["verified_prefix_length"])
        finalization = None
        if self.finalization_path.exists():
            finalization = _read_json(
                self.finalization_path, label="full publication finalization"
            )
            self._validate_finalization(finalization, manifest, checkpoint)
        return {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_verification",
            "passed": True,
            "complete": prefix == total_pairs,
            "finalized": finalization is not None,
            "state": checkpoint["state"],
            "matrix_identity": copy.deepcopy(manifest["matrix_identity"]),
            "run_identity": copy.deepcopy(manifest["run_identity"]),
            "verified_pairs": prefix,
            "verified_arms": prefix * 2,
            "expected_pairs": total_pairs,
            "expected_arms": total_pairs * 2,
            "verified_pairs_sha256": _identity(checkpoint["verified_pairs"])[
                "sha256"
            ],
        }

    def finalize(self) -> dict[str, Any]:
        with self._exclusive_run_root_lock():
            return self._finalize_locked()

    def finalized_snapshot(self) -> dict[str, Any]:
        """Return validated compact inputs for deterministic result export."""

        with self._exclusive_run_root_lock():
            manifest, checkpoint = self._load_existing()
            if checkpoint.get("state") != "finalized" or not self.finalization_path.is_file():
                raise ContractError("full publication results require a finalized run")
            finalization = _read_json(
                self.finalization_path, label="full publication finalization"
            )
            self._validate_finalization(finalization, manifest, checkpoint)
            return {
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_finalized_snapshot",
                "matrix_identity": copy.deepcopy(manifest["matrix_identity"]),
                "run_identity": copy.deepcopy(manifest["run_identity"]),
                "matrix": copy.deepcopy(manifest["matrix"]),
                "verified_pairs": copy.deepcopy(checkpoint["verified_pairs"]),
                "finalization": copy.deepcopy(finalization),
            }

    def _finalize_locked(self) -> dict[str, Any]:
        manifest, checkpoint = self._load_existing()
        total_pairs = int(manifest["matrix"]["expected_pairs"])
        if (
            int(checkpoint["verified_prefix_length"]) != total_pairs
            or checkpoint["state"] not in {"complete", "finalized"}
        ):
            raise ContractError("cannot finalize incomplete run")

        if checkpoint["state"] == "finalized":
            finalization = _read_json(
                self.finalization_path, label="full publication finalization"
            )
            self._validate_finalization(finalization, manifest, checkpoint)
            return copy.deepcopy(finalization)

        if self.callbacks is None:
            raise PermanentRunError(
                "runner callbacks are required for remote finalization verification"
            )
        for sequence, record in enumerate(checkpoint["verified_pairs"]):
            acceptance_details = _strict_json_object(
                record["acceptance"], label="checkpoint pair acceptance"
            )
            stored_details = _strict_json_object(
                record["cloud_receipt"], label="checkpoint cloud receipt"
            )
            callback_context = self._pair_context(
                manifest,
                sequence=sequence,
                attempt=int(record["attempt"]),
            )
            remote_value = self.callbacks.verify_cloud(
                callback_context,
                CloudTransactionReceipt.verified_receipt(
                    copy.deepcopy(stored_details)
                ),
            )
            remotely_verified = self._require_cloud_receipt(
                remote_value,
                context=self._pair_context(
                    manifest,
                    sequence=sequence,
                    attempt=int(record["attempt"]),
                ),
                acceptance_details=acceptance_details,
                callback_name="verify_cloud",
            )
            if _canonical_json(remotely_verified.details) != _canonical_json(
                stored_details
            ):
                raise PermanentRunError(
                    f"remote cloud receipt drift for pair {record['pair_id']}"
                )

        verified_pairs_sha256 = _identity(checkpoint["verified_pairs"])["sha256"]
        remote_verification_sha256 = _identity(
            self._remote_verification_material(checkpoint["verified_pairs"])
        )["sha256"]
        candidate_finalization = {
            "schema_version": FINALIZATION_SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_finalization",
            "verified": True,
            "matrix_identity": copy.deepcopy(manifest["matrix_identity"]),
            "run_identity": copy.deepcopy(manifest["run_identity"]),
            "verified_pairs": total_pairs,
            "verified_arms": total_pairs * 2,
            "verified_pairs_sha256": verified_pairs_sha256,
            "remote_verified_pairs": total_pairs,
            "remote_verification_sha256": remote_verification_sha256,
            "finalized_at": _utc_now(),
        }
        finalization_preexisted = self.finalization_path.exists()
        if finalization_preexisted:
            existing_finalization = _read_json(
                self.finalization_path, label="full publication finalization"
            )
            self._validate_finalization(existing_finalization, manifest, checkpoint)
            finalization_seed = existing_finalization
        else:
            finalization_seed = candidate_finalization
        finalization = self._load_or_create_immutable_intent(
            self.finalization_path,
            finalization_seed,
            label="full publication finalization",
        )
        self._validate_finalization(finalization, manifest, checkpoint)
        if finalization_preexisted and finalization != existing_finalization:
            raise ContractError("full publication finalization intent drift")
        self._commit_immutable_json(
            self.finalization_path,
            finalization,
            label="full publication finalization",
            expose_fault=True,
            mode=0o600,
        )

        checkpoint["state"] = "finalized"
        checkpoint["last_error"] = None
        checkpoint["inflight"] = None
        self._write_checkpoint(checkpoint)
        return copy.deepcopy(finalization)

    def _current_matrix(self) -> dict[str, Any]:
        try:
            matrix = self.matrix_builder(copy.deepcopy(self.config))
        except ContractError:
            raise
        except Exception as error:
            raise ContractError(f"cannot build full publication matrix: {error}") from error
        self._validate_matrix(matrix)
        return _json_copy(matrix)

    @staticmethod
    def _validate_matrix(matrix: Any) -> None:
        if not isinstance(matrix, dict):
            raise ContractError("full publication matrix must be a mapping")
        pairs = matrix.get("pairs")
        if not isinstance(pairs, list):
            raise ContractError("full publication matrix pairs must be a list")
        expected_pairs = matrix.get("expected_pairs")
        expected_arms = matrix.get("expected_arms")
        if expected_pairs != len(pairs):
            raise ContractError("full publication matrix pair cardinality drift")
        if expected_arms != len(pairs) * 2:
            raise ContractError("full publication matrix arm cardinality drift")

        pair_ids: set[str] = set()
        arm_ids: set[str] = set()
        for sequence, pair in enumerate(pairs):
            if not isinstance(pair, dict):
                raise ContractError(f"matrix pair {sequence} must be a mapping")
            pair_id = pair.get("pair_id")
            if not isinstance(pair_id, str) or not pair_id:
                raise ContractError(f"matrix pair {sequence} has no pair_id")
            if pair_id in pair_ids:
                raise ContractError(f"duplicate matrix pair_id: {pair_id}")
            pair_ids.add(pair_id)
            arms = pair.get("arms")
            if not isinstance(arms, list) or len(arms) != 2:
                raise ContractError(f"matrix pair {pair_id} must contain exactly two arms")
            pair_arm_ids: list[str] = []
            for arm in arms:
                if not isinstance(arm, dict):
                    raise ContractError(f"matrix pair {pair_id} arm must be a mapping")
                arm_id = arm.get("arm_id")
                if not isinstance(arm_id, str) or not arm_id:
                    raise ContractError(f"matrix pair {pair_id} has an arm without arm_id")
                if arm_id in arm_ids:
                    raise ContractError(f"duplicate matrix arm_id: {arm_id}")
                arm_ids.add(arm_id)
                pair_arm_ids.append(arm_id)
            if len(set(pair_arm_ids)) != 2:
                raise ContractError(f"matrix pair {pair_id} arm IDs are not unique")

    @staticmethod
    def _run_identity(
        matrix_identity: Mapping[str, Any], identity_inputs: Mapping[str, Any]
    ) -> dict[str, Any]:
        return _identity(
            {
                "schema_version": 1,
                "matrix_identity": matrix_identity,
                "identity_inputs": identity_inputs,
            }
        )

    def _candidate_manifest(self) -> dict[str, Any]:
        matrix = self._current_matrix()
        matrix_identity = publication_matrix_identity(matrix)
        run_identity = self._run_identity(matrix_identity, self.identity_inputs)
        return {
            "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_run_manifest",
            "created_at": _utc_now(),
            "matrix": matrix,
            "matrix_identity": matrix_identity,
            "identity_inputs": copy.deepcopy(self.identity_inputs),
            "run_identity": run_identity,
        }

    def _initialize_or_resume(self) -> tuple[dict[str, Any], dict[str, Any]]:
        candidate = self._candidate_manifest()
        self.run_root.mkdir(parents=True, exist_ok=True)
        manifest_preexisted = self.manifest_path.exists()
        if manifest_preexisted:
            existing_manifest = _read_json(
                self.manifest_path, label="full publication run manifest"
            )
            self._validate_manifest(existing_manifest, candidate=candidate)
            manifest_seed = existing_manifest
        else:
            if self.checkpoint_path.exists() or self.finalization_path.exists():
                raise ContractError("run state exists without an immutable run manifest")
            manifest_seed = candidate
        manifest = self._load_or_create_immutable_intent(
            self.manifest_path,
            manifest_seed,
            label="full publication run manifest",
        )
        self._validate_manifest(manifest, candidate=candidate)
        if manifest_preexisted and manifest != existing_manifest:
            raise ContractError("full publication run manifest intent drift")
        self._commit_immutable_json(
            self.manifest_path,
            manifest,
            label="full publication run manifest",
            expose_fault=True,
            mode=0o600,
        )

        if self.checkpoint_path.exists():
            checkpoint = _read_json(
                self.checkpoint_path, label="full publication checkpoint"
            )
            self._validate_checkpoint(checkpoint, manifest)
        else:
            checkpoint = self._initial_checkpoint(manifest)
            self._write_checkpoint(checkpoint)
        self._validate_existing_finalization(manifest, checkpoint)
        return manifest, checkpoint

    def _load_existing(self) -> tuple[dict[str, Any], dict[str, Any]]:
        if not self.manifest_path.exists() or not self.checkpoint_path.exists():
            raise ContractError("full publication run is not initialized")
        candidate = self._candidate_manifest()
        manifest = _read_json(self.manifest_path, label="full publication run manifest")
        self._validate_manifest(manifest, candidate=candidate)
        checkpoint = _read_json(
            self.checkpoint_path, label="full publication checkpoint"
        )
        self._validate_checkpoint(checkpoint, manifest)
        self._validate_existing_finalization(manifest, checkpoint)
        return manifest, checkpoint

    def _validate_existing_finalization(
        self,
        manifest: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
    ) -> None:
        if not self.finalization_path.exists():
            return
        finalization = _read_json(
            self.finalization_path, label="full publication finalization"
        )
        self._validate_finalization(finalization, manifest, checkpoint)

    def _validate_manifest(
        self,
        manifest: Mapping[str, Any],
        *,
        candidate: Mapping[str, Any],
    ) -> None:
        if manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION:
            raise ContractError("full publication run manifest schema drift")
        if manifest.get("artifact_kind") != "vast_full_publication_run_manifest":
            raise ContractError("invalid full publication run manifest artifact kind")
        matrix = manifest.get("matrix")
        self._validate_matrix(matrix)
        actual_matrix_identity = publication_matrix_identity(matrix)
        if manifest.get("matrix_identity") != actual_matrix_identity:
            raise ContractError("stored full publication matrix identity is invalid")
        actual_run_identity = self._run_identity(
            actual_matrix_identity, manifest.get("identity_inputs") or {}
        )
        if manifest.get("run_identity") != actual_run_identity:
            raise ContractError("stored full publication run identity is invalid")
        if candidate["matrix_identity"] != manifest["matrix_identity"]:
            raise IdentityDriftError("matrix identity drift detected")
        if candidate["run_identity"] != manifest["run_identity"]:
            raise IdentityDriftError("run identity drift detected")

    @staticmethod
    def _initial_checkpoint(manifest: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_checkpoint",
            "matrix_identity_sha256": manifest["matrix_identity"]["sha256"],
            "run_identity_sha256": manifest["run_identity"]["sha256"],
            "state": "initialized",
            "verified_prefix_length": 0,
            "verified_pairs": [],
            "inflight": None,
            "last_error": None,
            "updated_at": _utc_now(),
        }

    def _validate_checkpoint(
        self, checkpoint: Mapping[str, Any], manifest: Mapping[str, Any]
    ) -> None:
        if checkpoint.get("schema_version") != CHECKPOINT_SCHEMA_VERSION:
            raise ContractError("full publication checkpoint schema drift")
        if checkpoint.get("artifact_kind") != "vast_full_publication_checkpoint":
            raise ContractError("invalid full publication checkpoint artifact kind")
        if checkpoint.get("matrix_identity_sha256") != manifest["matrix_identity"][
            "sha256"
        ]:
            raise ContractError("checkpoint matrix identity drift")
        if checkpoint.get("run_identity_sha256") != manifest["run_identity"]["sha256"]:
            raise ContractError("checkpoint run identity drift")
        state = checkpoint.get("state")
        if state not in {
            "initialized",
            "running",
            "paused_transient",
            "failed_permanent",
            "complete",
            "finalized",
        }:
            raise ContractError("invalid full publication checkpoint state")

        records = checkpoint.get("verified_pairs")
        prefix = checkpoint.get("verified_prefix_length")
        if type(records) is not list or type(prefix) is not int:
            raise ContractError("invalid contiguous verified prefix metadata")
        if prefix != len(records):
            raise ContractError("checkpoint does not contain a contiguous verified prefix")
        pairs = manifest["matrix"]["pairs"]
        if prefix < 0 or prefix > len(pairs):
            raise ContractError("checkpoint contiguous verified prefix is out of range")
        for expected_sequence, record in enumerate(records):
            if (
                type(record) is not dict
                or type(record.get("sequence")) is not int
                or record.get("sequence") != expected_sequence
            ):
                raise ContractError("checkpoint does not contain a contiguous verified prefix")
            expected_pair = pairs[expected_sequence]
            if record.get("pair_id") != expected_pair["pair_id"]:
                raise ContractError("checkpoint verified pair order drift")
            if record.get("pair_sha256") != _identity(expected_pair)["sha256"]:
                raise ContractError("checkpoint verified pair identity drift")
            if record.get("arm_ids") != [
                arm["arm_id"] for arm in expected_pair["arms"]
            ]:
                raise ContractError("checkpoint verified arm identity drift")
            if record.get("cloud_verified") is not True:
                raise ContractError("checkpoint pair lacks verified cloud receipt")
            acceptance = _strict_json_object(
                record.get("acceptance"), label="checkpoint pair acceptance"
            )
            acceptance_manifest_sha256 = acceptance.get(
                "acceptance_manifest_sha256"
            )
            if (
                type(acceptance_manifest_sha256) is not str
                or _SHA256_RE.fullmatch(acceptance_manifest_sha256) is None
            ):
                raise ContractError(
                    "checkpoint pair lacks acceptance manifest identity"
                )
            if record.get("acceptance_sha256") != _identity(acceptance)["sha256"]:
                raise ContractError("checkpoint pair acceptance receipt drift")
            cloud_receipt = _strict_json_object(
                record.get("cloud_receipt"), label="checkpoint cloud receipt"
            )
            if record.get("cloud_receipt_sha256") != _identity(cloud_receipt)[
                "sha256"
            ]:
                raise ContractError("checkpoint cloud receipt drift")
            cloud_schema_error = self._cloud_receipt_schema_error(
                cloud_receipt,
                expected_matrix_sha256=str(manifest["matrix_identity"]["sha256"]),
                expected_run_id=str(manifest["run_identity"]["sha256"]),
                expected_sequence=expected_sequence,
                expected_pair_id=str(expected_pair["pair_id"]),
                expected_acceptance_manifest_sha256=acceptance_manifest_sha256,
            )
            if cloud_schema_error is not None:
                raise ContractError(cloud_schema_error)
            if type(record.get("attempt")) is not int or record["attempt"] < 1:
                raise ContractError("checkpoint pair has invalid attempt metadata")

        inflight = checkpoint.get("inflight")
        if inflight is not None:
            if type(inflight) is not dict:
                raise ContractError("invalid inflight pair metadata")
            if prefix >= len(pairs):
                raise ContractError("completed checkpoint cannot contain an inflight pair")
            phase = inflight.get("phase")
            base_fields = {
                "phase",
                "sequence",
                "pair_id",
                "pair_sha256",
                "arm_ids",
                "attempt",
            }
            expected_fields = (
                base_fields | {"arm_states"}
                if phase == "executing"
                else base_fields | {"acceptance", "acceptance_sha256"}
                if phase == "accepted"
                else set()
            )
            expected_pair = pairs[prefix]
            if (
                set(inflight) != expected_fields
                or type(inflight.get("sequence")) is not int
                or inflight.get("sequence") != prefix
                or inflight.get("pair_id") != expected_pair["pair_id"]
                or inflight.get("pair_sha256")
                != _identity(expected_pair)["sha256"]
                or inflight.get("arm_ids")
                != [arm["arm_id"] for arm in expected_pair["arms"]]
                or type(inflight.get("attempt")) is not int
                or inflight["attempt"] < 1
            ):
                raise ContractError("inflight pair is not the next contiguous sequence")
            if phase == "accepted":
                acceptance = _strict_json_object(
                    inflight.get("acceptance"), label="inflight pair acceptance"
                )
                acceptance_manifest_sha256 = acceptance.get(
                    "acceptance_manifest_sha256"
                )
                if (
                    type(acceptance_manifest_sha256) is not str
                    or _SHA256_RE.fullmatch(acceptance_manifest_sha256) is None
                    or inflight.get("acceptance_sha256")
                    != _identity(acceptance)["sha256"]
                ):
                    raise ContractError("inflight pair acceptance receipt drift")
            if phase == "executing":
                arm_states = inflight.get("arm_states")
                if type(arm_states) is not list or len(arm_states) != 2:
                    raise ContractError("inflight pair arm state cardinality drift")
                for arm_index, arm_state in enumerate(arm_states):
                    expected_arm = expected_pair["arms"][arm_index]
                    if type(arm_state) is not dict:
                        raise ContractError("inflight pair arm state is invalid")
                    arm_phase = arm_state.get("state")
                    arm_base_fields = {"arm_index", "arm_id", "state"}
                    arm_expected_fields = (
                        arm_base_fields | {"result", "result_sha256"}
                        if arm_phase == "committed"
                        else arm_base_fields
                        if arm_phase in {"pending", "executing"}
                        else set()
                    )
                    if (
                        set(arm_state) != arm_expected_fields
                        or arm_state.get("arm_index") != arm_index
                        or arm_state.get("arm_id") != expected_arm["arm_id"]
                    ):
                        raise ContractError("inflight pair arm state identity drift")
                    if arm_phase == "committed":
                        result = _strict_json_copy(
                            arm_state.get("result"),
                            label="checkpoint arm result",
                        )
                        if arm_state.get("result_sha256") != _identity(result)["sha256"]:
                            raise ContractError("inflight pair arm result drift")
                phases = [arm_state["state"] for arm_state in arm_states]
                if phases[1] != "pending" and phases[0] != "committed":
                    raise ContractError("inflight pair arm state is not a prefix")
        if state in {"complete", "finalized"}:
            if prefix != len(pairs) or inflight is not None:
                raise ContractError("completed checkpoint is not fully verified")
        if state == "finalized" and not self.finalization_path.exists():
            raise ContractError("finalized checkpoint lacks finalization artifact")

    def _write_checkpoint(self, checkpoint: dict[str, Any]) -> None:
        checkpoint["updated_at"] = _utc_now()
        _atomic_write_json(self.checkpoint_path, checkpoint)

    @staticmethod
    def _require_decision(
        value: Any, *, callback_name: str
    ) -> CallbackDecision:
        if type(value) is not CallbackDecision:
            raise PermanentRunError(
                f"{callback_name} callback returned an invalid decision"
            )
        if type(value.accepted) is not bool or type(value.retryable) is not bool:
            raise PermanentRunError(
                f"{callback_name} decision booleans must be exact bool values"
            )
        if type(value.reason) is not str:
            raise PermanentRunError(
                f"{callback_name} decision reason must be a string"
            )
        try:
            details = _strict_json_object(
                value.details, label=f"{callback_name} decision details"
            )
        except ContractError as error:
            raise PermanentRunError(str(error)) from error
        return CallbackDecision(
            accepted=value.accepted,
            details=details,
            reason=value.reason,
            retryable=value.retryable,
        )

    @staticmethod
    def _require_acceptance_manifest_hash(
        details: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = _strict_json_object(
            details, label="accept_pair decision details"
        )
        acceptance_manifest_sha256 = normalized.get(
            "acceptance_manifest_sha256"
        )
        if (
            type(acceptance_manifest_sha256) is not str
            or _SHA256_RE.fullmatch(acceptance_manifest_sha256) is None
        ):
            raise PermanentRunError(
                "accept_pair details require acceptance_manifest_sha256"
            )
        return normalized

    @staticmethod
    def _cloud_receipt_schema_error(
        details: Mapping[str, Any],
        *,
        expected_matrix_sha256: str,
        expected_run_id: str,
        expected_sequence: int,
        expected_pair_id: str,
        expected_acceptance_manifest_sha256: str,
    ) -> str | None:
        if set(details) != _CLOUD_RECEIPT_FIELDS:
            return "cloud receipt fields do not match the transaction result schema"
        expected_identity = {
            "state": "local_pruned",
            "matrix_sha256": expected_matrix_sha256,
            "run_id": expected_run_id,
            "pair_sequence": expected_sequence,
            "pair_id": expected_pair_id,
            "acceptance_sha256": expected_acceptance_manifest_sha256,
        }
        for field, expected in expected_identity.items():
            actual = details.get(field)
            if type(actual) is not type(expected) or actual != expected:
                return f"cloud receipt identity drift: {field}"
        for field in (
            "archive_sha256",
            "receipt_sha256",
            "ledger_entry_sha256",
        ):
            value = details.get(field)
            if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                return f"cloud receipt has invalid {field}"
        for field in ("archive_size_bytes", "receipt_size_bytes"):
            value = details.get(field)
            if type(value) is not int or value < 1:
                return f"cloud receipt has invalid {field}"
        for field in (
            "archive_remote_name",
            "receipt_remote_name",
            "local_archive_path",
            "local_receipt_path",
        ):
            value = details.get(field)
            if type(value) is not str or not value:
                return f"cloud receipt has invalid {field}"
        return None

    def _require_cloud_receipt(
        self,
        value: Any,
        *,
        context: PairContext,
        acceptance_details: Mapping[str, Any],
        callback_name: str,
    ) -> CloudTransactionReceipt:
        if type(value) is not CloudTransactionReceipt:
            raise PermanentRunError(
                f"{callback_name} callback returned an invalid receipt"
            )
        if type(value.verified) is not bool or type(value.retryable) is not bool:
            raise PermanentRunError(
                f"{callback_name} receipt booleans must be exact bool values"
            )
        if type(value.reason) is not str:
            raise PermanentRunError(
                f"{callback_name} receipt reason must be a string"
            )
        try:
            details = _strict_json_object(
                value.details, label=f"{callback_name} receipt details"
            )
        except ContractError as error:
            raise PermanentRunError(str(error)) from error
        if not value.verified:
            error_type = TransientRunError if value.retryable else PermanentRunError
            raise error_type(
                value.reason
                or f"pair {context.pair['pair_id']} cloud receipt is not verified"
            )
        if value.retryable:
            raise PermanentRunError(
                f"{callback_name} returned a verified retryable receipt"
            )
        schema_error = self._cloud_receipt_schema_error(
            details,
            expected_matrix_sha256=str(context.run.matrix_identity["sha256"]),
            expected_run_id=str(context.run.run_identity["sha256"]),
            expected_sequence=context.sequence,
            expected_pair_id=str(context.pair["pair_id"]),
            expected_acceptance_manifest_sha256=str(
                acceptance_details["acceptance_manifest_sha256"]
            ),
        )
        if schema_error is not None:
            raise PermanentRunError(schema_error)
        return CloudTransactionReceipt.verified_receipt(details)

    def _pair_context(
        self,
        manifest: Mapping[str, Any],
        *,
        sequence: int,
        attempt: int,
    ) -> PairContext:
        return PairContext(
            run=self._run_context(manifest, next_sequence=sequence),
            sequence=sequence,
            pair=copy.deepcopy(manifest["matrix"]["pairs"][sequence]),
            attempt=attempt,
        )

    @staticmethod
    def _inflight_identity(
        pair: Mapping[str, Any],
        *,
        sequence: int,
        attempt: int,
        phase: str,
    ) -> dict[str, Any]:
        return {
            "phase": phase,
            "sequence": sequence,
            "pair_id": pair["pair_id"],
            "pair_sha256": _identity(pair)["sha256"],
            "arm_ids": [arm["arm_id"] for arm in pair["arms"]],
            "attempt": attempt,
        }

    @classmethod
    def _executing_inflight_identity(
        cls,
        pair: Mapping[str, Any],
        *,
        sequence: int,
        attempt: int,
    ) -> dict[str, Any]:
        value = cls._inflight_identity(
            pair,
            sequence=sequence,
            attempt=attempt,
            phase="executing",
        )
        value["arm_states"] = [
            {
                "arm_index": arm_index,
                "arm_id": arm["arm_id"],
                "state": "pending",
            }
            for arm_index, arm in enumerate(pair["arms"])
        ]
        return value

    @staticmethod
    def _raise_rejected(decision: CallbackDecision, default_reason: str) -> None:
        error_type = TransientRunError if decision.retryable else PermanentRunError
        raise error_type(decision.reason or default_reason)

    @staticmethod
    def _verified_pair_record(
        context: PairContext,
        acceptance: CallbackDecision,
        cloud_receipt: CloudTransactionReceipt,
    ) -> dict[str, Any]:
        acceptance_details = _json_copy(acceptance.details)
        cloud_details = _json_copy(cloud_receipt.details)
        return {
            "sequence": context.sequence,
            "pair_id": context.pair["pair_id"],
            "pair_sha256": _identity(context.pair)["sha256"],
            "arm_ids": [arm["arm_id"] for arm in context.pair["arms"]],
            "attempt": context.attempt,
            "acceptance": acceptance_details,
            "acceptance_sha256": _identity(acceptance_details)["sha256"],
            "cloud_verified": True,
            "cloud_receipt": cloud_details,
            "cloud_receipt_sha256": _identity(cloud_details)["sha256"],
            "committed_at": _utc_now(),
        }

    @staticmethod
    def _remote_verification_material(
        records: list[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "sequence": record["sequence"],
                "pair_id": record["pair_id"],
                "acceptance_manifest_sha256": record["acceptance"][
                    "acceptance_manifest_sha256"
                ],
                "archive_sha256": record["cloud_receipt"]["archive_sha256"],
                "receipt_sha256": record["cloud_receipt"]["receipt_sha256"],
                "ledger_entry_sha256": record["cloud_receipt"][
                    "ledger_entry_sha256"
                ],
            }
            for record in records
        ]

    def _record_failure(
        self, checkpoint: dict[str, Any], error: Exception, *, transient: bool
    ) -> None:
        checkpoint["state"] = "paused_transient" if transient else "failed_permanent"
        checkpoint["last_error"] = {
            "classification": "transient" if transient else "permanent",
            "type": type(error).__name__,
            "message": str(error),
            "at": _utc_now(),
        }
        self._write_checkpoint(checkpoint)

    def _run_context(
        self, manifest: Mapping[str, Any], *, next_sequence: int,
        recovering_accepted_pair: bool = False,
    ) -> RunContext:
        return RunContext(
            run_root=self.run_root,
            matrix_identity=copy.deepcopy(manifest["matrix_identity"]),
            run_identity=copy.deepcopy(manifest["run_identity"]),
            next_sequence=next_sequence,
            total_pairs=int(manifest["matrix"]["expected_pairs"]),
            recovering_accepted_pair=recovering_accepted_pair,
        )

    def _result(
        self,
        checkpoint: Mapping[str, Any],
        manifest: Mapping[str, Any],
        exit_code: ExitCode,
        message: str = "",
    ) -> RunResult:
        total_pairs = int(manifest["matrix"]["expected_pairs"])
        prefix = int(checkpoint["verified_prefix_length"])
        status = {
            ExitCode.COMPLETE: "complete",
            ExitCode.TRANSIENT: "transient",
            ExitCode.PERMANENT: "permanent",
        }[exit_code]
        return RunResult(
            exit_code=exit_code,
            status=status,
            completed_pairs=prefix,
            completed_arms=prefix * 2,
            total_pairs=total_pairs,
            total_arms=total_pairs * 2,
            next_sequence=prefix if prefix < total_pairs else None,
            message=message,
        )

    def _unopened_error_result(
        self, exit_code: ExitCode, message: str
    ) -> RunResult:
        try:
            matrix = self._current_matrix()
            total_pairs = int(matrix["expected_pairs"])
        except Exception:
            total_pairs = 0
        return RunResult(
            exit_code=exit_code,
            status="transient" if exit_code == ExitCode.TRANSIENT else "permanent",
            completed_pairs=0,
            completed_arms=0,
            total_pairs=total_pairs,
            total_arms=total_pairs * 2,
            next_sequence=0 if total_pairs else None,
            message=message,
        )

    def _validate_finalization(
        self,
        finalization: Mapping[str, Any],
        manifest: Mapping[str, Any],
        checkpoint: Mapping[str, Any],
    ) -> None:
        total_pairs = int(manifest["matrix"]["expected_pairs"])
        if (
            checkpoint.get("verified_prefix_length") != total_pairs
            or checkpoint.get("state") not in {"complete", "finalized"}
        ):
            raise ContractError(
                "full publication finalization drift: incomplete checkpoint"
            )
        expected_pairs_sha256 = _identity(checkpoint["verified_pairs"])["sha256"]
        expected = {
            "schema_version": FINALIZATION_SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_finalization",
            "verified": True,
            "matrix_identity": manifest["matrix_identity"],
            "run_identity": manifest["run_identity"],
            "verified_pairs": total_pairs,
            "verified_arms": total_pairs * 2,
            "verified_pairs_sha256": expected_pairs_sha256,
            "remote_verified_pairs": total_pairs,
            "remote_verification_sha256": _identity(
                self._remote_verification_material(checkpoint["verified_pairs"])
            )["sha256"],
        }
        if set(finalization) != set(expected) | {"finalized_at"}:
            raise ContractError("full publication finalization drift: fields")
        for key, value in expected.items():
            if _canonical_json(finalization.get(key)) != _canonical_json(value):
                raise ContractError(f"full publication finalization drift: {key}")
        finalized_at = finalization.get("finalized_at")
        if type(finalized_at) is not str:
            raise ContractError("full publication finalization drift: finalized_at")
        try:
            timestamp = datetime.fromisoformat(finalized_at)
        except ValueError:
            raise ContractError(
                "full publication finalization drift: finalized_at"
            ) from None
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ContractError("full publication finalization drift: finalized_at")


__all__ = [
    "ArmContext",
    "CallbackDecision",
    "CloudTransactionReceipt",
    "ExitCode",
    "FullPublicationRunner",
    "IdentityDriftError",
    "PairContext",
    "PermanentRunError",
    "RunContext",
    "RunResult",
    "RunnerCallbacks",
    "TransientRunError",
]
