from __future__ import annotations

import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_openvino_gva_qualification_fragment_v3 as target  # noqa: E402


RESOURCE_FIELDS = {
    "process_cpu_time_ns",
    "rss_before_bytes",
    "rss_after_bytes",
    "accelerator_memory_bytes",
    "cuda_h2d_bytes",
    "cuda_d2h_bytes",
    "cuda_transfer_intervals",
}
INTERVAL_FIELDS = {
    "direction",
    "host_start_monotonic_ns",
    "host_end_monotonic_ns",
    "device_elapsed_ns",
    "bytes",
    "device_id",
    "timing_source",
}


class OpenVINOGVAQualificationFragmentV3Tests(unittest.TestCase):
    def _materialize(self, temporary: str) -> tuple[Path, dict[str, object]]:
        output = Path(temporary).resolve() / "qualification"
        result = target.materialize_qualification_fragment(
            project_root=ROOT,
            output_dir=output,
        )
        return output, result

    def test_phase_one_materializes_exact_policy_and_resource_bindings(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output, result = self._materialize(temporary)
            fragment_path = output / target.FRAGMENT_FILENAME
            self.assertEqual(result["fragment_path"], fragment_path)
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            self.assertEqual(fragment["system"], "openvino_gva")
            self.assertEqual(fragment["pilots"], [])
            self.assertEqual(len(fragment["policy_bindings"]), 8)
            self.assertEqual(len(fragment["resource_bindings"]), 2)
            self.assertEqual(
                {(row["branch"], row["resource"]) for row in fragment["policy_bindings"]},
                {
                    (branch, resource)
                    for branch in target.BRANCHES
                    for resource in target.RESOURCES
                },
            )
            paths: set[str] = set()
            inodes: set[tuple[int, int]] = set()
            for row in (*fragment["policy_bindings"], *fragment["resource_bindings"]):
                self.assertEqual(set(row), target.ROW_FIELDS)
                path = ROOT / row["path"]
                info = path.lstat()
                self.assertTrue(stat.S_ISREG(info.st_mode))
                self.assertFalse(path.is_symlink())
                self.assertEqual(info.st_nlink, 1)
                self.assertNotIn(row["path"], paths)
                self.assertNotIn((info.st_dev, info.st_ino), inodes)
                paths.add(row["path"])
                inodes.add((info.st_dev, info.st_ino))
            assessment = target.assess_qualification_fragment(
                project_root=ROOT,
                fragment_path=fragment_path,
            )
            self.assertTrue(assessment["passed"], assessment["blockers"])

    def test_policy_identity_is_the_external_worker_and_topology_v2_is_invariant(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output, _ = self._materialize(temporary)
            fragment = json.loads(
                (output / target.FRAGMENT_FILENAME).read_text(encoding="utf-8")
            )
            for row in fragment["policy_bindings"]:
                artifact = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
                binding = artifact["analytics_execution_worker_binding_identity"]
                identity = row["runtime_identity"]
                self.assertEqual(set(identity), target.POLICY_RUNTIME_FIELDS)
                self.assertEqual(identity["worker_image_digest"], binding["worker_image_id"])
                self.assertEqual(identity["terminal_detector"], binding["model_id"])
                self.assertIn("analytics-execution:", identity["terminal_backend"])
                self.assertNotIn("gvadetect", identity["terminal_backend"].lower())
                if row["resource"] == "cpu":
                    self.assertEqual(identity["device_api"], "CPU")
                    self.assertIsNone(identity["gpu_id"])
                    self.assertTrue(identity["terminal_backend"].endswith(";device=CPU"))
                else:
                    self.assertEqual(identity["device_api"], "NVIDIA_CUDA")
                    self.assertEqual(identity["gpu_id"], 0)
                    self.assertTrue(
                        identity["terminal_backend"].endswith(";device=NVIDIA_CUDA:0")
                    )
                topology = artifact["topology_contract"]
                self.assertEqual(topology["contract_version"], 2)
                self.assertEqual(
                    topology["terminal_chain"],
                    [row["branch"], f"postprocess_{row['branch']}", "branch_complete"],
                )
                self.assertEqual(topology["postprocess_resource"], "HOST_CPU")
                self.assertTrue(topology["invariant_across_cpu_gpu_selection"])

    def test_exact_worker_receipt_and_resource_v2_evidence_are_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output, _ = self._materialize(temporary)
            fragment = json.loads(
                (output / target.FRAGMENT_FILENAME).read_text(encoding="utf-8")
            )
            for row in fragment["policy_bindings"]:
                artifact = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
                receipt = artifact["analytics_execution_resource_receipt_contract"]
                self.assertEqual(set(receipt["fields"]), RESOURCE_FIELDS)
                self.assertEqual(set(receipt["cuda_interval_fields"]), INTERVAL_FIELDS)
                if row["resource"] == "cpu":
                    self.assertEqual(receipt["cuda_transfer_intervals"], "exact_empty")
                else:
                    self.assertEqual(receipt["cuda_interval_order"], ["h2d", "d2h"])
                    self.assertEqual(
                        receipt["execution_stage_binding"],
                        {"h2d": row["branch"], "d2h": f"postprocess_{row['branch']}"},
                    )
            for row in fragment["resource_bindings"]:
                artifact = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
                evidence = artifact["resource_v2_evidence"]
                self.assertEqual(evidence["contract_version"], 2)
                self.assertEqual(evidence["decoder_device_api"], "NVIDIA_NVDEC")
                self.assertIn("nvdec_intervals", evidence["native_emitters"])
                self.assertIn("fanout_intervals", evidence["native_emitters"])
                self.assertIn("fanout_work_counters", evidence["native_emitters"])


if __name__ == "__main__":
    unittest.main()
