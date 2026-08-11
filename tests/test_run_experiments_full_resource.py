from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import FULL_RESOURCE_PUBLICATION_SCOPE  # noqa: E402
from collect_metrics import HardwareResourceCollector  # noqa: E402
from run_experiments import make_hardware_resource_collector, summary_fieldnames  # noqa: E402


def load_config() -> dict:
    with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
        return yaml.safe_load(source)


class RunExperimentsFullResourceTests(unittest.TestCase):
    def test_summary_schema_exposes_article_ready_v2_resource_metrics(self) -> None:
        expected = {
            "full_resource_evidence_accepted",
            "full_resource_coverage_complete",
            "resource_contract_version",
            "nvdec_busy_equivalent_ns",
            "nvdec_counter_scope",
            "fanout_thread_cpu_time_ns",
            "fanout_work_units",
            "fanout_counter_scope",
        }
        self.assertTrue(expected.issubset(summary_fieldnames()))
    def test_collector_is_disabled_until_v2_scope_is_accepted(self) -> None:
        config = load_config()
        with tempfile.TemporaryDirectory() as tmp:
            collector = make_hardware_resource_collector(
                config,
                mode="benchmark",
                system="deepstream",
                scenario=config["scenarios"]["checkpoint_video_dag_shared"],
                scenario_name="checkpoint_video_dag_shared",
                policy="adaptive_weights",
                run_dir=Path(tmp),
                run_id="run-1",
                interval_s=1.0,
            )
        self.assertIsNone(collector)

    def test_accepted_v2_scope_binds_collector_to_exact_sidecar(self) -> None:
        config = copy.deepcopy(load_config())
        extension = config["benchmark"]["resource_interval_extension"]
        extension["status"] = "accepted_full_resource_publication_v2"
        extension["current_publication_bundle_scope"] = FULL_RESOURCE_PUBLICATION_SCOPE
        extension["publication_bundle_bound"] = True
        extension["evidence_accepted"] = True
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            collector = make_hardware_resource_collector(
                config,
                mode="benchmark",
                system="deepstream",
                scenario=config["scenarios"]["checkpoint_video_dag_shared"],
                scenario_name="checkpoint_video_dag_shared",
                policy="adaptive_weights",
                run_dir=root,
                run_id="run-1",
                interval_s=1.0,
            )

            self.assertIsInstance(collector, HardwareResourceCollector)
            assert collector is not None
            self.assertEqual(collector.output_csv, root / "hardware_resource_samples.csv")
            self.assertEqual(collector.run_id, "run-1")


if __name__ == "__main__":
    unittest.main()
