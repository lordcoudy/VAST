from __future__ import annotations

"""Fail-closed native scheduling bridge for all checkpoint publication runtimes."""

import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import socket
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from analytics_execution_endpoint import terminal_detector_identity
from analytics_execution_worker import validate_worker_capability

from benchmark_contract import (
    POLICY_DECISION_COLUMNS,
    TELEMETRY_SCHEMA_VERSION,
    validate_frozen_policy_decisions,
    validate_frozen_policy_feedback,
    validate_policy_decisions,
)
from publication_policy_contract import (
    ANALYTICS_BRANCHES,
    POLICIES,
    POLICY_SCOPE,
    PUBLISHABLE_SYSTEMS,
    RESOURCES,
    PolicyContractError,
    PolicyEngine,
    assess_capability_manifest,
    bind_native_decision_evidence,
    select_static_hybrid_map,
    validate_decision_record,
)
from publication_policy_frozen_replay_v1 import (
    canonical_json_v1, payload_with_sha256_v1,
)
from publication_policy_projection_v1 import (
    MAX_ACCEPTANCE_AGGREGATE_BYTES_V1,
    MAX_RUNTIME_HISTORY_BYTES_V1,
    MAX_RUNTIME_HISTORY_EVENTS_V1,
    MAX_RUNTIME_HISTORY_LINE_BYTES_V1,
    RUNTIME_HISTORY_JSONL,
    project_accepted_decision_v1,
    reconstruct_original_decision_v1,
    serialize_runtime_history_v1,
    validate_published_decisions_v1,
)
from publication_operational_request_domain_v1 import (
    MAX_NATIVE_DECISIONS_V1, NATIVE_OPERATIONAL_JSONL, OperationalDomainError,
    build_native_occurrence_v1, validate_native_header_v1,
    validate_native_request_source_v1, write_native_domain_v1,
)


POLICY_RPC_SCHEMA_VERSION = 1
POLICY_RPC_FD_ENV = "VAST_CHECKPOINT_POLICY_FD"
POLICY_RPC_MAX_MESSAGE_BYTES = 64 * 1024
NATIVE_EXECUTION_BINDING_PROVENANCE = "native_scheduler_execution_binding_v1"
POLICY_DECISIONS_JSONL = "publication_policy_decisions.jsonl"
POLICY_FEEDBACK_JSONL = "publication_policy_feedback.jsonl"
POLICY_DECISIONS_CSV = "policy_decisions.csv"

_NVIDIA_CUDA_TERMINAL_BACKEND = re.compile(
    r"^analytics-execution:tensorrt_cuda;runtime=[^;\r\n]+;"
    r"native_api=[^;\r\n]+;device=NVIDIA_CUDA:[^;\r\n]+$"
)
_DROP_DETECTOR_IDENTITY = re.compile(
    r"^(?!identity;|topology_only;)[A-Za-z0-9._-]{1,80};model_sha256=[0-9a-f]{64}$"
)

_REQUEST_FIELDS = {
    "schema_version",
    "message_type",
    "run_id",
    "worker_id",
    "input_frame_key",
    "trace_id",
    "stream_id",
    "frame_id",
    "transport_pts_ns",
    "branch",
    "arrival_ms",
    "decision_time_ms",
    "feature_observed_timestamp_ms",
    "queue_depths",
}
_PATH_FIELDS = {
    "schema_version",
    "message_type",
    "run_id",
    "worker_id",
    "decision_id",
    "input_frame_key",
    "branch",
    "transport_pts_ns",
    "selected_resource",
    "implementation_id",
    "emitter_id",
    "emitter_sha256",
    "event_id",
    "timestamp_ms",
}
_TERMINAL_FIELDS = {
    "schema_version",
    "message_type",
    "run_id",
    "worker_id",
    "decision_id",
    "input_frame_key",
    "branch",
    "transport_pts_ns",
    "selected_resource",
    "terminal_status",
    "terminal_timestamp_ms",
    "actual_service_ms",
    "detector",
    "backend",
}


EXTERNAL_EXECUTION_MANIFEST_KIND = "vast_checkpoint_external_analytics_execution_manifest_v1"


def _assess_external_worker_execution_manifest(
    manifest: Mapping[str, Any],
    *,
    system: str | None,
    capability_manifest: Mapping[str, Any] | None,
    preprocessing_contract_sha256: str | None,
) -> dict[str, Any]:
    """Bind all eight real service workers to the exact policy authority."""
    blockers: list[str] = []
    ready: dict[str, set[str]] = {resource: set() for resource in RESOURCES}
    expected_fields = {
        "schema_version", "artifact_kind", "system",
        "policy_capability_manifest_sha256", "execution_config", "branches",
    }
    if set(manifest) != expected_fields or manifest.get("schema_version") != 1:
        blockers.append("external_execution_manifest_schema_mismatch")
    if system not in {"openvino_gva", "gstreamer_custom"} or manifest.get("system") != system:
        blockers.append("external_execution_manifest_system_mismatch")
    execution = manifest.get("execution_config")
    if not isinstance(execution, Mapping) or set(execution) != {"path", "size_bytes", "sha256"}:
        blockers.append("external_execution_config_descriptor_missing")
    else:
        path = execution.get("path")
        if (not isinstance(path, str) or not path or ":" in path or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
                or type(execution.get("size_bytes")) is not int or execution["size_bytes"] <= 0
                or not isinstance(execution.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", execution["sha256"]) is None):
            blockers.append("external_execution_config_descriptor_invalid")
    assessment = assess_capability_manifest(capability_manifest)
    if not assessment["passed"]:
        blockers.extend(assessment["blockers"])
    if manifest.get("policy_capability_manifest_sha256") != assessment.get("manifest_sha256"):
        blockers.append("external_execution_policy_manifest_identity_mismatch")
    if not isinstance(preprocessing_contract_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", preprocessing_contract_sha256) is None:
        blockers.append("external_execution_preprocessing_identity_missing")
    branches = manifest.get("branches")
    if not isinstance(branches, Mapping) or set(branches) != set(ANALYTICS_BRANCHES):
        blockers.append("external_execution_branch_set_mismatch")
    if not blockers:
        for branch in ANALYTICS_BRANCHES:
            resources = branches[branch]
            if not isinstance(resources, Mapping) or set(resources) != set(RESOURCES):
                blockers.append(f"external_execution:{branch}:resource_set_mismatch")
                continue
            checked: dict[str, dict[str, Any]] = {}
            for resource in RESOURCES:
                label = f"external_execution:{branch}:{resource}"
                try:
                    worker = validate_worker_capability(resources[resource])
                    binding = capability_manifest["systems"][system]["branches"][branch][resource]
                    engine = "openvino_cpu" if resource == "cpu" else "tensorrt_cuda"
                    if worker["branch"] != branch or worker["engine"] != engine:
                        raise ValueError("branch or resource identity mismatch")
                    if worker["preprocessing_contract_sha256"] != preprocessing_contract_sha256:
                        raise ValueError("preprocessing identity mismatch")
                    expected = {
                        "worker_image_digest": worker["worker_image_id"],
                        "implementation_version": "sha256:" + worker["worker_implementation_sha256"],
                        "terminal_detector": terminal_detector_identity(worker),
                        # Same attested terminal format emitted by the service;
                        # native images do not ship the SDK protocol bridge.
                        "terminal_backend": (
                            f"analytics-execution:{worker['engine']};runtime={worker['runtime_name']};"
                            f"native_api={worker['native_inference_api']};"
                            f"device={worker['device_api']}:{worker['device_id']}"
                        ),
                        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
                        "gpu_id": None if resource == "cpu" else 0,
                    }
                    if any(binding.get(key) != value for key, value in expected.items()):
                        raise ValueError("worker differs from exact policy capability binding")
                    checked[resource] = worker
                    ready[resource].add(branch)
                except (ValueError, TypeError, KeyError) as error:
                    blockers.append(f"{label}:{error}")
            if len(checked) == 2 and any(
                checked["cpu"][field] != checked["gpu"][field]
                for field in ("model_id", "source_model_sha256", "preprocessing_contract_sha256", "output_contract_sha256")
            ):
                blockers.append(f"external_execution:{branch}:cpu_gpu_model_contract_mismatch")
    passed = not blockers and all(ready[resource] == set(ANALYTICS_BRANCHES) for resource in RESOURCES)
    return {
        "schema_version": 1,
        "artifact_kind": "vast_checkpoint_gstreamer_native_policy_capability_assessment",
        "passed": passed,
        "status": "ready" if passed else "blocked",
        "cpu_ready_branches": sorted(ready["cpu"]),
        "nvidia_gpu_ready_branches": sorted(ready["gpu"]),
        "eligible_policies": list(POLICIES) if passed else [],
        "blockers": list(dict.fromkeys(blockers)),
    }


def assess_gstreamer_native_policy_execution_manifest(
    manifest: Mapping[str, Any] | None,
    *,
    system: str | None = None,
    capability_manifest: Mapping[str, Any] | None = None,
    preprocessing_contract_sha256: str | None = None,
) -> dict[str, Any]:
    """Assess real CPU/NVIDIA analytics paths; OpenVINO ``GPU`` is not CUDA."""

    if isinstance(manifest, Mapping) and manifest.get("artifact_kind") == EXTERNAL_EXECUTION_MANIFEST_KIND:
        return _assess_external_worker_execution_manifest(
            manifest, system=system, capability_manifest=capability_manifest,
            preprocessing_contract_sha256=preprocessing_contract_sha256,
        )

    blockers: list[str] = []
    cpu_ready: set[str] = set()
    gpu_ready: set[str] = set()
    if not isinstance(manifest, Mapping):
        blockers.append("checkpoint_policy_execution_manifest_missing")
        raw_branches: Mapping[str, Any] = {}
    else:
        branches_value = manifest.get("branches")
        raw_branches = branches_value if isinstance(branches_value, Mapping) else {}
        if set(raw_branches) != set(ANALYTICS_BRANCHES):
            blockers.append("checkpoint_policy_execution_manifest_branch_set_mismatch")

    def valid_sha(value: Any) -> bool:
        text = str(value)
        return len(text) == 64 and all(char in "0123456789abcdef" for char in text)

    for branch in ANALYTICS_BRANCHES:
        raw_branch = raw_branches.get(branch)
        if not isinstance(raw_branch, Mapping):
            blockers.extend(
                [
                    f"runtime_capability:{branch}:cpu_binding_missing",
                    f"runtime_capability:{branch}:nvidia_gpu_binding_missing",
                ]
            )
            continue
        resources = raw_branch.get("resources")
        if isinstance(resources, Mapping):
            cpu = resources.get("cpu")
            gpu = resources.get("gpu")
        else:
            # Schema-v2 OpenVINO manifest is a genuine CPU binding, never a GPU one.
            cpu = raw_branch
            gpu = None
        if (
            isinstance(cpu, Mapping)
            and cpu.get("factory") in {"gvadetect", "object_detect"}
            and str(cpu.get("device", "")).upper() == "CPU"
            and valid_sha(cpu.get("model_sha256"))
            and valid_sha(cpu.get("weights_sha256"))
        ):
            cpu_ready.add(branch)
        else:
            blockers.append(f"runtime_capability:{branch}:native_cpu_openvino_binding_invalid")

        if not isinstance(gpu, Mapping):
            blockers.append(f"runtime_capability:{branch}:nvidia_gpu_binding_missing")
            continue
        factory = str(gpu.get("factory", ""))
        backend = str(gpu.get("backend", ""))
        device_api = str(gpu.get("device_api", ""))
        if factory in {"gvadetect", "object_detect"} or backend.startswith("openvino"):
            blockers.append(f"runtime_capability:{branch}:openvino_gpu_is_not_nvidia_cuda")
            continue
        native_cuda = (
            factory in {"nvinfer", "vastcudainfer"}
            and backend in {"deepstream_tensorrt", "cuda_tensorrt"}
            and device_api == "NVIDIA_CUDA"
            and str(gpu.get("gpu_id", "")) == "0"
            and str(gpu.get("runtime_status", ""))
            == "implemented_and_native_terminal_verified"
            and valid_sha(gpu.get("model_sha256"))
            and valid_sha(gpu.get("runtime_config_sha256"))
            and len(str(gpu.get("parity_binding_id", ""))) >= 8
        )
        if not native_cuda:
            blockers.append(f"runtime_capability:{branch}:native_nvidia_cuda_binding_invalid")
            continue
        gpu_ready.add(branch)

    cpu_complete = cpu_ready == set(ANALYTICS_BRANCHES)
    gpu_complete = gpu_ready == set(ANALYTICS_BRANCHES)
    blockers = list(dict.fromkeys(blockers))
    return {
        "schema_version": 1,
        "artifact_kind": "vast_checkpoint_gstreamer_native_policy_capability_assessment",
        "passed": cpu_complete and gpu_complete and not blockers,
        "status": "ready" if cpu_complete and gpu_complete and not blockers else "blocked",
        "cpu_ready_branches": sorted(cpu_ready),
        "nvidia_gpu_ready_branches": sorted(gpu_ready),
        "eligible_policies": list(POLICIES) if cpu_complete and gpu_complete else (["cpu_only"] if cpu_complete else []),
        "blockers": blockers,
    }


def native_policy_identity_environment(
    *,
    system: str,
    capability_manifest: Mapping[str, Any],
) -> dict[str, str]:
    """Expose each branch's frozen CPU/GPU policy identities to native workers.

    Qualification-v2 identities are coordinate hashes over the image patch,
    parity and analytics bindings, so the native probe cannot derive them; it
    binds the manifest's values exactly and the coordinator rejects any other.
    """
    try:
        branches = capability_manifest["systems"][system]["branches"]
    except (KeyError, TypeError) as exc:
        raise NativePolicyRuntimeError(f"{system} capability bindings are missing") from exc
    if not isinstance(branches, Mapping) or set(branches) != set(ANALYTICS_BRANCHES):
        raise NativePolicyRuntimeError("native policy identities do not cover every branch")
    environment: dict[str, str] = {}
    for branch in ANALYTICS_BRANCHES:
        drop_detectors: set[str] = set()
        for resource in RESOURCES:
            try:
                binding = branches[branch][resource]
                native = binding["native_evidence"]
                drop_detector = binding["terminal_detector"]
                runtime_identity = binding["runtime_identity"]
                values = {
                    "IMPLEMENTATION_ID": _text(binding["implementation_id"], "implementation_id"),
                    "EMITTER_ID": _text(native["emitter_id"], "emitter_id"),
                    "EMITTER_SHA256": str(native["emitter_sha256"]),
                }
            except (KeyError, TypeError) as exc:
                raise NativePolicyRuntimeError(
                    f"{branch}:{resource}: native policy identity is missing"
                ) from exc
            if re.fullmatch(r"[0-9a-f]{64}", values["EMITTER_SHA256"]) is None:
                raise NativePolicyRuntimeError(f"{branch}:{resource}: emitter_sha256 is invalid")
            if (
                type(drop_detector) is not str
                or _DROP_DETECTOR_IDENTITY.fullmatch(drop_detector) is None
                or not isinstance(runtime_identity, Mapping)
                or runtime_identity.get("terminal_detector") != drop_detector
            ):
                raise NativePolicyRuntimeError(
                    f"{branch}:{resource}: external drop detector identity is invalid or drifted"
                )
            drop_detectors.add(drop_detector)
            for field, value in values.items():
                environment[f"VAST_CHECKPOINT_ANALYTICS_{resource.upper()}_{field}_{branch}"] = value
        if len(drop_detectors) != 1:
            raise NativePolicyRuntimeError(
                f"{branch}: CPU/GPU external drop detector identities differ"
            )
        environment[f"VAST_CHECKPOINT_ANALYTICS_DROP_DETECTOR_{branch}"] = next(
            iter(drop_detectors)
        )
    environment["VAST_CHECKPOINT_ANALYTICS_EXTERNAL_EXECUTION_MODE"] = "1"
    return environment


def require_exact_native_cpu_capability_bindings(
    *,
    binary: Path,
    analytics_bindings: Mapping[str, Mapping[str, Any]],
    capability_manifest: Mapping[str, Any],
) -> None:
    """Match the frozen manifest to identities computed by the loaded CPU worker."""

    binary_path = Path(binary)
    resolved_binary = (
        binary_path
        if re.fullmatch(r"/proc/self/fd/[0-9]+", str(binary_path))
        else binary_path.resolve()
    )
    if not resolved_binary.is_file():
        raise NativePolicyRuntimeError(f"native policy binary is missing: {resolved_binary}")
    executable_sha256 = hashlib.sha256(resolved_binary.read_bytes()).hexdigest()
    if set(analytics_bindings) != set(ANALYTICS_BRANCHES):
        raise NativePolicyRuntimeError("native CPU analytics bindings do not cover every branch")
    try:
        manifest_bindings = capability_manifest["systems"]["gstreamer_custom"]["branches"]
    except (KeyError, TypeError) as exc:
        raise NativePolicyRuntimeError("gstreamer_custom capability bindings are missing") from exc
    for branch in ANALYTICS_BRANCHES:
        analytics = analytics_bindings[branch]
        factory = str(analytics.get("factory", ""))
        model_sha256 = str(analytics.get("model_sha256", ""))
        weights_sha256 = str(analytics.get("weights_sha256", ""))
        device = str(analytics.get("device", ""))
        expected_implementation = (
            f"gstreamer-custom-openvino-cpu-v1:{branch}:{factory}:"
            f"{model_sha256}:{weights_sha256}"
        )
        expected_emitter = f"vast-native-gst-policy-path-v1:{branch}:cpu"
        expected_detector = (
            f"{analytics.get('detector_id', '')};model_sha256={model_sha256};"
            f"weights_sha256={weights_sha256}"
        )
        expected_backend = f"openvino-dlstreamer:{factory};device=CPU"
        cpu = manifest_bindings[branch]["cpu"]
        native = cpu["native_evidence"]
        if device != "CPU" or factory not in {"gvadetect", "object_detect"}:
            raise NativePolicyRuntimeError(
                f"{branch}: native CPU capability is not an exact OpenVINO CPU path"
            )
        if cpu.get("implementation_id") != expected_implementation:
            raise NativePolicyRuntimeError(
                f"{branch}: CPU implementation_id differs from loaded detector identity"
            )
        if native.get("emitter_id") != expected_emitter:
            raise NativePolicyRuntimeError(
                f"{branch}: CPU emitter_id differs from compiled worker identity"
            )
        if native.get("emitter_sha256") != executable_sha256:
            raise NativePolicyRuntimeError(
                f"{branch}: CPU emitter_sha256 differs from loaded worker executable"
            )
        if (
            cpu.get("runtime_backend") != "openvino_dlstreamer"
            or cpu.get("device_api") != "CPU"
            or cpu.get("terminal_detector") != expected_detector
            or cpu.get("terminal_backend") != expected_backend
        ):
            raise NativePolicyRuntimeError(
                f"{branch}: CPU terminal identity differs from loaded detector path"
            )


class NativePolicyRuntimeError(RuntimeError):
    """A native scheduling transport or execution invariant failed."""


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise NativePolicyRuntimeError("policy runtime value is not canonical JSON") from exc


def _finite(value: Any, name: str, *, positive: bool = False) -> float:
    if isinstance(value, bool):
        raise NativePolicyRuntimeError(f"{name} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise NativePolicyRuntimeError(f"{name} must be numeric") from exc
    if not math.isfinite(number) or number < 0 or (positive and number <= 0):
        qualifier = "positive" if positive else "nonnegative"
        raise NativePolicyRuntimeError(f"{name} must be finite and {qualifier}")
    return number


def _integer(value: Any, name: str, *, positive: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise NativePolicyRuntimeError(f"{name} must be an integer")
    if value < 0 or (positive and value <= 0):
        qualifier = "positive" if positive else "nonnegative"
        raise NativePolicyRuntimeError(f"{name} must be {qualifier}")
    return value


def _text(value: Any, name: str) -> str:
    text = str(value)
    if len(text) < 8 or text.strip() != text:
        raise NativePolicyRuntimeError(f"{name} must be a stable non-placeholder ID")
    return text


def _require_exact_fields(message: Mapping[str, Any], expected: set[str]) -> None:
    if set(message) != expected:
        raise NativePolicyRuntimeError("native policy message fields have drifted")
    if message.get("schema_version") != POLICY_RPC_SCHEMA_VERSION:
        raise NativePolicyRuntimeError("native policy message schema_version has drifted")


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise NativePolicyRuntimeError(f"refusing to overwrite native policy evidence: {path}")
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    if temporary.exists():
        raise NativePolicyRuntimeError(f"stale policy evidence temporary exists: {temporary}")
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


@dataclass
class _DecisionState:
    worker_id: str
    input_frame_key: str
    transport_pts_ns: int
    feature_observed_timestamp_ms: float
    submitted_decision_time_ms: float
    record: dict[str, Any]
    decision_request: dict[str, Any] | None = None
    path: dict[str, Any] | None = None
    terminal: dict[str, Any] | None = None
    accepted: dict[str, Any] | None = None
    feedback: dict[str, Any] | None = None
    feedback_seq: int | None = None


class NativePolicyRuntimeCoordinator:
    """One shared deterministic scheduler for every worker in one benchmark arm."""

    def __init__(
        self,
        *,
        run_id: str,
        arm_id: str,
        system: str,
        scenario: str,
        codec: str,
        policy: str,
        deadline_ms: float,
        branches: tuple[str, ...] | list[str],
        capability_manifest: Mapping[str, Any],
        calibration: Mapping[str, Any],
        static_hybrid_map: Mapping[str, Any] | None = None,
        operational_context: Mapping[str, Any] | None = None,
        study_runtime_plan: Mapping[str, Any] | None = None,
    ) -> None:
        self.run_id = _text(run_id, "run_id")
        self.arm_id = _text(arm_id, "arm_id")
        if system not in PUBLISHABLE_SYSTEMS:
            raise NativePolicyRuntimeError(
                "native checkpoint policy binding is outside the publishable runtime set"
            )
        if scenario not in {
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        }:
            raise NativePolicyRuntimeError("unsupported checkpoint topology scenario")
        normalized_codec = str(codec).strip().lower()
        if normalized_codec not in {"h264", "h265"}:
            raise NativePolicyRuntimeError("checkpoint policy codec must be exactly h264 or h265")
        if policy not in POLICIES:
            raise NativePolicyRuntimeError("checkpoint policy is outside the frozen seven-policy set")
        if tuple(branches) != tuple(ANALYTICS_BRANCHES):
            raise NativePolicyRuntimeError("checkpoint analytics branch set or order has drifted")

        assessment = assess_capability_manifest(capability_manifest)
        if not assessment["passed"]:
            raise NativePolicyRuntimeError(
                "publication policy capability manifest is blocked: "
                + ", ".join(str(item) for item in assessment["blockers"][:8])
            )
        try:
            expected_static_map = select_static_hybrid_map(
                system,
                calibration,
                capability_manifest,
            )
        except PolicyContractError as exc:
            raise NativePolicyRuntimeError(f"publication policy calibration is blocked: {exc}") from exc
        if policy == "static_hybrid":
            if dict(static_hybrid_map or {}) != expected_static_map:
                raise NativePolicyRuntimeError(
                    "static_hybrid map is not the exact exhaustive map selected from calibration"
                )
            engine_static_map: Mapping[str, Any] | None = expected_static_map
        else:
            if static_hybrid_map is not None:
                raise NativePolicyRuntimeError("static_hybrid_map is forbidden for another policy")
            engine_static_map = None

        self.system = system
        self.scenario = scenario
        self.codec = normalized_codec
        self.policy = policy
        self.deadline_ms = _finite(deadline_ms, "deadline_ms", positive=True)
        self.branches = tuple(branches)
        self._capability_manifest = copy.deepcopy(dict(capability_manifest))
        self._calibration = copy.deepcopy(dict(calibration))
        self._static_placement = dict(expected_static_map["placement"])
        self._engine = PolicyEngine(
            policy=policy,
            system=system,
            capability_manifest=self._capability_manifest,
            static_hybrid_map=engine_static_map,
        )
        self._engine.reset(self.arm_id)
        self._initial_policy_state = self._engine.state_snapshot()
        self._operational_context = None
        self._operational_error: str | None = None
        if operational_context is not None:
            if not isinstance(operational_context, Mapping) or set(operational_context) != {"header", "output_dir"}:
                raise NativePolicyRuntimeError("operational context fields mismatch")
            header = copy.deepcopy(dict(operational_context["header"]))
            try:
                scope = None
                if study_runtime_plan is not None:
                    from checkpoint_runtime_plan import validate_finite_study_runtime_plan_v1
                    validate_finite_study_runtime_plan_v1(study_runtime_plan)
                    scope = {"kind": "finite-component-study", "plan_sha256": study_runtime_plan["study_plan"]["sha256"],
                        "max_frame_id": 441, "max_requests_per_arm": 10608, "max_operations": 32}
                validate_native_header_v1(header, require_sha="sha256" in header, study_scope=scope)
            except ValueError as exc:
                raise NativePolicyRuntimeError(f"operational context is blocked: {exc}") from exc
            for key, expected in (("run_id", self.run_id), ("system", self.system),
                                  ("scenario", self.scenario), ("codec", self.codec),
                                  ("policy", self.policy), ("deadline_ms", self.deadline_ms),
                                  ("initial_state", self._initial_policy_state)):
                if canonical_json_v1(header[key]) != canonical_json_v1(expected):
                    raise NativePolicyRuntimeError(f"operational context {key} mismatch")
            self._operational_context = {"header": header,
                                         "output_dir": Path(operational_context["output_dir"])}
        self._lock = threading.RLock()
        self._next_decision_seq = 1
        self._next_feedback_seq = 1
        self._last_decision_timestamp_ms = 0.0
        self._resource_available_ms = {resource: 0.0 for resource in RESOURCES}
        self._states: dict[str, _DecisionState] = {}
        self._decision_by_execution: dict[tuple[str, str, str, int], str] = {}
        # Actual successful commits only, recorded under the same coordinator
        # lock. Records already live in _states; this log stores compact refs.
        self._history_events: list[dict[str, Any]] = []
        self._history_capture_bytes = 4096  # bounded header reservation
        self._history_error: str | None = None

    def persist_study_operational_v1(self, *, measurement_input_keys):
        """Retain real accepted decisions without promoting a legacy full export."""
        with self._lock:
            _require(self._operational_context is not None and
                self._operational_context["header"].get("study_scope") is not None,
                "finite study requires its original separately typed context")
            header = copy.deepcopy(self._operational_context["header"])
            scope = header["study_scope"]
            ordered = sorted(self._states.values(), key=lambda state: state.record["decision_seq"])
            _require(len(ordered) <= scope["max_requests_per_arm"] and self._operational_error is None,
                     "finite native source gate has failed")
            measured = set(measurement_input_keys)
            records = []
            for state in ordered:
                _require(state.decision_request is not None and state.accepted is not None and
                    state.path is not None and state.terminal is not None,
                    "finite native occurrence is unresolved; no completion may be invented")
                records.append(build_native_occurrence_v1(runtime_decision_seq=state.record["decision_seq"],
                    measurement=state.input_frame_key in measured, decision_request=state.decision_request,
                    accepted_record=state.accepted, path=state.path, terminal=state.terminal,
                    issued_record_sha256=state.record["sha256"], study_scope=scope))
            count = sum(record["measurement"] for record in records)
            header["counts"] = {"complete_decision_count": len(records), "measurement_decision_count": count,
                "excluded_decision_count": len(records)-count, "runtime_feedback_count": self._next_feedback_seq-1,
                "measurement_feedback_count": sum(state.feedback is not None and state.input_frame_key in measured for state in ordered),
                "excluded_feedback_count": sum(state.feedback is not None and state.input_frame_key not in measured for state in ordered)}
            header["initial_state"] = copy.deepcopy(self._initial_policy_state)
            header["adaptive_history"] = None
            header = payload_with_sha256_v1(header)
            # Existing decision validator checks the complete original capability,
            # and occurrence validation joins the raw request/path/terminal.
            def original_authority(record):
                assessment = validate_decision_record(record["accepted_record"], self._capability_manifest)
                _require(assessment["passed"], "study original native authority validation failed: " + str(assessment["blockers"]))
            destination = self._operational_context["output_dir"] / NATIVE_OPERATIONAL_JSONL
            return write_native_domain_v1(destination, header, records,
                original_authority_validator=original_authority, study_scope=scope)

    def _capture_history_event(self, event: Mapping[str, Any]) -> None:
        if self.policy != "adaptive_weights":
            return
        captured = payload_with_sha256_v1({
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_runtime_history_event_v1",
            "event_seq": len(self._history_events) + 1,
            **event,
        })
        line_bytes = len(canonical_json_v1(captured)) + 1
        if (
            len(self._history_events) >= MAX_RUNTIME_HISTORY_EVENTS_V1
            or line_bytes > MAX_RUNTIME_HISTORY_LINE_BYTES_V1
            or self._history_capture_bytes + line_bytes > MAX_RUNTIME_HISTORY_BYTES_V1
        ):
            self._history_error = "adaptive runtime history capture exceeds frozen bounds"
            raise NativePolicyRuntimeError(self._history_error)
        self._history_events.append(captured)
        self._history_capture_bytes += line_bytes

    def _binding(self, branch: str, resource: str) -> Mapping[str, Any]:
        return self._capability_manifest["systems"][self.system]["branches"][branch][resource]

    def _allowed(self, branch: str, resource: str) -> bool:
        if self.policy == "cpu_only":
            return resource == "cpu"
        if self.policy == "gpu_only":
            return resource == "gpu"
        if self.policy == "static_hybrid":
            return resource == self._static_placement[branch]
        return True

    def _handle_request(self, worker_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        _require_exact_fields(message, _REQUEST_FIELDS)
        if self._operational_context is not None:
            try:
                scope = self._operational_context["header"].get("study_scope")
                validate_native_request_source_v1(message, study_scope=scope)
                maximum = scope["max_requests_per_arm"] if scope is not None else MAX_NATIVE_DECISIONS_V1
                if len(self._states) >= maximum:
                    raise OperationalDomainError("native operational state exceeds original bounded decisions")
            except ValueError as exc:
                self._operational_error = str(exc)
                raise NativePolicyRuntimeError(self._operational_error) from exc
        if message.get("message_type") != "decision_request":
            raise NativePolicyRuntimeError("expected decision_request")
        observed_worker = _text(message.get("worker_id"), "worker_id")
        if worker_id != observed_worker:
            raise NativePolicyRuntimeError("worker_id does not match policy transport endpoint")
        if message.get("run_id") != self.run_id:
            raise NativePolicyRuntimeError("run_id does not match policy arm")
        input_frame_key = _text(message.get("input_frame_key"), "input_frame_key")
        trace_id = _text(message.get("trace_id"), "trace_id")
        _integer(message.get("stream_id"), "stream_id")
        _integer(message.get("frame_id"), "frame_id")
        transport_pts_ns = _integer(message.get("transport_pts_ns"), "transport_pts_ns")
        branch = str(message.get("branch", ""))
        if branch not in self.branches:
            raise NativePolicyRuntimeError("decision branch is outside analytics_only scope")
        arrival_ms = _finite(message.get("arrival_ms"), "arrival_ms")
        submitted_decision_time_ms = _finite(
            message.get("decision_time_ms"), "decision_time_ms", positive=True
        )
        observed_ms = _finite(
            message.get("feature_observed_timestamp_ms"),
            "feature_observed_timestamp_ms",
            positive=True,
        )
        if (
            observed_ms > submitted_decision_time_ms
            or arrival_ms > submitted_decision_time_ms
        ):
            raise NativePolicyRuntimeError("decision features or arrival occur after the decision")
        # Worker processes capture their timestamps before contending for this
        # coordinator lock.  The decision sequence is assigned here, so bind
        # its timestamp to the same serialized order while retaining the
        # original feature observation for provenance/age.
        decision_time_ms = max(
            submitted_decision_time_ms, self._last_decision_timestamp_ms
        )
        raw_depths = message.get("queue_depths")
        if not isinstance(raw_depths, Mapping) or set(raw_depths) != set(RESOURCES):
            raise NativePolicyRuntimeError("queue_depths must contain exactly cpu and gpu")
        queue_depths = {
            resource: _integer(raw_depths[resource], f"queue_depths.{resource}")
            for resource in RESOURCES
        }
        execution_key = (observed_worker, input_frame_key, branch, transport_pts_ns)
        if execution_key in self._decision_by_execution:
            raise NativePolicyRuntimeError("duplicate decision request for one native execution")

        decision_seq = self._next_decision_seq
        decision_id = (
            f"{self.run_id}:native-policy:{decision_seq}:{observed_worker}:"
            f"{transport_pts_ns}:{branch}"
        )
        candidates: dict[str, dict[str, Any]] = {}
        rank_u_ms = 0.0
        for resource in RESOURCES:
            calibration = self._calibration["costs"][branch][resource]
            service_ms = _finite(
                calibration["service_ms"],
                f"calibration.{branch}.{resource}.service_ms",
                positive=True,
            )
            transfer_ms = _finite(
                calibration["transfer_ms"],
                f"calibration.{branch}.{resource}.transfer_ms",
            )
            rank_u_ms = max(rank_u_ms, service_ms + transfer_ms)
            candidates[resource] = {
                "allowed": self._allowed(branch, resource),
                "implementation_id": self._binding(branch, resource)["implementation_id"],
                "available_ms": self._resource_available_ms[resource],
                "queue_depth": queue_depths[resource],
                "estimated_service_ms": service_ms,
                "transfer_ms": transfer_ms,
            }
        try:
            record = self._engine.decide(
                {
                    "decision_id": decision_id,
                    "decision_seq": decision_seq,
                    "trace_id": trace_id,
                    "branch": branch,
                    "arrival_ms": arrival_ms,
                    "decision_time_ms": decision_time_ms,
                    "deadline_ms": arrival_ms + self.deadline_ms,
                    "rank_u_ms": rank_u_ms,
                    "candidates": candidates,
                }
            )
        except PolicyContractError as exc:
            raise NativePolicyRuntimeError(f"frozen policy decision failed: {exc}") from exc
        selected = str(record["selected_resource"])
        self._resource_available_ms[selected] = float(
            record["evaluations"][selected]["predicted_finish_ms"]
        )
        state = _DecisionState(
            worker_id=observed_worker,
            input_frame_key=input_frame_key,
            transport_pts_ns=transport_pts_ns,
            feature_observed_timestamp_ms=observed_ms,
            submitted_decision_time_ms=submitted_decision_time_ms,
            record=record,
            decision_request=(copy.deepcopy(dict(message))
                              if self._operational_context is not None else None),
        )
        self._states[decision_id] = state
        self._decision_by_execution[execution_key] = decision_id
        self._last_decision_timestamp_ms = float(
            record["request"]["decision_time_ms"]
        )
        self._next_decision_seq += 1
        if self.policy == "adaptive_weights":
            self._capture_history_event({
                "event_type": "decision_issued", "runtime_decision_seq": decision_seq,
                "decision_id": decision_id, "measurement": False,
                "issued_record_sha256": record["sha256"],
                "accepted_record_sha256": "0" * 64, "accepted_record": None,
            })
        binding = self._binding(branch, selected)
        native = binding["native_evidence"]
        return {
            "schema_version": POLICY_RPC_SCHEMA_VERSION,
            "message_type": "decision_response",
            "decision_id": decision_id,
            "decision_seq": decision_seq,
            "selected_resource": selected,
            "selected_implementation_id": record["selected_implementation_id"],
            "emitter_id": native["emitter_id"],
            "emitter_sha256": native["emitter_sha256"],
        }

    def _state_for_message(
        self,
        worker_id: str,
        message: Mapping[str, Any],
    ) -> _DecisionState:
        if message.get("run_id") != self.run_id:
            raise NativePolicyRuntimeError("run_id does not match policy arm")
        observed_worker = _text(message.get("worker_id"), "worker_id")
        if worker_id != observed_worker:
            raise NativePolicyRuntimeError("worker_id does not match policy transport endpoint")
        decision_id = _text(message.get("decision_id"), "decision_id")
        state = self._states.get(decision_id)
        if state is None:
            raise NativePolicyRuntimeError("native policy message references an unknown decision_id")
        if state.worker_id != observed_worker:
            raise NativePolicyRuntimeError("decision_id belongs to another worker")
        branch = str(message.get("branch", ""))
        if branch != state.record["branch"]:
            raise NativePolicyRuntimeError("decision branch identity drifted")
        if message.get("input_frame_key") != state.input_frame_key:
            raise NativePolicyRuntimeError("decision input_frame_key identity drifted")
        pts = _integer(message.get("transport_pts_ns"), "transport_pts_ns")
        if pts != state.transport_pts_ns:
            raise NativePolicyRuntimeError("decision transport_pts_ns identity drifted")
        return state

    def _handle_path(self, worker_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        _require_exact_fields(message, _PATH_FIELDS)
        if message.get("message_type") != "path_enter":
            raise NativePolicyRuntimeError("expected path_enter")
        state = self._state_for_message(worker_id, message)
        if state.path is not None:
            raise NativePolicyRuntimeError("duplicate native path entry")
        if state.terminal is not None:
            raise NativePolicyRuntimeError("native path entry follows terminal evidence")
        selected = str(state.record["selected_resource"])
        observed = str(message.get("selected_resource", ""))
        if observed != selected:
            raise NativePolicyRuntimeError(
                f"unselected execution path entered: expected {selected}, observed {observed}"
            )
        binding = self._binding(str(state.record["branch"]), selected)
        native = binding["native_evidence"]
        expected = {
            "implementation_id": binding["implementation_id"],
            "emitter_id": native["emitter_id"],
            "emitter_sha256": native["emitter_sha256"],
        }
        for field, value in expected.items():
            if message.get(field) != value:
                raise NativePolicyRuntimeError(f"native path {field} does not match capability binding")
        _text(message.get("event_id"), "event_id")
        timestamp_ms = _finite(message.get("timestamp_ms"), "timestamp_ms", positive=True)
        # Bound the path entry by the decision timestamp the worker submitted,
        # not by the serialized value this coordinator may have raised above it.
        # The raised value is never returned to the worker, so holding a worker
        # to it turns a host wall-clock regression between two concurrent
        # workers into a false native ordering violation.
        if timestamp_ms < state.submitted_decision_time_ms:
            raise NativePolicyRuntimeError("native path entry precedes its decision")
        state.path = copy.deepcopy(dict(message))
        return {
            "schema_version": POLICY_RPC_SCHEMA_VERSION,
            "message_type": "path_ack",
            "decision_id": state.record["decision_id"],
            "accepted": True,
        }

    def _handle_terminal(self, worker_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        _require_exact_fields(message, _TERMINAL_FIELDS)
        if message.get("message_type") != "terminal":
            raise NativePolicyRuntimeError("expected terminal")
        state = self._state_for_message(worker_id, message)
        if state.path is None:
            raise NativePolicyRuntimeError("terminal has no native path entry")
        if state.terminal is not None or state.accepted is not None:
            raise NativePolicyRuntimeError("duplicate native terminal evidence")
        selected = str(state.record["selected_resource"])
        if message.get("selected_resource") != selected:
            raise NativePolicyRuntimeError("terminal resource does not match selected execution path")
        if message.get("terminal_status") != "completed":
            raise NativePolicyRuntimeError("native detector terminal_status must be completed")
        terminal_ms = _finite(
            message.get("terminal_timestamp_ms"),
            "terminal_timestamp_ms",
            positive=True,
        )
        if terminal_ms < float(state.path["timestamp_ms"]):
            raise NativePolicyRuntimeError("native detector terminal precedes path entry")
        actual_service_ms = _finite(
            message.get("actual_service_ms"),
            "actual_service_ms",
            positive=True,
        )
        detector = _text(message.get("detector"), "detector")
        backend = str(message.get("backend", ""))
        binding = self._binding(str(state.record["branch"]), selected)
        identity = binding.get("runtime_identity")
        if not isinstance(identity, Mapping):
            raise NativePolicyRuntimeError("selected capability has no validated runtime identity")
        expected_detector = str(identity.get("terminal_detector", ""))
        expected_backend = str(identity.get("terminal_backend", ""))
        identity_projection_matches = all(
            binding.get(field) == identity.get(field)
            for field in (
                "runtime_backend",
                "device_api",
                "gpu_id",
                "worker_image_digest",
                "implementation_version",
                "terminal_detector",
                "terminal_backend",
            )
        )
        if selected == "cpu":
            capability_matches_resource = (
                identity.get("device_api") == "CPU"
                and identity.get("gpu_id") is None
                and "device=CPU" in expected_backend
                and "NVIDIA_CUDA" not in expected_backend
            )
        else:
            capability_matches_resource = (
                identity.get("device_api") == "NVIDIA_CUDA"
                and type(identity.get("gpu_id")) is int
                and identity.get("gpu_id") == 0
                and _NVIDIA_CUDA_TERMINAL_BACKEND.fullmatch(expected_backend)
                is not None
            )
        if (
            not identity_projection_matches
            or not capability_matches_resource
            or not expected_detector
            or detector != expected_detector
            or backend != expected_backend
        ):
            raise NativePolicyRuntimeError(
                f"terminal identity does not match selected {selected} capability path"
            )
        path = state.path
        evidence = {
            "event_id": path["event_id"],
            "decision_id": state.record["decision_id"],
            "system": self.system,
            "branch": state.record["branch"],
            "selected_resource": selected,
            "implementation_id": path["implementation_id"],
            "emitter_id": path["emitter_id"],
            "emitter_sha256": path["emitter_sha256"],
            "telemetry_source": "native",
            "path_entry_timestamp_ms": path["timestamp_ms"],
            "terminal_status": "completed",
            "terminal_timestamp_ms": terminal_ms,
            "actual_service_ms": actual_service_ms,
            "detector": detector,
            "backend": backend,
            "worker_id": state.worker_id,
            "input_frame_key": state.input_frame_key,
            "transport_pts_ns": state.transport_pts_ns,
        }
        try:
            accepted = bind_native_decision_evidence(
                state.record,
                evidence,
                self._capability_manifest,
            )
            feedback = (
                self._engine.feedback(
                    state.record,
                    actual_service_ms=actual_service_ms,
                    completed_at_ms=terminal_ms,
                )
                if self.policy == "adaptive_weights"
                else None
            )
        except PolicyContractError as exc:
            raise NativePolicyRuntimeError(f"native terminal binding failed: {exc}") from exc
        state.terminal = copy.deepcopy(dict(message))
        state.accepted = accepted
        state.feedback = feedback
        if feedback is not None:
            state.feedback_seq = self._next_feedback_seq
            self._next_feedback_seq += 1
            self._capture_history_event({
                "event_type": "feedback_applied", "runtime_feedback_seq": state.feedback_seq,
                "decision_id": state.record["decision_id"], "measurement": False,
                "issued_record_sha256": state.record["sha256"],
                "feedback_record_sha256": feedback["sha256"], "feedback_record": None,
            })
        self._resource_available_ms[selected] = max(
            self._resource_available_ms[selected],
            terminal_ms,
        )
        return {
            "schema_version": POLICY_RPC_SCHEMA_VERSION,
            "message_type": "terminal_ack",
            "decision_id": state.record["decision_id"],
            "accepted": True,
        }

    def handle_message(self, worker_id: str, message: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(message, Mapping):
            raise NativePolicyRuntimeError("native policy message must be a JSON object")
        with self._lock:
            if self._operational_error is not None:
                raise NativePolicyRuntimeError(self._operational_error)
            if self._history_error is not None:
                raise NativePolicyRuntimeError(self._history_error)
            kind = message.get("message_type")
            if kind == "decision_request":
                return self._handle_request(worker_id, message)
            if kind == "path_enter":
                return self._handle_path(worker_id, message)
            if kind == "terminal":
                return self._handle_terminal(worker_id, message)
            raise NativePolicyRuntimeError("unknown native policy message_type")

    def serve_worker_socket(self, worker_id: str, endpoint: socket.socket) -> None:
        """Serve one inherited ``SOCK_SEQPACKET`` endpoint until the worker exits."""

        try:
            while True:
                packet, _ancillary, flags, _address = endpoint.recvmsg(
                    POLICY_RPC_MAX_MESSAGE_BYTES
                )
                if not packet:
                    return
                if flags & socket.MSG_TRUNC:
                    raise NativePolicyRuntimeError("native policy message exceeds size limit")
                try:
                    message = json.loads(packet.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise NativePolicyRuntimeError("native policy message is not valid UTF-8 JSON") from exc
                response = self.handle_message(worker_id, message)
                encoded = _canonical_json(response).encode("utf-8")
                if len(encoded) > POLICY_RPC_MAX_MESSAGE_BYTES:
                    raise NativePolicyRuntimeError("native policy response exceeds size limit")
                endpoint.sendall(encoded)
        except Exception as exc:
            try:
                encoded = _canonical_json(
                    {
                        "schema_version": POLICY_RPC_SCHEMA_VERSION,
                        "message_type": "policy_error",
                        "error": str(exc),
                    }
                ).encode("utf-8")
                endpoint.sendall(encoded)
            except OSError:
                pass
            raise
        finally:
            endpoint.close()

    def _policy_score(self, record: Mapping[str, Any], resource: str) -> float:
        evaluation = record["evaluations"][resource]
        if self.policy == "queue_aware_edf":
            return float(evaluation["queue_completion_ms"])
        if self.policy == "adaptive_weights":
            return float(evaluation["adaptive_score_ms"])
        return float(evaluation["predicted_finish_ms"])

    def _policy_row(
        self,
        state: _DecisionState,
        canonical: Mapping[str, Any],
    ) -> dict[str, Any]:
        if state.accepted is None or state.terminal is None:
            raise NativePolicyRuntimeError("cannot serialize an unaccepted native decision")
        record = state.accepted
        request = record["request"]
        selected = str(record["selected_resource"])
        allowed = [
            resource
            for resource in RESOURCES
            if bool(record["evaluations"][resource]["allowed"])
        ]
        scores = {resource: self._policy_score(record, resource) for resource in allowed}
        components = {
            resource: copy.deepcopy(record["evaluations"][resource])
            for resource in allowed
        }
        decision_ms = float(request["decision_time_ms"])
        feature_provenance = {
            "native_queue_depths": {
                "source": f"native_worker_socket:{state.worker_id}",
                "source_trace_id": str(request["trace_id"]),
                "observed_timestamp_ms": state.feature_observed_timestamp_ms,
                "age_ms": decision_ms - state.feature_observed_timestamp_ms,
                "estimator_version": f"native-{self.system}-queue-snapshot-v1",
            }
        }
        parameters: dict[str, Any] = {
            "score_epsilon": 1e-9,
            "weights": copy.deepcopy(record["state_before"]["weights"]),
            "policy_scope": POLICY_SCOPE,
            "engine_implementation_id": record["engine_implementation_id"],
        }
        if self.policy == "adaptive_weights":
            parameters.update(
                {
                    "weight_lower_bound": 0.5,
                    "weight_upper_bound": 1.5,
                    "ewma_alpha": 0.1,
                    "late_penalty": 0.002,
                    "on_time_reward": 0.0002,
                    "feedback_update_rule": "bounded_selected_resource_reward_penalty_v1",
                }
            )
        profile_digest = hashlib.sha256(
            _canonical_json(self._calibration).encode("utf-8")
        ).hexdigest()
        return {
            "schema_version": TELEMETRY_SCHEMA_VERSION,
            "run_id": self.run_id,
            "trace_id": _text(canonical.get("trace_id"), "canonical trace_id"),
            "stream_id": _integer(canonical.get("stream_id"), "canonical stream_id"),
            "frame_id": _integer(canonical.get("frame_id"), "canonical frame_id"),
            "stage": str(record["branch"]),
            "policy": self.policy,
            "decision": str(record["selected_implementation_id"]),
            "resource": selected,
            "queue_depth": int(request["candidates"][selected]["queue_depth"]),
            "estimated_cost_ms": scores[selected],
            "deadline_ms": self.deadline_ms,
            "policy_version": str(record["engine_implementation_id"]),
            "allowed_resources_json": _canonical_json(allowed),
            "alternative_scores_json": _canonical_json(scores),
            "cost_components_json": _canonical_json(components),
            "parameters_json": _canonical_json(parameters),
            "tie_break_rule": "transfer_ms,queue_depth,fixed_resource_order_cpu_gpu",
            "decision_mode": "applied",
            "update_seq": 0,
            "update_json": "{}",
            "reason": str(record["reason"]),
            "decision_id": str(record["decision_id"]),
            "decision_seq": int(record["decision_seq"]),
            "decision_timestamp_ms": decision_ms,
            "graph_version": f"{self.scenario}:native-{self.system}-policy-routing-v1",
            "profile_version": f"calibration-sha256:{profile_digest}",
            "feature_provenance_json": _canonical_json(feature_provenance),
            "terminal_status": str(state.terminal["terminal_status"]),
            "terminal_timestamp_ms": float(state.terminal["terminal_timestamp_ms"]),
            "update_timestamp_ms": 0.0,
            "source_decision_ids_json": "[]",
            "first_consumer_decision_id": "unavailable",
            "first_consumer_decision_seq": 0,
            "causal_trace_completeness": "full",
            "decision_provenance": "native_scheduler_trace",
            "trace_completeness": "full",
            "telemetry_source": "native",
        }

    def promote(
        self,
        output_dir: Path,
        *,
        canonical_frames: Mapping[str, Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Validate all native terminals, then atomically expose publication sidecars."""

        output_dir = Path(output_dir)
        with self._lock:
            if self._operational_error is not None:
                raise NativePolicyRuntimeError(self._operational_error)
            if not self._states:
                raise NativePolicyRuntimeError("native policy runtime emitted no decisions")
            pending = [
                decision_id
                for decision_id, state in self._states.items()
                if state.accepted is None or state.path is None or state.terminal is None
            ]
            if pending:
                raise NativePolicyRuntimeError(
                    "unterminated native decisions: " + ", ".join(pending[:5])
                )
            runtime_ordered = sorted(
                self._states.values(),
                key=lambda state: int(state.record["decision_seq"]),
            )
            ordered = [
                state
                for state in runtime_ordered
                if state.input_frame_key in canonical_frames
            ]
            if not ordered:
                raise NativePolicyRuntimeError(
                    "native policy runtime has no accepted measurement-cohort decisions"
                )
            canonical_by_state: list[Mapping[str, Any]] = []
            for state in ordered:
                canonical = canonical_frames.get(state.input_frame_key)
                if not isinstance(canonical, Mapping):
                    raise NativePolicyRuntimeError(
                        f"native decision has no canonical frame linkage: {state.input_frame_key}"
                    )
                canonical_by_state.append(canonical)
            if self._history_error is not None:
                raise NativePolicyRuntimeError(self._history_error)
            accepted_records = []
            rows = []
            for publication_seq, (state, canonical) in enumerate(
                zip(ordered, canonical_by_state, strict=True), 1
            ):
                projected = project_accepted_decision_v1(
                    state.accepted,
                    canonical_trace_id=_text(canonical.get("trace_id"), "canonical trace_id"),
                    publication_decision_seq=publication_seq,
                    issued_record_sha256=state.record["sha256"],
                )
                row = self._policy_row(state, canonical)
                row["decision_seq"] = publication_seq
                rows.append(row)
                accepted_records.append(projected)
            ingress_rows = [
                {"input_frame_key": key, "trace_id": value.get("trace_id"),
                 "stream_id": value.get("stream_id"), "frame_id": value.get("frame_id")}
                for key, value in canonical_frames.items()
            ]
            feedback_states = sorted(
                (state for state in ordered if state.feedback is not None),
                key=lambda state: int(state.feedback_seq or 0),
            )
            feedback_records = [state.feedback for state in feedback_states]
            if self.policy == "adaptive_weights" and (
                len(feedback_records) != len(ordered)
                or any(state.feedback is None for state in runtime_ordered)
            ):
                raise NativePolicyRuntimeError(
                    "adaptive_weights lacks complete native terminal feedback"
                )
            if self.policy != "adaptive_weights" and any(
                state.feedback is not None for state in runtime_ordered
            ):
                raise NativePolicyRuntimeError("non-adaptive policy emitted feedback")
            def bounded_jsonl(records):
                buffer = io.BytesIO()
                for record in records:
                    line = canonical_json_v1(record) + b"\n"
                    if buffer.tell() + len(line) > MAX_RUNTIME_HISTORY_BYTES_V1:
                        raise NativePolicyRuntimeError("native policy JSONL exceeds frozen file byte bound")
                    buffer.write(line)
                return buffer.getvalue()

            decisions_json = bounded_jsonl(accepted_records)
            feedback_json = bounded_jsonl(feedback_records)
            csv_buffer = io.StringIO(newline="")
            writer = csv.DictWriter(csv_buffer, fieldnames=POLICY_DECISION_COLUMNS)
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
                if csv_buffer.tell() > MAX_RUNTIME_HISTORY_BYTES_V1:
                    raise NativePolicyRuntimeError("native policy CSV exceeds frozen file byte bound")
            targets = {POLICY_DECISIONS_JSONL: decisions_json,
                       POLICY_DECISIONS_CSV: csv_buffer.getvalue().encode("utf-8")}
            if self.policy == "adaptive_weights":
                targets[POLICY_FEEDBACK_JSONL] = feedback_json
                measured_ids = {state.record["decision_id"] for state in ordered}
                def actual_history_events():
                    for captured in self._history_events:
                        event = copy.deepcopy(captured)
                        state = self._states[event["decision_id"]]
                        measurement = event["decision_id"] in measured_ids
                        event["measurement"] = measurement
                        if event["event_type"] == "decision_issued":
                            event["accepted_record_sha256"] = state.accepted["sha256"]
                            event["accepted_record"] = None if measurement else state.accepted
                        else:
                            event["feedback_record"] = None if measurement else state.feedback
                        yield payload_with_sha256_v1(event)
                header = payload_with_sha256_v1({
                    "schema_version": 1, "artifact_kind": "vast_publication_policy_runtime_history_v1",
                    "record_kind": "header", "run_id": self.run_id, "arm_id": self.arm_id,
                    "system": self.system, "policy": self.policy,
                    "policy_contract_sha256": accepted_records[0]["policy_contract_sha256"],
                    "engine_implementation_id": accepted_records[0]["engine_implementation_id"],
                    "initial_state": self._initial_policy_state,
                    "runtime_decision_count": len(runtime_ordered),
                    "runtime_feedback_count": self._next_feedback_seq - 1,
                    "measurement_decision_count": len(ordered),
                    "measurement_feedback_count": len(feedback_records), "event_count": len(self._history_events),
                })
                try:
                    targets[RUNTIME_HISTORY_JSONL] = serialize_runtime_history_v1(header, actual_history_events())
                except ValueError as exc:
                    raise NativePolicyRuntimeError(f"adaptive runtime history is blocked: {exc}") from exc
            # Preserve existing custody limits; no publication may add an
            # oversized sidecar or raise the aggregate acceptance budget.
            if any(len(payload) > MAX_RUNTIME_HISTORY_BYTES_V1 for payload in targets.values()) or sum(
                len(payload) for payload in targets.values()
            ) > MAX_ACCEPTANCE_AGGREGATE_BYTES_V1:
                raise NativePolicyRuntimeError("native policy publication exceeds frozen byte bounds")
            for name in (POLICY_DECISIONS_JSONL, POLICY_DECISIONS_CSV,
                         POLICY_FEEDBACK_JSONL, RUNTIME_HISTORY_JSONL):
                if os.path.lexists(output_dir / name):
                    raise NativePolicyRuntimeError(
                        f"refusing to overwrite native policy evidence: {output_dir / name}"
                    )
            output_dir.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".native-policy-publication.", dir=output_dir))
            published = []
            operational_descriptor = None
            operational_counts = None
            try:
                for name, payload in targets.items():
                    with (staging / name).open("xb") as stream:
                        stream.write(payload)
                validated_decisions = validate_policy_decisions(
                    staging / POLICY_DECISIONS_CSV,
                    require_labeled_provenance=True, require_full_trace=True, require_causal_trace=True,
                )
                history_path = staging / RUNTIME_HISTORY_JSONL if self.policy == "adaptive_weights" else None
                validate_published_decisions_v1(
                    accepted_records, rows, ingress_rows=ingress_rows,
                    history_path=history_path, feedback_records=feedback_records,
                    authority_callback=lambda record: validate_decision_record(record, self._capability_manifest),
                    expected_policy_contract_sha256=accepted_records[0]["policy_contract_sha256"],
                )
                validate_frozen_policy_decisions(
                    staging / POLICY_DECISIONS_JSONL, decisions=validated_decisions,
                    expected_policy=self.policy, ingress_rows=ingress_rows,
                    runtime_history_path=history_path,
                )
                if feedback_records:
                    validate_frozen_policy_feedback(
                        staging / POLICY_FEEDBACK_JSONL, decisions=validated_decisions,
                        decision_records_path=staging / POLICY_DECISIONS_JSONL, require_complete=True,
                        ingress_rows=ingress_rows, runtime_history_path=history_path,
                    )
                if self._operational_context is not None:
                    operational_dir = self._operational_context["output_dir"]
                    # This is a separate retained group, outside legacy stage custody.
                    if operational_dir.resolve().is_relative_to(output_dir.resolve()):
                        raise NativePolicyRuntimeError("operational group overlaps legacy stage output")
                    header = copy.deepcopy(self._operational_context["header"])
                    operational_counts = {
                        "complete_decision_count": len(runtime_ordered),
                        "measurement_decision_count": len(ordered),
                        "excluded_decision_count": len(runtime_ordered) - len(ordered),
                        "runtime_feedback_count": self._next_feedback_seq - 1,
                        "measurement_feedback_count": len(feedback_records),
                        "excluded_feedback_count": self._next_feedback_seq - 1 - len(feedback_records),
                    }
                    header["counts"] = operational_counts
                    header["initial_state"] = copy.deepcopy(self._initial_policy_state)
                    header["adaptive_history"] = ({
                        "path": str((output_dir / RUNTIME_HISTORY_JSONL).resolve()),
                        "size_bytes": len(targets[RUNTIME_HISTORY_JSONL]),
                        "sha256": hashlib.sha256(targets[RUNTIME_HISTORY_JSONL]).hexdigest(),
                    } if self.policy == "adaptive_weights" else None)
                    header = payload_with_sha256_v1(header)
                    def complete_operational_records():
                        for state in runtime_ordered:
                            if state.decision_request is None:
                                raise NativePolicyRuntimeError("original native request was not captured")
                            yield build_native_occurrence_v1(
                                runtime_decision_seq=state.record["decision_seq"],
                                measurement=state.input_frame_key in canonical_frames,
                                decision_request=state.decision_request, accepted_record=state.accepted,
                                path=state.path, terminal=state.terminal,
                                issued_record_sha256=state.record["sha256"],
                            )
                    def original_authority(record):
                        accepted = record["accepted_record"]
                        projected = project_accepted_decision_v1(
                            accepted, canonical_trace_id=accepted["trace_id"],
                            publication_decision_seq=accepted["decision_seq"],
                            issued_record_sha256=record["issued_record_sha256"],
                        )
                        original, issued = reconstruct_original_decision_v1(projected)
                        if canonical_json_v1(original) != canonical_json_v1(accepted):
                            raise NativePolicyRuntimeError("original accepted inverse mismatch")
                        rebound = bind_native_decision_evidence(
                            issued, accepted["native_decision_evidence"], self._capability_manifest,
                        )
                        if rebound["sha256"] != record["accepted_record_sha256"]:
                            raise NativePolicyRuntimeError("original native-binding roundtrip mismatch")
                    operational_dir.mkdir(parents=True, exist_ok=True)
                    operational_descriptor = write_native_domain_v1(
                        operational_dir / NATIVE_OPERATIONAL_JSONL, header,
                        complete_operational_records(), original_authority_validator=original_authority,
                    )
                    if sum(len(payload) for payload in targets.values()) + operational_descriptor["size_bytes"] > MAX_ACCEPTANCE_AGGREGATE_BYTES_V1:
                        raise NativePolicyRuntimeError("retained operation exceeds aggregate byte budget")
                # Exclusive hard links publish validated bytes without an
                # overwrite race. Roll back only our own links on any failure.
                for name in targets:
                    target = output_dir / name
                    os.link(staging / name, target)
                    published.append((staging / name, target))
            except BaseException as exc:
                if self._operational_context is not None:
                    self._operational_error = f"native operational publication failed: {type(exc).__name__}: {exc}"
                for candidate, target in reversed(published):
                    if target.exists() and os.path.samefile(candidate, target):
                        target.unlink()
                raise
            finally:
                shutil.rmtree(staging)
            result = {
                "schema_version": 1,
                "artifact_kind": "vast_checkpoint_native_policy_promotion",
                "run_id": self.run_id,
                "arm_id": self.arm_id,
                "system": self.system,
                "scenario": self.scenario,
                "codec": self.codec,
                "policy": self.policy,
                "deadline_ms": self.deadline_ms,
                "runtime_decision_count": len(runtime_ordered),
                "accepted_decision_count": len(ordered),
                "excluded_noncohort_decision_count": (
                    len(runtime_ordered) - len(ordered)
                ),
                "feedback_count": len(feedback_records),
                "status": "accepted",
            }
            if operational_descriptor is not None:
                result["operational_domain"] = operational_descriptor
                result["operational_counts"] = operational_counts
            return result

    def enrich_runtime_events(
        self,
        events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
    ) -> tuple[dict[str, Any], ...]:
        """Attach exact native scheduling linkage to the already validated DAG rows."""

        with self._lock:
            by_frame_branch = {
                (state.input_frame_key, str(state.record["branch"])): state
                for state in self._states.values()
                if state.accepted is not None
            }
            enriched: list[dict[str, Any]] = []
            for source in events:
                row = copy.deepcopy(dict(source))
                input_key = str(row.get("input_frame_key", ""))
                stage = str(row.get("stage", ""))
                branch = str(row.get("branch_id", ""))
                state = by_frame_branch.get((input_key, branch))
                if stage in self.branches:
                    state = by_frame_branch.get((input_key, stage))
                if state is not None and stage in {str(state.record["branch"]), branch}:
                    accepted = state.accepted
                    if accepted is None:
                        raise NativePolicyRuntimeError(
                            "accepted native execution state lost its policy record"
                        )
                    resource = str(accepted["selected_resource"])
                    decision_id = str(accepted["decision_id"])
                    action = f"{self.policy}:{resource}:{decision_id}"
                    request = accepted["request"]
                    scheduler_binding = {
                        "scheduler_queue_depth": int(
                            request["candidates"][resource]["queue_depth"]
                        ),
                        "scheduler_estimated_cost_ms": self._policy_score(
                            accepted, resource
                        ),
                    }
                else:
                    base = stage.split("_", 1)[0]
                    resource = "nvdec" if base == "decode" else "cpu"
                    execution_id = str(row.get("execution_id", stage))
                    decision_id = f"{self.run_id}:fixed:{input_key}:{execution_id}"
                    action = f"{self.policy}:fixed_outside_analytics_scope:{resource}"
                    scheduler_binding = {}
                row.update(
                    {
                        "execution_resource": resource,
                        "scheduler_policy": self.policy,
                        "policy_action": action,
                        "policy_decision_id": decision_id,
                        "execution_binding_provenance": NATIVE_EXECUTION_BINDING_PROVENANCE,
                        "benchmark_system": self.system,
                        "benchmark_scenario": self.scenario,
                        "benchmark_codec": self.codec,
                        "benchmark_deadline_ms": self.deadline_ms,
                        **scheduler_binding,
                    }
                )
                enriched.append(row)
            return tuple(enriched)


def canonical_frames_from_events(
    events: tuple[dict[str, Any], ...] | list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in events:
        input_key = str(row.get("input_frame_key", ""))
        if not input_key:
            continue
        value = {
            "trace_id": row.get("trace_id"),
            "stream_id": row.get("stream_id"),
            "frame_id": row.get("frame_id"),
        }
        prior = result.get(input_key)
        if prior is not None and prior != value:
            raise NativePolicyRuntimeError(
                f"runtime event canonical frame identity drifted: {input_key}"
            )
        result[input_key] = value
    return result
