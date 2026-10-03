from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_policy_contract import (  # noqa: E402
    ANALYTICS_BRANCHES,
    POLICIES,
    POLICY_SCOPE,
    PUBLISHABLE_SYSTEMS,
    RESOURCES,
    PolicyContractError,
    PolicyEngine,
    assess_capability_manifest,
    bind_native_decision_evidence,
    build_policy_contract,
    policy_contract_identity,
    replay_decision,
    select_ready_task,
    select_static_hybrid_map,
    validate_decision_record,
)


def valid_capability_manifest() -> dict:
    contract_sha256 = policy_contract_identity(build_policy_contract())["sha256"]
    systems: dict[str, dict] = {}
    for system_index, system in enumerate(PUBLISHABLE_SYSTEMS, start=1):
        branches: dict[str, dict] = {}
        for branch_index, branch in enumerate(ANALYTICS_BRANCHES, start=1):
            bindings: dict[str, dict] = {}
            for resource_index, resource in enumerate(RESOURCES, start=1):
                marker = system_index * 100 + branch_index * 10 + resource_index
                runtime_identity = {
                    "runtime_backend": f"{system}.{resource}.native.backend.v3",
                    "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
                    "gpu_id": None if resource == "cpu" else 0,
                    "worker_image_digest": "sha256:" + f"{marker + 2:064x}",
                    "implementation_version": f"{system}-{branch}-{resource}-implementation-v3",
                    "terminal_detector": f"opaque-{branch}-detector-v3",
                    "terminal_backend": (
                        "analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=CompiledModel;device=CPU:fixture-cpu"
                        if resource == "cpu"
                        else "analytics-execution:tensorrt_cuda;runtime=TensorRT;native_api=enqueueV3;device=NVIDIA_CUDA:GPU-fixture"
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
        "policy_contract_sha256": contract_sha256,
        "systems": systems,
    }


def calibration(system: str, manifest: dict) -> dict:
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


def decision_request(manifest: dict, system: str, *, branch: str = "plate_number") -> dict:
    bindings = manifest["systems"][system]["branches"][branch]
    return {
        "decision_id": "decision-0001",
        "decision_seq": 1,
        "trace_id": "trace-0001",
        "branch": branch,
        "arrival_ms": 1.0,
        "decision_time_ms": 10.0,
        "deadline_ms": 25.0,
        "rank_u_ms": 7.0,
        "candidates": {
            "cpu": {
                "allowed": True,
                "implementation_id": bindings["cpu"]["implementation_id"],
                "available_ms": 10.0,
                "queue_depth": 1,
                "estimated_service_ms": 8.0,
                "transfer_ms": 0.0,
            },
            "gpu": {
                "allowed": True,
                "implementation_id": bindings["gpu"]["implementation_id"],
                "available_ms": 12.0,
                "queue_depth": 0,
                "estimated_service_ms": 2.0,
                "transfer_ms": 1.0,
            },
        },
    }


def native_evidence(record: dict, manifest: dict) -> dict:
    binding = manifest["systems"][record["system"]]["branches"][record["branch"]][
        record["selected_resource"]
    ]
    return {
        "telemetry_source": "native",
        "event_id": "native-policy-event-0001",
        "decision_id": record["decision_id"],
        "system": record["system"],
        "branch": record["branch"],
        "selected_resource": record["selected_resource"],
        "implementation_id": record["selected_implementation_id"],
        "emitter_id": binding["native_evidence"]["emitter_id"],
        "emitter_sha256": binding["native_evidence"]["emitter_sha256"],
    }


class PublicationPolicyContractTests(unittest.TestCase):
    def test_contract_is_frozen_complete_and_digest_is_deterministic(self) -> None:
        first = build_policy_contract()
        second = build_policy_contract()

        self.assertEqual(first, second)
        self.assertEqual(first["policy_scope"], "analytics_only")
        self.assertEqual(tuple(first["analytics_branches"]), ANALYTICS_BRANCHES)
        self.assertEqual(tuple(first["resources"]), RESOURCES)
        self.assertEqual(tuple(first["policies"]), POLICIES)
        self.assertEqual(len(first["policy_definitions"]), 7)
        self.assertEqual(
            policy_contract_identity(first),
            policy_contract_identity(second),
        )
        self.assertRegex(policy_contract_identity(first)["sha256"], r"^[0-9a-f]{64}$")

    def test_capabilities_require_every_real_cpu_gpu_binding_and_native_emitter(self) -> None:
        manifest = valid_capability_manifest()
        self.assertTrue(assess_capability_manifest(manifest)["passed"])

        missing_gpu = copy.deepcopy(manifest)
        del missing_gpu["systems"]["deepstream"]["branches"]["damage"]["gpu"]
        assessment = assess_capability_manifest(missing_gpu)
        self.assertFalse(assessment["passed"])
        self.assertIn("capability:deepstream:damage:gpu:missing", assessment["blockers"])

        label_only = copy.deepcopy(manifest)
        label_only["systems"]["savant"]["branches"]["vehicle_type"]["cpu"][
            "implementation_id"
        ] = "cpu"
        assessment = assess_capability_manifest(label_only)
        self.assertFalse(assessment["passed"])
        self.assertIn(
            "capability:savant:vehicle_type:cpu:implementation_id_not_real",
            assessment["blockers"],
        )

        not_native = copy.deepcopy(manifest)
        not_native["systems"]["openvino_gva"]["branches"]["foreign_object"]["gpu"][
            "native_evidence"
        ]["telemetry_source"] = "derived"
        assessment = assess_capability_manifest(not_native)
        self.assertFalse(assessment["passed"])
        self.assertIn(
            "capability:openvino_gva:foreign_object:gpu:native_evidence_not_bound",
            assessment["blockers"],
        )

        missing_identity = copy.deepcopy(manifest)
        del missing_identity["systems"]["gstreamer_custom"]["branches"]["damage"]["cpu"][
            "runtime_identity"
        ]
        assessment = assess_capability_manifest(missing_identity)
        self.assertFalse(assessment["passed"])
        self.assertIn(
            "capability:gstreamer_custom:damage:cpu:runtime_identity_fields_invalid",
            assessment["blockers"],
        )

        projection_drift = copy.deepcopy(manifest)
        projection_drift["systems"]["deepstream"]["branches"]["plate_number"]["gpu"][
            "terminal_backend"
        ] += ":drift"
        assessment = assess_capability_manifest(projection_drift)
        self.assertFalse(assessment["passed"])
        self.assertIn(
            "capability:deepstream:plate_number:gpu:runtime_identity_projection_mismatch",
            assessment["blockers"],
        )

        cpu_on_gpu = copy.deepcopy(manifest)
        cpu_on_gpu["systems"]["savant"]["branches"]["vehicle_type"]["cpu"][
            "runtime_identity"
        ]["gpu_id"] = 0
        cpu_on_gpu["systems"]["savant"]["branches"]["vehicle_type"]["cpu"]["gpu_id"] = 0
        assessment = assess_capability_manifest(cpu_on_gpu)
        self.assertFalse(assessment["passed"])
        self.assertIn(
            "capability:savant:vehicle_type:cpu:runtime_identity_resource_mismatch",
            assessment["blockers"],
        )

        abbreviated = copy.deepcopy(manifest)
        abbreviated_binding = abbreviated["systems"]["deepstream"]["branches"][
            "plate_number"
        ]["gpu"]
        abbreviated_backend = (
            "analytics-execution:tensorrt_cuda;device=NVIDIA_CUDA:0"
        )
        abbreviated_binding["runtime_identity"]["terminal_backend"] = abbreviated_backend
        abbreviated_binding["terminal_backend"] = abbreviated_backend
        assessment = assess_capability_manifest(abbreviated)
        self.assertFalse(assessment["passed"])
        self.assertIn(
            "capability:deepstream:plate_number:gpu:runtime_identity_resource_mismatch",
            assessment["blockers"],
        )

    def test_static_hybrid_calibration_is_exhaustive_mixed_and_deterministic(self) -> None:
        manifest = valid_capability_manifest()
        profile = calibration("gstreamer_custom", manifest)

        first = select_static_hybrid_map("gstreamer_custom", profile, manifest)
        second = select_static_hybrid_map("gstreamer_custom", profile, manifest)

        self.assertEqual(first, second)
        self.assertEqual(
            first["placement"],
            {
                "plate_number": "cpu",
                "vehicle_type": "cpu",
                "damage": "gpu",
                "foreign_object": "gpu",
            },
        )
        self.assertEqual(set(first["placement"].values()), {"cpu", "gpu"})
        self.assertEqual(first["candidate_count"], 14)
        self.assertRegex(first["sha256"], r"^[0-9a-f]{64}$")

        insufficient = copy.deepcopy(profile)
        insufficient["costs"]["damage"]["gpu"]["samples"] = 29
        with self.assertRaisesRegex(PolicyContractError, "at least 30 samples"):
            select_static_hybrid_map("gstreamer_custom", insufficient, manifest)

    def test_all_seven_policies_emit_replayable_but_unaccepted_records(self) -> None:
        manifest = valid_capability_manifest()
        static_map = select_static_hybrid_map(
            "gstreamer_custom",
            calibration("gstreamer_custom", manifest),
            manifest,
        )
        expected = {
            "cpu_only": "cpu",
            "gpu_only": "gpu",
            "static_hybrid": "cpu",
            "heft": "gpu",
            "deadline_aware_heft": "gpu",
            "queue_aware_edf": "gpu",
            "adaptive_weights": "gpu",
        }

        for policy in POLICIES:
            with self.subTest(policy=policy):
                engine = PolicyEngine(
                    policy=policy,
                    system="gstreamer_custom",
                    capability_manifest=manifest,
                    static_hybrid_map=static_map if policy == "static_hybrid" else None,
                )
                engine.reset("arm-0001")
                record = engine.decide(decision_request(manifest, "gstreamer_custom"))
                self.assertEqual(record["selected_resource"], expected[policy])
                self.assertEqual(record["policy_scope"], POLICY_SCOPE)
                self.assertEqual(record["record_status"], "replayable_not_runtime_accepted")
                self.assertTrue(replay_decision(record, manifest)["passed"])
                self.assertFalse(validate_decision_record(record, manifest)["passed"])
                self.assertIn(
                    "native_decision_evidence_missing",
                    validate_decision_record(record, manifest)["blockers"],
                )

    def test_native_evidence_binding_is_exact_and_turns_record_acceptable(self) -> None:
        manifest = valid_capability_manifest()
        engine = PolicyEngine(
            policy="gpu_only",
            system="deepstream",
            capability_manifest=manifest,
        )
        engine.reset("arm-native")
        record = engine.decide(decision_request(manifest, "deepstream"))

        accepted = bind_native_decision_evidence(record, native_evidence(record, manifest), manifest)
        assessment = validate_decision_record(accepted, manifest)
        self.assertTrue(assessment["passed"], assessment["blockers"])
        self.assertEqual(accepted["record_status"], "accepted_native_runtime_decision")

        wrong = native_evidence(record, manifest)
        wrong["selected_resource"] = "cpu"
        with self.assertRaisesRegex(PolicyContractError, "selected_resource"):
            bind_native_decision_evidence(record, wrong, manifest)

    def test_ready_task_selection_and_resource_ties_are_stable(self) -> None:
        tasks = [
            {
                "trace_id": "trace-0002",
                "branch": "damage",
                "arrival_ms": 1.0,
                "deadline_ms": 20.0,
                "rank_u_ms": 9.0,
            },
            {
                "trace_id": "trace-0001",
                "branch": "plate_number",
                "arrival_ms": 2.0,
                "deadline_ms": 10.0,
                "rank_u_ms": 1.0,
            },
        ]
        self.assertEqual(select_ready_task("queue_aware_edf", tasks)["trace_id"], "trace-0001")
        self.assertEqual(select_ready_task("heft", tasks)["trace_id"], "trace-0002")

        manifest = valid_capability_manifest()
        request = decision_request(manifest, "savant")
        request["candidates"]["cpu"].update(
            available_ms=10.0,
            queue_depth=0,
            estimated_service_ms=4.0,
            transfer_ms=0.0,
        )
        request["candidates"]["gpu"].update(
            available_ms=10.0,
            queue_depth=0,
            estimated_service_ms=4.0,
            transfer_ms=0.0,
        )
        engine = PolicyEngine(policy="heft", system="savant", capability_manifest=manifest)
        engine.reset("arm-tie-0001")
        self.assertEqual(engine.decide(request)["selected_resource"], "cpu")

    def test_adaptive_feedback_is_bounded_and_reset_per_arm(self) -> None:
        manifest = valid_capability_manifest()
        engine = PolicyEngine(
            policy="adaptive_weights",
            system="openvino_gva",
            capability_manifest=manifest,
        )
        engine.reset("arm-adaptive-1")
        record = engine.decide(decision_request(manifest, "openvino_gva"))
        feedback = engine.feedback(record, actual_service_ms=3.0, completed_at_ms=30.0)
        self.assertEqual(feedback["outcome"], "late")
        self.assertAlmostEqual(feedback["state_after"]["weights"]["gpu"], 1.002)
        self.assertEqual(
            feedback["state_after"]["service_ewma_ms"]["plate_number"]["gpu"],
            3.0,
        )
        with self.assertRaisesRegex(PolicyContractError, "already applied"):
            engine.feedback(record, actual_service_ms=3.0, completed_at_ms=30.0)

        engine.reset("arm-adaptive-2")
        state = engine.state_snapshot()
        self.assertEqual(state["weights"], {"cpu": 1.0, "gpu": 1.0})
        self.assertEqual(state["service_ewma_ms"], {})

    def test_candidate_binding_and_replay_fail_closed_on_drift(self) -> None:
        manifest = valid_capability_manifest()
        engine = PolicyEngine(policy="heft", system="deepstream", capability_manifest=manifest)
        engine.reset("arm-drift")
        request = decision_request(manifest, "deepstream")
        request["candidates"]["gpu"]["implementation_id"] = "invented-gpu-label"
        with self.assertRaisesRegex(PolicyContractError, "capability binding"):
            engine.decide(request)

        request = decision_request(manifest, "deepstream")
        record = engine.decide(request)
        drifted = copy.deepcopy(record)
        drifted["selected_resource"] = "cpu"
        assessment = replay_decision(drifted, manifest)
        self.assertFalse(assessment["passed"])
        self.assertIn("decision_record_sha256_mismatch", assessment["blockers"])


if __name__ == "__main__":
    unittest.main()
