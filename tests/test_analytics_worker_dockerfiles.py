from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
OPENVINO_BASE_ID = (
    "sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1"
)
TENSORRT_BASE_ID = (
    "sha256:16d284eb311f04a95f148746f0dc5637d54d527cc42be9a6cced5fcf0240770c"
)


class AnalyticsWorkerDockerfileTests(unittest.TestCase):
    def _assert_reproducible_final_stage(self, name: str, base_id: str) -> None:
        path = ROOT / "deploy" / "analytics_execution" / name
        source = path.read_text(encoding="utf-8")
        self.assertIn("ARG SOURCE_DATE_EPOCH=0", source)
        self.assertIn("AS worker_builder", source)
        self.assertEqual(source.count("FROM ${BASE_IMAGE}"), 2)
        self.assertIn(f"ARG EXPECTED_BASE_IMAGE_ID={base_id}", source)
        self.assertIn('touch -h -d "@${SOURCE_DATE_EPOCH}"', source)
        final_stage = source.rsplit("FROM ${BASE_IMAGE}", maxsplit=1)[1]
        self.assertNotIn("\nRUN ", final_stage)
        self.assertEqual(final_stage.count("\nCOPY --from=worker_builder "), 1)

    def test_openvino_worker_has_one_normalized_final_copy_layer(self) -> None:
        self._assert_reproducible_final_stage(
            "Dockerfile.openvino", OPENVINO_BASE_ID
        )

    def test_tensorrt_worker_has_one_normalized_final_copy_layer(self) -> None:
        self._assert_reproducible_final_stage(
            "Dockerfile.tensorrt", TENSORRT_BASE_ID
        )


if __name__ == "__main__":
    unittest.main()
