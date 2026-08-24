from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from checkpoint_gstreamer_publication_plan import (  # noqa: E402
    CheckpointGstreamerPublicationPlanError,
    build_checkpoint_gstreamer_publication_plan,
)
from test_backend_publication_output_receipt import (  # noqa: E402
    arm_contract,
    canonical_sha,
)
from test_backend_publication_runtime_authority import (  # noqa: E402
    build_fixture as build_runtime_authority,
)


PLAN_FIELDS = {
    "schema_version", "artifact_kind", "executable", "arm_contract_sha256",
    "runtime_authority_sha256", "full_publication_execution_binding",
    "coordinate", "common_identities", "inputs", "runtime_contract",
    "blockers", "plan_sha256",
}
BASE_BLOCKERS = {
    "runtime_authority_not_integrated_into_arm_contract_or_backend_grant",
    "gstreamer_publication_launcher_still_fail_closed",
    "real_kpp_hardware_execution_not_performed",
    "physical_kpp_dataset_and_source_not_verified",
    "physical_policy_capability_and_calibration_not_verified",
    "live_analytics_socket_endpoint_not_bound_or_peer_verified",
}


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def gstreamer_arm(
    root: Path, *, policy: str = "cpu_only",
) -> dict[str, object]:
    value = arm_contract(
        root,
        policy=policy,
        model_parity_acceptance_binding_sha256="5" * 64,
    )
    dispatch = value["dispatch_resolution"]
    runtime = value["runtime_inputs"]
    assert isinstance(dispatch, dict)
    assert isinstance(runtime, dict)
    dispatch["system"] = "gstreamer_custom"
    dispatch.pop("resolution_sha256")
    dispatch["resolution_sha256"] = canonical_sha(dispatch)
    runtime["system"] = "gstreamer_custom"
    value.pop("contract_sha256")
    value["contract_sha256"] = canonical_sha(value)
    return value


class CheckpointGstreamerPublicationPlanTests(unittest.TestCase):
    def test_cpu_plan_is_closed_self_hashed_pure_and_never_executable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            arm = gstreamer_arm(root)
            authority = build_runtime_authority(root)
            arm_before = copy.deepcopy(arm)
            authority_before = copy.deepcopy(authority)
            plan = build_checkpoint_gstreamer_publication_plan(arm, authority)

            self.assertEqual(set(plan), PLAN_FIELDS)
            self.assertEqual(plan["schema_version"], 1)
            self.assertEqual(
                plan["artifact_kind"],
                "vast_checkpoint_gstreamer_publication_execution_plan",
            )
            self.assertIs(plan["executable"], False)
            self.assertEqual(plan["arm_contract_sha256"], arm["contract_sha256"])
            self.assertEqual(
                plan["runtime_authority_sha256"], authority["authority_sha256"]
            )
            self.assertEqual(
                plan["full_publication_execution_binding"],
                arm["full_publication_execution_binding"],
            )
            self.assertEqual(
                set(plan["blockers"]),
                BASE_BLOCKERS | {"gstreamer_cpu_native_accepted_run_not_performed"},
            )
            self.assertEqual(plan["blockers"], sorted(plan["blockers"]))
            unsigned = {
                key: item for key, item in plan.items()
                if key != "plan_sha256"
            }
            self.assertEqual(plan["plan_sha256"], sha(unsigned))
            self.assertNotIn("argv", plan)
            self.assertNotIn("receipt", plan)
            self.assertEqual(arm, arm_before)
            self.assertEqual(authority, authority_before)

    def test_coordinate_runtime_content_and_arm_identities_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            arm = gstreamer_arm(root)
            authority = build_runtime_authority(root)
            plan = build_checkpoint_gstreamer_publication_plan(arm, authority)
            dispatch = arm["dispatch_resolution"]
            self.assertEqual(plan["coordinate"], {
                "system": "gstreamer_custom",
                "scenario": "checkpoint_video_dag_shared",
                "topology_kind": "shared_video_dag",
                "codec": "h264",
                "policy": "cpu_only",
                "deadline_ms": 50,
            })
            self.assertEqual(plan["common_identities"], {
                "backend_runtime_grant_sha256": arm[
                    "backend_runtime_grant_sha256"
                ],
                "resource_capability_grant_sha256": arm[
                    "resource_capability_grant_sha256"
                ],
                "model_parity_grant_sha256": arm[
                    "model_parity_grant_sha256"
                ],
                "model_parity_acceptance_binding_sha256": arm[
                    "model_parity_acceptance_binding_sha256"
                ],
                "identity_artifact_binding_sha256": arm[
                    "identity_artifact_binding_sha256"
                ],
                "runtime_binding_identity_sha256": dispatch[
                    "runtime_binding_identity_sha256"
                ],
                "cell_identity_sha256": dispatch["cell_identity_sha256"],
            })
            self.assertEqual(plan["runtime_contract"], {
                "cohort_topology_plan": authority["cohort_topology_plan"],
                "system_specific_launcher_input": authority[
                    "system_specific_launcher_input"
                ],
            })

    def test_non_cpu_policy_adds_exact_gpu_mixed_blocker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            arm = gstreamer_arm(root, policy="gpu_only")
            authority = build_runtime_authority(root, policy="gpu_only")
            plan = build_checkpoint_gstreamer_publication_plan(arm, authority)
            self.assertIn(
                "gstreamer_non_cpu_policy_requires_frozen_tensorrt_cuda_parity_bindings",
                plan["blockers"],
            )
            self.assertNotIn(
                "gstreamer_cpu_native_accepted_run_not_performed",
                plan["blockers"],
            )
            self.assertIs(plan["executable"], False)

    def test_cross_coordinate_common_identity_and_scenario_replay_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            arm = gstreamer_arm(root)
            authority = build_runtime_authority(root)
            mismatched = copy.deepcopy(authority)
            mismatched["model_parity_acceptance_binding_sha256"] = "f" * 64
            mismatched["authority_sha256"] = sha({
                key: item for key, item in mismatched.items()
                if key != "authority_sha256"
            })
            with self.assertRaisesRegex(
                CheckpointGstreamerPublicationPlanError,
                "parity acceptance",
            ):
                build_checkpoint_gstreamer_publication_plan(arm, mismatched)

            with self.assertRaisesRegex(
                CheckpointGstreamerPublicationPlanError,
                "policy.*cross-dispatch",
            ):
                build_checkpoint_gstreamer_publication_plan(
                    gstreamer_arm(root, policy="gpu_only"), authority
                )

            replayed = copy.deepcopy(arm)
            replayed["runtime_inputs"]["scenario"] = (
                "checkpoint_independent_processes_baseline"
            )
            replayed.pop("contract_sha256")
            replayed["contract_sha256"] = canonical_sha(replayed)
            with self.assertRaisesRegex(
                CheckpointGstreamerPublicationPlanError,
                "scenario/topology",
            ):
                build_checkpoint_gstreamer_publication_plan(
                    replayed, authority
                )


if __name__ == "__main__":
    unittest.main()
