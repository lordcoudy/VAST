from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from run_experiments import load_resumable_result, run_directory  # noqa: E402


class RunExperimentsResumeTests(unittest.TestCase):
    def test_run_directory_matches_canonical_layout(self) -> None:
        scenario = {"name": "canonical_heterogeneous", "workload": {}}

        self.assertEqual(
            run_directory(Path("runs/root"), scenario, 6, "openvino_gva", 5),
            Path("runs/root/canonical_heterogeneous/streams_6/openvino_gva/rep_05"),
        )

    def test_load_resumable_result_accepts_matching_completed_metadata(self) -> None:
        result = {
            "status": "completed",
            "system": "openvino_gva",
            "scenario": "canonical_heterogeneous",
            "repeat": 5,
            "streams": 6,
            "duration_s": 180,
            "policy": "cpu_only",
            "dataset": "mot17_uadetrac_public",
        }
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(json.dumps({"result": result}), encoding="utf-8")

            self.assertEqual(
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="canonical_heterogeneous",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="mot17_uadetrac_public",
                ),
                result,
            )

    def test_load_resumable_result_rejects_incompatible_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "result": {
                            "status": "completed",
                            "system": "openvino_gva",
                            "scenario": "canonical_heterogeneous",
                            "repeat": 1,
                            "streams": 6,
                            "duration_s": 180,
                            "policy": "gpu_only",
                            "dataset": "mot17_uadetrac_public",
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, "does not match requested run.*repeat.*policy"):
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="canonical_heterogeneous",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="mot17_uadetrac_public",
                )


if __name__ == "__main__":
    unittest.main()
