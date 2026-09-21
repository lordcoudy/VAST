#!/usr/bin/env python3
"""Promote one pending native checkpoint arm into production evidence.

The production launcher is the parent of the native runtime.  It owns the
bounded host hardware collector and this finalization transaction, while the
outer ABI-v3 transaction retains launch-fence, capture, result, and receipt
ownership.  Native runtimes therefore write only their pending/raw namespace
into a private staging directory.  Durable metadata is committed after full
resource validation and the acceptance file is the final child-owned commit.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Protocol

from checkpoint_publication_runtime import prepare_checkpoint_publication_acceptance
from collect_metrics import HardwareResourceCollector
from publication_acceptance_evidence import (
    FULL_RESOURCE_EVIDENCE_FILES,
    accepted_arm_evidence_files,
    pre_finalization_acceptance_evidence_files,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


FINAL_ACCEPTANCE_FILENAME = "checkpoint_publication_acceptance.json"
PENDING_ACCEPTANCE_FILENAME = "checkpoint_publication_candidate.json"
RUN_METADATA_FILENAME = "run_metadata.json"
HARDWARE_EVIDENCE_FILENAME = "hardware_resource_samples.csv"
FINALIZER_KIND = "vast_production_arm_evidence_finalizer_v1"
METADATA_CONTRACT_KIND = "vast_production_arm_publication_run_contract_v1"
EVIDENCE_BUNDLE_KIND = "vast_production_arm_evidence_bundle_v1"
RUNTIME_INPUT_KEYS = MappingProxyType({
    "deepstream": "deepstream_publication_runtime_v3",
    "savant": "savant_publication_runtime_v3",
    "openvino_gva": "openvino_gva_publication_runtime_v3",
    "gstreamer_custom": "gstreamer_custom_publication_runtime_v3",
})
COLLECTOR_READY_TIMEOUT_S = 60.0
COLLECTOR_JOIN_TIMEOUT_S = 30.0
MAX_FINALIZED_EVIDENCE_FILE_BYTES = 64 * 1024 * 1024
MAX_FINALIZED_EVIDENCE_TOTAL_BYTES = 256 * 1024 * 1024
_SHA256_LENGTH = 64


class _Collector(Protocol):
    def start(self) -> None: ...
    def wait_until_ready(self, *, timeout_s: float) -> None: ...
    def stop(self) -> None: ...
    def join(self, *, timeout: float) -> None: ...
    def is_alive(self) -> bool: ...
    def raise_if_failed(self) -> None: ...


CollectorFactory = Callable[..., _Collector]
PrecommitGuard = Callable[[], None]
PhysicalFaultHook = Callable[[str], None]


def _adapter_types() -> tuple[type[BaseException], type[BaseException], type[Any]]:
    # Imported lazily to avoid an adapter/finalizer module import cycle.
    from checkpoint_publication_launcher_adapter_v3 import (
        NativePublicationOutcomeV3,
        NativePublicationPermanentErrorV3,
        NativePublicationTransientErrorV3,
    )

    return (
        NativePublicationPermanentErrorV3,
        NativePublicationTransientErrorV3,
        NativePublicationOutcomeV3,
    )


def _permanent(blocker: str) -> BaseException:
    permanent, _transient, _outcome = _adapter_types()
    return permanent(blocker)


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as error:
        raise _permanent("production_finalizer_material_not_canonical") from error


def _canonical_file_bytes(value: object) -> bytes:
    return _canonical_bytes(value) + b"\n"


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _valid_sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == _SHA256_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )


def native_candidate_evidence_files_v1(policy: object) -> tuple[str, ...]:
    """Return the exact native pending namespace consumed by the finalizer."""

    return (
        *pre_finalization_acceptance_evidence_files(policy),
        "resource_intervals.csv",
        "fanout_work_counters.csv",
        PENDING_ACCEPTANCE_FILENAME,
    )


def finalized_production_evidence_files_v1(policy: object) -> tuple[str, ...]:
    """Return the exact child evidence namespace committed to ABI v3."""

    return (
        *accepted_arm_evidence_files(policy, full_resource=True),
        FINAL_ACCEPTANCE_FILENAME,
        RUN_METADATA_FILENAME,
    )


def default_hardware_collector_factory_v1(
    path: Path, *, run_id: str
) -> HardwareResourceCollector:
    return HardwareResourceCollector(path, run_id=run_id, interval_s=1.0)


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _snapshot(info: os.stat_result) -> tuple[int, ...]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
        int(getattr(info, "st_file_attributes", 0)),
    )


def _held_payload(path: Path, *, blocker: str) -> bytes:
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(before)
            or int(before.st_nlink) != 1
            or not 0 < int(before.st_size) <= MAX_FINALIZED_EVIDENCE_FILE_BYTES
        ):
            raise OSError("invalid")
        payload = path.read_bytes()
        after = path.lstat()
    except OSError as error:
        raise _permanent(blocker) from error
    if _snapshot(before) != _snapshot(after) or len(payload) != int(after.st_size):
        raise _permanent(blocker)
    return payload


def _commit_or_adopt_exact(
    path: Path,
    payload: bytes,
    *,
    blocker: str,
    label: str,
    fault_hook: PhysicalFaultHook | None = None,
) -> tuple[int, int]:
    """Durably publish one immutable finalizer leaf, or adopt exact bytes.

    The atomic transaction namespace is rooted beside the arm output directory,
    so a hard crash cannot expose a partial leaf or pollute the exact child
    evidence namespace.  Exact retry preserves an already-published inode.
    """

    try:
        output = path.parent
        with PhysicalRootCustodyV1.open(
            output.parent,
            label=f"{label} publication parent",
        ) as custody:
            relative = f"{output.name}/{path.name}"
            descriptor, identity, _disposition = (
                custody.commit_or_adopt_exact_identity(
                    relative,
                    payload,
                    label=label,
                    mode=0o444,
                    create_parents=False,
                    after_publish_step=fault_hook,
                )
            )
            expected = {
                "path": relative,
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
            if descriptor != expected:
                raise PublicationPhysicalIoV1Error(
                    f"{label} descriptor drifted after atomic commit"
                )
            return identity
    except PublicationPhysicalIoV1Error as error:
        raise _permanent(blocker) from error


def _runtime_finalization_contract(
    request: Any,
) -> tuple[dict[str, Any], tuple[str, ...], Path]:
    runtime = request.runtime_inputs
    if type(runtime) is not MappingProxyType and not isinstance(runtime, Mapping):
        raise _permanent("production_runtime_inputs_missing")
    system = str(request.system)
    runtime_key = RUNTIME_INPUT_KEYS.get(system)
    dataset = runtime.get("dataset")
    contract = dataset.get(runtime_key) if isinstance(dataset, Mapping) else None
    policy = runtime.get("policy")
    raw_names = native_candidate_evidence_files_v1(policy)
    final_names = finalized_production_evidence_files_v1(policy)
    mapping = contract.get("evidence_mapping") if isinstance(contract, Mapping) else None
    if (
        runtime_key is None
        or type(contract) is not dict
        or contract.get("defer_full_resource_acceptance") is not True
        or type(mapping) is not dict
        or set(mapping) != set(raw_names)
        or len(mapping) != len(raw_names)
        or len(set(mapping.values())) != len(mapping)
        or any(
            type(name) is not str
            or not name
            or Path(name).name != name
            for name in (*mapping.keys(), *mapping.values())
        )
    ):
        raise _permanent("production_native_candidate_contract_not_q4_bound")
    if (
        set(request.launcher_evidence_files) != set(final_names)
        or len(request.launcher_evidence_files) != len(final_names)
    ):
        raise _permanent("production_finalized_evidence_contract_drifted")
    scratch_raw = contract.get("scratch_root")
    if type(scratch_raw) is not str or not scratch_raw:
        raise _permanent("production_finalizer_scratch_root_invalid")
    try:
        scratch = Path(scratch_raw).resolve(strict=True)
        info = scratch.lstat()
    except (OSError, RuntimeError) as error:
        raise _permanent("production_finalizer_scratch_root_invalid") from error
    if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
        raise _permanent("production_finalizer_scratch_root_invalid")
    return copy.deepcopy(contract), raw_names, scratch


def _staged_request(request: Any, *, output_dir: Path, names: tuple[str, ...]) -> Any:
    request_type = type(request)
    return request_type(
        system=request.system,
        topology_kind=request.topology_kind,
        scenario=request.scenario,
        project_root=request.project_root,
        output_dir=output_dir,
        arm_contract_path=request.arm_contract_path,
        arm_contract_file_sha256=request.arm_contract_file_sha256,
        run_id=request.run_id,
        arm_id=request.arm_id,
        runtime_inputs=MappingProxyType(copy.deepcopy(dict(request.runtime_inputs))),
        launcher_evidence_files=names,
        environment=request.environment,
        native_argv=request.native_argv,
    )


def _run_native_with_collector(
    *,
    request: Any,
    native_runner: Callable[[Any], Any],
    collector_factory: CollectorFactory,
    hardware_path: Path,
) -> Any:
    permanent, _transient, outcome_type = _adapter_types()
    collector: _Collector | None = None
    collector_started = False
    collector_stopped = False
    collector_joined = False
    runtime_error: BaseException | None = None
    returned: Any = None
    try:
        collector = collector_factory(hardware_path, run_id=request.run_id)
        collector.start()
        collector_started = True
        collector.wait_until_ready(timeout_s=COLLECTOR_READY_TIMEOUT_S)
        try:
            returned = native_runner(request)
        except BaseException as error:
            runtime_error = error
        finally:
            collector.stop()
            collector_stopped = True
            collector.join(timeout=COLLECTOR_JOIN_TIMEOUT_S)
            collector_joined = True
        if collector.is_alive():
            raise permanent("production_hardware_collector_stop_timeout")
        try:
            collector.raise_if_failed()
        except BaseException as error:
            raise permanent("production_hardware_collector_failed") from error
        if runtime_error is not None:
            raise runtime_error
        if type(returned) is not outcome_type:
            raise permanent("native_runtime_terminal_outcome_invalid")
        return returned
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException:
        raise
    finally:
        if collector is not None and collector_started and not collector_stopped:
            try:
                collector.stop()
            except BaseException:
                pass
        if collector is not None and collector_started and not collector_joined:
            try:
                collector.join(timeout=COLLECTOR_JOIN_TIMEOUT_S)
            except BaseException:
                pass


def _validate_staged_namespace(
    staging: Path, *, expected_names: set[str]
) -> dict[str, bytes]:
    try:
        entries = tuple(staging.iterdir())
    except OSError as error:
        raise _permanent("production_native_staging_namespace_unreadable") from error
    if (
        len(entries) != len({entry.name.casefold() for entry in entries})
        or {entry.name for entry in entries} != expected_names
    ):
        raise _permanent("production_native_staging_namespace_drifted")
    return {
        name: _held_payload(
            staging / name,
            blocker="production_native_staging_evidence_invalid",
        )
        for name in sorted(expected_names)
    }


def _build_metadata(
    *,
    request: Any,
    arm_contract: Mapping[str, Any],
    acceptance: Mapping[str, Any],
) -> dict[str, Any]:
    runtime = dict(request.runtime_inputs)
    dataset = runtime["dataset"]
    dataset_name = dataset.get("name") if isinstance(dataset, Mapping) else None
    if type(dataset_name) is not str or not dataset_name:
        raise _permanent("production_run_metadata_dataset_binding_invalid")
    execution = copy.deepcopy(arm_contract["full_publication_execution_binding"])
    identity_sha = arm_contract["identity_artifact_binding_sha256"]
    grants = {
        "pre_run_resource_capability_grant": {
            "grant_sha256": arm_contract["resource_capability_grant_sha256"],
            "identity_artifact_binding_sha256": identity_sha,
        },
        "pre_run_backend_runtime_grant": {
            "grant_sha256": arm_contract["backend_runtime_grant_sha256"],
            "identity_artifact_binding_sha256": identity_sha,
        },
        "pre_run_model_parity_grant": {
            "grant_sha256": arm_contract["model_parity_grant_sha256"],
            "identity_artifact_binding_sha256": identity_sha,
            "parity_acceptance_binding_sha256": arm_contract[
                "model_parity_acceptance_binding_sha256"
            ],
        },
    }
    publication_contract = {
        "schema_version": 1,
        "artifact_kind": METADATA_CONTRACT_KIND,
        "identity_artifact_binding_sha256": identity_sha,
        "full_publication_execution_binding": execution,
        **grants,
    }
    publication_contract_identity = {
        "schema_version": 1,
        "sha256": _canonical_sha256(publication_contract),
    }
    evidence_bundle = {
        "schema_version": 1,
        "artifact_kind": EVIDENCE_BUNDLE_KIND,
        "run_id": request.run_id,
        "evidence_sha256": copy.deepcopy(acceptance["evidence_sha256"]),
    }
    evidence_identity = {
        "schema_version": 1,
        "sha256": _canonical_sha256(evidence_bundle),
    }
    result = {
        "status": "completed",
        "system": runtime["system"],
        "scenario": runtime["scenario"],
        "policy": runtime["policy"],
        "dataset": dataset_name,
        "repeat": runtime["repeat_index"],
        "streams": runtime["streams"],
        "duration_s": runtime["duration_s"],
        "seed": runtime["base_seed"],
        "run_seed": runtime["run_seed"],
        "deadline_ms": runtime["deadline_ms"],
        "distributed": False,
        "deployment_mode": "heterogeneous",
        "host_topology": "single_host",
        "run_mode": "benchmark",
        "telemetry_source": "native",
    }
    return {
        "schema_version": 2,
        "artifact_kind": FINALIZER_KIND,
        "mode": "benchmark",
        "run_seed": runtime["run_seed"],
        "result": result,
        "publication_run_contract": publication_contract,
        "publication_run_contract_identity": publication_contract_identity,
        "publication_evidence_bundle": evidence_bundle,
        "publication_evidence_bundle_identity": evidence_identity,
        "arm_contract_file_sha256": request.arm_contract_file_sha256,
        "arm_contract_sha256": arm_contract["contract_sha256"],
        "dispatch_resolution_sha256": arm_contract["dispatch_resolution"][
            "resolution_sha256"
        ],
    }


def _bind_acceptance_to_metadata(
    *,
    request: Any,
    arm_contract: Mapping[str, Any],
    acceptance: Mapping[str, Any],
    metadata: Mapping[str, Any],
    metadata_payload: bytes,
) -> dict[str, Any]:
    execution = copy.deepcopy(arm_contract["full_publication_execution_binding"])
    binding: dict[str, Any] = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_acceptance_metadata_binding",
        "run_metadata_file": RUN_METADATA_FILENAME,
        "run_metadata_size_bytes": len(metadata_payload),
        "run_metadata_sha256": hashlib.sha256(metadata_payload).hexdigest(),
        "publication_run_contract_identity": copy.deepcopy(
            metadata["publication_run_contract_identity"]
        ),
        "publication_evidence_bundle_identity": copy.deepcopy(
            metadata["publication_evidence_bundle_identity"]
        ),
        "identity_artifact_binding_sha256": arm_contract[
            "identity_artifact_binding_sha256"
        ],
        "resource_capability_grant_sha256": arm_contract[
            "resource_capability_grant_sha256"
        ],
        "backend_runtime_grant_sha256": arm_contract[
            "backend_runtime_grant_sha256"
        ],
        "model_parity_grant_sha256": arm_contract[
            "model_parity_grant_sha256"
        ],
        "model_parity_acceptance_binding_sha256": arm_contract[
            "model_parity_acceptance_binding_sha256"
        ],
        "backend_publication_arm_contract_authority": {
            "path": request.arm_contract_path.name,
            "size_bytes": request.arm_contract_path.stat().st_size,
            "sha256": request.arm_contract_file_sha256,
            "contract_sha256": arm_contract["contract_sha256"],
        },
        # The outer transaction owns and commits this receipt after semantic
        # validation.  A child must never fabricate a future receipt authority.
        "backend_publication_output_receipt_authority": None,
        "execution_binding": execution,
    }
    binding["binding_sha256"] = _canonical_sha256(binding)
    committed = copy.deepcopy(dict(acceptance))
    committed["publication_metadata_binding"] = binding
    return committed


def validate_production_arm_finalization_contract_v1(
    *, request: Any, arm_contract: Mapping[str, Any]
) -> dict[str, Any]:
    """Validate the immutable Q4/raw/finalization binding without starting work."""

    permanent, _transient, _outcome_type = _adapter_types()
    runtime_contract, raw_names, scratch = _runtime_finalization_contract(request)
    if (
        type(arm_contract) is not dict
        or arm_contract.get("runtime_inputs") != dict(request.runtime_inputs)
        or arm_contract.get("full_publication_execution_binding", {}).get("arm_id")
        != request.arm_id
        or arm_contract.get("contract_sha256") is None
        or any(
            not _valid_sha(arm_contract.get(field))
            for field in (
                "resource_capability_grant_sha256",
                "backend_runtime_grant_sha256",
                "model_parity_grant_sha256",
                "model_parity_acceptance_binding_sha256",
                "identity_artifact_binding_sha256",
            )
        )
    ):
        raise permanent("production_finalizer_arm_crossbinding_invalid")
    return {
        "runtime_contract": runtime_contract,
        "raw_evidence_files": raw_names,
        "scratch_root": scratch,
    }


def finalize_production_arm_evidence_v1(
    *,
    request: Any,
    arm_contract: Mapping[str, Any],
    native_runner: Callable[[Any], Any],
    collector_factory: CollectorFactory | None = None,
    precommit_guard: PrecommitGuard | None = None,
    _fault_hook: Callable[[str], None] | None = None,
) -> Any:
    """Run, collect, validate, promote, crossbind, and commit one arm.

    This function does not authorize a launch.  Its caller must first validate
    launcher authority, grant pins, the Q4 cell binding, and the full coordinate.
    """

    permanent, _transient, outcome_type = _adapter_types()
    validated = validate_production_arm_finalization_contract_v1(
        request=request,
        arm_contract=arm_contract,
    )
    raw_names = validated["raw_evidence_files"]
    scratch = validated["scratch_root"]
    factory = collector_factory or default_hardware_collector_factory_v1
    with tempfile.TemporaryDirectory(
        prefix=f"vast-production-finalizer-{request.arm_id}-",
        dir=str(scratch),
    ) as temporary:
        work = Path(temporary).resolve(strict=True)
        staging = work / "native"
        try:
            staging.mkdir(mode=0o700)
        except OSError as error:
            raise permanent("production_native_staging_create_failed") from error
        hardware_staging = work / f".{HARDWARE_EVIDENCE_FILENAME}.host"
        staged_request = _staged_request(
            request,
            output_dir=staging,
            names=raw_names,
        )
        outcome = _run_native_with_collector(
            request=staged_request,
            native_runner=native_runner,
            collector_factory=factory,
            hardware_path=hardware_staging,
        )
        if outcome.exit_code != 0:
            return outcome
        staged_payloads = _validate_staged_namespace(
            staging,
            expected_names=set(raw_names),
        )
        hardware_payload = _held_payload(
            hardware_staging,
            blocker="production_hardware_evidence_custody_invalid",
        )
        _commit_or_adopt_exact(
            staging / HARDWARE_EVIDENCE_FILENAME,
            hardware_payload,
            blocker="production_hardware_evidence_promotion_failed",
            label="production hardware evidence",
            fault_hook=(
                None
                if _fault_hook is None
                else lambda step: _fault_hook(f"hardware_evidence:{step}")
            ),
        )
        staged_payloads[HARDWARE_EVIDENCE_FILENAME] = hardware_payload
        try:
            acceptance = prepare_checkpoint_publication_acceptance(
                output_dir=staging,
                expected_run_id=request.run_id,
                expected_system=request.system,
                expected_scenario=request.scenario,
                expected_codec=request.runtime_inputs["codec"],
                expected_policy=request.runtime_inputs["policy"],
                expected_deadline_ms=request.runtime_inputs["deadline_ms"],
                topology_kind=request.topology_kind,
                hardware_collector_stopped=True,
            )
        except Exception as error:
            raise permanent("production_full_resource_promotion_failed") from error

        accepted_names = accepted_arm_evidence_files(
            request.runtime_inputs["policy"], full_resource=True
        )
        if (
            set(acceptance.get("evidence_sha256", {})) != set(accepted_names)
            or set(acceptance.get("full_resource_evidence_sha256", {}))
            != set(FULL_RESOURCE_EVIDENCE_FILES)
        ):
            raise permanent("production_full_resource_acceptance_set_drifted")
        for name in accepted_names:
            payload = staged_payloads[name]
            if hashlib.sha256(payload).hexdigest() != acceptance["evidence_sha256"][name]:
                raise permanent("production_promoted_evidence_hash_drifted")

        metadata = _build_metadata(
            request=request,
            arm_contract=arm_contract,
            acceptance=acceptance,
        )
        metadata_payload = _canonical_file_bytes(metadata)
        committed_acceptance = _bind_acceptance_to_metadata(
            request=request,
            arm_contract=arm_contract,
            acceptance=acceptance,
            metadata=metadata,
            metadata_payload=metadata_payload,
        )
        acceptance_payload = _canonical_file_bytes(committed_acceptance)
        total_size = sum(len(staged_payloads[name]) for name in accepted_names)
        total_size += len(metadata_payload) + len(acceptance_payload)
        if total_size > MAX_FINALIZED_EVIDENCE_TOTAL_BYTES:
            raise permanent("production_finalized_evidence_total_size_exceeded")

        if precommit_guard is not None:
            try:
                precommit_guard()
            except permanent:
                raise
            except (KeyboardInterrupt, SystemExit):
                raise
            except BaseException as error:
                raise permanent("production_precommit_guard_failed") from error

        output = Path(request.output_dir)
        for name in accepted_names:
            _commit_or_adopt_exact(
                output / name,
                staged_payloads[name],
                blocker="production_finalized_evidence_commit_failed",
                label=f"production finalized evidence {name}",
                fault_hook=(
                    None
                    if _fault_hook is None
                    else lambda step, leaf=name: _fault_hook(
                        f"final_evidence:{leaf}:{step}"
                    )
                ),
            )
        _commit_or_adopt_exact(
            output / RUN_METADATA_FILENAME,
            metadata_payload,
            blocker="production_run_metadata_commit_failed",
            label="production run metadata",
            fault_hook=(
                None
                if _fault_hook is None
                else lambda step: _fault_hook(f"run_metadata:{step}")
            ),
        )
        _commit_or_adopt_exact(
            output / FINAL_ACCEPTANCE_FILENAME,
            acceptance_payload,
            blocker="production_final_acceptance_commit_failed",
            label="production final acceptance",
            fault_hook=(
                None
                if _fault_hook is None
                else lambda step: _fault_hook(f"final_acceptance:{step}")
            ),
        )
        return outcome_type(exit_code=0)


__all__ = [
    "COLLECTOR_JOIN_TIMEOUT_S",
    "COLLECTOR_READY_TIMEOUT_S",
    "FINAL_ACCEPTANCE_FILENAME",
    "HARDWARE_EVIDENCE_FILENAME",
    "PENDING_ACCEPTANCE_FILENAME",
    "RUN_METADATA_FILENAME",
    "default_hardware_collector_factory_v1",
    "finalize_production_arm_evidence_v1",
    "finalized_production_evidence_files_v1",
    "native_candidate_evidence_files_v1",
    "validate_production_arm_finalization_contract_v1",
]
