from __future__ import annotations

import json
import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (  # noqa: E402
    ContractError,
    frozen_policy_requires_feedback,
    validate_frozen_policy_feedback,
    validate_policy_decisions,
)
from checkpoint_native_policy_runtime import (  # noqa: E402
    NativePolicyRuntimeCoordinator,
    NativePolicyRuntimeError,
    assess_gstreamer_native_policy_execution_manifest,
    require_exact_native_cpu_capability_bindings,
)
from publication_policy_contract import (  # noqa: E402
    ANALYTICS_BRANCHES,
    POLICIES,
    POLICY_SCOPE,
    PUBLISHABLE_SYSTEMS,
    RESOURCES,
    build_policy_contract,
    policy_contract_identity,
    select_static_hybrid_map,
)


def capability_manifest() -> dict:
    contract_sha = policy_contract_identity(build_policy_contract())["sha256"]
    systems: dict[str, dict] = {}
    for system_index, system in enumerate(PUBLISHABLE_SYSTEMS, start=1):
        branches: dict[str, dict] = {}
        for branch_index, branch in enumerate(ANALYTICS_BRANCHES, start=1):
            bindings: dict[str, dict] = {}
            for resource_index, resource in enumerate(RESOURCES, start=1):
                marker = system_index * 100 + branch_index * 10 + resource_index
                runtime_identity = {
                    "runtime_backend": (
                        "openvino_dlstreamer" if resource == "cpu" else "cuda_tensorrt"
                    ),
                    "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
                    "gpu_id": None if resource == "cpu" else 0,
                    "worker_image_digest": "sha256:" + f"{marker + 2:064x}",
                    "implementation_version": f"{system}-{branch}-{resource}-implementation-v3",
                    "terminal_detector": f"{system}-{branch}-{resource}-native-detector-v1",
                    "terminal_backend": (
                        "openvino-dlstreamer:gvadetect;device=CPU"
                        if resource == "cpu"
                        else "cuda-tensorrt:nvinfer;device=NVIDIA_CUDA:0"
                    ),
                }
                bindings[resource] = {
                    "status": "implemented_and_native_evidence_bound",
                    "implementation_id": f"{system}-{branch}-{resource}-runtime-v1",
                    "implementation_sha256": f"{marker:064x}",
                    "runtime_binding": f"{system}:{branch}:{resource}:worker",
                    "runtime_identity": runtime_identity,
                    **runtime_identity,
                    "native_evidence": {
                        "status": "accepted_native_runtime_emitter",
                        "telemetry_source": "native",
                        "emitter_id": f"{system}-{branch}-{resource}-emitter-v1",
                        "emitter_sha256": f"{marker + 1:064x}",
                        "implementation_id_field": "implementation_id",
                        "resource_field": "selected_resource",
                    },
                }
            branches[branch] = bindings
        systems[system] = {"branches": branches}
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_capability_manifest",
        "policy_scope": POLICY_SCOPE,
        "policy_contract_sha256": contract_sha,
        "systems": systems,
    }


def calibration(manifest: dict, system: str = "gstreamer_custom") -> dict:
    costs = {
        "plate_number": {"cpu": (2.0, 0.0), "gpu": (9.0, 0.5)},
        "vehicle_type": {"cpu": (3.0, 0.0), "gpu": (8.0, 0.5)},
        "damage": {"cpu": (9.0, 0.0), "gpu": (2.0, 0.5)},
        "foreign_object": {"cpu": (8.0, 0.0), "gpu": (3.0, 0.5)},
    }
    rows: dict[str, dict] = {}
    bindings = manifest["systems"][system]["branches"]
    for branch in ANALYTICS_BRANCHES:
        rows[branch] = {}
        for resource in RESOURCES:
            service_ms, transfer_ms = costs[branch][resource]
            rows[branch][resource] = {
                "implementation_id": bindings[branch][resource]["implementation_id"],
                "service_ms": service_ms,
                "transfer_ms": transfer_ms,
                "samples": 30,
            }
    return {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_calibration",
        "system": system,
        "policy_contract_sha256": manifest["policy_contract_sha256"],
        "costs": rows,
    }


def coordinator(policy: str) -> NativePolicyRuntimeCoordinator:
    manifest = capability_manifest()
    profile = calibration(manifest)
    static_map = select_static_hybrid_map("gstreamer_custom", profile, manifest)
    return NativePolicyRuntimeCoordinator(
        run_id="run-native-policy-0001",
        arm_id=f"arm-native-policy-{policy}-0001",
        system="gstreamer_custom",
        scenario="checkpoint_video_dag_shared",
        codec="h265",
        policy=policy,
        deadline_ms=100.0,
        branches=ANALYTICS_BRANCHES,
        capability_manifest=manifest,
        calibration=profile,
        static_hybrid_map=static_map if policy == "static_hybrid" else None,
    )


def request_message(
    *,
    branch: str = "plate_number",
    frame_id: int = 1,
    run_id: str = "run-native-policy-0001",
) -> dict:
    return {
        "schema_version": 1,
        "message_type": "decision_request",
        "run_id": run_id,
        "worker_id": "worker-shared-0001",
        "input_frame_key": f"dataset:0:source:{frame_id}:1000",
        "trace_id": f"run-native-policy-0001:0:{frame_id}",
        "stream_id": 0,
        "frame_id": frame_id,
        "transport_pts_ns": frame_id * 1000,
        "branch": branch,
        "arrival_ms": 990.0 + frame_id,
        "decision_time_ms": 1000.0 + frame_id,
        "feature_observed_timestamp_ms": 999.0 + frame_id,
        "queue_depths": {"cpu": 0, "gpu": 0},
    }


def path_message(
    response: dict,
    *,
    request: dict,
    resource: str | None = None,
    system: str = "gstreamer_custom",
) -> dict:
    selected = resource or str(response["selected_resource"])
    manifest = capability_manifest()
    binding = manifest["systems"][system]["branches"][request["branch"]][selected]
    return {
        "schema_version": 1,
        "message_type": "path_enter",
        "run_id": request["run_id"],
        "worker_id": request["worker_id"],
        "decision_id": response["decision_id"],
        "input_frame_key": request["input_frame_key"],
        "branch": request["branch"],
        "transport_pts_ns": request["transport_pts_ns"],
        "selected_resource": selected,
        "implementation_id": binding["implementation_id"],
        "emitter_id": binding["native_evidence"]["emitter_id"],
        "emitter_sha256": binding["native_evidence"]["emitter_sha256"],
        "event_id": f"native-path-event-{request['branch']}-{selected}-{request['frame_id']}",
        "timestamp_ms": request["decision_time_ms"] + 1.0,
    }


def terminal_message(
    response: dict,
    *,
    request: dict,
    system: str = "gstreamer_custom",
) -> dict:
    resource = str(response["selected_resource"])
    binding = capability_manifest()["systems"][system]["branches"][
        request["branch"]
    ][resource]
    return {
        "schema_version": 1,
        "message_type": "terminal",
        "run_id": request["run_id"],
        "worker_id": request["worker_id"],
        "decision_id": response["decision_id"],
        "input_frame_key": request["input_frame_key"],
        "branch": request["branch"],
        "transport_pts_ns": request["transport_pts_ns"],
        "selected_resource": resource,
        "terminal_status": "completed",
        "terminal_timestamp_ms": request["decision_time_ms"] + 10.0,
        "actual_service_ms": 9.0,
        "detector": binding["terminal_detector"],
        "backend": binding["terminal_backend"],
    }


class NativePolicyRuntimeCoordinatorTests(unittest.TestCase):
    def test_all_four_publishable_systems_use_the_same_terminal_bound_coordinator(self) -> None:
        manifest = capability_manifest()
        for system in PUBLISHABLE_SYSTEMS:
            with self.subTest(system=system):
                run_id = f"run-{system}-policy-0001"
                runtime = NativePolicyRuntimeCoordinator(
                    run_id=run_id,
                    arm_id=f"arm-{system}-policy-cpu-0001",
                    system=system,
                    scenario="checkpoint_video_dag_shared",
                    codec="h264",
                    policy="cpu_only",
                    deadline_ms=50.0,
                    branches=ANALYTICS_BRANCHES,
                    capability_manifest=manifest,
                    calibration=calibration(manifest, system),
                )
                request = request_message(run_id=run_id)
                response = runtime.handle_message(request["worker_id"], request)
                runtime.handle_message(
                    request["worker_id"],
                    path_message(response, request=request, system=system),
                )
                terminal = runtime.handle_message(
                    request["worker_id"],
                    terminal_message(response, request=request, system=system),
                )
                self.assertTrue(terminal["accepted"])

    def test_deepstream_uses_the_same_frozen_native_policy_coordinator_contract(self) -> None:
        manifest = capability_manifest()
        profile = calibration(manifest)
        profile["system"] = "deepstream"
        bindings = manifest["systems"]["deepstream"]["branches"]
        for branch in ANALYTICS_BRANCHES:
            for resource in RESOURCES:
                profile["costs"][branch][resource]["implementation_id"] = bindings[branch][resource]["implementation_id"]
        runtime = NativePolicyRuntimeCoordinator(
            run_id="run-deepstream-policy-0001",
            arm_id="arm-deepstream-policy-cpu-0001",
            system="deepstream",
            scenario="checkpoint_video_dag_shared",
            codec="h264",
            policy="cpu_only",
            deadline_ms=50.0,
            branches=ANALYTICS_BRANCHES,
            capability_manifest=manifest,
            calibration=profile,
        )
        self.assertEqual(runtime.system, "deepstream")
        self.assertEqual(runtime.policy, "cpu_only")

    def test_current_openvino_manifest_blocks_every_nvidia_gpu_policy_path(self) -> None:
        manifest = yaml.safe_load(
            (ROOT / "configs" / "checkpoint_analytics_models_openvino.yaml").read_text(
                encoding="utf-8"
            )
        )
        assessment = assess_gstreamer_native_policy_execution_manifest(manifest)
        self.assertFalse(assessment["passed"])
        self.assertEqual(assessment["eligible_policies"], ["cpu_only"])
        self.assertEqual(
            assessment["nvidia_gpu_ready_branches"],
            [],
        )
        self.assertTrue(
            all(
                f"runtime_capability:{branch}:nvidia_gpu_binding_missing"
                in assessment["blockers"]
                for branch in ANALYTICS_BRANCHES
            )
        )

    def test_gvadetect_device_gpu_cannot_be_relabelled_as_nvidia_cuda(self) -> None:
        original = yaml.safe_load(
            (ROOT / "configs" / "checkpoint_analytics_models_openvino.yaml").read_text(
                encoding="utf-8"
            )
        )
        manifest = copy.deepcopy(original)
        for branch in ANALYTICS_BRANCHES:
            cpu = copy.deepcopy(original["branches"][branch])
            gpu = copy.deepcopy(cpu)
            gpu["device"] = "GPU"
            gpu["backend"] = "openvino_dlstreamer"
            manifest["branches"][branch] = {"resources": {"cpu": cpu, "gpu": gpu}}
        assessment = assess_gstreamer_native_policy_execution_manifest(manifest)
        self.assertFalse(assessment["passed"])
        self.assertTrue(
            all(
                f"runtime_capability:{branch}:openvino_gpu_is_not_nvidia_cuda"
                in assessment["blockers"]
                for branch in ANALYTICS_BRANCHES
            )
        )

    def test_cpu_capability_must_match_loaded_binary_and_model_identity(self) -> None:
        manifest = capability_manifest()
        analytics: dict[str, dict[str, str]] = {}
        binary_payload = b"native-policy-worker-contract-test"
        binary_sha = __import__("hashlib").sha256(binary_payload).hexdigest()
        for index, branch in enumerate(ANALYTICS_BRANCHES, start=1):
            model_sha = f"{index:064x}"
            weights_sha = f"{index + 10:064x}"
            analytics[branch] = {
                "factory": "gvadetect",
                "device": "CPU",
                "model_sha256": model_sha,
                "weights_sha256": weights_sha,
                "detector_id": f"native-{branch}-detector-v1",
            }
            cpu = manifest["systems"]["gstreamer_custom"]["branches"][branch]["cpu"]
            cpu["implementation_id"] = (
                f"gstreamer-custom-openvino-cpu-v1:{branch}:gvadetect:"
                f"{model_sha}:{weights_sha}"
            )
            cpu["native_evidence"]["emitter_id"] = (
                f"vast-native-gst-policy-path-v1:{branch}:cpu"
            )
            cpu["native_evidence"]["emitter_sha256"] = binary_sha
            cpu["runtime_backend"] = "openvino_dlstreamer"
            cpu["device_api"] = "CPU"
            cpu["terminal_detector"] = (
                f"native-{branch}-detector-v1;model_sha256={model_sha};"
                f"weights_sha256={weights_sha}"
            )
            cpu["terminal_backend"] = "openvino-dlstreamer:gvadetect;device=CPU"
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "vast_native_gst_probe"
            binary.write_bytes(binary_payload)
            require_exact_native_cpu_capability_bindings(
                binary=binary,
                analytics_bindings=analytics,
                capability_manifest=manifest,
            )
            manifest["systems"]["gstreamer_custom"]["branches"]["damage"]["cpu"][
                "native_evidence"
            ]["emitter_sha256"] = "f" * 64
            with self.assertRaisesRegex(NativePolicyRuntimeError, "loaded worker executable"):
                require_exact_native_cpu_capability_bindings(
                    binary=binary,
                    analytics_bindings=analytics,
                    capability_manifest=manifest,
                )
    def test_all_seven_policies_require_native_path_and_terminal_before_promotion(self) -> None:
        for policy in POLICIES:
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp:
                runtime = coordinator(policy)
                request = request_message()
                response = runtime.handle_message(request["worker_id"], request)
                self.assertEqual(response["message_type"], "decision_response")
                self.assertIn(response["selected_resource"], RESOURCES)
                runtime.handle_message(request["worker_id"], path_message(response, request=request))
                runtime.handle_message(request["worker_id"], terminal_message(response, request=request))
                summary = runtime.promote(
                    Path(tmp),
                    canonical_frames={
                        request["input_frame_key"]: {
                            "trace_id": "canonical-trace-0001",
                            "stream_id": 0,
                            "frame_id": 7,
                        }
                    },
                )
                self.assertEqual(summary["accepted_decision_count"], 1)
                decisions = validate_policy_decisions(
                    Path(tmp) / "policy_decisions.csv",
                    require_labeled_provenance=True,
                    require_full_trace=True,
                    require_causal_trace=True,
                )
                self.assertTrue(bool(decisions["causal_policy_claim_eligible"].all()))
                canonical = [
                    json.loads(line)
                    for line in (Path(tmp) / "publication_policy_decisions.jsonl")
                    .read_text(encoding="utf-8")
                    .splitlines()
                ]
                self.assertEqual(canonical[0]["record_status"], "accepted_native_runtime_decision")
                if policy == "adaptive_weights":
                    self.assertTrue((Path(tmp) / "publication_policy_feedback.jsonl").is_file())

    def test_adaptive_feedback_uses_application_order_and_is_mandatory(self) -> None:
        self.assertTrue(frozen_policy_requires_feedback("adaptive_weights"))
        self.assertTrue(
            all(
                not frozen_policy_requires_feedback(policy)
                for policy in POLICIES
                if policy != "adaptive_weights"
            )
        )
        runtime = coordinator("adaptive_weights")
        first_request = request_message(frame_id=1)
        second_request = request_message(branch="damage", frame_id=2)
        first_response = runtime.handle_message(first_request["worker_id"], first_request)
        second_response = runtime.handle_message(second_request["worker_id"], second_request)
        runtime.handle_message(
            first_request["worker_id"],
            path_message(first_response, request=first_request),
        )
        runtime.handle_message(
            second_request["worker_id"],
            path_message(second_response, request=second_request),
        )
        # Apply terminal feedback out of decision order; the JSONL must preserve
        # the coordinator's actual state-transition order, not decision_seq order.
        runtime.handle_message(
            second_request["worker_id"],
            terminal_message(second_response, request=second_request),
        )
        runtime.handle_message(
            first_request["worker_id"],
            terminal_message(first_response, request=first_request),
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            runtime.promote(
                output,
                canonical_frames={
                    first_request["input_frame_key"]: {
                        "trace_id": "canonical-trace-0001",
                        "stream_id": 0,
                        "frame_id": 1,
                    },
                    second_request["input_frame_key"]: {
                        "trace_id": "canonical-trace-0002",
                        "stream_id": 0,
                        "frame_id": 2,
                    },
                },
            )
            decisions = validate_policy_decisions(
                output / "policy_decisions.csv",
                require_labeled_provenance=True,
                require_full_trace=True,
                require_causal_trace=True,
            )
            feedback_path = output / "publication_policy_feedback.jsonl"
            feedback = validate_frozen_policy_feedback(
                feedback_path,
                decisions=decisions,
                require_complete=True,
            )
            self.assertEqual(
                list(feedback["decision_id"]),
                [second_response["decision_id"], first_response["decision_id"]],
            )

            feedback_path.unlink()
            with self.assertRaisesRegex(ContractError, "required frozen policy evidence is missing"):
                validate_frozen_policy_feedback(
                    feedback_path,
                    decisions=decisions,
                    require_complete=True,
                )

    def test_unselected_path_is_rejected_and_cannot_be_relabelled(self) -> None:
        runtime = coordinator("cpu_only")
        request = request_message()
        response = runtime.handle_message(request["worker_id"], request)
        self.assertEqual(response["selected_resource"], "cpu")
        with self.assertRaisesRegex(NativePolicyRuntimeError, "unselected execution path"):
            runtime.handle_message(
                request["worker_id"],
                path_message(response, request=request, resource="gpu"),
            )

    def test_terminal_without_native_path_and_duplicate_path_fail_closed(self) -> None:
        runtime = coordinator("heft")
        request = request_message()
        response = runtime.handle_message(request["worker_id"], request)
        with self.assertRaisesRegex(NativePolicyRuntimeError, "no native path entry"):
            runtime.handle_message(request["worker_id"], terminal_message(response, request=request))
        runtime.handle_message(request["worker_id"], path_message(response, request=request))
        with self.assertRaisesRegex(NativePolicyRuntimeError, "duplicate native path entry"):
            runtime.handle_message(request["worker_id"], path_message(response, request=request))

    def test_wrong_terminal_device_and_pending_decision_block_promotion(self) -> None:
        runtime = coordinator("gpu_only")
        request = request_message()
        response = runtime.handle_message(request["worker_id"], request)
        runtime.handle_message(request["worker_id"], path_message(response, request=request))
        terminal = terminal_message(response, request=request)
        terminal["backend"] = "openvino-dlstreamer:gvadetect;device=GPU"
        with self.assertRaisesRegex(NativePolicyRuntimeError, "terminal identity"):
            runtime.handle_message(request["worker_id"], terminal)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(NativePolicyRuntimeError, "unterminated native decisions"):
                runtime.promote(Path(tmp), canonical_frames={})

    def test_message_identity_and_exact_schema_are_enforced(self) -> None:
        runtime = coordinator("heft")
        wrong = request_message()
        wrong["run_id"] = "another-run-0001"
        with self.assertRaisesRegex(NativePolicyRuntimeError, "run_id"):
            runtime.handle_message(wrong["worker_id"], wrong)
        extra = request_message()
        extra["synthetic_resource"] = "gpu"
        with self.assertRaisesRegex(NativePolicyRuntimeError, "fields have drifted"):
            runtime.handle_message(extra["worker_id"], extra)


if __name__ == "__main__":
    unittest.main()
