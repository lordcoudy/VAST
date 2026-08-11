from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from publication_matrix import (  # noqa: E402
    FULL_RESOURCE_PUBLICATION_SCOPE,
    build_full_publication_matrix,
    publication_matrix_identity,
    validate_full_publication_readiness,
)


def load_config() -> dict:
    with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
        return yaml.safe_load(source)


class PublicationMatrixTests(unittest.TestCase):
    def test_full_matrix_is_deterministic_complete_and_paired(self) -> None:
        config = load_config()
        first = build_full_publication_matrix(config)
        second = build_full_publication_matrix(config)

        self.assertEqual(first, second)
        self.assertEqual(first["publication_scope"], FULL_RESOURCE_PUBLICATION_SCOPE)
        self.assertEqual(first["expected_pairs"], 2800)
        self.assertEqual(first["expected_arms"], 5600)
        self.assertEqual(
            set(first["systems"]),
            {"deepstream", "savant", "openvino_gva", "gstreamer_custom"},
        )
        self.assertEqual(set(first["codecs"]), {"h264", "h265"})
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
        self.assertEqual(identity["schema_version"], 1)
        self.assertRegex(identity["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(identity, publication_matrix_identity(second))

    def test_current_config_fails_closed_until_all_v2_gates_are_ready(self) -> None:
        assessment = validate_full_publication_readiness(load_config())

        self.assertFalse(assessment["passed"])
        self.assertFalse(any(blocker.startswith("scenario:") for blocker in assessment["blockers"]))
        self.assertIn("full_resource_publication_scope_not_active", assessment["blockers"])

    def test_readiness_accepts_only_exact_v2_contract(self) -> None:
        config = copy.deepcopy(load_config())
        for scenario_name in (
            "checkpoint_independent_processes_baseline",
            "checkpoint_video_dag_shared",
        ):
            config["scenarios"][scenario_name]["benchmark_status"] = "supported"
            config["scenarios"][scenario_name].pop("benchmark_reason", None)
        extension = config["benchmark"]["resource_interval_extension"]
        extension["status"] = "accepted_full_resource_publication_v2"
        extension["current_publication_bundle_scope"] = FULL_RESOURCE_PUBLICATION_SCOPE
        extension["publication_bundle_bound"] = True
        extension["evidence_accepted"] = True
        extension["true_nvdec_busy_status"] = "device_level_nvml_sampled"
        extension["fanout_resource_work_status"] = "native_cpu_thread_time_sampled"

        assessment = validate_full_publication_readiness(config)
        self.assertTrue(assessment["passed"], assessment["blockers"])

        drifted = copy.deepcopy(config)
        drifted["benchmark"]["resource_interval_extension"]["counter_scope"] = "estimated"
        with self.assertRaisesRegex(ContractError, "counter_scope"):
            validate_full_publication_readiness(drifted)


if __name__ == "__main__":
    unittest.main()
