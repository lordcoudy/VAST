#!/usr/bin/env python3
"""Fail-closed two-phase executor for the exact physical backend Q4 matrix.

Phase A is deliberately non-authorizing: it executes 560 native qualification
cells and promotes the resulting graph through the physical Q4 persistence
boundary.  Only a subsequently loaded full-publication identity may yield a
backend grant.  Phase B uses that grant for the same 560 coordinates and then
commits 280 two-topology sizing pairs.

Public arbitrary-Q4 runtime materialization, native qualification, and graph
finalization have fail-closed production defaults.  Dependency overrides are
retained only as test seams; the production arm remains a fixed repository
adapter.  This module owns ordering, durable fences, checkpoint recovery,
physical artifact closure, and the authorization boundary; it does not weaken
the separate exact-32 pilot executor.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import socket
import stat
import subprocess
import sys
import tempfile
import urllib.parse
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Callable, Iterator, Mapping, Protocol, Sequence

from backend_pair_archive_sizing_receipts_v1 import (
    AUTHORITY_ENVELOPE_KIND as PRODUCTION_AUTHORITY_ENVELOPE_KIND,
    build_backend_pair_archive_sizing_input_v1,
    load_operator_sizing_rows_v1,
    materialize_backend_pair_archive_sizing_receipts_v1,
    persist_backend_production_output_receipt_authority_v1,
)
from backend_publication_dispatch_v3 import (
    ARM_CONTRACT_FILENAME,
    LAUNCH_FENCE_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
    build_backend_publication_arm_contract_v3,
    build_backend_publication_dispatch_resolution_v3,
    canonical_backend_publication_arm_contract_bytes_v3,
)
from backend_publication_output_transaction_production_v3 import (
    PRODUCTION_EXECUTION_SCOPE,
    semantic_evidence_validator_identity_v3,
    prepare_backend_publication_production_transaction_v3,
    run_or_resume_backend_publication_production_transaction_v3,
)
from production_parent_artifact_pin_store_v1 import (
    ProductionParentArtifactPinStoreV1,
)
from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
    validate_publication_launcher_invocation_v3,
)
from backend_runtime_grant import (
    GRANT_V3_KIND,
    backend_runtime_grant_from_identity_artifacts,
    validate_pre_run_backend_runtime_grant_v3,
)
from backend_runtime_qualification_v4_catalog import (
    ARTIFACT_KIND as Q4_CATALOG_KIND,
    SCHEMA_VERSION as Q4_CATALOG_SCHEMA_VERSION,
    STATUS as Q4_CATALOG_STATUS,
    build_backend_runtime_qualification_v4_catalog,
)
from backend_runtime_qualification_v4_input_index import (
    ARTIFACT_KIND as Q4_INPUT_INDEX_KIND,
    SCHEMA_VERSION as Q4_INPUT_INDEX_SCHEMA_VERSION,
    build_backend_runtime_qualification_v4_input_index,
)
from backend_runtime_qualification_v4_persistence import (
    BINDING_INDEX_FILENAME as Q4_BINDING_INDEX_FILENAME,
    load_backend_runtime_qualification_v4_binding,
    promote_backend_runtime_qualification_v4,
)
from backend_runtime_validation_records_v2 import (
    CONTEXT_KIND as VALIDATION_CONTEXT_KIND,
    INDEX_KIND as VALIDATION_INDEX_KIND,
    QUALIFIED_REPLAY_RESULT,
    RECORD_KIND as VALIDATION_RECORD_KIND,
    REQUEST_KIND as VALIDATION_REQUEST_KIND,
    SCHEMA_VERSION as VALIDATION_RECORD_SCHEMA_VERSION,
    SHARD_KIND as VALIDATION_SHARD_KIND,
    build_backend_runtime_validation_index_v2,
    build_backend_runtime_validation_record_v2,
    build_backend_runtime_validation_request_v2,
    build_backend_runtime_validation_system_context_v2,
    build_backend_runtime_validation_system_shard_v2,
    canonical_identity as validation_canonical_identity,
)
from backend_runtime_validation_runner_authority import (
    assess_backend_runtime_validation_runner_authority,
    validate_backend_runtime_validation_runner_authority,
)
from backend_runtime_validator_authority_v4 import (
    assess_backend_runtime_validator_authority_v4,
    validate_backend_runtime_validator_authority_v4,
)
from full_publication_identity_artifacts import (
    load_full_publication_identity_artifacts,
)
from full_publication_identity_manifest_v2 import (
    build_full_publication_identity_manifest_v2,
)
from benchmark_contract import (
    resource_capability_grant_from_identity_artifacts,
    validate_pre_run_resource_capability_grant,
)
from model_parity_grant import (
    model_parity_grant_from_identity_artifacts,
    validate_pre_run_model_parity_grant,
)
from checkpoint_deepstream_publication_runtime_v3 import (
    run_checkpoint_deepstream_publication_runtime_v3,
)
from checkpoint_gstreamer_publication_runtime_v3 import (
    run_checkpoint_gstreamer_publication_runtime_v3,
)
from checkpoint_openvino_gva_publication_runtime_v3 import (
    run_checkpoint_openvino_gva_publication_runtime_v3,
)
from checkpoint_publication_launcher_adapter_v3 import (
    NativePublicationOutcomeV3,
    NativePublicationRequestV3,
)
from checkpoint_savant_publication_runtime_v3 import (
    run_checkpoint_savant_publication_runtime_v3,
)
from collect_metrics import HardwareResourceCollector
from publication_q4_runtime_contract_v4 import (
    PublicationQ4RuntimeContractV4Error,
    build_publication_runtime_contract_v4,
    qualification_launcher_evidence_files_v4,
    select_publication_q4_runtime_material_v4,
    validate_publication_q4_runtime_candidate_registry_v4,
    validate_publication_runtime_contract_v4,
)
from publication_q4_evidence_validator_v4 import (
    build_publication_q4_raw_evidence_manifest_v4,
)
from publication_physical_io_v1 import (
    PhysicalRootCustodyV1,
    PublicationPhysicalIoV1Error,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
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

WARMUP_S = 30
MEASUREMENT_S = 180
STREAMS = 6
SEED = 20260323
CELL_COUNT = 560
PAIR_COUNT = 280

EXIT_OK = 0
EXIT_TRANSIENT = 75
EXIT_PERMANENT = 78

SOURCE_REGISTRY_KIND = "vast_backend_q4_two_phase_source_registry_v1"
CHECKPOINT_KIND = "vast_backend_q4_two_phase_checkpoint_v1"
PHASE_A_INPUT_KIND = "vast_backend_q4_phase_a_input_v1"
PHASE_A_FENCE_KIND = "vast_backend_q4_phase_a_durable_fence_v1"
PHASE_A_RECORD_KIND = "vast_backend_q4_phase_a_record_v1"
PHASE_A_FINAL_KIND = "vast_backend_q4_phase_a_finalization_v1"
BOUNDARY_RECORD_KIND = "vast_backend_q4_identity_grant_boundary_v1"
PHASE_B_RECORD_KIND = "vast_backend_q4_phase_b_record_v1"
SIZING_FINAL_KIND = "vast_backend_q4_pair_sizing_finalization_v1"
MATERIALIZED_RUNTIME_INPUT_KIND = (
    "vast_backend_q4_materialized_runtime_input_v4"
)
RAW_EVIDENCE_MANIFEST_KIND = "vast_publication_q4_raw_evidence_manifest_v4"
NATIVE_VALIDATION_REQUEST_CANDIDATE_KIND = (
    "vast_publication_q4_native_validation_request_candidate_v4"
)
NATIVE_VALIDATION_RECORD_CANDIDATE_KIND = (
    "vast_publication_q4_native_validation_record_candidate_v4"
)
RAW_EVIDENCE_MANIFEST_FILENAME = "raw-evidence-manifest-v4.json"
NATIVE_RUNTIME_DIRECTORY = "native-runtime-v4"
PUBLICATION_RUNTIME_CONTRACT_FILENAME = "publication-runtime-contract-v4.json"
HARDWARE_EVIDENCE_FILENAME = "hardware_resource_samples.csv"

CHECKPOINT_FILENAME = "checkpoint_backend_q4_two_phase_executor_v1.json"
PHASE_A_INPUT_FILENAME = "qualification-input.json"
PHASE_A_FENCE_FILENAME = "qualification-launch-fence.json"
PHASE_A_REQUEST_FILENAME = "qualification-request.json"
PHASE_A_VALIDATION_RECORD_FILENAME = "validation-record.json"
PHASE_A_RECORD_FILENAME = "qualification-record.json"
PHASE_A_GRAPH_RECORD_FILENAME = "qualification-graph-record.json"
PHASE_A_FINAL_FILENAME = "phase-a-finalization.json"
BOUNDARY_RECORD_FILENAME = "identity-grant-boundary.json"
GRANT_FILENAME = "backend-runtime-grant-v3.json"
PHASE_B_RECORD_FILENAME = "production-record.json"
SIZING_INPUT_FILENAME = "backend-pair-sizing-input-v1.json"
SIZING_FINAL_FILENAME = "pair-sizing-finalization.json"
SIZING_INDEX_FILENAME = "checkpoint_backend_pair_archive_sizing_index_v1.json"
LOCK_FILENAME = ".backend-q4-two-phase-executor-v1.lock"

PRODUCTION_RECEIPT_CHAIN_KIND = (
    "vast_backend_q4_production_receipt_chain_binding_v1"
)
PRODUCTION_RUN_IDENTITY_KIND = "vast_backend_q4_production_run_identity_v1"
PHASE1_PLAN_RECEIPT_KIND = "vast_publication_q4_authority_plan_phase1_receipt_v1"
PHASE2_PLAN_RECEIPT_KIND = "vast_publication_q4_source_plan_phase2_receipt_v1"
SOURCE_MATERIALIZATION_RESULT_KIND = (
    "vast_backend_q4_two_phase_source_registry_materialization_result_v1"
)
_SCENARIO_BY_TOPOLOGY = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}
_PRODUCTION_RUN_SEED_GROUP = "kpp_iss_publication_v3_codecs_v1"
_PRODUCTION_CONTEXT_FIELDS = frozenset(
    {
        "phase1_receipt_path",
        "phase1_receipt_file_sha256",
        "phase1_receipt_sha256",
        "phase2_receipt_path",
        "phase2_receipt_file_sha256",
        "phase2_receipt_sha256",
        "source_materialization_result_path",
        "source_materialization_result_file_sha256",
        "source_materialization_result_sha256",
    }
)
_PRODUCTION_CONTEXT_TEST_SEAMS = frozenset(
    {"production_receipt_loader", "production_runtime_bind_mount_loader"}
)
_PRODUCTION_CONTEXT_PREPARED_FIELDS = frozenset(
    {"production_receipt_chain", "production_runtime_bind_mount"}
)
_CLI_OPTIONS = (
    "--project-root",
    "--source-registry",
    "--work-dir",
    "--identity-manifest-output",
    "--phase1-receipt",
    "--phase1-receipt-file-sha256",
    "--phase1-receipt-sha256",
    "--phase2-receipt",
    "--phase2-receipt-file-sha256",
    "--phase2-receipt-sha256",
    "--source-materialization-result",
    "--source-materialization-result-file-sha256",
    "--source-materialization-result-sha256",
    "--through-phase",
)

_SHA_RE = re.compile(r"[0-9a-f]{64}")
_DESCRIPTOR_FIELDS = {"path", "size_bytes", "sha256"}
_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)
_MAX_CUSTODY_CAPTURE_BYTES = 1024 * 1024 * 1024
_MAX_CUSTODY_DESCRIPTOR_BYTES = 1 << 50
_ACTIVE_PHYSICAL_CUSTODY: ContextVar[PhysicalRootCustodyV1 | None] = ContextVar(
    "backend_q4_two_phase_physical_custody_v1", default=None
)

_NATIVE_RUNTIME_REGISTRY = {
    "deepstream": run_checkpoint_deepstream_publication_runtime_v3,
    "savant": run_checkpoint_savant_publication_runtime_v3,
    "openvino_gva": run_checkpoint_openvino_gva_publication_runtime_v3,
    "gstreamer_custom": run_checkpoint_gstreamer_publication_runtime_v3,
}


class BackendQ4TwoPhaseExecutorV1Error(RuntimeError):
    """Closed executor failure carrying the process-level exit classification."""

    def __init__(self, blocker: str, *, exit_code: int = EXIT_PERMANENT) -> None:
        if exit_code not in {EXIT_TRANSIENT, EXIT_PERMANENT}:
            raise ValueError("executor errors may only use exit codes 75 or 78")
        self.blocker = blocker
        self.exit_code = exit_code
        super().__init__(blocker)


def _fail(blocker: str, *, exit_code: int = EXIT_PERMANENT) -> None:
    raise BackendQ4TwoPhaseExecutorV1Error(blocker, exit_code=exit_code)


def _canonical_bytes(value: Any, *, newline: bool = True) -> bytes:
    try:
        text = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        _fail(f"artifact is not canonical JSON: {error}")
    return (text + ("\n" if newline else "")).encode("ascii")


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value, newline=False)).hexdigest()


def _seal(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    material = copy.deepcopy(dict(value))
    if field in material:
        _fail(f"self-hash field {field} was supplied by caller")
    material[field] = _canonical_sha(material)
    return material


def _validate_sealed(value: Any, *, field: str, label: str) -> dict[str, Any]:
    if type(value) is not dict or not _SHA_RE.fullmatch(str(value.get(field, ""))):
        _fail(f"{label} is not a sealed object")
    unsigned = {key: item for key, item in value.items() if key != field}
    if value[field] != _canonical_sha(unsigned):
        _fail(f"{label} self-hash drifted")
    return copy.deepcopy(value)


def _deadline_slug(value: int | float) -> str:
    return str(value).replace(".", "p")


@dataclass(frozen=True, slots=True)
class BackendQ4CellV1:
    cell_index: int
    system: str
    codec: str
    topology_kind: str
    policy: str
    deadline_ms: int | float
    warmup_s: int = WARMUP_S
    measurement_s: int = MEASUREMENT_S
    streams: int = STREAMS
    seed: int = SEED

    @property
    def arm_id(self) -> str:
        return (
            f"{self.cell_index:04d}-{self.system}-{self.codec}-"
            f"{self.topology_kind.replace('_', '-')}-"
            f"{self.policy.replace('_', '-')}-{_deadline_slug(self.deadline_ms)}"
        )

    @property
    def coordinate(self) -> dict[str, Any]:
        return {
            "system": self.system,
            "codec": self.codec,
            "topology_kind": self.topology_kind,
            "policy": self.policy,
            "deadline_ms": self.deadline_ms,
            "cell_index": self.cell_index,
        }

    @property
    def frozen_run(self) -> dict[str, int]:
        return {
            "warmup_s": self.warmup_s,
            "measurement_s": self.measurement_s,
            "streams": self.streams,
            "seed": self.seed,
        }


def backend_q4_cells_v1() -> list[BackendQ4CellV1]:
    cells: list[BackendQ4CellV1] = []
    for system in SYSTEMS:
        for codec in CODECS:
            for topology in TOPOLOGIES:
                for policy in POLICIES:
                    for deadline in DEADLINES_MS:
                        cells.append(
                            BackendQ4CellV1(
                                cell_index=len(cells),
                                system=system,
                                codec=codec,
                                topology_kind=topology,
                                policy=policy,
                                deadline_ms=deadline,
                            )
                        )
    if len(cells) != CELL_COUNT or len({cell.arm_id for cell in cells}) != CELL_COUNT:
        _fail("internal Q4 matrix is not the exact frozen 560-cell product")
    return cells


def _missing_adapter(name: str) -> Callable[..., dict[str, Any]]:
    def missing(**_: Any) -> dict[str, Any]:
        _fail(
            f"required physical application adapter is unavailable: {name}",
            exit_code=EXIT_PERMANENT,
        )
    return missing


class BackendQ4ProductionArmAdapterV1(Protocol):
    """One production-v3 arm adapter; implementations must return live authority."""

    def __call__(
        self,
        *,
        project_root: Path,
        source_registry: dict[str, Any],
        source_registry_path: Path,
        cell: BackendQ4CellV1,
        transaction_dir: Path,
        q4_binding: dict[str, Any],
        identity_binding: dict[str, Any],
        backend_runtime_grant: dict[str, Any],
        production_context: dict[str, Any],
    ) -> dict[str, Any]: ...


class BackendQ4NativeQualificationAdapterV1(Protocol):
    """One pre-grant native Q4 cell; it may not consume a production grant."""

    def __call__(self, **kwargs: Any) -> dict[str, Any]: ...


def _required_sha_v1(value: Any, *, label: str) -> str:
    if type(value) is not str or _SHA_RE.fullmatch(value) is None:
        _fail(f"{label} is not a SHA-256 identity")
    return value


def _external_artifact_v1(value: Any, *, label: str) -> dict[str, Any]:
    fields = {
        "artifact_schema_version",
        "artifact_kind",
        "descriptor",
        "content_identity_sha256",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value.get("artifact_schema_version")) is not int
        or value["artifact_schema_version"] < 1
        or type(value.get("artifact_kind")) is not str
        or not value["artifact_kind"]
    ):
        _fail(f"{label} external artifact fields drifted")
    return {
        "artifact_schema_version": value["artifact_schema_version"],
        "artifact_kind": value["artifact_kind"],
        "descriptor": _descriptor(value["descriptor"], label=label),
        "content_identity_sha256": _required_sha_v1(
            value["content_identity_sha256"], label=f"{label} semantic identity"
        ),
    }


def _production_context_values_v1(value: Mapping[str, Any]) -> dict[str, Any]:
    if type(value) is not dict:
        _fail("production context must be an exact object")
    unexpected = (
        set(value)
        - _PRODUCTION_CONTEXT_FIELDS
        - _PRODUCTION_CONTEXT_TEST_SEAMS
        - _PRODUCTION_CONTEXT_PREPARED_FIELDS
    )
    missing = _PRODUCTION_CONTEXT_FIELDS - set(value)
    if unexpected or missing:
        _fail(
            "production context receipt pins drifted: "
            f"missing={sorted(missing)} unexpected={sorted(unexpected)}"
        )
    result = copy.deepcopy(dict(value))
    for key in sorted(_PRODUCTION_CONTEXT_FIELDS):
        item = result[key]
        if type(item) is not str or not item:
            _fail(f"production context {key} is empty")
        if key.endswith("sha256"):
            _required_sha_v1(item, label=f"production context {key}")
    for key in _PRODUCTION_CONTEXT_TEST_SEAMS & set(result):
        if not callable(result[key]):
            _fail(f"production context {key} test seam is not callable")
    for key in _PRODUCTION_CONTEXT_PREPARED_FIELDS & set(result):
        if type(result[key]) is not dict:
            _fail(f"production context {key} prepared binding is not an object")
    return result


def _validate_source_materialization_result_v1(value: Any) -> dict[str, Any]:
    fields = {
        "schema_version",
        "artifact_kind",
        "status",
        "plan_sha256",
        "source_registry",
        "source_registry_sha256",
        "identity_inputs",
        "result_sha256",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or value.get("schema_version") != 1
        or value.get("artifact_kind") != SOURCE_MATERIALIZATION_RESULT_KIND
        or value.get("status")
        != "materialized_accepted_physical_q4_sources"
        or type(value.get("identity_inputs")) is not dict
        or set(value["identity_inputs"])
        != {
            "analytics_model_parity",
            "analytics_execution_layer",
            "policy_qualification",
            "resource_qualification",
        }
    ):
        _fail("Q4 source-materialization result fields/status drifted")
    for key in ("plan_sha256", "source_registry_sha256", "result_sha256"):
        _required_sha_v1(value[key], label=f"source-materialization {key}")
    _descriptor(value["source_registry"], label="source-materialization registry")
    unsigned = {key: item for key, item in value.items() if key != "result_sha256"}
    if value["result_sha256"] != _canonical_sha(unsigned):
        _fail("Q4 source-materialization result self-hash drifted")
    return copy.deepcopy(value)


def load_backend_q4_production_receipt_chain_v1(
    *,
    project_root: Path,
    source_registry_path: Path,
    source_registry: Mapping[str, Any],
    phase1_receipt_path: Path | str,
    phase1_receipt_file_sha256: str,
    phase1_receipt_sha256: str,
    phase2_receipt_path: Path | str,
    phase2_receipt_file_sha256: str,
    phase2_receipt_sha256: str,
    source_materialization_result_path: Path | str,
    source_materialization_result_file_sha256: str,
    source_materialization_result_sha256: str,
) -> dict[str, Any]:
    """Load and cross-bind B3 Phase1/Phase2 plus the source-registry result.

    The three external receipts are independently pinned by raw file and
    semantic SHA-256.  The returned binding contains descriptors and identities
    only; no receipt is allowed to inject a grant or execution authority.
    """

    root = _physical_root(project_root)
    source_path = _under_root(
        root, source_registry_path, label="Q4 source registry", must_exist=True
    )
    source_descriptor = _descriptor_for(
        root, source_path, label="Q4 source registry"
    )
    if source_registry.get("registry_sha256") is None:
        _fail("Q4 source registry semantic identity is unavailable")
    registry_sha = _required_sha_v1(
        source_registry["registry_sha256"], label="Q4 source registry"
    )
    try:
        from publication_q4_authority_plan_pipeline_v1 import (
            load_publication_q4_authority_plan_phase1_receipt_v1,
            load_publication_q4_source_plan_phase2_receipt_v1,
        )

        phase1 = load_publication_q4_authority_plan_phase1_receipt_v1(
            project_root=root,
            receipt_path=phase1_receipt_path,
            expected_receipt_file_sha256=_required_sha_v1(
                phase1_receipt_file_sha256, label="Phase1 receipt raw file"
            ),
            expected_receipt_sha256=_required_sha_v1(
                phase1_receipt_sha256, label="Phase1 receipt semantic"
            ),
        )
        phase2 = load_publication_q4_source_plan_phase2_receipt_v1(
            project_root=root,
            receipt_path=phase2_receipt_path,
            expected_receipt_file_sha256=_required_sha_v1(
                phase2_receipt_file_sha256, label="Phase2 receipt raw file"
            ),
            expected_receipt_sha256=_required_sha_v1(
                phase2_receipt_sha256, label="Phase2 receipt semantic"
            ),
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"B3 Phase1/Phase2 receipt loader rejected production pins: {error}")
    if (
        type(phase1) is not dict
        or phase1.get("artifact_kind") != PHASE1_PLAN_RECEIPT_KIND
        or phase1.get("receipt_sha256") != phase1_receipt_sha256
        or type(phase2) is not dict
        or phase2.get("artifact_kind") != PHASE2_PLAN_RECEIPT_KIND
        or phase2.get("receipt_sha256") != phase2_receipt_sha256
    ):
        _fail("B3 Phase1/Phase2 receipt identity drifted after load")
    phase1_path = _under_root(
        root, phase1_receipt_path, label="Phase1 receipt", must_exist=True
    )
    phase2_path = _under_root(
        root, phase2_receipt_path, label="Phase2 receipt", must_exist=True
    )
    phase1_descriptor = _descriptor_for(root, phase1_path, label="Phase1 receipt")
    phase2_descriptor = _descriptor_for(root, phase2_path, label="Phase2 receipt")
    if (
        phase1_descriptor["sha256"] != phase1_receipt_file_sha256
        or phase2_descriptor["sha256"] != phase2_receipt_file_sha256
    ):
        _fail("B3 receipt raw-file identity changed after official load")
    phase1_ref = _external_artifact_v1(
        phase2.get("phase1_receipt"), label="Phase2 Phase1 receipt"
    )
    if (
        phase1_ref["artifact_schema_version"] != 1
        or phase1_ref["artifact_kind"] != PHASE1_PLAN_RECEIPT_KIND
        or phase1_ref["descriptor"] != phase1_descriptor
        or phase1_ref["content_identity_sha256"] != phase1_receipt_sha256
        or phase2.get("phase1_receipt_sha256") != phase1_receipt_sha256
    ):
        _fail("B3 Phase2 receipt is not cross-bound to the loaded Phase1 receipt")

    result_path = _under_root(
        root,
        source_materialization_result_path,
        label="Q4 source-materialization result",
        must_exist=True,
    )
    result_descriptor = _descriptor_for(
        root, result_path, label="Q4 source-materialization result"
    )
    if result_descriptor["sha256"] != _required_sha_v1(
        source_materialization_result_file_sha256,
        label="Q4 source-materialization result raw file",
    ):
        _fail("Q4 source-materialization result raw-file pin drifted")
    result = _validate_source_materialization_result_v1(
        _load_canonical_json(result_path, label="Q4 source-materialization result")
    )
    if result["result_sha256"] != _required_sha_v1(
        source_materialization_result_sha256,
        label="Q4 source-materialization result semantic",
    ):
        _fail("Q4 source-materialization result semantic pin drifted")

    source_plan = _external_artifact_v1(
        phase2.get("source_registry_path_plan"),
        label="Phase2 source-registry path plan",
    )
    planned_outputs = phase2.get("planned_outputs")
    planned_registry_path = (
        planned_outputs.get("source_registry_path")
        if type(planned_outputs) is dict
        else None
    )
    planned_result_path = (
        planned_outputs.get("source_materialization_result_path")
        if type(planned_outputs) is dict
        else None
    )
    if (
        result["plan_sha256"] != source_plan["content_identity_sha256"]
        or result_descriptor["path"] != planned_result_path
        or result["source_registry"] != source_descriptor
        or result["source_registry_sha256"] != registry_sha
        or planned_registry_path != source_descriptor["path"]
    ):
        _fail("B3 Phase2/source-materialization/source-registry causality drifted")

    runtime_artifact = _external_artifact_v1(
        phase2.get("runtime_candidate_registry"),
        label="Phase2 runtime-candidate registry",
    )
    runtime_descriptor = _descriptor(
        source_registry.get("runtime_candidate_registry"),
        label="Q4 runtime-candidate registry",
    )
    runtime_registry = _load_publication_q4_runtime_candidate_registry_v4(
        project_root=root, source_registry=source_registry
    )
    if (
        runtime_artifact["descriptor"] != runtime_descriptor
        or runtime_artifact["content_identity_sha256"]
        != runtime_registry["registry_sha256"]
    ):
        _fail("B3 Phase2 runtime registry differs from the accepted source registry")

    unsigned = {
        "schema_version": 1,
        "artifact_kind": PRODUCTION_RECEIPT_CHAIN_KIND,
        "phase1_receipt": phase1_descriptor,
        "phase1_receipt_sha256": phase1_receipt_sha256,
        "phase2_receipt": phase2_descriptor,
        "phase2_receipt_sha256": phase2_receipt_sha256,
        "source_materialization_result": result_descriptor,
        "source_materialization_result_sha256": (
            source_materialization_result_sha256
        ),
        "source_registry": source_descriptor,
        "source_registry_sha256": registry_sha,
        "source_registry_path_plan_sha256": source_plan[
            "content_identity_sha256"
        ],
        "runtime_candidate_registry_sha256": runtime_registry["registry_sha256"],
    }
    return {**unsigned, "receipt_chain_sha256": _canonical_sha(unsigned)}


def _load_production_runtime_bind_mount_v1(
    *, project_root: Path
) -> dict[str, Any]:
    try:
        from full_publication_entrypoint import _production_runtime_bind_mount

        value = _production_runtime_bind_mount(project_root=project_root)
    except Exception as error:
        _fail(f"production WSL runtime bind-mount preflight failed: {error}")
    if type(value) is not dict:
        _fail("production WSL runtime bind-mount preflight returned no contract")
    return copy.deepcopy(value)


def _validated_production_receipt_chain_v1(
    value: Any, *, root: Path, revalidate_files: bool
) -> dict[str, Any]:
    fields = {
        "schema_version",
        "artifact_kind",
        "phase1_receipt",
        "phase1_receipt_sha256",
        "phase2_receipt",
        "phase2_receipt_sha256",
        "source_materialization_result",
        "source_materialization_result_sha256",
        "source_registry",
        "source_registry_sha256",
        "source_registry_path_plan_sha256",
        "runtime_candidate_registry_sha256",
        "receipt_chain_sha256",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or value.get("schema_version") != 1
        or value.get("artifact_kind") != PRODUCTION_RECEIPT_CHAIN_KIND
    ):
        _fail("production receipt-chain binding fields drifted")
    for key in (
        "phase1_receipt_sha256",
        "phase2_receipt_sha256",
        "source_materialization_result_sha256",
        "source_registry_sha256",
        "source_registry_path_plan_sha256",
        "runtime_candidate_registry_sha256",
        "receipt_chain_sha256",
    ):
        _required_sha_v1(value[key], label=f"production receipt chain {key}")
    for key in (
        "phase1_receipt",
        "phase2_receipt",
        "source_materialization_result",
        "source_registry",
    ):
        expected = _descriptor(value[key], label=f"production receipt chain {key}")
        if revalidate_files and _revalidate_descriptor(
            root, expected, label=f"production receipt chain {key}"
        ) != expected:
            _fail(f"production receipt chain {key} physical identity drifted")
    unsigned = {key: item for key, item in value.items() if key != "receipt_chain_sha256"}
    if value["receipt_chain_sha256"] != _canonical_sha(unsigned):
        _fail("production receipt-chain binding self-hash drifted")
    return copy.deepcopy(value)


def _prepare_backend_q4_production_context_v1(
    *,
    project_root: Path,
    source_registry_path: Path,
    source_registry: Mapping[str, Any],
    production_context: Mapping[str, Any],
) -> dict[str, Any]:
    context = _production_context_values_v1(production_context)
    if _PRODUCTION_CONTEXT_PREPARED_FIELDS & set(context):
        _fail("caller may not self-supply prepared production context bindings")
    receipt_loader = context.pop(
        "production_receipt_loader", load_backend_q4_production_receipt_chain_v1
    )
    runtime_loader = context.pop(
        "production_runtime_bind_mount_loader",
        _load_production_runtime_bind_mount_v1,
    )
    chain = _validated_production_receipt_chain_v1(
        receipt_loader(
            project_root=project_root,
            source_registry_path=source_registry_path,
            source_registry=copy.deepcopy(dict(source_registry)),
            **context,
        ),
        root=project_root,
        revalidate_files=True,
    )
    if chain["source_registry_sha256"] != source_registry.get("registry_sha256"):
        _fail("prepared production receipt chain belongs to another source registry")
    runtime_binding = runtime_loader(project_root=project_root)
    if type(runtime_binding) is not dict:
        _fail("production runtime bind-mount loader returned no contract")
    _required_sha_v1(
        runtime_binding.get("binding_sha256"),
        label="prepared production runtime bind-mount",
    )
    return {
        **context,
        "production_receipt_chain": chain,
        "production_runtime_bind_mount": copy.deepcopy(runtime_binding),
    }


def _backend_q4_matrix_sha256_v1() -> str:
    return _canonical_sha(
        [
            {"coordinate": cell.coordinate, "frozen_run": cell.frozen_run}
            for cell in backend_q4_cells_v1()
        ]
    )


def _backend_q4_pair_execution_v1(cell: BackendQ4CellV1) -> tuple[int, str]:
    sequence = (
        SYSTEMS.index(cell.system) * len(CODECS) * len(POLICIES) * len(DEADLINES_MS)
        + CODECS.index(cell.codec) * len(POLICIES) * len(DEADLINES_MS)
        + POLICIES.index(cell.policy) * len(DEADLINES_MS)
        + DEADLINES_MS.index(cell.deadline_ms)
    )
    if not 0 <= sequence < PAIR_COUNT:
        _fail("internal Phase-B pair sequence escaped the frozen 280 pairs")
    pair_id = (
        f"q4-pair-{sequence:03d}-{cell.system}-{cell.codec}-"
        f"{cell.policy.replace('_', '-')}-{_deadline_slug(cell.deadline_ms)}"
    )
    return sequence, pair_id


def _backend_q4_run_seed_v1(cell: BackendQ4CellV1) -> int:
    payload = (
        f"{cell.seed}:{_PRODUCTION_RUN_SEED_GROUP}::"
        f"{cell.streams}:0"
    )
    return int(hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12], 16) % (
        2**31 - 1
    )


def materialize_backend_q4_production_v3_arm_v1(
    *,
    project_root: Path,
    source_registry: dict[str, Any],
    source_registry_path: Path,
    cell: BackendQ4CellV1,
    transaction_dir: Path,
    q4_binding: dict[str, Any],
    identity_binding: dict[str, Any],
    backend_runtime_grant: dict[str, Any],
    production_context: dict[str, Any],
) -> dict[str, Any]:
    """Build one real production-v3 arm from post-Q4 physical authorities."""

    root = _physical_root(project_root)
    output = _under_root(
        root, transaction_dir, label="Phase-B production transaction", must_exist=False
    )
    context = _production_context_values_v1(production_context)
    prepared = _PRODUCTION_CONTEXT_PREPARED_FIELDS & set(context)
    if prepared and prepared != _PRODUCTION_CONTEXT_PREPARED_FIELDS:
        _fail("production context prepared receipt/runtime binding is partial")
    if prepared:
        receipt_chain = _validated_production_receipt_chain_v1(
            context.pop("production_receipt_chain"),
            root=root,
            revalidate_files=True,
        )
        runtime_binding = copy.deepcopy(
            context.pop("production_runtime_bind_mount")
        )
        context.pop("production_receipt_loader", None)
        context.pop("production_runtime_bind_mount_loader", None)
    else:
        receipt_loader = context.pop(
            "production_receipt_loader",
            load_backend_q4_production_receipt_chain_v1,
        )
        runtime_loader = context.pop(
            "production_runtime_bind_mount_loader",
            _load_production_runtime_bind_mount_v1,
        )
        receipt_chain = _validated_production_receipt_chain_v1(
            receipt_loader(
                project_root=root,
                source_registry_path=source_registry_path,
                source_registry=copy.deepcopy(source_registry),
                **context,
            ),
            root=root,
            revalidate_files=True,
        )
        runtime_binding = runtime_loader(project_root=root)
    if receipt_chain["source_registry_sha256"] != source_registry.get(
        "registry_sha256"
    ):
        _fail("production receipt-chain loader returned another source registry")

    bindings = identity_binding.get("bindings")
    if (
        type(bindings) is not dict
        or bindings.get("backend_runtime_qualification") != q4_binding
    ):
        _fail("production materializer identity/Q4 boundary drifted")
    try:
        resource_grant = validate_pre_run_resource_capability_grant(
            resource_capability_grant_from_identity_artifacts(
                copy.deepcopy(identity_binding)
            )
        )
        model_grant = validate_pre_run_model_parity_grant(
            model_parity_grant_from_identity_artifacts(
                copy.deepcopy(identity_binding)
            )
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"production materializer could not derive identity grants: {error}")
    identity_sha = _required_sha_v1(
        identity_binding.get("binding_sha256"), label="identity artifact binding"
    )
    for grant, label in (
        (resource_grant, "resource capability grant"),
        (model_grant, "model-parity grant"),
        (backend_runtime_grant, "backend runtime grant"),
    ):
        if grant.get("identity_artifact_binding_sha256") != identity_sha:
            _fail(f"production {label} identity cross-binding drifted")
    resource_grant_sha = _required_sha_v1(
        resource_grant.get("grant_sha256"), label="resource capability grant"
    )
    model_grant_sha = _required_sha_v1(
        model_grant.get("grant_sha256"), label="model-parity grant"
    )
    parity_binding_sha = _required_sha_v1(
        model_grant.get("parity_acceptance_binding_sha256"),
        label="model-parity acceptance binding",
    )
    backend_grant_sha = _required_sha_v1(
        backend_runtime_grant.get("grant_sha256"), label="backend runtime grant"
    )

    _registry, runtime_authority, dataset_binding = _runtime_material_for_cell_v4(
        project_root=root, source_registry=source_registry, cell=cell
    )
    try:
        from full_publication_entrypoint import (
            _select_production_v3_authority,
            publication_arm_semantic_evidence_validator_v3,
        )

        selected = _select_production_v3_authority(
            identity_artifacts=identity_binding,
            backend_runtime_grant=backend_runtime_grant,
            coordinate={
                key: cell.coordinate[key]
                for key in ("system", "codec", "topology_kind", "policy", "deadline_ms")
            },
            runtime_authority_snapshot=runtime_authority,
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"production-v3 Q4 authority selection rejected cell {cell.cell_index}: {error}")
    if selected.get("model_parity_acceptance_binding_sha256") != parity_binding_sha:
        _fail("production-v3 runtime authority parity binding drifted")
    if (
        selected.get("runtime_authority_sha256")
        != runtime_authority.get("runtime_authority_sha256")
        or selected.get("qualification_dataset_runtime_input")
        != runtime_authority.get("runtime_input_template")
        or selected.get("qualification_launcher_evidence_files")
        != list(qualification_launcher_evidence_files_v4(cell.policy))
        or _SHA_RE.fullmatch(
            str(selected.get("launcher_input_wrapper_sha256", ""))
        ) is None
        or _SHA_RE.fullmatch(
            str(
                selected.get(
                    "launcher_input_projection_crossbinding_sha256", ""
                )
            )
        ) is None
    ):
        _fail("production-v3 accepted Q4/runtime-candidate authority drifted")

    if type(runtime_binding) is not dict:
        _fail("production runtime bind-mount loader returned no contract")
    runtime_binding_sha = _required_sha_v1(
        runtime_binding.get("binding_sha256"),
        label="production runtime bind-mount",
    )
    python_descriptor = {
        "path": runtime_binding.get("project_python_path"),
        "size_bytes": runtime_binding.get("source_python_size_bytes"),
        "sha256": runtime_binding.get("source_python_sha256"),
    }
    _descriptor(python_descriptor, label="production Python executable")

    invocation = publication_launcher_invocation_v3_contract()
    if selected.get("launcher_invocation") != invocation:
        _fail("production-v3 selected launcher invocation drifted")
    semantic_validator_sha = semantic_evidence_validator_identity_v3(
        publication_arm_semantic_evidence_validator_v3
    )
    run_identity_material = {
        "schema_version": 1,
        "artifact_kind": PRODUCTION_RUN_IDENTITY_KIND,
        "matrix_sha256": _backend_q4_matrix_sha256_v1(),
        "receipt_chain_sha256": receipt_chain["receipt_chain_sha256"],
        "source_registry_sha256": source_registry["registry_sha256"],
        "identity_artifact_binding_sha256": identity_sha,
        "resource_capability_grant_sha256": resource_grant_sha,
        "model_parity_grant_sha256": model_grant_sha,
        "backend_runtime_grant_sha256": backend_grant_sha,
        "runtime_binding_identity_sha256": runtime_binding_sha,
        "semantic_validator_identity_sha256": semantic_validator_sha,
        "run_seed_group": _PRODUCTION_RUN_SEED_GROUP,
        "repeat_index": 0,
    }
    run_identity_sha = _canonical_sha(run_identity_material)
    sequence, pair_id = _backend_q4_pair_execution_v1(cell)
    execution_binding = {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_arm_execution_binding",
        "run_identity_sha256": run_identity_sha,
        "sequence": sequence,
        "pair_id": pair_id,
        "attempt": 1,
        "arm_id": cell.arm_id,
    }
    dataset = copy.deepcopy(dataset_binding["dataset"])
    runtime_key = selected["dataset_runtime_input_key"]
    existing = dataset.get(runtime_key)
    if existing is not None and existing != selected["dataset_runtime_input"]:
        _fail("production-v3 dataset runtime input collision detected")
    dataset[runtime_key] = copy.deepcopy(selected["dataset_runtime_input"])
    scenario = _SCENARIO_BY_TOPOLOGY[cell.topology_kind]
    run_id = f"production-q4-v1-{run_identity_sha[:16]}-{cell.arm_id}"
    runtime_inputs = {
        "system": cell.system,
        "scenario": scenario,
        "topology_kind": cell.topology_kind,
        "codec": cell.codec,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "dataset": dataset,
        "streams": cell.streams,
        "duration_s": cell.measurement_s,
        "repeat_index": 0,
        "base_seed": cell.seed,
        "run_seed": _backend_q4_run_seed_v1(cell),
        "run_id": run_id,
        "project_root": str(root),
        "output_dir": str(output),
        "arm_contract_path": str(output / ARM_CONTRACT_FILENAME),
    }
    coordinate = {
        key: cell.coordinate[key]
        for key in ("system", "codec", "topology_kind", "policy", "deadline_ms")
    }
    resolution = build_backend_publication_dispatch_resolution_v3(
        coordinate=coordinate,
        python_executable=python_descriptor,
        publication_launcher=selected["launcher"],
        launcher_invocation=invocation,
        backend_runtime_grant_sha256=backend_grant_sha,
        identity_artifact_binding_sha256=identity_sha,
        cell_identity_sha256=selected["cell_identity_sha256"],
        validation_record_sha256=selected["validation_record_sha256"],
        runtime_binding_identity_sha256=runtime_binding_sha,
    )
    evidence_names = selected["launcher_evidence_files"]
    arm_contract = build_backend_publication_arm_contract_v3(
        dispatch_resolution=resolution,
        full_publication_execution_binding=execution_binding,
        resource_capability_grant_sha256=resource_grant_sha,
        model_parity_grant_sha256=model_grant_sha,
        model_parity_acceptance_binding_sha256=parity_binding_sha,
        runtime_inputs=runtime_inputs,
        launcher_evidence_files=evidence_names,
    )
    return {
        "arm_contract": arm_contract,
        "run_arguments": {
            "expected_python_executable": python_descriptor,
            "expected_publication_launcher": copy.deepcopy(selected["launcher"]),
            "expected_launcher_invocation_sha256": invocation["invocation_sha256"],
            "expected_cell_identity_sha256": selected["cell_identity_sha256"],
            "expected_validation_record_sha256": selected[
                "validation_record_sha256"
            ],
            "expected_runtime_binding_identity_sha256": runtime_binding_sha,
            "expected_dispatch_resolution_sha256": resolution["resolution_sha256"],
            "expected_full_publication_execution_binding": execution_binding,
            "expected_resource_capability_grant_sha256": resource_grant_sha,
            "expected_model_parity_grant_sha256": model_grant_sha,
            "expected_model_parity_acceptance_binding_sha256": parity_binding_sha,
            "expected_runtime_inputs": runtime_inputs,
            "expected_launcher_evidence_files": list(evidence_names),
            "expected_semantic_validator_identity_sha256": semantic_validator_sha,
            "semantic_evidence_validator": publication_arm_semantic_evidence_validator_v3,
            "expected_production_runtime_bind_mount": runtime_binding,
        },
    }


def run_backend_q4_production_v3_adapter_v1(
    *,
    project_root: Path,
    source_registry: dict[str, Any],
    cell: BackendQ4CellV1,
    transaction_dir: Path,
    q4_binding: dict[str, Any],
    identity_binding: dict[str, Any],
    backend_runtime_grant: dict[str, Any],
    production_context: dict[str, Any],
    source_registry_path: Path | None = None,
    _allow_spawn: bool = True,
    _allow_finalize: bool = True,
    _require_committed_parent_pin: bool = False,
) -> dict[str, Any]:
    """Standard adapter into the production-v3 prepare/run transaction APIs.

    The application factory builds an arm contract and non-authoritative run
    arguments from accepted model/resource inputs.  This adapter overwrites all
    Q4/identity/grant/coordinate pins with the physically loaded authorities.
    """

    if (
        type(_allow_spawn) is not bool
        or type(_allow_finalize) is not bool
        or type(_require_committed_parent_pin) is not bool
    ):
        _fail("production-v3 parent execution controls are invalid")
    factory = production_context.get(
        "production_v3_materializer", materialize_backend_q4_production_v3_arm_v1
    )
    if not callable(factory):
        _fail(
            "production_context production_v3_materializer override is not callable"
        )
    if (
        factory is materialize_backend_q4_production_v3_arm_v1
        and source_registry_path is None
    ):
        _fail("standard production-v3 materializer requires source_registry_path")
    try:
        material = factory(
            project_root=project_root,
            source_registry=copy.deepcopy(source_registry),
            source_registry_path=source_registry_path,
            cell=cell,
            transaction_dir=transaction_dir,
            q4_binding=copy.deepcopy(q4_binding),
            identity_binding=copy.deepcopy(identity_binding),
            backend_runtime_grant=copy.deepcopy(backend_runtime_grant),
            production_context={
                key: copy.deepcopy(item)
                for key, item in production_context.items()
                if key != "production_v3_materializer"
            },
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"production-v3 arm materializer rejected cell {cell.cell_index}: {error}")
    if type(material) is not dict or set(material) != {"arm_contract", "run_arguments"}:
        _fail("production-v3 materializer result fields drifted")
    arm_contract = material["arm_contract"]
    run_arguments = material["run_arguments"]
    if type(arm_contract) is not dict or type(run_arguments) is not dict:
        _fail("production-v3 materializer returned invalid arm/run arguments")
    runtime_inputs = arm_contract.get("runtime_inputs")
    if (
        type(runtime_inputs) is not dict
        or runtime_inputs.get("streams") != cell.streams
        or runtime_inputs.get("duration_s") != cell.measurement_s
        or runtime_inputs.get("base_seed") != cell.seed
        or (
            "warmup_s" in runtime_inputs
            and runtime_inputs.get("warmup_s") != cell.warmup_s
        )
    ):
        _fail("production-v3 arm runtime inputs drifted from frozen Q4 parameters")
    unsafe = {
        "project_root",
        "output_dir",
        "_allow_spawn",
        "_allow_finalize",
        "_fault_hook",
        "_require_committed_parent_pin",
        "expected_durable_parent_artifact_pin",
        "durable_parent_artifact_pin_sink",
    }
    if unsafe & set(run_arguments):
        _fail("production-v3 materializer attempted to control parent-owned execution fields")
    try:
        arm_payload = canonical_backend_publication_arm_contract_bytes_v3(arm_contract)
    except Exception as error:
        _fail(f"production-v3 arm contract is invalid: {error}")
    arm_sha = hashlib.sha256(arm_payload).hexdigest()
    arm_path = transaction_dir / ARM_CONTRACT_FILENAME
    try:
        prepared = prepare_backend_publication_production_transaction_v3(
            output_dir=transaction_dir, arm_contract=arm_contract
        )
    except Exception as error:
        _fail(
            f"production-v3 transaction prepare/recovery rejected the arm: {error}",
            exit_code=EXIT_TRANSIENT,
        )
    if (
        type(prepared) is not dict
        or prepared.get("status") != "prepared_production_arm_not_executed"
    ):
        _fail("production-v3 prepare/recovery did not return non-executed arm authority")
    if _read_physical(arm_path, label="production-v3 arm contract") != arm_payload:
        _fail("prepared production-v3 arm contract collision/tamper detected")
    coordinate = {
        key: cell.coordinate[key]
        for key in ("system", "codec", "topology_kind", "policy", "deadline_ms")
    }
    arguments = copy.deepcopy(run_arguments)
    authoritative = {
        "expected_arm_contract_file_sha256": arm_sha,
        "execution_scope": PRODUCTION_EXECUTION_SCOPE,
        "expected_coordinate": coordinate,
        "expected_backend_runtime_grant_sha256": backend_runtime_grant["grant_sha256"],
        "expected_identity_artifact_binding_sha256": identity_binding["binding_sha256"],
    }
    for key, expected in authoritative.items():
        if key in arguments and arguments[key] != expected:
            _fail(f"production-v3 materializer {key} conflicts with loaded authority")
        arguments[key] = copy.deepcopy(expected)
    pin_execution_binding = {
        "schema_version": 1,
        "artifact_kind": (
            "vast_backend_q4_production_parent_pin_execution_binding_v1"
        ),
        "arm_contract_file_sha256": arm_sha,
        "coordinate": copy.deepcopy(coordinate),
        "backend_runtime_grant_sha256": backend_runtime_grant["grant_sha256"],
        "identity_artifact_binding_sha256": identity_binding["binding_sha256"],
        "dispatch_resolution_sha256": arguments.get(
            "expected_dispatch_resolution_sha256"
        ),
        "cell_identity_sha256": arguments.get("expected_cell_identity_sha256"),
        "validation_record_sha256": arguments.get(
            "expected_validation_record_sha256"
        ),
        "runtime_binding_identity_sha256": arguments.get(
            "expected_runtime_binding_identity_sha256"
        ),
        "semantic_validator_identity_sha256": arguments.get(
            "expected_semantic_validator_identity_sha256"
        ),
        "full_publication_execution_binding_sha256": _canonical_sha(
            arguments.get("expected_full_publication_execution_binding")
        ),
        "runtime_inputs_sha256": _canonical_sha(
            arguments.get("expected_runtime_inputs")
        ),
        "launcher_evidence_files_sha256": _canonical_sha(
            sorted(arguments.get("expected_launcher_evidence_files", []))
        ),
    }
    durable_resume_pin: dict[str, Any] | None = None
    try:
        with ProductionParentArtifactPinStoreV1(
            project_root=project_root,
            output_dir=transaction_dir,
            arm_contract_file_sha256=arm_sha,
            execution_binding=pin_execution_binding,
        ) as parent_pin_store:
            durable_resume_pin = parent_pin_store.load_expected_pin()
            try:
                authority = (
                    run_or_resume_backend_publication_production_transaction_v3(
                        project_root=project_root,
                        output_dir=transaction_dir,
                        expected_durable_parent_artifact_pin=durable_resume_pin,
                        durable_parent_artifact_pin_sink=parent_pin_store,
                        _allow_spawn=_allow_spawn,
                        _allow_finalize=_allow_finalize,
                        **arguments,
                    )
                )
            except BaseException:
                durable_resume_pin = parent_pin_store.load_expected_pin()
                raise
            durable_resume_pin = parent_pin_store.load_expected_pin()
            if (
                _require_committed_parent_pin
                and (
                    type(durable_resume_pin) is not dict
                    or durable_resume_pin.get("state") != "committed"
                )
            ):
                _fail(
                    "production-v3 transaction lacks its committed parent pin"
                )
    except Exception as error:
        fenced = (transaction_dir / LAUNCH_FENCE_FILENAME).exists()
        resumable = (
            type(durable_resume_pin) is dict
            and durable_resume_pin.get("state")
            in {"result", "receipt_intent", "committed"}
        )
        _fail(
            f"production-v3 transaction rejected cell {cell.cell_index}: {error}",
            exit_code=(
                EXIT_TRANSIENT
                if resumable or not fenced
                else EXIT_PERMANENT
            ),
        )
    if type(authority) is not dict:
        _fail("production-v3 transaction did not return output-receipt authority")
    return {"exit_code": EXIT_OK, "authority": authority}


def _load_publication_q4_runtime_candidate_registry_v4(
    *, project_root: Path, source_registry: Mapping[str, Any]
) -> dict[str, Any]:
    descriptor = _revalidate_descriptor(
        project_root,
        source_registry.get("runtime_candidate_registry"),
        label="Q4 runtime candidate registry",
    )
    path = project_root / descriptor["path"]
    value = _load_canonical_json(path, label="Q4 runtime candidate registry")
    try:
        checked = validate_publication_q4_runtime_candidate_registry_v4(value)
    except PublicationQ4RuntimeContractV4Error as error:
        _fail(f"Q4 runtime candidate registry rejected: {error}")
    if checked.get("registry_sha256") != value.get("registry_sha256"):
        _fail("Q4 runtime candidate registry normalized identity drifted")
    return checked


def _runtime_material_for_cell_v4(
    *,
    project_root: Path,
    source_registry: Mapping[str, Any],
    cell: BackendQ4CellV1,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    registry = _load_publication_q4_runtime_candidate_registry_v4(
        project_root=project_root,
        source_registry=source_registry,
    )
    try:
        authority, dataset = select_publication_q4_runtime_material_v4(
            registry,
            coordinate=cell.coordinate,
        )
    except PublicationQ4RuntimeContractV4Error as error:
        _fail(f"Q4 runtime material selection rejected cell {cell.cell_index}: {error}")
    return registry, authority, dataset


def materialize_backend_q4_runtime_input_v4_adapter(
    *,
    project_root: Path,
    source_registry: dict[str, Any],
    source_registry_path: Path,
    cell: BackendQ4CellV1,
    output_dir: Path,
) -> dict[str, Any]:
    """Build the public non-authorizing runtime contract for any Q4 cell."""

    del source_registry_path, output_dir
    registry, authority, dataset = _runtime_material_for_cell_v4(
        project_root=project_root,
        source_registry=source_registry,
        cell=cell,
    )
    run_id = f"qualification-q4-v4-{cell.arm_id}"
    try:
        contract = build_publication_runtime_contract_v4(
            coordinate=cell.coordinate,
            authority_snapshot=authority,
            dataset_binding=dataset,
            run_id=run_id,
            duration_s=cell.measurement_s,
        )
    except PublicationQ4RuntimeContractV4Error as error:
        _fail(f"public Q4 runtime contract rejected cell {cell.cell_index}: {error}")
    return {
        "schema_version": 4,
        "artifact_kind": MATERIALIZED_RUNTIME_INPUT_KIND,
        "status": "materialized_non_authorizing_arbitrary_q4_runtime",
        "authorization_eligible": False,
        "execution_authorized": False,
        "runtime_candidate_registry_sha256": registry["registry_sha256"],
        "publication_runtime_contract_v4": contract,
    }


def _validated_materialized_runtime_contract_v4(
    *,
    qualification_input: Mapping[str, Any],
    project_root: Path,
    source_registry: Mapping[str, Any],
    cell: BackendQ4CellV1,
) -> dict[str, Any]:
    material = qualification_input.get("materialized_runtime_input")
    expected_fields = {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "runtime_candidate_registry_sha256",
        "publication_runtime_contract_v4",
    }
    registry, authority, dataset = _runtime_material_for_cell_v4(
        project_root=project_root,
        source_registry=source_registry,
        cell=cell,
    )
    if (
        type(material) is not dict
        or set(material) != expected_fields
        or material.get("schema_version") != 4
        or material.get("artifact_kind") != MATERIALIZED_RUNTIME_INPUT_KIND
        or material.get("status")
        != "materialized_non_authorizing_arbitrary_q4_runtime"
        or material.get("authorization_eligible") is not False
        or material.get("execution_authorized") is not False
        or material.get("runtime_candidate_registry_sha256")
        != registry["registry_sha256"]
    ):
        _fail("materialized public Q4 runtime input fields/trust pins drifted")
    run_id = f"qualification-q4-v4-{cell.arm_id}"
    try:
        return validate_publication_runtime_contract_v4(
            material.get("publication_runtime_contract_v4"),
            coordinate=cell.coordinate,
            authority_snapshot=authority,
            dataset_binding=dataset,
            run_id=run_id,
            duration_s=cell.measurement_s,
        )
    except PublicationQ4RuntimeContractV4Error as error:
        _fail(f"materialized public Q4 runtime contract drifted: {error}")


def _plain_single_link_file(path: Path, *, label: str) -> os.stat_result:
    try:
        info = path.lstat()
    except OSError as error:
        _fail(f"{label} is unavailable: {error}")
    if (
        not stat.S_ISREG(info.st_mode)
        or _is_link_or_reparse(info)
        or int(info.st_nlink) != 1
        or int(info.st_size) <= 0
    ):
        _fail(f"{label} is not a non-empty ordinary single-link file")
    return info


def _copy_host_evidence_noreplace(
    *, root: Path, source: Path, destination: Path, label: str,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    source_info = _plain_single_link_file(source, label=label)
    payload = _read_physical(source, label=label)
    destination = _under_root(root, destination, label=label)
    with _held_physical_root_v1(root) as custody:
        try:
            committed, _identity, _disposition = (
                custody.commit_or_adopt_exact_identity(
                    destination,
                    payload,
                    label=label,
                    mode=0o444,
                    create_parents=True,
                    after_publish_step=after_publish_step,
                )
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"{label} held atomic immutable copy failed: {error}")
        current = source.lstat()
        if _snapshot(current) != _snapshot(source_info):
            _fail(f"{label} source changed across held evidence copy")
        return committed


def _default_q4_hardware_collector(path: Path, *, run_id: str) -> Any:
    return HardwareResourceCollector(path, run_id=run_id, interval_s=1.0)


def run_backend_q4_native_runtime_v4_adapter(
    *,
    project_root: Path,
    source_registry: dict[str, Any],
    cell: BackendQ4CellV1,
    qualification_input: dict[str, Any],
    qualification_input_path: Path,
    output_dir: Path,
) -> dict[str, Any]:
    """Run one real v3 native hook and seal its physical, pending evidence."""

    contract = _validated_materialized_runtime_contract_v4(
        qualification_input=qualification_input,
        project_root=project_root,
        source_registry=source_registry,
        cell=cell,
    )
    input_descriptor = _descriptor_for(
        project_root,
        qualification_input_path,
        label=f"Q4 qualification input {cell.cell_index}",
    )
    native_dir = _under_root(
        project_root,
        output_dir / NATIVE_RUNTIME_DIRECTORY,
        label=f"Q4 native runtime output {cell.cell_index}",
    )
    if native_dir.exists() or os.path.lexists(native_dir):
        _fail(f"Q4 native runtime output collision for cell {cell.cell_index}")
    native_dir.mkdir(mode=0o700)
    if any(native_dir.iterdir()):
        _fail("Q4 native runtime output was not created empty")
    graph = contract["native_graph_contract"]
    evidence_names = tuple(graph["launcher_evidence_files"])
    if evidence_names != qualification_launcher_evidence_files_v4(cell.policy):
        _fail("public Q4 runtime launcher evidence namespace drifted")
    request = NativePublicationRequestV3(
        system=cell.system,
        topology_kind=cell.topology_kind,
        scenario=contract["runtime_inputs"]["scenario"],
        project_root=project_root,
        output_dir=native_dir,
        arm_contract_path=qualification_input_path,
        arm_contract_file_sha256=input_descriptor["sha256"],
        run_id=contract["run_id"],
        arm_id=cell.arm_id,
        runtime_inputs=copy.deepcopy(contract["runtime_inputs"]),
        launcher_evidence_files=evidence_names,
    )
    hardware_staging = output_dir / f".{HARDWARE_EVIDENCE_FILENAME}.host"
    if hardware_staging.exists() or os.path.lexists(hardware_staging):
        _fail("Q4 host hardware evidence staging collision")
    collector = _default_q4_hardware_collector(
        hardware_staging,
        run_id=contract["run_id"],
    )
    runtime_error: BaseException | None = None
    collector_started = False
    collector_stopped = False
    collector_joined = False
    try:
        collector.start()
        collector_started = True
        collector.wait_until_ready(timeout_s=60.0)
        try:
            outcome = _NATIVE_RUNTIME_REGISTRY[cell.system](request)
            if (
                type(outcome) is not NativePublicationOutcomeV3
                or outcome.exit_code != EXIT_OK
                or outcome.blockers != ()
            ):
                _fail(f"Q4 v3 native runtime did not succeed for {cell.arm_id}")
        except BaseException as error:
            runtime_error = error
        finally:
            collector.stop()
            collector_stopped = True
            collector.join(timeout=30.0)
            collector_joined = True
        if collector.is_alive():
            _fail(f"Q4 hardware collector survived bounded stop for {cell.arm_id}")
        collector.raise_if_failed()
        if runtime_error is not None:
            raise runtime_error
    finally:
        if collector_started and not collector_stopped:
            try:
                collector.stop()
            except BaseException:
                pass
        if collector_started and not collector_joined:
            try:
                collector.join(timeout=30.0)
            except BaseException:
                pass
    observed_names = {entry.name for entry in native_dir.iterdir()}
    if observed_names != set(evidence_names):
        _fail(f"Q4 v3 native evidence namespace drifted for {cell.arm_id}")
    evidence_descriptors = [
        _descriptor_for(
            project_root,
            native_dir / name,
            label=f"Q4 native evidence {cell.cell_index}:{name}",
        )
        for name in evidence_names
    ]
    hardware_descriptor = _copy_host_evidence_noreplace(
        root=project_root,
        source=hardware_staging,
        destination=native_dir / HARDWARE_EVIDENCE_FILENAME,
        label=f"Q4 hardware evidence {cell.cell_index}",
    )
    all_evidence = [*evidence_descriptors, hardware_descriptor]
    runtime_contract_descriptor = _write_immutable_json(
        project_root,
        native_dir / PUBLICATION_RUNTIME_CONTRACT_FILENAME,
        contract,
        label=f"Q4 public runtime contract {cell.cell_index}",
        allow_identical=False,
    )
    if runtime_contract_descriptor["path"] != (
        native_dir / PUBLICATION_RUNTIME_CONTRACT_FILENAME
    ).relative_to(project_root).as_posix():
        _fail("Q4 public runtime contract descriptor path drifted")
    try:
        manifest = build_publication_q4_raw_evidence_manifest_v4(
            project_root=project_root,
            evidence_dir=native_dir,
            runtime_contract_path=(
                native_dir / PUBLICATION_RUNTIME_CONTRACT_FILENAME
            ),
            coordinate=cell.coordinate,
            run_id=contract["run_id"],
            duration_s=cell.measurement_s,
        )
    except Exception as error:
        _fail(f"Q4 raw evidence manifest construction rejected: {error}")
    if manifest.get("evidence_files") != all_evidence:
        _fail("Q4 raw evidence manifest physical descriptor order drifted")
    manifest_descriptor = _write_immutable_json(
        project_root,
        output_dir / RAW_EVIDENCE_MANIFEST_FILENAME,
        manifest,
        label=f"Q4 raw evidence manifest {cell.cell_index}",
        allow_identical=False,
    )
    manifest_ref = {
        "descriptor": manifest_descriptor,
        "content_identity_sha256": manifest["raw_evidence_manifest_sha256"],
    }
    request_candidate = {
        "schema_version": 4,
        "artifact_kind": NATIVE_VALIDATION_REQUEST_CANDIDATE_KIND,
        "status": "pending_hermetic_evidence_replay",
        "authorization_eligible": False,
        "execution_authorized": False,
        "coordinate": cell.coordinate,
        "run_id": contract["run_id"],
        "runtime_contract_sha256": contract["contract_sha256"],
        "raw_evidence_ref": manifest_ref,
    }
    record_candidate = {
        "schema_version": 4,
        "artifact_kind": NATIVE_VALIDATION_RECORD_CANDIDATE_KIND,
        "status": "pending_hermetic_evidence_replay",
        "authorization_eligible": False,
        "execution_authorized": False,
        "validation_records_authenticated": False,
        "coordinate": cell.coordinate,
        "run_id": contract["run_id"],
        "runtime_contract_sha256": contract["contract_sha256"],
        "raw_evidence_ref": manifest_ref,
        "replay_result": None,
    }
    return {
        "exit_code": EXIT_OK,
        "raw_evidence_path": project_root / manifest_descriptor["path"],
        "qualification_request": request_candidate,
        "validation_record_candidate": record_candidate,
    }


def _typed_artifact_ref_v4(
    descriptor: Mapping[str, Any],
    *,
    schema_version: int,
    artifact_kind: str,
    semantic_sha256: str,
) -> dict[str, Any]:
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": copy.deepcopy(dict(descriptor)),
        "content_identity_sha256": semantic_sha256,
    }


def _write_typed_graph_node_v4(
    *,
    root: Path,
    path: Path,
    value: Mapping[str, Any],
    schema_version: int,
    artifact_kind: str,
    identity_field: str,
    label: str,
) -> dict[str, Any]:
    if (
        value.get("schema_version") != schema_version
        or value.get("artifact_kind") != artifact_kind
        or not _SHA_RE.fullmatch(str(value.get(identity_field, "")))
    ):
        _fail(f"{label} typed graph node identity drifted")
    descriptor = _write_immutable_json(root, path, value, label=label)
    return _typed_artifact_ref_v4(
        descriptor,
        schema_version=schema_version,
        artifact_kind=artifact_kind,
        semantic_sha256=str(value[identity_field]),
    )


def _load_registered_typed_json_v4(
    *,
    root: Path,
    source_registry: Mapping[str, Any],
    reference: Mapping[str, Any],
    label: str,
    identity_field: str,
) -> dict[str, Any]:
    if (
        type(reference) is not dict
        or set(reference)
        != {
            "artifact_schema_version",
            "artifact_kind",
            "descriptor",
            "content_identity_sha256",
        }
        or reference.get("descriptor") not in source_registry.get("files", [])
    ):
        _fail(f"{label} is outside the accepted source-file closure")
    descriptor = _revalidate_descriptor(
        root,
        reference["descriptor"],
        label=label,
    )
    value = _load_canonical_json(root / descriptor["path"], label=label)
    if (
        value.get("schema_version") != reference["artifact_schema_version"]
        or value.get("artifact_kind") != reference["artifact_kind"]
        or value.get(identity_field) != reference["content_identity_sha256"]
    ):
        _fail(f"{label} physical semantic identity drifted")
    return value


def _require_registered_descriptor_v4(
    *,
    root: Path,
    source_registry: Mapping[str, Any],
    descriptor: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if descriptor not in source_registry.get("files", []):
        _fail(f"{label} is outside the accepted source-file closure")
    return _revalidate_descriptor(root, descriptor, label=label)


def _load_phase_a_runtime_material_v4(
    *,
    root: Path,
    source_registry: Mapping[str, Any],
    phase_a_records: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from publication_q4_evidence_validator_v4 import (
        validate_publication_q4_raw_evidence_manifest_v4,
    )

    if (
        type(phase_a_records) is not list
        or len(phase_a_records) != CELL_COUNT
    ):
        _fail("standard Q4 graph requires exactly 560 Phase A records")
    registry = _load_publication_q4_runtime_candidate_registry_v4(
        project_root=root,
        source_registry=source_registry,
    )
    materials: list[dict[str, Any]] = []
    for position, phase_record in enumerate(phase_a_records):
        cell = backend_q4_cells_v1()[position]
        if (
            type(phase_record) is not dict
            or phase_record.get("coordinate") != cell.coordinate
        ):
            _fail(f"Phase A runtime record[{position}] coordinate drifted")
        request_descriptor = _revalidate_descriptor(
            root,
            phase_record.get("qualification_request"),
            label=f"Q4 native validation request candidate[{position}]",
        )
        request_candidate = _load_canonical_json(
            root / request_descriptor["path"],
            label=f"Q4 native validation request candidate[{position}]",
        )
        record_descriptor = _revalidate_descriptor(
            root,
            phase_record.get("validation_record_candidate"),
            label=f"Q4 native validation record candidate[{position}]",
        )
        record_candidate = _load_canonical_json(
            root / record_descriptor["path"],
            label=f"Q4 native validation record candidate[{position}]",
        )
        expected_request_fields = {
            "schema_version",
            "artifact_kind",
            "status",
            "authorization_eligible",
            "execution_authorized",
            "coordinate",
            "run_id",
            "runtime_contract_sha256",
            "raw_evidence_ref",
        }
        expected_record_fields = {
            *expected_request_fields,
            "validation_records_authenticated",
            "replay_result",
        }
        expected_run_id = f"qualification-q4-v4-{cell.arm_id}"
        if (
            set(request_candidate) != expected_request_fields
            or request_candidate.get("schema_version") != 4
            or request_candidate.get("artifact_kind")
            != NATIVE_VALIDATION_REQUEST_CANDIDATE_KIND
            or request_candidate.get("status") != "pending_hermetic_evidence_replay"
            or request_candidate.get("authorization_eligible") is not False
            or request_candidate.get("execution_authorized") is not False
            or request_candidate.get("coordinate") != cell.coordinate
            or request_candidate.get("run_id") != expected_run_id
            or set(record_candidate) != expected_record_fields
            or record_candidate.get("artifact_kind")
            != NATIVE_VALIDATION_RECORD_CANDIDATE_KIND
            or record_candidate.get("schema_version") != 4
            or record_candidate.get("status") != "pending_hermetic_evidence_replay"
            or record_candidate.get("authorization_eligible") is not False
            or record_candidate.get("execution_authorized") is not False
            or record_candidate.get("validation_records_authenticated") is not False
            or record_candidate.get("replay_result") is not None
            or record_candidate.get("coordinate") != cell.coordinate
            or record_candidate.get("run_id") != expected_run_id
            or record_candidate.get("runtime_contract_sha256")
            != request_candidate.get("runtime_contract_sha256")
            or record_candidate.get("raw_evidence_ref")
            != request_candidate.get("raw_evidence_ref")
        ):
            _fail(f"Q4 native validation candidate[{position}] drifted")
        raw_ref = request_candidate["raw_evidence_ref"]
        if (
            type(raw_ref) is not dict
            or set(raw_ref) != {"descriptor", "content_identity_sha256"}
            or raw_ref.get("descriptor") != phase_record.get("raw_evidence")
        ):
            _fail(f"Q4 raw evidence reference[{position}] drifted")
        raw_descriptor = _revalidate_descriptor(
            root,
            raw_ref["descriptor"],
            label=f"Q4 raw evidence manifest[{position}]",
        )
        raw_manifest = _load_canonical_json(
            root / raw_descriptor["path"],
            label=f"Q4 raw evidence manifest[{position}]",
        )
        try:
            authority, dataset = select_publication_q4_runtime_material_v4(
                registry,
                coordinate=cell.coordinate,
            )
            checked_manifest = validate_publication_q4_raw_evidence_manifest_v4(
                raw_manifest,
                expected_coordinate=cell.coordinate,
                expected_run_id=expected_run_id,
                expected_runtime_authority_sha256=authority[
                    "runtime_authority_sha256"
                ],
                expected_runtime_contract_sha256=request_candidate[
                    "runtime_contract_sha256"
                ],
            )
        except Exception as error:
            _fail(f"Q4 raw evidence manifest[{position}] rejected: {error}")
        if (
            checked_manifest.get("raw_evidence_manifest_sha256")
            != raw_ref["content_identity_sha256"]
        ):
            _fail(f"Q4 raw evidence manifest[{position}] semantic ref drifted")
        runtime_descriptor = _revalidate_descriptor(
            root,
            checked_manifest["runtime_contract"],
            label=f"Q4 public runtime contract[{position}]",
        )
        runtime_contract = _load_canonical_json(
            root / runtime_descriptor["path"],
            label=f"Q4 public runtime contract[{position}]",
        )
        try:
            checked_contract = validate_publication_runtime_contract_v4(
                runtime_contract,
                coordinate=cell.coordinate,
                authority_snapshot=authority,
                dataset_binding=dataset,
                run_id=expected_run_id,
                duration_s=cell.measurement_s,
            )
        except PublicationQ4RuntimeContractV4Error as error:
            _fail(f"Q4 public runtime contract[{position}] rejected: {error}")
        if (
            checked_contract["contract_sha256"]
            != request_candidate["runtime_contract_sha256"]
        ):
            _fail(f"Q4 public runtime contract[{position}] candidate pin drifted")
        materials.append(
            {
                "cell": cell,
                "authority_snapshot": authority,
                "dataset_binding": dataset,
                "runtime_contract": checked_contract,
                "raw_evidence_manifest": checked_manifest,
                "raw_evidence_ref": copy.deepcopy(raw_ref),
            }
        )
    return registry, materials


def _build_q4_input_index_from_runtime_material_v4(
    *,
    root: Path,
    source_registry: Mapping[str, Any],
    registry: Mapping[str, Any],
    materials: Sequence[Mapping[str, Any]],
    graph_dir: Path,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, str],
    dict[str, str],
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    snapshots = registry["authority_snapshots"]
    first = snapshots[0]
    for position, snapshot in enumerate(snapshots):
        _load_registered_typed_json_v4(
            root=root,
            source_registry=source_registry,
            reference=snapshot["runtime_authority_ref"],
            label=f"Q4 runtime authority[{position}]",
            identity_field="authority_sha256",
        )
    systems: list[dict[str, Any]] = []
    binding_pins: dict[str, str] = {}
    set_pins: dict[str, str] = {}
    launcher_refs: dict[str, dict[str, Any]] = {}
    launcher_pins: dict[str, str] = {}
    for system in SYSTEMS:
        system_snapshots = sorted(
            (
                item
                for item in snapshots
                if item["coordinate"]["system"] == system
            ),
            key=lambda item: tuple(
                item["coordinate"][field]
                for field in ("system", "codec", "topology_kind", "policy")
            ),
        )
        authorities = [
            {
                "coordinate": copy.deepcopy(item["coordinate"]),
                "authority_ref": copy.deepcopy(item["runtime_authority_ref"]),
                "authority_sha256": item["runtime_authority_sha256"],
            }
            for item in system_snapshots
        ]
        source = system_snapshots[0]
        _load_registered_typed_json_v4(
            root=root,
            source_registry=source_registry,
            reference=source["launcher_runtime_authority_ref"],
            label=f"Q4 {system} launcher runtime authority",
            identity_field="launcher_runtime_authority_sha256",
        )
        system_materials = [
            item for item in materials if item["cell"].system == system
        ]
        if len(system_materials) != 140:
            _fail(f"Q4 {system} material coverage is not 140 cells")
        cells = [
            {
                **item["cell"].coordinate,
                "runtime_authority_sha256": item["authority_snapshot"][
                    "runtime_authority_sha256"
                ],
                "raw_evidence_ref": copy.deepcopy(item["raw_evidence_ref"]),
            }
            for item in system_materials
        ]
        binding_pins[system] = source["runtime_binding_identity_v4_sha256"]
        set_pins[system] = source["runtime_authority_set_sha256"]
        launcher_refs[system] = copy.deepcopy(
            source["launcher_runtime_authority_ref"]
        )
        launcher_pins[system] = source["launcher_runtime_authority_sha256"]
        systems.append(
            {
                "system": system,
                "runtime_binding_identity_v4_sha256": binding_pins[system],
                "runtime_authority_set_sha256": set_pins[system],
                "runtime_authorities": authorities,
                "launcher_runtime_authority_ref": launcher_refs[system],
                "launcher_runtime_authority_sha256": launcher_pins[system],
                "cells": cells,
            }
        )
    unsigned = {
        "schema_version": Q4_INPUT_INDEX_SCHEMA_VERSION,
        "artifact_kind": Q4_INPUT_INDEX_KIND,
        "upstream_identities": copy.deepcopy(first["upstream_identities"]),
        "publication_launcher_invocation_v3_ref": copy.deepcopy(
            first["publication_launcher_invocation_v3_ref"]
        ),
        "publication_launcher_invocation_v3_sha256": first[
            "publication_launcher_invocation_v3"
        ]["invocation_sha256"],
        "systems": systems,
    }
    expected_sha = _canonical_sha(unsigned)
    try:
        q4_input = build_backend_runtime_qualification_v4_input_index(
            upstream_identities=first["upstream_identities"],
            publication_launcher_invocation_v3_ref=first[
                "publication_launcher_invocation_v3_ref"
            ],
            systems=systems,
            expected_semantic_sha256=expected_sha,
            expected_upstream_identities=first["upstream_identities"],
            expected_publication_launcher_invocation_v3_sha256=first[
                "publication_launcher_invocation_v3"
            ]["invocation_sha256"],
            expected_runtime_binding_identity_v4_sha256_by_system=binding_pins,
            expected_runtime_authority_set_sha256_by_system=set_pins,
            expected_launcher_runtime_authority_sha256_by_system=launcher_pins,
        )
    except Exception as error:
        _fail(f"standard Q4 input-index construction rejected physical material: {error}")
    q4_ref = _write_typed_graph_node_v4(
        root=root,
        path=graph_dir / "backend-runtime-qualification-v4-input-index.json",
        value=q4_input,
        schema_version=Q4_INPUT_INDEX_SCHEMA_VERSION,
        artifact_kind=Q4_INPUT_INDEX_KIND,
        identity_field="input_index_sha256",
        label="Q4 runtime qualification input index",
    )
    return (
        q4_input,
        q4_ref,
        binding_pins,
        set_pins,
        launcher_refs,
        launcher_pins,
    )


def _load_q4_validation_trust_roots_v4(
    *,
    root: Path,
    source_registry: Mapping[str, Any],
    registry: Mapping[str, Any],
) -> dict[str, Any]:
    first = registry["authority_snapshots"][0]
    validator = _load_registered_typed_json_v4(
        root=root,
        source_registry=source_registry,
        reference=first["q4_validator_authority_ref"],
        label="Q4 evidence validator authority",
        identity_field="authority_sha256",
    )
    runner = _load_registered_typed_json_v4(
        root=root,
        source_registry=source_registry,
        reference=first["runner_authority_ref"],
        label="Q4 evidence validation runner authority",
        identity_field="runner_authority_sha256",
    )
    invocation = _load_registered_typed_json_v4(
        root=root,
        source_registry=source_registry,
        reference=first["publication_launcher_invocation_v3_ref"],
        label="publication launcher invocation v3",
        identity_field="invocation_sha256",
    )
    try:
        checked_validator = validate_backend_runtime_validator_authority_v4(
            validator,
            expected_authority_sha256=first["q4_validator_authority_sha256"],
        )
        validator_assessment = assess_backend_runtime_validator_authority_v4(
            checked_validator,
            project_root=root,
            expected_authority_sha256=first["q4_validator_authority_sha256"],
        )
        checked_runner = validate_backend_runtime_validation_runner_authority(
            runner,
            expected_runner_authority_sha256=first["runner_authority_sha256"],
        )
        runner_assessment = assess_backend_runtime_validation_runner_authority(
            checked_runner,
            project_root=root,
            expected_runner_authority_sha256=first["runner_authority_sha256"],
        )
        checked_invocation = validate_publication_launcher_invocation_v3(invocation)
    except Exception as error:
        _fail(f"Q4 physical evidence-validation trust root rejected: {error}")
    if (
        validator_assessment.get("status") != "physically_valid"
        or runner_assessment.get("status") != "physically_valid"
        or checked_invocation != first["publication_launcher_invocation_v3"]
        or checked_runner["invocation_contract"]["invocation_sha256"]
        != first["runner_invocation_identity_sha256"]
        or checked_runner["validation_protocol_identity_sha256"]
        != checked_validator["validation_protocol_identity_sha256"]
        or checked_runner["input_schema_identity_sha256"]
        != checked_validator["validation_input_schema_identity_sha256"]
        or checked_runner["output_schema_identity_sha256"]
        != checked_validator["validation_output_schema_identity_sha256"]
    ):
        _fail("Q4 evidence validator/runner physical trust cross-binding drifted")
    _require_registered_descriptor_v4(
        root=root,
        source_registry=source_registry,
        descriptor=checked_validator["implementation"]["descriptor"],
        label="Q4 evidence validator implementation",
    )
    runner_closure = [
        checked_runner["runtime_bundle_manifest"]["descriptor"],
        checked_runner["python_executable"]["descriptor"],
        checked_runner["runner"]["descriptor"],
        *(
            item["descriptor"]
            for item in checked_runner["runtime_leaves"]
        ),
    ]
    for position, descriptor in enumerate(runner_closure):
        _require_registered_descriptor_v4(
            root=root,
            source_registry=source_registry,
            descriptor=descriptor,
            label=f"Q4 evidence runner closure[{position}]",
        )
    return {
        "snapshot": first,
        "validator": checked_validator,
        "runner": checked_runner,
        "invocation": checked_invocation,
        "validator_ref": copy.deepcopy(first["q4_validator_authority_ref"]),
        "runner_ref": copy.deepcopy(first["runner_authority_ref"]),
        "invocation_ref": copy.deepcopy(
            first["publication_launcher_invocation_v3_ref"]
        ),
    }


def _build_q4_validation_contexts_v4(
    *,
    root: Path,
    graph_dir: Path,
    q4_input: Mapping[str, Any],
    q4_input_ref: Mapping[str, Any],
    trust: Mapping[str, Any],
    binding_pins: Mapping[str, str],
    set_pins: Mapping[str, str],
    launcher_refs: Mapping[str, Mapping[str, Any]],
    launcher_pins: Mapping[str, str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    contexts: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    for system in SYSTEMS:
        try:
            context = build_backend_runtime_validation_system_context_v2(
                system=system,
                q4_input_ref=q4_input_ref,
                q4_input_sha256=q4_input["input_index_sha256"],
                q4_validator_authority_ref=trust["validator_ref"],
                q4_validator_authority_sha256=trust["validator"]["authority_sha256"],
                runner_authority_ref=trust["runner_ref"],
                runner_authority_sha256=trust["runner"]["runner_authority_sha256"],
                publication_launcher_invocation_v3_ref=trust["invocation_ref"],
                publication_launcher_invocation_v3_sha256=trust["invocation"][
                    "invocation_sha256"
                ],
                runner_invocation_identity_sha256=trust["snapshot"][
                    "runner_invocation_identity_sha256"
                ],
                runtime_binding_identity_v4_sha256=binding_pins[system],
                runtime_authority_set_sha256=set_pins[system],
                launcher_runtime_authority_ref=launcher_refs[system],
                launcher_runtime_authority_sha256=launcher_pins[system],
            )
        except Exception as error:
            _fail(f"Q4 {system} validation context construction rejected: {error}")
        reference = _write_typed_graph_node_v4(
            root=root,
            path=graph_dir / "system-contexts" / f"{system}.json",
            value=context,
            schema_version=VALIDATION_RECORD_SCHEMA_VERSION,
            artifact_kind=VALIDATION_CONTEXT_KIND,
            identity_field="context_sha256",
            label=f"Q4 {system} validation context",
        )
        contexts.append(context)
        refs.append(reference)
    return contexts, refs


def _common_validation_bindings_v4(
    *,
    q4_input: Mapping[str, Any],
    q4_input_ref: Mapping[str, Any],
    trust: Mapping[str, Any],
    system: str,
    binding_pins: Mapping[str, str],
    set_pins: Mapping[str, str],
    launcher_refs: Mapping[str, Mapping[str, Any]],
    launcher_pins: Mapping[str, str],
) -> dict[str, Any]:
    return {
        "q4_input_ref": q4_input_ref,
        "q4_input_sha256": q4_input["input_index_sha256"],
        "q4_validator_authority_ref": trust["validator_ref"],
        "q4_validator_authority_sha256": trust["validator"]["authority_sha256"],
        "runner_authority_ref": trust["runner_ref"],
        "runner_authority_sha256": trust["runner"]["runner_authority_sha256"],
        "publication_launcher_invocation_v3_ref": trust["invocation_ref"],
        "publication_launcher_invocation_v3_sha256": trust["invocation"][
            "invocation_sha256"
        ],
        "runner_invocation_identity_sha256": trust["snapshot"][
            "runner_invocation_identity_sha256"
        ],
        "runtime_binding_identity_v4_sha256": binding_pins[system],
        "runtime_authority_set_sha256": set_pins[system],
        "launcher_runtime_authority_ref": launcher_refs[system],
        "launcher_runtime_authority_sha256": launcher_pins[system],
    }


def _runner_argv_v4(
    *,
    root: Path,
    trust: Mapping[str, Any],
    request_ref: Mapping[str, Any],
    request_sha256: str,
) -> list[str]:
    runner = trust["runner"]
    mapping = {
        "python_executable": str(
            root / runner["python_executable"]["descriptor"]["path"]
        ),
        "runner_path": str(root / runner["runner"]["descriptor"]["path"]),
        "project_root": str(root),
        "runner_authority_path": str(
            root / trust["runner_ref"]["descriptor"]["path"]
        ),
        "runner_authority_file_sha256": trust["runner_ref"]["descriptor"][
            "sha256"
        ],
        "runner_authority_sha256": runner["runner_authority_sha256"],
        "validator_authority_path": str(
            root / trust["validator_ref"]["descriptor"]["path"]
        ),
        "validator_authority_file_sha256": trust["validator_ref"]["descriptor"][
            "sha256"
        ],
        "validator_authority_sha256": trust["validator"]["authority_sha256"],
        "request_path": str(root / request_ref["descriptor"]["path"]),
        "request_file_sha256": request_ref["descriptor"]["sha256"],
        "request_sha256": request_sha256,
    }
    try:
        argv = [
            item.format_map(mapping)
            for item in runner["invocation_contract"]["argv_template"]
        ]
    except (KeyError, ValueError) as error:
        _fail(f"Q4 evidence runner argv template rejected: {error}")
    expected_keys = set(mapping)
    template = runner["invocation_contract"]["argv_template"]
    used = {
        key
        for key in expected_keys
        if any("{" + key + "}" in item for item in template)
    }
    if used != expected_keys or any("{" in item or "}" in item for item in argv):
        _fail("Q4 evidence runner argv template placeholder coverage drifted")
    return argv


def _invoke_q4_evidence_runner_v4(
    *,
    root: Path,
    graph_dir: Path,
    cell: BackendQ4CellV1,
    trust: Mapping[str, Any],
    request_ref: Mapping[str, Any],
    request_sha256: str,
    raw_evidence_ref: Mapping[str, Any],
) -> dict[str, Any]:
    from publication_q4_evidence_validator_v4 import (
        validate_publication_q4_evidence_validation_result_v4,
    )

    result_path = graph_dir / "runner-results" / f"{cell.arm_id}.json"
    fence_path = graph_dir / "runner-fences" / f"{cell.arm_id}.json"
    expected_fence = _seal(
        {
            "schema_version": 4,
            "artifact_kind": "vast_publication_q4_evidence_runner_launch_fence_v4",
            "status": "hermetic_evidence_runner_launch_fenced",
            "authorization_eligible": False,
            "execution_authorized": False,
            "coordinate": cell.coordinate,
            "validation_request_ref": copy.deepcopy(dict(request_ref)),
            "raw_evidence_ref": copy.deepcopy(dict(raw_evidence_ref)),
            "validator_authority_ref": copy.deepcopy(trust["validator_ref"]),
            "runner_authority_ref": copy.deepcopy(trust["runner_ref"]),
            "runner_invocation_identity_sha256": trust["snapshot"][
                "runner_invocation_identity_sha256"
            ],
        },
        "fence_sha256",
    )
    fence_exists = fence_path.exists() or os.path.lexists(fence_path)
    result_exists = result_path.exists() or os.path.lexists(result_path)
    if result_exists and not fence_exists:
        _fail(f"Q4 evidence runner result[{cell.cell_index}] exists without fence")
    if fence_exists:
        observed_fence = _validate_sealed(
            _load_canonical_json(
                fence_path,
                label=f"Q4 evidence runner fence {cell.cell_index}",
            ),
            field="fence_sha256",
            label=f"Q4 evidence runner fence {cell.cell_index}",
        )
        if observed_fence != expected_fence:
            _fail(f"Q4 evidence runner fence[{cell.cell_index}] drifted")
        if not result_exists:
            _fail(
                f"Q4 evidence runner[{cell.cell_index}] has a durable fence without "
                "a committed result; retry is forbidden"
            )
        result = _load_canonical_json(
            result_path,
            label=f"Q4 evidence runner result {cell.cell_index}",
        )
    else:
        _write_immutable_json(
            root,
            fence_path,
            expected_fence,
            label=f"Q4 evidence runner fence {cell.cell_index}",
            allow_identical=False,
        )
        argv = _runner_argv_v4(
            root=root,
            trust=trust,
            request_ref=request_ref,
            request_sha256=request_sha256,
        )
        try:
            completed = subprocess.run(
                argv,
                cwd=root,
                env={},
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                close_fds=True,
                timeout=30.0,
            )
        except (OSError, subprocess.SubprocessError) as error:
            _fail(f"Q4 evidence runner[{cell.cell_index}] execution failed: {error}")
        if (
            completed.returncode != 0
            or completed.stderr
            or len(completed.stdout) > 1024 * 1024
            or len(completed.stderr) > 1024 * 1024
        ):
            diagnostic = completed.stderr[:4096].decode("utf-8", errors="replace")
            _fail(
                f"Q4 evidence runner[{cell.cell_index}] rejected physical evidence "
                f"(exit={completed.returncode}, diagnostic={diagnostic!r})"
            )
        try:
            result = json.loads(completed.stdout.decode("ascii"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            _fail(f"Q4 evidence runner[{cell.cell_index}] stdout is invalid: {error}")
        if type(result) is not dict or completed.stdout != _canonical_bytes(result):
            _fail(f"Q4 evidence runner[{cell.cell_index}] stdout is not canonical JSON")
        _write_immutable_json(
            root,
            result_path,
            result,
            label=f"Q4 evidence runner result {cell.cell_index}",
            allow_identical=False,
        )
    try:
        checked = validate_publication_q4_evidence_validation_result_v4(
            result,
            expected_coordinate=cell.coordinate,
            expected_request_sha256=request_sha256,
            expected_raw_evidence_manifest_sha256=raw_evidence_ref[
                "content_identity_sha256"
            ],
        )
    except Exception as error:
        _fail(f"Q4 evidence runner result[{cell.cell_index}] rejected: {error}")
    if checked.get("replay_result") != QUALIFIED_REPLAY_RESULT:
        _fail(f"Q4 evidence runner[{cell.cell_index}] did not qualify physical evidence")
    return checked


def _build_q4_validation_cells_v4(
    *,
    root: Path,
    graph_dir: Path,
    materials: Sequence[Mapping[str, Any]],
    q4_input: Mapping[str, Any],
    q4_input_ref: Mapping[str, Any],
    trust: Mapping[str, Any],
    context_refs: Sequence[Mapping[str, Any]],
    binding_pins: Mapping[str, str],
    set_pins: Mapping[str, str],
    launcher_refs: Mapping[str, Mapping[str, Any]],
    launcher_pins: Mapping[str, str],
) -> tuple[
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    requests: list[dict[str, Any]] = []
    request_refs: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    record_refs: list[dict[str, Any]] = []
    for position, material in enumerate(materials):
        cell = material["cell"]
        snapshot = material["authority_snapshot"]
        common = _common_validation_bindings_v4(
            q4_input=q4_input,
            q4_input_ref=q4_input_ref,
            trust=trust,
            system=cell.system,
            binding_pins=binding_pins,
            set_pins=set_pins,
            launcher_refs=launcher_refs,
            launcher_pins=launcher_pins,
        )
        try:
            request = build_backend_runtime_validation_request_v2(
                **cell.coordinate,
                context_ref=context_refs[SYSTEMS.index(cell.system)],
                runtime_authority_ref=snapshot["runtime_authority_ref"],
                runtime_authority_sha256=snapshot["runtime_authority_sha256"],
                raw_evidence_ref=material["raw_evidence_ref"],
                **common,
            )
        except Exception as error:
            _fail(f"Q4 validation request[{position}] construction rejected: {error}")
        request_ref = _write_typed_graph_node_v4(
            root=root,
            path=graph_dir / "validation-requests" / f"{cell.arm_id}.json",
            value=request,
            schema_version=VALIDATION_RECORD_SCHEMA_VERSION,
            artifact_kind=VALIDATION_REQUEST_KIND,
            identity_field="request_sha256",
            label=f"Q4 validation request {position}",
        )
        result = _invoke_q4_evidence_runner_v4(
            root=root,
            graph_dir=graph_dir,
            cell=cell,
            trust=trust,
            request_ref=request_ref,
            request_sha256=request["request_sha256"],
            raw_evidence_ref=material["raw_evidence_ref"],
        )
        try:
            record = build_backend_runtime_validation_record_v2(
                **cell.coordinate,
                request_ref=request_ref,
                runtime_authority_ref=snapshot["runtime_authority_ref"],
                runtime_authority_sha256=snapshot["runtime_authority_sha256"],
                raw_evidence_ref=material["raw_evidence_ref"],
                replay_result=result["replay_result"],
                **common,
            )
        except Exception as error:
            _fail(f"Q4 validation record[{position}] construction rejected: {error}")
        record_ref = _write_typed_graph_node_v4(
            root=root,
            path=graph_dir / "validation-records" / f"{cell.arm_id}.json",
            value=record,
            schema_version=VALIDATION_RECORD_SCHEMA_VERSION,
            artifact_kind=VALIDATION_RECORD_KIND,
            identity_field="validation_record_sha256",
            label=f"Q4 validation record {position}",
        )
        requests.append(request)
        request_refs.append(request_ref)
        records.append(record)
        record_refs.append(record_ref)
    return requests, request_refs, records, record_refs


def _build_q4_validation_index_and_catalog_v4(
    *,
    root: Path,
    graph_dir: Path,
    q4_input: Mapping[str, Any],
    q4_input_ref: Mapping[str, Any],
    trust: Mapping[str, Any],
    context_refs: Sequence[Mapping[str, Any]],
    request_refs: Sequence[Mapping[str, Any]],
    record_refs: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    binding_pins: Mapping[str, str],
    set_pins: Mapping[str, str],
    launcher_refs: Mapping[str, Mapping[str, Any]],
    launcher_pins: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    cells = backend_q4_cells_v1()
    if (
        type(records) is not list
        or len(records) != CELL_COUNT
        or type(record_refs) is not list
        or len(record_refs) != CELL_COUNT
        or type(request_refs) is not list
        or len(request_refs) != CELL_COUNT
        or type(context_refs) is not list
        or len(context_refs) != len(SYSTEMS)
    ):
        _fail("Q4 catalog requires the exact 560-record physical replay graph")
    replay_bool_fields = (
        "accepted",
        "synthetic",
        "nonpublication",
        "publication_capable",
        "deterministic_replay_completed",
    )

    def _same_typed_content_ref(
        left: Any, right: Any,
    ) -> bool:
        fields = {
            "artifact_schema_version",
            "artifact_kind",
            "descriptor",
            "content_identity_sha256",
        }
        if (
            type(left) is not dict
            or type(right) is not dict
            or set(left) != fields
            or set(right) != fields
            or type(left.get("descriptor")) is not dict
            or type(right.get("descriptor")) is not dict
        ):
            return False
        return (
            left["artifact_schema_version"]
            == right["artifact_schema_version"]
            and left["artifact_kind"] == right["artifact_kind"]
            and left["content_identity_sha256"]
            == right["content_identity_sha256"]
            and left["descriptor"].get("size_bytes")
            == right["descriptor"].get("size_bytes")
            and left["descriptor"].get("sha256")
            == right["descriptor"].get("sha256")
        )

    for position, (record, record_ref, request_ref, cell) in enumerate(
        zip(records, record_refs, request_refs, cells)
    ):
        replay = record.get("replay_result") if type(record) is dict else None
        unsigned = (
            {
                key: item
                for key, item in record.items()
                if key != "validation_record_sha256"
            }
            if type(record) is dict
            else {}
        )
        if (
            type(record) is not dict
            or any(
                record.get(field) != value
                for field, value in cell.coordinate.items()
            )
            or type(replay) is not dict
            or replay != QUALIFIED_REPLAY_RESULT
            or any(type(replay.get(field)) is not bool for field in replay_bool_fields)
            or type(replay.get("blocker_codes")) is not list
            or type(record_ref) is not dict
            or record_ref.get("content_identity_sha256")
            != record.get("validation_record_sha256")
            or record.get("validation_record_sha256")
            != validation_canonical_identity(unsigned)
            or not _same_typed_content_ref(record.get("request_ref"), request_ref)
        ):
            _fail(
                f"Q4 validation record[{position}] is not bound to a qualified "
                "physical replay"
            )
    shards: list[dict[str, Any]] = []
    shard_refs: list[dict[str, Any]] = []
    for system_position, system in enumerate(SYSTEMS):
        start = system_position * 140
        stop = start + 140
        common = _common_validation_bindings_v4(
            q4_input=q4_input,
            q4_input_ref=q4_input_ref,
            trust=trust,
            system=system,
            binding_pins=binding_pins,
            set_pins=set_pins,
            launcher_refs=launcher_refs,
            launcher_pins=launcher_pins,
        )
        try:
            shard = build_backend_runtime_validation_system_shard_v2(
                system=system,
                context_ref=context_refs[system_position],
                validation_record_refs=[
                    {
                        **cells[position].coordinate,
                        "validation_record_ref": copy.deepcopy(
                            record_refs[position]
                        ),
                    }
                    for position in range(start, stop)
                ],
                **common,
            )
        except Exception as error:
            _fail(f"Q4 {system} validation shard construction rejected: {error}")
        shard_ref = _write_typed_graph_node_v4(
            root=root,
            path=graph_dir / "system-shards" / f"{system}.json",
            value=shard,
            schema_version=VALIDATION_RECORD_SCHEMA_VERSION,
            artifact_kind=VALIDATION_SHARD_KIND,
            identity_field="system_shard_sha256",
            label=f"Q4 {system} validation shard",
        )
        shards.append(shard)
        shard_refs.append(shard_ref)
    try:
        index = build_backend_runtime_validation_index_v2(
            system_shards=shards,
            system_shard_refs=shard_refs,
            q4_input_ref=q4_input_ref,
            q4_input_sha256=q4_input["input_index_sha256"],
            q4_validator_authority_ref=trust["validator_ref"],
            q4_validator_authority_sha256=trust["validator"]["authority_sha256"],
            runner_authority_ref=trust["runner_ref"],
            runner_authority_sha256=trust["runner"]["runner_authority_sha256"],
            publication_launcher_invocation_v3_ref=trust["invocation_ref"],
            publication_launcher_invocation_v3_sha256=trust["invocation"][
                "invocation_sha256"
            ],
            runner_invocation_identity_sha256=trust["snapshot"][
                "runner_invocation_identity_sha256"
            ],
            expected_runtime_binding_identity_v4_sha256_by_system=binding_pins,
            expected_runtime_authority_set_sha256_by_system=set_pins,
            expected_launcher_runtime_authority_ref_by_system=launcher_refs,
            expected_launcher_runtime_authority_sha256_by_system=launcher_pins,
        )
    except Exception as error:
        _fail(f"Q4 validation global index construction rejected: {error}")
    index_ref = _write_typed_graph_node_v4(
        root=root,
        path=graph_dir / "backend-runtime-validation-record-set-index-v2.json",
        value=index,
        schema_version=VALIDATION_RECORD_SCHEMA_VERSION,
        artifact_kind=VALIDATION_INDEX_KIND,
        identity_field="index_sha256",
        label="Q4 validation global index",
    )
    system_graphs = copy.deepcopy(index["system_shards"])
    context_projection = [
        {
            "system": item["system"],
            "context_ref": item["context_ref"],
            "context_sha256": item["context_sha256"],
        }
        for item in system_graphs
    ]
    request_projection = [
        {
            "coordinate": cells[position].coordinate,
            "validation_request_ref": copy.deepcopy(request_refs[position]),
        }
        for position in range(CELL_COUNT)
    ]
    record_projection = [
        {
            "coordinate": cells[position].coordinate,
            "validation_record_ref": copy.deepcopy(record_refs[position]),
        }
        for position in range(CELL_COUNT)
    ]
    validation_cells = [
        {
            "coordinate": cells[position].coordinate,
            "validation_request_ref": copy.deepcopy(request_refs[position]),
            "validation_record_ref": copy.deepcopy(record_refs[position]),
        }
        for position in range(CELL_COUNT)
    ]
    expected_context_set = validation_canonical_identity(context_projection)
    expected_shard_set = index["system_shard_set_sha256"]
    expected_request_set = validation_canonical_identity(request_projection)
    expected_record_set = index["validation_record_global_set_sha256"]
    catalog_material = {
        "schema_version": Q4_CATALOG_SCHEMA_VERSION,
        "artifact_kind": Q4_CATALOG_KIND,
        "status": Q4_CATALOG_STATUS,
        "qualification_accepted": False,
        "trusted_replay_completed": False,
        "deterministic_replay_assessed": False,
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
        "authorization_eligible": False,
        "execution_authorized": False,
        "validation_records_authenticated": False,
        "q4_input_ref": copy.deepcopy(dict(q4_input_ref)),
        "q4_input_sha256": q4_input["input_index_sha256"],
        "q4_validator_authority_ref": copy.deepcopy(trust["validator_ref"]),
        "q4_validator_authority_sha256": trust["validator"]["authority_sha256"],
        "runner_authority_ref": copy.deepcopy(trust["runner_ref"]),
        "runner_authority_sha256": trust["runner"]["runner_authority_sha256"],
        "publication_launcher_invocation_v3_ref": copy.deepcopy(
            trust["invocation_ref"]
        ),
        "publication_launcher_invocation_v3_sha256": trust["invocation"][
            "invocation_sha256"
        ],
        "runner_invocation_identity_sha256": trust["snapshot"][
            "runner_invocation_identity_sha256"
        ],
        "records_v2_global_index_ref": index_ref,
        "records_v2_global_index_sha256": index["index_sha256"],
        "system_graphs": system_graphs,
        "system_context_set_sha256": expected_context_set,
        "system_shard_set_sha256": expected_shard_set,
        "validation_cells": validation_cells,
        "validation_request_global_set_sha256": expected_request_set,
        "validation_record_global_set_sha256": expected_record_set,
        "coverage": {
            "system_count": 4,
            "contexts_per_system": 1,
            "shards_per_system": 1,
            "cells_per_system": 140,
            "validation_request_count": 560,
            "validation_record_count": 560,
        },
    }
    expected_catalog_sha = _canonical_sha(catalog_material)
    try:
        catalog = build_backend_runtime_qualification_v4_catalog(
            q4_input_ref=q4_input_ref,
            q4_validator_authority_ref=trust["validator_ref"],
            runner_authority_ref=trust["runner_ref"],
            publication_launcher_invocation_v3_ref=trust["invocation_ref"],
            records_v2_global_index=index,
            records_v2_global_index_ref=index_ref,
            system_context_refs=context_refs,
            system_shard_refs=shard_refs,
            validation_request_refs=request_refs,
            validation_record_refs=record_refs,
            expected_q4_input_sha256=q4_input["input_index_sha256"],
            expected_q4_validator_authority_sha256=trust["validator"][
                "authority_sha256"
            ],
            expected_runner_authority_sha256=trust["runner"][
                "runner_authority_sha256"
            ],
            expected_publication_launcher_invocation_v3_sha256=trust[
                "invocation"
            ]["invocation_sha256"],
            expected_runner_invocation_identity_sha256=trust["snapshot"][
                "runner_invocation_identity_sha256"
            ],
            expected_records_v2_global_index_sha256=index["index_sha256"],
            expected_system_context_set_sha256=expected_context_set,
            expected_system_shard_set_sha256=expected_shard_set,
            expected_validation_request_global_set_sha256=expected_request_set,
            expected_validation_record_global_set_sha256=expected_record_set,
            expected_catalog_semantic_sha256=expected_catalog_sha,
        )
    except Exception as error:
        _fail(f"Q4 catalog construction rejected physical replay graph: {error}")
    catalog_path = graph_dir / "backend-runtime-qualification-v4-catalog.json"
    _write_immutable_json(
        root,
        catalog_path,
        catalog,
        label="Q4 runtime qualification v4 catalog",
    )
    return index, {"catalog": catalog, "catalog_path": catalog_path}


def finalize_backend_q4_qualification_graph_v4_adapter(
    *,
    project_root: Path,
    source_registry: dict[str, Any],
    phase_a_records: list[dict[str, Any]],
    graph_dir: Path,
) -> dict[str, Any]:
    """Finalize the formal v2 graph after hermetic physical replay."""

    registry, materials = _load_phase_a_runtime_material_v4(
        root=project_root,
        source_registry=source_registry,
        phase_a_records=phase_a_records,
    )
    trust = _load_q4_validation_trust_roots_v4(
        root=project_root,
        source_registry=source_registry,
        registry=registry,
    )
    (
        q4_input,
        q4_input_ref,
        binding_pins,
        set_pins,
        launcher_refs,
        launcher_pins,
    ) = _build_q4_input_index_from_runtime_material_v4(
        root=project_root,
        source_registry=source_registry,
        registry=registry,
        materials=materials,
        graph_dir=graph_dir,
    )
    _, context_refs = _build_q4_validation_contexts_v4(
        root=project_root,
        graph_dir=graph_dir,
        q4_input=q4_input,
        q4_input_ref=q4_input_ref,
        trust=trust,
        binding_pins=binding_pins,
        set_pins=set_pins,
        launcher_refs=launcher_refs,
        launcher_pins=launcher_pins,
    )
    _, request_refs, records, record_refs = _build_q4_validation_cells_v4(
        root=project_root,
        graph_dir=graph_dir,
        materials=materials,
        q4_input=q4_input,
        q4_input_ref=q4_input_ref,
        trust=trust,
        context_refs=context_refs,
        binding_pins=binding_pins,
        set_pins=set_pins,
        launcher_refs=launcher_refs,
        launcher_pins=launcher_pins,
    )
    _, catalog_result = _build_q4_validation_index_and_catalog_v4(
        root=project_root,
        graph_dir=graph_dir,
        q4_input=q4_input,
        q4_input_ref=q4_input_ref,
        trust=trust,
        context_refs=context_refs,
        request_refs=request_refs,
        record_refs=record_refs,
        records=records,
        binding_pins=binding_pins,
        set_pins=set_pins,
        launcher_refs=launcher_refs,
        launcher_pins=launcher_pins,
    )
    return {"catalog_path": catalog_result["catalog_path"]}


_Q4_SOCKET_ROLES = ("container_engine", "analytics_execution")
_Q4_IMAGE_ROLES = (
    "cpu_worker",
    "gpu_worker",
    "deepstream_runtime",
    "savant_runtime",
    "openvino_gva_runtime",
    "gstreamer_custom_runtime",
)
_Q4_SOCKET_PIN_FIELDS = {
    "role",
    "transport",
    "ownership",
    "path",
    "device",
    "inode",
    "owner_uid",
    "owner_gid",
    "service_authority",
}
_Q4_IMAGE_PIN_FIELDS = {
    "role",
    "reference",
    "image_id",
    "os",
    "architecture",
    "engine_socket_role",
}
_Q4_GUARDIAN_PIN_FIELDS = {
    "preprocessing_contract",
    "preprocessing_receipt",
    "preprocessing_authority",
    "preprocessing_authority_sha256",
    "service_identity_sha256",
    "policy_contract_sha256",
}


def _socket_transport_from_proc_v1(*, path: Path, inode: int) -> str:
    try:
        payload = Path("/proc/net/unix").read_text(encoding="ascii")
    except (OSError, UnicodeError) as error:
        _fail(f"cannot inspect live AF_UNIX transport: {error}")
    matches: list[str] = []
    for raw in payload.splitlines()[1:]:
        fields = raw.split(maxsplit=7)
        if len(fields) < 7:
            continue
        observed_path = fields[7] if len(fields) == 8 else ""
        # `/proc/net/unix` exposes the kernel socket-object inode, while the
        # immutable contract pins the filesystem socket-node inode returned by
        # lstat(2).  They are distinct identities on Linux.  Cross-bind the
        # transport through the exact canonical pathname and keep the node
        # identity check on lstat above.
        if fields[6].isdigit() and observed_path == str(path):
            matches.append(fields[4])
    if len(matches) != 1:
        _fail("live AF_UNIX socket is absent or ambiguous in /proc/net/unix")
    by_type = {
        "0001": "AF_UNIX/SOCK_STREAM",
        "0005": "AF_UNIX/SOCK_SEQPACKET",
    }
    transport = by_type.get(matches[0])
    if transport is None:
        _fail("live AF_UNIX socket transport is unsupported")
    return transport


def _live_socket_pin_v1(
    *, root: Path, value: Any, expected_role: str
) -> tuple[dict[str, Any], Path]:
    if type(value) is not dict or set(value) != _Q4_SOCKET_PIN_FIELDS:
        _fail(f"{expected_role} socket pin fields drifted")
    role = value.get("role")
    transport = value.get("transport")
    ownership = value.get("ownership")
    path_value = value.get("path")
    if (
        role != expected_role
        or transport
        not in {"AF_UNIX/SOCK_STREAM", "AF_UNIX/SOCK_SEQPACKET"}
        or type(path_value) is not str
        or not path_value.startswith("/")
        or "\x00" in path_value
        or os.path.normpath(path_value) != path_value
        or any(
            type(value.get(field)) is not int or value[field] < 0
            for field in ("device", "inode", "owner_uid", "owner_gid")
        )
    ):
        _fail(f"{expected_role} socket pin values drifted")
    if expected_role == "container_engine":
        if (
            transport != "AF_UNIX/SOCK_STREAM"
            or ownership != "external_container_engine"
            or value.get("service_authority") is not None
        ):
            _fail("container engine socket ownership/transport drifted")
    else:
        if (
            transport != "AF_UNIX/SOCK_SEQPACKET"
            or ownership != "executor_managed_sidecar_v1"
        ):
            _fail("analytics execution socket ownership/transport drifted")
        _revalidate_descriptor(
            root,
            value.get("service_authority"),
            label="analytics sidecar startup authority",
        )
    path = Path(path_value)
    try:
        info = path.lstat()
    except OSError as error:
        _fail(f"{expected_role} live socket is unavailable: {error}")
    if (
        not stat.S_ISSOCK(info.st_mode)
        or _is_link_or_reparse(info)
        or int(info.st_dev) != value["device"]
        or int(info.st_ino) != value["inode"]
        or int(info.st_uid) != value["owner_uid"]
        or int(info.st_gid) != value["owner_gid"]
        or _socket_transport_from_proc_v1(
            path=path, inode=int(value["inode"])
        )
        != transport
    ):
        _fail(f"{expected_role} live identity drifted")
    return copy.deepcopy(value), path


def _docker_http_body_v1(*, engine_socket_path: Path, target: str) -> bytes:
    request = (
        f"GET {target} HTTP/1.1\r\n"
        "Host: docker\r\n"
        "Accept: application/json\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii")
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.settimeout(10.0)
    try:
        endpoint.connect(str(engine_socket_path))
        endpoint.sendall(request)
        chunks: list[bytes] = []
        size = 0
        while True:
            chunk = endpoint.recv(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > 64 * 1024 * 1024:
                _fail("container image inspection response exceeded its bound")
            chunks.append(chunk)
    except OSError as error:
        _fail(f"container image inspection transport failed: {error}")
    finally:
        endpoint.close()
    payload = b"".join(chunks)
    head, separator, body = payload.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    if separator != b"\r\n\r\n" or not lines or lines[0] != b"HTTP/1.1 200 OK":
        _fail("container image inspection returned a non-success response")
    headers: dict[bytes, bytes] = {}
    for line in lines[1:]:
        name, marker, item = line.partition(b":")
        if marker != b":" or not name:
            _fail("container image inspection response headers are malformed")
        key = name.strip().lower()
        if key in headers:
            _fail("container image inspection response has duplicate headers")
        headers[key] = item.strip()
    encoding = headers.get(b"transfer-encoding")
    if encoding is not None:
        if encoding.lower() != b"chunked":
            _fail("container image inspection transfer encoding is unsupported")
        decoded = bytearray()
        cursor = body
        while True:
            line, marker, cursor = cursor.partition(b"\r\n")
            if marker != b"\r\n":
                _fail("container image inspection chunk header is truncated")
            try:
                length = int(line.split(b";", 1)[0], 16)
            except ValueError:
                _fail("container image inspection chunk length is invalid")
            if length == 0:
                if cursor not in {b"\r\n", b""}:
                    _fail("container image inspection chunk trailer is unsupported")
                break
            if len(cursor) < length + 2 or cursor[length : length + 2] != b"\r\n":
                _fail("container image inspection chunk is truncated")
            decoded.extend(cursor[:length])
            cursor = cursor[length + 2 :]
        body = bytes(decoded)
    elif b"content-length" in headers:
        try:
            expected = int(headers[b"content-length"])
        except ValueError:
            _fail("container image inspection content length is invalid")
        if expected != len(body):
            _fail("container image inspection body length drifted")
    return body


def _inspect_container_image_v1(
    *, engine_socket_path: Path, reference: str
) -> dict[str, str]:
    encoded = urllib.parse.quote(reference, safe="")
    payload = _docker_http_body_v1(
        engine_socket_path=engine_socket_path,
        target=f"/images/{encoded}/json",
    )
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        _fail(f"container image inspection JSON is invalid: {error}")
    if type(value) is not dict:
        _fail("container image inspection did not return an object")
    image_id = value.get("Id")
    system = value.get("Os")
    architecture = value.get("Architecture")
    if (
        type(image_id) is not str
        or re.fullmatch(r"sha256:[0-9a-f]{64}", image_id) is None
        or system != "linux"
        or type(architecture) is not str
        or not architecture
    ):
        _fail("container image inspection identity/platform drifted")
    return {
        "reference": reference,
        "image_id": image_id,
        "os": system,
        "architecture": architecture,
    }


def _image_pin_v1(value: Any, *, expected_role: str) -> dict[str, str]:
    if type(value) is not dict or set(value) != _Q4_IMAGE_PIN_FIELDS:
        _fail(f"{expected_role} image pin fields drifted")
    if (
        value.get("role") != expected_role
        or type(value.get("reference")) is not str
        or not value["reference"]
        or any(character in value["reference"] for character in "\r\n\x00")
        or re.fullmatch(r"sha256:[0-9a-f]{64}", str(value.get("image_id")))
        is None
        or value.get("os") != "linux"
        or type(value.get("architecture")) is not str
        or not value["architecture"]
        or value.get("engine_socket_role") != "container_engine"
    ):
        _fail(f"{expected_role} image pin values drifted")
    return copy.deepcopy(value)


def _accepted_guardian_pins_v1(
    value: Any,
    *,
    registered_files: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _Q4_GUARDIAN_PIN_FIELDS:
        _fail("accepted-policy analytics guardian pin fields drifted")
    contract = _descriptor(
        value.get("preprocessing_contract"),
        label="accepted-policy guardian preprocessing contract",
    )
    receipt = _descriptor(
        value.get("preprocessing_receipt"),
        label="accepted-policy guardian preprocessing receipt",
    )
    try:
        from publication_guardian_accepted_policy_preprocessing_contract_v1 import (
            validate_accepted_policy_guardian_preprocessing_authority_v1,
        )

        authority = validate_accepted_policy_guardian_preprocessing_authority_v1(
            value.get("preprocessing_authority")
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"accepted-policy analytics guardian authority drifted: {error}")
    if (
        value.get("preprocessing_authority_sha256") != _canonical_sha(authority)
        or not _SHA_RE.fullmatch(
            str(value.get("service_identity_sha256", ""))
        )
        or not _SHA_RE.fullmatch(
            str(value.get("policy_contract_sha256", ""))
        )
        or authority.get("preprocessing_contract_file_sha256")
        != contract["sha256"]
        or authority.get("materialization_receipt_file_sha256")
        != receipt["sha256"]
        or authority.get("policy_contract_sha256")
        != value.get("policy_contract_sha256")
    ):
        _fail("accepted-policy analytics guardian independent pins drifted")
    if registered_files is not None and (
        contract not in registered_files or receipt not in registered_files
    ):
        _fail(
            "accepted-policy analytics guardian artifacts are outside the "
            "registered file closure"
        )
    return {
        "preprocessing_contract": contract,
        "preprocessing_receipt": receipt,
        "preprocessing_authority": authority,
        "preprocessing_authority_sha256": value[
            "preprocessing_authority_sha256"
        ],
        "service_identity_sha256": value["service_identity_sha256"],
        "policy_contract_sha256": value["policy_contract_sha256"],
    }


def _assert_live_analytics_guardian_v1(
    *,
    root: Path,
    analytics_pin: Mapping[str, Any],
    images: Sequence[Mapping[str, Any]],
    guardian_pins: Mapping[str, Any],
) -> None:
    guardian = _accepted_guardian_pins_v1(guardian_pins)
    for field, label in (
        ("preprocessing_contract", "accepted guardian preprocessing contract"),
        ("preprocessing_receipt", "accepted guardian preprocessing receipt"),
    ):
        if _revalidate_descriptor(root, guardian[field], label=label) != guardian[field]:
            _fail(f"{label} physical identity drifted")
    authority_descriptor = _revalidate_descriptor(
        root,
        analytics_pin.get("service_authority"),
        label="analytics production guardian readiness authority",
    )
    authority_path = root / authority_descriptor["path"]
    authority = _load_canonical_json(
        authority_path,
        label="analytics production guardian readiness authority",
    )
    worker_images = {
        str(item.get("role")).removesuffix("_worker"): item.get("image_id")
        for item in images
        if type(item) is dict and item.get("role") in {"cpu_worker", "gpu_worker"}
    }
    preprocessing_authority = guardian["preprocessing_authority"]
    if worker_images != preprocessing_authority["worker_image_ids"]:
        _fail("analytics production guardian worker image pin coverage drifted")
    try:
        from checkpoint_gstreamer_analytics_sidecar import (
            assert_publication_sidecar_service_authority_v1,
        )

        checked = assert_publication_sidecar_service_authority_v1(
            authority,
            expected_front_socket=analytics_pin["path"],
            expected_execution_config_identity_sha256=preprocessing_authority[
                "execution_config_identity_sha256"
            ],
            expected_binding_set_identity_sha256=preprocessing_authority[
                "binding_set_identity_sha256"
            ],
            expected_worker_image_ids=preprocessing_authority["worker_image_ids"],
            expected_preprocessing_contract_authority=preprocessing_authority,
            expected_service_identity_sha256=guardian["service_identity_sha256"],
            expected_policy_contract_sha256=guardian["policy_contract_sha256"],
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"analytics production guardian is not live: {error}")
    expected_pin = {
        key: analytics_pin[key]
        for key in ("path", "device", "inode", "owner_uid", "owner_gid")
    }
    if (
        checked.get("front_socket") != expected_pin
        or Path(str(checked.get("readiness_artifact_path"))).resolve(strict=True)
        != authority_path
    ):
        _fail("analytics production guardian readiness/socket cross-binding drifted")


def _default_recheck_pins(**kwargs: Any) -> dict[str, Any]:
    registry = kwargs.get("source_registry")
    if type(registry) is not dict:
        _fail("source registry is unavailable to pin recheck")
    root = _physical_root(kwargs.get("project_root"))
    files = registry.get("files")
    sockets = registry.get("sockets")
    images = registry.get("images")
    guardian = _accepted_guardian_pins_v1(
        registry.get("analytics_guardian"),
        registered_files=files if type(files) is list else None,
    )
    if type(files) is not list or type(sockets) is not list or type(images) is not list:
        _fail("source registry file/socket/image sets are unavailable")
    if bool(sockets) != bool(images):
        _fail("source registry live socket/image coverage is partial")
    if sockets:
        if len(sockets) != len(_Q4_SOCKET_ROLES):
            _fail("source registry live socket coverage is not exact two")
        normalized_sockets: list[dict[str, Any]] = []
        paths: dict[str, Path] = {}
        for expected_role, raw in zip(_Q4_SOCKET_ROLES, sockets, strict=True):
            checked, path = _live_socket_pin_v1(
                root=root, value=raw, expected_role=expected_role
            )
            normalized_sockets.append(checked)
            paths[expected_role] = path
        if normalized_sockets != sockets:
            _fail("source registry live socket normalization drifted")
        if not images:
            _fail("source registry image pins are missing")
        normalized_images: list[dict[str, str]] = []
        observed_roles: list[str] = []
        for raw in images:
            if type(raw) is not dict or type(raw.get("role")) is not str:
                _fail("source registry image pin role is invalid")
            role = raw["role"]
            if role not in _Q4_IMAGE_ROLES or role in observed_roles:
                _fail("source registry image pin role coverage drifted")
            observed_roles.append(role)
            pin = _image_pin_v1(raw, expected_role=role)
            observed = _inspect_container_image_v1(
                engine_socket_path=paths["container_engine"],
                reference=pin["reference"],
            )
            if observed != {
                key: pin[key]
                for key in ("reference", "image_id", "os", "architecture")
            }:
                _fail(f"{role} live container image identity drifted")
            normalized_images.append(pin)
        if observed_roles != sorted(observed_roles):
            _fail("source registry image pins are not role-sorted")
        if normalized_images != images:
            _fail("source registry image pin normalization drifted")
        _assert_live_analytics_guardian_v1(
            root=root,
            analytics_pin=normalized_sockets[1],
            images=normalized_images,
            guardian_pins=guardian,
        )
    return {
        "status": "verified",
        "source_registry_sha256": registry["registry_sha256"],
        "file_set_sha256": _canonical_sha(files),
        "socket_set_sha256": _canonical_sha(sockets),
        "image_set_sha256": _canonical_sha(images),
    }


@dataclass(frozen=True, slots=True)
class BackendQ4TwoPhaseDependenciesV1:
    """Application adapters plus the fixed physical authorization APIs."""

    recheck_pins: Callable[..., dict[str, Any]] = _default_recheck_pins
    materialize_qualification_input: Callable[..., dict[str, Any]] = (
        materialize_backend_q4_runtime_input_v4_adapter
    )
    run_native_qualification: BackendQ4NativeQualificationAdapterV1 = (
        run_backend_q4_native_runtime_v4_adapter
    )
    finalize_qualification_graph: Callable[..., dict[str, Any]] = (
        finalize_backend_q4_qualification_graph_v4_adapter
    )
    promote_qualification: Callable[..., dict[str, Any]] = (
        promote_backend_runtime_qualification_v4
    )
    load_qualification: Callable[..., dict[str, Any]] = (
        load_backend_runtime_qualification_v4_binding
    )
    build_identity_manifest: Callable[..., dict[str, Any]] = (
        build_full_publication_identity_manifest_v2
    )
    load_identity: Callable[..., dict[str, Any]] = (
        load_full_publication_identity_artifacts
    )
    build_backend_grant: Callable[[dict[str, Any]], dict[str, Any]] = (
        backend_runtime_grant_from_identity_artifacts
    )
    validate_backend_grant: Callable[[Any], dict[str, Any]] = (
        validate_pre_run_backend_runtime_grant_v3
    )
    execute_production_arm: BackendQ4ProductionArmAdapterV1 = (
        run_backend_q4_production_v3_adapter_v1
    )
    persist_production_authority: Callable[..., dict[str, Any]] = (
        persist_backend_production_output_receipt_authority_v1
    )
    build_pair_sizing_input: Callable[..., dict[str, Any]] = (
        build_backend_pair_archive_sizing_input_v1
    )
    materialize_pair_sizing: Callable[..., dict[str, Any]] = (
        materialize_backend_pair_archive_sizing_receipts_v1
    )
    load_pair_sizing: Callable[..., list[dict[str, Any]]] = (
        load_operator_sizing_rows_v1
    )


def default_backend_q4_two_phase_dependencies_v1() -> BackendQ4TwoPhaseDependenciesV1:
    """Resolve fixed repository APIs; injectable overrides are test seams only."""

    return BackendQ4TwoPhaseDependenciesV1()


def _default_identity_inputs_from_source_registry_v1(
    *, root: Path, source_path: Path, expected_registry: Mapping[str, Any]
) -> dict[str, Any]:
    try:
        from backend_q4_two_phase_source_registry_v1 import (
            load_backend_q4_two_phase_source_registry_v1,
        )

        loaded = _guarded_cold_load_v1(
            root=root,
            paths=[source_path],
            label="default Q4 source-registry reload",
            callback=lambda: load_backend_q4_two_phase_source_registry_v1(
                project_root=root,
                registry_path=source_path,
            ),
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"default Q4 source-registry reload rejected identity inputs: {error}")
    if (
        type(loaded) is not dict
        or set(loaded) != {"registry", "identity_inputs", "source_registry"}
        or loaded.get("registry") != dict(expected_registry)
        or loaded.get("source_registry")
        != _descriptor_for(root, source_path, label="Q4 source registry")
        or type(loaded.get("identity_inputs")) is not dict
    ):
        _fail("default Q4 source-registry identity input projection drifted")
    return copy.deepcopy(loaded["identity_inputs"])


def _is_link_or_reparse(info: os.stat_result) -> bool:
    attributes = int(getattr(info, "st_file_attributes", 0))
    reparse = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse)


def _snapshot(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


def _physical_root(project_root: Path | str) -> Path:
    candidate = Path(project_root)
    try:
        lexical = candidate.absolute()
        lexical_info = lexical.lstat()
        if _is_link_or_reparse(lexical_info):
            _fail("project_root may not be a link/reparse alias")
        root = candidate.resolve(strict=True)
        info = root.lstat()
    except OSError as error:
        _fail(f"project_root is unavailable: {error}")
    if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
        _fail("project_root must be a physical directory")
    return root


def _active_physical_custody_v1(root: Path | None = None) -> PhysicalRootCustodyV1 | None:
    custody = _ACTIVE_PHYSICAL_CUSTODY.get()
    if custody is None:
        return None
    try:
        custody.verify()
    except PublicationPhysicalIoV1Error as error:
        _fail(f"B4 physical root custody changed: {error}")
    if root is not None and custody.root != root:
        _fail("B4 active physical custody belongs to another project_root")
    return custody


@contextmanager
def _held_physical_root_v1(
    root: Path,
) -> Iterator[PhysicalRootCustodyV1]:
    active = _ACTIVE_PHYSICAL_CUSTODY.get()
    if active is not None:
        checked = _active_physical_custody_v1(root)
        assert checked is not None
        yield checked
        return
    try:
        with PhysicalRootCustodyV1.open(
            root, label="backend Q4 two-phase project_root"
        ) as custody:
            token = _ACTIVE_PHYSICAL_CUSTODY.set(custody)
            try:
                yield custody
                custody.verify()
            finally:
                _ACTIVE_PHYSICAL_CUSTODY.reset(token)
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except PublicationPhysicalIoV1Error as error:
        _fail(f"B4 physical root custody failed: {error}")


def _guarded_cold_load_v1(
    *,
    root: Path,
    paths: Sequence[Path | str],
    label: str,
    callback: Callable[[], Any],
) -> Any:
    """Run a path-based read callback inside the held physical namespace."""

    custody = _active_physical_custody_v1(root)
    if custody is None:
        return callback()
    unique_paths: list[Path | str] = []
    seen: set[str] = set()
    for value in paths:
        key = str(value)
        if key not in seen:
            seen.add(key)
            unique_paths.append(value)
    try:
        namespace = custody.capture_read_namespace(unique_paths, label=label)
        directories = custody.capture_pinned_directory_epochs(label=label)
        mutation_watch = custody.begin_read_namespace_mutation_watch(
            unique_paths,
            label=label,
        )
    except PublicationPhysicalIoV1Error as error:
        _fail(f"{label} physical namespace pin failed: {error}")
    callback_error: BaseException | None = None
    result: Any = None
    try:
        result = callback()
    except BaseException as error:
        callback_error = error
    verification_error: PublicationPhysicalIoV1Error | None = None
    try:
        custody.verify_read_namespace(namespace, label=label)
        custody.verify_pinned_directory_epochs(directories, label=label)
    except PublicationPhysicalIoV1Error as error:
        verification_error = error
    try:
        custody.verify_pinned_directory_mutation_watch(
            mutation_watch, label=label,
        )
    except PublicationPhysicalIoV1Error as error:
        if verification_error is None:
            verification_error = error
    if verification_error is not None:
        _fail(
            f"{label} physical namespace changed during cold load: "
            f"{verification_error}"
        )
    if callback_error is not None:
        raise callback_error
    return result


def _relative_path(value: Path | str, *, label: str) -> Path:
    text = str(value)
    posix = PurePosixPath(text.replace("\\", "/"))
    windows = PureWindowsPath(text)
    if (
        not text
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        _fail(f"{label} path is unsafe")
    for part in posix.parts:
        stem = part.split(".", 1)[0].upper()
        if stem in _RESERVED or part.endswith((" ", ".")):
            _fail(f"{label} path contains a reserved component")
    return Path(*posix.parts)


def _under_root(
    root: Path,
    value: Path | str,
    *,
    label: str,
    must_exist: bool = False,
) -> Path:
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / _relative_path(candidate, label=label)
    candidate = candidate.absolute()
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as error:
        _fail(f"{label} path is outside project_root: {error}")
    cursor = root
    for part in lexical_relative.parts:
        cursor /= part
        if not cursor.exists():
            break
        try:
            info = cursor.lstat()
        except OSError as error:
            _fail(f"{label} path cannot be inspected: {error}")
        if _is_link_or_reparse(info):
            _fail(f"{label} path contains a link/reparse point")
    try:
        normalized = candidate.resolve(strict=must_exist)
        normalized.relative_to(root)
    except (OSError, ValueError) as error:
        _fail(f"{label} path is missing or outside project_root: {error}")
    if normalized != candidate:
        _fail(f"{label} path resolved through an alias")
    return normalized


def _ensure_directory(root: Path, value: Path | str, *, label: str) -> Path:
    custody = _active_physical_custody_v1(root)
    if custody is not None:
        try:
            return custody.ensure_directory(value, label=label)
        except PublicationPhysicalIoV1Error as error:
            _fail(f"{label} held directory creation failed: {error}")
    directory = _under_root(root, value, label=label)
    relative = directory.relative_to(root)
    cursor = root
    for part in relative.parts:
        cursor /= part
        if cursor.exists():
            info = cursor.lstat()
            if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
                _fail(f"{label} contains an unsafe existing component")
        else:
            try:
                cursor.mkdir()
            except OSError as error:
                _fail(f"{label} directory creation failed: {error}")
            info = cursor.lstat()
            if not stat.S_ISDIR(info.st_mode) or _is_link_or_reparse(info):
                _fail(f"{label} directory creation was replaced")
    return directory


def _read_physical(path: Path, *, label: str) -> bytes:
    custody = _active_physical_custody_v1()
    if custody is not None:
        try:
            _descriptor_value, payload = custody.read_descriptor(
                path,
                label=label,
                maximum=_MAX_CUSTODY_CAPTURE_BYTES,
                capture=True,
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"{label} held physical read failed: {error}")
        assert payload is not None
        return payload
    try:
        before = path.lstat()
        if (
            not stat.S_ISREG(before.st_mode)
            or _is_link_or_reparse(before)
            or int(before.st_nlink) != 1
        ):
            _fail(f"{label} is not an ordinary single-link file")
        descriptor = os.open(
            path,
            os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        try:
            opened = os.fstat(descriptor)
            chunks: list[bytes] = []
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        final = path.lstat()
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except OSError as error:
        _fail(f"{label} cannot be read physically: {error}")
    payload = b"".join(chunks)
    if (
        _snapshot(before) != _snapshot(opened)
        or _snapshot(opened) != _snapshot(after)
        or _snapshot(after) != _snapshot(final)
        or len(payload) != int(after.st_size)
    ):
        _fail(f"{label} changed while it was read")
    return payload


def _descriptor_for(root: Path, path: Path | str, *, label: str) -> dict[str, Any]:
    custody = _active_physical_custody_v1(root)
    if custody is not None:
        try:
            descriptor, _payload = custody.read_descriptor(
                path,
                label=label,
                maximum=_MAX_CUSTODY_DESCRIPTOR_BYTES,
                capture=False,
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"{label} held descriptor read failed: {error}")
        return descriptor
    physical = _under_root(root, path, label=label, must_exist=True)
    payload = _read_physical(physical, label=label)
    return {
        "path": physical.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _descriptor(value: Any, *, label: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != _DESCRIPTOR_FIELDS:
        _fail(f"{label} descriptor fields drifted")
    relative = _relative_path(value.get("path", ""), label=label).as_posix()
    size = value.get("size_bytes")
    digest = value.get("sha256")
    if type(size) is not int or size < 0 or not _SHA_RE.fullmatch(str(digest)):
        _fail(f"{label} descriptor values are invalid")
    return {"path": relative, "size_bytes": size, "sha256": digest}


def _revalidate_descriptor(
    root: Path, value: Any, *, label: str
) -> dict[str, Any]:
    expected = _descriptor(value, label=label)
    observed = _descriptor_for(root, expected["path"], label=label)
    if observed != expected:
        _fail(f"{label} descriptor drifted")
    return observed


def _load_canonical_json(path: Path, *, label: str) -> dict[str, Any]:
    payload = _read_physical(path, label=label)
    try:
        value = json.loads(payload.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{label} is not ASCII JSON: {error}")
    if type(value) is not dict or payload != _canonical_bytes(value):
        _fail(f"{label} is not canonical JSON")
    return value


def _write_immutable_json(
    root: Path,
    path: Path,
    value: Mapping[str, Any],
    *,
    label: str,
    allow_identical: bool = True,
    after_publish_step: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    destination = _under_root(root, path, label=label)
    payload = _canonical_bytes(dict(value))
    with _held_physical_root_v1(root) as custody:
        try:
            descriptor, _identity, disposition = (
                custody.commit_or_adopt_exact_identity(
                    destination,
                    payload,
                    label=label,
                    mode=0o444,
                    create_parents=True,
                    after_publish_step=after_publish_step,
                )
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"{label} held atomic immutable commit failed: {error}")
        if disposition == "adopted" and not allow_identical:
            _fail(f"{label} collision/no-overwrite violation")
        return descriptor


def _atomic_checkpoint(root: Path, path: Path, value: Mapping[str, Any]) -> None:
    destination = _under_root(root, path, label="Q4 checkpoint")
    payload = _canonical_bytes(dict(value))
    custody = _active_physical_custody_v1(root)
    if custody is not None:
        try:
            custody.replace_atomic(
                destination,
                payload,
                label="Q4 checkpoint",
                mode=0o600,
                create_parents=True,
            )
        except PublicationPhysicalIoV1Error as error:
            _fail(f"Q4 checkpoint held atomic commit failed: {error}")
        return
    parent = _ensure_directory(root, destination.parent, label="checkpoint parent")
    handle, name = tempfile.mkstemp(
        prefix=".backend-q4-checkpoint-v1.", suffix=".tmp", dir=parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(handle, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
    except OSError as error:
        _fail(f"Q4 checkpoint atomic commit failed: {error}")
    finally:
        if temporary.exists():
            # Preserve unexpected staged recovery files.  Only this exact local
            # temporary, opened by us and still a plain file, is removable.
            info = temporary.lstat()
            if temporary.parent == parent and stat.S_ISREG(info.st_mode):
                temporary.unlink()


def _inventory_tree(
    root: Path,
    directory: Path,
    *,
    label: str,
    exclude: Sequence[str] = (),
) -> list[dict[str, Any]]:
    physical = _under_root(root, directory, label=label, must_exist=True)
    if not physical.is_dir():
        _fail(f"{label} is not a directory")
    excluded = set(exclude)
    descriptors: list[dict[str, Any]] = []
    for path in sorted(physical.rglob("*"), key=lambda item: item.as_posix()):
        relative_inside = path.relative_to(physical).as_posix()
        if relative_inside in excluded:
            continue
        info = path.lstat()
        if _is_link_or_reparse(info):
            _fail(f"{label} contains a link/reparse point")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode) or int(info.st_nlink) != 1:
            _fail(f"{label} contains an unsafe namespace entry")
        descriptors.append(_descriptor_for(root, path, label=f"{label} file"))
    if len({item["path"] for item in descriptors}) != len(descriptors):
        _fail(f"{label} inventory contains duplicate paths")
    return descriptors


def _reject_circular_claims(value: Any, *, location: str = "source registry") -> None:
    forbidden = {
        "backend_runtime_grant",
        "backend_runtime_grant_sha256",
        "production_authority",
        "publication_ready",
        "promotable",
        "authorization_eligible",
    }
    if type(value) is dict:
        for key, item in value.items():
            if key in forbidden and item is not False and item is not None and item != "":
                _fail(f"{location} contains a circular authorization claim: {key}")
            _reject_circular_claims(item, location=f"{location}.{key}")
    elif type(value) is list:
        for position, item in enumerate(value):
            _reject_circular_claims(item, location=f"{location}[{position}]")


def _validate_source_registry(
    root: Path, source_registry_path: Path | str
) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = _under_root(
        root, source_registry_path, label="Q4 source registry", must_exist=True
    )
    value = _load_canonical_json(path, label="Q4 source registry")
    expected_fields = {
        "schema_version",
        "artifact_kind",
        "status",
        "accepted",
        "model_parity",
        "policy_qualification",
        "resource_qualification",
        "runtime_candidate_registry",
        "analytics_guardian",
        "files",
        "sockets",
        "images",
        "registry_sha256",
    }
    if (
        set(value) != expected_fields
        or value.get("schema_version") != 1
        or value.get("artifact_kind") != SOURCE_REGISTRY_KIND
        or value.get("status") != "accepted_reachable_runtime_candidates"
        or value.get("accepted") is not True
    ):
        _fail("Q4 source registry schema/status drifted")
    unsigned = {key: item for key, item in value.items() if key != "registry_sha256"}
    if value.get("registry_sha256") != _canonical_sha(unsigned):
        _fail("Q4 source registry self-hash drifted")
    files = value.get("files")
    if type(files) is not list or not files:
        _fail("Q4 source registry file closure is empty")
    normalized_files = [
        _descriptor(item, label=f"source file[{position}]")
        for position, item in enumerate(files)
    ]
    if (
        normalized_files != sorted(normalized_files, key=lambda item: item["path"])
        or len({item["path"] for item in normalized_files}) != len(normalized_files)
    ):
        _fail("Q4 source registry file descriptors are not sorted and unique")
    named = [
        _descriptor(value[key], label=f"source {key}")
        for key in (
            "model_parity",
            "policy_qualification",
            "resource_qualification",
            "runtime_candidate_registry",
        )
    ]
    if any(item not in normalized_files for item in named):
        _fail("Q4 named accepted source is outside the registered file closure")
    guardian = _accepted_guardian_pins_v1(
        value.get("analytics_guardian"), registered_files=normalized_files,
    )
    if guardian != value["analytics_guardian"]:
        _fail("Q4 accepted-policy analytics guardian pins did not normalize exactly")
    sockets = value.get("sockets")
    images = value.get("images")
    if type(sockets) is not list or type(images) is not list:
        _fail("Q4 source registry socket/image pins are invalid")
    if bool(sockets) != bool(images):
        _fail("Q4 source registry socket/image pin coverage is partial")
    if sockets:
        if len(sockets) != len(_Q4_SOCKET_ROLES):
            _fail("Q4 source registry socket pin coverage is not exact two")
        normalized_sockets: list[dict[str, Any]] = []
        for expected_role, item in zip(_Q4_SOCKET_ROLES, sockets, strict=True):
            if type(item) is not dict or set(item) != _Q4_SOCKET_PIN_FIELDS:
                _fail(f"Q4 {expected_role} socket pin fields drifted")
            if (
                item.get("role") != expected_role
                or item.get("transport")
                != (
                    "AF_UNIX/SOCK_STREAM"
                    if expected_role == "container_engine"
                    else "AF_UNIX/SOCK_SEQPACKET"
                )
                or item.get("ownership")
                != (
                    "external_container_engine"
                    if expected_role == "container_engine"
                    else "executor_managed_sidecar_v1"
                )
                or type(item.get("path")) is not str
                or not item["path"].startswith("/")
                or "\x00" in item["path"]
                or os.path.normpath(item["path"]) != item["path"]
                or any(
                    type(item.get(field)) is not int or item[field] < 0
                    for field in ("device", "inode", "owner_uid", "owner_gid")
                )
            ):
                _fail(f"Q4 {expected_role} socket pin values drifted")
            authority = item.get("service_authority")
            if expected_role == "container_engine":
                if authority is not None:
                    _fail("Q4 container engine socket may not claim a service authority")
            else:
                checked_authority = _descriptor(
                    authority, label="analytics sidecar startup authority"
                )
                if checked_authority not in normalized_files:
                    _fail(
                        "analytics sidecar startup authority is outside the "
                        "registered file closure"
                    )
            normalized_sockets.append(copy.deepcopy(item))
        if normalized_sockets != sockets:
            _fail("Q4 source registry socket pins did not normalize exactly")
        expected_image_roles = sorted(_Q4_IMAGE_ROLES)
        if len(images) != len(expected_image_roles):
            _fail("Q4 source registry image pin coverage is not exact six")
        normalized_images = [
            _image_pin_v1(item, expected_role=role)
            for role, item in zip(expected_image_roles, images, strict=True)
        ]
        if normalized_images != images:
            _fail("Q4 source registry image pins did not normalize exactly")
    _reject_circular_claims(value)
    for position, descriptor in enumerate(normalized_files):
        _revalidate_descriptor(root, descriptor, label=f"source file[{position}]")
    observed = copy.deepcopy(value)
    observed["files"] = normalized_files
    return path, observed, _descriptor_for(root, path, label="Q4 source registry")


def _pin_recheck(
    *,
    root: Path,
    source_path: Path,
    expected_registry: Mapping[str, Any],
    expected_descriptor: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
    phase: str,
    cell: BackendQ4CellV1 | None,
) -> dict[str, Any]:
    descriptor = _revalidate_descriptor(
        root, expected_descriptor, label="Q4 source registry"
    )
    if descriptor["path"] != source_path.relative_to(root).as_posix():
        _fail("accepted Q4 source registry path changed during execution")
    observed = _load_canonical_json(source_path, label="Q4 source registry")
    if observed != dict(expected_registry) or descriptor != dict(expected_descriptor):
        _fail("accepted Q4 source registry changed during execution")
    # The complete closure is hashed at process preflight and once more before
    # final success.  Rehashing multi-gigabyte media 2,242+ times would make
    # the frozen benchmark unusable.  Every cell still validates the immutable
    # registry envelope, its selected runtime authority/inputs, and the live
    # socket/image pins before and after native execution.
    if phase == "pair_sizing_after":
        _, final_registry, final_descriptor = _validate_source_registry(
            root, source_path
        )
        if (
            final_registry != dict(expected_registry)
            or final_descriptor != dict(expected_descriptor)
        ):
            _fail("accepted Q4 source closure changed before final success")
    try:
        result = dependencies.recheck_pins(
            project_root=root,
            source_registry=copy.deepcopy(observed),
            source_registry_path=source_path,
            phase=phase,
            cell=cell,
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"{phase} external source/socket/image pin recheck failed: {error}")
    expected_fields = {
        "status",
        "source_registry_sha256",
        "file_set_sha256",
        "socket_set_sha256",
        "image_set_sha256",
    }
    if (
        type(result) is not dict
        or set(result) != expected_fields
        or result.get("status") != "verified"
        or result.get("source_registry_sha256")
        != expected_registry.get("registry_sha256")
        or result.get("file_set_sha256")
        != _canonical_sha(expected_registry.get("files"))
        or result.get("socket_set_sha256")
        != _canonical_sha(expected_registry.get("sockets"))
        or result.get("image_set_sha256")
        != _canonical_sha(expected_registry.get("images"))
        or any(
            not _SHA_RE.fullmatch(str(result.get(key, "")))
            for key in (
                "file_set_sha256",
                "socket_set_sha256",
                "image_set_sha256",
            )
        )
    ):
        _fail(f"{phase} source/socket/image pin recheck was not authoritative")
    return copy.deepcopy(result)


@contextmanager
def _exclusive_lock(work_dir: Path) -> Iterator[None]:
    path = work_dir / LOCK_FILENAME
    custody = _active_physical_custody_v1()
    if custody is not None:
        payload = f"pid={os.getpid()}\n".encode("ascii")
        try:
            custody.write_exclusive(
                path,
                payload,
                label="Q4 executor lock",
                mode=0o600,
                create_parents=True,
            )
            _lock_descriptor, _lock_payload, identity = (
                custody.read_descriptor_identity(
                    path,
                    label="Q4 executor lock",
                    maximum=len(payload),
                    capture=True,
                )
            )
        except PublicationPhysicalIoV1Error as error:
            exit_code = (
                EXIT_TRANSIENT if "already exists" in str(error) else EXIT_PERMANENT
            )
            _fail(f"Q4 executor held lock creation failed: {error}", exit_code=exit_code)
        try:
            yield
        finally:
            try:
                custody.unlink_owned_identity(
                    path, identity, label="Q4 executor lock"
                )
            except PublicationPhysicalIoV1Error as error:
                _fail(f"Q4 executor held lock retirement failed: {error}")
        return
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        _fail("Q4 executor is already active", exit_code=EXIT_TRANSIENT)
    except OSError as error:
        _fail(f"Q4 executor lock creation failed: {error}", exit_code=EXIT_TRANSIENT)
    owned = os.fstat(descriptor)
    try:
        payload = f"pid={os.getpid()}\n".encode("ascii")
        os.write(descriptor, payload)
        os.fsync(descriptor)
        after_write = os.fstat(descriptor)
        if (int(after_write.st_dev), int(after_write.st_ino)) != (
            int(owned.st_dev), int(owned.st_ino)
        ):
            _fail("Q4 executor lock inode changed", exit_code=EXIT_TRANSIENT)
        yield
    finally:
        os.close(descriptor)
        try:
            current = path.lstat()
        except FileNotFoundError:
            current = None
        if current is not None and (
            int(current.st_dev), int(current.st_ino)
        ) == (int(owned.st_dev), int(owned.st_ino)):
            path.unlink()


def _initial_checkpoint(
    *, source_registry: Mapping[str, Any], source_descriptor: Mapping[str, Any]
) -> dict[str, Any]:
    cells = backend_q4_cells_v1()
    return {
        "schema_version": 1,
        "artifact_kind": CHECKPOINT_KIND,
        "source_registry": copy.deepcopy(dict(source_descriptor)),
        "source_registry_sha256": source_registry["registry_sha256"],
        "matrix_sha256": _canonical_sha(
            [
                {"coordinate": cell.coordinate, "frozen_run": cell.frozen_run}
                for cell in cells
            ]
        ),
        "phase_a_records": [],
        "phase_a_finalization": None,
        "boundary_record": None,
        "phase_b_context_sha256": None,
        "phase_b_records": [],
        "pair_sizing_finalization": None,
    }


def _checkpoint_value(unsigned: Mapping[str, Any]) -> dict[str, Any]:
    return _seal(unsigned, "checkpoint_sha256")


def _load_or_create_checkpoint(
    *,
    root: Path,
    checkpoint_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    expected = _initial_checkpoint(
        source_registry=source_registry, source_descriptor=source_descriptor
    )
    if not checkpoint_path.exists():
        _atomic_checkpoint(root, checkpoint_path, _checkpoint_value(expected))
        return expected
    value = _validate_sealed(
        _load_canonical_json(checkpoint_path, label="Q4 checkpoint"),
        field="checkpoint_sha256",
        label="Q4 checkpoint",
    )
    unsigned = {key: item for key, item in value.items() if key != "checkpoint_sha256"}
    if set(unsigned) != set(expected):
        _fail("Q4 checkpoint fields drifted")
    for key in (
        "schema_version",
        "artifact_kind",
        "source_registry",
        "source_registry_sha256",
        "matrix_sha256",
    ):
        if unsigned.get(key) != expected[key]:
            _fail(f"Q4 checkpoint {key} differs from this execution")
    if (
        type(unsigned.get("phase_a_records")) is not list
        or type(unsigned.get("phase_b_records")) is not list
        or len(unsigned["phase_a_records"]) > CELL_COUNT
        or len(unsigned["phase_b_records"]) > CELL_COUNT
    ):
        _fail("Q4 checkpoint record prefixes are invalid")
    if unsigned.get("boundary_record") is None and unsigned["phase_b_records"]:
        _fail("Q4 checkpoint contains Phase B progress before a grant boundary")
    phase_b_context_sha = unsigned.get("phase_b_context_sha256")
    if phase_b_context_sha is not None:
        _required_sha_v1(phase_b_context_sha, label="Q4 Phase-B context")
    if unsigned["phase_b_records"] and phase_b_context_sha is None:
        _fail("Q4 checkpoint contains Phase B progress without its frozen context")
    if phase_b_context_sha is not None and unsigned.get("boundary_record") is None:
        _fail("Q4 checkpoint freezes Phase B context before the grant boundary")
    if unsigned.get("phase_a_finalization") is None and unsigned.get("boundary_record") is not None:
        _fail("Q4 checkpoint contains a grant boundary before Phase A finalization")
    if (
        unsigned.get("phase_a_finalization") is not None
        and len(unsigned["phase_a_records"]) != CELL_COUNT
    ):
        _fail("Q4 checkpoint finalizes Phase A before all 560 records")
    if (
        unsigned.get("pair_sizing_finalization") is not None
        and (
            unsigned.get("boundary_record") is None
            or len(unsigned["phase_b_records"]) != CELL_COUNT
        )
    ):
        _fail("Q4 checkpoint finalizes sizing before all 560 Phase B records")
    return unsigned


def _commit_checkpoint(root: Path, path: Path, state: Mapping[str, Any]) -> None:
    _atomic_checkpoint(root, path, _checkpoint_value(state))


def _load_record_descriptor(
    *,
    root: Path,
    descriptor: Any,
    expected_path: Path,
    label: str,
    hash_field: str,
) -> dict[str, Any]:
    normalized = _revalidate_descriptor(root, descriptor, label=label)
    if normalized["path"] != expected_path.relative_to(root).as_posix():
        _fail(f"{label} path/order drifted")
    return _validate_sealed(
        _load_canonical_json(expected_path, label=label),
        field=hash_field,
        label=label,
    )


def _validate_artifact_inventory(
    *,
    root: Path,
    directory: Path,
    expected: Any,
    record_filename: str,
    label: str,
) -> list[dict[str, Any]]:
    if type(expected) is not list:
        _fail(f"{label} registered artifact inventory is invalid")
    normalized = [
        _descriptor(item, label=f"{label} artifact[{position}]")
        for position, item in enumerate(expected)
    ]
    if normalized != sorted(normalized, key=lambda item: item["path"]):
        _fail(f"{label} registered artifact inventory is not sorted")
    observed = _inventory_tree(
        root, directory, label=label, exclude=(record_filename,)
    )
    if observed != normalized:
        _fail(f"{label} physical artifact closure drifted")
    return normalized


def _validate_phase_a_record(
    *,
    root: Path,
    cell: BackendQ4CellV1,
    cell_dir: Path,
    source_descriptor: Mapping[str, Any],
    record_descriptor: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    record_path = cell_dir / PHASE_A_RECORD_FILENAME
    if record_descriptor is None:
        descriptor = _descriptor_for(root, record_path, label="Phase A record")
        record = _validate_sealed(
            _load_canonical_json(record_path, label="Phase A record"),
            field="record_sha256",
            label="Phase A record",
        )
    else:
        descriptor = _revalidate_descriptor(
            root, record_descriptor, label="Phase A record"
        )
        if descriptor["path"] != record_path.relative_to(root).as_posix():
            _fail("Phase A checkpoint record prefix/order drifted")
        record = _validate_sealed(
            _load_canonical_json(record_path, label="Phase A record"),
            field="record_sha256",
            label="Phase A record",
        )
    required = {
        "schema_version",
        "artifact_kind",
        "status",
        "qualification_scope",
        "coordinate",
        "frozen_run",
        "source_registry",
        "qualification_input",
        "launch_fence",
        "raw_evidence",
        "qualification_request",
        "validation_record_candidate",
        "pin_recheck_before",
        "pin_recheck_after",
        "artifacts",
        "record_sha256",
    }
    if (
        set(record) != required
        or record.get("schema_version") != 1
        or record.get("artifact_kind") != PHASE_A_RECORD_KIND
        or record.get("status") != "completed_native_qualification"
        or record.get("qualification_scope")
        != "backend_native_runtime_q4_pre_grant_only"
        or record.get("coordinate") != cell.coordinate
        or record.get("frozen_run") != cell.frozen_run
        or record.get("source_registry") != dict(source_descriptor)
        or record.get("pin_recheck_before") != record.get("pin_recheck_after")
    ):
        _fail(f"Phase A record {cell.cell_index} semantic fields drifted")
    for field, filename in (
        ("qualification_input", PHASE_A_INPUT_FILENAME),
        ("launch_fence", PHASE_A_FENCE_FILENAME),
        ("qualification_request", PHASE_A_REQUEST_FILENAME),
        ("validation_record_candidate", PHASE_A_VALIDATION_RECORD_FILENAME),
    ):
        item = _revalidate_descriptor(
            root, record[field], label=f"Phase A {field}"
        )
        if item["path"] != (cell_dir / filename).relative_to(root).as_posix():
            _fail(f"Phase A {field} path drifted")
    raw = _revalidate_descriptor(root, record["raw_evidence"], label="raw evidence")
    try:
        (root / raw["path"]).relative_to(cell_dir)
    except ValueError:
        _fail("Phase A raw evidence escaped its cell namespace")
    _validate_artifact_inventory(
        root=root,
        directory=cell_dir,
        expected=record["artifacts"],
        record_filename=PHASE_A_RECORD_FILENAME,
        label=f"Phase A cell {cell.cell_index}",
    )
    return descriptor, record


def _validate_phase_a_record_live_semantics_v4(
    *,
    root: Path,
    cell: BackendQ4CellV1,
    source_descriptor: Mapping[str, Any],
    runtime_registry: Mapping[str, Any],
    record: Mapping[str, Any],
) -> None:
    """Cold-crossbind one checkpointed native result to its Q4 authorities."""

    input_descriptor = _revalidate_descriptor(
        root, record.get("qualification_input"), label="Phase A qualification input"
    )
    input_value = _validate_sealed(
        _load_canonical_json(
            root / input_descriptor["path"], label="Phase A qualification input"
        ),
        field="input_sha256",
        label="Phase A qualification input",
    )
    if (
        set(input_value)
        != {
            "schema_version",
            "artifact_kind",
            "status",
            "qualification_scope",
            "coordinate",
            "frozen_run",
            "source_registry",
            "materialized_runtime_input",
            "input_sha256",
        }
        or input_value.get("schema_version") != 1
        or input_value.get("artifact_kind") != PHASE_A_INPUT_KIND
        or input_value.get("status") != "materialized_non_authorizing_q4_input"
        or input_value.get("qualification_scope")
        != "backend_native_runtime_q4_pre_grant_only"
        or input_value.get("coordinate") != cell.coordinate
        or input_value.get("frozen_run") != cell.frozen_run
        or input_value.get("source_registry") != dict(source_descriptor)
        or type(input_value.get("materialized_runtime_input")) is not dict
    ):
        _fail(f"Phase A input {cell.cell_index} semantic crossbinding drifted")

    fence_descriptor = _revalidate_descriptor(
        root, record.get("launch_fence"), label="Phase A launch fence"
    )
    fence_value = _validate_sealed(
        _load_canonical_json(
            root / fence_descriptor["path"], label="Phase A launch fence"
        ),
        field="fence_sha256",
        label="Phase A launch fence",
    )
    if (
        set(fence_value)
        != {
            "schema_version",
            "artifact_kind",
            "status",
            "coordinate",
            "frozen_run",
            "source_registry",
            "qualification_input",
            "fence_sha256",
        }
        or fence_value.get("schema_version") != 1
        or fence_value.get("artifact_kind") != PHASE_A_FENCE_KIND
        or fence_value.get("status") != "native_qualification_launch_fenced"
        or fence_value.get("coordinate") != cell.coordinate
        or fence_value.get("frozen_run") != cell.frozen_run
        or fence_value.get("source_registry") != dict(source_descriptor)
        or fence_value.get("qualification_input") != input_descriptor
    ):
        _fail(f"Phase A fence {cell.cell_index} semantic crossbinding drifted")

    request_descriptor = _revalidate_descriptor(
        root,
        record.get("qualification_request"),
        label=f"Q4 native validation request candidate[{cell.cell_index}]",
    )
    request_candidate = _load_canonical_json(
        root / request_descriptor["path"],
        label=f"Q4 native validation request candidate[{cell.cell_index}]",
    )
    record_descriptor = _revalidate_descriptor(
        root,
        record.get("validation_record_candidate"),
        label=f"Q4 native validation record candidate[{cell.cell_index}]",
    )
    record_candidate = _load_canonical_json(
        root / record_descriptor["path"],
        label=f"Q4 native validation record candidate[{cell.cell_index}]",
    )
    expected_request_fields = {
        "schema_version",
        "artifact_kind",
        "status",
        "authorization_eligible",
        "execution_authorized",
        "coordinate",
        "run_id",
        "runtime_contract_sha256",
        "raw_evidence_ref",
    }
    expected_record_fields = {
        *expected_request_fields,
        "validation_records_authenticated",
        "replay_result",
    }
    expected_run_id = f"qualification-q4-v4-{cell.arm_id}"
    if (
        set(request_candidate) != expected_request_fields
        or request_candidate.get("schema_version") != 4
        or request_candidate.get("artifact_kind")
        != NATIVE_VALIDATION_REQUEST_CANDIDATE_KIND
        or request_candidate.get("status") != "pending_hermetic_evidence_replay"
        or request_candidate.get("authorization_eligible") is not False
        or request_candidate.get("execution_authorized") is not False
        or request_candidate.get("coordinate") != cell.coordinate
        or request_candidate.get("run_id") != expected_run_id
        or set(record_candidate) != expected_record_fields
        or record_candidate.get("schema_version") != 4
        or record_candidate.get("artifact_kind")
        != NATIVE_VALIDATION_RECORD_CANDIDATE_KIND
        or record_candidate.get("status") != "pending_hermetic_evidence_replay"
        or record_candidate.get("authorization_eligible") is not False
        or record_candidate.get("execution_authorized") is not False
        or record_candidate.get("validation_records_authenticated") is not False
        or record_candidate.get("replay_result") is not None
        or record_candidate.get("coordinate") != cell.coordinate
        or record_candidate.get("run_id") != expected_run_id
        or record_candidate.get("runtime_contract_sha256")
        != request_candidate.get("runtime_contract_sha256")
        or record_candidate.get("raw_evidence_ref")
        != request_candidate.get("raw_evidence_ref")
    ):
        _fail(f"Q4 native validation candidate[{cell.cell_index}] drifted")
    raw_ref = request_candidate["raw_evidence_ref"]
    if (
        type(raw_ref) is not dict
        or set(raw_ref) != {"descriptor", "content_identity_sha256"}
        or raw_ref.get("descriptor") != record.get("raw_evidence")
    ):
        _fail(f"Q4 raw evidence reference[{cell.cell_index}] drifted")
    raw_descriptor = _revalidate_descriptor(
        root,
        raw_ref["descriptor"],
        label=f"Q4 raw evidence manifest[{cell.cell_index}]",
    )
    raw_manifest = _load_canonical_json(
        root / raw_descriptor["path"],
        label=f"Q4 raw evidence manifest[{cell.cell_index}]",
    )
    try:
        from publication_q4_evidence_validator_v4 import (
            validate_publication_q4_raw_evidence_manifest_v4,
        )

        authority, dataset = select_publication_q4_runtime_material_v4(
            runtime_registry,
            coordinate=cell.coordinate,
        )
        checked_manifest = validate_publication_q4_raw_evidence_manifest_v4(
            raw_manifest,
            expected_coordinate=cell.coordinate,
            expected_run_id=expected_run_id,
            expected_runtime_authority_sha256=authority[
                "runtime_authority_sha256"
            ],
            expected_runtime_contract_sha256=request_candidate[
                "runtime_contract_sha256"
            ],
        )
    except Exception as error:
        _fail(
            f"Q4 raw evidence manifest[{cell.cell_index}] rejected: {error}"
        )
    if (
        checked_manifest.get("raw_evidence_manifest_sha256")
        != raw_ref.get("content_identity_sha256")
    ):
        _fail(f"Q4 raw evidence manifest[{cell.cell_index}] semantic ref drifted")
    runtime_descriptor = _revalidate_descriptor(
        root,
        checked_manifest["runtime_contract"],
        label=f"Q4 public runtime contract[{cell.cell_index}]",
    )
    runtime_contract = _load_canonical_json(
        root / runtime_descriptor["path"],
        label=f"Q4 public runtime contract[{cell.cell_index}]",
    )
    try:
        checked_contract = validate_publication_runtime_contract_v4(
            runtime_contract,
            coordinate=cell.coordinate,
            authority_snapshot=authority,
            dataset_binding=dataset,
            run_id=expected_run_id,
            duration_s=cell.measurement_s,
        )
    except PublicationQ4RuntimeContractV4Error as error:
        _fail(f"Q4 public runtime contract[{cell.cell_index}] rejected: {error}")
    if (
        checked_contract["contract_sha256"]
        != request_candidate["runtime_contract_sha256"]
    ):
        _fail(f"Q4 public runtime contract[{cell.cell_index}] candidate pin drifted")


def _invoke_before_fence(
    callback: Callable[..., dict[str, Any]], *, label: str, kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        result = callback(**kwargs)
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"{label} failed before durable fence: {error}", exit_code=EXIT_TRANSIENT)
    if type(result) is not dict:
        _fail(f"{label} returned a non-object")
    return result


def _invoke_after_fence(
    callback: Callable[..., dict[str, Any]], *, label: str, kwargs: dict[str, Any]
) -> dict[str, Any]:
    try:
        result = callback(**kwargs)
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        _fail(
            f"{label} failed after its durable launch fence; retry is forbidden: {error}"
        )
    if type(result) is not dict:
        _fail(f"{label} returned a non-object after its durable launch fence")
    return result


def _run_phase_a_cell(
    *,
    root: Path,
    work_dir: Path,
    cell: BackendQ4CellV1,
    source_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    cell_dir = _ensure_directory(
        root, work_dir / "phase-a" / "cells" / cell.arm_id,
        label=f"Phase A cell {cell.cell_index}",
    )
    record_path = cell_dir / PHASE_A_RECORD_FILENAME
    fence_path = cell_dir / PHASE_A_FENCE_FILENAME
    if record_path.exists():
        _fail(
            f"Phase A cell {cell.cell_index} has an uncheckpointed record; "
            "child-created recovery records are not parent-authorized"
        )
    if fence_path.exists():
        _fail(
            f"Phase A cell {cell.cell_index} has a durable fence without a committed "
            "record; native qualification retry is forbidden"
        )

    pin_before = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_a_before_cell",
        cell=cell,
    )
    materialized = _invoke_before_fence(
        dependencies.materialize_qualification_input,
        label=f"Phase A input materializer for cell {cell.cell_index}",
        kwargs={
            "project_root": root,
            "source_registry": copy.deepcopy(dict(source_registry)),
            "source_registry_path": source_path,
            "cell": cell,
            "output_dir": cell_dir,
        },
    )
    _reject_circular_claims(materialized, location="Phase A materialized input")
    input_value = _seal(
        {
            "schema_version": 1,
            "artifact_kind": PHASE_A_INPUT_KIND,
            "status": "materialized_non_authorizing_q4_input",
            "qualification_scope": "backend_native_runtime_q4_pre_grant_only",
            "coordinate": cell.coordinate,
            "frozen_run": cell.frozen_run,
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "materialized_runtime_input": copy.deepcopy(materialized),
        },
        "input_sha256",
    )
    input_descriptor = _write_immutable_json(
        root,
        cell_dir / PHASE_A_INPUT_FILENAME,
        input_value,
        label=f"Phase A input {cell.cell_index}",
    )
    fence_value = _seal(
        {
            "schema_version": 1,
            "artifact_kind": PHASE_A_FENCE_KIND,
            "status": "native_qualification_launch_fenced",
            "coordinate": cell.coordinate,
            "frozen_run": cell.frozen_run,
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "qualification_input": input_descriptor,
        },
        "fence_sha256",
    )
    fence_descriptor = _write_immutable_json(
        root,
        fence_path,
        fence_value,
        label=f"Phase A launch fence {cell.cell_index}",
        allow_identical=False,
    )
    result = _invoke_after_fence(
        dependencies.run_native_qualification,
        label=f"native qualification cell {cell.cell_index}",
        kwargs={
            "project_root": root,
            "source_registry": copy.deepcopy(dict(source_registry)),
            "cell": cell,
            "qualification_input": copy.deepcopy(input_value),
            "qualification_input_path": root / input_descriptor["path"],
            "output_dir": cell_dir,
        },
    )
    if set(result) != {
        "exit_code",
        "raw_evidence_path",
        "qualification_request",
        "validation_record_candidate",
    }:
        _fail(f"native qualification cell {cell.cell_index} result fields drifted")
    exit_code = result.get("exit_code")
    if exit_code not in {EXIT_OK, EXIT_TRANSIENT, EXIT_PERMANENT}:
        _fail(f"native qualification cell {cell.cell_index} returned invalid exit code")
    if exit_code != EXIT_OK:
        _fail(
            f"native qualification cell {cell.cell_index} failed after durable fence; "
            "retry is forbidden"
        )
    raw_path = _under_root(
        root, result["raw_evidence_path"], label="Phase A raw evidence", must_exist=True
    )
    try:
        raw_path.relative_to(cell_dir)
    except ValueError:
        _fail("native qualification raw evidence escaped its cell namespace")
    raw_descriptor = _descriptor_for(root, raw_path, label="Phase A raw evidence")
    if (
        type(result["qualification_request"]) is not dict
        or type(result["validation_record_candidate"]) is not dict
    ):
        _fail("native qualification request/record candidates must be JSON objects")
    request_descriptor = _write_immutable_json(
        root,
        cell_dir / PHASE_A_REQUEST_FILENAME,
        result["qualification_request"],
        label=f"Phase A qualification request {cell.cell_index}",
        allow_identical=False,
    )
    validation_record_descriptor = _write_immutable_json(
        root,
        cell_dir / PHASE_A_VALIDATION_RECORD_FILENAME,
        result["validation_record_candidate"],
        label=f"Phase A validation record {cell.cell_index}",
        allow_identical=False,
    )
    pin_after = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_a_after_cell",
        cell=cell,
    )
    if pin_after != pin_before:
        _fail(f"Phase A cell {cell.cell_index} pins changed across execution")
    for expected, label in (
        (input_descriptor, "Phase A qualification input"),
        (fence_descriptor, "Phase A launch fence"),
        (raw_descriptor, "Phase A raw evidence"),
        (request_descriptor, "Phase A qualification request"),
        (validation_record_descriptor, "Phase A validation record"),
    ):
        _revalidate_descriptor(root, expected, label=label)
    artifacts = _inventory_tree(
        root, cell_dir, label=f"Phase A cell {cell.cell_index}",
        exclude=(PHASE_A_RECORD_FILENAME,),
    )
    record_value = _seal(
        {
            "schema_version": 1,
            "artifact_kind": PHASE_A_RECORD_KIND,
            "status": "completed_native_qualification",
            "qualification_scope": "backend_native_runtime_q4_pre_grant_only",
            "coordinate": cell.coordinate,
            "frozen_run": cell.frozen_run,
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "qualification_input": input_descriptor,
            "launch_fence": fence_descriptor,
            "raw_evidence": raw_descriptor,
            "qualification_request": request_descriptor,
            "validation_record_candidate": validation_record_descriptor,
            "pin_recheck_before": pin_before,
            "pin_recheck_after": pin_after,
            "artifacts": artifacts,
        },
        "record_sha256",
    )
    record_descriptor = _write_immutable_json(
        root,
        record_path,
        record_value,
        label=f"Phase A record {cell.cell_index}",
        allow_identical=False,
    )
    return record_descriptor, record_value


def _validate_q4_binding(value: Any, *, expected_index: Mapping[str, Any]) -> dict[str, Any]:
    if (
        type(value) is not dict
        or value.get("schema_version") != 3
        or value.get("artifact_kind")
        != "vast_full_publication_backend_runtime_qualification_binding_v3"
        or value.get("authorization_eligible") is not True
        or value.get("validation_trust_status")
        != "authenticated_persisted_physical_q4_v4"
        or value.get("semantic_crossbinding_complete") is not True
        or value.get("authorization_blockers") != []
        or value.get("binding_index") != dict(expected_index)
    ):
        _fail("persisted Q4 binding did not pass the schema-v3 physical trust boundary")
    return copy.deepcopy(value)


def _load_phase_a_records(
    *,
    root: Path,
    work_dir: Path,
    cells: Sequence[BackendQ4CellV1],
    record_descriptors: Sequence[Any],
    source_descriptor: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if len(record_descriptors) != CELL_COUNT:
        _fail("Phase A finalization requires exactly 560 committed records")
    records: list[dict[str, Any]] = []
    for cell, descriptor in zip(cells, record_descriptors, strict=True):
        cell_dir = work_dir / "phase-a" / "cells" / cell.arm_id
        _, record = _validate_phase_a_record(
            root=root,
            cell=cell,
            cell_dir=cell_dir,
            source_descriptor=source_descriptor,
            record_descriptor=descriptor,
        )
        records.append(record)
    return records


def _load_graph_record(
    *, root: Path, graph_record_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    descriptor = _descriptor_for(root, graph_record_path, label="Phase A graph record")
    record = _validate_sealed(
        _load_canonical_json(graph_record_path, label="Phase A graph record"),
        field="graph_record_sha256",
        label="Phase A graph record",
    )
    if (
        set(record)
        != {
            "schema_version",
            "artifact_kind",
            "status",
            "catalog",
            "phase_a_record_set_sha256",
            "graph_record_sha256",
        }
        or record.get("schema_version") != 1
        or record.get("artifact_kind") != "vast_backend_q4_phase_a_graph_record_v1"
        or record.get("status") != "qualification_graph_committed"
    ):
        _fail("Phase A graph record fields drifted")
    _revalidate_descriptor(root, record["catalog"], label="Q4 catalog")
    return descriptor, record


def _promotion_descriptors_from_disk(
    *, root: Path, output_dir: Path
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]] | None:
    index_path = output_dir / Q4_BINDING_INDEX_FILENAME
    if not index_path.exists():
        return None
    index = _descriptor_for(root, index_path, label="Q4 binding index")
    receipts: dict[str, dict[str, Any]] = {}
    for system in SYSTEMS:
        receipt_path = (
            output_dir
            / f"checkpoint_{system}_backend_runtime_qualification_v4_receipt.json"
        )
        if not receipt_path.exists():
            _fail("Q4 binding index exists without all four committed receipts")
        receipts[system] = _descriptor_for(
            root, receipt_path, label=f"Q4 {system} receipt"
        )
    return index, receipts


def _phase_a_finalization(
    *,
    root: Path,
    work_dir: Path,
    cells: Sequence[BackendQ4CellV1],
    record_descriptors: Sequence[Any],
    source_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    phase_dir = _ensure_directory(root, work_dir / "phase-a", label="Phase A root")
    graph_dir = _ensure_directory(root, phase_dir / "graph", label="Q4 graph output")
    persisted_dir = _ensure_directory(
        root, phase_dir / "persisted-q4", label="persisted Q4 output"
    )
    final_path = phase_dir / PHASE_A_FINAL_FILENAME
    records = _load_phase_a_records(
        root=root,
        work_dir=work_dir,
        cells=cells,
        record_descriptors=record_descriptors,
        source_descriptor=source_descriptor,
    )
    record_set_sha = _canonical_sha([item["record_sha256"] for item in records])

    if final_path.exists():
        final_descriptor = _descriptor_for(
            root, final_path, label="Phase A finalization"
        )
        final = _validate_sealed(
            _load_canonical_json(final_path, label="Phase A finalization"),
            field="finalization_sha256",
            label="Phase A finalization",
        )
        if (
            final.get("artifact_kind") != PHASE_A_FINAL_KIND
            or final.get("phase_a_record_set_sha256") != record_set_sha
            or final.get("source_registry") != dict(source_descriptor)
            or final.get("pin_recheck_before") != final.get("pin_recheck_after")
        ):
            _fail("Phase A finalization differs from the committed 560 records")
        index = _revalidate_descriptor(
            root, final.get("binding_index"), label="Q4 binding index"
        )
        _revalidate_descriptor(root, final.get("catalog"), label="Q4 catalog")
        receipts = final.get("receipts")
        if type(receipts) is not dict or set(receipts) != set(SYSTEMS):
            _fail("Phase A finalization receipt set drifted")
        for system in SYSTEMS:
            _revalidate_descriptor(root, receipts[system], label=f"Q4 {system} receipt")
        q4 = _validate_q4_binding(
            _guarded_cold_load_v1(
                root=root,
                paths=[
                    root / index["path"],
                    *(root / receipts[system]["path"] for system in SYSTEMS),
                ],
                label="committed Q4 qualification reload",
                callback=lambda: dependencies.load_qualification(
                    project_root=root, binding_index_path=index["path"]
                ),
            ),
            expected_index=index,
        )
        if final.get("q4_binding_sha256") != _canonical_sha(q4):
            _fail("Phase A loaded Q4 binding changed after finalization")
        return final_descriptor, final, q4

    pin_before = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_a_before_finalization",
        cell=None,
    )
    graph_record_path = graph_dir / PHASE_A_GRAPH_RECORD_FILENAME
    if graph_record_path.exists():
        _, graph_record = _load_graph_record(
            root=root, graph_record_path=graph_record_path
        )
        if graph_record.get("phase_a_record_set_sha256") != record_set_sha:
            _fail("Phase A staged graph belongs to a different 560-record set")
        catalog_descriptor = _revalidate_descriptor(
            root, graph_record["catalog"], label="Q4 catalog"
        )
    else:
        graph_result = _invoke_before_fence(
            dependencies.finalize_qualification_graph,
            label="Q4 qualification graph finalizer",
            kwargs={
                "project_root": root,
                "source_registry": copy.deepcopy(dict(source_registry)),
                "phase_a_records": copy.deepcopy(records),
                "graph_dir": graph_dir,
            },
        )
        if set(graph_result) != {"catalog_path"}:
            _fail("Q4 qualification graph finalizer result fields drifted")
        catalog_path = _under_root(
            root,
            graph_result["catalog_path"],
            label="Q4 catalog",
            must_exist=True,
        )
        try:
            catalog_path.relative_to(graph_dir)
        except ValueError:
            _fail("Q4 catalog escaped its graph namespace")
        catalog_descriptor = _descriptor_for(root, catalog_path, label="Q4 catalog")
        graph_record = _seal(
            {
                "schema_version": 1,
                "artifact_kind": "vast_backend_q4_phase_a_graph_record_v1",
                "status": "qualification_graph_committed",
                "catalog": catalog_descriptor,
                "phase_a_record_set_sha256": record_set_sha,
            },
            "graph_record_sha256",
        )
        _write_immutable_json(
            root,
            graph_record_path,
            graph_record,
            label="Phase A graph record",
            allow_identical=False,
        )

    existing_promotion = _promotion_descriptors_from_disk(
        root=root, output_dir=persisted_dir
    )
    if existing_promotion is None:
        try:
            promoted = dependencies.promote_qualification(
                project_root=root,
                catalog_path=catalog_descriptor["path"],
                output_dir=persisted_dir,
            )
        except Exception as error:
            _fail(f"physical Q4 persistence rejected the graph: {error}")
        if (
            type(promoted) is not dict
            or "binding_index_descriptor" not in promoted
            or "receipt_descriptors" not in promoted
        ):
            _fail("physical Q4 persistence result fields drifted")
        index = _revalidate_descriptor(
            root, promoted["binding_index_descriptor"], label="Q4 binding index"
        )
        receipts = promoted["receipt_descriptors"]
        if type(receipts) is not dict or set(receipts) != set(SYSTEMS):
            _fail("physical Q4 persistence did not return exactly four receipts")
        normalized_receipts = {
            system: _revalidate_descriptor(
                root, receipts[system], label=f"Q4 {system} receipt"
            )
            for system in SYSTEMS
        }
    else:
        index, normalized_receipts = existing_promotion
    if index["path"] != (persisted_dir / Q4_BINDING_INDEX_FILENAME).relative_to(root).as_posix():
        _fail("physical Q4 persistence binding index namespace drifted")
    q4_paths = [
        root / index["path"],
        *(root / normalized_receipts[system]["path"] for system in SYSTEMS),
    ]
    q4 = _validate_q4_binding(
        _guarded_cold_load_v1(
            root=root,
            paths=q4_paths,
            label="persisted Q4 qualification load",
            callback=lambda: dependencies.load_qualification(
                project_root=root, binding_index_path=index["path"]
            ),
        ),
        expected_index=index,
    )
    pin_after = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_a_after_finalization",
        cell=None,
    )
    if pin_after != pin_before:
        _fail("source/socket/image pins changed while finalizing Phase A")
    _revalidate_descriptor(root, catalog_descriptor, label="Q4 catalog")
    _revalidate_descriptor(root, index, label="Q4 binding index")
    for system in SYSTEMS:
        _revalidate_descriptor(
            root, normalized_receipts[system], label=f"Q4 {system} receipt"
        )
    q4_reloaded = _validate_q4_binding(
        _guarded_cold_load_v1(
            root=root,
            paths=q4_paths,
            label="persisted Q4 qualification cold reload",
            callback=lambda: dependencies.load_qualification(
                project_root=root, binding_index_path=index["path"]
            ),
        ),
        expected_index=index,
    )
    if q4_reloaded != q4:
        _fail("persisted Q4 binding changed immediately before finalization commit")
    final = _seal(
        {
            "schema_version": 1,
            "artifact_kind": PHASE_A_FINAL_KIND,
            "status": "persisted_authenticated_physical_q4",
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "phase_a_record_set_sha256": record_set_sha,
            "catalog": catalog_descriptor,
            "binding_index": index,
            "receipts": normalized_receipts,
            "q4_binding_sha256": _canonical_sha(q4),
            "pin_recheck_before": pin_before,
            "pin_recheck_after": pin_after,
        },
        "finalization_sha256",
    )
    final_descriptor = _write_immutable_json(
        root,
        final_path,
        final,
        label="Phase A finalization",
        allow_identical=False,
    )
    return final_descriptor, final, q4


def _identity_inputs(value: Any) -> dict[str, Any]:
    fields = {
        "analytics_model_parity",
        "analytics_execution_layer",
        "policy_qualification",
        "resource_qualification",
    }
    if type(value) is not dict or set(value) != fields:
        _fail("identity_inputs must contain exactly the four non-backend bindings")
    _reject_circular_claims(value, location="identity_inputs")
    return copy.deepcopy(value)


def _validate_identity_binding(value: Any) -> dict[str, Any]:
    if (
        type(value) is not dict
        or value.get("schema_version") != 2
        or value.get("artifact_kind")
        != "vast_full_publication_identity_artifact_binding"
        or not _SHA_RE.fullmatch(str(value.get("binding_sha256", "")))
    ):
        _fail("identity loader did not return an accepted schema-v2 binding")
    return copy.deepcopy(value)


def _load_identity_binding_guarded_v1(
    *,
    root: Path,
    manifest_path: Path | str,
    dependencies: BackendQ4TwoPhaseDependenciesV1,
    label: str,
) -> dict[str, Any]:
    return _validate_identity_binding(
        _guarded_cold_load_v1(
            root=root,
            paths=[root / manifest_path if not Path(manifest_path).is_absolute() else Path(manifest_path)],
            label=label,
            callback=lambda: dependencies.load_identity(
                project_root=root,
                manifest_path=manifest_path,
            ),
        )
    )


def _identity_q4_crossbind(
    identity: Mapping[str, Any], q4_binding: Mapping[str, Any]
) -> None:
    bindings = identity.get("bindings")
    if (
        type(bindings) is not dict
        or bindings.get("backend_runtime_qualification") != dict(q4_binding)
    ):
        _fail("schema-v2 identity does not physically register this persisted Q4 binding")


def _validate_grant(
    value: Any, *, identity_binding_sha256: str
) -> dict[str, Any]:
    if (
        type(value) is not dict
        or value.get("schema_version") != 3
        or value.get("artifact_kind") != GRANT_V3_KIND
        or value.get("identity_artifact_binding_sha256")
        != identity_binding_sha256
        or not _SHA_RE.fullmatch(str(value.get("grant_sha256", "")))
    ):
        _fail("identity-derived backend runtime grant v3 is invalid")
    return copy.deepcopy(value)


def _identity_grant_boundary(
    *,
    root: Path,
    work_dir: Path,
    identity_manifest_output: Path | str,
    identity_inputs: Mapping[str, Any],
    phase_a_descriptor: Mapping[str, Any],
    phase_a_final: Mapping[str, Any],
    q4_binding: Mapping[str, Any],
    source_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    boundary_dir = _ensure_directory(root, work_dir / "boundary", label="Q4 boundary")
    record_path = boundary_dir / BOUNDARY_RECORD_FILENAME
    identity_path = _under_root(
        root, identity_manifest_output, label="identity manifest output"
    )
    _ensure_directory(root, identity_path.parent, label="identity manifest parent")
    inputs = _identity_inputs(identity_inputs)

    if record_path.exists():
        record_descriptor = _descriptor_for(
            root, record_path, label="identity/grant boundary record"
        )
        record = _validate_sealed(
            _load_canonical_json(record_path, label="identity/grant boundary record"),
            field="boundary_sha256",
            label="identity/grant boundary record",
        )
        required = {
            "schema_version",
            "artifact_kind",
            "status",
            "source_registry",
            "phase_a_finalization",
            "phase_a_finalization_sha256",
            "q4_binding_sha256",
            "identity_manifest",
            "identity_binding_sha256",
            "backend_runtime_grant",
            "backend_runtime_grant_sha256",
            "pin_recheck_before",
            "pin_recheck_after",
            "boundary_sha256",
        }
        if (
            set(record) != required
            or record.get("schema_version") != 1
            or record.get("artifact_kind") != BOUNDARY_RECORD_KIND
            or record.get("status") != "accepted_identity_derived_backend_grant"
            or record.get("source_registry") != dict(source_descriptor)
            or record.get("phase_a_finalization") != dict(phase_a_descriptor)
            or record.get("phase_a_finalization_sha256")
            != phase_a_final.get("finalization_sha256")
            or record.get("q4_binding_sha256") != _canonical_sha(q4_binding)
            or record.get("pin_recheck_before") != record.get("pin_recheck_after")
        ):
            _fail("identity/grant boundary record causality drifted")
        manifest_descriptor = _revalidate_descriptor(
            root, record["identity_manifest"], label="identity manifest"
        )
        grant_descriptor = _revalidate_descriptor(
            root, record["backend_runtime_grant"], label="backend runtime grant"
        )
        identity = _load_identity_binding_guarded_v1(
            root=root,
            manifest_path=manifest_descriptor["path"],
            dependencies=dependencies,
            label="committed identity boundary reload",
        )
        _identity_q4_crossbind(identity, q4_binding)
        if identity.get("binding_sha256") != record["identity_binding_sha256"]:
            _fail("loaded identity differs from the committed grant boundary")
        grant = _validate_grant(
            dependencies.validate_backend_grant(
                _load_canonical_json(
                    root / grant_descriptor["path"], label="backend runtime grant"
                )
            ),
            identity_binding_sha256=identity["binding_sha256"],
        )
        if grant.get("grant_sha256") != record["backend_runtime_grant_sha256"]:
            _fail("loaded grant differs from the committed identity boundary")
        return record_descriptor, record, identity, grant

    pin_before = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="boundary_before_identity",
        cell=None,
    )
    if identity_path.exists():
        identity = _load_identity_binding_guarded_v1(
            root=root,
            manifest_path=identity_path,
            dependencies=dependencies,
            label="preexisting identity manifest load",
        )
        _identity_q4_crossbind(identity, q4_binding)
    else:
        backend_input = {
            "binding_index": copy.deepcopy(phase_a_final["binding_index"]),
            "receipts": copy.deepcopy(phase_a_final["receipts"]),
        }
        try:
            built = dependencies.build_identity_manifest(
                project_root=root,
                output_path=identity_path,
                **inputs,
                backend_runtime_qualification=backend_input,
            )
        except Exception as error:
            _fail(f"full-publication identity construction rejected Q4: {error}")
        if type(built) is not dict or set(built) != {"manifest_path", "binding"}:
            _fail("identity builder result fields drifted")
        built_path = _under_root(
            root, built["manifest_path"], label="built identity manifest", must_exist=True
        )
        if built_path != identity_path:
            _fail("identity builder committed outside the requested manifest path")
        identity = _validate_identity_binding(built["binding"])
        loaded = _load_identity_binding_guarded_v1(
            root=root,
            manifest_path=identity_path,
            dependencies=dependencies,
            label="new identity manifest cold reload",
        )
        if loaded != identity:
            _fail("identity changed between candidate build and physical reload")
        _identity_q4_crossbind(identity, q4_binding)
    manifest_descriptor = _descriptor_for(root, identity_path, label="identity manifest")

    # This is the only grant construction call: persisted Q4 -> physical
    # identity -> schema-v3 grant.  No catalog/pre-identity shortcut exists.
    try:
        grant_candidate = dependencies.build_backend_grant(copy.deepcopy(identity))
        grant = _validate_grant(
            dependencies.validate_backend_grant(grant_candidate),
            identity_binding_sha256=identity["binding_sha256"],
        )
    except BackendQ4TwoPhaseExecutorV1Error:
        raise
    except Exception as error:
        _fail(f"identity-derived backend runtime grant was rejected: {error}")
    grant_descriptor = _write_immutable_json(
        root,
        boundary_dir / GRANT_FILENAME,
        grant,
        label="backend runtime grant",
        allow_identical=True,
    )
    pin_after = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="boundary_after_grant",
        cell=None,
    )
    if pin_after != pin_before:
        _fail("source/socket/image pins changed across identity/grant boundary")
    _revalidate_descriptor(root, manifest_descriptor, label="identity manifest")
    _revalidate_descriptor(root, grant_descriptor, label="backend runtime grant")
    reloaded_identity = _load_identity_binding_guarded_v1(
        root=root,
        manifest_path=manifest_descriptor["path"],
        dependencies=dependencies,
        label="identity pre-boundary cold reload",
    )
    _identity_q4_crossbind(reloaded_identity, q4_binding)
    if reloaded_identity != identity:
        _fail("identity changed immediately before boundary commit")
    reloaded_grant = _validate_grant(
        dependencies.validate_backend_grant(
            _load_canonical_json(
                root / grant_descriptor["path"], label="backend runtime grant"
            )
        ),
        identity_binding_sha256=identity["binding_sha256"],
    )
    if reloaded_grant != grant:
        _fail("backend grant changed immediately before boundary commit")
    record = _seal(
        {
            "schema_version": 1,
            "artifact_kind": BOUNDARY_RECORD_KIND,
            "status": "accepted_identity_derived_backend_grant",
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "phase_a_finalization": copy.deepcopy(dict(phase_a_descriptor)),
            "phase_a_finalization_sha256": phase_a_final["finalization_sha256"],
            "q4_binding_sha256": _canonical_sha(q4_binding),
            "identity_manifest": manifest_descriptor,
            "identity_binding_sha256": identity["binding_sha256"],
            "backend_runtime_grant": grant_descriptor,
            "backend_runtime_grant_sha256": grant["grant_sha256"],
            "pin_recheck_before": pin_before,
            "pin_recheck_after": pin_after,
        },
        "boundary_sha256",
    )
    record_descriptor = _write_immutable_json(
        root,
        record_path,
        record,
        label="identity/grant boundary record",
        allow_identical=False,
    )
    return record_descriptor, record, identity, grant


def _validate_phase_b_record(
    *,
    root: Path,
    work_dir: Path,
    cell: BackendQ4CellV1,
    source_descriptor: Mapping[str, Any],
    boundary_record: Mapping[str, Any],
    record_descriptor: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    transaction_dir = work_dir / "phase-b" / "transactions" / cell.arm_id
    record_path = work_dir / "phase-b" / "records" / f"{cell.arm_id}.json"
    if record_descriptor is None:
        descriptor = _descriptor_for(root, record_path, label="Phase B record")
    else:
        descriptor = _revalidate_descriptor(
            root, record_descriptor, label="Phase B record"
        )
        if descriptor["path"] != record_path.relative_to(root).as_posix():
            _fail("Phase B checkpoint record prefix/order drifted")
    record = _validate_sealed(
        _load_canonical_json(record_path, label="Phase B record"),
        field="record_sha256",
        label="Phase B record",
    )
    required = {
        "schema_version",
        "artifact_kind",
        "status",
        "execution_scope",
        "coordinate",
        "frozen_run",
        "source_registry",
        "boundary_sha256",
        "transaction_directory",
        "arm_contract",
        "launch_fence",
        "output_receipt",
        "output_receipt_authority",
        "pin_recheck_before",
        "pin_recheck_after",
        "transaction_artifacts",
        "record_sha256",
    }
    if (
        set(record) != required
        or record.get("schema_version") != 1
        or record.get("artifact_kind") != PHASE_B_RECORD_KIND
        or record.get("status") != "completed_post_grant_production_arm"
        or record.get("execution_scope") != "full_publication_measurement_v3"
        or record.get("coordinate") != cell.coordinate
        or record.get("frozen_run") != cell.frozen_run
        or record.get("source_registry") != dict(source_descriptor)
        or record.get("boundary_sha256") != boundary_record.get("boundary_sha256")
        or record.get("transaction_directory")
        != transaction_dir.relative_to(root).as_posix()
        or record.get("pin_recheck_before") != record.get("pin_recheck_after")
    ):
        _fail(f"Phase B record {cell.cell_index} semantic/causal fields drifted")
    for field, filename in (
        ("arm_contract", ARM_CONTRACT_FILENAME),
        ("launch_fence", LAUNCH_FENCE_FILENAME),
        ("output_receipt", OUTPUT_RECEIPT_FILENAME),
    ):
        item = _revalidate_descriptor(root, record[field], label=f"Phase B {field}")
        if item["path"] != (transaction_dir / filename).relative_to(root).as_posix():
            _fail(f"Phase B {field} path drifted")
    authority = _revalidate_descriptor(
        root, record["output_receipt_authority"], label="production authority"
    )
    authority_path = root / authority["path"]
    try:
        authority_path.relative_to(transaction_dir)
    except ValueError:
        pass
    else:
        _fail("production authority was persisted inside its transaction namespace")
    _validate_artifact_inventory(
        root=root,
        directory=transaction_dir,
        expected=record["transaction_artifacts"],
        record_filename="__record_is_external__",
        label=f"Phase B transaction {cell.cell_index}",
    )
    return descriptor, record


def _load_phase_b_persisted_authority(
    *,
    root: Path,
    transaction_dir: Path,
    descriptor: Mapping[str, Any],
    require_parent_envelope: bool,
) -> dict[str, Any]:
    authority_descriptor = _revalidate_descriptor(
        root, descriptor, label="persisted production authority"
    )
    value = _load_canonical_json(
        root / authority_descriptor["path"],
        label="persisted production authority",
    )
    if value.get("artifact_kind") == PRODUCTION_AUTHORITY_ENVELOPE_KIND:
        if (
            set(value)
            != {
                "schema_version",
                "artifact_kind",
                "transaction_directory",
                "authority",
                "authority_sha256",
                "envelope_sha256",
            }
            or value.get("schema_version") != 1
            or value.get("transaction_directory")
            != transaction_dir.relative_to(root).as_posix()
            or type(value.get("authority")) is not dict
            or value.get("authority_sha256")
            != value["authority"].get("authority_sha256")
            or value.get("envelope_sha256")
            != _canonical_sha(
                {
                    key: copy.deepcopy(item)
                    for key, item in value.items()
                    if key != "envelope_sha256"
                }
            )
        ):
            _fail("persisted production authority envelope drifted")
        return copy.deepcopy(value["authority"])
    if require_parent_envelope:
        _fail("production recovery authority lacks its parent-owned envelope")
    if type(value) is not dict:
        _fail("persisted production authority is not an object")
    return copy.deepcopy(value)


def _validate_phase_b_record_live_recovery(
    *,
    root: Path,
    work_dir: Path,
    cell: BackendQ4CellV1,
    source_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
    q4_binding: Mapping[str, Any],
    identity_binding: Mapping[str, Any],
    backend_runtime_grant: Mapping[str, Any],
    boundary_record: Mapping[str, Any],
    production_context: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
    record_descriptor: Any | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Re-admit one record only through live pins and the parent transaction WAL."""

    descriptor, record = _validate_phase_b_record(
        root=root,
        work_dir=work_dir,
        cell=cell,
        source_descriptor=source_descriptor,
        boundary_record=boundary_record,
        record_descriptor=record_descriptor,
    )
    pin_before = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_b_record_recovery_before",
        cell=cell,
    )
    if (
        pin_before != record["pin_recheck_before"]
        or pin_before != record["pin_recheck_after"]
    ):
        _fail(f"Phase B record {cell.cell_index} live source pins drifted")
    transaction_dir = work_dir / "phase-b" / "transactions" / cell.arm_id
    production_default = (
        dependencies.execute_production_arm
        is run_backend_q4_production_v3_adapter_v1
    )
    persisted_authority = _load_phase_b_persisted_authority(
        root=root,
        transaction_dir=transaction_dir,
        descriptor=record["output_receipt_authority"],
        require_parent_envelope=production_default,
    )
    if production_default:
        try:
            recovered = run_backend_q4_production_v3_adapter_v1(
                project_root=root,
                source_registry=copy.deepcopy(dict(source_registry)),
                source_registry_path=source_path,
                cell=cell,
                transaction_dir=transaction_dir,
                q4_binding=copy.deepcopy(dict(q4_binding)),
                identity_binding=copy.deepcopy(dict(identity_binding)),
                backend_runtime_grant=copy.deepcopy(dict(backend_runtime_grant)),
                production_context=copy.deepcopy(dict(production_context)),
                _allow_spawn=False,
                _allow_finalize=True,
                _require_committed_parent_pin=True,
            )
        except Exception as error:
            _fail(
                f"Phase B record {cell.cell_index} parent-WAL validation failed: "
                f"{error}"
            )
        if (
            set(recovered) != {"exit_code", "authority"}
            or recovered.get("exit_code") != EXIT_OK
            or recovered.get("authority") != persisted_authority
        ):
            _fail(
                f"Phase B record {cell.cell_index} parent-WAL authority drifted"
            )
    try:
        persisted_descriptor = dependencies.persist_production_authority(
            project_root=root,
            transaction_dir=transaction_dir,
            authority=copy.deepcopy(persisted_authority),
            output_path=root / record["output_receipt_authority"]["path"],
        )
    except Exception as error:
        _fail(
            f"Phase B record {cell.cell_index} parent authority validation "
            f"failed: {error}"
        )
    persisted_descriptor = _revalidate_descriptor(
        root,
        persisted_descriptor,
        label="idempotently persisted production authority",
    )
    if persisted_descriptor != record["output_receipt_authority"]:
        _fail(
            f"Phase B record {cell.cell_index} parent authority descriptor drifted"
        )
    pin_after = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_b_record_recovery_after",
        cell=cell,
    )
    if pin_after != pin_before:
        _fail(f"Phase B record {cell.cell_index} pins changed during recovery")
    observed_descriptor, observed_record = _validate_phase_b_record(
        root=root,
        work_dir=work_dir,
        cell=cell,
        source_descriptor=source_descriptor,
        boundary_record=boundary_record,
        record_descriptor=descriptor,
    )
    if observed_descriptor != descriptor or observed_record != record:
        _fail(f"Phase B record {cell.cell_index} changed during live recovery")
    return descriptor, record


def _run_phase_b_cell(
    *,
    root: Path,
    work_dir: Path,
    cell: BackendQ4CellV1,
    source_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
    q4_binding: Mapping[str, Any],
    identity_binding: Mapping[str, Any],
    backend_runtime_grant: Mapping[str, Any],
    boundary_record: Mapping[str, Any],
    production_context: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    transactions_dir = _ensure_directory(
        root,
        work_dir / "phase-b" / "transactions",
        label="Phase B transactions",
    )
    transaction_dir = transactions_dir / cell.arm_id
    if transaction_dir.exists():
        _ensure_directory(
            root, transaction_dir, label=f"Phase B transaction {cell.cell_index}"
        )
    records_dir = _ensure_directory(
        root, work_dir / "phase-b" / "records", label="Phase B records"
    )
    authorities_dir = _ensure_directory(
        root, work_dir / "phase-b" / "authorities", label="Phase B authorities"
    )
    record_path = records_dir / f"{cell.arm_id}.json"
    fence_path = transaction_dir / LAUNCH_FENCE_FILENAME
    receipt_path = transaction_dir / OUTPUT_RECEIPT_FILENAME
    if record_path.exists():
        if (
            dependencies.execute_production_arm
            is not run_backend_q4_production_v3_adapter_v1
        ):
            _fail(
                f"Phase B cell {cell.cell_index} has an uncheckpointed record "
                "without the production parent WAL"
            )
        return _validate_phase_b_record_live_recovery(
            root=root,
            work_dir=work_dir,
            cell=cell,
            source_path=source_path,
            source_registry=source_registry,
            source_descriptor=source_descriptor,
            q4_binding=q4_binding,
            identity_binding=identity_binding,
            backend_runtime_grant=backend_runtime_grant,
            boundary_record=boundary_record,
            production_context=production_context,
            dependencies=dependencies,
        )
    if receipt_path.exists() and not fence_path.exists():
        _fail(
            f"Phase B cell {cell.cell_index} has an output receipt without its "
            "durable production fence"
        )
    pin_before = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_b_before_cell",
        cell=cell,
    )
    try:
        execute_arguments = {
            "project_root": root,
            "source_registry": copy.deepcopy(dict(source_registry)),
            "source_registry_path": source_path,
            "cell": cell,
            "transaction_dir": transaction_dir,
            "q4_binding": copy.deepcopy(dict(q4_binding)),
            "identity_binding": copy.deepcopy(dict(identity_binding)),
            "backend_runtime_grant": copy.deepcopy(
                dict(backend_runtime_grant)
            ),
            "production_context": copy.deepcopy(dict(production_context)),
        }
        if (
            dependencies.execute_production_arm
            is run_backend_q4_production_v3_adapter_v1
        ):
            result = dependencies.execute_production_arm(
                **execute_arguments,
                _require_committed_parent_pin=True,
            )
        else:
            result = dependencies.execute_production_arm(**execute_arguments)
    except BaseException as error:
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        if (
            isinstance(error, BackendQ4TwoPhaseExecutorV1Error)
            and error.exit_code == EXIT_TRANSIENT
        ):
            raise
        if fence_path.exists():
            _fail(
                f"production cell {cell.cell_index} failed after its durable fence; "
                f"retry is forbidden: {error}"
            )
        if isinstance(error, BackendQ4TwoPhaseExecutorV1Error):
            raise
        _fail(
            f"production cell {cell.cell_index} failed before durable fence: {error}",
            exit_code=EXIT_TRANSIENT,
        )
    if type(result) is not dict or "exit_code" not in result:
        if fence_path.exists():
            _fail(
                f"production cell {cell.cell_index} returned an invalid result after "
                "durable fence; retry is forbidden"
            )
        _fail(f"production cell {cell.cell_index} returned an invalid result")
    exit_code = result.get("exit_code")
    if exit_code not in {EXIT_OK, EXIT_TRANSIENT, EXIT_PERMANENT}:
        _fail(f"production cell {cell.cell_index} returned an invalid exit code")
    if exit_code != EXIT_OK:
        if fence_path.exists():
            _fail(
                f"production cell {cell.cell_index} failed after durable fence; "
                "retry is forbidden"
            )
        _fail(
            f"production cell {cell.cell_index} failed before durable fence",
            exit_code=exit_code,
        )
    if set(result) != {"exit_code", "authority"}:
        _fail(f"production cell {cell.cell_index} success result fields drifted")
    for filename in (ARM_CONTRACT_FILENAME, LAUNCH_FENCE_FILENAME, OUTPUT_RECEIPT_FILENAME):
        if not (transaction_dir / filename).exists():
            _fail(
                f"production cell {cell.cell_index} did not commit required {filename}"
            )
    arm_descriptor = _descriptor_for(
        root, transaction_dir / ARM_CONTRACT_FILENAME, label="production arm contract"
    )
    fence_descriptor = _descriptor_for(
        root, fence_path, label="production launch fence"
    )
    receipt_descriptor = _descriptor_for(
        root,
        receipt_path,
        label="production output receipt",
    )
    pin_after = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="phase_b_after_cell",
        cell=cell,
    )
    if pin_after != pin_before:
        _fail(f"Phase B cell {cell.cell_index} pins changed across execution")
    authority_path = authorities_dir / f"{cell.arm_id}.json"
    try:
        authority_descriptor = dependencies.persist_production_authority(
            project_root=root,
            transaction_dir=transaction_dir,
            authority=copy.deepcopy(result["authority"]),
            output_path=authority_path,
        )
    except Exception as error:
        _fail(
            f"production cell {cell.cell_index} authority persistence failed after "
            f"durable fence; retry is permitted only through the exact "
            f"receipt/parent-pin WAL: {error}",
            exit_code=EXIT_TRANSIENT,
        )
    authority_descriptor = _revalidate_descriptor(
        root, authority_descriptor, label="persisted production authority"
    )
    if authority_descriptor["path"] != authority_path.relative_to(root).as_posix():
        _fail("production authority persistence escaped its external namespace")
    transaction_artifacts = _inventory_tree(
        root, transaction_dir, label=f"Phase B transaction {cell.cell_index}"
    )
    for expected, label in (
        (arm_descriptor, "production arm contract"),
        (fence_descriptor, "production launch fence"),
        (receipt_descriptor, "production output receipt"),
        (authority_descriptor, "persisted production authority"),
    ):
        _revalidate_descriptor(root, expected, label=label)
    record = _seal(
        {
            "schema_version": 1,
            "artifact_kind": PHASE_B_RECORD_KIND,
            "status": "completed_post_grant_production_arm",
            "execution_scope": "full_publication_measurement_v3",
            "coordinate": cell.coordinate,
            "frozen_run": cell.frozen_run,
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "boundary_sha256": boundary_record["boundary_sha256"],
            "transaction_directory": transaction_dir.relative_to(root).as_posix(),
            "arm_contract": arm_descriptor,
            "launch_fence": fence_descriptor,
            "output_receipt": receipt_descriptor,
            "output_receipt_authority": authority_descriptor,
            "pin_recheck_before": pin_before,
            "pin_recheck_after": pin_after,
            "transaction_artifacts": transaction_artifacts,
        },
        "record_sha256",
    )
    record_descriptor = _write_immutable_json(
        root,
        record_path,
        record,
        label=f"Phase B record {cell.cell_index}",
        allow_identical=False,
    )
    return record_descriptor, record


def _load_phase_b_records(
    *,
    root: Path,
    work_dir: Path,
    cells: Sequence[BackendQ4CellV1],
    record_descriptors: Sequence[Any],
    source_descriptor: Mapping[str, Any],
    boundary_record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    if len(record_descriptors) != CELL_COUNT:
        _fail("pair sizing requires exactly 560 committed Phase B records")
    records: list[dict[str, Any]] = []
    for cell, descriptor in zip(cells, record_descriptors, strict=True):
        _, record = _validate_phase_b_record(
            root=root,
            work_dir=work_dir,
            cell=cell,
            source_descriptor=source_descriptor,
            boundary_record=boundary_record,
            record_descriptor=descriptor,
        )
        records.append(record)
    return records


def _pair_payloads(
    records: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    by_coordinate = {
        (
            record["coordinate"]["system"],
            record["coordinate"]["codec"],
            record["coordinate"]["topology_kind"],
            record["coordinate"]["policy"],
            record["coordinate"]["deadline_ms"],
        ): record
        for record in records
    }
    if len(by_coordinate) != CELL_COUNT:
        _fail("Phase B record coordinates are not the exact unique 560-cell matrix")
    pairs: list[dict[str, Any]] = []
    for system in SYSTEMS:
        for codec in CODECS:
            for policy in POLICIES:
                for deadline in DEADLINES_MS:
                    arms: dict[str, Any] = {}
                    for topology in TOPOLOGIES:
                        key = (system, codec, topology, policy, deadline)
                        if key not in by_coordinate:
                            _fail("Phase B topology pair coverage is incomplete")
                        record = by_coordinate[key]
                        arms[topology] = {
                            "output_receipt_authority": copy.deepcopy(
                                record["output_receipt_authority"]
                            ),
                            "arm_payload": copy.deepcopy(record["arm_contract"]),
                        }
                    pairs.append(
                        {
                            "coordinate": {
                                "system": system,
                                "codec": codec,
                                "policy": policy,
                                "deadline_ms": deadline,
                            },
                            "arms": arms,
                        }
                    )
    if len(pairs) != PAIR_COUNT:
        _fail("internal Phase B pairing did not yield exactly 280 coordinates")
    return pairs


def _pair_sizing_finalization(
    *,
    root: Path,
    work_dir: Path,
    cells: Sequence[BackendQ4CellV1],
    phase_b_descriptors: Sequence[Any],
    source_path: Path,
    source_registry: Mapping[str, Any],
    source_descriptor: Mapping[str, Any],
    boundary_record: Mapping[str, Any],
    q4_binding_index: Mapping[str, Any],
    dependencies: BackendQ4TwoPhaseDependenciesV1,
) -> tuple[dict[str, Any], dict[str, Any]]:
    sizing_dir = _ensure_directory(
        root, work_dir / "phase-b" / "pair-sizing", label="pair sizing output"
    )
    materialized_dir = _ensure_directory(
        root, sizing_dir / "materialized", label="materialized pair sizing"
    )
    final_path = sizing_dir / SIZING_FINAL_FILENAME
    records = _load_phase_b_records(
        root=root,
        work_dir=work_dir,
        cells=cells,
        record_descriptors=phase_b_descriptors,
        source_descriptor=source_descriptor,
        boundary_record=boundary_record,
    )
    record_set_sha = _canonical_sha([item["record_sha256"] for item in records])
    if final_path.exists():
        descriptor = _descriptor_for(root, final_path, label="pair sizing finalization")
        final = _validate_sealed(
            _load_canonical_json(final_path, label="pair sizing finalization"),
            field="finalization_sha256",
            label="pair sizing finalization",
        )
        if (
            final.get("artifact_kind") != SIZING_FINAL_KIND
            or final.get("phase_b_record_set_sha256") != record_set_sha
            or final.get("boundary_sha256") != boundary_record.get("boundary_sha256")
            or final.get("pair_count") != PAIR_COUNT
            or final.get("topology_arm_count") != CELL_COUNT
            or final.get("pin_recheck_before") != final.get("pin_recheck_after")
        ):
            _fail("pair sizing finalization causality/coverage drifted")
        _revalidate_descriptor(root, final.get("input"), label="pair sizing input")
        _revalidate_descriptor(root, final.get("index"), label="pair sizing index")
        return descriptor, final

    pin_before = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="pair_sizing_before",
        cell=None,
    )
    pairs = _pair_payloads(records)
    try:
        input_value = dependencies.build_pair_sizing_input(
            q4_binding_index=copy.deepcopy(dict(q4_binding_index)),
            pairs=copy.deepcopy(pairs),
        )
    except Exception as error:
        _fail(f"280-pair sizing input construction failed: {error}")
    if type(input_value) is not dict:
        _fail("pair sizing input builder returned a non-object")
    input_descriptor = _write_immutable_json(
        root,
        sizing_dir / SIZING_INPUT_FILENAME,
        input_value,
        label="pair sizing input",
        allow_identical=True,
    )
    committed_index = materialized_dir / SIZING_INDEX_FILENAME
    if committed_index.exists():
        index_descriptor = _descriptor_for(
            root, committed_index, label="pair sizing index"
        )
        try:
            recovered_rows = _guarded_cold_load_v1(
                root=root,
                paths=[root / index_descriptor["path"]],
                label="committed pair sizing index reload",
                callback=lambda: dependencies.load_pair_sizing(
                    project_root=root,
                    index_path=index_descriptor["path"],
                ),
            )
        except Exception as error:
            _fail(f"committed pair sizing index recovery failed: {error}")
        if type(recovered_rows) is not list or len(recovered_rows) != PAIR_COUNT:
            _fail("committed pair sizing index did not reload exactly 280 rows")
    else:
        try:
            materialized = dependencies.materialize_pair_sizing(
                project_root=root,
                input_path=input_descriptor["path"],
                output_dir=materialized_dir,
            )
        except Exception as error:
            _fail(f"physical 280-pair sizing materialization failed: {error}")
        if (
            type(materialized) is not dict
            or "index" not in materialized
            or "sizing_rows" not in materialized
            or type(materialized["sizing_rows"]) is not list
            or len(materialized["sizing_rows"]) != PAIR_COUNT
        ):
            _fail("pair sizing materializer did not return exactly 280 rows")
        index_descriptor = _revalidate_descriptor(
            root, materialized["index"], label="pair sizing index"
        )
    if index_descriptor["path"] != committed_index.relative_to(root).as_posix():
        _fail("pair sizing index namespace drifted")
    pin_after = _pin_recheck(
        root=root,
        source_path=source_path,
        expected_registry=source_registry,
        expected_descriptor=source_descriptor,
        dependencies=dependencies,
        phase="pair_sizing_after",
        cell=None,
    )
    if pin_after != pin_before:
        _fail("source/socket/image pins changed during pair sizing")
    _revalidate_descriptor(root, input_descriptor, label="pair sizing input")
    _revalidate_descriptor(root, index_descriptor, label="pair sizing index")
    final = _seal(
        {
            "schema_version": 1,
            "artifact_kind": SIZING_FINAL_KIND,
            "status": "committed_post_q4_pair_sizing_index",
            "source_registry": copy.deepcopy(dict(source_descriptor)),
            "boundary_sha256": boundary_record["boundary_sha256"],
            "phase_b_record_set_sha256": record_set_sha,
            "q4_binding_index": copy.deepcopy(dict(q4_binding_index)),
            "input": input_descriptor,
            "index": index_descriptor,
            "pair_count": PAIR_COUNT,
            "topology_arm_count": CELL_COUNT,
            "pin_recheck_before": pin_before,
            "pin_recheck_after": pin_after,
        },
        "finalization_sha256",
    )
    descriptor = _write_immutable_json(
        root,
        final_path,
        final,
        label="pair sizing finalization",
        allow_identical=False,
    )
    return descriptor, final


def execute_backend_q4_two_phase_v1(
    *,
    project_root: Path | str,
    source_registry_path: Path | str,
    work_dir: Path | str,
    identity_manifest_output: Path | str,
    production_context: Mapping[str, Any],
    identity_inputs: Mapping[str, Any] | None = None,
    dependencies: BackendQ4TwoPhaseDependenciesV1 | None = None,
    through_phase: str = "phase_b",
    _fault_hook: Callable[[str, BackendQ4CellV1 | None], None] | None = None,
) -> dict[str, Any]:
    """Run or conservatively resume the exact physical Q4 two-phase workflow."""

    if through_phase not in {"phase_a", "boundary", "phase_b"}:
        _fail("through_phase must be phase_a, boundary, or phase_b")
    if type(production_context) is not dict:
        _fail("production_context must be an object")
    if any(
        key in production_context
        for key in (
            "backend_runtime_grant",
            "backend_runtime_grant_sha256",
            "q4_binding",
        )
    ):
        _fail("production_context may not self-supply Q4 or backend grant authority")
    deps = dependencies or default_backend_q4_two_phase_dependencies_v1()
    if not isinstance(deps, BackendQ4TwoPhaseDependenciesV1):
        _fail("dependencies must be BackendQ4TwoPhaseDependenciesV1")
    root = _physical_root(project_root)
    if _ACTIVE_PHYSICAL_CUSTODY.get() is None:
        with _held_physical_root_v1(root):
            return execute_backend_q4_two_phase_v1(
                project_root=root,
                source_registry_path=source_registry_path,
                work_dir=work_dir,
                identity_manifest_output=identity_manifest_output,
                production_context=production_context,
                identity_inputs=identity_inputs,
                dependencies=deps,
                through_phase=through_phase,
                _fault_hook=_fault_hook,
            )
    _active_physical_custody_v1(root)
    work = _ensure_directory(root, work_dir, label="Q4 work directory")
    source_path, source_registry, source_descriptor = _validate_source_registry(
        root, source_registry_path
    )
    resolved_identity_inputs = (
        _default_identity_inputs_from_source_registry_v1(
            root=root,
            source_path=source_path,
            expected_registry=source_registry,
        )
        if identity_inputs is None
        else copy.deepcopy(dict(identity_inputs))
    )
    checkpoint_path = work / CHECKPOINT_FILENAME
    cells = backend_q4_cells_v1()

    with _exclusive_lock(work):
        state = _load_or_create_checkpoint(
            root=root,
            checkpoint_path=checkpoint_path,
            source_registry=source_registry,
            source_descriptor=source_descriptor,
        )
        _pin_recheck(
            root=root,
            source_path=source_path,
            expected_registry=source_registry,
            expected_descriptor=source_descriptor,
            dependencies=deps,
            phase="executor_resume_preflight",
            cell=None,
        )

        # Validate the entire parent-checkpointed prefix before doing new work.
        # Child-created sibling records are never a recovery authority.
        phase_a_runtime_registry: dict[str, Any] | None = None
        if (
            state["phase_a_records"]
            and deps.materialize_qualification_input
            is materialize_backend_q4_runtime_input_v4_adapter
            and deps.run_native_qualification
            is run_backend_q4_native_runtime_v4_adapter
            and deps.finalize_qualification_graph
            is finalize_backend_q4_qualification_graph_v4_adapter
        ):
            phase_a_runtime_registry = (
                _load_publication_q4_runtime_candidate_registry_v4(
                    project_root=root,
                    source_registry=source_registry,
                )
            )
        for position, descriptor in enumerate(state["phase_a_records"]):
            cell = cells[position]
            _phase_a_descriptor, phase_a_record = _validate_phase_a_record(
                root=root,
                cell=cell,
                cell_dir=work / "phase-a" / "cells" / cell.arm_id,
                source_descriptor=source_descriptor,
                record_descriptor=descriptor,
            )
            live_pin = _pin_recheck(
                root=root,
                source_path=source_path,
                expected_registry=source_registry,
                expected_descriptor=source_descriptor,
                dependencies=deps,
                phase="phase_a_checkpoint_recovery",
                cell=cell,
            )
            if (
                live_pin != phase_a_record["pin_recheck_before"]
                or live_pin != phase_a_record["pin_recheck_after"]
            ):
                _fail(
                    f"Phase A record {cell.cell_index} live source pins drifted"
                )
            if phase_a_runtime_registry is not None:
                _validate_phase_a_record_live_semantics_v4(
                    root=root,
                    cell=cell,
                    source_descriptor=source_descriptor,
                    runtime_registry=phase_a_runtime_registry,
                    record=phase_a_record,
                )
        for cell in cells[len(state["phase_a_records"]) :]:
            descriptor, _ = _run_phase_a_cell(
                root=root,
                work_dir=work,
                cell=cell,
                source_path=source_path,
                source_registry=source_registry,
                source_descriptor=source_descriptor,
                dependencies=deps,
            )
            state["phase_a_records"].append(descriptor)
            _commit_checkpoint(root, checkpoint_path, state)
            if _fault_hook is not None:
                _fault_hook("phase_a_after_record", cell)

        phase_a_descriptor, phase_a_final, q4_binding = _phase_a_finalization(
            root=root,
            work_dir=work,
            cells=cells,
            record_descriptors=state["phase_a_records"],
            source_path=source_path,
            source_registry=source_registry,
            source_descriptor=source_descriptor,
            dependencies=deps,
        )
        if state["phase_a_finalization"] is None:
            state["phase_a_finalization"] = phase_a_descriptor
            if _fault_hook is not None:
                _fault_hook("phase_a_after_finalization", None)
            _commit_checkpoint(root, checkpoint_path, state)
        elif state["phase_a_finalization"] != phase_a_descriptor:
            _fail("checkpoint Phase A finalization descriptor drifted")

        if through_phase == "phase_a":
            return {
                "status": "completed_phase_a",
                "phase_a_completed_cells": CELL_COUNT,
                "phase_b_completed_cells": 0,
                "pair_count": 0,
                "checkpoint": _descriptor_for(
                    root, checkpoint_path, label="Q4 checkpoint"
                ),
                "q4_binding_index": copy.deepcopy(phase_a_final["binding_index"]),
            }

        boundary_descriptor, boundary_record, identity, grant = (
            _identity_grant_boundary(
                root=root,
                work_dir=work,
                identity_manifest_output=identity_manifest_output,
                identity_inputs=resolved_identity_inputs,
                phase_a_descriptor=phase_a_descriptor,
                phase_a_final=phase_a_final,
                q4_binding=q4_binding,
                source_path=source_path,
                source_registry=source_registry,
                source_descriptor=source_descriptor,
                dependencies=deps,
            )
        )
        if state["boundary_record"] is None:
            state["boundary_record"] = boundary_descriptor
            if _fault_hook is not None:
                _fault_hook("boundary_after_record", None)
            _commit_checkpoint(root, checkpoint_path, state)
        elif state["boundary_record"] != boundary_descriptor:
            _fail("checkpoint identity/grant boundary descriptor drifted")

        if through_phase == "boundary":
            return {
                "status": "completed_boundary",
                "phase_a_completed_cells": CELL_COUNT,
                "phase_b_completed_cells": 0,
                "pair_count": 0,
                "checkpoint": _descriptor_for(
                    root, checkpoint_path, label="Q4 checkpoint"
                ),
                "q4_binding_index": copy.deepcopy(phase_a_final["binding_index"]),
                "identity_manifest": copy.deepcopy(boundary_record["identity_manifest"]),
                "backend_runtime_grant": copy.deepcopy(
                    boundary_record["backend_runtime_grant"]
                ),
            }

        effective_production_context = copy.deepcopy(dict(production_context))
        if deps.execute_production_arm is run_backend_q4_production_v3_adapter_v1:
            effective_production_context = (
                _prepare_backend_q4_production_context_v1(
                    project_root=root,
                    source_registry_path=source_path,
                    source_registry=source_registry,
                    production_context=production_context,
                )
            )
        phase_b_context_sha = _canonical_sha(
            {
                "schema_version": 1,
                "source_registry_sha256": source_registry["registry_sha256"],
                "boundary_sha256": boundary_record["boundary_sha256"],
                "production_context": effective_production_context,
            }
        )
        if state["phase_b_context_sha256"] is None:
            state["phase_b_context_sha256"] = phase_b_context_sha
            _commit_checkpoint(root, checkpoint_path, state)
        elif state["phase_b_context_sha256"] != phase_b_context_sha:
            _fail("checkpoint Phase-B production context/pins drifted on resume")

        for position, descriptor in enumerate(state["phase_b_records"]):
            _validate_phase_b_record_live_recovery(
                root=root,
                work_dir=work,
                cell=cells[position],
                source_path=source_path,
                source_registry=source_registry,
                source_descriptor=source_descriptor,
                q4_binding=q4_binding,
                identity_binding=identity,
                backend_runtime_grant=grant,
                boundary_record=boundary_record,
                production_context=effective_production_context,
                dependencies=deps,
                record_descriptor=descriptor,
            )
        for cell in cells[len(state["phase_b_records"]) :]:
            descriptor, _ = _run_phase_b_cell(
                root=root,
                work_dir=work,
                cell=cell,
                source_path=source_path,
                source_registry=source_registry,
                source_descriptor=source_descriptor,
                q4_binding=q4_binding,
                identity_binding=identity,
                backend_runtime_grant=grant,
                boundary_record=boundary_record,
                production_context=effective_production_context,
                dependencies=deps,
            )
            state["phase_b_records"].append(descriptor)
            _commit_checkpoint(root, checkpoint_path, state)
            if _fault_hook is not None:
                _fault_hook("phase_b_after_record", cell)

        sizing_descriptor, sizing_final = _pair_sizing_finalization(
            root=root,
            work_dir=work,
            cells=cells,
            phase_b_descriptors=state["phase_b_records"],
            source_path=source_path,
            source_registry=source_registry,
            source_descriptor=source_descriptor,
            boundary_record=boundary_record,
            q4_binding_index=phase_a_final["binding_index"],
            dependencies=deps,
        )
        if state["pair_sizing_finalization"] is None:
            state["pair_sizing_finalization"] = sizing_descriptor
            if _fault_hook is not None:
                _fault_hook("pair_sizing_after_finalization", None)
            _commit_checkpoint(root, checkpoint_path, state)
        elif state["pair_sizing_finalization"] != sizing_descriptor:
            _fail("checkpoint pair sizing finalization descriptor drifted")

        return {
            "status": "completed",
            "phase_a_completed_cells": len(state["phase_a_records"]),
            "phase_b_completed_cells": len(state["phase_b_records"]),
            "pair_count": sizing_final["pair_count"],
            "checkpoint": _descriptor_for(root, checkpoint_path, label="Q4 checkpoint"),
            "q4_binding_index": copy.deepcopy(phase_a_final["binding_index"]),
            "identity_manifest": copy.deepcopy(boundary_record["identity_manifest"]),
            "backend_runtime_grant": copy.deepcopy(
                boundary_record["backend_runtime_grant"]
            ),
            "pair_sizing_index": copy.deepcopy(sizing_final["index"]),
        }


def _parse_cli_v1(argv: Sequence[str]) -> dict[str, str]:
    if type(argv) not in {list, tuple} or len(argv) != len(_CLI_OPTIONS) * 2:
        _fail("Q4 executor CLI argv arity drifted")
    values: dict[str, str] = {}
    for position, option in enumerate(_CLI_OPTIONS):
        observed = argv[position * 2]
        value = argv[position * 2 + 1]
        if observed != option:
            _fail(f"Q4 executor CLI option[{position}] drifted")
        if type(value) is not str or not value:
            _fail(f"Q4 executor CLI value[{position}] is empty")
        values[option] = value
    if values["--through-phase"] not in {"phase_a", "boundary", "phase_b"}:
        _fail("Q4 executor CLI through-phase is invalid")
    for option in _CLI_OPTIONS:
        if option.endswith("sha256"):
            _required_sha_v1(values[option], label=f"Q4 executor CLI {option}")
    return values


def run_cli(
    argv: Sequence[str],
    *,
    dependencies: BackendQ4TwoPhaseDependenciesV1 | None = None,
) -> int:
    try:
        arguments = _parse_cli_v1(argv)
        result = execute_backend_q4_two_phase_v1(
            project_root=arguments["--project-root"],
            source_registry_path=arguments["--source-registry"],
            work_dir=arguments["--work-dir"],
            identity_manifest_output=arguments["--identity-manifest-output"],
            production_context={
                "phase1_receipt_path": arguments["--phase1-receipt"],
                "phase1_receipt_file_sha256": arguments[
                    "--phase1-receipt-file-sha256"
                ],
                "phase1_receipt_sha256": arguments["--phase1-receipt-sha256"],
                "phase2_receipt_path": arguments["--phase2-receipt"],
                "phase2_receipt_file_sha256": arguments[
                    "--phase2-receipt-file-sha256"
                ],
                "phase2_receipt_sha256": arguments["--phase2-receipt-sha256"],
                "source_materialization_result_path": arguments[
                    "--source-materialization-result"
                ],
                "source_materialization_result_file_sha256": arguments[
                    "--source-materialization-result-file-sha256"
                ],
                "source_materialization_result_sha256": arguments[
                    "--source-materialization-result-sha256"
                ],
            },
            dependencies=dependencies,
            through_phase=arguments["--through-phase"],
        )
        payload = _canonical_bytes(result)
        if hasattr(sys.stdout, "buffer"):
            sys.stdout.buffer.write(payload)
            sys.stdout.buffer.flush()
        else:
            sys.stdout.write(payload.decode("ascii"))
            sys.stdout.flush()
        return EXIT_OK
    except BackendQ4TwoPhaseExecutorV1Error as error:
        sys.stderr.write(f"backend Q4 two-phase executor rejected: {error.blocker}\n")
        sys.stderr.flush()
        return error.exit_code
    except Exception as error:
        sys.stderr.write(
            "backend Q4 two-phase executor rejected: "
            f"{type(error).__name__}: {error}\n"
        )
        sys.stderr.flush()
        return EXIT_PERMANENT


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(list(sys.argv[1:] if argv is None else argv))


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ARM_CONTRACT_FILENAME",
    "BackendQ4CellV1",
    "BackendQ4NativeQualificationAdapterV1",
    "BackendQ4ProductionArmAdapterV1",
    "BackendQ4TwoPhaseDependenciesV1",
    "BackendQ4TwoPhaseExecutorV1Error",
    "CODECS",
    "DEADLINES_MS",
    "LAUNCH_FENCE_FILENAME",
    "OUTPUT_RECEIPT_FILENAME",
    "POLICIES",
    "Q4_BINDING_INDEX_FILENAME",
    "SYSTEMS",
    "TOPOLOGIES",
    "backend_q4_cells_v1",
    "default_backend_q4_two_phase_dependencies_v1",
    "execute_backend_q4_two_phase_v1",
    "finalize_backend_q4_qualification_graph_v4_adapter",
    "load_backend_q4_production_receipt_chain_v1",
    "main",
    "materialize_backend_q4_production_v3_arm_v1",
    "materialize_backend_q4_runtime_input_v4_adapter",
    "run_cli",
    "run_backend_q4_production_v3_adapter_v1",
    "run_backend_q4_native_runtime_v4_adapter",
]
