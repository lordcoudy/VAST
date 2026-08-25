from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from publication_policy_contract import (  # noqa: E402
    POLICIES,
    policy_contract_identity,
)
from publication_matrix import (  # noqa: E402
    DATASET_BY_CODEC,
    FULL_RESOURCE_PUBLICATION_SCOPE,
    build_full_publication_matrix,
    publication_matrix_identity,
    validate_full_publication_readiness,
)
from backend_runtime_grant import backend_runtime_grant_from_identity_artifacts  # noqa: E402
from model_parity_grant import model_parity_grant_from_identity_artifacts  # noqa: E402
from test_model_parity_grant import identity as parity_identity  # noqa: E402
from test_backend_runtime_grant import v2_identity, v3_identity  # noqa: E402


def load_config() -> dict:
    with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
        return yaml.safe_load(source)


def resource_capability_grant() -> dict:
    grant = {
        "schema_version": 1,
        "artifact_kind": "vast_verified_pre_run_resource_capability_grant",
        "status": "accepted_pre_run_resource_capability_qualification",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": "a" * 64,
        "qualification_receipt": {
            "path": "artifacts/checkpoint_full_resource_qualification_receipt.json",
            "size_bytes": 101,
            "sha256": "b" * 64,
        },
        "capability_manifest": {
            "path": "artifacts/checkpoint_full_resource_capability_manifest.json",
            "size_bytes": 202,
            "sha256": "c" * 64,
        },
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    grant["grant_sha256"] = hashlib.sha256(
        json.dumps(
            grant,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return grant


class PublicationMatrixTests(unittest.TestCase):
    def test_authenticated_q4_protocol_grant_unlocks_exact_5600_runtime_arms(self) -> None:
        grant = backend_runtime_grant_from_identity_artifacts(v3_identity())
        assessment = validate_full_publication_readiness(
            load_config(), backend_runtime_grant=grant,
        )
        self.assertTrue(
            assessment["backend_launcher_output_receipt_protocol_ready"]
        )
        self.assertEqual(
            assessment["runtime_cell_assessment"]["ready_arms"], 5600
        )
        self.assertEqual(
            assessment["runtime_cell_assessment"]["blocked_arms"], 0
        )

        tampered = copy.deepcopy(grant)
        tampered["production_output_receipt_protocol"]["protocol_files"][
            "production_output_transaction"
        ]["sha256"] = "f" * 64
        result = validate_full_publication_readiness(
            load_config(), backend_runtime_grant=tampered,
        )
        self.assertFalse(
            result["backend_launcher_output_receipt_protocol_ready"]
        )
        self.assertEqual(result["runtime_cell_assessment"]["ready_arms"], 0)

    def test_full_matrix_is_deterministic_complete_and_paired(self) -> None:
        config = load_config()
        first = build_full_publication_matrix(config)
        second = build_full_publication_matrix(config)

        self.assertEqual(first, second)
        self.assertEqual(first["schema_version"], 3)
        self.assertEqual(first["publication_scope"], FULL_RESOURCE_PUBLICATION_SCOPE)
        self.assertEqual(first["policies"], list(POLICIES))
        self.assertEqual(
            first["policy_contract_identity"],
            policy_contract_identity(),
        )
        self.assertEqual(first["expected_pairs"], 2800)
        self.assertEqual(first["expected_arms"], 5600)
        self.assertEqual(
            set(first["systems"]),
            {"deepstream", "savant", "openvino_gva", "gstreamer_custom"},
        )
        self.assertEqual(set(first["codecs"]), {"h264", "h265"})
        self.assertEqual(
            DATASET_BY_CODEC,
            {
                "h264": "kpp_iss_publication_v3_h264",
                "h265": "kpp_iss_publication_v3_h265",
            },
        )
        self.assertEqual(
            {pair["dataset"] for pair in first["pairs"]},
            set(DATASET_BY_CODEC.values()),
        )
        self.assertEqual(len(first["pairs"]), 2800)
        self.assertEqual(len({pair["pair_id"] for pair in first["pairs"]}), 2800)
        self.assertEqual(
            len({arm["arm_id"] for pair in first["pairs"] for arm in pair["arms"]}),
            5600,
        )

        for pair in first["pairs"]:
            self.assertEqual(len(pair["arms"]), 2)
            self.assertEqual(
                {arm["scenario"] for arm in pair["arms"]},
                {
                    "checkpoint_independent_processes_baseline",
                    "checkpoint_video_dag_shared",
                },
            )
            for arm in pair["arms"]:
                self.assertEqual(arm["warmup_s"], 30)
                self.assertEqual(arm["measurement_s"], 180)
                self.assertEqual(arm["streams"], 6)

        identity = publication_matrix_identity(first)
        self.assertEqual(identity["schema_version"], 3)
        self.assertRegex(identity["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(identity, publication_matrix_identity(second))

        drifted = copy.deepcopy(config)
        drifted["benchmark"]["scheduler_policies"][-1] = "invented_policy"
        with self.assertRaisesRegex(ContractError, "frozen policy contract"):
            build_full_publication_matrix(drifted)

    def test_current_config_fails_closed_until_all_v2_gates_are_ready(self) -> None:
        assessment = validate_full_publication_readiness(load_config())

        self.assertFalse(assessment["passed"])
        self.assertFalse(any(blocker.startswith("scenario:") for blocker in assessment["blockers"]))
        self.assertIn(
            "pre_run_resource_capability_qualification_missing",
            assessment["blockers"],
        )
        self.assertTrue(
            any(
                blocker.startswith("pre_run_model_parity_grant:")
                for blocker in assessment["blockers"]
            )
        )
        self.assertTrue(
            any(
                blocker.startswith("pre_run_backend_runtime_grant:")
                for blocker in assessment["blockers"]
            )
        )
        self.assertIn(
            "publication_policy_capability_manifest_missing",
            assessment["blockers"],
        )
        runtime = assessment["runtime_cell_assessment"]
        self.assertEqual(runtime["assessed_arms"], 5600)
        self.assertGreater(runtime["blocked_arms"], 0)
        self.assertEqual(runtime["blocked_by_system"]["deepstream"], 1400)
        self.assertTrue(
            any(
                blocker.startswith("checkpoint_runtime_cells_blocked:")
                for blocker in assessment["blockers"]
            )
        )

    def test_readiness_uses_exact_pre_run_grant_and_preserves_post_run_false(self) -> None:
        config = copy.deepcopy(load_config())
        for scenario_name in (
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        ):
            config["scenarios"][scenario_name]["benchmark_status"] = "supported"
            config["scenarios"][scenario_name].pop("benchmark_reason", None)
        extension = config["benchmark"]["resource_interval_extension"]
        self.assertFalse(extension["publication_bundle_bound"])
        self.assertFalse(extension["evidence_accepted"])

        assessment = validate_full_publication_readiness(
            config,
            resource_capability_grant=resource_capability_grant(),
            backend_runtime_grant=backend_runtime_grant_from_identity_artifacts(
                v2_identity()
            ),
            model_parity_grant=model_parity_grant_from_identity_artifacts(
                parity_identity()
            ),
        )
        self.assertFalse(assessment["passed"])
        self.assertNotIn(
            "pre_run_resource_capability_qualification_missing",
            assessment["blockers"],
        )
        self.assertFalse(
            any(blocker.startswith("pre_run_resource_capability_grant_") for blocker in assessment["blockers"])
        )
        self.assertTrue(assessment["pre_run_model_parity_grant_assessment"]["passed"])
        self.assertIn(
            "publication_policy_capability_manifest_missing",
            assessment["blockers"],
        )
        self.assertEqual(
            assessment["runtime_cell_assessment"]["ready_arms"], 0
        )
        self.assertEqual(
            assessment["runtime_cell_assessment"]["blocked_arms"], 5600
        )
        self.assertFalse(
            assessment["backend_launcher_output_receipt_protocol_ready"]
        )

        drifted = copy.deepcopy(config)
        drifted["benchmark"]["resource_interval_extension"]["counter_scope"] = "estimated"
        with self.assertRaisesRegex(ContractError, "counter_scope"):
            validate_full_publication_readiness(
                drifted,
                resource_capability_grant=resource_capability_grant(),
                backend_runtime_grant=backend_runtime_grant_from_identity_artifacts(
                    v2_identity()
                ),
            )

    def test_exact_backend_grant_stays_blocked_until_output_receipt_protocol(self) -> None:
        assessment = validate_full_publication_readiness(
            load_config(),
            resource_capability_grant=resource_capability_grant(),
            backend_runtime_grant=backend_runtime_grant_from_identity_artifacts(
                v2_identity()
            ),
        )
        runtime = assessment["runtime_cell_assessment"]
        self.assertEqual(runtime["assessed_arms"], 5600)
        self.assertEqual(runtime["ready_arms"], 0)
        self.assertEqual(runtime["blocked_arms"], 5600)
        self.assertEqual(
            runtime["blocked_by_system"],
            {
                "deepstream": 1400,
                "gstreamer_custom": 1400,
                "openvino_gva": 1400,
                "savant": 1400,
            },
        )
        self.assertIn(
            "backend_launcher_output_receipt_protocol_not_implemented",
            runtime["blocker_counts"],
        )

    def test_backend_grant_missing_cell_or_launcher_invocation_drift_blocks_arms(self) -> None:
        grant = backend_runtime_grant_from_identity_artifacts(v2_identity())
        missing = copy.deepcopy(grant)
        missing["systems"]["deepstream"]["qualified_cells"].pop()
        missing.pop("grant_sha256")
        missing["grant_sha256"] = hashlib.sha256(
            json.dumps(
                missing,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        result = validate_full_publication_readiness(
            load_config(), backend_runtime_grant=missing
        )
        self.assertEqual(result["runtime_cell_assessment"]["ready_arms"], 0)

        drifted = copy.deepcopy(grant)
        drifted["systems"]["deepstream"]["launcher_invocation"][
            "runtime_kind"
        ] = "shell"
        drifted.pop("grant_sha256")
        drifted["grant_sha256"] = hashlib.sha256(
            json.dumps(
                drifted,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode()
        ).hexdigest()
        result = validate_full_publication_readiness(
            load_config(), backend_runtime_grant=drifted
        )
        self.assertEqual(result["runtime_cell_assessment"]["ready_arms"], 0)

    def test_readiness_rejects_drifted_pre_run_grant(self) -> None:
        grant = resource_capability_grant()
        grant["publication_scope"] = "self_declared_scope"

        assessment = validate_full_publication_readiness(
            load_config(),
            resource_capability_grant=grant,
        )

        self.assertFalse(assessment["passed"])
        self.assertIn(
            "pre_run_resource_capability_grant_publication_scope_mismatch",
            assessment["blockers"],
        )

    def test_readiness_rejects_missing_or_tampered_model_parity_grant(self) -> None:
        missing = validate_full_publication_readiness(load_config())
        self.assertFalse(missing["pre_run_model_parity_grant_assessment"]["passed"])
        self.assertTrue(
            any(value.startswith("pre_run_model_parity_grant:") for value in missing["blockers"])
        )
        grant = model_parity_grant_from_identity_artifacts(parity_identity())
        grant["evidence_count"] = 31
        grant.pop("grant_sha256")
        grant["grant_sha256"] = hashlib.sha256(
            json.dumps(grant, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
        ).hexdigest()
        tampered = validate_full_publication_readiness(
            load_config(), model_parity_grant=grant
        )
        self.assertFalse(tampered["pre_run_model_parity_grant_assessment"]["passed"])


if __name__ == "__main__":
    unittest.main()
