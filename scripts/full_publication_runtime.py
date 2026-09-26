#!/usr/bin/env python3
"""Real pair staging, acceptance, cloud commit, and remote verification callbacks."""

from __future__ import annotations

import copy
import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from benchmark_contract import ContractError
from checkpoint_acceptance_metadata_binding import (
    AcceptanceMetadataBindingError,
    validate_checkpoint_acceptance_metadata_binding,
)
from publication_acceptance_evidence import (
    FULL_RESOURCE_EVIDENCE_FILES,
    accepted_arm_evidence_files,
)
from full_publication_runner import (
    ArmContext,
    CallbackDecision,
    CloudTransactionReceipt,
    PairContext,
    RunContext,
    RunnerCallbacks,
)
from publication_archive import PairArchiveError
from publication_cloud_transaction import (
    CloudTransactionError,
    LedgerIntegrityError,
    PublicationCloudTransaction,
)
from publication_article_statistics_v1 import (
    ArticleStatisticsV1Error,
    seal_pair_article_statistics_v1,
    validate_article_statistics_binding_v1,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)
from publication_matrix import validate_full_publication_readiness
from seafile_artifact_store import ArtifactIntegrityError, ArtifactStoreError


PAIR_ACCEPTANCE_SCHEMA_VERSION = 2
MINIMUM_CONFIRMED_CLOUD_GIB = 500.0
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ARM_ACCEPTANCE_NAME = "checkpoint_publication_acceptance.json"
_RUN_METADATA_NAME = "run_metadata.json"
_REQUIRED_ARM_GATES = (
    "ingress_ledger_complete",
    "ingress_cohort_closed",
    "branch_terminal_trace_complete",
    "checkpoint_frame_aggregation_complete",
    "stage_semantic_contract_complete",
    "decoder_placement_verified",
    "resource_attribution_complete",
    "reset_state_verified",
    "full_resource_evidence_accepted",
    "full_resource_coverage_complete",
)
_FULL_RESOURCE_EVIDENCE_NAMES = frozenset(FULL_RESOURCE_EVIDENCE_FILES)


ArmRunner = Callable[[ArmContext, Path], Mapping[str, Any]]
ReadinessValidator = Callable[[dict[str, Any]], Mapping[str, Any]]
ArticleStatisticsSealer = Callable[..., Mapping[str, Any]]
PairAcceptancePhysicalFault = Callable[[str, Path], None]


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
        raise ContractError(f"full runtime artifact is not canonical JSON: {error}") from error


def _json_copy(value: Any) -> Any:
    return json.loads(_canonical_json(value).decode("utf-8"))


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _sha256_file(path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ContractError(f"invalid {label}: {error}") from error
    if type(value) is not dict:
        raise ContractError(f"invalid {label}: expected a JSON object")
    return value


class _AcceptedPairOutputJournal:
    """Durably publish/adopt the two causal pair-acceptance copies."""

    def __init__(
        self,
        custody: PhysicalRootCustodyV1,
        *,
        after_physical_commit_step: PairAcceptancePhysicalFault | None,
    ) -> None:
        self.custody = custody
        self.after_physical_commit_step = after_physical_commit_step
        self.entries: dict[
            Path, tuple[dict[str, Any], bytes, tuple[int, int]]
        ] = {}

    def commit(self, path: Path, value: Mapping[str, Any]) -> str:
        if path in self.entries:
            raise ContractError(f"pair acceptance journal duplicated: {path.name}")
        payload = _canonical_json(value) + b"\n"
        relative = path.relative_to(self.custody.root).as_posix()
        expected = {
            "path": relative,
            "size_bytes": len(payload),
            "sha256": _sha256_bytes(payload),
        }

        def physical_step(step: str) -> None:
            if self.after_physical_commit_step is not None:
                self.after_physical_commit_step(step, path)

        try:
            descriptor, identity, disposition = (
                self.custody.commit_or_adopt_exact_identity(
                    relative,
                    payload,
                    label="pair acceptance",
                    mode=0o600,
                    create_parents=False,
                    after_publish_step=physical_step,
                )
            )
        except PublicationPhysicalIoV1Error as write_error:
            try:
                _descriptor, existing = self.custody.read_descriptor(
                    relative,
                    label="existing pair acceptance",
                    maximum=len(payload),
                    capture=True,
                )
            except PublicationPhysicalIoV1Error as read_error:
                raise ContractError(
                    "pair acceptance physical immutable commit failed: "
                    f"{write_error}"
                ) from read_error
            if existing != payload:
                raise ContractError(
                    f"immutable pair acceptance collision: {path.name}"
                ) from write_error
            raise ContractError(
                f"pair acceptance exact adoption failed: {path.name}"
            ) from write_error
        if descriptor != expected or disposition not in {"published", "adopted"}:
            raise ContractError("pair acceptance atomic commit result drifted")
        self.entries[path] = (descriptor, payload, identity)
        return descriptor["sha256"]

    def verify(self) -> None:
        if len(self.entries) != 2:
            raise ContractError("pair acceptance journal is incomplete")
        for path, (expected, payload, identity) in self.entries.items():
            observed, cold_payload, cold_identity = (
                self.custody.read_descriptor_identity(
                    expected["path"],
                    label=f"committed pair acceptance {path.name}",
                    maximum=len(payload),
                    capture=True,
                )
            )
            observed_mode, stat_identity = self.custody.stat_regular_identity(
                expected["path"],
                label=f"committed pair acceptance {path.name} mode",
            )
            if (
                observed != expected
                or cold_payload != payload
                or cold_identity != identity
                or stat_identity != identity
                or observed_mode != 0o600
            ):
                raise ContractError("pair acceptance journal identity drifted")
        self.custody.verify()


class FullPublicationRuntime:
    """Callbacks that turn an accepted two-arm pair into durable cloud progress."""

    def __init__(
        self,
        *,
        run_root: Path | str,
        config: Mapping[str, Any],
        cloud_store: Any,
        arm_runner: ArmRunner,
        readiness_validator: ReadinessValidator = validate_full_publication_readiness,
        article_statistics_sealer: ArticleStatisticsSealer = (
            seal_pair_article_statistics_v1
        ),
        minimum_free_bytes: int = 20 * 1024**3,
        scratch_roots: Sequence[Path | str] = (),
        capacity_confirmed_gib: float = 0.0,
        pair_acceptance_physical_fault: PairAcceptancePhysicalFault | None = None,
    ) -> None:
        self.run_root = Path(run_root).resolve()
        self.config = _json_copy(config)
        self.cloud_store = cloud_store
        self.arm_runner = arm_runner
        self.readiness_validator = readiness_validator
        self.article_statistics_sealer = article_statistics_sealer
        self.minimum_free_bytes = int(minimum_free_bytes)
        self.scratch_roots = tuple(Path(path).resolve() for path in scratch_roots)
        self.capacity_confirmed_gib = float(capacity_confirmed_gib)
        self.pair_acceptance_physical_fault = pair_acceptance_physical_fault
        if self.minimum_free_bytes < 1:
            raise ContractError("minimum_free_bytes must be positive")
        if not math.isfinite(self.capacity_confirmed_gib):
            raise ContractError("capacity_confirmed_gib must be finite")

    def callbacks(self) -> RunnerCallbacks:
        return RunnerCallbacks(
            preflight=self.preflight,
            execute_arm=self.execute_arm,
            accept_pair=self.accept_pair,
            cloud_transaction=self.cloud_transaction,
            verify_cloud=self.verify_cloud,
            before_pair=self.before_pair,
        )

    def _assert_context_root(self, context: RunContext) -> None:
        if Path(context.run_root).resolve() != self.run_root:
            raise ContractError("runtime callback run_root drift")

    def _inside_run(self, path: Path, *, label: str) -> Path:
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(self.run_root)
        except ValueError:
            raise ContractError(f"{label} must be inside run_root") from None
        if not relative.parts:
            raise ContractError(f"{label} must not equal run_root")
        return resolved

    @staticmethod
    def _safe_identifier(value: Any, *, label: str) -> str:
        text = str(value)
        if _IDENTIFIER_RE.fullmatch(text) is None:
            raise ContractError(f"{label} contains unsupported characters")
        return text

    def attempt_root(self, context: PairContext) -> Path:
        self._assert_context_root(context.run)
        pair_id = self._safe_identifier(context.pair.get("pair_id"), label="pair_id")
        if type(context.sequence) is not int or context.sequence < 0:
            raise ContractError("pair sequence must be non-negative")
        if type(context.attempt) is not int or context.attempt < 1:
            raise ContractError("pair attempt must be positive")
        path = (
            self.run_root
            / "pairs"
            / f"{context.sequence:04d}_{pair_id}"
            / f"attempt-{context.attempt:04d}"
        )
        return self._inside_run(path, label="pair attempt root")

    def _arm_root(self, context: ArmContext) -> Path:
        arm_id = self._safe_identifier(context.arm.get("arm_id"), label="arm_id")
        position = context.arm.get("arm_position")
        if type(position) is not int or position not in {1, 2}:
            raise ContractError("arm_position must be 1 or 2")
        return self._inside_run(
            self.attempt_root(context.pair_context)
            / "arms"
            / f"{position:02d}_{arm_id}",
            label="arm root",
        )

    def _existing_ancestor(self) -> Path:
        candidate = self.run_root
        while not candidate.exists() and candidate.parent != candidate:
            candidate = candidate.parent
        if not candidate.exists():
            raise ContractError("cannot resolve a filesystem for run_root")
        return candidate

    def _disk_admission(self) -> CallbackDecision:
        """Apply the operational reserve to results, native scratch and host storage."""
        try:
            paths = [self._existing_ancestor(), Path(tempfile.gettempdir()), *self.scratch_roots]
            host_backing = Path("/mnt/c")
            if host_backing.is_dir():
                paths.append(host_backing)
            observations = []
            for path in dict.fromkeys(paths):
                free = int(shutil.disk_usage(path).free)
                observations.append({"path": str(path), "free_bytes": free})
            details = {
                "filesystems": observations,
                "free_bytes": observations[0]["free_bytes"],
                "minimum_free_bytes": self.minimum_free_bytes,
            }
            if any(item["free_bytes"] < self.minimum_free_bytes for item in observations):
                return CallbackDecision.rejected(
                    "local storage is below the operational free-space reserve",
                    details=details, retryable=True,
                )
            return CallbackDecision.passed(details)
        except OSError:
            return CallbackDecision.rejected(
                "local storage free-space check is unavailable", retryable=True,
            )

    def before_pair(self, context: PairContext) -> CallbackDecision:
        self._assert_context_root(context.run)
        return self._disk_admission()

    def _allow_remote_inflight_sequence(self, completed_pairs: int) -> bool:
        checkpoint_path = self.run_root / "checkpoint.json"
        if not checkpoint_path.exists():
            return False
        if checkpoint_path.is_symlink() or not checkpoint_path.is_file():
            raise ContractError("full publication checkpoint is invalid")
        checkpoint = _read_object(
            checkpoint_path, label="full publication checkpoint continuity"
        )
        if checkpoint.get("verified_prefix_length") != completed_pairs:
            raise ContractError("full publication checkpoint prefix drift")
        inflight = checkpoint.get("inflight")
        return (
            type(inflight) is dict
            and inflight.get("phase") == "accepted"
            and inflight.get("sequence") == completed_pairs
        )

    def _validate_remote_run_prefix(
        self,
        remote_files: Mapping[str, Any],
        *,
        allowed_prefix: str,
        completed_pairs: int,
    ) -> None:
        if type(completed_pairs) is not int or completed_pairs < 0:
            raise ContractError("preflight completed pair prefix is invalid")
        pattern = re.compile(
            rf"^{re.escape(allowed_prefix)}(?P<sequence>[0-9]{{4}})_"
            rf"(?P<pair_key>[0-9a-f]{{16}})_(?P<sha256>[0-9a-f]{{64}})"
            rf"(?P<suffix>\.tar\.zst|\.receipt\.json)$"
        )
        observed: dict[int, dict[str, str]] = {}
        malformed_owned_names = 0
        for raw_name, metadata in remote_files.items():
            name = str(raw_name)
            if (
                type(raw_name) is not str
                or type(metadata) is not dict
                or metadata.get("file_name") != name
                or metadata.get("is_dir") is not False
            ):
                raise ArtifactStoreError("Seafile remote listing entry is invalid")
            match = pattern.fullmatch(name)
            if match is None:
                if name.startswith(allowed_prefix):
                    malformed_owned_names += 1
                continue
            sequence = int(match.group("sequence"))
            kind = (
                "archive"
                if match.group("suffix") == ".tar.zst"
                else "receipt"
            )
            pair_key = match.group("pair_key")
            kinds = observed.setdefault(sequence, {})
            if kind in kinds:
                raise ArtifactIntegrityError(
                    f"duplicate remote {kind} for pair sequence {sequence}"
                )
            if kinds and pair_key not in set(kinds.values()):
                raise ArtifactIntegrityError(
                    f"remote pair key mismatch for pair sequence {sequence}"
                )
            kinds[kind] = pair_key
        if malformed_owned_names:
            raise ContractError(
                "Seafile frozen run namespace contains malformed artifacts"
            )
        expected_complete = set(range(completed_pairs))
        for sequence in expected_complete:
            if set(observed.get(sequence, {})) != {"archive", "receipt"}:
                raise ArtifactIntegrityError(
                    f"remote pair continuity is incomplete at sequence {sequence}"
                )
        unexpected = set(observed) - expected_complete
        allow_inflight = self._allow_remote_inflight_sequence(completed_pairs)
        if unexpected - ({completed_pairs} if allow_inflight else set()):
            raise ArtifactIntegrityError("remote pair sequence exceeds local checkpoint")
        if completed_pairs in observed:
            kinds = set(observed[completed_pairs])
            if not allow_inflight or not kinds <= {"archive", "receipt"} or (
                "receipt" in kinds and "archive" not in kinds
            ):
                raise ArtifactIntegrityError(
                    "remote inflight pair does not match durable local acceptance"
                )

    def preflight(self, context: RunContext) -> CallbackDecision:
        try:
            self._assert_context_root(context)
            assessment = _json_copy(self.readiness_validator(copy.deepcopy(self.config)))
            if type(assessment) is not dict or type(assessment.get("passed")) is not bool:
                raise ContractError("full publication readiness returned an invalid assessment")
            if not assessment["passed"]:
                blockers = assessment.get("blockers")
                rendered = ", ".join(str(value) for value in blockers or [])
                return CallbackDecision.rejected(
                    rendered or "full publication readiness is blocked",
                    details={"readiness": assessment},
                    retryable=False,
                )
            if self.capacity_confirmed_gib < MINIMUM_CONFIRMED_CLOUD_GIB:
                return CallbackDecision.rejected(
                    "Seafile capacity lower-bound attestation must be at least 500 GiB",
                    retryable=False,
                )
            disk = (
                CallbackDecision.passed({"storage_admission_deferred_for_accepted_pair": True})
                if context.recovering_accepted_pair else self._disk_admission()
            )
            if not disk.accepted:
                return disk
            cloud = _json_copy(self.cloud_store.preflight())
            if type(cloud) is not dict or cloud.get("status") != "ready":
                raise ArtifactStoreError("Seafile preflight did not return ready")
            remote_files = self.cloud_store.list_remote_files()
            if type(remote_files) is not dict:
                raise ArtifactStoreError("Seafile remote listing is invalid")
            run_key = hashlib.sha256(
                str(context.run_identity["sha256"]).encode("utf-8")
            ).hexdigest()[:16]
            allowed_prefix = f"{context.matrix_identity['sha256']}_{run_key}_"
            self._validate_remote_run_prefix(
                remote_files,
                allowed_prefix=allowed_prefix,
                completed_pairs=context.next_sequence,
            )
            return CallbackDecision.passed(
                {
                    "readiness": assessment,
                    "cloud": cloud,
                    **disk.details,
                    "minimum_free_bytes": self.minimum_free_bytes,
                    "capacity_confirmed_gib": self.capacity_confirmed_gib,
                }
            )
        except ArtifactIntegrityError as error:
            return CallbackDecision.rejected(str(error), retryable=False)
        except ArtifactStoreError as error:
            return CallbackDecision.rejected(str(error), retryable=True)
        except ContractError as error:
            return CallbackDecision.rejected(str(error), retryable=False)

    def execute_arm(self, context: ArmContext) -> dict[str, Any]:
        self._assert_context_root(context.pair_context.run)
        expected_arms = context.pair_context.pair.get("arms")
        if type(expected_arms) is not list or len(expected_arms) != 2:
            raise ContractError("pair does not contain exactly two frozen arms")
        if type(context.arm_index) is not int or context.arm_index not in {0, 1}:
            raise ContractError("arm_index must be 0 or 1")
        if _canonical_json(context.arm) != _canonical_json(expected_arms[context.arm_index]):
            raise ContractError("arm callback identity drift")
        arm_root = self._arm_root(context)
        if arm_root.exists():
            if arm_root.is_symlink() or not arm_root.is_dir():
                raise ContractError("arm attempt root is not a regular directory")
        arm_root.parent.mkdir(parents=True, exist_ok=True)
        raw_result = self.arm_runner(context, arm_root)
        result = _json_copy(raw_result)
        if type(result) is not dict:
            raise ContractError("arm runner result must be a JSON object")
        if result.get("status") != "completed":
            raise ContractError("arm runner did not complete")
        if result.get("arm_id") != context.arm["arm_id"]:
            raise ContractError("arm runner result identity drift")
        if not arm_root.is_dir() or arm_root.is_symlink():
            raise ContractError("arm runner did not create a regular evidence directory")
        acceptance_paths = sorted(arm_root.rglob(_ARM_ACCEPTANCE_NAME))
        metadata_paths = sorted(arm_root.rglob(_RUN_METADATA_NAME))
        if len(acceptance_paths) != 1 or len(metadata_paths) != 1:
            raise ContractError("arm evidence must contain exactly one acceptance and metadata file")
        for path in (acceptance_paths[0], metadata_paths[0]):
            if path.is_symlink() or not path.is_file():
                raise ContractError("arm evidence manifest must be a regular file")
            self._inside_run(path, label="arm evidence manifest")
        return {
            "status": "completed",
            "arm_id": str(context.arm["arm_id"]),
            "arm_index": context.arm_index,
            "arm_root_relative_path": arm_root.relative_to(self.run_root).as_posix(),
            "runtime_acceptance_relative_path": acceptance_paths[0]
            .relative_to(self.run_root)
            .as_posix(),
            "run_metadata_relative_path": metadata_paths[0]
            .relative_to(self.run_root)
            .as_posix(),
        }

    def _result_path(self, result: Mapping[str, Any], field: str) -> Path:
        raw = result.get(field)
        if type(raw) is not str or not raw:
            raise ContractError(f"arm result lacks {field}")
        return self._inside_run(self.run_root / raw, label=field)

    @staticmethod
    def _equal_number(actual: Any, expected: Any) -> bool:
        if isinstance(actual, bool) or isinstance(expected, bool):
            return False
        try:
            return math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1e-9)
        except (TypeError, ValueError):
            return False

    def _validate_arm_result(
        self,
        context: PairContext,
        expected_arm: Mapping[str, Any],
        result: Mapping[str, Any],
        *,
        arm_index: int,
    ) -> dict[str, Any]:
        if type(result) is not dict or set(result) != {
            "status",
            "arm_id",
            "arm_index",
            "arm_root_relative_path",
            "runtime_acceptance_relative_path",
            "run_metadata_relative_path",
        }:
            raise ContractError("arm callback result schema drift")
        if (
            result.get("status") != "completed"
            or result.get("arm_id") != expected_arm["arm_id"]
            or result.get("arm_index") != arm_index
        ):
            raise ContractError("arm callback result identity drift")
        arm_root = self._result_path(result, "arm_root_relative_path")
        acceptance_path = self._result_path(
            result, "runtime_acceptance_relative_path"
        )
        metadata_path = self._result_path(result, "run_metadata_relative_path")
        if not arm_root.is_dir() or arm_root.is_symlink():
            raise ContractError("accepted arm root is not a regular directory")
        for path in (acceptance_path, metadata_path):
            try:
                path.relative_to(arm_root)
            except ValueError:
                raise ContractError("arm manifest escaped its evidence root") from None
        acceptance = _read_object(
            acceptance_path, label="checkpoint arm acceptance"
        )
        if (
            acceptance.get("schema_version") != 2
            or acceptance.get("artifact_kind")
            != "checkpoint_publication_runtime_acceptance"
            or acceptance.get("status") != "accepted_native_checkpoint_arm"
        ):
            raise ContractError("checkpoint arm is not runtime-accepted")
        expected_execution_binding = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_arm_execution_binding",
            "run_identity_sha256": str(context.run.run_identity["sha256"]),
            "sequence": context.sequence,
            "pair_id": str(context.pair["pair_id"]),
            "attempt": context.attempt,
            "arm_id": str(expected_arm["arm_id"]),
        }
        try:
            metadata_authorities = (
                validate_checkpoint_acceptance_metadata_binding(
                    acceptance,
                    run_metadata_path=metadata_path,
                    expected_execution_binding=expected_execution_binding,
                )
            )
        except AcceptanceMetadataBindingError as error:
            raise ContractError(
                f"checkpoint arm acceptance metadata binding drift: {error}"
            ) from error
        exact_fields = (
            "system",
            "scenario",
            "codec",
            "policy",
        )
        for field in exact_fields:
            if acceptance.get(field) != expected_arm[field]:
                raise ContractError(f"checkpoint arm acceptance drift: {field}")
        if not self._equal_number(
            acceptance.get("deadline_ms"), expected_arm["deadline_ms"]
        ):
            raise ContractError("checkpoint arm acceptance drift: deadline_ms")
        schedule_sha = acceptance.get("measurement_schedule_fingerprint_sha256")
        if type(schedule_sha) is not str or _SHA256_RE.fullmatch(schedule_sha) is None:
            raise ContractError("checkpoint arm schedule fingerprint is invalid")
        summary = acceptance.get("summary")
        if type(summary) is not dict or any(
            summary.get(gate) is not True for gate in _REQUIRED_ARM_GATES
        ):
            raise ContractError("checkpoint arm required acceptance gate failed")
        if summary.get("resource_contract_version") != 2:
            raise ContractError("checkpoint arm full-resource contract version drift")
        evidence = acceptance.get("evidence_sha256")
        expected_evidence = set(
            accepted_arm_evidence_files(
                expected_arm["policy"],
                full_resource=True,
            )
        )
        if type(evidence) is not dict or set(evidence) != expected_evidence:
            raise ContractError("checkpoint arm evidence hash set drifted")
        for name, expected_sha in evidence.items():
            if (
                type(name) is not str
                or Path(name).name != name
                or type(expected_sha) is not str
                or _SHA256_RE.fullmatch(expected_sha) is None
            ):
                raise ContractError("checkpoint arm evidence identity is invalid")
            evidence_path = acceptance_path.parent / name
            if (
                evidence_path.is_symlink()
                or not evidence_path.is_file()
                or _sha256_file(evidence_path) != expected_sha
            ):
                raise ContractError(f"checkpoint arm evidence hash drift: {name}")
        full_resource_evidence = acceptance.get("full_resource_evidence_sha256")
        if (
            type(full_resource_evidence) is not dict
            or set(full_resource_evidence) != _FULL_RESOURCE_EVIDENCE_NAMES
            or any(evidence.get(name) != digest for name, digest in full_resource_evidence.items())
        ):
            raise ContractError("checkpoint arm full-resource evidence binding drift")
        resource_summary = acceptance.get("full_resource_summary")
        if (
            type(resource_summary) is not dict
            or resource_summary.get("resource_contract_version") != 2
            or resource_summary.get("evidence_accepted") is not True
            or resource_summary.get("publication_bundle_bound") is not True
            or resource_summary.get("full_resource_coverage_complete") is not True
        ):
            raise ContractError("checkpoint arm full-resource summary is not accepted")
        finalization = acceptance.get("acceptance_finalization")
        if finalization != {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
        }:
            raise ContractError("checkpoint arm acceptance was not finalized after collection")

        metadata = _read_object(metadata_path, label="checkpoint arm metadata")
        metadata_result = metadata.get("result")
        if type(metadata_result) is not dict or metadata_result.get("status") != "completed":
            raise ContractError("checkpoint arm metadata is not completed")
        for field in ("system", "scenario", "policy", "dataset", "repeat", "streams", "seed"):
            if metadata_result.get(field) != expected_arm[field]:
                raise ContractError(f"checkpoint arm metadata drift: {field}")
        if not self._equal_number(
            metadata_result.get("deadline_ms"), expected_arm["deadline_ms"]
        ):
            raise ContractError("checkpoint arm metadata drift: deadline_ms")
        run_seed = metadata_result.get("run_seed")
        if type(run_seed) is not int or metadata.get("run_seed") != run_seed:
            raise ContractError("checkpoint arm run_seed identity is invalid")
        return {
            "arm_id": str(expected_arm["arm_id"]),
            "scenario": str(expected_arm["scenario"]),
            "run_id": str(acceptance.get("run_id", "")),
            "run_seed": run_seed,
            "schedule_sha256": schedule_sha,
            "runtime_acceptance_relative_path": acceptance_path
            .relative_to(self.run_root)
            .as_posix(),
            "runtime_acceptance_sha256": _sha256_file(acceptance_path),
            "run_metadata_relative_path": metadata_path
            .relative_to(self.run_root)
            .as_posix(),
            "run_metadata_sha256": _sha256_file(metadata_path),
            "evidence_sha256": copy.deepcopy(evidence),
            "result": copy.deepcopy(metadata_result),
            "arm_acceptance_summary": copy.deepcopy(summary),
            "full_resource_summary": copy.deepcopy(resource_summary),
            "qualification_authorities": {
                field: metadata_authorities[field]
                for field in (
                    "identity_artifact_binding_sha256",
                    "resource_capability_grant_sha256",
                    "backend_runtime_grant_sha256",
                    "model_parity_grant_sha256",
                    "model_parity_acceptance_binding_sha256",
                )
            },
        }

    def accept_pair(
        self,
        context: PairContext,
        arm_results: tuple[Any, Any],
    ) -> CallbackDecision:
        try:
            self._assert_context_root(context.run)
            expected_arms = context.pair.get("arms")
            if type(expected_arms) is not list or len(expected_arms) != 2:
                raise ContractError("pair must contain exactly two frozen arms")
            if type(arm_results) is not tuple or len(arm_results) != 2:
                raise ContractError("pair acceptance requires exactly two arm results")
            records = [
                self._validate_arm_result(
                    context,
                    expected_arms[index],
                    _json_copy(arm_results[index]),
                    arm_index=index,
                )
                for index in range(2)
            ]
            schedules = {record["schedule_sha256"] for record in records}
            run_seeds = {record["run_seed"] for record in records}
            if len(schedules) != 1:
                raise ContractError("paired arms have different input schedules")
            if len(run_seeds) != 1:
                raise ContractError("paired arms have different run_seed values")
            qualification_fields = (
                "identity_artifact_binding_sha256",
                "resource_capability_grant_sha256",
                "backend_runtime_grant_sha256",
                "model_parity_grant_sha256",
                "model_parity_acceptance_binding_sha256",
            )
            if any(
                len({
                    record["qualification_authorities"][field]
                    for record in records
                }) != 1
                for field in qualification_fields
            ):
                raise ContractError(
                    "paired arms have different qualification authorities"
                )
            qualification_authorities = {
                field: records[0]["qualification_authorities"][field]
                for field in qualification_fields
            }
            scenarios = {record["scenario"] for record in records}
            if scenarios != {
                "checkpoint_independent_processes_baseline",
                "checkpoint_video_dag_shared",
            }:
                raise ContractError("paired arms do not cover both checkpoint architectures")

            attempt_root = self.attempt_root(context)
            pair_sha256 = _sha256_bytes(_canonical_json(context.pair))
            statistics_binding = _json_copy(
                self.article_statistics_sealer(
                    run_root=self.run_root,
                    pair_dir=attempt_root,
                    config=copy.deepcopy(self.config),
                    pair=copy.deepcopy(context.pair),
                    arm_records=copy.deepcopy(records),
                    matrix_sha256=str(context.run.matrix_identity["sha256"]),
                    run_id=str(context.run.run_identity["sha256"]),
                    pair_sequence=context.sequence,
                    pair_id=str(context.pair["pair_id"]),
                    pair_sha256=pair_sha256,
                    attempt=context.attempt,
                )
            )
            statistics_binding = validate_article_statistics_binding_v1(
                statistics_binding,
                run_root=self.run_root,
                pair_dir=attempt_root,
                require_attempt_copy=True,
                require_retained_copy=True,
                require_raw_evidence=True,
            )
            expected_statistics_pair = {
                "matrix_sha256": str(context.run.matrix_identity["sha256"]),
                "run_id": str(context.run.run_identity["sha256"]),
                "pair_sequence": context.sequence,
                "pair_id": str(context.pair["pair_id"]),
                "pair_sha256": pair_sha256,
                "attempt": context.attempt,
            }
            if statistics_binding["pair"] != expected_statistics_pair:
                raise ContractError(
                    "article-statistics pair identity differs from runtime context"
                )
            if statistics_binding["arm_ids"] != [
                str(arm["arm_id"]) for arm in expected_arms
            ]:
                raise ContractError(
                    "article-statistics arm identities differ from runtime context"
                )
            manifest = {
                "schema_version": PAIR_ACCEPTANCE_SCHEMA_VERSION,
                "artifact_kind": "vast_full_publication_pair_acceptance",
                "status": "accepted",
                "matrix_sha256": str(context.run.matrix_identity["sha256"]),
                "run_id": str(context.run.run_identity["sha256"]),
                "pair_sequence": context.sequence,
                "pair_id": str(context.pair["pair_id"]),
                "pair_sha256": pair_sha256,
                "attempt": context.attempt,
                "arm_ids": [str(arm["arm_id"]) for arm in expected_arms],
                "run_seed": records[0]["run_seed"],
                "measurement_schedule_fingerprint_sha256": records[0][
                    "schedule_sha256"
                ],
                "qualification_authorities": qualification_authorities,
                "pair_gates": {
                    "both_arms_runtime_accepted": True,
                    "input_schedule_exact_match": True,
                    "run_seed_exact_match": True,
                    "all_evidence_hashes_verified": True,
                    "common_identity_and_qualification_authorities": True,
                    "article_statistics_sealed_and_cross_bound": True,
                },
                "arms": records,
                "article_statistics": statistics_binding,
            }
            acceptance_path = attempt_root / "acceptance.json"
            compact_path = (
                self.run_root
                / "accepted_pairs"
                / (
                    f"{context.sequence:04d}_"
                    f"{self._safe_identifier(context.pair['pair_id'], label='pair_id')}"
                    f".attempt-{context.attempt:04d}.acceptance.json"
                )
            )
            try:
                with PhysicalRootCustodyV1.open(
                    self.run_root, label="full publication run_root"
                ) as custody:
                    # Pin both parent chains before either acceptance copy is
                    # committed, so a compact-root redirect cannot create an
                    # external partial write.
                    custody.ensure_directory(
                        acceptance_path.parent,
                        label="pair acceptance parent",
                    )
                    custody.ensure_directory(
                        compact_path.parent,
                        label="compact pair acceptance parent",
                    )
                    journal = _AcceptedPairOutputJournal(
                        custody,
                        after_physical_commit_step=(
                            self.pair_acceptance_physical_fault
                        ),
                    )
                    digest = journal.commit(acceptance_path, manifest)
                    compact_digest = journal.commit(compact_path, manifest)
                    journal.verify()
            except PublicationPhysicalIoV1Error as error:
                raise ContractError(
                    f"pair acceptance physical namespace rejected: {error}"
                ) from error
            if compact_digest != digest:
                raise ContractError("compact pair acceptance identity drift")
            return CallbackDecision.passed(
                {
                    "acceptance_manifest_sha256": digest,
                    "acceptance_manifest_relative_path": acceptance_path
                    .relative_to(self.run_root)
                    .as_posix(),
                    "compact_acceptance_relative_path": compact_path
                    .relative_to(self.run_root)
                    .as_posix(),
                    "pair_sha256": manifest["pair_sha256"],
                    "measurement_schedule_fingerprint_sha256": manifest[
                        "measurement_schedule_fingerprint_sha256"
                    ],
                    "article_statistics_record_identity_sha256": (
                        statistics_binding["record_identity_sha256"]
                    ),
                    "article_statistics_retained_relative_path": (
                        statistics_binding["retained_copy"]["relative_path"]
                    ),
                }
            )
        except (ArticleStatisticsV1Error, ContractError) as error:
            return CallbackDecision.rejected(str(error), retryable=False)

    def _acceptance_path(
        self, context: PairContext, decision: CallbackDecision
    ) -> Path:
        if decision.accepted is not True or type(decision.details) is not dict:
            raise ContractError("cloud callback requires an accepted pair decision")
        raw = decision.details.get("acceptance_manifest_relative_path")
        compact_raw = decision.details.get("compact_acceptance_relative_path")
        expected_sha = decision.details.get("acceptance_manifest_sha256")
        if (
            type(raw) is not str
            or type(compact_raw) is not str
            or type(expected_sha) is not str
        ):
            raise ContractError("accepted pair decision lacks immutable manifest identity")
        path = self._inside_run(self.run_root / raw, label="pair acceptance manifest")
        compact_path = self._inside_run(
            self.run_root / compact_raw, label="compact pair acceptance manifest"
        )
        try:
            path.relative_to(self.attempt_root(context))
        except ValueError:
            raise ContractError("pair acceptance manifest belongs to another attempt") from None
        accepted_root = (self.run_root / "accepted_pairs").resolve()
        try:
            compact_path.relative_to(accepted_root)
        except ValueError:
            raise ContractError("compact pair acceptance escaped accepted_pairs") from None
        if (
            not compact_path.is_file()
            or compact_path.is_symlink()
            or _sha256_file(compact_path) != expected_sha
        ):
            raise ContractError("compact pair acceptance manifest hash drift")
        if path.exists() and (
            not path.is_file() or path.is_symlink() or _sha256_file(path) != expected_sha
        ):
            raise ContractError("pair acceptance manifest hash drift")
        return path if path.is_file() else compact_path

    def cloud_transaction(
        self, context: PairContext, decision: CallbackDecision
    ) -> CloudTransactionReceipt:
        try:
            self._assert_context_root(context.run)
            acceptance_path = self._acceptance_path(context, decision)
            result = PublicationCloudTransaction(
                store=self.cloud_store,
                run_root=self.run_root,
            ).commit_pair(
                pair_dir=self.attempt_root(context),
                acceptance_manifest=acceptance_path,
                matrix_sha256=str(context.run.matrix_identity["sha256"]),
                run_id=str(context.run.run_identity["sha256"]),
                pair_sequence=context.sequence,
                pair_id=str(context.pair["pair_id"]),
            )
            # The transaction API also reports statistics already bound into its
            # ledger and the durable acceptance manifest. Keep the runner's
            # established checkpoint receipt schema at this callback boundary.
            for field in (
                "article_statistics_record_identity_sha256",
                "article_statistics_statistics_aggregate_sha256",
            ):
                value = result.pop(field, None)
                if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
                    raise ContractError("cloud transaction statistics identity is invalid")
            retained = result.pop("article_statistics_retained_relative_path", None)
            if type(retained) is not str or not retained or Path(retained).is_absolute():
                raise ContractError("cloud transaction retained statistics path is invalid")
            self._inside_run(self.run_root / retained, label="retained article statistics")
            return CloudTransactionReceipt.verified_receipt(_json_copy(result))
        except (ArtifactIntegrityError, LedgerIntegrityError, PairArchiveError, ContractError) as error:
            return CloudTransactionReceipt.unverified(str(error), retryable=False)
        except (ArtifactStoreError, CloudTransactionError, OSError) as error:
            return CloudTransactionReceipt.unverified(str(error), retryable=True)

    def verify_cloud(
        self,
        context: PairContext,
        stored_receipt: CloudTransactionReceipt,
    ) -> CloudTransactionReceipt:
        try:
            self._assert_context_root(context.run)
            if stored_receipt.verified is not True or type(stored_receipt.details) is not dict:
                raise ContractError("remote verification requires a stored verified receipt")
            details = _json_copy(stored_receipt.details)
            PublicationCloudTransaction(
                store=self.cloud_store,
                run_root=self.run_root,
            ).verify_pair_remote(
                pair_sequence=context.sequence,
                pair_id=str(context.pair["pair_id"]),
            )
            return CloudTransactionReceipt.verified_receipt(details)
        except (ArtifactIntegrityError, LedgerIntegrityError, PairArchiveError, ContractError) as error:
            return CloudTransactionReceipt.unverified(str(error), retryable=False)
        except (ArtifactStoreError, CloudTransactionError, OSError) as error:
            return CloudTransactionReceipt.unverified(str(error), retryable=True)


__all__ = ["FullPublicationRuntime", "PAIR_ACCEPTANCE_SCHEMA_VERSION"]
