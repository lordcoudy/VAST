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
        scenario = {"name": "checkpoint_video_dag_shared", "workload": {}}

        self.assertEqual(
            run_directory(Path("runs/root"), scenario, 6, "openvino_gva", 5),
            Path("runs/root/checkpoint_video_dag_shared/streams_6/openvino_gva/rep_05"),
        )
        self.assertEqual(
            run_directory(Path("runs/root"), scenario, 6, "openvino_gva", 5, 16.7),
            Path("runs/root/checkpoint_video_dag_shared/streams_6/deadline_16p7/openvino_gva/rep_05"),
        )

    def test_load_resumable_result_accepts_matching_completed_metadata(self) -> None:
        result = {
            "status": "completed",
            "system": "openvino_gva",
            "scenario": "checkpoint_video_dag_shared",
            "repeat": 5,
            "streams": 6,
            "duration_s": 180,
            "policy": "cpu_only",
            "dataset": "kpp_real_avi",
            "deadline_ms": 16.7,
        }
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(json.dumps({"result": result}), encoding="utf-8")

            self.assertEqual(
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="kpp_real_avi",
                    deadline_ms=16.7,
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
                            "scenario": "checkpoint_video_dag_shared",
                            "repeat": 1,
                            "streams": 6,
                            "duration_s": 180,
                            "policy": "gpu_only",
                            "dataset": "kpp_real_avi",
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, "does not match requested run.*repeat.*policy"):
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="kpp_real_avi",
                )


if __name__ == "__main__":
    unittest.main()
